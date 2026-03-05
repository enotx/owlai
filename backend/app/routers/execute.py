# backend/app/routers/execute.py

"""代码执行 API：接收代码 → 沙箱执行 → 返回结果"""

import os
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Knowledge
from app.schemas import ExecuteRequest, ExecuteResponse
from app.services.sandbox import execute_code_in_sandbox
from app.services.data_processor import sanitize_variable_name

router = APIRouter(prefix="/api/execute", tags=["execute"])


async def _build_csv_var_map(task_id: str, db: AsyncSession) -> dict[str, str]:
    """
    根据 task_id 查出所有 CSV Knowledge，构建 {变量名: 绝对路径} 映射。
    """
    result = await db.execute(
        select(Knowledge).where(
            Knowledge.task_id == task_id,
            Knowledge.type == "csv",
        )
    )
    csv_items = result.scalars().all()
    var_map: dict[str, str] = {}
    for item in csv_items:
        if item.file_path and os.path.exists(item.file_path):
            var_name = sanitize_variable_name(item.name)
            var_map[var_name] = os.path.abspath(item.file_path)
    return var_map


@router.post("", response_model=ExecuteResponse)
async def execute_code(body: ExecuteRequest, db: AsyncSession = Depends(get_db)):
    """执行 Pandas 代码（沙箱隔离）"""
    csv_var_map = await _build_csv_var_map(body.task_id, db)

    result = await execute_code_in_sandbox(
        code=body.code,
        csv_var_map=csv_var_map,
    )

    return ExecuteResponse(
        success=result["success"],
        output=result.get("output"),
        error=result.get("error"),
        execution_time=result.get("execution_time", 0.0),
    )