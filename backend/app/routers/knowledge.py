# backend/app/routers/knowledge.py

"""Knowledge 管理 API：上传/列表/删除/预览"""

import os
import shutil
import aiofiles
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Knowledge
from app.schemas import KnowledgeResponse
from app.services.data_processor import parse_csv_metadata, get_csv_preview
from app.config import UPLOADS_DIR  # 新增：导入动态路径

from app.services.data_processor import (
    parse_csv_metadata, 
    parse_excel_metadata,  # 新增
    get_csv_preview,
    get_excel_preview,     # 新增
    read_text_content      # 新增
)


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


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
    task_dir = UPLOADS_DIR / task_id
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
    if item.type == "csv":
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
    
    # 安全检查：确保文件路径在UPLOADS_DIR内
    real_path = os.path.realpath(item.file_path)
    uploads_real = os.path.realpath(UPLOADS_DIR)
    if not real_path.startswith(uploads_real):
        raise HTTPException(status_code=403, detail="Access denied")
    
    return FileResponse(
        path=item.file_path,
        filename=item.name,
        media_type="application/octet-stream",
    )
