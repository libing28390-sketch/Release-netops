"""
rack_service.py — 机柜管理服务层

Provides CRUD for racks, device types, and rack devices.
Enforces U-position constraints: no overlap, within rack bounds, start_u >= 1.
"""

import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal

from services import rack_asset_resolver
from services import rack_placement_service

logger = logging.getLogger(__name__)


_RACK_OFFLINE_STATES = frozenset({'offline', 'unreachable', 'down', 'inactive'})
_RACK_HEALTHY_STATES = frozenset({'online', 'active', 'healthy', 'up'})


def _normalize_asset_id(asset_id: object) -> str:
    return str(asset_id or '').strip()


def _derive_rack_health(
    *,
    device_count: int,
    monitored_device_count: int,
    healthy_device_count: int,
    offline_device_count: int,
    unknown_monitoring_device_count: int,
    invalid_device_count: int,
) -> tuple[str, str]:
    """Derive a conservative rack health/data-quality state.

    A monitoring row is not proof of health: its status must be a recognized
    healthy state. Unknown or missing status therefore remains unknown/partial
    instead of being silently promoted to healthy.
    """
    if device_count == 0:
        return 'empty', 'empty'
    if offline_device_count > 0:
        health_status = 'offline'
    elif monitored_device_count == device_count and healthy_device_count == device_count:
        health_status = 'healthy'
    elif healthy_device_count > 0:
        health_status = 'partial'
    else:
        health_status = 'unknown'

    data_quality_status = 'invalid' if invalid_device_count else (
        'complete'
        if monitored_device_count == device_count and unknown_monitoring_device_count == 0
        else 'partial'
    )
    return health_status, data_quality_status


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        values = {k: row[k] for k in row.keys()}
    else:
        values = dict(row)
    # PostgreSQL returns NUMERIC/DECIMAL columns as Decimal instances.  Rack
    # service responses are JSON-facing read models, so expose the same
    # numeric contract as the SQLite-era API and avoid leaking driver types.
    return {
        key: float(value) if isinstance(value, Decimal) else value
        for key, value in values.items()
    }


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
                     allow_front_rear_mount: bool = True, mount_policy: str = 'front_rear',
                     description: str = '') -> dict:
    mount_policy = str(mount_policy or '').strip().lower()
    if mount_policy not in {'front_only', 'front_rear', 'full_depth'}:
        raise ValueError("mount_policy must be one of 'front_only', 'front_rear', or 'full_depth'")
    if mount_policy == 'front_only':
        allow_front_rear_mount = False
    rack_type_id = str(uuid.uuid4())
    now = _utc_now()
    conn.execute(
        """INSERT INTO rack_types (
            id, name, vendor, model, total_u, width_mm, depth_mm, max_weight_kg,
            power_capacity_watts, allow_front_rear_mount, mount_policy, description,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rack_type_id, name.strip(), vendor, model, total_u, width_mm, depth_mm,
            max_weight_kg, power_capacity_watts, 1 if allow_front_rear_mount else 0,
            mount_policy, description, now, now,
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
        'max_weight_kg', 'power_capacity_watts', 'allow_front_rear_mount', 'mount_policy', 'description'
    ):
        if key in fields and fields[key] is not None:
            val = fields[key]
            if key == 'allow_front_rear_mount':
                val = 1 if val else 0
            elif key == 'mount_policy':
                val = str(val or '').strip().lower()
                if val not in {'front_only', 'front_rear', 'full_depth'}:
                    raise ValueError("mount_policy must be one of 'front_only', 'front_rear', or 'full_depth'")
                if val == 'front_only':
                    updates.append("allow_front_rear_mount = ?")
                    params.append(0)
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

def list_racks(
    conn,
    site_id: str = '',
    datacenter: str = '',
    *,
    tenant_id: str | None = None,
    allowed_site_ids: tuple[str, ...] | None = None,
) -> list[dict]:
    query = """SELECT r.*, s.site_code, s.site_name, s.tenant_id AS site_tenant_id
               FROM racks r LEFT JOIN sites s ON s.id = r.site_id"""
    filters: list[str] = []
    params: list[object] = []
    if site_id:
        filters.append("r.site_id = ?")
        params.append(site_id)
    elif datacenter:
        filters.append("(r.datacenter = ? OR s.site_code = ? OR s.site_name = ?)")
        params.extend((datacenter, datacenter, datacenter))
    if tenant_id is not None:
        filters.append("COALESCE(s.tenant_id, 'tenant-default') = ?")
        params.append(tenant_id)
    if allowed_site_ids is not None:
        if not allowed_site_ids:
            return []
        placeholders = ','.join('?' for _ in allowed_site_ids)
        filters.append(f"r.site_id IN ({placeholders})")
        params.extend(allowed_site_ids)
    where_sql = f" WHERE {' AND '.join(filters)}" if filters else ''
    order_sql = " ORDER BY r.name" if site_id or datacenter else " ORDER BY s.site_code, r.name"
    rows = conn.execute(query + where_sql + order_sql, tuple(params)).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_rack_summaries(
    conn,
    *,
    page: int = 1,
    page_size: int = 50,
    keyword: str = '',
    site_id: str = '',
    floor: str = '',
    room: str = '',
    row: str = '',
    status: str = '',
    health: str = '',
    tenant_id: str | None = None,
    allowed_site_ids: tuple[str, ...] | None = None,
) -> dict:
    """Return a paged rack read model without loading full layouts.

    The page query only returns rack metadata. Device occupancy, power and
    monitoring coverage are calculated from two bounded batch queries for the
    selected page, avoiding both N+1 layout requests and invented health data.
    """
    page = max(1, int(page))
    page_size = min(500, max(1, int(page_size)))
    filters: list[str] = []
    params: list[object] = []

    if site_id:
        filters.append("r.site_id = ?")
        params.append(site_id)
    if tenant_id is not None:
        filters.append("COALESCE(s.tenant_id, 'tenant-default') = ?")
        params.append(tenant_id)
    if allowed_site_ids is not None:
        if not allowed_site_ids:
            return {'items': [], 'total': 0, 'page': page, 'page_size': page_size}
        placeholders = ','.join('?' for _ in allowed_site_ids)
        filters.append(f"r.site_id IN ({placeholders})")
        params.extend(allowed_site_ids)
    if floor:
        filters.append("r.floor = ?")
        params.append(floor)
    if room:
        filters.append("r.room = ?")
        params.append(room)
    if row:
        filters.append("r.row = ?")
        params.append(row)
    if status:
        filters.append("r.status = ?")
        params.append(status)
    if health:
        offline_condition = "LOWER(COALESCE(d_health.status, '')) IN (" + ','.join(
            f"'{state}'" for state in sorted(_RACK_OFFLINE_STATES)
        ) + ")"
        healthy_condition = "LOWER(COALESCE(d_health.status, '')) IN (" + ','.join(
            f"'{state}'" for state in sorted(_RACK_HEALTHY_STATES)
        ) + ")"
        rack_devices_exist = "EXISTS (SELECT 1 FROM rack_devices rd_health WHERE rd_health.rack_id = r.id)"
        healthy_exist = f"""EXISTS (
            SELECT 1 FROM rack_devices rd_health
            JOIN devices d_health ON d_health.asset_id = rd_health.asset_id
            WHERE rd_health.rack_id = r.id AND {healthy_condition}
        )"""
        offline_exist = f"""EXISTS (
            SELECT 1 FROM rack_devices rd_health
            JOIN devices d_health ON d_health.asset_id = rd_health.asset_id
            WHERE rd_health.rack_id = r.id AND {offline_condition}
        )"""
        unmonitored_exist = """EXISTS (
            SELECT 1 FROM rack_devices rd_health
            LEFT JOIN devices d_health ON d_health.asset_id = rd_health.asset_id
            WHERE rd_health.rack_id = r.id AND d_health.id IS NULL
        )"""
        unknown_monitoring_exist = f"""EXISTS (
            SELECT 1 FROM rack_devices rd_health
            JOIN devices d_health ON d_health.asset_id = rd_health.asset_id
            WHERE rd_health.rack_id = r.id
              AND NOT ({healthy_condition})
              AND NOT ({offline_condition})
        )"""
        if health == 'offline':
            filters.append(offline_exist)
        elif health == 'healthy':
            filters.extend((rack_devices_exist, f"NOT ({offline_exist})", f"NOT ({unmonitored_exist})", f"NOT ({unknown_monitoring_exist})"))
        elif health == 'partial':
            filters.extend((rack_devices_exist, f"NOT ({offline_exist})", healthy_exist, f"({unmonitored_exist} OR {unknown_monitoring_exist})"))
        elif health == 'unknown':
            filters.extend((rack_devices_exist, f"NOT ({offline_exist})", f"NOT ({healthy_exist})"))
        elif health == 'empty':
            filters.append(f"NOT ({rack_devices_exist})")
    if keyword.strip():
        pattern = f"%{keyword.strip().lower()}%"
        filters.append(
            """(
                LOWER(COALESCE(r.name, '')) LIKE ? OR
                LOWER(COALESCE(r.rack_code, '')) LIKE ? OR
                LOWER(COALESCE(r.floor, '')) LIKE ? OR
                LOWER(COALESCE(r.room, '')) LIKE ? OR
                LOWER(COALESCE(r.row, '')) LIKE ? OR
                LOWER(COALESCE(s.site_code, '')) LIKE ? OR
                LOWER(COALESCE(s.site_name, '')) LIKE ? OR
                EXISTS (
                    SELECT 1 FROM rack_devices rd_search
                    LEFT JOIN device_types dt_search ON dt_search.id = rd_search.device_type_id
                    WHERE rd_search.rack_id = r.id AND (
                        LOWER(COALESCE(rd_search.name, '')) LIKE ? OR
                        LOWER(COALESCE(rd_search.serial_number, '')) LIKE ? OR
                        LOWER(COALESCE(rd_search.asset_id, '')) LIKE ? OR
                        LOWER(COALESCE(dt_search.vendor, '')) LIKE ? OR
                        LOWER(COALESCE(dt_search.model, '')) LIKE ?
                    )
                )
            )"""
        )
        params.extend([pattern] * 12)

    where_sql = f" WHERE {' AND '.join(filters)}" if filters else ''
    count_row = conn.execute(
        f"""SELECT COUNT(*) AS total
            FROM racks r LEFT JOIN sites s ON s.id = r.site_id
            {where_sql}""",
        tuple(params),
    ).fetchone()
    total = int(count_row['total'] if hasattr(count_row, 'keys') else count_row[0])
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"""SELECT
                r.id, r.name, r.rack_name, r.rack_code, r.site_id,
                s.site_code, s.site_name, r.datacenter, r.floor, r.room, r.row,
                r.room_name, r.row_name, r.total_u, r.status,
                r.power_capacity_w, r.power_capacity_watts,
                r.max_weight_kg, r.cooling_zone, r.remarks, r.description,
                r.placement_strategy, r.rack_type_id, r.width_mm, r.depth_mm,
                r.allow_front_rear_mount, r.mount_policy, r.layout_revision,
                r.created_at, r.updated_at
            FROM racks r LEFT JOIN sites s ON s.id = r.site_id
            {where_sql}
            ORDER BY COALESCE(s.site_code, ''), COALESCE(r.floor, ''),
                     COALESCE(r.room, ''), COALESCE(r.row, ''), r.name
            LIMIT ? OFFSET ?""",
        tuple([*params, page_size, offset]),
    ).fetchall()
    rack_items = [_row_to_dict(item) for item in rows]
    if not rack_items:
        return {'items': [], 'total': total, 'page': page, 'page_size': page_size}

    rack_ids = [str(item['id']) for item in rack_items]
    placeholders = ','.join('?' for _ in rack_ids)
    device_rows = conn.execute(
        f"""SELECT rd.id, rd.rack_id, rd.asset_id, rd.start_u, rd.position,
                   rd.mount_kind, rd.height_u, rd.placement_status,
                   rd.location_note, rd.status, dt.u_height, dt.power_watts
            FROM rack_devices rd
            JOIN device_types dt ON dt.id = rd.device_type_id
            WHERE rd.rack_id IN ({placeholders})
            ORDER BY rd.rack_id,
                     CASE WHEN rd.start_u IS NULL THEN 1 ELSE 0 END,
                     rd.start_u""",
        tuple(rack_ids),
    ).fetchall()
    devices_by_rack: dict[str, list[dict]] = {rack_id: [] for rack_id in rack_ids}
    asset_ids: set[str] = set()
    for row_item in device_rows:
        device = _row_to_dict(row_item)
        devices_by_rack.setdefault(str(device['rack_id']), []).append(device)
        asset_id_value = str(device.get('asset_id') or '').strip()
        if asset_id_value:
            asset_ids.add(asset_id_value)

    monitoring_by_asset: dict[str, list[str]] = {}
    if asset_ids:
        asset_placeholders = ','.join('?' for _ in asset_ids)
        monitoring_rows = conn.execute(
            f"""SELECT asset_id, status FROM devices
                WHERE asset_id IN ({asset_placeholders})""",
            tuple(sorted(asset_ids)),
        ).fetchall()
        for monitoring_row in monitoring_rows:
            monitoring = _row_to_dict(monitoring_row)
            asset_key = str(monitoring.get('asset_id') or '').strip()
            if asset_key:
                monitoring_by_asset.setdefault(asset_key, []).append(
                    str(monitoring.get('status') or '').lower()
                )

    offline_states = _RACK_OFFLINE_STATES
    healthy_states = _RACK_HEALTHY_STATES
    summaries = []
    for rack in rack_items:
        devices = devices_by_rack.get(str(rack['id']), [])
        front_occupied: set[int] = set()
        rear_occupied: set[int] = set()
        invalid_device_count = 0
        power_used_watts = 0
        monitored_device_count = 0
        offline_device_count = 0
        healthy_device_count = 0
        unknown_monitoring_device_count = 0
        unlinked_asset_count = 0
        non_u_device_count = 0
        unknown_placement_device_count = 0

        for device in devices:
            mount_kind = str(device.get('mount_kind') or 'u_mount').strip().lower()
            position = str(device.get('position') or 'unknown').strip().lower()
            if mount_kind == 'u_mount':
                try:
                    start_u = int(device.get('start_u')) if device.get('start_u') is not None else 0
                    height_u = int(device.get('height_u') or device.get('u_height') or 0)
                except (TypeError, ValueError):
                    start_u, height_u = 0, 0
                end_u = start_u + height_u - 1
                if start_u < 1 or height_u < 1 or end_u > int(rack.get('total_u') or 0) or position not in {'front', 'rear', 'full_depth'}:
                    invalid_device_count += 1
                else:
                    occupied_range = range(start_u, end_u + 1)
                    if position in {'front', 'full_depth'}:
                        front_occupied.update(occupied_range)
                    if position in {'rear', 'full_depth'}:
                        rear_occupied.update(occupied_range)
            elif mount_kind in {'zero_u', 'side_mount', 'floor'}:
                non_u_device_count += 1
                if mount_kind == 'side_mount' and position not in {'left_side', 'right_side'}:
                    invalid_device_count += 1
                elif mount_kind == 'zero_u' and position not in {'rear', 'left_side', 'right_side', 'unknown'}:
                    invalid_device_count += 1
                elif mount_kind == 'floor' and not str(device.get('location_note') or '').strip():
                    invalid_device_count += 1
            else:
                non_u_device_count += 1
                unknown_placement_device_count += 1
            power_used_watts += int(device.get('power_watts') or 0)

            asset_id_value = _normalize_asset_id(device.get('asset_id'))
            if not asset_id_value:
                unlinked_asset_count += 1
                continue
            monitoring_states = monitoring_by_asset.get(asset_id_value, [])
            if monitoring_states:
                monitored_device_count += 1
                if any(state in offline_states for state in monitoring_states):
                    offline_device_count += 1
                elif any(state in healthy_states for state in monitoring_states):
                    healthy_device_count += 1
                else:
                    unknown_monitoring_device_count += 1

        occupied = front_occupied | rear_occupied
        total_u = int(rack.get('total_u') or 0)
        capacity_watts = int(rack.get('power_capacity_watts') or rack.get('power_capacity_w') or 0)
        device_count = len(devices)
        unmonitored_device_count = device_count - monitored_device_count
        health_status, data_quality_status = _derive_rack_health(
            device_count=device_count,
            monitored_device_count=monitored_device_count,
            healthy_device_count=healthy_device_count,
            offline_device_count=offline_device_count,
            unknown_monitoring_device_count=unknown_monitoring_device_count,
            invalid_device_count=invalid_device_count,
        )

        summaries.append({
            **rack,
            'site_label': rack.get('site_name') or rack.get('site_code') or rack.get('datacenter') or rack.get('site_id') or '',
            'device_count': device_count,
            'front_used': len(front_occupied),
            'rear_used': len(rear_occupied),
            'used_u': len(occupied),
            'available_u': max(0, total_u - len(occupied)),
            'u_utilization_pct': round(len(occupied) / total_u * 100, 1) if total_u > 0 else None,
            'power_used_watts': power_used_watts,
            'power_utilization_pct': round(power_used_watts / capacity_watts * 100, 1) if capacity_watts > 0 else None,
            'monitored_device_count': monitored_device_count,
            'healthy_device_count': healthy_device_count,
            'offline_device_count': offline_device_count,
            'unknown_monitoring_device_count': unknown_monitoring_device_count,
            'unlinked_asset_count': unlinked_asset_count,
            'unmonitored_device_count': unmonitored_device_count,
            'non_u_device_count': non_u_device_count,
            'unknown_placement_device_count': unknown_placement_device_count,
            'invalid_device_count': invalid_device_count,
            'health_status': health_status,
            'data_quality_status': data_quality_status,
        })

    return {'items': summaries, 'total': total, 'page': page, 'page_size': page_size}


def get_rack(conn, rack_id: str) -> dict:
    row = conn.execute(
        """SELECT r.*, s.site_code, s.site_name,
                  s.tenant_id AS site_tenant_id
             FROM racks r LEFT JOIN sites s ON s.id = r.site_id
            WHERE r.id = ?""",
        (rack_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Rack not found: {rack_id}")
    return _row_to_dict(row)


def resolve_rack_reference(conn, reference: str) -> dict | None:
    """Resolve a rack by stable ID/code or by a legacy display name.

    IDs and rack codes are authoritative.  Legacy asset forms may still send
    ``name``/``rack_name``; when that value is shared by more than one rack,
    returning an arbitrary ``LIMIT 1`` row would move an asset silently, so
    expose a stable 409 domain failure instead.
    """

    normalized = str(reference or '').strip()
    if not normalized:
        return None

    for column in ('id', 'rack_code'):
        row = conn.execute(
            f"""SELECT r.*, s.site_code, s.site_name,
                              s.tenant_id AS site_tenant_id
                   FROM racks r LEFT JOIN sites s ON s.id = r.site_id
                  WHERE r.{column} = ?
                  LIMIT 1""",
            (normalized,),
        ).fetchone()
        if row:
            return _row_to_dict(row)

    rows = conn.execute(
        """SELECT r.*, s.site_code, s.site_name,
                         s.tenant_id AS site_tenant_id
                  FROM racks r LEFT JOIN sites s ON s.id = r.site_id
                 WHERE r.name = ? OR r.rack_name = ?
                 ORDER BY r.id""",
        (normalized, normalized),
    ).fetchall()
    unique_rows: dict[str, dict] = {}
    for row in rows:
        item = _row_to_dict(row)
        unique_rows[str(item.get('id') or '')] = item
    if len(unique_rows) > 1:
        raise rack_placement_service.RackPlacementError(
            'RACK_NOT_UNIQUE',
            'Rack name matches more than one rack; use rack_id or rack_code',
            status_code=409,
            details={
                'reference': normalized,
                'rack_ids': sorted(unique_rows),
            },
        )
    return next(iter(unique_rows.values()), None)


def create_rack(conn, *, name: str, datacenter: str = '', floor: str = '', room: str = '',
                row: str = '', total_u: int = 42, description: str = '',
                status: str = 'active', power_capacity_watts: int | None = None,
                site_id: str = 'site-default', rack_code: str = '',
                placement_strategy: str = 'bottom_first', rack_type_id: str = '',
                width_mm: int = 600, depth_mm: int = 1000,
                allow_front_rear_mount: bool | None = True, mount_policy: str | None = None,
                commit: bool = True, **kwargs) -> dict:
    rack_id = str(uuid.uuid4())
    if not rack_code:
        rack_code = f"RACK_{uuid.uuid4().hex[:12].upper()}"

    # Give callers a stable domain conflict before PostgreSQL's unique
    # constraint raises a driver-specific IntegrityError.  This is important
    # for atomic batch creation, where a duplicate row must be reported as a
    # validation/conflict response rather than an opaque 500.
    existing_code = conn.execute(
        "SELECT id FROM racks WHERE rack_code = ? LIMIT 1",
        (rack_code,),
    ).fetchone()
    if existing_code:
        raise rack_placement_service.RackPlacementError(
            "RACK_CODE_CONFLICT",
            "Rack code already exists",
            status_code=409,
            details={"rack_code": rack_code, "existing_rack_id": existing_code["id"]},
        )

    legacy_power_capacity = kwargs.get('power_capacity_w')
    if power_capacity_watts is not None and legacy_power_capacity is not None:
        try:
            canonical_power = int(power_capacity_watts)
            legacy_power = int(legacy_power_capacity)
        except (TypeError, ValueError) as exc:
            raise ValueError("power capacity fields must be integers") from exc
        if canonical_power != legacy_power:
            raise rack_placement_service.RackPlacementError(
                "POWER_FIELD_CONFLICT",
                "power_capacity_watts and power_capacity_w must have the same value",
                status_code=422,
                details={
                    "power_capacity_watts": canonical_power,
                    "power_capacity_w": legacy_power,
                },
            )
    elif power_capacity_watts is None:
        power_capacity_watts = legacy_power_capacity if legacy_power_capacity is not None else 5000
    if power_capacity_watts is not None and int(power_capacity_watts) < 0:
        raise ValueError("power capacity must be >= 0")

    site_id, site_code, _site_name = _resolve_site(conn, site_id, datacenter)

    rack_type = None
    if rack_type_id:
        rack_type = get_rack_type(conn, rack_type_id)
        total_u = kwargs.get('total_u') or total_u or rack_type.get('total_u') or 42
        width_mm = kwargs.get('width_mm') or width_mm or rack_type.get('width_mm') or 600
        depth_mm = kwargs.get('depth_mm') or depth_mm or rack_type.get('depth_mm') or 1000
        if not power_capacity_watts:
            power_capacity_watts = int(rack_type.get('power_capacity_watts') or 0)
        if kwargs.get('max_weight_kg') is None:
            kwargs['max_weight_kg'] = rack_type.get('max_weight_kg')
        if allow_front_rear_mount is None:
            allow_front_rear_mount = bool(rack_type.get('allow_front_rear_mount'))

    if mount_policy is None:
        if rack_type and rack_type.get('mount_policy'):
            mount_policy = str(rack_type['mount_policy']).strip().lower()
        else:
            mount_policy = 'front_rear' if allow_front_rear_mount is not False else 'front_only'
    mount_policy = str(mount_policy).strip().lower()
    if mount_policy not in {'front_only', 'front_rear', 'full_depth'}:
        raise ValueError("mount_policy must be one of 'front_only', 'front_rear', or 'full_depth'")
    if mount_policy == 'front_only':
        allow_front_rear_mount = False
    elif allow_front_rear_mount is None:
        allow_front_rear_mount = True
    
    # Synchronize old and new fields
    rack_name = kwargs.get('rack_name') or name
    room_name = kwargs.get('room_name') or room
    row_name = kwargs.get('row_name') or row
    remarks = kwargs.get('remarks') or description
    power_capacity_w = int(power_capacity_watts or 0)
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
            placement_strategy, rack_type_id, width_mm, depth_mm, allow_front_rear_mount,
            mount_policy, layout_revision, created_at, updated_at
           )
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rack_id, site_id, rack_code, rack_name, name, site_code, floor, room, row, room_name, row_name,
            total_u, used_u, available_u, power_capacity_w, power_capacity_watts, status, remarks, description,
            current_power_w, power_utilization, max_weight_kg, current_weight_kg, cooling_zone,
            placement_strategy, rack_type_id, width_mm, depth_mm, 1 if allow_front_rear_mount else 0,
            mount_policy, 1, now, now
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

    canonical_power = fields.get('power_capacity_watts')
    legacy_power = fields.get('power_capacity_w')
    if canonical_power is not None or legacy_power is not None:
        if canonical_power is not None and legacy_power is not None:
            try:
                canonical_power = int(canonical_power)
                legacy_power = int(legacy_power)
            except (TypeError, ValueError) as exc:
                raise ValueError("power capacity fields must be integers") from exc
            if canonical_power != legacy_power:
                raise rack_placement_service.RackPlacementError(
                    "POWER_FIELD_CONFLICT",
                    "power_capacity_watts and power_capacity_w must have the same value",
                    status_code=422,
                    details={
                        "power_capacity_watts": canonical_power,
                        "power_capacity_w": legacy_power,
                    },
                )
        else:
            effective_power = canonical_power if canonical_power is not None else legacy_power
            fields['power_capacity_watts'] = effective_power
            fields['power_capacity_w'] = effective_power
        if int(fields['power_capacity_watts']) < 0:
            raise ValueError("power capacity must be >= 0")

    if 'total_u' in fields and fields['total_u'] is not None:
        try:
            requested_total_u = int(fields['total_u'])
        except (TypeError, ValueError) as exc:
            raise ValueError("total_u must be an integer") from exc
        if requested_total_u < 1:
            raise ValueError("total_u must be >= 1")
        current_total_u = int(existing.get('total_u') or 0)
        if requested_total_u < current_total_u:
            affected: list[dict] = []
            rows = conn.execute(
                """SELECT rd.id, rd.name, rd.start_u, rd.height_u,
                          rd.mount_kind, dt.u_height
                     FROM rack_devices rd
                     JOIN device_types dt ON dt.id = rd.device_type_id
                    WHERE rd.rack_id = ?""",
                (rack_id,),
            ).fetchall()
            for raw in rows:
                device = _row_to_dict(raw)
                if str(device.get('mount_kind') or 'u_mount').strip().lower() != 'u_mount':
                    continue
                try:
                    start_u = int(device.get('start_u'))
                    height_u = int(device.get('height_u') or device.get('u_height') or 0)
                except (TypeError, ValueError):
                    affected.append({"id": device.get('id'), "name": device.get('name'), "reason": "invalid U geometry"})
                    continue
                end_u = start_u + height_u - 1
                if start_u < 1 or height_u < 1 or end_u > requested_total_u:
                    affected.append({
                        "id": device.get('id'),
                        "name": device.get('name') or device.get('id'),
                        "start_u": start_u,
                        "end_u": end_u,
                    })
            if affected:
                raise rack_placement_service.RackPlacementError(
                    "RACK_RESIZE_CONFLICT",
                    "Cannot reduce rack height while installed U placements would be out of bounds",
                    status_code=409,
                    details={"rack_id": rack_id, "requested_total_u": requested_total_u, "placements": affected},
                )

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
        'allow_front_rear_mount', 'mount_policy'
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
            elif key == 'mount_policy':
                fields[key] = str(fields[key] or '').strip().lower()
                if fields[key] not in {'front_only', 'front_rear', 'full_depth'}:
                    raise ValueError("mount_policy must be one of 'front_only', 'front_rear', or 'full_depth'")
                if fields[key] == 'front_only' and 'allow_front_rear_mount' not in fields:
                    updates.append("allow_front_rear_mount = ?")
                    params.append(0)
            updates.append(f"{key} = ?")
            params.append(fields[key])
            
    if not updates:
        return existing
        
    layout_fields = {
        'total_u', 'width_mm', 'depth_mm', 'allow_front_rear_mount',
        'mount_policy', 'rack_type_id',
    }
    if any(key in fields for key in layout_fields):
        updates.append("layout_revision = COALESCE(layout_revision, 0) + 1")
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
                       description: str = '', power_watts: int = 0,
                       depth_class: str = 'unknown', width_mm: int | None = None,
                       depth_mm: int | None = None, height_mm: int | None = None,
                       weight_kg: float | None = None, dimension_status: str = 'unknown',
                       default_mount_kind: str = 'u_mount', model_family: str = '',
                       catalog_key: str = '') -> dict:
    depth_class = str(depth_class or 'unknown').strip().lower()
    dimension_status = str(dimension_status or 'unknown').strip().lower()
    default_mount_kind = str(default_mount_kind or 'u_mount').strip().lower()
    if depth_class not in {'half', 'full', 'unknown'}:
        raise ValueError("depth_class must be one of 'half', 'full', or 'unknown'")
    if dimension_status not in rack_placement_service.DIMENSION_STATUSES:
        raise ValueError(f"dimension_status must be one of {sorted(rack_placement_service.DIMENSION_STATUSES)}")
    if default_mount_kind not in rack_placement_service.MOUNT_KINDS:
        raise ValueError(f"default_mount_kind must be one of {sorted(rack_placement_service.MOUNT_KINDS)}")
    dt_id = str(uuid.uuid4())
    now = _utc_now()
    conn.execute(
        """INSERT INTO device_types (
               id, model, vendor, u_height, device_role, is_full_depth, description, power_watts,
               depth_class, width_mm, depth_mm, height_mm, weight_kg, dimension_status,
               default_mount_kind, model_family, catalog_key, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            dt_id, model, vendor, u_height, device_role, 1 if is_full_depth else 0,
            description, power_watts, depth_class, width_mm, depth_mm, height_mm,
            weight_kg, dimension_status, default_mount_kind, model_family, catalog_key, now, now,
        )
    )
    conn.commit()
    logger.info(f"[RackService] Created device type '{vendor} {model}' ({u_height}U, {power_watts}W)")
    return get_device_type(conn, dt_id)


def update_device_type(conn, dt_id: str, **fields) -> dict:
    existing = get_device_type(conn, dt_id)
    updates = []
    params = []
    supported_keys = (
        'model', 'vendor', 'u_height', 'device_role', 'is_full_depth', 'description', 'power_watts',
        'depth_class', 'width_mm', 'depth_mm', 'height_mm', 'weight_kg', 'dimension_status',
        'default_mount_kind', 'model_family', 'catalog_key',
    )

    if 'u_height' in fields and fields['u_height'] is not None:
        try:
            requested_height = int(fields['u_height'])
        except (TypeError, ValueError) as exc:
            raise ValueError("u_height must be an integer") from exc
        if requested_height < 0:
            raise ValueError("u_height must be >= 0")
        current_height = int(existing.get('u_height') or 0)
        if requested_height != current_height:
            affected: list[dict] = []
            rows = conn.execute(
                """SELECT rd.id, rd.name, rd.rack_id, rd.start_u,
                          rd.position, rd.mount_kind, rd.height_u,
                          rd.placement_status, rd.placement_source,
                          rd.dimension_status, rd.location_note,
                          rd.asset_id
                     FROM rack_devices rd
                    WHERE rd.device_type_id = ?""",
                (dt_id,),
            ).fetchall()
            for raw in rows:
                placement = _row_to_dict(raw)
                if str(placement.get('mount_kind') or 'u_mount').strip().lower() != 'u_mount':
                    continue
                # An explicit placement height is an operator override and is
                # not changed by a template edit.  Only inherited rows need
                # to be checked against the new device-type height.
                if (
                    placement.get('height_u') not in (None, '')
                    and str(placement.get('placement_status') or '').strip().lower() != 'estimated'
                ):
                    continue
                result = rack_placement_service.validate(
                    conn,
                    rack_id=str(placement.get('rack_id') or ''),
                    device_type_id=dt_id,
                    start_u=placement.get('start_u'),
                    position=placement.get('position'),
                    mount_kind=placement.get('mount_kind'),
                    height_u=requested_height,
                    asset_id=placement.get('asset_id') or '',
                    exclude_device_id=placement.get('id') or '',
                    location_note=placement.get('location_note') or '',
                    placement_status=placement.get('placement_status'),
                    placement_source=placement.get('placement_source'),
                    dimension_status=placement.get('dimension_status'),
                    check_asset=False,
                )
                if not result.get('valid'):
                    affected.append({
                        "id": placement.get('id'),
                        "name": placement.get('name') or placement.get('id'),
                        "rack_id": placement.get('rack_id'),
                        "errors": result.get('errors') or [],
                    })
            if affected:
                raise rack_placement_service.RackPlacementError(
                    "DEVICE_TYPE_UPDATE_CONFLICT",
                    "Cannot change device type height while inherited rack placements would become invalid",
                    status_code=409,
                    details={"device_type_id": dt_id, "requested_u_height": requested_height, "placements": affected},
                )
        fields['u_height'] = requested_height
    for key in supported_keys:
        if key in fields and fields[key] is not None:
            val = fields[key]
            if key == 'is_full_depth':
                val = 1 if val else 0
            elif key == 'depth_class':
                val = str(val or 'unknown').strip().lower()
                if val not in {'half', 'full', 'unknown'}:
                    raise ValueError("depth_class must be one of 'half', 'full', or 'unknown'")
            elif key == 'dimension_status':
                val = str(val or 'unknown').strip().lower()
                if val not in rack_placement_service.DIMENSION_STATUSES:
                    raise ValueError(f"dimension_status must be one of {sorted(rack_placement_service.DIMENSION_STATUSES)}")
            elif key == 'default_mount_kind':
                val = str(val or 'u_mount').strip().lower()
                if val not in rack_placement_service.MOUNT_KINDS:
                    raise ValueError(f"default_mount_kind must be one of {sorted(rack_placement_service.MOUNT_KINDS)}")
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
        raise rack_placement_service.RackPlacementError(
            "DEVICE_TYPE_IN_USE",
            "Cannot delete device type in use by rack devices.",
            status_code=409,
            details={"device_type_id": dt_id},
        )
    conn.execute("DELETE FROM device_types WHERE id = ?", (dt_id,))
    conn.commit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RackDevice CRUD + U-position constraint enforcement
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _check_u_constraints(conn, rack_id: str, start_u: int, u_height: int,
                         position: str, exclude_device_id: str = ''):
    """Compatibility wrapper around the canonical placement validator."""
    from database import _USE_PG

    if _USE_PG:
        # Preserve the legacy helper's explicit parent lock for callers that
        # still use it directly; the placement service also locks during a
        # real install/move transaction.
        conn.execute("SELECT 1 FROM racks WHERE id = ? FOR UPDATE", (rack_id,))

    result = rack_placement_service.validate(
        conn,
        rack_id=rack_id,
        device_type_id='',
        start_u=start_u,
        position=position,
        mount_kind='u_mount',
        height_u=u_height,
        exclude_device_id=exclude_device_id,
        check_asset=False,
    )
    if not result.get('valid'):
        raise ValueError('; '.join(result.get('errors') or ['invalid rack placement']))


def _check_asset_installation(conn, asset_id: str, exclude_device_id: str = '') -> None:
    """Compatibility wrapper around the canonical asset identity lock/check."""
    rack_placement_service.ensure_asset_available(
        conn,
        asset_id,
        exclude_device_id=exclude_device_id,
    )


def list_rack_devices(conn, rack_id: str) -> list[dict]:
    """Return all devices in a rack with device type info, sorted by start_u."""
    rows = conn.execute("""
        SELECT rd.*, dt.model, dt.vendor, dt.u_height, dt.device_role, dt.is_full_depth, dt.power_watts,
               dt.depth_class, dt.width_mm, dt.depth_mm, dt.height_mm, dt.weight_kg,
               dt.dimension_status AS type_dimension_status, dt.default_mount_kind,
               dt.model_family, dt.catalog_key,
               pa.asset_tag AS physical_asset_tag,
               pa.serial_number AS physical_serial_number,
               pa.hostname AS physical_hostname,
               (SELECT d.id FROM devices d
                 WHERE d.asset_id = rd.asset_id
                 ORDER BY d.id LIMIT 1) AS network_device_id,
               (SELECT d.hostname FROM devices d
                 WHERE d.asset_id = rd.asset_id
                 ORDER BY d.id LIMIT 1) AS network_hostname,
               (SELECT d.sn FROM devices d
                 WHERE d.asset_id = rd.asset_id
                 ORDER BY d.id LIMIT 1) AS network_sn
        FROM rack_devices rd
        JOIN device_types dt ON rd.device_type_id = dt.id
        LEFT JOIN physical_assets pa ON pa.id = rd.asset_id
        WHERE rd.rack_id = ?
        ORDER BY CASE WHEN rd.start_u IS NULL THEN 1 ELSE 0 END, rd.start_u ASC, rd.position ASC
    """, (rack_id,)).fetchall()
    devices: list[dict] = []
    for row in rows:
        device = _row_to_dict(row)
        visual = rack_asset_resolver.resolve_asset_for_device(device)
        device.update({
            'resolved_asset_key': visual['asset_key'],
            'asset_resolution_level': visual['resolution_level'],
            'asset_fidelity': visual['fidelity'],
            'asset_path': visual['glb_path'],
            'asset_url': visual.get('asset_url'),
            'asset_available': visual['available'],
            'asset_render_strategy': visual['render_strategy'],
        })
        devices.append(device)
    return devices


def get_rack_device(conn, device_id: str) -> dict:
    device = rack_placement_service.get_placement(conn, device_id)
    visual = rack_asset_resolver.resolve_asset_for_device(device)
    device.update({
        'resolved_asset_key': visual['asset_key'],
        'asset_resolution_level': visual['resolution_level'],
        'asset_fidelity': visual['fidelity'],
        'asset_path': visual['glb_path'],
        'asset_url': visual.get('asset_url'),
        'asset_available': visual['available'],
        'asset_render_strategy': visual['render_strategy'],
    })
    return device


def create_rack_device(conn, *, name: str, rack_id: str, device_type_id: str,
                       start_u: int | None = None, position: str = 'front', status: str = 'active',
                       serial_number: str = '', asset_id: str = '', mount_kind: str | None = None,
                       height_u: int | None = None, placement_status: str | None = None,
                       placement_source: str = 'manual', dimension_status: str | None = None,
                       location_note: str = '', model_key: str = '',
                       require_asset_record: bool = False, commit: bool = True) -> dict:
    return rack_placement_service.install(
        conn,
        name=name,
        rack_id=rack_id,
        device_type_id=device_type_id,
        start_u=start_u,
        position=position,
        mount_kind=mount_kind,
        height_u=height_u,
        placement_status=placement_status,
        placement_source=placement_source,
        dimension_status=dimension_status,
        location_note=location_note,
        model_key=model_key,
        status=status,
        serial_number=serial_number,
        asset_id=asset_id,
        require_asset_record=require_asset_record,
        commit=commit,
    )


def update_rack_device(conn, device_id: str, **fields) -> dict:
    commit = bool(fields.pop('commit', True))
    return rack_placement_service.update(conn, device_id, commit=commit, **fields)


def delete_rack_device(conn, device_id: str, *, commit: bool = True) -> None:
    rack_placement_service.uninstall(conn, device_id, commit=commit)
    logger.info(f"[RackService] Removed rack device {device_id}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Rack Layout — full visualization payload
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _placement_occupancy(device: dict, total_u: int) -> tuple[set[int], set[int], str, bool]:
    """Return front/rear occupancy plus placement class and validity.

    ``rack_devices`` is allowed to contain non-U rows.  Keeping this helper
    shared by layout and aggregate statistics prevents a 0U/side/floor row
    from being coerced into U1 and accidentally consuming cabinet capacity.
    """
    mount_kind = str(device.get('mount_kind') or 'u_mount').strip().lower()
    position = str(device.get('position') or 'unknown').strip().lower()
    if mount_kind != 'u_mount':
        if mount_kind == 'side_mount':
            valid = position in {'left_side', 'right_side'}
        elif mount_kind == 'zero_u':
            valid = position in {'rear', 'left_side', 'right_side', 'unknown'}
        elif mount_kind == 'floor':
            valid = bool(str(device.get('location_note') or '').strip())
        else:
            valid = mount_kind == 'unknown'
        return set(), set(), mount_kind, valid

    try:
        start_u = int(device.get('start_u')) if device.get('start_u') is not None else 0
        height_u = int(device.get('height_u') or device.get('u_height') or 0)
    except (TypeError, ValueError):
        return set(), set(), mount_kind, False
    end_u = start_u + height_u - 1
    if (
        start_u < 1 or height_u < 1 or end_u > int(total_u or 0)
        or position not in {'front', 'rear', 'full_depth'}
    ):
        return set(), set(), mount_kind, False
    occupied = set(range(start_u, end_u + 1))
    return (
        occupied if position in {'front', 'full_depth'} else set(),
        occupied if position in {'rear', 'full_depth'} else set(),
        mount_kind,
        True,
    )


def get_rack_layout(conn, rack_id: str) -> dict:
    """Return rack info + all devices for rendering a rack diagram."""
    rack = get_rack(conn, rack_id)
    devices = list_rack_devices(conn, rack_id)

    # Compute occupancy
    front_occupied = set()
    rear_occupied = set()
    non_u_device_count = 0
    unknown_placement_device_count = 0
    invalid_device_count = 0
    total_u = int(rack.get('total_u') or 0)
    for d in devices:
        front, rear, mount_kind, valid = _placement_occupancy(d, total_u)
        if mount_kind == 'u_mount':
            if valid:
                front_occupied |= front
                rear_occupied |= rear
            else:
                invalid_device_count += 1
        else:
            non_u_device_count += 1
            if mount_kind == 'unknown':
                unknown_placement_device_count += 1
            if not valid:
                invalid_device_count += 1

    # Compute power usage: sum power_watts from device_types of installed devices
    power_used = 0
    for d in devices:
        power_used += int(d.get('power_watts') or 0)
    power_capacity = int(rack.get('power_capacity_watts') or 0)

    return {
        **rack,
        'devices': devices,
        # Canonical aliases for new consumers.  ``devices`` and the flat
        # summary fields remain for the existing 2D page during the migration
        # window; 3D/exports can consume the explicit read-model sections.
        'placements': devices,
        'occupancy': {
            'front': sorted(front_occupied),
            'rear': sorted(rear_occupied),
            'used_u': len(front_occupied | rear_occupied),
            'available_u': max(0, total_u - len(front_occupied | rear_occupied)),
        },
        'data_quality': {
            'non_u_device_count': non_u_device_count,
            'unknown_placement_device_count': unknown_placement_device_count,
            'invalid_device_count': invalid_device_count,
            'status': 'invalid' if invalid_device_count else ('partial' if unknown_placement_device_count else 'complete'),
        },
        'meta': {
            'schema_version': 'rack-layout-v1',
            'layout_revision': int(rack.get('layout_revision') or 0),
            'generated_at': _utc_now(),
        },
        'front_used': len(front_occupied),
        'rear_used': len(rear_occupied),
        'total_used': len(front_occupied | rear_occupied),
        'available_u': total_u - len(front_occupied | rear_occupied),
        'power_used_watts': power_used,
        'power_capacity_watts': power_capacity,
        'power_utilization_pct': round(power_used / power_capacity * 100, 1) if power_capacity > 0 else None,
        'non_u_device_count': non_u_device_count,
        'unknown_placement_device_count': unknown_placement_device_count,
        'invalid_device_count': invalid_device_count,
    }


def get_rack_stats(
    conn,
    *,
    tenant_id: str | None = None,
    allowed_site_ids: tuple[str, ...] | None = None,
) -> dict:
    """Return aggregated rack statistics."""
    racks = list_racks(
        conn,
        tenant_id=tenant_id,
        allowed_site_ids=allowed_site_ids,
    )
    total_racks = len(racks)
    total_u = sum(r['total_u'] for r in racks)
    total_power_capacity = sum(int(r.get('power_capacity_watts') or 0) for r in racks)
    if not racks:
        device_rows = []
    else:
        rack_ids = [str(r['id']) for r in racks]
        placeholders = ','.join('?' for _ in rack_ids)
        device_rows = conn.execute(
            f"""
            SELECT rd.rack_id, rd.start_u, rd.position, rd.mount_kind, rd.height_u,
                   rd.location_note, dt.u_height, dt.power_watts
            FROM rack_devices rd
            JOIN device_types dt ON dt.id = rd.device_type_id
            WHERE rd.rack_id IN ({placeholders})
            """,
            tuple(rack_ids),
        ).fetchall()
    devices_by_rack: dict[str, list] = {}
    for row in device_rows:
        devices_by_rack.setdefault(str(row['rack_id']), []).append(row)

    total_devices = len(device_rows)
    total_used_u = 0
    total_power_used = 0
    total_non_u_devices = 0
    total_unknown_placements = 0
    total_invalid_placements = 0
    for r in racks:
        occupied = set()
        for d in devices_by_rack.get(str(r['id']), []):
            front, rear, mount_kind, valid = _placement_occupancy(_row_to_dict(d), int(r.get('total_u') or 0))
            if mount_kind != 'u_mount':
                total_non_u_devices += 1
                if mount_kind == 'unknown':
                    total_unknown_placements += 1
            if not valid:
                total_invalid_placements += 1
            occupied |= front | rear
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
        'total_non_u_devices': total_non_u_devices,
        'total_unknown_placements': total_unknown_placements,
        'total_invalid_placements': total_invalid_placements,
    }
