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