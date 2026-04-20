# backend/app/services/task_executor.py

"""
Task 执行调度器
根据 task_type 分发到对应执行引擎，统一 SSE 输出协议
"""

import json
import logging
from typing import Any, AsyncGenerator, Mapping

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Task, Asset, DataPipeline, DuckDBTable

from app.services.execution_helpers import (
    HeartbeatEvent,
    is_heartbeat_event,
    run_with_heartbeat,
)


logger = logging.getLogger(__name__)


def _sse(data: Mapping[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

TaskExecutorEvent = dict[str, Any] | HeartbeatEvent

async def execute_task_events(
    task_id: str,
    db: AsyncSession,
    env_vars_override: dict[str, str] | None = None,
    user_message: str | None = None,
    model_override: tuple[str, str] | None = None,
) -> AsyncGenerator[TaskExecutorEvent, None]:
    """
    统一任务执行入口（内部事件版本）
    
    返回原生 dict event，供 execution_registry 直接存储
    """
    task = await db.get(Task, task_id)
    if not task:
        yield {"type": "error", "content": "Task not found"}
        yield {"type": "done"}
        return
    if task.task_type == "ad_hoc":
        yield {"type": "error", "content": "Ad-hoc tasks use /api/chat/stream"}
        yield {"type": "done"}
        return
    # 分发
    if task.task_type == "script":
        if not task.asset_id:
            yield {"type": "error", "content": "script task requires a bound asset"}
            yield {"type": "done"}
            return
        asset = await db.get(Asset, task.asset_id)
        if not asset:
            yield {"type": "error", "content": "Bound asset not found"}
            yield {"type": "done"}
            return
        async for event in _execute_deterministic_events(
            task, asset, db, env_vars_override
        ):
            yield event
    
    elif task.task_type == "pipeline":
        if not task.pipeline_id:
            yield {"type": "error", "content": "pipeline task requires a bound pipeline"}
            yield {"type": "done"}
            return
        pipeline = await db.get(DataPipeline, task.pipeline_id)
        if not pipeline:
            yield {"type": "error", "content": "Bound pipeline not found"}
            yield {"type": "done"}
            return
        result = await db.execute(
            select(DuckDBTable).where(DuckDBTable.pipeline_id == pipeline.id)
        )
        table = result.scalar_one_or_none()
        if not table:
            yield {"type": "error", "content": "Target DuckDB table metadata not found for pipeline"}
            yield {"type": "done"}
            return
        async for event in _execute_pipeline_task_events(task, pipeline, table, db):
            yield event
    
    elif task.task_type == "routine":
        if not task.asset_id:
            yield {"type": "error", "content": "routine task requires a bound asset"}
            yield {"type": "done"}
            return
        asset = await db.get(Asset, task.asset_id)
        if not asset:
            yield {"type": "error", "content": "Bound asset not found"}
            yield {"type": "done"}
            return
        async for event in _execute_routine_events(
            task, asset, db, user_message, model_override
        ):
            yield event
    
    else:
        yield {"type": "error", "content": f"Unknown task_type: {task.task_type}"}
        yield {"type": "done"}
        
async def _execute_deterministic_events(
    task: Task,
    asset: Asset,
    db: AsyncSession,
    env_vars_override: dict[str, str] | None,
) -> AsyncGenerator[TaskExecutorEvent, None]:
    """script 执行：原生 dict event 版本"""
    from app.services.script_runner import run_script_events
    data_source_ids = json.loads(task.data_source_ids) if task.data_source_ids else []
    async for event in run_script_events(
        task_id=task.id,
        asset=asset,
        db=db,
        env_vars_override=env_vars_override,
        data_source_ids=data_source_ids,
    ):
        yield event

async def _execute_pipeline_task_events(
    task: Task,
    pipeline: DataPipeline,
    table: DuckDBTable,
    db: AsyncSession,
) -> AsyncGenerator[TaskExecutorEvent, None]:
    """pipeline 执行：原生 dict event 版本"""
    from datetime import datetime
    from app.services.pipeline_executor import execute_pipeline
    from app.services.execution_helpers import run_with_heartbeat
    
    yield {
        "type": "text",
        "content": f"🚀 Executing pipeline: **{pipeline.name}**\n",
    }
    
    from app.services.pipeline_executor import PipelineExecutionResult
    result: PipelineExecutionResult | None = None
    async for item in run_with_heartbeat(
        execute_pipeline(pipeline=pipeline, table=table, db=db),
        interval=15.0,
        message="pipeline_running",
    ):
        if is_heartbeat_event(item):
            yield item
            continue
        if isinstance(item, PipelineExecutionResult):
            result = item
    if result is None:
        task.last_run_at = datetime.now()
        task.last_run_status = "failed"
        await db.commit()
        yield {
            "type": "error",
            "content": "Pipeline execution returned no result",
        }
        yield {"type": "done"}
        return
    pipeline_result = result
    task.last_run_at = datetime.now()
    task.last_run_status = "success" if pipeline_result.success else "failed"
    await db.commit()
    yield {
        "type": "tool_result",
        "success": pipeline_result.success,
        "output": pipeline_result.message,
        "error": pipeline_result.error,
        "time": pipeline_result.execution_time,
    }
    if pipeline_result.success:
        yield {
            "type": "text",
            "content": f"\n✅ {pipeline_result.message}",
        }
    else:
        yield {
            "type": "text",
            "content": f"\n❌ {pipeline_result.message}",
        }
    yield {"type": "done"}

async def _execute_routine_events(
    task: Task,
    asset: Asset,
    db: AsyncSession,
    user_message: str | None,
    model_override: tuple[str, str] | None,
) -> AsyncGenerator[TaskExecutorEvent, None]:
    """
    routine 执行：原生 dict event 版本

    现在直接消费 run_agent_events()，不再需要 parse SSE。
    """
    from app.services.agent import run_agent_events

    if asset.asset_type != "sop" or not asset.content_markdown:
        yield {
            "type": "error",
            "content": "Routine requires a valid SOP asset with content",
        }
        yield {"type": "done"}
        return

    effective_message = (
        user_message
        or "Please execute the analysis according to the bound SOP."
    )

    async for event in run_agent_events(
        task_id=task.id,
        user_message=effective_message,
        db=db,
        mode="analyst",
        model_override=model_override,
    ):
        yield event

# ============================================================
# 保留：兼容层（SSE 版本）
# ============================================================
async def execute_task(
    task_id: str,
    db: AsyncSession,
    env_vars_override: dict[str, str] | None = None,
    user_message: str | None = None,
    model_override: tuple[str, str] | None = None,
) -> AsyncGenerator[str, None]:
    """
    兼容层：包装 execute_task_events() 为 SSE 字符串输出
    
    保留此函数是为了向后兼容直接 SSE 流式输出的场景
    """
    async for event in execute_task_events(
        task_id=task_id,
        db=db,
        env_vars_override=env_vars_override,
        user_message=user_message,
        model_override=model_override,
    ):
        yield _sse(event)

