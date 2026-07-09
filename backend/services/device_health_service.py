import json
from datetime import datetime, timedelta, timezone
from typing import Any

from database import get_db_connection, fetch_interface_data


DEVICE_HEALTH_RETENTION_DAYS = 30

# 服务器/Linux 主机平台标识（与 inspection_service 保持一致）
# 这些平台不具备 fan/psu/interface 等网络设备专有指标
_SERVER_PLATFORMS = {'linux', 'ubuntu', 'centos', 'debian', 'redhat'}
DEVICE_HEALTH_SELECT = (
    'id, hostname, ip_address, platform, status, compliance, role, site, '
    'cpu_usage, memory_usage, temp, fan_status, psu_status'
)


HEALTH_STATUS_RANK = {
    'critical': 0,
    'warning': 1,
    'unknown': 2,
    'healthy': 3,
}


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


def evaluate_device_health(device: dict[str, Any], alert_stats: dict[str, int] | None = None) -> dict[str, Any]:
    alert_stats = alert_stats or {}
    platform = str(device.get('platform') or '').lower()
    category = str(device.get('device_category') or '').lower()
    is_server = platform in _SERVER_PLATFORMS or 'server' in category
    status = str(device.get('status') or 'unknown').lower()
    compliance = str(device.get('compliance') or 'unknown').lower()
    cpu_usage = _as_float(device.get('cpu_usage'), 0.0)
    memory_usage = _as_float(device.get('memory_usage'), 0.0)
    temp = _as_float(device.get('temp'), 0.0)
    fan_status = str(device.get('fan_status') or '').lower()
    psu_status = str(device.get('psu_status') or '').lower()
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

    if status == 'offline':
        penalize('Device is offline or unreachable', 'critical', 85)
    elif status == 'pending':
        penalize('Device is pending validation or onboarding', 'warning', 25)

    # Fan/PSU checks only apply to network devices (servers don't report these)
    if not is_server:
        if fan_status == 'fail':
            penalize('Fan status indicates a hardware failure', 'critical', 35)

        if psu_status == 'fail':
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
        if (_as_float(interface.get('in_errors')) + _as_float(interface.get('out_errors')) + _as_float(interface.get('in_discards')) + _as_float(interface.get('out_discards'))) > 0:
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

    if compliance == 'non-compliant':
        penalize('设备合规检查未通过', 'warning', 12)
    elif compliance == 'unknown':
        penalize('尚未进行合规检查', 'warning', 5)

    if forced_status == 'critical' or score < 50:
        health_status = 'critical'
    elif status not in ('online', 'offline', 'pending'):
        health_status = 'unknown'
    elif forced_status == 'warning' or score < 85:
        health_status = 'warning'
    else:
        health_status = 'healthy'

    if status == 'pending' and health_status != 'critical':
        health_status = 'unknown'

    ordered_reasons = [message for _severity, message, _points in sorted(reasons, key=lambda item: (0 if item[0] == 'critical' else 1, -item[2], item[1]))]
    ordered_findings = [{'severity': severity, 'message': message} for severity, message, _points in sorted(reasons, key=lambda item: (0 if item[0] == 'critical' else 1, -item[2], item[1]))]
    summary = ordered_reasons[0] if ordered_reasons else 'No active health issues detected'

    return {
        'health_status': health_status,
        'health_score': max(0, min(100, int(round(score)))),
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
    normalized_devices = [dict(device) for device in devices]
    device_ids = [str(device.get('id') or '') for device in normalized_devices if device.get('id')]
    alert_stats_map = _build_open_alert_stats(conn, device_ids)
    enriched: list[dict[str, Any]] = []
    for device in normalized_devices:
        health = evaluate_device_health(device, alert_stats_map.get(str(device.get('id') or ''), {}))
        enriched.append({**device, **health})
    return enriched


def build_health_overview(devices: list[dict[str, Any]], top_n: int = 8) -> dict[str, Any]:
    counts = {
        'healthy': 0,
        'warning': 0,
        'critical': 0,
        'unknown': 0,
    }
    total_score = 0

    for device in devices:
        health_status = str(device.get('health_status') or 'unknown')
        counts[health_status] = counts.get(health_status, 0) + 1
        total_score += int(device.get('health_score') or 0)

    average_score = round(total_score / len(devices), 1) if devices else 0.0
    risky_devices = sorted(
        devices,
        key=lambda device: (
            HEALTH_STATUS_RANK.get(str(device.get('health_status') or 'unknown'), 99),
            int(device.get('health_score') or 0),
            -int(device.get('open_alert_count') or 0),
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
                'health_status': device.get('health_status'),
                'health_score': device.get('health_score'),
                'health_summary': device.get('health_summary'),
                'open_alert_count': device.get('open_alert_count'),
            }
            for device in risky_devices
        ],
    }


def load_devices_for_health(conn, device_id: str | None = None) -> list[dict[str, Any]]:
    if device_id:
        rows = conn.execute(
            f'SELECT {DEVICE_HEALTH_SELECT} FROM devices WHERE id = ? ORDER BY hostname ASC',
            (device_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            f'SELECT {DEVICE_HEALTH_SELECT} FROM devices ORDER BY hostname ASC'
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
                    interface_error_count, health_summary, health_reasons_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                  health_reasons_json=excluded.health_reasons_json
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
            ROUND(AVG(health_score), 1) AS average_score,
            COUNT(*) AS total_devices,
            SUM(CASE WHEN health_status = 'healthy' THEN 1 ELSE 0 END) AS healthy,
            SUM(CASE WHEN health_status = 'warning' THEN 1 ELSE 0 END) AS warning,
            SUM(CASE WHEN health_status = 'critical' THEN 1 ELSE 0 END) AS critical,
            SUM(CASE WHEN health_status = 'unknown' THEN 1 ELSE 0 END) AS unknown
        FROM device_health_samples
        WHERE ts >= ?
        GROUP BY ts
        ORDER BY ts ASC
        ''',
        (cutoff,),
    ).fetchall()
    return {
        'range_hours': range_hours,
        'sample_count': len(rows),
        'series': [dict(row) for row in rows],
    }


def fetch_device_health_trend(conn, device_id: str, range_hours: int = 24) -> dict[str, Any]:
    device_row = conn.execute(
        'SELECT id, hostname, ip_address, platform, role, site FROM devices WHERE id = ?',
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