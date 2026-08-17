"""Bounded, read-only PostgreSQL operational telemetry for OBS-008.

The API exposes only aggregate catalog statistics.  It deliberately does not
return SQL text, query parameters, database credentials, tenant identifiers,
document bodies, or host details.  PostgreSQL is the production authority;
SQLite is reported as a compatibility boundary and is never accepted as a
production capacity result.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from database import core as database_core
from database.capacity import DEFAULTS, collect_postgres_relation_stats


_OBSERVATION_TABLES = (
    "ai_document",
    "ai_document_chunk",
    "ai_request_log",
    "ai_trace",
    "kb_document",
    "kb_document_version",
)
_MAX_SLOW_QUERIES = 20
_DEFAULT_SLOW_QUERY_MS = 500.0


def _bounded_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, parsed)


def _bounded_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _slow_query_threshold_ms() -> float:
    raw = os.environ.get("NEXORA_SLOW_QUERY_THRESHOLD_MS", "")
    value = _bounded_float(raw, _DEFAULT_SLOW_QUERY_MS)
    return value if value > 0 else _DEFAULT_SLOW_QUERY_MS


def _run_probe(
    name: str,
    probe: Callable[[], dict[str, Any]],
    connection: Any | None = None,
) -> dict[str, Any]:
    """Run one independent catalog probe and redact all failure details."""

    try:
        result = probe()
        result.setdefault("status", "PASS")
        return result
    except Exception as exc:  # pragma: no cover - exercised by DB permission probes
        if connection is not None:
            _safe_rollback(connection)
        return {
            "status": "UNAVAILABLE",
            "error_class": type(exc).__name__,
            "probe": name,
        }


def _safe_rollback(connection: Any) -> None:
    try:
        connection.rollback()
    except Exception:
        pass


def _cache_probe(connection: Any) -> dict[str, Any]:
    placeholders = ", ".join("?" for _ in _OBSERVATION_TABLES)
    row = connection.execute(
        f"""
        SELECT COALESCE(SUM(heap_blks_hit), 0), COALESCE(SUM(heap_blks_read), 0)
        FROM pg_statio_user_tables
        WHERE schemaname = current_schema() AND relname IN ({placeholders})
        """,
        _OBSERVATION_TABLES,
    ).fetchone()
    hits = _bounded_int(row[0] if row else 0)
    reads = _bounded_int(row[1] if row else 0)
    total = hits + reads
    return {
        "status": "PASS",
        "scope": "allowlisted_knowledge_relations",
        "hits": hits,
        "reads": reads,
        "hit_rate": round(hits / total, 6) if total else 0.0,
    }


def _slow_query_probe(connection: Any) -> dict[str, Any]:
    threshold = _slow_query_threshold_ms()
    # pg_stat_statements is optional.  Querying it directly lets deployments
    # without the extension fall back to currently active statements.
    try:
        rows = connection.execute(
            """
            SELECT queryid, calls, total_exec_time, mean_exec_time, rows,
                   shared_blks_hit, shared_blks_read
            FROM pg_stat_statements
            WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
            ORDER BY total_exec_time DESC
            LIMIT ?
            """,
            (_MAX_SLOW_QUERIES,),
        ).fetchall()
    except Exception as extension_error:
        _safe_rollback(connection)
        active_row = connection.execute(
            """
            SELECT COUNT(*), COALESCE(MAX(EXTRACT(EPOCH FROM (clock_timestamp() - query_start)) * 1000), 0)
            FROM pg_stat_activity
            WHERE datname = current_database() AND pid <> pg_backend_pid()
              AND state = 'active' AND query_start IS NOT NULL
              AND EXTRACT(EPOCH FROM (clock_timestamp() - query_start)) * 1000 >= ?
            """,
            (threshold,),
        ).fetchone()
        active_count = _bounded_int(active_row[0] if active_row else 0)
        max_active_ms = round(_bounded_float(active_row[1] if active_row else 0), 3)
        return {
            "status": "PASS",
            "source": "pg_stat_activity",
            "extension": "pg_stat_statements",
            "extension_status": "UNAVAILABLE",
            "extension_error_class": type(extension_error).__name__,
            "threshold_ms": threshold,
            "sample_size": active_count,
            "slow_query_count": active_count,
            "max_active_ms": max_active_ms,
            "queries": [],
            "query_text_included": False,
        }
    queries: list[dict[str, Any]] = []
    slow_count = 0
    for row in rows:
        mean_ms = round(_bounded_float(row[3] if len(row) > 3 else 0), 3)
        if mean_ms >= threshold:
            slow_count += 1
        queries.append({
            "query_id": str(row[0])[:64] if row[0] is not None else None,
            "calls": _bounded_int(row[1] if len(row) > 1 else 0),
            "total_exec_ms": round(_bounded_float(row[2] if len(row) > 2 else 0), 3),
            "mean_exec_ms": mean_ms,
            "rows": _bounded_int(row[4] if len(row) > 4 else 0),
            "shared_blks_hit": _bounded_int(row[5] if len(row) > 5 else 0),
            "shared_blks_read": _bounded_int(row[6] if len(row) > 6 else 0),
        })
    return {
        "status": "PASS",
        "extension": "pg_stat_statements",
        "threshold_ms": threshold,
        "sample_size": len(queries),
        "slow_query_count": slow_count,
        "queries": queries,
        "query_text_included": False,
    }


def _capacity_probe(connection: Any) -> dict[str, Any]:
    row = connection.execute(
        "SELECT pg_database_size(current_database())"
    ).fetchone()
    database_bytes = _bounded_int(row[0] if row else 0)
    budget_bytes = _bounded_int(DEFAULTS["operational_relation_budget_bytes"])
    usage_ratio = database_bytes / budget_bytes if budget_bytes else 0.0
    if usage_ratio >= 0.95:
        status = "CRITICAL"
    elif usage_ratio >= 0.80:
        status = "WARN"
    else:
        status = "PASS"
    return {
        "status": status,
        "scope": "current_database",
        "database_bytes": database_bytes,
        "budget_bytes": budget_bytes,
        "usage_ratio": round(usage_ratio, 6),
        "budget_source": "DB-024 operational_relation_budget_bytes",
        "synthetic_rows_inserted": False,
    }


def snapshot(connection: Any | None = None) -> dict[str, Any]:
    """Return a bounded OBS-008 snapshot without changing database state."""

    use_pg = bool(database_core._USE_PG)
    if not use_pg:
        return {
            "backend": "sqlite",
            "status": "NOT_APPLICABLE",
            "production_authority": "postgresql",
            "reason": "SQLite is compatibility-only for OBS-008 production monitoring",
        }

    own_connection = connection is None
    conn = connection or database_core.get_db_connection()
    try:
        relation_stats = _run_probe(
            "relation_stats",
            lambda: collect_postgres_relation_stats(
                conn,
                table_names=_OBSERVATION_TABLES,
                use_pg=True,
            ),
            conn,
        )
        cache = _run_probe("cache", lambda: _cache_probe(conn), conn)
        slow_queries = _run_probe("slow_queries", lambda: _slow_query_probe(conn), conn)
        capacity = _run_probe("capacity", lambda: _capacity_probe(conn), conn)
        child_statuses = (relation_stats, cache, slow_queries, capacity)
        if any(item.get("status") == "UNAVAILABLE" for item in child_statuses):
            status = "DEGRADED"
        elif any(item.get("status") in {"WARN", "CRITICAL"} for item in child_statuses):
            status = "WARN"
        else:
            status = "PASS"
        return {
            "backend": "postgresql",
            "status": status,
            "read_only": True,
            "production_authority": "postgresql",
            "relation_stats": relation_stats,
            "cache": cache,
            "slow_queries": slow_queries,
            "capacity": capacity,
            "redaction": {
                "query_text": False,
                "parameters": False,
                "credentials": False,
                "tenant_ids": False,
                "document_content": False,
            },
        }
    finally:
        if own_connection:
            conn.close()


__all__ = ["snapshot"]
