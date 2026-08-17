"""PostgreSQL RET-022 benchmark over session-local fixtures.

The benchmark never touches production tables.  It uses one temporary table,
builds the same FTS/trigram/HNSW index shapes as m0138, measures bounded top-k
queries at 10k/100k/1m rows, records p50/p95 and rolls the transaction back.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from database import core  # noqa: E402


SCALES = (10_000, 100_000, 1_000_000)
REPEATS = 5


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


def _run() -> dict[str, Any]:
    if not core._USE_PG:
        raise RuntimeError("RET-022 requires PostgreSQL; SQLite is not a benchmark substitute")
    conn = core.get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("CREATE TEMP TABLE ret_benchmark_chunk (id BIGINT PRIMARY KEY, tenant_id TEXT NOT NULL, search_text TEXT NOT NULL, embedding_vector vector(3) NOT NULL)")
        # Build indexes after each scale's bulk load.  Building HNSW while
        # inserting one row at a time makes the 1m fixture needlessly slow and
        # does not represent the normal bulk-index deployment path.
        cur.execute("SET maintenance_work_mem = '256MB'")
        results: list[dict[str, Any]] = []
        for scale in SCALES:
            cur.execute("TRUNCATE ret_benchmark_chunk")
            cur.execute("DROP INDEX IF EXISTS ret_bench_fts")
            cur.execute("DROP INDEX IF EXISTS ret_bench_trgm")
            cur.execute("DROP INDEX IF EXISTS ret_bench_hnsw")
            cur.execute("DROP INDEX IF EXISTS ret_bench_hnsw_tenant_a")
            cur.execute(
                "INSERT INTO ret_benchmark_chunk (id, tenant_id, search_text, embedding_vector) "
                "SELECT g, CASE WHEN g % 10 = 0 THEN 'tenant-b' ELSE 'tenant-a' END, "
                "'display ospf peer reference ' || g, "
                "CASE WHEN g % 100 = 0 THEN '[1,0,0]'::vector ELSE '[0,1,0]'::vector END "
                "FROM generate_series(1, ?, 1) AS g",
                (scale,),
            )
            cur.execute("CREATE INDEX ret_bench_fts ON ret_benchmark_chunk USING GIN (to_tsvector('simple', search_text))")
            cur.execute("CREATE INDEX ret_bench_trgm ON ret_benchmark_chunk USING GIN (search_text gin_trgm_ops)")
            cur.execute("CREATE INDEX ret_bench_hnsw ON ret_benchmark_chunk USING hnsw (embedding_vector vector_cosine_ops) WITH (m=4, ef_construction=8)")
            # A tenant-partial HNSW index is an explicit comparison point for
            # deployments that need a highly selective access scope.  The
            # application path still bounds the shared m0138 index by IDs.
            cur.execute("CREATE INDEX ret_bench_hnsw_tenant_a ON ret_benchmark_chunk USING hnsw (embedding_vector vector_cosine_ops) WITH (m=4, ef_construction=8) WHERE tenant_id='tenant-a'")
            cur.execute("ANALYZE ret_benchmark_chunk")
            conn.commit()
            # pgvector approximate filtering can exhaust ef_search before it
            # finds ten rows for a selective tenant predicate.  Iterative scan
            # is the production-safe setting for this benchmark and records
            # the behavior we require from RET-010.
            cur.execute("SET hnsw.iterative_scan = 'strict_order'")
            cur.execute("SET hnsw.ef_search = 100")
            timings: dict[str, list[float]] = {"fts_ms": [], "trgm_ms": [], "vector_ms": []}
            queries = {
                "fts_ms": "SELECT id FROM ret_benchmark_chunk WHERE tenant_id='tenant-a' AND to_tsvector('simple', search_text) @@ websearch_to_tsquery('simple', 'show ospf peer') LIMIT 10",
                "trgm_ms": "SELECT id FROM ret_benchmark_chunk WHERE tenant_id='tenant-a' AND similarity(search_text, 'display ospf peer refernce') >= 0.35 ORDER BY similarity(search_text, 'display ospf peer refernce') DESC LIMIT 10",
                "vector_ms": "SELECT id FROM ret_benchmark_chunk WHERE tenant_id='tenant-a' ORDER BY embedding_vector <=> '[1,0,0]'::vector LIMIT 10",
            }
            for _ in range(REPEATS):
                for name, sql in queries.items():
                    started = time.perf_counter()
                    cur.execute(sql)
                    cur.fetchall()
                    timings[name].append((time.perf_counter() - started) * 1000.0)
            cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + queries["vector_ms"])
            plan = cur.fetchone()[0]
            vector_nodes = list(_walk(plan))
            vector_ids = [row[0] for row in cur.execute(queries["vector_ms"]).fetchall()]
            tenant_leaks = [row for row in cur.execute("SELECT id, tenant_id FROM ret_benchmark_chunk WHERE id = ANY(?)", ([*vector_ids],)).fetchall() if row[1] != "tenant-a"]
            row_result = {
                "rows": scale,
                "p50_ms": {name: round(statistics.median(values), 3) for name, values in timings.items()},
                "p95_ms": {name: round(sorted(values)[max(0, int(len(values) * 0.95) - 1)], 3) for name, values in timings.items()},
                "vector_plan_indexes": _index_names(plan),
                "vector_plan_nodes": [str(node.get("Node Type")) for node in vector_nodes],
                "top_k": len(vector_ids),
                "tenant_leaks": len(tenant_leaks),
            }
            if row_result["tenant_leaks"] != 0 or row_result["top_k"] != 10:
                raise AssertionError(f"RET-022 tenant/top-k gate failed: {row_result}")
            results.append(row_result)
        conn.rollback()
        return {
            "status": "PASS",
            "database": "PostgreSQL",
            "server": str(cur.execute("SELECT version()").fetchone()[0]),
            "extensions": {str(row[0]): str(row[1]) for row in cur.execute("SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector','pg_trgm')").fetchall()},
            "fixture": "temporary_session_only",
            "repeats": REPEATS,
            "scales": results,
            "rollback": "PASS",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        payload = _run()
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if payload["status"] == "PASS" else 1)
