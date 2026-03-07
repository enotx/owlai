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
import asyncio

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ── SSE 流式对话（ReAct Agent） ────────────────────────────────
@router.post("/stream")
async def stream_message(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    通过 SSE 逐步推送 Agent 的分析过程。
    事件类型：text / tool_start / tool_result / step_saved / done / error
    """

    async def event_generator():
        try:
            async for sse_line in run_agent_stream(
                task_id=body.task_id,
                user_message=body.message,
                db=db,
            ):
                yield sse_line
        except asyncio.CancelledError:
            # 客户端断开连接，静默退出
            return
        except Exception as e:
            # 未预期错误，发送错误事件后关闭
            import json
            yield f"data: {json.dumps({'type': 'error', 'content': f'Stream error: {str(e)}'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'steps': []}, ensure_ascii=False)}\n\n"

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


# ── 获取 Step 中捕获的 DataFrame 预览数据 ──────────────────
@router.get("/steps/{step_id}/dataframe/{df_name}")
async def get_step_dataframe(
    step_id: str,
    df_name: str,
    db: AsyncSession = Depends(get_db),
):
    """返回某个 tool_use Step 中捕获的 DataFrame 数据（columns + rows）"""
    import os, json as _json
    # 查找 Step
    result = await db.execute(select(Step).where(Step.id == step_id))
    step = result.scalar_one_or_none()
    if not step:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Step not found")
    if step.step_type != "tool_use" or not step.code_output:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Step has no code execution data")
    # 从 code_output 解析 dataframes 元数据，找到 capture_id
    try:
        output_data = _json.loads(step.code_output)
    except _json.JSONDecodeError:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Invalid code_output format")
    dataframes_meta = output_data.get("dataframes", [])
    target = None
    for df_meta in dataframes_meta:
        if df_meta.get("name") == df_name:
            target = df_meta
            break
    if not target:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"DataFrame '{df_name}' not found in this step")
    capture_id = target.get("capture_id", "")
    capture_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "uploads", step.task_id, "captures",
    )
    file_path = os.path.join(capture_dir, f"{capture_id}_{df_name}.json")
    if not os.path.exists(file_path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Captured data file not found")
    # 读取并返回
    with open(file_path, "r", encoding="utf-8") as f:
        data = _json.load(f)
    return data  # {"columns": [...], "rows": [...]}
