import json
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Body, HTTPException, Query, Depends
from core.rbac import require_role
from core.config import settings
from services.config_approval_service import verify_code, consume_approval
from database import get_db_connection
from services import alert_maintenance_service
from services import alert_rule_service
from services.audit_service import log_audit_event
from services.alert_control_service import AlertState, check_no_data, compute_health, correlate_alerts, detect_storm, suppress_dependency_alerts, transition_state


router = APIRouter()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _verify_alert_rule_approval(payload: dict, approval_type: str = 'alert_rule'):
    is_test_env = getattr(settings, 'ENVIRONMENT', 'development') != 'production'
    skip_approval_verification = payload.get("skip_approval_verification", False) if is_test_env else False
    
    if skip_approval_verification:
        return
        
    approval_token = (payload.get("approval_token") or "").strip()
    approval_code = (payload.get("approval_code") or "").strip()
    
    if not approval_token or not approval_code:
        raise HTTPException(
            status_code=400,
            detail="安全校验失败：执行此修改必须提供有效工单审批码。请先获取验证码验证。" if not is_test_env else "安全校验失败：必须提供有效工单审批码（或在测试环境使用 skip_approval_verification=true 绕过）"
        )
        
    ok, err = verify_code(approval_token, approval_code)
    if not ok:
        raise HTTPException(status_code=403, detail=err)
        
    # Consume it
    consume_approval(approval_token)


def _normalize_workflow_status(row: dict) -> str:
    status = str(row.get('workflow_status') or '').strip().lower()
    if row.get('resolved_at'):
        return 'resolved'
    if status in {'acknowledged', 'investigating', 'suppressed'}:
        return status
    return 'open'


def _row_to_alert(row) -> dict:
    item = dict(row)
    item['workflow_status'] = _normalize_workflow_status(item)
    created_at = item.get('created_at')
    resolved_at = item.get('resolved_at')
    duration_seconds = None
    try:
        start_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00')) if created_at else None
        end_dt = datetime.fromisoformat(resolved_at.replace('Z', '+00:00')) if resolved_at else datetime.now(timezone.utc)
        if start_dt:
            duration_seconds = max(0, int((end_dt - start_dt).total_seconds()))
    except Exception:
        duration_seconds = None
    item['duration_seconds'] = duration_seconds
    item['is_open'] = resolved_at is None
    item['note'] = item.get('note') or ''
    return item


@router.get('/alerts/{alert_id}/activity')
def list_alert_activity(alert_id: str, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    """Return metadata-only state transitions for one alert."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, alert_id, event_type, actor_id, from_state, to_state, note, metadata_json, created_at FROM alert_activity WHERE alert_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (alert_id, limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item['metadata'] = json.loads(item.pop('metadata_json') or '{}')
            except Exception:
                item['metadata'] = {}
            items.append(item)
        return {'items': items, 'alert_id': alert_id, 'limit': limit, 'offset': offset}
    except Exception:
        # Keep the endpoint compatible with installations before m0105.
        return {'items': [], 'alert_id': alert_id, 'limit': limit, 'offset': offset}
    finally:
        conn.close()


@router.get('/alerts/{alert_id}/correlations')
def list_alert_correlations(alert_id: str, limit: int = Query(default=100, ge=1, le=500)):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, alert_id, root_alert_id, correlation_type, confidence, evidence_json, created_at FROM alert_correlations WHERE alert_id = ? ORDER BY confidence DESC, created_at DESC LIMIT ?",
            (alert_id, limit),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item['evidence'] = json.loads(item.pop('evidence_json') or '[]')
            except Exception:
                item['evidence'] = []
            items.append(item)
        return {'items': items, 'alert_id': alert_id}
    except Exception:
        return {'items': [], 'alert_id': alert_id}
    finally:
        conn.close()


@router.get('/alerts/storms')
def list_alert_storms(limit: int = Query(default=50, ge=1, le=200), status: str = Query(default='open')):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, tenant_id, fingerprint, window_start, window_end, alert_count, site_count, type_count, status, metadata_json FROM alert_storms WHERE status = ? ORDER BY window_start DESC LIMIT ?",
            (status, limit),
        ).fetchall()
        return {'items': [dict(row) for row in rows]}
    except Exception:
        return {'items': []}
    finally:
        conn.close()


@router.post('/alerts/dry-run')
def alert_rule_dry_run(payload: dict = Body(...)):
    """Evaluate lifecycle policy without changing alert_events or notifications."""
    state = AlertState(state=str(payload.get('state') or 'OK'))
    transition = transition_state(
        state,
        breached=bool(payload.get('breached', False)),
        for_seconds=int(payload.get('for_seconds') or 0),
        recovery_threshold=int(payload.get('recovery_threshold') or 1),
        recovery_seconds=int(payload.get('recovery_seconds') or 0),
    )
    return {
        'state': transition.state,
        'emit': transition.emit,
        'event': transition.event,
        'reason': transition.reason,
        'counters': {'breach_count': state.breach_count, 'recovery_count': state.recovery_count},
        'side_effects': [],
    }


@router.post('/alerts/analyze-batch')
def analyze_alert_batch(payload: dict = Body(...)):
    """Return explainable correlation/suppression/storm results without writes."""
    alerts = payload.get('alerts') if isinstance(payload.get('alerts'), list) else []
    edges = payload.get('edges') if isinstance(payload.get('edges'), list) else []
    correlations = correlate_alerts(alerts)
    suppressed = suppress_dependency_alerts(alerts, edges)
    storm = detect_storm(alerts, count_threshold=int(payload.get('storm_threshold') or 20))
    return {'alerts': suppressed, 'correlations': correlations, 'storm': storm, 'external_calls': 0}


def _parse_optional_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail='last_sample_at must be an ISO timestamp') from exc


@router.post('/alerts/health/evaluate')
def evaluate_alert_health(payload: dict = Body(...)):
    """Evaluate health/no-data evidence without creating an alert or probing out."""
    return {
        'health': compute_health(
            icmp=payload.get('icmp'),
            snmp=payload.get('snmp'),
            ssh=payload.get('ssh'),
        ),
        'no_data': check_no_data(
            _parse_optional_timestamp(payload.get('last_sample_at')),
            threshold_seconds=int(payload.get('no_data_seconds') or 300),
        ),
        'external_calls': 0,
    }


@router.get('/alerts/silences')
def list_alert_silences(status: str = Query(default='active'), limit: int = Query(default=100, ge=1, le=500)):
    """List notification silences separately from scheduled maintenance."""
    conn = get_db_connection()
    try:
        now = _utc_now_iso()
        conn.execute("UPDATE alert_silences SET status = 'expired' WHERE status = 'active' AND ends_at < ?", (now,))
        params: list = []
        where = ""
        if status != 'all':
            where = "WHERE status = ?"
            params.append(status)
        rows = conn.execute(
            f"SELECT id, tenant_id, scope_json, reason, starts_at, ends_at, created_by, status FROM alert_silences {where} ORDER BY starts_at DESC LIMIT ?",
            tuple([*params, limit]),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item['scope'] = json.loads(item.pop('scope_json') or '{}')
            except (TypeError, ValueError):
                item['scope'] = {}
            items.append(item)
        conn.commit()
        return {'items': items}
    except Exception as exc:
        raise HTTPException(status_code=503, detail='Alert silence storage is not available') from exc
    finally:
        conn.close()


@router.post('/alerts/silences')
def create_alert_silence(payload: dict = Body(...)):
    """Create a temporary notification silence; raw alert state is preserved."""
    reason = str(payload.get('reason') or '').strip()
    if not reason:
        raise HTTPException(status_code=400, detail='reason is required')
    scope = payload.get('scope') if isinstance(payload.get('scope'), dict) else {}
    starts_at = str(payload.get('starts_at') or _utc_now_iso())
    ends_at = str(payload.get('ends_at') or '')
    if not ends_at:
        raise HTTPException(status_code=400, detail='ends_at is required')
    try:
        start_dt = datetime.fromisoformat(starts_at.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(ends_at.replace('Z', '+00:00'))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if start_dt >= end_dt:
            raise ValueError
    except ValueError as exc:
        raise HTTPException(status_code=422, detail='ends_at must be later than starts_at') from exc
    silence_id = f"silence_{uuid.uuid4().hex[:16]}"
    now = _utc_now_iso()
    created_by = str(payload.get('created_by') or 'system')[:128]
    tenant_id = str(payload.get('tenant_id') or 'tenant-default')[:128]
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO alert_silences (id, tenant_id, scope_json, reason, starts_at, ends_at, created_by, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)",
            (silence_id, tenant_id, json.dumps(scope, ensure_ascii=False), reason, starts_at, ends_at, created_by, now),
        )
        conn.commit()
        return {'id': silence_id, 'tenant_id': tenant_id, 'scope': scope, 'reason': reason, 'starts_at': starts_at, 'ends_at': ends_at, 'created_by': created_by, 'status': 'active', 'created_at': now}
    except Exception as exc:
        raise HTTPException(status_code=503, detail='Alert silence storage is not available') from exc
    finally:
        conn.close()


@router.post('/alerts/silences/{silence_id}/expire')
def expire_alert_silence(silence_id: str, payload: dict = Body(default={} )):
    conn = get_db_connection()
    try:
        result = conn.execute("UPDATE alert_silences SET status = 'expired' WHERE id = ? AND status = 'active'", (silence_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail='Active silence not found')
        conn.commit()
        return {'success': True, 'id': silence_id, 'status': 'expired', 'actor': payload.get('actor_username') or 'system'}
    finally:
        conn.close()


@router.get('/alerts/summary')
def get_alert_summary():
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc)
        since_24h = (now - timedelta(hours=24)).replace(microsecond=0).isoformat()
        open_count = conn.execute("SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NULL AND COALESCE(workflow_status, 'open') != 'suppressed'").fetchone()['c']
        critical_open = conn.execute("SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NULL AND COALESCE(workflow_status, 'open') != 'suppressed' AND LOWER(severity) = 'critical'").fetchone()['c']
        major_open = conn.execute("SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NULL AND COALESCE(workflow_status, 'open') != 'suppressed' AND LOWER(severity) = 'major'").fetchone()['c']
        warning_open = conn.execute("SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NULL AND COALESCE(workflow_status, 'open') != 'suppressed' AND LOWER(severity) = 'warning'").fetchone()['c']
        acknowledged_open = conn.execute("SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NULL AND workflow_status = 'acknowledged'").fetchone()['c']
        suppressed_open = conn.execute("SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NULL AND workflow_status = 'suppressed'").fetchone()['c']
        assigned_open = conn.execute("SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NULL AND assignee IS NOT NULL AND assignee != ''").fetchone()['c']
        alerts_24h = conn.execute('SELECT COUNT(*) AS c FROM alert_events WHERE created_at >= ?', (since_24h,)).fetchone()['c']
        resolved_24h = conn.execute('SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NOT NULL AND resolved_at >= ?', (since_24h,)).fetchone()['c']
        mttr_rows = conn.execute(
            '''
            SELECT created_at, resolved_at FROM alert_events
            WHERE resolved_at IS NOT NULL AND resolved_at >= ?
            ORDER BY resolved_at DESC
            LIMIT 200
            ''',
            (since_24h,),
        ).fetchall()
        mttr_minutes = []
        for row in mttr_rows:
            try:
                created_dt = datetime.fromisoformat(str(row['created_at']).replace('Z', '+00:00'))
                resolved_dt = datetime.fromisoformat(str(row['resolved_at']).replace('Z', '+00:00'))
                mttr_minutes.append(max(0, (resolved_dt - created_dt).total_seconds() / 60.0))
            except Exception:
                continue
        ack_rows = conn.execute(
            '''
            SELECT created_at, ack_at FROM alert_events
            WHERE ack_at IS NOT NULL
            ORDER BY ack_at DESC
            LIMIT 200
            '''
        ).fetchall()
        mtta_minutes = []
        for row in ack_rows:
            try:
                created_dt = datetime.fromisoformat(str(row['created_at']).replace('Z', '+00:00'))
                ack_dt = datetime.fromisoformat(str(row['ack_at']).replace('Z', '+00:00'))
                mtta_minutes.append(max(0, (ack_dt - created_dt).total_seconds() / 60.0))
            except Exception:
                continue
        return {
            'open_count': int(open_count),
            'critical_open': int(critical_open),
            'major_open': int(major_open),
            'warning_open': int(warning_open),
            'acknowledged_open': int(acknowledged_open),
            'suppressed_open': int(suppressed_open),
            'assigned_open': int(assigned_open),
            'alerts_24h': int(alerts_24h),
            'resolved_24h': int(resolved_24h),
            'avg_mttr_minutes': round(sum(mttr_minutes) / len(mttr_minutes), 1) if mttr_minutes else None,
            'avg_mtta_minutes': round(sum(mtta_minutes) / len(mtta_minutes), 1) if mtta_minutes else None,
        }
    finally:
        conn.close()


@router.get('/alerts')
def list_alerts(
    status: str = Query(default='open'),
    severity: str = Query(default='all'),
    search: str = Query(default=''),
    site: str = Query(default='all'),
    assignee: str = Query(default='all'),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    created_from: str = Query(default='', description='Filter alerts created on or after this ISO timestamp'),
    created_to: str = Query(default='', description='Filter alerts created on or before this ISO timestamp'),
):
    conn = get_db_connection()
    try:
        where = []
        params = []

        status_value = (status or 'open').lower()
        if status_value == 'open':
            where.append('a.resolved_at IS NULL AND COALESCE(a.workflow_status, \'open\') = \'open\'')
        elif status_value == 'acknowledged':
            where.append("a.resolved_at IS NULL AND a.workflow_status = 'acknowledged'")
        elif status_value == 'investigating':
            where.append("a.resolved_at IS NULL AND a.workflow_status = 'investigating'")
        elif status_value == 'suppressed':
            where.append("a.resolved_at IS NULL AND a.workflow_status = 'suppressed'")
        elif status_value == 'resolved':
            where.append('a.resolved_at IS NOT NULL')
        elif status_value == 'all_active':
            where.append('a.resolved_at IS NULL')

        severity_value = (severity or 'all').lower()
        if severity_value != 'all':
            where.append('LOWER(a.severity) = ?')
            params.append(severity_value)

        site_value = (site or 'all').strip()
        if site_value and site_value.lower() != 'all':
            where.append('COALESCE(d.site, \'\') = ?')
            params.append(site_value)

        assignee_value = (assignee or 'all').strip()
        if assignee_value and assignee_value.lower() != 'all':
            if assignee_value == '__unassigned__':
                where.append("(a.assignee IS NULL OR a.assignee = '')")
            else:
                where.append('a.assignee = ?')
                params.append(assignee_value)

        search_value = (search or '').strip()
        if search_value:
            q = f"%{search_value}%"
            where.append('''(
                a.title LIKE ? OR a.message LIKE ? OR a.dedupe_key LIKE ? OR
                a.interface_name LIKE ? OR COALESCE(d.hostname, '') LIKE ? OR COALESCE(d.ip_address, '') LIKE ?
            )''')
            params.extend([q, q, q, q, q, q])

        created_from_value = (created_from or '').strip()
        if created_from_value:
            where.append('a.created_at >= ?')
            params.append(created_from_value)

        created_to_value = (created_to or '').strip()
        if created_to_value:
            where.append('a.created_at <= ?')
            params.append(created_to_value)

        where_sql = f"WHERE {' AND '.join(where)}" if where else ''
        total = conn.execute(
            f'''
            SELECT COUNT(*) AS c
            FROM alert_events a
            LEFT JOIN devices d ON d.id = a.device_id
            {where_sql}
            ''',
            tuple(params),
        ).fetchone()['c']

        offset = (page - 1) * page_size
        rows = conn.execute(
            f'''
            SELECT
                a.id, a.dedupe_key, a.source, a.severity, a.title, a.message,
                a.device_id, a.interface_name, a.created_at, a.resolved_at,
                a.workflow_status, a.assignee, a.ack_by, a.ack_at, a.note, a.updated_at,
                d.hostname, d.ip_address, d.site,
                (
                    SELECT COUNT(*) FROM alert_events a2
                    WHERE a2.dedupe_key = a.dedupe_key
                ) AS occurrence_count
            FROM alert_events a
            LEFT JOIN devices d ON d.id = a.device_id
            {where_sql}
            ORDER BY
                CASE WHEN a.resolved_at IS NULL THEN 0 ELSE 1 END ASC,
                CASE LOWER(a.severity)
                    WHEN 'critical' THEN 0
                    WHEN 'major' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                END ASC,
                COALESCE(a.updated_at, a.created_at) DESC
            LIMIT ? OFFSET ?
            ''',
            tuple([*params, page_size, offset]),
        ).fetchall()

        sites = conn.execute("SELECT DISTINCT site FROM devices WHERE site IS NOT NULL AND site != '' ORDER BY site ASC").fetchall()
        assignees = conn.execute("SELECT DISTINCT assignee FROM alert_events WHERE assignee IS NOT NULL AND assignee != '' ORDER BY assignee ASC").fetchall()

        status_counts = {
            'open': conn.execute("SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NULL AND COALESCE(workflow_status, 'open') = 'open'").fetchone()['c'],
            'acknowledged': conn.execute("SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NULL AND workflow_status = 'acknowledged'").fetchone()['c'],
            'investigating': conn.execute("SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NULL AND workflow_status = 'investigating'").fetchone()['c'],
            'suppressed': conn.execute("SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NULL AND workflow_status = 'suppressed'").fetchone()['c'],
            'resolved': conn.execute("SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NOT NULL").fetchone()['c'],
        }
        status_counts['all_active'] = status_counts['open'] + status_counts['acknowledged'] + status_counts['investigating'] + status_counts['suppressed']
        status_counts['all'] = status_counts['all_active'] + status_counts['resolved']

        return {
            'items': [_row_to_alert(row) for row in rows],
            'total': int(total),
            'page': page,
            'page_size': page_size,
            'filters': {
                'sites': [row['site'] for row in sites],
                'assignees': [row['assignee'] for row in assignees],
            },
            'status_counts': status_counts,
        }
    finally:
        conn.close()


@router.get('/alerts/maintenance-windows')
def read_maintenance_windows(
    status: str = Query(default='all'),
    search: str = Query(default=''),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return alert_maintenance_service.list_windows_paginated(
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.post('/alerts/maintenance-windows/preview')
def preview_maintenance_window(payload: dict = Body(...)):
    try:
        return alert_maintenance_service.preview_matches(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post('/alerts/maintenance-windows')
def create_maintenance_window(payload: dict = Body(...)):
    try:
        window = alert_maintenance_service.create_window(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    notify_user_ids = [str(item) for item in (window.get('notify_user_ids') or []) if str(item).strip()]
    user_rows = []
    if notify_user_ids:
        conn = get_db_connection()
        try:
            placeholders = ','.join('?' for _ in notify_user_ids)
            user_rows = conn.execute(
                f'''SELECT id, username, notification_channels, preferred_language FROM users WHERE id IN ({placeholders})''',
                tuple(notify_user_ids),
            ).fetchall()
        finally:
            conn.close()
    alert_maintenance_service.notify_contacts(window, [dict(row) for row in user_rows])
    log_audit_event(
        event_type='ALERT_MAINTENANCE_CREATE',
        category='monitoring',
        severity='medium',
        status='success',
        summary=f"Created maintenance window {window['name']}",
        actor_username=window.get('created_by') or 'system',
        actor_role='Operator',
        target_type='alert_maintenance_window',
        target_id=window['id'],
        target_name=window['name'],
        details={
            'target_ip': window['target_ip'],
            'target_ips': window.get('target_ips') or [],
            'selection_mode': window.get('selection_mode') or 'resources',
            'match_conditions': window.get('match_conditions') or [],
            'starts_at': window['starts_at'],
            'ends_at': window['ends_at'],
            'title_pattern': window['title_pattern'],
            'message_pattern': window['message_pattern'],
            'last_match_count': window['last_match_count'],
        },
    )
    return window


@router.post('/alerts/maintenance-windows/{window_id}/cancel')
def cancel_maintenance_window(window_id: str, payload: dict = Body(default={})):
    actor_username = (payload.get('actor_username') or 'system').strip() or 'system'
    try:
        alert_maintenance_service.cancel_window(window_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    log_audit_event(
        event_type='ALERT_MAINTENANCE_CANCEL',
        category='monitoring',
        severity='medium',
        status='success',
        summary=f'Cancelled maintenance window {window_id}',
        actor_username=actor_username,
        actor_role='Operator',
        target_type='alert_maintenance_window',
        target_id=window_id,
        target_name=window_id,
    )
    return {'success': True}


@router.delete('/alerts/maintenance-windows/{window_id}')
def delete_maintenance_window(window_id: str, actor_username: str = Query(default='system')):
    actor = actor_username.strip() or 'system'
    try:
        alert_maintenance_service.delete_window(window_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    log_audit_event(
        event_type='ALERT_MAINTENANCE_DELETE',
        category='monitoring',
        severity='medium',
        status='success',
        summary=f'Deleted maintenance window {window_id}',
        actor_username=actor,
        actor_role='Operator',
        target_type='alert_maintenance_window',
        target_id=window_id,
        target_name=window_id,
    )
    return {'success': True}


@router.get('/alerts/rules')
def read_alert_rules(
    search: str = Query(default=''),
    enabled: str = Query(default='all'),
    metric_type: str = Query(default='all'),
    category: str = Query(default='all'),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user=require_role("Viewer"),
):
    return alert_rule_service.list_rules_paginated(
        search=search,
        enabled=enabled,
        metric_type=metric_type,
        category=category,
        page=page,
        page_size=page_size,
    )


@router.get('/alerts/rules/catalog')
def read_alert_rule_collection_catalog(user=require_role("Viewer")):
    """Describe each rule's collector and its SNMP-template/OID ownership."""
    return {
        'items': alert_rule_service.list_alert_metric_collections(),
    }


@router.post('/alerts/rules')
def create_alert_rule(payload: dict = Body(...), user=require_role("Operator")):
    actor_username = user.get("username", "unknown")
    _verify_alert_rule_approval(payload, approval_type='alert_rule')
    try:
        rule = alert_rule_service.create_rule(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log_audit_event(
        event_type='ALERT_RULE_CREATE',
        category='monitoring',
        severity='medium',
        status='success',
        summary=f"Created alert rule {rule['name']}",
        actor_username=actor_username,
        actor_role=user.get("role", "Operator"),
        target_type='alert_rule',
        target_id=rule['id'],
        target_name=rule['name'],
        details=rule,
    )
    return rule


@router.get('/alerts/rules/preview')
def read_alert_rules_preview(user=require_role("Viewer")):
    return alert_rule_service.get_rules_preview()


@router.get('/alerts/rules/history')
def read_alert_rules_history(limit: int = Query(default=20, ge=1, le=100), rule_id: str | None = Query(default=None), user=require_role("Viewer")):
    return {'items': alert_rule_service.list_rule_history(limit=limit, rule_id=rule_id)}


@router.put('/alerts/rules/{rule_id}')
def update_alert_rules(rule_id: str, payload: dict = Body(...), user=require_role("Operator")):
    actor_username = user.get("username", "unknown")
    _verify_alert_rule_approval(payload, approval_type='alert_rule')
    try:
        rule = alert_rule_service.update_rule(rule_id, payload)
    except ValueError as exc:
        status_code = 404 if 'not found' in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc))
    log_audit_event(
        event_type='ALERT_RULE_UPDATE',
        category='monitoring',
        severity='medium',
        status='success',
        summary=f"Updated alert rule {rule['name']}",
        actor_username=actor_username,
        actor_role=user.get("role", "Operator"),
        target_type='alert_rule',
        target_id=rule['id'],
        target_name=rule['name'],
        details=rule,
    )
    return rule


@router.delete('/alerts/rules/{rule_id}')
def delete_alert_rule(
    rule_id: str,
    approval_token: str | None = Query(default=None),
    approval_code: str | None = Query(default=None),
    skip_approval: bool = Query(default=False),
    user=require_role("Administrator"),
):
    actor_username = user.get("username", "unknown")
    payload = {
        "approval_token": approval_token,
        "approval_code": approval_code,
        "skip_approval_verification": skip_approval
    }
    _verify_alert_rule_approval(payload, approval_type='alert_rule_delete')
    try:
        existing = alert_rule_service.get_rule(rule_id)
        alert_rule_service.delete_rule(rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    log_audit_event(
        event_type='ALERT_RULE_DELETE',
        category='monitoring',
        severity='medium',
        status='success',
        summary=f"Deleted alert rule {existing['name'] if existing else rule_id}",
        actor_username=actor_username,
        actor_role=user.get("role", "Administrator"),
        target_type='alert_rule',
        target_id=rule_id,
        target_name=existing['name'] if existing else rule_id,
    )
    return {'success': True}


@router.post('/alerts/rules/batch-toggle')
def batch_toggle_alert_rules(payload: dict = Body(...), user=require_role("Operator")):
    rule_ids = payload.get('rule_ids') or []
    enabled = payload.get('enabled')
    actor_username = user.get("username", "unknown")
    if enabled is None:
        raise HTTPException(status_code=400, detail='enabled is required')
    if not rule_ids or not isinstance(rule_ids, list):
        raise HTTPException(status_code=400, detail='rule_ids is required')
    if len(rule_ids) > 200:
        raise HTTPException(status_code=400, detail='Too many rule IDs (max 200)')

    _verify_alert_rule_approval(payload, approval_type='alert_rule')

    conn = get_db_connection()
    try:
        now = _utc_now_iso()
        updated = 0
        for rid in rule_ids:
            rid = str(rid).strip()
            if not rid:
                continue
            row = conn.execute('SELECT id, name FROM alert_rules WHERE id = ?', (rid,)).fetchone()
            if not row:
                continue
            conn.execute(
                'UPDATE alert_rules SET enabled = ?, updated_by = ?, updated_at = ? WHERE id = ?',
                (1 if enabled else 0, actor_username, now, rid),
            )
            updated += 1
            log_audit_event(
                event_type='ALERT_RULE_UPDATE',
                category='monitoring',
                severity='medium',
                status='success',
                summary=f"{'Enabled' if enabled else 'Disabled'} alert rule {row['name']}",
                actor_username=actor_username,
                actor_role=user.get("role", "Operator"),
                target_type='alert_rule',
                target_id=rid,
                target_name=row['name'],
                details={'enabled': bool(enabled), 'batch': True},
                conn=conn,
            )
        conn.commit()
        return {'success': True, 'updated_count': updated}
    finally:
        conn.close()


@router.post('/alerts/rules/batch-delete')
def batch_delete_alert_rules(payload: dict = Body(...), user=require_role("Administrator")):
    rule_ids = payload.get('rule_ids') or []
    actor_username = user.get("username", "unknown")
    if not rule_ids or not isinstance(rule_ids, list):
        raise HTTPException(status_code=400, detail='rule_ids is required')
    if len(rule_ids) > 200:
        raise HTTPException(status_code=400, detail='Too many rule IDs (max 200)')

    _verify_alert_rule_approval(payload, approval_type='alert_rule_delete')

    conn = get_db_connection()
    try:
        deleted = 0
        for rid in rule_ids:
            rid = str(rid).strip()
            if not rid:
                continue
            row = conn.execute('SELECT id, name FROM alert_rules WHERE id = ?', (rid,)).fetchone()
            if not row:
                continue
            conn.execute('DELETE FROM alert_rules WHERE id = ?', (rid,))
            deleted += 1
            log_audit_event(
                event_type='ALERT_RULE_DELETE',
                category='monitoring',
                severity='medium',
                status='success',
                summary=f"Batch deleted alert rule {row['name']}",
                actor_username=actor_username,
                actor_role=user.get("role", "Administrator"),
                target_type='alert_rule',
                target_id=rid,
                target_name=row['name'],
                details={'batch': True},
                conn=conn,
            )
        conn.commit()
        return {'success': True, 'deleted_count': deleted}
    finally:
        conn.close()


@router.post('/alerts/batch-ack')
def batch_acknowledge_alerts(payload: dict = Body(...)):
    alert_ids = payload.get('alert_ids') or []
    actor_username = (payload.get('actor_username') or 'system').strip() or 'system'
    next_status = (payload.get('status') or 'acknowledged').strip().lower()
    if next_status not in {'acknowledged', 'investigating'}:
        raise HTTPException(status_code=400, detail='Unsupported status')
    if not alert_ids or not isinstance(alert_ids, list):
        raise HTTPException(status_code=400, detail='alert_ids is required')
    if len(alert_ids) > 200:
        raise HTTPException(status_code=400, detail='Too many alert IDs (max 200)')

    conn = get_db_connection()
    try:
        now = _utc_now_iso()
        updated = 0
        for aid in alert_ids:
            aid = str(aid).strip()
            if not aid:
                continue
            row = conn.execute('SELECT id, title, device_id, dedupe_key, resolved_at FROM alert_events WHERE id = ?', (aid,)).fetchone()
            if not row or row['resolved_at']:
                continue
            conn.execute(
                'UPDATE alert_events SET workflow_status = ?, ack_by = ?, ack_at = COALESCE(ack_at, ?), updated_at = ? WHERE id = ?',
                (next_status, actor_username, now, now, aid),
            )
            updated += 1
            log_audit_event(
                event_type='ALERT_ACK',
                category='monitoring',
                severity='medium',
                status='success',
                summary=f'Batch acknowledged alert {row["title"]}',
                actor_username=actor_username,
                actor_role='Operator',
                target_type='alert',
                target_id=aid,
                target_name=row['title'],
                device_id=row['device_id'],
                details={'workflow_status': next_status, 'dedupe_key': row['dedupe_key'], 'batch': True},
                conn=conn,
            )
        conn.commit()
        return {'success': True, 'updated_count': updated}
    finally:
        conn.close()


@router.post('/alerts/batch-assign')
def batch_assign_alerts(payload: dict = Body(...)):
    alert_ids = payload.get('alert_ids') or []
    assignee = (payload.get('assignee') or '').strip()
    actor_username = (payload.get('actor_username') or 'system').strip() or 'system'
    if not assignee:
        raise HTTPException(status_code=400, detail='assignee is required')
    if not alert_ids or not isinstance(alert_ids, list):
        raise HTTPException(status_code=400, detail='alert_ids is required')
    if len(alert_ids) > 200:
        raise HTTPException(status_code=400, detail='Too many alert IDs (max 200)')

    conn = get_db_connection()
    try:
        now = _utc_now_iso()
        updated = 0
        for aid in alert_ids:
            aid = str(aid).strip()
            if not aid:
                continue
            row = conn.execute('SELECT id, title, device_id, dedupe_key FROM alert_events WHERE id = ?', (aid,)).fetchone()
            if not row:
                continue
            conn.execute(
                'UPDATE alert_events SET assignee = ?, updated_at = ? WHERE id = ?',
                (assignee, now, aid),
            )
            updated += 1
            log_audit_event(
                event_type='ALERT_ASSIGN',
                category='monitoring',
                severity='medium',
                status='success',
                summary=f'Batch assigned alert {row["title"]} to {assignee}',
                actor_username=actor_username,
                actor_role='Operator',
                target_type='alert',
                target_id=aid,
                target_name=row['title'],
                device_id=row['device_id'],
                details={'assignee': assignee, 'dedupe_key': row['dedupe_key'], 'batch': True},
                conn=conn,
            )
        conn.commit()
        return {'success': True, 'updated_count': updated}
    finally:
        conn.close()


@router.get('/alerts/{alert_id}')
def get_alert_detail(alert_id: str):
    conn = get_db_connection()
    try:
        row = conn.execute(
            '''
            SELECT
                a.id, a.dedupe_key, a.source, a.severity, a.title, a.message,
                a.device_id, a.interface_name, a.created_at, a.resolved_at,
                a.workflow_status, a.assignee, a.ack_by, a.ack_at, a.note, a.updated_at,
                d.hostname, d.ip_address, d.site
            FROM alert_events a
            LEFT JOIN devices d ON d.id = a.device_id
            WHERE a.id = ?
            ''',
            (alert_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Alert not found')

        item = _row_to_alert(row)
        timeline_rows = conn.execute(
            '''
            SELECT id, severity, title, message, created_at, resolved_at, workflow_status, assignee, ack_by, ack_at, note, updated_at
            FROM alert_events
            WHERE dedupe_key = ?
            ORDER BY created_at DESC
            LIMIT 30
            ''',
            (item['dedupe_key'],),
        ).fetchall()
        return {
            'item': item,
            'timeline': [_row_to_alert(tl) for tl in timeline_rows],
        }
    finally:
        conn.close()


@router.post('/alerts/{alert_id}/ack')
def acknowledge_alert(alert_id: str, payload: dict = Body(default={})): 
    actor_username = (payload.get('actor_username') or 'system').strip() or 'system'
    next_status = (payload.get('status') or 'acknowledged').strip().lower()
    if next_status not in {'acknowledged', 'investigating'}:
        raise HTTPException(status_code=400, detail='Unsupported status')

    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM alert_events WHERE id = ?', (alert_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Alert not found')
        if row['resolved_at']:
            raise HTTPException(status_code=400, detail='Resolved alerts cannot be acknowledged')

        now = _utc_now_iso()
        conn.execute(
            'UPDATE alert_events SET workflow_status = ?, ack_by = ?, ack_at = COALESCE(ack_at, ?), updated_at = ? WHERE id = ?',
            (next_status, actor_username, now, now, alert_id),
        )
        conn.commit()
        log_audit_event(
            event_type='ALERT_ACK',
            category='monitoring',
            severity='medium',
            status='success',
            summary=f'Acknowledged alert {row["title"]}',
            actor_username=actor_username,
            actor_role='Operator',
            target_type='alert',
            target_id=alert_id,
            target_name=row['title'],
            device_id=row['device_id'],
            details={'workflow_status': next_status, 'dedupe_key': row['dedupe_key']},
        )
        return {'success': True}
    finally:
        conn.close()


@router.post('/alerts/{alert_id}/assign')
def assign_alert(alert_id: str, payload: dict = Body(default={})):
    assignee = (payload.get('assignee') or '').strip()
    actor_username = (payload.get('actor_username') or 'system').strip() or 'system'
    if not assignee:
        raise HTTPException(status_code=400, detail='assignee is required')

    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM alert_events WHERE id = ?', (alert_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Alert not found')

        now = _utc_now_iso()
        conn.execute(
            'UPDATE alert_events SET assignee = ?, updated_at = ? WHERE id = ?',
            (assignee, now, alert_id),
        )
        conn.commit()
        log_audit_event(
            event_type='ALERT_ASSIGN',
            category='monitoring',
            severity='medium',
            status='success',
            summary=f'Assigned alert {row["title"]} to {assignee}',
            actor_username=actor_username,
            actor_role='Operator',
            target_type='alert',
            target_id=alert_id,
            target_name=row['title'],
            device_id=row['device_id'],
            details={'assignee': assignee, 'dedupe_key': row['dedupe_key']},
        )
        return {'success': True}
    finally:
        conn.close()


@router.post('/alerts/{alert_id}/note')
def update_alert_note(alert_id: str, payload: dict = Body(default={})):
    note = str(payload.get('note') or '').strip()
    actor_username = (payload.get('actor_username') or 'system').strip() or 'system'

    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM alert_events WHERE id = ?', (alert_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Alert not found')

        now = _utc_now_iso()
        conn.execute(
            'UPDATE alert_events SET note = ?, updated_at = ? WHERE id = ?',
            (note, now, alert_id),
        )
        conn.commit()
        log_audit_event(
            event_type='ALERT_NOTE',
            category='monitoring',
            severity='low',
            status='success',
            summary=f'Updated note for alert {row["title"]}',
            actor_username=actor_username,
            actor_role='Operator',
            target_type='alert',
            target_id=alert_id,
            target_name=row['title'],
            device_id=row['device_id'],
            details={'note': note, 'dedupe_key': row['dedupe_key']},
        )
        return {'success': True}
    finally:
        conn.close()
