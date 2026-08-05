"""
rack_service.py — 机柜管理服务层

Provides CRUD for racks, device types, and rack devices.
Enforces U-position constraints: no overlap, within rack bounds, start_u >= 1.
"""

import uuid
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def _resolve_site(conn, site_id: str = '', legacy_label: str = '') -> tuple[str, str, str]:
    """Resolve a rack location to the canonical sites row.

    The old rack form stored free text in ``datacenter``.  Accepting that
    value here keeps old imports usable, while every new write is normalized
    to ``site_id`` and the site code is only mirrored into the legacy column.
    """
    requested_id = (site_id or '').strip()
    requested_label = (legacy_label or '').strip()
    if requested_id:
        row = conn.execute(
            """SELECT id, site_code, site_name FROM sites
               WHERE id = ? OR site_code = ? OR site_name = ?
               ORDER BY CASE WHEN id = ? THEN 0 WHEN site_code = ? THEN 1 ELSE 2 END
               LIMIT 1""",
            (requested_id, requested_id, requested_id, requested_id, requested_id),
        ).fetchone()
        if not row:
            raise ValueError(f"Site not found: {requested_id}")
        return row['id'], row['site_code'] or row['site_name'] or row['id'], row['site_name'] or row['site_code'] or row['id']

    if requested_label:
        row = conn.execute(
            """SELECT id, site_code, site_name FROM sites
               WHERE id = ? OR site_code = ? OR site_name = ?
               ORDER BY CASE WHEN id = ? THEN 0 WHEN site_code = ? THEN 1 ELSE 2 END
               LIMIT 1""",
            (requested_label, requested_label, requested_label, requested_label, requested_label),
        ).fetchone()
        if row:
            return row['id'], row['site_code'] or row['site_name'] or row['id'], row['site_name'] or row['site_code'] or row['id']
        raise ValueError(f"Site not found: {requested_label}")

    rows = conn.execute(
        "SELECT id, site_code, site_name FROM sites WHERE status = 'active' ORDER BY site_code"
    ).fetchall()
    if len(rows) == 1:
        row = rows[0]
        return row['id'], row['site_code'] or row['site_name'] or row['id'], row['site_name'] or row['site_code'] or row['id']
    raise ValueError("A site is required when creating a rack")


# ═══════════════════════════════════════════════════════════════════════════════
# RackType CRUD
# ═══════════════════════════════════════════════════════════════════════════════

def list_rack_types(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM rack_types ORDER BY name").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_rack_type(conn, rack_type_id: str) -> dict:
    row = conn.execute("SELECT * FROM rack_types WHERE id = ?", (rack_type_id,)).fetchone()
    if not row:
        raise ValueError(f"Rack type not found: {rack_type_id}")
    return _row_to_dict(row)


def create_rack_type(conn, *, name: str, vendor: str = '', model: str = '',
                     total_u: int = 42, width_mm: int = 600, depth_mm: int = 1000,
                     max_weight_kg: int = 0, power_capacity_watts: int = 0,
                     allow_front_rear_mount: bool = True, description: str = '') -> dict:
    rack_type_id = str(uuid.uuid4())
    now = _utc_now()
    conn.execute(
        """INSERT INTO rack_types (
            id, name, vendor, model, total_u, width_mm, depth_mm, max_weight_kg,
            power_capacity_watts, allow_front_rear_mount, description, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rack_type_id, name.strip(), vendor, model, total_u, width_mm, depth_mm,
            max_weight_kg, power_capacity_watts, 1 if allow_front_rear_mount else 0,
            description, now, now,
        )
    )
    conn.commit()
    return get_rack_type(conn, rack_type_id)


def update_rack_type(conn, rack_type_id: str, **fields) -> dict:
    existing = get_rack_type(conn, rack_type_id)
    updates = []
    params = []
    for key in (
        'name', 'vendor', 'model', 'total_u', 'width_mm', 'depth_mm',
        'max_weight_kg', 'power_capacity_watts', 'allow_front_rear_mount', 'description'
    ):
        if key in fields and fields[key] is not None:
            val = fields[key]
            if key == 'allow_front_rear_mount':
                val = 1 if val else 0
            updates.append(f"{key} = ?")
            params.append(val)
    if not updates:
        return existing
    updates.append("updated_at = ?")
    params.append(_utc_now())
    params.append(rack_type_id)
    conn.execute(f"UPDATE rack_types SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    return get_rack_type(conn, rack_type_id)


def delete_rack_type(conn, rack_type_id: str) -> None:
    get_rack_type(conn, rack_type_id)
    usage = conn.execute(
        "SELECT COUNT(*) as cnt FROM racks WHERE rack_type_id = ?", (rack_type_id,)
    ).fetchone()
    cnt = usage['cnt'] if hasattr(usage, 'keys') and 'cnt' in usage.keys() else usage[0]
    if cnt and cnt > 0:
        raise ValueError("Cannot delete rack type: one or more racks are using it.")
    conn.execute("DELETE FROM rack_types WHERE id = ?", (rack_type_id,))
    conn.commit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Rack CRUD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def list_racks(conn, site_id: str = '', datacenter: str = '') -> list[dict]:
    query = """SELECT r.*, s.site_code, s.site_name
               FROM racks r LEFT JOIN sites s ON s.id = r.site_id"""
    if site_id:
        rows = conn.execute(query + " WHERE r.site_id = ? ORDER BY r.name", (site_id,)).fetchall()
    elif datacenter:
        rows = conn.execute(
            query + " WHERE r.datacenter = ? OR s.site_code = ? OR s.site_name = ? ORDER BY r.name",
            (datacenter, datacenter, datacenter),
        ).fetchall()
    else:
        rows = conn.execute(query + " ORDER BY s.site_code, r.name").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_rack(conn, rack_id: str) -> dict:
    row = conn.execute(
        "SELECT r.*, s.site_code, s.site_name FROM racks r LEFT JOIN sites s ON s.id = r.site_id WHERE r.id = ?",
        (rack_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Rack not found: {rack_id}")
    return _row_to_dict(row)


def create_rack(conn, *, name: str, datacenter: str = '', floor: str = '', room: str = '',
                row: str = '', total_u: int = 42, description: str = '',
                status: str = 'active', power_capacity_watts: int = 0,
                site_id: str = 'site-default', rack_code: str = '',
                placement_strategy: str = 'bottom_first', rack_type_id: str = '',
                width_mm: int = 600, depth_mm: int = 1000,
                allow_front_rear_mount: bool = True, commit: bool = True, **kwargs) -> dict:
    rack_id = str(uuid.uuid4())
    if not rack_code:
        rack_code = f"RACK_{uuid.uuid4().hex[:12].upper()}"

    site_id, site_code, _site_name = _resolve_site(conn, site_id, datacenter)

    if rack_type_id:
        rack_type = get_rack_type(conn, rack_type_id)
        total_u = kwargs.get('total_u') or total_u or rack_type.get('total_u') or 42
        width_mm = kwargs.get('width_mm') or width_mm or rack_type.get('width_mm') or 600
        depth_mm = kwargs.get('depth_mm') or depth_mm or rack_type.get('depth_mm') or 1000
        if not power_capacity_watts:
            power_capacity_watts = int(rack_type.get('power_capacity_watts') or 0)
        if kwargs.get('max_weight_kg') is None:
            kwargs['max_weight_kg'] = rack_type.get('max_weight_kg')
        allow_front_rear_mount = bool(rack_type.get('allow_front_rear_mount')) if allow_front_rear_mount is None else allow_front_rear_mount
    
    # Synchronize old and new fields
    rack_name = kwargs.get('rack_name') or name
    room_name = kwargs.get('room_name') or room
    row_name = kwargs.get('row_name') or row
    remarks = kwargs.get('remarks') or description
    power_capacity_w = kwargs.get('power_capacity_w') or power_capacity_watts or 5000
    used_u = kwargs.get('used_u', 0)
    available_u = kwargs.get('available_u')
    if available_u is None:
        available_u = total_u - used_u
        
    current_power_w = kwargs.get('current_power_w', 0)
    power_utilization = kwargs.get('power_utilization', 0.0)
    max_weight_kg = kwargs.get('max_weight_kg', None)
    current_weight_kg = kwargs.get('current_weight_kg', 0)
    cooling_zone = kwargs.get('cooling_zone', '')
    
    now = _utc_now()
    conn.execute(
        """INSERT INTO racks (
            id, site_id, rack_code, rack_name, name, datacenter, floor, room, row, room_name, row_name,
            total_u, used_u, available_u, power_capacity_w, power_capacity_watts, status, remarks, description,
            current_power_w, power_utilization, max_weight_kg, current_weight_kg, cooling_zone,
            placement_strategy, rack_type_id, width_mm, depth_mm, allow_front_rear_mount, created_at, updated_at
           )
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rack_id, site_id, rack_code, rack_name, name, site_code, floor, room, row, room_name, row_name,
            total_u, used_u, available_u, power_capacity_w, power_capacity_watts, status, remarks, description,
            current_power_w, power_utilization, max_weight_kg, current_weight_kg, cooling_zone,
            placement_strategy, rack_type_id, width_mm, depth_mm, 1 if allow_front_rear_mount else 0, now, now
        )
    )
    if commit:
        conn.commit()
    logger.info(f"[RackService] Created rack '{name}' at site {site_id}")
    return get_rack(conn, rack_id)


def update_rack(conn, rack_id: str, **fields) -> dict:
    existing = get_rack(conn, rack_id)
    updates = []
    params = []

    if 'site_id' in fields and fields['site_id'] is not None:
        resolved_id, site_code, _site_name = _resolve_site(conn, fields['site_id'])
        fields['site_id'] = resolved_id
        fields['datacenter'] = site_code
    elif 'datacenter' in fields and fields['datacenter'] is not None:
        resolved_id, site_code, _site_name = _resolve_site(conn, '', fields['datacenter'])
        fields['site_id'] = resolved_id
        fields['datacenter'] = site_code
    
    # We should support updating both sets of fields
    supported_keys = (
        'name', 'datacenter', 'floor', 'room', 'row', 'total_u', 'description', 'status', 'power_capacity_watts',
        'site_id', 'rack_code', 'rack_name', 'room_name', 'row_name', 'used_u', 'available_u',
        'power_capacity_w', 'current_power_w', 'power_utilization', 'max_weight_kg', 'current_weight_kg',
        'cooling_zone', 'remarks', 'placement_strategy', 'rack_type_id', 'width_mm', 'depth_mm',
        'allow_front_rear_mount'
    )
    
    # Align values if one of the duplicates is modified
    if 'name' in fields and 'rack_name' not in fields:
        fields['rack_name'] = fields['name']
    elif 'rack_name' in fields and 'name' not in fields:
        fields['name'] = fields['rack_name']
        
    if 'room' in fields and 'room_name' not in fields:
        fields['room_name'] = fields['room']
    elif 'room_name' in fields and 'room' not in fields:
        fields['room'] = fields['room_name']
        
    if 'row' in fields and 'row_name' not in fields:
        fields['row_name'] = fields['row']
    elif 'row_name' in fields and 'row' not in fields:
        fields['row'] = fields['row_name']
        
    if 'description' in fields and 'remarks' not in fields:
        fields['remarks'] = fields['description']
    elif 'remarks' in fields and 'description' not in fields:
        fields['description'] = fields['remarks']
        
    if 'power_capacity_watts' in fields and 'power_capacity_w' not in fields:
        fields['power_capacity_w'] = fields['power_capacity_watts']
    elif 'power_capacity_w' in fields and 'power_capacity_watts' not in fields:
        fields['power_capacity_watts'] = fields['power_capacity_w']
        
    for key in supported_keys:
        if key in fields and fields[key] is not None:
            if key == 'allow_front_rear_mount':
                fields[key] = 1 if fields[key] else 0
            updates.append(f"{key} = ?")
            params.append(fields[key])
            
    if not updates:
        return existing
        
    updates.append("updated_at = ?")
    params.append(_utc_now())
    params.append(rack_id)
    
    conn.execute(f"UPDATE racks SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    return get_rack(conn, rack_id)


def delete_rack(conn, rack_id: str) -> None:
    get_rack(conn, rack_id)  # ensure exists
    device_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM rack_devices WHERE rack_id = ?", (rack_id,)
    ).fetchone()
    cnt = device_count['cnt'] if hasattr(device_count, '__getitem__') and 'cnt' in device_count.keys() else device_count[0]
    if cnt and cnt > 0:
        raise ValueError(
            "Cannot delete rack: remove all installed devices from this rack first, then try again."
        )
    conn.execute("DELETE FROM racks WHERE id = ?", (rack_id,))
    conn.commit()
    logger.info(f"[RackService] Deleted rack {rack_id}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DeviceType CRUD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def list_device_types(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM device_types ORDER BY vendor, model").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_device_type(conn, dt_id: str) -> dict:
    row = conn.execute("SELECT * FROM device_types WHERE id = ?", (dt_id,)).fetchone()
    if not row:
        raise ValueError(f"DeviceType not found: {dt_id}")
    return _row_to_dict(row)


def create_device_type(conn, *, model: str, vendor: str = '', u_height: int = 1,
                       device_role: str = 'switch', is_full_depth: bool = True,
                       description: str = '', power_watts: int = 0) -> dict:
    dt_id = str(uuid.uuid4())
    now = _utc_now()
    conn.execute(
        """INSERT INTO device_types (id, model, vendor, u_height, device_role, is_full_depth, description, power_watts, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (dt_id, model, vendor, u_height, device_role, 1 if is_full_depth else 0, description, power_watts, now, now)
    )
    conn.commit()
    logger.info(f"[RackService] Created device type '{vendor} {model}' ({u_height}U, {power_watts}W)")
    return get_device_type(conn, dt_id)


def update_device_type(conn, dt_id: str, **fields) -> dict:
    existing = get_device_type(conn, dt_id)
    updates = []
    params = []
    for key in ('model', 'vendor', 'u_height', 'device_role', 'is_full_depth', 'description', 'power_watts'):
        if key in fields and fields[key] is not None:
            val = fields[key]
            if key == 'is_full_depth':
                val = 1 if val else 0
            updates.append(f"{key} = ?")
            params.append(val)
    if not updates:
        return existing
    updates.append("updated_at = ?")
    params.append(_utc_now())
    params.append(dt_id)
    conn.execute(f"UPDATE device_types SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    return get_device_type(conn, dt_id)


def delete_device_type(conn, dt_id: str) -> None:
    get_device_type(conn, dt_id)
    usage = conn.execute(
        "SELECT COUNT(*) as cnt FROM rack_devices WHERE device_type_id = ?", (dt_id,)
    ).fetchone()
    if usage and (usage['cnt'] if hasattr(usage, '__getitem__') else usage[0]) > 0:
        raise ValueError("Cannot delete device type in use by rack devices.")
    conn.execute("DELETE FROM device_types WHERE id = ?", (dt_id,))
    conn.commit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RackDevice CRUD + U-position constraint enforcement
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _check_u_constraints(conn, rack_id: str, start_u: int, u_height: int,
                         position: str, exclude_device_id: str = ''):
    """Enforce: start_u >= 1, end_u <= total_u, no overlap with existing devices."""
    from database import _USE_PG
    if _USE_PG:
        # Row-level lock on parent rack row to prevent race conditions during concurrent inserts
        conn.execute("SELECT 1 FROM racks WHERE id = ? FOR UPDATE", (rack_id,))

    rack = get_rack(conn, rack_id)
    total_u = rack['total_u']
    end_u = start_u + u_height - 1

    if start_u < 1:
        raise ValueError(f"起始 U 位必须大于或等于 1 (当前: {start_u})")
    if end_u > total_u:
        raise ValueError(
            f"设备超出机柜高度范围：占用 U{start_u}-U{end_u}，但机柜总高度仅有 {total_u}U"
        )

    # Check overlap with other devices on the same position (front/rear)
    query = """
        SELECT rd.id, rd.name, rd.start_u, dt.u_height
        FROM rack_devices rd
        JOIN device_types dt ON rd.device_type_id = dt.id
        WHERE rd.rack_id = ? AND rd.position = ?
    """
    params = [rack_id, position]
    if exclude_device_id:
        query += " AND rd.id != ?"
        params.append(exclude_device_id)

    existing = conn.execute(query, params).fetchall()
    for dev in existing:
        d = _row_to_dict(dev)
        existing_start = d['start_u']
        existing_end = existing_start + d['u_height'] - 1
        if start_u <= existing_end and end_u >= existing_start:
            raise ValueError(
                f"U位冲突：U{start_u}-U{end_u} 与已上架设备 '{d['name']}' (U{existing_start}-U{existing_end}) 空间重叠。"
            )


def list_rack_devices(conn, rack_id: str) -> list[dict]:
    """Return all devices in a rack with device type info, sorted by start_u."""
    rows = conn.execute("""
        SELECT rd.*, dt.model, dt.vendor, dt.u_height, dt.device_role, dt.is_full_depth, dt.power_watts
        FROM rack_devices rd
        JOIN device_types dt ON rd.device_type_id = dt.id
        WHERE rd.rack_id = ?
        ORDER BY rd.start_u ASC
    """, (rack_id,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_rack_device(conn, device_id: str) -> dict:
    row = conn.execute("""
        SELECT rd.*, dt.model, dt.vendor, dt.u_height, dt.device_role, dt.is_full_depth, dt.power_watts
        FROM rack_devices rd
        JOIN device_types dt ON rd.device_type_id = dt.id
        WHERE rd.id = ?
    """, (device_id,)).fetchone()
    if not row:
        raise ValueError(f"Rack device not found: {device_id}")
    return _row_to_dict(row)


def create_rack_device(conn, *, name: str, rack_id: str, device_type_id: str,
                       start_u: int, position: str = 'front', status: str = 'active',
                       serial_number: str = '', asset_id: str = '') -> dict:
    # Get device type for u_height
    dt = get_device_type(conn, device_type_id)
    u_height = dt['u_height']

    # Enforce constraints
    _check_u_constraints(conn, rack_id, start_u, u_height, position)

    device_id = str(uuid.uuid4())
    now = _utc_now()
    conn.execute(
        """INSERT INTO rack_devices
           (id, name, rack_id, device_type_id, start_u, position, status, serial_number, asset_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (device_id, name, rack_id, device_type_id, start_u, position, status,
         serial_number, asset_id, now, now)
    )
    conn.commit()
    logger.info(f"[RackService] Added '{name}' to rack at U{start_u} ({position})")
    return get_rack_device(conn, device_id)


def update_rack_device(conn, device_id: str, **fields) -> dict:
    existing = get_rack_device(conn, device_id)

    # Resolve new values
    rack_id = fields.get('rack_id') or existing['rack_id']
    device_type_id = fields.get('device_type_id') or existing['device_type_id']
    start_u = fields.get('start_u') if fields.get('start_u') is not None else existing['start_u']
    position = fields.get('position') or existing['position']

    dt = get_device_type(conn, device_type_id)
    _check_u_constraints(conn, rack_id, start_u, dt['u_height'], position, exclude_device_id=device_id)

    updates = []
    params = []
    for key in ('name', 'rack_id', 'device_type_id', 'start_u', 'position', 'status', 'serial_number', 'asset_id'):
        if key in fields and fields[key] is not None:
            updates.append(f"{key} = ?")
            params.append(fields[key])
    if not updates:
        return existing
    updates.append("updated_at = ?")
    params.append(_utc_now())
    params.append(device_id)
    conn.execute(f"UPDATE rack_devices SET {', '.join(updates)} WHERE id = ?", params)

    # Reverse-sync: if start_u changed and device is linked to an asset, update physical_assets
    if 'start_u' in fields and fields['start_u'] is not None:
        asset_id = existing.get('asset_id')
        if asset_id:
            conn.execute(
                "UPDATE physical_assets SET planned_start_u = ?, updated_at = ? WHERE id = ?",
                (fields['start_u'], _utc_now(), asset_id)
            )
            logger.info(f"[RackService] Reverse-synced planned_start_u={fields['start_u']} to asset {asset_id}")

    conn.commit()
    return get_rack_device(conn, device_id)


def delete_rack_device(conn, device_id: str) -> None:
    get_rack_device(conn, device_id)
    conn.execute("DELETE FROM rack_devices WHERE id = ?", (device_id,))
    conn.commit()
    logger.info(f"[RackService] Removed rack device {device_id}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Rack Layout — full visualization payload
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_rack_layout(conn, rack_id: str) -> dict:
    """Return rack info + all devices for rendering a rack diagram."""
    rack = get_rack(conn, rack_id)
    devices = list_rack_devices(conn, rack_id)

    # Compute occupancy
    front_occupied = set()
    rear_occupied = set()
    for d in devices:
        u_range = set(range(d['start_u'], d['start_u'] + d['u_height']))
        if d['position'] == 'front':
            front_occupied |= u_range
        else:
            rear_occupied |= u_range

    total_u = rack['total_u']
    # Compute power usage: sum power_watts from device_types of installed devices
    power_used = 0
    for d in devices:
        power_used += int(d.get('power_watts') or 0)
    power_capacity = int(rack.get('power_capacity_watts') or 0)

    return {
        **rack,
        'devices': devices,
        'front_used': len(front_occupied),
        'rear_used': len(rear_occupied),
        'total_used': len(front_occupied | rear_occupied),
        'available_u': total_u - len(front_occupied | rear_occupied),
        'power_used_watts': power_used,
        'power_capacity_watts': power_capacity,
        'power_utilization_pct': round(power_used / power_capacity * 100, 1) if power_capacity > 0 else None,
    }


def get_rack_stats(conn) -> dict:
    """Return aggregated rack statistics."""
    racks = list_racks(conn)
    total_racks = len(racks)
    total_u = sum(r['total_u'] for r in racks)
    total_power_capacity = sum(int(r.get('power_capacity_watts') or 0) for r in racks)
    device_rows = conn.execute(
        """
        SELECT rd.rack_id, rd.start_u, dt.u_height, dt.power_watts
        FROM rack_devices rd
        JOIN device_types dt ON dt.id = rd.device_type_id
        """
    ).fetchall()
    devices_by_rack: dict[str, list] = {}
    for row in device_rows:
        devices_by_rack.setdefault(str(row['rack_id']), []).append(row)

    total_devices = len(device_rows)
    total_used_u = 0
    total_power_used = 0
    for r in racks:
        occupied = set()
        for d in devices_by_rack.get(str(r['id']), []):
            occupied |= set(range(d['start_u'], d['start_u'] + d['u_height']))
            total_power_used += int(d['power_watts'] or 0)
        total_used_u += len(occupied)

    return {
        'total_racks': total_racks,
        'total_devices': total_devices,
        'total_u': total_u,
        'used_u': total_used_u,
        'utilization': round(total_used_u / total_u * 100, 1) if total_u > 0 else 0,
        'total_power_capacity_watts': total_power_capacity,
        'total_power_used_watts': total_power_used,
        'power_utilization_pct': round(total_power_used / total_power_capacity * 100, 1) if total_power_capacity > 0 else None,
    }
