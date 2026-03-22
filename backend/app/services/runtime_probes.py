from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.entities import ModelConfig, ProviderConfig
from app.services.langgraph_models import build_chat_model, resolve_endpoint


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {"text", "input_text", "output_text"}:
                    parts.append(str(item.get("text", "")))
                elif "content" in item:
                    parts.append(str(item.get("content", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    return str(content or "")


def _extract_preview(result: Any) -> str:
    if isinstance(result, BaseMessage):
        return _message_text(result)
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if isinstance(message, AIMessage):
                    return _message_text(message)
            if messages:
                return _message_text(messages[-1])
    return str(result or "")


async def test_model_connection(provider: ProviderConfig, model: ModelConfig) -> dict[str, Any]:
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

    runtime_model = build_chat_model(provider, model)
    started_at = datetime.now(timezone.utc)
    try:
        result = await runtime_model.ainvoke(
            [
                SystemMessage(content="You are a connectivity test bot. Reply briefly."),
                HumanMessage(content="Reply with PONG only."),
            ]
        )
        finished_at = datetime.now(timezone.utc)
        latency_ms = int((finished_at - started_at).total_seconds() * 1000)
        return {
            "success": True,
            "provider_type": provider.provider_type,
            "model_name": model.model_name,
            "latency_ms": latency_ms,
            "preview": (_extract_preview(result) or "<empty response>")[:200],
            "endpoint": endpoint,
        }
    except Exception as exc:
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
