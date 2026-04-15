# backend/app/routers/data_pipelines.py

"""Data Pipeline 管理 API"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import DataPipeline
from app.schemas import DataPipelineResponse

router = APIRouter(prefix="/api/data-pipelines", tags=["data-pipelines"])


@router.get("", response_model=list[DataPipelineResponse])
async def list_data_pipelines(db: AsyncSession = Depends(get_db)):
    """列出所有 Data Pipelines"""
    result = await db.execute(
        select(DataPipeline).order_by(DataPipeline.updated_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{pipeline_id}", response_model=DataPipelineResponse)
async def get_data_pipeline(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    from fastapi import HTTPException

    pipeline = await db.get(DataPipeline, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="DataPipeline not found")
    return pipeline