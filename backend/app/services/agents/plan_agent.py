# backend/app/services/agents/plan_agent.py

"""PlanAgent - 负责需求澄清和任务分拆"""

from typing import AsyncGenerator, Any
import json
from app.services.agents.base import BaseAgent
from openai.types.chat import ChatCompletionMessageParam


PLAN_SYSTEM_PROMPT = """\
You are **Owl Planning Agent 🦉**, a careful analyst who helps users prepare for data analysis.

## Your Mission: Prepare, Don't Rush

You work in THREE PHASES. You MUST complete each phase before moving to the next.

### PHASE 1: Clarify Requirements (ALWAYS START HERE)
Before doing ANYTHING else, you must understand:
- What business question is the user trying to answer?
- What specific metrics or insights do they need?
- What is the expected output format? (chart, table, report, etc.)
- Are there any domain-specific terms that need clarification?

**Ask questions** until you have clear answers. Use `execute_python_code` to explore data if needed.

### PHASE 2: Assess Data Readiness
Once requirements are clear, check:
- Do we have all necessary datasets?
- Are the data fields sufficient for the analysis?
- Are there data quality issues? (missing values, inconsistencies, etc.)
- Do we need additional data sources?

**If data is insufficient**, tell the user EXACTLY what's missing and ask them to provide it.
**DO NOT proceed to planning** if critical data is missing.

### PHASE 3: Create Analysis Plan (ONLY WHEN READY)
You can ONLY generate a plan when BOTH conditions are met:
1. ✅ Requirements are crystal clear
2. ✅ All necessary data is available

**CRITICAL RULES**:
- NEVER generate a plan in your first response
- NEVER skip Phase 1 and Phase 2
- If the user pushes you to plan prematurely, politely explain what information is still needed
- If you're unsure about data sufficiency, ASK rather than assume

### Plan Output Format (ONLY use when ready)
When you're truly ready to propose a plan, output:
```json
{{
"plan_ready": true,
"confidence": "high", // or "medium" if you have concerns
"prerequisites_met": {{
 "requirements_clear": true,
 "data_sufficient": true
}},
"subtasks": [
 {{
 "order": 1,
 "title": "...",
 "description": "..."
 }}
]
}}


## Available Datasets
{dataset_context}

## Reference Documents
{text_context}

## Variable Reference
{variable_reference}

**Remember**: A good plan is built on solid understanding. Take your time.

# Exceptions:
If the user explicitly says "just start" or "skip clarification", you may proceed to planning,
but you should still note any assumptions you're making.
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
        history = context.get("history_messages", [])
        # 获取Knowledge上下文
        dataset_ctx, text_ctx, var_ref, csv_var_map = await self._get_knowledge_context()
        
        system_prompt = PLAN_SYSTEM_PROMPT.format(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
        )

        # 🆕 计算对话轮次（排除system消息）
        conversation_turns = len([m for m in history if m["role"] in ("user", "assistant")])
        
        # 🆕 如果是第一轮对话，添加额外提醒
        if conversation_turns == 0:
            first_turn_reminder = (
                "\n\n**IMPORTANT**: This is your FIRST interaction with the user. "
                "You MUST start by asking clarifying questions. "
                "DO NOT generate a plan in this response."
            )
            system_prompt += first_turn_reminder
            

        
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
            
            # 在处理纯文本回复时，检查是否包含Plan JSON
            if text_content.strip():
                plan_data = self._extract_plan_json(text_content)
                
                if plan_data:
                    # 🆕 检查是否是错误（被拦截的Plan）
                    if plan_data.get("error") == "premature_plan":
                        # 发送警告给模型，要求重新思考
                        yield self._sse({
                            "type": "text",
                            "content": f"\n\n⚠️ {plan_data['message']}\n\n",
                        })
                        
                        # 将警告注入到messages中，让模型重新回答
                        messages.append({
                            "role": "assistant",
                            "content": text_content,
                        })
                        messages.append({
                            "role": "user",
                            "content": (
                                f"⚠️ System Warning: {plan_data['message']}\n\n"
                                "Please continue the conversation to address this issue before generating a plan."
                            ),
                        })
                        
                        # 继续下一轮对话
                        continue
                    
                    # 正常的Plan
                    yield self._sse({
                        "type": "plan_generated",
                        "plan": plan_data,
                    })
                
                break        

        yield self._sse({"type": "done"})
    
    def _extract_plan_json(self, text: str) -> dict | None:
        """从文本中提取并验证JSON格式的Plan"""
        import re
        
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                plan_data = json.loads(json_match.group(1))
                
                # 基本格式检查
                if not plan_data.get("plan_ready") or "subtasks" not in plan_data:
                    return None
                
                # 🆕 验证前置条件
                prerequisites = plan_data.get("prerequisites_met", {})
                
                if not prerequisites.get("requirements_clear"):
                    # 拦截：需求未澄清
                    return {
                        "error": "premature_plan",
                        "message": "Requirements are not yet clear. Please continue clarifying with the user.",
                    }
                
                if not prerequisites.get("data_sufficient"):
                    # 拦截：数据不足
                    return {
                        "error": "premature_plan", 
                        "message": "Data availability has not been confirmed. Please assess data readiness first.",
                    }
                
                # 🆕 检查是否是第一轮对话（防止直接生成Plan）
                # 这个需要从context传入对话轮次
                
                return plan_data
                
            except json.JSONDecodeError:
                pass
        
        return None