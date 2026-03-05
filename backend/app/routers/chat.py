# backend/app/routers/chat.py

"""Chat 对话 API —— ReAct Agent + SSE 流式回复"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Step
from app.schemas import ChatRequest, StepResponse
from app.services.agent import run_agent_stream

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ── SSE 流式对话（ReAct Agent） ────────────────────────────────
@router.post("/stream")
async def stream_message(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    通过 SSE 逐步推送 Agent 的分析过程。
    事件类型：text / tool_start / tool_result / step_saved / done / error
    """

    async def event_generator():
        async for sse_line in run_agent_stream(
            task_id=body.task_id,
            user_message=body.message,
            db=db,
        ):
            yield sse_line

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── 历史记录 ───────────────────────────────────────────────────
@router.get("/history", response_model=list[StepResponse])
async def get_history(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取指定 Task 的对话历史"""
    result = await db.execute(
        select(Step).where(Step.task_id == task_id).order_by(Step.created_at.asc())
    )
    return result.scalars().all()