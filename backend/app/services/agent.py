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
from app.services.agents.orchestrator import AgentOrchestrator

from app.services.sandbox import execute_code_in_sandbox

from app.config import UPLOADS_DIR


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


# ── Tool 定义（OpenAI Function Calling 格式） ────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_python_code",
            "description": (
                "Execute Python code in a sandboxed environment with pandas and numpy. "
                "All CSV datasets are pre-loaded as DataFrames. "
                "Use print() to output results. "
                "Use this tool to explore data, compute statistics, verify hypotheses, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute. Use print() for output.",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Brief description of what this code does (1 sentence).",
                    },
                },
                "required": ["code", "purpose"],
            },
        },
    }
]


# ── System Prompt 构建 ────────────────────────────────────────
SYSTEM_PROMPT_TEMPLATE = """\
You are **Owl 🦉**, an expert AI data analyst.

## Your Approach
You MUST work step-by-step:
1. **Understand** — Read the user's question carefully. If unclear, ask for clarification BEFORE doing analysis.
2. **Explore** — Use `execute_python_code` to inspect the data (shape, distributions, missing values, etc.).
3. **Analyze** — Form hypotheses, write code to test them, iterate.
4. **Conclude** — Summarize findings with evidence (numbers, statistics).

## Rules
- **ALWAYS explore data first** before drawing conclusions. Never guess.
- **One step at a time** — do NOT try to answer everything in one giant code block. Break it down.
- If your analysis direction is uncertain, **pause and ask the user** which direction they prefer.
- Answer in the **same language** the user uses.
- When presenting results, be concise but include key numbers.
- If the user hasn't uploaded data yet, tell them to upload first.

## DataFrame Naming Convention (IMPORTANT)
When your code produces **key result DataFrames** that would be valuable for the user to preview, \
you MUST name them using one of these prefixes so the system can auto-capture them:
- `result` / `result_xxx` — final or intermediate analysis results (e.g. `result`, `result_top10`, `result_by_region`)
- `output` / `output_xxx` — processed/transformed data ready for review (e.g. `output`, `output_cleaned`, `output_pivot`)
- `summary` / `summary_xxx` — aggregated summaries or statistics (e.g. `summary`, `summary_stats`, `summary_monthly`)
Examples:
```python
# ✅ Good — will be captured for user preview
result_top10 = df.nlargest(10, 'revenue')
summary_by_city = df.groupby('city').agg({{'revenue': 'sum'}}).reset_index()
output = df[df['status'] == 'active']
# ❌ Bad — generic names won't be prioritized
temp = df.nlargest(10, 'revenue')
x = df.groupby('city').agg({{'revenue': 'sum'}})



## Available Datasets
{dataset_context}

## Reference Documents
{text_context}

## Variable Name Reference
When writing code, use these pre-loaded DataFrame variable names:
{variable_reference}
"""


async def _build_knowledge_context(
    task_id: str, db: AsyncSession
) -> tuple[str, str, str, dict[str, str]]:
    """
    构建三部分上下文：
    1. dataset_context: CSV 元数据 + 样本行
    2. text_context: TXT 全文
    3. variable_reference: 变量名对照表
    4. data_var_map: {变量名: 文件路径} 用于沙箱

    Returns: (dataset_context, text_context, variable_reference, data_var_map)
    """
    result = await db.execute(
        select(Knowledge).where(Knowledge.task_id == task_id)
    )
    knowledge_items = list(result.scalars().all())

    dataset_parts: list[str] = []
    text_parts: list[str] = []
    var_ref_parts: list[str] = []
    data_var_map: dict[str, str] = {}

    for k in knowledge_items:
        if k.type == "csv" and k.file_path and os.path.exists(k.file_path):
            var_name = sanitize_variable_name(k.name)
            data_var_map[var_name] = os.path.abspath(k.file_path)

            # 元数据
            section = f"### 📊 {k.name}  →  variable: `{var_name}`\n"
            if k.metadata_json:
                try:
                    meta = json.loads(k.metadata_json)
                    shape = meta.get("shape", [0, 0])
                    section += f"- **Shape**: {shape[0]:,} rows × {shape[1]} columns\n"
                    if "columns" in meta and "dtypes" in meta:
                        col_info = ", ".join(
                            f"`{c}` ({meta['dtypes'].get(c, '?')})"
                            for c in meta["columns"]
                        )
                        section += f"- **Columns**: {col_info}\n"
                    if "describe" in meta:
                        section += f"- **Statistics**:\n```\n{json.dumps(meta['describe'], indent=2, ensure_ascii=False)[:2000]}\n```\n"
                except json.JSONDecodeError:
                    section += f"- Metadata: {k.metadata_json[:500]}\n"

            # 样本行（前 200 行）
            try:
                sample = get_csv_sample_rows(k.file_path, n_rows=200)
                # 限制样本文本长度，防止 token 爆炸
                if len(sample) > 5000:
                    sample = sample[:5000] + "\n... [sample truncated]"
                section += f"- **Sample rows (first 200)**:\n```\n{sample}\n```\n"
            except Exception:
                pass

            dataset_parts.append(section)
            var_ref_parts.append(f"- `{var_name}` ← {k.name}")

        elif k.type in ("text", "backstory") and k.file_path and os.path.exists(k.file_path):
            try:
                content = read_text_content(k.file_path)
                text_parts.append(f"### 📄 {k.name}\n{content}")
            except Exception as e:
                text_parts.append(f"### 📄 {k.name}\n[Error reading file: {e}]")

    dataset_context = "\n".join(dataset_parts) if dataset_parts else "[No datasets uploaded yet.]"
    text_context = "\n\n".join(text_parts) if text_parts else "[No reference documents.]"
    variable_reference = "\n".join(var_ref_parts) if var_ref_parts else "[No datasets available.]"

    return dataset_context, text_context, variable_reference, data_var_map


async def _load_history_messages(
    task_id: str, db: AsyncSession
) -> list[ChatCompletionMessageParam]:
    """
    加载对话历史，转换为 OpenAI messages 格式。
    tool_use 类型的 Step 需要还原为 assistant(tool_call) + tool(result) 对。
    """
    result = await db.execute(
        select(Step)
        .where(Step.task_id == task_id)
        .order_by(Step.created_at.asc())
    )
    all_steps = list(result.scalars().all())
    # 取最近 N 条
    recent = all_steps[-MAX_HISTORY_STEPS:]

    messages: list[ChatCompletionMessageParam] = []
    for s in recent:
        if s.step_type == "user_message":
            messages.append({"role": "user", "content": s.content})
        elif s.step_type == "tool_use":
            # 还原为 tool_call + tool_result 对
            tool_call_id = f"call_{s.id[:20]}"
            messages.append({
                "role": "assistant",
                "content": s.content or "",
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": "execute_python_code",
                            "arguments": json.dumps({
                                "code": s.code or "",
                                "purpose": s.content or "",
                            }),
                        },
                    }
                ],
            })  # type: ignore
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": s.code_output or "(no output)",
            })  # type: ignore
        elif s.step_type == "assistant_message":
            messages.append({"role": "assistant", "content": s.content})
        elif s.step_type == "visualization":
            # 对 LLM 来说，可视化属于展示结果；这里作为 assistant 的简短描述即可
            messages.append({"role": "assistant", "content": f"[Visualization created] {s.content}"})
        elif s.step_type == "hitl_request":
            # HITL 请求在 LLM 历史中表现为 assistant 的说明
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
                    hitl_info = f"[HITL Request] {s.content}"
            else:
                hitl_info = f"[HITL Request] {s.content}"
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


async def run_agent_stream(
    task_id: str,
    user_message: str,
    db: AsyncSession,
    mode: str | None = None,
    model_override: tuple[str, str] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Agent 主入口（生成器），产出 SSE 格式字符串。
    
    Args:
        task_id: 任务ID
        user_message: 用户消息
        db: 数据库会话
        mode: 可选的执行模式 ('auto'|'plan'|'analyst')，如果为None则从Task读取
        model_override: 用户显式指定的模型 (provider_id, model_id)
    """
    from app.database import async_session
    from app.models import Task, Step
    from sqlalchemy import select
    
    # ── 保存用户消息 ──────────────────────────────────────
    async with async_session() as write_db:
        user_step = Step(
            task_id=task_id,
            role="user",
            step_type="user_message",
            content=user_message,
        )
        write_db.add(user_step)
        await write_db.commit()
        await write_db.refresh(user_step)
        yield _sse({"type": "step_saved", "step": _step_to_dict(user_step)})
    
    # ── 获取Task信息 ──────────────────────────────────────
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        yield _sse({"type": "error", "content": "Task not found"})
        yield _sse({"type": "done", "steps": []})
        return
    
    # 确定执行模式
    execution_mode = mode or task.mode
    
    # 如果用户切换了模式，更新Task
    if mode and mode != task.mode:
        async with async_session() as write_db:
            result = await write_db.execute(select(Task).where(Task.id == task_id))
            task_to_update = result.scalar_one_or_none()
            if task_to_update:
                task_to_update.mode = mode
                await write_db.commit()
    
    # ── 检查 LLM 配置 ──────────────────────────────────────
    client_result = await _get_client_from_db(db)
    if client_result is None:
        error_msg = (
            "⚠️ LLM configuration required\n\n"
            "Please configure your LLM provider and model first:\n"
            "1. Go to **Settings → Providers** to add an API provider\n"
            "2. Then go to **Settings → Agents** to assign a model to the Default Agent"
        )
        yield _sse({"type": "text", "content": error_msg})
        
        async with async_session() as write_db:
            error_step = Step(
                task_id=task_id,
                role="assistant",
                step_type="assistant_message",
                content=error_msg,
            )
            write_db.add(error_step)
            await write_db.commit()
            await write_db.refresh(error_step)
            yield _sse({"type": "step_saved", "step": _step_to_dict(error_step)})
        
        yield _sse({"type": "done", "steps": [_step_to_dict(error_step)]})
        return
    
    client, model = client_result
    
    # ── 加载历史消息 ──────────────────────────────────────
    history_messages = await _load_history_messages(task_id, db)
    
    # ── 使用 Orchestrator 调度 ────────────────────────────
    orchestrator = AgentOrchestrator(
        task_id=task_id,
        db=db,
        model_override=model_override,
    )
    
    saved_steps: list[dict] = []
    
    # 维护状态
    accumulated_text = ""  # 累积的文本内容
    current_tool_code = ""  # 当前工具的代码
    current_tool_purpose = ""  # 当前工具的目的
    
    try:
        async for event_line in orchestrator.run(
            mode=execution_mode,
            user_message=user_message,
            context={"history_messages": history_messages},
        ):
            # 解析事件
            if event_line.startswith("data: "):
                try:
                    event_data = json.loads(event_line[6:])
                    event_type = event_data.get("type")
                    
                    # 累积文本内容
                    if event_type == "text":
                        accumulated_text += event_data.get("content", "")
                    
                    # 记录工具信息
                    elif event_type == "tool_start":
                        # 如果有累积的文本，先保存为 assistant_message
                        if accumulated_text.strip():
                            async with async_session() as write_db:
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
                                yield _sse({"type": "step_saved", "step": _step_to_dict(text_step)})
                            accumulated_text = ""  # 清空
                        
                        # 记录当前工具信息
                        current_tool_code = event_data.get("code", "")
                        current_tool_purpose = event_data.get("purpose", "")
                    
                    # 保存 tool_use Step
                    elif event_type == "tool_result":
                        async with async_session() as write_db:
                            tool_step = Step(
                                task_id=task_id,
                                role="assistant",
                                step_type="tool_use",
                                content=current_tool_purpose or "Code execution",
                                code=current_tool_code,
                                code_output=json.dumps({
                                    "success": event_data.get("success"),
                                    "output": event_data.get("output"),
                                    "error": event_data.get("error"),
                                    "execution_time": event_data.get("time", 0),
                                    "dataframes": event_data.get("dataframes", []),
                                }, ensure_ascii=False),
                            )
                            write_db.add(tool_step)
                            await write_db.commit()
                            await write_db.refresh(tool_step)
                            saved_steps.append(_step_to_dict(tool_step))
                            yield _sse({"type": "step_saved", "step": _step_to_dict(tool_step)})
                        
                        # 清空工具信息
                        current_tool_code = ""
                        current_tool_purpose = ""
                    
                    # plan_generated 事件
                    elif event_type == "plan_generated":
                        # 先保存累积的文本
                        if accumulated_text.strip():
                            async with async_session() as write_db:
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
                                yield _sse({"type": "step_saved", "step": _step_to_dict(text_step)})
                            accumulated_text = ""
                        
                        # 保存 plan
                        plan_data = event_data.get("plan", {})
                        async with async_session() as write_db:
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
                            yield _sse({"type": "step_saved", "step": _step_to_dict(plan_step)})

                    # visualization 事件：持久化 Visualization + 保存一个 visualization Step
                    elif event_type == "visualization":
                        # 先把累积的文本落库（避免“图表前的文字”丢失）
                        if accumulated_text.strip():
                            async with async_session() as write_db:
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
                                yield _sse({"type": "step_saved", "step": _step_to_dict(text_step)})
                            accumulated_text = ""

                        from app.models import Visualization

                        title = str(event_data.get("title", "")).strip() or "Untitled Chart"
                        chart_type = str(event_data.get("chart_type", "")).strip() or "bar"
                        option = event_data.get("option", {})

                        # 基础安全/体积限制：避免 option 过大导致 DB/前端卡死
                        try:
                            option_json = json.dumps(option, ensure_ascii=False)
                        except Exception:
                            yield _sse({"type": "error", "content": "Invalid visualization option JSON"})
                            continue

                        if len(option_json) > 200_000:
                            yield _sse({"type": "error", "content": "Visualization option too large (>200KB). Please aggregate data."})
                            continue

                        async with async_session() as write_db:
                            viz = Visualization(
                                task_id=task_id,
                                title=title,
                                chart_type=chart_type,
                                option_json=option_json,
                            )
                            write_db.add(viz)
                            await write_db.commit()
                            await write_db.refresh(viz)

                            # 写一个 Step：step_type = visualization
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
                                        "option": option,  # 直接存一份给前端渲染（历史也能回放）
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                            write_db.add(viz_step)
                            await write_db.commit()
                            await write_db.refresh(viz_step)

                            saved_steps.append(_step_to_dict(viz_step))
                            yield _sse({"type": "step_saved", "step": _step_to_dict(viz_step)})
                    # hitl_request 事件：保存为 hitl_request Step
                    elif event_type == "hitl_request":
                        # 先保存累积的文本
                        if accumulated_text.strip():
                            async with async_session() as write_db:
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
                                yield _sse({"type": "step_saved", "step": _step_to_dict(text_step)})
                            accumulated_text = ""
                        
                        # 保存 HITL 请求 Step（保留扩展字段：pipeline / script）
                        hitl_data = {
                            "title": event_data.get("title", ""),
                            "description": event_data.get("description", ""),
                            "options": event_data.get("options", []),
                        }
                        if event_data.get("hitl_type"):
                            hitl_data["hitl_type"] = event_data["hitl_type"]
                        if event_data.get("pipeline") is not None:
                            hitl_data["pipeline"] = event_data["pipeline"]
                        if event_data.get("script") is not None:
                            hitl_data["script"] = event_data["script"]
                        # Preserve extra fields for pipeline_confirmation
                        if event_data.get("hitl_type"):
                            hitl_data["hitl_type"] = event_data["hitl_type"]
                        if event_data.get("pipeline"):
                            hitl_data["pipeline"] = event_data["pipeline"]

                        async with async_session() as write_db:
                            hitl_step = Step(
                                task_id=task_id,
                                role="assistant",
                                step_type="hitl_request",
                                content=event_data.get("description", "Awaiting your guidance"),
                                code_output=json.dumps(hitl_data, ensure_ascii=False),
                            )
                            write_db.add(hitl_step)
                            await write_db.commit()
                            await write_db.refresh(hitl_step)
                            saved_steps.append(_step_to_dict(hitl_step))
                            yield _sse({"type": "step_saved", "step": _step_to_dict(hitl_step)})
                except json.JSONDecodeError:
                    pass
            
            # 转发原始事件
            yield event_line
        
        # 流结束时，如果还有累积的文本，保存它
        if accumulated_text.strip():
            async with async_session() as write_db:
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
                yield _sse({"type": "step_saved", "step": _step_to_dict(final_text_step)})
        
        # 发送完成信号
        yield _sse({"type": "done", "steps": saved_steps})
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        yield _sse({"type": "error", "content": f"Agent error: {str(e)}"})
        
        try:
            async with async_session() as write_db:
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
        
        yield _sse({"type": "done", "steps": []})

        
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