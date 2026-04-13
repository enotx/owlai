# backend/app/routers/assets.py

"""Asset 管理 API"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json

from app.database import get_db
from app.models import Asset, Task
from app.schemas import AssetCreate, AssetUpdate, AssetResponse, RunAssetRequest

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.post("", response_model=AssetResponse)
async def create_asset(body: AssetCreate, db: AsyncSession = Depends(get_db)):
    """创建资产（从提取流程调用）"""
    asset = Asset(
        name=body.name,
        description=body.description,
        asset_type=body.asset_type,
        source_task_id=body.source_task_id,
        code=body.code,
        script_type=body.script_type,
        env_vars_json=json.dumps(body.env_vars, ensure_ascii=False),
        allowed_modules_json=json.dumps(body.allowed_modules, ensure_ascii=False),
        content_markdown=body.content_markdown,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return AssetResponse.from_orm(asset)


@router.get("", response_model=list[AssetResponse])
async def list_assets(
    asset_type: str | None = Query(None, pattern="^(script|sop)$"),
    script_type: str | None = Query(None, pattern="^(general|pipeline)$"),
    db: AsyncSession = Depends(get_db)
):
    """列出资产"""
    query = select(Asset).order_by(Asset.updated_at.desc())
    
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
    if script_type:
        query = query.where(Asset.script_type == script_type)
    
    result = await db.execute(query)
    assets = result.scalars().all()
    return [AssetResponse.from_orm(a) for a in assets]


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    """获取资产详情"""
    asset = await db.get(Asset, asset_id)
    if not asset:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetResponse.from_orm(asset)


@router.patch("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: str,
    body: AssetUpdate,
    db: AsyncSession = Depends(get_db)
):
    """编辑资产"""
    asset = await db.get(Asset, asset_id)
    if not asset:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Asset not found")
    
    if body.name is not None:
        asset.name = body.name
    if body.description is not None:
        asset.description = body.description
    if body.code is not None:
        asset.code = body.code
    if body.env_vars is not None:
        asset.env_vars_json = json.dumps(body.env_vars, ensure_ascii=False)
    if body.allowed_modules is not None:
        asset.allowed_modules_json = json.dumps(body.allowed_modules, ensure_ascii=False)
    if body.content_markdown is not None:
        asset.content_markdown = body.content_markdown
    
    await db.commit()
    await db.refresh(asset)
    return AssetResponse.from_orm(asset)


@router.delete("/{asset_id}")
async def delete_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    """删除资产"""
    asset = await db.get(Asset, asset_id)
    if not asset:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Asset not found")
    
    await db.delete(asset)
    await db.commit()
    return {"detail": "Asset deleted"}


@router.post("/{asset_id}/run")
async def run_asset(
    asset_id: str,
    body: RunAssetRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    执行资产
    - script/pipeline: 创建 Task 并立即执行，返回 SSE stream
    - sop: 创建 Task，返回 task_id（前端跳转后通过 chat stream 执行）
    """
    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse
    from app.services.script_runner import run_script

    # 1. 读取 Asset
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # 2. 确定 task_type
    if asset.asset_type == "sop":
        task_type = "routine"
    elif asset.script_type == "pipeline":
        task_type = "pipeline"
    else:
        task_type = "script"

    # 3. 创建 Task
    task = Task(
        title=f"Run: {asset.name}",
        description=f"Executing {asset.asset_type}: {asset.name}",
        task_type=task_type,
        asset_id=asset_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # 4. 对于 script/pipeline，立即执行并返回 SSE stream
    if task_type in ("script", "pipeline"):
        async def event_generator():
            try:
                async for event in run_script(
                    task_id=task.id,
                    asset=asset,
                    db=db,
                    env_vars_override=body.env_vars_override,
                    data_source_ids=body.data_source_ids,
                ):
                    yield event
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
                "X-Task-ID": task.id,
            },
        )

    # 5. 对于 routine/sop，返回 task_id
    return {"task_id": task.id, "task_type": task_type}