from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.db import SessionLocal
from app.entities import AgentConfig, ChatSession, ChatSessionAgent
from app.services.feishu_messaging import FEISHU_OPEN_BASE
from app.services.feishu_models import AutoBindDiagnostics, AgentMembershipProbe, FeishuConversationRef, ParsedCommand, ParsedMessageContext

if TYPE_CHECKING:
    from app.feishu import FeishuBridgeService


logger = logging.getLogger(__name__)


class FeishuAutoBindService:
    def __init__(self, bridge: FeishuBridgeService) -> None:
        self._bridge = bridge

    async def ensure_session_for_binding(
        self,
        conversation: FeishuConversationRef,
        *,
        message_ctx: ParsedMessageContext,
        source: dict[str, Any],
        command: ParsedCommand,
        available_agents: list[AgentConfig],
    ) -> tuple[ChatSession | None, bool, AutoBindDiagnostics | None]:
        if not self.should_auto_create_session(conversation, command):
            return None, False, None

        async with self._bridge._chat_lock(f"binding:{conversation.binding_key}"):
            session = await self._bridge._load_session_binding(conversation)
            if session and session.feishu_enabled:
                return session, False, None

            created, diagnostics = await self.auto_create_session(
                conversation,
                message_ctx=message_ctx,
                source=source,
                command=command,
                available_agents=available_agents,
            )
            return created, created is not None, diagnostics

    def should_auto_create_session(self, conversation: FeishuConversationRef, command: ParsedCommand) -> bool:
        if conversation.is_topic_group:
            return command.kind == "start"
        return True

    async def auto_create_session(
        self,
        conversation: FeishuConversationRef,
        *,
        message_ctx: ParsedMessageContext,
        source: dict[str, Any],
        command: ParsedCommand,
        available_agents: list[AgentConfig],
    ) -> tuple[ChatSession | None, AutoBindDiagnostics]:
        inferred_agent_ids = self.infer_auto_session_agent_ids(
            available_agents,
            message_ctx=message_ctx,
            source=source,
            command=command,
        )
        member_agent_ids, member_check_succeeded, probes = await self.detect_chat_member_agent_ids(conversation.chat_id, available_agents)

        if member_check_succeeded:
            member_set = set(member_agent_ids)
            if command.kind == "ask":
                agent_ids = [agent_id for agent_id in inferred_agent_ids if agent_id in member_set]
            else:
                filtered_ids = [agent_id for agent_id in inferred_agent_ids if agent_id in member_set]
                agent_ids = filtered_ids or member_agent_ids
            diagnostics = AutoBindDiagnostics(mode="chat_members", selected_agent_ids=list(agent_ids), probes=probes)
        else:
            agent_ids = inferred_agent_ids
            diagnostics = AutoBindDiagnostics(mode="message_inference", selected_agent_ids=list(agent_ids), probes=probes)

        selected_agent_names = [agent.name for agent in available_agents if agent.id in set(agent_ids)]
        logger.warning(
            "Feishu auto-bind session: chat_id=%s topic_root=%s mode=%s selected_agents=%s",
            conversation.chat_id,
            conversation.session_topic_root_id or "-",
            diagnostics.mode,
            ",".join(selected_agent_names) if selected_agent_names else "-",
        )

        if not agent_ids:
            return None, diagnostics

        session_name = self.build_auto_session_name(conversation, available_agents, agent_ids)
        session_topic = await self.resolve_initial_session_topic(
            command=command,
            conversation=conversation,
            source=source,
            message_ctx=message_ctx,
        )

        async with SessionLocal() as db:
            stmt = select(ChatSession).where(
                ChatSession.feishu_chat_id == conversation.chat_id,
                ChatSession.feishu_enabled.is_(True),
            )
            if conversation.session_topic_root_id:
                stmt = stmt.where(ChatSession.feishu_topic_root_id == conversation.session_topic_root_id)
            else:
                stmt = stmt.where(ChatSession.feishu_topic_root_id.is_(None))
            existing = (await db.execute(stmt.order_by(ChatSession.created_at.desc()))).scalars().first()
            if existing:
                await db.rollback()
                return await self._bridge._load_session_binding(conversation), diagnostics

            row = ChatSession(
                name=session_name,
                topic=session_topic,
                max_rounds=10,
                status="draft",
                feishu_chat_id=conversation.chat_id,
                feishu_topic_root_id=conversation.session_topic_root_id,
                feishu_enabled=True,
            )
            db.add(row)
            await db.flush()
            for index, agent_id in enumerate(agent_ids, start=1):
                db.add(ChatSessionAgent(session_id=row.id, agent_id=agent_id, speak_order=index))
            await db.commit()
            logger.warning(
                "Feishu session auto-created: session_id=%s chat_id=%s topic_root=%s name=%s topic=%s",
                row.id,
                conversation.chat_id,
                conversation.session_topic_root_id,
                session_name,
                session_topic,
            )

        return await self._bridge._load_session_binding(conversation), diagnostics

    async def detect_chat_member_agent_ids(self, chat_id: str, agents: list[AgentConfig]) -> tuple[list[str], bool, list[AgentMembershipProbe]]:
        bot_agents = [agent for agent in agents if agent.feishu_bot and agent.feishu_bot.enabled]
        if not bot_agents:
            return [], False, []

        probe_results = await asyncio.gather(
            *(self.probe_agent_bot_in_chat(chat_id, agent) for agent in bot_agents),
            return_exceptions=True,
        )

        detected_ids: list[str] = []
        check_succeeded = False
        probes: list[AgentMembershipProbe] = []
        for agent, result in zip(bot_agents, probe_results, strict=False):
            if isinstance(result, Exception):
                error_text = str(result)
                logger.warning("Feishu membership probe failed: chat_id=%s agent=%s error=%s", chat_id, agent.name, error_text)
                probes.append(AgentMembershipProbe(agent_id=agent.id, agent_name=agent.name, in_chat=None, error=error_text))
                continue
            check_succeeded = True
            logger.warning("Feishu membership probe: chat_id=%s agent=%s in_chat=%s", chat_id, agent.name, result)
            probes.append(AgentMembershipProbe(agent_id=agent.id, agent_name=agent.name, in_chat=bool(result), error=None))
            if result and agent.id not in detected_ids:
                detected_ids.append(agent.id)

        return detected_ids, check_succeeded, probes

    async def probe_agent_bot_in_chat(self, chat_id: str, agent: AgentConfig) -> bool:
        bot = agent.feishu_bot
        if not bot or not bot.enabled:
            return False

        access_token = await self._bridge._messaging.tenant_access_token(bot)
        data = await self._bridge._messaging.request_json(
            f"{FEISHU_OPEN_BASE}/im/v1/chats/{chat_id}/members/is_in_chat",
            method="GET",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if int(data.get("code", 0)) != 0:
            raise ValueError(data.get("msg") or f"check chat membership failed for {agent.name}")

        payload = data.get("data") or {}
        return bool(payload.get("is_in_chat"))

    def looks_garbled_text(self, value: str | None) -> bool:
        if not value:
            return False
        stripped = value.strip()
        if not stripped:
            return False
        if "?" not in stripped:
            return False
        meaningful = [ch for ch in stripped if ch not in {"?", "？", " ", "·", "、", ":", "：", "-", "_"}]
        if not meaningful:
            return True
        return stripped.count("?") >= max(2, len(stripped) // 3)

    def infer_auto_session_agent_ids(
        self,
        agents: list[AgentConfig],
        *,
        message_ctx: ParsedMessageContext,
        source: dict[str, Any],
        command: ParsedCommand,
    ) -> list[str]:
        if not agents:
            return []

        agents_by_name = {agent.name: agent for agent in agents}
        agent_name_map = {self._bridge._commands.normalize_name(agent.name): agent.name for agent in agents}
        bot_name_map = self._bridge._commands.agent_bot_name_map(None, available_agents=agents)
        mentioned_names = self._bridge._commands.mentioned_agent_names(message_ctx, agent_name_map, bot_name_map)
        mentioned_ids = [agents_by_name[name].id for name in mentioned_names if name in agents_by_name]
        source_agent_id = getattr(source.get("config"), "agent_id", None)
        enabled_bot_agent_ids = [agent.id for agent in agents if agent.feishu_bot and agent.feishu_bot.enabled]
        all_agent_ids = [agent.id for agent in agents]

        if command.kind == "ask":
            target_name = command.agent_name
            if target_name and target_name in agents_by_name:
                return [agents_by_name[target_name].id]
            if source_agent_id:
                return [source_agent_id]
            return mentioned_ids[:1]

        selected_ids: list[str] = []
        if command.mentioned_agents:
            selected_ids.extend([agents_by_name[name].id for name in command.mentioned_agents if name in agents_by_name])
        for agent_id in mentioned_ids:
            if agent_id not in selected_ids:
                selected_ids.append(agent_id)

        if selected_ids:
            return selected_ids
        if enabled_bot_agent_ids:
            return enabled_bot_agent_ids
        return all_agent_ids

    def build_auto_session_name(self, conversation: FeishuConversationRef, agents: list[AgentConfig], agent_ids: list[str]) -> str:
        selected = [agent.name for agent in agents if agent.id in set(agent_ids)]
        prefix = "飞书话题" if conversation.is_topic_group else "飞书群聊"
        if selected:
            label = "、".join(selected[:3])
            if len(selected) > 3:
                label = f"{label}等{len(selected)}位"
            return f"{prefix} · {label}"
        suffix_source = conversation.session_topic_root_id or conversation.chat_id
        suffix = suffix_source[-6:] if len(suffix_source) >= 6 else suffix_source
        return f"{prefix} · {suffix}"

    def build_auto_session_topic(self, command: ParsedCommand, *, conversation: FeishuConversationRef | None = None) -> str:
        if command.kind == "start" and command.topic:
            return command.topic.strip() or "请在群里输入 #start 讨论主题"
        if command.kind == "ask" and command.question:
            return f"飞书单聊问题：{command.question.strip()}"
        if conversation and conversation.is_topic_group:
            return "飞书话题讨论"
        return "飞书自动创建的讨论会话"

    async def resolve_initial_session_topic(
        self,
        *,
        command: ParsedCommand,
        conversation: FeishuConversationRef,
        source: dict[str, Any],
        message_ctx: ParsedMessageContext,
    ) -> str:
        topic = await self.resolve_topic_candidate(
            command=command,
            conversation=conversation,
            source=source,
            message_ctx=message_ctx,
        )
        return topic or self.build_auto_session_topic(command, conversation=conversation)

    async def resolve_session_topic(
        self,
        *,
        command: ParsedCommand,
        session: ChatSession,
        conversation: FeishuConversationRef,
        source: dict[str, Any],
        message_ctx: ParsedMessageContext,
    ) -> str:
        topic = await self.resolve_topic_candidate(
            command=command,
            conversation=conversation,
            source=source,
            message_ctx=message_ctx,
        )
        if topic:
            return topic
        return (session.topic or "").strip() or self.build_auto_session_topic(command, conversation=conversation)

    async def resolve_topic_candidate(
        self,
        *,
        command: ParsedCommand,
        conversation: FeishuConversationRef,
        source: dict[str, Any],
        message_ctx: ParsedMessageContext,
    ) -> str | None:
        if conversation.is_topic_group:
            topic_title = await self.fetch_topic_title(conversation, source=source)
            if topic_title and not self.is_generic_start_text(topic_title):
                return topic_title

        explicit = (command.topic or "").strip()
        if explicit and not self.is_generic_start_text(explicit):
            return explicit

        fallback = self._bridge._commands.extract_start_topic(message_ctx.text or "")
        if fallback and not self.is_generic_start_text(fallback):
            return fallback.strip()
        return None

    async def fetch_topic_title(self, conversation: FeishuConversationRef, *, source: dict[str, Any]) -> str | None:
        if conversation.thread_id:
            try:
                items = await self._bridge._messaging.list_thread_messages(
                    thread_id=conversation.thread_id,
                    source=source,
                    page_size=1,
                )
                if items:
                    thread_text = self.extract_message_text(items[0])
                    logger.warning(
                        "Feishu topic resolved from thread history: chat_id=%s thread_id=%s text=%s",
                        conversation.chat_id,
                        conversation.thread_id,
                        thread_text,
                    )
                    if thread_text:
                        return thread_text
            except Exception as exc:
                logger.warning(
                    "Failed to fetch Feishu thread history: chat_id=%s thread_id=%s error=%s",
                    conversation.chat_id,
                    conversation.thread_id,
                    exc,
                )

        candidate_ids = [conversation.root_message_id, conversation.parent_message_id, conversation.message_id]
        for message_id in candidate_ids:
            if not message_id:
                continue
            try:
                details = await self._bridge._messaging.get_message_details(message_id, source=source)
            except Exception as exc:
                logger.warning("Failed to fetch Feishu topic title: message_id=%s error=%s", message_id, exc)
                continue
            text = self.extract_message_text(details)
            if text:
                return text
        return None

    def extract_message_text(self, message_details: dict[str, Any]) -> str | None:
        body = message_details.get("body") or {}
        content = body.get("content") if isinstance(body, dict) else message_details.get("content")
        if isinstance(content, dict):
            return self.extract_text_from_content_obj(content)
        if not isinstance(content, str):
            return None

        stripped = content.strip()
        if not stripped:
            return None
        if stripped.startswith("text:"):
            return stripped[5:].strip() or None
        try:
            parsed = json.loads(stripped)
        except Exception:
            return stripped
        return self.extract_text_from_content_obj(parsed)

    def extract_text_from_content_obj(self, content: dict[str, Any]) -> str | None:
        if not isinstance(content, dict):
            return None

        text = str(content.get("text") or content.get("title") or "").strip()
        if text:
            return text

        blocks = content.get("content") or []
        direct_text = self.extract_text_from_blocks(blocks)
        if direct_text:
            return direct_text

        for locale_payload in content.values():
            if not isinstance(locale_payload, dict):
                continue
            title = str(locale_payload.get("title") or "").strip()
            if title:
                return title
            locale_text = self.extract_text_from_blocks(locale_payload.get("content") or [])
            if locale_text:
                return locale_text
        return None

    def extract_text_from_blocks(self, blocks: Any) -> str | None:
        if not isinstance(blocks, list):
            return None
        for row in blocks:
            if not isinstance(row, list):
                continue
            texts = [str(item.get("text") or "").strip() for item in row if isinstance(item, dict)]
            merged = " ".join([item for item in texts if item]).strip()
            if merged:
                return merged
        return None

    def is_generic_start_text(self, value: str | None) -> bool:
        normalized = re.sub(r"\s+", "", (value or "").strip()).lower()
        normalized = normalized.strip("：:，,。.!！?？#")
        generic_values = {
            "",
            "开始讨论",
            "发起讨论",
            "开始一下讨论",
            "发起一下讨论",
            "start",
            "topic",
        }
        return normalized in generic_values

    def is_missing_topic_for_start(self, topic: str | None, *, conversation: FeishuConversationRef) -> bool:
        if not conversation.is_topic_group:
            return False
        normalized = (topic or "").strip()
        if not normalized:
            return True
        return normalized in {"飞书话题讨论", "飞书自动创建的讨论会话"} or self.is_generic_start_text(normalized)

    def auto_created_session_text(self, session: ChatSession, *, diagnostics: AutoBindDiagnostics | None = None) -> str:
        participants = [link.agent.name for link in sorted(session.agents, key=lambda item: item.speak_order)]
        participants_text = "、".join(participants) if participants else "暂无 Agent"
        lines = [
            "系统已为当前群自动创建并绑定会话。",
            "识别方式：优先按群内实际 Agent Bot 成员自动匹配。" if diagnostics and diagnostics.mode == "chat_members" else "识别方式：群成员探测失败，已回退为消息内容推断。",
            *self.auto_bind_diagnostic_lines(diagnostics),
            f"会话名称：{session.name}",
            f"参与 Agent：{participants_text}",
            "后续可直接在群里使用 #start / #help / @机器人名。",
        ]
        return "\n".join(lines)

    def auto_bind_diagnostic_lines(self, diagnostics: AutoBindDiagnostics | None) -> list[str]:
        if not diagnostics:
            return []

        selected = {probe.agent_id for probe in diagnostics.probes if probe.agent_id in set(diagnostics.selected_agent_ids)}
        detected = [probe.agent_name for probe in diagnostics.probes if probe.in_chat]
        missing = [probe.agent_name for probe in diagnostics.probes if probe.in_chat is False]
        errors = [f"{probe.agent_name}（{probe.error}）" for probe in diagnostics.probes if probe.error]

        lines: list[str] = []
        if detected:
            lines.append(f"检测到群内 Agent Bot：{'、'.join(detected)}")
        if missing:
            lines.append(f"未检测到在群内：{'、'.join(missing)}")
        if errors:
            lines.append(f"探测失败：{'；'.join(errors)}")
        if diagnostics.mode == "message_inference" and diagnostics.selected_agent_ids:
            lines.append("已按消息内容推断参与 Agent。")
        if not lines and selected:
            lines.append("已完成自动识别。")
        return lines
