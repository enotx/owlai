# backend/app/routers/chat.py

"""Chat 对话 API —— SSE 流式回复 + OpenAI 集成"""

import os
import json
from typing import cast
from typing_extensions import Literal
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from dotenv import load_dotenv

from app.database import get_db, async_session
from app.models import Step, Knowledge
from app.schemas import ChatRequest, StepResponse

load_dotenv()

router = APIRouter(prefix="/api/chat", tags=["chat"])

# ── OpenAI 异步客户端（懒加载） ────────────────────────────────
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
    return _client


# ── 系统提示词 ─────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are **Owl 🦉**, an expert AI data analyst.

## Rules
- The user may upload CSV datasets. Their metadata (column names, dtypes, sample rows, statistics) will be provided in the context below.
- Answer in the **same language** the user uses.
- When the user asks for analysis, provide:
  1. A brief explanation of your analysis approach.
  2. If appropriate, a Pandas code snippet (fenced in ```python … ```) that the user can execute.
  3. A clear conclusion or insight.
- If no data has been uploaded yet, help the user understand what they can do and ask them to upload data first.
- Be concise but thorough.
"""


def _build_knowledge_context(knowledge_items: list[Knowledge]) -> str:
    """将当前 Task 的 Knowledge 拼装为上下文文本"""
    if not knowledge_items:
        return "\n[No datasets uploaded yet.]\n"
    parts: list[str] = []
    for k in knowledge_items:
        parts.append(f"### Dataset: {k.name}  (type={k.type})")
        if k.metadata_json:
            try:
                meta = json.loads(k.metadata_json)
                if "columns" in meta:
                    parts.append(f"Columns: {meta['columns']}")
                if "dtypes" in meta:
                    parts.append(f"Dtypes: {meta['dtypes']}")
                if "shape" in meta:
                    parts.append(f"Shape: {meta['shape']}")
                if "head" in meta:
                    parts.append(f"Sample rows:\n{meta['head']}")
                if "describe" in meta:
                    parts.append(f"Statistics:\n{meta['describe']}")
            except json.JSONDecodeError:
                parts.append(k.metadata_json)
        parts.append("")
    return "\n".join(parts)


async def _build_messages(task_id: str, db: AsyncSession) -> list[ChatCompletionMessageParam]:
    """构建发送给 OpenAI 的 messages 列表"""
    # 加载 Knowledge 上下文
    kn_result = await db.execute(
        select(Knowledge).where(Knowledge.task_id == task_id)
    )
    knowledge_items = list(kn_result.scalars().all())
    knowledge_context = _build_knowledge_context(knowledge_items)

    # 加载对话历史（最近 20 条，防止 token 超限）
    hist_result = await db.execute(
        select(Step)
        .where(Step.task_id == task_id)
        .order_by(Step.created_at.asc())
    )
    recent_steps = list(hist_result.scalars().all())[-20:]

    messages: list[ChatCompletionMessageParam] = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + "\n\n## Available Data Context\n" + knowledge_context,
        }
    ]
    for s in recent_steps:
        if s.role in ("system", "user", "assistant", "developer", "tool"):
            role = cast(Literal["system", "user", "assistant", "developer", "tool"], s.role)
        else:
            role = "user"
        messages.append(
            cast(
                ChatCompletionMessageParam,
                {"role": role, "content": s.content},
            )
        )
    return messages


# ── SSE 流式对话 ───────────────────────────────────────────────
@router.post("/stream")
async def stream_message(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    """通过 SSE 逐 token 推送 AI 回复"""

    # 1. 保存用户消息
    user_step = Step(task_id=body.task_id, role="user", content=body.message)
    db.add(user_step)
    await db.commit()

    # 2. 构建 messages（在生成器外完成，避免 session 已关闭问题）
    messages = await _build_messages(body.task_id, db)
    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    task_id = body.task_id

    # 3. SSE 生成器
    async def event_generator():
        client = _get_client()
        full_content = ""

        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=0.4,
                max_tokens=4096,
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    token = delta.content
                    full_content += token
                    yield f"data: {json.dumps({'token': token})}\n\n"

            # 流结束 → 新会话保存 AI 回复
            async with async_session() as session:
                assistant_step = Step(
                    task_id=task_id,
                    role="assistant",
                    content=full_content,
                    code=None,
                    code_output=None,
                )
                session.add(assistant_step)
                await session.commit()
                await session.refresh(assistant_step)

                step_data = {
                    "id": assistant_step.id,
                    "task_id": assistant_step.task_id,
                    "role": assistant_step.role,
                    "content": assistant_step.content,
                    "code": assistant_step.code,
                    "code_output": assistant_step.code_output,
                    "created_at": assistant_step.created_at.isoformat(),
                }
                yield f"data: {json.dumps({'done': True, 'step': step_data})}\n\n"

        except Exception as e:
            error_msg = f"AI 请求失败: {str(e)}"
            async with async_session() as session:
                err_step = Step(
                    task_id=task_id,
                    role="assistant",
                    content=f"⚠️ {error_msg}",
                )
                session.add(err_step)
                await session.commit()
            yield f"data: {json.dumps({'error': error_msg})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 非流式端点（保留用于回退/测试） ──────────────────────────
@router.post("", response_model=StepResponse)
async def send_message(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    """非流式：完整等待后返回"""
    user_step = Step(task_id=body.task_id, role="user", content=body.message)
    db.add(user_step)
    await db.commit()

    messages = await _build_messages(body.task_id, db)
    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    client = _get_client()

    try:
        response = await client.chat.completions.create(
            model=model, messages=messages, temperature=0.4, max_tokens=4096,
        )
        content = response.choices[0].message.content or "（AI 未返回内容）"
    except Exception as e:
        content = f"⚠️ AI 请求失败: {str(e)}"

    assistant_step = Step(task_id=body.task_id, role="assistant", content=content)
    db.add(assistant_step)
    await db.commit()
    await db.refresh(assistant_step)
    return assistant_step


# ── 历史记录 ───────────────────────────────────────────────────
@router.get("/history", response_model=list[StepResponse])
async def get_history(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取指定 Task 的对话历史"""
    result = await db.execute(
        select(Step).where(Step.task_id == task_id).order_by(Step.created_at.asc())
    )
    return result.scalars().all()