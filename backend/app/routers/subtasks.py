# backend/app/routers/subtasks.py

"""SubTask管理API"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import SubTask, Task
from app.schemas import SubTaskResponse, SubTaskCreate, SubTaskUpdate, PlanConfirmation

router = APIRouter(prefix="/api/subtasks", tags=["subtasks"])


@router.get("/{task_id}", response_model=list[SubTaskResponse])
async def get_subtasks(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取Task的所有SubTask"""
    result = await db.execute(
        select(SubTask)
        .where(SubTask.task_id == task_id)
        .order_by(SubTask.order.asc())
    )
    return result.scalars().all()


@router.post("/{task_id}/confirm-plan")
async def confirm_plan(
    task_id: str,
    body: PlanConfirmation,
    db: AsyncSession = Depends(get_db),
):
    """
    用户确认或修改Plan
    
    如果confirmed=True，根据提供的subtasks创建SubTask记录
    如果confirmed=False，返回modifications供PlanAgent重新生成
    """
    # 查找Task
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if body.confirmed:
        if not body.subtasks:
            raise HTTPException(
                status_code=400,
                detail="subtasks data required when confirming plan"
            )
        
        # 删除旧的SubTask（如果用户重新确认Plan）
        result = await db.execute(
            select(SubTask).where(SubTask.task_id == task_id)
        )
        old_subtasks = result.scalars().all()
        for old_subtask in old_subtasks:
            await db.delete(old_subtask)
        
        # 创建新的SubTask
        for subtask_data in body.subtasks:
            subtask = SubTask(
                task_id=task_id,
                title=subtask_data.title,
                description=subtask_data.description,
                order=subtask_data.order,
                status="pending",
            )
            db.add(subtask)
        
        # 标记Plan已确认
        task.plan_confirmed = True
        await db.commit()
        
        return {"success": True, "message": "Plan confirmed and subtasks created"}
    
    else:
        # 用户要求修改Plan
        return {
            "success": False,
            "message": "Plan rejected",
            "modifications": body.modifications,
        }

@router.post("/{subtask_id}/start")
async def start_subtask(subtask_id: str, db: AsyncSession = Depends(get_db)):
    """开始执行SubTask"""
    result = await db.execute(select(SubTask).where(SubTask.id == subtask_id))
    subtask = result.scalar_one_or_none()
    if not subtask:
        raise HTTPException(status_code=404, detail="SubTask not found")
    
    subtask.status = "running"
    
    # 更新Task的current_subtask_id
    result = await db.execute(select(Task).where(Task.id == subtask.task_id))
    task = result.scalar_one_or_none()
    if task:
        task.current_subtask_id = subtask_id
    
    await db.commit()
    
    return {"success": True, "subtask_id": subtask_id}


@router.post("/{subtask_id}/complete")
async def complete_subtask(
    subtask_id: str,
    result_summary: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """完成SubTask"""
    result = await db.execute(select(SubTask).where(SubTask.id == subtask_id))
    subtask = result.scalar_one_or_none()
    if not subtask:
        raise HTTPException(status_code=404, detail="SubTask not found")
    
    subtask.status = "completed"
    if result_summary:
        subtask.result = result_summary
    
    await db.commit()
    
    return {"success": True, "subtask_id": subtask_id}

@router.get("/detail/{subtask_id}", response_model=SubTaskResponse)
async def get_subtask_detail(subtask_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个SubTask详情（包含关联的Steps）"""
    result = await db.execute(select(SubTask).where(SubTask.id == subtask_id))
    subtask = result.scalar_one_or_none()
    
    if not subtask:
        raise HTTPException(status_code=404, detail="SubTask not found")
    
    return subtask

@router.patch("/{subtask_id}", response_model=SubTaskResponse)
async def update_subtask(
    subtask_id: str,
    data: SubTaskUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新SubTask状态或结果"""
    result = await db.execute(select(SubTask).where(SubTask.id == subtask_id))
    subtask = result.scalar_one_or_none()
    
    if not subtask:
        raise HTTPException(status_code=404, detail="SubTask not found")
    
    if data.title is not None:
        subtask.title = data.title
    if data.description is not None:
        subtask.description = data.description
    if data.status is not None:
        subtask.status = data.status
    if data.result is not None:
        subtask.result = data.result
    
    await db.commit()
    await db.refresh(subtask)
    
    return subtask
