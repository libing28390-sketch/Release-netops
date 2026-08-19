import json
from datetime import datetime, timedelta, timezone
from typing import Any

from database import get_db_connection, fetch_interface_data
from services.collection_status_service import COLLECTOR_STALE_SECONDS


DEVICE_HEALTH_RETENTION_DAYS = 30

# 服务器/Linux 主机平台标识（与 inspection_service 保持一致）
# 这些平台不具备 fan/psu/interface 等网络设备专有指标
_SERVER_PLATFORMS = {'linux', 'ubuntu', 'centos', 'debian', 'redhat'}
DEVICE_HEALTH_SELECT = (
    'd.id, d.hostname, d.ip_address, d.platform, d.status, d.compliance, d.role, '
    "COALESCE(NULLIF(s.site_name, ''), CASE WHEN SUBSTR(COALESCE(d.site, ''), 1, 5) = 'site-' THEN '' ELSE COALESCE(d.site, '') END, '') AS site, "
    'd.cpu_usage, d.memory_usage, d.temp, d.fan_status, d.psu_status, d.device_category'
)


HEALTH_STATUS_RANK = {
    'critical': 0,
    'warning': 1,
    'unknown': 2,
    'healthy': 3,
}

_COLLECTION_SUCCESS_STATUSES = {'success', 'no_neighbors'}
_EXPECTED_COLLECTORS = ('reachability', 'snmp_metrics', 'snmp_interfaces')


def normalize_hardware_status(value: Any) -> bool | None:
    """Normalize legacy hardware status labels to the public boolean contract."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().casefold()
    if normalized in {'1', 'true', 'ok', 'normal', 'redundant', 'single', 'up', 'running', 'ready'}:
        return True
    if normalized in {'0', 'false', 'fail', 'failed', 'warning', 'error', 'down', 'offline', 'alarm'}:
        return False
    return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_json_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    except Exception:
        return []
    return []


def _parse_json_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, '')]
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item not in (None, '')]
    except Exception:
        return []
    return []


def _age_seconds(value: Any) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    except (TypeError, ValueError):
        return None


def _build_collection_stats(conn, device_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Build a compact, device-level view of collector freshness.

    Collection state is deliberately kept separate from health state.  A
    device can be reachable while its SNMP metrics are stale, and a device
    can be offline without having any recent health sample.  Keeping this
    distinction in the API prevents the UI from presenting missing telemetry
    as a health score of zero.
    """
    result = {
        device_id: {
            'collection_status': 'unknown',
            'data_confidence': 0,
            'health_metrics_available': False,
            'collection_failures': [],
            'collection_last_success_at': None,
        }
        for device_id in device_ids
    }
    if not device_ids:
        return result

    placeholders = ', '.join('?' for _ in device_ids)
    try:
        rows = conn.execute(
            f'''
            SELECT device_id, collector, status, last_success_at,
                   coverage_total, coverage_supported, error_code, error_message
            FROM device_collection_status
            WHERE device_id IN ({placeholders})
            ''',
            tuple(device_ids),
        ).fetchall()
    except Exception:
        # Older installations may not have the optional collector table yet.
        # The caller still receives an explicit unknown state.
        try:
            conn.rollback()
        except Exception:
            pass
        return result

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        grouped.setdefault(str(item.get('device_id') or ''), []).append(item)

    for device_id, items in grouped.items():
        expected_items = {str(item.get('collector') or ''): item for item in items}
        effective: dict[str, str] = {}
        failures: list[dict[str, str]] = []
        healthy_expected = 0
        health_metrics_available = False
        latest_success_at: str | None = None

        for collector in _EXPECTED_COLLECTORS:
            item = expected_items.get(collector)
            if not item:
                effective[collector] = 'unknown'
                continue

            raw_status = str(item.get('status') or 'unknown').lower()
            effective_status = raw_status
            if raw_status in _COLLECTION_SUCCESS_STATUSES:
                age = _age_seconds(item.get('last_success_at'))
                threshold = COLLECTOR_STALE_SECONDS.get(collector)
                if threshold and (age is None or age > threshold):
                    effective_status = 'stale'
                else:
                    effective_status = 'healthy'
                    if item.get('last_success_at') and (
                        latest_success_at is None or str(item['last_success_at']) > latest_success_at
                    ):
                        latest_success_at = str(item['last_success_at'])
            elif raw_status in {'failed', 'not_configured', 'stale'}:
                effective_status = raw_status
            else:
                effective_status = 'unknown'

            effective[collector] = effective_status
            if effective_status == 'healthy':
                healthy_expected += 1
            if effective_status in {'failed', 'not_configured', 'stale'}:
                failures.append({
                    'collector': collector,
                    'status': effective_status,
                    'error_code': str(item.get('error_code') or ''),
                    'message': str(item.get('error_message') or ''),
                })

            if collector in {'snmp_metrics', 'snmp_interfaces'} and effective_status == 'healthy':
                coverage_supported = int(item.get('coverage_supported') or 0)
                coverage_total = int(item.get('coverage_total') or 0)
                if collector == 'snmp_interfaces' or coverage_supported > 0 or coverage_total > 0:
                    health_metrics_available = True

        statuses = list(effective.values())
        has_failure = any(value in {'failed', 'not_configured'} for value in statuses)
        has_stale = 'stale' in statuses
        has_healthy = 'healthy' in statuses
        if not any(value != 'unknown' for value in statuses):
            collection_status = 'unknown'
        elif has_failure and has_healthy:
            collection_status = 'partial_failed'
        elif has_stale and has_healthy:
            collection_status = 'partial_failed'
        elif has_failure:
            collection_status = 'failed'
        elif has_stale:
            collection_status = 'stale'
        elif healthy_expected == len(_EXPECTED_COLLECTORS):
            collection_status = 'healthy'
        else:
            collection_status = 'partial'

        result[device_id] = {
            'collection_status': collection_status,
            'data_confidence': round((healthy_expected / len(_EXPECTED_COLLECTORS)) * 100),
            'health_metrics_available': health_metrics_available,
            'collection_failures': failures,
            'collection_last_success_at': latest_success_at,
        }
    return result


def _build_open_alert_stats(conn, device_ids: list[str]) -> dict[str, dict[str, int]]:
    if not device_ids:
        return {}

    placeholders = ', '.join('?' for _ in device_ids)
    rows = conn.execute(
        f'''
        SELECT
            device_id,
            COUNT(*) AS open_alert_count,
            SUM(CASE WHEN LOWER(COALESCE(severity, '')) = 'critical' THEN 1 ELSE 0 END) AS critical_open_alerts,
            SUM(CASE WHEN LOWER(COALESCE(severity, '')) = 'major' THEN 1 ELSE 0 END) AS major_open_alerts,
            SUM(CASE WHEN LOWER(COALESCE(severity, '')) NOT IN ('critical', 'major') THEN 1 ELSE 0 END) AS warning_open_alerts
        FROM alert_events
        WHERE resolved_at IS NULL
          AND COALESCE(workflow_status, 'open') != 'suppressed'
          AND device_id IN ({placeholders})
        GROUP BY device_id
        ''',
        tuple(device_ids),
    ).fetchall()

    result: dict[str, dict[str, int]] = {}
    for row in rows:
        device_id = str(row['device_id'] or '')
        if not device_id:
            continue
        result[device_id] = {
            'open_alert_count': int(row['open_alert_count'] or 0),
            'critical_open_alerts': int(row['critical_open_alerts'] or 0),
            'major_open_alerts': int(row['major_open_alerts'] or 0),
            'warning_open_alerts': int(row['warning_open_alerts'] or 0),
        }
    return result


def evaluate_device_health(
    device: dict[str, Any],
    alert_stats: dict[str, int] | None = None,
    collection_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    alert_stats = alert_stats or {}
    collection_data = collection_data or {}
    platform = str(device.get('platform') or '').lower()
    category = str(device.get('device_category') or '').lower()
    is_server = platform in _SERVER_PLATFORMS or 'server' in category
    status = str(device.get('status') or 'unknown').lower()
    availability_status = status if status in {'online', 'offline'} else 'unknown'
    collection_status = str(collection_data.get('collection_status') or 'unknown')
    data_confidence = max(0, min(100, int(collection_data.get('data_confidence') or 0)))
    health_metrics_available = bool(collection_data.get('health_metrics_available'))
    compliance = str(device.get('compliance') or 'unknown').lower()
    fan_raw = device.get('fan_status')
    psu_raw = device.get('psu_status')
    fan_status = str(fan_raw).lower() if fan_raw is not None else ''
    psu_status = str(psu_raw).lower() if psu_raw is not None else ''
    interfaces = _parse_json_list(device.get('interface_data')) if not is_server else []

    reasons: list[tuple[str, str, int]] = []
    score = 100
    forced_status: str | None = None

    def penalize(message: str, severity: str, points: int) -> None:
        nonlocal score, forced_status
        score = max(0, score - points)
        reasons.append((severity, message, points))
        if severity == 'critical':
            forced_status = 'critical'
        elif severity == 'warning' and forced_status != 'critical':
            forced_status = 'warning'

    # Availability is intentionally not a health penalty.  An unreachable
    # device belongs in the availability dimension; without a recent health
    # sample its health score must remain unavailable rather than becoming 0.
    if health_metrics_available:
        cpu_usage = _as_float(device.get('cpu_usage'), 0.0)
        memory_usage = _as_float(device.get('memory_usage'), 0.0)
        temp = _as_float(device.get('temp'), 0.0)

        # Fan/PSU checks only apply to network devices (servers don't report these)
        if not is_server:
            if fan_raw is False or fan_status in {'false', '0', 'fail', 'failed', 'error', 'down'}:
                penalize('Fan status indicates a hardware failure', 'critical', 35)

            if psu_raw is False or psu_status in {'false', '0', 'fail', 'failed', 'error', 'down'}:
                penalize('Power supply status indicates a failure', 'critical', 35)
            elif psu_status == 'single':
                penalize('Power supply lost redundancy', 'warning', 12)

        if cpu_usage >= 90:
            penalize(f'CPU usage is {cpu_usage:.0f}%', 'critical', 25)
        elif cpu_usage >= 80:
            penalize(f'CPU usage is elevated at {cpu_usage:.0f}%', 'warning', 14)

        if memory_usage >= 90:
            penalize(f'Memory usage is {memory_usage:.0f}%', 'critical', 25)
        elif memory_usage >= 80:
            penalize(f'Memory usage is elevated at {memory_usage:.0f}%', 'warning', 14)

        # Temperature checks: skip for servers (usually not reported via SNMP/DB)
        if not is_server:
            if temp >= 75:
                penalize(f'Temperature is high at {temp:.0f}C', 'critical', 20)
            elif temp >= 60:
                penalize(f'Temperature is elevated at {temp:.0f}C', 'warning', 10)

    down_interfaces = 0
    flapping_interfaces = 0
    high_util_interfaces = 0
    error_interfaces = 0
    for interface in interfaces:
        intf_status = str(interface.get('status') or '').lower()
        if intf_status == 'down':
            down_interfaces += 1
        if bool(interface.get('flapping')):
            flapping_interfaces += 1
        max_util = max(_as_float(interface.get('bw_in_pct')), _as_float(interface.get('bw_out_pct')))
        if max_util >= 85:
            high_util_interfaces += 1
        # Keep raw counters visible, but do not lower the device health score
        # for the known Comware agent/view pattern where every physical port
        # exposes the same non-zero error tuple.  The collector marks that
        # condition explicitly as suspicious_uniform.
        if interface.get('counter_quality') != 'suspicious_uniform' and (
            _as_float(interface.get('in_errors'))
            + _as_float(interface.get('out_errors'))
            + _as_float(interface.get('in_discards'))
            + _as_float(interface.get('out_discards'))
        ) > 0:
            error_interfaces += 1

    # down_interfaces is informational only — unused ports being down is normal

    if flapping_interfaces > 0:
        penalty = min(18, 6 + flapping_interfaces * 3)
        penalize(f'{flapping_interfaces} interface(s) are flapping', 'warning', penalty)

    if high_util_interfaces > 0:
        penalty = min(15, 4 + high_util_interfaces * 2)
        penalize(f'{high_util_interfaces} interface(s) exceed 85% utilization', 'warning', penalty)

    if error_interfaces > 0:
        penalty = min(16, 4 + error_interfaces * 2)
        penalize(f'{error_interfaces} interface(s) report errors or discards', 'warning', penalty)

    critical_open_alerts = int(alert_stats.get('critical_open_alerts') or 0)
    major_open_alerts = int(alert_stats.get('major_open_alerts') or 0)
    warning_open_alerts = int(alert_stats.get('warning_open_alerts') or 0)
    open_alert_count = int(alert_stats.get('open_alert_count') or 0)

    if critical_open_alerts > 0:
        penalty = min(36, 18 + critical_open_alerts * 6)
        penalize(f'{critical_open_alerts} critical alert(s) are still open', 'critical', penalty)
    if major_open_alerts > 0:
        penalty = min(22, 8 + major_open_alerts * 4)
        penalize(f'{major_open_alerts} major alert(s) are still open', 'warning', penalty)
    if warning_open_alerts > 0:
        penalty = min(10, 3 + warning_open_alerts)
        penalize(f'{warning_open_alerts} minor alert(s) remain active', 'warning', penalty)

    if compliance == 'non-compliant' and (health_metrics_available or interfaces):
        penalize('设备合规检查未通过', 'warning', 12)
    health_evaluable = health_metrics_available or bool(interfaces) or open_alert_count > 0
    if not health_evaluable:
        health_status = 'unknown'
        health_score = None
        ordered_reasons = []
        if collection_status in {'failed', 'stale', 'partial_failed'}:
            ordered_reasons.append(f'Collector status is {collection_status}')
        ordered_reasons.append('No recent telemetry is available for health evaluation')
        ordered_findings = [{'severity': 'info', 'message': message} for message in ordered_reasons]
        summary = ordered_reasons[0]
    else:
        if forced_status == 'critical' or score < 50:
            health_status = 'critical'
        elif forced_status == 'warning' or score < 85:
            health_status = 'warning'
        else:
            health_status = 'healthy'

        ordered_reasons = [message for _severity, message, _points in sorted(reasons, key=lambda item: (0 if item[0] == 'critical' else 1, -item[2], item[1]))]
        ordered_findings = [{'severity': severity, 'message': message} for severity, message, _points in sorted(reasons, key=lambda item: (0 if item[0] == 'critical' else 1, -item[2], item[1]))]
        summary = ordered_reasons[0] if ordered_reasons else 'No active health issues detected'
        health_score = max(0, min(100, int(round(score))))

    if not data_confidence and health_evaluable:
        data_confidence = 50 if open_alert_count > 0 else 25

    return {
        'availability_status': availability_status,
        'collection_status': collection_status,
        'collection_last_success_at': collection_data.get('collection_last_success_at'),
        'collection_failures': collection_data.get('collection_failures') or [],
        'data_confidence': data_confidence,
        'health_score_available': health_evaluable,
        'health_status': health_status,
        'health_score': health_score,
        'health_summary': summary,
        'health_reasons': ordered_reasons,
        'health_findings': ordered_findings,
        'open_alert_count': open_alert_count,
        'critical_open_alerts': critical_open_alerts,
        'major_open_alerts': major_open_alerts,
        'warning_open_alerts': warning_open_alerts,
        'interface_down_count': down_interfaces,
        'interface_flap_count': flapping_interfaces,
        'high_util_interface_count': high_util_interfaces,
        'interface_error_count': error_interfaces,
    }


def annotate_devices_with_health(conn, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_devices = []
    for device in devices:
        item = dict(device)
        for status_key in ('fan_status', 'psu_status'):
            if status_key in item:
                item[status_key] = normalize_hardware_status(item.get(status_key))
        normalized_devices.append(item)
    device_ids = [str(device.get('id') or '') for device in normalized_devices if device.get('id')]
    alert_stats_map = _build_open_alert_stats(conn, device_ids)
    collection_stats_map = _build_collection_stats(conn, device_ids)
    enriched: list[dict[str, Any]] = []
    for device in normalized_devices:
        device_id = str(device.get('id') or '')
        health = evaluate_device_health(
            device,
            alert_stats_map.get(device_id, {}),
            collection_stats_map.get(device_id, {}),
        )
        enriched.append({**device, **health})
    return enriched


def build_health_overview(devices: list[dict[str, Any]], top_n: int = 8) -> dict[str, Any]:
    counts = {
        'healthy': 0,
        'warning': 0,
        'critical': 0,
        'unknown': 0,
    }
    scores: list[float] = []
    confidence_values: list[int] = []
    availability_counts = {'online': 0, 'offline': 0, 'unknown': 0}
    collection_counts: dict[str, int] = {}
    health_evaluable_count = 0
    collection_timestamps: list[str] = []

    for device in devices:
        health_status = str(device.get('health_status') or 'unknown')
        counts[health_status] = counts.get(health_status, 0) + 1
        score = device.get('health_score')
        score_available = device.get('health_score_available', score is not None)
        if score_available and score is not None:
            scores.append(float(score))
            health_evaluable_count += 1
        availability = str(device.get('availability_status') or 'unknown')
        availability_counts[availability] = availability_counts.get(availability, 0) + 1
        collection_status = str(device.get('collection_status') or 'unknown')
        collection_counts[collection_status] = collection_counts.get(collection_status, 0) + 1
        if device.get('collection_last_success_at'):
            collection_timestamps.append(str(device['collection_last_success_at']))
        confidence_values.append(max(0, min(100, int(device.get('data_confidence') or 0))))

    average_score = round(sum(scores) / len(scores), 1) if scores else None
    def impact_priority(device: dict[str, Any]) -> tuple[int, int]:
        role = str(device.get('role') or '').lower()
        role_weight = 5 if any(token in role for token in ('core', 'aggregation', 'firewall', 'router', 'load_balancer', '出口')) else 3 if any(token in role for token in ('distribution', 'gateway', 'border')) else 1
        alert_weight = (
            int(device.get('critical_open_alerts') or 0) * 5
            + int(device.get('major_open_alerts') or 0) * 3
            + int(device.get('warning_open_alerts') or 0)
        )
        return role_weight * 20 + alert_weight * 10 + int(device.get('open_alert_count') or 0), role_weight

    risky_devices = sorted(
        devices,
        key=lambda device: (
            HEALTH_STATUS_RANK.get(str(device.get('health_status') or 'unknown'), 99),
            -impact_priority(device)[0],
            int(device.get('health_score')) if device.get('health_score') is not None else 101,
            str(device.get('hostname') or ''),
        ),
    )[:top_n]

    return {
        'total_devices': len(devices),
        'average_score': average_score,
        **counts,
        'top_risky_devices': [
            {
                'id': device.get('id'),
                'hostname': device.get('hostname'),
                'ip_address': device.get('ip_address'),
                'platform': device.get('platform'),
                'role': device.get('role'),
                'site': device.get('site'),
                'status': device.get('status'),
                'availability_status': device.get('availability_status'),
                'collection_status': device.get('collection_status'),
                'collection_last_success_at': device.get('collection_last_success_at'),
                'collection_failures': device.get('collection_failures') or [],
                'data_confidence': device.get('data_confidence'),
                'health_score_available': device.get('health_score_available'),
                'health_status': device.get('health_status'),
                'health_score': device.get('health_score'),
                'health_summary': device.get('health_summary'),
                'open_alert_count': device.get('open_alert_count'),
                'critical_open_alerts': device.get('critical_open_alerts'),
                'major_open_alerts': device.get('major_open_alerts'),
                'warning_open_alerts': device.get('warning_open_alerts'),
                'impact_priority': impact_priority(device)[0],
                'impact_role_weight': impact_priority(device)[1],
                'health_reasons': device.get('health_reasons') or [],
            }
            for device in risky_devices
        ],
        'health_evaluable_count': health_evaluable_count,
        'health_score_available': bool(scores),
        'availability': availability_counts,
        'online_devices': availability_counts.get('online', 0),
        'offline_devices': availability_counts.get('offline', 0),
        'unknown_availability_devices': availability_counts.get('unknown', 0),
        'collection': collection_counts,
        'collection_anomaly_devices': sum(collection_counts.get(key, 0) for key in ('failed', 'stale', 'partial_failed')),
        'last_collection_at': max(collection_timestamps) if collection_timestamps else None,
        'data_confidence_avg': round(sum(confidence_values) / len(confidence_values), 1) if confidence_values else None,
    }


def load_devices_for_health(conn, device_id: str | None = None) -> list[dict[str, Any]]:
    if device_id:
        rows = conn.execute(
            f'SELECT {DEVICE_HEALTH_SELECT} FROM devices d LEFT JOIN sites s ON s.id = d.site_id WHERE d.id = ? ORDER BY d.hostname ASC',
            (device_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            f'SELECT {DEVICE_HEALTH_SELECT} FROM devices d LEFT JOIN sites s ON s.id = d.site_id ORDER BY d.hostname ASC'
        ).fetchall()
    res = []
    for row in rows:
        item = dict(row)
        item['interface_data'] = fetch_interface_data(conn, item['id'])
        res.append(item)
    return res


def record_device_health_snapshot() -> dict[str, Any]:
    conn = get_db_connection()
    try:
        devices = annotate_devices_with_health(conn, load_devices_for_health(conn))
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if devices:
            conn.executemany(
                '''
                INSERT INTO device_health_samples (
                    ts, device_id, hostname, status, health_status, health_score,
                    open_alert_count, critical_open_alerts, major_open_alerts, warning_open_alerts,
                    interface_down_count, interface_flap_count, high_util_interface_count,
                    interface_error_count, health_summary, health_reasons_json,
                    health_score_available, availability_status, collection_status, data_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (ts, device_id) DO UPDATE SET
                  hostname=excluded.hostname, status=excluded.status,
                  health_status=excluded.health_status, health_score=excluded.health_score,
                  open_alert_count=excluded.open_alert_count,
                  critical_open_alerts=excluded.critical_open_alerts,
                  major_open_alerts=excluded.major_open_alerts,
                  warning_open_alerts=excluded.warning_open_alerts,
                  interface_down_count=excluded.interface_down_count,
                  interface_flap_count=excluded.interface_flap_count,
                  high_util_interface_count=excluded.high_util_interface_count,
                  interface_error_count=excluded.interface_error_count,
                  health_summary=excluded.health_summary,
                  health_reasons_json=excluded.health_reasons_json,
                  health_score_available=excluded.health_score_available,
                  availability_status=excluded.availability_status,
                  collection_status=excluded.collection_status,
                  data_confidence=excluded.data_confidence
                ''',
                [(
                    ts,
                    str(device.get('id') or ''),
                    device.get('hostname'),
                    device.get('status'),
                    device.get('health_status'),
                    int(device.get('health_score') or 0),
                    int(device.get('open_alert_count') or 0),
                    int(device.get('critical_open_alerts') or 0),
                    int(device.get('major_open_alerts') or 0),
                    int(device.get('warning_open_alerts') or 0),
                    int(device.get('interface_down_count') or 0),
                    int(device.get('interface_flap_count') or 0),
                    int(device.get('high_util_interface_count') or 0),
                    int(device.get('interface_error_count') or 0),
                    device.get('health_summary') or '',
                    json.dumps(device.get('health_reasons') or [], ensure_ascii=False),
                    1 if device.get('health_score_available') else 0,
                    device.get('availability_status') or 'unknown',
                    device.get('collection_status') or 'unknown',
                    int(device.get('data_confidence') or 0),
                ) for device in devices],
            )
        cutoff = (datetime.now(timezone.utc) - timedelta(days=DEVICE_HEALTH_RETENTION_DAYS)).replace(microsecond=0).isoformat()
        conn.execute('DELETE FROM device_health_samples WHERE ts < ?', (cutoff,))
        conn.commit()
        return {
            'ts': ts,
            'sample_count': len(devices),
        }
    finally:
        conn.close()


def fetch_device_health_history(conn, range_hours: int = 24) -> dict[str, Any]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, range_hours))).replace(microsecond=0).isoformat()
    rows = conn.execute(
        '''
        SELECT
            ts,
            ROUND(AVG(CASE WHEN health_score_available = 1 THEN health_score END), 1) AS average_score,
            COUNT(*) AS total_devices,
            SUM(CASE WHEN health_status = 'healthy' THEN 1 ELSE 0 END) AS healthy,
            SUM(CASE WHEN health_status = 'warning' THEN 1 ELSE 0 END) AS warning,
            SUM(CASE WHEN health_status = 'critical' THEN 1 ELSE 0 END) AS critical,
            SUM(CASE WHEN health_status = 'unknown' THEN 1 ELSE 0 END) AS unknown,
            SUM(CASE WHEN availability_status = 'online' THEN 1 ELSE 0 END) AS online_devices,
            SUM(CASE WHEN collection_status = 'healthy' THEN 1 ELSE 0 END) AS collection_healthy_devices,
            SUM(CASE WHEN collection_status IN ('failed', 'partial_failed', 'stale', 'unconfigured') THEN 1 ELSE 0 END) AS collection_anomaly_devices,
            COALESCE(SUM(open_alert_count), 0) AS open_alerts,
            COALESCE(SUM(critical_open_alerts), 0) AS critical_open_alerts
        FROM device_health_samples
        WHERE ts >= ?
        GROUP BY ts
        ORDER BY ts ASC
        ''',
        (cutoff,),
    ).fetchall()
    alert_rows = conn.execute(
        "SELECT created_at, resolved_at FROM alert_events WHERE created_at >= ? OR resolved_at >= ?",
        (cutoff, cutoff),
    ).fetchall()
    new_alerts = 0
    recovered_alerts = 0
    mttr_seconds: list[float] = []
    cutoff_dt = datetime.fromisoformat(cutoff.replace('Z', '+00:00'))
    for alert_row in alert_rows:
        created_raw = alert_row['created_at']
        resolved_raw = alert_row['resolved_at']
        try:
            created_dt = datetime.fromisoformat(str(created_raw).replace('Z', '+00:00'))
        except (TypeError, ValueError):
            continue
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        if created_dt >= cutoff_dt:
            new_alerts += 1
        if not resolved_raw:
            continue
        try:
            resolved_dt = datetime.fromisoformat(str(resolved_raw).replace('Z', '+00:00'))
        except (TypeError, ValueError):
            continue
        if resolved_dt.tzinfo is None:
            resolved_dt = resolved_dt.replace(tzinfo=timezone.utc)
        if resolved_dt >= cutoff_dt:
            recovered_alerts += 1
            if resolved_dt >= created_dt:
                mttr_seconds.append((resolved_dt - created_dt).total_seconds())
    avg_mttr_minutes = round(sum(mttr_seconds) / len(mttr_seconds) / 60, 1) if mttr_seconds else None
    return {
        'range_hours': range_hours,
        'sample_count': len(rows),
        'new_alerts': new_alerts,
        'recovered_alerts': recovered_alerts,
        'avg_mttr_minutes': avg_mttr_minutes,
        'series': [
            {
                **dict(row),
                'online_rate': round((int(row['online_devices'] or 0) / int(row['total_devices'] or 1)) * 100, 1),
                'collection_success_rate': round((int(row['collection_healthy_devices'] or 0) / int(row['total_devices'] or 1)) * 100, 1),
            }
            for row in rows
        ],
    }


def fetch_device_health_trend(conn, device_id: str, range_hours: int = 24) -> dict[str, Any]:
    device_row = conn.execute(
        "SELECT d.id, d.hostname, d.ip_address, d.platform, d.role, COALESCE(NULLIF(s.site_name, ''), CASE WHEN SUBSTR(COALESCE(d.site, ''), 1, 5) = 'site-' THEN '' ELSE COALESCE(d.site, '') END, '') AS site FROM devices d LEFT JOIN sites s ON s.id = d.site_id WHERE d.id = ?",
        (device_id,),
    ).fetchone()
    if not device_row:
        return {
            'device': None,
            'range_hours': range_hours,
            'sample_count': 0,
            'series': [],
        }

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, range_hours))).replace(microsecond=0).isoformat()
    rows = conn.execute(
        '''
        SELECT
            ts,
            status,
            availability_status,
            collection_status,
            data_confidence,
            health_score_available,
            health_status,
            health_score,
            open_alert_count,
            critical_open_alerts,
            major_open_alerts,
            warning_open_alerts,
            interface_down_count,
            interface_flap_count,
            high_util_interface_count,
            interface_error_count,
            health_summary,
            health_reasons_json
        FROM device_health_samples
        WHERE device_id = ? AND ts >= ?
        ORDER BY ts ASC
        ''',
        (device_id, cutoff),
    ).fetchall()
    series = []
    for row in rows:
        point = dict(row)
        point['health_reasons'] = _parse_json_strings(point.pop('health_reasons_json', None))
        series.append(point)
    return {
        'device': dict(device_row),
        'range_hours': range_hours,
        'sample_count': len(rows),
        'series': series,
    }
