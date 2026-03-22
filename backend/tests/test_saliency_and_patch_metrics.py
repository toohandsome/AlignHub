from __future__ import annotations

from app.runtime_langgraph import _annotate_patch_log_metrics, _moderator_patch_metrics
from app.services.discussion_prompts import estimate_message_saliency


def test_saliency_prioritizes_questions_early_and_decisions_late() -> None:
    early_question, _ = estimate_message_saliency(
        {"text": "请问是否还缺少关键证据？", "round_no": 1, "max_rounds": 10}
    )
    late_question, _ = estimate_message_saliency(
        {"text": "请问是否还缺少关键证据？", "round_no": 10, "max_rounds": 10}
    )
    early_decision, _ = estimate_message_saliency(
        {"text": "结论：方案已经收敛，可以形成共识。", "round_no": 1, "max_rounds": 10}
    )
    late_decision, _ = estimate_message_saliency(
        {"text": "结论：方案已经收敛，可以形成共识。", "round_no": 10, "max_rounds": 10}
    )

    assert early_question > late_question
    assert late_decision > early_decision


def test_patch_log_tracks_moderator_adoption_rate_by_agent_and_field() -> None:
    patch_log = _annotate_patch_log_metrics(
        [
            {
                "patch_id": "p1",
                "decision": "accepted_by_moderator",
                "decided_by": "moderator",
                "round_no": 3,
                "proposal_agent_id": "agent-a",
                "proposal_agent_name": "架构师",
                "target_field": "agreements",
                "operation": "add",
                "value": "先补齐压测基线",
            },
            {
                "patch_id": "p2",
                "decision": "rejected_by_moderator",
                "decided_by": "moderator",
                "round_no": 3,
                "proposal_agent_id": "agent-b",
                "proposal_agent_name": "产品经理",
                "target_field": "risks",
                "operation": "add",
                "value": "当前方案完全不可行",
            },
        ]
    )
    metrics = _moderator_patch_metrics(patch_log)

    assert metrics["moderator_adoption_rate"] == 0.5
    assert patch_log[-1]["moderator_adoption_rate"] == 0.5
    assert patch_log[0]["moderator_adoption_rate_by_agent"] == 1.0
    assert patch_log[1]["moderator_adoption_rate_by_agent"] == 0.0
    assert patch_log[0]["moderator_adoption_rate_by_field"] == 1.0
    assert patch_log[1]["moderator_adoption_rate_by_field"] == 0.0
