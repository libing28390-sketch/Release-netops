"""Database-backed collector queue with leases and process-safe slots."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from database import _USE_PG, get_db_connection

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.isoformat()


def ensure_worker_slots(collector: str, slot_count: int) -> None:
    """Create the configured global slots; never removes existing slots."""
    count = max(1, int(slot_count or 1))
    now = _iso(_now())
    placeholder = "%s" if _USE_PG else "?"
    conn = get_db_connection()
    try:
        conn.executemany(
            f"""
            INSERT INTO collector_worker_slots
                (collector, slot_id, task_id, lease_owner, lease_until, updated_at)
            VALUES ({placeholder}, {placeholder}, NULL, '', NULL, {placeholder})
            ON CONFLICT(collector, slot_id) DO NOTHING
            """,
            [(collector, slot_id, now) for slot_id in range(count)],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def enqueue_tasks(
    collector: str,
    *,
    run_id: str,
    device_ids: list[str],
    payload_by_device: dict[str, dict[str, Any]] | None = None,
    available_at: datetime | None = None,
    priority: int = 100,
) -> int:
    """Enqueue one current task per device without replacing active leases."""
    ids = sorted({str(item) for item in device_ids if item})
    if not ids:
        return 0
    now = _now()
    available = available_at or now
    placeholder = "%s" if _USE_PG else "?"
    sql = f"""
        INSERT INTO collector_task_queue (
            id, collector, device_id, run_id, status, priority, available_at,
            lease_owner, lease_until, attempt, error_class, error_message,
            payload_json, result_json, created_at, started_at, completed_at, updated_at
        ) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, 'pending',
                  {placeholder}, {placeholder}, '', NULL, 0, '', '',
                  {placeholder}, '{{}}', {placeholder}, NULL, NULL, {placeholder})
        ON CONFLICT(collector, device_id) DO UPDATE SET
            run_id = CASE
                WHEN collector_task_queue.status = 'running'
                     AND collector_task_queue.lease_until > excluded.available_at
                    THEN collector_task_queue.run_id
                ELSE excluded.run_id
            END,
            status = CASE
                WHEN collector_task_queue.status = 'running'
                     AND collector_task_queue.lease_until > excluded.available_at
                    THEN collector_task_queue.status
                ELSE 'pending'
            END,
            priority = excluded.priority,
            available_at = CASE
                WHEN collector_task_queue.status = 'pending'
                     AND collector_task_queue.available_at > excluded.available_at
                    THEN collector_task_queue.available_at
                ELSE excluded.available_at
            END,
            lease_owner = CASE
                WHEN collector_task_queue.status = 'running'
                     AND collector_task_queue.lease_until > excluded.available_at
                    THEN collector_task_queue.lease_owner
                ELSE ''
            END,
            lease_until = CASE
                WHEN collector_task_queue.status = 'running'
                     AND collector_task_queue.lease_until > excluded.available_at
                    THEN collector_task_queue.lease_until
                ELSE NULL
            END,
            attempt = CASE
                WHEN collector_task_queue.status = 'running'
                     AND collector_task_queue.lease_until > excluded.available_at
                    THEN collector_task_queue.attempt
                ELSE 0
            END,
            error_class = CASE
                WHEN collector_task_queue.status = 'running'
                     AND collector_task_queue.lease_until > excluded.available_at
                    THEN collector_task_queue.error_class
                ELSE ''
            END,
            error_message = CASE
                WHEN collector_task_queue.status = 'running'
                     AND collector_task_queue.lease_until > excluded.available_at
                    THEN collector_task_queue.error_message
                ELSE ''
            END,
            payload_json = CASE
                WHEN collector_task_queue.status = 'running'
                     AND collector_task_queue.lease_until > excluded.available_at
                    THEN collector_task_queue.payload_json
                ELSE excluded.payload_json
            END,
            result_json = CASE
                WHEN collector_task_queue.status = 'running'
                     AND collector_task_queue.lease_until > excluded.available_at
                    THEN collector_task_queue.result_json
                ELSE '{{}}'
            END,
            completed_at = CASE
                WHEN collector_task_queue.status = 'running'
                     AND collector_task_queue.lease_until > excluded.available_at
                    THEN collector_task_queue.completed_at
                ELSE NULL
            END,
            updated_at = excluded.updated_at
    """
    values = [
        (
            f"{collector}:{device_id}", collector, device_id, run_id,
            int(priority), _iso(available),
            json.dumps((payload_by_device or {}).get(device_id) or {}, ensure_ascii=False),
            _iso(now), _iso(now),
        )
        for device_id in ids
    ]
    conn = get_db_connection()
    try:
        conn.executemany(sql, values)
        conn.commit()
        return len(ids)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_task(
    collector: str,
    *,
    worker_id: str,
    slot_count: int,
    lease_seconds: int,
) -> dict[str, Any] | None:
    """Atomically claim one pending task and one global worker slot."""
    now = _now()
    now_iso = _iso(now)
    lease_until = _iso(now + timedelta(seconds=max(30, int(lease_seconds or 30))))
    placeholder = "%s" if _USE_PG else "?"
    conn = get_db_connection()
    try:
        if not _USE_PG:
            conn.execute("BEGIN IMMEDIATE")

        conn.execute(
            f"""
            UPDATE collector_task_queue
               SET status = 'pending', lease_owner = '', lease_until = NULL,
                   updated_at = {placeholder}
             WHERE collector = {placeholder} AND status = 'running'
               AND lease_until IS NOT NULL AND lease_until <= {placeholder}
            """,
            (now_iso, collector, now_iso),
        )
        conn.execute(
            f"""
            UPDATE collector_worker_slots
               SET task_id = NULL, lease_owner = '', lease_until = NULL,
                   updated_at = {placeholder}
             WHERE collector = {placeholder}
               AND lease_until IS NOT NULL AND lease_until <= {placeholder}
            """,
            (now_iso, collector, now_iso),
        )

        lock_suffix = " FOR UPDATE SKIP LOCKED" if _USE_PG else ""
        slot = conn.execute(
            f"""
            SELECT slot_id FROM collector_worker_slots
             WHERE collector = {placeholder} AND task_id IS NULL
               AND slot_id < {placeholder}
             ORDER BY slot_id LIMIT 1{lock_suffix}
            """,
            (collector, max(1, int(slot_count or 1))),
        ).fetchone()
        if not slot:
            conn.commit()
            return None

        task = conn.execute(
            f"""
            SELECT * FROM collector_task_queue
             WHERE collector = {placeholder}
               AND status = 'pending'
               AND available_at <= {placeholder}
             ORDER BY priority, available_at, id
             LIMIT 1{lock_suffix}
            """,
            (collector, now_iso),
        ).fetchone()
        if not task:
            conn.commit()
            return None

        slot_id = int(slot[0])
        task_id = str(task["id"] if hasattr(task, "keys") else task[0])
        conn.execute(
            f"""
            UPDATE collector_task_queue
               SET status = 'running', lease_owner = {placeholder},
                   lease_until = {placeholder}, attempt = attempt + 1,
                   started_at = COALESCE(started_at, {placeholder}),
                   updated_at = {placeholder}
             WHERE id = {placeholder} AND status = 'pending'
            """,
            (worker_id, lease_until, now_iso, now_iso, task_id),
        )
        conn.execute(
            f"""
            UPDATE collector_worker_slots
               SET task_id = {placeholder}, lease_owner = {placeholder},
                   lease_until = {placeholder}, updated_at = {placeholder}
             WHERE collector = {placeholder} AND slot_id = {placeholder}
            """,
            (task_id, worker_id, lease_until, now_iso, collector, slot_id),
        )
        conn.commit()
        result = dict(task) if hasattr(task, "keys") else dict(task)
        result.update({
            "status": "running",
            "attempt": int(result.get("attempt") or 0) + 1,
            "started_at": result.get("started_at") or now_iso,
            "slot_id": slot_id,
            "lease_owner": worker_id,
            "lease_until": lease_until,
        })
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish_task(
    task: dict[str, Any],
    *,
    worker_id: str,
    success: bool,
    retry_at: datetime | None = None,
    error_class: str = "",
    error_message: str = "",
    result: dict[str, Any] | None = None,
) -> None:
    """Release the worker slot and finish or requeue the leased task."""
    now = _now()
    task_id = str(task.get("id") or "")
    collector = str(task.get("collector") or "")
    next_status = "succeeded" if success else ("pending" if retry_at else "failed")
    available = _iso(retry_at or now)
    placeholder = "%s" if _USE_PG else "?"
    conn = get_db_connection()
    try:
        conn.execute(
            f"""
            UPDATE collector_task_queue
               SET status = {placeholder}, available_at = {placeholder},
                   lease_owner = '', lease_until = NULL,
                   error_class = {placeholder}, error_message = {placeholder},
                result_json = {placeholder}, completed_at = {placeholder},
                   updated_at = {placeholder}
             WHERE id = {placeholder} AND status = 'running'
               AND lease_owner = {placeholder}
            """,
            (
                next_status, available, str(error_class or "")[:40],
                str(error_message or "")[:500],
                json.dumps(result or {}, ensure_ascii=False), _iso(now),
                _iso(now), task_id, worker_id,
            ),
        )
        conn.execute(
            f"""
            UPDATE collector_worker_slots
               SET task_id = NULL, lease_owner = '', lease_until = NULL,
                   updated_at = {placeholder}
             WHERE collector = {placeholder} AND task_id = {placeholder}
               AND lease_owner = {placeholder}
            """,
            ( _iso(now), collector, task_id, worker_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def queue_summary(collector: str) -> dict[str, int]:
    """Return lightweight queue counters for health/status pages."""
    conn = get_db_connection()
    try:
        placeholder = "%s" if _USE_PG else "?"
        rows = conn.execute(
            f"SELECT status, COUNT(*) AS count FROM collector_task_queue WHERE collector = {placeholder} GROUP BY status",
            (collector,),
        ).fetchall()
        summary = {str(row[0]): int(row[1]) for row in rows}
        summary["total"] = sum(summary.values())
        return summary
    except Exception:
        return {}
    finally:
        conn.close()
