# backend/app/routers/visualizations.py

"""Visualization CRUD API"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Visualization
from app.schemas import VisualizationResponse

router = APIRouter(prefix="/api/visualizations", tags=["visualizations"])


@router.get("/task/{task_id}", response_model=list[VisualizationResponse])
async def list_visualizations(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取指定 Task 下的所有可视化"""
    result = await db.execute(
        select(Visualization)
        .where(Visualization.task_id == task_id)
        .order_by(Visualization.created_at.asc())
    )
    return result.scalars().all()


@router.get("/{viz_id}", response_model=VisualizationResponse)
async def get_visualization(viz_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个可视化详情"""
    result = await db.execute(
        select(Visualization).where(Visualization.id == viz_id)
    )
    viz = result.scalar_one_or_none()
    if not viz:
        raise HTTPException(status_code=404, detail="Visualization not found")
    return viz


@router.delete("/{viz_id}")
async def delete_visualization(viz_id: str, db: AsyncSession = Depends(get_db)):
    """删除可视化"""
    result = await db.execute(
        select(Visualization).where(Visualization.id == viz_id)
    )
    viz = result.scalar_one_or_none()
    if not viz:
        raise HTTPException(status_code=404, detail="Visualization not found")
    await db.delete(viz)
    await db.commit()
    return {"success": True}