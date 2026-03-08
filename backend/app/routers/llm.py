# backend/app/routers/llm.py

"""LLM Provider 配置管理路由"""

import json
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

from app.models import LLMProvider, AgentConfig
from app.schemas import (
    LLMProviderCreate,
    LLMProviderUpdate,
    LLMProviderResponse,
    LLMTestConnectionRequest,
    LLMTestConnectionResponse,
    AgentConfigUpdate,
    AgentConfigResponse,
)

router = APIRouter(prefix="/api/llm", tags=["LLM"])


@router.get("/providers", response_model=list[LLMProviderResponse])
async def list_providers(db: AsyncSession = Depends(get_db)):
    """获取所有 LLM Provider 配置"""
    result = await db.execute(select(LLMProvider).order_by(LLMProvider.created_at.desc()))
    providers = result.scalars().all()
    
    # 将 models_json 字符串解析为列表
    return [
        LLMProviderResponse(
            id=p.id,
            display_name=p.display_name,
            base_url=p.base_url,
            api_key=p.api_key,
            models=json.loads(p.models_json),
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in providers
    ]


@router.post("/providers", response_model=LLMProviderResponse, status_code=201)
async def create_provider(
    data: LLMProviderCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建新的 LLM Provider"""
    provider = LLMProvider(
        display_name=data.display_name,
        base_url=data.base_url,
        api_key=data.api_key,
        models_json=json.dumps([m.model_dump() for m in data.models]),
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    
    return LLMProviderResponse(
        id=provider.id,
        display_name=provider.display_name,
        base_url=provider.base_url,
        api_key=provider.api_key,
        models=json.loads(provider.models_json),
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


@router.get("/providers/{provider_id}", response_model=LLMProviderResponse)
async def get_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个 Provider 详情"""
    result = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    provider = result.scalar_one_or_none()
    
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    return LLMProviderResponse(
        id=provider.id,
        display_name=provider.display_name,
        base_url=provider.base_url,
        api_key=provider.api_key,
        models=json.loads(provider.models_json),
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


@router.patch("/providers/{provider_id}", response_model=LLMProviderResponse)
async def update_provider(
    provider_id: str,
    data: LLMProviderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新 Provider 配置"""
    result = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    provider = result.scalar_one_or_none()
    
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    # 更新字段
    if data.display_name is not None:
        provider.display_name = data.display_name
    if data.base_url is not None:
        provider.base_url = data.base_url
    if data.api_key is not None:
        provider.api_key = data.api_key
    if data.models is not None:
        provider.models_json = json.dumps([m.model_dump() for m in data.models])
    
    await db.commit()
    await db.refresh(provider)
    
    return LLMProviderResponse(
        id=provider.id,
        display_name=provider.display_name,
        base_url=provider.base_url,
        api_key=provider.api_key,
        models=json.loads(provider.models_json),
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    """删除 Provider"""
    result = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    provider = result.scalar_one_or_none()
    
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    await db.delete(provider)
    await db.commit()


@router.post("/providers/test-connection", response_model=LLMTestConnectionResponse)
async def test_connection(data: LLMTestConnectionRequest):
    """测试 LLM Provider 连通性"""
    try:
        headers = {"Content-Type": "application/json"}
        if data.api_key:
            headers["Authorization"] = f"Bearer {data.api_key}"
        
        # 尝试调用 /v1/models 端点（OpenAI 兼容接口标准）
        # 但实际代码中去掉/v1，因为有些服务可能不遵守此规则，比如Meituan的Friday，无语……
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{data.base_url.rstrip('/')}/models",
                headers=headers,
            )
            
            if response.status_code == 200:
                models_data = response.json()
                # 提取模型 ID 列表
                available_models = []
                if "data" in models_data:
                    available_models = [m.get("id", "") for m in models_data["data"]]
                
                return LLMTestConnectionResponse(
                    success=True,
                    message="Connection successful",
                    available_models=available_models,
                )
            else:
                return LLMTestConnectionResponse(
                    success=False,
                    message=f"HTTP {response.status_code}: {response.text[:200]}",
                )
    
    except httpx.TimeoutException:
        return LLMTestConnectionResponse(
            success=False,
            message="Connection timeout (10s)",
        )
    except Exception as e:
        return LLMTestConnectionResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
        )
    

# ===== Agent Config Routes =====
@router.get("/agents", response_model=list[AgentConfigResponse])
async def get_agent_configs(db: AsyncSession = Depends(get_db)):
    """获取所有 Agent 配置 (异步实现)"""
    result = await db.execute(select(AgentConfig))
    configs = result.scalars().all()
    
    # 如果数据库为空，初始化默认配置
    if not configs:
        default_types = ["default", "plan", "analyst", "misc"]
        for agent_type in default_types:
            config = AgentConfig(agent_type=agent_type)
            db.add(config)
        await db.commit()
        
        # 重新查询
        result = await db.execute(select(AgentConfig))
        configs = result.scalars().all()
    
    return configs
@router.patch("/agents/{agent_type}", response_model=AgentConfigResponse)
async def update_agent_config(
    agent_type: str,
    data: AgentConfigUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新指定 Agent 的配置 (异步实现)"""
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.agent_type == agent_type)
    )
    config = result.scalar_one_or_none()
    
    if not config:
        config = AgentConfig(agent_type=agent_type)
        db.add(config)
    
    if data.provider_id is not None:
        config.provider_id = data.provider_id
    if data.model_id is not None:
        config.model_id = data.model_id
    
    await db.commit()
    await db.refresh(config)
    
    return config
