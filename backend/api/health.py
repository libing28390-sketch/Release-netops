from datetime import datetime, timedelta, timezone
import json
import math
from typing import Any
from fastapi import APIRouter, Query
from core.config import settings
from database import DB_PATH, get_db_connection, init_db
from services import alert_maintenance_service
from services import notification_service
import logging
import os
import shutil
import uuid

try:
    import psutil
except ImportError:  # pragma: no cover - optional runtime dependency fallback
    psutil = None

router = APIRouter()
logger = logging.getLogger(__name__)

HOST_RESOURCE_ALERT_SOURCE = "system_resource"
HOST_RESOURCE_SAMPLE_RETENTION_DAYS = 30
DEFAULT_UI_LANGUAGE = getattr(settings, 'DEFAULT_LANGUAGE', 'zh')
HOST_RESOURCE_ALERT_RULES = {
    "cpu_percent": {
        "warn": 75,
        "critical": 90,
        "title": "Host CPU usage high",
        "title_zh": "宿主机 CPU 使用率过高",
    },
    "memory_percent": {
        "warn": 80,
        "critical": 90,
        "title": "Host memory usage high",
        "title_zh": "宿主机内存使用率过高",
    },
    "disk_percent": {
        "warn": 80,
        "critical": 90,
        "title": "Host disk usage high",
        "title_zh": "宿主机磁盘使用率过高",
    },
}


def _get_host_resource_rule(metric_key: str | None) -> dict[str, Any] | None:
    if not metric_key:
        return None
    return HOST_RESOURCE_ALERT_RULES.get(metric_key)


def _get_host_resource_alert_title(metric_key: str | None, fallback_title: str | None = None) -> str:
    if metric_key == "database_status":
        return "数据库连接异常" if DEFAULT_UI_LANGUAGE == 'zh' else "Database connection unhealthy"
    rule = _get_host_resource_rule(metric_key)
    if rule:
        return rule["title_zh"] if DEFAULT_UI_LANGUAGE == 'zh' else rule["title"]
    return fallback_title or ("宿主机资源告警" if DEFAULT_UI_LANGUAGE == 'zh' else "Host resource alert")


def _normalize_host_resource_alert_row(row: dict[str, Any]) -> dict[str, Any]:
    metric_key = row.get("metric_key")
    normalized = dict(row)
    normalized["title"] = _get_host_resource_alert_title(metric_key, str(row.get("title") or ""))
    return normalized


def _local_alert_time(iso_value: str | None) -> str:
    if not iso_value:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        return datetime.fromisoformat(str(iso_value)).astimezone().strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(iso_value)


def _dispatch_host_resource_notification(
    alert: dict[str, Any],
    *,
    status: str,
    first_occurrence: str,
    last_occurrence: str | None = None,
    duration_seconds: int | None = None,
    impact_window: str | None = None,
    alert_count: int | None = None,
) -> None:
    alert_info = {
        'title': alert.get('title') or _get_host_resource_alert_title(alert.get('metric_key')),
        'object_name': alert.get('metric_key') or alert.get('dedupe_key') or HOST_RESOURCE_ALERT_SOURCE,
        'ip_address': '',
        'status': status,
        'severity': alert.get('severity') or 'major',
        'message': alert.get('message') or '',
        'first_occurrence': _local_alert_time(first_occurrence),
        'last_occurrence': _local_alert_time(last_occurrence or first_occurrence),
        'lang': DEFAULT_UI_LANGUAGE or 'zh',
    }
    if duration_seconds is not None:
        alert_info['duration_seconds'] = duration_seconds
    if impact_window is not None:
        alert_info['impact_window'] = impact_window
    if alert_count is not None:
        alert_info['alert_count'] = alert_count

    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT notification_channels, preferred_language FROM users WHERE notification_channels IS NOT NULL AND notification_channels != '{}'",
        ).fetchall()
    finally:
        conn.close()

    for row in rows or []:
        try:
            channels = json.loads(row['notification_channels'] or '{}')
        except Exception:
            continue
        if not channels:
            continue
        user_alert = {
            **alert_info,
            'lang': row['preferred_language'] if 'preferred_language' in row.keys() and row['preferred_language'] else alert_info['lang'],
        }
        notification_service.send_all_channels(channels, user_alert)


def _get_db_health() -> tuple[bool, str]:
    db_ok = False
    db_status = "missing"
    try:
        if os.path.exists(DB_PATH):
            conn = get_db_connection()
            conn.execute("SELECT 1").fetchone()
            conn.close()
            db_ok = True
            db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)[:100]}"
    return db_ok, db_status


def _resource_status(cpu_percent: float | None, memory_percent: float | None, disk_percent: float | None, db_ok: bool) -> str:
    critical = any(value is not None and value >= 90 for value in (cpu_percent, memory_percent, disk_percent))
    degraded = any(value is not None and value >= 75 for value in (cpu_percent, memory_percent, disk_percent))
    if not db_ok or critical:
        return "critical"
    if degraded:
        return "degraded"
    return "healthy"


def _build_resource_snapshot(db_ok: bool, db_status: str) -> dict[str, Any]:
    disk = shutil.disk_usage(os.path.dirname(DB_PATH) or '.')
    disk_total_gb = round(disk.total / (1024**3), 2)
    disk_used_gb = round(disk.used / (1024**3), 2)
    disk_free_gb = round(disk.free / (1024**3), 2)
    disk_percent = round((disk.used / disk.total) * 100, 1) if disk.total else 0.0

    cpu_percent = None
    memory_percent = None
    memory_used_gb = None
    memory_total_gb = None
    load_1m = None
    process_memory_mb = None
    process_cpu_percent = None
    uptime_hours = None
    metrics_available = psutil is not None

    if psutil is not None:
        cpu_percent = round(float(psutil.cpu_percent(interval=None)), 1)
        vm = psutil.virtual_memory()
        memory_percent = round(float(vm.percent), 1)
        memory_used_gb = round(vm.used / (1024**3), 2)
        memory_total_gb = round(vm.total / (1024**3), 2)
        try:
            load_avg = os.getloadavg()
            load_1m = round(float(load_avg[0]), 2)
        except (AttributeError, OSError):
            load_1m = None
        process = psutil.Process(os.getpid())
        process_memory_mb = round(process.memory_info().rss / (1024**2), 1)
        process_cpu_percent = round(float(process.cpu_percent(interval=None)), 1)
        uptime_hours = round((datetime.now(timezone.utc).timestamp() - float(psutil.boot_time())) / 3600, 1)

    status = _resource_status(cpu_percent, memory_percent, disk_percent, db_ok)
    return {
        "status": status,
        "metrics_available": metrics_available,
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "memory_used_gb": memory_used_gb,
        "memory_total_gb": memory_total_gb,
        "disk_percent": disk_percent,
        "disk_used_gb": disk_used_gb,
        "disk_total_gb": disk_total_gb,
        "disk_free_gb": disk_free_gb,
        "load_1m": load_1m,
        "uptime_hours": uptime_hours,
        "database_status": db_status,
        "database_ok": db_ok,
        "process_memory_mb": process_memory_mb,
        "process_cpu_percent": process_cpu_percent,
        "hostname": os.environ.get("HOSTNAME") or os.environ.get("COMPUTERNAME") or os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME"),
        "platform": os.name,
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _get_host_resource_alerts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for metric_key, rule in HOST_RESOURCE_ALERT_RULES.items():
        raw_value = snapshot.get(metric_key)
        if raw_value is None:
            continue
        metric_value = float(raw_value)
        if metric_value >= rule["critical"]:
            severity = "critical"
        elif metric_value >= rule["warn"]:
            severity = "major"
        else:
            continue

        display_name = metric_key.replace("_percent", "").upper()
        alerts.append({
            "dedupe_key": f"{HOST_RESOURCE_ALERT_SOURCE}:{metric_key}",
            "severity": severity,
            "title": rule["title_zh"] if DEFAULT_UI_LANGUAGE == 'zh' else rule["title"],
            "message": f"{display_name} is {metric_value:.1f}% (warn >= {rule['warn']}%, critical >= {rule['critical']}%)",
            "metric_key": metric_key,
        })

    if not snapshot.get("database_ok", False):
        alerts.append({
            "dedupe_key": f"{HOST_RESOURCE_ALERT_SOURCE}:database",
            "severity": "critical",
            "title": "数据库连接异常" if DEFAULT_UI_LANGUAGE == 'zh' else "Database connection unhealthy",
            "message": str(snapshot.get("database_status") or "Database unavailable"),
            "metric_key": "database_status",
        })
    return alerts


def _sync_host_resource_alerts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    desired_alerts = _get_host_resource_alerts(snapshot)
    desired_map = {item["dedupe_key"]: item for item in desired_alerts}
    conn = get_db_connection()
    try:
        open_rows = conn.execute(
            "SELECT dedupe_key, severity, title, message, interface_name AS metric_key, created_at, workflow_status FROM alert_events WHERE source = ? AND resolved_at IS NULL",
            (HOST_RESOURCE_ALERT_SOURCE,),
        ).fetchall()
        open_map = {row["dedupe_key"]: dict(row) for row in open_rows}
        open_keys = set(open_map)
        now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        for dedupe_key, alert in desired_map.items():
            if dedupe_key in open_keys:
                existing = open_map[dedupe_key]
                if (
                    existing.get("severity") != alert["severity"]
                    or existing.get("title") != alert["title"]
                    or existing.get("message") != alert["message"]
                    or existing.get("metric_key") != alert["metric_key"]
                ):
                    conn.execute(
                        "UPDATE alert_events SET severity = ?, title = ?, message = ?, interface_name = ?, updated_at = ? WHERE dedupe_key = ? AND source = ? AND resolved_at IS NULL",
                        (
                            alert["severity"],
                            alert["title"],
                            alert["message"],
                            alert["metric_key"],
                            now_utc,
                            dedupe_key,
                            HOST_RESOURCE_ALERT_SOURCE,
                        ),
                    )
                continue
            maintenance_window = alert_maintenance_service.find_active_window_for_alert({
                'dedupe_key': dedupe_key,
                'severity': alert['severity'],
                'title': alert['title'],
                'message': alert['message'],
                'ip_address': '',
            }, conn=conn)
            workflow_status = 'suppressed' if maintenance_window else 'open'
            note = f"Suppressed by maintenance window: {maintenance_window['name']}" if maintenance_window else ''
            conn.execute(
                '''
                INSERT INTO alert_events (
                    id, dedupe_key, source, severity, title, message, device_id, interface_name,
                    created_at, resolved_at, workflow_status, note, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, ?, ?, ?)
                ''',
                (
                    str(uuid.uuid4()),
                    dedupe_key,
                    HOST_RESOURCE_ALERT_SOURCE,
                    alert["severity"],
                    alert["title"],
                    alert["message"],
                    alert["metric_key"],
                    now_utc,
                    workflow_status,
                    note,
                    now_utc,
                ),
            )
            if not maintenance_window:
                _dispatch_host_resource_notification(
                    alert,
                    status='active',
                    first_occurrence=now_utc,
                    last_occurrence=now_utc,
                )

        stale_keys = open_keys - set(desired_map)
        if stale_keys:
            resolved_rows = [
                {
                    **open_map[dedupe_key],
                    'dedupe_key': dedupe_key,
                    'metric_key': open_map[dedupe_key].get('metric_key') or dedupe_key.split(':', 1)[-1],
                }
                for dedupe_key in stale_keys
            ]
            conn.executemany(
                "UPDATE alert_events SET resolved_at = ?, workflow_status = 'resolved', updated_at = ? WHERE dedupe_key = ? AND source = ? AND resolved_at IS NULL",
                [(now_utc, now_utc, dedupe_key, HOST_RESOURCE_ALERT_SOURCE) for dedupe_key in stale_keys],
            )
            for row in resolved_rows:
                if str(row.get('workflow_status') or '').lower() == 'suppressed':
                    continue
                first_occurrence = str(row.get('created_at') or now_utc)
                try:
                    start_dt = datetime.fromisoformat(first_occurrence)
                    end_dt = datetime.fromisoformat(now_utc)
                    duration_seconds = max(0, int((end_dt - start_dt).total_seconds()))
                except Exception:
                    duration_seconds = None
                start_label = _local_alert_time(first_occurrence)
                end_label = _local_alert_time(now_utc)
                impact_window = None
                if ' ' in start_label and ' ' in end_label:
                    impact_window = f"{start_label.split(' ')[-1]} → {end_label.split(' ')[-1]}"
                _dispatch_host_resource_notification(
                    row,
                    status='resolved',
                    first_occurrence=first_occurrence,
                    last_occurrence=now_utc,
                    duration_seconds=duration_seconds,
                    impact_window=impact_window,
                    alert_count=1,
                )
        conn.commit()
    finally:
        conn.close()
    return desired_alerts


def record_host_resource_snapshot(sync_alerts: bool = True) -> dict[str, Any]:
    init_db()
    db_ok, db_status = _get_db_health()
    snapshot = _build_resource_snapshot(db_ok, db_status)
    conn = get_db_connection()
    try:
        conn.execute(
            '''
            INSERT OR REPLACE INTO host_resource_samples (
                ts, status, cpu_percent, memory_percent, disk_percent, load_1m,
                process_memory_mb, process_cpu_percent, memory_used_gb, memory_total_gb,
                disk_used_gb, disk_total_gb, disk_free_gb, uptime_hours, database_ok, database_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                snapshot["updated_at"],
                snapshot["status"],
                snapshot["cpu_percent"],
                snapshot["memory_percent"],
                snapshot["disk_percent"],
                snapshot["load_1m"],
                snapshot["process_memory_mb"],
                snapshot["process_cpu_percent"],
                snapshot["memory_used_gb"],
                snapshot["memory_total_gb"],
                snapshot["disk_used_gb"],
                snapshot["disk_total_gb"],
                snapshot["disk_free_gb"],
                snapshot["uptime_hours"],
                1 if snapshot["database_ok"] else 0,
                snapshot["database_status"],
            ),
        )
        cutoff = (datetime.now(timezone.utc) - timedelta(days=HOST_RESOURCE_SAMPLE_RETENTION_DAYS)).replace(microsecond=0).isoformat()
        conn.execute("DELETE FROM host_resource_samples WHERE ts < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()

    active_alerts = _sync_host_resource_alerts(snapshot) if sync_alerts else _get_host_resource_alerts(snapshot)
    snapshot["active_alert_count"] = len(active_alerts)
    snapshot["active_alerts"] = active_alerts
    return snapshot


def _load_recent_host_resource_alerts(range_hours: int) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=range_hours)).replace(microsecond=0).isoformat()
    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''
            SELECT id, severity, title, message, interface_name AS metric_key, created_at, resolved_at
            FROM alert_events
            WHERE source = ? AND (resolved_at IS NULL OR created_at >= ?)
            ORDER BY created_at DESC
            LIMIT 20
            ''',
            (HOST_RESOURCE_ALERT_SOURCE, cutoff),
        ).fetchall()
        return [_normalize_host_resource_alert_row(dict(row)) for row in rows]
    finally:
        conn.close()


def _downsample_host_resource_series(rows: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    if max_points <= 0 or len(rows) <= max_points:
        return rows

    chunk_size = max(1, math.ceil(len(rows) / max_points))
    numeric_keys = [
        "cpu_percent",
        "memory_percent",
        "disk_percent",
        "load_1m",
        "process_memory_mb",
        "process_cpu_percent",
        "memory_used_gb",
        "memory_total_gb",
        "disk_used_gb",
        "disk_total_gb",
        "disk_free_gb",
        "uptime_hours",
    ]
    severity_rank = {"healthy": 0, "degraded": 1, "critical": 2}
    aggregated: list[dict[str, Any]] = []

    for index in range(0, len(rows), chunk_size):
        chunk = rows[index:index + chunk_size]
        latest = chunk[-1]
        point = {
            "ts": latest["ts"],
            "status": max((str(item.get("status") or "healthy") for item in chunk), key=lambda value: severity_rank.get(value, 0)),
            "database_ok": 1 if any(int(item.get("database_ok") or 0) == 1 for item in chunk) else 0,
            "database_status": latest.get("database_status") or "",
        }
        for key in numeric_keys:
            samples = [float(item[key]) for item in chunk if item.get(key) is not None]
            point[key] = round(sum(samples) / len(samples), 2) if samples else None
        aggregated.append(point)
    return aggregated

@router.api_route("/health", methods=["GET", "HEAD"], tags=["health"])
async def health_check():
    logger.debug("Health check endpoint called")
    db_ok, db_status = _get_db_health()

    resources = _build_resource_snapshot(db_ok, db_status)
    disk_free_gb = resources["disk_free_gb"]
    disk_warn = disk_free_gb < 1.0

    overall = "healthy" if (db_ok and not disk_warn) else "degraded"

    # Device summary for public display (login page)
    device_total = 0
    device_online = 0
    try:
        conn = get_db_connection()
        row = conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status='online' THEN 1 ELSE 0 END) as online FROM devices"
        ).fetchone()
        if row:
            device_total = row["total"] or 0
            device_online = row["online"] or 0
        conn.close()
    except Exception:
        pass

    return {
        "status": overall,
        "environment": settings.ENVIRONMENT,
        "project": settings.PROJECT_NAME,
        "database": db_status,
        "disk_free_gb": disk_free_gb,
        "disk_warning": disk_warn,
        "device_total": device_total,
        "device_online": device_online,
        "resources": {
            "status": resources["status"],
            "cpu_percent": resources["cpu_percent"],
            "memory_percent": resources["memory_percent"],
            "disk_percent": resources["disk_percent"],
            "updated_at": resources["updated_at"],
        },
    }


@router.get("/health/resources", tags=["health"])
async def health_resources():
    logger.debug("Health resources endpoint called")
    return record_host_resource_snapshot(sync_alerts=True)


@router.get("/health/resources/history", tags=["health"])
async def health_resource_history(
    range_hours: int = Query(default=24, ge=1, le=24 * 7),
):
    logger.debug("Health resource history endpoint called")
    init_db()
    current = record_host_resource_snapshot(sync_alerts=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=range_hours)).replace(microsecond=0).isoformat()
    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''
            SELECT ts, status, cpu_percent, memory_percent, disk_percent, load_1m,
                   process_memory_mb, process_cpu_percent, memory_used_gb, memory_total_gb,
                   disk_used_gb, disk_total_gb, disk_free_gb, uptime_hours, database_ok, database_status
            FROM host_resource_samples
            WHERE ts >= ?
            ORDER BY ts ASC
            ''',
            (cutoff,),
        ).fetchall()
        raw_series = [dict(row) for row in rows]
    finally:
        conn.close()

    target_points = 60 if range_hours <= 1 else 180 if range_hours <= 24 else 240
    series = _downsample_host_resource_series(raw_series, target_points)

    return {
        "current": current,
        "series": series,
        "alerts": _load_recent_host_resource_alerts(range_hours),
        "range_hours": range_hours,
        "resolution_hint": '1m' if range_hours <= 1 else '5m' if range_hours <= 24 else '30m',
        "sample_count": len(series),
        "thresholds": HOST_RESOURCE_ALERT_RULES,
    }
