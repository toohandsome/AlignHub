from __future__ import annotations

import json
import re
import uuid
from typing import Any

from agentscope.formatter import (
    AnthropicChatFormatter,
    AnthropicMultiAgentFormatter,
    OllamaChatFormatter,
    OllamaMultiAgentFormatter,
    OpenAIChatFormatter,
    OpenAIMultiAgentFormatter,
)
from agentscope.message import TextBlock, ToolUseBlock
from agentscope.model import AnthropicChatModel, ChatModelBase, ChatResponse, OllamaChatModel, OpenAIChatModel

from app.core import SecretCodec, settings
from app.entities import ModelConfig, ProviderConfig


class MockChatModel(ChatModelBase):
    """用于本地联调的 mock 模型。"""

    def __init__(self, model_name: str = "mock-gpt", stream: bool = False) -> None:
        super().__init__(model_name=model_name, stream=stream)

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        structured_model: type | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        tool_names = [tool["function"]["name"] for tool in (tools or [])]
        last_text = self._extract_text(messages)
        has_tool_result = any(msg.get("role") == "tool" for msg in messages)

        if tool_choice == "required" and "generate_response" in tool_names:
            return ChatResponse(
                content=[
                    ToolUseBlock(
                        type="tool_use",
                        id=f"call_{uuid.uuid4().hex[:10]}",
                        name="generate_response",
                        input=self._judge_payload(last_text),
                    ),
                ],
            )

        available_tools = [name for name in tool_names if name != "generate_response"]
        if available_tools and tool_choice != "none" and not has_tool_result:
            chosen = available_tools[0]
            tool_schema = next(tool for tool in (tools or []) if tool["function"]["name"] == chosen)
            return ChatResponse(
                content=[
                    ToolUseBlock(
                        type="tool_use",
                        id=f"call_{uuid.uuid4().hex[:10]}",
                        name=chosen,
                        input=self._build_tool_input(chosen, tool_schema, last_text),
                    ),
                ],
            )

        base = "我建议优先选择模块化、可审计、易扩展的实现路径。"
        if has_tool_result:
            base = "基于工具验证结果，我建议将结论落到可执行方案与下一步动作。"
        return ChatResponse(content=[TextBlock(type="text", text=f"{base}\n\n结合当前上下文：{last_text[:220] or '暂无更多上下文。'}")])

    def _extract_text(self, messages: list[dict]) -> str:
        parts: list[str] = []
        for msg in messages[-4:]:
            content = msg.get("content", "")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") in {"text", "input_text"}:
                            parts.append(block.get("text", ""))
                        else:
                            parts.append(json.dumps(block, ensure_ascii=False))
        return "\n".join([p for p in parts if p]).strip()

    def _judge_payload(self, last_text: str) -> dict:
        round_no = self._find_int(last_text, r"当前轮次[:：]?\s*(\d+)") or 1
        max_rounds = self._find_int(last_text, r"最大轮次[:：]?\s*(\d+)") or settings.mock_discussion_round_cap
        finished = round_no >= min(max_rounds, settings.mock_discussion_round_cap)
        return {
            "finished": finished,
            "reason": "mock moderator decided based on configured round cap",
            "next_focus": None if finished else "继续比较方案可执行性与风险",
        }

    def _build_tool_input(self, tool_name: str, tool_schema: dict, last_text: str) -> dict:
        properties = tool_schema.get("function", {}).get("parameters", {}).get("properties", {})
        result: dict[str, Any] = {}
        for key, meta in properties.items():
            typ = meta.get("type")
            if tool_name == "topic_probe" and key == "topic":
                result[key] = last_text[:200] or "请分析当前主题"
            elif tool_name == "read_file":
                if key == "path":
                    result[key] = "README.md"
                elif key == "start_line":
                    result[key] = 1
                elif key == "end_line":
                    result[key] = 40
            elif tool_name == "list_files":
                if key == "path":
                    result[key] = "."
                elif key == "recursive":
                    result[key] = False
                elif key == "limit":
                    result[key] = 20
            elif tool_name == "write_file":
                if key == "path":
                    result[key] = "mock_notes.txt"
                elif key == "content":
                    result[key] = "mock generated content"
                elif key == "overwrite":
                    result[key] = True
            elif tool_name == "edit_file":
                if key == "path":
                    result[key] = "mock_notes.txt"
                elif key == "old_text":
                    result[key] = "mock generated content"
                elif key == "new_text":
                    result[key] = "mock updated content"
                elif key == "replace_all":
                    result[key] = False
            elif tool_name == "git_status":
                result[key] = False if typ == "boolean" else ""
            elif tool_name == "git_log":
                if key == "limit":
                    result[key] = 5
            elif tool_name == "git_diff":
                if key == "pathspec":
                    result[key] = ""
            elif tool_name == "git_add":
                if key == "pathspec":
                    result[key] = "."
            elif tool_name == "git_commit":
                if key == "message":
                    result[key] = "mock commit"
            elif typ == "string":
                result[key] = last_text[:100] or "mock-input"
            elif typ == "integer":
                result[key] = 1
            elif typ == "number":
                result[key] = 1
            elif typ == "boolean":
                result[key] = True
            else:
                result[key] = last_text[:100] or "mock-input"
        return result

    def _find_int(self, text: str, pattern: str) -> int | None:
        match = re.search(pattern, text)
        return int(match.group(1)) if match else None


def build_model(provider: ProviderConfig, model: ModelConfig):
    api_key = SecretCodec.decode(provider.api_key_encrypted)
    if provider.provider_type == "mock":
        return MockChatModel(model_name=model.model_name, stream=False)
    if provider.provider_type == "openai":
        client_kwargs = dict(model.extra_config_json.get("client_kwargs", {}))
        if provider.base_url:
            client_kwargs.setdefault("base_url", provider.base_url)
        return OpenAIChatModel(
            model_name=model.model_name,
            api_key=api_key,
            stream=model.stream_enabled,
            organization=provider.organization,
            client_kwargs=client_kwargs,
            generate_kwargs=_generate_kwargs(model),
        )
    if provider.provider_type == "azure":
        client_kwargs = dict(model.extra_config_json.get("client_kwargs", {}))
        if provider.base_url:
            client_kwargs.setdefault("azure_endpoint", provider.base_url)
        return OpenAIChatModel(
            model_name=model.model_name,
            api_key=api_key,
            stream=model.stream_enabled,
            client_type="azure",
            organization=provider.organization,
            client_kwargs=client_kwargs,
            generate_kwargs=_generate_kwargs(model),
        )
    if provider.provider_type in {"openrouter", "openai_compatible"}:
        client_kwargs = dict(model.extra_config_json.get("client_kwargs", {}))
        if provider.base_url:
            client_kwargs.setdefault("base_url", provider.base_url)
        return OpenAIChatModel(
            model_name=model.model_name,
            api_key=api_key,
            stream=model.stream_enabled,
            organization=provider.organization,
            client_kwargs=client_kwargs,
            generate_kwargs=_generate_kwargs(model),
        )
    if provider.provider_type == "anthropic":
        client_kwargs = dict(model.extra_config_json.get("client_kwargs", {}))
        if provider.base_url:
            client_kwargs.setdefault("base_url", provider.base_url)
        return AnthropicChatModel(
            model_name=model.model_name,
            api_key=api_key,
            stream=model.stream_enabled,
            client_kwargs=client_kwargs,
            generate_kwargs=_generate_kwargs(model),
        )
    if provider.provider_type == "ollama":
        return OllamaChatModel(
            model_name=model.model_name,
            stream=model.stream_enabled,
            host=provider.base_url,
            generate_kwargs=_generate_kwargs(model),
        )
    raise ValueError(f"Unsupported provider type: {provider.provider_type}")


def build_formatter(provider_type: str, formatter_type: str, *, multi_agent: bool):
    if formatter_type == "openai_chat":
        return OpenAIChatFormatter()
    if formatter_type == "openai_multi_agent":
        return OpenAIMultiAgentFormatter()
    if formatter_type == "anthropic_chat":
        return AnthropicChatFormatter()
    if formatter_type == "anthropic_multi_agent":
        return AnthropicMultiAgentFormatter()
    if formatter_type == "ollama_chat":
        return OllamaChatFormatter()
    if formatter_type == "ollama_multi_agent":
        return OllamaMultiAgentFormatter()
    if provider_type == "anthropic":
        return AnthropicMultiAgentFormatter() if multi_agent else AnthropicChatFormatter()
    if provider_type == "ollama":
        return OllamaMultiAgentFormatter() if multi_agent else OllamaChatFormatter()
    return OpenAIMultiAgentFormatter() if multi_agent else OpenAIChatFormatter()


def resolve_endpoint(provider: ProviderConfig, model: ModelConfig) -> str | None:
    client_kwargs = dict(model.extra_config_json.get("client_kwargs", {}))
    if provider.provider_type == "azure":
        return str(client_kwargs.get("azure_endpoint") or provider.base_url or "")
    if provider.provider_type in {"openai", "openrouter", "openai_compatible", "anthropic"}:
        return str(client_kwargs.get("base_url") or provider.base_url or "")
    if provider.provider_type == "ollama":
        return str(provider.base_url or client_kwargs.get("host") or "")
    return None


def _generate_kwargs(model: ModelConfig) -> dict:
    kwargs = {"temperature": model.temperature, "max_tokens": model.max_tokens}
    if model.top_p is not None:
        kwargs["top_p"] = model.top_p
    return kwargs
