# backend/app/routers/tasks.py
"""Task 管理 API"""

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException, Request
from fastapi.responses import Response, StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.database import get_db
from app.tenant_context import open_tenant_session
from app.models import Task, Step, Knowledge, DataPipeline, JupyterConfig
from app.schemas import (
    TaskCreate, 
    TaskUpdate, 
    TaskResponse, 
    TaskModeUpdate, 
    ExecuteTaskRequest, 
    RuntimeSwitchRequest,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

def _json_sse(data: dict) -> str:
    import json as _json
    return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_task_in_background(
    *,
    execution_id: str,
    task_id: str,
    env_vars_override: dict[str, str] | None,
    user_message: str | None,
) -> None:
    """
    后台执行 task，并将事件写入内存 registry。
    注意：
    - execution 元信息只在 registry 内存中
    - 业务 Step / Task 状态仍由 execute_task 原逻辑写库
    """
    from app.database import async_session
    from app.services.task_executor import execute_task
    import asyncio
    from app.services.execution_registry import execution_registry

    try:
        async with open_tenant_session() as db:
            async for raw_event in execute_task(
                task_id=task_id,
                db=db,
                env_vars_override=env_vars_override,
                user_message=user_message,
            ):
                # execute_task 返回的是 SSE 字符串，这里反解成 dict 存入 registry
                if not raw_event.startswith("data: "):
                    continue
                payload = raw_event[6:].strip()
                if not payload:
                    continue
                try:
                    import json as _json
                    event_data = _json.loads(payload)
                except Exception:
                    continue
                await execution_registry.append_event(execution_id, event_data)

        await execution_registry.mark_completed(execution_id)
        
    except asyncio.CancelledError:
        await execution_registry.append_event(
            execution_id,
            {"type": "error", "content": "Execution cancelled"},
        )
        await execution_registry.append_event(
            execution_id,
            {"type": "done"},
        )
        await execution_registry.mark_cancelled(execution_id)
        raise
    except Exception as e:
        await execution_registry.append_event(
            execution_id,
            {"type": "error", "content": str(e)},
        )
        await execution_registry.append_event(
            execution_id,
            {"type": "done"},
        )
        await execution_registry.mark_failed(execution_id, str(e))


async def _stream_execution_events(
    request: Request,
    *,
    execution_id: str,
) -> StreamingResponse:
    from app.services.execution_registry import execution_registry

    async def event_generator():
        after_seq = 0

        # 支持从 query 参数恢复，也支持 SSE Last-Event-ID（后面前端再接）
        try:
            after_seq_str = request.query_params.get("after_seq", "0")
            after_seq = int(after_seq_str)
        except ValueError:
            after_seq = 0

        while True:
            if await request.is_disconnected():
                break

            session = await execution_registry.get_session(execution_id)
            if not session:
                yield _json_sse({"type": "error", "content": "Execution session not found"})
                yield _json_sse({"type": "done"})
                break

            new_events = await execution_registry.read_events_after(execution_id, after_seq)

            if new_events:
                for event in new_events:
                    after_seq = event.seq
                    yield (
                        f"id: {event.seq}\n"
                        + _json_sse(event.data)
                    )

                if session.status in ("completed", "failed", "cancelled"):
                    # 如果最后状态已结束且已把事件吐完，就结束 SSE
                    latest_events = await execution_registry.read_events_after(execution_id, after_seq)
                    if not latest_events:
                        break
                continue

            if session.status in ("completed", "failed", "cancelled"):
                break

            # 没有新事件时等待一会儿；超时后发送 heartbeat
            await execution_registry.wait_for_updates(execution_id, timeout=15.0)

            if await request.is_disconnected():
                break

            yield _json_sse({"type": "heartbeat", "content": "execution_stream_alive"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("", response_model=TaskResponse)
async def create_task(body: TaskCreate, db: AsyncSession = Depends(get_db)):
    """创建新任务（支持类型化创建）"""
    import json as _json
    from fastapi import HTTPException
    from app.models import Asset
    # ── 校验绑定对象 ──
    if body.task_type == "ad_hoc":
        if body.asset_id or body.pipeline_id:
            raise HTTPException(
                status_code=400,
                detail="ad_hoc task should not have asset_id or pipeline_id",
            )
    elif body.task_type == "routine":
        if body.pipeline_id:
            raise HTTPException(
                status_code=400,
                detail="routine task should not have pipeline_id",
            )
        if body.asset_id:
            asset = await db.get(Asset, body.asset_id)
            if not asset:
                raise HTTPException(status_code=404, detail="Asset not found")
            if asset.asset_type != "sop":
                raise HTTPException(
                    status_code=400,
                    detail="routine task requires asset_type='sop'",
                )
    elif body.task_type == "script":
        if body.pipeline_id:
            raise HTTPException(
                status_code=400,
                detail="script task should not have pipeline_id",
            )
        if body.asset_id:
            asset = await db.get(Asset, body.asset_id)
            if not asset:
                raise HTTPException(status_code=404, detail="Asset not found")
            if asset.asset_type != "script" or asset.script_type != "general":
                raise HTTPException(
                    status_code=400,
                    detail="script task requires asset_type='script' and script_type='general'",
                )
    elif body.task_type == "pipeline":
        if body.asset_id:
            raise HTTPException(
                status_code=400,
                detail="pipeline task should not use asset_id",
            )
        if body.pipeline_id:
            pipeline = await db.get(DataPipeline, body.pipeline_id)
            if not pipeline:
                raise HTTPException(status_code=404, detail="DataPipeline not found")
        
    task = Task(
        title=body.title,
        description=body.description,
        task_type=body.task_type,
        asset_id=body.asset_id,
        pipeline_id=body.pipeline_id,
        data_source_ids=_json.dumps(body.data_source_ids, ensure_ascii=False),
    )
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
    import json as _json
    from fastapi import HTTPException
    from app.models import Asset

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if body.title is not None:
        task.title = body.title

    if body.description is not None:
        task.description = body.description

    if body.task_type is not None:
        task.task_type = body.task_type

    if body.data_source_ids is not None:
        task.data_source_ids = _json.dumps(body.data_source_ids, ensure_ascii=False)

    if body.asset_id is not None:
        if body.asset_id == "":
            task.asset_id = None
        else:
            if task.task_type == "pipeline":
                raise HTTPException(
                    status_code=400,
                    detail="pipeline task should not use asset_id",
                )
            asset = await db.get(Asset, body.asset_id)
            if not asset:
                raise HTTPException(status_code=404, detail="Asset not found")
            if task.task_type == "routine":
                if asset.asset_type != "sop":
                    raise HTTPException(
                        status_code=400,
                        detail="routine task requires asset_type='sop'",
                    )
            elif task.task_type == "script":
                if asset.asset_type != "script" or asset.script_type != "general":
                    raise HTTPException(
                        status_code=400,
                        detail="script task requires asset_type='script' and script_type='general'",
                    )
            task.asset_id = body.asset_id
    if body.pipeline_id is not None:
        if body.pipeline_id == "":
            task.pipeline_id = None
        else:
            if task.task_type != "pipeline":
                raise HTTPException(
                    status_code=400,
                    detail=f"{task.task_type} task should not use pipeline_id",
                )

            pipeline = await db.get(DataPipeline, body.pipeline_id)
            if not pipeline:
                raise HTTPException(status_code=404, detail="DataPipeline not found")

            task.pipeline_id = body.pipeline_id
            
    await db.commit()
    await db.refresh(task)
    return task

@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """删除任务（级联删除关联数据 + 后台清理磁盘文件）"""
    task = await db.get(Task, task_id)
    if not task:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Task not found")

    # ── 在删除 DB 前收集文件路径 ─────────────────────────
    result = await db.execute(
        select(Knowledge).where(Knowledge.task_id == task_id)
    )
    knowledge_file_paths = [
        k.file_path for k in result.scalars().all() if k.file_path
    ]

    # ── 级联删除 DB 记录 ────────────────────────────────
    await db.delete(task)
    await db.commit()

    # ── 清理内存态 execution session（如果存在） ─────────────
    try:
        from app.services.execution_registry import execution_registry
        session = await execution_registry.get_latest_session_by_task(task_id)
        if session and session.status == "running":
            await execution_registry.cancel_session(session.execution_id)
    except Exception:
        pass
    
    # ── 后台清理磁盘文件 ────────────────────────────────
    from app.services.cleanup import delete_task_files
    background_tasks.add_task(delete_task_files, task_id, knowledge_file_paths)

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
    return task

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

@router.get("/{task_id}/export")
async def export_task(
    task_id: str,
    format: str = Query(..., pattern="^(markdown|ipynb)$"),
    db: AsyncSession = Depends(get_db),
):
    """
    导出对话记录
    - format=markdown → 下载 .md 文件
    - format=ipynb    → 下载 .ipynb 文件
    """
    from fastapi import HTTPException
    from app.services.export_service import export_as_markdown, export_as_notebook
    import json
    # 获取 Task
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # 获取 Steps（按时间排序）
    result = await db.execute(
        select(Step)
        .where(Step.task_id == task_id)
        .order_by(Step.created_at.asc())
    )
    steps = list(result.scalars().all())
    # 获取 Knowledge
    result = await db.execute(
        select(Knowledge).where(Knowledge.task_id == task_id)
    )
    knowledge_items = list(result.scalars().all())
    # 安全文件名：替换不可用字符
    safe_title = "".join(
        c if c.isalnum() or c in (" ", "-", "_") else "_"
        for c in task.title
    ).strip()[:50]
    date_str = datetime.now().strftime("%Y%m%d")
    if format == "markdown":
        content = await export_as_markdown(task, steps, knowledge_items)
        filename = f"{safe_title}_{date_str}.md"
        return Response(
            content=content.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{_url_encode(filename)}"
            },
        )
    else:  # ipynb
        notebook = await export_as_notebook(task, steps, knowledge_items)
        content = json.dumps(notebook, ensure_ascii=False, indent=1)
        filename = f"{safe_title}_{date_str}.ipynb"
        return Response(
            content=content.encode("utf-8"),
            media_type="application/x-ipynb+json; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{_url_encode(filename)}"
            },
        )
    
@router.post("/{task_id}/execute")
async def execute_task_endpoint(
    task_id: str,
    body: ExecuteTaskRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    启动后台执行任务（Phase 2）
    
    - ad_hoc: 400, 请使用 /api/chat/stream
    - script/pipeline: 后台执行 + 内存事件流
    - routine: 暂时仍走老机制（Phase 3 再统一）
    """
    import asyncio
    from app.services.execution_registry import execution_registry

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.task_type == "ad_hoc":
        raise HTTPException(
            status_code=400,
            detail="Ad-hoc tasks should use /api/chat/stream endpoint",
        )

    if task.task_type == "routine":
        raise HTTPException(
            status_code=400,
            detail="Routine background execution will be enabled in Phase 3",
        )

    # 若已有正在运行的 execution，直接返回它，避免重复触发
    latest = await execution_registry.get_latest_session_by_task(task_id)
    if latest and latest.status == "running":
        return JSONResponse({
            "task_id": task_id,
            "execution_id": latest.execution_id,
            "status": latest.status,
            "task_type": task.task_type,
            "reused": True,
        })

    env_vars_override = body.env_vars_override if body else None
    user_message = body.user_message if body else None

    session = await execution_registry.create_session(
        task_id=task_id,
        task_type=task.task_type,
    )

    bg_task = asyncio.create_task(
        _run_task_in_background(
            execution_id=session.execution_id,
            task_id=task_id,
            env_vars_override=env_vars_override,
            user_message=user_message,
        )
    )
    await execution_registry.set_task(session.execution_id, bg_task)

    return JSONResponse(
        status_code=202,
        content={
            "task_id": task_id,
            "execution_id": session.execution_id,
            "status": session.status,
            "task_type": task.task_type,
            "reused": False,
        },
    )

@router.get("/{task_id}/executions/latest")
async def get_latest_execution(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    获取该 task 的最新 execution session（仅内存态）。
    用于页面刷新后恢复正在进行的执行。
    """
    from app.services.execution_registry import execution_registry

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    session = await execution_registry.get_latest_session_by_task(task_id)
    if not session:
        return {
            "task_id": task_id,
            "execution": None,
        }

    return {
        "task_id": task_id,
        "execution": {
            "execution_id": session.execution_id,
            "status": session.status,
            "task_type": session.task_type,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "finished_at": session.finished_at,
            "error": session.error,
            "last_seq": session.next_seq - 1,
        },
    }

@router.get("/{task_id}/executions/{execution_id}/events")
async def stream_execution_events(
    task_id: str,
    execution_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    消费某次 execution 的事件流。
    - after_seq: 从某个序号之后继续追事件
    - execution 信息只在内存，不落库
    """
    from app.services.execution_registry import execution_registry

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    session = await execution_registry.get_session(execution_id)
    if not session or session.task_id != task_id:
        raise HTTPException(status_code=404, detail="Execution session not found")

    return await _stream_execution_events(
        request,
        execution_id=execution_id,
    )

@router.post("/{task_id}/executions/{execution_id}/cancel")
async def cancel_execution(
    task_id: str,
    execution_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    取消某次后台 execution（仅内存态 session）。
    注意：
    - execution 元信息不落库
    - 最终是否立即停止，取决于当前执行点是否可取消
    """
    from app.services.execution_registry import execution_registry

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    session = await execution_registry.get_session(execution_id)
    if not session or session.task_id != task_id:
        raise HTTPException(status_code=404, detail="Execution session not found")

    if session.status != "running":
        return {
            "task_id": task_id,
            "execution_id": execution_id,
            "status": session.status,
            "cancelled": False,
            "message": f"Execution is already {session.status}",
        }

    ok = await execution_registry.cancel_session(execution_id)

    return {
        "task_id": task_id,
        "execution_id": execution_id,
        "status": "cancelling" if ok else session.status,
        "cancelled": ok,
    }

@router.put("/{task_id}/runtime")
async def switch_task_runtime(
    task_id: str,
    body: RuntimeSwitchRequest,
    db: AsyncSession = Depends(get_db),
):
    """切换 Task 的执行运行时，清除 Knowledge 和中间变量"""
    from app.models import Knowledge, JupyterConfig
    from app.config import UPLOADS_DIR
    from sqlalchemy import select
    import shutil
    import os
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    old_backend = task.execution_backend
    new_backend = body.execution_backend
    if old_backend == new_backend:
        return {"ok": True, "message": "No change", "cleared": False}
    # 验证新 backend
    if new_backend != "local":
        if not new_backend.startswith("jupyter:"):
            raise HTTPException(400, "Invalid format. Use 'local' or 'jupyter:{config_id}'")
        config_id = new_backend.split(":", 1)[1]
        config = await db.get(JupyterConfig, config_id)
        if not config or config.status != "active":
            raise HTTPException(400, "Invalid or inactive Jupyter config")
    # 清除 Knowledge
    result = await db.execute(
        select(Knowledge).where(Knowledge.task_id == task_id)
    )
    knowledge_items = list(result.scalars().all())
    for k in knowledge_items:
        await db.delete(k)
    # 清除文件系统
    captures_dir = os.path.join(str(UPLOADS_DIR), task_id, "captures")
    if os.path.isdir(captures_dir):
        shutil.rmtree(captures_dir, ignore_errors=True)
    # Shutdown 旧 Jupyter kernel
    if old_backend.startswith("jupyter:"):
        try:
            from app.services.execution.resolver import get_backend
            old_be = get_backend(old_backend)
            await old_be.shutdown(task_id)
        except Exception:
            pass
    # 更新
    task.execution_backend = new_backend
    await db.commit()
    return {
        "ok": True,
        "message": f"Switched to {new_backend}",
        "cleared": True,
        "cleared_knowledge_count": len(knowledge_items),
    }



def _url_encode(filename: str) -> str:
    """RFC 5987 编码文件名，支持中文"""
    from urllib.parse import quote
    return quote(filename, safe="")

