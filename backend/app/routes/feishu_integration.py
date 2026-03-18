from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.entities import AgentConfig
from app.feishu import FeishuBridgeService
from app.routes.common import get_feishu_bridge
from app.schemas import FeishuAgentBotConfigRead, FeishuChatDiagnoseItem, FeishuChatDiagnoseRequest, FeishuConfigRead, FeishuConfigUpdate, FeishuTestSendRequest
from app.services import feishu_agent_bot_to_read, feishu_config_to_read

router = APIRouter()


@router.get("/integrations/feishu/config", response_model=FeishuConfigRead)
async def get_feishu_config(feishu_bridge: FeishuBridgeService = Depends(get_feishu_bridge)):
    """读取 Host Bot 飞书配置。"""
    row = await feishu_bridge.get_config()
    return feishu_config_to_read(row)


@router.get("/integrations/feishu/agent-bots", response_model=list[FeishuAgentBotConfigRead])
async def list_feishu_agent_bots(db: AsyncSession = Depends(get_db)):
    """列出所有已绑定的 Agent Bot。"""
    res = await db.execute(
        select(AgentConfig)
        .options(selectinload(AgentConfig.feishu_bot))
        .order_by(AgentConfig.created_at.asc())
    )
    agents = res.scalars().all()
    return [feishu_agent_bot_to_read(agent.id, agent.feishu_bot, agent_name=agent.name) for agent in agents if agent.feishu_bot]


@router.put("/integrations/feishu/config", response_model=FeishuConfigRead)
async def update_feishu_config(payload: FeishuConfigUpdate, feishu_bridge: FeishuBridgeService = Depends(get_feishu_bridge)):
    """更新 Host Bot 配置。"""
    row = await feishu_bridge.upsert_config(
        app_id=payload.app_id,
        app_secret=payload.app_secret,
        verification_token=payload.verification_token,
        bot_name=payload.bot_name,
        enabled=payload.enabled,
    )
    return feishu_config_to_read(row)


@router.post("/integrations/feishu/test-send")
async def test_feishu_send(payload: FeishuTestSendRequest, feishu_bridge: FeishuBridgeService = Depends(get_feishu_bridge)):
    """发送一条飞书测试消息。"""
    try:
        return await feishu_bridge.test_send(payload.chat_id, payload.text, agent_id=payload.agent_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/integrations/feishu/diagnose-chat", response_model=list[FeishuChatDiagnoseItem])
async def diagnose_feishu_chat(payload: FeishuChatDiagnoseRequest, feishu_bridge: FeishuBridgeService = Depends(get_feishu_bridge)):
    """检查各个 Agent Bot 是否在指定群内。"""
    try:
        return await feishu_bridge.diagnose_chat(payload.chat_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/integrations/feishu/events")
async def feishu_events(payload: dict, feishu_bridge: FeishuBridgeService = Depends(get_feishu_bridge)):
    """飞书事件回调入口。"""
    try:
        return await feishu_bridge.handle_callback(payload)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
