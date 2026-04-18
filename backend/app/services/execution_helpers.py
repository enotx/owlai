# backend/app/services/execution_helpers.py

"""
执行辅助工具 —— 提供心跳包装等通用能力
"""

import asyncio
import json
from typing import Any, AsyncGenerator, Coroutine


def _sse(data: dict) -> str:
    """生成 SSE 事件格式"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def run_with_heartbeat(
    coro: Coroutine[Any, Any, Any],
    *,
    interval: float = 15.0,
    message: str = "executing",
) -> AsyncGenerator[str | Any, None]:
    """
    包装一个协程，在其执行期间定期 yield SSE 心跳事件。

    约定：
    - yield str  → SSE 心跳字符串，调用方直接转发给前端
    - yield Any  → 协程的最终返回值（最后一个 yield）

    用法：
        result = None
        async for item in run_with_heartbeat(some_coro()):
            if isinstance(item, str):
                yield item          # 转发心跳到 SSE 流
            else:
                result = item       # 拿到真正的结果

    异常会原样抛出，由调用方的 try/except 处理。
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
            yield _sse({"type": "heartbeat", "content": message})

    # task 已完成（可能在 shield 和下一次循环之间完成）
    yield await task