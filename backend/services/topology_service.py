import asyncio
import ipaddress
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from netmiko import ConnectHandler
from scrapli.driver.core import AsyncEOSDriver, AsyncIOSXEDriver, AsyncJunosDriver, AsyncNXOSDriver
from scrapli_community.hp.comware.async_driver import AsyncHPComwareDriver
from scrapli_community.huawei.vrp.async_driver import AsyncHuaweiVRPDriver

from core.crypto import decrypt_credential
from core.interface_utils import normalize_interface_name
from core.textfsm import configure_ntc_templates
from database import get_db_connection
from services.vault_service import resolve_device_credentials
from drivers.ssh_compat import build_netmiko_compatibility_kwargs

logger = logging.getLogger(__name__)
configure_ntc_templates()

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

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
        creds = resolve_device_credentials(device)
        device['username'] = creds['username'] or device.get('username', '')
        device['password'] = creds['password']
        device['enable_password'] = creds['enable_password']
        return device
    finally:
        conn.close()


def _match_target_device(conn, neighbor_name: str, neighbor_ip: str, chassis_id: str = '') -> dict[str, Any] | None:
    # Phase 1: Exact IP match (highest confidence)
    if neighbor_ip:
        row = conn.execute(
            'SELECT id, hostname, ip_address FROM devices WHERE LOWER(ip_address) = LOWER(?)',
            (neighbor_ip,),
        ).fetchone()
        if row:
            return dict(row)

    normalized_name = normalize_hostname(neighbor_name)
    normalized_chassis = str(chassis_id or '').strip().lower()

    if not normalized_name and not normalized_chassis:
        return None

    rows = conn.execute('SELECT id, hostname, ip_address, sys_name, sn, model FROM devices').fetchall()

    # Phase 2: Exact hostname / sys_name / serial / chassis-id match
    for row in rows:
        device = dict(row)
        candidates = {
            normalize_hostname(device.get('hostname')),
            normalize_hostname(device.get('sys_name')),
            normalize_hostname(device.get('ip_address')),
        }
        # Also check serial number as chassis-id (Cisco often advertises this)
        sn = str(device.get('sn') or '').strip().lower()
        if sn:
            candidates.add(sn)
        candidates.discard('')
        if normalized_name and normalized_name in candidates:
            return device
        # Match by chassis_id against serial number (common for Cisco/Arista)
        if normalized_chassis and sn and normalized_chassis == sn:
            return device

    # Phase 3: Prefix match — neighbor "core-sw" matches device "core-sw-01.example.com"
    # This handles LLDP system-name truncation and FQDN variations
    if len(normalized_name) >= 3:
        for row in rows:
            device = dict(row)
            device_hostname = normalize_hostname(device.get('hostname'))
            device_sysname = normalize_hostname(device.get('sys_name'))
            if device_hostname and (device_hostname.startswith(normalized_name) or normalized_name.startswith(device_hostname)):
                return device
            if device_sysname and (device_sysname.startswith(normalized_name) or normalized_name.startswith(device_sysname)):
                return device

    return None


def _build_link_key(source_device_id: str, source_port: str, target_device_id: str, target_port: str) -> str:
    left = (str(source_device_id), normalize_interface_name(source_port) or str(source_port or '').strip().lower())
    right = (str(target_device_id), normalize_interface_name(target_port) or str(target_port or '').strip().lower())
    ordered = sorted([left, right], key=lambda item: (item[0], item[1]))
    return f'{ordered[0][0]}::{ordered[0][1]}--{ordered[1][0]}::{ordered[1][1]}'


async def _collect_neighbors_with_scrapli(device: dict[str, Any], commands: list[tuple[str, str]]) -> tuple[list[dict[str, Any]], str]:
    platform = device.get('platform', 'cisco_ios')
    driver_class = SCRAPLI_DRIVERS.get(platform)
    if not driver_class or platform in SCRAPLI_LEGACY_SSH_SKIP_PLATFORMS:
        raise RuntimeError('scrapli_unavailable')

    scrapli_device = {
        'host': device.get('ip_address'),
        'auth_username': device.get('username'),
        'auth_password': device.get('password'),
        'auth_strict_key': False,
        'port': 22,
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
    device_type = PLATFORM_MAP.get(device.get('platform', 'cisco_ios'), 'cisco_ios')
    netmiko_device = {
        'device_type': device_type,
        'host': device.get('ip_address'),
        'username': device.get('username'),
        'password': device.get('password'),
        'port': 22,
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

    commands = DISCOVERY_COMMANDS.get(device.get('platform', 'cisco_ios'), [('lldp', 'show lldp neighbors')])
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


def _replace_device_observations(device: dict[str, Any], observations: list[dict[str, Any]], run_id: str | None):
    now = _utc_now_iso()
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM topology_observations WHERE source_device_id = ?', (device['id'],))

        for observation in observations:
            target_device = _match_target_device(
                conn,
                observation['neighbor_name_raw'],
                observation['neighbor_ip_address'],
                observation.get('neighbor_chassis_id', ''),
            )
            conn.execute(
                '''
                INSERT INTO topology_observations (
                    id, source_device_id, source_hostname, source_port_raw, source_port_normalized,
                    neighbor_name_raw, neighbor_name_normalized, neighbor_ip_address,
                    target_device_id, target_hostname, target_port_raw, target_port_normalized,
                    protocol, confidence, status, discovery_run_id, raw_payload_json, collected_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    observation['confidence'],
                    'active',
                    run_id,
                    observation['raw_payload_json'],
                    now,
                    now,
                ),
            )

        conn.commit()
    finally:
        conn.close()


def rebuild_links_from_observations() -> int:
    conn = get_db_connection()
    try:
        existing_rows = conn.execute('SELECT * FROM topology_links').fetchall()
        existing_by_key = {str(row['link_key'] or ''): dict(row) for row in existing_rows if row['link_key']}
        rows = conn.execute(
            '''
            SELECT * FROM topology_observations
            WHERE target_device_id IS NOT NULL
              AND COALESCE(source_port_normalized, '') <> ''
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
                    "INSERT INTO interfaces (id, device_id, interface_name, admin_status, oper_status) VALUES (?, ?, ?, 'up', 'up')",
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
                    "INSERT INTO interfaces (id, device_id, interface_name, admin_status, oper_status) VALUES (?, ?, ?, 'up', 'up')",
                    (tgt_intf_id, tgt_dev, ordered[1]['port_raw'] or tgt_port)
                )
                interface_map[(tgt_dev, tgt_port_norm)] = tgt_intf_id

            conn.execute(
                '''
                INSERT INTO topology_links (
                    id, link_key, source_device_id, source_interface_id, source_hostname, source_port, source_port_normalized,
                    target_device_id, target_interface_id, target_hostname, target_port, target_port_normalized,
                    discovery_source, confidence, status, is_inferred, evidence_count,
                    metadata_json, created_at, updated_at, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    'up',
                    0,
                    len(observations),
                    _safe_json({'protocols': protocols, 'reverse_seen': reverse_seen}),
                    existing.get('created_at') or now,
                    now,
                    max(obs.get('updated_at') or now for obs in observations),
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
                    metadata_json, created_at, updated_at, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )

        conn.commit()
        return len(active_link_keys)
    finally:
        conn.close()


def create_discovery_run(device_ids: list[str], requested_by: str = 'system', scope: str = 'full') -> str:
    run_id = str(uuid.uuid4())
    now = _utc_now_iso()
    conn = get_db_connection()
    try:
        conn.execute(
            '''
            INSERT INTO topology_discovery_runs (
                id, scope, status, requested_by, protocol_scope, started_at, total_devices, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (run_id, scope, 'pending', requested_by, 'lldp_cdp', now, len(device_ids), '{}'),
        )

        for device_id in device_ids:
            device = conn.execute('SELECT hostname FROM devices WHERE id = ?', (device_id,)).fetchone()
            conn.execute(
                '''
                INSERT INTO topology_discovery_run_devices (
                    id, run_id, device_id, hostname, status
                ) VALUES (?, ?, ?, ?, ?)
                ''',
                (str(uuid.uuid4()), run_id, device_id, device['hostname'] if device else '', 'pending'),
            )

        conn.commit()
        return run_id
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


async def discover_device_neighbors(device_id: str, run_id: str | None = None) -> dict[str, Any]:
    device = _get_device(device_id)
    if not device:
        raise RuntimeError('device_not_found')
    if device.get('status') == 'offline':
        raise RuntimeError('device_is_offline')
    if not device.get('ip_address') or not device.get('username') or not device.get('password'):
        raise RuntimeError('device_credentials_incomplete')

    observations, method = await _collect_device_observations(device)
    _replace_device_observations(device, observations, run_id)
    link_count = rebuild_links_from_observations()
    matched_count = sum(1 for item in observations if item.get('neighbor_name_normalized'))
    return {
        'device_id': device_id,
        'hostname': device.get('hostname') or '',
        'discovery_method': method,
        'observations_count': len(observations),
        'matched_links_count': link_count,
        'protocols': sorted({item.get('protocol') or 'lldp' for item in observations}),
    }


async def discover_lldp_neighbors(device_id: str):
    try:
        return await discover_device_neighbors(device_id, None)
    except RuntimeError as exc:
        # 凭据不完整 / 设备不存在等属于预期情况（如新增设备未配凭据），
        # 周期任务中静默跳过即可，避免 "Task exception was never retrieved" 日志。
        logger.debug('Periodic LLDP discovery skipped for device %s: %s', device_id, exc)
        return None


async def execute_discovery_run(run_id: str, device_ids: list[str]):
    started_at = _utc_now_iso()
    _update_run(run_id, status='running', started_at=started_at)

    success_devices = 0
    failed_devices = 0
    total_observations = 0

    for device_id in device_ids:
        _update_run_device(run_id, device_id, status='running', started_at=_utc_now_iso())
        try:
            result = await discover_device_neighbors(device_id, run_id)
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
            )
        except Exception as exc:  # noqa: BLE001
            failed_devices += 1
            logger.warning('Topology discovery failed for device %s in run %s: %s', device_id, run_id, exc)
            logger.debug('Detailed traceback for topology discovery failure:', exc_info=True)
            _update_run_device(
                run_id,
                device_id,
                status='failed',
                completed_at=_utc_now_iso(),
                error_message=str(exc),
            )

    conn = get_db_connection()
    try:
        total_links = conn.execute('SELECT COUNT(*) AS c FROM topology_links').fetchone()['c']
    finally:
        conn.close()

    _update_run(
        run_id,
        status='completed' if failed_devices == 0 else ('partial' if success_devices > 0 else 'failed'),
        completed_at=_utc_now_iso(),
        success_devices=success_devices,
        failed_devices=failed_devices,
        total_observations=total_observations,
        total_links=total_links,
        summary_json=_safe_json({
            'total_devices': len(device_ids),
            'success_devices': success_devices,
            'failed_devices': failed_devices,
            'total_observations': total_observations,
            'total_links': total_links,
        }),
    )


def get_current_links(limit: int | None = 5000) -> list[dict[str, Any]]:
    """Return managed topology links.

    A `limit` is enforced (default 5000) so a fully meshed datacenter doesn't
    ship hundreds of thousands of rows on every poll. The Topology page
    renders client-side anyway; if you need more than 5000 links you should
    be using filters or paging APIs at the canvas level.
    """
    conn = get_db_connection()
    try:
        if limit and limit > 0:
            rows = conn.execute(
                '''
                SELECT l.*, s.hostname as source_hostname_resolved, t.hostname as target_hostname_resolved
                FROM topology_links l
                JOIN devices s ON l.source_device_id = s.id
                JOIN devices t ON l.target_device_id = t.id
                ORDER BY l.source_hostname, l.source_port_normalized, l.target_hostname, l.target_port_normalized
                LIMIT ?
                ''',
                (int(limit),),
            ).fetchall()
        else:
            rows = conn.execute(
                '''
                SELECT l.*, s.hostname as source_hostname_resolved, t.hostname as target_hostname_resolved
                FROM topology_links l
                JOIN devices s ON l.source_device_id = s.id
                JOIN devices t ON l.target_device_id = t.id
                ORDER BY l.source_hostname, l.source_port_normalized, l.target_hostname, l.target_port_normalized
                '''
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_unmanaged_neighbors() -> dict[str, Any]:
    """Aggregate topology observations where the neighbor was not matched to any managed device.

    Returns a dict with:
      - unmanaged_nodes: list of pseudo-device dicts for each unique unmanaged neighbor
      - unmanaged_links: list of link dicts connecting managed source → unmanaged neighbor
    """
    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''
            SELECT source_device_id, source_hostname, source_port_raw, source_port_normalized,
                   neighbor_name_raw, neighbor_name_normalized, neighbor_ip_address,
                   target_port_raw, target_port_normalized, protocol, confidence,
                   collected_at
            FROM topology_observations
            WHERE target_device_id IS NULL
              AND COALESCE(neighbor_name_raw, '') <> ''
            ORDER BY source_hostname, neighbor_name_raw
            '''
        ).fetchall()

        # Group by unique unmanaged neighbor identity (normalized name + ip)
        neighbor_groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            obs = dict(row)
            # Build a stable ID for this unmanaged neighbor
            norm_name = obs.get('neighbor_name_normalized') or ''
            ip = obs.get('neighbor_ip_address') or ''
            # Prefer IP-based key for uniqueness, fall back to normalized name
            neighbor_key = f'unmanaged::{ip}' if ip else f'unmanaged::{norm_name}'
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
                'site': '',
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
                    'status': 'up',
                    'is_inferred': 0,
                    'is_unmanaged': True,
                    'evidence_count': 1,
                    'last_seen': obs.get('collected_at') or '',
                })

        return {
            'unmanaged_nodes': unmanaged_nodes,
            'unmanaged_links': unmanaged_links,
        }
    finally:
        conn.close()


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
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_discovery_run(run_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        run_row = conn.execute('SELECT * FROM topology_discovery_runs WHERE id = ?', (run_id,)).fetchone()
        if not run_row:
            return None
        device_rows = conn.execute(
            '''
            SELECT * FROM topology_discovery_run_devices
            WHERE run_id = ?
            ORDER BY hostname, device_id
            ''',
            (run_id,),
        ).fetchall()
        return {
            'run': dict(run_row),
            'devices': [dict(row) for row in device_rows],
        }
    finally:
        conn.close()
