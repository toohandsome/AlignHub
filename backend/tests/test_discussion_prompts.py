from __future__ import annotations

from app.services.discussion_prompts import build_agent_turn_prompt, estimate_message_saliency, format_discussion_context


def test_full_history_is_preserved_when_budget_is_enough() -> None:
    history = [
        {"round_no": 1, "agent_name": "架构师", "text": "建议优先明确约束条件。"},
        {"round_no": 1, "agent_name": "产品经理", "text": "需要同时比较交付成本和风险。"},
    ]
    context = format_discussion_context(
        history,
        round_summaries=[],
        structured_state={"topic": "讨论交付策略", "rounds_completed": 1},
        prompt_token_budget=5000,
        recent_full_message_count=4,
        retrieval_item_limit=4,
    )
    assert "完整历史原文" in context
    assert "建议优先明确约束条件" in context
    assert "需要同时比较交付成本和风险" in context


def test_layered_context_uses_recent_raw_and_old_history_retrieval_without_truncation_marker() -> None:
    history = [
        {"round_no": 1, "agent_name": "架构师", "text": "建议优先采用模块化发布方案，并先补齐回滚链路。"},
        {"round_no": 1, "agent_name": "产品经理", "text": "需要同时评估交付成本和时间窗口。"},
        {"round_no": 2, "agent_name": "测试", "text": "当前最大的风险是压测样本不足，证据不够。"},
        {"round_no": 2, "agent_name": "开发", "text": "可以先做小流量灰度验证。"},
        {"round_no": 3, "agent_name": "运维", "text": "回滚脚本还没有完成演练。"},
        {"round_no": 3, "agent_name": "架构师", "text": "建议下一轮重点补充压测基线和回滚演练证据。"},
    ]
    round_summaries = [
        {
            "round_no": 1,
            "summary_text": "首轮讨论确认了模块化方向，但仍需补充成本评估。",
            "agreements": ["优先采用模块化思路"],
            "open_questions": ["成本是否可接受"],
            "candidate_options": ["方案A"],
            "risks": ["交付时间紧张"],
        },
        {
            "round_no": 2,
            "summary_text": "第二轮聚焦压测与灰度验证，但仍缺证据。",
            "agreements": ["需要先补验证证据"],
            "open_questions": ["压测基线是否充分"],
            "candidate_options": ["方案B"],
            "risks": ["压测样本不足"],
        },
    ]
    structured_state = {
        "topic": "讨论发布方案",
        "rounds_completed": 2,
        "latest_decision": "continue",
        "latest_decision_reason": "尚未形成稳定结论，缺少验证证据。",
        "next_focus": "补充压测基线与回滚演练",
        "agreements": ["需要继续补证据"],
        "open_questions": ["压测是否充分"],
        "candidate_options": ["方案A", "方案B"],
        "risks": ["回滚演练不足"],
        "recent_key_points": ["优先补验证", "继续灰度评估"],
    }
    context = format_discussion_context(
        history,
        round_summaries=round_summaries,
        structured_state=structured_state,
        prompt_token_budget=260,
        recent_full_message_count=2,
        retrieval_item_limit=3,
    )
    assert "最近原文" in context
    assert "讨论发布方案" in context
    assert "Round 3" in context
    assert "较老历史召回" in context
    assert "[truncated]" not in context


def test_agent_prompt_includes_private_working_memory_and_disclosure_rule() -> None:
    prompt = build_agent_turn_prompt(
        topic="讨论缓存一致性策略",
        round_no=2,
        max_rounds=4,
        agent_name="架构师",
        history=[
            {"round_no": 1, "agent_name": "产品经理", "text": "请补充工具验证结果，并比较性能风险。"},
        ],
        round_summaries=[],
        structured_state={
            "topic": "讨论缓存一致性策略",
            "rounds_completed": 1,
            "latest_decision": "continue",
            "next_focus": "补充性能风险与验证路径",
        },
        private_working_memory={
            "draft_notes": ["先回应产品经理，再说明推荐方案。"],
            "current_focus": ["优先关注：补充性能风险与验证路径"],
            "analysis_preferences": ["角色视角：偏好模块化与可审计方案"],
            "tool_result_cache": [
                {"tool_name": "read_file", "status": "completed", "summary": "已读取缓存设计文档。", "round_no": 2}
            ],
        },
        prompt_token_budget=2400,
        recent_full_message_count=4,
        retrieval_item_limit=4,
    )
    assert "私有工作记忆" in prompt
    assert "工具结果缓存" in prompt
    assert "read_file" in prompt
    assert "只有公开表达后" in prompt
    assert "[STATE PATCH PROPOSAL]" in prompt
    assert "optional" in prompt.lower()
    assert "significant state change" in prompt.lower()


def test_layered_context_prefers_salient_older_message_over_trivial_recent_chatter() -> None:
    history = [
        {"round_no": 1, "agent_name": "架构师", "text": "建议采用双写校验方案，并补充压测基线，当前最大风险是回滚链路不完整。"},
        {"round_no": 2, "agent_name": "产品经理", "text": "收到"},
        {"round_no": 2, "agent_name": "测试", "text": "同意"},
        {"round_no": 3, "agent_name": "开发", "text": "好的"},
        {"round_no": 3, "agent_name": "运维", "text": "收到"},
    ]
    context = format_discussion_context(
        history,
        round_summaries=[],
        structured_state={"topic": "讨论发布方案", "rounds_completed": 3, "next_focus": "补充压测基线"},
        prompt_token_budget=360,
        recent_full_message_count=2,
        retrieval_item_limit=1,
    )
    assert "双写校验方案" in context


def test_saliency_scoring_applies_density_penalty_to_verbose_low_signal_message() -> None:
    concise_score, _ = estimate_message_saliency({"text": "建议采用方案A，并补充压测基线。"})
    verbose_score, _ = estimate_message_saliency(
        {"text": "建议" + "这是一些铺垫描述。" * 80}
    )
    assert concise_score > verbose_score


def test_saliency_density_penalty_whitelist_protects_code_blocks() -> None:
    verbose_score, _ = estimate_message_saliency({"text": "建议" + "这是一些铺垫描述。" * 80})
    code_like_score, _ = estimate_message_saliency(
        {
            "text": """建议补充真实实现细节：
```python
def rollback():
    for step in steps:
        if step.failed:
            return {"status": "abort", "reason": "rollback_incomplete"}
    return {"status": "ok", "checks": ["db", "cache", "queue"]}
```
"""
        }
    )
    assert code_like_score > verbose_score


def test_saliency_density_penalty_whitelist_protects_long_json_payload() -> None:
    verbose_score, _ = estimate_message_saliency({"text": "这里有很多背景描述，但几乎没有新增信息。" * 70})
    json_like_score, _ = estimate_message_saliency(
        {
            "text": """{
  "service": "alignhub-worker",
  "module": "discussion_runtime",
  "error_code": "CTX_TRUNCATION_FALSE_POSITIVE",
  "path": "backend/app/runtime_langgraph.py",
  "candidate_fix": {
    "strategy": "full_history_first",
    "fallbacks": ["recent_raw_messages", "round_summaries", "structured_state"]
  },
  "evidence": ["token_budget_hit", "recent_messages_intact", "moderator_summary_missing"]
}"""
        }
    )
    assert json_like_score > verbose_score


def test_archived_state_memory_can_be_retrieved_when_relevant() -> None:
    history = [
        {"round_no": 1, "agent_name": "产品经理", "text": "收到，我们先记一下回滚链路这个点。"},
        {"round_no": 2, "agent_name": "开发", "text": "同意，但当前没有更多新增信息。"},
        {"round_no": 3, "agent_name": "测试", "text": "好的，后续继续围绕回滚链路讨论。"},
        {"round_no": 4, "agent_name": "架构师", "text": "请继续围绕回滚链路讨论，并确认是否存在未覆盖回滚场景。"},
    ]
    structured_state = {
        "topic": "讨论发布策略",
        "rounds_completed": 4,
        "next_focus": "回滚链路",
        "agreement_items": [],
        "open_question_items": [],
        "candidate_option_items": [],
        "risk_items": [
            {
                "value": "回滚链路不完整",
                "status": "archived",
                "created_round": 1,
                "last_seen_round": 1,
                "importance": 0.7,
                "support_count": 1,
                "source": "moderator",
            }
        ],
        "risks": [],
    }
    context = format_discussion_context(
        history,
        round_summaries=[],
        structured_state=structured_state,
        prompt_token_budget=150,
        recent_full_message_count=1,
        retrieval_item_limit=2,
    )
    assert "回滚链路不完整" in context
    assert "[ARCHIVED CONTEXT - FOR REFERENCE ONLY]" in context


def test_prompt_context_excludes_runtime_diagnostics_from_structured_state() -> None:
    context = format_discussion_context(
        [{"round_no": 1, "agent_name": "架构师", "text": "请继续聚焦回滚链路完整性。"}],
        round_summaries=[],
        structured_state={
            "topic": "讨论发布策略",
            "rounds_completed": 1,
            "next_focus": "回滚链路完整性",
            "patch_metrics": {"moderator_adoption_rate": 0.25},
            "unresolved_conflict_details": [{"summary": "冲突详情"}],
            "unresolved_conflicts": ["回滚方案仍有冲突"],
        },
        prompt_token_budget=500,
        recent_full_message_count=2,
        retrieval_item_limit=2,
    )
    assert "patch_metrics" not in context
    assert "unresolved_conflict_details" not in context
    assert "回滚方案仍有冲突" in context
