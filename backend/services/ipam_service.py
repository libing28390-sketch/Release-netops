"""
IPAM Service — Business logic for IP/VLAN resource management.
Provides subnet and IP address CRUD with validation, overlap detection, and conflict scanning.
Extended with hierarchy tree, VRF-scoped uniqueness, pool/VIP/lease CRUD, and active endpoints.
"""

import uuid
import ipaddress
import logging
from datetime import datetime, timezone
from typing import Optional

from database import get_db_connection, _USE_PG

logger = logging.getLogger(__name__)

_GROUP_CONCAT = 'STRING_AGG({col}, \',\')' if _USE_PG else 'GROUP_CONCAT({col})'
_PH = '%s' if _USE_PG else '?'


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
                f'SELECT COUNT(*) as cnt FROM ip_addresses WHERE subnet_id = {_PH}',
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
    # Normalize CIDR
    try:
        net = ipaddress.ip_network(prefix, strict=False)
        prefix = str(net)  # Normalize e.g. 10.1.1.5/24 -> 10.1.1.0/24
    except ValueError as exc:
        raise ValueError(f"Invalid CIDR: {exc}") from exc

    conn = get_db_connection()
    try:
        # VRF-scoped duplicate check
        if vrf_id:
            existing = conn.execute(
                f'SELECT id FROM prefixes WHERE prefix = {_PH} AND vrf_id = {_PH}',
                (prefix, vrf_id),
            ).fetchone()
        else:
            existing = conn.execute(
                f'SELECT id FROM prefixes WHERE prefix = {_PH} AND (vrf_id IS NULL OR vrf_id = {_PH})',
                (prefix, ''),
            ).fetchone()

        if existing:
            raise ValueError('Prefix already exists in this VRF')

        prefix_id = f"prefix-{uuid.uuid4().hex[:12]}"
        now = _utc_now()

        conn.execute(
            f'''INSERT INTO prefixes
               (id, prefix, vrf_id, vlan_id, site_id, tenant_id, status,
                name, gateway, description, network_type, gateway_device_id,
                gateway_interface_id, traceable, created_at, updated_at)
               VALUES ({_ph(16)})''',
            (prefix_id, prefix, vrf_id or None, vlan_id or None, site_id or None,
             tenant_id, status, name, gateway, description, network_type,
             gateway_device_id or None, gateway_interface_id or None,
             traceable, now, now),
        )
        conn.commit()

        # Rebuild hierarchy after adding new prefix
        rebuild_prefixes_hierarchy(conn)

        logger.info("Created prefix %s (%s)", prefix_id, prefix)
        return {'id': prefix_id, 'total_ips': _calculate_total_ips(prefix)}
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

        allowed_fields = (
            'name', 'vrf_id', 'vlan_id', 'site_id', 'tenant_id', 'status',
            'gateway', 'description', 'prefix', 'network_type',
            'gateway_device_id', 'gateway_interface_id', 'traceable',
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
) -> dict:
    """Add an IP address after validating it belongs to the subnet."""
    conn = get_db_connection()
    try:
        subnet = conn.execute(
            f'SELECT * FROM prefixes WHERE id = {_PH}', (subnet_id,)
        ).fetchone()
        if not subnet:
            raise ValueError('Subnet not found')

        # Parse prefix to validate
        try:
            net = ipaddress.ip_network(subnet['prefix'], strict=False)
        except ValueError:
            raise ValueError('Invalid subnet prefix')

        if ipaddress.ip_address(address) not in net:
            raise ValueError(f"Address {address} is not within subnet {net}")

        # Duplicate check
        existing = conn.execute(
            f'SELECT id FROM ip_addresses WHERE subnet_id = {_PH} AND address = {_PH}',
            (subnet_id, address),
        ).fetchone()
        if existing:
            raise ValueError('IP address already registered in this subnet')

        addr_id = f"ip-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        conn.execute(
            f'''INSERT INTO ip_addresses
               (id, subnet_id, address, hostname, device_id, interface_name,
                mac_address, device_type, status, description, last_seen, created_at, updated_at)
               VALUES ({_ph(13)})''',
            (addr_id, subnet_id, address, hostname, device_id,
             interface_name, mac_address, device_type, status, description, now, now, now),
        )
        conn.commit()
        return {'id': addr_id}
    finally:
        conn.close()


def update_address(address_id: str, **fields) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT * FROM ip_addresses WHERE id = {_PH}', (address_id,)
        ).fetchone()
        if not row:
            return False

        updates = []
        params = []
        for field in ('hostname', 'device_id', 'interface_name', 'mac_address',
                      'device_type', 'description', 'status'):
            val = fields.get(field)
            if val is not None:
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


# ══════════════════════════════════════════════════════════
# Conflict Detection
# ══════════════════════════════════════════════════════════

def detect_conflicts() -> dict:
    """Scan for duplicate IPs across subnets and duplicate MACs."""
    conn = get_db_connection()
    try:
        dup_ips = conn.execute(f'''
            SELECT address, {_GROUP_CONCAT.format(col='subnet_id')} as subnets, COUNT(*) as cnt
            FROM ip_addresses GROUP BY address HAVING cnt > 1
        ''').fetchall()

        dup_macs = conn.execute(f'''
            SELECT mac_address, {_GROUP_CONCAT.format(col='address')} as addresses, COUNT(*) as cnt
            FROM ip_addresses
            WHERE mac_address != '' AND mac_address IS NOT NULL
            GROUP BY mac_address HAVING cnt > 1
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

        total_used = conn.execute('SELECT COUNT(*) as total FROM ip_addresses').fetchone()

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
                f'SELECT COUNT(*) as cnt FROM ip_addresses WHERE subnet_id = {_PH}',
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
    conn = get_db_connection()
    try:
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
    conn = get_db_connection()
    try:
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
            
        allocated_rows = conn.execute(
            f'SELECT address FROM ip_addresses WHERE subnet_id = {_PH}', (subnet_id,)
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
