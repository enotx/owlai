# backend/app/services/agents/analyst_agent.py

"""AnalystAgent - 负责执行具体分析任务"""

from datetime import datetime
from typing import AsyncGenerator, Any
import json
import uuid
import os
import re
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

import logging
logger = logging.getLogger(__name__)



class AnalystAgent(BaseAgent):
    """Analyst模式Agent - 执行具体分析"""
    
    async def run(self, context: dict[str, Any]) -> AsyncGenerator[str, None]:
        """
        执行分析任务：
        1. 读取SubTask描述（如果有）
        2. 执行数据分析
        3. 记录Step到数据库
        """

        # ── NEW: Custom handler 路由（优先于标准流程） ──
        handler_type = context.get("invoked_skill_handler_type")
        if handler_type == "custom_handler":
            handler_config = context.get("invoked_skill_handler_config", {})
            handler_name = handler_config.get("handler_name")
            
            if handler_name == "derive_pipeline":
                async for chunk in self._handle_derive_pipeline(context, handler_config):
                    yield chunk
                return
            elif handler_name == "extract_script":
                async for chunk in self._handle_extract_script(context, handler_config):
                    yield chunk
                return
            elif handler_name == "extract_sop":
                async for chunk in self._handle_extract_sop(context, handler_config):
                    yield chunk
                return
            else:
                yield self._sse({
                    "type": "error",
                    "content": f"Unknown custom handler: {handler_name}",
                })
                yield self._sse({"type": "done"})
                return
        
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

        # 获取 DuckDB 仓库上下文
        warehouse_context = await self._build_warehouse_context()

        # ── 处理 slash command 显式指定的 skill ──────────────
        invoked_skill_name = context.get("invoked_skill_name")
        if invoked_skill_name:
            invoked_prompt = context.get("invoked_skill_prompt", "")
            is_active = context.get("invoked_skill_is_active", False)
            # 构建强调段落 — 让 LLM 明确知道用户想用哪个 skill
            emphasized_section = (
                f"## ⚡ User-Invoked Skill: {invoked_skill_name}\n"
                f"**The user has explicitly requested to use this skill. "
                f"Prioritize its instructions and capabilities for this task.**\n\n"
                f"{invoked_prompt}"
            )
            if is_active:
                # skill 已经在 _get_skill_context() 的结果中 → 去重
                # 从 skill_ctx 中移除该 skill 的普通段落，用强调版替代
                if skill_ctx and skill_ctx != "[No skills configured.]":
                    # 按 "---" 分割各 skill 段落，移除匹配的那一段
                    sections = skill_ctx.split("\n---\n")
                    filtered = [
                        s for s in sections
                        if f"### 🔧 Skill: {invoked_skill_name}" not in s
                    ]
                    other_skills = "\n---\n".join(filtered) if filtered else ""
                    # 强调版在前，其他 active skills 在后
                    if other_skills and other_skills.strip():
                        skill_ctx = emphasized_section + "\n---\n" + other_skills
                    else:
                        skill_ctx = emphasized_section
                else:
                    skill_ctx = emphasized_section
            else:
                # skill 是 inactive → 不在 _get_skill_context() 结果中，直接追加
                if skill_ctx and skill_ctx != "[No skills configured.]":
                    skill_ctx = emphasized_section + "\n---\n" + skill_ctx
                else:
                    skill_ctx = emphasized_section

        system_prompt = build_analyst_system_prompt(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
            skill_context=skill_ctx,
            current_task=current_task or "[Direct analysis mode]",
            include_viz_examples=include_viz_examples,
            warehouse_context=warehouse_context,
        )
        
        # 加载历史
        history = context.get("history_messages", [])
        
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_message},
        ]
        
        # 跨轮次持久化的中间变量 {var_name: .parquet/.json path}
        persistent_vars: dict[str, str] = {}
        
        # 尝试从 persist/ 目录恢复之前对话轮次的变量
        # .parquet 优先于 .json（同名变量取 parquet 版本）
        persist_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures", "persist")
        if os.path.isdir(persist_dir):
            import glob
            for fpath in glob.glob(os.path.join(persist_dir, "*.json")):
                var_name = os.path.splitext(os.path.basename(fpath))[0]
                persistent_vars[var_name] = fpath
            # Parquet 后扫描，覆盖同名 JSON（升级过渡期可能共存）
            for fpath in glob.glob(os.path.join(persist_dir, "*.parquet")):
                var_name = os.path.splitext(os.path.basename(fpath))[0]
                persistent_vars[var_name] = fpath
        
        # ReAct循环
        max_rounds = 10
        
        hitl_break = False
        for round_idx in range(max_rounds):
            if hitl_break:
                break
            try:
                agent_tools = get_tools_for_agent("analyst")
                # print('Agent Messages:', messages)  # 调试输出当前消息列表
                # print('Agent Tools:', [t for t in agent_tools])  # 调试输出工具列表
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

                            # ── 合并 extra_skill_envs（来自 slash command 调用） ──
                            effective_skill_envs = dict(skill_envs) if skill_envs else {}
                            extra_envs_from_ctx = context.get("extra_skill_envs")
                            invoked_is_active = context.get("invoked_skill_is_active", False)
                            # 仅当 skill 是 inactive 时才需要额外注入 env vars
                            # （active skill 的 env vars 已经在 _get_skill_context → skill_envs 中）
                            if extra_envs_from_ctx and not invoked_is_active:
                                # 特殊处理 __allowed_modules__（需要合并而非覆盖）
                                if "__allowed_modules__" in extra_envs_from_ctx and "__allowed_modules__" in effective_skill_envs:
                                    import json as _j
                                    existing_m = set(_j.loads(effective_skill_envs["__allowed_modules__"]))
                                    new_m = set(_j.loads(extra_envs_from_ctx["__allowed_modules__"]))
                                    effective_skill_envs["__allowed_modules__"] = _j.dumps(list(existing_m | new_m))
                                    # 其他环境变量直接更新
                                    extra_envs_clean = {k: v for k, v in extra_envs_from_ctx.items() if k != "__allowed_modules__"}
                                    effective_skill_envs.update(extra_envs_clean)
                                else:
                                    effective_skill_envs.update(extra_envs_from_ctx)

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
                    # ---------- Tool: get_skill_reference ----------
                    elif tc["name"] == "get_skill_reference":
                        skill_name = args.get("skill_name", "")
                        ref_content = await self._lookup_skill_reference(skill_name)
                        # 截断保护
                        if len(ref_content) > 12000:
                            ref_content = ref_content[:12000] + "\n\n[... reference truncated]"
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": ref_content,
                        })  # type: ignore

                    # ---------- Tool: materialize_to_duckdb ----------
                    elif tc["name"] == "materialize_to_duckdb":
                        result_content = await self._handle_materialize_to_duckdb(
                            args=args,
                            persistent_vars=persistent_vars,
                            capture_dir=os.path.join(UPLOADS_DIR, self.task_id, "captures"),
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_content,
                        })  # type: ignore

                    # ---------- Tool: list_duckdb_tables ----------
                    elif tc["name"] == "list_duckdb_tables":
                        result_content = await self._handle_list_duckdb_tables()
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_content,
                        })  # type: ignore

                    # ---------- Tool: request_human_input (HITL) ----------
                    elif tc["name"] == "request_human_input":
                        hitl_event, tool_content = self._handle_hitl_request(args)
                        yield hitl_event
                        
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": tool_content,
                        })  # type: ignore
                        
                        # Break inner loop (stop processing remaining tool calls)
                        # and signal outer loop to stop
                        hitl_break = True
                        break

                # 如果 HITL 中断，停止 ReAct 循环
                if hitl_break:
                    break
                # 继续下一轮 ReAct                
                continue
            
            # 纯文本 - 结束
            if text_content.strip():
                break
        
        yield self._sse({"type": "done"})

    async def _handle_materialize_to_duckdb(
        self,
        args: dict,
        persistent_vars: dict[str, str],
        capture_dir: str,
    ) -> str:
        """
        处理 materialize_to_duckdb 工具调用。
        从 persist/ 目录读取 DataFrame，写入 DuckDB，注册元数据。
        """
        import pandas as pd
        import pyarrow.parquet as pq
        from app.services import warehouse as wh
        from app.models import DuckDBTable
        from app.database import async_session
        from sqlalchemy import select

        var_name = args.get("dataframe_variable", "")
        table_name = args.get("table_name", "")
        display_name = args.get("display_name", table_name)
        description = args.get("description", "")
        strategy = args.get("write_strategy", "replace")
        upsert_key = args.get("upsert_key")
        source_type = args.get("source_type", "unknown")
        source_config = args.get("source_config")

        # 1. 验证表名
        valid, err = wh.validate_table_name(table_name)
        if not valid:
            return f"ERROR: {err}"

        # 2. 从 persist/ 目录找到 DataFrame
        persist_dir = os.path.join(capture_dir, "persist")
        df = None

        # 优先查找 parquet
        parquet_path = os.path.join(persist_dir, f"{var_name}.parquet")
        json_path = os.path.join(persist_dir, f"{var_name}.json")

        if os.path.exists(parquet_path):
            try:
                table = pq.read_table(parquet_path)
                meta = table.schema.metadata or {}
                # 不能物化 Series，只能物化 DataFrame
                if meta.get(b"__persist_type__") == b"series":
                    return (
                        f"ERROR: '{var_name}' is a Series, not a DataFrame. "
                        "Convert it to DataFrame first: df = series.to_frame()"
                    )
                df = table.to_pandas()
            except Exception as e:
                return f"ERROR: Failed to read '{var_name}' from persist: {str(e)}"

        elif os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    blob = json.load(f)
                ptype = blob.get("__persist_type__")
                if ptype not in (None, "dataframe"):
                    return (
                        f"ERROR: '{var_name}' is type '{ptype}', not a DataFrame. "
                        "Only DataFrames can be materialized to DuckDB."
                    )
                cols = blob.get("columns", [])
                rows = blob.get("rows", [])
                df = pd.DataFrame(rows, columns=cols) if cols else pd.DataFrame(rows)
            except Exception as e:
                return f"ERROR: Failed to read '{var_name}' from persist: {str(e)}"

        # 也在 persistent_vars 映射中查找
        elif var_name in persistent_vars:
            fpath = persistent_vars[var_name]
            try:
                if fpath.endswith(".parquet"):
                    table = pq.read_table(fpath)
                    df = table.to_pandas()
                else:
                    with open(fpath, "r", encoding="utf-8") as f:
                        blob = json.load(f)
                    cols = blob.get("columns", [])
                    rows = blob.get("rows", [])
                    df = pd.DataFrame(rows, columns=cols) if cols else pd.DataFrame(rows)
            except Exception as e:
                return f"ERROR: Failed to read '{var_name}': {str(e)}"

        if df is None:
            available = list(persistent_vars.keys()) if persistent_vars else []
            # 也扫描 persist/ 目录
            if os.path.isdir(persist_dir):
                import glob
                for fp in glob.glob(os.path.join(persist_dir, "*.parquet")):
                    n = os.path.splitext(os.path.basename(fp))[0]
                    if n not in available:
                        available.append(n)
                for fp in glob.glob(os.path.join(persist_dir, "*.json")):
                    n = os.path.splitext(os.path.basename(fp))[0]
                    if n not in available:
                        available.append(n)
            return (
                f"ERROR: DataFrame variable '{var_name}' not found in sandbox. "
                f"Available variables: {available}. "
                "Make sure you created this variable in a previous execute_python_code call."
            )

        if df.empty:
            return "ERROR: DataFrame is empty (0 rows). Nothing to materialize."

        # 3. 写入 DuckDB
        try:
            result = await wh.async_write_dataframe(df, table_name, strategy, upsert_key)
        except Exception as e:
            return f"ERROR: DuckDB write failed: {str(e)}"

        # 4. 注册/更新元数据到 SQLite
        try:
            async with async_session() as meta_db:
                existing = await meta_db.execute(
                    select(DuckDBTable).where(DuckDBTable.table_name == table_name)
                )
                table_meta = existing.scalar_one_or_none()

                table_schema_json = json.dumps(result["schema"], ensure_ascii=False)
                now = datetime.now()

                if table_meta:
                    table_meta.display_name = display_name
                    table_meta.description = description
                    table_meta.table_schema_json = table_schema_json
                    table_meta.row_count = result["total_rows"]
                    table_meta.source_type = source_type
                    table_meta.source_config = source_config
                    table_meta.data_updated_at = now
                    table_meta.status = "ready"
                else:
                    table_meta = DuckDBTable(
                        table_name=table_name,
                        display_name=display_name,
                        description=description,
                        table_schema_json=table_schema_json,
                        row_count=result["total_rows"],
                        source_type=source_type,
                        source_config=source_config,
                        data_updated_at=now,
                        status="ready",
                    )
                    meta_db.add(table_meta)

                await meta_db.commit()
        except Exception as e:
            # 写入 DuckDB 成功但元数据注册失败 — 不致命，只打日志
            import logging
            logging.getLogger(__name__).error(f"DuckDB metadata registration failed: {e}")

        # 5. 返回成功信息
        col_info = ", ".join(f"{s['name']} ({s['type']})" for s in result["schema"][:10])
        if len(result["schema"]) > 10:
            col_info += f", ... ({len(result['schema'])} total)"

        return (
            f"Successfully materialized {result['rows_written']:,} rows into "
            f"DuckDB table '{table_name}' (strategy: {strategy}).\n"
            f"Total rows in table: {result['total_rows']:,}\n"
            f"Columns: {col_info}\n\n"
            f"The table is now registered as a data asset and can be queried in future tasks."
        )

    async def _handle_list_duckdb_tables(self) -> str:
        """处理 list_duckdb_tables 工具调用"""
        from app.services import warehouse as wh

        try:
            tables = await wh.async_list_tables()
        except Exception as e:
            return f"ERROR: Failed to list tables: {str(e)}"

        if not tables:
            return "No tables found in the local DuckDB warehouse. The warehouse is empty."

        lines = ["Tables in local DuckDB warehouse:\n"]
        for t in tables:
            col_info = ", ".join(f"{s['name']} ({s['type']})" for s in t["schema"][:8])
            if len(t["schema"]) > 8:
                col_info += f", ... ({len(t['schema'])} total)"
            lines.append(
                f"- **{t['table_name']}** ({t['row_count']:,} rows)\n"
                f"  Columns: {col_info}"
            )
        return "\n".join(lines)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Custom Handler: Derive Pipeline
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _handle_derive_pipeline(
        self, context: dict, handler_config: dict
    ) -> AsyncGenerator[str, None]:
        """Custom handler for /derive command"""
        user_instructions = context.get("user_message", "")
        
        # Check if this is a confirmation message
        confirm_match = re.match(r"^\[(Derive|Pipeline)\s+Confirm\]\s*(\{.*\})", user_instructions.strip(), re.DOTALL)
        if confirm_match:
            try:
                config = json.loads(confirm_match.group(2))
            except json.JSONDecodeError:
                yield self._sse({"type": "error", "content": "Invalid derive confirmation payload."})
                yield self._sse({"type": "done"})
                return
            
            if config.get("cancelled"):
                tbl = config.get("table_name", "")
                if tbl:
                    try:
                        from app.services import warehouse as wh
                        await wh.async_drop_table(tbl)
                    except Exception:
                        pass
                yield self._sse({"type": "text", "content": "Derive cancelled. No data was saved."})
                yield self._sse({"type": "done"})
                return
            
            async for chunk in self._register_derive_metadata(config):
                yield chunk
            return
        
        # ── Main derive flow ──
        yield self._sse({"type": "text", "content": "🔍 Analyzing task history to extract a data pipeline...\n"})

        code_history = await self._collect_code_history()
        if not code_history:
            yield self._sse({
                "type": "text",
                "content": (
                    "⚠️ No successful code executions found in this task. "
                    "Please run some analysis first, then use `/derive` to save the result."
                ),
            })
            yield self._sse({"type": "done"})
            return

        knowledge_ctx = await self._gather_knowledge_summary()

        max_react_rounds = handler_config.get("max_react_rounds", 3)
        last_error: str | None = None
        derive_result: dict | None = None
        final_code: str | None = None
        pipeline_proposal: dict | None = None

        for attempt in range(max_react_rounds):
            round_label = f"(attempt {attempt + 1}/{max_react_rounds})"

            if attempt == 0:
                yield self._sse({"type": "text", "content": f"📝 Generating pipeline code {round_label}...\n"})
            else:
                yield self._sse({
                    "type": "text",
                    "content": (
                        f"🔄 Previous attempt failed. Retrying {round_label}...\n"
                        f"Error was: `{last_error[:200] if last_error else 'unknown'}`\n"
                    ),
                })

            pipeline_proposal = None
            async for item in self._extract_pipeline_with_llm_heartbeat(
                code_history, user_instructions, knowledge_ctx, context, last_error
            ):
                if isinstance(item, str):
                    yield item  # 心跳转发
                else:
                    pipeline_proposal = item
            if pipeline_proposal is None:
                yield self._sse({
                    "type": "text",
                    "content": "⚠️ Failed to extract a pipeline from the task history."
                })
                yield self._sse({"type": "done"})
                return

            transform_code = pipeline_proposal.get("transform_code", "")
            final_code = transform_code

            yield self._sse({
                "type": "tool_start",
                "code": transform_code,
                "purpose": f"Pipeline execution {round_label}",
            })

            exec_result = None
            async for item in self._execute_derive_code_with_heartbeat(transform_code):
                if isinstance(item, str):
                    yield item  # 心跳转发
                else:
                    exec_result = item

            if exec_result is None:
                last_error = "Sandbox execution returned no result"
                yield self._sse({"type": "tool_result", "success": False, "output": None, "error": last_error, "time": 0})
                continue

            yield self._sse({
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
            derive_result = self._parse_derive_marker(output_text)

            if derive_result is None:
                last_error = "Code executed successfully but did not print the __DERIVE_OK__ marker."
                continue

            break

        if derive_result is None:
            yield self._sse({
                "type": "text",
                "content": (
                    f"❌ Pipeline extraction failed after {max_react_rounds} attempts.\n\n"
                    f"Last error: `{last_error[:300] if last_error else 'unknown'}`\n\n"
                    "Please fix the analysis in chat and try `/derive` again."
                ),
            })
            yield self._sse({"type": "done"})
            return

        if pipeline_proposal is None:
            yield self._sse({
                "type": "text",
                "content": "❌ Pipeline extraction finished without a valid proposal. Please try `/derive` again.",
            })
            yield self._sse({"type": "done"})
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

            yield self._sse({
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
            async for chunk in self._register_derive_metadata(config):
                yield chunk
            return
        
        yield self._sse({"type": "done"})

    # ── Helper methods for derive pipeline ──

    async def _collect_code_history(self) -> list[dict]:
        """回溯 Task 历史，收集成功的 tool_use Steps"""
        from app.models import Step
        from sqlalchemy import select

        result = await self.db.execute(
            select(Step).where(Step.task_id == self.task_id, Step.step_type == "tool_use").order_by(Step.created_at.asc())
        )
        steps = list(result.scalars().all())

        history = []
        for step in steps:
            if not step.code or not step.code_output:
                continue
            try:
                output_data = json.loads(step.code_output)
            except json.JSONDecodeError:
                continue
            if not output_data.get("success"):
                continue

            history.append({
                "code": step.code,
                "output": output_data.get("output", "")[:2000],
                "purpose": step.content or "",
            })

        return history

    async def _gather_knowledge_summary(self) -> str:
        """收集当前 Task 的 Knowledge 摘要"""
        from app.models import Knowledge
        from sqlalchemy import select

        knowledge_ctx = ""
        try:
            result = await self.db.execute(select(Knowledge).where(Knowledge.task_id == self.task_id))
            items = list(result.scalars().all())
            if items:
                parts = [f"- {k.name} (type: {k.type})" for k in items]
                knowledge_ctx = "Available data:\n" + "\n".join(parts)
        except Exception:
            pass
        return knowledge_ctx

    async def _extract_pipeline_with_llm(
        self,
        code_history: list[dict],
        user_instructions: str,
        knowledge_context: str,
        context: dict,
        previous_error: str | None = None,
    ) -> dict | None:
        """使用 LLM 从代码历史中提取 pipeline 定义（从 skill prompt 读取）"""
        
        # ── 从 skill 获取 prompt（而不是从独立文件） ──
        system_prompt = context.get("invoked_skill_prompt", "")
        if not system_prompt:
            logger.error("Derive skill prompt_markdown is empty")
            return None

        # ── 构建 user prompt ──
        user_prompt = self._build_pipeline_user_prompt(code_history, user_instructions, knowledge_context)

        if previous_error:
            user_prompt += (
                f"\n\n## ⚠️ Previous Attempt Failed\n"
                f"```\n{previous_error[:1000]}\n```\n\n"
                f"Fix the code and try again."
            )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
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

    async def _extract_pipeline_with_llm_heartbeat(
        self,
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
            r = await self._extract_pipeline_with_llm(
                code_history, user_instructions, knowledge_context,
                context, previous_error,
            )
            result_holder.append(r)
            done_event.set()
        task = asyncio.create_task(_do_extract())
        while not done_event.is_set():
            try:
                await asyncio.wait_for(asyncio.shield(done_event.wait()), timeout=15.0)
            except asyncio.TimeoutError:
                yield self._sse({"type": "heartbeat", "content": "llm_thinking"})
        # 检查任务异常
        if task.done() and task.exception():
            logger.error(f"Pipeline extraction task failed: {task.exception()}")
            yield None
            return
        yield result_holder[0] if result_holder else None

    def _build_pipeline_user_prompt(
        self,
        code_history: list[dict],
        user_instructions: str,
        knowledge_context: str,
    ) -> str:
        """构建 pipeline 提取的 user prompt（纯数据组装）"""
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

    async def _execute_derive_code(self, transform_code: str) -> dict | None:
        """在沙箱中执行 derive 代码"""
        from app.services.sandbox import execute_code_in_sandbox
        from app.services.data_processor import sanitize_variable_name
        from app.models import Knowledge
        from app.config import UPLOADS_DIR
        from sqlalchemy import select

        data_var_map: dict[str, str] = {}
        result = await self.db.execute(select(Knowledge).where(Knowledge.task_id == self.task_id))
        for k in result.scalars().all():
            if k.type in ("csv", "excel") and k.file_path and os.path.exists(k.file_path):
                var_name = sanitize_variable_name(k.name)
                data_var_map[var_name] = os.path.abspath(k.file_path)

        capture_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures", "derive_exec")
        os.makedirs(capture_dir, exist_ok=True)

        persist_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures", "persist")
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

        from sqlalchemy import select as sa_select
        from app.models import Skill
        skill_result = await self.db.execute(sa_select(Skill).where(Skill.is_active == True))
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

        try:
            exec_result = await execute_code_in_sandbox(
                code=transform_code,
                data_var_map=data_var_map,
                timeout=300,
                capture_dir=capture_dir,
                injected_envs=skill_envs if skill_envs else None,
                persisted_var_map=persisted_var_map if persisted_var_map else None,
            )
            return exec_result
        except Exception as e:
            logger.error(f"Derive code sandbox error: {e}")
            return {"success": False, "output": None, "error": str(e), "execution_time": 0.0}

    async def _execute_derive_code_with_heartbeat(
        self, transform_code: str
    ) -> AsyncGenerator[str | dict, None]:
        """带心跳的 derive 代码执行，复用 base._execute_code_with_heartbeat"""
        from app.services.data_processor import sanitize_variable_name
        from app.models import Knowledge, Skill
        from sqlalchemy import select

        # ── 准备 data_var_map ──
        data_var_map: dict[str, str] = {}
        result = await self.db.execute(
            select(Knowledge).where(Knowledge.task_id == self.task_id)
        )
        for k in result.scalars().all():
            if k.type in ("csv", "excel") and k.file_path and os.path.exists(k.file_path):
                var_name = sanitize_variable_name(k.name)
                data_var_map[var_name] = os.path.abspath(k.file_path)

        capture_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures", "derive_exec")
        os.makedirs(capture_dir, exist_ok=True)

        # ── 准备 persistent_vars ──
        persist_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures", "persist")
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

        # ── 准备 skill_envs ──
        skill_result = await self.db.execute(select(Skill).where(Skill.is_active == True))
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

        # ── 复用 base 的心跳包装器 ──
        async for item in self._execute_code_with_heartbeat(
            code=transform_code,
            data_var_map=data_var_map,
            capture_dir=capture_dir,
            skill_envs=skill_envs if skill_envs else None,
            persistent_vars=persisted_var_map if persisted_var_map else None,
        ):
            yield item

    def _parse_derive_marker(self, output: str) -> dict | None:
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

    async def _register_derive_metadata(self, config: dict) -> AsyncGenerator[str, None]:
        """用户确认后，注册元数据到 SQLite"""
        from app.models import DuckDBTable, DataPipeline
        from app.database import async_session
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
            yield self._sse({"type": "error", "content": "Invalid confirmation: missing table_name."})
            yield self._sse({"type": "done"})
            return

        exists = await wh.async_table_exists(table_name)
        if not exists:
            yield self._sse({
                "type": "error",
                "content": f"Table `{table_name}` not found in DuckDB. Please try `/derive` again."
            })
            yield self._sse({"type": "done"})
            return

        yield self._sse({"type": "text", "content": f"📋 Registering `{table_name}` as a data asset...\n"})

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
                    source_task_id=self.task_id,
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

        yield self._sse({"type": "text", "content": success_msg})
        yield self._sse({"type": "done"})

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Custom Handler: Extract SOP
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    async def _handle_extract_sop(
        self, context: dict, handler_config: dict
    ) -> AsyncGenerator[str, None]:
        """Custom handler for /sop command"""
        user_instructions = context.get("user_message", "")
        
        yield self._sse({"type": "text", "content": "📋 Analyzing task history to extract SOP...\n"})

        code_history = await self._collect_code_history()
        if not code_history:
            yield self._sse({
                "type": "text",
                "content": "⚠️ No code execution history found. Please complete some analysis first."
            })
            yield self._sse({"type": "done"})
            return

        knowledge_ctx = await self._gather_knowledge_summary()
        
        # ── 从 skill 获取 system prompt（而不是硬编码） ──
        system_prompt = context.get("invoked_skill_prompt", "")
        if not system_prompt:
            # Fallback to a basic prompt if skill prompt is empty
            system_prompt = "You are an expert at documenting data analysis procedures."
        
        # ── 构建 user prompt（纯数据组装） ──
        user_prompt = self._build_sop_extraction_prompt(
            code_history, user_instructions, knowledge_ctx
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=8192,
            )

            sop_content = (response.choices[0].message.content or "").strip()

            yield self._sse({"type": "text", "content": "\n\n---\n\n" + sop_content + "\n\n---\n\n"})
            yield self._sse({
                "type": "text",
                "content": "💡 **Tip**: You can save this SOP as a text file in the Knowledge section for future reference."
            })

        except Exception as e:
            logger.error(f"SOP extraction failed: {e}")
            yield self._sse({"type": "error", "content": f"Failed to generate SOP: {str(e)}"})

        yield self._sse({"type": "done"})

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Custom Handler: Extract Script
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    async def _handle_extract_script(
        self, context: dict, handler_config: dict
    ) -> AsyncGenerator[str, None]:
        """Custom handler for /script command — extract reusable script from task history"""
        user_instructions = context.get("user_message", "")
        # ── Check if this is a confirmation message ──
        confirm_match = re.match(
            r"^\[Script\s+Confirm\]\s*(\{.*\})", user_instructions.strip(), re.DOTALL
        )
        if confirm_match:
            try:
                config = json.loads(confirm_match.group(1))
            except json.JSONDecodeError:
                yield self._sse({"type": "error", "content": "Invalid script confirmation payload."})
                yield self._sse({"type": "done"})
                return
            if config.get("cancelled"):
                yield self._sse({"type": "text", "content": "Script extraction cancelled."})
                yield self._sse({"type": "done"})
                return
            async for chunk in self._save_script_asset(config):
                yield chunk
            return
        
        # ── Main extraction flow ──
        yield self._sse({"type": "text", "content": "📝 Analyzing task history to extract a reusable script...\n"})
        code_history = await self._collect_code_history()
        if not code_history:
            yield self._sse({
                "type": "text",
                "content": (
                    "⚠️ No successful code executions found in this task. "
                    "Please run some analysis first, then use `/script` to save it."
                ),
            })
            yield self._sse({"type": "done"})
            return
        knowledge_ctx = await self._gather_knowledge_summary()
        system_prompt = context.get("invoked_skill_prompt", "")
        if not system_prompt:
            logger.error("Extract Script skill prompt_markdown is empty")
            yield self._sse({"type": "error", "content": "Script extraction skill is misconfigured."})
            yield self._sse({"type": "done"})
            return
        max_react_rounds = handler_config.get("max_react_rounds", 3)
        last_error: str | None = None
        proposal: dict | None = None
        validated_code: str | None = None
        for attempt in range(max_react_rounds):
            round_label = f"(attempt {attempt + 1}/{max_react_rounds})"
            if attempt == 0:
                yield self._sse({"type": "text", "content": f"🔧 Generating script {round_label}...\n"})
            else:
                yield self._sse({
                    "type": "text",
                    "content": (
                        f"🔄 Previous attempt failed. Retrying {round_label}...\n"
                        f"Error: `{last_error[:200] if last_error else 'unknown'}`\n"
                    ),
                })
            # ── LLM extraction (with heartbeat) ──
            proposal = None
            async for item in self._extract_script_with_llm_heartbeat(
                code_history, user_instructions, knowledge_ctx,
                system_prompt, last_error,
            ):
                if isinstance(item, str):
                    yield item  # heartbeat
                else:
                    proposal = item
            if proposal is None:
                yield self._sse({
                    "type": "text",
                    "content": "⚠️ Failed to extract script from the task history.",
                })
                yield self._sse({"type": "done"})
                return
            code = proposal.get("code", "")
            if not code.strip():
                last_error = "LLM returned empty code"
                continue
            # ── Sandbox validation ──
            yield self._sse({
                "type": "tool_start",
                "code": code,
                "purpose": f"Script validation {round_label}",
            })
            exec_result = None
            async for item in self._execute_script_validation_with_heartbeat(code, context):
                if isinstance(item, str):
                    yield item
                else:
                    exec_result = item
            if exec_result is None:
                last_error = "Sandbox returned no result"
                yield self._sse({"type": "tool_result", "success": False, "output": None, "error": last_error, "time": 0})
                continue
            yield self._sse({
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
            yield self._sse({
                "type": "text",
                "content": (
                    f"❌ Script extraction failed after {max_react_rounds} attempts.\n\n"
                    f"Last error: `{last_error[:300] if last_error else 'unknown'}`\n\n"
                    "Please fix the analysis and try `/script` again."
                ),
            })
            yield self._sse({"type": "done"})
            return
        assert proposal is not None
        # ── HITL confirmation card ──
        script_payload = {
            "name": proposal.get("name", "Untitled Script"),
            "description": proposal.get("description", ""),
            "code": validated_code,
            "script_type": proposal.get("script_type", "general"),
            "env_vars": proposal.get("env_vars", {}),
            "allowed_modules": proposal.get("allowed_modules", []),
        }
        yield self._sse({
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
        yield self._sse({"type": "done"})
    # ── Script extraction helper methods ──
    async def _extract_script_with_llm(
        self,
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
            response = await self.client.chat.completions.create(
                model=self.model,
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
    async def _extract_script_with_llm_heartbeat(
        self,
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
            r = await self._extract_script_with_llm(
                code_history, user_instructions, knowledge_context,
                system_prompt, previous_error,
            )
            result_holder.append(r)
            done_event.set()
        task = asyncio.create_task(_do_extract())
        while not done_event.is_set():
            try:
                await asyncio.wait_for(asyncio.shield(done_event.wait()), timeout=15.0)
            except asyncio.TimeoutError:
                yield self._sse({"type": "heartbeat", "content": "llm_thinking"})
        if task.done() and task.exception():
            logger.error(f"Script extraction task failed: {task.exception()}")
            yield None
            return
        yield result_holder[0] if result_holder else None
    async def _execute_script_validation_with_heartbeat(
        self, code: str, context: dict
    ) -> AsyncGenerator[str | dict, None]:
        """在沙箱中验证脚本可执行，带心跳"""
        from app.services.data_processor import sanitize_variable_name
        from app.models import Knowledge, Skill
        from sqlalchemy import select

        # ── 准备 data_var_map ──
        data_var_map: dict[str, str] = {}
        result = await self.db.execute(
            select(Knowledge).where(Knowledge.task_id == self.task_id)
        )
        for k in result.scalars().all():
            if k.type in ("csv", "excel") and k.file_path and os.path.exists(k.file_path):
                var_name = sanitize_variable_name(k.name)
                data_var_map[var_name] = os.path.abspath(k.file_path)

        capture_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures", "script_validate")
        os.makedirs(capture_dir, exist_ok=True)

        # ── 准备 persistent_vars ──
        persist_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures", "persist")
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

        # ── 准备 skill_envs ──
        skill_result = await self.db.execute(select(Skill).where(Skill.is_active == True))
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

        # 合并 context 中 extra_skill_envs（来自 /script 调用的 skill）
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

        # ── 复用 base 心跳包装器执行 ──
        async for item in self._execute_code_with_heartbeat(
            code=code,
            data_var_map=data_var_map,
            capture_dir=capture_dir,
            skill_envs=skill_envs if skill_envs else None,
            persistent_vars=persisted_var_map if persisted_var_map else None,
        ):
            yield item

    async def _save_script_asset(self, config: dict) -> AsyncGenerator[str, None]:
        """用户确认后，将 script 保存为 Asset"""
        from app.models import Asset
        from app.database import async_session
        print(f"Saving script asset with config: {config}")
        name = config.get("name", "Untitled Script")
        description = config.get("description", "")
        code = config.get("code", "")
        script_type = config.get("script_type", "general")
        env_vars = config.get("env_vars", {})
        allowed_modules = config.get("allowed_modules", [])

        if not code.strip():
            yield self._sse({"type": "error", "content": "Cannot save script: code is empty."})
            yield self._sse({"type": "done"})
            return

        yield self._sse({"type": "text", "content": f"💾 Saving script `{name}` as an asset...\n"})

        try:
            async with async_session() as db:
                asset = Asset(
                    name=name,
                    description=description,
                    asset_type="script",
                    source_task_id=self.task_id,
                    code=code,
                    script_type=script_type,
                    env_vars_json=json.dumps(env_vars, ensure_ascii=False),
                    allowed_modules_json=json.dumps(allowed_modules, ensure_ascii=False),
                )
                db.add(asset)
                await db.commit()
                await db.refresh(asset)

            env_summary = ""
            if env_vars:
                env_keys = ", ".join(f"`{k}`" for k in env_vars.keys())
                env_summary = f"| Env Vars | {env_keys} |\n"

            module_summary = ""
            if allowed_modules:
                module_summary = f"| Modules | {', '.join(f'`{m}`' for m in allowed_modules)} |\n"

            code_lines = len(code.strip().split("\n"))

            success_msg = (
                f"✅ **Script saved successfully!**\n\n"
                f"| Property | Value |\n"
                f"|----------|-------|\n"
                f"| Name | `{name}` |\n"
                f"| Type | {script_type} |\n"
                f"| Lines | {code_lines} |\n"
                f"{env_summary}"
                f"{module_summary}"
                f"\nYou can find this script in the **Assets** tab on the right panel.\n"
                f"Use the **Run** button to execute it independently."
            )
            yield self._sse({"type": "text", "content": success_msg})

        except Exception as e:
            logger.error(f"Script asset save failed: {e}")
            yield self._sse({"type": "error", "content": f"Failed to save script: {str(e)}"})

        yield self._sse({"type": "done"})

    def _build_sop_extraction_prompt(
        self,
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
Based on the analysis history above, create a **Standard Operating Procedure (SOP)** document in Markdown format.
The SOP should include:
1. **Objective** — What problem does this procedure solve?
2. **Prerequisites** — Required data sources, tools, or knowledge
3. **Step-by-Step Instructions** — Clear, actionable steps (abstract away specific file names)
4. **Expected Outputs** — What results should be produced
5. **Common Issues & Solutions** — Troubleshooting guide based on the history
Focus on making the SOP reusable for similar tasks in the future. Use clear headings and bullet points.
"""
        
        return prompt
