"""
IPAM Service — Business logic for IP/VLAN resource management.
Provides subnet and IP address CRUD with validation, overlap detection, and conflict scanning.
Extended with hierarchy tree, VRF-scoped uniqueness, pool/VIP/lease CRUD, and active endpoints.
"""

import uuid
import contextvars
import functools
import ipaddress
import logging
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from core.interface_utils import normalize_interface_name
from services.ipam_inventory_scope import (
    endpoint_address_key, endpoint_site_id, load_inventory_catalog,
    manual_address_key, match_inventory_prefix,
)
from services.ipam_network_scope import (
    BUSINESS_UTILIZATION_NETWORK_TYPES,
    INTERCONNECT_NETWORK_TYPES,
    is_business_utilization_network as _is_business_utilization_network,
)
from services.ipam_address_space_service import (
    _get_address_space,
    ensure_vrf_address_space,
    lock_ipam_scope,
)
from services.audit_service import log_audit_event

from database import get_db_connection

logger = logging.getLogger(__name__)

# Per-request read cache for list/summary endpoints. Capacity metrics are
# computed per Prefix, and each computation used to reload the same global
# observation sets (ARP/ND, FHRP, legacy endpoints, CMDB interface snapshots,
# sites, information_schema). Inside a read-only listing those inputs cannot
# change, so they are loaded once per request. Outside a cached read scope
# (all writes and allocation paths) every call still queries live data.
_READ_SCOPE_CACHE: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    'ipam_read_scope_cache', default=None,
)


def _with_read_scope_cache(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if _READ_SCOPE_CACHE.get() is not None:
            return func(*args, **kwargs)
        token = _READ_SCOPE_CACHE.set({})
        try:
            return func(*args, **kwargs)
        finally:
            _READ_SCOPE_CACHE.reset(token)
    return wrapper


def _scoped_read(conn, key: tuple, loader):
    cache = _READ_SCOPE_CACHE.get()
    if cache is None:
        return loader()
    cache_key = (id(conn), *key)
    if cache_key not in cache:
        cache[cache_key] = loader()
    return cache[cache_key]

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
    return PREFIX_TO_IP_PURPOSE.get(str(network_type or '').strip().lower(), 'other')


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _idempotency_key(value: str | None) -> str:
    key = str(value or '').strip()
    if len(key) > 200:
        raise ValueError('Idempotency-Key must be at most 200 characters')
    return key


def _idempotency_hash(payload: dict) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(',', ':'),
        default=str,
    )
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def _idempotency_replay(
    conn,
    *,
    tenant_id: str,
    operation: str,
    idempotency_key: str | None,
    payload: dict,
) -> dict | None:
    key = _idempotency_key(idempotency_key)
    if not key:
        return None
    tenant_key = str(tenant_id or 'tenant-default').strip() or 'tenant-default'
    operation_key = str(operation or '').strip()
    if not operation_key:
        raise ValueError('IPAM idempotency operation is required')
    request_hash = _idempotency_hash(payload)
    lock_key = f'ipam-idempotency:{tenant_key}:{operation_key}:{key}'
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', (lock_key,))
    row = conn.execute(
        '''SELECT request_hash, response_json
             FROM ipam_idempotency_records
            WHERE tenant_id = ? AND operation = ? AND idempotency_key = ?''',
        (tenant_key, operation_key, key),
    ).fetchone()
    if not row:
        return None
    if str(row['request_hash'] or '') != request_hash:
        raise ValueError('Idempotency-Key was already used with a different request body')
    stored = row['response_json']
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except (TypeError, ValueError) as exc:
            raise ValueError('Stored idempotent response is invalid; contact an administrator') from exc
    if not isinstance(stored, dict):
        raise ValueError('Stored idempotent response is invalid; contact an administrator')
    return {**stored, '_idempotency_replay': True}


def _store_idempotency_response(
    conn,
    *,
    tenant_id: str,
    operation: str,
    idempotency_key: str | None,
    payload: dict,
    response: dict,
    resource_type: str,
) -> None:
    key = _idempotency_key(idempotency_key)
    if not key:
        return
    tenant_key = str(tenant_id or 'tenant-default').strip() or 'tenant-default'
    resource_id = str(response.get('id') or response.get('ipam_address_id') or 'batch')
    conn.execute(
        '''INSERT INTO ipam_idempotency_records
               (tenant_id, operation, idempotency_key, request_hash, response_json,
                resource_type, resource_id)
           VALUES (?, ?, ?, ?, CAST(? AS JSONB), ?, ?)''',
        (
            tenant_key, operation, key, _idempotency_hash(payload),
            json.dumps(response, ensure_ascii=True, sort_keys=True, default=str),
            resource_type, resource_id,
        ),
    )


def _write_ipam_audit(
    conn,
    audit_context: dict | None,
    *,
    event_type: str,
    severity: str,
    summary: str,
    target_type: str,
    target_id: str,
    target_name: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    details: dict | None = None,
) -> None:
    if not audit_context:
        return
    log_audit_event(
        event_type=event_type,
        category='ipam',
        severity=severity,
        status='success',
        summary=summary,
        actor_id=audit_context.get('actor_id'),
        actor_username=audit_context.get('actor_username'),
        actor_role=audit_context.get('actor_role'),
        request_id=audit_context.get('request_id'),
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        before=before,
        after=after,
        details=details,
        conn=conn,
    )


_CROSS_SITE_REUSE_CONDITION_TEMPLATE = """(
    COALESCE(p.is_active, 1) = 1
    AND COALESCE(p.status, '') <> 'stale'
    AND p.address_space_id IS NOT NULL
    AND COALESCE(p.site_id, '') <> ''
    AND EXISTS (
        SELECT 1
        FROM prefixes other_prefix
        WHERE other_prefix.prefix = p.prefix
          AND other_prefix.address_space_id = p.address_space_id
          AND COALESCE(other_prefix.site_id, '') <> ''
          AND other_prefix.site_id <> p.site_id
          AND COALESCE(other_prefix.is_active, 1) = 1
          AND COALESCE(other_prefix.status, '') <> 'stale'
          {other_prefix_allow_sql}
    )
)"""

_PENDING_CROSS_SITE_DUPLICATE_CONDITION_TEMPLATE = """(
    COALESCE(p.is_active, 1) = 1
    AND COALESCE(p.status, '') <> 'stale'
    AND COALESCE(p.tenant_id, '') <> ''
    AND COALESCE(p.site_id, '') <> ''
    AND EXISTS (
        SELECT 1
        FROM prefixes other_prefix
        WHERE other_prefix.prefix = p.prefix
          AND other_prefix.tenant_id = p.tenant_id
          AND COALESCE(other_prefix.site_id, '') <> ''
          AND other_prefix.site_id <> p.site_id
          AND COALESCE(other_prefix.is_active, 1) = 1
          AND COALESCE(other_prefix.status, '') <> 'stale'
          AND (
              COALESCE(NULLIF(p.address_space_id, ''), '') = ''
              OR COALESCE(NULLIF(other_prefix.address_space_id, ''), '') = ''
          )
          {other_prefix_allow_sql}
    )
)"""

CROSS_SITE_REUSE_CONDITION = _CROSS_SITE_REUSE_CONDITION_TEMPLATE.format(
    other_prefix_allow_sql='',
)


def _cross_site_reuse_condition(
    allowed_prefix_ids: list[str] | None = None,
) -> tuple[str, tuple[str, ...]]:
    other_prefix_sql, params = _allowed_prefix_filter(
        allowed_prefix_ids,
        column='other_prefix.id',
    )
    return _CROSS_SITE_REUSE_CONDITION_TEMPLATE.format(
        other_prefix_allow_sql=other_prefix_sql,
    ), params


def _pending_cross_site_duplicate_condition(
    allowed_prefix_ids: list[str] | None = None,
) -> tuple[str, tuple[str, ...]]:
    other_prefix_sql, params = _allowed_prefix_filter(
        allowed_prefix_ids,
        column='other_prefix.id',
    )
    return _PENDING_CROSS_SITE_DUPLICATE_CONDITION_TEMPLATE.format(
        other_prefix_allow_sql=other_prefix_sql,
    ), params

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
    classification: str = 'all', allowed_prefix_ids: list[str] | None = None,
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
        if classification == 'reuse':
            filter_sql, other_prefix_params = _cross_site_reuse_condition(allowed_prefix_ids)
            params.extend(other_prefix_params)
        clauses.append(filter_sql)
    return ' AND '.join(clauses), tuple(params)


def _allowed_prefix_filter(
    allowed_prefix_ids: list[str] | None,
    *,
    column: str = 'p.id',
) -> tuple[str, tuple[str, ...]]:
    """Build an optional allowlist filter for a Prefix-owned query."""
    if allowed_prefix_ids is None:
        return '', ()
    normalized_ids = tuple(sorted({str(value).strip() for value in allowed_prefix_ids if str(value).strip()}))
    if not normalized_ids:
        return ' AND 1 = 0', ()
    placeholders = ', '.join(_PH for _ in normalized_ids)
    return f' AND {column} IN ({placeholders})', normalized_ids


def _cross_site_reuse_ids(
    conn,
    rows: list[dict],
    allowed_prefix_ids: list[str] | None = None,
) -> set[str]:
    """Find current page rows whose CIDR is reused across assigned sites.

    Site is an IPAM address-space boundary. The same CIDR may be valid in
    another site or VRF, so reuse is reported separately from conflict_status.
    """
    ids = [str(row.get('id') or '') for row in rows if row.get('id')]
    if not ids:
        return set()
    placeholders = ', '.join(_PH for _ in ids)
    reuse_condition, other_prefix_params = _cross_site_reuse_condition(allowed_prefix_ids)
    matches = conn.execute(
        f'SELECT p.id FROM prefixes p WHERE p.id IN ({placeholders}) AND {reuse_condition}',
        (*ids, *other_prefix_params),
    ).fetchall()
    return {str(row['id']) for row in matches}


def _table_columns(conn, table: str) -> set[str]:
    def load() -> frozenset[str]:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return frozenset(str(row[0]) for row in rows)
    return set(_scoped_read(conn, ('table_columns', table), load))


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
    """Calculate usable host capacity matching ``_prefix_host_bounds``."""
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
    pl = net.prefixlen
    if pl == 128:
        return 1
    if pl == 127:
        return 2
    # IPv6 has no broadcast address; only subnet-router anycast (network_address)
    # is excluded, matching _prefix_host_bounds().
    total = max(0, (2 ** (128 - pl)) - 1)
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


def _normalize_host_address(address: str) -> str:
    """Normalize a registered host address without silently discarding a mask."""
    raw_address = str(address or '').strip()
    if '/' in raw_address:
        raise ValueError('IP address must be a host address without a CIDR prefix length')
    if '%' in raw_address and ':' in raw_address:
        raise ValueError('IP address must not include an IPv6 zone identifier')
    return _normalize_address(raw_address)


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


def _container_child_coverage(
    conn,
    prefix: dict,
    network: ipaddress._BaseNetwork,
) -> tuple[int, int, float]:
    """Compute merged address coverage of strict child Prefixes inside a container."""
    space_id = str(prefix.get('address_space_id') or '').strip()
    prefix_id = str(prefix.get('id') or '')
    if space_id:
        rows = conn.execute(
            f'''SELECT id, prefix FROM prefixes
                 WHERE address_space_id = {_PH} AND id <> {_PH}''',
            (space_id, prefix_id),
        ).fetchall()
    else:
        rows = conn.execute(
            f'''SELECT id, prefix FROM prefixes
                 WHERE address_space_id IS NULL
                   AND COALESCE(tenant_id, 'tenant-default') = {_PH}
                   AND COALESCE(vrf_id, '') = {_PH}
                   AND COALESCE(site_id, '') = {_PH}
                   AND id <> {_PH}''',
            (
                str(prefix.get('tenant_id') or 'tenant-default'),
                str(prefix.get('vrf_id') or ''),
                str(prefix.get('site_id') or ''),
                prefix_id,
            ),
        ).fetchall()
    child_ranges: list[tuple[int, int]] = []
    for row in rows:
        try:
            child_net = ipaddress.ip_network(str(row['prefix'] or ''), strict=False)
        except ValueError:
            continue
        if (
            child_net.version == network.version
            and child_net.prefixlen > network.prefixlen
            and child_net.subnet_of(network)
        ):
            child_ranges.append((int(child_net.network_address), int(child_net.broadcast_address)))
    merged = _merge_integer_ranges(child_ranges)
    child_ips = min(sum(end - start + 1 for start, end in merged), 2**63)
    container_total = min(int(network.num_addresses), 2**63)
    utilization = round(child_ips / container_total * 100, 1) if container_total > 0 else 0.0
    return child_ips, container_total, utilization


def _calculate_prefix_capacity_metrics(conn, prefix: dict) -> dict:
    """Compute unified registered, reserved, container, and allocatable metrics.

    Shares ``_pool_allocation_intervals`` and ``_current_allocation_occupancy``
    with ``get_next_available_ip_details`` / ``allocate_next_address`` so
    reported allocatable counts stay strictly aligned with real allocation.
    """
    prefix_str = str(prefix.get('prefix') or '')
    status = str(prefix.get('status') or '').strip().lower()
    total_ips = _calculate_total_ips(prefix_str)
    registered_ips = _count_prefix_used_ips(conn, prefix)
    registered_utilization = round(registered_ips / total_ips * 100, 1) if total_ips > 0 else 0.0

    try:
        network = ipaddress.ip_network(prefix_str, strict=False)
    except ValueError:
        return {
            'total_ips': 0,
            'used_ips': registered_ips,
            'registered_ips': registered_ips,
            'registered_utilization': 0.0,
            'reserved_ips': 0,
            'occupied_in_allocatable_ips': 0,
            'allocatable_capacity_ips': 0,
            'allocatable_free_ips': 0,
            'effective_used_ips': registered_ips,
            'effective_utilization': 0.0,
            'container_child_ips': 0,
            'container_utilization': 0.0,
            'utilization': 0.0,
            'allocation_ready': False,
            'allocation_blocked_reason': 'invalid_prefix',
        }

    if status == 'container':
        child_ips, _container_total, container_util = _container_child_coverage(conn, prefix, network)
        return {
            'total_ips': total_ips,
            'used_ips': registered_ips,
            'registered_ips': registered_ips,
            'registered_utilization': registered_utilization,
            'reserved_ips': 0,
            'occupied_in_allocatable_ips': 0,
            'allocatable_capacity_ips': 0,
            'allocatable_free_ips': 0,
            'effective_used_ips': child_ips,
            'effective_utilization': container_util,
            'container_child_ips': child_ips,
            'container_utilization': container_util,
            'utilization': container_util,
            'allocation_ready': False,
            'allocation_blocked_reason': 'container_prefix',
        }

    space_id = str(prefix.get('address_space_id') or '').strip()
    if not space_id:
        return {
            'total_ips': total_ips,
            'used_ips': registered_ips,
            'registered_ips': registered_ips,
            'registered_utilization': registered_utilization,
            'reserved_ips': 0,
            'occupied_in_allocatable_ips': min(registered_ips, total_ips),
            'allocatable_capacity_ips': 0,
            'allocatable_free_ips': 0,
            'effective_used_ips': registered_ips,
            'effective_utilization': registered_utilization,
            'container_child_ips': 0,
            'container_utilization': 0.0,
            'utilization': registered_utilization,
            'allocation_ready': False,
            'allocation_blocked_reason': 'scope_pending',
        }

    host_start, host_end = _prefix_host_bounds(network)
    if host_start > host_end:
        allowed_intervals: list[tuple[int, int]] = []
    elif _table_exists(conn, 'ipam_pools'):
        allowed_intervals = _pool_allocation_intervals(conn, prefix, network)
    else:
        allowed_intervals = [(host_start, host_end)]

    allocatable_capacity_ips = min(
        sum(end - start + 1 for start, end in allowed_intervals),
        2**63,
    )
    reserved_ips = max(0, total_ips - allocatable_capacity_ips)

    occupied_in_allocatable_ips = 0
    if allowed_intervals:
        occupied_set, _pending = _current_allocation_occupancy(conn, prefix, network)
        for value in occupied_set:
            try:
                parsed = ipaddress.ip_address(value)
            except ValueError:
                continue
            if parsed.version != network.version:
                continue
            addr_int = int(parsed)
            if any(start <= addr_int <= end for start, end in allowed_intervals):
                occupied_in_allocatable_ips += 1

    allocatable_free_ips = max(0, allocatable_capacity_ips - occupied_in_allocatable_ips)
    effective_used_ips = min(total_ips, reserved_ips + occupied_in_allocatable_ips)
    effective_utilization = round(effective_used_ips / total_ips * 100, 1) if total_ips > 0 else 0.0

    return {
        'total_ips': total_ips,
        'used_ips': registered_ips,
        'registered_ips': registered_ips,
        'registered_utilization': registered_utilization,
        'reserved_ips': reserved_ips,
        'occupied_in_allocatable_ips': occupied_in_allocatable_ips,
        'allocatable_capacity_ips': allocatable_capacity_ips,
        'allocatable_free_ips': allocatable_free_ips,
        'effective_used_ips': effective_used_ips,
        'effective_utilization': effective_utilization,
        'container_child_ips': 0,
        'container_utilization': 0.0,
        'utilization': registered_utilization,
        'allocation_ready': True,
        'allocation_blocked_reason': '' if allocatable_free_ips > 0 else 'exhausted',
    }


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
    """Return current successful interface rows and uniquely mapped contexts.

    Typed contexts match source/type/key. An unknown context with a non-empty
    raw local key may resolve only through one active same-device/source mapping.
    An empty unknown context may resolve only through an explicit global mapping
    keyed ``--``; absent or ambiguous mappings remain unresolved.
    """
    rows = conn.execute(
        """WITH current_addresses AS (
                SELECT address.device_id, address.normalized_interface_name,
                       address.interface_name, host(address.ip_address) AS ip_address,
                       address.ip_prefix_length, address.context_source,
                       address.context_type, address.local_context_key,
                       address.local_context_name, address.generation,
                       COALESCE(interface.observed_at, address.observed_at::text) AS observed_at,
                       address.run_id,
                       interface.interface_type, interface.admin_status,
                       interface.oper_status
                  FROM cmdb_device_interface_address_observations AS address
                  JOIN cmdb_collection_snapshots AS snapshot
                    ON snapshot.device_id = address.device_id
                   AND snapshot.domain = 'interface_inventory'
                   AND snapshot.successful_generation = address.generation
                  LEFT JOIN cmdb_device_interface_observations AS interface
                    ON interface.device_id = address.device_id
                   AND interface.normalized_interface_name = address.normalized_interface_name
                   AND interface.generation = address.generation
                UNION ALL
                SELECT interface.device_id, interface.normalized_interface_name,
                       interface.interface_name, interface.ip_address,
                       interface.ip_prefix_length, 'cli'::text AS context_source,
                       'unknown'::text AS context_type, ''::text AS local_context_key,
                       ''::text AS local_context_name, interface.generation,
                       interface.observed_at, interface.run_id,
                       interface.interface_type, interface.admin_status,
                       interface.oper_status
                  FROM cmdb_device_interface_observations AS interface
                  JOIN cmdb_collection_snapshots AS snapshot
                    ON snapshot.device_id = interface.device_id
                   AND snapshot.domain = 'interface_inventory'
                   AND snapshot.successful_generation = interface.generation
                 WHERE COALESCE(interface.ip_address, '') <> ''
                   AND NOT EXISTS (
                       SELECT 1
                         FROM cmdb_device_interface_address_observations AS address
                        WHERE address.device_id = interface.device_id
                          AND address.normalized_interface_name = interface.normalized_interface_name
                          AND address.generation = interface.generation
                   )
            )
            SELECT observation.device_id, observation.normalized_interface_name,
                   observation.interface_name, observation.ip_address,
                   observation.ip_prefix_length, observation.interface_type,
                   observation.observed_at, observation.run_id,
                   observation.context_source, observation.context_type,
                   observation.local_context_key, observation.local_context_name,
                   CASE
                     WHEN routing_mapping.mapping_count = 1
                     THEN routing_mapping.address_space_id
                     ELSE NULL
                   END AS address_space_id,
                   CASE
                     WHEN routing_mapping.mapping_count = 1
                     THEN routing_mapping.vrf_id
                     ELSE NULL
                   END AS mapped_vrf_id,
                   observation.admin_status, observation.oper_status,
                   device.hostname AS device_hostname, device.ip_address AS device_ip,
                   COALESCE(device.tenant_id, 'tenant-default') AS tenant_id,
                   device.site_id AS device_site_id, device.site AS device_site,
                   asset.site_id AS asset_site_id
              FROM current_addresses AS observation
              JOIN devices AS device ON device.id = observation.device_id
              LEFT JOIN physical_assets AS asset ON asset.id = device.asset_id
              LEFT JOIN LATERAL (
                    SELECT COUNT(*) AS mapping_count,
                           CASE WHEN COUNT(*) = 1 THEN MIN(candidate.address_space_id) END AS address_space_id,
                           CASE WHEN COUNT(*) = 1 THEN MIN(space.vrf_id) END AS vrf_id
                      FROM ipam_device_routing_contexts AS candidate
                      JOIN ipam_address_spaces AS space ON space.id = candidate.address_space_id
                     WHERE candidate.device_id = observation.device_id
                       AND candidate.context_source = observation.context_source
                       AND (
                           candidate.local_context_key = observation.local_context_key
                           OR (observation.context_type = 'unknown'
                               AND btrim(observation.local_context_key) = ''
                               AND candidate.context_type = 'global'
                               AND candidate.local_context_key = '--')
                       )
                       AND candidate.status = 'active'
                       AND space.status = 'active'
                       AND space.security_tenant_id = COALESCE(device.tenant_id, 'tenant-default')
                       AND (
                           (candidate.context_type = observation.context_type
                            AND ((candidate.context_type = 'vrf' AND space.kind = 'vrf')
                              OR (candidate.context_type = 'global' AND space.kind = 'global')))
                           OR (observation.context_type = 'unknown'
                               AND (
                                   (btrim(observation.local_context_key) <> ''
                                    AND candidate.context_type IN ('vrf', 'global'))
                                   OR (btrim(observation.local_context_key) = ''
                                       AND candidate.context_type = 'global'
                                       AND candidate.local_context_key = '--')
                               )
                               AND ((candidate.context_type = 'vrf' AND space.kind = 'vrf')
                                 OR (candidate.context_type = 'global' AND space.kind = 'global')))
                       )
              ) AS routing_mapping ON TRUE
              ORDER BY device.hostname, observation.normalized_interface_name,
                       observation.ip_address"""
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


def _validate_address_space_gateway_policy(
    conn,
    subnet,
    address: str,
    *,
    device_type: str = '',
    purpose: str = '',
) -> None:
    """Protect configured gateways across Prefixes in one resolved space."""
    gateway_role = (
        str(device_type or '').strip().lower() == 'gateway'
        or str(purpose or '').strip().lower() == 'gateway'
    )
    try:
        network = ipaddress.ip_network(subnet['prefix'], strict=False)
    except ValueError:
        return
    own_gateway = _configured_prefix_gateway(subnet)
    if gateway_role and address == own_gateway:
        return
    if address in _space_gateway_reservations(conn, subnet, network):
        raise ValueError(
            f'Gateway address {address} is reserved by another Prefix in this address space'
        )


def _discovered_address_reservations(
    conn,
    network: ipaddress._BaseNetwork,
    *,
    tenant_id: str,
    vrf_id: str,
    site_id: str,
    address_space_id: str | None = None,
) -> tuple[set[str], set[str]]:
    """Return current-page discovered occupancy split by scope certainty.

    Active endpoints are scoped through their CMDB device. Interface IPs come
    only from each device's latest successful interface snapshot and have no
    VRF, so they are pending host reservations when tenant and site are known.
    """
    tenant = str(tenant_id or 'tenant-default').strip()
    target_space = str(address_space_id or '').strip()
    target_site = str(site_id or '').strip()
    if not tenant:
        return set(), set()
    sites = {
        str(row['id']): {
            'id': str(row['id']),
            'name': row['site_name'] or row['site_code'] or '',
            'code': row['site_code'] or '',
            'tenant_id': str(row['tenant_id'] or 'tenant-default'),
        }
        for row in _scoped_read(
            conn, ('sites',),
            lambda: conn.execute('SELECT id, site_name, site_code, tenant_id FROM sites').fetchall(),
        )
    }
    pending: set[str] = set()
    resolved: set[str] = set()
    from services.ipam_current_endpoint_observation_service import list_current_endpoint_observations

    current_address_observations = _scoped_read(conn, ('current_arp_ndp_observations',), lambda: [
        *list_current_endpoint_observations(conn, observation_source="arp"),
        *list_current_endpoint_observations(conn, observation_source="ndp"),
    ])
    current_neighbor_identity_keys: set[tuple[str, str, str, str]] = set()
    for observation in current_address_observations:
        try:
            address = ipaddress.ip_address(str(observation.get('ip_address') or '').strip())
        except ValueError:
            continue
        canonical_address = str(address)
        owner = {
            'cmdb_device_id': observation.get('source_device_id'),
            'asset_site_id': observation.get('asset_site_id'),
            'device_site_id': observation.get('device_site_id'),
            'device_site': observation.get('device_site'),
        }
        observed_site = endpoint_site_id(owner, sites)
        observed_mac = ''.join(
            char for char in str(observation.get('mac_address') or '').lower()
            if char in '0123456789abcdef'
        )
        observation_tenant = str(observation.get('tenant_id') or 'tenant-default')
        if observed_mac:
            current_neighbor_identity_keys.add((
                canonical_address, observed_mac, observation_tenant, observed_site,
            ))
        if address.version != network.version or address not in network:
            continue
        observed_space_id = str(observation.get('address_space_id') or '')
        if observed_space_id:
            if target_space and observed_space_id == target_space:
                resolved.add(canonical_address)
            # A unique explicit device/context mapping owns the observation in
            # exactly one address space; it cannot reserve a mapped sibling.
            continue
        if target_site and observation_tenant == tenant and observed_site == target_site:
            # Current ARP/ND facts with no unique local-context mapping retain
            # only this host as pending within the observed tenant/site.
            pending.add(canonical_address)

    from services.ipam_current_fhrp_projection_service import list_current_fhrp_observation_projection

    for observation in _scoped_read(
        conn, ('current_fhrp_projection',), lambda: list_current_fhrp_observation_projection(conn),
    ):
        try:
            address = ipaddress.ip_address(str(observation.get('virtual_ip') or '').strip())
        except ValueError:
            continue
        canonical_address = str(address)
        if address.version != network.version or address not in network:
            continue
        observation_tenant = str(observation.get('tenant_id') or 'tenant-default')
        observed_space_id = str(observation.get('address_space_id') or '')
        if observation.get('scope_status') == 'resolved' and observed_space_id:
            if target_space and observed_space_id == target_space:
                # The HSRP/VRRP virtual address is current host occupancy even
                # when no formal VIP has been linked yet. Multiple member
                # observations collapse naturally into this address set.
                resolved.add(canonical_address)
            continue
        owner = {
            'cmdb_device_id': observation.get('source_device_id'),
            'asset_site_id': observation.get('site_id'),
            'device_site_id': observation.get('site_id'),
        }
        observed_site = endpoint_site_id(owner, sites)
        if target_site and observation_tenant == tenant and observed_site == target_site:
            pending.add(canonical_address)

    if _table_exists(conn, 'network_endpoints'):
        endpoint_rows = _scoped_read(conn, ('active_network_endpoints',), lambda: conn.execute(
            """SELECT ne.ip, ne.mac, ne.vrf, ne.site, ne.switch_id,
                      d.id AS cmdb_device_id, d.tenant_id AS device_tenant_id,
                      d.site_id AS device_site_id, d.site AS device_site,
                      pa.site_id AS asset_site_id
                 FROM network_endpoints ne
                 LEFT JOIN devices d ON d.id = ne.switch_id
                 LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                WHERE ne.is_active = 1 AND COALESCE(ne.ip, '') <> ''"""
        ).fetchall())
        for row in endpoint_rows:
            endpoint = dict(row)
            try:
                address = ipaddress.ip_address(str(endpoint.get('ip') or '').strip())
            except ValueError:
                continue
            if address.version != network.version or address not in network:
                continue
            owner = {
                'cmdb_device_id': endpoint.get('cmdb_device_id'),
                'asset_site_id': endpoint.get('asset_site_id'),
                'device_site_id': endpoint.get('device_site_id'),
                'device_site': endpoint.get('device_site'),
                'site': endpoint.get('site'),
            }
            observed_site = endpoint_site_id(owner, sites)
            if endpoint.get('cmdb_device_id'):
                device_tenant = str(endpoint.get('device_tenant_id') or 'tenant-default')
            else:
                device_tenant = str((sites.get(observed_site) or {}).get('tenant_id') or '')
            if not device_tenant or device_tenant != tenant:
                continue
            legacy_mac = ''.join(
                char for char in str(endpoint.get('mac') or '').lower()
                if char in '0123456789abcdef'
            )
            if (
                legacy_mac and (
                    str(address), legacy_mac, device_tenant, observed_site,
                ) in current_neighbor_identity_keys
            ):
                # The scoped current ARP/ND projection preserves same-IP
                # identities that the legacy cache can only collapse.
                continue
            if endpoint.get('cmdb_device_id'):
                endpoint['device_tenant_id'] = device_tenant
                scope_key = endpoint_address_key(endpoint)
            else:
                scope_key = endpoint_address_key(endpoint)
            if scope_key is not None:
                observed_space_id = scope_key[1].removeprefix('space:')
                if target_space and observed_space_id == target_space:
                    resolved.add(str(address))
                # A positively mapped foreign address space must not reserve
                # this one. Legacy VRF names are not canonical identity.
                continue
            if target_site and observed_site == target_site:
                pending.add(str(address))

    for observation in _scoped_read(
        conn, ('cmdb_interface_ip_observations',), lambda: _current_cmdb_interface_ip_observations(conn),
    ):
        try:
            address = ipaddress.ip_address(str(observation.get('ip_address') or '').strip())
        except ValueError:
            continue
        if address.version != network.version or address not in network:
            continue
        observation_tenant = str(observation.get('tenant_id') or 'tenant-default')
        observed_space_id = str(observation.get('address_space_id') or '')
        if observed_space_id:
            if target_space and observed_space_id == target_space:
                resolved.add(str(address))
            # A positively mapped interface context in another address space
            # cannot reserve this Prefix, even when the devices share a site.
            continue
        owner = {
            'cmdb_device_id': observation.get('device_id'),
            'asset_site_id': observation.get('asset_site_id'),
            'device_site_id': observation.get('device_site_id'),
            'device_site': observation.get('device_site'),
        }
        observed_site = endpoint_site_id(owner, sites)
        if target_site and observation_tenant == tenant and observed_site == target_site:
            # Unmapped device-local context reserves only this observed host
            # within the matching tenant/site; it never becomes Global by name.
            pending.add(str(address))

    pending.difference_update(resolved)
    return resolved, pending


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
    """Reject active addresses in the same address space (or legacy scope)."""
    tenant_id = subnet['tenant_id'] or 'tenant-default'
    vrf_id = subnet['vrf_id'] or ''
    address_space_id = str(subnet.get('address_space_id') or '').strip()
    params = [address]
    exclude_sql = ''
    if exclude_id:
        exclude_sql = f' AND ip.id <> {_PH}'
    if address_space_id:
        params = [address_space_id, address, *([exclude_id] if exclude_id else [])]
        existing = conn.execute(
            f"""SELECT ip.id FROM ip_addresses ip
                 WHERE ip.address_space_id = {_PH}
                   AND ip.address_inet = CAST({_PH} AS inet)
                   AND COALESCE(ip.status, 'active') NOT IN ('released', 'available')
                   {exclude_sql}
                 LIMIT 1""",
            tuple(params),
        ).fetchone()
    else:
        params = [address, tenant_id, vrf_id, *([exclude_id] if exclude_id else [])]
        existing = conn.execute(
            f"""SELECT ip.id FROM ip_addresses ip
                 LEFT JOIN prefixes p ON p.id = ip.subnet_id
                 WHERE ip.address = {_PH}
                   AND p.address_space_id IS NULL
                   AND COALESCE(p.tenant_id, 'tenant-default') = {_PH}
                   AND COALESCE(p.vrf_id, '') = {_PH}
                   AND COALESCE(ip.status, 'active') NOT IN ('released', 'available')
                   {exclude_sql}
                 LIMIT 1""",
            tuple(params),
        ).fetchone()
    if existing:
        try:
            from core.metrics import metrics_registry
            metrics_registry.record_ipam_conflict()
        except Exception:
            pass
        scope_label = 'address space' if address_space_id else 'legacy tenant/VRF scope'
        raise ValueError(f'IP address {address} is already allocated in this {scope_label}')
    vip = None
    if address_space_id and _table_exists(conn, 'ipam_vips'):
        vip = conn.execute(
            f"""SELECT id FROM ipam_vips
                WHERE address_space_id = {_PH}
                  AND address_inet = CAST({_PH} AS inet)
                  AND COALESCE(status, 'active') NOT IN ('released', 'deprecated', 'disabled') LIMIT 1""",
            (address_space_id, address),
        ).fetchone()
    if vip:
        try:
            from core.metrics import metrics_registry
            metrics_registry.record_ipam_conflict()
        except Exception:
            pass
        raise ValueError(f'IP address {address} conflicts with an active VIP')


def _validate_prefix_vlan(
    conn,
    *,
    vlan_id: str | None,
    tenant_id: str | None,
    site_id: str | None,
) -> str | None:
    """Validate that an attached VLAN exists and matches the Prefix tenant/site scope."""
    normalized_vlan_id = str(vlan_id or '').strip()
    if not normalized_vlan_id:
        return None
    vlan = conn.execute(
        f'SELECT id, tenant_id, site_id FROM vlans WHERE id = {_PH}',
        (normalized_vlan_id,),
    ).fetchone()
    if not vlan:
        raise ValueError(f'VLAN not found: {normalized_vlan_id}')
    vlan_tenant = str(vlan['tenant_id'] or 'tenant-default').strip()
    target_tenant = str(tenant_id or 'tenant-default').strip()
    if vlan_tenant != target_tenant:
        raise ValueError('Selected VLAN belongs to a different security tenant')
    vlan_site = str(vlan['site_id'] or '').strip()
    target_site = str(site_id or '').strip()
    if vlan_site and not target_site:
        raise ValueError('Site-scoped VLAN cannot be attached to a Prefix without a matching site')
    if vlan_site and target_site and vlan_site != target_site:
        raise ValueError('Selected VLAN belongs to a different site')
    return normalized_vlan_id


def _validate_prefix_cidr_contains_children(
    conn,
    prefix_id: str,
    target_network: ipaddress._BaseNetwork,
) -> None:
    """Reject CIDR edits that would leave active child IPs, Pools, or VIPs outside the Prefix."""
    ip_rows = conn.execute(
        f"""SELECT id, address
              FROM ip_addresses
             WHERE subnet_id = {_PH}
               AND COALESCE(status, 'active') NOT IN ('released', 'available')""",
        (prefix_id,),
    ).fetchall()
    for row in ip_rows:
        raw_addr = str(row['address'] or '').strip()
        if not raw_addr:
            continue
        try:
            addr = ipaddress.ip_address(raw_addr)
        except ValueError:
            continue
        if addr.version != target_network.version or addr not in target_network:
            raise ValueError(
                f'Prefix {target_network} does not contain existing formal IP address {addr}'
            )

    if _table_exists(conn, 'ipam_pools'):
        pool_rows = conn.execute(
            f'SELECT id, name, start_ip, end_ip FROM ipam_pools WHERE prefix_id = {_PH}',
            (prefix_id,),
        ).fetchall()
        for row in pool_rows:
            for endpoint in (row['start_ip'], row['end_ip']):
                raw_addr = str(endpoint or '').strip()
                if not raw_addr:
                    continue
                try:
                    addr = ipaddress.ip_address(raw_addr)
                except ValueError:
                    continue
                if addr.version != target_network.version or addr not in target_network:
                    pool_label = str(row['name'] or row['id'])
                    raise ValueError(
                        f'Prefix {target_network} does not contain existing IP pool {pool_label} ({addr})'
                    )

    if _table_exists(conn, 'ipam_vips'):
        vip_rows = conn.execute(
            f"""SELECT id, address_inet
                  FROM ipam_vips
                 WHERE prefix_id = {_PH}
                   AND COALESCE(status, 'active') NOT IN ('released', 'deprecated', 'disabled')""",
            (prefix_id,),
        ).fetchall()
        for row in vip_rows:
            raw_addr = str(row['address_inet'] or '').strip().split('/', 1)[0]
            if not raw_addr:
                continue
            try:
                addr = ipaddress.ip_address(raw_addr)
            except ValueError:
                continue
            if addr.version != target_network.version or addr not in target_network:
                raise ValueError(
                    f'Prefix {target_network} does not contain existing VIP {addr}'
                )


def _validate_prefix_overlap(conn, *, prefix: str, tenant_id: str | None = None,
                             vrf_id: str | None = None, site_id: str | None = None,
                             address_space_id: str | None = None,
                             exclude_id: str | None = None) -> None:
    """Reject duplicate or sibling-overlap Prefixes in one routing domain.

    Parent/child containment is allowed; partial sibling overlap and exact duplicate
    are rejected. Site is not an address identity when a canonical space exists.
    """
    normalized, new_net = _normalize_prefix(prefix)
    tenant = tenant_id or 'tenant-default'
    vrf = vrf_id or ''
    site = site_id or ''

    if address_space_id:
        rows = conn.execute(
            f"""SELECT id, prefix FROM prefixes
                 WHERE address_space_id = {_PH}""",
            (address_space_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""SELECT id, prefix FROM prefixes
                 WHERE address_space_id IS NULL
                   AND COALESCE(tenant_id, 'tenant-default') = {_PH}
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
            raise ValueError(f"Prefix {normalized} already exists in this address space")
        if new_net.subnet_of(existing) or existing.subnet_of(new_net):
            continue
        raise ValueError(f"Prefix {normalized} overlaps with existing sibling prefix {row['prefix']}")


def _prefix_lock_scope(prefix: dict) -> tuple[str, str, str]:
    return (
        str(prefix.get('tenant_id') or 'tenant-default').strip() or 'tenant-default',
        str(prefix.get('address_space_id') or '').strip(),
        str(prefix.get('vrf_id') or '').strip(),
    )


def _lock_prefixes_with_scopes(
    conn,
    prefix_ids: set[str],
    *,
    missing_ok: bool = False,
    extra_scopes: set[tuple[str, str, str]] | None = None,
) -> dict[str, dict]:
    """Acquire all scope locks before Prefix rows, with deterministic ordering.

    Scope is read optimistically to discover the advisory locks. After those
    locks are held, Prefix rows are locked by ID and their scope is rechecked
    so a concurrent mapping change cannot make us proceed under the wrong
    address-space lock.
    """
    normalized_ids = sorted({str(value or '').strip() for value in prefix_ids if str(value or '').strip()})
    initial: dict[str, dict] = {}
    for prefix_id in normalized_ids:
        row = conn.execute(
            f'SELECT id, tenant_id, address_space_id, vrf_id FROM prefixes WHERE id = {_PH}',
            (prefix_id,),
        ).fetchone()
        if row:
            initial[prefix_id] = dict(row)
        elif not missing_ok:
            raise ValueError('The selected prefix does not exist')

    scopes = {_prefix_lock_scope(row) for row in initial.values()}
    scopes.update(
        (
            str(tenant_id or 'tenant-default').strip() or 'tenant-default',
            str(address_space_id or '').strip(),
            str(vrf_id or '').strip(),
        )
        for tenant_id, address_space_id, vrf_id in (extra_scopes or set())
    )
    for tenant_id, address_space_id, vrf_id in sorted(scopes):
        lock_ipam_scope(
            conn,
            security_tenant_id=tenant_id,
            address_space_id=address_space_id,
            vrf_id=vrf_id,
        )

    locked: dict[str, dict] = {}
    for prefix_id in sorted(initial):
        row = conn.execute(
            f'SELECT * FROM prefixes WHERE id = {_PH} FOR UPDATE',
            (prefix_id,),
        ).fetchone()
        if not row:
            if missing_ok:
                continue
            raise ValueError('The selected prefix does not exist')
        record = dict(row)
        if _prefix_lock_scope(record) != _prefix_lock_scope(initial[prefix_id]):
            raise ValueError('Prefix scope changed concurrently; refresh and retry')
        locked[prefix_id] = record
    return locked


def _select_prefix_for_update(conn, subnet_id: str):
    return _lock_prefixes_with_scopes(
        conn, {str(subnet_id or '')}, missing_ok=True,
    ).get(str(subnet_id or '').strip())


def _ph(n: int = 1) -> str:
    """Return n comma-separated placeholders."""
    return ', '.join([_PH] * n)


# ══════════════════════════════════════════════════════════
# Prefix Hierarchy
# ══════════════════════════════════════════════════════════

def _prefix_hierarchy_scope_key(row: dict) -> tuple:
    address_space_id = str(row.get('address_space_id') or '').strip()
    if address_space_id:
        return ('space', address_space_id)
    return (
        'legacy',
        str(row.get('tenant_id') or 'tenant-default'),
        str(row.get('vrf_id') or ''),
        str(row.get('site_id') or ''),
    )


def rebuild_prefixes_hierarchy(conn=None, *, scope_keys: set[tuple] | None = None, commit: bool = True):
    """Rebuild parent_prefix_id for prefixes using CIDR containment rules.
    The most-specific (longest prefix) containing network becomes the parent.
    Within each address space (or legacy scope), prefixes form a tree.

    When ``scope_keys`` is provided, only prefixes in the affected scopes are
    loaded and recalculated. When ``commit`` is False, updates stay in the
    caller's transaction so prefix writes and hierarchy updates commit atomically.
    """
    should_close = conn is None
    if conn is None:
        conn = get_db_connection()
    try:
        if scope_keys is not None:
            normalized_scopes = set(scope_keys)
            if not normalized_scopes:
                return
            space_ids = sorted({scope[1] for scope in normalized_scopes if scope[0] == 'space' and scope[1]})
            has_legacy = any(scope[0] == 'legacy' for scope in normalized_scopes)
            clauses = []
            params: list = []
            if space_ids:
                placeholders = ', '.join(_PH for _ in space_ids)
                clauses.append(f'address_space_id IN ({placeholders})')
                params.extend(space_ids)
            if has_legacy:
                clauses.append('address_space_id IS NULL')
            if not clauses:
                return
            rows = conn.execute(
                f'''SELECT id, prefix, vrf_id, tenant_id, site_id, address_space_id, parent_prefix_id
                      FROM prefixes
                     WHERE {' OR '.join(clauses)}''',
                tuple(params),
            ).fetchall()
        else:
            normalized_scopes = None
            rows = conn.execute(
                'SELECT id, prefix, vrf_id, tenant_id, site_id, address_space_id, parent_prefix_id FROM prefixes'
            ).fetchall()

        items_by_scope: dict[tuple, list[dict]] = {}
        for r in rows:
            scope_key = _prefix_hierarchy_scope_key(dict(r))
            if normalized_scopes is not None and scope_key not in normalized_scopes:
                continue
            try:
                net = ipaddress.ip_network(r['prefix'], strict=False)
                items_by_scope.setdefault(scope_key, []).append({
                    'id': r['id'],
                    'prefix': r['prefix'],
                    'current_parent_id': r['parent_prefix_id'],
                    'net': net,
                    'prefixlen': net.prefixlen,
                })
            except ValueError:
                continue

        updated_count = 0
        for scope_items in items_by_scope.values():
            scope_items.sort(key=lambda x: x['prefixlen'])
            for i, item in enumerate(scope_items):
                best_parent = None
                best_len = -1
                for j, candidate in enumerate(scope_items):
                    if i == j:
                        continue
                    if item['net'].version != candidate['net'].version:
                        continue
                    if candidate['prefixlen'] >= item['prefixlen']:
                        continue
                    if item['net'].subnet_of(candidate['net']):
                        if candidate['prefixlen'] > best_len:
                            best_len = candidate['prefixlen']
                            best_parent = candidate['id']
                if item['current_parent_id'] != best_parent:
                    conn.execute(
                        f'UPDATE prefixes SET parent_prefix_id = {_PH} WHERE id = {_PH}',
                        (best_parent, item['id']),
                    )
                    updated_count += 1
        if commit:
            conn.commit()
        logger.info("Rebuilt prefix hierarchy (%d parent updates).", updated_count)
    finally:
        if should_close:
            conn.close()


# ══════════════════════════════════════════════════════════
# Subnet (Prefix) CRUD — using the `prefixes` table
# ══════════════════════════════════════════════════════════

@_with_read_scope_cache
def list_subnets(
    *, site: str = 'all', status: str = 'all', q: str = '', family: str = 'all',
    classification: str = 'all', page: int | None = None, page_size: int = 20,
    allowed_prefix_ids: list[str] | None = None,
    include_metrics: bool = True,
) -> list[dict] | dict:
    conn = get_db_connection()
    try:
        where_sql, filter_params = build_prefix_filter_clause(
            site=site, status=status, q=q, family=family, classification=classification,
            allowed_prefix_ids=allowed_prefix_ids,
        )
        allowed_sql, allowed_params = _allowed_prefix_filter(allowed_prefix_ids)
        where_sql += allowed_sql
        params: list = [*filter_params, *allowed_params]
        sql = f'''
            SELECT p.*,
                   v.vrf_name,
                   asp.name AS address_space_name,
                   asp.kind AS address_space_kind,
                   vl.vlan_id AS vlan_number, vl.name AS vlan_display_name,
                   s.site_name, s.site_code,
                   t.name AS tenant_name,
                   d.hostname AS gateway_device_name
            FROM prefixes p
            LEFT JOIN vrfs v ON p.vrf_id = v.id
            LEFT JOIN ipam_address_spaces asp ON asp.id = p.address_space_id
            LEFT JOIN vlans vl ON p.vlan_id = vl.id
            LEFT JOIN sites s ON p.site_id = s.id
            LEFT JOIN tenants t ON p.tenant_id = t.id
            LEFT JOIN devices d ON p.gateway_device_id = d.id
            WHERE {where_sql}
        '''
        sql += ' ORDER BY COALESCE(s.site_name, s.site_code, p.site_id, \'\'), p.prefix'
        total: int | None = None
        normalized_page_size = min(max(int(page_size or 20), 1), 100)
        normalized_page = max(int(page or 1), 1)
        if page is not None:
            count_sql = f'SELECT COUNT(*) AS cnt FROM prefixes p WHERE {where_sql}'
            count_row = conn.execute(count_sql, tuple(params)).fetchone()
            total = int(count_row['cnt'] if count_row else 0)
            sql += f' LIMIT {_PH} OFFSET {_PH}'
            params.extend([normalized_page_size, (normalized_page - 1) * normalized_page_size])
        rows = conn.execute(sql, tuple(params)).fetchall()
        raw_items = [dict(row) for row in rows]
        reuse_ids = _cross_site_reuse_ids(conn, raw_items, allowed_prefix_ids)
        suggestions = _suggest_prefix_network_types(conn, raw_items) if include_metrics else {}
        result = []
        for r, item in zip(rows, raw_items):
            item['scope_status'] = 'resolved' if item.get('address_space_id') else 'scope_pending'
            item['cross_site_reuse'] = str(item.get('id') or '') in reuse_ids
            if str(item.get('conflict_status') or '') == 'cross_site_prefix':
                # Old versions persisted legitimate cross-site reuse as a
                # conflict. Hide that legacy label in API responses without
                # rewriting historical rows in the live database.
                item['conflict_status'] = ''
                item['conflict_json'] = '{}'

            if not include_metrics:
                item['vlan_id'] = item.get('vlan_number') or item.get('vlan_id')
                result.append(item)
                continue

            metrics = _calculate_prefix_capacity_metrics(conn, item)
            item.update(metrics)

            # Count discovered IPs that are *currently* observed. `is_active`
            # alone stays 1 long after collection stops, so the count only
            # includes rows inside the discovery freshness window.
            try:
                recent_by_scope = _recent_endpoint_ips(conn)
                prefix_members: set[str] = set()
                interface_alive: set[str] = set()
                for address_row in conn.execute(
                    f'''SELECT address, device_id, interface_name FROM ip_addresses WHERE subnet_id = {_PH}
                          AND COALESCE(status, 'active') NOT IN ('released', 'available')''',
                    (r['id'],),
                ).fetchall():
                    try:
                        member = str(ipaddress.ip_address(str(address_row['address'] or '').split('/')[0].strip()))
                    except ValueError:
                        continue
                    prefix_members.add(member)
                    liveness = _interface_liveness(conn, dict(address_row))
                    if liveness and liveness.get('alive'):
                        interface_alive.add(member)
                gateway = _configured_prefix_gateway(item)
                if gateway:
                    prefix_members.add(gateway)
                prefix_scope = (
                    str(item.get('tenant_id') or 'tenant-default'),
                    str(item.get('site_id') or ''),
                    str(item.get('address_space_id') or ''),
                )
                arp_alive = (
                    prefix_members & recent_by_scope.get(prefix_scope, set())
                    if prefix_scope[1] and prefix_scope[2] else set()
                )
                # Endpoints count when ARP/ND saw them in the current window;
                # device interface (infrastructure) addresses count when their
                # interface was last collected up within the interface window.
                item['active_ips'] = len(arp_alive | interface_alive)
                item['active_arp_ips'] = len(arp_alive)
                item['active_interface_ips'] = len(interface_alive - arp_alive)
            except Exception:
                # On PostgreSQL a failed query aborts the whole transaction;
                # roll back so subsequent statements in this connection survive.
                try:
                    conn.rollback()
                except Exception:
                    pass
                item['active_ips'] = 0

            # Resolve VLAN info
            item['vlan_id'] = item.get('vlan_number') or item.get('vlan_id')

            suggestion = suggestions.get(str(item.get('id') or ''))
            item['suggested_network_type'] = suggestion[0] if suggestion else ''
            item['suggestion_reason'] = suggestion[1] if suggestion else ''

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


def _suggest_prefix_network_types(conn, prefixes: list[dict]) -> dict[str, tuple[str, str]]:
    """Suggest a purpose for unclassified, unlocked prefixes from registered evidence.

    Read-only: the suggestion is returned to the UI and is only stored when an
    operator applies it through the normal batch purpose update. Rules, in order:
      * an address equals a CMDB device management IP -> management
      * every registered address sits on a loopback interface -> loopback
      * /30, /31 (IPv6 /126, /127) link networks -> transit
    """
    candidates: dict[str, ipaddress._BaseNetwork] = {}
    for prefix in prefixes:
        if str(prefix.get('network_type') or 'unclassified').strip().lower() not in ('', 'unclassified'):
            continue
        if prefix.get('manual_override'):
            continue
        try:
            candidates[str(prefix.get('id') or '')] = ipaddress.ip_network(str(prefix.get('prefix') or ''), strict=False)
        except ValueError:
            continue
    candidates.pop('', None)
    if not candidates:
        return {}

    addresses: dict[str, list[tuple[str, str]]] = {prefix_id: [] for prefix_id in candidates}
    management_ips: set[str] = set()
    try:
        ids = list(candidates)
        for start in range(0, len(ids), 200):
            chunk = ids[start:start + 200]
            rows = conn.execute(
                f'''SELECT subnet_id, address, COALESCE(interface_name, '') AS interface_name
                    FROM ip_addresses
                    WHERE subnet_id IN ({_ph(len(chunk))})
                      AND COALESCE(status, 'active') NOT IN ('released', 'available')''',
                tuple(chunk),
            ).fetchall()
            for row in rows:
                addresses.setdefault(str(row['subnet_id']), []).append(
                    (str(row['address'] or ''), str(row['interface_name'] or ''))
                )
        for row in conn.execute(
            "SELECT ip_address FROM devices WHERE COALESCE(ip_address, '') <> ''"
        ).fetchall():
            management_ips.add(str(row['ip_address']).split('/')[0].strip())
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return {}

    suggestions: dict[str, tuple[str, str]] = {}
    for prefix_id, network in candidates.items():
        members = addresses.get(prefix_id) or []
        point_to_point = network.prefixlen in ((30, 31) if network.version == 4 else (126, 127))
        if not point_to_point and any(address in management_ips for address, _ in members):
            suggestions[prefix_id] = ('management', 'device_management_ip')
        elif members and all(_is_loopback_interface_name(name) for _, name in members):
            suggestions[prefix_id] = ('loopback', 'loopback_interface')
        elif point_to_point:
            suggestions[prefix_id] = ('transit', 'point_to_point_mask')
    return suggestions


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
    *,
    prefix: str,
    site_id: str | None,
    tenant_id: str,
    gateway_ip: str | None = None,
    address_space_id: str | None = None,
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
        tenant_key = str(tenant_id or 'tenant-default')
        target_space_id = str(address_space_id or '').strip()
        if target_space_id:
            address_space = conn.execute(
                """SELECT id, security_tenant_id, kind, vrf_id, status
                     FROM ipam_address_spaces WHERE id = ?""",
                (target_space_id,),
            ).fetchone()
            if (
                not address_space
                or str(address_space['security_tenant_id']) != tenant_key
                or str(address_space['status']) != 'active'
            ):
                raise ValueError('Address space is unavailable in the current tenant scope')
            prefix_exists = conn.execute(
                """SELECT 1 FROM prefixes
                     WHERE prefix_cidr = ? AND tenant_id = ?
                       AND address_space_id = ?
                       AND (? IS NULL OR COALESCE(site_id, '') IN ('', ?))
                     LIMIT 1""",
                (str(network), tenant_key, target_space_id, site_id, str(site_id or '')),
            ).fetchone()
            if not prefix_exists:
                raise ValueError('Address space does not own the requested Prefix')
        else:
            possible_spaces = conn.execute(
                """SELECT DISTINCT address_space_id FROM prefixes
                     WHERE prefix_cidr = ? AND tenant_id = ?
                       AND address_space_id IS NOT NULL
                       AND (? IS NULL OR COALESCE(site_id, '') IN ('', ?))""",
                (str(network), tenant_key, site_id, str(site_id or '')),
            ).fetchall()
            unique_spaces = sorted({str(row['address_space_id']) for row in possible_spaces})
            if len(unique_spaces) == 1:
                target_space_id = unique_spaces[0]

        observation_rows = _current_cmdb_interface_ip_observations(conn)
        candidates: list[dict] = []
        down_states = {'down', 'admin_down', 'administratively down', 'shutdown', 'notpresent', 'lowerlayerdown'}
        for row in observation_rows:
            if str(row.get('tenant_id') or 'tenant-default') != tenant_key:
                continue
            admin_state = str(row.get('admin_status') or '').strip().lower()
            oper_state = str(row.get('oper_status') or '').strip().lower()
            # Exclude explicitly down / shutdown interfaces from gateway candidate
            # selection so decommissioned cutover interfaces never hijack or
            # create false ambiguity against the active gateway.
            if admin_state in down_states or oper_state in down_states:
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
            observed_space_id = str(row.get('address_space_id') or '')
            if target_space_id and observed_space_id and observed_space_id != target_space_id:
                continue
            scope_resolved = bool(target_space_id and observed_space_id == target_space_id)
            candidates.append({
                'device_id': str(row.get('device_id') or ''),
                'device_name': str(row.get('device_hostname') or ''),
                'interface_name': str(row.get('interface_name') or ''),
                'interface_id': None,
                'address': address,
                'interface_type': str(row.get('interface_type') or '').strip().lower(),
                'address_space_id': observed_space_id or None,
                'context_source': str(row.get('context_source') or ''),
                'context_type': str(row.get('context_type') or 'unknown'),
                'local_context_key': str(row.get('local_context_key') or ''),
                'scope_status': 'resolved' if scope_resolved else 'scope_pending',
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

        exact_gateway_candidates = [
            item for item in candidates
            if normalized_gateway and item['address'] == normalized_gateway
            and item['scope_status'] == 'resolved'
        ]
        unresolved_gateway_candidates = [
            item for item in candidates
            if normalized_gateway and item['address'] == normalized_gateway
            and item['scope_status'] != 'resolved'
        ]
        if len(exact_gateway_candidates) == 1:
            status, selected = 'matched', exact_gateway_candidates[0]
        elif len(exact_gateway_candidates) > 1:
            status, selected = 'ambiguous', None
        elif unresolved_gateway_candidates or (candidates and not target_space_id):
            status, selected = 'scope_pending', None
        elif candidates:
            status, selected = 'no_candidate', None
        else:
            status, selected = 'no_candidate', None

        # Strip internal mapping keys and return exactly the candidate shape
        # shared by the selected item and the evidence list.
        endpoint_fields = (
            'device_id', 'device_name', 'interface_name', 'interface_id',
            'address', 'interface_type', 'address_space_id', 'context_source',
            'context_type', 'local_context_key', 'scope_status',
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
            'address_space_id': target_space_id or None,
            'selected': selected_result,
            'endpoints': endpoints,
        }
    finally:
        conn.close()


def _is_loopback_interface_name(interface_name: str) -> bool:
    """Recognize canonical loopback names without matching unrelated `lo...` names."""
    name = str(interface_name or '').strip().casefold()
    # H3C/Ruijie CLI output abbreviates LoopBack0 as "Loop0"; Huawei/Cisco use
    # "LoopBack0"/"Loopback0"; Linux uses "lo".
    return bool(re.fullmatch(r'(?:loopback\s?\d*|loop\d+|lo\d*)(?:\.\d+)?', name))


_MANAGEMENT_INTERFACE_RE = re.compile(
    # Out-of-band management ports: H3C M-GigabitEthernet/MGE, Huawei MEth,
    # Cisco/Arista Management/Mgmt, Juniper me0/fxp0/em0.
    r'(?:m-?gigabitethernet|m-?ge|meth|mgmt(?:eth)?|management|me|fxp|em)\s?[\d/:.]+',
    re.I,
)


def _is_management_interface_name(interface_name: str) -> bool:
    return bool(_MANAGEMENT_INTERFACE_RE.fullmatch(str(interface_name or '').strip()))


_VLAN_INTERFACE_RE = re.compile(r'(?:vlan[-_ ]?(?:interface|if)?\s?\d+|vlanif\d+|vl\d+|svi\d*|bdif\d+|irb\.\d+)', re.I)
_TUNNEL_INTERFACE_RE = re.compile(r'(?:tunnel\s?\d+|tun\d+|gre\d+|vxlan[-_]?tunnel\d*|nve\d+)', re.I)
_PHYSICAL_INTERFACE_RE = re.compile(
    r'(?:(?:ten-|twenty-five|forty|hundred|four-hundred)?gigabitethernet|fastethernet|ethernet|eth|'
    r'ge|xge|fge|hge|wge|mge|te|gi|fa|fo|hu|tf|et|xe|'
    r'ragg|bagg|bridge-aggregation|route-aggregation|eth-trunk|port-channel|po|ae|bond)\s?[\d/:.]+',
    re.I,
)


def _classify_interface_address_kind(interface_name: str, prefix_length: int | None = None, ip_version: int | None = None) -> str:
    """Derive the structural interface kind of an interface-generated address.

    This only describes *where* the address lives (loopback, SVI, tunnel,
    point-to-point link, physical port).  It is a display/filter fact derived
    from the interface name and mask; it never overwrites a stored type.
    """
    name = str(interface_name or '').strip()
    if not name:
        return 'interface'
    if _is_loopback_interface_name(name):
        return 'loopback'
    if _VLAN_INTERFACE_RE.fullmatch(name):
        return 'vlan'
    if _TUNNEL_INTERFACE_RE.fullmatch(name):
        return 'tunnel'
    if _is_management_interface_name(name):
        # A management port is never a transit link, whatever its mask.
        return 'physical'
    point_to_point = prefix_length is not None and (
        (ip_version != 6 and prefix_length in (30, 31)) or (ip_version == 6 and prefix_length in (126, 127))
    )
    if _PHYSICAL_INTERFACE_RE.fullmatch(name):
        return 'transit' if point_to_point else 'physical'
    if point_to_point:
        return 'transit'
    return 'interface'


_INTERFACE_KIND_PURPOSE = {
    'loopback': 'loopback',
    'transit': 'transit',
    'tunnel': 'transit',
}


def _derive_interface_address_classification(item: dict) -> None:
    """Fill effective type/purpose for interface-generated ledger rows in place.

    Stored values stay untouched (``stored_device_type``/``stored_purpose``);
    ``classification_inferred`` tells the UI the value is a derived suggestion.
    """
    stored_type = str(item.get('device_type') or '')
    stored_purpose = str(item.get('stored_purpose') or '')
    if stored_type not in ('', 'interface') and stored_purpose:
        return
    prefix_length = None
    ip_version = None
    try:
        network = ipaddress.ip_network(str(item.get('subnet_prefix') or ''), strict=False)
        prefix_length, ip_version = network.prefixlen, network.version
    except ValueError:
        pass
    inferred = False
    kind = _classify_interface_address_kind(item.get('interface_name') or '', prefix_length, ip_version)
    if stored_type in ('', 'interface') and kind != 'interface' and str(item.get('interface_name') or ''):
        item['device_type'] = kind
        inferred = True
    if not stored_purpose:
        address = str(item.get('address') or '')
        management_ips = {
            str(item.get('bound_device_ip') or '').split('/')[0].strip(),
            str(item.get('asset_management_ip') or '').split('/')[0].strip(),
        } - {''}
        network_purpose = _infer_ip_purpose(item.get('network_type'))
        if (address and address in management_ips) or _is_management_interface_name(item.get('interface_name') or ''):
            item['purpose'] = 'management'
            inferred = True
        elif network_purpose != 'other':
            item['purpose'] = network_purpose
        elif kind in _INTERFACE_KIND_PURPOSE:
            item['purpose'] = _INTERFACE_KIND_PURPOSE[kind]
            inferred = True
        elif prefix_length is not None and (
            (ip_version != 6 and prefix_length in (30, 31)) or (ip_version == 6 and prefix_length in (126, 127))
        ):
            item['purpose'] = 'transit'
            inferred = True
    item['classification_inferred'] = inferred


def _normalized_mac(value) -> str:
    digits = ''.join(ch for ch in str(value or '').lower() if ch in '0123456789abcdef')
    if len(digits) != 12 or digits in ('000000000000', 'ffffffffffff'):
        return ''
    return digits


def _ipam_address_space_facts(conn) -> dict:
    """Load the narrow, authoritative IP-to-address-space evidence used by reads.

    Current ARP/ND observations already carry address-space resolution from
    ``list_current_endpoint_observations``. This catalog is only a compatibility
    bridge for the older ``network_endpoints`` cache, whose VRF label and
    device/site identity must agree with a unique registered address before it
    can be assigned to a domain.
    """
    def load() -> dict:
        facts = {
            'spaces': {}, 'addresses': {}, 'vrf_aliases': {},
            'sites': {}, 'site_tenants': {},
        }
        try:
            for row in conn.execute(
                "SELECT id, site_name, site_code, tenant_id FROM sites"
            ).fetchall():
                site_id = str(row['id'] or '')
                if not site_id:
                    continue
                facts['sites'][site_id] = {
                    'id': site_id,
                    'name': row['site_name'] or row['site_code'] or '未命名站点',
                    'code': row['site_code'] or '',
                }
                facts['site_tenants'][site_id] = str(row['tenant_id'] or 'tenant-default')

            for row in conn.execute(
                """SELECT id, kind, vrf_id, security_tenant_id
                     FROM ipam_address_spaces WHERE status = 'active'"""
            ).fetchall():
                space_id = str(row['id'] or '')
                if space_id:
                    facts['spaces'][space_id] = {
                        'kind': str(row['kind'] or '').strip().lower(),
                        'vrf_id': str(row['vrf_id'] or ''),
                        'tenant_id': str(row['security_tenant_id'] or 'tenant-default'),
                    }

            for row in conn.execute(
                """SELECT vrf.id, vrf.vrf_name,
                          COALESCE(NULLIF(vrf.tenant_id, ''), 'tenant-default') AS tenant_id
                     FROM vrfs vrf"""
            ).fetchall():
                vrf_id = str(row['id'] or '')
                tenant_id = str(row['tenant_id'] or 'tenant-default')
                for alias in (vrf_id, str(row['vrf_name'] or '')):
                    normalized_alias = alias.strip().casefold()
                    if normalized_alias:
                        facts['vrf_aliases'].setdefault((tenant_id, normalized_alias), set()).add(vrf_id)

            rows = conn.execute(
                """SELECT COALESCE(NULLIF(p.tenant_id, ''), NULLIF(ip.tenant_id, ''), 'tenant-default') AS tenant_id,
                          COALESCE(p.site_id, '') AS site_id,
                          COALESCE(NULLIF(p.address_space_id, ''), NULLIF(ip.address_space_id, '')) AS address_space_id,
                          COALESCE(host(ip.address_inet), ip.address) AS address
                     FROM ip_addresses ip
                     LEFT JOIN prefixes p ON p.id = ip.subnet_id
                    WHERE COALESCE(ip.status, 'active') NOT IN ('released', 'available')
                      AND COALESCE(p.status, 'active') = 'active'"""
            ).fetchall()
            for row in rows:
                address = _canonical_host_ip(row['address'])
                tenant_id = str(row['tenant_id'] or 'tenant-default')
                site_id = str(row['site_id'] or '')
                space_id = str(row['address_space_id'] or '')
                space = facts['spaces'].get(space_id)
                if address and site_id and space_id and space and space['tenant_id'] == tenant_id:
                    facts['addresses'].setdefault((tenant_id, site_id, address), set()).add(space_id)

            for row in conn.execute(
                """SELECT p.tenant_id, p.site_id, p.gateway, p.address_space_id
                     FROM prefixes p
                     JOIN ipam_address_spaces space ON space.id = p.address_space_id
                    WHERE p.status = 'active' AND space.status = 'active'
                      AND COALESCE(p.gateway, '') <> ''"""
            ).fetchall():
                address = _canonical_host_ip(row['gateway'])
                tenant_id = str(row['tenant_id'] or 'tenant-default')
                site_id = str(row['site_id'] or '')
                space_id = str(row['address_space_id'] or '')
                space = facts['spaces'].get(space_id)
                if address and site_id and space_id and space and space['tenant_id'] == tenant_id:
                    facts['addresses'].setdefault((tenant_id, site_id, address), set()).add(space_id)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return {
                'spaces': {}, 'addresses': {}, 'vrf_aliases': {},
                'sites': {}, 'site_tenants': {},
            }
        return facts
    return _scoped_read(conn, ('ipam_address_space_facts',), load)


def _canonical_host_ip(value) -> str:
    try:
        return str(ipaddress.ip_address(str(value or '').strip()))
    except ValueError:
        return ''


def _legacy_endpoint_address_space(
    *, ip_address: str, tenant_id: str, site_id: str, vrf_label: str, facts: dict,
) -> str:
    """Resolve a legacy endpoint only with a known context and one IP match."""
    address = _canonical_host_ip(ip_address)
    tenant = str(tenant_id or 'tenant-default')
    site = str(site_id or '')
    context = str(vrf_label or '').strip().casefold()
    if not (address and site and context):
        return ''

    if context in {'global', 'global routing table', 'global/default'}:
        expected_kind = 'global'
        expected_vrf_id = ''
    else:
        vrf_ids = facts.get('vrf_aliases', {}).get((tenant, context), set())
        if len(vrf_ids) != 1:
            return ''
        expected_kind = 'vrf'
        expected_vrf_id = next(iter(vrf_ids))

    candidates = facts.get('addresses', {}).get((tenant, site, address), set())
    matching = {
        space_id for space_id in candidates
        if facts.get('spaces', {}).get(space_id, {}).get('kind') == expected_kind
        and (
            expected_kind == 'global'
            or facts.get('spaces', {}).get(space_id, {}).get('vrf_id') == expected_vrf_id
        )
    }
    return next(iter(matching)) if len(matching) == 1 else ''


def _current_observation_scope(observation: dict, facts: dict) -> tuple[str, str, str] | None:
    """Return tenant/site/address-space only when the canonical mapping resolved."""
    site_id = endpoint_site_id({
        'cmdb_device_id': observation.get('source_device_id'),
        'asset_site_id': observation.get('asset_site_id'),
        'device_site_id': observation.get('device_site_id'),
        'device_site': observation.get('device_site'),
    }, facts.get('sites', {}))
    tenant_id = str(
        observation.get('tenant_id')
        or facts.get('site_tenants', {}).get(site_id)
        or 'tenant-default'
    )
    space_id = str(observation.get('address_space_id') or '')
    if not site_id or not space_id:
        return None
    space = facts.get('spaces', {}).get(space_id)
    if not space or space.get('tenant_id') != tenant_id:
        return None
    return tenant_id, site_id, space_id


def _legacy_endpoint_scope(endpoint: dict, facts: dict) -> tuple[str, str, str] | None:
    """Resolve a historical cache row only if its context and IP scope agree."""
    source_device_id = str(endpoint.get('switch_id') or endpoint.get('cmdb_device_id') or '')
    site_id = endpoint_site_id({
        'cmdb_device_id': source_device_id,
        'asset_site_id': endpoint.get('asset_site_id'),
        'device_site_id': endpoint.get('device_site_id'),
        'device_site': endpoint.get('device_site'),
        'site': endpoint.get('site'),
    }, facts.get('sites', {}))
    tenant_id = str(
        endpoint.get('device_tenant_id')
        or facts.get('site_tenants', {}).get(site_id)
        or 'tenant-default'
    )
    space_id = _legacy_endpoint_address_space(
        ip_address=endpoint.get('ip'), tenant_id=tenant_id, site_id=site_id,
        vrf_label=endpoint.get('vrf'), facts=facts,
    )
    if not (site_id and space_id):
        return None
    return tenant_id, site_id, space_id


def _cmdb_device_scope(conn, device_id: str, facts: dict | None = None) -> tuple[str, str] | None:
    normalized_id = str(device_id or '').strip()
    if not normalized_id:
        return None
    row = _scoped_read(
        conn, ('cmdb_device_scope', normalized_id),
        lambda: conn.execute(
            """SELECT d.tenant_id, d.site_id AS device_site_id, d.site AS device_site,
                      pa.site_id AS asset_site_id
                 FROM devices d LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                WHERE d.id = ?""",
            (normalized_id,),
        ).fetchone(),
    )
    if not row:
        return None
    address_facts = facts or _ipam_address_space_facts(conn)
    site_id = endpoint_site_id({
        'cmdb_device_id': normalized_id,
        'asset_site_id': row['asset_site_id'],
        'device_site_id': row['device_site_id'],
        'device_site': row['device_site'],
    }, address_facts.get('sites', {}))
    tenant_id = str(
        row['tenant_id'] or address_facts.get('site_tenants', {}).get(site_id) or 'tenant-default'
    )
    return tenant_id, site_id


def _interface_mac_sources(conn) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str, str, str], set[str]]]:
    """Read-only MAC evidence for device-owned interface addresses.

    * ``by_interface``: IF-MIB ``ifPhysAddress`` already stored in ``interfaces``
      (SNMP interface inventory), keyed by (device_id, normalized interface name).
    * ``by_scope_ip``: MACs for the exact tenant/site/address-space/IP observed
      in current ARP/ND, plus legacy rows whose known context maps uniquely.

    Both are observations; callers expose them separately from the ledger's
    stored ``mac_address`` and never write them back.
    """
    def load():
        by_interface: dict[tuple[str, str], str] = {}
        by_scope_ip: dict[tuple[str, str, str, str], set[str]] = {}
        facts = _ipam_address_space_facts(conn)
        try:
            for row in conn.execute(
                "SELECT device_id, interface_name, mac_address FROM interfaces "
                "WHERE COALESCE(mac_address, '') <> ''"
            ).fetchall():
                mac = _normalized_mac(row['mac_address'])
                key = normalize_interface_name(str(row['interface_name'] or ''))
                if mac and key:
                    by_interface[(str(row['device_id'] or ''), key)] = mac
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            observations = _current_address_observations(conn)
            for observation in observations:
                mac = _normalized_mac(observation.get('mac_address'))
                try:
                    ip = str(ipaddress.ip_address(str(observation.get('ip_address') or '').strip()))
                except ValueError:
                    continue
                scope = _current_observation_scope(observation, facts)
                if mac and scope:
                    by_scope_ip.setdefault((*scope, ip), set()).add(mac)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            rows = conn.execute(
                """SELECT ne.ip, ne.mac, ne.vrf, ne.site, ne.switch_id,
                          d.site_id AS device_site_id, d.site AS device_site,
                          d.tenant_id AS device_tenant_id, pa.site_id AS asset_site_id
                     FROM network_endpoints ne
                     LEFT JOIN devices d ON d.id = ne.switch_id
                     LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                    WHERE ne.is_active = 1 AND COALESCE(ne.ip, '') <> ''"""
            ).fetchall()
            for row in rows:
                endpoint = dict(row)
                mac = _normalized_mac(endpoint.get('mac'))
                ip = _canonical_host_ip(endpoint.get('ip'))
                scope = _legacy_endpoint_scope(endpoint, facts)
                if mac and ip and scope:
                    by_scope_ip.setdefault((*scope, ip), set()).add(mac)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        return by_interface, by_scope_ip
    return _scoped_read(conn, ('interface_mac_sources',), load)


def _attach_interface_mac(
    conn, item: dict, *, visible_scopes: set[tuple[str, str]] | None = None,
) -> None:
    """Expose an observed interface MAC for a registered address without storing it."""
    if _normalized_mac(item.get('mac_address')):
        return
    facts = _ipam_address_space_facts(conn)
    tenant_id = str(item.get('prefix_tenant_id') or item.get('tenant_id') or 'tenant-default')
    site_id = str(
        item.get('_security_site_id') or item.get('prefix_site_id') or item.get('site_id') or ''
    )
    target_scope = (tenant_id, site_id)
    if visible_scopes is not None and target_scope not in visible_scopes:
        return
    device_id = str(item.get('device_id') or '')
    if visible_scopes is not None and device_id:
        device_scope = _cmdb_device_scope(conn, device_id, facts)
        if device_scope is None or device_scope not in visible_scopes:
            return
    by_interface, by_scope_ip = _interface_mac_sources(conn)
    interface_key = normalize_interface_name(str(item.get('interface_name') or ''))
    mac = by_interface.get((device_id, interface_key)) if device_id and interface_key else None
    if mac:
        item['interface_mac'] = mac
        item['interface_mac_source'] = 'snmp_ifmib'
        return
    try:
        address = str(ipaddress.ip_address(str(item.get('address') or '').strip()))
    except ValueError:
        return
    address_space_id = str(item.get('prefix_address_space_id') or item.get('address_space_id') or '')
    if not (tenant_id and site_id and address_space_id):
        return
    candidates = by_scope_ip.get((tenant_id, site_id, address_space_id, address)) or set()
    if len(candidates) == 1:
        item['interface_mac'] = next(iter(candidates))
        item['interface_mac_source'] = 'neighbor_arp'
    elif len(candidates) > 1:
        # Several MACs answer for one IP: surface the ambiguity, pick none.
        item['interface_mac_conflict'] = sorted(candidates)


def _discovery_freshness(source_type, observed_at) -> dict:
    """Classify a discovery timestamp with the same window as Discovered Endpoints.

    ``network_endpoints.is_active`` only says the row was not explicitly
    retired; it stays 1 after collection stops. Freshness is therefore judged
    by age: ARP/ND records are current within two ARP sweep intervals plus
    jitter (IPAM_DISCOVERY_RECENT_MINUTES), MAC-table records within the
    endpoint-fact window (IPAM_DISCOVERY_MAC_RECENT_MINUTES).
    """
    from services.ipam_discovery_service import _mac_recent_minutes, _parse_time, _recent_minutes

    kind = str(source_type or '').strip().lower()
    window = _mac_recent_minutes() if kind in ('mac', 'fdb', 'mac_table') else _recent_minutes()
    parsed, status = _parse_time(observed_at)
    if parsed is None or status not in ('valid', 'future'):
        return {'freshness': 'unknown', 'age_minutes': None, 'window_minutes': window}
    age_minutes = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds() // 60))
    return {
        'freshness': 'recent' if age_minutes <= window else 'historical',
        'age_minutes': age_minutes,
        'window_minutes': window,
    }


def _interface_fresh_minutes() -> int:
    """How long an interface state observation counts as current.

    Interface collection is not on a short background schedule (CLI snapshots
    come from the CMDB "collect interfaces" job or NSOT refresh, SNMP from
    on-demand refreshes), so the default window is one day. Override with
    IPAM_INTERFACE_FRESH_MINUTES.
    """
    import os
    try:
        return min(max(int(os.getenv('IPAM_INTERFACE_FRESH_MINUTES', '1440')), 5), 43200)
    except ValueError:
        return 1440


def _interface_state_sources(conn) -> dict[tuple[str, str], dict]:
    """Latest known admin/oper state per (device_id, normalized interface name).

    Merges shared interface rows only when their dedicated state timestamp and
    source certify the admin/oper pair, then compares them with the latest
    successful CMDB CLI interface snapshot and keeps the newer observation.
    """
    from services.ipam_discovery_service import _parse_time

    def load() -> dict[tuple[str, str], dict]:
        states: dict[tuple[str, str], dict] = {}

        def offer(device_id, name, admin, oper, observed_at, source):
            key = (str(device_id or ''), normalize_interface_name(str(name or '')).strip().lower())
            if not key[0] or not key[1]:
                return
            parsed, status = _parse_time(observed_at)
            if parsed is None or status not in ('valid', 'future'):
                parsed = None
            current = states.get(key)
            if current and current.get('_parsed') and (parsed is None or parsed <= current['_parsed']):
                return
            states[key] = {
                'admin_status': str(admin or 'unknown').lower(),
                'oper_status': str(oper or 'unknown').lower(),
                'observed_at': str(observed_at or ''),
                'source': source,
                '_parsed': parsed,
            }

        for sql, source in (
            (
                "SELECT device_id, interface_name, "
                "certified_admin_status AS admin_status, certified_oper_status AS oper_status, "
                "status_observed_at AS observed_at, status_observation_source AS state_source "
                "FROM interfaces WHERE status_observed_at IS NOT NULL "
                "AND status_observation_source IN ('snmp', 'cli_snapshot') "
                "AND certified_admin_status IS NOT NULL AND certified_oper_status IS NOT NULL",
                'snmp',
            ),
            (
                """SELECT o.device_id, o.interface_name, o.admin_status, o.oper_status, o.observed_at
                     FROM cmdb_device_interface_observations o
                     JOIN cmdb_collection_snapshots snap
                       ON snap.device_id = o.device_id
                      AND snap.domain = 'interface_inventory'
                      AND snap.successful_generation = o.generation""",
                'cli_snapshot',
            ),
        ):
            try:
                rows = conn.execute(sql).fetchall()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                continue
            for row in rows:
                offer(row['device_id'], row['interface_name'], row['admin_status'],
                      row['oper_status'], row['observed_at'], row.get('state_source') or source)
        return states
    return _scoped_read(conn, ('interface_state_sources',), load)


def _interface_liveness(conn, item: dict) -> dict | None:
    """Liveness of a device-owned (infrastructure) address from its interface.

    Loopback and point-to-point addresses never or rarely appear in ARP tables,
    so the owning interface's state is the right evidence for them. Returns
    None when the address is not bound to a device interface.
    """
    device_id = str(item.get('device_id') or '')
    interface_name = str(item.get('interface_name') or '')
    if not device_id or not interface_name:
        return None
    key = (device_id, normalize_interface_name(interface_name).strip().lower())
    state = _interface_state_sources(conn).get(key)
    window = _interface_fresh_minutes()
    if not state:
        return {'state': 'unknown', 'freshness': 'unknown', 'window_minutes': window,
                'admin_status': '', 'oper_status': '', 'observed_at': '', 'source': '', 'alive': False}
    parsed = state.get('_parsed')
    age_minutes = None
    freshness = 'unknown'
    if parsed is not None:
        age_minutes = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds() // 60))
        freshness = 'recent' if age_minutes <= window else 'historical'
    admin, oper = state['admin_status'], state['oper_status']
    if admin == 'down':
        condition = 'admin_down'
    elif oper == 'up':
        condition = 'up'
    elif oper == 'down':
        condition = 'down'
    else:
        condition = 'unknown'
    return {
        'state': condition,
        'admin_status': admin,
        'oper_status': oper,
        'observed_at': state['observed_at'],
        'source': state['source'],
        'age_minutes': age_minutes,
        'window_minutes': window,
        'freshness': freshness,
        'alive': condition == 'up' and freshness == 'recent',
    }


def _current_address_observations(conn) -> list[dict]:
    """Current ARP/ND observation rows (refreshed every sweep), cached per read scope."""
    def load() -> list[dict]:
        try:
            from services.ipam_current_endpoint_observation_service import list_current_endpoint_observations
            return [
                *list_current_endpoint_observations(conn, observation_source="arp"),
                *list_current_endpoint_observations(conn, observation_source="ndp"),
            ]
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return []
    return _scoped_read(conn, ('current_arp_ndp_observations',), load)


def _recent_endpoint_ips(conn) -> dict[tuple[str, str, str], frozenset[str]]:
    """Fresh ARP/ND hosts keyed by tenant, site, and resolved address space."""
    def load() -> dict[tuple[str, str, str], frozenset[str]]:
        recent: dict[tuple[str, str, str], set[str]] = {}
        facts = _ipam_address_space_facts(conn)
        try:
            rows = conn.execute(
                """SELECT ne.ip, ne.vrf, ne.site, ne.source_type, ne.last_seen, ne.switch_id,
                          d.site_id AS device_site_id, d.site AS device_site,
                          d.tenant_id AS device_tenant_id, pa.site_id AS asset_site_id
                     FROM network_endpoints ne
                     LEFT JOIN devices d ON d.id = ne.switch_id
                     LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                    WHERE ne.is_active = 1 AND COALESCE(ne.ip, '') <> ''"""
            ).fetchall()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            rows = []
        for row in rows:
            if _discovery_freshness(row['source_type'], row['last_seen'])['freshness'] != 'recent':
                continue
            endpoint = dict(row)
            scope = _legacy_endpoint_scope(endpoint, facts)
            address = _canonical_host_ip(endpoint.get('ip'))
            if not (scope and address):
                continue
            recent.setdefault(scope, set()).add(address)

        # Current observations use the canonical routing-context resolver.
        # An unresolved context remains pending even if a bare IP happens to
        # match exactly one IPAM row in this site.
        for observation in _current_address_observations(conn):
            if _discovery_freshness(observation.get('observation_source') or 'arp', observation.get('observed_at'))['freshness'] != 'recent':
                continue
            scope = _current_observation_scope(observation, facts)
            address = _canonical_host_ip(observation.get('ip_address'))
            if not (scope and address):
                continue
            recent.setdefault(scope, set()).add(address)
        return {scope: frozenset(addresses) for scope, addresses in recent.items()}
    return _scoped_read(conn, ('recent_endpoint_ips_by_scope',), load)


def _loopback_prefix_length(interface_name: str, ip_obj: ipaddress._BaseAddress) -> Optional[int]:
    """Use a host prefix only when the interface is explicitly a loopback."""
    if _is_loopback_interface_name(interface_name):
        return 32 if ip_obj.version == 4 else 128
    return None


def _interface_prefix_candidate_id(
    prefix: str,
    tenant_id: str,
    site_id: str,
    *,
    address_space_id: str = '',
    pending_scope_key: str = '',
) -> str:
    scope_identity = (
        ('space', str(address_space_id))
        if address_space_id
        else ('pending', str(tenant_id or 'tenant-default'), str(site_id or ''), str(pending_scope_key))
    )
    digest = hashlib.sha256(
        json.dumps([prefix, *scope_identity], ensure_ascii=True, separators=(',', ':')).encode()
    ).hexdigest()[:24]
    return f'{prefix}|{digest}'


def _registered_interface_scope_matches(conn, source_refs: set[str]) -> dict[str, list[dict]]:
    """Load active, explicitly registered interface IP provenance by source_ref.

    A matching ledger row can resolve the address space for that single
    observation. It never creates or implies a device routing-context mapping.
    """
    normalized_refs = sorted({str(value or '').strip() for value in source_refs if str(value or '').strip()})
    if not normalized_refs:
        return {}

    matches: dict[str, list[dict]] = {}
    # Keep each query bounded for imports with many current interfaces.
    for start in range(0, len(normalized_refs), 500):
        ref_chunk = normalized_refs[start:start + 500]
        placeholders = ', '.join(_PH for _ in ref_chunk)
        rows = conn.execute(
            f'''SELECT ip.source_ref, ip.device_id, ip.interface_name,
                       COALESCE(host(ip.address_inet), ip.address) AS address,
                       p.id AS prefix_id, p.prefix_cidr, p.tenant_id, p.site_id,
                       p.vrf_id, p.address_space_id,
                       space.security_tenant_id, space.vrf_id AS space_vrf_id
                  FROM ip_addresses ip
                  JOIN prefixes p ON p.id = ip.subnet_id
                  JOIN ipam_address_spaces space ON space.id = p.address_space_id
                 WHERE ip.source_type = 'interface_collection'
                   AND COALESCE(ip.status, 'active') = 'active'
                   AND p.status = 'active'
                   AND space.status = 'active'
                   AND ip.source_ref IN ({placeholders})''',
            tuple(ref_chunk),
        ).fetchall()
        for row in rows:
            source_ref = str(row['source_ref'] or '').strip()
            if source_ref:
                matches.setdefault(source_ref, []).append(dict(row))
    return matches


def _load_interface_prefix_candidates(
    conn,
    *,
    include_all_interfaces: bool = False,
    skipped_sample_limit: int = 25,
) -> dict:
    """Build IPAM candidates from the current L3 interface collection.

    Current devices use their last successful CMDB CLI snapshot. Legacy devices
    without a successful snapshot continue to use ``interfaces``. CMDB snapshots
    do not assert a VRF; an operator must choose a VRF (including explicit global)
    before a new prefix can be generated from an otherwise unscoped observation.
    """
    legacy_interface_rows = [dict(row) for row in conn.execute(
        '''SELECT i.id, i.device_id, i.interface_name, i.primary_ip, i.ip_address,
                  i.ip_prefix_length, i.ip_version, i.is_l3, i.ip_enabled,
                  i.vrf_id, i.last_seen, d.hostname, d.ip_address AS device_ip,
                  d.site_id, d.tenant_id, d.platform, d.device_type_id
           FROM interfaces i
           JOIN devices d ON d.id = i.device_id
            WHERE (COALESCE(i.is_l3, FALSE) = TRUE OR COALESCE(i.ip_enabled, 0) = 1)
             AND (COALESCE(i.primary_ip, '') <> '' OR COALESCE(i.ip_address, '') <> '')
            ORDER BY d.hostname, i.interface_name'''
    ).fetchall()]
    active_vrf_spaces = {
        (str(row['security_tenant_id']), str(row['vrf_id'])): str(row['id'])
        for row in conn.execute(
            """SELECT id, security_tenant_id, vrf_id
                 FROM ipam_address_spaces
                WHERE kind = 'vrf' AND status = 'active' AND vrf_id IS NOT NULL"""
        ).fetchall()
    }
    for row in legacy_interface_rows:
        row_tenant = str(row.get('tenant_id') or 'tenant-default')
        local_vrf_id = str(row.get('vrf_id') or '').strip()
        mapped_space_id = active_vrf_spaces.get((row_tenant, local_vrf_id)) if local_vrf_id else None
        row.update({
            'address_space_id': mapped_space_id or '',
            'mapped_vrf_id': local_vrf_id if mapped_space_id else '',
            '_context_source': 'legacy_interface',
            '_context_type': 'vrf' if local_vrf_id else 'unknown',
            '_local_context_key': local_vrf_id,
            '_scope_pending_key': f"legacy:{row.get('device_id')}:{local_vrf_id}",
            '_vrf_unknown': not bool(mapped_space_id),
        })

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
        # Older installations may not have the optional legacy IP mask table.
        try:
            conn.rollback()
        except Exception:
            pass

    snapshot_observations: list[dict] = []
    snapshot_device_ids: set[str] = set()
    try:
        snapshot_device_ids = {
            str(row['device_id'])
            for row in conn.execute(
                """SELECT device_id FROM cmdb_collection_snapshots
                   WHERE domain = 'interface_inventory' AND successful_generation > 0"""
            ).fetchall()
        }
        snapshot_observations = _current_cmdb_interface_ip_observations(conn)
    except Exception:
        # Older installations may not have the isolated CMDB snapshot tables.
        try:
            conn.rollback()
        except Exception:
            pass
        snapshot_device_ids = set()
        snapshot_observations = []

    interface_rows: list[dict] = []
    _, site_catalog, _ = load_inventory_catalog(conn)
    for observation in snapshot_observations:
        owner = {
            'cmdb_device_id': observation.get('device_id'),
            'asset_site_id': observation.get('asset_site_id'),
            'device_site_id': observation.get('device_site_id'),
            'device_site': observation.get('device_site'),
        }
        interface_rows.append({
            'id': None,
            '_source_ref': (
                f"cmdb-interface:{observation.get('device_id')}:{observation.get('normalized_interface_name')}:"
                f"{observation.get('context_source')}:{observation.get('context_type')}:"
                f"{observation.get('local_context_key')}:{observation.get('ip_address')}"
            ),
            'device_id': observation.get('device_id'),
            'interface_name': observation.get('interface_name'),
            'primary_ip': observation.get('ip_address'),
            'ip_address': observation.get('ip_address'),
            'ip_prefix_length': observation.get('ip_prefix_length'),
            'ip_version': None,
            'is_l3': True,
            'ip_enabled': True,
            'vrf_id': observation.get('mapped_vrf_id'),
            'address_space_id': observation.get('address_space_id') or '',
            'mapped_vrf_id': observation.get('mapped_vrf_id') or '',
            '_context_source': observation.get('context_source') or '',
            '_context_type': observation.get('context_type') or 'unknown',
            '_local_context_key': observation.get('local_context_key') or '',
            '_scope_pending_key': (
                f"{observation.get('device_id')}:{observation.get('context_source')}:"
                f"{observation.get('context_type')}:{observation.get('local_context_key')}"
            ),
            '_vrf_unknown': not bool(observation.get('address_space_id')),
            'last_seen': observation.get('observed_at'),
            'hostname': observation.get('device_hostname'),
            'device_ip': observation.get('device_ip'),
            'site_id': endpoint_site_id(owner, site_catalog),
            'tenant_id': observation.get('tenant_id') or 'tenant-default',
            'platform': '',
            'device_type_id': '',
        })
    interface_rows.extend(
        dict(row) for row in legacy_interface_rows
        if str(row.get('device_id') or '') not in snapshot_device_ids
    )
    existing_rows = conn.execute(
        'SELECT id, prefix, tenant_id, site_id, vrf_id, address_space_id, name FROM prefixes'
    ).fetchall()
    existing_by_scope = {
        (str(row['address_space_id'] or ''), str(row['prefix'] or '')): dict(row)
        for row in existing_rows if row['address_space_id']
    }
    registered_scope_matches = _registered_interface_scope_matches(
        conn,
        {
            str(row.get('_source_ref') or row.get('id') or '').strip()
            for row in interface_rows
        },
    )

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
        address_space_id = str(row.get('address_space_id') or '')
        vrf_id = str(row.get('mapped_vrf_id') or '')
        scope_resolution_source = ''
        if not address_space_id:
            source_ref = str(row.get('_source_ref') or row.get('id') or '').strip()
            observation_matches = []
            for match in registered_scope_matches.get(source_ref, []):
                try:
                    registered_address = str(ipaddress.ip_address(str(match.get('address') or '').strip()))
                except ValueError:
                    continue
                if (
                    str(match.get('device_id') or '') == str(row.get('device_id') or '')
                    and normalize_interface_name(str(match.get('interface_name') or ''))
                    == normalize_interface_name(str(row.get('interface_name') or ''))
                    and registered_address == str(ip_obj)
                    and str(match.get('prefix_cidr') or match.get('prefix') or '') == prefix
                    and str(match.get('tenant_id') or 'tenant-default') == tenant_id
                    and str(match.get('security_tenant_id') or '') == tenant_id
                    and str(match.get('site_id') or '') == site_id
                    and str(match.get('address_space_id') or '')
                ):
                    observation_matches.append(match)
            distinct_scope_matches = {
                (
                    str(match.get('address_space_id') or ''),
                    str(match.get('prefix_id') or ''),
                    str(match.get('vrf_id') or match.get('space_vrf_id') or ''),
                ): match
                for match in observation_matches
            }
            if len(distinct_scope_matches) == 1:
                matched_scope = next(iter(distinct_scope_matches.values()))
                address_space_id = str(matched_scope.get('address_space_id') or '')
                vrf_id = str(matched_scope.get('vrf_id') or matched_scope.get('space_vrf_id') or '')
                scope_resolution_source = 'registered_interface_ip'
        vrf_unknown = not bool(address_space_id)
        vrf_defaulted = False
        candidate_id = _interface_prefix_candidate_id(
            prefix,
            tenant_id,
            site_id,
            address_space_id=address_space_id,
            pending_scope_key=str(row.get('_scope_pending_key') or row.get('device_id') or ''),
        )
        existing_prefix = existing_by_scope.get((address_space_id, prefix)) if address_space_id else None
        item = candidates.setdefault(candidate_id, {
            'candidate_id': candidate_id,
            'prefix': prefix,
            'tenant_id': tenant_id,
            'site_id': site_id or None,
            'address_space_id': address_space_id or None,
            'vrf_id': None if vrf_unknown else vrf_id or None,
            'status': 'scope_pending' if vrf_unknown else 'existing' if existing_prefix else 'to_create',
            'vrf_scope_pending': vrf_unknown,
            'vrf_scope_defaulted': vrf_defaulted,
            'scope_review_reason': '设备本地上下文未映射到明确地址空间' if vrf_unknown else '',
            '_scope_resolution_sources': set(),
            '_scope_resolution_observation_count': 0,
            '_observation_count': 0,
            'existing_prefix_id': (existing_prefix or {}).get('id'),
            'existing_prefix_name': (existing_prefix or {}).get('name') or '',
            'interface_count': 0,
            'ip_count': 0,
            'interfaces': [],
            '_interface_keys': set(),
            '_ip_keys': set(),
            '_site_ids': set(),
            '_search_values': set(),
        })
        item['_search_values'].update(
            str(value).strip()
            for value in (
                prefix,
                row.get('hostname'),
                row.get('device_ip'),
                row.get('interface_name'),
                address,
                tenant_id,
                site_id,
                site_catalog.get(site_id, {}).get('name'),
                site_catalog.get(site_id, {}).get('code'),
                address_space_id,
                vrf_id,
                row.get('_context_source'),
                row.get('_context_type'),
                row.get('_local_context_key'),
            )
            if value is not None and str(value).strip()
        )
        interface_identity = (
            str(row.get('device_id') or ''),
            normalize_interface_name(str(row.get('interface_name') or '')),
        )
        if interface_identity not in item['_interface_keys']:
            item['_interface_keys'].add(interface_identity)
            item['interface_count'] += 1
        if address not in item['_ip_keys']:
            item['_ip_keys'].add(address)
            item['ip_count'] += 1
        if site_id:
            item['_site_ids'].add(site_id)
            if len(item['_site_ids']) > 1 and not item.get('existing_prefix_id'):
                item['site_id'] = None
        item['_observation_count'] += 1
        if scope_resolution_source:
            item['_scope_resolution_sources'].add(scope_resolution_source)
            item['_scope_resolution_observation_count'] += 1
        if include_all_interfaces or len(item['interfaces']) < 3:
            item['interfaces'].append({
                'interface_id': row['id'],
                'source_ref': row.get('_source_ref') or str(row['id'] or ''),
                'device_id': row['device_id'],
                'device_name': row['hostname'],
                'device_ip': row['device_ip'],
                'interface_name': row['interface_name'],
                'address': address,
                'context_source': row.get('_context_source') or '',
                'context_type': row.get('_context_type') or 'unknown',
                'local_context_key': row.get('_local_context_key') or '',
                'address_space_id': address_space_id or None,
            })

    for item in candidates.values():
        item['_search_text'] = ' '.join(sorted(item.pop('_search_values', set()))).casefold()
        if (
            item['_scope_resolution_sources'] == {'registered_interface_ip'}
            and item['_scope_resolution_observation_count'] == item['_observation_count']
        ):
            item['scope_resolution_source'] = 'registered_interface_ip'
        item.pop('_scope_resolution_sources', None)
        item.pop('_scope_resolution_observation_count', None)
        item.pop('_observation_count', None)
        item.pop('_interface_keys', None)
        item.pop('_ip_keys', None)
        item.pop('_site_ids', None)
    result_candidates = sorted(
        candidates.values(),
        key=lambda item: (item['prefix'], item['tenant_id'], item['site_id'] or '', item['candidate_id']),
    )
    return {
        'source': 'cmdb_interface_snapshot',
        'source_label': '最后一次成功的接口快照',
        'interface_count': interface_count,
        'scope_pending_count': sum(1 for item in result_candidates if item['status'] == 'scope_pending'),
        'vrf_pending_count': sum(1 for item in result_candidates if item.get('vrf_scope_pending')),
        'vrf_defaulted_count': sum(1 for item in result_candidates if item.get('vrf_scope_defaulted')),
        'candidate_count': len(result_candidates),
        'existing_count': sum(1 for item in result_candidates if item['status'] == 'existing'),
        'to_create_count': sum(1 for item in result_candidates if item['status'] == 'to_create'),
        'skipped_count': skipped_count,
        'candidates': result_candidates,
        'skipped': skipped,
        'skipped_truncated_count': skipped_count - len(skipped),
    }


def preview_interface_prefixes(
    *, page: int = 1, page_size: int = 25, status: str = 'all', q: str = '',
    visible_scopes: set[tuple[str, str]] | None = None,
) -> dict:
    """Preview canonical prefixes that can be generated from current interfaces."""
    if page < 1:
        raise ValueError('page 必须大于等于 1')
    if page_size < 1 or page_size > 100:
        raise ValueError('page_size 必须在 1 到 100 之间')
    if status not in {'all', 'to_create', 'existing', 'scope_pending', 'global_default'}:
        raise ValueError('status 必须为 all、to_create、existing、scope_pending 或 global_default')
    search_query = ' '.join(str(q or '').split()).casefold()
    if len(search_query) > 120:
        raise ValueError('q 最多 120 个字符')

    conn = get_db_connection()
    try:
        preview = _load_interface_prefix_candidates(conn, skipped_sample_limit=25)
    finally:
        conn.close()

    if visible_scopes is not None:
        # Restricted viewers see only candidates with a single authorized
        # tenant/site owner. Skipped evidence has no reliable owner and stays
        # hidden so its samples and counts cannot reveal other sites.
        preview['candidates'] = [
            item for item in preview['candidates']
            if (
                str(item.get('tenant_id') or 'tenant-default'),
                str(item.get('site_id') or ''),
            ) in visible_scopes
        ]
        preview['candidate_count'] = len(preview['candidates'])
        preview['existing_count'] = sum(1 for item in preview['candidates'] if item['status'] == 'existing')
        preview['to_create_count'] = sum(1 for item in preview['candidates'] if item['status'] == 'to_create')
        preview['scope_pending_count'] = sum(1 for item in preview['candidates'] if item['status'] == 'scope_pending')
        preview['vrf_pending_count'] = sum(1 for item in preview['candidates'] if item.get('vrf_scope_pending'))
        preview['vrf_defaulted_count'] = sum(1 for item in preview['candidates'] if item.get('vrf_scope_defaulted'))
        preview['interface_count'] = sum(int(item.get('interface_count') or 0) for item in preview['candidates'])
        preview['skipped_count'] = 0
        preview['skipped'] = []
        preview['skipped_truncated_count'] = 0

    filtered_candidates = []
    for item in preview['candidates']:
        matches_status = status == 'all' or (status != 'global_default' and item['status'] == status)
        matches_query = not search_query or search_query in str(item.get('_search_text') or '').casefold()
        if matches_status and matches_query:
            filtered_candidates.append(item)
    filtered_count = len(filtered_candidates)
    start = (page - 1) * page_size
    total_pages = (filtered_count + page_size - 1) // page_size
    for item in preview['candidates']:
        item.pop('_search_text', None)
    return {
        'source': preview['source'],
        'source_label': preview['source_label'],
        'candidate_count': preview['candidate_count'],
        'existing_count': preview['existing_count'],
        'to_create_count': preview['to_create_count'],
        'interface_count': preview['interface_count'],
        'scope_pending_count': preview['scope_pending_count'],
        'vrf_pending_count': preview['vrf_pending_count'],
        'vrf_defaulted_count': preview['vrf_defaulted_count'],
        'skipped_count': preview['skipped_count'],
        'page': page,
        'page_size': page_size,
        'filtered_count': filtered_count,
        'total_pages': total_pages,
        'candidates': filtered_candidates[start:start + page_size],
        'skipped': preview['skipped'],
        'skipped_truncated_count': preview['skipped_truncated_count'],
    }


def preview_interface_prefix_import(
    candidate_ids: list[str],
    *,
    address_space_overrides: dict[str, str] | None = None,
    allowed_scopes: set[tuple[str, str]] | None = None,
) -> dict:
    """Read-only preview of the exact selected interface import targets.

    Original loader candidate IDs remain the source identities. Candidates are
    merged only after they resolve to the same tenant, explicit address space,
    and canonical CIDR. Unresolved candidates retain isolated pending groups.
    """
    requested_ids = sorted({str(value or '').strip() for value in candidate_ids if str(value or '').strip()})
    if not requested_ids:
        raise ValueError('candidate_ids 不能为空')

    overrides: dict[str, str] = {}
    for raw_key, raw_value in (address_space_overrides or {}).items():
        key = str(raw_key or '').strip()
        value = str(raw_value or '').strip()
        if not key or not value:
            raise ValueError('地址空间覆盖必须包含候选 ID 和地址空间 ID')
        overrides[key] = value
    if set(overrides) - set(requested_ids):
        raise ValueError('地址空间覆盖只能用于本次选择的候选')

    conn = get_db_connection()
    try:
        loaded = _load_interface_prefix_candidates(conn, include_all_interfaces=True)
        by_id = {
            str(candidate.get('candidate_id') or ''): candidate
            for candidate in loaded['candidates']
        }
        selected: list[dict] = []
        for candidate_id in requested_ids:
            candidate = by_id.get(candidate_id)
            if candidate is None:
                raise LookupError('候选不存在或无权访问，请刷新预览')
            owner_scope = (
                str(candidate.get('tenant_id') or 'tenant-default'),
                str(candidate.get('site_id') or ''),
            )
            if allowed_scopes is not None and owner_scope not in allowed_scopes:
                raise LookupError('候选不存在或无权访问，请刷新预览')
            selected.append(candidate)

        selected_by_id = {
            str(candidate.get('candidate_id') or ''): candidate
            for candidate in selected
        }
        for candidate_id in overrides:
            candidate = selected_by_id[candidate_id]
            if candidate.get('address_space_id'):
                raise ValueError('地址空间覆盖只能用于归属待确认的候选')

        resolved_candidates: list[dict] = []
        for source in selected:
            candidate = dict(source)
            candidate_id = str(candidate.get('candidate_id') or '')
            tenant_id = str(candidate.get('tenant_id') or 'tenant-default')
            selected_space_id = overrides.get(candidate_id)
            known_vrf_ids = {
                str(candidate.get('vrf_id') or '').strip(),
                *{
                    str(item.get('local_context_key') or '').strip()
                    for item in (candidate.get('interfaces') or [])
                    if str(item.get('context_type') or '').strip().casefold() == 'vrf'
                },
            }
            known_vrf_ids.discard('')

            if selected_space_id:
                address_space = _get_address_space(conn, selected_space_id, tenant_id)
                if not address_space or str(address_space.get('status') or '') != 'active':
                    raise ValueError('地址空间无效、未启用或与候选租户不匹配')
                target_vrf_id = str(address_space.get('vrf_id') or '').strip()
                if known_vrf_ids and (not target_vrf_id or known_vrf_ids != {target_vrf_id}):
                    raise ValueError('所选地址空间与接口已知 VRF 不兼容')
                candidate['address_space_id'] = str(address_space['id'])
                candidate['vrf_id'] = target_vrf_id or None
                candidate['_preview_space'] = address_space
            elif candidate.get('address_space_id'):
                address_space = _get_address_space(
                    conn, str(candidate['address_space_id']), tenant_id,
                )
                if not address_space or str(address_space.get('status') or '') != 'active':
                    raise ValueError('候选映射的地址空间无效、未启用或与候选租户不匹配')
                target_vrf_id = str(address_space.get('vrf_id') or '').strip()
                if known_vrf_ids and target_vrf_id and known_vrf_ids != {target_vrf_id}:
                    raise ValueError('候选映射的地址空间与接口已知 VRF 不兼容')
                candidate['address_space_id'] = str(address_space['id'])
                candidate['vrf_id'] = target_vrf_id or None
                candidate['_preview_space'] = address_space
            else:
                candidate['address_space_id'] = None
                candidate['_preview_space'] = None
            resolved_candidates.append(candidate)

        groups_by_key: dict[tuple, dict] = {}
        selected_candidate_group: dict[str, tuple] = {}
        for candidate in resolved_candidates:
            candidate_id = str(candidate['candidate_id'])
            tenant_id = str(candidate.get('tenant_id') or 'tenant-default')
            address_space_id = str(candidate.get('address_space_id') or '')
            prefix = str(candidate.get('prefix') or '')
            if address_space_id:
                key = (tenant_id, address_space_id, prefix)
                status = 'to_create'
            else:
                # Pending scopes are deliberately unique to their original
                # candidate, even when another source reports the same CIDR.
                key = (tenant_id, '', prefix, candidate_id)
                status = 'scope_pending'
            selected_candidate_group[candidate_id] = key
            group = groups_by_key.setdefault(key, {
                '_tenant_id': tenant_id,
                '_address_space_id': address_space_id or None,
                '_prefix': prefix,
                '_status': status,
                '_candidate_ids': set(),
                '_interface_keys': set(),
                '_ip_keys': set(),
                '_interfaces': [],
                '_interfaces_by_key': {},
                '_blockers': set(),
                '_existing_prefix_id': None,
            })
            group['_candidate_ids'].add(candidate_id)
            if status == 'scope_pending':
                group['_blockers'].add(f'{prefix} 尚未明确归属地址空间')

            for interface in candidate.get('interfaces') or []:
                interface_key = (
                    str(interface.get('device_id') or ''),
                    normalize_interface_name(str(interface.get('interface_name') or '')),
                )
                if interface_key not in group['_interface_keys']:
                    group['_interface_keys'].add(interface_key)
                    group['_interfaces_by_key'][interface_key] = dict(interface)
                try:
                    address = str(ipaddress.ip_address(str(interface.get('address') or '').strip()))
                except ValueError:
                    continue
                group['_ip_keys'].add(address)

        explicit_space_ids = sorted({
            str(group['_address_space_id'])
            for group in groups_by_key.values()
            if group['_address_space_id']
        })
        prefixes_by_space: dict[str, list[dict]] = {space_id: [] for space_id in explicit_space_ids}
        if explicit_space_ids:
            placeholders = ', '.join(_PH for _ in explicit_space_ids)
            prefix_rows = conn.execute(
                f'''SELECT id, prefix, prefix_cidr, address_space_id, tenant_id, vrf_id
                      FROM prefixes
                     WHERE address_space_id IN ({placeholders})''',
                tuple(explicit_space_ids),
            ).fetchall()
            for row in prefix_rows:
                prefixes_by_space.setdefault(str(row['address_space_id'] or ''), []).append(dict(row))

        exact_prefix_ids: dict[tuple[str, str], str] = {}
        desired_prefixes = {
            (str(group['_address_space_id']), str(group['_prefix']))
            for group in groups_by_key.values() if group['_address_space_id']
        }
        for space_id, prefix in desired_prefixes:
            for row in prefixes_by_space.get(space_id, []):
                if str(row.get('prefix_cidr') or '') == prefix:
                    exact_prefix_ids[(space_id, prefix)] = str(row.get('id') or '')
                    break

        legacy_by_prefix: dict[str, list[dict]] = {}
        desired_cidrs = sorted({prefix for _, prefix in desired_prefixes})
        for start in range(0, len(desired_cidrs), 500):
            cidr_chunk = desired_cidrs[start:start + 500]
            if not cidr_chunk:
                continue
            placeholders = ', '.join(_PH for _ in cidr_chunk)
            legacy_rows = conn.execute(
                f'''SELECT id, prefix, prefix_cidr, tenant_id, vrf_id, site_id
                      FROM prefixes
                     WHERE address_space_id IS NULL
                       AND prefix_cidr IN ({placeholders})''',
                tuple(cidr_chunk),
            ).fetchall()
            for row in legacy_rows:
                legacy_by_prefix.setdefault(str(row['prefix_cidr'] or ''), []).append(dict(row))

        for group in groups_by_key.values():
            space_id = str(group['_address_space_id'] or '')
            if not space_id:
                continue
            prefix = str(group['_prefix'])
            exact_prefix_id = exact_prefix_ids.get((space_id, prefix))
            if exact_prefix_id:
                group['_status'] = 'existing'
                group['_existing_prefix_id'] = exact_prefix_id
                continue

            address_space = next(
                candidate.get('_preview_space')
                for candidate in resolved_candidates
                if str(candidate.get('address_space_id') or '') == space_id
                and str(candidate.get('tenant_id') or 'tenant-default') == str(group['_tenant_id'])
            )
            target_vrf_id = str((address_space or {}).get('vrf_id') or '')
            if any(
                str(legacy.get('tenant_id') or 'tenant-default') == str(group['_tenant_id'])
                and str(legacy.get('vrf_id') or '') == target_vrf_id
                for legacy in legacy_by_prefix.get(prefix, [])
            ):
                group['_blockers'].add(
                    f'{prefix} 已存在未映射的旧 Prefix，请先明确映射地址空间'
                )

            try:
                target_network = ipaddress.ip_network(prefix, strict=False)
            except ValueError:
                group['_blockers'].add(f'{prefix} 不是有效网段')
                continue
            for existing_prefix in prefixes_by_space.get(space_id, []):
                existing_text = str(existing_prefix.get('prefix') or '')
                try:
                    existing_network = ipaddress.ip_network(existing_text, strict=False)
                except ValueError:
                    continue
                if existing_network.version != target_network.version or not existing_network.overlaps(target_network):
                    continue
                if existing_network == target_network:
                    # The generator's fast exact lookup is keyed on prefix_cidr.
                    # A legacy-shaped row missing that canonical field would
                    # otherwise fail later in _validate_prefix_overlap.
                    group['_blockers'].add(f'{prefix} 与目标地址空间中的网段冲突')
                elif not (target_network.subnet_of(existing_network) or existing_network.subnet_of(target_network)):
                    group['_blockers'].add(f'{prefix} 与目标地址空间中的网段存在重叠')

        addresses_by_space: dict[str, set[str]] = {}
        for group in groups_by_key.values():
            space_id = str(group['_address_space_id'] or '')
            if space_id:
                addresses_by_space.setdefault(space_id, set()).update(group['_ip_keys'])

        existing_addresses: dict[tuple[str, str], list[dict]] = {}
        active_vips: set[tuple[str, str]] = set()
        for space_id, addresses in addresses_by_space.items():
            ordered_addresses = sorted(addresses)
            for start in range(0, len(ordered_addresses), 250):
                address_chunk = ordered_addresses[start:start + 250]
                if not address_chunk:
                    continue
                placeholders = ', '.join(_PH for _ in address_chunk)
                rows = conn.execute(
                    f'''SELECT ip.id, ip.subnet_id, ip.address_space_id, ip.status,
                               COALESCE(host(ip.address_inet), ip.address) AS canonical_address,
                               p.address_space_id AS prefix_address_space_id
                          FROM ip_addresses ip
                          LEFT JOIN prefixes p ON p.id = ip.subnet_id
                         WHERE (ip.address_space_id = {_PH} OR p.address_space_id = {_PH})
                           AND COALESCE(host(ip.address_inet), ip.address) IN ({placeholders})''',
                    (space_id, space_id, *address_chunk),
                ).fetchall()
                for row in rows:
                    try:
                        address = str(ipaddress.ip_address(str(row.get('canonical_address') or '').strip()))
                    except ValueError:
                        continue
                    key = (space_id, address)
                    existing_addresses.setdefault(key, []).append(dict(row))

                if _table_exists(conn, 'ipam_vips'):
                    vip_rows = conn.execute(
                        f'''SELECT COALESCE(host(address_inet), '') AS address, status
                              FROM ipam_vips
                             WHERE address_space_id = {_PH}
                               AND address_inet IN ({', '.join(f'CAST({_PH} AS inet)' for _ in address_chunk)})''',
                        (space_id, *address_chunk),
                    ).fetchall()
                    for row in vip_rows:
                        if str(row.get('status') or 'active') not in {'released', 'deprecated', 'disabled'}:
                            try:
                                active_vips.add((space_id, str(ipaddress.ip_address(str(row.get('address') or '')))))
                            except ValueError:
                                continue

        selected_prefixes_for_address: dict[tuple[str, str], set[str]] = {}
        for group in groups_by_key.values():
            space_id = str(group['_address_space_id'] or '')
            if not space_id:
                continue
            for address in group['_ip_keys']:
                selected_prefixes_for_address.setdefault((space_id, address), set()).add(str(group['_prefix']))
        for (space_id, address), selected_prefixes in selected_prefixes_for_address.items():
            if len(selected_prefixes) > 1:
                blockers_text = f'{address} 在同一地址空间的多个目标网段中重复出现'
                for group in groups_by_key.values():
                    if str(group['_address_space_id'] or '') == space_id and address in group['_ip_keys']:
                        group['_blockers'].add(blockers_text)

        for group in groups_by_key.values():
            space_id = str(group['_address_space_id'] or '')
            if not space_id:
                continue
            expected_prefix_id = str(group['_existing_prefix_id'] or '')
            for address in group['_ip_keys']:
                rows = existing_addresses.get((space_id, address), [])
                exact_rows = [row for row in rows if str(row.get('subnet_id') or '') == expected_prefix_id and expected_prefix_id]
                active_space_rows = [
                    row for row in rows
                    if str(row.get('address_space_id') or '') == space_id
                    and str(row.get('status') or 'active') not in {'released', 'available'}
                ]
                if exact_rows or active_space_rows:
                    continue
                if (space_id, address) in active_vips:
                    group['_blockers'].add(f'{address} 与目标地址空间中的 VIP 冲突')
                    continue
                # With no exact target Prefix, an active formal address in the
                # same space would make the original generation skip this IP.
                conflicting_rows = [
                    row for row in rows
                    if str(row.get('status') or 'active') not in {'released', 'available'}
                ]
                if conflicting_rows:
                    group['_blockers'].add(f'{address} 已在目标地址空间的其他网段登记')

        blockers: list[str] = []
        for group in groups_by_key.values():
            blockers.extend(sorted(group['_blockers']))
        blockers = list(dict.fromkeys(blockers))

        sorted_groups = sorted(
            groups_by_key.items(),
            key=lambda entry: (
                entry[1]['_prefix'], entry[1]['_tenant_id'],
                entry[1]['_address_space_id'] or '', tuple(sorted(entry[1]['_candidate_ids'])),
            ),
        )
        public_groups: list[dict] = []
        known_scope_ip_counts: set[tuple[str, str]] = set()
        pending_scope_ip_counts: set[tuple[str, str]] = set()
        unique_interfaces: set[tuple[str, str, str]] = set()
        pending_candidate_ids: set[str] = set()
        new_addresses: set[tuple[str, str]] = set()
        existing_address_keys: set[tuple[str, str]] = set()
        for key, group in sorted_groups:
            candidate_id_list = sorted(group['_candidate_ids'])
            tenant_id = str(group['_tenant_id'])
            space_id = str(group['_address_space_id'] or '')
            prefix = str(group['_prefix'])
            if space_id:
                group_id_payload = [tenant_id, space_id, prefix]
                for address in group['_ip_keys']:
                    ip_key = (space_id, address)
                    known_scope_ip_counts.add(ip_key)
                    rows = existing_addresses.get(ip_key, [])
                    exact_prefix_id = str(group['_existing_prefix_id'] or '')
                    exact_exists = any(
                        str(row.get('subnet_id') or '') == exact_prefix_id and exact_prefix_id
                        for row in rows
                    )
                    active_elsewhere_exists = any(
                        str(row.get('address_space_id') or '') == space_id
                        and str(row.get('status') or 'active') not in {'released', 'available'}
                        for row in rows
                    )
                    if exact_exists or active_elsewhere_exists:
                        existing_address_keys.add(ip_key)
                    elif (space_id, address) not in active_vips:
                        new_addresses.add(ip_key)
            else:
                group_id_payload = [tenant_id, '', prefix, candidate_id_list]
                pending_candidate_ids.update(candidate_id_list)
                for address in group['_ip_keys']:
                    pending_scope_ip_counts.add((candidate_id_list[0], address))
            group_id = f"{prefix}|{hashlib.sha256(json.dumps(group_id_payload, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()[:24]}"
            for interface in group['_interfaces_by_key'].values():
                unique_interfaces.add((
                    tenant_id,
                    str(interface.get('device_id') or ''),
                    normalize_interface_name(str(interface.get('interface_name') or '')),
                ))
            interfaces = sorted(
                group['_interfaces_by_key'].values(),
                key=lambda item: (
                    str(item.get('device_name') or ''),
                    str(item.get('interface_name') or ''),
                    str(item.get('address') or ''),
                ),
            )[:5]
            public_group = {
                'group_id': group_id,
                'candidate_ids': candidate_id_list,
                'prefix': prefix,
                'tenant_id': tenant_id,
                'address_space_id': group['_address_space_id'],
                'status': group['_status'],
                'interface_count': len(group['_interface_keys']),
                'ip_count': len(group['_ip_keys']),
                'interfaces': interfaces,
                'source_count': len(candidate_id_list),
            }
            if group['_existing_prefix_id']:
                public_group['existing_prefix_id'] = group['_existing_prefix_id']
            public_groups.append(public_group)

        return {
            'selected_candidate_count': len(requested_ids),
            'prefix_count': len(public_groups),
            'new_prefix_count': sum(1 for group in public_groups if group['status'] == 'to_create'),
            'existing_prefix_count': sum(1 for group in public_groups if group['status'] == 'existing'),
            'pending_candidate_count': len(pending_candidate_ids),
            'interface_count': len(unique_interfaces),
            'ip_count': len(known_scope_ip_counts) + len(pending_scope_ip_counts),
            'new_address_count': len(new_addresses),
            'existing_address_count': len(existing_address_keys),
            'can_generate': not blockers and not pending_candidate_ids,
            'blockers': blockers,
            'groups': public_groups,
        }
    finally:
        conn.close()


def generate_interface_prefixes(
    candidate_ids: Optional[list[str]] = None,
    *,
    all_pending: bool = False,
    vrf_overrides: Optional[dict[str, str]] = None,
    address_space_overrides: Optional[dict[str, str]] = None,
    audit_context: dict | None = None,
    idempotency_key: str | None = None,
    idempotency_tenant_id: str | None = None,
    allowed_scopes: set[tuple[str, str]] | None = None,
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
    confirmed_vrf_scopes: list[dict] = []
    defaulted_vrf_scopes: list[dict] = []
    confirmed_address_spaces: list[dict] = []
    try:
        preview = _load_interface_prefix_candidates(conn, include_all_interfaces=True)
        def candidate_is_allowed(item: dict) -> bool:
            return allowed_scopes is None or (
                str(item.get('tenant_id') or 'tenant-default'),
                str(item.get('site_id') or ''),
            ) in allowed_scopes

        normalized_vrf_overrides = {
            str(key).strip(): str(value).strip()
            for key, value in (vrf_overrides or {}).items()
            if str(key).strip()
        }
        normalized_space_overrides = {
            str(key).strip(): str(value).strip()
            for key, value in (address_space_overrides or {}).items()
            if str(key).strip() and str(value).strip()
        }
        if all_pending and candidate_ids is not None:
            raise ValueError('candidate_ids 与 all_pending 不能同时提供')
        if all_pending:
            selected = [
                item for item in preview['candidates']
                if item['status'] == 'to_create' and candidate_is_allowed(item)
            ]
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
            selected_all = [
                item for item in preview['candidates']
                if item['candidate_id'] in requested
            ]
            if any(not candidate_is_allowed(item) for item in selected_all):
                raise ValueError('候选不存在或无权访问，请刷新预览')
            selected = selected_all
        override_candidate_ids = {
            item['candidate_id'] for item in selected if item.get('vrf_scope_pending')
        }
        if all_pending:
            # Bulk generation includes only to-create candidates. A page-level
            # override map may also contain visible candidates already marked
            # existing; ignore those without applying them to a different row.
            normalized_vrf_overrides = {
                key: value for key, value in normalized_vrf_overrides.items()
                if key in override_candidate_ids
            }
            normalized_space_overrides = {
                key: value for key, value in normalized_space_overrides.items()
                if key in override_candidate_ids
            }
        if set(normalized_vrf_overrides) - override_candidate_ids:
            raise ValueError('VRF 选择只能应用于已选择且归属待确认的候选网段')
        if set(normalized_space_overrides) - override_candidate_ids:
            raise ValueError('地址空间选择只能应用于已选择且归属待确认的候选网段')

        for candidate in selected:
            original_candidate_id = candidate['candidate_id']
            selected_vrf = normalized_vrf_overrides.get(original_candidate_id)
            selected_space_id = normalized_space_overrides.get(original_candidate_id)
            if selected_space_id:
                address_space = _get_address_space(
                    conn, selected_space_id, str(candidate['tenant_id'] or 'tenant-default')
                )
                if not address_space or address_space['status'] != 'active':
                    raise ValueError(f"{candidate['prefix']} 的地址空间不存在、停用或不属于当前租户")
                candidate['address_space_id'] = str(address_space['id'])
                candidate['vrf_id'] = str(address_space['vrf_id'] or '') or None
                if selected_vrf and selected_vrf != '__global__' and selected_vrf != candidate['vrf_id']:
                    raise ValueError(f"{candidate['prefix']} 的 VRF 与所选地址空间不匹配")
            elif candidate.get('address_space_id'):
                address_space = _get_address_space(
                    conn,
                    str(candidate['address_space_id']),
                    str(candidate['tenant_id'] or 'tenant-default'),
                )
                if not address_space or address_space['status'] != 'active':
                    raise ValueError(f"{candidate['prefix']} 的映射地址空间不存在、停用或已越权")
                candidate['vrf_id'] = str(address_space['vrf_id'] or '') or None
            else:
                if candidate.get('vrf_scope_pending'):
                    if not selected_vrf:
                        raise ValueError(f"请为 {candidate['prefix']} 显式选择地址空间；空 VRF 不能代表 Global")
                    if selected_vrf == '__global__':
                        raise ValueError(f"请为 {candidate['prefix']} 选择一个明确的 Global 地址空间")
                    candidate['vrf_id'] = str(selected_vrf)
                if candidate.get('vrf_id'):
                    address_space = ensure_vrf_address_space(
                        conn,
                        vrf_id=str(candidate['vrf_id']),
                        security_tenant_id=str(candidate['tenant_id'] or 'tenant-default'),
                    )
                    candidate['address_space_id'] = str(address_space['id'])
                else:
                    raise ValueError(f"请为 {candidate['prefix']} 显式选择地址空间")
            if original_candidate_id in normalized_vrf_overrides or original_candidate_id in normalized_space_overrides:
                confirmed_vrf_scopes.append({
                    'prefix': candidate['prefix'],
                    'tenant_id': candidate['tenant_id'],
                    'site_id': candidate['site_id'] or '',
                    'vrf_id': candidate['vrf_id'] or '',
                })
                confirmed_address_spaces.append({
                    'prefix': candidate['prefix'],
                    'address_space_id': candidate['address_space_id'],
                    'vrf_id': candidate['vrf_id'] or '',
                })
            candidate['vrf_scope_pending'] = False
            candidate['vrf_scope_defaulted'] = False
            candidate['scope_review_reason'] = ''
        candidate_scopes = {
            (
                str(candidate.get('tenant_id') or 'tenant-default').strip() or 'tenant-default',
                str(candidate.get('address_space_id') or '').strip(),
                str(candidate.get('vrf_id') or '').strip(),
            )
            for candidate in selected
        }
        if any(not address_space_id for _, address_space_id, _ in candidate_scopes):
            raise ValueError('Resolve every selected interface Prefix to an address space before writing')
        for tenant_key, address_space_id, scope_vrf_id in sorted(candidate_scopes):
            lock_ipam_scope(
                conn,
                security_tenant_id=tenant_key,
                address_space_id=address_space_id,
                vrf_id=scope_vrf_id,
            )

        idempotency_payload = {
            'candidate_ids': sorted(str(value).strip() for value in (candidate_ids or [])),
            'all_pending': bool(all_pending),
            'vrf_overrides': dict(sorted(normalized_vrf_overrides.items())),
            'address_space_overrides': dict(sorted(normalized_space_overrides.items())),
        }
        replay = _idempotency_replay(
            conn,
            tenant_id=idempotency_tenant_id or 'tenant-default',
            operation='ipam.prefix.generate_from_interfaces',
            idempotency_key=idempotency_key,
            payload=idempotency_payload,
        )
        if replay is not None:
            replay.pop('_idempotency_replay', None)
            conn.commit()
            return replay

        now = _utc_now()
        prefix_ids: dict[str, str] = {}

        for candidate in selected:
            candidate_id = candidate['candidate_id']
            existing = conn.execute(
                f'''SELECT id, address_space_id FROM prefixes
                    WHERE address_space_id = {_PH} AND prefix_cidr = {_PH}
                    ORDER BY id LIMIT 1''',
                (
                    candidate['address_space_id'], candidate['prefix'],
                ),
            ).fetchone()
            if existing:
                prefix_ids[candidate_id] = existing['id']
                existing_prefixes += 1
                continue
            legacy_matches = conn.execute(
                f'''SELECT id FROM prefixes
                    WHERE address_space_id IS NULL AND prefix_cidr = {_PH}
                      AND COALESCE(tenant_id, 'tenant-default') = {_PH}
                      AND COALESCE(vrf_id, '') = {_PH}
                    ORDER BY id''',
                (
                    candidate['prefix'], candidate['tenant_id'],
                    candidate['vrf_id'] or '',
                ),
            ).fetchall()
            if legacy_matches:
                raise ValueError(
                    f"{candidate['prefix']} already has an unmapped legacy Prefix; resolve its address space first"
                )

            normalized, network = _normalize_prefix(candidate['prefix'])
            _validate_prefix_overlap(
                conn,
                prefix=normalized,
                tenant_id=candidate['tenant_id'],
                vrf_id=candidate['vrf_id'],
                site_id=candidate['site_id'],
                address_space_id=candidate['address_space_id'],
            )
            prefix_id = f'prefix-{uuid.uuid4().hex[:12]}'
            # An address mask or SVI name does not establish business purpose.
            # Keep unknown purposes reviewable instead of silently calling them
            # server or transit networks. Explicit loopback names are evidence.
            interface_names = [str(item.get('interface_name') or '') for item in candidate['interfaces']]
            network_type = 'loopback' if interface_names and all(
                _is_loopback_interface_name(name) for name in interface_names
            ) else 'unclassified'
            conn.execute(
                f'''INSERT INTO prefixes
                   (id, prefix, address_space_id, vrf_id, site_id, tenant_id, status, name,
                    description, network_type, created_at, updated_at,
                    prefix_cidr, ip_version, prefix_len, traceable,
                    source_type, source_ref)
                   VALUES ({_ph(18)})''',
                (
                    prefix_id, normalized, candidate['address_space_id'], candidate['vrf_id'], candidate['site_id'],
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
                        source_ref=interface.get('source_ref') or interface.get('interface_id'),
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

        result = {
            'ok': True,
            'source': 'interfaces',
            'selected_count': len(selected),
            'created_prefixes': created_prefixes,
            'existing_prefixes': existing_prefixes,
            'created_addresses': created_addresses,
            'existing_addresses': existing_addresses,
            'skipped_addresses': skipped_addresses,
            'confirmed_vrf_scopes': confirmed_vrf_scopes,
            'confirmed_address_spaces': confirmed_address_spaces,
            'defaulted_vrf_scopes': defaulted_vrf_scopes,
        }
        _store_idempotency_response(
            conn,
            tenant_id=idempotency_tenant_id or 'tenant-default',
            operation='ipam.prefix.generate_from_interfaces',
            idempotency_key=idempotency_key,
            payload=idempotency_payload,
            response=result,
            resource_type='ipam',
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type='ipam.prefix.generate_from_interfaces',
            severity='info',
            summary=(
                f"Generated {result['created_prefixes']} prefixes and "
                f"{result['created_addresses']} addresses from interface collection"
            ),
            target_type='ipam',
            target_id='interface-collection',
            after=result,
            details=result,
        )
        conn.commit()
        rebuild_prefixes_hierarchy(conn)
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_subnet(
    *,
    prefix: str,
    address_space_id: Optional[str] = None,
    vrf_id: Optional[str] = None,
    vlan_id: Optional[str] = None,
    site_id: Optional[str] = None,
    tenant_id: Optional[str] = 'tenant-default',
    status: str = 'active',
    name: str = '',
    gateway: str = '',
    description: str = '',
    network_type: str = 'unclassified',
    gateway_device_id: Optional[str] = None,
    gateway_interface_id: Optional[str] = None,
    traceable: int = 1,
    idempotency_key: str | None = None,
    audit_context: dict | None = None,
) -> dict:
    """Create a Prefix in an explicit address space or a verified VRF space."""
    prefix, net = _normalize_prefix(prefix)
    status = _validate_prefix_status(status)

    conn = get_db_connection()
    try:
        tenant_key = str(tenant_id or 'tenant-default')
        requested_vrf = str(vrf_id or '').strip()
        space_id = str(address_space_id or '').strip()
        if space_id:
            space = _get_address_space(conn, space_id, tenant_key)
            if not space:
                raise ValueError('Address space not found in this security tenant')
            if space['status'] != 'active':
                raise ValueError('Inactive address spaces cannot receive new Prefixes')
            space_vrf = str(space['vrf_id'] or '').strip()
            if requested_vrf and requested_vrf != space_vrf:
                raise ValueError('Selected address space does not match the VRF')
            vrf_id = space_vrf or None
        elif requested_vrf:
            space = ensure_vrf_address_space(
                conn, vrf_id=requested_vrf, security_tenant_id=tenant_key,
            )
            if space['status'] != 'active':
                raise ValueError('Inactive address spaces cannot receive new Prefixes')
            space_id = str(space['id'])
            vrf_id = str(space['vrf_id'])
        else:
            raise ValueError('Select an explicit Global address space; an empty VRF or site does not determine routing scope')

        lock_ipam_scope(
            conn, security_tenant_id=tenant_key,
            address_space_id=space_id, vrf_id=vrf_id,
        )
        idempotency_payload = {
            'prefix': prefix, 'address_space_id': space_id, 'vrf_id': vrf_id or '',
            'vlan_id': vlan_id or '', 'site_id': site_id or '', 'tenant_id': tenant_key,
            'status': status, 'name': name, 'gateway': gateway,
            'description': description, 'network_type': network_type,
            'gateway_device_id': gateway_device_id or '',
            'gateway_interface_id': gateway_interface_id or '', 'traceable': traceable,
        }
        replay = _idempotency_replay(
            conn,
            tenant_id=tenant_key,
            operation='ipam.prefix.create',
            idempotency_key=idempotency_key,
            payload=idempotency_payload,
        )
        if replay is not None:
            replay.pop('_idempotency_replay', None)
            conn.commit()
            return replay
        _validate_prefix_overlap(
            conn,
            prefix=prefix,
            tenant_id=tenant_id,
            vrf_id=vrf_id,
            site_id=site_id,
            address_space_id=space_id,
        )
        vlan_id = _validate_prefix_vlan(
            conn,
            vlan_id=vlan_id,
            tenant_id=tenant_id,
            site_id=site_id,
        )

        prefix_id = f"prefix-{uuid.uuid4().hex[:12]}"
        now = _utc_now()

        conn.execute(
            f'''INSERT INTO prefixes
               (id, prefix, address_space_id, vrf_id, vlan_id, site_id, tenant_id, status,
                name, gateway, description, network_type, gateway_device_id,
                gateway_interface_id, traceable, created_at, updated_at,
                prefix_cidr, ip_version, prefix_len)
               VALUES ({_ph(20)})''',
            (prefix_id, prefix, space_id, vrf_id or None, vlan_id or None, site_id or None,
             tenant_id, status, name, gateway, description, network_type,
             gateway_device_id or None, gateway_interface_id or None,
             traceable, now, now, prefix, net.version, net.prefixlen),
        )
        result = {
            'id': prefix_id,
            'prefix': prefix,
            'revision': 1,
            'address_space_id': space_id,
            'vrf_id': vrf_id or None,
            'scope_status': 'resolved',
            'ip_version': net.version,
            'prefix_len': net.prefixlen,
            'total_ips': _calculate_total_ips(prefix),
        }
        _store_idempotency_response(
            conn,
            tenant_id=tenant_key,
            operation='ipam.prefix.create',
            idempotency_key=idempotency_key,
            payload=idempotency_payload,
            response=result,
            resource_type='prefix',
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type='ipam.prefix.create',
            severity='info',
            summary=f'Created prefix {prefix}',
            target_type='prefix',
            target_id=prefix_id,
            target_name=prefix,
            after=result,
            details={'address_space_id': space_id, 'site_id': site_id, 'network_type': network_type},
        )
        rebuild_prefixes_hierarchy(
            conn,
            scope_keys={_prefix_hierarchy_scope_key({
                'address_space_id': space_id,
                'tenant_id': tenant_id,
                'vrf_id': vrf_id,
                'site_id': site_id,
            })},
            commit=False,
        )
        conn.commit()

        logger.info("Created prefix %s (%s)", prefix_id, prefix)
        return result
    finally:
        conn.close()


def update_subnet(subnet_id: str, *, audit_context: dict | None = None, **fields) -> bool:
    conn = get_db_connection()
    try:
        expected_revision = fields.pop('expected_revision', None)
        initial = conn.execute(
            f'SELECT * FROM prefixes WHERE id = {_PH}', (subnet_id,)
        ).fetchone()
        if not initial:
            return False
        initial = dict(initial)
        target_tenant = str(fields.get('tenant_id') or initial.get('tenant_id') or 'tenant-default')
        extra_scopes = {
            (
                target_tenant,
                str(initial.get('address_space_id') or ''),
                str(initial.get('vrf_id') or ''),
            )
        }
        row = _lock_prefixes_with_scopes(
            conn, {subnet_id}, extra_scopes=extra_scopes,
        ).get(str(subnet_id))
        if not row:
            return False
        if expected_revision is not None and int(row.get('revision') or 1) != int(expected_revision):
            raise ValueError('Prefix revision is stale; refresh and retry')

        if 'prefix' in fields and fields['prefix'] is not None:
            fields['prefix'], _net = _normalize_prefix(fields['prefix'])
        if 'status' in fields and fields['status'] is not None:
            fields['status'] = _validate_prefix_status(fields['status'])
        target = dict(row)
        target.update({k: v for k, v in fields.items() if v is not None})
        current_space_id = str(row['address_space_id'] or '').strip()
        if current_space_id and 'tenant_id' in fields and str(fields['tenant_id'] or '') != str(row['tenant_id'] or ''):
            raise ValueError('Changing a Prefix security tenant requires a separate migration workflow')
        if current_space_id and 'vrf_id' in fields:
            current_space = _get_address_space(
                conn, current_space_id, str(row['tenant_id'] or 'tenant-default')
            )
            if not current_space or str(fields['vrf_id'] or '').strip() != str(current_space['vrf_id'] or '').strip():
                raise ValueError('Changing a mapped Prefix routing domain requires the explicit scope workflow')
        elif not current_space_id and 'vrf_id' in fields and str(fields.get('vrf_id') or '').strip() != str(row['vrf_id'] or '').strip():
            raise ValueError('Changing an unmapped Prefix routing domain requires explicit address-space confirmation')
        if any(k in fields for k in ('prefix', 'tenant_id', 'vrf_id', 'site_id')):
            _validate_prefix_overlap(
                conn,
                prefix=target.get('prefix') or '',
                tenant_id=target.get('tenant_id'),
                vrf_id=target.get('vrf_id'),
                site_id=target.get('site_id'),
                address_space_id=target.get('address_space_id'),
                exclude_id=subnet_id,
            )
        if any(k in fields for k in ('vlan_id', 'site_id', 'tenant_id')):
            validated_vlan_id = _validate_prefix_vlan(
                conn,
                vlan_id=target.get('vlan_id'),
                tenant_id=target.get('tenant_id'),
                site_id=target.get('site_id'),
            )
            if 'vlan_id' in fields and fields['vlan_id'] is not None:
                fields['vlan_id'] = validated_vlan_id

        if 'prefix' in fields and fields['prefix'] is not None:
            _validate_prefix_cidr_contains_children(conn, subnet_id, _net)
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
            updates.append('revision = revision + 1')
            params.append(subnet_id)
            conn.execute(
                f"UPDATE prefixes SET {', '.join(updates)} WHERE id = {_PH}",
                tuple(params),
            )
            after = conn.execute(
                f'SELECT * FROM prefixes WHERE id = {_PH}', (subnet_id,)
            ).fetchone()
            _write_ipam_audit(
                conn,
                audit_context,
                event_type='ipam.prefix.update',
                severity='info',
                summary=f'Updated prefix {subnet_id}',
                target_type='prefix',
                target_id=subnet_id,
                before=dict(row),
                after=dict(after) if after else {},
                details={key: value for key, value in fields.items() if key != 'expected_revision'},
            )
            if prefix_changed or 'vrf_id' in fields or 'site_id' in fields:
                affected_scopes = {_prefix_hierarchy_scope_key(dict(row))}
                if after:
                    affected_scopes.add(_prefix_hierarchy_scope_key(dict(after)))
                rebuild_prefixes_hierarchy(conn, scope_keys=affected_scopes, commit=False)
            conn.commit()

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
    expected_revisions: dict[str, int] | None = None,
    scope_validator: Callable[[dict], None] | None = None,
    audit_context: dict | None = None,
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
    try:
        locked_prefixes = _lock_prefixes_with_scopes(
            conn, set(normalized_ids), missing_ok=True,
        )
        if len(locked_prefixes) != len(normalized_ids):
            raise LookupError('One or more prefixes were not found')
        rows = [
            {key: prefix.get(key) for key in ('id', 'tenant_id', 'site_id', 'revision')}
            for prefix in (locked_prefixes[prefix_id] for prefix_id in sorted(normalized_ids))
        ]
        placeholders = ', '.join(_PH for _ in normalized_ids)

        if expected_revisions is not None:
            if set(expected_revisions) != set(normalized_ids):
                raise ValueError('Prefix revision map does not match the selected Prefixes')
            for row in rows:
                if int(row.get('revision') or 1) != int(expected_revisions[str(row['id'])]):
                    raise ValueError(f"Prefix {row['id']} revision is stale; refresh and retry")

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
                    updated_at = {_PH},
                    revision = revision + 1
                WHERE id IN ({placeholders})''',
            (network_type, network_type, now, *normalized_ids),
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type='ipam.prefix.batch_update_network_type',
            severity='info',
            summary=f'Updated network type for {len(rows)} prefixes',
            target_type='prefix',
            target_id='batch',
            before={'ids': [str(row['id']) for row in rows]},
            after={'ids': [str(row['id']) for row in rows], 'network_type': network_type},
            details={'ids': [str(row['id']) for row in rows], 'network_type': network_type},
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


def delete_subnet(
    subnet_id: str,
    *,
    expected_revision: int | None = None,
    audit_context: dict | None = None,
) -> bool:
    conn = get_db_connection()
    try:
        prefix = _select_prefix_for_update(conn, subnet_id)
        if not prefix:
            return False
        if expected_revision is not None and int(prefix.get('revision') or 1) != int(expected_revision):
            raise ValueError('Prefix revision is stale; refresh and retry')
        _ensure_prefixes_have_no_vip_or_lease_dependencies(conn, [subnet_id])
        conn.execute(
            f'SELECT id FROM ip_addresses WHERE subnet_id = {_PH} ORDER BY id FOR UPDATE',
            (subnet_id,),
        ).fetchall()
        # Only released/available tombstones can remain after dependency check
        conn.execute(f'DELETE FROM ip_addresses WHERE subnet_id = {_PH}', (subnet_id,))
        conn.execute(f'DELETE FROM prefixes WHERE id = {_PH}', (subnet_id,))
        _write_ipam_audit(
            conn,
            audit_context,
            event_type='ipam.prefix.delete',
            severity='warning',
            summary=f'Deleted prefix {subnet_id}',
            target_type='prefix',
            target_id=subnet_id,
            before=prefix,
            after={},
        )
        rebuild_prefixes_hierarchy(
            conn,
            scope_keys={_prefix_hierarchy_scope_key(dict(prefix))},
            commit=False,
        )
        conn.commit()

        logger.info("Deleted prefix %s", subnet_id)
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def preview_delete_subnet(subnet_id: str) -> dict | None:
    """Return dependency counts and blockers before deleting a Prefix."""
    conn = get_db_connection()
    try:
        prefix = conn.execute(
            f'SELECT id, prefix, name, status, revision FROM prefixes WHERE id = {_PH}',
            (subnet_id,),
        ).fetchone()
        if not prefix:
            return None
        active_ip_row = conn.execute(
            f'''SELECT COUNT(*) AS cnt FROM ip_addresses
                 WHERE subnet_id = {_PH}
                   AND COALESCE(status, 'active') NOT IN ('released', 'available')''',
            (subnet_id,),
        ).fetchone()
        released_ip_row = conn.execute(
            f'''SELECT COUNT(*) AS cnt FROM ip_addresses
                 WHERE subnet_id = {_PH}
                   AND COALESCE(status, 'active') IN ('released', 'available')''',
            (subnet_id,),
        ).fetchone()
        active_ip_count = int(active_ip_row['cnt'] if active_ip_row else 0)
        released_ip_count = int(released_ip_row['cnt'] if released_ip_row else 0)
        pool_count = 0
        if _table_exists(conn, 'ipam_pools'):
            row = conn.execute(
                f'SELECT COUNT(*) AS cnt FROM ipam_pools WHERE prefix_id = {_PH}',
                (subnet_id,),
            ).fetchone()
            pool_count = int(row['cnt'] if row else 0)
        vip_count = 0
        if _table_exists(conn, 'ipam_vips'):
            row = conn.execute(
                f'SELECT COUNT(*) AS cnt FROM ipam_vips WHERE prefix_id = {_PH}',
                (subnet_id,),
            ).fetchone()
            vip_count = int(row['cnt'] if row else 0)
        lease_count = 0
        if _table_exists(conn, 'ipam_dhcp_leases') and _table_exists(conn, 'ipam_pools'):
            row = conn.execute(
                f'''SELECT COUNT(*) AS cnt
                      FROM ipam_dhcp_leases lease
                      JOIN ipam_pools pool ON pool.id = lease.pool_id
                     WHERE pool.prefix_id = {_PH}''',
                (subnet_id,),
            ).fetchone()
            lease_count = int(row['cnt'] if row else 0)
        child_prefix_row = conn.execute(
            f'SELECT COUNT(*) AS cnt FROM prefixes WHERE parent_prefix_id = {_PH}',
            (subnet_id,),
        ).fetchone()
        child_prefix_count = int(child_prefix_row['cnt'] if child_prefix_row else 0)

        blockers: list[str] = []
        if active_ip_count > 0:
            blockers.append(f'Prefix has {active_ip_count} active formal IP address(es)')
        if pool_count > 0:
            blockers.append(f'Prefix has {pool_count} IP pool(s)')
        if vip_count > 0:
            blockers.append(f'Prefix has {vip_count} assigned VIP record(s)')
        if lease_count > 0:
            blockers.append(f'Prefix has {lease_count} Pool-linked DHCP lease(s)')

        return {
            'prefix_id': str(prefix['id']),
            'prefix': str(prefix['prefix']),
            'name': str(prefix['name'] or ''),
            'status': str(prefix['status'] or ''),
            'revision': int(prefix['revision'] or 1),
            'active_ip_count': active_ip_count,
            'released_ip_count': released_ip_count,
            'pool_count': pool_count,
            'vip_count': vip_count,
            'lease_count': lease_count,
            'child_prefix_count': child_prefix_count,
            'can_delete': len(blockers) == 0,
            'blockers': blockers,
        }
    finally:
        conn.close()


def audit_ipam_scope_integrity(allowed_prefix_ids: list[str] | None = None) -> dict:
    """Read-only integrity audit for Prefix/child scope drift and unmapped legacy rows."""
    conn = get_db_connection()
    try:
        visible_sql, visible_ids = _allowed_prefix_filter(allowed_prefix_ids)
        ip_mismatches = [
            dict(row)
            for row in conn.execute(
                f'''SELECT ip.id AS ip_id, ip.address, ip.subnet_id AS prefix_id,
                           p.prefix, p.address_space_id AS prefix_address_space_id,
                           ip.address_space_id AS ip_address_space_id,
                           p.tenant_id AS prefix_tenant_id, ip.tenant_id AS ip_tenant_id,
                           p.vrf_id AS prefix_vrf_id, ip.vrf_id AS ip_vrf_id
                      FROM ip_addresses ip
                      JOIN prefixes p ON p.id = ip.subnet_id
                     WHERE 1=1{visible_sql}
                       AND (
                           COALESCE(ip.address_space_id, '') <> COALESCE(p.address_space_id, '')
                           OR COALESCE(ip.tenant_id, 'tenant-default') <> COALESCE(p.tenant_id, 'tenant-default')
                           OR COALESCE(ip.vrf_id, '') <> COALESCE(p.vrf_id, '')
                       )
                     ORDER BY p.prefix, ip.address''',
                visible_ids,
            ).fetchall()
        ]
        pool_mismatches: list[dict] = []
        if _table_exists(conn, 'ipam_pools'):
            pool_mismatches = [
                dict(row)
                for row in conn.execute(
                    f'''SELECT pool.id AS pool_id, pool.name AS pool_name, pool.prefix_id,
                               p.prefix, p.address_space_id AS prefix_address_space_id,
                               pool.address_space_id AS pool_address_space_id,
                               p.tenant_id AS prefix_tenant_id, pool.tenant_id AS pool_tenant_id
                          FROM ipam_pools pool
                          JOIN prefixes p ON p.id = pool.prefix_id
                         WHERE 1=1{visible_sql}
                           AND (
                               COALESCE(pool.address_space_id, '') <> COALESCE(p.address_space_id, '')
                               OR COALESCE(pool.tenant_id, 'tenant-default') <> COALESCE(p.tenant_id, 'tenant-default')
                           )
                         ORDER BY p.prefix, pool.name''',
                    visible_ids,
                ).fetchall()
            ]
        vip_mismatches: list[dict] = []
        if _table_exists(conn, 'ipam_vips'):
            vip_mismatches = [
                dict(row)
                for row in conn.execute(
                    f'''SELECT vip.id AS vip_id, host(vip.address_inet) AS address, vip.prefix_id,
                               p.prefix, p.address_space_id AS prefix_address_space_id,
                               vip.address_space_id AS vip_address_space_id,
                               p.tenant_id AS prefix_tenant_id, vip.tenant_id AS vip_tenant_id
                          FROM ipam_vips vip
                          JOIN prefixes p ON p.id = vip.prefix_id
                         WHERE 1=1{visible_sql}
                           AND (
                               COALESCE(vip.address_space_id, '') <> COALESCE(p.address_space_id, '')
                               OR COALESCE(vip.tenant_id, 'tenant-default') <> COALESCE(p.tenant_id, 'tenant-default')
                           )
                         ORDER BY p.prefix, vip.id''',
                    visible_ids,
                ).fetchall()
            ]
        unmapped_prefixes = [
            dict(row)
            for row in conn.execute(
                f'''SELECT p.id AS prefix_id, p.prefix, p.name, p.tenant_id, p.site_id, p.vrf_id, p.status
                      FROM prefixes p
                     WHERE p.address_space_id IS NULL{visible_sql}
                     ORDER BY p.prefix, p.id''',
                visible_ids,
            ).fetchall()
        ]
        duplicate_legacy_groups: dict[tuple[str, str, str], list[dict]] = {}
        for row in unmapped_prefixes:
            key = (
                str(row.get('tenant_id') or 'tenant-default'),
                str(row.get('vrf_id') or ''),
                str(row.get('prefix') or ''),
            )
            duplicate_legacy_groups.setdefault(key, []).append(row)
        duplicate_legacy_cidrs = [
            {
                'tenant_id': tenant_id,
                'vrf_id': vrf_id,
                'prefix': cidr,
                'prefix_ids': [str(item['prefix_id']) for item in group],
                'count': len(group),
            }
            for (tenant_id, vrf_id, cidr), group in sorted(duplicate_legacy_groups.items())
            if len(group) > 1
        ]
        return {
            'summary': {
                'prefix_ip_space_mismatch_count': len(ip_mismatches),
                'prefix_pool_space_mismatch_count': len(pool_mismatches),
                'prefix_vip_space_mismatch_count': len(vip_mismatches),
                'unmapped_legacy_prefix_count': len(unmapped_prefixes),
                'duplicate_legacy_cidr_count': len(duplicate_legacy_cidrs),
                'healthy': (
                    len(ip_mismatches) == 0
                    and len(pool_mismatches) == 0
                    and len(vip_mismatches) == 0
                ),
            },
            'prefix_ip_space_mismatches': ip_mismatches,
            'prefix_pool_space_mismatches': pool_mismatches,
            'prefix_vip_space_mismatches': vip_mismatches,
            'unmapped_legacy_prefixes': unmapped_prefixes,
            'duplicate_legacy_cidrs': duplicate_legacy_cidrs,
        }
    finally:
        conn.close()


def _ensure_prefixes_have_no_vip_or_lease_dependencies(conn, prefix_ids: list[str]) -> None:
    normalized_ids = sorted({str(value or '').strip() for value in prefix_ids if str(value or '').strip()})
    if not normalized_ids:
        return
    placeholders = ', '.join(_PH for _ in normalized_ids)
    active_ip = conn.execute(
        f'''SELECT id FROM ip_addresses
             WHERE subnet_id IN ({placeholders})
               AND COALESCE(status, 'active') NOT IN ('released', 'available')
             ORDER BY id LIMIT 1''',
        tuple(normalized_ids),
    ).fetchone()
    if active_ip:
        raise ValueError('Prefix has active formal IP addresses; release, move, or delete them before deleting the Prefix')
    if _table_exists(conn, 'ipam_pools'):
        pool = conn.execute(
            f'''SELECT id FROM ipam_pools
                 WHERE prefix_id IN ({placeholders})
                 ORDER BY id LIMIT 1''',
            tuple(normalized_ids),
        ).fetchone()
        if pool:
            raise ValueError('Prefix has IP pools; delete them before deleting the Prefix')
    vip = conn.execute(
        f'''SELECT id FROM ipam_vips
             WHERE prefix_id IN ({placeholders})
             ORDER BY id LIMIT 1''',
        tuple(normalized_ids),
    ).fetchone()
    if vip:
        raise ValueError('Prefix has assigned VIP records; move or delete them before deleting the Prefix')
    lease = conn.execute(
        f'''SELECT lease.id
              FROM ipam_dhcp_leases lease
              JOIN ipam_pools pool ON pool.id = lease.pool_id
             WHERE pool.prefix_id IN ({placeholders})
             ORDER BY lease.id LIMIT 1''',
        tuple(normalized_ids),
    ).fetchone()
    if lease:
        raise ValueError('Prefix has Pool-linked DHCP leases; clear or delete them before deleting the Prefix')


def delete_subnets(
    ids: list[str],
    *,
    expected_revisions: dict[str, int],
    audit_context: dict | None = None,
) -> dict:
    """Delete selected Prefixes and their IP rows as one revision-checked transaction."""
    normalized_ids = [str(value or '').strip() for value in ids]
    if not normalized_ids or any(not value for value in normalized_ids):
        raise ValueError('ids must be a non-empty list of Prefix IDs')
    if len(set(normalized_ids)) != len(normalized_ids):
        raise ValueError('ids must not contain duplicates')
    if set(expected_revisions) != set(normalized_ids):
        raise ValueError('expected_revisions must include every selected Prefix')

    conn = get_db_connection()
    try:
        locked_prefixes = _lock_prefixes_with_scopes(
            conn, set(normalized_ids), missing_ok=True,
        )
        if len(locked_prefixes) != len(normalized_ids):
            raise LookupError('One or more Prefixes were not found')
        for prefix_id in sorted(normalized_ids):
            current_revision = int(locked_prefixes[prefix_id].get('revision') or 1)
            if current_revision != int(expected_revisions[prefix_id]):
                raise ValueError(f'Prefix {prefix_id} revision is stale; refresh and retry')
        _ensure_prefixes_have_no_vip_or_lease_dependencies(conn, normalized_ids)

        placeholders = ', '.join(_PH for _ in normalized_ids)
        conn.execute(
            f'''SELECT id FROM ip_addresses
                 WHERE subnet_id IN ({placeholders})
                 ORDER BY id FOR UPDATE''',
            tuple(normalized_ids),
        ).fetchall()
        conn.execute(
            f'DELETE FROM ip_addresses WHERE subnet_id IN ({placeholders})',
            tuple(normalized_ids),
        )
        for prefix_id in sorted(normalized_ids):
            conn.execute(f'DELETE FROM prefixes WHERE id = {_PH}', (prefix_id,))
        for prefix_id in sorted(normalized_ids):
            _write_ipam_audit(
                conn,
                audit_context,
                event_type='ipam.prefix.delete',
                severity='warning',
                summary=f'Batch deleted prefix {prefix_id}',
                target_type='prefix',
                target_id=prefix_id,
                before=locked_prefixes[prefix_id],
                after={},
            )
        affected_scopes = {
            _prefix_hierarchy_scope_key(dict(locked_prefixes[prefix_id]))
            for prefix_id in normalized_ids
        }
        rebuild_prefixes_hierarchy(conn, scope_keys=affected_scopes, commit=False)
        conn.commit()
        return {'deleted': len(normalized_ids), 'ids': sorted(normalized_ids)}
    except Exception:
        conn.rollback()
        raise
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


@_with_read_scope_cache
def list_ip_inventory(*, site_id: str = 'all', prefix_id: str = '', q: str = '', status: str = 'all', device_type: str = 'all', purpose: str = 'all', page: int = 1, page_size: int = 20, registered_only: bool = False, visible_scopes: set[tuple[str, str]] | None = None) -> dict:
    """Return manual IPAM records merged with active discovered endpoints.

    Manual records remain the authoritative editable record.  Discovery facts
    fill its empty L2 fields within the same tenant and VRF; endpoints without
    a manual record are returned as read-only discovered inventory. Prefixes
    are matched within that scope and site names come from the CMDB directory.
    """
    conn = get_db_connection()
    try:
        prefix_catalog, sites, vrfs = load_inventory_catalog(conn)
        site_tenants = {
            str(row['id']): str(row['tenant_id'] or 'tenant-default')
            for row in conn.execute('SELECT id, tenant_id FROM sites').fetchall()
        }
        if visible_scopes is not None:
            prefix_catalog = [
                prefix for prefix in prefix_catalog
                if (
                    str(prefix.get('tenant_id') or 'tenant-default'),
                    str(prefix.get('site_id') or ''),
                ) in visible_scopes
            ]

        manual_rows = conn.execute(
            '''SELECT ip.*, p.prefix AS subnet_prefix, p.name AS subnet_name,
                      p.site_id AS prefix_site_id, p.network_type,
                      p.tenant_id AS prefix_tenant_id, p.vrf_id AS prefix_vrf_id,
                      p.address_space_id AS prefix_address_space_id,
                      s.site_name AS prefix_site_name, s.site_code AS prefix_site_code,
                      d.hostname AS bound_device_hostname, d.ip_address AS bound_device_ip, d.asset_id AS linked_asset_id,
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
        from services.ipam_current_endpoint_observation_service import list_current_endpoint_observations

        current_address_observation_rows = [
            *list_current_endpoint_observations(conn, observation_source="arp"),
            *list_current_endpoint_observations(conn, observation_source="ndp"),
        ]
        # CLI interface facts live in the CMDB snapshot tables by design. Read
        # only the last successful generation; never project these read-only
        # observations back into shared interfaces, ip_inventory, or monitoring.
        interface_ip_rows = _current_cmdb_interface_ip_observations(conn)

        all_items: list[dict] = []
        manual_by_scope: dict[tuple, list[dict]] = {}
        for row in manual_rows:
            item = dict(row)
            scope_key = manual_address_key(item)
            raw_site_id = str(item.get('prefix_site_id') or item.get('site_id') or '')
            manual_site = sites.get(raw_site_id)
            item.update({
                'tenant_id': scope_key[0],
                'vrf_id': str(item.get('prefix_vrf_id') or item.get('vrf_id') or ''),
                'address_space_id': item.get('prefix_address_space_id') or item.get('address_space_id') or '',
                'site_id': manual_site['id'] if manual_site else '',
                'site_name': manual_site['name'] if manual_site else '未分配站点',
                '_security_site_id': raw_site_id,
                'stored_device_type': item.get('device_type') or '',
                'stored_purpose': item.get('purpose') or '',
                'purpose': item.get('purpose') or _infer_ip_purpose(item.get('network_type')),
                'source': 'manual', 'is_discovered': False,
                '_registered_ipam_record': True,
                'discovered_last_seen': '', 'switch_name': '', 'switch_port': '', 'vlan': '',
            })
            if str(item.get('source_type') or '') == 'interface_collection' or item.get('stored_device_type') in ('', 'interface'):
                _derive_interface_address_classification(item)
            all_items.append(item)
            manual_by_scope.setdefault(scope_key, []).append(item)

        legacy_endpoint_rows = [dict(row) for row in endpoint_rows]

        def normalized_mac_identity(value) -> str:
            return ''.join(
                character for character in str(value or '').lower()
                if character in '0123456789abcdef'
            )

        def current_endpoint_identity(endpoint: dict) -> tuple[str, str, str, str] | None:
            try:
                address_key = str(ipaddress.ip_address(str(endpoint.get('ip') or '').strip()))
            except ValueError:
                return None
            mac_key = normalized_mac_identity(endpoint.get('mac'))
            tenant_key = str(endpoint.get('device_tenant_id') or endpoint.get('tenant_id') or '')
            site_owner = {
                'cmdb_device_id': endpoint.get('cmdb_device_id'),
                'asset_site_id': endpoint.get('asset_site_id'),
                'device_site_id': endpoint.get('device_site_id'),
                'device_site': endpoint.get('device_site'),
                'site': endpoint.get('site'),
            }
            site_key = endpoint_site_id(site_owner, sites)
            if not (address_key and mac_key and tenant_key and site_key):
                return None
            return address_key, mac_key, tenant_key, site_key

        legacy_by_identity: dict[tuple[str, str, str, str], list[dict]] = {}
        for endpoint in legacy_endpoint_rows:
            identity = current_endpoint_identity(endpoint)
            if identity:
                legacy_by_identity.setdefault(identity, []).append(endpoint)

        current_endpoint_rows: list[dict] = []
        current_endpoint_identities: set[tuple[str, str, str, str]] = set()
        for observation in current_address_observation_rows:
            try:
                normalized_ip = str(ipaddress.ip_address(
                    str(observation.get('ip_address') or '').strip()
                ))
            except ValueError:
                continue
            source_device_id = str(observation.get('source_device_id') or '')
            source_site_id = endpoint_site_id({
                'cmdb_device_id': source_device_id,
                'asset_site_id': observation.get('asset_site_id'),
                'device_site_id': observation.get('device_site_id'),
                'device_site': observation.get('device_site'),
            }, sites)
            observation_source = str(observation.get('observation_source') or 'arp')
            endpoint = {
                'id': '',
                'ip': normalized_ip,
                'mac': str(observation.get('mac_address') or ''),
                'hostname': '',
                'switch_id': '',
                'switch_port': '',
                'vlan': str(observation.get('vlan_id') or ''),
                'vrf': str(observation.get('mapped_vrf_id') or ''),
                'site': source_site_id,
                'last_seen': str(observation.get('observed_at') or ''),
                'source_type': observation_source,
                'observation_source': observation_source,
                'confidence': '',
                'switch_name': '',
                'device_site': observation.get('device_site'),
                'cmdb_device_id': source_device_id,
                'device_site_id': observation.get('device_site_id'),
                'device_tenant_id': str(observation.get('tenant_id') or 'tenant-default'),
                'asset_site_id': observation.get('asset_site_id'),
                'address_space_id': str(observation.get('address_space_id') or ''),
                'mapped_vrf_id': str(observation.get('mapped_vrf_id') or ''),
                'source_device_name': str(observation.get('source_device_name') or source_device_id),
                'arp_interface_name': str(observation.get('interface_name') or ''),
                'local_context_key': str(observation.get('local_context_key') or ''),
                'local_context_name': str(observation.get('local_context_name') or ''),
                'context_type': str(observation.get('context_type') or 'unknown'),
                'resolved_context_type': str(observation.get('resolved_context_type') or ''),
                'latest_collection_status': str(observation.get('latest_status') or ''),
                'latest_success_at': str(observation.get('last_success_at') or ''),
                'is_current_arp_observation': observation_source == 'arp',
                'is_current_ndp_observation': observation_source == 'ndp',
                'is_current_ip_observation': True,
            }
            identity = current_endpoint_identity(endpoint)
            if identity:
                current_endpoint_identities.add(identity)
                location_candidates = legacy_by_identity.get(identity, [])
                if len(location_candidates) == 1:
                    location = location_candidates[0]
                    endpoint.update({
                        'hostname': location.get('hostname') or '',
                        'switch_id': location.get('switch_id') or '',
                        'switch_port': location.get('switch_port') or '',
                        'switch_name': location.get('switch_name') or '',
                        'vlan': endpoint.get('vlan') or location.get('vlan') or '',
                    })
            identity_parts = (
                source_device_id, observation.get('context_source'),
                observation.get('context_type'), observation.get('local_context_key'),
                normalized_ip, observation.get('mac_address'), observation.get('interface_name'),
                observation.get('vlan_id'), observation.get('generation'),
            )
            marker = '\x1f'.join(str(value or '') for value in identity_parts)
            endpoint['id'] = f'{observation_source}-current-' + hashlib.sha256(marker.encode('utf-8')).hexdigest()[:32]
            current_endpoint_rows.append(endpoint)

        current_scope_signatures: dict[tuple, set[tuple[str, str]]] = {}
        for endpoint in current_endpoint_rows:
            scope_key = endpoint_address_key(endpoint, vrfs)
            if scope_key:
                signature = (
                    normalized_mac_identity(endpoint.get('mac')),
                    str(endpoint.get('vlan') or ''),
                )
                current_scope_signatures.setdefault(scope_key, set()).add(signature)
        current_conflicted_scope_keys = {
            scope_key for scope_key, signatures in current_scope_signatures.items()
            if len(signatures) > 1
        }
        for endpoint in current_endpoint_rows:
            endpoint['current_scope_conflict'] = (
                endpoint_address_key(endpoint, vrfs) in current_conflicted_scope_keys
            )

        filtered_legacy_rows = []
        for endpoint in legacy_endpoint_rows:
            identity = current_endpoint_identity(endpoint)
            if identity and identity in current_endpoint_identities:
                # The new per-context row is authoritative for this matching
                # IP/MAC/site observation; the legacy IP-unique row cannot add
                # reliable routing scope and is only used above for port detail.
                continue
            filtered_legacy_rows.append(endpoint)

        for endpoint in [*current_endpoint_rows, *filtered_legacy_rows]:
            address = str(endpoint.get('ip') or '')
            if not address:
                continue
            try:
                address = _normalize_address(address)
            except ValueError:
                continue
            endpoint['ip'] = address
            scope_key = endpoint_address_key(endpoint, vrfs)
            endpoint_site = endpoint_site_id(endpoint, sites)
            prefix = match_inventory_prefix(address, scope_key, endpoint_site, prefix_catalog)
            manuals = manual_by_scope.get(scope_key, [])
            manual = manuals[0] if len(manuals) == 1 else None
            if manual is not None and endpoint.get('current_scope_conflict'):
                # Several current MAC/VLAN identities claim the same scoped
                # host. Keep the formal row untouched and surface the current
                # facts separately for review.
                manual = None
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
                    'observed_switch_id': endpoint.get('switch_id') or '',
                    'observed_switch_name': endpoint.get('switch_name') or '',
                    'observed_switch_port': endpoint.get('switch_port') or '',
                    'observed_hostname': endpoint.get('hostname') or '',
                    'observed_mac_address': endpoint.get('mac') or '',
                    'observed_vlan': endpoint.get('vlan') or '',
                    'observed_vrf': endpoint.get('vrf') or '',
                    'observed_source_device_id': endpoint.get('cmdb_device_id') or '',
                    'observed_source_device_name': endpoint.get('source_device_name') or '',
                    'observed_arp_interface': endpoint.get('arp_interface_name') or '',
                    'observed_source_type': endpoint.get('observation_source') or '',
                    'observed_context_type': endpoint.get('context_type') or '',
                    'observed_context_key': endpoint.get('local_context_key') or '',
                    'observed_context_status': endpoint.get('latest_collection_status') or '',
                    'observed_confidence': endpoint.get('confidence') or '',
                    'observed_linked_asset_id': endpoint.get('linked_asset_id') or '',
                    'observed_asset_tag': endpoint.get('asset_tag') or '',
                    'observed_asset_serial_number': endpoint.get('asset_serial_number') or '',
                    'observed_asset_hostname': endpoint.get('asset_hostname') or '',
                    'observed_asset_vendor': endpoint.get('asset_vendor') or '',
                    'observed_asset_model': endpoint.get('asset_model') or '',
                    'observed_asset_management_ip': endpoint.get('asset_management_ip') or '',
                    'observed_asset_business_ip': endpoint.get('asset_business_ip') or '',
                })
                continue

            item = {
                'id': f"discovered-{endpoint['id']}", 'subnet_id': (prefix or {}).get('id') or '',
                'tenant_id': scope_key[0] if scope_key else str(endpoint.get('device_tenant_id') or ''),
                'address_space_id': (
                    str(endpoint.get('address_space_id') or '')
                    if scope_key else ''
                ),
                'vrf_id': str((prefix or {}).get('vrf_id') or endpoint.get('mapped_vrf_id') or ''),
                'address': address, 'hostname': endpoint.get('hostname') or '',
                'device_id': '' if endpoint.get('is_current_ip_observation') else endpoint.get('switch_id') or '',
                'interface_name': '' if endpoint.get('is_current_ip_observation') else endpoint.get('switch_port') or '',
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
                'scope_status': (
                    'conflict' if endpoint.get('current_scope_conflict')
                    else 'resolved' if scope_key else 'scope_pending'
                ),
                'switch_name': endpoint.get('switch_name') or '',
                'switch_port': endpoint.get('switch_port') or '',
                'vlan': endpoint.get('vlan') or '', 'discovered_vrf': endpoint.get('vrf') or '',
                'discovered_confidence': endpoint.get('confidence') or '',
                'observed_source_device_id': endpoint.get('cmdb_device_id') or '',
                'observed_source_device_name': endpoint.get('source_device_name') or '',
                'observed_arp_interface': endpoint.get('arp_interface_name') or '',
                'observed_source_type': endpoint.get('observation_source') or '',
                'observed_context_type': endpoint.get('context_type') or '',
                'observed_context_key': endpoint.get('local_context_key') or '',
                'observed_context_status': endpoint.get('latest_collection_status') or '',
                'linked_asset_id': '',
                'asset_tag': '',
                'asset_serial_number': '',
                'asset_hostname': '',
                'asset_vendor': '',
                'asset_model': '',
                'asset_management_ip': '',
                'asset_business_ip': '',
                'observed_linked_asset_id': endpoint.get('linked_asset_id') or '',
                'observed_asset_tag': endpoint.get('asset_tag') or '',
                'observed_asset_serial_number': endpoint.get('asset_serial_number') or '',
                'observed_asset_hostname': endpoint.get('asset_hostname') or '',
                'observed_asset_vendor': endpoint.get('asset_vendor') or '',
                'observed_asset_model': endpoint.get('asset_model') or '',
                'observed_asset_management_ip': endpoint.get('asset_management_ip') or '',
                'observed_asset_business_ip': endpoint.get('asset_business_ip') or '',
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
            observed_space_id = str(observation.get('address_space_id') or '')
            owner = {
                'cmdb_device_id': observation.get('device_id'),
                'asset_site_id': observation.get('asset_site_id'),
                'device_site_id': observation.get('device_site_id'),
                'device_site': observation.get('device_site'),
            }
            observed_site_id = endpoint_site_id(owner, sites)
            possible_prefixes = [
                prefix for prefix in prefix_catalog
                if prefix['tenant_id'] == tenant_id
                and not prefix.get('invalid_site_assignment')
                and ip_obj.version == prefix['network'].version
                and ip_obj in prefix['network']
                and (not observed_site_id or not prefix['site_id'] or prefix['site_id'] == observed_site_id)
            ]
            candidate_prefixes = (
                [prefix for prefix in possible_prefixes if prefix.get('address_space_id') == observed_space_id]
                if observed_space_id else possible_prefixes
            )
            prefix_match_status = (
                'matched' if observed_space_id and candidate_prefixes
                else 'unmatched' if observed_space_id or not candidate_prefixes
                else 'scope_pending'
            )
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
            observed_device_type = {
                'loopback': 'loopback',
                'svi': 'vlan',
                'tunnel': 'tunnel',
            }.get(interface_type, 'device')
            observation_id = (
                f"cmdb-interface-observed:{observation.get('device_id')}:"
                f"{observation.get('normalized_interface_name')}:"
                f"{observation.get('context_source')}:{observation.get('context_type')}:"
                f"{observation.get('local_context_key')}:{normalized_address}:{prefix_length}"
            )
            generated_records = [
                item for item in all_items
                if item.get('_registered_ipam_record')
                and item.get('source_type') == 'interface_collection'
                and str(item.get('device_id') or '') == str(observation.get('device_id') or '')
                and str(item.get('address') or '') == normalized_address
                and str(item.get('tenant_id') or 'tenant-default') == tenant_id
                and str(item.get('site_id') or '') == observed_site_id
                and observed_space_id
                and str(item.get('address_space_id') or '') == observed_space_id
            ]
            if len(generated_records) == 1:
                # An interface-generated ledger entry and its own snapshot
                # describe the same address. Keep the ledger ID and allocation
                # fields; attach the independent observation without another row.
                if not registered_only:
                    generated_records[0].update({
                        'has_interface_observation': True,
                        'interface_admin_status': str(observation.get('admin_status') or 'unknown'),
                        'interface_oper_status': str(observation.get('oper_status') or 'unknown'),
                        'discovered_last_seen': str(observation.get('observed_at') or ''),
                        'scope_status': 'resolved',
                        'observed_prefix': observed_prefix,
                        'prefix_match_status': prefix_match_status,
                    })
                continue
            all_items.append({
                'id': observation_id,
                'subnet_id': '',
                'tenant_id': tenant_id,
                'vrf_id': str(observation.get('mapped_vrf_id') or ''),
                'address_space_id': observed_space_id,
                'address': normalized_address,
                'hostname': str(observation.get('device_hostname') or ''),
                'device_id': str(observation.get('device_id') or ''),
                'interface_name': str(observation.get('interface_name') or ''),
                'mac_address': '',
                'device_type': observed_device_type,
                'purpose': 'management' if _is_management_interface_name(observation.get('interface_name') or '') else 'other',
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
                'context_source': str(observation.get('context_source') or ''),
                'context_type': str(observation.get('context_type') or 'unknown'),
                'local_context_key': str(observation.get('local_context_key') or ''),
                'local_context_name': str(observation.get('local_context_name') or ''),
                'scope_status': 'resolved' if observed_space_id else 'scope_pending',
                'interface_admin_status': str(observation.get('admin_status') or 'unknown'),
                'interface_oper_status': str(observation.get('oper_status') or 'unknown'),
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
                'prefix_review_reason': (
                    '已映射地址空间内存在候选网段'
                    if observed_space_id and candidate_prefixes
                    else '未映射设备上下文，候选网段仅供核查'
                    if candidate_prefixes
                    else '未找到匹配的地址空间网段'
                    if observed_space_id
                    else '设备本地上下文尚未映射'
                ),
                'vrf_unknown': not bool(observed_space_id),
            })

        if visible_scopes is not None:
            # Filter before gateway synthesis, summary counts, and pagination.
            # Unresolved observations have no authorized tenant/site owner and
            # are therefore omitted from restricted views.
            all_items = [
                item for item in all_items
                if (
                    str(item.get('tenant_id') or 'tenant-default'),
                    str(item.get('_security_site_id') or item.get('site_id') or ''),
                ) in visible_scopes
            ]

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

        for item in all_items:
            if item.get('_registered_ipam_record') and (
                str(item.get('source_type') or '') == 'interface_collection' or item.get('device_id')
            ):
                device_id = str(item.get('device_id') or '')
                if visible_scopes is not None and device_id:
                    device_scope = _cmdb_device_scope(conn, device_id)
                    if device_scope is None or device_scope not in visible_scopes:
                        continue
                _attach_interface_mac(conn, item, visible_scopes=visible_scopes)
                liveness = _interface_liveness(conn, item)
                if liveness:
                    item['interface_liveness'] = liveness

        if registered_only:
            all_items = [item for item in all_items if item.get('_registered_ipam_record')]

        prefix_by_id = {str(item.get('id') or ''): item for item in prefix_catalog}

        def is_matching_interface_observation(item: dict) -> bool:
            selected_prefix = prefix_by_id.get(prefix_id)
            return bool(
                item.get('source') == 'interface_cli'
                and selected_prefix is not None
                and bool(item.get('address_space_id'))
                and str(item.get('address_space_id') or '') == str(selected_prefix.get('address_space_id') or '')
                and str(item.get('observed_prefix') or '') == str(selected_prefix.get('prefix') or '')
                and str(item.get('tenant_id') or 'tenant-default') == str(selected_prefix.get('tenant_id') or 'tenant-default')
                and str(item.get('site_id') or '') == str(selected_prefix.get('site_id') or '')
            )

        for item in all_items:
            if prefix_id and str(item.get('subnet_id') or '') != prefix_id:
                if not is_matching_interface_observation(item):
                    continue
            site_key = str(item.get('site_id') or '')
            if site_key in sites and not item.get('is_virtual_gateway'):
                sites[site_key]['ip_count'] += 1

        normalized_query = q.strip().lower()
        items = []
        for item in all_items:
            if prefix_id and str(item.get('subnet_id') or '') != prefix_id and not is_matching_interface_observation(item):
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

        def _network_sort_key(value) -> tuple:
            try:
                network = ipaddress.ip_network(str(value or '').strip(), strict=False)
                return (0, network.version, int(network.network_address), network.prefixlen)
            except ValueError:
                return (1, 0, 0, 0)

        def _address_sort_key(value) -> tuple:
            try:
                address = ipaddress.ip_address(str(value or '').strip())
                return (0, address.version, int(address))
            except ValueError:
                return (1, 0, 0)

        # Numeric ordering: 10.254.34.0/30 must sort before 10.254.252.0/30.
        items.sort(key=lambda item: (
            str(item.get('site_name') or ''),
            _network_sort_key(item.get('subnet_prefix') or item.get('observed_prefix')),
            _address_sort_key(item.get('address')),
        ))

        normalized_page_size = min(max(int(page_size or 20), 1), 100)
        normalized_page = max(int(page or 1), 1)
        total = len(items)
        start = (normalized_page - 1) * normalized_page_size
        for item in all_items:
            item.pop('_registered_ipam_record', None)
            item.pop('_security_site_id', None)
        visible_sites = list(sites.values())
        if visible_scopes is not None:
            visible_sites = [
                site for site_id, site in sites.items()
                if (site_tenants.get(str(site_id), 'tenant-default'), str(site_id)) in visible_scopes
            ]
        return {
            'items': items[start:start + normalized_page_size],
            'total': total,
            'page': normalized_page,
            'page_size': normalized_page_size,
            'has_more': start + normalized_page_size < total,
            'sites': visible_sites,
            'summary': {
                # Virtual gateways are visible inventory rows, but not persisted
                # IPAM/discovery records and are counted separately.
                'total': sum(1 for item in items if not item.get('is_virtual_gateway')),
                'discovered': sum(1 for item in items if item.get('source') == 'discovered'),
                'manual': sum(1 for item in items if str(item.get('source') or '').startswith('manual')),
                'gateways': sum(1 for item in items if item.get('is_prefix_gateway')),
                'prefixes': len(prefix_catalog),
                'interface_observed': sum(1 for item in items if item.get('source') == 'interface_cli' or item.get('has_interface_observation')),
                'interface_observed_networks': len({
                    str(item.get('observed_prefix') or '')
                    for item in items
                    if (item.get('source') == 'interface_cli' or item.get('has_interface_observation')) and item.get('observed_prefix')
                }),
                'interface_unmatched_prefix': sum(1 for item in items if item.get('prefix_match_status') == 'unmatched'),
                'interface_vrf_review': sum(1 for item in items if item.get('prefix_match_status') == 'vrf_unavailable'),
                'interface_global_default': sum(1 for item in items if item.get('prefix_match_status') == 'global_default'),
                'interface_matched': sum(1 for item in items if item.get('source') == 'interface_cli' or item.get('has_interface_observation'))
                    - sum(1 for item in items if item.get('prefix_match_status') in {'unmatched', 'vrf_unavailable'}),
            },
        }
    finally:
        conn.close()



def _detail_optional_rows(conn, sql: str, params: tuple) -> list[dict]:
    """Run an optional detail query; a missing table/column must not break the panel."""
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []


def _audit_changed_fields(before: dict, after: dict) -> list[dict]:
    ignored = {'updated_at', 'revision', 'last_seen'}
    changes = []
    for key in sorted(set(before) | set(after)):
        if key in ignored:
            continue
        old, new = before.get(key), after.get(key)
        if (old or '') != (new or ''):
            changes.append({'field': key, 'before': old, 'after': new})
    return changes[:12]


@_with_read_scope_cache
def get_address_detail(
    address_id: str,
    *,
    visible_scopes: set[tuple[str, str]] | None = None,
) -> dict | None:
    """Return one registered IPAM address with its prefix, device/interface,
    discovery evidence, same-IP records in other prefixes and change history.

    Read-only. Every optional section degrades to an empty list so the detail
    panel still opens when an auxiliary table is unavailable.
    """
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'''SELECT ip.*, p.prefix AS subnet_prefix, p.name AS subnet_name,
                       p.network_type, p.status AS prefix_status, p.gateway AS prefix_gateway,
                       p.site_id AS prefix_site_id, p.vrf_id AS prefix_vrf_id,
                       p.tenant_id AS prefix_tenant_id, p.address_space_id AS prefix_address_space_id,
                       s.site_name, s.site_code,
                       d.hostname AS bound_device_hostname, d.ip_address AS bound_device_ip,
                       d.platform AS device_platform, d.model AS device_model,
                       d.role AS device_role, d.status AS device_status,
                        d.tenant_id AS bound_device_tenant_id,
                        d.site_id AS bound_device_site_id, d.site AS bound_device_site,
                       d.asset_id AS linked_asset_id,
                       pa.asset_tag, pa.serial_number AS asset_serial_number,
                        pa.site_id AS asset_site_id,
                        pa.vendor AS asset_vendor, pa.model AS asset_model,
                       pa.management_ip AS asset_management_ip
                FROM ip_addresses ip
                LEFT JOIN prefixes p ON p.id = ip.subnet_id
                LEFT JOIN sites s ON s.id = p.site_id
                LEFT JOIN devices d ON d.id = ip.device_id
                LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                WHERE ip.id = {_PH}''',
            (address_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        facts = _ipam_address_space_facts(conn)
        target_tenant_id = str(item.get('prefix_tenant_id') or item.get('tenant_id') or 'tenant-default')
        target_site_id = str(item.get('prefix_site_id') or '')
        target_space_id = str(item.get('prefix_address_space_id') or item.get('address_space_id') or '')
        target_scope = (target_tenant_id, target_site_id)
        if visible_scopes is not None and target_scope not in visible_scopes:
            return None

        device_scope = _cmdb_device_scope(conn, str(item.get('device_id') or ''), facts)
        can_view_device = (
            visible_scopes is None
            or not item.get('device_id')
            or (device_scope is not None and device_scope in visible_scopes)
        )
        if not can_view_device:
            # Address records can retain a device association after a device is
            # moved to another site. Keep the authorized IP record visible but
            # do not reveal foreign device, interface, or asset details.
            for key in (
                'device_id', 'interface_id', 'interface_name',
                'bound_device_hostname', 'bound_device_ip', 'device_platform',
                'device_model', 'device_role', 'device_status',
                'bound_device_tenant_id', 'bound_device_site_id', 'bound_device_site',
                'linked_asset_id', 'asset_tag', 'asset_serial_number', 'asset_site_id',
                'asset_vendor', 'asset_model', 'asset_management_ip',
            ):
                item[key] = ''
        item['stored_device_type'] = item.get('device_type') or ''
        item['stored_purpose'] = item.get('purpose') or ''
        item['purpose'] = item.get('purpose') or _infer_ip_purpose(item.get('network_type'))
        _derive_interface_address_classification(item)
        if can_view_device:
            _attach_interface_mac(conn, item, visible_scopes=visible_scopes)
            liveness = _interface_liveness(conn, item)
            if liveness:
                item['interface_liveness'] = liveness

        address = str(item.get('address') or '')
        vrf_name = ''
        if item.get('prefix_vrf_id'):
            vrf_rows = _detail_optional_rows(
                conn, f'SELECT vrf_name FROM vrfs WHERE id = {_PH}', (item['prefix_vrf_id'],),
            )
            vrf_name = str(vrf_rows[0].get('vrf_name') or '') if vrf_rows else ''
        item['vrf_name'] = vrf_name

        interface = None
        if can_view_device and item.get('device_id') and item.get('interface_name'):
            wanted = normalize_interface_name(item['interface_name'])
            for candidate in _detail_optional_rows(
                conn,
                f'''SELECT interface_name, description, admin_status, oper_status, mac_address,
                           interface_type, speed, mtu, access_vlan, vrf_id
                    FROM interfaces WHERE device_id = {_PH}''',
                (item['device_id'],),
            ):
                if normalize_interface_name(candidate.get('interface_name') or '') == wanted:
                    interface = candidate
                    break
            if interface is None:
                # Devices collected over CLI keep interface state in the latest
                # successful interface_inventory snapshot, not in `interfaces`.
                snapshot_rows = _detail_optional_rows(
                    conn,
                    f'''SELECT o.interface_name, o.description, o.admin_status, o.oper_status,
                               o.interface_type, o.observed_at, o.metadata_json
                        FROM cmdb_device_interface_observations o
                        JOIN cmdb_collection_snapshots snap
                          ON snap.device_id = o.device_id
                         AND snap.domain = 'interface_inventory'
                         AND snap.successful_generation = o.generation
                        WHERE o.device_id = {_PH} AND o.normalized_interface_name = {_PH}
                        LIMIT 1''',
                    (item['device_id'], wanted),
                )
                if snapshot_rows:
                    interface = snapshot_rows[0]
                    interface.pop('metadata_json', None)
                    # metadata_json is collection-level (parser/template), not a
                    # per-interface MAC; `display interface brief` has no MAC.
                    interface['mac_address'] = ''
                    interface['source'] = 'cli_snapshot'

        discovery_rows = _detail_optional_rows(
            conn,
            f'''SELECT ne.ip, ne.mac, ne.hostname, ne.vendor, ne.switch_port, ne.vlan, ne.vrf,
                       ne.site, ne.source_type, ne.first_seen, ne.last_seen, ne.is_active,
                       ne.switch_id, d.hostname AS switch_name, d.site AS device_site,
                       d.site_id AS device_site_id, d.tenant_id AS device_tenant_id,
                       pa.site_id AS asset_site_id
                FROM network_endpoints ne
                LEFT JOIN devices d ON d.id = ne.switch_id
                LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                WHERE ne.ip = {_PH}
                ORDER BY ne.last_seen DESC''',
            (address,),
        ) if address else []

        current_entries = []
        for observation in _current_address_observations(conn) if address else []:
            try:
                if str(ipaddress.ip_address(str(observation.get('ip_address') or '').strip())) != address:
                    continue
            except ValueError:
                continue
            observation_scope = _current_observation_scope(observation, facts)
            if observation_scope != (target_tenant_id, target_site_id, target_space_id):
                continue
            if visible_scopes is not None and observation_scope[:2] not in visible_scopes:
                continue
            current_entries.append({
                'mac': str(observation.get('mac_address') or ''),
                'hostname': '',
                'vendor': '',
                'switch_name': str(observation.get('source_device_name') or observation.get('source_device_id') or ''),
                'switch_port': str(observation.get('interface_name') or ''),
                'vlan': str(observation.get('vlan_id') or ''),
                'vrf': str(observation.get('mapped_vrf_id') or ''),
                'source_type': str(observation.get('observation_source') or 'arp'),
                'first_seen': '',
                'last_seen': str(observation.get('observed_at') or ''),
                'is_active': 1,
                'evidence_source': 'current_observation',
            })
        seen_keys = {(_normalized_mac(e['mac']), e['switch_name']) for e in current_entries}
        scoped_legacy_rows = []
        for legacy_row in discovery_rows:
            legacy_scope = _legacy_endpoint_scope(legacy_row, facts)
            if legacy_scope != (target_tenant_id, target_site_id, target_space_id):
                continue
            if visible_scopes is not None and legacy_scope[:2] not in visible_scopes:
                continue
            scoped_legacy_rows.append(legacy_row)
        discovery = current_entries + [
            {**entry, 'evidence_source': 'legacy_cache'} for entry in scoped_legacy_rows[:5]
            if (_normalized_mac(entry.get('mac')), str(entry.get('switch_name') or '')) not in seen_keys
        ]
        for entry in discovery:
            entry.update(_discovery_freshness(entry.get('source_type'), entry.get('last_seen')))

        same_ip_elsewhere = _detail_optional_rows(
            conn,
            f'''SELECT ip.id, ip.status, ip.hostname, p.prefix AS subnet_prefix,
                       p.vrf_id, s.site_name,
                       COALESCE(NULLIF(p.tenant_id, ''), 'tenant-default') AS tenant_id,
                       COALESCE(p.site_id, '') AS site_id,
                       COALESCE(NULLIF(p.address_space_id, ''), NULLIF(ip.address_space_id, '')) AS address_space_id
                FROM ip_addresses ip
                LEFT JOIN prefixes p ON p.id = ip.subnet_id
                LEFT JOIN sites s ON s.id = p.site_id
                WHERE ip.address = {_PH} AND ip.id <> {_PH}
                  AND COALESCE(ip.status, 'active') NOT IN ('released', 'available')
                ORDER BY ip.id''',
            (address, address_id),
        ) if address else []
        if visible_scopes is not None:
            same_ip_elsewhere = [
                other for other in same_ip_elsewhere
                if (str(other.get('tenant_id') or 'tenant-default'), str(other.get('site_id') or ''))
                in visible_scopes
            ]
        same_ip_elsewhere = same_ip_elsewhere[:10]
        for other in same_ip_elsewhere:
            other_space_id = str(other.get('address_space_id') or '')
            other['same_routing_domain'] = (
                bool(target_space_id and other_space_id and target_space_id == other_space_id)
            )

        history = []
        history_events = _detail_optional_rows(
            conn,
            f'''SELECT id, event_type, summary, actor_username, created_at,
                       before_json, after_json
                FROM audit_events
                WHERE target_type = 'ip_address' AND target_id = {_PH}
                ORDER BY created_at DESC
                LIMIT 20''',
            (address_id,),
        )
        if visible_scopes is not None and history_events:
            event_prefix_ids: dict[str, set[str]] = {}
            all_prefix_ids: set[str] = set()
            for event in history_events:
                event_prefix_ids[str(event.get('id') or '')] = set()
                for field in ('before_json', 'after_json'):
                    try:
                        snapshot = json.loads(event.get(field) or '{}') or {}
                    except (TypeError, ValueError):
                        snapshot = {}
                    if isinstance(snapshot, dict) and snapshot.get('subnet_id'):
                        prefix_ref = str(snapshot['subnet_id'])
                        event_prefix_ids[str(event.get('id') or '')].add(prefix_ref)
                        all_prefix_ids.add(prefix_ref)
            prefix_scopes: dict[str, tuple[str, str]] = {}
            if all_prefix_ids:
                prefix_rows = _detail_optional_rows(
                    conn,
                    f'''SELECT id, COALESCE(NULLIF(tenant_id, ''), 'tenant-default') AS tenant_id,
                               COALESCE(site_id, '') AS site_id
                          FROM prefixes WHERE id IN ({_ph(len(all_prefix_ids))})''',
                    tuple(sorted(all_prefix_ids)),
                )
                prefix_scopes = {
                    str(prefix['id']): (
                        str(prefix['tenant_id'] or 'tenant-default'), str(prefix['site_id'] or ''),
                    )
                    for prefix in prefix_rows
                }
            history_events = [
                event for event in history_events
                if (
                    all(prefix_ref in prefix_scopes and prefix_scopes[prefix_ref] in visible_scopes
                        for prefix_ref in event_prefix_ids.get(str(event.get('id') or ''), set()))
                    if event_prefix_ids.get(str(event.get('id') or ''))
                    else target_scope in visible_scopes
                )
            ]
        for event in history_events:
            try:
                before = json.loads(event.get('before_json') or '{}') or {}
            except (TypeError, ValueError):
                before = {}
            try:
                after = json.loads(event.get('after_json') or '{}') or {}
            except (TypeError, ValueError):
                after = {}
            history.append({
                'id': event.get('id'),
                'event_type': event.get('event_type'),
                'summary': event.get('summary'),
                'actor_username': event.get('actor_username'),
                'created_at': event.get('created_at'),
                'changes': _audit_changed_fields(
                    before if isinstance(before, dict) else {},
                    after if isinstance(after, dict) else {},
                ),
            })

        for key in ('password', 'snmp_community'):
            item.pop(key, None)
        return {
            'address': item,
            'interface': interface,
            'discovery': discovery,
            'same_ip_elsewhere': same_ip_elsewhere,
            'history': history,
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
    pool_id: str | None = None,
    requested_by: str = '',
    expires_at: str = '',
    source_type: str = 'manual',
    source_ref: str = '',
    idempotency_key: str | None = None,
    idempotency_operation: str = 'ipam.address.create',
    audit_context: dict | None = None,
) -> dict:
    """Add an IP address after validating it belongs to the subnet."""
    address = _normalize_host_address(address)
    status = _validate_address_status(status)
    idempotency_payload = {
        'subnet_id': subnet_id, 'address': address, 'hostname': hostname,
        'device_id': device_id or '', 'interface_name': interface_name,
        'interface_id': interface_id or '', 'mac_address': mac_address,
        'device_type': device_type, 'description': description, 'status': status,
        'purpose': purpose, 'pool_id': pool_id or '', 'requested_by': requested_by,
        'expires_at': expires_at, 'source_type': source_type, 'source_ref': source_ref,
    }
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
            pool_id=pool_id,
            requested_by=requested_by,
            expires_at=expires_at,
            source_type=source_type,
            source_ref=source_ref,
            idempotency_key=idempotency_key,
            idempotency_operation=idempotency_operation,
            idempotency_payload=idempotency_payload,
        )
        is_replay = bool(addr.pop('_idempotency_replay', False))
        if not is_replay:
            event_type = idempotency_operation
            is_reservation = event_type == 'ipam.address.reserve'
            _write_ipam_audit(
                conn,
                audit_context,
                event_type=event_type,
                severity='info',
                summary=(
                    f"Reserved IP {addr.get('address')} in prefix {subnet_id}"
                    if is_reservation else f"Added IP {addr.get('address')} to prefix {subnet_id}"
                ),
                target_type='ip_address',
                target_id=str(addr.get('id') or ''),
                target_name=str(addr.get('address') or address),
                after=addr,
                details={'subnet_id': subnet_id, 'pool_id': pool_id or None},
            )
        conn.commit()
        return addr
    finally:
        conn.close()


def _normalize_ip_assignment(conn, *, device_id: str | None, interface_id: str | None) -> tuple[str | None, str | None]:
    normalized_device_id = str(device_id or '').strip()
    normalized_interface_id = str(interface_id or '').strip()
    if normalized_interface_id:
        interface = conn.execute(
            'SELECT id, device_id FROM interfaces WHERE id = ?',
            (normalized_interface_id,),
        ).fetchone()
        if not interface:
            raise ValueError('Selected interface does not exist')
        interface_device_id = str(interface['device_id'] or '').strip()
        if normalized_device_id and normalized_device_id != interface_device_id:
            raise ValueError('Selected interface does not belong to the selected device')
        normalized_device_id = interface_device_id
    if normalized_device_id:
        device = conn.execute(
            'SELECT id FROM devices WHERE id = ?',
            (normalized_device_id,),
        ).fetchone()
        if not device:
            raise ValueError('Selected device does not exist')
    return normalized_device_id or None, normalized_interface_id or None


def _create_address_with_conn(conn, subnet_id: str, *, address: str, hostname: str = '',
                              device_id: str = '', interface_name: str = '',
                              interface_id: str = '', mac_address: str = '',
                              device_type: str = '', description: str = '',
                              status: str = 'active', lock_prefix: bool = False,
                              purpose: str = '', pool_id: str | None = None,
                              requested_by: str = '',
                              expires_at: str = '', source_type: str = 'manual',
                              source_ref: str = '',
                              idempotency_key: str | None = None,
                              idempotency_operation: str = 'ipam.address.create',
                              idempotency_payload: dict | None = None) -> dict:
    subnet = _select_prefix_for_update(conn, subnet_id) if lock_prefix else conn.execute(
        f'SELECT * FROM prefixes WHERE id = {_PH}', (subnet_id,)
    ).fetchone()
    if not subnet:
        raise ValueError('Subnet not found')
    lock_ipam_scope(
        conn,
        security_tenant_id=str(subnet['tenant_id'] or 'tenant-default'),
        address_space_id=str(subnet['address_space_id'] or ''),
        vrf_id=str(subnet['vrf_id'] or ''),
    )
    tenant_key = str(subnet['tenant_id'] or 'tenant-default').strip() or 'tenant-default'
    payload = idempotency_payload or {
        'subnet_id': subnet_id, 'address': address, 'hostname': hostname,
        'device_id': device_id or '', 'interface_name': interface_name,
        'interface_id': interface_id or '', 'mac_address': mac_address,
        'device_type': device_type, 'description': description, 'status': status,
        'purpose': purpose, 'pool_id': pool_id or '', 'requested_by': requested_by,
        'expires_at': expires_at, 'source_type': source_type, 'source_ref': source_ref,
    }
    replay = _idempotency_replay(
        conn,
        tenant_id=tenant_key,
        operation=idempotency_operation,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        return replay
    device_id, interface_id = _normalize_ip_assignment(
        conn, device_id=device_id, interface_id=interface_id,
    )
    try:
        net = ipaddress.ip_network(subnet['prefix'], strict=False)
    except ValueError:
        raise ValueError('Invalid subnet prefix')
    if ipaddress.ip_address(address) not in net:
        raise ValueError(f"Address {address} is not within subnet {net}")
    status = _validate_address_status(status)
    _validate_address_policy(subnet, address, device_type=device_type, purpose=purpose)
    _validate_address_space_gateway_policy(
        conn, subnet, address, device_type=device_type, purpose=purpose,
    )
    _validate_selected_pool_address(conn, subnet, address, pool_id)
    _validate_pool_address_policy(conn, subnet, address)
    _validate_address_conflicts(conn, subnet, address)
    address_columns = _table_columns(conn, 'ip_addresses')
    existing_fields = 'id, status' + (', revision' if 'revision' in address_columns else '')
    existing_fields += ', available_after' if 'available_after' in address_columns else ''
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
            'pool_id': str(pool_id or '').strip() or None,
            'description': description, 'purpose': purpose,
            'requested_by': requested_by, 'expires_at': expires_at or None,
            'source_type': source_type, 'source_ref': source_ref,
            'released_at': None, 'available_after': None, 'updated_at': now,
            'address_space_id': subnet['address_space_id'],
        }
        reuse_values = {key: value for key, value in reuse_values.items() if key in address_columns}
        assignments = ', '.join(f'{key} = {_PH}' for key in reuse_values)
        conn.execute(
            f"UPDATE ip_addresses SET {assignments}, revision = revision + 1 WHERE id = {_PH}",
            (*reuse_values.values(), existing['id']),
        )
        result = {
            'id': existing['id'], 'address': address, 'status': status,
            'revision': int(existing['revision'] or 1) + 1 if 'revision' in address_columns else 1,
            'reused': True,
        }
        _store_idempotency_response(
            conn,
            tenant_id=tenant_key,
            operation=idempotency_operation,
            idempotency_key=idempotency_key,
            payload=payload,
            response=result,
            resource_type='ip_address',
        )
        return result
    addr_id = f"ip-{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    ip_addr_with_mask = f"{address}/{net.prefixlen}"
    insert_values = {
        'id': addr_id, 'subnet_id': subnet_id, 'address': address,
        'hostname': hostname, 'device_id': device_id, 'interface_name': interface_name,
        'mac_address': mac_address, 'device_type': device_type, 'status': status,
        'description': description, 'last_seen': now, 'created_at': now, 'updated_at': now,
        'ip_address': ip_addr_with_mask, 'prefix_id': subnet_id,
        'address_space_id': subnet['address_space_id'],
        'vrf_id': subnet['vrf_id'] or '', 'tenant_id': subnet['tenant_id'] or 'tenant-default',
        'site_id': subnet['site_id'] or '', 'interface_id': interface_id,
        'address_inet': address, 'ip_version': ipaddress.ip_address(address).version,
        'purpose': purpose, 'requested_by': requested_by, 'expires_at': expires_at or None,
        'pool_id': str(pool_id or '').strip() or None,
        'source_type': source_type, 'source_ref': source_ref,
    }
    insert_values = {key: value for key, value in insert_values.items() if key in address_columns}
    conn.execute(
        f"INSERT INTO ip_addresses ({', '.join(insert_values)}) VALUES ({_ph(len(insert_values))})",
        tuple(insert_values.values()),
    )
    result = {'id': addr_id, 'address': address, 'status': status, 'revision': 1}
    _store_idempotency_response(
        conn,
        tenant_id=tenant_key,
        operation=idempotency_operation,
        idempotency_key=idempotency_key,
        payload=payload,
        response=result,
        resource_type='ip_address',
    )
    return result


def _registered_address_reservations(conn, subnet, network, now: str) -> set[str]:
    """Load active/quarantined formal addresses across the target routing domain."""
    has_available_after = 'available_after' in _table_columns(conn, 'ip_addresses')
    status_clause = (
        "(COALESCE(ip.status, 'active') NOT IN ('released', 'available') "
        "OR (ip.available_after IS NOT NULL AND ip.available_after > ?))"
        if has_available_after
        else "COALESCE(ip.status, 'active') NOT IN ('released', 'available')"
    )
    params: list = []
    space_id = str(subnet['address_space_id'] or '').strip()
    if space_id:
        scope_clause = 'ip.address_space_id = ?'
        params.append(space_id)
    else:
        scope_clause = "p.address_space_id IS NULL AND COALESCE(p.tenant_id, 'tenant-default') = ? AND COALESCE(p.vrf_id, '') = ?"
        params.extend([
            str(subnet['tenant_id'] or 'tenant-default'),
            str(subnet['vrf_id'] or ''),
        ])
    if has_available_after:
        params.append(now)
    params.append(str(network))
    rows = conn.execute(
        f"""SELECT COALESCE(host(ip.address_inet), ip.address) AS address
              FROM ip_addresses ip
              LEFT JOIN prefixes p ON p.id = ip.subnet_id
             WHERE {scope_clause}
               AND {status_clause}
               AND (
                   ip.address_inet <<= CAST(? AS cidr)
                   OR ip.address_inet IS NULL
               )""",
        tuple(params),
    ).fetchall()
    used: set[str] = set()
    for row in rows:
        raw_address = str(row['address'] or '').split('/')[0].strip()
        try:
            parsed = ipaddress.ip_address(raw_address)
        except ValueError:
            continue
        if parsed.version == network.version and parsed in network:
            used.add(str(parsed))
    return used


def _space_gateway_reservations(conn, subnet, network) -> set[str]:
    space_id = str(subnet['address_space_id'] or '').strip()
    if not space_id:
        candidate_prefixes = [subnet]
    else:
        rows = conn.execute(
            "SELECT prefix, gateway FROM prefixes WHERE address_space_id = ? AND COALESCE(gateway, '') <> ''",
            (space_id,),
        ).fetchall()
        candidate_prefixes = [dict(row) for row in rows]
    gateways: set[str] = set()
    for candidate_prefix in candidate_prefixes:
        try:
            address = _configured_prefix_gateway(candidate_prefix)
            if not address:
                continue
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if parsed.version == network.version and parsed in network:
            gateways.add(address)
    return gateways


def _space_vip_reservations(conn, subnet, network) -> set[str]:
    """Return active VIPs only when they have an explicit matching space.

    DHCP leases are observations, not hard allocation reservations. The
    containing external DHCP Pool is the allocation barrier for its range.
    Legacy VIP rows with no address-space link stay pending and cannot block
    otherwise unrelated spaces.
    """
    address_space_id = str(subnet.get('address_space_id') or '').strip()
    if not address_space_id or not _table_exists(conn, 'ipam_vips'):
        return set()
    rows = conn.execute(
        """SELECT host(address_inet) AS address FROM ipam_vips
             WHERE address_space_id = ?
               AND address_inet IS NOT NULL
               AND address_inet <<= CAST(? AS cidr)
               AND COALESCE(status, 'active') NOT IN ('released', 'deprecated', 'disabled')""",
        (address_space_id, str(network)),
    ).fetchall()
    return {str(row['address']) for row in rows if row['address']}


def _first_free_address(
    network: ipaddress._BaseNetwork,
    occupied: set[str],
) -> str | None:
    """Find the first free host by sorting occupied integers, never enumerating a subnet."""
    if network.version == 4 and network.prefixlen < 31:
        start = int(network.network_address) + 1
        end = int(network.broadcast_address) - 1
    elif network.version == 6 and network.prefixlen < 127:
        start = int(network.network_address) + 1
        end = int(network.broadcast_address)
    else:
        start = int(network.network_address)
        end = int(network.broadcast_address)
    return _first_free_address_in_bounds(network, occupied, start, end)


def _first_free_address_in_bounds(
    network: ipaddress._BaseNetwork,
    occupied: set[str],
    start: int,
    end: int,
) -> str | None:
    """Find a free address inside an inclusive integer interval without enumeration."""
    if start > end:
        return None

    blocked: list[int] = []
    for value in occupied:
        address = ipaddress.ip_address(value)
        if address.version != network.version:
            continue
        numeric_address = int(address)
        if start <= numeric_address <= end:
            blocked.append(numeric_address)
    blocked.sort()
    candidate = start
    for value in blocked:
        if value < candidate:
            continue
        if value > candidate:
            break
        candidate += 1
        if candidate > end:
            return None
    return str(ipaddress.ip_address(candidate)) if candidate <= end else None


def _current_nonformal_allocation_reservations(conn, subnet, network):
    """Return current discovered and explicitly modeled non-IP reservations."""
    resolved_discovered, pending_discovered = _discovered_address_reservations(
        conn, network,
        tenant_id=str(subnet['tenant_id'] or 'tenant-default'),
        vrf_id=str(subnet['vrf_id'] or ''),
        site_id=str(subnet['site_id'] or ''),
        address_space_id=str(subnet['address_space_id'] or ''),
    )
    gateways = _space_gateway_reservations(conn, subnet, network)
    other_resources = _space_vip_reservations(conn, subnet, network)
    return resolved_discovered | pending_discovered | gateways | other_resources, pending_discovered, gateways


def _current_allocation_occupancy(conn, subnet, network) -> tuple[set[str], int]:
    """Return the shared occupied-host set and pending observation count."""
    registered_ips = _registered_address_reservations(conn, subnet, network, _utc_now())
    nonformal, pending_discovered, gateways = _current_nonformal_allocation_reservations(
        conn, subnet, network,
    )
    occupied = registered_ips | nonformal
    pending_count = len(pending_discovered - registered_ips - gateways)
    return occupied, pending_count


def _first_free_address_from_formal_inventory(
    conn,
    subnet,
    network: ipaddress._BaseNetwork,
    intervals: list[tuple[int, int]],
    nonformal_reservations: set[str],
) -> tuple[bool, str | None]:
    """Find the first free host with a PostgreSQL ordered-gap query.

    The boolean indicates whether this query path preserved all registered-IP
    cases. Legacy rows without ``address_inet`` require the existing full
    normalization path, so they deliberately fall back to it.
    """
    if not intervals:
        return True, None
    address_columns = _table_columns(conn, 'ip_addresses')
    address_space_id = str(subnet.get('address_space_id') or '').strip()
    if 'address_inet' not in address_columns or not address_space_id:
        return False, None

    has_available_after = 'available_after' in address_columns
    now = _utc_now()
    status_clause = (
        "(COALESCE(ip.status, 'active') NOT IN ('released', 'available') "
        "OR (ip.available_after IS NOT NULL AND ip.available_after > ?))"
        if has_available_after
        else "COALESCE(ip.status, 'active') NOT IN ('released', 'available')"
    )
    null_address_params: list = [address_space_id]
    if has_available_after:
        null_address_params.append(now)
    legacy_null = conn.execute(
        f"""SELECT 1 FROM ip_addresses ip
              WHERE ip.address_space_id = ?
                AND ip.address_inet IS NULL
                AND {status_clause}
              LIMIT 1""",
        tuple(null_address_params),
    ).fetchone()
    if legacy_null:
        return False, None

    external_numbers: set[int] = set()
    for value in nonformal_reservations:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.version == network.version and address in network:
            external_numbers.add(int(address))

    gap_sql = f"""WITH occupied AS (
                      SELECT host(ip.address_inet)::inet AS address
                        FROM ip_addresses ip
                       WHERE ip.address_space_id = ?
                         AND ip.address_inet IS NOT NULL
                         AND host(ip.address_inet)::inet BETWEEN CAST(? AS inet) AND CAST(? AS inet)
                         AND {status_clause}
                  ), ordered AS (
                      SELECT address, LEAD(address) OVER (ORDER BY address) AS next_address
                        FROM occupied
                  ), candidate_gaps AS (
                      SELECT CAST(? AS inet) AS address
                       WHERE NOT EXISTS (
                           SELECT 1 FROM occupied WHERE address = CAST(? AS inet)
                       )
                      UNION ALL
                      SELECT address + 1
                        FROM ordered
                       WHERE next_address > address + 1
                      UNION ALL
                      SELECT last_address + 1
                        FROM (
                            SELECT address AS last_address
                              FROM occupied
                             ORDER BY address DESC
                             LIMIT 1
                        ) last
                       WHERE last_address < CAST(? AS inet)
                  )
                  SELECT host(address) AS address
                    FROM candidate_gaps
                   WHERE address <= CAST(? AS inet)
                   ORDER BY address
                   LIMIT 1"""

    for interval_start, interval_end in intervals:
        candidate = interval_start
        while candidate <= interval_end:
            start_address = str(ipaddress.ip_address(candidate))
            end_address = str(ipaddress.ip_address(interval_end))
            params: list = [address_space_id, start_address, end_address]
            if has_available_after:
                params.append(now)
            params.extend([start_address, start_address, end_address, end_address])
            row = conn.execute(gap_sql, tuple(params)).fetchone()
            if not row or not row['address']:
                break
            address = ipaddress.ip_address(str(row['address']))
            selected_number = int(address)
            if selected_number not in external_numbers:
                return True, str(address)
            candidate = selected_number + 1
    return True, None


def _prefix_host_bounds(network: ipaddress._BaseNetwork) -> tuple[int, int]:
    if network.version == 4 and network.prefixlen < 31:
        return int(network.network_address) + 1, int(network.broadcast_address) - 1
    if network.version == 6 and network.prefixlen < 127:
        return int(network.network_address) + 1, int(network.broadcast_address)
    return int(network.network_address), int(network.broadcast_address)


def _pool_range_integers(pool: dict) -> tuple[int, int, int]:
    try:
        start = ipaddress.ip_address(str(pool.get('start_ip') or '').strip())
        end = ipaddress.ip_address(str(pool.get('end_ip') or '').strip())
    except ValueError as exc:
        raise ValueError(f"Pool {pool.get('id')} has an invalid address range") from exc
    if start.version != end.version or int(start) > int(end):
        raise ValueError(f"Pool {pool.get('id')} has an invalid address range")
    return start.version, int(start), int(end)


def _pool_is_policy_pending(pool: dict) -> bool:
    return pool.get('management_mode') is None or pool.get('allocation_allowed') is None


def _pool_blocks_local_allocation(pool: dict) -> bool:
    if str(pool.get('status') or '').strip().lower() != 'active':
        return True
    if _pool_is_policy_pending(pool):
        return True
    return (
        str(pool.get('management_mode') or '').strip().lower() != 'local_static'
        or not bool(pool.get('allocation_allowed'))
        or bool(pool.get('mark_populated'))
    )


def _pool_policy_conflicts_with_active_addresses(
    conn,
    address_space_id: str,
    start_ip: str,
    end_ip: str,
) -> list[str]:
    """Return active formal addresses covered by a newly blocking Pool policy."""
    try:
        start = ipaddress.ip_address(str(start_ip).strip())
        end = ipaddress.ip_address(str(end_ip).strip())
    except ValueError as exc:
        raise ValueError(f'Invalid Pool range: {exc}') from exc
    rows = conn.execute(
        """SELECT ip.id, COALESCE(host(ip.address_inet), ip.address) AS address
             FROM ip_addresses ip
             LEFT JOIN prefixes prefix ON prefix.id = ip.subnet_id
            WHERE (ip.address_space_id = ? OR (ip.address_space_id IS NULL AND prefix.address_space_id = ?))
              AND COALESCE(ip.status, 'active') NOT IN ('released', 'available')""",
        (address_space_id, address_space_id),
    ).fetchall()
    conflicts: list[str] = []
    for row in rows:
        try:
            address = ipaddress.ip_address(str(row['address'] or '').strip())
        except ValueError:
            continue
        if address.version == start.version == end.version and start <= address <= end:
            conflicts.append(str(row['id']))
    return conflicts


def _ensure_pool_policy_does_not_hide_active_addresses(
    conn,
    *,
    pool: dict,
    start_ip: str,
    end_ip: str,
) -> None:
    space_id = str(pool.get('address_space_id') or pool.get('resolved_address_space_id') or '').strip()
    if not space_id:
        raise ValueError('Resolve the Pool address space before applying an allocation policy')
    conflicts = _pool_policy_conflicts_with_active_addresses(
        conn, space_id, start_ip, end_ip,
    )
    if conflicts:
        samples = ', '.join(conflicts[:5])
        raise ValueError(
            f"Pool policy conflicts with {len(conflicts)} active IP record(s); sample IDs: {samples}"
        )


def _pool_rows_for_address_space(conn, address_space_id: str, tenant_id: str) -> list[dict]:
    """Load Pool ranges associated directly or through an explicitly mapped Prefix."""
    rows = conn.execute(
        """SELECT pool.*, prefix.address_space_id AS prefix_address_space_id,
                  prefix.tenant_id AS prefix_tenant_id, prefix.prefix AS prefix_cidr,
                  COALESCE(pool.address_space_id, prefix.address_space_id) AS resolved_address_space_id
             FROM ipam_pools pool
             JOIN prefixes prefix ON prefix.id = pool.prefix_id
            WHERE pool.address_space_id = ? OR prefix.address_space_id = ?""",
        (address_space_id, address_space_id),
    ).fetchall()
    result: list[dict] = []
    expected_tenant = str(tenant_id or 'tenant-default')
    for row in rows:
        pool = dict(row)
        pool_space = str(pool.get('address_space_id') or '').strip()
        prefix_space = str(pool.get('prefix_address_space_id') or '').strip()
        prefix_tenant = str(pool.get('prefix_tenant_id') or 'tenant-default')
        pool_tenant = str(pool.get('tenant_id') or 'tenant-default')
        if pool_space and prefix_space and pool_space != prefix_space:
            raise ValueError(f"Pool {pool.get('id')} address space conflicts with its parent Prefix")
        resolved_space = pool_space or prefix_space
        if resolved_space != address_space_id:
            continue
        if prefix_tenant != pool_tenant or pool_tenant != expected_tenant:
            raise ValueError(f"Pool {pool.get('id')} tenant does not match its address space")
        pool['resolved_address_space_id'] = resolved_space
        result.append(pool)
    return result


def _merge_integer_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if start > end:
            continue
        if not merged or start > merged[-1][1] + 1:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _subtract_integer_ranges(
    start: int,
    end: int,
    blocked: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    allowed: list[tuple[int, int]] = []
    cursor = start
    for block_start, block_end in _merge_integer_ranges(blocked):
        if block_end < cursor:
            continue
        if block_start > end:
            break
        if block_start > cursor:
            allowed.append((cursor, min(end, block_start - 1)))
        cursor = max(cursor, block_end + 1)
        if cursor > end:
            break
    if cursor <= end:
        allowed.append((cursor, end))
    return allowed


def _pool_allocation_intervals(
    conn,
    subnet,
    network: ipaddress._BaseNetwork,
    *,
    pool_id: str | None = None,
) -> list[tuple[int, int]]:
    host_start, host_end = _prefix_host_bounds(network)
    if host_start > host_end:
        return []
    space_id = str(subnet.get('address_space_id') or '').strip()
    if not space_id:
        if pool_id:
            raise ValueError('Resolve the Prefix address space before selecting a Pool')
        return [(host_start, host_end)]

    all_pools = _pool_rows_for_address_space(
        conn, space_id, str(subnet.get('tenant_id') or 'tenant-default'),
    )
    active_pools = [
        pool for pool in all_pools
        if str(pool.get('status') or '').strip().lower() == 'active'
    ]
    target_pool = None
    if pool_id:
        target_pool = next((pool for pool in active_pools if str(pool.get('id')) == str(pool_id)), None)
        if not target_pool:
            raise ValueError('Selected Pool is not active in this address space')
        if _pool_is_policy_pending(target_pool):
            raise ValueError('Selected Pool policy is pending confirmation')
        if _pool_blocks_local_allocation(target_pool):
            raise ValueError('Selected Pool does not allow local allocation')
        target_version, target_start, target_end = _pool_range_integers(target_pool)
        if target_version != network.version or target_start < int(network.network_address) or target_end > int(network.broadcast_address):
            raise ValueError('Selected Pool range is not contained by this Prefix')
        base_start = max(host_start, target_start)
        base_end = min(host_end, target_end)
    else:
        base_start, base_end = host_start, host_end

    if base_start > base_end:
        return []

    blockers: list[tuple[int, int]] = []
    for pool in all_pools:
        if target_pool and str(pool.get('id')) == str(target_pool.get('id')):
            continue
        if not _pool_blocks_local_allocation(pool):
            continue
        version, start, end = _pool_range_integers(pool)
        if version != network.version:
            continue
        clipped_start = max(base_start, start)
        clipped_end = min(base_end, end)
        if clipped_start <= clipped_end:
            blockers.append((clipped_start, clipped_end))

    return _subtract_integer_ranges(base_start, base_end, blockers)


def _first_free_address_in_intervals(
    network: ipaddress._BaseNetwork,
    occupied: set[str],
    intervals: list[tuple[int, int]],
) -> str | None:
    for start, end in intervals:
        candidate = _first_free_address_in_bounds(network, occupied, start, end)
        if candidate:
            return candidate
    return None


def _validate_pool_address_policy(conn, subnet, address: str) -> None:
    """Prevent manual records inside explicitly non-allocatable Pool ranges."""
    space_id = str(subnet.get('address_space_id') or '').strip()
    if not space_id:
        return
    address_obj = ipaddress.ip_address(address)
    for pool in _pool_rows_for_address_space(
        conn, space_id, str(subnet.get('tenant_id') or 'tenant-default'),
    ):
        # NULL mode/allow means an old, unconfirmed policy. It blocks automatic
        # suggestions but does not override the user's approved manual claim.
        status = str(pool.get('status') or '').strip().lower()
        if status == 'active' and _pool_is_policy_pending(pool):
            continue
        if not _pool_blocks_local_allocation(pool):
            continue
        version, start, end = _pool_range_integers(pool)
        if address_obj.version == version and start <= int(address_obj) <= end:
            raise ValueError(
                f"IP address {address} is inside a Pool that does not allow local allocation"
            )


def _validate_selected_pool_address(conn, subnet, address: str, pool_id: str | None) -> None:
    selected_pool_id = str(pool_id or '').strip()
    if not selected_pool_id:
        return
    space_id = str(subnet.get('address_space_id') or '').strip()
    if not space_id:
        raise ValueError('Resolve the Prefix address space before selecting a Pool')
    pools = _pool_rows_for_address_space(
        conn, space_id, str(subnet.get('tenant_id') or 'tenant-default'),
    )
    pool = next((item for item in pools if str(item.get('id') or '') == selected_pool_id), None)
    if not pool:
        raise ValueError('Selected Pool is not in this address space')
    if str(pool.get('status') or '').strip().lower() != 'active':
        raise ValueError('Selected Pool is not active')
    if _pool_is_policy_pending(pool):
        raise ValueError('Selected Pool policy is pending confirmation')
    if _pool_blocks_local_allocation(pool):
        raise ValueError('Selected Pool does not allow local allocation')
    version, start, end = _pool_range_integers(pool)
    try:
        network = ipaddress.ip_network(str(subnet['prefix']), strict=False)
        candidate = ipaddress.ip_address(address)
    except ValueError as exc:
        raise ValueError('Selected Pool or target Prefix has an invalid address') from exc
    if (
        version != network.version
        or start < int(network.network_address)
        or end > int(network.broadcast_address)
    ):
        raise ValueError('Selected Pool range is not contained by this Prefix')
    if candidate.version != version or not start <= int(candidate) <= end:
        raise ValueError(f'Address {address} is outside the selected Pool range')


def update_address(
    address_id: str,
    *,
    audit_context: dict | None = None,
    audit_event_type: str = 'ipam.address.update',
    audit_summary: str | None = None,
    audit_details: dict | None = None,
    **fields,
) -> bool:
    conn = get_db_connection()
    try:
        expected_revision = fields.pop('expected_revision', None)
        initial = conn.execute(
            f'SELECT * FROM ip_addresses WHERE id = {_PH}', (address_id,)
        ).fetchone()
        if not initial:
            return False
        initial = dict(initial)
        subnet_id = str(initial.get('subnet_id') or '')
        subnet = _select_prefix_for_update(conn, subnet_id)
        if not subnet:
            raise ValueError('Subnet not found')
        row = conn.execute(
            f'SELECT * FROM ip_addresses WHERE id = {_PH} FOR UPDATE', (address_id,)
        ).fetchone()
        if not row:
            return False
        row = dict(row)
        if str(row.get('subnet_id') or '') != subnet_id:
            raise ValueError('Address Prefix changed concurrently; refresh and retry')
        if expected_revision is not None and int(row.get('revision') or 1) != int(expected_revision):
            raise ValueError('Address revision is stale; refresh and retry')

        if 'device_id' in fields or 'interface_id' in fields:
            normalized_device, normalized_interface = _normalize_ip_assignment(
                conn,
                device_id=fields.get('device_id', row.get('device_id')),
                interface_id=fields.get('interface_id', row.get('interface_id')),
            )
            fields['device_id'] = normalized_device
            fields['interface_id'] = normalized_interface

        if 'pool_id' in fields:
            target_pool_id = str(fields.get('pool_id') or '').strip() or None
            if target_pool_id:
                _validate_selected_pool_address(
                    conn, subnet, str(row.get('address') or ''), target_pool_id,
                )
            _validate_pool_address_policy(conn, subnet, str(row.get('address') or ''))
            fields['pool_id'] = target_pool_id

        if 'status' in fields and fields['status'] is not None:
            target_status = _validate_address_status(fields['status'])
            current_status = (row['status'] or 'active').lower()
            if target_status != current_status and target_status not in ADDRESS_TRANSITIONS.get(current_status, set()):
                raise ValueError(f'Invalid address lifecycle transition: {current_status} -> {target_status}')
            fields['status'] = target_status
            if target_status not in ('released', 'available'):
                _validate_address_conflicts(conn, subnet, str(row['address']), exclude_id=address_id)

        updates = []
        params = []
        address_columns = _table_columns(conn, 'ip_addresses')
        for field in ('hostname', 'device_id', 'interface_name', 'interface_id', 'mac_address',
                      'device_type', 'description', 'status', 'purpose', 'requested_by',
                      'expires_at', 'source_type', 'source_ref', 'released_at', 'available_after', 'pool_id'):
            val = fields.get(field)
            if (
                val is not None
                or (field in {'device_id', 'interface_id', 'pool_id'} and field in fields)
            ) and field in address_columns:
                updates.append(f'{field} = {_PH}')
                params.append(val)
        if updates:
            updates.append(f'updated_at = {_PH}')
            params.append(_utc_now())
            updates.append('revision = revision + 1')
            params.append(address_id)
            conn.execute(
                f"UPDATE ip_addresses SET {', '.join(updates)} WHERE id = {_PH}",
                tuple(params),
            )
            after = conn.execute(
                f'SELECT * FROM ip_addresses WHERE id = {_PH}', (address_id,)
            ).fetchone()
            _write_ipam_audit(
                conn,
                audit_context,
                event_type=audit_event_type,
                severity='info',
                summary=audit_summary or f'Updated address {address_id}',
                target_type='ip_address',
                target_id=address_id,
                before=row,
                after=dict(after) if after else {},
                details=audit_details or {key: value for key, value in fields.items() if key != 'expected_revision'},
            )
            conn.commit()
        return True
    finally:
        conn.close()


def delete_address(
    address_id: str,
    *,
    expected_revision: int | None = None,
    audit_context: dict | None = None,
) -> bool:
    conn = get_db_connection()
    try:
        initial = conn.execute(
            f'SELECT subnet_id FROM ip_addresses WHERE id = {_PH}', (address_id,)
        ).fetchone()
        if not initial:
            return False
        subnet_id = str(initial['subnet_id'] or '')
        subnet = _select_prefix_for_update(conn, subnet_id)
        if not subnet:
            raise ValueError('Address Prefix no longer exists; refresh and retry')
        locked = conn.execute(
            f'SELECT * FROM ip_addresses WHERE id = {_PH} FOR UPDATE', (address_id,)
        ).fetchone()
        if not locked:
            return False
        before = dict(locked)
        if str(before.get('subnet_id') or '') != subnet_id:
            raise ValueError('Address Prefix changed concurrently; refresh and retry')
        current = conn.execute(
            f'SELECT revision FROM ip_addresses WHERE id = {_PH}', (address_id,)
        ).fetchone()
        current_revision = int(dict(current).get('revision') or 1) if current else 1
        if expected_revision is not None and current_revision != int(expected_revision):
            raise ValueError('Address revision is stale; refresh and retry')
        conn.execute(f'DELETE FROM ip_addresses WHERE id = {_PH}', (address_id,))
        _write_ipam_audit(
            conn,
            audit_context,
            event_type='ipam.address.delete',
            severity='warning',
            summary=f'Deleted address {address_id}',
            target_type='ip_address',
            target_id=address_id,
            before=before,
            after={},
        )
        conn.commit()
        return True
    finally:
        conn.close()


def allocate_next_address(subnet_id: str, *, hostname: str = '', device_id: str = '',
                          interface_id: str = '', interface_name: str = '', device_type: str = '',
                          mac_address: str = '', purpose: str = '',
                          pool_id: str = '',
                          requested_by: str = '', status: str = 'allocated',
                          expires_at: str = '',
                          idempotency_key: str | None = None,
                          audit_context: dict | None = None) -> dict:
    conn = get_db_connection()
    try:
        subnet = _select_prefix_for_update(conn, subnet_id)
        if not subnet:
            raise ValueError('Subnet not found')
        if str(subnet.get('status') or '').strip().lower() == 'container':
            raise ValueError('Container prefixes cannot allocate host IP addresses directly; allocate from a child prefix')
        space_id = str(subnet['address_space_id'] or '').strip()
        if not space_id:
            raise ValueError('Resolve the Prefix address space before automatic allocation')
        lock_ipam_scope(
            conn,
            security_tenant_id=str(subnet['tenant_id'] or 'tenant-default'),
            address_space_id=space_id,
            vrf_id=str(subnet['vrf_id'] or ''),
        )
        tenant_key = str(subnet['tenant_id'] or 'tenant-default').strip() or 'tenant-default'
        idempotency_payload = {
            'subnet_id': subnet_id, 'hostname': hostname,
            'device_id': device_id or '', 'interface_id': interface_id or '',
            'interface_name': interface_name, 'device_type': device_type,
            'mac_address': mac_address, 'purpose': purpose,
            'pool_id': pool_id or '', 'requested_by': requested_by,
            'status': status, 'expires_at': expires_at,
        }
        replay = _idempotency_replay(
            conn,
            tenant_id=tenant_key,
            operation='ipam.address.allocate',
            idempotency_key=idempotency_key,
            payload=idempotency_payload,
        )
        if replay is not None:
            replay.pop('_idempotency_replay', None)
            conn.commit()
            return replay
        net = ipaddress.ip_network(subnet['prefix'], strict=False)
        nonformal_reservations, _pending_discovery_count, _gateways = (
            _current_nonformal_allocation_reservations(conn, subnet, net)
        )
        candidate_intervals = _pool_allocation_intervals(
            conn, subnet, net, pool_id=pool_id or None,
        )
        formal_path_handled, selected = _first_free_address_from_formal_inventory(
            conn, subnet, net, candidate_intervals, nonformal_reservations,
        )
        if not formal_path_handled:
            registered_ips = _registered_address_reservations(
                conn, subnet, net, _utc_now(),
            )
            selected = _first_free_address_in_intervals(
                net, registered_ips | nonformal_reservations, candidate_intervals,
            )
        if not selected:
            if pool_id:
                raise ValueError('No available IP addresses in the selected Pool')
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
            pool_id=pool_id or None,
            requested_by=requested_by,
            expires_at=expires_at,
        )
        addr = {
            **addr,
            'subnet_id': subnet_id,
            'address_space_id': space_id,
            'pool_id': pool_id or None,
        }
        _write_ipam_audit(
            conn,
            audit_context,
            event_type='ipam.address.allocate',
            severity='info',
            summary=f"Allocated next IP {addr.get('address')} from prefix {subnet_id}",
            target_type='ip_address',
            target_id=str(addr.get('id') or ''),
            target_name=str(addr.get('address') or ''),
            after=addr,
            details={'subnet_id': subnet_id, **idempotency_payload},
        )
        _store_idempotency_response(
            conn,
            tenant_id=tenant_key,
            operation='ipam.address.allocate',
            idempotency_key=idempotency_key,
            payload=idempotency_payload,
            response=addr,
            resource_type='ip_address',
        )
        conn.commit()
        return addr
    finally:
        conn.close()


def reserve_address(subnet_id: str, *, address: str, hostname: str = '', device_id: str = '',
                    interface_id: str = '', interface_name: str = '', mac_address: str = '',
                    device_type: str = '',
                    purpose: str = '', pool_id: str | None = None,
                    requested_by: str = '', expires_at: str = '',
                    idempotency_key: str | None = None,
                    audit_context: dict | None = None) -> dict:
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
        pool_id=pool_id,
        requested_by=requested_by,
        expires_at=expires_at,
        idempotency_key=idempotency_key,
        idempotency_operation='ipam.address.reserve',
        audit_context=audit_context,
    )


def release_address(
    address_id: str,
    *,
    released_by: str = '',
    expected_revision: int | None = None,
    audit_context: dict | None = None,
) -> bool:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    available_after = (now + timedelta(hours=24)).isoformat()
    description_suffix = f"Released by {released_by}" if released_by else "Released"
    return update_address(
        address_id,
        status='released',
        device_id=None,
        interface_id=None,
        interface_name='',
        mac_address='',
        description=description_suffix,
        released_at=now.isoformat(),
        available_after=available_after,
        expected_revision=expected_revision,
        audit_context=audit_context,
        audit_event_type='ipam.address.release',
        audit_summary=f'Released address {address_id}',
        audit_details={'released_by': released_by},
    )


# ══════════════════════════════════════════════════════════
# Conflict Detection
# ══════════════════════════════════════════════════════════

def detect_conflicts(allowed_prefix_ids: list[str] | None = None) -> dict:
    """Report duplicate IP/MAC facts only within an explicitly known address space."""
    conn = get_db_connection()
    try:
        visible_sql, visible_params = _allowed_prefix_filter(
            allowed_prefix_ids,
            column='ip.subnet_id',
        )
        scope_sql = "COALESCE(NULLIF(BTRIM(ip.address_space_id), ''), NULLIF(BTRIM(owner.address_space_id), ''))"
        ip_address_sql = "COALESCE(host(ip.address_inet), ip.address)"
        dup_ips = conn.execute(f"""
            SELECT {scope_sql} AS address_space_id,
                   {ip_address_sql} AS address,
                   {_GROUP_CONCAT.format(col='ip.subnet_id')} AS subnets,
                   COUNT(*) AS cnt
              FROM ip_addresses ip
              LEFT JOIN prefixes owner ON owner.id = ip.subnet_id
             WHERE COALESCE(ip.status, 'active') NOT IN ('released', 'available')
               AND {scope_sql} IS NOT NULL
               {visible_sql}
             GROUP BY {scope_sql}, {ip_address_sql}
            HAVING COUNT(*) > 1
        """, visible_params).fetchall()

        dup_macs = conn.execute(f"""
            SELECT {scope_sql} AS address_space_id,
                   LOWER(BTRIM(ip.mac_address)) AS mac_address,
                   {_GROUP_CONCAT.format(col='ip.address')} AS addresses,
                   {_GROUP_CONCAT.format(col='ip.subnet_id')} AS subnets,
                   COUNT(*) AS cnt
              FROM ip_addresses ip
              LEFT JOIN prefixes owner ON owner.id = ip.subnet_id
             WHERE NULLIF(BTRIM(ip.mac_address), '') IS NOT NULL
               AND COALESCE(ip.status, 'active') NOT IN ('released', 'available')
               AND {scope_sql} IS NOT NULL
               {visible_sql}
             GROUP BY {scope_sql}, LOWER(BTRIM(ip.mac_address))
            HAVING COUNT(*) > 1
        """, visible_params).fetchall()

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

@_with_read_scope_cache
def ipam_summary(allowed_prefix_ids: list[str] | None = None) -> dict:
    conn = get_db_connection()
    try:
        prefix_filter, visible_ids = _allowed_prefix_filter(allowed_prefix_ids)
        subnet_where = f' WHERE 1=1{prefix_filter}'
        subnet_params = visible_ids
        address_filter, address_ids = _allowed_prefix_filter(
            allowed_prefix_ids,
            column='ip.subnet_id',
        )
        address_where = f' WHERE 1=1{address_filter}'
        subnets = conn.execute(
            f'SELECT COUNT(*) as cnt FROM prefixes p{subnet_where}',
            subnet_params,
        ).fetchone()
        addresses = conn.execute(
            f'SELECT COUNT(*) as cnt FROM ip_addresses ip{address_where}',
            address_ids,
        ).fetchone()

        # Calculate total capacity dynamically
        all_prefixes = conn.execute(
            f'SELECT id, prefix, status, gateway, tenant_id, vrf_id, site_id, address_space_id FROM prefixes p{subnet_where}',
            subnet_params,
        ).fetchall()
        capacity_prefixes = [
            row for row in all_prefixes
            if _is_capacity_prefix(row['prefix'], row['status'])
        ]
        total_capacity = 0
        total_reserved = 0
        total_allocatable_free = 0
        total_effective_used = 0
        for row in capacity_prefixes:
            metrics = _calculate_prefix_capacity_metrics(conn, dict(row))
            total_capacity += metrics['total_ips']
            total_reserved += metrics['reserved_ips']
            total_allocatable_free += metrics['allocatable_free_ips']
            total_effective_used += metrics['effective_used_ips']

        total_used = sum(_count_prefix_used_ips(conn, dict(prefix_row)) for prefix_row in all_prefixes)

        return {
            'total_subnets': subnets['cnt'] if subnets else 0,
            'total_addresses': addresses['cnt'] if addresses else 0,
            'total_capacity': total_capacity,
            'total_used': total_used,
            'total_reserved': total_reserved,
            'total_allocatable_free': total_allocatable_free,
            'total_effective_used': total_effective_used,
            'capacity_prefixes_count': len(capacity_prefixes),
            'excluded_prefixes_count': len(all_prefixes) - len(capacity_prefixes),
            'high_utilization_subnets': [],
        }
    finally:
        conn.close()


@_with_read_scope_cache
def get_utilization_analytics(
    network_scope: str = 'all',
    allowed_prefix_ids: list[str] | None = None,
) -> dict:
    """Return analytics data for IPAM utilization dashboards.

    ``business`` uses explicitly classified business prefixes; ``all`` keeps
    the historical capacity report. Every aggregate is computed from one
    consistent prefix set. Shape matches the frontend IPUtilizationTab:
      { overview, top_utilized_prefixes, site_breakdown, forecast_trend }
    """
    network_scope = str(network_scope or '').strip().lower()
    if network_scope not in {'business', 'all'}:
        raise ValueError('Unsupported IPAM utilization network_scope')

    conn = get_db_connection()
    try:
        visible_sql, visible_ids = _allowed_prefix_filter(allowed_prefix_ids)
        # ── Per-prefix utilization ──────────────────────────
        rows = conn.execute(
            '''SELECT p.id, p.prefix, p.name, p.status, p.site_id, p.gateway, p.tenant_id,
                      p.vrf_id, p.address_space_id, p.network_type,
                      s.site_name, s.site_code
               FROM prefixes p
               LEFT JOIN sites s ON p.site_id = s.id
               WHERE 1=1''' + visible_sql,
            visible_ids,
        ).fetchall()
        scoped_rows = (
            [row for row in rows if _is_business_utilization_network(row['network_type'])]
            if network_scope == 'business'
            else rows
        )
        scope_excluded_prefixes_count = len(rows) - len(scoped_rows)
        interconnect_prefixes_excluded_count = (
            sum(
                str(row['network_type'] or '').strip().lower() in INTERCONNECT_NETWORK_TYPES
                for row in rows
            )
            if network_scope == 'business'
            else 0
        )

        per_prefix = []
        total_ips_sum = 0
        used_ips_sum = 0
        reserved_ips_sum = 0
        allocatable_free_ips_sum = 0
        effective_used_ips_sum = 0
        free_ips_sum = 0
        capacity_prefixes_count = 0
        excluded_prefixes_count = 0
        site_agg: dict[str, dict] = {}

        for r in scoped_rows:
            row_dict = dict(r)
            metrics = _calculate_prefix_capacity_metrics(conn, row_dict)
            total = metrics['total_ips']
            exclusion_reason = _capacity_exclusion_reason(r['prefix'], r['status'])
            capacity_eligible = not exclusion_reason
            used_count = metrics['used_ips']

            if capacity_eligible:
                total_ips_sum += total
                used_ips_sum += used_count
                reserved_ips_sum += metrics['reserved_ips']
                allocatable_free_ips_sum += metrics['allocatable_free_ips']
                effective_used_ips_sum += metrics['effective_used_ips']
                if metrics['allocation_ready']:
                    free_ips_sum += metrics['allocatable_free_ips']
                else:
                    free_ips_sum += max(0, total - used_count)
                capacity_prefixes_count += 1
            else:
                excluded_prefixes_count += 1

            per_prefix.append({
                'id': r['id'],
                'prefix': r['prefix'],
                'name': r['name'],
                'status': r['status'],
                'network_type': r['network_type'] or 'unclassified',
                **metrics,
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
            if allowed_prefix_ids is None:
                row = conn.execute(f'SELECT COUNT(*) as cnt FROM {table}').fetchone()
            elif not visible_ids:
                return 0
            elif table == 'ip_addresses':
                row = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM ip_addresses WHERE subnet_id IN ({', '.join(_PH for _ in visible_ids)})",
                    visible_ids,
                ).fetchone()
            elif table == 'ipam_pools':
                row = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM ipam_pools WHERE prefix_id IN ({', '.join(_PH for _ in visible_ids)})",
                    visible_ids,
                ).fetchone()
            elif table == 'ipam_vips':
                row = conn.execute(
                    f"SELECT COUNT(*) AS cnt FROM ipam_vips WHERE prefix_id IN ({', '.join(_PH for _ in visible_ids)})",
                    visible_ids,
                ).fetchone()
            elif table == 'ipam_dhcp_leases':
                row = conn.execute(
                    f"""SELECT COUNT(*) AS cnt
                          FROM ipam_dhcp_leases lease
                          JOIN ipam_pools pool ON pool.id = lease.pool_id
                         WHERE pool.prefix_id IN ({', '.join(_PH for _ in visible_ids)})""",
                    visible_ids,
                ).fetchone()
            else:
                # Only the fixed IPAM tables above have a supported relationship
                # to a visible Prefix. Unknown tables fail closed for scoped users.
                return 0
            return row['cnt'] if row else 0

        prefixes_count = len(scoped_rows)
        ips_count = _count('ip_addresses')
        pools_count = _count('ipam_pools')
        vips_count = _count('ipam_vips')
        leases_count = _count('ipam_dhcp_leases')

        registered_rate = round(used_ips_sum / total_ips_sum * 100, 1) if total_ips_sum > 0 else 0
        effective_rate = round(effective_used_ips_sum / total_ips_sum * 100, 1) if total_ips_sum > 0 else 0
        overview = {
            'prefixes_count': prefixes_count,
            'ips_count': ips_count,
            'pools_count': pools_count,
            'vips_count': vips_count,
            'leases_count': leases_count,
            'total_ips': total_ips_sum,
            'used_ips': used_ips_sum,
            'registered_ips': used_ips_sum,
            'reserved_ips': reserved_ips_sum,
            'effective_used_ips': effective_used_ips_sum,
            'allocatable_free_ips': allocatable_free_ips_sum,
            'free_ips': free_ips_sum,
            'utilization_rate': registered_rate,
            'registered_utilization_rate': registered_rate,
            'effective_utilization_rate': effective_rate,
            'capacity_prefixes_count': capacity_prefixes_count,
            'excluded_prefixes_count': excluded_prefixes_count,
            'scope_excluded_prefixes_count': scope_excluded_prefixes_count,
            'interconnect_prefixes_excluded_count': interconnect_prefixes_excluded_count,
            'network_scope': network_scope,
            'capacity_policy': f'{network_scope}_scope_excluding_non_allocatable_prefixes',
        }

        # ── Allocation trend for allocatable prefixes (cumulative, by created day) ───
        forecast_trend = []
        day_rows = conn.execute(
            '''SELECT ip.created_at, p.prefix, p.status AS prefix_status, p.network_type
               FROM ip_addresses ip
               JOIN prefixes p ON p.id = ip.subnet_id
               WHERE ip.created_at IS NOT NULL
                 AND COALESCE(ip.status, 'active') NOT IN ('released', 'available')''' +
            _allowed_prefix_filter(allowed_prefix_ids, column='p.id')[0] +
            ' ORDER BY ip.created_at',
            _allowed_prefix_filter(allowed_prefix_ids, column='p.id')[1],
        ).fetchall()
        day_counts: dict[str, int] = {}
        for dr in day_rows:
            created_at = str(dr['created_at'] or '')
            if len(created_at) < 10 or not _is_capacity_prefix(
                dr['prefix'] or '',
                dr['prefix_status'] or '',
            ):
                continue
            if network_scope == 'business' and not _is_business_utilization_network(
                dr['network_type'],
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
            'network_scope': network_scope,
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

@_with_read_scope_cache
def get_subnets_tree(allowed_prefix_ids: list[str] | None = None) -> list[dict]:
    """Build a hierarchy tree from parent_prefix_id relationships."""
    conn = get_db_connection()
    try:
        visible_sql, visible_params = _allowed_prefix_filter(allowed_prefix_ids)
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
            WHERE 1=1{visible_sql}
            ORDER BY p.prefix
        ''', visible_params).fetchall()

        nodes = {}
        for r in rows:
            item = dict(r)
            item.update(_calculate_prefix_capacity_metrics(conn, item))
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
) -> tuple[dict, str, str]:
    """Validate range containment and address-space-wide inclusive overlaps."""
    prefix_id = str(prefix_id or '').strip()
    if not prefix_id:
        raise ValueError('An IP pool must belong to a prefix')
    prefix_row = _select_prefix_for_update(conn, prefix_id)
    if not prefix_row:
        raise ValueError('The selected prefix does not exist')
    prefix_row = dict(prefix_row)
    address_space_id = str(prefix_row.get('address_space_id') or '').strip()
    tenant_id = str(prefix_row.get('tenant_id') or '').strip()
    if not address_space_id or not tenant_id:
        raise ValueError('Resolve the Prefix address space before creating or changing a Pool')
    try:
        network = ipaddress.ip_network(str(prefix_row['prefix']), strict=False)
        start_text = str(start_ip or '').strip()
        end_text = str(end_ip or '').strip()
        if '/' in start_text or '/' in end_text:
            raise ValueError('Pool endpoints must be host IPs without a CIDR prefix length')
        start = ipaddress.ip_address(start_text)
        end = ipaddress.ip_address(end_text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Invalid pool address range: {exc}') from exc
    if start.version != end.version or start.version != network.version:
        raise ValueError('Pool start, end, and prefix must use the same IP version')
    if int(start) > int(end):
        raise ValueError('Pool start address must not be greater than end address')
    if start not in network or end not in network:
        raise ValueError('Both pool endpoints must be inside the selected prefix')

    for pool in _pool_rows_for_address_space(conn, address_space_id, tenant_id):
        if str(pool.get('id')) == str(exclude_pool_id or ''):
            continue
        existing_version, existing_start, existing_end = _pool_range_integers(pool)
        if existing_version != start.version:
            continue
        if int(start) <= existing_end and existing_start <= int(end):
            raise ValueError(f'Pool range overlaps existing Pool {pool["id"]} in this address space')
    return prefix_row, str(start), str(end)


def _validate_pool_management_policy(management_mode: str, allocation_allowed: bool) -> tuple[str, bool]:
    mode = str(management_mode or '').strip().lower()
    if mode not in {'local_static', 'reserved', 'external_dhcp', 'external_other'}:
        raise ValueError('Pool management_mode must be local_static, reserved, external_dhcp, or external_other')
    if allocation_allowed is None:
        raise ValueError('Pool allocation_allowed must be explicit')
    allow_local = bool(allocation_allowed)
    if mode != 'local_static' and allow_local:
        raise ValueError('reserved and external pools must not allow local allocation')
    return mode, allow_local


def _lock_pool_prefixes(conn, prefix_ids: set[str]) -> dict[str, dict]:
    return _lock_prefixes_with_scopes(conn, prefix_ids)


def _lock_pool_scope_rows(conn, prefixes: list[dict]) -> None:
    scopes: dict[tuple[str, str, str], dict] = {}
    for prefix in prefixes:
        tenant_id = str(prefix.get('tenant_id') or 'tenant-default').strip()
        space_id = str(prefix.get('address_space_id') or '').strip()
        vrf_id = str(prefix.get('vrf_id') or '').strip()
        if not tenant_id:
            raise ValueError('Pool parent Prefix tenant is unknown')
        scopes[(tenant_id, space_id, vrf_id)] = prefix
    for (tenant_id, space_id, vrf_id), _ in sorted(
        scopes.items(), key=lambda item: f"{item[0][0]}:{item[0][1] or item[0][2]}"
    ):
        lock_ipam_scope(
            conn,
            security_tenant_id=tenant_id,
            address_space_id=space_id,
            vrf_id=vrf_id,
        )

def list_pools(
    *,
    q: str = '',
    status: str = '',
    prefix_id: str = '',
    page: int | None = None,
    page_size: int = 20,
    allowed_prefix_ids: list[str] | None = None,
) -> list[dict] | dict:
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
        if allowed_prefix_ids is not None:
            normalized_allowed = sorted({str(value or '').strip() for value in allowed_prefix_ids if str(value or '').strip()})
            if normalized_allowed:
                clauses.append(f"p.prefix_id IN ({_ph(len(normalized_allowed))})")
                params.extend(normalized_allowed)
            else:
                clauses.append('1 = 0')
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
            SELECT p.*, pf.prefix AS prefix_cidr, t.name AS tenant_name,
                   COALESCE(p.address_space_id, pf.address_space_id) AS resolved_address_space_id,
                   a.name AS address_space_name,
                   pf.tenant_id AS prefix_tenant_id
            FROM ipam_pools p
            LEFT JOIN prefixes pf ON p.prefix_id = pf.id
            LEFT JOIN tenants t ON p.tenant_id = t.id
            LEFT JOIN ipam_address_spaces a
                   ON a.id = COALESCE(p.address_space_id, pf.address_space_id)
            {where}
            ORDER BY p.name{page_clause}
        ''', tuple(params + page_params)).fetchall()

        pools_by_space: dict[str, list[dict]] = {}
        pools_by_prefix: dict[str, list[dict]] = {}
        used_by_pool: dict[str, set[str]] = {}
        for pool in (dict(row) for row in rows):
            pool_id_value = str(pool.get('id') or '')
            pool_id_prefix = str(pool.get('prefix_id') or '')
            pool_space = str(pool.get('resolved_address_space_id') or '').strip()
            used_by_pool[pool_id_value] = set()
            pools_by_prefix.setdefault(pool_id_prefix, []).append(pool)
            if pool_space:
                pools_by_space.setdefault(pool_space, []).append(pool)

        prefix_ids = sorted({prefix_id for prefix_id in pools_by_prefix if prefix_id})
        space_ids = sorted(pools_by_space)
        address_clauses = []
        address_params: list[str] = []
        if space_ids:
            address_clauses.append(f'ip.address_space_id IN ({_ph(len(space_ids))})')
            address_params.extend(space_ids)
        if prefix_ids:
            address_clauses.append(f'ip.subnet_id IN ({_ph(len(prefix_ids))})')
            address_params.extend(prefix_ids)
        if address_clauses:
            manual_rows = conn.execute(
                f"""SELECT ip.subnet_id, ip.address_space_id,
                           COALESCE(host(ip.address_inet), ip.address) AS address
                      FROM ip_addresses ip
                     WHERE ({' OR '.join(address_clauses)})
                       AND COALESCE(ip.status, 'active') NOT IN ('released', 'available')""",
                tuple(address_params),
            ).fetchall()
            for manual_row in manual_rows:
                address_space_id = str(manual_row['address_space_id'] or '').strip()
                subnet_id = str(manual_row['subnet_id'] or '')
                scope_pools = pools_by_space.get(address_space_id, []) if address_space_id else pools_by_prefix.get(subnet_id, [])
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
            p_dict['address_space_id'] = p_dict.get('resolved_address_space_id') or None
            p_dict['policy_pending'] = bool(
                not p_dict['address_space_id']
                or p_dict.get('management_mode') is None
                or p_dict.get('allocation_allowed') is None
            )
            
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
            p_dict['utilization'] = (
                100.0 if p_dict.get('mark_utilized') and total_ips > 0
                else round((used_ips / total_ips * 100), 1) if total_ips > 0
                else 0
            )
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
    management_mode: str,
    allocation_allowed: bool,
    mark_populated: bool = False,
    mark_utilized: bool = False,
    description: str = '',
    status: str = 'active',
    idempotency_key: str | None = None,
    audit_context: dict | None = None,
) -> dict:
    conn = get_db_connection()
    try:
        prefix_id = str(prefix_id or '').strip()
        mode, allow_local = _validate_pool_management_policy(management_mode, allocation_allowed)
        initial_prefix = _select_prefix_for_update(conn, prefix_id)
        if not initial_prefix:
            raise ValueError('The selected prefix does not exist')
        tenant_id = str(initial_prefix.get('tenant_id') or '').strip()
        address_space_id = str(initial_prefix.get('address_space_id') or '').strip()
        idempotency_payload = {
            'name': name, 'prefix_id': prefix_id, 'start_ip': str(start_ip),
            'end_ip': str(end_ip), 'management_mode': mode,
            'allocation_allowed': allow_local, 'mark_populated': bool(mark_populated),
            'mark_utilized': bool(mark_utilized), 'description': description,
            'status': status,
        }
        replay = _idempotency_replay(
            conn,
            tenant_id=tenant_id,
            operation='ipam.pool.create',
            idempotency_key=idempotency_key,
            payload=idempotency_payload,
        )
        if replay is not None:
            replay.pop('_idempotency_replay', None)
            conn.commit()
            return replay
        prefix, start_ip, end_ip = _validate_pool_range(
            conn, prefix_id=prefix_id, start_ip=start_ip, end_ip=end_ip,
        )
        tenant_id = str(prefix.get('tenant_id') or '').strip()
        address_space_id = str(prefix.get('address_space_id') or '').strip()
        candidate_pool = {
            'address_space_id': address_space_id,
            'management_mode': mode,
            'allocation_allowed': allow_local,
            'mark_populated': bool(mark_populated),
            'mark_utilized': bool(mark_utilized),
            'status': status,
        }
        if _pool_blocks_local_allocation(candidate_pool):
            _ensure_pool_policy_does_not_hide_active_addresses(
                conn, pool=candidate_pool, start_ip=start_ip, end_ip=end_ip,
            )
        pool_id = f"pool-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        conn.execute(
            f'''INSERT INTO ipam_pools
               (id, name, prefix_id, address_space_id, start_ip, end_ip, description, status,
                management_mode, allocation_allowed, mark_populated, mark_utilized, tenant_id,
                created_at, updated_at)
               VALUES ({_ph(15)})''',
            (pool_id, name, prefix_id, address_space_id, start_ip, end_ip, description, status,
             mode, allow_local, bool(mark_populated), bool(mark_utilized), tenant_id, now, now),
        )
        result = {
            'id': pool_id,
            'revision': 1,
            'address_space_id': address_space_id,
            'management_mode': mode,
            'allocation_allowed': allow_local,
            'mark_populated': bool(mark_populated),
            'mark_utilized': bool(mark_utilized),
            'policy_pending': False,
        }
        _store_idempotency_response(
            conn,
            tenant_id=tenant_id,
            operation='ipam.pool.create',
            idempotency_key=idempotency_key,
            payload=idempotency_payload,
            response=result,
            resource_type='ipam_pool',
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type='ipam.pool.create',
            severity='info',
            summary=f'Created IP Pool {name}',
            target_type='ipam_pool',
            target_id=pool_id,
            target_name=name,
            after=result,
            details={'prefix_id': prefix_id, 'address_space_id': address_space_id,
                     'management_mode': mode, 'allocation_allowed': allow_local,
                     'mark_populated': bool(mark_populated), 'mark_utilized': bool(mark_utilized)},
        )
        conn.commit()
        return result
    finally:
        conn.close()


def update_pool(pool_id: str, *, audit_context: dict | None = None, **fields) -> bool:
    conn = get_db_connection()
    try:
        expected_revision = fields.pop('expected_revision', None)
        initial = conn.execute(
            f'SELECT * FROM ipam_pools WHERE id = {_PH}', (pool_id,)
        ).fetchone()
        if not initial:
            return False
        initial = dict(initial)
        fields = dict(fields)
        target_prefix_id = str(fields.get('prefix_id') or initial['prefix_id'] or '').strip()
        locked_prefixes = _lock_pool_prefixes(
            conn, {str(initial['prefix_id'] or ''), target_prefix_id},
        )
        old_prefix = locked_prefixes[str(initial['prefix_id'])]
        target_prefix = locked_prefixes[target_prefix_id]
        old_space_id = str(old_prefix.get('address_space_id') or '').strip()
        target_space_id = str(target_prefix.get('address_space_id') or '').strip()
        initial_pool_space = str(initial.get('address_space_id') or '').strip()
        if initial_pool_space and initial_pool_space != old_space_id:
            raise ValueError('Pool address space conflicts with its parent Prefix')
        if target_prefix_id != str(initial['prefix_id']) and old_space_id != target_space_id:
            raise ValueError('Moving a Pool between address spaces requires an explicit mapping preview')
        _lock_pool_scope_rows(conn, [old_prefix, target_prefix])
        row = conn.execute(
            f'SELECT * FROM ipam_pools WHERE id = {_PH} FOR UPDATE', (pool_id,)
        ).fetchone()
        if not row:
            return False
        row = dict(row)
        if int(row.get('revision') or 1) != int(initial.get('revision') or 1):
            raise ValueError('Pool changed during update; refresh and retry')
        if expected_revision is not None and int(row.get('revision') or 1) != int(expected_revision):
            raise ValueError('Pool revision is stale; refresh and retry')

        policy_fields = {'management_mode', 'allocation_allowed'}
        if policy_fields.intersection(fields) and not policy_fields.issubset(fields):
            raise ValueError('Update management_mode and allocation_allowed together')
        current_mode = fields.get('management_mode', row.get('management_mode'))
        current_allowed = fields.get('allocation_allowed', row.get('allocation_allowed'))
        policy_changed = bool(
            policy_fields.intersection(fields)
            or {'mark_populated', 'mark_utilized'}.intersection(fields)
        )
        if policy_fields.intersection(fields):
            current_mode, current_allowed = _validate_pool_management_policy(
                current_mode, current_allowed,
            )
            fields['management_mode'] = current_mode
            fields['allocation_allowed'] = current_allowed

        range_changed = any(name in fields for name in ('prefix_id', 'start_ip', 'end_ip'))
        scope_revalidation_required = range_changed or policy_changed or 'status' in fields
        target_space_id = str(target_prefix.get('address_space_id') or '').strip()
        if scope_revalidation_required and not target_space_id:
            raise ValueError('Resolve the Prefix address space before confirming a Pool policy or range')
        stored_space_id = str(row.get('address_space_id') or '').strip()
        if target_space_id and stored_space_id and stored_space_id != target_space_id:
            raise ValueError('Pool address space conflicts with its parent Prefix')
        target_start = fields.get('start_ip', row['start_ip'])
        target_end = fields.get('end_ip', row['end_ip'])
        if scope_revalidation_required:
            target_prefix, target_start, target_end = _validate_pool_range(
                conn,
                prefix_id=target_prefix_id,
                start_ip=target_start,
                end_ip=target_end,
                exclude_pool_id=pool_id,
            )
            fields.update({
                'prefix_id': target_prefix_id,
                'address_space_id': str(target_prefix['address_space_id']),
                'start_ip': target_start,
                'end_ip': target_end,
            })
        elif target_prefix_id != str(row['prefix_id'] or ''):
            raise ValueError('Pool prefix update requires range validation')

        if scope_revalidation_required:
            proposed_pool = dict(row)
            proposed_pool.update(fields)
            proposed_pool['address_space_id'] = (
                str(target_prefix.get('address_space_id') or '').strip()
                or str(row.get('address_space_id') or '').strip()
            )
            old_allocatable = (
                str(row.get('status') or '').strip().lower() == 'active'
                and str(row.get('management_mode') or '').strip().lower() == 'local_static'
                and row.get('allocation_allowed') is True
                and not bool(row.get('mark_populated'))
            )
            new_blocked = _pool_blocks_local_allocation(proposed_pool)
            populating_now = not bool(row.get('mark_populated')) and bool(proposed_pool.get('mark_populated'))
            if new_blocked and (old_allocatable or populating_now or range_changed):
                _ensure_pool_policy_does_not_hide_active_addresses(
                    conn,
                    pool=proposed_pool,
                    start_ip=str(proposed_pool.get('start_ip') or ''),
                    end_ip=str(proposed_pool.get('end_ip') or ''),
                )

        if not fields:
            return True
        updates = []
        params = []
        allowed_fields = (
            'name', 'prefix_id', 'address_space_id', 'start_ip', 'end_ip', 'description', 'status',
            'management_mode', 'allocation_allowed', 'mark_populated', 'mark_utilized',
        )
        for f in allowed_fields:
            val = fields.get(f)
            if val is not None:
                updates.append(f'{f} = {_PH}')
                params.append(val)
        if updates:
            updates.append(f'updated_at = {_PH}')
            params.append(_utc_now())
            updates.append('revision = revision + 1')
            params.append(pool_id)
            conn.execute(
                f"UPDATE ipam_pools SET {', '.join(updates)} WHERE id = {_PH}",
                tuple(params),
            )
            after = conn.execute(
                f'SELECT * FROM ipam_pools WHERE id = {_PH}', (pool_id,)
            ).fetchone()
            _write_ipam_audit(
                conn,
                audit_context,
                event_type='ipam.pool.update',
                severity='info',
                summary=f'Updated IP Pool {pool_id}',
                target_type='ipam_pool',
                target_id=pool_id,
                before=row,
                after=dict(after) if after else {},
                details={key: value for key, value in fields.items() if key != 'expected_revision'},
            )
            conn.commit()
        return True
    finally:
        conn.close()


def delete_pool(
    pool_id: str,
    *,
    expected_revision: int | None = None,
    audit_context: dict | None = None,
) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT id, prefix_id, revision FROM ipam_pools WHERE id = {_PH}', (pool_id,)
        ).fetchone()
        if not row:
            return False
        initial = dict(row)
        prefix = _lock_pool_prefixes(conn, {str(initial['prefix_id'] or '')})[str(initial['prefix_id'])]
        _lock_pool_scope_rows(conn, [prefix])
        locked_row = conn.execute(
            f'SELECT * FROM ipam_pools WHERE id = {_PH} FOR UPDATE',
            (pool_id,),
        ).fetchone()
        if not locked_row:
            return False
        if (
            str(locked_row['prefix_id'] or '') != str(initial['prefix_id'] or '')
            or int(locked_row['revision'] or 1) != int(initial['revision'] or 1)
        ):
            raise ValueError('Pool changed during deletion; refresh and retry')
        if expected_revision is not None and int(locked_row['revision'] or 1) != int(expected_revision):
            raise ValueError('Pool revision is stale; refresh and retry')
        assigned = conn.execute(
            'SELECT id FROM ip_addresses WHERE pool_id = ? ORDER BY id LIMIT 1',
            (pool_id,),
        ).fetchone()
        if assigned:
            raise ValueError('Pool has explicitly assigned IP addresses; clear those assignments before deleting it')
        conn.execute(f'DELETE FROM ipam_pools WHERE id = {_PH}', (pool_id,))
        _write_ipam_audit(
            conn,
            audit_context,
            event_type='ipam.pool.delete',
            severity='warning',
            summary=f'Deleted IP Pool {pool_id}',
            target_type='ipam_pool',
            target_id=pool_id,
            before=dict(locked_row),
            after={},
        )
        conn.commit()
        return True
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# VIP CRUD
# ══════════════════════════════════════════════════════════

def list_vips(
    *,
    q: str = '',
    vip_type: str = '',
    status: str = '',
    prefix_id: str = '',
    page: int | None = None,
    page_size: int = 20,
    allowed_prefix_ids: list[str] | None = None,
    allowed_pending_tenant_ids: list[str] | None = None,
) -> list[dict] | dict:
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
                f"SELECT prefix, address_space_id FROM prefixes WHERE id = {_PH}",
                (prefix_id.strip(),),
            ).fetchone()
            if not prefix_row:
                return _empty_ipam_page(page=page, page_size=page_size)
            address_space_id = str(prefix_row['address_space_id'] or '').strip()
            if not address_space_id:
                return _empty_ipam_page(page=page, page_size=page_size)
            try:
                network = ipaddress.ip_network(str(prefix_row['prefix']), strict=False)
            except (KeyError, TypeError, ValueError):
                return _empty_ipam_page(page=page, page_size=page_size)
            clauses.append('vip.address_space_id = ?')
            params.append(address_space_id)
            clauses.append('vip.address_inet <<= CAST(? AS cidr)')
            params.append(str(network))
        if allowed_prefix_ids is not None:
            normalized_prefix_ids = sorted({str(value or '').strip() for value in allowed_prefix_ids if str(value or '').strip()})
            visible_scope_clauses: list[str] = []
            if normalized_prefix_ids:
                visible_scope_clauses.append(f"vip.prefix_id IN ({_ph(len(normalized_prefix_ids))})")
                params.extend(normalized_prefix_ids)
            normalized_pending_tenants = sorted({
                str(value or '').strip()
                for value in (allowed_pending_tenant_ids or [])
                if str(value or '').strip()
            })
            if normalized_pending_tenants:
                visible_scope_clauses.append(
                    f"(vip.prefix_id IS NULL AND vip.address_space_id IS NULL "
                    f"AND COALESCE(vip.tenant_id, 'tenant-default') IN ({_ph(len(normalized_pending_tenants))}))"
                )
                params.extend(normalized_pending_tenants)
            if not visible_scope_clauses:
                clauses.append('1 = 0')
            else:
                clauses.append(f"({' OR '.join(visible_scope_clauses)})")
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
                   t.name AS tenant_name,
                   p.prefix AS prefix_cidr, p.name AS prefix_name,
                   spaces.name AS address_space_name
            FROM ipam_vips vip
            LEFT JOIN devices d ON vip.device_id = d.id
            LEFT JOIN devices bd ON vip.backup_device_id = bd.id
            LEFT JOIN tenants t ON vip.tenant_id = t.id
            LEFT JOIN prefixes p ON vip.prefix_id = p.id
            LEFT JOIN ipam_address_spaces spaces ON spaces.id = vip.address_space_id
            {where}
            ORDER BY vip.address{page_clause}
        ''', tuple(params + page_params)).fetchall()
        items = [dict(r) for r in rows]
        for item in items:
            item['scope_pending'] = not bool(item.get('address_space_id') and item.get('prefix_id'))
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


def _validate_vip_prefix_scope(conn, *, prefix_id: str, address: str) -> dict:
    """Resolve a VIP's address space only from its explicitly selected Prefix."""
    prefix_id = str(prefix_id or '').strip()
    if not prefix_id:
        raise ValueError('Select an explicitly scoped Prefix for this VIP')
    row = conn.execute(
        f"SELECT * FROM prefixes WHERE id = {_PH}", (prefix_id,)
    ).fetchone()
    if not row:
        raise ValueError('Selected prefix was not found')
    prefix = dict(row)
    tenant_id = str(prefix.get('tenant_id') or '').strip()
    address_space_id = str(prefix.get('address_space_id') or '').strip()
    if not tenant_id or not address_space_id:
        raise ValueError('Resolve the Prefix address space before creating or moving a VIP')
    try:
        network = ipaddress.ip_network(str(prefix.get('prefix') or ''), strict=False)
        host = _normalize_host_address(address)
        ip_address = ipaddress.ip_address(host)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Selected Prefix or VIP host address is invalid') from exc
    if ip_address.version != network.version or ip_address not in network:
        raise ValueError(f'VIP {host} is outside selected Prefix {network}')
    prefix['tenant_id'] = tenant_id
    prefix['address_space_id'] = address_space_id
    prefix['normalized_vip_address'] = host
    return prefix


def _lock_vip_prefix_scopes(
    conn,
    prefix_ids: set[str],
    *,
    extra_scopes: set[tuple[str, str, str]] | None = None,
) -> dict[str, dict]:
    prefixes = _lock_prefixes_with_scopes(
        conn,
        prefix_ids,
        extra_scopes=extra_scopes,
    )
    if any(
        not str(prefix.get('tenant_id') or '').strip()
        or not str(prefix.get('address_space_id') or '').strip()
        for prefix in prefixes.values()
    ):
        raise ValueError('Resolve the Prefix address space before changing a scoped VIP')
    return prefixes


def _fhrp_vip_group_scopes(conn, vip_id: str) -> set[tuple[str, str, str]]:
    rows = conn.execute(
        """
        SELECT group_row.security_tenant_id, group_row.address_space_id
          FROM ipam_fhrp_group_vips relation
          JOIN ipam_fhrp_groups group_row ON group_row.id = relation.group_id
         WHERE relation.vip_id = ?
        """,
        (vip_id,),
    ).fetchall()
    return {
        (
            str(row['security_tenant_id'] or 'tenant-default').strip() or 'tenant-default',
            str(row['address_space_id'] or '').strip(),
            '',
        )
        for row in rows
    }


def _validate_vip_fhrp_group_update(conn, vip_id: str, current: dict, fields: dict) -> None:
    groups = conn.execute(
        """
        SELECT group_row.id, group_row.security_tenant_id,
               group_row.address_space_id, group_row.protocol,
               group_row.address_family
          FROM ipam_fhrp_group_vips relation
          JOIN ipam_fhrp_groups group_row ON group_row.id = relation.group_id
         WHERE relation.vip_id = ?
         FOR UPDATE OF group_row
        """,
        (vip_id,),
    ).fetchall()
    if len(groups) > 1:
        raise ValueError('VIP is linked to more than one FHRP or Anycast group')
    for group in groups:
        target_address_space = fields.get('address_space_id', current.get('address_space_id'))
        target_tenant = fields.get('tenant_id', current.get('tenant_id'))
        target_protocol = fields.get('vip_type', current.get('vip_type'))
        target_address = (
            fields.get('address_inet')
            or fields.get('address')
            or current.get('address_inet')
            or current.get('address')
        )
        try:
            target_family = ipaddress.ip_address(str(target_address)).version
        except (TypeError, ValueError) as exc:
            raise ValueError('An FHRP-linked VIP must retain a valid host address') from exc

        tenant_key = str(target_tenant or 'tenant-default').strip() or 'tenant-default'
        if str(target_address_space or '') != str(group['address_space_id']):
            raise ValueError('An FHRP-linked VIP must remain in the group address space')
        if tenant_key != str(group['security_tenant_id']):
            raise ValueError('An FHRP-linked VIP must remain in the group security tenant')
        if str(target_protocol or '').strip().lower() != str(group['protocol']).strip().lower():
            raise ValueError('VIP protocol must match its FHRP or Anycast group')
        if int(target_family) != int(group['address_family']):
            raise ValueError('VIP address family must match its FHRP or Anycast group')
        target_status = str(fields.get('status', current.get('status') or 'active')).strip().lower()
        if target_status in {'released', 'deprecated', 'disabled'}:
            raise ValueError(
                'Cannot deactivate a VIP while it is linked to an FHRP or Anycast group; detach it first'
            )


def _validate_vip_conflicts(
    conn,
    prefix: dict,
    address: str,
    *,
    exclude_vip_id: str = '',
) -> None:
    space_id = str(prefix.get('address_space_id') or '').strip()
    tenant_id = str(prefix.get('tenant_id') or 'tenant-default')
    if not space_id:
        raise ValueError('Resolve the Prefix address space before creating a VIP')
    ip_conflict = conn.execute(
        """SELECT ip.id FROM ip_addresses ip
             LEFT JOIN prefixes owner ON owner.id = ip.subnet_id
            WHERE (
                    ip.address_space_id = ?
                    OR (ip.address_space_id IS NULL AND owner.address_space_id = ?)
                  )
              AND COALESCE(ip.status, 'active') NOT IN ('released', 'available')
              AND COALESCE(host(ip.address_inet), ip.address) = ?
            LIMIT 1""",
        (space_id, space_id, address),
    ).fetchone()
    if ip_conflict:
        raise ValueError(f'VIP {address} conflicts with an allocated IP in this address space')

    vip_params: list = [space_id, address]
    exclude_sql = ''
    if exclude_vip_id:
        exclude_sql = f' AND id <> {_PH}'
        vip_params.append(exclude_vip_id)
    vip_conflict = conn.execute(
        f"""SELECT id FROM ipam_vips
             WHERE address_space_id = {_PH}
               AND address_inet = CAST({_PH} AS inet)
               AND COALESCE(status, 'active') NOT IN ('released', 'deprecated', 'disabled')
               {exclude_sql}
             LIMIT 1""",
        tuple(vip_params),
    ).fetchone()
    if vip_conflict:
        raise ValueError(f'VIP {address} is already registered in this address space')

    _validate_address_space_gateway_policy(
        conn,
        prefix,
        address,
        device_type='gateway' if _configured_prefix_gateway(prefix) == address else '',
        purpose='',
    )
    _validate_pool_address_policy(conn, prefix, address)


def _validate_vip_controller_devices(device_id: str | None, backup_device_id: str | None) -> None:
    primary = str(device_id or '').strip()
    standby = str(backup_device_id or '').strip()
    if primary and standby and primary.casefold() == standby.casefold():
        raise ValueError('VIP primary and backup devices must be different')


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
    tenant_id: str | None = None,
    prefix_id: str | None = None,
    idempotency_key: str | None = None,
    audit_context: dict | None = None,
) -> dict:
    _validate_vip_controller_devices(device_id, backup_device_id)
    address = _normalize_host_address(address)
    conn = get_db_connection()
    try:
        prefix = _validate_vip_prefix_scope(conn, prefix_id=prefix_id or '', address=address)
        if tenant_id and str(tenant_id).strip() != str(prefix['tenant_id']):
            raise ValueError('VIP tenant must match the selected Prefix tenant')
        prefix = _lock_vip_prefix_scopes(conn, {str(prefix['id'])})[str(prefix['id'])]
        tenant_key = str(prefix.get('tenant_id') or 'tenant-default').strip() or 'tenant-default'
        idempotency_payload = {
            'address': address, 'vip_type': vip_type, 'device_id': device_id or '',
            'backup_device_id': backup_device_id or '', 'interface_name': interface_name,
            'description': description, 'real_servers': real_servers,
            'status': status, 'prefix_id': str(prefix['id']),
        }
        replay = _idempotency_replay(
            conn,
            tenant_id=tenant_key,
            operation='ipam.vip.create',
            idempotency_key=idempotency_key,
            payload=idempotency_payload,
        )
        if replay is not None:
            replay.pop('_idempotency_replay', None)
            conn.commit()
            return replay
        prefix = _validate_vip_prefix_scope(
            conn, prefix_id=str(prefix['id']), address=address,
        )
        if str(status or 'active').strip().lower() not in {'released', 'deprecated', 'disabled'}:
            _validate_vip_conflicts(conn, prefix, address)
        vip_id = f"vip-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        conn.execute(
            f'''INSERT INTO ipam_vips
               (id, address, address_inet, prefix_id, address_space_id,
                vip_type, device_id, backup_device_id, interface_name,
                description, real_servers, status, tenant_id, created_at, updated_at)
               VALUES ({_ph(15)})''',
            (
                vip_id, address, address, prefix['id'], prefix['address_space_id'],
                vip_type, device_id or None, backup_device_id or None, interface_name,
                description, real_servers, status, prefix['tenant_id'], now, now,
            ),
        )
        response = conn.execute(
            f'''SELECT vip.*, prefix.prefix AS prefix_cidr,
                       prefix.name AS prefix_name, spaces.name AS address_space_name
                  FROM ipam_vips vip
                  JOIN prefixes prefix ON prefix.id = vip.prefix_id
                  LEFT JOIN ipam_address_spaces spaces ON spaces.id = vip.address_space_id
                 WHERE vip.id = {_PH}''',
            (vip_id,),
        ).fetchone()
        result = dict(response) if response else {'id': vip_id, 'address': address}
        result['scope_pending'] = not bool(result.get('address_space_id') and result.get('prefix_id'))
        result['scope_status'] = 'scope_pending' if result['scope_pending'] else 'scope_resolved'
        _store_idempotency_response(
            conn,
            tenant_id=tenant_key,
            operation='ipam.vip.create',
            idempotency_key=idempotency_key,
            payload=idempotency_payload,
            response=result,
            resource_type='ipam_vip',
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type='ipam.vip.create',
            severity='info',
            summary=f'Created VIP {address}',
            target_type='ipam_vip',
            target_id=vip_id,
            target_name=address,
            after=result,
            details={'prefix_id': prefix['id'], 'address_space_id': prefix['address_space_id']},
        )
        conn.commit()
        return result
    finally:
        conn.close()


def update_vip(vip_id: str, *, audit_context: dict | None = None, **fields) -> bool:
    conn = get_db_connection()
    try:
        expected_revision = fields.pop('expected_revision', None)
        initial = conn.execute(
            f'SELECT * FROM ipam_vips WHERE id = {_PH}', (vip_id,)
        ).fetchone()
        if not initial:
            return False
        initial = dict(initial)
        fields = dict(fields)
        fields.pop('tenant_id', None)
        _validate_vip_controller_devices(
            fields.get('device_id') if fields.get('device_id') is not None else initial.get('device_id'),
            fields.get('backup_device_id') if fields.get('backup_device_id') is not None else initial.get('backup_device_id'),
        )
        old_prefix_id = str(initial.get('prefix_id') or '').strip()
        target_prefix_id = str(fields.get('prefix_id') or old_prefix_id).strip()
        fhrp_group_scopes = _fhrp_vip_group_scopes(conn, vip_id)
        _lock_vip_prefix_scopes(
            conn,
            {old_prefix_id, target_prefix_id},
            extra_scopes=fhrp_group_scopes,
        )
        target_prefix = None
        if not target_prefix_id:
            if 'address' in fields or 'prefix_id' in fields:
                raise ValueError('Select an explicitly scoped Prefix before changing a legacy pending VIP')
            row = conn.execute(
                f'SELECT * FROM ipam_vips WHERE id = {_PH} FOR UPDATE', (vip_id,)
            ).fetchone()
            if not row:
                return False
            row = dict(row)
            if int(row.get('revision') or 1) != int(initial.get('revision') or 1):
                raise ValueError('VIP changed during update; refresh and retry')
            if expected_revision is not None and int(row.get('revision') or 1) != int(expected_revision):
                raise ValueError('VIP revision is stale; refresh and retry')
        else:
            row = conn.execute(
                f'SELECT * FROM ipam_vips WHERE id = {_PH} FOR UPDATE', (vip_id,)
            ).fetchone()
            if not row:
                return False
            row = dict(row)
            if (
                int(row.get('revision') or 1) != int(initial.get('revision') or 1)
                or str(row.get('prefix_id') or '') != old_prefix_id
            ):
                raise ValueError('VIP changed during update; refresh and retry')
            if expected_revision is not None and int(row.get('revision') or 1) != int(expected_revision):
                raise ValueError('VIP revision is stale; refresh and retry')
            target_prefix = _validate_vip_prefix_scope(
                conn,
                prefix_id=target_prefix_id,
                address=_normalize_host_address(fields.get('address') or row['address']),
            )
            fields['address'] = target_prefix['normalized_vip_address']
            fields['prefix_id'] = target_prefix_id
            fields['address_space_id'] = target_prefix['address_space_id']
            fields['address_inet'] = fields['address']
            fields['tenant_id'] = target_prefix['tenant_id']
            resulting_status = str(fields.get('status', row.get('status') or 'active')).strip().lower()
            if resulting_status not in {'released', 'deprecated', 'disabled'}:
                _validate_vip_conflicts(
                    conn, target_prefix, fields['address'], exclude_vip_id=vip_id,
                )
        _validate_vip_fhrp_group_update(conn, vip_id, row, fields)
        updates = []
        params = []
        for f in ('address', 'address_inet', 'prefix_id', 'address_space_id',
                  'vip_type', 'device_id', 'backup_device_id', 'interface_name',
                  'description', 'real_servers', 'status', 'tenant_id'):
            val = fields.get(f)
            if f in {'device_id', 'backup_device_id'} and isinstance(val, str) and not val.strip():
                updates.append(f'{f} = NULL')
                continue
            if val is not None:
                updates.append(f'{f} = {_PH}')
                params.append(val)
        if updates:
            updates.append(f'updated_at = {_PH}')
            params.append(_utc_now())
            updates.append('revision = revision + 1')
            params.append(vip_id)
            conn.execute(
                f"UPDATE ipam_vips SET {', '.join(updates)} WHERE id = {_PH}",
                tuple(params),
            )
            after = conn.execute(
                f'SELECT * FROM ipam_vips WHERE id = {_PH}', (vip_id,)
            ).fetchone()
            _write_ipam_audit(
                conn,
                audit_context,
                event_type='ipam.vip.update',
                severity='info',
                summary=f'Updated VIP {vip_id}',
                target_type='ipam_vip',
                target_id=vip_id,
                before=dict(row),
                after=dict(after) if after else {},
                details={key: value for key, value in fields.items() if key != 'expected_revision'},
            )
            conn.commit()
        return True
    finally:
        conn.close()


def delete_vip(
    vip_id: str,
    *,
    expected_revision: int | None = None,
    audit_context: dict | None = None,
) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT id, prefix_id, revision FROM ipam_vips WHERE id = {_PH}', (vip_id,)
        ).fetchone()
        if not row:
            return False
        initial = dict(row)
        prefix_id = str(initial.get('prefix_id') or '').strip()
        fhrp_group_scopes = _fhrp_vip_group_scopes(conn, vip_id)
        if prefix_id:
            _lock_vip_prefix_scopes(
                conn,
                {prefix_id},
                extra_scopes=fhrp_group_scopes,
            )
        elif fhrp_group_scopes:
            _lock_vip_prefix_scopes(
                conn,
                set(),
                extra_scopes=fhrp_group_scopes,
            )
        locked = conn.execute(
            f'SELECT * FROM ipam_vips WHERE id = {_PH} FOR UPDATE',
            (vip_id,),
        ).fetchone()
        if not locked:
            return False
        if (
            str(locked['prefix_id'] or '') != prefix_id
            or int(locked['revision'] or 1) != int(initial.get('revision') or 1)
        ):
            raise ValueError('VIP changed during deletion; refresh and retry')
        if expected_revision is not None and int(locked['revision'] or 1) != int(expected_revision):
            raise ValueError('VIP revision is stale; refresh and retry')
        linked_group = conn.execute(
            'SELECT 1 FROM ipam_fhrp_group_vips WHERE vip_id = ? LIMIT 1',
            (vip_id,),
        ).fetchone()
        if linked_group:
            raise ValueError(
                'Cannot delete a VIP while it is linked to an FHRP or Anycast group; detach it first'
            )
        conn.execute(f'DELETE FROM ipam_vips WHERE id = {_PH}', (vip_id,))
        _write_ipam_audit(
            conn,
            audit_context,
            event_type='ipam.vip.delete',
            severity='warning',
            summary=f'Deleted VIP {vip_id}',
            target_type='ipam_vip',
            target_id=vip_id,
            before=dict(locked),
            after={},
        )
        conn.commit()
        return True
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# DHCP Lease CRUD
# ══════════════════════════════════════════════════════════

def _lock_lease_external_identity(conn, tenant_id: str, dhcp_server: str, external_id: str) -> None:
    """Serialize idempotent lease writes by source identity, never by raw IP."""
    key = f"ipam-lease:{tenant_id}:{dhcp_server.strip().lower()}:{external_id.strip()}"
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', (key,))


def _lock_external_dhcp_pool_for_lease(
    conn,
    *,
    pool_id: str,
    address: str,
    tenant_id: str,
) -> dict:
    """Resolve a lease's scope only through an active external-DHCP Pool."""
    pool_id = str(pool_id or '').strip()
    initial = conn.execute(
        'SELECT id, prefix_id FROM ipam_pools WHERE id = ?', (pool_id,)
    ).fetchone()
    if not initial:
        raise ValueError('Selected external DHCP Pool was not found')
    prefix_id = str(initial['prefix_id'] or '').strip()
    prefix = _select_prefix_for_update(conn, prefix_id)
    if not prefix:
        raise ValueError('Selected Pool Prefix was not found')
    prefix = dict(prefix)
    prefix_tenant = str(prefix.get('tenant_id') or 'tenant-default').strip()
    prefix_space = str(prefix.get('address_space_id') or '').strip()
    if prefix_tenant != str(tenant_id or 'tenant-default').strip():
        raise ValueError('Lease tenant must match the selected external DHCP Pool tenant')
    if not prefix_space:
        raise ValueError('Resolve the Pool Prefix address space before recording a scoped lease')
    pool_row = conn.execute(
        f'SELECT * FROM ipam_pools WHERE id = {_PH} FOR UPDATE', (pool_id,)
    ).fetchone()
    if not pool_row:
        raise ValueError('Selected external DHCP Pool was not found')
    pool = dict(pool_row)
    if str(pool.get('address_space_id') or '').strip() != prefix_space:
        raise ValueError('Selected Pool address space does not match its Prefix')
    if str(pool.get('tenant_id') or 'tenant-default').strip() != prefix_tenant:
        raise ValueError('Selected Pool tenant does not match its Prefix')
    if str(pool.get('status') or 'active').strip().lower() != 'active':
        raise ValueError('Selected external DHCP Pool is not active')
    if _pool_is_policy_pending(pool):
        raise ValueError('Selected external DHCP Pool policy is pending confirmation')
    if str(pool.get('management_mode') or '').strip().lower() != 'external_dhcp':
        raise ValueError('A DHCP lease must reference an external_dhcp Pool')
    if bool(pool.get('allocation_allowed')):
        raise ValueError('External DHCP Pool cannot allow local static allocation')
    version, start, end = _pool_range_integers(pool)
    parsed = ipaddress.ip_address(address)
    if parsed.version != version or not start <= int(parsed) <= end:
        raise ValueError('DHCP lease address is outside the selected external DHCP Pool')
    pool['address_space_id'] = prefix_space
    pool['tenant_id'] = prefix_tenant
    return pool

def _parse_lease_timestamp(value: str | None) -> datetime | None:
    text = str(value or '').strip()
    if not text:
        return None
    normalized = text.replace('Z', '+00:00')
    if ' ' in normalized and 'T' not in normalized:
        normalized = normalized.replace(' ', 'T', 1)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _annotate_lease_effective_state(item: dict, now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    source_state = str(item.get('lease_state') or 'active').strip().lower() or 'active'
    lease_end_dt = _parse_lease_timestamp(item.get('lease_end'))
    is_expired = lease_end_dt is not None and lease_end_dt <= current
    if source_state in ('expired', 'released', 'revoked', 'inactive'):
        effective_state = source_state
    elif is_expired:
        effective_state = 'expired'
    else:
        effective_state = source_state
    item['source_lease_state'] = source_state
    item['effective_state'] = effective_state
    item['is_expired'] = is_expired or effective_state == 'expired'
    item['scope_pending'] = not bool(item.get('address_space_id') and item.get('pool_id'))
    item['blocks_local_allocation'] = bool(item.get('pool_id') and item.get('address_space_id'))
    return item


def list_leases(
    *,
    q: str = '',
    state: str = '',
    page: int | None = None,
    page_size: int = 20,
    tenant_id: str | None = None,
    allowed_pool_ids: list[str] | None = None,
    allowed_unscoped_tenant_ids: list[str] | None = None,
    include_unscoped_tenant: bool = True,
) -> list[dict] | dict:
    conn = get_db_connection()
    try:
        clauses: list[str] = []
        params: list[str] = []
        if q.strip():
            clauses.append("(LOWER(lease.address) LIKE ? OR LOWER(COALESCE(lease.mac_address, '')) LIKE ? OR LOWER(COALESCE(lease.hostname, '')) LIKE ? OR LOWER(COALESCE(lease.dhcp_server, '')) LIKE ?)")
            fuzzy = f"%{q.strip().lower()}%"
            params.extend([fuzzy] * 4)
        requested_state = str(state or '').strip().lower()
        if allowed_pool_ids is not None:
            normalized_pool_ids = sorted({str(value or '').strip() for value in allowed_pool_ids if str(value or '').strip()})
            scope_clauses: list[str] = []
            if normalized_pool_ids:
                scope_clauses.append(f"lease.pool_id IN ({_ph(len(normalized_pool_ids))})")
                params.extend(normalized_pool_ids)
            normalized_pending_tenants = sorted({
                str(value or '').strip()
                for value in (allowed_unscoped_tenant_ids or [])
                if str(value or '').strip()
            })
            if include_unscoped_tenant and normalized_pending_tenants:
                scope_clauses.append(
                    f"(lease.pool_id IS NULL AND lease.address_space_id IS NULL "
                    f"AND COALESCE(lease.tenant_id, 'tenant-default') IN ({_ph(len(normalized_pending_tenants))}))"
                )
                params.extend(normalized_pending_tenants)
            elif include_unscoped_tenant and tenant_id:
                scope_clauses.append("(lease.pool_id IS NULL AND COALESCE(lease.tenant_id, 'tenant-default') = ?)")
                params.append(str(tenant_id))
            elif include_unscoped_tenant and tenant_id is None and allowed_unscoped_tenant_ids is None:
                scope_clauses.append('lease.pool_id IS NULL')
            clauses.append(f"({' OR '.join(scope_clauses)})" if scope_clauses else '1 = 0')
        elif tenant_id:
            clauses.append("COALESCE(lease.tenant_id, 'tenant-default') = ?")
            params.append(str(tenant_id))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        rows = conn.execute(f'''SELECT lease.*, pool.name AS pool_name,
                                       spaces.name AS address_space_name,
                                       prefix.prefix AS pool_prefix
                                  FROM ipam_dhcp_leases lease
                                  LEFT JOIN ipam_pools pool ON pool.id = lease.pool_id
                                  LEFT JOIN ipam_address_spaces spaces ON spaces.id = lease.address_space_id
                                  LEFT JOIN prefixes prefix ON prefix.id = pool.prefix_id
                                  {where}
                                 ORDER BY lease.address''',
                            tuple(params)).fetchall()
        now = datetime.now(timezone.utc)
        items = [_annotate_lease_effective_state(dict(row), now) for row in rows]
        if requested_state and requested_state != 'all':
            items = [item for item in items if item['effective_state'] == requested_state]
        total = len(items)
        if page is None:
            return items
        safe_page = max(int(page or 1), 1)
        safe_page_size = min(max(int(page_size or 20), 1), 100)
        start = (safe_page - 1) * safe_page_size
        paged_items = items[start:start + safe_page_size]
        return {'items': paged_items, 'total': total, 'page': safe_page, 'page_size': safe_page_size, 'total_pages': max(1, (total + safe_page_size - 1) // safe_page_size)}
    finally:
        conn.close()


def _lease_response(conn, lease_id: str) -> dict:
    row = conn.execute(
        f'''SELECT lease.*, pool.name AS pool_name,
                   spaces.name AS address_space_name,
                   prefix.prefix AS pool_prefix
              FROM ipam_dhcp_leases lease
              LEFT JOIN ipam_pools pool ON pool.id = lease.pool_id
              LEFT JOIN ipam_address_spaces spaces ON spaces.id = lease.address_space_id
              LEFT JOIN prefixes prefix ON prefix.id = pool.prefix_id
             WHERE lease.id = {_PH}''',
        (lease_id,),
    ).fetchone()
    result = dict(row) if row else {'id': lease_id}
    _annotate_lease_effective_state(result)
    result['scope_status'] = str(
        result.get('scope_status') or ('scope_pending' if result['scope_pending'] else 'scope_resolved')
    )
    return result


def create_lease(
    *,
    address: str,
    mac_address: str,
    hostname: str = '',
    dhcp_server: str = '',
    pool_id: str | None = None,
    external_id: str | None = None,
    tenant_id: str = 'tenant-default',
    lease_state: str = 'active',
    lease_start: str = '',
    lease_end: str = '',
    idempotency_key: str | None = None,
    audit_context: dict | None = None,
) -> dict:
    address = _normalize_host_address(address)
    pool_id = str(pool_id or '').strip() or None
    external_id = str(external_id or '').strip() or None
    dhcp_server = str(dhcp_server or '').strip()
    tenant_id = str(tenant_id or 'tenant-default').strip()
    if external_id and not dhcp_server:
        raise ValueError('A DHCP server/source is required when external_id is supplied')
    conn = get_db_connection()
    try:
        pool = None
        if pool_id:
            pool = _lock_external_dhcp_pool_for_lease(
                conn, pool_id=pool_id, address=address, tenant_id=tenant_id,
            )
        address_space_id = str(pool.get('address_space_id') or '') if pool else None
        scope_status = 'scope_resolved' if address_space_id else 'scope_unknown'
        idempotency_payload = {
            'address': address, 'mac_address': mac_address, 'hostname': hostname,
            'dhcp_server': dhcp_server, 'pool_id': pool_id or '',
            'external_id': external_id or '', 'tenant_id': tenant_id,
            'lease_state': lease_state, 'lease_start': lease_start,
            'lease_end': lease_end,
        }
        replay = _idempotency_replay(
            conn,
            tenant_id=tenant_id,
            operation='ipam.lease.create',
            idempotency_key=idempotency_key,
            payload=idempotency_payload,
        )
        if replay is not None:
            replay.pop('_idempotency_replay', None)
            conn.commit()
            return replay
        if external_id:
            _lock_lease_external_identity(conn, tenant_id, dhcp_server, external_id)
            existing = conn.execute(
                f"""SELECT * FROM ipam_dhcp_leases
                     WHERE COALESCE(tenant_id, 'tenant-default') = {_PH}
                       AND lower(COALESCE(dhcp_server, '')) = lower({_PH})
                       AND external_id = {_PH}
                     FOR UPDATE""",
                (tenant_id, dhcp_server, external_id),
            ).fetchone()
            if existing:
                existing = dict(existing)
                if (
                    str(existing.get('pool_id') or '') != str(pool_id or '')
                    or str(existing.get('address_space_id') or '') != str(address_space_id or '')
                ):
                    raise ValueError('DHCP external_id is already bound to a different Pool/address space')
                now = _utc_now()
                conn.execute(
                    f"""UPDATE ipam_dhcp_leases
                           SET address = {_PH}, mac_address = {_PH}, hostname = {_PH},
                               lease_state = {_PH}, lease_start = {_PH}, lease_end = {_PH},
                               updated_at = {_PH}, revision = revision + 1
                         WHERE id = {_PH}""",
                    (address, mac_address, hostname, lease_state, lease_start, lease_end, now, existing['id']),
                )
                result = _lease_response(conn, str(existing['id']))
                result['reused'] = True
                _store_idempotency_response(
                    conn,
                    tenant_id=tenant_id,
                    operation='ipam.lease.create',
                    idempotency_key=idempotency_key,
                    payload=idempotency_payload,
                    response=result,
                    resource_type='ipam_lease',
                )
                _write_ipam_audit(
                    conn,
                    audit_context,
                    event_type='ipam.lease.create',
                    severity='info',
                    summary=f'Updated DHCP Lease {address} from source identity',
                    target_type='ipam_lease',
                    target_id=str(existing['id']),
                    target_name=address,
                    before=existing,
                    after=result,
                    details={'pool_id': pool_id, 'external_id': external_id},
                )
                conn.commit()
                return result
        lease_id = f"lease-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        conn.execute(
            f'''INSERT INTO ipam_dhcp_leases
               (id, address, address_space_id, pool_id, external_id, scope_status,
                mac_address, hostname, dhcp_server, tenant_id, lease_state,
                lease_start, lease_end, created_at, updated_at)
               VALUES ({_ph(15)})''',
            (lease_id, address, address_space_id, pool_id, external_id, scope_status,
             mac_address, hostname, dhcp_server, tenant_id, lease_state,
             lease_start, lease_end, now, now),
        )
        result = _lease_response(conn, lease_id)
        _store_idempotency_response(
            conn,
            tenant_id=tenant_id,
            operation='ipam.lease.create',
            idempotency_key=idempotency_key,
            payload=idempotency_payload,
            response=result,
            resource_type='ipam_lease',
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type='ipam.lease.create',
            severity='info',
            summary=f'Created DHCP Lease {address}',
            target_type='ipam_lease',
            target_id=lease_id,
            target_name=address,
            after=result,
            details={'pool_id': pool_id, 'external_id': external_id},
        )
        conn.commit()
        return result
    finally:
        conn.close()


def update_lease(lease_id: str, *, audit_context: dict | None = None, **fields) -> bool:
    conn = get_db_connection()
    try:
        expected_revision = fields.pop('expected_revision', None)
        initial = conn.execute(
            f'SELECT * FROM ipam_dhcp_leases WHERE id = {_PH}', (lease_id,)
        ).fetchone()
        if not initial:
            return False
        initial = dict(initial)
        fields = dict(fields)
        external_id_supplied = 'external_id' in fields
        tenant_id = str(initial.get('tenant_id') or 'tenant-default')
        if 'pool_id' in fields:
            target_pool_id = str(fields.get('pool_id') or '').strip() or None
        else:
            target_pool_id = str(initial.get('pool_id') or '').strip() or None
        address = _normalize_host_address(fields.get('address') or initial.get('address') or '')
        pool = None
        if target_pool_id:
            pool = _lock_external_dhcp_pool_for_lease(
                conn, pool_id=target_pool_id, address=address, tenant_id=tenant_id,
            )
        address_space_id = str(pool.get('address_space_id') or '') if pool else None
        scope_status = 'scope_resolved' if address_space_id else 'scope_unknown'
        external_id = str(fields.get('external_id', initial.get('external_id')) or '').strip() or None
        dhcp_server = str(fields.get('dhcp_server', initial.get('dhcp_server')) or '').strip()
        if external_id and not dhcp_server:
            raise ValueError('A DHCP server/source is required when external_id is supplied')
        if external_id:
            _lock_lease_external_identity(conn, tenant_id, dhcp_server, external_id)
            duplicate = conn.execute(
                f"""SELECT id FROM ipam_dhcp_leases
                     WHERE COALESCE(tenant_id, 'tenant-default') = {_PH}
                       AND lower(COALESCE(dhcp_server, '')) = lower({_PH})
                       AND external_id = {_PH} AND id <> {_PH}
                     LIMIT 1""",
                (tenant_id, dhcp_server, external_id, lease_id),
            ).fetchone()
            if duplicate:
                raise ValueError('DHCP external_id is already used by another lease')
        row = conn.execute(
            f'SELECT * FROM ipam_dhcp_leases WHERE id = {_PH} FOR UPDATE', (lease_id,)
        ).fetchone()
        if not row:
            return False
        row = dict(row)
        if int(row.get('revision') or 1) != int(initial.get('revision') or 1):
            raise ValueError('DHCP lease changed during update; refresh and retry')
        if expected_revision is not None and int(row.get('revision') or 1) != int(expected_revision):
            raise ValueError('DHCP lease revision is stale; refresh and retry')
        updates = []
        params = []
        fields.update({
            'address': address,
            'pool_id': target_pool_id,
            'address_space_id': address_space_id,
            'scope_status': scope_status,
            'external_id': external_id,
            'dhcp_server': dhcp_server,
        })
        for f in ('address', 'pool_id', 'address_space_id', 'scope_status', 'external_id',
                  'mac_address', 'hostname', 'dhcp_server', 'lease_state', 'lease_start', 'lease_end'):
            val = fields.get(f)
            if val is not None or f in {'pool_id', 'address_space_id'} or (f == 'external_id' and external_id_supplied):
                updates.append(f'{f} = {_PH}')
                params.append(val)
        if updates:
            updates.append(f'updated_at = {_PH}')
            params.append(_utc_now())
            updates.append('revision = revision + 1')
            params.append(lease_id)
            conn.execute(
                f"UPDATE ipam_dhcp_leases SET {', '.join(updates)} WHERE id = {_PH}",
                tuple(params),
            )
            after = _lease_response(conn, lease_id)
            _write_ipam_audit(
                conn,
                audit_context,
                event_type='ipam.lease.update',
                severity='info',
                summary=f'Updated DHCP Lease {lease_id}',
                target_type='ipam_lease',
                target_id=lease_id,
                before=row,
                after=after,
                details={key: value for key, value in fields.items() if key != 'expected_revision'},
            )
            conn.commit()
        return True
    finally:
        conn.close()


def delete_lease(
    lease_id: str,
    *,
    expected_revision: int | None = None,
    audit_context: dict | None = None,
) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f'SELECT id, revision FROM ipam_dhcp_leases WHERE id = {_PH}', (lease_id,)
        ).fetchone()
        if not row:
            return False
        initial_revision = int(row['revision'] or 1)
        locked = conn.execute(
            f'SELECT * FROM ipam_dhcp_leases WHERE id = {_PH} FOR UPDATE',
            (lease_id,),
        ).fetchone()
        if not locked:
            return False
        if int(locked['revision'] or 1) != initial_revision:
            raise ValueError('DHCP lease changed during deletion; refresh and retry')
        if expected_revision is not None and int(locked['revision'] or 1) != int(expected_revision):
            raise ValueError('DHCP lease revision is stale; refresh and retry')
        conn.execute(f'DELETE FROM ipam_dhcp_leases WHERE id = {_PH}', (lease_id,))
        _write_ipam_audit(
            conn,
            audit_context,
            event_type='ipam.lease.delete',
            severity='warning',
            summary=f'Deleted DHCP Lease {lease_id}',
            target_type='ipam_lease',
            target_id=lease_id,
            before=dict(locked),
            after={},
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_next_available_ip_details(subnet_id: str, *, pool_id: str | None = None) -> dict:
    """Return a suggestion and distinct current-page IPs pending scope review."""
    conn = get_db_connection()
    try:
        subnet = conn.execute(
            f'''SELECT id, prefix, status, gateway, tenant_id, vrf_id, site_id, address_space_id
                  FROM prefixes WHERE id = {_PH}''',
            (subnet_id,),
        ).fetchone()
        if not subnet:
            return {'next_available_ip': None, 'pending_discovery_count': 0}

        if str(subnet['status'] or '').strip().lower() == 'container':
            return {'next_available_ip': None, 'pending_discovery_count': 0}

        space_id = str(subnet['address_space_id'] or '').strip()
        if not space_id:
            return {
                'next_available_ip': None,
                'pending_discovery_count': 0,
            }
        try:
            net = ipaddress.ip_network(subnet['prefix'], strict=False)
        except ValueError:
            return {'next_available_ip': None, 'pending_discovery_count': 0}

        occupied_ips, pending_discovery_count = _current_allocation_occupancy(
            conn, subnet, net,
        )
        candidate_intervals = _pool_allocation_intervals(
            conn, subnet, net, pool_id=pool_id,
        )
        return {
            'next_available_ip': _first_free_address_in_intervals(
                net, occupied_ips, candidate_intervals,
            ),
            'pending_discovery_count': pending_discovery_count,
        }
    finally:
        conn.close()


def get_next_available_ip(subnet_id: str, *, pool_id: str | None = None) -> Optional[str]:
    """Compatibility wrapper returning only the next IP address."""
    return get_next_available_ip_details(subnet_id, pool_id=pool_id).get('next_available_ip')


def _first_available_child_prefix(
    parent_net: ipaddress._BaseNetwork,
    prefix_len: int,
    existing_nets: list[ipaddress._BaseNetwork],
) -> str | None:
    """Find the first non-overlapping child prefix without scanning candidates.

    Existing prefixes are converted to blocked candidate-index intervals. This
    keeps the search bounded by the number of existing records, even when the
    parent contains an enormous number of possible child networks.
    """
    if prefix_len <= parent_net.prefixlen or prefix_len > parent_net.max_prefixlen:
        return None

    candidate_count = 1 << (prefix_len - parent_net.prefixlen)
    candidate_size = 1 << (parent_net.max_prefixlen - prefix_len)
    parent_start = int(parent_net.network_address)
    parent_end = int(parent_net.broadcast_address)
    blocked_intervals: list[tuple[int, int]] = []

    for existing in existing_nets:
        if existing.version != parent_net.version or not existing.overlaps(parent_net):
            continue
        # A Prefix containing the complete requested parent is a container,
        # not an occupied child. Any narrower overlapping range blocks each
        # child index it intersects.
        if existing.prefixlen <= parent_net.prefixlen and parent_net.subnet_of(existing):
            continue
        overlap_start = max(parent_start, int(existing.network_address))
        overlap_end = min(parent_end, int(existing.broadcast_address))
        first_index = (overlap_start - parent_start) // candidate_size
        last_index = (overlap_end - parent_start) // candidate_size
        blocked_intervals.append((first_index, last_index))

    candidate_index = 0
    for first_index, last_index in sorted(blocked_intervals):
        if last_index < candidate_index:
            continue
        if first_index > candidate_index:
            break
        candidate_index = last_index + 1
        if candidate_index >= candidate_count:
            return None

    candidate_address = parent_start + candidate_index * candidate_size
    return str(ipaddress.ip_network((candidate_address, prefix_len)))


def get_next_available_prefix(subnet_id: str, prefix_len: int) -> Optional[str]:
    """Calculate the first unused child prefix of length prefix_len inside parent subnet."""
    conn = get_db_connection()
    try:
        parent = conn.execute(
            f'SELECT prefix, address_space_id FROM prefixes WHERE id = {_PH}', (subnet_id,)
        ).fetchone()
        if not parent:
            return None
            
        parent_prefix = parent['prefix']
        address_space_id = str(parent['address_space_id'] or '').strip()
        if not address_space_id:
            return None
        
        try:
            parent_net = ipaddress.ip_network(parent_prefix, strict=False)
        except ValueError:
            return None
            
        if prefix_len <= parent_net.prefixlen:
            return None
            
        existing_rows = conn.execute(
            f'SELECT prefix FROM prefixes WHERE address_space_id = {_PH}',
            (address_space_id,),
        ).fetchall()
            
        existing_nets = []
        for r in existing_rows:
            try:
                existing_nets.append(ipaddress.ip_network(r['prefix'], strict=False))
            except ValueError:
                continue
                
        return _first_available_child_prefix(parent_net, prefix_len, existing_nets)
    finally:
        conn.close()


def get_ipam_reconciliation(*, active_tab: str = '', q: str = '', page: int | None = None, page_size: int = 20,
                           visible_scopes: set[tuple[str, str]] | None = None) -> dict:
    """Compare current IPAM, endpoint and successful CMDB interface state."""
    conn = get_db_connection()
    try:
        from services.ipam_discovery_service import build_ipam_reconciliation
        return build_ipam_reconciliation(
            conn, active_tab=active_tab, q=q, page=page, page_size=page_size,
            visible_scopes=visible_scopes,
        )
    finally:
        conn.close()
