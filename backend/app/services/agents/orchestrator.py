# backend/app/services/agents/orchestrator.py

"""AgentOrchestrator - 多Agent调度器"""

import json
import re


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
            target_mode, reason = await self._classify_intent(user_message)
            
            if target_mode == "plan":
                yield self._sse({
                    "type": "mode_switch",
                    "from": "auto",
                    "to": "plan",
                    "reason": reason,
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
    
    async def _classify_intent(self, user_message: str) -> tuple[str, str]:
        """
        使用LLM进行意图识别，判断应使用plan还是analyst模式。
        
        模型选择走 _get_agent_config("misc") 的标准优先级链：
          model_override → misc DB config → default DB config → ValueError
        
        Returns:
            (mode, reason) — mode: 'plan' | 'analyst'
        """
        try:
            client, model = await self._get_agent_config("misc")
        except ValueError:
            # 没有任何可用的LLM配置 → 关键词兜底
            return self._keyword_fallback(user_message)
        
        # 收集上下文摘要
        context_summary = await self._get_context_summary()
        
        classification_prompt = f"""You are a task router. Classify the user's request into one of two modes:

**plan**: Complex, multi-step analysis that needs:
- Requirement clarification or scoping
- Breaking down into multiple sub-tasks
- Strategic thinking about approach
- Broad/vague questions that need discussion first
- Requests involving multiple datasets or cross-analysis

**analyst**: Straightforward analysis that can be:
- Answered directly with 1-3 code executions
- Clearly defined without ambiguity
- Simple queries, calculations, visualizations, or explorations
- Follow-up questions on previous results

## Available Context
{context_summary}

## User Message
{user_message}

Respond with ONLY a JSON object, no markdown fences:
{{"mode": "plan" or "analyst", "reason": "one-sentence explanation"}}"""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": classification_prompt}],
                temperature=0.0,
                max_tokens=120,
            )
            
            content = (response.choices[0].message.content or "").strip()
            
            # 解析 JSON（兼容 LLM 可能加 markdown fence）
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                result_data = json.loads(json_match.group())
                mode = result_data.get("mode", "analyst")
                reason = result_data.get("reason", "LLM classification")
                if mode not in ("plan", "analyst"):
                    mode = "analyst"
                return mode, reason
            
            return "analyst", "Intent classification returned unparseable response; defaulting to analyst"
        
        except Exception:
            return self._keyword_fallback(user_message)
    
    async def _get_context_summary(self) -> str:
        """收集当前 Task 的上下文摘要，供意图分类使用"""
        from app.models import Knowledge
        from sqlalchemy import select, func
        
        result = await self.db.execute(
            select(func.count(Knowledge.id)).where(Knowledge.task_id == self.task_id)
        )
        knowledge_count = result.scalar() or 0
        
        # 按类型统计
        result = await self.db.execute(
            select(Knowledge.type, func.count(Knowledge.id))
            .where(Knowledge.task_id == self.task_id)
            .group_by(Knowledge.type)
        )
        type_counts = {row[0]: row[1] for row in result.all()}
        
        # 知识名称列表（最多取10条）
        result = await self.db.execute(
            select(Knowledge.name, Knowledge.type)
            .where(Knowledge.task_id == self.task_id)
            .limit(10)
        )
        items = [f"- {row.name} ({row.type})" for row in result.all()]
        
        lines = [f"Total knowledge items: {knowledge_count}"]
        if type_counts:
            lines.append(f"By type: {type_counts}")
        if items:
            lines.append("Items:\n" + "\n".join(items))
        
        return "\n".join(lines) if lines else "No knowledge items uploaded yet."
    
    def _keyword_fallback(self, user_message: str) -> tuple[str, str]:
        """关键词兜底分类（无LLM可用时使用）"""
        complex_keywords = [
            "多个", "multiple", "关联", "join", "merge", "combine",
            "对比", "compare", "趋势", "trend", "预测", "predict",
            "分类", "classify", "聚类", "cluster", "思路", "brainstorm",
            "give me some ideas", "分析方案", "分析计划", "怎么分析",
            "how to analyze", "help me plan",
        ]
        
        msg_lower = user_message.lower()
        matched = [kw for kw in complex_keywords if kw in msg_lower]
        
        if matched:
            return "plan", f"Keyword match: {', '.join(matched[:3])}"
        return "analyst", "No complex indicators detected"

    def _sse(self, data: dict) -> str:
        """生成SSE事件"""
        import json
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"