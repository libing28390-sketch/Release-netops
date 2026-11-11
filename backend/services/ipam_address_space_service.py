"""Explicit routing-domain identity for IPAM resources.

VRFs remain owned by the CMDB VRF catalog. This module adds a stable IPAM
identity around those VRFs and supports multiple independently confirmed
Global domains without deriving domain identity from site.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime, timezone

from database import get_db_connection
from services.audit_service import log_audit_event


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def lock_ipam_scope(
    conn,
    *,
    security_tenant_id: str,
    address_space_id: str | None = None,
    vrf_id: str | None = None,
) -> None:
    """Serialize writes that can claim the same address identity.

    Advisory keys are deterministic for the database server and include a
    namespace so other application locks cannot collide semantically.
    """
    tenant = str(security_tenant_id or 'tenant-default').strip() or 'tenant-default'
    address_space = str(address_space_id or '').strip()
    scope_key = (
        f"nexora:ipam:space:{tenant}:{address_space}"
        if address_space
        else f"nexora:ipam:legacy:{tenant}:{str(vrf_id or '').strip()}"
    )
    conn.execute(
        'SELECT pg_advisory_xact_lock(hashtextextended(?, 0))',
        (scope_key,),
    )


def _record(row) -> dict | None:
    return dict(row) if row else None


def _get_address_space(conn, address_space_id: str, security_tenant_id: str | None = None) -> dict | None:
    sql = """
        SELECT s.id, s.security_tenant_id, s.name, s.kind, s.vrf_id,
               v.vrf_name, s.status, s.revision, s.created_at, s.updated_at
          FROM ipam_address_spaces s
          LEFT JOIN vrfs v ON v.id = s.vrf_id
         WHERE s.id = ?
    """
    params: list = [address_space_id]
    if security_tenant_id is not None:
        sql += " AND s.security_tenant_id = ?"
        params.append(security_tenant_id)
    return _record(conn.execute(sql, tuple(params)).fetchone())


def list_address_spaces(
    *,
    security_tenant_id: str | None = None,
    include_inactive: bool = False,
) -> list[dict]:
    conn = get_db_connection()
    try:
        sql = """
            SELECT s.id, s.security_tenant_id, s.name, s.kind, s.vrf_id,
                   v.vrf_name, s.status, s.revision, s.created_at, s.updated_at
              FROM ipam_address_spaces s
              LEFT JOIN vrfs v ON v.id = s.vrf_id
             WHERE 1 = 1
        """
        params: list = []
        if security_tenant_id is not None:
            sql += " AND s.security_tenant_id = ?"
            params.append(security_tenant_id)
        if not include_inactive:
            sql += " AND s.status = 'active'"
        sql += " ORDER BY s.kind, lower(s.name), s.id"
        return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
    finally:
        conn.close()


def ensure_vrf_address_space(
    conn,
    *,
    vrf_id: str,
    security_tenant_id: str,
    name: str | None = None,
) -> dict:
    """Return/create the unique address space for a verified VRF identity."""
    vrf_key = str(vrf_id or '').strip()
    tenant_key = str(security_tenant_id or '').strip()
    if not vrf_key or not tenant_key:
        raise ValueError('VRF and security tenant are required to resolve an address space')

    vrf = conn.execute(
        "SELECT id, vrf_name, tenant_id FROM vrfs WHERE id = ?",
        (vrf_key,),
    ).fetchone()
    if not vrf:
        raise ValueError('VRF not found')
    if str(vrf['tenant_id'] or '') != tenant_key:
        raise ValueError('VRF does not belong to this security tenant')

    existing = conn.execute(
        "SELECT id, security_tenant_id FROM ipam_address_spaces WHERE vrf_id = ?",
        (vrf_key,),
    ).fetchone()
    if existing:
        if str(existing['security_tenant_id']) != tenant_key:
            raise ValueError('VRF is already mapped to a different security tenant')
        result = _get_address_space(conn, str(existing['id']), tenant_key)
        if not result:
            raise ValueError('VRF address-space mapping is inconsistent')
        return result

    space_name = str(name or vrf['vrf_name'] or f"VRF {vrf_key}").strip()
    if not space_name:
        space_name = f"VRF {vrf_key}"
    collision = conn.execute(
        """SELECT 1 FROM ipam_address_spaces
             WHERE security_tenant_id = ? AND lower(btrim(name)) = lower(btrim(?))
             LIMIT 1""",
        (tenant_key, space_name),
    ).fetchone()
    if collision:
        space_name = f"VRF {space_name} [{vrf_key}]"

    now = _utc_now()
    space_id = f"as-vrf:{vrf_key}"
    conn.execute(
        """INSERT INTO ipam_address_spaces
               (id, security_tenant_id, name, kind, vrf_id, status, revision, created_at, updated_at)
           VALUES (?, ?, ?, 'vrf', ?, 'active', 1, ?, ?)
           ON CONFLICT DO NOTHING""",
        (space_id, tenant_key, space_name, vrf_key, now, now),
    )
    result_row = conn.execute(
        "SELECT id, security_tenant_id FROM ipam_address_spaces WHERE vrf_id = ?",
        (vrf_key,),
    ).fetchone()
    if not result_row or str(result_row['security_tenant_id']) != tenant_key:
        raise ValueError('VRF address-space mapping could not be created')
    result = _get_address_space(conn, str(result_row['id']), tenant_key)
    if not result:
        raise ValueError('VRF address-space mapping could not be loaded')
    return result


def create_address_space(
    *,
    name: str,
    kind: str,
    vrf_id: str | None,
    security_tenant_id: str,
) -> dict:
    normalized_name = str(name or '').strip()
    normalized_kind = str(kind or '').strip().lower()
    tenant_key = str(security_tenant_id or '').strip()
    normalized_vrf_id = str(vrf_id or '').strip()
    if not tenant_key:
        raise ValueError('Security tenant is required')
    if not normalized_name:
        raise ValueError('Address-space name is required')
    if normalized_kind not in {'global', 'vrf'}:
        raise ValueError('Address-space kind must be global or vrf')
    if normalized_kind == 'global' and normalized_vrf_id:
        raise ValueError('Global address spaces must not reference a VRF')
    if normalized_kind == 'vrf' and not normalized_vrf_id:
        raise ValueError('VRF address spaces require a VRF')

    conn = get_db_connection()
    try:
        existing_name = conn.execute(
            """SELECT id FROM ipam_address_spaces
                 WHERE security_tenant_id = ?
                   AND lower(btrim(name)) = lower(btrim(?))
                 LIMIT 1""",
            (tenant_key, normalized_name),
        ).fetchone()
        if existing_name:
            raise ValueError('Address-space name already exists in this security tenant')
        if normalized_kind == 'vrf':
            # Explicit creation requests cannot silently reuse a pre-existing
            # mapping under a different display name. The caller can select
            # the existing mapping returned by GET instead.
            existing = conn.execute(
                'SELECT id FROM ipam_address_spaces WHERE vrf_id = ?',
                (normalized_vrf_id,),
            ).fetchone()
            if existing:
                raise ValueError('VRF already has an address-space mapping')
            space = ensure_vrf_address_space(
                conn,
                vrf_id=normalized_vrf_id,
                security_tenant_id=tenant_key,
                name=normalized_name,
            )
            conn.commit()
            return space

        now = _utc_now()
        space_id = f"as-global:{uuid.uuid4().hex}"
        conn.execute(
            """INSERT INTO ipam_address_spaces
                   (id, security_tenant_id, name, kind, vrf_id,
                    status, revision, created_at, updated_at)
               VALUES (?, ?, ?, 'global', NULL, 'active', 1, ?, ?)""",
            (space_id, tenant_key, normalized_name, now, now),
        )
        conn.commit()
        return _get_address_space(conn, space_id, tenant_key) or {}
    except Exception as exc:
        conn.rollback()
        if getattr(exc, 'sqlstate', '') == '23505':
            raise ValueError('Address-space identity or name already exists') from exc
        raise
    finally:
        conn.close()


def _count_addresses(conn, prefix_id: str) -> int:
    row = conn.execute(
        'SELECT COUNT(*) AS count FROM ip_addresses WHERE subnet_id = ?',
        (prefix_id,),
    ).fetchone()
    return int(row['count'] if row else 0)


def _addresses_in_network(conn, table: str, column: str, tenant_id: str, network) -> int:
    if table not in {'ipam_vips', 'ipam_dhcp_leases'} or column != 'address':
        return 0
    rows = conn.execute(
        f"SELECT {column} FROM {table} WHERE COALESCE(tenant_id, 'tenant-default') = ?",
        (tenant_id,),
    ).fetchall()
    count = 0
    for row in rows:
        try:
            address = ipaddress.ip_address(str(row[column] or '').strip())
        except ValueError:
            continue
        if address.version == network.version and address in network:
            count += 1
    return count


def _pool_range_details(pool: dict, owner_prefix: str) -> tuple[int, int, int] | None:
    try:
        network = ipaddress.ip_network(str(owner_prefix or ''), strict=False)
        start_text = str(pool.get('start_ip') or '').strip()
        end_text = str(pool.get('end_ip') or '').strip()
        if '/' in start_text or '/' in end_text:
            return None
        start = ipaddress.ip_address(start_text)
        end = ipaddress.ip_address(end_text)
    except ValueError:
        return None
    if (
        start.version != end.version
        or start.version != network.version
        or int(start) > int(end)
        or start not in network
        or end not in network
    ):
        return None
    return start.version, int(start), int(end)


def _pool_mapping_impact(conn, prefix, address_space_id: str) -> tuple[dict, list[dict[str, str]]]:
    prefix_id = str(prefix['id'])
    prefix_tenant = str(prefix['tenant_id'] or '').strip()
    rows = [
        dict(row)
        for row in conn.execute(
            """SELECT pool.id, pool.prefix_id, pool.tenant_id, pool.address_space_id,
                      pool.start_ip, pool.end_ip, pool.management_mode, pool.allocation_allowed,
                      owner.address_space_id AS owner_address_space_id,
                      owner.tenant_id AS owner_tenant_id, owner.prefix AS owner_prefix
                 FROM ipam_pools pool
                 JOIN prefixes owner ON owner.id = pool.prefix_id
                WHERE pool.prefix_id = ?
                ORDER BY pool.id""",
            (prefix_id,),
        ).fetchall()
    ]
    blockers: list[dict[str, str]] = []
    valid_current: list[tuple[dict, tuple[int, int, int]]] = []
    examples = [
        {
            'pool_id': str(row.get('id') or ''),
            'start_ip': str(row.get('start_ip') or ''),
            'end_ip': str(row.get('end_ip') or ''),
            'management_mode': row.get('management_mode'),
            'policy_pending': row.get('management_mode') is None or row.get('allocation_allowed') is None,
        }
        for row in rows[:5]
    ]
    for pool in rows:
        pool_id = str(pool.get('id') or '')
        pool_tenant = str(pool.get('tenant_id') or '').strip()
        owner_tenant = str(pool.get('owner_tenant_id') or '')
        if pool_tenant != prefix_tenant or owner_tenant != prefix_tenant:
            blockers.append({
                'code': 'pool_tenant_mismatch',
                'message': f'Pool {pool_id} tenant does not match its Prefix security tenant',
            })
            continue
        current_space = str(pool.get('address_space_id') or '').strip()
        owner_space = str(pool.get('owner_address_space_id') or '').strip()
        if current_space or owner_space:
            blockers.append({
                'code': 'pool_scope_inconsistent',
                'message': f'Pool {pool_id} already has an address-space mapping that must be reviewed',
            })
            continue
        range_details = _pool_range_details(pool, str(pool.get('owner_prefix') or ''))
        if not range_details:
            blockers.append({
                'code': 'pool_range_invalid',
                'message': f'Pool {pool_id} has an invalid range or range outside its Prefix',
            })
            continue
        valid_current.append((pool, range_details))

    for index, (pool, (family, start, end)) in enumerate(valid_current):
        for other_pool, (other_family, other_start, other_end) in valid_current[index + 1:]:
            if family == other_family and start <= other_end and other_start <= end:
                blockers.append({
                    'code': 'pool_range_overlap',
                    'message': f"Pools {pool.get('id')} and {other_pool.get('id')} overlap",
                })

    target_rows = conn.execute(
        """SELECT pool.id, pool.prefix_id, pool.tenant_id, pool.address_space_id,
                  pool.start_ip, pool.end_ip, owner.address_space_id AS owner_address_space_id,
                  owner.tenant_id AS owner_tenant_id, owner.prefix AS owner_prefix
             FROM ipam_pools pool
             JOIN prefixes owner ON owner.id = pool.prefix_id
            WHERE pool.prefix_id <> ?
              AND (pool.address_space_id = ? OR owner.address_space_id = ?)""",
        (prefix_id, address_space_id, address_space_id),
    ).fetchall()
    conflict_samples: list[dict[str, str]] = []
    for pool in valid_current:
        current_pool, (family, start, end) = pool
        for existing_row in target_rows:
            existing = dict(existing_row)
            existing_id = str(existing.get('id') or '')
            existing_tenant = str(existing.get('tenant_id') or '').strip()
            owner_tenant = str(existing.get('owner_tenant_id') or '')
            existing_space = str(existing.get('address_space_id') or '').strip()
            owner_space = str(existing.get('owner_address_space_id') or '').strip()
            if existing_tenant != prefix_tenant or owner_tenant != prefix_tenant:
                blockers.append({
                    'code': 'target_pool_tenant_mismatch',
                    'message': f'Target-space Pool {existing_id} has a tenant mismatch',
                })
                continue
            if existing_space and owner_space and existing_space != owner_space:
                blockers.append({
                    'code': 'target_pool_scope_inconsistent',
                    'message': f'Target-space Pool {existing_id} conflicts with its Prefix scope',
                })
                continue
            resolved_space = existing_space or owner_space
            if resolved_space != address_space_id:
                continue
            existing_range = _pool_range_details(existing, str(existing.get('owner_prefix') or ''))
            if not existing_range:
                blockers.append({
                    'code': 'target_pool_range_invalid',
                    'message': f'Target-space Pool {existing_id} has an invalid range',
                })
                continue
            other_family, other_start, other_end = existing_range
            if family == other_family and start <= other_end and other_start <= end:
                blockers.append({
                    'code': 'pool_range_overlap',
                    'message': f"Pool {current_pool.get('id')} overlaps target-space Pool {existing_id}",
                })
                if len(conflict_samples) < 5:
                    conflict_samples.append({
                        'pool_id': str(current_pool.get('id') or ''),
                        'conflicting_pool_id': existing_id,
                        'start_ip': str(current_pool.get('start_ip') or ''),
                        'end_ip': str(current_pool.get('end_ip') or ''),
                    })

    impact = {
        'pools': len(rows),
        'pools_to_map': sum(1 for pool, _ in valid_current if not pool.get('address_space_id')),
        'pool_samples': examples,
        'pool_conflicts': conflict_samples,
    }
    # Collapse duplicate blocker messages while keeping deterministic order.
    unique_blockers = []
    seen = set()
    for blocker in blockers:
        key = (blocker['code'], blocker['message'])
        if key not in seen:
            seen.add(key)
            unique_blockers.append(blocker)
    return impact, unique_blockers


def _prefix_resolution_preview(conn, prefix, address_space_id: str) -> dict:
    prefix_tenant = str(prefix['tenant_id'] or '').strip()
    if not prefix_tenant:
        return {
            'can_confirm': False,
            'target_space': None,
            'blockers': [{
                'code': 'prefix_tenant_unknown',
                'message': 'Prefix tenant is unknown; confirm its security tenant before mapping',
            }],
            'impact': {},
        }
    target = _get_address_space(
        conn, address_space_id, prefix_tenant
    )
    blockers: list[dict[str, str]] = []
    if not target:
        return {
            'can_confirm': False,
            'target_space': None,
            'blockers': [{
                'code': 'target_space_unavailable',
                'message': 'Target address space is missing or belongs to another tenant',
            }],
            'impact': {},
        }
    if target['status'] != 'active':
        blockers.append({'code': 'target_space_inactive', 'message': 'Target address space is inactive'})
    if str(prefix['address_space_id'] or '').strip():
        blockers.append({
            'code': 'prefix_already_mapped',
            'message': 'Prefix is already mapped; moving a mapped prefix requires a separate operation',
        })

    current_vrf = str(prefix['vrf_id'] or '').strip()
    target_vrf = str(target['vrf_id'] or '').strip()
    if current_vrf and current_vrf != target_vrf:
        blockers.append({'code': 'vrf_mismatch', 'message': 'Target address space does not match the Prefix VRF'})

    try:
        network = ipaddress.ip_network(str(prefix['prefix']), strict=False)
    except ValueError:
        network = None
        blockers.append({'code': 'invalid_prefix', 'message': 'Prefix CIDR is invalid'})

    duplicate_prefix = None
    if network is not None:
        duplicate_prefix = conn.execute(
            """SELECT id FROM prefixes
                 WHERE address_space_id = ? AND prefix_cidr = ? AND id <> ?
                 LIMIT 1""",
            (address_space_id, str(network), str(prefix['id'])),
        ).fetchone()
        if duplicate_prefix:
            blockers.append({
                'code': 'duplicate_prefix_cidr',
                'message': 'Target address space already has this CIDR',
            })

    address_count = _count_addresses(conn, str(prefix['id']))
    pool_impact, pool_blockers = _pool_mapping_impact(
        conn, prefix, address_space_id,
    )
    blockers.extend(pool_blockers)
    pool_count = int(pool_impact['pools'])
    vip_count = (
        _addresses_in_network(conn, 'ipam_vips', 'address', str(prefix['tenant_id'] or 'tenant-default'), network)
        if network is not None else 0
    )
    lease_count = (
        _addresses_in_network(conn, 'ipam_dhcp_leases', 'address', str(prefix['tenant_id'] or 'tenant-default'), network)
        if network is not None else 0
    )

    address_conflict_count = 0
    if network is not None and address_count:
        rows = conn.execute(
            """SELECT ip.address_inet
                 FROM ip_addresses ip
                WHERE ip.subnet_id = ?
                  AND ip.address_inet IS NOT NULL
                  AND COALESCE(ip.status, 'active') NOT IN ('released', 'available')""",
            (str(prefix['id']),),
        ).fetchall()
        for row in rows:
            conflict = conn.execute(
                """SELECT 1 FROM ip_addresses
                     WHERE address_space_id = ?
                       AND address_inet = ?
                       AND subnet_id <> ?
                       AND COALESCE(status, 'active') NOT IN ('released', 'available')
                     LIMIT 1""",
                (address_space_id, str(row['address_inet']), str(prefix['id'])),
            ).fetchone()
            address_conflict_count += int(bool(conflict))
        if address_conflict_count:
            blockers.append({
                'code': 'duplicate_active_ip',
                'message': 'Target address space already contains one or more active IP addresses in this Prefix',
            })

    return {
        'can_confirm': not blockers,
        'target_space': target,
        'blockers': blockers,
        'impact': {
            'ip_addresses': address_count,
            'pools': pool_count,
            'pools_to_map': pool_impact['pools_to_map'],
            'pool_samples': pool_impact['pool_samples'],
            'pool_conflicts': pool_impact['pool_conflicts'],
            'vips': vip_count,
            'leases': lease_count,
            'conflicting_active_addresses': address_conflict_count,
        },
    }


def preview_prefix_address_space(
    prefix_id: str,
    *,
    address_space_id: str,
    security_tenant_id: str | None = None,
) -> dict | None:
    conn = get_db_connection()
    try:
        prefix = conn.execute(
            'SELECT * FROM prefixes WHERE id = ?',
            (prefix_id,),
        ).fetchone()
        if not prefix:
            return None
        prefix_tenant = str(prefix['tenant_id'] or '').strip()
        if security_tenant_id is not None and prefix_tenant != str(security_tenant_id):
            return None
        result = _prefix_resolution_preview(conn, prefix, address_space_id)
        return {
            'prefix_id': prefix_id,
            'prefix': str(prefix['prefix'] or ''),
            'current_address_space_id': prefix['address_space_id'],
            'current_vrf_id': prefix['vrf_id'],
            'expected_updated_at': str(prefix['updated_at'] or ''),
            'expected_revision': int(prefix['revision'] or 1),
            **result,
        }
    finally:
        conn.close()


def resolve_prefix_address_space(
    prefix_id: str,
    *,
    address_space_id: str,
    expected_updated_at: str,
    confirmed: bool,
    security_tenant_id: str | None = None,
    expected_revision: int | None = None,
    audit_context: dict | None = None,
) -> dict:
    if not confirmed:
        raise ValueError('Explicit address-space confirmation is required')
    if not str(expected_updated_at or '').strip():
        raise ValueError('Prefix revision is required')
    conn = get_db_connection()
    try:
        initial = conn.execute(
            'SELECT * FROM prefixes WHERE id = ?',
            (prefix_id,),
        ).fetchone()
        if not initial:
            raise ValueError('Prefix not found')
        initial = dict(initial)
        prefix_tenant = str(initial['tenant_id'] or '').strip()
        if not prefix_tenant or (
            security_tenant_id is not None and prefix_tenant != str(security_tenant_id)
        ):
            raise ValueError('Prefix is not available in this security tenant')
        target = conn.execute(
            'SELECT id, security_tenant_id, kind, vrf_id, status FROM ipam_address_spaces WHERE id = ?',
            (address_space_id,),
        ).fetchone()
        if not target or str(target['security_tenant_id'] or '') != prefix_tenant:
            raise ValueError('Address space not found in this security tenant')
        scopes = {
            (
                prefix_tenant,
                str(initial.get('address_space_id') or '').strip(),
                str(initial.get('vrf_id') or '').strip(),
            ),
            (
                prefix_tenant,
                str(target['id'] or '').strip(),
                str(target['vrf_id'] or '').strip(),
            ),
        }
        for tenant_key, scope_id, scope_vrf_id in sorted(scopes):
            lock_ipam_scope(
                conn,
                security_tenant_id=tenant_key,
                address_space_id=scope_id,
                vrf_id=scope_vrf_id,
            )

        prefix = conn.execute(
            'SELECT * FROM prefixes WHERE id = ? FOR UPDATE',
            (prefix_id,),
        ).fetchone()
        if not prefix:
            raise ValueError('Prefix not found')
        prefix = dict(prefix)
        prefix_tenant = str(prefix['tenant_id'] or '').strip()
        if not prefix_tenant or (
            security_tenant_id is not None and prefix_tenant != str(security_tenant_id)
        ):
            raise ValueError('Prefix is not available in this security tenant')
        if (
            str(prefix['updated_at'] or '') != str(expected_updated_at)
            or (
                expected_revision is not None
                and int(prefix.get('revision') or 1) != int(expected_revision)
            )
            or str(prefix.get('address_space_id') or '') != str(initial.get('address_space_id') or '')
            or str(prefix.get('vrf_id') or '') != str(initial.get('vrf_id') or '')
        ):
            raise ValueError('Prefix changed after preview; refresh and review the mapping again')
        tenant_key = prefix_tenant
        locked_target = conn.execute(
            'SELECT id, security_tenant_id, kind, vrf_id, status FROM ipam_address_spaces WHERE id = ? FOR UPDATE',
            (address_space_id,),
        ).fetchone()
        if (
            not locked_target
            or str(locked_target['security_tenant_id'] or '') != tenant_key
            or str(locked_target['status'] or '') != 'active'
            or str(locked_target['vrf_id'] or '') != str(target['vrf_id'] or '')
        ):
            raise ValueError('Address-space mapping changed after preview; refresh and retry')
        preview = _prefix_resolution_preview(conn, prefix, address_space_id)
        if not preview['can_confirm']:
            raise ValueError('; '.join(item['message'] for item in preview['blockers']))

        target = preview['target_space']
        target_vrf = str(target['vrf_id'] or '')
        now = _utc_now()
        conn.execute(
            """UPDATE prefixes
                  SET address_space_id = ?, vrf_id = ?, updated_at = ?, revision = revision + 1
                WHERE id = ? AND address_space_id IS NULL""",
            (address_space_id, target_vrf or None, now, prefix_id),
        )
        conn.execute(
            """UPDATE ip_addresses
                  SET address_space_id = ?, vrf_id = ?, tenant_id = ?, site_id = ?,
                      updated_at = ?, revision = revision + 1
                WHERE subnet_id = ?""",
            (
                address_space_id, target_vrf, prefix_tenant,
                str(prefix['site_id'] or ''), now, prefix_id,
            ),
        )
        expected_pool_mappings = int(preview['impact'].get('pools_to_map') or 0)
        pool_update = conn.execute(
            """UPDATE ipam_pools
                  SET address_space_id = ?, updated_at = ?, revision = revision + 1
                WHERE prefix_id = ? AND address_space_id IS NULL AND tenant_id = ?""",
            (address_space_id, now, prefix_id, prefix_tenant),
        )
        mapped_pool_count = int(getattr(pool_update, 'rowcount', 0) or 0)
        if mapped_pool_count != expected_pool_mappings:
            raise ValueError('Pool rows changed after preview; refresh and review the mapping again')
        impact = dict(preview['impact'])
        impact['pools_mapped'] = mapped_pool_count
        result = {
            'ok': True,
            'prefix_id': prefix_id,
            'address_space_id': address_space_id,
            'address_space_name': target['name'],
            'vrf_id': target_vrf or None,
            'updated_at': now,
            'expected_revision': int(prefix.get('revision') or 1) + 1,
            'impact': impact,
        }
        if audit_context:
            log_audit_event(
                event_type='ipam.prefix.resolve_address_space',
                category='ipam',
                severity='warning',
                status='success',
                summary=f'Resolved address space for Prefix {prefix_id}',
                actor_id=audit_context.get('actor_id'),
                actor_username=audit_context.get('actor_username'),
                actor_role=audit_context.get('actor_role'),
                request_id=audit_context.get('request_id'),
                target_type='prefix',
                target_id=prefix_id,
                before=prefix,
                after=result,
                details={'address_space_id': address_space_id, 'impact': impact},
                conn=conn,
            )
        conn.commit()
        return result
    except Exception as exc:
        conn.rollback()
        if getattr(exc, 'sqlstate', '') == '23505':
            raise ValueError('Address-space resolution conflicts with an existing Prefix/IP identity')
        raise
    finally:
        conn.close()


def _prefix_address_space_move_preview(conn, prefix: dict, address_space_id: str) -> dict:
    tenant_id = str(prefix.get('tenant_id') or '').strip()
    source_space_id = str(prefix.get('address_space_id') or '').strip()
    if not tenant_id:
        return {
            'can_confirm': False,
            'target_space': None,
            'source_space': None,
            'blockers': [{'code': 'prefix_tenant_unknown', 'message': 'Prefix tenant is unknown'}],
            'impact': {},
        }

    source_space = _get_address_space(conn, source_space_id, tenant_id) if source_space_id else None
    target_space = _get_address_space(conn, address_space_id, tenant_id)
    blockers: list[dict[str, str]] = []
    if not source_space:
        blockers.append({'code': 'source_space_unavailable', 'message': 'Current address space is missing or belongs to another tenant'})
    if not target_space:
        return {
            'can_confirm': False,
            'target_space': None,
            'source_space': source_space,
            'blockers': blockers + [{'code': 'target_space_unavailable', 'message': 'Target address space is missing or belongs to another tenant'}],
            'impact': {},
        }
    if not source_space_id:
        blockers.append({'code': 'prefix_not_mapped', 'message': 'Only a mapped Prefix can be moved'})
    elif source_space_id == str(address_space_id or '').strip():
        blockers.append({'code': 'same_address_space', 'message': 'Prefix is already in the target address space'})
    if source_space and str(prefix.get('vrf_id') or '').strip() != str(source_space.get('vrf_id') or '').strip():
        blockers.append({'code': 'source_scope_inconsistent', 'message': 'Prefix VRF does not match its current address space'})
    if target_space.get('status') != 'active':
        blockers.append({'code': 'target_space_inactive', 'message': 'Target address space is inactive'})

    try:
        network = ipaddress.ip_network(str(prefix.get('prefix') or ''), strict=False)
    except ValueError:
        network = None
        blockers.append({'code': 'invalid_prefix', 'message': 'Prefix CIDR is invalid'})

    if network is not None:
        duplicate = conn.execute(
            """SELECT id FROM prefixes
                 WHERE address_space_id = ? AND prefix_cidr = ? AND id <> ?
                 LIMIT 1""",
            (address_space_id, str(network), str(prefix['id'])),
        ).fetchone()
        if duplicate:
            blockers.append({'code': 'duplicate_prefix_cidr', 'message': 'Target address space already has this CIDR'})

    address_rows = conn.execute(
        """SELECT id, address_inet, address_space_id, tenant_id, status
             FROM ip_addresses WHERE subnet_id = ? ORDER BY id""",
        (str(prefix['id']),),
    ).fetchall()
    address_conflicts = 0
    for row in address_rows:
        current_address_space = str(row['address_space_id'] or '').strip()
        current_tenant = str(row['tenant_id'] or '').strip()
        if current_address_space != source_space_id or current_tenant != tenant_id:
            blockers.append({
                'code': 'ip_scope_inconsistent',
                'message': f"Registered IP {row['id']} does not match the Prefix's current scope",
            })
            continue
        if row['address_inet'] is not None:
            collision = conn.execute(
                """SELECT 1 FROM ip_addresses
                     WHERE address_space_id = ? AND address_inet = ? AND id <> ?
                     LIMIT 1""",
                (address_space_id, str(row['address_inet']), str(row['id'])),
            ).fetchone()
            address_conflicts += int(bool(collision))
    if address_conflicts:
        blockers.append({
            'code': 'duplicate_target_ip',
            'message': 'Target address space already contains one or more registered IPs from this Prefix',
        })

    pool_count = int(conn.execute(
        'SELECT COUNT(*) FROM ipam_pools WHERE prefix_id = ?',
        (str(prefix['id']),),
    ).fetchone()[0])
    vip_count = (
        _addresses_in_network(conn, 'ipam_vips', 'address', tenant_id, network)
        if network is not None else 0
    )
    lease_count = (
        _addresses_in_network(conn, 'ipam_dhcp_leases', 'address', tenant_id, network)
        if network is not None else 0
    )
    if pool_count:
        blockers.append({'code': 'prefix_has_pools', 'message': 'Move the Prefix address pools in a separate reviewed operation first'})
    if vip_count:
        blockers.append({'code': 'prefix_has_vips', 'message': 'Review VIP address-space ownership before moving this Prefix'})
    if lease_count:
        blockers.append({'code': 'prefix_has_leases', 'message': 'Review DHCP lease address-space ownership before moving this Prefix'})

    return {
        'can_confirm': not blockers,
        'source_space': source_space,
        'target_space': target_space,
        'blockers': blockers,
        'impact': {
            'ip_addresses': len(address_rows),
            'pools': pool_count,
            'vips': vip_count,
            'leases': lease_count,
            'conflicting_addresses': address_conflicts,
        },
    }


def preview_prefix_address_space_move(
    prefix_id: str,
    *,
    address_space_id: str,
    security_tenant_id: str | None = None,
) -> dict | None:
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM prefixes WHERE id = ?', (prefix_id,)).fetchone()
        if not row:
            return None
        prefix = dict(row)
        tenant_id = str(prefix.get('tenant_id') or '').strip()
        if security_tenant_id is not None and tenant_id != str(security_tenant_id):
            return None
        return {
            'prefix_id': prefix_id,
            'prefix': str(prefix.get('prefix') or ''),
            'current_address_space_id': prefix.get('address_space_id'),
            'current_vrf_id': prefix.get('vrf_id'),
            'expected_updated_at': str(prefix.get('updated_at') or ''),
            'expected_revision': int(prefix.get('revision') or 1),
            **_prefix_address_space_move_preview(conn, prefix, address_space_id),
        }
    finally:
        conn.close()


def move_prefix_address_space(
    prefix_id: str,
    *,
    address_space_id: str,
    expected_updated_at: str,
    expected_revision: int,
    confirmed: bool,
    security_tenant_id: str | None = None,
    audit_context: dict | None = None,
) -> dict:
    if not confirmed:
        raise ValueError('Explicit address-space move confirmation is required')
    if not str(expected_updated_at or '').strip() or expected_revision < 1:
        raise ValueError('Prefix revision is required')
    conn = get_db_connection()
    try:
        initial_row = conn.execute('SELECT * FROM prefixes WHERE id = ?', (prefix_id,)).fetchone()
        if not initial_row:
            raise ValueError('Prefix not found')
        initial = dict(initial_row)
        tenant_id = str(initial.get('tenant_id') or '').strip()
        if not tenant_id or (security_tenant_id is not None and tenant_id != str(security_tenant_id)):
            raise ValueError('Prefix is not available in this security tenant')
        source_space_id = str(initial.get('address_space_id') or '').strip()
        if not source_space_id:
            raise ValueError('Only a mapped Prefix can be moved')
        source_space = _get_address_space(conn, source_space_id, tenant_id)
        target_space = _get_address_space(conn, address_space_id, tenant_id)
        if not source_space or not target_space:
            raise ValueError('Source or target address space is unavailable in this security tenant')

        scopes = {
            (tenant_id, source_space_id, str(source_space.get('vrf_id') or '').strip()),
            (tenant_id, str(address_space_id).strip(), str(target_space.get('vrf_id') or '').strip()),
        }
        for scope_tenant, scope_id, scope_vrf in sorted(scopes):
            lock_ipam_scope(conn, security_tenant_id=scope_tenant, address_space_id=scope_id, vrf_id=scope_vrf)

        prefix_row = conn.execute(
            'SELECT * FROM prefixes WHERE id = ? FOR UPDATE', (prefix_id,),
        ).fetchone()
        if not prefix_row:
            raise ValueError('Prefix not found')
        prefix = dict(prefix_row)
        if (
            str(prefix.get('updated_at') or '') != str(expected_updated_at)
            or int(prefix.get('revision') or 1) != int(expected_revision)
            or str(prefix.get('address_space_id') or '').strip() != source_space_id
            or str(prefix.get('vrf_id') or '').strip() != str(initial.get('vrf_id') or '').strip()
        ):
            raise ValueError('Prefix changed after preview; refresh and review the move again')
        locked_target = conn.execute(
            'SELECT id, security_tenant_id, kind, vrf_id, status FROM ipam_address_spaces WHERE id = ? FOR UPDATE',
            (address_space_id,),
        ).fetchone()
        if (
            not locked_target
            or str(locked_target['security_tenant_id'] or '') != tenant_id
            or str(locked_target['status'] or '') != 'active'
            or str(locked_target['vrf_id'] or '') != str(target_space.get('vrf_id') or '')
        ):
            raise ValueError('Target address space changed after preview; refresh and retry')
        address_rows = conn.execute(
            'SELECT id, revision FROM ip_addresses WHERE subnet_id = ? ORDER BY id FOR UPDATE',
            (prefix_id,),
        ).fetchall()
        preview = _prefix_address_space_move_preview(conn, prefix, address_space_id)
        if not preview['can_confirm']:
            raise ValueError('; '.join(item['message'] for item in preview['blockers']))

        target_vrf = str(target_space.get('vrf_id') or '')
        now = _utc_now()
        conn.execute(
            """UPDATE prefixes SET address_space_id = ?, vrf_id = ?, updated_at = ?, revision = revision + 1
                 WHERE id = ? AND address_space_id = ? AND revision = ?""",
            (address_space_id, target_vrf or None, now, prefix_id, source_space_id, expected_revision),
        )
        moved_addresses = conn.execute(
            """UPDATE ip_addresses
                  SET address_space_id = ?, vrf_id = ?, site_id = ?, updated_at = ?, revision = revision + 1
                WHERE subnet_id = ? AND address_space_id = ? AND tenant_id = ?""",
            (
                address_space_id, target_vrf, str(prefix.get('site_id') or ''), now,
                prefix_id, source_space_id, tenant_id,
            ),
        )
        moved_count = int(getattr(moved_addresses, 'rowcount', 0) or 0)
        if moved_count != len(address_rows):
            raise ValueError('Registered IP rows changed after preview; refresh and review the move again')

        result = {
            'ok': True,
            'prefix_id': prefix_id,
            'source_address_space_id': source_space_id,
            'address_space_id': address_space_id,
            'address_space_name': target_space['name'],
            'vrf_id': target_vrf or None,
            'updated_at': now,
            'expected_revision': expected_revision + 1,
            'impact': {**preview['impact'], 'ip_addresses_moved': moved_count},
        }
        if audit_context:
            log_audit_event(
                event_type='ipam.prefix.move_address_space',
                category='ipam',
                severity='warning',
                status='success',
                summary=f'Moved Prefix {prefix_id} to another address space',
                actor_id=audit_context.get('actor_id'),
                actor_username=audit_context.get('actor_username'),
                actor_role=audit_context.get('actor_role'),
                request_id=audit_context.get('request_id'),
                target_type='prefix',
                target_id=prefix_id,
                before=prefix,
                after=result,
                details={
                    'source_address_space_id': source_space_id,
                    'address_space_id': address_space_id,
                    'moved_ip_ids': [str(row['id']) for row in address_rows],
                    'impact': result['impact'],
                },
                conn=conn,
            )
        conn.commit()
        return result
    except Exception as exc:
        conn.rollback()
        if getattr(exc, 'sqlstate', '') == '23505':
            raise ValueError('Address-space move conflicts with an existing Prefix/IP identity') from exc
        raise
    finally:
        conn.close()


def _normalized_batch_prefix_ids(prefix_ids: list[str]) -> list[str]:
    normalized = [str(value or '').strip() for value in prefix_ids]
    if not normalized or any(not value for value in normalized):
        raise ValueError('At least one non-empty Prefix ID is required')
    if len(normalized) > 100:
        raise ValueError('At most 100 Prefixes can be mapped in one batch')
    if len(set(normalized)) != len(normalized):
        raise ValueError('Prefix IDs must not contain duplicates')
    return normalized


def _load_prefix_rows_for_batch(conn, prefix_ids: list[str], *, for_update: bool = False) -> dict[str, dict]:
    placeholders = ', '.join('?' for _ in prefix_ids)
    lock_clause = ' FOR UPDATE OF p' if for_update else ''
    rows = conn.execute(
        f'''SELECT p.*, s.site_name
              FROM prefixes p
              LEFT JOIN sites s ON s.id = p.site_id
             WHERE p.id IN ({placeholders})
             ORDER BY p.id{lock_clause}''',
        tuple(prefix_ids),
    ).fetchall()
    return {str(row['id']): dict(row) for row in rows}


def _prefix_address_space_batch_preview(
    conn,
    prefix_ids: list[str],
    address_space_id: str,
    *,
    security_tenant_id: str | None = None,
) -> dict:
    normalized_ids = _normalized_batch_prefix_ids(prefix_ids)
    normalized_space_id = str(address_space_id or '').strip()
    if not normalized_space_id:
        raise ValueError('Address-space ID is required')
    prefixes_by_id = _load_prefix_rows_for_batch(conn, normalized_ids)
    missing = [prefix_id for prefix_id in normalized_ids if prefix_id not in prefixes_by_id]
    if missing:
        raise ValueError(f'Selected Prefix not found: {missing[0]}')

    items_by_id: dict[str, dict] = {}
    for prefix_id in normalized_ids:
        prefix = prefixes_by_id[prefix_id]
        prefix_tenant = str(prefix.get('tenant_id') or '').strip()
        if security_tenant_id is not None and prefix_tenant != str(security_tenant_id):
            raise ValueError(f'Prefix {prefix_id} is not available in this security tenant')
        preview = _prefix_resolution_preview(conn, prefix, normalized_space_id)
        items_by_id[prefix_id] = {
            'prefix_id': prefix_id,
            'prefix': str(prefix.get('prefix') or ''),
            'site_name': str(prefix.get('site_name') or ''),
            'current_address_space_id': prefix.get('address_space_id'),
            'current_vrf_id': prefix.get('vrf_id'),
            'expected_updated_at': str(prefix.get('updated_at') or ''),
            'expected_revision': int(prefix.get('revision') or 1),
            'target_space': preview['target_space'],
            'impact': dict(preview.get('impact') or {}),
            'blockers': list(preview.get('blockers') or []),
            'can_confirm': bool(preview.get('can_confirm')),
        }

    # The single-Prefix preview cannot see another pending Prefix selected in
    # the same operation. Guard duplicate CIDRs and active host IPs across the
    # entire batch before allowing any scope write.
    prefixes_by_network: dict[str, list[str]] = {}
    for prefix_id in normalized_ids:
        try:
            network = ipaddress.ip_network(str(prefixes_by_id[prefix_id].get('prefix') or ''), strict=False)
        except ValueError:
            continue
        prefixes_by_network.setdefault(str(network), []).append(prefix_id)
    for network_text, matching_ids in prefixes_by_network.items():
        if len(matching_ids) < 2:
            continue
        duplicate_sites = sorted({
            str(prefixes_by_id[matching_id].get('site_name') or '').strip()
            for matching_id in matching_ids
            if str(prefixes_by_id[matching_id].get('site_name') or '').strip()
        })
        message = (
            f'Batch contains {len(matching_ids)} Prefix records for CIDR {network_text}; '
            'verify whether these are duplicate records or valid reuse across routing domains'
        )
        for prefix_id in matching_ids:
            items_by_id[prefix_id]['blockers'].append({
                'code': 'duplicate_prefix_cidr_in_batch',
                'message': message,
                'network': network_text,
                'duplicate_count': len(matching_ids),
                'sites': duplicate_sites,
            })

    id_placeholders = ', '.join('?' for _ in normalized_ids)
    active_ip_rows = conn.execute(
        f'''SELECT subnet_id, COALESCE(address_inet::text, address) AS address
              FROM ip_addresses
             WHERE subnet_id IN ({id_placeholders})
               AND COALESCE(status, 'active') NOT IN ('released', 'available')
               AND COALESCE(address_inet::text, address, '') <> ''
             ORDER BY address, subnet_id, id''',
        tuple(normalized_ids),
    ).fetchall()
    prefixes_by_address: dict[str, set[str]] = {}
    for row in active_ip_rows:
        try:
            canonical = str(ipaddress.ip_address(str(row['address'] or '').strip()))
        except ValueError:
            continue
        prefixes_by_address.setdefault(canonical, set()).add(str(row['subnet_id']))
    for address, matching_ids in prefixes_by_address.items():
        if len(matching_ids) < 2:
            continue
        message = f'Active IP {address} appears in more than one selected Prefix'
        for prefix_id in matching_ids:
            if prefix_id in items_by_id:
                items_by_id[prefix_id]['blockers'].append({
                    'code': 'duplicate_active_ip_in_batch',
                    'message': message,
                })

    # Pool ranges are unique across an address space, including when both
    # unscoped Pools are being mapped by this same batch.
    pool_rows = conn.execute(
        f'''SELECT pool.id, pool.prefix_id, pool.tenant_id, pool.address_space_id,
                   pool.start_ip, pool.end_ip, owner.prefix AS owner_prefix,
                   owner.tenant_id AS owner_tenant_id
              FROM ipam_pools pool
              JOIN prefixes owner ON owner.id = pool.prefix_id
             WHERE pool.prefix_id IN ({id_placeholders})
             ORDER BY pool.id''',
        tuple(normalized_ids),
    ).fetchall()
    valid_ranges: list[tuple[str, str, tuple[int, int, int]]] = []
    for raw_row in pool_rows:
        pool = dict(raw_row)
        prefix_id = str(pool.get('prefix_id') or '')
        if prefix_id not in items_by_id:
            continue
        prefix = prefixes_by_id[prefix_id]
        expected_tenant = str(prefix.get('tenant_id') or '').strip()
        if (
            str(pool.get('tenant_id') or '').strip() != expected_tenant
            or str(pool.get('owner_tenant_id') or '').strip() != expected_tenant
            or str(pool.get('address_space_id') or '').strip()
        ):
            continue
        details = _pool_range_details(pool, str(pool.get('owner_prefix') or ''))
        if details:
            valid_ranges.append((str(pool.get('id') or ''), prefix_id, details))
    for index, (pool_id, prefix_id, (family, start, end)) in enumerate(valid_ranges):
        for other_id, other_prefix_id, (other_family, other_start, other_end) in valid_ranges[index + 1:]:
            if prefix_id == other_prefix_id or family != other_family:
                continue
            if start <= other_end and other_start <= end:
                message = f'Pools {pool_id} and {other_id} overlap within the selected address-space batch'
                for affected_prefix_id in (prefix_id, other_prefix_id):
                    items_by_id[affected_prefix_id]['blockers'].append({
                        'code': 'pool_range_overlap_in_batch',
                        'message': message,
                    })

    items = [items_by_id[prefix_id] for prefix_id in normalized_ids]
    for item in items:
        # Keep deterministic blocker output if a row has multiple discovery paths.
        unique_blockers = []
        seen_blockers = set()
        for blocker in item['blockers']:
            key = (str(blocker.get('code') or ''), str(blocker.get('message') or ''))
            if key not in seen_blockers:
                seen_blockers.add(key)
                unique_blockers.append(blocker)
        item['blockers'] = unique_blockers
        item['can_confirm'] = not unique_blockers

    totals = {
        key: sum(int((item.get('impact') or {}).get(key) or 0) for item in items)
        for key in ('ip_addresses', 'pools', 'pools_to_map', 'vips', 'leases', 'conflicting_active_addresses')
    }
    blockers = [
        {'prefix_id': item['prefix_id'], 'prefix': item['prefix'], **blocker}
        for item in items
        for blocker in item['blockers']
    ]
    target_spaces = [item.get('target_space') for item in items if item.get('target_space')]
    target_space = target_spaces[0] if target_spaces and all(
        str(space.get('id') or '') == str(target_spaces[0].get('id') or '')
        for space in target_spaces
    ) else None
    return {
        'address_space_id': normalized_space_id,
        'target_space': target_space,
        'expected_target_revision': int(target_space.get('revision') or 1) if target_space else None,
        'selected_count': len(items),
        'can_confirm': bool(target_space) and all(item['can_confirm'] for item in items),
        'items': items,
        'totals': totals,
        'blockers': blockers,
    }


def preview_prefix_address_space_batch(
    prefix_ids: list[str],
    *,
    address_space_id: str,
    security_tenant_id: str | None = None,
) -> dict:
    conn = get_db_connection()
    try:
        return _prefix_address_space_batch_preview(
            conn,
            prefix_ids,
            address_space_id,
            security_tenant_id=security_tenant_id,
        )
    finally:
        conn.close()


def resolve_prefix_address_space_batch(
    items: list[dict],
    *,
    address_space_id: str,
    expected_target_revision: int,
    confirmed: bool,
    security_tenant_id: str | None = None,
    audit_context: dict | None = None,
) -> dict:
    if not confirmed:
        raise ValueError('Explicit address-space confirmation is required')
    normalized_space_id = str(address_space_id or '').strip()
    if not normalized_space_id:
        raise ValueError('Address-space ID is required')
    if not items or len(items) > 100:
        raise ValueError('Batch must contain between 1 and 100 Prefixes')
    item_by_id: dict[str, dict] = {}
    for item in items:
        prefix_id = str(item.get('prefix_id') or '').strip()
        expected_updated_at = str(item.get('expected_updated_at') or '').strip()
        expected_revision = item.get('expected_revision')
        if not prefix_id or not expected_updated_at or isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 1:
            raise ValueError('Each Prefix requires a valid ID, revision, and preview timestamp')
        if prefix_id in item_by_id:
            raise ValueError('Prefix items must not contain duplicates')
        item_by_id[prefix_id] = {
            'expected_updated_at': expected_updated_at,
            'expected_revision': expected_revision,
        }
    prefix_ids = list(item_by_id)

    conn = get_db_connection()
    try:
        initial = _load_prefix_rows_for_batch(conn, prefix_ids)
        missing = [prefix_id for prefix_id in prefix_ids if prefix_id not in initial]
        if missing:
            raise ValueError(f'Selected Prefix not found: {missing[0]}')
        tenants = {str(row.get('tenant_id') or '').strip() for row in initial.values()}
        if '' in tenants or len(tenants) != 1:
            raise ValueError('A batch must contain Prefixes from one known security tenant')
        tenant_key = next(iter(tenants))
        if security_tenant_id is not None and tenant_key != str(security_tenant_id):
            raise ValueError('Selected Prefixes are not available in this security tenant')
        initial_target = _get_address_space(conn, normalized_space_id, tenant_key)
        if not initial_target:
            raise ValueError('Address space not found in this security tenant')

        scopes = {
            (
                tenant_key,
                str(row.get('address_space_id') or '').strip(),
                str(row.get('vrf_id') or '').strip(),
            )
            for row in initial.values()
        }
        scopes.add((tenant_key, normalized_space_id, str(initial_target.get('vrf_id') or '').strip()))
        for scope_tenant, scope_space, scope_vrf in sorted(scopes):
            lock_ipam_scope(
                conn,
                security_tenant_id=scope_tenant,
                address_space_id=scope_space,
                vrf_id=scope_vrf,
            )

        locked = _load_prefix_rows_for_batch(conn, prefix_ids, for_update=True)
        for prefix_id in prefix_ids:
            prefix = locked.get(prefix_id)
            if not prefix:
                raise ValueError(f'Selected Prefix not found: {prefix_id}')
            before = initial[prefix_id]
            if (
                str(prefix.get('tenant_id') or '').strip() != tenant_key
                or str(prefix.get('address_space_id') or '') != str(before.get('address_space_id') or '')
                or str(prefix.get('vrf_id') or '') != str(before.get('vrf_id') or '')
            ):
                raise ValueError(f'Prefix {prefix_id} scope changed concurrently; refresh and retry')
            expected = item_by_id[prefix_id]
            if (
                str(prefix.get('updated_at') or '') != expected['expected_updated_at']
                or int(prefix.get('revision') or 1) != expected['expected_revision']
            ):
                raise ValueError(f'Prefix {prefix_id} revision is stale; refresh and retry')

        target = conn.execute(
            'SELECT id, security_tenant_id, name, kind, vrf_id, status, revision FROM ipam_address_spaces WHERE id = ? FOR UPDATE',
            (normalized_space_id,),
        ).fetchone()
        if (
            not target
            or str(target['security_tenant_id'] or '') != tenant_key
            or str(target['status'] or '') != 'active'
            or int(target['revision'] or 1) != int(expected_target_revision)
            or str(target['vrf_id'] or '') != str(initial_target.get('vrf_id') or '')
        ):
            raise ValueError('Address space changed after preview; refresh and review the batch again')

        preview = _prefix_address_space_batch_preview(
            conn,
            prefix_ids,
            normalized_space_id,
            security_tenant_id=tenant_key,
        )
        if not preview['can_confirm']:
            first = preview['blockers'][0] if preview['blockers'] else {}
            prefix_label = f"{first.get('prefix')} · " if first.get('prefix') else ''
            raise ValueError(f"{prefix_label}{first.get('message') or 'Batch address-space mapping is blocked'}")

        target_space = dict(target)
        now = _utc_now()
        preview_items = {item['prefix_id']: item for item in preview['items']}
        results = []
        for prefix_id in sorted(prefix_ids):
            prefix = locked[prefix_id]
            target_vrf = str(target_space.get('vrf_id') or '')
            update_prefix = conn.execute(
                """UPDATE prefixes
                      SET address_space_id = ?, vrf_id = ?, updated_at = ?, revision = revision + 1
                    WHERE id = ? AND address_space_id IS NULL AND revision = ?""",
                (
                    normalized_space_id,
                    target_vrf or None,
                    now,
                    prefix_id,
                    int(prefix.get('revision') or 1),
                ),
            )
            if int(getattr(update_prefix, 'rowcount', 0) or 0) != 1:
                raise ValueError(f'Prefix {prefix_id} changed after preview; refresh and retry')
            conn.execute(
                """UPDATE ip_addresses
                      SET address_space_id = ?, vrf_id = ?, tenant_id = ?, site_id = ?,
                          updated_at = ?, revision = revision + 1
                    WHERE subnet_id = ?""",
                (
                    normalized_space_id, target_vrf, tenant_key,
                    str(prefix.get('site_id') or ''), now, prefix_id,
                ),
            )
            expected_pool_mappings = int(preview_items[prefix_id]['impact'].get('pools_to_map') or 0)
            pool_update = conn.execute(
                """UPDATE ipam_pools
                      SET address_space_id = ?, updated_at = ?, revision = revision + 1
                    WHERE prefix_id = ? AND address_space_id IS NULL AND tenant_id = ?""",
                (normalized_space_id, now, prefix_id, tenant_key),
            )
            mapped_pool_count = int(getattr(pool_update, 'rowcount', 0) or 0)
            if mapped_pool_count != expected_pool_mappings:
                raise ValueError(f'Pool rows for Prefix {prefix_id} changed after preview; refresh and retry')

            item_impact = dict(preview_items[prefix_id].get('impact') or {})
            item_impact['pools_mapped'] = mapped_pool_count
            result = {
                'ok': True,
                'prefix_id': prefix_id,
                'address_space_id': normalized_space_id,
                'address_space_name': target_space['name'],
                'vrf_id': target_vrf or None,
                'updated_at': now,
                'expected_revision': int(prefix.get('revision') or 1) + 1,
                'impact': item_impact,
            }
            if audit_context:
                log_audit_event(
                    event_type='ipam.prefix.resolve_address_space',
                    category='ipam',
                    severity='warning',
                    status='success',
                    summary=f'Resolved address space for Prefix {prefix_id} in batch',
                    actor_id=audit_context.get('actor_id'),
                    actor_username=audit_context.get('actor_username'),
                    actor_role=audit_context.get('actor_role'),
                    request_id=audit_context.get('request_id'),
                    target_type='prefix',
                    target_id=prefix_id,
                    target_name=str(prefix.get('prefix') or ''),
                    before=prefix,
                    after=result,
                    details={
                        'address_space_id': normalized_space_id,
                        'batch_size': len(prefix_ids),
                        'impact': item_impact,
                    },
                    conn=conn,
                )
            results.append(result)

        conn.commit()
        totals = dict(preview.get('totals') or {})
        totals['pools_mapped'] = sum(int(result['impact'].get('pools_mapped') or 0) for result in results)
        return {
            'ok': True,
            'updated': len(results),
            'address_space_id': normalized_space_id,
            'address_space_name': target_space['name'],
            'vrf_id': str(target_space.get('vrf_id') or '') or None,
            'totals': totals,
            'items': results,
        }
    except Exception as exc:
        conn.rollback()
        if getattr(exc, 'sqlstate', '') == '23505':
            raise ValueError('Batch address-space mapping conflicts with an existing Prefix/IP identity')
        raise
    finally:
        conn.close()
