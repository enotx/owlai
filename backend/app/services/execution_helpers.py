# backend/app/services/execution_helpers.py

"""
执行辅助工具 —— 提供心跳包装等通用能力
"""

import asyncio
import json
from typing import Any, AsyncGenerator, Coroutine, Literal, TypeGuard, TypeVar, TypedDict


def _sse(data: dict) -> str:
    """生成 SSE 事件格式"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


T = TypeVar("T")

class HeartbeatEvent(TypedDict):
    type: Literal["heartbeat"]
    content: str

def is_heartbeat_event(value: object) -> TypeGuard[HeartbeatEvent]:
    if not isinstance(value, dict):
        return False
    event_type = value.get("type")
    content = value.get("content")
    return event_type == "heartbeat" and isinstance(content, str)

async def run_with_heartbeat(
    coro: Coroutine[Any, Any, T],
    *,
    interval: float = 15.0,
    message: str = "executing",
) -> AsyncGenerator[HeartbeatEvent | T, None]:
    """
    包装一个协程，在其执行期间定期 yield 心跳事件。

    约定：
    - yield HeartbeatEvent -> 心跳事件
    - yield T              -> 协程最终结果（最后一个 yield）
    """
    task = asyncio.create_task(coro)

    while not task.done():
        try:
            result = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=interval,
            )
            yield result
            return
        except asyncio.TimeoutError:
            yield {"type": "heartbeat", "content": message}

    yield await task