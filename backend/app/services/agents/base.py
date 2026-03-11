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
        Returns: (dataset_context, text_context, variable_reference, csv_var_map)
        """
        from app.services.data_processor import (
            sanitize_variable_name,
            get_csv_sample_rows,
            read_text_content,
        )
        from app.models import Knowledge
        from sqlalchemy import select
        import os
        
        result = await self.db.execute(
            select(Knowledge).where(Knowledge.task_id == self.task_id)
        )
        knowledge_items = list(result.scalars().all())
        
        dataset_parts: list[str] = []
        text_parts: list[str] = []
        var_ref_parts: list[str] = []
        csv_var_map: dict[str, str] = {}
        
        for k in knowledge_items:
            if k.type == "csv" and k.file_path and os.path.exists(k.file_path):
                var_name = sanitize_variable_name(k.name)
                csv_var_map[var_name] = os.path.abspath(k.file_path)
                
                section = f"### 📊 {k.name}  →  variable: `{var_name}`\n"
                if k.metadata_json:
                    try:
                        meta = json.loads(k.metadata_json)
                        shape = meta.get("shape", [0, 0])
                        section += f"- **Shape**: {shape[0]:,} rows × {shape[1]} columns\n"
                        if "columns" in meta and "dtypes" in meta:
                            col_info = ", ".join(
                                f"`{c}` ({meta['dtypes'].get(c, '?')})"
                                for c in meta["columns"]
                            )
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
            
            elif k.type in ("text", "backstory") and k.file_path and os.path.exists(k.file_path):
                try:
                    content = read_text_content(k.file_path)
                    text_parts.append(f"### 📄 {k.name}\n{content}")
                except Exception:
                    pass
        
        dataset_context = "\n".join(dataset_parts) if dataset_parts else "[No datasets uploaded yet.]"
        text_context = "\n\n".join(text_parts) if text_parts else "[No reference documents.]"
        variable_reference = "\n".join(var_ref_parts) if var_ref_parts else "[No datasets available.]"
        
        return dataset_context, text_context, variable_reference, csv_var_map