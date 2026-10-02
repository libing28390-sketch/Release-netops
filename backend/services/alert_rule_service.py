from datetime import datetime, timedelta, timezone
from datetime import datetime, timedelta, timezone
import fnmatch
import json
import re
from typing import Any
import uuid

from database import get_db_connection
from services.snmp_metric_profile_service import (
    get_alert_metric_collection,
    list_alert_metric_collections,
)


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
SUPPORTED_METRIC_TYPES = frozenset(metric for metric in METRIC_TYPES if not metric.startswith('srv_'))
THRESHOLD_METRICS = {
    'cpu', 'memory', 'interface_util', 'temperature_high', 'interface_error_rate_high',
    'host_cpu', 'host_memory', 'host_disk',
    'srv_cpu_load', 'srv_cpu_util', 'srv_iowait', 'srv_mem_avail', 'srv_swap',
    'srv_disk_util', 'srv_disk_inode', 'srv_io_latency', 'srv_tcp_retrans', 'srv_tcp_conns',
}
SCOPE_TYPES = {'global', 'site', 'device', 'devices', 'interface', 'role', 'composite', 'ip', 'tag'}
SCOPE_MATCH_MODES = {'exact', 'contains', 'prefix', 'glob'}
SCOPE_PRIORITY = {
    'global': 0,
    'site': 1,
    'role': 1,
    'composite': 2,
    'tag': 2,
    'device': 3,
    'devices': 5,
    'ip': 3,
    'interface': 4,
}
ALLOWED_SEVERITIES = {'critical', 'major', 'warning'}
ALLOWED_NOTIFICATION_CHANNELS = {
    'workspace', 'feishu', 'dingtalk', 'wechat', 'email', 'global_webhook',
}


class UnsupportedMetricTypeError(ValueError):
    """Raised when an alert metric has no connected runtime evaluator."""

    def __init__(self, metric_type: str):
        self.metric_type = metric_type
        self.supported_metric_types = sorted(SUPPORTED_METRIC_TYPES)
        super().__init__(f'metric_type {metric_type!r} is not supported by the alert rule engine')


def _tenant_id(value: Any = None) -> str:
    return str(value or 'tenant-default').strip() or 'tenant-default'


def _normalize_notification_group_names(value: Any) -> list[str]:
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = [part.strip() for part in raw.split(',') if part.strip()]
    if not isinstance(raw, (list, tuple, set)):
        raw = []
    normalized: list[str] = []
    for name in raw:
        group_name = str(name or '').strip()
        if group_name and group_name not in normalized:
            normalized.append(group_name)
    return normalized


def _normalize_notification_channels(value: Any) -> list[str]:
    """Normalize persisted/API channel values without exposing raw JSONB."""
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = [part.strip() for part in raw.split(',') if part.strip()]
    if not isinstance(raw, (list, tuple, set)):
        raw = ['workspace']
    normalized: list[str] = []
    for channel in raw:
        key = str(channel or '').strip().lower()
        if key and key in ALLOWED_NOTIFICATION_CHANNELS and key not in normalized:
            normalized.append(key)
    return normalized or ['workspace']


def _normalize_current_notification_channels(value: Any, metric_type: str) -> list[str]:
    """Expose only the notification methods supported by alert rules.

    ``workspace`` was the legacy "follow each user's preference" channel.
    Network alert rules now describe an explicit Webhook (Feishu) and/or email
    policy. Host resource rules are consumed by the platform health evaluator,
    so they retain their internal workspace marker.
    """
    if str(metric_type or '').startswith('host_'):
        return ['workspace']
    raw_channels = _normalize_notification_channels(value)
    supported = [channel for channel in raw_channels if channel in {'feishu', 'email'}]
    if 'workspace' in raw_channels or not supported:
        return ['feishu', 'email']
    return supported


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
    item['metric_type'] = str(item.get('metric_type') or '').strip()
    item['notification_channels'] = _normalize_current_notification_channels(
        item.get('notification_channels_json'), item['metric_type'],
    )
    item.pop('notification_channels_json', None)
    item['notification_group_names'] = _normalize_notification_group_names(item.get('notification_group_names_json'))
    item.pop('notification_group_names_json', None)
    item['tenant_id'] = _tenant_id(item.get('tenant_id'))
    item['enabled'] = bool(item.get('enabled', 1))
    item['notify_on_active'] = bool(item.get('notify_on_active', 1))
    item['notify_on_recovery'] = bool(item.get('notify_on_recovery', 1))
    item['notify_on_reopen_after_maintenance'] = bool(item.get('notify_on_reopen_after_maintenance', 1))
    item['threshold'] = None if item.get('threshold') is None else round(float(item.get('threshold')), 1)
    item['notification_repeat_window_seconds'] = int(item.get('notification_repeat_window_seconds', 120) or 120)
    item['for_duration_seconds'] = int(item.get('for_duration_seconds', 0) or 0)
    item['aggregation_mode'] = str(item.get('aggregation_mode') or 'dedupe_key').strip() or 'dedupe_key'
    item['rule_supported'] = item['metric_type'] in SUPPORTED_METRIC_TYPES
    item['unsupported_reason'] = '' if item['rule_supported'] else 'no_alert_executor'
    item['scope_type'] = str(item.get('scope_type') or 'global').strip() or 'global'
    item['scope_match_mode'] = str(item.get('scope_match_mode') or 'exact').strip() or 'exact'
    item['scope_value'] = str(item.get('scope_value') or '').strip()
    item['severity'] = str(item.get('severity') or _default_severity_for_metric(item['metric_type'])).strip().lower() or _default_severity_for_metric(item['metric_type'])
    item['created_by'] = str(item.get('created_by') or 'system')
    item['created_at'] = str(item.get('created_at') or _utc_now_iso())
    item['updated_by'] = str(item.get('updated_by') or 'system')
    item['updated_at'] = str(item.get('updated_at') or _utc_now_iso())
    # OIDs are owned by the SNMP metric template. Expose the read-only
    # binding without persisting a duplicate OID in alert_rules.
    item['collection'] = get_alert_metric_collection(item['metric_type'])
    return item


def _history_item_from_row(row) -> dict[str, Any]:
    item = dict(row)
    try:
      snapshot = json.loads(item.get('snapshot_json') or '{}')
    except Exception:
      snapshot = {}
    if isinstance(snapshot, dict):
        snapshot['notification_channels'] = _normalize_current_notification_channels(
            snapshot.get('notification_channels'), str(snapshot.get('metric_type') or ''),
        )
    return {
        'id': item['id'],
        'rule_id': item.get('rule_id') or item.get('settings_id'),
        'tenant_id': _tenant_id(item.get('tenant_id') or snapshot.get('tenant_id')),
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


def _validate_rule_payload(
    payload: dict[str, Any],
    existing: dict[str, Any] | None = None,
    *,
    conn=None,
    tenant_id: str = 'tenant-default',
) -> dict[str, Any]:
    base = dict(existing or {})
    metric_type = str(payload.get('metric_type', base.get('metric_type') or '')).strip()
    if metric_type not in METRIC_TYPES:
        raise ValueError(f'metric_type must be one of {sorted(METRIC_TYPES)}')
    if metric_type.startswith('srv_'):
        raise UnsupportedMetricTypeError(metric_type)

    name = str(payload.get('name', base.get('name') or '')).strip()
    if not name:
        raise ValueError('name is required')

    scope_type = str(payload.get('scope_type', base.get('scope_type') or 'global')).strip() or 'global'
    if scope_type not in SCOPE_TYPES:
        raise ValueError(f'scope_type must be one of {sorted(SCOPE_TYPES)}')

    tenant_id = _tenant_id(tenant_id)
    if metric_type.startswith('host_'):
        if tenant_id != 'tenant-default':
            raise ValueError('host_* alert rules are only available in tenant-default')
        if scope_type != 'global':
            raise ValueError('host_* alert rules must use global scope')

    scope_match_mode = str(payload.get('scope_match_mode', base.get('scope_match_mode') or 'exact')).strip() or 'exact'
    if scope_match_mode not in SCOPE_MATCH_MODES:
        raise ValueError(f'scope_match_mode must be one of {sorted(SCOPE_MATCH_MODES)}')

    scope_value = str(payload.get('scope_value', base.get('scope_value') or '')).strip()
    if scope_type == 'devices' and scope_match_mode != 'exact':
        raise ValueError('selected device scope only supports exact matching')
    if scope_type != 'global' and not scope_value:
        raise ValueError('scope_value is required when scope_type is not global')
    if scope_type == 'devices':
        device_ids = _parse_scope_device_ids(scope_value)
        if not device_ids:
            raise ValueError('execution machine scope requires at least one CMDB device')
        if len(device_ids) > 200:
            raise ValueError('execution machine scope supports at most 200 devices')
        if conn is None:
            raise ValueError('execution machine validation requires a tenant database context')
        placeholders = ','.join('?' for _ in device_ids)
        found_rows = conn.execute(
            f"SELECT id FROM devices WHERE COALESCE(tenant_id, 'tenant-default') = ? AND id IN ({placeholders})",
            [tenant_id, *device_ids],
        ).fetchall()
        found_ids = {str(row['id']) for row in found_rows}
        if any(device_id not in found_ids for device_id in device_ids):
            raise ValueError('one or more selected execution machines are not in the current tenant CMDB')
        scope_value = json.dumps(device_ids, ensure_ascii=False)
    elif scope_type == 'composite':
        try:
            composite_filters = json.loads(scope_value)
        except (TypeError, ValueError):
            raise ValueError('composite scope_value must be a JSON object')
        if not isinstance(composite_filters, dict) or not any(
            str(composite_filters.get(field) or '').strip()
            for field in ('site', 'role', 'category', 'platform', 'interface')
        ):
            raise ValueError('composite scope requires at least one asset condition')
    elif scope_type == 'tag':
        try:
            tag_filter = json.loads(scope_value)
        except (TypeError, ValueError):
            raise ValueError('tag scope_value must be a JSON object')
        expression = tag_filter.get('expression') if isinstance(tag_filter, dict) else None
        if not isinstance(expression, dict) or not _tag_expression_has_conditions(expression):
            raise ValueError('tag scope requires at least one tag condition')
    elif scope_type == 'ip' and not _parse_scope_ip_values(scope_value):
        raise ValueError('IP scope requires at least one IP address')

    default_severity = _default_severity_for_metric(metric_type)
    severity = str(payload.get('severity', base.get('severity') or default_severity)).strip().lower() or default_severity
    if severity not in ALLOWED_SEVERITIES:
        raise ValueError(f'severity must be one of {sorted(ALLOWED_SEVERITIES)}')

    aggregation_mode = str(payload.get('aggregation_mode', base.get('aggregation_mode') or 'dedupe_key')).strip() or 'dedupe_key'
    if aggregation_mode != 'dedupe_key':
        raise ValueError('Only dedupe_key aggregation mode is currently supported')

    channels_value = payload.get('notification_channels', base.get('notification_channels', ['workspace']))
    if channels_value is None:
        channels_value = ['workspace']
    if isinstance(channels_value, str):
        try:
            channels_value = json.loads(channels_value)
        except (TypeError, ValueError):
            channels_value = [part.strip() for part in channels_value.split(',') if part.strip()]
    if not isinstance(channels_value, (list, tuple, set)):
        raise ValueError('notification_channels must be an array')
    notification_channels = []
    for channel in channels_value:
        normalized_channel = str(channel or '').strip().lower()
        if normalized_channel not in ALLOWED_NOTIFICATION_CHANNELS:
            raise ValueError(
                f'notification_channels must contain only {sorted(ALLOWED_NOTIFICATION_CHANNELS)}'
            )
        if normalized_channel not in notification_channels:
            notification_channels.append(normalized_channel)
    if not notification_channels:
        raise ValueError('notification_channels must contain at least one channel')
    if 'workspace' in notification_channels and len(notification_channels) > 1:
        raise ValueError('workspace cannot be combined with explicit notification channels')
    if metric_type.startswith('host_') and notification_channels != ['workspace']:
        raise ValueError('host_* alert rules only support workspace notifications')
    if not metric_type.startswith('host_') and 'workspace' in notification_channels:
        raise ValueError('workspace notifications are reserved for system host alerts; select Webhook or email')
    if not metric_type.startswith('host_') and any(
        channel not in {'feishu', 'email'} for channel in notification_channels
    ):
        raise ValueError('alert rules only support Webhook and email notifications')

    groups_value = payload.get('notification_group_names', base.get('notification_group_names', []))
    notification_group_names = _normalize_notification_group_names(groups_value)
    if metric_type.startswith('host_') and notification_group_names:
        raise ValueError('host_* alert rules cannot target notification groups')
    if notification_group_names:
        if conn is None:
            raise ValueError('notification group validation requires a tenant database context')
        unknown = []
        for group_name in notification_group_names:
            exists = conn.execute(
                "SELECT 1 FROM users WHERE tenant_id = ? AND status = 'active' AND group_name = ? LIMIT 1",
                (tenant_id, group_name),
            ).fetchone()
            if not exists:
                unknown.append(group_name)
        if unknown:
            raise ValueError(f'Unknown active user group(s): {", ".join(unknown)}')

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
        'notification_channels': notification_channels,
        'notification_group_names': notification_group_names,
        'notify_on_active': bool(payload.get('notify_on_active', base.get('notify_on_active', True))),
        'notify_on_recovery': bool(payload.get('notify_on_recovery', base.get('notify_on_recovery', True))),
        'notify_on_reopen_after_maintenance': bool(payload.get('notify_on_reopen_after_maintenance', base.get('notify_on_reopen_after_maintenance', True))),
    }


def _write_history(conn, rule: dict[str, Any]) -> None:
    conn.execute(
        '''
        INSERT INTO alert_rule_history (id, settings_id, rule_id, tenant_id, snapshot_json, changed_by, created_at)
        VALUES (?, 'default', ?, ?, ?, ?, ?)
        ''',
        (
            str(uuid.uuid4()),
            rule['id'],
            _tenant_id(rule.get('tenant_id')),
            json.dumps(rule, ensure_ascii=False),
            rule['updated_by'],
            rule['updated_at'],
        ),
    )


def list_rules(tenant_id: str = 'tenant-default') -> list[dict[str, Any]]:
    tenant_id = _tenant_id(tenant_id)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''
            SELECT *
            FROM alert_rules
            WHERE tenant_id = ?
            ORDER BY metric_type ASC, enabled DESC, scope_type DESC, updated_at DESC, name ASC
            ''',
            (tenant_id,),
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


def _supported_metric_types_for_tenant(tenant_id: str) -> list[str]:
    supported = SUPPORTED_METRIC_TYPES
    if _tenant_id(tenant_id) != 'tenant-default':
        supported = frozenset(metric for metric in supported if not metric.startswith('host_'))
    return sorted(supported)


def list_rules_paginated(
    search: str = '',
    enabled: str = 'all',
    metric_type: str = 'all',
    category: str = 'all',
    page: int = 1,
    page_size: int = 20,
    tenant_id: str = 'tenant-default',
) -> dict[str, Any]:
    tenant_id = _tenant_id(tenant_id)
    all_items = list_rules(tenant_id=tenant_id)
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
        'collection_catalog': list_alert_metric_collections(),
        'supported_metric_types': _supported_metric_types_for_tenant(tenant_id),
    }


def get_rule(rule_id: str, tenant_id: str = 'tenant-default') -> dict[str, Any] | None:
    tenant_id = _tenant_id(tenant_id)
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM alert_rules WHERE id = ? AND tenant_id = ?', (rule_id, tenant_id)).fetchone()
        return _normalize_rule_row(row) if row else None
    finally:
        conn.close()


def create_rule(payload: dict[str, Any], tenant_id: str = 'tenant-default') -> dict[str, Any]:
    tenant_id = _tenant_id(tenant_id)
    now = _utc_now_iso()
    conn = get_db_connection()
    try:
        rule = _validate_rule_payload(payload, conn=conn, tenant_id=tenant_id)
        rule_id = str(uuid.uuid4())
        created_by = str(payload.get('created_by') or payload.get('updated_by') or 'system').strip() or 'system'
        created = {
            'id': rule_id,
            'tenant_id': tenant_id,
            **rule,
            'created_by': created_by,
            'created_at': now,
            'updated_by': created_by,
            'updated_at': now,
        }
        created['collection'] = get_alert_metric_collection(created['metric_type'])
        conn.execute(
            '''
            INSERT INTO alert_rules (
                id, tenant_id, name, metric_type, scope_type, scope_match_mode, scope_value, severity, threshold, enabled,
                aggregation_mode, notification_repeat_window_seconds, for_duration_seconds,
                notification_channels_json, notification_group_names_json,
                notify_on_active, notify_on_recovery, notify_on_reopen_after_maintenance,
                created_by, created_at, updated_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                created['id'],
                created['tenant_id'],
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
                json.dumps(created['notification_channels'], ensure_ascii=False),
                json.dumps(created['notification_group_names'], ensure_ascii=False),
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


def update_rule(rule_id: str, payload: dict[str, Any], tenant_id: str = 'tenant-default') -> dict[str, Any]:
    tenant_id = _tenant_id(tenant_id)
    conn = get_db_connection()
    try:
        existing_row = conn.execute('SELECT * FROM alert_rules WHERE id = ? AND tenant_id = ?', (rule_id, tenant_id)).fetchone()
        if not existing_row:
            raise ValueError('Alert rule not found')
        existing = _normalize_rule_row(existing_row)
        updated_fields = _validate_rule_payload(payload, existing, conn=conn, tenant_id=tenant_id)
        updated = {
            **existing,
            'tenant_id': tenant_id,
            **updated_fields,
            'updated_by': str(payload.get('updated_by') or existing.get('updated_by') or 'system').strip() or 'system',
            'updated_at': _utc_now_iso(),
        }
        updated['collection'] = get_alert_metric_collection(updated['metric_type'])
        conn.execute(
            '''
            UPDATE alert_rules
            SET name = ?, metric_type = ?, scope_type = ?, scope_match_mode = ?, scope_value = ?, severity = ?, threshold = ?, enabled = ?,
                aggregation_mode = ?, notification_repeat_window_seconds = ?, for_duration_seconds = ?,
                notification_channels_json = ?::jsonb, notification_group_names_json = ?::jsonb,
                notify_on_active = ?, notify_on_recovery = ?, notify_on_reopen_after_maintenance = ?,
                updated_by = ?, updated_at = ?
            WHERE id = ? AND tenant_id = ?
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
                json.dumps(updated['notification_channels'], ensure_ascii=False),
                json.dumps(updated['notification_group_names'], ensure_ascii=False),
                1 if updated['notify_on_active'] else 0,
                1 if updated['notify_on_recovery'] else 0,
                1 if updated['notify_on_reopen_after_maintenance'] else 0,
                updated['updated_by'],
                updated['updated_at'],
                rule_id,
                tenant_id,
            ),
        )
        if any(existing.get(key) != updated.get(key) for key in updated.keys() if key not in {'updated_at'}):
            _write_history(conn, updated)
        conn.commit()
        return updated
    finally:
        conn.close()


def delete_rule(rule_id: str, tenant_id: str = 'tenant-default') -> None:
    tenant_id = _tenant_id(tenant_id)
    conn = get_db_connection()
    try:
        deleted = conn.execute('DELETE FROM alert_rules WHERE id = ? AND tenant_id = ?', (rule_id, tenant_id)).rowcount
        if not deleted:
            raise ValueError('Alert rule not found')
        conn.commit()
    finally:
        conn.close()


def get_runtime_rules(tenant_id: str = 'tenant-default') -> list[dict[str, Any]]:
    return [rule for rule in list_rules(tenant_id=tenant_id) if rule['enabled']]


def _parse_scope_ip_values(scope_value: Any) -> list[str]:
    raw_value = str(scope_value or '').strip()
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        parsed = raw_value
    if isinstance(parsed, (list, tuple, set)):
        values = parsed
    elif isinstance(parsed, str):
        values = re.split(r'[,;\s]+', parsed)
    else:
        return []
    return list(dict.fromkeys(str(value or '').strip().lower() for value in values if str(value or '').strip()))


def _parse_scope_device_ids(value: Any) -> list[str]:
    try:
        raw = json.loads(str(value or ''))
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(str(device_id or '').strip() for device_id in raw if str(device_id or '').strip()))


def _tag_expression_has_conditions(expression: dict[str, Any], depth: int = 0) -> bool:
    if depth > 16 or not isinstance(expression, dict):
        return False
    tag_ids = expression.get('tag_ids')
    groups = expression.get('groups')
    return bool(
        (isinstance(tag_ids, list) and any(str(tag_id or '').strip() for tag_id in tag_ids))
        or (isinstance(groups, list) and any(
            _tag_expression_has_conditions(group, depth + 1) for group in groups
        ))
    )


def _tag_expression_matches(expression: Any, tag_ids: set[str], *, depth: int = 0, budget: list[int] | None = None) -> bool:
    if budget is None:
        budget = [0]
    budget[0] += 1
    if budget[0] > 4096 or depth > 16 or not isinstance(expression, dict):
        return False
    configured_ids = [str(tag_id).strip() for tag_id in expression.get('tag_ids', []) if str(tag_id or '').strip()] \
        if isinstance(expression.get('tag_ids'), list) else []
    child_groups = expression.get('groups')
    values = [tag_id in tag_ids for tag_id in configured_ids]
    if isinstance(child_groups, list):
        values.extend(
            _tag_expression_matches(child, tag_ids, depth=depth + 1, budget=budget)
            for child in child_groups
        )
    if not values:
        return False
    result = any(values) if str(expression.get('operator') or 'and').lower() == 'or' else all(values)
    return not result if expression.get('negated') is True else result


def _scope_matches(rule: dict[str, Any], context: dict[str, Any]) -> bool:
    scope_type = rule.get('scope_type') or 'global'
    scope_match_mode = str(rule.get('scope_match_mode') or 'exact').strip().lower() or 'exact'
    raw_scope_value = str(rule.get('scope_value') or '').strip()
    scope_value = raw_scope_value.lower()

    def match_value(candidate: str, expected_value: str = scope_value) -> bool:
        normalized = str(candidate or '').strip().lower()
        expected = str(expected_value or '').strip().lower()
        if not normalized or not expected:
            return False
        if scope_match_mode == 'contains':
            return expected in normalized
        if scope_match_mode == 'prefix':
            return normalized.startswith(expected)
        if scope_match_mode == 'glob':
            return fnmatch.fnmatch(normalized, expected)
        return normalized == expected

    if scope_type == 'global':
        return True
    if scope_type == 'site':
        return match_value(str(context.get('site') or ''))
    if scope_type == 'role':
        return match_value(str(context.get('role') or ''))
    if scope_type == 'device':
        device_candidates = [
            str(context.get('device_id') or ''),
            str(context.get('hostname') or ''),
            str(context.get('ip_address') or ''),
        ]
        return any(match_value(candidate) for candidate in device_candidates)
    if scope_type == 'devices':
        selected_device_ids = set(_parse_scope_device_ids(raw_scope_value))
        return bool(selected_device_ids) and str(context.get('device_id') or '').strip() in selected_device_ids
    if scope_type == 'ip':
        target_ips = set(_parse_scope_ip_values(raw_scope_value))
        return bool(target_ips) and str(context.get('ip_address') or '').strip().lower() in target_ips
    if scope_type == 'interface':
        return match_value(str(context.get('interface_name') or ''))
    if scope_type == 'composite':
        try:
            filters = json.loads(raw_scope_value)
        except (TypeError, ValueError):
            return False
        if not isinstance(filters, dict):
            return False
        fields = {
            'site': context.get('site'),
            'role': context.get('role'),
            'category': context.get('category') or context.get('device_category'),
            'platform': context.get('platform'),
            'interface': context.get('interface_name'),
        }
        configured = [
            (field, str(filters.get(field) or '').strip())
            for field in ('site', 'role', 'category', 'platform', 'interface')
            if str(filters.get(field) or '').strip()
        ]
        return bool(configured) and all(
            match_value(str(fields[field] or ''), value) for field, value in configured
        )
    if scope_type == 'tag':
        assigned_tag_ids = context.get('tag_ids')
        if not isinstance(assigned_tag_ids, (list, tuple, set, frozenset)):
            return False
        try:
            tag_filter = json.loads(raw_scope_value)
        except (TypeError, ValueError):
            return False
        expression = tag_filter.get('expression') if isinstance(tag_filter, dict) else None
        if not _tag_expression_has_conditions(expression or {}):
            return False
        return _tag_expression_matches(expression, {str(tag_id) for tag_id in assigned_tag_ids})
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


def list_rule_history(limit: int = 20, rule_id: str | None = None, tenant_id: str = 'tenant-default') -> list[dict[str, Any]]:
    tenant_id = _tenant_id(tenant_id)
    conn = get_db_connection()
    try:
        if rule_id:
            rows = conn.execute(
                '''
                SELECT id, settings_id, rule_id, tenant_id, snapshot_json, changed_by, created_at
                FROM alert_rule_history
                WHERE rule_id = ? AND tenant_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                ''',
                (rule_id, tenant_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                '''
                SELECT id, settings_id, rule_id, tenant_id, snapshot_json, changed_by, created_at
                FROM alert_rule_history
                WHERE tenant_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                ''',
                (tenant_id, limit),
            ).fetchall()
        return [_history_item_from_row(row) for row in rows]
    finally:
        conn.close()


def list_notification_groups(tenant_id: str = 'tenant-default') -> list[dict[str, Any]]:
    """Return active user groups visible to one tenant, without user details."""
    tenant_id = _tenant_id(tenant_id)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT group_name AS name, COUNT(*) AS member_count
            FROM users
            WHERE tenant_id = ? AND status = 'active' AND COALESCE(group_name, '') <> ''
            GROUP BY group_name
            ORDER BY group_name ASC
            """,
            (tenant_id,),
        ).fetchall()
        return [
            {'name': str(row['name']), 'member_count': int(row['member_count'])}
            for row in rows
        ]
    finally:
        conn.close()


def get_scope_catalog(
    tenant_id: str = 'tenant-default',
    *,
    search: str = '',
    device_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return tenant filter options and a bounded CMDB device search result."""
    tenant_id = _tenant_id(tenant_id)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''
            SELECT site, role, category, platform, COUNT(*) AS device_count
            FROM (
                SELECT
                    d.id,
                    COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), NULLIF(d.site, ''), '') AS site,
                    COALESCE(NULLIF(TRIM(d.role), ''), '') AS role,
                    COALESCE(
                        NULLIF(TRIM(d.device_category), ''),
                        CASE WHEN LOWER(COALESCE(d.role, '')) LIKE '%server%' THEN 'Server' ELSE 'Network' END
                    ) AS category,
                    COALESCE(NULLIF(TRIM(d.platform), ''), '') AS platform
                FROM devices d
                LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
                WHERE COALESCE(d.tenant_id, 'tenant-default') = ?
            ) scoped_devices
            GROUP BY site, role, category, platform
            ORDER BY site, role, category, platform
            ''',
            (tenant_id,),
        ).fetchall()
        counts: dict[str, dict[str, int]] = {
            'sites': {}, 'roles': {}, 'categories': {}, 'platforms': {},
        }
        for row in rows:
            device_count = int(row['device_count'] or 0)
            for key in counts:
                value = str(row['category' if key == 'categories' else key[:-1]] or '').strip()
                if key == 'sites' and re.fullmatch(r'site-[a-z0-9]+', value, flags=re.IGNORECASE):
                    continue
                if value:
                    counts[key][value] = counts[key].get(value, 0) + device_count

        def options(key: str) -> list[dict[str, Any]]:
            return [
                {'value': value, 'count': count}
                for value, count in sorted(counts[key].items(), key=lambda item: (-item[1], item[0].casefold()))
            ]

        normalized_device_ids = list(dict.fromkeys(
            str(device_id or '').strip() for device_id in (device_ids or []) if str(device_id or '').strip()
        ))
        if len(normalized_device_ids) > 200:
            raise ValueError('at most 200 execution machine IDs can be resolved at once')

        device_items: list[dict[str, Any]] = []
        device_total = 0
        missing_device_ids: list[str] = []
        device_where = "COALESCE(d.tenant_id, 'tenant-default') = ?"
        device_params: list[Any] = [tenant_id]
        if normalized_device_ids:
            placeholders = ','.join('?' for _ in normalized_device_ids)
            device_where += f' AND d.id IN ({placeholders})'
            device_params.extend(normalized_device_ids)
        elif str(search or '').strip():
            query = f"%{str(search).strip().lower()}%"
            searchable_fields = (
                "d.id", "d.hostname", "d.ip_address", "d.sn", "pa.hostname",
                "pa.management_ip", "pa.business_ip", "pa.asset_tag", "pa.serial_number",
            )
            device_where += ' AND (' + ' OR '.join(
                f"LOWER(COALESCE({field}, '')) LIKE ?" for field in searchable_fields
            ) + ')'
            device_params.extend([query] * len(searchable_fields))

        if normalized_device_ids or str(search or '').strip():
            device_total_row = conn.execute(
                f'''
                SELECT COUNT(*) AS count
                FROM devices d
                LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                WHERE {device_where}
                ''',
                device_params,
            ).fetchone()
            device_total = int(device_total_row['count'] or 0) if device_total_row else 0
            result_limit = 200 if normalized_device_ids else 50
            device_rows = conn.execute(
                f'''
                SELECT
                    d.id,
                    COALESCE(NULLIF(pa.hostname, ''), NULLIF(d.hostname, ''), d.id) AS hostname,
                    COALESCE(NULLIF(pa.management_ip, ''), NULLIF(d.ip_address, ''), '') AS management_ip,
                    COALESCE(NULLIF(d.ip_address, ''), NULLIF(pa.management_ip, ''), '') AS ip_address,
                    COALESCE(NULLIF(pa.serial_number, ''), NULLIF(d.sn, ''), '') AS serial_number,
                    COALESCE(NULLIF(pa.asset_tag, ''), '') AS asset_tag,
                    COALESCE(NULLIF(d.platform, ''), '') AS platform,
                    COALESCE(NULLIF(d.role, ''), '') AS role,
                    COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), NULLIF(d.site, ''), '') AS site,
                    COALESCE(NULLIF(d.device_category, ''), '') AS category,
                    COALESCE(NULLIF(d.status, ''), '') AS status
                FROM devices d
                LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
                WHERE {device_where}
                ORDER BY COALESCE(NULLIF(pa.hostname, ''), NULLIF(d.hostname, ''), d.id), d.id
                LIMIT ?
                ''',
                [*device_params, result_limit],
            ).fetchall()
            device_items = [dict(row) for row in device_rows]
            if normalized_device_ids:
                found_ids = {str(item.get('id') or '') for item in device_items}
                missing_device_ids = [device_id for device_id in normalized_device_ids if device_id not in found_ids]

        return {
            'sites': options('sites'),
            'roles': options('roles'),
            'categories': options('categories'),
            'platforms': options('platforms'),
            'devices': device_items,
            'device_total': device_total,
            'missing_device_ids': missing_device_ids,
        }
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
