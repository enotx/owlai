# backend/app/routers/runtimes.py

"""Runtime 管理 API（Jupyter 配置 + 全局默认）"""
import os

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import JupyterConfig, SystemSetting
from app.schemas import (
    JupyterConfigCreate,
    JupyterConfigUpdate,
    JupyterConfigResponse,
    JupyterTestConnectionResponse,
    SystemSettingResponse,
    SystemSettingUpdate,
    RuntimeSwitchRequest,
)

router = APIRouter(prefix="/api/runtimes", tags=["runtimes"])


# ── Jupyter 配置 CRUD ────────────────────────────────────

@router.get("", response_model=list[JupyterConfigResponse])
async def list_jupyter_configs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(JupyterConfig).order_by(JupyterConfig.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=JupyterConfigResponse)
async def create_jupyter_config(
    body: JupyterConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    config = JupyterConfig(
        name=body.name,
        server_url=body.server_url.rstrip("/"),
        token=body.token,
        kernel_name=body.kernel_name,
        security_level=body.security_level,
        data_transfer_mode=body.data_transfer_mode,
        shared_storage_path=body.shared_storage_path,
        idle_timeout=body.idle_timeout,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


@router.get("/{config_id}", response_model=JupyterConfigResponse)
async def get_jupyter_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(JupyterConfig, config_id)
    if not config:
        raise HTTPException(404, "Jupyter config not found")
    return config


@router.put("/{config_id}", response_model=JupyterConfigResponse)
async def update_jupyter_config(
    config_id: str,
    body: JupyterConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(JupyterConfig, config_id)
    if not config:
        raise HTTPException(404, "Jupyter config not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "server_url" and value:
            value = value.rstrip("/")
        setattr(config, field, value)

    await db.commit()
    await db.refresh(config)
    return config


@router.delete("/{config_id}")
async def delete_jupyter_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(JupyterConfig, config_id)
    if not config:
        raise HTTPException(404, "Jupyter config not found")

    # 注销已注册的 backend
    from app.services.execution.resolver import unregister_backend
    unregister_backend(f"jupyter:{config_id}")

    await db.delete(config)
    await db.commit()
    return {"ok": True}


@router.post("/{config_id}/test", response_model=JupyterTestConnectionResponse)
async def test_jupyter_connection(
    config_id: str,
    db: AsyncSession = Depends(get_db),
):
    """测试 Jupyter Server 连接"""
    config = await db.get(JupyterConfig, config_id)
    if not config:
        raise HTTPException(404, "Jupyter config not found")

    import httpx

    try:
        headers = {}
        if config.token:
            headers["Authorization"] = f"token {config.token}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            # 测试 API 可达性
            resp = await client.get(
                f"{config.server_url}/api/status",
                headers=headers,
            )
            resp.raise_for_status()

            # 获取可用 kernel specs
            specs_resp = await client.get(
                f"{config.server_url}/api/kernelspecs",
                headers=headers,
            )
            kernel_specs = []
            if specs_resp.status_code == 200:
                data = specs_resp.json()
                kernel_specs = list(data.get("kernelspecs", {}).keys())

        # 更新连接状态
        config.status = "active"
        config.last_connected_at = datetime.now()
        await db.commit()

        return JupyterTestConnectionResponse(
            success=True,
            message="Connected successfully",
            kernel_specs=kernel_specs,
        )

    except httpx.HTTPStatusError as e:
        config.status = "error"
        await db.commit()
        return JupyterTestConnectionResponse(
            success=False,
            message=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
        )
    except Exception as e:
        config.status = "error"
        await db.commit()
        return JupyterTestConnectionResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
        )


# ── 全局默认 Runtime 设置 ────────────────────────────────

@router.get("/settings/default", response_model=SystemSettingResponse)
async def get_default_runtime(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SystemSetting).where(
            SystemSetting.key == "default_execution_backend"
        )
    )
    setting = result.scalar_one_or_none()
    if not setting:
        # 返回默认值
        return SystemSettingResponse(
            key="default_execution_backend",
            value="local",
            updated_at=datetime.now(),
        )
    return setting


@router.put("/settings/default", response_model=SystemSettingResponse)
async def set_default_runtime(
    body: SystemSettingUpdate,
    db: AsyncSession = Depends(get_db),
):
    """设置全局默认 Runtime

    value: "local" | "jupyter:{config_id}" | "auto"
    """
    result = await db.execute(
        select(SystemSetting).where(
            SystemSetting.key == "default_execution_backend"
        )
    )
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = body.value
    else:
        setting = SystemSetting(
            key="default_execution_backend",
            value=body.value,
        )
        db.add(setting)

    await db.commit()
    await db.refresh(setting)
    return setting

# ── Task Runtime 切换 ────────────────────────────────────

@router.put("/tasks/{task_id}/runtime")
async def switch_task_runtime(
    task_id: str,
    body: "RuntimeSwitchRequest",
    db: AsyncSession = Depends(get_db),
):
    """切换 Task 的执行运行时

    副作用：清除该 Task 的所有 Knowledge 和 persist 目录
    """
    from app.schemas import RuntimeSwitchRequest as RSR
    from app.models import Task, Knowledge
    from app.config import UPLOADS_DIR
    import shutil

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    old_backend = task.execution_backend
    new_backend = body.execution_backend

    if old_backend == new_backend:
        return {"ok": True, "message": "No change", "cleared": False}

    # 验证新 backend 有效性
    if new_backend != "local" and new_backend.startswith("jupyter:"):
        config_id = new_backend.split(":", 1)[1]
        config = await db.get(JupyterConfig, config_id)
        if not config or config.status != "active":
            raise HTTPException(400, "Invalid or inactive Jupyter config")
    elif new_backend != "local":
        raise HTTPException(400, "Invalid backend format. Use 'local' or 'jupyter:{config_id}'")

    # 清除 Knowledge
    result = await db.execute(
        select(Knowledge).where(Knowledge.task_id == task_id)
    )
    knowledge_items = list(result.scalars().all())
    for k in knowledge_items:
        await db.delete(k)

    # 清除 persist 目录
    persist_dir = os.path.join(str(UPLOADS_DIR), task_id, "captures", "persist")
    if os.path.isdir(persist_dir):
        shutil.rmtree(persist_dir, ignore_errors=True)

    # 清除 captures 目录
    captures_dir = os.path.join(str(UPLOADS_DIR), task_id, "captures")
    if os.path.isdir(captures_dir):
        shutil.rmtree(captures_dir, ignore_errors=True)

    # 如果旧 backend 是 Jupyter，shutdown kernel
    if old_backend.startswith("jupyter:"):
        from app.services.execution.resolver import get_backend
        old_be = get_backend(old_backend)
        try:
            await old_be.shutdown(task_id)
        except Exception:
            pass

    # 更新 Task
    task.execution_backend = new_backend
    await db.commit()

    return {
        "ok": True,
        "message": f"Switched from {old_backend} to {new_backend}",
        "cleared": True,
        "cleared_knowledge_count": len(knowledge_items),
    }
