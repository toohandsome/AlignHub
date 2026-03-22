from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import zlib
from pathlib import Path
from typing import Any

from app.core import settings

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    import sqlite_vec
except Exception:  # pragma: no cover - optional dependency
    sqlite_vec = None


_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False
_SCHEMA_READY_PATH: str | None = None
_VEC_EXTENSION_READY: bool | None = None

_SEMANTIC_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "风险": ("隐患", "问题", "代价", "瓶颈", "risk", "hazard"),
    "隐患": ("风险", "问题", "代价"),
    "问题": ("风险", "隐患", "分歧", "question"),
    "证据": ("数据", "日志", "实验", "压测", "benchmark", "指标"),
    "数据": ("证据", "指标", "日志"),
    "日志": ("证据", "数据", "观测"),
    "结论": ("决定", "共识", "最终", "decision"),
    "共识": ("结论", "决定", "收敛"),
    "方案": ("提议", "路径", "option", "proposal"),
    "提议": ("方案", "建议", "option"),
    "建议": ("方案", "提议", "推荐"),
    "回滚": ("兜底", "恢复", "fallback"),
    "压测": ("benchmark", "性能", "基线", "实验"),
    "性能": ("压测", "延迟", "吞吐", "benchmark"),
}


def _db_path() -> Path:
    return Path(settings.discussion_retrieval_sqlite_path).resolve()


def _vector_enabled() -> bool:
    return bool(settings.discussion_hybrid_retrieval_enabled and settings.discussion_vector_search_enabled)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _load_vec_extension(conn: sqlite3.Connection) -> bool:
    global _VEC_EXTENSION_READY
    if not _vector_enabled():
        _VEC_EXTENSION_READY = False
        return False
    if _VEC_EXTENSION_READY is False:
        return False
    if sqlite_vec is None:
        _VEC_EXTENSION_READY = False
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _VEC_EXTENSION_READY = True
        return True
    except Exception as exc:  # pragma: no cover - depends on local sqlite build
        logger.warning("sqlite-vec unavailable, falling back to FTS/lexical retrieval: %s", exc)
        try:
            conn.enable_load_extension(False)
        except Exception:
            pass
        _VEC_EXTENSION_READY = False
        return False


def _ensure_schema(conn: sqlite3.Connection) -> bool:
    """确保检索侧车库中的表、FTS 索引和向量表已就绪。

    返回值表示当前连接是否真的可用 sqlite-vec。
    """
    global _SCHEMA_READY, _SCHEMA_READY_PATH
    with _SCHEMA_LOCK:
        vector_ready = _load_vec_extension(conn)
        current_path = str(_db_path())
        if _SCHEMA_READY and _SCHEMA_READY_PATH == current_path:
            if vector_ready:
                conn.execute(
                    f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_vec
                    USING vec0(embedding float[{int(settings.discussion_vector_dimensions)}])
                    """
                )
                conn.commit()
            return vector_ready

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                chunk_key TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                round_no INTEGER DEFAULT 0,
                agent_id TEXT,
                saliency_score REAL DEFAULT 0,
                is_archived INTEGER DEFAULT 0,
                ordinal INTEGER DEFAULT 0,
                text TEXT NOT NULL,
                lexical_text TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS ix_memory_chunks_run_id ON memory_chunks(run_id);
            CREATE INDEX IF NOT EXISTS ix_memory_chunks_run_source ON memory_chunks(run_id, source_type, round_no);

            CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts
            USING fts5(
                chunk_key UNINDEXED,
                run_id UNINDEXED,
                lexical_text
            );
            """
        )
        if vector_ready:
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_vec
                USING vec0(embedding float[{int(settings.discussion_vector_dimensions)}])
                """
        )
        conn.commit()
        _SCHEMA_READY = True
        _SCHEMA_READY_PATH = current_path
        return vector_ready


def _expand_tokens(tokens: list[str]) -> list[tuple[str, float]]:
    expanded: list[tuple[str, float]] = []
    for token in tokens:
        expanded.append((token, 1.0))
        for related in _SEMANTIC_EXPANSIONS.get(token, ()):
            expanded.append((related, 0.35))
    return expanded


def build_hashed_embedding(
    lexical_text: str,
    *,
    dimensions: int | None = None,
    entity_terms: list[str] | None = None,
    anchor_terms: list[str] | None = None,
) -> list[float]:
    """把文本映射成轻量哈希向量。

    这里不依赖外部 embedding 模型，而是用稳定的哈希投影在本地生成可比较的向量。
    """
    dims = max(16, int(dimensions or settings.discussion_vector_dimensions))
    tokens = [token.strip() for token in (lexical_text or "").split() if token.strip()]
    if not tokens and not entity_terms and not anchor_terms:
        return []

    vector = [0.0] * dims
    for token, weight in _expand_tokens(tokens):
        digest = zlib.crc32(token.encode("utf-8"))
        index = digest % dims
        sign = -1.0 if (digest >> 8) & 1 else 1.0
        vector[index] += sign * weight
    for token in entity_terms or []:
        normalized = token.strip()
        if not normalized:
            continue
        digest = zlib.crc32(normalized.encode("utf-8"))
        index = digest % dims
        sign = -1.0 if (digest >> 8) & 1 else 1.0
        vector[index] += sign * 1.8
    for token in anchor_terms or []:
        normalized = token.strip()
        if not normalized:
            continue
        digest = zlib.crc32(normalized.encode("utf-8"))
        index = digest % dims
        sign = -1.0 if (digest >> 8) & 1 else 1.0
        vector[index] += sign * 0.85

    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return []
    return [round(value / norm, 6) for value in vector]


def hybrid_search_chunks(
    *,
    run_id: str,
    chunks: list[dict[str, Any]],
    query_text: str,
    query_terms: list[str],
    vector_anchor_terms: list[str] | None,
    excluded_chunk_keys: set[str],
    item_limit: int,
) -> list[dict[str, Any]]:
    """执行混合检索。

    流程为：刷新当前 Run 的检索分块 -> FTS 召回 -> 向量召回 -> 融合排序。
    """
    if not settings.discussion_hybrid_retrieval_enabled or not run_id or not chunks:
        return []

    try:
        with _connect() as conn:
            vector_ready = _ensure_schema(conn)
            _replace_run_chunks(conn, run_id=run_id, chunks=chunks, vector_ready=vector_ready)
            lexical_hits = _search_fts(
                conn,
                run_id=run_id,
                query_terms=query_terms,
                excluded_chunk_keys=excluded_chunk_keys,
                limit=max(item_limit * 3, settings.discussion_retrieval_fts_limit),
            )
            vector_hits = (
                _search_vector(
                    conn,
                    run_id=run_id,
                    query_lexical_text=" ".join(query_terms) if query_terms else query_text,
                    query_anchor_terms=vector_anchor_terms or [],
                    excluded_chunk_keys=excluded_chunk_keys,
                    limit=max(item_limit * 3, settings.discussion_retrieval_vector_limit),
                )
                if vector_ready
                else []
            )
            return _merge_ranked_hits(
                query_text=query_text,
                query_terms=query_terms,
                lexical_hits=lexical_hits,
                vector_hits=vector_hits,
                limit=item_limit,
            )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Hybrid retrieval failed, falling back to in-memory lexical search: %s", exc)
        return []


def purge_run_chunks(run_id: str) -> None:
    if not run_id:
        return
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            row_ids = [row[0] for row in conn.execute("SELECT id FROM memory_chunks WHERE run_id = ?", (run_id,)).fetchall()]
            chunk_keys = [row[0] for row in conn.execute("SELECT chunk_key FROM memory_chunks WHERE run_id = ?", (run_id,)).fetchall()]
            if row_ids and _VEC_EXTENSION_READY:
                placeholders = ",".join("?" for _ in row_ids)
                conn.execute(f"DELETE FROM memory_chunks_vec WHERE rowid IN ({placeholders})", row_ids)
            if chunk_keys:
                placeholders = ",".join("?" for _ in chunk_keys)
                conn.execute(f"DELETE FROM memory_chunks_fts WHERE chunk_key IN ({placeholders})", chunk_keys)
            conn.execute("DELETE FROM memory_chunks WHERE run_id = ?", (run_id,))
            conn.commit()
    except Exception as exc:  # pragma: no cover - best effort cleanup
        logger.warning("Failed to purge retrieval chunks for run %s: %s", run_id, exc)


def inspect_retrieval_runtime() -> dict[str, Any]:
    """探测当前进程下检索能力的真实运行态，供启动日志和诊断接口复用。"""
    status: dict[str, Any] = {
        "hybrid_enabled": bool(settings.discussion_hybrid_retrieval_enabled),
        "vector_requested": bool(settings.discussion_vector_search_enabled),
        "sqlite_path": str(_db_path()),
        "sqlite_version": sqlite3.sqlite_version,
        "vector_dimensions": int(settings.discussion_vector_dimensions),
        "sqlite_vec_installed": sqlite_vec is not None,
        "python_supports_load_extension": False,
        "fts_available": False,
        "vector_available": False,
        "vec_version": None,
        "mode": "lexical_only",
        "reason": "",
    }

    probe_conn = sqlite3.connect(":memory:")
    try:
        status["python_supports_load_extension"] = hasattr(probe_conn, "enable_load_extension")
    finally:
        probe_conn.close()

    if not status["hybrid_enabled"]:
        status["reason"] = "hybrid retrieval disabled by config"
        return status

    if not status["vector_requested"]:
        status["reason"] = "vector search disabled by config"

    try:
        with _connect() as conn:
            vector_ready = _ensure_schema(conn)
            fts_row = conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'memory_chunks_fts' LIMIT 1"
            ).fetchone()
            status["fts_available"] = bool(fts_row)
            status["vector_available"] = bool(vector_ready)
            if vector_ready:
                vec_row = conn.execute("SELECT vec_version()").fetchone()
                status["vec_version"] = vec_row[0] if vec_row else None
            if status["fts_available"] and status["vector_available"]:
                status["mode"] = "hybrid_fts_vector"
                status["reason"] = "fts + sqlite-vec enabled"
            elif status["fts_available"]:
                status["mode"] = "fts_only"
                if not status["reason"]:
                    status["reason"] = "sqlite-vec unavailable, using fts + lexical fallback"
            else:
                status["mode"] = "lexical_only"
                status["reason"] = status["reason"] or "sqlite sidecar schema unavailable"
    except Exception as exc:  # pragma: no cover - defensive logging
        status["mode"] = "lexical_only"
        status["reason"] = f"runtime probe failed: {exc}"
    return status


def log_retrieval_runtime_status(target_logger: logging.Logger | None = None) -> dict[str, Any]:
    runtime_logger = target_logger or logger
    status = inspect_retrieval_runtime()
    runtime_logger.info(
        "Discussion retrieval runtime: mode=%s fts=%s vector=%s vec_version=%s hybrid_enabled=%s vector_requested=%s sqlite=%s path=%s dims=%s reason=%s",
        status["mode"],
        "on" if status["fts_available"] else "off",
        "on" if status["vector_available"] else "off",
        status["vec_version"] or "-",
        status["hybrid_enabled"],
        status["vector_requested"],
        status["sqlite_version"],
        status["sqlite_path"],
        status["vector_dimensions"],
        status["reason"] or "-",
    )
    return status


def _replace_run_chunks(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    chunks: list[dict[str, Any]],
    vector_ready: bool,
) -> None:
    """用最新的 chunks 完整替换某个 Run 的检索索引。

    该实现选择整批替换而不是增量更新，以降低状态漂移和脏数据残留风险。
    """
    existing = conn.execute("SELECT id, chunk_key FROM memory_chunks WHERE run_id = ?", (run_id,)).fetchall()
    if existing:
        row_ids = [int(row["id"]) for row in existing]
        chunk_keys = [str(row["chunk_key"]) for row in existing]
        if row_ids and vector_ready:
            placeholders = ",".join("?" for _ in row_ids)
            conn.execute(f"DELETE FROM memory_chunks_vec WHERE rowid IN ({placeholders})", row_ids)
        if chunk_keys:
            placeholders = ",".join("?" for _ in chunk_keys)
            conn.execute(f"DELETE FROM memory_chunks_fts WHERE chunk_key IN ({placeholders})", chunk_keys)
        conn.execute("DELETE FROM memory_chunks WHERE run_id = ?", (run_id,))

    for ordinal, chunk in enumerate(chunks, start=1):
        lexical_text = str(chunk.get("lexical_text") or "").strip()
        text = str(chunk.get("text") or "").strip()
        if not lexical_text or not text:
            continue
        cursor = conn.execute(
            """
            INSERT INTO memory_chunks(
                run_id, chunk_key, source_type, source_ref, round_no, agent_id,
                saliency_score, is_archived, ordinal, text, lexical_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                str(chunk.get("chunk_key") or f"{run_id}:{ordinal}"),
                str(chunk.get("source_type") or "memory"),
                str(chunk.get("source_ref") or ordinal),
                int(chunk.get("round_no") or 0),
                str(chunk.get("agent_id") or "") or None,
                float(chunk.get("saliency_score") or 0.0),
                1 if chunk.get("is_archived") else 0,
                int(chunk.get("ordinal") or ordinal),
                text,
                lexical_text,
            ),
        )
        row_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO memory_chunks_fts(chunk_key, run_id, lexical_text) VALUES (?, ?, ?)",
            (str(chunk.get("chunk_key") or f"{run_id}:{ordinal}"), run_id, lexical_text),
        )
        if vector_ready:
            embedding = build_hashed_embedding(
                str(chunk.get("embedding_text") or lexical_text),
                entity_terms=list(chunk.get("entity_terms") or []),
                anchor_terms=list(chunk.get("anchor_terms") or []),
            )
            if embedding:
                conn.execute(
                    "INSERT INTO memory_chunks_vec(rowid, embedding) VALUES (?, ?)",
                    (row_id, json.dumps(embedding, ensure_ascii=False)),
                )
    conn.commit()


def _search_fts(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    query_terms: list[str],
    excluded_chunk_keys: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    terms = _normalize_query_terms(query_terms)
    if not terms:
        return []
    match_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
    rows = conn.execute(
        """
        SELECT
            m.id,
            m.chunk_key,
            m.source_type,
            m.source_ref,
            m.round_no,
            m.agent_id,
            m.saliency_score,
            m.is_archived,
            m.ordinal,
            m.text,
            bm25(memory_chunks_fts) AS lexical_rank
        FROM memory_chunks_fts
        JOIN memory_chunks m ON m.chunk_key = memory_chunks_fts.chunk_key
        WHERE memory_chunks_fts MATCH ?
          AND m.run_id = ?
        ORDER BY lexical_rank ASC, m.round_no DESC, m.ordinal DESC
        LIMIT ?
        """,
        (match_query, run_id, max(1, limit)),
    ).fetchall()
    return [_row_to_dict(row, rank=index + 1, score_key="lexical_rank") for index, row in enumerate(rows) if row["chunk_key"] not in excluded_chunk_keys]


def _search_vector(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    query_lexical_text: str,
    query_anchor_terms: list[str],
    excluded_chunk_keys: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    embedding = build_hashed_embedding(query_lexical_text, anchor_terms=query_anchor_terms)
    if not embedding:
        return []
    vector_rows = conn.execute(
        """
        SELECT rowid, distance
        FROM memory_chunks_vec
        WHERE embedding MATCH ?
        ORDER BY distance ASC
        LIMIT ?
        """,
        (json.dumps(embedding, ensure_ascii=False), max(1, limit * 3)),
    ).fetchall()
    if not vector_rows:
        return []
    ids = [int(row["rowid"]) for row in vector_rows]
    placeholders = ",".join("?" for _ in ids)
    metadata_rows = conn.execute(
        f"""
        SELECT id, chunk_key, source_type, source_ref, round_no, agent_id, saliency_score, is_archived, ordinal, text
        FROM memory_chunks
        WHERE run_id = ?
          AND id IN ({placeholders})
        """,
        (run_id, *ids),
    ).fetchall()
    metadata = {int(row["id"]): row for row in metadata_rows}
    result: list[dict[str, Any]] = []
    rank = 0
    for row in vector_rows:
        meta = metadata.get(int(row["rowid"]))
        if not meta or meta["chunk_key"] in excluded_chunk_keys:
            continue
        rank += 1
        result.append(
            {
                "id": int(meta["id"]),
                "chunk_key": str(meta["chunk_key"]),
                "source_type": str(meta["source_type"]),
                "source_ref": str(meta["source_ref"]),
                "round_no": int(meta["round_no"] or 0),
                "agent_id": str(meta["agent_id"] or "") or None,
                "saliency_score": float(meta["saliency_score"] or 0.0),
                "is_archived": bool(meta["is_archived"]),
                "ordinal": int(meta["ordinal"] or 0),
                "text": str(meta["text"]),
                "vector_distance": float(row["distance"]),
                "vector_rank": rank,
            }
        )
        if len(result) >= limit:
            break
    return result


def _lexical_priority_boost(query_text: str, query_terms: list[str]) -> float:
    boost = 0.0
    raw = query_text or ""
    if re.search(r"[A-Z]{2,}", raw):
        boost += 0.12
    if re.search(r"[A-Za-z]+[_./:\\-][A-Za-z0-9_./:\\-]+", raw):
        boost += 0.16
    if re.search(r"[A-Za-z]*\d+[A-Za-z\d_]*", raw):
        boost += 0.14
    if any("_" in term or any(ch.isdigit() for ch in term) for term in query_terms):
        boost += 0.12
    return min(boost, 0.35)


def _merge_ranked_hits(
    *,
    query_text: str,
    query_terms: list[str],
    lexical_hits: list[dict[str, Any]],
    vector_hits: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """融合 FTS 与向量检索结果。

    当前策略显式偏向 lexical 命中，再叠加 saliency、轮次新近性等信号。
    """
    merged: dict[str, dict[str, Any]] = {}
    lexical_weight = 1.9 + _lexical_priority_boost(query_text, query_terms)
    vector_weight = 1.05
    for hit in lexical_hits:
        item = merged.setdefault(hit["chunk_key"], dict(hit))
        item["fusion_score"] = item.get("fusion_score", 0.0) + lexical_weight / (hit.get("lexical_rank", 1) + 0.2)
    for hit in vector_hits:
        item = merged.setdefault(hit["chunk_key"], dict(hit))
        item["fusion_score"] = item.get("fusion_score", 0.0) + vector_weight / (hit.get("vector_rank", 1) + 0.2)
        if "vector_distance" in hit and "vector_distance" not in item:
            item["vector_distance"] = hit["vector_distance"]
            item["vector_rank"] = hit["vector_rank"]

    ranked = []
    for item in merged.values():
        score = float(item.get("fusion_score") or 0.0)
        score += min(float(item.get("saliency_score") or 0.0), 2.5) * 0.12
        score += min(int(item.get("round_no") or 0), 50) * 0.015
        if item.get("source_type") == "round_summary":
            score += 0.12
        if item.get("source_type") == "archived_state" or item.get("is_archived"):
            score -= 0.08
        item["fusion_score"] = score
        ranked.append(item)

    ranked.sort(
        key=lambda item: (
            float(item.get("fusion_score") or 0.0),
            float(item.get("saliency_score") or 0.0),
            int(item.get("round_no") or 0),
            int(item.get("ordinal") or 0),
        ),
        reverse=True,
    )
    return ranked[: max(1, limit)]


def _normalize_query_terms(query_terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in sorted((term.strip() for term in query_terms if term and term.strip()), key=lambda item: (len(item), item), reverse=True):
        if term in seen:
            continue
        seen.add(term)
        result.append(term)
        if len(result) >= 16:
            break
    return result


def _row_to_dict(row: sqlite3.Row, *, rank: int, score_key: str) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "chunk_key": str(row["chunk_key"]),
        "source_type": str(row["source_type"]),
        "source_ref": str(row["source_ref"]),
        "round_no": int(row["round_no"] or 0),
        "agent_id": str(row["agent_id"] or "") or None,
        "saliency_score": float(row["saliency_score"] or 0.0),
        "is_archived": bool(row["is_archived"]),
        "ordinal": int(row["ordinal"] or 0),
        "text": str(row["text"]),
        score_key: float(row[score_key]) if row[score_key] is not None else 0.0,
        "lexical_rank": rank if score_key == "lexical_rank" else None,
    }
