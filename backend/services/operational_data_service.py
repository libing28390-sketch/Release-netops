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
)


PLATFORM_DEVICE_TYPE_MAP = {
    'cisco_ios': 'cisco_ios',
    'cisco_nxos': 'cisco_nxos',
    'juniper_junos': 'juniper_junos',
    'arista_eos': 'arista_eos',
    'huawei_vrp': 'huawei',
    'h3c_comware': 'hp_comware',
    'ruijie_rgos': 'ruijie_os',
    'linux': 'linux',
    'ubuntu': 'linux',
    'centos': 'linux',
    'generic': 'linux',
}

NTC_PLATFORM_MAP = {
    'cisco_ios': 'cisco_ios',
    'cisco_nxos': 'cisco_nxos',
    'juniper_junos': 'juniper_junos',
    'arista_eos': 'arista_eos',
    'huawei_vrp': 'huawei_vrp',
    'h3c_comware': 'hp_comware',
    # ntc-templates 当前没有 ruijie_os 平台索引，临时回退到 Cisco 语法族做有限复用。
    'ruijie_rgos': 'cisco_ios',
}


# 按设备角色排除不适用的采集类别
# router: 不采集 mac_table（交换表是二层交换功能）
# access/switch: 不采集 bgp、ospf、bfd（纯接入层通常无路由协议邻居）
ROLE_EXCLUDED_CATEGORIES: dict[str, set[str]] = {
    'router': {'mac_table'},
    'access': {'bgp', 'ospf', 'bfd'},
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
    },
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
    catalog = COMMAND_CATALOG.get(platform) or COMMAND_CATALOG['cisco_ios']
    return {category: catalog.get(category, []) for category in categories}


def _build_connection_params(device_info: dict[str, Any], auth_role: str = 'normal') -> dict[str, Any]:
    platform = str(device_info.get('platform') or 'cisco_ios').lower()
    device_type = PLATFORM_DEVICE_TYPE_MAP.get(platform, 'cisco_ios')
    
    # PAM logic: select username/password based on role
    if auth_role == 'admin':
        username = device_info.get('admin_username') or device_info.get('username')
        password = device_info.get('admin_password') or device_info.get('password')
    else:
        # Default to normal user, but fallback to main credentials if missing
        username = device_info.get('normal_username') or device_info.get('username')
        password = device_info.get('normal_password') or device_info.get('password')

    params = {
        'device_type': device_type,
        'host': device_info.get('ip_address'),
        'username': username,
        'password': password,
        'port': int(device_info.get('port') or 22),
        'timeout': 20,
        'session_timeout': 60,
        'fast_cli': platform not in {'huawei_vrp', 'h3c_comware'},
        'global_delay_factor': 1.5 if platform in {'huawei_vrp', 'h3c_comware'} else 0.5,
        'blocking_timeout': 30,
    }
    params.update(build_netmiko_compatibility_kwargs())
    secret = device_info.get('enable_password') or device_info.get('secret') or ''
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
    parsed = parse_output(
        platform=_resolve_ntc_platform(platform),
        command=_normalize_command_for_template_match(command),
        data=output,
    )
    return _normalize_records(parsed)


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


def collect_operational_data(device_info: dict[str, Any], categories: list[str] | None = None, auth_role: str = 'normal') -> dict[str, Any]:
    role = str(device_info.get('role') or '').strip()
    selected_categories = _resolve_categories(categories, role=role)
    platform = str(device_info.get('platform') or 'cisco_ios').lower()
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


def collect_custom_command_data(device_info: dict[str, Any], command: str, auth_role: str = 'normal') -> dict[str, Any]:
    platform = str(device_info.get('platform') or 'cisco_ios').lower()
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