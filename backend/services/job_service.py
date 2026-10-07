"""Unified enterprise job lifecycle and target-level concurrency controls."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from database import _USE_PG, get_db_connection
from services.audit_service import log_audit_event


TERMINAL_STATUSES = {'succeeded', 'partially_failed', 'failed', 'cancelled', 'timeout'}
JOB_STATUSES = {'queued', 'running', *TERMINAL_STATUSES}
TARGET_STATUSES = {'queued', 'running', 'succeeded', 'failed', 'cancelled', 'timeout'}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=True, default=str)


def add_job_event(conn, job_id: str, event_type: str, message: str, *, severity: str = 'info', details: dict | None = None) -> str:
    event_id = f"job-event-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """INSERT INTO job_events (id, job_id, event_type, severity, message, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (event_id, job_id, event_type, severity, message, _json(details), _now()),
    )
    return event_id


def create_job(
    *, job_type: str, task_name: str, created_by: str,
    targets: list[dict], steps: list[str] | None = None,
    concurrency_limit: int = 5, retry_limit: int = 0,
    timeout_seconds: int = 300, scope: dict | None = None,
    job_id: str | None = None,
) -> dict:
    if not targets:
        raise ValueError('At least one job target is required')
    if concurrency_limit < 1 or concurrency_limit > 200:
        raise ValueError('concurrency_limit must be between 1 and 200')
    job_id = job_id or f"job-{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO jobs
               (id, device_id, task_name, status, output, created_at, job_type,
                created_by, updated_at, progress, total_targets, success_count,
                failed_count, cancel_requested, error_summary, concurrency_limit,
                retry_limit, timeout_seconds, scope_json)
               VALUES (?, NULL, ?, 'queued', '', ?, ?, ?, ?, 0, ?, 0, 0, 0, '', ?, ?, ?, ?)""",
            (job_id, task_name, now, job_type, created_by, now, len(targets),
             concurrency_limit, max(0, retry_limit), max(1, timeout_seconds), _json(scope)),
        )
        for order, step in enumerate(steps or ['execute']):
            conn.execute(
                """INSERT INTO job_steps
                   (id, job_id, step_name, step_order, status, result_json)
                   VALUES (?, ?, ?, ?, 'queued', '{}')""",
                (f"job-step-{uuid.uuid4().hex[:12]}", job_id, step, order),
            )
        for target in targets:
            target_id = str(target.get('target_id') or target.get('device_id') or '').strip()
            if not target_id:
                raise ValueError('Each job target requires target_id')
            site_id = target.get('site_id')
            vendor = target.get('vendor')
            if target.get('target_type', 'device') == 'device' and (not site_id or not vendor):
                device_row = conn.execute(
                    "SELECT site_id, vendor FROM devices WHERE id = ?", (target_id,)
                ).fetchone()
                if device_row:
                    site_id = site_id or device_row['site_id']
                    vendor = vendor or device_row['vendor']
            conn.execute(
                """INSERT INTO job_targets
                   (id, job_id, target_type, target_id, site_id, vendor, status, result_json)
                   VALUES (?, ?, ?, ?, ?, ?, 'queued', '{}')""",
                (f"job-target-{uuid.uuid4().hex[:12]}", job_id,
                 target.get('target_type', 'device'), target_id,
                 site_id, vendor),
            )
        add_job_event(conn, job_id, 'created', f'Job created with {len(targets)} targets')
        log_audit_event(
            event_type='job.create', category='job', severity='info', status='success',
            summary=f'Created {job_type} job {job_id}', actor_username=created_by,
            target_type='job', target_id=job_id, job_id=job_id,
            after={'job_type': job_type, 'targets': len(targets), 'concurrency_limit': concurrency_limit},
            conn=conn,
        )
        conn.commit()
        return get_job(job_id, conn=conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_job(
    job_id: str,
    *,
    conn=None,
    target_statuses: set[str] | None = None,
    target_limit: int | None = None,
) -> dict:
    own_conn = conn is None
    conn = conn or get_db_connection()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise ValueError('Job not found')
        item = dict(row)
        try:
            target_params: list[Any] = [job_id]
            target_filter = ''
            if target_statuses:
                statuses = sorted({str(status) for status in target_statuses if str(status) in TARGET_STATUSES})
                if statuses:
                    target_filter = f" AND jt.status IN ({','.join('?' for _ in statuses)})"
                    target_params.extend(statuses)
            target_limit_sql = ''
            if target_limit is not None:
                target_limit_sql = ' LIMIT ?'
                target_params.append(max(1, int(target_limit)))
            target_rows = conn.execute(
                f"""SELECT jt.*, d.hostname AS target_hostname, d.ip_address AS target_ip
                   FROM job_targets jt
                   LEFT JOIN devices d
                     ON jt.target_type = 'device' AND d.id = jt.target_id
                   WHERE jt.job_id = ?{target_filter}
                   ORDER BY jt.status, jt.id{target_limit_sql}""",
                tuple(target_params),
            ).fetchall()
        except Exception:
            # Keep generic job reads usable during bootstrap databases where
            # the devices table has not been created yet.
            target_rows = conn.execute(
                "SELECT * FROM job_targets WHERE job_id = ? ORDER BY id", (job_id,)
            ).fetchall()
        item['targets'] = [dict(value) for value in target_rows]
        status_counts = conn.execute(
            "SELECT status, COUNT(*) AS count FROM job_targets WHERE job_id = ? GROUP BY status",
            (job_id,),
        ).fetchall()
        item['target_status_counts'] = {str(value['status']): int(value['count'] or 0) for value in status_counts}
        item['targets_truncated'] = bool(target_limit is not None and sum(item['target_status_counts'].values()) > len(item['targets']))
        item['steps'] = [dict(value) for value in conn.execute(
            "SELECT * FROM job_steps WHERE job_id = ? ORDER BY step_order", (job_id,)
        ).fetchall()]
        item['events'] = [dict(value) for value in conn.execute(
            "SELECT * FROM job_events WHERE job_id = ? ORDER BY created_at DESC LIMIT 200", (job_id,)
        ).fetchall()]
        return item
    finally:
        if own_conn:
            conn.close()


def request_cancel(job_id: str, *, requested_by: str) -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise ValueError('Job not found')
        if row['status'] in TERMINAL_STATUSES:
            raise ValueError(f"Job is already {row['status']}")
        now = _now()
        conn.execute("UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE id = ?", (now, job_id))
        conn.execute("UPDATE job_targets SET status = 'cancelled', finished_at = ? WHERE job_id = ? AND status = 'queued'", (now, job_id))
        add_job_event(conn, job_id, 'cancel_requested', f'Cancellation requested by {requested_by}', severity='warning')
        conn.commit()
        _refresh_job(conn, job_id)
        conn.commit()
        return get_job(job_id, conn=conn)
    finally:
        conn.close()


def claim_targets(job_id: str, *, limit: int | None = None) -> list[dict]:
    """Atomically claim runnable targets while respecting job and device locks."""
    conn = get_db_connection()
    try:
        job_sql = "SELECT * FROM jobs WHERE id = ?" + (" FOR UPDATE" if _USE_PG else '')
        job_row = conn.execute(job_sql, (job_id,)).fetchone()
        if not job_row:
            raise ValueError('Job not found')
        job = dict(job_row)
        if job['status'] in TERMINAL_STATUSES or job.get('cancel_requested'):
            return []
        running = conn.execute("SELECT COUNT(*) AS count FROM job_targets WHERE job_id = ? AND status = 'running'", (job_id,)).fetchone()['count']
        capacity = max(0, min(limit or job['concurrency_limit'], job['concurrency_limit'] - int(running or 0)))
        if capacity == 0:
            return []
        suffix = " FOR UPDATE SKIP LOCKED" if _USE_PG else ''
        candidates = conn.execute(
            f"SELECT * FROM job_targets WHERE job_id = ? AND status = 'queued' ORDER BY id LIMIT ?{suffix}",
            (job_id, capacity * 4),
        ).fetchall()
        claimed = []
        try:
            scope = json.loads(job.get('scope_json') or '{}')
        except Exception:
            scope = {}
        site_limit = max(1, int(scope.get('site_concurrency') or job['concurrency_limit']))
        vendor_limit = max(1, int(scope.get('vendor_concurrency') or job['concurrency_limit']))
        for row in candidates:
            if len(claimed) >= capacity:
                break
            target = dict(row)
            conflict = conn.execute(
                """SELECT 1 FROM job_targets
                   WHERE target_type = ? AND target_id = ? AND status = 'running' AND job_id <> ? LIMIT 1""",
                (target['target_type'], target['target_id'], job_id),
            ).fetchone()
            if conflict:
                continue
            if target.get('site_id'):
                site_running = conn.execute(
                    "SELECT COUNT(*) AS count FROM job_targets WHERE site_id = ? AND status = 'running'",
                    (target['site_id'],),
                ).fetchone()['count']
                if int(site_running or 0) >= site_limit:
                    continue
            if target.get('vendor'):
                vendor_running = conn.execute(
                    "SELECT COUNT(*) AS count FROM job_targets WHERE vendor = ? AND status = 'running'",
                    (target['vendor'],),
                ).fetchone()['count']
                if int(vendor_running or 0) >= vendor_limit:
                    continue
            conn.execute(
                "UPDATE job_targets SET status = 'running', attempt_count = attempt_count + 1, started_at = ? WHERE id = ? AND status = 'queued'",
                (_now(), target['id']),
            )
            target['status'] = 'running'
            target['attempt_count'] = int(target.get('attempt_count') or 0) + 1
            claimed.append(target)
        if claimed:
            now = _now()
            conn.execute(
                "UPDATE jobs SET status = 'running', started_at = COALESCE(started_at, ?), updated_at = ? WHERE id = ?",
                (now, now, job_id),
            )
            add_job_event(conn, job_id, 'targets_claimed', f'Claimed {len(claimed)} targets', details={'target_ids': [item['target_id'] for item in claimed]})
        conn.commit()
        return claimed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def complete_target(target_row_id: str, *, status: str, result: dict | None = None, error_message: str = '') -> dict:
    if status not in TARGET_STATUSES - {'queued', 'running'}:
        raise ValueError(f'Invalid terminal target status: {status}')
    conn = get_db_connection()
    try:
        target = conn.execute(
            """SELECT jt.*, j.cancel_requested FROM job_targets jt
               JOIN jobs j ON j.id = jt.job_id WHERE jt.id = ?""",
            (target_row_id,),
        ).fetchone()
        if not target:
            raise ValueError('Job target not found')
        if target['cancel_requested']:
            status = 'cancelled'
            result = {'discarded': True, 'reason': 'job_cancelled'}
            error_message = 'Result discarded because cancellation was requested'
        conn.execute(
            """UPDATE job_targets SET status = ?, finished_at = ?, result_json = ?, error_message = ?
               WHERE id = ?""",
            (status, _now(), _json(result), error_message, target_row_id),
        )
        add_job_event(conn, target['job_id'], 'target_completed', f"Target {target['target_id']} completed as {status}", severity='error' if status in ('failed', 'timeout') else 'info')
        _refresh_job(conn, target['job_id'])
        conn.commit()
        return get_job(target['job_id'], conn=conn)
    finally:
        conn.close()


def retry_failed_targets(job_id: str, *, requested_by: str) -> dict:
    conn = get_db_connection()
    try:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            raise ValueError('Job not found')
        count = conn.execute(
            """UPDATE job_targets SET status = 'queued', started_at = NULL, finished_at = NULL,
               error_message = '' WHERE job_id = ? AND status IN ('failed', 'timeout')
               AND attempt_count <= ?""",
            (job_id, int(job['retry_limit'] or 0)),
        ).rowcount
        if count:
            conn.execute("UPDATE jobs SET status = 'queued', cancel_requested = 0, finished_at = NULL, updated_at = ? WHERE id = ?", (_now(), job_id))
            add_job_event(conn, job_id, 'retry', f'{count} failed targets queued by {requested_by}', severity='warning')
        conn.commit()
        return {'job_id': job_id, 'queued': count}
    finally:
        conn.close()


def _refresh_job(conn, job_id: str) -> None:
    counts = {row['status']: int(row['count']) for row in conn.execute(
        "SELECT status, COUNT(*) AS count FROM job_targets WHERE job_id = ? GROUP BY status", (job_id,)
    ).fetchall()}
    total = sum(counts.values())
    success = counts.get('succeeded', 0)
    failed = counts.get('failed', 0) + counts.get('timeout', 0)
    cancelled = counts.get('cancelled', 0)
    completed = success + failed + cancelled
    progress = int((completed / total) * 100) if total else 0
    if completed == total and total:
        if cancelled == total:
            status = 'cancelled'
        elif failed == total:
            status = 'failed'
        elif failed or cancelled:
            status = 'partially_failed'
        else:
            status = 'succeeded'
        finished_at = _now()
    elif counts.get('running', 0):
        status, finished_at = 'running', None
    else:
        status, finished_at = 'queued', None
    conn.execute(
        """UPDATE jobs SET status = ?, progress = ?, success_count = ?, failed_count = ?,
           finished_at = ?, updated_at = ? WHERE id = ?""",
        (status, progress, success, failed, finished_at, _now(), job_id),
    )
