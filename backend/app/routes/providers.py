from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import SecretCodec
from app.db import get_db
from app.entities import ModelConfig, ProviderConfig
from app.services.runtime_probes import test_model_connection
from app.schemas import ModelCreate, ModelRead, ModelUpdate, ProviderCreate, ProviderRead, ProviderUpdate
from app.services import commit_or_409, delete_and_commit_or_409, model_to_read, provider_to_read

router = APIRouter()


@router.get("/providers", response_model=list[ProviderRead])
async def list_providers(db: AsyncSession = Depends(get_db)):
    """查询 Provider 列表，按创建时间倒序返回。"""
    res = await db.execute(select(ProviderConfig).order_by(ProviderConfig.created_at.desc()))
    return [provider_to_read(item) for item in res.scalars().all()]


@router.post("/providers", response_model=ProviderRead, status_code=status.HTTP_201_CREATED)
async def create_provider(payload: ProviderCreate, db: AsyncSession = Depends(get_db)):
    """创建 Provider，并对敏感字段做统一编码。"""
    row = ProviderConfig(
        provider_type=payload.provider_type,
        name=payload.name,
        api_key_encrypted=SecretCodec.encode(payload.api_key),
        base_url=payload.base_url,
        organization=payload.organization,
        extra_config_json=payload.extra_config_json,
    )
    db.add(row)
    await commit_or_409(db, entity_name="provider")
    await db.refresh(row)
    return provider_to_read(row)


@router.put("/providers/{provider_id}", response_model=ProviderRead)
async def update_provider(provider_id: str, payload: ProviderUpdate, db: AsyncSession = Depends(get_db)):
    """更新指定 Provider。"""
    row = await db.get(ProviderConfig, provider_id)
    if not row:
        raise HTTPException(404, "Provider not found")
    data = payload.model_dump(exclude_unset=True)
    if "api_key" in data:
        row.api_key_encrypted = SecretCodec.encode(data.pop("api_key"))
    for key, value in data.items():
        setattr(row, key, value)
    await commit_or_409(db, entity_name="provider")
    await db.refresh(row)
    return provider_to_read(row)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    """删除 Provider。"""
    row = await db.get(ProviderConfig, provider_id)
    if not row:
        raise HTTPException(404, "Provider not found")
    await delete_and_commit_or_409(db, row, entity_name="provider")


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    """测试 Provider 连通性。

    当前实现会优先取该 Provider 下的第一个模型做连通性探测。
    """
    provider = await db.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    res = await db.execute(select(ModelConfig).where(ModelConfig.provider_id == provider_id).order_by(ModelConfig.created_at.asc()))
    model = res.scalars().first()
    if not model:
        if provider.provider_type == "mock":
            return {"success": True, "provider_type": provider.provider_type, "message": "Mock provider is configured."}
        raise HTTPException(400, "No model configured under this provider")
    return await test_model_connection(provider, model)


@router.get("/models", response_model=list[ModelRead])
async def list_models(db: AsyncSession = Depends(get_db)):
    """查询模型列表。"""
    res = await db.execute(select(ModelConfig).order_by(ModelConfig.created_at.desc()))
    return [model_to_read(item) for item in res.scalars().all()]


@router.post("/models", response_model=ModelRead, status_code=status.HTTP_201_CREATED)
async def create_model(payload: ModelCreate, db: AsyncSession = Depends(get_db)):
    """创建模型配置。"""
    if not await db.get(ProviderConfig, payload.provider_id):
        raise HTTPException(400, "Provider not found")
    row = ModelConfig(**payload.model_dump())
    db.add(row)
    await commit_or_409(db, entity_name="model")
    await db.refresh(row)
    return model_to_read(row)


@router.put("/models/{model_id}", response_model=ModelRead)
async def update_model(model_id: str, payload: ModelUpdate, db: AsyncSession = Depends(get_db)):
    """更新模型配置。"""
    row = await db.get(ModelConfig, model_id)
    if not row:
        raise HTTPException(404, "Model not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await commit_or_409(db, entity_name="model")
    await db.refresh(row)
    return model_to_read(row)


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: str, db: AsyncSession = Depends(get_db)):
    """删除模型配置。"""
    row = await db.get(ModelConfig, model_id)
    if not row:
        raise HTTPException(404, "Model not found")
    await delete_and_commit_or_409(db, row, entity_name="model")


@router.post("/models/{model_id}/test")
async def test_model(model_id: str, db: AsyncSession = Depends(get_db)):
    """直接测试某个模型配置的可用性。"""
    model = await db.get(ModelConfig, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    provider = await db.get(ProviderConfig, model.provider_id)
    if not provider:
        raise HTTPException(400, "Provider not found")
    return await test_model_connection(provider, model)
