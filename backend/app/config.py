# backend/app/config.py
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（从项目根目录或 backend 目录查找）
# 优先查找 backend/.env，其次是项目根目录的 .env
env_path = Path(__file__).parent.parent / ".env"
if not env_path.exists():
    env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# 现在可以正确读取 APP_MODE 了
APP_MODE = os.getenv("APP_MODE", "desktop")

def get_data_dir() -> Path:
    """获取所有持久化数据（SQLite、CSV 等）的根目录"""
    if APP_MODE == "cloud":
        # 云端挂载路径
        project_backend = Path(__file__).parent.parent
        base_dir = project_backend / "data"
    else:
        # 单机桌面版：存放在用户自己的 AppData / Application Support 下
        import platformdirs
        base_dir = Path(platformdirs.user_data_dir("OwlDataAnalyzer"))
    
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir

DATA_DIR = get_data_dir()
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)