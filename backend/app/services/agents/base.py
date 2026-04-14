# backend/app/services/agents/base.py

"""Agent 基类 - 提供共享的 ReAct 循环和工具分发逻辑"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Any
from dataclasses import dataclass
import json
import os
import glob
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from openai import AsyncOpenAI

from app.config import UPLOADS_DIR
from app.models import Knowledge, Skill
from app.services.data_processor import sanitize_variable_name, get_csv_sample_rows, get_excel_sample_rows, read_text_content


@dataclass
class SandboxEnv:
    """沙箱执行环境配置"""
    data_var_map: dict[str, str]
    skill_envs: dict[str, str]
    persistent_vars: dict[str, str]
    capture_dir: str


class BaseAgent(ABC):
    """所有 Agent 的抽象基类"""
    
    def __init__(
        self,
        task_id: str,
        db: AsyncSession,
        client: AsyncOpenAI,
        model: str,
    ):
        self.task_id = task_id
        self.db = db
        self.client = client
        self.model = model
    
    @abstractmethod
    async def run(self, context: dict[str, Any]) -> AsyncGenerator[str, None]:
        """执行 Agent 逻辑，返回 SSE 流式输出"""
        if False:  # 永远不会执行，仅用于类型检查
            yield
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 安全辅助方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    def _safe_str(self, context: dict, key: str, default: str = "") -> str:
        """安全地从 context 获取字符串，防止 None"""
        value = context.get(key, default)
        return str(value) if value is not None else default
    
    def _sse(self, data: dict) -> str:
        """生成 SSE 事件格式"""
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 上下文准备
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def _get_knowledge_context(self) -> tuple[str, str, str, dict[str, str]]:
        """
        获取 Knowledge 上下文
        Returns: (dataset_context, text_context, variable_reference, data_var_map)
        """
        result = await self.db.execute(
            select(Knowledge).where(Knowledge.task_id == self.task_id)
        )
        knowledge_items = list(result.scalars().all())
        
        dataset_parts: list[str] = []
        text_parts: list[str] = []
        var_ref_parts: list[str] = []
        data_var_map: dict[str, str] = {}
        
        for k in knowledge_items:
            # CSV 处理
            if k.type == "csv" and k.file_path and os.path.exists(k.file_path):
                var_name = sanitize_variable_name(k.name)
                data_var_map[var_name] = os.path.abspath(k.file_path)
                
                section = f"### 📊 {k.name}  →  variable: `{var_name}`\n"
                section += "- **Type**: CSV\n"
                
                if k.metadata_json:
                    try:
                        meta = json.loads(k.metadata_json)
                        shape = meta.get("shape", [0, 0])
                        section += f"- **Shape**: {shape[0]:,} rows × {shape[1]} columns\n"
                        if "columns" in meta and "dtypes" in meta:
                            col_info = ", ".join(
                                f"`{c}` ({meta['dtypes'].get(c, '?')})"
                                for c in meta["columns"][:10]
                            )
                            if len(meta["columns"]) > 10:
                                col_info += f""", ... ({len(meta["columns"])} total)"""
                            section += f"- **Columns**: {col_info}\n"
                    except json.JSONDecodeError:
                        pass
                
                try:
                    sample = get_csv_sample_rows(k.file_path, n_rows=200)
                    if len(sample) > 5000:
                        sample = sample[:5000] + "\n... [sample truncated]"
                    section += f"""- **Sample rows**:\n```\n{sample}\n```\n"""
                except Exception:
                    pass
                
                dataset_parts.append(section)
                var_ref_parts.append(f"- `{var_name}` ← {k.name}")
            
            # Excel 处理
            elif k.type == "excel" and k.file_path and os.path.exists(k.file_path):
                var_name = sanitize_variable_name(k.name)
                data_var_map[var_name] = os.path.abspath(k.file_path)
                
                section = f"### 📊 {k.name}  →  variable: `{var_name}`\n"
                section += "- **Type**: Excel\n"
                
                sheet_names = []
                default_sheet = None
                if k.metadata_json:
                    try:
                        meta = json.loads(k.metadata_json)
                        sheet_names = meta.get("sheet_names", [])
                        sheets_data = meta.get("sheets", [])
                        
                        if sheet_names:
                            section += f"- **Sheets**: {', '.join(sheet_names)}\n"
                            default_sheet = sheet_names[0]
                            section += f"- **Default sheet**: `{default_sheet}` (loaded as `{var_name}`)\n"
                            
                            if len(sheet_names) > 1:
                                other_sheets = ', '.join(f"`{s}`" for s in sheet_names[1:])
                                section += f"- **Access other sheets**: Use `{var_name}_sheets[{other_sheets}]`\n"
                        
                        if sheets_data:
                            first_sheet = sheets_data[0]
                            shape = first_sheet.get("shape", [0, 0])
                            section += f"- **Shape** (default sheet): {shape[0]:,} rows × {shape[1]} columns\n"
                            
                            if "columns" in first_sheet and "dtypes" in first_sheet:
                                col_info = ", ".join(
                                    f"`{c}` ({first_sheet['dtypes'].get(c, '?')})"
                                    for c in first_sheet["columns"][:10]
                                )
                                if len(first_sheet["columns"]) > 10:
                                    col_info += f", ... ({len(first_sheet['columns'])} total)"
                                section += f"- **Columns**: {col_info}\n"
                    except json.JSONDecodeError:
                        pass
                
                try:
                    sample = get_excel_sample_rows(k.file_path, sheet_name=default_sheet, n_rows=200)
                    if len(sample) > 5000:
                        sample = sample[:5000] + "\n... [sample truncated]"
                    section += f"- **Sample rows** (default sheet):\n```\n{sample}\n```\n"
                except Exception:
                    pass
                
                dataset_parts.append(section)
                var_ref_parts.append(f"- `{var_name}` ← {k.name} (default sheet)")
                if len(sheet_names) > 1:
                    var_ref_parts.append(f"  - `{var_name}_sheets` ← all sheets dictionary")
            
            # 文本文件处理
            elif k.type in ("text", "backstory") and k.file_path and os.path.exists(k.file_path):
                try:
                    content = read_text_content(k.file_path)
                    text_parts.append(f"### 📄 {k.name}\n{content}")
                except Exception:
                    pass
            
            # DuckDB 表引用处理
            elif k.type == "duckdb_table" and k.metadata_json:
                try:
                    meta = json.loads(k.metadata_json)
                    tbl_name = meta.get("table_name", k.name)
                    display = meta.get("display_name", tbl_name)
                    desc = meta.get("description", "")
                    schema = meta.get("schema", [])
                    row_count = meta.get("row_count", 0)
                    src_type = meta.get("source_type", "unknown")
                    updated = meta.get("data_updated_at", "unknown")
                    sample = meta.get("sample_rows", [])

                    section = f"### 📊 [DuckDB] {display}  →  table: `{tbl_name}`\n"
                    section += f"- **Source**: {src_type}\n"
                    section += f"- **Rows**: {row_count:,}\n"
                    section += f"- **Last updated**: {updated}\n"
                    if desc:
                        section += f"- **Description**: {desc}\n"
                    if schema:
                        col_info = ", ".join(
                            f"`{c['name']}` ({c['type']})" for c in schema[:15]
                        )
                        if len(schema) > 15:
                            col_info += f", ... ({len(schema)} total)"
                        section += f"- **Columns**: {col_info}\n"
                    if sample:
                        import pandas as pd
                        try:
                            sample_df = pd.DataFrame(sample)
                            sample_str = sample_df.to_string(index=False, max_rows=5)
                            if len(sample_str) > 2000:
                                sample_str = sample_str[:2000] + "\n... [truncated]"
                            section += f"- **Sample rows**:\n```\n{sample_str}\n```\n"
                        except Exception:
                            pass

                    section += (
                        f"\n> **Query this table**: In execute_python_code, use:\n"
                        f"> ```python\n"
                        f"> import duckdb\n"
                        f"> con = duckdb.connect(getenv('WAREHOUSE_PATH'), read_only=True)\n"
                        f"> df = con.execute(\"SELECT * FROM {tbl_name} LIMIT 100\").fetchdf()\n"
                        f"> con.close()\n"
                        f"> ```\n"
                    )

                    dataset_parts.append(section)
                except (json.JSONDecodeError, Exception):
                    pass

        dataset_context = "\n".join(dataset_parts) if dataset_parts else "[No datasets uploaded yet.]"
        text_context = "\n\n".join(text_parts) if text_parts else "[No reference documents.]"
        
        # 扫描 persist/ 目录，将已持久化的中间变量摘要加入 variable_reference
        persist_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures", "persist")
        persisted_var_parts: list[str] = []
        _seen_vars: set[str] = set()
        
        if os.path.isdir(persist_dir):
            _all_files = sorted(glob.glob(os.path.join(persist_dir, "*.parquet"))) + \
                         sorted(glob.glob(os.path.join(persist_dir, "*.json")))
            for fpath in _all_files:
                vname = os.path.splitext(os.path.basename(fpath))[0]
                if vname in data_var_map or vname in _seen_vars:
                    continue
                _seen_vars.add(vname)

                if fpath.endswith(".parquet"):
                    try:
                        import pyarrow.parquet as pq
                        pf = pq.ParquetFile(fpath)
                        schema = pf.schema_arrow
                        num_rows = pf.metadata.num_rows
                        meta = schema.metadata or {}
                        persist_type = meta.get(b'__persist_type__', b'').decode('utf-8')

                        if persist_type == "series":
                            sname = meta.get(b'__series_name__', b'').decode('utf-8') or '?'
                            col_type = str(schema.field(0).type) if schema else '?'
                            persisted_var_parts.append(
                                f"- `{vname}` — Series(name={sname!r}, dtype={col_type}, len={num_rows})"
                            )
                        else:
                            col_names = [schema.field(i).name for i in range(len(schema))]
                            col_preview = ", ".join(f"`{c}`" for c in col_names[:8])
                            if len(col_names) > 8:
                                col_preview += f", ... ({len(col_names)} cols)"
                            persisted_var_parts.append(
                                f"- `{vname}` — DataFrame ({num_rows} rows) [{col_preview}]"
                            )
                    except Exception:
                        persisted_var_parts.append(f"- `{vname}` — (unable to read parquet)")
                    continue

                # JSON 文件（向后兼容）
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        blob = json.load(f)
                    ptype = blob.get("__persist_type__")

                    if ptype is None or ptype == "dataframe":
                        cols = blob.get("columns", [])
                        rows = blob.get("rows", [])
                        col_preview = ", ".join(f"`{c}`" for c in cols[:8])
                        if len(cols) > 8:
                            col_preview += f", ... ({len(cols)} cols)"
                        persisted_var_parts.append(
                            f"- `{vname}` — DataFrame ({len(rows)} rows) [{col_preview}]"
                        )
                    elif ptype == "series":
                        data = blob.get("data", [])
                        name = blob.get("name", "")
                        dtype = blob.get("dtype", "?")
                        persisted_var_parts.append(
                            f"- `{vname}` — Series(name={name!r}, dtype={dtype}, len={len(data)})"
                        )
                    elif ptype == "ndarray":
                        shape = blob.get("shape", [])
                        dtype = blob.get("dtype", "?")
                        persisted_var_parts.append(
                            f"- `{vname}` — np.ndarray(shape={shape}, dtype={dtype})"
                        )
                    elif ptype == "numpy_scalar":
                        val = blob.get("value")
                        dtype = blob.get("dtype", "?")
                        persisted_var_parts.append(
                            f"- `{vname}` — numpy scalar = {val!r} ({dtype})"
                        )
                    elif ptype == "value":
                        val = blob.get("value")
                        type_name = type(val).__name__
                        if isinstance(val, (list, dict)):
                            val_preview = repr(val)
                            if len(val_preview) > 80:
                                val_preview = val_preview[:77] + "..."
                            persisted_var_parts.append(
                                f"- `{vname}` — {type_name}(len={len(val)}) = {val_preview}"
                            )
                        else:
                            persisted_var_parts.append(
                                f"- `{vname}` — {type_name} = {val!r}"
                            )
                    else:
                        persisted_var_parts.append(
                            f"- `{vname}` — (unknown type: {ptype})"
                        )
                except Exception:
                    persisted_var_parts.append(f"- `{vname}` — (unable to read)")

        # 合并 variable_reference
        if var_ref_parts or persisted_var_parts:
            all_var_parts = []
            if var_ref_parts:
                all_var_parts.append("**Datasets (preloaded):**")
                all_var_parts.extend(var_ref_parts)
            if persisted_var_parts:
                all_var_parts.append("")
                all_var_parts.append("**Intermediate variables (from previous steps):**")
                all_var_parts.extend(persisted_var_parts)
            variable_reference = "\n".join(all_var_parts)
        else:
            variable_reference = "[No datasets or variables available.]"
        
        return dataset_context, text_context, variable_reference, data_var_map
    
    async def _get_skill_context(self) -> tuple[str, dict[str, str]]:
        """
        获取所有激活的 Skill 上下文
        Returns: (skill_prompt, skill_envs)
        """
        result = await self.db.execute(
            select(Skill).where(Skill.is_active == True)
        )
        skills = list(result.scalars().all())
        if not skills:
            return "[No skills configured.]", {}
        
        prompt_parts: list[str] = []
        merged_envs: dict[str, str] = {}
        all_modules: set[str] = set()
        
        for skill in skills:
            section = f"### 🔧 Skill: {skill.name}\n"
            if skill.description:
                section += f"{skill.description}\n"
            if skill.prompt_markdown:
                section += f"\n{skill.prompt_markdown}\n"
            
            try:
                env_dict: dict[str, str] = json.loads(skill.env_vars_json) if skill.env_vars_json else {}
            except (json.JSONDecodeError, TypeError):
                env_dict = {}
            if env_dict:
                env_keys = ", ".join(f"`{k}`" for k in env_dict.keys())
                section += f"\n> **Available env vars** (use `_safe_getenv('KEY')`): {env_keys}\n"
                merged_envs.update(env_dict)
            
            try:
                modules: list[str] = json.loads(skill.allowed_modules_json) if skill.allowed_modules_json else []
            except (json.JSONDecodeError, TypeError):
                modules = []
            if modules:
                all_modules.update(modules)
                section += f"> **Allowed imports**: {', '.join(f'`{m}`' for m in modules)}\n"
            
            if skill.reference_markdown:
                section += (
                    f"\n> 📚 **Detailed reference available** — call "
                    f"`get_skill_reference('{skill.name}')` when you need "
                    f"exact API signatures, advanced usage, or troubleshooting.\n"
                )
            prompt_parts.append(section)
        
        if all_modules:
            merged_envs["__allowed_modules__"] = json.dumps(list(all_modules))
        
        skill_prompt = "\n---\n".join(prompt_parts)
        return skill_prompt, merged_envs
    
    async def _lookup_skill_reference(self, skill_name: str) -> str:
        """根据 Skill 名称查询其 reference_markdown"""
        result = await self.db.execute(
            select(Skill).where(Skill.name == skill_name, Skill.is_active == True)
        )
        skill = result.scalar_one_or_none()

        if not skill:
            all_result = await self.db.execute(
                select(Skill.name).where(Skill.is_active == True)
            )
            available = [row[0] for row in all_result.all()]
            if available:
                return (
                    f"ERROR: No active skill named '{skill_name}'. "
                    f"Available skills: {', '.join(available)}"
                )
            return f"ERROR: No active skill named '{skill_name}'. No skills are currently active."

        if not skill.reference_markdown:
            return (
                f"Skill '{skill_name}' has no detailed reference documentation. "
                f"Use the basic prompt already in your context."
            )

        return f"# Reference: {skill.name}\n\n{skill.reference_markdown}"
    
    async def _build_warehouse_context(self) -> str:
        """构建 DuckDB 仓库的上下文信息"""
        from app.models import DuckDBTable

        result = await self.db.execute(
            select(DuckDBTable)
            .where(DuckDBTable.status != "error")
            .order_by(DuckDBTable.updated_at.desc())
            .limit(20)
        )
        tables = list(result.scalars().all())

        if not tables:
            return (
                "The local DuckDB warehouse is empty. You can use `materialize_to_duckdb` "
                "to save cleaned DataFrames as persistent tables.\n\n"
                "To query DuckDB tables in code, use:\n"
                "```python\n"
                "import duckdb\n"
                "con = duckdb.connect(getenv('WAREHOUSE_PATH'), read_only=True)\n"
                "df = con.execute('SELECT * FROM table_name').fetchdf()\n"
                "con.close()\n"
                "```"
            )

        lines = [
            "The following tables exist in the local DuckDB warehouse. "
            "You can query them using `duckdb.connect(getenv('WAREHOUSE_PATH'))` "
            "inside `execute_python_code`.\n"
        ]
        for t in tables:
            try:
                schema = json.loads(t.table_schema_json) if t.table_schema_json else []
            except (json.JSONDecodeError, TypeError):
                schema = []
            col_preview = ", ".join(f"`{s['name']}` ({s['type']})" for s in schema[:8])
            if len(schema) > 8:
                col_preview += f", ... ({len(schema)} cols)"

            updated = t.data_updated_at.strftime("%Y-%m-%d %H:%M") if t.data_updated_at else "unknown"
            lines.append(
                f"- **{t.table_name}** — {t.display_name} "
                f"({t.row_count:,} rows, source: {t.source_type}, updated: {updated})\n"
                f"  Columns: {col_preview}"
            )
            if t.description:
                lines.append(f"  Description: {t.description}")

        lines.append(
            "\n**To persist new data**: Use `materialize_to_duckdb` tool. "
            "For FIRST-TIME writes, confirm with the user via `request_human_input` first."
        )

        return "\n".join(lines)
    
    async def _prepare_sandbox_env(
        self,
        *,
        capture_subdir: str = "",
        extra_skill_envs: dict[str, str] | None = None,
    ) -> SandboxEnv:
        """
        准备沙箱执行环境
        
        Args:
            capture_subdir: 捕获目录的子目录名（如 "default", "derive_exec", "script_validate"）
            extra_skill_envs: 额外的技能环境变量（如来自 slash command 的 inactive skill）
        """
        # 收集 data_var_map
        dataset_ctx, text_ctx, var_ref, data_var_map = await self._get_knowledge_context()
        
        # 收集 skill_envs
        skill_ctx, skill_envs = await self._get_skill_context()
        
        # 合并 extra_skill_envs
        if extra_skill_envs:
            effective_envs = dict(skill_envs)
            # 特殊处理 __allowed_modules__（需要合并而非覆盖）
            if "__allowed_modules__" in extra_skill_envs and "__allowed_modules__" in effective_envs:
                existing_m = set(json.loads(effective_envs["__allowed_modules__"]))
                new_m = set(json.loads(extra_skill_envs["__allowed_modules__"]))
                effective_envs["__allowed_modules__"] = json.dumps(list(existing_m | new_m))
                # 其他环境变量直接更新
                extra_clean = {k: v for k, v in extra_skill_envs.items() if k != "__allowed_modules__"}
                effective_envs.update(extra_clean)
            else:
                effective_envs.update(extra_skill_envs)
            skill_envs = effective_envs
        
        # 收集 persistent_vars
        persist_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures", "persist")
        persistent_vars: dict[str, str] = {}
        if os.path.isdir(persist_dir):
            for fpath in glob.glob(os.path.join(persist_dir, "*.json")):
                var_name = os.path.splitext(os.path.basename(fpath))[0]
                persistent_vars[var_name] = fpath
            # Parquet 后扫描，覆盖同名 JSON
            for fpath in glob.glob(os.path.join(persist_dir, "*.parquet")):
                var_name = os.path.splitext(os.path.basename(fpath))[0]
                persistent_vars[var_name] = fpath
        
        # 准备 capture_dir
        if capture_subdir:
            capture_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures", capture_subdir)
        else:
            capture_dir = os.path.join(UPLOADS_DIR, self.task_id, "captures")
        os.makedirs(capture_dir, exist_ok=True)
        
        return SandboxEnv(
            data_var_map=data_var_map,
            skill_envs=skill_envs,
            persistent_vars=persistent_vars,
            capture_dir=capture_dir,
        )
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 核心 ReAct 循环
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def _run_react_loop(
        self,
        *,
        messages: list,
        tools: list[dict],
        sandbox_env: SandboxEnv,
        context: dict,
        max_rounds: int = 10,
        temperature: float = 0.4,
    ) -> AsyncGenerator[str, None]:
        """
        统一的 ReAct 循环：调用 LLM，处理工具调用，流式输出
        
        Args:
            messages: OpenAI messages 列表
            tools: 工具定义列表
            sandbox_env: 沙箱环境配置
            context: 执行上下文（包含 user_message 等）
            max_rounds: 最大循环轮次
            temperature: LLM 温度
        
        Yields:
            SSE 格式的字符串
        """
        hitl_break = False
        
        for round_idx in range(max_rounds):
            if hitl_break:
                break
            
            try:
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools if tools else None,  # type: ignore
                    tool_choice="auto" if tools else None,  # type: ignore
                    stream=True,
                    temperature=temperature,
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
            
            # 处理 tool calls
            if tool_calls_acc:
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
                    
                    # ── Tool: execute_python_code ──
                    if tc["name"] == "execute_python_code":
                        code = args.get("code", "")
                        purpose = args.get("purpose", "")
                        
                        yield self._sse({"type": "tool_start", "code": code, "purpose": purpose})
                        
                        capture_id = uuid.uuid4().hex[:12]
                        
                        try:
                            exec_result = None
                            async for item in self._execute_code_with_heartbeat(
                                code=code,
                                data_var_map=sandbox_env.data_var_map,
                                capture_dir=sandbox_env.capture_dir,
                                skill_envs=sandbox_env.skill_envs,
                                persistent_vars=sandbox_env.persistent_vars,
                            ):
                                if isinstance(item, str):
                                    yield item  # 心跳转发
                                else:
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
                        
                        # 重命名捕获的 DataFrame 文件
                        captured_dfs = exec_result.get("dataframes", [])
                        for df_meta in captured_dfs:
                            df_meta["capture_id"] = capture_id
                            old_path = os.path.join(sandbox_env.capture_dir, f"{df_meta['name']}.json")
                            new_name = f"{capture_id}_{df_meta['name']}.json"
                            new_path = os.path.join(sandbox_env.capture_dir, new_name)
                            if os.path.exists(old_path):
                                try:
                                    os.rename(old_path, new_path)
                                except OSError:
                                    pass
                        
                        # 收集本轮持久化的变量
                        new_persisted = exec_result.get("persisted_vars", {})
                        if new_persisted:
                            sandbox_env.persistent_vars.update(new_persisted)
                        
                        yield self._sse({
                            "type": "tool_result",
                            "success": exec_result["success"],
                            "output": exec_result.get("output"),
                            "error": exec_result.get("error"),
                            "time": exec_result.get("execution_time", 0),
                            "dataframes": captured_dfs,
                        })
                        
                        # 处理沙箱内 create_chart() 捕获的图表
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
                        
                        # 处理沙箱内 create_map() 捕获的地图
                        sandbox_maps = exec_result.get("maps", [])
                        for map_meta in sandbox_maps:
                            map_config = map_meta.get("config", {})
                            from app.tools.visualization import validate_map_config
                            ok_map, err_map = validate_map_config(map_config)
                            if ok_map:
                                yield self._sse({
                                    "type": "visualization",
                                    "title": map_meta.get("title", "Untitled Map"),
                                    "chart_type": "map",
                                    "option": map_config,
                                })
                            else:
                                yield self._sse({
                                    "type": "error",
                                    "content": f"Map validation failed: {err_map}",
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
                    
                    # ── Tool: create_visualization ──
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
                    
                    # ── Tool: get_skill_reference ──
                    elif tc["name"] == "get_skill_reference":
                        skill_name = args.get("skill_name", "")
                        ref_content = await self._lookup_skill_reference(skill_name)
                        if len(ref_content) > 12000:
                            ref_content = ref_content[:12000] + "\n\n[... reference truncated]"
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": ref_content,
                        })  # type: ignore
                    
                    # ── Tool: materialize_to_duckdb ──
                    elif tc["name"] == "materialize_to_duckdb":
                        result_content = await self._handle_materialize_to_duckdb(
                            args=args,
                            persistent_vars=sandbox_env.persistent_vars,
                            capture_dir=sandbox_env.capture_dir,
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_content,
                        })  # type: ignore
                    
                    # ── Tool: list_duckdb_tables ──
                    elif tc["name"] == "list_duckdb_tables":
                        result_content = await self._handle_list_duckdb_tables()
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_content,
                        })  # type: ignore
                    
                    # ── Tool: request_human_input (HITL) ──
                    elif tc["name"] == "request_human_input":
                        hitl_event, tool_content = self._handle_hitl_request(args)
                        yield hitl_event
                        
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(tool_content, ensure_ascii=False),
                        })  # type: ignore
                        
                        hitl_break = True
                        break
                    
                    # ── Unknown tool ──
                    else:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": f"ERROR: Unknown tool '{tc['name']}'",
                        })  # type: ignore
                
                if hitl_break:
                    break
                continue  # 继续下一轮 ReAct
            
            # 纯文本回复 - 调用子类钩子
            if text_content.strip():
                extra_events, extra_messages, should_continue = await self._on_text_complete(
                    text_content, messages, context
                )
                
                # 发送额外事件
                for event in extra_events:
                    yield event
                
                # 注入额外消息
                messages.extend(extra_messages)
                
                # 决定是否继续
                if not should_continue:
                    break
                continue
            
            # 既没有 tool call 也没有文本 - 结束
            break
    
    async def _on_text_complete(
        self,
        text_content: str,
        messages: list,
        context: dict,
    ) -> tuple[list[str], list, bool]:
        """
        文本回复完成后的钩子，供子类覆盖
        
        Args:
            text_content: LLM 返回的文本内容
            messages: 当前消息列表
            context: 执行上下文
        
        Returns:
            (extra_sse_events, extra_messages, should_continue)
            - extra_sse_events: 额外的 SSE 事件列表
            - extra_messages: 需要注入到 messages 的额外消息
            - should_continue: 是否继续 ReAct 循环
        """
        # 默认实现：不产生额外事件，不继续循环
        return [], [], False
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 工具处理辅助方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def _execute_code_with_heartbeat(
        self,
        code: str,
        data_var_map: dict[str, str],
        capture_dir: str,
        skill_envs: dict[str, str] | None = None,
        persistent_vars: dict[str, str] | None = None,
    ) -> AsyncGenerator[str | dict, None]:
        """执行代码并定期发送心跳，避免前端 90s 超时"""
        import asyncio
        from app.services.sandbox import execute_code_in_sandbox
        
        exec_task = asyncio.create_task(
            execute_code_in_sandbox(
                code=code,
                data_var_map=data_var_map,
                capture_dir=capture_dir,
                injected_envs=skill_envs,
                persisted_var_map=persistent_vars,
            )
        )
        
        while not exec_task.done():
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(exec_task),
                    timeout=15.0
                )
                yield result
                return
            except asyncio.TimeoutError:
                yield self._sse({"type": "heartbeat", "content": "tool_running"})
        
        try:
            result = await exec_task
            yield result
        except Exception as e:
            yield {
                "success": False,
                "output": None,
                "error": f"Execution failed: {str(e)}",
                "execution_time": 0.0,
            }
    
    def _handle_hitl_request(self, args: dict) -> tuple[str, dict]:
        """处理 request_human_input 工具调用"""
        title = args.get("title", "Awaiting your guidance")
        description = args.get("description", "")
        options = args.get("options", [])
        
        hitl_event = self._sse({
            "type": "hitl_request",
            "title": title,
            "description": description,
            "options": options,
        })
        
        tool_content = {
            "status": "paused",
            "message": (
                "PAUSED: A decision card has been presented to the user. "
                "The conversation will resume with the user's choice. "
                "Do NOT continue generating — wait for the user's response."
            )
        }
        return hitl_event, tool_content
    
    async def _handle_materialize_to_duckdb(
        self,
        args: dict,
        persistent_vars: dict[str, str],
        capture_dir: str,
    ) -> str:
        """处理 materialize_to_duckdb 工具调用"""
        import pandas as pd
        import pyarrow.parquet as pq
        from app.services import warehouse as wh
        from app.models import DuckDBTable
        from app.database import async_session
        from datetime import datetime

        var_name = args.get("dataframe_variable", "")
        table_name = args.get("table_name", "")
        display_name = args.get("display_name", table_name)
        description = args.get("description", "")
        strategy = args.get("write_strategy", "replace")
        upsert_key = args.get("upsert_key")
        source_type = args.get("source_type", "unknown")
        source_config = args.get("source_config")

        # 验证表名
        valid, err = wh.validate_table_name(table_name)
        if not valid:
            return f"ERROR: {err}"

        # 从 persist/ 目录找到 DataFrame
        persist_dir = os.path.join(capture_dir, "persist")
        df = None

        parquet_path = os.path.join(persist_dir, f"{var_name}.parquet")
        json_path = os.path.join(persist_dir, f"{var_name}.json")

        if os.path.exists(parquet_path):
            try:
                table = pq.read_table(parquet_path)
                meta = table.schema.metadata or {}
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

        # 写入 DuckDB
        try:
            result = await wh.async_write_dataframe(df, table_name, strategy, upsert_key)
        except Exception as e:
            return f"ERROR: DuckDB write failed: {str(e)}"

        # 注册/更新元数据到 SQLite
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
            import logging
            logging.getLogger(__name__).error(f"DuckDB metadata registration failed: {e}")

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