from __future__ import annotations

from typing import Any

from app.core import SecretCodec
from app.entities import FeishuAgentBotConfig, FeishuIntegrationConfig


def _matches_source(
    config: FeishuIntegrationConfig | FeishuAgentBotConfig,
    *,
    app_id: str,
    token: str,
) -> bool:
    configured_token = SecretCodec.decode(config.verification_token_encrypted) or ""

    if app_id and config.app_id != app_id:
        return False
    if token and configured_token != token:
        return False

    return bool(app_id or token)


def resolve_callback_source(
    *,
    host: FeishuIntegrationConfig | None,
    agent_bots: list[FeishuAgentBotConfig],
    app_id: str,
    token: str,
) -> dict[str, Any]:
    if not (app_id or token):
        raise PermissionError("Missing Feishu callback credentials")

    if host and host.enabled and _matches_source(host, app_id=app_id, token=token):
        return {"kind": "host", "config": host}

    for bot in agent_bots:
        if not bot.enabled or not bot.receive_enabled:
            continue
        if _matches_source(bot, app_id=app_id, token=token):
            return {"kind": "agent", "config": bot}

    raise PermissionError("Feishu callback authentication failed")
