# backend/app/routers/knowledge.py

"""Knowledge 管理 API：上传/列表/删除/预览"""

import os
import shutil
import aiofiles
import json
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Knowledge, Asset, DataPipeline
from app.schemas import (
    KnowledgeResponse,
    AddAssetToContextRequest,
    AddPipelineToContextRequest,
)
from app.services.data_processor import parse_csv_metadata, get_csv_preview
from app.tenant_context import get_uploads_dir  # 新增：导入动态路径

from app.services.data_processor import (
    parse_csv_metadata, 
    parse_excel_metadata,  # 新增
    get_csv_preview,
    get_excel_preview,     # 新增
    read_text_content      # 新增
)


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

async def _find_existing_asset_knowledge(
    db: AsyncSession,
    task_id: str,
    asset_id: str,
) -> Knowledge | None:
    result = await db.execute(
        select(Knowledge).where(
            Knowledge.task_id == task_id,
            Knowledge.type.in_(["asset_script", "asset_sop"]),
        )
    )
    for item in result.scalars().all():
        if not item.metadata_json:
            continue
        try:
            meta = json.loads(item.metadata_json)
        except json.JSONDecodeError:
            continue
        if meta.get("asset_id") == asset_id:
            return item
    return None


async def _find_existing_pipeline_knowledge(
    db: AsyncSession,
    task_id: str,
    pipeline_id: str,
) -> Knowledge | None:
    result = await db.execute(
        select(Knowledge).where(
            Knowledge.task_id == task_id,
            Knowledge.type == "data_pipeline",
        )
    )
    for item in result.scalars().all():
        if not item.metadata_json:
            continue
        try:
            meta = json.loads(item.metadata_json)
        except json.JSONDecodeError:
            continue
        if meta.get("pipeline_id") == pipeline_id:
            return item
    return None

@router.post("", response_model=KnowledgeResponse)
async def upload_knowledge(
    task_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传 Knowledge 文件（CSV/Excel/文本），保存到磁盘并解析元数据"""
    filename = file.filename or "unknown"
    
    # 识别文件类型
    lower_name = filename.lower()
    if lower_name.endswith(".csv"):
        file_type = "csv"
    elif lower_name.endswith((".xlsx", ".xls")):
        file_type = "excel"
    else:
        file_type = "text"
    # 同名文件查重：同一 Task 下不允许上传同名 Knowledge
    existing = await db.execute(
        select(Knowledge).where(
            Knowledge.task_id == task_id,
            Knowledge.name == filename,
        )
    )
    if existing.scalars().first() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A file named '{filename}' already exists in this task. Please rename or delete the existing one first.",
        )
    task_dir = get_uploads_dir() / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    # 文件落盘
    file_path = task_dir / filename
    content = await file.read()
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)
    # 元数据解析
    metadata_json = None
    if file_type == "csv":
        try:
            metadata_json = parse_csv_metadata(str(file_path))
        except Exception as e:
            metadata_json = f'{{"parse_error": "{str(e)}"}}'
    elif file_type == "excel":
        try:
            metadata_json = parse_excel_metadata(str(file_path))
        except Exception as e:
            metadata_json = f'{{"parse_error": "{str(e)}"}}'
    # 写入数据库
    knowledge = Knowledge(
        task_id=task_id,
        type=file_type,
        name=filename,
        file_path=str(file_path),
        metadata_json=metadata_json,
    )
    db.add(knowledge)
    await db.commit()
    await db.refresh(knowledge)
    return knowledge

@router.post("/context/asset", response_model=KnowledgeResponse)
async def add_asset_to_context(
    body: AddAssetToContextRequest,
    db: AsyncSession = Depends(get_db),
):
    """将 Script / SOP 资产加入指定 Task 的 Knowledge 上下文"""
    asset = await db.get(Asset, body.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    existing = await _find_existing_asset_knowledge(db, body.task_id, body.asset_id)
    if existing:
        return existing

    knowledge_type = "asset_script" if asset.asset_type == "script" else "asset_sop"

    knowledge = Knowledge(
        task_id=body.task_id,
        type=knowledge_type,
        name=asset.name,
        file_path=None,
        metadata_json=json.dumps(
            {
                "asset_id": asset.id,
                "asset_type": asset.asset_type,
                "description": asset.description,
                "script_type": asset.script_type,
            },
            ensure_ascii=False,
        ),
    )
    db.add(knowledge)
    await db.commit()
    await db.refresh(knowledge)
    return knowledge

@router.post("/context/pipeline", response_model=KnowledgeResponse)
async def add_pipeline_to_context(
    body: AddPipelineToContextRequest,
    db: AsyncSession = Depends(get_db),
):
    """将 Data Pipeline 加入指定 Task 的 Knowledge 上下文"""
    pipeline = await db.get(DataPipeline, body.pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    existing = await _find_existing_pipeline_knowledge(db, body.task_id, body.pipeline_id)
    if existing:
        return existing

    knowledge = Knowledge(
        task_id=body.task_id,
        type="data_pipeline",
        name=pipeline.name,
        file_path=None,
        metadata_json=json.dumps(
            {
                "pipeline_id": pipeline.id,
                "target_table_name": pipeline.target_table_name,
                "source_type": pipeline.source_type,
                "write_strategy": pipeline.write_strategy,
                "description": pipeline.description,
            },
            ensure_ascii=False,
        ),
    )
    db.add(knowledge)
    await db.commit()
    await db.refresh(knowledge)
    return knowledge

@router.get("", response_model=list[KnowledgeResponse])
async def list_knowledge(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取指定 Task 的 Knowledge 列表"""
    result = await db.execute(
        select(Knowledge).where(Knowledge.task_id == task_id).order_by(Knowledge.created_at)
    )
    return result.scalars().all()


@router.get("/{knowledge_id}", response_model=KnowledgeResponse)
async def get_knowledge(knowledge_id: str, db: AsyncSession = Depends(get_db)):
    """获取 Knowledge 详情"""
    item = await db.get(Knowledge, knowledge_id)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge not found")
    return item


@router.delete("/{knowledge_id}")
async def delete_knowledge(knowledge_id: str, db: AsyncSession = Depends(get_db)):
    """删除 Knowledge：同时清理磁盘文件"""
    item = await db.get(Knowledge, knowledge_id)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge not found")

    # 级联清理磁盘文件
    if item.file_path and os.path.exists(item.file_path):
        os.remove(item.file_path)

        # 如果该 task 目录已空，顺便清理空目录
        task_dir = os.path.dirname(item.file_path)
        if os.path.isdir(task_dir) and not os.listdir(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)

    await db.delete(item)
    await db.commit()
    return {"detail": "Knowledge deleted"}


@router.get("/{knowledge_id}/preview")
async def preview_knowledge(
    knowledge_id: str,
    n: int = Query(default=50, ge=1, le=500, description="预览行数"),
    sheet_name: str | None = Query(default=None, description="Excel sheet 名称"),
    db: AsyncSession = Depends(get_db),
):
    """预览 Knowledge 数据：CSV/Excel 返回表格，文本返回内容"""
    item = await db.get(Knowledge, knowledge_id)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge not found")
    if not item.file_path or not os.path.exists(item.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    if item.type in ("asset_script", "asset_sop"):
        if not item.metadata_json:
            raise HTTPException(status_code=500, detail="Knowledge metadata missing")
        try:
            meta = json.loads(item.metadata_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Knowledge metadata invalid")
        asset_id = meta.get("asset_id")
        asset = await db.get(Asset, asset_id) if asset_id else None
        if not asset:
            raise HTTPException(status_code=404, detail="Referenced asset not found")
        if asset.asset_type == "script":
            content = (
                f"# Script: {asset.name}\n\n"
                f"{asset.description or ''}\n\n"
                f"## Script Type\n{asset.script_type or 'general'}\n\n"
                f"## Code\n\n```python\n{asset.code or ''}\n```"
            )
        else:
            content = (
                f"# SOP: {asset.name}\n\n"
                f"{asset.description or ''}\n\n"
                f"{asset.content_markdown or ''}"
            )
        return {
            "knowledge_id": knowledge_id,
            "type": "text",
            "content": content,
            "columns": [],
            "rows": [],
            "total_rows": 0,
        }
    elif item.type == "data_pipeline":
        if not item.metadata_json:
            raise HTTPException(status_code=500, detail="Knowledge metadata missing")
        try:
            meta = json.loads(item.metadata_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Knowledge metadata invalid")
        pipeline_id = meta.get("pipeline_id")
        pipeline = await db.get(DataPipeline, pipeline_id) if pipeline_id else None
        if not pipeline:
            raise HTTPException(status_code=404, detail="Referenced pipeline not found")
        content = (
            f"# Data Pipeline: {pipeline.name}\n\n"
            f"{pipeline.description or ''}\n\n"
            f"## Source Type\n{pipeline.source_type}\n\n"
            f"## Target Table\n{pipeline.target_table_name}\n\n"
            f"## Write Strategy\n{pipeline.write_strategy}\n\n"
            f"## Transform Description\n{pipeline.transform_description or ''}\n\n"
            f"## Transform Code\n\n```python\n{pipeline.transform_code}\n```"
        )
        return {
            "knowledge_id": knowledge_id,
            "type": "text",
            "content": content,
            "columns": [],
            "rows": [],
            "total_rows": 0,
        }
    elif item.type == "csv":
        try:
            preview = get_csv_preview(item.file_path, n_rows=n)
            return {"knowledge_id": knowledge_id, "type": "csv", **preview}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"CSV parse error: {str(e)}")
    elif item.type == "excel":
        try:
            preview = get_excel_preview(item.file_path, sheet_name=sheet_name, n_rows=n)
            return {"knowledge_id": knowledge_id, "type": "excel", **preview}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Excel parse error: {str(e)}")
    
    else:
        # 文本文件：返回完整内容（带截断保护）
        try:
            content = read_text_content(item.file_path)
            return {
                "knowledge_id": knowledge_id,
                "type": "text",
                "content": content,
                "columns": [],
                "rows": [],
                "total_rows": 0,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Text read error: {str(e)}")

@router.get("/{knowledge_id}/download")
async def download_knowledge(
    knowledge_id: str,
    db: AsyncSession = Depends(get_db),
):
    """下载Knowledge源文件"""
    from fastapi.responses import FileResponse
    from fastapi import HTTPException
    
    item = await db.get(Knowledge, knowledge_id)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge not found")
    
    if not item.file_path or not os.path.exists(item.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    
    # 安全检查：确保文件路径在UPLOADS_DIR内（用get_uploads_dir()获取）
    real_path = os.path.realpath(item.file_path)
    uploads_real = os.path.realpath(str(get_uploads_dir()))
    if not real_path.startswith(uploads_real):
        raise HTTPException(status_code=403, detail="Access denied")
    
    return FileResponse(
        path=item.file_path,
        filename=item.name,
        media_type="application/octet-stream",
    )
