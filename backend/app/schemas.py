# backend/app/schemas.py

"""Pydantic 请求/响应数据模型"""

from datetime import datetime
from pydantic import BaseModel, Field


# ===== Task =====
class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class TaskResponse(BaseModel):
    id: str
    title: str
    description: str | None
    created_at: datetime
    updated_at: datetime

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
class ChatRequest(BaseModel):
    task_id: str
    message: str = Field(..., min_length=1)

class StepResponse(BaseModel):
    id: str
    task_id: str
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