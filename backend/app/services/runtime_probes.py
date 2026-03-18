from __future__ import annotations

from datetime import datetime, timezone

from agentscope.message import Msg

from app.entities import ModelConfig, ProviderConfig
from app.services.runtime_models import build_formatter, build_model, resolve_endpoint


async def test_model_connection(provider: ProviderConfig, model: ModelConfig) -> dict:
    runtime_model = build_model(provider, model)
    endpoint = resolve_endpoint(provider, model) or None

    if provider.provider_type == "mock":
        return {
            "success": True,
            "provider_type": provider.provider_type,
            "model_name": model.model_name,
            "latency_ms": 0,
            "preview": "PONG(mock)",
            "endpoint": endpoint,
        }

    formatter = build_formatter(provider.provider_type, model.formatter_type, multi_agent=False)
    messages = [
        Msg("system", "You are a connectivity test bot. Reply briefly.", "system"),
        Msg("user", "Reply with PONG only.", "user"),
    ]

    started_at = datetime.now(timezone.utc)
    try:
        prompt = await formatter.format(messages)
        result = await runtime_model(prompt)
        if getattr(runtime_model, "stream", False):
            content = []
            async for chunk in result:
                content.extend(list(chunk.content))
        else:
            content = list(result.content)

        preview = ""
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                preview += str(block.get("text", ""))

        finished_at = datetime.now(timezone.utc)
        latency_ms = int((finished_at - started_at).total_seconds() * 1000)
        return {
            "success": True,
            "provider_type": provider.provider_type,
            "model_name": model.model_name,
            "latency_ms": latency_ms,
            "preview": (preview or "<empty response>")[:200],
            "endpoint": endpoint,
        }
    except Exception as exc:  # noqa: BLE001
        finished_at = datetime.now(timezone.utc)
        latency_ms = int((finished_at - started_at).total_seconds() * 1000)
        return {
            "success": False,
            "provider_type": provider.provider_type,
            "model_name": model.model_name,
            "latency_ms": latency_ms,
            "endpoint": endpoint,
            "error": str(exc),
        }
