"""Collection Health is separate from Device Health.

Device health answers whether a device is operational.  Collection health
answers whether the configured assignment was sampled recently and whether the
collector reported an actionable error category.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


ERROR_CATEGORIES = {
    "AUTH_FAILED", "TIMEOUT", "NETWORK_UNREACHABLE", "OID_UNSUPPORTED",
    "MODULE_ERROR", "EXPORTER_ERROR", "SCRAPE_TIMEOUT",
}


def _age_seconds(value: Any, now: datetime) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (now - parsed).total_seconds())
    except (TypeError, ValueError):
        return None


def classify_collection_health(
    assignment: Mapping[str, Any],
    *,
    now: datetime | None = None,
    stale_factor: float = 3.0,
) -> dict[str, Any]:
    """Return a stable, API-safe health record for one assignment."""
    now = now or datetime.now(timezone.utc)
    interval = max(1, int(assignment.get("interval_seconds") or 60))
    enabled = assignment.get("enabled", True) not in (False, 0, "0")
    error_code = str(assignment.get("error_code") or "").upper()
    if error_code and error_code not in ERROR_CATEGORIES:
        error_code = "MODULE_ERROR"
    last_success = assignment.get("last_success_at") or assignment.get("last_collected_at")
    age = _age_seconds(last_success, now)
    if not enabled:
        status = "DISABLED"
    elif error_code:
        status = "FAILED"
    elif age is None:
        status = "UNKNOWN"
    elif age > interval * max(1.0, float(stale_factor)):
        status = "STALE"
    else:
        status = "OK"
    return {
        "assignment_id": assignment.get("id"),
        "asset_id": assignment.get("asset_id"),
        "collector_id": assignment.get("collector_id"),
        "module_variant_id": assignment.get("module_variant_id"),
        "status": status,
        "error_code": error_code or None,
        "last_success_at": last_success,
        "last_attempt_at": assignment.get("last_attempt_at"),
        "duration_ms": assignment.get("duration_ms"),
        "consecutive_failures": int(assignment.get("consecutive_failures") or 0),
        "age_seconds": age,
        "interval_seconds": interval,
        "device_health": assignment.get("device_health"),
    }

def summarize_collection_health(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "UNKNOWN").upper()
        counts[status] = counts.get(status, 0) + 1
    total = len(items)
    healthy = counts.get("OK", 0)
    return {
        "total": total,
        "healthy": healthy,
        "health_ratio": (healthy / total) if total else 1.0,
        "by_status": counts,
    }
