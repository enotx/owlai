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
import uuid
from app.services.sandbox import execute_code_in_sandbox

# ── 配置 ──────────────────────────────────────────────────────
MAX_TOOL_ROUNDS = 10  # 最大工具调用轮次（防止无限循环）
MAX_HISTORY_STEPS = 30  # 加载的最大历史步骤数

# ── OpenAI 客户端（懒加载） ──────────────────────────────────
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        from dotenv import load_dotenv
        load_dotenv()
        _client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
    return _client


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
    4. csv_var_map: {变量名: 文件路径} 用于沙箱

    Returns: (dataset_context, text_context, variable_reference, csv_var_map)
    """
    result = await db.execute(
        select(Knowledge).where(Knowledge.task_id == task_id)
    )
    knowledge_items = list(result.scalars().all())

    dataset_parts: list[str] = []
    text_parts: list[str] = []
    var_ref_parts: list[str] = []
    csv_var_map: dict[str, str] = {}

    for k in knowledge_items:
        if k.type == "csv" and k.file_path and os.path.exists(k.file_path):
            var_name = sanitize_variable_name(k.name)
            csv_var_map[var_name] = os.path.abspath(k.file_path)

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

    return dataset_context, text_context, variable_reference, csv_var_map


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


async def run_agent_stream(
    task_id: str,
    user_message: str,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """
    Agent 主循环（生成器），产出 SSE 格式字符串。

    Args:
        task_id: 任务 ID
        user_message: 用户输入
        db: 数据库会话（仅用于读取上下文/历史，写入由独立会话完成）
    """
    from app.database import async_session

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

    try:
        # ── 构建上下文 ────────────────────────────────────────
        dataset_ctx, text_ctx, var_ref, csv_var_map = await _build_knowledge_context(task_id, db)

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
        )

        # ── 加载历史 ──────────────────────────────────────────
        history_messages = await _load_history_messages(task_id, db)

        # 组装完整 messages
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            *history_messages,
        ]

        # 如果最后一条不是刚才的 user_message（历史可能已包含），确保用户消息在末尾
        # 因为 user_step 刚保存，history 加载时不含它（时序问题），所以显式追加
        # 去重：检查 history 末尾是否已包含刚保存的 user_message
        # （write_db commit 后，db 新查询可能已读到该条记录）
        already_included = (
            len(history_messages) > 0
            and history_messages[-1].get("role") == "user"
            and history_messages[-1].get("content") == user_message
        )
        if not already_included:
            messages.append({"role": "user", "content": user_message})

        client = _get_client()
        model = os.getenv("OPENAI_MODEL", "gpt-4o")
        saved_steps: list[dict] = []

        # ── ReAct 循环 ────────────────────────────────────────
        for round_idx in range(MAX_TOOL_ROUNDS):
            try:
                stream = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=TOOLS,  # type: ignore
                    tool_choice="auto",
                    stream=True,
                    temperature=0.4,
                    max_tokens=4096,
                )
            except Exception as e:
                yield _sse({"type": "error", "content": f"LLM request failed: {str(e)}"})
                # 保存错误 Step
                async with async_session() as write_db:
                    err_step = Step(
                        task_id=task_id,
                        role="assistant",
                        step_type="assistant_message",
                        content=f"⚠️ LLM request failed: {str(e)}",
                    )
                    write_db.add(err_step)
                    await write_db.commit()
                    await write_db.refresh(err_step)
                    saved_steps.append(_step_to_dict(err_step))
                    yield _sse({"type": "step_saved", "step": _step_to_dict(err_step)})
                break

            # 逐 chunk 累积
            text_content = ""
            tool_calls_acc: dict[int, dict[str, str]] = {}
            # tool_calls_acc[index] = {"id": "...", "name": "...", "arguments": "..."}

            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue

                delta = choice.delta

                # ── 文本流 ──────────────────────────────────
                if delta.content:
                    token = delta.content
                    text_content += token
                    yield _sse({"type": "text", "content": token})

                # ── Tool call 流 ────────────────────────────
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc_delta.id:
                            tool_calls_acc[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_acc[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

                # 检查是否结束
                if choice.finish_reason:
                    break

            # ── 处理本轮结果 ────────────────────────────────

            # 情况 A：有 tool_calls → 执行代码 → 继续循环
            if tool_calls_acc:
                # 如果同时有文本，先保存为思考步骤
                if text_content.strip():
                    async with async_session() as write_db:
                        thought_step = Step(
                            task_id=task_id,
                            role="assistant",
                            step_type="assistant_message",
                            content=text_content.strip(),
                        )
                        write_db.add(thought_step)
                        await write_db.commit()
                        await write_db.refresh(thought_step)
                        saved_steps.append(_step_to_dict(thought_step))
                        yield _sse({"type": "step_saved", "step": _step_to_dict(thought_step)})

                # 构造 assistant message（带 tool_calls）给 messages 上下文
                tool_calls_for_api = []
                for idx in sorted(tool_calls_acc.keys()):
                    tc = tool_calls_acc[idx]
                    tool_calls_for_api.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    })

                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": text_content or None,
                    "tool_calls": tool_calls_for_api,
                }
                messages.append(assistant_msg)  # type: ignore

                # 逐个执行 tool_call
                for idx in sorted(tool_calls_acc.keys()):
                    tc = tool_calls_acc[idx]
                    tool_call_id = tc["id"]
                    func_name = tc["name"]
                    try:
                        args = json.loads(tc["arguments"])
                    except (json.JSONDecodeError, TypeError):
                        # 参数解析失败，直接返回错误而不执行
                        error_msg = f"Failed to parse tool arguments: {tc['arguments'][:200]}"
                        yield _sse({
                            "type": "tool_result",
                            "success": False,
                            "output": None,
                            "error": error_msg,
                            "time": 0,
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": f"ERROR: {error_msg}",
                        })  # type: ignore
                        continue

                    if func_name == "execute_python_code":
                        code = args.get("code", "")
                        purpose = args.get("purpose", "")

                        # 通知前端：即将执行代码
                        yield _sse({
                            "type": "tool_start",
                            "code": code,
                            "purpose": purpose,
                        })

                        # 创建 DataFrame 捕获目录
                        capture_id = uuid.uuid4().hex[:12]
                        capture_dir = os.path.join(
                            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "data", "uploads", task_id, "captures",
                        )
                        os.makedirs(capture_dir, exist_ok=True)
                        # 沙箱执行
                        try:
                            exec_result = await execute_code_in_sandbox(
                                code=code,
                                csv_var_map=csv_var_map,
                                capture_dir=capture_dir,
                            )
                        except Exception as sandbox_err:
                            exec_result = {
                                "success": False,
                                "output": None,
                                "error": f"Sandbox crashed: {str(sandbox_err)}",
                                "execution_time": 0.0,
                            }


                        # 重命名捕获的 DataFrame 文件，注入 capture_id
                        captured_dfs = exec_result.get("dataframes", [])
                        for df_meta in captured_dfs:
                            df_meta["capture_id"] = capture_id
                            old_path = os.path.join(capture_dir, f"{df_meta['name']}.json")
                            new_name = f"{capture_id}_{df_meta['name']}.json"
                            new_path = os.path.join(capture_dir, new_name)
                            if os.path.exists(old_path):
                                try:
                                    os.rename(old_path, new_path)
                                except OSError:
                                    pass

                        # 通知前端：执行结果（含 dataframes 元数据）
                        yield _sse({
                            "type": "tool_result",
                            "success": exec_result["success"],
                            "output": exec_result.get("output"),
                            "error": exec_result.get("error"),
                            "time": exec_result.get("execution_time", 0),
                            "dataframes": captured_dfs,
                        })

                        # 组装 tool result 文本
                        if exec_result["success"]:
                            tool_output = exec_result.get("output") or "(no output)"
                        else:
                            tool_output = f"ERROR:\n{exec_result.get('error', 'Unknown error')}"
                            if exec_result.get("output"):
                                tool_output = f"STDOUT:\n{exec_result['output']}\n\n{tool_output}"

                        # 限制回传给 LLM 的输出长度（节省 token）
                        if len(tool_output) > 8000:
                            tool_output = tool_output[:8000] + "\n\n[Output truncated for context limit]"

                        # 追加 tool result 到 messages
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": tool_output,
                        })  # type: ignore

                        # 持久化为 tool_use Step
                        async with async_session() as write_db:
                            tool_step = Step(
                                task_id=task_id,
                                role="assistant",
                                step_type="tool_use",
                                content=purpose,
                                code=code,
                                code_output=json.dumps({
                                    "success": exec_result["success"],
                                    "output": exec_result.get("output"),
                                    "error": exec_result.get("error"),
                                    "execution_time": exec_result.get("execution_time", 0),
                                    "dataframes": captured_dfs,
                                }, ensure_ascii=False),
                            )
                            write_db.add(tool_step)
                            await write_db.commit()
                            await write_db.refresh(tool_step)
                            saved_steps.append(_step_to_dict(tool_step))
                            yield _sse({"type": "step_saved", "step": _step_to_dict(tool_step)})
                    else:
                        # 不认识的函数
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": f"Unknown function: {func_name}",
                        })  # type: ignore

                # 继续循环 → 回到 LLM 调用
                continue

            # 情况 B：纯文本回复 → 保存并结束
            if text_content.strip():
                async with async_session() as write_db:
                    answer_step = Step(
                        task_id=task_id,
                        role="assistant",
                        step_type="assistant_message",
                        content=text_content.strip(),
                    )
                    write_db.add(answer_step)
                    await write_db.commit()
                    await write_db.refresh(answer_step)
                    saved_steps.append(_step_to_dict(answer_step))
                    yield _sse({"type": "step_saved", "step": _step_to_dict(answer_step)})

            # 纯文本意味着 Agent 认为回答完成 → 退出循环
            break

        else:
            # for-else: 达到 MAX_TOOL_ROUNDS 上限
            yield _sse({
                "type": "text",
                "content": f"\n\n⚠️ Reached maximum analysis rounds ({MAX_TOOL_ROUNDS}). "
                        "Please ask a follow-up question to continue."
            })
            async with async_session() as write_db:
                limit_step = Step(
                    task_id=task_id,
                    role="assistant",
                    step_type="assistant_message",
                    content=f"⚠️ Reached maximum analysis rounds ({MAX_TOOL_ROUNDS}). "
                            "Please ask a follow-up question to continue.",
                )
                write_db.add(limit_step)
                await write_db.commit()
                await write_db.refresh(limit_step)
                saved_steps.append(_step_to_dict(limit_step))

        # ── 发送完成信号 ──────────────────────────────────────
        yield _sse({"type": "done", "steps": saved_steps})
    except Exception as e:
        # 全局兜底：确保前端一定收到错误信息
        import traceback
        error_detail = traceback.format_exc()
        yield _sse({
            "type": "error",
            "content": f"Agent internal error: {str(e)}",
        })
        # 持久化错误
        try:
            async with async_session() as write_db:
                err_step = Step(
                    task_id=task_id,
                    role="assistant",
                    step_type="assistant_message",
                    content=f"⚠️ Internal error: {str(e)}",
                )
                write_db.add(err_step)
                await write_db.commit()
        except Exception:
            pass  # 数据库写入失败也不能再抛
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