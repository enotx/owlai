# backend/app/routers/execute.py

"""代码执行 API（占位实现）"""

from fastapi import APIRouter
from app.schemas import ExecuteRequest, ExecuteResponse

router = APIRouter(prefix="/api/execute", tags=["execute"])


@router.post("", response_model=ExecuteResponse)
async def execute_code(body: ExecuteRequest):
    """执行 Pandas 代码 — 占位实现"""
    # TODO: 安全沙箱执行
    return ExecuteResponse(
        success=True,
        output="代码执行功能尚未实现（占位）",
        error=None,
        execution_time=0.0,
    )

