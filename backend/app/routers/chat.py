"""Chat 对话 API —— ReAct Agent + 后台执行"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.tenant_context import open_tenant_session
from app.models import Step, Task, Visualization
from app.schemas import ChatRequest, StepResponse
from app.services.agent import run_agent_events
from app.services.execution_registry import execution_registry
import asyncio
import os
import json as _json
from datetime import datetime
from typing import Any, Mapping, Sequence, cast, Dict
from app.tenant_context import get_uploads_dir
router = APIRouter(prefix="/api/chat", tags=["chat"])
# ── 后台 chat execution runner ─────────────────────────────────
async def _run_chat_in_background(
    execution_id: str,
    task_id: str,
    user_message: str,
    mode: str | None,
    model_override: tuple[str, str] | None,
) -> None:
    """后台执行 agent，事件写入 ExecutionRegistry"""
    try:
        async with open_tenant_session() as db:
            async for event in run_agent_events(
                task_id=task_id,
                user_message=user_message,
                db=db,
                mode=mode,
                model_override=model_override,
            ):
                await execution_registry.append_event(execution_id, event)
                if event.get("type") == "done":
                    await execution_registry.mark_completed(execution_id)
                    return
        # Generator 正常结束但没有 done event（防御性）
        await execution_registry.mark_completed(execution_id)
    except asyncio.CancelledError:
        await execution_registry.append_event(execution_id, {
            "type": "error", "content": "Execution cancelled",
        })
        await execution_registry.append_event(execution_id, {
            "type": "done", "steps": [],
        })
        await execution_registry.mark_cancelled(execution_id)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await execution_registry.append_event(execution_id, {
            "type": "error", "content": f"Agent error: {str(e)}",
        })
        await execution_registry.append_event(execution_id, {
            "type": "done", "steps": [],
        })
        await execution_registry.mark_failed(execution_id, str(e))
# ── SSE 流式对话（后台执行版） ────────────────────────────────
@router.post("/stream")
async def stream_message(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    启动后台 chat execution，返回 execution_id。
    前端通过 GET /tasks/{task_id}/executions/{execution_id}/events 消费事件流。
    """
    task_id = body.task_id
    mode = body.mode
    # 验证 Task 存在
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task_type = task.task_type or "ad_hoc"
    # 检查是否有正在运行的 execution（防止重复启动）
    existing = await execution_registry.get_latest_session_by_task(task_id)
    if existing and existing.status == "running":
        return JSONResponse({
            "task_id": task_id,
            "execution_id": existing.execution_id,
            "status": "running",
            "task_type": task_type,
            "reused": True,
        })
    # 创建 execution session
    session = await execution_registry.create_session(task_id, task_type)
    # 解析 model override
    model_override = None
    if body.model_override:
        model_override = (body.model_override.provider_id, body.model_override.model_id)
    # 启动后台任务
    bg_task = asyncio.create_task(
        _run_chat_in_background(
            execution_id=session.execution_id,
            task_id=task_id,
            user_message=body.message,
            mode=mode,
            model_override=model_override,
        )
    )
    await execution_registry.set_task(session.execution_id, bg_task)
    return JSONResponse({
        "task_id": task_id,
        "execution_id": session.execution_id,
        "status": "running",
        "task_type": task_type,
        "reused": False,
    })


# ── 历史记录 ───────────────────────────────────────────────────
@router.get("/history", response_model=list[StepResponse])
async def get_history(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取指定 Task 的对话历史"""
    result = await db.execute(
        select(Step).where(Step.task_id == task_id).order_by(Step.created_at.asc())
    )
    return result.scalars().all()


# ── 获取 Step 中捕获的 DataFrame 预览数据 ──────────────────
@router.get("/steps/{step_id}/dataframe/{df_name}")
async def get_step_dataframe(
    step_id: str,
    df_name: str,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
):
    """返回某个 tool_use Step 中捕获的 DataFrame 数据（columns + rows），支持 limit 分页"""
    import os, json as _json
    from fastapi import HTTPException

    # 查找 Step
    result = await db.execute(select(Step).where(Step.id == step_id))
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    if step.step_type != "tool_use" or not step.code_output:
        raise HTTPException(status_code=400, detail="Step has no code execution data")

    try:
        output_data = _json.loads(step.code_output)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid code_output format")

    dataframes_meta = output_data.get("dataframes", [])
    target = None
    for df_meta in dataframes_meta:
        if df_meta.get("name") == df_name:
            target = df_meta
            break
    if not target:
        raise HTTPException(status_code=404, detail=f"DataFrame '{df_name}' not found in this step")

    capture_id = target.get("capture_id", "")
    capture_dir = os.path.join(str(get_uploads_dir()), step.task_id, "captures")
    file_path = os.path.join(capture_dir, f"{capture_id}_{df_name}.json")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Captured data file not found")

    with open(file_path, "r", encoding="utf-8") as f:
        data = _json.load(f)

    # 限制返回行数，附带总行数信息
    all_rows = data.get("rows", [])
    total_rows = len(all_rows)
    clamped_limit = max(1, min(limit, 10000))  # 硬上限 10000
    truncated_rows = all_rows[:clamped_limit]

    return {
        "columns": data.get("columns", []),
        "rows": truncated_rows,
        "total_rows": total_rows,
        "returned_rows": len(truncated_rows),
        "truncated": total_rows > clamped_limit,
    }
@router.get("/steps/{step_id}/dataframe/{df_name}/export")
async def export_step_dataframe(
    step_id: str,
    df_name: str,
    db: AsyncSession = Depends(get_db),
):
    """导出Step中捕获的DataFrame为Excel文件"""
    import pandas as pd
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    import tempfile
    from datetime import datetime
    
    # 1. 查找Step
    result = await db.execute(select(Step).where(Step.id == step_id))
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    
    if step.step_type != "tool_use" or not step.code_output:
        raise HTTPException(status_code=400, detail="Step has no code execution data")
    
    # 2. 从 code_output 解析 dataframes 元数据，找到 capture_id
    try:
        output_data = _json.loads(step.code_output)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid code_output format")
    
    dataframes_meta = output_data.get("dataframes", [])
    target = None
    for df_meta in dataframes_meta:
        if df_meta.get("name") == df_name:
            target = df_meta
            break
    
    if not target:
        raise HTTPException(status_code=404, detail=f"DataFrame '{df_name}' not found in this step")
    
    capture_id = target.get("capture_id", "")
    
    # 3. 组装文件路径
    capture_dir = os.path.join(str(get_uploads_dir()), step.task_id, "captures")
    file_path = os.path.join(capture_dir, f"{capture_id}_{df_name}.json")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Captured data file not found")
    
    # 安全检查
    real_path = os.path.realpath(file_path)
    uploads_real = os.path.realpath(str(get_uploads_dir()))
    if not real_path.startswith(uploads_real):
        raise HTTPException(status_code=403, detail="Access denied")
    
    try:
        # 4. 读取JSON数据
        with open(file_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        
        # 5. 转换为DataFrame
        df = pd.DataFrame(data["rows"], columns=data["columns"])
        
        # 6. 写入临时Excel文件
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".xlsx", delete=False
        ) as tmp:
            df.to_excel(tmp.name, index=False, engine="openpyxl")
            tmp_path = tmp.name
        
        # 7. 生成文件名（包含时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{df_name}_{timestamp}.xlsx"
        
        # 8. 返回文件
        return FileResponse(
            path=tmp_path,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

# ── 删除单条 Step ──────────────────────────────────────────────
@router.delete("/steps/{step_id}")
async def delete_step(
    step_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除指定的单条 Step，同时清理关联的 Visualization 和 capture 文件。
    """
    from fastapi import HTTPException
    
    # 1. 查找目标 Step
    result = await db.execute(select(Step).where(Step.id == step_id))
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    
    task_id = step.task_id
    
    # 2. 清理关联的 capture 文件
    if step.step_type == "tool_use" and step.code_output:
        try:
            output_data = _json.loads(step.code_output)
            for df_meta in output_data.get("dataframes", []):
                capture_id = df_meta.get("capture_id", "")
                df_name = df_meta.get("name", "")
                capture_dir = os.path.join(str(get_uploads_dir()), step.task_id, "captures")
                file_path = os.path.join(capture_dir, f"{capture_id}_{df_name}.json")
                if os.path.exists(file_path):
                    os.remove(file_path)
        except (_json.JSONDecodeError, Exception):
            pass
    
    # 3. 删除关联的 Visualization
    viz_result = await db.execute(
        select(Visualization).where(Visualization.step_id == step_id)
    )
    for viz in viz_result.scalars().all():
        await db.delete(viz)
    
    # 4. 删除 Step
    await db.delete(step)
    
    # 5. 清空 Task 的 compact context（因为历史已变化）
    task_result = await db.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalar_one_or_none()
    if task and task.compact_context:
        task.compact_context = None
        task.compact_anchor_step_id = None
        task.compact_anchor_created_at = None
    
    await db.commit()
    return {"deleted_ids": [step_id]}


# ── 重新生成：删除 Step 并返回需要重发的用户消息 ──────────────
@router.post("/steps/{step_id}/regenerate")
async def regenerate_from_step(
    step_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    找到指定 Step 之前最近的 user_message，
    删除该 user_message 及其之后的所有 Step，
    返回 user_message 内容供前端重新发送。
    """
    from fastapi import HTTPException

    # 1. 查找目标 Step
    result = await db.execute(select(Step).where(Step.id == step_id))
    target_step = result.scalar_one_or_none()
    if not target_step:
        raise HTTPException(status_code=404, detail="Step not found")

    task_id = target_step.task_id

    # 2. 查找该 Step 之前（含自身）最近的 user_message
    #    如果目标本身就是 user_message，则使用它
    if target_step.step_type == "user_message":
        anchor_step = target_step
    else:
        # 找到该 step 之前最近的 user_message
        result = await db.execute(
            select(Step)
            .where(
                Step.task_id == task_id,
                Step.step_type == "user_message",
                Step.created_at <= target_step.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            )
            .order_by(Step.created_at.desc())
            .limit(1)
        )
        anchor_step = result.scalar_one_or_none()
        if not anchor_step:
            raise HTTPException(
                status_code=400,
                detail="No user message found before this step"
            )

    user_message = anchor_step.content

    # 3. 删除 anchor_step 及其之后的所有 Step
    result = await db.execute(
        select(Step)
        .where(
            Step.task_id == task_id,
            Step.created_at >= anchor_step.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        )
        .order_by(Step.created_at.asc())
    )
    steps_to_delete = result.scalars().all()
    deleted_ids = [s.id for s in steps_to_delete]

    # 清理 capture 文件
    for step in steps_to_delete:
        if step.step_type == "tool_use" and step.code_output:
            try:
                output_data = _json.loads(step.code_output)
                for df_meta in output_data.get("dataframes", []):
                    capture_id = df_meta.get("capture_id", "")
                    df_name = df_meta.get("name", "")
                    capture_dir = os.path.join(str(get_uploads_dir()), step.task_id, "captures")
                    file_path = os.path.join(capture_dir, f"{capture_id}_{df_name}.json")
                    if os.path.exists(file_path):
                        os.remove(file_path)
            except (_json.JSONDecodeError, Exception):
                pass

    for step in steps_to_delete:
        await db.delete(step)

    # 清空 Task 的 compact context
    task_result = await db.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalar_one_or_none()
    if task and task.compact_context:
        task.compact_context = None
        task.compact_anchor_step_id = None
        task.compact_anchor_created_at = None

    await db.commit()

    return {
        "user_message": user_message,
        "task_id": task_id,
        "deleted_ids": deleted_ids,
    }


from app.services.token_counter import count_tokens, count_messages_tokens
from app.services.context_builder import build_task_context_snapshot
@router.get("/context-size")
async def get_context_size(
    task_id: str,
    mode: str = "analyst",
    db: AsyncSession = Depends(get_db),
):
    """
    估算当前 Task 的上下文 token 数量
    
    Args:
        task_id: 任务 ID
        mode: 执行模式 (auto/plan/analyst)，影响 system prompt 构建
    """
    from app.models import Task
    from app.services.agent import _load_history_messages
    from fastapi import HTTPException
    
    # 获取 Task
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 构建上下文快照（不依赖 LLM 配置）
    try:
        context_snapshot = await build_task_context_snapshot(
            task_id=task_id,
            db=db,
            mode=mode,
            include_viz_examples=False,  # 保守估计
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Context snapshot failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to build context: {str(e)}")
    
    system_tokens = count_tokens(context_snapshot["system_prompt"])
    
    # 加载历史消息（不排除最后一条，因为这是估算全量）
    history_messages = await _load_history_messages(task_id, db, exclude_latest_user=False)
    history_tokens = count_messages_tokens(cast(list[dict[str, Any]], history_messages))
    
    total_tokens = system_tokens + history_tokens
    
    # 检查是否超出限制
    MAX_CONTEXT_TOKENS = 200_000
    needs_compact = total_tokens > MAX_CONTEXT_TOKENS
    
    return {
        "total_tokens": total_tokens,
        "system_tokens": system_tokens,
        "history_tokens": history_tokens,
        "compact_active": task.compact_context is not None,
        "needs_compact": needs_compact,
        "max_tokens": MAX_CONTEXT_TOKENS,
    }


# 全局字典存储压缩任务状态（内存中，重启后丢失）
_compact_tasks: Dict[str, Dict[str, Any]] = {}
_compact_task_refs: Dict[str, asyncio.Task] = {}  # ← 新增：防止 GC

# 在现有的 compact_context endpoint 之后添加：
@router.post("/tasks/{task_id}/compact/start")
async def start_compact_context(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    启动后台压缩任务（非阻塞）
    
    Returns:
        {"status": "started", "task_id": str}
    """
    from fastapi import HTTPException
    
    # 检查是否已有进行中的任务
    if task_id in _compact_tasks:
        status = _compact_tasks[task_id].get("status")
        if status == "running":
            return {
                "status": "already_running",
                "message": "Compression task is already running for this task"
            }
    
    # 获取 Task
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 初始化状态
    _compact_tasks[task_id] = {
        "status": "running",
        "progress": 0,
        "phase": "initializing",
        "message": "Starting compression...",
        "started_at": datetime.now().isoformat(),
    }
    
    # 启动后台任务 — 必须保存引用，防止 GC
    bg_task = asyncio.create_task(_background_compact_task(task_id))
    _compact_task_refs[task_id] = bg_task
    
    # 任务完成后自动清理引用
    def _cleanup(t: asyncio.Task, tid: str = task_id):
        _compact_task_refs.pop(tid, None)
    bg_task.add_done_callback(_cleanup)
    
    return {"status": "started", "task_id": task_id}

@router.get("/tasks/{task_id}/compact/status")
async def get_compact_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    查询压缩任务状态
    
    Returns:
        {
            "status": "idle" | "running" | "completed" | "failed",
            "progress": 0-100,
            "phase": str,
            "message": str,
            "result": {...} (仅completed时)
        }
    """
    if task_id not in _compact_tasks:
        return {
            "status": "idle",
            "progress": 0,
            "phase": "idle",
            "message": "No compression task running",
        }
    
    return _compact_tasks[task_id]

async def _background_compact_task(task_id: str):
    """后台压缩任务：规则预处理 + 单次 LLM 精炼"""
    from app.services.agent import _get_client_from_db, _load_history_messages
    from app.database import async_session
    
    try:
        _compact_tasks[task_id].update({
            "progress": 10,
            "phase": "loading",
            "message": "Loading conversation history...",
        })
        
        async with async_session() as db:
            # 获取 Task
            result = await db.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            if not task:
                raise ValueError("Task not found")
            
            # 获取 LLM 客户端
            client_result = await _get_client_from_db(db, "misc")
            if not client_result:
                client_result = await _get_client_from_db(db, "default")
            if not client_result:
                raise ValueError("No LLM configuration available")
            
            client, model = client_result
            
            # 加载历史消息
            history_messages = await _load_history_messages(task_id, db, exclude_latest_user=False)
            
            if not history_messages:
                raise ValueError("No conversation history to compress")
            
            original_tokens = count_messages_tokens(
                cast(list[dict[str, Any]], history_messages)
            )
            
            if original_tokens < 10000:
                raise ValueError("Context too small to benefit from compression (< 10K tokens)")
            
            # ── Phase 1: 规则化预处理（不需要 LLM） ──
            _compact_tasks[task_id].update({
                "progress": 20,
                "phase": "preprocessing",
                "message": f"Rule-based preprocessing ({original_tokens:,} tokens)...",
            })
            
            preprocessed_text = _preprocess_for_compression(history_messages)
            preprocessed_tokens = count_tokens(preprocessed_text)
            
            _compact_tasks[task_id].update({
                "progress": 40,
                "phase": "preprocessing_done",
                "message": f"Preprocessed: {original_tokens:,} → {preprocessed_tokens:,} tokens. Starting LLM refinement...",
            })
            
            # ── Phase 2: LLM 精炼（限制输入大小） ──
            # 如果预处理后仍然太大，截断到 ~60K tokens 以适配大多数模型
            MAX_INPUT_TOKENS = 60000
            if preprocessed_tokens > MAX_INPUT_TOKENS:
                # 粗略估算：1 token ≈ 4 chars
                char_limit = MAX_INPUT_TOKENS * 4
                preprocessed_text = preprocessed_text[:char_limit] + (
                    "\n\n... [earlier history truncated for compression]"
                )
                preprocessed_tokens = count_tokens(preprocessed_text)
            
            _compact_tasks[task_id].update({
                "progress": 50,
                "phase": "llm_refine",
                "message": f"LLM refinement ({preprocessed_tokens:,} tokens input)...",
            })
            
            compress_prompt = f"""You are a context compression assistant. Compress the following conversation history into a concise summary that preserves all actionable information.

**Rules:**
1. Preserve ALL code blocks that define reusable functions or important transformations
2. Preserve user decisions (especially HITL choices, data strategy decisions)
3. Compress verbose explanations into bullet points
4. Replace visualization configs with brief descriptions like "[Created bar chart: Revenue by Region]"
5. Keep discovered data insights, statistics, and anomalies
6. Summarize repetitive tool outputs (keep final results only)
7. Maintain chronological flow with clear section markers
8. For failed code attempts, keep only the final working version and a brief note about what was tried

**Target:** Compress to ~30-40% of original length. Prioritize preserving information needed for future analysis steps.

---
**Conversation History:**

{preprocessed_text}

---
**Compressed Summary:**"""

            try:
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": compress_prompt}],
                        temperature=0.0,
                    ),
                    timeout=300.0,  # 5 分钟硬超时
                )
            except asyncio.TimeoutError:
                raise ValueError("LLM compression call timed out (5 min). Try deleting some conversation steps first.")
            
            compressed_summary = (response.choices[0].message.content or "").strip()
            
            if not compressed_summary:
                raise ValueError("Compression failed: LLM returned empty result")
            
            compressed_tokens = count_tokens(compressed_summary)
            compression_ratio = compressed_tokens / original_tokens if original_tokens > 0 else 0
            
            # ── Phase 3: 保存结果 ──
            _compact_tasks[task_id].update({
                "progress": 90,
                "phase": "saving",
                "message": f"Saving: {original_tokens:,} → {compressed_tokens:,} tokens ({compression_ratio:.0%})...",
            })
            
            # 找到最后一个 step 作为 anchor
            result = await db.execute(
                select(Step)
                .where(Step.task_id == task_id)
                .order_by(Step.created_at.desc())
                .limit(1)
            )
            last_step = result.scalar_one_or_none()
            
            if not last_step:
                raise ValueError("No steps found to anchor compression")
            
            task.compact_context = compressed_summary
            task.compact_anchor_step_id = last_step.id
            task.compact_anchor_created_at = last_step.created_at
            await db.commit()
            
            warning = None
            if compression_ratio > 0.6:
                warning = (
                    f"Compression ratio ({compression_ratio:.0%}) is higher than target (30-50%). "
                    "Consider deleting unnecessary conversation steps."
                )
            
            _compact_tasks[task_id].update({
                "status": "completed",
                "progress": 100,
                "phase": "completed",
                "message": "Compression completed successfully",
                "result": {
                    "success": True,
                    "original_tokens": original_tokens,
                    "compressed_tokens": compressed_tokens,
                    "compression_ratio": round(compression_ratio, 2),
                    "compact_anchor_step_id": task.compact_anchor_step_id,
                    "compact_anchor_created_at": (
                        compact_anchor_created_at.isoformat()
                        if (
                            (compact_anchor_created_at := task.compact_anchor_created_at)
                            is not None
                        )
                        else None
                    ),
                    "warning": warning,
                },
                "completed_at": datetime.now().isoformat(),
            })
    
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Background compact failed: {e}", exc_info=True)
        
        _compact_tasks[task_id].update({
            "status": "failed",
            "progress": 0,
            "phase": "failed",
            "message": f"Compression failed: {str(e)}",
            "error": str(e),
            "failed_at": datetime.now().isoformat(),
        })

def _preprocess_for_compression(messages: Sequence[Mapping[str, Any]]) -> str:
    """
    规则化预处理：在 LLM 介入之前先做大幅度的噪声裁减。
    
    策略：
    1. 工具输出截断到 300 chars
    2. 如果连续多次 code → error → code → error，只保留最后成功的
    3. 去掉 visualization JSON configs
    4. 保留所有 user messages 和 code blocks
    """
    lines: list[str] = []
    
    # 先做一遍扫描，标记 "失败重试" 链
    processed = _collapse_retry_chains(messages)
    
    for entry in processed:
        role = entry.get("role", "unknown")
        content = entry.get("content", "")
        
        if role == "user":
            lines.append(f"\n**User:** {content}")
        
        elif role == "assistant":
            tool_calls = entry.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    if isinstance(tc, dict) and "function" in tc:
                        func = tc["function"]
                        func_name = func.get("name", "")
                        if func_name == "execute_python_code":
                            try:
                                args = _json.loads(func.get("arguments", "{}"))
                                code = args.get("code", "")
                                purpose = args.get("purpose", "")
                                lines.append(f"\n**Code Execution:** {purpose}")
                                # 截断过长的代码
                                if len(code) > 3000:
                                    code = code[:3000] + "\n# ... [code truncated]"
                                lines.append(f"```python\n{code}\n```")
                            except _json.JSONDecodeError:
                                pass
                        elif func_name == "create_visualization":
                            try:
                                args = _json.loads(func.get("arguments", "{}"))
                                title = args.get("title", "Untitled")
                                chart_type = args.get("chart_type", "chart")
                                lines.append(f"\n**[Visualization: {chart_type} - {title}]**")
                            except _json.JSONDecodeError:
                                lines.append("\n**[Visualization created]**")
                        elif func_name == "request_human_input":
                            try:
                                args = _json.loads(func.get("arguments", "{}"))
                                lines.append(
                                    f"\n**[HITL Request]** {args.get('title', '')}: "
                                    f"{args.get('description', '')}"
                                )
                            except _json.JSONDecodeError:
                                pass
                        # 其他工具调用简要记录
                        else:
                            lines.append(f"\n**[Tool: {func_name}]**")
            elif content:
                # 截断过长的 assistant 消息
                if len(content) > 2000:
                    content = content[:2000] + "\n... [message truncated]"
                lines.append(f"\n**Assistant:** {content}")
        
        elif role == "tool":
            tool_content = content
            # 工具输出大幅截断
            if len(tool_content) > 500:
                tool_content = tool_content[:500] + "\n... [output truncated]"
            lines.append(f"\n**Result:** {tool_content}")
    
    return "\n".join(lines)

def _collapse_retry_chains(
    messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    折叠 "代码执行失败 → 重试" 链。
    
    如果检测到连续 3+ 次 execute_python_code 调用针对相似目的，
    只保留最后一次成功的（或最后一次失败的）和一条摘要说明。
    """
    result: list[dict[str, Any]] = []
    i = 0
    msg_list = list(messages)
    
    while i < len(msg_list):
        msg = dict(msg_list[i])
        
        # 检测 assistant 带 execute_python_code 工具调用
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            chain_start = i
            chain: list[tuple[int, dict]] = []  # (index, msg)
            
            j = i
            while j < len(msg_list):
                m = msg_list[j]
                if m.get("role") == "assistant" and m.get("tool_calls"):
                    tcs = m.get("tool_calls", [])
                    is_code = any(
                        (isinstance(tc, dict) and 
                         tc.get("function", {}).get("name") == "execute_python_code")
                        for tc in tcs
                    )
                    if is_code:
                        chain.append((j, dict(m)))
                        # 跳过对应的 tool response
                        if j + 1 < len(msg_list) and msg_list[j + 1].get("role") == "tool":
                            j += 2
                        else:
                            j += 1
                        continue
                # 如果遇到 user 消息或非代码 assistant，链结束
                break
            
            if len(chain) >= 3:
                # 折叠：只保留摘要 + 最后一次
                result.append({
                    "role": "assistant",
                    "content": f"[Attempted {len(chain)} code executions; showing final attempt only]",
                })
                # 添加最后一次的 assistant + tool response
                last_idx = chain[-1][0]
                result.append(dict(msg_list[last_idx]))
                if last_idx + 1 < len(msg_list) and msg_list[last_idx + 1].get("role") == "tool":
                    result.append(dict(msg_list[last_idx + 1]))
                i = j
            else:
                # 不够长的链，原样保留
                result.append(msg)
                i += 1
        else:
            result.append(msg)
            i += 1
    
    return result