from datetime import datetime, timedelta, timezone
from typing import Optional
import heapq
import json
import threading

from fastapi import APIRouter, HTTPException, Query

from database import get_db_connection, fetch_interface_data
from services.device_health_service import annotate_devices_with_health, build_health_overview

router = APIRouter()

_SERVER_PLATFORMS = {'linux', 'ubuntu', 'centos', 'debian', 'redhat'}

_OVERVIEW_CACHE_TTL_SECONDS = 30
_overview_cache_lock = threading.Lock()
_overview_cache: dict[str, object] = {
    'expires_at': None,
    'payload': None,
}


def _parse_json(value, default):
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _align_bucket_range(start_dt: datetime, end_dt: datetime, step_seconds: int) -> tuple[datetime, datetime]:
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    aligned_start_ts = ((start_ts + step_seconds - 1) // step_seconds) * step_seconds
    aligned_end_ts = (end_ts // step_seconds) * step_seconds
    return (
        datetime.fromtimestamp(aligned_start_ts, tz=timezone.utc),
        datetime.fromtimestamp(aligned_end_ts, tz=timezone.utc),
    )


def _fill_missing_time_buckets(rows: list[dict], start_dt: datetime, end_dt: datetime, step_seconds: int) -> list[dict]:
    if step_seconds <= 0:
        return rows
    aligned_start, aligned_end = _align_bucket_range(start_dt, end_dt, step_seconds)
    if aligned_start > aligned_end:
        return []

    metric_keys = [
        'total_in_bps',
        'total_out_bps',
        'peak_bw_in_pct',
        'peak_bw_out_pct',
        'total_in_pkts',
        'total_out_pkts',
        'total_errors',
        'total_drops',
    ]
    rows_by_ts = {str(r.get('ts_minute')): r for r in rows if r.get('ts_minute')}

    filled: list[dict] = []
    cursor = aligned_start
    while cursor <= aligned_end:
        key = cursor.replace(microsecond=0).isoformat()
        existing = rows_by_ts.get(key)
        if existing is not None:
            filled.append(existing)
        else:
            point = {'ts_minute': key}
            for metric_key in metric_keys:
                point[metric_key] = None
            filled.append(point)
        cursor += timedelta(seconds=step_seconds)
    return filled


@router.get('/monitoring/search-devices')
def search_online_devices(
    q: str = Query(default='', min_length=0),
    limit: int = Query(default=20, ge=1, le=50),
):
    qv = (q or '').strip()
    if not qv:
        return {'items': [], 'query': qv}

    conn = get_db_connection()
    try:
        pattern = f"%{qv}%"
        rows = conn.execute(
            '''
            SELECT id, hostname, ip_address, platform, role, site, status, device_category
            FROM devices
            WHERE status = 'online'
                            AND (LOWER(hostname) LIKE LOWER(?) OR LOWER(ip_address) LIKE LOWER(?))
            ORDER BY hostname ASC
            LIMIT ?
            ''',
            (pattern, pattern, limit),
        ).fetchall()
        return {'items': [dict(r) for r in rows], 'query': qv}
    finally:
        conn.close()


@router.get('/monitoring/overview')
def monitoring_overview(force_refresh: bool = Query(default=False)):
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    if not force_refresh:
        with _overview_cache_lock:
            cached_expires_at = _overview_cache.get('expires_at')
            cached_payload = _overview_cache.get('payload')
            if isinstance(cached_expires_at, datetime) and cached_expires_at > now_utc and isinstance(cached_payload, dict):
                return cached_payload

    conn = get_db_connection()
    try:
        stats_window_minutes = 60
        stats_window_start = (now_utc - timedelta(minutes=stats_window_minutes)).isoformat()
        hot_interface_limit = 24

        total_online = conn.execute(
            "SELECT COUNT(*) AS c FROM devices WHERE status = 'online'"
        ).fetchone()['c']

        devices_rows = conn.execute(
            "SELECT id, hostname, ip_address, platform, status, compliance, role, site, "
            "cpu_usage, memory_usage, temp, fan_status, psu_status "
            "FROM devices WHERE status = 'online'"
        ).fetchall()
        devices = []
        for r in devices_rows:
            d = dict(r)
            d['interface_data'] = fetch_interface_data(conn, d['id'])
            devices.append(d)

        interfaces_up = 0
        interfaces_down = 0
        high_util = 0
        hot_interface_heap = []
        hot_interface_seq = 0
        for d in devices:
            intfs = _parse_json(d['interface_data'], [])
            for i in intfs:
                status = str(i.get('status', '')).lower()
                if status == 'up':
                    interfaces_up += 1
                elif status == 'down':
                    interfaces_down += 1
                max_bw = max(_as_float(i.get('bw_in_pct')), _as_float(i.get('bw_out_pct')))
                if max_bw >= 85:
                    high_util += 1
                in_bps = _as_float(i.get('in_bps'))
                out_bps = _as_float(i.get('out_bps'))
                error_total = _as_int(i.get('in_errors')) + _as_int(i.get('out_errors'))
                drop_total = _as_int(i.get('in_discards')) + _as_int(i.get('out_discards'))
                throughput_bps = in_bps + out_bps
                payload = {
                    'device_id': d['id'],
                    'hostname': d['hostname'],
                    'ip_address': d['ip_address'],
                    'platform': d['platform'],
                    'role': d['role'],
                    'site': d['site'],
                    'interface_name': i.get('name') or i.get('interface_name') or 'Unknown',
                    'status': i.get('status') or 'unknown',
                    'utilization_pct': round(max_bw, 1),
                    'speed_mbps': _as_int(i.get('speed_mbps')),
                    'errors': error_total,
                    'drops': drop_total,
                    'in_bps': round(in_bps, 1),
                    'out_bps': round(out_bps, 1),
                    'throughput_bps': round(throughput_bps, 1),
                }
                ranking = (
                    1 if status == 'down' else 0,
                    1 if (error_total + drop_total) > 0 else 0,
                    error_total + drop_total,
                    throughput_bps,
                    float(payload['utilization_pct'] or 0),
                    str(payload['hostname'] or ''),
                )
                hot_interface_seq += 1
                heap_entry = (ranking, hot_interface_seq, payload)
                if len(hot_interface_heap) < hot_interface_limit:
                    heapq.heappush(hot_interface_heap, heap_entry)
                else:
                    heapq.heappushpop(hot_interface_heap, heap_entry)

        top_hot_interfaces = [item[2] for item in sorted(hot_interface_heap, key=lambda entry: (entry[0], entry[1]), reverse=True)]

        recent_totals = conn.execute(
            '''
            SELECT
                COALESCE(SUM(t.in_pkts_sum), 0) AS in_pkts_window,
                COALESCE(SUM(t.out_pkts_sum), 0) AS out_pkts_window,
                COALESCE(SUM(t.err_delta_sum), 0) AS errors_window,
                COALESCE(SUM(t.discard_delta_sum), 0) AS drops_window
            FROM interface_telemetry_1m t
            JOIN devices d ON d.id = t.device_id
            WHERE d.status = 'online' AND t.ts_minute >= ?
            ''',
            (stats_window_start,),
        ).fetchone()

        last_24h = (now_utc - timedelta(hours=24)).isoformat()
        open_alerts = conn.execute(
            "SELECT COUNT(*) AS c FROM alert_events WHERE resolved_at IS NULL AND COALESCE(workflow_status, 'open') != 'suppressed'"
        ).fetchone()['c']
        alerts_24h = conn.execute(
            "SELECT COUNT(*) AS c FROM alert_events WHERE created_at >= ?",
            (last_24h,),
        ).fetchone()['c']
        recent_open_alerts = conn.execute(
            '''
            SELECT
                a.id,
                a.severity,
                a.title,
                a.message,
                a.device_id,
                a.interface_name,
                a.created_at,
                d.hostname,
                d.ip_address,
                d.platform,
                d.role,
                d.site
            FROM alert_events a
            LEFT JOIN devices d ON d.id = a.device_id
            WHERE a.resolved_at IS NULL AND COALESCE(a.workflow_status, 'open') != 'suppressed'
            ORDER BY a.created_at DESC
            LIMIT 8
            '''
        ).fetchall()

        payload = {
            'online_devices': int(total_online),
            'interfaces_up': interfaces_up,
            'interfaces_down': interfaces_down,
            'high_util_interfaces': high_util,
            'in_pkts_window': int(recent_totals['in_pkts_window']),
            'out_pkts_window': int(recent_totals['out_pkts_window']),
            'errors_window': int(recent_totals['errors_window']),
            'drops_window': int(recent_totals['drops_window']),
            'stats_window_minutes': stats_window_minutes,
            'open_alerts': int(open_alerts),
            'alerts_24h': int(alerts_24h),
            'top_hot_interfaces': top_hot_interfaces,
            'recent_open_alerts': [dict(r) for r in recent_open_alerts],
            'updated_at': now_utc.isoformat(),
        }

        # Health evaluation: reuse already-fetched online device rows,
        # only query non-online devices to avoid loading interface_data twice.
        online_dicts = [dict(row) for row in devices]
        non_online_rows = conn.execute(
            '''
            SELECT id, hostname, ip_address, platform, status, compliance, role, site,
                   cpu_usage, memory_usage, temp, fan_status, psu_status
            FROM devices
            WHERE status != 'online'
            ORDER BY hostname ASC
            '''
        ).fetchall()
        non_online_dicts = []
        for r in non_online_rows:
            d = dict(r)
            d['interface_data'] = fetch_interface_data(conn, d['id'])
            non_online_dicts.append(d)
        all_device_dicts = online_dicts + non_online_dicts
        evaluated_devices = annotate_devices_with_health(conn, all_device_dicts)
        payload['device_health_summary'] = build_health_overview(evaluated_devices)
        payload['top_risky_devices'] = payload['device_health_summary']['top_risky_devices']

        with _overview_cache_lock:
            _overview_cache['payload'] = payload
            _overview_cache['expires_at'] = now_utc + timedelta(seconds=_OVERVIEW_CACHE_TTL_SECONDS)
        return payload
    finally:
        conn.close()


@router.get('/monitoring/device/{device_id}/realtime')
def monitoring_device_realtime(
    device_id: str,
    window_minutes: int = Query(default=15, ge=1, le=180),
    limit: int = Query(default=600, ge=50, le=2000),
):
    conn = get_db_connection()
    try:
        device = conn.execute(
            "SELECT id, hostname, ip_address, platform, status, device_category, "
            "cpu_usage, memory_usage, temp, fan_status, psu_status FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()
        if not device:
            raise HTTPException(status_code=404, detail='Device not found')
        device = dict(device)
        device['interface_data'] = fetch_interface_data(conn, device['id'])

        plat = str(device.get('platform') or '').lower()
        category = str(device.get('device_category') or '').lower()
        is_server = plat in _SERVER_PLATFORMS or 'server' in category

        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).replace(microsecond=0).isoformat()
        if is_server:
            rows = conn.execute(
                '''
                SELECT ts, cpu_load, cpu_util, mem_avail, swap_util, io_wait, io_latency,
                       disk_util, inode_util, tcp_conns, tcp_retrans,
                       tcp_estab, tcp_time_wait, tcp_close_wait, tcp_syn_recv, tcp_listen,
                       process_health, service_sshd, service_crond, service_docker
                FROM device_telemetry_samples
                WHERE device_id = ? AND ts >= ?
                ORDER BY ts ASC
                LIMIT ?
                ''',
                (device_id, cutoff, limit),
            ).fetchall()
            series = [dict(r) for r in rows]
            return {
                'device': {
                    'id': device['id'],
                    'hostname': device['hostname'],
                    'ip_address': device['ip_address'],
                    'platform': device['platform'],
                    'status': device['status'],
                    'cpu_usage': device['cpu_usage'],
                    'memory_usage': device['memory_usage'],
                    'temp': device['temp'],
                    'fan_status': device['fan_status'],
                    'psu_status': device['psu_status'],
                },
                'is_server': True,
                'series': series,
                'window_minutes': window_minutes,
                'updated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            }
        rows = conn.execute(
            '''
            SELECT ts, interface_name, status, speed_mbps, in_bps, out_bps, bw_in_pct, bw_out_pct,
                 in_pkts, out_pkts, in_errors, out_errors, in_discards, out_discards
            FROM interface_telemetry_raw
            WHERE device_id = ? AND ts >= ?
            ORDER BY ts DESC
            LIMIT ?
            ''',
            (device_id, cutoff, limit),
        ).fetchall()

        latest_by_interface = {}
        for r in rows:
            name = r['interface_name']
            if name not in latest_by_interface:
                latest_by_interface[name] = dict(r)

        latest_interfaces = sorted(
            latest_by_interface.values(),
            key=lambda x: (x.get('status') != 'up', str(x.get('interface_name', ''))),
        )

        # Build concise timeseries for charts (aggregate total in/out by timestamp)
        ts_agg = {}
        for r in rows:
            ts = r['ts']
            bucket = ts_agg.setdefault(ts, {
                'ts': ts,
                'in_bps': 0.0,
                'out_bps': 0.0,
                'in_pkts': 0,
                'out_pkts': 0,
                'errors': 0,
                'drops': 0,
            })
            bucket['in_bps'] += float(r['in_bps'] or 0)
            bucket['out_bps'] += float(r['out_bps'] or 0)
            bucket['in_pkts'] += int(r['in_pkts'] or 0)
            bucket['out_pkts'] += int(r['out_pkts'] or 0)
            bucket['errors'] += int(r['in_errors'] or 0) + int(r['out_errors'] or 0)
            bucket['drops'] += int(r['in_discards'] or 0) + int(r['out_discards'] or 0)

        series = sorted(ts_agg.values(), key=lambda x: x['ts'])

        summary = {
            'in_bps': 0.0,
            'out_bps': 0.0,
            'in_pkts': 0,
            'out_pkts': 0,
            'errors': 0,
            'drops': 0,
        }
        for item in latest_interfaces:
            summary['in_bps'] += float(item.get('in_bps') or 0)
            summary['out_bps'] += float(item.get('out_bps') or 0)
            summary['in_pkts'] += int(item.get('in_pkts') or 0)
            summary['out_pkts'] += int(item.get('out_pkts') or 0)
            summary['errors'] += int(item.get('in_errors') or 0) + int(item.get('out_errors') or 0)
            summary['drops'] += int(item.get('in_discards') or 0) + int(item.get('out_discards') or 0)

        return {
            'device': {
                'id': device['id'],
                'hostname': device['hostname'],
                'ip_address': device['ip_address'],
                'platform': device['platform'],
                'status': device['status'],
                'cpu_usage': device['cpu_usage'],
                'memory_usage': device['memory_usage'],
                'temp': device['temp'],
                'fan_status': device['fan_status'],
                'psu_status': device['psu_status'],
            },
            'latest_interfaces': latest_interfaces[:200],
            'summary': summary,
            'series': series,
            'window_minutes': window_minutes,
            'updated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
    finally:
        conn.close()


@router.get('/monitoring/device/{device_id}/trend')
def monitoring_device_trend(
    device_id: str,
    range_hours: int = Query(default=24, ge=1, le=24 * 30),
    interface_name: Optional[str] = Query(default=None),
    resolution: str = Query(default='auto'),
    start_time: Optional[str] = Query(default=None),
    end_time: Optional[str] = Query(default=None),
):
    conn = get_db_connection()
    try:
        device = conn.execute(
            "SELECT id, hostname, ip_address, platform, status, device_category FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()
        if not device:
            raise HTTPException(status_code=404, detail='Device not found')
        device = dict(device)

        now_utc = datetime.now(timezone.utc)

        def parse_ts(raw: Optional[str]) -> Optional[datetime]:
            if not raw:
                return None
            try:
                v = raw.strip().replace('Z', '+00:00')
                dt = datetime.fromisoformat(v)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).replace(microsecond=0)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f'Invalid timestamp: {raw}') from exc

        start_dt = parse_ts(start_time)
        end_dt = parse_ts(end_time)
        if end_dt is None:
            end_dt = now_utc.replace(microsecond=0)
        if start_dt is None:
            start_dt = (end_dt - timedelta(hours=range_hours)).replace(microsecond=0)
        if start_dt >= end_dt:
            raise HTTPException(status_code=400, detail='start_time must be earlier than end_time')

        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()
        target_resolution = (resolution or 'auto').strip().lower()

        plat = str(device.get('platform') or '').lower()
        category = str(device.get('device_category') or '').lower()
        is_server = plat in _SERVER_PLATFORMS or 'server' in category

        if is_server:
            use_raw = range_hours <= 24 and target_resolution != '5m'
            if use_raw:
                rows = conn.execute(
                    '''
                    SELECT ts AS ts_minute, cpu_load, cpu_util, mem_avail, swap_util, io_wait, io_latency,
                           disk_util, inode_util, tcp_conns, tcp_retrans,
                           tcp_estab, tcp_time_wait, tcp_close_wait, tcp_syn_recv, tcp_listen,
                           process_health, service_sshd, service_crond, service_docker
                    FROM device_telemetry_samples
                    WHERE device_id = ? AND ts >= ? AND ts <= ?
                    ORDER BY ts ASC
                    ''',
                    (device_id, start_iso, end_iso),
                ).fetchall()
            else:
                rows = conn.execute(
                    '''
                    SELECT ts_hour AS ts_minute,
                           avg_cpu_load AS cpu_load,
                           avg_cpu_util AS cpu_util,
                           avg_mem_avail AS mem_avail,
                           avg_swap_util AS swap_util,
                           avg_io_wait AS io_wait,
                           avg_io_latency AS io_latency,
                           avg_disk_util AS disk_util,
                           avg_inode_util AS inode_util,
                           avg_tcp_conns AS tcp_conns,
                           avg_tcp_retrans AS tcp_retrans,
                           avg_tcp_estab AS tcp_estab,
                           avg_tcp_time_wait AS tcp_time_wait,
                           avg_tcp_close_wait AS tcp_close_wait,
                           avg_tcp_syn_recv AS tcp_syn_recv,
                           avg_tcp_listen AS tcp_listen,
                           avg_process_health AS process_health,
                           0 AS service_sshd, 0 AS service_crond, 0 AS service_docker
                    FROM device_telemetry_hourly
                    WHERE device_id = ? AND ts_hour >= ? AND ts_hour <= ?
                    ORDER BY ts_hour ASC
                    ''',
                    (device_id, start_iso, end_iso),
                ).fetchall()

            series = [dict(r) for r in rows]
            return {
                'device': {
                    'id': device['id'],
                    'hostname': device['hostname'],
                    'ip_address': device.get('ip_address'),
                    'platform': device.get('platform'),
                    'status': device['status'],
                },
                'is_server': True,
                'range_hours': range_hours,
                'resolution': '1m' if use_raw else '5m',
                'start_time': start_iso,
                'end_time': end_iso,
                'series': series,
            }

        # Explicit user-selected resolutions.
        if target_resolution == '5m':
            intf_where = 'AND interface_name = ?' if interface_name and interface_name.strip() else ''
            params = [device_id, start_iso, end_iso]
            if interface_name and interface_name.strip():
                params.append(interface_name.strip())
            rows = conn.execute(
                f'''
                WITH per_minute AS (
                    SELECT ts_minute,
                           SUM(COALESCE(avg_in_bps, 0)) AS total_in_bps,
                           SUM(COALESCE(avg_out_bps, 0)) AS total_out_bps,
                           MAX(COALESCE(max_bw_in_pct, 0)) AS peak_bw_in_pct,
                           MAX(COALESCE(max_bw_out_pct, 0)) AS peak_bw_out_pct,
                           SUM(COALESCE(in_pkts_sum, 0)) AS total_in_pkts,
                           SUM(COALESCE(out_pkts_sum, 0)) AS total_out_pkts,
                           SUM(COALESCE(err_delta_sum, 0)) AS total_errors,
                           SUM(COALESCE(discard_delta_sum, 0)) AS total_drops
                    FROM interface_telemetry_1m
                    WHERE device_id = ? AND ts_minute >= ? AND ts_minute <= ? {intf_where}
                    GROUP BY ts_minute
                )
                SELECT
                    substr(ts_minute, 1, 14) || printf('%02d', (CAST(substr(ts_minute, 15, 2) AS INTEGER) / 5) * 5) || ':00+00:00' AS ts_minute,
                    AVG(total_in_bps) AS total_in_bps,
                    AVG(total_out_bps) AS total_out_bps,
                    MAX(peak_bw_in_pct) AS peak_bw_in_pct,
                    MAX(peak_bw_out_pct) AS peak_bw_out_pct,
                    SUM(total_in_pkts) AS total_in_pkts,
                    SUM(total_out_pkts) AS total_out_pkts,
                    SUM(total_errors) AS total_errors,
                    SUM(total_drops) AS total_drops
                FROM per_minute
                GROUP BY ts_minute
                ORDER BY ts_minute ASC
                ''',
                tuple(params),
            ).fetchall()

            series_rows = _fill_missing_time_buckets([dict(r) for r in rows], start_dt, end_dt, 300)

            return {
                'device': {'id': device['id'], 'hostname': device['hostname'], 'status': device['status']},
                'range_hours': range_hours,
                'resolution': '5m',
                'start_time': start_iso,
                'end_time': end_iso,
                'interface_name': interface_name.strip() if interface_name and interface_name.strip() else None,
                'series': series_rows,
            }

        if target_resolution == '1m' and range_hours > 24:
            intf_where = 'AND interface_name = ?' if interface_name and interface_name.strip() else ''
            params = [device_id, start_iso, end_iso]
            if interface_name and interface_name.strip():
                params.append(interface_name.strip())
            rows = conn.execute(
                f'''
                SELECT ts_minute,
                       SUM(COALESCE(avg_in_bps, 0)) AS total_in_bps,
                       SUM(COALESCE(avg_out_bps, 0)) AS total_out_bps,
                       MAX(COALESCE(max_bw_in_pct, 0)) AS peak_bw_in_pct,
                       MAX(COALESCE(max_bw_out_pct, 0)) AS peak_bw_out_pct,
                       SUM(COALESCE(in_pkts_sum, 0)) AS total_in_pkts,
                       SUM(COALESCE(out_pkts_sum, 0)) AS total_out_pkts,
                       SUM(COALESCE(err_delta_sum, 0)) AS total_errors,
                       SUM(COALESCE(discard_delta_sum, 0)) AS total_drops
                FROM interface_telemetry_1m
                WHERE device_id = ? AND ts_minute >= ? AND ts_minute <= ? {intf_where}
                GROUP BY ts_minute
                ORDER BY ts_minute ASC
                ''',
                tuple(params),
            ).fetchall()

            series_rows = _fill_missing_time_buckets([dict(r) for r in rows], start_dt, end_dt, 60)

            return {
                'device': {'id': device['id'], 'hostname': device['hostname'], 'status': device['status']},
                'range_hours': range_hours,
                'resolution': '1m',
                'start_time': start_iso,
                'end_time': end_iso,
                'interface_name': interface_name.strip() if interface_name and interface_name.strip() else None,
                'series': series_rows,
            }

        # Backward-compatible behavior for legacy callers.
        use_raw = target_resolution == '5s' or (target_resolution in ('auto', '1m') and range_hours <= 24)

        if interface_name and interface_name.strip() and use_raw:
            rows = conn.execute(
                '''
                SELECT ts AS ts_minute,
                       SUM(COALESCE(in_bps, 0)) AS total_in_bps,
                       SUM(COALESCE(out_bps, 0)) AS total_out_bps,
                       MAX(COALESCE(bw_in_pct, 0)) AS peak_bw_in_pct,
                       MAX(COALESCE(bw_out_pct, 0)) AS peak_bw_out_pct,
                       SUM(COALESCE(in_pkts, 0)) AS total_in_pkts,
                       SUM(COALESCE(out_pkts, 0)) AS total_out_pkts,
                       SUM(COALESCE(in_errors, 0) + COALESCE(out_errors, 0)) AS total_errors,
                       SUM(COALESCE(in_discards, 0) + COALESCE(out_discards, 0)) AS total_drops
                FROM interface_telemetry_raw
                WHERE device_id = ? AND ts >= ? AND ts <= ? AND interface_name = ?
                GROUP BY ts
                ORDER BY ts ASC
                ''',
                (device_id, start_iso, end_iso, interface_name.strip()),
            ).fetchall()
        elif use_raw:
            rows = conn.execute(
                '''
                SELECT ts AS ts_minute,
                       SUM(COALESCE(in_bps, 0)) AS total_in_bps,
                       SUM(COALESCE(out_bps, 0)) AS total_out_bps,
                       MAX(COALESCE(bw_in_pct, 0)) AS peak_bw_in_pct,
                       MAX(COALESCE(bw_out_pct, 0)) AS peak_bw_out_pct,
                       SUM(COALESCE(in_pkts, 0)) AS total_in_pkts,
                       SUM(COALESCE(out_pkts, 0)) AS total_out_pkts,
                       SUM(COALESCE(in_errors, 0) + COALESCE(out_errors, 0)) AS total_errors,
                       SUM(COALESCE(in_discards, 0) + COALESCE(out_discards, 0)) AS total_drops
                FROM interface_telemetry_raw
                WHERE device_id = ? AND ts >= ? AND ts <= ?
                GROUP BY ts
                ORDER BY ts ASC
                ''',
                (device_id, start_iso, end_iso),
            ).fetchall()
        elif interface_name and interface_name.strip():
            rows = conn.execute(
                '''
                SELECT ts_minute,
                       SUM(COALESCE(avg_in_bps, 0)) AS total_in_bps,
                       SUM(COALESCE(avg_out_bps, 0)) AS total_out_bps,
                       MAX(COALESCE(max_bw_in_pct, 0)) AS peak_bw_in_pct,
                       MAX(COALESCE(max_bw_out_pct, 0)) AS peak_bw_out_pct,
                       SUM(COALESCE(in_pkts_sum, 0)) AS total_in_pkts,
                       SUM(COALESCE(out_pkts_sum, 0)) AS total_out_pkts,
                       SUM(COALESCE(err_delta_sum, 0)) AS total_errors,
                       SUM(COALESCE(discard_delta_sum, 0)) AS total_drops
                FROM interface_telemetry_1m
                WHERE device_id = ? AND ts_minute >= ? AND ts_minute <= ? AND interface_name = ?
                GROUP BY ts_minute
                ORDER BY ts_minute ASC
                ''',
                (device_id, start_iso, end_iso, interface_name.strip()),
            ).fetchall()
        else:
            rows = conn.execute(
                '''
                SELECT ts_minute,
                       SUM(COALESCE(avg_in_bps, 0)) AS total_in_bps,
                       SUM(COALESCE(avg_out_bps, 0)) AS total_out_bps,
                       MAX(COALESCE(max_bw_in_pct, 0)) AS peak_bw_in_pct,
                       MAX(COALESCE(max_bw_out_pct, 0)) AS peak_bw_out_pct,
                       SUM(COALESCE(in_pkts_sum, 0)) AS total_in_pkts,
                       SUM(COALESCE(out_pkts_sum, 0)) AS total_out_pkts,
                       SUM(COALESCE(err_delta_sum, 0)) AS total_errors,
                       SUM(COALESCE(discard_delta_sum, 0)) AS total_drops
                FROM interface_telemetry_1m
                WHERE device_id = ? AND ts_minute >= ? AND ts_minute <= ?
                GROUP BY ts_minute
                ORDER BY ts_minute ASC
                ''',
                (device_id, start_iso, end_iso),
            ).fetchall()

        series_rows = [dict(r) for r in rows]
        if not use_raw:
            series_rows = _fill_missing_time_buckets(series_rows, start_dt, end_dt, 60)

        return {
            'device': {'id': device['id'], 'hostname': device['hostname'], 'status': device['status']},
            'range_hours': range_hours,
            'resolution': '5s' if use_raw else '1m',
            'start_time': start_iso,
            'end_time': end_iso,
            'interface_name': interface_name.strip() if interface_name and interface_name.strip() else None,
            'series': series_rows,
        }
    finally:
        conn.close()


@router.get('/monitoring/alerts')
def monitoring_alerts(
    device_id: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default='all'),
    phase: Optional[str] = Query(default='all'),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    conn = get_db_connection()
    try:
        where = []
        params = []

        if device_id:
            where.append('device_id = ?')
            params.append(device_id)

        sev = (severity or 'all').lower()
        phase_filter = (phase or 'all').lower()
        where.append("COALESCE(workflow_status, 'open') != 'suppressed'")
        if sev != 'all':
            where.append('LOWER(severity) = ?')
            params.append(sev)
        if phase_filter == 'active':
            where.append('resolved_at IS NULL')
        elif phase_filter == 'recovered':
            where.append('resolved_at IS NOT NULL')

        where_sql = f"WHERE {' AND '.join(where)}" if where else ''

        total = conn.execute(
            f'SELECT COUNT(*) AS c FROM alert_events {where_sql}',
            tuple(params),
        ).fetchone()['c']

        offset = (page - 1) * page_size
        rows = conn.execute(
            f'''
            SELECT id, dedupe_key, source, severity, title, message, device_id, interface_name, created_at, resolved_at
            FROM alert_events
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            ''',
            tuple([*params, page_size, offset]),
        ).fetchall()

        return {
            'items': [dict(r) for r in rows],
            'total': int(total),
            'page': page,
            'page_size': page_size,
        }
    finally:
        conn.close()
