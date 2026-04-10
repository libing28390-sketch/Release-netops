"""
assets.py — Physical Asset Management (PAM) API
Provides CRUD for servers and network devices with physical/location metadata.
When asset_type='network_device', a linked record in the `devices` table is
auto-created / synced / cascade-deleted so that the asset registry serves as
the single source of truth (Plan-A).
"""

import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import get_db_connection
from core.crypto import encrypt_credential

logger = logging.getLogger(__name__)

router = APIRouter()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')


# ── helpers: devices ↔ physical_assets sync ──────────────────────────

def _platform_from_vendor(vendor: str) -> str:
    """Map asset vendor string to a best-guess Netmiko platform."""
    v = vendor.lower()
    if 'cisco' in v:
        return 'cisco_ios'
    if 'huawei' in v:
        return 'huawei_vrp'
    if 'h3c' in v or 'comware' in v:
        return 'hp_comware'
    if 'arista' in v:
        return 'arista_eos'
    if 'juniper' in v:
        return 'juniper_junos'
    return 'cisco_ios'


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
    platform = getattr(body, 'platform', '') or _platform_from_vendor(body.vendor)
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
    management_ip: str = ''
    business_ip: str = ''
    device_role: str = ''  # switch/router/firewall/ap — only for network_device
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
    page_size: int = Query(50, ge=1, le=200),
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
                datacenter, rack, rack_unit, management_ip, business_ip, device_role,
                vlan, uplink_switch, uplink_port,
                status, lifecycle_status, purchase_date, warranty_expiry, department, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            asset_id, body.asset_type, body.asset_tag, body.serial_number, body.vendor,
            body.model, body.hostname, body.datacenter, body.rack, body.rack_unit,
            body.management_ip, body.business_ip, body.device_role,
            body.vlan, body.uplink_switch, body.uplink_port,
            body.status, body.lifecycle_status,
            body.purchase_date, body.warranty_expiry, body.department, body.notes, now, now
        ))

        # Plan-A: auto-create linked device for network_device assets
        device_id = None
        if body.asset_type == 'network_device':
            device_id = _create_linked_device(conn, asset_id, body)
            logger.info('Auto-created device %s for asset %s', device_id, asset_id)

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
        if transitioning_to_production and row['asset_type'] == 'network_device':
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
                # Also check credentials exist — merge values from request body
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
            'datacenter', 'rack', 'rack_unit', 'management_ip', 'business_ip', 'device_role',
            'vlan', 'uplink_switch', 'uplink_port',
            'status', 'lifecycle_status', 'purchase_date', 'warranty_expiry', 'department', 'notes'
        ]
        for field in updatable:
            val = getattr(body, field, None)
            if val is not None:
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
            if transitioning_to_production:
                device_row = conn.execute(
                    'SELECT id FROM devices WHERE asset_id = ?', (asset_id,)
                ).fetchone()
                if device_row:
                    try:
                        from services.password_rotation_service import rotate_password
                        rotation_result = rotate_password(device_row['id'])
                        if rotation_result and not rotation_result.get('success'):
                            # Rollback: revert lifecycle to previous state
                            conn.execute(
                                'UPDATE physical_assets SET lifecycle_status = ? WHERE id = ?',
                                (old_lifecycle, asset_id)
                            )
                            conn.execute(
                                'UPDATE devices SET lifecycle_status = ? WHERE asset_id = ?',
                                (old_lifecycle, asset_id)
                            )
                            conn.commit()
                            logger.warning(
                                'Auto-rotation failed for asset %s, lifecycle reverted to %s: %s',
                                asset_id, old_lifecycle, rotation_result.get('message', '')
                            )
                        else:
                            logger.info(
                                'Auto-rotated password for device %s on production transition (asset %s)',
                                device_row['id'], asset_id
                            )
                    except Exception as e:
                        # Rollback lifecycle on unexpected error
                        conn.execute(
                            'UPDATE physical_assets SET lifecycle_status = ? WHERE id = ?',
                            (old_lifecycle, asset_id)
                        )
                        conn.execute(
                            'UPDATE devices SET lifecycle_status = ? WHERE asset_id = ?',
                            (old_lifecycle, asset_id)
                        )
                        conn.commit()
                        logger.warning('Auto-rotation exception for asset %s, lifecycle reverted: %s', asset_id, e)
                        rotation_result = {'success': False, 'message': str(e)}

        return {
            'ok': True,
            'password_rotated': rotation_result is not None and rotation_result.get('success', False),
            'rotation_detail': rotation_result.get('message', '') if rotation_result else None,
            'lifecycle_reverted': rotation_result is not None and not rotation_result.get('success', False),
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
                    datacenter, rack, rack_unit, management_ip, business_ip, device_role,
                    vlan, uplink_switch, uplink_port,
                    status, purchase_date, warranty_expiry, department, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                asset_id, body.asset_type, body.asset_tag, body.serial_number, body.vendor,
                body.model, body.hostname, body.datacenter, body.rack, body.rack_unit,
                body.management_ip, body.business_ip, body.device_role,
                body.vlan, body.uplink_switch, body.uplink_port,
                body.status,
                body.purchase_date, body.warranty_expiry, body.department, body.notes, now, now
            ))
            # Plan-A: auto-create linked device for network_device assets
            if body.asset_type == 'network_device':
                _create_linked_device(conn, asset_id, body)
            created += 1
        conn.commit()
        return {'created': created, 'skipped': skipped}
    finally:
        conn.close()
