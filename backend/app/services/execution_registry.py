# backend/app/services/execution_registry.py

"""
内存态 Execution Registry

职责：
- 管理 task 执行会话（仅内存，不落库）
- 存储执行事件队列，供 SSE 消费
- 支持断线重连时按 cursor 续读
- 支持执行完成后短时保留结果
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass
class ExecutionEvent:
    seq: int
    data: dict[str, Any]
    created_at: float


@dataclass
class ExecutionSession:
    execution_id: str
    task_id: str
    task_type: str
    status: str = "running"  # running | completed | failed | cancelled
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None
    events: list[ExecutionEvent] = field(default_factory=list)
    next_seq: int = 1
    wakeup: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[Any] | None = None

    def append_event(self, data: dict[str, Any]) -> int:
        seq = self.next_seq
        self.next_seq += 1
        self.updated_at = time.time()
        self.events.append(
            ExecutionEvent(
                seq=seq,
                data=data,
                created_at=self.updated_at,
            )
        )
        self.wakeup.set()
        return seq

    def mark_completed(self) -> None:
        self.status = "completed"
        self.finished_at = time.time()
        self.updated_at = self.finished_at
        self.wakeup.set()

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.error = error
        self.finished_at = time.time()
        self.updated_at = self.finished_at
        self.wakeup.set()

    def mark_cancelled(self) -> None:
        self.status = "cancelled"
        self.finished_at = time.time()
        self.updated_at = self.finished_at
        self.wakeup.set()


class ExecutionRegistry:
    """
    仅内存 Registry。
    key 设计：
    - by_execution_id：主索引
    - latest_by_task_id：一个 task 同时最多保留一个“最新执行”
    """

    def __init__(self) -> None:
        self._by_execution_id: dict[str, ExecutionSession] = {}
        self._latest_by_task_id: dict[str, str] = {}
        self._lock = asyncio.Lock()

        # 保留策略
        self._retention_seconds = 60 * 30  # 完成后保留 30 分钟

    async def create_session(self, task_id: str, task_type: str) -> ExecutionSession:
        async with self._lock:
            execution_id = uuid.uuid4().hex
            session = ExecutionSession(
                execution_id=execution_id,
                task_id=task_id,
                task_type=task_type,
            )
            self._by_execution_id[execution_id] = session
            self._latest_by_task_id[task_id] = execution_id
            return session

    async def get_session(self, execution_id: str) -> ExecutionSession | None:
        return self._by_execution_id.get(execution_id)

    async def get_latest_session_by_task(self, task_id: str) -> ExecutionSession | None:
        execution_id = self._latest_by_task_id.get(task_id)
        if not execution_id:
            return None
        return self._by_execution_id.get(execution_id)

    async def append_event(self, execution_id: str, data: dict[str, Any]) -> int:
        session = self._by_execution_id[execution_id]
        return session.append_event(data)

    async def set_task(self, execution_id: str, task: asyncio.Task[Any]) -> None:
        session = self._by_execution_id[execution_id]
        session.task = task

    async def mark_completed(self, execution_id: str) -> None:
        session = self._by_execution_id[execution_id]
        session.mark_completed()

    async def mark_failed(self, execution_id: str, error: str) -> None:
        session = self._by_execution_id[execution_id]
        session.mark_failed(error)

    async def mark_cancelled(self, execution_id: str) -> None:
        session = self._by_execution_id[execution_id]
        session.mark_cancelled()

    async def cancel_session(self, execution_id: str) -> bool:
        session = self._by_execution_id.get(execution_id)
        if not session:
            return False

        if session.status != "running":
            return False

        if session.task and not session.task.done():
            session.task.cancel()

        return True
    
    async def read_events_after(
        self,
        execution_id: str,
        after_seq: int,
    ) -> list[ExecutionEvent]:
        session = self._by_execution_id[execution_id]
        return [e for e in session.events if e.seq > after_seq]

    async def wait_for_updates(
        self,
        execution_id: str,
        timeout: float = 15.0,
    ) -> None:
        session = self._by_execution_id[execution_id]
        wakeup = session.wakeup
        try:
            await asyncio.wait_for(wakeup.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return
        finally:
            wakeup.clear()

    async def cleanup_expired(self) -> None:
        now = time.time()
        expired_ids: list[str] = []

        async with self._lock:
            for execution_id, session in self._by_execution_id.items():
                if session.status == "running":
                    continue
                finished_at = session.finished_at or session.updated_at
                if now - finished_at > self._retention_seconds:
                    expired_ids.append(execution_id)

            for execution_id in expired_ids:
                session = self._by_execution_id.pop(execution_id, None)
                if not session:
                    continue
                latest_execution_id = self._latest_by_task_id.get(session.task_id)
                if latest_execution_id == execution_id:
                    self._latest_by_task_id.pop(session.task_id, None)


execution_registry = ExecutionRegistry()