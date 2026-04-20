# backend/app/services/agents/orchestrator.py

"""AgentOrchestrator - 多Agent调度器"""

import json
import re
import logging

from typing import AsyncGenerator, Any
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI

from app.services.agents.plan_agent import PlanAgent
from app.services.agents.analyst_agent import AnalystAgent
from app.models import Skill

logger = logging.getLogger(__name__)

# Slash command: /command args...
_SLASH_CMD_PATTERN = re.compile(r"^/(\w+)\s*(.*)", re.DOTALL)

# Generic confirm pattern: [Derive Confirm] {...} / [Pipeline Confirm] {...}
_CONFIRM_PATTERN = re.compile(r"^\[([\w\s]+?)\s+Confirm\]\s*(\{.*\})", re.DOTALL)
_CONFIRM_SKILL_MAP: dict[str, str] = {
    "derive": "derive",
    "pipeline": "derive",
    "script": "script",
    "sop": "sop",
}


class AgentOrchestrator:
    """Agent调度器 - 根据Task.mode选择执行流程"""
    
    def __init__(
        self,
        task_id: str,
        db: AsyncSession,
        model_override: tuple[str, str] | None = None,
    ):
        self.task_id = task_id
        self.db = db
        self.model_override = model_override
    
    async def _get_agent_config(self, agent_type: str) -> tuple[AsyncOpenAI, str]:
        """获取指定Agent类型的LLM配置"""
        from app.models import LLMProvider
        from sqlalchemy import select
        
        if self.model_override:
            provider_id, model_id = self.model_override
            result = await self.db.execute(
                select(LLMProvider).where(LLMProvider.id == provider_id)
            )
            provider = result.scalar_one_or_none()
            if not provider:
                raise ValueError(f"Provider {provider_id} not found")
            client = AsyncOpenAI(
                api_key=provider.api_key or "",
                base_url=provider.base_url,
            )
            return client, model_id
        
        from app.services.agent import _get_client_from_db
        result = await _get_client_from_db(self.db, agent_type)
        if result is None:
            result = await _get_client_from_db(self.db, "default")
            if result is None:
                raise ValueError(
                    f"No LLM configuration found for '{agent_type}' agent. "
                    "Please configure it in Settings → Agents."
                )
        return result

    async def run_events(
        self,
        mode: str,
        user_message: str,
        context: dict | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """根据模式调度Agent（事件原生版）"""
        context = context or {}
        context["user_message"] = user_message

        # ── 1. Confirm 消息路由（HITL 回调） ──
        confirm_match = _CONFIRM_PATTERN.match(user_message.strip())
        if confirm_match:
            confirm_type = confirm_match.group(1).strip().lower()
            target_command = _CONFIRM_SKILL_MAP.get(confirm_type)
            if target_command:
                from sqlalchemy import select as sa_select
                skill_result = await self.db.execute(
                    sa_select(Skill).where(Skill.slash_command == target_command)
                )
                matched_skill = skill_result.scalar_one_or_none()
                if matched_skill:
                    async for event in self._invoke_skill_events(
                        matched_skill, user_message, context
                    ):
                        yield event
                    return

        # ── 2. Slash command 路由 ──
        slash_match = _SLASH_CMD_PATTERN.match(user_message.strip())
        if slash_match:
            command = slash_match.group(1).lower()
            slash_args = slash_match.group(2).strip()

            from sqlalchemy import select as sa_select
            skill_result = await self.db.execute(
                sa_select(Skill).where(Skill.slash_command == command)
            )
            matched_skill = skill_result.scalar_one_or_none()

            if matched_skill:
                async for event in self._invoke_skill_events(
                    matched_skill, slash_args, context
                ):
                    yield event
                return

        # ── 3. 标准模式路由 ──
        if mode == "plan":
            if context is None:
                context = {}

            if "include_viz_examples" not in context:
                from app.prompts.fragments import needs_viz_examples
                context["include_viz_examples"] = needs_viz_examples(user_message)

            try:
                client, model = await self._get_agent_config("plan")
            except ValueError as e:
                yield {"type": "error", "content": str(e)}
                return

            agent = PlanAgent(self.task_id, self.db, client, model)
            async for event in agent.run_events(context):
                yield event

        elif mode == "analyst":
            if context is not None and "include_viz_examples" not in context:
                from app.prompts.fragments import needs_viz_examples
                context["include_viz_examples"] = needs_viz_examples(user_message)

            try:
                client, model = await self._get_agent_config("analyst")
            except ValueError as e:
                yield {"type": "error", "content": str(e)}
                return

            agent = AnalystAgent(self.task_id, self.db, client, model)
            async for event in agent.run_events(context):
                yield event

        elif mode == "auto":
            target_mode, reason, viz_examples = await self._classify_intent(user_message)
            context["include_viz_examples"] = viz_examples

            if target_mode == "plan":
                yield {
                    "type": "mode_switch",
                    "from": "auto",
                    "to": "plan",
                    "reason": reason,
                }
                try:
                    client, model = await self._get_agent_config("plan")
                except ValueError as e:
                    yield {"type": "error", "content": str(e)}
                    return
                agent = PlanAgent(self.task_id, self.db, client, model)
            else:
                try:
                    client, model = await self._get_agent_config("analyst")
                except ValueError as e:
                    yield {"type": "error", "content": str(e)}
                    return
                agent = AnalystAgent(self.task_id, self.db, client, model)

            async for event in agent.run_events(context):
                yield event
        else:
            yield {"type": "error", "content": f"Unknown mode: {mode}"}

    async def run(
        self,
        mode: str,
        user_message: str,
        context: dict | None = None,
    ) -> AsyncGenerator[str, None]:
        """兼容层：包装 run_events() 为 SSE 字符串输出"""
        if context is None:
            context = {}

        async for event in self.run_events(mode, user_message, context):
            yield self._sse(event)


        # ── 1. Confirm 消息路由（HITL 回调） ──
        confirm_match = _CONFIRM_PATTERN.match(user_message.strip())
        if confirm_match:
            confirm_type = confirm_match.group(1).strip().lower()
            print(f"Confirm message matched: confirm_type={confirm_type}, raw={user_message[:300]!r}")
            target_command = _CONFIRM_SKILL_MAP.get(confirm_type)
            if target_command:
                from sqlalchemy import select as sa_select
                skill_result = await self.db.execute(
                    sa_select(Skill).where(Skill.slash_command == target_command)
                )
                matched_skill = skill_result.scalar_one_or_none()
                if matched_skill:
                    async for chunk in self._invoke_skill(
                        matched_skill, user_message, context
                    ):
                        yield chunk
                    return

        # ── 2. Slash command 路由 ──
        slash_match = _SLASH_CMD_PATTERN.match(user_message.strip())
        if slash_match:
            command = slash_match.group(1).lower()
            slash_args = slash_match.group(2).strip()
            
            from sqlalchemy import select as sa_select
            skill_result = await self.db.execute(
                sa_select(Skill).where(Skill.slash_command == command)
            )
            matched_skill = skill_result.scalar_one_or_none()
            
            if matched_skill:
                async for chunk in self._invoke_skill(
                    matched_skill, slash_args, context
                ):
                    yield chunk
                return
        
        # ── 3. 标准模式路由 ──
        if mode == "plan":
            if "include_viz_examples" not in context:
                from app.prompts.fragments import needs_viz_examples
                context["include_viz_examples"] = needs_viz_examples(user_message)
            
            try:
                client, model = await self._get_agent_config("plan")
            except ValueError as e:
                yield self._sse({"type": "error", "content": str(e)})
                return
            
            agent = PlanAgent(self.task_id, self.db, client, model)
            async for event in agent.run(context):
                yield event
        
        elif mode == "analyst":
            if "include_viz_examples" not in context:
                from app.prompts.fragments import needs_viz_examples
                context["include_viz_examples"] = needs_viz_examples(user_message)

            try:
                client, model = await self._get_agent_config("analyst")
            except ValueError as e:
                yield self._sse({"type": "error", "content": str(e)})
                return
            
            agent = AnalystAgent(self.task_id, self.db, client, model)
            async for event in agent.run(context):
                yield event
        
        elif mode == "auto":
            target_mode, reason, viz_examples = await self._classify_intent(user_message)
            context["include_viz_examples"] = viz_examples
            
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
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Skill invocation
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _invoke_skill(
        self,
        skill: Skill,
        user_instructions: str,
        context: dict,
    ) -> AsyncGenerator[str, None]:
        """兼容层"""
        async for event in self._invoke_skill_events(skill, user_instructions, context):
            yield self._sse(event)

    async def _invoke_skill_events(
        self,
        skill: Skill,
        user_instructions: str,
        context: dict,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """统一的 Skill 调用入口（事件原生版）"""
        # 复用 _invoke_skill 的 context 准备逻辑
        handler_type = "standard"
        handler_config: dict = {}
        try:
            if skill.handler_type:
                handler_type = skill.handler_type
            if skill.handler_config:
                handler_config = json.loads(skill.handler_config)
        except (json.JSONDecodeError, AttributeError):
            pass

        context["invoked_skill_name"] = skill.name
        context["invoked_skill_prompt"] = skill.prompt_markdown or ""
        context["invoked_skill_reference"] = skill.reference_markdown or ""
        context["invoked_skill_is_active"] = skill.is_active
        context["invoked_skill_handler_type"] = handler_type
        context["invoked_skill_handler_config"] = handler_config

        try:
            env_dict = json.loads(skill.env_vars_json) if skill.env_vars_json else {}
        except (json.JSONDecodeError, TypeError):
            env_dict = {}

        extra_envs = dict(env_dict)
        try:
            modules = json.loads(skill.allowed_modules_json) if skill.allowed_modules_json else []
            if modules:
                extra_envs["__allowed_modules__"] = json.dumps(modules)
        except (json.JSONDecodeError, TypeError):
            pass
        context["extra_skill_envs"] = extra_envs

        if handler_type == "custom_handler":
            context["user_message"] = user_instructions
        else:
            enhanced_message = (
                f"[Using skill: {skill.name}]\n\n"
                f"{user_instructions or 'Please use this skill to help me.'}"
            )
            context["user_message"] = enhanced_message

        from app.prompts.fragments import needs_viz_examples
        context["include_viz_examples"] = needs_viz_examples(
            context["user_message"]
        )

        try:
            client, model = await self._get_agent_config("analyst")
        except ValueError as e:
            yield {"type": "error", "content": str(e)}
            return

        agent = AnalystAgent(self.task_id, self.db, client, model)
        async for event in agent.run_events(context):
            yield event

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Intent classification (修正版)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    async def _classify_intent(self, user_message: str) -> tuple[str, str, bool]:
        """使用LLM进行意图识别（收紧 plan 门槛）"""
        try:
            client, model = await self._get_agent_config("misc")
        except ValueError:
            mode, reason = self._keyword_fallback(user_message)
            return mode, reason, False
        
        context_summary = await self._get_context_summary()
        
        classification_prompt = f"""You are a task router. Analyze the user's request and return TWO decisions:

**1. mode** — Which agent should handle this?
- **analyst**: The DEFAULT choice. Use for:
  - Direct data analysis questions (even if multi-step)
  - Exploratory data analysis
  - Statistical calculations
  - Data visualization requests
  - Questions that can be answered through code execution
  - ANY request where the user has clear intent and sufficient data
  
- **plan**: ONLY use when:
  - User explicitly asks for help planning or breaking down a complex project
  - Requirements are genuinely unclear and need structured clarification
  - Data availability is uncertain and needs systematic assessment
  - User asks "how should I approach this?" or "help me plan"
  
**IMPORTANT**: Default to 'analyst' unless there's strong evidence the user needs planning help.

**2. viz_examples** — Does the request likely involve creating charts, maps, or other visualizations?
- **true**: User explicitly or implicitly wants visual output
- **false**: User wants numbers, tables, text answers, or it's too early to tell

## Available Context
{context_summary}

## User Message
{user_message}

Respond with ONLY a JSON object, no markdown fences:
{{"mode": "analyst" or "plan", "reason": "one-sentence explanation", "viz_examples": true or false}}"""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": classification_prompt}],
                temperature=0.0,
                max_tokens=8192,
            )
            content = (response.choices[0].message.content or "").strip()
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                result_data = json.loads(json_match.group())
                mode = result_data.get("mode", "analyst")
                reason = result_data.get("reason", "LLM classification")
                viz_examples = bool(result_data.get("viz_examples", False))
                if mode not in ("plan", "analyst"):
                    mode = "analyst"
                return mode, reason, viz_examples
            return "analyst", "Unparseable response; defaulting to analyst", False
        except Exception:
            mode, reason = self._keyword_fallback(user_message)
            return mode, reason, False
    
    async def _get_context_summary(self) -> str:
        """收集当前 Task 的上下文摘要"""
        from app.models import Knowledge
        from sqlalchemy import select, func
        
        result = await self.db.execute(
            select(func.count(Knowledge.id)).where(Knowledge.task_id == self.task_id)
        )
        knowledge_count = result.scalar() or 0
        
        result = await self.db.execute(
            select(Knowledge.type, func.count(Knowledge.id))
            .where(Knowledge.task_id == self.task_id)
            .group_by(Knowledge.type)
        )
        type_counts = {row[0]: row[1] for row in result.all()}
        
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
        """关键词兜底分类（收紧 plan 关键词）"""
        # 只有真正需要规划的关键词才触发 plan
        plan_keywords = [
            "help me plan", "how should i approach", "break down",
            "what's the best way to", "guide me through",
            "帮我规划", "如何着手", "分解任务", "最佳方案",
        ]
        
        msg_lower = user_message.lower()
        matched = [kw for kw in plan_keywords if kw in msg_lower]
        if matched:
            return "plan", f"Keyword match: {', '.join(matched[:2])}"
        
        # 默认走 analyst
        return "analyst", "Default to analyst for direct analysis"
    
    def _sse(self, data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"