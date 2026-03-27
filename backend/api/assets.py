"""
assets.py — Physical Asset Management (PAM) API
Provides CRUD for servers and network devices with physical/location metadata.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')


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
    purchase_date: str = ''
    warranty_expiry: str = ''
    department: str = ''
    notes: str = ''


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
    purchase_date: Optional[str] = None
    warranty_expiry: Optional[str] = None
    department: Optional[str] = None
    notes: Optional[str] = None


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
        warranty_soon = conn.execute(
            "SELECT COUNT(*) FROM physical_assets WHERE warranty_expiry != '' AND warranty_expiry <= date(?, '+90 days') AND warranty_expiry >= ?",
            (now_str, now_str)
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
        conn.commit()
        return {'id': asset_id}
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

        updates = []
        params = []
        updatable = [
            'asset_type', 'asset_tag', 'serial_number', 'vendor', 'model', 'hostname',
            'datacenter', 'rack', 'rack_unit', 'management_ip', 'business_ip', 'device_role',
            'vlan', 'uplink_switch', 'uplink_port',
            'status', 'purchase_date', 'warranty_expiry', 'department', 'notes'
        ]
        for field in updatable:
            val = getattr(body, field, None)
            if val is not None:
                updates.append(f'{field} = ?')
                params.append(val)

        if updates:
            updates.append('updated_at = ?')
            params.append(_utc_now())
            params.append(asset_id)
            conn.execute(f"UPDATE physical_assets SET {', '.join(updates)} WHERE id = ?", tuple(params))
            conn.commit()
        return {'ok': True}
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
            created += 1
        conn.commit()
        return {'created': created, 'skipped': skipped}
    finally:
        conn.close()
