# backend/app/services/execution/resolver.py

"""Backend 解析与注册"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.execution.backend import ExecutionBackend
from app.services.execution.local_backend import LocalSandboxBackend

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── 全局单例 ──────────────────────────────────────────────
_local_backend = LocalSandboxBackend()
_backends: dict[str, ExecutionBackend] = {}


def get_backend(backend_id: str | None = None) -> ExecutionBackend:
    """获取执行后端。None 或 "local" 返回 LocalSandboxBackend。"""
    if backend_id is None or backend_id == "local":
        return _local_backend
    backend = _backends.get(backend_id)
    if backend is None:
        logger.warning(
            "Backend %r not found, falling back to local", backend_id
        )
        return _local_backend
    return backend


def register_backend(backend_id: str, backend: ExecutionBackend) -> None:
    """注册一个命名 Backend（供 JupyterBackend 等动态注册）"""
    _backends[backend_id] = backend


def unregister_backend(backend_id: str) -> None:
    """注销 Backend"""
    _backends.pop(backend_id, None)


async def resolve_backend_for_task(
    task_id: str,
    db: "AsyncSession",
) -> ExecutionBackend:
    """根据 Task 配置解析对应的 Backend

    优先级：
    1. Task.execution_backend（如果非空且非 "auto"）
    2. 全局默认（SystemSetting 中的 default_execution_backend）
    3. 兜底 → LocalSandboxBackend
    """
    from sqlalchemy import select
    from app.models import Task, SystemSetting

    task = await db.get(Task, task_id)
    backend_key: str | None = None

    if task and task.execution_backend and task.execution_backend != "auto":
        backend_key = task.execution_backend
    else:
        # 查全局默认
        result = await db.execute(
            select(SystemSetting).where(
                SystemSetting.key == "default_execution_backend"
            )
        )
        setting = result.scalar_one_or_none()
        if setting and setting.value and setting.value != "auto":
            backend_key = setting.value

    if backend_key is None or backend_key == "local":
        return _local_backend

    # 尝试获取已注册的 backend
    if backend_key in _backends:
        return _backends[backend_key]

    # 尝试动态创建 Jupyter backend
    if backend_key.startswith("jupyter:"):
        config_id = backend_key.split(":", 1)[1]
        from app.models import JupyterConfig
        config = await db.get(JupyterConfig, config_id)
        if not config or config.status != "active":
            logger.warning(
                f"Jupyter config {config_id} not found or inactive, falling back to local"
            )
            return _local_backend
        # 创建 JupyterBackend 实例
        from app.services.execution.jupyter import JupyterBackend, KernelSessionManager
        sm = KernelSessionManager(
            jupyter_url=config.server_url,
            token=config.token,
            kernel_name=config.kernel_name,
            idle_timeout=config.idle_timeout,
            data_transfer_mode=config.data_transfer_mode,
            shared_storage_path=config.shared_storage_path,
        )
        sm.start_cleanup_loop()  # 启动后台清理
        backend = JupyterBackend(
            session_manager=sm,
            default_security_level=config.security_level,
        )
        register_backend(backend_key, backend)
        logger.info(f"Created JupyterBackend for config {config_id}")
        return backend
    logger.warning("Unknown backend %r, falling back to local", backend_key)
    return _local_backend
