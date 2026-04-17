# backend/app/services/agents/plan_agent.py

"""PlanAgent - 负责需求澄清和数据准备评估"""

from typing import AsyncGenerator, Any
import json
import re

from app.services.agents.base import BaseAgent
from app.prompts import build_plan_system_prompt
from app.services.context_builder import build_agent_context_bundle
from app.tools import get_tools_for_agent

import logging
logger = logging.getLogger(__name__)


class PlanAgent(BaseAgent):
    """Plan 模式 Agent - 需求澄清和数据准备评估"""
    
    async def run(self, context: dict[str, Any]) -> AsyncGenerator[str, None]:
        """执行 Plan 流程"""
        
        user_message = self._safe_str(context, "user_message")
        history = context.get("history_messages", [])
        
        # 判断是否是第一轮对话
        conversation_turns = len([m for m in history if m["role"] in ("user", "assistant")])
        include_viz_examples = context.get("include_viz_examples", False)
        
        # 使用统一的 context builder
        context_bundle = await build_agent_context_bundle(
            task_id=self.task_id,
            db=self.db,
            mode="plan",
            current_task="",
            is_first_turn=(conversation_turns == 0),
            include_viz_examples=include_viz_examples,
        )
        
        system_prompt = context_bundle["system_prompt"]
        data_var_map = context_bundle["data_var_map"]
        skill_envs = context_bundle["skill_envs"]
                
        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_message},
        ]
        
        # 准备沙箱环境
        sandbox_env = self._build_sandbox_env_from_bundle(
            data_var_map=data_var_map,
            skill_envs=skill_envs,
            capture_subdir="plan",
        )

        
        # 获取工具列表
        plan_tools = get_tools_for_agent("plan")
        
        # 运行 ReAct 循环
        async for event in self._run_react_loop(
            messages=messages,
            tools=plan_tools,
            sandbox_env=sandbox_env,
            context=context,
            max_rounds=5,  # Plan 阶段限制轮次
            temperature=0.3,
        ):
            yield event
        
        yield self._sse({"type": "done"})
    
    async def _on_text_complete(
        self,
        text_content: str,
        messages: list,
        context: dict,
    ) -> tuple[list[str], list, bool]:
        """
        Plan Agent 的文本完成钩子：检查是否包含 Plan JSON
        """
        plan_data = self._extract_plan_json(text_content)
        
        if plan_data:
            # 检查是否是错误（被拦截的 Plan）
            if plan_data.get("error") == "premature_plan":
                # 发送警告，要求重新思考
                warning_event = self._sse({
                    "type": "text",
                    "content": f"\n\n⚠️ {plan_data['message']}\n\n",
                })
                
                # 注入警告消息，让模型重新回答
                extra_messages = [
                    {"role": "assistant", "content": text_content},
                    {
                        "role": "user",
                        "content": (
                            f"⚠️ System Warning: {plan_data['message']}\n\n"
                            "Please continue the conversation to address this issue before generating a plan."
                        ),
                    },
                ]
                
                return [warning_event], extra_messages, True  # 继续循环
            
            # 正常的 Plan
            plan_event = self._sse({
                "type": "plan_generated",
                "plan": plan_data,
            })
            
            return [plan_event], [], False  # 不继续循环
        
        # 没有 Plan JSON，正常结束
        return [], [], False
    
    def _extract_plan_json(self, text: str) -> dict | None:
        """从文本中提取并验证 JSON 格式的 Plan"""
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                plan_data = json.loads(json_match.group(1))
                
                # 基本格式检查
                if not plan_data.get("plan_ready") or "subtasks" not in plan_data:
                    return None
                
                # 验证前置条件
                prerequisites = plan_data.get("prerequisites_met", {})
                
                if not prerequisites.get("requirements_clear"):
                    return {
                        "error": "premature_plan",
                        "message": "Requirements are not yet clear. Please continue clarifying with the user.",
                    }
                
                if not prerequisites.get("data_sufficient"):
                    return {
                        "error": "premature_plan",
                        "message": "Data availability has not been confirmed. Please assess data readiness first.",
                    }
                
                return plan_data
                
            except json.JSONDecodeError:
                pass
        
        return None