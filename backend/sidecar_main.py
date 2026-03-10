# backend/sidecar_main.py
"""
Tauri Sidecar 启动入口：
- 动态分配可用端口
- 将端口写入临时文件供 Tauri 读取
- 启动 FastAPI 服务
"""
import sys
import io
import os
import socket
import uvicorn
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def find_free_port() -> int:
    """查找可用端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port

def main():
    # 设置环境变量（触发 app/main.py 中的 CORS 配置）
    os.environ["APP_MODE"] = "desktop"
    
    # 查找可用端口
    port = find_free_port()
    
    # 将端口写入临时文件（Tauri 会读取）
    port_file = Path.home() / ".owl_backend_port"
    if port_file.exists():
        port_file.unlink()
    port_file.write_text(str(port))
    
    print(f"🦉 Owl Backend starting on http://127.0.0.1:{port}")
    
    # CORS 配置已在 app/main.py 中根据 APP_MODE 自动处理
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=False,
    )

if __name__ == "__main__":
    main()