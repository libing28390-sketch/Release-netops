"""Health, failure and performance views for the platform registry."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from database import get_db_connection
from services.platform_registry_service import (
    _assert_profile_access,
)


_PARSE_FAILURE_CODES = {
    "FIELD_CONTRACT_VIOLATION",
    "PARSER_OUTPUT_LIMIT_EXCEEDED",
    "PARSER_SAMPLE_UNAVAILABLE",
    "PARSER_TIMEOUT",
    "TEMPLATE_NOT_MATCHED",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _pct(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) * 100.0 / float(denominator), 2)


def _tenant_filter(user: dict[str, Any], column: str) -> tuple[str, list[Any]]:
    tenant_id = str(user.get("tenant_id") or "")
    if tenant_id:
        return f" AND {column} = ?", [tenant_id]
    return "", []


def _affected_playbooks(conn, release_ids: set[str], user: dict[str, Any]) -> int:
    if not release_ids:
        return 0
    try:
        tenant_sql, params = _tenant_filter(user, "tenant_id")
        rows = conn.execute(
            "SELECT tenant_id, platform_release_ids_json FROM playbook_versions WHERE 1 = 1"
            + tenant_sql,
            params,
        ).fetchall()
    except Exception:
        return 0
    count = 0
    for row in rows:
        try:
            values = json.loads(row["platform_release_ids_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            values = []
        if isinstance(values, dict):
            values = values.get("release_ids") or values.get("platform_release_ids") or []
        if not isinstance(values, list):
            values = []
        if release_ids.intersection({str(item) for item in values}):
            count += 1
    return count


def _profile_health(conn, profile: dict[str, Any], user: dict[str, Any], range_hours: int) -> dict[str, Any]:
    profile_id = str(profile["id"])
    current_release_id = str(profile.get("current_release_id") or "")
    actions = conn.execute(
        "SELECT action_code FROM platform_release_actions WHERE release_id = ?",
        (current_release_id,),
    ).fetchall() if current_release_id else []
    definition_count = int(conn.execute("SELECT COUNT(*) FROM action_definitions").fetchone()[0] or 0)
    action_count = len(actions)

    current_time = _now()
    since = current_time - timedelta(hours=range_hours)
    tenant_sql, tenant_params = _tenant_filter(user, "r.tenant_id")
    run_rows = conn.execute(
        "SELECT r.id, r.tenant_id, r.device_id, r.platform_release_id, r.action_code, "
        "r.status, r.failure_stage, r.error_code, r.record_count, r.duration_ms, r.output_bytes, "
        "r.raw_output_encrypted, r.raw_output_expires_at, r.created_at, "
        "a.command AS action_command, "
        "d.hostname AS device_hostname, d.role AS device_role "
        "FROM platform_action_runs r "
        "LEFT JOIN platform_release_actions a ON a.release_id = r.platform_release_id AND a.action_code = r.action_code "
        "LEFT JOIN devices d ON d.id = r.device_id "
        "WHERE r.platform_profile_id = ? AND r.created_at >= ?"
        + tenant_sql + " ORDER BY r.created_at DESC",
        [profile_id, _iso(since), *tenant_params],
    ).fetchall()
    run_count = len(run_rows)
    success_count = sum(1 for row in run_rows if str(row["status"] or "").upper() == "SUCCESS")
    parse_failure_rows = [row for row in run_rows if str(row["error_code"] or "") in _PARSE_FAILURE_CODES]
    durations = [max(0, int(row["duration_ms"] or 0)) for row in run_rows]
    last_run_at = str(run_rows[0]["created_at"]) if run_rows else None
    last_failure_at = next((str(row["created_at"]) for row in run_rows if str(row["status"] or "").upper() == "FAILED"), None)
    last_time = _parse_time(last_run_at)
    age_hours = max(0.0, (current_time - last_time).total_seconds() / 3600.0) if last_time else None
    freshness = max(0.0, 1.0 - ((age_hours or float(range_hours)) / max(float(range_hours), 1.0))) if last_time else 0.0

    command_coverage = _pct(action_count, definition_count)
    success_rate = _pct(success_count, run_count)
    parse_failure_rate = _pct(len(parse_failure_rows), run_count)
    if run_count:
        score = round(
            min(100.0, (command_coverage or 0.0) * 0.30
                 + (success_rate or 0.0) * 0.45
                 + max(0.0, 100.0 - (parse_failure_rate or 0.0)) * 0.15
                 + freshness * 10.0),
        )
        health_status = "healthy" if score >= 85 else "warning" if score >= 60 else "critical"
    else:
        score = None
        health_status = "unknown"

    failure_queue = []
    for row in run_rows:
        if str(row["status"] or "").upper() != "FAILED":
            continue
        failure_queue.append({
            "id": row["id"],
            "device_id": row["device_id"],
            "device_hostname": row["device_hostname"],
            "device_role": row["device_role"],
            "command": row["action_command"],
            "action_code": row["action_code"],
            "error_code": row["error_code"],
            "failure_stage": row["failure_stage"],
            "duration_ms": int(row["duration_ms"] or 0),
            "created_at": row["created_at"],
            "raw_output_available": bool(row["raw_output_encrypted"] and row["raw_output_expires_at"]),
        })
        if len(failure_queue) >= 50:
            break

    trend: dict[str, dict[str, Any]] = {}
    for row in reversed(run_rows):
        created = str(row["created_at"] or "")
        bucket = created[:13] if len(created) >= 13 else created
        item = trend.setdefault(bucket, {"bucket": bucket, "runs": 0, "successes": 0, "failures": 0, "timeouts": 0, "avg_duration_ms": 0.0})
        item["runs"] += 1
        item["successes"] += int(str(row["status"] or "").upper() == "SUCCESS")
        item["failures"] += int(str(row["status"] or "").upper() == "FAILED")
        item["timeouts"] += int("TIMEOUT" in str(row["error_code"] or "").upper())
        item["avg_duration_ms"] += int(row["duration_ms"] or 0)
    for item in trend.values():
        item["avg_duration_ms"] = round(item["avg_duration_ms"] / item["runs"], 2) if item["runs"] else 0

    bound_device_sql, bound_params = _tenant_filter(user, "d.tenant_id")
    device_counts = conn.execute(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN LOWER(COALESCE(d.status, '')) IN ('online', 'active', 'up') THEN 1 ELSE 0 END) AS online "
        "FROM devices d WHERE d.platform_profile_id = ?" + bound_device_sql,
        [profile_id, *bound_params],
    ).fetchone()
    release_ids = {str(row["platform_release_id"]) for row in run_rows if row["platform_release_id"]}
    if current_release_id:
        release_ids.add(current_release_id)
    return {
        "profile_id": profile_id,
        "platform_code": profile.get("platform_code"),
        "current_release_id": current_release_id or None,
        "range_hours": range_hours,
        "command_coverage_pct": command_coverage,
        "recent_run_count": run_count,
        "recent_success_rate_pct": success_rate,
        "recent_parse_failure_count": len(parse_failure_rows),
        "recent_parse_failure_rate_pct": parse_failure_rate,
        "last_run_at": last_run_at,
        "last_failure_at": last_failure_at,
        "last_run_age_hours": round(age_hours, 2) if age_hours is not None else None,
        "avg_duration_ms": round(sum(durations) / len(durations), 2) if durations else None,
        "p95_duration_ms": sorted(durations)[min(len(durations) - 1, math.ceil(len(durations) * 0.95) - 1)] if durations else None,
        "health_score": score,
        "health_score_available": score is not None,
        "health_status": health_status,
        "bound_device_count": int(device_counts["total"] or 0),
        "online_device_count": int(device_counts["online"] or 0),
        "affected_playbook_count": _affected_playbooks(conn, release_ids, user),
        "failure_queue": failure_queue,
        "unknown_output_queue": [item for item in failure_queue if item["error_code"] in _PARSE_FAILURE_CODES],
        "performance_trend": list(trend.values()),
    }


def get_profile_health(profile_id: str, user: dict[str, Any], *, range_hours: int = 168) -> dict[str, Any]:
    try:
        range_hours = max(1, min(720, int(range_hours)))
    except (TypeError, ValueError):
        range_hours = 168
    conn = get_db_connection()
    try:
        profile = _assert_profile_access(conn, profile_id, user)
        return _profile_health(conn, profile, user, range_hours)
    finally:
        conn.close()
