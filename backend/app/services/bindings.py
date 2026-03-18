from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.entities import (
    AgentConfig,
    AgentMCPBinding,
    AgentSkillBinding,
    AgentToolBinding,
    ChatSession,
    ChatSessionAgent,
    MCPServerConfig,
    SkillDefinition,
    ToolDefinition,
)


async def load_agent(db: AsyncSession, agent_id: str) -> AgentConfig | None:
    res = await db.execute(
        select(AgentConfig)
        .options(selectinload(AgentConfig.tool_bindings).selectinload(AgentToolBinding.tool))
        .options(selectinload(AgentConfig.skill_bindings).selectinload(AgentSkillBinding.skill))
        .options(selectinload(AgentConfig.mcp_bindings).selectinload(AgentMCPBinding.mcp))
        .options(selectinload(AgentConfig.feishu_bot))
        .where(AgentConfig.id == agent_id)
    )
    return res.scalar_one_or_none()


async def load_session(db: AsyncSession, session_id: str) -> ChatSession | None:
    res = await db.execute(select(ChatSession).options(selectinload(ChatSession.agents)).where(ChatSession.id == session_id))
    return res.scalar_one_or_none()


async def sync_agent_tools(db: AsyncSession, agent_id: str, tool_names: list[str]) -> None:
    await db.execute(delete(AgentToolBinding).where(AgentToolBinding.agent_id == agent_id))
    if not tool_names:
        return
    res = await db.execute(select(ToolDefinition).where(ToolDefinition.name.in_(tool_names)))
    tools = {tool.name: tool for tool in res.scalars().all()}
    missing = [name for name in tool_names if name not in tools]
    if missing:
        raise ValueError(f"Tool(s) not found: {', '.join(missing)}")
    for name in tool_names:
        db.add(AgentToolBinding(agent_id=agent_id, tool_id=tools[name].id, config_json={}))


async def sync_agent_skills(db: AsyncSession, agent_id: str, skill_ids: list[str]) -> None:
    await db.execute(delete(AgentSkillBinding).where(AgentSkillBinding.agent_id == agent_id))
    if not skill_ids:
        return
    res = await db.execute(select(SkillDefinition).where(SkillDefinition.id.in_(skill_ids)))
    skills = {skill.id: skill for skill in res.scalars().all()}
    missing = [skill_id for skill_id in skill_ids if skill_id not in skills]
    if missing:
        raise ValueError(f"Skill(s) not found: {', '.join(missing)}")
    for skill_id in skill_ids:
        db.add(AgentSkillBinding(agent_id=agent_id, skill_id=skill_id, config_json={}))


async def sync_agent_mcps(db: AsyncSession, agent_id: str, mcp_ids: list[str]) -> None:
    await db.execute(delete(AgentMCPBinding).where(AgentMCPBinding.agent_id == agent_id))
    if not mcp_ids:
        return
    res = await db.execute(select(MCPServerConfig).where(MCPServerConfig.id.in_(mcp_ids)))
    mcps = {mcp.id: mcp for mcp in res.scalars().all()}
    missing = [mcp_id for mcp_id in mcp_ids if mcp_id not in mcps]
    if missing:
        raise ValueError(f"MCP(s) not found: {', '.join(missing)}")
    for mcp_id in mcp_ids:
        db.add(AgentMCPBinding(agent_id=agent_id, mcp_id=mcp_id, config_json={}))


async def sync_session_agents(db: AsyncSession, session_id: str, agent_ids: list[str]) -> None:
    await db.execute(delete(ChatSessionAgent).where(ChatSessionAgent.session_id == session_id))
    if not agent_ids:
        return
    res = await db.execute(select(AgentConfig.id).where(AgentConfig.id.in_(agent_ids)))
    existing = {row[0] for row in res.all()}
    missing = [agent_id for agent_id in agent_ids if agent_id not in existing]
    if missing:
        raise ValueError(f"Agent(s) not found: {', '.join(missing)}")
    for index, agent_id in enumerate(agent_ids, start=1):
        db.add(ChatSessionAgent(session_id=session_id, agent_id=agent_id, speak_order=index))
