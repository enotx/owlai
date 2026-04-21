# backend/app/services/execution/jupyter/uploader.py

"""Jupyter Contents API 文件上传"""

import base64
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class JupyterUploader:
    """通过 Jupyter Contents API 上传文件到远端"""

    def __init__(self, server_url: str, token: str | None = None):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self._headers = {}
        if token:
            self._headers["Authorization"] = f"token {token}"

    async def upload_file(
        self,
        local_path: str,
        remote_dir: str = "owl_data",
    ) -> str:
        """
        上传文件到 Jupyter Server。

        Args:
            local_path: 本地文件绝对路径
            remote_dir: 远端目录（相对于 Jupyter 工作目录）

        Returns:
            远端文件路径（供 kernel 中 pd.read_csv() 使用）
        """
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")

        file_name = Path(local_path).name
        remote_path = f"{remote_dir}/{file_name}"

        # 读取文件内容并 base64 编码
        with open(local_path, "rb") as f:
            content_bytes = f.read()

        # Jupyter Contents API 限制：单文件 < 200MB（base64 后约 270MB）
        if len(content_bytes) > 200 * 1024 * 1024:
            raise ValueError(
                f"File too large for Contents API upload: {len(content_bytes) / 1024 / 1024:.1f} MB "
                "(max 200 MB). Consider using shared storage."
            )

        content_b64 = base64.b64encode(content_bytes).decode("ascii")

        # 构造 Contents API 请求
        payload = {
            "type": "file",
            "format": "base64",
            "content": content_b64,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            # 先确保目录存在
            await self._ensure_directory(client, remote_dir)

            # 上传文件（PUT 会覆盖同名文件）
            resp = await client.put(
                f"{self.server_url}/api/contents/{remote_path}",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()

        logger.info(f"Uploaded {file_name} → {remote_path} ({len(content_bytes) / 1024:.1f} KB)")
        return remote_path

    async def _ensure_directory(self, client: httpx.AsyncClient, dir_path: str) -> None:
        """确保远端目录存在（递归创建）"""
        # 检查目录是否存在
        try:
            resp = await client.get(
                f"{self.server_url}/api/contents/{dir_path}",
                headers=self._headers,
            )
            if resp.status_code == 200:
                return  # 目录已存在
        except httpx.HTTPStatusError:
            pass

        # 创建目录
        payload = {"type": "directory"}
        try:
            resp = await client.put(
                f"{self.server_url}/api/contents/{dir_path}",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            logger.info(f"Created remote directory: {dir_path}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 409:  # 409 = already exists
                raise