# backend/app/prompts/fragments/__init__.py
"""Prompt 片段：可被多个 Agent 复用的公共文本块"""
from app.prompts.fragments.common_rules import COMMON_RULES
from app.prompts.fragments.data_conventions import DATAFRAME_NAMING_CONVENTION
from app.prompts.fragments.echarts_guide import ECHARTS_GUIDE
__all__ = [
    "COMMON_RULES",
    "DATAFRAME_NAMING_CONVENTION",
    "ECHARTS_GUIDE",
]
