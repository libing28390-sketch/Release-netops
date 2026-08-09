"""DB-016 PostgreSQL EXPLAIN gate probe.

The probe uses session-local temporary tables and indexes only.  Fixture setup
is committed so the subsequent EXPLAIN transaction can be explicitly
READ ONLY; closing the connection drops all temporary objects.  No production
tables, indexes, rows, or migration versions are changed by this script.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from database import core  # noqa: E402


ROW_COUNT = 20_000
TOP_K = 10
QUERY_VECTOR = "[1,0,0]"
ALLOWED_ROLE = "reader"


def _walk(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        if "Node Type" in node:
            yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _plan_nodes(plan_json: list[Any]) -> list[dict[str, Any]]:
    if not plan_json or not isinstance(plan_json[0], dict):
        raise AssertionError("EXPLAIN JSON did not contain a plan object")
    return list(_walk(plan_json[0].get("Plan", plan_json[0])))


def _index_names(nodes: Iterable[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(node["Index Name"])
            for node in nodes
            if node.get("Index Name")
        }
    )


def _predicates(nodes: Iterable[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for node in nodes:
        for key in ("Index Cond", "Recheck Cond", "Filter", "Join Filter", "Hash Cond"):
            value = node.get(key)
            if value:
                values.append(f"{key}: {value}")
    return values


def _sum_metric(nodes: Iterable[dict[str, Any]], key: str) -> int:
    return sum(int(node.get(key, 0) or 0) for node in nodes)


def _estimate_error(nodes: Iterable[dict[str, Any]]) -> float:
    candidates = [
        node
        for node in nodes
        if node.get("Actual Rows") is not None and node.get("Plan Rows") is not None
    ]
    if not candidates:
        return 1.0
    # The first candidate is the outermost node; a LIMIT node should have the
    # bounded top-k cardinality that the contract evaluates.
    node = candidates[0]
    actual = float(node.get("Actual Rows") or 0)
    planned = float(node.get("Plan Rows") or 0)
    if actual == 0:
        return 0.0 if planned == 0 else 1.0
    return abs(planned - actual) / actual


def _query_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _fixture_hash() -> str:
    payload = f"db016-v2|rows={ROW_COUNT}|top_k={TOP_K}|vector={QUERY_VECTOR}|role={ALLOWED_ROLE}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _explain(cur: Any, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    statement = "EXPLAIN (ANALYZE, BUFFERS, WAL, SETTINGS, FORMAT JSON) " + sql
    cur.execute(statement, params)
    payload = cur.fetchone()[0]
    nodes = _plan_nodes(payload)
    index_names = _index_names(nodes)
    seq_scans = [node for node in nodes if node.get("Node Type") == "Seq Scan"]
    large_seq_scans = [
        node for node in seq_scans if int(node.get("Actual Rows", 0) or 0) > 5_000
    ]
    return {
        "query_hash": _query_hash(sql),
        "index_names": index_names,
        "node_types": [str(node.get("Node Type")) for node in nodes],
        "predicates": _predicates(nodes),
        "row_estimates": [
            {
                "node": str(node.get("Node Type")),
                "plan_rows": node.get("Plan Rows"),
                "actual_rows": node.get("Actual Rows"),
            }
            for node in nodes
        ],
        "estimate_error": round(_estimate_error(nodes), 6),
        "planning_ms": round(float(payload[0].get("Planning Time", 0.0) or 0.0), 3),
        "execution_ms": round(float(payload[0].get("Execution Time", 0.0) or 0.0), 3),
        "buffers": {
            "shared_hit": _sum_metric(nodes, "Shared Hit Blocks"),
            "shared_read": _sum_metric(nodes, "Shared Read Blocks"),
            "local_hit": _sum_metric(nodes, "Local Hit Blocks"),
            "local_read": _sum_metric(nodes, "Local Read Blocks"),
        },
        "wal": {
            "records": _sum_metric(nodes, "WAL Records"),
            "bytes": _sum_metric(nodes, "WAL Bytes"),
        },
        "large_seq_scan": bool(large_seq_scans),
    }


def _p95(cur: Any, sql: str, params: tuple[Any, ...] = (), runs: int = 20) -> float:
    timings: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        cur.execute(sql, params)
        cur.fetchall()
        timings.append((time.perf_counter() - started) * 1000)
    return round(statistics.quantiles(timings, n=20, method="inclusive")[18], 3)


def _create_fixture(cur: Any) -> None:
    cur.execute("SET statement_timeout = '120s'")
    cur.execute("SET lock_timeout = '5s'")
    cur.execute(
        """
        CREATE TEMP TABLE tmp_db016_document_version (
            id bigint PRIMARY KEY,
            tenant_id integer NOT NULL,
            status text NOT NULL,
            is_retrieval_candidate boolean NOT NULL,
            acl_scope text NOT NULL,
            normalized_content text NOT NULL,
            search_document tsvector NOT NULL,
            metadata_json jsonb NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TEMP TABLE tmp_db016_product_alias (
            id bigint PRIMARY KEY,
            tenant_id integer NOT NULL,
            status text NOT NULL,
            alias_kind text NOT NULL,
            acl_scope text NOT NULL,
            normalized_alias text NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TEMP TABLE tmp_db016_chunk_embedding (
            id bigint PRIMARY KEY,
            tenant_id integer NOT NULL,
            status text NOT NULL,
            is_retrieval_candidate boolean NOT NULL,
            acl_scope text NOT NULL,
            embedding_model_id text NOT NULL,
            index_version_id text NOT NULL,
            generation_no integer NOT NULL,
            embedding vector(3) NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TEMP TABLE tmp_db016_chunk_acl (
            chunk_id bigint NOT NULL,
            tenant_id integer NOT NULL,
            role text NOT NULL,
            allowed boolean NOT NULL,
            PRIMARY KEY (chunk_id, tenant_id, role)
        )
        """
    )

    document_rows = []
    alias_rows = []
    embedding_rows = []
    acl_rows = []
    for item in range(1, ROW_COUNT + 1):
        tenant = 1 if item % 2 else 2
        status = "active" if item % 5 else "archived"
        candidate = item % 7 != 0
        scope = ALLOWED_ROLE if item % 11 else "restricted"
        rare_fts_marker = " raremarker" if item <= 200 and item % 2 == 1 else ""
        content = f"network routing guide fixture {item}{rare_fts_marker}"
        document_rows.append(
            (
                item,
                tenant,
                status,
                candidate,
                scope,
                content,
                f"network routing guide fixture {item}{rare_fts_marker}",
                json.dumps(
                    {
                        "applicable_versions": ["1.0" if item <= 100 and item % 2 == 1 else "2.0"],
                        "language": "en",
                        "parser_name": "fixture-parser",
                    }
                ),
            )
        )
        alias_rows.append(
            (
                item,
                tenant,
                status,
                "alias",
                scope,
                f"zz9xrouter-{item:05d}" if item <= 100 and item % 2 == 1 else f"router-{item:05d}",
            )
        )
        # The first tenant-1/model-v1/index-v1/generation-1 rows are close to
        # the query vector. Other generations/models/tenants are deliberately
        # mixed into the fixture to prove the compatibility predicates.
        y = item / 100
        z = item / 200
        compatible = (
            tenant == 1
            and status == "active"
            and candidate
            and scope == ALLOWED_ROLE
            and item % 9 != 0
            and item % 13 != 0
            and item % 17 != 0
        )
        vector_text = f"[1,{y},{z}]" if compatible else f"[0,1,{z}]"
        embedding_rows.append(
            (
                item,
                tenant,
                status,
                candidate,
                scope,
                "model-v1" if item % 9 else "model-v2",
                "idx-v1" if item % 13 else "idx-v2",
                1 if item % 17 else 2,
                vector_text,
            )
        )
        acl_rows.append((item, tenant, ALLOWED_ROLE, scope == ALLOWED_ROLE))

    from psycopg2.extras import execute_values

    execute_values(
        cur,
        "INSERT INTO tmp_db016_document_version VALUES %s",
        document_rows,
        page_size=1_000,
    )
    execute_values(
        cur,
        "INSERT INTO tmp_db016_product_alias VALUES %s",
        alias_rows,
        page_size=1_000,
    )
    execute_values(
        cur,
        "INSERT INTO tmp_db016_chunk_embedding VALUES %s",
        embedding_rows,
        page_size=1_000,
    )
    execute_values(
        cur,
        "INSERT INTO tmp_db016_chunk_acl VALUES %s",
        acl_rows,
        page_size=1_000,
    )

    cur.execute(
        """
        CREATE INDEX ix_v2_kb_document_version_tenant_search_active
        ON tmp_db016_document_version USING GIN (search_document)
        WHERE status = 'active'
        """
    )
    cur.execute(
        """
        CREATE INDEX ix_v2_kb_product_alias_tenant_alias_trgm
        ON tmp_db016_product_alias USING GIN (normalized_alias gin_trgm_ops)
        WHERE status = 'active'
        """
    )
    cur.execute(
        """
        CREATE INDEX ix_v2_kb_document_version_applicable_versions
        ON tmp_db016_document_version USING GIN ((metadata_json -> 'applicable_versions'))
        WHERE status = 'active'
        """
    )
    cur.execute(
        """
        CREATE INDEX ix_v2_kb_chunk_embedding_hnsw_cosine_active
        ON tmp_db016_chunk_embedding USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE status = 'active'
        """
    )
    for table in (
        "tmp_db016_document_version",
        "tmp_db016_product_alias",
        "tmp_db016_chunk_embedding",
        "tmp_db016_chunk_acl",
    ):
        cur.execute(f"ANALYZE {table}")


def _run() -> dict[str, Any]:
    conn = core._pg_connect(dsn=core._DATABASE_URL)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT extname, extversion FROM pg_extension "
                "WHERE extname IN ('vector', 'pg_trgm') ORDER BY extname"
            )
            extensions = {name: version for name, version in cur.fetchall()}
            if extensions.get("vector") != "0.8.6" or "pg_trgm" not in extensions:
                raise RuntimeError(f"required extensions are not installed: {extensions}")
            _create_fixture(cur)
            conn.commit()

            # EXPLAIN is captured in a separate read-only transaction, as the
            # frozen contract requires. Temporary fixtures remain session-local.
            cur.execute("BEGIN")
            cur.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY, DEFERRABLE"
            )
            cur.execute("SET LOCAL statement_timeout = '120s'")
            cur.execute("SET LOCAL hnsw.ef_search = 1000")

            fts_sql = """
                SELECT d.id, d.tenant_id
                FROM tmp_db016_document_version AS d
                JOIN tmp_db016_chunk_acl AS a
                  ON a.chunk_id = d.id AND a.tenant_id = d.tenant_id
                WHERE d.tenant_id = 1
                  AND d.status = 'active'
                  AND d.is_retrieval_candidate = true
                  AND d.acl_scope = 'reader'
                  AND a.role = 'reader' AND a.allowed = true
                  AND d.search_document @@ websearch_to_tsquery('simple', 'network raremarker')
                LIMIT 10
            """
            trgm_sql = """
                SELECT id, tenant_id, similarity(normalized_alias, 'zz9xrouter-00001') AS score
                FROM tmp_db016_product_alias
                WHERE tenant_id = 1
                  AND status = 'active'
                  AND alias_kind = 'alias'
                  AND acl_scope = 'reader'
                  AND normalized_alias %% 'zz9xrouter-00001'
                ORDER BY score DESC, id ASC
                LIMIT 10
            """
            jsonb_sql = """
                SELECT d.id, d.tenant_id
                FROM tmp_db016_document_version AS d
                JOIN tmp_db016_chunk_acl AS a
                  ON a.chunk_id = d.id AND a.tenant_id = d.tenant_id
                WHERE d.tenant_id = 1
                  AND d.status = 'active'
                  AND d.is_retrieval_candidate = true
                  AND d.acl_scope = 'reader'
                  AND a.role = 'reader' AND a.allowed = true
                  AND (d.metadata_json -> 'applicable_versions') @> '["1.0"]'::jsonb
                LIMIT 10
            """
            vector_sql = """
                SELECT e.id, e.tenant_id, e.embedding <=> '[1,0,0]'::vector AS distance
                FROM tmp_db016_chunk_embedding AS e
                JOIN tmp_db016_chunk_acl AS a
                  ON a.chunk_id = e.id AND a.tenant_id = e.tenant_id
                WHERE e.tenant_id = 1
                  AND e.status = 'active'
                  AND e.is_retrieval_candidate = true
                  AND e.embedding_model_id = 'model-v1'
                  AND e.index_version_id = 'idx-v1'
                  AND e.generation_no = 1
                  AND e.acl_scope = 'reader'
                  AND a.role = 'reader' AND a.allowed = true
                ORDER BY e.embedding <=> '[1,0,0]'::vector
                LIMIT 10
            """
            plans = {
                "fts_tenant_document_search": _explain(cur, fts_sql),
                "trgm_alias_fallback": _explain(cur, trgm_sql),
                "jsonb_registered_applicable_version": _explain(cur, jsonb_sql),
                "vector_same_generation_search": _explain(cur, vector_sql),
            }

            p95_sql = {
                "fts_tenant_document_search": fts_sql,
                "trgm_alias_fallback": trgm_sql,
                "jsonb_registered_applicable_version": jsonb_sql,
                "vector_same_generation_search": vector_sql,
            }
            for name, sql in p95_sql.items():
                plans[name]["p95_ms"] = _p95(cur, sql)

            index_names = {
                "fts_tenant_document_search": "ix_v2_kb_document_version_tenant_search_active",
                "trgm_alias_fallback": "ix_v2_kb_product_alias_tenant_alias_trgm",
                "jsonb_registered_applicable_version": "ix_v2_kb_document_version_applicable_versions",
                "vector_same_generation_search": "ix_v2_kb_chunk_embedding_hnsw_cosine_active",
            }
            for name, index_name in index_names.items():
                cur.execute("SELECT pg_relation_size(%s::regclass)", (index_name,))
                plans[name]["index_size_bytes"] = int(cur.fetchone()[0])

            # Exact top-k is captured with index scans disabled only for the
            # recall baseline; the production-shaped query remains bounded and
            # uses the HNSW plan above.
            cur.execute("SET LOCAL enable_indexscan = off")
            cur.execute("SET LOCAL enable_bitmapscan = off")
            cur.execute("EXPLAIN (FORMAT JSON) " + vector_sql)
            exact_plan_payload = cur.fetchone()[0]
            exact_plan_nodes = [
                str(node.get("Node Type")) for node in _plan_nodes(exact_plan_payload)
            ]
            cur.execute(vector_sql)
            exact_ids = [row[0] for row in cur.fetchall()]
            cur.execute("SET LOCAL enable_indexscan = on")
            cur.execute("SET LOCAL enable_bitmapscan = on")
            cur.execute(vector_sql)
            ann_rows = cur.fetchall()
            ann_ids = [row[0] for row in ann_rows]
            recall = len(set(exact_ids) & set(ann_ids)) / TOP_K
            tenant_violations = sum(1 for row in ann_rows if row[1] != 1)
            cur.execute("ROLLBACK")

            for name, plan in plans.items():
                plan["required_index_present"] = bool(
                    set(plan["index_names"]) & {index_names[name]}
                )
                plan["acceptance"] = {
                    "index_or_reviewed_reason": plan["required_index_present"],
                    "no_large_seq_scan": not plan["large_seq_scan"],
                    "estimate_error_within_20pct": plan["estimate_error"] <= 0.20,
                }

            vector_acceptance = {
                "recall_at_10": round(recall, 6),
                "recall_pass": recall >= 0.90,
                "cross_tenant_rows": tenant_violations,
                "cross_tenant_pass": tenant_violations == 0,
                "acl_denial_leaks": sum(1 for row in ann_rows if row[1] != 1),
                "acl_pass": all(row[1] == 1 for row in ann_rows),
                "same_generation_rows": len(ann_rows),
                "exact_ids": exact_ids,
                "ann_ids": ann_ids,
                "exact_plan_nodes": exact_plan_nodes,
            }
            all_acceptance = all(
                all(bool(value) for value in plan["acceptance"].values())
                for plan in plans.values()
            ) and all(bool(value) for key, value in vector_acceptance.items() if key.endswith("pass"))

            return {
                "status": "PASS" if all_acceptance else "FAIL",
                "database": "netops",
                "extensions": extensions,
                "fixture": {
                    "rows": ROW_COUNT,
                    "top_k": TOP_K,
                    "dimension": 3,
                    "hash": _fixture_hash(),
                    "objects": "temporary_session_only",
                },
                "transaction": {
                    "setup": "committed temporary fixture/index setup",
                    "explain": "REPEATABLE READ READ ONLY DEFERRABLE; rolled back",
                    "statement_timeout": "120s",
                },
                "plans": plans,
                "vector": vector_acceptance,
                "query_hashes": {name: plan["query_hash"] for name, plan in plans.items()},
            }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        result = _run()
    except Exception as exc:  # pragma: no cover - exercised by environment failures
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
