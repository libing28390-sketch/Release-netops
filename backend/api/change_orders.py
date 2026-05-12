"""
change_orders.py — Change Order / Ticket Management API
CRUD endpoints for change order lifecycle management.
"""

import os
import shutil
import uuid
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Body, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from database import get_db_connection, PROJECT_ROOT
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

# ── Feature Flags (Stage 2 / Stage 3 enforcement gates) ─────────────
# Set FEATURE_TEMPLATE_REQUIRED=1 in the environment to enable template
# enforcement (cluster 1.1 fix, task 14.1).  Defaults to OFF so that
# Stage-1 fixes (clusters 1.3 / 1.4) can be shipped independently.
FEATURE_TEMPLATE_REQUIRED: bool = os.environ.get('FEATURE_TEMPLATE_REQUIRED', '0').strip() == '1'

# Set FEATURE_CONTROL_SHEET=1 to enable control-sheet completeness
# enforcement (cluster 1.2 fix, task 15.3).  Defaults to OFF.
FEATURE_CONTROL_SHEET: bool = os.environ.get('FEATURE_CONTROL_SHEET', '0').strip() == '1'


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
    'final_review': {'approved', 'rejected', 'cancelled', 'initial_review'},
    'approved': {'implementing', 'cancelled'},
    'implementing': {'completed', 'failed', 'rollback_in_progress', 'cancelled'},
    'rollback_in_progress': {'rolled_back', 'failed'},
    'failed': {'rollback_in_progress', 'cancelled'},
    'rejected': {'draft', 'cancelled'},
    # Terminal states
    'completed': set(),
    'rolled_back': set(),
    'cancelled': set(),
    # Legacy status compatibility path
    'pending': {'approved', 'rejected', 'cancelled'},
    'executing': {'completed', 'failed', 'rollback_in_progress', 'cancelled'},
}

# Sanity-check: every status in ALLOWED_STATUSES must have an explicit entry in
# ALLOWED_TRANSITIONS so that terminal states are never silently swallowed by the
# .get(current_status, set()) fallback.  This assertion fires at import time
# (and therefore at test-collection time) to catch any future drift.
assert ALLOWED_STATUSES <= ALLOWED_TRANSITIONS.keys(), (
    "ALLOWED_TRANSITIONS is missing keys for: "
    + str(ALLOWED_STATUSES - ALLOWED_TRANSITIONS.keys())
)


def _validate_assignment_rules(requester_username: str, payload: dict):
    """
    Validate assignment constraints (Property 3 & 4):
    - Requester cannot be assigned as initial reviewer or final approver.
    - Initial reviewer and Final approver cannot be the same person.
    """
    rev_id = str(payload.get('assigned_initial_reviewer_id') or '').strip()
    rev_name = str(payload.get('assigned_initial_reviewer_username') or '').strip()
    app_id = str(payload.get('assigned_final_approver_id') or '').strip()
    app_name = str(payload.get('assigned_final_approver_username') or '').strip()

    if rev_name and rev_name == requester_username:
        raise HTTPException(status_code=400, detail='申请人不能作为指定的初审人')
    if app_name and app_name == requester_username:
        raise HTTPException(status_code=400, detail='申请人不能作为指定的终审人')
    if rev_id and rev_id == app_id:
        raise HTTPException(status_code=400, detail='初审人与终审人不能为同一人')


_TEMPLATE_REQUIRED_STATUSES = frozenset({
    'initial_review', 'final_review', 'approved', 'implementing', 'completed',
})


def _validate_template_completeness(payload: dict):
    """
    Property 1: Template Enforcement (Task 14.1)

    When ``payload['status']`` is one of the five non-draft workflow statuses
    that require a rendered command template
    (``{'initial_review','final_review','approved','implementing','completed'}``),
    the ``command_template`` field MUST satisfy all of:
      - present and non-empty
      - ``mode == 'template'``
      - non-empty ``scenario_id``
      - non-empty ``preview.execute`` list

    Any violation raises ``HTTPException(400, '提交初审前必须选择场景化命令模板并渲染出可执行命令')``.

    This function is a no-op for ``status == 'draft'`` and for terminal /
    error statuses (``rejected``, ``failed``, ``cancelled``, etc.) that are
    not in ``_TEMPLATE_REQUIRED_STATUSES``.

    Gated by ``FEATURE_TEMPLATE_REQUIRED`` at the call sites in
    ``api_create_change_order``, ``api_update_change_order``, and
    ``api_transition_change_order``.
    """
    status = payload.get('status')
    if status not in _TEMPLATE_REQUIRED_STATUSES:
        return

    tpl = payload.get('command_template') or {}
    if not tpl or tpl.get('mode') != 'template' or not str(tpl.get('scenario_id') or '').strip():
        raise HTTPException(
            status_code=400,
            detail='提交初审前必须选择场景化命令模板并渲染出可执行命令',
        )

    preview = tpl.get('preview') or {}
    if not preview.get('execute'):
        raise HTTPException(
            status_code=400,
            detail='提交初审前必须渲染出可执行命令',
        )


def _validate_control_sheet_completeness(conn, order_id: str, payload: dict, new_status: str):
    """
    Property 2: Control Sheet Enforcement (Task 15.3)

    The 9 required structured fields (per design.md §Data Model Changes →
    control_sheet_json):
      change_time   — dict with 'start' and 'end' ISO timestamps
      implementer   — dict with 'id' and 'username'
      co_reviewer   — dict with 'id' and 'username'
      device_ips    — non-empty list of IP strings
      pre_check     — non-empty string
      execution     — non-empty string
      post_verify   — non-empty string
      business_verify — non-empty string
      rollback_plan — non-empty string
    """
    if new_status == 'initial_review':
        cs = payload.get('control_sheet') or {}
        # Required fields per design.md §Data Model Changes → control_sheet_json
        required_fields = [
            'change_time', 'implementer', 'co_reviewer', 'device_ips',
            'pre_check', 'execution', 'post_verify', 'business_verify',
            'rollback_plan',
        ]
        missing = []
        for f in required_fields:
            val = cs.get(f)
            if val is None:
                missing.append(f)
            elif isinstance(val, (list,)) and not val:
                missing.append(f)
            elif isinstance(val, dict) and not val:
                missing.append(f)
            elif isinstance(val, str) and not val.strip():
                missing.append(f)
        if missing:
            raise HTTPException(status_code=400, detail=f'提交初审前必须填写完整的变更控制表，缺失字段: {", ".join(missing)}')

    if new_status == 'implementing':
        # Additionally require >= 1 row in change_order_control_sheet_attachments
        count = conn.execute(
            "SELECT COUNT(*) FROM change_order_control_sheet_attachments WHERE order_id = ?",
            (order_id,)
        ).fetchone()[0]
        if count == 0:
            raise HTTPException(status_code=400, detail='进入实施阶段前必须上传至少一个附件（变更控制表扫描件/截图）')


STATUS_ZH = {
    'draft': '草稿',
    'initial_review': '初审中',
    'final_review': '终审中',
    'approved': '审批完成',
    'implementing': '实施中',
    'completed': '完成',
    'rollback_in_progress': '回溯中',
    'rolled_back': '已回溯',
    'rejected': '已驳回',
    'failed': '执行失败',
    'cancelled': '已取消',
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
        if 'initial_reviewer' not in groups:
            raise HTTPException(status_code=400, detail='Selected user is not in the initial review group')
    if stage == 'final':
        if user.get('role') != 'Administrator':
            raise HTTPException(status_code=400, detail='Final approver must be an Administrator')
        if 'final_approver' not in groups:
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
    source_kind = str(template_payload.get('source_kind') or 'scenario').strip().lower()

    from api.playbooks import _all_scenarios, _render_phase_commands

    def _default_checks_for_platform(platform_key: str) -> tuple[list[str], list[str]]:
        pre_post_map: dict[str, tuple[list[str], list[str]]] = {
            'cisco_ios': (
                ['show version', 'show running-config | include interface'],
                ['show running-config | include interface', 'show interfaces status'],
            ),
            'cisco_nxos': (
                ['show version', 'show running-config | include interface'],
                ['show running-config | include interface', 'show interface status'],
            ),
            'cisco_iosxr': (
                ['show version', 'show running-config | include interface'],
                ['show running-config | include interface', 'show interfaces'],
            ),
            'huawei_vrp': (
                ['display version', 'display current-configuration | include interface'],
                ['display current-configuration | include interface', 'display interface'],
            ),
            'h3c_comware': (
                ['display version', 'display current-configuration | include interface'],
                ['display current-configuration | include interface', 'display interface'],
            ),
            'arista_eos': (
                ['show version', 'show running-config | include interface'],
                ['show running-config | include interface', 'show interfaces status'],
            ),
            'juniper_junos': (
                ['show version', 'show configuration | display set | grep interface'],
                ['show configuration | display set | grep interface', 'show interfaces'],
            ),
        }
        return pre_post_map.get(platform_key, ([], []))

    scenario = None
    if source_kind == 'config_template':
        conn = get_db_connection()
        try:
            row = conn.execute(
                'SELECT id, name, vendor, content FROM templates WHERE id = ?',
                (scenario_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=400, detail='Selected configuration template does not exist')
        template = dict(row)
        platform = str(template_payload.get('platform') or '').strip()
        if not platform:
            raise HTTPException(status_code=400, detail='command_template.platform is required for config template mode')
        pre_check, post_check = _default_checks_for_platform(platform)
        scenario = {
            'id': template['id'],
            'name': template.get('name') or '',
            'name_zh': template.get('name') or '',
            'variables': [],
            'platform_phases': {
                platform: {
                    'pre_check': pre_check,
                    'execute': [str(template.get('content') or '')] if str(template.get('content') or '').strip() else [],
                    'post_check': post_check,
                    'rollback': [],
                }
            },
            'default_platform': platform,
            'supported_platforms': [platform],
        }
    else:
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
        'source_kind': source_kind,
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
    status = normalized.get('status', 'draft')
    order_type = normalized.get('order_type', 'config_change')

    if not template_payload:
        # When FEATURE_TEMPLATE_REQUIRED is ON, reject empty templates for
        # non-draft config-change orders at normalization time (before the
        # dedicated _validate_template_completeness call).  When the flag is
        # OFF we silently accept the empty dict for backward compatibility.
        if FEATURE_TEMPLATE_REQUIRED and status in _TEMPLATE_REQUIRED_STATUSES and order_type == 'config_change':
            raise HTTPException(status_code=400, detail='非草稿状态的配置变更工单必须携带有效的场景化模板')
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
    status: str = 'draft'
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
    authorization_exempt: bool = False
    control_sheet: dict = {}


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
    authorization_exempt: Optional[bool] = None
    control_sheet: Optional[dict] = None
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
        return {'success': True, 'data': get_summary(conn, user_id=str(user.get('user_id') or ''), username=user.get('username', ''))}
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
    my_todo_kind: str = Query('', description='Filter my_todo by kind (review/implement/modify)'),
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
            exclude_requester=user.get('username', ''),
            my_participated=my_participated, my_drafts=my_drafts,
            order_type=order_type,
            created_from=created_from, created_to=created_to,
            completed_from=completed_from, completed_to=completed_to,
            scheduled_from=scheduled_from, scheduled_to=scheduled_to,
            my_todo_kind=my_todo_kind,
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
        
        # Wire Property 3 & 4 (Task 12.1)
        _validate_assignment_rules(user.get('username'), payload)
        
        # Property 1: Template Enforcement (Task 14.1)
        if FEATURE_TEMPLATE_REQUIRED:
            _validate_template_completeness(payload)

        if payload.get('status') != 'draft' and not payload.get('assigned_initial_reviewer_id'):
            raise HTTPException(status_code=400, detail='提交初审时必须指定初审人')
        
        # Property 2: Control Sheet Enforcement (Task 15.3)
        if FEATURE_CONTROL_SHEET and payload.get('status') == 'initial_review':
            _validate_control_sheet_completeness(conn, None, payload, 'initial_review')

        order = create_change_order(
            conn,
            title=payload['title'],
            description=payload['description'],
            order_type=payload['order_type'],
            priority=payload['priority'],
            status=payload.get('status', 'draft'),
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
            authorization_exempt=bool(payload.get('authorization_exempt')),
            control_sheet=payload.get('control_sheet') or {},
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
            
        existing = get_change_order(conn, order_id)
        if not existing:
            raise HTTPException(status_code=404, detail='Change order not found')
            
        # Merge updates with existing for validation
        full_payload = {**existing, **updates}
        _validate_assignment_rules(existing.get('requester_username'), full_payload)
        
        # Property 1: Template Enforcement (Task 14.1)
        if FEATURE_TEMPLATE_REQUIRED:
            _validate_template_completeness(full_payload)
        
        # Property 2: Control Sheet Enforcement (Task 15.3)
        if FEATURE_CONTROL_SHEET and full_payload.get('status') == 'initial_review' and existing.get('status') != 'initial_review':
             _validate_control_sheet_completeness(conn, order_id, full_payload, 'initial_review')

        order = update_change_order(conn, order_id, updates)
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
        if requester_username and requester_username == actor_username:
            if new_status in {'final_review', 'approved', 'rejected'} or (new_status == 'initial_review' and current_status != 'draft'):
                raise HTTPException(status_code=403, detail='申请人不能审核或审批自己的变更工单')
        # Final approval requires administrator role.
        if new_status == 'approved' and user.get('role') != 'Administrator':
            raise HTTPException(status_code=403, detail='只有管理员角色的用户才能执行最终审批')
        # Final-stage reject also requires administrator role.
        if current_status == 'final_review' and new_status in {'rejected', 'initial_review'} and user.get('role') != 'Administrator':
            raise HTTPException(status_code=403, detail='只有管理员角色的用户才能在终审阶段驳回工单')
        if current_status == 'initial_review' and new_status in {'final_review', 'rejected'}:
            assigned_initial_reviewer_id = str(existing.get('assigned_initial_reviewer_id') or '')
            if assigned_initial_reviewer_id and assigned_initial_reviewer_id != str(user.get('user_id') or ''):
                raise HTTPException(status_code=403, detail='只有被指定的初审人才能处理此工单的初审')
            if not assigned_initial_reviewer_id and actor_groups and 'initial_reviewer' not in actor_groups and user.get('role') != 'Administrator':
                raise HTTPException(status_code=403, detail='只有初审组成员或管理员才能处理此工单的初审')
        if current_status == 'final_review' and new_status in {'approved', 'rejected', 'initial_review'}:
            assigned_final_approver_id = str(existing.get('assigned_final_approver_id') or '')
            if assigned_final_approver_id and assigned_final_approver_id != str(user.get('user_id') or ''):
                raise HTTPException(status_code=403, detail='只有被指定的终审人才能处理此工单的终审')
            if not assigned_final_approver_id and actor_groups and 'final_approver' not in actor_groups and user.get('role') != 'Administrator':
                raise HTTPException(status_code=403, detail='只有终审组成员或管理员才能处理此工单的终审')
        
        # Implementation stages: Only requester can operate
        implementation_statuses = {'implementing', 'completed', 'failed', 'rollback_in_progress', 'rolled_back'}
        if new_status in implementation_statuses or current_status in implementation_statuses:
            if requester_username != actor_username and user.get('role') != 'Administrator':
                raise HTTPException(status_code=403, detail='只有工单申请人（实施人）才能操作实施阶段')
        
        if new_status == 'final_review' and not existing.get('assigned_final_approver_id'):
            # If moving to final review, check if it was assigned during the transition
            assigned_final = body.get('assigned_final_approver_id') or existing.get('assigned_final_approver_id')
            if not assigned_final:
                raise HTTPException(status_code=400, detail='提交终审时必须指定终审人')

        updates = {'status': new_status}
        if new_status == 'draft' and current_status in {'initial_review', 'final_review', 'rejected'}:
            # Task 13.1 / Property 5 / Bug C4:
            # When transitioning back to draft (reject→draft or direct pushback→draft),
            # clear all six approver witness fields and pop the two review timestamps
            # from result_detail.  Keep rejected_reason and the timeline event intact.
            updates.update({
                'assigned_initial_reviewer_id': '',
                'assigned_initial_reviewer_username': '',
                'assigned_final_approver_id': '',
                'assigned_final_approver_username': '',
                'initial_reviewer_id': '',
                'initial_reviewer_username': '',
                'final_approver_id': '',
                'final_approver_username': '',
                'approver_id': '',
                'approver_username': '',
            })
            # Only pop the two review-phase timestamps; preserve rejected_reason,
            # rejected_at, rejected_by, rejected_stage so the rejection history is
            # still visible in the timeline / detail view.
            rd = dict(existing.get('result_detail') or {})
            rd.pop('initial_review_at', None)
            rd.pop('approved_at', None)
            updates['result_detail'] = rd
        if new_status in {'rejected', 'initial_review'} and current_status in {'initial_review', 'final_review'}:
            updates['rejected_reason'] = body.get('rejected_reason', '')
            
            # Record who performed the review action (rejection/pushback)
            if current_status == 'initial_review':
                updates['initial_reviewer_id'] = user.get('user_id', '')
                updates['initial_reviewer_username'] = user.get('username', '')
            elif current_status == 'final_review':
                updates['final_approver_id'] = user.get('user_id', '')
                updates['final_approver_username'] = user.get('username', '')

            updates['result_detail'] = {
                **(existing.get('result_detail') or {}),
                'rejected_by': user.get('username', ''),
                'rejected_at': _utc_now_iso(),
                'rejected_stage': current_status,
            }
        if new_status == 'final_review':
            updates['initial_reviewer_id'] = user.get('user_id', '')
            updates['initial_reviewer_username'] = user.get('username', '')
            
            final_approver_id = body.get('assigned_final_approver_id')
            if final_approver_id:
                resolved = _resolve_assignment_user(conn, final_approver_id, stage='final')
                updates['assigned_final_approver_id'] = resolved['id']
                updates['assigned_final_approver_username'] = resolved['username']
            
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
            }

        # Property 3 & 4 (Task 12.1)
        full_payload = {**existing, **updates}
        _validate_assignment_rules(existing.get('requester_username'), full_payload)
        
        # Property 1 & 2 Enforcement (Task 14.1, 15.3)
        if new_status == 'initial_review':
            if FEATURE_TEMPLATE_REQUIRED:
                _validate_template_completeness(full_payload)
            if FEATURE_CONTROL_SHEET:
                _validate_control_sheet_completeness(conn, order_id, full_payload, 'initial_review')
        if new_status == 'implementing':
            if FEATURE_CONTROL_SHEET:
                _validate_control_sheet_completeness(conn, order_id, full_payload, 'implementing')

        order = update_change_order(conn, order_id, updates)
        severity = 'high' if new_status in ('rejected', 'failed') else 'medium'
        log_audit_event(
            event_type=f'change_order.{new_status}',
            category='change_order',
            severity=severity,
            status='open',
            summary=f"变更工单 {existing['order_number']} 状态变更为 {STATUS_ZH.get(new_status, new_status)}",
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
        return {'success': True, 'data': order, 'message': f"工单状态已更新为 {STATUS_ZH.get(new_status, new_status)}"}
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


# ── Control Sheet Upload ─────────────────────────────────────────────

# MIME whitelist for control-sheet attachments (Property 2 / Req 2.5)
_CONTROL_SHEET_ALLOWED_MIMES: frozenset[str] = frozenset({
    'application/pdf',
    'application/msword',                                                    # .doc
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
    'application/vnd.ms-excel',                                              # .xls
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',    # .xlsx
})

# Extension → canonical MIME (used when the client sends an empty / wrong content-type)
_EXT_TO_MIME: dict[str, str] = {
    '.pdf':  'application/pdf',
    '.doc':  'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls':  'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

# Statuses that allow control-sheet uploads (design.md §API Surface Changes)
_CONTROL_SHEET_UPLOAD_STATUSES: frozenset[str] = frozenset({
    'approved', 'implementing', 'completed', 'rolled_back',
})

_CONTROL_SHEET_MAX_BYTES: int = 20 * 1024 * 1024  # 20 MiB


@router.post('/change-orders/{order_id}/control-sheet')
async def api_upload_control_sheet(
    order_id: str,
    file: UploadFile = File(...),
    note: Optional[str] = Form(None),
    user=require_role("Operator"),
):
    """
    POST /api/change-orders/{order_id}/control-sheet

    Upload a control-sheet attachment (pdf / doc / docx / xlsx, ≤ 20 MiB).

    Authorization:
      - The authenticated user must be the order's requester, or have the
        Administrator role.  (Implementer is the requester in this workflow.)
      - The order must be in one of: approved / implementing / completed / rolled_back.

    Validates: Property 2 (design.md §Correctness Properties)
    Requirements: 2.5
    """
    conn = get_db_connection()
    try:
        # 1. Verify order exists
        existing = get_change_order(conn, order_id)
        if not existing:
            raise HTTPException(status_code=404, detail='Change order not found')

        # 2. Authorization: requester or Administrator
        actor_username = user.get('username', '')
        actor_role = user.get('role', '')
        requester_username = existing.get('requester_username', '')
        if actor_username != requester_username and actor_role != 'Administrator':
            raise HTTPException(
                status_code=403,
                detail='只有工单申请人（实施人）或管理员才能上传变更控制表附件',
            )

        # 3. Status check
        order_status = existing.get('status', '')
        if order_status not in _CONTROL_SHEET_UPLOAD_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f'当前工单状态 "{order_status}" 不允许上传变更控制表附件；'
                    f'允许的状态：{", ".join(sorted(_CONTROL_SHEET_UPLOAD_STATUSES))}'
                ),
            )

        # 4. MIME type validation
        #    Prefer the client-supplied content_type; fall back to extension mapping.
        client_mime = (file.content_type or '').strip().lower().split(';')[0].strip()
        filename = file.filename or ''
        ext = os.path.splitext(filename)[1].lower()
        resolved_mime = client_mime if client_mime in _CONTROL_SHEET_ALLOWED_MIMES else _EXT_TO_MIME.get(ext, client_mime)

        if resolved_mime not in _CONTROL_SHEET_ALLOWED_MIMES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f'不支持的文件类型 "{client_mime or ext or "unknown"}"；'
                    '仅允许上传 PDF、Word（.doc/.docx）、Excel（.xls/.xlsx）文件'
                ),
            )

        # 5. Read file content and enforce size limit
        content = await file.read()
        if len(content) > _CONTROL_SHEET_MAX_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f'文件大小超过限制（最大 20 MiB，当前 {len(content) / 1024 / 1024:.1f} MiB）',
            )
        if len(content) == 0:
            raise HTTPException(status_code=400, detail='上传的文件不能为空')

        # 6. Persist file to storage directory
        attachment_id = f"cs-{uuid.uuid4().hex[:12]}"
        safe_ext = ext if ext in _EXT_TO_MIME else '.bin'
        stored_filename = f"{attachment_id}{safe_ext}"
        attachments_dir = os.path.join(PROJECT_ROOT, 'data', 'change_order_attachments')
        os.makedirs(attachments_dir, exist_ok=True)
        file_path = os.path.join(attachments_dir, stored_filename)

        with open(file_path, 'wb') as fh:
            fh.write(content)

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

        # 7. Insert row into change_order_control_sheet_attachments
        conn.execute(
            '''
            INSERT INTO change_order_control_sheet_attachments
                (id, order_id, file_path, file_name, file_size, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (attachment_id, order_id, file_path, filename or stored_filename, len(content), now),
        )

        # 8. Emit audit event
        log_audit_event(
            event_type='change_order.control_sheet_uploaded',
            category='change_order',
            severity='low',
            status='open',
            summary=(
                f"变更工单 {existing['order_number']} 上传了变更控制表附件: "
                f"{filename or stored_filename}"
            ),
            actor_id=user.get('user_id'),
            actor_username=actor_username,
            actor_role=actor_role,
            target_type='change_order',
            target_id=order_id,
            target_name=existing['order_number'],
            details={
                'attachment_id': attachment_id,
                'filename': filename or stored_filename,
                'mime_type': resolved_mime,
                'size_bytes': len(content),
                'note': note or '',
            },
            conn=conn,
        )

        conn.commit()

        return {
            'success': True,
            'data': {
                'id': attachment_id,
                'filename': filename or stored_filename,
                'mime_type': resolved_mime,
                'size_bytes': len(content),
                'uploaded_at': now,
                'note': note or '',
            },
        }
    finally:
        conn.close()


@router.post('/change-orders/{order_id}/attachments')
async def api_upload_attachment(order_id: str, file: UploadFile = File(...), user=require_role("Operator")):
    conn = get_db_connection()
    try:
        existing = get_change_order(conn, order_id)
        if not existing:
            raise HTTPException(status_code=404, detail='Change order not found')
        
        attachment_id = f"att-{uuid.uuid4().hex[:12]}"
        file_ext = os.path.splitext(file.filename)[1]
        stored_filename = f"{attachment_id}{file_ext}"
        attachments_dir = os.path.join(PROJECT_ROOT, 'data', 'change_order_attachments')
        file_path = os.path.join(attachments_dir, stored_filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(file_path)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        conn.execute('''
            INSERT INTO change_order_control_sheet_attachments (id, order_id, file_path, file_name, file_size, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (attachment_id, order_id, file_path, file.filename, file_size, now))
        conn.commit()
        
        return {'success': True, 'data': {'id': attachment_id, 'file_name': file.filename, 'file_size': file_size}}
    finally:
        conn.close()


@router.get('/change-orders/{order_id}/attachments/{attachment_id}')
def api_get_attachment(order_id: str, attachment_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT file_path, file_name FROM change_order_control_sheet_attachments WHERE id = ? AND order_id = ?',
            (attachment_id, order_id)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Attachment not found')
        
        return FileResponse(row['file_path'], filename=row['file_name'])
    finally:
        conn.close()


@router.delete('/change-orders/{order_id}/attachments/{attachment_id}')
def api_delete_attachment(order_id: str, attachment_id: str, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT file_path FROM change_order_control_sheet_attachments WHERE id = ? AND order_id = ?',
            (attachment_id, order_id)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Attachment not found')
        
        file_path = row['file_path']
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
            
        conn.execute('DELETE FROM change_order_control_sheet_attachments WHERE id = ?', (attachment_id,))
        conn.commit()
        return {'success': True, 'message': '附件已删除'}
    finally:
        conn.close()
