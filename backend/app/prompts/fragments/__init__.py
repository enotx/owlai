# backend/app/prompts/fragments/__init__.py
"""Prompt 片段：可被多个 Agent 复用的公共文本块"""
from app.prompts.fragments.common_rules import COMMON_RULES
from app.prompts.fragments.data_conventions import DATAFRAME_NAMING_CONVENTION
from app.prompts.fragments.execution_profiles import (
    PromptProfile,
    LOCAL_PROFILE,
    JUPYTER_PROFILE,
    resolve_prompt_profile,
)

__all__ = [
    "COMMON_RULES",
    "DATAFRAME_NAMING_CONVENTION",
    "build_visualization_guide",
    "PromptProfile",
    "LOCAL_PROFILE",
    "JUPYTER_PROFILE",
    "resolve_prompt_profile",
]


# ── 可视化指南：渐进式披露 ──────────────────────────────────
from app.prompts.fragments.echarts_guide import ECHARTS_RULES, ECHARTS_EXAMPLES
from app.prompts.fragments.map_guide import MAP_RULES, MAP_EXAMPLES
_VIZ_KEYWORDS = frozenset({
    # English
    "chart", "plot", "graph", "visualiz", "diagram", "bar chart", "line chart",
    "pie chart", "heatmap", "histogram", "scatter", "funnel", "radar",
    "map", "geographic", "location", "latitude", "longitude", "spatial",
    "coordinates", "geograph",
    # Chinese
    "图表", "可视化", "画图", "柱状图", "折线图", "饼图", "散点图",
    "热力图", "漏斗图", "雷达图", "地图", "经纬度", "坐标", "分布图",
    "门店分布", "地理",
})

def needs_viz_examples(*texts: str) -> bool:
    """关键词检测：任意文本中是否包含可视化相关词汇"""
    combined = " ".join(t for t in texts if t).lower()
    return any(kw in combined for kw in _VIZ_KEYWORDS)

def build_visualization_guide(*, include_examples: bool = False) -> str:
    """组装可视化指南：Rules 永远包含，Examples 按需包含"""
    parts = [ECHARTS_RULES, MAP_RULES]
    if include_examples:
        parts.append(ECHARTS_EXAMPLES)
        parts.append(MAP_EXAMPLES)
    return "\n\n".join(parts)
