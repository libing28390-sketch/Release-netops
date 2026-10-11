import json
import uuid
from datetime import datetime, timezone

from database import get_db_connection
from services.audit_service import log_audit_event
from core.rbac import RESOURCE_ACTION_CATALOG, enforce_resource_scope, is_global_administrator


VALID_SCOPE_TYPES = {'global', 'tenant', 'site', 'device_group'}
VALID_ACTIONS = {
    'read', 'create', 'update', 'delete', 'execute', 'approve', 'approve_low_risk',
    'export', 'allocate', 'reserve', 'release', '*',
    *{action for actions in RESOURCE_ACTION_CATALOG.values() for action in actions},
}


def _get_authorized_target_user(conn, user_id: str, actor: dict | None, action: str) -> dict | None:
    row = conn.execute(
        'SELECT id, username, tenant_id FROM users WHERE id = ?', (user_id,),
    ).fetchone()
    if not row:
        return None
    target = dict(row)
    if actor is None:
        return target
    tenant_id = str(actor.get('tenant_id') or '').strip()
    target_tenant_id = str(target.get('tenant_id') or '').strip()
    global_admin = is_global_administrator(actor)
    if not global_admin and (not tenant_id or tenant_id != target_tenant_id):
        raise PermissionError('User is outside the administrator tenant')
    enforce_resource_scope(
        actor, 'user', action,
        tenant_id=None if global_admin else tenant_id,
    )
    return target


def list_user_scopes(user_id: str, *, actor: dict | None = None) -> list[dict]:
    conn = get_db_connection()
    try:
        if actor is not None and not _get_authorized_target_user(conn, user_id, actor, 'manage_scopes'):
            raise ValueError('User not found')
        rows = conn.execute(
            "SELECT * FROM user_resource_scopes WHERE user_id = ? ORDER BY resource_type, scope_type, scope_id",
            (user_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item['actions'] = json.loads(item.get('actions_json') or '[]')
            except Exception:
                item['actions'] = []
            result.append(item)
        return result
    finally:
        conn.close()


def replace_user_scopes(
    user_id: str,
    scopes: list[dict],
    *,
    changed_by: str,
    actor: dict | None = None,
) -> list[dict]:
    conn = get_db_connection()
    try:
        user = _get_authorized_target_user(conn, user_id, actor, 'manage_scopes')
        if not user:
            raise ValueError('User not found')
        before = list_user_scopes(user_id)
        normalized = []
        for scope in scopes:
            scope_type = str(scope.get('scope_type') or '').strip()
            resource_type = str(scope.get('resource_type') or '').strip()
            scope_id = str(scope.get('scope_id') or '').strip()
            actions = sorted({str(action) for action in scope.get('actions', [])})
            if scope_type not in VALID_SCOPE_TYPES:
                raise ValueError(f'Unsupported scope_type: {scope_type}')
            if not resource_type:
                raise ValueError('resource_type is required')
            if resource_type != '*' and resource_type not in RESOURCE_ACTION_CATALOG:
                raise ValueError(f'Unsupported resource_type: {resource_type}')
            if scope_type != 'global' and not scope_id:
                raise ValueError(f'scope_id is required for {scope_type}')
            if scope_type == 'global' and scope_id:
                raise ValueError('scope_id must be empty for global scopes')
            if actor is not None and not is_global_administrator(actor):
                target_tenant_id = str(user.get('tenant_id') or '').strip()
                if scope_type == 'global':
                    raise ValueError('Tenant administrators cannot assign global scopes')
                if scope_type == 'tenant' and scope_id != target_tenant_id:
                    raise ValueError('Tenant administrators can only assign the user tenant scope')
                if scope_type == 'site':
                    site = conn.execute(
                        'SELECT 1 FROM sites WHERE id = ? AND tenant_id = ?',
                        (scope_id, target_tenant_id),
                    ).fetchone()
                    if not site:
                        raise ValueError('Site scope must belong to the user tenant')
                if scope_type == 'device_group':
                    group = conn.execute(
                        'SELECT 1 FROM devices WHERE device_group_id = ? AND tenant_id = ? LIMIT 1',
                        (scope_id, target_tenant_id),
                    ).fetchone()
                    if not group:
                        raise ValueError('Device-group scope must belong to the user tenant')
            supported_actions = (
                VALID_ACTIONS if resource_type == '*'
                else VALID_ACTIONS.intersection(RESOURCE_ACTION_CATALOG[resource_type] | {'*'})
            )
            invalid_actions = set(actions) - supported_actions
            if invalid_actions:
                raise ValueError(
                    f"Unsupported actions for {resource_type}: {', '.join(sorted(invalid_actions))}"
                )
            normalized.append({
                'id': f"scope-{uuid.uuid4().hex[:12]}", 'resource_type': resource_type,
                'scope_type': scope_type, 'scope_id': scope_id, 'actions': actions,
            })
        conn.execute("DELETE FROM user_resource_scopes WHERE user_id = ?", (user_id,))
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        for scope in normalized:
            conn.execute(
                """INSERT INTO user_resource_scopes
                   (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (scope['id'], user_id, scope['resource_type'], scope['scope_type'],
                 scope['scope_id'], json.dumps(scope['actions']), now),
            )
        conn.execute(
            "UPDATE users SET scope_mode = 'restricted' WHERE id = ?",
            (user_id,),
        )
        after = [{**scope, 'user_id': user_id} for scope in normalized]
        log_audit_event(
            event_type='rbac.scope.replace', category='security', severity='warning', status='success',
            summary=f"Updated resource scopes for {user['username']}", actor_username=changed_by,
            actor_role='Administrator', target_type='user', target_id=user_id,
            target_name=user['username'], before={'scopes': before}, after={'scopes': after}, conn=conn,
        )
        conn.commit()
        return after
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
