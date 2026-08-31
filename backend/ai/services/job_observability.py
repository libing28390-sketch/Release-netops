"""Bounded Import/Reindex queue and lease observability (OBS-007).

The ingestion control-plane is still process-local until the DB-011 migration
gate, while the knowledge reindex job is durable in PostgreSQL.  This
module deliberately normalizes both sources into the same aggregate shape for
the AI metrics endpoint.  No job, tenant, worker, URL, SQL or exception text is
returned.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from ai.services.metrics import ai_metrics
from database import core as database_core
from database.core import get_db_connection
from services.ingestion_pipeline_service import ingestion_pipeline


_QUEUE_FIELDS = (
    "queued", "retry_wait", "running", "succeeded", "completed", "failed",
    "cancelled", "backlog", "lease_anomalies", "lease_expired",
    "document_failures",
)


def _empty_queue() -> dict[str, int]:
    return {key: 0 for key in _QUEUE_FIELDS}


def _threshold(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _import_queue_snapshot() -> tuple[dict[str, int], str]:
    try:
        return ingestion_pipeline.observability_snapshot(family="import"), "process_local"
    except Exception:
        # Metrics must remain available during a partial worker/control-plane
        # failure; the alert itself is represented by the next health check.
        return _empty_queue(), "unavailable"


def _reindex_queue_snapshot() -> tuple[dict[str, int], str]:
    snapshot = _empty_queue()
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, status, failed FROM ai_knowledge_reindex_job")
            rows = cursor.fetchall()
            lock_map: dict[str, Any] = {}
            try:
                cursor.execute("SELECT lock_name, expires_at FROM scheduler_locks WHERE lock_name LIKE ?", ("knowledge_reindex:%",))
                lock_map = {str(row[0]): row[1] for row in cursor.fetchall()}
            except Exception:
                # The reindex table is authoritative for queue counts; a
                # missing lock table only means lease health is unavailable.
                try:
                    conn.rollback()
                except Exception:
                    pass
            now = datetime.now(timezone.utc)
            for row in rows:
                job_id = str(row[0] or "")
                status = str(row[1] or "").strip().lower()
                if status in snapshot:
                    snapshot[status] += 1
                if status in {"queued", "retry_wait"}:
                    snapshot["backlog"] += 1
                if status == "failed":
                    try:
                        snapshot["document_failures"] += max(0, int(row[2] or 0))
                    except (TypeError, ValueError):
                        pass
                if status == "running":
                    lock_name = f"knowledge_reindex:{job_id}"
                    expires_at = lock_map.get(lock_name)
                    parsed_expiry = _parse_timestamp(expires_at)
                    if not expires_at or parsed_expiry is None or parsed_expiry <= now:
                        snapshot["lease_anomalies"] += 1
                        snapshot["lease_expired"] += 1
            return snapshot, "postgresql"
    except Exception:
        return _empty_queue(), "unavailable"


def _alerts(kind: str, queue: dict[str, int], *, source: str) -> list[dict[str, Any]]:
    if source == "unavailable":
        return []
    alerts: list[dict[str, Any]] = []
    backlog_threshold = _threshold("AI_JOB_QUEUE_BACKLOG_ALERT_THRESHOLD", 100)
    failure_threshold = _threshold("AI_JOB_FAILURE_ALERT_THRESHOLD", 1)
    lease_threshold = _threshold("AI_JOB_LEASE_ANOMALY_ALERT_THRESHOLD", 1)
    if queue["backlog"] >= backlog_threshold:
        alerts.append({
            "code": f"{kind.upper()}_QUEUE_BACKLOG",
            "severity": "warning",
            "kind": kind,
            "value": queue["backlog"],
            "threshold": backlog_threshold,
            "message": "Job queue backlog exceeded the configured threshold",
        })
    if queue["failed"] >= failure_threshold:
        alerts.append({
            "code": f"{kind.upper()}_JOB_FAILURE",
            "severity": "error",
            "kind": kind,
            "value": queue["failed"],
            "threshold": failure_threshold,
            "message": "One or more jobs are in a failed state",
        })
    if queue["lease_anomalies"] >= lease_threshold:
        alerts.append({
            "code": f"{kind.upper()}_LEASE_ANOMALY",
            "severity": "error",
            "kind": kind,
            "value": queue["lease_anomalies"],
            "threshold": lease_threshold,
            "message": "A running job has a missing or expired worker lease",
        })
    return alerts


def snapshot() -> dict[str, Any]:
    """Collect bounded queue gauges and deterministic alert conditions."""

    import_queue, import_source = _import_queue_snapshot()
    reindex_queue, reindex_source = _reindex_queue_snapshot()
    ai_metrics.set_job_queue_snapshot("import", import_queue)
    ai_metrics.set_job_queue_snapshot("reindex", reindex_queue)
    alerts = _alerts("import", import_queue, source=import_source)
    alerts.extend(_alerts("reindex", reindex_queue, source=reindex_source))
    return {
        "observed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "sources": {"import": import_source, "reindex": reindex_source},
        "queues": {"import": import_queue, "reindex": reindex_queue},
        "alerts": alerts,
        "alert_thresholds": {
            "backlog": _threshold("AI_JOB_QUEUE_BACKLOG_ALERT_THRESHOLD", 100),
            "failed": _threshold("AI_JOB_FAILURE_ALERT_THRESHOLD", 1),
            "lease_anomalies": _threshold("AI_JOB_LEASE_ANOMALY_ALERT_THRESHOLD", 1),
        },
    }


__all__ = ["snapshot"]
