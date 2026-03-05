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

# 上传根目录（相对于后端工作目录）
UPLOAD_ROOT = os.path.join("data", "uploads")

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.post("", response_model=KnowledgeResponse)
async def upload_knowledge(
    task_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传 Knowledge 文件（CSV/文本），保存到磁盘并解析元数据"""
    filename = file.filename or "unknown"
    file_type = "csv" if filename.lower().endswith(".csv") else "text"

    # 1-1：按 task_{id} 隔离创建目录
    task_dir = os.path.join(UPLOAD_ROOT, f"task_{task_id}")
    os.makedirs(task_dir, exist_ok=True)

    # 1-2：文件落盘
    file_path = os.path.join(task_dir, filename)
    content = await file.read()
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    # 1-3：CSV 元数据解析
    metadata_json = None
    if file_type == "csv":
        try:
            metadata_json = parse_csv_metadata(file_path)
        except Exception as e:
            # 解析失败不阻塞上传，记录错误信息到 metadata
            metadata_json = f'{{"parse_error": "{str(e)}"}}'

    # 写入数据库
    knowledge = Knowledge(
        task_id=task_id,
        type=file_type,
        name=filename,
        file_path=file_path,
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

    # 1-4：级联清理磁盘文件
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
    db: AsyncSession = Depends(get_db),
):
    """预览 Knowledge 数据：CSV 返回前 N 行表格，文本返回内容"""
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
    else:
        # 文本文件：返回前 1000 字符
        async with aiofiles.open(item.file_path, "r", encoding="utf-8") as f:
            content = await f.read(1000)
        return {
            "knowledge_id": knowledge_id,
            "type": "text",
            "content": content,
            "columns": [],
            "rows": [],
            "total_rows": 0,
        }