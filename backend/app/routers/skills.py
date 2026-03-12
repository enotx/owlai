# backend/app/routers/skills.py

"""Skill 动态技能 CRUD 路由"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Skill
from app.schemas import (
    SkillCreate,
    SkillUpdate,
    SkillResponse,
)

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=list[SkillResponse])
async def list_skills(db: AsyncSession = Depends(get_db)):          # ← get_db
    """获取所有 Skill"""
    result = await db.execute(select(Skill).order_by(Skill.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str, db: AsyncSession = Depends(get_db)):    # ← get_db
    """获取单个 Skill"""
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.post("", response_model=SkillResponse, status_code=201)
async def create_skill(
    body: SkillCreate,
    db: AsyncSession = Depends(get_db),                              # ← get_db
):
    """创建新 Skill"""
    # 检查 name 是否重复
    existing = await db.execute(select(Skill).where(Skill.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Skill name '{body.name}' already exists")

    import json
    skill = Skill(
        name=body.name,
        description=body.description,
        prompt_markdown=body.prompt_markdown,
        env_vars_json=json.dumps(body.env_vars, ensure_ascii=False) if body.env_vars else "{}",
        allowed_modules_json=json.dumps(body.allowed_modules, ensure_ascii=False) if body.allowed_modules else "[]",
        is_active=body.is_active,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return skill


@router.patch("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: str,
    body: SkillUpdate,
    db: AsyncSession = Depends(get_db),                              # ← get_db
):
    """更新 Skill"""
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    import json

    if body.name is not None:
        # 检查新 name 是否与其他 Skill 冲突
        existing = await db.execute(
            select(Skill).where(Skill.name == body.name, Skill.id != skill_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Skill name '{body.name}' already exists")
        skill.name = body.name

    if body.description is not None:
        skill.description = body.description
    if body.prompt_markdown is not None:
        skill.prompt_markdown = body.prompt_markdown
    if body.env_vars is not None:
        skill.env_vars_json = json.dumps(body.env_vars, ensure_ascii=False)
    if body.allowed_modules is not None:
        skill.allowed_modules_json = json.dumps(body.allowed_modules, ensure_ascii=False)
    if body.is_active is not None:
        skill.is_active = body.is_active

    await db.commit()
    await db.refresh(skill)
    return skill


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),                              # ← get_db
):
    """删除 Skill"""
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    await db.delete(skill)
    await db.commit()