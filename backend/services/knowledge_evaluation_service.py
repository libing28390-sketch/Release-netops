"""Tenant-safe, PostgreSQL-authoritative Knowledge Engine evaluation read model.

The KUI surface intentionally evaluates the fixed V1 compatibility set in a
temporary PostgreSQL transaction.  It never writes production rows and never
returns raw SQL, chunk bodies, debug plans, expected document ids, or provider
data to the administrator UI.
"""

from __future__ import annotations

import math
import importlib.util
import threading
import time
from pathlib import Path
from typing import Any, Mapping


class KnowledgeEvaluationError(Exception):
    """Stable, redacted errors exposed by the evaluation API."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


ROOT = Path(__file__).resolve().parents[2]
CASE_FILE = ROOT / "docs" / "knowledge-engine" / "eval" / "v1-baseline-cases.yaml"
GOLD_400_CASE_FILE = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-400.yaml"
SUITE_ID = "v1_baseline_postgresql"
CONTRACT_VERSION = "kui-016-v1"
MAX_CASES = 200
GOLD_400_CASE_COUNT = 400
MAX_FIXTURE_FILE_BYTES = 2 * 1024 * 1024

# These are deliberately hard-coded release gates.  Changing a threshold is
# an architecture/release decision, not a frontend setting.
THRESHOLDS: dict[str, dict[str, Any]] = {
    "retrieval_accuracy": {"operator": ">=", "threshold": 0.95},
    "wrong_vendor_rate": {"operator": "<=", "threshold": 0.01},
    "version_conflict_rate": {"operator": "<=", "threshold": 0.01},
    "citation_accuracy": {"operator": ">=", "threshold": 0.95},
    "citation_recall": {"operator": ">=", "threshold": 0.95},
}

_RUN_LOCK = threading.Lock()
_LAST_REPORT: dict[str, Any] | None = None


def _finite_number(value: Any, default: float = 0.0) -> float:
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return default
    return round(candidate, 4) if math.isfinite(candidate) else default


def _load_case_catalog() -> dict[str, Any]:
    if not CASE_FILE.exists():
        raise KnowledgeEvaluationError("EVAL_DATASET_NOT_CONFIGURED", "Evaluation dataset is not configured", 503)
    try:
        import yaml

        payload = yaml.safe_load(CASE_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - dependency/startup failure
        raise KnowledgeEvaluationError("EVAL_DATASET_UNAVAILABLE", "Evaluation dataset is unavailable", 503) from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("cases"), list):
        raise KnowledgeEvaluationError("EVAL_DATASET_INVALID", "Evaluation dataset is invalid", 503)
    cases = payload.get("cases") or []
    if len(cases) > MAX_CASES:
        raise KnowledgeEvaluationError("EVAL_DATASET_TOO_LARGE", "Evaluation dataset exceeds the supported limit", 503)
    # Only aggregate, non-sensitive dataset facts are returned before a run.
    domains: set[str] = set()
    for item in cases:
        if not isinstance(item, Mapping):
            raise KnowledgeEvaluationError("EVAL_DATASET_INVALID", "Evaluation dataset is invalid", 503)
        for value in item.get("tags") or item.get("topics") or []:
            if isinstance(value, str) and value.strip():
                domains.add(value.strip()[:64])
    return {
        "baseline_id": str(payload.get("baseline_id") or "v1-baseline")[:128],
        "case_count": len(cases),
        "domains": sorted(domains)[:32],
        "database": "PostgreSQL",
    }


def _fixture_bucket_counts(cases: list[Mapping[str, Any]], field: str, *, unknown_key: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in cases:
        raw_value = item.get(field)
        value = str(raw_value).strip()[:64] if isinstance(raw_value, str) and raw_value.strip() else unknown_key
        counts[value] = counts.get(value, 0) + 1
    return [
        {"key": key, "count": count}
        for key, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def get_gold_400_fixture_summary(user: Mapping[str, Any]) -> dict[str, Any]:
    """Return only safe aggregate metadata for the official-source 400-case fixture.

    This endpoint is deliberately not a case browser.  The fixture contains
    generated prompts, answers, expected document identities, and review
    metadata; none of those fields may be exposed to the tenant UI.  The
    summary reports source provenance and coverage, not retrieval quality.
    """

    del user  # Permission is enforced by the API dependency; the file is not tenant data.
    if not GOLD_400_CASE_FILE.exists():
        raise KnowledgeEvaluationError("EVAL_GOLD_400_NOT_CONFIGURED", "400-case evaluation fixture is not configured", 503)
    try:
        if GOLD_400_CASE_FILE.stat().st_size > MAX_FIXTURE_FILE_BYTES:
            raise KnowledgeEvaluationError("EVAL_GOLD_400_TOO_LARGE", "400-case evaluation fixture exceeds the supported limit", 503)
        import yaml

        payload = yaml.safe_load(GOLD_400_CASE_FILE.read_text(encoding="utf-8")) or {}
    except KnowledgeEvaluationError:
        raise
    except Exception as exc:  # pragma: no cover - dependency/filesystem failure
        raise KnowledgeEvaluationError("EVAL_GOLD_400_UNAVAILABLE", "400-case evaluation fixture is unavailable", 503) from exc

    if not isinstance(payload, Mapping) or not isinstance(payload.get("cases"), list):
        raise KnowledgeEvaluationError("EVAL_GOLD_400_INVALID", "400-case evaluation fixture is invalid", 503)
    cases = [item for item in payload["cases"] if isinstance(item, Mapping)]
    if len(cases) != len(payload["cases"]) or len(cases) != GOLD_400_CASE_COUNT:
        raise KnowledgeEvaluationError("EVAL_GOLD_400_INVALID", "400-case evaluation fixture does not contain exactly 400 cases", 503)
    if payload.get("case_count") != GOLD_400_CASE_COUNT:
        raise KnowledgeEvaluationError("EVAL_GOLD_400_INVALID", "400-case evaluation fixture count metadata is invalid", 503)
    if not isinstance(payload.get("test_only"), bool) or not isinstance(payload.get("synthetic_data"), bool):
        raise KnowledgeEvaluationError("EVAL_GOLD_400_POLICY_INVALID", "400-case dataset policy flags are invalid", 503)

    source_policy = payload.get("source_policy") if isinstance(payload.get("source_policy"), Mapping) else {}
    if source_policy.get("official_sources") != "required" or source_policy.get("source_collection") != "official_url_backed_local_summary":
        raise KnowledgeEvaluationError("EVAL_GOLD_400_POLICY_INVALID", "400-case dataset is not official-source-backed", 503)
    collection = payload.get("collection") if isinstance(payload.get("collection"), Mapping) else {}
    if (
        collection.get("mode") != "official_url_backed_local_summary"
        or not str(collection.get("source_manifest") or "").strip()
        or not str(collection.get("source_manifest_sha256") or "").strip()
    ):
        raise KnowledgeEvaluationError("EVAL_GOLD_400_POLICY_INVALID", "400-case source manifest metadata is invalid", 503)
    review_policy = payload.get("review_policy") if isinstance(payload.get("review_policy"), Mapping) else {}
    return {
        "dataset_id": str(payload.get("dataset_id") or "nexora-kb-eval-gold-400")[:128],
        "status": str(payload.get("status") or "unknown")[:32],
        "purpose": str(payload.get("purpose") or "Official-source-backed automated evaluation dataset")[:160],
        "test_only": bool(payload.get("test_only")),
        "synthetic_data": bool(payload.get("synthetic_data")),
        "production_eligible": bool(payload.get("production_eligible")),
        "production_gate": "READY" if payload.get("production_eligible") is True else "NOT_READY",
        "case_count": GOLD_400_CASE_COUNT,
        "database": "PostgreSQL",
        "collection": {
            "mode": str(collection.get("mode") or "unknown")[:96],
            "source_manifest": str(collection.get("source_manifest") or "")[:160],
            "source_manifest_sha256": str(collection.get("source_manifest_sha256") or "")[:128],
            "collected_at": str(collection.get("collected_at") or "")[:32],
            "content_origin": str(collection.get("content_origin") or "")[:128],
        },
        "source_policy": {
            "database": str(source_policy.get("database") or "PostgreSQL")[:32],
            "sqlite": str(source_policy.get("sqlite") or "not_used")[:32],
            "external_network": str(source_policy.get("external_network") or "forbidden")[:32],
            "secrets": str(source_policy.get("secrets") or "forbidden")[:32],
            "production_data": str(source_policy.get("production_data") or "forbidden")[:32],
            "official_sources": str(source_policy.get("official_sources") or "required")[:32],
            "source_collection": str(source_policy.get("source_collection") or "official_url_backed_local_summary")[:64],
        },
        "coverage": {
            "categories": _fixture_bucket_counts(cases, "category", unknown_key="unknown"),
            "vendors": _fixture_bucket_counts(cases, "vendor", unknown_key="cross_vendor_or_unknown"),
            "splits": _fixture_bucket_counts(cases, "split", unknown_key="unspecified"),
        },
        "review": {
            "mode": str(review_policy.get("review_mode") or "unknown")[:96],
            "minimum_double_review_cases": int(review_policy.get("minimum_double_review_cases") or 0),
            "human_review_required": bool(review_policy.get("human_review_required")),
            "human_review_ready": not bool(review_policy.get("human_review_required")),
        },
        "redacted": True,
        "contains_case_content": False,
    }


def _project_case(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project a runner row without exposing ids, SQL, bodies, or debug data."""

    return {
        "id": str(row.get("id") or "")[:128],
        "retrieval_correct": bool(row.get("retrieval_correct")),
        "citation_precision": _finite_number(row.get("citation_precision")),
        "vendor_mismatch": bool(row.get("vendor_mismatch")),
        "version_conflict": bool(row.get("version_conflict")),
        "latency_ms": _finite_number(row.get("latency_ms")),
    }


def _citation_recall(rows: list[Mapping[str, Any]]) -> float:
    values: list[float] = []
    for row in rows:
        expected = {str(value) for value in (row.get("expected_ids") or [])}
        returned = {str(value) for value in (row.get("returned_ids") or [])}
        if not expected:
            values.append(1.0 if not returned else 0.0)
        else:
            values.append(len(expected & returned) / max(1, len(expected)))
    return round(sum(values) / max(1, len(values)), 4)


def _gate_results(metrics: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    checks: list[dict[str, Any]] = []
    all_passed = True
    for key, definition in THRESHOLDS.items():
        actual = _finite_number(metrics.get(key))
        threshold = float(definition["threshold"])
        passed = actual >= threshold if definition["operator"] == ">=" else actual <= threshold
        all_passed = all_passed and passed
        checks.append({
            "metric": key,
            "actual": actual,
            "operator": definition["operator"],
            "threshold": threshold,
            "passed": passed,
        })
    return checks, all_passed


def _project_report(raw: Mapping[str, Any], *, tenant_id: str, started_at: float, duration_ms: float) -> dict[str, Any]:
    raw_rows = raw.get("cases") if isinstance(raw.get("cases"), list) else []
    rows = [_project_case(item) for item in raw_rows[:MAX_CASES] if isinstance(item, Mapping)]
    raw_metrics = raw.get("metrics") if isinstance(raw.get("metrics"), Mapping) else {}
    metrics = {
        "retrieval_accuracy": _finite_number(raw_metrics.get("retrieval_accuracy")),
        "wrong_vendor_rate": _finite_number(raw_metrics.get("wrong_vendor_rate")),
        "version_conflict_rate": _finite_number(raw_metrics.get("version_conflict_rate")),
        "citation_accuracy": _finite_number(raw_metrics.get("citation_accuracy")),
        "citation_recall": _finite_number(raw_metrics.get("citation_recall"), _citation_recall(raw_rows)),
    }
    raw_latency = raw_metrics.get("latency_ms") if isinstance(raw_metrics.get("latency_ms"), Mapping) else {}
    metrics["latency_ms"] = {
        "average": _finite_number(raw_latency.get("average")),
        "p50": _finite_number(raw_latency.get("p50")),
        "p95": _finite_number(raw_latency.get("p95")),
        "max": _finite_number(raw_latency.get("max")),
    }
    checks, passed = _gate_results(metrics)
    return {
        "contract_version": CONTRACT_VERSION,
        "suite": SUITE_ID,
        "status": "passed" if passed else "failed",
        "tenant_id": tenant_id,
        "baseline_id": str(raw.get("baseline_id") or "")[:128],
        "system_under_test": str(raw.get("system_under_test") or "current-local-rag-retrieval-path")[:128],
        "database": "PostgreSQL",
        "execution_mode": "temporary_transaction",
        "production_database_write": False,
        "external_network_call": False,
        "rollback": "transaction_rollback",
        "case_count": len(rows),
        "metrics": metrics,
        "gates": checks,
        "cases": rows,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at)),
        "duration_ms": round(max(0.0, duration_ms), 2),
    }


def get_evaluation_report(user: Mapping[str, Any], *, include_cases: bool = True) -> dict[str, Any]:
    """Return the last in-process PostgreSQL evaluation, or a safe empty state."""

    tenant_id = str(user.get("tenant_id") or "tenant-default")[:128]
    catalog = _load_case_catalog()
    report = dict(_LAST_REPORT) if _LAST_REPORT else None
    if report is not None:
        report["tenant_id"] = tenant_id
        if not include_cases:
            report["cases"] = []
        return report
    return {
        "contract_version": CONTRACT_VERSION,
        "suite": SUITE_ID,
        "status": "not_run",
        "tenant_id": tenant_id,
        "baseline_id": catalog["baseline_id"],
        "system_under_test": "current-local-rag-retrieval-path",
        "database": "PostgreSQL",
        "execution_mode": "temporary_transaction",
        "production_database_write": False,
        "external_network_call": False,
        "rollback": "transaction_rollback",
        "case_count": catalog["case_count"],
        "dataset": catalog,
        "thresholds": THRESHOLDS,
        "metrics": None,
        "gates": [],
        "cases": [],
        "last_run": None,
    }


def _run_postgresql_baseline() -> dict[str, Any]:
    """Run the existing authoritative PG probe while restoring process globals."""

    try:
        runner_path = ROOT / "scripts" / "knowledge_baseline_pg.py"
        spec = importlib.util.spec_from_file_location("nexora_kui016_pg_baseline", runner_path)
        if spec is None or spec.loader is None:
            raise ImportError("evaluation runner spec unavailable")
        runner_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner_module)
        run_baseline = runner_module.run
    except Exception as exc:  # pragma: no cover - startup/import failure
        raise KnowledgeEvaluationError("EVAL_RUNNER_UNAVAILABLE", "PostgreSQL evaluation runner is unavailable", 503) from exc

    import ai.services.rag_retriever as retriever_module

    had_embed_query = hasattr(retriever_module.embedding_provider, "embed_query")
    missing = object()
    original_use_pg = getattr(retriever_module, "_USE_PG", missing)
    original = {
        "get_db_connection": retriever_module.get_db_connection,
        "use_pg": original_use_pg,
        "embed_text": retriever_module.embedding_provider.embed_text,
        "embed_query": getattr(retriever_module.embedding_provider, "embed_query", None),
    }
    try:
        return run_baseline()
    except SystemExit as exc:
        raise KnowledgeEvaluationError("EVAL_POSTGRES_REQUIRED", "PostgreSQL evaluation is unavailable", 503) from exc
    except KnowledgeEvaluationError:
        raise
    except Exception as exc:
        raise KnowledgeEvaluationError("EVAL_RUN_FAILED", "PostgreSQL evaluation failed", 503) from exc
    finally:
        retriever_module.get_db_connection = original["get_db_connection"]
        if original["use_pg"] is missing:
            try:
                delattr(retriever_module, "_USE_PG")
            except AttributeError:
                pass
        else:
            retriever_module._USE_PG = original["use_pg"]
        retriever_module.embedding_provider.embed_text = original["embed_text"]
        if had_embed_query:
            retriever_module.embedding_provider.embed_query = original["embed_query"]
        elif hasattr(retriever_module.embedding_provider, "embed_query"):
            delattr(retriever_module.embedding_provider, "embed_query")


def run_evaluation(user: Mapping[str, Any]) -> dict[str, Any]:
    """Execute the bounded PG baseline and retain only its safe projection."""

    global _LAST_REPORT
    tenant_id = str(user.get("tenant_id") or "tenant-default")[:128]
    with _RUN_LOCK:
        started = time.time()
        raw = _run_postgresql_baseline()
        report = _project_report(raw, tenant_id=tenant_id, started_at=started, duration_ms=(time.time() - started) * 1000.0)
        _LAST_REPORT = report
        return dict(report)


__all__ = [
    "CONTRACT_VERSION",
    "GOLD_400_CASE_COUNT",
    "KnowledgeEvaluationError",
    "SUITE_ID",
    "get_gold_400_fixture_summary",
    "get_evaluation_report",
    "run_evaluation",
]
