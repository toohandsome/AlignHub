from __future__ import annotations

import asyncio

from app.core import RealtimeBroker
from app.runtime_common import EventService, ModeratorDecision
from app.runtime_langgraph import (
    DiscussionEngine,
    _apply_safe_state_patch_candidates,
    _apply_semantic_ttl,
    _build_moderator_summary_text,
    _extract_json_object,
    _extract_state_patch_proposals,
    _finalize_patch_candidates,
    _group_patch_conflicts,
    _resolve_unresolved_conflicts,
)
from app.schemas import RunControlRequest
from app.services.discussion_prompts import build_moderator_prompt

ZH_MORE_DATA = "\u8865\u5145\u98ce\u9669"
ZH_NOT_CONVERGED = "\u7ed3\u8bba\u672a\u6536\u655b"
ZH_NEXT_FOCUS = "\u8865\u5145\u6027\u80fd\u57fa\u7ebf"
ZH_AGREEMENT = "\u9700\u8981\u5148\u76d8\u70b9\u4e8b\u5b9e"
ZH_OPEN = "\u6027\u80fd\u57fa\u7ebf\u662f\u591a\u5c11"
ZH_RISK = "\u7f3a\u5c11\u538b\u6d4b\u6570\u636e"
ZH_FINISH_TEXT = "\u8ba8\u8bba\u5df2\u8db3\u591f\u6536\u655b\uff0c\u53ef\u4ee5\u7ed3\u675f\u3002"
ZH_UNSTABLE = "\u7ed3\u8bba\u8fd8\u4e0d\u7a33\u5b9a"
ZH_COMPARE = "\u8865\u5145\u6210\u672c\u548c\u98ce\u9669\u5bf9\u6bd4"
ZH_FINISHED_BANNER = "\u672c\u8f6e\u8ba8\u8bba\u5df2\u6536\u655b\uff0c\u53ef\u4ee5\u7ed3\u675f"
ZH_CONTINUE_BANNER = "\u672c\u8f6e\u8ba8\u8bba\u6682\u4e0d\u7ed3\u675f"
ZH_CONVERGED = "\u8ba8\u8bba\u5df2\u6536\u655b"


def _engine() -> DiscussionEngine:
    return DiscussionEngine(EventService(RealtimeBroker()))


def test_extract_json_object_from_fenced_block() -> None:
    payload = _extract_json_object(
        f"""```json
        {{"finished": false, "reason": "need more data", "next_focus": "{ZH_MORE_DATA}"}}
        ```"""
    )
    assert payload == {"finished": False, "reason": "need more data", "next_focus": ZH_MORE_DATA}


def test_parse_moderator_decision_uses_json_payload() -> None:
    engine = _engine()
    state = {"round_no": 2, "max_rounds": 4}
    decision = engine._parse_moderator_decision(
        f'{{"finished": false, "reason": "{ZH_NOT_CONVERGED}", "next_focus": "{ZH_NEXT_FOCUS}", "agreements": ["{ZH_AGREEMENT}"], "open_questions": ["{ZH_OPEN}"], "risks": ["{ZH_RISK}"]}}',
        state,
    )
    assert decision.finished is False
    assert decision.reason == ZH_NOT_CONVERGED
    assert decision.next_focus == ZH_NEXT_FOCUS
    assert decision.agreements == [ZH_AGREEMENT]
    assert decision.open_questions == [ZH_OPEN, ZH_NEXT_FOCUS]
    assert decision.risks == [ZH_RISK]


def test_parse_moderator_decision_falls_back_for_plain_text() -> None:
    engine = _engine()
    state = {"round_no": 4, "max_rounds": 4}
    decision = engine._parse_moderator_decision(ZH_FINISH_TEXT, state)
    assert decision.finished is True
    assert ZH_FINISH_TEXT in (decision.reason or "")
    assert decision.next_focus is None


def test_build_moderator_summary_text_for_continue() -> None:
    text = _build_moderator_summary_text(
        ModeratorDecision(finished=False, reason=ZH_UNSTABLE, next_focus=ZH_COMPARE),
    )
    assert ZH_CONTINUE_BANNER in text
    assert ZH_UNSTABLE in text
    assert ZH_COMPARE in text


def test_build_moderator_summary_text_for_finish() -> None:
    text = _build_moderator_summary_text(
        ModeratorDecision(finished=True, reason=ZH_CONVERGED, next_focus=None),
    )
    assert ZH_FINISHED_BANNER in text
    assert ZH_CONVERGED in text


def test_extract_state_patch_proposals_splits_public_text_and_patch_block() -> None:
    public_text, patches = _extract_state_patch_proposals(
        "我们还缺少压测基线。\n\n[STATE PATCH PROPOSAL]\n- add risk: 缺少压测基线\n- add open_question: 方案A的高并发延迟是多少",
        round_no=2,
        agent_id="agent-1",
        agent_name="架构师",
        source_message_id="msg-1",
    )
    assert public_text == "我们还缺少压测基线。"
    assert len(patches) == 2
    assert patches[0]["target_field"] == "risks"
    assert patches[0]["operation"] == "add"
    assert patches[1]["target_field"] == "open_questions"


def test_apply_safe_state_patch_candidates_auto_accepts_low_risk_additions() -> None:
    structured_state, pending, patch_log = _apply_safe_state_patch_candidates(
        {
            "round_no": 3,
            "structured_state": {
                "topic": "讨论发布策略",
                "open_question_items": [],
                "candidate_option_items": [],
                "risk_items": [],
                "agreement_items": [],
                "recent_key_points": [],
            },
            "state_patch_candidates": [
                {
                    "id": "patch-1",
                    "round_no": 3,
                    "agent_id": "agent-1",
                    "agent_name": "架构师",
                    "target_field": "open_questions",
                    "operation": "add",
                    "value": "是否需要先补压测",
                    "risk_level": "low",
                    "status": "pending",
                },
            ],
            "state_patch_log": [],
        }
    )
    assert "是否需要先补压测" in structured_state["open_questions"]
    assert pending == []
    assert patch_log[-1]["decision"] == "accepted_auto"


def test_apply_semantic_ttl_archives_stale_open_questions() -> None:
    state = _apply_semantic_ttl(
        {
            "next_focus": None,
            "open_question_items": [
                {
                    "value": "是否需要补压测",
                    "status": "active",
                    "created_round": 1,
                    "last_seen_round": 1,
                    "importance": 0.4,
                    "support_count": 1,
                    "source": "moderator",
                }
            ],
            "candidate_option_items": [],
            "risk_items": [],
            "agreement_items": [],
            "recent_key_points": [],
        },
        round_no=5,
        max_rounds=10,
    )
    assert state["open_question_items"][0]["status"] == "archived"
    assert state["open_questions"] == []


def test_apply_semantic_ttl_is_more_aggressive_in_late_phase_for_low_priority_questions() -> None:
    state = _apply_semantic_ttl(
        {
            "next_focus": "方案对比",
            "open_question_items": [
                {
                    "value": "是否补充边缘场景说明",
                    "status": "active",
                    "created_round": 6,
                    "last_seen_round": 7,
                    "importance": 0.82,
                    "support_count": 1,
                    "source": "moderator",
                }
            ],
            "candidate_option_items": [],
            "risk_items": [],
            "agreement_items": [],
            "recent_key_points": [],
        },
        round_no=9,
        max_rounds=10,
    )
    assert state["open_question_items"][0]["status"] == "archived"


def test_group_patch_conflicts_marks_cross_field_semantic_conflicts_high_risk() -> None:
    grouped = _group_patch_conflicts(
        [
            {
                "id": "patch-1",
                "target_field": "agreements",
                "operation": "add",
                "value": "方案A可行",
                "risk_level": "medium",
                "status": "pending",
            },
            {
                "id": "patch-2",
                "target_field": "risks",
                "operation": "add",
                "value": "方案A不可行，存在回滚风险",
                "risk_level": "medium",
                "status": "pending",
            },
        ]
    )
    assert grouped[0]["status"] == "conflicted"
    assert grouped[1]["status"] == "conflicted"
    assert grouped[0]["risk_level"] == "high"


def test_group_patch_conflicts_uses_antonym_pairs_for_semantic_conflict() -> None:
    grouped = _group_patch_conflicts(
        [
            {
                "id": "patch-3",
                "target_field": "agreements",
                "operation": "add",
                "value": "方案B已解决回滚问题，可接受",
                "risk_level": "medium",
                "status": "pending",
            },
            {
                "id": "patch-4",
                "target_field": "risks",
                "operation": "add",
                "value": "方案B回滚问题未解决，不可接受",
                "risk_level": "medium",
                "status": "pending",
            },
        ]
    )
    assert grouped[0]["status"] == "conflicted"
    assert grouped[1]["status"] == "conflicted"


def test_moderator_prompt_forces_review_of_patch_candidates() -> None:
    prompt = build_moderator_prompt(
        topic="讨论发布策略",
        round_no=3,
        max_rounds=5,
        history=[{"round_no": 3, "agent_name": "架构师", "text": "我建议继续审查回滚链路。"}],
        round_summaries=[],
        structured_state={"topic": "讨论发布策略", "rounds_completed": 2},
        state_patch_candidates=[
            {
                "agent_name": "架构师",
                "target_field": "open_questions",
                "operation": "add",
                "value": "是否需要补充回滚演练",
                "risk_level": "medium",
                "status": "pending",
            }
        ],
        prompt_token_budget=3200,
        recent_full_message_count=6,
        retrieval_item_limit=6,
    )
    lowered = prompt.lower()
    assert "must review and respond" in lowered
    assert "do not ignore" in lowered


def test_moderator_prompt_includes_conflict_resolution_template_for_conflicted_patches() -> None:
    prompt = build_moderator_prompt(
        topic="讨论发布策略",
        round_no=5,
        max_rounds=8,
        history=[{"round_no": 5, "agent_name": "架构师", "text": "请重点核对方案A的可行性。"}],
        round_summaries=[],
        structured_state={"topic": "讨论发布策略", "rounds_completed": 4},
        state_patch_candidates=[
            {
                "agent_name": "Agent A",
                "target_field": "agreements",
                "operation": "add",
                "value": "方案A可行",
                "risk_level": "high",
                "status": "conflicted",
                "round_no": 4,
            },
            {
                "agent_name": "Agent B",
                "target_field": "risks",
                "operation": "add",
                "value": "方案A不可行",
                "risk_level": "high",
                "status": "conflicted",
                "round_no": 5,
            },
        ],
        prompt_token_budget=3200,
        recent_full_message_count=6,
        retrieval_item_limit=6,
    )
    assert "冲突补丁裁决指引" in prompt
    assert "冲突解决模板" in prompt
    assert "第 4-5 轮" in prompt


def test_unresolved_conflict_is_raised_when_moderator_reason_is_vague() -> None:
    unresolved, details, patch_log = _resolve_unresolved_conflicts(
        [
            {
                "id": "patch-x",
                "agent_id": "agent-a",
                "agent_name": "Agent A",
                "target_field": "agreements",
                "operation": "add",
                "value": "方案A可行",
                "status": "conflicted",
            }
        ],
        structured_state={"agreements": [], "open_questions": [], "candidate_options": [], "risks": [], "next_focus": ""},
        decision_reason="仍有分歧，继续讨论。",
        round_no=5,
    )
    assert unresolved
    assert details
    assert patch_log[-1]["decision"] == "unresolved_conflict"


def test_mark_important_user_input_gets_max_saliency_and_pinned_state() -> None:
    engine = _engine()

    async def run() -> dict:
        control = engine.control("run-test")
        await control.add_input(message="请始终优先关注回滚链路完整性。", mark_important=True)
        return await engine._inject_inputs_node(
            {
                "run_id": "run-test",
                "round_no": 2,
                "max_rounds": 8,
                "discussion_history": [],
                "structured_state": {"topic": "发布策略", "recent_key_points": [], "user_pinned_points": []},
            }
        )

    result = asyncio.run(run())
    history = result["discussion_history"]
    structured_state = result["structured_state"]
    assert history[-1]["saliency_score"] == 2.5
    assert history[-1]["human_priority"] == "pinned"
    assert "请始终优先关注回滚链路完整性。" in structured_state["user_pinned_points"]


def test_run_control_request_accepts_mark_important_flag() -> None:
    payload = RunControlRequest(message="请继续", source="frontend", mark_important=True)
    assert payload.mark_important is True


def test_finalize_patch_candidates_accepts_semantically_equivalent_moderator_update() -> None:
    remaining, patch_log = _finalize_patch_candidates(
        [
            {
                "id": "patch-semantic",
                "agent_id": "agent-1",
                "agent_name": "架构师",
                "target_field": "open_questions",
                "operation": "add",
                "value": "是否需要先补压测基线",
                "status": "pending",
            }
        ],
        structured_state={
            "open_questions": ["下一轮先补充压测基线是否充分"],
        },
        round_no=3,
    )
    assert remaining == []
    assert patch_log[-1]["decision"] == "accepted_by_moderator"


def test_execute_purges_retrieval_chunks_after_terminal_run(monkeypatch) -> None:
    engine = _engine()

    class _DummyGraph:
        async def ainvoke(self, payload, config):
            return {"status": "ok"}

    purged: list[str] = []

    async def _always_terminal(run_id: str) -> bool:
        return True

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(engine, "_graph", _DummyGraph())
    monkeypatch.setattr(engine, "_is_terminal_run", _always_terminal)
    monkeypatch.setattr(engine, "clear_persisted_control_state", _noop)
    monkeypatch.setattr("app.runtime_langgraph.prepare_run_workspace_async", _noop)
    monkeypatch.setattr("app.runtime_langgraph.cleanup_run_workspace_async", _noop)
    monkeypatch.setattr("app.runtime_langgraph.purge_run_chunks", lambda run_id: purged.append(run_id))

    asyncio.run(engine.execute("run-cleanup", command={"resume": {"source": "test"}}))
    assert purged == ["run-cleanup"]
