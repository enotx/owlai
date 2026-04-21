# backend/app/services/execution/jupyter/wire.py

"""Jupyter Server REST API / WebSocket 通信层"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import httpx

import websockets
from app.services.execution.jupyter.types import WebSocketLike


logger = logging.getLogger(__name__)


class JupyterWire:
    """Jupyter Server 通信层（REST API + WebSocket）"""

    def __init__(self, server_url: str, token: str | None = None):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self._headers = {}
        if token:
            self._headers["Authorization"] = f"token {token}"

    def _client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        """统一创建 httpx client，处理 SSL 和重定向"""
        return httpx.AsyncClient(
            timeout=timeout,
            verify=False,
            follow_redirects=False,
            headers=self._headers,
        )

    # ── REST API ──────────────────────────────────────────

    async def start_kernel(self, kernel_name: str = "python3") -> str:
        """启动一个新 kernel，返回 kernel_id"""
        async with self._client(timeout=30.0) as client:
            resp = await client.post(
                f"{self.server_url}/api/kernels",
                headers=self._headers,
                json={"name": kernel_name},
            )
            resp.raise_for_status()
            data = resp.json()
            kernel_id = data["id"]
            logger.info(f"Started kernel {kernel_id} (spec: {kernel_name})")
            return kernel_id

    async def shutdown_kernel(self, kernel_id: str) -> None:
        """关闭 kernel"""
        async with self._client(timeout=20.0) as client:
            resp = await client.delete(
                f"{self.server_url}/api/kernels/{kernel_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            logger.info(f"Shutdown kernel {kernel_id}")

    async def interrupt_kernel(self, kernel_id: str) -> bool:
        """中断 kernel 执行"""
        try:
            async with self._client(timeout=20.0) as client:
                resp = await client.post(
                    f"{self.server_url}/api/kernels/{kernel_id}/interrupt",
                    headers=self._headers,
                )
                resp.raise_for_status()
                logger.info(f"Interrupted kernel {kernel_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to interrupt kernel {kernel_id}: {e}")
            return False

    async def get_kernel_status(self, kernel_id: str) -> dict:
        """获取 kernel 状态"""
        async with self._client(timeout=30.0) as client:
            resp = await client.get(
                f"{self.server_url}/api/kernels/{kernel_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def list_kernelspecs(self) -> dict[str, Any]:
        """列出可用的 kernel specs"""
        async with self._client(timeout=30.0) as client:
            resp = await client.get(
                f"{self.server_url}/api/kernelspecs",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    # ── WebSocket ─────────────────────────────────────────

    async def connect_ws(self, kernel_id: str) -> WebSocketLike:
        import ssl as _ssl
        ws_url = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
        uri = f"{ws_url}/api/kernels/{kernel_id}/channels"
        if self.token:
            uri += f"?token={self.token}"
        # 构建不验证证书的 SSL context
        ssl_context = _ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = _ssl.CERT_NONE
        ws = await websockets.connect(
            uri,
            max_size=10 * 1024 * 1024,
            ssl=ssl_context if uri.startswith("wss://") else None,
        )
        logger.info(f"WebSocket connected to kernel {kernel_id}")
        return ws

    async def execute_code(
        self,
        ws: WebSocketLike,
        code: str,
        timeout: float = 300.0,
        silent: bool = False,
    ) -> dict[str, Any]:
        """
        通过 WebSocket 执行代码，收集输出。

        Returns:
            {
                "success": bool,
                "output": str,  # stdout + stderr 合并
                "error": str | None,
                "execution_time": float,
                "display_data": list[dict],  # iopub 的 display_data 消息
            }
        """
        msg_id = uuid.uuid4().hex

        # 构造 execute_request 消息
        request = {
            "header": {
                "msg_id": msg_id,
                "msg_type": "execute_request",
                "username": "owl",
                "session": uuid.uuid4().hex,
                "version": "5.3",
            },
            "parent_header": {},
            "metadata": {},
            "content": {
                "code": code,
                "silent": silent,
                "store_history": not silent,
                "user_expressions": {},
                "allow_stdin": False,
            },
            "buffers": [],
            "channel": "shell",
        }

        await ws.send(json.dumps(request))

        # 收集输出
        output_parts: list[str] = []
        error_parts: list[str] = []
        display_data_list: list[dict] = []
        execution_state = "busy"
        start_time = asyncio.get_event_loop().time()

        try:
            while True:
                if asyncio.get_event_loop().time() - start_time > timeout:
                    raise TimeoutError(f"Execution timeout ({timeout}s)")

                try:
                    raw_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    # 5秒无消息 → 继续等待（kernel 可能在长时间计算）
                    continue

                msg = json.loads(raw_msg)
                msg_type = msg.get("msg_type")
                parent_msg_id = msg.get("parent_header", {}).get("msg_id")

                # 只处理与当前 execute_request 相关的消息
                if parent_msg_id != msg_id:
                    continue

                content = msg.get("content", {})

                # ── iopub channel 消息 ──
                if msg_type == "stream":
                    text = content.get("text", "")
                    if content.get("name") == "stdout":
                        output_parts.append(text)
                    elif content.get("name") == "stderr":
                        error_parts.append(text)

                elif msg_type == "execute_result":
                    # 执行结果（如最后一行表达式的值）
                    data = content.get("data", {})
                    if "text/plain" in data:
                        output_parts.append(data["text/plain"])

                elif msg_type == "display_data":
                    # 图表等 rich output
                    display_data_list.append(content)

                elif msg_type == "error":
                    # 执行错误
                    traceback = content.get("traceback", [])
                    error_parts.extend(traceback)

                elif msg_type == "status":
                    # kernel 状态变化
                    execution_state = content.get("execution_state", "busy")
                    if execution_state == "idle":
                        # kernel 空闲 → 执行完成
                        break

                elif msg_type == "execute_reply":
                    # shell channel 的回复（包含执行状态）
                    status = content.get("status")
                    if status == "error":
                        # 执行失败
                        ename = content.get("ename", "UnknownError")
                        evalue = content.get("evalue", "")
                        error_parts.append(f"{ename}: {evalue}")
                    # 注意：execute_reply 不代表执行完成，需等 status=idle

        except Exception as e:
            logger.error(f"WebSocket execution error: {e}")
            error_parts.append(f"WebSocket error: {str(e)}")

        elapsed = asyncio.get_event_loop().time() - start_time

        output_text = "".join(output_parts).strip()
        error_text = "".join(error_parts).strip() if error_parts else None

        return {
            "success": not bool(error_text),
            "output": output_text or None,
            "error": error_text,
            "execution_time": elapsed,
            "display_data": display_data_list,
        }