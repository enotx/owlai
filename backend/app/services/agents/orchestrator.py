# backend/app/services/agents/orchestrator.py

"""AgentOrchestrator - 多Agent调度器"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI

from app.services.agents.plan_agent import PlanAgent
from app.services.agents.analyst_agent import AnalystAgent
from app.services.agents.task_manager_agent import TaskManagerAgent


class AgentOrchestrator:
    """Agent调度器 - 根据Task.mode选择执行流程"""
    
    def __init__(
        self,
        task_id: str,
        db: AsyncSession,
        model_override: tuple[str, str] | None = None,
    ):
        """
        初始化Orchestrator
        
        Args:
            task_id: 任务ID
            db: 数据库会话
            model_override: 用户显式指定的模型 (provider_id, model_id)，优先级高于数据库配置
        """
        self.task_id = task_id
        self.db = db
        self.model_override = model_override
    
    async def _get_agent_config(self, agent_type: str) -> tuple[AsyncOpenAI, str]:
        """
        获取指定Agent类型的LLM配置
        
        优先级：
        1. 用户显式指定的model_override（如果存在）
        2. 数据库中该agent_type的配置
        3. 数据库中default agent的配置
        
        Args:
            agent_type: Agent类型 ('plan' | 'analyst' | 'task_manager')
        
        Returns:
            (client, model_id) 元组
        
        Raises:
            ValueError: 如果配置不存在
        """
        from app.models import LLMProvider
        from sqlalchemy import select
        
        # 优先级1：用户显式指定
        if self.model_override:
            provider_id, model_id = self.model_override
            
            # 查询Provider信息
            result = await self.db.execute(
                select(LLMProvider).where(LLMProvider.id == provider_id)
            )
            provider = result.scalar_one_or_none()
            
            if not provider:
                raise ValueError(f"Provider {provider_id} not found")
            
            # 创建客户端
            client = AsyncOpenAI(
                api_key=provider.api_key or "",
                base_url=provider.base_url,
            )
            
            return client, model_id
        
        # 优先级2 & 3：数据库配置
        from app.services.agent import _get_client_from_db
        
        result = await _get_client_from_db(self.db, agent_type)
        if result is None:
            # 回退到default配置
            result = await _get_client_from_db(self.db, "default")
            if result is None:
                raise ValueError(
                    f"No LLM configuration found for '{agent_type}' agent. "
                    "Please configure it in Settings → Agents."
                )
        
        return result
    
    async def run(
        self,
        mode: str,
        user_message: str,
        context: dict | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        根据模式调度Agent
        
        Args:
            mode: 'auto' | 'plan' | 'analyst'
            user_message: 用户输入
            context: 额外上下文
        """
        context = context or {}
        context["user_message"] = user_message
        
        if mode == "plan":
            try:
                client, model = await self._get_agent_config("plan")
            except ValueError as e:
                yield self._sse({"type": "error", "content": str(e)})
                return
            
            agent = PlanAgent(self.task_id, self.db, client, model)
            async for event in agent.run(context):
                yield event
        
        elif mode == "analyst":
            try:
                client, model = await self._get_agent_config("analyst")
            except ValueError as e:
                yield self._sse({"type": "error", "content": str(e)})
                return
            
            agent = AnalystAgent(self.task_id, self.db, client, model)
            async for event in agent.run(context):
                yield event
        
        elif mode == "auto":
            complexity = await self._assess_complexity(user_message)
            
            if complexity == "complex":
                yield self._sse({
                    "type": "mode_switch",
                    "from": "auto",
                    "to": "plan",
                    "reason": "Detected complex analysis requirements",
                })
                
                try:
                    client, model = await self._get_agent_config("plan")
                except ValueError as e:
                    yield self._sse({"type": "error", "content": str(e)})
                    return
                
                agent = PlanAgent(self.task_id, self.db, client, model)
            else:
                try:
                    client, model = await self._get_agent_config("analyst")
                except ValueError as e:
                    yield self._sse({"type": "error", "content": str(e)})
                    return
                
                agent = AnalystAgent(self.task_id, self.db, client, model)
            
            async for event in agent.run(context):
                yield event
        
        else:
            yield self._sse({"type": "error", "content": f"Unknown mode: {mode}"})
    
    async def _assess_complexity(self, user_message: str) -> str:
        """
        评估任务复杂度
        Returns: 'simple' | 'complex'
        """
        from app.models import Knowledge
        from sqlalchemy import select, func
        
        result = await self.db.execute(
            select(func.count(Knowledge.id)).where(Knowledge.task_id == self.task_id)
        )
        knowledge_count = result.scalar() or 0
        
        # TODO: 现在的keyword匹配也太蠢了，可以考虑引入一个小模型来评估复杂度
        complex_keywords = [
            "多个", "multiple", "关联", "join", "merge", "combine",
            "对比", "compare", "趋势", "trend", "预测", "predict",
            "分类", "classify", "聚类", "cluster", "思路", "brainstorm" , "give me some ideas"
        ]
        
        has_complex_keyword = any(kw in user_message.lower() for kw in complex_keywords)
        
        if knowledge_count > 2 or has_complex_keyword:
            return "complex"
        else:
            return "simple"
    
    def _sse(self, data: dict) -> str:
        """生成SSE事件"""
        import json
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"