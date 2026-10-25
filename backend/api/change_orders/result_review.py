"""Post-implementation decisions, separate from pre-execution approval."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.rbac import require_role
from core.tenant_policy import TENANT_ISOLATION_ENABLED, tenant_scope_for_user
from database import get_db_connection
from services.audit_service import log_audit_event
from services.change_order_service import get_change_order, update_change_order
from api.change_orders.helpers import (
    APPROVAL_SNAPSHOT_VERSION, approval_snapshot_hash, assert_order_verification_complete,
    resolve_active_order_implementer, resolve_active_order_result_reviewer,
    resolve_active_order_initial_reviewer, _utc_now_iso,
)

router = APIRouter()


class ResultReviewRequest(BaseModel):
    action: Literal['submit', 'pass', 'fail', 'accept', 'reject']
    summary: str = Field(min_length=1, max_length=4000)


@router.post('/change-orders/{order_id}/result-review')
def api_result_review(order_id: str, body: ResultReviewRequest, user=require_role('Viewer')):
    conn = get_db_connection()
    try:
        conn.execute('SELECT id FROM change_orders WHERE id = ? FOR UPDATE', (order_id,))
        order = get_change_order(conn, order_id)
        if not order:
            raise HTTPException(status_code=404, detail='Change order not found')
        actor_id = str(user.get('user_id') or user.get('id') or '')
        actor = conn.execute('SELECT id, username, status, tenant_id FROM users WHERE id = ?', (actor_id,)).fetchone()
        if not actor or str(actor['status']).lower() != 'active':
            raise HTTPException(status_code=403, detail='当前账号不可用')
        if TENANT_ISOLATION_ENABLED and (
            tenant_scope_for_user(user) != str(order.get('tenant_id') or '')
            or str(actor['tenant_id'] or '') != str(order.get('tenant_id') or '')
        ):
            raise HTTPException(status_code=404, detail='Change order not found')
        implementer = resolve_active_order_implementer(conn, order)
        reviewer = resolve_active_order_result_reviewer(conn, order, required=True)
        if str(reviewer['id']) == str(implementer['id']):
            raise HTTPException(status_code=409, detail='复核人不能与实施人相同')
        status = str(order.get('status') or '')
        action = body.action
        summary = body.summary.strip()
        if not summary:
            raise HTTPException(status_code=400, detail='请填写实施结果或复核意见')
        if action == 'submit':
            expected = str(implementer['id'])
            allowed = {'implementing', 'failed'}
            target = 'implementation_review'
        elif action in {'pass', 'fail'}:
            expected = str(reviewer['id'])
            allowed = {'implementation_review'}
            target = 'completed' if action == 'pass' else 'implementation_result_review'
            if action == 'fail':
                resolve_active_order_initial_reviewer(conn, order)
        else:
            expected = str(resolve_active_order_initial_reviewer(conn, order)['id'])
            allowed = {'implementation_result_review'}
            target = 'completed' if action == 'accept' else 'failed'
        if actor_id != expected or (action != 'submit' and actor_id == str(implementer['id'])):
            raise HTTPException(status_code=403, detail='只有该阶段指定的处理人可以提交结果')
        if status not in allowed:
            raise HTTPException(status_code=409, detail='工单状态已变化，请刷新后重试')
        detail = dict(order.get('result_detail') or {})
        snapshot = approval_snapshot_hash(order)
        if detail.get('approval_snapshot_version') != APPROVAL_SNAPSHOT_VERSION or detail.get('approval_snapshot_hash') != snapshot:
            raise HTTPException(status_code=409, detail='审批内容已变化，不能提交实施复核')
        if action in {'submit', 'pass', 'accept'}:
            assert_order_verification_complete(order)
        if action != 'submit' and detail.get('result_review_snapshot_hash') != snapshot:
            raise HTTPException(status_code=409, detail='实施复核内容已变化，请重新提交')
        now = _utc_now_iso()
        records = list(detail.get('result_reviews') or [])
        records.append({'action': action, 'summary': summary, 'actor_id': actor_id,
                        'actor_username': str(actor['username']), 'created_at': now,
                        'from_status': status, 'to_status': target, 'approval_snapshot_hash': snapshot})
        detail.update(result_reviews=records, result_review_summary=summary, result_review_snapshot_hash=snapshot)
        updates = {'status': target, 'result_detail': detail, 'result_summary': summary}
        if target == 'completed':
            updates['actual_end'] = now
        result = update_change_order(conn, order_id, updates, commit=False)
        log_audit_event(event_type=f'change_order.result_review_{action}', category='change_order', severity='medium',
                        status='closed' if target == 'completed' else 'open', summary=f"变更工单 {order['order_number']} 实施复核：{action}",
                        actor_id=actor_id, actor_username=str(actor['username']), actor_role=user.get('role'),
                        target_type='change_order', target_id=order_id, target_name=order['order_number'],
                        details={'from_status': status, 'to_status': target, 'summary': summary}, conn=conn)
        conn.commit()
        return {'success': True, 'data': result}
    finally:
        conn.close()
