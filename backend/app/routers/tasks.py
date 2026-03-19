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


@router.post("/{task_id}/auto-rename", response_model=TaskResponse)
async def auto_rename_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    自动重命名任务：根据对话历史用 misc/default agent 生成简短标题
    整体 try/except 保护，失败时静默返回原 task
    """
    import logging
    from app.models import Step

    logger = logging.getLogger(__name__)

    task = await db.get(Task, task_id)
    if not task:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        # 获取最近对话历史（最多10条 Step）
        result = await db.execute(
            select(Step)
            .where(Step.task_id == task_id)
            .order_by(Step.created_at.asc())
            .limit(10)
        )
        steps = result.scalars().all()

        # 拼接对话摘要
        conversation_lines: list[str] = []
        for step in steps:
            if step.step_type == "user_message":
                conversation_lines.append(f"User: {step.content[:200]}")
            elif step.step_type == "assistant_message":
                conversation_lines.append(f"Assistant: {step.content[:200]}")

        if not conversation_lines:
            logger.info(f"Auto-rename skipped for task {task_id}: no conversation")
            return task

        # 获取 LLM 客户端：misc → default 回退
        from app.services.agent import _get_client_from_db

        config = await _get_client_from_db(db, "misc")
        if config is None:
            config = await _get_client_from_db(db, "default")
        if config is None:
            logger.info(f"Auto-rename skipped for task {task_id}: no LLM config")
            return task

        client, model_id = config

        prompt = (
            "Based on the following conversation, generate a concise task title "
            "(max 30 characters, no quotes, no punctuation at end).\n"
            "The title should capture the main topic or goal.\n\n"
            "Conversation:\n"
            + "\n".join(conversation_lines)
            + "\n\nReply with ONLY the title text, nothing else."
        )

        response = await client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            reasoning_effort="minimal", # type: ignore
            temperature=0.0,
            max_tokens=120,
        )
        new_title = (response.choices[0].message.content or "").strip().strip("\"'")
        logger.info(f"Auto-rename LLM returned: '{new_title}' for task {task_id}")
        print("Original Response:", repr(response))
        print("Auto-rename LLM returned:", repr(new_title))

        if not new_title or len(new_title) > 50:
            return task

        # 重新获取 task 以确保 session 中对象有效，避免 stale object
        task = await db.get(Task, task_id)
        if task is None:
            return task  # type: ignore
        task.title = new_title
        await db.commit()
        await db.refresh(task)
        logger.info(f"Auto-rename succeeded: task {task_id} → '{new_title}'")

    except Exception as e:
        logger.warning(f"Auto-rename failed for task {task_id}: {e}", exc_info=True)
        # 回滚脏状态，防止后续请求受影响
        await db.rollback()
        # 重新获取干净的 task 对象返回
        task = await db.get(Task, task_id)

    return task