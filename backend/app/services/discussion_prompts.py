from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from app.entities import AgentConfig
from app.services.context_retrieval import hybrid_search_chunks


def shorten_text(text: str, limit: int = 220) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def estimate_token_count(text: str) -> int:
    if not text:
        return 0
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9_]+", text))
    other_chars = max(0, len(text) - chinese_chars)
    return max(1, chinese_chars + latin_words + other_chars // 4)


def _truncate_multiline(text: str, limit: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}\n...[truncated]"


def _normalize_list(values: list[Any] | None, *, limit: int = 6, item_limit: int = 120) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = shorten_text(str(value or "").strip(), item_limit)
        if not text or text in result:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _json_block(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _looks_like_json_payload(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 80 or stripped[0:1] not in {"{", "["} or stripped[-1:] not in {"}", "]"}:
        return False
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, (dict, list))


def _code_or_config_line_ratio(text: str) -> float:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 0.0
    code_like = 0
    for line in lines:
        stripped = line.strip()
        if (
            re.search(r"```", stripped)
            or re.search(r'^\s*".+?"\s*:\s*.+', stripped)
            or re.search(r"^[A-Za-z0-9_.-]+\s*[:=]\s*.+", stripped)
            or re.search(r"^(def|class|function|const|let|var|if|for|while|return|SELECT|INSERT|UPDATE|DELETE)\b", stripped)
            or re.search(r"^\s*at\s+.+", stripped)
            or re.search(r"^[A-Za-z]:\\", stripped)
            or "/" in stripped and re.search(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", stripped)
        ):
            code_like += 1
            continue
        symbol_ratio = sum(1 for ch in stripped if ch in "{}[]()<>=:;,.`\\/\"'_-") / max(len(stripped), 1)
        if symbol_ratio >= 0.18:
            code_like += 1
    return code_like / len(lines)


def _density_penalty_protection(text: str) -> float:
    stripped = text.strip()
    if "```" in stripped:
        return 1.0
    if _looks_like_json_payload(stripped):
        return 1.0
    line_ratio = _code_or_config_line_ratio(stripped)
    if line_ratio >= 0.72:
        return 1.0
    if line_ratio >= 0.45 and len(stripped) >= 120:
        return 0.7
    if len(stripped) >= 180 and re.search(r"([{}\[\]:,]{16,}|[A-Za-z]:\\|Traceback|Exception:)", stripped):
        return 0.5
    return 0.0


def estimate_message_saliency(item: dict[str, Any] | None) -> tuple[float, str]:
    """估算一条消息在后续上下文中的保留价值。

    返回值包含 saliency 分数和推断出的消息类型，供检索、摘要和裁剪策略复用。
    """
    payload = dict(item or {})
    text = str(payload.get("text") or "").strip()
    if not text:
        return 0.0, "empty"

    explicit_score = payload.get("saliency_score")
    explicit_kind = str(payload.get("message_kind") or "").strip()
    if isinstance(explicit_score, (int, float)) and explicit_kind:
        bounded = max(0.0, min(float(explicit_score), 2.5))
        return bounded, explicit_kind

    trivial_messages = {
        "收到",
        "好的",
        "好",
        "明白",
        "了解",
        "赞同",
        "同意",
        "ok",
        "roger",
    }
    lowered = text.lower()
    if len(text) <= 12 and lowered in trivial_messages:
        return 0.05, "social"

    score = 0.25
    message_kind = "discussion"
    signal_hits = 0
    keyword_groups = [
        ("question", ("?", "？", "问题", "请问", "why", "how", "是否")),
        ("proposal", ("建议", "方案", "option", "proposal", "可以考虑", "推荐")),
        ("risk", ("风险", "risk", "隐患", "问题点", "瓶颈", "代价")),
        ("evidence", ("数据", "证据", "日志", "实验", "压测", "benchmark", "指标")),
        ("objection", ("不同意", "反对", "质疑", "但是", "不过", "冲突", "矛盾")),
        ("decision", ("结论", "决定", "定案", "收敛", "最终", "共识")),
    ]
    for kind, keywords in keyword_groups:
        if any(keyword in text for keyword in keywords):
            score += 0.25
            signal_hits += 1
            if message_kind == "discussion":
                message_kind = kind
    if len(text) >= 80:
        score += 0.15
    if len(text) >= 160:
        score += 0.10
    if payload.get("agent_id") == "user":
        score += 0.20
        message_kind = "user_input"
    round_no = int(payload.get("round_no") or 0)
    max_rounds = int(payload.get("max_rounds") or 0)
    if round_no > 0 and max_rounds > 1:
        phase = min(1.0, max(0.0, (round_no - 1) / max(max_rounds - 1, 1)))
        if phase <= 0.35:
            if message_kind == "question":
                score += 0.18
            elif message_kind == "objection":
                score += 0.14
            elif message_kind == "risk":
                score += 0.10
            elif message_kind == "decision":
                score -= 0.04
        elif phase <= 0.75:
            if message_kind in {"proposal", "evidence"}:
                score += 0.12
            elif message_kind == "question":
                score += 0.06
            elif message_kind == "decision":
                score += 0.04
        else:
            if message_kind == "decision":
                score += 0.22
            elif message_kind in {"proposal", "evidence"}:
                score += 0.08
            elif message_kind == "question":
                score -= 0.06
            elif message_kind == "objection":
                score -= 0.03
    density_penalty = 0.0
    if len(text) >= 180 and signal_hits <= 1:
        density_penalty = 0.18
    elif len(text) >= 300 and signal_hits <= 2:
        density_penalty = 0.12
    if density_penalty > 0:
        density_penalty *= max(0.0, 1.0 - _density_penalty_protection(text))
        score -= density_penalty
    if explicit_score is not None:
        score = max(score, float(explicit_score))
    return max(0.0, min(score, 2.5)), explicit_kind or message_kind


def _tokenize_for_retrieval(text: str) -> list[str]:
    lowered = (text or "").lower()
    tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", lowered)
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]{2,}", token):
            expanded.extend(token[index : index + 2] for index in range(len(token) - 1))
    return expanded


def _score_text(query_terms: set[str], text: str, recency_bias: float = 0.0) -> float:
    if not text:
        return 0.0
    doc_terms = Counter(_tokenize_for_retrieval(text))
    overlap = sum(1 for term in query_terms if term in doc_terms)
    if overlap == 0:
        return recency_bias
    return overlap + recency_bias + min(len(text) / 500.0, 1.5)


def compose_agent_system_prompt(
    agent: AgentConfig,
    *,
    skill_char_limit: int,
    skill_total_char_limit: int,
) -> str:
    """拼装单个 Agent 的 system prompt。

    会把角色、persona、工具、技能、MCP 等运行时能力压缩成一份模型可消费的说明。
    """
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


def _format_full_message(item: dict[str, Any]) -> str:
    speaker = str(item.get("agent_name") or item.get("speaker") or "Unknown")
    round_no = item.get("round_no", "-")
    text = str(item.get("text") or "").strip()
    return f"[Round {round_no}] {speaker}:\n{text}".strip()


def _format_round_summary(summary: dict[str, Any]) -> str:
    lines = [f"[Round {summary.get('round_no', '-')}] {summary.get('summary_text') or summary.get('decision_reason') or ''}".strip()]
    for label, key in (
        ("Key points", "key_points"),
        ("Agreements", "agreements"),
        ("Open questions", "open_questions"),
        ("Candidate options", "candidate_options"),
        ("Risks", "risks"),
    ):
        values = _normalize_list(summary.get(key), limit=4, item_limit=100)
        if values:
            lines.append(f"- {label}: {' | '.join(values)}")
    next_focus = str(summary.get("next_focus") or "").strip()
    if next_focus:
        lines.append(f"- Next focus: {shorten_text(next_focus, 120)}")
    return "\n".join(lines)


def _render_structured_state(structured_state: dict[str, Any] | None, *, include_diagnostics: bool = False) -> str:
    state = dict(structured_state or {})
    if not state:
        return "{}"
    compact = {
        "topic": state.get("topic") or "",
        "rounds_completed": state.get("rounds_completed") or 0,
        "latest_decision": state.get("latest_decision") or "in_progress",
        "latest_decision_reason": shorten_text(str(state.get("latest_decision_reason") or ""), 200),
        "next_focus": shorten_text(str(state.get("next_focus") or ""), 160) or None,
        "agreements": _normalize_list(state.get("agreements"), limit=6),
        "open_questions": _normalize_list(state.get("open_questions"), limit=6),
        "candidate_options": _normalize_list(state.get("candidate_options"), limit=6),
        "risks": _normalize_list(state.get("risks"), limit=6),
        "recent_key_points": _normalize_list(state.get("recent_key_points"), limit=6),
        "user_pinned_points": _normalize_list(state.get("user_pinned_points"), limit=6),
        "unresolved_conflicts": _normalize_list(state.get("unresolved_conflicts"), limit=6),
    }
    if include_diagnostics:
        compact["unresolved_conflict_details"] = list(state.get("unresolved_conflict_details") or [])[:4] or None
        compact["patch_metrics"] = state.get("patch_metrics") or None
    return _json_block(compact)


def _render_private_working_memory(private_working_memory: dict[str, Any] | None) -> str:
    memory = dict(private_working_memory or {})
    if not memory:
        return ""

    lines = [
        "## 私有工作记忆（仅当前 Agent 可见）",
        "以下内容仅供你私下组织思路，不代表共享事实。",
        "如果这些内容影响你的公开发言，请务必在公开回复中明确说出关键点；只有公开表达后，它们才会进入 discussion_history、round_summaries、structured_state。",
    ]

    draft_notes = _normalize_list(memory.get("draft_notes"), limit=4, item_limit=160)
    if draft_notes:
        lines.append("")
        lines.append("### 临时草稿")
        lines.extend(f"- {item}" for item in draft_notes)

    current_focus = _normalize_list(memory.get("current_focus"), limit=4, item_limit=140)
    if current_focus:
        lines.append("")
        lines.append("### 本轮关注点")
        lines.extend(f"- {item}" for item in current_focus)

    analysis_preferences = _normalize_list(memory.get("analysis_preferences"), limit=4, item_limit=160)
    if analysis_preferences:
        lines.append("")
        lines.append("### 个体分析偏好")
        lines.extend(f"- {item}" for item in analysis_preferences)

    tool_lines: list[str] = []
    for item in list(memory.get("tool_result_cache") or [])[:4]:
        if not isinstance(item, dict):
            continue
        tool_name = shorten_text(str(item.get("tool_name") or "tool"), 60)
        status = shorten_text(str(item.get("status") or "cached"), 20)
        summary = shorten_text(str(item.get("summary") or ""), 180)
        round_no = item.get("round_no")
        prefix = f"Round {round_no} | " if round_no not in {None, ''} else ""
        line = f"- {prefix}{tool_name} [{status}]"
        if summary:
            line = f"{line}: {summary}"
        tool_lines.append(line)
    if tool_lines:
        lines.append("")
        lines.append("### 工具结果缓存")
        lines.extend(tool_lines)

    return "\n".join(lines).strip()


def _render_state_patch_candidates(state_patch_candidates: list[dict[str, Any]] | None) -> str:
    lines = ["## 待审状态补丁提案"]
    items: list[str] = []
    for candidate in list(state_patch_candidates or [])[:6]:
        if not isinstance(candidate, dict):
            continue
        target = shorten_text(str(candidate.get("target_field") or ""), 40)
        operation = shorten_text(str(candidate.get("operation") or ""), 24)
        value = shorten_text(str(candidate.get("value") or ""), 120)
        agent_name = shorten_text(str(candidate.get("agent_name") or ""), 40)
        risk_level = shorten_text(str(candidate.get("risk_level") or "medium"), 20)
        status = shorten_text(str(candidate.get("status") or "pending"), 20)
        if not target or not operation or not value:
            continue
        line = f"- {agent_name or 'Agent'} proposes {operation} {target}: {value} [{risk_level}/{status}]"
        reason = shorten_text(str(candidate.get("reason") or ""), 120)
        if reason:
            line = f"{line} | reason: {reason}"
        items.append(line)
    if not items:
        return ""
    lines.extend(items)
    return "\n".join(lines)


def _render_patch_conflict_guidance(state_patch_candidates: list[dict[str, Any]] | None) -> str:
    conflicted = [
        dict(candidate)
        for candidate in list(state_patch_candidates or [])
        if isinstance(candidate, dict) and str(candidate.get("status") or "") == "conflicted"
    ]
    if not conflicted:
        return ""

    lines = [
        "## 冲突补丁裁决指引",
        "以下提案存在明显冲突。你必须给出明确裁决，而不是只复述分歧。",
        "请优先参考对应轮次及其附近原文，判断哪一方更符合公开讨论证据；若证据仍不足，请明确写入下一轮验证焦点。",
    ]
    grouped = [conflicted[index : index + 2] for index in range(0, len(conflicted), 2)]
    index = 0
    for items in grouped:
        if len(items) < 2:
            continue
        index += 1
        rounds = sorted({int(item.get('round_no') or 0) for item in items if int(item.get('round_no') or 0) > 0})
        round_hint = ""
        if rounds:
            round_hint = f"请重点核对第 {rounds[0]}-{rounds[-1]} 轮及其附近原文。"
        lines.append("")
        lines.append(f"### 冲突案例 {index}")
        for item in items[:4]:
            agent_name = shorten_text(str(item.get("agent_name") or "Agent"), 40)
            target = shorten_text(str(item.get("target_field") or ""), 40)
            operation = shorten_text(str(item.get("operation") or ""), 24)
            value = shorten_text(str(item.get("value") or ""), 120)
            lines.append(f"- {agent_name} 认为：{operation} {target} => {value}")
        lines.append(f"- 冲突解决模板：Agent A 认为 X，Agent B 认为 Y。{round_hint or '请回到相关原文给出最终判定。'}")
        lines.append("- 你的输出必须在 reason / agreements / risks / open_questions / next_focus 中体现最终裁决。")
    return "\n".join(lines) if index else ""


def _collect_archived_state_memories(structured_state: dict[str, Any] | None) -> list[str]:
    state = dict(structured_state or {})
    candidates: list[str] = []
    item_configs = [
        ("agreement_items", "归档共识"),
        ("open_question_items", "归档问题"),
        ("candidate_option_items", "归档候选方案"),
        ("risk_items", "归档风险"),
    ]
    for key, label in item_configs:
        for item in list(state.get(key) or []):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "active")
            if status == "active":
                continue
            value = shorten_text(str(item.get("value") or "").strip(), 160)
            if not value:
                continue
            support_count = int(item.get("support_count") or 1)
            importance = float(item.get("importance") or 0.5)
            candidates.append(
                f"[ARCHIVED CONTEXT - FOR REFERENCE ONLY] {label} [{status}] {value} "
                f"(importance={importance:.2f}, support={support_count})"
            )
    return candidates[:8]


def _build_query_text(
    *,
    topic: str,
    latest_text: str,
    structured_state: dict[str, Any] | None,
) -> str:
    state = structured_state or {}
    parts = [topic, latest_text, state.get("next_focus") or ""]
    for key in ("agreements", "open_questions", "candidate_options", "risks", "recent_key_points", "user_pinned_points", "unresolved_conflicts"):
        values = state.get(key)
        if isinstance(values, list):
            parts.extend(str(value) for value in values)
    return "\n".join(part for part in parts if part)


def _extract_entity_terms(text: str) -> list[str]:
    if not text:
        return []
    matches = re.findall(r"[A-Z]{2,}[A-Z0-9_/-]*|[A-Za-z0-9_./:-]*\d+[A-Za-z0-9_./:-]*|[A-Za-z0-9_./:-]+/[A-Za-z0-9_./:-]+", text)
    result: list[str] = []
    for item in matches:
        normalized = item.strip()
        if not normalized or normalized in result:
            continue
        result.append(normalized)
        if len(result) >= 8:
            break
    return result


def _state_anchor_terms(structured_state: dict[str, Any] | None) -> list[str]:
    state = structured_state or {}
    terms: list[str] = []
    for value in [state.get("topic"), *(state.get("agreements") or []), *(state.get("user_pinned_points") or [])]:
        for token in _tokenize_for_retrieval(str(value or "")):
            if token not in terms:
                terms.append(token)
            if len(terms) >= 24:
                return terms
    return terms


def _message_chunk_key(item: dict[str, Any], index: int) -> str:
    return f"message:{item.get('message_id') or index}"


def _build_retrieval_chunks(
    *,
    history: list[dict[str, Any]],
    round_summaries: list[dict[str, Any]],
    structured_state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    anchor_terms = _state_anchor_terms(structured_state)
    chunks: list[dict[str, Any]] = []
    for index, item in enumerate(history):
        text = _format_full_message(item)
        if not text:
            continue
        score, _ = estimate_message_saliency(item)
        chunks.append(
            {
                "chunk_key": _message_chunk_key(item, index),
                "source_type": "message",
                "source_ref": str(item.get("message_id") or index),
                "round_no": int(item.get("round_no") or 0),
                "agent_id": str(item.get("agent_id") or "") or None,
                "saliency_score": float(item.get("saliency_score") or score),
                "is_archived": False,
                "ordinal": index + 1,
                "text": text,
                "lexical_text": " ".join(_tokenize_for_retrieval(text)),
                "embedding_text": " ".join(_tokenize_for_retrieval(text)),
                "entity_terms": _extract_entity_terms(text),
                "anchor_terms": anchor_terms,
            }
        )

    base_ordinal = len(chunks)
    for index, item in enumerate(round_summaries):
        text = _format_round_summary(item)
        if not text:
            continue
        chunks.append(
            {
                "chunk_key": f"round_summary:{item.get('round_no', index + 1)}:{index}",
                "source_type": "round_summary",
                "source_ref": str(item.get("round_no") or index + 1),
                "round_no": int(item.get("round_no") or 0),
                "agent_id": None,
                "saliency_score": 0.9,
                "is_archived": False,
                "ordinal": base_ordinal + index + 1,
                "text": text,
                "lexical_text": " ".join(_tokenize_for_retrieval(text)),
                "embedding_text": " ".join(_tokenize_for_retrieval(text)),
                "entity_terms": _extract_entity_terms(text),
                "anchor_terms": anchor_terms,
            }
        )

    archived_base_ordinal = base_ordinal + len(round_summaries)
    for index, text in enumerate(_collect_archived_state_memories(structured_state)):
        chunks.append(
            {
                "chunk_key": f"archived_state:{index}",
                "source_type": "archived_state",
                "source_ref": str(index),
                "round_no": int((structured_state or {}).get("rounds_completed") or 0),
                "agent_id": None,
                "saliency_score": 0.7,
                "is_archived": True,
                "ordinal": archived_base_ordinal + index + 1,
                "text": text,
                "lexical_text": " ".join(_tokenize_for_retrieval(text)),
                "embedding_text": " ".join(_tokenize_for_retrieval(text)),
                "entity_terms": _extract_entity_terms(text),
                "anchor_terms": anchor_terms,
            }
        )
    return chunks


def _fit_messages_by_budget(history: list[dict[str, Any]], indexes: list[int], *, token_budget: int) -> tuple[list[dict[str, Any]], set[int]]:
    selected: list[dict[str, Any]] = []
    selected_indexes: set[int] = set()
    remaining = max(0, token_budget)
    for index in indexes:
        if index < 0 or index >= len(history):
            continue
        item = history[index]
        text = _format_full_message(item)
        tokens = estimate_token_count(text)
        if selected and tokens > remaining:
            continue
        if not selected and tokens > remaining:
            selected.append(item)
            selected_indexes.add(index)
            break
        selected.append(item)
        selected_indexes.add(index)
        remaining -= tokens
    return selected, selected_indexes


def _select_recent_messages(history: list[dict[str, Any]], *, count: int, token_budget: int) -> tuple[list[dict[str, Any]], set[int]]:
    if not history:
        return [], set()
    recent_indexes: list[int] = []
    remaining = max(0, token_budget)
    for index in range(len(history) - 1, -1, -1):
        item = history[index]
        text = _format_full_message(item)
        tokens = estimate_token_count(text)
        if recent_indexes and (len(recent_indexes) >= count or tokens > remaining):
            continue
        if not recent_indexes and tokens > remaining:
            recent_indexes.append(index)
            break
        recent_indexes.append(index)
        remaining -= tokens
        if len(recent_indexes) >= count:
            break
    recent_indexes = list(reversed(recent_indexes))

    first_content_index = next((idx for idx, item in enumerate(history) if str(item.get("text") or "").strip()), None)
    anchor_indexes = [first_content_index] if first_content_index is not None and first_content_index not in recent_indexes else []

    salient_candidates: list[tuple[float, int]] = []
    for index, item in enumerate(history):
        if index in recent_indexes or index in anchor_indexes:
            continue
        score, _ = estimate_message_saliency(item)
        if score >= 0.55:
            salient_candidates.append((score, index))
    salient_indexes = [
        index
        for _, index in sorted(salient_candidates, key=lambda item: (item[0], item[1]), reverse=True)[: max(1, count // 2)]
    ]
    ordered_indexes = sorted({*anchor_indexes, *salient_indexes, *recent_indexes})
    return _fit_messages_by_budget(history, ordered_indexes, token_budget=token_budget)


def _retrieve_older_memories_lexical(
    *,
    history: list[dict[str, Any]],
    round_summaries: list[dict[str, Any]],
    structured_state: dict[str, Any] | None,
    query_text: str,
    excluded_recent_ids: set[int],
    item_limit: int,
    token_budget: int,
) -> list[str]:
    query_terms = set(_tokenize_for_retrieval(query_text))
    if not query_terms:
        return []

    candidates: list[tuple[float, str]] = []
    total_history = len(history)
    for index, item in enumerate(history):
        if index in excluded_recent_ids:
            continue
        text = _format_full_message(item)
        score = _score_text(query_terms, text, recency_bias=index / max(total_history, 1))
        if score > 0:
            candidates.append((score, text))

    total_summaries = len(round_summaries)
    for index, item in enumerate(round_summaries):
        text = _format_round_summary(item)
        score = _score_text(query_terms, text, recency_bias=(index + 1) / max(total_summaries, 1) + 0.5)
        if score > 0:
            candidates.append((score, text))

    archived_state_memories = _collect_archived_state_memories(structured_state)
    total_archived = len(archived_state_memories)
    for index, text in enumerate(archived_state_memories):
        score = _score_text(query_terms, text, recency_bias=(index + 1) / max(total_archived, 1) + 0.8)
        if score > 0:
            candidates.append((score, text))

    selected: list[str] = []
    remaining = max(0, token_budget)
    for _, text in sorted(candidates, key=lambda item: item[0], reverse=True):
        tokens = estimate_token_count(text)
        if tokens > remaining:
            continue
        if text in selected:
            continue
        selected.append(text)
        remaining -= tokens
        if len(selected) >= item_limit:
            break
    return selected


def _retrieve_older_memories(
    *,
    run_id: str | None,
    history: list[dict[str, Any]],
    round_summaries: list[dict[str, Any]],
    structured_state: dict[str, Any] | None,
    query_text: str,
    excluded_recent_ids: set[int],
    item_limit: int,
    token_budget: int,
) -> list[str]:
    query_terms = _tokenize_for_retrieval(query_text)
    if not query_terms:
        return []

    if run_id:
        excluded_chunk_keys = {
            _message_chunk_key(history[index], index)
            for index in excluded_recent_ids
            if 0 <= index < len(history)
        }
        chunks = _build_retrieval_chunks(
            history=history,
            round_summaries=round_summaries,
            structured_state=structured_state,
        )
        hybrid_results = hybrid_search_chunks(
            run_id=run_id,
            chunks=chunks,
            query_text=" ".join(query_terms),
            query_terms=query_terms,
            vector_anchor_terms=_state_anchor_terms(structured_state),
            excluded_chunk_keys=excluded_chunk_keys,
            item_limit=max(1, item_limit),
        )
        selected: list[str] = []
        remaining = max(0, token_budget)
        for item in hybrid_results:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            tokens = estimate_token_count(text)
            if tokens > remaining:
                continue
            if text in selected:
                continue
            selected.append(text)
            remaining -= tokens
            if len(selected) >= item_limit:
                return selected

    return _retrieve_older_memories_lexical(
        history=history,
        round_summaries=round_summaries,
        structured_state=structured_state,
        query_text=query_text,
        excluded_recent_ids=excluded_recent_ids,
        item_limit=item_limit,
        token_budget=token_budget,
    )


def _fit_section(title: str, items: list[str], *, token_budget: int) -> str:
    if not items or token_budget <= 0:
        return ""
    prefix = f"## {title}\n"
    used = estimate_token_count(prefix)
    lines: list[str] = []
    for item in items:
        line = item.strip()
        if not line:
            continue
        tokens = estimate_token_count(line) + 1
        if lines and used + tokens > token_budget:
            break
        if not lines and used + tokens > token_budget:
            continue
        lines.append(line)
        used += tokens
    return prefix + "\n\n".join(lines) if lines else ""


def format_discussion_context(
    history: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    round_summaries: list[dict[str, Any]] | None = None,
    structured_state: dict[str, Any] | None = None,
    prompt_token_budget: int,
    recent_full_message_count: int,
    retrieval_item_limit: int,
) -> str:
    """按预算拼装讨论上下文。

    优先尝试完整历史；超预算时退化为结构化状态 + 最近原文 + 轮次总结 + 老历史召回。
    """
    if not history and not round_summaries:
        return "暂无历史讨论内容。请先给出你的初步判断，并保持讨论推进的口吻。"

    full_history_items = [_format_full_message(item) for item in history]
    full_history_block = _fit_section("完整历史原文", full_history_items, token_budget=prompt_token_budget)
    structured_block = _fit_section("结构化状态", [_render_structured_state(structured_state)], token_budget=max(200, prompt_token_budget // 4))

    full_candidate = "\n\n".join(block for block in [structured_block, full_history_block] if block)
    # 如果完整历史仍在预算内，优先保留原文，避免过早摘要损失语义。
    if full_history_block and estimate_token_count(full_candidate) <= prompt_token_budget:
        return full_candidate

    recent_messages, selected_indexes = _select_recent_messages(
        history,
        count=max(1, recent_full_message_count),
        token_budget=max(200, int(prompt_token_budget * 0.45)),
    )
    recent_message_texts = [_format_full_message(item) for item in recent_messages]

    query_text = _build_query_text(
        topic=str((structured_state or {}).get("topic") or ""),
        latest_text=str(history[-1].get("text") if history else ""),
        structured_state=structured_state,
    )
    older_memories = _retrieve_older_memories(
        run_id=run_id,
        history=history,
        round_summaries=round_summaries or [],
        structured_state=structured_state,
        query_text=query_text,
        excluded_recent_ids=selected_indexes,
        item_limit=max(1, retrieval_item_limit),
        token_budget=max(180, int(prompt_token_budget * 0.25)),
    )

    recent_round_summaries = [
        _format_round_summary(item)
        for item in (round_summaries or [])[-max(2, recent_full_message_count // 2) :]
    ]

    sections = [
        _fit_section("结构化状态", [_render_structured_state(structured_state)], token_budget=max(220, int(prompt_token_budget * 0.20))),
        _fit_section("最近原文", recent_message_texts, token_budget=max(280, int(prompt_token_budget * 0.40))),
        _fit_section("最近轮次总结", recent_round_summaries, token_budget=max(180, int(prompt_token_budget * 0.18))),
        _fit_section("较老历史召回", older_memories, token_budget=max(160, int(prompt_token_budget * 0.17))),
    ]
    context = "\n\n".join(section for section in sections if section)
    return context or "暂无可用讨论上下文。"


def build_agent_turn_prompt(
    *,
    run_id: str | None = None,
    topic: str,
    round_no: int,
    max_rounds: int,
    agent_name: str,
    history: list[dict[str, Any]],
    round_summaries: list[dict[str, Any]],
    structured_state: dict[str, Any] | None,
    private_working_memory: dict[str, Any] | None,
    prompt_token_budget: int,
    recent_full_message_count: int,
    retrieval_item_limit: int,
) -> str:
    """生成 Agent 单轮发言 Prompt。

    Prompt 同时包含共享上下文和私有工作记忆，并明确要求先回应上一位发言者。
    """
    latest = history[-1] if history else None
    latest_hint = (
        f"最近一位发言者是 {latest['agent_name']}，请先回应他的最新观点，再补充你的新增判断。"
        if latest
        else "当前还没有其他智能体发言，请先给出你的初步判断。"
    )
    context = format_discussion_context(
        history,
        run_id=run_id,
        round_summaries=round_summaries,
        structured_state=structured_state,
        prompt_token_budget=prompt_token_budget,
        recent_full_message_count=recent_full_message_count,
        retrieval_item_limit=retrieval_item_limit,
    )
    private_memory_block = _render_private_working_memory(private_working_memory)
    return (
        f"当前议题：{topic}\n"
        f"当前轮次：{round_no}\n"
        f"最大轮次：{max_rounds}\n"
        f"你当前代表：{agent_name}\n\n"
        "你现在处于多智能体交替讨论，不是独立答题。请严格遵守：\n"
        "1. 先回应最近一位智能体的观点，说明你赞同、质疑或补充的点。\n"
        "2. 再提出你的新增判断，推动讨论向共识收敛。\n"
        "3. 避免重复原题答案，避免简单复述自己或他人的旧观点。\n"
        "4. 输出应体现“讨论推进”，而不是重新开题。\n"
        "5. 如果你引用私有工作记忆中的内容，必须在公开回复里把关键点明确说出来。\n"
        "6. 如果你认为共享状态需要更新，只能基于你的公开发言提出补丁提案。\n\n"
        f"{latest_hint}\n\n"
        f"{context}\n\n"
        f"{private_memory_block}\n\n"
        "If you believe the shared state should be updated, you may append an optional block at the end in this exact format:\n"
        "[STATE PATCH PROPOSAL]\n"
        "- add risk: ...\n"
        "- add open_question: ...\n"
        "- close open_question: ...\n"
        "- add candidate_option: ...\n"
        "- add recent_key_point: ...\n"
        "- remove agreement: ...\n"
        "This block is optional. Only emit it when this round introduces a significant state change.\n"
        "Only propose patches that are explicitly supported by your public message.\n"
    )


def build_moderator_prompt(
    *,
    run_id: str | None = None,
    topic: str,
    round_no: int,
    max_rounds: int,
    history: list[dict[str, Any]],
    round_summaries: list[dict[str, Any]],
    structured_state: dict[str, Any] | None,
    state_patch_candidates: list[dict[str, Any]] | None,
    prompt_token_budget: int,
    recent_full_message_count: int,
    retrieval_item_limit: int,
) -> str:
    """生成主持人裁决 Prompt。

    除了常规上下文外，还会附带待审 patch 和冲突裁决指引。
    """
    context = format_discussion_context(
        history,
        run_id=run_id,
        round_summaries=round_summaries,
        structured_state=structured_state,
        prompt_token_budget=prompt_token_budget,
        recent_full_message_count=recent_full_message_count,
        retrieval_item_limit=retrieval_item_limit,
    )
    patch_block = _render_state_patch_candidates(state_patch_candidates)
    conflict_block = _render_patch_conflict_guidance(state_patch_candidates)
    schema = {
        "finished": True,
        "reason": "请说明当前裁决原因",
        "next_focus": "若未结束，请写明下一轮聚焦点；若结束可为 null",
        "key_points": ["本轮关键观点"],
        "agreements": ["已形成的共识"],
        "disagreements": ["仍存在的分歧"],
        "open_questions": ["尚未解决的问题"],
        "candidate_options": ["候选方案"],
        "risks": ["需要关注的风险"],
    }
    return (
        f"请判断讨论是否结束。当前议题：{topic}\n"
        f"当前轮次：{round_no}\n"
        f"最大轮次：{max_rounds}\n\n"
        "请只在以下条件都满足时才判定 finished=true：\n"
        "1. 参与者已经明确回应了彼此观点，而不是各自独立答题；\n"
        "2. 已经收敛出较稳定的结论；\n"
        "3. 再继续讨论的新增价值有限。\n\n"
        "You must review and respond to the agent state patch proposals below. Do not ignore them.\n"
        "If a proposal should affect the shared state, reflect that in your final structured decision.\n"
        "If a proposal should not be accepted, ensure your decision rationale is consistent with rejecting it.\n\n"
        "请仅返回 JSON，不要输出 Markdown 或额外说明。\n"
        "JSON 中必须包含 finished / reason / next_focus，并尽量补充其余结构化字段。\n"
        f"JSON 参考格式：{_json_block(schema)}\n\n"
        f"{patch_block}\n\n"
        f"{conflict_block}\n\n"
        f"{context}\n"
    )


def build_final_report(
    *,
    session_name: str,
    topic: str,
    history: list[dict[str, Any]],
    round_summaries: list[dict[str, Any]] | None,
    structured_state: dict[str, Any] | None,
    rounds: int,
    per_message_char_limit: int,
) -> tuple[str, str, dict]:
    """把完整讨论历史压缩成最终报告标题、Markdown 摘要和结构化结论。"""
    transcript = [
        f"- 第 {item['round_no']} 轮 · {item['agent_name']}：{shorten_text(item['text'], per_message_char_limit)}"
        for item in history
        if str(item.get("text") or "").strip()
    ]
    state = dict(structured_state or {})
    summaries = list(round_summaries or [])
    summary_lines = [
        f"# {session_name} 讨论纪要",
        "",
        f"- 主题：{topic}",
        f"- 实际轮次：{rounds}",
        f"- 有效发言数：{len(transcript)}",
        "",
        "## 结构化状态",
        _render_structured_state(state, include_diagnostics=True),
        "",
        "## 轮次总结",
    ]
    if summaries:
        summary_lines.extend(_format_round_summary(item) for item in summaries)
    else:
        summary_lines.append("- 暂无轮次总结。")

    summary_lines.extend(["", "## 讨论摘录"])
    if transcript:
        summary_lines.extend(transcript)
    else:
        summary_lines.append("- 本次运行未产生有效发言。")

    conclusion_json = {
        "topic": topic,
        "rounds": rounds,
        "message_count": len(transcript),
        "participant_names": sorted({str(item.get('agent_name') or '') for item in history if item.get("agent_name")}),
        "structured_state": state,
        "round_summaries": summaries,
    }
    return f"{session_name} Final Report", "\n".join(summary_lines), conclusion_json
