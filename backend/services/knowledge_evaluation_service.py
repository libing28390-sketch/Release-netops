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
CASE_FILE = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "v1-baseline-cases.yaml"
SUITE_ID = "v1_baseline_postgresql"
CONTRACT_VERSION = "kui-016-v1"
MAX_CASES = 200

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


def _project_case(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project a runner row without exposing ids, SQL, bodies, or debug data."""

    query = str(row.get("query") or "")[:256]
    return {
        "id": str(row.get("id") or "")[:128],
        "query": query,
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
        runner_path = ROOT / "scripts" / "knowledge_engine_v2_v1_baseline_pg.py"
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
    original = {
        "get_db_connection": retriever_module.get_db_connection,
        "use_pg": retriever_module._USE_PG,
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
    "KnowledgeEvaluationError",
    "SUITE_ID",
    "get_evaluation_report",
    "run_evaluation",
]
