from fastapi import APIRouter, HTTPException, Query

from database import get_db_connection
from services.device_health_service import annotate_devices_with_health, build_health_overview, fetch_device_health_history, fetch_device_health_trend, load_devices_for_health, record_device_health_snapshot


router = APIRouter()


@router.get('/device-health/overview')
def device_health_overview():
    conn = get_db_connection()
    try:
        devices = annotate_devices_with_health(conn, load_devices_for_health(conn))
        return build_health_overview(devices)
    finally:
        conn.close()


@router.get('/device-health/history')
def device_health_history(range_hours: int = Query(default=24, ge=1, le=24 * 30)):
    conn = get_db_connection()
    try:
        history = fetch_device_health_history(conn, range_hours)
        if history['sample_count'] == 0:
            conn.close()
            record_device_health_snapshot()
            conn = get_db_connection()
            history = fetch_device_health_history(conn, range_hours)
        return history
    finally:
        conn.close()


@router.get('/device-health/device/{device_id}')
def device_health_detail(device_id: str):
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT * FROM devices WHERE id = ?',
            (device_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Device not found')

        device = annotate_devices_with_health(conn, [dict(row)])[0]
        recent_alerts = conn.execute(
            '''
            SELECT id, severity, title, message, interface_name, created_at
            FROM alert_events
            WHERE device_id = ?
              AND resolved_at IS NULL
              AND COALESCE(workflow_status, 'open') != 'suppressed'
            ORDER BY created_at DESC
            LIMIT 10
            ''',
            (device_id,),
        ).fetchall()

        return {
            'device': device,
            'recent_open_alerts': [dict(item) for item in recent_alerts],
        }
    finally:
        conn.close()


@router.get('/device-health/device/{device_id}/trend')
def device_health_device_trend(
    device_id: str,
    range_hours: int = Query(default=24, ge=1, le=24 * 30),
):
    conn = get_db_connection()
    try:
        trend = fetch_device_health_trend(conn, device_id, range_hours)
        if not trend['device']:
            raise HTTPException(status_code=404, detail='Device not found')
        if trend['sample_count'] == 0:
            conn.close()
            record_device_health_snapshot()
            conn = get_db_connection()
            trend = fetch_device_health_trend(conn, device_id, range_hours)
        return trend
    finally:
        conn.close()