"""Use the same short action labels as the quick-query cards."""

from __future__ import annotations


VERSION = 178
NAME = "unify_platform_action_labels"


ACTION_LABELS = {
    "get_version": ("设备信息", "Device Information"),
    "get_lldp_neighbors": ("LLDP邻居", "LLDP Neighbors"),
    "get_interface_brief": ("接口状态", "Interface Status"),
    "get_interfaces": ("接口详情", "Interface Details"),
    "get_ip_interfaces": ("三层接口", "Layer 3 Interfaces"),
    "get_link_aggregation": ("Eth-Trunk/链路聚合", "Eth-Trunk / Link Aggregation"),
    "get_bfd_sessions": ("BFD会话", "BFD Sessions"),
    "get_ntp_status": ("NTP同步", "NTP Synchronization"),
    "get_logbuffer": ("日志概览", "Log Overview"),
    "get_interface_description": ("接口配置", "Interface Configuration"),
    "get_irf": ("IRF状态", "IRF Status"),
    "get_uptime": ("系统运行时间", "System Uptime"),
    "get_arp_table": ("ARP表", "ARP Table"),
    "get_mac_table": ("MAC表", "MAC Table"),
    "get_vlan_table": ("VLAN", "VLAN"),
    "get_route_table": ("路由表", "Routing Table"),
    "get_bgp_neighbors": ("BGP邻居", "BGP Neighbors"),
    "get_ospf_neighbors": ("OSPF邻居", "OSPF Neighbors"),
    "get_isis_neighbors": ("ISIS邻居", "ISIS Neighbors"),
    "get_stp": ("STP状态", "STP Status"),
    "get_transceivers": ("光模块状态", "Transceiver Status"),
    "get_cpu": ("CPU状态", "CPU Status"),
    "get_memory": ("内存状态", "Memory Status"),
    "get_fans": ("风扇状态", "Fan Status"),
    "get_power": ("电源状态", "Power Status"),
    "get_temperature": ("环境温度", "Environment Temperature"),
    "get_clock": ("系统时钟", "System Clock"),
    "get_running_config": ("运行配置", "Running Configuration"),
    "get_startup_config": ("启动配置", "Startup Configuration"),
}


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    try:
        cursor.execute("SELECT 1 FROM action_definitions LIMIT 1")
    except Exception:
        return
    for action_code, (name_zh, name_en) in ACTION_LABELS.items():
        cursor.execute(
            "UPDATE action_definitions SET name_zh = ?, name_en = ? WHERE action_code = ?",
            (name_zh, name_en, action_code),
        )


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
