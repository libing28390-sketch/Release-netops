from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

import database as database_module
from core.rbac import authorize_resource, enforce_resource_scope, require_role
from core.tenant_policy import TENANT_ISOLATION_ENABLED, tenant_scope_for_user
from database import get_db_connection
from services.audit_service import log_audit_event
from services.change_order_service import (
    control_sheet_business_confirmer,
    control_sheet_implementer,
    archive_change_order_approval_authorization,
    get_change_order,
    normalize_control_sheet_identity,
    update_change_order,
)
from api.change_orders.helpers import (
    APPROVAL_SNAPSHOT_VERSION,
    approval_snapshot_hash,
    assert_explicit_execution_profile,
)

router = APIRouter()


class ChangeOrderAssignmentRequest(BaseModel):
    action: Literal['assign', 'claim', 'transfer']
    implementer_id: str | None = None
    reason: str | None = Field(default=None, max_length=2000)


class ChangeOrderVerificationRequest(BaseModel):
    kind: Literal['technical', 'business']
    result: Literal['passed', 'failed']
    summary: str = Field(min_length=1, max_length=4000)
    evidence: Any = None


def _lock_order(conn, order_id: str) -> None:
    if database_module._USE_PG:
        conn.execute('SELECT id FROM change_orders WHERE id = ? FOR UPDATE', (order_id,))


def _active_actor(conn, user: dict) -> dict:
    actor_id = str(user.get('user_id') or user.get('id') or '').strip()
    if not actor_id:
        raise HTTPException(status_code=403, detail='当前账号缺少稳定身份，不能操作工单')
    row = conn.execute(
        'SELECT id, username, role, role_profile, status, tenant_id, scope_mode FROM users WHERE id = ?',
        (actor_id,),
    ).fetchone()
    if not row or str(row['status'] or '').lower() != 'active':
        raise HTTPException(status_code=403, detail='当前账号已停用或不可用')
    return dict(row)


def _assert_order_scope(
    conn,
    order: dict,
    user: dict,
    actor_id: str,
    *,
    action: str = 'update',
    allow_explicit_business_confirmer: bool = False,
    require_resource_permission: bool = True,
) -> None:
    tenant_id = str(order.get('tenant_id') or '').strip()
    if TENANT_ISOLATION_ENABLED and (
        not tenant_id or tenant_scope_for_user(user) != tenant_id
    ):
        raise HTTPException(status_code=404, detail='Change order not found')
    is_requester = bool(str(order.get('requester_id') or '') == actor_id)
    configured = control_sheet_business_confirmer(order.get('control_sheet'))
    confirmer_id = str(configured.get('id') or '').strip()
    if not confirmer_id and str(configured.get('username') or '').strip():
        confirmer_row = conn.execute(
            'SELECT id FROM users WHERE username = ?',
            (str(configured.get('username') or '').strip(),),
        ).fetchone()
        confirmer_id = str(confirmer_row['id'] or '') if confirmer_row else ''
    is_explicit_confirmer = bool(confirmer_id and confirmer_id == actor_id)
    if (
        user.get('role_profile') == 'Change Requester'
        and not is_requester
        and not (action == 'view' and is_explicit_confirmer)
    ):
        raise HTTPException(status_code=404, detail='Change order not found')
    if allow_explicit_business_confirmer and action == 'view' and is_explicit_confirmer:
        return
    if require_resource_permission:
        enforce_resource_scope(user, 'change_order', action, tenant_id=tenant_id or None)


def _validate_implementer_target(conn, order: dict, implementer_id: str) -> dict:
    row = conn.execute(
        'SELECT id, username, role, role_profile, status, tenant_id, scope_mode FROM users WHERE id = ?',
        (implementer_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail='指定的实施人账号不存在')
    implementer = dict(row)
    if str(implementer.get('status') or '').lower() != 'active':
        raise HTTPException(status_code=400, detail='停用账号不能被指派或接手为实施人')
    if implementer_id in {
        str(order.get('assigned_final_approver_id') or ''),
        str(order.get('final_approver_id') or ''),
        str(order.get('approver_id') or ''),
    }:
        raise HTTPException(status_code=400, detail='终审人不能被指派为该工单的实施人')
    tenant_id = str(order.get('tenant_id') or '').strip()
    if TENANT_ISOLATION_ENABLED and (
        not tenant_id or str(implementer.get('tenant_id') or '') != tenant_id
    ):
        raise HTTPException(status_code=400, detail='实施人必须属于工单所在租户')
    assert_explicit_execution_profile(implementer, 'command')
    if not authorize_resource(implementer, 'command', 'execute', tenant_id=tenant_id or None):
        raise HTTPException(status_code=400, detail='该账号没有目标租户的设备执行权限')
    return implementer


@router.post('/change-orders/{order_id}/assignment')
def api_change_order_assignment(
    order_id: str,
    body: ChangeOrderAssignmentRequest = Body(...),
    user=require_role('Viewer'),
):
    conn = get_db_connection()
    try:
        _lock_order(conn, order_id)
        order = get_change_order(conn, order_id)
        if not order:
            raise HTTPException(status_code=404, detail='Change order not found')
        actor = _active_actor(conn, user)
        actor_id = str(actor.get('id') or '')
        _assert_order_scope(conn, order, actor, actor_id)

        old_control_sheet = normalize_control_sheet_identity(order.get('control_sheet'))
        old_implementer = control_sheet_implementer(old_control_sheet)
        old_id = str(old_implementer.get('id') or '').strip()
        requester_id = str(order.get('requester_id') or '')
        is_requester = bool(requester_id and actor_id == requester_id)
        is_current_implementer = bool(old_id and actor_id == old_id)
        is_admin = actor.get('role') == 'Administrator'
        action = body.action

        if action == 'claim':
            if old_id:
                raise HTTPException(status_code=409, detail='工单已指定实施人，请使用转派操作')
            implementer_id = actor_id
        else:
            implementer_id = str(body.implementer_id or '').strip()
            if not implementer_id:
                raise HTTPException(status_code=400, detail='implementer_id is required')

        if action == 'assign' and not (is_requester or is_admin):
            raise HTTPException(status_code=403, detail='只有申请人或管理员可以指派实施人')
        if action == 'transfer' and not (is_requester or is_current_implementer or is_admin):
            raise HTTPException(status_code=403, detail='只有申请人、当前实施人或管理员可以转派')
        if action == 'transfer' and not str(body.reason or '').strip():
            raise HTTPException(status_code=400, detail='转派时必须填写原因')
        if action == 'claim' and not (is_requester or is_admin or actor.get('role') in {'Operator', 'Administrator'}):
            raise HTTPException(status_code=403, detail='当前账号不能接手该工单')

        if str(order.get('status') or '') in {'completed', 'rolled_back', 'cancelled', 'implementation_review', 'implementation_result_review'}:
            raise HTTPException(status_code=409, detail='终态工单不能更改实施人')
        status = str(order.get('status') or 'draft')
        implementer = _validate_implementer_target(conn, order, implementer_id)
        if old_id == implementer_id:
            raise HTTPException(status_code=409, detail='该账号已是工单实施人')

        result_detail = dict(order.get('result_detail') or {})
        if status == 'implementing' and str(result_detail.get('execution_started_at') or '').strip():
            raise HTTPException(status_code=409, detail='设备操作已经开始，不能在执行中转派')

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        reason = str(body.reason or '').strip()
        approved_lifecycle = {'approved', 'implementing', 'failed'}
        approval_invalidated = status in approved_lifecycle or bool(result_detail.get('approval_snapshot_hash'))
        new_status = status
        updates: dict[str, Any] = {}

        if approval_invalidated or status == 'final_review':
            new_status = 'initial_review'
            archive_change_order_approval_authorization(
                result_detail,
                actor=actor,
                reason=reason or f'{action}:{old_id}->{implementer_id}',
                at=now,
            )
            if any(str(order.get(key) or '').strip() for key in ('actual_start', 'actual_end', 'result_summary')):
                cycles = result_detail.get('implementation_cycles')
                if not isinstance(cycles, list):
                    cycles = []
                cycles.append({
                    'status': status,
                    'actual_start': order.get('actual_start') or '',
                    'actual_end': order.get('actual_end') or '',
                    'result_summary': order.get('result_summary') or '',
                    'archived_at': now,
                })
                result_detail['implementation_cycles'] = cycles
            updates.update({
                'status': new_status,
                'initial_reviewer_id': '',
                'initial_reviewer_username': '',
                'assigned_final_approver_id': '',
                'assigned_final_approver_username': '',
                'final_approver_id': '',
                'final_approver_username': '',
                'approver_id': '',
                'approver_username': '',
                'actual_start': '',
                'actual_end': '',
                'result_summary': '',
            })

        events = result_detail.get('assignment_events')
        if not isinstance(events, list):
            events = []
        events.append({
            'action': action,
            'actor_id': actor_id,
            'actor_username': str(actor.get('username') or ''),
            'from_implementer_id': old_id,
            'from_username': str(old_implementer.get('username') or ''),
            'to_implementer_id': implementer_id,
            'to_username': str(implementer.get('username') or ''),
            'implementer_id': implementer_id,
            'implementer_username': str(implementer.get('username') or ''),
            'reason': reason,
            'created_at': now,
        })
        result_detail['assignment_events'] = events
        new_control_sheet = dict(old_control_sheet)
        new_control_sheet['implementer'] = {
            'id': implementer_id,
            'username': str(implementer.get('username') or ''),
        }
        updates['control_sheet'] = new_control_sheet
        updates['result_detail'] = result_detail

        updated = update_change_order(conn, order_id, updates, commit=False)
        log_audit_event(
            event_type='change_order.assignment',
            category='change_order',
            severity='medium',
            status='open',
            summary=f"工单 {order.get('order_number') or order_id} 实施人已更新",
            actor_id=actor_id,
            actor_username=actor.get('username'),
            actor_role=actor.get('role'),
            target_type='change_order',
            target_id=order_id,
            target_name=order.get('order_number'),
            details=events[-1],
            conn=conn,
        )
        conn.commit()
        return {'success': True, 'data': updated}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _configured_business_verifier(conn, order: dict) -> dict:
    configured = control_sheet_business_confirmer(order.get('control_sheet'))
    user_id = str(configured.get('id') or '').strip()
    username = str(configured.get('username') or '').strip()
    if user_id:
        row = conn.execute(
            'SELECT id, username, status FROM users WHERE id = ?', (user_id,),
        ).fetchone()
    elif username:
        row = conn.execute(
            'SELECT id, username, status FROM users WHERE username = ?', (username,),
        ).fetchone()
    else:
        requester_id = str(order.get('requester_id') or '').strip()
        if requester_id:
            row = conn.execute(
                'SELECT id, username, status FROM users WHERE id = ?', (requester_id,),
            ).fetchone()
        else:
            requester_name = str(order.get('requester_username') or '').strip()
            row = conn.execute(
                'SELECT id, username, status FROM users WHERE username = ?', (requester_name,),
            ).fetchone() if requester_name else None
    if not row or str(row['status'] or '').lower() != 'active':
        raise HTTPException(status_code=409, detail='业务确认人账号不可用')
    return dict(row)


@router.post('/change-orders/{order_id}/verification')
def api_change_order_verification(
    order_id: str,
    body: ChangeOrderVerificationRequest = Body(...),
    user=require_role('Viewer'),
):
    conn = get_db_connection()
    try:
        _lock_order(conn, order_id)
        order = get_change_order(conn, order_id)
        if not order:
            raise HTTPException(status_code=404, detail='Change order not found')
        actor = _active_actor(conn, user)
        actor_id = str(actor.get('id') or '')
        if str(order.get('status') or '') not in {'implementing', 'failed', 'rollback_in_progress', 'rolled_back'}:
            raise HTTPException(status_code=409, detail='工单尚未实施或已处于终态，不能记录验证')
        detail = dict(order.get('result_detail') or {})
        if int(detail.get('approval_snapshot_version') or 0) != APPROVAL_SNAPSHOT_VERSION:
            raise HTTPException(status_code=409, detail='工单缺少有效审批快照，不能记录验证')
        snapshot = approval_snapshot_hash(order)
        if str(detail.get('approval_snapshot_hash') or '') != snapshot:
            raise HTTPException(status_code=409, detail='工单审批快照已变化，不能记录验证')

        implementation = control_sheet_implementer(order.get('control_sheet'))
        implementer_id = str(implementation.get('id') or '')
        if body.kind == 'technical':
            _assert_order_scope(
                conn,
                order,
                actor,
                actor_id,
                action='view',
                require_resource_permission=False,
            )
            if actor_id == implementer_id:
                raise HTTPException(status_code=403, detail='技术验证人必须独立于实施人')
            enforce_resource_scope(user, 'pam', 'intervene', tenant_id=str(order.get('tenant_id') or '') or None)
        else:
            verifier = _configured_business_verifier(conn, order)
            if actor_id != str(verifier.get('id') or ''):
                raise HTTPException(status_code=403, detail='只有申请人或工单指定的业务确认人可以提交业务验证')
            explicit_confirmer = control_sheet_business_confirmer(order.get('control_sheet'))
            is_explicit_confirmer = bool(
                str(explicit_confirmer.get('id') or '').strip()
                or str(explicit_confirmer.get('username') or '').strip()
            )
            if is_explicit_confirmer:
                _assert_order_scope(
                    conn,
                    order,
                    actor,
                    actor_id,
                    action='view',
                    allow_explicit_business_confirmer=True,
                    require_resource_permission=False,
                )
            else:
                _assert_order_scope(conn, order, actor, actor_id, action='update')

        records = detail.get('verification_records')
        if not isinstance(records, list):
            records = []
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        summary = body.summary.strip()
        if not summary:
            raise HTTPException(status_code=400, detail='summary must not be blank')
        record = {
            'kind': body.kind,
            'result': body.result,
            'actor_id': actor_id,
            'actor_username': str(actor.get('username') or ''),
            'summary': summary,
            'evidence': body.evidence,
            'created_at': now,
            'approval_snapshot_hash': snapshot,
        }
        records.append(record)
        detail['verification_records'] = records
        updated = update_change_order(conn, order_id, {'result_detail': detail}, commit=False)
        log_audit_event(
            event_type=f'change_order.{body.kind}_verification',
            category='change_order',
            severity='high' if body.result == 'failed' else 'medium',
            status=body.result,
            summary=f"工单 {order.get('order_number') or order_id} {body.kind} 验证 {body.result}",
            actor_id=actor_id,
            actor_username=actor.get('username'),
            actor_role=actor.get('role'),
            target_type='change_order',
            target_id=order_id,
            target_name=order.get('order_number'),
            details={
                'kind': body.kind,
                'result': body.result,
                'created_at': now,
                'approval_snapshot_hash': snapshot,
            },
            conn=conn,
        )
        conn.commit()
        return {'success': True, 'data': updated}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
