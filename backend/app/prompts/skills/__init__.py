# backend/app/prompts/skills/__init__.py
"""内置 Skill 定义模块"""
from app.prompts.skills.derive_data_source import get_skill_definition as get_derive_skill
from app.prompts.skills.extract_sop import get_skill_definition as get_sop_skill
def get_builtin_skills() -> list[dict]:
    """
    获取所有内置 Skill 定义
    
    Returns:
        List of skill definition dicts, each containing:
        - name, slash_command, handler_type, handler_config
        - description, prompt_markdown, reference_markdown
        - is_active, is_system
    """
    return [
        get_derive_skill(),
        get_sop_skill(),
    ]
