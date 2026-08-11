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
          '统计非 Established 的 BGP 邻居', 'show ip bgp summary', 'cisco_nxos',
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
          '统计非 Established 的 BGP 邻居', 'display bgp peer ipv4 unicast', 'h3c_comware',
          1, 2, 'count', 'h3c_comware_display_bgp_peer_ipv4_unicast', 'STATE',
          parse_filter='{"field":"STATE","op":"!=","value":"Established"}')
    _item('net_h3c_route_total', 'H3C Comware Route Total', 'H3C Comware 路由总数', 'Network', 'h3c_comware_route_total',
          '路由总数（与上次对比）', 'display ip routing-table statistics', 'h3c_comware',
          10, 30, 'diff', 'h3c_comware_display_ip_routing_table_statistics', 'ACTIVE',
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
tcp_retrans_pct=$(awk '/^Tcp:/ {if ($13 != "") {out=$12; retrans=$13}} END {if (out > 0) printf "%.2f", (retrans/out)*100; else print 0}' /proc/net/snmp 2>/dev/null)
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

LOAD_WARN_PCT=80
MEM_WARN_PCT=85
MEM_CRIT_PCT=95
SWAP_WARN_PCT=50
DISK_WARN_PCT=90
DISK_CRIT_PCT=95
INODE_WARN_PCT=90
INODE_CRIT_PCT=95
IOWAIT_WARN_PCT=15
IOWAIT_CRIT_PCT=30
TCP_CONN_WARN=5000
TCP_CONN_CRIT=10000
SSH_FAIL_WARN_COUNT=20

TOTAL_ERRORS=0
TOTAL_WARNINGS=0

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
cpu_cores=$(grep -c ^processor /proc/cpuinfo)
load_avg=$(cat /proc/loadavg | awk '{print $1", "$2", "$3}')
load_1min=$(cat /proc/loadavg | awk '{print $1}')
load_pct=$(awk -v l="$load_1min" -v c="$cpu_cores" 'BEGIN { if (c>0) printf "%.2f", (l/c)*100; else print 0 }')
cpu_idle=$(top -bn1 | grep "Cpu(s)" | sed 's/.*, *\([0-9.]*\)%* id.*/\1/' | awk '{print $1}')
cpu_util=$(awk -v idle="$cpu_idle" 'BEGIN { printf "%.2f", 100 - idle }')
cpu_iowait=$(top -bn1 | grep "Cpu(s)" | sed 's/.*, *\([0-9.]*\)%* wa.*/\1/' | awk '{print $1}')
if [ -z "$cpu_iowait" ]; then
    cpu_iowait=$(vmstat 1 2 | tail -n 1 | awk '{print $16}')
fi

load_status="SUCCESS"
cpu_status="OK"
if (( $(echo "$load_pct >= 100" | bc -l) )); then
    load_status="ERROR"
    cpu_status="CRITICAL"
    TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif (( $(echo "$load_pct >= $LOAD_WARN_PCT" | bc -l) )); then
    load_status="WARNING"
    cpu_status="ERROR"
    TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi

print_section_header "${load_status}" "2. CPU 利用率与系统负载 (CPU & Load)"
echo "逻辑 CPU 核心: ${cpu_cores} 核"
echo "系统平均负载 (1/5/15 min): ${load_avg}"
echo "系统负载比例 (负载/核数): ${load_pct}%"
echo "CPU 整体利用率: ${cpu_util}%"
echo "CPU IO等待占比: ${cpu_iowait}%"

if [ "$load_status" = "ERROR" ]; then
    echo "[ERROR] 系统平均负载率已超过 100%，CPU 资源极度紧张！"
elif [ "$load_status" = "WARNING" ]; then
    echo "[WARNING] 系统平均负载率超过 ${LOAD_WARN_PCT}%，请关注系统资源消耗。"
fi

echo "--- CPU 占用前 5 的进程 ---"
ps -eo pid,ppid,%cpu,%mem,comm --sort=-%cpu | head -n 6

# 3. 内存与交换空间使用情况 (Memory & Swap)
mem_total=$(awk '/^MemTotal:/{print $2}' /proc/meminfo)
mem_avail=$(awk '/^MemAvailable:/{print $2; have_a=1} /^MemFree:/{f=$2} /^Buffers:/{b=$2} /^Cached:/{c=$2} END{if(!have_a) print f+b+c}' /proc/meminfo)
mem_util=$(awk -v t="$mem_total" -v a="$mem_avail" 'BEGIN { printf "%.2f", ((t-a)/t)*100 }')
swap_total=$(awk '/^SwapTotal:/{print $2}' /proc/meminfo)
swap_free=$(awk '/^SwapFree:/{print $2}' /proc/meminfo)
swap_util=0
if [ "$swap_total" -gt 0 ]; then
    swap_util=$(awk -v t="$swap_total" -v f="$swap_free" 'BEGIN { printf "%.2f", ((t-f)/t)*100 }')
fi
oom_events=$(dmesg -T 2>/dev/null | grep -i -E "oom-killer|out of memory" | tail -n 5)

mem_status="SUCCESS"
mem_level="OK"
if (( $(echo "$mem_util >= $MEM_CRIT_PCT" | bc -l) )) || [ -n "$oom_events" ]; then
    mem_status="ERROR"
    mem_level="CRITICAL"
    TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif (( $(echo "$mem_util >= $MEM_WARN_PCT" | bc -l) )) || (( $(echo "$swap_util >= $SWAP_WARN_PCT" | bc -l) )); then
    mem_status="WARNING"
    mem_level="ERROR"
    TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi

print_section_header "${mem_status}" "3. 内存与交换空间使用情况 (Memory & Swap)"
echo "物理内存: 总量 $(awk -v t="$mem_total" 'BEGIN {printf "%.2f GB", t/1024/1024}'), 可用 $(awk -v a="$mem_avail" 'BEGIN {printf "%.2f GB", a/1024/1024}') (使用率: ${mem_util}%)"
if [ "$swap_total" -gt 0 ]; then
    echo "交换空间: 总量 $(awk -v t="$swap_total" 'BEGIN {printf "%.2f GB", t/1024/1024}'), 已用 $(awk -v t="$swap_total" -v f="$swap_free" 'BEGIN {printf "%.2f GB", (t-f)/1024/1024}') (使用率: ${swap_util}%)"
else
    echo "交换空间: 未启用 Swap"
fi

if [ -n "$oom_events" ]; then
    echo "[ERROR] 检测到系统最近发生过 OOM Killer 杀进程事件："
    echo "${oom_events}"
elif (( $(echo "$mem_util >= $MEM_CRIT_PCT" | bc -l) )); then
    echo "[ERROR] 物理内存使用率已超过 ${MEM_CRIT_PCT}%，极易触发 OOM！"
elif (( $(echo "$mem_util >= $MEM_WARN_PCT" | bc -l) )); then
    echo "[WARNING] 物理内存使用率超过 ${MEM_WARN_PCT}%，可用内存较低。"
fi

if (( $(echo "$swap_util >= $SWAP_WARN_PCT" | bc -l) )); then
    echo "[WARNING] 交换分区使用率超过 ${SWAP_WARN_PCT}%，物理内存可能不足且开始换页！"
fi

echo "--- 内存占用前 5 的进程 ---"
ps -eo pid,ppid,%cpu,%mem,comm --sort=-%mem | head -n 6

# 4. 磁盘与 Inode 空间使用率 (Disk & Inode Space)
disk_status="SUCCESS"
disk_level="OK"
disk_messages=""
df_out=$(df -hP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2)
while read -r line; do
    fs=$(echo "$line" | awk '{print $1}')
    pct=$(echo "$line" | awk '{print $5}' | sed 's/%//')
    mnt=$(echo "$line" | awk '{print $6}')
    [ -z "$pct" ] && continue
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

ro_mounts=$(mount | grep -iE " \(ro," | grep -vE "type (tmpfs|devtmpfs|proc|sysfs|cgroup)")
if [ -n "$ro_mounts" ]; then
    disk_status="ERROR"
    disk_level="CRITICAL"
    disk_messages="${disk_messages}\n[ERROR] 检测到有文件系统处于只读模式 (Read-only):\n${ro_mounts}"
fi

inode_messages=""
inode_level="OK"
df_i_out=$(df -iP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2)
while read -r line; do
    fs=$(echo "$line" | awk '{print $1}')
    pct=$(echo "$line" | awk '{print $5}' | sed 's/%//')
    mnt=$(echo "$line" | awk '{print $6}')
    [ -z "$pct" ] && continue
    if [ "$pct" -ge "$INODE_CRIT_PCT" ]; then
        disk_status="ERROR"
        inode_level="CRITICAL"
        inode_messages="${inode_messages}\n[ERROR] 挂载点 ${mnt} Inode 已达 ${pct}% (超过严重阈值 ${INODE_CRIT_PCT}%)"
    elif [ "$pct" -ge "$INODE_WARN_PCT" ]; then
        if [ "$disk_status" != "ERROR" ]; then
            disk_status="WARNING"
        fi
        if [ "$inode_level" != "CRITICAL" ]; then
            inode_level="ERROR"
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
echo "--- 磁盘分区空间使用详情 ---"
df -hP | grep -vE "tmpfs|devtmpfs"
[ -n "$disk_messages" ] && echo -e "$disk_messages"

echo "--- Inode 使用详情 ---"
df -iP | grep -vE "tmpfs|devtmpfs"
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

if type ss >/dev/null 2>&1; then
    ss_out=$(ss -ant | tail -n +2)
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
    parse_proc_tcp "/proc/net/tcp"
    parse_proc_tcp "/proc/net/tcp6"
fi

tcp_total=$((tcp_estab + tcp_syn_sent + tcp_syn_recv + tcp_fin_wait1 + tcp_fin_wait2 + tcp_time_wait + tcp_close_wait + tcp_last_ack + tcp_closing))
tcp_status="SUCCESS"
tcp_estab_level="OK"
tcp_tw_level="OK"

# TCP 重传率 (RetransSegs / OutSegs * 100)，优先用 nstat，回退到 /proc/net/snmp
tcp_retrans_pct=0
if type nstat >/dev/null 2>&1; then
    _out_segs=$(nstat -az 2>/dev/null | awk '/TcpOutSegs/{print $2; exit}')
    _retr_segs=$(nstat -az 2>/dev/null | awk '/TcpRetransSegs/{print $2; exit}')
fi
if [ -z "$_out_segs" ] || [ -z "$_retr_segs" ]; then
    # /proc/net/snmp: 取 Tcp: 行，OutSegs 与 RetransSegs 列
    _snmp=$(awk '/^Tcp:/{if(h==""){h=$0}else{d=$0}} END{print h"\n"d}' /proc/net/snmp 2>/dev/null)
    _out_segs=$(echo "$_snmp" | awk 'NR==1{for(i=1;i<=NF;i++)if($i=="OutSegs")c=i} NR==2{print $c}')
    _retr_segs=$(echo "$_snmp" | awk 'NR==1{for(i=1;i<=NF;i++)if($i=="RetransSegs")c=i} NR==2{print $c}')
fi
if [[ "$_out_segs" =~ ^[0-9]+$ ]] && [ "$_out_segs" -gt 0 ] && [[ "$_retr_segs" =~ ^[0-9]+$ ]]; then
    tcp_retrans_pct=$(awk -v r="$_retr_segs" -v o="$_out_segs" 'BEGIN { printf "%.2f", (r/o)*100 }')
fi

if [ "$tcp_total" -ge "$TCP_CONN_CRIT" ] || [ "$tcp_close_wait" -ge 100 ]; then
    tcp_status="ERROR"
    tcp_estab_level="CRITICAL"
    TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif [ "$tcp_total" -ge "$TCP_CONN_WARN" ] || [ "$tcp_close_wait" -ge 20 ]; then
    tcp_status="WARNING"
    tcp_estab_level="ERROR"
    TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi

if [ "$tcp_time_wait" -ge 2000 ]; then
    tcp_tw_level="CRITICAL"
elif [ "$tcp_time_wait" -ge 1000 ]; then
    tcp_tw_level="ERROR"
fi

print_section_header "${tcp_status}" "5. TCP 连接状态监控 (TCP Connections)"
echo "ESTABLISHED 连接数 : ${tcp_estab}"
echo "TIME_WAIT 连接数   : ${tcp_time_wait}"
echo "CLOSE_WAIT 连接数  : ${tcp_close_wait}"
echo "LISTEN 端口数      : ${tcp_listen}"
echo "SYN_RECV 状态数    : ${tcp_syn_recv}"
echo "活动连接总数 (无L) : ${tcp_total}"
echo "TCP 重传率         : ${tcp_retrans_pct}%"

if [ "$tcp_total" -ge "$TCP_CONN_CRIT" ]; then
    echo "[ERROR] 并发 TCP 活动连接数已达 ${tcp_total}，超过严重限制 (${TCP_CONN_CRIT})！"
elif [ "$tcp_total" -ge "$TCP_CONN_WARN" ]; then
    echo "[WARNING] 并发 TCP 活动连接数较高，超过警告阈值 (${TCP_CONN_WARN})。"
fi

if [ "$tcp_close_wait" -ge 50 ]; then
    echo "[ERROR] 检测到 CLOSE_WAIT 数量达到 ${tcp_close_wait}，可能存在应用程序连接泄漏！"
elif [ "$tcp_close_wait" -ge 20 ]; then
    echo "[WARNING] CLOSE_WAIT 数量为 ${tcp_close_wait}，请关注应用释放连接情况。"
fi

# 6. 磁盘 I/O 延迟与吞吐 (Disk I/O Latency)
io_status="SUCCESS"
io_level="OK"
iowait_pct=$(cat /proc/stat | grep '^cpu ' | awk '{t=$2+$3+$4+$5+$6+$7+$8+$9+$10; io=$6; printf "%.2f", (io/t)*100}')
read_lat_ms=0
write_lat_ms=0

if type iostat >/dev/null 2>&1; then
    read_lat_ms=$(iostat -dx 1 2 | awk '/^[a-zA-Z]/{dev=$1; r_await=$(NF-4); w_await=$(NF-3); util=$NF} END{print r_await}')
    write_lat_ms=$(iostat -dx 1 2 | awk '/^[a-zA-Z]/{dev=$1; r_await=$(NF-4); w_await=$(NF-3); util=$NF} END{print w_await}')
    [[ ! "$read_lat_ms" =~ ^[0-9.]+$ ]] && read_lat_ms=0
    [[ ! "$write_lat_ms" =~ ^[0-9.]+$ ]] && write_lat_ms=0
fi

# 综合 I/O 延迟指标：取读/写平均延迟中的较大值 (ms)
io_latency_ms=$(awk -v r="$read_lat_ms" -v w="$write_lat_ms" 'BEGIN { printf "%.2f", (r>w?r:w) }')

if (( $(echo "$iowait_pct >= $IOWAIT_CRIT_PCT" | bc -l) )); then
    io_status="ERROR"
    io_level="CRITICAL"
    TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
elif (( $(echo "$iowait_pct >= $IOWAIT_WARN_PCT" | bc -l) )); then
    io_status="WARNING"
    io_level="ERROR"
    TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi

print_section_header "${io_status}" "6. 磁盘 I/O 延迟与吞吐 (Disk I/O Latency)"
echo "CPU IOWait 比例 : ${iowait_pct}%"
if type iostat >/dev/null 2>&1; then
    echo "读取平均延迟   : ${read_lat_ms} ms"
    echo "写入平均延迟   : ${write_lat_ms} ms"
    iostat -d -x 1 1
else
    echo "I/O 响应时间    : 无法获取 (iostat 未安装，请安装 sysstat 软件包以获取精确延迟数据)"
fi

if (( $(echo "$iowait_pct >= $IOWAIT_CRIT_PCT" | bc -l) )); then
    echo "[ERROR] CPU IOWait 达到 ${iowait_pct}%，磁盘 I/O 拥堵非常严重！"
elif (( $(echo "$iowait_pct >= $IOWAIT_WARN_PCT" | bc -l) )); then
    echo "[WARNING] CPU IOWait 达到 ${iowait_pct}%，磁盘读写出现等待。"
fi

# 7. 系统核心服务与进程 (Critical Services)
serv_status="SUCCESS"
failed_units=""
if type systemctl >/dev/null 2>&1; then
    failed_units=$(systemctl list-units --state=failed --no-legend)
    [ -n "$failed_units" ] && { serv_status="WARNING"; TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1)); }
fi

missing_procs=""
missing_procs_count=0
for p in sshd crond docker; do
    if ! pgrep -x "$p" >/dev/null && ! pgrep -f "$p" >/dev/null; then
        missing_procs_count=$((missing_procs_count + 1))
        if type systemctl >/dev/null 2>&1; then
            if ! systemctl is-active "$p" >/dev/null 2>&1; then
                missing_procs="${missing_procs}\n[ERROR] 关键服务进程 $p 未运行！"
                serv_status="ERROR"
            fi
        else
            missing_procs="${missing_procs}\n[ERROR] 关键服务进程 $p 未运行！"
            serv_status="ERROR"
        fi
    fi
done

if [ "$serv_status" = "ERROR" ]; then
    TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
fi

print_section_header "${serv_status}" "7. 系统核心服务与进程 (Critical Services)"
if type systemctl >/dev/null 2>&1; then
    echo "--- 失败的 systemd 服务单元 ---"
    [ -n "$failed_units" ] && echo "${failed_units}" || echo "无失败服务 (正常)"
fi

echo "--- 关键服务存活状态 ---"
for p in sshd crond docker; do
    if pgrep -x "$p" >/dev/null || pgrep -f "$p" >/dev/null; then
        echo "进程 $p: 运行中 [SUCCESS]"
    else
        echo "进程 $p: 未运行 [ERROR]"
    fi
done
[ -n "$missing_procs" ] && echo -e "$missing_procs"

# 8. 安全防线与入侵审计 (Security Audit)
sec_status="SUCCESS"
ssh_fail_count=0
sec_logs=""

if [ -f "/var/log/secure" ]; then
    ssh_fail_count=$(grep -i "failed" /var/log/secure | grep -c "invalid user\|password")
    sec_logs=$(grep -i "failed" /var/log/secure | grep "invalid user\|password" | tail -n 5)
elif [ -f "/var/log/auth.log" ]; then
    ssh_fail_count=$(grep -i "failed" /var/log/auth.log | grep -c "invalid user\|password")
    sec_logs=$(grep -i "failed" /var/log/auth.log | grep "invalid user\|password" | tail -n 5)
fi

if [ "$ssh_fail_count" -ge "$SSH_FAIL_WARN_COUNT" ]; then
    sec_status="WARNING"
    TOTAL_WARNINGS=$((TOTAL_WARNINGS + 1))
fi

print_section_header "${sec_status}" "8. 安全防线与入侵审计 (Security Audit)"
echo "最近 24小时 SSH 登录失败次数 : ${ssh_fail_count}"
[ -n "$sec_logs" ] && { echo "--- 最近登录失败日志片段 ---"; echo "${sec_logs}"; }
if [ "$ssh_fail_count" -ge "$SSH_FAIL_WARN_COUNT" ]; then
    echo "[WARNING] 检测到频繁的 SSH 登录失败，可能存在暴力破解风险，请核查安全组及防火墙配置！"
fi

# 9. 巡检汇总 (Summary)
overall_status="SUCCESS"
if [ "$TOTAL_ERRORS" -gt 0 ]; then
    overall_status="ERROR"
elif [ "$TOTAL_WARNINGS" -gt 0 ]; then
    overall_status="WARNING"
fi

max_usage=$(df -hP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | awk '{print $5}' | sed 's/%//' | sort -rn | head -1)
max_inode=$(df -iP | grep -vE "tmpfs|devtmpfs|cdrom" | tail -n +2 | awk '{print $5}' | sed 's/%//' | sort -rn | head -1)

echo "======================================================================"
echo "巡检汇总 (Summary)"
echo "======================================================================"
echo "发现严重错误 (ERROR)   : ${TOTAL_ERRORS} 个"
echo "发现警告信息 (WARNING) : ${TOTAL_WARNINGS} 个"
echo "综合健康评级           : [${overall_status}]"

echo "--- METRICS ---"
echo "cpu_load: ${load_pct}"
echo "cpu_util: ${cpu_util}"
echo "mem_avail: ${mem_util}"
echo "swap_util: ${swap_util}"
echo "io_wait: ${iowait_pct}"
echo "io_latency: ${io_latency_ms:-0}"
echo "disk_util: ${max_usage:-0}"
echo "inode_util: ${max_inode:-0}"
echo "tcp_conns: ${tcp_total}"
echo "tcp_retrans: ${tcp_retrans_pct:-0}"
echo "tcp_estab: ${tcp_estab}"
echo "tcp_time_wait: ${tcp_time_wait}"
echo "tcp_close_wait: ${tcp_close_wait}"
echo "tcp_syn_recv: ${tcp_syn_recv}"
echo "tcp_listen: ${tcp_listen}"
echo "service_sshd: $( (pgrep -x sshd >/dev/null || pgrep -f sshd >/dev/null) && echo 1 || echo 0 )"
echo "service_crond: $( (pgrep -x crond >/dev/null || pgrep -f crond >/dev/null) && echo 1 || echo 0 )"
echo "service_docker: $( (pgrep -x docker >/dev/null || pgrep -f docker >/dev/null) && echo 1 || echo 0 )"
echo "======================================================================"
""", 'Linux 主机综合巡检脚本，覆盖系统负载/CPU/内存/磁盘/TCP连接/IO延迟/关键服务及安全审计', 'Linux', 'inspection'),
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

        ('srv_cpu_load', 'CPU Load Average', 'CPU 系统负载', 'Server', 'cpu_load', '监控 1min 负载相对于核心数的比例', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 80, 150, 'Linux', '', now, now),
        ('srv_cpu_util', 'CPU Utilization', 'CPU 使用率', 'Server', 'cpu_util', '监控整体 CPU 使用率 (0-100)', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 90, 95, 'Linux', '', now, now),
        ('srv_mem_avail', 'Available Memory', '可用内存', 'Server', 'mem_avail', '监控系统内存使用百分比 (0-100)', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 85, 95, 'Linux', '', now, now),
        ('srv_swap', 'Swap Usage', '交换分区使用率', 'Server', 'swap_util', '监控交换分区使用百分比 (0-100)', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 70, 90, 'Linux', '', now, now),
        ('srv_iowait', 'Disk IO Wait', '磁盘 IO 等待 (IOWait)', 'Server', 'io_wait', '监控 CPU 等待 IO 时间占比 (阈值: >15% 告警)', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 15, 30, 'Linux', '', now, now),
        ('srv_disk_util', 'Disk Space Usage', '磁盘空间利用率', 'Server', 'disk_util', '监控根分区空间占用 (0-100)', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 90, 95, 'Linux', '', now, now),
        ('srv_disk_inode', 'Inode Utilization', 'Inode 使用率', 'Server', 'inode_util', '监控根分区 Inode 占用 (0-100)', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 90, 95, 'Linux', '', now, now),
        ('srv_net_conns', 'Established Connections', '并发连接数', 'Server', 'tcp_conns', '监控 TCP Established 状态连接数', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 5000, 10000, 'Linux', '', now, now),
        ('srv_process', 'Critical Processes', '核心进程监控', 'Server', 'process_health', '监控指定进程是否存在', 'Shell', 'std_linux_integrated', 'std_linux_integrated', None, 1, 'Linux', '', now, now),
        ('srv_oom_events', 'OOM Killer Events', 'OOM 杀进程事件数', 'Server', 'oom_events', '监控系统最近是否触发过 OOM-killer 强制杀死过进程', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 1, 5, 'Linux', '', now, now),
        ('srv_ro_mounts', 'Read-only Mounts', '只读挂载文件系统数', 'Server', 'ro_mounts', '监控是否存在只读挂载的文件系统，防止硬盘故障', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 1, 1, 'Linux', '', now, now),
        ('srv_kernel_errs', 'Kernel Error Log Count', '内核严重报错日志数', 'Server', 'kernel_errs', '监控系统内核报错日志数量 (dmesg)', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 1, 10, 'Linux', '', now, now),
        ('srv_zombie_procs', 'Zombie Processes', '僵尸进程数', 'Server', 'zombie_procs', '监控未能被正常回收的僵尸进程占用量', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 2, 5, 'Linux', '', now, now),
        ('srv_fd_util', 'File Descriptor Utilization %', '文件句柄使用率', 'Server', 'fd_util', '监控系统已开启文件句柄数占上限的比例', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 80, 90, 'Linux', '', now, now),
        ('srv_net_errs', 'Network Interface Errors/Drops', '网卡丢包与报错数', 'Server', 'net_errs', '监测系统所有网卡接口 errors 和 dropped 的总计数', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 10, 100, 'Linux', '', now, now),
        ('srv_ntp_desync', 'NTP Desync Status', 'NTP 时间失步状态', 'Server', 'ntp_desync', '监控 NTP 本地时钟是否同步 (0=同步, 1=失步/失败)', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 1, 1, 'Linux', '', now, now),
        ('srv_dns_latency', 'DNS Resolution Latency', 'DNS 解析延迟 (ms)', 'Server', 'dns_latency', '监控域名解析延迟 (单位: 毫秒，超时失败为 9999)', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 1000, 5000, 'Linux', '', now, now),
        ('srv_recent_reboot', 'Recent Reboot Alert', '系统最近重启告警', 'Server', 'recent_reboot', '监控系统最近 15 分钟内是否重启过 (0=否, 1=是)', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 1, 1, 'Linux', '', now, now),
        ('srv_core_dumps_count', 'Core Dump Files', 'CoreDump 崩溃文件数', 'Server', 'core_dumps_count', '监控系统关键目录和临时目录下崩溃文件数', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 1, 5, 'Linux', '', now, now),
        ('srv_disk_io_await', 'Disk I/O Await Latency', '磁盘 I/O 等待延迟 (ms)', 'Server', 'disk_io_await', '监控系统磁盘平均读写响应等待耗时 (毫秒)', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 20, 50, 'Linux', '', now, now),
        ('srv_tcp_close_wait', 'TCP CLOSE_WAIT Connections', 'TCP CLOSE_WAIT 异常连接数', 'Server', 'tcp_close_wait', '监控系统处于 CLOSE_WAIT 异常未关闭状态的 TCP 连接数', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 50, 200, 'Linux', '', now, now),
        ('srv_tcp_retrans_pct', 'TCP Retransmission Ratio %', 'TCP 协议栈重传段比例', 'Server', 'tcp_retrans_pct', '监控 TCP 协议栈中重传的报文比例 (%)', 'Shell', 'std_linux_integrated', 'std_linux_integrated', 2, 5, 'Linux', '', now, now),
    ]


compliance_expected_values = {
    'compliance_cisco_ios_ntp': 'synchronized',
    'compliance_cisco_ios_aaa': 'aaa new-model',
    'compliance_cisco_ios_telnet': 'ssh',
    'compliance_cisco_ios_ssh_ver': '2.0',
    'compliance_cisco_ios_snmp': '',
}
