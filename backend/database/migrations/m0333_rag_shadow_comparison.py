"""Durable record of RAG shadow comparisons (RAG refactor phase 5).

``AI_RETRIEVAL_ENGINE=shadow`` serves the V1 result and runs V2 next to it.
Until now the comparison only reached a log line and the per-request debug
payload, so a week of shadow traffic could not be summarised.  One row per
compared search, metadata only:

* no query text by default -- ``query_hash`` (sha256, 32 hex) groups repeats;
  ``query_preview`` is filled only when AI_RETRIEVAL_SHADOW_STORE_QUERY=1,
  after the log sanitizer, at most 200 characters;
* document ids (internal identifiers) of both top-k lists, so a mismatch can
  be investigated without re-running it;
* ``v2_engine`` separates the indexed path from the exact small-set path:
  below AI_RETRIEVAL_V2_EXACT_THRESHOLD chunks V2 *is* V1, so those rows
  always agree and must not be counted as evidence for the switch.

Rows older than AI_RETRIEVAL_SHADOW_RETENTION_DAYS (30) are pruned by the
writer.  Summarise with ``python scripts/rag_shadow_report.py``.
"""

from __future__ import annotations

VERSION = 333
NAME = "rag_shadow_comparison"

TABLE = "ai_retrieval_shadow_comparison"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            query_hash TEXT NOT NULL,
            query_preview TEXT,
            status TEXT NOT NULL,
            error_code TEXT,
            v2_engine TEXT,
            vector_source TEXT,
            top1_match BOOLEAN,
            overlap_at_k REAL,
            v1_result_count INTEGER NOT NULL DEFAULT 0,
            v2_result_count INTEGER NOT NULL DEFAULT 0,
            v2_candidate_count INTEGER,
            v1_latency_ms INTEGER,
            v2_latency_ms INTEGER,
            v1_document_ids TEXT[] NOT NULL DEFAULT '{{}}',
            v2_document_ids TEXT[] NOT NULL DEFAULT '{{}}',
            capability_degraded TEXT[] NOT NULL DEFAULT '{{}}'
        )
        """
    )
    cursor.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_created_at ON {TABLE} (created_at)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_query_hash ON {TABLE} (query_hash)")


def downgrade(cursor, use_pg: bool) -> None:
    # Diagnostic data only; dropping it loses nothing the product relies on.
    if use_pg:
        cursor.execute(f"DROP TABLE IF EXISTS {TABLE}")
