# backend/app/services/agents/plan_agent.py

"""PlanAgent - 负责需求澄清和任务分拆"""

from typing import AsyncGenerator, Any
import json
import uuid
from app.services.agents.base import BaseAgent
from openai.types.chat import ChatCompletionMessageParam

from app.prompts import build_plan_system_prompt
from app.tools import get_tools_for_agent


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
        import os
        import glob
        from app.config import UPLOADS_DIR

        user_message = context.get("user_message", "")
        history = context.get("history_messages", [])
        # 获取Knowledge上下文
        dataset_ctx, text_ctx, var_ref, data_var_map = await self._get_knowledge_context()

        conversation_turns = len([m for m in history if m["role"] in ("user", "assistant")])
        system_prompt = build_plan_system_prompt(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
            is_first_turn=(conversation_turns == 0),
            has_datasets=bool(data_var_map),
        )


        
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_message},
        ]
        
        # 跨轮次持久化的中间变量 {var_name: json_file_path}
        persistent_vars: dict[str, str] = {}
        
        # 从 persist/ 目录恢复之前对话轮次的变量
        persist_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures", "persist")
        if os.path.isdir(persist_dir):
            for fpath in glob.glob(os.path.join(persist_dir, "*.json")):
                var_name = os.path.splitext(os.path.basename(fpath))[0]
                persistent_vars[var_name] = fpath
        
        # 调用LLM（支持tool calling）
        max_rounds = 5  # Plan阶段限制轮次
        
        plan_tools = get_tools_for_agent("plan")
        for round_idx in range(max_rounds):
            try:
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=plan_tools if plan_tools else None,  # type: ignore
                    tool_choice="auto" if plan_tools else None, # type: ignore
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
                                skill_envs= None,
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

                        # ── 【新增】处理沙箱内 create_chart() 捕获的图表 ──
                        sandbox_charts = exec_result.get("charts", [])
                        for chart_meta in sandbox_charts:
                            chart_option = chart_meta.get("option", {})
                            from app.tools import validate_echarts_option
                            ok_chart, err_chart = validate_echarts_option(chart_option)
                            if ok_chart:
                                yield self._sse({
                                    "type": "visualization",
                                    "title": chart_meta.get("title", "Untitled Chart"),
                                    "chart_type": chart_meta.get("chart_type", "bar"),
                                    "option": chart_option,
                                })
                            else:
                                yield self._sse({
                                    "type": "error",
                                    "content": f"Chart validation failed: {err_chart}",
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
                    # ---------- Tool: create_visualization ----------
                    elif tc["name"] == "create_visualization":
                        from app.tools import (
                            validate_echarts_option,
                            normalize_echarts_option,
                            merge_top_level_keys,
                        )
                        title = str(args.get("title", "")).strip() or "Untitled Chart"
                        chart_type = str(args.get("chart_type", "")).strip() or "bar"
                        raw_option = args.get("option", {})
                        normalized_option, norm_err = normalize_echarts_option(raw_option)
                        if normalized_option is None:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": f"ERROR: Invalid ECharts option: {norm_err}",
                            })  # type: ignore
                            yield self._sse({"type": "error", "content": f"Visualization option invalid: {norm_err}"})
                            continue
                        normalized_option = merge_top_level_keys(normalized_option, args)
                        ok, err = validate_echarts_option(normalized_option)
                        if not ok:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": f"ERROR: Invalid ECharts option: {err}. "
                                           "Please use create_chart() inside execute_python_code instead.",
                            })  # type: ignore
                            yield self._sse({"type": "error", "content": f"Visualization option invalid: {err}"})
                            continue
                        yield self._sse({
                            "type": "visualization",
                            "title": title,
                            "chart_type": chart_type,
                            "option": normalized_option,
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": f"OK: visualization created. title={title!r}, chart_type={chart_type!r}",
                        })  # type: ignore
                    # ---------- Unknown tool ----------
                    else:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": f"ERROR: Unknown tool '{tc['name']}'",
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