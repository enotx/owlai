# backend/app/routers/tasks.py
"""Task 管理 API（占位实现）"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Task
from app.schemas import TaskCreate, TaskUpdate, TaskResponse, TaskModeUpdate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse)
async def create_task(body: TaskCreate, db: AsyncSession = Depends(get_db)):
    """创建新任务"""
    task = Task(title=body.title, description=body.description)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.get("", response_model=list[TaskResponse])
async def list_tasks(db: AsyncSession = Depends(get_db)):
    """获取任务列表"""
    result = await db.execute(select(Task).order_by(Task.updated_at.desc()))
    return result.scalars().all()


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取任务详情"""
    task = await db.get(Task, task_id)
    if not task:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, body: TaskUpdate, db: AsyncSession = Depends(get_db)):
    """更新任务"""
    task = await db.get(Task, task_id)
    if not task:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Task not found")
    if body.title is not None:
        task.title = body.title
    if body.description is not None:
        task.description = body.description
    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}")
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """删除任务（级联删除关联数据）"""
    task = await db.get(Task, task_id)
    if not task:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Task not found")
    await db.delete(task)
    await db.commit()
    return {"detail": "Task deleted"}

@router.patch("/{task_id}/mode", response_model=TaskResponse)
async def update_task_mode(
    task_id: str,
    data: TaskModeUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    切换Task的执行模式
    
    支持在执行过程中动态切换模式：
    - auto → plan/analyst
    - plan → analyst (跳过Plan阶段)
    - analyst → plan (重新规划)
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    
    if not task:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Task not found")
    
    old_mode = task.mode
    task.mode = data.mode
    
    # 如果切换到plan模式，重置plan_confirmed标志
    if data.mode == "plan" and old_mode != "plan":
        task.plan_confirmed = False
        # 清空current_subtask_id
        task.current_subtask_id = None
    
    await db.commit()
    await db.refresh(task)
