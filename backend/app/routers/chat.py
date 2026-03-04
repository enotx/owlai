# backend/app/routers/chat.py

"""Chat 对话 API（占位实现）"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Step
from app.schemas import ChatRequest, StepResponse

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=StepResponse)
async def send_message(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    """发送消息并获取 AI 回复 — 占位实现"""
    # 保存用户消息
    user_step = Step(task_id=body.task_id, role="user", content=body.message)
    db.add(user_step)
    await db.commit()

    # TODO: 调用 AI Agent，生成回复、执行代码
    assistant_step = Step(
        task_id=body.task_id,
        role="assistant",
        content="这是一条占位回复。AI Agent 功能尚未实现。",
        code=None,
        code_output=None,
    )
    db.add(assistant_step)
    await db.commit()
    await db.refresh(assistant_step)
    return assistant_step


@router.get("/history", response_model=list[StepResponse])
async def get_history(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取指定 Task 的对话历史"""
    result = await db.execute(
        select(Step).where(Step.task_id == task_id).order_by(Step.created_at.asc())
    )
    return result.scalars().all()