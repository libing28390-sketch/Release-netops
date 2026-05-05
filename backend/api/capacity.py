"""
capacity.py — Capacity Planning API
Provides link utilization trending and capacity forecasting.
"""

import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query
from database import get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter()


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _get_table_columns(conn, table: str) -> set[str]:
    try:
        rows = conn.execute(
            '''
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = ?
            ''',
            (table,),
        ).fetchall()
        if rows:
            return {r['column_name'] for r in rows}
    except Exception:
        pass
    cols = conn.execute(f'PRAGMA table_info({table})').fetchall()
    return {c['name'] for c in cols} if cols else set()


# ──────────────────────────────────────────────
# Capacity Planning endpoints
# ──────────────────────────────────────────────

@router.get('/capacity/overview')
def capacity_overview():
    """Overall capacity dashboard: top utilized interfaces, devices with high CPU/memory."""
    conn = get_db_connection()
    try:
        # Get devices with CPU/memory info
        devices = conn.execute('''
            SELECT id, hostname, ip_address, platform, status,
                   cpu_usage, memory_usage, interface_data,
                   uptime, model
            FROM devices
            WHERE status = 'online'
            ORDER BY cpu_usage DESC
        ''').fetchall()

        high_cpu = [dict(d) for d in devices if (d['cpu_usage'] or 0) >= 80]
        high_mem = [dict(d) for d in devices if (d['memory_usage'] or 0) >= 80]

        # Get top utilized interfaces from recent telemetry (schema-compatible)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        raw_cols = _get_table_columns(conn, 'interface_telemetry_raw')
        in_col = 'bw_in_pct' if 'bw_in_pct' in raw_cols else 'avg_in_util'
        out_col = 'bw_out_pct' if 'bw_out_pct' in raw_cols else 'avg_out_util'
        speed_col = 'speed_mbps' if 'speed_mbps' in raw_cols else 'bandwidth_mbps'
        hot_interfaces = conn.execute('''
            SELECT device_id, interface_name,
                   AVG(COALESCE({in_col}, 0)) as avg_in_util, AVG(COALESCE({out_col}, 0)) as avg_out_util,
                   MAX(COALESCE({in_col}, 0)) as peak_in_util, MAX(COALESCE({out_col}, 0)) as peak_out_util,
                   MAX(COALESCE({speed_col}, 0)) as bandwidth_mbps
            FROM interface_telemetry_raw
            WHERE ts >= ?
            GROUP BY device_id, interface_name
            HAVING AVG(COALESCE({in_col}, 0)) > 50 OR AVG(COALESCE({out_col}, 0)) > 50
            ORDER BY
                CASE
                    WHEN MAX(COALESCE({in_col}, 0)) > MAX(COALESCE({out_col}, 0))
                    THEN MAX(COALESCE({in_col}, 0))
                    ELSE MAX(COALESCE({out_col}, 0))
                END DESC
            LIMIT 20
        '''.format(in_col=in_col, out_col=out_col, speed_col=speed_col), (cutoff,)).fetchall()

        # Enrich with hostname
        dev_map = {d['id']: d['hostname'] for d in devices}
        hot_intf_list = []
        for intf in hot_interfaces:
            item = dict(intf)
            item['hostname'] = dev_map.get(intf['device_id'], '')
            hot_intf_list.append(item)

        # Summary stats
        total_devices = len(devices)
        avg_cpu = round(sum(d['cpu_usage'] or 0 for d in devices) / max(total_devices, 1), 1)
        avg_mem = round(sum(d['memory_usage'] or 0 for d in devices) / max(total_devices, 1), 1)

        return {
            'total_devices': total_devices,
            'avg_cpu': avg_cpu,
            'avg_memory': avg_mem,
            'high_cpu_count': len(high_cpu),
            'high_memory_count': len(high_mem),
            'high_cpu_devices': high_cpu[:10],
            'high_memory_devices': high_mem[:10],
            'hot_interfaces': hot_intf_list,
        }
    finally:
        conn.close()


@router.get('/capacity/device/{device_id}/trend')
def device_capacity_trend(device_id: str, days: int = Query(default=30, ge=1, le=365)):
    """Get daily CPU/memory/interface utilization trend for a device."""
    conn = get_db_connection()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # From device_health_samples
        health_rows = conn.execute('''
            SELECT DATE(ts) as day, AVG(health_score) as avg_health,
                   COUNT(*) as samples
            FROM device_health_samples
            WHERE device_id = ? AND ts >= ?
            GROUP BY DATE(ts)
            ORDER BY day
        ''', (device_id, cutoff)).fetchall()

        # From interface telemetry (1m rollup, schema-compatible)
        rollup_cols = _get_table_columns(conn, 'interface_telemetry_1m')
        avg_in_col = 'avg_bw_in_pct' if 'avg_bw_in_pct' in rollup_cols else 'avg_in_util'
        avg_out_col = 'avg_bw_out_pct' if 'avg_bw_out_pct' in rollup_cols else 'avg_out_util'
        peak_in_col = 'max_bw_in_pct' if 'max_bw_in_pct' in rollup_cols else 'peak_in_util'
        peak_out_col = 'max_bw_out_pct' if 'max_bw_out_pct' in rollup_cols else 'peak_out_util'
        intf_rows = conn.execute('''
            SELECT DATE(ts_minute) as day, interface_name,
                   AVG(COALESCE({avg_in_col}, 0)) as avg_in, AVG(COALESCE({avg_out_col}, 0)) as avg_out,
                   MAX(COALESCE({peak_in_col}, 0)) as peak_in, MAX(COALESCE({peak_out_col}, 0)) as peak_out
            FROM interface_telemetry_1m
            WHERE device_id = ? AND ts_minute >= ?
            GROUP BY DATE(ts_minute), interface_name
            ORDER BY day
        '''.format(
            avg_in_col=avg_in_col,
            avg_out_col=avg_out_col,
            peak_in_col=peak_in_col,
            peak_out_col=peak_out_col,
        ), (device_id, cutoff)).fetchall()

        # Aggregate interface data per day (pick the busiest interface)
        day_intf = {}
        for row in intf_rows:
            d = row['day']
            if d not in day_intf or max(row['avg_in'] or 0, row['avg_out'] or 0) > max(day_intf[d].get('avg_in', 0), day_intf[d].get('avg_out', 0)):
                day_intf[d] = {
                    'interface_name': row['interface_name'],
                    'avg_in': round(row['avg_in'] or 0, 1),
                    'avg_out': round(row['avg_out'] or 0, 1),
                    'peak_in': round(row['peak_in'] or 0, 1),
                    'peak_out': round(row['peak_out'] or 0, 1),
                }

        # Get current device info
        dev = conn.execute('SELECT hostname, cpu_usage, memory_usage FROM devices WHERE id = ?', (device_id,)).fetchone()
        hostname = dev['hostname'] if dev else ''

        trends = []
        for row in health_rows:
            day = row['day']
            intf = day_intf.get(day, {})
            trends.append({
                'date': day,
                'health_score': round(row['avg_health'] or 0, 1),
                'avg_in_util': intf.get('avg_in', 0),
                'avg_out_util': intf.get('avg_out', 0),
                'peak_in_util': intf.get('peak_in', 0),
                'peak_out_util': intf.get('peak_out', 0),
                'busiest_interface': intf.get('interface_name', ''),
            })

        # Simple linear forecast (next 30 days) for the busiest metric
        forecast = []
        if len(trends) >= 7:
            # Use peak utilization for forecasting
            peak_values = [max(t['peak_in_util'], t['peak_out_util']) for t in trends]
            n = len(peak_values)
            x_mean = (n - 1) / 2
            y_mean = sum(peak_values) / n
            numerator = sum((i - x_mean) * (peak_values[i] - y_mean) for i in range(n))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            slope = numerator / denominator if denominator != 0 else 0
            intercept = y_mean - slope * x_mean

            for i in range(1, 31):
                predicted = slope * (n + i - 1) + intercept
                predicted = max(0, min(100, round(predicted, 1)))
                future_date = (datetime.now(timezone.utc) + timedelta(days=i)).strftime('%Y-%m-%d')
                forecast.append({'date': future_date, 'predicted_util': predicted})

            # Days until 80% and 95%
            days_to_80 = None
            days_to_95 = None
            current_val = peak_values[-1] if peak_values else 0
            if slope > 0:
                if current_val < 80:
                    days_to_80 = max(1, round((80 - intercept) / slope - n + 1))
                if current_val < 95:
                    days_to_95 = max(1, round((95 - intercept) / slope - n + 1))
        else:
            days_to_80 = None
            days_to_95 = None

        return {
            'device_id': device_id,
            'hostname': hostname,
            'trends': trends,
            'forecast': forecast,
            'days_to_80_pct': days_to_80,
            'days_to_95_pct': days_to_95,
        }
    finally:
        conn.close()


@router.get('/capacity/forecast')
def capacity_forecast_all():
    """Get capacity forecast summary for all devices — which ones will hit thresholds soonest."""
    conn = get_db_connection()
    try:
        devices = conn.execute('''
            SELECT id, hostname, ip_address, platform, cpu_usage, memory_usage
            FROM devices WHERE status = 'online'
        ''').fetchall()

        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        rollup_cols = _get_table_columns(conn, 'interface_telemetry_1m')
        avg_in_col = 'avg_bw_in_pct' if 'avg_bw_in_pct' in rollup_cols else 'avg_in_util'
        peak_in_col = 'max_bw_in_pct' if 'max_bw_in_pct' in rollup_cols else 'peak_in_util'

        warnings = []
        for dev in devices:
            # Get recent peak interface utilization
            intf_data = conn.execute('''
                SELECT AVG(COALESCE({avg_in_col}, 0)) as avg_util,
                       MAX(COALESCE({peak_in_col}, 0)) as peak_util
                FROM interface_telemetry_1m
                WHERE device_id = ? AND ts_minute >= ?
            '''.format(avg_in_col=avg_in_col, peak_in_col=peak_in_col), (dev['id'], cutoff)).fetchone()

            cpu = dev['cpu_usage'] or 0
            mem = dev['memory_usage'] or 0
            peak_util = round(intf_data['peak_util'] or 0, 1) if intf_data else 0
            avg_util = round(intf_data['avg_util'] or 0, 1) if intf_data else 0

            risk_level = 'normal'
            reasons = []
            if cpu >= 90:
                risk_level = 'critical'
                reasons.append(f'CPU {cpu}%')
            elif cpu >= 80:
                risk_level = 'warning' if risk_level == 'normal' else risk_level
                reasons.append(f'CPU {cpu}%')
            if mem >= 90:
                risk_level = 'critical'
                reasons.append(f'Memory {mem}%')
            elif mem >= 80:
                risk_level = 'warning' if risk_level == 'normal' else risk_level
                reasons.append(f'Memory {mem}%')
            if peak_util >= 90:
                risk_level = 'critical'
                reasons.append(f'Link peak {peak_util}%')
            elif peak_util >= 75:
                risk_level = 'warning' if risk_level == 'normal' else risk_level
                reasons.append(f'Link peak {peak_util}%')

            if risk_level != 'normal':
                warnings.append({
                    'device_id': dev['id'],
                    'hostname': dev['hostname'],
                    'ip_address': dev['ip_address'],
                    'platform': dev['platform'],
                    'cpu': cpu,
                    'memory': mem,
                    'peak_link_util': peak_util,
                    'avg_link_util': avg_util,
                    'risk_level': risk_level,
                    'reasons': reasons,
                })

        warnings.sort(key=lambda w: (0 if w['risk_level'] == 'critical' else 1, -max(w['cpu'], w['memory'], w['peak_link_util'])))
        return {
            'total_warnings': len(warnings),
            'critical_count': sum(1 for w in warnings if w['risk_level'] == 'critical'),
            'warning_count': sum(1 for w in warnings if w['risk_level'] == 'warning'),
            'items': warnings,
        }
    finally:
        conn.close()
