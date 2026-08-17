"""Bounded official Seed URL collection for the Knowledge Engine.

CAT-001, CAT-003 and CAT-004 remain the URL, source-registry and outbound
security authorities. This module adds tenant/host scheduling, operational
policy evidence and a bounded anomaly projection around the single-URL
importer.
"""

from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from services.official_url_import_service import OfficialUrlImportError, import_single_official_url
from services.source_registry_service import SourceRegistryError, validate_official_url_input


MAX_SEED_ITEMS = 20
MAX_RATE_LIMIT_PER_MINUTE = 30
DEFAULT_RATE_LIMIT_PER_MINUTE = 6
MAX_CONCURRENCY = 4
DEFAULT_CONCURRENCY = 2
MAX_BACKOFF_BASE_SECONDS = 5.0
DEFAULT_BACKOFF_BASE_SECONDS = 0.25

_ALERT_SEVERE_CODES = {
    "ROBOTS_DISALLOWED",
    "ROBOTS_UNAVAILABLE",
    "ROBOTS_PARSE_INVALID",
    "OUTBOUND_HTTP_SOURCE_NOT_FOUND",
    "OFFICIAL_SOURCE_REMOVED",
}


class OfficialSeedBatchError(ValueError):
    """Stable, safe error for a rejected batch before network activity."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class _TenantHostRateLimiter:
    """Process-local fixed-spacing limiter; reservation is concurrency-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_allowed: dict[tuple[str, str], float] = {}

    def reserve(self, *, tenant_id: str, host: str, rate_limit_per_minute: int, now: float | None = None) -> float:
        interval = 60.0 / float(rate_limit_per_minute)
        moment = time.monotonic() if now is None else float(now)
        key = (str(tenant_id), str(host).lower())
        with self._lock:
            scheduled = max(moment, self._next_allowed.get(key, moment))
            self._next_allowed[key] = scheduled + interval
        return max(0.0, scheduled - moment)

    def reset_for_tests(self) -> None:
        with self._lock:
            self._next_allowed.clear()


rate_limiter = _TenantHostRateLimiter()


def _tenant(user: Mapping[str, Any]) -> str:
    return str(user.get("tenant_id") or "tenant-default").strip() or "tenant-default"


def _bounded_text(value: Any, *, maximum: int = 256) -> str:
    return str(value or "").strip()[:maximum]


def _item_payload(item: Mapping[str, Any], *, index: int, batch_request_id: str) -> dict[str, Any]:
    payload = copy.deepcopy(dict(item))
    payload["request_id"] = _bounded_text(payload.get("request_id") or f"{batch_request_id}:item:{index + 1}")
    return payload


def _preflight_item(item: Mapping[str, Any], *, index: int, user: Mapping[str, Any]) -> dict[str, Any]:
    url = _bounded_text(item.get("url"), maximum=4096)
    source_kind = _bounded_text(item.get("source_kind") or "product_page", maximum=64).lower()
    metadata = {
        "vendor": _bounded_text(item.get("vendor"), maximum=128),
        "product_family": _bounded_text(item.get("product_family"), maximum=256),
        "version_scope": copy.deepcopy(item.get("version_scope") or {}),
        "terms_review_status": _bounded_text(item.get("terms_review_status"), maximum=32).lower(),
        "reviewer": _bounded_text(item.get("reviewer") or user.get("username") or user.get("id") or "system", maximum=256),
        "reviewed_at": _bounded_text(item.get("reviewed_at"), maximum=128),
    }
    try:
        preflight = validate_official_url_input(url, source_kind=source_kind, metadata=metadata)
    except SourceRegistryError as exc:
        detail = {"index": index, "code": str(exc.code or "SEED_PREFLIGHT_FAILED")[:128]}
        raise OfficialSeedBatchError(
            "SEED_PREFLIGHT_FAILED",
            "One or more Seed URLs failed the official-source preflight",
            status_code=exc.status_code,
            details=[detail],
        ) from exc
    return {
        "index": index,
        "canonical_url": str(preflight.get("canonical_url") or ""),
        "host": str(urlsplit(str(preflight.get("canonical_url") or url)).hostname or "").lower(),
        "source_kind": source_kind,
        "payload": dict(item),
    }


def _public_result(result: Mapping[str, Any], *, index: int, canonical_url: str) -> dict[str, Any]:
    job = result.get("job") if isinstance(result.get("job"), Mapping) else {}
    source = result.get("source") if isinstance(result.get("source"), Mapping) else {}
    version = result.get("version") if isinstance(result.get("version"), Mapping) else {}
    error = result.get("error") if isinstance(result.get("error"), Mapping) else {}
    policy = result.get("policy") if isinstance(result.get("policy"), Mapping) else {}
    terms = policy.get("terms_review") if isinstance(policy.get("terms_review"), Mapping) else {}
    robots = policy.get("robots") if isinstance(policy.get("robots"), Mapping) else {}
    return {
        "index": index,
        "url": canonical_url,
        "success": bool(result.get("success")),
        "replayed": bool(result.get("replayed")),
        "continuation_required": bool(result.get("continuation_required")),
        "job": {
            "id": str(job.get("id") or ""),
            "execution_state": str(job.get("execution_state") or ""),
            "phase": str(job.get("phase") or ""),
            "progress_percent": float(job.get("progress_percent") or 0),
        },
        "source_id": str(source.get("id") or ""),
        "source_version_id": str(version.get("id") or ""),
        "policy": {
            "operational_enforced": bool(policy.get("operational_enforced")),
            "terms_review": {
                "required": bool(terms.get("required")),
                "status": str(terms.get("status") or "pending")[:32],
                "reviewer_present": bool(terms.get("reviewer_present")),
                "reviewed_at_present": bool(terms.get("reviewed_at_present")),
            },
            "robots": {
                "policy": str(robots.get("policy") or "not_checked")[:32],
                "outcome": str(robots.get("outcome") or "not_checked")[:64],
                "allowed": bool(robots.get("allowed")),
                "error_code": str(robots.get("error_code") or "")[:128],
                "status_code": robots.get("status_code"),
                "bytes_read": int(robots.get("bytes_read") or 0),
                "review_required": bool(robots.get("review_required")),
            },
        },
        "error": {
            "code": str(error.get("code") or "")[:128],
            "retryable": bool(error.get("retryable")),
        } if error else None,
    }


def _invoke_importer(importer: Callable[..., dict[str, Any]], user: Mapping[str, Any], payload: dict[str, Any], *, backoff_base_seconds: float, sleeper: Callable[[float], None]) -> dict[str, Any]:
    """Call the importer with policy knobs while keeping old test doubles."""
    try:
        return importer(user, payload, operational_policy=True, backoff_base_seconds=backoff_base_seconds, sleeper=sleeper)
    except TypeError as exc:
        message = str(exc)
        if "unexpected keyword argument" not in message and "got an unexpected keyword" not in message:
            raise
        return importer(user, payload)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _record_site_alerts(user: Mapping[str, Any], *, batch_id: str, alerts: Sequence[Mapping[str, Any]]) -> None:
    """Persist bounded tenant/host/code alerts, never using legacy alert_events."""
    if not alerts:
        return
    from database import get_db_connection

    tenant_id = _tenant(user)
    actor = _bounded_text(user.get("id") or user.get("username") or "system", maximum=128)
    now = _utc_now()
    conn = get_db_connection()
    try:
        for alert in alerts:
            host = _bounded_text(alert.get("host"), maximum=255).lower()
            code = _bounded_text(alert.get("alert_code"), maximum=128)
            if not host or not code:
                continue
            source_ids = sorted({_bounded_text(item, maximum=128) for item in (alert.get("source_ids") or []) if item})
            details = {"batch_id": _bounded_text(batch_id), "observed_count": int(alert.get("observed_count") or 0), "actor": actor}
            row = conn.execute("SELECT id, failure_count FROM kb_site_anomaly_alert WHERE tenant_id = ? AND host = ? AND alert_code = ?", (tenant_id, host, code)).fetchone()
            if row:
                row_dict = dict(row)
                conn.execute(
                    "UPDATE kb_site_anomaly_alert SET severity = ?, title = ?, status = 'open', failure_count = ?, last_seen_at = ?, resolved_at = NULL, source_ids_json = ?, details_json = ? WHERE tenant_id = ? AND host = ? AND alert_code = ?",
                    (_bounded_text(alert.get("severity") or "warning", maximum=16), _bounded_text(alert.get("title") or "Official source site anomaly", maximum=256), int(row_dict.get("failure_count") or 0) + int(alert.get("observed_count") or 0), now, json.dumps(source_ids, ensure_ascii=True), json.dumps(details, ensure_ascii=True), tenant_id, host, code),
                )
            else:
                conn.execute(
                    "INSERT INTO kb_site_anomaly_alert (id, tenant_id, host, alert_code, severity, title, status, failure_count, first_seen_at, last_seen_at, resolved_at, source_ids_json, details_json) VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, NULL, ?, ?)",
                    (str(uuid.uuid4()), tenant_id, host, code, _bounded_text(alert.get("severity") or "warning", maximum=16), _bounded_text(alert.get("title") or "Official source site anomaly", maximum=256), int(alert.get("observed_count") or 0), now, now, json.dumps(source_ids, ensure_ascii=True), json.dumps(details, ensure_ascii=True)),
                )
        conn.commit()
    finally:
        conn.close()


def _build_site_alerts(candidates: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate, result in zip(candidates, results):
        if bool(result.get("success")):
            continue
        error = result.get("error") if isinstance(result.get("error"), Mapping) else {}
        code = _bounded_text(error.get("code") or "SEED_IMPORT_FAILED", maximum=128)
        host = _bounded_text(candidate.get("host"), maximum=255).lower()
        entry = grouped.setdefault((host, code), {"host": host, "alert_code": code, "observed_count": 0, "source_ids": []})
        entry["observed_count"] += 1
        source_id = _bounded_text(result.get("source_id"), maximum=128)
        if source_id and source_id not in entry["source_ids"]:
            entry["source_ids"].append(source_id)
    alerts: list[dict[str, Any]] = []
    for entry in grouped.values():
        code = str(entry["alert_code"])
        count = int(entry["observed_count"])
        if count < 2 and code not in _ALERT_SEVERE_CODES:
            continue
        severity = "major" if code in _ALERT_SEVERE_CODES else "warning"
        alerts.append({**entry, "severity": severity, "title": "Official source site requires attention" if severity == "major" else "Official source site anomaly"})
    return sorted(alerts, key=lambda item: (str(item.get("host") or ""), str(item.get("alert_code") or "")))


def list_site_anomaly_alerts(
    user: Mapping[str, Any],
    *,
    host: str = "",
    status: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return a tenant-scoped, metadata-only operational alert read model."""
    try:
        bounded_limit = max(1, min(200, int(limit)))
    except (TypeError, ValueError) as exc:
        raise OfficialSeedBatchError("SITE_ALERT_LIMIT_INVALID", "limit must be an integer", status_code=400) from exc
    host_value = _bounded_text(host, maximum=255).lower()
    status_value = _bounded_text(status, maximum=16).lower()
    if status_value and status_value not in {"open", "resolved"}:
        raise OfficialSeedBatchError("SITE_ALERT_STATUS_INVALID", "status must be open or resolved", status_code=400)
    from database import get_db_connection

    clauses = ["tenant_id = ?"]
    params: list[Any] = [_tenant(user)]
    if host_value:
        clauses.append("host = ?")
        params.append(host_value)
    if status_value:
        clauses.append("status = ?")
        params.append(status_value)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, host, alert_code, severity, title, status, failure_count, first_seen_at, last_seen_at, resolved_at "
            "FROM kb_site_anomaly_alert WHERE " + " AND ".join(clauses) + " ORDER BY last_seen_at DESC, id DESC LIMIT ?",
            tuple([*params, bounded_limit]),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def collect_official_seed_batch(
    user: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    *,
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
    concurrency: int = DEFAULT_CONCURRENCY,
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    request_id: str = "",
    importer: Callable[..., dict[str, Any]] = import_single_official_url,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Collect at most 20 reviewed URLs with bounded concurrency and backoff."""
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        raise OfficialSeedBatchError("SEED_ITEMS_INVALID", "Seed items must be a list", status_code=400)
    if not 1 <= len(items) <= MAX_SEED_ITEMS:
        raise OfficialSeedBatchError("SEED_BATCH_SIZE_INVALID", f"Seed batch must contain 1 to {MAX_SEED_ITEMS} items", status_code=400)
    try:
        rate = int(rate_limit_per_minute)
    except (TypeError, ValueError) as exc:
        raise OfficialSeedBatchError("SEED_RATE_LIMIT_INVALID", "rate_limit_per_minute must be an integer", status_code=400) from exc
    if not 1 <= rate <= MAX_RATE_LIMIT_PER_MINUTE:
        raise OfficialSeedBatchError("SEED_RATE_LIMIT_INVALID", f"rate_limit_per_minute must be between 1 and {MAX_RATE_LIMIT_PER_MINUTE}", status_code=400)
    try:
        worker_count = int(concurrency)
    except (TypeError, ValueError) as exc:
        raise OfficialSeedBatchError("SEED_CONCURRENCY_INVALID", "concurrency must be an integer", status_code=400) from exc
    if not 1 <= worker_count <= MAX_CONCURRENCY:
        raise OfficialSeedBatchError("SEED_CONCURRENCY_INVALID", f"concurrency must be between 1 and {MAX_CONCURRENCY}", status_code=400)
    try:
        backoff = float(backoff_base_seconds)
    except (TypeError, ValueError) as exc:
        raise OfficialSeedBatchError("SEED_BACKOFF_INVALID", "backoff_base_seconds must be a number", status_code=400) from exc
    if not 0.0 <= backoff <= MAX_BACKOFF_BASE_SECONDS:
        raise OfficialSeedBatchError("SEED_BACKOFF_INVALID", f"backoff_base_seconds must be between 0 and {MAX_BACKOFF_BASE_SECONDS:g}", status_code=400)

    batch_request_id = _bounded_text(request_id or f"seed_batch_{uuid.uuid4().hex[:16]}")
    preflighted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise OfficialSeedBatchError("SEED_ITEM_INVALID", "Each Seed item must be an object", status_code=400, details=[{"index": index}])
        candidate = _preflight_item(item, index=index, user=user)
        if not candidate["canonical_url"] or candidate["canonical_url"] in seen:
            raise OfficialSeedBatchError("SEED_DUPLICATE_URL", "Seed URLs must be unique after canonicalization", status_code=409, details=[{"index": index}])
        seen.add(candidate["canonical_url"])
        preflighted.append(candidate)

    started = time.monotonic()

    def _collect_one(candidate: Mapping[str, Any]) -> dict[str, Any]:
        wait_seconds = rate_limiter.reserve(tenant_id=_tenant(user), host=str(candidate["host"]), rate_limit_per_minute=rate)
        if wait_seconds > 0:
            sleeper(wait_seconds)
        payload = _item_payload(candidate["payload"], index=int(candidate["index"]), batch_request_id=batch_request_id)
        try:
            result = _invoke_importer(importer, user, payload, backoff_base_seconds=backoff, sleeper=sleeper)
        except OfficialUrlImportError as exc:
            result = {"success": False, "error": {"code": str(exc.code or "SEED_IMPORT_FAILED")[:128], "retryable": False}, "continuation_required": False, "replayed": False}
        except Exception:
            result = {"success": False, "error": {"code": "SEED_IMPORT_FAILED", "retryable": True}, "continuation_required": False, "replayed": False}
        return _public_result(result, index=int(candidate["index"]), canonical_url=str(candidate["canonical_url"]))

    results_by_index: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(worker_count, len(preflighted)), thread_name_prefix="kb-seed") as executor:
        futures = {executor.submit(_collect_one, candidate): int(candidate["index"]) for candidate in preflighted}
        for future in as_completed(futures):
            results_by_index[futures[future]] = future.result()
    results = [results_by_index[index] for index in sorted(results_by_index)]
    alerts = _build_site_alerts(preflighted, results)
    _record_site_alerts(user, batch_id=batch_request_id, alerts=alerts)
    succeeded = sum(1 for item in results if item["success"])
    return {
        "batch_id": batch_request_id,
        "tenant_id": _tenant(user),
        "item_count": len(results),
        "succeeded_count": succeeded,
        "failed_count": len(results) - succeeded,
        "rate_limit_per_minute": rate,
        "concurrency": worker_count,
        "backoff_base_seconds": backoff,
        "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
        "items": results,
        "alerts": alerts,
    }


__all__ = [
    "DEFAULT_RATE_LIMIT_PER_MINUTE",
    "DEFAULT_CONCURRENCY",
    "DEFAULT_BACKOFF_BASE_SECONDS",
    "MAX_RATE_LIMIT_PER_MINUTE",
    "MAX_CONCURRENCY",
    "MAX_BACKOFF_BASE_SECONDS",
    "MAX_SEED_ITEMS",
    "OfficialSeedBatchError",
    "collect_official_seed_batch",
    "list_site_anomaly_alerts",
    "rate_limiter",
]
