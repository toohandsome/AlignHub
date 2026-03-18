from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import SecretCodec  # noqa: E402
from app.entities import ModelConfig, ProviderConfig  # noqa: E402
from app.runtime import test_model_connection  # noqa: E402


def build_provider(provider_type: str, name: str, *, api_key: str | None = None, base_url: str | None = None, organization: str | None = None) -> ProviderConfig:
    return ProviderConfig(
        provider_type=provider_type,
        name=name,
        api_key_encrypted=SecretCodec.encode(api_key),
        base_url=base_url,
        organization=organization,
        extra_config_json={}
    )


def build_model(provider: ProviderConfig, model_name: str, *, formatter_type: str = "auto") -> ModelConfig:
    return ModelConfig(
        provider_id=provider.id,
        model_name=model_name,
        temperature=0.2,
        max_tokens=128,
        formatter_type=formatter_type,
        extra_config_json={}
    )


async def main() -> None:
    matrix: list[tuple[str, ProviderConfig, ModelConfig]] = []

    mock_provider = build_provider("mock", "mock-live")
    matrix.append(("mock", mock_provider, build_model(mock_provider, "mock-gpt", formatter_type="openai_multi_agent")))

    if os.getenv("OPENAI_API_KEY"):
        provider = build_provider("openai", "openai-live", api_key=os.getenv("OPENAI_API_KEY"), organization=os.getenv("OPENAI_ORG"))
        matrix.append(("openai", provider, build_model(provider, os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))))

    if os.getenv("OPENROUTER_API_KEY"):
        provider = build_provider(
            "openrouter",
            "openrouter-live",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        )
        matrix.append(("openrouter", provider, build_model(provider, os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"))))

    if os.getenv("ANTHROPIC_API_KEY"):
        provider = build_provider("anthropic", "anthropic-live", api_key=os.getenv("ANTHROPIC_API_KEY"))
        matrix.append(("anthropic", provider, build_model(provider, os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"))))

    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
        provider = build_provider(
            "azure",
            "azure-openai-live",
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            base_url=os.getenv("AZURE_OPENAI_ENDPOINT"),
        )
        matrix.append(("azure", provider, build_model(provider, os.getenv("AZURE_OPENAI_MODEL", "gpt-4.1-mini"))))

    if os.getenv("OLLAMA_BASE_URL"):
        provider = build_provider("ollama", "ollama-live", base_url=os.getenv("OLLAMA_BASE_URL"))
        matrix.append(("ollama", provider, build_model(provider, os.getenv("OLLAMA_MODEL", "llama3.1"))))

    print("provider_connectivity_matrix", [name for name, *_ in matrix])
    for name, provider, model in matrix:
        result = await test_model_connection(provider, model)
        print(f"[{name}]", result)


if __name__ == "__main__":
    asyncio.run(main())
