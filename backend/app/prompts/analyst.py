# backend/app/prompts/analyst.py

# backend/app/prompts/analyst.py

"""AnalystAgent 的 system prompt 模板与构建函数"""

from app.prompts.fragments.common_rules import COMMON_RULES
from app.prompts.fragments.data_conventions import DATAFRAME_NAMING_CONVENTION
from app.prompts.fragments import build_visualization_guide
from app.prompts.fragments.execution_profiles import PromptProfile, LOCAL_PROFILE


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

{common_rules}

{execution_rules}

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

# ## Local Data Warehouse (DuckDB)
# {warehouse_context}

def _assemble_execution_rules(profile: PromptProfile) -> str:
    """组装执行环境相关的规则片段"""
    return "\n\n".join([
        profile.sandbox_rules,
        profile.data_access_guide,
        profile.env_var_guide,
        profile.warehouse_guide,
        profile.persistence_guide,
        profile.viz_note,
    ])


def build_analyst_system_prompt(
    *,
    dataset_context: str,
    text_context: str,
    variable_reference: str,
    skill_context: str,
    current_task: str,
    # warehouse_context: str = "",
    include_viz_examples: bool = False,
    profile: PromptProfile = LOCAL_PROFILE,
) -> str:
    """
    构建 AnalystAgent 的 system prompt。
    
    Args:
        profile: 执行环境 profile（默认 LOCAL_PROFILE）
        ... (其他参数不变)
    """
    execution_rules = _assemble_execution_rules(profile)
    visualization_guide = build_visualization_guide(
        include_examples=include_viz_examples,
    )
    
    return _ANALYST_TEMPLATE.format(
        common_rules=COMMON_RULES,
        execution_rules=execution_rules,
        naming_convention=DATAFRAME_NAMING_CONVENTION,
        visualization_guide=visualization_guide,
        dataset_context=dataset_context,
        text_context=text_context,
        variable_reference=variable_reference,
        skill_context=skill_context,
        current_task=current_task,
        # warehouse_context=warehouse_context,
    )