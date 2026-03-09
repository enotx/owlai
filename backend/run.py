# backend/run.py
"""
开发/云端环境启动脚本
用法：
  python backend/run.py --port 61102
"""
import uvicorn
import argparse
import sys
import os

# 将 backend 目录加入环境变量
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.main import app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start Owl Backend")
    parser.add_argument("--port", type=int, default=61102, help="Port to listen on")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind")
    args = parser.parse_args()
    
    print(f"🦉 Starting Owl Backend on {args.host}:{args.port}")
    
    # CORS 配置已移至 app/main.py，根据 APP_MODE 自动处理
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )