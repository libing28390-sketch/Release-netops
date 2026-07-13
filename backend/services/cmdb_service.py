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

logger = logging.getLogger(__name__)

_DEFAULT_TENANT = 'tenant-default'


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CMDB Network Skeleton
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def list_cmdb_devices(conn) -> list[dict]:
    """Return devices as CMDB skeleton nodes with asset and relationship counts."""
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
            pa.datacenter,
            pa.rack,
            pa.rack_unit,
            pa.management_ip,
            pa.business_ip,
            pa.lifecycle_status AS asset_lifecycle_status,
            (
                SELECT COUNT(*)
                FROM interfaces i
                WHERE i.device_id = d.id
            ) AS interface_count,
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
        ORDER BY COALESCE(d.hostname, ''), COALESCE(d.ip_address, '')
        """
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_cmdb_interfaces(conn) -> list[dict]:
    """Return interfaces as CMDB skeleton resources with device context."""
    rows = conn.execute(
        """
        SELECT
            i.id,
            i.device_id,
            d.hostname AS device_hostname,
            d.ip_address AS device_ip,
            d.platform AS device_platform,
            d.status AS device_status,
            i.interface_name,
            i.description,
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
        ORDER BY COALESCE(d.hostname, ''), COALESCE(i.interface_name, '')
        """
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


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

def list_sites(conn, tenant_id: str = '') -> list[dict]:
    if tenant_id:
        rows = conn.execute(
            "SELECT * FROM sites WHERE tenant_id = ? ORDER BY site_name", (tenant_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM sites ORDER BY site_name").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_site(conn, site_id: str) -> dict:
    row = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
    if not row:
        raise ValueError(f"Site not found: {site_id}")
    return _row_to_dict(row)


def create_site(conn, *, site_code: str, site_name: str, country: str = '',
                city: str = '', timezone: str = 'Asia/Shanghai', address: str = '',
                status: str = 'active', tenant_id: str = _DEFAULT_TENANT) -> dict:
    dup = conn.execute("SELECT 1 FROM sites WHERE site_code = ?", (site_code,)).fetchone()
    if dup:
        raise ValueError(f"Site code already exists: {site_code}")
    site_id = _new_id('site')
    conn.execute(
        """INSERT INTO sites (id, site_code, site_name, country, city, timezone, address, status, tenant_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (site_id, site_code, site_name, country, city, timezone, address, status, tenant_id or _DEFAULT_TENANT),
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
    for key in ('site_code', 'site_name', 'country', 'city', 'timezone', 'address', 'status', 'tenant_id'):
        if key in fields and fields[key] is not None:
            updates.append(f"{key} = ?")
            params.append(fields[key])
    if not updates:
        return get_site(conn, site_id)
    params.append(site_id)
    conn.execute(f"UPDATE sites SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    return get_site(conn, site_id)


def delete_site(conn, site_id: str) -> None:
    get_site(conn, site_id)
    site = get_site(conn, site_id)
    _raise_if_referenced(conn, "site", [
        ('devices', 'site_id', site_id),
        ('racks', 'site_id', site_id),
        ('vlans', 'site_id', site_id),
        ('prefixes', 'site_id', site_id),
    ])
    conn.execute("DELETE FROM sites WHERE id = ?", (site_id,))
    conn.commit()
    logger.info(f"[CmdbService] Deleted site {site_id} ({site.get('site_code')})")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VRFs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def list_vrfs(conn, tenant_id: str = '') -> list[dict]:
    if tenant_id:
        rows = conn.execute(
            "SELECT * FROM vrfs WHERE tenant_id = ? ORDER BY vrf_name", (tenant_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM vrfs ORDER BY vrf_name").fetchall()
    return [_row_to_dict(r) for r in rows]


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

def list_vlans(conn, site_id: str = '', tenant_id: str = '') -> list[dict]:
    clauses, params = [], []
    if site_id:
        clauses.append("site_id = ?")
        params.append(site_id)
    if tenant_id:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM vlans{where} ORDER BY vlan_id", params
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


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
