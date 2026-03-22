from __future__ import annotations

import math
import sqlite3

from app.core import settings
from app.services.context_retrieval import (
    _merge_ranked_hits,
    build_hashed_embedding,
    inspect_retrieval_runtime,
    log_retrieval_runtime_status,
    purge_run_chunks,
)
from app.services.discussion_prompts import format_discussion_context


def test_hybrid_retrieval_uses_sqlite_sidecar_for_older_memories(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "discussion_retrieval.sqlite"
    monkeypatch.setattr(settings, "discussion_retrieval_sqlite_path", str(db_path))
    monkeypatch.setattr(settings, "discussion_hybrid_retrieval_enabled", True)
    monkeypatch.setattr(settings, "discussion_vector_search_enabled", False)

    history = [
        {
            "message_id": "m1",
            "round_no": 1,
            "agent_name": "Architect",
            "text": "We still lack rollback rehearsal evidence and pressure-test baseline for the release plan.",
        },
        {"message_id": "m2", "round_no": 2, "agent_name": "PM", "text": "ack"},
        {"message_id": "m3", "round_no": 3, "agent_name": "Ops", "text": "copy"},
        {
            "message_id": "m4",
            "round_no": 4,
            "agent_name": "Developer",
            "text": "Please keep focusing on rollback rehearsal evidence before we close this discussion.",
        },
    ]
    context = format_discussion_context(
        history,
        run_id="run-hybrid-1",
        round_summaries=[],
        structured_state={
            "topic": "Release readiness",
            "rounds_completed": 4,
            "next_focus": "rollback rehearsal evidence",
            "agreements": [],
            "open_questions": ["Do we have enough rollback evidence?"],
            "candidate_options": [],
            "risks": ["Rollback chain may still be incomplete"],
            "recent_key_points": ["Need more evidence before final sign-off"],
        },
        prompt_token_budget=220,
        recent_full_message_count=1,
        retrieval_item_limit=2,
    )

    assert "较老历史召回" in context
    assert "rollback rehearsal evidence and pressure-test baseline" in context
    assert db_path.exists()


def test_hybrid_retrieval_sidecar_can_be_purged(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "discussion_retrieval.sqlite"
    monkeypatch.setattr(settings, "discussion_retrieval_sqlite_path", str(db_path))
    monkeypatch.setattr(settings, "discussion_hybrid_retrieval_enabled", True)
    monkeypatch.setattr(settings, "discussion_vector_search_enabled", False)

    format_discussion_context(
        [
            {"message_id": "m1", "round_no": 1, "agent_name": "Architect", "text": "Rollback evidence is missing."},
            {"message_id": "m2", "round_no": 2, "agent_name": "Developer", "text": "We need another rehearsal."},
            {"message_id": "m3", "round_no": 3, "agent_name": "PM", "text": "ack"},
            {"message_id": "m4", "round_no": 4, "agent_name": "Ops", "text": "Please keep checking rollback evidence."},
        ],
        run_id="run-hybrid-purge",
        round_summaries=[],
        structured_state={"topic": "Release readiness", "rounds_completed": 2, "next_focus": "rollback evidence"},
        prompt_token_budget=120,
        recent_full_message_count=1,
        retrieval_item_limit=1,
    )

    with sqlite3.connect(db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM memory_chunks WHERE run_id = ?", ("run-hybrid-purge",)).fetchone()[0]
    assert before > 0

    purge_run_chunks("run-hybrid-purge")

    with sqlite3.connect(db_path) as conn:
        after = conn.execute("SELECT COUNT(*) FROM memory_chunks WHERE run_id = ?", ("run-hybrid-purge",)).fetchone()[0]
    assert after == 0


def test_hashed_embedding_is_normalized() -> None:
    vector = build_hashed_embedding("rollback rehearsal evidence risk baseline", dimensions=32)
    norm = math.sqrt(sum(value * value for value in vector))
    assert len(vector) == 32
    assert 0.99 <= norm <= 1.01


def test_hashed_embedding_changes_when_entity_and_anchor_terms_are_boosted() -> None:
    base = build_hashed_embedding("cache module fallback", dimensions=32)
    boosted = build_hashed_embedding(
        "cache module fallback",
        dimensions=32,
        entity_terms=["ERR_CACHE_409"],
        anchor_terms=["发布策略", "需要补齐回滚证据"],
    )
    assert base != boosted


def test_runtime_probe_logs_vector_off_when_disabled(tmp_path, monkeypatch, caplog) -> None:
    db_path = tmp_path / "discussion_retrieval.sqlite"
    monkeypatch.setattr(settings, "discussion_retrieval_sqlite_path", str(db_path))
    monkeypatch.setattr(settings, "discussion_hybrid_retrieval_enabled", True)
    monkeypatch.setattr(settings, "discussion_vector_search_enabled", False)

    status = inspect_retrieval_runtime()
    assert status["hybrid_enabled"] is True
    assert status["vector_requested"] is False
    assert status["fts_available"] is True
    assert status["vector_available"] is False

    with caplog.at_level("INFO"):
        log_retrieval_runtime_status()
    assert "vector=off" in caplog.text
    assert "mode=fts_only" in caplog.text


def test_rrf_prefers_lexical_hits_for_exact_module_like_terms() -> None:
    ranked = _merge_ranked_hits(
        query_text="ERR_CACHE_409 alignhub/cache.py",
        query_terms=["err_cache_409", "alignhub", "cache", "py"],
        lexical_hits=[
            {
                "chunk_key": "lexical",
                "lexical_rank": 1,
                "saliency_score": 0.2,
                "round_no": 3,
                "ordinal": 3,
                "source_type": "message",
                "is_archived": False,
            }
        ],
        vector_hits=[
            {
                "chunk_key": "vector",
                "vector_rank": 1,
                "saliency_score": 0.2,
                "round_no": 3,
                "ordinal": 3,
                "source_type": "message",
                "is_archived": False,
            }
        ],
        limit=2,
    )
    assert ranked[0]["chunk_key"] == "lexical"
