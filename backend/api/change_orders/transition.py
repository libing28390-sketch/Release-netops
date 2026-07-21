import logging
from fastapi import APIRouter, HTTPException, Body
from database import get_db_connection
from core.rbac import require_role
from services.audit_service import log_audit_event
from services.change_order_service import get_change_order, update_change_order
from api.change_orders.helpers import (
    ALLOWED_STATUSES,
    ALLOWED_TRANSITIONS,
    STATUS_ZH,
    is_template_required,
    is_control_sheet_enabled,
    _utc_now_iso,
    _load_actor_change_groups,
    _resolve_assignment_user,
    _validate_assignment_rules,
    _validate_template_completeness,
    _validate_control_sheet_completeness,
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
        allowed_next = ALLOWED_TRANSITIONS.get(current_status, set())
        if new_status not in allowed_next:
            raise HTTPException(
                status_code=400,
                detail=f'Invalid transition: {current_status} -> {new_status}',
            )

        requester_username = existing.get('requester_username', '')
        actor_username = user.get('username', '')
        actor_groups = _load_actor_change_groups(conn, str(user.get('user_id') or ''))
        is_admin = user.get('role') == 'Administrator'

        requester_actions = (
            new_status == 'cancelled'
            or (current_status == 'draft' and new_status == 'initial_review')
            or (current_status == 'rejected' and new_status == 'draft')
        )
        if requester_actions and requester_username != actor_username and not is_admin:
            raise HTTPException(status_code=403, detail='Only the requester or an administrator can perform this transition')

        if new_status == 'initial_review' and current_status == 'draft' and not existing.get('assigned_initial_reviewer_id'):
            raise HTTPException(status_code=400, detail='An initial reviewer is required before submission')

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
            if requester_username != actor_username and user.get('role') != 'Administrator':
                raise HTTPException(status_code=403, detail='只有工单申请人（实施人）才能操作实施阶段')
        
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

        # Validate assignment rules on transition
        full_payload = {**existing, **updates}
        _validate_assignment_rules(existing.get('requester_username'), full_payload)
        
        # Enforcement checks on transition
        if new_status == 'initial_review':
            if is_template_required():
                _validate_template_completeness(full_payload)
            if is_control_sheet_enabled():
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
            details={'from_status': existing['status'], 'to_status': new_status, 'extra': body},
            conn=conn,
        )
        conn.commit()
        return {'success': True, 'data': order, 'message': f"工单状态已更新为 {STATUS_ZH.get(new_status, new_status)}"}
    finally:
        conn.close()
