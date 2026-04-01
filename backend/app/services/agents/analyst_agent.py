# backend/app/services/agents/analyst_agent.py

"""AnalystAgent - 负责执行具体分析任务"""

from typing import AsyncGenerator, Any
import json
import uuid
import os
from app.services.agents.base import BaseAgent
from openai.types.chat import ChatCompletionMessageParam
from app.config import UPLOADS_DIR
from app.prompts import build_analyst_system_prompt
from app.tools import (
    get_tools_for_agent,
    validate_echarts_option,
    normalize_echarts_option,
    merge_top_level_keys,
)
from app.tools.visualization import validate_map_config



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
        
        # 从 context 获取可视化示例开关（由 orchestrator 的 LLM 分类 或 关键词兜底决定）
        include_viz_examples = context.get("include_viz_examples", False)
        
        # 额外兜底：如果有数据集，也倾向于包含示例
        if not include_viz_examples and data_var_map:
            from app.prompts.fragments import needs_viz_examples
            include_viz_examples = needs_viz_examples(user_message, current_task)
        system_prompt = build_analyst_system_prompt(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
            skill_context=skill_ctx,
            current_task=current_task or "[Direct analysis mode]",
            include_viz_examples=include_viz_examples,
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
                agent_tools = get_tools_for_agent("analyst")
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=agent_tools if agent_tools else None,  # type: ignore
                    tool_choice="auto" if agent_tools else None, # type: ignore
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
                        # ── 处理沙箱内 create_chart() 捕获的图表 ──
                        sandbox_charts = exec_result.get("charts", [])
                        for chart_meta in sandbox_charts:
                            chart_option = chart_meta.get("option", {})
                            # 基础校验
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
                        # ── 【新增】处理沙箱内 create_map() 捕获的地图 ──
                        sandbox_maps = exec_result.get("maps", [])
                        for map_meta in sandbox_maps:
                            map_config = map_meta.get("config", {})
                            # 基础校验
                            ok, err = validate_map_config(map_config)
                            if not ok:
                                yield self._sse({
                                    "type": "error",
                                    "content": f"Map validation failed: {err}",
                                })
                                continue
                            yield self._sse({
                                "type": "visualization",
                                "title": map_meta.get("title", "Untitled Map"),
                                "chart_type": "map",
                                "option": map_config,
                            })
                        tool_output = exec_result.get("output") or "(no output)"
                        if not exec_result["success"]:
                            tool_output = f"ERROR: {exec_result.get('error', 'Unknown')}"
                        
                        if len(tool_output) > 8000:
                            tool_output = tool_output[:8000] + "\n[truncated]"

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": tool_output,
                            }  # type: ignore
                        )

                    # ---------- Tool: create_visualization ----------
                    elif tc["name"] == "create_visualization":
                        title = str(args.get("title", "")).strip() or "Untitled Chart"
                        chart_type = str(args.get("chart_type", "")).strip() or "bar"
                        raw_option = args.get("option", {})
                        normalized_option, norm_err = normalize_echarts_option(raw_option)
                        if normalized_option is None:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc["id"],
                                    "content": f"ERROR: Invalid ECharts option: {norm_err}",
                                }  # type: ignore
                            )
                            yield self._sse({"type": "error", "content": f"Visualization option invalid: {norm_err}"})
                            continue

                        # 兼容：LLM 可能把 series/xAxis/yAxis 等放在 tool args 顶层而非 option 内
                        for merge_key in ("series", "xAxis", "yAxis", "legend", "grid", "dataset", "tooltip", "title"):
                            if merge_key not in normalized_option and merge_key in args:
                                normalized_option[merge_key] = args[merge_key]

                        normalized_option = merge_top_level_keys(normalized_option, args)
                        ok, err = validate_echarts_option(normalized_option)
                        if not ok:
                            option_keys = list(normalized_option.keys()) if isinstance(normalized_option, dict) else []
                            err_detail = f"{err} (option_keys={option_keys}, args_keys={list(args.keys())})"
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc["id"],
                                    "content": f"ERROR: Invalid ECharts option: {err_detail}. "
                                               "Please use create_chart() inside execute_python_code instead.",
                                }  # type: ignore
                            )
                            yield self._sse({"type": "error", "content": f"Visualization option invalid: {err_detail}"})
                            continue
                        option = normalized_option

                        # 关键：这里不直接写 DB（因为 Agent 层不负责持久化），只产出 SSE 事件
                        # 后端 agent service 层（app/services/agent.py）会接管持久化
                        yield self._sse(
                            {
                                "type": "visualization",
                                "title": title,
                                "chart_type": chart_type,
                                "option": option,
                            }
                        )

                        # tool 回传给 LLM，告诉它已创建（后续它可以继续总结）
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": f"OK: visualization created. title={title!r}, chart_type={chart_type!r}",
                            }  # type: ignore
                        )

                        # messages.append({
                        #     "role": "tool",
                        #     "tool_call_id": tc["id"],
                        #     "content": tool_output,
                        # })  # type: ignore

                # 继续下一轮 ReAct                
                continue
            
            # 纯文本 - 结束
            if text_content.strip():
                break
        
        yield self._sse({"type": "done"})