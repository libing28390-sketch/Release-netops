"""
IPAM Service — Business logic for IP/VLAN resource management.
Provides subnet and IP address CRUD with validation, overlap detection, and conflict scanning.
Extended with hierarchy tree, VRF-scoped uniqueness, pool/VIP/lease CRUD, and active endpoints.
"""

import uuid
import ipaddress
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from core.interface_utils import normalize_interface_name
from services.ipam_inventory_scope import (
    endpoint_address_key, endpoint_site_id, load_inventory_catalog,
    manual_address_key, match_inventory_prefix,
)

from database import get_db_connection

logger = logging.getLogger(__name__)

_GROUP_CONCAT = 'STRING_AGG({col}, \',\')'
_PH = '?'

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

PREFIX_TO_IP_PURPOSE = {
    'management': 'management',
    'server': 'business',
    'user': 'business',
    'user_access': 'business',
    'dmz': 'business',
    'wireless': 'business',
    'voice': 'business',
    'storage': 'business',
    'container': 'business',
    'network_service': 'infrastructure',
    'transit': 'transit',
    'p2p': 'transit',
    'wan': 'transit',
    'loopback': 'loopback',
    'vip': 'vip',
    'vpn': 'business',
}


def _infer_ip_purpose(network_type: str | None) -> str:
    return PREFIX_TO_IP_PURPOSE.get(str(network_type or '').strip().lower(), 'business')


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


CROSS_SITE_REUSE_CONDITION = """(
    COALESCE(p.is_active, 1) = 1
    AND COALESCE(p.status, '') <> 'stale'
    AND COALESCE(p.site_id, '') <> ''
    AND EXISTS (
        SELECT 1
        FROM prefixes other_prefix
        WHERE other_prefix.prefix = p.prefix
          AND COALESCE(other_prefix.tenant_id, 'tenant-default') = COALESCE(p.tenant_id, 'tenant-default')
          AND COALESCE(other_prefix.site_id, '') <> ''
          AND other_prefix.site_id <> p.site_id
          AND COALESCE(other_prefix.is_active, 1) = 1
          AND COALESCE(other_prefix.status, '') <> 'stale'
    )
)"""

_PREFIX_CLASSIFICATION_FILTERS = {
    'auto': "COALESCE(p.classification_status, 'manual') = 'auto'",
    'manual': "(COALESCE(p.manual_override, 0) = 1 OR COALESCE(p.source_type, '') = 'manual')",
    'unclassified': "COALESCE(p.network_type, 'unclassified') = 'unclassified'",
    'mixed': 'COALESCE(p.mixed_network, 0) = 1',
    # cross_site_prefix was historically written for legitimate site-local
    # address reuse. Keep it out of real conflict counts and filters.
    'conflict': "COALESCE(p.conflict_status, '') NOT IN ('', 'cross_site_prefix')",
    'reuse': CROSS_SITE_REUSE_CONDITION,
    'stale': "(COALESCE(p.is_active, 1) = 0 OR COALESCE(p.status, '') = 'stale')",
}


def build_prefix_filter_clause(
    *, site: str = 'all', status: str = 'all', q: str = '', family: str = 'all',
    classification: str = 'all',
) -> tuple[str, tuple]:
    clauses = ['1=1']
    params: list = []
    if site and site != 'all':
        clauses.append(f'p.site_id = {_PH}')
        params.append(site)
    if status and status != 'all':
        clauses.append(f'p.status = {_PH}')
        params.append(status)
    if family == 'ipv4':
        clauses.append("p.prefix NOT LIKE '%:%'")
    elif family == 'ipv6':
        clauses.append("p.prefix LIKE '%:%'")
    if q and q.strip():
        fuzzy = f'%{q.strip().lower()}%'
        clauses.append(f'(LOWER(p.name) LIKE {_PH} OR LOWER(p.prefix) LIKE {_PH} OR LOWER(p.description) LIKE {_PH})')
        params.extend([fuzzy, fuzzy, fuzzy])
    if classification and classification != 'all':
        filter_sql = _PREFIX_CLASSIFICATION_FILTERS.get(classification)
        if filter_sql is None:
            raise ValueError(f'Unsupported prefix classification: {classification}')
        clauses.append(filter_sql)
    return ' AND '.join(clauses), tuple(params)


def _cross_site_reuse_ids(conn, rows: list[dict]) -> set[str]:
    """Find current page rows whose CIDR is reused across assigned sites.

    Site is an IPAM address-space boundary. The same CIDR may be valid in
    another site or VRF, so reuse is reported separately from conflict_status.
    """
    ids = [str(row.get('id') or '') for row in rows if row.get('id')]
    if not ids:
        return set()
    placeholders = ', '.join(_PH for _ in ids)
    matches = conn.execute(
        f'SELECT p.id FROM prefixes p WHERE p.id IN ({placeholders}) AND {CROSS_SITE_REUSE_CONDITION}',
        tuple(ids),
    ).fetchall()
    return {str(row['id']) for row in matches}


def _table_columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _table_exists(conn, table: str) -> bool:
    return bool(_table_columns(conn, table))


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


def _capacity_exclusion_reason(prefix_str: str, status: str = '') -> str:
    """Return why a prefix must not contribute to allocatable capacity."""
    if (status or '').strip().lower() == 'container':
        return 'container_prefix'
    try:
        net = ipaddress.ip_network(prefix_str, strict=False)
    except ValueError:
        return 'invalid_prefix'
    if net.prefixlen == net.max_prefixlen:
        return 'host_route'
    if net.prefixlen == net.max_prefixlen - 1:
        return 'point_to_point'
    return ''


def _is_capacity_prefix(prefix_str: str, status: str = '') -> bool:
    return not _capacity_exclusion_reason(prefix_str, status)


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


def _configured_prefix_gateway(prefix: dict) -> str:
    """Return a usable gateway only when it belongs to the prefix."""
    raw_gateway = str(prefix.get('gateway') or '').strip()
    if not raw_gateway:
        return ''
    try:
        network = ipaddress.ip_network(str(prefix.get('prefix') or ''), strict=False)
        gateway = ipaddress.ip_address(raw_gateway)
    except ValueError:
        return ''
    if gateway.version != network.version or gateway not in network:
        return ''
    if network.version == 4 and network.prefixlen < 31:
        if gateway in (network.network_address, network.broadcast_address):
            return ''
    return str(gateway)


def _count_prefix_used_ips(conn, prefix: dict) -> int:
    """Count distinct manually registered addresses and the configured gateway."""
    prefix_id = str(prefix.get('id') or '')
    rows = conn.execute(
        f"""SELECT address FROM ip_addresses WHERE subnet_id = {_PH}
             AND COALESCE(status, 'active') NOT IN ('released', 'available')""",
        (prefix_id,),
    ).fetchall()
    used: set[str] = set()
    for row in rows:
        try:
            used.add(_normalize_address(row['address'] or ''))
        except ValueError:
            continue
    gateway = _configured_prefix_gateway(prefix)
    if gateway:
        used.add(gateway)
    return len(used)


def _mark_prefix_gateway_item(item: dict, prefix: dict, *, virtual: bool = False) -> dict:
    """Annotate one inventory row as the gateway configured on its prefix."""
    item['is_prefix_gateway'] = True
    item['is_virtual_gateway'] = virtual
    item['gateway_device_name'] = prefix.get('gateway_device_name') or ''
    item['device_type'] = 'gateway'
    item['purpose'] = item.get('purpose') or 'infrastructure'
    if not item.get('device_id') and prefix.get('gateway_device_id'):
        item['device_id'] = prefix['gateway_device_id']
    if not item.get('bound_device_hostname'):
        item['bound_device_hostname'] = prefix.get('gateway_device_name') or ''
    if item.get('status') in ('available', 'released', None, ''):
        item['status'] = 'active'
    return item


def _build_prefix_gateway_item(prefix: dict, gateway: str) -> dict:
    """Build a read-only inventory view for a gateway not in ip_addresses."""
    item = {
        'id': f"prefix-gateway-{prefix['id']}",
        'subnet_id': prefix['id'],
        'tenant_id': prefix.get('tenant_id') or 'tenant-default',
        'vrf_id': prefix.get('vrf_id') or '',
        'address': gateway,
        'hostname': prefix.get('gateway_device_name') or '',
        'device_id': prefix.get('gateway_device_id') or '',
        'interface_name': '',
        'mac_address': '',
        'device_type': 'gateway',
        'purpose': 'infrastructure',
        'status': 'active',
        'description': '',
        'last_seen': '',
        'created_at': '',
        'updated_at': '',
        'subnet_prefix': prefix.get('prefix') or '',
        'subnet_name': prefix.get('name') or '',
        'network_type': prefix.get('network_type') or '',
        'site_id': prefix.get('site_id') or '',
        'site_name': prefix.get('site_name') or '未分配站点',
        'source': 'prefix_gateway',
        'is_discovered': False,
        'discovered_last_seen': '',
        'switch_name': '',
        'switch_port': '',
        'vlan': '',
    }
    return _mark_prefix_gateway_item(item, prefix, virtual=True)


def _current_cmdb_interface_ip_observations(conn) -> list[dict]:
    """Return IP-bearing interface rows fenced to each device's last good CMDB snapshot."""
    rows = conn.execute(
        """SELECT o.device_id, o.normalized_interface_name, o.interface_name,
                  o.ip_address, o.ip_prefix_length, o.interface_type, o.observed_at,
                  d.hostname AS device_hostname, d.ip_address AS device_ip,
                  COALESCE(d.tenant_id, 'tenant-default') AS tenant_id,
                  d.site_id AS device_site_id, d.site AS device_site,
                  pa.site_id AS asset_site_id
           FROM cmdb_device_interface_observations o
           JOIN cmdb_collection_snapshots s ON s.device_id = o.device_id
                AND s.domain = 'interface_inventory'
                AND s.successful_generation = o.generation
           JOIN devices d ON d.id = o.device_id
           LEFT JOIN physical_assets pa ON pa.id = d.asset_id
           WHERE COALESCE(o.ip_address, '') <> ''
           ORDER BY d.hostname, o.normalized_interface_name"""
    ).fetchall()
    return [dict(row) for row in rows]


def _address_matches_pool(address: str, pool: dict) -> bool:
    try:
        candidate = ipaddress.ip_address(address)
        start = ipaddress.ip_address(str(pool.get('start_ip') or '').strip())
        end = ipaddress.ip_address(str(pool.get('end_ip') or '').strip())
    except (TypeError, ValueError):
        return False
    return candidate.version == start.version == end.version and start <= candidate <= end


def _validate_address_policy(subnet, address: str, *, device_type: str = '', purpose: str = '') -> None:
    """Reject addresses that are structurally or administratively unavailable.

    Standard IPv4 network and broadcast addresses are not host allocations.  A
    prefix gateway is also protected from ordinary allocations, but it may be
    registered explicitly as a gateway address so the IPAM record can carry
    its device/interface ownership.
    """
    net = ipaddress.ip_network(subnet['prefix'], strict=False)
    ip_obj = ipaddress.ip_address(address)
    if net.version == 4 and net.prefixlen < 31:
        if ip_obj == net.network_address:
            raise ValueError(f"Network address {address} cannot be allocated")
        if ip_obj == net.broadcast_address:
            raise ValueError(f"Broadcast address {address} cannot be allocated")

    gateway = str(subnet['gateway'] or '').strip()
    if gateway:
        try:
            gateway = _normalize_address(gateway)
        except ValueError:
            gateway = ''
    gateway_role = str(device_type or '').strip().lower() == 'gateway' or str(purpose or '').strip().lower() == 'gateway'
    if gateway and gateway == address and not gateway_role:
        raise ValueError(f"Gateway address {address} is reserved; use the gateway role to register it")


def _active_discovered_addresses(conn, network: ipaddress._BaseNetwork) -> set[str]:
    """Return active discovery facts that fall inside *network*.

    Discovery data is an occupancy signal even when an operator has not yet
    created a manual IPAM record. Suggestions and automatic allocation must
    therefore treat these addresses as unavailable.
    """
    if not _table_exists(conn, 'network_endpoints'):
        return set()
    rows = conn.execute(
        "SELECT ip FROM network_endpoints "
        "WHERE is_active = 1 AND COALESCE(ip, '') <> ''"
    ).fetchall()
    occupied: set[str] = set()
    for row in rows:
        try:
            candidate = ipaddress.ip_address(str(row['ip']).strip())
        except (TypeError, ValueError):
            continue
        if candidate.version == network.version and candidate in network:
            occupied.add(str(candidate))
    return occupied


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
    vip = None
    if _table_exists(conn, 'ipam_vips'):
        vip = conn.execute(
            f"""SELECT id FROM ipam_vips
                WHERE address = {_PH} AND COALESCE(tenant_id, 'tenant-default') = {_PH}
                  AND COALESCE(status, 'active') NOT IN ('released', 'deprecated') LIMIT 1""",
            (address, tenant_id),
        ).fetchone()
    if vip:
        try:
            from core.metrics import metrics_registry
            metrics_registry.record_ipam_conflict()
        except Exception:
            pass
        raise ValueError(f'IP address {address} conflicts with an active VIP')
    lease = None
    if _table_exists(conn, 'ipam_dhcp_leases'):
        lease = conn.execute(
            f"""SELECT id FROM ipam_dhcp_leases
                WHERE address = {_PH} AND COALESCE(lease_state, 'active') IN ('active', 'offered')
                LIMIT 1""",
            (address,),
        ).fetchone()
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
    return conn.execute(
        f"SELECT * FROM prefixes WHERE id = {_PH} FOR UPDATE",
        (subnet_id,),
    ).fetchone()


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

def list_subnets(
    *, site: str = 'all', status: str = 'all', q: str = '', family: str = 'all',
    classification: str = 'all', page: int | None = None, page_size: int = 20,
) -> list[dict] | dict:
    conn = get_db_connection()
    try:
        where_sql, filter_params = build_prefix_filter_clause(
            site=site, status=status, q=q, family=family, classification=classification,
        )
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
            WHERE {where_sql}
        '''
        params: list = list(filter_params)
        sql += ' ORDER BY COALESCE(s.site_name, s.site_code, p.site_id, \'\'), p.prefix'
        total: int | None = None
        normalized_page_size = min(max(int(page_size or 20), 1), 100)
        normalized_page = max(int(page or 1), 1)
        if page is not None:
            count_sql = f'SELECT COUNT(*) AS cnt FROM prefixes p WHERE {where_sql}'
            count_row = conn.execute(count_sql, filter_params).fetchone()
            total = int(count_row['cnt'] if count_row else 0)
            sql += f' LIMIT {_PH} OFFSET {_PH}'
            params.extend([normalized_page_size, (normalized_page - 1) * normalized_page_size])
        rows = conn.execute(sql, tuple(params)).fetchall()
        raw_items = [dict(row) for row in rows]
        reuse_ids = _cross_site_reuse_ids(conn, raw_items)
        result = []
        for r, item in zip(rows, raw_items):
            item['cross_site_reuse'] = str(item.get('id') or '') in reuse_ids
            if str(item.get('conflict_status') or '') == 'cross_site_prefix':
                # Old versions persisted legitimate cross-site reuse as a
                # conflict. Hide that legacy label in API responses without
                # rewriting historical rows in the live database.
                item['conflict_status'] = ''
                item['conflict_json'] = '{}'

            prefix_str = item.get('prefix', '')
            total_ips = _calculate_total_ips(prefix_str)
            item['total_ips'] = total_ips

            # A configured gateway consumes an address even before an operator
            # creates a separate IPAM address record for it.
            used_ips = _count_prefix_used_ips(conn, item)
            item['used_ips'] = used_ips

            # Count active endpoints from network_endpoints if table exists
            try:
                gateway = _configured_prefix_gateway(item)
                gateway_clause = f' OR ip = {_PH}' if gateway else ''
                endpoint_params = (r['id'], gateway) if gateway else (r['id'],)
                active = conn.execute(
                    f'''SELECT COUNT(DISTINCT ip) as cnt FROM network_endpoints
                        WHERE is_active = 1 AND (ip IN (
                            SELECT address FROM ip_addresses WHERE subnet_id = {_PH}
                              AND COALESCE(status, 'active') NOT IN ('released', 'available')
                        ){gateway_clause})''',
                    endpoint_params,
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
        if page is None:
            return result
        return {
            'items': result,
            'total': total or 0,
            'page': normalized_page,
            'page_size': normalized_page_size,
        }
    finally:
        conn.close()


def _parse_interface_prefix_length(value) -> Optional[int]:
    """Normalize an interface prefix length or netmask to an integer."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.startswith('/'):
        raw = raw[1:].strip()
    try:
        if '.' in raw:
            mask = ipaddress.IPv4Network(f'0.0.0.0/{raw}').prefixlen
        else:
            mask = int(raw)
    except (ValueError, TypeError):
        return None
    return mask if 0 <= mask <= 128 else None


def get_prefix_gateway_candidates(
    *, prefix: str, site_id: str | None, tenant_id: str, gateway_ip: str | None = None,
) -> dict:
    """Read the latest successful CLI interface snapshot for gateway evidence.

    Interface observations are returned only as candidate evidence. They are
    never copied into ``interfaces``, ``ip_inventory`` or prefix ownership.
    """
    if not site_id:
        return {
            'status': 'needs_site', 'prefix': prefix, 'site_id': None,
            'gateway_ip': gateway_ip or None, 'selected': None, 'endpoints': [],
        }
    try:
        network = ipaddress.ip_network(str(prefix or '').strip(), strict=False)
    except ValueError as exc:
        raise ValueError('Invalid prefix CIDR') from exc
    try:
        normalized_gateway = str(ipaddress.ip_address(gateway_ip)) if gateway_ip else None
    except ValueError as exc:
        raise ValueError('Invalid gateway IP') from exc

    conn = get_db_connection()
    try:
        _, sites, _ = load_inventory_catalog(conn)
        observation_rows = _current_cmdb_interface_ip_observations(conn)
        candidates: list[dict] = []
        for row in observation_rows:
            if str(row.get('tenant_id') or 'tenant-default') != str(tenant_id or 'tenant-default'):
                continue
            owner = {
                'cmdb_device_id': row.get('device_id'),
                'asset_site_id': row.get('asset_site_id'),
                'device_site_id': row.get('device_site_id'),
                'device_site': row.get('device_site'),
            }
            if endpoint_site_id(owner, sites) != str(site_id):
                continue
            raw_address = str(row.get('ip_address') or '').strip()
            try:
                address = _normalize_address(raw_address)
                address_obj = ipaddress.ip_address(address)
            except ValueError:
                continue
            if address_obj.version != network.version or address_obj not in network:
                continue
            candidates.append({
                'device_id': str(row.get('device_id') or ''),
                'device_name': str(row.get('device_hostname') or ''),
                'interface_name': str(row.get('interface_name') or ''),
                'interface_id': None,
                'address': address,
                'interface_type': str(row.get('interface_type') or '').strip().lower(),
                '_normalized_interface_name': str(row.get('normalized_interface_name') or '').strip().lower(),
            })

        device_ids = sorted({item['device_id'] for item in candidates if item['device_id']})
        interface_ids_by_key: dict[tuple[str, str], list[str]] = {}
        if device_ids:
            placeholders = ', '.join(_PH for _ in device_ids)
            interface_rows = conn.execute(
                f'''SELECT id, device_id, interface_name
                    FROM interfaces
                    WHERE device_id IN ({placeholders})''',
                tuple(device_ids),
            ).fetchall()
            for interface_row in interface_rows:
                normalized_name = normalize_interface_name(str(interface_row['interface_name'] or '')).strip().lower()
                key = (str(interface_row['device_id'] or ''), normalized_name)
                interface_ids_by_key.setdefault(key, []).append(str(interface_row['id']))

        for item in candidates:
            key = (item['device_id'], item.pop('_normalized_interface_name'))
            matching_ids = interface_ids_by_key.get(key, [])
            if len(matching_ids) == 1:
                item['interface_id'] = matching_ids[0]

        candidates.sort(key=lambda item: (
            ipaddress.ip_address(item['address']).version,
            int(ipaddress.ip_address(item['address'])),
            item['device_name'].lower(),
            item['interface_name'].lower(),
        ))

        if normalized_gateway:
            exact_matches = [item for item in candidates if item['address'] == normalized_gateway]
            if len(exact_matches) == 1:
                status, selected = 'matched', exact_matches[0]
            elif exact_matches:
                status, selected = 'no_unique_gateway', None
            else:
                status, selected = 'no_candidate', None
        else:
            svi_candidates = [item for item in candidates if item['interface_type'] == 'svi']
            if len(svi_candidates) == 1:
                status, selected = 'matched', svi_candidates[0]
            elif candidates:
                status, selected = 'no_unique_gateway', None
            else:
                status, selected = 'no_candidate', None

        # Strip internal mapping keys and return exactly the candidate shape
        # shared by the selected item and the evidence list.
        endpoint_fields = (
            'device_id', 'device_name', 'interface_name', 'interface_id',
            'address', 'interface_type',
        )
        endpoints = [{key: item[key] for key in endpoint_fields} for item in candidates]
        selected_result = (
            {key: selected[key] for key in endpoint_fields}
            if selected else None
        )
        return {
            'status': status,
            'prefix': str(network),
            'site_id': str(site_id),
            'gateway_ip': normalized_gateway,
            'selected': selected_result,
            'endpoints': endpoints,
        }
    finally:
        conn.close()


def _loopback_prefix_length(interface_name: str, ip_obj: ipaddress._BaseAddress) -> Optional[int]:
    """Use a host prefix only when the interface is explicitly a loopback."""
    name = str(interface_name or '').strip().lower()
    if name.startswith('loopback') or name.startswith('lo'):
        return 32 if ip_obj.version == 4 else 128
    return None


def _interface_prefix_candidate_id(prefix: str, tenant_id: str, site_id: str, vrf_id: str) -> str:
    return f'{prefix}|{tenant_id or "tenant-default"}|{site_id or ""}|{vrf_id or ""}'


def _load_interface_prefix_candidates(
    conn,
    *,
    include_all_interfaces: bool = False,
    skipped_sample_limit: int = 25,
) -> dict:
    """Build IPAM candidates from the current L3 interface collection.

    ``interfaces`` is the authoritative current interface source.  ``ip_inventory``
    is consulted only for a missing mask because older collectors stored the mask
    there; it is deliberately never returned as IPAM data and is never migrated by
    this function.
    """
    interface_rows = conn.execute(
        '''SELECT i.id, i.device_id, i.interface_name, i.primary_ip, i.ip_address,
                  i.ip_prefix_length, i.ip_version, i.is_l3, i.ip_enabled,
                  i.vrf_id, i.last_seen, d.hostname, d.ip_address AS device_ip,
                  d.site_id, d.tenant_id, d.platform, d.device_type_id
           FROM interfaces i
           JOIN devices d ON d.id = i.device_id
            WHERE (COALESCE(i.is_l3, FALSE) = TRUE OR COALESCE(i.ip_enabled, 0) = 1)
             AND (COALESCE(i.primary_ip, '') <> '' OR COALESCE(i.ip_address, '') <> '')
           ORDER BY d.hostname, i.interface_name'''
    ).fetchall()

    inventory_by_interface: dict[tuple[str, str], dict] = {}
    try:
        inventory_rows = conn.execute(
            '''SELECT device_id, interface, mask, last_seen
               FROM ip_inventory
               WHERE COALESCE(ip, '') <> ''
               ORDER BY last_seen DESC'''
        ).fetchall()
        for row in inventory_rows:
            key = (str(row['device_id'] or ''), normalize_interface_name(row['interface']))
            inventory_by_interface.setdefault(key, dict(row))
    except Exception:
        # IPAM generation must still work if the optional collection snapshot is
        # unavailable on an older installation.
        try:
            conn.rollback()
        except Exception:
            pass

    existing_rows = conn.execute(
        'SELECT id, prefix, tenant_id, site_id, vrf_id, name FROM prefixes'
    ).fetchall()
    existing_by_scope = {
        _interface_prefix_candidate_id(
            str(row['prefix'] or ''),
            str(row['tenant_id'] or 'tenant-default'),
            str(row['site_id'] or ''),
            str(row['vrf_id'] or ''),
        ): dict(row)
        for row in existing_rows
    }

    candidates: dict[str, dict] = {}
    skipped: list[dict] = []
    skipped_count = 0
    interface_count = 0

    def record_skipped(item: dict) -> None:
        nonlocal skipped_count
        skipped_count += 1
        if len(skipped) < skipped_sample_limit:
            skipped.append(item)

    for row in interface_rows:
        interface_count += 1
        raw_address = str(row['primary_ip'] or row['ip_address'] or '').strip()
        address = raw_address.split('/', 1)[0].strip()
        try:
            ip_obj = ipaddress.ip_address(address)
        except ValueError:
            record_skipped({
                'interface_id': row['id'],
                'device_name': row['hostname'],
                'interface_name': row['interface_name'],
                'address': raw_address,
                'reason': '接口 IP 不是合法地址',
            })
            continue

        prefix_len = _parse_interface_prefix_length(row['ip_prefix_length'])
        if '/' in raw_address and prefix_len is None:
            prefix_len = _parse_interface_prefix_length(raw_address.rsplit('/', 1)[1])
        if prefix_len is None:
            snapshot = inventory_by_interface.get((str(row['device_id']), normalize_interface_name(row['interface_name'])))
            prefix_len = _parse_interface_prefix_length(snapshot.get('mask') if snapshot else None)
        if prefix_len is None:
            prefix_len = _loopback_prefix_length(row['interface_name'], ip_obj)
        if prefix_len is None or (ip_obj.version == 4 and prefix_len > 32):
            record_skipped({
                'interface_id': row['id'],
                'device_name': row['hostname'],
                'interface_name': row['interface_name'],
                'address': address,
                'reason': '接口采集结果缺少前缀长度/掩码',
            })
            continue

        try:
            network = ipaddress.ip_interface(f'{address}/{prefix_len}').network
        except ValueError:
            record_skipped({
                'interface_id': row['id'],
                'device_name': row['hostname'],
                'interface_name': row['interface_name'],
                'address': address,
                'reason': '接口 IP 与前缀长度无法组成有效网段',
            })
            continue

        prefix = str(network)
        tenant_id = str(row['tenant_id'] or 'tenant-default')
        site_id = str(row['site_id'] or '')
        vrf_id = str(row['vrf_id'] or '')
        candidate_id = _interface_prefix_candidate_id(prefix, tenant_id, site_id, vrf_id)
        item = candidates.setdefault(candidate_id, {
            'candidate_id': candidate_id,
            'prefix': prefix,
            'tenant_id': tenant_id,
            'site_id': site_id or None,
            'vrf_id': vrf_id or None,
            'status': 'existing' if candidate_id in existing_by_scope else 'to_create',
            'existing_prefix_id': (existing_by_scope.get(candidate_id) or {}).get('id'),
            'existing_prefix_name': (existing_by_scope.get(candidate_id) or {}).get('name') or '',
            'interface_count': 0,
            'ip_count': 0,
            'interfaces': [],
        })
        item['interface_count'] += 1
        item['ip_count'] += 1
        if include_all_interfaces or len(item['interfaces']) < 3:
            item['interfaces'].append({
                'interface_id': row['id'],
                'device_id': row['device_id'],
                'device_name': row['hostname'],
                'device_ip': row['device_ip'],
                'interface_name': row['interface_name'],
                'address': address,
            })

    result_candidates = sorted(candidates.values(), key=lambda item: item['prefix'])
    return {
        'source': 'interfaces',
        'source_label': '当前接口采集结果',
        'interface_count': interface_count,
        'candidate_count': len(result_candidates),
        'existing_count': sum(1 for item in result_candidates if item['status'] == 'existing'),
        'to_create_count': sum(1 for item in result_candidates if item['status'] == 'to_create'),
        'skipped_count': skipped_count,
        'candidates': result_candidates,
        'skipped': skipped,
        'skipped_truncated_count': skipped_count - len(skipped),
    }


def preview_interface_prefixes(*, page: int = 1, page_size: int = 25, status: str = 'all') -> dict:
    """Preview canonical prefixes that can be generated from current interfaces."""
    if page < 1:
        raise ValueError('page 必须大于等于 1')
    if page_size < 1 or page_size > 100:
        raise ValueError('page_size 必须在 1 到 100 之间')
    if status not in {'all', 'to_create', 'existing'}:
        raise ValueError('status 必须为 all、to_create 或 existing')

    conn = get_db_connection()
    try:
        preview = _load_interface_prefix_candidates(conn, skipped_sample_limit=25)
    finally:
        conn.close()

    filtered_candidates = [
        item for item in preview['candidates']
        if status == 'all' or item['status'] == status
    ]
    filtered_count = len(filtered_candidates)
    start = (page - 1) * page_size
    total_pages = (filtered_count + page_size - 1) // page_size
    return {
        'source': preview['source'],
        'source_label': preview['source_label'],
        'candidate_count': preview['candidate_count'],
        'existing_count': preview['existing_count'],
        'to_create_count': preview['to_create_count'],
        'interface_count': preview['interface_count'],
        'skipped_count': preview['skipped_count'],
        'page': page,
        'page_size': page_size,
        'filtered_count': filtered_count,
        'total_pages': total_pages,
        'candidates': filtered_candidates[start:start + page_size],
        'skipped': preview['skipped'],
        'skipped_truncated_count': preview['skipped_truncated_count'],
    }


def generate_interface_prefixes(
    candidate_ids: Optional[list[str]] = None,
    *,
    all_pending: bool = False,
) -> dict:
    """Create canonical prefixes and interface IP records from current interfaces.

    The operation is idempotent: existing prefixes and addresses are preserved,
    while only missing canonical records are added.  No legacy IPAM table is read
    as a source and no collection-cache row is deleted.
    """
    conn = get_db_connection()
    created_prefixes = 0
    created_addresses = 0
    existing_prefixes = 0
    existing_addresses = 0
    skipped_addresses: list[dict] = []
    try:
        preview = _load_interface_prefix_candidates(conn, include_all_interfaces=True)
        if all_pending and candidate_ids is not None:
            raise ValueError('candidate_ids 与 all_pending 不能同时提供')
        if all_pending:
            selected = [item for item in preview['candidates'] if item['status'] == 'to_create']
        elif candidate_ids is None:
            raise ValueError('请提供非空 candidate_ids，或显式设置 all_pending=true')
        else:
            requested = {str(value).strip() for value in candidate_ids if str(value).strip()}
            if not requested:
                raise ValueError('candidate_ids 不能为空；如需一键生成待创建网段，请显式设置 all_pending=true')
            current_ids = {item['candidate_id'] for item in preview['candidates']}
            unknown_ids = sorted(requested - current_ids)
            if unknown_ids:
                sample = ', '.join(unknown_ids[:5])
                remainder = len(unknown_ids) - min(len(unknown_ids), 5)
                suffix = f' 等 {remainder} 项' if remainder else ''
                raise ValueError(f'候选已不存在或已变化，请刷新预览后重试：{sample}{suffix}')
            selected = [
                item for item in preview['candidates']
                if item['candidate_id'] in requested
            ]
        now = _utc_now()
        prefix_ids: dict[str, str] = {}

        for candidate in selected:
            candidate_id = candidate['candidate_id']
            existing = conn.execute(
                f'''SELECT id FROM prefixes
                    WHERE prefix = {_PH}
                      AND COALESCE(tenant_id, 'tenant-default') = {_PH}
                      AND COALESCE(site_id, '') = {_PH}
                      AND COALESCE(vrf_id, '') = {_PH}''',
                (candidate['prefix'], candidate['tenant_id'], candidate['site_id'] or '', candidate['vrf_id'] or ''),
            ).fetchone()
            if existing:
                prefix_ids[candidate_id] = existing['id']
                existing_prefixes += 1
                continue

            normalized, network = _normalize_prefix(candidate['prefix'])
            _validate_prefix_overlap(
                conn,
                prefix=normalized,
                tenant_id=candidate['tenant_id'],
                vrf_id=candidate['vrf_id'],
                site_id=candidate['site_id'],
            )
            prefix_id = f'prefix-{uuid.uuid4().hex[:12]}'
            network_type = 'transit' if (
                (network.version == 4 and network.prefixlen in (30, 31))
                or (network.version == 6 and network.prefixlen == 127)
            ) else 'server'
            conn.execute(
                f'''INSERT INTO prefixes
                   (id, prefix, vrf_id, site_id, tenant_id, status, name,
                    description, network_type, created_at, updated_at,
                    prefix_cidr, ip_version, prefix_len, traceable,
                    source_type, source_ref)
                   VALUES ({_ph(17)})''',
                (
                    prefix_id, normalized, candidate['vrf_id'], candidate['site_id'],
                    candidate['tenant_id'], 'active', f'接口采集 · {normalized}',
                    '由当前接口采集结果生成；不会读取旧 IPAM 前缀', network_type,
                    now, now, normalized, network.version, network.prefixlen, 1,
                    'interface_collection', 'interface-collection',
                ),
            )
            prefix_ids[candidate_id] = prefix_id
            created_prefixes += 1

        # Address creation is deliberately scoped to the selected candidate and
        # leaves existing manually managed address metadata untouched.
        for candidate in selected:
            subnet_id = prefix_ids.get(candidate['candidate_id'])
            if not subnet_id:
                continue
            for interface in candidate['interfaces']:
                existing_address = conn.execute(
                    f'''SELECT id FROM ip_addresses
                        WHERE subnet_id = {_PH} AND address = {_PH}''',
                    (subnet_id, interface['address']),
                ).fetchone()
                if existing_address:
                    existing_addresses += 1
                    continue
                try:
                    _create_address_with_conn(
                        conn,
                        subnet_id,
                        address=interface['address'],
                        hostname=interface['device_name'],
                        device_id=interface['device_id'],
                        interface_name=interface['interface_name'],
                        interface_id=interface['interface_id'],
                        device_type='interface',
                        status='active',
                        source_type='interface_collection',
                        source_ref=interface['interface_id'],
                    )
                    created_addresses += 1
                except ValueError as exc:
                    skipped_addresses.append({
                        'prefix': candidate['prefix'],
                        'device_name': interface['device_name'],
                        'interface_name': interface['interface_name'],
                        'address': interface['address'],
                        'reason': str(exc),
                    })

        conn.commit()
        rebuild_prefixes_hierarchy(conn)
        return {
            'ok': True,
            'source': 'interfaces',
            'selected_count': len(selected),
            'created_prefixes': created_prefixes,
            'existing_prefixes': existing_prefixes,
            'created_addresses': created_addresses,
            'existing_addresses': existing_addresses,
            'skipped_addresses': skipped_addresses,
        }
    except Exception:
        conn.rollback()
        raise
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

        # A user changing the primary network type takes ownership of the
        # classification. Automatic discovery may continue refreshing evidence
        # but must not overwrite this explicit decision.
        if 'network_type' in fields and fields['network_type'] is not None:
            fields['manual_override'] = 1
            fields['manual_network_type'] = fields['network_type']
            fields['classification_status'] = 'manual'
            fields['classification_source'] = 'manual'

        allowed_fields = (
            'name', 'vrf_id', 'vlan_id', 'site_id', 'tenant_id', 'status',
            'gateway', 'description', 'prefix', 'network_type',
            'gateway_device_id', 'gateway_interface_id', 'traceable',
            'prefix_cidr', 'ip_version', 'prefix_len',
            'manual_override', 'manual_network_type', 'classification_status',
            'classification_source',
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


PREFIX_NETWORK_TYPES = frozenset({
    'management', 'server', 'user', 'user_access', 'network_service', 'unclassified',
    'wireless', 'voice', 'dmz', 'transit', 'loopback', 'wan', 'vpn', 'storage',
    'vip', 'p2p', 'container',
})


def batch_update_subnet_network_type(
    ids: list[str],
    network_type: str,
    *,
    scope_validator: Callable[[dict], None] | None = None,
) -> dict:
    """Atomically set a manual network type on all selected prefixes.

    Scope validation is called for every locked row before any write, keeping
    authorization failures and missing IDs inside the same rollback boundary.
    """
    normalized_ids = [str(value or '').strip() for value in ids]
    if not normalized_ids or any(not value for value in normalized_ids):
        raise ValueError('ids must be a non-empty list of prefix IDs')
    if len(set(normalized_ids)) != len(normalized_ids):
        raise ValueError('ids must not contain duplicates')
    if network_type not in PREFIX_NETWORK_TYPES:
        raise ValueError('Unsupported prefix network_type')

    conn = get_db_connection()
    placeholders = ', '.join(_PH for _ in normalized_ids)
    try:
        rows = conn.execute(
            f'''SELECT id, tenant_id, site_id
                FROM prefixes
                WHERE id IN ({placeholders})
                ORDER BY id
                FOR UPDATE''',
            tuple(normalized_ids),
        ).fetchall()
        if len(rows) != len(normalized_ids):
            raise LookupError('One or more prefixes were not found')

        if scope_validator is not None:
            for row in rows:
                scope_validator(dict(row))

        now = _utc_now()
        conn.execute(
            f'''UPDATE prefixes
                SET network_type = {_PH},
                    manual_override = 1,
                    manual_network_type = {_PH},
                    classification_status = 'manual',
                    classification_source = 'manual',
                    updated_at = {_PH}
                WHERE id IN ({placeholders})''',
            (network_type, network_type, now, *normalized_ids),
        )
        conn.commit()
        return {
            'ok': True,
            'updated': len(rows),
            'ids': [str(row['id']) for row in rows],
            'network_type': network_type,
        }
    except Exception:
        conn.rollback()
        raise
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

def list_addresses(subnet_id: str, *, q: str = '', status: str = 'all', device_type: str = 'all', purpose: str = 'all', page: int | None = None, page_size: int = 20) -> list[dict] | dict:
    conn = get_db_connection()
    try:
        where = f'WHERE subnet_id = {_PH}'
        params: list = [subnet_id]
        if status and status != 'all':
            where += f" AND COALESCE(status, 'active') = {_PH}"
            params.append(status)
        if device_type and device_type != 'all':
            where += f" AND COALESCE(device_type, '') = {_PH}"
            params.append(device_type)
        if purpose and purpose != 'all':
            where += f" AND COALESCE(purpose, '') = {_PH}"
            params.append(purpose)
        if q and q.strip():
            fuzzy = f'%{q.strip().lower()}%'
            where += f" AND (LOWER(COALESCE(address, '')) LIKE {_PH} OR LOWER(COALESCE(hostname, '')) LIKE {_PH} OR LOWER(COALESCE(interface_name, '')) LIKE {_PH} OR LOWER(COALESCE(mac_address, '')) LIKE {_PH} OR LOWER(COALESCE(purpose, '')) LIKE {_PH})"
            params.extend([fuzzy, fuzzy, fuzzy, fuzzy, fuzzy])
        count_row = conn.execute(f'SELECT COUNT(*) AS cnt FROM ip_addresses {where}', tuple(params)).fetchone()
        total = int(count_row['cnt'] if count_row else 0)
        sql = f'SELECT * FROM ip_addresses {where} ORDER BY address'
        normalized_page_size = min(max(int(page_size or 20), 1), 100)
        normalized_page = max(int(page or 1), 1)
        if page is not None:
            sql += f' LIMIT {_PH} OFFSET {_PH}'
            params.extend([normalized_page_size, (normalized_page - 1) * normalized_page_size])
        rows = conn.execute(sql, tuple(params)).fetchall()
        result = [dict(r) for r in rows]
        if page is None:
            return result
        return {'items': result, 'total': total, 'page': normalized_page, 'page_size': normalized_page_size,
                'total_pages': max(1, (total + normalized_page_size - 1) // normalized_page_size)}
    finally:
        conn.close()


def list_ip_inventory(*, site_id: str = 'all', prefix_id: str = '', q: str = '', status: str = 'all', device_type: str = 'all', purpose: str = 'all', page: int = 1, page_size: int = 20, registered_only: bool = False) -> dict:
    """Return manual IPAM records merged with active discovered endpoints.

    Manual records remain the authoritative editable record.  Discovery facts
    fill its empty L2 fields within the same tenant and VRF; endpoints without
    a manual record are returned as read-only discovered inventory. Prefixes
    are matched within that scope and site names come from the CMDB directory.
    """
    conn = get_db_connection()
    try:
        prefix_catalog, sites, vrfs = load_inventory_catalog(conn)

        manual_rows = conn.execute(
            '''SELECT ip.*, p.prefix AS subnet_prefix, p.name AS subnet_name,
                      p.site_id AS prefix_site_id, p.network_type,
                      p.tenant_id AS prefix_tenant_id, p.vrf_id AS prefix_vrf_id,
                      s.site_name AS prefix_site_name, s.site_code AS prefix_site_code,
                      d.hostname AS bound_device_hostname, d.asset_id AS linked_asset_id,
                      pa.asset_tag, pa.serial_number AS asset_serial_number,
                      pa.hostname AS asset_hostname, pa.vendor AS asset_vendor,
                      pa.model AS asset_model, pa.management_ip AS asset_management_ip,
                      pa.business_ip AS asset_business_ip
               FROM ip_addresses ip
               LEFT JOIN prefixes p ON p.id = ip.subnet_id
               LEFT JOIN sites s ON s.id = p.site_id
               LEFT JOIN devices d ON d.id = ip.device_id
               LEFT JOIN physical_assets pa ON pa.id = d.asset_id
               ORDER BY ip.address'''
        ).fetchall()
        endpoint_rows = conn.execute(
            '''SELECT ne.id, ne.ip, ne.mac, ne.hostname, ne.switch_id, ne.switch_port,
                      ne.vlan, ne.vrf, ne.site, ne.last_seen, ne.source_type,
                      ne.confidence, d.hostname AS switch_name, d.site AS device_site,
                      d.id AS cmdb_device_id,
                      d.site_id AS device_site_id, d.tenant_id AS device_tenant_id,
                      pa.site_id AS asset_site_id,
                      d.asset_id AS linked_asset_id, pa.asset_tag,
                      pa.serial_number AS asset_serial_number,
                      pa.hostname AS asset_hostname, pa.vendor AS asset_vendor,
                      pa.model AS asset_model, pa.management_ip AS asset_management_ip,
                      pa.business_ip AS asset_business_ip
               FROM network_endpoints ne
               LEFT JOIN devices d ON d.id = ne.switch_id
               LEFT JOIN physical_assets pa ON pa.id = d.asset_id
               WHERE ne.is_active = 1 AND COALESCE(ne.ip, '') <> ''
               ORDER BY ne.last_seen DESC'''
        ).fetchall()
        # CLI interface facts live in the CMDB snapshot tables by design. Read
        # only the last successful generation; never project these read-only
        # observations back into shared interfaces, ip_inventory, or monitoring.
        interface_ip_rows = _current_cmdb_interface_ip_observations(conn)

        all_items: list[dict] = []
        manual_by_scope: dict[tuple, list[dict]] = {}
        for row in manual_rows:
            item = dict(row)
            scope_key = manual_address_key(item)
            manual_site = sites.get(str(item.get('prefix_site_id') or item.get('site_id') or ''))
            item.update({
                'tenant_id': scope_key[0], 'vrf_id': scope_key[1],
                'site_id': manual_site['id'] if manual_site else '',
                'site_name': manual_site['name'] if manual_site else '未分配站点',
                'purpose': item.get('purpose') or _infer_ip_purpose(item.get('network_type')),
                'source': 'manual', 'is_discovered': False,
                '_registered_ipam_record': True,
                'discovered_last_seen': '', 'switch_name': '', 'switch_port': '', 'vlan': '',
            })
            all_items.append(item)
            manual_by_scope.setdefault(scope_key, []).append(item)

        for row in endpoint_rows:
            endpoint = dict(row)
            address = str(endpoint.get('ip') or '')
            if not address:
                continue
            scope_key = endpoint_address_key(endpoint, vrfs)
            endpoint_site = endpoint_site_id(endpoint, sites)
            prefix = match_inventory_prefix(address, scope_key, endpoint_site, prefix_catalog)
            manuals = manual_by_scope.get(scope_key, [])
            manual = manuals[0] if len(manuals) == 1 else None
            resolved_site_id = (prefix or {}).get('site_id') or endpoint_site
            resolved_site = sites.get(resolved_site_id)
            resolved_site_name = resolved_site['name'] if resolved_site else '未分配站点'
            if manual is not None:
                if registered_only:
                    # The address page is the authoritative ledger. Keep the
                    # stored values visible without borrowing read-only cache
                    # fields from network_endpoints.
                    continue
                manual.update({
                    'source': 'manual+discovered',
                    'discovered_last_seen': endpoint.get('last_seen') or '',
                    'switch_name': endpoint.get('switch_name') or '',
                    'switch_port': endpoint.get('switch_port') or '',
                    'vlan': endpoint.get('vlan') or '',
                    'discovered_vrf': endpoint.get('vrf') or '',
                    'discovered_confidence': endpoint.get('confidence') or '',
                    'site_id': manual.get('site_id') or resolved_site_id,
                    'site_name': manual.get('site_name') if manual.get('site_id') else resolved_site_name,
                })
                if not manual.get('mac_address'):
                    manual['mac_address'] = endpoint.get('mac') or ''
                if not manual.get('hostname'):
                    manual['hostname'] = endpoint.get('hostname') or ''
                if not manual.get('device_id'):
                    manual['device_id'] = endpoint.get('switch_id') or ''
                if not manual.get('interface_name'):
                    manual['interface_name'] = endpoint.get('switch_port') or ''
                for key in (
                    'linked_asset_id', 'asset_tag', 'asset_serial_number', 'asset_hostname',
                    'asset_vendor', 'asset_model', 'asset_management_ip', 'asset_business_ip',
                ):
                    if not manual.get(key):
                        manual[key] = endpoint.get(key) or ''
                continue

            item = {
                'id': f"discovered-{endpoint['id']}", 'subnet_id': (prefix or {}).get('id') or '',
                'tenant_id': scope_key[0] if scope_key else str(endpoint.get('device_tenant_id') or ''),
                'vrf_id': scope_key[1] if scope_key else str(endpoint.get('vrf') or ''),
                'address': address, 'hostname': endpoint.get('hostname') or '',
                'device_id': endpoint.get('switch_id') or '',
                'interface_name': endpoint.get('switch_port') or '',
                'mac_address': endpoint.get('mac') or '', 'device_type': 'host',
                'purpose': _infer_ip_purpose((prefix or {}).get('network_type')),
                'status': 'active', 'description': '', 'last_seen': endpoint.get('last_seen') or '',
                'created_at': '', 'updated_at': endpoint.get('last_seen') or '',
                'subnet_prefix': (prefix or {}).get('prefix') or '',
                'subnet_name': (prefix or {}).get('name') or '',
                'network_type': (prefix or {}).get('network_type') or '',
                'site_id': resolved_site_id, 'site_name': resolved_site_name,
                'source': 'discovered', 'is_discovered': True,
                '_registered_ipam_record': False,
                'discovered_last_seen': endpoint.get('last_seen') or '',
                'switch_name': endpoint.get('switch_name') or '',
                'switch_port': endpoint.get('switch_port') or '',
                'vlan': endpoint.get('vlan') or '', 'discovered_vrf': endpoint.get('vrf') or '',
                'discovered_confidence': endpoint.get('confidence') or '',
                'linked_asset_id': endpoint.get('linked_asset_id') or '',
                'asset_tag': endpoint.get('asset_tag') or '',
                'asset_serial_number': endpoint.get('asset_serial_number') or '',
                'asset_hostname': endpoint.get('asset_hostname') or '',
                'asset_vendor': endpoint.get('asset_vendor') or '',
                'asset_model': endpoint.get('asset_model') or '',
                'asset_management_ip': endpoint.get('asset_management_ip') or '',
                'asset_business_ip': endpoint.get('asset_business_ip') or '',
            }
            all_items.append(item)

        for observation in interface_ip_rows:
            address = str(observation.get('ip_address') or '').strip()
            try:
                normalized_address = _normalize_address(address)
                ip_obj = ipaddress.ip_address(normalized_address)
            except ValueError:
                continue

            tenant_id = str(observation.get('tenant_id') or 'tenant-default')
            owner = {
                'cmdb_device_id': observation.get('device_id'),
                'asset_site_id': observation.get('asset_site_id'),
                'device_site_id': observation.get('device_site_id'),
                'device_site': observation.get('device_site'),
            }
            observed_site_id = endpoint_site_id(owner, sites)
            candidate_prefixes = [
                prefix for prefix in prefix_catalog
                if prefix['tenant_id'] == tenant_id
                and not prefix.get('invalid_site_assignment')
                and ip_obj.version == prefix['network'].version
                and ip_obj in prefix['network']
                and (not observed_site_id or not prefix['site_id'] or prefix['site_id'] == observed_site_id)
            ]
            # The isolated interface snapshot currently has no VRF field. Even
            # a unique CIDR is therefore only a candidate: assigning it to a
            # global or named-VRF prefix could silently misclassify the IP.
            prefix_match_status = 'vrf_unavailable' if candidate_prefixes else 'unmatched'
            prefix_length = _parse_interface_prefix_length(observation.get('ip_prefix_length'))
            observed_prefix = ''
            if prefix_length is not None:
                try:
                    observed_prefix = str(ipaddress.ip_interface(
                        f'{normalized_address}/{prefix_length}'
                    ).network)
                except ValueError:
                    pass

            interface_type = str(observation.get('interface_type') or '').strip().lower()
            device_type = {
                'loopback': 'loopback',
                'svi': 'vlan',
                'tunnel': 'tunnel',
            }.get(interface_type, 'device')
            observation_id = (
                f"cmdb-interface-observed:{observation.get('device_id')}:"
                f"{observation.get('normalized_interface_name')}"
            )
            all_items.append({
                'id': observation_id,
                'subnet_id': '',
                'tenant_id': tenant_id,
                'vrf_id': '',
                'address': normalized_address,
                'hostname': str(observation.get('device_hostname') or ''),
                'device_id': str(observation.get('device_id') or ''),
                'interface_name': str(observation.get('interface_name') or ''),
                'mac_address': '',
                'device_type': device_type,
                'purpose': 'other',
                'status': 'active',
                'description': '',
                'last_seen': str(observation.get('observed_at') or ''),
                'created_at': '',
                'updated_at': str(observation.get('observed_at') or ''),
                'site_id': observed_site_id,
                'site_name': sites.get(observed_site_id, {}).get('name', '未分配站点'),
                'subnet_prefix': '',
                'subnet_name': '',
                'network_type': '',
                'source': 'interface_cli',
                'is_discovered': True,
                '_registered_ipam_record': False,
                'is_prefix_gateway': False,
                'is_virtual_gateway': False,
                'discovered_last_seen': str(observation.get('observed_at') or ''),
                'switch_name': str(observation.get('device_hostname') or ''),
                'switch_port': str(observation.get('interface_name') or ''),
                'vlan': '',
                'bound_device_hostname': str(observation.get('device_hostname') or ''),
                'observed_prefix': observed_prefix,
                'prefix_match_status': prefix_match_status,
                'prefix_review_reason': 'VRF未包含在接口观察快照中' if candidate_prefixes else '未找到匹配的IPAM前缀',
                'vrf_unknown': True,
            })

        # Prefix gateway configuration is authoritative even when no IPAM row
        # or discovery fact exists for the address. Reuse an existing inventory
        # row when present; otherwise expose one explicit read-only view row.
        for prefix in prefix_catalog:
            gateway = _configured_prefix_gateway(prefix)
            if not gateway:
                continue
            matching_items = []
            for item in all_items:
                if str(item.get('subnet_id') or '') != str(prefix['id']):
                    continue
                try:
                    item_address = _normalize_address(str(item.get('address') or ''))
                except ValueError:
                    continue
                if item_address == gateway:
                    matching_items.append(item)
            if matching_items:
                for item in matching_items:
                    _mark_prefix_gateway_item(item, prefix)
            else:
                all_items.append(_build_prefix_gateway_item(prefix, gateway))

        if registered_only:
            all_items = [item for item in all_items if item.get('_registered_ipam_record')]

        for item in all_items:
            if prefix_id and str(item.get('subnet_id') or '') != prefix_id:
                continue
            site_key = str(item.get('site_id') or '')
            if site_key in sites and not item.get('is_virtual_gateway'):
                sites[site_key]['ip_count'] += 1

        normalized_query = q.strip().lower()
        items = []
        for item in all_items:
            if prefix_id and str(item.get('subnet_id') or '') != prefix_id:
                continue
            item_site = str(item.get('site_id') or '')
            if site_id != 'all' and site_id and item_site != site_id:
                continue
            if status and status != 'all' and status != 'available' and str(item.get('status') or '') != status:
                continue
            if status == 'available':
                continue
            if device_type and device_type != 'all' and str(item.get('device_type') or '') != device_type:
                continue
            if purpose and purpose != 'all' and str(item.get('purpose') or '') != purpose:
                continue
            if normalized_query:
                haystack = ' '.join(str(item.get(key) or '') for key in (
                    'address', 'hostname', 'interface_name', 'description', 'site_name',
                    'subnet_prefix', 'observed_prefix', 'subnet_name', 'mac_address', 'switch_name', 'vlan',
                    'purpose', 'device_type', 'source', 'gateway_device_name',
                    'bound_device_hostname', 'asset_tag', 'asset_serial_number',
                    'asset_hostname', 'asset_vendor', 'asset_model', 'asset_management_ip',
                    'asset_business_ip',
                )).lower()
                if item.get('is_prefix_gateway'):
                    haystack += ' prefix gateway 前缀网关 网关'
                if normalized_query not in haystack:
                    continue
            items.append(item)

        items.sort(key=lambda item: (
            str(item.get('site_name') or ''), str(item.get('subnet_prefix') or ''), str(item.get('address') or '')
        ))

        normalized_page_size = min(max(int(page_size or 20), 1), 100)
        normalized_page = max(int(page or 1), 1)
        total = len(items)
        start = (normalized_page - 1) * normalized_page_size
        for item in all_items:
            item.pop('_registered_ipam_record', None)
        return {
            'items': items[start:start + normalized_page_size],
            'total': total,
            'page': normalized_page,
            'page_size': normalized_page_size,
            'has_more': start + normalized_page_size < total,
            'sites': list(sites.values()),
            'summary': {
                # Virtual gateways are visible inventory rows, but not persisted
                # IPAM/discovery records and are counted separately.
                'total': sum(1 for item in items if not item.get('is_virtual_gateway')),
                'discovered': sum(1 for item in items if item.get('is_discovered')),
                'manual': sum(1 for item in items if str(item.get('source') or '').startswith('manual')),
                'gateways': sum(1 for item in items if item.get('is_prefix_gateway')),
                'prefixes': len(prefix_catalog),
                'interface_observed': sum(1 for item in items if item.get('source') == 'interface_cli'),
                'interface_observed_networks': len({
                    str(item.get('observed_prefix') or '')
                    for item in items
                    if item.get('source') == 'interface_cli' and item.get('observed_prefix')
                }),
                'interface_unmatched_prefix': sum(1 for item in items if item.get('prefix_match_status') == 'unmatched'),
                'interface_vrf_review': sum(1 for item in items if item.get('prefix_match_status') == 'vrf_unavailable'),
                'interface_matched': sum(1 for item in items if item.get('source') == 'interface_cli')
                    - sum(1 for item in items if item.get('prefix_match_status') in {'unmatched', 'vrf_unavailable'}),
            },
        }
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
    _validate_address_policy(subnet, address, device_type=device_type, purpose=purpose)
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
                          interface_id: str = '', interface_name: str = '', device_type: str = '',
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
        gateway = str(subnet['gateway'] or '').strip()
        try:
            gateway = _normalize_address(gateway) if gateway else ''
        except ValueError:
            gateway = ''
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
        used.update(_active_discovered_addresses(conn, net))
        candidates = net.hosts() if net.version == 4 and net.prefixlen < 31 else iter(net)
        selected = None
        for candidate in candidates:
            cand = str(candidate)
            if cand == gateway:
                continue
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
            device_type=device_type,
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
                    device_type: str = '',
                    purpose: str = '', requested_by: str = '', expires_at: str = '') -> dict:
    return create_address(
        subnet_id,
        address=address,
        hostname=hostname,
        device_id=device_id,
        interface_id=interface_id,
        interface_name=interface_name,
        mac_address=mac_address,
        device_type=device_type,
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
        all_prefixes = conn.execute('SELECT id, prefix, status, gateway, tenant_id FROM prefixes').fetchall()
        capacity_prefixes = [
            row for row in all_prefixes
            if _is_capacity_prefix(row['prefix'], row['status'])
        ]
        total_capacity = sum(_calculate_total_ips(r['prefix']) for r in capacity_prefixes)

        total_used = sum(_count_prefix_used_ips(conn, dict(prefix_row)) for prefix_row in all_prefixes)

        return {
            'total_subnets': subnets['cnt'] if subnets else 0,
            'total_addresses': addresses['cnt'] if addresses else 0,
            'total_capacity': total_capacity,
            'total_used': total_used,
            'capacity_prefixes_count': len(capacity_prefixes),
            'excluded_prefixes_count': len(all_prefixes) - len(capacity_prefixes),
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
            '''SELECT p.id, p.prefix, p.name, p.status, p.site_id, p.gateway, p.tenant_id,
                      s.site_name, s.site_code
               FROM prefixes p
               LEFT JOIN sites s ON p.site_id = s.id'''
        ).fetchall()

        per_prefix = []
        total_ips_sum = 0
        used_ips_sum = 0
        capacity_prefixes_count = 0
        excluded_prefixes_count = 0
        site_agg: dict[str, dict] = {}

        for r in rows:
            total = _calculate_total_ips(r['prefix'])
            exclusion_reason = _capacity_exclusion_reason(r['prefix'], r['status'])
            capacity_eligible = not exclusion_reason
            used_count = _count_prefix_used_ips(conn, dict(r))

            if capacity_eligible:
                total_ips_sum += total
                used_ips_sum += used_count
                capacity_prefixes_count += 1
            else:
                excluded_prefixes_count += 1

            per_prefix.append({
                'id': r['id'],
                'prefix': r['prefix'],
                'name': r['name'],
                'status': r['status'],
                'total_ips': total,
                'used_ips': used_count,
                'utilization': round(used_count / total * 100, 1) if total > 0 else 0,
                'capacity_eligible': capacity_eligible,
                'capacity_excluded_reason': exclusion_reason,
            })

            # Aggregate only allocatable capacity by site.
            if capacity_eligible:
                site_key = r['site_name'] or r['site_code'] or 'Unassigned'
                bucket = site_agg.setdefault(site_key, {'site': site_key, 'total_ips': 0, 'used_ips': 0})
                bucket['total_ips'] += total
                bucket['used_ips'] += used_count

        # Top 5 allocatable prefixes by utilization.
        top_utilized = sorted(
            [p for p in per_prefix if p['capacity_eligible'] and p['total_ips'] > 0],
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
            exists = conn.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = ?",
                (table,),
            ).fetchone()
            if not exists:
                return 0
            row = conn.execute(f'SELECT COUNT(*) as cnt FROM {table}').fetchone()
            return row['cnt'] if row else 0

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
            'capacity_prefixes_count': capacity_prefixes_count,
            'excluded_prefixes_count': excluded_prefixes_count,
            'capacity_policy': 'allocatable_prefixes_excluding_containers_and_point_to_point_or_host_routes',
        }

        # ── Allocation trend for allocatable prefixes (cumulative, by created day) ───
        forecast_trend = []
        day_rows = conn.execute(
            '''SELECT ip.created_at, p.prefix, p.status AS prefix_status
               FROM ip_addresses ip
               LEFT JOIN prefixes p ON p.id = ip.subnet_id
               WHERE ip.created_at IS NOT NULL
                 AND COALESCE(ip.status, 'active') NOT IN ('released', 'available')
               ORDER BY ip.created_at'''
        ).fetchall()
        day_counts: dict[str, int] = {}
        for dr in day_rows:
            created_at = str(dr['created_at'] or '')
            if len(created_at) < 10 or not _is_capacity_prefix(
                dr['prefix'] or '',
                dr['prefix_status'] or '',
            ):
                continue
            day = created_at[:10]
            day_counts[day] = day_counts.get(day, 0) + 1
        cumulative = 0
        for day in sorted(day_counts):
            cumulative += day_counts[day]
            forecast_trend.append({'day': day, 'allocated': cumulative})
        # Keep the most recent 14 data points for a readable chart
        forecast_trend = forecast_trend[-14:]

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
            used_ips = _count_prefix_used_ips(conn, item)
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

def _validate_pool_range(
    conn,
    *,
    prefix_id: str,
    start_ip: str,
    end_ip: str,
    exclude_pool_id: str = '',
) -> tuple[str, str]:
    """Validate a pool's CIDR bounds and reject inclusive range overlaps."""
    prefix_id = str(prefix_id or '').strip()
    if not prefix_id:
        raise ValueError('An IP pool must belong to a prefix')
    prefix_row = conn.execute(
        f'SELECT id, prefix FROM prefixes WHERE id = {_PH} FOR UPDATE',
        (prefix_id,),
    ).fetchone()
    if not prefix_row:
        raise ValueError('The selected prefix does not exist')
    try:
        network = ipaddress.ip_network(str(prefix_row['prefix']), strict=False)
        start = ipaddress.ip_address(str(start_ip).strip())
        end = ipaddress.ip_address(str(end_ip).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Invalid pool address range: {exc}') from exc
    if start.version != end.version or start.version != network.version:
        raise ValueError('Pool start, end, and prefix must use the same IP version')
    if int(start) > int(end):
        raise ValueError('Pool start address must not be greater than end address')
    if start not in network or end not in network:
        raise ValueError('Both pool endpoints must be inside the selected prefix')

    overlap_clause = ''
    params: list[str] = [prefix_id]
    if exclude_pool_id:
        overlap_clause = f' AND id <> {_PH}'
        params.append(exclude_pool_id)
    existing_rows = conn.execute(
        f'''SELECT id, start_ip, end_ip FROM ipam_pools
             WHERE prefix_id = {_PH}{overlap_clause}''',
        tuple(params),
    ).fetchall()
    for row in existing_rows:
        try:
            existing_start = ipaddress.ip_address(str(row['start_ip']).strip())
            existing_end = ipaddress.ip_address(str(row['end_ip']).strip())
        except (TypeError, ValueError):
            continue
        if existing_start.version != start.version or existing_end.version != start.version:
            continue
        if int(start) <= int(existing_end) and int(existing_start) <= int(end):
            raise ValueError(f'Pool range overlaps existing pool {row["id"]}')
    return str(start), str(end)

def list_pools(*, q: str = '', status: str = '', prefix_id: str = '', page: int | None = None, page_size: int = 20) -> list[dict] | dict:
    conn = get_db_connection()
    try:
        prefix_id = str(prefix_id or '').strip()
        clauses: list[str] = []
        params: list[str] = []
        if q.strip():
            clauses.append("(LOWER(p.name) LIKE ? OR LOWER(COALESCE(p.description, '')) LIKE ? OR LOWER(COALESCE(pf.prefix, '')) LIKE ?)")
            fuzzy = f"%{q.strip().lower()}%"
            params.extend([fuzzy, fuzzy, fuzzy])
        if status and status.lower() != 'all':
            clauses.append("LOWER(COALESCE(p.status, '')) = ?")
            params.append(status.lower())
        if prefix_id.strip():
            clauses.append('p.prefix_id = ?')
            params.append(prefix_id.strip())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        count_row = conn.execute(
            f'''SELECT COUNT(*) AS total
                FROM ipam_pools p
                LEFT JOIN prefixes pf ON p.prefix_id = pf.id{where}''',
            tuple(params),
        ).fetchone()
        total = int(count_row['total'] or 0) if count_row else 0
        page_clause = ''
        page_params: list[int] = []
        if page is not None:
            safe_page_size = min(max(int(page_size or 20), 1), 100)
            safe_page = max(int(page or 1), 1)
            page_clause = ' LIMIT ? OFFSET ?'
            page_params = [safe_page_size, (safe_page - 1) * safe_page_size]
        rows = conn.execute(f'''
            SELECT p.*, pf.prefix AS prefix_cidr, t.name AS tenant_name
            FROM ipam_pools p
            LEFT JOIN prefixes pf ON p.prefix_id = pf.id
            LEFT JOIN tenants t ON p.tenant_id = t.id
            {where}
            ORDER BY p.name{page_clause}
        ''', tuple(params + page_params)).fetchall()

        pools_by_prefix: dict[str, list[dict]] = {}
        used_by_pool: dict[str, set[str]] = {}
        for pool in (dict(row) for row in rows):
            pool_id_value = str(pool.get('id') or '')
            pool_id_prefix = str(pool.get('prefix_id') or '')
            used_by_pool[pool_id_value] = set()
            pools_by_prefix.setdefault(pool_id_prefix, []).append(pool)

        prefix_ids = sorted({prefix_id for prefix_id in pools_by_prefix if prefix_id})
        if prefix_ids:
            manual_rows = conn.execute(
                f"""SELECT subnet_id, address FROM ip_addresses
                     WHERE subnet_id IN ({_ph(len(prefix_ids))})
                       AND COALESCE(status, 'active') NOT IN ('released', 'available')""",
                tuple(prefix_ids),
            ).fetchall()
            for manual_row in manual_rows:
                scope_pools = pools_by_prefix.get(str(manual_row['subnet_id'] or ''), [])
                try:
                    address = _normalize_address(manual_row['address'] or '')
                except ValueError:
                    continue
                for pool in scope_pools:
                    pool_id_value = str(pool.get('id') or '')
                    if _address_matches_pool(address, pool):
                        used_by_pool.setdefault(pool_id_value, set()).add(address)

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
            
            used_ips = len(used_by_pool.get(str(p_dict.get('id') or ''), set()))
            
            p_dict['used_ips'] = used_ips
            p_dict['utilization'] = round((used_ips / total_ips * 100), 1) if total_ips > 0 else 0
            pools.append(p_dict)
            
        if page is None:
            return pools
        return {
            'items': pools,
            'total': total,
            'page': safe_page,
            'page_size': safe_page_size,
            'total_pages': max(1, (total + safe_page_size - 1) // safe_page_size),
        }
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
        prefix_id = str(prefix_id or '').strip()
        start_ip, end_ip = _validate_pool_range(
            conn, prefix_id=prefix_id, start_ip=start_ip, end_ip=end_ip,
        )
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
            f'SELECT id, prefix_id, start_ip, end_ip FROM ipam_pools WHERE id = {_PH}', (pool_id,)
        ).fetchone()
        if not row:
            return False
        fields = dict(fields)
        if any(name in fields for name in ('prefix_id', 'start_ip', 'end_ip')):
            prefix_id = str(fields.get('prefix_id', row['prefix_id']) or '').strip()
            start_ip, end_ip = _validate_pool_range(
                conn,
                prefix_id=prefix_id,
                start_ip=fields.get('start_ip', row['start_ip']),
                end_ip=fields.get('end_ip', row['end_ip']),
                exclude_pool_id=pool_id,
            )
            fields.update({'prefix_id': prefix_id, 'start_ip': start_ip, 'end_ip': end_ip})
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

def list_vips(*, q: str = '', vip_type: str = '', status: str = '', prefix_id: str = '', page: int | None = None, page_size: int = 20) -> list[dict] | dict:
    conn = get_db_connection()
    try:
        prefix_id = str(prefix_id or '').strip()
        clauses: list[str] = []
        params: list[str] = []
        if q.strip():
            clauses.append("(LOWER(vip.address) LIKE ? OR LOWER(COALESCE(vip.description, '')) LIKE ? OR LOWER(COALESCE(vip.real_servers, '')) LIKE ?)")
            fuzzy = f"%{q.strip().lower()}%"
            params.extend([fuzzy, fuzzy, fuzzy])
        if vip_type and vip_type.lower() != 'all':
            clauses.append("LOWER(COALESCE(vip.vip_type, '')) = ?")
            params.append(vip_type.lower())
        if status and status.lower() != 'all':
            clauses.append("LOWER(COALESCE(vip.status, '')) = ?")
            params.append(status.lower())
        if prefix_id.strip():
            prefix_row = conn.execute(
                f"SELECT prefix, COALESCE(tenant_id, 'tenant-default') AS tenant_id FROM prefixes WHERE id = {_PH}",
                (prefix_id.strip(),),
            ).fetchone()
            if not prefix_row:
                return _empty_ipam_page(page=page, page_size=page_size)
            try:
                network = ipaddress.ip_network(str(prefix_row['prefix']), strict=False)
            except (KeyError, TypeError, ValueError):
                return _empty_ipam_page(page=page, page_size=page_size)
            clauses.append('vip.address::inet <<= CAST(? AS cidr)')
            params.append(str(network))
            clauses.append("COALESCE(vip.tenant_id, 'tenant-default') = ?")
            params.append(str(prefix_row['tenant_id'] or 'tenant-default'))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        safe_page = max(int(page or 1), 1)
        safe_page_size = min(max(int(page_size or 20), 1), 100)
        count_row = conn.execute(
            f'''SELECT COUNT(*) AS total FROM ipam_vips vip{where}''', tuple(params)
        ).fetchone()
        total = int(count_row['total'] or 0) if count_row else 0
        page_clause = '' if page is None else ' LIMIT ? OFFSET ?'
        page_params = [] if page is None else [safe_page_size, (safe_page - 1) * safe_page_size]
        rows = conn.execute(f'''
            SELECT vip.*, d.hostname AS device_name,
                   bd.hostname AS backup_device_name,
                   t.name AS tenant_name
            FROM ipam_vips vip
            LEFT JOIN devices d ON vip.device_id = d.id
            LEFT JOIN devices bd ON vip.backup_device_id = bd.id
            LEFT JOIN tenants t ON vip.tenant_id = t.id
            {where}
            ORDER BY vip.address{page_clause}
        ''', tuple(params + page_params)).fetchall()
        items = [dict(r) for r in rows]
        if page is None:
            return items
        return {'items': items, 'total': total, 'page': safe_page, 'page_size': safe_page_size, 'total_pages': max(1, (total + safe_page_size - 1) // safe_page_size)}
    finally:
        conn.close()


def _empty_ipam_page(*, page: int | None, page_size: int) -> list[dict] | dict:
    if page is None:
        return []
    safe_page = max(int(page or 1), 1)
    safe_page_size = min(max(int(page_size or 20), 1), 100)
    return {
        'items': [],
        'total': 0,
        'page': safe_page,
        'page_size': safe_page_size,
        'total_pages': 1,
    }


def _validate_vip_prefix_scope(conn, *, prefix_id: str, address: str, tenant_id: str) -> None:
    """Ensure a VIP being edited in a prefix-scoped workflow belongs to that scope."""
    if not prefix_id:
        return
    row = conn.execute(
        f"SELECT prefix, COALESCE(tenant_id, 'tenant-default') AS tenant_id FROM prefixes WHERE id = {_PH}",
        (prefix_id,),
    ).fetchone()
    if not row:
        raise ValueError('Selected prefix was not found')
    try:
        network = ipaddress.ip_network(str(row['prefix']), strict=False)
        ip_address = ipaddress.ip_address(address)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Selected prefix or VIP address is invalid') from exc
    if ip_address.version != network.version or ip_address not in network:
        raise ValueError(f'VIP {address} is outside selected prefix {network}')
    prefix_tenant_id = str(row['tenant_id'] or 'tenant-default')
    if str(tenant_id or 'tenant-default') != prefix_tenant_id:
        raise ValueError('VIP tenant must match the selected prefix tenant')


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
    prefix_id: str | None = None,
) -> dict:
    address = _normalize_address(address)
    prefix_id = str(prefix_id or '').strip()
    conn = get_db_connection()
    try:
        _validate_vip_prefix_scope(conn, prefix_id=prefix_id, address=address, tenant_id=tenant_id)
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
            f'SELECT id, address, tenant_id FROM ipam_vips WHERE id = {_PH}', (vip_id,)
        ).fetchone()
        if not row:
            return False
        prefix_id = str(fields.get('prefix_id') or '').strip()
        if prefix_id:
            _validate_vip_prefix_scope(
                conn,
                prefix_id=prefix_id,
                address=_normalize_address(fields.get('address') or row['address']),
                tenant_id=str(fields.get('tenant_id') or row['tenant_id'] or 'tenant-default'),
            )
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

def list_leases(*, q: str = '', state: str = '', page: int | None = None, page_size: int = 20) -> list[dict] | dict:
    conn = get_db_connection()
    try:
        clauses: list[str] = []
        params: list[str] = []
        if q.strip():
            clauses.append("(LOWER(address) LIKE ? OR LOWER(COALESCE(mac_address, '')) LIKE ? OR LOWER(COALESCE(hostname, '')) LIKE ? OR LOWER(COALESCE(dhcp_server, '')) LIKE ?)")
            fuzzy = f"%{q.strip().lower()}%"
            params.extend([fuzzy] * 4)
        if state and state.lower() != 'all':
            clauses.append("LOWER(COALESCE(lease_state, '')) = ?")
            params.append(state.lower())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        count_row = conn.execute(f'SELECT COUNT(*) AS total FROM ipam_dhcp_leases{where}', tuple(params)).fetchone()
        total = int(count_row['total'] or 0) if count_row else 0
        safe_page = max(int(page or 1), 1)
        safe_page_size = min(max(int(page_size or 20), 1), 100)
        page_clause = '' if page is None else ' LIMIT ? OFFSET ?'
        page_params = [] if page is None else [safe_page_size, (safe_page - 1) * safe_page_size]
        rows = conn.execute(f'SELECT * FROM ipam_dhcp_leases{where} ORDER BY address{page_clause}', tuple(params + page_params)).fetchall()
        items = [dict(row) for row in rows]
        if page is None:
            return items
        return {'items': items, 'total': total, 'page': safe_page, 'page_size': safe_page_size, 'total_pages': max(1, (total + safe_page_size - 1) // safe_page_size)}
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
    """Return the first free IP not allocated manually or seen in discovery."""
    conn = get_db_connection()
    try:
        subnet = conn.execute(
            f'SELECT prefix, gateway FROM prefixes WHERE id = {_PH}', (subnet_id,)
        ).fetchone()
        if not subnet:
            return None
        
        prefix_str = subnet['prefix']
        gateway_ip = str(subnet['gateway'] or '').strip()
        try:
            gateway_ip = _normalize_address(gateway_ip) if gateway_ip else ''
        except ValueError:
            gateway_ip = ''
        
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
        allocated_ips = set()
        for row in allocated_rows:
            try:
                allocated_ips.add(_normalize_address(row['address']))
            except ValueError:
                continue
        occupied_ips = allocated_ips | _active_discovered_addresses(conn, net)
        
        limit = 10000
        count = 0
        for ip_obj in net.hosts():
            count += 1
            if count > limit:
                break
            ip_str = str(ip_obj)
            if ip_str == gateway_ip:
                continue
            if ip_str in occupied_ips:
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


def get_ipam_reconciliation(*, active_tab: str = '', q: str = '', page: int | None = None, page_size: int = 20,
                           visible_scopes: set[tuple[str, str]] | None = None) -> dict:
    """Compare IPAM with the independent IPAM discovery evidence ledger."""
    conn = get_db_connection()
    try:
        from services.ipam_discovery_service import build_ipam_reconciliation
        return build_ipam_reconciliation(
            conn, active_tab=active_tab, q=q, page=page, page_size=page_size,
            visible_scopes=visible_scopes,
        )
    finally:
        conn.close()
