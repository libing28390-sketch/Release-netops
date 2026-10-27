import logging
import uuid
from fastapi import APIRouter, HTTPException, Body
from database import get_db_connection
from core.rbac import enforce_resource_scope, require_role
from core.tenant_policy import TENANT_ISOLATION_ENABLED, tenant_scope_for_user
from services.audit_service import log_audit_event
from services.change_order_service import get_change_order, update_change_order
from api.change_orders.helpers import (
    APPROVAL_SNAPSHOT_VERSION,
    ALLOWED_STATUSES,
    ALLOWED_TRANSITIONS,
    STATUS_ZH,
    assert_change_order_window_open,
    assert_change_order_window_approvable,
    assert_explicit_execution_profile,
    assert_order_verification_complete,
    is_template_required,
    is_control_sheet_enabled,
    _utc_now_iso,
    _load_actor_change_groups,
    _resolve_assignment_user,
    _validate_assignment_rules,
    _validate_template_completeness,
    _validate_control_sheet_completeness,
    validate_emergency_change_details,
    approval_snapshot_hash,
    resolve_active_order_implementer,
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post('/change-orders/{order_id}/transition')
def api_transition_change_order(order_id: str, body: dict = Body(...), user=require_role("Operator")):
    new_status = body.get('status', '')
    if new_status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f'Invalid status: {new_status}')

    conn = get_db_connection()
    try:
        # Serialize state transitions on PostgreSQL so two reviewers cannot
        # approve/reject the same state concurrently.
        import database as database_module
        if database_module._USE_PG:
            conn.execute('SELECT id FROM change_orders WHERE id = ? FOR UPDATE', (order_id,))

        existing = get_change_order(conn, order_id)
        if not existing:
            raise HTTPException(status_code=404, detail='Change order not found')

        current_status = existing.get('status', 'draft')
        from services.change_order_service import control_sheet_result_reviewer
        if current_status in {'implementation_review', 'implementation_result_review'} or new_status in {'implementation_review', 'implementation_result_review'}:
            raise HTTPException(status_code=409, detail='请通过实施复核操作提交结果')
        if new_status == 'completed' and control_sheet_result_reviewer(existing.get('control_sheet')):
            raise HTTPException(status_code=409, detail='已指定复核人，请先提交实施复核')
        allowed_next = ALLOWED_TRANSITIONS.get(current_status, set())
        if new_status not in allowed_next:
            raise HTTPException(
                status_code=400,
                detail=f'Invalid transition: {current_status} -> {new_status}',
            )

        requester_username = existing.get('requester_username', '')
        requester_id = str(existing.get('requester_id') or '')
        actor_username = user.get('username', '')
        actor_id = str(user.get('user_id') or '')
        actor_groups = _load_actor_change_groups(conn, str(user.get('user_id') or ''))
        is_admin = user.get('role') == 'Administrator'
        tenant_id = str(existing.get('tenant_id') or '').strip()
        if TENANT_ISOLATION_ENABLED:
            actor_tenant_id = tenant_scope_for_user(user)
            if not tenant_id or not actor_tenant_id or tenant_id != actor_tenant_id:
                raise HTTPException(status_code=404, detail='Change order not found')
        permission_action = (
            'approve' if new_status == 'approved' or (current_status == 'final_review' and new_status in {'rejected', 'initial_review'})
            else 'create_change' if current_status == 'draft' and new_status == 'initial_review'
            else 'request_approval' if new_status in {'initial_review', 'final_review', 'rejected'}
            else 'intervene' if new_status in {'implementing', 'completed', 'failed', 'rollback_in_progress', 'rolled_back'}
            else 'create_change'
        )
        enforce_resource_scope(user, 'pam', permission_action, tenant_id=tenant_id or None)
        is_requester = bool(requester_id and actor_id and requester_id == actor_id)

        requester_actions = (
            new_status == 'cancelled'
            or (current_status == 'draft' and new_status == 'initial_review')
            or (current_status == 'rejected' and new_status == 'draft')
        )
        if requester_actions and not is_requester and not is_admin:
            raise HTTPException(status_code=403, detail='Only the requester or an administrator can perform this transition')

        if new_status == 'initial_review' and current_status == 'draft' and not existing.get('assigned_initial_reviewer_id'):
            raise HTTPException(status_code=400, detail='An initial reviewer is required before submission')

        # Applicant cannot review/approve own ticket.
        if requester_id and requester_id == actor_id:
            if new_status in {'final_review', 'approved', 'rejected'} or (new_status == 'initial_review' and current_status != 'draft'):
                raise HTTPException(status_code=403, detail='申请人不能审核或审批自己的变更工单')
        # Final approval requires administrator role.
        if new_status == 'approved' and user.get('role') != 'Administrator':
            raise HTTPException(status_code=403, detail='只有管理员角色的用户才能执行最终审批')
        # Final-stage reject also requires administrator role.
        if current_status == 'final_review' and new_status in {'rejected', 'initial_review'} and user.get('role') != 'Administrator':
            raise HTTPException(status_code=403, detail='只有管理员角色的用户才能在终审阶段驳回工单')
        if current_status == 'initial_review' and new_status in {'final_review', 'rejected'}:
            if user.get('role') != 'Administrator':
                raise HTTPException(status_code=403, detail='只有管理员角色的用户才能处理初审')
            assigned_initial_reviewer_id = str(existing.get('assigned_initial_reviewer_id') or '')
            if assigned_initial_reviewer_id and assigned_initial_reviewer_id != str(user.get('user_id') or ''):
                raise HTTPException(status_code=403, detail='只有被指定的初审人才能处理此工单的初审')
            if not assigned_initial_reviewer_id and 'initial_reviewer' not in actor_groups and not is_admin:
                raise HTTPException(status_code=403, detail='只有初审组成员或管理员才能处理此工单的初审')
        if current_status == 'final_review' and new_status in {'approved', 'rejected', 'initial_review'}:
            assigned_final_approver_id = str(existing.get('assigned_final_approver_id') or '')
            if assigned_final_approver_id and assigned_final_approver_id != str(user.get('user_id') or ''):
                raise HTTPException(status_code=403, detail='只有被指定的终审人才能处理此工单的终审')
            if not assigned_final_approver_id and 'final_approver' not in actor_groups and not is_admin:
                raise HTTPException(status_code=403, detail='只有终审组成员或管理员才能处理此工单的终审')
        
        # Implementation stages: Only requester can operate
        implementation_statuses = {'implementing', 'completed', 'failed', 'rollback_in_progress', 'rolled_back'}
        if new_status in implementation_statuses or current_status in implementation_statuses:
            implementer = resolve_active_order_implementer(conn, existing)
            if str(implementer.get('id') or '') != actor_id:
                raise HTTPException(status_code=403, detail='只有工单指定的实施人可以操作实施阶段')
        
        if new_status == 'final_review' and not existing.get('assigned_final_approver_id'):
            # If moving to final review, check if it was assigned during the transition
            assigned_final = body.get('assigned_final_approver_id') or existing.get('assigned_final_approver_id')
            if not assigned_final:
                raise HTTPException(status_code=400, detail='提交终审时必须指定终审人')

        updates = {'status': new_status}
        if new_status == 'draft' and current_status in {'initial_review', 'final_review', 'rejected'}:
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
            assert_change_order_window_approvable(existing)
            implementer = resolve_active_order_implementer(conn, existing)
            if str(implementer.get('id') or '') == actor_id:
                raise HTTPException(status_code=403, detail='终审人不能作为该工单的实施人')
            updates['approver_id'] = user.get('user_id', '')
            updates['approver_username'] = user.get('username', '')
            updates['final_approver_id'] = user.get('user_id', '')
            updates['final_approver_username'] = user.get('username', '')
            updates['result_detail'] = {
                **(existing.get('result_detail') or {}),
                'approved_at': _utc_now_iso(),
                'approval_comment': str(body.get('approval_comment') or ''),
                'approval_snapshot_hash': approval_snapshot_hash(existing),
                'approval_snapshot_version': APPROVAL_SNAPSHOT_VERSION,
            }
        if new_status == 'implementing':
            result_detail = dict(existing.get('result_detail') or {})
            approved_hash = str(result_detail.get('approval_snapshot_hash') or '')
            current_hash = approval_snapshot_hash(existing)
            if not approved_hash:
                raise HTTPException(status_code=409, detail='该工单缺少审批快照，必须退回并重新审批后才能实施')
            if int(result_detail.get('approval_snapshot_version') or 0) != APPROVAL_SNAPSHOT_VERSION:
                raise HTTPException(status_code=409, detail='工单使用旧版审批快照，必须重新审批后才能实施')
            if approved_hash != current_hash:
                raise HTTPException(status_code=409, detail='审批后的设备、参数、命令或 Playbook 快照已变化，必须重新审批')

            implementer = resolve_active_order_implementer(conn, existing)
            if str(implementer.get('id') or '') != actor_id:
                raise HTTPException(status_code=403, detail='只有工单指定的实施人可以开始实施')
            approver_id = str(existing.get('final_approver_id') or existing.get('approver_id') or '')
            if not approver_id or approver_id == actor_id:
                raise HTTPException(status_code=403, detail='终审人不能实施，且工单必须保留独立终审身份')
            assert_explicit_execution_profile(user, 'command')
            assert_change_order_window_open(existing)

            # Check the individual device scope before the state can enter the
            # implementation phase, including when the implementer is an admin.
            # A tenant-only check here would incorrectly reject an operator
            # whose explicit command grant is narrower (site/device-group),
            # even though the per-device check below can validate that grant.
            from api.automation import _resolve_change_order_target_ids
            from core.rbac import enforce_resource_scope as enforce_scope
            device_ids = _resolve_change_order_target_ids(conn, existing.get('target_devices') or [])
            placeholders = ','.join('?' for _ in device_ids)
            devices = conn.execute(
                f'SELECT id, tenant_id, site_id, site, device_group_id FROM devices WHERE id IN ({placeholders})',
                tuple(device_ids),
            ).fetchall()
            if len(devices) != len(device_ids):
                raise HTTPException(status_code=409, detail='工单目标设备已从资产库删除')
            for device in devices:
                device_scope = {
                    'tenant_id': str(device['tenant_id'] or ''),
                    'site_id': device['site_id'] or device['site'] or None,
                    'device_group_id': device['device_group_id'] or None,
                }
                enforce_scope(user, 'command', 'execute', **device_scope)

            # Production execution is PostgreSQL-only and always requires MFA.
            # The repository's isolated legacy tests intentionally replace
            # PostgreSQL with SQLite; preserving that compatibility harness
            # does not weaken the actual PostgreSQL runtime gate.
            mfa_verified = False
            if database_module._USE_PG:
                mfa_code = str(body.get('mfa_code') or '').strip()
                if not mfa_code:
                    raise HTTPException(status_code=400, detail='配置变更实施前必须输入 MFA 动态验证码')
                actor = conn.execute(
                    'SELECT mfa_enabled, mfa_secret, status, username FROM users WHERE id = ?',
                    (actor_id,),
                ).fetchone()
                if not actor or str(actor['status'] or '').lower() != 'active' or not actor['mfa_enabled'] or not actor['mfa_secret']:
                    raise HTTPException(status_code=403, detail='实施人尚未启用 MFA，不能执行配置变更')
                from api.users import verify_totp
                if not verify_totp(actor['mfa_secret'], mfa_code, window=1):
                    raise HTTPException(status_code=403, detail='MFA 动态验证码无效或已过期')
                mfa_verified = True

            verified_at = _utc_now_iso()
            updates['actual_start'] = verified_at
            result_detail = {
                **(existing.get('result_detail') or {}),
                'execution_token_id': f"exec-{uuid.uuid4().hex}",
                'execution_token_consumed_at': verified_at,
                'executing_snapshot_hash': current_hash,
            }
            if mfa_verified:
                result_detail.update({
                    'mfa_verified_at': verified_at,
                    'mfa_verified_by_id': actor_id,
                    'mfa_verified_by': str(actor['username'] or user.get('username') or ''),
                })
            updates['result_detail'] = result_detail
        if new_status in {'completed', 'rolled_back'}:
            assert_order_verification_complete(existing, rollback=new_status == 'rolled_back')
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

        if new_status in {'failed', 'rollback_in_progress', 'rolled_back'}:
            result_detail = dict(updates.get('result_detail') or existing.get('result_detail') or {})
            lifecycle_events = result_detail.get('lifecycle_events')
            if not isinstance(lifecycle_events, list):
                lifecycle_events = []
            lifecycle_events.append({
                'event_id': f"lifecycle-{uuid.uuid4().hex}",
                'status': new_status,
                'summary': str(body.get('result_summary') or body.get('rollback_reason') or '').strip(),
                'actor': {'id': actor_id, 'username': actor_username},
                'occurred_at': _utc_now_iso(),
            })
            result_detail['lifecycle_events'] = lifecycle_events
            updates['result_detail'] = result_detail

        # Validate assignment rules on transition
        full_payload = {**existing, **updates}
        _validate_assignment_rules(existing.get('requester_username'), full_payload)
        
        # Enforcement checks on transition
        if new_status == 'initial_review':
            if str(existing.get('order_type') or '') == 'emergency':
                emergency = validate_emergency_change_details(conn, {**existing, **updates})
                updates.update({
                    'emergency_reason': emergency['emergency_reason'],
                    'emergency_review_owner_id': emergency['emergency_review_owner_id'],
                    'emergency_review_due_at': emergency['emergency_review_due_at'],
                    'emergency_review_status': 'pending',
                    'emergency_reviewed_by_id': '',
                    'emergency_reviewed_by': '',
                    'emergency_reviewed_at': None,
                    'emergency_review_note': '',
                })
                full_payload = {**existing, **updates}
            if is_template_required():
                _validate_template_completeness(full_payload)
            _validate_control_sheet_completeness(conn, order_id, full_payload, 'initial_review')
        if new_status == 'implementing':
            if is_control_sheet_enabled():
                _validate_control_sheet_completeness(conn, order_id, full_payload, 'implementing')

        order = update_change_order(conn, order_id, updates, commit=False)
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
            details={
                'from_status': existing['status'],
                'to_status': new_status,
                'extra': {key: value for key, value in body.items() if key not in {'mfa_code', 'password', 'token'}},
                'mfa_verified': new_status == 'implementing' and database_module._USE_PG,
            },
            conn=conn,
        )
        conn.commit()
        return {'success': True, 'data': order, 'message': f"工单状态已更新为 {STATUS_ZH.get(new_status, new_status)}"}
    finally:
        conn.close()
