from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProviderCreate(BaseModel):
    provider_type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    api_key: str | None = None
    base_url: str | None = None
    organization: str | None = None
    extra_config_json: dict = Field(default_factory=dict)


class ProviderUpdate(BaseModel):
    provider_type: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    api_key: str | None = None
    base_url: str | None = None
    organization: str | None = None
    extra_config_json: dict | None = None


class ProviderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    provider_type: str
    name: str
    base_url: str | None
    organization: str | None
    extra_config_json: dict
    api_key_masked: str | None = None
    created_at: datetime
    updated_at: datetime


class ModelCreate(BaseModel):
    provider_id: str
    model_name: str = Field(min_length=1, max_length=128)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    top_p: float | None = Field(default=None, ge=0, le=1)
    stream_enabled: bool = False
    formatter_type: str = "auto"
    extra_config_json: dict = Field(default_factory=dict)


class ModelUpdate(BaseModel):
    provider_id: str | None = None
    model_name: str | None = Field(default=None, min_length=1, max_length=128)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    top_p: float | None = Field(default=None, ge=0, le=1)
    stream_enabled: bool | None = None
    formatter_type: str | None = None
    extra_config_json: dict | None = None


class ModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    provider_id: str
    model_name: str
    temperature: float
    max_tokens: int
    top_p: float | None
    stream_enabled: bool
    formatter_type: str
    extra_config_json: dict
    created_at: datetime
    updated_at: datetime


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=128)
    persona: str | None = None
    system_prompt: str = Field(min_length=1)
    model_id: str
    memory_strategy: str = "in_memory"
    max_steps: int = Field(default=6, ge=1, le=32)
    is_moderator: bool = False
    is_reporter: bool = False
    extra_config_json: dict = Field(default_factory=dict)
    tool_names: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    mcp_ids: list[str] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    role: str | None = Field(default=None, min_length=1, max_length=128)
    persona: str | None = None
    system_prompt: str | None = Field(default=None, min_length=1)
    model_id: str | None = None
    memory_strategy: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=32)
    is_moderator: bool | None = None
    is_reporter: bool | None = None
    extra_config_json: dict | None = None
    tool_names: list[str] | None = None
    skill_ids: list[str] | None = None
    mcp_ids: list[str] | None = None


class AgentRead(BaseModel):
    id: str
    name: str
    role: str
    persona: str | None
    system_prompt: str
    model_id: str
    memory_strategy: str
    max_steps: int
    is_moderator: bool
    is_reporter: bool
    extra_config_json: dict
    tool_names: list[str]
    skill_ids: list[str]
    skill_names: list[str]
    mcp_ids: list[str]
    mcp_names: list[str]
    feishu_bot_id: str | None = None
    feishu_bot_name: str | None = None
    feishu_bot_enabled: bool = False
    feishu_bot_receive_enabled: bool = False
    created_at: datetime
    updated_at: datetime


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2000)
    content: str = ""
    source_type: str = "manual"
    package_path: str | None = None
    entry_file: str | None = None
    enabled: bool = True
    builtin: bool = False


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    content: str | None = None
    source_type: str | None = None
    package_path: str | None = None
    entry_file: str | None = None
    enabled: bool | None = None
    builtin: bool | None = None


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str
    content: str
    source_type: str
    package_path: str | None
    entry_file: str | None
    package_files: list[str] = Field(default_factory=list)
    enabled: bool
    builtin: bool
    created_at: datetime
    updated_at: datetime


class MCPServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    transport_type: str = "stdio"
    description: str = ""
    command: str | None = None
    args_json: list = Field(default_factory=list)
    env_json: dict = Field(default_factory=dict)
    base_url: str | None = None
    jar_path: str | None = None
    enabled: bool = True


class MCPServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    transport_type: str | None = None
    description: str | None = None
    command: str | None = None
    args_json: list | None = None
    env_json: dict | None = None
    base_url: str | None = None
    jar_path: str | None = None
    enabled: bool | None = None


class MCPServerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    transport_type: str
    description: str
    command: str | None
    args_json: list
    env_json: dict
    base_url: str | None
    jar_path: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class MCPInvokeTestRequest(BaseModel):
    action: str = "ping"
    payload_json: dict = Field(default_factory=dict)


class RunControlRequest(BaseModel):
    message: str | None = None
    source: str = "user"


class RunUserInputRequest(BaseModel):
    message: str = Field(min_length=1)
    source: str = "user"
    pause: bool = False


class ChatSessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    topic: str = Field(min_length=1)
    max_rounds: int = Field(default=10, ge=1, le=50)
    status: str = "draft"
    agent_ids: list[str] = Field(default_factory=list)
    feishu_chat_id: str | None = None
    feishu_topic_root_id: str | None = None
    feishu_enabled: bool = False


class ChatSessionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    topic: str | None = Field(default=None, min_length=1)
    max_rounds: int | None = Field(default=None, ge=1, le=50)
    status: str | None = None
    agent_ids: list[str] | None = None
    feishu_chat_id: str | None = None
    feishu_topic_root_id: str | None = None
    feishu_enabled: bool | None = None


class ChatSessionStartRequest(BaseModel):
    notify_feishu: bool = True


class ChatSessionRead(BaseModel):
    id: str
    name: str
    topic: str
    max_rounds: int
    status: str
    agent_ids: list[str]
    feishu_chat_id: str | None = None
    feishu_topic_root_id: str | None = None
    feishu_enabled: bool = False
    created_at: datetime
    updated_at: datetime


class FeishuConfigUpdate(BaseModel):
    app_id: str = Field(min_length=1)
    app_secret: str = Field(min_length=1)
    verification_token: str = Field(min_length=1)
    bot_name: str | None = None
    enabled: bool = True


class FeishuConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str | None = None
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""
    bot_name: str | None = None
    enabled: bool = False
    webhook_path: str = "/api/v1/integrations/feishu/events"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FeishuTestSendRequest(BaseModel):
    chat_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    agent_id: str | None = None


class FeishuChatDiagnoseRequest(BaseModel):
    chat_id: str = Field(min_length=1)


class FeishuChatDiagnoseItem(BaseModel):
    agent_id: str
    agent_name: str
    bot_name: str | None = None
    app_id: str = ""
    enabled: bool = False
    receive_enabled: bool = False
    in_chat: bool | None = None
    error: str | None = None


class FeishuAgentBotConfigUpdate(BaseModel):
    app_id: str = Field(min_length=1)
    app_secret: str = Field(min_length=1)
    verification_token: str = Field(min_length=1)
    bot_name: str | None = None
    enabled: bool = True
    receive_enabled: bool = False


class FeishuAgentBotConfigRead(BaseModel):
    id: str | None = None
    agent_id: str
    agent_name: str | None = None
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""
    bot_name: str | None = None
    enabled: bool = False
    receive_enabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: str
    name: str
    category: str
    description: str
    schema_data: dict = Field(alias="schema_json", serialization_alias="schema_json")
    builtin: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ReportSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    run_id: str
    title: str
    created_at: datetime


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    session_id: str
    status: str
    current_round: int
    started_at: datetime | None
    ended_at: datetime | None
    stop_reason: str | None
    latest_report: "ReportSummaryRead | None" = None
    created_at: datetime
    updated_at: datetime


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    run_id: str
    seq: int
    round_no: int
    event_type: str
    agent_id: str | None
    tool_name: str | None
    payload_json: dict
    created_at: datetime


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    run_id: str
    title: str
    summary_markdown: str
    conclusion_json: dict
    created_at: datetime
    updated_at: datetime


class ToolLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    run_id: str
    round_no: int
    agent_id: str | None
    call_id: str | None = None
    tool_name: str
    tool_input_json: dict
    tool_output_json: dict
    status: str
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime
