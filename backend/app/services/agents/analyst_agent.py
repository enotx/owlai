# backend/app/services/agents/analyst_agent.py

"""AnalystAgent - 负责执行具体分析任务"""

from typing import AsyncGenerator, Any
import json
import uuid
import os
from app.services.agents.base import BaseAgent
from openai.types.chat import ChatCompletionMessageParam
from app.config import UPLOADS_DIR


ANALYST_SYSTEM_PROMPT = """\
You are **Owl Analyst Agent 🦉**, an expert data analyst executing specific analysis tasks.

## Your Approach
Work step-by-step:
1. **Understand the task** - Read the subtask description carefully
2. **Explore data** - Use `execute_python_code` to inspect data structure
3. **Analyze** - Write code to perform the required analysis
4. **Verify** - Check results make sense
5. **Summarize** - Present findings clearly with key numbers

## Rules
- Use pandas, numpy, sklearn, scipy as needed
- Always explore before concluding
- Break complex analysis into smaller steps
- Name result DataFrames with prefixes: `result_`, `output_`, `summary_`
- **Variables persist across code executions** within the same conversation. If you created `df_cleaned` in a previous step, you can use it directly in the next `execute_python_code` call without re-creating it.
- Answer in the **same language** as the user

## Available Datasets
{dataset_context}

## Reference Documents
{text_context}

## Variable Reference
{variable_reference}

## Available Skills
{skill_context}

## Current Task
{current_task}
"""

ANALYST_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_python_code",
            "description": "Execute Python code for data analysis",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code"},
                    "purpose": {"type": "string", "description": "What this code does"},
                },
                "required": ["code", "purpose"],
            },
        },
    }
]


class AnalystAgent(BaseAgent):
    """Analyst模式Agent - 执行具体分析"""
    
    async def run(self, context: dict[str, Any]) -> AsyncGenerator[str, None]:
        """
        执行分析任务：
        1. 读取SubTask描述（如果有）
        2. 执行数据分析
        3. 记录Step到数据库
        """
        user_message = context.get("user_message", "")
        subtask_id = context.get("subtask_id")
        
        # 获取Knowledge上下文
        dataset_ctx, text_ctx, var_ref, data_var_map = await self._get_knowledge_context()

        # 获取Skill上下文（提示词 + 环境变量）
        skill_ctx, skill_envs = await self._get_skill_context()

        # 如果有SubTask，加载其描述
        current_task = ""
        if subtask_id:
            from app.models import SubTask
            from sqlalchemy import select
            result = await self.db.execute(
                select(SubTask).where(SubTask.id == subtask_id)
            )
            subtask = result.scalar_one_or_none()
            if subtask:
                current_task = f"**SubTask {subtask.order}: {subtask.title}**\n{subtask.description or ''}"
        
        system_prompt = ANALYST_SYSTEM_PROMPT.format(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
            skill_context=skill_ctx,
            current_task=current_task or "[Direct analysis mode]",
        )
        
        # 加载历史
        history = context.get("history_messages", [])
        
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_message},
        ]
        
        # 跨轮次持久化的中间变量 {var_name: json_file_path}
        persistent_vars: dict[str, str] = {}
        
        # 尝试从 persist/ 目录恢复之前对话轮次的变量
        persist_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures", "persist")
        if os.path.isdir(persist_dir):
            import glob
            for fpath in glob.glob(os.path.join(persist_dir, "*.json")):
                var_name = os.path.splitext(os.path.basename(fpath))[0]
                persistent_vars[var_name] = fpath
        
        # ReAct循环
        max_rounds = 10
        
        for round_idx in range(max_rounds):
            try:
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=ANALYST_TOOLS,  # type: ignore
                    tool_choice="auto",
                    stream=True,
                    temperature=0.4,
                )
            except Exception as e:
                yield self._sse({"type": "error", "content": f"LLM error: {str(e)}"})
                break
            
            text_content = ""
            tool_calls_acc: dict[int, dict[str, str]] = {}
            
            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue
                
                delta = choice.delta
                
                if delta.content:
                    token = delta.content
                    text_content += token
                    yield self._sse({"type": "text", "content": token})
                
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            tool_calls_acc[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_acc[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments
                
                if choice.finish_reason:
                    break
            
            # 处理tool calls
            if tool_calls_acc:
                from app.services.sandbox import execute_code_in_sandbox
                
                tool_calls_for_api = []
                for idx in sorted(tool_calls_acc.keys()):
                    tc = tool_calls_acc[idx]
                    tool_calls_for_api.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    })
                
                messages.append({
                    "role": "assistant",
                    "content": text_content or None,
                    "tool_calls": tool_calls_for_api,
                })  # type: ignore
                
                for idx in sorted(tool_calls_acc.keys()):
                    tc = tool_calls_acc[idx]
                    try:
                        args = json.loads(tc["arguments"])
                    except json.JSONDecodeError:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": "ERROR: Invalid arguments",
                        })  # type: ignore
                        continue
                    
                    if tc["name"] == "execute_python_code":
                        code = args.get("code", "")
                        purpose = args.get("purpose", "")
                        
                        yield self._sse({"type": "tool_start", "code": code, "purpose": purpose})
                        
                        capture_id = uuid.uuid4().hex[:12]
                        capture_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures")
                        os.makedirs(capture_dir, exist_ok=True)
                        
                        try:
                            # 使用心跳包装器执行代码
                            exec_result = None
                            async for item in self._execute_code_with_heartbeat(
                                code=code,
                                data_var_map=data_var_map,
                                capture_dir=capture_dir,
                                skill_envs=skill_envs if skill_envs else None,
                                persistent_vars=persistent_vars if persistent_vars else None,
                            ):
                                if isinstance(item, str):
                                    # 心跳事件，直接转发
                                    yield item
                                else:
                                    # 执行结果
                                    exec_result = item
                            
                            if exec_result is None:
                                exec_result = {
                                    "success": False,
                                    "output": None,
                                    "error": "Execution failed: no result returned",
                                    "execution_time": 0.0,
                                }
                        except Exception as e:
                            exec_result = {
                                "success": False,
                                "output": None,
                                "error": str(e),
                                "execution_time": 0.0,
                            }
                        
                        # 重命名捕获的DataFrame文件
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
                        # 收集本轮持久化的变量
                        new_persisted = exec_result.get("persisted_vars", {})
                        if new_persisted:
                            persistent_vars.update(new_persisted)
                        yield self._sse({
                            "type": "tool_result",
                            "success": exec_result["success"],
                            "output": exec_result.get("output"),
                            "error": exec_result.get("error"),
                            "time": exec_result.get("execution_time", 0),
                            "dataframes": captured_dfs,
                        })
                        
                        tool_output = exec_result.get("output") or "(no output)"
                        if not exec_result["success"]:
                            tool_output = f"ERROR: {exec_result.get('error', 'Unknown')}"
                        
                        if len(tool_output) > 8000:
                            tool_output = tool_output[:8000] + "\n[truncated]"
                        
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": tool_output,
                        })  # type: ignore
                
                continue
            
            # 纯文本 - 结束
            if text_content.strip():
                break
        
        yield self._sse({"type": "done"})