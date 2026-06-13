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
    # racks/vlans cascade via FK; warn if devices still reference the site by code
    site = get_site(conn, site_id)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM racks WHERE site_id = ?", (site_id,)
        ).fetchone()
        cnt = row['cnt'] if hasattr(row, 'keys') and 'cnt' in row.keys() else row[0]
        if cnt and cnt > 0:
            raise ValueError(f"Cannot delete site: {cnt} rack(s) still installed in it.")
    except ValueError:
        raise
    except Exception:
        pass
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
    dup = conn.execute("SELECT 1 FROM vrfs WHERE vrf_name = ?", (vrf_name,)).fetchone()
    if dup:
        raise ValueError(f"VRF name already exists: {vrf_name}")
    vrf_id = _new_id('vrf')
    conn.execute(
        "INSERT INTO vrfs (id, vrf_name, rd, description, tenant_id) VALUES (?, ?, ?, ?, ?)",
        (vrf_id, vrf_name, rd, description, tenant_id or _DEFAULT_TENANT),
    )
    conn.commit()
    logger.info(f"[CmdbService] Created VRF '{vrf_name}'")
    return get_vrf(conn, vrf_id)


def update_vrf(conn, vrf_id: str, **fields) -> dict:
    get_vrf(conn, vrf_id)
    if 'vrf_name' in fields and fields['vrf_name'] is not None:
        dup = conn.execute(
            "SELECT 1 FROM vrfs WHERE vrf_name = ? AND id != ?", (fields['vrf_name'], vrf_id)
        ).fetchone()
        if dup:
            raise ValueError(f"VRF name already exists: {fields['vrf_name']}")
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
    if 'vlan_id' in fields and fields['vlan_id'] is not None:
        if not (1 <= int(fields['vlan_id']) <= 4094):
            raise ValueError("vlan_id must be between 1 and 4094")
        target_site = fields.get('site_id', existing.get('site_id'))
        if target_site:
            dup = conn.execute(
                "SELECT 1 FROM vlans WHERE site_id = ? AND vlan_id = ? AND id != ?",
                (target_site, fields['vlan_id'], vlan_pk),
            ).fetchone()
            if dup:
                raise ValueError(f"VLAN {fields['vlan_id']} already exists in this site")
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
    get_vlan(conn, vlan_pk)
    conn.execute("DELETE FROM vlans WHERE id = ?", (vlan_pk,))
    conn.commit()
    logger.info(f"[CmdbService] Deleted VLAN {vlan_pk}")
