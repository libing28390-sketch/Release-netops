"""
change_order_service.py — Change Order / Ticket Management Service
Ticket number format: BG + YYYYMMDD + 4-digit sequential number
Example: BG202603280001
"""

import json
import uuid
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d')


def generate_order_number(conn) -> str:
    """Generate the next change order number for today: BG + YYYYMMDD + 0001~9999."""
    today = _today_str()
    prefix = f"BG{today}"
    row = conn.execute(
        "SELECT order_number FROM change_orders WHERE order_number LIKE ? ORDER BY order_number DESC LIMIT 1",
        (f"{prefix}%",),
    ).fetchone()
    if row:
        last_seq = int(row['order_number'][-4:])
        next_seq = last_seq + 1
    else:
        next_seq = 1
    return f"{prefix}{next_seq:04d}"


def create_change_order(conn, *, title: str, description: str = '',
                        order_type: str = 'config_change', priority: str = 'medium',
                        status: str = 'draft',
                        requester_id: str = '', requester_username: str = '',
                        assigned_initial_reviewer_id: str = '',
                        assigned_initial_reviewer_username: str = '',
                        assigned_final_approver_id: str = '',
                        assigned_final_approver_username: str = '',
                        command_template: dict | None = None,
                        target_devices: list | None = None,
                        commands: list | None = None,
                        rollback_plan: str = '',
                        risk_level: str = 'low',
                        scheduled_start: str = '',
                        scheduled_end: str = '',
                        authorization_exempt: bool = False) -> dict:
    order_id = str(uuid.uuid4())
    order_number = generate_order_number(conn)
    now = _utc_now_iso()
    conn.execute(
        '''
        INSERT INTO change_orders (
            id, order_number, title, description, order_type, priority, status,
            requester_id, requester_username,
            assigned_initial_reviewer_id, assigned_initial_reviewer_username,
            assigned_final_approver_id, assigned_final_approver_username,
            command_template_json,
            target_devices_json, commands_json, rollback_plan, risk_level,
            scheduled_start, scheduled_end,
            authorization_exempt,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            order_id, order_number, title, description, order_type, priority, status,
            requester_id, requester_username,
            assigned_initial_reviewer_id, assigned_initial_reviewer_username,
            assigned_final_approver_id, assigned_final_approver_username,
            json.dumps(command_template or {}, ensure_ascii=False),
            json.dumps(target_devices or [], ensure_ascii=False),
            json.dumps(commands or [], ensure_ascii=False),
            rollback_plan, risk_level,
            scheduled_start, scheduled_end,
            1 if authorization_exempt else 0,
            now, now,
        ),
    )
    conn.commit()
    return get_change_order(conn, order_id)



def update_change_order(conn, order_id: str, updates: dict) -> dict | None:
    existing = get_change_order(conn, order_id)
    if not existing:
        return None

    allowed_fields = {
        'title', 'description', 'order_type', 'priority', 'status',
        'approver_id', 'approver_username',
        'initial_reviewer_id', 'initial_reviewer_username',
        'final_approver_id', 'final_approver_username',
        'assigned_initial_reviewer_id', 'assigned_initial_reviewer_username',
        'assigned_final_approver_id', 'assigned_final_approver_username',
        'command_template_json',
        'target_devices_json', 'commands_json',
        'rollback_plan', 'risk_level',
        'scheduled_start', 'scheduled_end',
        'authorization_exempt',
        'actual_start', 'actual_end',
        'result_summary', 'result_detail_json',
        'approval_token', 'rejected_reason',
    }

    # Convert list fields to JSON strings
    if 'target_devices' in updates:
        updates['target_devices_json'] = json.dumps(updates.pop('target_devices'), ensure_ascii=False)
    if 'commands' in updates:
        updates['commands_json'] = json.dumps(updates.pop('commands'), ensure_ascii=False)
    if 'result_detail' in updates:
        updates['result_detail_json'] = json.dumps(updates.pop('result_detail'), ensure_ascii=False)
    if 'command_template' in updates:
        updates['command_template_json'] = json.dumps(updates.pop('command_template'), ensure_ascii=False)

    set_parts = []
    values = []
    for key, val in updates.items():
        if key in allowed_fields:
            set_parts.append(f"{key} = ?")
            values.append(val)

    if not set_parts:
        return existing

    set_parts.append("updated_at = ?")
    values.append(_utc_now_iso())
    values.append(order_id)

    conn.execute(
        f"UPDATE change_orders SET {', '.join(set_parts)} WHERE id = ?",
        values,
    )
    conn.commit()
    return get_change_order(conn, order_id)


def get_change_order(conn, order_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM change_orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def list_change_orders(conn, *, page: int = 1, page_size: int = 20,
                       status: str = '', priority: str = '',
                       search: str = '', requester: str = '',
                       assignee: str = '',
                       bookmarked_by: str = '',
                       my_todo: str = '',
                       group_todo: str = '',
                       my_participated: str = '',
                       my_drafts: str = '',
                       order_type: str = '',
                       created_from: str = '',
                       created_to: str = '',
                       completed_from: str = '',
                       completed_to: str = '',
                       scheduled_from: str = '',
                       scheduled_to: str = '',
                       exclude_requester: str = '') -> tuple[list[dict], int]:
    conditions = []
    params = []

    if my_drafts:
        conditions.append("(requester_username = ? AND status = 'draft')")
        params.append(my_drafts)
    elif my_participated:
        conditions.append(
            "("
            "requester_username = ?"
            " OR assigned_initial_reviewer_username = ?"
            " OR assigned_final_approver_username = ?"
            " OR initial_reviewer_username = ?"
            " OR final_approver_username = ?"
            " OR approver_username = ?"
            ")"
        )
        params.extend([my_participated] * 6)
    elif my_todo:
        conditions.append(
            "("
            "(requester_username = ? AND status IN ('draft', 'rejected', 'approved'))"
            " OR (assigned_initial_reviewer_username = ? AND status = 'initial_review' AND requester_username != ?)"
            " OR (assigned_final_approver_username = ? AND status = 'final_review' AND requester_username != ?)"
            ")"
        )
        params.extend([my_todo, my_todo, my_todo, my_todo, my_todo])
    if group_todo:
        groups = [g.strip() for g in group_todo.split(',') if g.strip()]
        gconds = []
        if 'initial_reviewer' in groups:
            # Show initial_review orders that either have no specific assignee,
            # or are assigned to the current user (my_todo handles the personal case,
            # group_todo shows unassigned ones for anyone in the group to pick up)
            gconds.append("(status = 'initial_review' AND (assigned_initial_reviewer_id IS NULL OR assigned_initial_reviewer_id = ''))")
        if 'final_approver' in groups:
            gconds.append("(status = 'final_review' AND (assigned_final_approver_id IS NULL OR assigned_final_approver_id = ''))")
        if gconds:
            conditions.append(f"({' OR '.join(gconds)})")
            if exclude_requester:
                conditions.append("requester_username != ?")
                params.append(exclude_requester)
        else:
            conditions.append("1=0")
    if status:
        conditions.append("status = ?")
        params.append(status)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)
    if requester:
        conditions.append("requester_username = ?")
        params.append(requester)
    if assignee:
        conditions.append("(assigned_initial_reviewer_username = ? OR assigned_final_approver_username = ? OR initial_reviewer_username = ? OR final_approver_username = ?)")
        params.extend([assignee, assignee, assignee, assignee])
    if bookmarked_by:
        conditions.append("id IN (SELECT order_id FROM change_order_bookmarks WHERE user_id = ?)")
        params.append(bookmarked_by)
    if search:
        conditions.append("(order_number LIKE ? OR title LIKE ? OR description LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    if order_type:
        conditions.append("order_type = ?")
        params.append(order_type)
    if created_from:
        conditions.append("created_at >= ?")
        params.append(created_from)
    if created_to:
        conditions.append("created_at <= ?")
        params.append(created_to)
    if completed_from:
        conditions.append("actual_end >= ?")
        params.append(completed_from)
    if completed_to:
        conditions.append("actual_end <= ?")
        params.append(completed_to)
    if scheduled_from:
        conditions.append("scheduled_start >= ?")
        params.append(scheduled_from)
    if scheduled_to:
        conditions.append("scheduled_end <= ?")
        params.append(scheduled_to)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = conn.execute(f"SELECT COUNT(*) FROM change_orders {where}", params).fetchone()[0]

    offset = (page - 1) * page_size
    rows = conn.execute(
        f"SELECT * FROM change_orders {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()

    return [_row_to_dict(r) for r in rows], total


def get_summary(conn, user_id: str = '', username: str = '') -> dict:
    total = conn.execute("SELECT COUNT(*) FROM change_orders").fetchone()[0]
    by_status = {}
    for row in conn.execute("SELECT status, COUNT(*) as cnt FROM change_orders GROUP BY status"):
        by_status[row['status']] = row['cnt']
    by_priority = {}
    for row in conn.execute("SELECT priority, COUNT(*) as cnt FROM change_orders GROUP BY priority"):
        by_priority[row['priority']] = row['cnt']
    by_type = {}
    for row in conn.execute("SELECT order_type, COUNT(*) as cnt FROM change_orders GROUP BY order_type"):
        by_type[row['order_type']] = row['cnt']

    my_todo_count = 0
    group_todo_count = 0
    if user_id and username:
        # My Todo
        my_todo_count = conn.execute(
            """
            SELECT COUNT(*) FROM change_orders 
            WHERE (
                (status = 'initial_review' AND assigned_initial_reviewer_id = ?) OR 
                (status = 'final_review' AND assigned_final_approver_id = ?)
            ) AND requester_username != ?
            """,
            (user_id, user_id, username)
        ).fetchone()[0]

        # Group Todo
        # Get user's groups
        row = conn.execute('SELECT change_groups_json FROM users WHERE id = ?', (user_id,)).fetchone()
        groups = set()
        if row:
            raw_groups = row[0]
            if isinstance(raw_groups, str):
                import json
                try:
                    raw_groups = json.loads(raw_groups or '[]')
                except Exception:
                    raw_groups = []
            if isinstance(raw_groups, (list, tuple, set)):
                groups = {str(item or '').strip() for item in raw_groups if str(item or '').strip()}
        
        if groups:
            gconds = []
            if 'initial_reviewer' in groups:
                gconds.append("(status = 'initial_review' AND (assigned_initial_reviewer_id IS NULL OR assigned_initial_reviewer_id = ''))")
            if 'final_approver' in groups:
                gconds.append("(status = 'final_review' AND (assigned_final_approver_id IS NULL OR assigned_final_approver_id = ''))")
            
            if gconds:
                group_todo_count = conn.execute(
                    f"SELECT COUNT(*) FROM change_orders WHERE ({' OR '.join(gconds)}) AND requester_username != ?",
                    (username,)
                ).fetchone()[0]

    return {
        'total': total,
        'by_status': by_status,
        'by_priority': by_priority,
        'by_type': by_type,
        'my_todo_count': my_todo_count,
        'group_todo_count': group_todo_count,
    }


def delete_change_order(conn, order_id: str) -> bool:
    row = conn.execute("SELECT id FROM change_orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM change_orders WHERE id = ?", (order_id,))
    conn.commit()
    return True


# ── Bookmarks ────────────────────────────────────────────────────────

def toggle_bookmark(conn, user_id: str, order_id: str) -> bool:
    """Toggle bookmark. Returns True if bookmarked, False if removed."""
    existing = conn.execute(
        "SELECT id FROM change_order_bookmarks WHERE user_id = ? AND order_id = ?",
        (user_id, order_id),
    ).fetchone()
    if existing:
        conn.execute("DELETE FROM change_order_bookmarks WHERE id = ?", (existing['id'],))
        conn.commit()
        return False
    conn.execute(
        "INSERT INTO change_order_bookmarks (id, user_id, order_id, created_at) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), user_id, order_id, _now()),
    )
    conn.commit()
    return True


def get_user_bookmarks(conn, user_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT order_id FROM change_order_bookmarks WHERE user_id = ?", (user_id,)
    ).fetchall()
    return [r['order_id'] for r in rows]


# ── Templates ────────────────────────────────────────────────────────

def save_order_as_template(conn, *, name: str, description: str,
                           order: dict, creator_id: str,
                           creator_username: str) -> dict:
    tid = str(uuid.uuid4())
    now = _now()
    conn.execute(
        """INSERT INTO change_order_templates
           (id, name, description, order_type, priority, target_devices_json,
            commands_json, rollback_plan, risk_level, creator_id,
            creator_username, source_order_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (tid, name, description, order.get('order_type', 'config_change'),
         order.get('priority', 'medium'),
         json.dumps(order.get('target_devices', []), ensure_ascii=False),
         json.dumps(order.get('commands', []), ensure_ascii=False),
         order.get('rollback_plan', ''),
         order.get('risk_level', 'low'),
         creator_id, creator_username, order.get('id', ''), now, now),
    )
    conn.commit()
    return {'id': tid, 'name': name, 'created_at': now}


def list_templates(conn, creator_id: str = '') -> list[dict]:
    if creator_id:
        rows = conn.execute(
            "SELECT * FROM change_order_templates WHERE creator_id = ? ORDER BY created_at DESC",
            (creator_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM change_order_templates ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for jf in ('target_devices_json', 'commands_json'):
            raw = d.get(jf, '') or ''
            try:
                d[jf.replace('_json', '')] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d[jf.replace('_json', '')] = []
        result.append(d)
    return result


def delete_template(conn, template_id: str) -> bool:
    row = conn.execute("SELECT id FROM change_order_templates WHERE id = ?", (template_id,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM change_order_templates WHERE id = ?", (template_id,))
    conn.commit()
    return True


def get_template(conn, template_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM change_order_templates WHERE id = ?", (template_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    for jf in ('target_devices_json', 'commands_json'):
        raw = d.get(jf, '') or ''
        try:
            d[jf.replace('_json', '')] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            d[jf.replace('_json', '')] = []
    return d


def _row_to_dict(row) -> dict:
    d = dict(row)
    for json_field in ('target_devices_json', 'commands_json', 'result_detail_json', 'command_template_json'):
        raw = d.get(json_field, '') or ''
        try:
            parsed = json.loads(raw)
            if json_field == 'command_template_json' and not isinstance(parsed, dict):
                parsed = {}
            d[json_field.replace('_json', '')] = parsed
        except (json.JSONDecodeError, TypeError):
            d[json_field.replace('_json', '')] = [] if json_field in ('target_devices_json', 'commands_json') else {}
    if 'authorization_exempt' in d:
        d['authorization_exempt'] = bool(d.get('authorization_exempt'))
    return d
