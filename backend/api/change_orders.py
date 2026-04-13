"""
change_orders.py — Change Order / Ticket Management API
CRUD endpoints for change order lifecycle management.
"""

import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel
from database import get_db_connection
from core.rbac import require_role
from services.audit_service import log_audit_event
from services.change_order_service import (
    create_change_order,
    update_change_order,
    get_change_order,
    list_change_orders,
    get_summary,
    delete_change_order,
    toggle_bookmark,
    get_user_bookmarks,
    save_order_as_template,
    list_templates,
    delete_template,
    get_template,
)

logger = logging.getLogger(__name__)
router = APIRouter()


ALLOWED_STATUSES = {
    # New workflow statuses
    'draft', 'initial_review', 'final_review', 'approved', 'implementing', 'completed',
    'rollback_in_progress', 'rolled_back', 'rejected', 'failed', 'cancelled',
    # Legacy statuses kept for compatibility
    'pending', 'executing',
}


ALLOWED_TRANSITIONS = {
    'draft': {'initial_review', 'cancelled'},
    'initial_review': {'final_review', 'rejected', 'cancelled'},
    'final_review': {'approved', 'rejected', 'cancelled'},
    'approved': {'implementing', 'cancelled'},
    'implementing': {'completed', 'failed', 'rollback_in_progress', 'cancelled'},
    'rollback_in_progress': {'rolled_back', 'failed'},
    'failed': {'rollback_in_progress', 'cancelled'},
    'rejected': {'draft', 'cancelled'},
    # Legacy status compatibility path
    'pending': {'approved', 'rejected', 'cancelled'},
    'executing': {'completed', 'failed', 'rollback_in_progress', 'cancelled'},
}


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _parse_change_groups(raw_value) -> set[str]:
    if isinstance(raw_value, str):
        try:
            raw_value = json.loads(raw_value or '[]')
        except Exception:
            raw_value = []
    if not isinstance(raw_value, (list, tuple, set)):
        return set()
    return {str(item or '').strip() for item in raw_value if str(item or '').strip()}


def _resolve_assignment_user(conn, user_id: str, stage: str) -> dict:
    row = conn.execute(
        'SELECT id, username, role, change_groups_json FROM users WHERE id = ?',
        (user_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail='Selected reviewer does not exist')

    user = dict(row)
    groups = _parse_change_groups(user.get('change_groups_json'))
    if stage == 'initial':
        if user.get('role') == 'Viewer':
            raise HTTPException(status_code=400, detail='Initial reviewer must be Operator or Administrator')
        if groups and 'initial_reviewer' not in groups:
            raise HTTPException(status_code=400, detail='Selected user is not in the initial review group')
    if stage == 'final':
        if user.get('role') != 'Administrator':
            raise HTTPException(status_code=400, detail='Final approver must be an Administrator')
        if groups and 'final_approver' not in groups:
            raise HTTPException(status_code=400, detail='Selected user is not in the final approval group')
    return {'id': str(user.get('id') or ''), 'username': str(user.get('username') or '')}


def _normalize_assignment_payload(conn, payload: dict) -> dict:
    normalized = dict(payload)
    assignment_fields = (
        ('assigned_initial_reviewer_id', 'assigned_initial_reviewer_username', 'initial'),
        ('assigned_final_approver_id', 'assigned_final_approver_username', 'final'),
    )
    for id_field, name_field, stage in assignment_fields:
        if id_field not in normalized and name_field not in normalized:
            continue

        assignee_id = str(normalized.get(id_field) or '').strip()
        if not assignee_id:
            normalized[id_field] = ''
            normalized[name_field] = ''
            continue

        assignee = _resolve_assignment_user(conn, assignee_id, stage)
        normalized[id_field] = assignee['id']
        normalized[name_field] = assignee['username']
    return normalized


def _load_actor_change_groups(conn, user_id: str) -> set[str]:
    if not user_id:
        return set()
    row = conn.execute('SELECT change_groups_json FROM users WHERE id = ?', (user_id,)).fetchone()
    if not row:
        return set()
    return _parse_change_groups(row['change_groups_json'])


def _build_command_template_snapshot(template_payload: dict) -> dict:
    if not isinstance(template_payload, dict):
        raise HTTPException(status_code=400, detail='command_template must be an object')

    scenario_id = str(template_payload.get('scenario_id') or '').strip()
    if not scenario_id:
        raise HTTPException(status_code=400, detail='command_template.scenario_id is required')

    from api.playbooks import _all_scenarios, _render_phase_commands

    scenario = next((item for item in _all_scenarios() if item.get('id') == scenario_id), None)
    if not scenario:
        raise HTTPException(status_code=400, detail='Selected scenario does not exist')

    supported_platforms = scenario.get('supported_platforms') or []
    default_platform = str(scenario.get('default_platform') or (supported_platforms[0] if supported_platforms else '')).strip()
    platform = str(template_payload.get('platform') or default_platform).strip()
    phases = (scenario.get('platform_phases') or {}).get(platform)
    if not phases:
        raise HTTPException(status_code=400, detail=f"Platform '{platform}' is not supported by the selected scenario")

    raw_variables = template_payload.get('variables') or {}
    if not isinstance(raw_variables, dict):
        raise HTTPException(status_code=400, detail='command_template.variables must be an object')
    variables = {str(key): '' if value is None else str(value) for key, value in raw_variables.items()}

    variable_defs = scenario.get('variables') or []
    missing_labels = []
    for variable in variable_defs:
        key = str(variable.get('key') or '').strip()
        if not key:
            continue
        value = str(variables.get(key, '')).strip()
        if variable.get('required') and not value:
            missing_labels.append(str(variable.get('label') or key))
        options = variable.get('options') or []
        if value and options and str(variable.get('type') or '') == 'select' and value not in [str(item) for item in options]:
            raise HTTPException(status_code=400, detail=f"Invalid option for variable '{key}'")

    if missing_labels:
        raise HTTPException(status_code=400, detail=f"Missing required scenario variables: {', '.join(missing_labels)}")

    preview = {
        'pre_check': _render_phase_commands(phases.get('pre_check', []), variables),
        'execute': _render_phase_commands(phases.get('execute', []), variables),
        'post_check': _render_phase_commands(phases.get('post_check', []), variables),
        'rollback': _render_phase_commands(phases.get('rollback', []), variables),
    }
    if not preview['execute']:
        raise HTTPException(status_code=400, detail='Selected scenario rendered no executable commands')

    return {
        'mode': 'template',
        'scenario_id': scenario_id,
        'scenario_name': str(scenario.get('name') or ''),
        'scenario_name_zh': str(scenario.get('name_zh') or scenario.get('name') or ''),
        'platform': platform,
        'variables': variables,
        'preview': preview,
        'generated_at': _utc_now_iso(),
    }


def _normalize_command_template_payload(payload: dict) -> dict:
    normalized = dict(payload)
    if 'command_template' not in normalized:
        return normalized

    template_payload = normalized.get('command_template') or {}
    if not template_payload:
        normalized['command_template'] = {}
        return normalized

    snapshot = _build_command_template_snapshot(template_payload)
    normalized['command_template'] = snapshot
    normalized['commands'] = snapshot['preview']['execute']
    normalized['rollback_plan'] = '\n'.join(snapshot['preview']['rollback']) if snapshot['preview']['rollback'] else str(normalized.get('rollback_plan') or '')
    return normalized


# ── Pydantic Models ──────────────────────────────────────────────────

class ChangeOrderCreate(BaseModel):
    title: str
    description: str = ''
    order_type: str = 'config_change'
    priority: str = 'medium'
    assigned_initial_reviewer_id: str = ''
    assigned_initial_reviewer_username: str = ''
    assigned_final_approver_id: str = ''
    assigned_final_approver_username: str = ''
    command_template: dict = {}
    target_devices: list = []
    commands: list = []
    rollback_plan: str = ''
    risk_level: str = 'low'
    scheduled_start: str = ''
    scheduled_end: str = ''


class ChangeOrderUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    order_type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    approver_id: Optional[str] = None
    approver_username: Optional[str] = None
    assigned_initial_reviewer_id: Optional[str] = None
    assigned_initial_reviewer_username: Optional[str] = None
    assigned_final_approver_id: Optional[str] = None
    assigned_final_approver_username: Optional[str] = None
    command_template: Optional[dict] = None
    target_devices: Optional[list] = None
    commands: Optional[list] = None
    rollback_plan: Optional[str] = None
    risk_level: Optional[str] = None
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    actual_start: Optional[str] = None
    actual_end: Optional[str] = None
    result_summary: Optional[str] = None
    result_detail: Optional[dict] = None
    rejected_reason: Optional[str] = None


# ── Summary ──────────────────────────────────────────────────────────

@router.get('/change-orders/summary')
def api_change_order_summary(user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {'success': True, 'data': get_summary(conn)}
    finally:
        conn.close()


# ── List / Search ────────────────────────────────────────────────────

@router.get('/change-orders')
def api_list_change_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query('', description='Filter by status'),
    priority: str = Query('', description='Filter by priority'),
    search: str = Query('', description='Search in order number / title'),
    requester: str = Query('', description='Filter by requester username'),
    assignee: str = Query('', description='Filter by assignee (reviewer/approver)'),
    bookmarked: str = Query('', description='Filter bookmarked by user_id'),
    my_todo: str = Query('', description='Filter personal todo by username'),
    group_todo: str = Query('', description='Filter group todo by comma-separated change_groups'),
    my_participated: str = Query('', description='Filter orders where user is involved'),
    my_drafts: str = Query('', description='Filter draft orders by requester username'),
    order_type: str = Query('', description='Filter by order type'),
    created_from: str = Query('', description='Filter created_at >= ISO datetime'),
    created_to: str = Query('', description='Filter created_at <= ISO datetime'),
    completed_from: str = Query('', description='Filter actual_end >= ISO datetime'),
    completed_to: str = Query('', description='Filter actual_end <= ISO datetime'),
    scheduled_from: str = Query('', description='Filter scheduled_start >= ISO datetime'),
    scheduled_to: str = Query('', description='Filter scheduled_end <= ISO datetime'),
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        orders, total = list_change_orders(
            conn, page=page, page_size=page_size,
            status=status, priority=priority,
            search=search, requester=requester,
            assignee=assignee, bookmarked_by=bookmarked,
            my_todo=my_todo, group_todo=group_todo,
            my_participated=my_participated, my_drafts=my_drafts,
            order_type=order_type,
            created_from=created_from, created_to=created_to,
            completed_from=completed_from, completed_to=completed_to,
            scheduled_from=scheduled_from, scheduled_to=scheduled_to,
        )
        return {'success': True, 'data': orders, 'total': total, 'page': page, 'page_size': page_size}
    finally:
        conn.close()


# ── Validate ticket for automation execution ─────────────────────────

@router.get('/change-orders/validate-ticket/{order_number}')
def api_validate_change_ticket(order_number: str, user=require_role("Viewer")):
    """Validate a change order number for automation execution time window check."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, order_number, title, status, scheduled_start, scheduled_end FROM change_orders WHERE order_number = ?",
            (order_number.strip(),),
        ).fetchone()
        if not row:
            return {
                'success': True,
                'data': {
                    'found': False,
                    'valid': False,
                    'reason': 'not_found',
                    'message': '未找到该变更工单',
                },
            }
        order = dict(row)
        status = order.get('status', '')
        scheduled_start = order.get('scheduled_start', '')
        scheduled_end = order.get('scheduled_end', '')

        # Check status: only approved/implementing orders allow execution
        executable_statuses = {'approved', 'implementing'}
        if status not in executable_statuses:
            return {
                'success': True,
                'data': {
                    'found': True,
                    'valid': False,
                    'reason': 'invalid_status',
                    'status': status,
                    'title': order.get('title', ''),
                    'order_number': order.get('order_number', ''),
                    'message': f'工单状态为 {status}，仅已审批/执行中的工单允许操作',
                },
            }

        # Check time window
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        time_ok = True
        reason = 'ok'
        message = ''

        if scheduled_start:
            try:
                start_dt = datetime.fromisoformat(scheduled_start.replace('Z', '+00:00'))
                if now < start_dt:
                    time_ok = False
                    reason = 'not_started'
                    message = f'变更窗口尚未开始（计划开始：{scheduled_start}）'
            except (ValueError, TypeError):
                pass

        if time_ok and scheduled_end:
            try:
                end_dt = datetime.fromisoformat(scheduled_end.replace('Z', '+00:00'))
                if now > end_dt:
                    time_ok = False
                    reason = 'expired'
                    message = f'变更窗口已超时（计划结束：{scheduled_end}）'
            except (ValueError, TypeError):
                pass

        return {
            'success': True,
            'data': {
                'found': True,
                'valid': time_ok,
                'reason': reason,
                'status': status,
                'title': order.get('title', ''),
                'order_number': order.get('order_number', ''),
                'scheduled_start': scheduled_start,
                'scheduled_end': scheduled_end,
                'message': message or '工单有效，可以执行',
            },
        }
    finally:
        conn.close()


@router.get('/change-orders/{order_id}')
def api_get_change_order(order_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        order = get_change_order(conn, order_id)
        if not order:
            raise HTTPException(status_code=404, detail='Change order not found')
        return {'success': True, 'data': order}
    finally:
        conn.close()

@router.get('/change-orders/{order_id}/timeline')
def api_get_change_order_timeline(order_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        order = get_change_order(conn, order_id)
        if not order:
            raise HTTPException(status_code=404, detail='Change order not found')
        rows = conn.execute(
            '''
            SELECT id, event_type, summary, actor_username, created_at, details_json
            FROM audit_events
            WHERE category = 'change_order' AND target_id = ?
            ORDER BY created_at ASC, id ASC
            ''',
            (order_id,),
        ).fetchall()
        timeline = []
        for row in rows:
            item = dict(row)
            timeline.append({
                'id': item.get('id', ''),
                'event_type': item.get('event_type', ''),
                'summary': item.get('summary', ''),
                'actor_username': item.get('actor_username', ''),
                'created_at': item.get('created_at', ''),
            })
        return {'success': True, 'data': timeline}
    finally:
        conn.close()


# ── Create ───────────────────────────────────────────────────────────

@router.post('/change-orders')
def api_create_change_order(body: ChangeOrderCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        payload = _normalize_assignment_payload(conn, body.model_dump())
        payload = _normalize_command_template_payload(payload)
        if payload.get('assigned_initial_reviewer_id') == user.get('user_id'):
            raise HTTPException(status_code=400, detail='Requester cannot be the assigned initial reviewer')
        if payload.get('assigned_final_approver_id') == user.get('user_id'):
            raise HTTPException(status_code=400, detail='Requester cannot be the assigned final approver')
        order = create_change_order(
            conn,
            title=payload['title'],
            description=payload['description'],
            order_type=payload['order_type'],
            priority=payload['priority'],
            requester_id=user.get('user_id', ''),
            requester_username=user.get('username', ''),
            assigned_initial_reviewer_id=payload.get('assigned_initial_reviewer_id', ''),
            assigned_initial_reviewer_username=payload.get('assigned_initial_reviewer_username', ''),
            assigned_final_approver_id=payload.get('assigned_final_approver_id', ''),
            assigned_final_approver_username=payload.get('assigned_final_approver_username', ''),
            command_template=payload.get('command_template') or {},
            target_devices=payload['target_devices'],
            commands=payload['commands'],
            rollback_plan=payload['rollback_plan'],
            risk_level=payload['risk_level'],
            scheduled_start=payload['scheduled_start'],
            scheduled_end=payload['scheduled_end'],
        )
        log_audit_event(
            event_type='change_order.created',
            category='change_order',
            severity='medium',
            status='open',
            summary=f"变更工单 {order['order_number']} 已创建: {payload['title']}",
            actor_id=user.get('user_id'),
            actor_username=user.get('username'),
            actor_role=user.get('role'),
            target_type='change_order',
            target_id=order['id'],
            target_name=order['order_number'],
            details={
                'assigned_initial_reviewer_id': payload.get('assigned_initial_reviewer_id', ''),
                'assigned_final_approver_id': payload.get('assigned_final_approver_id', ''),
            },
            conn=conn,
        )
        conn.commit()
        return {'success': True, 'data': order, 'message': f"工单 {order['order_number']} 创建成功"}
    finally:
        conn.close()


# ── Update ───────────────────────────────────────────────────────────

@router.put('/change-orders/{order_id}')
def api_update_change_order(order_id: str, body: ChangeOrderUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        updates = _normalize_assignment_payload(conn, body.model_dump(exclude_none=True))
        updates = _normalize_command_template_payload(updates)
        if not updates:
            raise HTTPException(status_code=400, detail='No fields to update')
        order = update_change_order(conn, order_id, updates)
        if not order:
            raise HTTPException(status_code=404, detail='Change order not found')
        log_audit_event(
            event_type='change_order.updated',
            category='change_order',
            severity='low',
            status='open',
            summary=f"变更工单 {order['order_number']} 已更新",
            actor_id=user.get('user_id'),
            actor_username=user.get('username'),
            actor_role=user.get('role'),
            target_type='change_order',
            target_id=order['id'],
            target_name=order['order_number'],
            details=updates,
            conn=conn,
        )
        conn.commit()
        return {'success': True, 'data': order}
    finally:
        conn.close()


# ── Status Transition ────────────────────────────────────────────────

@router.post('/change-orders/{order_id}/transition')
def api_transition_change_order(order_id: str, body: dict = Body(...), user=require_role("Operator")):
    new_status = body.get('status', '')
    if new_status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f'Invalid status: {new_status}')

    conn = get_db_connection()
    try:
        existing = get_change_order(conn, order_id)
        if not existing:
            raise HTTPException(status_code=404, detail='Change order not found')

        current_status = existing.get('status', 'draft')
        allowed_next = ALLOWED_TRANSITIONS.get(current_status, set())
        if new_status not in allowed_next:
            raise HTTPException(
                status_code=400,
                detail=f'Invalid transition: {current_status} -> {new_status}',
            )

        requester_username = existing.get('requester_username', '')
        actor_username = user.get('username', '')
        actor_groups = _load_actor_change_groups(conn, str(user.get('user_id') or ''))
        # Applicant cannot review/approve own ticket.
        if new_status in {'final_review', 'approved', 'rejected'} and requester_username and requester_username == actor_username:
            raise HTTPException(status_code=403, detail='Requester cannot review/approve own change order')
        # Final approval requires administrator role.
        if new_status == 'approved' and user.get('role') != 'Administrator':
            raise HTTPException(status_code=403, detail='Only Administrator can finalize approval for change orders')
        # Final-stage reject also requires administrator role.
        if current_status == 'final_review' and new_status == 'rejected' and user.get('role') != 'Administrator':
            raise HTTPException(status_code=403, detail='Only Administrator can reject in final review stage')
        if current_status == 'initial_review' and new_status in {'final_review', 'rejected'}:
            assigned_initial_reviewer_id = str(existing.get('assigned_initial_reviewer_id') or '')
            if assigned_initial_reviewer_id and assigned_initial_reviewer_id != str(user.get('user_id') or ''):
                raise HTTPException(status_code=403, detail='Only the assigned initial reviewer can process this change order')
            if not assigned_initial_reviewer_id and actor_groups and 'initial_reviewer' not in actor_groups and user.get('role') != 'Administrator':
                raise HTTPException(status_code=403, detail='Only users in the initial review group can process this change order')
        if current_status == 'final_review' and new_status in {'approved', 'rejected'}:
            assigned_final_approver_id = str(existing.get('assigned_final_approver_id') or '')
            if assigned_final_approver_id and assigned_final_approver_id != str(user.get('user_id') or ''):
                raise HTTPException(status_code=403, detail='Only the assigned final approver can process this change order')
            if not assigned_final_approver_id and actor_groups and 'final_approver' not in actor_groups and user.get('role') != 'Administrator':
                raise HTTPException(status_code=403, detail='Only users in the final approval group can process this change order')

        updates = {'status': new_status}
        if new_status == 'rejected':
            updates['rejected_reason'] = body.get('rejected_reason', '')
            updates['result_detail'] = {
                **(existing.get('result_detail') or {}),
                'rejected_by': user.get('username', ''),
                'rejected_at': _utc_now_iso(),
                'rejected_stage': current_status,
            }
        if new_status == 'final_review':
            updates['initial_reviewer_id'] = user.get('user_id', '')
            updates['initial_reviewer_username'] = user.get('username', '')
            updates['result_detail'] = {
                **(existing.get('result_detail') or {}),
                'initial_review_at': _utc_now_iso(),
            }
        if new_status == 'approved':
            updates['approver_id'] = user.get('user_id', '')
            updates['approver_username'] = user.get('username', '')
            updates['final_approver_id'] = user.get('user_id', '')
            updates['final_approver_username'] = user.get('username', '')
            updates['result_detail'] = {
                **(existing.get('result_detail') or {}),
                'approved_at': _utc_now_iso(),
            }
        if new_status == 'implementing' and not existing.get('actual_start'):
            updates['actual_start'] = _utc_now_iso()
        if new_status in {'completed', 'rolled_back'}:
            updates['result_summary'] = body.get('result_summary', '')
            updates['actual_end'] = _utc_now_iso()
        if new_status == 'failed':
            updates['result_summary'] = body.get('result_summary', '')
        if new_status == 'rollback_in_progress':
            updates['result_detail'] = {
                **(existing.get('result_detail') or {}),
                'rollback_reason': body.get('rollback_reason', ''),
                'rollback_started_at': _utc_now_iso(),
            }
        if new_status == 'rolled_back':
            updates['result_detail'] = {
                **(existing.get('result_detail') or {}),
                'rollback_completed_at': _utc_now_iso(),
            }

        order = update_change_order(conn, order_id, updates)
        severity = 'high' if new_status in ('rejected', 'failed') else 'medium'
        log_audit_event(
            event_type=f'change_order.{new_status}',
            category='change_order',
            severity=severity,
            status='open',
            summary=f"变更工单 {existing['order_number']} 状态变更为 {new_status}",
            actor_id=user.get('user_id'),
            actor_username=user.get('username'),
            actor_role=user.get('role'),
            target_type='change_order',
            target_id=order_id,
            target_name=existing['order_number'],
            details={'from_status': existing['status'], 'to_status': new_status, 'extra': body},
            conn=conn,
        )
        conn.commit()
        return {'success': True, 'data': order, 'message': f"工单状态已更新为 {new_status}"}
    finally:
        conn.close()


# ── Delete ───────────────────────────────────────────────────────────

@router.delete('/change-orders/{order_id}')
def api_delete_change_order(order_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        existing = get_change_order(conn, order_id)
        if not existing:
            raise HTTPException(status_code=404, detail='Change order not found')
        delete_change_order(conn, order_id)
        log_audit_event(
            event_type='change_order.deleted',
            category='change_order',
            severity='high',
            status='open',
            summary=f"变更工单 {existing['order_number']} 已删除",
            actor_id=user.get('user_id'),
            actor_username=user.get('username'),
            actor_role=user.get('role'),
            target_type='change_order',
            target_id=order_id,
            target_name=existing['order_number'],
            conn=conn,
        )
        conn.commit()
        return {'success': True, 'message': f"工单 {existing['order_number']} 已删除"}
    finally:
        conn.close()


# ── Bookmarks ────────────────────────────────────────────────────────

@router.post('/change-orders/{order_id}/bookmark')
def api_toggle_bookmark(order_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        if not get_change_order(conn, order_id):
            raise HTTPException(status_code=404, detail='Change order not found')
        bookmarked = toggle_bookmark(conn, user.get('user_id', ''), order_id)
        return {'success': True, 'data': {'bookmarked': bookmarked}}
    finally:
        conn.close()


@router.get('/change-orders-bookmarks')
def api_get_my_bookmarks(user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        order_ids = get_user_bookmarks(conn, user.get('user_id', ''))
        return {'success': True, 'data': order_ids}
    finally:
        conn.close()


# ── Templates ────────────────────────────────────────────────────────

@router.post('/change-order-templates')
def api_save_as_template(body: dict = Body(...), user=require_role("Operator")):
    conn = get_db_connection()
    try:
        order_id = body.get('order_id', '')
        name = body.get('name', '').strip()
        description = body.get('description', '').strip()
        if not order_id or not name:
            raise HTTPException(status_code=400, detail='order_id and name are required')
        order = get_change_order(conn, order_id)
        if not order:
            raise HTTPException(status_code=404, detail='Change order not found')
        tpl = save_order_as_template(
            conn, name=name, description=description, order=order,
            creator_id=user.get('user_id', ''),
            creator_username=user.get('username', ''),
        )
        return {'success': True, 'data': tpl, 'message': '模板保存成功'}
    finally:
        conn.close()


@router.get('/change-order-templates')
def api_list_templates(mine: str = Query('', description='If "1", only my templates'), user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        creator_id = user.get('user_id', '') if mine == '1' else ''
        return {'success': True, 'data': list_templates(conn, creator_id)}
    finally:
        conn.close()


@router.get('/change-order-templates/{template_id}')
def api_get_template(template_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        tpl = get_template(conn, template_id)
        if not tpl:
            raise HTTPException(status_code=404, detail='Template not found')
        return {'success': True, 'data': tpl}
    finally:
        conn.close()


@router.delete('/change-order-templates/{template_id}')
def api_delete_template(template_id: str, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        if not delete_template(conn, template_id):
            raise HTTPException(status_code=404, detail='Template not found')
        return {'success': True, 'message': '模板已删除'}
    finally:
        conn.close()
