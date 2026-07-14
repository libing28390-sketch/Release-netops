from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from netmiko import ConnectHandler
from ntc_templates.parse import parse_output

from drivers.ssh_compat import build_netmiko_compatibility_kwargs


SUPPORTED_CATEGORIES = (
    'interfaces',
    'neighbors',
    'arp',
    'mac_table',
    'routing_table',
    'bgp',
    'ospf',
    'bfd',
    'bgp_routes',
    'ntp',
    'environment',
    'fan',
    'power',
    'stack',
    'transceiver',
    'eth_trunk',
)


PLATFORM_DEVICE_TYPE_MAP = {
    'cisco_ios': 'cisco_ios',
    'cisco': 'cisco_ios',
    'ios': 'cisco_ios',
    'iosxe': 'cisco_ios',
    'cisco_iosxe': 'cisco_ios',
    'cisco_xe': 'cisco_ios',
    'cisco_nxos': 'cisco_nxos',
    'nxos': 'cisco_nxos',
    'nexus': 'cisco_nxos',
    'juniper_junos': 'juniper_junos',
    'juniper': 'juniper_junos',
    'junos': 'juniper_junos',
    'arista_eos': 'arista_eos',
    'arista': 'arista_eos',
    'eos': 'arista_eos',
    'huawei_vrp': 'huawei',
    'huawei_vrpv8': 'huawei',
    'h3c_comware9': 'hp_comware',
    'huawei': 'huawei',
    'vrp': 'huawei',
    'ce': 'huawei',
    'ce_vrp': 'huawei',
    'ne': 'huawei',
    '\u534e\u4e3avrp': 'huawei',
    'h3c_comware': 'hp_comware',
    'h3c': 'hp_comware',
    'comware': 'hp_comware',
    'hp_comware': 'hp_comware',
    'ruijie_rgos': 'ruijie_os',
    'ruijie_os': 'ruijie_os',
    'ruijie': 'ruijie_os',
    'rgos': 'ruijie_os',
    'zte_zxros': 'zte_zxros',
    'zte': 'zte_zxros',
    'zxros': 'zte_zxros',
    'maipu': 'maipu',
    'maipu_network': 'maipu',
    'linux': 'linux',
    'ubuntu': 'linux',
    'centos': 'linux',
    'generic': 'linux',
}

NTC_PLATFORM_MAP = {
    'cisco_ios': 'cisco_ios',
    'cisco': 'cisco_ios',
    'ios': 'cisco_ios',
    'iosxe': 'cisco_ios',
    'cisco_iosxe': 'cisco_ios',
    'cisco_xe': 'cisco_ios',
    'cisco_nxos': 'cisco_nxos',
    'nxos': 'cisco_nxos',
    'nexus': 'cisco_nxos',
    'juniper_junos': 'juniper_junos',
    'juniper': 'juniper_junos',
    'junos': 'juniper_junos',
    'arista_eos': 'arista_eos',
    'arista': 'arista_eos',
    'eos': 'arista_eos',
    'huawei_vrp': 'huawei_vrp',
    'huawei_vrpv8': 'huawei_vrp',
    'h3c_comware9': 'h3c_comware9',
    'huawei': 'huawei_vrp',
    'vrp': 'huawei_vrp',
    'ce': 'huawei_vrp',
    'ce_vrp': 'huawei_vrp',
    'ne': 'huawei_vrp',
    '\u534e\u4e3avrp': 'huawei_vrp',
    'h3c_comware': 'hp_comware',
    'h3c': 'hp_comware',
    'comware': 'hp_comware',
    'hp_comware': 'hp_comware',
    # ntc-templates 当前没有 ruijie_os 平台索引，临时回退 to Cisco 语法族做有限复用。
    'ruijie_rgos': 'ruijie_rgos',
    'ruijie_os': 'ruijie_rgos',
    'ruijie': 'ruijie_rgos',
    'rgos': 'ruijie_rgos',
    'zte_zxros': 'zte_zxros',
    'zte': 'zte_zxros',
    'zxros': 'zte_zxros',
    'maipu': 'maipu',
    'maipu_network': 'maipu',
}

# Alias map: maps non-standard platform values stored in DB to canonical keys
_PLATFORM_ALIAS: dict[str, str] = {
    'cisco': 'cisco_ios',
    'ios': 'cisco_ios',
    'iosxe': 'cisco_ios',
    'cisco_iosxe': 'cisco_ios',
    'cisco_xe': 'cisco_ios',
    'nxos': 'cisco_nxos',
    'nexus': 'cisco_nxos',
    'juniper': 'juniper_junos',
    'junos': 'juniper_junos',
    'arista': 'arista_eos',
    'eos': 'arista_eos',
    'h3c': 'h3c_comware',
    'comware': 'h3c_comware',
    'huawei': 'huawei_vrp',
    'vrp': 'huawei_vrp',
    'ce': 'huawei_vrp',
    'ce_vrp': 'huawei_vrp',
    'ne': 'huawei_vrp',
    '\u534e\u4e3avrp': 'huawei_vrp',
    'ruijie': 'ruijie_rgos',
    'rgos': 'ruijie_rgos',
    'ruijie_os': 'ruijie_rgos',
    'zte': 'zte_zxros',
    'zxros': 'zte_zxros',
    'maipu_network': 'maipu',
}


def _normalize_platform(raw: str) -> str:
    """Normalize a raw platform string to a canonical COMMAND_CATALOG key."""
    p = str(raw or '').lower().strip()
    return _PLATFORM_ALIAS.get(p, p)

# 按设备角色排除不适用的采集类别
# router: 不采集 mac_table（交换表是二层交换功能）
# access/switch: 不采集 bgp、ospf、bfd（纯接入层通常无路由协议邻居）
ROLE_EXCLUDED_CATEGORIES: dict[str, set[str]] = {
    'router': {'mac_table'},
    'access': {'bgp', 'ospf', 'bfd', 'bgp_routes'},
}

COMMAND_CATALOG: dict[str, dict[str, list[str]]] = {
    'cisco_ios': {
        'interfaces': ['show ip interface brief'],
        'neighbors': ['show lldp neighbors detail', 'show cdp neighbors detail'],
        'arp': ['show arp'],
        'mac_table': ['show mac address-table'],
        'routing_table': ['show ip route'],
        'bgp': ['show ip bgp summary'],
        'ospf': ['show ip ospf neighbor'],
        'bfd': ['show bfd neighbors', 'show bfd neighbors details'],
        'bgp_routes': ['show ip bgp'],
    },
    'cisco_nxos': {
        'interfaces': ['show ip interface brief'],
        'neighbors': ['show lldp neighbors detail', 'show cdp neighbors detail'],
        'arp': ['show ip arp'],
        'mac_table': ['show mac address-table'],
        'routing_table': ['show ip route'],
        'bgp': ['show bgp ipv4 unicast summary'],
        'ospf': ['show ip ospf neighbors'],
        'bfd': ['show bfd neighbors'],
        'bgp_routes': ['show bgp ipv4 unicast'],
    },
    'juniper_junos': {
        'interfaces': ['show interfaces terse'],
        'neighbors': ['show lldp neighbors'],
        'arp': ['show arp no-resolve'],
        'mac_table': ['show ethernet-switching table'],
        'routing_table': ['show route'],
        'bgp': ['show bgp summary'],
        'ospf': ['show ospf neighbor'],
        'bfd': ['show bfd session'],
        'bgp_routes': ['show route protocol bgp'],
    },
    'arista_eos': {
        'interfaces': ['show ip interface brief'],
        'neighbors': ['show lldp neighbors detail'],
        'arp': ['show arp'],
        'mac_table': ['show mac address-table'],
        'routing_table': ['show ip route'],
        'bgp': ['show ip bgp summary'],
        'ospf': ['show ip ospf neighbor'],
        'bfd': ['show bfd neighbors'],
        'bgp_routes': ['show ip bgp'],
    },
    'huawei_vrp': {
        'interfaces': ['display interface brief'],
        'neighbors': ['display lldp neighbor verbose'],
        'arp': ['display arp all'],
        'mac_table': ['display mac-address'],
        'routing_table': ['display ip routing-table'],
        'bgp': ['display bgp peer'],
        'ospf': ['display ospf peer'],
        'bfd': ['display bfd session all'],
        'bgp_routes': ['display bgp routing-table'],
        'ntp': ['display ntp-service status'],
        'environment': ['display temperature all'],
        'fan': ['display fan'],
        'power': ['display power'],
        'stack': ['display stack'],
        'transceiver': ['display transceiver interface'],
        'eth_trunk': ['display eth-trunk'],
    },
    'huawei_vrpv8': {
        'interfaces': ['display interface brief'],
        'neighbors': ['display lldp neighbor verbose'],
        'arp': ['display arp all'],
        'mac_table': ['display mac-address'],
        'routing_table': ['display ip routing-table'],
        'bgp': ['display bgp peer'],
        'ospf': ['display ospf peer brief'],
        'bfd': ['display bfd session all'],
        'bgp_routes': ['display bgp routing-table'],
        'ntp': ['display ntp status'],
        'environment': ['display temperature all'],
        'fan': ['display fan'],
        'power': ['display power'],
        'stack': ['display stack'],
        'transceiver': ['display transceiver interface'],
        'eth_trunk': ['display eth-trunk'],
    },
    'h3c_comware': {
        'interfaces': ['display interface brief'],
        'neighbors': ['display lldp neighbor-information list'],
        'arp': ['display arp'],
        'mac_table': ['display mac-address'],
        'routing_table': ['display ip routing-table'],
        'bgp': ['display bgp peer'],
        'ospf': ['display ospf peer'],
        'bfd': ['display bfd session all'],
        'bgp_routes': ['display bgp routing-table'],
        'ntp': ['display ntp-service status'],
        'environment': ['display environment'],
        'fan': ['display fan'],
        'power': ['display power'],
        'stack': ['display irf'],
        'transceiver': ['display transceiver interface'],
        'eth_trunk': ['display link-aggregation verbose'],
    },
    # Comware5 remains a separate catalog because its output grammar and
    # template family differ from Comware7/9.
    'hp_comware': {
        'interfaces': ['display interface brief'],
        'neighbors': ['display lldp neighbor-information list'],
        'arp': ['display arp'],
        'mac_table': ['display mac-address'],
        'routing_table': ['display ip routing-table'],
        'bgp': ['display bgp peer'],
        'ospf': ['display ospf peer'],
        'ntp': ['display ntp-service status'],
        'fan': ['display fan'],
        'eth_trunk': ['display link-aggregation verbose'],
    },
    'h3c_comware9': {
        'interfaces': ['display interface brief'],
        'neighbors': ['display lldp neighbor-information list'],
        'arp': ['display arp'],
        'mac_table': ['display mac-address'],
        'routing_table': ['display ip routing-table'],
        'bgp': ['display bgp peer'],
        'ospf': ['display ospf peer'],
        'bfd': ['display bfd session all'],
        'bgp_routes': ['display bgp routing-table'],
        'ntp': ['display ntp-service status'],
        'environment': ['display environment'],
        'fan': ['display fan'],
        'power': ['display power'],
        'stack': ['display irf'],
        'transceiver': ['display transceiver interface'],
        'eth_trunk': ['display link-aggregation verbose'],
    },
    'ruijie_rgos': {
        'interfaces': ['show ip interface brief'],
        'neighbors': ['show lldp neighbors detail'],
        'arp': ['show arp'],
        'mac_table': ['show mac address-table'],
        'routing_table': ['show ip route'],
        'bgp': ['show ip bgp summary'],
        'ospf': ['show ip ospf neighbor'],
        'bfd': ['show bfd neighbors', 'show bfd neighbors details'],
        'bgp_routes': ['show ip bgp'],
    },
    # Keep registered domestic platforms isolated until an official output
    # fixture proves the command grammar for the exact platform family.
    'zte_zxros': {},
    'maipu': {},
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_categories(categories: list[str] | None, role: str = '') -> list[str]:
    if not categories:
        base = list(SUPPORTED_CATEGORIES)
    else:
        requested = [str(item).strip().lower() for item in categories if str(item).strip()]
        invalid = [item for item in requested if item not in SUPPORTED_CATEGORIES]
        if invalid:
            raise ValueError(f'Unsupported categories: {", ".join(sorted(set(invalid)))}')
        base = requested
    excluded = ROLE_EXCLUDED_CATEGORIES.get(role.lower().strip(), set()) if role else set()
    if excluded:
        base = [c for c in base if c not in excluded]
    return base


def _resolve_commands(platform: str, categories: list[str]) -> dict[str, list[str]]:
    # Never send Cisco commands to a recognized non-Cisco platform when a
    # catalog entry is missing; surface an empty category instead.
    catalog = COMMAND_CATALOG.get(_normalize_platform(platform), {})
    return {category: catalog.get(category, []) for category in categories}


def _first_complete_pair(*pairs: tuple[str, str]) -> tuple[str, str]:
    for username, password in pairs:
        if username and password:
            return username, password
    return '', ''


def _build_connection_params(device_info: dict[str, Any], auth_role: str = 'auto') -> dict[str, Any]:
    platform = _normalize_platform(device_info.get('platform') or '')
    device_type = PLATFORM_DEVICE_TYPE_MAP.get(platform) or platform or 'cisco_ios'
    
    from core.crypto import decrypt_credential
    from services.vault_service import resolve_device_credentials

    # 统一通过 resolve_device_credentials 解密，避免直接读取加密字段
    creds = resolve_device_credentials(device_info)

    username = ''
    password = ''
    role = str(auth_role or 'auto').lower().strip()
    if role == 'admin':
        username, password = _first_complete_pair(
            (creds.get('admin_username') or '', creds.get('admin_password') or ''),
            (creds.get('username') or '', creds.get('password') or ''),
            (creds.get('normal_username') or '', creds.get('normal_password') or ''),
        )
    elif role == 'normal':
        username, password = _first_complete_pair(
            (creds.get('normal_username') or '', creds.get('normal_password') or ''),
            (creds.get('username') or '', creds.get('password') or ''),
            (creds.get('admin_username') or '', creds.get('admin_password') or ''),
        )
    else:
        # For operational collection, prefer the credential-vault primary login,
        # then privileged login, then normal login. Keep username/password paired.
        username, password = _first_complete_pair(
            (creds.get('username') or '', creds.get('password') or ''),
            (creds.get('admin_username') or '', creds.get('admin_password') or ''),
            (creds.get('normal_username') or '', creds.get('normal_password') or ''),
        )

    params = {
        'device_type': device_type,
        'host': device_info.get('ip_address'),
        'username': username,
        'password': password,
        'port': int(device_info.get('port') or device_info.get('management_port') or 22),
        'timeout': 20,
        'session_timeout': 60,
        'fast_cli': device_type not in {'huawei', 'hp_comware', 'huawei_vrp', 'ruijie_os', 'zte_zxros', 'maipu'},
        'global_delay_factor': 1.5 if device_type in {'huawei', 'hp_comware', 'huawei_vrp', 'ruijie_os', 'zte_zxros', 'maipu'} else 0.5,
        'blocking_timeout': 30,
    }
    params.update(build_netmiko_compatibility_kwargs())
    secret = creds.get('enable_password') or device_info.get('secret') or ''
    if secret:
        params['secret'] = secret
    return params



def _resolve_ntc_platform(platform: str) -> str:
    return NTC_PLATFORM_MAP.get(platform, 'cisco_ios')


def _normalize_records(parsed: Any) -> list[dict[str, Any]]:
    if isinstance(parsed, list):
        normalized: list[dict[str, Any]] = []
        for item in parsed:
            if isinstance(item, dict):
                normalized.append(item)
            else:
                normalized.append({'value': item})
        return normalized
    if isinstance(parsed, dict):
        return [parsed]
    return []


def _normalize_command_for_template_match(command: str) -> str:
    return re.sub(r'\s+', ' ', str(command or '').strip()).lower()


def _parse_with_ntc(platform: str, command: str, output: str) -> list[dict[str, Any]]:
    from core.textfsm import smart_parse_cli
    res = smart_parse_cli(output=output, command=command, platform=platform)
    if res.get('success') and res.get('data'):
        return res['data']
    # IOS-XE keeps its asset/platform identity, while TextFSM uses the
    # Cisco IOS grammar family unless a dedicated IOS-XE template exists.
    ntc_platform = _resolve_ntc_platform(platform)
    if ntc_platform != platform:
        res = smart_parse_cli(output=output, command=command, platform=ntc_platform)
        if res.get('success') and res.get('data'):
            return res['data']
    return []


def _parse_bfd_raw(output: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw_line in str(output or '').splitlines():
        line = raw_line.strip()
        if not line or len(line) < 4:
            continue
        lowered = line.lower()
        if any(token in lowered for token in ('neighbor', 'address', 'session', 'state interface', 'ouraddr', 'peeraddr')):
            continue

        ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', line)
        if not ip_match:
            continue

        state_match = re.search(r'\b(up|down|admindown|admin-down|init|fail|failed)\b', lowered)
        if not state_match:
            continue

        interface_match = re.search(r'\b([a-z]{1,6}[\w/-]*\d[\w./-]*)\b', line, re.IGNORECASE)
        records.append({
            'peer': ip_match.group(0),
            'state': state_match.group(1),
            'interface': interface_match.group(1) if interface_match else '',
            'raw_line': line,
        })
    return records


def _parse_bgp_raw(output: str, platform: str) -> list[dict[str, Any]]:
    import ipaddress
    records: list[dict[str, Any]] = []
    
    local_as = 0
    local_as_match = re.search(r'local AS(?: number)?\s*(?::)?\s*(\d+)', output, re.IGNORECASE)
    if local_as_match:
        try:
            local_as = int(local_as_match.group(1))
        except ValueError:
            pass

    for raw_line in str(output or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue
            
        tokens = line.split()
        if not tokens or len(tokens) < 3:
            continue
            
        neigh_ip = tokens[0]
        try:
            ipaddress.ip_address(neigh_ip)
        except ValueError:
            continue
            
        remote_as = ''
        if tokens[1].isdigit() and tokens[2].isdigit() and tokens[1] == '4':
            remote_as = tokens[2]
        elif tokens[1].isdigit():
            remote_as = tokens[1]
            
        up_down = ''
        state_pfxrcd = ''
        
        if len(tokens) >= 8:
            last_token = tokens[-1]
            sec_last = tokens[-2]
            third_last = tokens[-3]
            
            bgp_states = {'established', 'idle', 'active', 'connect', 'opensent', 'openconfirm'}
            if sec_last.lower() in bgp_states:
                state_pfxrcd = last_token if last_token.isdigit() else sec_last
                up_down = third_last
            elif last_token.lower() in bgp_states or not last_token.isdigit():
                state_pfxrcd = last_token
                up_down = sec_last
            else:
                state_pfxrcd = last_token
                up_down = sec_last
        else:
            state_pfxrcd = tokens[-1]
            up_down = tokens[-2] if len(tokens) >= 2 else ''
            
        records.append({
            'bgp_neigh': neigh_ip,
            'neigh_as': remote_as,
            'state_pfxrcd': state_pfxrcd,
            'up_down': up_down,
            'local_as': local_as
        })
        
    return records


def _parse_ospf_raw(output: str, platform: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    tabular_pattern = re.compile(r'^\s*([0-9.]+)\s+(\d+)\s+(\S+)\s+(\S+)\s+([0-9.]+)\s+(\S+)\s*$')
    
    current_area = '0.0.0.0'
    current_interface = ''
    neigh_id = None
    neigh_ip = None
    
    for raw_line in str(output or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue
            
        tab_match = tabular_pattern.match(line)
        if tab_match:
            records.append({
                'neighbor_id': tab_match.group(1),
                'state': tab_match.group(3),
                'address': tab_match.group(5),
                'interface': tab_match.group(6),
                'area_id': current_area
            })
            continue
            
        area_match = re.search(r'Area\s+([0-9.]+)\s+interface\s+([^\s\'(]+)', line, re.IGNORECASE)
        if area_match:
             current_area = area_match.group(1)
             current_interface = area_match.group(2)
             paren_match = re.search(r'interface\s+[0-9.]+\(([^)]+)\)', line, re.IGNORECASE)
             if paren_match:
                 current_interface = paren_match.group(1)
             continue
             
        router_match = re.search(r'Router\s*ID:?\s*([0-9.]+)\s+Address:?\s*([0-9.]+)', line, re.IGNORECASE)
        if router_match:
            neigh_id = router_match.group(1)
            neigh_ip = router_match.group(2)
            continue
            
        state_match = re.search(r'State:?\s*([a-zA-Z]+)', line, re.IGNORECASE)
        if state_match and neigh_id and neigh_ip:
            records.append({
                'neighbor_id': neigh_id,
                'address': neigh_ip,
                'state': state_match.group(1),
                'interface': current_interface,
                'area_id': current_area
            })
            neigh_id = None
            neigh_ip = None
            
    return records


def _parse_bgp_routes_raw(output: str, platform: str) -> list[dict[str, Any]]:
    """Parse BGP RIB output from Cisco IOS / NX-OS / Huawei / Juniper.

    Real-world Cisco IOS `show ip bgp` output looks like:

        BGP table version is 10, local router ID is 9.9.9.9
        ...
             Network          Next Hop            Metric LocPrf Weight Path
         r>i  6.6.6.6/32       6.6.6.6                  0    100      0 i
         *>   9.9.9.9/32       0.0.0.0                  0         32768 i
         * i                   6.6.6.6                  0    100      0 i

    Key challenges:
      - Status flags occupy the first 1-4 chars and may include
        r (RIB-failure), s (suppressed), d (damped), h (history),
        * (valid), > (best), i (internal).
      - Continuation lines have NO network column – they inherit the
        previous prefix.
      - Column widths are determined by the header line.
    """
    import ipaddress
    records: list[dict[str, Any]] = []
    lines = str(output or '').splitlines()

    current_prefix = ''

    # ── Juniper-specific handling ──────────────────────────────────
    if platform.startswith('juniper'):
        prefix_pattern = re.compile(
            r'\b(?:[0-9a-fA-F]{1,4}:){1,7}:?[0-9a-fA-F]{0,4}/\d{1,3}\b'
            r'|\b(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}\b'
        )
        current_loc_pref = 100
        current_as_path = ''
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            prefix_match = prefix_pattern.search(line)
            if prefix_match:
                current_prefix = prefix_match.group(0)
                current_loc_pref = 100
                current_as_path = ''
            loc_pref_m = re.search(r'localpref\s*(\d+)', line, re.IGNORECASE)
            if loc_pref_m:
                current_loc_pref = int(loc_pref_m.group(1))
            asp_m = re.search(r'AS\s*path:\s*([^,]+)', line, re.IGNORECASE)
            if asp_m:
                current_as_path = asp_m.group(1).strip()
            to_match = re.search(r'>?\s*to\s+([0-9a-fA-F.:]+)', line)
            if to_match and current_prefix:
                next_hop = to_match.group(1)
                is_best = '>' in line or '*' in line
                records.append({
                    'prefix': current_prefix,
                    'next_hop': next_hop,
                    'metric': 0,
                    'loc_pref': current_loc_pref,
                    'weight': 0,
                    'as_path': current_as_path,
                    'is_best': 1 if is_best else 0,
                    'is_active': 1 if is_best else 0,
                    'status': 'best' if is_best else 'valid',
                })
        return records

    # ── Cisco / Huawei / Arista style handling ─────────────────────
    # Step 1: Detect column positions from the header line.
    #   "     Network          Next Hop            Metric LocPrf Weight Path"
    # If the header is not found, fall back to reasonable defaults.
    col_network = 0
    col_nexthop = 20
    col_metric = 40
    col_locprf = 47
    col_weight = 54
    col_path = 61

    for raw_line in lines:
        if 'Network' in raw_line and 'Next Hop' in raw_line:
            col_network = raw_line.index('Network')
            col_nexthop = raw_line.index('Next Hop')
            m_col = raw_line.find('Metric')
            col_metric = m_col if m_col != -1 else col_nexthop + 20
            lp_col = raw_line.find('LocPrf')
            col_locprf = lp_col if lp_col != -1 else col_metric + 7
            w_col = raw_line.find('Weight')
            col_weight = w_col if w_col != -1 else col_locprf + 7
            p_col = raw_line.find('Path')
            col_path = p_col if p_col != -1 else col_weight + 7
            break

    # The status-flags field spans from column 0 up to (but not including) the
    # Network column.  Valid flag characters: * > s d h r i (space).
    flag_chars = set('*>sdhrif ')
    past_header = False

    for raw_line in lines:
        # Wait until we pass the header line
        if not past_header:
            if 'Network' in raw_line and 'Next Hop' in raw_line:
                past_header = True
            continue

        # Skip blank lines
        if not raw_line.strip():
            continue

        # ── Parse status flags (everything before col_network) ──
        flag_zone = raw_line[:col_network] if len(raw_line) > col_network else raw_line
        # Validate that it looks like a status-flag zone (not a random text line)
        if flag_zone.strip() and not all(ch in flag_chars for ch in flag_zone):
            continue

        status_flags = flag_zone.rstrip()
        is_best = '>' in status_flags
        is_valid = '*' in status_flags or '>' in status_flags

        # ── Parse Network (prefix) ──
        if len(raw_line) > col_network:
            network_zone = raw_line[col_network:col_nexthop].strip() if len(raw_line) > col_nexthop else raw_line[col_network:].strip()
            if network_zone and '/' in network_zone:
                current_prefix = network_zone
            elif network_zone:
                # Could be a host route shown without mask (e.g. just an IP)
                ip_m = re.match(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})$', network_zone)
                if ip_m:
                    current_prefix = network_zone + '/32'

        if not current_prefix:
            continue

        # ── Parse Next Hop ──
        nh = ''
        if len(raw_line) > col_nexthop:
            nh_zone = raw_line[col_nexthop:col_metric].strip() if len(raw_line) > col_metric else raw_line[col_nexthop:].strip()
            # Try IPv4 first
            nh_m = re.match(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', nh_zone)
            if nh_m:
                nh = nh_m.group(1)
            else:
                # Try IPv6
                nh_v6 = nh_zone.split()[0] if nh_zone.split() else ''
                if ':' in nh_v6:
                    nh = nh_v6

        if not nh:
            continue

        try:
            ipaddress.ip_address(nh)
        except ValueError:
            continue

        # ── Parse Metric ──
        metric = 0
        if len(raw_line) > col_metric:
            met_zone = raw_line[col_metric:col_locprf].strip() if len(raw_line) > col_locprf else raw_line[col_metric:].strip()
            if met_zone and met_zone.isdigit():
                metric = int(met_zone)

        # ── Parse Local Preference ──
        loc_pref = 0
        if len(raw_line) > col_locprf:
            lp_zone = raw_line[col_locprf:col_weight].strip() if len(raw_line) > col_weight else raw_line[col_locprf:].strip()
            if lp_zone and lp_zone.isdigit():
                loc_pref = int(lp_zone)

        # ── Parse Weight ──
        weight = 0
        if len(raw_line) > col_weight:
            w_zone = raw_line[col_weight:col_path].strip() if len(raw_line) > col_path else raw_line[col_weight:].strip()
            if w_zone and w_zone.isdigit():
                weight = int(w_zone)

        # ── Parse AS Path ──
        as_path = ''
        if len(raw_line) > col_path:
            as_path = raw_line[col_path:].strip()

        # Build human-readable status string
        status_str = status_flags.strip() or '*'
        if not is_valid and not status_str:
            status_str = '?'

        records.append({
            'prefix': current_prefix,
            'next_hop': nh,
            'metric': metric,
            'loc_pref': loc_pref,
            'weight': weight,
            'as_path': as_path,
            'is_best': 1 if is_best else 0,
            'is_active': 1 if is_best else 0,
            'status': status_str,
        })

    return records


def _parse_command_output(platform: str, category: str, command: str, output: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        records = _parse_with_ntc(platform, command, output)
    except Exception:
        records = []

    if records:
        return records

    normalized_command = _normalize_command_for_template_match(command)
    if category == 'bfd' or ' bfd ' in f' {normalized_command} ':
        return _parse_bfd_raw(output)

    # bgp_routes must be checked BEFORE generic bgp to avoid misrouting
    if category == 'bgp_routes' or (' bgp ' in f' {normalized_command} ' and 'summary' not in normalized_command and 'peer' not in normalized_command):
        return _parse_bgp_routes_raw(output, platform)

    if category == 'bgp' or (' bgp ' in f' {normalized_command} ' and ('summary' in normalized_command or 'peer' in normalized_command)):
        return _parse_bgp_raw(output, platform)

    if category == 'ospf' or ' ospf ' in f' {normalized_command} ':
        return _parse_ospf_raw(output, platform)

    return []


def _build_base_payload(device_info: dict[str, Any], platform: str) -> dict[str, Any]:
    return {
        'device': {
            'id': device_info.get('id'),
            'hostname': device_info.get('hostname'),
            'ip_address': device_info.get('ip_address'),
            'platform': platform,
        },
        'collected_at': _utc_now_iso(),
        'categories': [],
    }


def collect_operational_data(device_info: dict[str, Any], categories: list[str] | None = None, auth_role: str = 'auto') -> dict[str, Any]:
    role = str(device_info.get('role') or '').strip()
    selected_categories = _resolve_categories(categories, role=role)
    from core.platform_utils import normalize_device_platform
    platform = normalize_device_platform(device_info.get('vendor'), device_info.get('platform') or 'cisco_ios')
    commands_by_category = _resolve_commands(platform, selected_categories)
    conn_params = _build_connection_params(device_info, auth_role=auth_role)


    payload: dict[str, Any] = _build_base_payload(device_info, platform)

    with ConnectHandler(**conn_params) as client:
        if conn_params.get('secret'):
            try:
                client.enable()
            except Exception:
                pass

        for category in selected_categories:
            category_commands = commands_by_category.get(category, [])
            category_result: dict[str, Any] = {
                'key': category,
                'success': True,
                'commands': category_commands,
                'count': 0,
                'records': [],
                'raw_outputs': [],
                'parser': 'ntc-templates',
            }

            if not category_commands:
                category_result['success'] = False
                category_result['error'] = f'No command catalog found for category {category} on platform {platform}'
                payload['categories'].append(category_result)
                continue

            try:
                for command in category_commands:
                    output = client.send_command(
                        command,
                        cmd_verify=False,
                        strip_prompt=True,
                        strip_command=True,
                        read_timeout=45,
                    )
                    category_result['raw_outputs'].append({'command': command, 'output': output})
                    try:
                        records = _parse_command_output(platform, category, command, output)
                        if records:
                            category_result['records'].extend(records)
                            category_result['count'] = len(category_result['records'])
                    except Exception as parse_exc:
                        category_result.setdefault('parse_errors', []).append({
                            'command': command,
                            'error': str(parse_exc),
                        })
            except Exception as exc:
                category_result['success'] = False
                category_result['error'] = str(exc)

            payload['categories'].append(category_result)

    payload['summary'] = {
        'requested_categories': selected_categories,
        'successful_categories': sum(1 for item in payload['categories'] if item.get('success')),
        'failed_categories': sum(1 for item in payload['categories'] if not item.get('success')),
        'total_records': sum(int(item.get('count') or 0) for item in payload['categories']),
    }
    return payload


def collect_custom_command_data(device_info: dict[str, Any], command: str, auth_role: str = 'auto') -> dict[str, Any]:
    from core.platform_utils import normalize_device_platform
    platform = normalize_device_platform(device_info.get('vendor'), device_info.get('platform') or 'cisco_ios')
    conn_params = _build_connection_params(device_info, auth_role=auth_role)

    commands = [line.strip() for line in str(command or '').splitlines() if line.strip()]
    if not commands:
        raise ValueError('Command cannot be empty')

    payload: dict[str, Any] = _build_base_payload(device_info, platform)
    category_result: dict[str, Any] = {
        'key': 'custom_command',
        'success': True,
        'commands': commands,
        'count': 0,
        'records': [],
        'raw_outputs': [],
        'parser': 'ntc-templates',
        'parse_status': 'unmatched',
    }

    with ConnectHandler(**conn_params) as client:
        if conn_params.get('secret'):
            try:
                client.enable()
            except Exception:
                pass

        try:
            for item in commands:
                output = client.send_command(
                    item,
                    cmd_verify=False,
                    strip_prompt=True,
                    strip_command=True,
                    read_timeout=45,
                )
                category_result['raw_outputs'].append({'command': item, 'output': output})
                try:
                    records = _parse_with_ntc(platform, item, output)
                    if records:
                        category_result['records'].extend(records)
                        category_result['count'] = len(category_result['records'])
                        category_result['parse_status'] = 'matched'
                except Exception as parse_exc:
                    category_result.setdefault('parse_errors', []).append({
                        'command': item,
                        'error': str(parse_exc),
                    })
                    if category_result['parse_status'] != 'matched':
                        category_result['parse_status'] = 'failed'
        except Exception as exc:
            category_result['success'] = False
            category_result['error'] = str(exc)
            category_result['parse_status'] = 'failed'

    if category_result.get('parse_status') == 'failed' and category_result.get('records'):
        category_result['parse_status'] = 'matched'
    elif category_result.get('parse_status') == 'failed' and category_result.get('raw_outputs') and not category_result.get('parse_errors'):
        category_result['parse_status'] = 'unmatched'

    payload['categories'].append(category_result)
    payload['summary'] = {
        'requested_categories': ['custom_command'],
        'successful_categories': 1 if category_result.get('success') else 0,
        'failed_categories': 0 if category_result.get('success') else 1,
        'total_records': int(category_result.get('count') or 0),
    }
    return payload
