from __future__ import annotations

import re
from typing import Any

from app.entities import AgentConfig


def shorten_text(text: str, limit: int = 220) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def _truncate_multiline(text: str, limit: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}\n...[truncated]"


def compose_agent_system_prompt(
    agent: AgentConfig,
    *,
    skill_char_limit: int,
    skill_total_char_limit: int,
) -> str:
    sections = [agent.system_prompt.strip()]

    enabled_skills = [binding.skill for binding in agent.skill_bindings if binding.skill.enabled]
    if enabled_skills and skill_total_char_limit > 0 and skill_char_limit > 0:
        remaining = skill_total_char_limit
        skill_sections: list[str] = []
        omitted = 0
        for skill in enabled_skills:
            if remaining <= 0:
                omitted += 1
                continue
            snippet = _truncate_multiline(skill.content, min(skill_char_limit, remaining))
            if not snippet:
                continue
            block = f"- {skill.name}: {skill.description}\n{snippet}".strip()
            if len(block) > remaining:
                block = _truncate_multiline(block, remaining)
            if not block:
                omitted += 1
                continue
            skill_sections.append(block)
            remaining -= len(block)
        if omitted:
            skill_sections.append(f"- {omitted} additional skill(s) omitted to keep prompt compact.")
        if skill_sections:
            sections.append("## Mounted Skills\n" + "\n\n".join(skill_sections))

    enabled_mcps = [binding.mcp for binding in agent.mcp_bindings if binding.mcp.enabled]
    if enabled_mcps:
        mcp_lines = []
        for mcp in enabled_mcps:
            endpoint = mcp.base_url or mcp.command or "-"
            slug = re.sub(r"[^a-zA-Z0-9_]+", "_", mcp.name).strip("_").lower() or "server"
            mcp_lines.append(
                (
                    f"- {mcp.name} [{mcp.transport_type}] endpoint={endpoint}\n"
                    f"  description: {mcp.description or '-'}\n"
                    f"  tool name: mcp_{slug}\n"
                    "  call pattern: provide action + payload_json"
                ).rstrip(),
            )
        sections.append(
            "## Mounted MCP Servers\n"
            "Below are available MCP resources for this agent. These MCPs are mounted as callable tools.\n"
            + "\n".join(mcp_lines)
        )

    return "\n\n".join([section for section in sections if section])


def format_discussion_context(history: list[dict[str, Any]], *, max_messages: int) -> str:
    if not history:
        return "暂无历史发言。你需要先给出初步观点，但仍需保持讨论口吻。"

    lines = []
    for item in history[-max_messages:]:
        lines.append(f"- Round {item['round_no']} | {item['agent_name']}: {shorten_text(item['text'])}")
    return "\n".join(lines)


def build_agent_turn_prompt(
    *,
    topic: str,
    round_no: int,
    max_rounds: int,
    agent_name: str,
    history: list[dict[str, Any]],
    context_messages: int,
) -> str:
    recent_context = format_discussion_context(history, max_messages=context_messages)
    latest = history[-1] if history else None
    latest_hint = (
        f"最近一位发言者是 {latest['agent_name']}，他的核心观点是：{shorten_text(latest['text'], 160)}"
        if latest
        else "当前还没有其他智能体发言。"
    )
    return (
        f"当前议题：{topic}\n"
        f"当前轮次：{round_no}\n"
        f"最大轮次：{max_rounds}\n"
        f"你当前代表：{agent_name}\n\n"
        "你现在处于多智能体交替讨论，不是独立答题。请严格遵守：\n"
        "1. 先回应最近一位智能体的观点，说明你赞同、质疑或补充的点。\n"
        "2. 再提出你的新增判断，推动讨论向共识收敛。\n"
        "3. 避免重复原题答案，避免简单复述自己或他人的旧观点。\n"
        "4. 输出应体现“讨论推进”，而不是重新开题。\n\n"
        f"{latest_hint}\n\n"
        "最近讨论上下文：\n"
        f"{recent_context}\n"
    )


def build_moderator_prompt(
    *,
    topic: str,
    round_no: int,
    max_rounds: int,
    history: list[dict[str, Any]],
    context_messages: int,
) -> str:
    return (
        f"请判断讨论是否结束。当前议题：{topic}\n"
        f"当前轮次：{round_no}\n"
        f"最大轮次：{max_rounds}\n\n"
        "请只在以下条件都满足时才判定 finished=true：\n"
        "1. 参与者已经明确回应了彼此观点，而不是各自独立答题；\n"
        "2. 已经收敛出较稳定的结论；\n"
        "3. 再继续讨论新增价值有限。\n"
        "最近讨论上下文：\n"
        f"{format_discussion_context(history, max_messages=context_messages)}\n\n"
        "若未结束，请给出下一轮应重点讨论的分歧点或待验证点。"
    )


def build_final_report(
    *,
    session_name: str,
    topic: str,
    history: list[dict[str, Any]],
    rounds: int,
    per_message_char_limit: int,
) -> tuple[str, str, dict]:
    transcript = [
        f"- 第 {item['round_no']} 轮 · {item['agent_name']}：{shorten_text(item['text'], per_message_char_limit)}"
        for item in history
        if str(item.get("text") or "").strip()
    ]
    summary_lines = [
        f"# {session_name} 讨论纪要",
        "",
        f"- 主题：{topic}",
        f"- 实际轮次：{rounds}",
        f"- 有效发言数：{len(transcript)}",
        "",
        "## 讨论摘要",
    ]
    if transcript:
        summary_lines.extend(transcript)
    else:
        summary_lines.append("- 本次运行未产生有效发言。")
    conclusion_json = {
        "topic": topic,
        "rounds": rounds,
        "message_count": len(transcript),
        "participant_names": sorted({str(item.get('agent_name') or '') for item in history if item.get("agent_name")}),
    }
    return f"{session_name} Final Report", "\n".join(summary_lines), conclusion_json
