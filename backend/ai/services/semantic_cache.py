"""Local Semantic QA Cache backed by PostgreSQL + local embedding provider.

Eliminates redundant LLM token spend when operators ask identical or near-
identical knowledge / general network questions:
- Tier 1: O(1) normalized query SHA-256 exact match
- Tier 2: Cosine similarity >= threshold (default 0.94) using Nexora's active
  local semantic embedding provider (no external token spend).
- Safety & freshness guards:
  * Only caches clean ``knowledge`` / ``general_qa`` answers (never CMDB,
    per-device, sensitive/tokenized, or live web-search answers).
  * Automatically binds entries to ``kb_version`` (latest knowledge document
    timestamp) and expires entries after TTL (default 24h).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.config import settings
from database.core import get_db_connection

logger = logging.getLogger(__name__)

_TABLE_READY = False
_CACHEABLE_INTENTS = frozenset({"knowledge", "general_qa"})
_IP_OR_MAC_RE = re.compile(
    r"(?:\b(?:\d{1,3}\.){3}\d{1,3}\b|(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2})"
)
_REALTIME_RE = re.compile(r"(今天|今日|现在|最新|实时|天气|股价|金价|新闻|当前|刚刚|today|latest|weather)", re.IGNORECASE)


def _normalize_query(query: str) -> str:
    text = " ".join(str(query or "").strip().lower().split())
    text = re.sub(r"[?？。！!，,、；;]+$", "", text).strip()
    return text


def _query_hash(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _ensure_table(conn: Any) -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_semantic_qa_cache (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
                intent TEXT NOT NULL,
                query_normalized TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                embedding_json TEXT,
                answer_text TEXT NOT NULL,
                citations_json TEXT NOT NULL DEFAULT '[]',
                kb_version TEXT NOT NULL DEFAULT '',
                hit_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_semantic_cache_lookup ON ai_semantic_qa_cache(tenant_id, intent, query_hash)"
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    _TABLE_READY = True


def _current_kb_version(conn: Any) -> str:
    try:
        row = conn.execute("SELECT MAX(updated_at) FROM ai_knowledge_documents").fetchone()
        return str((row[0] if row else "") or "")
    except Exception:
        return ""


def _embed_for_cache(normalized_query: str) -> Optional[List[float]]:
    try:
        from ai.providers.embedding import semantic_embedding_provider

        provider = semantic_embedding_provider()
        if provider is None:
            return None
        # Only use local/zero-cost embedding providers for cache lookups.
        if str(getattr(provider, "mode", "") or "").lower() == "external":
            return None
        vec = provider.embed_query(normalized_query)
        return [float(v) for v in vec] if vec else None
    except Exception:
        return None


def is_cacheable_query(
    query: str,
    *,
    intent: str,
    has_history: bool = False,
    web_search: bool = False,
) -> bool:
    """Return True only when a query is safe and deterministic to cache locally."""
    if not bool(getattr(settings, "AI_SEMANTIC_CACHE_ENABLED", True)):
        return False
    if str(intent or "").strip().lower() not in _CACHEABLE_INTENTS:
        return False
    if has_history or web_search:
        return False
    norm = _normalize_query(query)
    if len(norm) < 4 or len(norm) > 240:
        return False
    if _IP_OR_MAC_RE.search(norm) or _REALTIME_RE.search(norm):
        return False
    return True


def lookup_semantic_cache(
    query: str,
    *,
    intent: str,
    tenant_id: Optional[str] = None,
    has_history: bool = False,
    web_search: bool = False,
) -> Optional[Dict[str, Any]]:
    """Look up an exact or high-similarity cached answer from PostgreSQL."""
    if not is_cacheable_query(query, intent=intent, has_history=has_history, web_search=web_search):
        return None

    norm = _normalize_query(query)
    qhash = _query_hash(norm)
    tid = str(tenant_id or "tenant-default")
    now_iso = datetime.now(timezone.utc).isoformat()
    threshold = float(getattr(settings, "AI_SEMANTIC_CACHE_THRESHOLD", 0.94) or 0.94)

    try:
        with get_db_connection() as conn:
            _ensure_table(conn)
            kb_ver = _current_kb_version(conn)

            # Tier 1: O(1) exact normalized hash match
            row = conn.execute(
                """
                SELECT id, answer_text, citations_json, query_normalized
                FROM ai_semantic_qa_cache
                WHERE tenant_id = ? AND intent = ? AND query_hash = ?
                  AND kb_version = ? AND expires_at > ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (tid, intent, qhash, kb_ver, now_iso),
            ).fetchone()
            if row:
                conn.execute("UPDATE ai_semantic_qa_cache SET hit_count = hit_count + 1 WHERE id = ?", (row[0],))
                conn.commit()
                return {
                    "cache_id": row[0],
                    "answer": str(row[1] or ""),
                    "citations": json.loads(row[2] or "[]"),
                    "similarity": 1.0,
                    "match_type": "exact",
                }

            # Tier 2: Semantic cosine similarity via local embedding provider
            qvec = _embed_for_cache(norm)
            if not qvec:
                return None

            candidates = conn.execute(
                """
                SELECT id, answer_text, citations_json, embedding_json
                FROM ai_semantic_qa_cache
                WHERE tenant_id = ? AND intent = ? AND kb_version = ?
                  AND expires_at > ? AND embedding_json IS NOT NULL
                ORDER BY created_at DESC LIMIT 120
                """,
                (tid, intent, kb_ver, now_iso),
            ).fetchall()
            best_row = None
            best_sim = 0.0
            for cand in candidates:
                try:
                    cvec = json.loads(cand[3] or "[]")
                except Exception:
                    continue
                sim = _cosine_similarity(qvec, cvec)
                if sim >= threshold and sim > best_sim:
                    best_sim = sim
                    best_row = cand

            if best_row is not None:
                conn.execute("UPDATE ai_semantic_qa_cache SET hit_count = hit_count + 1 WHERE id = ?", (best_row[0],))
                conn.commit()
                return {
                    "cache_id": best_row[0],
                    "answer": str(best_row[1] or ""),
                    "citations": json.loads(best_row[2] or "[]"),
                    "similarity": round(best_sim, 4),
                    "match_type": "semantic",
                }
    except Exception as exc:
        logger.debug("Semantic cache lookup skipped: %s", type(exc).__name__)
    return None


def store_semantic_cache(
    query: str,
    answer: str,
    *,
    intent: str,
    citations: Optional[List[Dict[str, Any]]] = None,
    tenant_id: Optional[str] = None,
    has_history: bool = False,
    web_search: bool = False,
) -> bool:
    """Persist a verified clean answer into PostgreSQL semantic cache."""
    if not is_cacheable_query(query, intent=intent, has_history=has_history, web_search=web_search):
        return False
    clean_answer = str(answer or "").strip()
    if len(clean_answer) < 20 or len(clean_answer) > 20_000:
        return False
    # Never cache error/fallback/security messages.
    if any(bad in clean_answer for bad in ("请求被安全策略拦截", "暂时无法生成回答", "处理失败", "[[NXA_")):
        return False

    norm = _normalize_query(query)
    qhash = _query_hash(norm)
    tid = str(tenant_id or "tenant-default")
    ttl_hours = max(1, int(getattr(settings, "AI_SEMANTIC_CACHE_TTL_HOURS", 24) or 24))
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=ttl_hours)
    qvec = _embed_for_cache(norm)
    emb_json = json.dumps(qvec) if qvec else None

    try:
        with get_db_connection() as conn:
            _ensure_table(conn)
            kb_ver = _current_kb_version(conn)
            conn.execute(
                """
                INSERT INTO ai_semantic_qa_cache
                    (id, tenant_id, intent, query_normalized, query_hash, embedding_json,
                     answer_text, citations_json, kb_version, hit_count, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    f"sc_{uuid.uuid4().hex[:16]}",
                    tid,
                    intent,
                    norm,
                    qhash,
                    emb_json,
                    clean_answer,
                    json.dumps(citations or [], ensure_ascii=False),
                    kb_ver,
                    now.isoformat(),
                    expires.isoformat(),
                ),
            )
            conn.commit()
            return True
    except Exception as exc:
        logger.debug("Semantic cache store skipped: %s", type(exc).__name__)
        return False
