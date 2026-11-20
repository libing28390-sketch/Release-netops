"""NetBox-aligned IPAM native models: VLAN Groups, Route Targets, RIRs, Aggregates, and ASNs."""

from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection


_DEFAULT_TENANT = 'tenant-default'
_RT_PATTERN = re.compile(r'^[A-Za-z0-9._-]+:[0-9]+$')


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tenant(value: str | None) -> str:
    return str(value or '').strip() or _DEFAULT_TENANT


def _slugify(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', str(name or '').strip().lower()).strip('-') or 'item'


# ── VLAN Groups ───────────────────────────────────────────────────────────────

def list_vlan_groups(*, tenant_id: str | None = None, scope_id: str = '') -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        clauses = ['1 = 1']
        params: list[Any] = []
        if tenant_id:
            clauses.append('g.tenant_id = ?')
            params.append(_tenant(tenant_id))
        if scope_id:
            clauses.append('g.scope_id = ?')
            params.append(scope_id.strip())
        rows = conn.execute(
            f"""SELECT g.*,
                       (SELECT COUNT(*) FROM vlans v WHERE v.vlan_group_id = g.id) AS vlan_count
                  FROM ipam_vlan_groups g
                 WHERE {' AND '.join(clauses)}
                 ORDER BY g.name""",
            tuple(params),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_vlan_group(
    *,
    name: str,
    scope_type: str = '',
    scope_id: str = '',
    min_vid: int = 1,
    max_vid: int = 4094,
    description: str = '',
    tenant_id: str = _DEFAULT_TENANT,
) -> dict[str, Any]:
    clean_name = str(name or '').strip()
    if not clean_name:
        raise ValueError('VLAN Group name is required')
    clean_scope_type = str(scope_type or '').strip().lower()
    clean_scope_id = str(scope_id or '').strip()
    if clean_scope_type not in {'', 'site'}:
        raise ValueError('scope_type must be empty or site')
    if clean_scope_type == 'site' and not clean_scope_id:
        raise ValueError('scope_id is required when scope_type is site')
    if not (1 <= int(min_vid) <= int(max_vid) <= 4094):
        raise ValueError('VID range must satisfy 1 <= min_vid <= max_vid <= 4094')

    eff_tenant = _tenant(tenant_id)
    now = _utc_now()
    gid = f"vlg-{uuid.uuid4().hex[:12]}"
    conn = get_db_connection()
    try:
        if clean_scope_type == 'site':
            site = conn.execute(
                "SELECT id, COALESCE(tenant_id, 'tenant-default') AS tenant_id FROM sites WHERE id = ?",
                (clean_scope_id,),
            ).fetchone()
            if not site or str(site['tenant_id']) != eff_tenant:
                raise ValueError('Scoped site not found in this security tenant')
        dup = conn.execute(
            'SELECT id FROM ipam_vlan_groups WHERE tenant_id = ? AND lower(name) = lower(?)',
            (eff_tenant, clean_name),
        ).fetchone()
        if dup:
            raise ValueError(f'VLAN Group {clean_name} already exists')
        conn.execute(
            """INSERT INTO ipam_vlan_groups
               (id, name, slug, scope_type, scope_id, min_vid, max_vid, description, tenant_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                gid, clean_name, _slugify(clean_name), clean_scope_type, clean_scope_id,
                int(min_vid), int(max_vid), str(description or '').strip(), eff_tenant, now, now,
            ),
        )
        conn.commit()
        row = conn.execute('SELECT * FROM ipam_vlan_groups WHERE id = ?', (gid,)).fetchone()
        return dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def assign_vlan_to_group(vlan_pk: str, group_id: str | None, *, tenant_id: str = _DEFAULT_TENANT) -> dict[str, Any]:
    eff_tenant = _tenant(tenant_id)
    conn = get_db_connection()
    try:
        vlan = conn.execute('SELECT * FROM vlans WHERE id = ?', (vlan_pk,)).fetchone()
        if not vlan or _tenant(vlan['tenant_id']) != eff_tenant:
            raise LookupError(f'VLAN not found: {vlan_pk}')
        if group_id:
            group = conn.execute('SELECT * FROM ipam_vlan_groups WHERE id = ?', (group_id,)).fetchone()
            if not group or _tenant(group['tenant_id']) != eff_tenant:
                raise ValueError(f'VLAN Group not found: {group_id}')
            vid = int(vlan['vlan_id'])
            if not (int(group['min_vid']) <= vid <= int(group['max_vid'])):
                raise ValueError(
                    f"VLAN {vid} is outside VLAN Group {group['name']} range ({group['min_vid']}-{group['max_vid']})"
                )
            if group['scope_type'] == 'site' and str(vlan['site_id'] or '') and str(vlan['site_id']) != str(group['scope_id']):
                raise ValueError('VLAN site does not match the VLAN Group site scope')
            dup = conn.execute(
                'SELECT id FROM vlans WHERE vlan_group_id = ? AND vlan_id = ? AND id <> ?',
                (group_id, vid, vlan_pk),
            ).fetchone()
            if dup:
                raise ValueError(f'VLAN {vid} already exists in VLAN Group {group["name"]}')
        conn.execute('UPDATE vlans SET vlan_group_id = ? WHERE id = ?', (group_id or None, vlan_pk))
        conn.commit()
        updated = conn.execute('SELECT * FROM vlans WHERE id = ?', (vlan_pk,)).fetchone()
        return dict(updated)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_vlan_group(group_id: str, *, tenant_id: str = _DEFAULT_TENANT) -> bool:
    eff_tenant = _tenant(tenant_id)
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT id FROM ipam_vlan_groups WHERE id = ? AND tenant_id = ?',
            (group_id, eff_tenant),
        ).fetchone()
        if not row:
            return False
        conn.execute('DELETE FROM ipam_vlan_groups WHERE id = ?', (group_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Route Targets & VRF import/export ─────────────────────────────────────────

def list_route_targets(*, tenant_id: str | None = None) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        if tenant_id:
            rows = conn.execute(
                'SELECT * FROM ipam_route_targets WHERE tenant_id = ? ORDER BY name',
                (_tenant(tenant_id),),
            ).fetchall()
        else:
            rows = conn.execute('SELECT * FROM ipam_route_targets ORDER BY name').fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_route_target(
    *,
    name: str,
    description: str = '',
    tenant_id: str = _DEFAULT_TENANT,
) -> dict[str, Any]:
    clean_name = str(name or '').strip()
    if not clean_name or not _RT_PATTERN.match(clean_name):
        raise ValueError('Route Target must follow ASN:nn or IP:nn format (e.g. 65001:100)')
    eff_tenant = _tenant(tenant_id)
    now = _utc_now()
    rt_id = f"rt-{uuid.uuid4().hex[:12]}"
    conn = get_db_connection()
    try:
        dup = conn.execute(
            'SELECT id FROM ipam_route_targets WHERE tenant_id = ? AND lower(name) = lower(?)',
            (eff_tenant, clean_name),
        ).fetchone()
        if dup:
            raise ValueError(f'Route Target {clean_name} already exists')
        conn.execute(
            """INSERT INTO ipam_route_targets (id, name, description, tenant_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rt_id, clean_name, str(description or '').strip(), eff_tenant, now, now),
        )
        conn.commit()
        row = conn.execute('SELECT * FROM ipam_route_targets WHERE id = ?', (rt_id,)).fetchone()
        return dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_route_target(rt_id: str, *, tenant_id: str = _DEFAULT_TENANT) -> bool:
    eff_tenant = _tenant(tenant_id)
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT id FROM ipam_route_targets WHERE id = ? AND tenant_id = ?',
            (rt_id, eff_tenant),
        ).fetchone()
        if not row:
            return False
        conn.execute('DELETE FROM ipam_route_targets WHERE id = ?', (rt_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_vrf_route_targets(vrf_id: str, *, tenant_id: str | None = None) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        vrf = conn.execute('SELECT id, vrf_name, tenant_id FROM vrfs WHERE id = ?', (vrf_id,)).fetchone()
        if not vrf or (tenant_id is not None and _tenant(vrf['tenant_id']) != _tenant(tenant_id)):
            raise LookupError(f'VRF not found: {vrf_id}')
        rows = conn.execute(
            """SELECT link.direction, rt.id, rt.name, rt.description
                 FROM ipam_vrf_route_targets link
                 JOIN ipam_route_targets rt ON rt.id = link.route_target_id
                WHERE link.vrf_id = ?
                ORDER BY link.direction, rt.name""",
            (vrf_id,),
        ).fetchall()
        imports = [dict(r) for r in rows if r['direction'] == 'import']
        exports = [dict(r) for r in rows if r['direction'] == 'export']
        return {'vrf_id': vrf_id, 'vrf_name': vrf['vrf_name'], 'import_targets': imports, 'export_targets': exports}
    finally:
        conn.close()


def set_vrf_route_targets(
    vrf_id: str,
    *,
    import_target_ids: list[str],
    export_target_ids: list[str],
    tenant_id: str = _DEFAULT_TENANT,
) -> dict[str, Any]:
    eff_tenant = _tenant(tenant_id)
    imp_ids = sorted({str(x).strip() for x in (import_target_ids or []) if str(x).strip()})
    exp_ids = sorted({str(x).strip() for x in (export_target_ids or []) if str(x).strip()})
    all_ids = sorted(set(imp_ids) | set(exp_ids))
    conn = get_db_connection()
    try:
        vrf = conn.execute('SELECT id, vrf_name, tenant_id FROM vrfs WHERE id = ?', (vrf_id,)).fetchone()
        if not vrf or _tenant(vrf['tenant_id']) != eff_tenant:
            raise LookupError(f'VRF not found: {vrf_id}')
        if all_ids:
            marks = ','.join('?' for _ in all_ids)
            found = conn.execute(
                f'SELECT id FROM ipam_route_targets WHERE tenant_id = ? AND id IN ({marks})',
                (eff_tenant, *all_ids),
            ).fetchall()
            if len(found) != len(all_ids):
                raise ValueError('One or more Route Targets do not exist in this security tenant')
        now = _utc_now()
        conn.execute('DELETE FROM ipam_vrf_route_targets WHERE vrf_id = ?', (vrf_id,))
        for rt_id in imp_ids:
            conn.execute(
                "INSERT INTO ipam_vrf_route_targets (vrf_id, route_target_id, direction, created_at) VALUES (?, ?, 'import', ?)",
                (vrf_id, rt_id, now),
            )
        for rt_id in exp_ids:
            conn.execute(
                "INSERT INTO ipam_vrf_route_targets (vrf_id, route_target_id, direction, created_at) VALUES (?, ?, 'export', ?)",
                (vrf_id, rt_id, now),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_vrf_route_targets(vrf_id, tenant_id=eff_tenant)


# ── RIRs, Aggregates & ASNs ───────────────────────────────────────────────────

def list_rirs(*, tenant_id: str | None = None) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        if tenant_id:
            rows = conn.execute(
                """SELECT r.*,
                          (SELECT COUNT(*) FROM ipam_aggregates a WHERE a.rir_id = r.id) AS aggregate_count,
                          (SELECT COUNT(*) FROM ipam_asns n WHERE n.rir_id = r.id) AS asn_count
                     FROM ipam_rirs r
                    WHERE r.tenant_id = ?
                    ORDER BY r.name""",
                (_tenant(tenant_id),),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT r.*,
                          (SELECT COUNT(*) FROM ipam_aggregates a WHERE a.rir_id = r.id) AS aggregate_count,
                          (SELECT COUNT(*) FROM ipam_asns n WHERE n.rir_id = r.id) AS asn_count
                     FROM ipam_rirs r
                    ORDER BY r.name"""
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_rir(
    *,
    name: str,
    is_private: bool = False,
    description: str = '',
    tenant_id: str = _DEFAULT_TENANT,
) -> dict[str, Any]:
    clean_name = str(name or '').strip()
    if not clean_name:
        raise ValueError('RIR name is required')
    eff_tenant = _tenant(tenant_id)
    now = _utc_now()
    rir_id = f"rir-{uuid.uuid4().hex[:12]}"
    conn = get_db_connection()
    try:
        dup = conn.execute(
            'SELECT id FROM ipam_rirs WHERE tenant_id = ? AND lower(name) = lower(?)',
            (eff_tenant, clean_name),
        ).fetchone()
        if dup:
            raise ValueError(f'RIR {clean_name} already exists')
        conn.execute(
            """INSERT INTO ipam_rirs (id, name, slug, is_private, description, tenant_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rir_id, clean_name, _slugify(clean_name), bool(is_private), str(description or '').strip(), eff_tenant, now, now),
        )
        conn.commit()
        row = conn.execute('SELECT * FROM ipam_rirs WHERE id = ?', (rir_id,)).fetchone()
        return dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_rir(rir_id: str, *, tenant_id: str = _DEFAULT_TENANT) -> bool:
    eff_tenant = _tenant(tenant_id)
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT id FROM ipam_rirs WHERE id = ? AND tenant_id = ?',
            (rir_id, eff_tenant),
        ).fetchone()
        if not row:
            return False
        agg = conn.execute('SELECT id FROM ipam_aggregates WHERE rir_id = ? LIMIT 1', (rir_id,)).fetchone()
        if agg:
            raise ValueError('Cannot delete RIR while Aggregates reference it')
        asn = conn.execute('SELECT id FROM ipam_asns WHERE rir_id = ? LIMIT 1', (rir_id,)).fetchone()
        if asn:
            raise ValueError('Cannot delete RIR while ASNs reference it')
        conn.execute('DELETE FROM ipam_rirs WHERE id = ?', (rir_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_aggregates(*, tenant_id: str | None = None, rir_id: str = '') -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        clauses = ['1 = 1']
        params: list[Any] = []
        if tenant_id:
            clauses.append('a.tenant_id = ?')
            params.append(_tenant(tenant_id))
        if rir_id:
            clauses.append('a.rir_id = ?')
            params.append(rir_id.strip())
        rows = conn.execute(
            f"""SELECT a.id, a.prefix, a.ip_version, a.rir_id, r.name AS rir_name,
                       a.date_added, a.description, a.tenant_id, a.created_at, a.updated_at
                  FROM ipam_aggregates a
                  JOIN ipam_rirs r ON r.id = a.rir_id
                 WHERE {' AND '.join(clauses)}
                 ORDER BY a.prefix_cidr""",
            tuple(params),
        ).fetchall()
        items = [dict(r) for r in rows]
        for item in items:
            cnt = conn.execute(
                """SELECT COUNT(*) AS cnt FROM prefixes
                    WHERE COALESCE(tenant_id, 'tenant-default') = ?
                      AND prefix_cidr <<= CAST(? AS cidr)""",
                (item['tenant_id'], item['prefix']),
            ).fetchone()
            item['child_prefix_count'] = int(cnt['cnt'] if cnt else 0)
        return items
    finally:
        conn.close()


def create_aggregate(
    *,
    prefix: str,
    rir_id: str,
    date_added: str = '',
    description: str = '',
    tenant_id: str = _DEFAULT_TENANT,
) -> dict[str, Any]:
    try:
        net = ipaddress.ip_network(str(prefix or '').strip(), strict=False)
    except ValueError as exc:
        raise ValueError(f'Invalid Aggregate CIDR: {prefix}') from exc
    canonical = str(net)
    eff_tenant = _tenant(tenant_id)
    now = _utc_now()
    agg_id = f"agg-{uuid.uuid4().hex[:12]}"
    conn = get_db_connection()
    try:
        rir = conn.execute(
            'SELECT id, name FROM ipam_rirs WHERE id = ? AND tenant_id = ?',
            (str(rir_id or '').strip(), eff_tenant),
        ).fetchone()
        if not rir:
            raise ValueError('RIR not found in this security tenant')
        existing_rows = conn.execute(
            'SELECT id, prefix FROM ipam_aggregates WHERE tenant_id = ? AND ip_version = ?',
            (eff_tenant, net.version),
        ).fetchall()
        for existing in existing_rows:
            existing_net = ipaddress.ip_network(existing['prefix'], strict=False)
            if existing_net.overlaps(net):
                raise ValueError(f'Aggregate {canonical} overlaps existing Aggregate {existing["prefix"]}')
        conn.execute(
            """INSERT INTO ipam_aggregates
               (id, prefix, prefix_cidr, ip_version, rir_id, date_added, description, tenant_id, created_at, updated_at)
               VALUES (?, ?, CAST(? AS cidr), ?, ?, ?, ?, ?, ?, ?)""",
            (agg_id, canonical, canonical, net.version, rir['id'], str(date_added or '').strip(), str(description or '').strip(), eff_tenant, now, now),
        )
        conn.commit()
        row = conn.execute(
            """SELECT a.id, a.prefix, a.ip_version, a.rir_id, r.name AS rir_name,
                      a.date_added, a.description, a.tenant_id, a.created_at, a.updated_at
                 FROM ipam_aggregates a JOIN ipam_rirs r ON r.id = a.rir_id
                WHERE a.id = ?""",
            (agg_id,),
        ).fetchone()
        return dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_aggregate(aggregate_id: str, *, tenant_id: str = _DEFAULT_TENANT) -> bool:
    eff_tenant = _tenant(tenant_id)
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT id FROM ipam_aggregates WHERE id = ? AND tenant_id = ?',
            (aggregate_id, eff_tenant),
        ).fetchone()
        if not row:
            return False
        conn.execute('DELETE FROM ipam_aggregates WHERE id = ?', (aggregate_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_asns(*, tenant_id: str | None = None, rir_id: str = '') -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        clauses = ['1 = 1']
        params: list[Any] = []
        if tenant_id:
            clauses.append('n.tenant_id = ?')
            params.append(_tenant(tenant_id))
        if rir_id:
            clauses.append('n.rir_id = ?')
            params.append(rir_id.strip())
        rows = conn.execute(
            f"""SELECT n.*, r.name AS rir_name, s.site_name
                  FROM ipam_asns n
                  JOIN ipam_rirs r ON r.id = n.rir_id
                  LEFT JOIN sites s ON s.id = n.site_id
                 WHERE {' AND '.join(clauses)}
                 ORDER BY n.asn""",
            tuple(params),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_asn(
    *,
    asn: int,
    rir_id: str,
    site_id: str | None = None,
    description: str = '',
    tenant_id: str = _DEFAULT_TENANT,
) -> dict[str, Any]:
    asn_num = int(asn)
    if not (1 <= asn_num <= 4294967295):
        raise ValueError('ASN must be between 1 and 4294967295')
    eff_tenant = _tenant(tenant_id)
    now = _utc_now()
    asn_id = f"asn-{uuid.uuid4().hex[:12]}"
    conn = get_db_connection()
    try:
        rir = conn.execute(
            'SELECT id FROM ipam_rirs WHERE id = ? AND tenant_id = ?',
            (str(rir_id or '').strip(), eff_tenant),
        ).fetchone()
        if not rir:
            raise ValueError('RIR not found in this security tenant')
        clean_site = str(site_id or '').strip() or None
        if clean_site:
            site = conn.execute(
                "SELECT id, COALESCE(tenant_id, 'tenant-default') AS tenant_id FROM sites WHERE id = ?",
                (clean_site,),
            ).fetchone()
            if not site or str(site['tenant_id']) != eff_tenant:
                raise ValueError('Site not found in this security tenant')
        dup = conn.execute(
            'SELECT id FROM ipam_asns WHERE tenant_id = ? AND asn = ?',
            (eff_tenant, asn_num),
        ).fetchone()
        if dup:
            raise ValueError(f'ASN {asn_num} already exists')
        conn.execute(
            """INSERT INTO ipam_asns (id, asn, rir_id, site_id, description, tenant_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (asn_id, asn_num, rir['id'], clean_site, str(description or '').strip(), eff_tenant, now, now),
        )
        conn.commit()
        row = conn.execute(
            """SELECT n.*, r.name AS rir_name, s.site_name
                 FROM ipam_asns n
                 JOIN ipam_rirs r ON r.id = n.rir_id
                 LEFT JOIN sites s ON s.id = n.site_id
                WHERE n.id = ?""",
            (asn_id,),
        ).fetchone()
        return dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_asn(asn_id: str, *, tenant_id: str = _DEFAULT_TENANT) -> bool:
    eff_tenant = _tenant(tenant_id)
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT id FROM ipam_asns WHERE id = ? AND tenant_id = ?',
            (asn_id, eff_tenant),
        ).fetchone()
        if not row:
            return False
        conn.execute('DELETE FROM ipam_asns WHERE id = ?', (asn_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
