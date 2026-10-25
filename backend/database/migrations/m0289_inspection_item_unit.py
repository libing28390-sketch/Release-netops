"""Persist and backfill display units for built-in inspection metric values."""

from __future__ import annotations


VERSION = 289
NAME = "inspection_item_unit"

# Frozen backfill for the built-in catalog that existed when this migration was
# introduced. Keep this list independent from seed.py: seed definitions can
# evolve, while a tracked migration must remain deterministic for fresh and
# upgraded databases alike. Keys omitted here have no source-backed unit.
_BUILTIN_UNIT_BY_CHECK_KEY = {
    # Legacy shared network entries.
    "ping": "ms",
    "ssh": "ms",
    "cpu": "%",
    "memory": "%",
    "bgp_neighbor": "个邻居",
    # Linux metrics.
    "cpu_load": "%",
    "cpu_util": "%",
    "mem_avail": "%",
    "swap_util": "%",
    "io_wait": "%",
    "disk_util": "%",
    "inode_util": "%",
    "tcp_conns": "个连接",
    "process_health": "个进程",
    "oom_events": "次",
    "ro_mounts": "个挂载",
    "kernel_errs": "条",
    "zombie_procs": "个进程",
    "fd_util": "%",
    "net_errs": "次/秒",
    "ntp_desync": "状态",
    "dns_latency": "ms",
    "recent_reboot": "状态",
    "core_dumps_count": "个文件",
    "disk_io_await": "ms",
    "tcp_close_wait": "个连接",
    "tcp_retrans_pct": "%",
    # Network processor, memory, temperature, and component-state metrics.
    "cisco_ios_cpu": "%",
    "cisco_ios_mem": "%",
    "cisco_ios_temp": "°C",
    "cisco_ios_fan": "状态",
    "cisco_ios_psu": "状态",
    "cisco_nxos_cpu": "%",
    "cisco_nxos_mem": "%",
    "cisco_nxos_temp": "°C",
    "cisco_nxos_fan": "状态",
    "cisco_nxos_psu": "状态",
    "huawei_vrp_cpu": "%",
    "huawei_vrp_mem": "%",
    "huawei_vrp_temp": "°C",
    "huawei_vrp_fan": "状态",
    "huawei_vrp_psu": "状态",
    "huawei_vrpv8_cpu": "%",
    "huawei_vrpv8_mem": "%",
    "huawei_vrpv8_temp": "°C",
    "huawei_vrpv8_fan": "状态",
    "huawei_vrpv8_psu": "状态",
    "h3c_comware_cpu": "%",
    "h3c_comware_mem": "%",
    "h3c_comware_temp": "°C",
    "h3c_comware_fan": "状态",
    "h3c_comware_psu": "状态",
    "juniper_junos_cpu": "%",
    "juniper_junos_mem": "%",
    "juniper_junos_temp": "°C",
    "juniper_junos_fan": "状态",
    "juniper_junos_psu": "状态",
    "arista_eos_cpu": "%",
    "arista_eos_mem": "%",
    "arista_eos_temp": "°C",
    "arista_eos_fan": "状态",
    "arista_eos_psu": "状态",
    # Interface, routing, and route-count checks.
    "cisco_ios_intf_down": "个接口",
    "cisco_nxos_intf_down": "个接口",
    "huawei_vrp_intf_down": "个接口",
    "huawei_vrpv8_intf_down": "个接口",
    "h3c_comware_intf_down": "个接口",
    "juniper_junos_intf_down": "个接口",
    "arista_eos_intf_down": "个接口",
    "cisco_ios_bgp_down": "个邻居",
    "cisco_ios_ospf_down": "个邻居",
    "cisco_nxos_bgp_down": "个邻居",
    "cisco_nxos_ospf_down": "个邻居",
    "huawei_vrp_bgp_down": "个邻居",
    "huawei_vrp_ospf_down": "个邻居",
    "huawei_vrpv8_bgp_down": "个邻居",
    "huawei_vrpv8_ospf_down": "个邻居",
    "h3c_comware_bgp_down": "个邻居",
    "h3c_comware_ospf_down": "个邻居",
    "juniper_junos_bgp_down": "个邻居",
    "juniper_junos_ospf_down": "个邻居",
    "arista_eos_bgp_down": "个邻居",
    "arista_eos_ospf_down": "个邻居",
    "cisco_ios_route_total": "条",
    "huawei_vrp_route_total": "条",
    "huawei_vrpv8_route_total": "条",
    "h3c_comware_route_total": "条",
    "juniper_junos_route_total": "条",
    # Cisco compliance checks.
    "cisco_ios_ntp_status": "状态",
    "cisco_ios_syslog_count": "个日志主机",
    "cisco_ios_aaa_status": "状态",
    "cisco_ios_telnet_status": "状态",
    "cisco_ios_ssh_version": "版本",
    "cisco_ios_snmp_community": "状态",
}


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Inspection item unit migration requires PostgreSQL")
    cursor.execute("ALTER TABLE inspection_items ADD COLUMN IF NOT EXISTS unit TEXT")
    cursor.execute("UPDATE inspection_items SET unit = '' WHERE unit IS NULL")
    for check_key, unit in _BUILTIN_UNIT_BY_CHECK_KEY.items():
        cursor.execute(
            "UPDATE inspection_items SET unit = ? "
            "WHERE check_key = ? AND COALESCE(unit, '') = ''",
            (unit, check_key),
        )
    cursor.execute("ALTER TABLE inspection_items ALTER COLUMN unit SET DEFAULT ''")
    cursor.execute("ALTER TABLE inspection_items ALTER COLUMN unit SET NOT NULL")


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep display metadata during rollback; older code ignores the column.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
