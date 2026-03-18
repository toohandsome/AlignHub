from __future__ import annotations

import asyncio
import base64
from collections import defaultdict
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """集中管理后端运行配置。

    所有配置都支持通过 `APP_` 前缀环境变量覆盖，便于本地开发和部署。
    """
    app_name: str = "AlignHub Backend"
    database_url: str = "sqlite+aiosqlite:///./backend.db"
    secret_key: str = "dev-secret-key"
    workspace_root: str = str(Path.cwd())
    artifact_root: str = str(Path.cwd() / "artifacts")
    mock_discussion_round_cap: int = 2
    min_discussion_rounds: int = 2
    discussion_context_messages: int = 6
    cleanup_run_workspace_on_finish: bool = True
    skill_prompt_char_limit: int = 1200
    skill_prompt_total_char_limit: int = 3200
    report_message_char_limit: int = 400

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")


settings = Settings()


class SecretCodec:
    """对敏感字段做统一编码与脱敏处理。

    这里的职责是“统一读写格式”，不是严格意义上的安全加密。
    因此它主要用于避免明文直存，而不是替代专业密钥管理方案。
    """
    @staticmethod
    def encode(value: str | None) -> str | None:
        if not value:
            return None
        raw = f"{settings.secret_key}:{value}".encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("utf-8")

    @staticmethod
    def decode(value: str | None) -> str | None:
        if not value:
            return None
        decoded = base64.urlsafe_b64decode(value.encode("utf-8")).decode("utf-8")
        prefix = f"{settings.secret_key}:"
        return decoded[len(prefix) :] if decoded.startswith(prefix) else decoded

    @staticmethod
    def mask(value: str | None) -> str | None:
        if not value:
            return None
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}***{value[-4:]}"


class RealtimeBroker:
    """运行事件的进程内发布/订阅总线。

    WebSocket 连接会订阅某个 run_id，对应运行的事件会被推送到所有订阅者。
    """
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, run_id: str) -> asyncio.Queue:
        """为某个运行创建订阅队列。"""
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subs[run_id].add(queue)
        return queue

    async def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        """移除订阅队列，避免无效连接持续占用内存。"""
        async with self._lock:
            self._subs.get(run_id, set()).discard(queue)
            if run_id in self._subs and not self._subs[run_id]:
                self._subs.pop(run_id, None)

    async def publish(self, run_id: str, payload: dict) -> None:
        """把某条运行事件广播给所有订阅该 run_id 的连接。"""
        async with self._lock:
            targets = list(self._subs.get(run_id, set()))
        for queue in targets:
            await queue.put(payload)
