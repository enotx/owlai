# backend/app/prompts/analyst.py

"""AnalystAgent 的 system prompt 模板与构建函数"""

from app.prompts.fragments.common_rules import COMMON_RULES
from app.prompts.fragments.data_conventions import DATAFRAME_NAMING_CONVENTION
from app.prompts.fragments import build_visualization_guide

# ── 模板 ──────────────────────────────────────────────────────
# 占位符: {rules}, {naming_convention}, {visualization_guide},
#          {dataset_context}, {text_context}, {variable_reference},
#          {skill_context}, {current_task}

_ANALYST_TEMPLATE = """\
You are **Owl Analyst Agent 🦉**, an expert data analyst executing specific analysis tasks.

## Your Approach
Work step-by-step:
1. **Understand the task** — Read the subtask description carefully
2. **Explore data** — Use `execute_python_code` to inspect data structure
3. **Analyze** — Write code to perform the required analysis
4. **Visualize** — If results benefit from a chart, use `create_chart()` inside `execute_python_code` (see guidelines below)
5. **Verify** — Check results make sense
6. **Summarize** — Present findings clearly with key numbers

{rules}

{naming_convention}

{visualization_guide}

## Available Datasets
{dataset_context}

## Reference Documents
{text_context}

## Variable Reference
{variable_reference}

## Available Skills
{skill_context}

## Current Task
{current_task}\
"""

def build_analyst_system_prompt(
    *,
    dataset_context: str,
    text_context: str,
    variable_reference: str,
    skill_context: str,
    current_task: str,
    include_viz_examples: bool = False,
) -> str:
    """
    构建 AnalystAgent 的 system prompt。
    Args:
        dataset_context: 数据集元数据 + 样本行
        text_context: 文本知识内容
        variable_reference: 变量名对照表
        skill_context: 激活的 Skill 提示词
        current_task: 当前 SubTask 描述
        include_viz_examples: 是否注入完整代码示例
    """
    visualization_guide = build_visualization_guide(
        include_examples=include_viz_examples,
    )
    return _ANALYST_TEMPLATE.format(
        rules=COMMON_RULES,
        naming_convention=DATAFRAME_NAMING_CONVENTION,
        visualization_guide=visualization_guide,
        dataset_context=dataset_context,
        text_context=text_context,
        variable_reference=variable_reference,
        skill_context=skill_context,
        current_task=current_task,
    )
