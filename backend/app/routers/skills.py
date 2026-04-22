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

def _skill_to_response(s) -> SkillResponse:
    """将 Skill ORM 对象转为响应模型（统一序列化逻辑）"""
    import json
    
    # 反序列化 handler_config
    handler_config = None
    if s.handler_config:
        try:
            handler_config = json.loads(s.handler_config)
        except json.JSONDecodeError:
            pass
    
    return SkillResponse(
        id=s.id,
        name=s.name,
        description=s.description,
        prompt_markdown=s.prompt_markdown,
        reference_markdown=s.reference_markdown,
        handler_type=s.handler_type or "standard",
        handler_config=handler_config,
        env_vars=json.loads(s.env_vars_json) if s.env_vars_json else {},
        allowed_modules=json.loads(s.allowed_modules_json) if s.allowed_modules_json else [],
        is_active=s.is_active,
        is_system=s.is_system,
        slash_command=s.slash_command,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("", response_model=list[SkillResponse])
async def list_skills(db: AsyncSession = Depends(get_db)):
    """获取所有 Skill"""
    result = await db.execute(select(Skill).order_by(Skill.created_at.desc()))
    return [_skill_to_response(s) for s in result.scalars().all()]


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个 Skill"""
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return _skill_to_response(skill)

@router.post("", response_model=SkillResponse, status_code=201)
async def create_skill(
    body: SkillCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建新 Skill"""
    import json

    # 检查 name 是否重复
    existing = await db.execute(select(Skill).where(Skill.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Skill name '{body.name}' already exists")

    # 检查 slash_command 是否重复
    if body.slash_command:
        existing_cmd = await db.execute(
            select(Skill).where(Skill.slash_command == body.slash_command)
        )
        if existing_cmd.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Slash command '/{body.slash_command}' already in use",
            )
    # 序列化 handler_config
    handler_config_json = None
    if body.handler_config:
        handler_config_json = json.dumps(body.handler_config, ensure_ascii=False)

    skill = Skill(
        name=body.name,
        description=body.description,
        prompt_markdown=body.prompt_markdown,
        reference_markdown=body.reference_markdown,
        handler_type=body.handler_type or "standard",
        handler_config=handler_config_json,
        env_vars_json=json.dumps(body.env_vars, ensure_ascii=False) if body.env_vars else "{}",
        allowed_modules_json=json.dumps(body.allowed_modules, ensure_ascii=False) if body.allowed_modules else "[]",
        is_active=body.is_active,
        is_system=body.is_system,
        slash_command=body.slash_command,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return _skill_to_response(skill)


@router.patch("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: str,
    body: SkillUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新 Skill"""
    import json

    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    # 系统 Skill 保护：不允许改名或改 slash_command
    if skill.is_system:
        if body.name is not None and body.name != skill.name:
            raise HTTPException(status_code=403, detail="Cannot rename a system skill")
        if body.slash_command is not None and body.slash_command != skill.slash_command:
            raise HTTPException(status_code=403, detail="Cannot change slash command of a system skill")
        if body.handler_type is not None and body.handler_type != skill.handler_type:
            raise HTTPException(status_code=403, detail="Cannot change handler type of a system skill")

    if body.name is not None:
        existing = await db.execute(
            select(Skill).where(Skill.name == body.name, Skill.id != skill_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Skill name '{body.name}' already exists")
        skill.name = body.name

    if body.slash_command is not None:
        if body.slash_command:  # non-empty
            existing_cmd = await db.execute(
                select(Skill).where(
                    Skill.slash_command == body.slash_command,
                    Skill.id != skill_id,
                )
            )
            if existing_cmd.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail=f"Slash command '/{body.slash_command}' already in use",
                )
        skill.slash_command = body.slash_command or None

    if body.description is not None:
        skill.description = body.description
    if body.prompt_markdown is not None:
        skill.prompt_markdown = body.prompt_markdown
    if body.reference_markdown is not None:
        skill.reference_markdown = body.reference_markdown
    if body.env_vars is not None:
        skill.env_vars_json = json.dumps(body.env_vars, ensure_ascii=False)
    if body.allowed_modules is not None:
        skill.allowed_modules_json = json.dumps(body.allowed_modules, ensure_ascii=False)
    if body.is_active is not None:
        skill.is_active = body.is_active
    # is_system 不允许通过 API 修改（防止用户把系统 skill 变成非系统）

    await db.commit()
    await db.refresh(skill)
    return _skill_to_response(skill)


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除 Skill（系统 Skill 不可删除）"""
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.is_system:
        raise HTTPException(status_code=403, detail="Cannot delete a system skill")
    await db.delete(skill)
    await db.commit()

from datetime import datetime
import yaml
from fastapi.responses import Response
# 敏感关键词列表（不区分大小写）
SENSITIVE_KEYWORDS = [
    "password", "token", "key", "secret", 
    "credential", "auth", "api_key", "access"
]
def _mask_sensitive_value(key: str, value: str) -> str:
    """如果 key 包含敏感关键词，返回占位符；否则返回原值"""
    key_lower = key.lower()
    for keyword in SENSITIVE_KEYWORDS:
        if keyword in key_lower:
            placeholder = f"YOUR_{key.upper()}"
            return placeholder
    return value
@router.get("/{skill_id}/export")
async def export_skill(skill_id: str, db: AsyncSession = Depends(get_db)):
    """导出 Skill 为 YAML 格式（敏感环境变量用占位符替代）"""
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    import json
    
    # 解析环境变量并替换敏感值
    env_vars = json.loads(skill.env_vars_json) if skill.env_vars_json else {}
    masked_env_vars = {
        k: _mask_sensitive_value(k, v) for k, v in env_vars.items()
    }
    
    # 解析 handler_config
    handler_config = None
    if skill.handler_config:
        try:
            handler_config = json.loads(skill.handler_config)
        except json.JSONDecodeError:
            pass
    
    export_data = {
        "version": "1.0",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "skill": {
            "name": skill.name,
            "description": skill.description,
            "handler_type": skill.handler_type or "standard",
            "handler_config": handler_config,
            "is_active": skill.is_active,
            "allowed_modules": json.loads(skill.allowed_modules_json) if skill.allowed_modules_json else [],
            "env_vars": masked_env_vars,
            "prompt_markdown": skill.prompt_markdown,
            "reference_markdown": skill.reference_markdown,
        }
    }
    
    # 生成 YAML
    yaml_content = yaml.dump(
        export_data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )
    
    filename = f"{skill.name.replace(' ', '_')}_skill.yaml"
    return Response(
        content=yaml_content,
        media_type="application/x-yaml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )

@router.post("/import", response_model=SkillResponse, status_code=201)
async def import_skill(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """导入 Skill（支持 YAML 或 JSON 格式）"""
    import json
    
    # 验证格式
    if "skill" not in body:
        raise HTTPException(status_code=400, detail="Invalid import format: missing 'skill' key")
    
    skill_data = body["skill"]
    required_fields = ["name"]
    for field in required_fields:
        if field not in skill_data:
            raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
    
    # 检查名称是否已存在
    existing = await db.execute(select(Skill).where(Skill.name == skill_data["name"]))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409, 
            detail=f"Skill name '{skill_data['name']}' already exists. Please rename before importing."
        )
    
    # 序列化 handler_config
    handler_config_json = None
    if skill_data.get("handler_config"):
        handler_config_json = json.dumps(skill_data["handler_config"], ensure_ascii=False)
    
    # 创建新 Skill
    skill = Skill(
        name=skill_data["name"],
        description=skill_data.get("description"),
        prompt_markdown=skill_data.get("prompt_markdown"),
        reference_markdown=skill_data.get("reference_markdown"),
        handler_type=skill_data.get("handler_type", "standard"),
        handler_config=handler_config_json,
        env_vars_json=json.dumps(skill_data.get("env_vars", {}), ensure_ascii=False),
        allowed_modules_json=json.dumps(skill_data.get("allowed_modules", []), ensure_ascii=False),
        is_active=skill_data.get("is_active", True),
        is_system=False,
        slash_command=None,
    )
    
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    
    return _skill_to_response(skill)
