# backend/app/database.py

"""数据库连接与会话管理"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import DATA_DIR
import os

# 使用动态路径（桌面模式 → AppData，云端模式 → /app/data）
db_path = os.path.join(DATA_DIR, "owl.db")
DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"

# DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'owl.db'}"
# DATABASE_URL = "sqlite+aiosqlite:///./data/owl.db"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """初始化数据库，创建所有表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """获取数据库会话的依赖注入"""
    async with async_session() as session:
        yield session