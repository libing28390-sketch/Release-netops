import os
import json
import uuid
import logging
import sys
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from database import get_db_connection
from core.rbac import require_role
from core.tenant_policy import TENANT_ISOLATION_ENABLED
from services.change_order_service import (
    control_sheet_implementer,
    control_sheet_result_reviewer,
    normalize_control_sheet_identity,
)

logger = logging.getLogger(__name__)

# ── Base Feature Flags ──────────────────────────────────────────────
_BASE_FEATURE_TEMPLATE_REQUIRED: bool = os.environ.get('FEATURE_TEMPLATE_REQUIRED', '0').strip() == '1'
_BASE_FEATURE_CONTROL_SHEET: bool = os.environ.get('FEATURE_CONTROL_SHEET', '0').strip() == '1'


_RISK_RANK = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}


def scan_change_commands(commands: list, platform: str = '') -> dict:
    """Statically scan rendered commands and return explainable guard evidence."""
    flattened = []
    for command in commands or []:
        flattened.extend(str(command or '').splitlines())
    findings: list[dict] = []
    blocked_patterns = (
        (r'\bwrite\s+erase\b', '清空启动配置'),
        (r'\berase\s+startup-config\b', '清空启动配置'),
        (r'\breset\s+saved-configuration\b', '清空已保存配置'),
        (r'\bfactory[- ]?reset\b', '恢复出厂设置'),
        (r'(^|\s)format(\s|$)', '格式化存储'),
        (r'\brm\s+-rf\s+/(?:\s|$)', '递归删除根目录'),
        (r'\bdel\s+/[sq]\b', 'Windows 递归删除'),
    )
    high_patterns = (
        (r'(^|\s)(reload|reboot)(\s|$)', '设备重启'),
        (r'(^|\s)(shutdown|undo\s+shutdown|no\s+shutdown)(\s|$)', '接口或系统启停'),
        (r'\b(no|undo|delete)\s+(router|protocols?|bgp|ospf|isis|aaa|ssh)\b', '关键控制面删除'),
        (r'\b(access-list|acl|firewall|traffic-policy|route-policy)\b', '安全或路由策略变更'),
        (r'\b(username|local-user|aaa|authentication|authorization)\b', '账号或认证配置变更'),
        (r'\b(management|mgmt|vty|ssh)\b', '管理通道变更'),
    )
    for index, raw_line in enumerate(flattened, start=1):
        line = raw_line.strip()
        if not line or line.startswith(('#', '!', '//')):
            continue
        lowered = line.lower()
        for pattern, reason in blocked_patterns:
            if re.search(pattern, lowered):
                findings.append({
                    'line': index,
                    'command': line,
                    'risk': 'critical',
                    'action': 'block',
                    'reason': reason,
                })
                break
        else:
            for pattern, reason in high_patterns:
                if re.search(pattern, lowered):
                    findings.append({
                        'line': index,
                        'command': line,
                        'risk': 'high',
                        'action': 'require_approval',
                        'reason': reason,
                    })
                    break

    max_risk = max(
        (item['risk'] for item in findings),
        key=lambda item: _RISK_RANK[item],
        default='low',
    )
    return {
        'platform': platform or 'unknown',
        'scanned_lines': len(flattened),
        'max_risk': max_risk,
        'blocked': any(item['action'] == 'block' for item in findings),
        'findings': findings,
    }


APPROVAL_SNAPSHOT_VERSION = 2
CHANGE_WINDOW_TIMEZONE = ZoneInfo('Asia/Shanghai')


def _parse_change_window_to_utc(value: object) -> datetime | None:
    """Parse ISO timestamps; legacy and datetime-local values use Asia/Shanghai."""
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CHANGE_WINDOW_TIMEZONE)
    return parsed.astimezone(timezone.utc)


def _snapshot_time_value(value: object) -> str:
    """Hash valid window values in UTC while retaining malformed input evidence."""
    raw = str(value or '').strip()
    parsed = _parse_change_window_to_utc(raw)
    return parsed.isoformat() if parsed else raw


def assert_change_order_window_open(order: dict, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Require an open [start, end) window, comparing all values in UTC.

    ISO offsets are authoritative.  Existing timezone-less UI values are
    interpreted as Asia/Shanghai wall time for compatibility.
    """
    raw_start = str(order.get('scheduled_start') or '').strip()
    raw_end = str(order.get('scheduled_end') or '').strip()
    start = _parse_change_window_to_utc(raw_start)
    end = _parse_change_window_to_utc(raw_end)
    if not raw_start or not raw_end:
        raise HTTPException(status_code=409, detail='变更窗口缺失，必须重新申请并重新审批')
    if start is None or end is None or start >= end:
        raise HTTPException(status_code=409, detail='变更窗口无效，必须修正后重新审批')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    if current < start:
        raise HTTPException(status_code=409, detail='变更窗口尚未开始，暂不能实施')
    if current >= end:
        raise HTTPException(status_code=409, detail='变更窗口已结束，必须重新申请并重新审批')
    return start, end


def assert_change_order_window_approvable(order: dict, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Require a valid window that has not expired, allowing approval before its start."""
    raw_start = str(order.get('scheduled_start') or '').strip()
    raw_end = str(order.get('scheduled_end') or '').strip()
    start = _parse_change_window_to_utc(raw_start)
    end = _parse_change_window_to_utc(raw_end)
    if not raw_start or not raw_end:
        raise HTTPException(status_code=409, detail='变更窗口缺失，必须调整后重新提交审批')
    if start is None or end is None or start >= end:
        raise HTTPException(status_code=409, detail='变更窗口无效，必须修正后重新提交审批')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if current.astimezone(timezone.utc) >= end:
        raise HTTPException(status_code=409, detail='变更窗口已结束，请调整实施时间并重新提交审批')
    return start, end


def approval_snapshot_hash(order: dict) -> str:
    """Hash all content that can affect an approved change or its execution."""
    attachments = order.get('control_sheet_attachments')
    if not isinstance(attachments, list):
        attachments = []
    attachment_scope = [
        {
            'id': str(item.get('id') or ''),
            'file_name': str(item.get('file_name') or ''),
            'file_size': int(item.get('file_size') or 0),
            'created_at': str(item.get('created_at') or ''),
            'sha256': str(item.get('sha256') or ''),
        }
        for item in attachments if isinstance(item, dict)
    ]
    attachment_scope.sort(key=lambda item: (item['id'], item['created_at'], item['file_name']))
    payload = {
        'version': APPROVAL_SNAPSHOT_VERSION,
        'title': order.get('title') or '',
        'description': order.get('description') or '',
        'requester_id': str(order.get('requester_id') or ''),
        'assigned_initial_reviewer_id': str(order.get('assigned_initial_reviewer_id') or ''),
        'assigned_final_approver_id': str(order.get('assigned_final_approver_id') or ''),
        'order_type': order.get('order_type') or '',
        'emergency_reason': str(order.get('emergency_reason') or '').strip(),
        'emergency_review_owner_id': str(order.get('emergency_review_owner_id') or '').strip(),
        'emergency_review_due_at_utc': _snapshot_time_value(order.get('emergency_review_due_at')),
        'priority': order.get('priority') or '',
        'target_devices': order.get('target_devices') or [],
        'commands': order.get('commands') or [],
        'rollback_plan': order.get('rollback_plan') or '',
        'risk_level': order.get('risk_level') or '',
        'scheduled_start_utc': _snapshot_time_value(order.get('scheduled_start')),
        'scheduled_end_utc': _snapshot_time_value(order.get('scheduled_end')),
        'authorization_exempt': bool(order.get('authorization_exempt')),
        'command_template': order.get('command_template') or {},
        'control_sheet': normalize_control_sheet_identity(order.get('control_sheet')),
        'control_sheet_attachments': attachment_scope,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def resolve_active_order_implementer(conn, order: dict) -> dict:
    """Resolve the explicit, active implementation identity by stable user ID."""
    control_sheet = normalize_control_sheet_identity(order.get('control_sheet'))
    implementation = control_sheet_implementer(control_sheet)
    implementer_id = str(implementation.get('id') or '').strip()
    if not implementer_id:
        raise HTTPException(status_code=409, detail='工单未指定实施人，必须指派实施人并重新审批')
    row = conn.execute(
        'SELECT id, username, role, role_profile, status, tenant_id, scope_mode FROM users WHERE id = ?',
        (implementer_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail='指定实施人账号不存在，不能实施')
    implementer = dict(row)
    if str(implementer.get('status') or '').lower() != 'active':
        raise HTTPException(status_code=403, detail='指定实施人账号已停用，不能实施')
    if TENANT_ISOLATION_ENABLED and str(implementer.get('tenant_id') or '') != str(order.get('tenant_id') or ''):
        raise HTTPException(status_code=403, detail='指定实施人与工单不属于同一租户')
    return implementer


def _resolve_active_review_identity(conn, order: dict, user_id: str, username: str, label: str) -> dict:
    stable_id = str(user_id or '').strip()
    display_name = str(username or '').strip()
    if not stable_id and not display_name:
        return {}
    if stable_id:
        row = conn.execute(
            'SELECT id, username, status, tenant_id FROM users WHERE id = ?', (stable_id,),
        ).fetchone()
    else:
        row = conn.execute(
            'SELECT id, username, status, tenant_id FROM users WHERE username = ?', (display_name,),
        ).fetchone()
    if not row or str(row['status'] or '').lower() != 'active':
        raise HTTPException(status_code=409, detail=f'{label}账号不存在或已停用')
    reviewer = dict(row)
    if TENANT_ISOLATION_ENABLED and str(reviewer.get('tenant_id') or '') != str(order.get('tenant_id') or ''):
        raise HTTPException(status_code=409, detail=f'{label}必须属于工单所在租户')
    return reviewer


def resolve_active_order_result_reviewer(conn, order: dict, *, required: bool = False) -> dict:
    """Resolve the optional co_reviewer, retaining username-only legacy compatibility."""
    configured = control_sheet_result_reviewer(order.get('control_sheet'))
    if not configured:
        if required:
            raise HTTPException(status_code=409, detail='工单未指定实施结果复核人')
        return {}
    return _resolve_active_review_identity(
        conn,
        order,
        configured.get('id'),
        configured.get('username'),
        '实施结果复核人',
    )


def resolve_active_order_initial_reviewer(conn, order: dict) -> dict:
    """Resolve the original initial reviewer, preferring the recorded decision maker."""
    reviewer_id = str(order.get('initial_reviewer_id') or '').strip()
    if not reviewer_id:
        reviewer_id = str(order.get('assigned_initial_reviewer_id') or '').strip()
    reviewer_username = str(order.get('initial_reviewer_username') or '').strip()
    if not reviewer_username:
        reviewer_username = str(order.get('assigned_initial_reviewer_username') or '').strip()
    if not reviewer_id and not reviewer_username:
        raise HTTPException(status_code=409, detail='工单未保留原初审人身份')
    return _resolve_active_review_identity(
        conn, order, reviewer_id, reviewer_username, '原初审人',
    )


def is_order_result_review_participant(conn, order: dict, actor_id: str) -> bool:
    """Return whether an active, same-tenant assigned reviewer may read this order."""
    try:
        result_reviewer = resolve_active_order_result_reviewer(conn, order)
    except HTTPException:
        result_reviewer = {}
    if result_reviewer and str(result_reviewer.get('id') or '') == str(actor_id or ''):
        return True
    try:
        initial_reviewer = resolve_active_order_initial_reviewer(conn, order)
    except HTTPException:
        initial_reviewer = {}
    return bool(initial_reviewer and str(initial_reviewer.get('id') or '') == str(actor_id or ''))


def assert_explicit_execution_profile(user: dict, resource_type: str, action: str = 'execute') -> None:
    """Prevent an Administrator's coarse role wildcard from granting execution."""
    if user.get('role') == 'Administrator' and not str(user.get('role_profile') or '').strip():
        raise HTTPException(status_code=403, detail=f'管理员账号必须具备明确的 {resource_type}.{action} 执行权限配置')


def assert_order_mfa_valid(order: dict, user_id: str, username: str, now: datetime | None = None) -> None:
    detail = order.get('result_detail') if isinstance(order.get('result_detail'), dict) else {}
    if str(detail.get('mfa_verified_by_id') or '') != str(user_id or '') or str(detail.get('mfa_verified_by') or '') != str(username or ''):
        raise HTTPException(status_code=403, detail='实施 MFA 身份与当前账号不一致')
    raw_verified_at = str(detail.get('mfa_verified_at') or '').strip()
    try:
        verified_at = datetime.fromisoformat(raw_verified_at.replace('Z', '+00:00'))
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise HTTPException(status_code=403, detail='实施授权缺少有效的 MFA 记录')
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = (current.astimezone(timezone.utc) - verified_at.astimezone(timezone.utc)).total_seconds()
    if age < -30 or age > 300:
        raise HTTPException(status_code=403, detail='实施 MFA 已过期或时间无效，请重新完成实施授权')


def assert_order_verification_complete(order: dict, *, rollback: bool = False) -> None:
    detail = order.get('result_detail') if isinstance(order.get('result_detail'), dict) else {}
    records = detail.get('verification_records')
    if not isinstance(records, list):
        records = []
    current_snapshot = approval_snapshot_hash(order)
    current_records = [
        item for item in records
        if isinstance(item, dict) and str(item.get('approval_snapshot_hash') or '') == current_snapshot
    ]
    if rollback:
        rollback_started_at = str(detail.get('rollback_started_at') or '').strip()
        if not rollback_started_at:
            raise HTTPException(status_code=409, detail='回退恢复验证缺少回退开始记录')
        try:
            rollback_started = datetime.fromisoformat(rollback_started_at.replace('Z', '+00:00'))
            if rollback_started.tzinfo is None:
                rollback_started = rollback_started.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=409, detail='回退开始时间无效，不能完成回退')
        filtered_records = []
        for record in current_records:
            try:
                recorded_at = datetime.fromisoformat(str(record.get('created_at') or '').replace('Z', '+00:00'))
                if recorded_at.tzinfo is None:
                    recorded_at = recorded_at.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if recorded_at.astimezone(timezone.utc) >= rollback_started.astimezone(timezone.utc):
                filtered_records.append(record)
        current_records = filtered_records
    technical = [item for item in current_records if item.get('kind') == 'technical']
    if not technical or technical[-1].get('result') != 'passed':
        message = '回退完成前必须记录回退后的技术恢复验证' if rollback else '完成工单前必须有通过的技术验证记录'
        raise HTTPException(status_code=409, detail=message)

    control_sheet = normalize_control_sheet_identity(order.get('control_sheet'))
    business_confirmer = control_sheet.get('business_confirmer') or {}
    business_configured = bool(
        str(control_sheet.get('business_verify') or '').strip()
        or str(business_confirmer.get('id') or '').strip()
        or str(business_confirmer.get('username') or '').strip()
    )
    if business_configured:
        business = [item for item in current_records if item.get('kind') == 'business']
        if not business or business[-1].get('result') != 'passed':
            message = '该工单已配置业务验证，回退完成前必须有通过的业务恢复验证' if rollback else '该工单已配置业务验证，完成前必须有通过的业务验证记录'
            raise HTTPException(status_code=409, detail=message)


def is_template_required() -> bool:
    """Dynamically resolve FEATURE_TEMPLATE_REQUIRED from package namespace for monkeypatching compatibility."""
    co_module = sys.modules.get('api.change_orders')
    if co_module and hasattr(co_module, 'FEATURE_TEMPLATE_REQUIRED'):
        return co_module.FEATURE_TEMPLATE_REQUIRED
    return _BASE_FEATURE_TEMPLATE_REQUIRED


def is_control_sheet_enabled() -> bool:
    """Dynamically resolve FEATURE_CONTROL_SHEET from package namespace for monkeypatching compatibility."""
    co_module = sys.modules.get('api.change_orders')
    if co_module and hasattr(co_module, 'FEATURE_CONTROL_SHEET'):
        return co_module.FEATURE_CONTROL_SHEET
    return _BASE_FEATURE_CONTROL_SHEET


ALLOWED_STATUSES = {
    'draft', 'initial_review', 'final_review', 'approved', 'implementing', 'completed',
    'implementation_review', 'implementation_result_review',
    'rollback_in_progress', 'rolled_back', 'rejected', 'failed', 'cancelled',
    'pending', 'executing',
}

ALLOWED_TRANSITIONS = {
    'draft': {'initial_review', 'cancelled'},
    'initial_review': {'final_review', 'rejected', 'cancelled'},
    'final_review': {'approved', 'rejected', 'cancelled', 'initial_review'},
    'approved': {'implementing', 'cancelled'},
    'implementing': {'completed', 'implementation_review', 'failed', 'rollback_in_progress', 'cancelled'},
    'rollback_in_progress': {'rolled_back', 'failed'},
    'failed': {'implementation_review', 'rollback_in_progress', 'cancelled'},
    'implementation_review': {'completed', 'implementation_result_review'},
    'implementation_result_review': {'completed', 'failed'},
    'rejected': {'draft', 'cancelled'},
    'completed': set(),
    'rolled_back': set(),
    'cancelled': set(),
    'pending': {'approved', 'rejected', 'cancelled'},
    'executing': {'completed', 'failed', 'rollback_in_progress', 'cancelled'},
}

assert ALLOWED_STATUSES <= ALLOWED_TRANSITIONS.keys(), (
    "ALLOWED_TRANSITIONS is missing keys for: "
    + str(ALLOWED_STATUSES - ALLOWED_TRANSITIONS.keys())
)

STATUS_ZH = {
    'draft': '草稿',
    'initial_review': '初审中',
    'final_review': '终审中',
    'approved': '审批完成',
    'implementing': '实施中',
    'implementation_review': '实施结果复核中',
    'implementation_result_review': '实施结果初审中',
    'completed': '完成',
    'rollback_in_progress': '回溯中',
    'rolled_back': '已回溯',
    'rejected': '已驳回',
    'failed': '执行失败',
    'cancelled': '已取消',
}

_TEMPLATE_REQUIRED_STATUSES = frozenset({
    'initial_review', 'final_review', 'approved', 'implementing', 'completed',
})


def _validate_assignment_rules(requester_username: str, payload: dict):
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

    control_sheet = normalize_control_sheet_identity(payload.get('control_sheet'))
    implementer = control_sheet_implementer(control_sheet)
    implementer_id = str(implementer.get('id') or '').strip().casefold()
    implementer_username = str(implementer.get('username') or '').strip().casefold()
    if not implementer_id and not implementer_username:
        return

    def _same_person(user_id: object, username: object) -> bool:
        candidate_id = str(user_id or '').strip().casefold()
        candidate_username = str(username or '').strip().casefold()
        if implementer_id and candidate_id:
            return implementer_id == candidate_id
        return bool(implementer_username and candidate_username and implementer_username == candidate_username)

    assigned_reviewers = (
        ('初审人', rev_id, rev_name),
        ('终审人', app_id, app_name),
    )
    for label, reviewer_id, reviewer_username in assigned_reviewers:
        if _same_person(reviewer_id, reviewer_username):
            raise HTTPException(status_code=400, detail=f'实施人不能同时担任{label}')

    co_reviewer = control_sheet.get('co_reviewer')
    co_reviewer = co_reviewer if isinstance(co_reviewer, dict) else {}
    co_reviewer_id = co_reviewer.get('id') or control_sheet.get('co_reviewer_id')
    co_reviewer_username = co_reviewer.get('username') or control_sheet.get('co_reviewer_username')
    if _same_person(co_reviewer_id, co_reviewer_username):
        raise HTTPException(status_code=400, detail='复核人不能与实施人相同')

    business_confirmer = control_sheet.get('business_confirmer')
    business_confirmer = business_confirmer if isinstance(business_confirmer, dict) else {}
    confirmer_id = business_confirmer.get('id')
    confirmer_username = business_confirmer.get('username')
    if _same_person(confirmer_id, confirmer_username):
        raise HTTPException(status_code=400, detail='实施人不能同时担任业务确认人')


def validate_emergency_change_details(conn, order: dict) -> dict:
    """Validate emergency rationale and independent post-implementation review."""
    if str(order.get('order_type') or '') != 'emergency':
        return order
    reason = str(order.get('emergency_reason') or '').strip()
    reviewer_id = str(order.get('emergency_review_owner_id') or '').strip()
    due_raw = str(order.get('emergency_review_due_at') or '').strip()
    if not reason:
        raise HTTPException(status_code=422, detail='紧急变更必须填写紧急原因')
    if not reviewer_id:
        raise HTTPException(status_code=422, detail='紧急变更必须指定事后复核人')
    if not due_raw:
        raise HTTPException(status_code=422, detail='紧急变更必须设置事后复核期限')
    try:
        due_at = datetime.fromisoformat(due_raw.replace('Z', '+00:00'))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail='事后复核期限格式无效') from exc
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    due_at = due_at.astimezone(timezone.utc)
    if due_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail='事后复核期限必须晚于当前时间')

    reviewer_row = conn.execute(
        'SELECT id, status, tenant_id FROM users WHERE id = ?', (reviewer_id,),
    ).fetchone()
    if not reviewer_row or str(reviewer_row['status'] or '').lower() != 'active':
        raise HTTPException(status_code=422, detail='事后复核人不存在或未启用')
    reviewer = dict(reviewer_row)
    tenant_id = str(order.get('tenant_id') or '')
    if tenant_id and str(reviewer.get('tenant_id') or '') != tenant_id:
        raise HTTPException(status_code=422, detail='事后复核人必须属于同一租户')
    if reviewer_id == str(order.get('requester_id') or ''):
        raise HTTPException(status_code=422, detail='事后复核人必须与申请人分离')
    try:
        implementer = resolve_active_order_implementer(conn, order)
    except HTTPException as exc:
        raise HTTPException(status_code=422, detail='紧急变更必须先指定有效的实施人') from exc
    if reviewer_id == str(implementer.get('id') or ''):
        raise HTTPException(status_code=422, detail='事后复核人必须与实施人分离')
    return {
        **order,
        'emergency_reason': reason,
        'emergency_review_owner_id': reviewer_id,
        'emergency_review_due_at': due_at.isoformat().replace('+00:00', 'Z'),
        'emergency_review_status': 'pending',
        'emergency_reviewed_by_id': '',
        'emergency_reviewed_by': '',
        'emergency_reviewed_at': None,
        'emergency_review_note': '',
    }


def _validate_template_completeness(payload: dict):
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
    if new_status == 'initial_review':
        cs = payload.get('control_sheet')
        cs = cs if isinstance(cs, dict) else {}
        missing = []
        def add_missing(label: str):
            if label not in missing:
                missing.append(label)

        change_time = cs.get('change_time')
        if not isinstance(change_time, dict) or (
            not str(change_time.get('start') or '').strip()
            or not str(change_time.get('end') or '').strip()
        ):
            add_missing('变更时间')

        for field, label in (('implementer', '实施人'),):
            person = cs.get(field)
            if not isinstance(person, dict) or not (
                str(person.get('id') or '').strip() or str(person.get('username') or '').strip()
            ):
                add_missing(label)

        device_ips = cs.get('device_ips')
        if not isinstance(device_ips, list) or not any(str(value or '').strip() for value in device_ips):
            add_missing('目标设备')

        required_text_fields = (
            ('pre_check', '变更前检查'),
            ('execution', '人工实施步骤'),
            ('post_verify', '变更后验证'),
            ('business_verify', '业务验证'),
            ('rollback_plan', '回退命令'),
        )
        for field, label in required_text_fields:
            value = cs.get(field)
            if not isinstance(value, str) or not value.strip():
                add_missing(label)

        if missing:
            raise HTTPException(
                status_code=400,
                detail=f'提交初审前必须填写完整的变更控制表：{"、".join(missing)}',
            )

    if new_status == 'implementing':
        count = conn.execute(
            "SELECT COUNT(*) FROM change_order_control_sheet_attachments WHERE order_id = ?",
            (order_id,)
        ).fetchone()[0]
        if count == 0:
            raise HTTPException(status_code=400, detail='进入实施阶段前必须上传至少一个附件（变更控制表扫描件/截图）')


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
        if user.get('role') != 'Administrator':
            raise HTTPException(status_code=400, detail='Initial reviewer must be an Administrator')
        if 'initial_reviewer' not in groups:
            raise HTTPException(status_code=400, detail='Selected user is not in the initial review group')
    if stage == 'final':
        if user.get('role') != 'Administrator':
            raise HTTPException(status_code=400, detail='Final approver must be an Administrator')
        if 'final_approver' not in groups:
            raise HTTPException(status_code=400, detail='Selected user is not in the final approval group')
    return {'id': str(user.get('id') or ''), 'username': str(user.get('username') or '')}


def _normalize_assignment_payload(conn, payload: dict, *, tenant_id: str = '') -> dict:
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

    configured_result_reviewer = control_sheet_result_reviewer(normalized.get('control_sheet'))
    reviewer_id = str(configured_result_reviewer.get('id') or '').strip()
    reviewer_username = str(configured_result_reviewer.get('username') or '').strip()
    if reviewer_id or reviewer_username:
        if reviewer_id:
            reviewer_row = conn.execute(
                'SELECT id, username, status, tenant_id FROM users WHERE id = ?',
                (reviewer_id,),
            ).fetchone()
        else:
            reviewer_row = conn.execute(
                'SELECT id, username, status, tenant_id FROM users WHERE username = ?',
                (reviewer_username,),
            ).fetchone()
        if not reviewer_row or str(reviewer_row['status'] or '').lower() != 'active':
            raise HTTPException(status_code=400, detail='指定的实施结果复核人不存在或未启用')
        if TENANT_ISOLATION_ENABLED and tenant_id and str(reviewer_row['tenant_id'] or '') != tenant_id:
            raise HTTPException(status_code=400, detail='实施结果复核人必须属于工单所在租户')
    return normalized


def _load_actor_change_groups(conn, user_id: str) -> set[str]:
    if not user_id:
        return set()
    row = conn.execute('SELECT change_groups_json FROM users WHERE id = ?', (user_id,)).fetchone()
    if not row:
        return set()
    return _parse_change_groups(row['change_groups_json'])


def validate_variable_value(
    key: str,
    val: str,
    var_type: str = "text",
    platform: str = "",
    variables: dict = None
) -> Optional[str]:
    import re
    import ipaddress
    val_str = str(val).strip()
    if not val_str:
        return None

    is_acl_number = ("acl" in key.lower()) and ("name" not in key.lower())
    is_as_number = any(w == "as" for w in re.split(r'[^a-zA-Z0-9]', key.lower()))

    if is_as_number:
        if '.' in val_str:
            parts = val_str.split('.')
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                high, low = int(parts[0]), int(parts[1])
                if not (0 <= high <= 65535 and 0 <= low <= 65535 and not (high == 0 and low == 0)):
                    return f"AS 号 '{key}' ASdot 格式非法 (高低 16 位均需在 0-65535 之间且不能同时为 0)"
            else:
                return f"AS 号 '{key}' ASdot 格式非法 (应为 X.Y 格式)"
        else:
            if not re.match(r'^\d+$', val_str):
                return f"AS 号 '{key}' 必须是正整数或 ASdot 点分十进制格式"
            num = int(val_str)
            if num < 1 or num > 4294967295:
                return f"AS 号 '{key}' 必须在 1 到 4294967295 之间"
    
    number_indicators = ["vlan", "port", "key_size", "modulus", "process"]
    if (var_type == "number" or is_acl_number or any(k in key.lower() for k in number_indicators)) and not is_as_number:
        if not re.match(r'^\d+$', val_str):
            return f"变量 '{key}' 的值必须是正整数"
        num = int(val_str)
        if "vlan" in key.lower() and (num < 1 or num > 4094):
            return f"VLAN ID '{key}' 必须在 1 到 4094 之间"
        if "port" in key.lower() and (num < 1 or num > 65535):
            return f"端口号 '{key}' 必须在 1 到 65535 之间"
        if "process" in key.lower() and (num < 1 or num > 65535):
            return f"OSPF 进程 ID '{key}' 必须在 1 到 65535 之间"

        if is_acl_number:
            platform_lower = platform.lower() if platform else ""
            if "cisco" in platform_lower:
                if not ((1 <= num <= 199) or (1300 <= num <= 1999) or (2000 <= num <= 2699)):
                    return f"思科 ACL 编号 '{key}' 必须在 1-199 或 1300-1999 或 2000-2699 之间"
            elif "huawei" in platform_lower or "h3c" in platform_lower:
                if not (2000 <= num <= 6999):
                    return f"华为/H3C ACL 编号 '{key}' 必须在 2000-6999 之间"
            elif "arista" in platform_lower:
                if not (1 <= num <= 199):
                    return f"Arista ACL 编号 '{key}' 必须在 1-199 之间"

    if any(k in key.lower() for k in ["wildcard", "inverse_mask"]):
        octets = val_str.split('.')
        if len(octets) != 4 or not all(o.isdigit() and 0 <= int(o) <= 255 for o in octets):
            return f"反掩码 '{key}' 必须是合法的点分十进制格式 (如 0.0.0.255)"
    
    if ("mask" in key.lower()) and ("wildcard" not in key.lower()):
        try:
            if val_str.isdigit():
                platform_lower = platform.lower() if platform else ""
                if "cisco" in platform_lower:
                    return f"思科子网掩码 '{key}' 必须是点分十进制格式 (如 255.255.255.0)，不支持输入数字位数 '{val_str}'"
                num = int(val_str)
                if num < 0 or num > 32:
                    return f"子网掩码 '{key}' 必须在 0 到 32 之间"
            else:
                octets = val_str.split('.')
                if len(octets) != 4 or not all(o.isdigit() and 0 <= int(o) <= 255 for o in octets):
                    return f"子网掩码 '{key}' 必须是合法的点分十进制格式 (如 255.255.255.0)"
                ipaddress.IPv4Network(f"0.0.0.0/{val_str}")
        except ValueError:
            return f"子网掩码 '{key}' 格式非法"

    if "area" in key.lower():
        platform_lower = platform.lower() if platform else ""
        if "juniper" in platform_lower:
            if not re.match(r'^\d+\.\d+\.\d+\.\d+$', val_str):
                return f"Juniper OSPF 区域 ID '{key}' 必须为点分十进制 IP 格式 (如 0.0.0.0)"
            try:
                ipaddress.ip_address(val_str)
            except ValueError:
                return f"OSPF 区域 ID '{key}' 格式非法"
        else:
            if val_str.isdigit():
                num = int(val_str)
                if num < 0 or num > 4294967295:
                    return f"OSPF 区域 ID '{key}' 必须在 0 到 4294967295 之间"
            else:
                try:
                    ipaddress.ip_address(val_str)
                except ValueError:
                    return f"OSPF 区域 ID '{key}' 必须是正整数或点分十进制 IP 格式 (如 0.0.0.0)"

    if any(k in key.lower() for k in ["address_family", "bgp_family", "addr_family"]) or (key.lower() == "family"):
        valid_keywords = ["ipv4", "ipv6", "inet", "inet6", "vpnv4", "vpnv6", "l2vpn", "evpn", "unicast", "multicast"]
        words = re.split(r'[^a-zA-Z0-9-]', val_str.lower())
        if not all(any(vk in w for vk in valid_keywords) for w in words if w):
            return f"地址簇 '{key}' 格式非法 (支持如 ipv4 unicast, ipv4-family, inet unicast 等)"

    if any(k in key.lower() for k in ["interface", "intf"]) and not any(k in key.lower() for k in ["type", "description"]):
        platform_lower = platform.lower() if platform else ""
        if "cisco" in platform_lower:
            if not re.match(r'^(gi|gigabitethernet|fa|fastethernet|te|tengigabitethernet|tw|twentyfivegige|fo|fortygige|hu|hundredgige|vl|vlan|lo|loopback|se|serial|pos|port-channel)\s*\d+([\/\d\.]+)*$', val_str, re.IGNORECASE):
                return f"思科接口名称 '{key}' 格式不正确 (如 GigabitEthernet0/1, Vlan10, GigabitEthernet0/1.10)"
        elif "huawei" in platform_lower or "h3c" in platform_lower:
            if re.match(r'^(ge|gigabitethernet|xge|xgigabitethernet)', val_str, re.IGNORECASE):
                if not re.match(r'^(ge|gigabitethernet|xge|xgigabitethernet)\s*\d+/\d+/\d+(\.\d+)?$', val_str, re.IGNORECASE):
                    return f"华为/H3C物理接口名称 '{key}' 必须是三级槽位格式 (如 GigabitEthernet0/0/1 或 GE0/0/1)"
            else:
                if not re.match(r'^(eth-trunk|vlanif|loopback|lo|null)\s*\d+(\.\d+)?$', val_str, re.IGNORECASE):
                    return f"华为/H3C逻辑接口名称 '{key}' 格式不正确 (如 Vlanif10, Eth-Trunk1)"
        elif "juniper" in platform_lower:
            if not (re.match(r'^(ge|xe|et|ae|fe|lo|vlan|irb)\-\d+\/\d+\/\d+(\.\d+)?$', val_str, re.IGNORECASE) or 
                    re.match(r'^lo0\.\d+$', val_str, re.IGNORECASE) or 
                    re.match(r'^ae\d+(\.\d+)?$', val_str, re.IGNORECASE) or 
                    re.match(r'^vlan\.\d+$', val_str, re.IGNORECASE) or 
                    re.match(r'^irb\.\d+$', val_str, re.IGNORECASE)):
                return f"Juniper接口名称 '{key}' 格式不正确 (如 ge-0/0/0, ge-0/0/0.10, ae1.10, lo0.0)"
        elif "arista" in platform_lower:
            if not re.match(r'^(eth|ethernet|vlan|loopback|port-channel|lo)\s*\d+([\/\d\.]+)*$', val_str, re.IGNORECASE):
                return f"Arista接口名称 '{key}' 格式不正确 (如 Ethernet1, Vlan10, Ethernet1.10)"

    ip_indicators = ["ip", "host", "server", "neighbor", "gateway", "network", "src", "dst", "router"]
    is_ip_field = any(ind in key.lower() for ind in ip_indicators) and not any(k in key.lower() for k in ["mask", "wildcard"])
    
    if is_ip_field:
        strict_ip = any(ind in key.lower() for ind in ["ip", "network", "src", "dst", "addr", "router_id"]) and not any(k in key.lower() for k in ["name", "domain"])
        
        if strict_ip:
            if not re.match(r'^[\d\./]+$', val_str):
                return f"IP地址/网段 '{key}' 格式非法"
        else:
            if not re.match(r'^[\w\.\-\/]+$', val_str):
                return f"IP地址/主机名 '{key}' 的格式不正确"
        
        if re.match(r'^[\d\./]+$', val_str):
            platform_lower = platform.lower() if platform else ""
            has_independent_mask = False
            if variables:
                has_independent_mask = any("mask" in k.lower() or "wildcard" in k.lower() for k in variables.keys())
            
            is_traditional_platform = any(p in platform_lower for p in ["cisco", "huawei", "h3c"])
            is_host_ip_only = any(k in key.lower() for k in ["router_id", "peer_ip", "neighbor_ip", "server_ip", "gateway"])
            
            if is_host_ip_only or (is_traditional_platform and has_independent_mask):
                if '/' in val_str:
                    return f"变量 '{key}' 必须是纯 IP 地址，不能带 '/' 掩码位数"
                try:
                    ipaddress.ip_address(val_str)
                except ValueError:
                    return f"IP地址 '{key}' 格式非法"
            else:
                try:
                    if '/' in val_str:
                        ipaddress.ip_network(val_str, strict=False)
                    else:
                        ipaddress.ip_address(val_str)
                except ValueError:
                    return f"IP地址/网段 '{key}' 格式非法"

    return None


def get_pre_post_checks(platform: str, category: str, name: str) -> tuple[list[str], list[str]]:
    plat = platform.lower()
    cat = (category or "").lower()
    nm = (name or "").lower()

    if "cisco" in plat:
        if cat == "routing" or "bgp" in nm or "ospf" in nm or "route" in nm:
            if "bgp" in nm:
                return (
                    ["show ip bgp summary", "show ip route"],
                    ["show ip bgp summary", "show ip route"]
                )
            elif "ospf" in nm:
                return (
                    ["show ip ospf neighbor", "show ip route"],
                    ["show ip ospf neighbor", "show ip route"]
                )
            else:
                return (
                    ["show ip route"],
                    ["show ip route"]
                )
        elif cat == "security" or "acl" in nm or "ssh" in nm or "aaa" in nm or "tacacs" in nm:
            if "acl" in nm:
                return (
                    ["show ip access-lists"],
                    ["show ip access-lists"]
                )
            elif "ssh" in nm or "aaa" in nm or "tacacs" in nm:
                return (
                    ["show run | include ssh", "show run | include aaa"],
                    ["show ssh", "show run | include ssh"]
                )
            else:
                return (
                    ["show running-config"],
                    ["show running-config"]
                )
        elif cat == "switching" or "vlan" in nm:
            return (
                ["show vlan brief", "show interfaces status"],
                ["show vlan brief", "show interfaces status"]
            )
        elif cat == "management" or "snmp" in nm or "ntp" in nm:
            if "snmp" in nm:
                return (
                    ["show snmp"],
                    ["show snmp"]
                )
            else:
                return (
                    ["show ntp status"],
                    ["show ntp status"]
                )
        return (
            ["show version", "show running-config | include interface"],
            ["show running-config | include interface", "show interfaces status"]
        )

    elif "huawei" in plat or "h3c" in plat:
        if cat == "routing" or "bgp" in nm or "ospf" in nm or "route" in nm:
            if "bgp" in nm:
                return (
                    ["display bgp peer", "display ip routing-table"],
                    ["display bgp peer", "display ip routing-table"]
                )
            elif "ospf" in nm:
                return (
                    ["display ospf peer brief", "display ip routing-table"],
                    ["display ospf peer brief", "display ip routing-table"]
                )
            else:
                return (
                    ["display ip routing-table"],
                    ["display ip routing-table"]
                )
        elif cat == "security" or "acl" in nm or "ssh" in nm or "aaa" in nm or "tacacs" in nm:
            if "acl" in nm:
                return (
                    ["display acl all"],
                    ["display acl all"]
                )
            elif "ssh" in nm or "aaa" in nm or "tacacs" in nm:
                return (
                    ["display local-user"],
                    ["display local-user"]
                )
            else:
                return (
                    ["display current-configuration"],
                    ["display current-configuration"]
                )
        elif cat == "switching" or "vlan" in nm:
            return (
                ["display vlan"],
                ["display vlan"]
            )
        elif cat == "management" or "snmp" in nm or "ntp" in nm:
            if "snmp" in nm:
                return (
                    ["display snmp-agent sys-info"],
                    ["display snmp-agent sys-info"]
                )
            else:
                return (
                    ["display ntp-service status"],
                    ["display ntp-service status"]
                )
        return (
            ["display version", "display current-configuration | include interface"],
            ["display current-configuration | include interface", "display interface"]
        )

    elif "juniper" in plat:
        if cat == "routing" or "bgp" in nm or "ospf" in nm or "route" in nm:
            if "bgp" in nm:
                return (
                    ["show bgp summary", "show route"],
                    ["show bgp summary", "show route"]
                )
            elif "ospf" in nm:
                return (
                    ["show ospf neighbor", "show route"],
                    ["show ospf neighbor", "show route"]
                )
            else:
                return (
                    ["show route"],
                    ["show route"]
                )
        elif cat == "security" or "acl" in nm or "ssh" in nm or "aaa" in nm:
            if "acl" in nm or "filter" in nm:
                return (
                    ["show firewall"],
                    ["show firewall"]
                )
            else:
                return (
                    ["show system services"],
                    ["show system services"]
                )
        elif cat == "switching" or "vlan" in nm:
            return (
                ["show vlans"],
                ["show vlans"]
            )
        elif cat == "management" or "snmp" in nm or "ntp" in nm:
            if "snmp" in nm:
                return (
                    ["show snmp mib"],
                    ["show snmp mib"]
                )
            else:
                return (
                    ["show ntp status"],
                    ["show ntp status"]
                )
        return (
            ["show version", "show configuration | display set | grep interface"],
            ["show configuration | display set | grep interface", "show interfaces"]
        )

    elif "arista" in plat:
        if cat == "routing" or "bgp" in nm or "ospf" in nm or "route" in nm:
            if "bgp" in nm:
                return (
                    ["show ip bgp summary", "show ip route"],
                    ["show ip bgp summary", "show ip route"]
                )
            elif "ospf" in nm:
                return (
                    ["show ip ospf neighbor", "show ip route"],
                    ["show ip ospf neighbor", "show ip route"]
                )
            else:
                return (
                    ["show ip route"],
                    ["show ip route"]
                )
        elif cat == "security" or "acl" in nm or "ssh" in nm:
            return (
                ["show ip access-lists"],
                ["show ip access-lists"]
            )
        elif cat == "switching" or "vlan" in nm:
            return (
                ["show vlan"],
                ["show vlan"]
            )
        elif cat == "management" or "snmp" in nm or "ntp" in nm:
            if "snmp" in nm:
                return (
                    ["show snmp"],
                    ["show snmp"]
                )
            else:
                return (
                    ["show ntp status"],
                    ["show ntp status"]
                )
        return (
            ["show version", "show running-config | include interface"],
            ["show running-config | include interface", "show interfaces status"]
        )

    return ([], [])


def validate_template_parameters(
    scenario_id: str,
    source_kind: str,
    platform: str,
    variables: dict,
    target_devices: list = []
) -> list[str]:
    import re
    errors = []

    from api.playbooks import _all_scenarios

    scenario = None
    if source_kind == 'config_template':
        conn = get_db_connection()
        try:
            row = conn.execute(
                'SELECT id, name, category, vendor, content, rollback FROM templates WHERE id = ?',
                (scenario_id,),
            ).fetchone()
            if not row:
                return [f"配置模板 '{scenario_id}' 不存在"]
            template = dict(row)
        finally:
            conn.close()

        content = template.get('content') or ''
        rollback = template.get('rollback') or ''

        var_matches = re.findall(r'\{\{\s*([\w.-]+)(?:\s*\|\s*[^}]+)?\s*\}\}', content)
        unique_vars = sorted(list(set(var_matches)))

        variable_defs = []
        for k in unique_vars:
            k_lower = k.lower()
            is_req = not any(x in k_lower for x in ["group_name", "family", "description"])
            if k_lower == 'family' or 'address_family' in k_lower or 'bgp_family' in k_lower or 'addr_family' in k_lower:
                variable_defs.append({
                    'key': k, 'label': k, 'type': 'select', 'required': is_req,
                    'options': [
                        'ipv4 unicast', 'ipv4 multicast', 'ipv6 unicast', 'ipv6 multicast',
                        'vpnv4 unicast', 'vpnv6 unicast', 'l2vpn evpn',
                        'ipv4-family unicast', 'ipv4-family vpnv4', 'ipv6-family unicast',
                        'inet unicast', 'inet6 unicast',
                    ],
                })
            else:
                variable_defs.append({'key': k, 'label': k, 'type': 'text', 'required': is_req})

        pre_check, post_check = get_pre_post_checks(platform, template.get('category') or '', template.get('name') or '')
        phases = {
            'pre_check': pre_check,
            'execute': [content] if content.strip() else [],
            'post_check': post_check,
            'rollback': [rollback] if rollback.strip() else [],
        }
    else:
        scenario = next((item for item in _all_scenarios() if item.get('id') == scenario_id), None)
        if not scenario:
            return [f"变更场景 '{scenario_id}' 不存在"]

        variable_defs = scenario.get('variables') or []
        phases = (scenario.get('platform_phases') or {}).get(platform)
        if not phases:
            return [f"所选场景不支持平台 '{platform}'"]

    for variable in variable_defs:
        key = str(variable.get('key') or '').strip()
        if not key:
            continue
        val = str(variables.get(key, '')).strip()
        if variable.get('required') and not val:
            errors.append(f"必填变量 '{variable.get('label') or key}' 不能为空")

    for key, val in variables.items():
        var_def = next((v for v in variable_defs if v.get('key') == key), None)
        var_type = var_def.get('type', 'text') if var_def else 'text'
        err = validate_variable_value(key, val, var_type, platform, variables)
        if err:
            errors.append(err)

    from jinja2 import StrictUndefined, TemplateSyntaxError, UndefinedError
    from jinja2.sandbox import SandboxedEnvironment
    env = SandboxedEnvironment(undefined=StrictUndefined)

    strict_vars = {k: str(v) for k, v in variables.items()}

    try:
        for phase_name, templates_list in phases.items():
            for tmpl_str in templates_list:
                tmpl = env.from_string(tmpl_str)
                tmpl.render(**strict_vars)
    except TemplateSyntaxError as e:
        errors.append(f"模板语法错误: {e.message} (行 {e.lineno})")
    except UndefinedError as e:
        errors.append(f"缺失或未定义变量: {e.message}")
    except Exception as e:
        errors.append(f"模板渲染出错: {str(e)}")

    if target_devices:
        for device in target_devices:
            dev_hostname = device.get('hostname', 'Unknown')
            dev_platform = device.get('platform', '')
            if dev_platform and platform:
                dev_vendor = dev_platform.split('_')[0] if '_' in dev_platform else dev_platform
                tmpl_vendor = platform.split('_')[0] if '_' in platform else platform
                if dev_vendor.lower() != tmpl_vendor.lower():
                    errors.append(f"设备 '{dev_hostname}' 的平台是 '{dev_platform}'，与模板的适配平台 '{platform}' 不兼容")

    return errors


def _build_command_template_snapshot(template_payload: dict, target_devices: list = None, status: str = 'draft') -> dict:
    if target_devices is None:
        target_devices = []
    if not isinstance(template_payload, dict):
        raise HTTPException(status_code=400, detail='command_template must be an object')

    scenario_id = str(template_payload.get('scenario_id') or '').strip()
    if not scenario_id:
        raise HTTPException(status_code=400, detail='command_template.scenario_id is required')
    source_kind = str(template_payload.get('source_kind') or 'scenario').strip().lower()

    from api.playbooks import _all_scenarios, _render_phase_commands

    scenario = None
    if source_kind == 'config_template':
        conn = get_db_connection()
        try:
            row = conn.execute(
                'SELECT id, name, category, vendor, content, rollback FROM templates WHERE id = ?',
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
        pre_check, post_check = get_pre_post_checks(platform, template.get('category') or '', template.get('name') or '')
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
                    'rollback': [str(template.get('rollback') or '')] if str(template.get('rollback') or '').strip() else [],
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

    if status != 'draft':
        errors = validate_template_parameters(scenario_id, source_kind, platform, variables, target_devices)
        if errors:
            raise HTTPException(status_code=400, detail="、".join(errors))

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
        if is_template_required() and status in _TEMPLATE_REQUIRED_STATUSES and order_type == 'config_change':
            raise HTTPException(status_code=400, detail='非草稿状态的配置变更工单必须携带有效的场景化模板')
        normalized['command_template'] = {}
        guard = scan_change_commands(
            normalized.get('commands') or [],
            str(normalized.get('platform') or ''),
        )
        if guard['blocked']:
            raise HTTPException(status_code=400, detail={
                'message': '命令守卫阻断了不可逆高危命令',
                'guard': guard,
            })
        normalized['command_guard'] = guard
        if _RISK_RANK[guard['max_risk']] > _RISK_RANK.get(str(normalized.get('risk_level') or 'low'), 0):
            normalized['risk_level'] = guard['max_risk']
        return normalized

    target_devices = normalized.get('target_devices') or []
    snapshot = _build_command_template_snapshot(template_payload, target_devices, status)
    guard = scan_change_commands(snapshot['preview']['execute'], snapshot.get('platform') or '')
    if guard['blocked']:
        raise HTTPException(status_code=400, detail={
            'message': '命令守卫阻断了不可逆高危命令',
            'guard': guard,
        })
    snapshot['command_guard'] = guard
    normalized['command_template'] = snapshot
    normalized['commands'] = snapshot['preview']['execute']
    normalized['rollback_plan'] = '\n'.join(snapshot['preview']['rollback']) if snapshot['preview']['rollback'] else str(normalized.get('rollback_plan') or '')
    normalized['command_guard'] = guard
    if _RISK_RANK[guard['max_risk']] > _RISK_RANK.get(str(normalized.get('risk_level') or 'low'), 0):
        normalized['risk_level'] = guard['max_risk']
    return normalized
