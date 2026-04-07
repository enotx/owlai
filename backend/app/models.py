# backend/app/models.py

"""SQLAlchemy ORM 数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, func, Integer, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # 新增：多Agent协作字段
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="analyst")  # 'auto', 'plan', 'analyst'
    plan_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # Plan是否已确认
    current_subtask_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # 当前执行的SubTask ID
    
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联关系，级联删除
    knowledge_items: Mapped[list["Knowledge"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    steps: Mapped[list["Step"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    subtasks: Mapped[list["SubTask"]] = relationship(back_populates="task", cascade="all, delete-orphan", order_by="SubTask.order")
    visualizations: Mapped[list["Visualization"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class SubTask(Base):
    """子任务模型，用于Plan模式的任务分拆"""
    __tablename__ = "subtasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False)  # 执行顺序，从1开始
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # 'pending', 'running', 'completed', 'failed'
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON格式存储执行结果
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联关系
    task: Mapped["Task"] = relationship(back_populates="subtasks")
    steps: Mapped[list["Step"]] = relationship(back_populates="subtask", cascade="all, delete-orphan")


class Knowledge(Base):
    __tablename__ = "knowledge"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'csv', 'text', 'backstory'
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 格式存储
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped["Task"] = relationship(back_populates="knowledge_items")


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    
    # 新增：关联SubTask（可选，向后兼容）
    subtask_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("subtasks.id", ondelete="CASCADE"), nullable=True)
    
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'user' or 'assistant'
    step_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="assistant_message"
    )  # 'user_message' | 'tool_use' | 'assistant_message'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_output: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 格式
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    task: Mapped["Task"] = relationship(back_populates="steps")
    subtask: Mapped["SubTask | None"] = relationship(back_populates="steps")


class LLMProvider(Base):
    """LLM Provider 配置表"""
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 可选，支持通过 header 管理
    models_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON 数组：[{"id": "gpt-4", "name": "GPT-4"}]
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AgentConfig(Base):
    """Agent 模型配置表"""
    __tablename__ = "agent_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)  # 'default', 'plan', 'analyst', 'task_manager'
    provider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 模型的 id，如 "gpt-4"
    
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    
    provider: Mapped["LLMProvider | None"] = relationship()

class Skill(Base):
    """
    动态扩展技能模型
    - prompt_markdown: 给 Agent 看的使用说明（Markdown 格式）
    - env_vars_json: 运行时注入沙箱的环境变量 {"KEY": "VALUE"}
    - allowed_modules_json: 该技能需要额外放行的 Python 模块 ["pytalos"]
    """
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    env_vars_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    allowed_modules_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class Visualization(Base):
    """ECharts 可视化配置表"""
    __tablename__ = "visualizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    subtask_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("subtasks.id", ondelete="SET NULL"), nullable=True)
    step_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("steps.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    chart_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'bar','line','pie','scatter','radar','heatmap','boxplot','funnel'
    option_json: Mapped[str] = mapped_column(Text, nullable=False)  # 完整 ECharts option JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    task: Mapped["Task"] = relationship(back_populates="visualizations")

class DuckDBTable(Base):
    """DuckDB 仓库中的表元数据（注册在 SQLite 中）"""
    __tablename__ = "duckdb_tables"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    table_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)  # DuckDB 实际表名
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Schema 快照
    table_schema_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON: [{"name":"col","type":"VARCHAR"},...]
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 数据血缘 & 依赖
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    # "csv_upload" | "api" | "datasource" | "pipeline" | "manual" | "unknown"
    source_config: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: 依赖描述
    pipeline_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("data_pipelines.id", ondelete="SET NULL"), nullable=True
    )

    # 数据时效
    data_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    latest_data_date: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 状态
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    # "ready" | "stale" | "refreshing" | "error"

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    pipeline: Mapped["DataPipeline | None"] = relationship(back_populates="target_table", foreign_keys=[pipeline_id])


class DataPipeline(Base):
    """数据管道定义"""
    __tablename__ = "data_pipelines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 来源追踪
    source_task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )

    # Pipeline 定义
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # "api" | "csv" | "upload" | "datasource"
    source_config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    transform_code: Mapped[str] = mapped_column(Text, nullable=False)
    transform_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 目标
    target_table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    write_strategy: Mapped[str] = mapped_column(String(20), nullable=False, default="replace")
    # "replace" | "append" | "upsert"
    upsert_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_schema: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON

    # 执行特性
    is_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 状态
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # "draft" | "active" | "paused" | "error"
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_run_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    target_table: Mapped["DuckDBTable | None"] = relationship(
        back_populates="pipeline", foreign_keys="[DuckDBTable.pipeline_id]"
    )