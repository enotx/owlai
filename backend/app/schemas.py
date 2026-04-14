# backend/app/schemas.py

"""Pydantic 请求/响应数据模型"""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


# ===== Task =====
class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    task_type: str = Field(default="ad_hoc", pattern="^(ad_hoc|script|pipeline|routine)$")
    asset_id: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class TaskResponse(BaseModel):
    id: str
    title: str
    description: str | None
    mode: str  # 'auto', 'plan', 'analyst'
    plan_confirmed: bool
    current_subtask_id: str | None
    created_at: datetime
    updated_at: datetime
    task_type: str 
    asset_id: str | None  
    last_run_at: datetime | None  
    last_run_status: str | None  
    compact_context: str | None  
    compact_anchor_step_id: str | None  
    compact_anchor_created_at: datetime | None  
    model_config = {"from_attributes": True}


# ===== Knowledge =====
class KnowledgeResponse(BaseModel):
    id: str
    task_id: str
    type: str
    name: str
    file_path: str | None
    metadata_json: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ===== Step / Chat =====
class ModelOverride(BaseModel):
    """用户显式指定的模型配置"""
    provider_id: str
    model_id: str

class ChatRequest(BaseModel):
    task_id: str
    message: str = Field(..., min_length=1)
    mode: str | None = Field(None, pattern="^(auto|plan|analyst)$")  # 可选的模式
    model_override: ModelOverride | None = None  # 用户显式指定的模型

class StepResponse(BaseModel):
    id: str
    task_id: str
    subtask_id: str | None
    role: str
    step_type: str
    content: str
    code: str | None
    code_output: str | None
    created_at: datetime
    model_config = {"from_attributes": True}

# ===== Code Execution =====
class ExecuteRequest(BaseModel):
    task_id: str
    code: str = Field(..., min_length=1)


class ExecuteResponse(BaseModel):
    success: bool
    output: str | None = None
    error: str | None = None
    execution_time: float = 0.0


# ===== Health =====
class HealthResponse(BaseModel):
    status: str
    message: str

# ===== LLM Provider =====
class LLMModelItem(BaseModel):
    """单个模型配置"""
    id: str = Field(..., min_length=1)  # 模型 ID，如 "gpt-4"
    name: str = Field(..., min_length=1)  # 显示名称，如 "GPT-4"


class LLMProviderCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=255)
    base_url: str = Field(..., min_length=1, max_length=500)
    api_key: str | None = None
    models: list[LLMModelItem] = Field(default_factory=list)


class LLMProviderUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=255)
    base_url: str | None = Field(None, min_length=1, max_length=500)
    api_key: str | None = None
    models: list[LLMModelItem] | None = None


class LLMProviderResponse(BaseModel):
    id: str
    display_name: str
    base_url: str
    api_key: str | None
    models: list[LLMModelItem]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LLMTestConnectionRequest(BaseModel):
    base_url: str = Field(..., min_length=1)
    api_key: str | None = None


class LLMTestConnectionResponse(BaseModel):
    success: bool
    message: str
    available_models: list[str] = Field(default_factory=list)

# ===== Agent Config =====
class AgentConfigUpdate(BaseModel):
    """更新 Agent 配置"""
    provider_id: str | None = None
    model_id: str | None = None

class AgentConfigResponse(BaseModel):
    """Agent 配置响应"""
    id: str
    agent_type: str
    provider_id: str | None
    model_id: str | None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

# ===== SubTask =====
class SubTaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    order: int = Field(..., ge=1)


class SubTaskCreate(SubTaskBase):
    task_id: str


class SubTaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = Field(None, pattern="^(pending|running|completed|failed)$")
    result: str | None = None


class SubTaskResponse(SubTaskBase):
    id: str
    task_id: str
    status: str  # 'pending', 'running', 'completed', 'failed'
    result: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ===== Task Mode & Plan =====
class TaskModeUpdate(BaseModel):
    """切换Task的执行模式"""
    mode: str = Field(..., pattern="^(auto|plan|analyst)$")


class SubTaskListResponse(BaseModel):
    """SubTask列表响应（用于Plan展示）"""
    subtasks: list[SubTaskResponse]
    total: int

class PlanConfirmation(BaseModel):
    """Plan确认请求(带SubTask数据)"""
    confirmed: bool
    subtasks: list[SubTaskCreate] | None = None  # 用户确认时必须提供
    modifications: str | None = None  # 用户拒绝时提供修改建议


# ===== Chat with Mode =====
class ChatRequestWithMode(BaseModel):
    """带模式选择的聊天请求"""
    task_id: str
    message: str = Field(..., min_length=1)
    mode: str | None = Field(None, pattern="^(auto|plan|analyst)$")  # 可选，用于切换模式
    agent_config_id: str | None = None  # 可选，指定使用的AgentConfig

# ===== Database Management =====
class DBCompatibilityResponse(BaseModel):
    """数据库兼容性检查响应"""
    compatible: bool
    exists: bool
    issues: list[str]
    db_path: str
class DBRecreateResponse(BaseModel):
    """数据库重建响应"""
    success: bool
    message: str


# ===== Skill =====
class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    prompt_markdown: str | None = None
    reference_markdown: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    allowed_modules: list[str] = Field(default_factory=list)
    is_active: bool = True
    is_system: bool = False
    slash_command: str | None = None
    handler_type: str | None = Field(default="standard", pattern="^(standard|custom_handler)$")
    handler_config: dict[str, Any] | None = None  # 会被序列化为 JSON



class SkillUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    prompt_markdown: str | None = None
    reference_markdown: str | None = None
    env_vars: dict[str, str] | None = None
    allowed_modules: list[str] | None = None
    is_active: bool | None = None
    is_system: bool | None = None
    slash_command: str | None = Field(None, max_length=50)
    handler_type: str | None = Field(None, pattern="^(standard|custom_handler)$")
    handler_config: dict[str, Any] | None = None


class SkillResponse(BaseModel):
    id: str
    name: str
    description: str | None
    prompt_markdown: str | None
    reference_markdown: str | None
    env_vars: dict[str, str]
    allowed_modules: list[str]
    is_active: bool
    is_system: bool
    slash_command: str | None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
    handler_type: str
    handler_config: dict[str, Any] | None


# ===== Visualization =====
class VisualizationResponse(BaseModel):
    id: str
    task_id: str
    subtask_id: str | None
    step_id: str | None
    title: str
    chart_type: str
    option_json: str  # 前端自行 JSON.parse
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

# ===== DuckDB Table =====
class DuckDBTableResponse(BaseModel):
    id: str
    table_name: str
    display_name: str
    description: str | None
    table_schema_json: str
    row_count: int
    source_type: str
    source_config: str | None
    pipeline_id: str | None
    data_updated_at: datetime | None
    latest_data_date: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DuckDBTablePreviewResponse(BaseModel):
    columns: list[str]
    rows: list[dict]
    total_rows: int


# ===== Data Pipeline =====
class DataPipelineCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    source_type: str
    source_config: str = "{}"
    transform_code: str
    transform_description: str | None = None
    target_table_name: str = Field(..., min_length=1, max_length=255)
    write_strategy: str = Field(default="replace", pattern="^(replace|append|upsert)$")
    upsert_key: str | None = None
    output_schema: str | None = None
    is_auto: bool = False
    freshness_policy: str = Field(default='{"type": "none"}')


class DataPipelineResponse(BaseModel):
    id: str
    name: str
    description: str | None
    source_task_id: str | None
    source_type: str
    source_config: str
    transform_code: str
    transform_description: str | None
    target_table_name: str
    write_strategy: str
    upsert_key: str | None
    output_schema: str | None
    is_auto: bool
    freshness_policy_json: str
    status: str
    last_run_at: datetime | None
    last_run_status: str | None
    last_run_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

# ===== Asset =====
class AssetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    asset_type: str = Field(..., pattern="^(script|sop)$")
    source_task_id: str | None = None
    
    # Script 字段
    code: str | None = None
    script_type: str | None = Field(None, pattern="^(general|pipeline)$")
    env_vars: dict[str, str] = Field(default_factory=dict)
    allowed_modules: list[str] = Field(default_factory=list)
    
    # SOP 字段
    content_markdown: str | None = None
class AssetUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    code: str | None = None
    env_vars: dict[str, str] | None = None
    allowed_modules: list[str] | None = None
    content_markdown: str | None = None
class AssetResponse(BaseModel):
    id: str
    name: str
    description: str | None
    asset_type: str
    source_task_id: str | None
    
    # Script 字段
    code: str | None
    script_type: str | None
    env_vars: dict[str, str]
    allowed_modules: list[str]
    
    # SOP 字段
    content_markdown: str | None
    
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
    
    @classmethod
    def from_orm(cls, obj):
        """自定义 ORM 转换，处理 JSON 字段"""
        import json
        data = {
            "id": obj.id,
            "name": obj.name,
            "description": obj.description,
            "asset_type": obj.asset_type,
            "source_task_id": obj.source_task_id,
            "code": obj.code,
            "script_type": obj.script_type,
            "env_vars": json.loads(obj.env_vars_json) if obj.env_vars_json else {},
            "allowed_modules": json.loads(obj.allowed_modules_json) if obj.allowed_modules_json else [],
            "content_markdown": obj.content_markdown,
            "created_at": obj.created_at,
            "updated_at": obj.updated_at,
        }
        return cls(**data)

class RunAssetRequest(BaseModel):
    """执行资产的请求"""
    user_message: str | None = None
    env_vars_override: dict[str, str] | None = None
    data_source_ids: list[str] | None = None  # Knowledge 或 DuckDB table IDs
