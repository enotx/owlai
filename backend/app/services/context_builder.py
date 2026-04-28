# backend/app/services/context_builder.py

"""上下文构建服务 - 独立于 Agent 实例的上下文拼装逻辑"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Task, Knowledge, Skill, Asset, DataPipeline
from app.prompts.fragments.execution_profiles import (
    PromptProfile,
    LOCAL_PROFILE,
    resolve_prompt_profile,
)
from app.prompts.analyst import build_analyst_system_prompt
from app.prompts.plan import build_plan_system_prompt
from app.services.data_processor import (
    sanitize_variable_name,
    get_csv_sample_rows,
    get_excel_sample_rows,
    read_text_content,
)

import os
import json
import glob

async def _get_knowledge_context(task_id: str, db: AsyncSession) -> tuple[str, str, str]:
    """获取 Knowledge 上下文（复用 BaseAgent 的逻辑）"""
    result = await db.execute(
        select(Knowledge).where(Knowledge.task_id == task_id)
    )
    knowledge_items = list(result.scalars().all())
    
    dataset_parts: list[str] = []
    text_parts: list[str] = []
    var_ref_parts: list[str] = []
    
    for k in knowledge_items:
        if k.type == "csv" and k.file_path and os.path.exists(k.file_path):
            var_name = sanitize_variable_name(k.name)
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
                            col_info += f", ... ({len(meta['columns'])} total)"
                        section += f"- **Columns**: {col_info}\n"
                except json.JSONDecodeError:
                    pass
            
            try:
                sample = get_csv_sample_rows(k.file_path, n_rows=200)
                if len(sample) > 5000:
                    sample = sample[:5000] + "\n... [sample truncated]"
                section += f"- **Sample rows**:\n```\n{sample}\n```\n"
            except Exception:
                pass
            
            dataset_parts.append(section)
            var_ref_parts.append(f"- `{var_name}` ← {k.name}")
        
        elif k.type == "excel" and k.file_path and os.path.exists(k.file_path):
            var_name = sanitize_variable_name(k.name)
            section = f"### 📊 {k.name}  →  variable: `{var_name}`\n"
            section += "- **Type**: Excel\n"
            
            sheet_names = []
            default_sheet = None
            if k.metadata_json:
                try:
                    meta = json.loads(k.metadata_json)
                    sheet_names = meta.get("sheet_names", [])
                    if sheet_names:
                        section += f"- **Sheets**: {', '.join(sheet_names)}\n"
                        default_sheet = sheet_names[0]
                        section += f"- **Default sheet**: `{default_sheet}`\n"
                        if len(sheet_names) > 1:
                            section += f"- **Access other sheets**: Use `{var_name}_sheets[...]`\n"
                    
                    sheets_data = meta.get("sheets", [])
                    if sheets_data:
                        first_sheet = sheets_data[0]
                        shape = first_sheet.get("shape", [0, 0])
                        section += f"- **Shape**: {shape[0]:,} rows × {shape[1]} columns\n"
                        if "columns" in first_sheet:
                            col_info = ", ".join(
                                f"`{c}`" for c in first_sheet["columns"][:10]
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
                section += f"- **Sample rows**:\n```\n{sample}\n```\n"
            except Exception:
                pass
            
            dataset_parts.append(section)
            var_ref_parts.append(f"- `{var_name}` ← {k.name}")
        
        elif k.type in ("text", "backstory") and k.file_path and os.path.exists(k.file_path):
            try:
                content = read_text_content(k.file_path)
                text_parts.append(f"### 📄 {k.name}\n{content}")
            except Exception:
                pass
        
        elif k.type == "duckdb_table" and k.metadata_json:
            try:
                meta = json.loads(k.metadata_json)
                tbl_name = meta.get("table_name", k.name)
                display = meta.get("display_name", tbl_name)
                desc = meta.get("description", "")
                schema = meta.get("schema", [])
                row_count = meta.get("row_count", 0)
                
                section = f"### 📊 [DuckDB] {display}  →  table: `{tbl_name}`\n"
                section += f"- **Rows**: {row_count:,}\n"
                if desc:
                    section += f"- **Description**: {desc}\n"
                if schema:
                    col_info = ", ".join(
                        f"`{c['name']}` ({c['type']})" for c in schema[:15]
                    )
                    if len(schema) > 15:
                        col_info += f", ... ({len(schema)} total)"
                    section += f"- **Columns**: {col_info}\n"
                
                dataset_parts.append(section)
            except (json.JSONDecodeError, Exception):
                pass
    
    # 扫描 persist/ 目录
    from app.tenant_context import get_uploads_dir
    persist_dir = os.path.join(str(get_uploads_dir()), task_id, "captures", "persist")
    persisted_var_parts: list[str] = []
    
    if os.path.isdir(persist_dir):
        for fpath in sorted(glob.glob(os.path.join(persist_dir, "*.parquet"))):
            vname = os.path.splitext(os.path.basename(fpath))[0]
            try:
                import pyarrow.parquet as pq
                pf = pq.ParquetFile(fpath)
                num_rows = pf.metadata.num_rows
                schema = pf.schema_arrow
                col_names = [schema.field(i).name for i in range(len(schema))]
                col_preview = ", ".join(f"`{c}`" for c in col_names[:8])
                if len(col_names) > 8:
                    col_preview += f", ... ({len(col_names)} cols)"
                persisted_var_parts.append(
                    f"- `{vname}` — DataFrame ({num_rows} rows) [{col_preview}]"
                )
            except Exception:
                persisted_var_parts.append(f"- `{vname}` — (unable to read)")
    
    # 合并 variable_reference
    all_var_parts = []
    if var_ref_parts:
        all_var_parts.append("**Datasets (preloaded):**")
        all_var_parts.extend(var_ref_parts)
    if persisted_var_parts:
        all_var_parts.append("")
        all_var_parts.append("**Intermediate variables:**")
        all_var_parts.extend(persisted_var_parts)
    
    dataset_context = "\n".join(dataset_parts) if dataset_parts else "[No datasets uploaded yet.]"
    text_context = "\n\n".join(text_parts) if text_parts else "[No reference documents.]"
    variable_reference = "\n".join(all_var_parts) if all_var_parts else "[No datasets or variables available.]"
    
    return dataset_context, text_context, variable_reference

async def _get_knowledge_context_with_assets(
    task_id: str, db: AsyncSession
) -> tuple[str, str, str, dict[str, str]]:
    """
    获取 Knowledge 上下文（支持 asset/sop/pipeline）
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
        # ── CSV ──
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
                            col_info += f", ... ({len(meta['columns'])} total)"
                        section += f"- **Columns**: {col_info}\n"
                except json.JSONDecodeError:
                    pass
            
            try:
                sample = get_csv_sample_rows(k.file_path, n_rows=200)
                if len(sample) > 5000:
                    sample = sample[:5000] + "\n... [sample truncated]"
                section += f"- **Sample rows**:\n```\n{sample}\n```\n"
            except Exception:
                pass
            
            dataset_parts.append(section)
            var_ref_parts.append(f"- `{var_name}` ← {k.name}")
        
        # ── Excel ──
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
                    if sheet_names:
                        section += f"- **Sheets**: {', '.join(sheet_names)}\n"
                        default_sheet = sheet_names[0]
                        section += f"- **Default sheet**: `{default_sheet}`\n"
                        if len(sheet_names) > 1:
                            section += f"- **Access other sheets**: Use `{var_name}_sheets[...]`\n"
                    
                    sheets_data = meta.get("sheets", [])
                    if sheets_data:
                        first_sheet = sheets_data[0]
                        shape = first_sheet.get("shape", [0, 0])
                        section += f"- **Shape**: {shape[0]:,} rows × {shape[1]} columns\n"
                        if "columns" in first_sheet:
                            col_info = ", ".join(
                                f"`{c}`" for c in first_sheet["columns"][:10]
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
                section += f"- **Sample rows**:\n```\n{sample}\n```\n"
            except Exception:
                pass
            
            dataset_parts.append(section)
            var_ref_parts.append(f"- `{var_name}` ← {k.name}")
        
        # ── Text / Backstory ──
        elif k.type in ("text", "backstory") and k.file_path and os.path.exists(k.file_path):
            try:
                content = read_text_content(k.file_path)
                text_parts.append(f"### 📄 {k.name}\n{content}")
            except Exception:
                pass
        
        # ── Asset Script ──
        elif k.type == "asset_script" and k.metadata_json:
            try:
                meta = json.loads(k.metadata_json)
                asset_id = meta.get("asset_id")
                asset = await db.get(Asset, asset_id) if asset_id else None
                if not asset:
                    continue

                section = f"### 🧩 Script Asset: {asset.name}\n"
                if asset.description:
                    section += f"- **Description**: {asset.description}\n"
                if asset.script_type:
                    section += f"- **Script Type**: {asset.script_type}\n"
                section += (
                    "\nThis is a deterministic reusable Python script reference. "
                    "Use it as context and guidance. Do not assume it has already been executed.\n"
                )
                if asset.code:
                    code = asset.code
                    if len(code) > 12000:
                        code = code[:12000] + "\n# ... [truncated]"
                    section += f"\n```python\n{code}\n```\n"
                text_parts.append(section)
            except Exception:
                pass
        
        # ── Asset SOP ──
        elif k.type == "asset_sop" and k.metadata_json:
            try:
                meta = json.loads(k.metadata_json)
                asset_id = meta.get("asset_id")
                asset = await db.get(Asset, asset_id) if asset_id else None
                if not asset:
                    continue

                section = f"### 📘 SOP Asset: {asset.name}\n"
                if asset.description:
                    section += f"- **Description**: {asset.description}\n"
                section += (
                    "\nThis is a reusable operating procedure reference. "
                    "Use it as contextual guidance unless this task is explicitly bound to it as a routine.\n\n"
                )
                content = asset.content_markdown or ""
                if len(content) > 12000:
                    content = content[:12000] + "\n\n...[truncated]"
                section += content
                text_parts.append(section)
            except Exception:
                pass
        
        # ── Data Pipeline ──
        elif k.type == "data_pipeline" and k.metadata_json:
            try:
                meta = json.loads(k.metadata_json)
                pipeline_id = meta.get("pipeline_id")
                pipeline = await db.get(DataPipeline, pipeline_id) if pipeline_id else None
                if not pipeline:
                    continue

                section = f"### 🔄 Data Pipeline: {pipeline.name}\n"
                if pipeline.description:
                    section += f"- **Description**: {pipeline.description}\n"
                section += f"- **Source Type**: {pipeline.source_type}\n"
                section += f"- **Target Table**: `{pipeline.target_table_name}`\n"
                section += f"- **Write Strategy**: {pipeline.write_strategy}\n"
                if pipeline.transform_description:
                    section += f"- **Transform Description**: {pipeline.transform_description}\n"
                section += (
                    "\nThis pipeline defines how a derived dataset is produced or refreshed. "
                    "Treat it as lineage and transformation context.\n"
                )
                code = pipeline.transform_code or ""
                if len(code) > 12000:
                    code = code[:12000] + "\n# ... [truncated]"
                section += f"\n```python\n{code}\n```\n"
                text_parts.append(section)
            except Exception:
                pass
        
        # ── DuckDB Table ──
        elif k.type == "duckdb_table" and k.metadata_json:
            try:
                meta = json.loads(k.metadata_json)
                tbl_name = meta.get("table_name", k.name)
                display = meta.get("display_name", tbl_name)
                desc = meta.get("description", "")
                schema = meta.get("schema", [])
                row_count = meta.get("row_count", 0)
                
                section = f"### 📊 [DuckDB] {display}  →  table: `{tbl_name}`\n"
                section += f"- **Rows**: {row_count:,}\n"
                if desc:
                    section += f"- **Description**: {desc}\n"
                
                pipeline_id = meta.get("pipeline_id")
                if pipeline_id:
                    section += f"- **Pipeline ID**: `{pipeline_id}`\n"
                    section += "- **Lineage**: This table has an associated data pipeline available in context or retrievable by ID.\n"
                
                if schema:
                    col_info = ", ".join(
                        f"`{c['name']}` ({c['type']})" for c in schema[:15]
                    )
                    if len(schema) > 15:
                        col_info += f", ... ({len(schema)} total)"
                    section += f"- **Columns**: {col_info}\n"
                
                dataset_parts.append(section)
            except (json.JSONDecodeError, Exception):
                pass
    
    # 扫描 persist/ 目录
    from app.tenant_context import get_uploads_dir
    persist_dir = os.path.join(str(get_uploads_dir()), task_id, "captures", "persist")
    persisted_var_parts: list[str] = []
    
    if os.path.isdir(persist_dir):
        for fpath in sorted(glob.glob(os.path.join(persist_dir, "*.parquet"))):
            vname = os.path.splitext(os.path.basename(fpath))[0]
            try:
                import pyarrow.parquet as pq
                pf = pq.ParquetFile(fpath)
                num_rows = pf.metadata.num_rows
                schema = pf.schema_arrow
                col_names = [schema.field(i).name for i in range(len(schema))]
                col_preview = ", ".join(f"`{c}`" for c in col_names[:8])
                if len(col_names) > 8:
                    col_preview += f", ... ({len(col_names)} cols)"
                persisted_var_parts.append(
                    f"- `{vname}` — DataFrame ({num_rows} rows) [{col_preview}]"
                )
            except Exception:
                persisted_var_parts.append(f"- `{vname}` — (unable to read)")
    
    # 合并 variable_reference
    all_var_parts = []
    if var_ref_parts:
        all_var_parts.append("**Datasets (preloaded):**")
        all_var_parts.extend(var_ref_parts)
    if persisted_var_parts:
        all_var_parts.append("")
        all_var_parts.append("**Intermediate variables:**")
        all_var_parts.extend(persisted_var_parts)
    
    dataset_context = "\n".join(dataset_parts)
    if not dataset_parts:
        dataset_context = "[No datasets uploaded yet.]"
    
    text_context = "\n\n".join(text_parts) if text_parts else "[No reference documents.]"
    variable_reference = "\n".join(all_var_parts) if all_var_parts else "[No datasets or variables available.]"
    
    return dataset_context, text_context, variable_reference, data_var_map


async def _get_skill_context(db: AsyncSession) -> tuple[str, dict[str, str]]:
    """
    获取所有激活的 Skill 上下文
    Returns: (skill_prompt, skill_envs)
    """
    result = await db.execute(
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

async def _get_warehouse_context(db: AsyncSession) -> str:
    """获取 DuckDB Warehouse 上下文"""
    from app.models import DuckDBTable
    
    result = await db.execute(
        select(DuckDBTable)
        .where(DuckDBTable.status != "error")
        .order_by(DuckDBTable.updated_at.desc())
        .limit(20)
    )
    tables = list(result.scalars().all())
    
    if not tables:
        return (
            "The local DuckDB warehouse is empty. You can use `materialize_to_duckdb` "
            "to save cleaned DataFrames as persistent tables."
        )
    
    lines = ["The following tables exist in the local DuckDB warehouse:\n"]
    for t in tables:
        try:
            schema = json.loads(t.table_schema_json) if t.table_schema_json else []
        except (json.JSONDecodeError, TypeError):
            schema = []
        col_preview = ", ".join(f"`{s['name']}`" for s in schema[:8])
        if len(schema) > 8:
            col_preview += f", ... ({len(schema)} cols)"
        
        lines.append(
            f"- **{t.table_name}** — {t.display_name} ({t.row_count:,} rows)\n"
            f"  Columns: {col_preview}"
        )
    
    return "\n".join(lines)

def format_sop_context(sop_name: str, sop_markdown: str) -> str:
    """
    将 SOP 格式化为 system prompt 注入段。
    
    这是一个纯函数，供 context_builder 和 analyst_agent 共用。
    """
    return f"""## Routine Execution Contract

This task is a **routine analysis** bound to a formal Standard Operating Procedure (SOP).

**Execution Rules:**
1. Follow the SOP steps strictly and in order
2. Do NOT improvise alternative analysis workflows beyond the SOP
3. If required inputs are missing or ambiguous, STOP and explain what is needed
4. Use only the data sources provided in this context
5. Output results in the format specified by the SOP
6. If a step fails, report the failure clearly rather than guessing alternatives

## Bound SOP: {sop_name}

{sop_markdown}

---
"""

async def _get_sop_context_if_routine(task_id: str, db: AsyncSession) -> str | None:
    """如果 task 是 routine 类型且绑定了 SOP asset，返回格式化的 SOP 上下文"""
    from app.models import Task, Asset
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task or task.task_type != "routine" or not task.asset_id:
        return None
    asset = await db.get(Asset, task.asset_id)
    if not asset or asset.asset_type != "sop" or not asset.content_markdown:
        return None
    return format_sop_context(asset.name, asset.content_markdown)

async def build_agent_context_bundle(
    task_id: str,
    db: AsyncSession,
    mode: str = "analyst",
    current_task: str = "[Context building]",
    is_first_turn: bool = False,
    include_viz_examples: bool = False,
    profile: PromptProfile | None = None,  # 新增参数
) -> dict:
    """
    统一的 Agent 上下文构建入口（运行时使用）
    
    Args:
        profile: 执行环境 profile。如果为 None,则根据 Task.execution_backend 自动解析
    
    Returns:
        {
            "dataset_context": str,
            "text_context": str,
            "variable_reference": str,
            "data_var_map": dict[str, str],
            "skill_context": str,
            "skill_envs": dict[str, str],
            "sop_context": str | None,
            "system_prompt": str,
            "profile": PromptProfile,  # 新增返回值
        }
    """
    # ── 自动解析 profile（如果未提供） ──────────────────
    if profile is None:
        from app.models import Task
        from sqlalchemy import select
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        backend_type = task.execution_backend if task else "local"
        profile = resolve_prompt_profile(backend_type)
    
    # 获取各类上下文
    dataset_ctx, text_ctx, var_ref, data_var_map = await _get_knowledge_context_with_assets(task_id, db)
    skill_ctx, skill_envs = await _get_skill_context(db)
    # warehouse_ctx = await _get_warehouse_context(db)
    sop_ctx = await _get_sop_context_if_routine(task_id, db)
    
    # 构建 system prompt（传入 profile）
    if mode == "plan":
        from app.prompts.plan import build_plan_system_prompt
        system_prompt = build_plan_system_prompt(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
            skill_context=skill_ctx,
            # warehouse_context=warehouse_ctx,
            is_first_turn=is_first_turn,
            include_viz_examples=include_viz_examples,
            profile=profile,  # 传入 profile
        )
    else:  # analyst / auto
        from app.prompts.analyst import build_analyst_system_prompt
        system_prompt = build_analyst_system_prompt(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
            skill_context=skill_ctx,
            current_task=current_task,
            # warehouse_context=warehouse_ctx,
            include_viz_examples=include_viz_examples,
            profile=profile,  # 传入 profile
        )
        if sop_ctx:
            system_prompt = sop_ctx + "\n\n" + system_prompt
    
    return {
        "dataset_context": dataset_ctx,
        "text_context": text_ctx,
        "variable_reference": var_ref,
        "data_var_map": data_var_map,
        "skill_context": skill_ctx,
        "skill_envs": skill_envs,
        # "warehouse_context": warehouse_ctx,
        "sop_context": sop_ctx,
        "system_prompt": system_prompt,
        "profile": profile,  # 新增返回值
    }

async def build_task_context_snapshot(
    task_id: str,
    db: AsyncSession,
    mode: str = "analyst",
    include_viz_examples: bool = False,
    profile: PromptProfile | None = None,  # 新增参数
) -> dict:
    """
    构建 Task 的完整上下文快照（不依赖 LLM 配置）
    
    Args:
        profile: 执行环境 profile。如果为 None,则根据 Task.execution_backend 自动解析
    
    Returns:
        {
            "dataset_context": str,
            "text_context": str,
            "variable_reference": str,
            "skill_context": str,
            "system_prompt": str,
            "profile": PromptProfile,  # 新增返回值
        }
    """
    # ── 自动解析 profile（如果未提供） ──────────────────
    if profile is None:
        from app.models import Task
        from sqlalchemy import select
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        backend_type = task.execution_backend if task else "local"
        profile = resolve_prompt_profile(backend_type)
    
    # 获取 Knowledge 上下文
    dataset_ctx, text_ctx, var_ref = await _get_knowledge_context(task_id, db)
    
    # 获取 Skill 上下文
    skill_ctx, _ = await _get_skill_context(db)
    
    # 获取 Warehouse 上下文
    # warehouse_ctx = await _get_warehouse_context(db)

    # 检测 routine task 的 SOP
    sop_ctx = await _get_sop_context_if_routine(task_id, db)

    # 构建 system prompt（根据 mode + profile）
    if mode == "plan":
        from app.prompts.plan import build_plan_system_prompt
        system_prompt = build_plan_system_prompt(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
            skill_context=skill_ctx,
            # warehouse_context=warehouse_ctx,
            is_first_turn=False,
            include_viz_examples=include_viz_examples,
            profile=profile,
        )
    else:  # analyst / auto
        from app.prompts.analyst import build_analyst_system_prompt
        system_prompt = build_analyst_system_prompt(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
            skill_context=skill_ctx,
            current_task="[Context size estimation]",
            # warehouse_context=warehouse_ctx,
            include_viz_examples=include_viz_examples,
            profile=profile,
        )
        if sop_ctx:
            system_prompt = sop_ctx + "\n\n" + system_prompt

    
    return {
        "dataset_context": dataset_ctx,
        "text_context": text_ctx,
        "variable_reference": var_ref,
        "skill_context": skill_ctx,
        # "warehouse_context": warehouse_ctx,
        "system_prompt": system_prompt,
        "profile": profile,  # 新增返回值
    }