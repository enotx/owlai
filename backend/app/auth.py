# backend/app/auth.py
"""
多模式认证模块。

- cloud 模式：验证 Supabase JWT，提取 user_id，动态路由到租户目录
- dev / docker / desktop 模式：返回固定的 "local" 用户，行为与原来完全一致
"""

from jwt import decode, ExpiredSignatureError, InvalidTokenError
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import APP_MODE, CLOUD_MODE, SUPABASE_JWT_SECRET, TENANT_DATA_ROOT

# cloud 模式使用 Bearer token；其他模式此依赖不生效
_http_bearer = HTTPBearer(auto_error=False)


def verify_supabase_jwt(token: str) -> dict:
    """
    验证 Supabase JWT，返回 payload dict。
    
    供 get_current_user 和 get_db (cloud模式) 共用。
    """
    try:
        payload = decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

@dataclass
class CurrentUser:
    """当前请求的用户上下文"""
    user_id: str
    email: str
    data_dir: Path        # 该用户的数据根目录
    uploads_dir: Path     # 该用户的上传目录
    warehouse_path: Path  # 该用户的 DuckDB warehouse 文件路径
    db_path: Path         # 该用户的 SQLite 数据库路径


def _build_user_from_tenant_dir(user_id: str, email: str, base_dir: Path) -> CurrentUser:
    """根据数据目录构建 CurrentUser"""
    base_dir.mkdir(parents=True, exist_ok=True)
    
    uploads_dir = base_dir / "uploads"
    uploads_dir.mkdir(exist_ok=True)
    
    warehouse_dir = base_dir / "warehouse"
    warehouse_dir.mkdir(exist_ok=True)
    
    temp_dir = base_dir / "temp"
    temp_dir.mkdir(exist_ok=True)
    
    return CurrentUser(
        user_id=user_id,
        email=email,
        data_dir=base_dir,
        uploads_dir=uploads_dir,
        warehouse_path=warehouse_dir / "warehouse.duckdb",
        db_path=base_dir / "owl.db",
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
) -> CurrentUser:
    """
    FastAPI 依赖注入：根据 APP_MODE 返回当前用户上下文。
    
    - cloud 模式：从 JWT 解析 user_id，映射到租户专属目录
    - 其他模式：返回固定的 "local" 用户，数据目录为原来的 DATA_DIR
    """
    if not CLOUD_MODE:
        # 非 cloud 模式：固定用户，使用全局 DATA_DIR
        from app.config import DATA_DIR
        return _build_user_from_tenant_dir("local", "local@localhost", DATA_DIR)
    
    # ── Cloud 模式：验证 JWT ──
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = verify_supabase_jwt(credentials.credentials)
    
    user_id = payload.get("sub")
    email = payload.get("email", "")
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing sub",
        )
    
    # 租户目录
    tenant_dir = TENANT_DATA_ROOT / f"u_{user_id}"
    return _build_user_from_tenant_dir(user_id, email, tenant_dir)