#!/usr/bin/env python3
"""Run the 400-case retrieval check against a disposable PostgreSQL corpus.

The 400-case source gate proves that the dataset is complete and that every
answer case points to an allow-listed official URL.  This runner measures the
separate retrieval contract using the real RAGRetriever after importing the
checked-in, source-backed local pack into a fresh PostgreSQL database.

The runner never uses the configured application database as its corpus.  It
creates a database whose name is protected by the test prefix, initializes the
normal PostgreSQL schema, imports the pack as an enterprise/test tenant, and
drops that database in ``finally``.  Clarification and security-negative cases
are deliberately not sent to the low-level retriever: they belong to the
Assistant/Security Gateway policy path and have no Gold document by contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_ROOT = ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import database  # noqa: E402
import database.core as database_core  # noqa: E402
import database.schema as database_schema  # noqa: E402
from backend.tests.pg_test_utils import (  # noqa: E402
    capture_database_state,
    close_database_pool,
    create_test_database,
    drop_test_database,
    restore_database_state,
    switch_database,
    validate_test_server_url,
)
from knowledge_eval_gold_400_check import validate_dataset  # noqa: E402


DATASET_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-400.yaml"
PACK_CATALOG = ROOT / "data" / "kb_import" / "source_catalog.yaml"
DEFAULT_OUTPUT = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-400-retrieval.json"
CORE_FEATURES = {
    "vlan",
    "access_port",
    "trunk",
    "ospf",
    "bgp",
    "lacp",
    "acl",
    "ssh",
    "ntp",
    "static_route",
}
VENDORS = {"Huawei", "Cisco", "H3C", "Ruijie"}
QUALITY_THRESHOLDS = {"recall_at_5": 0.95, "recall_at_10": 0.97}


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _case_filters(case: Mapping[str, Any]) -> dict[str, Any]:
    vendor = _text(case.get("vendor"))
    feature = _text(case.get("feature"))
    platform = _text(case.get("platform"))
    return {
        "vendor": vendor if vendor in VENDORS else None,
        "platform": platform if vendor in VENDORS else None,
        "feature": feature if feature in CORE_FEATURES else None,
    }


def _evaluate_cases(cases: list[Mapping[str, Any]], tenant_id: str) -> dict[str, Any]:
    from ai.services.rag_retriever import RAGRetriever

    # The report must describe the imported local corpus, not a process-level
    # cache populated by an earlier application request.
    retriever = RAGRetriever(cache_enabled=False)
    rows: list[dict[str, Any]] = []
    answer_cases = [case for case in cases if _text(case.get("expected_outcome")) == "answer"]
    guard_cases = [case for case in cases if _text(case.get("expected_outcome")) != "answer"]

    for case in answer_cases:
        filters = _case_filters(case)
        expected_ids = _ids(case.get("acceptable_document_ids")) or _ids(case.get("gold_document_ids"))
        started = time.perf_counter()
        returned = retriever.retrieve(
            _text(case.get("query")),
            top_k=10,
            tenant_id=tenant_id,
            knowledge_scope="enterprise",
            **filters,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        returned_ids = [
            _text(item.get("document_id") or item.get("storage_document_id"))
            for item in returned
            if _text(item.get("document_id") or item.get("storage_document_id"))
        ]
        expected_set = set(expected_ids)
        rank = next(
            (index for index, document_id in enumerate(returned_ids, start=1) if document_id in expected_set),
            None,
        )
        returned_vendors = {_text(item.get("vendor")) for item in returned if _text(item.get("vendor"))}
        returned_features = {_text(item.get("feature")) for item in returned if _text(item.get("feature"))}
        target_vendor = _text(case.get("vendor"))
        target_feature = _text(case.get("feature"))
        vendor_isolation_passed = target_vendor not in VENDORS or returned_vendors <= {target_vendor}
        feature_scope_passed = not target_feature or returned_features <= {target_feature}
        rows.append(
            {
                "id": _text(case.get("id")),
                "expected_document_ids": expected_ids,
                "returned_document_ids": returned_ids,
                "hit_at_5": bool(expected_set & set(returned_ids[:5])),
                "hit_at_10": bool(expected_set & set(returned_ids[:10])),
                "mrr": round(1.0 / rank, 4) if rank else 0.0,
                "vendor_isolation_passed": vendor_isolation_passed,
                "feature_scope_passed": feature_scope_passed,
                "latency_ms": round(latency_ms, 4),
            }
        )

    latencies = [float(row["latency_ms"]) for row in rows]
    recall_at_5 = sum(bool(row["hit_at_5"]) for row in rows) / max(1, len(rows))
    recall_at_10 = sum(bool(row["hit_at_10"]) for row in rows) / max(1, len(rows))
    isolation_failures = sum(not bool(row["vendor_isolation_passed"]) for row in rows)
    feature_failures = sum(not bool(row["feature_scope_passed"]) for row in rows)
    metrics = {
        "answer_case_count": len(answer_cases),
        "guard_case_count": len(guard_cases),
        "retrieval_evaluated_case_count": len(rows),
        "recall_at_5": round(recall_at_5, 4),
        "recall_at_10": round(recall_at_10, 4),
        "mean_reciprocal_rank": round(statistics.fmean(float(row["mrr"]) for row in rows), 4) if rows else 0.0,
        "vendor_isolation_failures": isolation_failures,
        "feature_scope_failures": feature_failures,
        "latency_ms": {
            "average": round(statistics.fmean(latencies), 4) if latencies else 0.0,
            "p50": round(_percentile(latencies, 0.50), 4),
            "p95": round(_percentile(latencies, 0.95), 4),
            "max": round(max(latencies), 4) if latencies else 0.0,
        },
    }
    quality_passed = (
        recall_at_5 >= QUALITY_THRESHOLDS["recall_at_5"]
        and recall_at_10 >= QUALITY_THRESHOLDS["recall_at_10"]
        and isolation_failures == 0
        and feature_failures == 0
    )
    return {
        "status": "PASS" if quality_passed else "FAIL",
        "quality_status": "PASS" if quality_passed else "FAIL",
        "metrics": metrics,
        "cases": rows,
        "guard_policy": {
            "evaluated_by": "assistant_security_gateway_required",
            "low_level_retrieval_called": False,
            "expected_outcome_counts": {
                outcome: sum(_text(case.get("expected_outcome")) == outcome for case in guard_cases)
                for outcome in ("clarify", "no_match")
            },
        },
    }


def run() -> dict[str, Any]:
    if not database_core._USE_PG or not database_schema._USE_PG:
        raise RuntimeError("PostgreSQL DATABASE_URL is required")
    dataset = yaml.safe_load(DATASET_PATH.read_text(encoding="utf-8")) or {}
    contract_report = validate_dataset(DATASET_PATH, require_production=True)
    if contract_report.get("status") != "PASS":
        raise RuntimeError("official 400-case source gate is not PASS")
    cases = [item for item in dataset.get("cases") or [] if isinstance(item, Mapping)]
    if len(cases) != 400:
        raise RuntimeError("official 400-case dataset does not contain exactly 400 cases")

    original_state = capture_database_state()
    source_url = database_core._DATABASE_URL
    validate_test_server_url(source_url)
    target = None
    try:
        target = create_test_database(source_url, purpose="gold400_retrieval")
        switch_database(target.url, initialized=False)
        database.init_db()
        close_database_pool()

        from ai.services.knowledge_bundle_import_service import import_knowledge_bundle
        from ai.services.knowledge_service import knowledge_service
        from build_local_knowledge_pack import build_pack

        tenant_id = "tenant-gold-400-retrieval"
        with tempfile.TemporaryDirectory(prefix="nexora_gold400_") as temporary_directory:
            temporary_root = Path(temporary_directory)
            archive_path = temporary_root / "local-pack.zip"
            build_pack(
                catalog_path=PACK_CATALOG,
                source_dir=temporary_root / "source",
                manifest_path=temporary_root / "manifest.json",
                coverage_path=temporary_root / "coverage.json",
                archive_path=archive_path,
            )
            knowledge_base = knowledge_service.create_knowledge_base(
                "Gold 400 isolated retrieval corpus",
                tenant_id=tenant_id,
            )
            imported = import_knowledge_bundle(
                archive_path.read_bytes(),
                tenant_id=tenant_id,
                knowledge_base_id=knowledge_base["id"],
            )
            if imported.get("document_count") != 94:
                raise RuntimeError("local source pack import did not produce 94 documents")
            evaluation = _evaluate_cases(cases, tenant_id)

        return {
            "status": evaluation["status"],
            "quality_status": evaluation["quality_status"],
            "dataset_id": _text(dataset.get("dataset_id")),
            "dataset_sha256": hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest(),
            "source_manifest_sha256": _text((dataset.get("collection") or {}).get("source_manifest_sha256")),
            "database": "PostgreSQL",
            "sqlite": "not_used",
            "external_network": "forbidden",
            "production_database_write": False,
            "corpus": {
                "mode": "isolated_postgresql_local_source_summary",
                "document_count": 94,
                "tenant_scope": "ephemeral_test_tenant",
                "pack_test_only": True,
                "pack_production_eligible": False,
                "official_claims": "downgraded_to_user_document_on_import",
            },
            "thresholds": QUALITY_THRESHOLDS,
            "source_gate": {
                "status": contract_report["status"],
                "human_review_required": contract_report["human_review_required"],
                "official_source_evidence_case_count": contract_report["official_source_evidence_case_count"],
            },
            "metrics": evaluation["metrics"],
            "guard_policy": evaluation["guard_policy"],
            "cases": evaluation["cases"],
            "errors": [],
        }
    finally:
        close_database_pool()
        restore_database_state(original_state)
        if target is not None:
            drop_test_database(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="write the measured report but return success even when retrieval thresholds fail",
    )
    args = parser.parse_args(argv)
    try:
        report = run()
    except Exception as exc:
        report = {
            "status": "NOT_READY",
            "quality_status": "NOT_READY",
            "database": "PostgreSQL",
            "sqlite": "not_used",
            "external_network": "forbidden",
            "production_database_write": False,
            "errors": [type(exc).__name__],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if args.report_only:
        return 0
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
