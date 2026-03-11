# backend/app/routers/database.py

"""数据库管理相关 API"""

from fastapi import APIRouter
from app.database import check_db_compatibility, delete_and_recreate_db
from pydantic import BaseModel

router = APIRouter(prefix="/api/database", tags=["database"])


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


@router.get("/compatibility", response_model=DBCompatibilityResponse)
async def get_db_compatibility():
    """
    检查数据库兼容性
    
    前端应在应用启动时调用此接口，如果返回 compatible=False，
    则提示用户删除旧数据库
    """
    result = await check_db_compatibility()
    return result


@router.post("/recreate", response_model=DBRecreateResponse)
async def recreate_database():
    """
    删除旧数据库并重新创建
    
    ⚠️ 警告：此操作将删除所有历史数据，不可恢复
    """
    result = await delete_and_recreate_db()
    return result