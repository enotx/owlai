# backend/app/services/execution/backend.py

"""ExecutionBackend 统一协议"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.services.execution.types import ExecutionContext
from app.services.sandbox import SandboxExecutionResult


@runtime_checkable
class ExecutionBackend(Protocol):
    """代码执行后端的统一协议

    所有后端必须返回 SandboxExecutionResult，确保上层零改动。
    """

    async def execute(self, ctx: ExecutionContext) -> SandboxExecutionResult:
        """执行代码，返回标准结果"""
        ...

    async def interrupt(self, task_id: str) -> bool:
        """中断指定 task 正在执行的代码。返回是否成功。"""
        ...

    async def shutdown(self, task_id: str) -> None:
        """关闭 task 关联的执行会话（释放资源）"""
        ...

    async def list_variables(self, task_id: str) -> list[dict]:
        """列出当前会话中的变量元信息

        返回格式: [{"name": str, "type": str, "shape": str, ...}, ...]
        """
        ...