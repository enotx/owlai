# backend/app/main.py

"""FastAPI 应用入口"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from app.schemas import HealthResponse
from app.routers import tasks, knowledge, chat, execute


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库和上传目录"""
    os.makedirs("data/uploads", exist_ok=True)
    await init_db()
    print("✅ Owl Backend is ready.")
    yield


app = FastAPI(title="Owl API", version="0.1.0", lifespan=lifespan)

# 注册路由
app.include_router(tasks.router)
app.include_router(knowledge.router)
app.include_router(chat.router)
app.include_router(execute.router)


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """健康检查接口，用于验证前后端连通性"""
    return HealthResponse(status="ok", message="Owl backend is running")