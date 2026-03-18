from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import SecretCodec
from app.db import get_db
from app.entities import AgentConfig, AgentMCPBinding, AgentSkillBinding, AgentToolBinding, FeishuAgentBotConfig, ModelConfig
from app.schemas import AgentCreate, AgentRead, AgentUpdate, FeishuAgentBotConfigRead, FeishuAgentBotConfigUpdate
from app.services import (
    agent_to_read,
    commit_or_409,
    delete_and_commit_or_409,
    feishu_agent_bot_to_read,
    flush_or_409,
    load_agent,
    sync_agent_mcps,
    sync_agent_skills,
    sync_agent_tools,
)

router = APIRouter()


@router.get("/agents", response_model=list[AgentRead])
async def list_agents(db: AsyncSession = Depends(get_db)):
    """查询 Agent 列表及其挂载信息。"""
    res = await db.execute(
        select(AgentConfig)
        .options(selectinload(AgentConfig.tool_bindings).selectinload(AgentToolBinding.tool))
        .options(selectinload(AgentConfig.skill_bindings).selectinload(AgentSkillBinding.skill))
        .options(selectinload(AgentConfig.mcp_bindings).selectinload(AgentMCPBinding.mcp))
        .options(selectinload(AgentConfig.feishu_bot))
        .order_by(AgentConfig.created_at.desc())
    )
    return [agent_to_read(item) for item in res.scalars().all()]


@router.post("/agents", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(payload: AgentCreate, db: AsyncSession = Depends(get_db)):
    """创建 Agent，并同步 Tool / Skill / MCP 绑定。"""
    if not await db.get(ModelConfig, payload.model_id):
        raise HTTPException(400, "Model not found")
    row = AgentConfig(**payload.model_dump(exclude={"tool_names", "skill_ids", "mcp_ids"}))
    db.add(row)
    await flush_or_409(db, entity_name="agent")
    try:
        await sync_agent_tools(db, row.id, payload.tool_names)
        await sync_agent_skills(db, row.id, payload.skill_ids)
        await sync_agent_mcps(db, row.id, payload.mcp_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await commit_or_409(db, entity_name="agent")
    loaded = await load_agent(db, row.id)
    return agent_to_read(loaded)


@router.get("/agents/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    """查看单个 Agent 详情。"""
    row = await load_agent(db, agent_id)
    if not row:
        raise HTTPException(404, "Agent not found")
    return agent_to_read(row)


@router.put("/agents/{agent_id}", response_model=AgentRead)
async def update_agent(agent_id: str, payload: AgentUpdate, db: AsyncSession = Depends(get_db)):
    """更新 Agent 及其挂载关系。"""
    row = await load_agent(db, agent_id)
    if not row:
        raise HTTPException(404, "Agent not found")
    data = payload.model_dump(exclude_unset=True, exclude={"tool_names", "skill_ids", "mcp_ids"})
    for key, value in data.items():
        setattr(row, key, value)
    if payload.tool_names is not None:
        try:
            await sync_agent_tools(db, row.id, payload.tool_names)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if payload.skill_ids is not None:
        try:
            await sync_agent_skills(db, row.id, payload.skill_ids)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if payload.mcp_ids is not None:
        try:
            await sync_agent_mcps(db, row.id, payload.mcp_ids)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    await commit_or_409(db, entity_name="agent")
    loaded = await load_agent(db, agent_id)
    return agent_to_read(loaded)


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    """删除 Agent。"""
    row = await db.get(AgentConfig, agent_id)
    if not row:
        raise HTTPException(404, "Agent not found")
    await delete_and_commit_or_409(db, row, entity_name="agent")


@router.get("/agents/{agent_id}/feishu-bot", response_model=FeishuAgentBotConfigRead)
async def get_agent_feishu_bot(agent_id: str, db: AsyncSession = Depends(get_db)):
    """查询某个 Agent 绑定的飞书 Bot 配置。"""
    agent = await load_agent(db, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return feishu_agent_bot_to_read(agent_id, agent.feishu_bot, agent_name=agent.name)


@router.put("/agents/{agent_id}/feishu-bot", response_model=FeishuAgentBotConfigRead)
async def update_agent_feishu_bot(agent_id: str, payload: FeishuAgentBotConfigUpdate, db: AsyncSession = Depends(get_db)):
    """为 Agent 创建或更新独立飞书 Bot。"""
    agent = await load_agent(db, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    if agent.feishu_bot:
        row = agent.feishu_bot
        row.app_id = payload.app_id
        if payload.app_secret is not None:
            row.app_secret_encrypted = SecretCodec.encode(payload.app_secret)
        if payload.verification_token is not None:
            row.verification_token_encrypted = SecretCodec.encode(payload.verification_token)
        row.bot_name = payload.bot_name
        row.enabled = payload.enabled
        row.receive_enabled = payload.receive_enabled
    else:
        row = FeishuAgentBotConfig(
            agent_id=agent_id,
            app_id=payload.app_id,
            app_secret_encrypted=SecretCodec.encode(payload.app_secret),
            verification_token_encrypted=SecretCodec.encode(payload.verification_token),
            bot_name=payload.bot_name,
            enabled=payload.enabled,
            receive_enabled=payload.receive_enabled,
        )
        db.add(row)

    await commit_or_409(db, entity_name="feishu agent bot")
    await db.refresh(row)
    return feishu_agent_bot_to_read(agent_id, row, agent_name=agent.name)


@router.delete("/agents/{agent_id}/feishu-bot", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_feishu_bot(agent_id: str, db: AsyncSession = Depends(get_db)):
    """删除 Agent 的飞书 Bot 绑定。"""
    agent = await load_agent(db, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    if agent.feishu_bot:
        await delete_and_commit_or_409(db, agent.feishu_bot, entity_name="feishu agent bot")
