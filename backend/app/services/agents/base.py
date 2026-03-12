# backend/app/services/agents/base.py

"""Agent基类定义"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Any
import json
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI


class BaseAgent(ABC):
    """所有Agent的抽象基类"""
    
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
        """
        执行Agent逻辑，返回SSE流式输出
        
        Args:
            context: 执行上下文，包含：
                - user_message: 用户输入
                - subtask_id: 当前SubTask ID（可选）
                - knowledge_context: Knowledge上下文（可选）
                - history_messages: 历史消息（可选）
        
        Yields:
            SSE格式的字符串
        """
        if False:  # 永远不会执行，仅用于类型检查
            yield
    
    def _sse(self, data: dict) -> str:
        """生成SSE事件格式"""
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    
    async def _get_knowledge_context(self) -> tuple[str, str, str, dict[str, str]]:
        """
        获取Knowledge上下文
        Returns: (dataset_context, text_context, variable_reference, data_var_map)
        """
        from app.services.data_processor import (
            sanitize_variable_name,
            get_csv_sample_rows,
            get_excel_sample_rows,
            read_text_content,
        )
        from app.models import Knowledge
        from sqlalchemy import select
        import os
        import json
        
        result = await self.db.execute(
            select(Knowledge).where(Knowledge.task_id == self.task_id)
        )
        knowledge_items = list(result.scalars().all())
        
        dataset_parts: list[str] = []
        text_parts: list[str] = []
        var_ref_parts: list[str] = []
        data_var_map: dict[str, str] = {}  # 改名：data_var_map → data_var_map
        
        for k in knowledge_items:
            # ── CSV 处理 ──────────────────────────────────────
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
                                for c in meta["columns"][:10]  # 限制显示列数
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
            
            # ── Excel 处理 ────────────────────────────────────
            elif k.type == "excel" and k.file_path and os.path.exists(k.file_path):
                var_name = sanitize_variable_name(k.name)
                data_var_map[var_name] = os.path.abspath(k.file_path)
                
                section = f"### 📊 {k.name}  →  variable: `{var_name}`\n"
                section += "- **Type**: Excel\n"
                
                # 解析元数据
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
                        
                        # 展示默认 sheet 的详细信息
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
                            
                            # 其他 sheet 的简要信息
                            if len(sheets_data) > 1:
                                other_info = []
                                for sheet_meta in sheets_data[1:]:
                                    s_name = sheet_meta.get("sheet_name", "?")
                                    s_shape = sheet_meta.get("shape", [0, 0])
                                    other_info.append(f"`{s_name}` ({s_shape[0]:,} rows)")
                                section += f"- **Other sheets**: {', '.join(other_info)}\n"
                    
                    except json.JSONDecodeError:
                        pass
                
                # 样本行（默认 sheet）
                try:
                    sample = get_excel_sample_rows(
                        k.file_path, 
                        sheet_name=default_sheet,
                        n_rows=200
                    )
                    if len(sample) > 5000:
                        sample = sample[:5000] + "\n... [sample truncated]"
                    section += f"- **Sample rows** (default sheet):\n```\n{sample}\n```\n"
                except Exception:
                    pass
                
                dataset_parts.append(section)
                var_ref_parts.append(f"- `{var_name}` ← {k.name} (default sheet)")
                if len(sheet_names) > 1:
                    var_ref_parts.append(f"  - `{var_name}_sheets` ← all sheets dictionary")
            
            # ── 文本文件处理 ──────────────────────────────────
            elif k.type in ("text", "backstory") and k.file_path and os.path.exists(k.file_path):
                try:
                    content = read_text_content(k.file_path)
                    text_parts.append(f"### 📄 {k.name}\n{content}")
                except Exception:
                    pass
        
        dataset_context = "\n".join(dataset_parts) if dataset_parts else "[No datasets uploaded yet.]"
        text_context = "\n\n".join(text_parts) if text_parts else "[No reference documents.]"
        variable_reference = "\n".join(var_ref_parts) if var_ref_parts else "[No datasets available.]"
        
        return dataset_context, text_context, variable_reference, data_var_map
    
    async def _get_skill_context(self) -> tuple[str, dict[str, str]]:
        """
        获取所有激活的 Skill 上下文
        Returns:
            skill_prompt: 拼接后的 Skill 提示词（Markdown），注入 System Prompt
            skill_envs:   合并后的环境变量字典（含 __allowed_modules__ 特殊键）
        """
        from app.models import Skill
        from sqlalchemy import select
        import json
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
            # 拼接提示词
            section = f"### 🔧 Skill: {skill.name}\n"
            if skill.description:
                section += f"{skill.description}\n"
            if skill.prompt_markdown:
                section += f"\n{skill.prompt_markdown}\n"
            # 提示 Agent 可以通过 getenv() 获取凭证
            try:
                env_dict: dict[str, str] = json.loads(skill.env_vars_json) if skill.env_vars_json else {}
            except (json.JSONDecodeError, TypeError):
                env_dict = {}
            if env_dict:
                env_keys = ", ".join(f"`{k}`" for k in env_dict.keys())
                section += f"\n> **Available env vars** (use `getenv('KEY')`): {env_keys}\n"
                merged_envs.update(env_dict)
            # 收集额外模块
            try:
                modules: list[str] = json.loads(skill.allowed_modules_json) if skill.allowed_modules_json else []
            except (json.JSONDecodeError, TypeError):
                modules = []
            if modules:
                all_modules.update(modules)
                section += f"> **Allowed imports**: {', '.join(f'`{m}`' for m in modules)}\n"
            prompt_parts.append(section)
        # 将 allowed_modules 打包为特殊 key，由 sandbox 层解析
        if all_modules:
            merged_envs["__allowed_modules__"] = json.dumps(list(all_modules))
        skill_prompt = "\n---\n".join(prompt_parts)
        return skill_prompt, merged_envs
