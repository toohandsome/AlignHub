from __future__ import annotations

from app.core import SecretCodec
from app.entities import (
    AgentConfig,
    ChatSession,
    DiscussionEvent,
    DiscussionRun,
    FeishuAgentBotConfig,
    FinalReport,
    MCPServerConfig,
    ModelConfig,
    ProviderConfig,
    ToolCallLog,
    ToolDefinition,
)
from app.schemas import (
    AgentRead,
    ChatSessionRead,
    EventRead,
    FeishuAgentBotConfigRead,
    FeishuConfigRead,
    MCPServerRead,
    ModelRead,
    ProviderRead,
    ReportRead,
    ReportSummaryRead,
    RunRead,
    ToolLogRead,
    ToolRead,
)


def provider_to_read(row: ProviderConfig) -> ProviderRead:
    return ProviderRead(
        id=row.id,
        provider_type=row.provider_type,
        name=row.name,
        base_url=row.base_url,
        organization=row.organization,
        extra_config_json=row.extra_config_json,
        api_key_masked=SecretCodec.mask(SecretCodec.decode(row.api_key_encrypted)),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def agent_to_read(row: AgentConfig) -> AgentRead:
    return AgentRead(
        id=row.id,
        name=row.name,
        role=row.role,
        persona=row.persona,
        system_prompt=row.system_prompt,
        model_id=row.model_id,
        memory_strategy=row.memory_strategy,
        max_steps=row.max_steps,
        is_moderator=row.is_moderator,
        extra_config_json=row.extra_config_json,
        tool_names=[binding.tool.name for binding in row.tool_bindings],
        skill_ids=[binding.skill.id for binding in row.skill_bindings],
        skill_names=[binding.skill.name for binding in row.skill_bindings],
        mcp_ids=[binding.mcp.id for binding in row.mcp_bindings],
        mcp_names=[binding.mcp.name for binding in row.mcp_bindings],
        feishu_bot_id=row.feishu_bot.id if row.feishu_bot else None,
        feishu_bot_name=(row.feishu_bot.bot_name or row.name) if row.feishu_bot else None,
        feishu_bot_enabled=bool(row.feishu_bot.enabled) if row.feishu_bot else False,
        feishu_bot_receive_enabled=bool(row.feishu_bot.receive_enabled) if row.feishu_bot else False,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def session_to_read(row: ChatSession) -> ChatSessionRead:
    return ChatSessionRead(
        id=row.id,
        name=row.name,
        topic=row.topic,
        max_rounds=row.max_rounds,
        status=row.status,
        agent_ids=[link.agent_id for link in sorted(row.agents, key=lambda item: item.speak_order)],
        feishu_chat_id=row.feishu_chat_id,
        feishu_topic_root_id=row.feishu_topic_root_id,
        feishu_enabled=row.feishu_enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def feishu_config_to_read(row) -> FeishuConfigRead:
    if not row:
        return FeishuConfigRead()
    return FeishuConfigRead(
        id=row.id,
        app_id=row.app_id,
        app_secret=SecretCodec.decode(row.app_secret_encrypted) or "",
        verification_token=SecretCodec.decode(row.verification_token_encrypted) or "",
        bot_name=row.bot_name,
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def feishu_agent_bot_to_read(agent_id: str, row: FeishuAgentBotConfig | None, *, agent_name: str | None = None) -> FeishuAgentBotConfigRead:
    if not row:
        return FeishuAgentBotConfigRead(agent_id=agent_id, agent_name=agent_name)
    return FeishuAgentBotConfigRead(
        id=row.id,
        agent_id=row.agent_id,
        agent_name=agent_name,
        app_id=row.app_id,
        app_secret=SecretCodec.decode(row.app_secret_encrypted) or "",
        verification_token=SecretCodec.decode(row.verification_token_encrypted) or "",
        bot_name=row.bot_name,
        enabled=row.enabled,
        receive_enabled=row.receive_enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def model_to_read(row: ModelConfig) -> ModelRead:
    return ModelRead(
        id=row.id,
        provider_id=row.provider_id,
        model_name=row.model_name,
        temperature=row.temperature,
        max_tokens=row.max_tokens,
        top_p=row.top_p,
        stream_enabled=row.stream_enabled,
        formatter_type=row.formatter_type,
        extra_config_json=row.extra_config_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def tool_to_read(row: ToolDefinition) -> ToolRead:
    return ToolRead(
        id=row.id,
        name=row.name,
        category=row.category,
        description=row.description,
        schema_json=row.schema_json,
        builtin=row.builtin,
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def mcp_to_read(row: MCPServerConfig) -> MCPServerRead:
    return MCPServerRead(
        id=row.id,
        name=row.name,
        transport_type=row.transport_type,
        description=row.description,
        command=row.command,
        args_json=list(row.args_json or []),
        env_json=dict(row.env_json or {}),
        base_url=row.base_url,
        jar_path=row.jar_path,
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def report_summary_to_read(row: FinalReport | None) -> ReportSummaryRead | None:
    if not row:
        return None
    return ReportSummaryRead(
        id=row.id,
        run_id=row.run_id,
        title=row.title,
        created_at=row.created_at,
    )


def run_to_read(row: DiscussionRun) -> RunRead:
    return RunRead(
        id=row.id,
        session_id=row.session_id,
        status=row.status,
        current_round=row.current_round,
        started_at=row.started_at,
        ended_at=row.ended_at,
        stop_reason=row.stop_reason,
        latest_report=report_summary_to_read(row.latest_report),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def event_to_read(row: DiscussionEvent) -> EventRead:
    return EventRead(
        id=row.id,
        run_id=row.run_id,
        seq=row.seq,
        round_no=row.round_no,
        event_type=row.event_type,
        agent_id=row.agent_id,
        tool_name=row.tool_name,
        payload_json=dict(row.payload_json or {}),
        created_at=row.created_at,
    )


def report_to_read(row: FinalReport) -> ReportRead:
    return ReportRead(
        id=row.id,
        run_id=row.run_id,
        title=row.title,
        summary_markdown=row.summary_markdown,
        conclusion_json=dict(row.conclusion_json or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def tool_log_to_read(row: ToolCallLog) -> ToolLogRead:
    return ToolLogRead(
        id=row.id,
        run_id=row.run_id,
        round_no=row.round_no,
        agent_id=row.agent_id,
        call_id=row.call_id,
        tool_name=row.tool_name,
        tool_input_json=dict(row.tool_input_json or {}),
        tool_output_json=dict(row.tool_output_json or {}),
        status=row.status,
        started_at=row.started_at,
        ended_at=row.ended_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
