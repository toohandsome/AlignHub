from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProviderConfig(Base, TimestampMixin):
    __tablename__ = "provider_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider_type: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128), unique=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(256), nullable=True)
    extra_config_json: Mapped[dict] = mapped_column(JSON, default=dict)

    models: Mapped[list["ModelConfig"]] = relationship(back_populates="provider", cascade="all, delete-orphan")


class ModelConfig(Base, TimestampMixin):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider_id: Mapped[str] = mapped_column(ForeignKey("provider_configs.id", ondelete="CASCADE"))
    model_name: Mapped[str] = mapped_column(String(128))
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1024)
    top_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    stream_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    formatter_type: Mapped[str] = mapped_column(String(64), default="auto")
    extra_config_json: Mapped[dict] = mapped_column(JSON, default=dict)

    provider: Mapped[ProviderConfig] = relationship(back_populates="models")
    agents: Mapped[list["AgentConfig"]] = relationship(back_populates="model")

    __table_args__ = (UniqueConstraint("provider_id", "model_name", name="uq_provider_model_name"),)


class ToolDefinition(Base, TimestampMixin):
    __tablename__ = "tool_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), unique=True)
    category: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    schema_json: Mapped[dict] = mapped_column(JSON, default=dict)
    builtin: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    bindings: Mapped[list["AgentToolBinding"]] = relationship(back_populates="tool", cascade="all, delete-orphan")


class SkillDefinition(Base, TimestampMixin):
    __tablename__ = "skill_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    package_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)

    bindings: Mapped[list["AgentSkillBinding"]] = relationship(back_populates="skill", cascade="all, delete-orphan")


class MCPServerConfig(Base, TimestampMixin):
    __tablename__ = "mcp_server_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), unique=True)
    transport_type: Mapped[str] = mapped_column(String(32), default="stdio")
    description: Mapped[str] = mapped_column(Text, default="")
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    args_json: Mapped[list] = mapped_column(JSON, default=list)
    env_json: Mapped[dict] = mapped_column(JSON, default=dict)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    jar_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    bindings: Mapped[list["AgentMCPBinding"]] = relationship(back_populates="mcp", cascade="all, delete-orphan")


class AgentConfig(Base, TimestampMixin):
    __tablename__ = "agent_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), unique=True)
    role: Mapped[str] = mapped_column(String(128))
    persona: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(ForeignKey("model_configs.id"))
    memory_strategy: Mapped[str] = mapped_column(String(32), default="in_memory")
    max_steps: Mapped[int] = mapped_column(Integer, default=6)
    is_moderator: Mapped[bool] = mapped_column(Boolean, default=False)
    is_reporter: Mapped[bool] = mapped_column(Boolean, default=False)
    extra_config_json: Mapped[dict] = mapped_column(JSON, default=dict)

    model: Mapped[ModelConfig] = relationship(back_populates="agents")
    tool_bindings: Mapped[list["AgentToolBinding"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    skill_bindings: Mapped[list["AgentSkillBinding"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    mcp_bindings: Mapped[list["AgentMCPBinding"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    session_links: Mapped[list["ChatSessionAgent"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    feishu_bot: Mapped["FeishuAgentBotConfig | None"] = relationship(back_populates="agent", cascade="all, delete-orphan", uselist=False)


class AgentToolBinding(Base):
    __tablename__ = "agent_tool_bindings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_configs.id", ondelete="CASCADE"))
    tool_id: Mapped[str] = mapped_column(ForeignKey("tool_definitions.id", ondelete="CASCADE"))
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)

    agent: Mapped[AgentConfig] = relationship(back_populates="tool_bindings")
    tool: Mapped[ToolDefinition] = relationship(back_populates="bindings")

    __table_args__ = (UniqueConstraint("agent_id", "tool_id", name="uq_agent_tool"),)


class AgentSkillBinding(Base):
    __tablename__ = "agent_skill_bindings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_configs.id", ondelete="CASCADE"))
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_definitions.id", ondelete="CASCADE"))
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)

    agent: Mapped[AgentConfig] = relationship(back_populates="skill_bindings")
    skill: Mapped[SkillDefinition] = relationship(back_populates="bindings")

    __table_args__ = (UniqueConstraint("agent_id", "skill_id", name="uq_agent_skill"),)


class AgentMCPBinding(Base):
    __tablename__ = "agent_mcp_bindings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_configs.id", ondelete="CASCADE"))
    mcp_id: Mapped[str] = mapped_column(ForeignKey("mcp_server_configs.id", ondelete="CASCADE"))
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)

    agent: Mapped[AgentConfig] = relationship(back_populates="mcp_bindings")
    mcp: Mapped[MCPServerConfig] = relationship(back_populates="bindings")

    __table_args__ = (UniqueConstraint("agent_id", "mcp_id", name="uq_agent_mcp"),)


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        UniqueConstraint("feishu_chat_id", "feishu_topic_root_id", name="uq_chat_session_feishu_topic"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128))
    topic: Mapped[str] = mapped_column(Text)
    max_rounds: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    feishu_chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    feishu_topic_root_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    feishu_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    agents: Mapped[list["ChatSessionAgent"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    runs: Mapped[list["DiscussionRun"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatSessionAgent(Base):
    __tablename__ = "chat_session_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_configs.id", ondelete="CASCADE"))
    speak_order: Mapped[int] = mapped_column(Integer, default=1)

    session: Mapped[ChatSession] = relationship(back_populates="agents")
    agent: Mapped[AgentConfig] = relationship(back_populates="session_links")


class DiscussionRun(Base, TimestampMixin):
    __tablename__ = "discussion_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    current_round: Mapped[int] = mapped_column(Integer, default=0)
    notify_feishu: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped[ChatSession] = relationship(back_populates="runs")
    events: Mapped[list["DiscussionEvent"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    reports: Mapped[list["FinalReport"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    tool_logs: Mapped[list["ToolCallLog"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    event_counter: Mapped["DiscussionEventCounter | None"] = relationship(back_populates="run", cascade="all, delete-orphan", uselist=False)

    @property
    def latest_report(self) -> "FinalReport | None":
        state = inspect(self)
        if "reports" in state.unloaded:
            return None
        if not self.reports:
            return None
        return max(self.reports, key=lambda item: item.created_at)


class DiscussionEvent(Base):
    __tablename__ = "discussion_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("discussion_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    round_no: Mapped[int] = mapped_column(Integer, default=0)
    event_type: Mapped[str] = mapped_column(String(64))
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[DiscussionRun] = relationship(back_populates="events")

    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_seq"),)


class DiscussionEventCounter(Base):
    __tablename__ = "discussion_event_counters"

    run_id: Mapped[str] = mapped_column(ForeignKey("discussion_runs.id", ondelete="CASCADE"), primary_key=True)
    next_seq: Mapped[int] = mapped_column(Integer, default=1)

    run: Mapped[DiscussionRun] = relationship(back_populates="event_counter")


class FinalReport(Base, TimestampMixin):
    __tablename__ = "final_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("discussion_runs.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    summary_markdown: Mapped[str] = mapped_column(Text)
    conclusion_json: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[DiscussionRun] = relationship(back_populates="reports")


class ToolCallLog(Base, TimestampMixin):
    __tablename__ = "tool_call_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("discussion_runs.id", ondelete="CASCADE"))
    round_no: Mapped[int] = mapped_column(Integer, default=0)
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(128))
    tool_input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    tool_output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="started")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[DiscussionRun] = relationship(back_populates="tool_logs")


class FeishuIntegrationConfig(Base, TimestampMixin):
    __tablename__ = "feishu_integration_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    app_id: Mapped[str] = mapped_column(String(128), unique=True)
    app_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    bot_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class FeishuMessageReceipt(Base, TimestampMixin):
    __tablename__ = "feishu_message_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id: Mapped[str] = mapped_column(String(128), unique=True)
    chat_id: Mapped[str] = mapped_column(String(128))
    command_type: Mapped[str] = mapped_column(String(64), default="unknown")
    status: Mapped[str] = mapped_column(String(32), default="received")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class FeishuAgentBotConfig(Base, TimestampMixin):
    __tablename__ = "feishu_agent_bot_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_configs.id", ondelete="CASCADE"), unique=True)
    app_id: Mapped[str] = mapped_column(String(128), unique=True)
    app_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    bot_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    receive_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    agent: Mapped[AgentConfig] = relationship(back_populates="feishu_bot")
