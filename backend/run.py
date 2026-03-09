# backend/run.py
import uvicorn
import argparse
import sys
import os

# 将 backend 目录加入环境变量以防找不到包
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.main import app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=61102) # 使用一个冷门端口
    args = parser.parse_args()
    
    # 针对跨域问题：单机下前端(tauri://localhost)与后端(127.0.0.1)算跨域，需放行
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    uvicorn.run(app, host="127.0.0.1", port=args.port)