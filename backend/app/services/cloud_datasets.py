# owlai/backend/app/services/cloud_datasets.py
"""owl-server 云数据集 HTTP 客户端"""

import httpx
from app.config import OWL_SERVER_URL

_TIMEOUT = 30.0


async def list_cloud_datasets() -> list[dict]:
    """获取 owl-server 公开数据集列表"""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{OWL_SERVER_URL}/api/v1/datasets")
        resp.raise_for_status()
        return resp.json()


async def query_cloud_dataset(slug: str, sql: str, limit: int = 1000) -> dict:
    """
    对远程数据集执行 SQL 查询。
    Returns: {"columns": [...], "rows": [[...], ...], "row_count": int, "truncated": bool}
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{OWL_SERVER_URL}/api/v1/datasets/{slug}/query",
            json={"sql": sql, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()