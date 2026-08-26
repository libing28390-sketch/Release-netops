from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from typing import Any

from netmiko import ConnectHandler
try:
    from netmiko.ssh_dispatcher import CLASS_MAP, CLASS_MAP_BASE
    from netmiko.cisco import CiscoIosSSH
    CLASS_MAP['dptech_ios'] = CiscoIosSSH
    CLASS_MAP_BASE['dptech_ios'] = CiscoIosSSH
except Exception:
    pass
from ntc_templates.parse import parse_output

from drivers.ssh_compat import build_netmiko_compatibility_kwargs
from services.network_access_limiter import limited_connect_handler
from services.neighbor_collection_contract import assert_lldp_command
from services.collection_plan_service import resolve_collection_plan


SUPPORTED_CATEGORIES = (
    'interfaces',
    'neighbors',
    'arp',
    'mac_table',
    'vlan',
    'routing_table',
    'bgp',
    'ospf',
    'eigrp',
    'isis',
    'stp',
    'rip',
    'bfd',
    'bgp_routes',
    'ntp',
    'environment',
    'fan',
    'power',
    'stack',
    'transceiver',
    'eth_trunk',
    'version',
    'logs',
    'interface_description',
    'uptime',
    'clock',
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
    # These are private Profile-release selectors used only when a collector
    # already knows the concrete V5/V7/V9 grammar. Persisted devices still use
    # the public ``h3c_comware`` platform plus a concrete Platform Profile.
    'h3c_comware_v5': 'hp_comware',
    'h3c_comware_v7': 'hp_comware',
    'h3c_comware_v9': 'hp_comware',
    'huawei': 'huawei',
    'vrp': 'huawei',
    'ce': 'huawei',
    'ce_vrp': 'huawei',
    'ne': 'huawei',
    '\u534e\u4e3avrp': 'huawei',
    'h3c_comware': 'hp_comware',
    'ruijie_rgos': 'ruijie_os',
    'ruijie_os': 'ruijie_os',
    'ruijie': 'ruijie_os',
    'rgos': 'ruijie_os',
    'zte_zxros': 'zte_zxros',
    'zte': 'zte_zxros',
    'zxros': 'zte_zxros',
    'maipu': 'maipu',
    'maipu_network': 'maipu',
    'dptech': 'dptech_ios',
    'dptech_ios': 'dptech_ios',
    'dptech_conplat': 'dptech_ios',
    'dptech_conplat_fw': 'dptech_ios',
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
    # H3C/Comware is one parser family.  V5/V7/V9 grammar selection is owned
    # by the platform profile and its registered template version.
    'h3c_comware_v5': 'h3c_comware',
    'h3c_comware_v7': 'h3c_comware',
    'h3c_comware_v9': 'h3c_comware',
    'huawei': 'huawei_vrp',
    'vrp': 'huawei_vrp',
    'ce': 'huawei_vrp',
    'ce_vrp': 'huawei_vrp',
    'ne': 'huawei_vrp',
    '\u534e\u4e3avrp': 'huawei_vrp',
    'h3c_comware': 'h3c_comware',
    'h3c': 'h3c_comware',
    'comware': 'h3c_comware',
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
    'h3c_comware_v7': 'h3c_comware',
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
    'maipu': 'maipu',
    'maipu_mypower': 'maipu',
    'maipu_network': 'maipu',
    'dptech': 'dptech_ios',
    'dptech_conplat': 'dptech_ios',
    'dptech_conplat_fw': 'dptech_ios',
}


def _normalize_platform(raw: str) -> str:
    """Normalize a raw platform string to a canonical COMMAND_CATALOG key."""
    p = str(raw or '').lower().strip()
    return _PLATFORM_ALIAS.get(p, p)


_H3C_PROFILE_VARIANTS = {
    'hp_comware': 'h3c_comware_v5',
    'h3c_comware': 'h3c_comware_v7',
    'h3c_comware9': 'h3c_comware_v9',
    'h3c_comware_v5': 'h3c_comware_v5',
    'h3c_comware_v7': 'h3c_comware_v7',
    'h3c_comware_v9': 'h3c_comware_v9',
}

_PROFILE_PARSER_VARIANTS = {
    **_H3C_PROFILE_VARIANTS,
    'huawei_vrp5': 'huawei_vrp5',
    'huawei_vrp8': 'huawei_vrpv8',
    'huawei_vrp_unknown': 'huawei_vrp_unknown',
    'h3c_comware_unknown': 'h3c_comware_unknown',
    'maipu_mypower_v6': 'maipu_mypower_v6',
    'maipu_mypower_v8': 'maipu_mypower_v8',
    'maipu_mypower_v9': 'maipu_mypower_v9',
    'maipu_mypower_unknown': 'maipu_mypower_unknown',
    'ruijie_rgos_v10': 'ruijie_rgos_v10',
    'ruijie_rgos_v11': 'ruijie_rgos_v11',
    'ruijie_rgos_v12': 'ruijie_rgos_v12',
    'ruijie_rgos_unknown': 'ruijie_rgos_unknown',
    'zte_zxros': 'zte_zxros',
    'zte_rosng': 'zte_rosng',
    'zte_os_unknown': 'zte_os_unknown',
    'dptech_conplat': 'dptech_conplat',
    'dptech_conplat_unknown': 'dptech_conplat_unknown',
}


def _load_platform_profile_context(device_info: dict[str, Any]) -> dict[str, Any]:
    """Load the concrete platform profile when a caller only has a device row.

    Device records intentionally keep the public platform family (for example
    ``h3c_comware``).  The bound profile is the authoritative source for the
    concrete V5/V7/V9 grammar.  This lookup is best-effort so old/unbound
    devices and fixture callers keep working without a registry schema.
    """
    profile = {
        'platform_code': device_info.get('profile_platform_code') or device_info.get('platform_code'),
        'parser_platform': device_info.get('profile_parser_platform') or device_info.get('parser_platform'),
        'connection_driver': device_info.get('profile_connection_driver') or device_info.get('connection_driver'),
    }
    profile_id = str(device_info.get('platform_profile_id') or '').strip()
    if profile_id and not profile.get('platform_code'):
        try:
            from database import get_db_connection
            conn = get_db_connection()
            try:
                row = conn.execute(
                    'SELECT platform_code, parser_platform, connection_driver '
                    'FROM platform_profiles WHERE id = ?',
                    (profile_id,),
                ).fetchone()
                if row:
                    profile.update({
                        'platform_code': row['platform_code'],
                        'parser_platform': row['parser_platform'],
                        'connection_driver': row['connection_driver'],
                    })
            finally:
                conn.close()
        except Exception:
            # A platform profile is an enhancement to the legacy device row;
            # failure to read it must not turn a read-only command into a
            # connection failure.
            pass
    return {key: str(value or '').strip().lower() for key, value in profile.items()}


def resolve_device_platform_context(device_info: dict[str, Any]) -> dict[str, Any]:
    """Resolve the deterministic transport, catalog, and parser identities.

    ``public_platform`` is the value exposed by inventory.  ``catalog_platform``
    selects the command catalog and ``parser_platform`` selects the concrete
    TextFSM namespace.  In particular, all three H3C profiles use Netmiko's
    ``hp_comware`` driver but select independent V5/V7/V9 template namespaces.
    """
    from core.platform_utils import normalize_device_platform
    from core.textfsm import resolve_textfsm_parser_platform, resolve_textfsm_platform

    raw_platform = str(device_info.get('platform') or '').strip().lower()
    profile = _load_platform_profile_context(device_info)
    profile_code = profile['platform_code']
    profile_parser = profile['parser_platform']
    vendor = str(device_info.get('vendor') or '').strip().lower()

    public_platform = normalize_device_platform(vendor, raw_platform or profile_parser or profile_code or 'cisco_ios')
    if raw_platform in {'hp_comware', 'h3c_comware9'} or profile_code in _H3C_PROFILE_VARIANTS:
        public_platform = 'h3c_comware'

    # The concrete profile code (hp_comware / h3c_comware9) outranks the
    # shared parser family.  Otherwise every H3C device carrying the family
    # value ``h3c_comware`` would be incorrectly routed to the V7 grammar.
    explicit_candidates = (profile_code, profile_parser, raw_platform, public_platform)
    parser_platform = next(
        (_PROFILE_PARSER_VARIANTS[item] for item in explicit_candidates if item in _PROFILE_PARSER_VARIANTS),
        '',
    )
    if not parser_platform:
        version = (
            device_info.get('platform_version')
            or device_info.get('software_version')
            or device_info.get('version')
            or ''
        )
        parser_platform = resolve_textfsm_parser_platform(
            profile_parser or raw_platform or public_platform,
            str(version),
        ) or profile_parser or raw_platform or public_platform

    # A system profile code is also the command-catalog variant.  For a
    # generic/custom profile, use its declared parser family instead of
    # inventing a command catalog from the tenant-specific profile name.
    catalog_platform = next(
        (item for item in (profile_code, parser_platform, profile_parser, raw_platform, public_platform)
         if item in COMMAND_CATALOG),
        public_platform,
    )
    parser_family = resolve_textfsm_platform(parser_platform) or parser_platform
    return {
        'raw_platform': raw_platform,
        'public_platform': public_platform,
        'catalog_platform': catalog_platform,
        'parser_platform': parser_platform,
        'parser_family': parser_family,
        'profile_platform_code': profile_code,
        'connection_driver': profile['connection_driver'] or raw_platform,
    }


def parse_device_cli_output(
    device_info: dict[str, Any],
    command: str,
    output: str,
    *,
    max_records: int | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse one device response using its concrete profile and exact command.

    This is intentionally independent of the legacy parser-template registry.
    A missing or non-matching template is a parse status, not a command
    execution failure; callers can always display the original CLI output.
    """
    selected_context = context or resolve_device_platform_context(device_info)
    from core.textfsm import get_template_content, smart_parse_cli, template_action_code

    try:
        result = smart_parse_cli(
            output=str(output or ''),
            command=str(command or ''),
            platform=selected_context['parser_platform'],
            version=str(device_info.get('version') or device_info.get('software_version') or ''),
            model=str(device_info.get('model') or ''),
        )
        records = _normalize_records(result.get('data') or [])
        if max_records is not None:
            records = records[:max(0, int(max_records))]
        template = str(result.get('template') or '').strip()
        associated_action = ''
        if template:
            try:
                template_content, _ = get_template_content(template)
                associated_action = template_action_code(template_content)
            except Exception:
                associated_action = ''
        device_message = str(result.get('message') or '')
        if not result.get('success', True) and device_message.startswith('设备返回错误回显'):
            parse_status = 'device_error'
        else:
            parse_status = 'matched' if records else 'unmatched'
        parser = f"textfsm:{template}" if template else 'platform-parser'
        return {
            'records': records,
            'count': len(records),
            'parser': parser,
            'template': template or None,
            'template_source': result.get('template_source'),
            'template_action_code': associated_action or None,
            'parser_platform': selected_context['parser_platform'],
            'parser_family': selected_context['parser_family'],
            'parse_status': parse_status,
            'confidence': result.get('confidence', 0.0),
            'message': device_message,
        }
    except Exception as exc:
        logger.warning(
            'Automatic TextFSM parse failed platform=%s command=%s: %s',
            selected_context.get('parser_platform'), command, exc,
        )
        return {
            'records': [],
            'count': 0,
            'parser': 'platform-parser',
            'template': None,
            'template_source': None,
            'parser_platform': selected_context['parser_platform'],
            'parser_family': selected_context['parser_family'],
            'parse_status': 'failed',
            'confidence': 0.0,
            'message': str(exc),
        }

# 按设备角色排除不适用的采集类别
# router: 不采集 mac_table（交换表是二层交换功能）
# access/switch: 不采集 bgp、ospf、bfd（纯接入层通常无路由协议邻居）
ROLE_EXCLUDED_CATEGORIES: dict[str, set[str]] = {
    'router': {'mac_table', 'vlan'},
    'access': {'bgp', 'ospf', 'bfd', 'bgp_routes'},
}

COMMAND_CATALOG: dict[str, dict[str, list[str]]] = {
    'cisco_ios': {
        'interfaces': ['show ip interface brief'],
        'neighbors': ['show lldp neighbors'],
        'arp': ['show arp'],
        'mac_table': ['show mac address-table'],
        'vlan': ['show vlan brief'],
        'routing_table': ['show ip route'],
        'bgp': ['show ip bgp summary'],
        'ospf': ['show ip ospf neighbor'],
        'eigrp': ['show ip eigrp neighbors'],
        'isis': ['show isis neighbors'],
        'rip': ['show ip rip database'],
        'bfd': ['show bfd neighbors details'],
        'eth_trunk': ['show etherchannel summary'],
        'bgp_routes': ['show ip bgp'],
        'ntp': ['show ntp status'],
        'environment': ['show environment temperature'],
        'transceiver': ['show interfaces transceiver'],
        'version': ['show version'],
        'logs': ['show logging'],
        'interface_description': ['show interfaces description'],
        'uptime': ['show version'],
    },
    'dptech_ios': {
        'interfaces': ['show interface status'],
        'neighbors': ['show lldp neighbors'],
        'arp': ['show arp all'],
        'mac_table': ['show mac-address-table'],
        'vlan': ['show vlan'],
        'ntp': ['show ntp status'],
        'bfd': ['show bfd session'],
        'routing_table': ['show ip route'],
        'environment': ['show environment'],
        'version': ['show version'],
        'logs': ['show logging operlog recent'],
        'interface_description': ['show ip interface brief'],
        'clock': ['show clock'],
        'uptime': ['show version'],
    },
    'cisco_nxos': {
        'interfaces': ['show ip interface brief'],
        'neighbors': ['show lldp neighbors detail'],
        'arp': ['show ip arp'],
        'mac_table': ['show mac address-table'],
        'vlan': ['show vlan brief'],
        'routing_table': ['show ip route'],
        'bgp': ['show ip bgp summary'],
        'ospf': ['show ip ospf neighbors'],
        'isis': ['show isis neighbors'],
        'rip': ['show ip rip database'],
        'bfd': ['show bfd neighbors'],
        'eth_trunk': ['show port-channel summary'],
        'bgp_routes': ['show ip bgp'],
        'ntp': ['show ntp peer-status'],
        'environment': ['show environment'],
        'transceiver': ['show interface transceiver'],
        'version': ['show version'],
        'logs': ['show logging last 30'],
        'interface_description': ['show interface description'],
        'uptime': ['show version'],
    },
    'juniper_junos': {
        'interfaces': ['show interfaces terse'],
        'neighbors': ['show lldp neighbors'],
        'arp': ['show arp no-resolve'],
        'mac_table': ['show ethernet-switching table'],
        'vlan': ['show vlans'],
        'routing_table': ['show route'],
        'bgp': ['show bgp summary'],
        'ospf': ['show ospf neighbor'],
        'isis': ['show isis adjacency'],
        'rip': ['show rip neighbor'],
        'bfd': ['show bfd session'],
        'eth_trunk': ['show lacp interfaces'],
        'bgp_routes': ['show route protocol bgp'],
        'version': ['show version'],
        'logs': ['show log messages | last 30'],
        'interface_description': ['show interfaces descriptions'],
        'uptime': ['show system uptime'],
    },
    'arista_eos': {
        'interfaces': ['show ip interface brief'],
        'neighbors': ['show lldp neighbors detail'],
        'arp': ['show arp'],
        'mac_table': ['show mac address-table'],
        'vlan': ['show vlan'],
        'routing_table': ['show ip route'],
        'bgp': ['show ip bgp summary'],
        'ospf': ['show ip ospf neighbor'],
        'isis': ['show isis neighbors'],
        'rip': ['show ip rip'],
        'bfd': ['show bfd neighbors'],
        'eth_trunk': ['show port-channel summary'],
        'bgp_routes': ['show ip bgp'],
        'version': ['show version'],
        'logs': ['show logging'],
        'interface_description': ['show interfaces description'],
        'uptime': ['show version'],
    },
    'huawei_vrp': {
        'interfaces': ['display interface brief'],
        'neighbors': ['display lldp neighbor brief'],
        'arp': ['display arp all'],
        'mac_table': ['display mac-address'],
        'vlan': ['display vlan'],
        # VRP5 S-series returns the usable tabular RIB from the non-verbose
        # command; the verbose form is a different record-oriented view.
        'routing_table': ['display ip routing-table'],
        'bgp': ['display bgp peer'],
        'ospf': ['display ospf peer'],
        'isis': ['display isis peer'],
        'rip': ['display rip 1 neighbor'],
        'bfd': ['display bfd session all'],
        'bgp_routes': ['display bgp routing-table'],
        'ntp': ['display ntp-service status'],
        'environment': ['display environment'],
        # The published platform registry uses the full spelling as the
        # canonical command.  The parser still accepts historical ``dis``
        # output in fixtures, but new fallback sends must match the release
        # contract so legacy and registry paths cannot drift.
        'fan': ['dis fan'],
        'power': ['display power'],
        'stack': ['display stack'],
        'transceiver': ['display transceiver interface'],
        'eth_trunk': ['display eth-trunk'],
        'version': ['display version'],
        'logs': ['display logbuffer last 30'],
        'interface_description': ['display interface description'],
        'uptime': ['display version'],
    },
    'huawei_vrpv8': {
        'interfaces': ['display interface brief'],
        'neighbors': ['display lldp neighbor brief'],
        'arp': ['display arp all'],
        'mac_table': ['display mac-address'],
        'vlan': ['display vlan'],
        'routing_table': ['display ip routing-table verbose'],
        'bgp': ['display bgp peer'],
        'ospf': ['display ospf peer brief'],
        'isis': ['display isis peer'],
        'rip': ['display rip 1 neighbor'],
        'bfd': ['display bfd session all'],
        'bgp_routes': ['display bgp routing-table'],
        'ntp': ['display ntp status'],
        'environment': ['display temperature all'],
        'fan': ['display fan'],
        'power': ['display power'],
        'stack': ['display stack'],
        'transceiver': ['display transceiver interface'],
        'eth_trunk': ['display eth-trunk'],
        'version': ['display version'],
        'logs': ['display logbuffer last 30'],
        'interface_description': ['display interface description'],
        'uptime': ['display version'],
    },
    'h3c_comware': {
        'interfaces': ['display interface brief'],
        'neighbors': ['display lldp neighbor-information list'],
        'arp': ['display arp all'],
        'mac_table': ['display mac-address'],
        'vlan': ['display vlan brief'],
        'routing_table': ['display ip routing-table'],
        'bgp': ['display bgp peer ipv4 unicast'],
        'ospf': ['display ospf peer'],
        'isis': ['display isis peer'],
        'rip': ['display rip 1 neighbor'],
        'bfd': ['display bfd session'],
        'bgp_routes': ['display bgp routing-table ipv4'],
        'ntp': ['display ntp-service status'],
        'environment': ['display environment'],
        'fan': ['display fan'],
        'power': ['display power'],
        'stack': ['display irf'],
        'transceiver': ['display transceiver interface'],
        'eth_trunk': ['display link-aggregation verbose'],
        'version': ['display version'],
        'logs': ['display logbuffer'],
        'interface_description': ['display interface brief description'],
        'uptime': ['display version'],
    },
    # Profile-specific Comware V5 commands remain separate because the CLI
    # grammar differs from the shared V7/V9 family; this is not a public
    # platform namespace.
    'h3c_comware_v5': {
        'interfaces': ['display interface brief'],
        'neighbors': ['display lldp neighbor-information list'],
        'arp': ['display arp'],
        'mac_table': ['display mac-address'],
        'vlan': ['display vlan brief'],
        'routing_table': ['display ip routing-table'],
        # Comware V5 accepts the family command without the V7/V9 `unicast`
        # suffix. Keep this catalog separate from H3C Comware V7/V9 so a
        # parser template cannot be selected for the wrong CLI grammar.
        'bgp': ['display bgp peer ipv4'],
        'ospf': ['display ospf peer'],
        'bgp_routes': ['display bgp routing-table ipv4'],
        'ntp': ['display ntp-service status'],
        'environment': ['display environment'],
        'fan': ['display fan'],
        'power': ['display power'],
        'stack': ['display irf'],
        'transceiver': ['display transceiver interface'],
        'eth_trunk': ['display link-aggregation verbose'],
        'version': ['display version'],
        'logs': ['display logbuffer'],
        'interface_description': ['display interface brief description'],
        'uptime': ['display version'],
    },
    'h3c_comware_v9': {
        'interfaces': ['display interface brief'],
        'neighbors': ['display lldp neighbor-information list'],
        'arp': ['display arp all'],
        'mac_table': ['display mac-address'],
        'vlan': ['display vlan brief'],
        'routing_table': ['display ip routing-table'],
        'bgp': ['display bgp peer ipv4 unicast'],
        'ospf': ['display ospf peer'],
        'isis': ['display isis peer'],
        'rip': ['display rip 1 neighbor'],
        'bfd': ['display bfd session'],
        'bgp_routes': ['display bgp routing-table ipv4'],
        'ntp': ['display ntp-service status'],
        'environment': ['display environment'],
        'fan': ['display fan'],
        'power': ['display power'],
        'stack': ['display irf'],
        'transceiver': ['display transceiver interface'],
        'eth_trunk': ['display link-aggregation verbose'],
        'version': ['display version'],
        'logs': ['display logbuffer'],
        'interface_description': ['display interface brief description'],
        'uptime': ['display version'],
    },
    'ruijie_rgos': {
        'interfaces': ['show interface status'],
        'neighbors': ['show lldp neighbors'],
        'arp': ['show arp'],
        'vlan': ['show vlan'],
        'routing_table': ['show ip route'],
        'bgp':['show ip bgp neighbors'],
        'ospf':['show ip ospf neighbor'],
        'transceiver': ['show interfaces transceiver'],
        'environment': ['show temperature'],
        'bfd': ['show bfd neighbors'],
        'fan': ['show fan'],
        'cpu': ['show cpu'],
        'logs': ['show logging'],
        'power': ['show power'],
        'version': ['show version'],
        'ntp': ['show ntp status'],
        'interface_description': ['show ip interface brief'],
        'uptime': ['show version'],
    },
    # Keep registered domestic platforms isolated until an official output
    # fixture proves the command grammar for the exact platform family.
    'zte_zxros': {
        'interfaces': ['show interface brief'],
        'neighbors': ['show lldp neighbor'],
        'arp': ['show arp'],
        'mac_table': ['show mac table'],
        'vlan': ['show vlan'],
        'routing_table': ['show ip forwarding route'],
        'ospf': ['show ip ospf neighbor'],
        'bgp': ['show ip bgp neighbors'],
        'ntp': ['show ntp status'],
        'transceiver': ['show opticalinfo brief'],
        'environment': ['show temperature detail'],
        'fan': ['show fan'],
        'power': ['show power'],
        'version': ['show version'],
        'logs': ['show logging buffer almlog'],
        'interface_description': ['show ip interface brief'],
        'clock': ['show clock'],
        'uptime': ['show version'],
    },
    'maipu': {
        'interfaces': ['show interface switchport brief'],
        'neighbors': ['show lldp neighbors'],
        'arp': ['show arp'],
        'mac_table': ['show mac-address all'],
        'vlan': ['show vlan'],
        'routing_table': ['show ip route'],
        'transceiver': ['show optical all'],
        'environment': ['show environment'],
        'fan': ['show system fan'],
        'power': ['show system power'],
        'version': ['show version'],
        'interface_description': ['show ip interface brief'],
        'clock': ['show clock'],
        'ntp': ['show ntp status'],
        'uptime': ['show version'],
    },
}

# STP/MSTP is a separate operational category. Its records become
# L2_NEIGHBOR evidence with state/role/instance metadata; it never creates a
# PHYSICAL relation by itself.
_STP_COMMANDS = {
    'cisco_ios': ['show spanning-tree'],
    'cisco_nxos': ['show spanning-tree'],
    'arista_eos': ['show spanning-tree'],
    'huawei_vrp': ['display stp brief'],
    'huawei_vrpv8': ['display stp brief'],
    'h3c_comware': ['display stp brief'],
    'h3c_comware_v5': ['display stp brief'],
    'h3c_comware_v7': ['display stp brief'],
    'h3c_comware_v9': ['display stp brief'],
    'ruijie_rgos': ['show spanning-tree'],
    'zte_zxros': ['show spanning-tree'],
    'dptech_ios': ['show spanning-tree'],
    'maipu': ['show spanning-tree'],
    'juniper_junos': ['show spanning-tree bridge'],
}
for _platform_name, _commands in _STP_COMMANDS.items():
    COMMAND_CATALOG.setdefault(_platform_name, {})['stp'] = _commands


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_categories(
    categories: list[str] | None,
    role: str = '',
    device_info: dict[str, Any] | None = None,
    policy_override_categories: set[str] | None = None,
) -> list[str]:
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
    if device_info:
        plan = resolve_collection_plan(device_info)["effective"]
        category_to_collector = {
            "neighbors": "lldp",
            "routing_table": "routes",
            "bgp_routes": "bgp",
            "bgp": "bgp",
            "ospf": "ospf",
            "eigrp": "eigrp",
            "isis": "isis",
            "stp": "stp",
            "rip": "rip",
            "bfd": "bfd",
            "mac_table": "mac_table",
            "vlan": "vlan",
            "arp": "arp",
            "interfaces": "interface_status",
        }
        base = [
            category for category in base
            if category not in category_to_collector
            or category in (policy_override_categories or set())
            or bool(plan.get(category_to_collector[category], True))
        ]
    return base


def _resolve_commands(platform: str, categories: list[str]) -> dict[str, list[str]]:
    # Prefer the published action catalog for system profiles.  The action
    # catalog is the command source, not the TextFSM source: if a release has
    # no mapping yet, a known platform still gets its explicit catalog command
    # so a read-only collection can return raw output instead of failing at
    # the parser-registration boundary.
    normalized_platform = _normalize_platform(platform)
    catalog = COMMAND_CATALOG.get(normalized_platform, {})
    action_by_category = {
        'neighbors': 'get_lldp_neighbors', 'interfaces': 'get_interface_brief',
        'arp': 'get_arp_table', 'mac_table': 'get_mac_table', 'vlan': 'get_vlan_table',
        'routing_table': 'get_route_table', 'bgp': 'get_bgp_neighbors',
        'ospf': 'get_ospf_neighbors', 'isis': 'get_isis_neighbors', 'stp': 'get_stp',
        'eth_trunk': 'get_link_aggregation',
        'transceiver': 'get_transceivers', 'version': 'get_version',
        'environment': 'get_temperature', 'fan': 'get_fans', 'power': 'get_power',
        'ntp': 'get_ntp_status', 'bfd': 'get_bfd_sessions', 'logs': 'get_logbuffer',
        'interface_description': 'get_interface_description', 'uptime': 'get_uptime',
        'stack': 'get_irf',
    }
    from services.platform_registry_service import SYSTEM_PROFILES, resolve_action_mapping, normalize_platform_code
    canonical_profile = normalize_platform_code(normalized_platform)
    known_system_profile = any(item['platform_code'] == canonical_profile for item in SYSTEM_PROFILES)
    registry_available = False
    registry_profile_exists = False
    if known_system_profile:
        try:
            from database import get_db_connection
            registry_conn = get_db_connection()
            try:
                registry_conn.execute("SELECT 1 FROM platform_profiles LIMIT 1").fetchone()
                registry_available = True
                registry_profile_exists = bool(registry_conn.execute(
                    "SELECT 1 FROM platform_profiles WHERE platform_code = ? AND source = 'SYSTEM' LIMIT 1",
                    (canonical_profile,),
                ).fetchone())
            finally:
                registry_conn.close()
        except Exception:
            # A pre-migration process can still serve the legacy system catalog;
            # once m0072 exists, missing mappings remain explicitly unsupported.
            registry_available = False
    legacy_catalog_enabled = os.environ.get("LEGACY_COMMAND_CATALOG_ENABLED", "1").strip().lower() in {
        "1", "true", "yes", "on",
    }
    resolved: dict[str, list[str]] = {}
    for category in categories:
        action_code = action_by_category.get(category)
        if action_code and known_system_profile and registry_available and registry_profile_exists:
            try:
                resolved[category] = [resolve_action_mapping(canonical_profile, action_code)['command']]
            except Exception:
                resolved[category] = catalog.get(category, []) if legacy_catalog_enabled else []
        elif legacy_catalog_enabled:
            resolved[category] = catalog.get(category, [])
        else:
            resolved[category] = []
    for command in resolved.get('neighbors', []):
        # Catch catalog regressions before a transport session is opened.
        assert_lldp_command(normalized_platform, command, scenario_id='neighbor_lldp')
    return resolved


_REGISTRY_ACTION_BY_CATEGORY = {
    'neighbors': 'get_lldp_neighbors',
    'interfaces': 'get_interface_brief',
    'arp': 'get_arp_table',
    'mac_table': 'get_mac_table',
    'vlan': 'get_vlan_table',
    'routing_table': 'get_route_table',
    'bgp': 'get_bgp_neighbors',
    'bgp_routes': 'get_bgp_routes',
    'ospf': 'get_ospf_neighbors',
    'isis': 'get_isis_neighbors',
    'stp': 'get_stp',
    'eth_trunk': 'get_link_aggregation',
    'transceiver': 'get_transceivers',
    'version': 'get_version',
    'environment': 'get_temperature',
    'fan': 'get_fans',
    'power': 'get_power',
    'ntp': 'get_ntp_status',
    'bfd': 'get_bfd_sessions',
    'logs': 'get_logbuffer',
    'interface_description': 'get_interface_description',
    'uptime': 'get_uptime',
    'stack': 'get_irf',
}

_REGISTRY_VRF_ACTION_BY_CATEGORY = {
    'arp': 'get_arp_table_vrf',
    'mac_table': 'get_mac_table_vrf',
    'routing_table': 'get_route_table_vrf',
    'bgp': 'get_bgp_neighbors_vrf',
    'bgp_routes': 'get_bgp_routes_vrf',
}


def _collect_registry_categories(
    device_info: dict[str, Any],
    platform: str,
    categories: list[str],
    platform_action_session=None,
) -> dict[str, dict[str, Any]]:
    """Collect standard categories through the published platform resolver."""
    from services.platform_registry_service import PlatformRegistryError, execute_platform_action

    user = {
        'id': f"collector:{device_info.get('id') or 'unknown'}",
        'username': 'collector',
        'role': 'Operator',
        'tenant_id': device_info.get('tenant_id') or '',
    }
    results: dict[str, dict[str, Any]] = {}
    for category in categories:
        vrf = str(device_info.get('active_vrf') or device_info.get('vrf') or '').strip()
        action_code = _REGISTRY_VRF_ACTION_BY_CATEGORY.get(category) if vrf else None
        action_code = action_code or _REGISTRY_ACTION_BY_CATEGORY[category]
        category_result: dict[str, Any] = {
            'key': category,
            'success': False,
            'commands': [],
            'count': 0,
            'records': [],
            'raw_outputs': [],
            'parser': 'platform-registry',
            'parse_status': 'failed',
        }
        try:
            action_kwargs = {
                'user': user,
                'parameters': {'vrf': vrf} if vrf and action_code in _REGISTRY_VRF_ACTION_BY_CATEGORY.values() else None,
            }
            if platform_action_session is not None:
                action_kwargs['_session'] = platform_action_session
            # The quick-query surface must retain the raw command output for
            # platform-action-backed commands. In particular, a valid empty result
            # (for example, ``BFD is not configured.``) otherwise becomes an
            # ambiguous "no raw output" message in the UI even though the
            # action was executed successfully even when no direct template
            # matched the returned output.
            action_kwargs['include_raw_output'] = True
            result = execute_platform_action(str(device_info['id']), action_code, **action_kwargs)
            category_result['parser'] = result.get('parser') or category_result['parser']
            command = result.get('command')
            if command:
                category_result['commands'] = [command]
            raw_output = result.get('raw_output')
            if raw_output is not None:
                category_result['raw_outputs'] = [{'command': command, 'output': raw_output}]
            category_result['records'] = result.get('records') or []
            category_result['count'] = len(category_result['records'])
            # Action success means the read-only command completed.  Parsing
            # is reported independently so an absent/incorrect template does
            # not turn a valid device response into a transport failure.
            category_result['success'] = bool(result.get('success'))
            category_result['parse_status'] = result.get('parse_status') or (
                'matched' if category_result['records'] else 'unmatched'
            )
            if result.get('parser_platform'):
                category_result['parser_platform'] = result.get('parser_platform')
            if result.get('template'):
                category_result['template'] = result.get('template')
            if result.get('template_source'):
                category_result['template_source'] = result.get('template_source')
            if result.get('template_action_code'):
                category_result['template_action_code'] = result.get('template_action_code')
            category_result['parser_selection'] = result.get('parser_selection') or 'automatic'
            if result.get('parser_message'):
                category_result['parser_message'] = result.get('parser_message')
            category_result['platform_release_id'] = result.get('platform_release_id')
            category_result['release_checksum'] = result.get('release_checksum')
            category_result['command_checksum'] = result.get('command_checksum')
            if result.get('error'):
                category_result['error'] = result['error']
            if result.get('error_code'):
                category_result['error_code'] = result['error_code']
        except PlatformRegistryError as exc:
            category_result['error_code'] = exc.code
            category_result['error'] = exc.message
            category_result['parse_status'] = 'unsupported_by_platform' if exc.code == 'UNSUPPORTED_ACTION' else 'failed'
        except Exception as exc:
            category_result['error'] = str(exc)
        results[category] = category_result
    return results


def _first_complete_pair(*pairs: tuple[str, str]) -> tuple[str, str]:
    for username, password in pairs:
        if username and password:
            return username, password
    return '', ''


def _build_connection_params(device_info: dict[str, Any], auth_role: str = 'auto') -> dict[str, Any]:
    raw_p = str(device_info.get('platform') or '').lower().strip()
    raw_v = str(device_info.get('vendor') or '').lower().strip()
    platform = _normalize_platform(raw_p)
    device_type = PLATFORM_DEVICE_TYPE_MAP.get(platform) or PLATFORM_DEVICE_TYPE_MAP.get(raw_p)
    if not device_type or device_type in ('dptech_conplat', 'dptech_conplat_fw', 'dptech'):
        if 'dptech' in raw_p or 'dptech' in raw_v:
            device_type = 'dptech_ios'
        else:
            device_type = platform or 'cisco_ios'
    
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
        )
    elif role == 'normal':
        username, password = _first_complete_pair(
            (creds.get('normal_username') or '', creds.get('normal_password') or ''),
        )
    else:
        # Auto mode is read-only by default: prefer the normal asset role and
        # only use the admin role when explicitly available as a fallback.
        username, password = _first_complete_pair(
            (creds.get('normal_username') or '', creds.get('normal_password') or ''),
            (creds.get('admin_username') or '', creds.get('admin_password') or ''),
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
    """Resolve the secondary parser without crossing a vendor boundary.

    ``NTC_PLATFORM_MAP`` contains the platform families with a dedicated NTC
    grammar.  Older code used Cisco IOS as the catch-all value when an entry
    was missing, which could silently parse a recognised non-Cisco platform
    with the wrong column grammar (for example a DPtech variant).  The
    canonical Nexora/TextFSM platform is the only safe fallback; an unknown
    value is kept as-is so the caller reports an unmatched parse instead of
    manufacturing Cisco-shaped records.
    """
    normalized = str(platform or '').strip().lower()
    mapped = NTC_PLATFORM_MAP.get(normalized)
    if mapped:
        return mapped
    from core.textfsm import resolve_textfsm_platform
    return resolve_textfsm_platform(normalized) or normalized


def _normalize_records(parsed: Any) -> list[dict[str, Any]]:
    """Return parser records with stable, case-insensitive field names.

    Built-in and local TextFSM templates expose headers in uppercase while
    the raw-parser fallbacks use lowercase names.  Normalizing at this shared
    boundary keeps downstream collectors independent of the selected parser.
    """
    def normalize_record(item: Any) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {'value': item}
        return {
            str(key).strip().replace('-', '_').lower(): value
            for key, value in item.items()
        }

    if isinstance(parsed, list):
        return [normalize_record(item) for item in parsed]
    if isinstance(parsed, dict):
        return [normalize_record(parsed)]
    return []


def _normalize_bgp_route_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand Comware/Huawei TextFSM attribute tails into BGP columns.

    Comware's ``Path/Ogn`` tail collapses empty columns when it is captured as
    one TextFSM value. For example ``0                     0 65008i`` means
    MED=0, LocalPref=0, Weight=0, AS path=65008i. Normalize it once here so
    the DB writer and every API consumer see the same semantics.
    """
    expanded: list[dict[str, Any]] = []
    for original in records:
        record = dict(original)
        attributes = record.get('attributes') or record.get('ATTRIBUTES')
        has_route_identity = record.get('network') or record.get('prefix')
        if attributes and has_route_identity:
            tokens = str(attributes).split()
            numeric = lambda value: str(value).isdigit()
            if tokens and 'metric' not in record:
                record['metric'] = tokens[0] if numeric(tokens[0]) else 0
            if len(tokens) >= 4:
                if 'loc_pref' not in record:
                    record['loc_pref'] = tokens[1] if numeric(tokens[1]) else 0
                if 'weight' not in record:
                    record['weight'] = tokens[2] if numeric(tokens[2]) else 0
                if 'as_path' not in record:
                    record['as_path'] = ' '.join(tokens[3:])
            elif len(tokens) == 3:
                # H3C's compact form is MED, PrefVal, Path/Ogn when LocPrf
                # is blank; Cisco's equivalent is Metric, Weight, Path.
                if 'loc_pref' not in record:
                    record['loc_pref'] = 0
                if 'weight' not in record:
                    record['weight'] = tokens[1] if numeric(tokens[1]) else 0
                if 'as_path' not in record:
                    record['as_path'] = tokens[2]
            elif len(tokens) == 2:
                if 'loc_pref' not in record:
                    record['loc_pref'] = 0
                if 'weight' not in record:
                    record['weight'] = 0
                if 'as_path' not in record:
                    record['as_path'] = tokens[1]
            if 'attributes' not in record and 'ATTRIBUTES' in record:
                record['attributes'] = record.pop('ATTRIBUTES')

        flags = str(record.get('flags') or record.get('status') or '')
        if 'is_best' not in record:
            record['is_best'] = 1 if '>' in flags else 0
        if 'is_active' not in record:
            record['is_active'] = record['is_best']
        expanded.append(record)
    return expanded


def _normalize_command_for_template_match(command: str) -> str:
    return re.sub(r'\s+', ' ', str(command or '').strip()).lower()


def _parse_with_ntc(platform: str, command: str, output: str) -> list[dict[str, Any]]:
    from core.textfsm import resolve_textfsm_platform, smart_parse_cli
    parser_platform = resolve_textfsm_platform(platform) or platform
    # Pass the selected profile/variant through the parser.  The parser
    # returns the canonical public family in its result, but needs the
    # concrete variant while choosing V5/V7/V9 template files.
    res = smart_parse_cli(output=output, command=command, platform=platform)
    if res.get('success') and res.get('data'):
        return _normalize_records(res['data'])
    # IOS-XE and legacy platform aliases keep their asset/platform identity,
    # while TextFSM uses the canonical parser grammar family.
    ntc_platform = _resolve_ntc_platform(platform)
    if ntc_platform != parser_platform:
        res = smart_parse_cli(output=output, command=command, platform=ntc_platform)
        if res.get('success') and res.get('data'):
            return _normalize_records(res['data'])
    # Comware releases expose two incompatible interface tables.  The
    # catalog command is ``display interface brief`` for compatibility with
    # the standard brief grammar, while some S6850/Comware devices return the
    # IP-oriented table shown by ``display ip interface brief``.  Retry the
    # canonical alternate TextFSM grammar only when the first grammar did
    # not match; never replace a successful standard parse.
    if (
        resolve_textfsm_platform(platform) == 'h3c_comware'
        and _normalize_command_for_template_match(command) == 'display interface brief'
        and re.search(r'interface\s+physical', str(output or ''), re.IGNORECASE)
    ):
        alternate = smart_parse_cli(
            output=output,
            command='display ip interface brief',
            platform=platform,
        )
        if alternate.get('success') and alternate.get('data'):
            return _normalize_records(alternate['data'])
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


def _parse_dynamic_neighbor_raw(output: str, category: str) -> list[dict[str, Any]]:
    """Conservative fallback for EIGRP/IS-IS/RIP neighbor-style outputs."""
    records: list[dict[str, Any]] = []
    error_markers = ('invalid input', 'unrecognized', 'unknown command', 'not found', 'error')
    interface_pattern = re.compile(r'\b[A-Za-z][A-Za-z0-9./:-]*\d[A-Za-z0-9./:-]*\b')
    ipv4_pattern = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
    isis_id_pattern = re.compile(r'\b[0-9A-Fa-f]{2}(?:\.[0-9A-Fa-f]{4}){2}\b')
    state_pattern = re.compile(
        r'\b(full|up|down|init|established|active|inactive|adjacent|adjacency|two-way|loading|failed)\b',
        re.IGNORECASE,
    )

    for raw_line in str(output or '').splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if not line or any(marker in lowered for marker in error_markers):
            continue
        if any(header in lowered for header in ('neighbor', 'address', 'interface', 'holdtime', 'uptime', 'system id')):
            # Keep data rows such as "Neighbor 10.0.0.1 ..." out of the
            # header filter only when no peer token is present.
            if not ipv4_pattern.search(line) and not isis_id_pattern.search(line):
                continue

        peer_match = ipv4_pattern.search(line)
        if category == 'rip':
            via_match = re.search(r'\bvia\s+((?:\d{1,3}\.){3}\d{1,3})', line, re.IGNORECASE)
            peer = via_match.group(1) if via_match else (peer_match.group(0) if peer_match else '')
        elif peer_match:
            peer = peer_match.group(0)
        else:
            isis_match = isis_id_pattern.search(line)
            peer = isis_match.group(0) if isis_match else ''
        if not peer:
            continue

        interface_match = interface_pattern.search(line)
        state_match = state_pattern.search(line)
        records.append({
            'neighbor_id': peer,
            'address': peer,
            'state': state_match.group(1) if state_match else 'discovered',
            'interface': interface_match.group(0) if interface_match else '',
            'area_id': '0.0.0.0',
        })
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
    token_table_layout = False

    for raw_line in lines:
        # Cisco/Huawei style: "Network   Next Hop   Metric LocPrf Weight Path"
        if 'Network' in raw_line and 'Next Hop' in raw_line:
            col_network = raw_line.index('Network')
            col_nexthop = raw_line.index('Next Hop')
            token_table_layout = col_network == 0
            m_col = raw_line.find('Metric')
            col_metric = m_col if m_col != -1 else col_nexthop + 20
            lp_col = raw_line.find('LocPrf')
            col_locprf = lp_col if lp_col != -1 else col_metric + 7
            w_col = raw_line.find('Weight')
            col_weight = w_col if w_col != -1 else col_locprf + 7
            p_col = raw_line.find('Path')
            col_path = p_col if p_col != -1 else col_weight + 7
            break
        # H3C Comware style: "Network   NextHop   MED   LocPrf   PrefVal   Path/Ogn"
        if 'Network' in raw_line and 'NextHop' in raw_line:
            col_network = raw_line.index('Network')
            col_nexthop = raw_line.index('NextHop')
            token_table_layout = col_network == 0
            m_col = raw_line.find('MED')
            if m_col == -1:
                m_col = raw_line.find('Metric')
            col_metric = m_col if m_col != -1 else col_nexthop + 20
            lp_col = raw_line.find('LocPrf')
            col_locprf = lp_col if lp_col != -1 else col_metric + 7
            w_col = raw_line.find('PrefVal')
            if w_col == -1:
                w_col = raw_line.find('Weight')
            col_weight = w_col if w_col != -1 else col_locprf + 7
            p_col = raw_line.find('Path')
            col_path = p_col if p_col != -1 else col_weight + 7
            break

    # The status-flags field spans from column 0 up to (but not including) the
    # Network column.  Valid flag characters: * > s d h r i (space).
    # Cisco/Huawei/H3C status flags include external ``e`` and stale ``S``;
    # rejecting either flag silently drops otherwise valid BGP rows.
    flag_chars = set('*>sdhrifSeE?D ')
    past_header = False

    for raw_line in lines:
        # Wait until we pass the header line
        if not past_header:
            if 'Network' in raw_line and ('Next Hop' in raw_line or 'NextHop' in raw_line):
                past_header = True
            continue

        # Skip blank lines
        if not raw_line.strip():
            continue

        # ── Parse status flags (everything before col_network) ──
        # Some Huawei/Comware versions print ``Network`` at column zero,
        # while data rows still reserve leading status-flag columns. Tokenize
        # around the first CIDR token instead of treating ``* >e`` as prefix.
        if token_table_layout:
            tokens = raw_line.split()
            prefix_index = next(
                (idx for idx, token in enumerate(tokens)
                 if re.match(r'^\d{1,3}(?:\.\d{1,3}){3}/\d{1,3}$', token)),
                None,
            )
            if prefix_index is None or len(tokens) <= prefix_index + 1:
                continue
            prefix = tokens[prefix_index]
            next_hop = tokens[prefix_index + 1]
            try:
                ipaddress.ip_address(next_hop)
            except ValueError:
                continue
            attrs = tokens[prefix_index + 2:]
            if not attrs:
                continue
            numeric = lambda value: str(value).isdigit()
            metric = int(attrs[0]) if numeric(attrs[0]) else 0
            loc_pref = int(attrs[1]) if len(attrs) >= 4 and numeric(attrs[1]) else 0
            weight_index = 2 if len(attrs) >= 4 else 1
            weight = int(attrs[weight_index]) if len(attrs) > weight_index and numeric(attrs[weight_index]) else 0
            path_index = 3 if len(attrs) >= 4 else 2
            as_path = ' '.join(attrs[path_index:]) if len(attrs) > path_index else attrs[-1]
            flags = ''.join(tokens[:prefix_index])
            records.append({
                'prefix': prefix,
                'next_hop': next_hop,
                'metric': metric,
                'loc_pref': loc_pref,
                'weight': weight,
                'as_path': as_path,
                'is_best': 1 if '>' in flags else 0,
                'is_active': 1 if '>' in flags else 0,
                'status': flags or '*',
            })
            continue

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


def _parse_aggregation_raw(output: str, platform: str = '') -> list[dict[str, Any]]:
    """Fallback parser for Cisco/EOS/Juniper summaries without TextFSM."""
    records: list[dict[str, Any]] = []
    current_parent = ''
    for raw_line in str(output or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parent_match = re.search(r'(?i)(?:port-channel|portchannel|po|ae|bundle-ether)\s*(\d+)\s*\(([^)]*)\)', line)
        if parent_match:
            prefix = 'ae' if 'junos' in str(platform).lower() else ('Port-Channel' if 'arista' in str(platform).lower() else 'Port-channel')
            current_parent = f"{prefix}{parent_match.group(1)}"
            state = parent_match.group(2)
            remainder = line[parent_match.end():]
            members = re.findall(r'(?i)\b((?:gi|te|fa|et|eth|ethernet|xe|ge|et-\d[-/]\d+|[a-z]+-\d+/\d+/\d+)[\w./-]*)\(([^)]*)\)', remainder)
            for member, member_state in members:
                records.append({
                    'PORT_CHANNEL': current_parent,
                    'INTERFACE': member,
                    'STATUS': member_state or state,
                    'PROTOCOL': 'LACP' if re.search(r'(?i)lacp', line) else '',
                    'OPERATE_STATUS': 'up' if any(flag in (member_state or state).upper() for flag in ('P', 'S', 'U')) else 'down',
                })
            continue
        aggregate_match = re.search(r'(?i)(?:aggregated interface|aggregate interface|eth-trunk)\s*[: ]\s*(\S+)', line)
        if aggregate_match:
            current_parent = aggregate_match.group(1)
            continue
        if current_parent:
            member_match = re.match(r'(?i)([A-Za-z][\w./-]+)(?:\s+|\()', line)
            if member_match and not line.lower().startswith(('group', 'port-channel', 'flags', 'protocol')):
                member = member_match.group(1)
                if member.lower() not in {'local', 'remote', 'actor'}:
                    records.append({
                        'PORT_CHANNEL': current_parent,
                        'INTERFACE': member,
                        'STATUS': 'Selected' if re.search(r'(?i)selected|collecting|distributing|\(p\)', line) else 'Unselect',
                        'PROTOCOL': 'LACP' if re.search(r'(?i)lacp|collecting|distributing', line) else '',
                    })
    return records


def _parse_stp_raw(output: str, platform: str = '') -> list[dict[str, Any]]:
    """Parse common Cisco/Huawei/Comware STP and MSTP summary rows.

    The parser is intentionally conservative: a line must contain an
    interface and a forwarding/blocking state (or an explicit STP role). A
    partial bridge summary therefore cannot manufacture a topology edge.
    """
    records: list[dict[str, Any]] = []
    interface_pattern = re.compile(
        r'\b(?:Gi|Fa|Te|Eth|Ethernet|GE|XGigabitEthernet|GigabitEthernet|'
        r'ge-|xe-|et-|ae|Po|Port-channel|Bridge-Aggregation|Eth-Trunk)'
        r'[A-Za-z0-9./:-]*\d[A-Za-z0-9./:-]*\b',
        re.IGNORECASE,
    )
    state_pattern = re.compile(
        r'\b(FWD|FORWARDING|FORWARD|BLK|BLOCKING|DISCARDING|LEARN|LEARNING|'
        r'LISTEN|LISTENING|DOWN|UP|ACTIVE|INACTIVE)\b', re.IGNORECASE,
    )
    role_pattern = re.compile(
        r'\b(ROOT|DESG|DESIGNATED|ALTN|ALTERNATE|BACKUP|MASTER|DISCARDING)\b',
        re.IGNORECASE,
    )
    instance_pattern = re.compile(r'\b(?:MSTI?|INSTANCE|VLAN)\s*[-:]?\s*(\d+)\b', re.IGNORECASE)
    bridge_pattern = re.compile(r'\b(?:[0-9a-f]{4}\.){2}[0-9a-f]{4}\b', re.IGNORECASE)
    error_markers = ('invalid input', 'unrecognized', 'unknown command', 'not found', 'error')

    for raw_line in str(output or '').splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if not line or any(marker in lower for marker in error_markers):
            continue
        interface_match = interface_pattern.search(line)
        state_match = state_pattern.search(line)
        role_match = role_pattern.search(line)
        if not interface_match or (not state_match and not role_match):
            continue
        state = (state_match.group(1) if state_match else '').upper()
        state_aliases = {
            'FWD': 'forwarding', 'FORWARD': 'forwarding', 'FORWARDING': 'forwarding',
            'BLK': 'blocking', 'BLOCKING': 'blocking', 'DISCARDING': 'blocking',
            'LEARN': 'learning', 'LEARNING': 'learning', 'LISTEN': 'listening',
            'LISTENING': 'listening', 'UP': 'forwarding', 'DOWN': 'down',
            'ACTIVE': 'forwarding', 'INACTIVE': 'down',
        }
        role = (role_match.group(1).upper() if role_match else '')
        role_aliases = {'DESG': 'designated', 'DESIGNATED': 'designated', 'ROOT': 'root', 'ALTN': 'alternate', 'ALTERNATE': 'alternate', 'BACKUP': 'backup', 'MASTER': 'master'}
        record: dict[str, Any] = {
            'interface': interface_match.group(0),
            'state': state_aliases.get(state, state.lower() or 'discovered'),
            'role': role_aliases.get(role, role.lower()),
            'instance': (instance_pattern.search(line).group(1) if instance_pattern.search(line) else '0'),
        }
        bridge_match = bridge_pattern.search(line)
        if bridge_match:
            record['designated_bridge'] = bridge_match.group(0)
        records.append(record)
    return records


def _parse_command_output(platform: str, category: str, command: str, output: str) -> list[dict[str, Any]]:
    if category == 'stp':
        raw_stp = _parse_stp_raw(output, platform)
        if raw_stp:
            return raw_stp
    records: list[dict[str, Any]] = []
    try:
        records = _parse_with_ntc(platform, command, output)
    except Exception:
        records = []

    if category == 'bgp_routes':
        # The Huawei/H3C tabular RIB is more accurately parsed from column
        # positions than from a generic TextFSM attribute tail. Prefer this
        # canonical parser even when a legacy template returned rows.
        raw_bgp_routes = _parse_bgp_routes_raw(output, platform)
        if raw_bgp_routes:
            return raw_bgp_routes
        if records:
            return _normalize_bgp_route_records(records)

    if records:
        return records

    normalized_command = _normalize_command_for_template_match(command)
    if category == 'eth_trunk':
        return _parse_aggregation_raw(output, platform)

    if category == 'bfd' or ' bfd ' in f' {normalized_command} ':
        return _parse_bfd_raw(output)

    if category == 'routing_table':
        # Reuse the authoritative Huawei/H3C/Cisco route parser used by the
        # Network Source of Truth route collector. This keeps quick queries
        # and NSOT synchronized instead of returning an empty category when
        # no TextFSM template exists for the non-verbose Huawei table.
        try:
            from services.ip_locator_service import parse_routing_table
            return parse_routing_table(output, platform)
        except Exception:
            return []

    # bgp_routes must be checked BEFORE generic bgp to avoid misrouting
    if category == 'bgp_routes' or (' bgp ' in f' {normalized_command} ' and 'summary' not in normalized_command and 'peer' not in normalized_command):
        return _parse_bgp_routes_raw(output, platform)

    if category == 'bgp' or (' bgp ' in f' {normalized_command} ' and ('summary' in normalized_command or 'peer' in normalized_command)):
        return _parse_bgp_raw(output, platform)

    if category == 'ospf' or ' ospf ' in f' {normalized_command} ':
        return _parse_ospf_raw(output, platform)

    if category in {'eigrp', 'isis', 'rip'}:
        return _parse_dynamic_neighbor_raw(output, category)

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


def collect_operational_data(
    device_info: dict[str, Any],
    categories: list[str] | None = None,
    auth_role: str = 'auto',
    policy_override_categories: set[str] | None = None,
    _platform_action_session=None,
) -> dict[str, Any]:
    role = str(device_info.get('role') or '').strip()
    selected_categories = _resolve_categories(
        categories,
        role=role,
        device_info=device_info,
        policy_override_categories=policy_override_categories,
    )
    from core.platform_utils import normalize_device_platform
    raw_platform = str(device_info.get('platform') or 'cisco_ios').strip().lower()
    platform = normalize_device_platform(device_info.get('vendor'), raw_platform)
    # Persisted devices expose only the public ``h3c_comware`` platform.  A
    # direct caller may still pass an explicit release grammar selector for an
    # unbound collection/fixture path; keep that selector private to command
    # and parser lookup while the returned device identity stays canonical.
    parser_platform = (
        raw_platform
        if raw_platform in {'h3c_comware_v5', 'h3c_comware_v7', 'h3c_comware_v9'}
        else platform
    )
    commands_by_category = _resolve_commands(parser_platform, selected_categories)
    conn_params = _build_connection_params(device_info, auth_role=auth_role)


    payload: dict[str, Any] = _build_base_payload(device_info, platform)

    # A disabled capability must not open an SSH session just to return an
    # empty category list.  This is important for routers with BGP/OSPF
    # disabled and for servers receiving a network-only request by mistake.
    if not selected_categories:
        payload['summary'] = {
            'requested_categories': [],
            'successful_categories': 0,
            'failed_categories': 0,
            'total_records': 0,
        }
        return payload

    registry_bound = bool(device_info.get('id') and device_info.get('platform_profile_id'))
    registry_categories = [
        category for category in selected_categories
        if category in _REGISTRY_ACTION_BY_CATEGORY
    ] if registry_bound else []
    if registry_categories:
        payload['categories'].extend(
            _collect_registry_categories(
                device_info,
                platform,
                registry_categories,
                platform_action_session=_platform_action_session,
            ).values()
        )
    if registry_bound:
        # A bound device may only execute an action from its published
        # release.  Categories without a registered action are returned as an
        # explicit unsupported result; they must not open a legacy Netmiko
        # session with a vendor catalog command.
        for category in selected_categories:
            if category in registry_categories:
                continue
            payload['categories'].append({
                'key': category,
                'success': False,
                'commands': [],
                'count': 0,
                'records': [],
                'raw_outputs': [],
                'parser': 'platform-registry',
                'parse_status': 'unsupported_by_platform',
                'error_code': 'UNSUPPORTED_ACTION',
                'error': f'Category {category} has no published platform action',
            })
        legacy_categories = []
    else:
        legacy_categories = list(selected_categories)
    if not legacy_categories:
        payload['summary'] = {
            'requested_categories': selected_categories,
            'successful_categories': sum(1 for item in payload['categories'] if item.get('success')),
            'failed_categories': sum(1 for item in payload['categories'] if not item.get('success')),
            'total_records': sum(int(item.get('count') or 0) for item in payload['categories']),
        }
        return payload

    with limited_connect_handler(device_info, ConnectHandler, **conn_params) as client:
        if conn_params.get('secret'):
            try:
                client.enable()
            except Exception:
                pass

        for category in legacy_categories:
            category_commands = commands_by_category.get(category, [])
            category_result: dict[str, Any] = {
                'key': category,
                'success': True,
                'commands': category_commands,
                'count': 0,
                'records': [],
                'raw_outputs': [],
                'parser': 'ntc-templates',
                'parse_status': 'unmatched',
            }

            if not category_commands:
                category_result['success'] = True
                category_result['parse_status'] = 'unsupported_by_platform'
                category_result['message'] = f'Category {category} is not configured for platform {platform}'
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
                        records = _parse_command_output(parser_platform, category, command, output)
                        if records:
                            category_result['records'].extend(records)
                            category_result['count'] = len(category_result['records'])
                            category_result['parse_status'] = 'matched'
                    except Exception as parse_exc:
                        category_result.setdefault('parse_errors', []).append({
                            'command': command,
                            'error': str(parse_exc),
                        })
            except Exception as exc:
                category_result['success'] = False
                category_result['error'] = str(exc)
                category_result['parse_status'] = 'failed'

            payload['categories'].append(category_result)

    payload['summary'] = {
        'requested_categories': selected_categories,
        'successful_categories': sum(1 for item in payload['categories'] if item.get('success')),
        'failed_categories': sum(1 for item in payload['categories'] if not item.get('success')),
        'total_records': sum(int(item.get('count') or 0) for item in payload['categories']),
    }
    return payload


def collect_custom_command_data(device_info: dict[str, Any], command: str, auth_role: str = 'auto') -> dict[str, Any]:
    context = resolve_device_platform_context(device_info)
    platform = context['public_platform']
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
        'parser': 'platform-parser',
        'parser_platform': context['parser_platform'],
        'templates': [],
        'parse_status': 'unmatched',
    }

    with limited_connect_handler(device_info, ConnectHandler, **conn_params) as client:
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
                    parse_result = parse_device_cli_output(
                        device_info,
                        item,
                        output,
                        context=context,
                    )
                    records = parse_result['records']
                    category_result['parser'] = parse_result['parser']
                    category_result['parser_platform'] = parse_result['parser_platform']
                    if parse_result.get('template') and parse_result['template'] not in category_result['templates']:
                        category_result['templates'].append(parse_result['template'])
                    if parse_result['parse_status'] == 'failed' and category_result['parse_status'] != 'matched':
                        category_result['parse_status'] = 'failed'
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
