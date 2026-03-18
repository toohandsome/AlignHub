from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.core import SecretCodec
from app.db import SessionLocal
from app.services.feishu_auth import resolve_callback_source
from app.services.feishu_models import FeishuConversationRef

if TYPE_CHECKING:
    from app.feishu import FeishuBridgeService


logger = logging.getLogger(__name__)


class FeishuCallbackService:
    def __init__(self, bridge: FeishuBridgeService) -> None:
        self._bridge = bridge

    async def handle_callback(self, payload: dict) -> dict:
        if payload.get("encrypt"):
            raise ValueError("当前版本暂不支持飞书事件加密，请在飞书事件订阅中使用明文模式。")

        header = payload.get("header", {}) or {}
        app_id = str(header.get("app_id") or payload.get("app_id") or "").strip()
        token = str(header.get("token") or payload.get("token") or "").strip()
        source = await self.resolve_callback_source(app_id=app_id, token=token)

        if payload.get("type") == "url_verification":
            verification_token = self.source_verification_token(source)
            if not verification_token or payload.get("token") != verification_token:
                raise PermissionError("飞书 verification token 校验失败")
            return {"challenge": payload.get("challenge", "")}

        event_type = header.get("event_type") or payload.get("type") or ""
        if event_type != "im.message.receive_v1":
            return {"ok": True, "ignored": event_type or "unknown"}

        event = payload.get("event", {}) or {}
        return await self._bridge._handle_message_event(event, source=source)

    async def resolve_callback_source(self, *, app_id: str, token: str) -> dict[str, Any]:
        async with SessionLocal() as db:
            host = await self._bridge._get_config_row(db)
            agent_bots = await self._bridge._get_agent_bot_rows(db)
        return resolve_callback_source(host=host, agent_bots=agent_bots, app_id=app_id, token=token)

    def source_verification_token(self, source: dict[str, Any]) -> str | None:
        config = source.get("config")
        if not config:
            return None
        return SecretCodec.decode(config.verification_token_encrypted)

    def build_conversation_ref(self, message: dict[str, Any]) -> FeishuConversationRef | None:
        message_id = str(message.get("message_id") or "").strip()
        chat_id = str(message.get("chat_id") or "").strip()
        chat_type = str(message.get("chat_type") or "").strip()
        if not message_id or not chat_id:
            return None

        root_message_id = str(message.get("root_id") or "").strip() or None
        parent_message_id = str(message.get("parent_id") or "").strip() or None
        thread_id = str(message.get("thread_id") or "").strip() or None
        if not root_message_id and parent_message_id:
            root_message_id = parent_message_id
        if chat_type == "topic_group" and not root_message_id:
            root_message_id = parent_message_id or message_id

        return FeishuConversationRef(
            chat_id=chat_id,
            chat_type=chat_type,
            message_id=message_id,
            root_message_id=root_message_id,
            parent_message_id=parent_message_id,
            thread_id=thread_id,
        )

    async def resolve_conversation_ref(
        self,
        conversation: FeishuConversationRef,
        *,
        source: dict[str, Any],
    ) -> FeishuConversationRef:
        logger.warning(
            "Feishu incoming conversation: chat_id=%s chat_type=%s message_id=%s root_id=%s parent_id=%s thread_id=%s",
            conversation.chat_id,
            conversation.chat_type,
            conversation.message_id,
            conversation.root_message_id,
            conversation.parent_message_id,
            conversation.thread_id,
        )
        if not conversation.is_topic_group:
            return conversation
        if conversation.root_message_id and conversation.thread_id:
            return conversation

        details = await self._bridge._messaging.get_message_details(conversation.message_id, source=source)
        root_message_id = (
            str(details.get("root_id") or "").strip()
            or str(details.get("parent_id") or "").strip()
            or conversation.parent_message_id
            or conversation.message_id
        )
        thread_id = str(details.get("thread_id") or "").strip() or conversation.thread_id
        logger.warning(
            "Feishu resolved topic conversation: chat_id=%s message_id=%s resolved_root_id=%s resolved_parent_id=%s resolved_thread_id=%s",
            conversation.chat_id,
            conversation.message_id,
            root_message_id,
            str(details.get("parent_id") or "").strip() or conversation.parent_message_id,
            thread_id,
        )
        return FeishuConversationRef(
            chat_id=conversation.chat_id,
            chat_type=conversation.chat_type,
            message_id=conversation.message_id,
            root_message_id=root_message_id,
            parent_message_id=str(details.get("parent_id") or "").strip() or conversation.parent_message_id,
            thread_id=thread_id,
        )
