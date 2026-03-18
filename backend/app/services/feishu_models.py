from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedCommand:
    kind: str
    topic: str | None = None
    agent_name: str | None = None
    question: str | None = None
    mentioned_agents: list[str] = field(default_factory=list)
    target_mode: str = "host"


@dataclass
class ParsedMessageContext:
    text: str
    mentions: list[dict]
    mention_names: list[str]
    normalized_mentions: set[str]


@dataclass
class FeishuConversationRef:
    chat_id: str
    chat_type: str
    message_id: str
    root_message_id: str | None = None
    parent_message_id: str | None = None
    thread_id: str | None = None

    @property
    def is_topic_group(self) -> bool:
        return self.chat_type == "topic_group" or bool(self.root_message_id or self.parent_message_id)

    @property
    def session_topic_root_id(self) -> str | None:
        if not self.is_topic_group:
            return None
        return self.root_message_id or self.parent_message_id

    @property
    def reply_to_message_id(self) -> str | None:
        return self.session_topic_root_id

    @property
    def binding_key(self) -> str:
        return f"{self.chat_id}:{self.thread_id or self.session_topic_root_id or '_group'}"


@dataclass
class AgentMembershipProbe:
    agent_id: str
    agent_name: str
    in_chat: bool | None = None
    error: str | None = None


@dataclass
class AutoBindDiagnostics:
    mode: str
    selected_agent_ids: list[str] = field(default_factory=list)
    probes: list[AgentMembershipProbe] = field(default_factory=list)
