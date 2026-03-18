from __future__ import annotations

import json
import re

from app.entities import AgentConfig, ChatSession
from app.services.feishu_models import ParsedCommand, ParsedMessageContext


class FeishuCommandService:
    def parse_message_context(self, message: dict) -> ParsedMessageContext:
        raw_content = message.get("content") or "{}"
        try:
            content = json.loads(raw_content) if isinstance(raw_content, str) else dict(raw_content)
        except Exception:
            content = {}
        text = str(content.get("text") or content.get("title") or "").strip()
        mentions = message.get("mentions") or []
        for mention in mentions:
            key = str(mention.get("key") or "").strip()
            name = str(mention.get("name") or "").strip()
            if key and name:
                text = text.replace(key, f"@{name}")
        text = re.sub(r"<at[^>]*>(.*?)</at>", lambda matched: f"@{matched.group(1).strip()}", text, flags=re.IGNORECASE)
        normalized_text = re.sub(r"\s+", " ", text).strip()
        mention_names = [str(item.get("name") or "").strip() for item in mentions if str(item.get("name") or "").strip()]
        normalized_mentions = {self.normalize_name(name) for name in mention_names if name}
        return ParsedMessageContext(
            text=normalized_text,
            mentions=list(mentions),
            mention_names=mention_names,
            normalized_mentions=normalized_mentions,
        )

    def parse_command(
        self,
        message_ctx: ParsedMessageContext,
        *,
        session: ChatSession | None,
        source: dict,
        available_agents: list[AgentConfig] | None = None,
    ) -> ParsedCommand | None:
        text = message_ctx.text
        if not text:
            return None

        agent_records = self.agent_records(session, available_agents=available_agents)
        agent_names = [agent.name for agent in agent_records]
        agent_name_map = {self.normalize_name(agent_name): agent_name for agent_name in agent_names}
        bot_name_map = self.agent_bot_name_map(session, available_agents=agent_records)
        normalized = self._strip_leading_mention_for_command(text.strip())
        lowered = normalized.lower()

        source_kind = str(source.get("kind") or "host")
        if lowered in {"#help", "help", "帮助"}:
            return ParsedCommand(kind="help", target_mode=source_kind)

        if lowered in {"暂停", "#pause", "pause"}:
            return ParsedCommand(kind="pause", target_mode=source_kind)
        if lowered in {"继续", "恢复", "#resume", "resume"}:
            return ParsedCommand(kind="resume", target_mode=source_kind)
        if lowered in {"停止", "结束", "#stop", "stop"}:
            return ParsedCommand(kind="stop", target_mode=source_kind)

        if self.looks_like_start(lowered, normalized):
            topic = self.extract_start_topic(normalized)
            mentioned_agents = self.mentioned_agent_names(message_ctx, agent_name_map, bot_name_map)
            return ParsedCommand(kind="start", topic=topic, mentioned_agents=mentioned_agents, target_mode=source_kind)

        if lowered.startswith("#ask"):
            body = normalized[4:].strip(" ：:")
            agent_name, question = self._split_agent_and_question(body, agent_names, agent_name_map, bot_name_map)
            if agent_name and question:
                return ParsedCommand(kind="ask", agent_name=agent_name, question=question, target_mode="agent")
            return ParsedCommand(kind="help", target_mode=source_kind)

        agent_name, question = self._extract_mention_ask(normalized, agent_names, agent_name_map, bot_name_map, message_ctx)
        if agent_name and question:
            return ParsedCommand(kind="ask", agent_name=agent_name, question=question, target_mode="agent")

        if source_kind == "agent":
            agent_bot = source.get("config")
            if agent_bot and getattr(agent_bot, "agent_id", None):
                bound_name = self.agent_name_by_id(session, agent_bot.agent_id, available_agents=agent_records)
                if bound_name:
                    stripped = self._strip_any_leading_mention(normalized)
                    if stripped:
                        return ParsedCommand(kind="ask", agent_name=bound_name, question=stripped, target_mode="agent")

        return None

    def help_text(self, session: ChatSession | None, *, available_agents: list[AgentConfig] | None = None) -> str:
        agent_records = self.agent_records(session, available_agents=available_agents)
        agent_lines = [
            f"- {agent.name}{f'（机器人：{agent.feishu_bot.bot_name}）' if agent.feishu_bot and agent.feishu_bot.bot_name else ''}"
            for agent in agent_records
        ]
        agents_text = "\n".join(agent_lines) if agent_lines else "- 暂无可用 Agent"
        return (
            "飞书接入第二版命令说明：\n"
            "1. #start 讨论主题\n"
            "2. 开始讨论：讨论主题\n"
            "3. 暂停 / 继续 / 停止\n"
            "4. #ask Agent名称: 你的问题\n"
            "5. @Agent名称 你的问题\n"
            "6. @机器人名 你的问题\n"
            "7. 讨论运行中直接发送用户补充信息，会自动触发软中断并注入上下文\n\n"
            f"当前会话可用 Agent：\n{agents_text}"
        )

    def normalize_name(self, value: str) -> str:
        return re.sub(r"[\s_()（）\[\]【】\-]+", "", value or "").lower()

    def agent_records(self, session: ChatSession | None, *, available_agents: list[AgentConfig] | None = None) -> list[AgentConfig]:
        if available_agents is not None:
            return list(available_agents)
        if not session:
            return []
        return [link.agent for link in sorted(session.agents, key=lambda item: item.speak_order)]

    def agent_bot_name_map(self, session: ChatSession | None, *, available_agents: list[AgentConfig] | None = None) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for agent in self.agent_records(session, available_agents=available_agents):
            bot = agent.feishu_bot
            if bot and bot.bot_name:
                mapping[self.normalize_name(bot.bot_name)] = agent.name
        return mapping

    def mentioned_agent_names(
        self,
        message_ctx: ParsedMessageContext,
        agent_name_map: dict[str, str],
        bot_name_map: dict[str, str],
    ) -> list[str]:
        found: list[str] = []
        for normalized in message_ctx.normalized_mentions:
            if normalized in bot_name_map and bot_name_map[normalized] not in found:
                found.append(bot_name_map[normalized])
            elif normalized in agent_name_map and agent_name_map[normalized] not in found:
                found.append(agent_name_map[normalized])
        return found

    def looks_like_start(self, lowered: str, normalized: str) -> bool:
        return any(
            lowered.startswith(prefix) or prefix in lowered
            for prefix in ("#start", "#topic", "开始讨论", "发起讨论", "开始一下讨论", "发起一下讨论")
        ) or ("开始讨论" in normalized and ("：" in normalized or ":" in normalized))

    def extract_start_topic(self, normalized: str) -> str | None:
        for prefix in ("#start", "#topic", "开始讨论", "发起讨论", "开始一下讨论", "发起一下讨论"):
            idx = normalized.lower().find(prefix.lower())
            if idx != -1:
                return normalized[idx + len(prefix) :].strip(" ：:")
        if "开始讨论" in normalized:
            return normalized.rsplit("开始讨论", 1)[1].strip(" ：:")
        return None

    def agent_name_by_id(
        self,
        session: ChatSession | None,
        agent_id: str,
        *,
        available_agents: list[AgentConfig] | None = None,
    ) -> str | None:
        for agent in self.agent_records(session, available_agents=available_agents):
            if agent.id == agent_id:
                return agent.name
        return None

    def _strip_leading_mention_for_command(self, text: str) -> str:
        normalized = text.strip()
        previous = normalized
        while normalized.startswith(("@", "＠")):
            parts = normalized.split(" ", 1)
            if len(parts) != 2:
                break
            remainder = parts[1].strip()
            lowered = remainder.lower()
            if lowered.startswith(("#start", "#topic", "#ask")) or remainder.startswith(("开始讨论", "发起讨论", "帮助", "help", "@", "＠")):
                previous = normalized
                normalized = remainder
                continue
            return previous
        return normalized

    def _split_agent_and_question(
        self,
        text: str,
        agent_names: list[str],
        agent_name_map: dict[str, str],
        bot_name_map: dict[str, str],
    ) -> tuple[str | None, str | None]:
        for sep in (":", "："):
            if sep in text:
                left, right = text.split(sep, 1)
                candidate = left.strip()
                question = right.strip()
                matched = self._match_agent_name(candidate, agent_names, agent_name_map, bot_name_map)
                if matched and question:
                    return matched, question
        for agent_name in agent_names:
            if text.startswith(agent_name):
                question = text[len(agent_name) :].strip(" ：:")
                if question:
                    return agent_name, question
        return None, None

    def _match_agent_name(
        self,
        candidate: str,
        agent_names: list[str],
        agent_name_map: dict[str, str],
        bot_name_map: dict[str, str],
    ) -> str | None:
        for agent_name in agent_names:
            if candidate == agent_name or candidate.lower() == agent_name.lower():
                return agent_name
        normalized = self.normalize_name(candidate.lstrip("@＠"))
        if normalized in agent_name_map:
            return agent_name_map[normalized]
        if normalized in bot_name_map:
            return bot_name_map[normalized]
        return None

    def _extract_mention_ask(
        self,
        normalized: str,
        agent_names: list[str],
        agent_name_map: dict[str, str],
        bot_name_map: dict[str, str],
        message_ctx: ParsedMessageContext,
    ) -> tuple[str | None, str | None]:
        candidate_names = []
        for raw_name in message_ctx.mention_names:
            matched = self._match_agent_name(raw_name, agent_names, agent_name_map, bot_name_map)
            if matched and matched not in candidate_names:
                candidate_names.append(matched)
        for agent_name in candidate_names:
            question = self._remove_agent_mentions_from_text(normalized, agent_name, message_ctx.mention_names)
            if question:
                return agent_name, question
        return None, None

    def _remove_agent_mentions_from_text(self, text: str, agent_name: str, mention_names: list[str]) -> str:
        result = text
        for raw_name in mention_names:
            result = result.replace(f"@{raw_name}", " ")
            result = result.replace(f"＠{raw_name}", " ")
        result = result.replace(f"@{agent_name}", " ").replace(f"＠{agent_name}", " ")
        return re.sub(r"\s+", " ", result).strip(" ：:")

    def _strip_any_leading_mention(self, text: str) -> str:
        normalized = text.strip()
        while normalized.startswith(("@", "＠")):
            parts = normalized.split(" ", 1)
            if len(parts) != 2:
                break
            normalized = parts[1].strip()
        return normalized
