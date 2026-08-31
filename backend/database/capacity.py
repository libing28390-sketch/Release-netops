"""Read-only V2 storage and index-capacity evaluation.

DB-024 intentionally separates an explicit sizing model from PostgreSQL
relation statistics.  The model is reproducible and exposes every assumption;
the catalog probe is read-only and reports bloat signals when the target tables
exist.  No synthetic million-row data is inserted into a production database.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import get_db_connection


logger = logging.getLogger(__name__)
SCENARIOS = (
    ("10k_documents_100k_chunks", 10_000, 100_000),
    ("10k_documents_1m_chunks", 10_000, 1_000_000),
)
DEFAULTS = {
    "document_row_bytes": 4096,
    "chunk_row_bytes": 6144,
    "document_index_bytes_per_row": 96,
    "chunk_btree_bytes_per_row": 96,
    "embedding_dimensions": 1536,
    "vector_index_multiplier": 1.55,
    "json_gin_bytes_per_chunk": 220,
    "bloat_budget_ratio": 0.20,
    "operational_relation_budget_bytes": 512 * 1024**3,
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def estimate_scale(
    *,
    document_count: int,
    chunk_count: int,
    assumptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate table/index bytes with explicit, reviewable assumptions."""
    docs = int(document_count)
    chunks = int(chunk_count)
    if docs < 0 or chunks < 0:
        raise ValueError("document_count and chunk_count must be non-negative")
    values = {**DEFAULTS, **(assumptions or {})}
    dimensions = int(values["embedding_dimensions"])
    if dimensions <= 0:
        raise ValueError("embedding_dimensions must be positive")
    raw_embedding_bytes = chunks * dimensions * 4
    document_table = docs * int(values["document_row_bytes"])
    chunk_table = chunks * int(values["chunk_row_bytes"])
    document_indexes = docs * int(values["document_index_bytes_per_row"])
    chunk_btree = chunks * int(values["chunk_btree_bytes_per_row"])
    vector_index = int(raw_embedding_bytes * float(values["vector_index_multiplier"]))
    json_gin = chunks * int(values["json_gin_bytes_per_chunk"])
    relation_bytes = document_table + chunk_table + document_indexes + chunk_btree + vector_index + json_gin
    bloat_budget = int(relation_bytes * float(values["bloat_budget_ratio"]))
    operational_budget = int(values["operational_relation_budget_bytes"])
    return {
        "name": f"{docs:,}_documents_{chunks:,}_chunks",
        "document_count": docs,
        "chunk_count": chunks,
        "table_bytes": {"ai_document": document_table, "ai_document_chunk": chunk_table},
        "index_bytes": {
            "document_btree": document_indexes,
            "chunk_btree": chunk_btree,
            "vector_index_estimate": vector_index,
            "chunk_metadata_gin_estimate": json_gin,
        },
        "raw_embedding_bytes": raw_embedding_bytes,
        "estimated_relation_bytes": relation_bytes,
        "estimated_relation_gib": round(relation_bytes / 1024**3, 3),
        "bloat_budget_bytes": bloat_budget,
        "operational_relation_budget_bytes": operational_budget,
        "status": "PASS" if relation_bytes <= operational_budget else "WARN",
        "assumptions": values,
        "assumption_warning": "Estimates require staging measurement before production sizing; vector index multiplier is model/version dependent.",
    }


def collect_postgres_relation_stats(
    conn: Any,
    *,
    table_names: tuple[str, ...] = ("ai_document", "ai_document_chunk"),
) -> dict[str, Any]:
    """Read PostgreSQL table/index/bloat signals without ANALYZE or writes."""
    tables: list[dict[str, Any]] = []
    for table in table_names:
        if not table.replace("_", "").isalnum():
            continue
        try:
            row = conn.execute(
                """
                SELECT c.relname,
                       COALESCE(s.n_live_tup, 0), COALESCE(s.n_dead_tup, 0),
                       COALESCE(pg_total_relation_size(c.oid), 0),
                       COALESCE(pg_indexes_size(c.oid), 0),
                       COALESCE(c.reltuples, 0)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
                WHERE n.nspname = current_schema() AND c.relname = ?
                """,
                (table,),
            ).fetchone()
        except Exception as exc:
            tables.append({"table": table, "status": "ERROR", "error_class": type(exc).__name__})
            continue
        if row is None:
            tables.append({"table": table, "status": "NOT_APPLICABLE"})
            continue
        live = int(row[1] or 0)
        dead = int(row[2] or 0)
        total = int(row[3] or 0)
        indexes = int(row[4] or 0)
        bloat_ratio = round(dead / live, 4) if live else 0.0
        tables.append({
            "table": str(row[0]), "status": "PASS" if bloat_ratio <= DEFAULTS["bloat_budget_ratio"] else "WARN",
            "live_rows": live, "dead_rows": dead, "total_bytes": total,
            "index_bytes": indexes, "planner_estimated_rows": float(row[5] or 0),
            "dead_to_live_ratio": bloat_ratio,
            "vacuum_signal": "review_autovacuum_or_bounded_repack" if bloat_ratio > DEFAULTS["bloat_budget_ratio"] else None,
        })
    return {
        "backend": "postgresql", "status": "PASS" if all(item.get("status") in {"PASS", "NOT_APPLICABLE"} for item in tables) else "WARN",
        "read_only": True, "tables": tables,
    }


def run_capacity_evaluation(
    conn: Any | None = None,
    *,
    assumptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return scale scenarios plus optional live PostgreSQL relation stats."""
    own_conn = conn is None
    connection = conn or get_db_connection()
    try:
        scenarios = [
            estimate_scale(document_count=docs, chunk_count=chunks, assumptions=assumptions)
            for _, docs, chunks in SCENARIOS
        ]
        stats = collect_postgres_relation_stats(connection)
        return {
            "scope": "knowledge_engine_capacity",
            "checked_at": _now(),
            "backend": "postgresql",
            "read_only": True,
            "scenarios": scenarios,
            "relation_stats": stats,
            "decision": "staging_load_required_before_production_scale",
            "no_synthetic_production_rows": True,
        }
    finally:
        if own_conn:
            connection.close()


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Nexora Knowledge Engine capacity evaluation")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = run_capacity_evaluation()
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = ["collect_postgres_relation_stats", "estimate_scale", "run_capacity_evaluation"]
