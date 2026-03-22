from __future__ import annotations

from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from app.core import SecretCodec
from app.entities import ModelConfig, ProviderConfig


def _model_kwargs(model: ModelConfig) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "temperature": model.temperature,
        "streaming": bool(model.stream_enabled),
    }
    if model.top_p is not None:
        kwargs["top_p"] = model.top_p
    return kwargs


def build_chat_model(provider: ProviderConfig, model: ModelConfig):
    api_key = SecretCodec.decode(provider.api_key_encrypted)
    client_kwargs = dict(model.extra_config_json.get("client_kwargs", {}))
    model_kwargs = dict(model.extra_config_json.get("model_kwargs", {}))

    if provider.provider_type in {"openai", "openrouter", "openai_compatible"}:
        return ChatOpenAI(
            model=model.model_name,
            api_key=api_key,
            base_url=provider.base_url or client_kwargs.get("base_url"),
            organization=provider.organization,
            model_kwargs=model_kwargs,
            max_completion_tokens=model.max_tokens,
            **_model_kwargs(model),
        )

    if provider.provider_type == "azure":
        return AzureChatOpenAI(
            model=model.model_name,
            api_key=api_key,
            azure_endpoint=provider.base_url or client_kwargs.get("azure_endpoint"),
            azure_deployment=client_kwargs.get("azure_deployment") or model.model_name,
            api_version=client_kwargs.get("api_version"),
            organization=provider.organization,
            model_kwargs=model_kwargs,
            max_completion_tokens=model.max_tokens,
            **_model_kwargs(model),
        )

    if provider.provider_type == "anthropic":
        return ChatAnthropic(
            model_name=model.model_name,
            api_key=api_key or "",
            base_url=provider.base_url or client_kwargs.get("base_url"),
            model_kwargs=model_kwargs,
            max_tokens_to_sample=model.max_tokens,
            **_model_kwargs(model),
        )

    if provider.provider_type == "ollama":
        return ChatOllama(
            model=model.model_name,
            base_url=provider.base_url or client_kwargs.get("host"),
            num_predict=model.max_tokens,
            **_model_kwargs(model),
            **model_kwargs,
        )

    raise ValueError(f"Unsupported provider type for LangGraph runtime: {provider.provider_type}")


def resolve_endpoint(provider: ProviderConfig, model: ModelConfig) -> str | None:
    client_kwargs = dict(model.extra_config_json.get("client_kwargs", {}))
    if provider.provider_type == "azure":
        return str(client_kwargs.get("azure_endpoint") or provider.base_url or "")
    if provider.provider_type in {"openai", "openrouter", "openai_compatible", "anthropic"}:
        return str(client_kwargs.get("base_url") or provider.base_url or "")
    if provider.provider_type == "ollama":
        return str(provider.base_url or client_kwargs.get("host") or "")
    return None
