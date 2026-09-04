"""Tenant-scoped persistence for evaluation runs, rollouts, and Shadow data.

Only bounded metadata and document identities are accepted here.  Prompts,
answers, CLI output, chunk bodies, tool parameters, and raw request IDs are
deliberately rejected so observability cannot become a second content store.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from database.core import get_db_connection

try:  # pragma: no cover - psycopg2 is a production dependency
    from psycopg2.extras import Json
except ImportError:  # pragma: no cover
    Json = None  # type: ignore[assignment,misc]


_COMPONENT_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,160}$")
_SECRET_MARKER_RE = re.compile(
    r"(?i)(?:password|passwd|secret|api[_ -]?key|authorization|bearer|snmp[_ -]?community|private key|database[_ -]?url|postgres(?:ql)?://|token\s*[:=])"
)
_FORBIDDEN_KEY_MARKERS = (
    "prompt",
    "answer",
    "content",
    "chunk",
    "cli_output",
    "tool_arg",
    "request_body",
    "raw",
    "secret",
    "password",
    "community",
    "private_key",
    "query",
    "response",
    "username",
    "ip_address",
    "mac_address",
)
_METRIC_KEYS = frozenset(
    {
        "recall_at_5",
        "recall_at_10",
        "mrr",
        "ndcg",
        "citation_precision",
        "citation_recall",
        "wrong_vendor_rate",
        "feature_pollution_rate",
        "latency_ms",
        "error_rate",
        "error_count",
        "rank_delta",
        "baseline_rank",
        "candidate_rank",
        "baseline_candidate_count",
        "candidate_count",
        "timeout_ms",
        "fallback_count",
    }
)
_ROLLOUT_MODES = frozenset({"disabled", "shadow", "active", "degraded", "failed"})
_SHADOW_STATUSES = frozenset({"observed", "timeout", "degraded", "failed"})


class ExperimentPersistenceError(RuntimeError):
    """Stable error for invalid or conflicting experiment state."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _text(value: Any, *, field: str, maximum: int = 256, required: bool = True) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{field} is required")
    if len(result) > maximum:
        raise ValueError(f"{field} is too long")
    if _SECRET_MARKER_RE.search(result):
        raise ValueError(f"{field} contains prohibited secret markers")
    return result


def _code(value: Any, *, field: str, maximum: int = 160, required: bool = True) -> str:
    result = _text(value, field=field, maximum=maximum, required=required)
    if result and not _SAFE_CODE_RE.fullmatch(result):
        raise ValueError(f"{field} contains unsupported characters")
    return result


def _component(value: Any) -> str:
    component = _code(value, field="component", maximum=64)
    if not _COMPONENT_RE.fullmatch(component):
        raise ValueError("component contains unsupported characters")
    return component


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        bounded: Any = _safe_mapping(value)
    elif isinstance(value, (list, tuple)):
        bounded = list(value)
    else:
        raise ValueError("JSON evidence must be an object or list")
    if Json is not None:
        return Json(bounded, dumps=lambda item: json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    return json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))


def _safe_mapping(value: Mapping[str, Any] | None, *, depth: int = 0) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("metadata must be an object")
    if depth > 2 or len(value) > 64:
        raise ValueError("metadata is too large")
    result: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()[:64]
        if not key or any(marker in key.casefold() for marker in _FORBIDDEN_KEY_MARKERS):
            raise ValueError("metadata contains a prohibited field")
        if isinstance(raw_value, Mapping):
            result[key] = _safe_mapping(raw_value, depth=depth + 1)
        elif isinstance(raw_value, (list, tuple)):
            if len(raw_value) > 64:
                raise ValueError("metadata list is too large")
            items: list[Any] = []
            for item in raw_value:
                if isinstance(item, Mapping):
                    items.append(_safe_mapping(item, depth=depth + 1))
                elif isinstance(item, (str, int, float, bool)) or item is None:
                    if isinstance(item, str) and _SECRET_MARKER_RE.search(item):
                        raise ValueError("metadata contains a prohibited value")
                    items.append(str(item)[:256] if isinstance(item, str) else item)
                else:
                    raise ValueError("metadata contains an unsupported value")
            result[key] = items
        elif isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
            if isinstance(raw_value, str):
                if _SECRET_MARKER_RE.search(raw_value):
                    raise ValueError("metadata contains a prohibited value")
                result[key] = raw_value[:512]
            else:
                result[key] = raw_value
        else:
            raise ValueError("metadata contains an unsupported value")
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 64_000:
        raise ValueError("metadata is too large")
    return result


def _safe_metrics(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        data: Mapping[str, Any] = {}
    elif not isinstance(value, Mapping):
        raise ValueError("metrics must be an object")
    else:
        data = value
    unknown = {str(key) for key in data if str(key) not in _METRIC_KEYS}
    if unknown:
        raise ValueError(f"unsupported metric fields: {sorted(unknown)}")
    result: dict[str, Any] = {}
    for key, raw_value in data.items():
        if raw_value is None or isinstance(raw_value, bool):
            result[str(key)] = raw_value
        elif isinstance(raw_value, (int, float)):
            if isinstance(raw_value, float) and (raw_value != raw_value or abs(raw_value) == float("inf")):
                raise ValueError("metric must be finite")
            result[str(key)] = raw_value
        else:
            raise ValueError("metric values must be numeric or null")
    return result


def _safe_ids(values: Sequence[Any] | None, *, field: str, maximum: int = 100) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set)):
        raise ValueError(f"{field} must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values)[:maximum]:
        item = _code(value, field=field, maximum=256)
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _row_value(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return row[index]


def _row_to_dict(row: Any, columns: Sequence[str]) -> dict[str, Any]:
    if row is None:
        return {}
    return {column: _row_value(row, column, index) for index, column in enumerate(columns)}


def _require_pg() -> None:
    """Fail closed if a caller tries to use DATA-001 without PostgreSQL."""

    from database import _USE_PG

    if not _USE_PG:
        raise ExperimentPersistenceError("AI experiment persistence requires PostgreSQL")


def create_experiment_run(
    *,
    tenant_id: str,
    dataset_id: str,
    git_sha: str,
    prompt_version: str,
    parser_version: str,
    chunker_config_hash: str,
    embedding_model: str,
    embedding_dimensions: int,
    distance_algorithm: str,
    reranker_version: str,
    provider_model: str,
    created_by: str,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a deterministic experiment manifest without storing prompts."""

    _require_pg()
    tenant = _code(tenant_id, field="tenant_id", maximum=128)
    values = {
        "dataset_id": _code(dataset_id, field="dataset_id"),
        "git_sha": _code(git_sha, field="git_sha", maximum=80),
        "prompt_version": _code(prompt_version, field="prompt_version"),
        "parser_version": _code(parser_version, field="parser_version"),
        "chunker_config_hash": _code(chunker_config_hash, field="chunker_config_hash", maximum=128),
        "embedding_model": _code(embedding_model, field="embedding_model"),
        "embedding_dimensions": max(0, int(embedding_dimensions)),
        "distance_algorithm": _code(distance_algorithm, field="distance_algorithm"),
        "reranker_version": _code(reranker_version, field="reranker_version"),
        "provider_model": _code(provider_model, field="provider_model"),
        "created_by": _code(created_by, field="created_by", maximum=128),
    }
    run_id = f"exp_{uuid.uuid4().hex[:20]}"
    now = _now()
    safe_config = _safe_mapping(config)
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_experiment_run
                (id, tenant_id, dataset_id, git_sha, prompt_version, parser_version,
                 chunker_config_hash, embedding_model, embedding_dimensions,
                 distance_algorithm, reranker_version, provider_model, status,
                 metrics_json, config_json, created_by, updated_by, version,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', '{}'::jsonb, ?, ?, ?, 1, ?, ?)
            """,
            (
                run_id,
                tenant,
                values["dataset_id"],
                values["git_sha"],
                values["prompt_version"],
                values["parser_version"],
                values["chunker_config_hash"],
                values["embedding_model"],
                values["embedding_dimensions"],
                values["distance_algorithm"],
                values["reranker_version"],
                values["provider_model"],
                _json_value(safe_config),
                values["created_by"],
                values["created_by"],
                now,
                now,
            ),
        )
        conn.commit()
    return get_experiment_run(run_id=run_id, tenant_id=tenant)


_RUN_COLUMNS = (
    "id", "tenant_id", "dataset_id", "git_sha", "prompt_version", "parser_version",
    "chunker_config_hash", "embedding_model", "embedding_dimensions",
    "distance_algorithm", "reranker_version", "provider_model", "status",
    "metrics_json", "config_json", "created_by", "updated_by", "version",
    "created_at", "updated_at", "started_at", "finished_at",
)


def get_experiment_run(*, run_id: str, tenant_id: str) -> dict[str, Any] | None:
    _require_pg()
    run = _code(run_id, field="run_id", maximum=128)
    tenant = _code(tenant_id, field="tenant_id", maximum=128)
    with get_db_connection() as conn:
        row = conn.execute(
            f"SELECT {', '.join(_RUN_COLUMNS)} FROM ai_experiment_run WHERE id = ? AND tenant_id = ?",
            (run, tenant),
        ).fetchone()
    return _row_to_dict(row, _RUN_COLUMNS) if row else None


def _stored_json_object(value: Any) -> dict[str, Any]:
    """Decode a JSONB object without allowing malformed storage to escape."""

    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def _stored_metrics(value: Any) -> dict[str, Any]:
    try:
        return _safe_metrics(_stored_json_object(value))
    except ValueError:
        # Stored rows are written through _safe_metrics.  Fail closed if an
        # older/manual row does not satisfy that contract instead of exposing
        # arbitrary JSON to the observability UI.
        return {}


def _stored_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _observability_run_projection(row: Any, columns: Sequence[str]) -> dict[str, Any]:
    item = _row_to_dict(row, columns)
    return {
        "run_id": str(item.get("id") or "")[:128],
        "dataset_id": str(item.get("dataset_id") or "")[:128],
        "git_sha": str(item.get("git_sha") or "")[:80],
        "prompt_version": str(item.get("prompt_version") or "")[:160],
        "parser_version": str(item.get("parser_version") or "")[:160],
        "chunker_config_hash": str(item.get("chunker_config_hash") or "")[:128],
        "embedding_model": str(item.get("embedding_model") or "")[:160],
        "embedding_dimensions": max(0, int(item.get("embedding_dimensions") or 0)),
        "distance_algorithm": str(item.get("distance_algorithm") or "")[:64],
        "reranker_version": str(item.get("reranker_version") or "")[:160],
        "provider_model": str(item.get("provider_model") or "")[:160],
        "status": str(item.get("status") or "")[:32],
        "metrics": _stored_metrics(item.get("metrics_json")),
        "version": max(0, int(item.get("version") or 0)),
        "created_at": _stored_timestamp(item.get("created_at")),
        "updated_at": _stored_timestamp(item.get("updated_at")),
        "started_at": _stored_timestamp(item.get("started_at")),
        "finished_at": _stored_timestamp(item.get("finished_at")),
    }


_OBSERVABILITY_RUN_COLUMNS = (
    "id", "dataset_id", "git_sha", "prompt_version", "parser_version",
    "chunker_config_hash", "embedding_model", "embedding_dimensions",
    "distance_algorithm", "reranker_version", "provider_model", "status",
    "metrics_json", "version", "created_at", "updated_at", "started_at",
    "finished_at",
)


def list_experiment_runs(*, tenant_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return only metadata for runs owned by one tenant."""

    _require_pg()
    tenant = _code(tenant_id, field="tenant_id", maximum=128)
    bounded_limit = max(1, min(int(limit), 100))
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_OBSERVABILITY_RUN_COLUMNS)} "
            "FROM ai_experiment_run WHERE tenant_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (tenant, bounded_limit),
        ).fetchall()
    return [_observability_run_projection(row, _OBSERVABILITY_RUN_COLUMNS) for row in rows]


def update_experiment_run(
    *,
    run_id: str,
    tenant_id: str,
    status: str | None = None,
    metrics: Mapping[str, Any] | None = None,
    updated_by: str,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Update a run with an optimistic version check."""

    _require_pg()
    run = _code(run_id, field="run_id", maximum=128)
    tenant = _code(tenant_id, field="tenant_id", maximum=128)
    actor = _code(updated_by, field="updated_by", maximum=128)
    safe_metrics = _safe_metrics(metrics) if metrics is not None else None
    allowed_statuses = {"planned", "running", "completed", "failed", "cancelled"}
    if status is not None and status not in allowed_statuses:
        raise ValueError("unsupported experiment status")
    now = _now()
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT status, version FROM ai_experiment_run WHERE id = ? AND tenant_id = ? FOR UPDATE",
            (run, tenant),
        ).fetchone()
        if not row:
            raise LookupError("experiment run not found")
        current_version = int(_row_value(row, "version", 1) or 0)
        if expected_version is not None and current_version != int(expected_version):
            raise ExperimentPersistenceError("experiment run version conflict")
        next_status = status or str(_row_value(row, "status", 0))
        assignments = ["status = ?", "updated_by = ?", "updated_at = ?", "version = version + 1"]
        params: list[Any] = [next_status, actor, now]
        if safe_metrics is not None:
            assignments.append("metrics_json = ?")
            params.append(_json_value(safe_metrics))
        if next_status == "running":
            assignments.append("started_at = COALESCE(started_at, ?)")
            params.append(now)
        if next_status in {"completed", "failed", "cancelled"}:
            assignments.append("finished_at = COALESCE(finished_at, ?)")
            params.append(now)
        params.extend([run, tenant, current_version])
        result = conn.execute(
            f"UPDATE ai_experiment_run SET {', '.join(assignments)} WHERE id = ? AND tenant_id = ? AND version = ?",
            params,
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            conn.rollback()
            raise ExperimentPersistenceError("experiment run version conflict")
        conn.commit()
    return get_experiment_run(run_id=run, tenant_id=tenant) or {}


_CASE_COLUMNS = (
    "id", "experiment_run_id", "tenant_id", "case_id", "expected_outcome",
    "actual_outcome", "safety_passed", "quality_passed", "recall_at_5",
    "recall_at_10", "mrr", "ndcg", "citation_precision", "citation_recall",
    "wrong_vendor_rate", "feature_pollution_rate", "latency_ms", "error_code",
    "gold_document_ids", "returned_document_ids", "returned_vendors", "metrics_json",
    "created_by", "updated_at", "version",
)


def record_experiment_case_result(
    *,
    run_id: str,
    tenant_id: str,
    case_id: str,
    expected_outcome: str,
    actual_outcome: str,
    safety_passed: bool,
    quality_passed: bool | None,
    gold_document_ids: Sequence[Any] | None = None,
    returned_document_ids: Sequence[Any] | None = None,
    returned_vendors: Sequence[Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    error_code: str | None = None,
    created_by: str,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Insert or update one case result without retaining answer material."""

    _require_pg()
    run = _code(run_id, field="run_id", maximum=128)
    tenant = _code(tenant_id, field="tenant_id", maximum=128)
    case = _code(case_id, field="case_id", maximum=160)
    expected = _code(expected_outcome, field="expected_outcome", maximum=64)
    actual = _code(actual_outcome, field="actual_outcome", maximum=64)
    actor = _code(created_by, field="created_by", maximum=128)
    error = _code(error_code, field="error_code", maximum=128, required=False) or None
    gold = _safe_ids(gold_document_ids, field="gold_document_ids")
    returned = _safe_ids(returned_document_ids, field="returned_document_ids")
    vendors = _safe_ids(returned_vendors, field="returned_vendors", maximum=32)
    safe_metrics = _safe_metrics(metrics)
    now = _now()
    metric_values = {key: safe_metrics.get(key) for key in _METRIC_KEYS}
    run_columns = "SELECT id, version FROM ai_experiment_run WHERE id = ? AND tenant_id = ? FOR UPDATE"
    with get_db_connection() as conn:
        run_row = conn.execute(run_columns, (run, tenant)).fetchone()
        if not run_row:
            raise LookupError("experiment run not found")
        case_row = conn.execute(
            "SELECT id, version FROM ai_experiment_case_result WHERE experiment_run_id = ? AND tenant_id = ? AND case_id = ? FOR UPDATE",
            (run, tenant, case),
        ).fetchone()
        if case_row:
            case_id_db = str(_row_value(case_row, "id", 0))
            current_version = int(_row_value(case_row, "version", 1) or 0)
            if expected_version is not None and current_version != int(expected_version):
                raise ExperimentPersistenceError("experiment case version conflict")
            conn.execute(
                """
                UPDATE ai_experiment_case_result
                SET expected_outcome = ?, actual_outcome = ?, safety_passed = ?, quality_passed = ?,
                    recall_at_5 = ?, recall_at_10 = ?, mrr = ?, ndcg = ?,
                    citation_precision = ?, citation_recall = ?, wrong_vendor_rate = ?,
                    feature_pollution_rate = ?, latency_ms = ?, error_code = ?,
                    gold_document_ids = ?, returned_document_ids = ?, returned_vendors = ?,
                    metrics_json = ?, created_by = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND tenant_id = ? AND version = ?
                """,
                (
                    expected,
                    actual,
                    bool(safety_passed),
                    quality_passed,
                    metric_values["recall_at_5"],
                    metric_values["recall_at_10"],
                    metric_values["mrr"],
                    metric_values["ndcg"],
                    metric_values["citation_precision"],
                    metric_values["citation_recall"],
                    metric_values["wrong_vendor_rate"],
                    metric_values["feature_pollution_rate"],
                    metric_values["latency_ms"],
                    error,
                    _json_value(gold),
                    _json_value(returned),
                    _json_value(vendors),
                    _json_value(safe_metrics),
                    actor,
                    now,
                    case_id_db,
                    tenant,
                    current_version,
                ),
            )
        else:
            case_id_db = f"exp_case_{uuid.uuid4().hex[:20]}"
            conn.execute(
                """
                INSERT INTO ai_experiment_case_result
                    (id, experiment_run_id, tenant_id, case_id, expected_outcome,
                     actual_outcome, safety_passed, quality_passed, recall_at_5,
                     recall_at_10, mrr, ndcg, citation_precision, citation_recall,
                     wrong_vendor_rate, feature_pollution_rate, latency_ms, error_code,
                     gold_document_ids, returned_document_ids, returned_vendors,
                     metrics_json, created_by, updated_at, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    case_id_db,
                    run,
                    tenant,
                    case,
                    expected,
                    actual,
                    bool(safety_passed),
                    quality_passed,
                    metric_values["recall_at_5"],
                    metric_values["recall_at_10"],
                    metric_values["mrr"],
                    metric_values["ndcg"],
                    metric_values["citation_precision"],
                    metric_values["citation_recall"],
                    metric_values["wrong_vendor_rate"],
                    metric_values["feature_pollution_rate"],
                    metric_values["latency_ms"],
                    error,
                    _json_value(gold),
                    _json_value(returned),
                    _json_value(vendors),
                    _json_value(safe_metrics),
                    actor,
                    now,
                ),
            )
        conn.execute(
            "UPDATE ai_experiment_run SET updated_at = ?, updated_by = ?, version = version + 1 WHERE id = ? AND tenant_id = ?",
            (now, actor, run, tenant),
        )
        conn.commit()
        row = conn.execute(
            f"SELECT {', '.join(_CASE_COLUMNS)} FROM ai_experiment_case_result WHERE id = ? AND tenant_id = ?",
            (case_id_db, tenant),
        ).fetchone()
    return _row_to_dict(row, _CASE_COLUMNS)


_ROLLOUT_COLUMNS = (
    "id", "tenant_id", "component", "mode", "rollout_percent", "baseline_version",
    "candidate_version", "kill_switch", "config_json", "created_by", "updated_by",
    "version", "created_at", "updated_at",
)


def get_runtime_rollout(*, tenant_id: str, component: str) -> dict[str, Any] | None:
    _require_pg()
    tenant = _code(tenant_id, field="tenant_id", maximum=128)
    name = _component(component)
    with get_db_connection() as conn:
        row = conn.execute(
            f"SELECT {', '.join(_ROLLOUT_COLUMNS)} FROM ai_runtime_rollout WHERE tenant_id = ? AND component = ?",
            (tenant, name),
        ).fetchone()
    return _row_to_dict(row, _ROLLOUT_COLUMNS) if row else None


def list_runtime_rollouts(*, tenant_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return tenant-scoped rollout pointers for the observability UI."""

    _require_pg()
    tenant = _code(tenant_id, field="tenant_id", maximum=128)
    bounded_limit = max(1, min(int(limit), 100))
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_ROLLOUT_COLUMNS[0:1] + _ROLLOUT_COLUMNS[2:])} "
            "FROM ai_runtime_rollout WHERE tenant_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (tenant, bounded_limit),
        ).fetchall()
    columns = _ROLLOUT_COLUMNS[0:1] + _ROLLOUT_COLUMNS[2:]
    result: list[dict[str, Any]] = []
    for row in rows:
        item = _row_to_dict(row, columns)
        result.append({
            "rollout_id": str(item.get("id") or "")[:128],
            "component": str(item.get("component") or "")[:64],
            "mode": str(item.get("mode") or "")[:32],
            "rollout_percent": max(0, min(100, int(item.get("rollout_percent") or 0))),
            "baseline_version": str(item.get("baseline_version") or "")[:160],
            "candidate_version": str(item.get("candidate_version") or "")[:160],
            "kill_switch": bool(item.get("kill_switch")),
            "version": max(0, int(item.get("version") or 0)),
            "updated_at": _stored_timestamp(item.get("updated_at")),
        })
    return result


def upsert_runtime_rollout(
    *,
    tenant_id: str,
    component: str,
    mode: str,
    rollout_percent: int,
    baseline_version: str,
    candidate_version: str,
    updated_by: str,
    kill_switch: bool = False,
    config: Mapping[str, Any] | None = None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Create/update a rollout pointer with PostgreSQL row locking."""

    _require_pg()
    tenant = _code(tenant_id, field="tenant_id", maximum=128)
    name = _component(component)
    actor = _code(updated_by, field="updated_by", maximum=128)
    base = _code(baseline_version, field="baseline_version")
    candidate = _code(candidate_version, field="candidate_version")
    if mode not in _ROLLOUT_MODES:
        raise ValueError("unsupported rollout mode")
    percent = max(0, min(100, int(rollout_percent)))
    safe_config = _safe_mapping(config)
    now = _now()
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, version FROM ai_runtime_rollout WHERE tenant_id = ? AND component = ? FOR UPDATE",
            (tenant, name),
        ).fetchone()
        if row:
            rollout_id = str(_row_value(row, "id", 0))
            current_version = int(_row_value(row, "version", 1) or 0)
            if expected_version is not None and current_version != int(expected_version):
                raise ExperimentPersistenceError("runtime rollout version conflict")
            result = conn.execute(
                """
                UPDATE ai_runtime_rollout
                SET mode = ?, rollout_percent = ?, baseline_version = ?, candidate_version = ?,
                    kill_switch = ?, config_json = ?, updated_by = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND tenant_id = ? AND version = ?
                """,
                (mode, percent, base, candidate, bool(kill_switch), _json_value(safe_config), actor, now, rollout_id, tenant, current_version),
            )
            if int(getattr(result, "rowcount", 0) or 0) != 1:
                conn.rollback()
                raise ExperimentPersistenceError("runtime rollout version conflict")
        else:
            rollout_id = f"rollout_{uuid.uuid4().hex[:20]}"
            conn.execute(
                """
                INSERT INTO ai_runtime_rollout
                    (id, tenant_id, component, mode, rollout_percent, baseline_version,
                     candidate_version, kill_switch, config_json, created_by, updated_by,
                     version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (rollout_id, tenant, name, mode, percent, base, candidate, bool(kill_switch), _json_value(safe_config), actor, actor, now, now),
            )
        conn.commit()
    return get_runtime_rollout(tenant_id=tenant, component=name) or {}


def stable_rollout_bucket(*, tenant_id: str, request_id: str) -> int:
    """Return a deterministic 0..99 bucket from tenant and request identity."""

    tenant = _code(tenant_id, field="tenant_id", maximum=128)
    request = _code(request_id, field="request_id", maximum=256)
    digest = hashlib.sha256(f"{tenant}\x00{request}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def runtime_rollout_decision(*, tenant_id: str, component: str, request_id: str) -> dict[str, Any]:
    """Resolve disabled/shadow/active behavior without random assignment."""

    rollout = get_runtime_rollout(tenant_id=tenant_id, component=component)
    if not rollout:
        return {
            "component": _component(component),
            "mode": "disabled",
            "assigned": False,
            "candidate_enabled": False,
            "production_version": None,
            "bucket": stable_rollout_bucket(tenant_id=tenant_id, request_id=request_id),
        }
    mode = str(rollout["mode"])
    bucket = stable_rollout_bucket(tenant_id=tenant_id, request_id=request_id)
    assigned = mode in {"shadow", "active"} and not bool(rollout["kill_switch"]) and bucket < int(rollout["rollout_percent"])
    candidate_enabled = assigned and mode in {"shadow", "active"}
    production_version = rollout["candidate_version"] if mode == "active" and assigned else rollout["baseline_version"]
    return {
        "component": rollout["component"],
        "mode": mode,
        "assigned": assigned,
        "candidate_enabled": candidate_enabled,
        "production_version": production_version,
        "baseline_version": rollout["baseline_version"],
        "candidate_version": rollout["candidate_version"],
        "rollout_percent": int(rollout["rollout_percent"]),
        "kill_switch": bool(rollout["kill_switch"]),
        "bucket": bucket,
        "version": int(rollout["version"]),
    }


def record_shadow_observation(
    *,
    tenant_id: str,
    component: str,
    request_id: str,
    baseline_ranked_ids: Sequence[Any] | None,
    candidate_ranked_ids: Sequence[Any] | None,
    metrics: Mapping[str, Any] | None = None,
    baseline_latency_ms: int | None = None,
    candidate_latency_ms: int | None = None,
    status: str = "observed",
    reason_code: str | None = None,
    retention_days: int = 60,
    experiment_run_id: str | None = None,
    created_by: str,
) -> dict[str, Any]:
    """Store a metadata-only Shadow comparison with bounded retention."""

    _require_pg()
    tenant = _code(tenant_id, field="tenant_id", maximum=128)
    name = _component(component)
    raw_request = _code(request_id, field="request_id", maximum=256)
    actor = _code(created_by, field="created_by", maximum=128)
    if status not in _SHADOW_STATUSES:
        raise ValueError("unsupported Shadow observation status")
    days = int(retention_days)
    if days < 30 or days > 90:
        raise ValueError("retention_days must be between 30 and 90")
    base_latency = None if baseline_latency_ms is None else max(0, int(baseline_latency_ms))
    candidate_latency = None if candidate_latency_ms is None else max(0, int(candidate_latency_ms))
    reason = _code(reason_code, field="reason_code", maximum=128, required=False) or None
    base_ids = _safe_ids(baseline_ranked_ids, field="baseline_ranked_ids")
    candidate_ids = _safe_ids(candidate_ranked_ids, field="candidate_ranked_ids")
    safe_metrics = _safe_metrics(metrics)
    observed_at = _now()
    expires_at = observed_at + timedelta(days=days)
    observation_id = f"shadow_{uuid.uuid4().hex[:20]}"
    request_hash = hashlib.sha256(raw_request.encode("utf-8")).hexdigest()
    run = _code(experiment_run_id, field="experiment_run_id", maximum=128, required=False) or None
    with get_db_connection() as conn:
        if run:
            run_row = conn.execute(
                "SELECT id FROM ai_experiment_run WHERE id = ? AND tenant_id = ? FOR SHARE",
                (run, tenant),
            ).fetchone()
            if not run_row:
                raise LookupError("experiment run not found")
        conn.execute(
            """
            INSERT INTO ai_shadow_observation
                (id, tenant_id, experiment_run_id, component, request_id_hash,
                 baseline_ranked_ids, candidate_ranked_ids, metrics_json,
                 baseline_latency_ms, candidate_latency_ms, status, reason_code,
                 retention_days, observed_at, expires_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (observation_id, tenant, run, name, request_hash, _json_value(base_ids), _json_value(candidate_ids), _json_value(safe_metrics), base_latency, candidate_latency, status, reason, days, observed_at, expires_at, actor),
        )
        conn.commit()
    return {
        "id": observation_id,
        "tenant_id": tenant,
        "experiment_run_id": run,
        "component": name,
        "request_id_hash": request_hash,
        "baseline_ranked_ids": base_ids,
        "candidate_ranked_ids": candidate_ids,
        "metrics": safe_metrics,
        "status": status,
        "reason_code": reason,
        "retention_days": days,
        "observed_at": observed_at,
        "expires_at": expires_at,
    }


_OBSERVATION_COLUMNS = (
    "id", "experiment_run_id", "component", "request_id_hash",
    "baseline_ranked_ids", "candidate_ranked_ids", "metrics_json",
    "baseline_latency_ms", "candidate_latency_ms", "status", "reason_code",
    "retention_days", "observed_at", "expires_at",
)


def _stored_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _rank_hashes(values: Any, tenant: str) -> list[str]:
    hashes: list[str] = []
    for value in _stored_json_list(values)[:100]:
        text = str(value or "").strip()[:256]
        if not text:
            continue
        digest = hashlib.sha256(f"{tenant}\x00{text}".encode("utf-8")).hexdigest()[:16]
        if digest not in hashes:
            hashes.append(digest)
    return hashes


def _rank_deltas(baseline: list[str], candidate: list[str]) -> list[dict[str, Any]]:
    baseline_rank = {value: index for index, value in enumerate(baseline, 1)}
    candidate_rank = {value: index for index, value in enumerate(candidate, 1)}
    deltas: list[dict[str, Any]] = []
    for value in list(dict.fromkeys([*baseline, *candidate]))[:100]:
        left = baseline_rank.get(value)
        right = candidate_rank.get(value)
        if left == right:
            continue
        deltas.append({
            "candidate_hash": value,
            "baseline_rank": left,
            "candidate_rank": right,
            "rank_delta": right - left if left is not None and right is not None else None,
        })
    return deltas


def list_shadow_observations(*, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return redacted ranking differences for one tenant only."""

    _require_pg()
    tenant = _code(tenant_id, field="tenant_id", maximum=128)
    bounded_limit = max(1, min(int(limit), 200))
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_OBSERVATION_COLUMNS)} "
            "FROM ai_shadow_observation WHERE tenant_id = ? "
            "ORDER BY observed_at DESC LIMIT ?",
            (tenant, bounded_limit),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = _row_to_dict(row, _OBSERVATION_COLUMNS)
        baseline = _rank_hashes(item.get("baseline_ranked_ids"), tenant)
        candidate = _rank_hashes(item.get("candidate_ranked_ids"), tenant)
        result.append({
            "observation_id": str(item.get("id") or "")[:128],
            "experiment_run_id": str(item.get("experiment_run_id") or "")[:128] or None,
            "component": str(item.get("component") or "")[:64],
            "request_hash": str(item.get("request_id_hash") or "")[:16],
            "baseline_count": len(baseline),
            "candidate_count": len(candidate),
            "order_changed": baseline != candidate,
            "rank_deltas": _rank_deltas(baseline, candidate),
            "baseline_latency_ms": max(0, int(item.get("baseline_latency_ms") or 0)) if item.get("baseline_latency_ms") is not None else None,
            "candidate_latency_ms": max(0, int(item.get("candidate_latency_ms") or 0)) if item.get("candidate_latency_ms") is not None else None,
            "status": str(item.get("status") or "")[:32],
            "reason_code": str(item.get("reason_code") or "")[:128] or None,
            "metrics": _stored_metrics(item.get("metrics_json")),
            "retention_days": max(30, min(90, int(item.get("retention_days") or 60))),
            "observed_at": _stored_timestamp(item.get("observed_at")),
            "expires_at": _stored_timestamp(item.get("expires_at")),
        })
    return result


def get_experiment_observability(*, tenant_id: str, limit: int = 50) -> dict[str, Any]:
    """Build the tenant-safe OBS-002 read model from PostgreSQL evidence."""

    _require_pg()
    tenant = _code(tenant_id, field="tenant_id", maximum=128)
    bounded_limit = max(1, min(int(limit), 100))
    return {
        "schema_version": "obs-002-v1",
        "tenant_id": tenant,
        "database": "PostgreSQL",
        "redacted": True,
        "contains_prompt_or_answer": False,
        "contains_document_or_chunk_identity": False,
        "runs": list_experiment_runs(tenant_id=tenant, limit=bounded_limit),
        "rollouts": list_runtime_rollouts(tenant_id=tenant, limit=bounded_limit),
        "shadow_observations": list_shadow_observations(tenant_id=tenant, limit=bounded_limit),
    }


def purge_expired_shadow_observations(*, now: datetime | None = None, limit: int = 1000) -> int:
    """Delete only observations past their declared retention window."""

    _require_pg()
    cutoff = now or _now()
    bounded_limit = max(1, min(int(limit), 10_000))
    with get_db_connection() as conn:
        result = conn.execute(
            """
            DELETE FROM ai_shadow_observation
            WHERE id IN (
                SELECT id FROM ai_shadow_observation
                WHERE expires_at <= ?
                ORDER BY expires_at
                LIMIT ?
            )
            """,
            (cutoff, bounded_limit),
        )
        count = int(getattr(result, "rowcount", 0) or 0)
        conn.commit()
    return count


__all__ = [
    "ExperimentPersistenceError",
    "create_experiment_run",
    "get_experiment_run",
    "list_experiment_runs",
    "update_experiment_run",
    "record_experiment_case_result",
    "get_runtime_rollout",
    "list_runtime_rollouts",
    "upsert_runtime_rollout",
    "stable_rollout_bucket",
    "runtime_rollout_decision",
    "record_shadow_observation",
    "list_shadow_observations",
    "get_experiment_observability",
    "purge_expired_shadow_observations",
]
