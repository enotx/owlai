# backend/app/routers/updates.py
"""
桌面模式下的软件更新支持：
- 从 License Server 流式下载安装包
- 打开已下载的安装包进行安装
仅在 APP_MODE=desktop 时注册此路由。
"""

import platform
import subprocess
import sys
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.config import DATA_DIR

router = APIRouter(prefix="/api/updates", tags=["updates"])

# 下载目录
UPDATES_DIR = DATA_DIR / "updates"
UPDATES_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/platform-info")
async def get_platform_info():
    """
    返回当前运行环境信息。
    前端在非 Tauri 环境下（fallback）可用此接口获取平台信息。
    """
    os_name = platform.system().lower()
    machine = platform.machine().lower()

    # 统一平台名称
    if os_name == "darwin":
        plat = "macos"
    elif os_name == "windows":
        plat = "windows"
    else:
        plat = "linux"

    # 统一架构名称
    if machine in ("arm64", "aarch64"):
        arch = "aarch64"
    elif machine in ("x86_64", "amd64"):
        arch = "x86_64"
    else:
        arch = machine

    return {
        "platform": plat,
        "arch": arch,
    }


@router.get("/download-stream")
async def download_update_stream(
    url: str = Query(..., description="安装包下载 URL"),
    file_name: str = Query(..., description="保存的文件名"),
):
    """
    从 License Server 流式下载安装包，通过 SSE 推送下载进度。
    下载完成后文件保存到 ~/.owl/updates/ 目录。
    """

    async def event_stream():
        file_path = UPDATES_DIR / file_name

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        yield f"data: {{\"type\": \"error\", \"message\": \"HTTP {response.status_code}\"}}\n\n"
                        return

                    total = int(response.headers.get("content-length", 0))
                    downloaded = 0

                    with open(file_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=256 * 1024):
                            f.write(chunk)
                            downloaded += len(chunk)
                            percent = int(downloaded * 100 / total) if total > 0 else 0

                            yield (
                                f"data: {{\"type\": \"progress\", "
                                f"\"percent\": {percent}, "
                                f"\"downloaded_bytes\": {downloaded}, "
                                f"\"total_bytes\": {total}}}\n\n"
                            )

            # 下载完成
            yield (
                f"data: {{\"type\": \"complete\", "
                f"\"file_path\": \"{file_path.as_posix()}\"}}\n\n"
            )

        except httpx.TimeoutException:
            yield f"data: {{\"type\": \"error\", \"message\": \"Download timed out\"}}\n\n"
        except Exception as e:
            # 清理失败的部分文件
            if file_path.exists():
                file_path.unlink(missing_ok=True)
            yield f"data: {{\"type\": \"error\", \"message\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/install")
async def install_update(data: dict):
    """
    打开已下载的安装包。
    - macOS: open xxx.dmg（挂载 DMG）
    - Windows: start xxx.msi（启动 MSI 安装器）
    """
    file_path = Path(data.get("file_path", ""))

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # 安全校验：确保文件在 updates 目录内
    try:
        file_path.resolve().relative_to(UPDATES_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    os_name = platform.system().lower()

    try:
        if os_name == "darwin":
            # macOS: 挂载 DMG
            subprocess.Popen(["open", str(file_path)])
            return {
                "success": True,
                "message": "DMG mounted. Please drag Owl to Applications folder, then run: xattr -cr '/Applications/Owl Data Analyst.app'",
            }
        elif os_name == "windows":
            # Windows: 启动 MSI 安装器
            subprocess.Popen(["cmd", "/c", "start", "", str(file_path)])
            return {
                "success": True,
                "message": "Installer launched. The application will close for update.",
            }
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported platform: {os_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch installer: {e}")