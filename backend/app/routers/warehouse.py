# backend/app/routers/warehouse.py

"""
DuckDB 仓库 & Data Pipeline REST API。

提供：
- DuckDB 表的列表/预览/删除/添加到上下文
- Data Pipeline 的 CRUD 和手动执行
- 表新鲜度检查与刷新
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


async def _find_existing_pipeline_knowledge(
    db: AsyncSession,
    task_id: str,
    pipeline_id: str,
) -> Knowledge | None:
    result = await db.execute(
        select(Knowledge).where(
            Knowledge.task_id == task_id,
            Knowledge.type == "data_pipeline",
        )
    )
    for item in result.scalars().all():
        if not item.metadata_json:
            continue
        try:
            meta = json.loads(item.metadata_json)
        except json.JSONDecodeError:
            continue
        if meta.get("pipeline_id") == pipeline_id:
            return item
    return None


async def _ensure_pipeline_in_context(
    db: AsyncSession,
    task_id: str,
    pipeline: DataPipeline,
) -> Knowledge | None:
    existing = await _find_existing_pipeline_knowledge(db, task_id, pipeline.id)
    if existing:
        return existing

    knowledge = Knowledge(
        task_id=task_id,
        type="data_pipeline",
        name=pipeline.name,
        file_path=None,
        metadata_json=json.dumps(
            {
                "pipeline_id": pipeline.id,
                "target_table_name": pipeline.target_table_name,
                "source_type": pipeline.source_type,
                "write_strategy": pipeline.write_strategy,
                "description": pipeline.description,
            },
            ensure_ascii=False,
        ),
    )
    db.add(knowledge)
    await db.flush()
    return knowledge

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
            "pipeline_id": table_meta.pipeline_id,
            "data_updated_at": table_meta.data_updated_at.isoformat() if table_meta.data_updated_at else None,
            "sample_rows": sample_rows,
        }, ensure_ascii=False),
    )
    db.add(knowledge)
    auto_pipeline_knowledge_id = None
    if table_meta.pipeline_id:
        p_result = await db.execute(
            select(DataPipeline).where(DataPipeline.id == table_meta.pipeline_id)
        )
        pipeline = p_result.scalar_one_or_none()
        if pipeline:
            pipeline_knowledge = await _ensure_pipeline_in_context(db, task_id, pipeline)
            if pipeline_knowledge:
                auto_pipeline_knowledge_id = pipeline_knowledge.id
    await db.commit()
    await db.refresh(knowledge)
    return {
        "status": "added",
        "knowledge_id": knowledge.id,
        "auto_added_pipeline_knowledge_id": auto_pipeline_knowledge_id,
    }


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


# ━━━ Table Freshness & Refresh ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/tables/{table_id}/freshness")
async def check_table_freshness_endpoint(
    table_id: str,
    db: AsyncSession = Depends(get_db),
):
    """检查指定表的数据新鲜度"""
    from app.services.freshness import check_table_freshness

    result = await db.execute(select(DuckDBTable).where(DuckDBTable.id == table_id))
    table_meta = result.scalar_one_or_none()
    if not table_meta:
        raise HTTPException(status_code=404, detail="Table not found")

    freshness = await check_table_freshness(table_meta.table_name, db)
    return {
        "table_name": table_meta.table_name,
        "is_fresh": freshness.is_fresh,
        "reason": freshness.reason,
        "staleness_hours": freshness.staleness_hours,
        "max_staleness_hours": freshness.max_staleness_hours,
        "latest_data_date": freshness.latest_data_date,
        "can_refresh": freshness.can_refresh,
    }


@router.post("/tables/{table_id}/refresh")
async def refresh_table_endpoint(
    table_id: str,
    db: AsyncSession = Depends(get_db),
):
    """手动触发表数据刷新（执行关联的 Pipeline）"""
    from app.services.pipeline_executor import execute_pipeline

    result = await db.execute(select(DuckDBTable).where(DuckDBTable.id == table_id))
    table_meta = result.scalar_one_or_none()
    if not table_meta:
        raise HTTPException(status_code=404, detail="Table not found")

    if not table_meta.pipeline_id:
        raise HTTPException(status_code=400, detail="Table has no associated pipeline")

    p_result = await db.execute(
        select(DataPipeline).where(DataPipeline.id == table_meta.pipeline_id)
    )
    pipeline = p_result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Associated pipeline not found")

    exec_result = await execute_pipeline(pipeline, table_meta, db)

    return {
        "success": exec_result.success,
        "message": exec_result.message,
        "rows_written": exec_result.rows_written,
        "total_rows": exec_result.total_rows,
        "latest_data_date": exec_result.latest_data_date,
        "execution_time": exec_result.execution_time,
        "error": exec_result.error,
    }


@router.get("/tables/stale")
async def list_stale_tables(db: AsyncSession = Depends(get_db)):
    """列出所有过期的 auto-refresh 表"""
    from app.services.freshness import check_stale_tables

    stale = await check_stale_tables(db)
    return {
        table_name: {
            "is_fresh": fr.is_fresh,
            "reason": fr.reason,
            "staleness_hours": fr.staleness_hours,
            "max_staleness_hours": fr.max_staleness_hours,
            "latest_data_date": fr.latest_data_date,
        }
        for table_name, fr in stale.items()
    }



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
        freshness_policy_json=body.freshness_policy,
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


@router.post("/pipelines/{pipeline_id}/execute")
async def execute_pipeline_endpoint(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db),
):
    """手动执行指定 Pipeline"""
    from app.services.pipeline_executor import execute_pipeline

    p_result = await db.execute(
        select(DataPipeline).where(DataPipeline.id == pipeline_id)
    )
    pipeline = p_result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    # 查找目标表，不存在则创建元数据占位
    t_result = await db.execute(
        select(DuckDBTable).where(DuckDBTable.table_name == pipeline.target_table_name)
    )
    table_meta = t_result.scalar_one_or_none()

    if not table_meta:
        table_meta = DuckDBTable(
            table_name=pipeline.target_table_name,
            display_name=pipeline.name,
            description=pipeline.description,
            source_type=pipeline.source_type,
            pipeline_id=pipeline.id,
            status="refreshing",
        )
        db.add(table_meta)
        await db.commit()
        await db.refresh(table_meta)

    exec_result = await execute_pipeline(pipeline, table_meta, db)

    return {
        "success": exec_result.success,
        "message": exec_result.message,
        "rows_written": exec_result.rows_written,
        "total_rows": exec_result.total_rows,
        "latest_data_date": exec_result.latest_data_date,
        "execution_time": exec_result.execution_time,
        "error": exec_result.error,
    }