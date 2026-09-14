from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional
import asyncio
import heapq
import json
import logging
import threading
import time
import uuid
from pydantic import BaseModel, Field

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from api.users import validate_session_token
from core.rbac import require_role
from database import get_db_connection, fetch_interface_data
from services.audit_service import log_audit_event
from services.device_health_service import annotate_devices_with_health, build_health_overview, load_devices_for_health
from services.collection_status_service import collection_status_summary, list_collection_status
from services.collection_diagnostics_service import diagnose_device_collection
from services.monitoring_incident_service import (
    append_incident_timeline,
    assign_incident,
    get_incident,
    get_incident_impact,
    list_incidents,
    recommend_incident_playbooks,
    update_incident_status,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_monitoring_session(request: Request) -> dict:
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else ''
    session = validate_session_token(token)
    if not session:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return session

_SERVER_PLATFORMS = {'linux', 'ubuntu', 'centos', 'debian', 'redhat'}


def _is_virtual_interface_name(name: object) -> bool:
    """Return whether an interface is a virtual/system interface.

    The SNMP collector already applies the same physical-interface policy, but
    the realtime API also has to protect the UI from historical rows written
    by older collectors (for example ``InLoopBack0`` and
    ``Register-Tunnel0``).  Filtering at read time removes those stale rows
    without deleting telemetry history.
    """
    lowered = str(name or '').strip().casefold()
    if not lowered:
        return True
    return (
        lowered.startswith(('lo', 'loopback', 'inloopback', 'vl', 'vlan', 'tu', 'tunnel'))
        or 'tunnel' in lowered
        or any(skip in lowered for skip in ('null', 'nu0', 'unrouted', 'stack', 'cpu', 'async', 'voip', 'vo0'))
    )

_OVERVIEW_CACHE_TTL_SECONDS = 30
_overview_cache_lock = threading.Lock()
_overview_cache: dict[str, object] = {
    'expires_at': None,
    'payload': None,
}


class MonitoringIncidentStatusRequest(BaseModel):
    status: Literal['acknowledged', 'investigating'] = 'acknowledged'


class MonitoringIncidentAssignRequest(BaseModel):
    assignee: str = Field(min_length=1, max_length=120)


class MonitoringIncidentPlaybookExecuteRequest(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=160)
    variables: dict[str, Any] = Field(default_factory=dict)


@router.get('/monitoring/collection-status')
def monitoring_collection_status(
    device_id: Optional[str] = Query(default=None),
    site_id: Optional[str] = Query(default=None),
    collector: Optional[str] = Query(default=None),
):
    """Return secret-free collector health for monitoring and topology UIs."""
    items = list_collection_status(device_id=device_id, site_id=site_id, collector=collector)
    return {
        'items': items,
        'summary': collection_status_summary(site_id=site_id),
    }


@router.get('/monitoring/device/{device_id}/collection-status')
def monitoring_device_collection_status(device_id: str):
    items = list_collection_status(device_id=device_id)
    return {
        'device_id': device_id,
        'items': items,
    }


@router.post('/monitoring/device/{device_id}/diagnostics')
async def monitoring_device_diagnostics(device_id: str, request: Request, incident_id: Optional[str] = Query(default=None)):
    _require_monitoring_session(request)
    result = await diagnose_device_collection(device_id)
    if result is None:
        raise HTTPException(status_code=404, detail='Device not found')
    if incident_id:
        actor = str(_require_monitoring_session(request).get('username') or 'system').strip() or 'system'
        conn = get_db_connection()
        try:
            append_incident_timeline(
                conn,
                incident_id,
                'diagnostics_completed',
                actor,
                f'Collection diagnostics completed for {result.get("hostname") or device_id}',
                {'device_id': device_id, 'status': result.get('status'), 'checks': result.get('checks') or {}},
            )
            conn.commit()
        finally:
            conn.close()
    return result


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
        'total_crc_errors',
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


def _downsample_network_series(rows: list[dict], bucket_seconds: int) -> list[dict]:
    """Database-agnostic time bucketing for PostgreSQL and SQLite."""
    if bucket_seconds <= 60:
        return rows
    buckets: dict[int, list[dict]] = {}
    for row in rows:
        raw_ts = row.get('ts_minute')
        if not raw_ts:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw_ts).replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        bucket = (int(parsed.timestamp()) // bucket_seconds) * bucket_seconds
        buckets.setdefault(bucket, []).append(row)

    average_keys = ('total_in_bps', 'total_out_bps')
    max_keys = ('peak_bw_in_pct', 'peak_bw_out_pct')
    sum_keys = ('total_in_pkts', 'total_out_pkts', 'total_errors', 'total_drops', 'total_crc_errors')
    result: list[dict] = []
    for bucket, points in sorted(buckets.items()):
        item: dict[str, object] = {
            'ts_minute': datetime.fromtimestamp(bucket, tz=timezone.utc).replace(microsecond=0).isoformat()
        }
        for key in average_keys:
            values = [float(point[key]) for point in points if point.get(key) is not None]
            item[key] = sum(values) / len(values) if values else None
        for key in max_keys:
            values = [float(point[key]) for point in points if point.get(key) is not None]
            item[key] = max(values) if values else None
        for key in sum_keys:
            values = [int(point[key]) for point in points if point.get(key) is not None]
            item[key] = sum(values) if values else None
        result.append(item)
    return result


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
            SELECT d.id, d.hostname, d.ip_address, d.platform, d.role,
                   COALESCE(NULLIF(s.site_name, ''),
                            CASE WHEN SUBSTR(COALESCE(d.site, ''), 1, 5) = 'site-' THEN '' ELSE COALESCE(d.site, '') END,
                            '') AS site,
                   d.status, d.device_category
            FROM devices d
            LEFT JOIN sites s ON s.id = d.site_id
            WHERE d.status = 'online'
              AND (LOWER(d.hostname) LIKE LOWER(?) OR LOWER(d.ip_address) LIKE LOWER(?))
            ORDER BY d.hostname ASC
            LIMIT ?
            ''',
            (pattern, pattern, limit),
        ).fetchall()
        return {'items': [dict(r) for r in rows], 'query': qv}
    finally:
        conn.close()


@router.get('/monitoring/network-devices')
def list_monitoring_network_devices(
    q: str = Query(default='', min_length=0, max_length=120),
    site_id: str = Query(default='all', min_length=0, max_length=120),
    status: Literal['all', 'online', 'offline'] = Query(default='all'),
    page: int = Query(default=1, ge=1, le=100000),
    page_size: int = Query(default=30, ge=10, le=100),
):
    """Return a bounded, server-filtered page for the network monitoring list.

    The monitoring screen only needs network devices.  Keeping the search,
    site/status filters, count, and pagination in SQL prevents the browser
    from receiving the whole inventory just to render the left-hand list.
    """
    qv = (q or '').strip()
    site_filter = (site_id or '').strip()
    if site_filter.lower() in {'', 'all'}:
        site_filter = ''

    network_predicate = """
        LOWER(COALESCE(d.platform, '')) NOT LIKE '%linux%'
        AND LOWER(COALESCE(d.platform, '')) NOT LIKE '%ubuntu%'
        AND LOWER(COALESCE(d.platform, '')) NOT LIKE '%centos%'
        AND LOWER(COALESCE(d.platform, '')) NOT LIKE '%debian%'
        AND LOWER(COALESCE(d.platform, '')) NOT LIKE '%redhat%'
        AND LOWER(COALESCE(d.platform, '')) NOT LIKE '%rocky%'
        AND LOWER(COALESCE(d.platform, '')) NOT LIKE '%alma%'
        AND LOWER(COALESCE(d.platform, '')) NOT LIKE '%' || 'server' || '%'
        AND LOWER(COALESCE(d.device_category, '')) NOT LIKE '%' || 'server' || '%'
        AND LOWER(COALESCE(d.role, '')) NOT LIKE '%' || 'server' || '%'
        AND LOWER(COALESCE(pa.asset_type, '')) NOT LIKE '%' || 'server' || '%'
    """
    site_id_expr = "COALESCE(NULLIF(d.site_id, ''), NULLIF(d.site, ''), '')"
    site_name_expr = "COALESCE(NULLIF(s.site_name, ''), CASE WHEN SUBSTR(COALESCE(d.site, ''), 1, 5) = 'site-' THEN '' ELSE COALESCE(d.site, '') END, {site_id_expr}, '')".format(site_id_expr=site_id_expr)
    where_parts = [network_predicate]
    where_params: list[Any] = []
    if qv:
        pattern = f"%{qv}%"
        where_parts.append("(LOWER(COALESCE(d.hostname, '')) LIKE LOWER(?) OR LOWER(COALESCE(d.ip_address, '')) LIKE LOWER(?))")
        where_params.extend([pattern, pattern])
    if site_filter:
        where_parts.append(f"{site_id_expr} = ?")
        where_params.append(site_filter)
    base_where = ' AND '.join(where_parts)

    status_where = list(where_parts)
    status_params = list(where_params)
    if status == 'online':
        status_where.append("LOWER(COALESCE(d.status, '')) = 'online'")
    elif status == 'offline':
        status_where.append("LOWER(COALESCE(d.status, '')) <> 'online'")

    conn = get_db_connection()
    try:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM devices d LEFT JOIN physical_assets pa ON pa.id = d.asset_id LEFT JOIN sites s ON s.id = d.site_id WHERE {' AND '.join(status_where)}",
            tuple(status_params),
        ).fetchone()
        total = int(total_row['total'] or 0) if total_row else 0

        status_row = conn.execute(
            f"""
            SELECT
                SUM(CASE WHEN LOWER(COALESCE(d.status, '')) = 'online' THEN 1 ELSE 0 END) AS online_count,
                SUM(CASE WHEN LOWER(COALESCE(d.status, '')) <> 'online' THEN 1 ELSE 0 END) AS offline_count
            FROM devices d LEFT JOIN physical_assets pa ON pa.id = d.asset_id LEFT JOIN sites s ON s.id = d.site_id
            WHERE {base_where}
            """,
            tuple(where_params),
        ).fetchone()

        site_rows = conn.execute(
            f"""
            SELECT {site_id_expr} AS id, {site_name_expr} AS name, COUNT(*) AS device_count
            FROM devices d LEFT JOIN physical_assets pa ON pa.id = d.asset_id LEFT JOIN sites s ON s.id = d.site_id
            WHERE {base_where}
            GROUP BY {site_id_expr}, {site_name_expr}
            HAVING {site_id_expr} <> ''
            ORDER BY LOWER({site_name_expr}) ASC
            """,
            tuple(where_params),
        ).fetchall()

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT d.id, d.hostname, d.ip_address, d.platform, d.status,
                   d.compliance, d.role, d.device_category, d.model, d.version,
                   {site_id_expr} AS site_id,
                   {site_name_expr} AS site
            FROM devices d LEFT JOIN physical_assets pa ON pa.id = d.asset_id LEFT JOIN sites s ON s.id = d.site_id
            WHERE {' AND '.join(status_where)}
            ORDER BY LOWER(COALESCE(d.hostname, '')) ASC, d.id ASC
            LIMIT ? OFFSET ?
            """,
            tuple(status_params) + (page_size, offset),
        ).fetchall()
        return {
            'items': [dict(row) for row in rows],
            'total': total,
            'page': page,
            'page_size': page_size,
            'pages': (total + page_size - 1) // page_size if total else 0,
            'query': qv,
            'site_id': site_filter or 'all',
            'status': status,
            'site_options': [dict(row) for row in site_rows],
            'status_counts': {
                'online': int((status_row['online_count'] if status_row else 0) or 0),
                'offline': int((status_row['offline_count'] if status_row else 0) or 0),
            },
        }
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

        device_counts = conn.execute(
            '''
            SELECT
                COUNT(*) AS total_devices,
                SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) AS online_devices,
                SUM(CASE WHEN status = 'offline' THEN 1 ELSE 0 END) AS offline_devices,
                SUM(CASE WHEN status IS NULL OR status NOT IN ('online', 'offline') THEN 1 ELSE 0 END) AS unknown_devices
            FROM devices
            '''
        ).fetchone()
        total_online = int(device_counts['online_devices'] or 0)

        devices_rows = conn.execute(
            "SELECT d.id, d.hostname, d.ip_address, d.platform, d.status, d.compliance, d.role, "
            "COALESCE(NULLIF(s.site_name, ''), CASE WHEN SUBSTR(COALESCE(d.site, ''), 1, 5) = 'site-' THEN '' ELSE COALESCE(d.site, '') END, '') AS site, "
            "d.cpu_usage, d.memory_usage, d.temp, d.fan_status, d.psu_status, d.device_category "
            "FROM devices d LEFT JOIN sites s ON s.id = d.site_id WHERE d.status = 'online'"
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
        open_alert_severity_rows = conn.execute(
            '''
            SELECT LOWER(COALESCE(severity, 'warning')) AS severity, COUNT(*) AS count
            FROM alert_events
            WHERE resolved_at IS NULL AND COALESCE(workflow_status, 'open') != 'suppressed'
            GROUP BY LOWER(COALESCE(severity, 'warning'))
            '''
        ).fetchall()
        open_alert_severity_counts = {'critical': 0, 'major': 0, 'warning': 0}
        for row in open_alert_severity_rows:
            severity = str(row['severity'] or 'warning').lower()
            bucket = severity if severity in {'critical', 'major'} else 'warning'
            open_alert_severity_counts[bucket] += int(row['count'] or 0)
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
                COALESCE(NULLIF(s.site_name, ''),
                         CASE WHEN SUBSTR(COALESCE(d.site, ''), 1, 5) = 'site-' THEN '' ELSE COALESCE(d.site, '') END,
                         '') AS site
            FROM alert_events a
            LEFT JOIN devices d ON d.id = a.device_id
            LEFT JOIN sites s ON s.id = d.site_id
            WHERE a.resolved_at IS NULL AND COALESCE(a.workflow_status, 'open') != 'suppressed'
            ORDER BY a.created_at DESC
            LIMIT 8
            '''
        ).fetchall()

        payload = {
            'online_devices': int(total_online),
            'offline_devices': int(device_counts['offline_devices'] or 0),
            'unknown_devices': int(device_counts['unknown_devices'] or 0),
            'total_devices': int(device_counts['total_devices'] or 0),
            'interfaces_up': interfaces_up,
            'interfaces_down': interfaces_down,
            'high_util_interfaces': high_util,
            'in_pkts_window': int(recent_totals['in_pkts_window']),
            'out_pkts_window': int(recent_totals['out_pkts_window']),
            'errors_window': int(recent_totals['errors_window']),
            'drops_window': int(recent_totals['drops_window']),
            'stats_window_minutes': stats_window_minutes,
            'open_alerts': int(open_alerts),
            'open_alert_severity_counts': open_alert_severity_counts,
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
            SELECT d.id, d.hostname, d.ip_address, d.platform, d.status, d.compliance, d.role,
                   COALESCE(NULLIF(s.site_name, ''), CASE WHEN SUBSTR(COALESCE(d.site, ''), 1, 5) = 'site-' THEN '' ELSE COALESCE(d.site, '') END, '') AS site,
                   d.cpu_usage, d.memory_usage, d.temp, d.fan_status, d.psu_status, d.device_category
            FROM devices d
            LEFT JOIN sites s ON s.id = d.site_id
            WHERE d.status IS NULL OR d.status != 'online'
            ORDER BY d.hostname ASC
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
        # The health summary is the authoritative source for availability and
        # collection dimensions because it covers every device, not only the
        # online rows used for interface telemetry.
        payload['online_devices'] = payload['device_health_summary']['online_devices']
        payload['offline_devices'] = payload['device_health_summary']['offline_devices']
        payload['unknown_devices'] = payload['device_health_summary']['unknown_availability_devices']
        payload['collection_anomaly_devices'] = payload['device_health_summary']['collection_anomaly_devices']
        payload['data_confidence_avg'] = payload['device_health_summary']['data_confidence_avg']
        payload['last_collection_at'] = payload['device_health_summary']['last_collection_at']
        collection_summary = collection_status_summary()
        by_status = collection_summary.get('by_status') or {}
        collector_count = len(collection_summary.get('by_collector') or {})
        collector_failures = sum(int(by_status.get(key) or 0) for key in ('failed', 'stale', 'partial_failed', 'unknown'))
        runtime_queues: dict[str, dict[str, int]] = {}
        runtime_workers: dict[str, dict[str, int]] = {}
        try:
            queue_rows = conn.execute(
                'SELECT collector, status, COUNT(*) AS count FROM collector_task_queue GROUP BY collector, status'
            ).fetchall()
            for row in queue_rows:
                collector = str(row['collector'] or 'unknown')
                runtime_queues.setdefault(collector, {})[str(row['status'] or 'unknown')] = int(row['count'] or 0)
            for collector, counts in runtime_queues.items():
                counts['total'] = sum(value for key, value in counts.items() if key != 'total')
                counts['pending'] = int(counts.get('pending') or 0)
                counts['running'] = int(counts.get('running') or 0)
            worker_rows = conn.execute(
                'SELECT collector, status, COUNT(*) AS count FROM collector_worker_slots GROUP BY collector, status'
            ).fetchall()
            for row in worker_rows:
                collector = str(row['collector'] or 'unknown')
                runtime_workers.setdefault(collector, {})[str(row['status'] or 'unknown')] = int(row['count'] or 0)
        except Exception:
            # Older deployments may not have the optional queue/worker tables.
            # The response reports unknown rather than claiming the platform is healthy.
            # PostgreSQL marks the current transaction as failed after a missing
            # relation/column error.  Reset it before continuing with the
            # incident projection query below; otherwise the next read raises
            # InFailedSqlTransaction and the whole monitoring overview fails.
            try:
                conn.rollback()
            except Exception:
                logger.debug('Unable to rollback optional platform-health probe', exc_info=True)
            runtime_queues = {}
            runtime_workers = {}
        try:
            from api.playbooks.manager import ws_manager
            websocket_connections = sum(len(items) for items in ws_manager.connections.values())
            websocket_sessions = len(ws_manager.connections)
        except Exception:
            websocket_connections = None
            websocket_sessions = None
        import os
        redis_configured = bool(os.environ.get('REDIS_URL') or os.environ.get('REDIS_HOST'))
        payload['platform_health'] = {
            'database': {'status': 'healthy', 'checked_at': now_utc.isoformat()},
            'collectors': {
                'total': collector_count,
                'failed': collector_failures,
                'status': 'degraded' if collector_failures else 'healthy',
            },
            'queue': runtime_queues or (collection_summary.get('queues') or {}),
            'workers': runtime_workers,
            'websocket': {
                'status': 'healthy' if websocket_connections is not None else 'unknown',
                'active_connections': websocket_connections,
                'active_sessions': websocket_sessions,
            },
            'redis': {
                'status': 'configured_unverified' if redis_configured else 'not_configured',
                'configured': redis_configured,
                'message': 'Redis health probe is not configured in this deployment.' if not redis_configured else 'Redis endpoint is configured; external probe is required for latency/auth validation.',
            },
            'sweeps': collection_summary.get('sweeps') or {},
            'updated_at': now_utc.isoformat(),
        }
        incident_page = list_incidents(conn, status='active', page=1, page_size=100)
        incident_items = incident_page['items']
        payload['active_incidents'] = int(incident_page['total'])
        payload['critical_incidents'] = sum(1 for item in incident_items if str(item.get('severity') or '').lower() == 'critical')
        payload['top_incidents'] = incident_items[:5]

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
        device['interface_data'] = [
            item for item in (fetch_interface_data(conn, device['id']) or [])
            if not _is_virtual_interface_name(item.get('interface_name') or item.get('name'))
        ]

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
                 in_pkts, out_pkts, in_errors, out_errors, in_discards, out_discards,
                 fcs_errors, frame_too_long_errors, mac_rx_errors, symbol_errors,
                 packet_counter_source, fcs_source
            FROM interface_telemetry_raw
            WHERE device_id = ? AND ts >= ?
            ORDER BY ts DESC
            LIMIT ?
            ''',
            (device_id, cutoff, limit),
        ).fetchall()
        rows = [dict(r) for r in rows if not _is_virtual_interface_name(r['interface_name'])]
        # The realtime table stores derived rates, while the collector's
        # durable IF-MIB snapshot keeps the exact cumulative octet counters
        # returned by the device.  Attach those raw values so the UI can show
        # a value even when a rate has not yet been derived from two samples.
        counter_snapshot_by_name: dict[str, dict[str, Any]] = {}
        counter_sampled_at = None
        try:
            snapshot_row = conn.execute(
                "SELECT values_json, sampled_at FROM snmp_interface_counter_samples "
                "WHERE device_id = ? ORDER BY updated_at DESC LIMIT 1",
                (device_id,),
            ).fetchone()
            if snapshot_row:
                counter_sampled_at = snapshot_row['sampled_at']
                snapshots = json.loads(snapshot_row['values_json'] or '{}')
                if isinstance(snapshots, dict):
                    for snapshot in snapshots.values():
                        if not isinstance(snapshot, dict):
                            continue
                        name = str(snapshot.get('name') or '').strip()
                        if name:
                            counter_snapshot_by_name[name] = snapshot
        except Exception as snapshot_error:
            logger.debug("Unable to attach raw interface counters for %s: %s", device_id, snapshot_error)
        for row in rows:
            snapshot = counter_snapshot_by_name.get(str(row.get('interface_name') or '').strip())
            if snapshot:
                row['in_octets'] = snapshot.get('in_octets')
                row['out_octets'] = snapshot.get('out_octets')
                row['counter_width'] = snapshot.get('counter_width')
                row['counter_source'] = snapshot.get('counter_source')
                row['counter_mode'] = snapshot.get('counter_mode')
                row['counter_quality'] = snapshot.get('counter_quality')
                row['counter_quality_reason'] = snapshot.get('counter_quality_reason')
                row['in_packets_total'] = snapshot.get('in_packets_total', row.get('in_pkts'))
                row['out_packets_total'] = snapshot.get('out_packets_total', row.get('out_pkts'))
                row['packet_counter_source'] = snapshot.get('packet_counter_source', row.get('packet_counter_source'))
                row['fcs_errors'] = snapshot.get('fcs_errors', row.get('fcs_errors'))
                row['frame_too_long_errors'] = snapshot.get('frame_too_long_errors', row.get('frame_too_long_errors'))
                row['mac_rx_errors'] = snapshot.get('mac_rx_errors', row.get('mac_rx_errors'))
                row['symbol_errors'] = snapshot.get('symbol_errors', row.get('symbol_errors'))
                row['fcs_source'] = snapshot.get('fcs_source', row.get('fcs_source'))
                row['counter_sampled_at'] = counter_sampled_at
        counter_fields = (
            'in_pkts', 'out_pkts', 'in_errors', 'out_errors',
            'in_discards', 'out_discards', 'fcs_errors',
        )
        for row in rows:
            # Do not rewrite or suppress values returned by the collector.
            # Older rows may have NULLs from a previous collector version; mark
            # that storage state without turning it into a user-facing status.
            if not row.get('counter_quality'):
                row['counter_quality'] = 'raw' if all(row.get(field) is None for field in counter_fields) else 'available'
            if not row.get('counter_source') and row.get('counter_width') in (32, 64):
                row['counter_source'] = (
                    'ifHCInOctets/ifHCOutOctets' if row.get('counter_width') == 64
                    else 'ifInOctets/ifOutOctets'
                )

        latest_by_interface = {}
        for r in rows:
            name = r['interface_name']
            if name not in latest_by_interface:
                latest_by_interface[name] = dict(r)

        latest_interfaces = sorted(
            (item for item in latest_by_interface.values() if str(item.get('status') or '').lower() == 'up'),
            key=lambda x: (x.get('status') != 'up', str(x.get('interface_name', ''))),
        )

        # Build concise timeseries for charts (aggregate total in/out by timestamp)
        ts_agg = {}
        for r in rows:
            if str(r['status'] or '').lower() != 'up':
                continue
            ts = r['ts']
            bucket = ts_agg.setdefault(ts, {
                'ts': ts,
                'in_bps': 0.0,
                'out_bps': 0.0,
                'in_pkts': 0,
                'out_pkts': 0,
                'errors': 0,
                'drops': 0,
                'crc_errors': 0,
            })
            bucket['in_bps'] += float(r['in_bps'] or 0)
            bucket['out_bps'] += float(r['out_bps'] or 0)
            bucket['in_pkts'] += int(r['in_pkts'] or 0)
            bucket['out_pkts'] += int(r['out_pkts'] or 0)
            bucket['errors'] += int(r['in_errors'] or 0) + int(r['out_errors'] or 0)
            bucket['drops'] += int(r['in_discards'] or 0) + int(r['out_discards'] or 0)
            bucket['crc_errors'] += int(r['fcs_errors'] or 0)

        series = sorted(ts_agg.values(), key=lambda x: x['ts'])

        summary = {
            'in_bps': 0.0,
            'out_bps': 0.0,
            'in_pkts': 0,
            'out_pkts': 0,
            'errors': 0,
            'drops': 0,
            'crc_errors': 0,
        }
        for item in latest_interfaces:
            summary['in_bps'] += float(item.get('in_bps') or 0)
            summary['out_bps'] += float(item.get('out_bps') or 0)
            summary['in_pkts'] += int(item.get('in_pkts') or 0)
            summary['out_pkts'] += int(item.get('out_pkts') or 0)
            summary['errors'] += int(item.get('in_errors') or 0) + int(item.get('out_errors') or 0)
            summary['drops'] += int(item.get('in_discards') or 0) + int(item.get('out_discards') or 0)
            summary['crc_errors'] += int(item.get('fcs_errors') or 0)

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
                SELECT ts_minute,
                       SUM(COALESCE(avg_in_bps, 0)) AS total_in_bps,
                       SUM(COALESCE(avg_out_bps, 0)) AS total_out_bps,
                       MAX(COALESCE(max_bw_in_pct, 0)) AS peak_bw_in_pct,
                       MAX(COALESCE(max_bw_out_pct, 0)) AS peak_bw_out_pct,
                       SUM(COALESCE(in_pkts_sum, 0)) AS total_in_pkts,
                       SUM(COALESCE(out_pkts_sum, 0)) AS total_out_pkts,
                       SUM(COALESCE(err_delta_sum, 0)) AS total_errors,
                       SUM(COALESCE(discard_delta_sum, 0)) AS total_drops,
                       SUM(COALESCE(fcs_sum, 0)) AS total_crc_errors
                FROM interface_telemetry_1m
                WHERE device_id = ? AND ts_minute >= ? AND ts_minute <= ? {intf_where}
                GROUP BY ts_minute
                ORDER BY ts_minute ASC
                ''',
                tuple(params),
            ).fetchall()

            series_rows = _downsample_network_series([dict(r) for r in rows], 300)
            series_rows = _fill_missing_time_buckets(series_rows, start_dt, end_dt, 300)

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
                       SUM(COALESCE(discard_delta_sum, 0)) AS total_drops,
                       SUM(COALESCE(fcs_sum, 0)) AS total_crc_errors
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
                       SUM(COALESCE(in_discards, 0) + COALESCE(out_discards, 0)) AS total_drops,
                       SUM(COALESCE(fcs_errors, 0)) AS total_crc_errors
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
                       SUM(COALESCE(in_discards, 0) + COALESCE(out_discards, 0)) AS total_drops,
                       SUM(COALESCE(fcs_errors, 0)) AS total_crc_errors
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
                       SUM(COALESCE(discard_delta_sum, 0)) AS total_drops,
                       SUM(COALESCE(fcs_sum, 0)) AS total_crc_errors
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
                       SUM(COALESCE(discard_delta_sum, 0)) AS total_drops,
                       SUM(COALESCE(fcs_sum, 0)) AS total_crc_errors
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


@router.get('/monitoring/health-devices')
def monitoring_health_devices(
    health_status: str = Query(default='all'),
    availability_status: str = Query(default='all'),
    collection_status: str = Query(default='all'),
    site: str = Query(default='all'),
    role: str = Query(default='all'),
    severity: str = Query(default='all'),
    problem_type: str = Query(default='all'),
    limit: int = Query(default=100, ge=1, le=500),
    user=require_role("Viewer"),
):
    """Return the exact device set behind a monitoring-center metric.

    This endpoint is intentionally read-only and evaluates the same health
    model used by ``/monitoring/overview``.  The UI can therefore drill down
    without rebuilding a second, subtly different status calculation.
    """
    conn = get_db_connection()
    try:
        evaluated = annotate_devices_with_health(conn, load_devices_for_health(conn))
        health_filter = (health_status or 'all').strip().lower()
        availability_filter = (availability_status or 'all').strip().lower()
        collection_filter = (collection_status or 'all').strip().lower()
        site_filter = (site or 'all').strip().lower()
        role_filter = (role or 'all').strip().lower()
        severity_filter = (severity or 'all').strip().lower()
        problem_filter = (problem_type or 'all').strip().lower()

        def matches_problem(device: dict) -> bool:
            if problem_filter == 'all':
                return True
            reasons = ' '.join(str(item) for item in (device.get('health_reasons') or [])).lower()
            collection_failures = ' '.join(
                f"{item.get('collector', '')} {item.get('status', '')} {item.get('message', '')}"
                for item in (device.get('collection_failures') or [])
                if isinstance(item, dict)
            ).lower()
            haystack = f"{reasons} {collection_failures} {device.get('health_summary') or ''}".lower()
            return problem_filter in haystack

        items = [
            device for device in evaluated
            if (health_filter == 'all' or str(device.get('health_status') or 'unknown').lower() == health_filter)
            and (availability_filter == 'all' or str(device.get('availability_status') or 'unknown').lower() == availability_filter)
            and (collection_filter == 'all' or str(device.get('collection_status') or 'unknown').lower() == collection_filter)
            and (site_filter == 'all' or str(device.get('site') or '').strip().lower() == site_filter)
            and (role_filter == 'all' or str(device.get('role') or '').strip().lower() == role_filter)
            and (
                severity_filter == 'all'
                or (severity_filter == 'critical' and int(device.get('critical_open_alerts') or 0) > 0)
                or (severity_filter == 'major' and int(device.get('major_open_alerts') or 0) > 0)
                or (severity_filter == 'warning' and int(device.get('warning_open_alerts') or 0) > 0)
            )
            and matches_problem(device)
        ]
        items.sort(key=lambda device: (
            {'critical': 0, 'warning': 1, 'unknown': 2, 'healthy': 3}.get(str(device.get('health_status') or 'unknown'), 9),
            str(device.get('hostname') or ''),
        ))
        safe_items = [
            {
                key: device.get(key)
                for key in (
                    'id', 'hostname', 'ip_address', 'platform', 'role', 'site', 'status',
                    'availability_status', 'collection_status', 'collection_last_success_at',
                    'data_confidence', 'health_status', 'health_score', 'health_score_available',
                    'health_summary', 'health_reasons', 'open_alert_count',
                    'critical_open_alerts', 'major_open_alerts', 'warning_open_alerts',
                )
            }
            for device in items[:limit]
        ]
        return {
            'items': safe_items,
            'total': len(items),
            'filters': {
                'health_status': health_filter,
                'availability_status': availability_filter,
                'collection_status': collection_filter,
                'site': site_filter,
                'role': role_filter,
                'severity': severity_filter,
                'problem_type': problem_filter,
            },
        }
    finally:
        conn.close()


@router.get('/monitoring/incidents')
def monitoring_incidents(
    status: str = Query(default='active'),
    severity: str = Query(default='all'),
    site: str = Query(default='all'),
    device_id: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _user=require_role('Viewer'),
):
    """Return the incident projection for NOC triage and drill-down."""
    conn = get_db_connection()
    try:
        return list_incidents(
            conn,
            status=status,
            severity=severity,
            site=site,
            device_id=device_id,
            page=page,
            page_size=page_size,
        )
    finally:
        conn.close()


@router.get('/monitoring/incidents/{incident_id}')
def monitoring_incident_detail(incident_id: str, _user=require_role('Viewer')):
    conn = get_db_connection()
    try:
        item = get_incident(conn, incident_id)
        if item is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        return {'item': item}
    finally:
        conn.close()


@router.get('/monitoring/incidents/{incident_id}/impact')
def monitoring_incident_impact(incident_id: str, _user=require_role('Viewer')):
    """Return the affected devices and known topology links for one incident."""
    conn = get_db_connection()
    try:
        item = get_incident_impact(conn, incident_id)
        if item is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        return item
    finally:
        conn.close()


@router.get('/monitoring/incidents/{incident_id}/playbook-recommendations')
def monitoring_incident_playbook_recommendations(incident_id: str, user=require_role('Viewer')):
    """Return safe, platform-aware read-only Playbook recommendations."""
    conn = get_db_connection()
    try:
        item = recommend_incident_playbooks(conn, incident_id)
        if item is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        actor = str(user.get('username') or 'system').strip() or 'system'
        append_incident_timeline(
            conn,
            incident_id,
            'playbook_recommendations_viewed',
            actor,
            'Platform-aware read-only Playbook recommendations viewed',
            {'count': len(item.get('items') or []), 'platform': (item.get('device') or {}).get('platform')},
        )
        conn.commit()
        return item
    finally:
        conn.close()


@router.post('/monitoring/incidents/{incident_id}/playbooks/execute')
async def execute_monitoring_incident_playbook(
    incident_id: str,
    payload: MonitoringIncidentPlaybookExecuteRequest,
    user=require_role('Operator'),
):
    """Manually run one recommended read-only Playbook for the incident device.

    This endpoint intentionally refuses every scenario that contains an
    execute phase.  Configuration changes continue through the normal
    Playbook/change-order approval contract.
    """
    conn = get_db_connection()
    try:
        recommendation_set = recommend_incident_playbooks(conn, incident_id)
        if recommendation_set is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        recommendation = next(
            (item for item in recommendation_set.get('items') or [] if item.get('scenario_id') == payload.scenario_id),
            None,
        )
        if not recommendation or not recommendation.get('manual_execution_allowed'):
            raise HTTPException(status_code=400, detail='Only a recommended read-only Playbook can be started from an incident')
        device_id = str(recommendation.get('device_id') or '').strip()
        if not device_id:
            raise HTTPException(status_code=400, detail='Incident has no primary device')

        from api.playbooks.engine import _run_playbook
        from api.playbooks.scenarios import _all_scenarios, resolve_platform_phases

        scenario = next((item for item in _all_scenarios() if item.get('id') == payload.scenario_id), None)
        if not scenario:
            raise HTTPException(status_code=404, detail='Playbook scenario not found')
        phases_catalog = scenario.get('platform_phases') or {}
        device_row = conn.execute('SELECT platform, vendor FROM devices WHERE id = ?', (device_id,)).fetchone()
        if not device_row:
            raise HTTPException(status_code=404, detail='Incident device not found')
        try:
            phases, resolved_platform = resolve_platform_phases(
                phases_catalog,
                recommendation_set.get('device', {}).get('platform'),
                device_row['vendor'],
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if phases.get('execute'):
            raise HTTPException(status_code=400, detail='Configuration Playbooks cannot be executed from monitoring incidents')
        execution_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        scenario_name = scenario.get('name') or payload.scenario_id
        conn.execute(
            '''INSERT INTO playbook_executions
               (id, scenario_id, scenario_name, platform, device_ids, variables, status, dry_run, author, concurrency, phases_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, 1, ?, ?, ?)''',
            (
                execution_id,
                payload.scenario_id,
                scenario_name,
                resolved_platform,
                json.dumps([device_id]),
                json.dumps(payload.variables or {}, ensure_ascii=False),
                str(user.get('username') or 'system'),
                json.dumps(phases_catalog, ensure_ascii=False),
                now,
                now,
            ),
        )
        append_incident_timeline(
            conn,
            incident_id,
            'playbook_started',
            str(user.get('username') or 'system'),
            f'Read-only Playbook {scenario_name} started for incident device',
            {'execution_id': execution_id, 'scenario_id': payload.scenario_id, 'platform': resolved_platform, 'device_id': device_id},
        )
        conn.commit()
    finally:
        conn.close()

    asyncio.create_task(_run_playbook(execution_id, [device_id], phases_catalog, payload.variables or {}, False, 1, resolved_platform, 0))
    log_audit_event(
        event_type='MONITORING_PLAYBOOK_EXECUTION',
        category='monitoring',
        severity='medium',
        status='pending',
        summary=f'Started read-only Playbook {scenario_name} from incident {incident_id}',
        actor_username=user.get('username'),
        actor_role=user.get('role'),
        target_type='monitoring_incident',
        target_id=incident_id,
        target_name=scenario_name,
        execution_id=execution_id,
        details={'scenario_id': payload.scenario_id, 'platform': resolved_platform, 'device_id': device_id, 'read_only': True},
    )
    return {'execution_id': execution_id, 'status': 'pending', 'scenario_id': payload.scenario_id, 'platform': resolved_platform, 'read_only': True}


@router.post('/monitoring/incidents/{incident_id}/acknowledge')
def acknowledge_monitoring_incident(
    incident_id: str,
    payload: MonitoringIncidentStatusRequest,
    user=require_role('Operator'),
):
    actor = str(user.get('username') or 'system').strip() or 'system'
    next_status = payload.status
    conn = get_db_connection()
    try:
        try:
            item = update_incident_status(conn, incident_id, next_status, actor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if item is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        log_audit_event(
            event_type='MONITORING_INCIDENT_STATUS',
            category='monitoring',
            severity='medium',
            status='success',
            summary=f'Updated monitoring incident {incident_id} to {next_status}',
            actor_username=actor,
            actor_role=user.get('role'),
            target_type='monitoring_incident',
            target_id=incident_id,
            target_name=item.get('title'),
            device_id=item.get('primary_device_id'),
            details={'status': next_status},
        )
        return {'success': True, 'item': item}
    finally:
        conn.close()


@router.post('/monitoring/incidents/{incident_id}/assign')
def assign_monitoring_incident(
    incident_id: str,
    payload: MonitoringIncidentAssignRequest,
    user=require_role('Operator'),
):
    assignee = payload.assignee.strip()
    if not assignee:
        raise HTTPException(status_code=400, detail='assignee is required')
    conn = get_db_connection()
    try:
        item = assign_incident(conn, incident_id, assignee)
        if item is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        log_audit_event(
            event_type='MONITORING_INCIDENT_ASSIGN',
            category='monitoring',
            severity='medium',
            status='success',
            summary=f'Assigned monitoring incident {incident_id} to {assignee}',
            actor_username=user.get('username'),
            actor_role=user.get('role'),
            target_type='monitoring_incident',
            target_id=incident_id,
            target_name=item.get('title'),
            device_id=item.get('primary_device_id'),
            details={'assignee': assignee},
        )
        return {'success': True, 'item': item}
    finally:
        conn.close()


@router.post('/monitoring/incidents/{incident_id}/resolve')
def resolve_monitoring_incident(
    incident_id: str,
    payload: Optional[MonitoringIncidentStatusRequest] = Body(default=None),
    user=require_role('Operator'),
):
    actor = str(user.get('username') or 'system').strip() or 'system'
    conn = get_db_connection()
    try:
        item = update_incident_status(conn, incident_id, 'resolved', actor)
        if item is None:
            raise HTTPException(status_code=404, detail='Incident not found')
        log_audit_event(
            event_type='MONITORING_INCIDENT_RESOLVE',
            category='monitoring',
            severity='medium',
            status='success',
            summary=f'Resolved monitoring incident {incident_id}',
            actor_username=actor,
            actor_role=user.get('role'),
            target_type='monitoring_incident',
            target_id=incident_id,
            target_name=item.get('title'),
            device_id=item.get('primary_device_id'),
            details={'status': 'resolved'},
        )
        return {'success': True, 'item': item}
    finally:
        conn.close()


# ── Internet outbound health APIs ──


class OutboundTargetPayload(BaseModel):
    id: Optional[str] = None
    target_name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=443, ge=1, le=65535)
    probe_type: str = Field(default="TCP_CONNECT", max_length=32)
    group_name: str = Field(default="business", max_length=32)
    url: str = Field(default="", max_length=2048)
    expected_status_code: int = Field(default=200, ge=100, le=599)
    expected_keyword: str = Field(default="", max_length=128)
    timeout_ms: int = Field(default=2000, ge=100, le=10000)
    enabled: bool = True


class WanLinkPayload(BaseModel):
    id: Optional[str] = None
    link_name: str = Field(min_length=1, max_length=128)
    site_id: str = ""
    site_name: str = ""
    device_id: str = Field(min_length=1)
    interface_id: str = Field(min_length=1)
    interface_name: str = ""
    if_index: Optional[int] = Field(default=None, ge=1)
    provider: str = ""
    circuit_number: str = ""
    public_ip: str = ""
    link_type: str = "Internet"
    link_role: Literal['primary', 'backup', 'load_balanced'] = "primary"
    direction_mode: Literal['normal', 'reversed'] = "normal"
    contracted_download_mbps: float = Field(gt=0, le=10_000_000)
    contracted_upload_mbps: float = Field(gt=0, le=10_000_000)
    collection_interval_sec: int = Field(default=60, ge=30, le=3600)
    timezone: str = "Asia/Shanghai"
    enabled: bool = True
    maintenance_window: str = ""
    notes: str = ""


class WanMaintenancePayload(BaseModel):
    id: Optional[str] = None
    name: str = Field(min_length=1, max_length=160)
    site_id: str = ''
    link_id: str = ''
    device_id: str = ''
    link_group_id: str = ''
    starts_at: str
    ends_at: str
    timezone: str = 'Asia/Shanghai'
    recurrence: Literal['once', 'daily', 'weekly', 'monthly'] = 'once'
    reason: str = ''
    enabled: bool = True


class WanAlertWorkflowPayload(BaseModel):
    action: Literal['acknowledge', 'close']
    note: str = Field(default='', max_length=1000)


class WanReportPayload(BaseModel):
    report_type: Literal['daily', 'weekly', 'monthly']
    period_start: str
    period_end: str


class WanProbeBindingPayload(BaseModel):
    id: Optional[str] = None
    link_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    route_mode: str = 'default'
    source_ip: str = ''
    priority: int = Field(default=100, ge=1, le=10000)
    enabled: bool = True


class WanCapacityReviewPayload(BaseModel):
    status: Literal['observing', 'review', 'handled', 'not_applicable']
    note: str = Field(default='', max_length=1000)


class WanLinkGroupMemberPayload(BaseModel):
    link_id: str = Field(min_length=1)
    role: Literal['primary', 'backup', 'load_balanced'] = 'primary'
    priority: int = Field(default=100, ge=1, le=10000)
    weight: int = Field(default=1, ge=1, le=1000)


class WanLinkGroupPayload(BaseModel):
    id: Optional[str] = None
    group_name: str = Field(min_length=1, max_length=128)
    mode: Literal['primary_backup', 'load_balanced'] = 'primary_backup'
    site_id: str = ''
    provider: str = ''
    enabled: bool = True
    members: list[WanLinkGroupMemberPayload] = Field(default_factory=list)


_manual_probe_lock = threading.Lock()
_manual_probe_last_at: dict[str, float] = {}
_MANUAL_PROBE_COOLDOWN_SECONDS = 5.0
_wan_collection_lock = threading.Lock()


def _outbound_audit(request: Request, user: dict, event_type: str, summary: str, **kwargs) -> None:
    try:
        log_audit_event(
            event_type=event_type,
            category="monitoring",
            severity="medium",
            status="success",
            summary=summary,
            actor_id=user.get("id"),
            actor_username=user.get("username"),
            actor_role=user.get("role"),
            source_ip=request.client.host if request.client else None,
            **kwargs,
        )
    except Exception:
        logger.warning("Failed to write outbound probe audit event", exc_info=True)

@router.get('/monitoring/outbound-status')
def get_monitoring_outbound_status(
    history_hours: int = Query(default=24, ge=1, le=168),
    user=require_role("Viewer"),
):
    from services.outbound_probe_service import get_outbound_status
    return get_outbound_status(history_hours=history_hours)


@router.get('/monitoring/outbound-targets')
def get_monitoring_outbound_targets(user=require_role("Viewer")):
    from services.outbound_probe_service import list_outbound_targets
    items = list_outbound_targets()
    return {"items": items, "total": len(items)}


@router.get('/monitoring/outbound-targets/{target_id}/history')
def get_monitoring_outbound_target_history(
    target_id: str,
    history_hours: int = Query(default=24, ge=1, le=168),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    user=require_role("Viewer"),
):
    from services.outbound_probe_service import get_outbound_target_history
    if start_time and end_time:
        try:
            from datetime import datetime, timedelta
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            if end_dt < start_dt:
                raise HTTPException(status_code=400, detail={"code": "INVALID_TIME_RANGE", "message": "End time must be after start time"})
            if (end_dt - start_dt) > timedelta(days=7):
                raise HTTPException(status_code=400, detail={"code": "TIME_SPAN_EXCEEDED", "message": "Query span cannot exceed 7 days"})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_TIME_FORMAT", "message": "Time must be in ISO 8601 format"}) from exc

    item = get_outbound_target_history(
        target_id=target_id,
        history_hours=history_hours,
        start_time=start_time,
        end_time=end_time,
    )
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "TARGET_NOT_FOUND", "message": "Target not found"})
    return item


@router.post('/monitoring/outbound-targets')
def upsert_monitoring_outbound_target(
    request: Request,
    payload: OutboundTargetPayload = Body(...),
    user=require_role("Operator"),
):
    from services.outbound_probe_service import upsert_outbound_target
    try:
        item = upsert_outbound_target(payload.model_dump(exclude_none=True), target_id=payload.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_TARGET", "message": str(exc)}) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail={"code": "TARGET_NAME_EXISTS", "message": "Target name must be unique"}) from exc
        raise HTTPException(status_code=500, detail="Unable to save outbound probe target") from exc
    _outbound_audit(
        request,
        user,
        "OUTBOUND_TARGET_UPSERT",
        f"Updated outbound probe target {item.get('target_name')}",
        target_type="outbound_probe_target",
        target_id=item.get("id"),
        target_name=item.get("target_name"),
        after={key: item.get(key) for key in ("target_name", "host", "port", "probe_type", "group_name", "enabled")},
    )
    return {"success": True, "item": item}


@router.patch('/monitoring/outbound-targets/{target_id}')
def patch_monitoring_outbound_target(
    target_id: str,
    request: Request,
    payload: OutboundTargetPayload = Body(...),
    user=require_role("Operator"),
):
    from services.outbound_probe_service import upsert_outbound_target
    try:
        item = upsert_outbound_target(payload.model_dump(exclude_none=True), target_id=target_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_TARGET", "message": str(exc)}) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail={"code": "TARGET_NAME_EXISTS", "message": "Target name must be unique"}) from exc
        raise HTTPException(status_code=500, detail="Unable to update outbound probe target") from exc
    _outbound_audit(
        request,
        user,
        "OUTBOUND_TARGET_UPDATE",
        f"Updated outbound probe target {item.get('target_name')}",
        target_type="outbound_probe_target",
        target_id=target_id,
        target_name=item.get("target_name"),
    )
    return {"success": True, "item": item}


@router.delete('/monitoring/outbound-targets/{target_id}')
def delete_monitoring_outbound_target(target_id: str, request: Request, user=require_role("Operator")):
    from services.outbound_probe_service import delete_outbound_target
    if not delete_outbound_target(target_id):
        raise HTTPException(status_code=404, detail={"code": "TARGET_NOT_FOUND", "message": "Target not found"})
    _outbound_audit(
        request,
        user,
        "OUTBOUND_TARGET_DELETE",
        f"Deleted outbound probe target {target_id}",
        target_type="outbound_probe_target",
        target_id=target_id,
    )
    return {"success": True, "id": target_id}


@router.get('/monitoring/outbound-egress-events')
def get_monitoring_outbound_egress_events(
    limit: int = Query(default=50, ge=1, le=200),
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM outbound_egress_ip_events ORDER BY observed_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": len(rows)}
    finally:
        conn.close()


@router.post('/monitoring/outbound-trigger')
def trigger_outbound_probe_manual(request: Request, user=require_role("Operator")):
    actor_key = str(user.get("id") or user.get("username") or (request.client.host if request.client else "unknown"))
    now = time.monotonic()
    with _manual_probe_lock:
        last_at = _manual_probe_last_at.get(actor_key, 0.0)
        if now - last_at < _MANUAL_PROBE_COOLDOWN_SECONDS:
            raise HTTPException(status_code=429, detail={"code": "PROBE_RATE_LIMITED", "message": "Please wait before triggering another probe"})
        _manual_probe_last_at[actor_key] = now
    if not _manual_probe_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail={"code": "PROBE_ALREADY_RUNNING", "message": "An outbound probe is already running"})
    try:
        from services.outbound_probe_service import run_outbound_probe_once
        result = run_outbound_probe_once(include_egress_ip=True)
        _outbound_audit(request, user, "OUTBOUND_PROBE_TRIGGER", "Manually triggered outbound probe", details={"run_id": result.get("run_id")})
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "PROBE_INVALID", "message": str(exc)}) from exc
    except Exception as exc:
        logger.exception("Manual outbound probe failed")
        raise HTTPException(status_code=500, detail={"code": "PROBE_FAILED", "message": "Outbound probe failed"}) from exc
    finally:
        _manual_probe_lock.release()


# ── P0 internet egress link APIs ──


@router.get('/monitoring/wan-options')
def get_monitoring_wan_options(site_id: str = Query(default=''), device_id: str = Query(default=''), user=require_role("Viewer")):
    from services.wan_link_service import list_wan_link_options
    return list_wan_link_options(site_id=site_id, device_id=device_id)


@router.get('/monitoring/wan-links')
def get_monitoring_wan_links(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    site_id: str = Query(default=''),
    provider: str = Query(default=''),
    health_status: str = Query(default=''),
    link_role: str = Query(default=''),
    group_id: str = Query(default=''),
    keyword: str = Query(default=''),
    user=require_role("Viewer"),
):
    from services.wan_link_service import list_wan_links
    try:
        return list_wan_links(page=page, page_size=page_size, site_id=site_id, provider=provider, health_status=health_status, link_role=link_role, group_id=group_id, keyword=keyword)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'INVALID_WAN_FILTER', 'message': str(exc)}) from exc


@router.get('/monitoring/wan-links/{link_id}/history')
def get_monitoring_wan_link_history(
    link_id: str,
    history_minutes: int | None = Query(default=None, ge=5, le=43_200),
    history_hours: int | None = Query(default=None, ge=1, le=720),
    user=require_role("Viewer"),
):
    from services.wan_link_service import get_wan_link_history
    duration_minutes = history_minutes if history_minutes is not None else (history_hours * 60 if history_hours is not None else 60)
    payload = get_wan_link_history(link_id, history_minutes=duration_minutes)
    if payload is None:
        raise HTTPException(status_code=404, detail={"code": "WAN_LINK_NOT_FOUND", "message": "WAN link not found"})
    return payload


@router.get('/monitoring/wan-links/{link_id}')
def get_monitoring_wan_link(link_id: str, user=require_role('Viewer')):
    from services.wan_link_service import get_wan_link
    payload = get_wan_link(link_id)
    if payload is None:
        raise HTTPException(status_code=404, detail={'code': 'WAN_LINK_NOT_FOUND', 'message': 'WAN link not found'})
    return {'item': payload}


@router.post('/monitoring/wan-links/test-config')
def test_monitoring_wan_link_configuration(payload: WanLinkPayload, request: Request, user=require_role('Operator')):
    """Read-only pre-save test for a selected device/interface binding."""
    from services.wan_link_service import test_wan_link_configuration
    result = asyncio.run(test_wan_link_configuration(payload.model_dump(exclude_none=True)))
    _outbound_audit(request, user, 'WAN_LINK_TEST_CONFIG', 'Tested an unsaved WAN link configuration', target_type='wan_link_configuration', target_id=payload.interface_id, details={'status': result.get('status'), 'error_code': result.get('error_code')})
    return result


@router.post('/monitoring/wan-links')
def create_monitoring_wan_link(
    request: Request,
    payload: WanLinkPayload,
    user=require_role("Operator"),
):
    from services.wan_link_service import upsert_wan_link
    try:
        item = upsert_wan_link(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_WAN_LINK", "message": str(exc)}) from exc
    except Exception as exc:
        if 'UNIQUE' in str(exc).upper():
            raise HTTPException(status_code=409, detail={"code": "WAN_LINK_EXISTS", "message": "The device interface is already bound to a WAN link"}) from exc
        raise HTTPException(status_code=500, detail={"code": "WAN_LINK_SAVE_FAILED", "message": "Unable to save WAN link"}) from exc
    _outbound_audit(request, user, "WAN_LINK_CREATE", f"Created WAN link {item.get('link_name')}", target_type="wan_link", target_id=item.get("id"))
    return {"success": True, "item": item}


@router.patch('/monitoring/wan-links/{link_id}')
def update_monitoring_wan_link(
    link_id: str,
    request: Request,
    payload: WanLinkPayload,
    user=require_role("Operator"),
):
    from services.wan_link_service import upsert_wan_link
    try:
        item = upsert_wan_link(payload.model_dump(exclude_none=True), link_id=link_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_WAN_LINK", "message": str(exc)}) from exc
    except Exception as exc:
        if 'UNIQUE' in str(exc).upper():
            raise HTTPException(status_code=409, detail={"code": "WAN_LINK_EXISTS", "message": "The device interface is already bound to a WAN link"}) from exc
        raise HTTPException(status_code=500, detail={"code": "WAN_LINK_SAVE_FAILED", "message": "Unable to update WAN link"}) from exc
    _outbound_audit(request, user, "WAN_LINK_UPDATE", f"Updated WAN link {item.get('link_name')}", target_type="wan_link", target_id=link_id)
    return {"success": True, "item": item}


@router.delete('/monitoring/wan-links/{link_id}')
def delete_monitoring_wan_link(link_id: str, request: Request, user=require_role("Operator")):
    from services.wan_link_service import delete_wan_link
    if not delete_wan_link(link_id):
        raise HTTPException(status_code=404, detail={"code": "WAN_LINK_NOT_FOUND", "message": "WAN link not found"})
    _outbound_audit(request, user, "WAN_LINK_DELETE", f"Deleted WAN link {link_id}", target_type="wan_link", target_id=link_id)
    return {"success": True, "id": link_id}


@router.post('/monitoring/wan-trigger')
def trigger_monitoring_wan_collection(request: Request, user=require_role("Operator")):
    global _manual_probe_last_at
    actor_key = str(user.get('id') or user.get('username') or 'unknown')
    now = time.monotonic()
    with _manual_probe_lock:
        if now - _manual_probe_last_at.get(f'wan:{actor_key}', 0.0) < _MANUAL_PROBE_COOLDOWN_SECONDS:
            raise HTTPException(status_code=429, detail={'code': 'WAN_RATE_LIMITED', 'message': 'Please wait before triggering another WAN collection'})
        _manual_probe_last_at[f'wan:{actor_key}'] = now
    if not _wan_collection_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail={'code': 'WAN_COLLECTION_ALREADY_RUNNING', 'message': 'A WAN collection is already running'})
    try:
        from services.wan_link_service import run_wan_collection_once
        result = run_wan_collection_once()
        _outbound_audit(request, user, "WAN_COLLECTION_TRIGGER", "Manually triggered WAN link collection", target_type="wan_link_collection")
        return result
    except Exception as exc:
        logger.exception("Manual WAN collection failed")
        raise HTTPException(status_code=500, detail={'code': 'WAN_COLLECTION_FAILED', 'message': 'WAN collection failed'}) from exc
    finally:
        _wan_collection_lock.release()


@router.post('/monitoring/wan-links/{link_id}/test')
def test_monitoring_wan_link(link_id: str, request: Request, user=require_role('Operator')):
    from services.wan_link_service import test_wan_link_collection
    result = asyncio.run(test_wan_link_collection(link_id))
    if result is None:
        raise HTTPException(status_code=404, detail={'code': 'WAN_LINK_NOT_FOUND', 'message': 'WAN link not found'})
    _outbound_audit(request, user, 'WAN_LINK_TEST', f'Tested WAN link {link_id}', target_type='wan_link', target_id=link_id, details={'status': result.get('status'), 'error_code': result.get('error_code')})
    return result


@router.get('/monitoring/wan-alert-events')
def get_monitoring_wan_alert_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str = Query(default=''),
    severity: str = Query(default=''),
    site_id: str = Query(default=''),
    provider: str = Query(default=''),
    link_id: str = Query(default=''),
    keyword: str = Query(default=''),
    start_at: str = Query(default=''),
    end_at: str = Query(default=''),
    user=require_role('Viewer'),
):
    from services.wan_link_service import list_wan_alert_events
    try:
        return list_wan_alert_events(
            page=page,
            page_size=page_size,
            status=status,
            severity=severity,
            site_id=site_id,
            provider=provider,
            link_id=link_id,
            keyword=keyword,
            start_at=start_at,
            end_at=end_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'INVALID_ALERT_FILTER', 'message': str(exc)}) from exc


@router.patch('/monitoring/wan-alert-events/{event_id}')
def update_monitoring_wan_alert(event_id: str, payload: WanAlertWorkflowPayload, request: Request, user=require_role('Operator')):
    from services.wan_p1_service import update_wan_alert_workflow
    try:
        item = update_wan_alert_workflow(event_id, payload.action, {**user, 'note': payload.note})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'INVALID_ALERT_ACTION', 'message': str(exc)}) from exc
    if item is None:
        raise HTTPException(status_code=404, detail={'code': 'WAN_ALERT_NOT_FOUND', 'message': 'WAN alert event not found'})
    _outbound_audit(request, user, f'WAN_ALERT_{payload.action.upper()}', f'{payload.action.title()} WAN alert {event_id}', target_type='wan_alert_event', target_id=event_id)
    return {'success': True, 'item': item}


@router.get('/monitoring/wan-maintenance-windows')
def get_monitoring_wan_maintenance_windows(user=require_role('Viewer')):
    from services.wan_p1_service import list_wan_maintenance_windows
    return {'items': list_wan_maintenance_windows()}


@router.post('/monitoring/wan-maintenance-windows')
def create_monitoring_wan_maintenance_window(payload: WanMaintenancePayload, request: Request, user=require_role('Operator')):
    from services.wan_p1_service import upsert_wan_maintenance_window
    try:
        item = upsert_wan_maintenance_window(payload.model_dump(exclude_none=True), user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'INVALID_MAINTENANCE_WINDOW', 'message': str(exc)}) from exc
    _outbound_audit(request, user, 'WAN_MAINTENANCE_CREATE', f'Created WAN maintenance window {item.get("name")}', target_type='wan_maintenance_window', target_id=item.get('id'))
    return {'success': True, 'item': item}


@router.delete('/monitoring/wan-maintenance-windows/{window_id}')
def delete_monitoring_wan_maintenance_window(window_id: str, request: Request, user=require_role('Operator')):
    from services.wan_p1_service import delete_wan_maintenance_window
    if not delete_wan_maintenance_window(window_id):
        raise HTTPException(status_code=404, detail={'code': 'WAN_MAINTENANCE_NOT_FOUND', 'message': 'WAN maintenance window not found'})
    _outbound_audit(request, user, 'WAN_MAINTENANCE_DELETE', f'Deleted WAN maintenance window {window_id}', target_type='wan_maintenance_window', target_id=window_id)
    return {'success': True, 'id': window_id}


@router.patch('/monitoring/wan-maintenance-windows/{window_id}')
def update_monitoring_wan_maintenance_window(window_id: str, payload: WanMaintenancePayload, request: Request, user=require_role('Operator')):
    from services.wan_p1_service import upsert_wan_maintenance_window
    try:
        item = upsert_wan_maintenance_window(payload.model_dump(exclude_none=True), user, window_id=window_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'INVALID_MAINTENANCE_WINDOW', 'message': str(exc)}) from exc
    _outbound_audit(request, user, 'WAN_MAINTENANCE_UPDATE', f'Updated WAN maintenance window {window_id}', target_type='wan_maintenance_window', target_id=window_id)
    return {'success': True, 'item': item}


@router.post('/monitoring/wan-reports')
def create_monitoring_wan_report(payload: WanReportPayload, request: Request, user=require_role('Operator')):
    from services.wan_p1_service import generate_wan_report
    try:
        result = generate_wan_report(payload.report_type, payload.period_start, payload.period_end, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'INVALID_WAN_REPORT', 'message': str(exc)}) from exc
    _outbound_audit(request, user, 'WAN_REPORT_GENERATE', f'Generated {payload.report_type} WAN report', target_type='wan_report', target_id=result.get('report_id'))
    return {'success': True, 'item': result}


@router.get('/monitoring/wan-reports')
def get_monitoring_wan_reports(report_type: str = Query(default=''), limit: int = Query(default=20, ge=1, le=100), user=require_role('Viewer')):
    from services.wan_p1_service import list_wan_reports
    return {'items': list_wan_reports(report_type=report_type, limit=limit)}


@router.get('/monitoring/wan-reports/{report_id}')
def get_monitoring_wan_report(report_id: str, user=require_role('Viewer')):
    from services.wan_p1_service import get_wan_report
    item = get_wan_report(report_id)
    if item is None:
        raise HTTPException(status_code=404, detail={'code': 'WAN_REPORT_NOT_FOUND', 'message': 'WAN report not found'})
    return {'item': item}


@router.post('/monitoring/wan-reports/{report_id}/export')
def export_monitoring_wan_report(report_id: str, request: Request, user=require_role('Operator')):
    from services.wan_p1_service import mark_wan_report_exported
    item = mark_wan_report_exported(report_id, user)
    if item is None:
        raise HTTPException(status_code=404, detail={'code': 'WAN_REPORT_NOT_FOUND', 'message': 'Completed WAN report not found'})
    _outbound_audit(request, user, 'WAN_REPORT_EXPORT', f'Exported WAN report {report_id}', target_type='wan_report', target_id=report_id)
    return {'success': True, 'item': item}


@router.get('/monitoring/wan-probe-bindings')
def get_monitoring_wan_probe_bindings(link_id: str = Query(default=''), target_id: str = Query(default=''), user=require_role('Viewer')):
    from services.wan_p2_service import list_probe_bindings
    return {'items': list_probe_bindings(link_id=link_id, target_id=target_id)}


@router.post('/monitoring/wan-probe-bindings')
def create_monitoring_wan_probe_binding(payload: WanProbeBindingPayload, request: Request, user=require_role('Operator')):
    from services.wan_p2_service import upsert_probe_binding
    try:
        item = upsert_probe_binding(payload.model_dump(exclude_none=True), user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'INVALID_WAN_BINDING', 'message': str(exc)}) from exc
    except Exception as exc:
        if 'UNIQUE' in str(exc).upper():
            raise HTTPException(status_code=409, detail={'code': 'WAN_BINDING_EXISTS', 'message': 'This probe target is already bound to the link'}) from exc
        raise HTTPException(status_code=500, detail={'code': 'WAN_BINDING_SAVE_FAILED', 'message': 'Unable to save probe binding'}) from exc
    _outbound_audit(request, user, 'WAN_PROBE_BINDING_CREATE', f'Created WAN probe binding {item.get("id")}', target_type='wan_probe_binding', target_id=item.get('id'))
    return {'success': True, 'item': item}


@router.patch('/monitoring/wan-probe-bindings/{binding_id}')
def update_monitoring_wan_probe_binding(binding_id: str, payload: WanProbeBindingPayload, request: Request, user=require_role('Operator')):
    from services.wan_p2_service import upsert_probe_binding
    try:
        item = upsert_probe_binding(payload.model_dump(exclude_none=True), user, binding_id=binding_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'INVALID_WAN_BINDING', 'message': str(exc)}) from exc
    _outbound_audit(request, user, 'WAN_PROBE_BINDING_UPDATE', f'Updated WAN probe binding {binding_id}', target_type='wan_probe_binding', target_id=binding_id)
    return {'success': True, 'item': item}


@router.delete('/monitoring/wan-probe-bindings/{binding_id}')
def delete_monitoring_wan_probe_binding(binding_id: str, request: Request, user=require_role('Operator')):
    from services.wan_p2_service import delete_probe_binding
    if not delete_probe_binding(binding_id, user):
        raise HTTPException(status_code=404, detail={'code': 'WAN_BINDING_NOT_FOUND', 'message': 'WAN probe binding not found'})
    _outbound_audit(request, user, 'WAN_PROBE_BINDING_DELETE', f'Deleted WAN probe binding {binding_id}', target_type='wan_probe_binding', target_id=binding_id)
    return {'success': True, 'id': binding_id}


@router.get('/monitoring/wan-correlations')
def get_monitoring_wan_correlations(page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), status: str = Query(default=''), code: str = Query(default=''), severity: str = Query(default=''), site_id: str = Query(default=''), provider: str = Query(default=''), keyword: str = Query(default=''), start_at: str = Query(default=''), end_at: str = Query(default=''), user=require_role('Viewer')):
    from services.wan_p2_service import list_wan_correlation_events
    return list_wan_correlation_events(page=page, page_size=page_size, status=status, code=code, severity=severity, site_id=site_id, provider=provider, keyword=keyword, start_at=start_at, end_at=end_at)


@router.get('/monitoring/wan-correlations/{event_id}')
def get_monitoring_wan_correlation(event_id: str, user=require_role('Viewer')):
    from services.wan_p2_service import get_wan_correlation_event
    item = get_wan_correlation_event(event_id)
    if item is None:
        raise HTTPException(status_code=404, detail={'code': 'WAN_CORRELATION_NOT_FOUND', 'message': 'WAN correlation event not found'})
    return {'item': item}


@router.get('/monitoring/wan-capacity-recommendations')
def get_monitoring_wan_capacity_recommendations(link_id: str = Query(default=''), user=require_role('Viewer')):
    from services.wan_p2_service import list_wan_capacity_recommendations
    return {'items': list_wan_capacity_recommendations(link_id)}


@router.patch('/monitoring/wan-capacity-recommendations/{recommendation_id}')
def review_monitoring_wan_capacity(recommendation_id: str, payload: WanCapacityReviewPayload, request: Request, user=require_role('Operator')):
    from services.wan_p2_service import update_wan_capacity_recommendation
    try:
        item = update_wan_capacity_recommendation(recommendation_id, payload.status, user, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'INVALID_WAN_CAPACITY_STATUS', 'message': str(exc)}) from exc
    if item is None:
        raise HTTPException(status_code=404, detail={'code': 'WAN_CAPACITY_NOT_FOUND', 'message': 'WAN capacity recommendation not found'})
    _outbound_audit(request, user, 'WAN_CAPACITY_REVIEW', f'Reviewed WAN capacity recommendation {recommendation_id}', target_type='wan_capacity_recommendation', target_id=recommendation_id, details={'status': payload.status})
    return {'success': True, 'item': item}


@router.get('/monitoring/wan-cockpit')
def get_monitoring_wan_cockpit(user=require_role('Viewer')):
    from services.wan_p2_service import get_wan_cockpit
    return get_wan_cockpit()


@router.post('/monitoring/wan-correlation-recompute')
def recompute_monitoring_wan_correlations(request: Request, user=require_role('Operator')):
    from services.wan_p2_service import recompute_wan_correlations
    result = recompute_wan_correlations()
    _outbound_audit(request, user, 'WAN_CORRELATION_RECOMPUTE', 'Recomputed WAN correlation events', target_type='wan_correlation')
    return result


@router.post('/monitoring/wan-capacity-recompute')
def recompute_monitoring_wan_capacity(request: Request, user=require_role('Operator')):
    from services.wan_p2_service import build_capacity_recommendations
    result = build_capacity_recommendations()
    _outbound_audit(request, user, 'WAN_CAPACITY_RECOMPUTE', 'Recomputed WAN capacity recommendations', target_type='wan_capacity')
    return result


@router.get('/monitoring/wan-link-groups')
def get_monitoring_wan_link_groups(user=require_role('Viewer')):
    from services.wan_p1_service import list_wan_link_groups
    return {'items': list_wan_link_groups()}


@router.post('/monitoring/wan-link-groups')
def create_monitoring_wan_link_group(payload: WanLinkGroupPayload, request: Request, user=require_role('Operator')):
    from services.wan_p1_service import upsert_wan_link_group
    try:
        data = payload.model_dump(exclude_none=True)
        data['members'] = [item.model_dump() for item in payload.members]
        item = upsert_wan_link_group(data, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'INVALID_WAN_GROUP', 'message': str(exc)}) from exc
    _outbound_audit(request, user, 'WAN_GROUP_CREATE', f'Created WAN link group {item.get("group_name")}', target_type='wan_link_group', target_id=item.get('id'))
    return {'success': True, 'item': item}


@router.patch('/monitoring/wan-link-groups/{group_id}')
def update_monitoring_wan_link_group(group_id: str, payload: WanLinkGroupPayload, request: Request, user=require_role('Operator')):
    from services.wan_p1_service import upsert_wan_link_group
    try:
        data = payload.model_dump(exclude_none=True)
        data['members'] = [item.model_dump() for item in payload.members]
        item = upsert_wan_link_group(data, user, group_id=group_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={'code': 'INVALID_WAN_GROUP', 'message': str(exc)}) from exc
    _outbound_audit(request, user, 'WAN_GROUP_UPDATE', f'Updated WAN link group {group_id}', target_type='wan_link_group', target_id=group_id)
    return {'success': True, 'item': item}
