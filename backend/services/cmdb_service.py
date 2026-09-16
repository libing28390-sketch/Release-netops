"""
cmdb_service.py — CMDB core entity service layer.

CRUD for the foundational CMDB inventory tables that previously had no API:
  - tenants
  - sites
  - vrfs
  - vlans

Conventions mirror rack_service / credential_service: callers pass an open
connection, functions raise ValueError on validation/not-found, and commits
happen inside each mutating function.
"""

import uuid
import logging
import re
import ipaddress
from datetime import datetime, timezone
from core.interface_utils import normalize_interface_name

logger = logging.getLogger(__name__)

_DEFAULT_TENANT = 'tenant-default'


def _format_mac_address(value: object) -> str:
    """Render a MAC address in the CMDB operator format: 0000-1111-2222."""
    raw = str(value or '').strip()
    compact = re.sub(r'[^0-9a-fA-F]', '', raw)
    if len(compact) == 12:
        compact = compact.lower()
        return '-'.join(compact[index:index + 4] for index in range(0, 12, 4))
    return raw


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _count_reference(conn, table: str, column: str, value: str) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM {table} WHERE {column} = ?",
        (value,),
    ).fetchone()
    if row is None:
        return 0
    if hasattr(row, 'keys') and 'cnt' in row.keys():
        return int(row['cnt'] or 0)
    return int(row[0] or 0)


def _raise_if_referenced(conn, label: str, refs: list[tuple[str, str, str]]) -> None:
    blockers = []
    for table, column, value in refs:
        try:
            cnt = _count_reference(conn, table, column, value)
        except Exception:
            continue
        if cnt > 0:
            blockers.append(f"{table}.{column}={value} ({cnt})")
    if blockers:
        raise ValueError(f"Cannot delete {label}: still referenced by " + "; ".join(blockers))


def _distinct_interface_counts(conn) -> dict[str, int]:
    """Count one interface identity per device for CMDB device summaries.

    Interface collectors may receive different vendor spellings for the same
    physical/logical interface (for example ``GE1/0/1`` and
    ``GigabitEthernet1/0/1``).  ``list_cmdb_interfaces`` already collapses
    those aliases with :func:`normalize_interface_name`; the device summary
    must use the same identity rule instead of counting raw table rows.
    """
    try:
        rows = conn.execute(
            "SELECT device_id, interface_name FROM interfaces"
        ).fetchall()
    except Exception:
        return {}

    identities: dict[str, set[str]] = {}
    for row in rows:
        device_value = row['device_id'] if hasattr(row, 'keys') else row[0]
        name_value = row['interface_name'] if hasattr(row, 'keys') else row[1]
        device_id = str(device_value or '').strip()
        raw_name = str(name_value or '').strip()
        if not device_id or not raw_name:
            continue
        identity = normalize_interface_name(raw_name).lower() or raw_name.lower()
        identities.setdefault(device_id, set()).add(identity)
    return {device_id: len(names) for device_id, names in identities.items()}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CMDB Network Skeleton
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def list_cmdb_devices(conn) -> list[dict]:
    """Return devices as CMDB skeleton nodes with asset and relationship counts."""
    interface_counts = _distinct_interface_counts(conn)
    rows = conn.execute(
        """
        SELECT
            d.id,
            d.hostname,
            d.ip_address,
            d.platform,
            d.status,
            d.role,
            d.site,
            d.vendor,
            d.lifecycle_status,
            d.asset_id,
            pa.asset_tag,
            pa.serial_number,
            COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''), '') AS site_id,
            s.site_code,
            s.site_name,
            s.country AS site_country,
            s.state_province AS site_state_province,
            s.city AS site_city,
            s.district AS site_district,
            COALESCE(NULLIF(r.id, ''), NULLIF(r_legacy.id, ''), '') AS cmdb_rack_id,
            COALESCE(NULLIF(r.rack_code, ''), NULLIF(r_legacy.rack_code, ''), '') AS rack_code,
            COALESCE(NULLIF(r.rack_name, ''), NULLIF(r_legacy.rack_name, ''), NULLIF(r_legacy.name, ''), '') AS rack_name,
            COALESCE(NULLIF(r.floor, ''), NULLIF(r_legacy.floor, ''), '') AS rack_floor,
            COALESCE(NULLIF(r.room, ''), NULLIF(r_legacy.room, ''), '') AS rack_room,
            COALESCE(NULLIF(r.row, ''), NULLIF(r_legacy.row, ''), '') AS rack_row,
            pa.rack,
            pa.rack_unit,
            pa.management_ip,
            pa.business_ip,
            pa.lifecycle_status AS asset_lifecycle_status,
            0 AS interface_count,
            (
                SELECT COUNT(*)
                FROM ip_addresses ip
                WHERE ip.device_id = d.id
            ) AS ip_count,
            (
                SELECT COUNT(*)
                FROM topology_links tl
                WHERE tl.source_device_id = d.id OR tl.target_device_id = d.id
            ) AS link_count
        FROM devices d
        LEFT JOIN physical_assets pa ON pa.id = d.asset_id
        LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
        LEFT JOIN rack_devices rd ON rd.asset_id = pa.id
        LEFT JOIN racks r ON r.id = COALESCE(NULLIF(d.rack_id, ''), NULLIF(rd.rack_id, ''))
        LEFT JOIN racks r_legacy ON NULLIF(pa.rack, '') IS NOT NULL
            AND r_legacy.site_id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
            AND (r_legacy.rack_code = pa.rack OR r_legacy.rack_name = pa.rack OR r_legacy.name = pa.rack)
        ORDER BY COALESCE(d.hostname, ''), COALESCE(d.ip_address, '')
        """
    ).fetchall()
    items = []
    for row in rows:
        item = _row_to_dict(row)
        item['interface_count'] = interface_counts.get(str(item.get('id') or ''), 0)
        items.append(item)
    return items


def list_resource_search(
    conn,
    *,
    q: str = '',
    search_field: str = 'all',
    search_mode: str = 'fuzzy',
    site_id: str = '',
    asset_type: str = 'all',
    device_category: str = '',
    vendor: str = '',
    platform: str = '',
    status: str = 'all',
    lifecycle_status: str = 'all',
    tag_ids: list[str] | None = None,
    tag_match_all: bool = True,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Search all technical resources without duplicating the asset model.

    ``devices`` is the resource population; ``physical_assets`` contributes
    canonical asset fields when the device has an asset record. Search values
    are always parameterized and secrets are intentionally excluded.
    """
    interface_counts = _distinct_interface_counts(conn)
    q = (q or '').strip()
    search_field = search_field if search_field in {
        'all', 'hostname', 'asset_tag', 'serial_number', 'ip',
        'management_ip', 'business_ip', 'vendor', 'model', 'platform',
    } else 'all'
    search_mode = 'exact' if search_mode == 'exact' else 'fuzzy'

    hostname_expr = "COALESCE(NULLIF(pa.hostname, ''), NULLIF(d.hostname, ''), '')"
    asset_tag_expr = "COALESCE(NULLIF(pa.asset_tag, ''), '')"
    serial_expr = "COALESCE(NULLIF(pa.serial_number, ''), NULLIF(d.sn, ''), '')"
    management_ip_expr = "COALESCE(NULLIF(pa.management_ip, ''), NULLIF(d.ip_address, ''), '')"
    business_ip_expr = "COALESCE(NULLIF(pa.business_ip, ''), '')"
    vendor_expr = "COALESCE(NULLIF(pa.vendor, ''), NULLIF(d.vendor, ''), '')"
    model_expr = "COALESCE(NULLIF(pa.model, ''), NULLIF(d.model, ''), '')"
    platform_expr = "COALESCE(NULLIF(pa.platform, ''), NULLIF(d.platform, ''), '')"
    site_expr = "COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''), '')"
    category_expr = "COALESCE(NULLIF(pa.device_category, ''), NULLIF(d.device_category, ''), '')"
    lifecycle_expr = "COALESCE(NULLIF(pa.lifecycle_status, ''), NULLIF(d.lifecycle_status, ''), '')"
    online_expr = "COALESCE(NULLIF(d.status, ''), CASE WHEN pa.status = 'active' THEN 'online' WHEN pa.status IN ('inactive', 'maintenance', 'decommissioned') THEN 'offline' ELSE 'pending' END)"

    field_expressions = {
        'hostname': [hostname_expr],
        'asset_tag': [asset_tag_expr],
        'serial_number': [serial_expr],
        'ip': [management_ip_expr, business_ip_expr],
        'management_ip': [management_ip_expr],
        'business_ip': [business_ip_expr],
        'vendor': [vendor_expr],
        'model': [model_expr],
        'platform': [platform_expr],
    }

    conditions: list[str] = []
    params: list[object] = []
    if site_id:
        conditions.append(f"{site_expr} = ?")
        params.append(site_id)
    if asset_type and asset_type != 'all':
        conditions.append("COALESCE(NULLIF(pa.asset_type, ''), 'other') = ?")
        params.append(asset_type)
    if device_category:
        conditions.append(f"{category_expr} = ?")
        params.append(device_category)
    if vendor:
        conditions.append(f"LOWER({vendor_expr}) = LOWER(?)")
        params.append(vendor.strip())
    if platform:
        conditions.append(f"LOWER({platform_expr}) = LOWER(?)")
        params.append(platform.strip())
    if status and status != 'all':
        conditions.append(f"{online_expr} = ?")
        params.append(status)
    if lifecycle_status and lifecycle_status != 'all':
        conditions.append(f"{lifecycle_expr} = ?")
        params.append(lifecycle_status)

    if q:
        if search_field == 'all':
            expressions = [value for values in field_expressions.values() for value in values]
        else:
            expressions = field_expressions.get(search_field, [hostname_expr])
        if search_mode == 'exact':
            conditions.append('(' + ' OR '.join(f"LOWER({expr}) = LOWER(?)" for expr in expressions) + ')')
            params.extend([q] * len(expressions))
        else:
            conditions.append('(' + ' OR '.join(f"{expr} LIKE ?" for expr in expressions) + ')')
            params.extend([f'%{q}%'] * len(expressions))

    requested_tag_ids = [str(value).strip() for value in (tag_ids or []) if str(value).strip()][:100]
    if requested_tag_ids:
        tag_exists = [
            "EXISTS (SELECT 1 FROM tag_assignments ta_filter "
            "WHERE ta_filter.resource_type='device' "
            "AND ta_filter.resource_id = d.id AND ta_filter.tag_id = ?)"
            for _ in requested_tag_ids
        ]
        conditions.append('(' + (' AND '.join(tag_exists) if tag_match_all else ' OR '.join(tag_exists)) + ')')
        params.extend(requested_tag_ids)

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ''
    from_sql = """
        FROM devices d
        LEFT JOIN physical_assets pa ON pa.id = d.asset_id
        LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
    """
    total_row = conn.execute(f"SELECT COUNT(*) AS cnt {from_sql} {where}", params).fetchone()
    total = int(total_row['cnt'] if hasattr(total_row, 'keys') else total_row[0])
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"""
        SELECT d.id AS device_id,
               pa.id AS asset_id,
               {hostname_expr} AS hostname,
               {asset_tag_expr} AS asset_tag,
               {serial_expr} AS serial_number,
               COALESCE(NULLIF(pa.asset_type, ''), 'other') AS asset_type,
               {category_expr} AS device_category,
               COALESCE(NULLIF(pa.device_role, ''), NULLIF(d.role, ''), '') AS device_role,
               {vendor_expr} AS vendor,
               {model_expr} AS model,
               {platform_expr} AS platform,
               {management_ip_expr} AS management_ip,
               {business_ip_expr} AS business_ip,
               {online_expr} AS online_status,
               {lifecycle_expr} AS lifecycle_status,
               {site_expr} AS site_id,
               COALESCE(s.site_code, '') AS site_code,
               COALESCE(s.site_name, '') AS site_name,
               d.status AS device_status,
               0 AS interface_count,
               (
                 SELECT COUNT(*) FROM topology_links tl
                 WHERE tl.source_device_id = d.id OR tl.target_device_id = d.id
               ) AS link_count
        {from_sql}
        {where}
        ORDER BY {hostname_expr}, {management_ip_expr}, d.id
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset],
    ).fetchall()
    items = []
    for row in rows:
        item = _row_to_dict(row)
        item['interface_count'] = interface_counts.get(str(item.get('device_id') or ''), 0)
        items.append(item)
    return {
        'items': items,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': max(1, -(-total // page_size)),
    }


def list_cmdb_interfaces(
    conn,
    has_ip: bool | None = None,
    device_id: str | None = None,
    search: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> list[dict] | dict:
    """Return interfaces as CMDB skeleton resources with optional has_ip, device_id, search filters."""
    # Device deletion historically did not remove the legacy IP inventory
    # projection.  Purge those orphaned rows at the read boundary so stale
    # ``Unknown device`` groups cannot reappear in the CMDB interface view.
    conn.execute(
        """DELETE FROM ip_inventory
           WHERE device_id IS NULL
              OR NOT EXISTS (SELECT 1 FROM devices d WHERE d.id = ip_inventory.device_id)"""
    )
    conn.commit()
    sql = """
        SELECT
            i.id,
            i.device_id,
            d.hostname AS device_hostname,
            d.ip_address AS device_ip,
            d.platform AS device_platform,
            d.status AS device_status,
            i.interface_name,
            i.description,
            COALESCE(
                NULLIF(i.primary_ip, ''),
                NULLIF(i.ip_address, ''),
                (
                    SELECT COALESCE(NULLIF(ip.ip_address, ''), NULLIF(ip.address, ''))
                    FROM ip_addresses ip
                    WHERE (
                        ip.interface_id = i.id
                        OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name)
                    )
                      AND COALESCE(i.ip_enabled, 0) = 1
                      AND COALESCE(NULLIF(ip.ip_address, ''), NULLIF(ip.address, '')) IS NOT NULL
                    -- Keep this SQLite/PostgreSQL compatible.  The exact
                    -- interface_id match is already preferred by the
                    -- skeleton fields above; the fallback only needs the
                    -- newest address observation.
                    ORDER BY ip.updated_at DESC NULLS LAST
                    LIMIT 1
                )
            ) AS interface_ip,
            i.admin_status,
            i.oper_status,
            i.mac_address,
            i.speed,
            i.bandwidth,
            i.interface_type,
            i.switchport_mode,
            i.access_vlan,
            i.native_vlan,
            i.allowed_vlans,
            i.vrf_id,
            v.vrf_name,
            i.ip_enabled,
            i.last_flapped,
            (
                SELECT COUNT(*)
                FROM ip_addresses ip
                WHERE ip.interface_id = i.id
                   OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name)
            ) AS ip_count,
            (
                SELECT COUNT(*)
                FROM topology_links tl
                WHERE tl.source_interface_id = i.id OR tl.target_interface_id = i.id
            ) AS link_count
        FROM interfaces i
        LEFT JOIN devices d ON d.id = i.device_id
        LEFT JOIN vrfs v ON v.id = i.vrf_id
        WHERE 1=1
    """
    params: list = []
    if has_ip is True:
        sql += """ AND (
            NULLIF(i.primary_ip, '') IS NOT NULL
            OR NULLIF(i.ip_address, '') IS NOT NULL
            OR EXISTS (
                SELECT 1 FROM ip_addresses ip
                WHERE (
                    ip.interface_id = i.id
                    OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name)
                )
                  AND COALESCE(i.ip_enabled, 0) = 1
                  AND COALESCE(NULLIF(ip.ip_address, ''), NULLIF(ip.address, '')) IS NOT NULL
            )
        )"""
    elif has_ip is False:
        sql += """ AND (
            NULLIF(i.primary_ip, '') IS NULL
            AND NULLIF(i.ip_address, '') IS NULL
            AND NOT EXISTS (
                SELECT 1 FROM ip_addresses ip
                WHERE (
                    ip.interface_id = i.id
                    OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name)
                )
                  AND COALESCE(i.ip_enabled, 0) = 1
                  AND COALESCE(NULLIF(ip.ip_address, ''), NULLIF(ip.address, '')) IS NOT NULL
            )
        )"""

    if device_id:
        sql += " AND i.device_id = ?"
        params.append(device_id)

    if search:
        s = f"%{search.strip()}%"
        sql += """ AND (
            i.interface_name LIKE ?
            OR d.hostname LIKE ?
            OR d.ip_address LIKE ?
            OR i.primary_ip LIKE ?
            OR i.ip_address LIKE ?
            OR i.description LIKE ?
            OR EXISTS (
                SELECT 1 FROM ip_addresses ip
                WHERE (
                    ip.interface_id = i.id
                    OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name)
                )
                  AND (
                    ip.ip_address LIKE ?
                    OR ip.address LIKE ?
                  )
            )
        )"""
        params.extend([s, s, s, s, s, s, s, s])

    sql += " ORDER BY COALESCE(d.hostname, ''), COALESCE(i.interface_name, '')"
    rows = conn.execute(sql, tuple(params)).fetchall()
    raw_items = [_row_to_dict(r) for r in rows]

    # A device can report the same interface using different presentation
    # names (for example H3C ``GE1/0/1`` and
    # ``GigabitEthernet1/0/1``).  The interface table is being converged over
    # time, so keep the read contract one-row-per-device/interface even while
    # older aliases are still present in the database.
    items_by_identity: dict[tuple[str, str], dict] = {}
    for candidate in raw_items:
        identity = (
            str(candidate.get('device_id') or ''),
            normalize_interface_name(candidate.get('interface_name')).lower(),
        )
        if not identity[1]:
            identity = (identity[0], str(candidate.get('interface_name') or '').strip().lower())
        current = items_by_identity.get(identity)
        if current is None:
            items_by_identity[identity] = candidate
            continue
        candidate_score = (
            bool(candidate.get('interface_ip')),
            str(candidate.get('oper_status') or '').lower() not in {'', 'unknown'},
            str(candidate.get('admin_status') or '').lower() not in {'', 'unknown'},
            bool(
                candidate.get('access_vlan')
                or candidate.get('native_vlan')
                or str(candidate.get('allowed_vlans') or '').strip()
            ),
            int(candidate.get('link_count') or 0) > 0,
            -len(str(candidate.get('interface_name') or '')),
        )
        current_score = (
            bool(current.get('interface_ip')),
            str(current.get('oper_status') or '').lower() not in {'', 'unknown'},
            str(current.get('admin_status') or '').lower() not in {'', 'unknown'},
            bool(
                current.get('access_vlan')
                or current.get('native_vlan')
                or str(current.get('allowed_vlans') or '').strip()
            ),
            int(current.get('link_count') or 0) > 0,
            -len(str(current.get('interface_name') or '')),
        )
        preferred, secondary = (candidate, current) if candidate_score > current_score else (current, candidate)
        for field in (
            'interface_ip', 'description', 'mac_address', 'speed', 'bandwidth', 'vrf_id', 'last_flapped',
            'interface_type', 'switchport_mode', 'access_vlan', 'native_vlan', 'allowed_vlans',
        ):
            preferred_value = str(preferred.get(field) or '').strip().lower()
            if preferred_value in {'', 'unknown', '-', '--'} and secondary.get(field) not in (None, ''):
                preferred[field] = secondary[field]
        for field in ('admin_status', 'oper_status'):
            if str(preferred.get(field) or '').strip().lower() in {'', 'unknown', '-', '--'}:
                if str(secondary.get(field) or '').strip().lower() not in {'', 'unknown', '-', '--'}:
                    preferred[field] = secondary[field]
        preferred['ip_count'] = max(int(preferred.get('ip_count') or 0), int(secondary.get('ip_count') or 0))
        preferred['link_count'] = max(int(preferred.get('link_count') or 0), int(secondary.get('link_count') or 0))
        items_by_identity[identity] = preferred

    items = list(items_by_identity.values())

    # NSOT's ip_inventory is populated by the interface-IP collector and can
    # be fresher than the interface skeleton table. Include those records as
    # read-only interface resources when the skeleton row has not received the
    # IP fields yet. This keeps CMDB and /assets/nsot on the same IP authority
    # without copying or mutating NSOT data here.
    if has_ip is True:
        interface_facts_by_identity: dict[tuple[str, str], dict] = {}
        try:
            all_interface_rows = conn.execute(
                """SELECT device_id, interface_name, interface_type, switchport_mode,
                          access_vlan, native_vlan, allowed_vlans, admin_status, oper_status,
                          mac_address, description, speed, bandwidth, vrf_id, ip_enabled, last_flapped
                   FROM interfaces"""
            ).fetchall()
        except Exception:
            all_interface_rows = []
        for interface_row in all_interface_rows:
            fact = _row_to_dict(interface_row)
            identity = (
                str(fact.get('device_id') or ''),
                normalize_interface_name(fact.get('interface_name')).lower(),
            )
            if not identity[1]:
                continue
            current_fact = interface_facts_by_identity.setdefault(identity, fact)
            for field in (
                'interface_type', 'switchport_mode', 'access_vlan', 'native_vlan', 'allowed_vlans',
                'admin_status', 'oper_status', 'mac_address', 'description', 'speed', 'bandwidth',
                'vrf_id', 'ip_enabled', 'last_flapped',
            ):
                current_value = str(current_fact.get(field) or '').strip().lower()
                candidate_value = fact.get(field)
                if current_value in {'', 'unknown', '-', '--'} and candidate_value not in (None, ''):
                    current_fact[field] = candidate_value
        try:
            inventory_rows = conn.execute(
                """
                SELECT inv.ip, inv.device_id, inv.interface, inv.type, inv.last_seen,
                       d.hostname AS device_hostname, d.ip_address AS device_ip,
                       d.platform AS device_platform, d.status AS device_status,
                       i.id AS skeleton_interface_id,
                       i.admin_status AS skeleton_admin_status,
                       i.oper_status AS skeleton_oper_status,
                       i.interface_type AS skeleton_interface_type,
                       i.switchport_mode AS skeleton_switchport_mode,
                       i.access_vlan AS skeleton_access_vlan,
                       i.native_vlan AS skeleton_native_vlan,
                       i.allowed_vlans AS skeleton_allowed_vlans,
                       i.mac_address AS skeleton_mac_address,
                       i.description AS skeleton_description,
                       i.speed AS skeleton_speed,
                       i.bandwidth AS skeleton_bandwidth,
                       i.vrf_id AS skeleton_vrf_id,
                       i.ip_enabled AS skeleton_ip_enabled,
                       i.last_flapped AS skeleton_last_flapped
                FROM ip_inventory inv
                LEFT JOIN devices d ON d.id = inv.device_id
                LEFT JOIN interfaces i
                  ON i.device_id = inv.device_id
                 AND LOWER(TRIM(i.interface_name)) = LOWER(TRIM(inv.interface))
                WHERE COALESCE(inv.ip, '') <> ''
                  AND d.id IS NOT NULL
                ORDER BY COALESCE(d.hostname, ''), COALESCE(inv.interface, ''), inv.ip
                """
            ).fetchall()
        except Exception:
            inventory_rows = []

        existing_by_identity = {
            (
                str(item.get('device_id') or ''),
                normalize_interface_name(item.get('interface_name')).lower(),
            ): item
            for item in items
        }
        search_value = search.strip().lower() if search else ''
        for inventory_row in inventory_rows:
            inventory = _row_to_dict(inventory_row)
            # A successful current-state collection can disable a retained
            # skeleton row when its address disappeared. Do not rehydrate
            # that deliberately cleared row from the legacy inventory cache.
            if inventory.get('skeleton_interface_id') and inventory.get('skeleton_ip_enabled') in (0, False, '0'):
                continue
            ip_value = str(inventory.get('ip') or '').strip()
            inventory_device_id = str(inventory.get('device_id') or '')
            interface_name = str(inventory.get('interface') or '').strip()
            if device_id and inventory_device_id != str(device_id):
                continue
            if search_value:
                searchable = ' '.join(str(inventory.get(key) or '') for key in (
                    'ip', 'device_hostname', 'device_ip', 'interface', 'type',
                )).lower()
                if search_value not in searchable:
                    continue
            identity = (inventory_device_id, normalize_interface_name(interface_name).lower())
            existing = existing_by_identity.get(identity)
            if existing is not None:
                # ip_inventory owns the freshest address observation. Enrich
                # the skeleton row instead of appending a second row merely
                # because the vendor used a long or short alias.
                if ip_value:
                    existing['interface_ip'] = ip_value
                    existing['interface_ip_source'] = 'ip_inventory'
                    existing['ip_count'] = max(1, int(existing.get('ip_count') or 0))
                if inventory.get('last_seen'):
                    existing['last_seen'] = inventory.get('last_seen')
                continue
            interface_fact = interface_facts_by_identity.get(identity, {})
            fallback_item = {
                'id': inventory.get('skeleton_interface_id') or f"ipinv-{inventory_device_id}-{interface_name}-{ip_value}",
                'device_id': inventory_device_id,
                'device_hostname': inventory.get('device_hostname') or '',
                'device_ip': inventory.get('device_ip') or '',
                'device_platform': inventory.get('device_platform') or '',
                'device_status': inventory.get('device_status') or '',
                'interface_name': interface_name,
                'description': inventory.get('skeleton_description') or '',
                'interface_ip': ip_value,
                'interface_ip_source': 'ip_inventory',
                # ip_inventory only owns the address. Reuse the interface
                # skeleton's latest CLI-collected state so the NSOT fallback
                # does not hide admin/oper status behind a synthetic default.
                'admin_status': inventory.get('skeleton_admin_status') or 'unknown',
                'oper_status': inventory.get('skeleton_oper_status') or 'unknown',
                'mac_address': inventory.get('skeleton_mac_address') or '',
                'speed': inventory.get('skeleton_speed'),
                'bandwidth': inventory.get('skeleton_bandwidth'),
                'interface_type': inventory.get('skeleton_interface_type') or interface_fact.get('interface_type') or inventory.get('type') or 'unknown',
                'switchport_mode': inventory.get('skeleton_switchport_mode') or interface_fact.get('switchport_mode') or 'routed',
                'access_vlan': inventory.get('skeleton_access_vlan') if inventory.get('skeleton_access_vlan') is not None else interface_fact.get('access_vlan'),
                'native_vlan': inventory.get('skeleton_native_vlan') if inventory.get('skeleton_native_vlan') is not None else interface_fact.get('native_vlan'),
                'allowed_vlans': inventory.get('skeleton_allowed_vlans') or interface_fact.get('allowed_vlans') or '',
                'vrf_id': inventory.get('skeleton_vrf_id'),
                'vrf_name': '',
                'ip_enabled': inventory.get('skeleton_ip_enabled') if inventory.get('skeleton_ip_enabled') is not None else 1,
                'last_flapped': inventory.get('skeleton_last_flapped'),
                'ip_count': 1,
                'link_count': 0,
                'last_seen': inventory.get('last_seen'),
            }
            items.append(fallback_item)
            existing_by_identity[identity] = fallback_item

        items.sort(key=lambda item: (
            str(item.get('device_hostname') or ''),
            str(item.get('interface_name') or ''),
            str(item.get('interface_ip') or ''),
        ))
    if page is None and page_size is None:
        return items

    safe_page = max(1, int(page or 1))
    safe_page_size = max(1, min(int(page_size or 20), 100))
    total = len(items)
    start = (safe_page - 1) * safe_page_size
    device_options = [
        {'value': str(device_id), 'label': str(label)}
        for device_id, label in sorted({
            (str(item.get('device_id') or ''), str(item.get('device_hostname') or ''))
            for item in items
            if item.get('device_id') and item.get('device_hostname')
        }, key=lambda value: value[1].lower())
    ]
    summary = {
        'total': total,
        'with_ip': sum(1 for item in items if item.get('interface_ip') or int(item.get('ip_count') or 0) > 0),
        'oper_up': sum(1 for item in items if str(item.get('oper_status') or '').lower() == 'up'),
        'with_links': sum(1 for item in items if int(item.get('link_count') or 0) > 0),
    }
    return {
        'items': items[start:start + safe_page_size],
        'total': total,
        'page': safe_page,
        'page_size': safe_page_size,
        'total_pages': max(1, -(-total // safe_page_size)),
        'summary': summary,
        'device_options': device_options,
    }


def get_field_authority_quality(conn) -> dict:
    """Return read-only data-quality counters for CMDB/IPAM authority migration."""
    def count(sql: str, params: tuple = ()) -> int:
        try:
            row = conn.execute(sql, params).fetchone()
        except Exception:
            return 0
        if row is None:
            return 0
        if hasattr(row, 'keys') and 'cnt' in row.keys():
            return int(row['cnt'] or 0)
        return int(row[0] or 0)

    device_total = count("SELECT COUNT(*) AS cnt FROM devices")
    interface_total = count("SELECT COUNT(*) AS cnt FROM interfaces")
    ip_total = count("SELECT COUNT(*) AS cnt FROM ip_addresses")
    link_total = count("SELECT COUNT(*) AS cnt FROM topology_links")

    site_id_missing = count(
        "SELECT COUNT(*) AS cnt FROM devices WHERE site_id IS NULL OR site_id = ''"
    )
    site_id_orphaned = count(
        """SELECT COUNT(*) AS cnt
           FROM devices d
           LEFT JOIN sites s ON s.id = d.site_id
           WHERE COALESCE(d.site_id, '') != '' AND s.id IS NULL"""
    )
    site_name_mismatch = count(
        """SELECT COUNT(*) AS cnt
           FROM devices d
           LEFT JOIN sites s ON s.id = d.site_id
           WHERE COALESCE(d.site, '') != ''
             AND COALESCE(d.site_id, '') != ''
             AND s.id IS NOT NULL
             AND d.site NOT IN (s.site_name, s.site_code)"""
    )
    asset_id_orphaned = count(
        """SELECT COUNT(*) AS cnt
           FROM devices d
           LEFT JOIN physical_assets pa ON pa.id = d.asset_id
           WHERE COALESCE(d.asset_id, '') != '' AND pa.id IS NULL"""
    )
    asset_device_ip_mismatch = count(
        """SELECT COUNT(*) AS cnt
           FROM devices d
           JOIN physical_assets pa ON pa.id = d.asset_id
           WHERE COALESCE(d.ip_address, '') != ''
             AND COALESCE(pa.management_ip, '') != ''
             AND d.ip_address != pa.management_ip"""
    )
    duplicate_asset_links = count(
        """SELECT COUNT(*) AS cnt
           FROM (
             SELECT asset_id
             FROM devices
             WHERE COALESCE(asset_id, '') != ''
             GROUP BY asset_id
             HAVING COUNT(*) > 1
           ) t"""
    )
    ip_missing_interface_id = count(
        """SELECT COUNT(*) AS cnt
           FROM ip_addresses
           WHERE COALESCE(interface_name, '') != ''
             AND (interface_id IS NULL OR interface_id = '')"""
    )
    ip_orphaned_interface_id = count(
        """SELECT COUNT(*) AS cnt
           FROM ip_addresses ip
           LEFT JOIN interfaces i ON i.id = ip.interface_id
           WHERE COALESCE(ip.interface_id, '') != '' AND i.id IS NULL"""
    )
    topo_missing_interface_id = count(
        """SELECT COUNT(*) AS cnt
           FROM topology_links
           WHERE (COALESCE(source_port, '') != '' AND (source_interface_id IS NULL OR source_interface_id = ''))
              OR (COALESCE(target_port, '') != '' AND (target_interface_id IS NULL OR target_interface_id = ''))"""
    )
    topo_orphaned_interface_id = count(
        """SELECT COUNT(*) AS cnt
           FROM topology_links tl
           LEFT JOIN interfaces si ON si.id = tl.source_interface_id
           LEFT JOIN interfaces ti ON ti.id = tl.target_interface_id
           WHERE (COALESCE(tl.source_interface_id, '') != '' AND si.id IS NULL)
              OR (COALESCE(tl.target_interface_id, '') != '' AND ti.id IS NULL)"""
    )
    duplicate_vrf_names = count(
        """SELECT COUNT(*) AS cnt FROM (
             SELECT COALESCE(tenant_id, ''), vrf_name FROM vrfs
             GROUP BY COALESCE(tenant_id, ''), vrf_name HAVING COUNT(*) > 1
           ) t"""
    )
    duplicate_site_vlans = count(
        """SELECT COUNT(*) AS cnt FROM (
             SELECT COALESCE(site_id, ''), vlan_id FROM vlans
             GROUP BY COALESCE(site_id, ''), vlan_id HAVING COUNT(*) > 1
           ) t"""
    )
    prefix_scope_missing = count(
        """SELECT COUNT(*) AS cnt FROM prefixes
           WHERE COALESCE(tenant_id, '') = '' OR COALESCE(vrf_id, '') = '' OR COALESCE(site_id, '') = ''"""
    )

    issues = {
        'site_id_missing': site_id_missing,
        'site_id_orphaned': site_id_orphaned,
        'site_name_mismatch': site_name_mismatch,
        'asset_id_orphaned': asset_id_orphaned,
        'asset_device_ip_mismatch': asset_device_ip_mismatch,
        'duplicate_asset_links': duplicate_asset_links,
        'ip_missing_interface_id': ip_missing_interface_id,
        'ip_orphaned_interface_id': ip_orphaned_interface_id,
        'topology_missing_interface_id': topo_missing_interface_id,
        'topology_orphaned_interface_id': topo_orphaned_interface_id,
        'duplicate_vrf_names': duplicate_vrf_names,
        'duplicate_site_vlans': duplicate_site_vlans,
        'prefix_scope_missing': prefix_scope_missing,
    }
    return {
        'scope': 'cmdb_ipam_field_authority',
        'summary': {
            'devices': device_total,
            'interfaces': interface_total,
            'ip_addresses': ip_total,
            'topology_links': link_total,
            'issue_count': sum(issues.values()),
        },
        'issues': issues,
        'recommendations': [
            'Backfill devices.site_id before freezing devices.site.',
            'Backfill ip_addresses.interface_id before treating interface_name as display-only.',
            'Backfill topology_links source/target interface ids before using interface-id topology APIs.',
            'Resolve duplicate devices.asset_id links before enforcing one-to-one asset/device relation.',
        ],
    }


def backfill_field_authority(conn) -> dict:
    """Perform deterministic, non-destructive authority-field backfills."""
    counters = {
        'devices_site_id': 0,
        'ip_addresses_interface_id': 0,
        'topology_source_interface_id': 0,
        'topology_target_interface_id': 0,
    }
    devices = conn.execute(
        "SELECT id, site FROM devices WHERE COALESCE(site_id, '') = '' AND COALESCE(site, '') <> ''"
    ).fetchall()
    for device in devices:
        matches = conn.execute(
            "SELECT id FROM sites WHERE site_code = ? OR site_name = ?",
            (device['site'], device['site']),
        ).fetchall()
        unique_ids = {row['id'] for row in matches}
        if len(unique_ids) == 1:
            conn.execute("UPDATE devices SET site_id = ? WHERE id = ?", (next(iter(unique_ids)), device['id']))
            counters['devices_site_id'] += 1

    addresses = conn.execute(
        """SELECT id, device_id, interface_name FROM ip_addresses
           WHERE COALESCE(interface_id, '') = '' AND COALESCE(device_id, '') <> ''
             AND COALESCE(interface_name, '') <> ''"""
    ).fetchall()
    for address in addresses:
        matches = conn.execute(
            "SELECT id FROM interfaces WHERE device_id = ? AND interface_name = ?",
            (address['device_id'], address['interface_name']),
        ).fetchall()
        if len(matches) == 1:
            conn.execute("UPDATE ip_addresses SET interface_id = ? WHERE id = ?", (matches[0]['id'], address['id']))
            counters['ip_addresses_interface_id'] += 1

    links = conn.execute(
        """SELECT id, source_device_id, source_port, source_interface_id,
                  target_device_id, target_port, target_interface_id
           FROM topology_links"""
    ).fetchall()
    for link in links:
        for side in ('source', 'target'):
            if link[f'{side}_interface_id'] or not link[f'{side}_device_id'] or not link[f'{side}_port']:
                continue
            matches = conn.execute(
                "SELECT id FROM interfaces WHERE device_id = ? AND interface_name = ?",
                (link[f'{side}_device_id'], link[f'{side}_port']),
            ).fetchall()
            if len(matches) == 1:
                conn.execute(
                    f"UPDATE topology_links SET {side}_interface_id = ? WHERE id = ?",
                    (matches[0]['id'], link['id']),
                )
                counters[f'topology_{side}_interface_id'] += 1
    conn.commit()
    return {'updated': counters, 'quality': get_field_authority_quality(conn)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tenants
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def list_tenants(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM tenants ORDER BY name").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_tenant(conn, tenant_id: str) -> dict:
    row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    if not row:
        raise ValueError(f"Tenant not found: {tenant_id}")
    return _row_to_dict(row)


def create_tenant(conn, *, name: str, description: str = '') -> dict:
    exists = conn.execute("SELECT 1 FROM tenants WHERE name = ?", (name,)).fetchone()
    if exists:
        raise ValueError(f"Tenant name already exists: {name}")
    tenant_id = _new_id('tenant')
    conn.execute(
        "INSERT INTO tenants (id, name, description) VALUES (?, ?, ?)",
        (tenant_id, name, description),
    )
    conn.commit()
    logger.info(f"[CmdbService] Created tenant '{name}'")
    return get_tenant(conn, tenant_id)


def update_tenant(conn, tenant_id: str, **fields) -> dict:
    get_tenant(conn, tenant_id)
    if 'name' in fields and fields['name'] is not None:
        dup = conn.execute(
            "SELECT 1 FROM tenants WHERE name = ? AND id != ?", (fields['name'], tenant_id)
        ).fetchone()
        if dup:
            raise ValueError(f"Tenant name already exists: {fields['name']}")
    updates, params = [], []
    for key in ('name', 'description'):
        if key in fields and fields[key] is not None:
            updates.append(f"{key} = ?")
            params.append(fields[key])
    if not updates:
        return get_tenant(conn, tenant_id)
    params.append(tenant_id)
    conn.execute(f"UPDATE tenants SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    return get_tenant(conn, tenant_id)


def delete_tenant(conn, tenant_id: str) -> None:
    if tenant_id == _DEFAULT_TENANT:
        raise ValueError("Cannot delete the default tenant.")
    get_tenant(conn, tenant_id)
    # Guard against orphaning critical assets
    for table in ('devices', 'sites', 'vrfs', 'vlans'):
        try:
            row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM {table} WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()
        except Exception:
            continue
        cnt = row['cnt'] if hasattr(row, 'keys') and 'cnt' in row.keys() else row[0]
        if cnt and cnt > 0:
            raise ValueError(
                f"Cannot delete tenant: {cnt} record(s) in '{table}' still reference it."
            )
    conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
    conn.commit()
    logger.info(f"[CmdbService] Deleted tenant {tenant_id}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Sites
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def list_sites(conn, tenant_id: str = '', q: str = '', page: int | None = None, page_size: int = 20) -> list[dict] | dict:
    normalized_page_size = min(max(int(page_size or 20), 1), 100)
    normalized_page = max(int(page or 1), 1)
    search = str(q or '').strip().lower()
    if tenant_id:
        rows = conn.execute(
            "SELECT * FROM sites WHERE tenant_id = ? AND (LOWER(COALESCE(site_code, '')) LIKE ? OR LOWER(COALESCE(site_name, '')) LIKE ?) ORDER BY site_name",
            (tenant_id, f'%{search}%', f'%{search}%') if search else (tenant_id, '%%', '%%')
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sites WHERE LOWER(COALESCE(site_code, '')) LIKE ? OR LOWER(COALESCE(site_name, '')) LIKE ? ORDER BY site_name",
            (f'%{search}%', f'%{search}%') if search else ('%%', '%%')
        ).fetchall()
    # Discovery/import flows can create a second row for the same logical
    # site with only a hostname/status populated.  A site is a reference
    # object, so callers must receive one stable record per site rather than
    # exposing those partial duplicates in every selector and table.
    merged: dict[str, dict] = {}
    for raw in rows:
        item = _row_to_dict(raw)
        site_code = str(item.get('site_code') or '').strip().lower()
        site_name = str(item.get('site_name') or '').strip().lower()
        if not site_code and not site_name:
            continue
        key = site_code or site_name
        current = merged.get(key)
        if current is None:
            merged[key] = item
            continue
        # Keep the richer record when a partial discovery row duplicates a
        # manually maintained site, while still filling any missing fields.
        for field, value in item.items():
            if (current.get(field) is None or str(current.get(field) or '').strip() == '') and value not in (None, ''):
                current[field] = value
        current_score = sum(1 for value in current.values() if value not in (None, ''))
        item_score = sum(1 for value in item.values() if value not in (None, ''))
        if item_score > current_score:
            merged[key] = {**current, **item}
    result = sorted(merged.values(), key=lambda item: str(item.get('site_name') or item.get('site_code') or '').lower())
    if page is None:
        return result
    start = (normalized_page - 1) * normalized_page_size
    return {
        'items': result[start:start + normalized_page_size],
        'total': len(result),
        'page': normalized_page,
        'page_size': normalized_page_size,
        'total_pages': max(1, (len(result) + normalized_page_size - 1) // normalized_page_size),
    }


def get_site(conn, site_id: str) -> dict:
    row = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
    if not row:
        raise ValueError(f"Site not found: {site_id}")
    return _row_to_dict(row)


def create_site(conn, *, site_code: str | None = None, site_name: str, country: str = '',
                state_province: str = '', city: str = '', district: str = '', contact_name: str = '',
                contact_phone: str = '', contact_email: str = '', timezone: str = 'Asia/Shanghai', address: str = '',
                status: str = 'active', tenant_id: str = _DEFAULT_TENANT) -> dict:
    site_id = _new_id('site')
    # Site codes are internal stable identifiers, not business data users need
    # to maintain.  Ignore any legacy request value and always generate the
    # code from the newly created immutable site ID.
    site_code = f"SITE-{site_id.split('-', 1)[1].upper()}"
    dup = conn.execute("SELECT 1 FROM sites WHERE site_code = ?", (site_code,)).fetchone()
    if dup:
        raise ValueError(f"Site code already exists: {site_code}")
    now = _utc_now()
    conn.execute(
        """INSERT INTO sites (id, site_code, site_name, country, state_province, city, district,
           contact_name, contact_phone, contact_email, timezone, address, status, tenant_id,
           created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (site_id, site_code, site_name, country, state_province, city, district,
         contact_name, contact_phone, contact_email, timezone, address, status, tenant_id or _DEFAULT_TENANT,
         now, now),
    )
    conn.commit()
    logger.info(f"[CmdbService] Created site '{site_code}'")
    return get_site(conn, site_id)


def update_site(conn, site_id: str, **fields) -> dict:
    get_site(conn, site_id)
    if 'site_code' in fields and fields['site_code'] is not None:
        dup = conn.execute(
            "SELECT 1 FROM sites WHERE site_code = ? AND id != ?", (fields['site_code'], site_id)
        ).fetchone()
        if dup:
            raise ValueError(f"Site code already exists: {fields['site_code']}")
    updates, params = [], []
    for key in ('site_code', 'site_name', 'country', 'state_province', 'city', 'district',
                'contact_name', 'contact_phone', 'contact_email', 'timezone', 'address', 'status', 'tenant_id'):
        if key in fields and fields[key] is not None:
            updates.append(f"{key} = ?")
            params.append(fields[key])
    if not updates:
        return get_site(conn, site_id)
    updates.append('updated_at = ?')
    params.append(_utc_now())
    params.append(site_id)
    conn.execute(f"UPDATE sites SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    return get_site(conn, site_id)


def _cleanup_empty_site_residue(conn, site_id: str) -> dict | None:
    """Remove collector-only residue from a site with no live CMDB data.

    VLAN discovery creates vendor/system VLAN rows and topology discovery keeps
    run history after the devices that produced it have been removed.  Those
    records are useful while a site exists, but they must not make an otherwise
    empty site impossible to delete.  Return ``None`` unless the site is safe
    to clean automatically; the caller keeps the normal replacement-site guard
    for every real reference.
    """
    from services.vlan_discovery_service import is_system_default_vlan

    live_refs = (
        ('devices', 'site_id'),
        ('physical_assets', 'site_id'),
        ('prefixes', 'site_id'),
        ('topology_links', 'source_site_id'),
        ('topology_links', 'target_site_id'),
        ('topology_observations', 'source_site_id'),
        ('vlan_business_bindings', 'site_id'),
    )
    if any(_count_reference(conn, table, column, site_id) for table, column in live_refs):
        return None

    vlan_rows = conn.execute(
        "SELECT id, vlan_id, name, discovery_source FROM vlans WHERE site_id = ?",
        (site_id,),
    ).fetchall()
    if any(
        not is_system_default_vlan(
            row['vlan_id'],
            row['name'],
            # A disconnected site no longer has device platform evidence. The
            # well-known default names and VLAN 1 are still sufficient evidence;
            # non-manual discovery rows retain Cisco legacy-default handling.
            platform='Cisco' if str(row['discovery_source'] or '').strip().lower() not in ('', 'manual') else '',
            discovery_source=row['discovery_source'],
        )
        for row in vlan_rows
    ):
        return None

    vlan_ids = [str(row['id']) for row in vlan_rows if row['id']]
    if vlan_ids:
        placeholders = ','.join('?' for _ in vlan_ids)
        prefix_ref = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM prefixes WHERE vlan_id IN ({placeholders})",
            vlan_ids,
        ).fetchone()
        if int(prefix_ref['cnt'] or 0):
            return None

    run_rows = conn.execute(
        "SELECT id FROM topology_discovery_runs WHERE site_id = ?",
        (site_id,),
    ).fetchall()
    run_ids = [str(row['id']) for row in run_rows if row['id']]
    if run_ids:
        run_placeholders = ','.join('?' for _ in run_ids)
        # These tables do not consistently use ON DELETE CASCADE on older
        # installations, so clear their children explicitly first.
        conn.execute(
            f"DELETE FROM topology_discovery_run_devices WHERE run_id IN ({run_placeholders})",
            run_ids,
        )
        conn.execute(
            f"DELETE FROM topology_observations WHERE discovery_run_id IN ({run_placeholders})",
            run_ids,
        )
        conn.execute(
            f"DELETE FROM topology_discovery_runs WHERE id IN ({run_placeholders})",
            run_ids,
        )
    if vlan_ids:
        placeholders = ','.join('?' for _ in vlan_ids)
        conn.execute(f"DELETE FROM vlans WHERE id IN ({placeholders})", vlan_ids)

    return {
        'vlans': len(vlan_ids),
        'topology_discovery_runs': len(run_ids),
    }


def delete_site(conn, site_id: str, replacement_site_id: str = '') -> dict:
    """Delete a site, optionally moving all site-owned records first.

    A site is a shared CMDB parent.  Deleting it without an explicit target
    would either violate foreign keys or leave assets/racks without a valid
    location, so callers must opt into a replacement site when references
    exist.  The updates and delete are committed as one transaction.
    """
    site = get_site(conn, site_id)
    replacement_site_id = (replacement_site_id or '').strip()
    if replacement_site_id:
        if replacement_site_id == site_id:
            raise ValueError("Replacement site must be different from the site being deleted")
        replacement = get_site(conn, replacement_site_id)
    else:
        replacement = None

    refs = [
        ('devices', 'site_id'),
        ('racks', 'site_id'),
        ('vlans', 'site_id'),
        ('prefixes', 'site_id'),
        ('physical_assets', 'site_id'),
        ('topology_discovery_runs', 'site_id'),
        ('topology_links', 'source_site_id'),
        ('topology_links', 'target_site_id'),
        ('topology_observations', 'source_site_id'),
        ('vlan_business_bindings', 'site_id'),
    ]
    blockers = []
    counts: dict[str, int] = {}
    for table, column in refs:
        try:
            count = _count_reference(conn, table, column, site_id)
        except Exception:
            count = 0
        if count:
            key = f'{table}.{column}'
            counts[key] = count
            blockers.append(f'{key}={site_id} ({count})')

    # Racks created by older versions may still have a free-text datacenter
    # label even when site_id was left at a legacy/default value. Treat those
    # rows as references too, and move them with the rest of the site-owned
    # records so deletion cannot leave an orphaned rack location.
    legacy_rack_labels = [site_id, site.get('site_code') or '', site.get('site_name') or '']
    legacy_rack_labels = [label for label in legacy_rack_labels if label]
    legacy_rack_count = 0
    if legacy_rack_labels:
        placeholders = ','.join('?' for _ in legacy_rack_labels)
        try:
            legacy_rack_count = conn.execute(
                f"""SELECT COUNT(*) AS cnt FROM racks
                    WHERE COALESCE(site_id, '') <> ?
                      AND COALESCE(datacenter, '') IN ({placeholders})""",
                [site_id, *legacy_rack_labels],
            ).fetchone()['cnt']
        except Exception:
            # Minimal/legacy installations may not have the old column.
            legacy_rack_count = 0
    if legacy_rack_count:
        counts['racks.datacenter'] = legacy_rack_count
        blockers.append(f'racks.datacenter={site.get("site_code") or site_id} ({legacy_rack_count})')

    cleaned_references: dict[str, int] = {}
    auto_cleanup_keys = {'vlans.site_id', 'topology_discovery_runs.site_id'}
    if blockers and not replacement_site_id:
        blocker_keys = set(counts)
        if blocker_keys and blocker_keys.issubset(auto_cleanup_keys) and not legacy_rack_count:
            cleaned = _cleanup_empty_site_residue(conn, site_id)
            if cleaned is not None:
                cleaned_references = cleaned
                blockers = []
                counts = {}

    if blockers and not replacement_site_id:
        raise ValueError(
            f"Cannot delete site {site.get('site_code') or site_id}: still referenced by "
            + '; '.join(blockers)
            + '. Select a replacement site and retry.'
        )

    try:
        if replacement_site_id:
            for table, column in refs:
                if counts.get(f'{table}.{column}', 0):
                    conn.execute(
                        f'UPDATE {table} SET {column} = ? WHERE {column} = ?',
                        (replacement_site_id, site_id),
                    )
            if legacy_rack_count:
                replacement = replacement or get_site(conn, replacement_site_id)
                replacement_label = replacement.get('site_code') or replacement.get('site_name') or replacement_site_id
                placeholders = ','.join('?' for _ in legacy_rack_labels)
                try:
                    conn.execute(
                        f"""UPDATE racks SET site_id = ?, datacenter = ?
                            WHERE COALESCE(site_id, '') <> ?
                              AND COALESCE(datacenter, '') IN ({placeholders})""",
                        [replacement_site_id, replacement_label, site_id, *legacy_rack_labels],
                    )
                except Exception:
                    # The count query succeeded only on schemas that expose
                    # the legacy field, but keep deletion safe if the schema
                    # changes between inspection and update.
                    raise
        conn.execute("DELETE FROM sites WHERE id = ?", (site_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    logger.info(f"[CmdbService] Deleted site {site_id} ({site.get('site_code')})")
    return {
        'deleted_site_id': site_id,
        'replacement_site_id': replacement_site_id or None,
        'migrated_references': counts if replacement_site_id else {},
        'cleaned_references': cleaned_references,
        'replacement_site_code': replacement.get('site_code') if replacement else None,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VRFs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def list_vrfs(conn, tenant_id: str = '', q: str = '', page: int | None = None, page_size: int = 20) -> list[dict] | dict:
    normalized_page_size = min(max(int(page_size or 20), 1), 100)
    normalized_page = max(int(page or 1), 1)
    search = str(q or '').strip().lower()
    where = "WHERE (LOWER(COALESCE(vrf_name, '')) LIKE ? OR LOWER(COALESCE(rd, '')) LIKE ? OR LOWER(COALESCE(description, '')) LIKE ?)"
    params: list = [f'%{search}%', f'%{search}%', f'%{search}%'] if search else ['%%', '%%', '%%']
    if tenant_id:
        where += " AND tenant_id = ?"
        params.append(tenant_id)
    rows = conn.execute(f"SELECT * FROM vrfs {where} ORDER BY vrf_name", tuple(params)).fetchall()
    result = [_row_to_dict(r) for r in rows]
    if page is None:
        return result
    start = (normalized_page - 1) * normalized_page_size
    return {
        'items': result[start:start + normalized_page_size],
        'total': len(result),
        'page': normalized_page,
        'page_size': normalized_page_size,
        'total_pages': max(1, (len(result) + normalized_page_size - 1) // normalized_page_size),
    }


def get_vrf(conn, vrf_id: str) -> dict:
    row = conn.execute("SELECT * FROM vrfs WHERE id = ?", (vrf_id,)).fetchone()
    if not row:
        raise ValueError(f"VRF not found: {vrf_id}")
    return _row_to_dict(row)


def create_vrf(conn, *, vrf_name: str, rd: str = '', description: str = '',
               tenant_id: str = _DEFAULT_TENANT) -> dict:
    target_tenant = tenant_id or _DEFAULT_TENANT
    dup = conn.execute(
        "SELECT 1 FROM vrfs WHERE vrf_name = ? AND COALESCE(tenant_id, ?) = ?",
        (vrf_name, _DEFAULT_TENANT, target_tenant),
    ).fetchone()
    if dup:
        raise ValueError(f"VRF name already exists: {vrf_name}")
    vrf_id = _new_id('vrf')
    conn.execute(
        "INSERT INTO vrfs (id, vrf_name, rd, description, tenant_id) VALUES (?, ?, ?, ?, ?)",
        (vrf_id, vrf_name, rd, description, target_tenant),
    )
    conn.commit()
    logger.info(f"[CmdbService] Created VRF '{vrf_name}'")
    return get_vrf(conn, vrf_id)


def update_vrf(conn, vrf_id: str, **fields) -> dict:
    existing = get_vrf(conn, vrf_id)
    if any(key in fields and fields[key] is not None for key in ('vrf_name', 'tenant_id')):
        target_name = fields.get('vrf_name', existing.get('vrf_name'))
        target_tenant = fields.get('tenant_id', existing.get('tenant_id')) or _DEFAULT_TENANT
        dup = conn.execute(
            "SELECT 1 FROM vrfs WHERE vrf_name = ? AND COALESCE(tenant_id, ?) = ? AND id != ?",
            (target_name, _DEFAULT_TENANT, target_tenant, vrf_id),
        ).fetchone()
        if dup:
            raise ValueError(f"VRF name already exists in tenant: {target_name}")
    updates, params = [], []
    for key in ('vrf_name', 'rd', 'description', 'tenant_id'):
        if key in fields and fields[key] is not None:
            updates.append(f"{key} = ?")
            params.append(fields[key])
    if not updates:
        return get_vrf(conn, vrf_id)
    params.append(vrf_id)
    conn.execute(f"UPDATE vrfs SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    return get_vrf(conn, vrf_id)


def delete_vrf(conn, vrf_id: str) -> None:
    get_vrf(conn, vrf_id)
    _raise_if_referenced(conn, "VRF", [
        ('interfaces', 'vrf_id', vrf_id),
        ('prefixes', 'vrf_id', vrf_id),
        ('ip_addresses', 'vrf_id', vrf_id),
    ])
    conn.execute("DELETE FROM vrfs WHERE id = ?", (vrf_id,))
    conn.commit()
    logger.info(f"[CmdbService] Deleted VRF {vrf_id}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VLANs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_vlan_scope_tree(conn, rows: list[dict]) -> list[dict]:
    """Build the CMDB asset hierarchy for VLAN evidence rows."""
    root = {"id": "root", "kind": "root", "label": "All assets", "count": 0, "branch": {}, "children": []}
    metadata = {
        str(row['id']): dict(row)
        for row in conn.execute(
            """SELECT d.id,
                      COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''), NULLIF(d.site, ''), 'unassigned') AS site_id,
                      COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), NULLIF(d.site, ''), 'Unassigned site') AS site_name,
                      COALESCE(NULLIF(pa.asset_type, ''), 'network_device') AS asset_type,
                      COALESCE(NULLIF(pa.device_category, ''), NULLIF(d.device_category, ''), 'other') AS device_category,
                      COALESCE(NULLIF(pa.device_role, ''), NULLIF(d.role, ''), 'unassigned') AS device_role
               FROM devices d
               LEFT JOIN physical_assets pa ON pa.id = d.asset_id
               LEFT JOIN sites s ON (
                   s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''), NULLIF(d.site, ''))
                   OR (COALESCE(d.site_id, '') = '' AND (s.site_code = d.site OR s.site_name = d.site))
               )"""
        ).fetchall()
    }

    def find_or_create(parent: dict, node_id: str, kind: str, label: str, branch: dict) -> dict:
        node = next((item for item in parent['children'] if item['id'] == node_id), None)
        if node is None:
            node = {'id': node_id, 'kind': kind, 'label': label or 'Unassigned', 'count': 0, 'branch': branch, 'children': []}
            parent['children'].append(node)
        node['count'] += 1
        return node

    for row in rows:
        device = metadata.get(str(row.get('device_id') or ''), {})
        site_id = str(device.get('site_id') or row.get('site_id') or 'unassigned')
        site_name = str(device.get('site_name') or row.get('site_name') or 'Unassigned site')
        asset_type = str(device.get('asset_type') or 'network_device')
        category = str(device.get('device_category') or 'other')
        role = str(device.get('device_role') or 'unassigned')
        root['count'] += 1
        site_branch = {'site_id': site_id}
        site = find_or_create(root, f'site:{site_id}', 'site', site_name, site_branch)
        asset = find_or_create(site, f"{site['id']}:type:{asset_type}", 'type', asset_type, {**site_branch, 'asset_type': asset_type})
        category_node = find_or_create(asset, f"{asset['id']}:category:{category}", 'category', category, {**site_branch, 'asset_type': asset_type, 'device_category': category})
        find_or_create(category_node, f"{category_node['id']}:role:{role}", 'role', role, {**site_branch, 'asset_type': asset_type, 'device_category': category, 'device_role': '' if role == 'unassigned' else role})
    return [root]


def list_vlans(conn, site_id: str = '', tenant_id: str = '', *, device_scoped: bool = False, q: str = '', status: str = 'all', asset_type: str = '', device_category: str = '', device_role: str = '', page: int | None = None, page_size: int = 20) -> list[dict] | dict:
    clauses, params = [], []
    if site_id:
        if site_id == 'unassigned':
            clauses.append("COALESCE(site_id, '') = ''")
        else:
            clauses.append("site_id = ?")
            params.append(site_id)
    if tenant_id:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)
    if status and status != 'all':
        clauses.append("status = ?")
        params.append(status)
    if q and q.strip():
        clauses.append("(LOWER(CAST(vlan_id AS TEXT)) LIKE ? OR LOWER(COALESCE(name, '')) LIKE ?)")
        fuzzy = f"%{q.strip().lower()}%"
        params.extend([fuzzy, fuzzy])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM vlans{where} ORDER BY vlan_id", params
    ).fetchall()
    result = []
    from services.vlan_discovery_service import (
        is_system_default_vlan,
        parse_vlan_id_from_interface,
        parse_vlan_values,
    )
    site_platforms: dict[str, set[str]] = {}
    for device in conn.execute("SELECT site_id, site, platform, vendor FROM devices").fetchall():
        scope = str(device['site_id'] or device['site'] or '')
        site_platforms.setdefault(scope, set()).add(str(device['platform'] or device['vendor'] or ''))

    for raw_row in rows:
        item = _row_to_dict(raw_row)
        vlan_number = int(item.get('vlan_id') or 0)
        scope_site = str(item.get('site_id') or '')
        if is_system_default_vlan(
            vlan_number,
            item.get('name'),
            platform=next(
                (value for value in site_platforms.get(scope_site, set())
                 if any(token in value.lower() for token in ('cisco', 'ios', 'nxos'))),
                '',
            ),
            discovery_source=item.get('discovery_source'),
        ):
            continue
        site = conn.execute(
            "SELECT site_code, site_name FROM sites WHERE id = ? LIMIT 1",
            (scope_site,),
        ).fetchone() if scope_site else None
        item['site_code'] = site['site_code'] if site else ''
        item['site_name'] = site['site_name'] if site else ''

        prefix_rows = conn.execute(
            """SELECT p.id, p.prefix, p.gateway, p.vrf_id,
                      v.vrf_name, gd.hostname AS gateway_device_name,
                      gi.interface_name AS gateway_interface_name
               FROM prefixes p
               LEFT JOIN vrfs v ON v.id = p.vrf_id
               LEFT JOIN devices gd ON gd.id = p.gateway_device_id
               LEFT JOIN interfaces gi ON gi.id = p.gateway_interface_id
               WHERE p.vlan_id = ?
               ORDER BY p.prefix""",
            (item.get('id'),),
        ).fetchall()
        prefix_ids = [str(row['id']) for row in prefix_rows if row['id']]
        item['prefix_count'] = len(prefix_rows)
        item['prefixes'] = ', '.join(str(row['prefix'] or '') for row in prefix_rows if row['prefix'])
        item['ip_count'] = 0
        if prefix_ids:
            placeholders = ','.join('?' for _ in prefix_ids)
            ip_count = conn.execute(
                f"SELECT COUNT(*) AS count FROM ip_addresses WHERE prefix_id IN ({placeholders})",
                tuple(prefix_ids),
            ).fetchone()
            item['ip_count'] = int(ip_count['count'] or 0) if ip_count else 0

        gateway = next((row for row in prefix_rows if row['gateway']), None)
        item['gateway'] = gateway['gateway'] if gateway else ''
        item['gateway_device'] = gateway['gateway_device_name'] if gateway else ''
        item['gateway_interface'] = gateway['gateway_interface_name'] if gateway else ''
        item['vrf_name'] = gateway['vrf_name'] if gateway else ''

        device_rows = conn.execute(
            """SELECT i.device_id, d.hostname, d.ip_address AS device_ip,
                      i.interface_name, i.description, i.interface_type,
                      i.primary_ip, i.ip_address, i.ip_prefix_length,
                      i.access_vlan, i.native_vlan, i.allowed_vlans
               FROM interfaces i
               JOIN devices d ON d.id = i.device_id
               WHERE (? = '' OR COALESCE(d.site_id, d.site, '') = ?)""",
            (scope_site, scope_site),
        ).fetchall()
        devices: set[str] = set()
        ports: set[str] = set()
        svi_names: set[str] = set()
        svi_descriptions: set[str] = set()
        port_details: list[str] = []
        port_detail_rows: list[dict] = []
        undocumented_ports = 0
        for interface in device_rows:
            svi_vlan = parse_vlan_id_from_interface(interface['interface_name'])
            if svi_vlan == vlan_number:
                # An SVI/Vlanif is the L3 gateway representation of the VLAN,
                # not an access/trunk port. Keep it in the SVI column only.
                svi_names.add(str(interface['interface_name']))
                svi_description = str(interface['description'] or '').strip()
                if svi_description:
                    svi_descriptions.add(svi_description)
                devices.add(str(interface['hostname'] or interface['device_id']))
                if not item.get('gateway'):
                    svi_ip = str(interface['primary_ip'] or interface['ip_address'] or '').strip()
                    if svi_ip:
                        item['gateway'] = svi_ip.split('/', 1)[0]
                        item['gateway_device'] = str(interface['hostname'] or interface['device_id'])
                        item['gateway_interface'] = str(interface['interface_name'])
                continue
            interface_vlans = parse_vlan_values(interface['access_vlan']) | parse_vlan_values(interface['native_vlan'])
            interface_vlans |= parse_vlan_values(interface['allowed_vlans'])
            if vlan_number in interface_vlans:
                devices.add(str(interface['hostname'] or interface['device_id']))
                ports.add(f"{interface['hostname'] or interface['device_id']}:{interface['interface_name']}")
                description = str(interface['description'] or '').strip()
                if not description:
                    undocumented_ports += 1
                port_details.append(
                    f"{interface['hostname'] or interface['device_id']}:{interface['interface_name']} - {description}"
                )
                port_detail_rows.append({
                    'device_id': str(interface['device_id'] or ''),
                    'device_hostname': str(interface['hostname'] or interface['device_id'] or ''),
                    'device_ip': str(interface['device_ip'] or ''),
                    'interface_name': str(interface['interface_name'] or ''),
                    'description': description,
                })
        item['device_count'] = len(devices)
        item['device_names'] = ', '.join(sorted(devices))
        item['port_count'] = len(ports)
        item['svi_count'] = len(svi_names)
        item['svi_interfaces'] = ', '.join(sorted(svi_names))
        item['description'] = '; '.join(sorted(svi_descriptions))
        item['port_details'] = '; '.join(sorted(port_details))
        item['port_detail_rows'] = port_detail_rows
        item['undocumented_port_count'] = undocumented_ports

        def count_observations(table: str) -> int:
            row = conn.execute(
                f"""SELECT COUNT(*) AS count FROM {table} x
                    JOIN devices d ON d.id = x.device_id
                    WHERE x.vlan_id = ?
                      AND (? = '' OR COALESCE(d.site_id, d.site, '') = ?)""",
                (vlan_number, scope_site, scope_site),
            ).fetchone()
            return int(row['count'] or 0) if row else 0

        item['arp_count'] = count_observations('arp_table')
        item['mac_count'] = count_observations('mac_table')

        # Keep the actual endpoint evidence alongside the aggregate counts so
        # the VLAN page can answer the operator's next question: which IP/MAC
        # was learned on which device/interface? ARP and MAC observations are
        # intentionally merged and de-duplicated for a compact detail view.
        endpoint_details: list[dict] = []
        endpoint_keys: set[tuple[str, str, str, str]] = set()
        arp_rows = conn.execute(
            """SELECT a.ip_address, a.mac_address, a.interface_name, a.vlan_id,
                      a.last_updated, d.hostname AS device_hostname, d.ip_address AS device_ip
               FROM arp_table a
               JOIN devices d ON d.id = a.device_id
               WHERE a.vlan_id = ?
                 AND (? = '' OR COALESCE(d.site_id, d.site, '') = ?)
               ORDER BY a.ip_address, d.hostname""",
            (vlan_number, scope_site, scope_site),
        ).fetchall()
        for observation in arp_rows:
            key = (
                'arp', str(observation['ip_address'] or ''),
                str(observation['mac_address'] or ''),
                str(observation['device_hostname'] or ''),
            )
            if key in endpoint_keys:
                continue
            endpoint_keys.add(key)
            endpoint_details.append({
                'source': 'arp',
                'ip_address': str(observation['ip_address'] or ''),
                'mac_address': str(observation['mac_address'] or ''),
                'interface_name': str(observation['interface_name'] or ''),
                'device_hostname': str(observation['device_hostname'] or ''),
                'device_ip': str(observation['device_ip'] or ''),
                'last_updated': observation['last_updated'],
            })

        mac_rows = conn.execute(
            """SELECT m.mac_address, m.interface_name, m.vlan_id,
                      m.last_updated, d.hostname AS device_hostname, d.ip_address AS device_ip
               FROM mac_table m
               JOIN devices d ON d.id = m.device_id
               WHERE m.vlan_id = ?
                 AND (? = '' OR COALESCE(d.site_id, d.site, '') = ?)
               ORDER BY m.mac_address, d.hostname""",
            (vlan_number, scope_site, scope_site),
        ).fetchall()
        for observation in mac_rows:
            key = (
                'mac', '', str(observation['mac_address'] or ''),
                f"{observation['device_hostname'] or ''}:{observation['interface_name'] or ''}",
            )
            if key in endpoint_keys:
                continue
            endpoint_keys.add(key)
            endpoint_details.append({
                'source': 'mac',
                'ip_address': '',
                'mac_address': str(observation['mac_address'] or ''),
                'interface_name': str(observation['interface_name'] or ''),
                'device_hostname': str(observation['device_hostname'] or ''),
                'device_ip': str(observation['device_ip'] or ''),
                'last_updated': observation['last_updated'],
            })

        item['endpoint_details'] = endpoint_details
        observation_times = [
            observation['last_updated']
            for observation in (*arp_rows, *mac_rows)
            if observation['last_updated']
        ]
        item['endpoint_last_seen_at'] = max(observation_times) if observation_times else ''

        bindings = conn.execute(
            """SELECT business_system, department, owner, business_level
               FROM vlan_business_bindings
               WHERE vlan_id = ? AND (site_id = ? OR (site_id = '' AND ? = ''))
                 AND status <> 'retired'
               ORDER BY business_system""",
            (vlan_number, scope_site, scope_site),
        ).fetchall()
        item['business_count'] = len(bindings)
        item['business_systems'] = ', '.join(str(row['business_system'] or '') for row in bindings)
        item['business_departments'] = ', '.join(sorted({str(row['department'] or '') for row in bindings if row['department']}))
        item['business_owners'] = ', '.join(sorted({str(row['owner'] or '') for row in bindings if row['owner']}))
        item['highest_business_level'] = next(
            (level for level in ('P1', 'P2', 'P3', 'P4') if any(row['business_level'] == level for row in bindings)),
            '',
        )
        result.append(item)
    expanded = _expand_vlan_rows_by_device(conn, result) if device_scoped else result
    full_expanded = list(expanded)
    if asset_type:
        expanded = [row for row in expanded if str(row.get('asset_type') or 'network_device') == asset_type]
    if device_category:
        expanded = [row for row in expanded if str(row.get('device_category') or 'other') == device_category]
    if device_role:
        expanded = [row for row in expanded if str(row.get('device_role') or 'unassigned') == device_role]
    if page is None:
        return expanded
    normalized_page_size = min(max(int(page_size or 20), 1), 100)
    normalized_page = max(int(page or 1), 1)
    start = (normalized_page - 1) * normalized_page_size
    site_counts: dict[str, dict[str, object]] = {}
    for row in expanded:
        site_id = str(row.get('site_id') or '').strip()
        key = site_id or 'unassigned'
        entry = site_counts.setdefault(key, {
            'key': key,
            'label': str(row.get('site_name') or row.get('site_code') or '未分配站点'),
            'count': 0,
        })
        entry['count'] = int(entry['count']) + 1
    return {
        'items': expanded[start:start + normalized_page_size],
        'total': len(expanded),
        'page': normalized_page,
        'page_size': normalized_page_size,
        'site_summary': sorted(site_counts.values(), key=lambda item: str(item['label']).lower()),
        'tree': _build_vlan_scope_tree(conn, full_expanded),
        'summary': {
            'total': len(expanded),
            'gateways': sum(1 for row in expanded if str(row.get('gateway') or '').strip()),
            'arp': sum(int(row.get('arp_count') or 0) for row in expanded),
            'mac': sum(int(row.get('mac_count') or 0) for row in expanded),
            'unbound': sum(1 for row in expanded if not int(row.get('business_count') or 0)),
        },
    }


def _expand_vlan_rows_by_device(conn, vlan_rows: list[dict]) -> list[dict]:
    """Return VLAN facts at the operator's device -> VLAN grain.

    The relational VLAN record remains scoped by site + VLAN, but a site can
    have the same VLAN on multiple switches.  The UI must not merge those
    switches because their SVI gateway, interfaces, ARP and collection times
    are different observations.
    """
    from services.vlan_discovery_service import parse_vlan_id_from_interface, parse_vlan_values

    device_metadata = {
        str(row['id']): dict(row)
        for row in conn.execute(
            """SELECT d.id,
                      COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''), NULLIF(d.site, ''), 'unassigned') AS resolved_site_id,
                      COALESCE(NULLIF(pa.asset_type, ''), 'network_device') AS asset_type,
                      COALESCE(NULLIF(pa.device_category, ''), NULLIF(d.device_category, ''), 'other') AS device_category,
                      COALESCE(NULLIF(pa.device_role, ''), NULLIF(d.role, ''), 'unassigned') AS device_role
               FROM devices d
               LEFT JOIN physical_assets pa ON pa.id = d.asset_id"""
        ).fetchall()
    }

    scoped_rows: list[dict] = []
    for item in vlan_rows:
        vlan_number = int(item.get('vlan_id') or 0)
        scope_site = str(item.get('site_id') or '')
        device_interfaces = conn.execute(
            """SELECT i.device_id, d.hostname AS device_hostname, d.ip_address AS device_ip,
                      i.interface_name, i.description, i.primary_ip, i.ip_address,
                      i.ip_prefix_length, i.access_vlan, i.native_vlan, i.allowed_vlans,
                      i.last_seen
               FROM interfaces i JOIN devices d ON d.id = i.device_id
               WHERE (? = '' OR COALESCE(d.site_id, d.site, '') = ?)
               ORDER BY d.hostname, i.interface_name""",
            (scope_site, scope_site),
        ).fetchall()
        device_ids = {
            str(row['device_id']) for row in device_interfaces
            if parse_vlan_id_from_interface(row['interface_name']) == vlan_number
            or vlan_number in (
                parse_vlan_values(row['access_vlan'])
                | parse_vlan_values(row['native_vlan'])
                | parse_vlan_values(row['allowed_vlans'])
            )
        }
        device_ids.update(str(row['device_id']) for row in conn.execute(
            """SELECT DISTINCT a.device_id FROM arp_table a JOIN devices d ON d.id = a.device_id
               WHERE a.vlan_id = ? AND (? = '' OR COALESCE(d.site_id, d.site, '') = ?)""",
            (vlan_number, scope_site, scope_site),
        ).fetchall())
        device_ids.update(str(row['device_id']) for row in conn.execute(
            """SELECT DISTINCT m.device_id FROM mac_table m JOIN devices d ON d.id = m.device_id
               WHERE m.vlan_id = ? AND (? = '' OR COALESCE(d.site_id, d.site, '') = ?)""",
            (vlan_number, scope_site, scope_site),
        ).fetchall())

        if not device_ids:
            scoped_rows.append(item)
            continue

        for device_id in sorted(device_ids):
            rows = [row for row in device_interfaces if str(row['device_id']) == device_id]
            if not rows:
                continue
            device_hostname = str(rows[0]['device_hostname'] or device_id)
            device_ip = str(rows[0]['device_ip'] or '')
            svi_rows = [row for row in rows if parse_vlan_id_from_interface(row['interface_name']) == vlan_number]
            access_rows = [
                row for row in rows
                if parse_vlan_id_from_interface(row['interface_name']) != vlan_number
                and vlan_number in (
                    parse_vlan_values(row['access_vlan'])
                    | parse_vlan_values(row['native_vlan'])
                    | parse_vlan_values(row['allowed_vlans'])
                )
            ]
            prefixes: list[str] = []
            gateways: list[str] = []
            for svi in svi_rows:
                raw_ip = str(svi['primary_ip'] or svi['ip_address'] or '').strip()
                if not raw_ip:
                    continue
                prefix_length = str(svi['ip_prefix_length'] or '').strip()
                if not prefix_length:
                    if '/' in raw_ip:
                        raw_ip, prefix_length = raw_ip.split('/', 1)
                    else:
                        norm_intf = normalize_interface_name(svi['interface_name'])
                        inv_row = conn.execute(
                            "SELECT mask FROM ip_inventory WHERE device_id = ? AND (interface = ? OR LOWER(interface) = ?) LIMIT 1",
                            (device_id, svi['interface_name'], norm_intf),
                        ).fetchone()
                        if inv_row and inv_row['mask']:
                            prefix_length = str(inv_row['mask']).strip()

                clean_host_ip = raw_ip.split('/', 1)[0].strip()
                if not clean_host_ip:
                    continue

                if prefix_length and '.' in prefix_length:
                    try:
                        net = ipaddress.IPv4Network(f'0.0.0.0/{prefix_length}')
                        prefix_length = str(net.prefixlen)
                    except ValueError:
                        prefix_length = ''

                try:
                    if prefix_length:
                        address = ipaddress.ip_interface(f'{clean_host_ip}/{prefix_length}')
                    else:
                        address = ipaddress.ip_interface(f'{clean_host_ip}/32')
                    gateways.append(str(address.ip))
                    if prefix_length and prefix_length != '32':
                        prefixes.append(str(address.network))
                    elif '/' in str(svi['primary_ip'] or svi['ip_address'] or ''):
                        prefixes.append(str(address.network))
                    else:
                        prefixes.append(str(address.ip))
                except ValueError:
                    continue

            arp_rows = conn.execute(
                "SELECT ip_address, mac_address, interface_name, last_updated FROM arp_table WHERE device_id = ? AND vlan_id = ? ORDER BY ip_address",
                (device_id, vlan_number),
            ).fetchall()
            mac_rows = conn.execute(
                "SELECT mac_address, interface_name, last_updated FROM mac_table WHERE device_id = ? AND vlan_id = ? ORDER BY mac_address",
                (device_id, vlan_number),
            ).fetchall()
            endpoint_details = [
                detail for detail in (item.get('endpoint_details') or [])
                if str(detail.get('device_hostname') or '') == device_hostname
            ]
            port_detail_rows = [{
                'device_id': device_id,
                'device_hostname': device_hostname,
                'device_ip': device_ip,
                'interface_name': str(row['interface_name'] or ''),
                'description': str(row['description'] or ''),
            } for row in access_rows]
            interface_times = [row['last_seen'] for row in (*svi_rows, *access_rows) if row['last_seen']]
            arp_times = [row['last_updated'] for row in arp_rows if row['last_updated']]
            mac_times = [row['last_updated'] for row in mac_rows if row['last_updated']]
            device_row = dict(item)
            device_info = device_metadata.get(device_id, {})
            device_row.update({
                'device_id': device_id,
                'device_hostname': device_hostname,
                'device_ip': device_ip,
                'asset_type': device_info.get('asset_type') or 'network_device',
                'device_category': device_info.get('device_category') or 'other',
                'device_role': device_info.get('device_role') or 'unassigned',
                'site_id': device_info.get('resolved_site_id') or device_row.get('site_id') or '',
                'device_count': 1,
                'device_names': device_hostname,
                'port_count': len(port_detail_rows),
                'port_detail_rows': port_detail_rows,
                'port_details': '; '.join(
                    f"{row['device_hostname']}:{row['interface_name']} - {row['description']}"
                    for row in port_detail_rows
                ),
                'undocumented_port_count': sum(1 for row in port_detail_rows if not row['description']),
                'svi_interfaces': ', '.join(str(row['interface_name'] or '') for row in svi_rows),
                'description': '; '.join(sorted({str(row['description'] or '') for row in svi_rows if row['description']})),
                'prefixes': ', '.join(dict.fromkeys(prefixes)),
                'gateway': gateways[0] if gateways else '',
                'gateway_device': device_hostname if gateways else '',
                'gateway_interface': str(svi_rows[0]['interface_name'] or '') if gateways and svi_rows else '',
                'arp_count': len(arp_rows),
                'mac_count': len(mac_rows),
                'endpoint_details': endpoint_details,
                'endpoint_last_seen_at': max(arp_times + mac_times) if arp_times + mac_times else '',
                'interface_collected_at': max(interface_times) if interface_times else '',
                'arp_collected_at': max(arp_times) if arp_times else '',
                'mac_collected_at': max(mac_times) if mac_times else '',
            })
            scoped_rows.append(device_row)
    return sorted(
        scoped_rows,
        key=lambda row: (
            str(row.get('device_hostname') or '').lower(),
            int(row.get('vlan_id') or 0),
            str(row.get('device_ip') or ''),
        ),
    )


def export_vlans(conn, site_id: str = '', tenant_id: str = '') -> list[dict]:
    """Build a complete, row-oriented VLAN export.

    The UI intentionally shows a bounded summary for large VLANs.  Export is
    the complete evidence view: one row per discovered access interface, with
    ARP/MAC observations aggregated for that device/interface.  A gateway-only
    row is emitted when no access interface was discovered.
    """
    from services.vlan_discovery_service import parse_vlan_id_from_interface, parse_vlan_values

    export_rows: list[dict] = []
    for vlan in list_vlans(conn, site_id=site_id, tenant_id=tenant_id, device_scoped=True):
        vlan_number = int(vlan.get('vlan_id') or 0)
        scope_site = str(vlan.get('site_id') or '')
        site_label = str(vlan.get('site_name') or vlan.get('site_code') or scope_site or '未分配站点')
        device_id = str(vlan.get('device_id') or '')
        device_clause = " AND d.id = ?" if device_id else ""
        device_params = (scope_site, scope_site, device_id) if device_id else (scope_site, scope_site)
        port_rows = conn.execute(
            f"""SELECT i.device_id, d.hostname AS device_hostname, d.ip_address AS device_ip,
                      i.interface_name, i.description, i.access_vlan, i.native_vlan,
                      i.allowed_vlans
               FROM interfaces i
               JOIN devices d ON d.id = i.device_id
               WHERE (? = '' OR COALESCE(d.site_id, d.site, '') = ?){device_clause}
               ORDER BY d.hostname, i.interface_name""",
            device_params,
        ).fetchall()
        access_rows: list[dict] = []
        for row in port_rows:
            interface_name = str(row['interface_name'] or '')
            if parse_vlan_id_from_interface(interface_name) == vlan_number:
                continue
            interface_vlans = (
                parse_vlan_values(row['access_vlan'])
                | parse_vlan_values(row['native_vlan'])
                | parse_vlan_values(row['allowed_vlans'])
            )
            if vlan_number in interface_vlans:
                access_rows.append(dict(row))

        endpoint_details = vlan.get('endpoint_details') or []
        common = {
            '站点': site_label,
            'VLAN ID': vlan_number,
            'VLAN描述': str(vlan.get('description') or vlan.get('name') or ''),
            '网关': str(vlan.get('gateway') or ''),
            '网段': str(vlan.get('prefixes') or ''),
            '业务系统': str(vlan.get('business_systems') or ''),
            '业务部门': str(vlan.get('business_departments') or vlan.get('department') or ''),
            '负责人': str(vlan.get('business_owners') or vlan.get('owner') or ''),
            '接口采集时间': str(vlan.get('interface_collected_at') or ''),
            'ARP采集时间': str(vlan.get('arp_collected_at') or ''),
            'MAC采集时间': str(vlan.get('mac_collected_at') or ''),
        }

        def endpoint_text(device_hostname: str, interface_name: str) -> str:
            matching = [
                item for item in endpoint_details
                if str(item.get('device_hostname') or '') == device_hostname
                and (not interface_name or str(item.get('interface_name') or '') == interface_name)
            ]
            if not matching:
                matching = [
                    item for item in endpoint_details
                    if str(item.get('device_hostname') or '') == device_hostname
                ]
            values: list[str] = []
            for item in matching:
                ip = str(item.get('ip_address') or '').strip()
                mac = _format_mac_address(item.get('mac_address'))
                learned_interface = str(item.get('interface_name') or '').strip()
                source = str(item.get('source') or '').upper()
                value = ' / '.join(part for part in (ip, mac, learned_interface) if part)
                if value:
                    values.append(f'{source}: {value}' if source else value)
            return '; '.join(dict.fromkeys(values))

        for row in access_rows:
            device_hostname = str(row['device_hostname'] or '')
            interface_name = str(row['interface_name'] or '')
            export_rows.append({
                **common,
                '设备名称': device_hostname,
                '设备IP': str(row['device_ip'] or ''),
                '接入接口': interface_name,
                '接口描述': str(row['description'] or ''),
                'ARP/MAC信息': endpoint_text(device_hostname, interface_name),
            })

        if not access_rows:
            export_rows.append({
                **common,
                '设备名称': str(vlan.get('gateway_device') or ''),
                '设备IP': next(
                    (str(row['device_ip'] or '') for row in port_rows
                     if str(row['device_hostname'] or '') == str(vlan.get('gateway_device') or '')),
                    '',
                ),
                '接入接口': str(vlan.get('gateway_interface') or ''),
                '接口描述': str(vlan.get('description') or ''),
                'ARP/MAC信息': endpoint_text(str(vlan.get('gateway_device') or ''), ''),
            })
    return export_rows


def get_vlan(conn, vlan_pk: str) -> dict:
    row = conn.execute("SELECT * FROM vlans WHERE id = ?", (vlan_pk,)).fetchone()
    if not row:
        raise ValueError(f"VLAN not found: {vlan_pk}")
    return _row_to_dict(row)


def create_vlan(conn, *, vlan_id: int, name: str, site_id: str | None = None,
                status: str = 'active', tenant_id: str = _DEFAULT_TENANT) -> dict:
    if not (1 <= int(vlan_id) <= 4094):
        raise ValueError("vlan_id must be between 1 and 4094")
    # Uniqueness within a site (or globally when no site)
    if site_id:
        dup = conn.execute(
            "SELECT 1 FROM vlans WHERE site_id = ? AND vlan_id = ?", (site_id, vlan_id)
        ).fetchone()
        if dup:
            raise ValueError(f"VLAN {vlan_id} already exists in this site")
    pk = _new_id('vlan')
    conn.execute(
        "INSERT INTO vlans (id, vlan_id, name, site_id, status, tenant_id) VALUES (?, ?, ?, ?, ?, ?)",
        (pk, int(vlan_id), name, site_id, status, tenant_id or _DEFAULT_TENANT),
    )
    conn.commit()
    logger.info(f"[CmdbService] Created VLAN {vlan_id} ('{name}')")
    return get_vlan(conn, pk)


def update_vlan(conn, vlan_pk: str, **fields) -> dict:
    existing = get_vlan(conn, vlan_pk)
    if any(key in fields and fields[key] is not None for key in ('vlan_id', 'site_id')):
        target_vlan = int(fields.get('vlan_id', existing.get('vlan_id')))
        if not (1 <= target_vlan <= 4094):
            raise ValueError("vlan_id must be between 1 and 4094")
        target_site = fields.get('site_id', existing.get('site_id'))
        if target_site:
            dup = conn.execute(
                "SELECT 1 FROM vlans WHERE site_id = ? AND vlan_id = ? AND id != ?",
                (target_site, target_vlan, vlan_pk),
            ).fetchone()
            if dup:
                raise ValueError(f"VLAN {target_vlan} already exists in this site")
    updates, params = [], []
    for key in ('vlan_id', 'name', 'site_id', 'status', 'tenant_id'):
        if key in fields and fields[key] is not None:
            updates.append(f"{key} = ?")
            params.append(fields[key])
    if not updates:
        return get_vlan(conn, vlan_pk)
    params.append(vlan_pk)
    conn.execute(f"UPDATE vlans SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    return get_vlan(conn, vlan_pk)


def delete_vlan(conn, vlan_pk: str) -> None:
    vlan = get_vlan(conn, vlan_pk)
    refs = [
        ('prefixes', 'vlan_id', vlan_pk),
    ]
    try:
        access_cnt = _count_reference(conn, 'interfaces', 'access_vlan', str(vlan.get('vlan_id')))
    except Exception:
        access_cnt = 0
    if access_cnt > 0:
        raise ValueError(
            f"Cannot delete VLAN: interfaces.access_vlan={vlan.get('vlan_id')} ({access_cnt})"
        )
    _raise_if_referenced(conn, "VLAN", refs)
    conn.execute("DELETE FROM vlans WHERE id = ?", (vlan_pk,))
    conn.commit()
    logger.info(f"[CmdbService] Deleted VLAN {vlan_pk}")


# VLAN business ownership bindings

def list_vlan_business_bindings(
    conn,
    *,
    site_id: str = '',
    vrf_id: str = '',
    vlan_id: int | None = None,
) -> list[dict]:
    clauses = []
    params: list = []
    if site_id:
        clauses.append('b.site_id = ?')
        params.append(site_id)
    if vrf_id:
        clauses.append('b.vrf_id = ?')
        params.append(vrf_id)
    if vlan_id is not None:
        clauses.append('b.vlan_id = ?')
        params.append(int(vlan_id))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
    rows = conn.execute(
        f'''SELECT b.*, s.site_name, s.site_code, r.vrf_name,
                   v.name AS vlan_name, v.status AS vlan_status
            FROM vlan_business_bindings b
            LEFT JOIN sites s ON s.id = NULLIF(b.site_id, '')
            LEFT JOIN vrfs r ON r.id = NULLIF(b.vrf_id, '')
            LEFT JOIN vlans v ON v.vlan_id = b.vlan_id
                              AND COALESCE(v.site_id, '') = b.site_id
            {where}
            ORDER BY b.site_id, b.vrf_id, b.vlan_id, b.business_system''',
        tuple(params),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_vlan_business_binding(conn, binding_id: str) -> dict:
    row = conn.execute(
        'SELECT * FROM vlan_business_bindings WHERE id = ?', (binding_id,)
    ).fetchone()
    if not row:
        raise ValueError(f'VLAN business binding not found: {binding_id}')
    return _row_to_dict(row)


def _validate_binding_scope(conn, site_id: str, vrf_id: str) -> None:
    if site_id and not conn.execute('SELECT 1 FROM sites WHERE id = ?', (site_id,)).fetchone():
        raise ValueError(f'Site not found: {site_id}')
    if vrf_id and not conn.execute('SELECT 1 FROM vrfs WHERE id = ?', (vrf_id,)).fetchone():
        raise ValueError(f'VRF not found: {vrf_id}')


def _validate_binding_vlan(conn, site_id: str, vlan_id: int) -> None:
    """Require the business binding to point at a VLAN in the same site scope."""
    row = conn.execute(
        '''SELECT 1 FROM vlans
           WHERE vlan_id = ? AND COALESCE(site_id, '') = ?
           LIMIT 1''',
        (int(vlan_id), site_id),
    ).fetchone()
    if not row:
        scope = f' site {site_id}' if site_id else ' the global scope'
        raise ValueError(f'VLAN {vlan_id} does not exist in{scope}')


def _ensure_binding_unique(
    conn,
    *,
    site_id: str,
    vrf_id: str,
    vlan_id: int,
    business_system: str,
    exclude_id: str = '',
) -> None:
    row = conn.execute(
        '''SELECT id FROM vlan_business_bindings
           WHERE site_id = ? AND vrf_id = ? AND vlan_id = ?
             AND LOWER(business_system) = LOWER(?) AND id != ?''',
        (site_id, vrf_id, int(vlan_id), business_system, exclude_id),
    ).fetchone()
    if row:
        raise ValueError('The VLAN business binding already exists in this site/VRF scope')


def create_vlan_business_binding(conn, **fields) -> dict:
    site_id = str(fields.get('site_id') or '').strip()
    vrf_id = str(fields.get('vrf_id') or '').strip()
    vlan_id = int(fields.get('vlan_id'))
    business_system = str(fields.get('business_system') or '').strip()
    department = str(fields.get('department') or '').strip()
    owner = str(fields.get('owner') or '').strip()
    business_level = str(fields.get('business_level') or 'P3').strip().upper()
    status = str(fields.get('status') or 'active').strip().lower()
    description = str(fields.get('description') or '').strip()
    if not (1 <= vlan_id <= 4094):
        raise ValueError('vlan_id must be between 1 and 4094')
    if not business_system:
        raise ValueError('business_system is required')
    if business_level not in {'P1', 'P2', 'P3', 'P4'}:
        raise ValueError('business_level must be P1, P2, P3 or P4')
    if status not in {'active', 'planned', 'retired'}:
        raise ValueError('status must be active, planned or retired')
    _validate_binding_scope(conn, site_id, vrf_id)
    _validate_binding_vlan(conn, site_id, vlan_id)
    _ensure_binding_unique(
        conn,
        site_id=site_id,
        vrf_id=vrf_id,
        vlan_id=vlan_id,
        business_system=business_system,
    )
    now = _utc_now()
    binding_id = _new_id('vlan-biz')
    conn.execute(
        '''INSERT INTO vlan_business_bindings
           (id, site_id, vrf_id, vlan_id, business_system, department, owner,
            business_level, status, description, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (binding_id, site_id, vrf_id, vlan_id, business_system, department, owner,
         business_level, status, description, now, now),
    )
    conn.commit()
    return get_vlan_business_binding(conn, binding_id)


def update_vlan_business_binding(conn, binding_id: str, **fields) -> dict:
    existing = get_vlan_business_binding(conn, binding_id)
    merged = {**existing, **{key: value for key, value in fields.items() if value is not None}}
    site_id = str(merged.get('site_id') or '').strip()
    vrf_id = str(merged.get('vrf_id') or '').strip()
    vlan_id = int(merged.get('vlan_id'))
    business_system = str(merged.get('business_system') or '').strip()
    business_level = str(merged.get('business_level') or 'P3').strip().upper()
    status = str(merged.get('status') or 'active').strip().lower()
    if not (1 <= vlan_id <= 4094):
        raise ValueError('vlan_id must be between 1 and 4094')
    if not business_system:
        raise ValueError('business_system is required')
    if business_level not in {'P1', 'P2', 'P3', 'P4'}:
        raise ValueError('business_level must be P1, P2, P3 or P4')
    if status not in {'active', 'planned', 'retired'}:
        raise ValueError('status must be active, planned or retired')
    _validate_binding_scope(conn, site_id, vrf_id)
    _validate_binding_vlan(conn, site_id, vlan_id)
    _ensure_binding_unique(
        conn,
        site_id=site_id,
        vrf_id=vrf_id,
        vlan_id=vlan_id,
        business_system=business_system,
        exclude_id=binding_id,
    )
    conn.execute(
        '''UPDATE vlan_business_bindings
           SET site_id = ?, vrf_id = ?, vlan_id = ?, business_system = ?,
               department = ?, owner = ?, business_level = ?, status = ?,
               description = ?, updated_at = ?
           WHERE id = ?''',
        (site_id, vrf_id, vlan_id, business_system,
         str(merged.get('department') or '').strip(),
         str(merged.get('owner') or '').strip(), business_level, status,
         str(merged.get('description') or '').strip(), _utc_now(), binding_id),
    )
    conn.commit()
    return get_vlan_business_binding(conn, binding_id)


def delete_vlan_business_binding(conn, binding_id: str) -> None:
    get_vlan_business_binding(conn, binding_id)
    conn.execute('DELETE FROM vlan_business_bindings WHERE id = ?', (binding_id,))
    conn.commit()
