"""
IPAM Service — Business logic for IP/VLAN resource management.
Provides subnet and IP address CRUD with validation, overlap detection, and conflict scanning.
Extended with hierarchy tree, VRF-scoped uniqueness, pool/VIP/lease CRUD, and active endpoints.
"""

import uuid
import ipaddress
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from database import get_db_connection, _USE_PG

logger = logging.getLogger(__name__)

_GROUP_CONCAT = 'STRING_AGG({col}, \',\')' if _USE_PG else 'GROUP_CONCAT({col})'
_PH = '%s' if _USE_PG else '?'

ADDRESS_STATUSES = {
    'available', 'reserved', 'allocated', 'active', 'dhcp', 'vip',
    'deprecated', 'released', 'quarantine',
}
PREFIX_STATUSES = {'container', 'active', 'reserved', 'deprecated'}
ADDRESS_TRANSITIONS = {
    'available': {'reserved', 'allocated', 'dhcp', 'vip', 'quarantine'},
    'reserved': {'allocated', 'released', 'deprecated', 'quarantine'},
    'allocated': {'released', 'deprecated', 'quarantine'},
    'active': {'released', 'deprecated', 'quarantine'},
    'dhcp': {'released', 'deprecated', 'quarantine'},
    'vip': {'released', 'deprecated', 'quarantine'},
    'deprecated': {'released', 'quarantine'},
    'released': {'available', 'reserved', 'allocated', 'quarantine'},
    'quarantine': {'available', 'released'},
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _table_columns(conn, table: str) -> set[str]:
    cursor = conn.execute(f"SELECT * FROM {table} WHERE 1 = 0")
    return {column[0] for column in (cursor.description or [])}


def _ip_in_subnet(addr: str, network: str, prefix_len: int) -> bool:
    """Check whether *addr* falls within the given CIDR block."""
    try:
        net = ipaddress.ip_network(f"{network}/{prefix_len}", strict=False)
        return ipaddress.ip_address(addr) in net
    except ValueError:
        return False


def _calculate_total_ips(prefix_str: str) -> int:
    """Calculate usable IPs for a CIDR prefix string like '10.1.0.0/24'."""
    try:
        net = ipaddress.ip_network(prefix_str, strict=False)
    except ValueError:
        return 0
    if net.version == 4:
        pl = net.prefixlen
        if pl == 32:
            return 1
        if pl == 31:
            return 2
        return max(0, (2 ** (32 - pl)) - 2)
    else:
        pl = net.prefixlen
        if pl == 128:
            return 1
        if pl == 127:
            return 2
        total = max(0, (2 ** (128 - pl)) - 2)
        return min(total, 2**63)


def _normalize_prefix(prefix: str) -> tuple[str, ipaddress._BaseNetwork]:
    try:
        net = ipaddress.ip_network(prefix, strict=False)
    except ValueError as exc:
        raise ValueError(f"Invalid CIDR: {exc}") from exc
    return str(net), net


def _normalize_address(address: str) -> str:
    try:
        return str(ipaddress.ip_address(str(address).split('/')[0].strip()))
    except ValueError as exc:
        raise ValueError(f"Invalid IP address: {exc}") from exc


def _prefix_scope(row_or_fields: dict) -> tuple[str, str, str]:
    return (
        row_or_fields.get('tenant_id') or 'tenant-default',
        row_or_fields.get('vrf_id') or '',
        row_or_fields.get('site_id') or '',
    )


def _validate_prefix_status(status: str) -> str:
    normalized = (status or 'active').strip().lower()
    if normalized not in PREFIX_STATUSES:
        raise ValueError(f"Unsupported prefix status: {status}")
    return normalized


def _validate_address_status(status: str) -> str:
    normalized = (status or 'allocated').strip().lower()
    if normalized not in ADDRESS_STATUSES:
        raise ValueError(f"Unsupported address status: {status}")
    return normalized


def _validate_address_conflicts(conn, subnet, address: str, *, exclude_id: str = '') -> None:
    """Reject active static/DHCP/VIP conflicts in the same authority scope."""
    tenant_id = subnet['tenant_id'] or 'tenant-default'
    vrf_id = subnet['vrf_id'] or ''
    params = [address, tenant_id, vrf_id]
    exclude_sql = ''
    if exclude_id:
        exclude_sql = f' AND ip.id <> {_PH}'
        params.append(exclude_id)
    existing = conn.execute(
        f"""SELECT ip.id FROM ip_addresses ip
            LEFT JOIN prefixes p ON p.id = ip.subnet_id
            WHERE ip.address = {_PH}
              AND COALESCE(p.tenant_id, 'tenant-default') = {_PH}
              AND COALESCE(p.vrf_id, '') = {_PH}
              AND COALESCE(ip.status, 'active') NOT IN ('released', 'available')
              {exclude_sql} LIMIT 1""",
        tuple(params),
    ).fetchone()
    if existing:
        try:
            from core.metrics import metrics_registry
            metrics_registry.record_ipam_conflict()
        except Exception:
            pass
        raise ValueError(f'IP address {address} is already allocated in this tenant/VRF')
    try:
        vip = conn.execute(
            f"""SELECT id FROM ipam_vips
                WHERE address = {_PH} AND COALESCE(tenant_id, 'tenant-default') = {_PH}
                  AND COALESCE(status, 'active') NOT IN ('released', 'deprecated') LIMIT 1""",
            (address, tenant_id),
        ).fetchone()
    except Exception:
        vip = None
    if vip:
        try:
            from core.metrics import metrics_registry
            metrics_registry.record_ipam_conflict()
        except Exception:
            pass
        raise ValueError(f'IP address {address} conflicts with an active VIP')
    try:
        lease = conn.execute(
            f"""SELECT id FROM ipam_dhcp_leases
                WHERE address = {_PH} AND COALESCE(lease_state, 'active') IN ('active', 'offered')
                LIMIT 1""",
            (address,),
        ).fetchone()
    except Exception:
        lease = None
    if lease:
        try:
            from core.metrics import metrics_registry
            metrics_registry.record_ipam_conflict()
        except Exception:
            pass
        raise ValueError(f'IP address {address} conflicts with an active DHCP lease')


def _validate_prefix_overlap(conn, *, prefix: str, tenant_id: str | None = None,
                             vrf_id: str | None = None, site_id: str | None = None,
                             exclude_id: str | None = None) -> None:
    """Reject duplicate or sibling-overlap prefixes in the same tenant/VRF/site scope.

    Parent/child containment is allowed; partial sibling overlap and exact duplicate
    are rejected. Different VRFs are allowed to reuse the same prefix.
    """
    normalized, new_net = _normalize_prefix(prefix)
    tenant = tenant_id or 'tenant-default'
    vrf = vrf_id or ''
    site = site_id or ''

    rows = conn.execute(
        f"""SELECT id, prefix, tenant_id, vrf_id, site_id
            FROM prefixes
            WHERE COALESCE(tenant_id, 'tenant-default') = {_PH}
              AND COALESCE(vrf_id, '') = {_PH}
              AND COALESCE(site_id, '') = {_PH}""",
        (tenant, vrf, site),
    ).fetchall()
    for row in rows:
        if exclude_id and row['id'] == exclude_id:
            continue
        try:
            existing = ipaddress.ip_network(row['prefix'], strict=False)
        except ValueError:
            continue
        if existing.version != new_net.version or not existing.overlaps(new_net):
            continue
        if existing == new_net:
            raise ValueError(f"Prefix {normalized} already exists in this tenant/VRF/site scope")
        if new_net.subnet_of(existing) or existing.subnet_of(new_net):
            continue
        raise ValueError(f"Prefix {normalized} overlaps with existing sibling prefix {row['prefix']}")


def _select_prefix_for_update(conn, subnet_id: str):
    sql = f"SELECT * FROM prefixes WHERE id = {_PH}"
    if _USE_PG:
        sql += " FOR UPDATE"
    return conn.execute(sql, (subnet_id,)).fetchone()


def _ph(n: int = 1) -> str:
    """Return n comma-separated placeholders."""
    return ', '.join([_PH] * n)


# ══════════════════════════════════════════════════════════
# Prefix Hierarchy
# ══════════════════════════════════════════════════════════

def rebuild_prefixes_hierarchy(conn=None):
    """Rebuild parent_prefix_id for all prefixes using CIDR containment rules.
    The most-specific (longest prefix) containing network becomes the parent.
    Within each VRF, prefixes form a tree.
    """
    should_close = conn is None
    if conn is None:
        conn = get_db_connection()
    try:
        rows = conn.execute('SELECT id, prefix, vrf_id FROM prefixes').fetchall()
        items = []
        for r in rows:
            try:
                net = ipaddress.ip_network(r['prefix'], strict=False)
                items.append({
                    'id': r['id'],
                    'prefix': r['prefix'],
                    'vrf_id': r['vrf_id'] or '',
                    'net': net,
                    'prefixlen': net.prefixlen,
                })
            except ValueError:
                continue

        # Sort by prefix length ascending so we process broader nets first
        items.sort(key=lambda x: x['prefixlen'])

        # For each prefix, find the most specific (longest prefixlen) parent
        id_to_parent = {}
        for i, item in enumerate(items):
            best_parent = None
            best_len = -1
            for j, candidate in enumerate(items):
                if i == j:
                    continue
                if item['vrf_id'] != candidate['vrf_id']:
                    continue
                # IPv4 and IPv6 prefixes never nest within each other
                if item['net'].version != candidate['net'].version:
                    continue
                # candidate must be a strict supernet
                if candidate['prefixlen'] >= item['prefixlen']:
                    continue
                if item['net'].subnet_of(candidate['net']):
                    if candidate['prefixlen'] > best_len:
                        best_len = candidate['prefixlen']
                        best_parent = candidate['id']
            id_to_parent[item['id']] = best_parent

        # Batch update
        for prefix_id, parent_id in id_to_parent.items():
            conn.execute(
                f'UPDATE prefixes SET parent_prefix_id = {_PH} WHERE id = {_PH}',
                (parent_id, prefix_id),
            )
        conn.commit()
        logger.info("Rebuilt prefix hierarchy for %d prefixes.", len(items))
    finally:
        if should_close:
            conn.close()


# ══════════════════════════════════════════════════════════
# Subnet (Prefix) CRUD — using the `prefixes` table
# ══════════════════════════════════════════════════════════

def list_subnets(*, site: str = 'all', status: str = 'all', q: str = '') -> list[dict]:
    conn = get_db_connection()
    try:
        sql = f'''
            SELECT p.*,
                   v.vrf_name,
                   vl.vlan_id AS vlan_number, vl.name AS vlan_display_name,
                   s.site_name, s.site_code,
                   t.name AS tenant_name,
                   d.hostname AS gateway_device_name
            FROM prefixes p
            LEFT JOIN vrfs v ON p.vrf_id = v.id
            LEFT JOIN vlans vl ON p.vlan_id = vl.id
            LEFT JOIN sites s ON p.site_id = s.id
            LEFT JOIN tenants t ON p.tenant_id = t.id
            LEFT JOIN devices d ON p.gateway_device_id = d.id
            WHERE 1=1
        '''
        params: list = []

        if site and site != 'all':
            sql += f' AND p.site_id = {_PH}'
            params.append(site)
        if status and status != 'all':
            sql += f' AND p.status = {_PH}'
            params.append(status)
        if q and q.strip():
            fuzzy = f'%{q.strip().lower()}%'
            sql += f' AND (LOWER(p.name) LIKE {_PH} OR LOWER(p.prefix) LIKE {_PH} OR LOWER(p.description) LIKE {_PH})'
            params.extend([fuzzy, fuzzy, fuzzy])

        sql += ' ORDER BY p.prefix'
        rows = conn.execute(sql, tuple(params)).fetchall()

        result = []
        for r in rows:
            item = dict(r)

            prefix_str = item.get('prefix', '')
            total_ips = _calculate_total_ips(prefix_str)
            item['total_ips'] = total_ips

            # Count used IPs (allocated in ip_addresses table)
            count = conn.execute(
                f"""SELECT COUNT(*) as cnt FROM ip_addresses WHERE subnet_id = {_PH}
                    AND COALESCE(status, 'active') NOT IN ('released', 'available')""",
                (r['id'],),
            ).fetchone()
            used_ips = count['cnt'] if count else 0
            item['used_ips'] = used_ips

            # Count active endpoints from network_endpoints if table exists
            try:
                active = conn.execute(
                    f'''SELECT COUNT(DISTINCT ip) as cnt FROM network_endpoints
                        WHERE is_active = 1 AND ip IN (
                            SELECT address FROM ip_addresses WHERE subnet_id = {_PH}
                        )''',
                    (r['id'],),
                ).fetchone()
                item['active_ips'] = active['cnt'] if active else 0
            except Exception:
                # On PostgreSQL a failed query aborts the whole transaction;
                # roll back so subsequent statements in this connection survive.
                try:
                    conn.rollback()
                except Exception:
                    pass
                item['active_ips'] = 0

            item['utilization'] = (
                round(used_ips / total_ips * 100, 1) if total_ips > 0 else 0
            )

            # Resolve VLAN info
            item['vlan_id'] = item.get('vlan_number') or item.get('vlan_id')

            result.append(item)
        return result
    finally:
        conn.close()


def create_subnet(
    *,
    prefix: str,
    vrf_id: Optional[str] = None,
    vlan_id: Optional[str] = None,
    site_id: Optional[str] = None,
    tenant_id: Optional[str] = 'tenant-default',
    status: str = 'active',
    name: str = '',
    gateway: str = '',
    description: str = '',
    network_type: str = 'server',
    gateway_device_id: Optional[str] = None,
    gateway_interface_id: Optional[str] = None,
    traceable: int = 1,
) -> dict:
    """Create a prefix after validating CIDR and checking for VRF-scoped duplicates."""
    prefix, net = _normalize_prefix(prefix)
    status = _validate_prefix_status(status)

    conn = get_db_connection()
    try:
        _validate_prefix_overlap(
            conn,
            prefix=prefix,
            tenant_id=tenant_id,
            vrf_id=vrf_id,
            site_id=site_id,
        )

        prefix_id = f"prefix-{uuid.uuid4().hex[:12]}"
        now = _utc_now()

        conn.execute(
            f'''INSERT INTO prefixes
               (id, prefix, vrf_id, vlan_id, site_id, tenant_id, status,
                name, gateway, description, network_type, gateway_device_id,
                gateway_interface_id, traceable, created_at, updated_at,
                prefix_cidr, ip_version, prefix_len)
               VALUES ({_ph(19)})''',
            (prefix_id, prefix, vrf_id or None, vlan_id or None, site_id or None,
             tenant_id, status, name, gateway, description, network_type,
             gateway_device_id or None, gateway_interface_id or None,
             traceable, now, now, prefix, net.version, net.prefixlen),
        )
        conn.commit()

        # Rebuild hierarchy after adding new prefix
        rebuild_prefixes_hierarchy(conn)

        logger.info("Created prefix %s (%s)", prefix_id, prefix)
        return {
            'id': prefix_id,
            'prefix': prefix,
            'ip_version': net.version,
            'prefix_len': net.prefixlen,
            'total_ips': _calculate_total_ips(prefix),
        }
    finally:
        conn.close()


def update_subnet(subnet_id: str, **fields) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT * FROM prefixes WHERE id = {_PH}', (subnet_id,)
        ).fetchone()
        if not row:
            return False

        if 'prefix' in fields and fields['prefix'] is not None:
            fields['prefix'], _net = _normalize_prefix(fields['prefix'])
        if 'status' in fields and fields['status'] is not None:
            fields['status'] = _validate_prefix_status(fields['status'])
        target = dict(row)
        target.update({k: v for k, v in fields.items() if v is not None})
        if any(k in fields for k in ('prefix', 'tenant_id', 'vrf_id', 'site_id')):
            _validate_prefix_overlap(
                conn,
                prefix=target.get('prefix') or '',
                tenant_id=target.get('tenant_id'),
                vrf_id=target.get('vrf_id'),
                site_id=target.get('site_id'),
                exclude_id=subnet_id,
            )

        if 'prefix' in fields and fields['prefix'] is not None:
            fields['prefix_cidr'] = fields['prefix']
            fields['ip_version'] = _net.version
            fields['prefix_len'] = _net.prefixlen

        allowed_fields = (
            'name', 'vrf_id', 'vlan_id', 'site_id', 'tenant_id', 'status',
            'gateway', 'description', 'prefix', 'network_type',
            'gateway_device_id', 'gateway_interface_id', 'traceable',
            'prefix_cidr', 'ip_version', 'prefix_len',
        )
        updates = []
        params = []
        prefix_changed = False
        for field in allowed_fields:
            val = fields.get(field)
            if val is not None:
                updates.append(f'{field} = {_PH}')
                params.append(val)
                if field == 'prefix':
                    prefix_changed = True

        if updates:
            updates.append(f'updated_at = {_PH}')
            params.append(_utc_now())
            params.append(subnet_id)
            conn.execute(
                f"UPDATE prefixes SET {', '.join(updates)} WHERE id = {_PH}",
                tuple(params),
            )
            conn.commit()

            # Rebuild hierarchy if prefix or VRF changed
            if prefix_changed or 'vrf_id' in fields:
                rebuild_prefixes_hierarchy(conn)

        return True
    finally:
        conn.close()


def delete_subnet(subnet_id: str) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT id FROM prefixes WHERE id = {_PH}', (subnet_id,)
        ).fetchone()
        if not row:
            return False
        # Cascade delete IP addresses
        conn.execute(f'DELETE FROM ip_addresses WHERE subnet_id = {_PH}', (subnet_id,))
        conn.execute(f'DELETE FROM prefixes WHERE id = {_PH}', (subnet_id,))
        conn.commit()

        # Rebuild hierarchy after deletion
        rebuild_prefixes_hierarchy(conn)

        logger.info("Deleted prefix %s", subnet_id)
        return True
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# IP Addresses
# ══════════════════════════════════════════════════════════

def list_addresses(subnet_id: str) -> list[dict]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f'SELECT * FROM ip_addresses WHERE subnet_id = {_PH} ORDER BY address',
            (subnet_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_address(
    subnet_id: str,
    *,
    address: str,
    hostname: str = '',
    device_id: str = '',
    interface_name: str = '',
    mac_address: str = '',
    device_type: str = '',
    description: str = '',
    status: str = 'active',
    interface_id: str = '',
    purpose: str = '',
    requested_by: str = '',
    expires_at: str = '',
    source_type: str = 'manual',
    source_ref: str = '',
) -> dict:
    """Add an IP address after validating it belongs to the subnet."""
    address = _normalize_address(address)
    status = _validate_address_status(status)
    conn = get_db_connection()
    try:
        addr = _create_address_with_conn(
            conn,
            subnet_id,
            address=address,
            hostname=hostname,
            device_id=device_id,
            interface_name=interface_name,
            interface_id=interface_id,
            mac_address=mac_address,
            device_type=device_type,
            description=description,
            status=status,
            lock_prefix=True,
            purpose=purpose,
            requested_by=requested_by,
            expires_at=expires_at,
            source_type=source_type,
            source_ref=source_ref,
        )
        conn.commit()
        return addr
    finally:
        conn.close()


def _create_address_with_conn(conn, subnet_id: str, *, address: str, hostname: str = '',
                              device_id: str = '', interface_name: str = '',
                              interface_id: str = '', mac_address: str = '',
                              device_type: str = '', description: str = '',
                              status: str = 'active', lock_prefix: bool = False,
                              purpose: str = '', requested_by: str = '',
                              expires_at: str = '', source_type: str = 'manual',
                              source_ref: str = '') -> dict:
    subnet = _select_prefix_for_update(conn, subnet_id) if lock_prefix else conn.execute(
        f'SELECT * FROM prefixes WHERE id = {_PH}', (subnet_id,)
    ).fetchone()
    if not subnet:
        raise ValueError('Subnet not found')
    try:
        net = ipaddress.ip_network(subnet['prefix'], strict=False)
    except ValueError:
        raise ValueError('Invalid subnet prefix')
    if ipaddress.ip_address(address) not in net:
        raise ValueError(f"Address {address} is not within subnet {net}")
    status = _validate_address_status(status)
    _validate_address_conflicts(conn, subnet, address)
    address_columns = _table_columns(conn, 'ip_addresses')
    existing_fields = 'id, status' + (', available_after' if 'available_after' in address_columns else '')
    existing = conn.execute(
        f'SELECT {existing_fields} FROM ip_addresses WHERE subnet_id = {_PH} AND address = {_PH}',
        (subnet_id, address),
    ).fetchone()
    if existing:
        if existing['status'] not in ('released', 'available'):
            raise ValueError('IP address already registered in this subnet')
        if 'available_after' in address_columns and existing['available_after'] and existing['available_after'] > _utc_now():
            raise ValueError(f"IP address is quarantined until {existing['available_after']}")
        now = _utc_now()
        reuse_values = {
            'status': status, 'hostname': hostname, 'device_id': device_id,
            'interface_name': interface_name, 'interface_id': interface_id,
            'mac_address': mac_address, 'device_type': device_type,
            'description': description, 'purpose': purpose,
            'requested_by': requested_by, 'expires_at': expires_at or None,
            'source_type': source_type, 'source_ref': source_ref,
            'released_at': None, 'available_after': None, 'updated_at': now,
        }
        reuse_values = {key: value for key, value in reuse_values.items() if key in address_columns}
        assignments = ', '.join(f'{key} = {_PH}' for key in reuse_values)
        conn.execute(
            f"UPDATE ip_addresses SET {assignments} WHERE id = {_PH}",
            (*reuse_values.values(), existing['id']),
        )
        return {'id': existing['id'], 'address': address, 'status': status, 'reused': True}
    addr_id = f"ip-{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    ip_addr_with_mask = f"{address}/{net.prefixlen}"
    insert_values = {
        'id': addr_id, 'subnet_id': subnet_id, 'address': address,
        'hostname': hostname, 'device_id': device_id, 'interface_name': interface_name,
        'mac_address': mac_address, 'device_type': device_type, 'status': status,
        'description': description, 'last_seen': now, 'created_at': now, 'updated_at': now,
        'ip_address': ip_addr_with_mask, 'prefix_id': subnet_id,
        'vrf_id': subnet['vrf_id'] or '', 'tenant_id': subnet['tenant_id'] or 'tenant-default',
        'site_id': subnet['site_id'] or '', 'interface_id': interface_id or '',
        'address_inet': address, 'ip_version': ipaddress.ip_address(address).version,
        'purpose': purpose, 'requested_by': requested_by, 'expires_at': expires_at or None,
        'source_type': source_type, 'source_ref': source_ref,
    }
    insert_values = {key: value for key, value in insert_values.items() if key in address_columns}
    conn.execute(
        f"INSERT INTO ip_addresses ({', '.join(insert_values)}) VALUES ({_ph(len(insert_values))})",
        tuple(insert_values.values()),
    )
    return {'id': addr_id, 'address': address, 'status': status}


def update_address(address_id: str, **fields) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT * FROM ip_addresses WHERE id = {_PH}', (address_id,)
        ).fetchone()
        if not row:
            return False

        if 'status' in fields and fields['status'] is not None:
            target_status = _validate_address_status(fields['status'])
            current_status = (row['status'] or 'active').lower()
            if target_status != current_status and target_status not in ADDRESS_TRANSITIONS.get(current_status, set()):
                raise ValueError(f'Invalid address lifecycle transition: {current_status} -> {target_status}')
            fields['status'] = target_status

        updates = []
        params = []
        address_columns = _table_columns(conn, 'ip_addresses')
        for field in ('hostname', 'device_id', 'interface_name', 'interface_id', 'mac_address',
                      'device_type', 'description', 'status', 'purpose', 'requested_by',
                      'expires_at', 'source_type', 'source_ref', 'released_at', 'available_after'):
            val = fields.get(field)
            if val is not None and field in address_columns:
                updates.append(f'{field} = {_PH}')
                params.append(val)
        if updates:
            updates.append(f'updated_at = {_PH}')
            params.append(_utc_now())
            params.append(address_id)
            conn.execute(
                f"UPDATE ip_addresses SET {', '.join(updates)} WHERE id = {_PH}",
                tuple(params),
            )
            conn.commit()
        return True
    finally:
        conn.close()


def delete_address(address_id: str) -> bool:
    conn = get_db_connection()
    try:
        addr = conn.execute(
            f'SELECT subnet_id FROM ip_addresses WHERE id = {_PH}', (address_id,)
        ).fetchone()
        if not addr:
            return False
        conn.execute(f'DELETE FROM ip_addresses WHERE id = {_PH}', (address_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def allocate_next_address(subnet_id: str, *, hostname: str = '', device_id: str = '',
                          interface_id: str = '', interface_name: str = '',
                          mac_address: str = '', purpose: str = '',
                          requested_by: str = '', status: str = 'allocated',
                          expires_at: str = '') -> dict:
    conn = get_db_connection()
    try:
        subnet = _select_prefix_for_update(conn, subnet_id)
        if not subnet:
            raise ValueError('Subnet not found')
        net = ipaddress.ip_network(subnet['prefix'], strict=False)
        now = _utc_now()
        if 'available_after' in _table_columns(conn, 'ip_addresses'):
            used_rows = conn.execute(
                f"""SELECT address FROM ip_addresses
                    WHERE subnet_id = {_PH}
                      AND (COALESCE(status, 'active') NOT IN ('released', 'available')
                           OR (available_after IS NOT NULL AND available_after > {_PH}))""",
                (subnet_id, now),
            ).fetchall()
        else:
            used_rows = conn.execute(
                f"""SELECT address FROM ip_addresses WHERE subnet_id = {_PH}
                    AND COALESCE(status, 'active') NOT IN ('released', 'available')""",
                (subnet_id,),
            ).fetchall()
        used = {str(ipaddress.ip_address(r['address'])) for r in used_rows if r['address']}
        candidates = net.hosts() if net.version == 4 and net.prefixlen < 31 else iter(net)
        selected = None
        for candidate in candidates:
            cand = str(candidate)
            if cand not in used:
                selected = cand
                break
        if not selected:
            raise ValueError('No available IP addresses in this subnet')
        addr = _create_address_with_conn(
            conn,
            subnet_id,
            address=selected,
            hostname=hostname,
            device_id=device_id,
            interface_name=interface_name,
            interface_id=interface_id,
            mac_address=mac_address,
            device_type=purpose,
            description=f"Allocated by {requested_by}" if requested_by else '',
            status=status,
            purpose=purpose,
            requested_by=requested_by,
            expires_at=expires_at,
        )
        conn.commit()
        return addr
    finally:
        conn.close()


def reserve_address(subnet_id: str, *, address: str, hostname: str = '', device_id: str = '',
                    interface_id: str = '', interface_name: str = '', mac_address: str = '',
                    purpose: str = '', requested_by: str = '', expires_at: str = '') -> dict:
    return create_address(
        subnet_id,
        address=address,
        hostname=hostname,
        device_id=device_id,
        interface_id=interface_id,
        interface_name=interface_name,
        mac_address=mac_address,
        device_type=purpose,
        description=f"Reserved by {requested_by}" if requested_by else '',
        status='reserved',
        purpose=purpose,
        requested_by=requested_by,
        expires_at=expires_at,
    )


def release_address(address_id: str, *, released_by: str = '') -> bool:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    available_after = (now + timedelta(hours=24)).isoformat()
    description_suffix = f"Released by {released_by}" if released_by else "Released"
    return update_address(
        address_id,
        status='released',
        device_id='',
        interface_id='',
        interface_name='',
        mac_address='',
        description=description_suffix,
        released_at=now.isoformat(),
        available_after=available_after,
    )


# ══════════════════════════════════════════════════════════
# Conflict Detection
# ══════════════════════════════════════════════════════════

def detect_conflicts() -> dict:
    """Scan for duplicate IPs across subnets and duplicate MACs."""
    conn = get_db_connection()
    try:
        dup_ips = conn.execute(f'''
            SELECT address, {_GROUP_CONCAT.format(col='subnet_id')} as subnets, COUNT(*) as cnt
            FROM ip_addresses
            WHERE COALESCE(status, 'active') NOT IN ('released', 'available')
            GROUP BY address HAVING COUNT(*) > 1
        ''').fetchall()

        dup_macs = conn.execute(f'''
            SELECT mac_address, {_GROUP_CONCAT.format(col='address')} as addresses, COUNT(*) as cnt
            FROM ip_addresses
            WHERE mac_address != '' AND mac_address IS NOT NULL
              AND COALESCE(status, 'active') NOT IN ('released', 'available')
            GROUP BY mac_address HAVING COUNT(*) > 1
        ''').fetchall()

        return {
            'ip_conflicts': [dict(r) for r in dup_ips],
            'mac_conflicts': [dict(r) for r in dup_macs],
            'total_conflicts': len(dup_ips) + len(dup_macs),
        }
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# Summary / Analytics
# ══════════════════════════════════════════════════════════

def ipam_summary() -> dict:
    conn = get_db_connection()
    try:
        subnets = conn.execute('SELECT COUNT(*) as cnt FROM prefixes').fetchone()
        addresses = conn.execute('SELECT COUNT(*) as cnt FROM ip_addresses').fetchone()

        # Calculate total capacity dynamically
        all_prefixes = conn.execute('SELECT prefix FROM prefixes').fetchall()
        total_capacity = sum(_calculate_total_ips(r['prefix']) for r in all_prefixes)

        total_used = conn.execute(
            "SELECT COUNT(*) as total FROM ip_addresses WHERE COALESCE(status, 'active') NOT IN ('released', 'available')"
        ).fetchone()

        return {
            'total_subnets': subnets['cnt'] if subnets else 0,
            'total_addresses': addresses['cnt'] if addresses else 0,
            'total_capacity': total_capacity,
            'total_used': total_used['total'] if total_used else 0,
            'high_utilization_subnets': [],
        }
    finally:
        conn.close()


def get_utilization_analytics() -> dict:
    """Return analytics data for IPAM utilization dashboards.

    Shape matches the frontend IPUtilizationTab:
      { overview, top_utilized_prefixes, site_breakdown, forecast_trend }
    """
    conn = get_db_connection()
    try:
        # ── Per-prefix utilization ──────────────────────────
        rows = conn.execute(
            '''SELECT p.id, p.prefix, p.name, p.status, p.site_id,
                      s.site_name, s.site_code
               FROM prefixes p
               LEFT JOIN sites s ON p.site_id = s.id'''
        ).fetchall()

        per_prefix = []
        total_ips_sum = 0
        used_ips_sum = 0
        site_agg: dict[str, dict] = {}

        for r in rows:
            total = _calculate_total_ips(r['prefix'])
            used_row = conn.execute(
                f"""SELECT COUNT(*) as cnt FROM ip_addresses WHERE subnet_id = {_PH}
                    AND COALESCE(status, 'active') NOT IN ('released', 'available')""",
                (r['id'],),
            ).fetchone()
            used_count = used_row['cnt'] if used_row else 0

            total_ips_sum += total
            used_ips_sum += used_count

            per_prefix.append({
                'id': r['id'],
                'prefix': r['prefix'],
                'name': r['name'],
                'status': r['status'],
                'total_ips': total,
                'used_ips': used_count,
                'utilization': round(used_count / total * 100, 1) if total > 0 else 0,
            })

            # Aggregate by site
            site_key = r['site_name'] or r['site_code'] or 'Unassigned'
            bucket = site_agg.setdefault(site_key, {'site': site_key, 'total_ips': 0, 'used_ips': 0})
            bucket['total_ips'] += total
            bucket['used_ips'] += used_count

        # Top 5 prefixes by utilization (exclude empty ones)
        top_utilized = sorted(
            [p for p in per_prefix if p['total_ips'] > 0],
            key=lambda x: x['utilization'],
            reverse=True,
        )[:5]

        # Site breakdown with utilization
        site_breakdown = []
        for bucket in site_agg.values():
            t = bucket['total_ips']
            u = bucket['used_ips']
            site_breakdown.append({
                'site': bucket['site'],
                'total_ips': t,
                'used_ips': u,
                'utilization': round(u / t * 100, 1) if t > 0 else 0,
            })
        site_breakdown.sort(key=lambda x: x['used_ips'], reverse=True)

        # ── Counts for the overview cards ───────────────────
        def _count(table: str) -> int:
            try:
                row = conn.execute(f'SELECT COUNT(*) as cnt FROM {table}').fetchone()
                return row['cnt'] if row else 0
            except Exception:
                return 0

        prefixes_count = len(per_prefix)
        ips_count = _count('ip_addresses')
        pools_count = _count('ipam_pools')
        vips_count = _count('ipam_vips')
        leases_count = _count('ipam_dhcp_leases')

        overview = {
            'prefixes_count': prefixes_count,
            'ips_count': ips_count,
            'pools_count': pools_count,
            'vips_count': vips_count,
            'leases_count': leases_count,
            'total_ips': total_ips_sum,
            'used_ips': used_ips_sum,
            'free_ips': max(0, total_ips_sum - used_ips_sum),
            'utilization_rate': round(used_ips_sum / total_ips_sum * 100, 1) if total_ips_sum > 0 else 0,
        }

        # ── Allocation trend (cumulative, by created day) ───
        forecast_trend = []
        try:
            day_rows = conn.execute(
                '''SELECT substr(created_at, 1, 10) as day, COUNT(*) as cnt
                   FROM ip_addresses
                   WHERE created_at IS NOT NULL AND created_at != ''
                     AND COALESCE(status, 'active') NOT IN ('released', 'available')
                   GROUP BY substr(created_at, 1, 10)
                   ORDER BY day'''
            ).fetchall()
            cumulative = 0
            for dr in day_rows:
                cumulative += dr['cnt']
                forecast_trend.append({'day': dr['day'], 'allocated': cumulative})
            # Keep the most recent 14 data points for a readable chart
            forecast_trend = forecast_trend[-14:]
        except Exception:
            forecast_trend = []

        return {
            'overview': overview,
            'top_utilized_prefixes': top_utilized,
            'site_breakdown': site_breakdown,
            'forecast_trend': forecast_trend,
            # Backward-compatible flat list
            'items': per_prefix,
        }
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# Hierarchy Tree (using parent_prefix_id)
# ══════════════════════════════════════════════════════════

def get_subnets_tree() -> list[dict]:
    """Build a hierarchy tree from parent_prefix_id relationships."""
    conn = get_db_connection()
    try:
        rows = conn.execute(f'''
            SELECT p.*, v.vrf_name,
                   vl.vlan_id AS vlan_number, vl.name AS vlan_display_name,
                   s.site_name, s.site_code,
                   t.name AS tenant_name
            FROM prefixes p
            LEFT JOIN vrfs v ON p.vrf_id = v.id
            LEFT JOIN vlans vl ON p.vlan_id = vl.id
            LEFT JOIN sites s ON p.site_id = s.id
            LEFT JOIN tenants t ON p.tenant_id = t.id
            ORDER BY p.prefix
        ''').fetchall()

        nodes = {}
        for r in rows:
            item = dict(r)
            total_ips = _calculate_total_ips(item.get('prefix', ''))
            item['total_ips'] = total_ips
            used = conn.execute(
                f'SELECT COUNT(*) as cnt FROM ip_addresses WHERE subnet_id = {_PH}',
                (r['id'],),
            ).fetchone()
            used_ips = used['cnt'] if used else 0
            item['used_ips'] = used_ips
            item['utilization'] = round(used_ips / total_ips * 100, 1) if total_ips > 0 else 0
            item['vlan_id'] = item.get('vlan_number') or item.get('vlan_id')
            item['children'] = []
            nodes[item['id']] = item

        roots = []
        for nid, node in nodes.items():
            parent_id = node.get('parent_prefix_id')
            if parent_id and parent_id in nodes:
                nodes[parent_id]['children'].append(node)
            else:
                roots.append(node)

        return roots
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# IP Pools CRUD
# ══════════════════════════════════════════════════════════

def list_pools() -> list[dict]:
    conn = get_db_connection()
    try:
        rows = conn.execute('''
            SELECT p.*, pf.prefix AS prefix_cidr, t.name AS tenant_name
            FROM ipam_pools p
            LEFT JOIN prefixes pf ON p.prefix_id = pf.id
            LEFT JOIN tenants t ON p.tenant_id = t.id
            ORDER BY p.name
        ''').fetchall()
        
        pools = []
        for r in rows:
            p_dict = dict(r)
            p_dict['prefix'] = p_dict.get('prefix_cidr') or ''
            
            start_ip_str = p_dict.get('start_ip', '')
            end_ip_str = p_dict.get('end_ip', '')
            
            total_ips = 0
            used_ips = 0
            
            try:
                start = ipaddress.ip_address(start_ip_str)
                end = ipaddress.ip_address(end_ip_str)
                if start.version == end.version:
                    total_ips = int(end) - int(start) + 1
            except Exception:
                pass
            
            p_dict['total_ips'] = total_ips
            
            prefix_id = p_dict.get('prefix_id')
            if prefix_id and total_ips > 0:
                addr_rows = conn.execute('''
                    SELECT address FROM ip_addresses WHERE subnet_id = ?
                ''', (prefix_id,)).fetchall()
                
                try:
                    start = ipaddress.ip_address(start_ip_str)
                    end = ipaddress.ip_address(end_ip_str)
                    for ar in addr_rows:
                        addr_str = ar['address']
                        try:
                            addr_obj = ipaddress.ip_address(addr_str)
                            if start <= addr_obj <= end:
                                used_ips += 1
                        except Exception:
                            pass
                except Exception:
                    pass
            
            p_dict['used_ips'] = used_ips
            p_dict['utilization'] = round((used_ips / total_ips * 100), 1) if total_ips > 0 else 0
            pools.append(p_dict)
            
        return pools
    finally:
        conn.close()


def create_pool(
    *,
    name: str,
    prefix_id: str,
    start_ip: str,
    end_ip: str,
    description: str = '',
    status: str = 'active',
    tenant_id: str = 'tenant-default',
) -> dict:
    conn = get_db_connection()
    try:
        pool_id = f"pool-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        conn.execute(
            f'''INSERT INTO ipam_pools
               (id, name, prefix_id, start_ip, end_ip, description, status, tenant_id, created_at, updated_at)
               VALUES ({_ph(10)})''',
            (pool_id, name, prefix_id, start_ip, end_ip, description, status, tenant_id, now, now),
        )
        conn.commit()
        return {'id': pool_id}
    finally:
        conn.close()


def update_pool(pool_id: str, **fields) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT id FROM ipam_pools WHERE id = {_PH}', (pool_id,)
        ).fetchone()
        if not row:
            return False
        updates = []
        params = []
        for f in ('name', 'prefix_id', 'start_ip', 'end_ip', 'description', 'status', 'tenant_id'):
            val = fields.get(f)
            if val is not None:
                updates.append(f'{f} = {_PH}')
                params.append(val)
        if updates:
            updates.append(f'updated_at = {_PH}')
            params.append(_utc_now())
            params.append(pool_id)
            conn.execute(
                f"UPDATE ipam_pools SET {', '.join(updates)} WHERE id = {_PH}",
                tuple(params),
            )
            conn.commit()
        return True
    finally:
        conn.close()


def delete_pool(pool_id: str) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT id FROM ipam_pools WHERE id = {_PH}', (pool_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute(f'DELETE FROM ipam_pools WHERE id = {_PH}', (pool_id,))
        conn.commit()
        return True
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# VIP CRUD
# ══════════════════════════════════════════════════════════

def list_vips() -> list[dict]:
    conn = get_db_connection()
    try:
        rows = conn.execute('''
            SELECT vip.*, d.hostname AS device_name,
                   bd.hostname AS backup_device_name,
                   t.name AS tenant_name
            FROM ipam_vips vip
            LEFT JOIN devices d ON vip.device_id = d.id
            LEFT JOIN devices bd ON vip.backup_device_id = bd.id
            LEFT JOIN tenants t ON vip.tenant_id = t.id
            ORDER BY vip.address
        ''').fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_vip(
    *,
    address: str,
    vip_type: str,
    device_id: Optional[str] = None,
    backup_device_id: Optional[str] = None,
    interface_name: str = '',
    description: str = '',
    real_servers: str = '',
    status: str = 'active',
    tenant_id: str = 'tenant-default',
) -> dict:
    address = _normalize_address(address)
    conn = get_db_connection()
    try:
        existing_ip = conn.execute(
            f"""SELECT ip.id FROM ip_addresses ip
                LEFT JOIN prefixes p ON p.id = ip.subnet_id
                WHERE ip.address = {_PH}
                  AND COALESCE(p.tenant_id, 'tenant-default') = {_PH}
                  AND COALESCE(ip.status, 'active') NOT IN ('released', 'available') LIMIT 1""",
            (address, tenant_id),
        ).fetchone()
        if existing_ip:
            raise ValueError(f'VIP {address} conflicts with an allocated IP address')
        existing_lease = conn.execute(
            f"SELECT id FROM ipam_dhcp_leases WHERE address = {_PH} AND COALESCE(lease_state, 'active') IN ('active', 'offered') LIMIT 1",
            (address,),
        ).fetchone()
        if existing_lease:
            raise ValueError(f'VIP {address} conflicts with an active DHCP lease')
        vip_id = f"vip-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        conn.execute(
            f'''INSERT INTO ipam_vips
               (id, address, vip_type, device_id, backup_device_id, interface_name,
                description, real_servers, status, tenant_id, created_at, updated_at)
               VALUES ({_ph(12)})''',
            (vip_id, address, vip_type, device_id or None, backup_device_id or None,
             interface_name, description, real_servers, status, tenant_id, now, now),
        )
        conn.commit()
        return {'id': vip_id}
    finally:
        conn.close()


def update_vip(vip_id: str, **fields) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT id FROM ipam_vips WHERE id = {_PH}', (vip_id,)
        ).fetchone()
        if not row:
            return False
        updates = []
        params = []
        for f in ('address', 'vip_type', 'device_id', 'backup_device_id',
                  'interface_name', 'description', 'real_servers', 'status', 'tenant_id'):
            val = fields.get(f)
            if val is not None:
                updates.append(f'{f} = {_PH}')
                params.append(val)
        if updates:
            updates.append(f'updated_at = {_PH}')
            params.append(_utc_now())
            params.append(vip_id)
            conn.execute(
                f"UPDATE ipam_vips SET {', '.join(updates)} WHERE id = {_PH}",
                tuple(params),
            )
            conn.commit()
        return True
    finally:
        conn.close()


def delete_vip(vip_id: str) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT id FROM ipam_vips WHERE id = {_PH}', (vip_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute(f'DELETE FROM ipam_vips WHERE id = {_PH}', (vip_id,))
        conn.commit()
        return True
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# DHCP Lease CRUD
# ══════════════════════════════════════════════════════════

def list_leases() -> list[dict]:
    conn = get_db_connection()
    try:
        rows = conn.execute('SELECT * FROM ipam_dhcp_leases ORDER BY address').fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_lease(
    *,
    address: str,
    mac_address: str,
    hostname: str = '',
    dhcp_server: str = '',
    lease_state: str = 'active',
    lease_start: str = '',
    lease_end: str = '',
) -> dict:
    address = _normalize_address(address)
    conn = get_db_connection()
    try:
        existing_ip = conn.execute(
            f"SELECT id FROM ip_addresses WHERE address = {_PH} AND COALESCE(status, 'active') NOT IN ('released', 'available') LIMIT 1",
            (address,),
        ).fetchone()
        if existing_ip:
            raise ValueError(f'DHCP lease {address} conflicts with an allocated IP address')
        existing_vip = conn.execute(
            f"SELECT id FROM ipam_vips WHERE address = {_PH} AND COALESCE(status, 'active') NOT IN ('released', 'deprecated') LIMIT 1",
            (address,),
        ).fetchone()
        if existing_vip:
            raise ValueError(f'DHCP lease {address} conflicts with an active VIP')
        lease_id = f"lease-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        conn.execute(
            f'''INSERT INTO ipam_dhcp_leases
               (id, address, mac_address, hostname, dhcp_server,
                lease_state, lease_start, lease_end, created_at, updated_at)
               VALUES ({_ph(10)})''',
            (lease_id, address, mac_address, hostname, dhcp_server,
             lease_state, lease_start, lease_end, now, now),
        )
        conn.commit()
        return {'id': lease_id}
    finally:
        conn.close()


def update_lease(lease_id: str, **fields) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT id FROM ipam_dhcp_leases WHERE id = {_PH}', (lease_id,)
        ).fetchone()
        if not row:
            return False
        updates = []
        params = []
        for f in ('address', 'mac_address', 'hostname', 'dhcp_server',
                  'lease_state', 'lease_start', 'lease_end'):
            val = fields.get(f)
            if val is not None:
                updates.append(f'{f} = {_PH}')
                params.append(val)
        if updates:
            updates.append(f'updated_at = {_PH}')
            params.append(_utc_now())
            params.append(lease_id)
            conn.execute(
                f"UPDATE ipam_dhcp_leases SET {', '.join(updates)} WHERE id = {_PH}",
                tuple(params),
            )
            conn.commit()
        return True
    finally:
        conn.close()


def delete_lease(lease_id: str) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT id FROM ipam_dhcp_leases WHERE id = {_PH}', (lease_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute(f'DELETE FROM ipam_dhcp_leases WHERE id = {_PH}', (lease_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def get_next_available_ip(subnet_id: str) -> Optional[str]:
    """Calculate the first unused IP address in the subnet CIDR range."""
    conn = get_db_connection()
    try:
        subnet = conn.execute(
            f'SELECT prefix, gateway FROM prefixes WHERE id = {_PH}', (subnet_id,)
        ).fetchone()
        if not subnet:
            return None
        
        prefix_str = subnet['prefix']
        gateway_ip = subnet['gateway']
        
        try:
            net = ipaddress.ip_network(prefix_str, strict=False)
        except ValueError:
            return None
            
        if 'available_after' in _table_columns(conn, 'ip_addresses'):
            allocated_rows = conn.execute(
                f"""SELECT address FROM ip_addresses WHERE subnet_id = {_PH}
                    AND (COALESCE(status, 'active') NOT IN ('released', 'available')
                         OR (available_after IS NOT NULL AND available_after > {_PH}))""",
                (subnet_id, _utc_now()),
            ).fetchall()
        else:
            allocated_rows = conn.execute(
                f"""SELECT address FROM ip_addresses WHERE subnet_id = {_PH}
                    AND COALESCE(status, 'active') NOT IN ('released', 'available')""",
                (subnet_id,),
            ).fetchall()
        allocated_ips = {r['address'] for r in allocated_rows}
        
        limit = 10000
        count = 0
        for ip_obj in net.hosts():
            count += 1
            if count > limit:
                break
            ip_str = str(ip_obj)
            if ip_str == gateway_ip:
                continue
            if ip_str in allocated_ips:
                continue
            return ip_str
            
        return None
    finally:
        conn.close()


def get_next_available_prefix(subnet_id: str, prefix_len: int) -> Optional[str]:
    """Calculate the first unused child prefix of length prefix_len inside parent subnet."""
    conn = get_db_connection()
    try:
        parent = conn.execute(
            f'SELECT prefix, vrf_id FROM prefixes WHERE id = {_PH}', (subnet_id,)
        ).fetchone()
        if not parent:
            return None
            
        parent_prefix = parent['prefix']
        vrf_id = parent['vrf_id']
        
        try:
            parent_net = ipaddress.ip_network(parent_prefix, strict=False)
        except ValueError:
            return None
            
        if prefix_len <= parent_net.prefixlen:
            return None
            
        if vrf_id:
            existing_rows = conn.execute(
                f'SELECT prefix FROM prefixes WHERE vrf_id = {_PH}', (vrf_id,)
            ).fetchall()
        else:
            existing_rows = conn.execute(
                f'SELECT prefix FROM prefixes WHERE vrf_id IS NULL OR vrf_id = {_PH}', ('',)
            ).fetchall()
            
        existing_nets = []
        for r in existing_rows:
            try:
                existing_nets.append(ipaddress.ip_network(r['prefix'], strict=False))
            except ValueError:
                continue
                
        limit = 1000
        count = 0
        for candidate in parent_net.subnets(new_prefix=prefix_len):
            count += 1
            if count > limit:
                break
            
            overlap_found = False
            for existing in existing_nets:
                if candidate.overlaps(existing):
                    # We only allow overlapping if the existing subnet is a strict supernet of candidate (e.g. parent container)
                    is_supernet = (candidate.subnet_of(existing) and existing.prefixlen < candidate.prefixlen)
                    if not is_supernet:
                        overlap_found = True
                        break
            if overlap_found:
                continue
            return str(candidate)
            
        return None
    finally:
        conn.close()


def get_ipam_reconciliation() -> dict:
    """Compare documented IPAM records against discovered active hosts in network_endpoints.
    Detect:
      - undocumented_endpoints: present in network_endpoints (is_active=1) but NOT in ip_addresses.
      - stale_ip_addresses: present in ip_addresses but NOT active in network_endpoints.
      - mismatched_endpoints: present in both but with different MAC address or hostname.
    """
    conn = get_db_connection()
    try:
        prefix_rows = conn.execute(
            'SELECT id, prefix, name FROM prefixes'
        ).fetchall()
        
        prefixes_list = []
        for r in prefix_rows:
            try:
                prefixes_list.append({
                    'id': r['id'],
                    'prefix': r['prefix'],
                    'name': r['name'] or '',
                    'net': ipaddress.ip_network(r['prefix'], strict=False)
                })
            except ValueError:
                continue
        prefixes_list.sort(key=lambda x: x['net'].prefixlen, reverse=True)
        
        def find_matching_subnet(ip_str: str) -> Optional[dict]:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                return None
            for p in prefixes_list:
                if ip_obj in p['net']:
                    return p
            return None

        ip_rows = conn.execute(f'''
            SELECT ip.id, ip.address, ip.hostname, ip.mac_address, ip.subnet_id, ip.status,
                   ip.device_type, ip.interface_name,
                   p.prefix AS subnet_prefix, p.name AS subnet_name, p.network_type
            FROM ip_addresses ip
            LEFT JOIN prefixes p ON ip.subnet_id = p.id
        ''').fetchall()
        
        endpoint_rows = conn.execute('''
            SELECT id, ip, mac, hostname, vendor, switch_id, switch_port, vlan, vrf, site, last_seen
            FROM network_endpoints
            WHERE is_active = 1 AND ip IS NOT NULL AND ip != ''
        ''').fetchall()
        
        def normalize_mac(mac_str: Optional[str]) -> str:
            if not mac_str:
                return ''
            return mac_str.replace(':', '').replace('-', '').replace('.', '').strip().lower()

        ipam_map = {r['address']: dict(r) for r in ip_rows}
        endpoints_map = {r['ip']: dict(r) for r in endpoint_rows}
        
        undocumented_endpoints = []
        stale_ip_addresses = []
        mismatched_endpoints = []
        
        for ip, ep in endpoints_map.items():
            if ip not in ipam_map:
                p = find_matching_subnet(ip)
                undocumented_endpoints.append({
                    'ip': ip,
                    'mac': ep['mac'],
                    'hostname': ep['hostname'] or '',
                    'vendor': ep['vendor'] or '',
                    'switch_id': ep['switch_id'] or '',
                    'switch_port': ep['switch_port'] or '',
                    'vlan': ep['vlan'] or '',
                    'vrf': ep['vrf'] or '',
                    'site': ep['site'] or '',
                    'last_seen': ep['last_seen'] or '',
                    'subnet_id': p['id'] if p else '',
                    'subnet_prefix': p['prefix'] if p else '',
                    'subnet_name': p['name'] if p else (p['prefix'] if p else '')
                })
                
        for ip, ipam in ipam_map.items():
            if ip not in endpoints_map:
                # Exclude loopbacks and VIPs because they don't have switch port endpoints/ARP
                is_loopback_or_vip = (
                    (ipam.get('device_type') or '').lower() in ('loopback', 'vip') or
                    (ipam.get('interface_name') or '').lower().startswith('loopback') or
                    (ipam.get('network_type') or '').lower() in ('loopback', 'vip')
                )
                if is_loopback_or_vip:
                    continue

                stale_ip_addresses.append({
                    'id': ipam['id'],
                    'address': ip,
                    'hostname': ipam['hostname'] or '',
                    'mac_address': ipam['mac_address'] or '',
                    'subnet_id': ipam['subnet_id'] or '',
                    'subnet_prefix': ipam['subnet_prefix'] or '',
                    'subnet_name': ipam['subnet_name'] or '',
                    'status': ipam['status'] or 'active'
                })
            else:
                ep = endpoints_map[ip]
                mac_mismatch = False
                hostname_mismatch = False
                
                norm_ipam_mac = normalize_mac(ipam['mac_address'])
                norm_ep_mac = normalize_mac(ep['mac'])
                if norm_ipam_mac and norm_ep_mac and norm_ipam_mac != norm_ep_mac:
                    mac_mismatch = True
                    
                ipam_host = (ipam['hostname'] or '').strip().lower()
                ep_host = (ep['hostname'] or '').strip().lower()
                if ipam_host and ep_host and ipam_host != ep_host:
                    hostname_mismatch = True
                    
                if mac_mismatch or hostname_mismatch:
                    mismatched_endpoints.append({
                        'ip': ip,
                        'ipam_address_id': ipam['id'],
                        'ipam_hostname': ipam['hostname'] or '',
                        'endpoint_hostname': ep['hostname'] or '',
                        'ipam_mac': ipam['mac_address'] or '',
                        'endpoint_mac': ep['mac'] or '',
                        'subnet_id': ipam['subnet_id'] or '',
                        'subnet_prefix': ipam['subnet_prefix'] or '',
                        'subnet_name': ipam['subnet_name'] or '',
                        'mac_mismatch': mac_mismatch,
                        'hostname_mismatch': hostname_mismatch
                    })
                    
        return {
            'undocumented_endpoints': undocumented_endpoints,
            'stale_ip_addresses': stale_ip_addresses,
            'mismatched_endpoints': mismatched_endpoints,
            'summary': {
                'total_undocumented': len(undocumented_endpoints),
                'total_stale': len(stale_ip_addresses),
                'total_mismatched': len(mismatched_endpoints)
            }
        }
    finally:
        conn.close()
