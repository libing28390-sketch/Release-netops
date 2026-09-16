import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from services import notification_service


VALID_SELECTION_MODES = {'conditions', 'resources'}
VALID_CONDITION_LOGICS = {'all', 'any', 'none'}
VALID_CONDITION_FIELDS = {'alert_description', 'alert_ip', 'alert_level'}
VALID_CONDITION_OPERATORS = {'contains', 'equals', 'not_contains', 'not_equals', 'regex'}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_json_loads(value: Any, fallback: Any) -> Any:
    if value in (None, ''):
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _normalize_runtime_status(row: dict[str, Any], now_iso: str | None = None) -> str:
    status = str(row.get('status') or 'scheduled').lower()
    if status == 'cancelled':
        return 'cancelled'

    starts_at = str(row.get('starts_at') or '').strip()
    ends_at = str(row.get('ends_at') or '').strip()
    if not starts_at or not ends_at:
        return status or 'scheduled'

    now_dt = datetime.fromisoformat((now_iso or utc_now_iso()).replace('Z', '+00:00'))
    start_dt = datetime.fromisoformat(starts_at.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(ends_at.replace('Z', '+00:00'))

    if now_dt < start_dt:
        return 'scheduled'
    if now_dt > end_dt:
        return 'expired'
    return 'active'


def _normalize_target_ips(raw: Any, fallback_ip: str = '') -> list[str]:
    values = raw if isinstance(raw, list) else _safe_json_loads(raw, [])
    items: list[str] = []
    for item in values:
        value = str(item or '').strip()
        if value and value not in items:
            items.append(value)

    fallback = str(fallback_ip or '').strip()
    if fallback and fallback not in items:
        items.append(fallback)
    return items


def _normalize_match_conditions(raw: Any) -> list[dict[str, str]]:
    values = raw if isinstance(raw, list) else _safe_json_loads(raw, [])
    conditions: list[dict[str, str]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        field = str(item.get('field') or '').strip()
        operator = str(item.get('operator') or '').strip()
        value = str(item.get('value') or '').strip()
        if field not in VALID_CONDITION_FIELDS or operator not in VALID_CONDITION_OPERATORS:
            continue
        conditions.append({'field': field, 'operator': operator, 'value': value})
    return conditions


def _legacy_conditions(window: dict[str, Any]) -> list[dict[str, str]]:
    conditions: list[dict[str, str]] = []
    target_ip = str(window.get('target_ip') or '').strip()
    if target_ip:
        conditions.append({'field': 'alert_ip', 'operator': 'equals', 'value': target_ip})

    title_pattern = str(window.get('title_pattern') or '').strip()
    if title_pattern:
        conditions.append({'field': 'alert_description', 'operator': 'contains', 'value': title_pattern})

    message_pattern = str(window.get('message_pattern') or '').strip()
    if message_pattern:
        conditions.append({'field': 'alert_description', 'operator': 'contains', 'value': message_pattern})

    return conditions


def _normalize_selection_mode(window: dict[str, Any]) -> str:
    mode = str(window.get('selection_mode') or '').strip().lower()
    if mode in VALID_SELECTION_MODES:
        return mode

    if _normalize_match_conditions(window.get('match_conditions') or window.get('match_conditions_json')):
        return 'conditions'

    if str(window.get('title_pattern') or '').strip() or str(window.get('message_pattern') or '').strip():
        return 'conditions'

    return 'resources'


def _normalize_condition_logic(window: dict[str, Any]) -> str:
    logic = str(window.get('condition_logic') or '').strip().lower()
    if logic in VALID_CONDITION_LOGICS:
        return logic
    return 'all'


def _alert_field_value(alert: dict[str, Any], field: str) -> str:
    if field == 'alert_description':
        title = str(alert.get('title') or '').strip()
        message = str(alert.get('message') or '').strip()
        return ' '.join(part for part in [title, message] if part).strip()
    if field == 'alert_ip':
        return str(alert.get('ip_address') or '').strip()
    if field == 'alert_level':
        return str(alert.get('severity') or '').strip().lower()
    return ''


def _match_operator(actual: str, operator: str, expected: str) -> bool:
    actual_value = str(actual or '')
    expected_value = str(expected or '')
    if not expected_value:
        return True
    if operator == 'contains':
        return expected_value.lower() in actual_value.lower()
    if operator == 'equals':
        return actual_value.lower() == expected_value.lower()
    if operator == 'not_contains':
        return expected_value.lower() not in actual_value.lower()
    if operator == 'not_equals':
        return actual_value.lower() != expected_value.lower()
    if operator == 'regex':
        try:
            return re.search(expected_value, actual_value, re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def _match_conditions(window: dict[str, Any], alert: dict[str, Any]) -> bool:
    conditions = [item for item in (window.get('match_conditions') or []) if str(item.get('value') or '').strip()]
    if not conditions:
        return False

    results: list[bool] = []
    for condition in conditions:
        actual = _alert_field_value(alert, condition['field'])
        results.append(_match_operator(actual, condition['operator'], condition['value']))

    logic = _normalize_condition_logic(window)
    if logic == 'any':
        return any(results)
    if logic == 'none':
        return not any(results)
    return all(results)


def _matching_summary(window: dict[str, Any], language: str = 'zh') -> str:
    item = dict(window)
    selection_mode = str(item.get('selection_mode') or '').strip().lower()
    if selection_mode not in VALID_SELECTION_MODES:
        selection_mode = _normalize_selection_mode(item)
    condition_logic = _normalize_condition_logic(item)
    target_ips = _normalize_target_ips(item.get('target_ips') or item.get('target_ips_json'), item.get('target_ip') or '')
    match_conditions = _normalize_match_conditions(item.get('match_conditions') or item.get('match_conditions_json'))
    if selection_mode == 'conditions' and not match_conditions:
        match_conditions = _legacy_conditions(item)

    if selection_mode == 'resources':
        targets = target_ips
        if language == 'zh':
            return f"资源对象：{', '.join(targets) if targets else '未指定'}"
        return f"Resources: {', '.join(targets) if targets else 'n/a'}"

    field_labels = {
        'alert_description': ('告警描述', 'Alert Description'),
        'alert_ip': ('告警IP', 'Alert IP'),
        'alert_level': ('告警等级', 'Alert Level'),
    }
    operator_labels = {
        'contains': ('包含', 'contains'),
        'equals': ('等于', 'equals'),
        'not_contains': ('不包含', 'not contains'),
        'not_equals': ('不等于', 'not equals'),
        'regex': ('正则表达式', 'regex'),
    }
    logic_labels = {
        'all': ('满足全部', 'Match All'),
        'any': ('满足任意', 'Match Any'),
        'none': ('都不满足', 'Match None'),
    }
    parts: list[str] = []
    for condition in match_conditions:
        value = str(condition.get('value') or '').strip()
        if not value:
            continue
        field_label = field_labels.get(condition['field'], (condition['field'], condition['field']))[0 if language == 'zh' else 1]
        operator_label = operator_labels.get(condition['operator'], (condition['operator'], condition['operator']))[0 if language == 'zh' else 1]
        parts.append(f"{field_label} {operator_label} {value}")
    prefix = logic_labels.get(condition_logic, logic_labels['all'])[0 if language == 'zh' else 1]
    joined = '；'.join(parts) if language == 'zh' else '; '.join(parts)
    return f"{prefix}：{joined}" if language == 'zh' else f"{prefix}: {joined}"


def _normalize_window_record(window: dict[str, Any]) -> dict[str, Any]:
    item = dict(window)
    item['notify_user_ids'] = [str(value) for value in _safe_json_loads(item.get('notify_user_ids'), []) if str(value).strip()]
    item['selection_mode'] = _normalize_selection_mode(item)
    item['condition_logic'] = _normalize_condition_logic(item)
    item['target_ips'] = _normalize_target_ips(item.get('target_ips') or item.get('target_ips_json'), item.get('target_ip') or '')
    item['target_ip'] = item['target_ips'][0] if item['target_ips'] else str(item.get('target_ip') or '').strip()
    item['match_conditions'] = _normalize_match_conditions(item.get('match_conditions') or item.get('match_conditions_json'))
    if item['selection_mode'] == 'conditions' and not item['match_conditions']:
        item['match_conditions'] = _legacy_conditions(item)
    item['runtime_status'] = item.get('runtime_status') or _normalize_runtime_status(item)
    item['scope_summary'] = _matching_summary(item, 'zh')
    return item


def alert_matches_window(window: dict[str, Any], alert: dict[str, Any]) -> bool:
    item = _normalize_window_record(window)
    if item['selection_mode'] == 'resources':
        alert_ip = str(alert.get('ip_address') or '').strip()
        return bool(alert_ip and alert_ip in set(item.get('target_ips') or []))
    return _match_conditions(item, alert)


def _normalize_window_payload(payload: dict[str, Any], validate_times: bool) -> dict[str, Any]:
    starts_at = str(payload.get('starts_at') or '').strip()
    ends_at = str(payload.get('ends_at') or '').strip()
    selection_mode = str(payload.get('selection_mode') or '').strip().lower()
    condition_logic = _normalize_condition_logic(payload)
    raw_target_ip = str(payload.get('target_ip') or '').strip()
    target_ips = _normalize_target_ips(payload.get('target_ips'), raw_target_ip)
    match_conditions = _normalize_match_conditions(payload.get('match_conditions'))
    legacy_conditions = _legacy_conditions(payload)

    if selection_mode not in VALID_SELECTION_MODES:
        if match_conditions or (legacy_conditions and not target_ips):
            selection_mode = 'conditions'
        elif target_ips and not match_conditions and not legacy_conditions:
            selection_mode = 'resources'
        elif legacy_conditions:
            selection_mode = 'conditions'
        else:
            selection_mode = 'resources'

    if selection_mode == 'conditions' and not match_conditions:
        match_conditions = legacy_conditions

    if validate_times:
        if not starts_at or not ends_at:
            raise ValueError('starts_at and ends_at are required')
        start_dt = datetime.fromisoformat(starts_at.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(ends_at.replace('Z', '+00:00'))
        if start_dt >= end_dt:
            raise ValueError('ends_at must be later than starts_at')

    if selection_mode == 'resources' and not target_ips:
        raise ValueError('at least one resource object is required')
    if selection_mode == 'conditions' and not any(str(item.get('value') or '').strip() for item in match_conditions):
        raise ValueError('at least one matching condition is required')

    for condition in match_conditions:
        if condition['operator'] == 'regex' and str(condition.get('value') or '').strip():
            try:
                re.compile(str(condition['value']))
            except re.error as exc:
                raise ValueError(f'invalid regex: {exc}')

    normalized = {
        'name': str(payload.get('name') or '').strip(),
        'target_ip': target_ips[0] if target_ips else raw_target_ip,
        'target_ips': target_ips,
        'selection_mode': selection_mode,
        'condition_logic': condition_logic,
        'match_conditions': match_conditions,
        'title_pattern': str(payload.get('title_pattern') or '').strip(),
        'message_pattern': str(payload.get('message_pattern') or '').strip(),
        'starts_at': starts_at,
        'ends_at': ends_at,
        'notify_user_ids': [str(item) for item in (payload.get('notify_user_ids') or []) if str(item).strip()],
        'reason': str(payload.get('reason') or '').strip(),
        'created_by': str(payload.get('created_by') or 'system').strip() or 'system',
    }

    if not normalized['name']:
        normalized['name'] = f"Maintenance {normalized['target_ip'] or 'Window'}"

    return normalized


def _fetch_open_alerts(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        '''
        SELECT
            a.id, a.dedupe_key, a.source, a.severity, a.title, a.message,
            a.device_id, a.interface_name, a.created_at, a.resolved_at,
            a.workflow_status, a.assignee, a.ack_by, a.ack_at, a.note, a.updated_at,
            d.hostname, d.ip_address, d.site
        FROM alert_events a
        LEFT JOIN devices d ON d.id = a.device_id
        WHERE a.resolved_at IS NULL
        ORDER BY a.created_at DESC
        '''
    ).fetchall()
    return [dict(row) for row in rows]


def preview_matches(payload: dict[str, Any]) -> dict[str, Any]:
    window = _normalize_window_payload(payload, validate_times=False)
    conn = get_db_connection()
    try:
        matches = [row for row in _fetch_open_alerts(conn) if alert_matches_window(window, row)]
        return {
            'count': len(matches),
            'items': [
                {
                    'id': row['id'],
                    'title': row['title'],
                    'message': row['message'],
                    'interface_name': row.get('interface_name'),
                    'created_at': row['created_at'],
                    'hostname': row.get('hostname'),
                    'ip_address': row.get('ip_address'),
                    'site': row.get('site'),
                }
                for row in matches[:100]
            ],
        }
    finally:
        conn.close()


def suppress_existing_alerts(window: dict[str, Any], conn=None) -> list[dict[str, Any]]:
    external_conn = conn is not None
    conn = conn or get_db_connection()
    try:
        matches = [row for row in _fetch_open_alerts(conn) if alert_matches_window(window, row)]
        now_iso = utc_now_iso()
        note = f"Suppressed by maintenance window: {window['name']}"
        for row in matches:
            conn.execute(
                '''
                UPDATE alert_events
                SET workflow_status = 'suppressed',
                    note = ?,
                    updated_at = ?
                WHERE id = ? AND resolved_at IS NULL
                ''',
                (note, now_iso, row['id']),
            )
        if not external_conn:
            conn.commit()
        return matches
    finally:
        if not external_conn:
            conn.close()


def create_window(payload: dict[str, Any]) -> dict[str, Any]:
    window = _normalize_window_payload(payload, validate_times=True)
    window_id = str(uuid.uuid4())
    now_iso = utc_now_iso()

    conn = get_db_connection()
    try:
        existing = conn.execute(
            'SELECT id FROM alert_maintenance_windows WHERE LOWER(name) = LOWER(?) LIMIT 1',
            (window['name'],),
        ).fetchone()
        if existing:
            raise ValueError('name already exists')

        conn.execute(
            '''
            INSERT INTO alert_maintenance_windows (
                id, name, target_ip, target_ips_json, selection_mode, condition_logic, match_conditions_json,
                title_pattern, message_pattern, starts_at, ends_at,
                notify_user_ids, reason, status, created_by, created_at, updated_at, last_match_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                window_id,
                window['name'],
                window['target_ip'],
                json.dumps(window['target_ips'], ensure_ascii=False),
                window['selection_mode'],
                window['condition_logic'],
                json.dumps(window['match_conditions'], ensure_ascii=False),
                window['title_pattern'],
                window['message_pattern'],
                window['starts_at'],
                window['ends_at'],
                json.dumps(window['notify_user_ids'], ensure_ascii=False),
                window['reason'],
                'scheduled',
                window['created_by'],
                now_iso,
                now_iso,
                0,
            ),
        )

        persisted = {
            **window,
            'id': window_id,
            'created_at': now_iso,
            'updated_at': now_iso,
            'status': 'scheduled',
        }
        matches = suppress_existing_alerts(persisted, conn=conn)
        conn.execute(
            'UPDATE alert_maintenance_windows SET last_match_count = ? WHERE id = ?',
            (len(matches), window_id),
        )
        conn.commit()

        return _normalize_window_record({
            **persisted,
            'notify_user_ids': json.dumps(window['notify_user_ids'], ensure_ascii=False),
            'target_ips_json': json.dumps(window['target_ips'], ensure_ascii=False),
            'condition_logic': window['condition_logic'],
            'match_conditions_json': json.dumps(window['match_conditions'], ensure_ascii=False),
            'last_match_count': len(matches),
        })
    finally:
        conn.close()


def list_windows(status: str = 'all') -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''
                 SELECT id, name, target_ip, target_ips_json, selection_mode, condition_logic, match_conditions_json,
                   title_pattern, message_pattern, starts_at, ends_at,
                   notify_user_ids, reason, status, created_by, created_at, updated_at, last_match_count
            FROM alert_maintenance_windows
            ORDER BY starts_at DESC
            '''
        ).fetchall()
        items: list[dict[str, Any]] = []
        now_iso = utc_now_iso()
        for row in rows:
            item = _normalize_window_record(dict(row))
            item['runtime_status'] = _normalize_runtime_status(item, now_iso)
            if status != 'all' and item['runtime_status'] != status:
                continue
            items.append(item)
        return items
    finally:
        conn.close()


def list_windows_paginated(status: str = 'all', search: str = '', page: int = 1, page_size: int = 20) -> dict[str, Any]:
    items = list_windows(status=status)
    query = str(search or '').strip().lower()
    if query:
        filtered: list[dict[str, Any]] = []
        for item in items:
            haystack = ' '.join([
                str(item.get('name') or ''),
                ' '.join(item.get('target_ips') or []),
                json.dumps(item.get('match_conditions') or [], ensure_ascii=False),
                str(item.get('reason') or ''),
                str(item.get('created_by') or ''),
                str(item.get('scope_summary') or ''),
            ]).lower()
            if query in haystack:
                filtered.append(item)
    else:
        filtered = items

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        'items': filtered[start:end],
        'total': total,
        'page': page,
        'page_size': page_size,
    }


def find_active_window_for_alert(alert: dict[str, Any], conn=None) -> dict[str, Any] | None:
    external_conn = conn is not None
    conn = conn or get_db_connection()
    try:
        rows = conn.execute(
            '''
                 SELECT id, name, target_ip, target_ips_json, selection_mode, condition_logic, match_conditions_json,
                   title_pattern, message_pattern, starts_at, ends_at,
                   notify_user_ids, reason, status, created_by, created_at, updated_at, last_match_count
            FROM alert_maintenance_windows
            WHERE status != 'cancelled'
            ORDER BY starts_at DESC
            '''
        ).fetchall()
        now_iso = utc_now_iso()
        for row in rows:
            item = _normalize_window_record(dict(row))
            if _normalize_runtime_status(item, now_iso) != 'active':
                continue
            if alert_matches_window(item, alert):
                return item
        return None
    finally:
        if not external_conn:
            conn.close()


def cancel_window(window_id: str) -> None:
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT id FROM alert_maintenance_windows WHERE id = ?', (window_id,)).fetchone()
        if not row:
            raise ValueError('maintenance window not found')
        conn.execute(
            "UPDATE alert_maintenance_windows SET status = 'cancelled', updated_at = ? WHERE id = ?",
            (utc_now_iso(), window_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_window(window_id: str) -> None:
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT id FROM alert_maintenance_windows WHERE id = ?', (window_id,)).fetchone()
        if not row:
            raise ValueError('maintenance window not found')
        conn.execute('DELETE FROM alert_maintenance_windows WHERE id = ?', (window_id,))
        conn.commit()
    finally:
        conn.close()


def reopen_expired_suppressed_alerts() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''
            SELECT
                a.id, a.dedupe_key, a.source, a.severity, a.title, a.message,
                a.device_id, a.interface_name, a.created_at, a.resolved_at,
                a.workflow_status, a.assignee, a.ack_by, a.ack_at, a.note, a.updated_at,
                d.hostname, d.ip_address, d.site
            FROM alert_events a
            LEFT JOIN devices d ON d.id = a.device_id
            WHERE a.resolved_at IS NULL AND COALESCE(a.workflow_status, 'open') = 'suppressed'
            ORDER BY a.created_at ASC
            '''
        ).fetchall()

        now_iso = utc_now_iso()
        reopened: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if find_active_window_for_alert(item, conn=conn):
                continue
            conn.execute(
                '''
                UPDATE alert_events
                SET workflow_status = 'open',
                    note = '',
                    updated_at = ?
                WHERE id = ?
                ''',
                (now_iso, item['id']),
            )
            item['workflow_status'] = 'open'
            item['note'] = ''
            item['updated_at'] = now_iso
            reopened.append(item)

        if reopened:
            conn.commit()
        return reopened
    finally:
        conn.close()


def notify_contacts(window: dict[str, Any], users: list[dict[str, Any]]) -> None:
    if not users:
        return

    normalized = _normalize_window_record(window)
    for user in users:
        raw_channels = user.get('notification_channels') or {}
        channels = _safe_json_loads(raw_channels, {}) if isinstance(raw_channels, str) else raw_channels
        if not isinstance(channels, dict) or not channels:
            continue

        language = str(user.get('preferred_language') or 'zh').lower()
        notification_service.send_all_channels(channels, {
            'title': '维护期已创建' if language == 'zh' else 'Maintenance window created',
            'object_name': normalized['name'],
            'ip_address': normalized['target_ip'] or ', '.join(normalized.get('target_ips') or []),
            'status': 'acknowledged',
            'severity': 'info',
            'message': _matching_summary(normalized, language),
            'first_occurrence': normalized['starts_at'],
            'last_occurrence': normalized['ends_at'],
            'lang': language,
        })
