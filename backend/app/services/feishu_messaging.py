from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select

from app.core import SecretCodec
from app.db import SessionLocal
from app.entities import ChatSession, DiscussionRun, FeishuAgentBotConfig, FeishuIntegrationConfig

if TYPE_CHECKING:
    from app.feishu import FeishuBridgeService


FEISHU_OPEN_BASE = "https://open.feishu.cn/open-apis"


class FeishuMessagingService:
    def __init__(self, bridge: FeishuBridgeService) -> None:
        self._bridge = bridge

    async def diagnose_chat(self, chat_id: str) -> list[dict[str, Any]]:
        agents = await self._bridge._load_all_agents()
        _, _, probes = await self._bridge._autobind.detect_chat_member_agent_ids(chat_id, agents)
        probe_map = {probe.agent_id: probe for probe in probes}

        results: list[dict[str, Any]] = []
        for agent in agents:
            bot = agent.feishu_bot
            if not bot:
                continue
            probe = probe_map.get(agent.id)
            results.append(
                {
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "bot_name": bot.bot_name,
                    "app_id": bot.app_id,
                    "enabled": bool(bot.enabled),
                    "receive_enabled": bool(bot.receive_enabled),
                    "in_chat": probe.in_chat if probe else None,
                    "error": probe.error if probe else None,
                }
            )
        return results

    async def handle_run_event(self, event: dict) -> None:
        event_type = str(event.get("event_type") or "")
        if event_type not in {"message_completed", "report_generated", "error", "run_status", "user_input"}:
            return

        binding = await self._load_chat_binding_by_run(str(event.get("run_id") or ""))
        if not binding:
            return

        chat_id = binding.feishu_chat_id
        if not chat_id:
            return

        reply_to_message_id = binding.feishu_topic_root_id or None
        payload = event.get("payload") or {}
        event_source = str(payload.get("source") or "").strip()
        if event_type == "message_completed":
            if not event.get("agent_id"):
                return
            text = str(payload.get("text") or "").strip()
            if not text:
                return
            agent_name = str(payload.get("agent_name") or "Agent").strip()
            await self.send_message(
                chat_id,
                title=f"{agent_name} 发言",
                body=text,
                agent_id=str(event.get("agent_id")),
                reply_to_message_id=reply_to_message_id,
            )
            return

        if event_type == "report_generated":
            summary = str(payload.get("summary_markdown") or "").strip()
            title = str(payload.get("title") or "最终报告").strip()
            if summary:
                await self.send_message(
                    chat_id,
                    title=title,
                    body=summary,
                    source_kind="host",
                    reply_to_message_id=reply_to_message_id,
                )
            return

        if event_type == "user_input":
            if event_source == "feishu":
                return
            text = str(payload.get("text") or "").strip()
            if text:
                await self.send_message(
                    chat_id,
                    title="用户补充信息",
                    body=text,
                    source_kind="host",
                    reply_to_message_id=reply_to_message_id,
                )
            return

        if event_type == "error":
            message = str(payload.get("message") or "运行失败").strip()
            await self.send_message(
                chat_id,
                title="讨论运行失败",
                body=message,
                source_kind="host",
                reply_to_message_id=reply_to_message_id,
            )
            return

        status = str(payload.get("status") or "").strip()
        if event_source == "feishu" and status in {"paused", "resumed", "stopped"}:
            return
        if status == "paused":
            await self.send_message(
                chat_id,
                title="讨论状态",
                body="讨论已暂停，等待补充信息或继续指令。",
                source_kind="host",
                reply_to_message_id=reply_to_message_id,
            )
            return
        if status == "resumed":
            await self.send_message(
                chat_id,
                title="讨论状态",
                body="讨论已恢复，将继续按原顺序发言。",
                source_kind="host",
                reply_to_message_id=reply_to_message_id,
            )
            return
        if status == "stopped":
            await self.send_message(
                chat_id,
                title="讨论状态",
                body="讨论已停止。",
                source_kind="host",
                reply_to_message_id=reply_to_message_id,
            )

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
        config = await self._resolve_sender_config(agent_id=agent_id, source_kind=source_kind)
        if not config:
            raise ValueError("未找到可用的飞书机器人配置")

        access_token = await self.tenant_access_token(config)
        lock_key = reply_to_message_id or chat_id
        async with self._bridge._chat_lock(lock_key):
            for title_chunk, text_chunk in self._chunk_post(title=title, body=body):
                if reply_to_message_id:
                    reply_text = self.compose_reply_text(title_chunk, text_chunk)
                    await self.request_json(
                        f"{FEISHU_OPEN_BASE}/im/v1/messages/{reply_to_message_id}/reply",
                        method="POST",
                        payload={
                            "msg_type": "text",
                            "content": json.dumps({"text": reply_text}, ensure_ascii=False),
                        },
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    continue

                await self.request_json(
                    f"{FEISHU_OPEN_BASE}/im/v1/messages?receive_id_type=chat_id",
                    method="POST",
                    payload={
                        "receive_id": chat_id,
                        "msg_type": "post",
                        "content": json.dumps(
                            {
                                "zh_cn": {
                                    "title": title_chunk,
                                    "content": [[{"tag": "text", "text": line}] for line in self._split_post_lines(text_chunk)],
                                }
                            },
                            ensure_ascii=False,
                        ),
                    },
                    headers={"Authorization": f"Bearer {access_token}"},
                )

    async def send_text(self, chat_id: str, text: str) -> None:
        await self.send_message(chat_id, title="消息", body=text, source_kind="host")

    def compose_reply_text(self, title: str, body: str) -> str:
        title_text = (title or "").strip()
        body_text = (body or "").strip()
        if title_text and body_text:
            return f"{title_text}\n{body_text}"
        return title_text or body_text or "-"

    async def tenant_access_token(self, config: FeishuIntegrationConfig | FeishuAgentBotConfig) -> str:
        now = datetime.now(timezone.utc)
        cached = self._bridge._token_cache.get(config.app_id)
        if cached and now < cached[1]:
            return cached[0]

        app_secret = SecretCodec.decode(config.app_secret_encrypted)
        if not config.app_id or not app_secret:
            raise ValueError("飞书 app_id / app_secret 未完整配置")

        data = await self.request_json(
            f"{FEISHU_OPEN_BASE}/auth/v3/tenant_access_token/internal",
            method="POST",
            payload={"app_id": config.app_id, "app_secret": app_secret},
        )
        if int(data.get("code", 0)) != 0:
            raise ValueError(data.get("msg") or "获取 tenant_access_token 失败")

        token = str(data.get("tenant_access_token") or "")
        expire = int(data.get("expire", 7200))
        self._bridge._token_cache[config.app_id] = (token, now + timedelta(seconds=max(60, expire - 120)))
        return token

    async def request_json(self, url: str, *, method: str, payload: dict | None = None, headers: dict | None = None) -> dict:
        def _request() -> dict:
            req = Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    **(headers or {}),
                },
                method=method,
            )
            with urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))

        try:
            return await asyncio.to_thread(_request)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"Feishu HTTPError {exc.code}: {body}") from exc
        except URLError as exc:
            raise ValueError(f"Feishu URLError: {exc.reason}") from exc

    async def get_message_details(self, message_id: str, *, source: dict[str, Any]) -> dict[str, Any]:
        config = source.get("config")
        if not config:
            host = await self._bridge.get_config()
            if not host:
                return {}
            config = host

        access_token = await self.tenant_access_token(config)
        data = await self.request_json(
            f"{FEISHU_OPEN_BASE}/im/v1/messages/{message_id}",
            method="GET",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        payload = data.get("data") or {}
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            items = payload.get("items") or []
            return items[0] if items else {}
        return payload if isinstance(payload, dict) else {}

    async def list_thread_messages(
        self,
        *,
        thread_id: str,
        source: dict[str, Any],
        page_size: int = 1,
    ) -> list[dict[str, Any]]:
        if not thread_id:
            return []

        config = source.get("config")
        if not config:
            host = await self._bridge.get_config()
            if not host:
                return []
            config = host

        access_token = await self.tenant_access_token(config)
        query = urlencode(
            {
                "container_id_type": "thread",
                "container_id": thread_id,
                "sort_type": "ByCreateTimeAsc",
                "page_size": page_size,
            }
        )
        data = await self.request_json(
            f"{FEISHU_OPEN_BASE}/im/v1/messages?{query}",
            method="GET",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        payload = data.get("data") or {}
        items = payload.get("items") if isinstance(payload, dict) else None
        return list(items or [])

    async def _resolve_sender_config(
        self,
        *,
        agent_id: str | None,
        source_kind: str,
    ) -> FeishuIntegrationConfig | FeishuAgentBotConfig | None:
        async with SessionLocal() as db:
            if agent_id:
                res = await db.execute(select(FeishuAgentBotConfig).where(FeishuAgentBotConfig.agent_id == agent_id))
                agent_bot = res.scalars().first()
                if agent_bot and agent_bot.enabled:
                    return agent_bot
            if source_kind == "agent" and agent_id:
                res = await db.execute(select(FeishuAgentBotConfig).where(FeishuAgentBotConfig.agent_id == agent_id))
                fallback_agent_bot = res.scalars().first()
                if fallback_agent_bot:
                    return fallback_agent_bot
            host = await self._bridge._get_config_row(db)
            return host if host and host.enabled else None

    async def _load_chat_binding_by_run(self, run_id: str) -> ChatSession | None:
        if not run_id:
            return None
        async with SessionLocal() as db:
            res = await db.execute(
                select(ChatSession)
                .join(DiscussionRun, DiscussionRun.session_id == ChatSession.id)
                .where(
                    ChatSession.feishu_enabled.is_(True),
                    DiscussionRun.id == run_id,
                    DiscussionRun.notify_feishu.is_(True),
                )
            )
            return res.scalars().first()

    def _chunk_post(self, *, title: str, body: str, limit: int = 1800) -> list[tuple[str, str]]:
        normalized = body.strip() or "-"
        if len(normalized) <= limit:
            return [(title, normalized)]
        chunks: list[tuple[str, str]] = []
        start = 0
        index = 1
        while start < len(normalized):
            end = min(len(normalized), start + limit)
            chunks.append((f"{title}（{index}）", normalized[start:end]))
            start = end
            index += 1
        return chunks

    def _split_post_lines(self, body: str, *, line_limit: int = 500) -> list[str]:
        raw_lines = [line.strip() for line in body.splitlines() if line.strip()]
        if not raw_lines:
            raw_lines = [body.strip() or "-"]
        lines: list[str] = []
        for line in raw_lines:
            if len(line) <= line_limit:
                lines.append(line)
                continue
            start = 0
            while start < len(line):
                end = min(len(line), start + line_limit)
                lines.append(line[start:end])
                start = end
        return lines[:30]
