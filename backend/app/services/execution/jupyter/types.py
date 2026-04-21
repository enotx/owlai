# backend/app/services/execution/jupyter/types.py

"""Jupyter 模块内部类型定义"""

from typing import Protocol, Union


class WebSocketLike(Protocol):
    """WebSocket 连接的最小接口（兼容所有 websockets 版本）"""

    async def send(self, message: Union[str, bytes]) -> None: ...
    async def recv(self) -> Union[str, bytes]: ...
    async def close(self) -> None: ...