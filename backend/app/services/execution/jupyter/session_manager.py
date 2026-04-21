# backend/app/services/execution/jupyter/session_manager.py

"""Kernel Session 生命周期管理"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.services.execution.jupyter.types import WebSocketLike

from app.services.execution.jupyter.wire import JupyterWire

logger = logging.getLogger(__name__)


@dataclass
class KernelSession:
    """单个 Kernel 会话的状态"""

    task_id: str
    kernel_id: str
    ws: WebSocketLike
    wire: JupyterWire

    status: str = "idle"  # "idle" | "busy" | "starting" | "dead"
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    setup_done: bool = False  # helper 函数是否已注入

    # 已上传的文件缓存（避免重复上传）
    uploaded_files: dict[str, str] = field(default_factory=dict)
    # {local_path: remote_path}


class KernelSessionManager:
    """管理 Task ↔ Kernel 映射，负责 kernel 生命周期"""

    def __init__(
        self,
        jupyter_url: str,
        token: str | None = None,
        kernel_name: str = "python3",
        idle_timeout: int = 1800,
        data_transfer_mode: str = "upload",
        shared_storage_path: str | None = None,
    ):
        self.jupyter_url = jupyter_url.rstrip("/")
        self.token = token
        self.kernel_name = kernel_name
        self.idle_timeout = idle_timeout
        self.data_transfer_mode = data_transfer_mode
        self.shared_storage_path = shared_storage_path

        self._wire = JupyterWire(jupyter_url, token)
        self._sessions: dict[str, KernelSession] = {}  # task_id → session
        self._lock = asyncio.Lock()

        # 启动后台清理任务
        self._cleanup_task: asyncio.Task | None = None

    def start_cleanup_loop(self) -> None:
        """启动后台 idle timeout 清理循环"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """后台循环：定期清理 idle 超时的 session"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟检查一次
                await self.cleanup_idle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")

    async def get_or_create(self, task_id: str) -> KernelSession:
        """获取或创建 task 对应的 kernel session"""
        async with self._lock:
            session = self._sessions.get(task_id)

            # 检查现有 session 是否可用
            if session:
                if session.status == "dead":
                    logger.warning(f"Session for task {task_id} is dead, recreating")
                    await self._cleanup_session(session)
                    del self._sessions[task_id]
                else:
                    session.last_activity = time.time()
                    return session

            # 创建新 session
            logger.info(f"Creating new kernel session for task {task_id}")
            kernel_id = await self._wire.start_kernel(self.kernel_name)

            # 先建立 WebSocket 连接（这会触发 kernel 完成初始化）
            logger.info(f"Connecting WebSocket to kernel {kernel_id}")
            ws = await self._wire.connect_ws(kernel_id)

            # 通过 WebSocket 等待 kernel ready
            await self._wait_for_kernel_ready_ws(ws, kernel_id)

            session = KernelSession(
                task_id=task_id,
                kernel_id=kernel_id,
                ws=ws,
                wire=self._wire,
            )
            self._sessions[task_id] = session
            return session

    async def _wait_for_kernel_ready_ws(
        self,
        ws: "WebSocketLike",
        kernel_id: str,
        timeout: float = 60.0,
    ) -> None:
        """通过 WebSocket 等待 kernel 进入 idle 状态"""
        import json as _json

        start = time.time()
        logger.info(f"Waiting for kernel {kernel_id} to become ready via WebSocket...")

        # 发送 kernel_info_request，触发 kernel 回应
        kernel_info_msg = {
            "header": {
                "msg_id": f"owl_kinit_{kernel_id[:8]}",
                "msg_type": "kernel_info_request",
                "username": "owl",
                "session": f"owl_session_{kernel_id[:8]}",
                "version": "5.3",
            },
            "parent_header": {},
            "metadata": {},
            "content": {},
            "buffers": [],
            "channel": "shell",
        }
        await ws.send(_json.dumps(kernel_info_msg))

        # 等待 status: idle 或 kernel_info_reply
        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                raise TimeoutError(
                    f"Kernel {kernel_id} did not become ready in {timeout}s "
                    f"(WebSocket connected but no idle status received)"
                )

            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                msg = _json.loads(raw)
                msg_type = msg.get("msg_type", "")

                if msg_type == "status":
                    state = msg.get("content", {}).get("execution_state")
                    logger.debug(f"Kernel {kernel_id} status: {state} ({elapsed:.1f}s)")
                    if state == "idle":
                        logger.info(
                            f"Kernel {kernel_id} ready after {elapsed:.1f}s"
                        )
                        return

                elif msg_type == "kernel_info_reply":
                    logger.info(
                        f"Kernel {kernel_id} responded to kernel_info after {elapsed:.1f}s"
                    )
                    # kernel_info_reply 之后通常紧跟 status: idle
                    # 继续等 idle 确认

            except asyncio.TimeoutError:
                logger.debug(
                    f"Kernel {kernel_id} still waiting... ({elapsed:.1f}s)"
                )
                continue
            
    async def shutdown(self, task_id: str) -> None:
        """关闭 task 对应的 kernel session"""
        async with self._lock:
            session = self._sessions.pop(task_id, None)
            if session:
                await self._cleanup_session(session)

    async def _cleanup_session(self, session: KernelSession) -> None:
        """清理单个 session（关闭 WS + shutdown kernel）"""
        try:
            await session.ws.close()
        except Exception as e:
            logger.warning(f"Failed to close WebSocket for {session.kernel_id}: {e}")

        try:
            await session.wire.shutdown_kernel(session.kernel_id)
        except Exception as e:
            logger.warning(f"Failed to shutdown kernel {session.kernel_id}: {e}")

        logger.info(f"Cleaned up session for task {session.task_id}")

    async def interrupt(self, task_id: str) -> bool:
        """中断 task 对应的 kernel 执行"""
        session = self._sessions.get(task_id)
        if not session:
            return False
        return await session.wire.interrupt_kernel(session.kernel_id)

    async def cleanup_idle(self) -> None:
        """清理所有 idle 超时的 session"""
        now = time.time()
        to_remove: list[str] = []

        async with self._lock:
            for task_id, session in self._sessions.items():
                if session.status == "idle":
                    idle_time = now - session.last_activity
                    if idle_time > self.idle_timeout:
                        logger.info(
                            f"Session for task {task_id} idle for {idle_time:.0f}s, cleaning up"
                        )
                        to_remove.append(task_id)

            for task_id in to_remove:
                session = self._sessions.pop(task_id)
                await self._cleanup_session(session)

    async def shutdown_all(self) -> None:
        """关闭所有 session（应用退出时调用）"""
        async with self._lock:
            tasks = [
                self._cleanup_session(session)
                for session in self._sessions.values()
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            self._sessions.clear()

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def list_sessions(self) -> list[dict]:
        """列出所有活跃 session（供前端展示）"""
        return [
            {
                "task_id": s.task_id,
                "kernel_id": s.kernel_id,
                "status": s.status,
                "created_at": s.created_at,
                "last_activity": s.last_activity,
                "idle_seconds": time.time() - s.last_activity,
            }
            for s in self._sessions.values()
        ]