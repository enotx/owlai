# backend/app/services/agents/analyst_agent.py

"""AnalystAgent - 负责执行具体分析任务"""

from typing import AsyncGenerator, Any
import re

from app.services.agents.base import BaseAgent
from app.prompts import build_analyst_system_prompt
from app.tools import get_tools_for_agent

from sqlalchemy import select

import logging
logger = logging.getLogger(__name__)


class AnalystAgent(BaseAgent):
    """Analyst 模式 Agent - 执行具体分析"""
    
    async def run(self, context: dict[str, Any]) -> AsyncGenerator[str, None]:
        """执行分析任务"""
        
        # ── Custom handler 路由（优先于标准流程） ──
        handler_type = context.get("invoked_skill_handler_type")
        if handler_type == "custom_handler":
            # 导入 custom handlers 模块
            from app.services.agents.custom_handlers import (
                handle_derive_pipeline,
                handle_extract_sop,
                handle_extract_script,
            )
            
            handler_config = context.get("invoked_skill_handler_config", {})
            handler_name = handler_config.get("handler_name")
            
            if handler_name == "derive_pipeline":
                async for chunk in handle_derive_pipeline(self, context, handler_config):
                    yield chunk
                return
            elif handler_name == "extract_sop":
                async for chunk in handle_extract_sop(self, context, handler_config):
                    yield chunk
                return
            elif handler_name == "extract_script":
                async for chunk in handle_extract_script(self, context, handler_config):
                    yield chunk
                return
            else:
                yield self._sse({
                    "type": "error",
                    "content": f"Unknown custom handler: {handler_name}",
                })
                yield self._sse({"type": "done"})
                return
        
        # ── 标准分析流程 ──
        user_message = self._safe_str(context, "user_message")
        
        # 获取上下文
        dataset_ctx, text_ctx, var_ref, data_var_map = await self._get_knowledge_context()
        skill_ctx, skill_envs = await self._get_skill_context()
        warehouse_context = await self._build_warehouse_context()
        
        # 构建 current_task 描述
        current_task = "[Direct analysis mode]"
        invoked_skill_name = context.get("invoked_skill_name")
        if invoked_skill_name:
            current_task = f"Using skill: {invoked_skill_name}"
        
        # 处理 slash command 显式指定的 skill
        if invoked_skill_name:
            invoked_prompt = context.get("invoked_skill_prompt", "")
            is_active = context.get("invoked_skill_is_active", False)
            
            emphasized_section = (
                f"## ⚡ User-Invoked Skill: {invoked_skill_name}\n"
                f"**The user has explicitly requested to use this skill. "
                f"Prioritize its instructions and capabilities for this task.**\n\n"
                f"{invoked_prompt}"
            )
            
            if is_active:
                # skill 已经在 _get_skill_context() 的结果中 → 去重
                if skill_ctx and skill_ctx != "[No skills configured.]":
                    sections = skill_ctx.split("\n---\n")
                    filtered = [
                        s for s in sections
                        if f"### 🔧 Skill: {invoked_skill_name}" not in s
                    ]
                    other_skills = "\n---\n".join(filtered) if filtered else ""
                    if other_skills and other_skills.strip():
                        skill_ctx = emphasized_section + "\n---\n" + other_skills
                    else:
                        skill_ctx = emphasized_section
                else:
                    skill_ctx = emphasized_section
            else:
                # skill 是 inactive → 不在 _get_skill_context() 结果中，直接追加
                if skill_ctx and skill_ctx != "[No skills configured.]":
                    skill_ctx = emphasized_section + "\n---\n" + skill_ctx
                else:
                    skill_ctx = emphasized_section
        
        # 构建 system prompt
        include_viz_examples = context.get("include_viz_examples", False)
        system_prompt = build_analyst_system_prompt(
            dataset_context=dataset_ctx,
            text_context=text_ctx,
            variable_reference=var_ref,
            skill_context=skill_ctx,
            current_task=current_task,  # ← 修复：添加缺失的参数
            warehouse_context=warehouse_context,
            include_viz_examples=include_viz_examples,
        )

        # ── SOP 注入（routine task） ──
        # 检查 context 中是否标记了 routine 任务
        # 如果是，从 Task.asset_id 加载 SOP 并注入到 system prompt 前部
        sop_context = await self._get_sop_context()
        if sop_context:
            system_prompt = sop_context + "\n\n" + system_prompt
            # routine 模式下覆盖 current_task 描述
            current_task = "[Routine analysis — follow the SOP strictly]"

        
        # 加载历史
        history = context.get("history_messages", [])
        
        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_message},
        ]
        
        # 准备沙箱环境
        extra_skill_envs = context.get("extra_skill_envs")
        sandbox_env = await self._prepare_sandbox_env(
            capture_subdir="",
            extra_skill_envs=extra_skill_envs,
        )
        
        # 获取工具列表
        agent_tools = get_tools_for_agent("analyst")
        
        # 运行 ReAct 循环
        async for event in self._run_react_loop(
            messages=messages,
            tools=agent_tools,
            sandbox_env=sandbox_env,
            context=context,
            max_rounds=10,
            temperature=0.4,
        ):
            yield event
        
        yield self._sse({"type": "done"})

    async def _get_sop_context(self) -> str | None:
        """
        如果当前 Task 是 routine 类型且绑定了 SOP，返回格式化 SOP 上下文。
        非 routine task 返回 None。
        """
        from app.models import Task, Asset
        from app.services.context_builder import format_sop_context
        result = await self.db.execute(
            select(Task).where(Task.id == self.task_id)
        )
        task = result.scalar_one_or_none()
        if not task or task.task_type != "routine" or not task.asset_id:
            return None
        asset = await self.db.get(Asset, task.asset_id)
        if not asset or asset.asset_type != "sop" or not asset.content_markdown:
            return None
        return format_sop_context(asset.name, asset.content_markdown)
