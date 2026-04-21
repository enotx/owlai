# backend/app/services/execution/__init__.py

"""
统一代码执行入口

所有调用方应使用 execute_code() 而非直接调用 sandbox。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.execution.resolver import get_backend, resolve_backend_for_task
from app.services.execution.types import ExecutionContext
from app.services.sandbox import SandboxExecutionResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def execute_code(
    code: str,
    task_id: str = "",
    data_var_map: dict[str, str] | None = None,
    timeout: int = 7200,
    capture_dir: str | None = None,
    injected_envs: dict[str, str] | None = None,
    persisted_var_map: dict[str, str] | None = None,
    backend_id: str | None = None,
    security_level: str = "strict",
) -> SandboxExecutionResult:
    """统一代码执行入口

    参数签名刻意与 execute_code_in_sandbox 保持兼容，
    仅新增 task_id / backend_id / security_level。

    Args:
        backend_id: 显式指定 backend。None → 使用默认 (local)。
                    如需根据 Task 配置自动解析，使用 execute_code_for_task()。
    """
    ctx = ExecutionContext(
        code=code,
        task_id=task_id,
        data_var_map=data_var_map or {},
        persisted_var_map=persisted_var_map or {},
        injected_envs=injected_envs or {},
        capture_dir=capture_dir or "",
        timeout=timeout,
        security_level=security_level,  # type: ignore[arg-type]
    )
    backend = get_backend(backend_id)
    return await backend.execute(ctx)


async def execute_code_for_task(
    code: str,
    task_id: str,
    db: "AsyncSession",
    data_var_map: dict[str, str] | None = None,
    timeout: int = 7200,
    capture_dir: str | None = None,
    injected_envs: dict[str, str] | None = None,
    persisted_var_map: dict[str, str] | None = None,
    security_level: str = "strict",
) -> SandboxExecutionResult:
    """根据 Task 配置自动解析 Backend 并执行

    与 execute_code() 的区别：需要传入 db session，
    会查询 Task.execution_backend 和全局默认设置。
    """
    ctx = ExecutionContext(
        code=code,
        task_id=task_id,
        data_var_map=data_var_map or {},
        persisted_var_map=persisted_var_map or {},
        injected_envs=injected_envs or {},
        capture_dir=capture_dir or "",
        timeout=timeout,
        security_level=security_level,  # type: ignore[arg-type]
    )
    backend = await resolve_backend_for_task(task_id, db)
    return await backend.execute(ctx)