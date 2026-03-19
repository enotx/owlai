# backend/app/tools/registry.py

"""
按 Agent 类型 + 上下文条件，组装 tool 列表。
所有 Agent 统一从这里获取自己的 tools，不再自行定义。
"""

from app.tools.definitions import (
    EXECUTE_PYTHON_CODE_TOOL,
    CREATE_VISUALIZATION_TOOL,
)


def get_tools_for_agent(
    agent_type: str,
    *,
    has_datasets: bool = False,
) -> list[dict]:
    """
    返回指定 Agent 类型应使用的 tool 列表。

    Args:
        agent_type: 'plan' | 'analyst' | 'task_manager'
        has_datasets: 是否有数据集（决定是否包含可视化 tool）
    """
    if agent_type == "plan":
        # PlanAgent 只需要探索性代码执行
        return [EXECUTE_PYTHON_CODE_TOOL, CREATE_VISUALIZATION_TOOL]

    elif agent_type == "analyst":
        tools = [EXECUTE_PYTHON_CODE_TOOL, CREATE_VISUALIZATION_TOOL]
        # 有数据集时才提供独立的可视化 tool
        # （即使没有这个 tool，Agent 仍可通过 create_chart() 在沙箱内创建图表）
        if has_datasets:
            tools.append(CREATE_VISUALIZATION_TOOL)
        return tools

    elif agent_type == "task_manager":
        # TaskManager 不执行代码，没有 tools
        return []

    else:
        # 默认：只提供代码执行
        return [EXECUTE_PYTHON_CODE_TOOL]