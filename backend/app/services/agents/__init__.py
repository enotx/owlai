# backend/app/services/agents/__init__.py

"""Multi-Agent协作模块"""

from app.services.agents.base import BaseAgent
from app.services.agents.plan_agent import PlanAgent
from app.services.agents.analyst_agent import AnalystAgent
from app.services.agents.task_manager_agent import TaskManagerAgent
from app.services.agents.orchestrator import AgentOrchestrator
from app.services.agents.custom_handlers import (
    handle_derive_pipeline,
    handle_extract_sop,
    handle_extract_script,
)


__all__ = [
    "BaseAgent",
    "PlanAgent",
    "AnalystAgent",
    "TaskManagerAgent",
    "AgentOrchestrator",
]