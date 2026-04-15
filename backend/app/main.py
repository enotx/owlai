# backend/app/main.py

"""FastAPI 应用入口"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from app.schemas import HealthResponse
from app.routers import tasks, knowledge, chat, execute, \
                        llm, database, subtasks, skills, \
                        visualizations, warehouse, assets, \
                        data_pipelines
from app.config import UPLOADS_DIR, APP_MODE



@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库和上传目录"""
    await init_db()

    # ── 启动时清理孤儿文件（DB 中已不存在的 Task 残留） ──
    try:
        from app.services.cleanup import cleanup_orphaned_files
        cleanup_stats = await cleanup_orphaned_files()
        if cleanup_stats.get("orphaned_dirs_removed") or cleanup_stats.get("temp_files_removed"):
            import logging
            logging.getLogger(__name__).info(
                f"Startup cleanup: {cleanup_stats['orphaned_dirs_removed']} orphaned dirs, "
                f"{cleanup_stats['temp_files_removed']} temp files, "
                f"{cleanup_stats['bytes_freed'] / 1024 / 1024:.1f} MB freed"
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Startup cleanup failed (non-fatal): {e}")

    yield

app = FastAPI(title="Owl API", version="0.1.3", lifespan=lifespan)

# ── CORS 配置（根据 APP_MODE 动态调整）──────────────────────
if APP_MODE in ("desktop", "dev"):
    # 桌面模式：允许 tauri://localhost 跨域
    # 开发模式：允许 localhost:3000 跨域
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 桌面/开发环境允许所有来源
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # print("🌐 CORS enabled for desktop/dev mode")
elif APP_MODE == "docker":
    # 云端模式：严格限制来源（生产环境）
    allowed_origins = os.getenv("ALLOWED_ORIGINS", "").split(",")
    if allowed_origins and allowed_origins[0]:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        # print(f"🌐 CORS enabled for origins: {allowed_origins}")


# 注册路由
app.include_router(tasks.router)
app.include_router(knowledge.router)
app.include_router(chat.router)
app.include_router(execute.router)
app.include_router(llm.router)
app.include_router(database.router)
app.include_router(subtasks.router)
app.include_router(skills.router)
app.include_router(visualizations.router)
app.include_router(warehouse.router)
app.include_router(assets.router)
app.include_router(data_pipelines.router)



# 仅桌面模式注册更新路由
if APP_MODE == "desktop":
    from app.routers import updates
    app.include_router(updates.router)




@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """健康检查接口，用于验证前后端连通性"""
    return HealthResponse(status="ok", message="Owl backend is running")