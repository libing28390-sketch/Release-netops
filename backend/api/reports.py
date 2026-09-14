from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query, Depends, HTTPException
from database import get_db_connection

router = APIRouter()

def _parse_iso_datetime(dt_str: str) -> datetime:
    return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))

@router.get('/reports/dashboard')
def get_reports_dashboard(time_range: str = Query(default='7d', alias='range')):
    # 1. Calculate time windows
    now_utc = datetime.now(timezone.utc)
    days = 30 if time_range == '30d' else 7
    since_dt = now_utc - timedelta(days=days)
    since_iso = since_dt.replace(microsecond=0).isoformat()
    
    since_24h = (now_utc - timedelta(hours=24)).replace(microsecond=0).isoformat()
    since_14d_dt = now_utc - timedelta(days=14)
    since_14d_iso = since_14d_dt.replace(microsecond=0).isoformat()

    conn = get_db_connection()
    try:
        # ── SLA Availability ──
        # Calculate percentage of online status from device_health_samples
        total_samples = conn.execute(
            "SELECT COUNT(*) as total_samples, SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) as online_samples FROM device_health_samples WHERE ts >= ?",
            (since_iso,)
        ).fetchone()
        
        sla_val = 100.0
        if total_samples and total_samples['total_samples'] and total_samples['total_samples'] > 0:
            sla_val = (total_samples['online_samples'] / total_samples['total_samples']) * 100.0
        else:
            # Fallback to current device status
            dev_stats = conn.execute(
                "SELECT COUNT(*) as total_devices, SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) as online_devices FROM devices"
            ).fetchone()
            if dev_stats and dev_stats['total_devices'] and dev_stats['total_devices'] > 0:
                sla_val = (dev_stats['online_devices'] / dev_stats['total_devices']) * 100.0

        # ── MTTR / MTTA ──
        # MTTR: Resolved alerts within the range
        mttr_rows = conn.execute(
            "SELECT created_at, resolved_at FROM alert_events WHERE resolved_at >= ? AND resolved_at IS NOT NULL",
            (since_iso,)
        ).fetchall()
        
        mttr_minutes = []
        for r in mttr_rows:
            try:
                c_dt = _parse_iso_datetime(r['created_at'])
                r_dt = _parse_iso_datetime(r['resolved_at'])
                mttr_minutes.append(max(0.0, (r_dt - c_dt).total_seconds() / 60.0))
            except Exception:
                continue
        avg_mttr = round(sum(mttr_minutes) / len(mttr_minutes), 1) if mttr_minutes else 0.0

        # MTTA: Acknowledged alerts within the range
        ack_rows = conn.execute(
            "SELECT created_at, ack_at FROM alert_events WHERE ack_at >= ? AND ack_at IS NOT NULL",
            (since_iso,)
        ).fetchall()
        
        mtta_minutes = []
        for r in ack_rows:
            try:
                c_dt = _parse_iso_datetime(r['created_at'])
                a_dt = _parse_iso_datetime(r['ack_at'])
                mtta_minutes.append(max(0.0, (a_dt - c_dt).total_seconds() / 60.0))
            except Exception:
                continue
        avg_mtta = round(sum(mtta_minutes) / len(mtta_minutes), 1) if mtta_minutes else 0.0

        # ── 14-day Incident & Resolution Trend ──
        # Get dates for the last 14 days
        trend_days = [(now_utc - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(13, -1, -1)]
        
        # Count incidents by date
        incident_rows = conn.execute(
            """
            SELECT SUBSTR(created_at, 1, 10) as date_str, COUNT(*) as cnt
            FROM alert_events
            WHERE created_at >= ? AND (LOWER(severity) = 'critical' OR LOWER(severity) = 'major')
            GROUP BY date_str
            """,
            (since_14d_iso,)
        ).fetchall()
        incident_map = {r['date_str']: r['cnt'] for r in incident_rows}

        # Collect MTTR values by date
        trend_mttr_rows = conn.execute(
            """
            SELECT SUBSTR(resolved_at, 1, 10) as date_str, created_at, resolved_at
            FROM alert_events
            WHERE resolved_at >= ? AND resolved_at IS NOT NULL
            """,
            (since_14d_iso,)
        ).fetchall()
        
        mttr_map = {}
        for r in trend_mttr_rows:
            try:
                c_dt = _parse_iso_datetime(r['created_at'])
                r_dt = _parse_iso_datetime(r['resolved_at'])
                diff = max(0.0, (r_dt - c_dt).total_seconds() / 60.0)
                mttr_map.setdefault(r['date_str'], []).append(diff)
            except Exception:
                continue

        incident_trend = []
        for d_str in trend_days:
            incidents = incident_map.get(d_str, 0)
            day_mttrs = mttr_map.get(d_str, [])
            day_avg_mttr = round(sum(day_mttrs) / len(day_mttrs), 1) if day_mttrs else 0.0
            incident_trend.append({
                "date": d_str,
                "incidents": incidents,
                "mttr": day_avg_mttr
            })

        # ── Top 5 Alerting Devices ──
        since_7d_iso = (now_utc - timedelta(days=7)).replace(microsecond=0).isoformat()
        top_alert_rows = conn.execute(
            """
            SELECT 
                a.device_id,
                d.hostname,
                d.ip_address,
                d.sys_contact,
                COUNT(*) as alert_count
            FROM alert_events a
            JOIN devices d ON a.device_id = d.id
            WHERE a.created_at >= ?
            GROUP BY a.device_id, d.hostname, d.ip_address, d.sys_contact
            ORDER BY alert_count DESC
            LIMIT 5
            """,
            (since_7d_iso,)
        ).fetchall()

        # Query all alerts count by device and day for sparklines
        spark_rows = conn.execute(
            """
            SELECT 
                device_id,
                SUBSTR(created_at, 1, 10) as date_str,
                COUNT(*) as cnt
            FROM alert_events
            WHERE created_at >= ? AND device_id IS NOT NULL
            GROUP BY device_id, date_str
            """,
            (since_7d_iso,)
        ).fetchall()
        
        spark_map = {}
        for r in spark_rows:
            spark_map.setdefault(r['device_id'], {})[r['date_str']] = r['cnt']

        # Get latest assignee per device for owner fallback
        assignee_rows = conn.execute(
            """
            SELECT DISTINCT ON (device_id) device_id, assignee
            FROM alert_events
            WHERE device_id IS NOT NULL AND assignee IS NOT NULL AND assignee != ''
            ORDER BY device_id, created_at DESC
            """
        ).fetchall()
        assignee_map = {r['device_id']: r['assignee'] for r in assignee_rows}

        spark_days = [(now_utc - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(6, -1, -1)]

        top_alerting = []
        for r in top_alert_rows:
            dev_id = r['device_id']
            dev_spark_map = spark_map.get(dev_id, {})
            spark = [dev_spark_map.get(d, 0) for d in spark_days]
            
            owner = r['sys_contact'] or assignee_map.get(dev_id) or "NetOps Admin"
            
            top_alerting.append({
                "name": r['hostname'],
                "ip": r['ip_address'],
                "alerts": r['alert_count'],
                "owner": owner,
                "spark": spark
            })

        # ── Top 5 Resource Consumers ──
        consumers = []
        
        # 1. CPU / Memory
        dev_resource_rows = conn.execute(
            "SELECT hostname, ip_address, cpu_usage, memory_usage FROM devices WHERE status = 'online'"
        ).fetchall()
        for r in dev_resource_rows:
            if r['cpu_usage'] is not None:
                consumers.append({
                    "name": r['hostname'],
                    "ip": r['ip_address'],
                    "metric": "CPU",
                    "value": float(r['cpu_usage']),
                    "unit": "%"
                })
            if r['memory_usage'] is not None:
                consumers.append({
                    "name": r['hostname'],
                    "ip": r['ip_address'],
                    "metric": "MEM",
                    "value": float(r['memory_usage']),
                    "unit": "%"
                })

        # 2. Bandwidth (BW)
        bw_rows = conn.execute(
            """
            SELECT 
                d.hostname,
                d.ip_address,
                MAX(CASE WHEN COALESCE(t.avg_bw_in_pct, 0) > COALESCE(t.avg_bw_out_pct, 0) 
                         THEN COALESCE(t.avg_bw_in_pct, 0) 
                         ELSE COALESCE(t.avg_bw_out_pct, 0) END) as max_util
            FROM interface_telemetry_1m t
            JOIN devices d ON t.device_id = d.id
            WHERE t.ts_minute >= ?
            GROUP BY d.hostname, d.ip_address
            """,
            (since_24h,)
        ).fetchall()
        for r in bw_rows:
            if r['max_util'] is not None:
                consumers.append({
                    "name": r['hostname'],
                    "ip": r['ip_address'],
                    "metric": "BW",
                    "value": round(float(r['max_util']), 2),
                    "unit": "%"
                })

        # Sort all resource points and slice top 5
        consumers.sort(key=lambda x: x['value'], reverse=True)
        top_consumers = consumers[:5]

        # Return comprehensive dashboard response
        return {
            "sla_availability": round(sla_val, 3),
            "avg_mttr_minutes": avg_mttr,
            "avg_mtta_minutes": avg_mtta,
            "incident_trend": incident_trend,
            "top_alerting": top_alerting,
            "top_consumers": top_consumers
        }
    finally:
        conn.close()
