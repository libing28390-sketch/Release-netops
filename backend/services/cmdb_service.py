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
import math
from datetime import datetime, timezone
from functools import lru_cache
from database import _USE_PG
from core.interface_utils import normalize_interface_name as _normalize_interface_name

logger = logging.getLogger(__name__)

_DEFAULT_TENANT = 'tenant-default'

INTERFACE_ROLES = frozenset({
    'uplink', 'wan', 'transit', 'server', 'storage',
    'management', 'access', 'loopback', 'other', 'unclassified',
})
DEFAULT_INTERFACE_ROLE = 'unclassified'
DEFAULT_UTILIZATION_WARN_PCT = 60.0
DEFAULT_UTILIZATION_HIGH_PCT = 75.0
DEFAULT_UTILIZATION_CRITICAL_PCT = 90.0


@lru_cache(maxsize=8192)
def _normalize_interface_name_cached(value: str | None) -> str:
    """Memoize the pure shared normalizer for repeated CMDB interface names."""
    return _normalize_interface_name(value)


def _device_site_predicate(alias: str, site_id: str) -> tuple[str, tuple[str, ...]]:
    """Match one site scope exactly; empty means unassigned, never every site."""
    site_expr = _device_site_expression(alias)
    if str(site_id or '').strip():
        return f"{site_expr} = ?", (str(site_id),)
    return f"{site_expr} = ''", ()


def _device_site_expression(alias: str, conn=None) -> str:
    """Resolve device site with the physical asset as the canonical source."""
    if conn is not None:
        device_columns = {
            str(column[0])
            for column in (conn.execute("SELECT * FROM devices LIMIT 0").description or [])
        }
        candidates: list[str] = []
        if 'asset_id' in device_columns:
            asset_state = conn.execute(
                "SELECT to_regclass('physical_assets') AS table_name"
            ).fetchone()
            if asset_state and _row_to_dict(asset_state).get('table_name'):
                candidates.append(
                    f"NULLIF((SELECT pa.site_id FROM physical_assets pa WHERE pa.id = {alias}.asset_id), '')"
                )
        if 'site_id' in device_columns:
            candidates.append(f"NULLIF({alias}.site_id, '')")
        if 'site' in device_columns:
            candidates.append(f"NULLIF({alias}.site, '')")
        return "COALESCE(" + ", ".join([*candidates, "''"]) + ")"
    return (
        f"COALESCE(NULLIF((SELECT pa.site_id FROM physical_assets pa "
        f"WHERE pa.id = {alias}.asset_id), ''), NULLIF({alias}.site_id, ''), "
        f"NULLIF({alias}.site, ''), '')"
    )


def _cmdb_snapshot_schema_available(conn) -> bool:
    row = conn.execute(
        "SELECT to_regclass('cmdb_collection_snapshots') AS table_name"
    ).fetchone()
    if not row:
        return False
    return bool(_row_to_dict(row).get('table_name'))


def _successful_collection_devices(
    conn,
    domains: tuple[str, ...],
    *,
    tenant_id: str | None = None,
    site_ids: tuple[str, ...] | None = None,
    device_id: str | None = None,
) -> dict[tuple[str, str], dict]:
    """Return only successful snapshot generations within the requested scope."""
    if not domains:
        return {}
    if not _cmdb_snapshot_schema_available(conn):
        # Minimal PostgreSQL contract fixtures predating M0298 exercise the
        # legacy read path without installing the optional CMDB snapshot schema.
        return {}
    clauses = ["s.domain IN (" + ",".join("?" for _ in domains) + ")", "s.successful_generation > 0"]
    params: list = list(domains)
    if tenant_id is not None:
        clauses.append("COALESCE(d.tenant_id, 'tenant-default') = ?")
        params.append(tenant_id)
    if site_ids is not None:
        if not site_ids:
            clauses.append("1 = 0")
        else:
            placeholders = ",".join("?" for _ in site_ids)
            clauses.append(f"{_device_site_expression('d')} IN ({placeholders})")
            params.extend(site_ids)
    if device_id:
        clauses.append("d.id = ?")
        params.append(device_id)
    rows = conn.execute(
        f"""SELECT s.device_id, s.domain, s.successful_generation,
                   s.last_success_at, s.observed_at, d.hostname AS device_hostname,
                   d.ip_address AS device_ip, d.platform AS device_platform,
                   d.status AS device_status,
                   {_device_site_expression('d')} AS resolved_site_id
            FROM cmdb_collection_snapshots s
            JOIN devices d ON d.id = s.device_id
            WHERE {' AND '.join(clauses)}""",
        tuple(params),
    ).fetchall()
    return {
        (str(row['domain'] or ''), str(row['device_id'] or '')): dict(row)
        for row in rows
    }


def _current_interface_observations(conn, successful_devices: dict[tuple[str, str], dict]) -> list[dict]:
    """Load interface rows fenced to each device's last successful generation."""
    domain_devices = [
        (device_id, state)
        for (domain, device_id), state in successful_devices.items()
        if domain == 'interface_inventory'
    ]
    if not domain_devices:
        return []
    device_ids = sorted({device_id for device_id, _state in domain_devices})
    placeholders = ','.join('?' for _ in device_ids)
    rows = conn.execute(
        f"""SELECT o.device_id, o.normalized_interface_name, o.interface_name,
                   o.description, o.admin_status, o.oper_status, o.ip_address,
                   o.ip_prefix_length, o.interface_type, o.generation, o.observed_at,
                   d.hostname AS device_hostname, d.ip_address AS device_ip,
                   d.platform AS device_platform, d.status AS device_status
            FROM cmdb_device_interface_observations o
            JOIN cmdb_collection_snapshots s ON s.device_id = o.device_id
                 AND s.domain = 'interface_inventory'
                 AND s.successful_generation = o.generation
            JOIN devices d ON d.id = o.device_id
            WHERE o.device_id IN ({placeholders})
            ORDER BY o.device_id, o.normalized_interface_name""",
        tuple(device_ids),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def _current_vlan_snapshot_projection(
    conn,
    *,
    tenant_id: str | None = None,
    site_id: str = '',
) -> dict:
    """Load successful CLI VLAN, port, and interface facts by snapshot generation."""
    resolved_site_filter = ('',) if site_id == 'unassigned' else ((site_id,) if site_id else None)
    successful = _successful_collection_devices(
        conn,
        ('interface_inventory', 'vlan_inventory'),
        tenant_id=tenant_id,
        site_ids=resolved_site_filter,
    )
    vlan_device_ids = sorted({
        device_id for (domain, device_id) in successful if domain == 'vlan_inventory'
    })
    vlan_observations: list[dict] = []
    vlan_ports: list[dict] = []
    if vlan_device_ids:
        placeholders = ','.join('?' for _ in vlan_device_ids)
        vlan_rows = conn.execute(
            f"""SELECT o.device_id, o.vlan_id, o.site_id AS observed_site_id,
                       o.vlan_name, o.vlan_status, o.generation, o.observed_at,
                       d.hostname AS device_hostname, d.ip_address AS device_ip,
                       d.tenant_id AS tenant_id,
                       {_device_site_expression('d')} AS resolved_site_id,
                       d.platform AS device_platform, d.vendor AS device_vendor
                FROM cmdb_device_vlan_observations o
                JOIN cmdb_collection_snapshots s ON s.device_id = o.device_id
                     AND s.domain = 'vlan_inventory'
                     AND s.successful_generation = o.generation
                JOIN devices d ON d.id = o.device_id
                WHERE o.device_id IN ({placeholders})
                ORDER BY o.vlan_id, o.device_id""",
            tuple(vlan_device_ids),
        ).fetchall()
        vlan_observations = [_row_to_dict(row) for row in vlan_rows]
        port_rows = conn.execute(
            f"""SELECT p.device_id, p.vlan_id, p.normalized_interface_name,
                       p.interface_name, p.port_mode, p.tagging, p.generation,
                       p.observed_at, p.metadata_json,
                       d.hostname AS device_hostname, d.ip_address AS device_ip,
                       {_device_site_expression('d')} AS resolved_site_id
                FROM cmdb_device_vlan_port_observations p
                JOIN cmdb_collection_snapshots s ON s.device_id = p.device_id
                     AND s.domain = 'vlan_inventory'
                     AND s.successful_generation = p.generation
                JOIN devices d ON d.id = p.device_id
                WHERE p.device_id IN ({placeholders})
                ORDER BY p.vlan_id, p.device_id, p.normalized_interface_name""",
            tuple(vlan_device_ids),
        ).fetchall()
        vlan_ports = [_row_to_dict(row) for row in port_rows]
    interface_observations = _current_interface_observations(conn, successful)
    interface_by_device_identity: dict[tuple[str, str], dict] = {}
    for row in interface_observations:
        identity = _interface_identity(row.get('device_id'), row.get('normalized_interface_name'))
        if identity[1]:
            interface_by_device_identity[identity] = row
    successful_by_domain: dict[str, dict[str, dict]] = {
        'interface_inventory': {},
        'vlan_inventory': {},
    }
    for (domain, device_id), row in successful.items():
        successful_by_domain.setdefault(domain, {})[device_id] = row
    return {
        'successful': successful_by_domain,
        'vlan_observations': vlan_observations,
        'vlan_ports': vlan_ports,
        'interface_observations': interface_observations,
        'interface_by_device_identity': interface_by_device_identity,
    }


def _interface_identity(device_id: object, interface_name: object) -> tuple[str, str]:
    device_key = str(device_id or '')
    raw_name = str(interface_name or '')
    normalized = _normalize_interface_name_cached(raw_name).lower() or raw_name.strip().lower()
    return device_key, normalized


def _interface_shared_candidates(conn, device_ids: set[str]) -> dict[tuple[str, str], list[dict]]:
    """Load narrow shared-interface IDs/counts for snapshot identity matching."""
    if not device_ids:
        return {}
    by_identity: dict[tuple[str, str], list[dict]] = {}
    sorted_ids = sorted(device_ids)
    for offset in range(0, len(sorted_ids), 500):
        batch = sorted_ids[offset:offset + 500]
        placeholders = ','.join('?' for _ in batch)
        rows = conn.execute(
            f"""SELECT i.id, i.device_id, i.interface_name,
                       (SELECT COUNT(*) FROM ip_addresses ip
                        WHERE ip.interface_id = i.id
                           OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name)) AS ip_count,
                       (SELECT COUNT(*) FROM topology_links tl
                        WHERE tl.source_interface_id = i.id OR tl.target_interface_id = i.id) AS link_count
                FROM interfaces i WHERE i.device_id IN ({placeholders})
                ORDER BY i.device_id, i.interface_name, i.id""",
            tuple(batch),
        ).fetchall()
        for row in rows:
            candidate = _row_to_dict(row)
            identity = _interface_identity(candidate.get('device_id'), candidate.get('interface_name'))
            if identity[1]:
                by_identity.setdefault(identity, []).append(candidate)
    return by_identity


def _interface_skeleton_display_rows(conn, interface_ids: set[str]) -> dict[tuple[str, str], dict]:
    """Load the wide shared profile once, and only for selected page identities."""
    if not interface_ids:
        return {}
    rows_by_identity: dict[tuple[str, str], list[dict]] = {}
    sorted_ids = sorted(interface_ids)
    for offset in range(0, len(sorted_ids), 500):
        batch = sorted_ids[offset:offset + 500]
        placeholders = ','.join('?' for _ in batch)
        rows = conn.execute(
            f"""SELECT i.id, i.device_id,
                       d.hostname AS device_hostname, d.ip_address AS device_ip,
                       d.platform AS device_platform, d.status AS device_status,
                       i.interface_name, i.description,
                       COALESCE(NULLIF(i.primary_ip, ''), NULLIF(i.ip_address, ''), '') AS interface_ip,
                       i.admin_status, i.oper_status, i.mac_address, i.speed, i.bandwidth,
                       i.interface_type, i.switchport_mode, i.access_vlan, i.native_vlan,
                       i.allowed_vlans, i.vrf_id, v.vrf_name, i.ip_enabled, i.last_flapped,
                       i.interface_role, i.utilization_warn_pct, i.utilization_high_pct,
                       i.utilization_critical_pct,
                       (SELECT COUNT(*) FROM ip_addresses ip
                        WHERE ip.interface_id = i.id
                           OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name)) AS ip_count,
                       (SELECT COUNT(*) FROM topology_links tl
                        WHERE tl.source_interface_id = i.id OR tl.target_interface_id = i.id) AS link_count
                FROM interfaces i LEFT JOIN devices d ON d.id = i.device_id
                LEFT JOIN vrfs v ON v.id = i.vrf_id
                WHERE i.id IN ({placeholders})
                ORDER BY COALESCE(d.hostname, ''), i.interface_name, i.id""",
            tuple(batch),
        ).fetchall()
        for row in rows:
            item = _row_to_dict(row)
            rows_by_identity.setdefault(
                _interface_identity(item.get('device_id'), item.get('interface_name')), []
            ).append(item)

    def score(item: dict) -> tuple:
        return (
            bool(item.get('interface_ip')),
            str(item.get('oper_status') or '').lower() not in {'', 'unknown'},
            str(item.get('admin_status') or '').lower() not in {'', 'unknown'},
            bool(item.get('access_vlan') or item.get('native_vlan') or str(item.get('allowed_vlans') or '').strip()),
            int(item.get('link_count') or 0) > 0,
            str(item.get('interface_role') or '').strip().lower() not in {'', 'unclassified'},
            sum(
                _as_profile_pct(item.get(field), default) != default
                for field, default in (
                    ('utilization_warn_pct', DEFAULT_UTILIZATION_WARN_PCT),
                    ('utilization_high_pct', DEFAULT_UTILIZATION_HIGH_PCT),
                    ('utilization_critical_pct', DEFAULT_UTILIZATION_CRITICAL_PCT),
                )
            ),
            -len(str(item.get('interface_name') or '')),
        )

    merged: dict[tuple[str, str], dict] = {}
    for identity, candidates in rows_by_identity.items():
        candidates.sort(key=lambda item: (score(item), str(item.get('id') or '')), reverse=True)
        preferred = dict(candidates[0])
        for secondary in candidates[1:]:
            for field in (
                'mac_address', 'speed', 'bandwidth', 'vrf_id', 'vrf_name', 'last_flapped',
                'switchport_mode', 'access_vlan', 'native_vlan', 'allowed_vlans',
                'interface_role', 'utilization_warn_pct', 'utilization_high_pct',
                'utilization_critical_pct',
            ):
                value = preferred.get(field)
                if value in (None, '') or str(value).strip().lower() in {'unknown', '-', '--', 'unclassified'}:
                    if secondary.get(field) not in (None, ''):
                        preferred[field] = secondary[field]
            preferred['ip_count'] = max(int(preferred.get('ip_count') or 0), int(secondary.get('ip_count') or 0))
            preferred['link_count'] = max(int(preferred.get('link_count') or 0), int(secondary.get('link_count') or 0))
        merged[identity] = preferred
    return merged


def _interface_observation_item(observation: dict, shared: dict | None = None) -> dict:
    """Project CLI-owned fields over optional read-only shared supplements."""
    shared = shared or {}
    item = dict(shared)
    device_id = str(observation.get('device_id') or '')
    normalized_name = str(observation.get('normalized_interface_name') or '')
    interface_name = str(observation.get('interface_name') or '')
    has_shared_id = bool(shared.get('id'))
    item.update({
        'id': str(shared.get('id') or f'cmdb-interface-observed:{device_id}:{normalized_name}'),
        'device_id': device_id,
        'device_hostname': str(observation.get('device_hostname') or shared.get('device_hostname') or device_id),
        'device_ip': str(observation.get('device_ip') or shared.get('device_ip') or ''),
        'device_platform': str(observation.get('device_platform') or shared.get('device_platform') or ''),
        'device_status': str(observation.get('device_status') or shared.get('device_status') or ''),
        'interface_name': interface_name,
        'description': str(observation.get('description') or ''),
        'admin_status': str(observation.get('admin_status') or 'unknown'),
        'oper_status': str(observation.get('oper_status') or 'unknown'),
        'interface_ip': str(observation.get('ip_address') or ''),
        'interface_ip_source': 'cmdb_cli_snapshot',
        'has_ip': bool(str(observation.get('ip_address') or '').strip()),
        'ip_prefix_length': observation.get('ip_prefix_length'),
        'interface_type': str(observation.get('interface_type') or 'unknown'),
        'interface_observed_at': observation.get('observed_at'),
        'interface_generation': int(observation.get('generation') or 0),
        'interface_source': 'cmdb_cli_snapshot',
        'profile_editable': has_shared_id,
        'ip_count': int(shared.get('ip_count') or observation.get('ip_count') or 0),
        'link_count': int(shared.get('link_count') or observation.get('link_count') or 0),
    })
    if not has_shared_id:
        item.update({
            'mac_address': '', 'speed': None, 'bandwidth': None,
            'switchport_mode': 'unknown', 'access_vlan': None,
            'native_vlan': None, 'allowed_vlans': '', 'vrf_id': None,
            'vrf_name': '', 'ip_enabled': 1, 'last_flapped': None,
            'interface_role': DEFAULT_INTERFACE_ROLE,
            'utilization_warn_pct': DEFAULT_UTILIZATION_WARN_PCT,
            'utilization_high_pct': DEFAULT_UTILIZATION_HIGH_PCT,
            'utilization_critical_pct': DEFAULT_UTILIZATION_CRITICAL_PCT,
        })
    return _normalize_interface_monitoring_profile(item)


def _as_profile_pct(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _normalize_interface_monitoring_profile(item: dict) -> dict:
    """Ensure every CMDB interface row exposes the stable profile contract."""
    role = str(item.get('interface_role') or DEFAULT_INTERFACE_ROLE).strip().lower()
    item['interface_role'] = role if role in INTERFACE_ROLES else DEFAULT_INTERFACE_ROLE
    item['utilization_warn_pct'] = _as_profile_pct(
        item.get('utilization_warn_pct'), DEFAULT_UTILIZATION_WARN_PCT
    )
    item['utilization_high_pct'] = _as_profile_pct(
        item.get('utilization_high_pct'), DEFAULT_UTILIZATION_HIGH_PCT
    )
    item['utilization_critical_pct'] = _as_profile_pct(
        item.get('utilization_critical_pct'), DEFAULT_UTILIZATION_CRITICAL_PCT
    )
    return item


def _validate_interface_monitoring_profile(
    *,
    interface_role: object,
    utilization_warn_pct: object,
    utilization_high_pct: object,
    utilization_critical_pct: object,
) -> tuple[str, float, float, float]:
    role = str(interface_role or '').strip().lower()
    if role not in INTERFACE_ROLES:
        raise ValueError(
            "interface_role must be one of: " + ', '.join(sorted(INTERFACE_ROLES))
        )
    percentages = tuple(
        _as_profile_pct(value, float('nan'))
        for value in (
            utilization_warn_pct,
            utilization_high_pct,
            utilization_critical_pct,
        )
    )
    if (
        not all(math.isfinite(value) for value in percentages)
        or not 0 <= percentages[0] < percentages[1] < percentages[2] <= 100
    ):
        raise ValueError(
            "utilization thresholds must satisfy "
            "0 <= utilization_warn_pct < utilization_high_pct "
            "< utilization_critical_pct <= 100"
        )
    return role, percentages[0], percentages[1], percentages[2]


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


def _bump_cmdb_reference_versions(conn, *, reference_domain: str) -> None:
    """Version CMDB projections and the exact reference directory changed."""
    normalized_domain = str(reference_domain or "").strip().lower()
    if normalized_domain not in {"sites", "vrfs"}:
        raise ValueError("reference_domain must be sites or vrfs")
    from services.cmdb_version_service import bump_read_versions

    bump_read_versions(
        conn,
        ("interfaces", "vlans", "bindings", normalized_domain),
    )


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
        identity = _normalize_interface_name_cached(raw_name).lower() or raw_name.lower()
        identities.setdefault(device_id, set()).add(identity)
    return {device_id: len(names) for device_id, names in identities.items()}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CMDB Network Skeleton
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def list_cmdb_devices(conn) -> list[dict]:
    """Return network devices as CMDB skeleton nodes with relationship counts."""
    # A few older/read-only database shapes do not expose the full physical
    # asset metadata set. Probe the available columns so optional classification
    # fields can be used without making the CMDB skeleton depend on migrations
    # that are not present in those shapes.
    physical_asset_columns = {
        str(column[0])
        for column in (conn.execute("SELECT * FROM physical_assets LIMIT 0").description or [])
    }
    device_columns = {
        str(column[0])
        for column in (conn.execute("SELECT * FROM devices LIMIT 0").description or [])
    }

    def first_nonempty_sql(sources: list[str]) -> str:
        candidates = [f"NULLIF(BTRIM({source}), '')" for source in sources]
        return "COALESCE(" + ", ".join([*candidates, "''"]) + ")"

    asset_type_expr = (
        "COALESCE(NULLIF(BTRIM(pa.asset_type), ''), 'network_device')"
        if 'asset_type' in physical_asset_columns else "'network_device'"
    )
    device_category_sources = []
    if 'device_category' in device_columns:
        device_category_sources.append('d.device_category')
    if 'device_category' in physical_asset_columns:
        device_category_sources.append('pa.device_category')
    platform_sources = []
    if 'platform' in device_columns:
        platform_sources.append('d.platform')
    if 'platform' in physical_asset_columns:
        platform_sources.append('pa.platform')
    role_sources = []
    if 'role' in device_columns:
        role_sources.append('d.role')
    if 'device_role' in physical_asset_columns:
        role_sources.append('pa.device_role')

    interface_counts = _distinct_interface_counts(conn)
    rows = conn.execute(
        f"""
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
            {asset_type_expr} AS _cmdb_asset_type,
            {first_nonempty_sql(device_category_sources)} AS _cmdb_device_category,
            {first_nonempty_sql(platform_sources)} AS _cmdb_platform,
            {first_nonempty_sql(role_sources)} AS _cmdb_role,
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
    from services.device_classification_service import is_server_device

    items = []
    for row in rows:
        item = _row_to_dict(row)
        asset_type = str(item.pop('_cmdb_asset_type', '') or 'network_device').strip().casefold()
        if asset_type != 'network_device':
            continue
        classification = {
            'device_category': item.pop('_cmdb_device_category', ''),
            'platform': item.pop('_cmdb_platform', ''),
            'role': item.pop('_cmdb_role', ''),
        }
        if is_server_device(classification):
            continue
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
    tenant_id: str | None = None,
    site_ids: tuple[str, ...] | None = None,
) -> list[dict] | dict:
    """Return interfaces as CMDB skeleton resources with optional has_ip, device_id, search filters."""
    snapshot_schema_available = _cmdb_snapshot_schema_available(conn)
    successful_devices = _successful_collection_devices(
        conn, ('interface_inventory',), tenant_id=tenant_id,
        site_ids=site_ids, device_id=device_id,
    )
    successful_interface_device_ids = {
        scoped_device_id
        for (domain, scoped_device_id) in successful_devices
        if domain == 'interface_inventory'
    }
    snapshot_observations = _current_interface_observations(conn, successful_devices)
    snapshot_shared_candidates = _interface_shared_candidates(
        conn, successful_interface_device_ids,
    )
    snapshot_by_identity: dict[tuple[str, str], dict] = {}
    snapshot_candidates: list[dict] = []
    snapshot_ids_by_identity: dict[tuple[str, str], list[str]] = {}
    search_value = str(search or '').strip().lower()
    for observation in snapshot_observations:
        identity = _interface_identity(
            observation.get('device_id'), observation.get('normalized_interface_name')
        )
        if not identity[1]:
            continue
        hostname = str(observation.get('device_hostname') or '')
        device_ip = str(observation.get('device_ip') or '')
        interface_ip = str(observation.get('ip_address') or '').strip()
        description = str(observation.get('description') or '')
        shared_rows = snapshot_shared_candidates.get(identity, [])
        ip_count = max((int(row.get('ip_count') or 0) for row in shared_rows), default=0)
        link_count = max((int(row.get('link_count') or 0) for row in shared_rows), default=0)
        if has_ip is True and not interface_ip:
            continue
        if has_ip is False and interface_ip:
            continue
        if search_value and search_value not in ' '.join((
            str(observation.get('interface_name') or ''), hostname, device_ip,
            interface_ip, description,
        )).lower():
            continue
        observation['ip_count'] = ip_count
        observation['link_count'] = link_count
        snapshot_by_identity[identity] = observation
        snapshot_ids_by_identity[identity] = [
            str(row.get('id') or '') for row in shared_rows if row.get('id')
        ]
        snapshot_candidates.append({
            'id': (snapshot_ids_by_identity[identity][0]
                   if snapshot_ids_by_identity[identity]
                   else f"cmdb-interface-observed:{identity[0]}:{identity[1]}"),
            'device_id': identity[0],
            'device_hostname': hostname,
            'device_ip': device_ip,
            'device_platform': str(observation.get('device_platform') or ''),
            'device_status': str(observation.get('device_status') or ''),
            'interface_name': str(observation.get('interface_name') or ''),
            'interface_ip': interface_ip,
            'interface_ip_source': 'cmdb_cli_snapshot',
            'has_ip': bool(interface_ip),
            'admin_status': str(observation.get('admin_status') or 'unknown'),
            'oper_status': str(observation.get('oper_status') or 'unknown'),
            'interface_type': str(observation.get('interface_type') or 'unknown'),
            'ip_count': ip_count,
            'link_count': link_count,
            'interface_source': 'cmdb_cli_snapshot',
            'profile_editable': bool(snapshot_ids_by_identity[identity]),
        })

    if page is not None or page_size is not None:
        # The paged API needs global alias identity/counts, but only page rows
        # need the wide display projection and correlated IP/topology counts.
        # Keep the legacy unpaged return path below unchanged.
        where_clauses: list[str] = []
        candidate_params: list = []
        if tenant_id is not None:
            where_clauses.append("d.id IS NOT NULL AND COALESCE(d.tenant_id, 'tenant-default') = ?")
            candidate_params.append(tenant_id)
        if site_ids is not None:
            if not site_ids:
                where_clauses.append("1 = 0")
            else:
                site_placeholders = ",".join("?" for _ in site_ids)
                where_clauses.append(f"{_device_site_expression('d', conn)} IN ({site_placeholders})")
                candidate_params.extend(site_ids)
        if has_ip is True:
            where_clauses.append("""(
                NULLIF(i.primary_ip, '') IS NOT NULL
                OR NULLIF(i.ip_address, '') IS NOT NULL
                OR EXISTS (
                    SELECT 1 FROM ip_addresses ip
                    WHERE (ip.interface_id = i.id
                        OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name))
                      AND COALESCE(i.ip_enabled, 0) = 1
                      AND COALESCE(NULLIF(ip.ip_address, ''), NULLIF(ip.address, '')) IS NOT NULL
                )
            )""")
        elif has_ip is False:
            where_clauses.append("""(
                NULLIF(i.primary_ip, '') IS NULL
                AND NULLIF(i.ip_address, '') IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM ip_addresses ip
                    WHERE (ip.interface_id = i.id
                        OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name))
                      AND COALESCE(i.ip_enabled, 0) = 1
                      AND COALESCE(NULLIF(ip.ip_address, ''), NULLIF(ip.address, '')) IS NOT NULL
                )
            )""")
        if device_id:
            where_clauses.append("i.device_id = ?")
            candidate_params.append(device_id)
        if search:
            search_pattern = f"%{search.strip()}%"
            where_clauses.append("""(
                i.interface_name LIKE ? OR d.hostname LIKE ? OR d.ip_address LIKE ?
                OR i.primary_ip LIKE ? OR i.ip_address LIKE ? OR i.description LIKE ?
                OR EXISTS (
                    SELECT 1 FROM ip_addresses ip
                    WHERE (ip.interface_id = i.id
                        OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name))
                      AND (ip.ip_address LIKE ? OR ip.address LIKE ?)
                )
            )""")
            candidate_params.extend([search_pattern] * 8)
        candidate_where = " AND ".join(where_clauses)
        candidate_where_sql = (
            " AND NOT EXISTS (\n                SELECT 1 FROM cmdb_collection_snapshots s\n"
            "                WHERE s.device_id = i.device_id AND s.domain = 'interface_inventory'\n"
            "                  AND s.successful_generation > 0\n            )"
            if snapshot_schema_available else ''
        )
        if candidate_where:
            candidate_where_sql += f" AND ({candidate_where})"

        def _paged_identity(candidate: dict) -> tuple[str, str]:
            identity_device = str(candidate.get('device_id') or '')
            identity_name = _normalize_interface_name_cached(candidate.get('interface_name')).lower()
            if not identity_name:
                identity_name = str(candidate.get('interface_name') or '').strip().lower()
            return identity_device, identity_name

        def _merge_paged_aliases(raw_items: list[dict]) -> dict[tuple[str, str], dict]:
            """Apply the existing score and secondary-field merge to a row set."""
            grouped: dict[tuple[str, str], dict] = {}
            for candidate in raw_items:
                identity = _paged_identity(candidate)
                current = grouped.get(identity)
                if current is None:
                    grouped[identity] = candidate
                    continue
                candidate_score = (
                    bool(candidate.get('interface_ip')),
                    str(candidate.get('oper_status') or '').lower() not in {'', 'unknown'},
                    str(candidate.get('admin_status') or '').lower() not in {'', 'unknown'},
                    bool(candidate.get('access_vlan') or candidate.get('native_vlan')
                         or str(candidate.get('allowed_vlans') or '').strip()),
                    int(candidate.get('link_count') or 0) > 0,
                    str(candidate.get('interface_role') or '').strip().lower() not in {'', 'unclassified'},
                    sum(
                        _as_profile_pct(candidate.get(field), default) != default
                        for field, default in (
                            ('utilization_warn_pct', DEFAULT_UTILIZATION_WARN_PCT),
                            ('utilization_high_pct', DEFAULT_UTILIZATION_HIGH_PCT),
                            ('utilization_critical_pct', DEFAULT_UTILIZATION_CRITICAL_PCT),
                        )
                    ),
                    -len(str(candidate.get('interface_name') or '')),
                )
                current_score = (
                    bool(current.get('interface_ip')),
                    str(current.get('oper_status') or '').lower() not in {'', 'unknown'},
                    str(current.get('admin_status') or '').lower() not in {'', 'unknown'},
                    bool(current.get('access_vlan') or current.get('native_vlan')
                         or str(current.get('allowed_vlans') or '').strip()),
                    int(current.get('link_count') or 0) > 0,
                    str(current.get('interface_role') or '').strip().lower() not in {'', 'unclassified'},
                    sum(
                        _as_profile_pct(current.get(field), default) != default
                        for field, default in (
                            ('utilization_warn_pct', DEFAULT_UTILIZATION_WARN_PCT),
                            ('utilization_high_pct', DEFAULT_UTILIZATION_HIGH_PCT),
                            ('utilization_critical_pct', DEFAULT_UTILIZATION_CRITICAL_PCT),
                        )
                    ),
                    -len(str(current.get('interface_name') or '')),
                )
                preferred, secondary = (candidate, current) if candidate_score > current_score else (current, candidate)
                for field in (
                    'interface_ip', 'description', 'mac_address', 'speed', 'bandwidth', 'vrf_id', 'last_flapped',
                    'interface_type', 'switchport_mode', 'access_vlan', 'native_vlan', 'allowed_vlans',
                    'interface_role', 'utilization_warn_pct', 'utilization_high_pct',
                    'utilization_critical_pct',
                ):
                    preferred_value = str(preferred.get(field) or '').strip().lower()
                    if preferred_value in {'', 'unknown', '-', '--'} and secondary.get(field) not in (None, ''):
                        preferred[field] = secondary[field]
                if str(preferred.get('interface_role') or '').strip().lower() in {'', 'unclassified'}:
                    secondary_role = str(secondary.get('interface_role') or '').strip().lower()
                    if secondary_role not in {'', 'unclassified'}:
                        preferred['interface_role'] = secondary['interface_role']
                for field, default in (
                    ('utilization_warn_pct', DEFAULT_UTILIZATION_WARN_PCT),
                    ('utilization_high_pct', DEFAULT_UTILIZATION_HIGH_PCT),
                    ('utilization_critical_pct', DEFAULT_UTILIZATION_CRITICAL_PCT),
                ):
                    if _as_profile_pct(preferred.get(field), default) == default and secondary.get(field) not in (None, ''):
                        preferred[field] = secondary[field]
                for field in ('admin_status', 'oper_status'):
                    if str(preferred.get(field) or '').strip().lower() in {'', 'unknown', '-', '--'}:
                        if str(secondary.get(field) or '').strip().lower() not in {'', 'unknown', '-', '--'}:
                            preferred[field] = secondary[field]
                preferred['ip_count'] = max(int(preferred.get('ip_count') or 0), int(secondary.get('ip_count') or 0))
                preferred['link_count'] = max(int(preferred.get('link_count') or 0), int(secondary.get('link_count') or 0))
                grouped[identity] = preferred
            return grouped

        candidate_sql = """
            SELECT i.id, i.device_id,
                   d.hostname AS device_hostname,
                   i.interface_name,
                   COALESCE(
                       NULLIF(i.primary_ip, ''), NULLIF(i.ip_address, ''),
                       (SELECT COALESCE(NULLIF(ip.ip_address, ''), NULLIF(ip.address, ''))
                        FROM ip_addresses ip
                        WHERE (ip.interface_id = i.id
                            OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name))
                          AND COALESCE(i.ip_enabled, 0) = 1
                          AND COALESCE(NULLIF(ip.ip_address, ''), NULLIF(ip.address, '')) IS NOT NULL
                        ORDER BY ip.updated_at DESC NULLS LAST LIMIT 1)
                   ) AS interface_ip,
                   i.admin_status, i.oper_status,
                   i.access_vlan, i.native_vlan, i.allowed_vlans,
                   i.interface_role, i.utilization_warn_pct, i.utilization_high_pct,
                   i.utilization_critical_pct,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM ip_addresses ip
                       WHERE ip.interface_id = i.id
                          OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name)
                   ) THEN 1 ELSE 0 END AS ip_count,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM topology_links tl
                       WHERE tl.source_interface_id = i.id OR tl.target_interface_id = i.id
                   ) THEN 1 ELSE 0 END AS link_count
            FROM interfaces i
            LEFT JOIN devices d ON d.id = i.device_id
            WHERE 1=1
        """ + candidate_where_sql + " ORDER BY COALESCE(d.hostname, ''), COALESCE(i.interface_name, ''), i.id"
        safe_page = max(1, int(page or 1))
        safe_page_size = max(1, min(int(page_size or 20), 100))
        page_offset = (safe_page - 1) * safe_page_size
        fast_projection = False
        fast_total = 0
        fast_summary: dict[str, int] = {}
        fast_device_options: list[dict] = []
        fast_option_pairs: set[tuple[str, str]] = set()
        fast_selected_identities: list[tuple[str, str]] = []
        candidate_ids_by_identity: dict[tuple[str, str], list[str]] = {}
        inventory_may_affect_candidates = False
        if has_ip is True:
            inventory_guard_clauses = ["COALESCE(inv.ip, '') <> ''", "d.id IS NOT NULL"]
            inventory_guard_params: list = []
            if snapshot_schema_available:
                inventory_guard_clauses.append(
                    "NOT EXISTS (SELECT 1 FROM cmdb_collection_snapshots s "
                    "WHERE s.device_id = inv.device_id AND s.domain = 'interface_inventory' "
                    "AND s.successful_generation > 0)"
                )
            if device_id:
                inventory_guard_clauses.append("inv.device_id = ?")
                inventory_guard_params.append(device_id)
            if tenant_id is not None:
                inventory_guard_clauses.append(
                    "COALESCE(d.tenant_id, 'tenant-default') = ?"
                )
                inventory_guard_params.append(tenant_id)
            if site_ids is not None:
                if not site_ids:
                    inventory_guard_clauses.append("1 = 0")
                else:
                    site_placeholders = ",".join("?" for _ in site_ids)
                    inventory_guard_clauses.append(
                        f"{_device_site_expression('d', conn)} IN ({site_placeholders})"
                    )
                    inventory_guard_params.extend(site_ids)
            # Search is intentionally omitted here: this is a conservative
            # guard. An inventory row outside the search may select the legacy
            # path, but can never make the SQL fast path change results.
            inventory_guard_clauses.append(
                "(i.id IS NULL OR i.ip_enabled IS NULL OR COALESCE(i.ip_enabled, 0) <> 0)"
            )
            inventory_may_affect_candidates = bool(conn.execute(
                f"""SELECT 1 FROM ip_inventory inv
                    LEFT JOIN devices d ON d.id = inv.device_id
                    LEFT JOIN interfaces i
                      ON i.device_id = inv.device_id
                     AND LOWER(TRIM(i.interface_name)) = LOWER(TRIM(inv.interface))
                    WHERE {' AND '.join(inventory_guard_clauses)}
                    LIMIT 1""",
                tuple(inventory_guard_params),
            ).fetchone())

        # Verify candidate identity uniqueness through the shared Python
        # normalizer using only narrow keys. Once every candidate has a unique
        # identity, SQL can count and page rows without loading the full
        # candidate projection into Python. Alias groups stay on the existing
        # merge path. Snapshot candidates and relevant ip_inventory rows also
        # retain the existing precedence and total logic.
        if not search and not snapshot_candidates and not inventory_may_affect_candidates:
            candidate_ip_sql = """COALESCE(
                NULLIF(i.primary_ip, ''), NULLIF(i.ip_address, ''),
                (SELECT COALESCE(NULLIF(ip.ip_address, ''), NULLIF(ip.address, ''))
                 FROM ip_addresses ip
                 WHERE (ip.interface_id = i.id
                     OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name))
                   AND COALESCE(i.ip_enabled, 0) = 1
                   AND COALESCE(NULLIF(ip.ip_address, ''), NULLIF(ip.address, '')) IS NOT NULL
                 ORDER BY ip.updated_at DESC NULLS LAST LIMIT 1)
            )"""
            preflight_fields = (
                "i.id, i.device_id, i.interface_name, COALESCE(d.hostname, '') AS device_hostname"
            )
            if has_ip is True:
                preflight_fields += f", {candidate_ip_sql} AS interface_ip"
            preflight_rows = [
                _row_to_dict(row)
                for row in conn.execute(
                    f"""SELECT {preflight_fields}
                        FROM interfaces i LEFT JOIN devices d ON d.id = i.device_id
                        WHERE 1=1 {candidate_where_sql}""",
                    tuple(candidate_params),
                ).fetchall()
            ]
            known_identities: set[tuple[str, str]] = set()
            can_page_unique_candidates = True
            for candidate in preflight_rows:
                identity = _paged_identity(candidate)
                option_device_id = str(candidate.get('device_id') or '')
                option_hostname = str(candidate.get('device_hostname') or '')
                if option_device_id and option_hostname:
                    fast_option_pairs.add((option_device_id, option_hostname))
                if identity in known_identities:
                    can_page_unique_candidates = False
                    break
                known_identities.add(identity)
                if has_ip is True and not all(
                    str(candidate.get(field) or '').isascii()
                    for field in ('id', 'device_hostname', 'interface_name', 'interface_ip')
                ):
                    can_page_unique_candidates = False
                    break

            if can_page_unique_candidates:
                fast_projection = True
                page_order_sql = (
                    f"ORDER BY COALESCE(d.hostname, '') COLLATE \"C\", "
                    f"COALESCE(i.interface_name, '') COLLATE \"C\", "
                    f"COALESCE({candidate_ip_sql}, '') COLLATE \"C\", i.id::text COLLATE \"C\""
                    if has_ip is True else
                    "ORDER BY COALESCE(d.hostname, ''), COALESCE(i.interface_name, ''), i.id"
                )
                page_fields = """i.id, i.device_id, i.interface_name,
                    COUNT(*) OVER() AS total,
                    SUM(CASE WHEN NULLIF(i.primary_ip, '') IS NOT NULL
                                  OR NULLIF(i.ip_address, '') IS NOT NULL
                                  OR EXISTS (
                                      SELECT 1 FROM ip_addresses ip
                                      WHERE ip.interface_id = i.id
                                         OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name)
                                  )
                             THEN 1 ELSE 0 END) OVER() AS with_ip,
                    SUM(CASE WHEN LOWER(COALESCE(i.oper_status, '')) = 'up'
                             THEN 1 ELSE 0 END) OVER() AS oper_up,
                    SUM(CASE WHEN EXISTS (
                                  SELECT 1 FROM topology_links tl
                                  WHERE tl.source_interface_id = i.id OR tl.target_interface_id = i.id
                             ) THEN 1 ELSE 0 END) OVER() AS with_links"""
                if has_ip is True:
                    page_fields += f", {candidate_ip_sql} AS interface_ip"
                page_rows = conn.execute(
                    f"""SELECT {page_fields}
                        FROM interfaces i LEFT JOIN devices d ON d.id = i.device_id
                        WHERE 1=1 {candidate_where_sql}
                        {page_order_sql}
                        LIMIT ? OFFSET ?""",
                    (*candidate_params, safe_page_size, page_offset),
                ).fetchall()
                if page_rows:
                    projection = _row_to_dict(page_rows[0])
                    fast_total = int(projection.get('total') or 0)
                    fast_summary = {
                        'total': fast_total,
                        'with_ip': int(projection.get('with_ip') or 0),
                        'oper_up': int(projection.get('oper_up') or 0),
                        'with_links': int(projection.get('with_links') or 0),
                    }
                else:
                    # Window aggregates return no row for an empty or out of
                    # range page; pay for the full summary only in this case.
                    empty_page_summary = _row_to_dict(conn.execute(
                        f"""SELECT COUNT(*) AS total,
                            COALESCE(SUM(CASE WHEN NULLIF(i.primary_ip, '') IS NOT NULL
                                                   OR NULLIF(i.ip_address, '') IS NOT NULL
                                                   OR EXISTS (
                                                       SELECT 1 FROM ip_addresses ip
                                                       WHERE ip.interface_id = i.id
                                                          OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name)
                                                   )
                                              THEN 1 ELSE 0 END), 0) AS with_ip,
                            COALESCE(SUM(CASE WHEN LOWER(COALESCE(i.oper_status, '')) = 'up'
                                              THEN 1 ELSE 0 END), 0) AS oper_up,
                            COALESCE(SUM(CASE WHEN EXISTS (
                                                   SELECT 1 FROM topology_links tl
                                                   WHERE tl.source_interface_id = i.id OR tl.target_interface_id = i.id
                                               ) THEN 1 ELSE 0 END), 0) AS with_links
                            FROM interfaces i LEFT JOIN devices d ON d.id = i.device_id
                            WHERE 1=1 {candidate_where_sql}""",
                        tuple(candidate_params),
                    ).fetchone())
                    fast_total = int(empty_page_summary.get('total') or 0)
                    fast_summary = {
                        'total': fast_total,
                        'with_ip': int(empty_page_summary.get('with_ip') or 0),
                        'oper_up': int(empty_page_summary.get('oper_up') or 0),
                        'with_links': int(empty_page_summary.get('with_links') or 0),
                    }
                for page_row in page_rows:
                    candidate = _row_to_dict(page_row)
                    identity = _paged_identity(candidate)
                    fast_selected_identities.append(identity)
                    candidate_ids_by_identity.setdefault(identity, []).append(str(candidate.get('id') or ''))
                fast_device_options = [
                    {'value': device_key, 'label': hostname}
                    for device_key, hostname in sorted(
                        fast_option_pairs, key=lambda value: value[1].lower(),
                    )
                ]

        raw_candidates = [] if fast_projection else [
            _row_to_dict(row)
            for row in conn.execute(candidate_sql, tuple(candidate_params)).fetchall()
        ]
        if not fast_projection:
            for candidate in raw_candidates:
                candidate_ids_by_identity.setdefault(_paged_identity(candidate), []).append(str(candidate.get('id') or ''))
        candidate_items_by_identity = _merge_paged_aliases(raw_candidates)
        candidate_items = list(candidate_items_by_identity.values())
        for identity, candidate in candidate_items_by_identity.items():
            candidate.setdefault('interface_source', 'shared_interface')
            candidate.setdefault('profile_editable', bool(candidate.get('id')))
        candidate_ids_by_identity.update(snapshot_ids_by_identity)
        for identity, candidate in _merge_paged_aliases(snapshot_candidates).items():
            candidate_items.append(candidate)

        # ip_inventory participates in the global total only for has_ip=True.
        # This candidate scan intentionally omits the fallback detail columns.
        eligible_inventory_rows: list[dict] = []
        inventory_scope: list[str] = []
        inventory_params: list = []
        if tenant_id is not None:
            inventory_scope.append("d.id IS NOT NULL AND COALESCE(d.tenant_id, 'tenant-default') = ?")
            inventory_params.append(tenant_id)
        if site_ids is not None:
            if not site_ids:
                inventory_scope.append("1 = 0")
            else:
                site_placeholders = ",".join("?" for _ in site_ids)
                inventory_scope.append(f"{_device_site_expression('d', conn)} IN ({site_placeholders})")
                inventory_params.extend(site_ids)
        inventory_scope_sql = " AND " + " AND ".join(inventory_scope) if inventory_scope else ""
        search_value = search.strip().lower() if search else ''
        if has_ip is True and not fast_projection:
            inventory_candidate_sql = """
                SELECT inv.ip, inv.device_id, inv.interface, inv.type, inv.last_seen,
                       d.hostname AS device_hostname, d.ip_address AS device_ip,
                       i.id AS skeleton_interface_id, i.ip_enabled AS skeleton_ip_enabled,
                       i.oper_status AS skeleton_oper_status
                FROM ip_inventory inv
                LEFT JOIN devices d ON d.id = inv.device_id
                LEFT JOIN interfaces i
                  ON i.device_id = inv.device_id
                 AND LOWER(TRIM(i.interface_name)) = LOWER(TRIM(inv.interface))
                WHERE COALESCE(inv.ip, '') <> '' AND d.id IS NOT NULL
            """ + (
                " AND NOT EXISTS (SELECT 1 FROM cmdb_collection_snapshots s "
                "WHERE s.device_id = inv.device_id AND s.domain = 'interface_inventory' "
                "AND s.successful_generation > 0)"
                if snapshot_schema_available else ''
            ) + inventory_scope_sql + " ORDER BY COALESCE(d.hostname, ''), COALESCE(inv.interface, ''), inv.ip"
            try:
                inventory_candidates = conn.execute(
                    inventory_candidate_sql, tuple(inventory_params)
                ).fetchall()
            except Exception:
                inventory_candidates = []
            for inventory_row in inventory_candidates:
                inventory = _row_to_dict(inventory_row)
                if device_id and str(inventory.get('device_id') or '') != str(device_id):
                    continue
                if search_value:
                    searchable = ' '.join(str(inventory.get(key) or '') for key in (
                        'ip', 'device_hostname', 'device_ip', 'interface', 'type',
                    )).lower()
                    if search_value not in searchable:
                        continue
                eligible_inventory_rows.append(inventory)

            existing_by_identity = {
                _paged_identity(item): item for item in candidate_items
            }
            for inventory in eligible_inventory_rows:
                if inventory.get('skeleton_interface_id') and inventory.get('skeleton_ip_enabled') in (0, False, '0'):
                    continue
                ip_value = str(inventory.get('ip') or '').strip()
                inventory_device_id = str(inventory.get('device_id') or '')
                interface_name = str(inventory.get('interface') or '').strip()
                identity = (inventory_device_id, _normalize_interface_name_cached(interface_name).lower())
                if not identity[1]:
                    identity = (identity[0], interface_name.lower())
                existing = existing_by_identity.get(identity)
                if existing is not None:
                    if ip_value:
                        existing['interface_ip'] = ip_value
                        existing['interface_ip_source'] = 'ip_inventory'
                        existing['ip_count'] = max(1, int(existing.get('ip_count') or 0))
                    if inventory.get('last_seen'):
                        existing['last_seen'] = inventory.get('last_seen')
                    continue
                fallback_candidate = {
                    'id': inventory.get('skeleton_interface_id') or f"ipinv-{inventory_device_id}-{interface_name}-{ip_value}",
                    'device_id': inventory_device_id,
                    'device_hostname': inventory.get('device_hostname') or '',
                    'interface_name': interface_name,
                    'interface_ip': ip_value,
                    'interface_ip_source': 'ip_inventory',
                    'oper_status': inventory.get('skeleton_oper_status') or 'unknown',
                    'ip_count': 1,
                    'link_count': 0,
                    'last_seen': inventory.get('last_seen'),
                }
                candidate_items.append(fallback_candidate)
                existing_by_identity[identity] = fallback_candidate
            candidate_items.sort(key=lambda item: (
                str(item.get('device_hostname') or ''),
                str(item.get('interface_name') or ''),
                str(item.get('interface_ip') or ''),
                str(item.get('id') or ''),
            ))

        if fast_projection:
            total = fast_total
            selected_identities = fast_selected_identities
        else:
            total = len(candidate_items)
            start = (safe_page - 1) * safe_page_size
            selected_page = candidate_items[start:start + safe_page_size]
            selected_identities = [_paged_identity(item) for item in selected_page]

        # Pull full skeleton columns and correlated associations for all alias
        # rows in the selected identity groups, never by raw-row LIMIT/OFFSET.
        full_items_by_identity: dict[tuple[str, str], dict] = {}
        selected_ids: list[str] = []
        seen_ids: set[str] = set()
        for identity in selected_identities:
            for interface_row_id in candidate_ids_by_identity.get(identity, []):
                if interface_row_id and interface_row_id not in seen_ids:
                    seen_ids.add(interface_row_id)
                    selected_ids.append(interface_row_id)
        full_select = """
            SELECT i.id, i.device_id,
                   d.hostname AS device_hostname, d.ip_address AS device_ip,
                   d.platform AS device_platform, d.status AS device_status,
                   i.interface_name, i.description,
                   COALESCE(
                       NULLIF(i.primary_ip, ''), NULLIF(i.ip_address, ''),
                       (SELECT COALESCE(NULLIF(ip.ip_address, ''), NULLIF(ip.address, ''))
                        FROM ip_addresses ip
                        WHERE (ip.interface_id = i.id
                            OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name))
                          AND COALESCE(i.ip_enabled, 0) = 1
                          AND COALESCE(NULLIF(ip.ip_address, ''), NULLIF(ip.address, '')) IS NOT NULL
                        ORDER BY ip.updated_at DESC NULLS LAST LIMIT 1)
                   ) AS interface_ip,
                   i.admin_status, i.oper_status, i.mac_address, i.speed, i.bandwidth,
                   i.interface_type, i.switchport_mode, i.access_vlan, i.native_vlan,
                   i.allowed_vlans, i.vrf_id, v.vrf_name, i.ip_enabled, i.last_flapped,
                   i.interface_role, i.utilization_warn_pct, i.utilization_high_pct,
                   i.utilization_critical_pct,
                   (SELECT COUNT(*) FROM ip_addresses ip
                    WHERE ip.interface_id = i.id
                       OR (ip.device_id = i.device_id AND ip.interface_name = i.interface_name)) AS ip_count,
                   (SELECT COUNT(*) FROM topology_links tl
                    WHERE tl.source_interface_id = i.id OR tl.target_interface_id = i.id) AS link_count
            FROM interfaces i
            LEFT JOIN devices d ON d.id = i.device_id
            LEFT JOIN vrfs v ON v.id = i.vrf_id
            WHERE i.id IN ({placeholders})
            ORDER BY COALESCE(d.hostname, ''), COALESCE(i.interface_name, ''), i.id
        """
        full_rows: list[dict] = []
        for offset in range(0, len(selected_ids), 500):
            id_batch = selected_ids[offset:offset + 500]
            full_rows.extend(
                _row_to_dict(row)
                for row in conn.execute(
                    full_select.format(placeholders=','.join('?' for _ in id_batch)),
                    tuple(id_batch),
                ).fetchall()
            )
        full_items_by_identity = _merge_paged_aliases(full_rows)
        display_by_identity = {
            identity: full_items_by_identity[identity]
            for identity in selected_identities
            if identity in full_items_by_identity
        }
        for identity in selected_identities:
            observation = snapshot_by_identity.get(identity)
            if observation is not None:
                display_by_identity[identity] = _interface_observation_item(
                    observation, full_items_by_identity.get(identity),
                )

        if has_ip is True and selected_identities and not fast_projection:
            selected_identity_set = set(selected_identities)
            fallback_fact_devices = sorted({
                str(inventory.get('device_id') or '')
                for inventory in eligible_inventory_rows
                if _paged_identity({
                    'device_id': inventory.get('device_id'),
                    'interface_name': inventory.get('interface'),
                }) in selected_identity_set
                and _paged_identity({
                    'device_id': inventory.get('device_id'),
                    'interface_name': inventory.get('interface'),
                }) not in full_items_by_identity
                and not (
                    inventory.get('skeleton_interface_id')
                    and inventory.get('skeleton_ip_enabled') in (0, False, '0')
                )
            } - {''})
            interface_facts_by_identity: dict[tuple[str, str], dict] = {}
            fact_fields = (
                'interface_type', 'switchport_mode', 'access_vlan', 'native_vlan', 'allowed_vlans',
                'admin_status', 'oper_status', 'mac_address', 'description', 'speed', 'bandwidth',
                'vrf_id', 'ip_enabled', 'last_flapped', 'interface_role',
                'utilization_warn_pct', 'utilization_high_pct', 'utilization_critical_pct',
            )
            for offset in range(0, len(fallback_fact_devices), 500):
                device_batch = fallback_fact_devices[offset:offset + 500]
                fact_rows = conn.execute(
                    f"""SELECT device_id, interface_name, {', '.join(fact_fields)}
                        FROM interfaces WHERE device_id IN ({','.join('?' for _ in device_batch)})
                        ORDER BY device_id, interface_name, id""",
                    tuple(device_batch),
                ).fetchall()
                for fact_row in fact_rows:
                    fact = _row_to_dict(fact_row)
                    identity = _paged_identity(fact)
                    if not identity[1]:
                        continue
                    current_fact = interface_facts_by_identity.setdefault(identity, fact)
                    for field in fact_fields:
                        current_value = str(current_fact.get(field) or '').strip().lower()
                        candidate_value = fact.get(field)
                        if current_value in {'', 'unknown', '-', '--'} and candidate_value not in (None, ''):
                            current_fact[field] = candidate_value

            selected_inventory_pairs = list(dict.fromkeys(
                (str(row.get('device_id') or ''), row.get('interface'))
                for row in eligible_inventory_rows
                if _paged_identity({'device_id': row.get('device_id'), 'interface_name': row.get('interface')})
                in selected_identity_set
            ))
            inventory_detail_rows: list[dict] = []
            for offset in range(0, len(selected_inventory_pairs), 200):
                pair_batch = selected_inventory_pairs[offset:offset + 200]
                pair_clauses: list[str] = []
                pair_params: list = []
                for selected_device_id, interface_name in pair_batch:
                    if interface_name is None:
                        pair_clauses.append("(inv.device_id = ? AND inv.interface IS NULL)")
                        pair_params.append(selected_device_id)
                    else:
                        pair_clauses.append("(inv.device_id = ? AND LOWER(TRIM(inv.interface)) = LOWER(TRIM(?)))")
                        pair_params.extend((selected_device_id, str(interface_name)))
                details_sql = """
                    SELECT inv.ip, inv.device_id, inv.interface, inv.type, inv.last_seen,
                           d.hostname AS device_hostname, d.ip_address AS device_ip,
                           d.platform AS device_platform, d.status AS device_status,
                           i.id AS skeleton_interface_id,
                           i.admin_status AS skeleton_admin_status, i.oper_status AS skeleton_oper_status,
                           i.interface_type AS skeleton_interface_type,
                           i.switchport_mode AS skeleton_switchport_mode,
                           i.access_vlan AS skeleton_access_vlan, i.native_vlan AS skeleton_native_vlan,
                           i.allowed_vlans AS skeleton_allowed_vlans, i.mac_address AS skeleton_mac_address,
                           i.description AS skeleton_description, i.speed AS skeleton_speed,
                           i.bandwidth AS skeleton_bandwidth, i.vrf_id AS skeleton_vrf_id,
                           i.ip_enabled AS skeleton_ip_enabled, i.last_flapped AS skeleton_last_flapped,
                           i.interface_role AS skeleton_interface_role,
                           i.utilization_warn_pct AS skeleton_utilization_warn_pct,
                           i.utilization_high_pct AS skeleton_utilization_high_pct,
                           i.utilization_critical_pct AS skeleton_utilization_critical_pct
                    FROM ip_inventory inv
                    LEFT JOIN devices d ON d.id = inv.device_id
                    LEFT JOIN interfaces i
                      ON i.device_id = inv.device_id
                     AND LOWER(TRIM(i.interface_name)) = LOWER(TRIM(inv.interface))
                    WHERE COALESCE(inv.ip, '') <> '' AND d.id IS NOT NULL
                """ + inventory_scope_sql + " AND (" + " OR ".join(pair_clauses) + ")"
                details_sql += " ORDER BY COALESCE(d.hostname, ''), COALESCE(inv.interface, ''), inv.ip"
                inventory_detail_rows.extend(
                    _row_to_dict(row)
                    for row in conn.execute(
                        details_sql, tuple(inventory_params + pair_params)
                    ).fetchall()
                )

            def _inventory_signature(inventory: dict) -> tuple:
                return tuple(inventory.get(field) for field in ('device_id', 'interface', 'ip', 'type', 'last_seen'))

            full_inventory_by_signature: dict[tuple, list[dict]] = {}
            for inventory in inventory_detail_rows:
                if device_id and str(inventory.get('device_id') or '') != str(device_id):
                    continue
                if search_value:
                    searchable = ' '.join(str(inventory.get(key) or '') for key in (
                        'ip', 'device_hostname', 'device_ip', 'interface', 'type',
                    )).lower()
                    if search_value not in searchable:
                        continue
                full_inventory_by_signature.setdefault(_inventory_signature(inventory), []).append(inventory)
            signature_offsets: dict[tuple, int] = {}
            page_inventory_rows: list[dict] = []
            for inventory in eligible_inventory_rows:
                identity = _paged_identity({'device_id': inventory.get('device_id'), 'interface_name': inventory.get('interface')})
                if identity not in selected_identity_set:
                    continue
                signature = _inventory_signature(inventory)
                matches = full_inventory_by_signature.get(signature, [])
                match_offset = signature_offsets.get(signature, 0)
                if match_offset < len(matches):
                    page_inventory_rows.append(matches[match_offset])
                    signature_offsets[signature] = match_offset + 1

            for inventory in page_inventory_rows:
                if inventory.get('skeleton_interface_id') and inventory.get('skeleton_ip_enabled') in (0, False, '0'):
                    continue
                ip_value = str(inventory.get('ip') or '').strip()
                inventory_device_id = str(inventory.get('device_id') or '')
                interface_name = str(inventory.get('interface') or '').strip()
                identity = (inventory_device_id, _normalize_interface_name_cached(interface_name).lower())
                if not identity[1]:
                    identity = (identity[0], interface_name.lower())
                existing = display_by_identity.get(identity)
                if existing is not None:
                    if ip_value:
                        existing['interface_ip'] = ip_value
                        existing['interface_ip_source'] = 'ip_inventory'
                        existing['ip_count'] = max(1, int(existing.get('ip_count') or 0))
                    if inventory.get('last_seen'):
                        existing['last_seen'] = inventory.get('last_seen')
                    continue
                interface_fact = interface_facts_by_identity.get(identity, {})
                display_by_identity[identity] = {
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
                    'interface_role': inventory.get('skeleton_interface_role') or interface_fact.get('interface_role') or DEFAULT_INTERFACE_ROLE,
                    'utilization_warn_pct': inventory.get('skeleton_utilization_warn_pct') if inventory.get('skeleton_utilization_warn_pct') is not None else interface_fact.get('utilization_warn_pct', DEFAULT_UTILIZATION_WARN_PCT),
                    'utilization_high_pct': inventory.get('skeleton_utilization_high_pct') if inventory.get('skeleton_utilization_high_pct') is not None else interface_fact.get('utilization_high_pct', DEFAULT_UTILIZATION_HIGH_PCT),
                    'utilization_critical_pct': inventory.get('skeleton_utilization_critical_pct') if inventory.get('skeleton_utilization_critical_pct') is not None else interface_fact.get('utilization_critical_pct', DEFAULT_UTILIZATION_CRITICAL_PCT),
                    'ip_count': 1,
                    'link_count': 0,
                    'last_seen': inventory.get('last_seen'),
                }

        display_items = [
            display_by_identity[identity]
            for identity in selected_identities
            if identity in display_by_identity
        ]
        for item in display_items:
            item.setdefault('interface_source', 'shared_interface')
            item.setdefault('profile_editable', bool(item.get('id')))
            _normalize_interface_monitoring_profile(item)
        if fast_projection:
            device_options = fast_device_options
            summary = fast_summary
        else:
            device_options = [
                {'value': str(option_device_id), 'label': str(label)}
                for option_device_id, label in sorted({
                    (str(item.get('device_id') or ''), str(item.get('device_hostname') or ''))
                    for item in candidate_items
                    if item.get('device_id') and item.get('device_hostname')
                }, key=lambda value: value[1].lower())
            ]
            summary = {
                'total': total,
                'with_ip': sum(1 for item in candidate_items if (
                    bool(item.get('interface_ip'))
                    if item.get('interface_source') == 'cmdb_cli_snapshot'
                    else item.get('interface_ip') or int(item.get('ip_count') or 0) > 0
                )),
                'oper_up': sum(1 for item in candidate_items if str(item.get('oper_status') or '').lower() == 'up'),
                'with_links': sum(1 for item in candidate_items if int(item.get('link_count') or 0) > 0),
            }
        return {
            'items': display_items,
            'total': total,
            'page': safe_page,
            'page_size': safe_page_size,
            'total_pages': max(1, -(-total // safe_page_size)),
            'summary': summary,
            'device_options': device_options,
        }

    # Listing is read-only. Legacy orphan inventory rows are filtered by the
    # devices join below and must be reconciled by an explicit maintenance path.
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
            i.interface_role,
            i.utilization_warn_pct,
            i.utilization_high_pct,
            i.utilization_critical_pct,
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
    if tenant_id is not None:
        sql += " AND d.id IS NOT NULL AND COALESCE(d.tenant_id, 'tenant-default') = ?"
        params.append(tenant_id)
    if site_ids is not None:
        if not site_ids:
            sql += " AND 1 = 0"
        else:
            site_placeholders = ",".join("?" for _ in site_ids)
            sql += f" AND {_device_site_expression('d', conn)} IN ({site_placeholders})"
            params.extend(site_ids)
    if snapshot_schema_available:
        sql += """ AND NOT EXISTS (
            SELECT 1 FROM cmdb_collection_snapshots s
            WHERE s.device_id = i.device_id AND s.domain = 'interface_inventory'
              AND s.successful_generation > 0
        )"""
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
            _normalize_interface_name_cached(candidate.get('interface_name')).lower(),
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
            str(candidate.get('interface_role') or '').strip().lower() not in {'', 'unclassified'},
            sum(
                _as_profile_pct(candidate.get(field), default) != default
                for field, default in (
                    ('utilization_warn_pct', DEFAULT_UTILIZATION_WARN_PCT),
                    ('utilization_high_pct', DEFAULT_UTILIZATION_HIGH_PCT),
                    ('utilization_critical_pct', DEFAULT_UTILIZATION_CRITICAL_PCT),
                )
            ),
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
            str(current.get('interface_role') or '').strip().lower() not in {'', 'unclassified'},
            sum(
                _as_profile_pct(current.get(field), default) != default
                for field, default in (
                    ('utilization_warn_pct', DEFAULT_UTILIZATION_WARN_PCT),
                    ('utilization_high_pct', DEFAULT_UTILIZATION_HIGH_PCT),
                    ('utilization_critical_pct', DEFAULT_UTILIZATION_CRITICAL_PCT),
                )
            ),
            -len(str(current.get('interface_name') or '')),
        )
        preferred, secondary = (candidate, current) if candidate_score > current_score else (current, candidate)
        for field in (
            'interface_ip', 'description', 'mac_address', 'speed', 'bandwidth', 'vrf_id', 'last_flapped',
            'interface_type', 'switchport_mode', 'access_vlan', 'native_vlan', 'allowed_vlans',
            'interface_role', 'utilization_warn_pct', 'utilization_high_pct',
            'utilization_critical_pct',
        ):
            preferred_value = str(preferred.get(field) or '').strip().lower()
            if preferred_value in {'', 'unknown', '-', '--'} and secondary.get(field) not in (None, ''):
                preferred[field] = secondary[field]
        if str(preferred.get('interface_role') or '').strip().lower() in {'', 'unclassified'}:
            secondary_role = str(secondary.get('interface_role') or '').strip().lower()
            if secondary_role not in {'', 'unclassified'}:
                preferred['interface_role'] = secondary_role
        for field, default in (
            ('utilization_warn_pct', DEFAULT_UTILIZATION_WARN_PCT),
            ('utilization_high_pct', DEFAULT_UTILIZATION_HIGH_PCT),
            ('utilization_critical_pct', DEFAULT_UTILIZATION_CRITICAL_PCT),
        ):
            if _as_profile_pct(preferred.get(field), default) == default and secondary.get(field) not in (None, ''):
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
                          mac_address, description, speed, bandwidth, vrf_id, ip_enabled, last_flapped,
                          interface_role, utilization_warn_pct, utilization_high_pct,
                          utilization_critical_pct
                   FROM interfaces"""
            ).fetchall()
        except Exception:
            all_interface_rows = []
        for interface_row in all_interface_rows:
            fact = _row_to_dict(interface_row)
            identity = (
                str(fact.get('device_id') or ''),
                _normalize_interface_name_cached(fact.get('interface_name')).lower(),
            )
            if not identity[1]:
                continue
            current_fact = interface_facts_by_identity.setdefault(identity, fact)
            for field in (
                'interface_type', 'switchport_mode', 'access_vlan', 'native_vlan', 'allowed_vlans',
                'admin_status', 'oper_status', 'mac_address', 'description', 'speed', 'bandwidth',
                'vrf_id', 'ip_enabled', 'last_flapped',
                'interface_role', 'utilization_warn_pct', 'utilization_high_pct',
                'utilization_critical_pct',
            ):
                current_value = str(current_fact.get(field) or '').strip().lower()
                candidate_value = fact.get(field)
                if current_value in {'', 'unknown', '-', '--'} and candidate_value not in (None, ''):
                    current_fact[field] = candidate_value
        inventory_scope = []
        inventory_params: list[str] = []
        if tenant_id is not None:
            inventory_scope.append("d.id IS NOT NULL AND COALESCE(d.tenant_id, 'tenant-default') = ?")
            inventory_params.append(tenant_id)
        if site_ids is not None:
            if not site_ids:
                inventory_scope.append("1 = 0")
            else:
                site_placeholders = ",".join("?" for _ in site_ids)
                inventory_scope.append(f"{_device_site_expression('d', conn)} IN ({site_placeholders})")
                inventory_params.extend(site_ids)
        inventory_scope_sql = " AND " + " AND ".join(inventory_scope) if inventory_scope else ""
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
                       i.last_flapped AS skeleton_last_flapped,
                       i.interface_role AS skeleton_interface_role,
                       i.utilization_warn_pct AS skeleton_utilization_warn_pct,
                       i.utilization_high_pct AS skeleton_utilization_high_pct,
                       i.utilization_critical_pct AS skeleton_utilization_critical_pct
                FROM ip_inventory inv
                LEFT JOIN devices d ON d.id = inv.device_id
                LEFT JOIN interfaces i
                  ON i.device_id = inv.device_id
                 AND LOWER(TRIM(i.interface_name)) = LOWER(TRIM(inv.interface))
                 WHERE COALESCE(inv.ip, '') <> ''
                   AND d.id IS NOT NULL
                 """ + (
                    " AND NOT EXISTS (SELECT 1 FROM cmdb_collection_snapshots s "
                    "WHERE s.device_id = inv.device_id AND s.domain = 'interface_inventory' "
                    "AND s.successful_generation > 0)"
                    if snapshot_schema_available else ''
                 ) + inventory_scope_sql + """
                ORDER BY COALESCE(d.hostname, ''), COALESCE(inv.interface, ''), inv.ip
                """
                , tuple(inventory_params)
            ).fetchall()
        except Exception:
            inventory_rows = []

        existing_by_identity = {
            (
                str(item.get('device_id') or ''),
                _normalize_interface_name_cached(item.get('interface_name')).lower(),
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
            identity = (inventory_device_id, _normalize_interface_name_cached(interface_name).lower())
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
                'interface_role': inventory.get('skeleton_interface_role') or interface_fact.get('interface_role') or DEFAULT_INTERFACE_ROLE,
                'utilization_warn_pct': (
                    inventory.get('skeleton_utilization_warn_pct')
                    if inventory.get('skeleton_utilization_warn_pct') is not None
                    else interface_fact.get('utilization_warn_pct', DEFAULT_UTILIZATION_WARN_PCT)
                ),
                'utilization_high_pct': (
                    inventory.get('skeleton_utilization_high_pct')
                    if inventory.get('skeleton_utilization_high_pct') is not None
                    else interface_fact.get('utilization_high_pct', DEFAULT_UTILIZATION_HIGH_PCT)
                ),
                'utilization_critical_pct': (
                    inventory.get('skeleton_utilization_critical_pct')
                    if inventory.get('skeleton_utilization_critical_pct') is not None
                    else interface_fact.get('utilization_critical_pct', DEFAULT_UTILIZATION_CRITICAL_PCT)
                ),
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
    if snapshot_by_identity:
        selected_shared_ids = {
            interface_id
            for identity, interface_ids in snapshot_ids_by_identity.items()
            if identity in snapshot_by_identity
            for interface_id in interface_ids
        }
        shared_display_by_identity = _interface_skeleton_display_rows(conn, selected_shared_ids)
        existing_by_identity = {
            _interface_identity(item.get('device_id'), item.get('interface_name')): item
            for item in items
        }
        for identity, observation in snapshot_by_identity.items():
            existing_by_identity[identity] = _interface_observation_item(
                observation, shared_display_by_identity.get(identity),
            )
        items = list(existing_by_identity.values())

    for item in items:
        item.setdefault(
            'interface_source',
            'ip_inventory' if str(item.get('id') or '').startswith('ipinv-') else 'shared_interface',
        )
        item.setdefault(
            'profile_editable',
            bool(item.get('id') and not str(item.get('id')).startswith('ipinv-')),
        )
        _normalize_interface_monitoring_profile(item)
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


def update_interface_monitoring_profile(
    conn,
    interface_id: str,
    *,
    tenant_id: str | None = None,
    site_ids: tuple[str, ...] | None = None,
    **updates,
) -> dict:
    """Update one CMDB interface's monitoring profile atomically.

    The thresholds are validated after merging the supplied PATCH fields with
    the current row.  PostgreSQL row locking prevents concurrent operators
    from validating against stale threshold values.
    """
    interface_key = str(interface_id or '').strip()
    if not interface_key:
        raise ValueError('interface_id is required')

    allowed = {
        'interface_role',
        'utilization_warn_pct',
        'utilization_high_pct',
        'utilization_critical_pct',
    }
    requested = {key: value for key, value in updates.items() if key in allowed and value is not None}
    if not requested:
        raise ValueError('At least one monitoring profile field is required')

    where = ['i.id = ?']
    query_params: list = [interface_key]
    if tenant_id is not None:
        where.append("COALESCE(d.tenant_id, 'tenant-default') = ?")
        query_params.append(tenant_id)
    if site_ids is not None:
        if not site_ids:
            raise ValueError(f'Interface {interface_key} not found')
        placeholders = ','.join('?' for _ in site_ids)
        where.append(f'd.site_id IN ({placeholders})')
        query_params.extend(site_ids)
    lock_suffix = ' FOR UPDATE OF i, d' if _USE_PG else ''
    try:
        row = conn.execute(
            """
            SELECT i.id, i.device_id, i.interface_name, i.interface_role,
                   i.utilization_warn_pct, i.utilization_high_pct,
                   i.utilization_critical_pct
              FROM interfaces i
              JOIN devices d ON d.id = i.device_id
             WHERE """ + ' AND '.join(where) + lock_suffix,
            tuple(query_params),
        ).fetchone()
        if row is None:
            raise ValueError(f'Interface {interface_key} not found')
        current = _row_to_dict(row)
        merged = {
            'interface_role': current.get('interface_role') or DEFAULT_INTERFACE_ROLE,
            'utilization_warn_pct': current.get('utilization_warn_pct', DEFAULT_UTILIZATION_WARN_PCT),
            'utilization_high_pct': current.get('utilization_high_pct', DEFAULT_UTILIZATION_HIGH_PCT),
            'utilization_critical_pct': current.get('utilization_critical_pct', DEFAULT_UTILIZATION_CRITICAL_PCT),
        }
        merged.update(requested)
        role, warn_pct, high_pct, critical_pct = _validate_interface_monitoring_profile(**merged)
        conn.execute(
            """
            UPDATE interfaces
               SET interface_role = ?,
                   utilization_warn_pct = ?,
                   utilization_high_pct = ?,
                   utilization_critical_pct = ?
             WHERE id = ?
            """,
            (role, warn_pct, high_pct, critical_pct, interface_key),
        )
        conn.commit()
        return {
            'id': current.get('id') or interface_key,
            'device_id': current.get('device_id') or '',
            'interface_name': current.get('interface_name') or '',
            'interface_role': role,
            'utilization_warn_pct': warn_pct,
            'utilization_high_pct': high_pct,
            'utilization_critical_pct': critical_pct,
        }
    except Exception:
        conn.rollback()
        raise


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
    """Return the sole organization record for legacy lookup consumers."""
    row = conn.execute("SELECT * FROM tenants WHERE id = ?", (_DEFAULT_TENANT,)).fetchone()
    return [_row_to_dict(row)] if row else []


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
    _bump_cmdb_reference_versions(conn, reference_domain="sites")
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
    _bump_cmdb_reference_versions(conn, reference_domain="sites")
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
        _bump_cmdb_reference_versions(conn, reference_domain="sites")
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
    _bump_cmdb_reference_versions(conn, reference_domain="vrfs")
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
    _bump_cmdb_reference_versions(conn, reference_domain="vrfs")
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
    _bump_cmdb_reference_versions(conn, reference_domain="vrfs")
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
            """SELECT d.id, d.hostname, d.ip_address,
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


def _vlan_list_filter_sql(
    site_id: str,
    tenant_id: str,
    q: str,
    status: str,
) -> tuple[str, tuple]:
    clauses: list[str] = []
    params: list = []
    if site_id:
        if site_id == 'unassigned':
            clauses.append("COALESCE(v.site_id, '') = ''")
        else:
            clauses.append("v.site_id = ?")
            params.append(site_id)
    if tenant_id:
        clauses.append("v.tenant_id = ?")
        params.append(tenant_id)
    if status and status != 'all':
        clauses.append("v.status = ?")
        params.append(status)
    if q and q.strip():
        fuzzy = f"%{q.strip().lower()}%"
        clauses.append(
            "(LOWER(CAST(v.vlan_id AS TEXT)) LIKE ? OR LOWER(COALESCE(v.name, '')) LIKE ? "
            "OR EXISTS (SELECT 1 FROM interfaces i JOIN devices d ON d.id = i.device_id "
            "WHERE " + _device_site_expression('d') + " = COALESCE(v.site_id, '') "
            "AND (LOWER(COALESCE(d.hostname, '')) LIKE ? OR LOWER(COALESCE(d.ip_address, '')) LIKE ? "
            "OR LOWER(COALESCE(i.interface_name, '')) LIKE ? OR LOWER(COALESCE(i.primary_ip, '')) LIKE ? "
            "OR LOWER(COALESCE(i.ip_address, '')) LIKE ? OR LOWER(COALESCE(i.description, '')) LIKE ?)) "
            "OR EXISTS (SELECT 1 FROM cmdb_device_vlan_observations o "
            "JOIN cmdb_collection_snapshots s ON s.device_id=o.device_id AND s.domain='vlan_inventory' "
            "AND s.successful_generation=o.generation JOIN devices d ON d.id=o.device_id "
            "WHERE o.vlan_id=v.vlan_id AND " + _device_site_expression('d') + "=COALESCE(v.site_id, '') "
            "AND (LOWER(COALESCE(o.vlan_name, '')) LIKE ? OR LOWER(COALESCE(d.hostname, '')) LIKE ? "
            "OR LOWER(COALESCE(d.ip_address, '')) LIKE ?)) "
            "OR EXISTS (SELECT 1 FROM cmdb_device_vlan_port_observations p "
            "JOIN cmdb_collection_snapshots s ON s.device_id=p.device_id AND s.domain='vlan_inventory' "
            "AND s.successful_generation=p.generation JOIN devices d ON d.id=p.device_id "
            "WHERE p.vlan_id=v.vlan_id AND " + _device_site_expression('d') + "=COALESCE(v.site_id, '') "
            "AND LOWER(COALESCE(p.interface_name, '')) LIKE ?) "
            "OR EXISTS (SELECT 1 FROM prefixes p WHERE p.vlan_id = v.id "
            "AND (LOWER(COALESCE(p.prefix, '')) LIKE ? OR LOWER(COALESCE(p.gateway, '')) LIKE ?)) "
            "OR EXISTS (SELECT 1 FROM vlan_business_bindings b WHERE b.vlan_id = v.vlan_id "
            "AND b.site_id = COALESCE(v.site_id, '') AND (LOWER(COALESCE(b.business_system, '')) LIKE ? "
            "OR LOWER(COALESCE(b.department, '')) LIKE ? OR LOWER(COALESCE(b.owner, '')) LIKE ?)))"
        )
        params.extend([fuzzy] * 17)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", tuple(params)


def _vlan_svi_networks(svi_rows: list, inventory: dict[str, str]) -> tuple[list[str], list[str]]:
    """Project SVI gateway addresses and prefixes using the inventory mask fallback."""
    gateways: list[str] = []
    prefixes: list[str] = []
    for svi in svi_rows:
        raw_ip = str(svi['primary_ip'] or svi['ip_address'] or '').strip()
        if not raw_ip:
            continue
        prefix_length = str(svi['ip_prefix_length'] or '').strip()
        if not prefix_length:
            if '/' in raw_ip:
                raw_ip, prefix_length = raw_ip.split('/', 1)
            else:
                prefix_length = inventory.get(_normalize_interface_name_cached(svi['interface_name']), '')

        clean_host_ip = raw_ip.split('/', 1)[0].strip()
        if not clean_host_ip:
            continue
        if prefix_length and '.' in prefix_length:
            try:
                prefix_length = str(ipaddress.IPv4Network(f'0.0.0.0/{prefix_length}').prefixlen)
            except ValueError:
                prefix_length = ''
        try:
            address = ipaddress.ip_interface(f'{clean_host_ip}/{prefix_length or 32}')
        except ValueError:
            continue
        gateways.append(str(address.ip))
        if prefix_length and prefix_length != '32':
            prefixes.append(str(address.network))
        elif '/' in str(svi['primary_ip'] or svi['ip_address'] or ''):
            prefixes.append(str(address.network))
        else:
            prefixes.append(str(address.ip))
    return gateways, list(dict.fromkeys(prefixes))


def _vlan_svi_gateway_present(svi_facts: list[dict]) -> bool:
    """Summarize gateway presence from narrow SVI address scalars."""
    for fact in svi_facts:
        raw_ip = str(fact.get('svi_ip') or '').strip()
        if not raw_ip:
            continue
        try:
            if '/' in raw_ip:
                ipaddress.ip_interface(raw_ip)
            else:
                ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        return True
    return False


def _load_vlan_page_endpoint_details(conn, candidates: list[dict]) -> dict[tuple[str, int, str], list[dict]]:
    """Load endpoint arrays only for page keys, in two bounded set queries."""
    keys = sorted({
        (str(row.get('_scope_site') or ''), int(row.get('vlan_id') or 0), str(row.get('device_id') or ''))
        for row in candidates
    })
    details: dict[tuple[str, int, str], list[dict]] = {key: [] for key in keys}
    if not keys:
        return details

    site_expression = _device_site_expression('d')
    predicates: list[str] = []
    params: list = []
    for scope_site, vlan_number, device_id in keys:
        predicate = f"(x.vlan_id = ? AND {site_expression} = ?"
        params.extend((vlan_number, scope_site))
        if device_id:
            predicate += " AND x.device_id = ?"
            params.append(device_id)
        predicates.append(predicate + ")")
    where = " OR ".join(predicates)
    # Include scope and VLAN in the result key so duplicate hostnames cannot
    # leak endpoint evidence across otherwise distinct page candidates.
    arp_rows = conn.execute(
        f"""SELECT {site_expression} AS site_scope, x.vlan_id, x.device_id,
                   x.ip_address, x.mac_address, x.interface_name,
                   x.last_updated, d.hostname AS device_hostname, d.ip_address AS device_ip
            FROM arp_table x JOIN devices d ON d.id = x.device_id
            WHERE {where}
            ORDER BY x.ip_address, d.hostname""",
        tuple(params),
    ).fetchall()
    for row in arp_rows:
        key = (str(row['site_scope'] or ''), int(row['vlan_id'] or 0), str(row['device_id'] or ''))
        if key not in details:
            continue
        value = {
            'source': 'arp',
            'ip_address': str(row['ip_address'] or ''),
            'mac_address': str(row['mac_address'] or ''),
            'interface_name': str(row['interface_name'] or ''),
            'device_hostname': str(row['device_hostname'] or ''),
            'device_ip': str(row['device_ip'] or ''),
            'last_updated': row['last_updated'],
        }
        identity = (value['source'], value['ip_address'], value['mac_address'], value['device_hostname'])
        if not any((item['source'], item['ip_address'], item['mac_address'], item['device_hostname']) == identity for item in details[key]):
            details[key].append(value)

    mac_rows = conn.execute(
        f"""SELECT {site_expression} AS site_scope, x.vlan_id, x.device_id,
                   x.mac_address, x.interface_name, x.last_updated,
                   d.hostname AS device_hostname, d.ip_address AS device_ip
            FROM mac_table x JOIN devices d ON d.id = x.device_id
            WHERE {where}
            ORDER BY x.mac_address, d.hostname""",
        tuple(params),
    ).fetchall()
    for row in mac_rows:
        key = (str(row['site_scope'] or ''), int(row['vlan_id'] or 0), str(row['device_id'] or ''))
        if key not in details:
            continue
        value = {
            'source': 'mac',
            'ip_address': '',
            'mac_address': str(row['mac_address'] or ''),
            'interface_name': str(row['interface_name'] or ''),
            'device_hostname': str(row['device_hostname'] or ''),
            'device_ip': str(row['device_ip'] or ''),
            'last_updated': row['last_updated'],
        }
        identity = (value['source'], '', value['mac_address'], f"{value['device_hostname']}:{value['interface_name']}")
        if not any((item['source'], item['ip_address'], item['mac_address'],
                    f"{item['device_hostname']}:{item['interface_name']}") == identity for item in details[key]):
            details[key].append(value)
    return details


def _list_vlans_page(
    conn,
    site_id: str,
    tenant_id: str,
    *,
    device_scoped: bool,
    q: str,
    status: str,
    asset_type: str,
    device_category: str,
    device_role: str,
    page: int,
    page_size: int,
    include_details: bool,
    all_rows: bool = False,
    detail_vlan_pk: str | None = None,
    detail_device_id: str = '',
) -> dict:
    """Build skinny page candidates and materialize display rows only for the page."""
    from services.vlan_discovery_service import is_system_default_vlan, parse_vlan_id_from_interface, parse_vlan_values

    where, filter_params = _vlan_list_filter_sql(site_id, tenant_id, q, status)
    vlan_rows = conn.execute(
        f"""SELECT v.id, v.vlan_id, v.name, v.site_id, v.tenant_id, v.status,
                   v.discovery_source
            FROM vlans v{where} ORDER BY v.vlan_id""",
        filter_params,
    ).fetchall()
    raw_vlans = [_row_to_dict(row) for row in vlan_rows]
    snapshot_projection = _current_vlan_snapshot_projection(
        conn, tenant_id=tenant_id or None, site_id=site_id,
    )
    snapshot_vlan_rows = snapshot_projection['vlan_observations']
    snapshot_port_rows = snapshot_projection['vlan_ports']
    snapshot_interface_rows = snapshot_projection['interface_observations']
    canonical_vlan_keys = {
        (str(row['site_id'] or ''), int(row['vlan_id'] or 0))
        for row in conn.execute("SELECT site_id, vlan_id FROM vlans").fetchall()
    }
    synthetic_vlan_rows: dict[str, dict] = {}
    q_value = str(q or '').strip().lower()
    snapshot_interfaces_by_device: dict[str, list[dict]] = {}
    for observation in snapshot_interface_rows:
        snapshot_interfaces_by_device.setdefault(str(observation.get('device_id') or ''), []).append(observation)
    snapshot_ports_by_device_vlan: dict[tuple[str, int], list[dict]] = {}
    for port in snapshot_port_rows:
        snapshot_ports_by_device_vlan.setdefault(
            (str(port.get('device_id') or ''), int(port.get('vlan_id') or 0)), []
        ).append(port)
    for observation in snapshot_vlan_rows:
        scope_site = str(observation.get('resolved_site_id') or '')
        vlan_number = int(observation.get('vlan_id') or 0)
        if (scope_site, vlan_number) in canonical_vlan_keys:
            continue
        observed_status = str(observation.get('vlan_status') or '')
        if status and status != 'all' and observed_status != status:
            continue
        search_parts = [
            str(vlan_number), str(observation.get('vlan_name') or ''),
            str(observation.get('device_hostname') or ''), str(observation.get('device_ip') or ''),
        ]
        search_parts.extend(
            str(port.get('interface_name') or '')
            for port in snapshot_ports_by_device_vlan.get((str(observation.get('device_id') or ''), vlan_number), [])
        )
        for interface in snapshot_interfaces_by_device.get(str(observation.get('device_id') or ''), []):
            if parse_vlan_id_from_interface(interface.get('interface_name')) == vlan_number:
                search_parts.extend((
                    str(interface.get('interface_name') or ''),
                    str(interface.get('description') or ''),
                    str(interface.get('ip_address') or ''),
                ))
        if q_value and q_value not in ' '.join(search_parts).lower():
            continue
        synthetic_id = f"cmdb-vlan-observed:{scope_site or 'unassigned'}:{vlan_number}"
        synthetic_vlan_rows.setdefault(synthetic_id, {
            'id': synthetic_id,
            'vlan_id': vlan_number,
            'name': str(observation.get('vlan_name') or ''),
            'site_id': scope_site,
            'tenant_id': str(observation.get('tenant_id') or tenant_id or _DEFAULT_TENANT),
            'status': observed_status or 'active',
            'discovery_source': 'vlan_command',
            'cmdb_observed_only': True,
        })
    raw_vlans.extend(synthetic_vlan_rows.values())

    site_platforms: dict[str, set[str]] = {}
    for device in conn.execute(
        f"SELECT {_device_site_expression('d')} AS site_id, d.platform, d.vendor FROM devices d"
    ).fetchall():
        scope = str(device['site_id'] or '')
        site_platforms.setdefault(scope, set()).add(str(device['platform'] or device['vendor'] or ''))
    filtered_vlans = []
    for vlan in raw_vlans:
        scope_site = str(vlan.get('site_id') or '')
        platform = next(
            (value for value in site_platforms.get(scope_site, set())
             if any(token in value.lower() for token in ('cisco', 'ios', 'nxos'))),
            '',
        )
        if not is_system_default_vlan(
            vlan.get('vlan_id'), vlan.get('name'), platform=platform,
            discovery_source=vlan.get('discovery_source'),
        ):
            filtered_vlans.append(vlan)
    if detail_vlan_pk:
        filtered_vlans = [row for row in filtered_vlans if str(row.get('id') or '') == str(detail_vlan_pk)]

    vlan_pks = [str(row['id']) for row in filtered_vlans if row.get('id')]
    vlan_numbers = sorted({int(row.get('vlan_id') or 0) for row in filtered_vlans})
    scope_sites = sorted({str(row.get('site_id') or '') for row in filtered_vlans})
    if not vlan_pks:
        vlan_pk_placeholders = ''
        vlan_number_placeholders = ''
        site_placeholders = ''
    else:
        vlan_pk_placeholders = ','.join('?' for _ in vlan_pks)
        vlan_number_placeholders = ','.join('?' for _ in vlan_numbers)
        site_placeholders = ','.join('?' for _ in scope_sites)

    sites_by_id: dict[str, dict] = {}
    named_scope_sites = [scope for scope in scope_sites if scope]
    if named_scope_sites:
        placeholders = ','.join('?' for _ in named_scope_sites)
        sites_by_id = {
            str(row['id']): _row_to_dict(row)
            for row in conn.execute(
                f"SELECT id, site_code, site_name FROM sites WHERE id IN ({placeholders})",
                tuple(named_scope_sites),
            ).fetchall()
        }

    # Interface membership is parsed once into a skinny index. Display fields
    # are loaded below only for selected page candidate interface IDs.
    member_by_scope_vlan_device: dict[tuple[str, int, str], dict[str, object]] = {}
    member_by_scope_vlan: dict[tuple[str, int], dict[str, object]] = {}
    snapshot_member_rows_by_id: dict[str, dict] = {}
    shared_interface_by_identity: dict[tuple[str, str], dict] = {}

    def add_member(scope_site: str, vlan_number: int, device_id: str, role: str, fact: dict) -> None:
        device_key = (scope_site, int(vlan_number), device_id)
        device_members = member_by_scope_vlan_device.setdefault(
            device_key, {'svi_rows': [], 'access_rows': [], 'device_ids': set()}
        )
        member_members = member_by_scope_vlan.setdefault(
            device_key[:2], {'svi_rows': [], 'access_rows': [], 'device_ids': set()}
        )
        if not any(str(existing.get('id') or '') == str(fact.get('id') or '') for existing in device_members[role]):
            device_members[role].append(fact)
        if not any(
            str(existing.get('id') or '') == str(fact.get('id') or '')
            and str(existing.get('device_id') or '') == device_id
            for existing in member_members[role]
        ):
            member_members[role].append(fact)
        device_members['device_ids'].add(device_id)
        member_members['device_ids'].add(device_id)

    if vlan_numbers and scope_sites:
        site_expression = _device_site_expression('d')
        interface_rows = conn.execute(
            f"""SELECT {site_expression} AS site_scope, i.id, i.device_id,
                       i.interface_name,
                       i.description,
                       NULLIF(TRIM(COALESCE(i.description, '')), '') IS NULL AS description_is_empty,
                       COALESCE(NULLIF(i.primary_ip, ''), NULLIF(i.ip_address, ''), '') AS svi_ip,
                       i.access_vlan, i.native_vlan, i.allowed_vlans
                FROM interfaces i JOIN devices d ON d.id = i.device_id
                WHERE {site_expression} IN ({site_placeholders})
                ORDER BY d.hostname, i.interface_name""",
            tuple(scope_sites),
        ).fetchall()
        requested_numbers = set(vlan_numbers)
        for row in interface_rows:
            scope_site = str(row['site_scope'] or '')
            device_id = str(row['device_id'] or '')
            svi_vlan = parse_vlan_id_from_interface(row['interface_name'])
            identity = _interface_identity(device_id, row['interface_name'])
            member_numbers = (
                parse_vlan_values(row['access_vlan'])
                | parse_vlan_values(row['native_vlan'])
                | parse_vlan_values(row['allowed_vlans'])
            ) & requested_numbers
            interface_fact = {
                'id': str(row['id'] or ''),
                'device_id': device_id,
                'interface_name': str(row['interface_name'] or ''),
                'description': str(row['description'] or ''),
                'description_is_empty': bool(row['description_is_empty']),
                'svi_ip': str(row['svi_ip'] or ''),
                'port_mode': 'unknown',
                'tagging': 'unknown',
            }
            shared_interface_by_identity.setdefault(identity, interface_fact)
            has_interface_snapshot = device_id in snapshot_projection['successful']['interface_inventory']
            has_vlan_snapshot = device_id in snapshot_projection['successful']['vlan_inventory']
            if svi_vlan in requested_numbers and not has_interface_snapshot:
                add_member(scope_site, int(svi_vlan), device_id, 'svi_rows', interface_fact)
            if not has_vlan_snapshot:
                for member_vlan in member_numbers:
                    if svi_vlan != member_vlan:
                        add_member(scope_site, int(member_vlan), device_id, 'access_rows', interface_fact)

        for observation in snapshot_interface_rows:
            device_id = str(observation.get('device_id') or '')
            scope_site = str(snapshot_projection['successful']['interface_inventory'][device_id].get('resolved_site_id') or '')
            svi_vlan = parse_vlan_id_from_interface(observation.get('interface_name'))
            if svi_vlan not in requested_numbers:
                continue
            observed_id = f"cmdb-interface-observed:{device_id}:{observation.get('normalized_interface_name') or ''}"
            fact = {
                'id': observed_id,
                'device_id': device_id,
                'interface_name': str(observation.get('interface_name') or ''),
                'description': str(observation.get('description') or ''),
                'description_is_empty': not bool(str(observation.get('description') or '').strip()),
                'svi_ip': str(observation.get('ip_address') or ''),
                'primary_ip': str(observation.get('ip_address') or ''),
                'ip_address': str(observation.get('ip_address') or ''),
                'ip_prefix_length': observation.get('ip_prefix_length'),
                'last_seen': observation.get('observed_at'),
                'port_mode': 'unknown',
                'tagging': 'unknown',
                'source': 'cmdb_cli_snapshot',
            }
            snapshot_member_rows_by_id[observed_id] = fact
            add_member(scope_site, int(svi_vlan), device_id, 'svi_rows', fact)

        for port in snapshot_port_rows:
            scope_site = str(port.get('resolved_site_id') or '')
            vlan_number = int(port.get('vlan_id') or 0)
            device_id = str(port.get('device_id') or '')
            if scope_site not in scope_sites or vlan_number not in requested_numbers:
                continue
            identity = _interface_identity(device_id, port.get('normalized_interface_name'))
            interface_observation = snapshot_projection['interface_by_device_identity'].get(identity)
            shared_fact = shared_interface_by_identity.get(identity, {})
            if device_id in snapshot_projection['successful']['interface_inventory']:
                description = str(interface_observation.get('description') or '') if interface_observation else ''
            else:
                description = str(shared_fact.get('description') or '')
            observed_id = (
                f"cmdb-vlan-port-observed:{device_id}:{vlan_number}:"
                f"{port.get('normalized_interface_name') or ''}"
            )
            fact = {
                'id': observed_id,
                'device_id': device_id,
                'interface_name': str(port.get('interface_name') or ''),
                'description': description,
                'description_is_empty': not bool(description.strip()),
                'svi_ip': '',
                'primary_ip': '',
                'ip_address': '',
                'ip_prefix_length': None,
                'last_seen': port.get('observed_at'),
                'port_mode': str(port.get('port_mode') or 'unknown'),
                'tagging': str(port.get('tagging') or 'unknown'),
                'source': 'cmdb_cli_snapshot',
            }
            snapshot_member_rows_by_id[observed_id] = fact
            add_member(scope_site, vlan_number, device_id, 'access_rows', fact)

    observation_by_scope_vlan_device: dict[tuple[str, int], dict[str, dict]] = {}
    arp_by_scope_vlan_device: dict[tuple[str, int], dict[str, dict]] = {}
    mac_by_scope_vlan_device: dict[tuple[str, int], dict[str, dict]] = {}
    site_expression = _device_site_expression('d')
    if vlan_numbers and scope_sites:
        for row in snapshot_vlan_rows:
            scope_site = str(row.get('resolved_site_id') or '')
            vlan_number = int(row.get('vlan_id') or 0)
            if scope_site in scope_sites and vlan_number in set(vlan_numbers):
                key = (scope_site, vlan_number)
                observation_by_scope_vlan_device.setdefault(key, {})[str(row['device_id'])] = row
        for table, target in (('arp_table', arp_by_scope_vlan_device), ('mac_table', mac_by_scope_vlan_device)):
            aggregate_rows = conn.execute(
                f"""SELECT {site_expression} AS site_scope, x.vlan_id, x.device_id,
                           COUNT(*) AS count, MAX(x.last_updated) AS last_updated
                    FROM {table} x JOIN devices d ON d.id = x.device_id
                    WHERE x.vlan_id IN ({vlan_number_placeholders})
                      AND {site_expression} IN ({site_placeholders})
                    GROUP BY {site_expression}, x.vlan_id, x.device_id""",
                (*vlan_numbers, *scope_sites),
            ).fetchall()
            for row in aggregate_rows:
                key = (str(row['site_scope'] or ''), int(row['vlan_id'] or 0))
                target.setdefault(key, {})[str(row['device_id'])] = {
                    'count': int(row['count'] or 0), 'last_updated': row['last_updated'],
                }

    prefix_gateway_by_vlan: dict[str, str] = {}
    if vlan_pks:
        for row in conn.execute(
            f"""SELECT p.vlan_id, p.gateway
                FROM prefixes p WHERE p.vlan_id IN ({vlan_pk_placeholders})
                  AND NULLIF(p.gateway, '') IS NOT NULL
                ORDER BY p.prefix""",
            tuple(vlan_pks),
        ).fetchall():
            prefix_gateway_by_vlan.setdefault(str(row['vlan_id'] or ''), str(row['gateway'] or ''))

    business_count_by_scope_vlan: dict[tuple[int, str], int] = {}
    if vlan_numbers and scope_sites:
        for row in conn.execute(
            f"""SELECT vlan_id, site_id, COUNT(*) AS count
                FROM vlan_business_bindings
                WHERE vlan_id IN ({vlan_number_placeholders})
                  AND site_id IN ({site_placeholders}) AND status <> 'retired'
                GROUP BY vlan_id, site_id""",
            (*vlan_numbers, *scope_sites),
        ).fetchall():
            business_count_by_scope_vlan[(int(row['vlan_id'] or 0), str(row['site_id'] or ''))] = int(row['count'] or 0)

    all_candidate_device_ids: set[str] = set()
    candidate_specs: list[dict] = []
    for vlan in filtered_vlans:
        vlan_pk = str(vlan.get('id') or '')
        vlan_number = int(vlan.get('vlan_id') or 0)
        scope_site = str(vlan.get('site_id') or '')
        vlan_scope_key = (scope_site, vlan_number)
        device_ids = set(member_by_scope_vlan.get(vlan_scope_key, {}).get('device_ids') or set())
        device_ids.update(observation_by_scope_vlan_device.get(vlan_scope_key, {}))
        device_ids.update(arp_by_scope_vlan_device.get(vlan_scope_key, {}))
        device_ids.update(mac_by_scope_vlan_device.get(vlan_scope_key, {}))
        all_candidate_device_ids.update(device_ids)
        site_vlan_members = member_by_scope_vlan.get(vlan_scope_key, {'svi_rows': [], 'access_rows': []})
        site_svi_count = len({str(row['interface_name']) for row in site_vlan_members['svi_rows']})
        if device_scoped and device_ids:
            for device_id in sorted(device_ids):
                member = member_by_scope_vlan_device.get((scope_site, vlan_number, device_id), {'svi_rows': [], 'access_rows': []})
                candidate_specs.append({
                    '_vlan_pk': vlan_pk,
                    '_scope_site': scope_site,
                    'vlan_id': vlan_number,
                    'device_id': device_id,
                    '_summary_gateway': _vlan_svi_gateway_present(member['svi_rows']),
                    '_summary_arp': int(arp_by_scope_vlan_device.get(vlan_scope_key, {}).get(device_id, {}).get('count') or 0),
                    '_summary_mac': int(mac_by_scope_vlan_device.get(vlan_scope_key, {}).get(device_id, {}).get('count') or 0),
                    '_summary_business': business_count_by_scope_vlan.get((vlan_number, scope_site), 0),
                    '_summary_svi_count': site_svi_count,
                    '_summary_port_count': len(member['access_rows']),
                    '_summary_undocumented_ports': sum(1 for row in member['access_rows'] if row['description_is_empty']),
                })
        else:
            member = member_by_scope_vlan.get(vlan_scope_key, {'svi_rows': [], 'access_rows': []})
            gateway = prefix_gateway_by_vlan.get(vlan_pk, '')
            if not gateway:
                gateway = next((str(row['svi_ip'] or '').split('/', 1)[0].strip()
                                for row in member['svi_rows'] if str(row['svi_ip'] or '').strip()), '')
            candidate_specs.append({
                '_vlan_pk': vlan_pk,
                '_scope_site': scope_site,
                'site_id': scope_site,
                'vlan_id': vlan_number,
                '_summary_gateway': bool(str(gateway or '').strip()),
                '_summary_arp': sum(int(row.get('count') or 0) for row in arp_by_scope_vlan_device.get(vlan_scope_key, {}).values()),
                '_summary_mac': sum(int(row.get('count') or 0) for row in mac_by_scope_vlan_device.get(vlan_scope_key, {}).values()),
                '_summary_business': business_count_by_scope_vlan.get((vlan_number, scope_site), 0),
                '_summary_svi_count': site_svi_count,
                '_summary_port_count': len(member['access_rows']),
                '_summary_undocumented_ports': sum(1 for row in member['access_rows'] if row['description_is_empty']),
            })

    device_metadata: dict[str, dict] = {}
    if all_candidate_device_ids:
        device_ids = sorted(all_candidate_device_ids)
        for start in range(0, len(device_ids), 500):
            batch = device_ids[start:start + 500]
            placeholders = ','.join('?' for _ in batch)
            for row in conn.execute(
                f"""SELECT d.id, d.hostname, d.ip_address,
                           COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''), NULLIF(d.site, ''), 'unassigned') AS resolved_site_id,
                           COALESCE(NULLIF(pa.asset_type, ''), 'network_device') AS asset_type,
                           COALESCE(NULLIF(pa.device_category, ''), NULLIF(d.device_category, ''), 'other') AS device_category,
                           COALESCE(NULLIF(pa.device_role, ''), NULLIF(d.role, ''), 'unassigned') AS device_role
                    FROM devices d LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                    WHERE d.id IN ({placeholders})""",
                tuple(batch),
            ).fetchall():
                device_metadata[str(row['id'])] = dict(row)

    for candidate in candidate_specs:
        device_id = str(candidate.get('device_id') or '')
        vlan_pk = str(candidate['_vlan_pk'])
        scope_site = str(candidate['_scope_site'])
        vlan_number = int(candidate.get('vlan_id') or 0)
        site = sites_by_id.get(scope_site, {})
        candidate['site_code'] = site.get('site_code') or ''
        candidate['site_name'] = site.get('site_name') or ''
        candidate['asset_type'] = 'network_device'
        candidate['device_category'] = 'other'
        candidate['device_role'] = 'unassigned'
        if device_id:
            device = device_metadata.get(device_id, {})
            candidate['device_hostname'] = str(device.get('hostname') or device_id)
            candidate['device_ip'] = str(device.get('ip_address') or '')
            candidate['asset_type'] = device.get('asset_type') or 'network_device'
            candidate['device_category'] = device.get('device_category') or 'other'
            candidate['device_role'] = device.get('device_role') or 'unassigned'
            candidate['site_id'] = device.get('resolved_site_id') or scope_site or ''
        else:
            candidate['device_hostname'] = ''
            candidate['device_ip'] = ''

    full_candidates = sorted(
        candidate_specs,
        key=lambda row: (
            str(row.get('device_hostname') or '').lower(),
            int(row.get('vlan_id') or 0),
            str(row.get('device_ip') or ''),
        ),
    )
    filtered_candidates = [
        row for row in full_candidates
        if (not asset_type or str(row.get('asset_type') or 'network_device') == asset_type)
        and (not device_category or str(row.get('device_category') or 'other') == device_category)
        and (not device_role or str(row.get('device_role') or 'unassigned') == device_role)
    ]
    if detail_device_id:
        filtered_candidates = [
            row for row in filtered_candidates
            if str(row.get('device_id') or '') == str(detail_device_id)
        ]
    normalized_page_size = max(1, len(filtered_candidates)) if all_rows else min(max(int(page_size or 20), 1), 100)
    normalized_page = max(int(page or 1), 1)
    start = (normalized_page - 1) * normalized_page_size
    page_candidates = filtered_candidates[start:start + normalized_page_size]

    def _page_candidate_key(candidate: dict) -> tuple[str, str, int, str]:
        return (
            str(candidate['_vlan_pk']),
            str(candidate['_scope_site']),
            int(candidate.get('vlan_id') or 0),
            str(candidate.get('device_id') or '') if device_scoped else '',
        )

    page_members: dict[tuple[str, str, int, str], dict[str, list]] = {
        _page_candidate_key(candidate): {'svi_rows': [], 'access_rows': []}
        for candidate in page_candidates
    }
    page_interface_roles: dict[str, list[tuple[tuple[str, str, int, str], str]]] = {}
    for candidate in page_candidates:
        candidate_key = _page_candidate_key(candidate)
        scope_site = str(candidate['_scope_site'])
        vlan_number = int(candidate.get('vlan_id') or 0)
        device_id = str(candidate.get('device_id') or '')
        if device_scoped and device_id:
            narrow_members = member_by_scope_vlan_device.get(
                (scope_site, vlan_number, device_id), {'svi_rows': [], 'access_rows': []}
            )
        else:
            narrow_members = member_by_scope_vlan.get(
                (scope_site, vlan_number), {'svi_rows': [], 'access_rows': []}
            )
        for role in ('svi_rows', 'access_rows'):
            for fact in narrow_members[role]:
                interface_id = str(fact['id'] or '')
                if interface_id:
                    page_interface_roles.setdefault(interface_id, []).append((candidate_key, role))

    page_svi_device_ids: set[str] = set()
    for interface_id, fact in snapshot_member_rows_by_id.items():
        roles = page_interface_roles.get(interface_id, [])
        if not roles:
            continue
        device_id = str(fact.get('device_id') or '')
        device = device_metadata.get(device_id, {})
        wide_row = dict(fact)
        wide_row['device_hostname'] = device.get('hostname') or device_id
        wide_row['device_ip'] = device.get('ip_address') or ''
        for candidate_key, role in roles:
            page_members[candidate_key][role].append(wide_row)
            if role == 'svi_rows' and device_id:
                page_svi_device_ids.add(device_id)
    selected_interface_ids = sorted(
        interface_id for interface_id in page_interface_roles
        if interface_id not in snapshot_member_rows_by_id
    )
    page_site_expression = _device_site_expression('d')
    for start_index in range(0, len(selected_interface_ids), 500):
        batch = selected_interface_ids[start_index:start_index + 500]
        placeholders = ','.join('?' for _ in batch)
        for row in conn.execute(
            f"""SELECT {page_site_expression} AS site_scope, i.id, i.device_id,
                       i.interface_name, i.description, i.primary_ip, i.ip_address,
                       i.ip_prefix_length, i.access_vlan, i.native_vlan, i.allowed_vlans,
                       i.last_seen
                FROM interfaces i JOIN devices d ON d.id = i.device_id
                WHERE i.id IN ({placeholders})
                ORDER BY d.hostname, i.interface_name""",
            tuple(batch),
        ).fetchall():
            wide_row = _row_to_dict(row)
            device_id = str(wide_row.get('device_id') or '')
            device = device_metadata.get(device_id, {})
            wide_row['device_hostname'] = device.get('hostname')
            wide_row['device_ip'] = device.get('ip_address')
            interface_id = str(wide_row.get('id') or '')
            for candidate_key, role in page_interface_roles.get(interface_id, []):
                page_members[candidate_key][role].append(wide_row)
                if role == 'svi_rows' and device_id:
                    page_svi_device_ids.add(device_id)

    ip_inventory_by_device: dict[str, dict[str, str]] = {}
    if page_svi_device_ids:
        selected_svi_devices = sorted(page_svi_device_ids)
        for start_index in range(0, len(selected_svi_devices), 500):
            batch = selected_svi_devices[start_index:start_index + 500]
            placeholders = ','.join('?' for _ in batch)
            for row in conn.execute(
                f"""SELECT device_id, interface, mask FROM ip_inventory
                    WHERE device_id IN ({placeholders})
                      AND NOT EXISTS (
                          SELECT 1 FROM cmdb_collection_snapshots s
                          WHERE s.device_id = ip_inventory.device_id
                            AND s.domain = 'interface_inventory'
                            AND s.successful_generation > 0
                      )""",
                tuple(batch),
            ).fetchall():
                device_id = str(row['device_id'] or '')
                interface_name = _normalize_interface_name_cached(row['interface'])
                if interface_name:
                    ip_inventory_by_device.setdefault(device_id, {})[interface_name] = str(row['mask'] or '').strip()

    for members in page_members.values():
        for role in ('svi_rows', 'access_rows'):
            members[role].sort(key=lambda row: (
                row['device_hostname'] is None,
                str(row['device_hostname'] or ''),
                row['interface_name'] is None,
                str(row['interface_name'] or ''),
            ))

    site_counts: dict[str, dict[str, object]] = {}
    for row in filtered_candidates:
        site_key = str(row.get('site_id') or '').strip() or 'unassigned'
        entry = site_counts.setdefault(site_key, {
            'key': site_key,
            'label': str(row.get('site_name') or row.get('site_code') or '未分配站点'),
            'count': 0,
        })
        entry['count'] = int(entry['count']) + 1
    summary = {
        'total': len({(str(row.get('site_id') or ''), int(row.get('vlan_id') or 0)) for row in filtered_candidates}),
        'gateways': sum(1 for row in filtered_candidates if row['_summary_gateway']),
        'arp': sum(int(row['_summary_arp'] or 0) for row in filtered_candidates),
        'mac': sum(int(row['_summary_mac'] or 0) for row in filtered_candidates),
        'unbound': sum(1 for row in filtered_candidates if not int(row['_summary_business'] or 0)),
    }

    selected_vlan_pks = sorted({str(row['_vlan_pk']) for row in page_candidates})
    selected_vlan_numbers = sorted({int(row['vlan_id']) for row in page_candidates})
    selected_scope_sites = sorted({str(row['_scope_site']) for row in page_candidates})
    page_vlan_rows: dict[str, dict] = {}
    selected_vlan_placeholders = ','.join('?' for _ in selected_vlan_pks)
    if selected_vlan_pks:
        page_vlan_rows = {
            str(row['id']): _row_to_dict(row)
            for row in conn.execute(
                f"SELECT v.* FROM vlans v WHERE v.id IN ({selected_vlan_placeholders})",
                tuple(selected_vlan_pks),
            ).fetchall()
        }
        page_vlan_rows.update({
            vlan_pk: synthetic_vlan_rows[vlan_pk]
            for vlan_pk in selected_vlan_pks
            if vlan_pk in synthetic_vlan_rows
        })

    prefixes_by_vlan_pk: dict[str, list] = {}
    ip_count_by_prefix: dict[str, int] = {}
    if selected_vlan_pks:
        prefix_rows = conn.execute(
            f"""SELECT p.id, p.vlan_id, p.prefix, p.gateway, p.vrf_id,
                       v.vrf_name, gd.hostname AS gateway_device_name,
                       gi.interface_name AS gateway_interface_name
                FROM prefixes p LEFT JOIN vrfs v ON v.id = p.vrf_id
                LEFT JOIN devices gd ON gd.id = p.gateway_device_id
                LEFT JOIN interfaces gi ON gi.id = p.gateway_interface_id
                WHERE p.vlan_id IN ({selected_vlan_placeholders})
                ORDER BY p.prefix""",
            tuple(selected_vlan_pks),
        ).fetchall()
        for row in prefix_rows:
            prefix = _row_to_dict(row)
            prefixes_by_vlan_pk.setdefault(str(prefix.get('vlan_id') or ''), []).append(prefix)
        prefix_ids = sorted({str(row['id']) for row in prefix_rows if row['id']})
        if prefix_ids:
            prefix_placeholders = ','.join('?' for _ in prefix_ids)
            ip_count_by_prefix = {
                str(row['prefix_id']): int(row['count'] or 0)
                for row in conn.execute(
                    f"SELECT prefix_id, COUNT(*) AS count FROM ip_addresses WHERE prefix_id IN ({prefix_placeholders}) GROUP BY prefix_id",
                    tuple(prefix_ids),
                ).fetchall()
            }

    bindings_by_vlan_scope: dict[tuple[int, str], list] = {}
    if selected_vlan_numbers and selected_scope_sites:
        number_placeholders = ','.join('?' for _ in selected_vlan_numbers)
        scope_placeholders = ','.join('?' for _ in selected_scope_sites)
        for row in conn.execute(
            f"""SELECT vlan_id, site_id, business_system, department, owner, business_level
                FROM vlan_business_bindings
                WHERE vlan_id IN ({number_placeholders}) AND site_id IN ({scope_placeholders})
                  AND status <> 'retired' ORDER BY business_system""",
            (*selected_vlan_numbers, *selected_scope_sites),
        ).fetchall():
            binding = _row_to_dict(row)
            key = (int(binding.get('vlan_id') or 0), str(binding.get('site_id') or ''))
            bindings_by_vlan_scope.setdefault(key, []).append(binding)

    endpoint_details_by_candidate = _load_vlan_page_endpoint_details(conn, page_candidates) if include_details else {}
    display_rows: list[dict] = []
    base_items: dict[str, dict] = {}
    for candidate in page_candidates:
        vlan_pk = str(candidate['_vlan_pk'])
        vlan = page_vlan_rows.get(vlan_pk)
        if vlan is None:
            continue
        if vlan_pk not in base_items:
            item = dict(vlan)
            scope_site = str(candidate['_scope_site'])
            site = sites_by_id.get(scope_site)
            item['site_code'] = site.get('site_code') if site else ''
            item['site_name'] = site.get('site_name') if site else ''
            prefix_rows = prefixes_by_vlan_pk.get(vlan_pk, [])
            prefix_ids = [str(row['id']) for row in prefix_rows if row.get('id')]
            item['prefix_count'] = len(prefix_rows)
            item['prefixes'] = ', '.join(str(row.get('prefix') or '') for row in prefix_rows if row.get('prefix'))
            item['ip_count'] = sum(ip_count_by_prefix.get(prefix_id, 0) for prefix_id in prefix_ids)
            gateway = next((row for row in prefix_rows if row.get('gateway')), None)
            item['gateway'] = gateway.get('gateway') if gateway else ''
            item['gateway_device'] = gateway.get('gateway_device_name') if gateway else ''
            item['gateway_interface'] = gateway.get('gateway_interface_name') if gateway else ''
            item['vrf_name'] = gateway.get('vrf_name') if gateway else ''
            bindings = bindings_by_vlan_scope.get((int(item.get('vlan_id') or 0), scope_site), [])
            item['business_count'] = len(bindings)
            item['business_systems'] = ', '.join(str(row['business_system'] or '') for row in bindings)
            item['business_departments'] = ', '.join(sorted({str(row['department'] or '') for row in bindings if row['department']}))
            item['business_owners'] = ', '.join(sorted({str(row['owner'] or '') for row in bindings if row['owner']}))
            item['highest_business_level'] = next(
                (level for level in ('P1', 'P2', 'P3', 'P4') if any(row['business_level'] == level for row in bindings)),
                '',
            )
            base_items[vlan_pk] = item

        item = dict(base_items[vlan_pk])
        scope_site = str(candidate['_scope_site'])
        vlan_number = int(candidate['vlan_id'])
        device_id = str(candidate.get('device_id') or '')
        if device_scoped and device_id:
            device_info = device_metadata.get(device_id, {})
            members = page_members.get(_page_candidate_key(candidate), {'svi_rows': [], 'access_rows': []})
            svi_rows = members['svi_rows']
            access_rows = members['access_rows']
            gateways, prefixes = _vlan_svi_networks(svi_rows, ip_inventory_by_device.get(device_id, {}))
            vlan_observation = observation_by_scope_vlan_device.get((scope_site, vlan_number), {}).get(device_id)
            arp_summary = arp_by_scope_vlan_device.get((scope_site, vlan_number), {}).get(device_id, {})
            mac_summary = mac_by_scope_vlan_device.get((scope_site, vlan_number), {}).get(device_id, {})
            device_hostname = str(candidate.get('device_hostname') or device_id)
            device_ip = str(candidate.get('device_ip') or '')
            interface_times = [row['last_seen'] for row in (*svi_rows, *access_rows) if row['last_seen']]
            arp_time = arp_summary.get('last_updated')
            mac_time = mac_summary.get('last_updated')
            item.update({
                'device_id': device_id,
                'device_hostname': device_hostname,
                'device_ip': device_ip,
                'asset_type': device_info.get('asset_type') or 'network_device',
                'device_category': device_info.get('device_category') or 'other',
                'device_role': device_info.get('device_role') or 'unassigned',
                'device_vlan_name': str(vlan_observation['vlan_name'] or '') if vlan_observation else '',
                'device_vlan_status': str(vlan_observation['vlan_status'] or '') if vlan_observation else '',
                'device_vlan_observed_at': str(vlan_observation['observed_at'] or '') if vlan_observation else '',
                'device_vlan_generation': int(vlan_observation['generation'] or 0) if vlan_observation else 0,
                'site_id': device_info.get('resolved_site_id') or item.get('site_id') or '',
                'device_count': 1,
                'device_names': device_hostname,
                'port_count': len(access_rows),
                'svi_count': int(candidate.get('_summary_svi_count') or 0),
                'undocumented_port_count': sum(1 for row in access_rows if not str(row['description'] or '').strip()),
                'svi_interfaces': ', '.join(str(row['interface_name'] or '') for row in svi_rows),
                'description': '; '.join(sorted({str(row['description'] or '') for row in svi_rows if row['description']})),
                'prefixes': ', '.join(prefixes),
                'gateway': gateways[0] if gateways else '',
                'gateway_device': device_hostname if gateways else '',
                'gateway_interface': str(svi_rows[0]['interface_name'] or '') if gateways and svi_rows else '',
                'arp_count': int(arp_summary.get('count') or 0),
                'mac_count': int(mac_summary.get('count') or 0),
                'endpoint_last_seen_at': max([value for value in (arp_time, mac_time) if value] or ['']),
                'interface_collected_at': max(interface_times) if interface_times else '',
                'arp_collected_at': arp_time or '',
                'mac_collected_at': mac_time or '',
            })
            if include_details:
                item['port_detail_rows'] = [{
                    'device_id': device_id,
                    'device_hostname': device_hostname,
                    'device_ip': device_ip,
                    'interface_name': str(row['interface_name'] or ''),
                    'description': str(row['description'] or ''),
                    **({
                        'port_mode': str(row.get('port_mode') or 'unknown'),
                        'tagging': str(row.get('tagging') or 'unknown'),
                        'source': 'cmdb_cli_snapshot',
                    } if row.get('source') == 'cmdb_cli_snapshot' else {}),
                } for row in access_rows]
                item['port_details'] = '; '.join(
                    f"{device_hostname}:{row['interface_name']} - {str(row['description'] or '')}"
                    for row in access_rows
                )
                item['endpoint_details'] = endpoint_details_by_candidate.get((scope_site, vlan_number, device_id), [])
        else:
            members = page_members.get(_page_candidate_key(candidate), {'svi_rows': [], 'access_rows': []})
            svi_rows = members['svi_rows']
            access_rows = members['access_rows']
            device_names = {
                str(row['device_hostname'] or row['device_id']) for row in (*svi_rows, *access_rows)
            }
            ports = {
                f"{row['device_hostname'] or row['device_id']}:{row['interface_name']}" for row in access_rows
            }
            svi_names = {str(row['interface_name']) for row in svi_rows}
            svi_descriptions = {str(row['description'] or '').strip() for row in svi_rows if str(row['description'] or '').strip()}
            gateway = str(item.get('gateway') or '')
            gateway_device = item.get('gateway_device')
            gateway_interface = item.get('gateway_interface')
            if not gateway:
                for row in svi_rows:
                    svi_ip = str(row['primary_ip'] or row['ip_address'] or '').strip()
                    if svi_ip:
                        gateway = svi_ip.split('/', 1)[0]
                        gateway_device = str(row['device_hostname'] or row['device_id'])
                        gateway_interface = str(row['interface_name'])
                        break
            arp_summary = arp_by_scope_vlan_device.get((scope_site, vlan_number), {})
            mac_summary = mac_by_scope_vlan_device.get((scope_site, vlan_number), {})
            arp_times = [row.get('last_updated') for row in arp_summary.values() if row.get('last_updated')]
            mac_times = [row.get('last_updated') for row in mac_summary.values() if row.get('last_updated')]
            item.update({
                'device_count': len(device_names),
                'device_names': ', '.join(sorted(device_names)),
                'port_count': len(ports),
                'svi_count': len(svi_names),
                'svi_interfaces': ', '.join(sorted(svi_names)),
                'description': '; '.join(sorted(svi_descriptions)),
                'gateway': gateway,
                'gateway_device': gateway_device,
                'gateway_interface': gateway_interface,
                'undocumented_port_count': sum(1 for row in access_rows if not str(row['description'] or '').strip()),
                'arp_count': sum(int(row.get('count') or 0) for row in arp_summary.values()),
                'mac_count': sum(int(row.get('count') or 0) for row in mac_summary.values()),
                'endpoint_last_seen_at': max(arp_times + mac_times) if arp_times + mac_times else '',
            })
            if include_details:
                item['port_details'] = '; '.join(sorted(
                    f"{row['device_hostname'] or row['device_id']}:{row['interface_name']} - {str(row['description'] or '').strip()}"
                    for row in access_rows
                ))
                item['port_detail_rows'] = [{
                    'device_id': str(row['device_id'] or ''),
                    'device_hostname': str(row['device_hostname'] or row['device_id'] or ''),
                    'device_ip': str(row['device_ip'] or ''),
                    'interface_name': str(row['interface_name'] or ''),
                    'description': str(row['description'] or '').strip(),
                    **({
                        'port_mode': str(row.get('port_mode') or 'unknown'),
                        'tagging': str(row.get('tagging') or 'unknown'),
                        'source': 'cmdb_cli_snapshot',
                    } if row.get('source') == 'cmdb_cli_snapshot' else {}),
                } for row in access_rows]
                item['endpoint_details'] = endpoint_details_by_candidate.get((scope_site, vlan_number, ''), [])
        display_rows.append(item)

    return {
        'items': display_rows,
        'total': len(filtered_candidates),
        'page': normalized_page,
        'page_size': normalized_page_size,
        'site_summary': sorted(site_counts.values(), key=lambda item: str(item['label']).lower()),
        'tree': _build_vlan_scope_tree(conn, full_candidates),
        'summary': summary,
    }


def list_vlans(conn, site_id: str = '', tenant_id: str = '', *, device_scoped: bool = False, q: str = '', status: str = 'all', asset_type: str = '', device_category: str = '', device_role: str = '', page: int | None = None, page_size: int = 20, include_details: bool = True) -> list[dict] | dict:
    if page is not None:
        return _list_vlans_page(
            conn,
            site_id,
            tenant_id,
            device_scoped=device_scoped,
            q=q,
            status=status,
            asset_type=asset_type,
            device_category=device_category,
            device_role=device_role,
            page=page,
            page_size=page_size,
            include_details=include_details,
        )

    resolved_site_scope = ('',) if site_id == 'unassigned' else ((site_id,) if site_id else None)
    if _successful_collection_devices(
        conn,
        ('interface_inventory', 'vlan_inventory'),
        tenant_id=tenant_id or None,
        site_ids=resolved_site_scope,
    ):
        # Keep the historical complete-list return shape while sharing one
        # generation-aware projection with the paged API and export callers.
        return _list_vlans_page(
            conn,
            site_id,
            tenant_id,
            device_scoped=device_scoped,
            q=q,
            status=status,
            asset_type=asset_type,
            device_category=device_category,
            device_role=device_role,
            page=1,
            page_size=page_size,
            include_details=include_details,
            all_rows=True,
        )['items']

    clauses, params = [], []
    if site_id:
        if site_id == 'unassigned':
            clauses.append("COALESCE(v.site_id, '') = ''")
        else:
            clauses.append("v.site_id = ?")
            params.append(site_id)
    if tenant_id:
        clauses.append("v.tenant_id = ?")
        params.append(tenant_id)
    if status and status != 'all':
        clauses.append("v.status = ?")
        params.append(status)
    if q and q.strip():
        fuzzy = f"%{q.strip().lower()}%"
        clauses.append(
            "(LOWER(CAST(v.vlan_id AS TEXT)) LIKE ? OR LOWER(COALESCE(v.name, '')) LIKE ? "
            "OR EXISTS (SELECT 1 FROM interfaces i JOIN devices d ON d.id = i.device_id "
            "WHERE " + _device_site_expression('d') + " = COALESCE(v.site_id, '') "
            "AND (LOWER(COALESCE(d.hostname, '')) LIKE ? OR LOWER(COALESCE(d.ip_address, '')) LIKE ? "
            "OR LOWER(COALESCE(i.interface_name, '')) LIKE ? OR LOWER(COALESCE(i.primary_ip, '')) LIKE ? "
            "OR LOWER(COALESCE(i.ip_address, '')) LIKE ? OR LOWER(COALESCE(i.description, '')) LIKE ?)) "
            "OR EXISTS (SELECT 1 FROM prefixes p WHERE p.vlan_id = v.id "
            "AND (LOWER(COALESCE(p.prefix, '')) LIKE ? OR LOWER(COALESCE(p.gateway, '')) LIKE ?)) "
            "OR EXISTS (SELECT 1 FROM vlan_business_bindings b WHERE b.vlan_id = v.vlan_id "
            "AND b.site_id = COALESCE(v.site_id, '') AND (LOWER(COALESCE(b.business_system, '')) LIKE ? "
            "OR LOWER(COALESCE(b.department, '')) LIKE ? OR LOWER(COALESCE(b.owner, '')) LIKE ?)))"
        )
        params.extend([fuzzy] * 13)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT v.* FROM vlans v{where} ORDER BY v.vlan_id", params
    ).fetchall()
    result = []
    from services.vlan_discovery_service import (
        is_system_default_vlan,
        parse_vlan_id_from_interface,
        parse_vlan_values,
    )
    site_platforms: dict[str, set[str]] = {}
    for device in conn.execute(
        f"SELECT {_device_site_expression('d')} AS site_id, d.platform, d.vendor FROM devices d"
    ).fetchall():
        scope = str(device['site_id'] or '')
        site_platforms.setdefault(scope, set()).add(str(device['platform'] or device['vendor'] or ''))

    # Load list projections in bounded batches. The list API does not need to
    # materialize endpoint evidence; its counts and timestamps come from the
    # aggregate queries below. The full evidence arrays remain available to
    # explicit detail/export callers through include_details=True.
    vlan_rows = [_row_to_dict(row) for row in rows]
    vlan_pks = [str(row.get('id') or '') for row in vlan_rows if row.get('id')]
    vlan_numbers = sorted({int(row.get('vlan_id') or 0) for row in vlan_rows if row.get('vlan_id') is not None})
    scope_sites = sorted({str(row.get('site_id') or '') for row in vlan_rows})
    site_expression = _device_site_expression('d')
    site_placeholders = ','.join('?' for _ in scope_sites)
    vlan_pk_placeholders = ','.join('?' for _ in vlan_pks)
    vlan_number_placeholders = ','.join('?' for _ in vlan_numbers)

    sites_by_id: dict[str, dict] = {}
    if scope_sites:
        named_scope_sites = [scope for scope in scope_sites if scope]
        if named_scope_sites:
            placeholders = ','.join('?' for _ in named_scope_sites)
            sites_by_id = {
                str(row['id']): _row_to_dict(row)
                for row in conn.execute(
                    f"SELECT id, site_code, site_name FROM sites WHERE id IN ({placeholders})",
                    tuple(named_scope_sites),
                ).fetchall()
            }

    prefixes_by_vlan_pk: dict[str, list] = {}
    ip_count_by_prefix: dict[str, int] = {}
    if vlan_pks:
        prefix_rows = conn.execute(
            f"""SELECT p.id, p.vlan_id, p.prefix, p.gateway, p.vrf_id,
                       v.vrf_name, gd.hostname AS gateway_device_name,
                       gi.interface_name AS gateway_interface_name
                FROM prefixes p
                LEFT JOIN vrfs v ON v.id = p.vrf_id
                LEFT JOIN devices gd ON gd.id = p.gateway_device_id
                LEFT JOIN interfaces gi ON gi.id = p.gateway_interface_id
                WHERE p.vlan_id IN ({vlan_pk_placeholders})
                ORDER BY p.prefix""",
            tuple(vlan_pks),
        ).fetchall()
        for prefix_row in prefix_rows:
            prefix = _row_to_dict(prefix_row)
            prefixes_by_vlan_pk.setdefault(str(prefix.get('vlan_id') or ''), []).append(prefix)
        prefix_ids = sorted({str(row['id']) for row in prefix_rows if row['id']})
        if prefix_ids:
            prefix_placeholders = ','.join('?' for _ in prefix_ids)
            ip_rows = conn.execute(
                f"""SELECT prefix_id, COUNT(*) AS count
                    FROM ip_addresses WHERE prefix_id IN ({prefix_placeholders})
                    GROUP BY prefix_id""",
                tuple(prefix_ids),
            ).fetchall()
            ip_count_by_prefix = {
                str(row['prefix_id']): int(row['count'] or 0) for row in ip_rows
            }

    interfaces_by_site: dict[str, list] = {}
    if scope_sites:
        interface_rows = conn.execute(
            f"""SELECT {site_expression} AS site_scope,
                       i.device_id, d.hostname, d.hostname AS device_hostname,
                       d.ip_address AS device_ip,
                       i.interface_name, i.description, i.interface_type,
                       i.primary_ip, i.ip_address, i.ip_prefix_length,
                       i.access_vlan, i.native_vlan, i.allowed_vlans, i.last_seen
                FROM interfaces i
                JOIN devices d ON d.id = i.device_id
                WHERE {site_expression} IN ({site_placeholders})
                ORDER BY d.hostname, i.interface_name""",
            tuple(scope_sites),
        ).fetchall()
        for interface_row in interface_rows:
            site_scope = str(interface_row['site_scope'] or '')
            interfaces_by_site.setdefault(site_scope, []).append(interface_row)
    for scope_site in scope_sites:
        interfaces_by_site.setdefault(scope_site, [])

    observation_counts: dict[tuple[str, int, str], dict[str, object]] = {}
    observation_max_times: dict[tuple[str, int], list[object]] = {}
    if vlan_number_placeholders and site_placeholders:
        for table in ('arp_table', 'mac_table'):
            aggregate_rows = conn.execute(
                f"""SELECT {site_expression} AS site_scope, x.vlan_id,
                           COUNT(*) AS count, MAX(x.last_updated) AS last_updated
                    FROM {table} x
                    JOIN devices d ON d.id = x.device_id
                    WHERE x.vlan_id IN ({vlan_number_placeholders})
                      AND {site_expression} IN ({site_placeholders})
                    GROUP BY {site_expression}, x.vlan_id""",
                (*vlan_numbers, *scope_sites),
            ).fetchall()
            for aggregate in aggregate_rows:
                key = (str(aggregate['site_scope'] or ''), int(aggregate['vlan_id'] or 0), table)
                observation_counts[key] = {
                    'count': int(aggregate['count'] or 0),
                    'last_updated': aggregate['last_updated'],
                }
                observation_max_times.setdefault(key[:2], []).append(aggregate['last_updated'])

    bindings_by_vlan_scope: dict[tuple[int, str], list] = {}
    if vlan_number_placeholders and site_placeholders:
        binding_rows = conn.execute(
            f"""SELECT vlan_id, site_id, business_system, department, owner, business_level
                FROM vlan_business_bindings
                WHERE vlan_id IN ({vlan_number_placeholders})
                  AND site_id IN ({site_placeholders})
                  AND status <> 'retired'
                ORDER BY business_system""",
            (*vlan_numbers, *scope_sites),
        ).fetchall()
        for binding_row in binding_rows:
            binding = _row_to_dict(binding_row)
            key = (int(binding.get('vlan_id') or 0), str(binding.get('site_id') or ''))
            bindings_by_vlan_scope.setdefault(key, []).append(binding)

    for item in vlan_rows:
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
        site = sites_by_id.get(scope_site)
        item['site_code'] = site.get('site_code') if site else ''
        item['site_name'] = site.get('site_name') if site else ''

        prefix_rows = prefixes_by_vlan_pk.get(str(item.get('id') or ''), [])
        prefix_ids = [str(row['id']) for row in prefix_rows if row.get('id')]
        item['prefix_count'] = len(prefix_rows)
        item['prefixes'] = ', '.join(str(row.get('prefix') or '') for row in prefix_rows if row.get('prefix'))
        item['ip_count'] = sum(ip_count_by_prefix.get(prefix_id, 0) for prefix_id in prefix_ids)

        gateway = next((row for row in prefix_rows if row.get('gateway')), None)
        item['gateway'] = gateway.get('gateway') if gateway else ''
        item['gateway_device'] = gateway.get('gateway_device_name') if gateway else ''
        item['gateway_interface'] = gateway.get('gateway_interface_name') if gateway else ''
        item['vrf_name'] = gateway.get('vrf_name') if gateway else ''

        device_rows = interfaces_by_site.get(scope_site, [])
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
                if include_details:
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
        if include_details:
            item['port_details'] = '; '.join(sorted(port_details))
        if include_details:
            item['port_detail_rows'] = port_detail_rows
        item['undocumented_port_count'] = undocumented_ports

        arp_summary = observation_counts.get((scope_site, vlan_number, 'arp_table'), {})
        mac_summary = observation_counts.get((scope_site, vlan_number, 'mac_table'), {})
        item['arp_count'] = int(arp_summary.get('count') or 0)
        item['mac_count'] = int(mac_summary.get('count') or 0)

        # Keep the actual endpoint evidence alongside the aggregate counts so
        # the VLAN page can answer the operator's next question: which IP/MAC
        # was learned on which device/interface? ARP and MAC observations are
        # intentionally merged and de-duplicated for a compact detail view.
        endpoint_details: list[dict] = []
        if include_details:
            endpoint_keys: set[tuple[str, str, str, str]] = set()
            endpoint_scope, endpoint_scope_params = _device_site_predicate('d', scope_site)
            arp_rows = conn.execute(
                f"""SELECT a.ip_address, a.mac_address, a.interface_name, a.vlan_id,
                          a.last_updated, d.hostname AS device_hostname, d.ip_address AS device_ip
                   FROM arp_table a
                   JOIN devices d ON d.id = a.device_id
                   WHERE a.vlan_id = ? AND {endpoint_scope}
                   ORDER BY a.ip_address, d.hostname""",
                (vlan_number, *endpoint_scope_params),
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
                f"""SELECT m.mac_address, m.interface_name, m.vlan_id,
                          m.last_updated, d.hostname AS device_hostname, d.ip_address AS device_ip
                   FROM mac_table m
                   JOIN devices d ON d.id = m.device_id
                   WHERE m.vlan_id = ? AND {endpoint_scope}
                   ORDER BY m.mac_address, d.hostname""",
                (vlan_number, *endpoint_scope_params),
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
        else:
            observation_times = observation_max_times.get((scope_site, vlan_number), [])
            item['endpoint_last_seen_at'] = max(
                (value for value in observation_times if value), default=''
            )

        bindings = bindings_by_vlan_scope.get((vlan_number, scope_site), [])
        item['business_count'] = len(bindings)
        item['business_systems'] = ', '.join(str(row['business_system'] or '') for row in bindings)
        item['business_departments'] = ', '.join(sorted({str(row['department'] or '') for row in bindings if row['department']}))
        item['business_owners'] = ', '.join(sorted({str(row['owner'] or '') for row in bindings if row['owner']}))
        item['highest_business_level'] = next(
            (level for level in ('P1', 'P2', 'P3', 'P4') if any(row['business_level'] == level for row in bindings)),
            '',
        )
        result.append(item)
    expanded = _expand_vlan_rows_by_device(
        conn,
        result,
        include_details=include_details,
        preloaded={
            'interfaces_by_site': interfaces_by_site,
        },
    ) if device_scoped else result
    if asset_type:
        expanded = [row for row in expanded if str(row.get('asset_type') or 'network_device') == asset_type]
    if device_category:
        expanded = [row for row in expanded if str(row.get('device_category') or 'other') == device_category]
    if device_role:
        expanded = [row for row in expanded if str(row.get('device_role') or 'unassigned') == device_role]
    return expanded


def get_vlan_details(
    conn,
    vlan_pk: str,
    *,
    site_id: str = '',
    device_id: str = '',
) -> dict:
    """Load full port and ARP/MAC evidence for one VLAN and optional device."""
    from services.vlan_discovery_service import parse_vlan_id_from_interface, parse_vlan_values

    snapshot_projection = _current_vlan_snapshot_projection(conn)
    observed_only = str(vlan_pk or '').startswith('cmdb-vlan-observed:')
    if observed_only:
        try:
            site_token, vlan_token = str(vlan_pk).removeprefix('cmdb-vlan-observed:').rsplit(':', 1)
            vlan_number = int(vlan_token)
        except (TypeError, ValueError) as exc:
            raise ValueError('VLAN not found') from exc
        if not 1 <= vlan_number <= 4094:
            raise ValueError('VLAN not found')
        vlan_site = '' if site_token == 'unassigned' else site_token
        matching_observations = [
            row for row in snapshot_projection['vlan_observations']
            if int(row.get('vlan_id') or 0) == vlan_number
            and str(row.get('resolved_site_id') or '') == vlan_site
        ]
        if not matching_observations:
            raise ValueError('VLAN not found')
        vlan = {'id': str(vlan_pk), 'vlan_id': vlan_number, 'site_id': vlan_site}
    else:
        vlan = conn.execute(
            "SELECT id, vlan_id, site_id FROM vlans WHERE id = ?",
            (str(vlan_pk),),
        ).fetchone()
        if not vlan:
            raise ValueError('VLAN not found')
        vlan_number = int(vlan['vlan_id'] or 0)
        vlan_site = str(vlan['site_id'] or '')
    requested_site = str(site_id or '').strip()
    if requested_site == 'unassigned':
        if vlan_site:
            raise ValueError('VLAN or device not found in the requested scope')
        requested_site = ''

    device_clause = ''
    device_params: tuple[str, ...] = ()
    resolved_device_site = ''
    if device_id:
        device = conn.execute(
            f"""SELECT d.id,
                       {_device_site_expression('d')} AS device_scope_site,
                       COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''), NULLIF(d.site, ''), 'unassigned') AS resolved_site_id
                FROM devices d
                LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                WHERE d.id = ?""",
            (str(device_id),),
        ).fetchone()
        if not device or str(device['device_scope_site'] or '') != vlan_site:
            raise ValueError('VLAN or device not found in the requested scope')
        resolved_device_site = str(device['resolved_site_id'] or '')
        allowed_sites = {vlan_site, resolved_device_site}
        if requested_site and requested_site not in allowed_sites:
            raise ValueError('VLAN or device not found in the requested scope')
        device_clause = ' AND d.id = ?'
        device_params = (str(device_id),)
    elif requested_site != vlan_site:
        raise ValueError('VLAN not found in the requested site')

    site_predicate, site_params = _device_site_predicate('d', vlan_site)
    interface_rows = conn.execute(
        f"""SELECT i.device_id, d.hostname AS device_hostname, d.ip_address AS device_ip,
                   i.interface_name, i.description, i.primary_ip, i.ip_address,
                   i.last_seen, i.access_vlan, i.native_vlan, i.allowed_vlans
            FROM interfaces i
            JOIN devices d ON d.id = i.device_id
            WHERE {site_predicate}{device_clause}
            ORDER BY d.hostname, i.interface_name""",
        (*site_params, *device_params),
    ).fetchall()

    port_detail_rows: list[dict] = []
    interface_times: list[object] = []
    interface_snapshot_devices = snapshot_projection['successful']['interface_inventory']
    vlan_snapshot_devices = snapshot_projection['successful']['vlan_inventory']
    snapshot_interface_by_identity = snapshot_projection['interface_by_device_identity']
    shared_interface_by_identity: dict[tuple[str, str], dict] = {}
    for row in interface_rows:
        row_device_id = str(row['device_id'] or '')
        identity = _interface_identity(row_device_id, row['interface_name'])
        shared_interface_by_identity.setdefault(identity, _row_to_dict(row))
        svi_vlan = parse_vlan_id_from_interface(row['interface_name'])
        if svi_vlan == vlan_number:
            if row_device_id in interface_snapshot_devices:
                continue
            if row['last_seen']:
                interface_times.append(row['last_seen'])
            continue
        if row_device_id in vlan_snapshot_devices:
            continue
        member_vlans = (
            parse_vlan_values(row['access_vlan'])
            | parse_vlan_values(row['native_vlan'])
            | parse_vlan_values(row['allowed_vlans'])
        )
        if vlan_number not in member_vlans:
            continue
        if row['last_seen']:
            interface_times.append(row['last_seen'])
        port_detail_rows.append({
            'device_id': row_device_id,
            'device_hostname': str(row['device_hostname'] or row['device_id'] or ''),
            'device_ip': str(row['device_ip'] or ''),
            'interface_name': str(row['interface_name'] or ''),
            'description': str(row['description'] or '').strip(),
            'port_mode': 'unknown',
            'tagging': 'unknown',
            'source': 'shared_interface',
        })

    for observation in snapshot_projection['interface_observations']:
        observed_device_id = str(observation.get('device_id') or '')
        state = interface_snapshot_devices.get(observed_device_id, {})
        if str(state.get('resolved_site_id') or '') != vlan_site:
            continue
        if device_id and observed_device_id != str(device_id):
            continue
        identity = _interface_identity(observed_device_id, observation.get('normalized_interface_name'))
        interface_vlan = parse_vlan_id_from_interface(observation.get('interface_name'))
        has_port_membership = any(
            str(port.get('device_id') or '') == observed_device_id
            and int(port.get('vlan_id') or 0) == vlan_number
            and str(port.get('normalized_interface_name') or '') == identity[1]
            for port in snapshot_projection['vlan_ports']
        )
        if interface_vlan == vlan_number or has_port_membership:
            if observation.get('observed_at'):
                interface_times.append(observation.get('observed_at'))

    for port in snapshot_projection['vlan_ports']:
        observed_device_id = str(port.get('device_id') or '')
        if int(port.get('vlan_id') or 0) != vlan_number:
            continue
        if str(port.get('resolved_site_id') or '') != vlan_site:
            continue
        if device_id and observed_device_id != str(device_id):
            continue
        identity = _interface_identity(observed_device_id, port.get('normalized_interface_name'))
        interface_observation = snapshot_interface_by_identity.get(identity)
        shared_interface = shared_interface_by_identity.get(identity, {})
        if observed_device_id in interface_snapshot_devices:
            description = str(interface_observation.get('description') or '') if interface_observation else ''
        else:
            description = str(shared_interface.get('description') or '')
        port_detail_rows.append({
            'device_id': observed_device_id,
            'device_hostname': str(port.get('device_hostname') or observed_device_id),
            'device_ip': str(port.get('device_ip') or ''),
            'interface_name': str(port.get('interface_name') or ''),
            'description': description.strip(),
            'port_mode': str(port.get('port_mode') or 'unknown'),
            'tagging': str(port.get('tagging') or 'unknown'),
            'source': 'cmdb_cli_snapshot',
        })
        if port.get('observed_at'):
            interface_times.append(port.get('observed_at'))

    endpoint_details: list[dict] = []
    endpoint_keys: set[tuple[str, str, str, str]] = set()
    arp_rows = conn.execute(
        f"""SELECT a.ip_address, a.mac_address, a.interface_name, a.last_updated,
                   d.hostname AS device_hostname, d.ip_address AS device_ip
            FROM arp_table a
            JOIN devices d ON d.id = a.device_id
            WHERE a.vlan_id = ? AND {site_predicate}{device_clause}
            ORDER BY a.ip_address, d.hostname""",
        (vlan_number, *site_params, *device_params),
    ).fetchall()
    mac_rows = conn.execute(
        f"""SELECT m.mac_address, m.interface_name, m.last_updated,
                   d.hostname AS device_hostname, d.ip_address AS device_ip
            FROM mac_table m
            JOIN devices d ON d.id = m.device_id
            WHERE m.vlan_id = ? AND {site_predicate}{device_clause}
            ORDER BY m.mac_address, d.hostname""",
        (vlan_number, *site_params, *device_params),
    ).fetchall()

    for row in arp_rows:
        key = (
            'arp', str(row['ip_address'] or ''), str(row['mac_address'] or ''),
            str(row['device_hostname'] or ''),
        )
        if key in endpoint_keys:
            continue
        endpoint_keys.add(key)
        endpoint_details.append({
            'source': 'arp',
            'ip_address': str(row['ip_address'] or ''),
            'mac_address': str(row['mac_address'] or ''),
            'interface_name': str(row['interface_name'] or ''),
            'device_hostname': str(row['device_hostname'] or ''),
            'device_ip': str(row['device_ip'] or ''),
            'last_updated': row['last_updated'],
        })
    for row in mac_rows:
        key = (
            'mac', '', str(row['mac_address'] or ''),
            f"{row['device_hostname'] or ''}:{row['interface_name'] or ''}",
        )
        if key in endpoint_keys:
            continue
        endpoint_keys.add(key)
        endpoint_details.append({
            'source': 'mac',
            'ip_address': '',
            'mac_address': str(row['mac_address'] or ''),
            'interface_name': str(row['interface_name'] or ''),
            'device_hostname': str(row['device_hostname'] or ''),
            'device_ip': str(row['device_ip'] or ''),
            'last_updated': row['last_updated'],
        })

    arp_times = [row['last_updated'] for row in arp_rows if row['last_updated']]
    mac_times = [row['last_updated'] for row in mac_rows if row['last_updated']]
    endpoint_times = arp_times + mac_times
    return {
        'cmdb_observed_only': observed_only,
        'port_detail_rows': port_detail_rows,
        'endpoint_details': endpoint_details,
        'meta': {
            'port_count': len(port_detail_rows),
            'undocumented_port_count': sum(1 for row in port_detail_rows if not row['description']),
            'arp_count': len(arp_rows),
            'mac_count': len(mac_rows),
            'endpoint_last_seen_at': max(endpoint_times) if endpoint_times else '',
            'interface_collected_at': max(interface_times) if interface_times else '',
            'arp_collected_at': max(arp_times) if arp_times else '',
            'mac_collected_at': max(mac_times) if mac_times else '',
        },
    }


def _expand_vlan_rows_by_device(
    conn,
    vlan_rows: list[dict],
    *,
    include_details: bool = True,
    preloaded: dict | None = None,
) -> list[dict]:
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
            """SELECT d.id, d.hostname, d.ip_address,
                      COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''), NULLIF(d.site, ''), 'unassigned') AS resolved_site_id,
                      COALESCE(NULLIF(pa.asset_type, ''), 'network_device') AS asset_type,
                      COALESCE(NULLIF(pa.device_category, ''), NULLIF(d.device_category, ''), 'other') AS device_category,
                      COALESCE(NULLIF(pa.device_role, ''), NULLIF(d.role, ''), 'unassigned') AS device_role
               FROM devices d
               LEFT JOIN physical_assets pa ON pa.id = d.asset_id"""
        ).fetchall()
    }
    preloaded = preloaded or {}
    device_interfaces_by_site: dict[str, list] = preloaded.get('interfaces_by_site') or {}
    device_interfaces_by_site_and_device: dict[str, dict[str, list]] = {}
    ip_inventory_by_device: dict[str, dict[str, str]] = {}

    # A paged list still needs all matching VLAN rows to compute its tree and
    # summary, but it only needs aggregate endpoint facts. Fetch those facts
    # once for the whole candidate set instead of loading every endpoint row
    # once per VLAN.
    vlan_numbers = sorted({int(row.get('vlan_id') or 0) for row in vlan_rows})
    scope_sites = sorted({str(row.get('site_id') or '') for row in vlan_rows})
    vlan_number_placeholders = ','.join('?' for _ in vlan_numbers)
    site_placeholders = ','.join('?' for _ in scope_sites)
    site_expression = _device_site_expression('d')
    observations_by_scope: dict[tuple[str, int], dict[str, dict]] = {}
    arp_by_scope_device: dict[tuple[str, int], dict[str, dict]] = {}
    mac_by_scope_device: dict[tuple[str, int], dict[str, dict]] = {}
    if not include_details and vlan_numbers and scope_sites:
        observation_rows = conn.execute(
            f"""SELECT {site_expression} AS site_scope, o.device_id, o.vlan_id,
                       o.vlan_name, o.vlan_status, o.observed_at, o.generation
                FROM cmdb_device_vlan_observations o
                JOIN cmdb_collection_snapshots s ON s.device_id = o.device_id
                     AND s.domain = 'vlan_inventory' AND s.successful_generation = o.generation
                JOIN devices d ON d.id = o.device_id
                WHERE o.vlan_id IN ({vlan_number_placeholders})
                  AND {site_expression} IN ({site_placeholders})""",
            (*vlan_numbers, *scope_sites),
        ).fetchall()
        for row in observation_rows:
            key = (str(row['site_scope'] or ''), int(row['vlan_id'] or 0))
            observations_by_scope.setdefault(key, {})[str(row['device_id'])] = dict(row)

        for table, target in (('arp_table', arp_by_scope_device), ('mac_table', mac_by_scope_device)):
            aggregate_rows = conn.execute(
                f"""SELECT {site_expression} AS site_scope, x.vlan_id, x.device_id,
                           COUNT(*) AS count, MAX(x.last_updated) AS last_updated
                    FROM {table} x
                    JOIN devices d ON d.id = x.device_id
                    WHERE x.vlan_id IN ({vlan_number_placeholders})
                      AND {site_expression} IN ({site_placeholders})
                    GROUP BY {site_expression}, x.vlan_id, x.device_id""",
                (*vlan_numbers, *scope_sites),
            ).fetchall()
            for row in aggregate_rows:
                key = (str(row['site_scope'] or ''), int(row['vlan_id'] or 0))
                target.setdefault(key, {})[str(row['device_id'])] = {
                    'count': int(row['count'] or 0),
                    'last_updated': row['last_updated'],
                }

    if not device_interfaces_by_site and scope_sites:
        interface_rows = conn.execute(
            f"""SELECT {site_expression} AS site_scope,
                       i.device_id, d.hostname AS device_hostname, d.ip_address AS device_ip,
                       i.interface_name, i.description, i.primary_ip, i.ip_address,
                       i.ip_prefix_length, i.access_vlan, i.native_vlan, i.allowed_vlans,
                       i.last_seen
                FROM interfaces i JOIN devices d ON d.id = i.device_id
                WHERE {site_expression} IN ({site_placeholders})
                ORDER BY d.hostname, i.interface_name""",
            tuple(scope_sites),
        ).fetchall()
        for row in interface_rows:
            device_interfaces_by_site.setdefault(str(row['site_scope'] or ''), []).append(row)
    for scope_site in scope_sites:
        device_interfaces_by_site.setdefault(scope_site, [])
    device_ids = sorted({
        str(row['device_id'])
        for site_rows in device_interfaces_by_site.values()
        for row in site_rows
        if row['device_id']
    })
    if device_ids:
        device_placeholders = ','.join('?' for _ in device_ids)
        for row in conn.execute(
            f"""SELECT device_id, interface, mask
                FROM ip_inventory WHERE device_id IN ({device_placeholders})""",
            tuple(device_ids),
        ).fetchall():
            device_id = str(row['device_id'] or '')
            interface_name = _normalize_interface_name_cached(row['interface'])
            if interface_name:
                ip_inventory_by_device.setdefault(device_id, {})[interface_name] = str(row['mask'] or '').strip()
    for device_id in device_ids:
        ip_inventory_by_device.setdefault(device_id, {})

    scoped_rows: list[dict] = []
    for item in vlan_rows:
        vlan_number = int(item.get('vlan_id') or 0)
        scope_site = str(item.get('site_id') or '')
        device_scope, device_scope_params = _device_site_predicate('d', scope_site)
        if scope_site not in device_interfaces_by_site:
            device_interfaces_by_site[scope_site] = conn.execute(
                f"""SELECT i.device_id, d.hostname AS device_hostname, d.ip_address AS device_ip,
                          i.interface_name, i.description, i.primary_ip, i.ip_address,
                          i.ip_prefix_length, i.access_vlan, i.native_vlan, i.allowed_vlans,
                          i.last_seen
                   FROM interfaces i JOIN devices d ON d.id = i.device_id
                   WHERE {device_scope}
                   ORDER BY d.hostname, i.interface_name""",
                device_scope_params,
            ).fetchall()
        device_interfaces = device_interfaces_by_site[scope_site]
        if scope_site not in device_interfaces_by_site_and_device:
            rows_by_device: dict[str, list] = {}
            for row in device_interfaces:
                rows_by_device.setdefault(str(row['device_id'] or ''), []).append(row)
            device_interfaces_by_site_and_device[scope_site] = rows_by_device
        if include_details:
            vlan_observations = conn.execute(
                f"""SELECT o.device_id, o.vlan_name, o.vlan_status,
                          o.observed_at, o.generation
                   FROM cmdb_device_vlan_observations o
                   JOIN cmdb_collection_snapshots s ON s.device_id = o.device_id
                        AND s.domain = 'vlan_inventory' AND s.successful_generation = o.generation
                   JOIN devices d ON d.id = o.device_id
                   WHERE o.vlan_id = ? AND {device_scope}""",
                (vlan_number, *device_scope_params),
            ).fetchall()
        else:
            vlan_observations = list(observations_by_scope.get((scope_site, vlan_number), {}).values())
        vlan_observations_by_device = {
            str(row['device_id']): row for row in vlan_observations
        }
        arp_rows_by_device: dict[str, list] = {}
        mac_rows_by_device: dict[str, list] = {}
        arp_summaries = arp_by_scope_device.get((scope_site, vlan_number), {})
        mac_summaries = mac_by_scope_device.get((scope_site, vlan_number), {})
        if include_details:
            for row in conn.execute(
                f"""SELECT a.device_id, a.ip_address, a.mac_address, a.interface_name, a.last_updated,
                          d.hostname AS device_hostname, d.ip_address AS device_ip
                   FROM arp_table a JOIN devices d ON d.id = a.device_id
                   WHERE a.vlan_id = ? AND {device_scope}
                   ORDER BY a.ip_address, d.hostname""",
                (vlan_number, *device_scope_params),
            ).fetchall():
                arp_rows_by_device.setdefault(str(row['device_id']), []).append(row)
            for row in conn.execute(
                f"""SELECT m.device_id, m.mac_address, m.interface_name, m.last_updated,
                          d.hostname AS device_hostname, d.ip_address AS device_ip
                   FROM mac_table m JOIN devices d ON d.id = m.device_id
                   WHERE m.vlan_id = ? AND {device_scope}
                   ORDER BY m.mac_address, d.hostname""",
                (vlan_number, *device_scope_params),
            ).fetchall():
                mac_rows_by_device.setdefault(str(row['device_id']), []).append(row)
        else:
            arp_rows_by_device = {device_id: [] for device_id in arp_summaries}
            mac_rows_by_device = {device_id: [] for device_id in mac_summaries}

        device_ids = {
            str(row['device_id']) for row in device_interfaces
            if parse_vlan_id_from_interface(row['interface_name']) == vlan_number
            or vlan_number in (
                parse_vlan_values(row['access_vlan'])
                | parse_vlan_values(row['native_vlan'])
                | parse_vlan_values(row['allowed_vlans'])
            )
        }
        device_ids.update(arp_rows_by_device)
        device_ids.update(mac_rows_by_device)
        device_ids.update(vlan_observations_by_device)

        if not device_ids:
            scoped_rows.append(item)
            continue

        for device_id in sorted(device_ids):
            rows = device_interfaces_by_site_and_device[scope_site].get(device_id, [])
            device_info = device_metadata.get(device_id, {})
            vlan_observation = vlan_observations_by_device.get(device_id)
            device_hostname = str((rows[0]['device_hostname'] if rows else device_info.get('hostname')) or device_id)
            device_ip = str((rows[0]['device_ip'] if rows else device_info.get('ip_address')) or '')
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
                        norm_intf = _normalize_interface_name_cached(svi['interface_name'])
                        if device_id not in ip_inventory_by_device:
                            ip_rows = conn.execute(
                                "SELECT interface, mask FROM ip_inventory WHERE device_id = ?",
                                (device_id,),
                            ).fetchall()
                            ip_inventory_by_device[device_id] = {
                                _normalize_interface_name_cached(row['interface']): str(row['mask'] or '').strip()
                                for row in ip_rows
                                if _normalize_interface_name_cached(row['interface'])
                            }
                        inv_mask = ip_inventory_by_device[device_id].get(norm_intf)
                        if inv_mask:
                            prefix_length = inv_mask

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

            arp_rows = arp_rows_by_device.get(device_id, [])
            mac_rows = mac_rows_by_device.get(device_id, [])
            endpoint_details = [
                detail for detail in (item.get('endpoint_details') or [])
                if str(detail.get('device_hostname') or '') == device_hostname
            ] if include_details else None
            port_detail_rows = [{
                'device_id': device_id,
                'device_hostname': device_hostname,
                'device_ip': device_ip,
                'interface_name': str(row['interface_name'] or ''),
                'description': str(row['description'] or ''),
            } for row in access_rows] if include_details else []
            interface_times = [row['last_seen'] for row in (*svi_rows, *access_rows) if row['last_seen']]
            arp_summary = arp_summaries.get(device_id, {})
            mac_summary = mac_summaries.get(device_id, {})
            arp_times = [row['last_updated'] for row in arp_rows if row['last_updated']]
            mac_times = [row['last_updated'] for row in mac_rows if row['last_updated']]
            if not include_details:
                arp_times = [arp_summary.get('last_updated')] if arp_summary.get('last_updated') else []
                mac_times = [mac_summary.get('last_updated')] if mac_summary.get('last_updated') else []
            device_row = dict(item)
            device_row.update({
                'device_id': device_id,
                'device_hostname': device_hostname,
                'device_ip': device_ip,
                'asset_type': device_info.get('asset_type') or 'network_device',
                'device_category': device_info.get('device_category') or 'other',
                'device_role': device_info.get('device_role') or 'unassigned',
                'device_vlan_name': str(vlan_observation['vlan_name'] or '') if vlan_observation else '',
                'device_vlan_status': str(vlan_observation['vlan_status'] or '') if vlan_observation else '',
                'device_vlan_observed_at': str(vlan_observation['observed_at'] or '') if vlan_observation else '',
                'device_vlan_generation': int(vlan_observation['generation'] or 0) if vlan_observation else 0,
                'site_id': device_info.get('resolved_site_id') or device_row.get('site_id') or '',
                'device_count': 1,
                'device_names': device_hostname,
                'port_count': len(access_rows),
                'undocumented_port_count': sum(1 for row in access_rows if not str(row['description'] or '').strip()),
                'svi_interfaces': ', '.join(str(row['interface_name'] or '') for row in svi_rows),
                'description': '; '.join(sorted({str(row['description'] or '') for row in svi_rows if row['description']})),
                'prefixes': ', '.join(dict.fromkeys(prefixes)),
                'gateway': gateways[0] if gateways else '',
                'gateway_device': device_hostname if gateways else '',
                'gateway_interface': str(svi_rows[0]['interface_name'] or '') if gateways and svi_rows else '',
                'arp_count': int(arp_summary.get('count') or len(arp_rows)),
                'mac_count': int(mac_summary.get('count') or len(mac_rows)),
                'endpoint_last_seen_at': max(arp_times + mac_times) if arp_times + mac_times else '',
                'interface_collected_at': max(interface_times) if interface_times else '',
                'arp_collected_at': max(arp_times) if arp_times else '',
                'mac_collected_at': max(mac_times) if mac_times else '',
            })
            if include_details:
                device_row['port_detail_rows'] = port_detail_rows
                device_row['port_details'] = '; '.join(
                    f"{device_hostname}:{row['interface_name']} - {str(row['description'] or '')}"
                    for row in access_rows
                )
                device_row['endpoint_details'] = endpoint_details or []
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
    export_rows: list[dict] = []
    for vlan in list_vlans(conn, site_id=site_id, tenant_id=tenant_id, device_scoped=True):
        vlan_number = int(vlan.get('vlan_id') or 0)
        site_label = str(vlan.get('site_name') or vlan.get('site_code') or vlan.get('site_id') or '未分配站点')
        access_rows = list(vlan.get('port_detail_rows') or [])

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
            gateway_device = str(vlan.get('gateway_device') or '')
            gateway_device_ip = str(vlan.get('device_ip') or '') if (
                not gateway_device or gateway_device == str(vlan.get('device_hostname') or '')
            ) else ''
            export_rows.append({
                **common,
                '设备名称': gateway_device,
                '设备IP': gateway_device_ip,
                '接入接口': str(vlan.get('gateway_interface') or ''),
                '接口描述': str(vlan.get('description') or ''),
                'ARP/MAC信息': endpoint_text(gateway_device, ''),
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
    from services.cmdb_version_service import bump_read_versions
    bump_read_versions(conn, ("vlans", "bindings"))
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
    from services.cmdb_version_service import bump_read_versions
    bump_read_versions(conn, ("vlans", "bindings"))
    conn.commit()
    return get_vlan(conn, vlan_pk)


def delete_vlan(conn, vlan_pk: str) -> None:
    vlan = get_vlan(conn, vlan_pk)
    discovery_source = str(vlan.get('discovery_source') or 'manual').strip().lower()
    site_scope = str(vlan.get('site_id') or '')
    binding_count = int(conn.execute(
        """SELECT COUNT(*) FROM vlan_business_bindings
           WHERE COALESCE(site_id, '') = ? AND vlan_id = ?""",
        (site_scope, int(vlan.get('vlan_id') or 0)),
    ).fetchone()[0] or 0)
    if binding_count:
        raise ValueError(
            "Cannot delete VLAN: "
            f"vlan_business_bindings.site_id={site_scope},vlan_id={vlan.get('vlan_id')} ({binding_count})"
        )

    try:
        access_cnt = _count_reference(conn, 'interfaces', 'access_vlan', str(vlan.get('vlan_id')))
    except Exception:
        access_cnt = 0
    if access_cnt > 0:
        raise ValueError(
            f"Cannot delete VLAN: interfaces.access_vlan={vlan.get('vlan_id')} ({access_cnt})"
        )

    if discovery_source == 'manual':
        _raise_if_referenced(conn, "VLAN", [('prefixes', 'vlan_id', vlan_pk)])
    else:
        from services.vlan_discovery_service import has_live_vlan_observations

        if has_live_vlan_observations(
            conn,
            site_id=site_scope,
            vlan_id=int(vlan.get('vlan_id') or 0),
        ):
            raise ValueError(
                f"Cannot delete VLAN: active device observations for "
                f"site_id={site_scope}, vlan_id={vlan.get('vlan_id')}"
            )
        manual_prefix_count = int(conn.execute(
            """SELECT COUNT(*) FROM prefixes
               WHERE vlan_id = ? AND COALESCE(manual_override, 0) <> 0""",
            (vlan_pk,),
        ).fetchone()[0] or 0)
        if manual_prefix_count:
            raise ValueError(
                f"Cannot delete VLAN: prefixes.vlan_id={vlan_pk} "
                f"({manual_prefix_count} manual override)"
            )
        # A stale automatic directory entry may be deleted while keeping its
        # prefix record. Only the automatic relation is cleared.
        conn.execute(
            """UPDATE prefixes SET vlan_id = NULL
               WHERE vlan_id = ? AND COALESCE(manual_override, 0) = 0""",
            (vlan_pk,),
        )
    conn.execute("DELETE FROM vlans WHERE id = ?", (vlan_pk,))
    from services.cmdb_version_service import bump_read_versions
    bump_read_versions(conn, ("vlans", "bindings"))
    conn.commit()
    logger.info(f"[CmdbService] Deleted VLAN {vlan_pk}")


# VLAN business ownership bindings

def list_vlan_business_bindings(
    conn,
    *,
    site_id: str = '',
    vrf_id: str = '',
    vlan_id: int | None = None,
    q: str = '',
    status: str = '',
    page: int | None = None,
    page_size: int = 20,
) -> list[dict] | dict:
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
    if status:
        clauses.append('b.status = ?')
        params.append(status)
    if q and q.strip():
        pattern = f"%{q.strip().lower()}%"
        clauses.append(
            "(LOWER(b.business_system) LIKE ? OR LOWER(COALESCE(b.department, '')) LIKE ? "
            "OR LOWER(COALESCE(b.owner, '')) LIKE ? OR LOWER(COALESCE(b.description, '')) LIKE ? "
            "OR CAST(b.vlan_id AS TEXT) LIKE ?)"
        )
        params.extend([pattern, pattern, pattern, pattern, pattern])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
    base_query = f'''FROM vlan_business_bindings b
            LEFT JOIN sites s ON s.id = NULLIF(b.site_id, '')
            LEFT JOIN vrfs r ON r.id = NULLIF(b.vrf_id, '')
            LEFT JOIN vlans v ON v.vlan_id = b.vlan_id
                              AND COALESCE(v.site_id, '') = b.site_id
            {where}'''
    select_columns = '''SELECT b.*, s.site_name, s.site_code, r.vrf_name,
                   v.name AS vlan_name, v.status AS vlan_status
            '''
    if page is None:
        rows = conn.execute(
            f'''{select_columns}{base_query}
                ORDER BY b.site_id, b.vrf_id, b.vlan_id, b.business_system''',
            tuple(params),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    normalized_page = max(1, int(page))
    normalized_page_size = min(100, max(1, int(page_size or 20)))
    count_row = conn.execute(f"SELECT COUNT(DISTINCT b.id) AS total {base_query}", tuple(params)).fetchone()
    total = int(count_row['total'] or 0) if count_row else 0
    rows = conn.execute(
        f'''SELECT b.*, s.site_name, s.site_code, r.vrf_name,
                   v.name AS vlan_name, v.status AS vlan_status
            {base_query}
            ORDER BY b.site_id, b.vrf_id, b.vlan_id, b.business_system
            LIMIT ? OFFSET ?''',
        (*params, normalized_page_size, (normalized_page - 1) * normalized_page_size),
    ).fetchall()
    return {
        'items': [_row_to_dict(row) for row in rows],
        'total': total,
        'page': normalized_page,
        'page_size': normalized_page_size,
        'total_pages': max(1, -(-total // normalized_page_size)),
    }


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
    from services.cmdb_version_service import bump_read_versions
    bump_read_versions(conn, ("bindings",))
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
    from services.cmdb_version_service import bump_read_versions
    bump_read_versions(conn, ("bindings",))
    conn.commit()
    return get_vlan_business_binding(conn, binding_id)


def delete_vlan_business_binding(conn, binding_id: str) -> None:
    get_vlan_business_binding(conn, binding_id)
    conn.execute('DELETE FROM vlan_business_bindings WHERE id = ?', (binding_id,))
    from services.cmdb_version_service import bump_read_versions
    bump_read_versions(conn, ("bindings",))
    conn.commit()
