# backend/app/services/agent.py

"""
Owl Agent：基于 OpenAI Function Calling 的 ReAct 循环。

核心流程：
1. 构建 system prompt（注入 knowledge 上下文）
2. 调用 LLM（流式），带 tools 定义
3. 若 LLM 返回 tool_call → 沙箱执行代码 → 将结果注入 messages → 回到 2
4. 若 LLM 返回纯文本 → 流式推送 → 结束
5. 最多循环 MAX_TOOL_ROUNDS 次
"""

import os
import json
from typing import AsyncGenerator, Any
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Step, Knowledge
from app.services.data_processor import (
    sanitize_variable_name,
    get_csv_sample_rows,
    read_text_content,
)
from app.tenant_context import open_tenant_session
from app.services.agents.orchestrator import AgentOrchestrator

from app.services.sandbox import execute_code_in_sandbox


# ── 配置 ──────────────────────────────────────────────────────
MAX_TOOL_ROUNDS = 10  # 最大工具调用轮次（防止无限循环）
MAX_HISTORY_STEPS = 30  # 加载的最大历史步骤数

# ── OpenAI 客户端（懒加载） ──────────────────────────────────
_client: AsyncOpenAI | None = None


# ── OpenAI 客户端（从数据库配置创建） ──────────────────────────────────
async def _get_client_from_db(
    db: AsyncSession,
    agent_type: str = "default"
) -> tuple[AsyncOpenAI, str] | None:
    """
    从数据库读取指定Agent的配置，返回 (client, model_id)。
    
    Args:
        db: 数据库会话
        agent_type: Agent类型 ('default'|'plan'|'analyst'|'task_manager')
    """
    from app.models import AgentConfig, LLMProvider
    
    # 查询指定agent配置
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.agent_type == agent_type)
    )
    agent_config = result.scalar_one_or_none()
    
    if not agent_config or not agent_config.provider_id or not agent_config.model_id:
        # 如果指定agent没有配置，回退到default
        if agent_type != "default":
            return await _get_client_from_db(db, "default")
        return None
    
    # 查询关联的 Provider
    result = await db.execute(
        select(LLMProvider).where(LLMProvider.id == agent_config.provider_id)
    )
    provider = result.scalar_one_or_none()
    
    if not provider or not provider.base_url:
        return None
    
    # 创建客户端
    client = AsyncOpenAI(
        api_key=provider.api_key or "",
        base_url=provider.base_url,
    )
    
    return client, agent_config.model_id


async def _load_history_messages(
    task_id: str,
    db: AsyncSession,
    exclude_latest_user: bool = False,
) -> list[ChatCompletionMessageParam]:
    """
    加载对话历史，转换为 OpenAI messages 格式
    
    Args:
        task_id: 任务 ID
        db: 数据库会话
        exclude_latest_user: 是否排除最后一条 user_message（避免重复注入当前消息）
    
    如果 Task 有 compact_context，则：
    1. 用 compact_context 作为第一条 assistant 消息
    2. 只加载 compact_anchor_created_at 之后的新 steps
    """
    from app.models import Step, Task
    from sqlalchemy import select
    
    # 获取 Task
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    
    messages: list[ChatCompletionMessageParam] = []
    
    # 如果有压缩上下文，先添加它
    if task and task.compact_context and task.compact_anchor_created_at:
        messages.append({
            "role": "assistant",
            "content": (
                "[COMPRESSED_CONTEXT_SUMMARY]\n"
                "This summary replaces earlier detailed history.\n"
                "It preserves: user goals, code artifacts, key outputs, decisions.\n"
                "It omits: visualization configs, verbose prose, redundant tool outputs.\n"
                "---\n\n"
                + task.compact_context
            ),
        })
        
        # 只加载 anchor 之后的 steps
        result = await db.execute(
            select(Step)
            .where(
                Step.task_id == task_id,
                Step.created_at > task.compact_anchor_created_at,
            )
            .order_by(Step.created_at.asc())
        )
        recent_steps = list(result.scalars().all())
    else:
        # 没有压缩上下文，加载全部历史（移除 MAX_HISTORY_STEPS 限制）
        result = await db.execute(
            select(Step)
            .where(Step.task_id == task_id)
            .order_by(Step.created_at.asc())
        )
        recent_steps = list(result.scalars().all())
    
    # 如果需要排除最后一条 user_message
    if exclude_latest_user and recent_steps:
        # 从后往前找第一条 user_message
        for i in range(len(recent_steps) - 1, -1, -1):
            if recent_steps[i].step_type == "user_message":
                recent_steps = recent_steps[:i] + recent_steps[i+1:]
                break
    
    # 转换 steps 为 messages
    for s in recent_steps:
        if not s.id or not s.step_type:
            continue
        
        content = s.content or ""
        if s.step_type == "user_message":
            if content.strip():
                messages.append({"role": "user", "content": content})
        elif s.step_type == "tool_use":
            tool_call_id = f"call_{str(s.id)}"
            code = s.code or ""
            code_output = s.code_output or "(no output)"
            
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": "execute_python_code",
                            "arguments": json.dumps({
                                "code": code,
                                "purpose": content,
                            }, ensure_ascii=False),
                        },
                    }
                ],
            })  # type: ignore
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": code_output,
            })  # type: ignore
        elif s.step_type == "assistant_message":
            if content.strip():
                messages.append({"role": "assistant", "content": content})
        elif s.step_type == "visualization":
            if content.strip():
                messages.append({"role": "assistant", "content": f"[Visualization created] {content}"})
        elif s.step_type == "hitl_request":
            hitl_info = ""
            if s.code_output:
                try:
                    hitl_data = json.loads(s.code_output)
                    options_text = ", ".join(
                        f'"{opt.get("label", "")}"' for opt in hitl_data.get("options", [])
                    )
                    hitl_info = (
                        f"[HITL Request] {hitl_data.get('title', '')}: "
                        f"{hitl_data.get('description', '')} "
                        f"Options presented: {options_text}"
                    )
                except json.JSONDecodeError:
                    hitl_info = f"[HITL Request] {content}"
            else:
                hitl_info = f"[HITL Request] {content}"
            if hitl_info.strip():
                messages.append({"role": "assistant", "content": hitl_info})
    return messages

# ── SSE 事件类型定义 ──────────────────────────────────────────
# 每个 SSE event 是一个 JSON 行：
# {"type": "thinking",    "content": "..."}     -- Agent 的思考文本（流式 token）
# {"type": "tool_start",  "code": "...", "purpose": "..."}  -- 即将执行代码
# {"type": "tool_result", "success": bool, "output": "...", "error": "...", "time": float}
# {"type": "text",        "content": "..."}     -- 流式文本 token
# {"type": "step_saved",  "step": {...}}        -- 一个 Step 已持久化
# {"type": "done",        "steps": [...]}       -- 全部完成
# {"type": "error",       "content": "..."}     -- 错误
# {"type": "visualization","title": "...","chart_type":"bar","option": {...}}  -- 生成 ECharts 图表（需要持久化）
# {"type": "hitl_request", "title": "...", "description": "...", "options": [...]}  -- HITL: 请求用户决策

async def run_agent_events(
    task_id: str,
    user_message: str,
    db: AsyncSession,
    mode: str | None = None,
    model_override: tuple[str, str] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Agent 主入口（事件原生版），产出 dict event。

    职责：
    1. 保存用户消息 Step
    2. 消费 orchestrator.run_events() 的 dict 事件
    3. 根据事件类型持久化 Step / Visualization
    4. yield 所有事件（包括 step_saved）
    """
    from app.database import async_session
    from app.models import Task, Step
    from sqlalchemy import select

    # ── 保存用户消息 ──
    async with open_tenant_session() as write_db:
        user_step = Step(
            task_id=task_id,
            role="user",
            step_type="user_message",
            content=user_message,
        )
        write_db.add(user_step)
        await write_db.commit()
        await write_db.refresh(user_step)
        yield {"type": "step_saved", "step": _step_to_dict(user_step)}

    # ── 获取 Task 信息 ──
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        yield {"type": "error", "content": "Task not found"}
        yield {"type": "done", "steps": []}
        return

    execution_mode = mode or task.mode

    if mode and mode != task.mode:
        async with open_tenant_session() as write_db:
            result = await write_db.execute(select(Task).where(Task.id == task_id))
            task_to_update = result.scalar_one_or_none()
            if task_to_update:
                task_to_update.mode = mode
                await write_db.commit()

    # ── 检查 LLM 配置 ──
    client_result = await _get_client_from_db(db)
    if client_result is None:
        error_msg = (
            "⚠️ LLM configuration required\n\n"
            "Please configure your LLM provider and model first:\n"
            "1. Go to **Settings → Providers** to add an API provider\n"
            "2. Then go to **Settings → Agents** to assign a model to the Default Agent"
        )
        yield {"type": "text", "content": error_msg}

        async with open_tenant_session() as write_db:
            error_step = Step(
                task_id=task_id,
                role="assistant",
                step_type="assistant_message",
                content=error_msg,
            )
            write_db.add(error_step)
            await write_db.commit()
            await write_db.refresh(error_step)
            yield {"type": "step_saved", "step": _step_to_dict(error_step)}

        yield {"type": "done", "steps": [_step_to_dict(error_step)]}
        return

    # ── 加载历史消息 ──
    history_messages = await _load_history_messages(task_id, db, exclude_latest_user=True)

    # ── 使用 Orchestrator 调度 ──
    orchestrator = AgentOrchestrator(
        task_id=task_id,
        db=db,
        model_override=model_override,
    )

    saved_steps: list[dict] = []
    accumulated_text = ""
    current_tool_code = ""
    current_tool_purpose = ""

    try:
        async for event in orchestrator.run_events(
            mode=execution_mode,
            user_message=user_message,
            context={"history_messages": history_messages},
        ):
            event_type = event.get("type")

            # ── 累积文本内容 ──
            if event_type == "text":
                accumulated_text += event.get("content", "")

            # ── tool_start：先落盘累积文本，再记录工具信息 ──
            elif event_type == "tool_start":
                if accumulated_text.strip():
                    async with open_tenant_session() as write_db:
                        text_step = Step(
                            task_id=task_id,
                            role="assistant",
                            step_type="assistant_message",
                            content=accumulated_text.strip(),
                        )
                        write_db.add(text_step)
                        await write_db.commit()
                        await write_db.refresh(text_step)
                        saved_steps.append(_step_to_dict(text_step))
                        yield {"type": "step_saved", "step": _step_to_dict(text_step)}
                    accumulated_text = ""

                current_tool_code = event.get("code", "")
                current_tool_purpose = event.get("purpose", "")

            # ── tool_result：保存 tool_use Step ──
            elif event_type == "tool_result":
                async with open_tenant_session() as write_db:
                    tool_step = Step(
                        task_id=task_id,
                        role="assistant",
                        step_type="tool_use",
                        content=current_tool_purpose or "Code execution",
                        code=current_tool_code,
                        code_output=json.dumps({
                            "success": event.get("success"),
                            "output": event.get("output"),
                            "error": event.get("error"),
                            "execution_time": event.get("time", 0),
                            "dataframes": event.get("dataframes", []),
                        }, ensure_ascii=False),
                    )
                    write_db.add(tool_step)
                    await write_db.commit()
                    await write_db.refresh(tool_step)
                    saved_steps.append(_step_to_dict(tool_step))
                    yield {"type": "step_saved", "step": _step_to_dict(tool_step)}

                current_tool_code = ""
                current_tool_purpose = ""

            # ── plan_generated ──
            elif event_type == "plan_generated":
                if accumulated_text.strip():
                    async with open_tenant_session() as write_db:
                        text_step = Step(
                            task_id=task_id,
                            role="assistant",
                            step_type="assistant_message",
                            content=accumulated_text.strip(),
                        )
                        write_db.add(text_step)
                        await write_db.commit()
                        await write_db.refresh(text_step)
                        saved_steps.append(_step_to_dict(text_step))
                        yield {"type": "step_saved", "step": _step_to_dict(text_step)}
                    accumulated_text = ""

                plan_data = event.get("plan", {})
                async with open_tenant_session() as write_db:
                    plan_step = Step(
                        task_id=task_id,
                        role="assistant",
                        step_type="assistant_message",
                        content=f"Generated plan with {len(plan_data.get('subtasks', []))} subtasks",
                        code_output=json.dumps(plan_data, ensure_ascii=False),
                    )
                    write_db.add(plan_step)
                    await write_db.commit()
                    await write_db.refresh(plan_step)
                    saved_steps.append(_step_to_dict(plan_step))
                    yield {"type": "step_saved", "step": _step_to_dict(plan_step)}

            # ── visualization ──
            elif event_type == "visualization":
                if accumulated_text.strip():
                    async with open_tenant_session() as write_db:
                        text_step = Step(
                            task_id=task_id,
                            role="assistant",
                            step_type="assistant_message",
                            content=accumulated_text.strip(),
                        )
                        write_db.add(text_step)
                        await write_db.commit()
                        await write_db.refresh(text_step)
                        saved_steps.append(_step_to_dict(text_step))
                        yield {"type": "step_saved", "step": _step_to_dict(text_step)}
                    accumulated_text = ""

                from app.models import Visualization

                title = str(event.get("title", "")).strip() or "Untitled Chart"
                chart_type = str(event.get("chart_type", "")).strip() or "bar"
                option = event.get("option", {})

                try:
                    option_json = json.dumps(option, ensure_ascii=False)
                except Exception:
                    yield {"type": "error", "content": "Invalid visualization option JSON"}
                    continue

                if len(option_json) > 200_000:
                    yield {"type": "error", "content": "Visualization option too large (>200KB). Please aggregate data."}
                    continue

                async with open_tenant_session() as write_db:
                    viz = Visualization(
                        task_id=task_id,
                        title=title,
                        chart_type=chart_type,
                        option_json=option_json,
                    )
                    write_db.add(viz)
                    await write_db.commit()
                    await write_db.refresh(viz)

                    viz_step = Step(
                        task_id=task_id,
                        role="assistant",
                        step_type="visualization",
                        content=title,
                        code_output=json.dumps(
                            {
                                "visualization_id": viz.id,
                                "title": title,
                                "chart_type": chart_type,
                                "option": option,
                            },
                            ensure_ascii=False,
                        ),
                    )
                    write_db.add(viz_step)
                    await write_db.commit()
                    await write_db.refresh(viz_step)

                    saved_steps.append(_step_to_dict(viz_step))
                    yield {"type": "step_saved", "step": _step_to_dict(viz_step)}

            # ── hitl_request ──
            elif event_type == "hitl_request":
                if accumulated_text.strip():
                    async with open_tenant_session() as write_db:
                        text_step = Step(
                            task_id=task_id,
                            role="assistant",
                            step_type="assistant_message",
                            content=accumulated_text.strip(),
                        )
                        write_db.add(text_step)
                        await write_db.commit()
                        await write_db.refresh(text_step)
                        saved_steps.append(_step_to_dict(text_step))
                        yield {"type": "step_saved", "step": _step_to_dict(text_step)}
                    accumulated_text = ""

                hitl_data: dict[str, Any] = {
                    "title": event.get("title", ""),
                    "description": event.get("description", ""),
                    "options": event.get("options", []),
                }
                if event.get("hitl_type"):
                    hitl_data["hitl_type"] = event["hitl_type"]
                if event.get("pipeline") is not None:
                    hitl_data["pipeline"] = event["pipeline"]
                if event.get("script") is not None:
                    hitl_data["script"] = event["script"]
                if event.get("sop") is not None:
                    hitl_data["sop"] = event["sop"]

                async with open_tenant_session() as write_db:
                    hitl_step = Step(
                        task_id=task_id,
                        role="assistant",
                        step_type="hitl_request",
                        content=event.get("description", "Awaiting your guidance"),
                        code_output=json.dumps(hitl_data, ensure_ascii=False),
                    )
                    write_db.add(hitl_step)
                    await write_db.commit()
                    await write_db.refresh(hitl_step)
                    saved_steps.append(_step_to_dict(hitl_step))
                    yield {"type": "step_saved", "step": _step_to_dict(hitl_step)}

            # ── 透传所有事件（text / heartbeat / mode_switch / done 等） ──
            yield event

        # ── 流结束，落盘剩余文本 ──
        if accumulated_text.strip():
            async with open_tenant_session() as write_db:
                final_text_step = Step(
                    task_id=task_id,
                    role="assistant",
                    step_type="assistant_message",
                    content=accumulated_text.strip(),
                )
                write_db.add(final_text_step)
                await write_db.commit()
                await write_db.refresh(final_text_step)
                saved_steps.append(_step_to_dict(final_text_step))
                yield {"type": "step_saved", "step": _step_to_dict(final_text_step)}

        yield {"type": "done", "steps": saved_steps}

    except Exception as e:
        import traceback
        traceback.format_exc()
        yield {"type": "error", "content": f"Agent error: {str(e)}"}

        try:
            async with open_tenant_session() as write_db:
                err_step = Step(
                    task_id=task_id,
                    role="assistant",
                    step_type="assistant_message",
                    content=f"⚠️ Error: {str(e)}",
                )
                write_db.add(err_step)
                await write_db.commit()
        except Exception:
            pass

        yield {"type": "done", "steps": []}

async def run_agent_stream(
    task_id: str,
    user_message: str,
    db: AsyncSession,
    mode: str | None = None,
    model_override: tuple[str, str] | None = None,
) -> AsyncGenerator[str, None]:
    """
    兼容层：包装 run_agent_events() 为 SSE 字符串输出。

    保留此函数是为了向后兼容 chat.py 等现有调用方。
    """
    async for event in run_agent_events(
        task_id=task_id,
        user_message=user_message,
        db=db,
        mode=mode,
        model_override=model_override,
    ):
        yield _sse(event)
        
# ── 工具函数 ──────────────────────────────────────────────────

def _sse(data: dict) -> str:
    """将 dict 编码为 SSE data 行"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _step_to_dict(step: Step) -> dict:
    """Step ORM → 可序列化 dict"""
    return {
        "id": step.id,
        "task_id": step.task_id,
        "role": step.role,
        "step_type": step.step_type,
        "content": step.content,
        "code": step.code,
        "code_output": step.code_output,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    }