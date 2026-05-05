"""
assets.py - Physical Asset Management (PAM) API
Provides CRUD for servers and network devices with physical/location metadata.
When asset_type='network_device', a linked record in the `devices` table is
auto-created / synced / cascade-deleted so that the asset registry serves as
the single source of truth (Plan-A).
"""

import uuid
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator
from database import get_db_connection
from core.crypto import encrypt_credential, decrypt_credential
from drivers.ssh_compat import get_ssh_error_code, build_ssh_error_guidance

import ping3
import socket
from scrapli import Scrapli

logger = logging.getLogger(__name__)

router = APIRouter()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')


# ── helpers: devices ↔ physical_assets sync ──────────────────────────

def _platform_from_vendor(vendor: str, asset_type: str = 'network_device') -> str:
    """Map asset vendor string to a best-guess Scrapli/Netmiko platform."""
    v = (vendor or '').lower()
    if 'cisco' in v:
        return 'cisco_iosxe'
    if 'huawei' in v:
        return 'huawei_vrp'
    if 'h3c' in v or 'comware' in v:
        return 'hp_comware'
    if 'arista' in v:
        return 'arista_eos'
    if 'juniper' in v:
        return 'juniper_junos'
    if any(x in v for x in ['ubuntu', 'debian', 'centos', 'redhat', 'linux']):
        return 'linux'
    
    if asset_type == 'server':
        return 'linux'
    return 'cisco_iosxe'


def _safe_encrypt(plaintext: str) -> str:
    """Encrypt credential, return empty string if encryption key is not configured."""
    if not plaintext:
        return plaintext
    try:
        return encrypt_credential(plaintext)
    except RuntimeError:
        logger.warning('CREDENTIAL_ENCRYPTION_KEY not configured, storing empty password')
        return ''


def _create_linked_device(conn, asset_id: str, body) -> str:
    """Create a devices row linked to a physical_assets row."""
    device_id = str(uuid.uuid4())
    platform = getattr(body, 'platform', '') or _platform_from_vendor(body.vendor, body.asset_type)
    method = getattr(body, 'connection_method', '') or 'ssh'
    uname = getattr(body, 'username', '') or ''
    pwd = getattr(body, 'password', '') or ''
    community = getattr(body, 'snmp_community', '') or 'public'
    port = getattr(body, 'snmp_port', None) or 161
    conn.execute('''
        INSERT INTO devices (
            id, asset_id, hostname, ip_address, platform, status, compliance,
            username, password, sn, model, version, role, site, uptime,
            connection_method, vendor, snmp_community, snmp_port
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        device_id, asset_id,
        body.hostname, body.management_ip,
        platform, 'pending', 'unknown',
        uname, _safe_encrypt(pwd),
        body.serial_number, body.model, '', body.device_role,
        body.datacenter, '0d 0h', method, body.vendor,
        community, port,
    ))
    return device_id


def _sync_device_from_asset(conn, asset_id: str, body) -> None:
    """Push basic-info changes from asset to its linked device row."""
    row = conn.execute('SELECT id FROM devices WHERE asset_id = ?', (asset_id,)).fetchone()
    if not row:
        return
    updates = {
        'hostname': body.hostname,
        'ip_address': body.management_ip,
        'sn': body.serial_number,
        'model': body.model,
        'role': body.device_role,
        'site': body.datacenter,
        'vendor': body.vendor,
        'platform': body.platform if hasattr(body, 'platform') else None,
        'connection_method': body.connection_method if hasattr(body, 'connection_method') else None,
        'snmp_community': body.snmp_community if hasattr(body, 'snmp_community') else None,
        'snmp_port': body.snmp_port if hasattr(body, 'snmp_port') else None,
    }
    # Handle username/password specially
    uname = getattr(body, 'username', None)
    pwd = getattr(body, 'password', None)
    if uname is not None:
        updates['username'] = uname
    if pwd is not None and pwd != '':
        updates['password'] = _safe_encrypt(pwd)
    # Only update non-None values (AssetUpdate has Optional fields)
    set_parts = []
    params = []
    for col, val in updates.items():
        if val is not None:
            set_parts.append(f'{col} = ?')
            params.append(val)
    if set_parts:
        params.append(row['id'])
        conn.execute(f"UPDATE devices SET {', '.join(set_parts)} WHERE id = ?", params)


def _delete_linked_device(conn, asset_id: str) -> None:
    """Cascade-delete the devices row linked to the asset, cleaning up all FK references first."""
    row = conn.execute('SELECT id FROM devices WHERE asset_id = ?', (asset_id,)).fetchone()
    if not row:
        return
    device_id = row['id'] if isinstance(row, dict) else row[0]

    # Delete from all tables that reference devices(id)
    conn.execute('DELETE FROM jobs WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM config_snapshots WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM links WHERE source_device_id = ? OR target_device_id = ?', (device_id, device_id))
    conn.execute('DELETE FROM topology_discovery_run_devices WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM topology_observations WHERE source_device_id = ? OR target_device_id = ?', (device_id, device_id))
    conn.execute('DELETE FROM compliance_findings WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM device_health_samples WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM config_drift_results WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM capacity_snapshots WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM inspection_results WHERE device_id = ?', (device_id,))

    conn.execute('DELETE FROM devices WHERE id = ?', (device_id,))


# ── Pydantic Models ──────────────────────────────────────────────────

class AssetCreate(BaseModel):
    asset_type: str  # 'server' | 'network_device'
    asset_tag: str = ''
    serial_number: str = ''
    vendor: str = ''
    model: str = ''
    hostname: str = ''
    datacenter: str = ''
    rack: str = ''
    rack_unit: str = ''
    u_height: int = 1
    planned_start_u: Optional[int] = None
    management_ip: str = ''
    business_ip: str = ''
    device_role: str = ''  # switch/router/firewall/ap - only for network_device
    vlan: str = ''
    uplink_switch: str = ''
    uplink_port: str = ''
    status: str = 'active'
    lifecycle_status: str = 'staging'
    purchase_date: str = ''
    warranty_expiry: str = ''
    department: str = ''
    notes: str = ''
    # Network-device-only fields (forwarded to devices table)
    platform: str = ''
    connection_method: str = 'ssh'
    username: str = ''
    password: str = ''
    snmp_community: str = 'public'
    snmp_port: int = 161

    @field_validator('u_height')
    @classmethod
    def validate_u_height(cls, v: int) -> int:
        return max(1, min(60, int(v) if v is not None else 1))

    @field_validator('planned_start_u')
    @classmethod
    def validate_planned_start_u(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        vi = int(v)
        if vi < 1 or vi > 60:
            return None
        return vi


class AssetUpdate(BaseModel):
    asset_type: Optional[str] = None
    asset_tag: Optional[str] = None
    serial_number: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    hostname: Optional[str] = None
    datacenter: Optional[str] = None
    rack: Optional[str] = None
    rack_unit: Optional[str] = None
    u_height: Optional[int] = None
    planned_start_u: Optional[int] = None
    management_ip: Optional[str] = None
    business_ip: Optional[str] = None
    device_role: Optional[str] = None
    vlan: Optional[str] = None
    uplink_switch: Optional[str] = None
    uplink_port: Optional[str] = None
    status: Optional[str] = None
    lifecycle_status: Optional[str] = None
    purchase_date: Optional[str] = None
    warranty_expiry: Optional[str] = None
    department: Optional[str] = None
    notes: Optional[str] = None
    # Network-device-only fields (forwarded to devices table)
    platform: Optional[str] = None
    connection_method: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    snmp_community: Optional[str] = None
    snmp_port: Optional[int] = None


# ── Summary ──────────────────────────────────────────────────────────

@router.get('/assets/summary')
def asset_summary():
    conn = get_db_connection()
    try:
        total = conn.execute('SELECT COUNT(*) FROM physical_assets').fetchone()[0]
        servers = conn.execute("SELECT COUNT(*) FROM physical_assets WHERE asset_type = 'server'").fetchone()[0]
        network = conn.execute("SELECT COUNT(*) FROM physical_assets WHERE asset_type = 'network_device'").fetchone()[0]

        # Warranty expiring within 90 days
        now_str = _utc_now()[:10]
        future_str = (datetime.now(timezone.utc) + timedelta(days=90)).strftime('%Y-%m-%d')
        warranty_soon = conn.execute(
            "SELECT COUNT(*) FROM physical_assets WHERE warranty_expiry != '' AND warranty_expiry <= ? AND warranty_expiry >= ?",
            (future_str, now_str)
        ).fetchone()[0]

        # By status
        by_status = {}
        for row in conn.execute('SELECT status, COUNT(*) as cnt FROM physical_assets GROUP BY status'):
            by_status[row['status']] = row['cnt']

        # By vendor (top 10)
        by_vendor = {}
        for row in conn.execute("SELECT vendor, COUNT(*) as cnt FROM physical_assets WHERE vendor != '' GROUP BY vendor ORDER BY cnt DESC LIMIT 10"):
            by_vendor[row['vendor']] = row['cnt']

        # By datacenter
        by_datacenter = {}
        for row in conn.execute("SELECT datacenter, COUNT(*) as cnt FROM physical_assets WHERE datacenter != '' GROUP BY datacenter ORDER BY cnt DESC"):
            by_datacenter[row['datacenter']] = row['cnt']

        # By department
        by_department = {}
        for row in conn.execute("SELECT department, COUNT(*) as cnt FROM physical_assets WHERE department != '' GROUP BY department ORDER BY cnt DESC"):
            by_department[row['department']] = row['cnt']

        return {
            'total': total,
            'by_type': {'server': servers, 'network_device': network},
            'warranty_expiring_soon': warranty_soon,
            'by_status': by_status,
            'by_vendor': by_vendor,
            'by_datacenter': by_datacenter,
            'by_department': by_department,
        }
    finally:
        conn.close()


# ── List / Search ────────────────────────────────────────────────────

@router.get('/assets')
def list_assets(
    asset_type: str = 'all',
    vendor: str = '',
    datacenter: str = '',
    department: str = '',
    status: str = 'all',
    device_role: str = '',
    q: str = '',
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
):
    conn = get_db_connection()
    try:
        conditions = []
        params = []

        if asset_type != 'all':
            conditions.append('asset_type = ?')
            params.append(asset_type)
        if vendor:
            conditions.append('vendor = ?')
            params.append(vendor)
        if datacenter:
            conditions.append('datacenter = ?')
            params.append(datacenter)
        if department:
            conditions.append('department = ?')
            params.append(department)
        if status != 'all':
            conditions.append('status = ?')
            params.append(status)
        if device_role:
            conditions.append('device_role = ?')
            params.append(device_role)
        if q:
            conditions.append(
                "(asset_tag LIKE ? OR serial_number LIKE ? OR hostname LIKE ? OR vendor LIKE ? OR model LIKE ? OR management_ip LIKE ? OR business_ip LIKE ? OR rack LIKE ?)"
            )
            like = f'%{q}%'
            params.extend([like] * 8)

        where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
        total = conn.execute(f'SELECT COUNT(*) FROM physical_assets{where}', params).fetchone()[0]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f'SELECT * FROM physical_assets{where} ORDER BY created_at DESC LIMIT ? OFFSET ?',
            params + [page_size, offset]
        ).fetchall()

        return {
            'items': [dict(r) for r in rows],
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': max(1, -(-total // page_size)),
        }
    finally:
        conn.close()


@router.get('/assets/{asset_id}')
def get_asset(asset_id: str):
    """Single asset row (same fields as list items) for rack drawer / cross-module detail."""
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM physical_assets WHERE id = ?', (asset_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Asset not found')
        return dict(row)
    finally:
        conn.close()


# ── Create ───────────────────────────────────────────────────────────

@router.post('/assets')
def create_asset(body: AssetCreate):
    conn = get_db_connection()
    try:
        asset_id = f"asset-{uuid.uuid4().hex[:12]}"
        now = _utc_now()

        # Check unique asset_tag if provided
        if body.asset_tag:
            existing = conn.execute('SELECT id FROM physical_assets WHERE asset_tag = ?', (body.asset_tag,)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail='Asset tag already exists')

        conn.execute('''
            INSERT INTO physical_assets (
                id, asset_type, asset_tag, serial_number, vendor, model, hostname,
                datacenter, rack, rack_unit, u_height, planned_start_u, management_ip, business_ip, device_role,
                vlan, uplink_switch, uplink_port,
                status, lifecycle_status, purchase_date, warranty_expiry, department, notes,
                platform, connection_method, username, password, snmp_community, snmp_port,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            asset_id, body.asset_type, body.asset_tag, body.serial_number, body.vendor,
            body.model, body.hostname, body.datacenter, body.rack, body.rack_unit,
            max(1, min(60, body.u_height)), body.planned_start_u,
            body.management_ip, body.business_ip, body.device_role,
            body.vlan, body.uplink_switch, body.uplink_port,
            body.status, body.lifecycle_status,
            body.purchase_date, body.warranty_expiry, body.department, body.notes,
            body.platform, body.connection_method, body.username, _safe_encrypt(body.password),
            body.snmp_community, body.snmp_port,
            now, now
        ))

        # Plan-A: auto-create linked device for managed assets
        device_id = None
        if body.asset_type in ('network_device', 'server'):
            device_id = _create_linked_device(conn, asset_id, body)
            logger.info('Auto-created device %s for asset %s (%s)', device_id, asset_id, body.asset_type)

        conn.commit()
        return {'id': asset_id, 'device_id': device_id}
    finally:
        conn.close()


# ── Update ───────────────────────────────────────────────────────────

@router.put('/assets/{asset_id}')
def update_asset(asset_id: str, body: AssetUpdate):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM physical_assets WHERE id = ?', (asset_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Asset not found')

        # Check unique asset_tag if changed
        if body.asset_tag is not None and body.asset_tag and body.asset_tag != row['asset_tag']:
            dup = conn.execute('SELECT id FROM physical_assets WHERE asset_tag = ? AND id != ?', (body.asset_tag, asset_id)).fetchone()
            if dup:
                raise HTTPException(status_code=409, detail='Asset tag already exists')

        # Detect lifecycle transition for auto password rotation
        old_lifecycle = row['lifecycle_status'] if 'lifecycle_status' in row.keys() else 'staging'
        new_lifecycle = body.lifecycle_status if body.lifecycle_status is not None else old_lifecycle
        transitioning_to_production = (new_lifecycle == 'production' and old_lifecycle != 'production')

        # ── Pre-flight: block production transition if onboarding not complete ──
        if transitioning_to_production and row['asset_type'] in ('network_device', 'server'):
            device_row = conn.execute(
                'SELECT id, onboarding_status, username, password, ip_address FROM devices WHERE asset_id = ?',
                (asset_id,)
            ).fetchone()
            if device_row:
                ob_status = device_row['onboarding_status'] or 'pending_credentials'
                if ob_status not in ('verified', 'active'):
                    status_labels = {
                        'pending_credentials': '待设置凭据',
                        'credentials_set': '待验证连通性',
                    }
                    hint = status_labels.get(ob_status, ob_status)
                    raise HTTPException(
                        status_code=422,
                        detail=f'投产前请先完成口令上手流程（当前状态: {hint}）。请在设备详情中完成凭据设置与连通性验证。'
                    )
                # Also check credentials exist - merge values from request body
                # (body may carry new username/password that hasn't been persisted yet)
                from core.crypto import decrypt_credential
                db_ip = (device_row['ip_address'] or '').strip()
                db_uname = (device_row['username'] or '').strip()
                db_pwd = (decrypt_credential(device_row['password']) or '').strip()
                body_ip = (getattr(body, 'management_ip', None) or '').strip()
                body_uname = (getattr(body, 'username', None) or '').strip()
                body_pwd = (getattr(body, 'password', None) or '').strip()
                ip = body_ip or db_ip
                uname = body_uname or db_uname
                pwd = body_pwd or db_pwd
                missing = []
                if not uname:
                    missing.append('用户名')
                if not pwd:
                    missing.append('密码')
                if not ip:
                    missing.append('管理IP')
                if missing:
                    raise HTTPException(
                        status_code=422,
                        detail=f'投产前请先配置设备凭据（缺少: {", ".join(missing)}）'
                    )

        updates = []
        params = []
        updatable = [
            'asset_type', 'asset_tag', 'serial_number', 'vendor', 'model', 'hostname',
            'datacenter', 'rack', 'rack_unit', 'u_height', 'planned_start_u', 'management_ip', 'business_ip', 'device_role',
            'vlan', 'uplink_switch', 'uplink_port',
            'status', 'lifecycle_status', 'purchase_date', 'warranty_expiry', 'department', 'notes',
            'platform', 'connection_method', 'username', 'password', 'snmp_community', 'snmp_port'
        ]
        for field in updatable:
            val = getattr(body, field, None)
            if val is not None:
                if field == 'password':
                    if val != '':
                        updates.append('password = ?')
                        params.append(_safe_encrypt(val))
                else:
                    updates.append(f'{field} = ?')
                    params.append(val)

        rotation_result = None
        if updates:
            updates.append('updated_at = ?')
            params.append(_utc_now())
            params.append(asset_id)
            conn.execute(f"UPDATE physical_assets SET {', '.join(updates)} WHERE id = ?", tuple(params))

            # Plan-A: sync basic info to linked device
            current_type = body.asset_type if body.asset_type is not None else row['asset_type']
            if current_type == 'network_device':
                _sync_device_from_asset(conn, asset_id, body)
                # Also sync lifecycle_status to linked device
                if body.lifecycle_status is not None:
                    conn.execute(
                        'UPDATE devices SET lifecycle_status = ? WHERE asset_id = ?',
                        (body.lifecycle_status, asset_id)
                    )

            conn.commit()

            # Auto-rotate default password when transitioning to production
            # Run in background thread to avoid blocking HTTP response (~8-10s SSH)
            if transitioning_to_production:
                device_row = conn.execute(
                    'SELECT id FROM devices WHERE asset_id = ?', (asset_id,)
                ).fetchone()
                if device_row:
                    _device_id = device_row['id'] if isinstance(device_row, dict) else device_row[0]
                    # Mark rotation pending immediately
                    conn.execute(
                        "UPDATE devices SET rotation_status = 'rotating' WHERE id = ?",
                        (_device_id,)
                    )
                    conn.commit()

                    def _bg_rotate(dev_id: str, a_id: str, old_lc: str):
                        try:
                            from services.password_rotation_service import rotate_password
                            # Fetch current device state to check auth_model
                            bg_conn_init = get_db_connection()
                            try:
                                dev_state = bg_conn_init.execute('SELECT auth_model FROM devices WHERE id = ?', (dev_id,)).fetchone()
                            finally:
                                bg_conn_init.close()
                                
                            auth_model = dev_state['auth_model'] if dev_state else 'single'
                            
                            logger.info(f"[Lifecycle] Starting Admin rotation for {dev_id}")
                            admin_result = rotate_password(dev_id, role='admin')
                            
                            if admin_result and admin_result.get('success'):
                                logger.info(f"[Lifecycle] Admin rotation SUCCESS for {dev_id}")
                                if auth_model == 'dual':
                                    logger.info(f"[Lifecycle] Starting Normal rotation for {dev_id} using new admin credentials")
                                    import time
                                    time.sleep(1) 
                                    normal_result = rotate_password(dev_id, role='normal')
                                    if not normal_result.get('success'):
                                        msg = normal_result.get('message', 'Unknown error')
                                        logger.error(f"[Lifecycle] Normal rotation FAILED for {dev_id}: {msg}")
                                        raise Exception(f"Normal user rotation failed: {msg}")
                                    logger.info(f"[Lifecycle] Normal rotation SUCCESS for {dev_id}")
                                
                                # All good
                                bg_conn = get_db_connection()
                                try:
                                    bg_conn.execute(
                                        "UPDATE devices SET rotation_status = 'completed' WHERE id = ?",
                                        (dev_id,)
                                    )
                                    bg_conn.commit()
                                finally:
                                    bg_conn.close()
                                logger.info(f'Auto-rotated all credentials for device {dev_id} successfully')
                            else:
                                err_msg = admin_result.get('message', 'Admin rotation failed') if admin_result else 'No response'
                                raise Exception(err_msg)
                        except Exception as e:
                            logger.error(f"[Lifecycle] Rotation FAILED for {dev_id}: {e}")
                            try:
                                bg_conn_fail = get_db_connection()
                                bg_conn_fail.execute(
                                    "UPDATE devices SET rotation_status = 'failed', lifecycle_status = ? WHERE id = ?",
                                    (old_lc, dev_id)
                                )
                                bg_conn_fail.execute(
                                    'UPDATE physical_assets SET lifecycle_status = ? WHERE id = ?',
                                    (old_lc, a_id)
                                )
                                bg_conn_fail.commit()
                                bg_conn_fail.close()
                            except Exception:
                                pass

                    threading.Thread(
                        target=_bg_rotate,
                        args=(_device_id, asset_id, old_lifecycle),
                        daemon=True,
                    ).start()
                    rotation_result = {'pending': True}

        return {
            'ok': True,
            'password_rotated': rotation_result is not None and rotation_result.get('success', False),
            'rotation_pending': rotation_result is not None and rotation_result.get('pending', False),
            'rotation_detail': rotation_result.get('message', '') if rotation_result and not rotation_result.get('pending') else None,
            'lifecycle_reverted': rotation_result is not None and not rotation_result.get('success', False) and not rotation_result.get('pending', False),
        }
    finally:
        conn.close()


# ── Delete ───────────────────────────────────────────────────────────

@router.delete('/assets/{asset_id}')
def delete_asset(asset_id: str):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT id FROM physical_assets WHERE id = ?', (asset_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Asset not found')
        # Plan-A: cascade-delete linked device first
        _delete_linked_device(conn, asset_id)
        conn.execute('DELETE FROM physical_assets WHERE id = ?', (asset_id,))
        conn.commit()
        return {'ok': True}
    finally:
        conn.close()


# ── Rotation status polling ──────────────────────────────────────────

@router.get('/assets/{asset_id}/rotation-status')
def get_rotation_status(asset_id: str):
    """Poll rotation progress after async production transition."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT d.rotation_status, d.lifecycle_status, d.password_last_rotated '
            'FROM devices d WHERE d.asset_id = ?', (asset_id,)
        ).fetchone()
        if not row:
            return {'rotation_status': 'none'}
        return {
            'rotation_status': row['rotation_status'] or '',
            'lifecycle_status': row['lifecycle_status'] or 'staging',
            'password_last_rotated': row['password_last_rotated'] or '',
        }
    finally:
        conn.close()


# ── Import (batch) ───────────────────────────────────────────────────

@router.post('/assets/import')
def import_assets(items: list[AssetCreate]):
    conn = get_db_connection()
    try:
        now = _utc_now()
        created = 0
        skipped = 0
        for body in items:
            asset_id = f"asset-{uuid.uuid4().hex[:12]}"
            if body.asset_tag:
                existing = conn.execute('SELECT id FROM physical_assets WHERE asset_tag = ?', (body.asset_tag,)).fetchone()
                if existing:
                    skipped += 1
                    continue
            conn.execute('''
                INSERT INTO physical_assets (
                    id, asset_type, asset_tag, serial_number, vendor, model, hostname,
                    datacenter, rack, rack_unit, u_height, planned_start_u, management_ip, business_ip, device_role,
                    vlan, uplink_switch, uplink_port,
                    status, purchase_date, warranty_expiry, department, notes,
                    platform, connection_method, username, password, snmp_community, snmp_port,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                asset_id, body.asset_type, body.asset_tag, body.serial_number, body.vendor,
                body.model, body.hostname, body.datacenter, body.rack, body.rack_unit,
                max(1, min(60, body.u_height)), body.planned_start_u,
                body.management_ip, body.business_ip, body.device_role,
                body.vlan, body.uplink_switch, body.uplink_port,
                body.status,
                body.purchase_date, body.warranty_expiry, body.department, body.notes,
                body.platform, body.connection_method, body.username, _safe_encrypt(body.password),
                body.snmp_community, body.snmp_port,
                now, now
            ))
            # Plan-A: auto-create linked device for managed assets
            if body.asset_type in ('network_device', 'server'):
                _create_linked_device(conn, asset_id, body)
            created += 1
        conn.commit()
        return {'created': created, 'skipped': skipped}
    finally:
        conn.close()

@router.get("/assets/{asset_id}/verify")
async def verify_asset_connectivity(asset_id: str):
    """
    Perform a quick connectivity check:
    1. Ping management IP
    2. Try SSH port (22)
    3. If credentials exist, try SSH login (fast)
    """
    conn = get_db_connection()
    try:
        asset = conn.execute('SELECT * FROM physical_assets WHERE id = ?', (asset_id,)).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        
        asset = dict(asset)
        ip = asset.get('management_ip')
        if not ip:
            return {"success": False, "error": "No management IP configured", "ping": False, "ssh": False}

        results = {
            "ping": False,
            "ssh": False,
            "latency": 0,
            "ssh_error": None,
            "ping_error": None
        }

        # 1. Ping Test
        try:
            latency = ping3.ping(ip, timeout=1)
            if latency is not None and latency is not False:
                results["ping"] = True
                results["latency"] = round(latency * 1000, 2)
            else:
                results["ping_error"] = "Ping timeout"
        except Exception as e:
            results["ping_error"] = str(e)

        # 2. SSH Port Test (Quick check)
        ssh_port = 22
        try:
            with socket.create_connection((ip, ssh_port), timeout=1):
                results["ssh_port_open"] = True
        except Exception:
            results["ssh_port_open"] = False
            results["ssh_error"] = "SSH port closed or unreachable"
            return results

        # 3. SSH Login Test (if credentials found)
        # Check physical_assets first, then linked device
        username = asset.get('username')
        password_enc = asset.get('password')
        
        if not username or not password_enc:
            dev = conn.execute('SELECT username, password, platform FROM devices WHERE asset_id = ?', (asset_id,)).fetchone()
            if dev:
                username = dev['username']
                password_enc = dev['password']
                # FORCE linux if it's a server
                if asset['asset_type'] == 'server':
                    platform = 'linux'
                else:
                    platform = dev['platform']
            else:
                platform = _platform_from_vendor(asset['vendor'], asset['asset_type'])
        else:
            if asset['asset_type'] == 'server':
                platform = 'linux'
            else:
                platform = _platform_from_vendor(asset['vendor'], asset['asset_type'])

        if username and password_enc:
            try:
                password = decrypt_credential(password_enc)
                # Use Scrapli for a quick "fast" login
                # We just want to see if we can get a prompt
                import platform as platform_module
                device_config = {
                    "host": ip,
                    "auth_username": username,
                    "auth_password": password,
                    "platform": platform or "linux",
                    "auth_strict_key": False,
                    "timeout_socket": 5,
                    "timeout_transport": 10,
                }
                
                # Windows compatibility (same as ScrapliDriver)
                if platform_module.system() == 'Windows':
                    device_config['transport'] = 'paramiko'
                    device_config['transport_options'] = {
                        'paramiko_open_options': {
                            'look_for_keys': False,
                            'allow_agent': False,
                        }
                    }

                if asset['asset_type'] == 'server':
                    # FOR SERVERS: Use direct Paramiko to avoid prompt detection complexity
                    import paramiko
                    client = paramiko.SSHClient()
                    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    try:
                        client.connect(
                            hostname=ip,
                            username=username,
                            password=password,
                            port=device_config.get('port', 22),
                            timeout=10,
                            allow_agent=False,
                            look_for_keys=False,
                            disabled_algorithms={}
                        )
                        results["ssh"] = True
                        results["ssh_summary"] = "SSH 登录验证成功 (直接认证通过)"
                    finally:
                        client.close()
                else:
                    # FOR NETWORK DEVICES: Use Scrapli for full stateful check
                    with Scrapli(**device_config) as conn_ssh:
                        results["ssh"] = True
                        results["ssh_summary"] = f"SSH 登录验证成功 ({platform} 提示符已捕获)"
            except Exception as e:
                err_str = str(e)
                logger.error(f"Asset verification failed for {ip}: {err_str}", exc_info=True)
                # Humanize the error for the UI
                err_code = get_ssh_error_code(err_str)
                if err_code == 'ssh_authentication_failed':
                    results["ssh_error"] = "认证失败：用户名或密码错误，或服务器禁用了密码登录"
                elif err_code == 'ssh_transport_timeout':
                    results["ssh_error"] = "连接超时：网络不通或 SSH 服务未响应"
                elif 'ScrapliConnectionNotOpened' in err_str:
                    results["ssh_error"] = "连接未建立：请检查 IP 和端口"
                else:
                    # Clean up technical debris from the error string
                    clean_err = err_str.split('\n')[0]
                    results["ssh_error"] = f"SSH 失败: {clean_err}"
        else:
            results["ssh_error"] = "No credentials provided for login test"

        return results
    finally:
        conn.close()
