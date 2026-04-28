# backend/app/config.py
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（从项目根目录或 backend 目录查找）
# 优先查找 backend/.env，其次是项目根目录的 .env
env_path = Path(__file__).parent.parent / ".env"
if not env_path.exists():
    env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# 现在可以正确读取 APP_MODE 了
APP_MODE = os.getenv("APP_MODE", "desktop")

def get_data_dir() -> Path:
    """获取所有持久化数据（SQLite、CSV 等）的根目录"""
    if APP_MODE == "dev":
        project_backend = Path(__file__).parent.parent
        base_dir = project_backend / "data"
    elif APP_MODE == "docker":
        project_backend = Path(__file__).parent.parent
        base_dir = project_backend / "data"
    elif APP_MODE == "cloud":
        # Cloud 模式下此函数不应被直接调用
        # 但为了兼容启动逻辑，返回一个默认目录
        home = Path.home()
        base_dir = home / os.getenv("TENANT_DATA_DIR", ".owl/tenant_data")
    elif APP_MODE == "desktop":
        import platformdirs
        base_dir = Path(platformdirs.user_data_dir("OwlDataAnalyzer"))
    else:
        raise ValueError(f"Unknown APP_MODE: {APP_MODE}")
    
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_python_executable() -> str:
    """
    获取 Python 解释器路径。
    桌面模式下，返回 Portable Python 的路径；
    其他模式返回当前 sys.executable。
    """
    if APP_MODE == "desktop":
        # 检测是否在 Tauri Sidecar 环境中
        # Sidecar 启动时，工作目录是 sidecar/python-xxx/
        cwd = Path.cwd()
        if (cwd / "env" / "bin" / "python3").exists():  # macOS/Linux
            return str(cwd / "env" / "bin" / "python3")
        elif (cwd / "env" / "Scripts" / "python.exe").exists():  # Windows
            return str(cwd / "env" / "Scripts" / "python.exe")
        else:
            # 回退到系统 Python（不应该发生）
            return sys.executable
    else:
        return sys.executable

PYTHON_EXECUTABLE = get_python_executable()

DATA_DIR = get_data_dir()
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
TEMP_DIR = DATA_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ── DuckDB 本地数据仓库 ──────────────────────────────────────
WAREHOUSE_DIR = DATA_DIR / "warehouse"
WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
WAREHOUSE_PATH = WAREHOUSE_DIR / "warehouse.duckdb"

# ── Cloud 模式配置 ──────────────────────────────────────
CLOUD_MODE = APP_MODE == "cloud"

# Supabase JWT 验证（仅 cloud 模式使用）
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

# 租户数据根目录（仅 cloud 模式使用）
home = Path.home()
TENANT_DATA_ROOT = home / os.getenv("TENANT_DATA_DIR", ".owl/tenant_data")
if CLOUD_MODE:
    TENANT_DATA_ROOT.mkdir(parents=True, exist_ok=True)

# New API 地址（仅 cloud 模式，用于 LLM 代理）
NEW_API_BASE_URL = os.getenv("NEW_API_BASE_URL", "http://localhost:3000")