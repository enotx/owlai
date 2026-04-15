# backend/app/services/task_executor.py

"""
Task 执行调度器
根据 task_type 分发到对应执行引擎，统一 SSE 输出协议
"""

import json
import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


from app.models import Task, Asset, DataPipeline, DuckDBTable

logger = logging.getLogger(__name__)


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def execute_task(
    task_id: str,
    db: AsyncSession,
    env_vars_override: dict[str, str] | None = None,
    user_message: str | None = None,
    model_override: tuple[str, str] | None = None,
) -> AsyncGenerator[str, None]:
    """
    统一任务执行入口。

    根据 task.task_type 分发：
    - ad_hoc   → 拒绝，应走 /chat/stream
    - script   → script_runner (LLM 不介入)
    - pipeline → script_runner (LLM 不介入)
    - routine  → run_agent_stream (SOP 注入 context)
    """
    task = await db.get(Task, task_id)
    if not task:
        yield _sse({"type": "error", "content": "Task not found"})
        yield _sse({"type": "done"})
        return

    if task.task_type == "ad_hoc":
        yield _sse({"type": "error", "content": "Ad-hoc tasks use /api/chat/stream"})
        yield _sse({"type": "done"})
        return

    # ── 校验 asset 绑定 ──
    # ── 分发 ──
    if task.task_type == "script":
        if not task.asset_id:
            yield _sse({"type": "error", "content": "script task requires a bound asset"})
            yield _sse({"type": "done"})
            return
        asset = await db.get(Asset, task.asset_id)
        if not asset:
            yield _sse({"type": "error", "content": "Bound asset not found"})
            yield _sse({"type": "done"})
            return
        async for event in _execute_deterministic(
            task, asset, db, env_vars_override
        ):
            yield event
    elif task.task_type == "pipeline":
        if not task.pipeline_id:
            yield _sse({"type": "error", "content": "pipeline task requires a bound pipeline"})
            yield _sse({"type": "done"})
            return
        pipeline = await db.get(DataPipeline, task.pipeline_id)
        if not pipeline:
            yield _sse({"type": "error", "content": "Bound pipeline not found"})
            yield _sse({"type": "done"})
            return
        result = await db.execute(
            select(DuckDBTable).where(DuckDBTable.pipeline_id == pipeline.id)
        )
        table = result.scalar_one_or_none()
        if not table:
            yield _sse({"type": "error", "content": "Target DuckDB table metadata not found for pipeline"})
            yield _sse({"type": "done"})
            return
        async for event in _execute_pipeline_task(task, pipeline, table, db):
            yield event
    elif task.task_type == "routine":
        if not task.asset_id:
            yield _sse({"type": "error", "content": "routine task requires a bound asset"})
            yield _sse({"type": "done"})
            return
        asset = await db.get(Asset, task.asset_id)
        if not asset:
            yield _sse({"type": "error", "content": "Bound asset not found"})
            yield _sse({"type": "done"})
            return
        async for event in _execute_routine(
            task, asset, db, user_message, model_override
        ):
            yield event

    else:
        yield _sse({"type": "error", "content": f"Unknown task_type: {task.task_type}"})
        yield _sse({"type": "done"})


async def _execute_deterministic(
    task: Task,
    asset: Asset,
    db: AsyncSession,
    env_vars_override: dict[str, str] | None,
) -> AsyncGenerator[str, None]:
    """script / pipeline 执行：旁路 LLM，直接跑代码"""
    from app.services.script_runner import run_script

    data_source_ids = json.loads(task.data_source_ids) if task.data_source_ids else []

    async for event in run_script(
        task_id=task.id,
        asset=asset,
        db=db,
        env_vars_override=env_vars_override,
        data_source_ids=data_source_ids,
    ):
        yield event


async def _execute_routine(
    task: Task,
    asset: Asset,
    db: AsyncSession,
    user_message: str | None,
    model_override: tuple[str, str] | None,
) -> AsyncGenerator[str, None]:
    """
    routine 执行：SOP 驱动的 Agent 分析。
    
    关键：复用 run_agent_stream() 获得完整的 step 持久化能力。
    SOP 通过 context 注入，在 AnalystAgent 构建 system prompt 时读取。
    """
    from app.services.agent import run_agent_stream
    from app.services.context_builder import format_sop_context

    # 校验
    if asset.asset_type != "sop" or not asset.content_markdown:
        yield _sse({
            "type": "error",
            "content": "Routine requires a valid SOP asset with content",
        })
        yield _sse({"type": "done"})
        return

    effective_message = (
        user_message
        or "Please execute the analysis according to the bound SOP."
    )

    # run_agent_stream 会自动保存 user step、调 orchestrator、持久化所有 step
    # 我们只需要确保 SOP 通过某种方式传递到 AnalystAgent
    # 方案：在 Task 上挂载临时属性，agent 链路中读取
    # 但这不够干净。更好的方式是让 run_agent_stream 接受额外 context

    async for event in run_agent_stream(
        task_id=task.id,
        user_message=effective_message,
        db=db,
        mode="analyst",
        model_override=model_override,
    ):
        yield event
        
async def _execute_pipeline_task(
    task: Task,
    pipeline: DataPipeline,
    table: DuckDBTable,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """pipeline 执行：走专用 pipeline_executor"""
    from datetime import datetime
    from app.services.pipeline_executor import execute_pipeline

    yield _sse({
        "type": "text",
        "content": f"🚀 Executing pipeline: **{pipeline.name}**\n",
    })

    result = await execute_pipeline(
        pipeline=pipeline,
        table=table,
        db=db,
    )

    task.last_run_at = datetime.now()
    task.last_run_status = "success" if result.success else "failed"
    await db.commit()

    yield _sse({
        "type": "tool_result",
        "success": result.success,
        "output": result.message,
        "error": result.error,
        "time": result.execution_time,
    })

    if result.success:
        yield _sse({
            "type": "text",
            "content": f"\n✅ {result.message}",
        })
    else:
        yield _sse({
            "type": "text",
            "content": f"\n❌ {result.message}",
        })

    yield _sse({"type": "done"})