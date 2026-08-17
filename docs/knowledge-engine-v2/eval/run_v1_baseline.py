"""Historical compatibility runner for the V1 retrieval baseline.

Project acceptance no longer uses this SQLite fixture.  Use
``scripts/knowledge_engine_v2_v1_baseline_pg.py`` for the authoritative
PostgreSQL temporary-table/transaction baseline.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
CASE_FILE = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "v1-baseline-cases.yaml"
RESULT_FILE = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "v1-baseline-results.json"


def _fixture_connection(documents: list[dict[str, Any]]) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY, name TEXT, vendor TEXT, platform TEXT,
            tenant_id TEXT, status TEXT, acl_json TEXT, source_trust_level TEXT,
            document_id TEXT, document_category TEXT, product_family TEXT,
            product_series TEXT, product_model TEXT, os_family TEXT,
            os_generation TEXT, software_train TEXT, software_release TEXT,
            cli_platform TEXT, feature_domain TEXT, feature TEXT,
            subfeature TEXT, risk_level TEXT, verification_level TEXT,
            rag_priority TEXT, exclude_from_rag INTEGER DEFAULT 0,
            metadata_json TEXT, normalized_content TEXT
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY, document_id TEXT, content TEXT, embedding TEXT,
            metadata_json TEXT, section TEXT, created_at TEXT,
            is_retrieval_candidate INTEGER, chunk_role TEXT, parent_chunk_id TEXT,
            ordinal INTEGER
        );
        """
    )
    for index, document in enumerate(documents):
        metadata = {"vendor": document["vendor"], **(document.get("metadata") or {})}
        document_id = str(document["id"])
        connection.execute(
            """INSERT INTO ai_document
            (id, name, vendor, platform, tenant_id, status, acl_json,
             source_trust_level, document_id, document_category, product_series,
             product_model, software_train, cli_platform, feature_domain, feature,
             exclude_from_rag, metadata_json, normalized_content)
            VALUES (?, ?, ?, ?, 'tenant-default', 'active', '{}', 'official',
                    ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (
                document_id,
                document["name"],
                document["vendor"],
                document["platform"],
                document["name"],
                document["category"],
                document.get("series"),
                document.get("model"),
                document.get("train"),
                document["platform"],
                "routing" if document.get("feature") in {"ospf", "arp"} else "switching",
                document.get("feature"),
                json.dumps(metadata, ensure_ascii=False),
                document["content"],
            ),
        )
        connection.execute(
            """INSERT INTO ai_document_chunk
               (id, document_id, content, embedding, metadata_json, section,
                created_at, is_retrieval_candidate, chunk_role, parent_chunk_id, ordinal)
               VALUES (?, ?, ?, ?, ?, 'General', ?, 1, 'standalone', NULL, 0)""",
            (
                f"chunk-{index}",
                document_id,
                document["content"],
                json.dumps([1.0, 0.0]),
                json.dumps(metadata, ensure_ascii=False),
                f"2026-01-{index + 1:02d}",
            ),
        )
    connection.commit()
    return connection


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def run() -> dict[str, Any]:
    from ai.services import rag_retriever as retriever_module
    from ai.services.rag_retriever import RAGRetriever, RetrievalRequest

    with CASE_FILE.open("r", encoding="utf-8") as handle:
        fixture = yaml.safe_load(handle)
    connection = _fixture_connection(fixture["documents"])
    # Patch only this process. The real retriever, SQL filtering, scoring and
    # document deduplication remain under test; no external embedding is used.
    retriever_module.get_db_connection = lambda: connection
    retriever_module._USE_PG = False
    retriever_module.embedding_provider.embed_text = lambda _text: [1.0, 0.0]

    retriever = RAGRetriever()
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    for case in fixture["cases"]:
        request = RetrievalRequest(
            query=str(case["query"]),
            top_k=5,
            **dict(case.get("request") or {}),
        )
        started = time.perf_counter()
        result = retriever.search(request)
        latency_ms = (time.perf_counter() - started) * 1000.0
        latencies.append(latency_ms)
        returned = result.get("results") or []
        returned_ids = [str(item.get("storage_document_id") or item.get("document_id")) for item in returned]
        expected_ids = [str(value) for value in (case.get("expected_ids") or [])]
        expected_set = set(expected_ids)
        returned_set = set(returned_ids)
        exact = returned_set == expected_set
        if not expected_ids:
            citation_precision = 1.0 if not returned_ids else 0.0
        else:
            citation_precision = len(returned_set & expected_set) / max(1, len(returned_set))
        expected_vendor = case.get("expected_vendor")
        vendor_mismatch = bool(
            expected_vendor
            and any(str(item.get("vendor") or "").lower() != str(expected_vendor).lower() for item in returned)
        )
        expected_platforms = {str(value) for value in (case.get("expected_platforms") or [])}
        version_conflict = bool(
            expected_platforms
            and any(str(item.get("platform") or "") not in expected_platforms for item in returned)
        )
        rows.append(
            {
                "id": case["id"],
                "query": case["query"],
                "expected_ids": expected_ids,
                "returned_ids": returned_ids,
                "retrieval_correct": exact,
                "citation_precision": round(citation_precision, 4),
                "vendor_mismatch": vendor_mismatch,
                "version_conflict": version_conflict,
                "latency_ms": round(latency_ms, 4),
                "debug": result.get("debug") or {},
            }
        )

    vendor_cases = [row for row in rows if any(case["id"] == row["id"] and case.get("expected_vendor") for case in fixture["cases"])]
    version_cases = [row for row in rows if any(case["id"] == row["id"] and case.get("expected_platforms") for case in fixture["cases"])]
    result = {
        "baseline_id": fixture["baseline_id"],
        "system_under_test": fixture["system_under_test"],
        "case_count": len(rows),
        "metrics": {
            "retrieval_accuracy": round(sum(bool(row["retrieval_correct"]) for row in rows) / max(1, len(rows)), 4),
            "wrong_vendor_rate": round(sum(bool(row["vendor_mismatch"]) for row in vendor_cases) / max(1, len(vendor_cases)), 4),
            "version_conflict_rate": round(sum(bool(row["version_conflict"]) for row in version_cases) / max(1, len(version_cases)), 4),
            "citation_accuracy": round(statistics.fmean(float(row["citation_precision"]) for row in rows), 4),
            "citation_recall": round(
                statistics.fmean(
                    1.0
                    if not row["expected_ids"] and not row["returned_ids"]
                    else len(set(row["expected_ids"]) & set(row["returned_ids"])) / max(1, len(set(row["expected_ids"])))
                    for row in rows
                ),
                4,
            ),
            "latency_ms": {
                "average": round(statistics.fmean(latencies), 4),
                "p50": round(_percentile(latencies, 0.50), 4),
                "p95": round(_percentile(latencies, 0.95), 4),
                "max": round(max(latencies), 4),
            },
        },
        "cases": rows,
        "external_network_call": False,
        "production_database_write": False,
    }
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    value = run()
    print(json.dumps({"baseline_id": value["baseline_id"], "case_count": value["case_count"], "metrics": value["metrics"]}, ensure_ascii=False, indent=2))
