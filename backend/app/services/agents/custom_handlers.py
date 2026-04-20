# backend/app/services/agents/custom_handlers.py

"""Custom handlers for special skills (derive, sop, script)"""

from typing import AsyncGenerator, TYPE_CHECKING
import json
import re
import os
import uuid

from app.config import UPLOADS_DIR
from app.database import async_session

if TYPE_CHECKING:
    from app.services.agents.base import BaseAgent

import logging
logger = logging.getLogger(__name__)


async def _persist_hitl_step(
    agent: "BaseAgent",
    *,
    title: str,
    description: str,
    payload: dict,
) -> str:
    """将 custom handler 生成的 HITL 请求保存为 Step，并返回 step_saved SSE"""
    from app.models import Step

    step = Step(
        task_id=agent.task_id,
        role="assistant",
        step_type="hitl_request",
        content=description or title,
        code=None,
        code_output=json.dumps(payload, ensure_ascii=False),
    )
    agent.db.add(step)
    await agent.db.commit()
    await agent.db.refresh(step)

    return agent._sse({
        "type": "step_saved",
        "step": {
            "id": step.id,
            "task_id": step.task_id,
            "role": step.role,
            "step_type": step.step_type,
            "content": step.content,
            "code": step.code,
            "code_output": step.code_output,
            "created_at": step.created_at.isoformat() if step.created_at else None,
        },
    })

async def _persist_hitl_step_event(
    agent: "BaseAgent",
    *,
    title: str,
    description: str,
    payload: dict,
) -> dict:
    """将 custom handler 生成的 HITL 请求保存为 Step，返回 step_saved dict event"""
    from app.models import Step

    step = Step(
        task_id=agent.task_id,
        role="assistant",
        step_type="hitl_request",
        content=description or title,
        code=None,
        code_output=json.dumps(payload, ensure_ascii=False),
    )
    agent.db.add(step)
    await agent.db.commit()
    await agent.db.refresh(step)

    return {
        "type": "step_saved",
        "step": {
            "id": step.id,
            "task_id": step.task_id,
            "role": step.role,
            "step_type": step.step_type,
            "content": step.content,
            "code": step.code,
            "code_output": step.code_output,
            "created_at": step.created_at.isoformat() if step.created_at else None,
        },
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Derive Pipeline Handler
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_derive_pipeline(
    agent: "BaseAgent",
    context: dict,
    handler_config: dict,
) -> AsyncGenerator[str, None]:
    """Custom handler for /derive command"""
    user_instructions = agent._safe_str(context, "user_message")
    
    # 检查是否是确认消息
    confirm_match = re.match(r"^\[(Derive|Pipeline)\s+Confirm\]\s*(\{.*\})", user_instructions.strip(), re.DOTALL)
    if confirm_match:
        try:
            config = json.loads(confirm_match.group(2))
        except json.JSONDecodeError:
            yield agent._sse({"type": "error", "content": "Invalid derive confirmation payload."})
            yield agent._sse({"type": "done"})
            return
        
        if config.get("cancelled"):
            tbl = config.get("table_name", "")
            if tbl:
                try:
                    from app.services import warehouse as wh
                    await wh.async_drop_table(tbl)
                except Exception:
                    pass
            yield agent._sse({"type": "text", "content": "Derive cancelled. No data was saved."})
            yield agent._sse({"type": "done"})
            return
        
        async for chunk in _register_derive_metadata(agent, config):
            yield chunk
        return
    
    # ── Main derive flow ──
    yield agent._sse({"type": "text", "content": "🔍 Analyzing task history to extract a data pipeline...\n"})

    code_history = await _collect_code_history(agent)
    if not code_history:
        yield agent._sse({
            "type": "text",
            "content": (
                "⚠️ No successful code executions found in this task. "
                "Please run some analysis first, then use `/derive` to save the result."
            ),
        })
        yield agent._sse({"type": "done"})
        return

    knowledge_ctx = await _gather_knowledge_summary(agent)

    max_react_rounds = handler_config.get("max_react_rounds", 3)
    last_error: str | None = None
    derive_result: dict | None = None
    final_code: str | None = None
    pipeline_proposal: dict | None = None

    for attempt in range(max_react_rounds):
        round_label = f"(attempt {attempt + 1}/{max_react_rounds})"

        if attempt == 0:
            yield agent._sse({"type": "text", "content": f"📝 Generating pipeline code {round_label}...\n"})
        else:
            yield agent._sse({
                "type": "text",
                "content": (
                    f"🔄 Previous attempt failed. Retrying {round_label}...\n"
                    f"Error was: `{last_error[:200] if last_error else 'unknown'}`\n"
                ),
            })

        pipeline_proposal = None
        async for item in _extract_pipeline_with_llm_heartbeat(
            agent, code_history, user_instructions, knowledge_ctx, context, last_error
        ):
            if isinstance(item, str):
                yield item  # 心跳转发
            else:
                pipeline_proposal = item
        
        if pipeline_proposal is None:
            yield agent._sse({
                "type": "text",
                "content": "⚠️ Failed to extract a pipeline from the task history."
            })
            yield agent._sse({"type": "done"})
            return

        transform_code = pipeline_proposal.get("transform_code", "")
        final_code = transform_code

        yield agent._sse({
            "type": "tool_start",
            "code": transform_code,
            "purpose": f"Pipeline execution {round_label}",
        })

        exec_result = None
        async for item in _execute_derive_code_with_heartbeat(agent, transform_code, context):
            if isinstance(item, str):
                yield item  # 心跳转发
            else:
                exec_result = item

        if exec_result is None:
            last_error = "Sandbox execution returned no result"
            yield agent._sse({"type": "tool_result", "success": False, "output": None, "error": last_error, "time": 0})
            continue

        yield agent._sse({
            "type": "tool_result",
            "success": exec_result.get("success", False),
            "output": exec_result.get("output"),
            "error": exec_result.get("error"),
            "time": exec_result.get("execution_time", 0),
        })

        if not exec_result.get("success"):
            last_error = exec_result.get("error", "Unknown execution error")
            continue

        output_text = exec_result.get("output", "") or ""
        derive_result = _parse_derive_marker(output_text)

        if derive_result is None:
            last_error = "Code executed successfully but did not print the __DERIVE_OK__ marker."
            continue

        break

    if derive_result is None:
        yield agent._sse({
            "type": "text",
            "content": (
                f"❌ Pipeline extraction failed after {max_react_rounds} attempts.\n\n"
                f"Last error: `{last_error[:300] if last_error else 'unknown'}`\n\n"
                "Please fix the analysis in chat and try `/derive` again."
            ),
        })
        yield agent._sse({"type": "done"})
        return

    if pipeline_proposal is None:
        yield agent._sse({
            "type": "text",
            "content": "❌ Pipeline extraction finished without a valid proposal. Please try `/derive` again.",
        })
        yield agent._sse({"type": "done"})
        return

    proposal = pipeline_proposal

    if handler_config.get("require_hitl_confirmation", True):
        schema = derive_result.get("schema", [])
        row_count = derive_result.get("row_count", 0)
        sample_rows = derive_result.get("sample_rows", [])
        actual_table_name = derive_result.get("table_name", proposal.get("table_name", ""))

        hitl_payload = {
            "hitl_type": "pipeline_confirmation",
            "title": "💾 Save as Derived Data Source",
            "description": proposal.get("transform_description", ""),
            "pipeline": {
                "table_name": actual_table_name,
                "display_name": proposal.get("display_name", actual_table_name),
                "description": proposal.get("description", ""),
                "source_type": proposal.get("source_type", "unknown"),
                "source_config": proposal.get("source_config", {}),
                "transform_code": final_code,
                "transform_description": proposal.get("transform_description", ""),
                "write_strategy": "replace",
                "schema": schema,
                "row_count": row_count,
                "sample_rows": sample_rows[:5],
            },
            "options": [
                {"label": "Confirm & Save", "value": "confirm", "badge": "recommended"},
                {"label": "Cancel", "value": "cancel"},
            ],
        }

        yield agent._sse({
            "type": "hitl_request",
            "title": hitl_payload["title"],
            "description": hitl_payload["description"],
            "options": hitl_payload["options"],
            **{k: v for k, v in hitl_payload.items()},
        })
    else:
        config = {
            "table_name": derive_result.get("table_name"),
            "display_name": proposal.get("display_name"),
            "description": proposal.get("description"),
            "transform_code": final_code,
            "source_type": proposal.get("source_type"),
            "source_config": proposal.get("source_config"),
            "write_strategy": "replace",
            "schema": derive_result.get("schema"),
            "row_count": derive_result.get("row_count"),
        }
        async for chunk in _register_derive_metadata(agent, config):
            yield chunk
        return
    
    yield agent._sse({"type": "done"})

async def handle_derive_pipeline_events(
    agent: "BaseAgent",
    context: dict,
    handler_config: dict,
) -> AsyncGenerator[dict, None]:
    """Custom handler for /derive command（事件原生版）"""
    user_instructions = agent._safe_str(context, "user_message")

    # 检查是否是确认消息
    confirm_match = re.match(
        r"^\[(Derive|Pipeline)\s+Confirm\]\s*(\{.*\})",
        user_instructions.strip(),
        re.DOTALL,
    )
    if confirm_match:
        try:
            config = json.loads(confirm_match.group(2))
        except json.JSONDecodeError:
            yield {"type": "error", "content": "Invalid derive confirmation payload."}
            yield {"type": "done"}
            return

        if config.get("cancelled"):
            tbl = config.get("table_name", "")
            if tbl:
                try:
                    from app.services import warehouse as wh
                    await wh.async_drop_table(tbl)
                except Exception:
                    pass
            yield {"type": "text", "content": "Derive cancelled. No data was saved."}
            yield {"type": "done"}
            return

        async for event in _register_derive_metadata_events(agent, config):
            yield event
        return

    # ── Main derive flow ──
    yield {"type": "text", "content": "🔍 Analyzing task history to extract a data pipeline...\n"}

    code_history = await _collect_code_history(agent)
    if not code_history:
        yield {
            "type": "text",
            "content": (
                "⚠️ No successful code executions found in this task. "
                "Please run some analysis first, then use `/derive` to save the result."
            ),
        }
        yield {"type": "done"}
        return

    knowledge_ctx = await _gather_knowledge_summary(agent)

    max_react_rounds = handler_config.get("max_react_rounds", 3)
    last_error: str | None = None
    derive_result: dict | None = None
    final_code: str | None = None
    pipeline_proposal: dict | None = None

    for attempt in range(max_react_rounds):
        round_label = f"(attempt {attempt + 1}/{max_react_rounds})"

        if attempt == 0:
            yield {"type": "text", "content": f"📝 Generating pipeline code {round_label}...\n"}
        else:
            yield {
                "type": "text",
                "content": (
                    f"🔄 Previous attempt failed. Retrying {round_label}...\n"
                    f"Error was: `{last_error[:200] if last_error else 'unknown'}`\n"
                ),
            }

        pipeline_proposal = None
        async for item in _extract_pipeline_with_llm_heartbeat_events(
            agent, code_history, user_instructions, knowledge_ctx, context, last_error
        ):
            if item is not None and item.get("type") == "heartbeat":
                yield item
            elif item is not None:
                pipeline_proposal = item

        if pipeline_proposal is None:
            yield {
                "type": "text",
                "content": "⚠️ Failed to extract a pipeline from the task history.",
            }
            yield {"type": "done"}
            return

        transform_code = pipeline_proposal.get("transform_code", "")
        final_code = transform_code

        yield {
            "type": "tool_start",
            "code": transform_code,
            "purpose": f"Pipeline execution {round_label}",
        }

        exec_result = None
        async for item in _execute_derive_code_with_heartbeat_events(
            agent, transform_code, context
        ):
            if isinstance(item, dict) and item.get("type") == "heartbeat":
                yield item
            elif isinstance(item, dict) and "success" in item:
                exec_result = item

        if exec_result is None:
            last_error = "Sandbox execution returned no result"
            yield {
                "type": "tool_result",
                "success": False,
                "output": None,
                "error": last_error,
                "time": 0,
            }
            continue

        yield {
            "type": "tool_result",
            "success": exec_result.get("success", False),
            "output": exec_result.get("output"),
            "error": exec_result.get("error"),
            "time": exec_result.get("execution_time", 0),
        }

        if not exec_result.get("success"):
            last_error = exec_result.get("error", "Unknown execution error")
            continue

        output_text = exec_result.get("output", "") or ""
        derive_result = _parse_derive_marker(output_text)

        if derive_result is None:
            last_error = (
                "Code executed successfully but did not print the __DERIVE_OK__ marker."
            )
            continue

        break

    if derive_result is None:
        yield {
            "type": "text",
            "content": (
                f"❌ Pipeline extraction failed after {max_react_rounds} attempts.\n\n"
                f"Last error: `{last_error[:300] if last_error else 'unknown'}`\n\n"
                "Please fix the analysis in chat and try `/derive` again."
            ),
        }
        yield {"type": "done"}
        return

    if pipeline_proposal is None:
        yield {
            "type": "text",
            "content": "❌ Pipeline extraction finished without a valid proposal. Please try `/derive` again.",
        }
        yield {"type": "done"}
        return

    proposal = pipeline_proposal

    if handler_config.get("require_hitl_confirmation", True):
        schema = derive_result.get("schema", [])
        row_count = derive_result.get("row_count", 0)
        sample_rows = derive_result.get("sample_rows", [])
        actual_table_name = derive_result.get(
            "table_name", proposal.get("table_name", "")
        )

        hitl_payload = {
            "hitl_type": "pipeline_confirmation",
            "title": "💾 Save as Derived Data Source",
            "description": proposal.get("transform_description", ""),
            "pipeline": {
                "table_name": actual_table_name,
                "display_name": proposal.get("display_name", actual_table_name),
                "description": proposal.get("description", ""),
                "source_type": proposal.get("source_type", "unknown"),
                "source_config": proposal.get("source_config", {}),
                "transform_code": final_code,
                "transform_description": proposal.get("transform_description", ""),
                "write_strategy": "replace",
                "schema": schema,
                "row_count": row_count,
                "sample_rows": sample_rows[:5],
            },
            "options": [
                {"label": "Confirm & Save", "value": "confirm", "badge": "recommended"},
                {"label": "Cancel", "value": "cancel"},
            ],
        }

        yield {
            "type": "hitl_request",
            "title": hitl_payload["title"],
            "description": hitl_payload["description"],
            "options": hitl_payload["options"],
            **{k: v for k, v in hitl_payload.items()},
        }
    else:
        config = {
            "table_name": derive_result.get("table_name"),
            "display_name": proposal.get("display_name"),
            "description": proposal.get("description"),
            "transform_code": final_code,
            "source_type": proposal.get("source_type"),
            "source_config": proposal.get("source_config"),
            "write_strategy": "replace",
            "schema": derive_result.get("schema"),
            "row_count": derive_result.get("row_count"),
        }
        async for event in _register_derive_metadata_events(agent, config):
            yield event
        return

    yield {"type": "done"}

# ── Derive helper methods ──

async def _collect_code_history(agent: "BaseAgent") -> list[dict]:
    """回溯 Task 历史，收集成功的 tool_use Steps"""
    from app.models import Step
    from sqlalchemy import select

    result = await agent.db.execute(
        select(Step).where(
            Step.task_id == agent.task_id,
            Step.step_type == "tool_use"
        ).order_by(Step.created_at.asc())
    )
    steps = list(result.scalars().all())

    history = []
    for step in steps:
        if not step.code or not step.code_output:
            continue

        try:
            output_data = json.loads(step.code_output)
        except (json.JSONDecodeError, TypeError):
            continue

        if not output_data.get("success"):
            continue

        history.append({
            "code": step.code,
            "output": output_data.get("output", "")[:2000],
            "purpose": step.content or "",
        })

    return history


async def _gather_knowledge_summary(agent: "BaseAgent") -> str:
    """收集当前 Task 的 Knowledge 摘要"""
    from app.models import Knowledge
    from sqlalchemy import select

    knowledge_ctx = ""
    try:
        result = await agent.db.execute(select(Knowledge).where(Knowledge.task_id == agent.task_id))
        items = list(result.scalars().all())
        if items:
            parts = [f"- {k.name} (type: {k.type})" for k in items]
            knowledge_ctx = "Available data:\n" + "\n".join(parts)
    except Exception:
        pass
    return knowledge_ctx


async def _extract_pipeline_with_llm_heartbeat(
    agent: "BaseAgent",
    code_history: list[dict],
    user_instructions: str,
    knowledge_context: str,
    context: dict,
    previous_error: str | None = None,
) -> AsyncGenerator[str | dict | None, None]:
    """包装 _extract_pipeline_with_llm，定期发送心跳"""
    import asyncio
    
    done_event = asyncio.Event()
    result_holder: list[dict | None] = []
    
    async def _do_extract():
        r = await _extract_pipeline_with_llm(
            agent, code_history, user_instructions, knowledge_context,
            context, previous_error,
        )
        result_holder.append(r)
        done_event.set()
    
    task = asyncio.create_task(_do_extract())
    while not done_event.is_set():
        try:
            await asyncio.wait_for(asyncio.shield(done_event.wait()), timeout=15.0)
        except asyncio.TimeoutError:
            yield agent._sse({"type": "heartbeat", "content": "llm_thinking"})
    
    if task.done() and task.exception():
        logger.error(f"Pipeline extraction task failed: {task.exception()}")
        yield None
        return
    
    yield result_holder[0] if result_holder else None

async def _extract_pipeline_with_llm_heartbeat_events(
    agent: "BaseAgent",
    code_history: list[dict],
    user_instructions: str,
    knowledge_context: str,
    context: dict,
    previous_error: str | None = None,
) -> AsyncGenerator[dict | None, None]:
    """包装 _extract_pipeline_with_llm，定期发送心跳 dict event"""
    import asyncio

    done_event = asyncio.Event()
    result_holder: list[dict | None] = []

    async def _do_extract():
        r = await _extract_pipeline_with_llm(
            agent, code_history, user_instructions, knowledge_context,
            context, previous_error,
        )
        result_holder.append(r)
        done_event.set()

    task = asyncio.create_task(_do_extract())
    while not done_event.is_set():
        try:
            await asyncio.wait_for(asyncio.shield(done_event.wait()), timeout=15.0)
        except asyncio.TimeoutError:
            yield {"type": "heartbeat", "content": "llm_thinking"}

    if task.done() and task.exception():
        logger.error(f"Pipeline extraction task failed: {task.exception()}")
        yield None
        return

    yield result_holder[0] if result_holder else None

async def _extract_pipeline_with_llm(
    agent: "BaseAgent",
    code_history: list[dict],
    user_instructions: str,
    knowledge_context: str,
    context: dict,
    previous_error: str | None = None,
) -> dict | None:
    """使用 LLM 从代码历史中提取 pipeline 定义"""
    
    system_prompt = context.get("invoked_skill_prompt", "")
    if not system_prompt:
        logger.error("Derive skill prompt_markdown is empty")
        return None

    user_prompt = _build_pipeline_user_prompt(code_history, user_instructions, knowledge_context)

    if previous_error:
        user_prompt += (
            f"\n\n## ⚠️ Previous Attempt Failed\n"
            f"```\n{previous_error[:1000]}\n```\n\n"
            f"Fix the code and try again."
        )

    try:
        response = await agent.client.chat.completions.create(
            model=agent.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=8192,
        )

        content = (response.choices[0].message.content or "").strip()
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if not json_match:
            logger.error("LLM did not return valid JSON for pipeline extraction")
            return None

        proposal = json.loads(json_match.group())

        required = ["table_name", "display_name", "description", "source_type", "transform_code"]
        for field in required:
            if field not in proposal:
                logger.error(f"Pipeline proposal missing field: {field}")
                return None

        from app.services.warehouse import validate_table_name, _sanitize_table_name
        valid, err = validate_table_name(proposal["table_name"])
        if not valid:
            proposal["table_name"] = _sanitize_table_name(proposal["table_name"])

        return proposal

    except Exception as e:
        logger.error(f"Pipeline extraction LLM call failed: {e}")
        return None


def _build_pipeline_user_prompt(
    code_history: list[dict],
    user_instructions: str,
    knowledge_context: str,
) -> str:
    """构建 pipeline 提取的 user prompt"""
    parts: list[str] = []

    parts.append("## Code History\n")
    for i, item in enumerate(code_history, 1):
        parts.append(f"### Execution {i}")
        parts.append(f"**Purpose**: {item.get('purpose', 'N/A')}")
        parts.append(f"```python\n{item['code']}\n```")
        output = item.get('output', '')[:500]
        if output:
            parts.append(f"**Output**:\n```\n{output}\n```")
        parts.append("")

    if user_instructions:
        parts.append(f"## User Instructions\n\n{user_instructions}\n")

    if knowledge_context:
        parts.append(f"## Available Data\n\n{knowledge_context}\n")

    parts.append(
        "## Task\n\n"
        "Extract a complete pipeline script from the history above. "
        "Return ONLY the JSON object."
    )

    return "\n".join(parts)


async def _execute_derive_code_with_heartbeat(
    agent: "BaseAgent",
    transform_code: str,
    context: dict,
) -> AsyncGenerator[str | dict, None]:
    """带心跳的 derive 代码执行"""
    from app.services.data_processor import sanitize_variable_name
    from app.models import Knowledge, Skill
    from sqlalchemy import select
    from app.config import UPLOADS_DIR

    # 准备 data_var_map
    data_var_map: dict[str, str] = {}
    result = await agent.db.execute(
        select(Knowledge).where(Knowledge.task_id == agent.task_id)
    )
    for k in result.scalars().all():
        if k.type in ("csv", "excel") and k.file_path and os.path.exists(k.file_path):
            var_name = sanitize_variable_name(k.name)
            data_var_map[var_name] = os.path.abspath(k.file_path)

    capture_dir = os.path.join(UPLOADS_DIR, agent.task_id, "captures", "derive_exec")
    os.makedirs(capture_dir, exist_ok=True)

    # 准备 persistent_vars
    persist_dir = os.path.join(UPLOADS_DIR, agent.task_id, "captures", "persist")
    persisted_var_map: dict[str, str] = {}
    if os.path.isdir(persist_dir):
        import glob
        for fpath in glob.glob(os.path.join(persist_dir, "*.parquet")):
            var_name = os.path.splitext(os.path.basename(fpath))[0]
            persisted_var_map[var_name] = fpath
        for fpath in glob.glob(os.path.join(persist_dir, "*.json")):
            var_name = os.path.splitext(os.path.basename(fpath))[0]
            if var_name not in persisted_var_map:
                persisted_var_map[var_name] = fpath

    # 准备 skill_envs
    skill_result = await agent.db.execute(select(Skill).where(Skill.is_active == True))
    skill_envs: dict[str, str] = {}
    for skill in skill_result.scalars().all():
        try:
            envs = json.loads(skill.env_vars_json) if skill.env_vars_json else {}
            skill_envs.update(envs)
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            modules = json.loads(skill.allowed_modules_json) if skill.allowed_modules_json else []
            if modules:
                existing = json.loads(skill_envs.get("__allowed_modules__", "[]"))
                existing.extend(modules)
                skill_envs["__allowed_modules__"] = json.dumps(list(set(existing)))
        except (json.JSONDecodeError, TypeError):
            pass

    # 注入 ARTIFACT_DIR
    artifact_dir = os.path.join(UPLOADS_DIR, agent.task_id, "captures", "artifacts")
    skill_envs["ARTIFACT_DIR"] = artifact_dir

    # 复用 base 的心跳包装器
    async for item in agent._execute_code_with_heartbeat(
        code=transform_code,
        data_var_map=data_var_map,
        capture_dir=capture_dir,
        skill_envs=skill_envs if skill_envs else None,
        persistent_vars=persisted_var_map if persisted_var_map else None,
    ):
        yield item

async def _execute_derive_code_with_heartbeat_events(
    agent: "BaseAgent",
    transform_code: str,
    context: dict,
) -> AsyncGenerator[dict, None]:
    """带心跳的 derive 代码执行（事件原生版）"""
    async for item in _execute_derive_code_with_heartbeat(agent, transform_code, context):
        if isinstance(item, str):
            # SSE heartbeat string → parse to dict
            if item.startswith("data: "):
                try:
                    yield json.loads(item[6:].strip())
                except json.JSONDecodeError:
                    yield {"type": "heartbeat", "content": "executing"}
            else:
                yield {"type": "heartbeat", "content": "executing"}
        else:
            yield item

def _parse_derive_marker(output: str) -> dict | None:
    """解析沙箱输出中的 __DERIVE_OK__ 标记"""
    marker = "__DERIVE_OK__"
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith(marker):
            try:
                return json.loads(line[len(marker):])
            except json.JSONDecodeError:
                pass
    return None


async def _register_derive_metadata(agent: "BaseAgent", config: dict) -> AsyncGenerator[str, None]:
    """用户确认后，注册元数据到 SQLite"""
    from app.models import DuckDBTable, DataPipeline
    from app.services import warehouse as wh
    from datetime import datetime

    table_name = config.get("table_name", "")
    display_name = config.get("display_name", table_name)
    description = config.get("description", "")
    transform_code = config.get("transform_code", "")
    source_type = config.get("source_type", "unknown")
    source_config = config.get("source_config", {})
    write_strategy = config.get("write_strategy", "replace")

    if not table_name:
        yield agent._sse({"type": "error", "content": "Invalid confirmation: missing table_name."})
        yield agent._sse({"type": "done"})
        return

    exists = await wh.async_table_exists(table_name)
    if not exists:
        yield agent._sse({
            "type": "error",
            "content": f"Table `{table_name}` not found in DuckDB. Please try `/derive` again."
        })
        yield agent._sse({"type": "done"})
        return

    yield agent._sse({"type": "text", "content": f"📋 Registering `{table_name}` as a data asset...\n"})

    try:
        tables_info = await wh.async_list_tables()
        table_info = next((t for t in tables_info if t["table_name"] == table_name), None)
        if table_info:
            schema = table_info["schema"]
            row_count = table_info["row_count"]
        else:
            schema = config.get("schema", [])
            row_count = config.get("row_count", 0)
    except Exception:
        schema = config.get("schema", [])
        row_count = config.get("row_count", 0)

    try:
        async with async_session() as meta_db:
            from sqlalchemy import select as sa_select

            table_schema_json = json.dumps(schema, ensure_ascii=False)
            now = datetime.now()

            existing = await meta_db.execute(sa_select(DuckDBTable).where(DuckDBTable.table_name == table_name))
            table_meta = existing.scalar_one_or_none()

            if table_meta:
                table_meta.display_name = display_name
                table_meta.description = description
                table_meta.table_schema_json = table_schema_json
                table_meta.row_count = row_count
                table_meta.source_type = source_type
                table_meta.source_config = json.dumps(source_config, ensure_ascii=False) if source_config else None
                table_meta.data_updated_at = now
                table_meta.status = "ready"
            else:
                table_meta = DuckDBTable(
                    table_name=table_name,
                    display_name=display_name,
                    description=description,
                    table_schema_json=table_schema_json,
                    row_count=row_count,
                    source_type=source_type,
                    source_config=json.dumps(source_config, ensure_ascii=False) if source_config else None,
                    data_updated_at=now,
                    status="ready",
                )
                meta_db.add(table_meta)
            await meta_db.flush()

            pipeline = DataPipeline(
                name=f"Pipeline: {display_name}",
                description=description,
                source_task_id=agent.task_id,
                source_type=source_type,
                source_config=json.dumps(source_config, ensure_ascii=False) if source_config else "{}",
                transform_code=transform_code,
                transform_description=config.get("transform_description", ""),
                target_table_name=table_name,
                write_strategy=write_strategy,
                output_schema=table_schema_json,
                is_auto=False,
                status="active",
                last_run_at=now,
                last_run_status="success",
            )
            meta_db.add(pipeline)
            await meta_db.flush()

            table_meta.pipeline_id = pipeline.id
            await meta_db.commit()

    except Exception as e:
        logger.error(f"Derive metadata registration failed: {e}")

    col_count = len(schema)
    col_preview = ", ".join(f"`{s['name']}` ({s['type']})" for s in schema[:8])
    if col_count > 8:
        col_preview += f", ... ({col_count} total)"

    success_msg = (
        f"✅ **Data saved successfully!**\n\n"
        f"| Property | Value |\n"
        f"|----------|-------|\n"
        f"| Table | `{table_name}` |\n"
        f"| Rows | {row_count:,} |\n"
        f"| Columns | {col_count} |\n\n"
        f"**Columns:** {col_preview}\n\n"
        f"You can find this table in the **Data Sources** tab on the right panel."
    )

    yield agent._sse({"type": "text", "content": success_msg})
    yield agent._sse({"type": "done"})

async def _register_derive_metadata_events(
    agent: "BaseAgent", config: dict
) -> AsyncGenerator[dict, None]:
    """用户确认后，注册元数据到 SQLite（事件原生版）"""
    from app.models import DuckDBTable, DataPipeline
    from app.services import warehouse as wh
    from datetime import datetime

    table_name = config.get("table_name", "")
    display_name = config.get("display_name", table_name)
    description = config.get("description", "")
    transform_code = config.get("transform_code", "")
    source_type = config.get("source_type", "unknown")
    source_config = config.get("source_config", {})
    write_strategy = config.get("write_strategy", "replace")

    if not table_name:
        yield {"type": "error", "content": "Invalid confirmation: missing table_name."}
        yield {"type": "done"}
        return

    exists = await wh.async_table_exists(table_name)
    if not exists:
        yield {
            "type": "error",
            "content": f"Table `{table_name}` not found in DuckDB. Please try `/derive` again.",
        }
        yield {"type": "done"}
        return

    yield {"type": "text", "content": f"📋 Registering `{table_name}` as a data asset...\n"}

    try:
        tables_info = await wh.async_list_tables()
        table_info = next((t for t in tables_info if t["table_name"] == table_name), None)
        if table_info:
            schema = table_info["schema"]
            row_count = table_info["row_count"]
        else:
            schema = config.get("schema", [])
            row_count = config.get("row_count", 0)
    except Exception:
        schema = config.get("schema", [])
        row_count = config.get("row_count", 0)

    try:
        async with async_session() as meta_db:
            from sqlalchemy import select as sa_select

            table_schema_json = json.dumps(schema, ensure_ascii=False)
            now = datetime.now()

            existing = await meta_db.execute(
                sa_select(DuckDBTable).where(DuckDBTable.table_name == table_name)
            )
            table_meta = existing.scalar_one_or_none()

            if table_meta:
                table_meta.display_name = display_name
                table_meta.description = description
                table_meta.table_schema_json = table_schema_json
                table_meta.row_count = row_count
                table_meta.source_type = source_type
                table_meta.source_config = (
                    json.dumps(source_config, ensure_ascii=False) if source_config else None
                )
                table_meta.data_updated_at = now
                table_meta.status = "ready"
            else:
                table_meta = DuckDBTable(
                    table_name=table_name,
                    display_name=display_name,
                    description=description,
                    table_schema_json=table_schema_json,
                    row_count=row_count,
                    source_type=source_type,
                    source_config=(
                        json.dumps(source_config, ensure_ascii=False) if source_config else None
                    ),
                    data_updated_at=now,
                    status="ready",
                )
                meta_db.add(table_meta)
            await meta_db.flush()

            pipeline = DataPipeline(
                name=f"Pipeline: {display_name}",
                description=description,
                source_task_id=agent.task_id,
                source_type=source_type,
                source_config=(
                    json.dumps(source_config, ensure_ascii=False) if source_config else "{}"
                ),
                transform_code=transform_code,
                transform_description=config.get("transform_description", ""),
                target_table_name=table_name,
                write_strategy=write_strategy,
                output_schema=table_schema_json,
                is_auto=False,
                status="active",
                last_run_at=now,
                last_run_status="success",
            )
            meta_db.add(pipeline)
            await meta_db.flush()

            table_meta.pipeline_id = pipeline.id
            await meta_db.commit()

    except Exception as e:
        logger.error(f"Derive metadata registration failed: {e}")

    col_count = len(schema)
    col_preview = ", ".join(f"`{s['name']}` ({s['type']})" for s in schema[:8])
    if col_count > 8:
        col_preview += f", ... ({col_count} total)"

    success_msg = (
        f"✅ **Data saved successfully!**\n\n"
        f"| Property | Value |\n"
        f"|----------|-------|\n"
        f"| Table | `{table_name}` |\n"
        f"| Rows | {row_count:,} |\n"
        f"| Columns | {col_count} |\n\n"
        f"**Columns:** {col_preview}\n\n"
        f"You can find this table in the **Data Sources** tab on the right panel."
    )

    yield {"type": "text", "content": success_msg}
    yield {"type": "done"}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Extract SOP Handler
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_extract_sop(
    agent: "BaseAgent",
    context: dict,
    handler_config: dict,
) -> AsyncGenerator[str, None]:
    """Custom handler for /sop command"""
    user_instructions = agent._safe_str(context, "user_message")
    # ── 确认消息分支 ──
    confirm_match = re.match(
        r"^\[SOP\s+Confirm\]\s*(\{.*\})", user_instructions.strip(), re.DOTALL
    )
    if confirm_match:
        logger.info("SOP confirm message received: %s", user_instructions[:500])
        try:
            config = json.loads(confirm_match.group(1))
            logger.info(
                "Parsed SOP confirm payload: name=%s, cancelled=%s, markdown_len=%s",
                config.get("name"),
                config.get("cancelled"),
                len(config.get("content_markdown", "") or ""),
            )
        except json.JSONDecodeError:
            logger.exception("Invalid SOP confirmation payload")
            yield agent._sse({"type": "error", "content": "Invalid SOP confirmation payload."})
            yield agent._sse({"type": "done"})
            return
        if config.get("cancelled"):
            yield agent._sse({"type": "text", "content": "SOP extraction cancelled."})
            yield agent._sse({"type": "done"})
            return
        async for chunk in _save_sop_asset(agent, config):
            yield chunk
        return
    # ── Main extraction flow ──
    yield agent._sse({"type": "text", "content": "📋 Analyzing task history to extract SOP...\n"})
    code_history = await _collect_code_history(agent)
    if not code_history:
        yield agent._sse({
            "type": "text",
            "content": "⚠️ No successful code execution history found. Please complete some analysis first."
        })
        yield agent._sse({"type": "done"})
        return
    knowledge_ctx = await _gather_knowledge_summary(agent)
    system_prompt = context.get("invoked_skill_prompt", "")
    if not system_prompt:
        system_prompt = "You are an expert at documenting data analysis procedures."
    user_prompt = _build_sop_extraction_prompt(code_history, user_instructions, knowledge_ctx)
    try:
        yield agent._sse({"type": "text", "content": "🧠 Generating SOP draft...\n"})
        proposal = None
        async for item in _extract_sop_with_llm_heartbeat(
            agent=agent,
            code_history=code_history,
            user_instructions=user_instructions,
            knowledge_context=knowledge_ctx,
            system_prompt=system_prompt,
        ):
            if isinstance(item, str):
                yield item
            else:
                proposal = item
        if proposal is None:
            yield agent._sse({
                "type": "error",
                "content": "Failed to generate SOP: model did not return a valid structured result.",
            })
            yield agent._sse({"type": "done"})
            return
        sop_name = proposal.get("name", "Untitled SOP")
        sop_description = proposal.get("description", "").strip() or (
            user_instructions.strip()
            if user_instructions.strip()
            else "Standard Operating Procedure extracted from task history"
        )
        content_markdown = proposal.get("content_markdown", "")
        sop_payload = {
            "name": sop_name,
            "description": sop_description,
            "content_markdown": content_markdown,
        }
        yield agent._sse({"type": "text", "content": "✅ SOP draft is ready. Preparing confirmation card...\n"})

        hitl_payload = {
            "hitl_type": "sop_confirmation",
            "title": "💾 Save as SOP Asset",
            "description": sop_description,
            "sop": sop_payload,
            "options": [
                {"label": "Save SOP", "value": "confirm", "badge": "recommended"},
                {"label": "Cancel", "value": "cancel"},
            ],
        }
        # 只保留持久化 step，前端通过 step_saved 统一渲染卡片
        yield await _persist_hitl_step(
            agent,
            title=hitl_payload["title"],
            description=hitl_payload["description"],
            payload=hitl_payload,
        )
    except Exception as e:
        logger.error(f"SOP extraction failed: {e}")
        yield agent._sse({"type": "error", "content": f"Failed to generate SOP: {str(e)}"})
    yield agent._sse({"type": "done"})

async def handle_extract_sop_events(
    agent: "BaseAgent",
    context: dict,
    handler_config: dict,
) -> AsyncGenerator[dict, None]:
    """Custom handler for /sop command（事件原生版）"""
    user_instructions = agent._safe_str(context, "user_message")

    # ── 确认消息分支 ──
    confirm_match = re.match(
        r"^\[SOP\s+Confirm\]\s*(\{.*\})", user_instructions.strip(), re.DOTALL
    )
    if confirm_match:
        try:
            config = json.loads(confirm_match.group(1))
        except json.JSONDecodeError:
            yield {"type": "error", "content": "Invalid SOP confirmation payload."}
            yield {"type": "done"}
            return
        if config.get("cancelled"):
            yield {"type": "text", "content": "SOP extraction cancelled."}
            yield {"type": "done"}
            return
        async for event in _save_sop_asset_events(agent, config):
            yield event
        return

    # ── Main extraction flow ──
    yield {"type": "text", "content": "📋 Analyzing task history to extract SOP...\n"}

    code_history = await _collect_code_history(agent)
    if not code_history:
        yield {
            "type": "text",
            "content": "⚠️ No successful code execution history found. Please complete some analysis first.",
        }
        yield {"type": "done"}
        return

    knowledge_ctx = await _gather_knowledge_summary(agent)
    system_prompt = context.get("invoked_skill_prompt", "")
    if not system_prompt:
        system_prompt = "You are an expert at documenting data analysis procedures."

    try:
        yield {"type": "text", "content": "🧠 Generating SOP draft...\n"}

        proposal = None
        async for item in _extract_sop_with_llm_heartbeat_events(
            agent=agent,
            code_history=code_history,
            user_instructions=user_instructions,
            knowledge_context=knowledge_ctx,
            system_prompt=system_prompt,
        ):
            if item is not None and isinstance(item, dict) and item.get("type") == "heartbeat":
                yield item
            elif item is not None:
                proposal = item

        if proposal is None:
            yield {
                "type": "error",
                "content": "Failed to generate SOP: model did not return a valid structured result.",
            }
            yield {"type": "done"}
            return

        sop_name = proposal.get("name", "Untitled SOP")
        sop_description = proposal.get("description", "").strip() or (
            user_instructions.strip()
            if user_instructions.strip()
            else "Standard Operating Procedure extracted from task history"
        )
        content_markdown = proposal.get("content_markdown", "")

        sop_payload = {
            "name": sop_name,
            "description": sop_description,
            "content_markdown": content_markdown,
        }

        yield {"type": "text", "content": "✅ SOP draft is ready. Preparing confirmation card...\n"}

        hitl_payload = {
            "hitl_type": "sop_confirmation",
            "title": "💾 Save as SOP Asset",
            "description": sop_description,
            "sop": sop_payload,
            "options": [
                {"label": "Save SOP", "value": "confirm", "badge": "recommended"},
                {"label": "Cancel", "value": "cancel"},
            ],
        }

        # 持久化 HITL step
        step_event = await _persist_hitl_step_event(
            agent,
            title=hitl_payload["title"],
            description=hitl_payload["description"],
            payload=hitl_payload,
        )
        yield step_event

    except Exception as e:
        logger.error(f"SOP extraction failed: {e}")
        yield {"type": "error", "content": f"Failed to generate SOP: {str(e)}"}

    yield {"type": "done"}

async def _extract_sop_with_llm_heartbeat(
    agent: "BaseAgent",
    code_history: list[dict],
    user_instructions: str,
    knowledge_context: str,
    system_prompt: str,
) -> AsyncGenerator[str | dict | None, None]:
    """包装 SOP 提取，定期发送心跳，避免前端超时"""
    import asyncio

    done_event = asyncio.Event()
    result_holder: list[dict | None] = []

    async def _do_extract():
        r = await _extract_sop_with_llm(
            agent=agent,
            code_history=code_history,
            user_instructions=user_instructions,
            knowledge_context=knowledge_context,
            system_prompt=system_prompt,
        )
        result_holder.append(r)
        done_event.set()

    task = asyncio.create_task(_do_extract())

    while not done_event.is_set():
        try:
            await asyncio.wait_for(asyncio.shield(done_event.wait()), timeout=15.0)
        except asyncio.TimeoutError:
            yield agent._sse({"type": "heartbeat", "content": "llm_thinking"})

    if task.done() and task.exception():
        logger.error(f"SOP extraction task failed: {task.exception()}")
        yield None
        return

    yield result_holder[0] if result_holder else None

async def _extract_sop_with_llm_heartbeat_events(
    agent: "BaseAgent",
    code_history: list[dict],
    user_instructions: str,
    knowledge_context: str,
    system_prompt: str,
) -> AsyncGenerator[dict | None, None]:
    """包装 SOP 提取，定期发送心跳 dict event"""
    import asyncio

    done_event = asyncio.Event()
    result_holder: list[dict | None] = []

    async def _do_extract():
        r = await _extract_sop_with_llm(
            agent=agent,
            code_history=code_history,
            user_instructions=user_instructions,
            knowledge_context=knowledge_context,
            system_prompt=system_prompt,
        )
        result_holder.append(r)
        done_event.set()

    task = asyncio.create_task(_do_extract())
    while not done_event.is_set():
        try:
            await asyncio.wait_for(asyncio.shield(done_event.wait()), timeout=15.0)
        except asyncio.TimeoutError:
            yield {"type": "heartbeat", "content": "llm_thinking"}

    if task.done() and task.exception():
        logger.error(f"SOP extraction task failed: {task.exception()}")
        yield None
        return

    yield result_holder[0] if result_holder else None

async def _extract_sop_with_llm(
    agent: "BaseAgent",
    code_history: list[dict],
    user_instructions: str,
    knowledge_context: str,
    system_prompt: str,
) -> dict | None:
    """调用 LLM 提取 SOP JSON"""
    user_prompt = _build_sop_extraction_prompt(
        code_history=code_history,
        user_instructions=user_instructions,
        knowledge_context=knowledge_context,
    )

    try:
        response = await agent.client.chat.completions.create(
            model=agent.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=8192,
        )

        raw_content = (response.choices[0].message.content or "").strip()
        if not raw_content:
            logger.error("SOP extraction returned empty response")
            return None

        json_match = re.search(r"\{.*\}", raw_content, re.DOTALL)
        if not json_match:
            logger.error("LLM did not return valid JSON for SOP extraction")
            return None

        proposal = json.loads(json_match.group())

        content_markdown = str(proposal.get("content_markdown", "")).strip()
        if not content_markdown:
            logger.error("SOP proposal missing content_markdown")
            return None

        proposal["name"] = str(proposal.get("name", "")).strip() or _guess_sop_name_from_markdown(content_markdown) or "Untitled SOP"
        proposal["description"] = str(proposal.get("description", "")).strip()
        proposal["content_markdown"] = content_markdown

        return proposal

    except Exception as e:
        logger.error(f"SOP extraction LLM call failed: {e}")
        return None

def _guess_sop_name_from_markdown(content: str) -> str | None:
    """从 markdown 第一行标题猜 SOP 名称"""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None

async def _save_sop_asset(agent: "BaseAgent", config: dict) -> AsyncGenerator[str, None]:
    """用户确认后，将 SOP 保存为 Asset"""
    from app.models import Asset

    name = config.get("name", "Untitled SOP")
    description = config.get("description", "")
    content_markdown = config.get("content_markdown", "")

    if not content_markdown.strip():
        yield agent._sse({"type": "error", "content": "Cannot save SOP: content is empty."})
        yield agent._sse({"type": "done"})
        return
    yield agent._sse({"type": "text", "content": f"💾 Saving SOP `{name}` as an asset...\n"})
    print(f"_save_sop_asset entered: name={name!r}, task_id={agent.task_id}, markdown_len={len(content_markdown)}")
    
    try:
        async with async_session() as db:
            asset = Asset(
                name=name,
                description=description,
                asset_type="sop",
                source_task_id=agent.task_id,
                content_markdown=content_markdown,
            )
            db.add(asset)
            await db.commit()
            await db.refresh(asset)
            print(f"SOP asset saved successfully: asset_id={asset.id}")

        line_count = len(content_markdown.strip().splitlines())

        success_msg = (
            f"✅ **SOP saved successfully!**\n\n"
            f"| Property | Value |\n"
            f"|----------|-------|\n"
            f"| Name | `{name}` |\n"
            f"| Type | sop |\n"
            f"| Lines | {line_count} |\n"
            f"\nYou can find this SOP in the **Assets** tab on the right panel."
        )
        yield agent._sse({"type": "text", "content": success_msg})

    except Exception as e:
        logger.error(f"SOP asset save failed: {e}")
        yield agent._sse({"type": "error", "content": f"Failed to save SOP: {str(e)}"})

    yield agent._sse({"type": "done"})

async def _save_sop_asset_events(
    agent: "BaseAgent", config: dict
) -> AsyncGenerator[dict, None]:
    """用户确认后，将 SOP 保存为 Asset（事件原生版）"""
    from app.models import Asset

    name = config.get("name", "Untitled SOP")
    description = config.get("description", "")
    content_markdown = config.get("content_markdown", "")

    if not content_markdown.strip():
        yield {"type": "error", "content": "Cannot save SOP: content is empty."}
        yield {"type": "done"}
        return

    yield {"type": "text", "content": f"💾 Saving SOP `{name}` as an asset...\n"}

    try:
        async with async_session() as db:
            asset = Asset(
                name=name,
                description=description,
                asset_type="sop",
                source_task_id=agent.task_id,
                content_markdown=content_markdown,
            )
            db.add(asset)
            await db.commit()
            await db.refresh(asset)

        line_count = len(content_markdown.strip().splitlines())

        success_msg = (
            f"✅ **SOP saved successfully!**\n\n"
            f"| Property | Value |\n"
            f"|----------|-------|\n"
            f"| Name | `{name}` |\n"
            f"| Type | sop |\n"
            f"| Lines | {line_count} |\n"
            f"\nYou can find this SOP in the **Assets** tab on the right panel."
        )
        yield {"type": "text", "content": success_msg}

    except Exception as e:
        logger.error(f"SOP asset save failed: {e}")
        yield {"type": "error", "content": f"Failed to save SOP: {str(e)}"}

    yield {"type": "done"}

def _build_sop_extraction_prompt(
    code_history: list[dict],
    user_instructions: str,
    knowledge_context: str,
) -> str:
    """构建 SOP 提取的 prompt"""
    history_section = "## Analysis History\n\n"
    for i, item in enumerate(code_history, 1):
        history_section += f"### Step {i}\n"
        history_section += f"**Purpose**: {item.get('purpose', 'N/A')}\n\n"
        history_section += f"**Code**:\n```python\n{item['code'][:500]}\n```\n\n"
    
    instructions_section = ""
    if user_instructions:
        instructions_section = f"## User Instructions\n\n{user_instructions}\n\n"
    
    knowledge_section = f"## Available Data\n\n{knowledge_context}\n\n"
    
    prompt = f"""
{history_section}
{instructions_section}
{knowledge_section}
## Your Task
Based on the analysis history above, create a reusable **Standard Operating Procedure (SOP)**.
Return ONLY a JSON object with:
- `name`: a concise SOP title
- `description`: a short summary of what the SOP is for
- `content_markdown`: the full SOP document in Markdown format
The SOP should include:
1. **Objective** — What problem does this procedure solve?
2. **Prerequisites** — Required data sources, tools, or knowledge
3. **Step-by-Step Instructions** — Clear, actionable steps (abstract away specific file names)
4. **Expected Outputs** — What results should be produced
5. **Common Issues & Solutions** — Troubleshooting guide based on the history
Focus on making the SOP reusable for similar tasks in the future. Use clear headings and bullet points.
"""
    
    return prompt


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Extract Script Handler
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_extract_script(
    agent: "BaseAgent",
    context: dict,
    handler_config: dict,
) -> AsyncGenerator[str, None]:
    """Custom handler for /script command"""
    user_instructions = agent._safe_str(context, "user_message")
    
    # 检查是否是确认消息
    confirm_match = re.match(
        r"^\[Script\s+Confirm\]\s*(\{.*\})", user_instructions.strip(), re.DOTALL
    )
    if confirm_match:
        try:
            config = json.loads(confirm_match.group(1))
        except json.JSONDecodeError:
            yield agent._sse({"type": "error", "content": "Invalid script confirmation payload."})
            yield agent._sse({"type": "done"})
            return
        if config.get("cancelled"):
            yield agent._sse({"type": "text", "content": "Script extraction cancelled."})
            yield agent._sse({"type": "done"})
            return
        async for chunk in _save_script_asset(agent, config):
            yield chunk
        return
    
    # ── Main extraction flow ──
    yield agent._sse({"type": "text", "content": "📝 Analyzing task history to extract a reusable script...\n"})
    
    code_history = await _collect_code_history(agent)
    if not code_history:
        yield agent._sse({
            "type": "text",
            "content": (
                "⚠️ No successful code executions found in this task. "
                "Please run some analysis first, then use `/script` to save it."
            ),
        })
        yield agent._sse({"type": "done"})
        return
    
    knowledge_ctx = await _gather_knowledge_summary(agent)
    system_prompt = context.get("invoked_skill_prompt", "")
    if not system_prompt:
        logger.error("Extract Script skill prompt_markdown is empty")
        yield agent._sse({"type": "error", "content": "Script extraction skill is misconfigured."})
        yield agent._sse({"type": "done"})
        return
    
    max_react_rounds = handler_config.get("max_react_rounds", 3)
    last_error: str | None = None
    proposal: dict | None = None
    validated_code: str | None = None
    
    for attempt in range(max_react_rounds):
        round_label = f"(attempt {attempt + 1}/{max_react_rounds})"
        if attempt == 0:
            yield agent._sse({"type": "text", "content": f"🔧 Generating script {round_label}...\n"})
        else:
            yield agent._sse({
                "type": "text",
                "content": (
                    f"🔄 Previous attempt failed. Retrying {round_label}...\n"
                    f"Error: `{last_error[:200] if last_error else 'unknown'}`\n"
                ),
            })
        
        # LLM extraction (with heartbeat)
        proposal = None
        async for item in _extract_script_with_llm_heartbeat(
            agent, code_history, user_instructions, knowledge_ctx,
            system_prompt, last_error,
        ):
            if isinstance(item, str):
                yield item  # heartbeat
            else:
                proposal = item
        
        if proposal is None:
            yield agent._sse({
                "type": "text",
                "content": "⚠️ Failed to extract script from the task history.",
            })
            yield agent._sse({"type": "done"})
            return
        
        code = proposal.get("code", "")
        if not code.strip():
            last_error = "LLM returned empty code"
            continue
        
        # Sandbox validation
        yield agent._sse({
            "type": "tool_start",
            "code": code,
            "purpose": f"Script validation {round_label}",
        })
        
        exec_result = None
        async for item in _execute_script_validation_with_heartbeat(agent, code, context):
            if isinstance(item, str):
                yield item
            else:
                exec_result = item
        
        if exec_result is None:
            last_error = "Sandbox returned no result"
            yield agent._sse({"type": "tool_result", "success": False, "output": None, "error": last_error, "time": 0})
            continue
        
        yield agent._sse({
            "type": "tool_result",
            "success": exec_result.get("success", False),
            "output": exec_result.get("output"),
            "error": exec_result.get("error"),
            "time": exec_result.get("execution_time", 0),
        })
        
        if not exec_result.get("success"):
            last_error = exec_result.get("error", "Unknown execution error")
            continue
        
        # ✅ Validation passed
        validated_code = code
        break
    
    if validated_code is None:
        yield agent._sse({
            "type": "text",
            "content": (
                f"❌ Script extraction failed after {max_react_rounds} attempts.\n\n"
                f"Last error: `{last_error[:300] if last_error else 'unknown'}`\n\n"
                "Please fix the analysis and try `/script` again."
            ),
        })
        yield agent._sse({"type": "done"})
        return
    
    assert proposal is not None
    
    # HITL confirmation card
    script_payload = {
        "name": proposal.get("name", "Untitled Script"),
        "description": proposal.get("description", ""),
        "code": validated_code,
        "script_type": proposal.get("script_type", "general"),
        "env_vars": proposal.get("env_vars", {}),
        "allowed_modules": proposal.get("allowed_modules", []),
    }
    
    yield agent._sse({
        "type": "hitl_request",
        "hitl_type": "script_confirmation",
        "title": "💾 Save as Reusable Script",
        "description": proposal.get("description", ""),
        "script": script_payload,
        "options": [
            {"label": "Save Script", "value": "confirm", "badge": "recommended"},
            {"label": "Cancel", "value": "cancel"},
        ],
    })
    yield agent._sse({"type": "done"})

async def handle_extract_script_events(
    agent: "BaseAgent",
    context: dict,
    handler_config: dict,
) -> AsyncGenerator[dict, None]:
    """Custom handler for /script command（事件原生版）"""
    user_instructions = agent._safe_str(context, "user_message")

    # 检查是否是确认消息
    confirm_match = re.match(
        r"^\[Script\s+Confirm\]\s*(\{.*\})", user_instructions.strip(), re.DOTALL
    )
    if confirm_match:
        try:
            config = json.loads(confirm_match.group(1))
        except json.JSONDecodeError:
            yield {"type": "error", "content": "Invalid script confirmation payload."}
            yield {"type": "done"}
            return
        if config.get("cancelled"):
            yield {"type": "text", "content": "Script extraction cancelled."}
            yield {"type": "done"}
            return
        async for event in _save_script_asset_events(agent, config):
            yield event
        return

    # ── Main extraction flow ──
    yield {
        "type": "text",
        "content": "📝 Analyzing task history to extract a reusable script...\n",
    }

    code_history = await _collect_code_history(agent)
    if not code_history:
        yield {
            "type": "text",
            "content": (
                "⚠️ No successful code executions found in this task. "
                "Please run some analysis first, then use `/script` to save it."
            ),
        }
        yield {"type": "done"}
        return

    knowledge_ctx = await _gather_knowledge_summary(agent)
    system_prompt = context.get("invoked_skill_prompt", "")
    if not system_prompt:
        yield {"type": "error", "content": "Script extraction skill is misconfigured."}
        yield {"type": "done"}
        return

    max_react_rounds = handler_config.get("max_react_rounds", 3)
    last_error: str | None = None
    proposal: dict | None = None
    validated_code: str | None = None

    for attempt in range(max_react_rounds):
        round_label = f"(attempt {attempt + 1}/{max_react_rounds})"
        if attempt == 0:
            yield {"type": "text", "content": f"🔧 Generating script {round_label}...\n"}
        else:
            yield {
                "type": "text",
                "content": (
                    f"🔄 Previous attempt failed. Retrying {round_label}...\n"
                    f"Error: `{last_error[:200] if last_error else 'unknown'}`\n"
                ),
            }

        # LLM extraction (with heartbeat)
        proposal = None
        async for item in _extract_script_with_llm_heartbeat_events(
            agent, code_history, user_instructions, knowledge_ctx,
            system_prompt, last_error,
        ):
            if item is not None and isinstance(item, dict) and item.get("type") == "heartbeat":
                yield item
            elif item is not None:
                proposal = item

        if proposal is None:
            yield {
                "type": "text",
                "content": "⚠️ Failed to extract script from the task history.",
            }
            yield {"type": "done"}
            return

        code = proposal.get("code", "")
        if not code.strip():
            last_error = "LLM returned empty code"
            continue

        # Sandbox validation
        yield {
            "type": "tool_start",
            "code": code,
            "purpose": f"Script validation {round_label}",
        }

        exec_result = None
        async for item in _execute_script_validation_with_heartbeat_events(
            agent, code, context
        ):
            if isinstance(item, dict) and item.get("type") == "heartbeat":
                yield item
            elif isinstance(item, dict) and "success" in item:
                exec_result = item

        if exec_result is None:
            last_error = "Sandbox returned no result"
            yield {
                "type": "tool_result",
                "success": False,
                "output": None,
                "error": last_error,
                "time": 0,
            }
            continue

        yield {
            "type": "tool_result",
            "success": exec_result.get("success", False),
            "output": exec_result.get("output"),
            "error": exec_result.get("error"),
            "time": exec_result.get("execution_time", 0),
        }

        if not exec_result.get("success"):
            last_error = exec_result.get("error", "Unknown execution error")
            continue

        validated_code = code
        break

    if validated_code is None:
        yield {
            "type": "text",
            "content": (
                f"❌ Script extraction failed after {max_react_rounds} attempts.\n\n"
                f"Last error: `{last_error[:300] if last_error else 'unknown'}`\n\n"
                "Please fix the analysis and try `/script` again."
            ),
        }
        yield {"type": "done"}
        return

    assert proposal is not None

    # HITL confirmation card
    script_payload = {
        "name": proposal.get("name", "Untitled Script"),
        "description": proposal.get("description", ""),
        "code": validated_code,
        "script_type": proposal.get("script_type", "general"),
        "env_vars": proposal.get("env_vars", {}),
        "allowed_modules": proposal.get("allowed_modules", []),
    }

    yield {
        "type": "hitl_request",
        "hitl_type": "script_confirmation",
        "title": "💾 Save as Reusable Script",
        "description": proposal.get("description", ""),
        "script": script_payload,
        "options": [
            {"label": "Save Script", "value": "confirm", "badge": "recommended"},
            {"label": "Cancel", "value": "cancel"},
        ],
    }
    yield {"type": "done"}

# ── Script extraction helper methods ──

async def _extract_script_with_llm_heartbeat(
    agent: "BaseAgent",
    code_history: list[dict],
    user_instructions: str,
    knowledge_context: str,
    system_prompt: str,
    previous_error: str | None = None,
) -> AsyncGenerator[str | dict | None, None]:
    """Wrapper with heartbeat for LLM extraction"""
    import asyncio
    
    done_event = asyncio.Event()
    result_holder: list[dict | None] = []
    
    async def _do_extract():
        r = await _extract_script_with_llm(
            agent, code_history, user_instructions, knowledge_context,
            system_prompt, previous_error,
        )
        result_holder.append(r)
        done_event.set()
    
    task = asyncio.create_task(_do_extract())
    while not done_event.is_set():
        try:
            await asyncio.wait_for(asyncio.shield(done_event.wait()), timeout=15.0)
        except asyncio.TimeoutError:
            yield agent._sse({"type": "heartbeat", "content": "llm_thinking"})
    
    if task.done() and task.exception():
        logger.error(f"Script extraction task failed: {task.exception()}")
        yield None
        return
    
    yield result_holder[0] if result_holder else None

async def _extract_script_with_llm_heartbeat_events(
    agent: "BaseAgent",
    code_history: list[dict],
    user_instructions: str,
    knowledge_context: str,
    system_prompt: str,
    previous_error: str | None = None,
) -> AsyncGenerator[dict | None, None]:
    """Wrapper with heartbeat dict events for LLM extraction"""
    import asyncio

    done_event = asyncio.Event()
    result_holder: list[dict | None] = []

    async def _do_extract():
        r = await _extract_script_with_llm(
            agent, code_history, user_instructions, knowledge_context,
            system_prompt, previous_error,
        )
        result_holder.append(r)
        done_event.set()

    task = asyncio.create_task(_do_extract())
    while not done_event.is_set():
        try:
            await asyncio.wait_for(asyncio.shield(done_event.wait()), timeout=15.0)
        except asyncio.TimeoutError:
            yield {"type": "heartbeat", "content": "llm_thinking"}

    if task.done() and task.exception():
        logger.error(f"Script extraction task failed: {task.exception()}")
        yield None
        return

    yield result_holder[0] if result_holder else None

async def _extract_script_with_llm(
    agent: "BaseAgent",
    code_history: list[dict],
    user_instructions: str,
    knowledge_context: str,
    system_prompt: str,
    previous_error: str | None = None,
) -> dict | None:
    """Use LLM to extract a reusable script from code history"""
    user_prompt_parts: list[str] = []
    
    user_prompt_parts.append("## Code History\n")
    for i, item in enumerate(code_history, 1):
        user_prompt_parts.append(f"### Execution {i}")
        user_prompt_parts.append(f"**Purpose**: {item.get('purpose', 'N/A')}")
        user_prompt_parts.append(f"```python\n{item['code']}\n```")
        output = item.get("output", "")[:500]
        if output:
            user_prompt_parts.append(f"**Output**:\n```\n{output}\n```")
        user_prompt_parts.append("")
    
    if user_instructions:
        user_prompt_parts.append(f"## User Instructions\n\n{user_instructions}\n")
    
    if knowledge_context:
        user_prompt_parts.append(f"## Available Data\n\n{knowledge_context}\n")
    
    if previous_error:
        user_prompt_parts.append(
            f"## ⚠️ Previous Attempt Failed\n"
            f"```\n{previous_error[:1000]}\n```\n\n"
            f"Fix the code and try again."
        )
    
    user_prompt_parts.append(
        "## Task\n\n"
        "Extract a complete, self-contained Python script from the history above. "
        "Return ONLY the JSON object."
    )
    
    user_prompt = "\n".join(user_prompt_parts)
    
    try:
        response = await agent.client.chat.completions.create(
            model=agent.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=8192,
        )
        
        content = (response.choices[0].message.content or "").strip()
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if not json_match:
            logger.error("LLM did not return valid JSON for script extraction")
            return None
        
        proposal = json.loads(json_match.group())
        
        required = ["name", "code"]
        for field in required:
            if field not in proposal:
                logger.error(f"Script proposal missing field: {field}")
                return None
        
        # Defaults
        proposal.setdefault("description", "")
        proposal.setdefault("script_type", "general")
        proposal.setdefault("env_vars", {})
        proposal.setdefault("allowed_modules", [])
        
        return proposal
    
    except Exception as e:
        logger.error(f"Script extraction LLM call failed: {e}")
        return None


async def _execute_script_validation_with_heartbeat(
    agent: "BaseAgent",
    code: str,
    context: dict,
) -> AsyncGenerator[str | dict, None]:
    """在沙箱中验证脚本可执行，带心跳"""
    from app.services.data_processor import sanitize_variable_name
    from app.models import Knowledge, Skill
    from sqlalchemy import select
    from app.config import UPLOADS_DIR

    # 准备 data_var_map
    data_var_map: dict[str, str] = {}
    result = await agent.db.execute(
        select(Knowledge).where(Knowledge.task_id == agent.task_id)
    )
    for k in result.scalars().all():
        if k.type in ("csv", "excel") and k.file_path and os.path.exists(k.file_path):
            var_name = sanitize_variable_name(k.name)
            data_var_map[var_name] = os.path.abspath(k.file_path)

    capture_dir = os.path.join(UPLOADS_DIR, agent.task_id, "captures", "script_validate")
    os.makedirs(capture_dir, exist_ok=True)

    # 准备 persistent_vars
    persist_dir = os.path.join(UPLOADS_DIR, agent.task_id, "captures", "persist")
    persisted_var_map: dict[str, str] = {}
    if os.path.isdir(persist_dir):
        import glob
        for fpath in glob.glob(os.path.join(persist_dir, "*.parquet")):
            var_name = os.path.splitext(os.path.basename(fpath))[0]
            persisted_var_map[var_name] = fpath
        for fpath in glob.glob(os.path.join(persist_dir, "*.json")):
            var_name = os.path.splitext(os.path.basename(fpath))[0]
            if var_name not in persisted_var_map:
                persisted_var_map[var_name] = fpath

    # 准备 skill_envs
    skill_result = await agent.db.execute(select(Skill).where(Skill.is_active == True))
    skill_envs: dict[str, str] = {}
    for skill in skill_result.scalars().all():
        try:
            envs = json.loads(skill.env_vars_json) if skill.env_vars_json else {}
            skill_envs.update(envs)
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            modules = json.loads(skill.allowed_modules_json) if skill.allowed_modules_json else []
            if modules:
                existing = json.loads(skill_envs.get("__allowed_modules__", "[]"))
                existing.extend(modules)
                skill_envs["__allowed_modules__"] = json.dumps(list(set(existing)))
        except (json.JSONDecodeError, TypeError):
            pass

    # 注入 ARTIFACT_DIR（指向任务主 artifact 目录，而非 script_validate 子目录）
    artifact_dir = os.path.join(UPLOADS_DIR, agent.task_id, "captures", "artifacts")
    skill_envs["ARTIFACT_DIR"] = artifact_dir

    # 合并 context 中 extra_skill_envs
    extra_envs = context.get("extra_skill_envs")
    if extra_envs:
        if "__allowed_modules__" in extra_envs and "__allowed_modules__" in skill_envs:
            existing_m = set(json.loads(skill_envs["__allowed_modules__"]))
            new_m = set(json.loads(extra_envs["__allowed_modules__"]))
            skill_envs["__allowed_modules__"] = json.dumps(list(existing_m | new_m))
            extra_clean = {k: v for k, v in extra_envs.items() if k != "__allowed_modules__"}
            skill_envs.update(extra_clean)
        else:
            skill_envs.update(extra_envs)

    # 复用 base 心跳包装器执行
    async for item in agent._execute_code_with_heartbeat(
        code=code,
        data_var_map=data_var_map,
        capture_dir=capture_dir,
        skill_envs=skill_envs if skill_envs else None,
        persistent_vars=persisted_var_map if persisted_var_map else None,
    ):
        yield item

async def _execute_script_validation_with_heartbeat_events(
    agent: "BaseAgent",
    code: str,
    context: dict,
) -> AsyncGenerator[dict, None]:
    """在沙箱中验证脚本可执行，带心跳（事件原生版）"""
    async for item in _execute_script_validation_with_heartbeat(agent, code, context):
        if isinstance(item, str):
            if item.startswith("data: "):
                try:
                    yield json.loads(item[6:].strip())
                except json.JSONDecodeError:
                    yield {"type": "heartbeat", "content": "executing"}
            else:
                yield {"type": "heartbeat", "content": "executing"}
        else:
            yield item

async def _save_script_asset(agent: "BaseAgent", config: dict) -> AsyncGenerator[str, None]:
    """用户确认后，将 script 保存为 Asset"""
    from app.models import Asset
    
    name = config.get("name", "Untitled Script")
    description = config.get("description", "")
    code = config.get("code", "")
    script_type = config.get("script_type", "general")
    env_vars = config.get("env_vars", {})
    allowed_modules = config.get("allowed_modules", [])

    if not code.strip():
        yield agent._sse({"type": "error", "content": "Cannot save script: code is empty."})
        yield agent._sse({"type": "done"})
        return

    yield agent._sse({"type": "text", "content": f"💾 Saving script `{name}` as an asset...\n"})

    try:
        async with async_session() as db:
            asset = Asset(
                name=name,
                description=description,
                asset_type="script",
                source_task_id=agent.task_id,
                code=code,
                script_type=script_type,
                env_vars_json=json.dumps(env_vars, ensure_ascii=False),
                allowed_modules_json=json.dumps(allowed_modules, ensure_ascii=False),
            )
            db.add(asset)
            await db.commit()
            await db.refresh(asset)

        # ── 复制 artifacts 到 asset 专属目录 ──
        import shutil
        task_artifact_dir = os.path.join(UPLOADS_DIR, agent.task_id, "captures", "artifacts")
        artifacts_manifest: list[dict] = []
        if os.path.isdir(task_artifact_dir):
            asset_artifact_dir = os.path.join(UPLOADS_DIR, "assets", asset.id, "artifacts")
            os.makedirs(asset_artifact_dir, exist_ok=True)
            for fname in sorted(os.listdir(task_artifact_dir)):
                if not fname.endswith(".joblib"):
                    continue
                src = os.path.join(task_artifact_dir, fname)
                dst = os.path.join(asset_artifact_dir, fname)
                try:
                    shutil.copy2(src, dst)
                    artifacts_manifest.append({
                        "name": fname[:-7],  # strip ".joblib"
                        "size": os.path.getsize(dst),
                        "format": "joblib",
                    })
                except Exception as copy_err:
                    logger.warning(f"Failed to copy artifact {fname}: {copy_err}")

        if artifacts_manifest:
            # 更新 asset 的 artifacts_json
            async with async_session() as db2:
                from app.models import Asset as AssetModel
                asset_upd = await db2.get(AssetModel, asset.id)
                if asset_upd:
                    asset_upd.artifacts_json = json.dumps(artifacts_manifest, ensure_ascii=False)
                    await db2.commit()

        env_summary = ""
        if env_vars:
            env_keys = ", ".join(f"`{k}`" for k in env_vars.keys())
            env_summary = f"| Env Vars | {env_keys} |\n"

        module_summary = ""
        if allowed_modules:
            module_summary = f"| Modules | {', '.join(f'`{m}`' for m in allowed_modules)} |\n"

        code_lines = len(code.strip().split("\n"))

        artifact_summary = ""
        if artifacts_manifest:
            total_size = sum(a["size"] for a in artifacts_manifest)
            artifact_names = ", ".join(f'`{a["name"]}`' for a in artifacts_manifest)
            artifact_summary = f"| Artifacts | {len(artifacts_manifest)} ({total_size:,} bytes): {artifact_names} |\n"
        success_msg = (
            f"✅ **Script saved successfully!**\n\n"
            f"| Property | Value |\n"
            f"|----------|-------|\n"
            f"| Name | `{name}` |\n"
            f"| Type | {script_type} |\n"
            f"| Lines | {code_lines} |\n"
            f"{env_summary}"
            f"{module_summary}"
            f"{artifact_summary}"
            f"\nYou can find this script in the **Assets** tab on the right panel.\n"
            f"Use the **Run** button to execute it independently."
        )
        yield agent._sse({"type": "text", "content": success_msg})

    except Exception as e:
        logger.error(f"Script asset save failed: {e}")
        yield agent._sse({"type": "error", "content": f"Failed to save script: {str(e)}"})

    yield agent._sse({"type": "done"})

async def _save_script_asset_events(
    agent: "BaseAgent", config: dict
) -> AsyncGenerator[dict, None]:
    """用户确认后，将 script 保存为 Asset（事件原生版）"""
    from app.models import Asset
    import shutil

    name = config.get("name", "Untitled Script")
    description = config.get("description", "")
    code = config.get("code", "")
    script_type = config.get("script_type", "general")
    env_vars = config.get("env_vars", {})
    allowed_modules = config.get("allowed_modules", [])

    if not code.strip():
        yield {"type": "error", "content": "Cannot save script: code is empty."}
        yield {"type": "done"}
        return

    yield {"type": "text", "content": f"💾 Saving script `{name}` as an asset...\n"}

    try:
        async with async_session() as db:
            asset = Asset(
                name=name,
                description=description,
                asset_type="script",
                source_task_id=agent.task_id,
                code=code,
                script_type=script_type,
                env_vars_json=json.dumps(env_vars, ensure_ascii=False),
                allowed_modules_json=json.dumps(allowed_modules, ensure_ascii=False),
            )
            db.add(asset)
            await db.commit()
            await db.refresh(asset)

        # ── 复制 artifacts 到 asset 专属目录 ──
        task_artifact_dir = os.path.join(
            UPLOADS_DIR, agent.task_id, "captures", "artifacts"
        )
        artifacts_manifest: list[dict] = []
        if os.path.isdir(task_artifact_dir):
            asset_artifact_dir = os.path.join(
                UPLOADS_DIR, "assets", asset.id, "artifacts"
            )
            os.makedirs(asset_artifact_dir, exist_ok=True)
            for fname in sorted(os.listdir(task_artifact_dir)):
                if not fname.endswith(".joblib"):
                    continue
                src = os.path.join(task_artifact_dir, fname)
                dst = os.path.join(asset_artifact_dir, fname)
                try:
                    shutil.copy2(src, dst)
                    artifacts_manifest.append({
                        "name": fname[:-7],
                        "size": os.path.getsize(dst),
                        "format": "joblib",
                    })
                except Exception as copy_err:
                    logger.warning(f"Failed to copy artifact {fname}: {copy_err}")

        if artifacts_manifest:
            async with async_session() as db2:
                from app.models import Asset as AssetModel
                asset_upd = await db2.get(AssetModel, asset.id)
                if asset_upd:
                    asset_upd.artifacts_json = json.dumps(
                        artifacts_manifest, ensure_ascii=False
                    )
                    await db2.commit()

        env_summary = ""
        if env_vars:
            env_keys = ", ".join(f"`{k}`" for k in env_vars.keys())
            env_summary = f"| Env Vars | {env_keys} |\n"

        module_summary = ""
        if allowed_modules:
            module_summary = (
                f"| Modules | {', '.join(f'`{m}`' for m in allowed_modules)} |\n"
            )

        code_lines = len(code.strip().split("\n"))

        artifact_summary = ""
        if artifacts_manifest:
            total_size = sum(a["size"] for a in artifacts_manifest)
            artifact_names = ", ".join(f'`{a["name"]}`' for a in artifacts_manifest)
            artifact_summary = (
                f"| Artifacts | {len(artifacts_manifest)} "
                f"({total_size:,} bytes): {artifact_names} |\n"
            )

        success_msg = (
            f"✅ **Script saved successfully!**\n\n"
            f"| Property | Value |\n"
            f"|----------|-------|\n"
            f"| Name | `{name}` |\n"
            f"| Type | {script_type} |\n"
            f"| Lines | {code_lines} |\n"
            f"{env_summary}"
            f"{module_summary}"
            f"{artifact_summary}"
            f"\nYou can find this script in the **Assets** tab on the right panel.\n"
            f"Use the **Run** button to execute it independently."
        )
        yield {"type": "text", "content": success_msg}

    except Exception as e:
        logger.error(f"Script asset save failed: {e}")
        yield {"type": "error", "content": f"Failed to save script: {str(e)}"}

    yield {"type": "done"}