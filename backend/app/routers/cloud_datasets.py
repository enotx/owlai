# owlai/backend/app/routers/cloud_datasets.py
"""云数据集 API — 供前端 Cloud Hub 使用"""

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Knowledge
from app.services.cloud_datasets import list_cloud_datasets, query_cloud_dataset

router = APIRouter(prefix="/api/cloud-datasets", tags=["cloud-datasets"])


@router.get("")
async def list_datasets():
    """列出 owl-server 上的公开数据集"""
    try:
        return await list_cloud_datasets()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"owl-server unreachable: {e}")


@router.get("/{slug}/schema")
async def get_dataset_schema(slug: str):
    """获取数据集 schema（通过 LIMIT 0 查询推断）"""
    try:
        result = await query_cloud_dataset(slug, f'SELECT * FROM "{slug}" LIMIT 5')
        return {
            "slug": slug,
            "columns": result["columns"],
            "sample_rows": result["rows"][:5],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{slug}/add-to-context")
async def add_cloud_dataset_to_context(
    slug: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """将云数据集加入 Task 的 Knowledge 上下文"""
    # 检查是否已添加
    result = await db.execute(
        select(Knowledge).where(
            Knowledge.task_id == task_id,
            Knowledge.type == "cloud_dataset",
            Knowledge.name == slug,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return {"status": "already_added", "knowledge_id": existing.id}

    # 获取 schema + sample
    try:
        schema_info = await query_cloud_dataset(slug, f'SELECT * FROM "{slug}" LIMIT 5')
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch schema: {e}")

    # 获取数据集基本信息
    try:
        datasets = await list_cloud_datasets()
        ds_info = next((d for d in datasets if d["slug"] == slug), None)
    except Exception:
        ds_info = None

    metadata = {
        "slug": slug,
        "name": ds_info["name"] if ds_info else slug,
        "description": ds_info.get("description", "") if ds_info else "",
        "columns": schema_info["columns"],
        "row_count": ds_info.get("row_count") if ds_info else None,
        "sample_rows": schema_info["rows"][:5],
    }

    knowledge = Knowledge(
        task_id=task_id,
        type="cloud_dataset",
        name=slug,
        file_path=None,
        metadata_json=json.dumps(metadata, ensure_ascii=False),
    )
    db.add(knowledge)
    await db.commit()
    await db.refresh(knowledge)
    return {"status": "added", "knowledge_id": knowledge.id}