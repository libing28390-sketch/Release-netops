from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from core.rbac import require_role
from database import get_db_connection
from services import rack_scope_service
from services.device_health_service import annotate_devices_with_health, build_health_overview, fetch_device_health_history, fetch_device_health_trend, load_devices_for_health, record_device_health_snapshot
from services.snmp_metric_profile_service import annotate_devices_with_snmp_profile
from services.site_identity_service import canonical_site_name


router = APIRouter(dependencies=[require_role("Viewer")])


def _health_asset_scope(conn, user):
    if not isinstance(user, dict):
        return None
    # Keep lightweight direct-call test doubles compatible with the endpoint;
    # real database connections always expose ``execute``.
    if not hasattr(conn, 'execute'):
        return None
    return rack_scope_service.allowed_resource_scope(conn, user, 'asset', 'view')


def _enforce_health_rack_scope(conn, user, rack_id: str) -> None:
    if not isinstance(user, dict):
        return
    rack = conn.execute(
        '''SELECT r.*, s.tenant_id AS site_tenant_id
             FROM racks r LEFT JOIN sites s ON s.id = r.site_id
            WHERE r.id = ? OR r.rack_code = ?
            LIMIT 1''',
        (rack_id, rack_id),
    ).fetchone()
    if not rack:
        raise HTTPException(status_code=404, detail='Rack not found')
    rack_scope_service.enforce_loaded_rack(user, dict(rack), 'view')


@router.get('/device-health/overview')
def device_health_overview(
    rack_id: str = Query(default='', max_length=128),
    _user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        normalized_rack_id = rack_id.strip()
        if normalized_rack_id:
            _enforce_health_rack_scope(conn, _user, normalized_rack_id)
        scope = _health_asset_scope(conn, _user)
        load_kwargs = {'rack_id': normalized_rack_id or None}
        if scope:
            load_kwargs.update(
                tenant_id=scope.tenant_id,
                site_ids=scope.site_ids,
            )
        devices = annotate_devices_with_snmp_profile(
            load_devices_for_health(conn, **load_kwargs)
        )
        devices = annotate_devices_with_health(conn, devices)
        overview = build_health_overview(devices)
        if normalized_rack_id:
            overview['items'] = devices
        response = {
            'success': True,
            'data': overview,
            'message': '',
            'meta': {
                'schema_version': 'device-health-v1',
                'generated_at': datetime.now(timezone.utc).isoformat(),
            },
        }
        # Keep the direct Python-call compatibility used by older rack-scoped
        # consumers while the HTTP contract is now carried under ``data``.
        if normalized_rack_id:
            response.update(overview)
        return response
    finally:
        conn.close()


@router.get('/device-health/history')
def device_health_history(
    range_hours: int = Query(default=24, ge=1, le=24 * 30),
    _user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        scope = _health_asset_scope(conn, _user)
        scope_kwargs = {
            'tenant_id': scope.tenant_id if scope else None,
            'site_ids': scope.site_ids if scope else None,
        }
        history = fetch_device_health_history(conn, range_hours, **scope_kwargs)
        if history['sample_count'] == 0:
            conn.close()
            record_device_health_snapshot(**scope_kwargs)
            conn = get_db_connection()
            history = fetch_device_health_history(conn, range_hours, **scope_kwargs)
        return history
    finally:
        conn.close()


@router.get('/device-health/device/{device_id}')
def device_health_detail(device_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT d.*, s.id AS resolved_site_id,
                      s.site_name AS site_name, s.site_code AS site_code,
                      s.tenant_id AS site_tenant_id
               FROM devices d
               LEFT JOIN physical_assets pa ON pa.id = d.asset_id
               LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
               WHERE d.id = ?""",
            (device_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Device not found')

        raw_device = dict(row)
        raw_device['site_id'] = str(raw_device.get('resolved_site_id') or raw_device.get('site_id') or '').strip()
        if isinstance(_user, dict):
            rack_scope_service.enforce_loaded_resource(_user, raw_device, 'asset', 'view')
        raw_device['site'] = canonical_site_name(raw_device)
        raw_device.pop('resolved_site_id', None)
        raw_device = annotate_devices_with_snmp_profile([raw_device])[0]
        device = annotate_devices_with_health(conn, [raw_device])[0]
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
    _user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        scope = _health_asset_scope(conn, _user)
        scope_kwargs = {
            'tenant_id': scope.tenant_id if scope else None,
            'site_ids': scope.site_ids if scope else None,
        }
        trend = fetch_device_health_trend(conn, device_id, range_hours, **scope_kwargs)
        if not trend['device']:
            raise HTTPException(status_code=404, detail='Device not found')
        if trend['sample_count'] == 0:
            conn.close()
            record_device_health_snapshot(**scope_kwargs)
            conn = get_db_connection()
            trend = fetch_device_health_trend(conn, device_id, range_hours, **scope_kwargs)
        return trend
    finally:
        conn.close()
