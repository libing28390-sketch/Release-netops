import logging
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import FileResponse
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
)
from api.change_orders.schemas import (
    TemplateValidateRequest,
    ChangeOrderCreate,
    ChangeOrderUpdate,
)
from api.change_orders.helpers import (
    is_template_required,
    is_control_sheet_enabled,
    validate_template_parameters,
    _build_command_template_snapshot,
    _normalize_assignment_payload,
    _normalize_command_template_payload,
    _validate_assignment_rules,
    _validate_template_completeness,
    _validate_control_sheet_completeness,
)

logger = logging.getLogger(__name__)
router = APIRouter()

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

@router.post('/change-orders/validate')
def api_validate_template(body: TemplateValidateRequest, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        errors = validate_template_parameters(
            scenario_id=body.scenario_id,
            source_kind=body.source_kind,
            platform=body.platform,
            variables=body.variables,
            target_devices=body.target_devices
        )

        preview = {}
        if not errors:
            try:
                snapshot = _build_command_template_snapshot({
                    'scenario_id': body.scenario_id,
                    'source_kind': body.source_kind,
                    'platform': body.platform,
                    'variables': body.variables
                }, body.target_devices, 'draft')
                preview = snapshot.get('preview') or {}
            except Exception as e:
                errors.append(f"生成预览失败: {str(e)}")

        return {
            'success': True,
            'valid': len(errors) == 0,
            'errors': errors,
            'preview': preview
        }
    finally:
        conn.close()


@router.post('/change-orders')
def api_create_change_order(body: ChangeOrderCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        payload = _normalize_assignment_payload(conn, body.model_dump())
        payload = _normalize_command_template_payload(payload)
        
        _validate_assignment_rules(user.get('username'), payload)
        
        if is_template_required():
            _validate_template_completeness(payload)

        if payload.get('status') != 'draft' and not payload.get('assigned_initial_reviewer_id'):
            raise HTTPException(status_code=400, detail='提交初审时必须指定初审人')
        
        if is_control_sheet_enabled() and payload.get('status') == 'initial_review':
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
            
        full_payload = {**existing, **updates}
        _validate_assignment_rules(existing.get('requester_username'), full_payload)
        
        if is_template_required():
            _validate_template_completeness(full_payload)
        
        if is_control_sheet_enabled() and full_payload.get('status') == 'initial_review' and existing.get('status') != 'initial_review':
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
