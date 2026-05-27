from datetime import datetime, timedelta, timezone
import fnmatch
import json
from typing import Any
import uuid

from database import get_db_connection


METRIC_TYPES = {
    'cpu', 'memory', 'interface_util', 'interface_down', 'interconnect_down',
    'temperature_high', 'snmp_unreachable', 'ping_unreachable', 'lldp_neighbor_lost', 'fan_failure', 'power_supply_failure',
    'interface_error_rate_high', 'interface_flap',
    'bgp_neighbor_down', 'ospf_neighbor_down', 'bfd_session_down',
    'host_cpu', 'host_memory', 'host_disk',
    'srv_cpu_load', 'srv_cpu_util', 'srv_iowait', 'srv_mem_avail', 'srv_swap',
    'srv_disk_util', 'srv_disk_inode', 'srv_io_latency', 'srv_tcp_retrans',
    'srv_tcp_conns', 'srv_process_health',
}
THRESHOLD_METRICS = {
    'cpu', 'memory', 'interface_util', 'temperature_high', 'interface_error_rate_high',
    'host_cpu', 'host_memory', 'host_disk',
    'srv_cpu_load', 'srv_cpu_util', 'srv_iowait', 'srv_mem_avail', 'srv_swap',
    'srv_disk_util', 'srv_disk_inode', 'srv_io_latency', 'srv_tcp_retrans', 'srv_tcp_conns',
}
SCOPE_TYPES = {'global', 'site', 'device', 'interface'}
SCOPE_MATCH_MODES = {'exact', 'contains', 'prefix', 'glob'}
SCOPE_PRIORITY = {'global': 0, 'site': 1, 'device': 2, 'interface': 3}
ALLOWED_SEVERITIES = {'critical', 'major', 'warning'}


def _default_severity_for_metric(metric_type: str) -> str:
    if metric_type in {
        'interconnect_down', 'snmp_unreachable', 'lldp_neighbor_lost', 'temperature_high', 'interface_error_rate_high', 'interface_flap', 'interface_down',
        'host_cpu', 'host_memory', 'host_disk',
        'srv_cpu_load', 'srv_cpu_util', 'srv_iowait', 'srv_mem_avail', 'srv_swap',
        'srv_disk_util', 'srv_disk_inode', 'srv_io_latency', 'srv_tcp_retrans', 'srv_tcp_conns'
    }:
        return 'major'
    if metric_type in {
        'fan_failure', 'power_supply_failure', 'bgp_neighbor_down', 'ospf_neighbor_down', 'bfd_session_down', 'ping_unreachable',
        'srv_process_health'
    }:
        return 'critical'
    return 'major'


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_rule_row(row) -> dict[str, Any]:
    item = dict(row)
    item['enabled'] = bool(item.get('enabled', 1))
    item['notify_on_active'] = bool(item.get('notify_on_active', 1))
    item['notify_on_recovery'] = bool(item.get('notify_on_recovery', 1))
    item['notify_on_reopen_after_maintenance'] = bool(item.get('notify_on_reopen_after_maintenance', 1))
    item['threshold'] = None if item.get('threshold') is None else round(float(item.get('threshold')), 1)
    item['notification_repeat_window_seconds'] = int(item.get('notification_repeat_window_seconds', 120) or 120)
    item['for_duration_seconds'] = int(item.get('for_duration_seconds', 0) or 0)
    item['aggregation_mode'] = str(item.get('aggregation_mode') or 'dedupe_key').strip() or 'dedupe_key'
    item['metric_type'] = str(item.get('metric_type') or '').strip()
    item['scope_type'] = str(item.get('scope_type') or 'global').strip() or 'global'
    item['scope_match_mode'] = str(item.get('scope_match_mode') or 'exact').strip() or 'exact'
    item['scope_value'] = str(item.get('scope_value') or '').strip()
    item['severity'] = str(item.get('severity') or _default_severity_for_metric(item['metric_type'])).strip().lower() or _default_severity_for_metric(item['metric_type'])
    item['created_by'] = str(item.get('created_by') or 'system')
    item['created_at'] = str(item.get('created_at') or _utc_now_iso())
    item['updated_by'] = str(item.get('updated_by') or 'system')
    item['updated_at'] = str(item.get('updated_at') or _utc_now_iso())
    return item


def _history_item_from_row(row) -> dict[str, Any]:
    item = dict(row)
    try:
      snapshot = json.loads(item.get('snapshot_json') or '{}')
    except Exception:
      snapshot = {}
    return {
        'id': item['id'],
        'rule_id': item.get('settings_id'),
        'changed_by': item.get('changed_by') or 'system',
        'created_at': item.get('created_at') or _utc_now_iso(),
        'snapshot': snapshot,
    }


def _validate_threshold(value: Any) -> float:
    try:
        numeric = float(value)
    except Exception as exc:
        raise ValueError('threshold must be a number') from exc
    if numeric < 0 or numeric > 100:
        raise ValueError('threshold must be between 0 and 100')
    return round(numeric, 1)


def _validate_rule_payload(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(existing or {})
    metric_type = str(payload.get('metric_type', base.get('metric_type') or '')).strip()
    if metric_type not in METRIC_TYPES:
        raise ValueError(f'metric_type must be one of {sorted(METRIC_TYPES)}')

    name = str(payload.get('name', base.get('name') or '')).strip()
    if not name:
        raise ValueError('name is required')

    scope_type = str(payload.get('scope_type', base.get('scope_type') or 'global')).strip() or 'global'
    if scope_type not in SCOPE_TYPES:
        raise ValueError(f'scope_type must be one of {sorted(SCOPE_TYPES)}')

    scope_match_mode = str(payload.get('scope_match_mode', base.get('scope_match_mode') or 'exact')).strip() or 'exact'
    if scope_match_mode not in SCOPE_MATCH_MODES:
        raise ValueError(f'scope_match_mode must be one of {sorted(SCOPE_MATCH_MODES)}')

    scope_value = str(payload.get('scope_value', base.get('scope_value') or '')).strip()
    if scope_type != 'global' and not scope_value:
        raise ValueError('scope_value is required when scope_type is not global')

    default_severity = _default_severity_for_metric(metric_type)
    severity = str(payload.get('severity', base.get('severity') or default_severity)).strip().lower() or default_severity
    if severity not in ALLOWED_SEVERITIES:
        raise ValueError(f'severity must be one of {sorted(ALLOWED_SEVERITIES)}')

    aggregation_mode = str(payload.get('aggregation_mode', base.get('aggregation_mode') or 'dedupe_key')).strip() or 'dedupe_key'
    if aggregation_mode != 'dedupe_key':
        raise ValueError('Only dedupe_key aggregation mode is currently supported')

    try:
        repeat_window = int(payload.get('notification_repeat_window_seconds', base.get('notification_repeat_window_seconds', 120)))
    except Exception as exc:
        raise ValueError('notification_repeat_window_seconds must be an integer') from exc
    if repeat_window < 0 or repeat_window > 86400:
        raise ValueError('notification_repeat_window_seconds must be between 0 and 86400')

    try:
        for_duration = int(payload.get('for_duration_seconds', base.get('for_duration_seconds', 0)))
    except Exception as exc:
        raise ValueError('for_duration_seconds must be an integer') from exc
    if for_duration < 0 or for_duration > 3600:
        raise ValueError('for_duration_seconds must be between 0 and 3600')

    threshold = base.get('threshold')
    if metric_type in THRESHOLD_METRICS:
        threshold = _validate_threshold(payload.get('threshold', threshold))
    else:
        threshold = None

    return {
        'name': name,
        'metric_type': metric_type,
        'scope_type': scope_type,
        'scope_match_mode': scope_match_mode,
        'scope_value': scope_value,
        'severity': severity,
        'threshold': threshold,
        'enabled': bool(payload.get('enabled', base.get('enabled', True))),
        'aggregation_mode': aggregation_mode,
        'notification_repeat_window_seconds': repeat_window,
        'for_duration_seconds': for_duration,
        'notify_on_active': bool(payload.get('notify_on_active', base.get('notify_on_active', True))),
        'notify_on_recovery': bool(payload.get('notify_on_recovery', base.get('notify_on_recovery', True))),
        'notify_on_reopen_after_maintenance': bool(payload.get('notify_on_reopen_after_maintenance', base.get('notify_on_reopen_after_maintenance', True))),
    }


def _write_history(conn, rule: dict[str, Any]) -> None:
    conn.execute(
        '''
        INSERT INTO alert_rule_history (id, settings_id, snapshot_json, changed_by, created_at)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (
            str(uuid.uuid4()),
            rule['id'],
            json.dumps(rule, ensure_ascii=False),
            rule['updated_by'],
            rule['updated_at'],
        ),
    )


def list_rules() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''
            SELECT *
            FROM alert_rules
            ORDER BY metric_type ASC, enabled DESC, scope_type DESC, updated_at DESC, name ASC
            '''
        ).fetchall()
        return [_normalize_rule_row(row) for row in rows]
    finally:
        conn.close()


def _get_metric_category(metric_type: str) -> str:
    if metric_type in {'host_cpu', 'host_memory', 'host_disk'}:
        return 'host'
    if metric_type.startswith('srv_'):
        return 'server'
    return 'network'


def list_rules_paginated(
    search: str = '',
    enabled: str = 'all',
    metric_type: str = 'all',
    category: str = 'all',
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    all_items = list_rules()
    enabled_filter = str(enabled or 'all').strip().lower()
    metric_filter = str(metric_type or 'all').strip().lower()
    cat_filter = str(category or 'all').strip().lower()
    filtered_items = all_items

    if enabled_filter == 'enabled':
        filtered_items = [item for item in filtered_items if item.get('enabled')]
    elif enabled_filter == 'disabled':
        filtered_items = [item for item in filtered_items if not item.get('enabled')]

    query = str(search or '').strip().lower()
    if query:
        next_items: list[dict[str, Any]] = []
        for item in filtered_items:
            haystack = ' '.join([
                str(item.get('name') or ''),
                str(item.get('metric_type') or ''),
                str(item.get('scope_type') or ''),
                str(item.get('scope_value') or ''),
                str(item.get('severity') or ''),
                str(item.get('updated_by') or ''),
            ]).lower()
            if query in haystack:
                next_items.append(item)
        filtered_items = next_items

    # Compute category counts after search and enabled filter are applied
    category_counts = {
        'all': len(filtered_items),
        'network': sum(1 for item in filtered_items if _get_metric_category(item.get('metric_type')) == 'network'),
        'host': sum(1 for item in filtered_items if _get_metric_category(item.get('metric_type')) == 'host'),
        'server': sum(1 for item in filtered_items if _get_metric_category(item.get('metric_type')) == 'server'),
    }

    # Filter by category
    if cat_filter != 'all':
        filtered_items = [item for item in filtered_items if _get_metric_category(item.get('metric_type')) == cat_filter]

    # Filter by metric type
    if metric_filter != 'all' and metric_filter:
        filtered_items = [item for item in filtered_items if item.get('metric_type') == metric_filter]

    total = len(filtered_items)
    current_page = max(1, int(page or 1))
    current_page_size = max(1, int(page_size or 20))
    start = (current_page - 1) * current_page_size
    end = start + current_page_size
    return {
        'items': filtered_items[start:end],
        'total': total,
        'page': current_page,
        'page_size': current_page_size,
        'category_counts': category_counts,
    }


def get_rule(rule_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM alert_rules WHERE id = ?', (rule_id,)).fetchone()
        return _normalize_rule_row(row) if row else None
    finally:
        conn.close()


def create_rule(payload: dict[str, Any]) -> dict[str, Any]:
    now = _utc_now_iso()
    rule = _validate_rule_payload(payload)
    rule_id = str(uuid.uuid4())
    created_by = str(payload.get('created_by') or payload.get('updated_by') or 'system').strip() or 'system'
    created = {
        'id': rule_id,
        **rule,
        'created_by': created_by,
        'created_at': now,
        'updated_by': created_by,
        'updated_at': now,
    }
    conn = get_db_connection()
    try:
        conn.execute(
            '''
            INSERT INTO alert_rules (
                id, name, metric_type, scope_type, scope_match_mode, scope_value, severity, threshold, enabled,
                aggregation_mode, notification_repeat_window_seconds, for_duration_seconds,
                notify_on_active, notify_on_recovery, notify_on_reopen_after_maintenance,
                created_by, created_at, updated_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                created['id'],
                created['name'],
                created['metric_type'],
                created['scope_type'],
                created['scope_match_mode'],
                created['scope_value'],
                created['severity'],
                created['threshold'],
                1 if created['enabled'] else 0,
                created['aggregation_mode'],
                created['notification_repeat_window_seconds'],
                created['for_duration_seconds'],
                1 if created['notify_on_active'] else 0,
                1 if created['notify_on_recovery'] else 0,
                1 if created['notify_on_reopen_after_maintenance'] else 0,
                created['created_by'],
                created['created_at'],
                created['updated_by'],
                created['updated_at'],
            ),
        )
        _write_history(conn, created)
        conn.commit()
        return created
    finally:
        conn.close()


def update_rule(rule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        existing_row = conn.execute('SELECT * FROM alert_rules WHERE id = ?', (rule_id,)).fetchone()
        if not existing_row:
            raise ValueError('Alert rule not found')
        existing = _normalize_rule_row(existing_row)
        updated_fields = _validate_rule_payload(payload, existing)
        updated = {
            **existing,
            **updated_fields,
            'updated_by': str(payload.get('updated_by') or existing.get('updated_by') or 'system').strip() or 'system',
            'updated_at': _utc_now_iso(),
        }
        conn.execute(
            '''
            UPDATE alert_rules
            SET name = ?, metric_type = ?, scope_type = ?, scope_match_mode = ?, scope_value = ?, severity = ?, threshold = ?, enabled = ?,
                aggregation_mode = ?, notification_repeat_window_seconds = ?, for_duration_seconds = ?,
                notify_on_active = ?, notify_on_recovery = ?, notify_on_reopen_after_maintenance = ?,
                updated_by = ?, updated_at = ?
            WHERE id = ?
            ''',
            (
                updated['name'],
                updated['metric_type'],
                updated['scope_type'],
                updated['scope_match_mode'],
                updated['scope_value'],
                updated['severity'],
                updated['threshold'],
                1 if updated['enabled'] else 0,
                updated['aggregation_mode'],
                updated['notification_repeat_window_seconds'],
                updated['for_duration_seconds'],
                1 if updated['notify_on_active'] else 0,
                1 if updated['notify_on_recovery'] else 0,
                1 if updated['notify_on_reopen_after_maintenance'] else 0,
                updated['updated_by'],
                updated['updated_at'],
                rule_id,
            ),
        )
        if any(existing.get(key) != updated.get(key) for key in updated.keys() if key not in {'updated_at'}):
            _write_history(conn, updated)
        conn.commit()
        return updated
    finally:
        conn.close()


def delete_rule(rule_id: str) -> None:
    conn = get_db_connection()
    try:
        deleted = conn.execute('DELETE FROM alert_rules WHERE id = ?', (rule_id,)).rowcount
        if not deleted:
            raise ValueError('Alert rule not found')
        conn.commit()
    finally:
        conn.close()


def get_runtime_rules() -> list[dict[str, Any]]:
    return [rule for rule in list_rules() if rule['enabled']]


def _scope_matches(rule: dict[str, Any], context: dict[str, Any]) -> bool:
    scope_type = rule.get('scope_type') or 'global'
    scope_match_mode = str(rule.get('scope_match_mode') or 'exact').strip().lower() or 'exact'
    scope_value = str(rule.get('scope_value') or '').strip().lower()

    def match_value(candidate: str) -> bool:
        normalized = str(candidate or '').strip().lower()
        if not normalized:
            return False
        if scope_match_mode == 'contains':
            return scope_value in normalized
        if scope_match_mode == 'prefix':
            return normalized.startswith(scope_value)
        if scope_match_mode == 'glob':
            return fnmatch.fnmatch(normalized, scope_value)
        return normalized == scope_value

    if scope_type == 'global':
        return True
    if scope_type == 'site':
        return match_value(str(context.get('site') or ''))
    if scope_type == 'device':
        device_candidates = [
            str(context.get('device_id') or ''),
            str(context.get('hostname') or ''),
            str(context.get('ip_address') or ''),
        ]
        return any(match_value(candidate) for candidate in device_candidates)
    if scope_type == 'interface':
        return match_value(str(context.get('interface_name') or ''))
    return False


def select_rule(rules: list[dict[str, Any]], metric_type: str, context: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [rule for rule in rules if rule.get('metric_type') == metric_type and _scope_matches(rule, context)]
    if not candidates:
        return None
    candidates.sort(
        key=lambda rule: (
            SCOPE_PRIORITY.get(str(rule.get('scope_type') or 'global'), 0),
            str(rule.get('updated_at') or ''),
        ),
        reverse=True,
    )
    return candidates[0]


def list_rule_history(limit: int = 20, rule_id: str | None = None) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        if rule_id:
            rows = conn.execute(
                '''
                SELECT id, settings_id, snapshot_json, changed_by, created_at
                FROM alert_rule_history
                WHERE settings_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                ''',
                (rule_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                '''
                SELECT id, settings_id, snapshot_json, changed_by, created_at
                FROM alert_rule_history
                ORDER BY created_at DESC
                LIMIT ?
                ''',
                (limit,),
            ).fetchall()
        return [_history_item_from_row(row) for row in rows]
    finally:
        conn.close()


def get_rules_preview() -> dict[str, Any]:
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc)
        since_24h = (now - timedelta(hours=24)).replace(microsecond=0).isoformat()
        alerts_24h = conn.execute('SELECT COUNT(*) AS c FROM alert_events WHERE created_at >= ?', (since_24h,)).fetchone()['c']
        resolved_24h = conn.execute('SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NOT NULL AND resolved_at >= ?', (since_24h,)).fetchone()['c']
        noisy_alerts = conn.execute(
            '''
            SELECT dedupe_key, title, severity, COUNT(*) AS event_count, MAX(created_at) AS last_seen
            FROM alert_events
            WHERE created_at >= ?
            GROUP BY dedupe_key, title, severity
            HAVING COUNT(*) > 1
            ORDER BY event_count DESC, last_seen DESC
            LIMIT 8
            ''',
            (since_24h,),
        ).fetchall()
        open_by_title = conn.execute(
            '''
            SELECT title, severity, COUNT(*) AS open_count
            FROM alert_events
            WHERE resolved_at IS NULL
            GROUP BY title, severity
            ORDER BY open_count DESC, title ASC
            LIMIT 8
            '''
        ).fetchall()
        return {
            'alerts_24h': int(alerts_24h),
            'resolved_24h': int(resolved_24h),
            'repeated_key_count': len(noisy_alerts),
            'top_repeated_alerts': [dict(row) for row in noisy_alerts],
            'open_alert_groups': [dict(row) for row in open_by_title],
        }
    finally:
        conn.close()