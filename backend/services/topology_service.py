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
from scrapli.driver.core import AsyncEOSDriver, AsyncIOSXEDriver, AsyncJunosDriver, AsyncNXOSDriver
from scrapli_community.hp.comware.async_driver import AsyncHPComwareDriver
from scrapli_community.huawei.vrp.async_driver import AsyncHuaweiVRPDriver

from core.crypto import decrypt_credential
from core.interface_utils import normalize_interface_name
from core.textfsm import configure_ntc_templates
from database import get_db_connection
from services.vault_service import resolve_collector_credentials
from services.collection_status_service import record_collection_result
from drivers.ssh_compat import build_netmiko_compatibility_kwargs

logger = logging.getLogger(__name__)
configure_ntc_templates()
_topology_rebuild_lock = threading.Lock()
TOPOLOGY_LINK_TTL_SECONDS = max(60, int(os.environ.get('TOPOLOGY_LINK_TTL_SECONDS', '1800')))
DISCOVERY_LEASE_SECONDS = max(30, int(os.environ.get('TOPOLOGY_DISCOVERY_LEASE_SECONDS', '90')))
DISCOVERY_DEFAULT_TIMEOUT_SECONDS = max(30, int(os.environ.get('TOPOLOGY_DISCOVERY_TIMEOUT_SECONDS', '300')))
DISCOVERY_DEFAULT_MAX_ATTEMPTS = max(1, int(os.environ.get('TOPOLOGY_DISCOVERY_MAX_ATTEMPTS', '2')))

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
    'h3c_comware9': 'hp_comware',
    'comware': 'hp_comware',
    'hp_comware': 'hp_comware',
    'ruijie_rgos': 'ruijie_os',
}

SCRAPLI_DRIVERS = {
    'cisco_ios': AsyncIOSXEDriver,
    'cisco_nxos': AsyncNXOSDriver,
    'juniper_junos': AsyncJunosDriver,
    'arista_eos': AsyncEOSDriver,
    'huawei_vrp': AsyncHuaweiVRPDriver,
    'huawei_vrpv8': AsyncHuaweiVRPDriver,
    'h3c_comware': AsyncHPComwareDriver,
    'h3c_comware9': AsyncHPComwareDriver,
}

SCRAPLI_LEGACY_SSH_SKIP_PLATFORMS = frozenset({
    'cisco_ios',
})

DISCOVERY_COMMANDS = {
    'cisco_ios': [
        ('lldp', 'show lldp neighbors detail'),
        ('cdp', 'show cdp neighbors detail'),
    ],
    'cisco_nxos': [
        ('lldp', 'show lldp neighbors detail'),
        ('cdp', 'show cdp neighbors detail'),
    ],
    'juniper_junos': [('lldp', 'show lldp neighbors detail')],
    'arista_eos': [('lldp', 'show lldp neighbors detail')],
    'huawei_vrp': [('lldp', 'display lldp neighbor verbose')],
    'h3c_comware': [('lldp', 'display lldp neighbor-information verbose')],
    'h3c_comware9': [('lldp', 'display lldp neighbor-information verbose')],
    'ruijie_rgos': [('lldp', 'show lldp neighbors detail')],
}


def normalize_topology_platform(platform: str | None) -> str:
    """Return the canonical discovery catalog key or raise a stable error."""
    raw = str(platform or '').strip().lower()
    aliases = {
        'cisco_xe': 'cisco_ios',
        'huawei_vrpv8': 'huawei_vrp',
        'huawei': 'huawei_vrp',
        'hp_comware': 'h3c_comware',
        'comware': 'h3c_comware',
        'ruijie_os': 'ruijie_rgos',
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
    if 'closed/unreachable' in message or 'timed out' in message or 'timeout' in message:
        return 'ssh_unreachable'
    if 'parse' in message or 'template' in message:
        return 'neighbor_parse_failed'
    return 'topology_discovery_failed'

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
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ''


def _extract_observation_fields(raw: dict[str, Any], protocol: str) -> dict[str, Any]:
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
    confidence = 0.9 if protocol == 'lldp' else 0.82
    return {
        'protocol': protocol,
        'neighbor_name_raw': neighbor_name,
        'neighbor_name_normalized': normalize_hostname(neighbor_name),
        'neighbor_ip_address': neighbor_ip,
        'neighbor_chassis_id': chassis_id,
        'source_port_raw': local_port,
        'source_port_normalized': normalize_interface_name(local_port),
        'target_port_raw': remote_port,
        'target_port_normalized': normalize_interface_name(remote_port),
        'confidence': confidence,
        'raw_payload_json': _safe_json(raw),
    }


def _get_device(device_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
        if not row:
            return None
        device = dict(row)
        collector_credentials = resolve_collector_credentials(device)
        ssh_credentials = collector_credentials['ssh']
        device['username'] = ssh_credentials['username'] or device.get('username', '')
        device['password'] = ssh_credentials['password']
        device['enable_password'] = ssh_credentials['enable_password']
        device['platform'] = normalize_topology_platform(device.get('platform'))
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


async def _collect_neighbors_with_scrapli(device: dict[str, Any], commands: list[tuple[str, str]]) -> tuple[list[dict[str, Any]], str]:
    platform = normalize_topology_platform(device.get('platform'))
    driver_class = SCRAPLI_DRIVERS.get(platform)
    if not driver_class or platform in SCRAPLI_LEGACY_SSH_SKIP_PLATFORMS:
        raise RuntimeError('scrapli_unavailable')

    scrapli_device = {
        'host': device.get('ip_address'),
        'auth_username': device.get('username'),
        'auth_password': device.get('password'),
        'auth_strict_key': False,
        'port': int(device.get('management_port') or device.get('port') or 22),
        'transport': 'asyncssh',
        'timeout_socket': 5,
        'timeout_transport': 5,
        'timeout_ops': 12,
    }

    collected: list[dict[str, Any]] = []
    async with driver_class(**scrapli_device) as client:
        for protocol, command in commands:
            response = await client.send_command(command)
            is_comware = 'comware' in platform or 'hp_comware' in platform
            parsed = None
            if not is_comware:
                try:
                    parsed = response.textfsm_parse_output() or []
                except Exception:
                    parsed = None

            if isinstance(parsed, list) and parsed:
                for item in parsed:
                    observation = _extract_observation_fields(item, protocol)
                    if observation['neighbor_name_raw'] and observation['source_port_raw']:
                        collected.append(observation)
            elif response.result and response.result.strip():
                # TextFSM template not found or Comware bypassed — use regex parser
                logger.info('Scrapli TextFSM bypassed/missed for %s %r, using regex parser', platform, command)
                regex_entries = _regex_parse_lldp_detail(response.result)
                for item in regex_entries:
                    observation = _extract_observation_fields(item, protocol)
                    if observation['neighbor_name_raw'] and observation['source_port_raw']:
                        collected.append(observation)
    return collected, 'scrapli'


async def _collect_neighbors_with_netmiko(device: dict[str, Any], commands: list[tuple[str, str]]) -> tuple[list[dict[str, Any]], str]:
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
        with ConnectHandler(**netmiko_device) as client:
            for protocol, command in commands:
                is_comware = 'comware' in device_type or 'hp_comware' in device_type or 'h3c' in str(device.get('platform', '')).lower()
                parsed = None
                if not is_comware:
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
                    # TextFSM template bypassed/missed — try regex fallback for LLDP/CDP detail
                    raw_text = parsed if isinstance(parsed, str) else client.send_command(command)
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


async def _collect_device_observations(device: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    ip = device.get('ip_address')
    port = int(device.get('management_port') or device.get('port') or 22)
    from drivers.ssh_compat import is_ssh_port_open
    if not is_ssh_port_open(ip, port):
        logger.warning('Skip topology discovery for %s: SSH port %s is closed/unreachable', device.get('hostname'), port)
        raise RuntimeError(f"SSH port {port} is closed/unreachable")

    platform = normalize_topology_platform(device.get('platform'))
    commands = DISCOVERY_COMMANDS[platform]
    last_error: Exception | None = None

    try:
        observations, method = await _collect_neighbors_with_scrapli(device, commands)
        return observations, method
    except Exception as exc:  # noqa: BLE001
        last_error = exc
        logger.warning('Scrapli topology discovery failed for %s: %s', device.get('hostname'), exc)

    try:
        observations, method = await _collect_neighbors_with_netmiko(device, commands)
        return observations, method
    except Exception as exc:  # noqa: BLE001
        last_error = exc
        logger.error('Netmiko topology discovery failed for %s: %s', device.get('hostname'), exc)

    raise RuntimeError(str(last_error) if last_error else 'topology_discovery_failed')


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
        conn.execute('DELETE FROM topology_observations WHERE source_device_id = ?', (device['id'],))
        source_site_id = str(device.get('site_id') or '')
        for observation in observations:
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
            conn.execute(
                '''
                INSERT INTO topology_observations (
                    id, source_device_id, source_hostname, source_port_raw, source_port_normalized,
                    neighbor_name_raw, neighbor_name_normalized, neighbor_ip_address,
                    target_device_id, target_hostname, target_port_raw, target_port_normalized,
                    protocol, confidence, status, discovery_run_id, raw_payload_json, collected_at, updated_at,
                    source_site_id, match_method, match_status, match_candidates_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    str(uuid.uuid4()),
                    device['id'],
                    device.get('hostname') or '',
                    observation['source_port_raw'],
                    observation['source_port_normalized'],
                    observation['neighbor_name_raw'],
                    observation['neighbor_name_normalized'],
                    observation['neighbor_ip_address'],
                    target_device['id'] if target_device else None,
                    target_device.get('hostname') if target_device else observation['neighbor_name_raw'],
                    observation['target_port_raw'],
                    observation['target_port_normalized'],
                    observation['protocol'],
                    final_confidence,
                    'active',
                    run_id,
                    observation['raw_payload_json'],
                    now,
                    now,
                    source_site_id,
                    evidence.get('method') or '',
                    match_status,
                    _safe_json(evidence.get('candidates') or []),
                ),
            )
        conn.commit()
        return {'matched': matched, 'ambiguous': ambiguous, 'unmatched': unmatched}
    finally:
        conn.close()


def rebuild_links_from_observations() -> int:
    with _topology_rebuild_lock:
        return _rebuild_links_from_observations_unlocked()


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
            '''
        ).fetchall()

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            link_key = _build_link_key(
                item['source_device_id'],
                item.get('source_port_normalized') or item.get('source_port_raw') or '',
                item['target_device_id'],
                item.get('target_port_normalized') or item.get('target_port_raw') or '',
            )
            grouped.setdefault(link_key, []).append(item)

        # Load all interfaces into memory for fast lookup
        intf_rows = conn.execute("SELECT id, device_id, interface_name FROM interfaces").fetchall()
        interface_map = {}
        for row in intf_rows:
            dev_id = row['device_id']
            intf_name = row['interface_name']
            norm = normalize_interface_name(intf_name).lower()
            interface_map[(dev_id, norm)] = row['id']

        device_site_rows = conn.execute('SELECT id, site_id FROM devices').fetchall()
        device_sites = {str(row['id']): str(row['site_id'] or '') for row in device_site_rows}

        now = _utc_now_iso()
        conn.execute('DELETE FROM topology_links')
        active_link_keys: set[str] = set()

        for link_key, observations in grouped.items():
            active_link_keys.add(link_key)
            first = observations[0]
            existing = existing_by_key.get(link_key, {})
            reverse_seen = any(
                obs['source_device_id'] == first['target_device_id'] and obs['target_device_id'] == first['source_device_id']
                for obs in observations
            )
            protocols = sorted({obs.get('protocol') or 'lldp' for obs in observations})
            confidence = 1.0 if reverse_seen else max(float(obs.get('confidence') or 0.0) for obs in observations)

            ordered = sorted(
                [
                    {
                        'device_id': first['source_device_id'],
                        'hostname': first.get('source_hostname') or '',
                        'port_raw': first.get('source_port_raw') or '',
                        'port_normalized': first.get('source_port_normalized') or '',
                    },
                    {
                        'device_id': first['target_device_id'],
                        'hostname': first.get('target_hostname') or '',
                        'port_raw': first.get('target_port_raw') or '',
                        'port_normalized': first.get('target_port_normalized') or '',
                    },
                ],
                key=lambda item: (item['device_id'], item['port_normalized'] or item['port_raw']),
            )

            # Resolve source_interface_id
            src_dev = ordered[0]['device_id']
            src_port = ordered[0]['port_normalized'] or ordered[0]['port_raw']
            src_port_norm = normalize_interface_name(src_port).lower()
            src_intf_id = interface_map.get((src_dev, src_port_norm))
            if src_dev and src_port_norm and not src_intf_id:
                src_intf_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO interfaces (id, device_id, interface_name, admin_status, oper_status) VALUES (?, ?, ?, 'unknown', 'unknown')",
                    (src_intf_id, src_dev, ordered[0]['port_raw'] or src_port)
                )
                interface_map[(src_dev, src_port_norm)] = src_intf_id

            # Resolve target_interface_id
            tgt_dev = ordered[1]['device_id']
            tgt_port = ordered[1]['port_normalized'] or ordered[1]['port_raw']
            tgt_port_norm = normalize_interface_name(tgt_port).lower()
            tgt_intf_id = interface_map.get((tgt_dev, tgt_port_norm))
            if tgt_dev and tgt_port_norm and not tgt_intf_id:
                tgt_intf_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO interfaces (id, device_id, interface_name, admin_status, oper_status) VALUES (?, ?, ?, 'unknown', 'unknown')",
                    (tgt_intf_id, tgt_dev, ordered[1]['port_raw'] or tgt_port)
                )
                interface_map[(tgt_dev, tgt_port_norm)] = tgt_intf_id

            conn.execute(
                '''
                INSERT INTO topology_links (
                    id, link_key, source_device_id, source_interface_id, source_hostname, source_port, source_port_normalized,
                    target_device_id, target_interface_id, target_hostname, target_port, target_port_normalized,
                    discovery_source, confidence, status, is_inferred, evidence_count,
                    metadata_json, created_at, updated_at, last_seen, source_site_id, target_site_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    'unknown',
                    0,
                    len(observations),
                    _safe_json({
                        'protocols': protocols,
                        'reverse_seen': reverse_seen,
                        'match_methods': sorted({obs.get('match_method') or '' for obs in observations if obs.get('match_method')}),
                    }),
                    existing.get('created_at') or now,
                    now,
                    max(obs.get('updated_at') or now for obs in observations),
                    device_sites.get(str(ordered[0]['device_id']), ''),
                    device_sites.get(str(ordered[1]['device_id']), ''),
                ),
            )

        stale_retention_seconds = 24 * 60 * 60
        for link_key, existing in existing_by_key.items():
            if link_key in active_link_keys:
                continue
            last_seen = str(existing.get('last_seen') or '')
            try:
                age_seconds = (datetime.fromisoformat(now) - datetime.fromisoformat(last_seen)).total_seconds() if last_seen else stale_retention_seconds + 1
            except Exception:
                age_seconds = stale_retention_seconds + 1
            if age_seconds > stale_retention_seconds:
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
                    metadata_json, created_at, updated_at, last_seen, source_site_id, target_site_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )

        conn.commit()
        return len(active_link_keys)
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
                run_id, scope, 'pending', requested_by, 'lldp_cdp', now, len(device_ids),
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

        observations, method = await _collect_device_observations(device)
        match_summary = _replace_device_observations(device, observations, run_id)
        total_links = rebuild_links_from_observations() if rebuild_links else None
        record_collection_result(
            device_id,
            'topology_lldp_cdp',
            status='success',
            transport='ssh',
            source='lldp_cdp_cli',
            duration_ms=(time.perf_counter() - started) * 1000,
            coverage_total=len(observations),
            coverage_supported=match_summary['matched'],
            metadata={
                'method': method,
                'ambiguous': match_summary['ambiguous'],
                'unmatched': match_summary['unmatched'],
                'run_id': run_id,
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
            'protocols': sorted({item.get('protocol') or 'lldp' for item in observations}),
        }
    except Exception as exc:
        record_collection_result(
            device_id,
            'topology_lldp_cdp',
            status='failed',
            transport='ssh',
            source='lldp_cdp_cli',
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
    try:
        for index, device_id in enumerate(device_ids):
            if not _renew_discovery_lease(run_id, worker_id):
                _update_run(run_id, status='failed', last_error_code='discovery_lease_lost')
                return
            if _is_run_cancel_requested(run_id):
                cancelled = True
                for pending_device_id in device_ids[index:]:
                    _update_run_device(
                        run_id,
                        pending_device_id,
                        status='cancelled',
                        completed_at=_utc_now_iso(),
                        error_code='discovery_cancelled',
                        error_message='Discovery cancelled before this device was processed',
                    )
                break

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
                    success_devices += 1
                    total_observations += int(result['observations_count'])
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
                    break
                except Exception as exc:  # noqa: BLE001
                    error_code = topology_error_code(exc)
                    logger.warning(
                        'Topology discovery failed for device %s in run %s (attempt %s/%s): %s',
                        device_id, run_id, attempt, max_attempts, exc,
                    )
                    if attempt >= max_attempts:
                        failed_devices += 1
                        _update_run_device(
                            run_id,
                            device_id,
                            status='failed',
                            completed_at=_utc_now_iso(),
                            error_code=error_code,
                            error_message=str(exc)[:500],
                        )

            _update_run(
                run_id,
                success_devices=success_devices,
                failed_devices=failed_devices,
                total_observations=total_observations,
            )

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


def get_current_links(
    limit: int | None = 5000,
    *,
    site_id: str | None = None,
    include_stale: bool = True,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if site_id:
        clauses.append('(COALESCE(l.source_site_id, sd.site_id, \'\') = ? OR COALESCE(l.target_site_id, td.site_id, \'\') = ?)')
        params.extend([site_id, site_id])
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
                   COALESCE(l.source_site_id, sd.site_id, '') AS source_site_id_resolved,
                   COALESCE(l.target_site_id, td.site_id, '') AS target_site_id_resolved,
                   COALESCE(ss.site_name, sd.site, '') AS source_site_name,
                   COALESCE(ts.site_name, td.site, '') AS target_site_name
            FROM topology_links l
            JOIN devices sd ON l.source_device_id = sd.id
            JOIN devices td ON l.target_device_id = td.id
            LEFT JOIN sites ss ON ss.id = COALESCE(l.source_site_id, sd.site_id)
            LEFT JOIN sites ts ON ts.id = COALESCE(l.target_site_id, td.site_id)
            {where_sql}
            ORDER BY source_site_name, l.source_hostname, l.source_port_normalized,
                     target_site_name, l.target_hostname, l.target_port_normalized
            {limit_sql}
            ''',
            tuple(params),
        ).fetchall()
        now = datetime.now(timezone.utc)
        result = []
        for row in rows:
            item = dict(row)
            effective_state, stale_reason = _link_operational_state(item, now)
            item['operational_state'] = effective_state
            item['stale_reason'] = stale_reason
            item['ttl_seconds'] = TOPOLOGY_LINK_TTL_SECONDS
            result.append(item)
        return result
    finally:
        conn.close()


def get_unmanaged_neighbors(site_id: str | None = None) -> dict[str, Any]:
    """Aggregate topology observations where the neighbor was not matched to any managed device.

    Returns a dict with:
      - unmanaged_nodes: list of pseudo-device dicts for each unique unmanaged neighbor
      - unmanaged_links: list of link dicts connecting managed source → unmanaged neighbor
    """
    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''
            SELECT o.source_device_id, o.source_hostname, o.source_port_raw, o.source_port_normalized,
                   o.neighbor_name_raw, o.neighbor_name_normalized, o.neighbor_ip_address,
                   o.target_port_raw, o.target_port_normalized, o.protocol, o.confidence,
                   o.collected_at, o.match_status, o.match_candidates_json,
                   COALESCE(o.source_site_id, d.site_id, '') AS source_site_id,
                   COALESCE(s.site_name, d.site, '') AS source_site_name
            FROM topology_observations o
            JOIN devices d ON d.id = o.source_device_id
            LEFT JOIN sites s ON s.id = COALESCE(o.source_site_id, d.site_id)
            WHERE o.target_device_id IS NULL
              AND COALESCE(o.neighbor_name_raw, '') <> ''
              AND (? IS NULL OR COALESCE(o.source_site_id, d.site_id, '') = ?)
            ORDER BY source_site_name, o.source_hostname, o.neighbor_name_raw
            ''',
            (site_id, site_id),
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


def get_topology_site_summaries() -> list[dict[str, Any]]:
    """Return canonical site cards used by the first-level topology view."""
    conn = get_db_connection()
    try:
        site_rows = conn.execute(
            "SELECT id, site_code, site_name, status FROM sites ORDER BY site_name"
        ).fetchall()
        device_rows = conn.execute(
            "SELECT id, site_id, status FROM devices ORDER BY id"
        ).fetchall()
        link_rows = conn.execute(
            "SELECT link_key, source_site_id, target_site_id, status, last_seen FROM topology_links"
        ).fetchall()
        orphan_rows = conn.execute(
            """
            SELECT COALESCE(source_site_id, '') AS site_id, COUNT(DISTINCT source_device_id) AS count
            FROM topology_observations
            WHERE target_device_id IS NULL
              AND COALESCE(match_status, 'unmatched') IN ('unmatched', 'ambiguous')
            GROUP BY COALESCE(source_site_id, '')
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
        key = site_id or 'unassigned'
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
    for row in link_rows:
        source_site = str(row['source_site_id'] or '')
        target_site = str(row['target_site_id'] or '')
        site_ids = {source_site, target_site}
        effective_state, _ = _link_operational_state(dict(row), now)
        for site_id in site_ids:
            summary = ensure_site(site_id)
            summary['link_count'] += 1
            if effective_state == 'stale':
                summary['stale_links'] += 1
            if source_site != target_site:
                summary['cross_site_links'] += 1

    for row in orphan_rows:
        ensure_site(str(row['site_id'] or ''))['orphan_devices'] = int(row['count'] or 0)

    seen_run_sites: set[str] = set()
    for row in run_rows:
        site_id = str(row['site_id'] or '')
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


def list_discovery_runs(limit: int = 20) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''
            SELECT * FROM topology_discovery_runs
            ORDER BY started_at DESC
            LIMIT ?
            ''',
            (limit,),
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
) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        run_row = conn.execute('SELECT * FROM topology_discovery_runs WHERE id = ?', (run_id,)).fetchone()
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
) -> dict[str, Any] | None:
    """Return bounded LLDP/CDP evidence without loading a whole run into memory."""
    safe_limit = max(1, min(int(limit or 100), 500))
    safe_offset = max(0, int(offset or 0))
    clauses = ['o.discovery_run_id = ?']
    params: list[Any] = [run_id]
    if match_status in {'matched', 'ambiguous', 'unmatched'}:
        clauses.append('COALESCE(o.match_status, \'unmatched\') = ?')
        params.append(match_status)
    where_sql = ' AND '.join(clauses)
    conn = get_db_connection()
    try:
        run_exists = conn.execute('SELECT id FROM topology_discovery_runs WHERE id = ?', (run_id,)).fetchone()
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
