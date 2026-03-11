# backend/app/services/agents/task_manager_agent.py

"""TaskManagerAgent - 负责流程控制和结果验收"""

from typing import AsyncGenerator, Any
from app.services.agents.base import BaseAgent


class TaskManagerAgent(BaseAgent):
    """TaskManager - 评估SubTask执行结果"""
    
    async def run(self, context: dict[str, Any]) -> AsyncGenerator[str, None]:
        """
        评估SubTask执行结果：
        1. 检查是否达成目标
        2. 决定是否进入下一个SubTask
        
        注：当前版本简化实现，主要由用户手动确认
        """
        subtask_id = context.get("subtask_id")
        
        # TODO: 未来可以让LLM自动评估结果质量
        # 当前版本：直接返回成功，由用户手动确认
        
        yield self._sse({
            "type": "text",
            "content": "SubTask completed. Please review the results.",
        })
        
        yield self._sse({"type": "done"})