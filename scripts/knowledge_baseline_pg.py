"""PostgreSQL-only V1 retrieval baseline.

This is the acceptance runner for the V1 retrieval path and is kept separate
from the historical migration/evidence records.
It uses PostgreSQL temporary tables in one session/transaction, invokes the
real V1 RAG retriever, and rolls the fixture back without touching production
rows.
"""

from __future__ import annotations

import json
import statistics
import time
from typing import Any

import yaml

from database.core import _USE_PG, get_db_connection


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
CASE_FILE = ROOT / "docs" / "knowledge-engine" / "eval" / "v1-baseline-cases.yaml"


class _SessionContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, tb):
        return False


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def run() -> dict[str, Any]:
    if not _USE_PG:
        raise SystemExit("V1-PG-BASELINE requires PostgreSQL DATABASE_URL")
    from ai.services import rag_retriever as retriever_module
    from ai.services.rag_retriever import RAGRetriever, RetrievalRequest

    fixture = yaml.safe_load(CASE_FILE.read_text(encoding="utf-8"))
    connection = get_db_connection()
    try:
        connection.execute("BEGIN")
        connection.execute("CREATE TEMP TABLE ai_document (id TEXT PRIMARY KEY, name TEXT, vendor TEXT, platform TEXT, tenant_id TEXT, status TEXT, acl_json JSONB, source_trust_level TEXT, document_id TEXT, document_category TEXT, product_family TEXT, product_series TEXT, product_model TEXT, os_family TEXT, os_generation TEXT, software_train TEXT, software_release TEXT, cli_platform TEXT, feature_domain TEXT, feature TEXT, subfeature TEXT, risk_level TEXT, verification_level TEXT, rag_priority TEXT, exclude_from_rag INTEGER DEFAULT 0, metadata_json JSONB, normalized_content TEXT, source TEXT, version TEXT)")
        connection.execute("CREATE TEMP TABLE ai_document_chunk (id TEXT PRIMARY KEY, document_id TEXT, content TEXT, embedding TEXT, embedding_vector vector(2), metadata_json JSONB, section TEXT, created_at TEXT, is_retrieval_candidate INTEGER, chunk_role TEXT, parent_chunk_id TEXT, ordinal INTEGER, search_text TEXT, embedding_model TEXT, embedding_dimensions INTEGER)")
        for index, document in enumerate(fixture["documents"]):
            metadata = {"vendor": document["vendor"], **(document.get("metadata") or {})}
            document_id = str(document["id"])
            connection.execute(
                "INSERT INTO ai_document (id,name,vendor,platform,tenant_id,status,acl_json,source_trust_level,document_id,document_category,product_series,product_model,software_train,cli_platform,feature_domain,feature,exclude_from_rag,metadata_json,normalized_content) VALUES (?,?,?,?,?,'active','{}'::jsonb,'official',?,?,?,?,?,?,?,?,0,?::jsonb,?)",
                (document_id, document["name"], document["vendor"], document["platform"], "tenant-default", document["name"], document["category"], document.get("series"), document.get("model"), document.get("train"), document["platform"], "routing" if document.get("feature") in {"ospf", "arp"} else "switching", document.get("feature"), json.dumps(metadata, ensure_ascii=False), document["content"]),
            )
            connection.execute(
                "INSERT INTO ai_document_chunk (id,document_id,content,embedding,embedding_vector,metadata_json,section,created_at,is_retrieval_candidate,chunk_role,parent_chunk_id,ordinal,search_text,embedding_model,embedding_dimensions) VALUES (?,?,?, ?,CAST(? AS vector),?::jsonb,'General',?,1,'standalone',NULL,0,?,?,2)",
                (f"chunk-{index}", document_id, document["content"], json.dumps([1.0, 0.0]), "[1,0]", json.dumps(metadata, ensure_ascii=False), f"2026-01-{index + 1:02d}", document["content"], "v1-baseline"),
            )

        retriever_module.get_db_connection = lambda: _SessionContext(connection)
        retriever_module._USE_PG = True
        retriever_module.embedding_provider.embed_text = lambda _text: [1.0, 0.0]
        retriever_module.embedding_provider.embed_query = lambda _text: [1.0, 0.0]
        retriever = RAGRetriever()
        rows: list[dict[str, Any]] = []
        latencies: list[float] = []
        for case in fixture["cases"]:
            request = RetrievalRequest(query=str(case["query"]), top_k=5, **dict(case.get("request") or {}))
            started = time.perf_counter()
            result = retriever.search(request)
            latency_ms = (time.perf_counter() - started) * 1000.0
            latencies.append(latency_ms)
            returned = result.get("results") or []
            returned_ids = [str(item.get("storage_document_id") or item.get("document_id")) for item in returned]
            expected_ids = [str(value) for value in (case.get("expected_ids") or [])]
            returned_set, expected_set = set(returned_ids), set(expected_ids)
            precision = 1.0 if not returned_ids and not expected_ids else (len(returned_set & expected_set) / max(1, len(returned_set)))
            rows.append({"id": case["id"], "query": case["query"], "expected_ids": expected_ids, "returned_ids": returned_ids, "retrieval_correct": returned_set == expected_set, "citation_precision": round(precision, 4), "vendor_mismatch": bool(case.get("expected_vendor") and any(str(item.get("vendor") or "").lower() != str(case["expected_vendor"]).lower() for item in returned)), "version_conflict": bool(case.get("expected_platforms") and any(str(item.get("platform") or "") not in set(map(str, case["expected_platforms"])) for item in returned)), "latency_ms": round(latency_ms, 4)})
        vendor_cases = [row for row in rows if any(case["id"] == row["id"] and case.get("expected_vendor") for case in fixture["cases"])]
        version_cases = [row for row in rows if any(case["id"] == row["id"] and case.get("expected_platforms") for case in fixture["cases"])]
        return {"baseline_id": fixture["baseline_id"], "system_under_test": fixture["system_under_test"], "database": "PostgreSQL", "case_count": len(rows), "metrics": {"retrieval_accuracy": round(sum(bool(row["retrieval_correct"]) for row in rows) / max(1, len(rows)), 4), "wrong_vendor_rate": round(sum(bool(row["vendor_mismatch"]) for row in vendor_cases) / max(1, len(vendor_cases)), 4), "version_conflict_rate": round(sum(bool(row["version_conflict"]) for row in version_cases) / max(1, len(version_cases)), 4), "citation_accuracy": round(statistics.fmean(float(row["citation_precision"]) for row in rows), 4), "latency_ms": {"average": round(statistics.fmean(latencies), 4), "p50": round(_percentile(latencies, 0.5), 4), "p95": round(_percentile(latencies, 0.95), 4), "max": round(max(latencies), 4)}}, "cases": rows, "external_network_call": False, "production_database_write": False, "rollback": "transaction_rollback"}
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
