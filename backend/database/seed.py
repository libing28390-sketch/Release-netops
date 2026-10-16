import json
from .core import _beijing_now_iso

def _build_network_inspection_items(now: str) -> list[tuple]:
    """
    构建网络设备巡检指标（CLI 方式 + TextFSM 解析）。
    """
    items: list[tuple] = []

    def _item(id_, name, name_zh, category, check_key, desc, cmd, vendor,
              w, c, parse_type, textfsm_template, parse_field,
              parse_filter='', fallback_regex='', method='CLI'):
        items.append((
            id_, name, name_zh, category, check_key, desc,
            method, cmd, '',
            w, c, vendor, '', now, now,
            parse_type, textfsm_template, parse_field,
            parse_filter, fallback_regex, 1,
        ))

    def _snmp_item(id_, name, name_zh, category, check_key, desc, vendor, oid,
                   w, c, parse_type='numeric'):
        items.append((
            id_, name, name_zh, category, check_key, desc,
            'SNMP', '', '',
            w, c, vendor, oid, now, now,
            parse_type, '', '',
            '', '', 1,
        ))

    # Cisco IOS / IOS-XE
    _snmp_item('net_cisco_ios_cpu', 'Cisco IOS CPU', 'Cisco IOS CPU 利用率', 'Network', 'cisco_ios_cpu',
              'CPU 利用率 (SNMP)', 'cisco_ios', '1.3.6.1.4.1.9.9.109.1.1.1.1.8', 80, 90)
    _snmp_item('net_cisco_ios_mem', 'Cisco IOS Memory', 'Cisco IOS 内存利用率', 'Network', 'cisco_ios_mem',
              '内存利用率 (SNMP)', 'cisco_ios', '1.3.6.1.4.1.9.9.48.1.1.1.5', 80, 90)
    _snmp_item('net_cisco_ios_temp', 'Cisco IOS Temperature', 'Cisco IOS 温度', 'Network', 'cisco_ios_temp',
              '设备温度 (SNMP)', 'cisco_ios', '1.3.6.1.4.1.9.9.13.1.3.1.3', 55, 70)
    _snmp_item('net_cisco_ios_fan', 'Cisco IOS Fan', 'Cisco IOS 风扇状态', 'Network', 'cisco_ios_fan',
              '风扇状态 (SNMP)', 'cisco_ios', '1.3.6.1.4.1.9.9.13.1.4.1.3', None, None, 'status')
    _snmp_item('net_cisco_ios_psu', 'Cisco IOS PSU', 'Cisco IOS 电源状态', 'Network', 'cisco_ios_psu',
              '电源状态 (SNMP)', 'cisco_ios', '1.3.6.1.4.1.9.9.13.1.5.1.3', None, None, 'status')
    _snmp_item('net_cisco_ios_intf_down', 'Cisco IOS Interface Down', 'Cisco IOS 接口 Down 数', 'Network', 'cisco_ios_intf_down',
              '统计 down 的接口数量 (SNMP)', 'cisco_ios', '1.3.6.1.2.1.2.2.1.8', 1, 3, 'count')
    _item('net_cisco_ios_bgp_down', 'Cisco IOS BGP Peer Down', 'Cisco IOS BGP 邻居 Down 数', 'Network', 'cisco_ios_bgp_down',
          '通过标准 BGP4-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'show ip bgp summary', 'cisco_ios',
          1, 2, 'count', 'cisco_ios_show_ip_bgp_summary', 'STATE_OR_PREFIXES_RECEIVED',
          parse_filter='{"field":"STATE_OR_PREFIXES_RECEIVED","op":"not_numeric"}', method='SNMP')
    _item('net_cisco_ios_ospf_down', 'Cisco IOS OSPF Peer Down', 'Cisco IOS OSPF 邻居 Down 数', 'Network', 'cisco_ios_ospf_down',
          '通过标准 OSPF-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'show ip ospf neighbor', 'cisco_ios',
          1, 2, 'count', '', '', method='SNMP')
    _item('net_cisco_ios_route_total', 'Cisco IOS Route Total', 'Cisco IOS 路由总数', 'Network', 'cisco_ios_route_total',
          '路由总数（与上次对比，变化 >10% 告警）', 'show ip route summary', 'cisco_ios',
          10, 30, 'diff', 'cisco_ios_show_ip_route_summary', 'TOTAL_ROUTE_COUNT')

    # Cisco NX-OS
    _snmp_item('net_cisco_nxos_cpu', 'Cisco NX-OS CPU', 'Cisco NX-OS CPU 利用率', 'Network', 'cisco_nxos_cpu',
              'CPU 利用率 (SNMP)', 'cisco_nxos', '1.3.6.1.4.1.9.9.109.1.1.1.1.8', 80, 90)
    _snmp_item('net_cisco_nxos_mem', 'Cisco NX-OS Memory', 'Cisco NX-OS 内存利用率', 'Network', 'cisco_nxos_mem',
              '内存利用率 (SNMP)', 'cisco_nxos', '1.3.6.1.4.1.9.9.305.1.1.2.0', 80, 90)
    _snmp_item('net_cisco_nxos_temp', 'Cisco NX-OS Temperature', 'Cisco NX-OS 温度', 'Network', 'cisco_nxos_temp',
              '设备温度 (SNMP)', 'cisco_nxos', '1.3.6.1.4.1.9.9.91.1.1.1.1.4', 55, 70)
    _snmp_item('net_cisco_nxos_fan', 'Cisco NX-OS Fan', 'Cisco NX-OS 风扇状态', 'Network', 'cisco_nxos_fan',
              '风扇状态 (SNMP)', 'cisco_nxos', '1.3.6.1.4.1.9.9.117.1.4.1.1.1', None, None, 'status')
    _snmp_item('net_cisco_nxos_psu', 'Cisco NX-OS PSU', 'Cisco NX-OS 电源状态', 'Network', 'cisco_nxos_psu',
              '电源状态 (SNMP)', 'cisco_nxos', '1.3.6.1.4.1.9.9.117.1.1.2.1.2', None, None, 'status')
    _snmp_item('net_cisco_nxos_intf_down', 'Cisco NX-OS Interface Down', 'Cisco NX-OS 接口 Down 数', 'Network', 'cisco_nxos_intf_down',
              '统计 down 的接口数量 (SNMP)', 'cisco_nxos', '1.3.6.1.2.1.2.2.1.8', 1, 3, 'count')
    _item('net_cisco_nxos_bgp_down', 'Cisco NX-OS BGP Peer Down', 'Cisco NX-OS BGP 邻居 Down 数', 'Network', 'cisco_nxos_bgp_down',
          '通过标准 BGP4-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'show ip bgp summary', 'cisco_nxos',
          1, 2, 'count', 'cisco_nxos_show_ip_bgp_summary', 'STATE_PFXRCD',
          parse_filter='{"field":"STATE_PFXRCD","op":"not_numeric"}', method='SNMP')
    _item('net_cisco_nxos_ospf_down', 'Cisco NX-OS OSPF Peer Down', 'Cisco NX-OS OSPF 邻居 Down 数', 'Network', 'cisco_nxos_ospf_down',
          '通过标准 OSPF-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'show ip ospf neighbors', 'cisco_nxos',
          1, 2, 'count', '', '', method='SNMP')

    # 华为 VRPv5
    _snmp_item('net_huawei_vrp_cpu', '华为 VRPv5 CPU', '华为 VRPv5 CPU 利用率', 'Network', 'huawei_vrp_cpu',
              'CPU 利用率 (SNMP)', 'huawei_vrp', '1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5', 80, 90)
    _snmp_item('net_huawei_vrp_mem', '华为 VRPv5 Memory', '华为 VRPv5 内存利用率', 'Network', 'huawei_vrp_mem',
              '内存利用率 (SNMP)', 'huawei_vrp', '1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7', 80, 90)
    _snmp_item('net_huawei_vrp_temp', '华为 VRPv5 Temperature', '华为 VRPv5 温度', 'Network', 'huawei_vrp_temp',
              '设备温度 (SNMP)', 'huawei_vrp', '1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11', 55, 70)
    _snmp_item('net_huawei_vrp_fan', '华为 VRPv5 Fan', '华为 VRPv5 风扇状态', 'Network', 'huawei_vrp_fan',
              '风扇状态 (SNMP)', 'huawei_vrp', '1.3.6.1.4.1.2011.5.25.31.1.1.10.1.7', None, None, 'status')
    _snmp_item('net_huawei_vrp_psu', '华为 VRPv5 PSU', '华为 VRPv5 电源状态', 'Network', 'huawei_vrp_psu',
              '电源状态 (SNMP)', 'huawei_vrp', '1.3.6.1.4.1.2011.5.25.31.1.1.13.1.2', None, None, 'status')
    _snmp_item('net_huawei_vrp_intf_down', '华为 VRPv5 Interface Down', '华为 VRPv5 接口 Down 数', 'Network', 'huawei_vrp_intf_down',
              '统计 down 的接口数量 (SNMP)', 'huawei_vrp', '1.3.6.1.2.1.2.2.1.8', 1, 3, 'count')
    _item('net_huawei_vrp_bgp_down', '华为 VRPv5 BGP Peer Down', '华为 VRPv5 BGP 邻居 Down 数', 'Network', 'huawei_vrp_bgp_down',
          '通过标准 BGP4-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'display bgp peer', 'huawei_vrp',
          1, 2, 'count', 'huawei_vrp_display_bgp_peer', 'STATE',
          parse_filter='{"field":"STATE","op":"!=","value":"Established"}', method='SNMP')
    _item('net_huawei_vrp_ospf_down', '华为 VRPv5 OSPF Peer Down', '华为 VRPv5 OSPF 邻居 Down 数', 'Network', 'huawei_vrp_ospf_down',
          '通过标准 OSPF-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'display ospf peer brief', 'huawei_vrp',
          1, 2, 'count', '', '', method='SNMP')
    _item('net_huawei_vrp_route_total', '华为 VRPv5 Route Total', '华为 VRPv5 路由总数', 'Network', 'huawei_vrp_route_total',
          '路由总数（与上次对比）', 'display ip routing-table statistics', 'huawei_vrp',
          10, 30, 'diff', 'huawei_vrp_display_ip_routing_table_statistics', 'ACTIVE_COUNT',
          parse_filter='{"field":"PROTO","op":"==","value":"Total"}')

    # 华为 VRPv8
    _snmp_item('net_huawei_vrpv8_cpu', '华为 VRPv8 CPU', '华为 VRPv8 CPU 利用率', 'Network', 'huawei_vrpv8_cpu',
              'CPU 利用率 (SNMP)', 'huawei_vrpv8', '1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5', 80, 90)
    _snmp_item('net_huawei_vrpv8_mem', '华为 VRPv8 Memory', '华为 VRPv8 内存利用率', 'Network', 'huawei_vrpv8_mem',
              '内存利用率 (SNMP)', 'huawei_vrpv8', '1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7', 80, 90)
    _snmp_item('net_huawei_vrpv8_temp', '华为 VRPv8 Temperature', '华为 VRPv8 温度', 'Network', 'huawei_vrpv8_temp',
              '设备温度 (SNMP)', 'huawei_vrpv8', '1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11', 55, 70)
    _snmp_item('net_huawei_vrpv8_fan', '华为 VRPv8 Fan', '华为 VRPv8 风扇状态', 'Network', 'huawei_vrpv8_fan',
              '风扇状态 (SNMP)', 'huawei_vrpv8', '1.3.6.1.4.1.2011.5.25.31.1.1.10.1.7', None, None, 'status')
    _snmp_item('net_huawei_vrpv8_psu', '华为 VRPv8 PSU', '华为 VRPv8 电源状态', 'Network', 'huawei_vrpv8_psu',
              '电源状态 (SNMP)', 'huawei_vrpv8', '1.3.6.1.4.1.2011.5.25.31.1.1.13.1.2', None, None, 'status')
    _snmp_item('net_huawei_vrpv8_intf_down', '华为 VRPv8 Interface Down', '华为 VRPv8 接口 Down 数', 'Network', 'huawei_vrpv8_intf_down',
              '统计 down 的接口数量 (SNMP)', 'huawei_vrpv8', '1.3.6.1.2.1.2.2.1.8', 1, 3, 'count')
    _item('net_huawei_vrpv8_bgp_down', '华为 VRPv8 BGP Peer Down', '华为 VRPv8 BGP 邻居 Down 数', 'Network', 'huawei_vrpv8_bgp_down',
          '通过标准 BGP4-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'display bgp peer', 'huawei_vrpv8',
          1, 2, 'count', 'huawei_vrp_display_bgp_peer', 'STATE',
          parse_filter='{"field":"STATE","op":"!=","value":"Established"}', method='SNMP')
    _item('net_huawei_vrpv8_ospf_down', '华为 VRPv8 OSPF Peer Down', '华为 VRPv8 OSPF 邻居 Down 数', 'Network', 'huawei_vrpv8_ospf_down',
          '通过标准 OSPF-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'display ospf peer brief', 'huawei_vrpv8',
          1, 2, 'count', '', '', method='SNMP')
    _item('net_huawei_vrpv8_route_total', '华为 VRPv8 Route Total', '华为 VRPv8 路由总数', 'Network', 'huawei_vrpv8_route_total',
          '路由总数（与上次对比）', 'display ip routing-table statistics', 'huawei_vrpv8',
          10, 30, 'diff', 'huawei_vrp_display_ip_routing_table_statistics', 'ACTIVE_COUNT',
          parse_filter='{"field":"PROTO","op":"==","value":"Total"}')

    # H3C Comware
    _snmp_item('net_h3c_cpu', 'H3C Comware CPU', 'H3C Comware CPU 利用率', 'Network', 'h3c_comware_cpu',
              'CPU 利用率 (SNMP)', 'h3c_comware', '1.3.6.1.4.1.25506.2.6.1.1.1.1.6', 80, 90)
    _snmp_item('net_h3c_mem', 'H3C Comware Memory', 'H3C Comware 内存利用率', 'Network', 'h3c_comware_mem',
              '内存利用率 (SNMP)', 'h3c_comware', '1.3.6.1.4.1.25506.2.6.1.1.1.1.8', 80, 90)
    _snmp_item('net_h3c_temp', 'H3C Comware Temperature', 'H3C Comware 温度', 'Network', 'h3c_comware_temp',
              '设备温度 (SNMP)', 'h3c_comware', '1.3.6.1.4.1.25506.2.6.1.1.1.1.12', 55, 70)
    _snmp_item('net_h3c_fan', 'H3C Comware Fan', 'H3C Comware 风扇状态', 'Network', 'h3c_comware_fan',
              '风扇状态 (SNMP)', 'h3c_comware', '1.3.6.1.4.1.25506.2.6.1.1.1.1.19', None, None, 'status')
    _snmp_item('net_h3c_psu', 'H3C Comware PSU', 'H3C Comware 电源状态', 'Network', 'h3c_comware_psu',
              '电源状态 (SNMP)', 'h3c_comware', '1.3.6.1.4.1.25506.2.6.1.1.1.1.21', None, None, 'status')
    _snmp_item('net_h3c_intf_down', 'H3C Comware Interface Down', 'H3C Comware 接口 Down 数', 'Network', 'h3c_comware_intf_down',
              '统计 down 的接口数量 (SNMP)', 'h3c_comware', '1.3.6.1.2.1.2.2.1.8', 1, 3, 'count')
    _item('net_h3c_bgp_down', 'H3C Comware BGP Peer Down', 'H3C Comware BGP 邻居 Down 数', 'Network', 'h3c_comware_bgp_down',
          '通过标准 BGP4-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'display bgp peer ipv4 unicast', 'h3c_comware',
          1, 2, 'count', 'h3c_comware_v7_display_bgp_peer_ipv4_unicast', 'STATE',
          parse_filter='{"field":"STATE","op":"!=","value":"Established"}', method='SNMP')
    _item('net_h3c_ospf_down', 'H3C Comware OSPF Peer Down', 'H3C Comware OSPF 邻居 Down 数', 'Network', 'h3c_comware_ospf_down',
          '通过标准 OSPF-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'display ospf peer', 'h3c_comware',
          1, 2, 'count', '', '', method='SNMP')
    _item('net_h3c_route_total', 'H3C Comware Route Total', 'H3C Comware 路由总数', 'Network', 'h3c_comware_route_total',
          '路由总数（与上次对比）', 'display ip routing-table statistics', 'h3c_comware',
          10, 30, 'diff', 'h3c_comware_v7_display_ip_routing_table_statistics', 'ACTIVE',
          parse_filter='{"field":"PROTO","op":"==","value":"Total"}')

    # Juniper JunOS
    _snmp_item('net_juniper_cpu', 'Juniper JunOS CPU', 'Juniper JunOS CPU 利用率', 'Network', 'juniper_junos_cpu',
              'CPU 利用率 (SNMP)', 'juniper_junos', '1.3.6.1.4.1.2636.3.1.13.1.8', 80, 90)
    _snmp_item('net_juniper_mem', 'Juniper JunOS Memory', 'Juniper JunOS 内存利用率', 'Network', 'juniper_junos_mem',
              '内存利用率 (SNMP)', 'juniper_junos', '1.3.6.1.4.1.2636.3.1.13.1.11', 80, 90)
    _snmp_item('net_juniper_temp', 'Juniper JunOS Temperature', 'Juniper JunOS 温度', 'Network', 'juniper_junos_temp',
              '设备温度 (SNMP)', 'juniper_junos', '1.3.6.1.4.1.2636.3.1.13.1.7', 55, 70)
    _snmp_item('net_juniper_fan', 'Juniper JunOS Fan', 'Juniper JunOS 风扇状态', 'Network', 'juniper_junos_fan',
              '风扇状态 (SNMP)', 'juniper_junos', '1.3.6.1.4.1.2636.3.1.13.1.6', None, None, 'status')
    _snmp_item('net_juniper_psu', 'Juniper JunOS PSU', 'Juniper JunOS 电源状态', 'Network', 'juniper_junos_psu',
              '电源状态 (SNMP)', 'juniper_junos', '1.3.6.1.4.1.2636.3.1.13.1.6', None, None, 'status')
    _snmp_item('net_juniper_intf_down', 'Juniper JunOS Interface Down', 'Juniper JunOS 接口 Down 数', 'Network', 'juniper_junos_intf_down',
              '统计 down 的接口数量 (SNMP)', 'juniper_junos', '1.3.6.1.2.1.2.2.1.8', 1, 3, 'count')
    _item('net_juniper_bgp_down', 'Juniper JunOS BGP Peer Down', 'Juniper JunOS BGP 邻居 Down 数', 'Network', 'juniper_junos_bgp_down',
          '通过标准 BGP4-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'show bgp summary', 'juniper_junos',
          1, 2, 'count', '', '', method='SNMP')
    _item('net_juniper_ospf_down', 'Juniper JunOS OSPF Peer Down', 'Juniper JunOS OSPF 邻居 Down 数', 'Network', 'juniper_junos_ospf_down',
          '通过标准 OSPF-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'show ospf neighbor', 'juniper_junos',
          1, 2, 'count', '', '', method='SNMP')
    _item('net_juniper_route_total', 'Juniper JunOS Route Total', 'Juniper JunOS 路由总数', 'Network', 'juniper_junos_route_total',
          '路由总数（与上次对比）', 'show route summary', 'juniper_junos',
          10, 30, 'diff', 'juniper_junos_show_route_summary', 'ACTIVE_ROUTE_COUNT')

    # Arista EOS
    _snmp_item('net_arista_cpu', 'Arista EOS CPU', 'Arista EOS CPU 利用率', 'Network', 'arista_eos_cpu',
              'CPU 利用率 (SNMP)', 'arista_eos', '1.3.6.1.2.1.25.3.3.1.2', 80, 90)
    _snmp_item('net_arista_mem', 'Arista EOS Memory', 'Arista EOS 内存利用率', 'Network', 'arista_eos_mem',
              '内存利用率 (SNMP)', 'arista_eos', '1.3.6.1.2.1.25.2.3.1.6', 80, 90)
    _snmp_item('net_arista_temp', 'Arista EOS Temperature', 'Arista EOS 温度', 'Network', 'arista_eos_temp',
              '设备温度 (SNMP)', 'arista_eos', '1.3.6.1.2.1.99.1.1.1.4', 55, 70)
    _snmp_item('net_arista_fan', 'Arista EOS Fan', 'Arista EOS 风扇状态', 'Network', 'arista_eos_fan',
              '风扇状态 (SNMP)', 'arista_eos', '1.3.6.1.2.1.99.1.1.1.4', None, None, 'status')
    _snmp_item('net_arista_psu', 'Arista EOS PSU', 'Arista EOS 电源状态', 'Network', 'arista_eos_psu',
              '电源状态 (SNMP)', 'arista_eos', '1.3.6.1.2.1.99.1.1.1.4', None, None, 'status')
    _snmp_item('net_arista_intf_down', 'Arista EOS Interface Down', 'Arista EOS 接口 Down 数', 'Network', 'arista_eos_intf_down',
              '统计 down 的接口数量 (SNMP)', 'arista_eos', '1.3.6.1.2.1.2.2.1.8', 1, 3, 'count')
    _item('net_arista_bgp_down', 'Arista EOS BGP Peer Down', 'Arista EOS BGP 邻居 Down 数', 'Network', 'arista_eos_bgp_down',
          '通过标准 BGP4-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'show ip bgp summary', 'arista_eos',
          1, 2, 'count', '', '', method='SNMP')
    _item('net_arista_ospf_down', 'Arista EOS OSPF Peer Down', 'Arista EOS OSPF 邻居 Down 数', 'Network', 'arista_eos_ospf_down',
          '通过标准 OSPF-MIB 采集邻居状态，SNMP 不支持时回退 CLI', 'show ip ospf neighbor', 'arista_eos',
          1, 2, 'count', '', '', method='SNMP')

    # 合规检查指标（R8.1, R8.2）
    _item('compliance_cisco_ios_ntp', 'NTP Status', 'NTP 时钟同步状态', 'compliance', 'cisco_ios_ntp_status',
          '检查 NTP 是否同步', 'show ntp status', 'cisco_ios',
          None, None, 'status', '', 'CLOCK_STATE',
          fallback_regex=r'Clock is (synchronized|unsynchronized)')
    _item('compliance_cisco_ios_syslog', 'Syslog Config', 'Syslog 服务器配置', 'compliance', 'cisco_ios_syslog_count',
          '统计 logging host 配置数量，0 则告警', 'show logging', 'cisco_ios',
          1, None, 'count', 'cisco_ios_show_logging', 'LOGGING_HOST',
          fallback_regex=r'Logging to (\d+\.\d+\.\d+\.\d+)')
    _item('compliance_cisco_ios_aaa', 'AAA Config', 'AAA 认证配置', 'compliance', 'cisco_ios_aaa_status',
          '检查 aaa new-model 是否启用', 'show running-config | include aaa', 'cisco_ios',
          None, None, 'status', '', 'AAA_STATUS',
          fallback_regex=r'(aaa new-model)')
    _item('compliance_cisco_ios_telnet', 'Telnet Disabled', 'Telnet 服务禁用状态', 'compliance', 'cisco_ios_telnet_status',
          '检查 VTY 是否禁用 telnet', 'show line vty 0 4', 'cisco_ios',
          None, None, 'status', '', 'TRANSPORT_INPUT',
          fallback_regex=r'transport input\s+(\S+)')
    _item('compliance_cisco_ios_ssh_ver', 'SSH Version', 'SSH 版本检查', 'compliance', 'cisco_ios_ssh_version',
          '检查 SSH 版本是否为 2.0', 'show ip ssh', 'cisco_ios',
          None, None, 'status', 'cisco_ios_show_ip_ssh', 'SSH_VERSION',
          fallback_regex=r'SSH\s+.*?version\s+([\d.]+)')
    _item('compliance_cisco_ios_snmp', 'SNMP Community', 'SNMP 社区字符串安全性', 'compliance', 'cisco_ios_snmp_community',
          '检查是否使用 public/private 等不安全社区字符串', 'show snmp community', 'cisco_ios',
          None, None, 'status', '', 'COMMUNITY_STRING',
          fallback_regex=r'Community name:\s*(\S+)')

    return items


# Seed standard scripts
std_scripts = [
    ('std_linux_mem', 'Linux 内存使用率',
     r"""#!/bin/bash
# 计算内存使用率: (MemTotal - MemAvailable) / MemTotal * 100
# MemAvailable 自动剔除可回收 buffer/cache, 是 Linux 推荐口径 (kernel >= 3.14)
# 旧内核回退: MemAvailable 缺失时使用 MemFree + Buffers + Cached 估算
awk '/^MemTotal:/{t=$2}
     /^MemAvailable:/{a=$2; have_a=1}
     /^MemFree:/{f=$2}
     /^Buffers:/{b=$2}
     /^Cached:/{c=$2}
     END {
         if (!have_a) {
             a = f + b + c
         }
         if (t > 0) {
             printf "%.2f\n", (t - a) / t * 100
         } else {
             print 0
         }
     }' /proc/meminfo""",
     '计算系统内存使用百分比 (0-100)', 'Linux', 'standard'),

    ('std_linux_cpu', 'Linux CPU 使用率',
     r"""#!/bin/bash
# 提取 top 输出中的 idle%, 用 100 减去得到整体使用率
idle_pct=$(top -bn1 | grep "Cpu(s)" | sed 's/.*, *\([0-9.]*\)%* id.*/\1/')
awk -v idle="$idle_pct" 'BEGIN { printf "%.2f\n", 100 - idle }'""",
     '计算系统整体 CPU 使用率 (0-100)', 'Linux', 'standard'),

    ('std_linux_disk', 'Linux 全量磁盘空间',
     r"""#!/bin/bash
# 扫描所有本地挂载点,过滤虚拟分区,按使用率排序
echo "Detailed Disk Usage (Top 10):"
df -hP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | sort -k5 -rn | head -n 10

# 提取全局最大利用率作为判定值
max_usage=$(df -hP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | awk '{print $5}' | sed 's/%//' | sort -rn | head -1)
echo "MAX_UTILIZATION: ${max_usage:-0}"
""",
     '扫描所有本地分区，取最大利用率百分比', 'Linux', 'standard'),

    ('std_linux_inode', 'Linux 全量磁盘 Inode',
     r"""#!/bin/bash
# 扫描所有本地挂载点 Inode 使用率
echo "Detailed Inode Usage (Top 10):"
df -iP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | sort -k5 -rn | head -n 10

max_inode=$(df -iP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | awk '{print $5}' | sed 's/%//' | sort -rn | head -1)
echo "MAX_INODE_UTIL: ${max_inode:-0}"
""",
     '扫描所有本地分区，取最大 Inode 使用率', 'Linux', 'standard'),

    ('std_linux_iowait', 'Linux IO Wait 延迟',
     r"""#!/bin/bash
# 提取 CPU IO 等待比例 (取第二次采样,首次包含开机以来累计值)
iostat -c 1 2 | grep -v "avg-cpu" | tail -1 | awk '{print $4}'""",
     'CPU 等待磁盘 IO 时间占比 (0-100)', 'Linux', 'standard'),

    ('std_linux_swap', 'Linux Swap 使用率',
     r"""#!/bin/bash
free | grep Swap | awk '{if ($2>0) print ($3/$2)*100; else print 0}'""",
     '交换分区使用百分比 (0-100)', 'Linux', 'standard'),

    ('std_linux_load', 'Linux CPU 负载比例',
     r"""#!/bin/bash
# 计算 1min 负载与核心数的比值
cores=$(grep -c ^processor /proc/cpuinfo)
load=$(uptime | awk -F'load average:' '{print $2}' | cut -d, -f1 | xargs)
awk -v l="$load" -v c="$cores" 'BEGIN {
    if (c > 0) {
        printf "%.2f\n", (l / c) * 100
    } else {
        print 0
    }
}'""",
     '系统 1min 负载相对于核心数的比例', 'Linux', 'standard'),

    ('std_linux_conns', 'Linux TCP 连接数',
     r"""#!/bin/bash
ss -ant | grep ESTAB | wc -l""",
     '统计系统 Established 状态的 TCP 连接总数', 'Linux', 'standard'),

    ('std_linux_proc', 'Linux 关键进程巡检',
     r"""#!/bin/bash
# 检查指定的多个关键进程，返回丢失的数量
procs=${1:-"sshd crond docker"}
missing=0
for p in $procs; do
    if ! pgrep -f "$p" > /dev/null; then
        echo "[CRITICAL] Process not found: $p"
        missing=$((missing + 1))
    fi
done
echo "MISSING_COUNT: $missing"
""",
     '检查进程存活状态，返回未运行的进程数', 'Linux', 'standard'),

    ('std_linux_oom_events', 'Linux OOM Killer 事件数',
     r"""#!/bin/bash
dmesg 2>/dev/null | grep -iE "oom-killer|killed process" | wc -l
""",
     '统计内核日志中 OOM-killer 和 killed process 事件数量', 'Linux', 'standard'),

    ('std_linux_ro_mounts', 'Linux 只读挂载数',
     r"""#!/bin/bash
mount 2>/dev/null | grep -E '\(ro[,$]|\(,ro,' | wc -l
""",
     '统计当前处于只读状态的挂载文件系统数量', 'Linux', 'standard'),

    ('std_linux_kernel_errs', 'Linux 内核错误日志数',
     r"""#!/bin/bash
dmesg 2>/dev/null | tail -n 200 | grep -iE "critical|error|corrupt" | wc -l
""",
     '统计最近 200 行内核日志中的严重错误数量', 'Linux', 'standard'),

    ('std_linux_zombie_procs', 'Linux 僵尸进程数',
     r"""#!/bin/bash
ps -eo stat= 2>/dev/null | awk '$1 ~ /^Z/ {n++} END {print n+0}'
""",
     '统计当前处于僵尸状态的进程数量', 'Linux', 'standard'),

    ('std_linux_fd_util', 'Linux 文件句柄使用率',
     r"""#!/bin/bash
awk '{if ($3 > 0) printf "%.2f\n", ($1/$3)*100; else print 0}' /proc/sys/fs/file-nr 2>/dev/null
""",
     '计算已分配文件句柄数占系统上限的比例', 'Linux', 'standard'),

    ('std_linux_net_errs', 'Linux 网卡错误与丢包数',
     r"""#!/bin/bash
awk 'NR>2 {err+=$4+$5+$12+$13} END {print err+0}' /proc/net/dev 2>/dev/null
""",
     '统计所有网卡接收/发送 errors 和 dropped 的累计数量', 'Linux', 'standard'),

    ('std_linux_ntp_desync', 'Linux NTP 失步状态',
     r"""#!/bin/bash
ntp_desync=1
if chronyc tracking >/dev/null 2>&1; then
  chronyc tracking | grep -q "Reference ID" && ntp_desync=0
elif ntpq -p >/dev/null 2>&1; then
  ntpq -p | grep -q '^\*' && ntp_desync=0
fi
echo "$ntp_desync"
""",
     '检查本机 NTP 是否存在已同步的参考时钟（0=同步，1=失步/失败）', 'Linux', 'standard'),

    ('std_linux_dns_latency', 'Linux DNS 解析延迟',
     r"""#!/bin/bash
start_t=$(date +%s%3N 2>/dev/null || date +%s)
if getent hosts www.baidu.com >/dev/null 2>&1; then
  end_t=$(date +%s%3N 2>/dev/null || date +%s)
  diff=$((end_t - start_t))
  [ "$diff" -le 0 ] && diff=5
  echo "$diff"
else
  echo 9999
fi
""",
     '测量 DNS 解析延迟（毫秒），解析失败返回 9999', 'Linux', 'standard'),

    ('std_linux_recent_reboot', 'Linux 最近重启状态',
     r"""#!/bin/bash
awk '{print ($1 < 900) ? 1 : 0}' /proc/uptime 2>/dev/null
""",
     '检查系统是否在最近 15 分钟内重启（0=否，1=是）', 'Linux', 'standard'),

    ('std_linux_core_dumps_count', 'Linux Core Dump 文件数',
     r"""#!/bin/bash
crash_count=$(find /var/crash/ -type f 2>/dev/null | wc -l)
core_count=$(find /tmp/ -name "core.[0-9]*" 2>/dev/null | wc -l)
echo $((crash_count + core_count))
""",
     '统计 /var/crash 和 /tmp 中的 Core Dump 文件数量', 'Linux', 'standard'),

    ('std_linux_disk_io_await', 'Linux 磁盘 I/O Await 延迟',
     r"""#!/bin/bash
iostat -dx 1 2 2>/dev/null | awk '
  /^Device/ {
    for (i = 1; i <= NF; i++) {
      if ($i == "r_await") r = i
      if ($i == "w_await") w = i
    }
    next
  }
  r && w && $1 !~ /^(Linux|avg-cpu|Device)$/ && $1 ~ /^[[:alnum:]_.:-]+$/ {
    if ($r ~ /^[0-9.]+$/ && $w ~ /^[0-9.]+$/) {
      sum += ($r + $w) / 2
      count++
    }
  }
  END { if (count > 0) printf "%.2f\n", sum / count; else print 0 }
'
""",
     '计算设备平均读写 I/O await 延迟（毫秒）', 'Linux', 'standard'),

    ('std_linux_tcp_close_wait', 'Linux TCP CLOSE_WAIT 数',
     r"""#!/bin/bash
ss -ant 2>/dev/null | awk 'tolower($0) ~ /close-wait/ {n++} END {print n+0}'
""",
     '统计当前处于 CLOSE_WAIT 状态的 TCP 连接数量', 'Linux', 'standard'),

    ('std_linux_tcp_retrans_pct', 'Linux TCP 重传率',
     r"""#!/bin/bash
# TCP retransmission ratio over a one-second counter delta.
read_tcp_counters() {
  if command -v nstat >/dev/null 2>&1; then
    _nstat=$(nstat -az 2>/dev/null | awk '$1 == "TcpOutSegs" {out=$2} $1 == "TcpRetransSegs" {retr=$2} END {if (out ~ /^[0-9]+$/ && retr ~ /^[0-9]+$/) print out, retr}')
    if [ -n "$_nstat" ]; then
      echo "$_nstat"
      return
    fi
  fi
  awk '
    $1 == "Tcp:" {
      if (!header_seen) {
        header_seen = 1
        for (i = 2; i <= NF; i++) header[$i] = i
      } else {
        out = $(header["OutSegs"])
        retr = $(header["RetransSegs"])
      }
    }
    END {
      if (out ~ /^[0-9]+$/ && retr ~ /^[0-9]+$/) print out, retr
      else print 0, 0
    }
  ' /proc/net/snmp 2>/dev/null
}

read -r out_before retr_before < <(read_tcp_counters)
sleep 1
read -r out_after retr_after < <(read_tcp_counters)

delta_out=$((out_after - out_before))
delta_retr=$((retr_after - retr_before))
if [ "$delta_out" -gt 0 ] && [ "$delta_retr" -ge 0 ]; then
  tcp_retrans_pct=$(awk -v retrans="$delta_retr" -v out="$delta_out" 'BEGIN { printf "%.2f", (retrans / out) * 100 }')
else
  tcp_retrans_pct=0
fi
echo "tcp_retrans_pct:${tcp_retrans_pct:-0}"
""",
     '按一秒 TCP 计数器增量计算重传段比例（百分比）', 'Linux', 'standard'),

    ('std_linux_integrated', 'Linux 集成巡检脚本',
     r"""#!/bin/bash
# Linux 集成巡检脚本
cores=$(grep -c ^processor /proc/cpuinfo)
load=$(uptime | awk -F'load average:' '{print $2}' | cut -d, -f1 | xargs)
cpu_load=$(awk -v l="$load" -v c="$cores" 'BEGIN{ if(c>0) printf "%.2f\n", (l/c)*100; else print 0 }')
echo "cpu_load:$cpu_load"
cpu_util=$(top -bn1 | grep "Cpu(s)" | sed 's/.*, *\([0-9.]*\)%* id.*/\1/' | awk '{print 100 - $1}')
echo "cpu_util:$cpu_util"
mem_avail=$(awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2; have_a=1} /^MemFree:/{f=$2} /^Buffers:/{b=$2} /^Cached:/{c=$2} END{ if(!have_a) a=f+b+c; if(t>0) printf "%.2f\n",(t-a)/t*100; else print 0 }' /proc/meminfo)
echo "mem_avail:$mem_avail"
swap_util=$(free | grep Swap | awk '{if ($2>0) print ($3/$2)*100; else print 0}')
echo "swap_util:$swap_util"
io_wait=$(iostat -c 1 2 2>/dev/null | grep -v "avg-cpu" | tail -1 | awk '{print $4}')
if [ -z "$io_wait" ]; then
  io_wait=$(vmstat 1 2 | tail -1 | awk '{print $16}')
fi
echo "io_wait:${io_wait:-0}"
max_disk=$(df -hP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | awk '{print $5}' | sed 's/%//' | sort -rn | head -1)
echo "disk_util:${max_disk:-0}"
max_inode=$(df -iP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | awk '{print $5}' | sed 's/%//' | sort -rn | head -1)
echo "inode_util:${max_inode:-0}"
tcp_conns=$(ss -ant 2>/dev/null | grep ESTAB | wc -l)
echo "tcp_conns:$tcp_conns"
procs="sshd crond docker"
missing=0
for p in $procs; do
  if ! pgrep -f "$p" > /dev/null; then
    missing=$((missing + 1))
  fi
done
echo "process_health:$missing"
oom_events=$(dmesg 2>/dev/null | grep -iE "oom-killer|killed process" | wc -l)
echo "oom_events:$oom_events"
ro_mounts=$(mount 2>/dev/null | grep -E '\(ro[,$]|\(,ro,' | wc -l)
echo "ro_mounts:$ro_mounts"
kernel_errs=$(dmesg 2>/dev/null | tail -n 200 | grep -iE "critical|error|corrupt" | wc -l)
echo "kernel_errs:$kernel_errs"
zombie_procs=$(ps -ef | grep defunc | grep -v grep | wc -l)
echo "zombie_procs:$zombie_procs"
fd_util=$(cat /proc/sys/fs/file-nr 2>/dev/null | awk '{if ($3>0) printf "%.2f", ($1/$3)*100; else print 0}')
echo "fd_util:${fd_util:-0}"
net_errs=$(awk 'NR>2 {err+=$4+$5+$12+$13} END {print err}' /proc/net/dev 2>/dev/null)
echo "net_errs:${net_errs:-0}"
ntp_desync=1
if chronyc tracking &>/dev/null; then
  if chronyc tracking | grep -q "Reference ID"; then
    ntp_desync=0
  fi
elif ntpq -p &>/dev/null; then
  if ntpq -p | grep -q '^\*'; then
    ntp_desync=0
  fi
fi
echo "ntp_desync:$ntp_desync"
dns_latency=$(curl -o /dev/null -s -w '%{time_namelookup}' --connect-timeout 2 http://www.baidu.com 2>/dev/null | awk '{print $1 * 1000}')
if [ -z "$dns_latency" ] || [ "$dns_latency" = "0" ]; then
  start_t=$(date +%s%3N 2>/dev/null || date +%s)
  if getent hosts www.baidu.com &>/dev/null; then
    end_t=$(date +%s%3N 2>/dev/null || date +%s)
    diff=$((end_t - start_t))
    if [ $diff -eq 0 ]; then diff=5; fi
    dns_latency=$diff
  else
    dns_latency=9999
  fi
fi
echo "dns_latency:${dns_latency:-9999}"
uptime_s=$(cat /proc/uptime 2>/dev/null | awk '{print int($1)}')
recent_reboot=0
if [ ! -z "$uptime_s" ] && [ $uptime_s -lt 900 ]; then
  recent_reboot=1
fi
echo "recent_reboot:$recent_reboot"
core_dumps=$(find /var/crash/ -type f 2>/dev/null | wc -l)
core_files=$(find /tmp/ -name "core.[0-9]*" 2>/dev/null | wc -l)
echo "core_dumps_count:$((core_dumps + core_files))"
disk_io_await=$(iostat -dx 1 2 2>/dev/null | awk '/^[a-zA-Z0-9]/ {if ($10 ~ /^[0-9]/) {sum+=$10; count++}} END {if (count>0) printf "%.2f", sum/count; else print 0}')
echo "disk_io_await:${disk_io_await:-0}"
tcp_close_wait=$(ss -ant 2>/dev/null | grep -i "close-wait" | wc -l)
echo "tcp_close_wait:$tcp_close_wait"
# Use a short counter delta rather than the boot-time cumulative ratio.
read_tcp_counters() {
    if command -v nstat >/dev/null 2>&1; then
        _nstat=$(nstat -az 2>/dev/null | awk '$1 == "TcpOutSegs" {out=$2} $1 == "TcpRetransSegs" {retr=$2} END {if (out ~ /^[0-9]+$/ && retr ~ /^[0-9]+$/) print out, retr}')
        if [ -n "$_nstat" ]; then
            echo "$_nstat"
            return
        fi
    fi
    awk '
        $1 == "Tcp:" {
            if (!header_seen) {
                header_seen = 1
                for (i = 2; i <= NF; i++) header[$i] = i
            } else {
                out = $(header["OutSegs"])
                retr = $(header["RetransSegs"])
            }
        }
        END {
            if (out ~ /^[0-9]+$/ && retr ~ /^[0-9]+$/) print out, retr
            else print 0, 0
        }
    ' /proc/net/snmp 2>/dev/null
}
_tcp_before=$(read_tcp_counters)
sleep 1
_tcp_after=$(read_tcp_counters)
set -- $_tcp_before
_out_before=${1:-0}
_retr_before=${2:-0}
set -- $_tcp_after
_out_after=${1:-0}
_retr_after=${2:-0}
_delta_out=$((_out_after - _out_before))
_delta_retr=$((_retr_after - _retr_before))
if [ "$_delta_out" -gt 0 ] 2>/dev/null && [ "$_delta_retr" -ge 0 ] 2>/dev/null; then
    tcp_retrans_pct=$(awk -v r="$_delta_retr" -v o="$_delta_out" 'BEGIN { printf "%.2f", (r/o)*100 }')
else
    tcp_retrans_pct=0
fi
echo "tcp_retrans_pct:${tcp_retrans_pct:-0}"
""",
     '集成巡检脚本，采集 CPU负载、CPU使用率、内存使用率、交换分区、IOWait、磁盘空间、Inode、TCP连接、关键进程、OOM事件、只读文件系统、内核错误日志、僵尸进程、文件句柄、网络报错、NTP同步状态、DNS延迟、最近重启、CoreDump奔溃、磁盘IO await延迟、TCP CLOSE_WAIT泄漏、TCP重传率', 'Linux', 'standard'),

    # Cisco IOS / IOS-XE
    ('insp_cisco_ios_full', 'Cisco IOS 综合巡检', 'show version\nshow processes cpu sorted\nshow processes memory sorted\nshow environment temperature\nshow environment power all\nshow interfaces status\nshow ip bgp summary\nshow ip ospf neighbor\nshow ip route summary', 'Cisco IOS / IOS-XE 综合巡检脚本，覆盖 CPU/内存/温度/电源/接口/路由协议/路由数量', 'cisco_ios', 'inspection'),
    # Cisco NX-OS
    ('insp_cisco_nxos_full', 'Cisco NX-OS 综合巡检', 'show version\nshow processes cpu\nshow system resources\nshow environment\nshow interface brief\nshow ip bgp summary\nshow ip ospf neighbor\nshow ip route summary', 'Cisco NX-OS 综合巡检脚本，覆盖 CPU/内存/环境/接口/路由协议/路由数量', 'cisco_nxos', 'inspection'),
    # 华为 VRPv5
    ('insp_huawei_vrp_full', '华为 VRPv5 综合巡检', 'display version\ndisplay cpu-usage\ndisplay memory-usage\ndisplay temperature all\ndisplay fan\ndisplay power\ndisplay interface brief\ndisplay bgp peer\ndisplay ospf peer brief\ndisplay ip routing-table statistics', '华为 VRPv5（S系列/AR/老NE）综合巡检脚本', 'huawei_vrp', 'inspection'),
    # 华为 VRPv8
    ('insp_huawei_vrpv8_full', '华为 VRPv8 综合巡检', 'display version\ndisplay cpu-usage\ndisplay memory-usage\ndisplay environment\ndisplay interface brief\ndisplay bgp peer\ndisplay ospf peer brief\ndisplay ip routing-table statistics', '华为 VRPv8（CE系列/新NE）综合巡检脚本', 'huawei_vrpv8', 'inspection'),
    # H3C Comware
    ('insp_h3c_comware_full', 'H3C Comware 综合巡检', 'display version\ndisplay cpu-usage\ndisplay memory\ndisplay environment\ndisplay fan\ndisplay power\ndisplay interface brief\ndisplay bgp peer ipv4 unicast\ndisplay ospf peer\ndisplay ip routing-table statistics', 'H3C Comware V7/V9 综合巡检脚本', 'h3c_comware', 'inspection'),
    # Juniper JunOS
    ('insp_juniper_junos_full', 'Juniper JunOS 综合巡检', 'show version\nshow chassis routing-engine\nshow chassis environment\nshow interfaces terse\nshow bgp summary\nshow ospf neighbor\nshow route summary', 'Juniper JunOS 综合巡检脚本（MX/EX/QFX/SRX 通用）', 'juniper_junos', 'inspection'),
    # Arista EOS
    ('insp_arista_eos_full', 'Arista EOS 综合巡检', 'show version\nshow processes top once\nshow memory\nshow environment temperature\nshow environment power\nshow interfaces status\nshow ip bgp summary\nshow ip ospf neighbor\nshow ip route summary', 'Arista EOS 综合巡检脚本', 'arista_eos', 'inspection'),

    ('insp_linux_full', 'Linux 综合巡检',
     r"""#!/bin/bash
# ======================================================================
# Linux Server Comprehensive Health Inspection Script
# ======================================================================
export LC_ALL=C

LOAD_WARN_PCT=${NEXORA_LOAD_WARN_PCT:-80}
LOAD_CRIT_PCT=${NEXORA_LOAD_CRIT_PCT:-150}
CPU_WARN_PCT=${NEXORA_CPU_WARN_PCT:-90}
CPU_CRIT_PCT=${NEXORA_CPU_CRIT_PCT:-95}
MEM_WARN_PCT=${NEXORA_MEM_WARN_PCT:-85}
MEM_CRIT_PCT=${NEXORA_MEM_CRIT_PCT:-95}
SWAP_WARN_PCT=${NEXORA_SWAP_WARN_PCT:-70}
SWAP_CRIT_PCT=${NEXORA_SWAP_CRIT_PCT:-90}
DISK_WARN_PCT=${NEXORA_DISK_WARN_PCT:-90}
DISK_CRIT_PCT=${NEXORA_DISK_CRIT_PCT:-95}
INODE_WARN_PCT=${NEXORA_INODE_WARN_PCT:-90}
INODE_CRIT_PCT=${NEXORA_INODE_CRIT_PCT:-95}
IOWAIT_WARN_PCT=${NEXORA_IOWAIT_WARN_PCT:-15}
IOWAIT_CRIT_PCT=${NEXORA_IOWAIT_CRIT_PCT:-30}
IO_AWAIT_WARN_MS=${NEXORA_IO_AWAIT_WARN_MS:-20}
IO_AWAIT_CRIT_MS=${NEXORA_IO_AWAIT_CRIT_MS:-50}
TCP_RETRANS_WARN_PCT=${NEXORA_TCP_RETRANS_WARN_PCT:-2}
TCP_RETRANS_CRIT_PCT=${NEXORA_TCP_RETRANS_CRIT_PCT:-5}
TCP_TIME_WAIT_WARN=${NEXORA_TCP_TIME_WAIT_WARN:-1000}
TCP_TIME_WAIT_CRIT=${NEXORA_TCP_TIME_WAIT_CRIT:-2000}
TCP_CLOSE_WAIT_WARN=${NEXORA_TCP_CLOSE_WAIT_WARN:-50}
TCP_CLOSE_WAIT_CRIT=${NEXORA_TCP_CLOSE_WAIT_CRIT:-200}
FD_WARN_PCT=${NEXORA_FD_WARN_PCT:-80}
FD_CRIT_PCT=${NEXORA_FD_CRIT_PCT:-90}
DNS_PROBE_NAME=${NEXORA_DNS_PROBE_NAME:-}
DNS_WARN_MS=${NEXORA_DNS_WARN_MS:-1000}
DNS_CRIT_MS=${NEXORA_DNS_CRIT_MS:-5000}
NTP_WARN_OFFSET_MS=${NEXORA_NTP_WARN_OFFSET_MS:-1000}
NTP_CRIT_OFFSET_MS=${NEXORA_NTP_CRIT_OFFSET_MS:-5000}
SSH_FAIL_WARN_COUNT=${NEXORA_SSH_FAIL_WARN_COUNT:-20}
SSH_FAIL_CRIT_COUNT=${NEXORA_SSH_FAIL_CRIT_COUNT:-100}
SSH_IGNORE_IPS=${NEXORA_SSH_IGNORE_IPS:-}

TOTAL_ERRORS=0
TOTAL_WARNINGS=0
TOTAL_UNCHECKED=0

float_ge() {
    awk -v left="$1" -v right="$2" 'BEGIN { if (left ~ /^-?[0-9]+([.][0-9]+)?$/ && right ~ /^-?[0-9]+([.][0-9]+)?$/ && left + 0 >= right + 0) exit 0; exit 1 }'
}

now_ms() {
    local value
    value=$(date +%s%3N 2>/dev/null)
    if [[ "$value" =~ ^[0-9]+$ ]]; then
        printf '%s' "$value"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c 'import time; print(time.time_ns() // 1000000)' 2>/dev/null
    else
        printf 'NA'
    fi
}

print_section_header() {
    local status="$1"
    local title="$2"
    echo "======================================================================"
    echo "[$status] $title"
    echo "----------------------------------------------------------------------"
}

# 1. 系统基本运行状态 (System Basic Info)
print_section_header "SUCCESS" "1. 系统基本运行状态 (System Basic Info)"
hostname=$(hostname)
os_version=$(cat /etc/os-release 2>/dev/null | grep -i PRETTY_NAME | cut -d'"' -f2)
if [ -z "$os_version" ]; then
    os_version=$(uname -sr)
fi
kernel_version=$(uname -r)
uptime_info=$(uptime -p 2>/dev/null)
if [ -z "$uptime_info" ]; then
    uptime_info=$(uptime | awk -F',  ' '{print $1}')
fi
system_time=$(date "+%Y-%m-%d %H:%M:%S %Z")

echo "主机名称: ${hostname}"
echo "操作系统: ${os_version}"
echo "内核版本: ${kernel_version}"
echo "运行时间: ${uptime_info}"
echo "系统时间: ${system_time}"

# 2. CPU 利用率与系统负载 (CPU & Load)
cpu_cores=$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || grep -c '^processor' /proc/cpuinfo)
cpu_cores=${cpu_cores:-1}
load_avg=$(awk '{print $1", "$2", "$3}' /proc/loadavg 2>/dev/null)
load_1min=$(awk '{print $1}' /proc/loadavg 2>/dev/null)
load_pct=$(awk -v l="${load_1min:-0}" -v c="$cpu_cores" 'BEGIN { if (c>0) printf "%.2f", (l/c)*100; else print "NA" }')

read_cpu_counters() {
    awk '/^cpu / { total=0; for (i=2; i<=9; i++) total+=$i; idle=$5; iowait=$6; print total, idle, iowait; exit }' /proc/stat 2>/dev/null
}
cpu_before=$(read_cpu_counters)
sleep 2
cpu_after=$(read_cpu_counters)
set -- $cpu_before
cpu_total_before=${1:-0}; cpu_idle_before=${2:-0}; cpu_wait_before=${3:-0}
set -- $cpu_after
cpu_total_after=${1:-0}; cpu_idle_after=${2:-0}; cpu_wait_after=${3:-0}
cpu_total_delta=$((cpu_total_after - cpu_total_before))
cpu_idle_delta=$((cpu_idle_after - cpu_idle_before))
cpu_wait_delta=$((cpu_wait_after - cpu_wait_before))
cpu_util="NA"
cpu_iowait="NA"
if [ "$cpu_total_delta" -gt 0 ] 2>/dev/null; then
    cpu_util=$(awk -v t="$cpu_total_delta" -v i="$cpu_idle_delta" -v w="$cpu_wait_delta" 'BEGIN { printf "%.2f", ((t-i-w)/t)*100 }')
    cpu_iowait=$(awk -v t="$cpu_total_delta" -v w="$cpu_wait_delta" 'BEGIN { printf "%.2f", (w/t)*100 }')
fi

load_status="SUCCESS"
cpu_status="SUCCESS"
if float_ge "$load_pct" "$LOAD_CRIT_PCT"; then
    load_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif float_ge "$load_pct" "$LOAD_WARN_PCT"; then
    load_status="WARNING"; TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi
if [ "$cpu_util" = "NA" ]; then
    cpu_status="UNCHECKED"
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
elif float_ge "$cpu_util" "$CPU_CRIT_PCT"; then
    cpu_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif float_ge "$cpu_util" "$CPU_WARN_PCT"; then
    cpu_status="WARNING"; TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi
cpu_section_status="$load_status"
if [ "$cpu_status" = "ERROR" ]; then cpu_section_status="ERROR"; fi
if [ "$cpu_status" = "WARNING" ] && [ "$cpu_section_status" = "SUCCESS" ]; then cpu_section_status="WARNING"; fi
if [ "$cpu_section_status" = "SUCCESS" ] && [ "$cpu_status" = "UNCHECKED" ]; then cpu_section_status="UNCHECKED"; fi

print_section_header "${cpu_section_status}" "2. CPU 使用率与系统负载 (CPU & Load)"
echo "逻辑 CPU 核心: ${cpu_cores} 核"
echo "系统平均负载 (1/5/15 分钟): ${load_avg:-未采集}"
echo "负载/核心: ${load_pct}% (关注 ${LOAD_WARN_PCT}%，严重 ${LOAD_CRIT_PCT}%)"
echo "CPU 使用率 (2 秒采样): ${cpu_util}% (关注 ${CPU_WARN_PCT}%，严重 ${CPU_CRIT_PCT}%) [${cpu_status}]"
echo "CPU I/O 等待 (2 秒采样): ${cpu_iowait}%"
if [ "$load_status" = "ERROR" ]; then
    echo "[ERROR] 1 分钟负载已达到每核 ${load_pct}%，建议检查持续占用 CPU 或等待 I/O 的进程。"
elif [ "$load_status" = "WARNING" ]; then
    echo "[WARNING] 1 分钟负载偏高；负载包含可运行和不可中断等待任务，不等同于 CPU 使用率。"
fi
if [ "$cpu_status" = "ERROR" ]; then
    echo "[ERROR] CPU 使用率达到严重阈值 ${CPU_CRIT_PCT}%。"
elif [ "$cpu_status" = "WARNING" ]; then
    echo "[WARNING] CPU 使用率达到关注阈值 ${CPU_WARN_PCT}%。"
elif [ "$cpu_status" = "UNCHECKED" ]; then
    echo "[未采集] 无法从 /proc/stat 取得 CPU 采样数据。"
fi
if [ "$cpu_section_status" = "ERROR" ] || [ "$cpu_section_status" = "WARNING" ]; then
    echo "高 CPU 进程 (异常时展示):"
    ps -eo pid,comm,%cpu,%mem --sort=-%cpu 2>/dev/null | head -n 6
fi

# 3. 内存与交换空间使用情况 (Memory & Swap)
mem_total=$(awk '/^MemTotal:/{print $2}' /proc/meminfo)
mem_avail=$(awk '/^MemAvailable:/{print $2; have_a=1} /^MemFree:/{f=$2} /^Buffers:/{b=$2} /^Cached:/{c=$2} END{if(!have_a) print f+b+c}' /proc/meminfo)
mem_total=${mem_total:-0}; mem_avail=${mem_avail:-0}
mem_util="NA"
if [ "$mem_total" -gt 0 ] 2>/dev/null; then
    mem_util=$(awk -v t="$mem_total" -v a="$mem_avail" 'BEGIN { printf "%.2f", ((t-a)/t)*100 }')
fi
swap_total=$(awk '/^SwapTotal:/{print $2}' /proc/meminfo)
swap_free=$(awk '/^SwapFree:/{print $2}' /proc/meminfo)
swap_util=0
swap_total=${swap_total:-0}; swap_free=${swap_free:-0}
if [ "$swap_total" -gt 0 ] 2>/dev/null; then
    swap_util=$(awk -v t="$swap_total" -v f="$swap_free" 'BEGIN { printf "%.2f", ((t-f)/t)*100 }')
fi
oom_events=""
oom_check_status="UNCHECKED"
if command -v journalctl >/dev/null 2>&1; then
    oom_output=$(journalctl -k --since '24 hours ago' --no-pager -o short-iso 2>/dev/null)
    oom_rc=$?
    if [ "$oom_rc" -eq 0 ]; then
        oom_check_status="SUCCESS"
        oom_events=$(printf '%s\n' "$oom_output" | grep -i -E 'oom-killer|out of memory|killed process' | tail -n 5)
    fi
fi

mem_status="SUCCESS"
mem_usage_status="SUCCESS"
swap_status="NOT_APPLICABLE"
if [ -n "$oom_events" ]; then
    mem_status="ERROR"
    TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
fi
if [ "$mem_util" = "NA" ]; then
    mem_usage_status="UNCHECKED"
    if [ "$mem_status" = "SUCCESS" ]; then mem_status="UNCHECKED"; fi
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
elif float_ge "$mem_util" "$MEM_CRIT_PCT"; then
    mem_status="ERROR"
    mem_usage_status="ERROR"
    TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif float_ge "$mem_util" "$MEM_WARN_PCT"; then
    if [ "$mem_status" != "ERROR" ]; then mem_status="WARNING"; fi
    mem_usage_status="WARNING"
    TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi
if [ "$swap_total" -gt 0 ] 2>/dev/null; then
    swap_status="SUCCESS"
    if float_ge "$swap_util" "$SWAP_CRIT_PCT"; then
        swap_status="ERROR"
        if [ "$mem_status" != "ERROR" ]; then mem_status="ERROR"; fi
        TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
    elif float_ge "$swap_util" "$SWAP_WARN_PCT"; then
        swap_status="WARNING"
        if [ "$mem_status" = "SUCCESS" ] || [ "$mem_status" = "UNCHECKED" ]; then mem_status="WARNING"; fi
        TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
    fi
fi

print_section_header "${mem_status}" "3. 内存与交换空间使用情况 (Memory & Swap)"
echo "物理内存: 总量 $(awk -v t="$mem_total" 'BEGIN {printf "%.2f GB", t/1024/1024}'), 可用 $(awk -v a="$mem_avail" 'BEGIN {printf "%.2f GB", a/1024/1024}') (使用率: ${mem_util}%)"
if [ "$swap_total" -gt 0 ]; then
    echo "交换空间: 总量 $(awk -v t="$swap_total" 'BEGIN {printf "%.2f GB", t/1024/1024}'), 已用 $(awk -v t="$swap_total" -v f="$swap_free" 'BEGIN {printf "%.2f GB", (t-f)/1024/1024}') (使用率: ${swap_util}%)"
else
    echo "交换空间: 未启用 Swap"
fi
echo "判定状态: 内存=${mem_usage_status}; Swap=${swap_status}; OOM 近 24h=${oom_check_status}"

if [ -n "$oom_events" ]; then
    echo "[ERROR] 检测到最近 24 小时内发生 OOM Killer 事件："
    echo "${oom_events}"
elif [ "$mem_util" != "NA" ] && float_ge "$mem_util" "$MEM_CRIT_PCT"; then
    echo "[ERROR] 物理内存使用率已超过 ${MEM_CRIT_PCT}%，极易触发 OOM！"
elif [ "$mem_util" != "NA" ] && float_ge "$mem_util" "$MEM_WARN_PCT"; then
    echo "[WARNING] 物理内存使用率超过 ${MEM_WARN_PCT}%，可用内存较低。"
fi

if [ "$swap_total" -gt 0 ] 2>/dev/null && float_ge "$swap_util" "$SWAP_CRIT_PCT"; then
    echo "[ERROR] 交换分区使用率达到严重阈值 ${SWAP_CRIT_PCT}%。"
elif [ "$swap_total" -gt 0 ] 2>/dev/null && float_ge "$swap_util" "$SWAP_WARN_PCT"; then
    echo "[WARNING] 交换分区使用率超过 ${SWAP_WARN_PCT}%，物理内存可能不足且开始换页！"
fi
if [ "$oom_check_status" = "UNCHECKED" ]; then
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
    echo "[未采集] 无权读取或缺少近 24 小时内核日志；未据此推断是否发生 OOM。"
fi

if [ "$mem_status" = "ERROR" ] || [ "$mem_status" = "WARNING" ]; then
    echo "高内存进程 (异常时展示):"
    ps -eo pid,comm,%mem,%cpu --sort=-%mem 2>/dev/null | head -n 6
fi

# 4. 磁盘与 Inode 空间使用率 (Disk & Inode Space)
disk_status="SUCCESS"
disk_level="OK"
disk_messages=""
df_out=$(df -hP -l -x tmpfs -x devtmpfs -x cdrom -x squashfs 2>/dev/null | tail -n +2)
while read -r line; do
    fs=$(echo "$line" | awk '{print $1}')
    pct=$(echo "$line" | awk '{print $5}' | sed 's/%//')
    mnt=$(echo "$line" | awk '{print $6}')
    [ -z "$pct" ] && continue
    [[ "$pct" =~ ^[0-9]+$ ]] || continue
    if [ "$pct" -ge "$DISK_CRIT_PCT" ]; then
        disk_status="ERROR"
        disk_level="CRITICAL"
        disk_messages="${disk_messages}\n[ERROR] 挂载点 ${mnt} 空间已达 ${pct}% (超过严重阈值 ${DISK_CRIT_PCT}%)"
    elif [ "$pct" -ge "$DISK_WARN_PCT" ]; then
        if [ "$disk_status" != "ERROR" ]; then
            disk_status="WARNING"
            disk_level="ERROR"
        fi
        disk_messages="${disk_messages}\n[WARNING] 挂载点 ${mnt} 空间已达 ${pct}% (超过警告阈值 ${DISK_WARN_PCT}%)"
    fi
done <<< "$df_out"

ro_mounts=$(mount 2>/dev/null | grep -iE '[,(]ro[),]' | grep -vE "type (tmpfs|devtmpfs|proc|sysfs|cgroup|cgroup2|squashfs|overlay|nsfs|tracefs|debugfs|configfs|mqueue|devpts)" | grep -vE " on (/snap(/| )|/var/snap(/| )|/boot/efi(/| ))")
ro_critical_mounts=$(printf '%s\n' "$ro_mounts" | grep -E " on /($| |var(/|$| )|home(/|$| )|data(/|$| )|srv(/|$| )|boot(/|$| ))")
if [ -n "$ro_critical_mounts" ]; then
    disk_status="ERROR"
    disk_level="CRITICAL"
    disk_messages="${disk_messages}\n[ERROR] 关键数据挂载点处于只读状态:\n${ro_critical_mounts}"
elif [ -n "$ro_mounts" ]; then
    if [ "$disk_status" != "ERROR" ]; then disk_status="WARNING"; fi
    disk_messages="${disk_messages}\n[WARNING] 检测到非关键只读挂载点，请确认是否为预期配置:\n${ro_mounts}"
fi

inode_messages=""
inode_level="OK"
inode_status="SUCCESS"
df_i_out=$(df -iP -l -x tmpfs -x devtmpfs -x cdrom -x squashfs 2>/dev/null | tail -n +2)
while read -r line; do
    fs=$(echo "$line" | awk '{print $1}')
    pct=$(echo "$line" | awk '{print $5}' | sed 's/%//')
    mnt=$(echo "$line" | awk '{print $6}')
    [ -z "$pct" ] && continue
    [[ "$pct" =~ ^[0-9]+$ ]] || continue
    if [ "$pct" -ge "$INODE_CRIT_PCT" ]; then
        disk_status="ERROR"
        inode_level="CRITICAL"
        inode_status="ERROR"
        inode_messages="${inode_messages}\n[ERROR] 挂载点 ${mnt} Inode 已达 ${pct}% (超过严重阈值 ${INODE_CRIT_PCT}%)"
    elif [ "$pct" -ge "$INODE_WARN_PCT" ]; then
        if [ "$disk_status" != "ERROR" ]; then
            disk_status="WARNING"
        fi
        if [ "$inode_level" != "CRITICAL" ]; then
            inode_level="ERROR"
            inode_status="WARNING"
        fi
        inode_messages="${inode_messages}\n[WARNING] 挂载点 ${mnt} Inode 已达 ${pct}% (超过警告阈值 ${INODE_WARN_PCT}%)"
    fi
done <<< "$df_i_out"

if [ "$disk_status" = "ERROR" ]; then
    TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif [ "$disk_status" = "WARNING" ]; then
    TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi

print_section_header "${disk_status}" "4. 磁盘与 Inode 空间使用率 (Disk & Inode Space)"
echo "--- 使用率最高的文件系统 ---"
df -hP -l -x tmpfs -x devtmpfs -x cdrom -x squashfs 2>/dev/null | awk 'NR>1 && $5 ~ /^[0-9]+%$/ {print $5, $6, $2, $4}' | sort -rn | head -n 5
[ -n "$disk_messages" ] && echo -e "$disk_messages"

echo "--- Inode 使用率最高的文件系统 ---"
df -iP -l -x tmpfs -x devtmpfs -x cdrom -x squashfs 2>/dev/null | awk 'NR>1 && $5 ~ /^[0-9]+%$/ {print $5, $6, $2, $4}' | sort -rn | head -n 5
[ -n "$inode_messages" ] && echo -e "$inode_messages"

# 5. TCP 连接状态监控 (TCP Connections)
tcp_estab=0
tcp_syn_sent=0
tcp_syn_recv=0
tcp_fin_wait1=0
tcp_fin_wait2=0
tcp_time_wait=0
tcp_close=0
tcp_close_wait=0
tcp_last_ack=0
tcp_listen=0
tcp_closing=0
tcp_collection_status="UNCHECKED"

if type ss >/dev/null 2>&1; then
    ss_raw=$(ss -ant 2>/dev/null)
    if [ $? -eq 0 ]; then
        tcp_collection_status="SUCCESS"
        ss_out=$(printf '%s\n' "$ss_raw" | tail -n +2)
        while read -r line; do
            state=$(echo "$line" | awk '{print $1}')
            case "$state" in
                ESTAB) tcp_estab=$((tcp_estab + 1)) ;;
                SYN-SENT) tcp_syn_sent=$((tcp_syn_sent + 1)) ;;
                SYN-RECV) tcp_syn_recv=$((tcp_syn_recv + 1)) ;;
                FIN-WAIT-1) tcp_fin_wait1=$((tcp_fin_wait1 + 1)) ;;
                FIN-WAIT-2) tcp_fin_wait2=$((tcp_fin_wait2 + 1)) ;;
                TIME-WAIT) tcp_time_wait=$((tcp_time_wait + 1)) ;;
                CLOSE-WAIT) tcp_close_wait=$((tcp_close_wait + 1)) ;;
                LAST-ACK) tcp_last_ack=$((tcp_last_ack + 1)) ;;
                LISTEN) tcp_listen=$((tcp_listen + 1)) ;;
                UNCONN) tcp_close=$((tcp_close + 1)) ;;
            esac
        done <<< "$ss_out"
    fi
else
    parse_proc_tcp() {
        local file="$1"
        [ ! -f "$file" ] && return
        while read -r line; do
            state=$(echo "$line" | awk '{print $4}')
            case "$state" in
                01) tcp_estab=$((tcp_estab + 1)) ;;
                02) tcp_syn_sent=$((tcp_syn_sent + 1)) ;;
                03) tcp_syn_recv=$((tcp_syn_recv + 1)) ;;
                04) tcp_fin_wait1=$((tcp_fin_wait1 + 1)) ;;
                05) tcp_fin_wait2=$((tcp_fin_wait2 + 1)) ;;
                06) tcp_time_wait=$((tcp_time_wait + 1)) ;;
                07) tcp_close=$((tcp_close + 1)) ;;
                08) tcp_close_wait=$((tcp_close_wait + 1)) ;;
                09) tcp_last_ack=$((tcp_last_ack + 1)) ;;
                0A) tcp_listen=$((tcp_listen + 1)) ;;
                0B) tcp_closing=$((tcp_closing + 1)) ;;
            esac
        done < <(tail -n +2 "$file")
    }
    if [ -r "/proc/net/tcp" ] || [ -r "/proc/net/tcp6" ]; then tcp_collection_status="SUCCESS"; fi
    parse_proc_tcp "/proc/net/tcp"
    parse_proc_tcp "/proc/net/tcp6"
fi

tcp_total=$((tcp_estab + tcp_syn_sent + tcp_syn_recv + tcp_fin_wait1 + tcp_fin_wait2 + tcp_time_wait + tcp_close_wait + tcp_last_ack + tcp_closing))
tcp_status="$tcp_collection_status"
tcp_close_wait_status="$tcp_collection_status"
tcp_time_wait_status="$tcp_collection_status"
tcp_retrans_status="UNCHECKED"
tcp_messages=""

# TCP 重传率：按采样窗口的计数器增量计算，避免启动以来累计值掩盖当前异常。
tcp_retrans_pct="NA"
read_tcp_counters() {
    if command -v nstat >/dev/null 2>&1; then
        _nstat=$(nstat -az 2>/dev/null | awk '$1 == "TcpOutSegs" {out=$2} $1 == "TcpRetransSegs" {retr=$2} END {if (out ~ /^[0-9]+$/ && retr ~ /^[0-9]+$/) print out, retr}')
        if [ -n "$_nstat" ]; then
            echo "$_nstat"
            return
        fi
    fi
    awk '
        $1 == "Tcp:" {
            if (!header_seen) {
                header_seen = 1
                for (i = 2; i <= NF; i++) header[$i] = i
            } else {
                out = $(header["OutSegs"])
                retr = $(header["RetransSegs"])
            }
        }
        END {
            if (out ~ /^[0-9]+$/ && retr ~ /^[0-9]+$/) print out, retr
            else print 0, 0
        }
    ' /proc/net/snmp 2>/dev/null
}
_tcp_before=$(read_tcp_counters)
sleep 1
_tcp_after=$(read_tcp_counters)
set -- $_tcp_before
_out_before=${1:-0}
_retr_before=${2:-0}
set -- $_tcp_after
_out_after=${1:-0}
_retr_after=${2:-0}
_delta_out=$((_out_after - _out_before))
_delta_retr=$((_retr_after - _retr_before))
if [ "$_delta_out" -gt 0 ] 2>/dev/null && [ "$_delta_retr" -ge 0 ] 2>/dev/null; then
    tcp_retrans_pct=$(awk -v r="$_delta_retr" -v o="$_delta_out" 'BEGIN { printf "%.2f", (r/o)*100 }')
fi

if [ "$tcp_collection_status" = "SUCCESS" ] && [ "$tcp_close_wait" -ge "$TCP_CLOSE_WAIT_CRIT" ]; then
    tcp_status="ERROR"; tcp_close_wait_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
    tcp_messages="${tcp_messages}\n[ERROR] CLOSE_WAIT=${tcp_close_wait}，达到严重阈值 ${TCP_CLOSE_WAIT_CRIT}。"
elif [ "$tcp_collection_status" = "SUCCESS" ] && [ "$tcp_close_wait" -ge "$TCP_CLOSE_WAIT_WARN" ]; then
    tcp_status="WARNING"; tcp_close_wait_status="WARNING"; TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
    tcp_messages="${tcp_messages}\n[WARNING] CLOSE_WAIT=${tcp_close_wait}，达到关注阈值 ${TCP_CLOSE_WAIT_WARN}。"
fi
if [ "$tcp_collection_status" = "SUCCESS" ] && [ "$tcp_time_wait" -ge "$TCP_TIME_WAIT_CRIT" ]; then
    tcp_status="ERROR"; tcp_time_wait_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
    tcp_messages="${tcp_messages}\n[ERROR] TIME_WAIT=${tcp_time_wait}，达到严重阈值 ${TCP_TIME_WAIT_CRIT}。"
elif [ "$tcp_collection_status" = "SUCCESS" ] && [ "$tcp_time_wait" -ge "$TCP_TIME_WAIT_WARN" ]; then
    if [ "$tcp_status" != "ERROR" ]; then tcp_status="WARNING"; fi
    tcp_time_wait_status="WARNING"
    TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
    tcp_messages="${tcp_messages}\n[WARNING] TIME_WAIT=${tcp_time_wait}，达到关注阈值 ${TCP_TIME_WAIT_WARN}。"
fi
if [ "$tcp_retrans_pct" != "NA" ]; then
    tcp_retrans_status="SUCCESS"
    if float_ge "$tcp_retrans_pct" "$TCP_RETRANS_CRIT_PCT"; then
        tcp_status="ERROR"; tcp_retrans_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
        tcp_messages="${tcp_messages}\n[ERROR] 当前采样窗口 TCP 重传率 ${tcp_retrans_pct}%，达到严重阈值 ${TCP_RETRANS_CRIT_PCT}%。"
    elif float_ge "$tcp_retrans_pct" "$TCP_RETRANS_WARN_PCT"; then
        if [ "$tcp_status" != "ERROR" ]; then tcp_status="WARNING"; fi
        tcp_retrans_status="WARNING"
        TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
        tcp_messages="${tcp_messages}\n[WARNING] 当前采样窗口 TCP 重传率 ${tcp_retrans_pct}%，达到关注阈值 ${TCP_RETRANS_WARN_PCT}%。"
    fi
fi

print_section_header "${tcp_status}" "5. TCP 连接状态监控 (TCP Connections)"
echo "ESTABLISHED 连接数 : ${tcp_estab}"
echo "TIME_WAIT 连接数   : ${tcp_time_wait}"
echo "CLOSE_WAIT 连接数  : ${tcp_close_wait}"
echo "LISTEN 端口数      : ${tcp_listen}"
echo "SYN_RECV 状态数    : ${tcp_syn_recv}"
echo "活动 TCP 连接总数: ${tcp_total} (本脚本不设统一阈值；对应巡检项配置的阈值仍由服务端应用)"
[ -n "$tcp_messages" ] && echo -e "$tcp_messages"
[ "$tcp_collection_status" = "UNCHECKED" ] && { TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1)); echo "[未采集] 无法从 ss 或 /proc/net/tcp 采集当前 TCP 状态。"; }
[ "$tcp_retrans_pct" = "NA" ] && { TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1)); echo "[未采集] 本采样窗口没有可用的 TCP 发送计数器或流量。"; }

# 6. 磁盘 I/O 延迟与吞吐 (Disk I/O Latency)
io_status="SUCCESS"
iowait_status="SUCCESS"
io_latency_status="SUCCESS"
iowait_pct=${cpu_iowait:-NA}
read_lat_ms="NA"
write_lat_ms="NA"
io_latency_ms="NA"
io_device_count=0

if command -v iostat >/dev/null 2>&1; then
    iostat_output=$(iostat -dx 1 2 2>/dev/null)
    iostat_values=$(printf '%s\n' "$iostat_output" | awk '
        BEGIN { rmax=0; wmax=0; umax=0; count=0; in_table=0 }
        $1 == "Device" {
            for (key in col) delete col[key]
            rmax=0; wmax=0; umax=0; count=0; in_table=1
            for (i=1; i<=NF; i++) col[tolower($i)]=i
            next
        }
        in_table && NF > 2 {
            dev=$1
            if (dev ~ /^(loop|ram|fd|sr|zram)/) next
            ri=col["r_await"]; wi=col["w_await"]; ui=col["%util"]
            r=(ri ? $(ri) : ""); w=(wi ? $(wi) : ""); u=(ui ? $(ui) : "")
            if (r ~ /^[0-9]+([.][0-9]+)?$/ && w ~ /^[0-9]+([.][0-9]+)?$/) {
                if (r+0 > rmax) rmax=r+0
                if (w+0 > wmax) wmax=w+0
                if (u ~ /^[0-9]+([.][0-9]+)?$/ && u+0 > umax) umax=u+0
                count++
            }
        }
        END { if (count) printf "%.2f %.2f %.2f %d\n", rmax, wmax, umax, count; else print "NA NA NA 0" }
    ')
    read -r read_lat_ms write_lat_ms io_util_pct io_device_count <<< "$iostat_values"
    if [[ "$read_lat_ms" =~ ^[0-9]+([.][0-9]+)?$ && "$write_lat_ms" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        io_latency_ms=$(awk -v r="$read_lat_ms" -v w="$write_lat_ms" 'BEGIN { printf "%.2f", (r>w?r:w) }')
    fi
else
    io_util_pct="NA"
fi

if [ "$iowait_pct" != "NA" ] && float_ge "$iowait_pct" "$IOWAIT_CRIT_PCT"; then
    io_status="ERROR"; iowait_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif [ "$iowait_pct" != "NA" ] && float_ge "$iowait_pct" "$IOWAIT_WARN_PCT"; then
    io_status="WARNING"; iowait_status="WARNING"; TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi
if [ "$io_latency_ms" != "NA" ] && float_ge "$io_latency_ms" "$IO_AWAIT_CRIT_MS"; then
    io_status="ERROR"; io_latency_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif [ "$io_latency_ms" != "NA" ] && float_ge "$io_latency_ms" "$IO_AWAIT_WARN_MS"; then
    if [ "$io_status" != "ERROR" ]; then io_status="WARNING"; fi
    io_latency_status="WARNING"
    TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi
if [ "$iowait_pct" = "NA" ]; then iowait_status="UNCHECKED"; fi
if [ "$io_latency_ms" = "NA" ]; then io_latency_status="UNCHECKED"; fi
if [ "$iowait_pct" = "NA" ] && [ "$io_latency_ms" = "NA" ]; then io_status="UNCHECKED"; fi

print_section_header "${io_status}" "6. 磁盘 I/O 延迟与吞吐 (Disk I/O Latency)"
echo "CPU I/O 等待 (2 秒采样): ${iowait_pct}% (关注 ${IOWAIT_WARN_PCT}%，严重 ${IOWAIT_CRIT_PCT}%)"
echo "物理磁盘数量: ${io_device_count}; 最大读延迟: ${read_lat_ms} ms; 最大写延迟: ${write_lat_ms} ms; 最大利用率: ${io_util_pct:-NA}%"
echo "判定延迟: ${io_latency_ms} ms (关注 ${IO_AWAIT_WARN_MS} ms，严重 ${IO_AWAIT_CRIT_MS} ms)"
if [ "$iowait_pct" = "NA" ]; then
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
    echo "[未采集] 无法从 /proc/stat 取得当前 I/O 等待采样值。"
elif float_ge "$iowait_pct" "$IOWAIT_CRIT_PCT"; then
    echo "[ERROR] 当前采样窗口 CPU I/O 等待达到严重阈值。"
elif float_ge "$iowait_pct" "$IOWAIT_WARN_PCT"; then
    echo "[WARNING] 当前采样窗口 CPU I/O 等待偏高。"
fi
if [ "$io_latency_ms" = "NA" ]; then
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
    echo "[未采集] 未安装 sysstat/iostat，或采样窗口没有可用物理磁盘数据。"
elif float_ge "$io_latency_ms" "$IO_AWAIT_CRIT_MS"; then
    echo "[ERROR] 至少一个物理磁盘的读写延迟达到严重阈值。"
elif float_ge "$io_latency_ms" "$IO_AWAIT_WARN_MS"; then
    echo "[WARNING] 至少一个物理磁盘的读写延迟达到关注阈值。"
fi

# 7. 系统核心服务与进程 (Critical Services)
serv_status="SUCCESS"
failed_units=""
sshd_active=0
service_sshd_status="ERROR"
cron_status="可选"
service_crond_status="NOT_APPLICABLE"
docker_status="未安装/未启用"
service_docker_status="NOT_APPLICABLE"
if type systemctl >/dev/null 2>&1; then
    failed_units=$(systemctl list-units --state=failed --no-legend --no-pager 2>/dev/null | head -n 10)
    if systemctl is-active --quiet sshd.service 2>/dev/null || systemctl is-active --quiet ssh.service 2>/dev/null; then
        sshd_active=1
    fi
    if systemctl is-active --quiet cron.service 2>/dev/null || systemctl is-active --quiet crond.service 2>/dev/null; then
        cron_status="运行中"
        service_crond_status="SUCCESS"
    fi
    if systemctl is-active --quiet docker.service 2>/dev/null; then
        docker_status="运行中"
        service_docker_status="SUCCESS"
    elif systemctl list-unit-files docker.service --no-legend 2>/dev/null | grep -q 'docker.service'; then
        docker_status="已安装但未运行"
    fi
else
    if pgrep -x cron >/dev/null 2>&1 || pgrep -x crond >/dev/null 2>&1; then cron_status="运行中"; service_crond_status="SUCCESS"; fi
    if pgrep -x dockerd >/dev/null 2>&1; then docker_status="运行中"; service_docker_status="SUCCESS"; fi
fi
if [ "$sshd_active" -eq 0 ] && { pgrep -x sshd >/dev/null 2>&1 || pgrep -x sshd-session >/dev/null 2>&1; }; then
    sshd_active=1
fi
if [ "$sshd_active" -eq 1 ]; then service_sshd_status="SUCCESS"; fi

if [ "$sshd_active" -eq 0 ]; then
    serv_status="ERROR"
    TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
fi

print_section_header "${serv_status}" "7. 系统核心服务与进程 (Critical Services)"
echo "SSH 服务: $([ "$sshd_active" -eq 1 ] && echo '运行中' || echo '未运行')"
echo "Cron 服务: ${cron_status} (非必需项)"
echo "Docker 服务: ${docker_status} (非必需项)"
if [ "$sshd_active" -eq 0 ]; then
    echo "[ERROR] 未发现 ssh/sshd 服务处于运行状态。"
fi
if [ -n "$failed_units" ]; then
    echo "[信息] 检测到失败的 systemd 单元（不默认视为主机故障，请按业务确认）："
    echo "$failed_units"
fi

# 8. 安全防线与入侵审计 (Security Audit)
sec_status="SUCCESS"
ssh_fail_count=0
ssh_auth_events=""
ssh_auth_check="UNCHECKED"
ssh_auth_check_reason="无法读取 systemd journal 中的 SSH 服务日志。"
if command -v journalctl >/dev/null 2>&1; then
    ssh_auth_raw=$(journalctl --since '24 hours ago' -u ssh.service -u sshd.service --no-pager -o cat 2>/dev/null)
    ssh_auth_rc=$?
    if [ "$ssh_auth_rc" -eq 0 ] && [ -n "$ssh_auth_raw" ]; then
        ssh_auth_check="SUCCESS"
        ssh_auth_events=$(printf '%s\n' "$ssh_auth_raw" | grep -iE 'failed password|failed publickey|invalid user|authentication failure|maximum authentication attempts' || true)
        if [ -n "$SSH_IGNORE_IPS" ]; then
            ssh_auth_events=$(printf '%s\n' "$ssh_auth_events" | awk -v ignore_ips="$SSH_IGNORE_IPS" '
                BEGIN { count=split(ignore_ips, ignored, ",") }
                {
                    source=""
                    for (i=1; i<NF; i++) if (tolower($i)=="from") { source=$(i+1); gsub(/[,:]/, "", source); break }
                    skip=0
                    for (i=1; i<=count; i++) { gsub(/^[ \t]+|[ \t]+$/, "", ignored[i]); if (source==ignored[i]) skip=1 }
                    if (!skip) print
                }
            ')
        fi
        ssh_fail_count=$(printf '%s\n' "$ssh_auth_events" | grep -c . || true)
    elif [ "$ssh_auth_rc" -eq 0 ]; then
        ssh_auth_check_reason="最近 24 小时没有可读取的 SSH 服务日志样本，无法据此确认认证失败次数。"
    fi
fi

if [ "$ssh_auth_check" = "UNCHECKED" ]; then
    sec_status="UNCHECKED"
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
elif [ "$ssh_fail_count" -ge "$SSH_FAIL_CRIT_COUNT" ]; then
    sec_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif [ "$ssh_fail_count" -ge "$SSH_FAIL_WARN_COUNT" ]; then
    sec_status="WARNING"; TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi

print_section_header "${sec_status}" "8. 安全防线与入侵审计 (Security Audit)"
echo "最近 24 小时 SSH 认证失败次数: ${ssh_fail_count} (关注 ${SSH_FAIL_WARN_COUNT}，严重 ${SSH_FAIL_CRIT_COUNT})"
echo "忽略的受信任来源: ${SSH_IGNORE_IPS:-无}"
if [ "$ssh_auth_check" = "UNCHECKED" ]; then
    echo "[未采集] ${ssh_auth_check_reason} 未扫描无时间范围的旧日志文件。"
elif [ "$ssh_fail_count" -ge "$SSH_FAIL_CRIT_COUNT" ]; then
    echo "[ERROR] 最近 24 小时 SSH 认证失败次数达到严重阈值，请核查来源和防护策略。"
elif [ "$ssh_fail_count" -ge "$SSH_FAIL_WARN_COUNT" ]; then
    echo "[WARNING] 最近 24 小时 SSH 认证失败次数较多，请核查来源和防护策略。"
fi
ssh_sources=$(printf '%s\n' "$ssh_auth_events" | grep -Eio 'from [0-9a-f:.]+' | awk '{print $2}' | sort | uniq -c | sort -rn | head -n 5)
if [ -n "$ssh_sources" ]; then
    echo "主要来源 (失败次数, IP):"
    echo "$ssh_sources"
fi

# 9. DNS 解析与响应时间 (DNS)
dns_status="SUCCESS"
dns_latency="NA"
dns_successes=0
dns_worst_ms=0
dns_resolvers=$(awk '$1 == "nameserver" {print $2}' /etc/resolv.conf 2>/dev/null | paste -sd ',' -)
resolve_dns_probe() {
    timeout 2 getent hosts "$1" >/dev/null 2>&1
}
dns_latency_known=1
if [ -n "$DNS_PROBE_NAME" ] && command -v getent >/dev/null 2>&1 && command -v timeout >/dev/null 2>&1; then
    for attempt in 1 2 3; do
        dns_start=$(now_ms)
        if resolve_dns_probe "$DNS_PROBE_NAME"; then
            dns_end=$(now_ms)
            dns_successes=$((dns_successes + 1))
            if [[ "$dns_start" =~ ^[0-9]+$ && "$dns_end" =~ ^[0-9]+$ ]]; then
                dns_elapsed=$((dns_end - dns_start))
                [ "$dns_elapsed" -lt 0 ] && dns_elapsed=0
                [ "$dns_elapsed" -gt "$dns_worst_ms" ] && dns_worst_ms=$dns_elapsed
            else
                dns_latency_known=0
            fi
        fi
    done
    if [ "$dns_successes" -gt 0 ]; then
        [ "$dns_latency_known" -eq 1 ] && dns_latency=$dns_worst_ms
        if [ "$dns_successes" -lt 3 ]; then dns_status="WARNING"; TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1)); fi
    else
        dns_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
    fi
    if [ "$dns_successes" -gt 0 ] && [ "$dns_latency_known" -eq 0 ]; then
        dns_status="UNCHECKED"; TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
    fi
else
    dns_status="UNCHECKED"; TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
fi
if [ "$dns_latency" != "NA" ] && float_ge "$dns_latency" "$DNS_CRIT_MS"; then
    dns_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif [ "$dns_latency" != "NA" ] && float_ge "$dns_latency" "$DNS_WARN_MS"; then
    dns_status="WARNING"; TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi
print_section_header "${dns_status}" "9. DNS 解析与响应时间 (DNS)"
echo "探测域名: ${DNS_PROBE_NAME:-未配置}; 配置解析器: ${dns_resolvers:-未发现 nameserver}"
echo "探测路径: getent 系统名称解析（可能命中 /etc/hosts 或本地缓存）"
echo "解析成功: ${dns_successes}/3; 最慢响应: ${dns_latency} ms (关注 ${DNS_WARN_MS} ms，严重 ${DNS_CRIT_MS} ms)"
if [ "$dns_status" = "ERROR" ] && [ "$dns_successes" -eq 0 ]; then
    echo "[ERROR] 连续 3 次均无法解析探测域名，请检查 DNS 配置和解析器可达性。"
elif [ "$dns_status" = "ERROR" ]; then
    echo "[ERROR] DNS 解析响应时间达到严重阈值。"
elif [ "$dns_status" = "WARNING" ]; then
    echo "[WARNING] DNS 解析响应时间达到关注阈值。"
elif [ "$dns_status" = "UNCHECKED" ]; then
    if [ -z "$DNS_PROBE_NAME" ]; then echo "[未采集] 未配置业务探测域名；请设置 NEXORA_DNS_PROBE_NAME 后再判定 DNS 解析。"
    elif ! command -v timeout >/dev/null 2>&1; then echo "[未采集] 系统缺少 timeout，无法对 DNS 查询设置安全时限。"
    elif ! command -v getent >/dev/null 2>&1; then echo "[未采集] 系统没有 getent，无法验证 DNS 解析。"
    else echo "[未采集] DNS 查询成功但当前系统无法准确测量响应时间。"
    fi
fi

# 10. NTP 同步状态与时间偏差 (NTP)
ntp_status="UNCHECKED"
ntp_sync_status="UNCHECKED"
ntp_offset_status="UNCHECKED"
ntp_desync="NA"
ntp_offset_ms="NA"
ntp_source="未知"
ntp_tracking=""
if command -v chronyc >/dev/null 2>&1 && ntp_tracking=$(chronyc tracking 2>/dev/null); then
    ntp_leap=$(printf '%s\n' "$ntp_tracking" | awk -F: '/^Leap status:/ {sub(/^[ \t]+/, "", $2); print $2; exit}')
    ntp_source=$(printf '%s\n' "$ntp_tracking" | awk -F: '/^Reference ID/ {sub(/^[ \t]+/, "", $2); print $2; exit}')
    ntp_offset_seconds=$(printf '%s\n' "$ntp_tracking" | awk -F: '/^System time:/ {sub(/^[ \t]+/, "", $2); print $2}' | awk '{print $1; exit}')
    if [[ "$ntp_offset_seconds" =~ ^-?[0-9]+([.][0-9]+)?$ ]]; then
        ntp_offset_ms=$(awk -v s="$ntp_offset_seconds" 'BEGIN { if (s<0) s=-s; printf "%.2f", s*1000 }')
    fi
    if [ "$ntp_leap" = "Normal" ]; then ntp_desync=0; ntp_sync_status="SUCCESS"; else ntp_desync=1; ntp_sync_status="ERROR"; fi
elif command -v ntpq >/dev/null 2>&1; then
    ntpq_output=$(ntpq -pn 2>/dev/null)
    ntp_peer=$(printf '%s\n' "$ntpq_output" | awk '$1 ~ /^\*/ {print; exit}')
    if [ -n "$ntp_peer" ]; then
        ntp_source=$(printf '%s\n' "$ntp_peer" | awk '{print $1}' | sed 's/^\*//')
        ntp_offset_seconds=$(printf '%s\n' "$ntp_peer" | awk '{print $9}')
        if [[ "$ntp_offset_seconds" =~ ^-?[0-9]+([.][0-9]+)?$ ]]; then
            ntp_offset_ms=$(awk -v s="$ntp_offset_seconds" 'BEGIN { if (s<0) s=-s; printf "%.2f", s }')
        fi
        ntp_desync=0; ntp_sync_status="SUCCESS"
    else
        ntp_desync=1; ntp_sync_status="ERROR"
    fi
elif command -v timedatectl >/dev/null 2>&1; then
    ntp_sync_value=$(timedatectl show -p NTPSynchronized --value 2>/dev/null)
    if [ "$ntp_sync_value" = "yes" ]; then ntp_desync=0; ntp_sync_status="SUCCESS"; fi
    if [ "$ntp_sync_value" = "no" ]; then ntp_desync=1; ntp_sync_status="ERROR"; fi
fi
if [ "$ntp_sync_status" = "ERROR" ]; then
    ntp_status="ERROR"
    TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif [ "$ntp_sync_status" = "SUCCESS" ]; then
    ntp_status="SUCCESS"
else
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
fi
if [ "$ntp_offset_ms" != "NA" ] && float_ge "$ntp_offset_ms" "$NTP_CRIT_OFFSET_MS"; then
    ntp_offset_status="ERROR"; ntp_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif [ "$ntp_offset_ms" != "NA" ] && float_ge "$ntp_offset_ms" "$NTP_WARN_OFFSET_MS"; then
    ntp_offset_status="WARNING"
    if [ "$ntp_status" != "ERROR" ]; then ntp_status="WARNING"; fi
    TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
elif [ "$ntp_offset_ms" != "NA" ]; then
    ntp_offset_status="SUCCESS"
else
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
fi
print_section_header "${ntp_status}" "10. NTP 同步状态与时间偏差 (NTP)"
echo "同步源: ${ntp_source}; 时间偏差: ${ntp_offset_ms} ms (关注 ${NTP_WARN_OFFSET_MS} ms，严重 ${NTP_CRIT_OFFSET_MS} ms)"
if [ "$ntp_sync_status" = "ERROR" ]; then
    echo "[ERROR] NTP 当前未同步，检查时间同步服务和上游源。"
elif [ "$ntp_offset_status" = "ERROR" ]; then
    echo "[ERROR] NTP 时间偏差达到严重阈值。"
elif [ "$ntp_offset_status" = "WARNING" ]; then
    echo "[WARNING] NTP 时间偏差达到关注阈值。"
elif [ "$ntp_status" = "UNCHECKED" ]; then
    echo "[未采集] 未找到可读取的 chrony、ntpq 或 timedatectl 同步状态。"
fi

# 11. 默认网关可达性 (Default Gateway)
gateway_status="UNCHECKED"
gateway_reachable="NA"
gateway_ip=""
gateway_dev=""
gateway_neigh_state=""
gateway_route_count=0
gateway_checked_count=0
gateway_error_count=0
gateway_warning_count=0
gateway_unknown_count=0
gateway_routes_report=""
if command -v ip >/dev/null 2>&1; then
    for gateway_family in -4 -6; do
        gateway_route=$(ip "$gateway_family" route show default 2>/dev/null | head -n 1)
        [ -z "$gateway_route" ] && continue
        gateway_route_count=$((gateway_route_count + 1))
        route_gateway_ip=$(printf '%s\n' "$gateway_route" | awk '{for (i=1; i<=NF; i++) if ($i=="via") {print $(i+1); exit}}')
        route_gateway_dev=$(printf '%s\n' "$gateway_route" | awk '{for (i=1; i<=NF; i++) if ($i=="dev") {print $(i+1); exit}}')
        if [ -z "$route_gateway_ip" ]; then
            gateway_routes_report="${gateway_routes_report}${gateway_family#-} 点到点/直连默认路由（无 via 网关）\\n"
            continue
        fi
        gateway_checked_count=$((gateway_checked_count + 1))
        [ -z "$gateway_ip" ] && gateway_ip="$route_gateway_ip"
        [ -z "$gateway_dev" ] && gateway_dev="$route_gateway_dev"

        gateway_ping_ok=0
        gateway_ping_status="UNAVAILABLE"
        if command -v ping >/dev/null 2>&1; then
            gateway_ping_cmd=(ping)
            [ "$gateway_family" = "-6" ] && gateway_ping_cmd+=(-6)
            [ -n "$route_gateway_dev" ] && gateway_ping_cmd+=(-I "$route_gateway_dev")
            gateway_ping_cmd+=(-c 2 -W 1 "$route_gateway_ip")
            if "${gateway_ping_cmd[@]}" >/dev/null 2>&1; then
                gateway_ping_ok=1
                gateway_ping_status="SUCCESS"
            else
                gateway_ping_status="FAILED"
            fi
        fi

        gateway_neigh_cmd=(ip "$gateway_family" neigh show to "$route_gateway_ip")
        [ -n "$route_gateway_dev" ] && gateway_neigh_cmd+=(dev "$route_gateway_dev")
        route_neigh_state=$("${gateway_neigh_cmd[@]}" 2>/dev/null | awk 'NR==1 {print $NF}')
        [ -n "$route_neigh_state" ] && gateway_neigh_state="$route_neigh_state"
        route_result="${gateway_family#-} ${route_gateway_ip} dev ${route_gateway_dev:-?}: "
        if [ "$gateway_ping_ok" -eq 1 ] || [ "$route_neigh_state" = "REACHABLE" ]; then
            gateway_routes_report="${gateway_routes_report}${route_result}可达（ping=${gateway_ping_status}, neigh=${route_neigh_state:-无}）\\n"
        elif [ "$route_neigh_state" = "FAILED" ] || [ "$route_neigh_state" = "INCOMPLETE" ]; then
            gateway_error_count=$((gateway_error_count + 1))
            gateway_routes_report="${gateway_routes_report}${route_result}邻居解析失败（${route_neigh_state}）\\n"
        elif [ "$gateway_ping_status" = "FAILED" ]; then
            gateway_warning_count=$((gateway_warning_count + 1))
            gateway_routes_report="${gateway_routes_report}${route_result}ping 无响应（neigh=${route_neigh_state:-无}）\\n"
        else
            gateway_unknown_count=$((gateway_unknown_count + 1))
            gateway_routes_report="${gateway_routes_report}${route_result}无实时可达性证据（neigh=${route_neigh_state:-无}）\\n"
        fi
    done

    if [ "$gateway_route_count" -eq 0 ]; then
        if [ "${NEXORA_REQUIRE_DEFAULT_GATEWAY:-0}" = "1" ]; then
            gateway_status="ERROR"; gateway_reachable=0; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
        else
            TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
        fi
    elif [ "$gateway_checked_count" -eq 0 ]; then
        TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
    elif [ "$gateway_error_count" -gt 0 ]; then
        gateway_status="ERROR"; gateway_reachable=0; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
    elif [ "$gateway_warning_count" -gt 0 ]; then
        gateway_status="WARNING"; gateway_reachable=0; TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
    elif [ "$gateway_unknown_count" -gt 0 ]; then
        TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
    else
        gateway_status="SUCCESS"; gateway_reachable=1
    fi
else
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
fi
print_section_header "${gateway_status}" "11. 默认网关可达性 (Default Gateway)"
echo "IPv4/IPv6 默认路由数: ${gateway_route_count}; 可探测网关数: ${gateway_checked_count}"
echo "网关检查结果 (ping 成功或邻居状态 REACHABLE 才确认可达):"
[ -n "$gateway_routes_report" ] && printf '%b' "$gateway_routes_report"
echo "兼容指标首个网关: ${gateway_ip:-未配置/无 via 网关}; 出接口: ${gateway_dev:-—}; 最近邻居状态: ${gateway_neigh_state:-—}"
echo "可达性指标: ${gateway_reachable}"
if [ "$gateway_status" = "ERROR" ]; then
    if [ "$gateway_route_count" -eq 0 ]; then echo "[ERROR] 当前配置要求默认网关，但未发现 IPv4/IPv6 默认路由。"; else echo "[ERROR] 至少一个默认网关的邻居解析失败。"; fi
elif [ "$gateway_status" = "WARNING" ]; then
    echo "[WARNING] 至少一个默认网关 Ping 无响应且没有当前 REACHABLE 邻居证据；ICMP 可能被屏蔽，请核查路径。"
elif [ "$gateway_status" = "UNCHECKED" ]; then
    if [ "$gateway_route_count" -eq 0 ]; then
        echo "[未采集] 未配置默认路由；如该主机必须有默认路由，可设置 NEXORA_REQUIRE_DEFAULT_GATEWAY=1。"
    elif [ "$gateway_checked_count" -eq 0 ]; then
        echo "[未采集] 默认路由是点到点/直连路由，没有 via 网关地址可单独探测。"
    else
        echo "[未采集] 邻居状态不是实时可达证据，且系统无法执行 Ping。"
    fi
fi

# 12. 文件句柄使用率 (File Descriptors)
fd_status="UNCHECKED"
fd_system_status="UNCHECKED"
fd_util="NA"
fd_used="NA"
fd_limit="NA"
fd_proc_max_pct="NA"
fd_process_status="UNCHECKED"
fd_process_severity="UNCHECKED"
fd_process_report=""
fd_process_accessible=0
fd_process_unreadable="NA"
if [ -r /proc/sys/fs/file-nr ]; then
    read -r fd_allocated fd_unused fd_max < /proc/sys/fs/file-nr
    if [[ "${fd_allocated:-}" =~ ^[0-9]+$ && "${fd_unused:-}" =~ ^[0-9]+$ && "${fd_max:-}" =~ ^[0-9]+$ && "$fd_max" -gt 0 ]]; then
        fd_used=$((fd_allocated - fd_unused))
        [ "$fd_used" -lt 0 ] && fd_used=0
        fd_limit=$fd_max
        fd_util=$(awk -v u="$fd_used" -v m="$fd_max" 'BEGIN { printf "%.2f", (u/m)*100 }')
        fd_system_status="SUCCESS"
    fi
fi
if [ "$fd_util" != "NA" ] && float_ge "$fd_util" "$FD_CRIT_PCT"; then
    fd_system_status="ERROR"; fd_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif [ "$fd_util" != "NA" ] && float_ge "$fd_util" "$FD_WARN_PCT"; then
    fd_system_status="WARNING"; fd_status="WARNING"; TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
elif [ "$fd_system_status" = "SUCCESS" ]; then
    fd_status="SUCCESS"
else
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
fi
if command -v python3 >/dev/null 2>&1; then
    fd_process_report=$(python3 - <<'PY'
import glob, os
rows = []
accessible = 0
unreadable = 0
for fd_dir in glob.glob('/proc/[0-9]*/fd'):
    pid = fd_dir.split('/')[2]
    try:
        count = len(os.listdir(fd_dir))
        with open(f'/proc/{pid}/limits', encoding='utf-8', errors='replace') as stream:
            limit_line = next((line for line in stream if line.startswith('Max open files')), '')
        fields = limit_line.split()
        if len(fields) < 5:
            unreadable += 1
            continue
        accessible += 1
        if fields[3] == 'unlimited':
            continue
        soft_limit = int(fields[3])
        if soft_limit <= 0:
            continue
        try:
            with open(f'/proc/{pid}/comm', encoding='utf-8', errors='replace') as stream:
                name = stream.read().strip() or 'unknown'
        except OSError:
            name = 'unknown'
        rows.append((count * 100.0 / soft_limit, name, pid, count, soft_limit))
    except FileNotFoundError:
        # The process exited during the scan; this is an ordinary sampling race.
        continue
    except PermissionError:
        unreadable += 1
        continue
    except (OSError, ValueError, IndexError):
        unreadable += 1
        continue
print(f'SUMMARY|{accessible}|{unreadable}')
for row in sorted(rows, reverse=True)[:5]:
    print(f'{row[0]:.2f}|{row[1]}|{row[2]}|{row[3]}|{row[4]}')
PY
    )
    fd_process_accessible=$(printf '%s\n' "$fd_process_report" | awk -F'|' 'NR==1 && $1=="SUMMARY" {print $2}')
    fd_process_unreadable=$(printf '%s\n' "$fd_process_report" | awk -F'|' 'NR==1 && $1=="SUMMARY" {print $3}')
    fd_process_accessible=${fd_process_accessible:-0}
    fd_process_unreadable=${fd_process_unreadable:-0}
    fd_process_report=$(printf '%s\n' "$fd_process_report" | tail -n +2)
    fd_proc_max_pct=$(printf '%s\n' "$fd_process_report" | awk -F'|' 'NF>=5 && $1+0>m {m=$1+0} END {if (m>0) printf "%.2f", m; else print "NA"}')
    if [ "$fd_process_accessible" -gt 0 ] 2>/dev/null && [ "$fd_process_unreadable" -eq 0 ] 2>/dev/null; then
        fd_process_status="SUCCESS"
        fd_process_severity="SUCCESS"
    elif [ "$fd_process_accessible" -gt 0 ] 2>/dev/null; then
        fd_process_status="UNCHECKED"
        fd_process_severity="UNCHECKED"
        TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
    else
        fd_process_status="UNCHECKED"
        fd_process_severity="UNCHECKED"
        TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
    fi
    if [ "$fd_proc_max_pct" = "NA" ] && [ "$fd_process_status" = "SUCCESS" ]; then
        fd_process_status="UNCHECKED"
        fd_process_severity="UNCHECKED"
        TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
    fi
    if [ "$fd_proc_max_pct" != "NA" ] && float_ge "$fd_proc_max_pct" "$FD_CRIT_PCT"; then
        fd_process_status="ERROR"; fd_process_severity="ERROR"; fd_status="ERROR"; TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
    elif [ "$fd_proc_max_pct" != "NA" ] && float_ge "$fd_proc_max_pct" "$FD_WARN_PCT"; then
        fd_process_status="WARNING"; fd_process_severity="WARNING"
        if [ "$fd_status" != "ERROR" ]; then fd_status="WARNING"; fi
        TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
    fi
else
    fd_process_status="UNCHECKED"
    fd_process_severity="UNCHECKED"
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
fi
if [ "$fd_util" = "NA" ] || [ "$fd_process_status" = "UNCHECKED" ]; then
    if [ "$fd_status" != "ERROR" ] && [ "$fd_status" != "WARNING" ]; then fd_status="UNCHECKED"; fi
fi
print_section_header "${fd_status}" "12. 文件句柄使用率 (File Descriptors)"
echo "系统文件句柄: ${fd_used}/${fd_limit} (${fd_util}%; 关注 ${FD_WARN_PCT}%，严重 ${FD_CRIT_PCT}%)"
echo "进程句柄使用率最高值: ${fd_proc_max_pct}% [${fd_process_status}] (可读取进程 ${fd_process_accessible:-0}，权限/读取失败 ${fd_process_unreadable:-NA})"
if [ "${fd_process_unreadable:-0}" -gt 0 ] 2>/dev/null; then
    echo "[未采集] 有 ${fd_process_unreadable} 个进程因权限或读取错误被跳过，进程级最大使用率可能不完整。"
fi
if [ -n "$fd_process_report" ]; then
    echo "进程级高使用率 (比例|进程|PID|已用|软上限):"
    echo "$fd_process_report"
else
    echo "[未采集] 当前用户权限或系统缺少 Python 3，无法完整检查各进程的文件句柄上限。"
fi
if [ "$fd_system_status" = "ERROR" ]; then echo "[ERROR] 系统文件句柄使用率达到严重阈值。"; fi
if [ "$fd_system_status" = "WARNING" ]; then echo "[WARNING] 系统文件句柄使用率达到关注阈值。"; fi
if [ "$fd_process_status" = "ERROR" ]; then echo "[ERROR] 至少一个可读取进程的文件句柄使用率达到严重阈值。"; fi
if [ "$fd_process_status" = "WARNING" ]; then echo "[WARNING] 至少一个可读取进程的文件句柄使用率达到关注阈值。"; fi
if [ "$fd_system_status" = "UNCHECKED" ]; then echo "[未采集] 无法读取系统文件句柄计数。"; fi
if [ "$fd_process_status" = "UNCHECKED" ] && [ "${fd_process_unreadable:-0}" -eq 0 ] 2>/dev/null; then echo "[未采集] 无法取得可用于判断进程句柄使用率的完整数据。"; fi

# 13. 巡检汇总 (Summary)
max_usage=$(df -hP -l -x tmpfs -x devtmpfs -x cdrom -x squashfs 2>/dev/null | awk 'NR>1 && $5 ~ /^[0-9]+%$/ {v=$5; sub(/%/, "", v); if (!seen || v>max) max=v; seen=1} END {if (seen) print max; else print "NA"}')
max_inode=$(df -iP -l -x tmpfs -x devtmpfs -x cdrom -x squashfs 2>/dev/null | awk 'NR>1 && $5 ~ /^[0-9]+%$/ {v=$5; sub(/%/, "", v); if (!seen || v>max) max=v; seen=1} END {if (seen) print max; else print "NA"}')
disk_usage_status="SUCCESS"
if [ "$max_usage" = "NA" ]; then
    disk_usage_status="UNCHECKED"
elif [ "$max_usage" -ge "$DISK_CRIT_PCT" ]; then
    disk_usage_status="ERROR"
elif [ "$max_usage" -ge "$DISK_WARN_PCT" ]; then
    disk_usage_status="WARNING"
fi
if [ "$max_usage" = "NA" ]; then
    if [ "$disk_status" = "SUCCESS" ]; then disk_status="UNCHECKED"; fi
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
fi
if [ "$max_inode" = "NA" ]; then
    inode_status="UNCHECKED"
    TOTAL_UNCHECKED=$((TOTAL_UNCHECKED + 1))
fi
service_sshd=$sshd_active
service_crond=0
service_docker=0
[ "$cron_status" = "运行中" ] && service_crond=1
[ "$docker_status" = "运行中" ] && service_docker=1

echo "======================================================================"
echo "巡检汇总 (Summary)"
echo "======================================================================"
echo "发现严重错误 (ERROR)   : ${TOTAL_ERRORS} 个"
echo "发现警告信息 (WARNING) : ${TOTAL_WARNINGS} 个"
echo "未采集检查项          : ${TOTAL_UNCHECKED} 个"
echo "========== HEALTH CHECK =========="
echo "主机: ${hostname}; 时间: ${system_time}"
echo "CPU 负载/使用率: ${load_status}/${cpu_status}; 内存: ${mem_status}; 磁盘/Inode: ${disk_status}/${inode_status}"
echo "TCP: ${tcp_status}; I/O: ${io_status}; 服务: ${serv_status}; SSH 审计: ${sec_status}"
echo "DNS: ${dns_status}; NTP: ${ntp_status}; 网关: ${gateway_status}; 文件句柄系统/进程: ${fd_status}/${fd_process_status}"
echo "异常数: 严重 ${TOTAL_ERRORS}，关注 ${TOTAL_WARNINGS}，未采集 ${TOTAL_UNCHECKED}"

echo "--- METRICS ---"
echo "cpu_load: ${load_pct}"
echo "cpu_load_status: ${load_status}"
echo "cpu_util: ${cpu_util}"
echo "cpu_util_status: ${cpu_status}"
echo "mem_avail: ${mem_util}"
echo "mem_avail_status: ${mem_usage_status}"
echo "swap_util: ${swap_util}"
echo "swap_util_status: ${swap_status}"
echo "io_wait: ${iowait_pct}"
echo "io_wait_status: ${iowait_status}"
echo "io_latency: ${io_latency_ms}"
echo "io_latency_status: ${io_latency_status}"
echo "disk_io_await: ${io_latency_ms}"
echo "disk_io_await_status: ${io_latency_status}"
echo "disk_util: ${max_usage}"
echo "disk_util_status: ${disk_usage_status}"
echo "inode_util: ${max_inode}"
echo "inode_util_status: ${inode_status}"
echo "tcp_conns: ${tcp_total}"
echo "tcp_conns_status: ${tcp_collection_status}"
echo "tcp_time_wait: ${tcp_time_wait}"
echo "tcp_time_wait_status: ${tcp_time_wait_status}"
echo "tcp_close_wait: ${tcp_close_wait}"
echo "tcp_close_wait_status: ${tcp_close_wait_status}"
echo "tcp_retrans_pct: ${tcp_retrans_pct:-0}"
echo "tcp_retrans_pct_status: ${tcp_retrans_status}"
# Legacy telemetry consumers use tcp_retrans; keep it as an alias.
echo "tcp_retrans: ${tcp_retrans_pct:-0}"
echo "tcp_retrans_status: ${tcp_retrans_status}"
echo "tcp_estab: ${tcp_estab}"
echo "tcp_syn_recv: ${tcp_syn_recv}"
echo "tcp_listen: ${tcp_listen}"
echo "dns_latency: ${dns_latency}"
echo "dns_latency_status: ${dns_status}"
echo "dns_probe_name: ${DNS_PROBE_NAME}"
echo "ntp_desync: ${ntp_desync}"
echo "ntp_desync_status: ${ntp_sync_status}"
echo "ntp_offset_ms: ${ntp_offset_ms}"
echo "ntp_offset_ms_status: ${ntp_offset_status}"
echo "ntp_source: ${ntp_source}"
echo "gateway_reachable: ${gateway_reachable}"
echo "gateway_reachable_status: ${gateway_status}"
echo "gateway_ip: ${gateway_ip:-NA}"
echo "gateway_interface: ${gateway_dev:-NA}"
echo "fd_util: ${fd_util}"
echo "fd_util_status: ${fd_system_status}"
echo "fd_process_max_pct: ${fd_proc_max_pct}"
echo "fd_process_max_pct_status: ${fd_process_severity}"
echo "fd_used: ${fd_used}"
echo "fd_limit: ${fd_limit}"
echo "service_sshd: ${service_sshd}"
echo "service_sshd_status: ${service_sshd_status}"
echo "service_crond: ${service_crond}"
echo "service_crond_status: ${service_crond_status}"
echo "service_docker: ${service_docker}"
echo "service_docker_status: ${service_docker_status}"
echo "======================================================================"
""", 'Linux 主机综合巡检脚本，检查 CPU/内存/文件系统/TCP/I/O/服务/SSH/DNS/NTP/网关/文件句柄', 'Linux', 'inspection'),
]


# Default items list
def get_default_items(now: str) -> list[tuple]:
    return [
        # --- Network Device ---
        ('net_ping', 'Connectivity (Ping)', '网络连通性 (Ping)', 'Network', 'ping', '检查设备 ICMP 响应时间与丢包率', 'ICMP', 'ping -c 3 {ip}', '', 100, 200, 'Generic', '', now, now),
        ('net_ssh', 'SSH Accessibility', '管理通道 (SSH)', 'Network', 'ssh', '检查 22 端口可用性', 'TCP', 'socket.connect({ip}, 22)', '', 500, 2000, 'Generic', '', now, now),
        ('net_cpu', 'CPU Utilization', 'CPU 利用率 (SNMP)', 'Network', 'cpu', '监控网络设备 CPU 负载', 'SNMP', 'OID: 1.3.6.1.4.1.9.9.109.1.1.1.1.7', '', 85, 95, 'Cisco', '1.3.6.1.4.1.9.9.109.1.1.1.1.7', now, now),
        ('net_mem', 'Memory Utilization', '内存利用率 (SNMP)', 'Network', 'memory', '监控网络设备内存消耗', 'SNMP', 'OID: 1.3.6.1.4.1.9.9.48.1.1.1.5.1', '', 90, 98, 'Cisco', '1.3.6.1.4.1.9.9.48.1.1.1.5.1', now, now),
        ('net_bgp', 'BGP Peer Status', 'BGP 邻居状态', 'Network', 'bgp_neighbor', '监控 BGP 状态机', 'SSH', 'show ip bgp summary', '', 0, 1, 'Generic', '', now, now),

        ('srv_cpu_load', 'CPU Load Average', 'CPU 系统负载', 'Server', 'cpu_load', '监控 1min 负载相对于核心数的比例', 'Shell', 'std_linux_load', 'std_linux_load', 80, 150, 'Linux', '', now, now),
        ('srv_cpu_util', 'CPU Utilization', 'CPU 使用率', 'Server', 'cpu_util', '监控整体 CPU 使用率 (0-100)', 'Shell', 'std_linux_cpu', 'std_linux_cpu', 90, 95, 'Linux', '', now, now),
        ('srv_mem_avail', 'Available Memory', '可用内存', 'Server', 'mem_avail', '监控系统内存使用百分比 (0-100)', 'Shell', 'std_linux_mem', 'std_linux_mem', 85, 95, 'Linux', '', now, now),
        ('srv_swap', 'Swap Usage', '交换分区使用率', 'Server', 'swap_util', '监控交换分区使用百分比 (0-100)', 'Shell', 'std_linux_swap', 'std_linux_swap', 70, 90, 'Linux', '', now, now),
        ('srv_iowait', 'Disk IO Wait', '磁盘 IO 等待 (IOWait)', 'Server', 'io_wait', '监控 CPU 等待 IO 时间占比 (阈值: >15% 告警)', 'Shell', 'std_linux_iowait', 'std_linux_iowait', 15, 30, 'Linux', '', now, now),
        ('srv_disk_util', 'Disk Space Usage', '磁盘空间利用率', 'Server', 'disk_util', '监控根分区空间占用 (0-100)', 'Shell', 'std_linux_disk', 'std_linux_disk', 90, 95, 'Linux', '', now, now),
        ('srv_disk_inode', 'Inode Utilization', 'Inode 使用率', 'Server', 'inode_util', '监控根分区 Inode 占用 (0-100)', 'Shell', 'std_linux_inode', 'std_linux_inode', 90, 95, 'Linux', '', now, now),
        ('srv_net_conns', 'Established Connections', '并发连接数', 'Server', 'tcp_conns', '监控 TCP Established 状态连接数', 'Shell', 'std_linux_conns', 'std_linux_conns', 5000, 10000, 'Linux', '', now, now),
        ('srv_process', 'Critical Processes', '核心进程监控', 'Server', 'process_health', '监控指定进程是否存在', 'Shell', 'std_linux_proc', 'std_linux_proc', None, 1, 'Linux', '', now, now),
        ('srv_oom_events', 'OOM Killer Events', 'OOM 杀进程事件数', 'Server', 'oom_events', '监控系统最近是否触发过 OOM-killer 强制杀死过进程', 'Shell', 'std_linux_oom_events', 'std_linux_oom_events', 1, 5, 'Linux', '', now, now),
        ('srv_ro_mounts', 'Read-only Mounts', '只读挂载文件系统数', 'Server', 'ro_mounts', '监控是否存在只读挂载的文件系统，防止硬盘故障', 'Shell', 'std_linux_ro_mounts', 'std_linux_ro_mounts', 1, 1, 'Linux', '', now, now),
        ('srv_kernel_errs', 'Kernel Error Log Count', '内核严重报错日志数', 'Server', 'kernel_errs', '监控系统内核报错日志数量 (dmesg)', 'Shell', 'std_linux_kernel_errs', 'std_linux_kernel_errs', 1, 10, 'Linux', '', now, now),
        ('srv_zombie_procs', 'Zombie Processes', '僵尸进程数', 'Server', 'zombie_procs', '监控未能被正常回收的僵尸进程占用量', 'Shell', 'std_linux_zombie_procs', 'std_linux_zombie_procs', 2, 5, 'Linux', '', now, now),
        ('srv_fd_util', 'File Descriptor Utilization %', '文件句柄使用率', 'Server', 'fd_util', '监控系统已开启文件句柄数占上限的比例', 'Shell', 'std_linux_fd_util', 'std_linux_fd_util', 80, 90, 'Linux', '', now, now),
        ('srv_net_errs', 'Network Interface Errors/Drops', '网卡丢包与报错数', 'Server', 'net_errs', '监测系统所有网卡接口 errors 和 dropped 的总计数', 'Shell', 'std_linux_net_errs', 'std_linux_net_errs', 10, 100, 'Linux', '', now, now),
        ('srv_ntp_desync', 'NTP Desync Status', 'NTP 时间失步状态', 'Server', 'ntp_desync', '监控 NTP 本地时钟是否同步 (0=同步, 1=失步/失败)', 'Shell', 'std_linux_ntp_desync', 'std_linux_ntp_desync', 1, 1, 'Linux', '', now, now),
        ('srv_dns_latency', 'DNS Resolution Latency', 'DNS 解析延迟 (ms)', 'Server', 'dns_latency', '监控域名解析延迟 (单位: 毫秒，超时失败为 9999)', 'Shell', 'std_linux_dns_latency', 'std_linux_dns_latency', 1000, 5000, 'Linux', '', now, now),
        ('srv_recent_reboot', 'Recent Reboot Alert', '系统最近重启告警', 'Server', 'recent_reboot', '监控系统最近 15 分钟内是否重启过 (0=否, 1=是)', 'Shell', 'std_linux_recent_reboot', 'std_linux_recent_reboot', 1, 1, 'Linux', '', now, now),
        ('srv_core_dumps_count', 'Core Dump Files', 'CoreDump 崩溃文件数', 'Server', 'core_dumps_count', '监控系统关键目录和临时目录下崩溃文件数', 'Shell', 'std_linux_core_dumps_count', 'std_linux_core_dumps_count', 1, 5, 'Linux', '', now, now),
        ('srv_disk_io_await', 'Disk I/O Await Latency', '磁盘 I/O 等待延迟 (ms)', 'Server', 'disk_io_await', '监控系统磁盘平均读写响应等待耗时 (毫秒)', 'Shell', 'std_linux_disk_io_await', 'std_linux_disk_io_await', 20, 50, 'Linux', '', now, now),
        ('srv_tcp_close_wait', 'TCP CLOSE_WAIT Connections', 'TCP CLOSE_WAIT 异常连接数', 'Server', 'tcp_close_wait', '监控系统处于 CLOSE_WAIT 异常未关闭状态的 TCP 连接数', 'Shell', 'std_linux_tcp_close_wait', 'std_linux_tcp_close_wait', 50, 200, 'Linux', '', now, now),
        ('srv_tcp_retrans_pct', 'TCP Retransmission Ratio %', 'TCP 协议栈重传段比例', 'Server', 'tcp_retrans_pct', '监控 TCP 协议栈中重传的报文比例 (%)', 'Shell', 'std_linux_tcp_retrans_pct', 'std_linux_tcp_retrans_pct', 2, 5, 'Linux', '', now, now),
    ]


compliance_expected_values = {
    'compliance_cisco_ios_ntp': 'synchronized',
    'compliance_cisco_ios_aaa': 'aaa new-model',
    'compliance_cisco_ios_telnet': 'ssh',
    'compliance_cisco_ios_ssh_ver': '2.0',
    'compliance_cisco_ios_snmp': '',
}
