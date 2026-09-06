import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from netmiko import ConnectHandler

from core.crypto import decrypt_credential
from core.interface_utils import interface_nominal_speed_mbps, normalize_interface_name
from core.textfsm import configure_ntc_templates, smart_parse_cli
from core.read_cache import invalidate_read_cache
from database import get_db_connection
from services.vault_service import resolve_collector_credentials
from services.network_access_limiter import limited_connect_handler
from services.collection_status_service import record_collection_result
from services.neighbor_collection_contract import assert_lldp_command, normalize_neighbor_record
from drivers.ssh_compat import build_netmiko_compatibility_kwargs

logger = logging.getLogger(__name__)
configure_ntc_templates()
_topology_rebuild_lock = threading.Lock()
TOPOLOGY_LINK_TTL_SECONDS = max(60, int(os.environ.get('TOPOLOGY_LINK_TTL_SECONDS', '172800')))
TOPOLOGY_LINK_STALE_RETENTION_SECONDS = max(
    TOPOLOGY_LINK_TTL_SECONDS,
    int(os.environ.get('TOPOLOGY_LINK_STALE_RETENTION_SECONDS', str(24 * 60 * 60))),
)
TOPOLOGY_AUTOMATIC_INTERVAL_SECONDS = max(
    60,
    int(os.environ.get('TOPOLOGY_AUTOMATIC_INTERVAL_SECONDS', '86400')),
)
DISCOVERY_LEASE_SECONDS = max(30, int(os.environ.get('TOPOLOGY_DISCOVERY_LEASE_SECONDS', '90')))
DISCOVERY_DEFAULT_TIMEOUT_SECONDS = max(30, int(os.environ.get('TOPOLOGY_DISCOVERY_TIMEOUT_SECONDS', '300')))
DISCOVERY_DEFAULT_MAX_ATTEMPTS = max(1, int(os.environ.get('TOPOLOGY_DISCOVERY_MAX_ATTEMPTS', '2')))
# Devices are independent discovery units, but the SSH limiter still keeps
# operations against the same device serialized.  A bounded run-level lane
# removes the historical device-by-device waterfall without overloading the
# network or the devices' VTY/CLI sessions.
DISCOVERY_DEVICE_CONCURRENCY = max(
    1,
    int(os.environ.get('TOPOLOGY_DISCOVERY_DEVICE_CONCURRENCY', '6')),
)
DISCOVERY_RETRYABLE_ERROR_CODES = frozenset({'ssh_unreachable'})

PLATFORM_MAP = {
    'cisco_ios': 'cisco_ios',
    'cisco_xe': 'cisco_ios',
    'cisco_nxos': 'cisco_nxos',
    'juniper_junos': 'juniper_junos',
    'arista_eos': 'arista_eos',
    'fortinet_fortios': 'fortinet',
    'huawei_vrp': 'huawei_vrp',
    'huawei_vrpv8': 'huawei_vrp',
    'huawei': 'huawei_vrp',
    '\u534e\u4e3avrp': 'huawei_vrp',
    'h3c_comware': 'hp_comware',
    'h3c_comware_v3': 'hp_comware',
    'ruijie_rgos': 'ruijie_os',
}

DISCOVERY_COMMANDS = {
    'cisco_ios': [
        ('lldp', 'show lldp neighbors'),
    ],
    'cisco_nxos': [
        ('lldp', 'show lldp neighbors detail'),
    ],
    'juniper_junos': [('lldp', 'show lldp neighbors detail')],
    'arista_eos': [('lldp', 'show lldp neighbors detail')],
    'huawei_vrp': [('lldp', 'display lldp neighbor brief')],
    'h3c_comware': [('lldp', 'display lldp neighbor-information list')],
    'ruijie_rgos': [('lldp', 'show lldp neighbors detail')],
    'zte_zxros': [('lldp', 'show lldp neighbor')],
    'dptech_ios': [('lldp', 'show lldp neighbors')],
    'maipu': [('lldp', 'show lldp neighbors')],
}


def normalize_topology_platform(platform: str | None) -> str:
    """Return the canonical discovery catalog key or raise a stable error."""
    raw = str(platform or '').strip().lower()
    aliases = {
        'cisco_xe': 'cisco_ios',
        'huawei_vrpv8': 'huawei_vrp',
        'huawei': 'huawei_vrp',
        'hp_comware': 'h3c_comware',
        'h3c_comware_v3': 'h3c_comware',
        'comware': 'h3c_comware',
        'ruijie_os': 'ruijie_rgos',
        'dptech': 'dptech_ios',
        'dptech_conplat': 'dptech_ios',
        'dptech_conplat_fw': 'dptech_ios',
        'maipu_mypower': 'maipu',
        'maipu_network': 'maipu',
    }
    normalized = aliases.get(raw, raw)
    if normalized not in DISCOVERY_COMMANDS:
        raise RuntimeError(f'topology_platform_unsupported:{raw or "missing"}')
    return normalized


def topology_error_code(exc: Exception) -> str:
    message = str(exc or '').lower()
    if 'cancel' in message:
        return 'discovery_cancelled'
    if 'device_not_found' in message:
        return 'device_not_found'
    if 'device_is_offline' in message:
        return 'device_offline'
    if 'credentials_incomplete' in message:
        return 'credentials_incomplete'
    if 'platform_unsupported' in message:
        return 'platform_unsupported'
    if 'authentication' in message or 'auth fail' in message:
        return 'ssh_authentication_failed'
    if any(
        marker in message
        for marker in (
            'closed/unreachable',
            'timed out',
            'timeout',
            'connection refused',
            'connection reset',
            'no route to host',
            'network is unreachable',
            'tcp connection to device failed',
            'ssh connection failed',
        )
    ):
        return 'ssh_unreachable'
    if 'parse' in message or 'template' in message:
        return 'neighbor_parse_failed'
    return 'topology_discovery_failed'


def _should_retry_discovery(error_code: str, attempt: int, max_attempts: int) -> bool:
    """Retry only transport failures that can plausibly recover by themselves."""
    return attempt < max_attempts and error_code in DISCOVERY_RETRYABLE_ERROR_CODES

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def _link_operational_state(link: dict[str, Any], now: datetime | None = None) -> tuple[str, str]:
    """Apply one server-side TTL policy so APIs and site cards agree with the UI."""
    status = str(link.get('status') or 'unknown').lower()
    last_seen = _parse_iso(link.get('last_seen'))
    age_seconds = None if last_seen is None else max(0, int(((now or datetime.now(timezone.utc)) - last_seen).total_seconds()))
    if status == 'stale' or last_seen is None or (age_seconds is not None and age_seconds > TOPOLOGY_LINK_TTL_SECONDS):
        return 'stale', 'missing_or_expired_discovery_evidence'
    return status if status in {'up', 'down', 'degraded', 'unknown'} else 'unknown', ''


def normalize_hostname(value: str | None) -> str:
    if not value:
        return ''
    raw = str(value).strip().lower()
    raw = raw.strip('[](){}<> ')
    if raw.count('.') >= 1 and not _is_ip_address(raw):
        raw = raw.split('.')[0]
    raw = re.sub(r'\s+', '', raw)
    return raw


def _load_site_identity_maps(conn) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Load canonical site IDs plus code/name aliases without leaking that logic into APIs."""
    rows = conn.execute('SELECT id, site_code, site_name, status FROM sites').fetchall()
    aliases: dict[str, str] = {}
    sites_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        site = dict(row)
        site_id = str(site.get('id') or '').strip()
        if not site_id:
            continue
        sites_by_id[site_id] = site
        for value in (site_id, site.get('site_code'), site.get('site_name')):
            normalized = str(value or '').strip().lower()
            if normalized:
                aliases.setdefault(normalized, site_id)
    return aliases, sites_by_id


def _canonical_site_id(value: Any, aliases: dict[str, str]) -> str:
    raw = str(value or '').strip()
    return aliases.get(raw.lower(), raw) if raw else ''


def _device_id_filter(column: str, device_ids: list[str] | tuple[str, ...] | None) -> tuple[str, list[str]]:
    """Return a safe SQL predicate for an already-authorized device set."""

    if device_ids is None:
        return '', []
    normalized = sorted({str(item).strip() for item in device_ids if str(item).strip()})
    if not normalized:
        return '1 = 0', []
    placeholders = ','.join('?' for _ in normalized)
    return f'{column} IN ({placeholders})', normalized


def _is_ip_address(value: str | None) -> bool:
    if not value:
        return False
    try:
        ipaddress.ip_address(str(value).strip())
        return True
    except ValueError:
        return False


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value or {}, ensure_ascii=False)
    except TypeError:
        return '{}'


def _regex_parse_lldp_detail(raw_text: str) -> list[dict[str, str]]:
    """Regex fallback for 'show lldp neighbors detail' when no TextFSM template exists (e.g. Ruijie, Juniper, H3C)."""
    entries: list[dict[str, str]] = []
    # Split by common LLDP detail block separator (20+ dashes, 'LLDP neighbor-information of port', 'Local Interface: ', 'Index ')
    blocks = re.split(r'-{20,}|(?=LLDP neighbor-information of port)|(?=Local Interface:)', raw_text)
    for block in blocks:
        if not block.strip():
            continue
        entry: dict[str, str] = {}
        # Local interface (Cisco/Ruijie: "Local Intf: Gi0/1", Huawei: "LLDP neighbor-information of port GE0/0/1:", Juniper: "Local Interface: ge-0/0/0")
        m = re.search(r'(?:Local\s+Int(?:f|erface)\s*:\s*(.+?)$|of port\s+(\S+?)\s*:)', block, re.IGNORECASE | re.MULTILINE)
        if m:
            entry['local_interface'] = (m.group(1) or m.group(2) or '').strip()
        
        # Clean local interface if it has H3C style index[port], e.g., 1[GigabitEthernet1/0/1]
        if 'local_interface' in entry:
            val = entry['local_interface']
            idx_m = re.match(r'\d+\[([^\]]+)\]', val)
            if idx_m:
                entry['local_interface'] = idx_m.group(1)

        # System Name
        m = re.search(r'System\s*(?:Name|name)\s*[:\-]\s*(.+?)$', block, re.IGNORECASE | re.MULTILINE)
        if m:
            entry['neighbor_name'] = m.group(1).strip()
        # Chassis ID
        m = re.search(r'Chassis\s*(?:id|ID)\s*[:\-]\s*(.+?)$', block, re.IGNORECASE | re.MULTILINE)
        if m:
            entry['chassis_id'] = m.group(1).strip()
        # Port ID / Neighbor interface
        m = re.search(r'Port\s*(?:id|ID)\s*[:\-]\s*(.+?)$', block, re.IGNORECASE | re.MULTILINE)
        if m:
            entry['neighbor_interface'] = m.group(1).strip()
        # Management Address (IP)
        m = re.search(r'(?:Management\s+Address(?:es)?|Management\s+address\s+value|IP)\s*[:\-]\s*([\d.]+)', block, re.IGNORECASE)
        if m:
            entry['mgmt_address'] = m.group(1).strip()
        # Device ID (CDP style)
        m = re.search(r'Device\s+ID\s*:\s*(.+?)$', block, re.IGNORECASE | re.MULTILINE)
        if m and 'neighbor_name' not in entry:
            entry['neighbor_name'] = m.group(1).strip()
            
        # Clean chassis_id, neighbor_interface, and neighbor_name from extra comments in parenthesis
        for field in ('chassis_id', 'neighbor_interface', 'neighbor_name'):
            if field in entry:
                entry[field] = re.sub(r'\s*\([^)]*\)', '', entry[field]).strip()

        if entry.get('local_interface') and (entry.get('neighbor_name') or entry.get('chassis_id')):
            entries.append(entry)
    return entries


def _extract_first(raw: dict[str, Any], *keys: str) -> str:
    casefolded = {str(key).lower(): value for key, value in raw.items()}
    for key in keys:
        value = casefolded.get(str(key).lower())
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ''


def _extract_observation_fields(raw: dict[str, Any], protocol: str) -> dict[str, Any]:
    common = normalize_neighbor_record(raw, protocol=protocol)
    neighbor_name = _extract_first(
        raw,
        'neighbor_name',        # Cisco IOS/NX-OS detail, Arista EOS, Huawei VRP, H3C Comware
        'neighbor',             # some textfsm variants
        'neighbor_id',          # older templates
        'remote_system_name',   # alternative naming
        'destination_host',     # CDP
        'dest_host',            # CDP short
        'device_id',            # CDP
        'system_name',          # generic
    )
    local_port = _extract_first(
        raw,
        'local_interface',      # Cisco, Arista, Huawei, H3C, Juniper
        'local_port',
        'local_port_id',
        'local_intf',
        'interface',
        'src_port',
    )
    remote_port = _extract_first(
        raw,
        'neighbor_interface',   # Cisco detail, Arista, Huawei, H3C Comware
        'neighbor_port_id',     # Cisco IOS detail (NEIGHBOR_PORT_ID)
        'remote_port',
        'port_id',              # Juniper/generic
        'remote_interface',
        'port',
    )
    neighbor_ip = _extract_first(
        raw,
        'mgmt_address',         # Cisco IOS/NX-OS detail, Arista EOS detail
        'management_address',   # alternative
        'mgmt_ip',              # Huawei VRP
        'neighbor_ip',
        'remote_management_address',
        'ip_address',
    )
    chassis_id = _extract_first(
        raw,
        'chassis_id',           # Cisco detail, Arista, Juniper, H3C Comware
        'serial',               # some templates expose serial as chassis-id
    )
    # Some LLDP implementations omit System Name but still expose a stable
    # chassis ID. Keep that evidence instead of silently dropping the peer.
    neighbor_identity = neighbor_name or chassis_id
    confidence = 0.9 if protocol == 'lldp' else 0.82
    return {
        **common,
        'protocol': 'lldp',
        'local_interface': local_port,
        'neighbor_name': neighbor_identity,
        'neighbor_interface': remote_port,
        'neighbor_management_ip': neighbor_ip,
        'neighbor_platform': common['neighbor_platform'],
        'neighbor_capabilities': common['neighbor_capabilities'],
        'neighbor_name_raw': neighbor_identity,
        'neighbor_name_normalized': normalize_hostname(neighbor_identity),
        'neighbor_ip_address': neighbor_ip,
        'neighbor_chassis_id': chassis_id,
        'source_port_raw': local_port,
        'source_port_normalized': normalize_interface_name(local_port),
        'target_port_raw': remote_port,
        'target_port_normalized': normalize_interface_name(remote_port),
        'confidence': confidence,
        'raw_payload_json': _safe_json(raw),
    }


def _deduplicate_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse parser duplicates while retaining the richest observation.

    LLDP detail output can repeat the same peer in multiple sections, and
    some TextFSM templates expose a partial record followed by a complete one.
    A local port + protocol + remote identity is the safe dedupe boundary; it
    does not collapse parallel links because those use different local ports.
    """
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for raw in observations:
        observation = dict(raw)
        source_port = _observation_port_normalized(observation, 'source_port_raw', 'source_port_normalized')
        protocol = str(observation.get('protocol') or 'lldp').strip().lower()
        chassis = re.sub(r'[^0-9a-z]', '', str(observation.get('neighbor_chassis_id') or '').lower())
        neighbor_ip = str(observation.get('neighbor_ip_address') or '').strip().lower()
        neighbor_name = normalize_hostname(
            observation.get('neighbor_name_normalized') or observation.get('neighbor_name_raw') or ''
        )
        identity = chassis or neighbor_ip or neighbor_name
        grouped.setdefault((source_port, protocol, identity), []).append(observation)

    deduplicated: list[dict[str, Any]] = []
    merge_fields = (
        'neighbor_name_raw',
        'neighbor_name_normalized',
        'neighbor_ip_address',
        'neighbor_chassis_id',
        'source_port_raw',
        'source_port_normalized',
        'target_port_raw',
        'target_port_normalized',
    )
    for records in grouped.values():
        def richness(item: dict[str, Any]) -> tuple[int, float]:
            populated = sum(1 for field in merge_fields if str(item.get(field) or '').strip())
            return populated, float(item.get('confidence') or 0.0)

        merged = dict(max(records, key=richness))
        for record in records:
            for field in merge_fields:
                if not str(merged.get(field) or '').strip() and str(record.get(field) or '').strip():
                    merged[field] = record[field]
            merged['confidence'] = max(
                float(merged.get('confidence') or 0.0),
                float(record.get('confidence') or 0.0),
            )
        merged['neighbor_name_normalized'] = normalize_hostname(
            merged.get('neighbor_name_raw') or merged.get('neighbor_name_normalized')
        )
        merged['source_port_normalized'] = _observation_port_normalized(
            merged, 'source_port_raw', 'source_port_normalized'
        )
        merged['target_port_normalized'] = _observation_port_normalized(
            merged, 'target_port_raw', 'target_port_normalized'
        )
        deduplicated.append(merged)

    return sorted(
        deduplicated,
        key=lambda item: (
            str(item.get('source_port_normalized') or ''),
            str(item.get('protocol') or ''),
            str(item.get('neighbor_name_normalized') or ''),
        ),
    )


def _parse_shared_lldp_output(platform: str, command: str, raw_text: str) -> list[dict[str, Any]]:
    """Parse Huawei/Comware LLDP tables with Nexora's custom templates."""
    if not raw_text or not str(raw_text).strip():
        return []
    try:
        result = smart_parse_cli(
            str(raw_text),
            command,
            # Keep a concrete H3C Profile code long enough for the parser to
            # select its explicit v5/v9 template variant.  The parser response
            # itself still reports the canonical h3c_comware family.
            platform=platform,
        )
        if result.get('success') and isinstance(result.get('data'), list):
            return result['data']
    except Exception as exc:  # noqa: BLE001
        logger.debug('Shared LLDP parser failed for %s %r: %s', platform, command, exc)
    return []


def _get_device(device_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
        if not row:
            return None
        device = dict(row)
        # Topology discovery is a read-only workflow and must use the
        # ordinary account stored on the linked CMDB asset. Administrative
        # credentials are reserved for backup/configuration workflows.
        collector_credentials = resolve_collector_credentials(device, ssh_role='normal')
        ssh_credentials = collector_credentials['ssh']
        device['username'] = ssh_credentials['username'] or device.get('username', '')
        device['password'] = ssh_credentials['password']
        device['enable_password'] = ssh_credentials['enable_password']
        return device
    finally:
        conn.close()


def _match_target_device_with_evidence(
    conn,
    neighbor_name: str,
    neighbor_ip: str,
    chassis_id: str = '',
) -> dict[str, Any]:
    """Score all candidates and refuse ambiguous prefix matches."""
    normalized_name = normalize_hostname(neighbor_name)
    normalized_ip = str(neighbor_ip or '').strip().lower()
    normalized_chassis = re.sub(r'[^0-9a-z]', '', str(chassis_id or '').lower())
    rows = conn.execute(
        'SELECT id, hostname, ip_address, sys_name, sn, model, site_id FROM devices'
    ).fetchall()
    candidates_by_id: dict[str, dict[str, Any]] = {}

    def add_candidate(device: dict[str, Any], score: float, method: str) -> None:
        current = candidates_by_id.get(str(device['id']))
        if current is None or score > float(current['score']):
            candidates_by_id[str(device['id'])] = {
                'device': device,
                'device_id': device['id'],
                'hostname': device.get('hostname') or '',
                'score': score,
                'method': method,
            }

    for row in rows:
        device = dict(row)
        device_ip = str(device.get('ip_address') or '').strip().lower()
        hostname = normalize_hostname(device.get('hostname'))
        sys_name = normalize_hostname(device.get('sys_name'))
        serial = re.sub(r'[^0-9a-z]', '', str(device.get('sn') or '').lower())

        if normalized_ip and device_ip and normalized_ip == device_ip:
            add_candidate(device, 1.0, 'management_ip')
        if normalized_chassis and serial and normalized_chassis == serial:
            add_candidate(device, 0.98, 'chassis_serial')
        if normalized_name and normalized_name in {hostname, sys_name}:
            add_candidate(device, 0.94, 'system_name')
        if len(normalized_name) >= 4:
            names = [value for value in (hostname, sys_name) if value]
            if any(value.startswith(normalized_name) or normalized_name.startswith(value) for value in names):
                add_candidate(device, 0.72, 'name_prefix')

    ordered = sorted(candidates_by_id.values(), key=lambda item: (-float(item['score']), str(item['hostname'])))
    public_candidates = [
        {
            'device_id': item['device_id'],
            'hostname': item['hostname'],
            'score': item['score'],
            'method': item['method'],
        }
        for item in ordered[:5]
    ]
    if not ordered:
        return {'device': None, 'status': 'unmatched', 'method': '', 'confidence': 0.0, 'candidates': []}

    best = ordered[0]
    if len(ordered) > 1 and float(best['score']) - float(ordered[1]['score']) < 0.05:
        return {
            'device': None,
            'status': 'ambiguous',
            'method': best['method'],
            'confidence': float(best['score']),
            'candidates': public_candidates,
        }
    return {
        'device': best['device'],
        'status': 'matched',
        'method': best['method'],
        'confidence': float(best['score']),
        'candidates': public_candidates,
    }


def _match_target_device(conn, neighbor_name: str, neighbor_ip: str, chassis_id: str = '') -> dict[str, Any] | None:
    return _match_target_device_with_evidence(conn, neighbor_name, neighbor_ip, chassis_id)['device']


def _build_link_key(source_device_id: str, source_port: str, target_device_id: str, target_port: str) -> str:
    left = (str(source_device_id), normalize_interface_name(source_port) or str(source_port or '').strip().lower())
    right = (str(target_device_id), normalize_interface_name(target_port) or str(target_port or '').strip().lower())
    ordered = sorted([left, right], key=lambda item: (item[0], item[1]))
    return f'{ordered[0][0]}::{ordered[0][1]}--{ordered[1][0]}::{ordered[1][1]}'


def _observation_port_normalized(observation: dict[str, Any], raw_key: str, normalized_key: str) -> str:
    """Normalize the observed port from its raw value, never stale metadata.

    Topology observations are durable evidence and can outlive a parser
    normalization change. Recomputing from ``*_raw`` during every rebuild
    prevents old aliases such as ``et0/1`` and ``eth0/1`` from becoming
    separate links.
    """
    raw = str(observation.get(raw_key) or '').strip()
    if raw:
        return normalize_interface_name(raw)
    return normalize_interface_name(str(observation.get(normalized_key) or '').strip())


def _canonical_link_endpoints(observation: dict[str, Any]) -> tuple[tuple[str, str], tuple[str, str]]:
    endpoints = [
        (
            str(observation.get('source_device_id') or ''),
            _observation_port_normalized(observation, 'source_port_raw', 'source_port_normalized'),
        ),
        (
            str(observation.get('target_device_id') or ''),
            _observation_port_normalized(observation, 'target_port_raw', 'target_port_normalized'),
        ),
    ]
    ordered = sorted(endpoints, key=lambda item: (item[0], item[1]))
    return ordered[0], ordered[1]


def _prefer_lldp_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only LLDP evidence when rebuilding topology links.

    Historical rows without a protocol are treated as legacy LLDP rows. CDP is
    never a fallback and cannot re-enter the active topology graph.
    """
    return [
        row for row in rows
        if str(row.get('protocol') or 'lldp').strip().lower() == 'lldp'
    ]


def _group_link_observations(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group directional evidence into physical links without merging parallel links.

    Complete endpoint/port pairs are canonical. A partial observation is
    attached only when its known port identifies exactly one complete link for
    the same device pair. Ambiguous partial evidence remains a separate link so
    the graph never invents connectivity.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    complete_keys_by_pair: dict[tuple[str, str], list[str]] = {}
    partial_rows: list[tuple[dict[str, Any], tuple[str, str], tuple[str, str]]] = []

    for item in rows:
        left, right = _canonical_link_endpoints(item)
        pair = (left[0], right[0])
        if left[1] and right[1]:
            link_key = f'{left[0]}::{left[1]}--{right[0]}::{right[1]}'
            grouped.setdefault(link_key, []).append(item)
            complete_keys_by_pair.setdefault(pair, []).append(link_key)
        else:
            partial_rows.append((item, left, right))

    for item, left, right in partial_rows:
        pair = (left[0], right[0])
        candidates: list[str] = []
        for link_key in set(complete_keys_by_pair.get(pair, [])):
            candidate_left, candidate_right = link_key.split('--', 1)
            candidate_left_port = candidate_left.split('::', 1)[1]
            candidate_right_port = candidate_right.split('::', 1)[1]
            if left[1] and candidate_left_port != left[1]:
                continue
            if right[1] and candidate_right_port != right[1]:
                continue
            candidates.append(link_key)
        if len(candidates) == 1:
            grouped[candidates[0]].append(item)
            continue

        link_key = f'{left[0]}::{left[1]}--{right[0]}::{right[1]}'
        grouped.setdefault(link_key, []).append(item)

    return grouped


def _interface_speed_mbps(row: dict[str, Any]) -> float:
    """Return an interface speed in Mbps from the inventory's bps fields."""
    for key in ('speed', 'bandwidth'):
        try:
            value = float(row.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            # Inventory stores speed/bandwidth in bits per second.
            return value / 1_000_000 if value >= 100_000 else value
    return float(interface_nominal_speed_mbps(row.get('interface_name') or row.get('name_display')))


def _interface_is_up(row: dict[str, Any]) -> bool:
    return str(row.get('oper_status') or row.get('status') or '').strip().lower() in {
        'up', 'up/up', 'online', 'active', 'selected', 'collecting', 'distributing',
    }


def _is_logical_aggregation_interface(row: dict[str, Any]) -> bool:
    """Recognise a logical LAG row without requiring a prior DB binding.

    Older interface collectors persisted the vendor-native aggregation rows
    as ``physical`` and left ``parent_interface_id`` empty.  The name is still
    authoritative for the read path; membership is resolved separately from
    the parallel link group and capacity below.
    """
    interface_type = str(row.get('interface_type') or '').strip().lower()
    if interface_type in {'port_channel', 'port-channel', 'lag', 'aggregation'}:
        return True
    compact = re.sub(r'[^a-z0-9-]', '', str(row.get('interface_name') or '').strip().lower())
    return bool(re.match(
        r'^(?:bridge-aggregation|route-aggregation|eth-trunk|port-channel|portchannel|bagg|ragg|po|be)\d+$',
        compact,
    ))


def _aggregation_family_key(value: Any) -> tuple[str, str] | None:
    """Return a stable family/number key for common LAG display aliases."""
    compact = re.sub(r'[^a-z0-9]', '', str(value or '').strip().lower())
    match = re.match(
        r'^(bridgeaggregation|bagg|routeaggregation|ragg|ethtrunk|portchannel|po|be)(\d+)$',
        compact,
    )
    if not match:
        return None
    prefix, number = match.groups()
    if prefix in {'bridgeaggregation', 'bagg'}:
        family = 'bridge'
    elif prefix in {'routeaggregation', 'ragg'}:
        family = 'route'
    else:
        family = 'trunk'
    return family, number


def _load_runtime_aggregation_candidates(conn) -> dict[str, list[dict[str, Any]]]:
    """Load logical LAG candidates for read-time contract synthesis.

    This function is deliberately read-only.  It exists for rolling upgrades
    where the interface table has logical rows but member parent bindings have
    not been written yet; no inventory backfill or mutation is performed.
    """
    rows = [dict(row) for row in conn.execute(
        '''
        SELECT id, device_id, interface_name, interface_type,
               aggregation_protocol, speed, bandwidth, oper_status
        FROM interfaces
        '''
    ).fetchall()]
    candidates: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not _is_logical_aggregation_interface(row):
            continue
        name = str(row.get('interface_name') or '').strip()
        device_id = str(row.get('device_id') or '').strip()
        if not name or not device_id:
            continue
        candidates.setdefault(device_id, []).append({
            'id': str(row.get('id') or ''),
            'name': name,
            'family_key': _aggregation_family_key(name),
            'capacity_mbps': _interface_speed_mbps(row),
            'protocol': str(row.get('aggregation_protocol') or '').strip(),
            'is_up': _interface_is_up(row),
        })
    return candidates


def _choose_runtime_aggregation_candidate(
    candidates: list[dict[str, Any]],
    member_capacity_mbps: float,
) -> dict[str, Any] | None:
    """Choose a parent whose advertised capacity matches a member bundle."""
    if not candidates or member_capacity_mbps <= 0:
        return None
    usable = [item for item in candidates if float(item.get('capacity_mbps') or 0) > 0]
    if not usable:
        return None
    tolerance = max(member_capacity_mbps * 0.2, 1.0)
    matched = [
        item for item in usable
        if abs(float(item.get('capacity_mbps') or 0) - member_capacity_mbps) <= tolerance
    ]
    # A logical interface with an unrelated capacity is not evidence that the
    # parallel links form a bundle.  Keep those links physical instead of
    # falling back to an arbitrary parent.
    if not matched:
        return None
    pool = matched
    return min(
        pool,
        key=lambda item: (
            abs(float(item.get('capacity_mbps') or 0) - member_capacity_mbps),
            0 if item.get('is_up') else 1,
            str(item.get('name') or ''),
        ),
    )


def _synthesise_runtime_aggregation_links(
    items: list[dict[str, Any]],
    conn,
) -> list[dict[str, Any]]:
    """Collapse verified parallel members into logical links at read time.

    A bundle is emitted only when both endpoints have a logical aggregation
    candidate whose advertised capacity matches the sum of the parallel
    member links and whose family/number agrees.  This avoids treating every
    pair of parallel LLDP observations as a LAG while still rendering legacy
    inventories correctly.
    """
    candidates_by_device = _load_runtime_aggregation_candidates(conn)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in items:
        if str(item.get('link_kind') or '').lower() == 'aggregation':
            continue
        source_id = str(item.get('source_device_id') or '').strip()
        target_id = str(item.get('target_device_id') or '').strip()
        if not source_id or not target_id or source_id == target_id:
            continue
        pair = tuple(sorted((source_id, target_id)))
        groups.setdefault(pair, []).append(item)

    replacements: dict[int, dict[str, Any]] = {}
    consumed: set[int] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        first = group[0]
        source_id = str(first.get('source_device_id') or '')
        target_id = str(first.get('target_device_id') or '')
        member_capacity = sum(
            float(item.get('bandwidth_mbps') or item.get('aggregation_bandwidth_mbps') or 0)
            for item in group
        )
        source_parent = _choose_runtime_aggregation_candidate(
            candidates_by_device.get(source_id, []), member_capacity,
        )
        target_parent = _choose_runtime_aggregation_candidate(
            candidates_by_device.get(target_id, []), member_capacity,
        )
        if not source_parent or not target_parent:
            continue
        source_family = source_parent.get('family_key')
        target_family = target_parent.get('family_key')
        if source_family and target_family and source_family != target_family:
            continue
        if source_family and target_family and source_family[1] != target_family[1]:
            continue

        members: list[dict[str, Any]] = []
        for item in group:
            item_source_id = str(item.get('source_device_id') or '')
            item_target_id = str(item.get('target_device_id') or '')
            source_endpoint = {
                'name': item.get('source_port') or item.get('source_port_normalized') or '',
                'normalized': item.get('source_port_normalized') or '',
                'device_id': item_source_id,
                'speed_mbps': float(item.get('bandwidth_mbps') or item.get('aggregation_bandwidth_mbps') or 0),
                'up': str(item.get('operational_state') or '').lower() not in {'down', 'stale'},
            }
            target_endpoint = {
                'name': item.get('target_port') or item.get('target_port_normalized') or '',
                'normalized': item.get('target_port_normalized') or '',
                'device_id': item_target_id,
                'speed_mbps': float(item.get('bandwidth_mbps') or item.get('aggregation_bandwidth_mbps') or 0),
                'up': str(item.get('operational_state') or '').lower() not in {'down', 'stale'},
            }
            if item_source_id == target_id and item_target_id == source_id:
                source_endpoint, target_endpoint = target_endpoint, source_endpoint
            members.append({
                'source': source_endpoint,
                'target': target_endpoint,
                'protocol': item.get('discovery_source') or item.get('protocol') or 'lldp',
            })

        aggregation = dict(first)
        aggregation.update({
            'link_kind': 'aggregation',
            'source_aggregation_name': source_parent['name'],
            'target_aggregation_name': target_parent['name'],
            'source_aggregation_id': source_parent.get('id') or '',
            'target_aggregation_id': target_parent.get('id') or '',
            'aggregation_protocol': source_parent.get('protocol') or target_parent.get('protocol') or '',
            'member_count': len(members),
            'active_member_count': sum(
                1 for member in members if member['source'].get('up') and member['target'].get('up')
            ),
            'aggregation_bandwidth_mbps': member_capacity,
            'members': members,
            'members_json': json.dumps(members, ensure_ascii=False),
        })
        if aggregation['active_member_count'] == aggregation['member_count']:
            aggregation['operational_state'] = 'up'
            aggregation['status'] = 'up'
        elif aggregation['active_member_count']:
            aggregation['operational_state'] = 'degraded'
            aggregation['status'] = 'degraded'
        else:
            aggregation['operational_state'] = 'unknown'
            aggregation['status'] = 'unknown'
        replacements[id(first)] = aggregation
        consumed.update(id(item) for item in group)

    output: list[dict[str, Any]] = []
    for item in items:
        item_id = id(item)
        if item_id in replacements:
            output.append(replacements[item_id])
        elif item_id not in consumed:
            output.append(item)
    return output


def _clean_interface_display_name(value: Any) -> str:
    """Remove parser presentation suffixes while retaining vendor spelling."""
    text = str(value or '').strip()
    return re.sub(r'\s+interface\s*$', '', text, flags=re.IGNORECASE).strip()


def _interface_display_score(row: dict[str, Any], device_meta: dict[str, Any]) -> tuple[int, int, str]:
    """Rank duplicate interface aliases for a stable native display name.

    Discovery can create both Cisco ``Et0/1`` and ``Ethernet0/1`` (or H3C
    ``GE3/0`` and ``GigabitEthernet3/0``) for the same normalized interface.
    Prefer an explicit display name, then the vendor's usual native CLI form.
    """
    raw = _clean_interface_display_name(row.get('name_display') or row.get('interface_name'))
    compact = re.sub(r'\s+', '', raw).lower()
    vendor = str(device_meta.get('vendor') or '').strip().lower()
    score = 0
    # Topology may have both a raw LLDP alias (for example XGE1/0/49) and a
    # long-form interface inventory row (Ten-GigabitEthernet1/0/49).  Prefer
    # the row carrying a real negotiated/configured rate; placeholder rows
    # created from neighbor evidence often have speed=0 and would otherwise
    # make a healthy 10G link render as unknown.
    try:
        has_rate = float(row.get('speed') or row.get('bandwidth') or 0) > 0
    except (TypeError, ValueError):
        has_rate = False
    if has_rate:
        score += 10000
    if row.get('name_display'):
        score += 1000
    if vendor == 'cisco' or 'cisco' in str(device_meta.get('platform') or '').lower():
        if re.match(r'^ethernet\d', compact):
            score += 80
        elif re.match(r'^(fastethernet|tengigabitethernet|gigabitethernet)\d', compact):
            score += 78
        elif re.match(r'^(et|e|te|gi|fa)\d', compact):
            score += 60
    elif vendor in {'h3c', 'huawei'} or any(
        token in str(device_meta.get('platform') or '').lower() for token in ('comware', 'huawei', 'vrp')
    ):
        if re.match(r'^(ge|xge|te|xe|fe|eth)\d', compact):
            score += 80
        elif re.match(r'^(gigabitethernet|tengigabitethernet|fastethernet)\d', compact):
            score += 65
    # A suffix-stripped value is always preferable to the raw parser label.
    if str(row.get('interface_name') or '').strip().lower().endswith(' interface'):
        score -= 20
    return score, len(raw), raw


def _canonical_fallback_interface_name(value: Any, device_meta: dict[str, Any]) -> str:
    """Expand a short LLDP alias when the interface inventory is incomplete."""
    raw = _clean_interface_display_name(value)
    compact = re.sub(r'\s+', '', raw)
    vendor = str(device_meta.get('vendor') or '').strip().lower()
    platform = str(device_meta.get('platform') or '').strip().lower()
    if vendor == 'cisco' or 'cisco' in platform:
        match = re.match(r'^(?:e|et)(\d.*)$', compact, flags=re.IGNORECASE)
        if match:
            return f'Ethernet{match.group(1)}'
    if vendor in {'h3c', 'huawei'} or any(token in platform for token in ('comware', 'huawei', 'vrp')):
        match = re.match(r'^(?:ge|gi|gigabitethernet)(\d.*)$', compact, flags=re.IGNORECASE)
        if match:
            return f'GE{match.group(1)}'
    return raw


def _load_interface_aggregation_map(conn) -> dict[tuple[str, str], dict[str, Any]]:
    """Build a vendor-neutral lookup from physical ports to their logical LAG.

    The inventory already stores ``interface_type``, ``parent_interface_id``
    and ``channel_group``.  This helper keeps the topology service independent
    of vendor naming while preserving the original interface name for display.
    """
    rows = [dict(row) for row in conn.execute(
        '''
        SELECT id, device_id, interface_name, interface_type, parent_interface_id,
               channel_group, aggregation_protocol, speed, bandwidth, admin_status, oper_status
        FROM interfaces
        '''
    ).fetchall()]
    by_id = {str(row.get('id') or ''): row for row in rows if row.get('id')}
    logical_by_channel: dict[tuple[str, int], dict[str, Any]] = {}
    logical_types = {'port_channel', 'port-channel', 'lag', 'aggregation'}

    def is_logical_aggregation(row: dict[str, Any]) -> bool:
        interface_type = str(row.get('interface_type') or '').strip().lower()
        if interface_type in logical_types:
            return True
        # Older CMDB/interface collectors wrote every row as ``physical``.
        # The vendor-native name is still authoritative enough to identify
        # the logical parent, but it must not be used to invent membership.
        name = re.sub(r'[^a-z0-9-]', '', str(row.get('interface_name') or '').strip().lower())
        return bool(re.match(
            r'^(?:bridge-aggregation|route-aggregation|eth-trunk|port-channel|portchannel|bagg|ragg|po|be)\d+$',
            name,
        ))

    def trailing_number(value: Any) -> int | None:
        match = re.search(r'(\d+)(?:\.\d+)?$', str(value or '').strip())
        return int(match.group(1)) if match else None

    for row in rows:
        if not is_logical_aggregation(row):
            continue
        channel = trailing_number(row.get('interface_name'))
        if channel is not None:
            logical_by_channel[(str(row.get('device_id') or ''), channel)] = row

    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        device_id = str(row.get('device_id') or '')
        raw_name = str(row.get('interface_name') or '').strip()
        if not device_id or not raw_name:
            continue
        interface_type = str(row.get('interface_type') or 'physical').strip().lower()
        parent = by_id.get(str(row.get('parent_interface_id') or ''))
        if parent is None and not is_logical_aggregation(row):
            try:
                channel_group = int(row.get('channel_group')) if row.get('channel_group') is not None else None
            except (TypeError, ValueError):
                channel_group = None
            if channel_group is not None:
                parent = logical_by_channel.get((device_id, channel_group))
        if parent is None and is_logical_aggregation(row):
            parent = row
        if parent is None:
            continue

        parent_id = str(parent.get('id') or '')
        parent_name = str(parent.get('interface_name') or '').strip()
        if not parent_id or not parent_name:
            continue
        result[(device_id, normalize_interface_name(raw_name).lower())] = {
            'aggregation_id': parent_id,
            'aggregation_name': parent_name,
            'aggregation_protocol': str(parent.get('aggregation_protocol') or '').strip(),
            'is_logical': parent_id == str(row.get('id') or ''),
            'interface_id': str(row.get('id') or ''),
            'raw_name': raw_name,
            'speed_mbps': _interface_speed_mbps(row),
            'is_up': _interface_is_up(row),
        }
    return result


def _sync_aggregation_inventory(device: dict[str, Any], platform_action_session=None) -> dict[str, int]:
    """Persist vendor-specific LAG membership for the next topology rebuild.

    LLDP exposes physical member ports, while the aggregation command
    exposes the parent/member relationship.  We collect the latter once per
    topology discovery run and keep the raw vendor names in ``interfaces``.
    A failure is intentionally isolated from neighbor discovery.
    """
    if str(os.environ.get('TOPOLOGY_AGGREGATION_DISCOVERY_ENABLED', '1')).strip().lower() in {'0', 'false', 'no'}:
        return {'parents': 0, 'members': 0}
    try:
        from services.operational_data_service import collect_operational_data

        # The CMDB interface collector owns interface status.  Topology only
        # refreshes the vendor-specific parent/member relationship needed to
        # collapse LLDP member links into one logical aggregation edge.
        payload = collect_operational_data(
            device,
            categories=['eth_trunk'],
            auth_role='admin',
            _platform_action_session=platform_action_session,
        )
        category = next((item for item in payload.get('categories', []) if item.get('key') == 'eth_trunk'), None)
        records = list(category.get('records') or []) if category else []
    except Exception as exc:  # noqa: BLE001
        logger.info('Aggregation inventory skipped for %s: %s', device.get('hostname'), exc)
        return {'parents': 0, 'members': 0}
    if not records:
        return {'parents': 0, 'members': 0}

    def value(record: dict[str, Any], *keys: str) -> str:
        normalized = {
            str(record_key).strip().replace('-', '_').upper(): raw_value
            for record_key, raw_value in record.items()
        }
        for key in keys:
            raw = normalized.get(str(key).strip().replace('-', '_').upper())
            if raw is not None and str(raw).strip():
                return str(raw).strip()
        return ''

    def clean_member(value_raw: str) -> str:
        cleaned = re.sub(r'\([^)]*\)', '', value_raw or '')
        cleaned = re.sub(r'\s+', '', cleaned).strip()
        return cleaned

    conn = get_db_connection()
    parents = 0
    members = 0
    interfaces = 0
    try:
        device_id = str(device.get('id') or '')
        interface_rows = conn.execute(
            'SELECT id, interface_name FROM interfaces WHERE device_id = ?', (device_id,)
        ).fetchall()
        interface_map = {
            normalize_interface_name(row['interface_name']).lower(): str(row['id'])
            for row in interface_rows
        }
        # The aggregation command is an authoritative snapshot.  Do not
        # leave members from a previous collection attached to the same
        # parent (for example old GE1/0/3-4 after a migration to XGE1/0/49-52).
        # Only clear bindings after a non-empty command result; a transport or
        # parser failure returns above and therefore cannot erase good data.
        if records:
            conn.execute(
                '''
                UPDATE interfaces
                SET parent_interface_id = NULL,
                    channel_group = NULL,
                    aggregation_protocol = ''
                WHERE device_id = ?
                  AND parent_interface_id IN (
                      SELECT id
                      FROM interfaces
                      WHERE device_id = ?
                        AND interface_type = 'port_channel'
                  )
                ''',
                (device_id, device_id),
            )

        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            parent_name = clean_member(value(record, 'AGGREGATE_INTERFACE', 'ETH_TRUNK', 'PORT_CHANNEL', 'PORTCHANNEL', 'BUNDLE'))
            member_name = clean_member(value(record, 'INTERFACE', 'MEMBER_INTERFACE', 'MEMBER', 'PORT'))
            if parent_name and member_name:
                grouped.setdefault(parent_name, []).append(record)

        for parent_name, parent_records in grouped.items():
            parent_norm = normalize_interface_name(parent_name).lower()
            parent_row = conn.execute(
                'SELECT id FROM interfaces WHERE device_id = ? AND interface_name = ?',
                (device_id, parent_name),
            ).fetchone()
            parent_id = str(parent_row['id']) if parent_row else str(uuid.uuid4())
            first = parent_records[0]
            mode = value(first, 'AGGREGATION_MODE', 'MODE', 'PROTOCOL').lower()
            protocol = 'LACP' if any(token in mode for token in ('dynamic', 'lacp')) else ('static' if mode else '')
            parent_status = value(first, 'OPERATE_STATUS', 'STATUS').lower()
            parent_oper = 'up' if parent_status in {'up', 'active', 'selected'} else 'down'
            conn.execute(
                '''
                INSERT INTO interfaces (
                    id, device_id, interface_name, interface_type, admin_status, oper_status,
                    aggregation_protocol
                ) VALUES (?, ?, ?, 'port_channel', 'up', ?, ?)
                ON CONFLICT(device_id, interface_name) DO UPDATE SET
                    interface_type = 'port_channel', oper_status = excluded.oper_status,
                    aggregation_protocol = excluded.aggregation_protocol
                ''',
                (parent_id, device_id, parent_name, parent_oper, protocol),
            )
            interface_map[parent_norm] = parent_id
            parents += 1

            channel_match = re.search(r'(\d+)(?:\.\d+)?$', parent_name)
            channel_group = int(channel_match.group(1)) if channel_match else None
            for record in parent_records:
                member_name = clean_member(value(record, 'INTERFACE', 'MEMBER_INTERFACE', 'MEMBER', 'PORT'))
                if not member_name:
                    continue
                member_norm = normalize_interface_name(member_name).lower()
                member_id = interface_map.get(member_norm)
                if not member_id:
                    member_id = str(uuid.uuid4())
                    conn.execute(
                        '''
                        INSERT INTO interfaces (
                            id, device_id, interface_name, interface_type, admin_status, oper_status,
                            parent_interface_id, channel_group
                        ) VALUES (?, ?, ?, 'physical', 'unknown', 'unknown', ?, ?)
                        ON CONFLICT(device_id, interface_name) DO UPDATE SET
                            parent_interface_id = excluded.parent_interface_id,
                            channel_group = excluded.channel_group
                        ''',
                        (member_id, device_id, member_name, parent_id, channel_group),
                    )
                    interface_map[member_norm] = member_id
                member_status = value(record, 'STATUS', 'PORT_STATUS').lower()
                member_oper = 'up' if member_status in {'s', 'selected', 'up', 'active', 'collecting', 'distributing'} else 'down'
                conn.execute(
                    '''
                    UPDATE interfaces SET parent_interface_id = ?, channel_group = ?,
                        oper_status = ?, aggregation_protocol = ?
                    WHERE id = ?
                    ''',
                    (parent_id, channel_group, member_oper, protocol, member_id),
                )
                members += 1
        conn.commit()
        return {'parents': parents, 'members': members, 'interfaces': interfaces}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _collapse_aggregation_groups(
    grouped: dict[str, list[dict[str, Any]]],
    aggregation_map: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Collapse physical member observations into one logical LAG edge.

    A link is collapsed only when both endpoints resolve to a logical
    aggregation.  Ambiguous or one-sided evidence remains a physical link.
    """
    collapsed: dict[str, dict[str, Any]] = {}
    aggregation_groups: dict[str, dict[str, Any]] = {}

    for link_key, observations in grouped.items():
        first = observations[0] if observations else {}
        source_key = (
            str(first.get('source_device_id') or ''),
            _observation_port_normalized(first, 'source_port_raw', 'source_port_normalized').lower(),
        )
        target_key = (
            str(first.get('target_device_id') or ''),
            _observation_port_normalized(first, 'target_port_raw', 'target_port_normalized').lower(),
        )
        source_agg = aggregation_map.get(source_key)
        target_agg = aggregation_map.get(target_key)
        if not source_agg or not target_agg:
            collapsed[link_key] = {'observations': observations, 'aggregation': None}
            continue

        endpoints = sorted([
            (str(first.get('source_device_id') or ''), source_agg),
            (str(first.get('target_device_id') or ''), target_agg),
        ], key=lambda item: item[0])
        group_key = (
            f"agg:{endpoints[0][0]}::{endpoints[0][1]['aggregation_id']}"
            f"--{endpoints[1][0]}::{endpoints[1][1]['aggregation_id']}"
        )
        group = aggregation_groups.setdefault(group_key, {
            'observations': [],
            'aggregation': {
                'source_device_id': endpoints[0][0],
                'source_aggregation_id': endpoints[0][1]['aggregation_id'],
                'source_aggregation_name': endpoints[0][1]['aggregation_name'],
                'target_device_id': endpoints[1][0],
                'target_aggregation_id': endpoints[1][1]['aggregation_id'],
                'target_aggregation_name': endpoints[1][1]['aggregation_name'],
                'aggregation_protocol': endpoints[0][1].get('aggregation_protocol') or endpoints[1][1].get('aggregation_protocol') or '',
                'member_pairs': {},
            },
        })
        group['observations'].extend(observations)
        aggregation = group['aggregation']
        for observation in observations:
            source_member_key = (
                str(observation.get('source_device_id') or ''),
                _observation_port_normalized(observation, 'source_port_raw', 'source_port_normalized').lower(),
            )
            target_member_key = (
                str(observation.get('target_device_id') or ''),
                _observation_port_normalized(observation, 'target_port_raw', 'target_port_normalized').lower(),
            )
            source_member_agg = aggregation_map.get(source_member_key) or source_agg
            target_member_agg = aggregation_map.get(target_member_key) or target_agg
            source_member = {
                'name': str(observation.get('source_port_raw') or observation.get('source_port_normalized') or ''),
                'normalized': str(observation.get('source_port_normalized') or ''),
                'device_id': str(observation.get('source_device_id') or ''),
                'speed_mbps': source_member_agg.get('speed_mbps') or 0,
                'up': source_member_agg.get('is_up', False),
            }
            target_member = {
                'name': str(observation.get('target_port_raw') or observation.get('target_port_normalized') or ''),
                'normalized': str(observation.get('target_port_normalized') or ''),
                'device_id': str(observation.get('target_device_id') or ''),
                'speed_mbps': target_member_agg.get('speed_mbps') or 0,
                'up': target_member_agg.get('is_up', False),
            }
            pair_key = '::'.join(sorted([
                f"{source_member['device_id']}:{source_member['normalized']}",
                f"{target_member['device_id']}:{target_member['normalized']}",
            ]))
            aggregation['member_pairs'][pair_key] = {
                'source': source_member,
                'target': target_member,
                'protocol': observation.get('protocol') or '',
            }

    collapsed.update(aggregation_groups)
    for bundle in collapsed.values():
        aggregation = bundle.get('aggregation')
        if not aggregation:
            continue
        members = list(aggregation['member_pairs'].values())
        source_capacity = sum(float(item['source'].get('speed_mbps') or 0) for item in members)
        target_capacity = sum(float(item['target'].get('speed_mbps') or 0) for item in members)
        aggregation['members'] = members
        aggregation['member_count'] = len(members)
        aggregation['active_member_count'] = sum(
            1 for item in members if item['source'].get('up') and item['target'].get('up')
        )
        aggregation['bandwidth_mbps'] = min(source_capacity, target_capacity) if source_capacity and target_capacity else max(source_capacity, target_capacity)
        if aggregation['active_member_count'] and aggregation['active_member_count'] < aggregation['member_count']:
            aggregation['status'] = 'degraded'
        elif aggregation['member_count'] and aggregation['active_member_count'] == aggregation['member_count']:
            aggregation['status'] = 'up'
        else:
            aggregation['status'] = 'unknown'
    return collapsed


async def _collect_neighbors_with_netmiko(
    device: dict[str, Any],
    commands: list[tuple[str, str]],
    platform_action_session=None,
) -> tuple[list[dict[str, Any]], str]:
    if device.get('platform_profile_id'):
        from services.platform_registry_service import PlatformRegistryError, execute_platform_action

        user = {
            'id': f"topology:{device.get('id') or 'unknown'}",
            'username': 'topology-collector',
            'role': 'Operator',
            'tenant_id': device.get('tenant_id') or '',
        }
        try:
            action_kwargs = {
                'user': user,
                'include_raw_output': True,
            }
            if platform_action_session is not None:
                action_kwargs['_session'] = platform_action_session
            result = await asyncio.to_thread(
                execute_platform_action,
                str(device['id']),
                'get_lldp_neighbors',
                **action_kwargs,
            )
        except PlatformRegistryError as exc:
            raise RuntimeError(f"platform_registry:{exc.code}:{exc.message}") from exc
        if not result.get('success'):
            raise RuntimeError(f"platform_registry:{result.get('error_code') or 'ACTION_FAILED'}:{result.get('error') or 'LLDP action failed'}")
        observations: list[dict[str, Any]] = []
        for item in result.get('records') or []:
            observation = _extract_observation_fields(item, 'lldp')
            if observation['neighbor_name_raw'] and observation['source_port_raw']:
                observations.append(observation)
        return observations, 'platform-registry'

    platform = normalize_topology_platform(device.get('platform'))
    device_type = PLATFORM_MAP.get(platform)
    if not device_type:
        raise RuntimeError(f'topology_platform_unsupported:{platform}')
    netmiko_device = {
        'device_type': device_type,
        'host': device.get('ip_address'),
        'username': device.get('username'),
        'password': device.get('password'),
        'port': int(device.get('management_port') or device.get('port') or 22),
        'fast_cli': True,
    }
    netmiko_device.update(build_netmiko_compatibility_kwargs())

    def _run_commands() -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        with limited_connect_handler(device, ConnectHandler, **netmiko_device) as client:
            for protocol, command in commands:
                assert_lldp_command(platform, command, scenario_id='topology_lldp')
                is_comware = 'comware' in device_type or 'hp_comware' in device_type or 'h3c' in str(device.get('platform', '')).lower()
                parsed = None
                raw_text = ''
                if is_comware or 'huawei' in platform:
                    raw_text = client.send_command(command)
                    parsed = _parse_shared_lldp_output(platform, command, raw_text)
                else:
                    try:
                        parsed = client.send_command(command, use_textfsm=True)
                    except Exception:
                        parsed = None

                if isinstance(parsed, list) and parsed:
                    # TextFSM parsed successfully
                    for item in parsed:
                        observation = _extract_observation_fields(item, protocol)
                        if observation['neighbor_name_raw'] and observation['source_port_raw']:
                            collected.append(observation)
                else:
                    # TextFSM template bypassed/missed — try regex fallback for LLDP detail
                    raw_text = raw_text or (parsed if isinstance(parsed, str) else client.send_command(command))
                    logger.info('TextFSM template bypassed/missed for %s %r, using regex parser', device_type, command)
                    regex_entries = _regex_parse_lldp_detail(raw_text)
                    for item in regex_entries:
                        observation = _extract_observation_fields(item, protocol)
                        if observation['neighbor_name_raw'] and observation['source_port_raw']:
                            collected.append(observation)
        return collected

    loop = asyncio.get_running_loop()
    collected = await loop.run_in_executor(None, _run_commands)
    return collected, 'netmiko'


async def _collect_device_observations(device: dict[str, Any], platform_action_session=None) -> tuple[list[dict[str, Any]], str]:
    ip = device.get('ip_address')
    port = int(device.get('management_port') or device.get('port') or 22)
    from drivers.ssh_compat import is_ssh_port_open
    if not is_ssh_port_open(ip, port):
        logger.warning('Skip topology discovery for %s: SSH port %s is closed/unreachable', device.get('hostname'), port)
        raise RuntimeError(f"SSH port {port} is closed/unreachable")

    platform = normalize_topology_platform(device.get('platform'))
    commands = DISCOVERY_COMMANDS[platform]
    for protocol, command in commands:
        assert_lldp_command(platform, command, scenario_id='topology_lldp')
    try:
        observations, method = await _collect_neighbors_with_netmiko(
            device,
            commands,
            platform_action_session=platform_action_session,
        )
        return observations, method
    except Exception as exc:  # noqa: BLE001
        logger.error('Netmiko topology discovery failed for %s: %s', device.get('hostname'), exc)
        raise RuntimeError(str(exc)) from exc


def _replace_device_observations(
    device: dict[str, Any],
    observations: list[dict[str, Any]],
    run_id: str | None,
) -> dict[str, int]:
    now = _utc_now_iso()
    matched = 0
    ambiguous = 0
    unmatched = 0
    conn = get_db_connection()
    try:
        source_site_id = str(device.get('site_id') or '')
        observed_keys: set[tuple[str, str, str, str]] = set()
        for observation in observations:
            protocol = str(observation.get('protocol') or 'lldp').strip().lower()
            if protocol != 'lldp':
                raise ValueError(f'neighbor_protocol_forbidden:{protocol}')
            source_port = str(observation.get('source_port_normalized') or '').strip()
            neighbor_name = str(observation.get('neighbor_name_normalized') or '').strip()
            target_port = str(observation.get('target_port_normalized') or '').strip()
            identity_key = (source_port, neighbor_name, target_port, protocol)
            observed_keys.add(identity_key)
            evidence = _match_target_device_with_evidence(
                conn,
                observation['neighbor_name_raw'],
                observation['neighbor_ip_address'],
                observation.get('neighbor_chassis_id', ''),
            )
            target_device = evidence.get('device')
            if target_device and target_device.get('id') == device.get('id'):
                target_device = None
                evidence = {**evidence, 'device': None, 'status': 'unmatched', 'method': 'self_reference'}

            match_status = str(evidence.get('status') or 'unmatched')
            if match_status == 'matched':
                matched += 1
            elif match_status == 'ambiguous':
                ambiguous += 1
            else:
                unmatched += 1

            protocol_confidence = float(observation.get('confidence') or 0.0)
            identity_confidence = float(evidence.get('confidence') or 0.0)
            final_confidence = min(protocol_confidence, identity_confidence) if target_device else protocol_confidence
            existing = conn.execute(
                '''
                SELECT id, first_seen_at
                FROM topology_observations
                WHERE source_device_id = ?
                  AND source_port_normalized = ?
                  AND neighbor_name_normalized = ?
                  AND target_port_normalized = ?
                  AND protocol = 'lldp'
                ORDER BY updated_at DESC
                LIMIT 1
                ''',
                (device['id'], source_port, neighbor_name, target_port),
            ).fetchone()
            if existing:
                conn.execute(
                    '''
                    UPDATE topology_observations
                    SET source_hostname = ?, source_port_raw = ?, neighbor_name_raw = ?, neighbor_ip_address = ?,
                        target_device_id = ?, target_hostname = ?, target_port_raw = ?, confidence = ?,
                        status = 'active', discovery_run_id = ?, raw_payload_json = ?, collected_at = ?,
                        updated_at = ?, source_site_id = ?, match_method = ?, match_status = ?,
                        match_candidates_json = ?, last_seen_at = ?, miss_count = 0, is_active = 1
                    WHERE id = ?
                    ''',
                    (
                        device.get('hostname') or '',
                        observation['source_port_raw'],
                        observation['neighbor_name_raw'],
                        observation['neighbor_ip_address'],
                        target_device['id'] if target_device else None,
                        target_device.get('hostname') if target_device else observation['neighbor_name_raw'],
                        observation['target_port_raw'],
                        final_confidence,
                        run_id,
                        observation['raw_payload_json'],
                        now,  # collected_at
                        now,  # updated_at
                        source_site_id,
                        evidence.get('method') or '',
                        match_status,
                        _safe_json(evidence.get('candidates') or []),
                        now,  # last_seen_at
                        existing['id'],
                    ),
                )
            else:
                conn.execute(
                    '''
                    INSERT INTO topology_observations (
                        id, source_device_id, source_hostname, source_port_raw, source_port_normalized,
                        neighbor_name_raw, neighbor_name_normalized, neighbor_ip_address,
                        target_device_id, target_hostname, target_port_raw, target_port_normalized,
                        protocol, confidence, status, discovery_run_id, raw_payload_json, collected_at, updated_at,
                        source_site_id, match_method, match_status, match_candidates_json,
                        first_seen_at, last_seen_at, miss_count, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'lldp', ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
                    ''',
                    (
                        str(uuid.uuid4()),
                        device['id'],
                        device.get('hostname') or '',
                        observation['source_port_raw'],
                        source_port,
                        observation['neighbor_name_raw'],
                        neighbor_name,
                        observation['neighbor_ip_address'],
                        target_device['id'] if target_device else None,
                        target_device.get('hostname') if target_device else observation['neighbor_name_raw'],
                        observation['target_port_raw'],
                        target_port,
                        final_confidence,
                        run_id,
                        observation['raw_payload_json'],
                        now,
                        now,
                        source_site_id,
                        evidence.get('method') or '',
                        match_status,
                        _safe_json(evidence.get('candidates') or []),
                        now,
                        now,
                    ),
                )

        # A successful scan is allowed to age observations. Failed scans never
        # call this function, so previously valid evidence is preserved.
        active_rows = conn.execute(
            '''
            SELECT id, source_port_normalized, neighbor_name_normalized,
                   target_port_normalized, protocol, miss_count
            FROM topology_observations
            WHERE source_device_id = ? AND protocol = 'lldp' AND COALESCE(is_active, 1) = 1
            ''',
            (device['id'],),
        ).fetchall()
        for row in active_rows:
            row_key = (
                str(row['source_port_normalized'] or ''),
                str(row['neighbor_name_normalized'] or ''),
                str(row['target_port_normalized'] or ''),
                str(row['protocol'] or 'lldp'),
            )
            if row_key in observed_keys:
                continue
            next_miss_count = int(row['miss_count'] or 0) + 1 if 'miss_count' in row.keys() else 1
            # A successful device scan is a complete snapshot for that
            # device.  Keeping a missing neighbor active for three scans
            # makes a changed port/LAG appear in the current topology after
            # the device has already reported the new state.  Retain the row
            # as stale history, but remove it from active evidence immediately.
            stale = next_miss_count >= 1
            conn.execute(
                '''
                UPDATE topology_observations
                SET miss_count = ?, is_active = ?, status = ?, updated_at = ?
                WHERE id = ?
                ''',
                (next_miss_count, 0 if stale else 1, 'stale' if stale else 'active', now, row['id']),
            )
        conn.commit()
        return {'matched': matched, 'ambiguous': ambiguous, 'unmatched': unmatched}
    finally:
        conn.close()


def rebuild_links_from_observations() -> int:
    with _topology_rebuild_lock:
        total_links = _rebuild_links_from_observations_unlocked()
        _sync_evidence_graph_from_observations()
        invalidate_read_cache('topology')
        return total_links


def _rebuild_links_from_observations_unlocked() -> int:
    conn = get_db_connection()
    try:
        existing_rows = conn.execute('SELECT * FROM topology_links').fetchall()
        existing_by_key = {str(row['link_key'] or ''): dict(row) for row in existing_rows if row['link_key']}
        rows = conn.execute(
            '''
            SELECT * FROM topology_observations
            WHERE target_device_id IS NOT NULL
              AND COALESCE(source_port_normalized, '') <> ''
              AND COALESCE(match_status, 'matched') = 'matched'
              AND COALESCE(is_active, 1) = 1
            '''
        ).fetchall()

        grouped = _group_link_observations(_prefer_lldp_rows([dict(row) for row in rows]))
        aggregation_map = _load_interface_aggregation_map(conn)
        grouped_with_contract = _collapse_aggregation_groups(grouped, aggregation_map)
        # Load all interfaces into memory for fast lookup.  A previous
        # discovery may have stored both short and long aliases for one
        # physical port; retain the best native spelling for display while
        # still matching through the normalized key.
        device_meta_rows = conn.execute("SELECT id, vendor, platform FROM devices").fetchall()
        device_meta = {str(row['id']): dict(row) for row in device_meta_rows}
        intf_rows = conn.execute(
            "SELECT id, device_id, interface_name, name_display, interface_type, speed, bandwidth FROM interfaces"
        ).fetchall()
        interface_map: dict[tuple[str, str], dict[str, Any]] = {}
        for raw_row in intf_rows:
            row = dict(raw_row)
            dev_id = str(row.get('device_id') or '')
            intf_name = row.get('interface_name') or ''
            norm = normalize_interface_name(intf_name).lower()
            if not dev_id or not norm:
                continue
            key = (dev_id, norm)
            current = interface_map.get(key)
            if current is None or _interface_display_score(row, device_meta.get(dev_id, {})) > _interface_display_score(current, device_meta.get(dev_id, {})):
                row['display_name'] = _clean_interface_display_name(row.get('name_display') or intf_name)
                row['speed'] = row.get('speed')
                row['bandwidth'] = row.get('bandwidth')
                interface_map[key] = row

        site_aliases, _ = _load_site_identity_maps(conn)
        device_site_rows = conn.execute('SELECT id, site_id FROM devices').fetchall()
        device_sites = {
            str(row['id']): _canonical_site_id(row['site_id'], site_aliases)
            for row in device_site_rows
        }

        now = _utc_now_iso()
        conn.execute('DELETE FROM topology_links')
        active_link_keys: set[str] = set()

        for link_key, bundle in grouped_with_contract.items():
            observations = bundle['observations']
            aggregation = bundle.get('aggregation') or {}
            active_link_keys.add(link_key)
            first = max(
                observations,
                key=lambda item: (
                    int(bool(item.get('source_port_normalized') or item.get('source_port_raw')))
                    + int(bool(item.get('target_port_normalized') or item.get('target_port_raw'))),
                    float(item.get('confidence') or 0.0),
                ),
            )
            existing = existing_by_key.get(link_key, {})
            reverse_seen = any(
                obs['source_device_id'] == first['target_device_id'] and obs['target_device_id'] == first['source_device_id']
                for obs in observations
            )
            protocols = sorted({obs.get('protocol') or 'lldp' for obs in observations})
            confidence = 1.0 if reverse_seen else max(float(obs.get('confidence') or 0.0) for obs in observations)

            is_aggregation = bool(aggregation)
            ordered = sorted(
                [
                    {
                        'device_id': first['source_device_id'],
                        'hostname': first.get('source_hostname') or '',
                        'port_raw': (aggregation.get('source_aggregation_name') if is_aggregation and str(first['source_device_id']) == str(aggregation.get('source_device_id')) else first.get('source_port_raw')) or '',
                        'port_normalized': '' if is_aggregation and str(first['source_device_id']) == str(aggregation.get('source_device_id')) else _observation_port_normalized(first, 'source_port_raw', 'source_port_normalized'),
                        'interface_id': aggregation.get('source_aggregation_id') if is_aggregation and str(first['source_device_id']) == str(aggregation.get('source_device_id')) else None,
                    },
                    {
                        'device_id': first['target_device_id'],
                        'hostname': first.get('target_hostname') or '',
                        'port_raw': (aggregation.get('target_aggregation_name') if is_aggregation and str(first['target_device_id']) == str(aggregation.get('target_device_id')) else first.get('target_port_raw')) or '',
                        'port_normalized': '' if is_aggregation and str(first['target_device_id']) == str(aggregation.get('target_device_id')) else _observation_port_normalized(first, 'target_port_raw', 'target_port_normalized'),
                        'interface_id': aggregation.get('target_aggregation_id') if is_aggregation and str(first['target_device_id']) == str(aggregation.get('target_device_id')) else None,
                    },
                ],
                key=lambda item: (item['device_id'], normalize_interface_name(item['port_raw']) or item['port_raw']),
            )

            # Resolve source_interface_id
            src_dev = ordered[0]['device_id']
            src_port = ordered[0]['port_normalized'] or ordered[0]['port_raw']
            src_port_norm = normalize_interface_name(src_port).lower()
            src_interface = interface_map.get((src_dev, src_port_norm))
            src_intf_id = ordered[0].get('interface_id') or (src_interface or {}).get('id')
            if not is_aggregation:
                display_name = _canonical_fallback_interface_name(
                    (src_interface or {}).get('display_name') or ordered[0]['port_raw'],
                    device_meta.get(str(src_dev), {}),
                )
                ordered[0]['port_raw'] = display_name
                ordered[0]['port_normalized'] = normalize_interface_name(display_name)
            if src_dev and src_port_norm and not src_intf_id:
                src_intf_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO interfaces (id, device_id, interface_name, admin_status, oper_status) VALUES (?, ?, ?, 'unknown', 'unknown')",
                    (src_intf_id, src_dev, ordered[0]['port_raw'] or src_port)
                )
                interface_map[(src_dev, src_port_norm)] = {
                    'id': src_intf_id,
                    'device_id': src_dev,
                    'interface_name': ordered[0]['port_raw'] or src_port,
                    'display_name': _clean_interface_display_name(ordered[0]['port_raw'] or src_port),
                    'interface_type': 'physical',
                }

            # Resolve target_interface_id
            tgt_dev = ordered[1]['device_id']
            tgt_port = ordered[1]['port_normalized'] or ordered[1]['port_raw']
            tgt_port_norm = normalize_interface_name(tgt_port).lower()
            tgt_interface = interface_map.get((tgt_dev, tgt_port_norm))
            tgt_intf_id = ordered[1].get('interface_id') or (tgt_interface or {}).get('id')
            if not is_aggregation:
                display_name = _canonical_fallback_interface_name(
                    (tgt_interface or {}).get('display_name') or ordered[1]['port_raw'],
                    device_meta.get(str(tgt_dev), {}),
                )
                ordered[1]['port_raw'] = display_name
                ordered[1]['port_normalized'] = normalize_interface_name(display_name)
            if tgt_dev and tgt_port_norm and not tgt_intf_id:
                tgt_intf_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO interfaces (id, device_id, interface_name, admin_status, oper_status) VALUES (?, ?, ?, 'unknown', 'unknown')",
                    (tgt_intf_id, tgt_dev, ordered[1]['port_raw'] or tgt_port)
                )
                interface_map[(tgt_dev, tgt_port_norm)] = {
                    'id': tgt_intf_id,
                    'device_id': tgt_dev,
                    'interface_name': ordered[1]['port_raw'] or tgt_port,
                    'display_name': _clean_interface_display_name(ordered[1]['port_raw'] or tgt_port),
                    'interface_type': 'physical',
                }

            member_rows = aggregation.get('members') or []
            metadata = {
                'protocols': protocols,
                'reverse_seen': reverse_seen,
                'match_methods': sorted({obs.get('match_method') or '' for obs in observations if obs.get('match_method')}),
            }
            if is_aggregation:
                metadata.update({
                    'link_kind': 'aggregation',
                    'source_aggregation_name': aggregation.get('source_aggregation_name') or '',
                    'target_aggregation_name': aggregation.get('target_aggregation_name') or '',
                    'aggregation_protocol': aggregation.get('aggregation_protocol') or '',
                    'member_count': int(aggregation.get('member_count') or 0),
                    'active_member_count': int(aggregation.get('active_member_count') or 0),
                    'members': member_rows,
                })

            conn.execute(
                '''
                INSERT INTO topology_links (
                    id, link_key, source_device_id, source_interface_id, source_hostname, source_port, source_port_normalized,
                    target_device_id, target_interface_id, target_hostname, target_port, target_port_normalized,
                    discovery_source, confidence, status, is_inferred, evidence_count,
                    metadata_json, created_at, updated_at, last_seen, source_site_id, target_site_id,
                    link_kind, source_aggregation_name, target_aggregation_name, aggregation_protocol,
                    member_count, active_member_count, aggregation_bandwidth_mbps, members_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    str(uuid.uuid4()),
                    link_key,
                    ordered[0]['device_id'],
                    src_intf_id,
                    ordered[0]['hostname'],
                    ordered[0]['port_raw'],
                    ordered[0]['port_normalized'],
                    ordered[1]['device_id'],
                    tgt_intf_id,
                    ordered[1]['hostname'],
                    ordered[1]['port_raw'],
                    ordered[1]['port_normalized'],
                    '+'.join(protocols),
                    confidence,
                    aggregation.get('status') if is_aggregation else 'unknown',
                    0,
                    len(observations),
                    _safe_json(metadata),
                    existing.get('created_at') or now,
                    now,
                    max(obs.get('updated_at') or now for obs in observations),
                    device_sites.get(str(ordered[0]['device_id']), ''),
                    device_sites.get(str(ordered[1]['device_id']), ''),
                    'aggregation' if is_aggregation else 'physical',
                    aggregation.get('source_aggregation_name') if is_aggregation else '',
                    aggregation.get('target_aggregation_name') if is_aggregation else '',
                    aggregation.get('aggregation_protocol') if is_aggregation else '',
                    int(aggregation.get('member_count') or 0) if is_aggregation else 0,
                    int(aggregation.get('active_member_count') or 0) if is_aggregation else 0,
                    float(aggregation.get('bandwidth_mbps') or 0) if is_aggregation else (
                        min(
                            float((src_interface or {}).get('speed') or (src_interface or {}).get('bandwidth') or 0),
                            float((tgt_interface or {}).get('speed') or (tgt_interface or {}).get('bandwidth') or 0)
                        ) / 1_000_000.0 if (src_interface and tgt_interface and ((src_interface.get('speed') or src_interface.get('bandwidth') or 0) and (tgt_interface.get('speed') or tgt_interface.get('bandwidth') or 0))) else (
                            float((src_interface or {}).get('speed') or (src_interface or {}).get('bandwidth') or (tgt_interface or {}).get('speed') or (tgt_interface or {}).get('bandwidth') or 0) / 1_000_000.0
                        )
                    ),
                    _safe_json(member_rows),
                ),
            )

        for link_key, existing in existing_by_key.items():
            if link_key in active_link_keys:
                continue
            existing_canonical_key = _build_link_key(
                str(existing.get('source_device_id') or ''),
                str(existing.get('source_port') or existing.get('source_port_normalized') or ''),
                str(existing.get('target_device_id') or ''),
                str(existing.get('target_port') or existing.get('target_port_normalized') or ''),
            )
            # A link written by an older normalization pass can have a
            # different persisted key while representing an active link.
            if existing_canonical_key in active_link_keys:
                continue
            # Do not retain historical CDP edges in the active topology. The
            # grace period applies only to LLDP observations after a successful
            # collection; failed collections never reach this rebuild path.
            if 'cdp' in str(existing.get('discovery_source') or '').lower():
                conn.execute(
                    "UPDATE topology_links SET status = 'stale', updated_at = ? WHERE id = ?",
                    (now, existing.get('id')),
                )
                continue
            last_seen = str(existing.get('last_seen') or '')
            try:
                age_seconds = (datetime.fromisoformat(now) - datetime.fromisoformat(last_seen)).total_seconds() if last_seen else TOPOLOGY_LINK_STALE_RETENTION_SECONDS + 1
            except Exception:
                age_seconds = TOPOLOGY_LINK_STALE_RETENTION_SECONDS + 1
            if age_seconds > TOPOLOGY_LINK_STALE_RETENTION_SECONDS:
                continue

            metadata = {}
            try:
                metadata = json.loads(existing.get('metadata_json') or '{}')
            except Exception:
                metadata = {}
            metadata['stale_reason'] = 'missing_from_latest_discovery'

            conn.execute(
                '''
                INSERT INTO topology_links (
                    id, link_key, source_device_id, source_interface_id, source_hostname, source_port, source_port_normalized,
                    target_device_id, target_interface_id, target_hostname, target_port, target_port_normalized,
                    discovery_source, confidence, status, is_inferred, evidence_count,
                    metadata_json, created_at, updated_at, last_seen, source_site_id, target_site_id,
                    link_kind, source_aggregation_name, target_aggregation_name, aggregation_protocol,
                    member_count, active_member_count, aggregation_bandwidth_mbps, members_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    str(existing.get('id') or uuid.uuid4()),
                    link_key,
                    existing.get('source_device_id'),
                    existing.get('source_interface_id'),
                    existing.get('source_hostname') or '',
                    existing.get('source_port') or '',
                    existing.get('source_port_normalized') or '',
                    existing.get('target_device_id'),
                    existing.get('target_interface_id'),
                    existing.get('target_hostname') or '',
                    existing.get('target_port') or '',
                    existing.get('target_port_normalized') or '',
                    existing.get('discovery_source') or 'lldp',
                    float(existing.get('confidence') or 0.0),
                    'stale',
                    int(existing.get('is_inferred') or 0),
                    int(existing.get('evidence_count') or 1),
                    _safe_json(metadata),
                    existing.get('created_at') or now,
                    now,
                    existing.get('last_seen') or existing.get('updated_at') or now,
                    existing.get('source_site_id') or device_sites.get(str(existing.get('source_device_id') or ''), ''),
                    existing.get('target_site_id') or device_sites.get(str(existing.get('target_device_id') or ''), ''),
                    existing.get('link_kind') or 'physical',
                    existing.get('source_aggregation_name') or '',
                    existing.get('target_aggregation_name') or '',
                    existing.get('aggregation_protocol') or '',
                    int(existing.get('member_count') or 0),
                    int(existing.get('active_member_count') or 0),
                    float(existing.get('aggregation_bandwidth_mbps') or 0),
                    existing.get('members_json') or '[]',
                ),
            )

        conn.commit()
        return len(active_link_keys)
    finally:
        conn.close()


def select_topology_discovery_devices(
    scope: str,
    *,
    site_id: str = '',
    device_ids: list[str] | None = None,
    allowed_device_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve a discovery scope into eligible, unique online devices.

    Scope validation lives in the service so manual API runs and future
    orchestrators cannot accidentally turn an incomplete site/device request
    into a full-network scan.
    """
    normalized_scope = str(scope or 'full').strip().lower()
    normalized_site_id = str(site_id or '').strip()
    requested_device_ids = list(dict.fromkeys(
        str(device_id or '').strip()
        for device_id in (device_ids or [])
        if str(device_id or '').strip()
    ))
    if normalized_scope not in {'full', 'site', 'devices'}:
        raise ValueError('topology_scope_invalid')
    if normalized_scope == 'site' and not normalized_site_id:
        raise ValueError('topology_site_required')
    if normalized_scope == 'devices' and not requested_device_ids:
        raise ValueError('topology_device_ids_required')
    if normalized_scope == 'full' and (normalized_site_id or requested_device_ids):
        raise ValueError('topology_full_scope_has_selectors')
    if normalized_scope == 'site' and requested_device_ids:
        raise ValueError('topology_site_scope_has_device_ids')
    if normalized_scope == 'devices' and normalized_site_id:
        raise ValueError('topology_device_scope_has_site_id')

    conn = get_db_connection()
    try:
        site_aliases, sites_by_id = _load_site_identity_maps(conn)
        canonical_site_id = _canonical_site_id(normalized_site_id, site_aliases)
        if normalized_scope == 'site' and canonical_site_id not in sites_by_id:
            raise ValueError('topology_site_not_found')

        clauses = ["d.status = 'online'", "COALESCE(d.ip_address, '') <> ''"]
        params: list[Any] = []
        if normalized_scope == 'site':
            site = sites_by_id[canonical_site_id]
            site_values = list(dict.fromkeys(
                value
                for value in (
                    canonical_site_id,
                    str(site.get('site_code') or '').strip(),
                    str(site.get('site_name') or '').strip(),
                )
                if value
            ))
            placeholders = ','.join('?' for _ in site_values)
            clauses.append(
                f"COALESCE(NULLIF(d.site_id, ''), NULLIF(pa.site_id, '')) IN ({placeholders})"
            )
            params.extend(site_values)
        elif normalized_scope == 'devices':
            placeholders = ','.join('?' for _ in requested_device_ids)
            clauses.append(f'd.id IN ({placeholders})')
            params.extend(requested_device_ids)

        allowed_filter, allowed_params = _device_id_filter('d.id', allowed_device_ids)
        if allowed_filter:
            clauses.append(allowed_filter)
            params.extend(allowed_params)
        if allowed_device_ids is not None and not allowed_device_ids:
            # Keep the discovery response shape but fail closed for an empty
            # site/tenant grant.
            clauses.append('1 = 0')

        rows = conn.execute(
            f'''
            SELECT d.id, d.hostname, d.ip_address, d.platform,
                   COALESCE(NULLIF(s.id, ''), NULLIF(d.site_id, ''), NULLIF(pa.site_id, '')) AS site_id
            FROM devices d
            LEFT JOIN physical_assets pa ON pa.id = d.asset_id
            LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
            WHERE {' AND '.join(clauses)}
            ORDER BY d.hostname, d.id
            ''',
            tuple(params),
        ).fetchall()
        devices = [dict(row) for row in rows]
        eligible_ids = [str(item['id']) for item in devices]
        eligible_id_set = set(eligible_ids)
        excluded_ids = [device_id for device_id in requested_device_ids if device_id not in eligible_id_set]
        return {
            'scope': normalized_scope,
            'site_id': canonical_site_id if normalized_scope == 'site' else '',
            'device_ids': eligible_ids,
            'devices': devices,
            'requested_device_ids': requested_device_ids,
            'excluded_device_ids': excluded_ids,
            'eligible_count': len(eligible_ids),
        }
    finally:
        conn.close()


def create_discovery_run(
    device_ids: list[str],
    requested_by: str = 'system',
    scope: str = 'full',
    *,
    site_id: str = '',
    scope_payload: dict[str, Any] | None = None,
    idempotency_key: str = '',
    max_attempts: int = DISCOVERY_DEFAULT_MAX_ATTEMPTS,
    timeout_seconds: int = DISCOVERY_DEFAULT_TIMEOUT_SECONDS,
) -> str:
    run_id = str(uuid.uuid4())
    now = _utc_now_iso()
    normalized_key = str(idempotency_key or '').strip()[:160]
    if normalized_key:
        normalized_key = hashlib.sha256(normalized_key.encode('utf-8')).hexdigest()
    conn = get_db_connection()
    try:
        if normalized_key:
            existing = conn.execute(
                'SELECT id FROM topology_discovery_runs WHERE idempotency_key = ?',
                (normalized_key,),
            ).fetchone()
            if existing:
                return str(existing['id'])
        conn.execute(
            '''
            INSERT INTO topology_discovery_runs (
                id, scope, status, requested_by, protocol_scope, started_at, total_devices,
                summary_json, site_id, scope_json, cancel_requested, idempotency_key,
                max_attempts, timeout_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                run_id, scope, 'pending', requested_by, 'lldp', now, len(device_ids),
                '{}', site_id, _safe_json(scope_payload or {'device_ids': device_ids}), 0,
                normalized_key, max(1, min(int(max_attempts or DISCOVERY_DEFAULT_MAX_ATTEMPTS), 5)),
                max(30, min(int(timeout_seconds or DISCOVERY_DEFAULT_TIMEOUT_SECONDS), 3600)),
            ),
        )

        for device_id in device_ids:
            device = conn.execute('SELECT hostname FROM devices WHERE id = ?', (device_id,)).fetchone()
            conn.execute(
                '''
                INSERT INTO topology_discovery_run_devices (
                    id, run_id, device_id, hostname, status, attempt_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (str(uuid.uuid4()), run_id, device_id, device['hostname'] if device else '', 'pending', 0),
            )

        conn.commit()
        return run_id
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        if normalized_key:
            existing = conn.execute(
                'SELECT id FROM topology_discovery_runs WHERE idempotency_key = ?',
                (normalized_key,),
            ).fetchone()
            if existing:
                return str(existing['id'])
        raise
    finally:
        conn.close()


def _update_run_device(run_id: str, device_id: str, **fields: Any):
    if not fields:
        return
    assignments = ', '.join(f'{key} = ?' for key in fields)
    values = list(fields.values()) + [run_id, device_id]
    conn = get_db_connection()
    try:
        conn.execute(
            f'UPDATE topology_discovery_run_devices SET {assignments} WHERE run_id = ? AND device_id = ?',
            values,
        )
        conn.commit()
    finally:
        conn.close()


def _update_run(run_id: str, **fields: Any):
    if not fields:
        return
    assignments = ', '.join(f'{key} = ?' for key in fields)
    values = list(fields.values()) + [run_id]
    conn = get_db_connection()
    try:
        conn.execute(f'UPDATE topology_discovery_runs SET {assignments} WHERE id = ?', values)
        conn.commit()
    finally:
        conn.close()


async def discover_device_neighbors(
    device_id: str,
    run_id: str | None = None,
    *,
    rebuild_links: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        device = _get_device(device_id)
        if not device:
            raise RuntimeError('device_not_found')
        if device.get('status') == 'offline':
            raise RuntimeError('device_is_offline')
        if not device.get('ip_address') or not device.get('username') or not device.get('password'):
            raise RuntimeError('device_credentials_incomplete')

        platform_action_session = None
        if device.get('platform_profile_id'):
            from services.platform_registry_service import PlatformActionSession

            platform_action_session = PlatformActionSession(
                str(device_id),
                {
                    'id': f"topology:{device.get('id') or 'unknown'}",
                    'username': 'topology-collector',
                    'role': 'Operator',
                    'tenant_id': device.get('tenant_id') or '',
                },
            )
            # Opening the driver is blocking; keep one session per device but
            # do not serialize login handshakes across the discovery batch.
            await asyncio.to_thread(platform_action_session.__enter__)
        try:
            if platform_action_session is None:
                # Keep the legacy no-profile call shape for integrations and
                # tests that provide a one-argument observation collector.
                observations, method = await _collect_device_observations(device)
            else:
                observations, method = await _collect_device_observations(
                    device,
                    platform_action_session=platform_action_session,
                )
            aggregation_summary = await asyncio.to_thread(
                _sync_aggregation_inventory,
                device,
                platform_action_session,
            )
            from services.topology_protocol_service import collect_protocol_evidence

            protocol_summary = await asyncio.to_thread(
                collect_protocol_evidence,
                device,
                run_id=run_id,
                platform_action_session=platform_action_session,
            )
        finally:
            if platform_action_session is not None:
                await asyncio.to_thread(platform_action_session.__exit__, None, None, None)
        if 'protocol_summary' not in locals():
            protocol_summary = {
                'success': False,
                'observations_count': 0,
                'protocols': [],
                'error': 'protocol_collection_not_started',
            }
        observations = _deduplicate_observations(observations)
        match_summary = _replace_device_observations(device, observations, run_id)
        total_links = rebuild_links_from_observations() if rebuild_links else None
        collection_status = 'success' if observations else 'no_neighbors'
        record_collection_result(
            device_id,
            'topology_lldp',
            status=collection_status,
            transport='ssh',
            source='lldp_playbook',
            duration_ms=(time.perf_counter() - started) * 1000,
            coverage_total=len(observations),
            coverage_supported=match_summary['matched'],
            metadata={
                'method': method,
                'ambiguous': match_summary['ambiguous'],
                'unmatched': match_summary['unmatched'],
                'aggregation': aggregation_summary,
                'protocols': protocol_summary,
                'run_id': run_id,
                'protocol': 'lldp',
                'collection_status': collection_status,
            },
        )
        return {
            'device_id': device_id,
            'hostname': device.get('hostname') or '',
            'discovery_method': method,
            'observations_count': len(observations),
            'matched_links_count': match_summary['matched'],
            'ambiguous_count': match_summary['ambiguous'],
            'unmatched_count': match_summary['unmatched'],
            'total_links': total_links,
            'protocols': sorted(
                {'lldp', *{item.get('protocol') or 'lldp' for item in observations}, *protocol_summary.get('protocols', [])}
            ),
            'protocol_observations_count': int(protocol_summary.get('observations_count') or 0),
            'protocol_collection': protocol_summary,
            'aggregation': aggregation_summary,
        }
    except Exception as exc:
        record_collection_result(
            device_id,
            'topology_lldp',
            status='failed',
            transport='ssh',
            source='lldp_playbook',
            duration_ms=(time.perf_counter() - started) * 1000,
            error_code=topology_error_code(exc),
            error_message=str(exc)[:500],
            metadata={'run_id': run_id},
        )
        raise


async def discover_lldp_neighbors(device_id: str):
    try:
        return await discover_device_neighbors(device_id, None, rebuild_links=False)
    except RuntimeError as exc:
        # 凭据不完整 / 设备不存在等属于预期情况（如新增设备未配凭据），
        # 周期任务中静默跳过即可，避免 "Task exception was never retrieved" 日志。
        logger.debug('Periodic LLDP discovery skipped for device %s: %s', device_id, exc)
        return None


def _is_run_cancel_requested(run_id: str) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT cancel_requested FROM topology_discovery_runs WHERE id = ?',
            (run_id,),
        ).fetchone()
        return bool(row and int(row['cancel_requested'] or 0))
    finally:
        conn.close()


def _claim_discovery_run(run_id: str, worker_id: str) -> bool:
    """Claim a pending or expired run atomically for cross-process workers."""
    now = datetime.now(timezone.utc)
    now_iso = now.replace(microsecond=0).isoformat()
    expires_iso = (now + timedelta(seconds=DISCOVERY_LEASE_SECONDS)).replace(microsecond=0).isoformat()
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            '''
            UPDATE topology_discovery_runs
            SET status = 'running', lease_owner = ?, lease_expires_at = ?, heartbeat_at = ?,
                attempt_count = COALESCE(attempt_count, 0) + 1,
                started_at = COALESCE(started_at, ?)
            WHERE id = ?
              AND COALESCE(attempt_count, 0) < COALESCE(max_attempts, ?)
              AND (
                status = 'pending'
                OR (status = 'running' AND (lease_expires_at IS NULL OR lease_expires_at < ?))
              )
            ''',
            (worker_id, expires_iso, now_iso, now_iso, run_id, DISCOVERY_DEFAULT_MAX_ATTEMPTS, now_iso),
        )
        conn.commit()
        return int(getattr(cursor, 'rowcount', 0) or 0) > 0
    finally:
        conn.close()


def _renew_discovery_lease(run_id: str, worker_id: str) -> bool:
    now = datetime.now(timezone.utc)
    now_iso = now.replace(microsecond=0).isoformat()
    expires_iso = (now + timedelta(seconds=DISCOVERY_LEASE_SECONDS)).replace(microsecond=0).isoformat()
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            '''
            UPDATE topology_discovery_runs
            SET lease_expires_at = ?, heartbeat_at = ?
            WHERE id = ? AND status = 'running' AND lease_owner = ?
            ''',
            (expires_iso, now_iso, run_id, worker_id),
        )
        conn.commit()
        return int(getattr(cursor, 'rowcount', 0) or 0) > 0
    finally:
        conn.close()


def _get_discovery_run_settings(run_id: str) -> tuple[int, int]:
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT timeout_seconds, max_attempts FROM topology_discovery_runs WHERE id = ?',
            (run_id,),
        ).fetchone()
        if not row:
            return DISCOVERY_DEFAULT_TIMEOUT_SECONDS, DISCOVERY_DEFAULT_MAX_ATTEMPTS
        return (
            max(30, int(row['timeout_seconds'] or DISCOVERY_DEFAULT_TIMEOUT_SECONDS)),
            max(1, min(int(row['max_attempts'] or DISCOVERY_DEFAULT_MAX_ATTEMPTS), 5)),
        )
    finally:
        conn.close()


def request_cancel_discovery_run(run_id: str) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT status FROM topology_discovery_runs WHERE id = ?', (run_id,)).fetchone()
        if not row:
            return False
        if str(row['status']) in {'completed', 'partial', 'failed', 'cancelled'}:
            return True
        conn.execute(
            'UPDATE topology_discovery_runs SET cancel_requested = 1 WHERE id = ?',
            (run_id,),
        )
        conn.commit()
        return True
    finally:
        conn.close()


async def _execute_discovery_device(
    run_id: str,
    device_id: str,
    timeout_seconds: int,
    max_attempts: int,
) -> dict[str, Any]:
    """Run one device's discovery lifecycle and return its run-level result."""
    for attempt in range(1, max_attempts + 1):
        _update_run_device(
            run_id,
            device_id,
            status='running',
            started_at=_utc_now_iso(),
            last_attempt_at=_utc_now_iso(),
            attempt_count=attempt,
        )
        try:
            result = await asyncio.wait_for(
                discover_device_neighbors(device_id, run_id, rebuild_links=False),
                timeout=timeout_seconds,
            )
            _update_run_device(
                run_id,
                device_id,
                status='success',
                discovery_method=result['discovery_method'],
                completed_at=_utc_now_iso(),
                observations_count=result['observations_count'],
                matched_links_count=result['matched_links_count'],
                error_code='',
                error_message='',
            )
            return {
                'device_id': device_id,
                'success': True,
                'observations_count': int(result['observations_count']),
            }
        except Exception as exc:  # noqa: BLE001
            error_code = topology_error_code(exc)
            logger.warning(
                'Topology discovery failed for device %s in run %s (attempt %s/%s): %s',
                device_id, run_id, attempt, max_attempts, exc,
            )
            if _is_run_cancel_requested(run_id):
                _update_run_device(
                    run_id,
                    device_id,
                    status='cancelled',
                    completed_at=_utc_now_iso(),
                    error_code='discovery_cancelled',
                    error_message='Discovery cancelled while this device was being processed',
                )
                return {'device_id': device_id, 'cancelled': True}
            if _should_retry_discovery(error_code, attempt, max_attempts):
                logger.info(
                    'Retrying transient topology discovery failure for device %s in run %s',
                    device_id,
                )
                continue
            _update_run_device(
                run_id,
                device_id,
                status='failed',
                completed_at=_utc_now_iso(),
                error_code=error_code,
                error_message=str(exc)[:500],
            )
            return {
                'device_id': device_id,
                'success': False,
                'error_code': error_code,
                'error_message': str(exc)[:500],
            }

    # The loop always returns after the final attempt; keep a defensive result
    # so a future retry-policy change cannot leave a device in ``running``.
    error_code = 'topology_discovery_failed'
    _update_run_device(
        run_id,
        device_id,
        status='failed',
        completed_at=_utc_now_iso(),
        error_code=error_code,
        error_message='Topology discovery exhausted its retry policy',
    )
    return {
        'device_id': device_id,
        'success': False,
        'error_code': error_code,
        'error_message': 'Topology discovery exhausted its retry policy',
    }


async def _discovery_lease_heartbeat(
    run_id: str,
    worker_id: str,
    stop_event: asyncio.Event,
    lease_lost: asyncio.Event,
) -> None:
    """Keep a long-running parallel batch from losing its run lease."""
    interval = max(5.0, min(30.0, DISCOVERY_LEASE_SECONDS / 3))
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            try:
                renewed = await asyncio.to_thread(_renew_discovery_lease, run_id, worker_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning('Failed to renew topology discovery lease %s: %s', run_id, exc)
                lease_lost.set()
                return
            if not renewed:
                logger.warning('Topology discovery lease lost for run %s', run_id)
                lease_lost.set()
                return


async def execute_discovery_run(run_id: str, device_ids: list[str]):
    worker_id = f'{os.getpid()}:{uuid.uuid4()}'
    if not _claim_discovery_run(run_id, worker_id):
        logger.info('Discovery run %s was already claimed or exhausted', run_id)
        return

    timeout_seconds, max_attempts = _get_discovery_run_settings(run_id)
    success_devices = 0
    failed_devices = 0
    total_observations = 0
    cancelled = False
    heartbeat_stop = asyncio.Event()
    lease_lost = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _discovery_lease_heartbeat(run_id, worker_id, heartbeat_stop, lease_lost)
    )
    try:
        concurrency = min(DISCOVERY_DEVICE_CONCURRENCY, max(1, len(device_ids)))
        for batch_start in range(0, len(device_ids), concurrency):
            if lease_lost.is_set() or not _renew_discovery_lease(run_id, worker_id):
                _update_run(run_id, status='failed', last_error_code='discovery_lease_lost')
                return
            if _is_run_cancel_requested(run_id):
                cancelled = True
                pending_device_ids = device_ids[batch_start:]
                for pending_device_id in pending_device_ids:
                    _update_run_device(
                        run_id,
                        pending_device_id,
                        status='cancelled',
                        completed_at=_utc_now_iso(),
                        error_code='discovery_cancelled',
                        error_message='Discovery cancelled before this device was processed',
                    )
                break

            batch_device_ids = device_ids[batch_start:batch_start + concurrency]
            batch_results = await asyncio.gather(
                *(
                    _execute_discovery_device(
                        run_id,
                        device_id,
                        timeout_seconds,
                        max_attempts,
                    )
                    for device_id in batch_device_ids
                ),
                return_exceptions=True,
            )
            for device_id, result in zip(batch_device_ids, batch_results):
                if isinstance(result, BaseException):
                    error_message = str(result)[:500]
                    error_code = topology_error_code(
                        result if isinstance(result, Exception) else RuntimeError(error_message)
                    )
                    logger.error(
                        'Topology discovery worker crashed for device %s in run %s: %s',
                        device_id,
                        run_id,
                        result,
                    )
                    failed_devices += 1
                    _update_run_device(
                        run_id,
                        device_id,
                        status='failed',
                        completed_at=_utc_now_iso(),
                        error_code=error_code,
                        error_message=error_message,
                    )
                    continue
                if result.get('cancelled'):
                    cancelled = True
                elif result.get('success'):
                    success_devices += 1
                    total_observations += int(result.get('observations_count') or 0)
                else:
                    failed_devices += 1

            _update_run(
                run_id,
                success_devices=success_devices,
                failed_devices=failed_devices,
                total_observations=total_observations,
            )
            if lease_lost.is_set():
                _update_run(run_id, status='failed', last_error_code='discovery_lease_lost')
                return
            if cancelled:
                pending_device_ids = device_ids[batch_start + len(batch_device_ids):]
                for pending_device_id in pending_device_ids:
                    _update_run_device(
                        run_id,
                        pending_device_id,
                        status='cancelled',
                        completed_at=_utc_now_iso(),
                        error_code='discovery_cancelled',
                        error_message='Discovery cancelled before this device was processed',
                    )
                break

        if not cancelled and _is_run_cancel_requested(run_id):
            cancelled = True
        if lease_lost.is_set():
            _update_run(run_id, status='failed', last_error_code='discovery_lease_lost')
            return

        total_links = rebuild_links_from_observations()
        final_status = (
            'cancelled'
            if cancelled
            else ('completed' if failed_devices == 0 else ('partial' if success_devices > 0 else 'failed'))
        )
        summary = {
            'total_devices': len(device_ids),
            'processed_devices': success_devices + failed_devices,
            'success_devices': success_devices,
            'failed_devices': failed_devices,
            'total_observations': total_observations,
            'total_links': total_links,
            'cancelled': cancelled,
            'max_attempts': max_attempts,
            'timeout_seconds': timeout_seconds,
            'device_concurrency': concurrency,
        }
        _update_run(
            run_id,
            status=final_status,
            completed_at=_utc_now_iso(),
            success_devices=success_devices,
            failed_devices=failed_devices,
            total_observations=total_observations,
            total_links=total_links,
            summary_json=_safe_json(summary),
            last_error_code='',
            lease_owner='',
            lease_expires_at=None,
            heartbeat_at=_utc_now_iso(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception('Discovery run %s crashed', run_id)
        _update_run(
            run_id,
            status='failed',
            completed_at=_utc_now_iso(),
            last_error_code=topology_error_code(exc),
            lease_owner='',
            lease_expires_at=None,
            heartbeat_at=_utc_now_iso(),
        )
    finally:
        heartbeat_stop.set()
        try:
            await heartbeat_task
        except Exception:  # noqa: BLE001
            logger.debug('Topology discovery lease heartbeat stopped with an error', exc_info=True)


def get_current_links(
    limit: int | None = 5000,
    *,
    site_id: str | None = None,
    device_ids: list[str] | None = None,
    include_stale: bool = True,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if site_id:
        clauses.append("(COALESCE(NULLIF(sd.site_id, ''), NULLIF(l.source_site_id, ''), '') = ? OR COALESCE(NULLIF(td.site_id, ''), NULLIF(l.target_site_id, ''), '') = ?)")
        params.extend([site_id, site_id])
    if device_ids is not None:
        normalized_device_ids = sorted({
            str(device_id).strip()
            for device_id in device_ids
            if device_id is not None and str(device_id).strip()
        })
        if not normalized_device_ids:
            return []
        placeholders = ','.join('?' for _ in normalized_device_ids)
        clauses.append(f"sd.id IN ({placeholders}) AND td.id IN ({placeholders})")
        params.extend(normalized_device_ids)
        params.extend(normalized_device_ids)
    if not include_stale:
        clauses.append("COALESCE(l.status, 'unknown') <> 'stale'")
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(seconds=TOPOLOGY_LINK_TTL_SECONDS)).replace(microsecond=0).isoformat()
    if not include_stale:
        clauses.append("COALESCE(l.last_seen, '') >= ?")
        params.append(cutoff_iso)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    limit_sql = ''
    if limit and limit > 0:
        limit_sql = 'LIMIT ?'
        params.append(int(limit))

    conn = get_db_connection()
    try:
        rows = conn.execute(
            f'''
            SELECT l.*,
                   sd.hostname AS source_hostname_resolved,
                   td.hostname AS target_hostname_resolved,
                   COALESCE(NULLIF(sd.site_id, ''), NULLIF(l.source_site_id, ''), '') AS source_site_id_resolved,
                   COALESCE(NULLIF(td.site_id, ''), NULLIF(l.target_site_id, ''), '') AS target_site_id_resolved,
                   COALESCE(ss.site_name, sd.site, '') AS source_site_name,
                   COALESCE(ts.site_name, td.site, '') AS target_site_name
            FROM topology_links l
            JOIN devices sd ON l.source_device_id = sd.id
            JOIN devices td ON l.target_device_id = td.id
            LEFT JOIN sites ss ON ss.id = COALESCE(NULLIF(sd.site_id, ''), NULLIF(l.source_site_id, ''))
            LEFT JOIN sites ts ON ts.id = COALESCE(NULLIF(td.site_id, ''), NULLIF(l.target_site_id, ''))
            {where_sql}
            ORDER BY source_site_name, l.source_hostname, l.source_port_normalized,
                     target_site_name, l.target_hostname, l.target_port_normalized
            {limit_sql}
            ''',
            tuple(params),
        ).fetchall()
        now = datetime.now(timezone.utc)
        aggregation_map = _load_interface_aggregation_map(conn)
        result = []
        for row in rows:
            item = dict(row)
            try:
                item['members'] = json.loads(item.get('members_json') or '[]')
            except (TypeError, ValueError):
                item['members'] = []
            item['link_kind'] = str(item.get('link_kind') or 'physical')
            source_key = (
                str(item.get('source_device_id') or ''),
                normalize_interface_name(item.get('source_port_normalized') or item.get('source_port') or '').lower(),
            )
            target_key = (
                str(item.get('target_device_id') or ''),
                normalize_interface_name(item.get('target_port_normalized') or item.get('target_port') or '').lower(),
            )
            source_aggregation = aggregation_map.get(source_key) or {}
            target_aggregation = aggregation_map.get(target_key) or {}
            if not source_aggregation and item.get('source_interface_id'):
                parent_row = conn.execute(
                    '''
                    SELECT parent.interface_name
                    FROM interfaces member
                    JOIN interfaces parent ON parent.id = member.parent_interface_id
                    WHERE member.id = ?
                    ''',
                    (item.get('source_interface_id'),),
                ).fetchone()
                if parent_row:
                    source_aggregation = {'aggregation_name': parent_row['interface_name']}
            if not target_aggregation and item.get('target_interface_id'):
                parent_row = conn.execute(
                    '''
                    SELECT parent.interface_name
                    FROM interfaces member
                    JOIN interfaces parent ON parent.id = member.parent_interface_id
                    WHERE member.id = ?
                    ''',
                    (item.get('target_interface_id'),),
                ).fetchone()
                if parent_row:
                    target_aggregation = {'aggregation_name': parent_row['interface_name']}
            if source_aggregation:
                item['source_aggregation_name'] = item.get('source_aggregation_name') or source_aggregation.get('aggregation_name') or ''
            if target_aggregation:
                item['target_aggregation_name'] = item.get('target_aggregation_name') or target_aggregation.get('aggregation_name') or ''
            effective_state, stale_reason = _link_operational_state(item, now)
            item['operational_state'] = effective_state
            item['stale_reason'] = stale_reason
            item['ttl_seconds'] = TOPOLOGY_LINK_TTL_SECONDS
            result.append(item)
        # Keep the database untouched during rolling upgrades.  If the
        # legacy interface inventory still has logical aggregation rows but
        # no parent bindings, synthesize the aggregation contract only for
        # this read response so the canvas can render one LAG edge and retain
        # every physical member for hover details.
        return _synthesise_runtime_aggregation_links(result, conn)
    finally:
        conn.close()


def _route_table_graph_observations(conn: Any, current_device_ids: set[str]) -> list[dict[str, Any]]:
    """Convert route next-hop facts into non-physical graph evidence.

    A route learned through OSPF/BGP is not proof of a cable-level adjacency,
    so these observations are deliberately classified as ``LOGICAL``.  The
    physical LLDP/CDP read model is not involved here.
    """
    try:
        rows = conn.execute(
            """
            SELECT rt.device_id, rt.next_hop, rt.outgoing_interface,
                   rt.protocol, rt.destination, rt.vrf_name, rt.metric,
                   rt.preference, rt.last_updated,
                   peer.id AS peer_device_id
            FROM route_table rt
            LEFT JOIN devices peer
              ON peer.ip_address = rt.next_hop
              OR LOWER(peer.hostname) = LOWER(rt.next_hop)
              OR EXISTS (
                  SELECT 1 FROM interfaces peer_intf
                  WHERE peer_intf.device_id = peer.id
                    AND (peer_intf.ip_address = rt.next_hop
                         OR peer_intf.primary_ip = rt.next_hop)
              )
              OR EXISTS (
                  SELECT 1 FROM ip_inventory peer_ip
                  WHERE peer_ip.device_id = peer.id
                    AND peer_ip.ip = rt.next_hop
              )
            WHERE TRIM(COALESCE(rt.next_hop, '')) NOT IN ('', '0.0.0.0', '::')
              AND COALESCE(rt.active, 1) = 1
              AND LOWER(COALESCE(rt.protocol, '')) NOT IN
                  ('connected', 'local', 'direct', 'c')
            """
        ).fetchall()
    except Exception:
        logger.debug('Route-table graph projection skipped', exc_info=True)
        return []

    protocol_aliases = {
        'o': 'ospf',
        'b': 'bgp',
        'ebgp': 'bgp',
        'ibgp': 'bgp',
        'd': 'eigrp',
        'i': 'isis',
        'r': 'rip',
    }
    observations: list[dict[str, Any]] = []
    for row in rows:
        source_device_id = str(row['device_id'] or '').strip()
        next_hop = str(row['next_hop'] or '').strip()
        if source_device_id not in current_device_ids or not next_hop:
            continue
        protocol_raw = str(row['protocol'] or 'routing').strip().lower()
        protocol = protocol_aliases.get(protocol_raw, protocol_raw or 'routing')
        target_device_id = str(row['peer_device_id'] or '').strip()
        if target_device_id not in current_device_ids:
            target_device_id = ''
        target = target_device_id or next_hop
        if target == source_device_id:
            continue
        observations.append({
            'source_device_id': source_device_id,
            'target_device_id': target,
            'target_ip': next_hop,
            'source_interface': row['outgoing_interface'] or '',
            'target_interface': '',
            'source_type': protocol,
            'protocol': protocol,
            'relation_type': 'LOGICAL',
            'semantic_relation': 'ROUTE_NEXT_HOP',
            'direction': 'directed',
            'confidence': 0.55,
            'observed_at': row['last_updated'] or datetime.now(timezone.utc).isoformat(),
            'metadata': {
                'category': 'routing_table',
                'route_protocol': protocol,
                'destination': row['destination'] or '',
                'vrf_name': row['vrf_name'] or 'default',
                'metric': row['metric'],
                'preference': row['preference'],
                'next_hop': next_hop,
            },
        })
    return observations


def _sync_evidence_graph_from_observations() -> None:
    """Project safe discovery metadata into the evidence graph after rebuild.

    ``topology_links`` remains the backwards-compatible physical-link read
    model. The graph model receives only normalized endpoint/protocol/confidence
    metadata; raw parser payloads, neighbor strings and addresses stay in the
    restricted discovery evidence table and are never copied to graph edges.
    """
    try:
        from services.topology_graph_service import build_graph, persist_graph

        with get_db_connection() as conn:
            device_rows = conn.execute(
                """
                SELECT id, hostname, ip_address, site_id, role, device_category,
                       function, zone, status
                FROM devices
                """
            ).fetchall()
            current_device_ids = {str(row['id']) for row in device_rows}
            nodes = [
                {
                    'id': f"device:{row['id']}",
                    'canonical_key': f"device:{row['id']}",
                    'device_id': str(row['id']),
                    'hostname': str(row['hostname'] or row['id']),
                    'ip_address': row['ip_address'],
                    'site_id': row['site_id'],
                    'role': row['role'],
                    'function': row['function'] or row['device_category'],
                    'zone': row['zone'] or 'Unknown',
                    'status': 'active' if str(row['status'] or '').lower() != 'decommissioned' else 'inactive',
                }
                for row in device_rows
            ]
            observation_rows = conn.execute(
                """
                SELECT source_device_id, target_device_id, source_port_normalized,
                       target_port_normalized, protocol, confidence, collected_at,
                       match_status, is_active, neighbor_name_normalized,
                       neighbor_ip_address
                FROM topology_observations
                WHERE COALESCE(is_active, 1) = 1
                """
            ).fetchall()
            observations = []
            for row in observation_rows:
                source_device_id = str(row['source_device_id'] or '').strip()
                target_device_id = str(row['target_device_id'] or '').strip()
                if source_device_id not in current_device_ids:
                    continue
                if target_device_id and target_device_id not in current_device_ids:
                    continue
                target = row['target_device_id'] or row['neighbor_ip_address'] or row['neighbor_name_normalized']
                if not target:
                    continue
                observations.append({
                    'source_device_id': str(row['source_device_id']),
                    'target_device_id': str(target),
                    'target_ip': row['neighbor_ip_address'] or '',
                    'source_interface': row['source_port_normalized'],
                    'target_interface': row['target_port_normalized'],
                    'source_type': str(row['protocol'] or 'lldp').lower(),
                    'protocol': str(row['protocol'] or 'lldp').lower(),
                    'confidence': float(row['confidence'] or 0),
                    'observed_at': row['collected_at'],
                    'metadata': {
                        'match_status': row['match_status'] or 'unmatched',
                        'target_identity': row['neighbor_name_normalized'] or '',
                    },
                })
            # Protocol observations are normalized facts, not topology_links.
            # Keep unresolved identities so the graph exposes formal UNKNOWN
            # nodes instead of guessing a device match.
            try:
                protocol_rows = conn.execute(
                    """
                    SELECT source_device_id, target_device_id, target_identity,
                           target_ip, source_interface, target_interface,
                           protocol, relation_type, direction, observation_json,
                           confidence, last_seen
                    FROM topology_protocol_observations
                    WHERE is_active = 1
                    """
                ).fetchall()
            except Exception:
                protocol_rows = []
            for row in protocol_rows:
                source_device_id = str(row['source_device_id'] or '').strip()
                target_device_id = str(row['target_device_id'] or '').strip()
                if source_device_id not in current_device_ids:
                    continue
                if target_device_id and target_device_id not in current_device_ids:
                    continue
                observation = {}
                try:
                    observation = json.loads(row['observation_json'] or '{}')
                except (TypeError, ValueError):
                    observation = {}
                metadata = dict(observation.get('metadata') or {})
                metadata['semantic_relation'] = observation.get('semantic_relation') or ''
                target = row['target_device_id'] or row['target_identity'] or row['target_ip']
                if not target:
                    continue
                observations.append({
                    'source_device_id': str(row['source_device_id']),
                    'target_device_id': str(target),
                    'target_ip': row['target_ip'] or '',
                    'source_interface': row['source_interface'],
                    'target_interface': row['target_interface'],
                    'source_type': str(row['protocol'] or 'unknown').lower(),
                    'protocol': str(row['protocol'] or 'unknown').lower(),
                    'relation_type': row['relation_type'],
                    'direction': row['direction'],
                    'semantic_relation': observation.get('semantic_relation') or '',
                    'confidence': float(row['confidence'] or 0),
                    'observed_at': row['last_seen'],
                    'metadata': metadata,
                })
            # Routing neighbors are collected by the operational inventory
            # job into ``routing_neighbors``.  They used to stop at that
            # table, so the topology graph never received the OSPF/ISIS/BGP
            # adjacency even though the routing page showed it.  Project the
            # normalized rows into the same evidence stream used by the
            # protocol collector.  Resolve the peer by IP/hostname only;
            # never guess a device from a router-id alone.
            try:
                routing_rows = conn.execute(
                    """
                    SELECT rn.device_id, rn.protocol, rn.neighbor_id, rn.neighbor_ip,
                           rn.local_interface, rn.state, rn.area_id, rn.last_updated,
                           peer.id AS peer_device_id
                    FROM routing_neighbors rn
                    LEFT JOIN devices peer
                      ON peer.ip_address = rn.neighbor_ip
                      OR LOWER(peer.hostname) = LOWER(rn.neighbor_id)
                      OR EXISTS (
                          SELECT 1 FROM interfaces peer_intf
                          WHERE peer_intf.device_id = peer.id
                            AND (peer_intf.ip_address = rn.neighbor_ip
                                 OR peer_intf.primary_ip = rn.neighbor_ip)
                      )
                      OR EXISTS (
                          SELECT 1 FROM ip_inventory peer_ip
                          WHERE peer_ip.device_id = peer.id
                            AND peer_ip.ip = rn.neighbor_ip
                      )
                    WHERE LOWER(COALESCE(rn.protocol, '')) IN
                          ('ospf', 'isis', 'eigrp', 'rip', 'bgp')
                    """
                ).fetchall()
            except Exception:
                routing_rows = []
            for row in routing_rows:
                source_device_id = str(row['device_id'] or '').strip()
                target_device_id = str(row['peer_device_id'] or '').strip()
                if source_device_id not in current_device_ids:
                    continue
                if target_device_id not in current_device_ids:
                    target_device_id = ''
                target = target_device_id or str(row['neighbor_id'] or row['neighbor_ip'] or '').strip()
                if not target:
                    continue
                protocol = str(row['protocol'] or 'routing').lower()
                observations.append({
                    'source_device_id': source_device_id,
                    'target_device_id': target,
                    'target_ip': row['neighbor_ip'] or '',
                    'source_interface': row['local_interface'] or '',
                    'target_interface': '',
                    'source_type': protocol,
                    'protocol': protocol,
                    'relation_type': 'L3_NEIGHBOR',
                    'semantic_relation': 'L3_NEIGHBOR',
                    'confidence': 0.9 if str(row['state'] or '').lower() in {'full', 'up'} else 0.6,
                    'observed_at': row['last_updated'],
                    'metadata': {
                        'area_id': row['area_id'] or '',
                        'state': row['state'] or '',
                        'evidence_scope': 'routing_neighbor',
                        'unresolved_target': not bool(target_device_id),
                    },
                })
            # Route-table facts are weaker than a directly observed protocol
            # neighbor, but they are still valid logical next-hop evidence.
            # This keeps the L3/logical views useful when a protocol-specific
            # neighbor collector has not produced a row yet, without ever
            # promoting the fact into a PHYSICAL edge.
            observations.extend(_route_table_graph_observations(conn, current_device_ids))
        graph = build_graph(nodes, observations, tenant_id='tenant-default')
        persist_graph(graph)
    except Exception:
        # The graph migration is additive and may not yet exist on a rolling
        # upgrade. Physical topology rebuild remains authoritative until the
        # next startup applies m0105.
        logger.debug('Evidence graph projection skipped', exc_info=True)


def get_topology_node_metadata(
    site_id: str | None = None,
    *,
    device_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return evidence-derived node rank/layout metadata for the legacy link API.

    The canvas still consumes ``/topology/links`` for backwards compatibility,
    while the evidence graph is persisted in ``topology_nodes``. Keeping this
    small read model on the link response lets existing clients receive the
    graph rank without rebuilding their device inventory contract. Missing
    migration tables are treated as an empty metadata set so older deployments
    continue to render physical LLDP links during upgrade.
    """
    conn = get_db_connection()
    try:
        clauses = [
            "n.status = 'active'",
            "n.device_id IS NOT NULL",
            "n.device_id <> ''",
            "EXISTS (SELECT 1 FROM devices d WHERE d.id = n.device_id)",
        ]
        params: list[Any] = []
        if site_id:
            clauses.append("(n.site_id = ? OR n.node_type = 'SITE')")
            params.append(site_id)
        device_filter, device_params = _device_id_filter('n.device_id', device_ids)
        if device_filter:
            clauses.append(device_filter)
            params.extend(device_params)
        rows = conn.execute(
            """
            SELECT n.device_id, n.rank, n.layout_override_json, n.role_identity, n.node_type
            FROM topology_nodes n
            WHERE """ + " AND ".join(clauses),
            tuple(params),
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            device_id = str(item.get('device_id') or '').strip()
            if not device_id:
                continue
            try:
                layout = json.loads(item.get('layout_override_json') or '{}')
            except (TypeError, ValueError):
                layout = {}
            result[device_id] = {
                'topology_rank': max(0, int(item.get('rank') or 0)),
                'role_identity': str(item.get('role_identity') or 'UNKNOWN'),
                'topology_node_type': str(item.get('node_type') or 'DEVICE'),
                'layout_override': layout if isinstance(layout, dict) else {},
            }
        return result
    except Exception:
        # The migration is applied during startup, but the link read path must
        # remain available while an older installation is being upgraded.
        return {}
    finally:
        conn.close()


def get_unmanaged_neighbors(
    site_id: str | None = None,
    *,
    source_device_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Aggregate topology observations where the neighbor was not matched to any managed device.

    Returns a dict with:
      - unmanaged_nodes: list of pseudo-device dicts for each unique unmanaged neighbor
      - unmanaged_links: list of link dicts connecting managed source → unmanaged neighbor
    """
    conn = get_db_connection()
    try:
        if source_device_ids is not None and not source_device_ids:
            return {'unmanaged_nodes': [], 'unmanaged_links': []}
        clauses = [
            'o.target_device_id IS NULL',
            "COALESCE(o.neighbor_name_raw, '') <> ''",
        ]
        params: list[Any] = []
        if site_id:
            clauses.append(
                "COALESCE(NULLIF(d.site_id, ''), NULLIF(o.source_site_id, ''), '') = ?"
            )
            params.append(site_id)
        source_filter, source_params = _device_id_filter('o.source_device_id', source_device_ids)
        if source_filter:
            clauses.append(source_filter)
            params.extend(source_params)
        rows = conn.execute(
            f'''
            SELECT o.source_device_id, o.source_hostname, o.source_port_raw, o.source_port_normalized,
                   o.neighbor_name_raw, o.neighbor_name_normalized, o.neighbor_ip_address,
                   o.target_port_raw, o.target_port_normalized, o.protocol, o.confidence,
                   o.collected_at, o.match_status, o.match_candidates_json,
                   COALESCE(NULLIF(d.site_id, ''), NULLIF(o.source_site_id, ''), '') AS source_site_id,
                   COALESCE(s.site_name, d.site, '') AS source_site_name
            FROM topology_observations o
            JOIN devices d ON d.id = o.source_device_id
            LEFT JOIN sites s ON s.id = COALESCE(NULLIF(d.site_id, ''), NULLIF(o.source_site_id, ''))
            WHERE {' AND '.join(clauses)}
            ORDER BY source_site_name, o.source_hostname, o.neighbor_name_raw
            ''',
            tuple(params),
        ).fetchall()

        # Group by unique unmanaged neighbor identity (normalized name + ip)
        neighbor_groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            obs = dict(row)
            # Build a stable ID for this unmanaged neighbor
            norm_name = obs.get('neighbor_name_normalized') or ''
            ip = obs.get('neighbor_ip_address') or ''
            # Prefer IP-based key for uniqueness, fall back to normalized name
            source_site_id = obs.get('source_site_id') or 'unassigned'
            identity = ip or norm_name
            neighbor_key = f'unmanaged::{source_site_id}::{identity}'
            neighbor_groups.setdefault(neighbor_key, []).append(obs)

        unmanaged_nodes: list[dict[str, Any]] = []
        unmanaged_links: list[dict[str, Any]] = []

        for neighbor_key, observations in neighbor_groups.items():
            first = observations[0]
            display_name = first.get('neighbor_name_raw') or first.get('neighbor_name_normalized') or 'Unknown'
            ip_address = first.get('neighbor_ip_address') or ''
            protocols = sorted({obs.get('protocol') or 'lldp' for obs in observations})
            max_confidence = max(float(obs.get('confidence') or 0.0) for obs in observations)

            # Pseudo-device node
            unmanaged_nodes.append({
                'id': neighbor_key,
                'hostname': display_name,
                'ip_address': ip_address,
                'platform': '',
                'status': 'unmanaged',
                'role': '',
                'site': first.get('source_site_name') or 'Unassigned',
                'site_id': first.get('source_site_id') or '',
                'is_unmanaged': True,
                'observation_count': len(observations),
                'protocols': protocols,
                'connected_device_ids': sorted({obs['source_device_id'] for obs in observations}),
            })

            # Create a link for each unique source_device + source_port combination
            seen_link_keys: set[str] = set()
            for obs in observations:
                src_port = obs.get('source_port_normalized') or obs.get('source_port_raw') or ''
                tgt_port = obs.get('target_port_normalized') or obs.get('target_port_raw') or ''
                lk = f"{obs['source_device_id']}::{src_port}--{neighbor_key}::{tgt_port}"
                if lk in seen_link_keys:
                    continue
                seen_link_keys.add(lk)
                unmanaged_links.append({
                    'link_key': lk,
                    'source_device_id': obs['source_device_id'],
                    'source_hostname': obs.get('source_hostname') or '',
                    'source_port': obs.get('source_port_raw') or '',
                    'source_port_normalized': src_port,
                    'target_device_id': neighbor_key,
                    'target_hostname': display_name,
                    'target_port': obs.get('target_port_raw') or '',
                    'target_port_normalized': tgt_port,
                    'discovery_source': obs.get('protocol') or 'lldp',
                    'confidence': float(obs.get('confidence') or 0.0),
                    'status': 'unknown',
                    'is_inferred': 0,
                    'is_unmanaged': True,
                    'evidence_count': 1,
                    'last_seen': obs.get('collected_at') or '',
                    'source_site_id': obs.get('source_site_id') or '',
                    'target_site_id': obs.get('source_site_id') or '',
                    'match_status': obs.get('match_status') or 'unmatched',
                    'match_candidates_json': obs.get('match_candidates_json') or '[]',
                })

        return {
            'unmanaged_nodes': unmanaged_nodes,
            'unmanaged_links': unmanaged_links,
        }
    finally:
        conn.close()


def get_topology_site_summaries(
    *,
    tenant_id: str | None = None,
    site_ids: list[str] | tuple[str, ...] | None = None,
    device_ids: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Return canonical site cards used by the first-level topology view.

    The optional filters are applied before the cards are assembled so a
    tenant/site-scoped caller cannot infer another scope from device, link,
    orphan, or discovery-run counts.
    """
    conn = get_db_connection()
    try:
        site_rows = conn.execute(
            "SELECT id, site_code, site_name, status, tenant_id FROM sites ORDER BY site_name"
        ).fetchall()
        device_rows = conn.execute(
            """
            SELECT d.id,
                   COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, '')) AS site_id,
                   d.status, s.tenant_id
            FROM devices d
            LEFT JOIN physical_assets pa ON pa.id = d.asset_id
            LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
            ORDER BY d.id
            """
        ).fetchall()
        link_rows = conn.execute(
            '''
            SELECT l.link_key, l.source_device_id, l.target_device_id,
                   COALESCE(NULLIF(spa.site_id, ''), NULLIF(sd.site_id, ''), NULLIF(l.source_site_id, ''), '') AS source_site_id,
                   COALESCE(NULLIF(tpa.site_id, ''), NULLIF(td.site_id, ''), NULLIF(l.target_site_id, ''), '') AS target_site_id,
                   l.status, l.last_seen
            FROM topology_links l
            LEFT JOIN devices sd ON sd.id = l.source_device_id
            LEFT JOIN devices td ON td.id = l.target_device_id
            LEFT JOIN physical_assets spa ON spa.id = sd.asset_id
            LEFT JOIN physical_assets tpa ON tpa.id = td.asset_id
            '''
        ).fetchall()
        orphan_rows = conn.execute(
            """
            SELECT COALESCE(NULLIF(d.site_id, ''), NULLIF(o.source_site_id, ''), '') AS site_id,
                   COUNT(DISTINCT o.source_device_id) AS count
            FROM topology_observations o
            LEFT JOIN devices d ON d.id = o.source_device_id
            WHERE o.target_device_id IS NULL
              AND COALESCE(o.match_status, 'unmatched') IN ('unmatched', 'ambiguous')
            GROUP BY COALESCE(NULLIF(d.site_id, ''), NULLIF(o.source_site_id, ''), '')
            """
        ).fetchall()
        run_rows = conn.execute(
            """
            SELECT site_id, status, started_at, completed_at
            FROM topology_discovery_runs
            ORDER BY started_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    normalized_site_ids = None if site_ids is None else {
        str(item).strip() for item in site_ids if str(item).strip()
    }
    requested_device_ids = None if device_ids is None else {
        str(item).strip() for item in device_ids if str(item).strip()
    }
    site_rows = [
        dict(row) for row in site_rows
        if (not tenant_id or str(row['tenant_id'] or '') == str(tenant_id))
        and (normalized_site_ids is None or str(row['id'] or '') in normalized_site_ids)
    ]
    visible_site_ids = {str(row['id']) for row in site_rows}
    device_rows = [
        dict(row) for row in device_rows
        if (requested_device_ids is None or str(row['id'] or '') in requested_device_ids)
        and (not tenant_id or str(row['tenant_id'] or '') == str(tenant_id))
        and (normalized_site_ids is None or str(row['site_id'] or '') in normalized_site_ids)
    ]
    visible_device_ids = {str(row['id']) for row in device_rows}
    if requested_device_ids is not None:
        # Preserve an explicit empty authorized set as empty, rather than
        # treating it as an omitted filter.
        visible_device_ids &= requested_device_ids
    link_rows = [
        dict(row) for row in link_rows
        if str(row['source_device_id'] or '') in visible_device_ids
        and str(row['target_device_id'] or '') in visible_device_ids
    ]
    orphan_rows = [
        dict(row) for row in orphan_rows
        if (not visible_device_ids or str(row.get('source_device_id') or '') in visible_device_ids)
    ]
    if not visible_device_ids and (requested_device_ids is not None or tenant_id or normalized_site_ids is not None):
        orphan_rows = []
    run_rows = [
        dict(row) for row in run_rows
        if (not normalized_site_ids or str(row['site_id'] or '') in normalized_site_ids)
        and (not tenant_id or str(row['site_id'] or '') in visible_site_ids)
    ]

    site_aliases: dict[str, str] = {}
    for row in site_rows:
        for value in (row['id'], row['site_code'], row['site_name']):
            normalized = str(value or '').strip().lower()
            if normalized:
                site_aliases.setdefault(normalized, str(row['id']))

    summaries: dict[str, dict[str, Any]] = {
        str(row['id']): {
            'site_id': str(row['id']),
            'site_code': row['site_code'] or '',
            'site_name': row['site_name'] or row['site_code'] or row['id'],
            'site_status': row['status'] or 'active',
            'device_count': 0,
            'online_devices': 0,
            'offline_devices': 0,
            'link_count': 0,
            'cross_site_links': 0,
            'stale_links': 0,
            'orphan_devices': 0,
            'last_discovery_at': None,
            'last_discovery_status': None,
        }
        for row in site_rows
    }

    def ensure_site(site_id: str) -> dict[str, Any]:
        key = _canonical_site_id(site_id, site_aliases) or 'unassigned'
        if key not in summaries:
            summaries[key] = {
                'site_id': '' if key == 'unassigned' else key,
                'site_code': 'UNASSIGNED' if key == 'unassigned' else key,
                'site_name': 'Unassigned' if key == 'unassigned' else key,
                'site_status': 'active',
                'device_count': 0,
                'online_devices': 0,
                'offline_devices': 0,
                'link_count': 0,
                'cross_site_links': 0,
                'stale_links': 0,
                'orphan_devices': 0,
                'last_discovery_at': None,
                'last_discovery_status': None,
            }
        return summaries[key]

    for row in device_rows:
        summary = ensure_site(str(row['site_id'] or ''))
        summary['device_count'] += 1
        if str(row['status'] or '').lower() == 'online':
            summary['online_devices'] += 1
        elif str(row['status'] or '').lower() == 'offline':
            summary['offline_devices'] += 1

    now = datetime.now(timezone.utc)
    # Site cards follow the canvas' logical-link contract: multiple physical
    # member rows between the same two devices count as one link.  The raw
    # topology_links table may still contain those members while a rolling
    # upgrade is in progress, so fold them here as well.
    link_groups: dict[tuple[str, str], list[Any]] = {}
    for row in link_rows:
        endpoints = sorted([str(row['source_device_id'] or ''), str(row['target_device_id'] or '')])
        link_groups.setdefault((endpoints[0], endpoints[1]), []).append(row)

    for grouped_rows in link_groups.values():
        active_rows = [row for row in grouped_rows if _link_operational_state(dict(row), now)[0] != 'stale']
        stale_rows = [row for row in grouped_rows if _link_operational_state(dict(row), now)[0] == 'stale']
        row = active_rows[0] if active_rows else grouped_rows[0]
        source_site = _canonical_site_id(row['source_site_id'], site_aliases)
        target_site = _canonical_site_id(row['target_site_id'], site_aliases)
        site_ids = {source_site, target_site}
        effective_state = 'unknown' if active_rows else 'stale'
        for site_id in site_ids:
            summary = ensure_site(site_id)
            # Keep stale evidence visible even when a newer member link keeps
            # the endpoint pair active.  Deduplicate rows sharing the same
            # link_key so directional/duplicate evidence does not inflate the
            # site card, while still separating current and stale links.
            stale_keys = {str(item['link_key'] or '') for item in stale_rows}
            summary['stale_links'] += len(stale_keys) if stale_keys else 0
            if effective_state != 'stale':
                summary['link_count'] += 1
                if source_site != target_site:
                    summary['cross_site_links'] += 1

    for row in orphan_rows:
        ensure_site(str(row['site_id'] or ''))['orphan_devices'] = int(row['count'] or 0)

    seen_run_sites: set[str] = set()
    for row in run_rows:
        site_id = _canonical_site_id(row['site_id'], site_aliases)
        if not site_id:
            continue
        key = site_id or 'unassigned'
        if key in seen_run_sites:
            continue
        seen_run_sites.add(key)
        summary = ensure_site(site_id)
        summary['last_discovery_at'] = row['completed_at'] or row['started_at']
        summary['last_discovery_status'] = row['status']

    return sorted(summaries.values(), key=lambda item: str(item['site_name']).lower())


def get_topology_generation_status(
    *,
    device_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Return an explainable snapshot of how the current graph was generated."""
    conn = get_db_connection()
    try:
        device_filter, device_params = _device_id_filter('d.id', device_ids)
        device_where = f'WHERE {device_filter}' if device_filter else ''
        device_metrics = conn.execute(
            f'''
            SELECT COUNT(*) AS managed_devices,
                   SUM(CASE WHEN status = 'online' AND COALESCE(ip_address, '') <> '' THEN 1 ELSE 0 END) AS eligible_devices
            FROM devices d
            {device_where}
            ''',
            tuple(device_params),
        ).fetchone()
        observation_filter, observation_params = _device_id_filter('o.source_device_id', device_ids)
        observation_where = f'WHERE {observation_filter}' if observation_filter else ''
        observation_metrics = conn.execute(
            f'''
            SELECT COUNT(*) AS total_observations,
                   SUM(CASE WHEN COALESCE(match_status, 'unmatched') = 'matched' THEN 1 ELSE 0 END) AS matched_observations,
                   SUM(CASE WHEN COALESCE(match_status, 'unmatched') = 'ambiguous' THEN 1 ELSE 0 END) AS ambiguous_observations,
                   SUM(CASE WHEN COALESCE(match_status, 'unmatched') = 'unmatched' THEN 1 ELSE 0 END) AS unmatched_observations,
                   MAX(collected_at) AS last_observation_at
            FROM topology_observations o
            {observation_where}
            ''',
            tuple(observation_params),
        ).fetchone()
        link_filter_source, link_source_params = _device_id_filter('source_device_id', device_ids)
        link_filter_target, link_target_params = _device_id_filter('target_device_id', device_ids)
        link_where_parts = [item for item in (link_filter_source, link_filter_target) if item]
        link_where = f"WHERE {' AND '.join(link_where_parts)}" if link_where_parts else ''
        link_rows = conn.execute(
            f'SELECT status, last_seen, evidence_count FROM topology_links {link_where}',
            tuple([*link_source_params, *link_target_params]),
        ).fetchall()
        if device_ids is None:
            run_where = ''
            run_params: list[Any] = []
        else:
            run_filter, run_filter_params = _device_id_filter('rd.device_id', device_ids)
            run_where = (
                'WHERE EXISTS (SELECT 1 FROM topology_discovery_run_devices rd '
                f'WHERE rd.run_id = topology_discovery_runs.id AND {run_filter})'
            )
            run_params = run_filter_params
        latest_run_row = conn.execute(
            f'''
            SELECT id, scope, site_id, status, requested_by, started_at, completed_at,
                   total_devices, success_devices, failed_devices, total_observations,
                   total_links, last_error_code, summary_json
            FROM topology_discovery_runs
            {run_where}
            ORDER BY started_at DESC
            LIMIT 1
            ''',
            tuple(run_params),
        ).fetchone()
    finally:
        conn.close()

    now = datetime.now(timezone.utc)
    stale_links = 0
    multi_evidence_links = 0
    for row in link_rows:
        item = dict(row)
        if _link_operational_state(item, now)[0] == 'stale':
            stale_links += 1
        if int(item.get('evidence_count') or 0) > 1:
            multi_evidence_links += 1

    devices = dict(device_metrics) if device_metrics else {}
    observations = dict(observation_metrics) if observation_metrics else {}
    latest_run = dict(latest_run_row) if latest_run_row else None
    if latest_run:
        try:
            latest_run['summary'] = json.loads(latest_run.pop('summary_json') or '{}')
        except (TypeError, ValueError):
            latest_run['summary'] = {}

    total_observations = int(observations.get('total_observations') or 0)
    ambiguous_observations = int(observations.get('ambiguous_observations') or 0)
    unmatched_observations = int(observations.get('unmatched_observations') or 0)
    warnings: list[dict[str, Any]] = []
    if int(devices.get('eligible_devices') or 0) == 0:
        warnings.append({
            'code': 'no_eligible_devices',
            'count': 0,
            'message': 'No online device with a management IP is eligible for topology discovery.',
        })
    if ambiguous_observations:
        warnings.append({
            'code': 'ambiguous_neighbors',
            'count': ambiguous_observations,
            'message': 'Some neighbor identities match more than one managed device.',
        })
    if unmatched_observations:
        warnings.append({
            'code': 'unmanaged_neighbors',
            'count': unmatched_observations,
            'message': 'Some neighbors are not present in managed device inventory.',
        })
    if stale_links:
        warnings.append({
            'code': 'stale_links',
            'count': stale_links,
            'message': 'Some links have not been refreshed within the discovery evidence TTL.',
        })

    return {
        'generation': {
            'strategy': 'automatic_and_on_demand',
            'automatic': {
                'enabled': True,
                'job_id': 'topology_interface_sync',
                'interval_seconds': TOPOLOGY_AUTOMATIC_INTERVAL_SECONDS,
                'scope': 'online_devices_with_management_ip',
            },
            'manual': {
                'enabled': True,
                'scopes': ['full', 'site', 'devices'],
            },
            'evidence_ttl_seconds': TOPOLOGY_LINK_TTL_SECONDS,
            'stale_retention_seconds': TOPOLOGY_LINK_STALE_RETENTION_SECONDS,
            'pipeline': [
                {'stage': 'select', 'description': 'Select online devices with a management IP.'},
                {'stage': 'collect', 'description': 'Run vendor-specific read-only LLDP commands over SSH.'},
                {'stage': 'normalize', 'description': 'Normalize platform, hostname, chassis ID, and interface names.'},
                {'stage': 'match', 'description': 'Match peers by management IP, chassis/serial, then exact system name.'},
                {'stage': 'deduplicate', 'description': 'Merge directional evidence into one canonical physical link.'},
                {'stage': 'publish', 'description': 'Publish managed links and retain unmatched peers as unmanaged nodes.'},
            ],
        },
        'inventory': {
            'managed_devices': int(devices.get('managed_devices') or 0),
            'eligible_devices': int(devices.get('eligible_devices') or 0),
            'total_observations': total_observations,
            'matched_observations': int(observations.get('matched_observations') or 0),
            'ambiguous_observations': ambiguous_observations,
            'unmatched_observations': unmatched_observations,
            'managed_links': len(link_rows),
            'multi_evidence_links': multi_evidence_links,
            'stale_links': stale_links,
            'last_observation_at': observations.get('last_observation_at'),
        },
        'latest_manual_run': latest_run,
        'warnings': warnings,
        'health': 'empty' if total_observations == 0 else ('degraded' if warnings else 'healthy'),
    }


def list_discovery_runs(
    limit: int = 20,
    *,
    device_ids: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        run_filter, run_params = _device_id_filter('rd.device_id', device_ids)
        run_where = ''
        params: list[Any] = []
        if device_ids is not None:
            run_where = (
                'WHERE EXISTS (SELECT 1 FROM topology_discovery_run_devices rd '
                f'WHERE rd.run_id = topology_discovery_runs.id AND {run_filter}) '
                'AND NOT EXISTS (SELECT 1 FROM topology_discovery_run_devices rd_hidden '
                f'WHERE rd_hidden.run_id = topology_discovery_runs.id AND NOT ({run_filter.replace("rd.", "rd_hidden.")}))'
            )
            params.extend([*run_params, *run_params])
        rows = conn.execute(
            f'''
            SELECT * FROM topology_discovery_runs
            {run_where}
            ORDER BY started_at DESC
            LIMIT ?
            ''',
            tuple([*params, limit]),
        ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            total = max(0, int(item.get('total_devices') or 0))
            processed = int(item.get('success_devices') or 0) + int(item.get('failed_devices') or 0)
            item['processed_devices'] = processed
            item['progress_percent'] = round(processed / total * 100) if total else 100
            try:
                item['summary'] = json.loads(item.get('summary_json') or '{}')
            except (TypeError, ValueError):
                item['summary'] = {}
            results.append(item)
        return results
    finally:
        conn.close()


def get_discovery_run(
    run_id: str,
    *,
    device_limit: int = 100,
    device_offset: int = 0,
    device_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        run_filter, run_params = _device_id_filter('rd.device_id', device_ids)
        if device_ids is None:
            run_sql = 'SELECT * FROM topology_discovery_runs WHERE id = ?'
            run_query_params: list[Any] = [run_id]
        else:
            run_sql = (
                'SELECT * FROM topology_discovery_runs '
                'WHERE id = ? AND EXISTS ('
                'SELECT 1 FROM topology_discovery_run_devices rd '
                f'WHERE rd.run_id = topology_discovery_runs.id AND {run_filter}) '
                'AND NOT EXISTS ('
                'SELECT 1 FROM topology_discovery_run_devices rd_hidden '
                f'WHERE rd_hidden.run_id = topology_discovery_runs.id AND NOT ({run_filter.replace("rd.", "rd_hidden.")}))'
            )
            run_query_params = [run_id, *run_params, *run_params]
        run_row = conn.execute(run_sql, tuple(run_query_params)).fetchone()
        if not run_row:
            return None
        safe_limit = max(1, min(int(device_limit or 100), 500))
        safe_offset = max(0, int(device_offset or 0))
        device_total_row = conn.execute(
            'SELECT COUNT(*) AS total FROM topology_discovery_run_devices WHERE run_id = ?',
            (run_id,),
        ).fetchone()
        status_rows = conn.execute(
            'SELECT status, COUNT(*) AS count FROM topology_discovery_run_devices WHERE run_id = ? GROUP BY status',
            (run_id,),
        ).fetchall()
        device_rows = conn.execute(
            '''
            SELECT * FROM topology_discovery_run_devices
            WHERE run_id = ?
            ORDER BY hostname, device_id
            LIMIT ? OFFSET ?
            ''',
            (run_id, safe_limit, safe_offset),
        ).fetchall()
        run = dict(run_row)
        devices = [dict(row) for row in device_rows]
        total_device_count = int((device_total_row['total'] if device_total_row else 0) or 0)
        processed = int(run.get('success_devices') or 0) + int(run.get('failed_devices') or 0)
        total = max(0, int(run.get('total_devices') or total_device_count))
        status_counts = {str(item['status'] or ''): int(item['count'] or 0) for item in status_rows}
        run['processed_devices'] = processed
        run['running_devices'] = status_counts.get('running', 0)
        run['pending_devices'] = status_counts.get('pending', 0)
        run['progress_percent'] = round(processed / total * 100) if total else 100
        try:
            run['summary'] = json.loads(run.get('summary_json') or '{}')
        except (TypeError, ValueError):
            run['summary'] = {}
        return {
            'run': run,
            'devices': devices,
            'device_pagination': {
                'limit': safe_limit,
                'offset': safe_offset,
                'total': total_device_count,
                'has_more': safe_offset + len(devices) < total_device_count,
            },
        }
    finally:
        conn.close()


def get_discovery_evidence(
    run_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    match_status: str | None = None,
    include_raw: bool = False,
    device_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    """Return bounded LLDP evidence without loading a whole run into memory."""
    safe_limit = max(1, min(int(limit or 100), 500))
    safe_offset = max(0, int(offset or 0))
    clauses = ['o.discovery_run_id = ?']
    params: list[Any] = [run_id]
    device_filter, device_params = _device_id_filter('o.source_device_id', device_ids)
    if device_ids is not None:
        clauses.append(device_filter)
        params.extend(device_params)
    if match_status in {'matched', 'ambiguous', 'unmatched'}:
        clauses.append('COALESCE(o.match_status, \'unmatched\') = ?')
        params.append(match_status)
    where_sql = ' AND '.join(clauses)
    conn = get_db_connection()
    try:
        if device_ids is None:
            run_exists = conn.execute(
                'SELECT id FROM topology_discovery_runs WHERE id = ?',
                (run_id,),
            ).fetchone()
        else:
            run_filter, run_params = _device_id_filter('rd.device_id', device_ids)
            run_exists = conn.execute(
                'SELECT id FROM topology_discovery_runs '
                'WHERE id = ? AND EXISTS ('
                'SELECT 1 FROM topology_discovery_run_devices rd '
                f'WHERE rd.run_id = topology_discovery_runs.id AND {run_filter}) '
                'AND NOT EXISTS ('
                'SELECT 1 FROM topology_discovery_run_devices rd_hidden '
                f'WHERE rd_hidden.run_id = topology_discovery_runs.id AND NOT ({run_filter.replace("rd.", "rd_hidden.")}))',
                tuple([run_id, *run_params, *run_params]),
            ).fetchone()
        if not run_exists:
            return None
        total_row = conn.execute(
            f'SELECT COUNT(*) AS total FROM topology_observations o WHERE {where_sql}',
            tuple(params),
        ).fetchone()
        rows = conn.execute(
            f'''
            SELECT o.id, o.source_device_id, o.source_hostname, o.source_port_raw,
                   o.neighbor_name_raw, o.neighbor_ip_address, o.target_device_id,
                   o.target_hostname, o.target_port_raw, o.protocol, o.confidence,
                   o.collected_at, o.source_site_id, o.match_method, o.match_status,
                   o.match_candidates_json, o.raw_payload_json
            FROM topology_observations o
            WHERE {where_sql}
            ORDER BY o.collected_at DESC, o.id
            LIMIT ? OFFSET ?
            ''',
            tuple(params + [safe_limit, safe_offset]),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item['match_candidates'] = json.loads(item.pop('match_candidates_json') or '[]')
            except (TypeError, ValueError):
                item['match_candidates'] = []
            raw_payload = item.pop('raw_payload_json', '{}')
            if include_raw:
                item['raw_payload'] = str(raw_payload or '{}')[:50000]
            items.append(item)
        total = int((total_row['total'] if total_row else 0) or 0)
        return {
            'run_id': run_id,
            'items': items,
            'pagination': {
                'limit': safe_limit,
                'offset': safe_offset,
                'total': total,
                'has_more': safe_offset + len(items) < total,
            },
        }
    finally:
        conn.close()
