from datetime import datetime
from fastapi import APIRouter, Query, Body, HTTPException
from database import get_db_connection

router = APIRouter()


@router.get('/notifications')
def list_notifications(
    limit: int = Query(default=30, ge=1, le=200),
    user_id: str | None = Query(default=None),
):
    """Build notification feed from recent jobs and playbook executions."""
    conn = get_db_connection()
    try:
        notifications = []

        jobs = conn.execute(
            'SELECT id, task_name, status, created_at FROM jobs ORDER BY created_at DESC LIMIT ?',
            (limit,)
        ).fetchall()

        for job in jobs:
            status = (job['status'] or '').lower()
            severity = 'high' if status == 'failed' else ('low' if status == 'success' else 'medium')
            title = 'Automation task failed' if status == 'failed' else ('Automation task completed' if status == 'success' else 'Automation task updated')
            notifications.append({
                'id': f"job-{job['id']}",
                'source': 'job',
                'title': title,
                'message': f"{job['task_name']} ({job['status']})",
                'severity': severity,
                'time': job['created_at'],
                'read': False,
            })

        playbooks = conn.execute(
            'SELECT id, scenario_name, status, created_at, dry_run FROM playbook_executions ORDER BY created_at DESC LIMIT ?',
            (limit,)
        ).fetchall()

        for pb in playbooks:
            status = (pb['status'] or '').lower()
            severity = 'high' if status in ('failed', 'error') else ('low' if status in ('success', 'dry_run_complete') else 'medium')
            mode = 'dry-run' if int(pb['dry_run'] or 0) == 1 else 'execute'
            title = 'Playbook failed' if severity == 'high' else 'Playbook update'
            notifications.append({
                'id': f"playbook-{pb['id']}",
                'source': 'playbook',
                'title': title,
                'message': f"{pb['scenario_name']} [{mode}] ({pb['status']})",
                'severity': severity,
                'time': pb['created_at'],
                'read': False,
            })

        alerts = conn.execute(
            '''
            SELECT id, source, severity, title, message, created_at, resolved_at
            FROM alert_events
            ORDER BY created_at DESC
            LIMIT ?
            ''',
            (limit,)
        ).fetchall()
        for alert in alerts:
            resolved = bool(alert['resolved_at'])
            notifications.append({
                'id': f"alert-{alert['id']}",
                'source': alert['source'] or 'alert',
                'title': alert['title'],
                'message': f"{alert['message']}{' (resolved)' if resolved else ''}",
                'severity': (alert['severity'] or 'medium').lower(),
                'time': alert['created_at'],
                'read': False,
            })

        read_ids = set()
        if user_id:
            rows = conn.execute(
                'SELECT notification_id FROM notification_reads WHERE user_id = ?',
                (user_id,)
            ).fetchall()
            read_ids = {r['notification_id'] for r in rows}

        notifications.sort(key=lambda x: x['time'] or '', reverse=True)
        merged = notifications[:limit]
        for item in merged:
            item['read'] = item['id'] in read_ids
        return merged
    finally:
        conn.close()


@router.post('/notifications/read')
def mark_notifications_read(payload: dict = Body(...)):
    user_id = (payload.get('user_id') or '').strip()
    notification_ids = payload.get('notification_ids') or []
    if not user_id:
        raise HTTPException(status_code=400, detail='user_id is required')
    if not isinstance(notification_ids, list) or not notification_ids:
        raise HTTPException(status_code=400, detail='notification_ids must be a non-empty array')

    now = datetime.now().isoformat()
    conn = get_db_connection()
    try:
        conn.executemany(
            '''
            INSERT INTO notification_reads (user_id, notification_id, read_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, notification_id) DO UPDATE SET read_at=excluded.read_at
            ''',
            [(user_id, str(nid), now) for nid in notification_ids]
        )
        conn.commit()
        return {'success': True, 'updated': len(notification_ids)}
    finally:
        conn.close()
