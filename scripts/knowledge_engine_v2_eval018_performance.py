"""PostgreSQL-only EVAL-018 performance samples.

The benchmark creates one temporary fixture and measures representative FTS,
trigram and pgvector top-k retrieval at 10k, 100k and 1m rows.  It never
touches V1/V2 production tables.  Five repetitions are intentionally bounded;
therefore p99 is the maximum observed sample and is reported as diagnostic
capacity evidence, not as a production SLO claim.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from database import core  # noqa: E402


TASK_ID = "EVAL-018"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-performance-v1.json"
SCALES = (10_000, 100_000, 1_000_000)
REPEATS = 5
QUERY_NAMES = ("fts", "trigram", "vector")


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if "Node Type" in value:
            yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _index_names(plan: Any) -> list[str]:
    return sorted({str(node["Index Name"]) for node in _walk(plan) if node.get("Index Name")})


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one sample")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return round(ordered[index], 3)


def _query_map() -> dict[str, str]:
    return {
        "fts": (
            "SELECT id FROM eval018_chunk "
            "WHERE tenant_id='tenant-a' "
            "AND to_tsvector('simple', search_text) "
            "@@ websearch_to_tsquery('simple', 'show ospf peer') LIMIT 10"
        ),
        "trigram": (
            "SELECT id FROM eval018_chunk "
            "WHERE tenant_id='tenant-a' "
            "AND similarity(search_text, 'display ospf peer refernce') >= 0.35 "
            "ORDER BY similarity(search_text, 'display ospf peer refernce') DESC LIMIT 10"
        ),
        "vector": (
            "SELECT id FROM eval018_chunk "
            "WHERE tenant_id='tenant-a' "
            "ORDER BY embedding_vector <=> '[1,0,0]'::vector LIMIT 10"
        ),
    }


def _run() -> dict[str, Any]:
    if not core._USE_PG:
        raise RuntimeError("EVAL-018 requires PostgreSQL; SQLite is forbidden")

    conn = core.get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "CREATE TEMP TABLE eval018_chunk ("
            "id BIGINT PRIMARY KEY, tenant_id TEXT NOT NULL, "
            "search_text TEXT NOT NULL, embedding_vector vector(3) NOT NULL"
            ")"
        )
        cur.execute("SET maintenance_work_mem = '256MB'")
        cur.execute("SET statement_timeout = '1800000'")
        results: list[dict[str, Any]] = []
        queries = _query_map()

        for scale in SCALES:
            scale_started = time.perf_counter()
            cur.execute("TRUNCATE eval018_chunk")
            for index_name in (
                "eval018_fts",
                "eval018_trgm",
                "eval018_hnsw",
                "eval018_hnsw_tenant_a",
            ):
                cur.execute(f"DROP INDEX IF EXISTS {index_name}")
            cur.execute(
                "INSERT INTO eval018_chunk (id, tenant_id, search_text, embedding_vector) "
                "SELECT g, CASE WHEN g % 10 = 0 THEN 'tenant-b' ELSE 'tenant-a' END, "
                "'display ospf peer reference ' || g, "
                "CASE WHEN g % 100 = 0 THEN '[1,0,0]'::vector ELSE '[0,1,0]'::vector END "
                "FROM generate_series(1, ?, 1) AS g",
                (scale,),
            )
            cur.execute(
                "CREATE INDEX eval018_fts ON eval018_chunk "
                "USING GIN (to_tsvector('simple', search_text))"
            )
            cur.execute(
                "CREATE INDEX eval018_trgm ON eval018_chunk "
                "USING GIN (search_text gin_trgm_ops)"
            )
            cur.execute(
                "CREATE INDEX eval018_hnsw ON eval018_chunk "
                "USING hnsw (embedding_vector vector_cosine_ops) "
                "WITH (m=4, ef_construction=8)"
            )
            cur.execute(
                "CREATE INDEX eval018_hnsw_tenant_a ON eval018_chunk "
                "USING hnsw (embedding_vector vector_cosine_ops) "
                "WITH (m=4, ef_construction=8) WHERE tenant_id='tenant-a'"
            )
            cur.execute("ANALYZE eval018_chunk")
            cur.execute("SET hnsw.iterative_scan = 'strict_order'")
            cur.execute("SET hnsw.ef_search = 100")

            timings: dict[str, list[float]] = {name: [] for name in QUERY_NAMES}
            for name in QUERY_NAMES:
                # Warm the planner/cache once, outside the measured sample.
                cur.execute(queries[name])
                cur.fetchall()
                for _ in range(REPEATS):
                    started = time.perf_counter()
                    cur.execute(queries[name])
                    cur.fetchall()
                    timings[name].append((time.perf_counter() - started) * 1000.0)

            cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + queries["vector"])
            vector_plan = cur.fetchone()[0]
            vector_ids = [row[0] for row in cur.execute(queries["vector"]).fetchall()]
            tenant_leaks = [
                row
                for row in cur.execute(
                    "SELECT id, tenant_id FROM eval018_chunk WHERE id = ANY(?)",
                    ([*vector_ids],),
                ).fetchall()
                if row[1] != "tenant-a"
            ]
            if len(vector_ids) != 10 or tenant_leaks:
                raise AssertionError(
                    f"EVAL-018 tenant/top-k gate failed at {scale}: "
                    f"top_k={len(vector_ids)} leaks={len(tenant_leaks)}"
                )

            p50 = {name: _percentile(values, 0.50) for name, values in timings.items()}
            p95 = {name: _percentile(values, 0.95) for name, values in timings.items()}
            p99 = {name: _percentile(values, 0.99) for name, values in timings.items()}
            results.append(
                {
                    "rows": scale,
                    "sample_count": REPEATS,
                    "p50_ms": p50,
                    "p95_ms": p95,
                    "p99_ms": p99,
                    "p99_is_max_observed": True,
                    "vector_plan_indexes": _index_names(vector_plan),
                    "vector_plan_nodes": [str(node.get("Node Type")) for node in _walk(vector_plan)],
                    "top_k": len(vector_ids),
                    "tenant_leaks": len(tenant_leaks),
                    "scale_elapsed_ms": round((time.perf_counter() - scale_started) * 1000.0, 3),
                }
            )

        cur.execute(
            "SELECT extname, extversion FROM pg_extension "
            "WHERE extname IN ('vector', 'pg_trgm') ORDER BY extname"
        )
        extensions = {str(row[0]): str(row[1]) for row in cur.fetchall()}
        if set(extensions) != {"vector", "pg_trgm"}:
            raise AssertionError(f"EVAL-018 requires vector and pg_trgm: {extensions}")
        server = str(cur.execute("SELECT version()").fetchone()[0])
        conn.rollback()
        return {
            "status": "PASS_WITH_CAPACITY_WARNING",
            "task_id": TASK_ID,
            "database": "PostgreSQL",
            "sqlite": "forbidden",
            "server": server,
            "extensions": extensions,
            "fixture": "temporary_session_only",
            "repeats": REPEATS,
            "percentile_method": "nearest_rank; p99 is max observed with five repetitions",
            "scales": results,
            "production_database_write": False,
            "rollback": "transaction_rollback_and_connection_close",
            "capacity_warning": any(
                row["p95_ms"]["trigram"] > 3000 for row in results
            ),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        report = _run()
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "task_id": TASK_ID, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0)
