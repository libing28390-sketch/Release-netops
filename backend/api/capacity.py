"""
capacity.py — Capacity Planning API
Provides link utilization trending and capacity forecasting.
"""

import logging
import math
import datetime as dt
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query
from database import _USE_PG, get_db_connection, fetch_interface_data
from services.forecast_engine import ForecastEngine, calculate_capacity_score

logger = logging.getLogger(__name__)

router = APIRouter()


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _calculate_percentile(lst: list[float], pct: float) -> float:
    if not lst:
        return 0.0
    sorted_lst = sorted(lst)
    k = (len(sorted_lst) - 1) * pct
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_lst[int(k)]
    d0 = sorted_lst[int(f)] * (c - k)
    d1 = sorted_lst[int(c)] * (k - f)
    return d0 + d1



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
        if _USE_PG:
            logger.warning("Failed to inspect PostgreSQL columns for table %s", table, exc_info=True)
            return set()
    if _USE_PG:
        # PRAGMA is SQLite-only. A missing PostgreSQL table should be treated
        # as an empty capability set instead of falling through to SQLite SQL.
        return set()
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
        devices_rows = conn.execute('''
            SELECT id, hostname, ip_address, platform, status,
                   cpu_usage, memory_usage, uptime, model
            FROM devices
            WHERE status = 'online'
            ORDER BY cpu_usage DESC
        ''').fetchall()
        devices = []
        for r in devices_rows:
            d = dict(r)
            d['interface_data'] = fetch_interface_data(conn, d['id'])
            devices.append(d)

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
            'all_devices': [dict(d) for d in devices],
        }
    finally:
        conn.close()


@router.get('/capacity/device/{device_id}/trend')
def device_capacity_trend(
    device_id: str,
    days: int = Query(default=30, ge=1, le=365),
    top_n: int = Query(default=5, ge=1, le=20)
):
    """Get daily P95 telemetry trend and forecasting for Top N busy interfaces plus chassis-level metrics."""
    conn = get_db_connection()
    try:
        # 1. Retrieve current device status info
        dev_row = conn.execute(
            '''SELECT hostname, cpu_usage, memory_usage,
                      COALESCE(ports_count, 0) as ports_count, 
                      COALESCE(ports_bandwidth_gbps, 0.0) as ports_bandwidth_gbps, 
                      COALESCE(switching_capacity_gbps, 0.0) as switching_capacity_gbps 
               FROM devices WHERE id = ?''',
            (device_id,)
        ).fetchone()
        if not dev_row:
            return {'error': 'Device not found'}
        dev = dict(dev_row)
        dev['interface_data'] = fetch_interface_data(conn, device_id)
        hostname = dev['hostname'] or ''
        cpu_curr = float(dev['cpu_usage'] or 0)
        mem_curr = float(dev['memory_usage'] or 0)
        
        # Dynamically calculate specs based on real interface list if available
        ports_count = int(dev['ports_count'] or 0)
        ports_bandwidth_gbps = float(dev['ports_bandwidth_gbps'] or 0.0)
        switching_capacity_gbps = float(dev['switching_capacity_gbps'] or 0.0)
        
        if dev['interface_data']:
            try:
                intf_list = dev['interface_data']
                # Filter out loopbacks, VLANs, tunnels, etc.
                phys_intfs = []
                for i in intf_list:
                    name = i.get('name', '').lower()
                    if not (name.startswith('lo') or name.startswith('loopback') or
                            name.startswith('vl') or name.startswith('vlan') or
                            name.startswith('tu') or name.startswith('tunnel')):
                        phys_intfs.append(i)
                
                if phys_intfs:
                    ports_count = len(phys_intfs)
                    total_speed_mbps = sum(float(i.get('speed_mbps') or 0.0) for i in phys_intfs)
                    ports_bandwidth_gbps = total_speed_mbps / 1000.0
                    # Switching capacity: for virtual switches, assume non-blocking full-duplex (2x ports speed)
                    switching_capacity_gbps = ports_bandwidth_gbps * 2.0
            except Exception as e:
                logger.warning(f"Failed to parse interface_data for dynamic specs: {e}")

        # Compute oversubscription / convergence specs
        c_ports = ports_bandwidth_gbps
        c_switching = switching_capacity_gbps
        if c_ports > 0 and c_switching > 0:
            max_forwarding_capacity_gbps = min(c_ports, c_switching / 2.0)
            oversubscription_ratio = (2.0 * c_ports) / c_switching
            is_blocking = oversubscription_ratio > 1.0
            bottleneck_type = "Backplane Capacity" if (c_switching / 2.0) < c_ports else "Ports Speed"
        else:
            max_forwarding_capacity_gbps = c_ports if c_ports > 0 else 0.0
            oversubscription_ratio = 1.0
            is_blocking = False
            bottleneck_type = "Ports Speed"

        # 2. Query 36 days of rollup minute telemetry data
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days + 6)).isoformat()
        rollup_cols = _get_table_columns(conn, 'interface_telemetry_1m')
        
        in_col = 'max_bw_in_pct' if 'max_bw_in_pct' in rollup_cols else ('avg_bw_in_pct' if 'avg_bw_in_pct' in rollup_cols else 'avg_in_util')
        out_col = 'max_bw_out_pct' if 'max_bw_out_pct' in rollup_cols else ('avg_bw_out_pct' if 'avg_bw_out_pct' in rollup_cols else 'avg_out_util')

        query = f'''
            SELECT ts_minute, substr(ts_minute, 1, 10) as day, interface_name,
                   COALESCE({in_col}, 0) as bw_in, COALESCE({out_col}, 0) as bw_out,
                   COALESCE(avg_in_bps, 0) as avg_in, COALESCE(avg_out_bps, 0) as avg_out,
                   COALESCE(err_delta_sum, 0) as errs, COALESCE(discard_delta_sum, 0) as discards,
                   COALESCE(in_pkts_sum, 0) + COALESCE(out_pkts_sum, 0) as pkts
            FROM interface_telemetry_1m
            WHERE device_id = ? AND ts_minute >= ?
        '''
        rows = conn.execute(query, (device_id, cutoff)).fetchall()

        # 3. Group by interface and day / minute
        intf_day_data = defaultdict(lambda: defaultdict(lambda: ([], [])))
        intf_stats = defaultdict(lambda: {"errs": 0, "discards": 0, "pkts": 0})
        minute_totals = defaultdict(float)  # ts_minute -> total dynamic load in bps
        
        for r in rows:
            intf = r["interface_name"]
            day = r["day"]
            ts_min = r["ts_minute"]
            intf_day_data[intf][day][0].append(float(r["bw_in"]))
            intf_day_data[intf][day][1].append(float(r["bw_out"]))
            
            stats = intf_stats[intf]
            stats["errs"] += int(r["errs"] or 0)
            stats["discards"] += int(r["discards"] or 0)
            stats["pkts"] += int(r["pkts"] or 0)
            
            # Aggregate chassis traffic: sum(max(in_bps, out_bps)) per minute
            in_bps = float(r["avg_in"] or 0.0)
            out_bps = float(r["avg_out"] or 0.0)
            minute_totals[ts_min] += max(in_bps, out_bps)

        # Build consecutive 36-day date index
        today_date = dt.datetime.now(dt.timezone.utc).date()
        date_list = [(today_date - dt.timedelta(days=i)).isoformat() for i in range(days + 6 - 1, -1, -1)]

        # Compute P95 values per interface per day
        intf_p95_series = {}
        for intf, days_map in intf_day_data.items():
            series = []
            for d in date_list:
                if d in days_map:
                    in_list, out_list = days_map[d]
                    p95_in = _calculate_percentile(in_list, 0.95)
                    p95_out = _calculate_percentile(out_list, 0.95)
                    series.append(max(p95_in, p95_out))
                else:
                    # Pad missing values
                    series.append(series[-1] if series else 0.0)
            intf_p95_series[intf] = series

        # Compute Chassis Utilization Series
        chassis_p95_series = []
        if max_forwarding_capacity_gbps > 0:
            cap_g = max_forwarding_capacity_gbps
            day_chassis_utils = defaultdict(list)
            for ts_min, total_load_bps in minute_totals.items():
                load_gbps = total_load_bps * 1e-9
                util_pct = (load_gbps / cap_g) * 100.0
                day = ts_min[:10]
                day_chassis_utils[day].append(min(100.0, max(0.0, util_pct)))
            
            for d in date_list:
                if d in day_chassis_utils:
                    p95_val = _calculate_percentile(day_chassis_utils[d], 0.95)
                    chassis_p95_series.append(p95_val)
                else:
                    chassis_p95_series.append(chassis_p95_series[-1] if chassis_p95_series else 0.0)
        else:
            chassis_p95_series = [0.0] * len(date_list)

        # Sort interfaces by mean P95 utilization to find Top N busiest
        intf_rank = []
        for intf, series in intf_p95_series.items():
            avg_p95 = sum(series) / len(series) if series else 0.0
            intf_rank.append((avg_p95, intf))
        intf_rank.sort(reverse=True)
        top_interfaces = [item[1] for item in intf_rank[:top_n]]

        # Use ForecastEngine for each top interface
        engine = ForecastEngine()
        interfaces_results = []

        # A. Append Chassis-Level virtual interface
        chassis_errs = sum(s["errs"] for s in intf_stats.values())
        chassis_discards = sum(s["discards"] for s in intf_stats.values())
        chassis_pkts = sum(s["pkts"] for s in intf_stats.values())
        chassis_loss_rate = chassis_discards / chassis_pkts if chassis_pkts > 0 else 0.0
        
        chassis_pred = engine.predict_interface_capacity(chassis_p95_series, forecast_days=30)
        current_chassis_p95 = chassis_p95_series[-1] if chassis_p95_series else 0.0
        
        chassis_score, chassis_risk = calculate_capacity_score(
            cpu_util=cpu_curr,
            mem_util=mem_curr,
            intf_p95=current_chassis_p95,
            err_count=chassis_errs,
            discard_count=chassis_discards,
            packet_loss_rate=chassis_loss_rate
        )
        
        forecast_dates = []
        for i in range(1, 31):
            f_date = (datetime.now(timezone.utc) + timedelta(days=i)).strftime('%Y-%m-%d')
            forecast_dates.append(f_date)
            
        chassis_forecast_30d = []
        for d_str, val in zip(forecast_dates, chassis_pred["predictions"]):
            chassis_forecast_30d.append({"date": d_str, "predicted_util": val})
            
        chassis_trends = []
        chassis_hist_raw = chassis_pred["history_raw"]
        chassis_hist_smooth = chassis_pred["history_smoothed"]
        trends_dates = date_list[-30:]
        for idx, d_str in enumerate(trends_dates):
            raw_val = chassis_hist_raw[idx] if idx < len(chassis_hist_raw) else 0.0
            smooth_val = chassis_hist_smooth[idx] if idx < len(chassis_hist_smooth) else 0.0
            chassis_trends.append({
                "date": d_str,
                "avg_in_util": raw_val,
                "avg_out_util": smooth_val,
                "peak_in_util": raw_val,
                "peak_out_util": smooth_val
            })
            
        interfaces_results.append({
            "interface_name": "Chassis-Level Capacity (整机接口容量)",
            "current_p95_util": round(current_chassis_p95, 2),
            "trends": chassis_trends,
            "forecast_30d": chassis_forecast_30d,
            "slope": chassis_pred["slope"],
            "r2": chassis_pred["r2"],
            "trend_confidence": chassis_pred["trend_confidence"],
            "days_to_80": chassis_pred["days_to_80"],
            "days_to_95": chassis_pred["days_to_95"],
            "risk_level": chassis_risk,
            "capacity_score": chassis_score,
            "packet_loss_rate": round(chassis_loss_rate * 100, 4),
            "error_count": chassis_errs,
            "discard_count": chassis_discards
        })

        # B. Append standard Top N busy interfaces
        for intf in top_interfaces:
            series = intf_p95_series[intf]
            pred_res = engine.predict_interface_capacity(series, forecast_days=30)
            
            stats = intf_stats[intf]
            err_count = stats["errs"]
            discard_count = stats["discards"]
            pkts = stats["pkts"]
            loss_rate = discard_count / pkts if pkts > 0 else 0.0
            
            current_p95 = series[-1] if series else 0.0
            
            score, risk = calculate_capacity_score(
                cpu_util=cpu_curr,
                mem_util=mem_curr,
                intf_p95=current_p95,
                err_count=err_count,
                discard_count=discard_count,
                packet_loss_rate=loss_rate
            )
            
            forecast_30d = []
            for d_str, val in zip(forecast_dates, pred_res["predictions"]):
                forecast_30d.append({"date": d_str, "predicted_util": val})
                
            trends = []
            hist_raw = pred_res["history_raw"]
            hist_smooth = pred_res["history_smoothed"]
            for idx, d_str in enumerate(trends_dates):
                raw_val = hist_raw[idx] if idx < len(hist_raw) else 0.0
                smooth_val = hist_smooth[idx] if idx < len(hist_smooth) else 0.0
                trends.append({
                    "date": d_str,
                    "avg_in_util": raw_val,       # Raw actual value
                    "avg_out_util": smooth_val,   # Smoothed trend value
                    "peak_in_util": raw_val,
                    "peak_out_util": smooth_val
                })

            interfaces_results.append({
                "interface_name": intf,
                "current_p95_util": round(current_p95, 2),
                "trends": trends,
                "forecast_30d": forecast_30d,
                "slope": pred_res["slope"],
                "r2": pred_res["r2"],
                "trend_confidence": pred_res["trend_confidence"],
                "days_to_80": pred_res["days_to_80"],
                "days_to_95": pred_res["days_to_95"],
                "risk_level": risk,
                "capacity_score": score,
                "packet_loss_rate": round(loss_rate * 100, 4),
                "error_count": err_count,
                'discard_count': discard_count
            })

        return {
            'device_id': device_id,
            'hostname': hostname,
            'cpu_usage': cpu_curr,
            'memory_usage': mem_curr,
            'chassis_spec': {
                "ports_count": ports_count,
                "ports_bandwidth_gbps": round(ports_bandwidth_gbps, 3),
                "switching_capacity_gbps": round(switching_capacity_gbps, 3),
                "oversubscription_ratio": round(oversubscription_ratio, 2),
                "max_forwarding_capacity_gbps": round(max_forwarding_capacity_gbps, 3),
                "is_blocking": is_blocking,
                "bottleneck_type": bottleneck_type
            },
            'interfaces': interfaces_results
        }
    finally:
        conn.close()


@router.get('/capacity/forecast')
def capacity_forecast_all():
    """Get capacity forecast summary for all devices based on P95, CPU, MEM, errors, and discards."""
    conn = get_db_connection()
    try:
        # 1. Get all online devices
        devices = conn.execute('''
            SELECT id, hostname, ip_address, platform, cpu_usage, memory_usage
            FROM devices WHERE status = 'online'
        ''').fetchall()
        if not devices:
            return {
                'total_warnings': 0,
                'critical_count': 0,
                'warning_count': 0,
                'items': []
            }

        # 2. Get current P95 from telemetry (last 24 hours)
        cutoff_1d = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        rollup_cols = _get_table_columns(conn, 'interface_telemetry_1m')
        
        in_col = 'max_bw_in_pct' if 'max_bw_in_pct' in rollup_cols else ('avg_bw_in_pct' if 'avg_bw_in_pct' in rollup_cols else 'avg_in_util')
        out_col = 'max_bw_out_pct' if 'max_bw_out_pct' in rollup_cols else ('avg_bw_out_pct' if 'avg_bw_out_pct' in rollup_cols else 'avg_out_util')

        query_p95 = f'''
            SELECT device_id, interface_name,
                   COALESCE({in_col}, 0) as bw_in, COALESCE({out_col}, 0) as bw_out
            FROM interface_telemetry_1m
            WHERE ts_minute >= ?
        '''
        rows_p95 = conn.execute(query_p95, (cutoff_1d,)).fetchall()

        # Group raw values in Python
        dev_intf_data = defaultdict(lambda: defaultdict(lambda: ([], [])))
        for r in rows_p95:
            d_id = r["device_id"]
            intf = r["interface_name"]
            dev_intf_data[d_id][intf][0].append(float(r["bw_in"]))
            dev_intf_data[d_id][intf][1].append(float(r["bw_out"]))

        # 3. Get error & discard statistics from telemetry (last 7 days)
        cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        query_stats = '''
            SELECT device_id, interface_name,
                   SUM(COALESCE(err_delta_sum, 0)) as errs,
                   SUM(COALESCE(discard_delta_sum, 0)) as discards,
                   SUM(COALESCE(in_pkts_sum, 0) + COALESCE(out_pkts_sum, 0)) as pkts
            FROM interface_telemetry_1m
            WHERE ts_minute >= ?
            GROUP BY device_id, interface_name
        '''
        rows_stats = conn.execute(query_stats, (cutoff_7d,)).fetchall()
        
        dev_intf_stats = defaultdict(dict)
        for r in rows_stats:
            d_id = r["device_id"]
            intf = r["interface_name"]
            dev_intf_stats[d_id][intf] = {
                "errs": int(r["errs"] or 0),
                "discards": int(r["discards"] or 0),
                "pkts": int(r["pkts"] or 0)
            }

        # 4. Evaluate risk for each device
        warnings = []
        for dev in devices:
            d_id = dev['id']
            cpu = float(dev['cpu_usage'] or 0)
            mem = float(dev['memory_usage'] or 0)

            # Get interfaces for this device
            interfaces = dev_intf_data.get(d_id, {})
            
            device_min_score = 100
            device_worst_risk = "healthy"
            worst_intf_name = "N/A"
            worst_intf_p95 = 0.0
            worst_intf_avg = 0.0
            device_reasons = []

            if cpu >= 80.0:
                device_reasons.append(f"CPU usage is {cpu}%")
            if mem >= 80.0:
                device_reasons.append(f"Memory usage is {mem}%")

            # Evaluate each interface
            for intf, (in_list, out_list) in interfaces.items():
                p95_in = _calculate_percentile(in_list, 0.95)
                p95_out = _calculate_percentile(out_list, 0.95)
                current_p95 = max(p95_in, p95_out)
                
                stats = dev_intf_stats.get(d_id, {}).get(intf, {"errs": 0, "discards": 0, "pkts": 0})
                err_count = stats["errs"]
                discard_count = stats["discards"]
                pkts = stats["pkts"]
                loss_rate = discard_count / pkts if pkts > 0 else 0.0
                
                score, risk = calculate_capacity_score(
                    cpu_util=cpu,
                    mem_util=mem,
                    intf_p95=current_p95,
                    err_count=err_count,
                    discard_count=discard_count,
                    packet_loss_rate=loss_rate
                )

                if score < device_min_score:
                    device_min_score = score
                    device_worst_risk = risk
                    worst_intf_name = intf
                    worst_intf_p95 = current_p95
                    
                    worst_intf_avg = sum(in_list + out_list) / len(in_list + out_list) if (in_list or out_list) else 0.0

            if worst_intf_p95 >= 75.0:
                device_reasons.append(f"Interface {worst_intf_name} P95 is {round(worst_intf_p95, 1)}%")

            # Only report warnings/risky devices (score < 90)
            if device_min_score < 90:
                warnings.append({
                    'device_id': d_id,
                    'hostname': dev['hostname'],
                    'ip_address': dev['ip_address'],
                    'platform': dev['platform'],
                    'cpu': cpu,
                    'memory': mem,
                    'peak_link_util': round(worst_intf_p95, 1),
                    'avg_link_util': round(worst_intf_avg, 1),
                    'risk_level': device_worst_risk,
                    'capacity_score': device_min_score,
                    'reasons': device_reasons if device_reasons else [f"Capacity score is {device_min_score}"],
                    'worst_interface': worst_intf_name
                })

        # Sort: critical first, then high, then warning; within same risk level, sort by lowest capacity_score
        warnings.sort(key=lambda w: (
            {"critical": 0, "high": 1, "warning": 2}.get(w['risk_level'], 3),
            w['capacity_score']
        ))

        return {
            'total_warnings': len(warnings),
            'critical_count': sum(1 for w in warnings if w['risk_level'] == 'critical'),
            'warning_count': sum(1 for w in warnings if w['risk_level'] == 'warning' or w['risk_level'] == 'high'),
            'items': warnings,
        }
    finally:
        conn.close()
