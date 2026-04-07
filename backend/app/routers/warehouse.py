# backend/app/routers/warehouse.py

"""
DuckDB 仓库 & Data Pipeline REST API。

提供：
- DuckDB 表的列表/预览/删除/添加到上下文
- Data Pipeline 的 CRUD 和手动执行
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_db
from app.models import DuckDBTable, DataPipeline, Knowledge
from app.schemas import (
    DuckDBTableResponse,
    DuckDBTablePreviewResponse,
    DataPipelineCreate,
    DataPipelineResponse,
)
from app.services import warehouse as wh

router = APIRouter(prefix="/api/warehouse", tags=["warehouse"])


# ━━━ DuckDB Tables ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/tables", response_model=list[DuckDBTableResponse])
async def list_duckdb_tables(db: AsyncSession = Depends(get_db)):
    """列出所有已注册的 DuckDB 表元数据"""
    result = await db.execute(
        select(DuckDBTable).order_by(DuckDBTable.updated_at.desc())
    )
    return list(result.scalars().all())


@router.get("/tables/{table_id}/preview", response_model=DuckDBTablePreviewResponse)
async def preview_duckdb_table(table_id: str, limit: int = 50, db: AsyncSession = Depends(get_db)):
    """预览 DuckDB 表数据"""
    result = await db.execute(select(DuckDBTable).where(DuckDBTable.id == table_id))
    table_meta = result.scalar_one_or_none()
    if not table_meta:
        raise HTTPException(status_code=404, detail="Table not found")

    try:
        preview = await wh.async_get_table_preview(table_meta.table_name, limit)
        return DuckDBTablePreviewResponse(**preview)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview failed: {str(e)}")


@router.delete("/tables/{table_id}")
async def delete_duckdb_table(table_id: str, db: AsyncSession = Depends(get_db)):
    """删除 DuckDB 表（物理 + 元数据）"""
    result = await db.execute(select(DuckDBTable).where(DuckDBTable.id == table_id))
    table_meta = result.scalar_one_or_none()
    if not table_meta:
        raise HTTPException(status_code=404, detail="Table not found")

    # 删除物理表
    try:
        await wh.async_drop_table(table_meta.table_name)
    except Exception:
        pass  # 物理表可能已不存在

    # 删除所有引用此表的 Knowledge 记录
    await db.execute(
        delete(Knowledge).where(
            Knowledge.type == "duckdb_table",
            Knowledge.metadata_json.contains(table_meta.table_name),
        )
    )

    # 删除元数据
    await db.delete(table_meta)
    await db.commit()
    return {"status": "deleted", "table_name": table_meta.table_name}


@router.post("/tables/{table_id}/add-to-context")
async def add_table_to_context(
    table_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """将 DuckDB 表添加到指定 Task 的 Knowledge 上下文"""
    # 查询表元数据
    result = await db.execute(select(DuckDBTable).where(DuckDBTable.id == table_id))
    table_meta = result.scalar_one_or_none()
    if not table_meta:
        raise HTTPException(status_code=404, detail="Table not found")

    # 检查是否已添加
    result = await db.execute(
        select(Knowledge).where(
            Knowledge.task_id == task_id,
            Knowledge.type == "duckdb_table",
            Knowledge.name == table_meta.table_name,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return {"status": "already_added", "knowledge_id": existing.id}

    # 获取表预览（前 5 行）
    try:
        preview = await wh.async_get_table_preview(table_meta.table_name, limit=5)
        sample_rows = preview["rows"]
    except Exception:
        sample_rows = []

    # 创建 Knowledge 记录
    knowledge = Knowledge(
        task_id=task_id,
        type="duckdb_table",
        name=table_meta.table_name,
        file_path=None,
        metadata_json=json.dumps({
            "duckdb_table_id": table_meta.id,
            "table_name": table_meta.table_name,
            "display_name": table_meta.display_name,
            "description": table_meta.description,
            "schema": json.loads(table_meta.table_schema_json),
            "row_count": table_meta.row_count,
            "source_type": table_meta.source_type,
            "data_updated_at": table_meta.data_updated_at.isoformat() if table_meta.data_updated_at else None,
            "sample_rows": sample_rows,
        }, ensure_ascii=False),
    )
    db.add(knowledge)
    await db.commit()
    await db.refresh(knowledge)

    return {"status": "added", "knowledge_id": knowledge.id}


@router.post("/tables/{table_id}/remove-from-context")
async def remove_table_from_context(
    table_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """从指定 Task 的上下文中移除 DuckDB 表"""
    result = await db.execute(select(DuckDBTable).where(DuckDBTable.id == table_id))
    table_meta = result.scalar_one_or_none()
    if not table_meta:
        raise HTTPException(status_code=404, detail="Table not found")

    await db.execute(
        delete(Knowledge).where(
            Knowledge.task_id == task_id,
            Knowledge.type == "duckdb_table",
            Knowledge.name == table_meta.table_name,
        )
    )
    await db.commit()
    return {"status": "removed"}


# ━━━ Data Pipelines ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/pipelines", response_model=list[DataPipelineResponse])
async def list_pipelines(db: AsyncSession = Depends(get_db)):
    """列出所有 Data Pipeline"""
    result = await db.execute(
        select(DataPipeline).order_by(DataPipeline.updated_at.desc())
    )
    return list(result.scalars().all())


@router.post("/pipelines", response_model=DataPipelineResponse)
async def create_pipeline(body: DataPipelineCreate, db: AsyncSession = Depends(get_db)):
    """创建 Data Pipeline"""
    pipeline = DataPipeline(
        name=body.name,
        description=body.description,
        source_type=body.source_type,
        source_config=body.source_config,
        transform_code=body.transform_code,
        transform_description=body.transform_description,
        target_table_name=body.target_table_name,
        write_strategy=body.write_strategy,
        upsert_key=body.upsert_key,
        output_schema=body.output_schema,
        is_auto=body.is_auto,
        status="active",
    )
    db.add(pipeline)
    await db.commit()
    await db.refresh(pipeline)
    return pipeline


@router.get("/pipelines/{pipeline_id}", response_model=DataPipelineResponse)
async def get_pipeline(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DataPipeline).where(DataPipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline


@router.delete("/pipelines/{pipeline_id}")
async def delete_pipeline(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DataPipeline).where(DataPipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    await db.delete(pipeline)
    await db.commit()
    return {"status": "deleted"}