# backend/app/models.py

"""SQLAlchemy ORM 数据模型"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联关系，级联删除
    knowledge_items: Mapped[list["Knowledge"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    steps: Mapped[list["Step"]] = relationship(back_populates="task", cascade="all, delete-orphan")


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
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'user' or 'assistant'
    # 在 role 字段之后添加
    step_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="assistant_message"
    )  # 'user_message' | 'tool_use' | 'assistant_message'

    content: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_output: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 格式
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped["Task"] = relationship(back_populates="steps")