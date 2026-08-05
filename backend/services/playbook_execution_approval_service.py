"""Execution-time approval gates for controlled Playbooks."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from core.rbac import authorize_resource
from database import get_db_connection
from api.playbooks.scenarios import extract_approval_steps


class PlaybookApprovalError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _actor_key(user: dict[str, Any]) -> str:
    return str(user.get('id') or user.get('username') or '')


def _lock_suffix() -> str:
    import database as database_module
    return ' FOR UPDATE' if database_module._USE_PG else ''


def _load_execution(conn, execution_id: str, *, lock: bool = False) -> dict[str, Any]:
    row = conn.execute(
        f'SELECT * FROM playbook_executions WHERE id = ?{_lock_suffix() if lock else ""}',
        (execution_id,),
    ).fetchone()
    if not row:
        raise PlaybookApprovalError('EXECUTION_NOT_FOUND', 'Playbook execution not found', status_code=404)
    return dict(row)


def _assert_scope(conn, execution_id: str, user: dict[str, Any], *, action: str) -> dict[str, Any]:
    execution = _load_execution(conn, execution_id)
    if user.get('role') == 'Administrator':
        return execution
    tenant_id = str(execution.get('tenant_id') or '')
    user_tenant_id = str(user.get('tenant_id') or '')
    if not tenant_id or tenant_id != user_tenant_id or not authorize_resource(user, 'playbook', action, tenant_id=tenant_id):
        raise PlaybookApprovalError('RESOURCE_SCOPE_DENIED', 'Execution is outside the current Playbook scope', status_code=403)
    return execution


def create_execution_approvals(conn, execution_id: str, phases: object, user: dict[str, Any]) -> list[dict[str, Any]]:
    """Insert stable approval rows in the same transaction as the execution."""
    steps = extract_approval_steps(phases)
    if not steps:
        return []
    now = _now()
    requested_by = _actor_key(user)
    created: list[dict[str, Any]] = []
    for step in steps:
        approval = {
            'id': str(uuid.uuid4()),
            'execution_id': execution_id,
            'tenant_id': str(user.get('tenant_id') or '') or None,
            'step_path': step['step_path'],
            'title': step['title'],
            'message': step['message'],
            'required_role': step['required_role'],
            'status': 'PENDING',
            'requested_by': requested_by,
            'requested_by_username': str(user.get('username') or '')[:128],
            'requested_by_role': str(user.get('role') or '')[:64],
            'created_at': now,
            'updated_at': now,
        }
        conn.execute(
            """INSERT INTO playbook_execution_approvals
               (id, execution_id, tenant_id, step_path, title, message, required_role,
                status, requested_by, requested_by_username, requested_by_role,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                approval['id'], approval['execution_id'], approval['tenant_id'], approval['step_path'],
                approval['title'], approval['message'], approval['required_role'], approval['status'],
                approval['requested_by'], approval['requested_by_username'], approval['requested_by_role'],
                approval['created_at'], approval['updated_at'],
            ),
        )
        created.append(approval)
    return created


def list_execution_approvals(execution_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        _assert_scope(conn, execution_id, user, action='view')
        rows = conn.execute(
            """SELECT id, execution_id, tenant_id, step_path, title, message,
                      required_role, status, requested_by, requested_by_username,
                      requested_by_role, decided_by, decided_by_username,
                      decision_reason, created_at, decided_at, updated_at
               FROM playbook_execution_approvals WHERE execution_id = ?
               ORDER BY created_at, step_path""",
            (execution_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def decide_execution_approval(execution_id: str, approval_id: str, decision: str, user: dict[str, Any], reason: str = '') -> dict[str, Any]:
    decision = str(decision or '').strip().upper()
    if decision not in {'APPROVED', 'REJECTED'}:
        raise PlaybookApprovalError('INVALID_APPROVAL_DECISION', 'Approval decision must be APPROVED or REJECTED')
    reason = str(reason or '').strip()
    if '\x00' in reason or len(reason) > 1_000:
        raise PlaybookApprovalError('INVALID_APPROVAL_REASON', 'Approval reason is invalid or too long')

    conn = get_db_connection()
    try:
        _assert_scope(conn, execution_id, user, action='approve')
        execution = _load_execution(conn, execution_id, lock=True)
        approval_row = conn.execute(
            f"SELECT * FROM playbook_execution_approvals WHERE id = ? AND execution_id = ?{_lock_suffix()}",
            (approval_id, execution_id),
        ).fetchone()
        if not approval_row:
            raise PlaybookApprovalError('APPROVAL_NOT_FOUND', 'Approval request not found', status_code=404)
        approval = dict(approval_row)
        if approval.get('status') != 'PENDING':
            raise PlaybookApprovalError('APPROVAL_ALREADY_DECIDED', 'Approval request has already been decided', status_code=409)
        if decision == 'APPROVED' and approval.get('requested_by') == _actor_key(user):
            raise PlaybookApprovalError('SELF_APPROVAL_FORBIDDEN', 'The execution requester cannot approve their own Playbook', status_code=403)
        required_role = str(approval.get('required_role') or 'Administrator')
        if required_role and user.get('role') != required_role and user.get('role') != 'Administrator':
            raise PlaybookApprovalError('APPROVAL_ROLE_REQUIRED', 'Approver does not satisfy the required role', status_code=403)

        now = _now()
        conn.execute(
            """UPDATE playbook_execution_approvals
               SET status = ?, decided_by = ?, decided_by_username = ?,
                   decision_reason = ?, decided_at = ?, updated_at = ?
               WHERE id = ? AND execution_id = ? AND status = 'PENDING'""",
            (decision, _actor_key(user), str(user.get('username') or '')[:128], reason, now, now, approval_id, execution_id),
        )
        should_start = False
        if decision == 'REJECTED':
            conn.execute(
                "UPDATE playbook_executions SET status = 'approval_rejected', updated_at = ? WHERE id = ? AND status = 'awaiting_approval'",
                (now, execution_id),
            )
        else:
            pending = conn.execute(
                "SELECT COUNT(*) FROM playbook_execution_approvals WHERE execution_id = ? AND status = 'PENDING'",
                (execution_id,),
            ).fetchone()[0]
            rejected = conn.execute(
                "SELECT COUNT(*) FROM playbook_execution_approvals WHERE execution_id = ? AND status = 'REJECTED'",
                (execution_id,),
            ).fetchone()[0]
            if int(pending or 0) == 0 and int(rejected or 0) == 0:
                updated = conn.execute(
                    "UPDATE playbook_executions SET status = 'pending', updated_at = ? WHERE id = ? AND status = 'awaiting_approval'",
                    (now, execution_id),
                )
                should_start = getattr(updated, 'rowcount', 1) == 1
        conn.commit()
        updated_approval = conn.execute("SELECT * FROM playbook_execution_approvals WHERE id = ?", (approval_id,)).fetchone()
        execution = _load_execution(conn, execution_id)
        return {
            'approval': dict(updated_approval) if updated_approval else {'id': approval_id, 'status': decision},
            'execution': execution,
            'should_start': should_start,
        }
    except PlaybookApprovalError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execution_start_payload(execution: dict[str, Any]) -> dict[str, Any]:
    """Decode the committed execution row for the async engine resume path."""
    try:
        device_ids = json.loads(execution.get('device_ids') or '[]')
        variables = json.loads(execution.get('variables') or '{}')
        phases = json.loads(execution.get('phases_json') or '{}')
    except (TypeError, json.JSONDecodeError) as exc:
        raise PlaybookApprovalError('EXECUTION_PAYLOAD_INVALID', 'Stored Playbook execution payload is invalid') from exc
    if not isinstance(device_ids, list) or not isinstance(variables, dict) or not isinstance(phases, dict):
        raise PlaybookApprovalError('EXECUTION_PAYLOAD_INVALID', 'Stored Playbook execution payload is invalid')
    return {
        'execution_id': execution.get('id'),
        'device_ids': [str(value) for value in device_ids],
        'variables': variables,
        'phases': phases,
        'dry_run': bool(execution.get('dry_run')),
        'concurrency': int(execution.get('concurrency') or 1),
        'platform': str(execution.get('platform') or 'cisco_ios'),
        'commit_confirmed_ttl': int(execution.get('commit_confirmed_ttl') or 0),
    }
