from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core import SecretCodec
from app.db import SessionLocal
from app.entities import (
    AgentConfig,
    ChatSession,
    ChatSessionAgent,
    FeishuAgentBotConfig,
    FeishuIntegrationConfig,
    FeishuMessageReceipt,
)
from app.services.feishu_autobind import FeishuAutoBindService
from app.services.feishu_callbacks import FeishuCallbackService
from app.services.feishu_commands import FeishuCommandService
from app.services.feishu_messaging import FeishuMessagingService
from app.services.feishu_models import AutoBindDiagnostics, FeishuConversationRef, ParsedCommand, ParsedMessageContext

if TYPE_CHECKING:
    from app.runtime_langgraph import RunManager


logger = logging.getLogger(__name__)


class FeishuBridgeService:
    """飞书集成门面。

    统一协调命令解析、自动建会话、消息发送、Run 控制以及事件回推。
    """

    def __init__(self) -> None:
        self._token_cache: dict[str, tuple[str, datetime]] = {}
        self._run_manager: RunManager | None = None
        self._chat_locks: dict[str, asyncio.Lock] = {}
        self._commands = FeishuCommandService()
        self._messaging = FeishuMessagingService(self)
        self._autobind = FeishuAutoBindService(self)
        self._callbacks = FeishuCallbackService(self)

    def bind_run_manager(self, run_manager: RunManager) -> None:
        self._run_manager = run_manager

    def _chat_lock(self, chat_id: str) -> asyncio.Lock:
        if chat_id not in self._chat_locks:
            self._chat_locks[chat_id] = asyncio.Lock()
        return self._chat_locks[chat_id]

    async def get_config(self) -> FeishuIntegrationConfig | None:
        async with SessionLocal() as db:
            return await self._get_config_row(db)

    async def upsert_config(
        self,
        *,
        app_id: str,
        app_secret: str | None,
        verification_token: str | None,
        bot_name: str | None,
        enabled: bool,
    ) -> FeishuIntegrationConfig:
        async with SessionLocal() as db:
            row = await self._get_config_row(db)
            if not row:
                row = FeishuIntegrationConfig(
                    app_id=app_id,
                    app_secret_encrypted=SecretCodec.encode(app_secret),
                    verification_token_encrypted=SecretCodec.encode(verification_token),
                    bot_name=bot_name,
                    enabled=enabled,
                )
                db.add(row)
            else:
                row.app_id = app_id
                if app_secret is not None:
                    row.app_secret_encrypted = SecretCodec.encode(app_secret)
                if verification_token is not None:
                    row.verification_token_encrypted = SecretCodec.encode(verification_token)
                row.bot_name = bot_name
                row.enabled = enabled
            await db.commit()
            await db.refresh(row)
            self._token_cache.pop(row.app_id, None)
            return row

    async def test_send(self, chat_id: str, text: str, *, agent_id: str | None = None) -> dict:
        await self.send_message(chat_id, title="测试消息", body=text, agent_id=agent_id)
        return {"success": True, "chat_id": chat_id}

    async def diagnose_chat(self, chat_id: str) -> list[dict[str, Any]]:
        return await self._messaging.diagnose_chat(chat_id)

    async def handle_callback(self, payload: dict) -> dict:
        return await self._callbacks.handle_callback(payload)

    async def _handle_message_event(self, event: dict, *, source: dict[str, Any]) -> dict:
        """处理飞书消息事件。

        核心流程是：识别上下文 -> 查找/自动绑定会话 -> 解析命令 -> 调用 RunManager -> 回写飞书。
        """
        message = event.get("message", {}) or {}
        sender = event.get("sender", {}) or {}
        conversation = self._callbacks.build_conversation_ref(message)
        message_type = str(message.get("message_type") or "").strip()

        if not conversation:
            return {"ok": True, "ignored": "missing_message_id_or_chat_id"}
        if conversation.chat_type and conversation.chat_type not in {"group", "topic_group"}:
            return {"ok": True, "ignored": "non_group_chat"}
        if message_type != "text":
            return {"ok": True, "ignored": "non_text_message"}

        if conversation.chat_type in {"group", "topic_group"}:
            conversation = await self._callbacks.resolve_conversation_ref(conversation, source=source)

        message_ctx = self._commands.parse_message_context(message)
        session = await self._load_session_binding(conversation)
        available_agents = await self._load_available_agents(session=session, source=source)
        command = self._commands.parse_command(
            message_ctx,
            session=session,
            source=source,
            available_agents=available_agents,
        )
        sender_type = str(sender.get("sender_type") or "").strip()

        active_run = None
        if session and self._run_manager:
            active_run = await self._run_manager.find_active_run_for_session(session.id)

        if not command:
            # 普通文本在已有运行中会被视为“用户补充”，触发软暂停并注入上下文。
            if session and active_run and sender_type == "user" and message_ctx.text and self._run_manager:
                receipt = await self._record_message(conversation.message_id, conversation.chat_id, "user_input")
                if not receipt:
                    return {"ok": True, "duplicate": True}
                await self._run_manager.inject_user_input(
                    active_run.id,
                    message=message_ctx.text,
                    source="feishu",
                    pause=True,
                )
                await self.send_message(
                    conversation.chat_id,
                    title="已暂停讨论",
                    body=f"已暂停当前讨论，并记录你的补充信息：\n{message_ctx.text}",
                    source_kind="host",
                    reply_to_message_id=conversation.reply_to_message_id,
                )
                await self._update_receipt(conversation.message_id, "completed", f"user_input={active_run.id}")
                return {"ok": True, "action": "user_input", "run_id": active_run.id}
            return {"ok": True, "ignored": "no_command"}

        receipt = await self._record_message(conversation.message_id, conversation.chat_id, command.kind)
        if not receipt:
            return {"ok": True, "duplicate": True}

        sender_name = (
            sender.get("sender_id", {}).get("user_id")
            or sender.get("sender_id", {}).get("open_id")
            or sender.get("sender_id", {}).get("union_id")
            or "用户"
        )

        try:
            auto_created = False
            auto_bind_diagnostics: AutoBindDiagnostics | None = None
            if not session or not session.feishu_enabled:
                # 群聊未绑定时，尝试根据当前群上下文和可用 Agent 自动补齐会话。
                session, auto_created, auto_bind_diagnostics = await self._autobind.ensure_session_for_binding(
                    conversation,
                    message_ctx=message_ctx,
                    source=source,
                    command=command,
                    available_agents=available_agents,
                )
                if session:
                    available_agents = await self._load_available_agents(session=session, source=source)

            if not session or not session.feishu_enabled:
                await self.send_message(
                    conversation.chat_id,
                    title="未绑定会话",
                    body="当前群聊/话题尚未绑定系统会话，且系统无法自动为该上下文创建会话。请先确认相关 Agent Bot 已加入该群并已在系统中启用，或到“讨论会话”页面手动绑定。",
                    source_kind=command.target_mode,
                    reply_to_message_id=conversation.reply_to_message_id,
                )
                await self._update_receipt(conversation.message_id, "failed", "session_not_bound")
                return {"ok": True, "action": "session_not_bound"}

            if auto_created:
                await self.send_message(
                    conversation.chat_id,
                    title="已自动创建会话",
                    body=self._autobind.auto_created_session_text(session, diagnostics=auto_bind_diagnostics),
                    source_kind="host",
                    reply_to_message_id=conversation.reply_to_message_id,
                )

            if command.kind == "help":
                await self.send_message(
                    conversation.chat_id,
                    title="飞书命令帮助",
                    body=self._commands.help_text(session, available_agents=available_agents),
                    source_kind=command.target_mode,
                    reply_to_message_id=conversation.reply_to_message_id,
                )
                await self._update_receipt(conversation.message_id, "completed", "help")
                return {"ok": True, "action": "help", "session_id": session.id}

            if command.kind == "pause":
                if not self._run_manager:
                    raise RuntimeError("RunManager 未绑定")
                active_run = active_run or await self._run_manager.find_active_run_for_session(session.id)
                if not active_run:
                    await self.send_message(
                        conversation.chat_id,
                        title="暂无运行中的讨论",
                        body="当前没有可暂停的讨论。",
                        source_kind=command.target_mode,
                        reply_to_message_id=conversation.reply_to_message_id,
                    )
                    await self._update_receipt(conversation.message_id, "failed", "no_active_run")
                    return {"ok": True, "action": "no_active_run"}
                await self._run_manager.pause(active_run.id, source="feishu")
                await self.send_message(
                    conversation.chat_id,
                    title="讨论已暂停",
                    body=f"当前讨论 {active_run.id} 已暂停。",
                    source_kind="host",
                    reply_to_message_id=conversation.reply_to_message_id,
                )
                await self._update_receipt(conversation.message_id, "completed", f"pause={active_run.id}")
                return {"ok": True, "action": "pause", "run_id": active_run.id}

            if command.kind == "resume":
                if not self._run_manager:
                    raise RuntimeError("RunManager 未绑定")
                active_run = active_run or await self._run_manager.find_active_run_for_session(session.id)
                if not active_run:
                    await self.send_message(
                        conversation.chat_id,
                        title="暂无可继续的讨论",
                        body="当前没有可恢复的讨论。",
                        source_kind=command.target_mode,
                        reply_to_message_id=conversation.reply_to_message_id,
                    )
                    await self._update_receipt(conversation.message_id, "failed", "no_active_run")
                    return {"ok": True, "action": "no_active_run"}
                await self._run_manager.resume(active_run.id, source="feishu")
                await self.send_message(
                    conversation.chat_id,
                    title="讨论已继续",
                    body=f"当前讨论 {active_run.id} 已恢复运行。",
                    source_kind="host",
                    reply_to_message_id=conversation.reply_to_message_id,
                )
                await self._update_receipt(conversation.message_id, "completed", f"resume={active_run.id}")
                return {"ok": True, "action": "resume", "run_id": active_run.id}

            if command.kind == "stop":
                if not self._run_manager:
                    raise RuntimeError("RunManager 未绑定")
                active_run = active_run or await self._run_manager.find_active_run_for_session(session.id)
                if not active_run:
                    await self.send_message(
                        conversation.chat_id,
                        title="暂无可停止的讨论",
                        body="当前没有运行中的讨论。",
                        source_kind=command.target_mode,
                        reply_to_message_id=conversation.reply_to_message_id,
                    )
                    await self._update_receipt(conversation.message_id, "failed", "no_active_run")
                    return {"ok": True, "action": "no_active_run"}
                await self._run_manager.stop(active_run.id, source="feishu")
                await self.send_message(
                    conversation.chat_id,
                    title="讨论已停止",
                    body=f"当前讨论 {active_run.id} 已停止。",
                    source_kind="host",
                    reply_to_message_id=conversation.reply_to_message_id,
                )
                await self._update_receipt(conversation.message_id, "completed", f"stop={active_run.id}")
                return {"ok": True, "action": "stop", "run_id": active_run.id}

            if command.kind == "start":
                # start 会重新修正会话 topic / name，再真正创建 Run。
                if not self._run_manager:
                    raise RuntimeError("RunManager 未绑定")
                active_run = await self._run_manager.find_active_run_for_session(session.id)
                if active_run:
                    await self.send_message(
                        conversation.chat_id,
                        title="已有运行中的讨论",
                        body=f"当前已有运行中的讨论：{active_run.id}\n请稍后再发起新的讨论。",
                        source_kind=command.target_mode,
                        reply_to_message_id=conversation.reply_to_message_id,
                    )
                    await self._update_receipt(conversation.message_id, "failed", "active_run_exists")
                    return {"ok": True, "action": "active_run_exists"}

                topic = await self._autobind.resolve_session_topic(
                    command=command,
                    session=session,
                    conversation=conversation,
                    source=source,
                    message_ctx=message_ctx,
                )
                if self._autobind.is_missing_topic_for_start(topic, conversation=conversation):
                    await self.send_message(
                        conversation.chat_id,
                        title="缺少讨论主题",
                        body="当前消息未能可靠识别飞书话题标题。请改用“开始讨论：今晚吃什么”这样的格式重新发起。",
                        source_kind=command.target_mode,
                        reply_to_message_id=conversation.reply_to_message_id,
                    )
                    await self._update_receipt(conversation.message_id, "failed", "missing_topic")
                    return {"ok": True, "action": "missing_topic"}

                session_agents = [link.agent for link in sorted(session.agents, key=lambda item: item.speak_order)]
                repaired_name = self._autobind.build_auto_session_name(
                    conversation,
                    session_agents,
                    [link.agent_id for link in sorted(session.agents, key=lambda item: item.speak_order)],
                )
                await self._update_session_metadata(
                    session.id,
                    topic=topic,
                    name=repaired_name if self._autobind.looks_garbled_text(session.name) else None,
                    feishu_topic_root_id=conversation.session_topic_root_id if conversation.is_topic_group else None,
                )
                session.topic = topic
                if self._autobind.looks_garbled_text(session.name):
                    session.name = repaired_name

                run = await self._run_manager.start(session.id)
                participant_names = [link.agent.name for link in sorted(session.agents, key=lambda item: item.speak_order)]
                await self.send_message(
                    conversation.chat_id,
                    title="讨论已启动",
                    body=(
                        f"会话：{session.name}\n"
                        f"主题：{topic}\n"
                        f"Run ID：{run.id}\n"
                        f"参与 Agent：{'、'.join(participant_names) if participant_names else '暂无 Agent'}"
                    ),
                    source_kind=command.target_mode,
                    reply_to_message_id=conversation.reply_to_message_id,
                )
                await self._update_receipt(conversation.message_id, "completed", f"run={run.id}")
                return {"ok": True, "action": "start", "run_id": run.id}

            if command.kind == "ask":
                if not self._run_manager:
                    raise RuntimeError("RunManager 未绑定")
                answer = await self._run_manager.ask_agent_in_session(session.id, command.agent_name or "", command.question or "")
                await self.send_message(
                    conversation.chat_id,
                    title=f"{answer['agent_name']} 的回复",
                    body=answer["text"],
                    agent_id=answer["agent_id"],
                    reply_to_message_id=conversation.reply_to_message_id,
                )
                await self._update_receipt(conversation.message_id, "completed", f"ask={answer['agent_id']}")
                return {"ok": True, "action": "ask", "agent_id": answer["agent_id"]}

            await self._update_receipt(conversation.message_id, "ignored", "unsupported_command")
            return {"ok": True, "ignored": "unsupported_command"}
        except Exception as exc:
            await self._update_receipt(conversation.message_id, "failed", str(exc))
            try:
                await self.send_message(
                    conversation.chat_id,
                    title="处理失败",
                    body=f"处理飞书消息失败：{exc}",
                    source_kind=command.target_mode,
                    reply_to_message_id=conversation.reply_to_message_id,
                )
            except Exception:
                pass
            return {"ok": False, "error": str(exc), "sender": sender_name}

    async def handle_run_event(self, event: dict) -> None:
        """把运行期事件转交给消息服务，由其决定是否回推飞书。"""
        await self._messaging.handle_run_event(event)

    async def send_message(
        self,
        chat_id: str,
        *,
        title: str,
        body: str,
        agent_id: str | None = None,
        source_kind: str = "host",
        reply_to_message_id: str | None = None,
    ) -> None:
        """统一的飞书消息发送入口。

        Host Bot、Agent Bot 以及 reply-to 逻辑都在 messaging service 中封装。
        """
        await self._messaging.send_message(
            chat_id,
            title=title,
            body=body,
            agent_id=agent_id,
            source_kind=source_kind,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_text(self, chat_id: str, text: str) -> None:
        await self._messaging.send_text(chat_id, text)

    async def _get_config_row(self, db) -> FeishuIntegrationConfig | None:
        res = await db.execute(select(FeishuIntegrationConfig).order_by(FeishuIntegrationConfig.created_at.desc()))
        return res.scalars().first()

    async def _get_agent_bot_rows(self, db) -> list[FeishuAgentBotConfig]:
        res = await db.execute(select(FeishuAgentBotConfig).order_by(FeishuAgentBotConfig.created_at.asc()))
        return list(res.scalars().all())

    async def _load_session_binding(self, conversation: FeishuConversationRef) -> ChatSession | None:
        async with SessionLocal() as db:
            stmt = (
                select(ChatSession)
                .options(
                    selectinload(ChatSession.agents)
                    .selectinload(ChatSessionAgent.agent)
                    .selectinload(AgentConfig.feishu_bot),
                )
                .where(ChatSession.feishu_chat_id == conversation.chat_id, ChatSession.feishu_enabled.is_(True))
                .order_by(ChatSession.created_at.desc())
            )
            if conversation.session_topic_root_id:
                stmt = stmt.where(ChatSession.feishu_topic_root_id == conversation.session_topic_root_id)
            else:
                stmt = stmt.where(ChatSession.feishu_topic_root_id.is_(None))
            res = await db.execute(stmt)
            return res.scalars().first()

    async def _load_all_agents(self) -> list[AgentConfig]:
        async with SessionLocal() as db:
            res = await db.execute(
                select(AgentConfig)
                .options(selectinload(AgentConfig.feishu_bot))
                .order_by(AgentConfig.created_at.asc())
            )
            return list(res.scalars().all())

    async def _load_available_agents(self, *, session: ChatSession | None, source: dict[str, Any]) -> list[AgentConfig]:
        if session:
            return [link.agent for link in sorted(session.agents, key=lambda item: item.speak_order)]

        agents = await self._load_all_agents()
        source_agent_id = getattr(source.get("config"), "agent_id", None)
        if not source_agent_id:
            return agents

        def _sort_key(agent: AgentConfig) -> tuple[int, datetime]:
            return (0 if agent.id == source_agent_id else 1, agent.created_at)

        return sorted(agents, key=_sort_key)

    async def _record_message(self, message_id: str, chat_id: str, command_type: str) -> FeishuMessageReceipt | None:
        async with SessionLocal() as db:
            exists = await db.execute(select(FeishuMessageReceipt).where(FeishuMessageReceipt.message_id == message_id))
            if exists.scalars().first():
                return None
            row = FeishuMessageReceipt(message_id=message_id, chat_id=chat_id, command_type=command_type, status="received")
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row

    async def _update_receipt(self, message_id: str, status: str, note: str | None) -> None:
        async with SessionLocal() as db:
            res = await db.execute(select(FeishuMessageReceipt).where(FeishuMessageReceipt.message_id == message_id))
            row = res.scalars().first()
            if not row:
                return
            row.status = status
            row.note = note
            await db.commit()

    async def _update_session_topic(self, session_id: str, topic: str) -> None:
        await self._update_session_metadata(session_id, topic=topic)

    async def _update_session_metadata(
        self,
        session_id: str,
        *,
        topic: str | None = None,
        name: str | None = None,
        feishu_topic_root_id: str | None = None,
    ) -> None:
        async with SessionLocal() as db:
            row = await db.get(ChatSession, session_id)
            if not row:
                return
            if topic is not None:
                row.topic = topic
            if name is not None:
                row.name = name
            if feishu_topic_root_id and not row.feishu_topic_root_id:
                row.feishu_topic_root_id = feishu_topic_root_id
            await db.commit()
