# backend/app/database.py

"""数据库连接与会话管理"""

import json

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select, text
from app.config import DATA_DIR
import os
import logging

logger = logging.getLogger(__name__)

# 使用动态路径（桌面模式 → AppData，云端模式 → /app/data）
db_path = DATA_DIR / "owl.db"
DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass



# ===== Schema Migration (in-app) =====
# 使用 SQLite PRAGMA user_version 记录 schema 版本，避免外部迁移脚本依赖
LATEST_SCHEMA_VERSION = 12
# v2: multi-agent (tasks.mode/plan_confirmed/current_subtask_id + subtasks + steps.subtask_id)
# v3: visualization (visualizations table)
# v4: skill reference_markdown (lazy-loaded reference doc)
# v5: duckdb_tables + data_pipelines
# v6: data_pipelines.freshness_policy_json + duckdb_tables.query_transform_code
# v7: skills.is_system + skills.slash_command
# v8: skills.handler_type + skills.handler_config (支持 custom_handler 类型的 Skill)
# v9: assets table + task.task_type/asset_id/last_run_*
# v10: tasks.compact_context + tasks.compact_anchor_step_id + tasks.compact_anchor_created_at
# v11: tasks.data_source_ids (执行输入绑定)
# v12: tasks.pipeline_id (pipeline task binds DataPipeline instead of Asset)


async def _get_user_version(conn) -> int:
    """读取 SQLite schema 版本（PRAGMA user_version）"""
    res = await conn.execute(text("PRAGMA user_version"))
    row = res.fetchone()
    return int(row[0]) if row else 0


async def _set_user_version(conn, version: int) -> None:
    """写入 SQLite schema 版本（PRAGMA user_version）"""
    await conn.execute(text(f"PRAGMA user_version = {int(version)}"))


async def _table_exists(conn, table_name: str) -> bool:
    res = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table_name},
    )
    return res.fetchone() is not None


async def _get_table_columns(conn, table_name: str) -> set[str]:
    """返回表的列名集合；表不存在则返回空集合"""
    if not await _table_exists(conn, table_name):
        return set()
    res = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    return {str(r[1]) for r in res.fetchall()}  # r[1] is column name


async def upgrade_db_schema() -> dict:
    """
    应用内迁移：按 user_version 增量升级数据库结构（不丢数据）。
    返回：
      { success: bool, from_version: int, to_version: int, applied: list[str], error?: str }
    """
    applied: list[str] = []
    try:
        async with engine.begin() as conn:
            from_version = await _get_user_version(conn)

            # user_version = 0 的情况：
            # - 可能是全新库（无表）
            # - 也可能是旧库但从未设置版本
            # 我们通过“是否存在 tasks 表”来做启发式判断：
            # 若 tasks 不存在，则走 create_all 后直接设置最新版本（无需逐步迁移）
            tasks_exists = await _table_exists(conn, "tasks")
            if not tasks_exists:
                # 全新库：先创建所有表（create_all），再设置版本
                await conn.run_sync(Base.metadata.create_all)
                await _set_user_version(conn, LATEST_SCHEMA_VERSION)
                applied.append(f"create_all → set user_version={LATEST_SCHEMA_VERSION}")
                return {
                    "success": True,
                    "from_version": from_version,
                    "to_version": LATEST_SCHEMA_VERSION,
                    "applied": applied,
                }

            # 如果是旧库但 user_version=0，我们假设它属于 v1（早期版本）
            current = from_version or 1

            # ── v2 migration: multi-agent fields + subtasks table + steps.subtask_id ──
            if current < 2:
                # tasks 表补列
                task_cols = await _get_table_columns(conn, "tasks")
                if "mode" not in task_cols:
                    await conn.execute(text("ALTER TABLE tasks ADD COLUMN mode VARCHAR(20) NOT NULL DEFAULT 'analyst'"))
                    applied.append("ALTER TABLE tasks ADD COLUMN mode")
                if "plan_confirmed" not in task_cols:
                    await conn.execute(text("ALTER TABLE tasks ADD COLUMN plan_confirmed BOOLEAN NOT NULL DEFAULT 0"))
                    applied.append("ALTER TABLE tasks ADD COLUMN plan_confirmed")
                if "current_subtask_id" not in task_cols:
                    await conn.execute(text("ALTER TABLE tasks ADD COLUMN current_subtask_id VARCHAR(36)"))
                    applied.append("ALTER TABLE tasks ADD COLUMN current_subtask_id")

                # subtasks 表（若不存在则创建）
                if not await _table_exists(conn, "subtasks"):
                    await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS subtasks (
                        id VARCHAR(36) PRIMARY KEY,
                        task_id VARCHAR(36) NOT NULL,
                        title VARCHAR(255) NOT NULL,
                        description TEXT,
                        "order" INTEGER NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        result TEXT,
                        created_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
                        updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
                        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                    )
                    """))
                    # 常用索引（按你的约束：task_id/status）
                    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_subtasks_task_id ON subtasks(task_id)"))
                    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_subtasks_status ON subtasks(status)"))
                    applied.append("CREATE TABLE subtasks + indexes")

                # steps 表补 subtask_id 列（向后兼容）
                steps_cols = await _get_table_columns(conn, "steps")
                if "subtask_id" not in steps_cols:
                    await conn.execute(text("ALTER TABLE steps ADD COLUMN subtask_id VARCHAR(36)"))
                    applied.append("ALTER TABLE steps ADD COLUMN subtask_id")

                # 设置版本到 2
                await _set_user_version(conn, 2)
                applied.append("set user_version=2")
                current = 2

            # ── v3 migration: visualizations table ──
            if current < 3:
                if not await _table_exists(conn, "visualizations"):
                    await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS visualizations (
                        id VARCHAR(36) PRIMARY KEY,
                        task_id VARCHAR(36) NOT NULL,
                        subtask_id VARCHAR(36),
                        step_id VARCHAR(36),
                        title VARCHAR(255) NOT NULL,
                        chart_type VARCHAR(50) NOT NULL,
                        option_json TEXT NOT NULL,
                        created_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
                        updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
                        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                        FOREIGN KEY(subtask_id) REFERENCES subtasks(id) ON DELETE SET NULL,
                        FOREIGN KEY(step_id) REFERENCES steps(id) ON DELETE SET NULL
                    )
                    """))
                    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_visualizations_task_id ON visualizations(task_id)"))
                    applied.append("CREATE TABLE visualizations + index")

                await _set_user_version(conn, 3)
                applied.append("set user_version=3")
                current = 3

            # ── v4 migration: skills.reference_markdown ──
            if current < 4:
                skills_cols = await _get_table_columns(conn, "skills")
                if "reference_markdown" not in skills_cols:
                    await conn.execute(text("ALTER TABLE skills ADD COLUMN reference_markdown TEXT"))
                    applied.append("ALTER TABLE skills ADD COLUMN reference_markdown")
                await _set_user_version(conn, 4)
                applied.append("set user_version=4")
                current = 4

            # ── v5 migration: duckdb_tables + data_pipelines ──
            if current < 5:
                # data_pipelines 表（需先创建，因为 duckdb_tables 引用它）
                if not await _table_exists(conn, "data_pipelines"):
                    await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS data_pipelines (
                        id VARCHAR(36) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        description TEXT,
                        source_task_id VARCHAR(36),
                        source_type VARCHAR(50) NOT NULL,
                        source_config TEXT NOT NULL DEFAULT '{}',
                        transform_code TEXT NOT NULL,
                        transform_description TEXT,
                        target_table_name VARCHAR(255) NOT NULL,
                        write_strategy VARCHAR(20) NOT NULL DEFAULT 'replace',
                        upsert_key VARCHAR(255),
                        output_schema TEXT,
                        is_auto BOOLEAN NOT NULL DEFAULT 0,
                        status VARCHAR(20) NOT NULL DEFAULT 'draft',
                        last_run_at DATETIME,
                        last_run_status VARCHAR(20),
                        last_run_error TEXT,
                        created_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
                        updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
                        FOREIGN KEY(source_task_id) REFERENCES tasks(id) ON DELETE SET NULL
                    )
                    """))
                    applied.append("CREATE TABLE data_pipelines")

                # duckdb_tables 表
                if not await _table_exists(conn, "duckdb_tables"):
                    await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS duckdb_tables (
                        id VARCHAR(36) PRIMARY KEY,
                        table_name VARCHAR(255) NOT NULL UNIQUE,
                        display_name VARCHAR(255) NOT NULL,
                        description TEXT,
                        table_schema_json TEXT NOT NULL DEFAULT '[]',
                        row_count INTEGER NOT NULL DEFAULT 0,
                        source_type VARCHAR(50) NOT NULL DEFAULT 'unknown',
                        source_config TEXT,
                        pipeline_id VARCHAR(36),
                        data_updated_at DATETIME,
                        latest_data_date VARCHAR(50),
                        status VARCHAR(20) NOT NULL DEFAULT 'ready',
                        created_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
                        updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
                        FOREIGN KEY(pipeline_id) REFERENCES data_pipelines(id) ON DELETE SET NULL
                    )
                    """))
                    await conn.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_duckdb_tables_table_name ON duckdb_tables(table_name)"
                    ))
                    applied.append("CREATE TABLE duckdb_tables + index")

                await _set_user_version(conn, 5)
                applied.append("set user_version=5")
                current = 5

            # ── v6 migration: freshness_policy + query_transform_code ──
            if current < 6:
                # data_pipelines 补 freshness_policy_json
                dp_cols = await _get_table_columns(conn, "data_pipelines")
                if "freshness_policy_json" not in dp_cols:
                    await conn.execute(text(
                        '''ALTER TABLE data_pipelines ADD COLUMN freshness_policy_json TEXT NOT NULL DEFAULT '{"max_staleness_hours": 24}' '''
                    ))
                    applied.append("ALTER TABLE data_pipelines ADD COLUMN freshness_policy_json")

                await _set_user_version(conn, 6)
                applied.append("set user_version=6")
                current = 6

            # ── v7 migration: skills.is_system + skills.slash_command ──
            if current < 7:
                skills_cols = await _get_table_columns(conn, "skills")
                if "is_system" not in skills_cols:
                    await conn.execute(text(
                        "ALTER TABLE skills ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT 0"
                    ))
                    applied.append("ALTER TABLE skills ADD COLUMN is_system")
                if "slash_command" not in skills_cols:
                    await conn.execute(text(
                        "ALTER TABLE skills ADD COLUMN slash_command VARCHAR(50)"
                    ))
                    applied.append("ALTER TABLE skills ADD COLUMN slash_command")
                    # 创建唯一索引（SQLite 中 ALTER TABLE 不支持 UNIQUE 约束，用索引代替）
                    await conn.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_skills_slash_command "
                        "ON skills(slash_command) WHERE slash_command IS NOT NULL"
                    ))
                    applied.append("CREATE UNIQUE INDEX ix_skills_slash_command")
                await _set_user_version(conn, 7)
                applied.append("set user_version=7")
                current = 7

            # ── v8 migration: skills.handler_type + skills.handler_config ──
            if current < 8:
                skills_cols = await _get_table_columns(conn, "skills")
                if "handler_type" not in skills_cols:
                    await conn.execute(text(
                        "ALTER TABLE skills ADD COLUMN handler_type VARCHAR(50) DEFAULT 'standard'"
                    ))
                    applied.append("ALTER TABLE skills ADD COLUMN handler_type")
                if "handler_config" not in skills_cols:
                    await conn.execute(text(
                        "ALTER TABLE skills ADD COLUMN handler_config TEXT"
                    ))
                    applied.append("ALTER TABLE skills ADD COLUMN handler_config")
                await _set_user_version(conn, 8)
                applied.append("set user_version=8")
                current = 8
            # ── v9 migration: assets table + task extensions ──
            if current < 9:
                # 创建 assets 表
                if not await _table_exists(conn, "assets"):
                    await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS assets (
                        id VARCHAR(36) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        description TEXT,
                        asset_type VARCHAR(20) NOT NULL,
                        source_task_id VARCHAR(36),
                        code TEXT,
                        script_type VARCHAR(20),
                        env_vars_json TEXT NOT NULL DEFAULT '{}',
                        allowed_modules_json TEXT NOT NULL DEFAULT '[]',
                        content_markdown TEXT,
                        created_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
                        updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
                        FOREIGN KEY(source_task_id) REFERENCES tasks(id) ON DELETE SET NULL
                    )
                    """))
                    await conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_assets_asset_type ON assets(asset_type)"
                    ))
                    await conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_assets_script_type ON assets(script_type)"
                    ))
                    applied.append("CREATE TABLE assets + indexes")
                
                # 扩展 tasks 表
                task_cols = await _get_table_columns(conn, "tasks")
                if "task_type" not in task_cols:
                    await conn.execute(text(
                        "ALTER TABLE tasks ADD COLUMN task_type VARCHAR(20) NOT NULL DEFAULT 'ad_hoc'"
                    ))
                    applied.append("ALTER TABLE tasks ADD COLUMN task_type")
                if "asset_id" not in task_cols:
                    await conn.execute(text(
                        "ALTER TABLE tasks ADD COLUMN asset_id VARCHAR(36)"
                    ))
                    applied.append("ALTER TABLE tasks ADD COLUMN asset_id")
                if "last_run_at" not in task_cols:
                    await conn.execute(text(
                        "ALTER TABLE tasks ADD COLUMN last_run_at DATETIME"
                    ))
                    applied.append("ALTER TABLE tasks ADD COLUMN last_run_at")
                if "last_run_status" not in task_cols:
                    await conn.execute(text(
                        "ALTER TABLE tasks ADD COLUMN last_run_status VARCHAR(20)"
                    ))
                    applied.append("ALTER TABLE tasks ADD COLUMN last_run_status")
                
                await _set_user_version(conn, 9)
                applied.append("set user_version=9")
                current = 9

            # 在 upgrade_db_schema() 函数的最后一个 if current < X 块之后添加
            # ── v10 migration: context compaction fields ──
            if current < 10:
                task_cols = await _get_table_columns(conn, "tasks")
                if "compact_context" not in task_cols:
                    await conn.execute(text(
                        "ALTER TABLE tasks ADD COLUMN compact_context TEXT"
                    ))
                    applied.append("ALTER TABLE tasks ADD COLUMN compact_context")
                if "compact_anchor_step_id" not in task_cols:
                    await conn.execute(text(
                        "ALTER TABLE tasks ADD COLUMN compact_anchor_step_id VARCHAR(36)"
                    ))
                    applied.append("ALTER TABLE tasks ADD COLUMN compact_anchor_step_id")
                if "compact_anchor_created_at" not in task_cols:
                    await conn.execute(text(
                        "ALTER TABLE tasks ADD COLUMN compact_anchor_created_at DATETIME"
                    ))
                    applied.append("ALTER TABLE tasks ADD COLUMN compact_anchor_created_at")
                
                await _set_user_version(conn, 10)
                applied.append("set user_version=10")
                current = 10
            # ── v11 migration: tasks.data_source_ids ──
            if current < 11:
                task_cols = await _get_table_columns(conn, "tasks")
                if "data_source_ids" not in task_cols:
                    await conn.execute(text(
                        "ALTER TABLE tasks ADD COLUMN data_source_ids TEXT DEFAULT '[]'"
                    ))
                    applied.append("ALTER TABLE tasks ADD COLUMN data_source_ids")
                await _set_user_version(conn, 11)
                applied.append("set user_version=11")
                current = 11
            # ── v12 migration: tasks.pipeline_id ──
            if current < 12:
                task_cols = await _get_table_columns(conn, "tasks")
                if "pipeline_id" not in task_cols:
                    await conn.execute(text(
                        "ALTER TABLE tasks ADD COLUMN pipeline_id VARCHAR(36)"
                    ))
                    applied.append("ALTER TABLE tasks ADD COLUMN pipeline_id")
                await _set_user_version(conn, 12)
                applied.append("set user_version=12")
                current = 12

            return {
                "success": True,
                "from_version": from_version,
                "to_version": current,
                "applied": applied,
            }

    except Exception as e:
        logger.exception("数据库升级失败")
        return {
            "success": False,
            "from_version": -1,
            "to_version": -1,
            "applied": applied,
            "error": str(e),
        }

async def check_db_compatibility() -> dict:
    """
    检查数据库兼容性
    
    Returns:
        dict: {
            "compatible": bool,  # 是否兼容
            "exists": bool,      # 数据库文件是否存在
            "issues": list[str], # 不兼容的具体问题列表
            "db_path": str       # 数据库文件路径
        }
    """
    result = {
        "compatible": True,
        "exists": db_path.exists(),
        "issues": [],
        "db_path": str(db_path)
    }
    
    if not result["exists"]:
        # 数据库不存在，视为兼容（将创建新数据库）
        return result
    
    try:
        async with engine.begin() as conn:
            # 检查 tasks 表是否存在
            table_check = await conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
            ))
            if not table_check.fetchone():
                # tasks 表不存在，可能是全新数据库
                return result
            
            # 检查 tasks 表的 mode 字段
            result_info = await conn.execute(text("PRAGMA table_info(tasks)"))
            columns = [row[1] for row in result_info.fetchall()]
            
            if "mode" not in columns:
                result["compatible"] = False
                result["issues"].append("tasks 表缺少 'mode' 字段")
            
            if "plan_confirmed" not in columns:
                result["compatible"] = False
                result["issues"].append("tasks 表缺少 'plan_confirmed' 字段")
            
            if "current_subtask_id" not in columns:
                result["compatible"] = False
                result["issues"].append("tasks 表缺少 'current_subtask_id' 字段")
            
            # 检查 subtasks 表是否存在
            subtasks_check = await conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='subtasks'"
            ))
            if not subtasks_check.fetchone():
                result["compatible"] = False
                result["issues"].append("缺少 'subtasks' 表")
            
            # 检查 steps 表的 subtask_id 字段
            steps_info = await conn.execute(text("PRAGMA table_info(steps)"))
            steps_columns = [row[1] for row in steps_info.fetchall()]
            
            if "subtask_id" not in steps_columns:
                result["compatible"] = False
                result["issues"].append("steps 表缺少 'subtask_id' 字段")
                


    except Exception as e:
        logger.error(f"数据库兼容性检查失败: {e}")
        result["compatible"] = False
        result["issues"].append(f"检查过程出错: {str(e)}")
    
    return result


async def delete_and_recreate_db() -> dict:
    """
    删除旧数据库并重新创建
    
    Returns:
        dict: {
            "success": bool,
            "message": str
        }
    """
    try:
        # 1. 关闭所有连接
        await engine.dispose()
        
        # 2. 删除数据库文件
        if db_path.exists():
            os.remove(db_path)
            logger.info(f"已删除旧数据库: {db_path}")
        
        # 3. 重新初始化数据库（会自动创建新的连接）
        await init_db()
        
        return {
            "success": True,
            "message": "数据库已成功重建"
        }
    except Exception as e:
        logger.error(f"删除并重建数据库失败: {e}")
        return {
            "success": False,
            "message": f"操作失败: {str(e)}"
        }


async def init_db() -> None:
    """初始化数据库：自动升级 schema + 创建缺失表 + 插入默认配置"""
    # 1) 先做“应用内迁移”（对旧库补字段/补表，不丢数据）
    upgrade_result = await upgrade_db_schema()
    if not upgrade_result.get("success"):
        # 迁移失败不直接删库，让用户走“数据库重建”按钮兜底
        logger.error(f"数据库升级失败: {upgrade_result.get('error')}")
        raise RuntimeError(f"DB migration failed: {upgrade_result.get('error')}")

    # 2) 再跑一次 create_all（保证新表/新索引尽可能补齐）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 3) 创建默认配置数据
    await _create_default_agent_configs()
    # 4) Seed 内置 Skills
    await _seed_builtin_skills()

    logger.info(
        f"数据库初始化完成 (schema upgrade: {upgrade_result.get('from_version')} -> {upgrade_result.get('to_version')}, "
        f"applied={upgrade_result.get('applied')})"
    )


async def _create_default_agent_configs() -> None:
    """创建默认的Agent配置（如果不存在）"""
    from app.models import AgentConfig
    
    default_configs = [
        {"agent_type": "default"},
        {"agent_type": "plan"},
        {"agent_type": "analyst"},
        {"agent_type": "task_manager"},
        {"agent_type": "misc"},
    ]
    
    async with async_session() as session:
        for config_data in default_configs:
            # 检查是否已存在
            result = await session.execute(
                select(AgentConfig).where(AgentConfig.agent_type == config_data["agent_type"])
            )
            existing = result.scalar_one_or_none()
            
            if not existing:
                config = AgentConfig(**config_data)
                session.add(config)
        
        await session.commit()


async def get_db():
    """获取数据库会话的依赖注入"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _seed_builtin_skills() -> None:
    """Seed 内置系统 Skill（幂等：仅在不存在时创建，已存在则同步配置）"""
    from app.models import Skill
    from app.prompts.skills import get_builtin_skills
    
    builtin_skills = get_builtin_skills()
    
    async with async_session() as session:
        for skill_def in builtin_skills:
            result = await session.execute(
                select(Skill).where(Skill.slash_command == skill_def["slash_command"])
            )
            existing = result.scalar_one_or_none()
            
            if not existing:
                # 创建新 skill
                skill = Skill(
                    name=skill_def["name"],
                    slash_command=skill_def["slash_command"],
                    handler_type=skill_def.get("handler_type"),
                    handler_config=skill_def.get("handler_config"),
                    description=skill_def["description"],
                    prompt_markdown=skill_def.get("prompt_markdown"),
                    reference_markdown=skill_def.get("reference_markdown"),
                    is_active=skill_def.get("is_active", True),
                    is_system=True,
                )
                session.add(skill)
            else:
                # 更新现有 skill 的配置（保留用户的 is_active 状态）
                existing.handler_type = skill_def.get("handler_type")
                existing.handler_config = skill_def.get("handler_config")
                existing.description = skill_def["description"]
                existing.prompt_markdown = skill_def.get("prompt_markdown")
                existing.reference_markdown = skill_def.get("reference_markdown")
                if not existing.is_system:
                    existing.is_system = True
        
        await session.commit()
