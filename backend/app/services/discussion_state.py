from __future__ import annotations

import re
import uuid
from typing import Any, Mapping

from app.entities import AgentConfig
from app.runtime_common import ModeratorDecision, StatePatchProposal, StructuredStateItem
from app.services.discussion_prompts import estimate_message_saliency, shorten_text


def clean_string_list(values: Any, *, limit: int = 8, item_limit: int = 160) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        text = shorten_text(str(value or "").strip(), item_limit)
        if not text or text in result:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result


def merge_unique(existing: list[str], incoming: list[str], *, limit: int = 12) -> list[str]:
    merged: list[str] = []
    for value in [*existing, *incoming]:
        normalized = value.strip()
        if not normalized or normalized in merged:
            continue
        merged.append(normalized)
        if len(merged) >= limit:
            break
    return merged


def build_history_message(
    *,
    round_no: int,
    max_rounds: int | None = None,
    agent_id: str,
    agent_name: str,
    text: str,
    message_id: str | None = None,
    message_kind: str | None = None,
    explicit_saliency_score: float | None = None,
    human_priority: str | None = None,
) -> dict[str, Any]:
    score, inferred_kind = estimate_message_saliency(
        {
            "agent_id": agent_id,
            "text": text,
            "message_kind": message_kind or "",
            "round_no": round_no,
            "max_rounds": max_rounds,
            "saliency_score": explicit_saliency_score,
        }
    )
    return {
        "message_id": message_id or uuid.uuid4().hex,
        "round_no": round_no,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "text": text,
        "message_kind": message_kind or inferred_kind,
        "saliency_score": score,
        "human_priority": human_priority,
    }


def _build_state_item(value: str, *, round_no: int, source: str, importance: float, status: str = "active") -> dict[str, Any]:
    return StructuredStateItem(
        value=value,
        status=status,
        created_round=round_no,
        last_seen_round=round_no,
        importance=max(0.0, min(float(importance), 1.0)),
        support_count=1,
        source=source,
    ).model_dump()


def _normalize_state_values(values: list[str] | None, *, limit: int = 8, item_limit: int = 160) -> list[str]:
    return clean_string_list(values, limit=limit, item_limit=item_limit)


def _upsert_state_items(
    existing: list[dict[str, Any]] | None,
    values: list[str] | None,
    *,
    round_no: int,
    source: str,
    importance: float,
    limit: int = 12,
) -> list[dict[str, Any]]:
    items = [dict(item) for item in list(existing or []) if isinstance(item, dict)]
    for value in _normalize_state_values(values, limit=limit):
        matched = next((item for item in items if str(item.get("value") or "").strip() == value), None)
        if matched is None:
            items.append(_build_state_item(value, round_no=round_no, source=source, importance=importance))
            continue
        matched["status"] = "active"
        matched["last_seen_round"] = round_no
        matched["support_count"] = min(int(matched.get("support_count") or 1) + 1, 99)
        matched["importance"] = min(1.0, float(matched.get("importance") or 0.5) + 0.08)
    return sorted(
        items,
        key=lambda item: (float(item.get("importance") or 0.0), int(item.get("last_seen_round") or 0), int(item.get("support_count") or 0)),
        reverse=True,
    )[:limit]


def _mark_state_items(
    existing: list[dict[str, Any]] | None,
    values: list[str] | None,
    *,
    round_no: int,
    new_status: str,
) -> list[dict[str, Any]]:
    items = [dict(item) for item in list(existing or []) if isinstance(item, dict)]
    targets = set(_normalize_state_values(values, limit=12))
    for item in items:
        if str(item.get("value") or "").strip() in targets:
            item["status"] = new_status
            item["last_seen_round"] = round_no
    return items


def _active_state_values(items: list[dict[str, Any]] | None, *, allowed_statuses: set[str] | None = None, limit: int = 12) -> list[str]:
    allowed = allowed_statuses or {"active"}
    ordered = sorted(
        [dict(item) for item in list(items or []) if isinstance(item, dict) and str(item.get("status") or "active") in allowed],
        key=lambda item: (float(item.get("importance") or 0.0), int(item.get("last_seen_round") or 0), int(item.get("support_count") or 0)),
        reverse=True,
    )
    values: list[str] = []
    for item in ordered:
        value = str(item.get("value") or "").strip()
        if not value or value in values:
            continue
        values.append(value)
        if len(values) >= limit:
            break
    return values


def sync_structured_state_views(state: dict[str, Any]) -> dict[str, Any]:
    state["agreements"] = _active_state_values(state.get("agreement_items"), allowed_statuses={"active"}, limit=12)
    state["open_questions"] = _active_state_values(state.get("open_question_items"), allowed_statuses={"active"}, limit=12)
    state["candidate_options"] = _active_state_values(state.get("candidate_option_items"), allowed_statuses={"active", "selected"}, limit=12)
    state["risks"] = _active_state_values(state.get("risk_items"), allowed_statuses={"active"}, limit=12)
    return state


def merge_unique_items(existing: list[str] | None, incoming: list[str] | None, *, limit: int = 8) -> list[str]:
    merged: list[str] = []
    for value in [*(existing or []), *(incoming or [])]:
        text = shorten_text(str(value or "").strip(), 180)
        if not text or text in merged:
            continue
        merged.append(text)
        if len(merged) >= limit:
            break
    return merged


def apply_semantic_ttl(state: dict[str, Any] | None, *, round_no: int, max_rounds: int | None = None) -> dict[str, Any]:
    updated = dict(state or {})
    next_focus = str(updated.get("next_focus") or "").strip()
    phase = 0.0
    if max_rounds and max_rounds > 1:
        phase = min(1.0, max(0.0, (round_no - 1) / max(max_rounds - 1, 1)))
    late_phase = phase >= 0.75

    def _ttl_items(key: str, *, inactive_after: int, low_importance_threshold: float, archive_status: str) -> None:
        items = [dict(item) for item in list(updated.get(key) or []) if isinstance(item, dict)]
        for item in items:
            if str(item.get("status") or "active") != "active":
                continue
            value = str(item.get("value") or "").strip()
            age = max(0, round_no - int(item.get("last_seen_round") or 0))
            importance = float(item.get("importance") or 0.5)
            support_count = int(item.get("support_count") or 1)
            if value and next_focus and value == next_focus:
                continue
            effective_inactive_after = inactive_after
            effective_threshold = low_importance_threshold
            if late_phase:
                if key == "open_question_items":
                    effective_inactive_after = max(1, inactive_after - 1)
                    effective_threshold = min(0.92, low_importance_threshold + 0.08)
                elif key == "candidate_option_items":
                    effective_inactive_after = max(1, inactive_after - 1)
                    effective_threshold = min(0.88, low_importance_threshold + 0.06)
            if age >= effective_inactive_after and importance <= effective_threshold and support_count <= 1:
                item["status"] = archive_status
        updated[key] = items

    _ttl_items("open_question_items", inactive_after=3, low_importance_threshold=0.78, archive_status="archived")
    _ttl_items("candidate_option_items", inactive_after=3, low_importance_threshold=0.72, archive_status="deprecated")
    _ttl_items("risk_items", inactive_after=4, low_importance_threshold=0.68, archive_status="archived")
    updated["recent_key_points"] = list(updated.get("recent_key_points") or [])[-10:]
    return sync_structured_state_views(updated)


def _patch_risk_level(target_field: str, operation: str) -> str:
    normalized_field = target_field.strip()
    normalized_operation = operation.strip()
    if normalized_field == "next_focus" or normalized_operation == "replace":
        return "high"
    if normalized_operation in {"remove", "close", "reopen"}:
        return "high" if normalized_field == "agreements" else "medium"
    if normalized_field in {"agreements", "risks"}:
        return "medium"
    return "low"


def _patch_semantic_tokens(text: str) -> set[str]:
    lowered = (text or "").lower()
    tokens = set(re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", lowered))
    for token in list(tokens):
        if re.fullmatch(r"[\u4e00-\u9fff]{2,}", token):
            tokens.update(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


def _signals_negative_constraint(text: str) -> bool:
    lowered = (text or "").lower()
    markers = ("不可", "不能", "不行", "不足", "缺少", "风险", "阻塞", "失败", "冲突", "否决", "not", "cannot", "risk")
    return any(marker in lowered for marker in markers)


_PATCH_ANTONYM_PAIRS = [
    ("可行", "不可行"),
    ("通过", "未通过"),
    ("满足", "不满足"),
    ("可接受", "不可接受"),
    ("已解决", "未解决"),
    ("收敛", "未收敛"),
    ("稳定", "不稳定"),
    ("feasible", "not feasible"),
    ("acceptable", "unacceptable"),
    ("resolved", "unresolved"),
    ("pass", "fail"),
]


def _has_antonym_conflict(left_text: str, right_text: str) -> bool:
    left = (left_text or "").lower()
    right = (right_text or "").lower()
    for positive, negative in _PATCH_ANTONYM_PAIRS:
        pos = positive.lower()
        neg = negative.lower()
        if (pos in left and neg in right) or (neg in left and pos in right):
            return True
    return False


def _patches_semantically_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_target = str(left.get("target_field") or "")
    right_target = str(right.get("target_field") or "")
    left_value = str(left.get("value") or "")
    right_value = str(right.get("value") or "")
    if not left_target or not right_target or not left_value or not right_value:
        return False

    direct_conflict = {("agreements", "risks"), ("candidate_options", "risks"), ("agreements", "open_questions")}
    pair = (left_target, right_target)
    reverse_pair = (right_target, left_target)
    if pair not in direct_conflict and reverse_pair not in direct_conflict:
        return False

    overlap = _patch_semantic_tokens(left_value) & _patch_semantic_tokens(right_value)
    if len(overlap) < 1 and not _has_antonym_conflict(left_value, right_value):
        return False
    return (
        _signals_negative_constraint(left_value)
        or _signals_negative_constraint(right_value)
        or _has_antonym_conflict(left_value, right_value)
    )


def _parse_patch_operation(raw_operation: str) -> tuple[str, str] | None:
    text = raw_operation.strip().lower().replace("_", " ")
    if not text:
        return None
    mapping = {
        "risk": "risks",
        "risks": "risks",
        "agreement": "agreements",
        "agreements": "agreements",
        "open question": "open_questions",
        "open questions": "open_questions",
        "open_question": "open_questions",
        "candidate option": "candidate_options",
        "candidate options": "candidate_options",
        "candidate_option": "candidate_options",
        "recent key point": "recent_key_points",
        "recent key points": "recent_key_points",
        "recent_key_point": "recent_key_points",
        "next focus": "next_focus",
        "next_focus": "next_focus",
    }
    parts = text.split()
    if not parts:
        return None
    operation = parts[0]
    field_raw = " ".join(parts[1:])
    target_field = mapping.get(field_raw)
    if operation not in {"add", "remove", "replace", "close", "reopen"} or not target_field:
        return None
    return operation, target_field


def extract_state_patch_proposals(
    raw_text: str,
    *,
    round_no: int,
    agent_id: str,
    agent_name: str,
    source_message_id: str,
) -> tuple[str, list[dict[str, Any]]]:
    marker = "[STATE PATCH PROPOSAL]"
    text = (raw_text or "").strip()
    marker_index = text.find(marker)
    if marker_index < 0:
        return text, []

    public_text = text[:marker_index].rstrip()
    patch_block = text[marker_index + len(marker) :].strip()
    proposals: list[dict[str, Any]] = []
    evidence_refs = [source_message_id]
    for line in patch_block.splitlines():
        normalized = line.strip()
        if not normalized.startswith("-"):
            continue
        body = normalized[1:].strip()
        if ":" not in body:
            continue
        raw_operation, raw_value = body.split(":", 1)
        parsed = _parse_patch_operation(raw_operation)
        value = shorten_text(raw_value.strip(), 180)
        if parsed is None or not value:
            continue
        operation, target_field = parsed
        proposal = StatePatchProposal(
            id=uuid.uuid4().hex,
            round_no=round_no,
            agent_id=agent_id,
            agent_name=agent_name,
            source_message_id=source_message_id,
            target_field=target_field,
            operation=operation,
            value=value,
            reason=shorten_text(public_text, 200) if public_text else None,
            confidence=0.55 if operation == "add" else 0.65,
            evidence_refs=evidence_refs,
            risk_level=_patch_risk_level(target_field, operation),
        )
        proposals.append(proposal.model_dump())
    return public_text or text, proposals


def group_patch_conflicts(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = [dict(item) for item in candidates if isinstance(item, dict)]
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        target = str(item.get("target_field") or "")
        value = str(item.get("value") or "")
        operation = str(item.get("operation") or "")
        key = (target, value)
        previous = seen.get(key)
        if previous and previous.get("operation") != operation:
            item["status"] = "conflicted"
            previous["status"] = "conflicted"
            item["risk_level"] = "high"
            previous["risk_level"] = "high"
        else:
            seen[key] = item
    for index, item in enumerate(items):
        for other in items[index + 1 :]:
            if _patches_semantically_conflict(item, other):
                item["status"] = "conflicted"
                other["status"] = "conflicted"
                item["risk_level"] = "high"
                other["risk_level"] = "high"
    return items


def _semantic_match(patch_value: str, state_value: str) -> bool:
    left = shorten_text(str(patch_value or "").strip(), 200).lower()
    right = shorten_text(str(state_value or "").strip(), 200).lower()
    if not left or not right:
        return False
    if left == right:
        return True
    if _has_antonym_conflict(left, right):
        return False
    if min(len(left), len(right)) >= 6 and (left in right or right in left):
        return True
    left_tokens = _patch_semantic_tokens(left)
    right_tokens = _patch_semantic_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = left_tokens & right_tokens
    if not overlap:
        return False
    left_ratio = len(overlap) / max(len(left_tokens), 1)
    right_ratio = len(overlap) / max(len(right_tokens), 1)
    return left_ratio >= 0.6 or right_ratio >= 0.6 or len(overlap) >= 3


def apply_patch_to_structured_state(state: dict[str, Any] | None, patch: dict[str, Any], *, round_no: int, source: str) -> dict[str, Any]:
    updated = dict(state or {})
    target = str(patch.get("target_field") or "")
    operation = str(patch.get("operation") or "")
    value = shorten_text(str(patch.get("value") or "").strip(), 160)
    if not target or not operation or not value:
        return updated
    if target == "recent_key_points":
        current = list(updated.get("recent_key_points") or [])
        if operation == "add":
            updated["recent_key_points"] = merge_unique(current, [value], limit=10)[-10:]
        return updated
    if target == "next_focus" and operation in {"replace", "add"}:
        updated["next_focus"] = value
        return updated

    key_map = {
        "agreements": "agreement_items",
        "open_questions": "open_question_items",
        "candidate_options": "candidate_option_items",
        "risks": "risk_items",
    }
    item_key = key_map.get(target)
    if not item_key:
        return updated
    if operation in {"add", "reopen"}:
        updated[item_key] = _upsert_state_items(
            updated.get(item_key),
            [value],
            round_no=round_no,
            source=source,
            importance=0.58 if source == "patch_auto" else 0.72,
        )
    elif operation == "remove":
        updated[item_key] = _mark_state_items(updated.get(item_key), [value], round_no=round_no, new_status="removed")
    elif operation == "close":
        close_status = "resolved" if target == "open_questions" else "archived"
        updated[item_key] = _mark_state_items(updated.get(item_key), [value], round_no=round_no, new_status=close_status)
    return sync_structured_state_views(updated)


def moderator_patch_metrics(patch_log: list[dict[str, Any]] | None) -> dict[str, Any]:
    moderator_entries = [
        dict(item)
        for item in list(patch_log or [])
        if str(item.get("decided_by") or "") == "moderator"
        and str(item.get("decision") or "") in {"accepted_by_moderator", "rejected_by_moderator"}
    ]
    total = len(moderator_entries)
    accepted = sum(1 for item in moderator_entries if str(item.get("decision")) == "accepted_by_moderator")
    overall_rate = round(accepted / total, 4) if total else None

    by_agent_raw: dict[str, dict[str, Any]] = {}
    by_field_raw: dict[str, dict[str, Any]] = {}
    for item in moderator_entries:
        agent_id = str(item.get("proposal_agent_id") or "")
        agent_name = str(item.get("proposal_agent_name") or "") or agent_id or "unknown"
        target_field = str(item.get("target_field") or "unknown")
        accepted_item = str(item.get("decision")) == "accepted_by_moderator"

        if agent_id:
            bucket = by_agent_raw.setdefault(
                agent_id,
                {"agent_id": agent_id, "agent_name": agent_name, "proposed": 0, "adopted": 0},
            )
            bucket["proposed"] += 1
            bucket["adopted"] += 1 if accepted_item else 0

        bucket = by_field_raw.setdefault(
            target_field,
            {"target_field": target_field, "proposed": 0, "adopted": 0},
        )
        bucket["proposed"] += 1
        bucket["adopted"] += 1 if accepted_item else 0

    by_agent = [
        {
            **bucket,
            "moderator_adoption_rate": round(bucket["adopted"] / bucket["proposed"], 4) if bucket["proposed"] else None,
        }
        for bucket in by_agent_raw.values()
    ]
    by_field = [
        {
            **bucket,
            "moderator_adoption_rate": round(bucket["adopted"] / bucket["proposed"], 4) if bucket["proposed"] else None,
        }
        for bucket in by_field_raw.values()
    ]
    by_agent.sort(key=lambda item: (item["moderator_adoption_rate"] or 0.0, item["proposed"]), reverse=True)
    by_field.sort(key=lambda item: (item["moderator_adoption_rate"] or 0.0, item["proposed"]), reverse=True)
    return {
        "moderator_patch_decisions": total,
        "moderator_patch_adopted": accepted,
        "moderator_adoption_rate": overall_rate,
        "by_agent": by_agent[:8],
        "by_field": by_field[:8],
    }


def annotate_patch_log_metrics(patch_log: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    annotated = [dict(item) for item in list(patch_log or [])]
    metrics = moderator_patch_metrics(annotated)
    by_agent = {
        str(item.get("agent_id") or ""): item.get("moderator_adoption_rate")
        for item in metrics.get("by_agent", [])
        if item.get("agent_id")
    }
    by_field = {
        str(item.get("target_field") or ""): item.get("moderator_adoption_rate")
        for item in metrics.get("by_field", [])
        if item.get("target_field")
    }
    for item in annotated:
        agent_id = str(item.get("proposal_agent_id") or "")
        target_field = str(item.get("target_field") or "")
        item["moderator_adoption_rate"] = metrics.get("moderator_adoption_rate")
        item["moderator_adoption_rate_by_agent"] = by_agent.get(agent_id)
        item["moderator_adoption_rate_by_field"] = by_field.get(target_field)
    return annotated


def _reason_is_vague(reason: str | None) -> bool:
    normalized = shorten_text(str(reason or "").strip(), 200)
    if len(normalized) < 18:
        return True
    vague_markers = ("仍需更多讨论", "需要继续讨论", "信息不足", "证据不足", "暂不明确", "继续观察", "仍有分歧", "继续验证")
    return any(marker in normalized for marker in vague_markers)


def _text_mentions_value(container: str, value: str) -> bool:
    return bool(value and value in container)


def resolve_unresolved_conflicts(
    candidates: list[dict[str, Any]] | None,
    *,
    structured_state: dict[str, Any] | None,
    decision_reason: str | None,
    round_no: int,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    state = dict(structured_state or {})
    conflicted = [dict(item) for item in list(candidates or []) if str(item.get("status") or "") == "conflicted"]
    if not conflicted:
        return list(state.get("unresolved_conflicts") or []), list(state.get("unresolved_conflict_details") or []), []

    state_text_parts = [
        str(state.get("next_focus") or ""),
        *[str(value) for value in state.get("agreements") or []],
        *[str(value) for value in state.get("open_questions") or []],
        *[str(value) for value in state.get("candidate_options") or []],
        *[str(value) for value in state.get("risks") or []],
    ]
    state_text = "\n".join(part for part in state_text_parts if part)
    unresolved = list(state.get("unresolved_conflicts") or [])
    details = [dict(item) for item in list(state.get("unresolved_conflict_details") or []) if isinstance(item, dict)]
    patch_log: list[dict[str, Any]] = []
    for item in conflicted:
        value = shorten_text(str(item.get("value") or "").strip(), 160)
        if not value:
            continue
        resolved_by_state = _text_mentions_value(state_text, value)
        if resolved_by_state and not _reason_is_vague(decision_reason):
            continue
        summary = shorten_text(f"{item.get('agent_name') or 'Agent'} 关于 {item.get('target_field') or 'state'} 的冲突主张：{value}", 180)
        if summary not in unresolved:
            unresolved.append(summary)
        detail = {
            "summary": summary,
            "agent_name": item.get("agent_name"),
            "agent_id": item.get("agent_id"),
            "target_field": item.get("target_field"),
            "operation": item.get("operation"),
            "value": value,
            "round_no": item.get("round_no"),
            "status": "unresolved_conflict",
            "reason": shorten_text(str(decision_reason or ""), 180) or None,
        }
        if not any(str(existing.get("summary") or "") == summary for existing in details):
            details.append(detail)
        patch_log.append(
            {
                "patch_id": item.get("id"),
                "decision": "unresolved_conflict",
                "decided_by": "runtime",
                "round_no": round_no,
                "proposal_agent_id": item.get("agent_id"),
                "proposal_agent_name": item.get("agent_name"),
                "target_field": item.get("target_field"),
                "operation": item.get("operation"),
                "value": value,
            }
        )
    return unresolved[-8:], details[-8:], patch_log[-20:]


def pin_user_focus_point(state: dict[str, Any] | None, text: str) -> dict[str, Any]:
    updated = dict(state or {})
    pinned = merge_unique_items(updated.get("user_pinned_points"), [text], limit=6)
    updated["user_pinned_points"] = pinned
    updated["recent_key_points"] = merge_unique(
        list(updated.get("recent_key_points") or []),
        [shorten_text(f"用户重点关注：{text}", 180)],
        limit=10,
    )[-10:]
    return updated


def structured_state_preview(state: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(state or {})
    return {
        "next_focus": current.get("next_focus"),
        "user_pinned_points": list(current.get("user_pinned_points") or [])[:6],
        "unresolved_conflicts": list(current.get("unresolved_conflicts") or [])[:6],
        "unresolved_conflict_details": list(current.get("unresolved_conflict_details") or [])[:6],
        "patch_metrics": current.get("patch_metrics") or None,
    }


def apply_safe_state_patch_candidates(
    state: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    structured_state = dict(state.get("structured_state") or {})
    patch_log = list(state.get("state_patch_log") or [])
    remaining: list[dict[str, Any]] = []
    for candidate in group_patch_conflicts(list(state.get("state_patch_candidates") or [])):
        risk_level = str(candidate.get("risk_level") or "medium")
        operation = str(candidate.get("operation") or "")
        target_field = str(candidate.get("target_field") or "")
        can_auto_apply = (
            str(candidate.get("status") or "pending") != "conflicted"
            and risk_level == "low"
            and operation == "add"
            and target_field in {"open_questions", "candidate_options", "recent_key_points"}
        )
        if can_auto_apply:
            structured_state = apply_patch_to_structured_state(
                structured_state,
                candidate,
                round_no=int(candidate.get("round_no") or state.get("round_no") or 0),
                source="patch_auto",
            )
            candidate["status"] = "accepted_auto"
            patch_log.append(
                {
                    "patch_id": candidate.get("id"),
                    "decision": "accepted_auto",
                    "decided_by": "runtime",
                    "round_no": candidate.get("round_no"),
                    "proposal_agent_id": candidate.get("agent_id"),
                    "proposal_agent_name": candidate.get("agent_name"),
                    "target_field": candidate.get("target_field"),
                    "operation": candidate.get("operation"),
                    "value": candidate.get("value"),
                }
            )
            continue
        remaining.append(candidate)
    structured_state = apply_semantic_ttl(
        structured_state,
        round_no=int(state.get("round_no") or 0),
        max_rounds=int(state.get("max_rounds") or 0),
    )
    return structured_state, remaining, patch_log[-50:]


def finalize_patch_candidates(
    candidates: list[dict[str, Any]],
    *,
    structured_state: dict[str, Any] | None,
    round_no: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    active_state = dict(structured_state or {})
    patch_log: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    list_fields = {"agreements", "open_questions", "candidate_options", "risks", "recent_key_points"}
    for candidate in list(candidates or []):
        item = dict(candidate)
        target = str(item.get("target_field") or "")
        value = str(item.get("value") or "")
        operation = str(item.get("operation") or "")
        status = str(item.get("status") or "pending")
        if status != "pending":
            remaining.append(item)
            continue
        accepted = False
        if target in list_fields:
            current_values = [str(v) for v in list(active_state.get(target) or [])]
            has_match = any(_semantic_match(value, current) for current in current_values)
            if operation in {"add", "reopen"}:
                accepted = has_match
            elif operation in {"remove", "close"}:
                accepted = not has_match
        elif target == "next_focus":
            current_focus = str(active_state.get("next_focus") or "")
            focus_matches = _semantic_match(value, current_focus)
            accepted = focus_matches if operation in {"add", "replace"} else not focus_matches
        item["status"] = "accepted_by_moderator" if accepted else "rejected_by_moderator"
        patch_log.append(
            {
                "patch_id": item.get("id"),
                "decision": item["status"],
                "decided_by": "moderator",
                "round_no": round_no,
                "proposal_agent_id": item.get("agent_id"),
                "proposal_agent_name": item.get("agent_name"),
                "target_field": target,
                "operation": operation,
                "value": value,
            }
        )
    return [], patch_log[-50:]


def current_round_messages(state: Mapping[str, Any], round_no: int) -> list[dict[str, Any]]:
    return [
        item
        for item in state.get("discussion_history", [])
        if int(item.get("round_no") or 0) == round_no and item.get("agent_id") != "user"
    ]


def build_round_summary_record(state: Mapping[str, Any], decision: ModeratorDecision) -> dict[str, Any]:
    round_no = int(state["round_no"])
    round_messages = current_round_messages(state, round_no)
    key_points = clean_string_list(
        decision.key_points or [f"{item.get('agent_name')}: {item.get('text')}" for item in round_messages],
        limit=6,
        item_limit=180,
    )
    open_questions = clean_string_list(
        decision.open_questions + ([decision.next_focus] if decision.next_focus else []),
        limit=6,
    )
    summary_text = (
        f"主持人裁决：{decision.reason or '本轮已完成裁决。'}"
        if decision.finished
        else f"主持人裁决：{decision.reason or '本轮暂不结束。'}"
    )
    if decision.next_focus:
        summary_text = f"{summary_text} 下一轮聚焦：{decision.next_focus}"
    return {
        "round_no": round_no,
        "summary_text": summary_text,
        "decision_reason": decision.reason,
        "next_focus": decision.next_focus,
        "finished": bool(decision.finished),
        "key_points": key_points,
        "agreements": clean_string_list(decision.agreements),
        "disagreements": clean_string_list(decision.disagreements),
        "open_questions": open_questions,
        "candidate_options": clean_string_list(decision.candidate_options),
        "risks": clean_string_list(decision.risks),
    }


def merge_structured_state(
    previous: dict[str, Any] | None,
    *,
    topic: str,
    round_no: int,
    max_rounds: int,
    participant_names: list[str],
    round_summary: dict[str, Any],
) -> dict[str, Any]:
    state = dict(previous or {})
    state["topic"] = topic
    state["rounds_completed"] = max(int(state.get("rounds_completed") or 0), round_no)
    state["participant_names"] = sorted({*map(str, state.get("participant_names", [])), *participant_names})
    state["latest_decision"] = "finished" if round_summary.get("finished") else "continue"
    state["latest_decision_reason"] = round_summary.get("decision_reason") or ""
    state["next_focus"] = None if round_summary.get("finished") else round_summary.get("next_focus")
    state["agreement_items"] = _upsert_state_items(
        state.get("agreement_items"),
        list(round_summary.get("agreements") or []),
        round_no=round_no,
        source="moderator",
        importance=0.82,
    )
    state["open_question_items"] = _upsert_state_items(
        state.get("open_question_items"),
        list(round_summary.get("open_questions") or []),
        round_no=round_no,
        source="moderator",
        importance=0.78,
    )
    state["candidate_option_items"] = _upsert_state_items(
        state.get("candidate_option_items"),
        list(round_summary.get("candidate_options") or []),
        round_no=round_no,
        source="moderator",
        importance=0.70,
    )
    state["risk_items"] = _upsert_state_items(
        state.get("risk_items"),
        list(round_summary.get("risks") or []),
        round_no=round_no,
        source="moderator",
        importance=0.76,
    )
    state["recent_key_points"] = merge_unique(
        list(state.get("recent_key_points") or []),
        list(round_summary.get("key_points") or []),
        limit=10,
    )[-10:]
    state["user_pinned_points"] = merge_unique_items(state.get("user_pinned_points"), [], limit=6)
    state["unresolved_conflicts"] = merge_unique_items(state.get("unresolved_conflicts"), [], limit=8)
    state["last_round_summary"] = round_summary.get("summary_text") or ""
    return apply_semantic_ttl(state, round_no=round_no, max_rounds=max_rounds)


def build_agent_analysis_preferences(agent: AgentConfig) -> list[str]:
    preferences: list[str] = []
    role = shorten_text(str(agent.role or "").strip(), 80)
    persona = shorten_text(str(agent.persona or "").strip(), 140)
    system_prompt = shorten_text(str(agent.system_prompt or "").strip(), 160)
    if role:
        preferences.append(f"角色视角：{role}")
    if persona:
        preferences.append(f"个体风格：{persona}")
    if system_prompt:
        preferences.append(f"默认方法偏好：{system_prompt}")
    return preferences[:4]


def _clean_private_tool_cache(items: Any, *, limit: int = 4) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        tool_name = shorten_text(str(item.get("tool_name") or "").strip(), 60)
        status = shorten_text(str(item.get("status") or "cached").strip(), 24)
        summary = shorten_text(str(item.get("summary") or "").strip(), 200)
        round_no = item.get("round_no")
        if not tool_name and not summary:
            continue
        result.append(
            {
                "tool_name": tool_name or "tool",
                "status": status or "cached",
                "summary": summary,
                "round_no": round_no,
            }
        )
    return result[-limit:]


def prepare_private_working_memory(
    agent: AgentConfig,
    existing: dict[str, Any] | None,
    *,
    topic: str,
    latest_message: dict[str, Any] | None,
    structured_state: dict[str, Any] | None,
) -> dict[str, Any]:
    memory = dict(existing or {})
    next_focus = shorten_text(str((structured_state or {}).get("next_focus") or "").strip(), 120)
    latest_speaker = shorten_text(str((latest_message or {}).get("agent_name") or "").strip(), 80)

    current_focus: list[str] = []
    if next_focus:
        current_focus.append(f"优先关注：{next_focus}")
    if latest_speaker and str((latest_message or {}).get("agent_id") or "") != agent.id:
        current_focus.append(f"先回应 {latest_speaker} 的最新观点")
    if topic:
        current_focus.append(f"围绕议题推进：{shorten_text(topic, 100)}")

    draft_notes: list[str] = []
    if latest_speaker and str((latest_message or {}).get("agent_id") or "") != agent.id:
        draft_notes.append(f"先对 {latest_speaker} 的观点表态，再补充你的新增判断。")
    if next_focus:
        draft_notes.append(f"公开发言尽量落到“{next_focus}”。")
    elif topic:
        draft_notes.append(f"公开发言继续围绕主题“{shorten_text(topic, 100)}”。")

    memory["draft_notes"] = clean_string_list(draft_notes, limit=3, item_limit=160)
    memory["current_focus"] = clean_string_list(current_focus, limit=4, item_limit=140)
    memory["analysis_preferences"] = clean_string_list(
        memory.get("analysis_preferences") or build_agent_analysis_preferences(agent),
        limit=4,
        item_limit=160,
    )
    memory["tool_result_cache"] = _clean_private_tool_cache(memory.get("tool_result_cache"))
    return memory


def apply_private_tool_updates(
    memory: dict[str, Any] | None,
    *,
    tool_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = dict(memory or {})
    merged = [*list(updated.get("tool_result_cache") or []), *tool_updates]
    updated["tool_result_cache"] = _clean_private_tool_cache(merged)
    return updated
