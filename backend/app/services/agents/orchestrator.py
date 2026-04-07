# backend/app/services/agents/orchestrator.py

"""AgentOrchestrator - 多Agent调度器"""

import json
import re
import logging
import os

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI

from app.services.agents.plan_agent import PlanAgent
from app.services.agents.analyst_agent import AnalystAgent
from app.services.agents.task_manager_agent import TaskManagerAgent

logger = logging.getLogger(__name__)
# Slash command pattern: /command args...
_SLASH_CMD_PATTERN = re.compile(r"^/(\w+)\s*(.*)", re.DOTALL)
# Pipeline confirm pattern: [Pipeline Confirm] {...}
_PIPELINE_CONFIRM_PATTERN = re.compile(
    r"^\[Pipeline Confirm\]\s*(\{.*\})", re.DOTALL
)


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

        # ── Slash command detection ──────────────────────
        slash_match = _SLASH_CMD_PATTERN.match(user_message.strip())
        if slash_match:
            command = slash_match.group(1).lower()
            args = slash_match.group(2).strip()

            if command == "derive":
                async for chunk in self._handle_derive_command(args, context):
                    yield chunk
                return

            if command == "sop":
                # SOP extraction — placeholder for future
                yield self._sse({
                    "type": "text",
                    "content": "⚠️ `/sop` is not yet implemented. Coming soon!",
                })
                yield self._sse({"type": "done"})
                return

            # Unknown slash command → fall through to normal routing

        # ── Pipeline confirm detection ───────────────────
        confirm_match = _PIPELINE_CONFIRM_PATTERN.match(user_message.strip())
        if confirm_match:
            try:
                config = json.loads(confirm_match.group(1))
            except json.JSONDecodeError:
                yield self._sse({
                    "type": "error",
                    "content": "Invalid pipeline confirmation payload.",
                })
                yield self._sse({"type": "done"})
                return

            if config.get("cancelled"):
                yield self._sse({
                    "type": "text",
                    "content": "Pipeline save cancelled.",
                })
                yield self._sse({"type": "done"})
                return

            async for chunk in self._execute_pipeline_save(config):
                yield chunk
            return
        
        if mode == "plan":
            # 非 auto 模式：关键词兜底判断是否需要可视化示例
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
            # 非 auto 模式：关键词兜底判断是否需要可视化示例
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
    
    async def _classify_intent(self, user_message: str) -> tuple[str, str, bool]:
        """
        使用LLM进行意图识别，判断应使用plan还是analyst模式；以及是否需要可视化示例。
        
        模型选择走 _get_agent_config("misc") 的标准优先级链：
          model_override → misc DB config → default DB config → ValueError
        

        Returns:
            (mode, reason, viz_examples)
        """
        try:
            client, model = await self._get_agent_config("misc")
        except ValueError:
            # 没有任何可用的LLM配置 → 关键词兜底
            mode, reason = self._keyword_fallback(user_message)
            return mode, reason, False
        
        # 收集上下文摘要
        context_summary = await self._get_context_summary()
        
        classification_prompt = f"""You are a task router. Analyze the user's request and return TWO decisions:
**1. mode** — Which agent should handle this?
- **plan**: Complex, multi-step analysis that needs requirement clarification, breaking down into sub-tasks, strategic thinking, or involves multiple datasets.
- **analyst**: Straightforward analysis that can be answered directly with 1-3 code executions, clearly defined without ambiguity.
**2. viz_examples** — Does the request likely involve creating charts, maps, or other visualizations?
- **true**: User explicitly or implicitly wants visual output (charts, plots, maps, geographic analysis, distribution diagrams, trend lines, etc.)
- **false**: User wants numbers, tables, text answers, data exploration, or it's too early to tell.
## Available Context
{context_summary}
## User Message
{user_message}
Respond with ONLY a JSON object, no markdown fences:
{{"mode": "plan" or "analyst", "reason": "one-sentence explanation", "viz_examples": true or false}}"""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": classification_prompt}],
                temperature=0.0,
                max_tokens=8192,
            )
            
            content = (response.choices[0].message.content or "").strip()
            
            # 解析 JSON（兼容 LLM 可能加 markdown fence）
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                result_data = json.loads(json_match.group())
                mode = result_data.get("mode", "analyst")
                reason = result_data.get("reason", "LLM classification")
                viz_examples = bool(result_data.get("viz_examples", False))
                if mode not in ("plan", "analyst"):
                    mode = "analyst"
                return mode, reason, viz_examples
            return "analyst", "Intent classification returned unparseable response; defaulting to analyst", False
        
        except Exception:
            mode, reason = self._keyword_fallback(user_message)
            return mode, reason, False
    
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

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # /derive command: Pipeline extraction flow
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _handle_derive_command(
        self, user_instructions: str, context: dict
    ) -> AsyncGenerator[str, None]:
        """
        /derive 命令处理：
        1. 回溯 Task 历史，收集成功的代码执行
        2. LLM 精炼 pipeline 定义
        3. 沙箱 dry-run 获取 schema + 预览
        4. 抛出 HITL pipeline_confirmation 卡片
        """
        yield self._sse({
            "type": "text",
            "content": "🔍 Analyzing task history to extract a data pipeline...\n",
        })

        # Step 1: Collect successful code history
        code_history = await self._collect_code_history()
        if not code_history:
            yield self._sse({
                "type": "text",
                "content": (
                    "⚠️ No successful code executions found in this task. "
                    "Please run some analysis first, then use `/derive` to save the result."
                ),
            })
            yield self._sse({"type": "done"})
            return

        # Step 2: LLM extracts pipeline
        yield self._sse({
            "type": "text",
            "content": "📝 Extracting pipeline definition...\n",
        })

        knowledge_ctx = ""
        try:
            # Get a minimal knowledge summary for LLM context
            from app.models import Knowledge
            from sqlalchemy import select

            result = await self.db.execute(
                select(Knowledge).where(Knowledge.task_id == self.task_id)
            )
            items = list(result.scalars().all())
            if items:
                parts = []
                for k in items:
                    parts.append(f"- {k.name} (type: {k.type})")
                knowledge_ctx = "Available data:\n" + "\n".join(parts)
        except Exception:
            pass

        pipeline_proposal = await self._extract_pipeline_with_llm(
            code_history, user_instructions, knowledge_ctx
        )
        if pipeline_proposal is None:
            yield self._sse({
                "type": "text",
                "content": (
                    "⚠️ Failed to extract a pipeline from the task history. "
                    "The code may be too complex or fragmented. "
                    "Try running a cleaner analysis first."
                ),
            })
            yield self._sse({"type": "done"})
            return

        # Step 3: Dry-run in sandbox to get real schema
        yield self._sse({
            "type": "text",
            "content": "🧪 Validating pipeline with a dry-run...\n",
        })

        dry_run_result = await self._dry_run_pipeline(pipeline_proposal)

        if dry_run_result is None:
            # Dry-run failed; still show proposal but without schema preview
            logger.warning("Pipeline dry-run failed, showing proposal without preview")
            schema: list[dict] = []
            row_count = 0
            sample_rows: list[dict] = []
        else:
            schema = dry_run_result["schema"]
            row_count = dry_run_result["row_count"]
            sample_rows = dry_run_result["sample_rows"]

        # Step 4: Build HITL confirmation card
        hitl_payload = {
            "hitl_type": "pipeline_confirmation",
            "title": "💾 Save as Derived Data Source",
            "description": pipeline_proposal.get("transform_description", ""),
            "pipeline": {
                "table_name": pipeline_proposal["table_name"],
                "display_name": pipeline_proposal["display_name"],
                "description": pipeline_proposal["description"],
                "source_type": pipeline_proposal["source_type"],
                "source_config": pipeline_proposal.get("source_config", {}),
                "transform_code": pipeline_proposal["transform_code"],
                "transform_description": pipeline_proposal.get(
                    "transform_description", ""
                ),
                "write_strategy": "replace",
                "schema": schema,
                "row_count": row_count,
                "sample_rows": sample_rows[:5],
            },
            "options": [
                {
                    "label": "Confirm & Save",
                    "value": "confirm",
                    "badge": "recommended",
                },
                {"label": "Cancel", "value": "cancel"},
            ],
        }

        # Emit as hitl_request event (agent.py will persist as hitl_request Step)
        yield self._sse({
            "type": "hitl_request",
            "title": hitl_payload["title"],
            "description": hitl_payload["description"],
            "options": hitl_payload["options"],
            # Extra fields for pipeline — stored in code_output via agent.py
            **{k: v for k, v in hitl_payload.items()},
        })
        yield self._sse({"type": "done"})

    async def _collect_code_history(self) -> list[dict]:
        """回溯 Task 历史，收集成功的 tool_use Steps。"""
        from app.models import Step
        from sqlalchemy import select

        result = await self.db.execute(
            select(Step)
            .where(
                Step.task_id == self.task_id,
                Step.step_type == "tool_use",
            )
            .order_by(Step.created_at.asc())
        )
        steps = list(result.scalars().all())

        history = []
        for step in steps:
            if not step.code or not step.code_output:
                continue
            try:
                output_data = json.loads(step.code_output)
            except json.JSONDecodeError:
                continue
            if not output_data.get("success"):
                continue

            history.append({
                "code": step.code,
                "output": output_data.get("output", "")[:2000],
                "purpose": step.content or "",
            })

        return history

    async def _extract_pipeline_with_llm(
        self,
        code_history: list[dict],
        user_instructions: str,
        knowledge_context: str,
    ) -> dict | None:
        """使用 LLM 从代码历史中提取 pipeline 定义。"""
        from app.prompts.pipeline_extraction import (
            PIPELINE_EXTRACTION_SYSTEM,
            build_pipeline_extraction_prompt,
        )

        try:
            client, model = await self._get_agent_config("analyst")
        except ValueError:
            try:
                client, model = await self._get_agent_config("default")
            except ValueError:
                logger.error("No LLM config available for pipeline extraction")
                return None

        user_prompt = build_pipeline_extraction_prompt(
            code_history, user_instructions, knowledge_context
        )

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": PIPELINE_EXTRACTION_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=8192,
            )

            content = (response.choices[0].message.content or "").strip()

            # Parse JSON — handle markdown fences
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if not json_match:
                logger.error("LLM did not return valid JSON for pipeline extraction")
                return None

            proposal = json.loads(json_match.group())

            # Validate required fields
            required = [
                "table_name",
                "display_name",
                "description",
                "source_type",
                "transform_code",
            ]
            for field in required:
                if field not in proposal:
                    logger.error(f"Pipeline proposal missing field: {field}")
                    return None

            # Sanitize table name
            from app.services.warehouse import validate_table_name

            valid, err = validate_table_name(proposal["table_name"])
            if not valid:
                # Try to fix it
                from app.services.warehouse import _sanitize_table_name

                proposal["table_name"] = _sanitize_table_name(
                    proposal["table_name"]
                )

            return proposal

        except Exception as e:
            logger.error(f"Pipeline extraction LLM call failed: {e}")
            return None

    async def _dry_run_pipeline(self, proposal: dict) -> dict | None:
        """
        在沙箱中试运行 transform_code，获取 schema 和预览数据。
        不写入 DuckDB，仅验证代码可执行并获取 df_output 的结构。
        """
        from app.services.sandbox import execute_code_in_sandbox
        from app.services.agents.base import BaseAgent
        from app.config import UPLOADS_DIR

        transform_code = proposal.get("transform_code", "")
        if not transform_code:
            return None

        # Build data_var_map from task knowledge
        from app.models import Knowledge
        from app.services.data_processor import sanitize_variable_name
        from sqlalchemy import select

        data_var_map: dict[str, str] = {}
        result = await self.db.execute(
            select(Knowledge).where(Knowledge.task_id == self.task_id)
        )
        for k in result.scalars().all():
            if k.type in ("csv", "excel") and k.file_path and os.path.exists(
                k.file_path
            ):
                var_name = sanitize_variable_name(k.name)
                data_var_map[var_name] = os.path.abspath(k.file_path)

        # Prepare capture dir
        capture_dir = os.path.join(
            UPLOADS_DIR, self.task_id, "captures", "pipeline_dryrun"
        )
        os.makedirs(capture_dir, exist_ok=True)

        # Also load persisted vars from previous steps
        persist_dir = os.path.join(
            UPLOADS_DIR, self.task_id, "captures", "persist"
        )
        persisted_var_map: dict[str, str] = {}
        if os.path.isdir(persist_dir):
            import glob

            for fpath in glob.glob(os.path.join(persist_dir, "*.parquet")):
                var_name = os.path.splitext(os.path.basename(fpath))[0]
                persisted_var_map[var_name] = fpath
            for fpath in glob.glob(os.path.join(persist_dir, "*.json")):
                var_name = os.path.splitext(os.path.basename(fpath))[0]
                if var_name not in persisted_var_map:
                    persisted_var_map[var_name] = fpath

        # Wrap transform_code to capture df_output info
        wrapped_code = transform_code + "\n\n" + """
# ── Pipeline dry-run: capture df_output metadata ──
import json as _drj
if 'df_output' in dir() and hasattr(df_output, 'shape'):
    _cols = [str(c) for c in df_output.columns.tolist()]
    _dtypes = {str(c): str(df_output[c].dtype) for c in df_output.columns}
    _preview = df_output.head(5)
    _preview_clean = _preview.where(pd.notnull(_preview), None)
    _rows = _drj.loads(_preview_clean.to_json(orient='records', default_handler=str))
    _schema = [{"name": c, "type": _dtypes.get(c, "UNKNOWN")} for c in _cols]
    print("__PIPELINE_DRYRUN__" + _drj.dumps({
        "schema": _schema,
        "row_count": len(df_output),
        "sample_rows": _rows,
    }, ensure_ascii=False))
else:
    print("__PIPELINE_DRYRUN_ERROR__: df_output not found or not a DataFrame")
"""

        # Collect skill envs (needed if pipeline uses skills)
        from app.models import Skill

        skill_result = await self.db.execute(
            select(Skill).where(Skill.is_active == True)
        )
        skill_envs: dict[str, str] = {}
        for skill in skill_result.scalars().all():
            try:
                envs = json.loads(skill.env_vars_json) if skill.env_vars_json else {}
                skill_envs.update(envs)
            except (json.JSONDecodeError, TypeError):
                pass
            try:
                modules = json.loads(skill.allowed_modules_json) if skill.allowed_modules_json else []
                if modules:
                    existing = json.loads(skill_envs.get("__allowed_modules__", "[]"))
                    existing.extend(modules)
                    skill_envs["__allowed_modules__"] = json.dumps(list(set(existing)))
            except (json.JSONDecodeError, TypeError):
                pass

        try:
            exec_result = await execute_code_in_sandbox(
                code=wrapped_code,
                data_var_map=data_var_map,
                timeout=120,
                capture_dir=capture_dir,
                injected_envs=skill_envs if skill_envs else None,
                persisted_var_map=persisted_var_map if persisted_var_map else None,
            )
        except Exception as e:
            logger.error(f"Pipeline dry-run sandbox error: {e}")
            return None

        if not exec_result.get("success"):
            logger.warning(
                f"Pipeline dry-run failed: {exec_result.get('error', 'unknown')}"
            )
            return None

        # Parse dry-run output
        output = exec_result.get("output", "") or ""
        marker = "__PIPELINE_DRYRUN__"
        for line in output.split("\n"):
            if line.startswith(marker):
                try:
                    return json.loads(line[len(marker):])
                except json.JSONDecodeError:
                    pass

        logger.warning("Pipeline dry-run: could not parse df_output metadata")
        return None

    async def _execute_pipeline_save(
        self, config: dict
    ) -> AsyncGenerator[str, None]:
        """
        用户确认后，执行 pipeline 并写入 DuckDB + 注册元数据。
        """
        from app.services.sandbox import execute_code_in_sandbox
        from app.services import warehouse as wh
        from app.models import DuckDBTable, DataPipeline, Knowledge
        from app.database import async_session
        from app.config import UPLOADS_DIR
        from app.services.data_processor import sanitize_variable_name
        from sqlalchemy import select
        from datetime import datetime
        import pandas as pd

        table_name = config.get("table_name", "")
        display_name = config.get("display_name", table_name)
        description = config.get("description", "")
        write_strategy = config.get("write_strategy", "replace")
        transform_code = config.get("transform_code", "")
        source_type = config.get("source_type", "unknown")
        source_config = config.get("source_config", {})

        if not transform_code or not table_name:
            yield self._sse({
                "type": "error",
                "content": "Invalid pipeline configuration: missing transform_code or table_name.",
            })
            yield self._sse({"type": "done"})
            return

        # Validate table name
        valid, err = wh.validate_table_name(table_name)
        if not valid:
            yield self._sse({"type": "error", "content": f"Invalid table name: {err}"})
            yield self._sse({"type": "done"})
            return

        yield self._sse({
            "type": "text",
            "content": f"⚙️ Executing pipeline and saving to `{table_name}`...\n",
        })

        # Build data_var_map
        data_var_map: dict[str, str] = {}
        result = await self.db.execute(
            select(Knowledge).where(Knowledge.task_id == self.task_id)
        )
        for k in result.scalars().all():
            if k.type in ("csv", "excel") and k.file_path and os.path.exists(
                k.file_path
            ):
                var_name = sanitize_variable_name(k.name)
                data_var_map[var_name] = os.path.abspath(k.file_path)

        capture_dir = os.path.join(
            UPLOADS_DIR, self.task_id, "captures", "pipeline_exec"
        )
        os.makedirs(capture_dir, exist_ok=True)

        # Load persisted vars
        persist_dir = os.path.join(
            UPLOADS_DIR, self.task_id, "captures", "persist"
        )
        persisted_var_map: dict[str, str] = {}
        if os.path.isdir(persist_dir):
            import glob

            for fpath in glob.glob(os.path.join(persist_dir, "*.parquet")):
                var_name = os.path.splitext(os.path.basename(fpath))[0]
                persisted_var_map[var_name] = fpath
            for fpath in glob.glob(os.path.join(persist_dir, "*.json")):
                var_name = os.path.splitext(os.path.basename(fpath))[0]
                if var_name not in persisted_var_map:
                    persisted_var_map[var_name] = fpath

        # Wrap code to persist df_output as parquet
        output_parquet = os.path.join(
            capture_dir, "__pipeline_output.parquet"
        ).replace("\\", "\\\\")
        wrapped = transform_code + f"""

# ── Pipeline: persist df_output ──
if 'df_output' in dir() and hasattr(df_output, 'to_parquet'):
    df_output.to_parquet("{output_parquet}", engine='pyarrow', index=False)
    print(f"__PIPELINE_OK__ rows={{len(df_output)}}")
else:
    print("__PIPELINE_ERROR__: df_output not found")
"""

        # Collect skill envs
        from app.models import Skill

        skill_result = await self.db.execute(
            select(Skill).where(Skill.is_active == True)
        )
        skill_envs: dict[str, str] = {}
        for skill in skill_result.scalars().all():
            try:
                envs = json.loads(skill.env_vars_json) if skill.env_vars_json else {}
                skill_envs.update(envs)
            except (json.JSONDecodeError, TypeError):
                pass
            try:
                modules = json.loads(skill.allowed_modules_json) if skill.allowed_modules_json else []
                if modules:
                    existing = json.loads(skill_envs.get("__allowed_modules__", "[]"))
                    existing.extend(modules)
                    skill_envs["__allowed_modules__"] = json.dumps(list(set(existing)))
            except (json.JSONDecodeError, TypeError):
                pass

        try:
            exec_result = await execute_code_in_sandbox(
                code=wrapped,
                data_var_map=data_var_map,
                timeout=300,
                capture_dir=capture_dir,
                injected_envs=skill_envs if skill_envs else None,
                persisted_var_map=persisted_var_map if persisted_var_map else None,
            )
        except Exception as e:
            yield self._sse({
                "type": "error",
                "content": f"Pipeline execution failed: {str(e)}",
            })
            yield self._sse({"type": "done"})
            return

        if not exec_result.get("success"):
            yield self._sse({
                "type": "text",
                "content": (
                    f"❌ Pipeline execution failed:\n```\n"
                    f"{exec_result.get('error', 'Unknown error')}\n```\n\n"
                    "Please fix the analysis in chat and try `/derive` again."
                ),
            })
            yield self._sse({"type": "done"})
            return

        # Check output marker
        output_text = exec_result.get("output", "") or ""
        if "__PIPELINE_ERROR__" in output_text:
            yield self._sse({
                "type": "text",
                "content": (
                    "❌ Pipeline did not produce `df_output`. "
                    "Make sure your code creates a DataFrame named `df_output`."
                ),
            })
            yield self._sse({"type": "done"})
            return

        # Read the parquet output
        parquet_path = output_parquet.replace("\\\\", "\\")
        if not os.path.exists(parquet_path):
            yield self._sse({
                "type": "error",
                "content": "Pipeline output file not found. Execution may have failed silently.",
            })
            yield self._sse({"type": "done"})
            return

        try:
            import pyarrow.parquet as pq

            df = pq.read_table(parquet_path).to_pandas()
        except Exception as e:
            yield self._sse({
                "type": "error",
                "content": f"Failed to read pipeline output: {str(e)}",
            })
            yield self._sse({"type": "done"})
            return

        if df.empty:
            yield self._sse({
                "type": "text",
                "content": "⚠️ Pipeline produced an empty DataFrame (0 rows). Nothing to save.",
            })
            yield self._sse({"type": "done"})
            return

        # Write to DuckDB
        try:
            wh_result = await wh.async_write_dataframe(
                df, table_name, write_strategy
            )
        except Exception as e:
            yield self._sse({
                "type": "error",
                "content": f"DuckDB write failed: {str(e)}",
            })
            yield self._sse({"type": "done"})
            return

        # Register metadata in SQLite
        try:
            async with async_session() as meta_db:
                # Upsert DuckDBTable
                existing = await meta_db.execute(
                    select(DuckDBTable).where(
                        DuckDBTable.table_name == table_name
                    )
                )
                table_meta = existing.scalar_one_or_none()

                table_schema_json = json.dumps(
                    wh_result["schema"], ensure_ascii=False
                )
                now = datetime.now()

                if table_meta:
                    table_meta.display_name = display_name
                    table_meta.description = description
                    table_meta.table_schema_json = table_schema_json
                    table_meta.row_count = wh_result["total_rows"]
                    table_meta.source_type = source_type
                    table_meta.source_config = json.dumps(
                        source_config, ensure_ascii=False
                    ) if source_config else None
                    table_meta.data_updated_at = now
                    table_meta.status = "ready"
                else:
                    table_meta = DuckDBTable(
                        table_name=table_name,
                        display_name=display_name,
                        description=description,
                        table_schema_json=table_schema_json,
                        row_count=wh_result["total_rows"],
                        source_type=source_type,
                        source_config=json.dumps(
                            source_config, ensure_ascii=False
                        ) if source_config else None,
                        data_updated_at=now,
                        status="ready",
                    )
                    meta_db.add(table_meta)
                await meta_db.flush()

                # Create DataPipeline record
                pipeline = DataPipeline(
                    name=f"Pipeline: {display_name}",
                    description=description,
                    source_task_id=self.task_id,
                    source_type=source_type,
                    source_config=json.dumps(
                        source_config, ensure_ascii=False
                    ) if source_config else "{}",
                    transform_code=transform_code,
                    transform_description=config.get(
                        "transform_description", ""
                    ),
                    target_table_name=table_name,
                    write_strategy=write_strategy,
                    output_schema=table_schema_json,
                    is_auto=False,
                    status="active",
                    last_run_at=now,
                    last_run_status="success",
                )
                meta_db.add(pipeline)
                await meta_db.flush()

                # Link pipeline to table
                table_meta.pipeline_id = pipeline.id

                await meta_db.commit()

        except Exception as e:
            logger.error(f"Pipeline metadata registration failed: {e}")
            # DuckDB write succeeded, metadata failed — not fatal

        # Build success message
        col_count = len(wh_result["schema"])
        col_preview = ", ".join(
            f"`{s['name']}` ({s['type']})" for s in wh_result["schema"][:8]
        )
        if col_count > 8:
            col_preview += f", ... ({col_count} total)"

        success_msg = (
            f"✅ **Data saved successfully!**\n\n"
            f"| Property | Value |\n"
            f"|----------|-------|\n"
            f"| Table | `{table_name}` |\n"
            f"| Rows | {wh_result['total_rows']:,} |\n"
            f"| Columns | {col_count} |\n"
            f"| Strategy | {write_strategy} |\n\n"
            f"**Columns:** {col_preview}\n\n"
            f"You can find this table in the **Data Sources** tab on the right panel. "
            f"To use it in future tasks, click the **+** button to add it to your context."
        )

        yield self._sse({"type": "text", "content": success_msg})
        yield self._sse({"type": "done"})

        # Cleanup temp parquet
        try:
            if os.path.exists(parquet_path):
                os.unlink(parquet_path)
        except OSError:
            pass
        
    def _sse(self, data: dict) -> str:
        """生成SSE事件"""
        import json
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"