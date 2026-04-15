# backend/app/services/context_builder.py
"""上下文构建服务 - 独立于 Agent 实例的上下文拼装逻辑"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Task, Knowledge, Skill
from app.prompts.analyst import build_analyst_system_prompt
from app.prompts.plan import build_plan_system_prompt
from app.services.data_processor import (
    sanitize_variable_name,
    get_csv_sample_rows,
    get_excel_sample_rows,
    read_text_content,
)
from app.config import UPLOADS_DIR
import os
import json
import glob


async def build_task_context_snapshot(
    task_id: str,
    db: AsyncSession,
    mode: str = "analyst",
    include_viz_examples: bool = False,
) -> dict:
    """
    构建 Task 的完整上下文快照（不依赖 LLM 配置）
    
    Returns:
        {
            "dataset_context": str,
            "text_context": str,
            "variable_reference": str,
            "skill_context": str,
            "warehouse_context": str,
            "system_prompt": str,
        }
    """
    # 获取 Knowledge 上下文
    dataset_ctx, text_ctx, var_ref = await _get_knowledge_context(task_id, db)
    
    # 获取 Skill 上下文
    skill_ctx = await _get_skill_context(db)
    
    # 获取 Warehouse 上下文
    warehouse_ctx = await _get_warehouse_context(db)

    # ── 新增：检测 routine task 的 SOP ──
    sop_ctx = await _get_sop_context_if_routine(task_id, db)

    # 构建 system prompt（根据 mode）
    if mode == "plan":
        system_prompt = build_plan_system_prompt(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
            skill_context=skill_ctx,
            warehouse_context=warehouse_ctx,
            is_first_turn=False,
            include_viz_examples=include_viz_examples,
        )
    else:  # analyst / auto
        system_prompt = build_analyst_system_prompt(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
            skill_context=skill_ctx,
            current_task="[Context size estimation]",
            warehouse_context=warehouse_ctx,
            include_viz_examples=include_viz_examples,
        )
        if sop_ctx:
            system_prompt = sop_ctx + "\n\n" + system_prompt

    
    return {
        "dataset_context": dataset_ctx,
        "text_context": text_ctx,
        "variable_reference": var_ref,
        "skill_context": skill_ctx,
        "warehouse_context": warehouse_ctx,
        "system_prompt": system_prompt,
    }


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
    persist_dir = os.path.join(UPLOADS_DIR, task_id, "captures", "persist")
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


async def _get_skill_context(db: AsyncSession) -> str:
    """获取 Skill 上下文"""
    result = await db.execute(
        select(Skill).where(Skill.is_active == True)
    )
    skills = list(result.scalars().all())
    if not skills:
        return "[No skills configured.]"
    
    prompt_parts: list[str] = []
    for skill in skills:
        section = f"### 🔧 Skill: {skill.name}\n"
        if skill.description:
            section += f"{skill.description}\n"
        if skill.prompt_markdown:
            section += f"\n{skill.prompt_markdown}\n"
        prompt_parts.append(section)
    
    return "\n---\n".join(prompt_parts)


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
