# backend/app/tenant_context.py
"""
请求级租户上下文管理。

设计：
- 使用 contextvars 存储当前请求的租户信息（路径、用户ID）
- get_db() 在请求入口处 set，深层代码通过 helper 读取
- asyncio.create_task() 自动继承 context，后台任务无需额外传递
- 非 cloud 模式下，租户固定为 "local"，路径指向全局 DATA_DIR
"""

import contextvars
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import APP_MODE, DATA_DIR, UPLOADS_DIR as _GLOBAL_UPLOADS_DIR


# ── 租户数据类 ──────────────────────────────────────────────

@dataclass(frozen=True)
class TenantInfo:
    """不可变的租户信息，存储在 contextvars 中"""
    user_id: str
    email: str
    data_dir: Path
    uploads_dir: Path
    warehouse_path: Path
    db_path: Path


# ── Context Variable ────────────────────────────────────────

_current_tenant: contextvars.ContextVar[TenantInfo | None] = contextvars.ContextVar(
    "current_tenant", default=None
)

# ── 本地固定租户（非 cloud 模式） ──────────────────────────

_LOCAL_TENANT: TenantInfo | None = None


def _get_local_tenant() -> TenantInfo:
    """懒初始化本地租户（非 cloud 模式使用）"""
    global _LOCAL_TENANT
    if _LOCAL_TENANT is None:
        from app.config import DATA_DIR, UPLOADS_DIR, WAREHOUSE_PATH
        _LOCAL_TENANT = TenantInfo(
            user_id="local",
            email="local@localhost",
            data_dir=DATA_DIR,
            uploads_dir=UPLOADS_DIR,
            warehouse_path=WAREHOUSE_PATH,
            db_path=DATA_DIR / "owl.db",
        )
    return _LOCAL_TENANT


# ── Setter / Getter ─────────────────────────────────────────

def set_tenant(tenant: TenantInfo) -> None:
    """设置当前请求的租户上下文（由 get_db 调用）"""
    _current_tenant.set(tenant)


def get_tenant() -> TenantInfo:
    """获取当前租户上下文"""
    t = _current_tenant.get(None)
    if t is not None:
        return t
    # 非 cloud 模式的 fallback（直接调用而非通过请求链）
    if APP_MODE != "cloud":
        return _get_local_tenant()
    raise RuntimeError(
        "No tenant context set. In cloud mode, all code paths "
        "must go through get_db() dependency first."
    )


# ── 便捷路径 getter（替代直接引用全局常量）──────────────────

def get_uploads_dir() -> Path:
    """获取当前租户的 uploads 目录"""
    return get_tenant().uploads_dir


def get_warehouse_path() -> Path:
    """获取当前租户的 DuckDB warehouse 文件路径"""
    return get_tenant().warehouse_path


def get_data_dir() -> Path:
    """获取当前租户的数据根目录"""
    return get_tenant().data_dir


# ── Engine 缓存（cloud 模式按 db_path 缓存）────────────────

_engine_cache: dict[str, AsyncEngine] = {}


def _get_or_create_engine(db_path: Path) -> AsyncEngine:
    """获取或创建指定路径的 AsyncEngine（NullPool，无常驻连接）"""
    key = str(db_path)
    if key not in _engine_cache:
        _engine_cache[key] = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
            poolclass=NullPool,
        )
    return _engine_cache[key]


# ── 租户会话工厂（供后台任务使用）──────────────────────────

@asynccontextmanager
async def open_tenant_session() -> AsyncGenerator[AsyncSession, None]:
    """
    异步上下文管理器：为当前租户打开一个 DB session。
    
    用于后台任务中替代直接使用 `async_session()`：
        # 旧代码:
        async with async_session() as db:
            ...
        # 新代码:
        async with open_tenant_session() as db:
            ...
    
    - 非 cloud 模式：使用全局 async_session（行为不变）
    - cloud 模式：根据 contextvar 中的 db_path 创建连接
    """
    tenant = get_tenant()

    if tenant.user_id == "local":
        # 非 cloud 模式：使用全局 session factory
        from app.database import async_session
        async with async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    else:
        # Cloud 模式：使用租户专属 engine
        engine = _get_or_create_engine(tenant.db_path)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


# ── Cloud 模式租户 DB 初始化 ────────────────────────────────

_initialized_tenants: set[str] = set()


async def ensure_tenant_db_initialized(tenant: TenantInfo) -> None:
    """确保租户数据库已完成 schema 初始化（幂等，首次调用时执行）"""
    if tenant.user_id == "local":
        return  # 非 cloud 模式由 main.py 的 init_db() 处理
    if tenant.user_id in _initialized_tenants:
        return

    from app.database import Base, LATEST_SCHEMA_VERSION
    from sqlalchemy import text

    engine = _get_or_create_engine(tenant.db_path)

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION}"))

    # Seed default agent configs
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        from app.models import AgentConfig
        from sqlalchemy import select

        for agent_type in ["default", "plan", "analyst", "task_manager", "misc"]:
            result = await session.execute(
                select(AgentConfig).where(AgentConfig.agent_type == agent_type)
            )
            if not result.scalar_one_or_none():
                session.add(AgentConfig(agent_type=agent_type))
        await session.commit()

    _initialized_tenants.add(tenant.user_id)