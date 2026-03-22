from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.entities import AgentConfig, AgentMCPBinding, AgentSkillBinding, AgentToolBinding, ChatSession, ModelConfig, ProviderConfig
from app.services import commit_or_409, flush_or_409, sync_agent_tools, sync_session_agents

router = APIRouter()


@router.post("/demo/bootstrap")
async def bootstrap_demo():
    async with SessionLocal() as db:
        provider = (await db.execute(select(ProviderConfig).where(ProviderConfig.name == "mock-dev"))).scalar_one_or_none()
        if not provider:
            provider = ProviderConfig(provider_type="mock", name="mock-dev")
            db.add(provider)
            await commit_or_409(db, entity_name="provider")
            await db.refresh(provider)

        model = (
            await db.execute(
                select(ModelConfig).where(
                    ModelConfig.provider_id == provider.id,
                    ModelConfig.model_name == "mock-gpt",
                ),
            )
        ).scalar_one_or_none()
        if not model:
            model = ModelConfig(provider_id=provider.id, model_name="mock-gpt", temperature=0.3, max_tokens=600, formatter_type="auto")
            db.add(model)
            await commit_or_409(db, entity_name="model")
            await db.refresh(model)

        specs = [
            (
                "Software Architect",
                "架构师",
                "你是一名软件架构师，关注系统边界、模块划分、可扩展性，并在必要时调用工具验证结论。",
                ["topic_probe", "list_files", "read_file", "git_status", "git_diff"],
                True,
            ),
            (
                "Backend Engineer",
                "后端工程师",
                "你是一名后端工程师，关注 API、数据模型、并发、稳定性，并在必要时调用工具检查文件与 Git 状态。",
                ["list_files", "read_file", "write_file", "edit_file", "git_status", "git_diff", "git_log"],
                False,
            ),
            (
                "Product Manager",
                "产品经理",
                "你是一名产品经理，关注用户价值、范围控制、交付优先级，必要时调用 topic_probe 理清讨论焦点。",
                ["topic_probe"],
                False,
            ),
        ]
        agent_ids = []
        for name, role, prompt, tools, is_moderator in specs:
            agent = await _load_agent_by_name(db, name)
            if not agent:
                agent = AgentConfig(name=name, role=role, persona=role, system_prompt=prompt, model_id=model.id, is_moderator=is_moderator)
                db.add(agent)
                await flush_or_409(db, entity_name="agent")
            else:
                agent.role = role
                agent.persona = role
                agent.system_prompt = prompt
                agent.model_id = model.id
                agent.is_moderator = is_moderator
            await sync_agent_tools(db, agent.id, tools)
            agent_ids.append(agent.id)
        await commit_or_409(db, entity_name="agent")

        session = (await db.execute(select(ChatSession).where(ChatSession.name == "AlignHub Demo Discussion"))).scalar_one_or_none()
        if not session:
            session = ChatSession(
                name="AlignHub Demo Discussion",
                topic="设计一个面向多智能体协同、共识收敛与联合决策的平台后端架构",
                max_rounds=10,
                status="draft",
            )
            db.add(session)
            await flush_or_409(db, entity_name="chat session")
        await sync_session_agents(db, session.id, agent_ids)
        await commit_or_409(db, entity_name="chat session")
        await db.refresh(session)
        return {"provider_id": provider.id, "model_id": model.id, "agent_ids": agent_ids, "session_id": session.id}


async def _load_agent_by_name(db: AsyncSession, name: str) -> AgentConfig | None:
    res = await db.execute(
        select(AgentConfig)
        .options(selectinload(AgentConfig.tool_bindings).selectinload(AgentToolBinding.tool))
        .options(selectinload(AgentConfig.skill_bindings).selectinload(AgentSkillBinding.skill))
        .options(selectinload(AgentConfig.mcp_bindings).selectinload(AgentMCPBinding.mcp))
        .where(AgentConfig.name == name)
    )
    return res.scalar_one_or_none()
