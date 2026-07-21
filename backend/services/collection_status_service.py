"""Durable collector-health state for network monitoring and topology."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from services.site_identity_service import canonical_site_name

logger = logging.getLogger(__name__)

COLLECTOR_STALE_SECONDS = {
    "reachability": 45,
    "snmp_metrics": 180,
    "snmp_interfaces": 180,
    "snmp_inventory": 900,
    "topology_lldp_cdp": 900,
    "diagnostics": 900,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value or {}, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


def _redact_metadata(value: Any) -> Any:
    """Drop secret-shaped keys before collector metadata is persisted."""
    secret_markers = ('password', 'community', 'secret', 'token', 'private_key')
    if isinstance(value, dict):
        return {
            str(key): _redact_metadata(item)
            for key, item in value.items()
            if not any(marker in str(key).lower() for marker in secret_markers)
        }
    if isinstance(value, list):
        return [_redact_metadata(item) for item in value]
    return value


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def record_collection_result(
    device_id: str,
    collector: str,
    *,
    status: str,
    transport: str = "",
    source: str = "",
    duration_ms: float | None = None,
    coverage_total: int = 0,
    coverage_supported: int = 0,
    error_code: str = "",
    error_message: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Upsert one collector result without ever storing credential material."""
    now = _utc_now_iso()
    success_at = now if status == "success" else None
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO device_collection_status (
                device_id, collector, status, transport, source,
                last_attempt_at, last_success_at, duration_ms,
                consecutive_failures, coverage_total, coverage_supported,
                error_code, error_message, metadata_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, collector) DO UPDATE SET
                status = excluded.status,
                transport = excluded.transport,
                source = excluded.source,
                last_attempt_at = excluded.last_attempt_at,
                last_success_at = CASE
                    WHEN excluded.status = 'success' THEN excluded.last_success_at
                    ELSE device_collection_status.last_success_at
                END,
                duration_ms = excluded.duration_ms,
                consecutive_failures = CASE
                    WHEN excluded.status = 'success' THEN 0
                    WHEN excluded.status IN ('failed', 'not_configured')
                        THEN device_collection_status.consecutive_failures + 1
                    ELSE device_collection_status.consecutive_failures
                END,
                coverage_total = excluded.coverage_total,
                coverage_supported = excluded.coverage_supported,
                error_code = excluded.error_code,
                error_message = excluded.error_message,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                device_id,
                collector,
                status,
                transport,
                source,
                now,
                success_at,
                duration_ms,
                0 if status == "success" else 1,
                max(0, int(coverage_total or 0)),
                max(0, int(coverage_supported or 0)),
                error_code[:80],
                error_message[:500],
                _safe_json(_redact_metadata(metadata)),
                now,
            ),
        )
        conn.commit()
    except Exception as exc:  # collector status must never break collection itself
        logger.warning("Failed to record %s collection status for %s: %s", collector, device_id, exc)
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def _decorate_status(item: dict[str, Any]) -> dict[str, Any]:
    raw_status = str(item.get("status") or "unknown")
    effective_status = raw_status
    threshold = COLLECTOR_STALE_SECONDS.get(str(item.get("collector") or ""))
    last_success = item.get("last_success_at")
    age_seconds: int | None = None
    if last_success:
        try:
            parsed = datetime.fromisoformat(str(last_success).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age_seconds = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
        except (TypeError, ValueError):
            age_seconds = None
    if raw_status == "success" and threshold and (age_seconds is None or age_seconds > threshold):
        effective_status = "stale"
    item["effective_status"] = effective_status
    item["age_seconds"] = age_seconds
    item["stale_after_seconds"] = threshold
    item['site_name'] = canonical_site_name(item)
    try:
        item["metadata"] = json.loads(item.pop("metadata_json", "{}") or "{}")
    except (TypeError, ValueError):
        item["metadata"] = {}
    return item


def list_collection_status(
    *,
    device_id: str | None = None,
    site_id: str | None = None,
    collector: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if device_id:
        clauses.append("c.device_id = ?")
        params.append(device_id)
    if site_id:
        clauses.append("d.site_id = ?")
        params.append(site_id)
    if collector:
        clauses.append("c.collector = ?")
        params.append(collector)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT c.*, d.hostname, d.ip_address, d.site_id,
                   COALESCE(s.site_name, d.site, '') AS site_name
            FROM device_collection_status c
            JOIN devices d ON d.id = c.device_id
            LEFT JOIN sites s ON s.id = d.site_id
            {where_sql}
            ORDER BY COALESCE(s.site_name, d.site, ''), d.hostname, c.collector
            """,
            tuple(params),
        ).fetchall()
        return [_decorate_status(_row_to_dict(row)) for row in rows]
    finally:
        conn.close()


def collection_status_summary(site_id: str | None = None) -> dict[str, Any]:
    items = list_collection_status(site_id=site_id)
    by_status: dict[str, int] = {}
    by_collector: dict[str, dict[str, int]] = {}
    for item in items:
        status = str(item.get("effective_status") or "unknown")
        collector = str(item.get("collector") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        collector_counts = by_collector.setdefault(collector, {})
        collector_counts[status] = collector_counts.get(status, 0) + 1
    return {
        "total": len(items),
        "by_status": by_status,
        "by_collector": by_collector,
    }
