import json
import uuid
from datetime import datetime, timezone

from database import get_db_connection
from services.audit_service import log_audit_event
from core.rbac import RESOURCE_ACTION_CATALOG


VALID_SCOPE_TYPES = {'global', 'tenant', 'site', 'device_group'}
VALID_ACTIONS = {
    'read', 'create', 'update', 'delete', 'execute', 'approve', 'approve_low_risk',
    'export', 'allocate', 'reserve', 'release', '*',
    *{action for actions in RESOURCE_ACTION_CATALOG.values() for action in actions},
}


def list_user_scopes(user_id: str) -> list[dict]:
    conn = get_db_connection()
    try:
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


def replace_user_scopes(user_id: str, scopes: list[dict], *, changed_by: str) -> list[dict]:
    conn = get_db_connection()
    try:
        user = conn.execute("SELECT id, username FROM users WHERE id = ?", (user_id,)).fetchone()
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
            if scope_type != 'global' and not scope_id:
                raise ValueError(f'scope_id is required for {scope_type}')
            invalid_actions = set(actions) - VALID_ACTIONS
            if invalid_actions:
                raise ValueError(f"Unsupported actions: {', '.join(sorted(invalid_actions))}")
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
