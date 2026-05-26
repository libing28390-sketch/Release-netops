import json
from .core import _beijing_now_iso

def _build_network_inspection_items(now: str) -> list[tuple]:
    """
    构建网络设备巡检指标（CLI 方式 + TextFSM 解析）。
    """
    items: list[tuple] = []

    def _item(id_, name, name_zh, category, check_key, desc, cmd, vendor,
              w, c, parse_type, textfsm_template, parse_field,
              parse_filter='', fallback_regex=''):
        items.append((
            id_, name, name_zh, category, check_key, desc,
            'CLI', cmd, '',
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
          '统计非 Established 的 BGP 邻居', 'show ip bgp summary', 'cisco_ios',
          1, 2, 'count', 'cisco_ios_show_ip_bgp_summary', 'STATE_OR_PREFIXES_RECEIVED',
          parse_filter='{"field":"STATE_OR_PREFIXES_RECEIVED","op":"not_numeric"}')
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
          '统计非 Established 的 BGP 邻居', 'show bgp ipv4 unicast summary', 'cisco_nxos',
          1, 2, 'count', 'cisco_nxos_show_ip_bgp_summary', 'STATE_PFXRCD',
          parse_filter='{"field":"STATE_PFXRCD","op":"not_numeric"}')

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
          '统计非 Established 的 BGP 邻居', 'display bgp peer', 'huawei_vrp',
          1, 2, 'count', 'huawei_vrp_display_bgp_peer', 'STATE',
          parse_filter='{"field":"STATE","op":"!=","value":"Established"}')
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
          '统计非 Established 的 BGP 邻居', 'display bgp peer ipv4', 'h3c_comware',
          1, 2, 'count', 'hp_comware_display_bgp_peer_ipv4', 'STATE',
          parse_filter='{"field":"STATE","op":"!=","value":"Established"}')
    _item('net_h3c_route_total', 'H3C Comware Route Total', 'H3C Comware 路由总数', 'Network', 'h3c_comware_route_total',
          '路由总数（与上次对比）', 'display ip routing-table statistics', 'h3c_comware',
          10, 30, 'diff', 'hp_comware_display_ip_routing_table_statistics', 'ACTIVE',
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
    ('std_linux_mem', 'Linux 内存使用率', '#!/bin/bash\n# 计算内存使用率 (已用/总计)\nmem_total=$(free | grep Mem | awk "{print $2}")\nmem_used=$(free | grep Mem | awk "{print $3}")\n[ "$mem_total" -gt 0 ] && echo | awk "{print ($mem_used/$mem_total)*100}" || echo 0', '计算系统内存使用百分比 (0-100)', 'Linux', 'standard'),
    ('std_linux_cpu', 'Linux CPU 使用率', '#!/bin/bash\n# 提取系统 CPU 整体利用率\ntop -bn1 | grep "Cpu(s)" | sed "s/.*, *\\([0-9.]*\\)%* id.*/\\1/" | awk "{print 100 - $1}"', '计算系统整体 CPU 使用率 (0-100)', 'Linux', 'standard'),
    ('std_linux_disk', 'Linux 全量磁盘空间', '#!/bin/bash\n# 扫描所有本地挂载点，过滤虚拟分区，按使用率排序\necho "Detailed Disk Usage (Top 10):"\ndf -hP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | sort -k5 -rn | head -n 10\n# 提取全局最大利用率作为判定值\nmax_usage=$(df -hP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | awk "{print $5}" | sed "s/%//" | sort -rn | head -1)\necho "MAX_UTILIZATION: ${max_usage:-0}"', '扫描所有本地分区，取最大利用率百分比', 'Linux', 'standard'),
    ('std_linux_inode', 'Linux 全量磁盘 Inode', '#!/bin/bash\n# 扫描所有本地挂载点 Inode 使用率\necho "Detailed Inode Usage (Top 10):"\ndf -iP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | sort -k5 -rn | head -n 10\nmax_inode=$(df -iP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | awk "{print $5}" | sed "s/%//" | sort -rn | head -1)\necho "MAX_INODE_UTIL: ${max_inode:-0}"', '扫描所有本地分区，取最大 Inode 使用率', 'Linux', 'standard'),
    ('std_linux_iowait', 'Linux IO Wait 延迟', '#!/bin/bash\n# 提取 CPU IO 等待比例\niostat -c 1 2 | grep -v "avg-cpu" | tail -1 | awk "{print $4}"', 'CPU 等待磁盘 IO 时间占比 (0-100)', 'Linux', 'standard'),
    ('std_linux_swap', 'Linux Swap 使用率', '#!/bin/bash\nfree | grep Swap | awk "{if ($2>0) print ($3/$2)*100; else print 0}"', '交换分区使用百分比 (0-100)', 'Linux', 'standard'),
    ('std_linux_load', 'Linux CPU 负载比例', '#!/bin/bash\n# 计算负载与核心数的比值\ncores=$(grep -c ^processor /proc/cpuinfo)\nload=$(uptime | awk -F "load average:" "{print $2}" | cut -d, -f1 | xargs)\necho | awk "{print ($load/$cores)*100}"', '系统 1min 负载相对于核心数的比例', 'Linux', 'standard'),
    ('std_linux_conns', 'Linux TCP 连接数', '#!/bin/bash\nss -ant | grep ESTAB | wc -l', '统计系统 Established 状态 the TCP 连接总数', 'Linux', 'standard'),
    ('std_linux_proc', 'Linux 关键进程巡检', '#!/bin/bash\n# 检查指定的多个关键进程，返回丢失的数量\nprocs=${1:-"sshd crond docker"}\nmissing=0\nfor p in $procs; do\n  if ! pgrep -f "$p" > /dev/null; then\n    echo "[CRITICAL] Process not found: $p"\n    missing=$((missing + 1))\n  fi\ndone\necho "MISSING_COUNT: $missing"', '检查进程存活状态，返回未运行的进程数', 'Linux', 'standard'),

    # Cisco IOS / IOS-XE
    ('insp_cisco_ios_full', 'Cisco IOS 综合巡检', 'show version\nshow processes cpu sorted\nshow processes memory sorted\nshow environment temperature\nshow environment power all\nshow interfaces status\nshow ip bgp summary\nshow ip ospf neighbor\nshow ip route summary', 'Cisco IOS / IOS-XE 综合巡检脚本，覆盖 CPU/内存/温度/电源/接口/路由协议/路由数量', 'cisco_ios', 'inspection'),
    # Cisco NX-OS
    ('insp_cisco_nxos_full', 'Cisco NX-OS 综合巡检', 'show version\nshow processes cpu\nshow system resources\nshow environment\nshow interface brief\nshow ip bgp summary\nshow ip ospf neighbor\nshow ip route summary', 'Cisco NX-OS 综合巡检脚本，覆盖 CPU/内存/环境/接口/路由协议/路由数量', 'cisco_nxos', 'inspection'),
    # 华为 VRPv5
    ('insp_huawei_vrp_full', '华为 VRPv5 综合巡检', 'display version\ndisplay cpu-usage\ndisplay memory-usage\ndisplay temperature all\ndisplay fan\ndisplay power\ndisplay interface brief\ndisplay bgp peer\ndisplay ospf peer brief\ndisplay ip routing-table statistics', '华为 VRPv5（S系列/AR/老NE）综合巡检脚本', 'huawei_vrp', 'inspection'),
    # 华为 VRPv8
    ('insp_huawei_vrpv8_full', '华为 VRPv8 综合巡检', 'display version\ndisplay cpu-usage\ndisplay memory-usage\ndisplay environment\ndisplay interface brief\ndisplay bgp peer\ndisplay ospf peer brief\ndisplay ip routing-table statistics', '华为 VRPv8（CE系列/新NE）综合巡检脚本', 'huawei_vrpv8', 'inspection'),
    # H3C Comware
    ('insp_h3c_comware_full', 'H3C Comware 综合巡检', 'display version\ndisplay cpu-usage\ndisplay memory\ndisplay environment\ndisplay fan\ndisplay power\ndisplay interface brief\ndisplay bgp peer ipv4\ndisplay ospf peer\ndisplay ip routing-table statistics', 'H3C Comware V7/V9 综合巡检脚本', 'h3c_comware', 'inspection'),
    # Juniper JunOS
    ('insp_juniper_junos_full', 'Juniper JunOS 综合巡检', 'show version\nshow chassis routing-engine\nshow chassis environment\nshow interfaces terse\nshow bgp summary\nshow ospf neighbor\nshow route summary', 'Juniper JunOS 综合巡检脚本（MX/EX/QFX/SRX 通用）', 'juniper_junos', 'inspection'),
    # Arista EOS
    ('insp_arista_eos_full', 'Arista EOS 综合巡检', 'show version\nshow processes top once\nshow memory\nshow environment temperature\nshow environment power\nshow interfaces status\nshow ip bgp summary\nshow ip ospf neighbor\nshow ip route summary', 'Arista EOS 综合巡检脚本', 'arista_eos', 'inspection')
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

        # --- Server / Host ---
        ('srv_cpu_load', 'CPU Load Average', 'CPU 系统负载', 'Server', 'cpu_load', '监控 1min 负载相对于核心数的比例', 'Shell', 'std_linux_load', 'std_linux_load', 80, 150, 'Linux', '', now, now),
        ('srv_cpu_util', 'CPU Utilization', 'CPU 使用率', 'Server', 'cpu_util', '监控整体 CPU 使用率 (0-100)', 'Shell', 'std_linux_cpu', 'std_linux_cpu', 90, 95, 'Linux', '', now, now),
        ('srv_mem_avail', 'Available Memory', '可用内存', 'Server', 'mem_avail', '监控系统内存使用百分比 (0-100)', 'Shell', 'std_linux_mem', 'std_linux_mem', 85, 95, 'Linux', '', now, now),
        ('srv_swap', 'Swap Usage', '交换分区使用率', 'Server', 'swap_util', '监控交换分区使用百分比 (0-100)', 'Shell', 'std_linux_swap', 'std_linux_swap', 70, 90, 'Linux', '', now, now),
        ('srv_iowait', 'Disk IO Wait', '磁盘 IO 等待 (IOWait)', 'Server', 'io_wait', '监控 CPU 等待 IO 时间占比 (阈值: >15% 告警)', 'Shell', 'std_linux_iowait', 'std_linux_iowait', 15, 30, 'Linux', '', now, now),
        ('srv_disk_util', 'Disk Space Usage', '磁盘空间利用率', 'Server', 'disk_util', '监控根分区空间占用 (0-100)', 'Shell', 'std_linux_disk', 'std_linux_disk', 90, 95, 'Linux', '', now, now),
        ('srv_disk_inode', 'Inode Utilization', 'Inode 使用率', 'Server', 'inode_util', '监控根分区 Inode 占用 (0-100)', 'Shell', 'std_linux_inode', 'std_linux_inode', 90, 95, 'Linux', '', now, now),
        ('srv_net_conns', 'Established Connections', '并发连接数', 'Server', 'tcp_conns', '监控 TCP Established 状态连接数', 'Shell', 'std_linux_conns', 'std_linux_conns', 5000, 10000, 'Linux', '', now, now),
        ('srv_process', 'Critical Processes', '核心进程监控', 'Server', 'process_health', '监控指定进程是否存在', 'Shell', 'std_linux_proc', 'std_linux_proc', 1, 0, 'Linux', '', now, now),
    ]


compliance_expected_values = {
    'compliance_cisco_ios_ntp': 'synchronized',
    'compliance_cisco_ios_aaa': 'aaa new-model',
    'compliance_cisco_ios_telnet': 'ssh',
    'compliance_cisco_ios_ssh_ver': '2.0',
    'compliance_cisco_ios_snmp': '',
}
