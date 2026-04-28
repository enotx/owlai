# backend/app/services/cleanup.py
"""
Task 资源清理服务
- 删除时清理：delete_task_files()
- 启动时兜底：cleanup_orphaned_files()
"""

import logging
import shutil
from pathlib import Path

from app.config import TEMP_DIR
from app.tenant_context import get_uploads_dir

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 删除时清理（由 delete_task API 调用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def delete_task_files(task_id: str, knowledge_file_paths: list[str]) -> None:
    """
    同步清理 Task 关联的磁盘文件。
    由 BackgroundTasks 在后台线程池调用，不阻塞 API。
    """
    uploads_resolved = get_uploads_dir().resolve()

    # ── 删除 Knowledge 上传文件 ──────────────────────────
    for fpath_str in knowledge_file_paths:
        try:
            p = Path(fpath_str).resolve()
            if not str(p).startswith(str(uploads_resolved)):
                logger.warning(f"Skipped file outside UPLOADS_DIR: {fpath_str}")
                continue
            if p.is_file():
                p.unlink()
                logger.debug(f"Deleted knowledge file: {fpath_str}")
        except Exception as e:
            logger.warning(f"Failed to delete knowledge file {fpath_str}: {e}")

    # ── 删除 Task 目录 (captures / persist / charts / maps) ──
    task_dir = get_uploads_dir() / task_id
    _safe_rmtree(task_dir, uploads_resolved)

    # ── 清理空父目录 ────────────────────────────────────
    for fpath_str in knowledge_file_paths:
        try:
            parent = Path(fpath_str).resolve().parent
            if (
                parent != uploads_resolved
                and str(parent).startswith(str(uploads_resolved))
                and parent.is_dir()
                and not any(parent.iterdir())
            ):
                parent.rmdir()
        except Exception:
            pass

    logger.info(f"Task {task_id} file cleanup completed")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 启动时孤儿清理（由 main.py lifespan 调用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cleanup_orphaned_files() -> dict:
    """
    扫描 UPLOADS_DIR 和 TEMP_DIR，删除数据库中不存在的 Task 的残留文件。
    
    策略：以 DB 为权威数据源
    - UPLOADS_DIR 下形如 UUID 的子目录 → 检查 tasks 表
    - TEMP_DIR 下超过 24h 的文件 → 无条件清理
    
    Returns:
        {"orphaned_dirs_removed": int, "temp_files_removed": int, "bytes_freed": int}
    """
    import re
    import time
    from app.database import async_session
    from sqlalchemy import text

    stats = {"orphaned_dirs_removed": 0, "temp_files_removed": 0, "bytes_freed": 0}

    # ── 2a. 收集数据库中所有存活的 task_id ──────────────
    live_task_ids: set[str] = set()
    try:
        async with async_session() as session:
            result = await session.execute(text("SELECT id FROM tasks"))
            live_task_ids = {row[0] for row in result.fetchall()}
    except Exception as e:
        logger.error(f"Failed to query live task IDs, skipping orphan cleanup: {e}")
        return stats

    # ── 2b. 扫描 UPLOADS_DIR 下的 task 目录 ─────────────
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )
    uploads_resolved = get_uploads_dir().resolve()

    if get_uploads_dir().exists():
        for child in get_uploads_dir().iterdir():
            if not child.is_dir():
                continue
            if not uuid_pattern.match(child.name):
                continue
            if child.name in live_task_ids:
                continue

            # 孤儿目录 → 清理
            freed = _dir_size(child)
            if _safe_rmtree(child, uploads_resolved):
                stats["orphaned_dirs_removed"] += 1
                stats["bytes_freed"] += freed
                logger.info(f"Removed orphaned task dir: {child.name} ({freed} bytes)")

    # ── 2c. 清理 TEMP_DIR 中超过 24h 的文件 ─────────────
    max_age_seconds = 24 * 3600
    now = time.time()

    if TEMP_DIR.exists():
        for item in TEMP_DIR.iterdir():
            try:
                age = now - item.stat().st_mtime
                if age < max_age_seconds:
                    continue
                freed = item.stat().st_size if item.is_file() else _dir_size(item)
                if item.is_file():
                    item.unlink()
                    stats["temp_files_removed"] += 1
                    stats["bytes_freed"] += freed
                elif item.is_dir():
                    if _safe_rmtree(item, TEMP_DIR.resolve()):
                        stats["temp_files_removed"] += 1
                        stats["bytes_freed"] += freed
            except Exception as e:
                logger.warning(f"Failed to clean temp item {item}: {e}")

    # ── 2d. 清理 UPLOADS_DIR 下孤立的 Knowledge 文件 ────
    # Knowledge 文件可能直接在 UPLOADS_DIR 根下（旧版行为）
    # 收集所有仍在 DB 中的 file_path
    try:
        async with async_session() as session:
            result = await session.execute(
                text("SELECT file_path FROM knowledge WHERE file_path IS NOT NULL")
            )
            live_file_paths = {
                str(Path(row[0]).resolve())
                for row in result.fetchall()
                if row[0]
            }
    except Exception as e:
        logger.warning(f"Failed to query knowledge file paths: {e}")
        live_file_paths = set()

    if get_uploads_dir().exists() and live_file_paths is not None:
        for child in get_uploads_dir().iterdir():
            if not child.is_file():
                continue
            resolved = str(child.resolve())
            if resolved not in live_file_paths:
                try:
                    freed = child.stat().st_size
                    child.unlink()
                    stats["temp_files_removed"] += 1
                    stats["bytes_freed"] += freed
                    logger.debug(f"Removed orphaned upload: {child.name}")
                except Exception as e:
                    logger.warning(f"Failed to remove orphaned upload {child}: {e}")

    logger.info(
        f"Orphan cleanup done: {stats['orphaned_dirs_removed']} dirs, "
        f"{stats['temp_files_removed']} temp files, "
        f"{stats['bytes_freed'] / 1024 / 1024:.1f} MB freed"
    )
    return stats


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Internal helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _safe_rmtree(target: Path, allowed_root: Path) -> bool:
    """安全删除目录，校验路径必须在 allowed_root 内"""
    try:
        resolved = target.resolve()
        if not str(resolved).startswith(str(allowed_root)):
            logger.warning(f"Refused to delete outside allowed root: {target}")
            return False
        if resolved == allowed_root:
            logger.warning(f"Refused to delete root dir itself: {target}")
            return False
        if target.exists():
            shutil.rmtree(target)
            return True
    except Exception as e:
        logger.warning(f"Failed to rmtree {target}: {e}")
    return False


def _dir_size(path: Path) -> int:
    """递归计算目录大小（字节），出错返回 0"""
    try:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except Exception:
        return 0