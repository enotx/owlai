# backend/app/routers/knowledge.py

"""Knowledge 管理 API（占位实现）"""

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Knowledge
from app.schemas import KnowledgeResponse

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.post("", response_model=KnowledgeResponse)
async def upload_knowledge(
    task_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传 Knowledge 文件（CSV/文本）— 占位实现"""
    # TODO: 保存文件到磁盘、解析 CSV 元数据
    knowledge = Knowledge(
        task_id=task_id,
        type="csv" if file.filename and file.filename.endswith(".csv") else "text",
        name=file.filename or "unknown",
        file_path=f"data/uploads/{task_id}/{file.filename}",
        metadata_json=None,
    )
    db.add(knowledge)
    await db.commit()
    await db.refresh(knowledge)
    return knowledge


@router.get("", response_model=list[KnowledgeResponse])
async def list_knowledge(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取指定 Task 的 Knowledge 列表"""
    result = await db.execute(select(Knowledge).where(Knowledge.task_id == task_id))
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
    """删除 Knowledge"""
    item = await db.get(Knowledge, knowledge_id)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge not found")
    await db.delete(item)
    await db.commit()
    return {"detail": "Knowledge deleted"}


@router.get("/{knowledge_id}/preview")
async def preview_knowledge(knowledge_id: str, db: AsyncSession = Depends(get_db)):
    """预览 Knowledge 数据 — 占位实现"""
    # TODO: 读取文件并返回预览数据
    return {"knowledge_id": knowledge_id, "preview": "TODO"}