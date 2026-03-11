# backend/app/database.py

"""数据库连接与会话管理"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select, text
from app.config import DATA_DIR
import os
import logging

logger = logging.getLogger(__name__)

# 使用动态路径（桌面模式 → AppData，云端模式 → /app/data）
db_path = DATA_DIR / "owl.db"
DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def check_db_compatibility() -> dict:
    """
    检查数据库兼容性
    
    Returns:
        dict: {
            "compatible": bool,  # 是否兼容
            "exists": bool,      # 数据库文件是否存在
            "issues": list[str], # 不兼容的具体问题列表
            "db_path": str       # 数据库文件路径
        }
    """
    result = {
        "compatible": True,
        "exists": db_path.exists(),
        "issues": [],
        "db_path": str(db_path)
    }
    
    if not result["exists"]:
        # 数据库不存在，视为兼容（将创建新数据库）
        return result
    
    try:
        async with engine.begin() as conn:
            # 检查 tasks 表是否存在
            table_check = await conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
            ))
            if not table_check.fetchone():
                # tasks 表不存在，可能是全新数据库
                return result
            
            # 检查 tasks 表的 mode 字段
            result_info = await conn.execute(text("PRAGMA table_info(tasks)"))
            columns = [row[1] for row in result_info.fetchall()]
            
            if "mode" not in columns:
                result["compatible"] = False
                result["issues"].append("tasks 表缺少 'mode' 字段")
            
            if "plan_confirmed" not in columns:
                result["compatible"] = False
                result["issues"].append("tasks 表缺少 'plan_confirmed' 字段")
            
            if "current_subtask_id" not in columns:
                result["compatible"] = False
                result["issues"].append("tasks 表缺少 'current_subtask_id' 字段")
            
            # 检查 subtasks 表是否存在
            subtasks_check = await conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='subtasks'"
            ))
            if not subtasks_check.fetchone():
                result["compatible"] = False
                result["issues"].append("缺少 'subtasks' 表")
            
            # 检查 steps 表的 subtask_id 字段
            steps_info = await conn.execute(text("PRAGMA table_info(steps)"))
            steps_columns = [row[1] for row in steps_info.fetchall()]
            
            if "subtask_id" not in steps_columns:
                result["compatible"] = False
                result["issues"].append("steps 表缺少 'subtask_id' 字段")
            
    except Exception as e:
        logger.error(f"数据库兼容性检查失败: {e}")
        result["compatible"] = False
        result["issues"].append(f"检查过程出错: {str(e)}")
    
    return result


async def delete_and_recreate_db() -> dict:
    """
    删除旧数据库并重新创建
    
    Returns:
        dict: {
            "success": bool,
            "message": str
        }
    """
    try:
        # 1. 关闭所有连接
        await engine.dispose()
        
        # 2. 删除数据库文件
        if db_path.exists():
            os.remove(db_path)
            logger.info(f"已删除旧数据库: {db_path}")
        
        # 3. 重新初始化数据库（会自动创建新的连接）
        await init_db()
        
        return {
            "success": True,
            "message": "数据库已成功重建"
        }
    except Exception as e:
        logger.error(f"删除并重建数据库失败: {e}")
        return {
            "success": False,
            "message": f"操作失败: {str(e)}"
        }


async def init_db() -> None:
    """初始化数据库，创建所有表并插入默认配置"""
    # 创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # 创建默认的AgentConfig
    await _create_default_agent_configs()
    
    logger.info("数据库初始化完成")


async def _create_default_agent_configs() -> None:
    """创建默认的Agent配置（如果不存在）"""
    from app.models import AgentConfig
    
    default_configs = [
        {"agent_type": "default"},
        {"agent_type": "plan"},
        {"agent_type": "analyst"},
        {"agent_type": "task_manager"},
    ]
    
    async with async_session() as session:
        for config_data in default_configs:
            # 检查是否已存在
            result = await session.execute(
                select(AgentConfig).where(AgentConfig.agent_type == config_data["agent_type"])
            )
            existing = result.scalar_one_or_none()
            
            if not existing:
                config = AgentConfig(**config_data)
                session.add(config)
        
        await session.commit()


async def get_db():
    """获取数据库会话的依赖注入"""
    async with async_session() as session:
        yield session