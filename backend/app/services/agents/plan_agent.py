# backend/app/services/agents/plan_agent.py

"""PlanAgent - 负责需求澄清和任务分拆"""

from typing import AsyncGenerator, Any
import json
from app.services.agents.base import BaseAgent
from openai.types.chat import ChatCompletionMessageParam


PLAN_SYSTEM_PROMPT = """\
You are **Owl Planning Agent 🦉**, an expert at understanding data analysis requirements and breaking them down into actionable subtasks.

## Your Role
You help users clarify their analysis goals and create a structured plan. You MUST:

1. **Clarify Requirements** - Ask questions to understand:
   - Business context and objectives
   - Data definitions and field meanings
   - Relationships between datasets/tables
   - Expected output format

2. **Assess Data Availability** - Check if current datasets are sufficient. If not, ask users to provide additional data.

3. **Create Subtasks** - Break complex analysis into sequential steps:
   - Each subtask should be clear and focused
   - Subtasks should build on each other logically
   - Number subtasks in execution order (1, 2, 3...)

4. **Exploratory Analysis** - You CAN use `execute_python_code` to explore data during planning:
   - Check data quality and structure
   - Verify assumptions
   - Help clarify requirements
   But keep it lightweight - detailed analysis happens in execution phase.

## Output Format
When you're ready to propose a plan, output a JSON block like this:
```json
{{
"plan_ready": true,
"subtasks": [
 {{
 "order": 1,
 "title": "Data Quality Check",
 "description": "Verify data completeness and identify missing values"
 }},
 {{
 "order": 2,
 "title": "Exploratory Analysis",
 "description": "Calculate basic statistics and distributions"
 }}
]
}}


## Available Datasets
{dataset_context}

## Reference Documents
{text_context}

## Variable Reference
{variable_reference}

Answer in the **same language** the user uses.
"""

# Tool定义（与AnalystAgent相同）
PLAN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_python_code",
            "description": "Execute Python code for exploratory analysis during planning",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "purpose": {"type": "string", "description": "Why you're running this code"},
                },
                "required": ["code", "purpose"],
            },
        },
    }
]


class PlanAgent(BaseAgent):
    """Plan模式Agent - 需求澄清和任务分拆"""
    
    async def run(self, context: dict[str, Any]) -> AsyncGenerator[str, None]:
        """
        执行Plan流程：
        1. 与用户澄清需求
        2. 可选：执行探索性代码
        3. 生成SubTask列表
        4. 等待用户确认
        """
        user_message = context.get("user_message", "")
        
        # 获取Knowledge上下文
        dataset_ctx, text_ctx, var_ref, csv_var_map = await self._get_knowledge_context()
        
        system_prompt = PLAN_SYSTEM_PROMPT.format(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
        )
        
        # 加载历史消息
        history = context.get("history_messages", [])
        
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_message},
        ]
        
        # 调用LLM（支持tool calling）
        max_rounds = 5  # Plan阶段限制轮次
        
        for round_idx in range(max_rounds):
            try:
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=PLAN_TOOLS,  # type: ignore
                    tool_choice="auto",
                    stream=True,
                    temperature=0.3,
                )
            except Exception as e:
                yield self._sse({"type": "error", "content": f"LLM request failed: {str(e)}"})
                break
            
            text_content = ""
            tool_calls_acc: dict[int, dict[str, str]] = {}
            
            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue
                
                delta = choice.delta
                
                # 文本流
                if delta.content:
                    token = delta.content
                    text_content += token
                    yield self._sse({"type": "text", "content": token})
                
                # Tool call流
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
                # 执行代码（探索性分析）
                from app.services.sandbox import execute_code_in_sandbox
                import os
                from app.config import UPLOADS_DIR
                
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
                        
                        capture_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures")
                        os.makedirs(capture_dir, exist_ok=True)
                        
                        try:
                            exec_result = await execute_code_in_sandbox(
                                code=code,
                                csv_var_map=csv_var_map,
                                capture_dir=capture_dir,
                            )
                        except Exception as e:
                            exec_result = {
                                "success": False,
                                "output": None,
                                "error": str(e),
                                "execution_time": 0.0,
                            }
                        
                        yield self._sse({
                            "type": "tool_result",
                            "success": exec_result["success"],
                            "output": exec_result.get("output"),
                            "error": exec_result.get("error"),
                            "time": exec_result.get("execution_time", 0),
                        })
                        
                        tool_output = exec_result.get("output") or "(no output)"
                        if not exec_result["success"]:
                            tool_output = f"ERROR: {exec_result.get('error', 'Unknown')}"
                        
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": tool_output[:4000],  # 限制长度
                        })  # type: ignore
                
                continue  # 继续下一轮
            
            # 纯文本回复 - 检查是否包含Plan
            if text_content.strip():
                # 尝试解析JSON格式的Plan
                plan_data = self._extract_plan_json(text_content)
                if plan_data:
                    yield self._sse({
                        "type": "plan_generated",
                        "plan": plan_data,
                    })
                
                # 结束
                break
        
        yield self._sse({"type": "done"})
    
    def _extract_plan_json(self, text: str) -> dict | None:
        """从文本中提取JSON格式的Plan"""
        import re
        
        # 查找```json ... ```代码块
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                plan_data = json.loads(json_match.group(1))
                if plan_data.get("plan_ready") and "subtasks" in plan_data:
                    return plan_data
            except json.JSONDecodeError:
                pass
        
        return None
