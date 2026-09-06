"""Platform registry and the single read-only action execution boundary.

The registry deliberately stores platform identity separately from the
connection implementation and the parser platform.  Consumers should resolve
an action through :func:`execute_platform_action` instead of maintaining
vendor-specific command fallbacks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from database import get_db_connection
from services.playbook_output_service import protect_output

logger = logging.getLogger(__name__)

PLATFORM_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
TEMPLATE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
ALLOWED_CONNECTION_DRIVERS = {
    "netmiko", "scrapli", "mock", "cisco_ios", "huawei_vrp", "hp_comware",
    "juniper_junos", "arista_eos", "zte_zxros", "ruijie_os", "dptech_ios", "maipu",
    "raisecom_ros",
}
CONNECTION_DRIVER_TO_IMPLEMENTATION = {
    "cisco_ios": "netmiko", "huawei_vrp": "netmiko", "hp_comware": "netmiko",
    "juniper_junos": "netmiko", "arista_eos": "netmiko", "zte_zxros": "netmiko",
    "ruijie_os": "netmiko", "dptech_ios": "netmiko", "maipu": "netmiko",
    "raisecom_ros": "netmiko",
}

ACTION_DEFINITIONS: tuple[dict[str, Any], ...] = (
    # Vendor/model are profile metadata or optional device facts; many
    # Comware version banners expose only the product name and software
    # version. Requiring them at the parser boundary made valid V5/V7/V9
    # output fail before discovery could use the version field.
    {"action_code": "get_version", "name_zh": "设备信息", "name_en": "Device Information", "purpose": "设备版本和型号", "risk": "low", "consumers": ["discovery", "inspection", "automation"], "fields": ["version"], "optional_fields": ["vendor", "model"], "max_records": 8},
    {"action_code": "get_lldp_neighbors", "name_zh": "LLDP邻居", "name_en": "LLDP Neighbors", "purpose": "拓扑邻居发现", "risk": "low", "consumers": ["topology", "discovery"], "fields": ["local_interface", "remote_device", "remote_interface"], "max_records": 5000},
    {"action_code": "get_interface_brief", "name_zh": "接口状态", "name_en": "Interface Status", "purpose": "接口状态采集", "risk": "low", "consumers": ["cmdb", "inspection"], "fields": ["interface"], "optional_fields": ["admin_status", "oper_status", "ip_address"], "max_records": 2000},
    {"action_code": "get_interfaces", "name_zh": "接口详情", "name_en": "Interface Details", "purpose": "接口详情采集", "risk": "low", "consumers": ["cmdb", "inspection"], "fields": ["interface", "description", "speed", "mac_address"], "max_records": 2000},
    {"action_code": "get_ip_interfaces", "name_zh": "三层接口", "name_en": "Layer 3 Interfaces", "purpose": "接口 IP 采集", "risk": "low", "consumers": ["cmdb", "ip_locator"], "fields": ["interface", "ip_address", "prefix_length"], "max_records": 2000},
    {"action_code": "get_link_aggregation", "name_zh": "Eth-Trunk/链路聚合", "name_en": "Eth-Trunk / Link Aggregation", "purpose": "聚合口采集", "risk": "low", "consumers": ["topology", "cmdb"], "fields": ["group", "interface", "member"], "max_records": 1000},
    {"action_code": "get_bfd_sessions", "name_zh": "BFD会话", "name_en": "BFD Sessions", "purpose": "BFD 会话采集", "risk": "low", "consumers": ["inspection", "topology"], "fields": ["local_discriminator", "remote_discriminator", "source_ip", "destination_ip", "status", "holdtime", "interface"], "max_records": 2000},
    {"action_code": "get_ntp_status", "name_zh": "NTP同步", "name_en": "NTP Synchronization", "purpose": "NTP 同步状态采集", "risk": "low", "consumers": ["inspection", "monitoring"], "fields": ["clock_status", "clock_stratum", "reference_clock_id"], "optional_fields": ["service_status", "reference_time", "poll_interval", "clock_jitter", "stability", "root_delay", "root_dispersion"], "max_records": 8},
    {"action_code": "get_logbuffer", "name_zh": "日志概览", "name_en": "Log Overview", "purpose": "设备日志采集", "risk": "low", "consumers": ["inspection", "automation"], "fields": ["timestamp", "hostname", "module", "severity", "mnemonic"], "optional_fields": ["message"], "max_records": 5000},
    {"action_code": "get_interface_description", "name_zh": "接口配置", "name_en": "Interface Configuration", "purpose": "接口描述和状态采集", "risk": "low", "consumers": ["topology", "cmdb", "inspection"], "fields": ["interface", "link", "protocol"], "optional_fields": ["primary_ip", "main_ip", "description", "speed", "duplex", "type", "pvid", "vlan_id"], "max_records": 5000},
    {"action_code": "get_irf", "name_zh": "IRF状态", "name_en": "IRF Status", "purpose": "IRF/堆叠成员采集", "risk": "low", "consumers": ["topology", "inspection"], "fields": ["member_id", "role", "priority", "cpu_mac", "description"], "max_records": 256},
    {"action_code": "get_uptime", "name_zh": "系统运行时间", "name_en": "System Uptime", "purpose": "设备运行时间采集", "risk": "low", "consumers": ["inspection", "monitoring"], "fields": ["uptime"], "max_records": 8},
    {"action_code": "get_arp_table", "name_zh": "ARP表", "name_en": "ARP Table", "purpose": "ARP 采集", "risk": "low", "consumers": ["ip_locator", "collection"], "fields": ["ip", "mac", "interface"], "max_records": 10000},
    {"action_code": "get_mac_table", "name_zh": "MAC表", "name_en": "MAC Table", "purpose": "MAC 采集", "risk": "low", "consumers": ["ip_locator", "collection"], "fields": ["mac", "vlan", "interface"], "max_records": 10000},
    {"action_code": "get_vlan_table", "name_zh": "VLAN", "name_en": "VLAN", "purpose": "VLAN 采集", "risk": "low", "consumers": ["collection", "inspection"], "fields": ["vlan", "name"], "optional_fields": ["status", "ports"], "max_records": 4096},
    {"action_code": "get_route_table", "name_zh": "路由表", "name_en": "Routing Table", "purpose": "路由采集", "risk": "low", "consumers": ["collection", "inspection"], "fields": ["prefix", "next_hop", "interface"], "max_records": 20000},
    {"action_code": "get_bgp_neighbors", "name_zh": "BGP邻居", "name_en": "BGP Neighbors", "purpose": "BGP 邻居采集", "risk": "low", "consumers": ["inspection"], "fields": ["neighbor", "asn", "state"], "max_records": 1000},
    {"action_code": "get_ospf_neighbors", "name_zh": "OSPF邻居", "name_en": "OSPF Neighbors", "purpose": "OSPF 邻居采集", "risk": "low", "consumers": ["inspection"], "fields": ["neighbor", "state", "interface"], "max_records": 1000},
    {"action_code": "get_isis_neighbors", "name_zh": "ISIS邻居", "name_en": "ISIS Neighbors", "purpose": "ISIS 邻居采集", "risk": "low", "consumers": ["topology", "inspection"], "fields": ["neighbor", "state", "interface", "system_id", "level"], "max_records": 1000},
    {"action_code": "get_stp", "name_zh": "STP状态", "name_en": "STP Status", "purpose": "二层生成树状态采集", "risk": "low", "consumers": ["topology", "inspection"], "fields": ["interface", "state", "role", "instance", "designated_bridge"], "max_records": 5000},
    {"action_code": "get_transceivers", "name_zh": "光模块状态", "name_en": "Transceiver Status", "purpose": "光模块采集", "risk": "low", "consumers": ["inspection"], "fields": ["interface", "vendor", "serial"], "max_records": 2000},
    {"action_code": "get_cpu", "name_zh": "CPU状态", "name_en": "CPU Status", "purpose": "CPU 健康度", "risk": "low", "consumers": ["inspection", "monitoring"], "fields": ["usage"], "max_records": 32},
    {"action_code": "get_memory", "name_zh": "内存状态", "name_en": "Memory Status", "purpose": "内存健康度", "risk": "low", "consumers": ["inspection", "monitoring"], "fields": ["usage", "total"], "max_records": 32},
    {"action_code": "get_fans", "name_zh": "风扇状态", "name_en": "Fan Status", "purpose": "风扇健康度", "risk": "low", "consumers": ["inspection"], "fields": ["name", "status"], "max_records": 128},
    {"action_code": "get_power", "name_zh": "电源状态", "name_en": "Power Status", "purpose": "电源健康度", "risk": "low", "consumers": ["inspection"], "fields": ["name", "status"], "max_records": 128},
    {"action_code": "get_temperature", "name_zh": "环境温度", "name_en": "Environment Temperature", "purpose": "温度健康度", "risk": "low", "consumers": ["inspection", "monitoring"], "fields": ["temperature"], "optional_fields": ["sensor", "status", "slot", "sensor_id", "lower", "warning", "alarm", "lower_limit", "warning_limit", "alarm_limit"], "max_records": 128},
    {"action_code": "get_clock", "name_zh": "系统时钟", "name_en": "System Clock", "purpose": "设备时间", "risk": "low", "consumers": ["inspection"], "fields": ["clock", "timezone"], "max_records": 8},
    {"action_code": "get_running_config", "name_zh": "运行配置", "name_en": "Running Configuration", "purpose": "配置备份和审计", "risk": "sensitive", "consumers": ["configuration", "inspection"], "fields": ["configuration"], "max_records": 1},
    {"action_code": "get_startup_config", "name_zh": "获取启动配置", "name_en": "Startup Configuration", "purpose": "启动配置备份和审计", "risk": "sensitive", "consumers": ["configuration", "inspection"], "fields": ["configuration"], "max_records": 1},
)

PARAMETERIZED_ACTION_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"action_code": "get_route_table_vrf", "name_zh": "VRF 路由表", "name_en": "Get VRF Route Table", "purpose": "Collect routes in an explicit VRF", "risk": "low", "consumers": ["diagnostics", "collection"], "fields": ["prefix", "next_hop", "interface"], "optional_fields": ["vrf_name"], "field_types": {"prefix": "string", "next_hop": "string", "interface": "string", "vrf_name": "string"}, "parameters": {"vrf": "string"}, "max_records": 20000},
    {"action_code": "get_arp_table_vrf", "name_zh": "VRF ARP 表", "name_en": "Get VRF ARP Table", "purpose": "Collect ARP entries in an explicit VRF", "risk": "low", "consumers": ["diagnostics", "ip_locator", "collection"], "fields": ["ip", "mac", "interface"], "optional_fields": ["vlan", "vrf_name"], "field_types": {"ip": "string", "mac": "string", "interface": "string", "vlan": "integer", "vrf_name": "string"}, "parameters": {"vrf": "string"}, "max_records": 10000},
    {"action_code": "get_mac_table_vrf", "name_zh": "VRF MAC 表", "name_en": "Get VRF MAC Table", "purpose": "Collect MAC entries in an explicit VRF", "risk": "low", "consumers": ["diagnostics", "ip_locator", "collection"], "fields": ["mac", "vlan", "interface"], "optional_fields": ["type", "vrf_name"], "field_types": {"mac": "string", "vlan": "integer", "interface": "string", "type": "string", "vrf_name": "string"}, "parameters": {"vrf": "string"}, "max_records": 10000},
    {"action_code": "get_bgp_neighbors_vrf", "name_zh": "VRF BGP 邻居", "name_en": "Get VRF BGP Neighbors", "purpose": "Collect BGP peers in an explicit VRF", "risk": "low", "consumers": ["diagnostics", "inspection", "collection"], "fields": ["neighbor", "asn", "state"], "optional_fields": ["vrf_name", "uptime"], "field_types": {"neighbor": "string", "asn": "integer", "state": "string", "vrf_name": "string", "uptime": "string"}, "parameters": {"vrf": "string"}, "max_records": 1000},
    {"action_code": "get_bgp_routes", "name_zh": "BGP 路由表", "name_en": "Get BGP Routes", "purpose": "Collect the global BGP routing table", "risk": "low", "consumers": ["collection", "scheduler"], "fields": ["prefix", "next_hop", "metric", "as_path"], "optional_fields": ["local_pref", "weight", "origin", "is_best"], "field_types": {"prefix": "string", "next_hop": "string", "metric": "integer", "as_path": "string", "local_pref": "integer", "weight": "integer", "origin": "string", "is_best": "boolean"}, "max_records": 20000},
    {"action_code": "get_bgp_routes_vrf", "name_zh": "VRF BGP 路由表", "name_en": "Get VRF BGP Routes", "purpose": "Collect BGP routes in an explicit VRF", "risk": "low", "consumers": ["collection", "scheduler"], "fields": ["prefix", "next_hop", "metric", "as_path"], "optional_fields": ["local_pref", "weight", "origin", "is_best", "vrf_name"], "field_types": {"prefix": "string", "next_hop": "string", "metric": "integer", "as_path": "string", "local_pref": "integer", "weight": "integer", "origin": "string", "is_best": "boolean", "vrf_name": "string"}, "parameters": {"vrf": "string"}, "max_records": 20000},
)

# These actions intentionally return opaque text instead of structured
# records. Every other action is parsed at runtime by the exact concrete
# platform profile and command; a missing parser is reported as unmatched
# instead of being hidden by a cross-version fallback.
RAW_OUTPUT_ACTION_CODES = frozenset({
    "get_clock",
    "get_running_config",
    "get_startup_config",
})

# A valid read-only command may legitimately report that a feature is not
# configured.  Keep this allow-list explicit so a genuinely mismatched
# structured parser still fails closed instead of turning every empty parse
# into a successful action.
ALLOW_EMPTY_RESULT_ACTION_CODES = frozenset({
    "get_bfd_sessions",
})

DEFAULT_ACTION_DEVICE_TYPES = ["router", "switch", "firewall"]


def iter_action_definitions() -> tuple[dict[str, Any], ...]:
    """Return complete action metadata used by fresh and upgrade seeds."""
    items: list[dict[str, Any]] = []
    for item in ACTION_DEFINITIONS + PARAMETERIZED_ACTION_DEFINITIONS:
        fields = [str(field) for field in item.get("fields") or []]
        optional = [str(field) for field in item.get("optional_fields") or []]
        field_types = dict(item.get("field_types") or {})
        for field in fields + optional:
            field_types.setdefault(field, "string")
        items.append({
            **item,
            "device_types": list(item.get("device_types") or DEFAULT_ACTION_DEVICE_TYPES),
            "fields": fields,
            "optional_fields": optional,
            "field_types": field_types,
            "parameters": dict(item.get("parameters") or {}),
            "timeout_seconds": int(item.get("timeout_seconds") or 30),
            "raw_output_retention_days": int(item.get("raw_output_retention_days") or 1),
            "failure_output_retention_days": int(item.get("failure_output_retention_days") or 7),
        })
    return tuple(items)


SYSTEM_PROFILES: tuple[dict[str, Any], ...] = (
    {"platform_code": "cisco_ios", "name_zh": "Cisco IOS", "name_en": "Cisco IOS", "vendor": "Cisco", "connection_driver": "cisco_ios", "parser_platform": "cisco_ios"},
    {"platform_code": "huawei_vrp", "name_zh": "Huawei VRP", "name_en": "Huawei VRP", "vendor": "Huawei", "connection_driver": "huawei_vrp", "parser_platform": "huawei_vrp"},
    # Concrete vendor/version profiles are the authoritative targets used by
    # manual inventory binding.  The older family profiles above remain
    # available for backwards-compatible device records.
    {"platform_code": "huawei_vrp5", "name_zh": "华为 VRP V5", "name_en": "Huawei VRP V5", "vendor": "Huawei", "connection_driver": "huawei_vrp", "parser_platform": "huawei_vrp"},
    {"platform_code": "huawei_vrp8", "name_zh": "华为 VRP V8", "name_en": "Huawei VRP V8", "vendor": "Huawei", "connection_driver": "huawei_vrp", "parser_platform": "huawei_vrpv8"},
    {"platform_code": "huawei_vrp_unknown", "name_zh": "华为 VRP 未知版本", "name_en": "Huawei VRP Unknown", "vendor": "Huawei", "connection_driver": "huawei_vrp", "parser_platform": "huawei_vrp"},
    # The profile IDs/codes remain concrete so V3/V5/V7/V9 can carry different
    # commands and template releases.  Their public parser family is one
    # canonical H3C key; ``hp_comware`` remains only the Netmiko driver name.
    {"platform_code": "h3c_comware_v3", "name_zh": "华三 Comware V3", "name_en": "H3C Comware V3", "vendor": "H3C", "connection_driver": "hp_comware", "parser_platform": "h3c_comware"},
    {"platform_code": "hp_comware", "name_zh": "H3C Comware V5", "name_en": "H3C Comware V5", "vendor": "H3C", "connection_driver": "hp_comware", "parser_platform": "h3c_comware"},
    {"platform_code": "h3c_comware", "name_zh": "H3C Comware V7", "name_en": "H3C Comware V7", "vendor": "H3C", "connection_driver": "hp_comware", "parser_platform": "h3c_comware"},
    {"platform_code": "h3c_comware9", "name_zh": "H3C Comware V9", "name_en": "H3C Comware V9", "vendor": "H3C", "connection_driver": "hp_comware", "parser_platform": "h3c_comware"},
    {"platform_code": "h3c_comware_v5", "name_zh": "华三 Comware V5", "name_en": "H3C Comware V5", "vendor": "H3C", "connection_driver": "hp_comware", "parser_platform": "h3c_comware"},
    {"platform_code": "h3c_comware_v7", "name_zh": "华三 Comware V7", "name_en": "H3C Comware V7", "vendor": "H3C", "connection_driver": "hp_comware", "parser_platform": "h3c_comware"},
    {"platform_code": "h3c_comware_v9", "name_zh": "华三 Comware V9", "name_en": "H3C Comware V9", "vendor": "H3C", "connection_driver": "hp_comware", "parser_platform": "h3c_comware"},
    {"platform_code": "h3c_comware_unknown", "name_zh": "华三 Comware 未知版本", "name_en": "H3C Comware Unknown", "vendor": "H3C", "connection_driver": "hp_comware", "parser_platform": "h3c_comware"},
    {"platform_code": "juniper_junos", "name_zh": "Juniper Junos", "name_en": "Juniper Junos", "vendor": "Juniper", "connection_driver": "juniper_junos", "parser_platform": "juniper_junos"},
    {"platform_code": "arista_eos", "name_zh": "Arista EOS", "name_en": "Arista EOS", "vendor": "Arista", "connection_driver": "arista_eos", "parser_platform": "arista_eos"},
    {"platform_code": "zte_5900_v6", "name_zh": "中兴 5900 V6", "name_en": "ZTE 5900 V6", "vendor": "ZTE", "connection_driver": "zte_zxros", "parser_platform": "zte_zxros"},
    {"platform_code": "zte_zsrv2_v3", "name_zh": "中兴 ZSRV2 V3", "name_en": "ZTE ZSRV2 V3", "vendor": "ZTE", "connection_driver": "zte_zxros", "parser_platform": "zte_zxros"},
    {"platform_code": "zte_zxros", "name_zh": "中兴 ZXROS", "name_en": "ZTE ZXROS", "vendor": "ZTE", "connection_driver": "zte_zxros", "parser_platform": "zte_zxros"},
    {"platform_code": "zte_rosng", "name_zh": "中兴 ROSng", "name_en": "ZTE ROSng", "vendor": "ZTE", "connection_driver": "zte_zxros", "parser_platform": "zte_zxros"},
    {"platform_code": "zte_os_unknown", "name_zh": "中兴 未知系统", "name_en": "ZTE Unknown OS", "vendor": "ZTE", "connection_driver": "zte_zxros", "parser_platform": "zte_zxros"},
    {"platform_code": "raisecom_ros", "name_zh": "瑞斯康达 ROS", "name_en": "Raisecom ROS", "vendor": "Raisecom", "connection_driver": "raisecom_ros", "parser_platform": "raisecom_ros"},
    {"platform_code": "ruijie_s6k_rgos12", "name_zh": "锐捷 S6K RGOS 12", "name_en": "Ruijie S6K RGOS 12", "vendor": "Ruijie", "connection_driver": "ruijie_os", "parser_platform": "ruijie_rgos"},
    {"platform_code": "ruijie_eg_rgos11", "name_zh": "锐捷 EG RGOS 11", "name_en": "Ruijie EG RGOS 11", "vendor": "Ruijie", "connection_driver": "ruijie_os", "parser_platform": "ruijie_rgos"},
    {"platform_code": "ruijie_rgos_v10", "name_zh": "锐捷 RGOS V10", "name_en": "Ruijie RGOS V10", "vendor": "Ruijie", "connection_driver": "ruijie_os", "parser_platform": "ruijie_rgos"},
    {"platform_code": "ruijie_rgos_v11", "name_zh": "锐捷 RGOS V11", "name_en": "Ruijie RGOS V11", "vendor": "Ruijie", "connection_driver": "ruijie_os", "parser_platform": "ruijie_rgos"},
    {"platform_code": "ruijie_rgos_v12", "name_zh": "锐捷 RGOS V12", "name_en": "Ruijie RGOS V12", "vendor": "Ruijie", "connection_driver": "ruijie_os", "parser_platform": "ruijie_rgos"},
    {"platform_code": "ruijie_rgos_unknown", "name_zh": "锐捷 RGOS 未知版本", "name_en": "Ruijie RGOS Unknown", "vendor": "Ruijie", "connection_driver": "ruijie_os", "parser_platform": "ruijie_rgos"},
    {"platform_code": "dptech_fw_s211", "name_zh": "迪普 FW S211", "name_en": "DPtech FW S211", "vendor": "DPtech", "connection_driver": "dptech_ios", "parser_platform": "dptech_ios"},
    {"platform_code": "dptech_conplat", "name_zh": "迪普 ConPlat", "name_en": "DPtech ConPlat", "vendor": "DPtech", "connection_driver": "dptech_ios", "parser_platform": "dptech_ios"},
    {"platform_code": "dptech_conplat_unknown", "name_zh": "迪普 ConPlat 未知系统", "name_en": "DPtech ConPlat Unknown", "vendor": "DPtech", "connection_driver": "dptech_ios", "parser_platform": "dptech_ios"},
    {"platform_code": "maipu_s3330_v9", "name_zh": "迈普 S3330 V9", "name_en": "Maipu S3330 V9", "vendor": "Maipu", "connection_driver": "maipu", "parser_platform": "maipu"},
    {"platform_code": "maipu_mypower_v6", "name_zh": "迈普 MyPower V6", "name_en": "Maipu MyPower V6", "vendor": "Maipu", "connection_driver": "maipu", "parser_platform": "maipu"},
    {"platform_code": "maipu_mypower_v8", "name_zh": "迈普 MyPower V8", "name_en": "Maipu MyPower V8", "vendor": "Maipu", "connection_driver": "maipu", "parser_platform": "maipu"},
    {"platform_code": "maipu_mypower_v9", "name_zh": "迈普 MyPower V9", "name_en": "Maipu MyPower V9", "vendor": "Maipu", "connection_driver": "maipu", "parser_platform": "maipu"},
    {"platform_code": "maipu_mypower_unknown", "name_zh": "迈普 MyPower 未知版本", "name_en": "Maipu MyPower Unknown", "vendor": "Maipu", "connection_driver": "maipu", "parser_platform": "maipu"},
)

PLATFORM_ALIASES = {
    "cisco": "cisco_ios", "ios": "cisco_ios", "huawei": "huawei_vrp", "vrp": "huawei_vrp",
    "huawei_vrpv8": "huawei_vrp", "h3c": "h3c_comware", "comware": "h3c_comware",
    "h3c_comware": "h3c_comware",
    "juniper": "juniper_junos",
    "junos": "juniper_junos", "arista": "arista_eos", "eos": "arista_eos", "zte": "zte_5900_v6",
    "zte_zxros": "zte_5900_v6", "ruijie": "ruijie_s6k_rgos12", "ruijie_os": "ruijie_s6k_rgos12",
    "ruijie_rgos": "ruijie_s6k_rgos12", "dptech": "dptech_fw_s211", "dptech_ios": "dptech_fw_s211",
    "maipu": "maipu_s3330_v9",
    "raisecom": "raisecom_ros", "瑞斯康达": "raisecom_ros",
}

PLATFORM_CATALOG_METADATA: dict[str, dict[str, str]] = {
    "huawei_vrp5": {"catalog_vendor": "huawei", "platform_family": "huawei_vrp", "version": "v5"},
    "huawei_vrp8": {"catalog_vendor": "huawei", "platform_family": "huawei_vrp", "version": "v8"},
    "huawei_vrp_unknown": {"catalog_vendor": "huawei", "platform_family": "huawei_vrp", "version": "unknown"},
    "h3c_comware_v3": {"catalog_vendor": "h3c", "platform_family": "h3c_comware", "version": "v3"},
    "h3c_comware_v5": {"catalog_vendor": "h3c", "platform_family": "h3c_comware", "version": "v5"},
    "h3c_comware_v7": {"catalog_vendor": "h3c", "platform_family": "h3c_comware", "version": "v7"},
    "h3c_comware_v9": {"catalog_vendor": "h3c", "platform_family": "h3c_comware", "version": "v9"},
    "h3c_comware_unknown": {"catalog_vendor": "h3c", "platform_family": "h3c_comware", "version": "unknown"},
    "maipu_mypower_v6": {"catalog_vendor": "maipu", "platform_family": "maipu_mypower", "version": "v6"},
    "maipu_mypower_v8": {"catalog_vendor": "maipu", "platform_family": "maipu_mypower", "version": "v8"},
    "maipu_mypower_v9": {"catalog_vendor": "maipu", "platform_family": "maipu_mypower", "version": "v9"},
    "maipu_mypower_unknown": {"catalog_vendor": "maipu", "platform_family": "maipu_mypower", "version": "unknown"},
    "ruijie_rgos_v10": {"catalog_vendor": "ruijie", "platform_family": "ruijie_rgos", "version": "v10"},
    "ruijie_rgos_v11": {"catalog_vendor": "ruijie", "platform_family": "ruijie_rgos", "version": "v11"},
    "ruijie_rgos_v12": {"catalog_vendor": "ruijie", "platform_family": "ruijie_rgos", "version": "v12"},
    "ruijie_rgos_unknown": {"catalog_vendor": "ruijie", "platform_family": "ruijie_rgos", "version": "unknown"},
    "zte_zxros": {"catalog_vendor": "zte", "platform_family": "zte_zxros", "version": "common"},
    "zte_rosng": {"catalog_vendor": "zte", "platform_family": "zte_rosng", "version": "common"},
    "zte_os_unknown": {"catalog_vendor": "zte", "platform_family": "zte_os_unknown", "version": "common"},
    "dptech_conplat": {"catalog_vendor": "dptech", "platform_family": "dptech_conplat", "version": "common"},
    "dptech_conplat_unknown": {"catalog_vendor": "dptech", "platform_family": "dptech_conplat_unknown", "version": "common"},
}

PLATFORM_FAMILY_ALIASES: dict[str, tuple[str, ...]] = {
    "huawei_vrp": ("huawei", "huawei_vrp"),
    "maipu_mypower": ("maipu", "maipu_mypower"),
    "ruijie_rgos": ("ruijie", "ruijie_os", "ruijie_rgos"),
    "dptech_conplat": ("dptech", "dptech_ios", "dptech_conplat"),
    "zte_zxros": ("zte", "zte_zxros"),
}


def _with_platform_catalog_metadata(profile: dict[str, Any]) -> dict[str, Any]:
    """Expose the same vendor/family/version contract as the TextFSM catalog."""
    code = str(profile.get("platform_code") or "").strip().lower()
    metadata = PLATFORM_CATALOG_METADATA.get(code)
    if metadata:
        return {**profile, **metadata}
    return {
        **profile,
        "catalog_vendor": str(profile.get("vendor") or "").strip().lower(),
        "platform_family": str(profile.get("parser_platform") or code).strip().lower(),
        "version": "common",
    }

# The commands are explicit data, never inferred from a requested vendor and
# never allowed to silently fall back to Cisco.
PLATFORM_ACTION_COMMANDS: dict[str, dict[str, str]] = {
    "cisco_ios": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbors", "get_interface_brief": "show ip interface brief", "get_interfaces": "show interfaces", "get_ip_interfaces": "show ip interface", "get_link_aggregation": "show etherchannel summary", "get_arp_table": "show ip arp", "get_mac_table": "show mac address-table", "get_vlan_table": "show vlan brief", "get_route_table": "show ip route", "get_bgp_neighbors": "show ip bgp summary", "get_ospf_neighbors": "show ip ospf neighbor", "get_isis_neighbors": "show isis neighbors", "get_stp": "show spanning-tree", "get_transceivers": "show interfaces transceiver", "get_cpu": "show processes cpu", "get_memory": "show processes memory", "get_fans": "show environment fan", "get_power": "show environment power", "get_temperature": "show environment temperature", "get_clock": "show clock", "get_running_config": "show running-config", "get_startup_config": "show startup-config"},
    "huawei_vrp": {"get_version": "display version", "get_lldp_neighbors": "display lldp neighbor brief", "get_interface_brief": "display interface brief", "get_interfaces": "display interface", "get_ip_interfaces": "display ip interface brief", "get_link_aggregation": "display eth-trunk", "get_arp_table": "display arp", "get_mac_table": "display mac-address", "get_vlan_table": "display vlan", "get_route_table": "display ip routing-table", "get_bgp_neighbors": "display bgp peer", "get_ospf_neighbors": "display ospf peer brief", "get_isis_neighbors": "display isis peer", "get_stp": "display stp brief", "get_transceivers": "display transceiver interface", "get_cpu": "display cpu-usage", "get_memory": "display memory-usage", "get_fans": "dis fan", "get_power": "display power", "get_temperature": "display temperature", "get_clock": "display clock", "get_running_config": "display current-configuration", "get_startup_config": "display saved-configuration"},
    "h3c_comware": {"get_version": "display version", "get_lldp_neighbors": "display lldp neighbor-information list", "get_interface_brief": "display interface brief", "get_interfaces": "display interface", "get_ip_interfaces": "display ip interface brief", "get_link_aggregation": "display link-aggregation verbose", "get_bfd_sessions": "display bfd session", "get_ntp_status": "display ntp-service status", "get_logbuffer": "display logbuffer", "get_interface_description": "display interface brief description", "get_irf": "display irf", "get_uptime": "display version", "get_arp_table": "display arp all", "get_mac_table": "display mac-address", "get_vlan_table": "display vlan brief", "get_route_table": "display ip routing-table", "get_bgp_neighbors": "display bgp peer ipv4 unicast", "get_ospf_neighbors": "display ospf peer", "get_isis_neighbors": "display isis peer", "get_stp": "display stp brief", "get_transceivers": "display transceiver interface", "get_cpu": "display cpu-usage", "get_memory": "display memory", "get_fans": "display fan", "get_power": "display power", "get_temperature": "display environment", "get_clock": "display clock", "get_running_config": "display current-configuration", "get_startup_config": "display saved-configuration"},
    "juniper_junos": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbors detail", "get_interfaces": "show interfaces detail", "get_interface_brief": "show interfaces terse", "get_ip_interfaces": "show interfaces terse", "get_route_table": "show route", "get_isis_neighbors": "show isis adjacency", "get_stp": "show spanning-tree bridge", "get_clock": "show system uptime", "get_running_config": "show configuration", "get_startup_config": "show configuration"},
    "arista_eos": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbors detail", "get_interface_brief": "show ip interface brief", "get_interfaces": "show interfaces", "get_ip_interfaces": "show ip interface", "get_link_aggregation": "show port-channel summary", "get_arp_table": "show arp", "get_mac_table": "show mac address-table", "get_vlan_table": "show vlan", "get_route_table": "show ip route", "get_bgp_neighbors": "show ip bgp summary", "get_ospf_neighbors": "show ip ospf neighbor", "get_isis_neighbors": "show isis neighbors", "get_stp": "show spanning-tree", "get_transceivers": "show interfaces transceiver", "get_cpu": "show processes top once", "get_memory": "show version", "get_clock": "show clock", "get_running_config": "show running-config", "get_startup_config": "show startup-config"},
    "ruijie_rgos": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbors", "get_interface_brief": "show interface brief", "get_interfaces": "show interfaces", "get_ip_interfaces": "show ip interface brief", "get_arp_table": "show arp", "get_mac_table": "show mac address-table", "get_vlan_table": "show vlan", "get_route_table": "show ip route", "get_bgp_neighbors": "show ip bgp neighbors", "get_ospf_neighbors": "show ip ospf neighbor", "get_isis_neighbors": "show isis neighbors", "get_stp": "show spanning-tree", "get_transceivers": "show interfaces transceiver", "get_cpu": "show cpu", "get_memory": "show memory", "get_fans": "show fan", "get_power": "show power", "get_temperature": "show temperature", "get_clock": "show clock", "get_running_config": "show running-config", "get_startup_config": "show startup-config"},
    "zte_zxros": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbor", "get_interface_brief": "show interface brief", "get_ip_interfaces": "show ip interface brief", "get_arp_table": "show arp", "get_mac_table": "show mac table", "get_route_table": "show ip forwarding route", "get_bgp_neighbors": "show ip bgp neighbors", "get_ospf_neighbors": "show ip ospf neighbor", "get_isis_neighbors": "show isis neighbors", "get_stp": "show spanning-tree", "get_transceivers": "show opticalinfo brief", "get_fans": "show fan", "get_power": "show power", "get_temperature": "show temperature detail", "get_clock": "show clock", "get_running_config": "show running-config", "get_startup_config": "show startup-config"},
    "raisecom_ros": {"get_version": "show version", "get_lldp_neighbors": "show lldp remote", "get_interface_brief": "show interface brief", "get_interfaces": "show interface", "get_ip_interfaces": "show ip interface brief", "get_arp_table": "show arp", "get_vlan_table": "show vlan", "get_route_table": "show ip route", "get_stp": "show spanning-tree", "get_clock": "show clock", "get_running_config": "show running-config", "get_startup_config": "show startup-config"},
    "dptech_ios": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbors", "get_interface_brief": "show interface status", "get_ip_interfaces": "show ip interface brief", "get_arp_table": "show arp all", "get_mac_table": "show mac-address-table", "get_vlan_table": "show vlan", "get_route_table": "show ip route", "get_stp": "show spanning-tree", "get_cpu": "show cpu-usage", "get_memory": "show memory", "get_temperature": "show environment", "get_ntp_status": "show ntp status", "get_bfd_sessions": "show bfd session", "get_logbuffer": "show logging operlog recent", "get_interface_description": "show ip interface brief", "get_clock": "show clock", "get_uptime": "show version", "get_running_config": "display current-configuration", "get_startup_config": "display saved-configuration"},
    "maipu": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbors", "get_interface_brief": "show interface brief", "get_ip_interfaces": "show ip interface brief", "get_arp_table": "show arp", "get_mac_table": "show mac address all", "get_vlan_table": "show vlan", "get_route_table": "show ip route", "get_bgp_neighbors": "show ip bgp summary", "get_ospf_neighbors": "show ip ospf neighbor", "get_isis_neighbors": "show isis neighbors", "get_stp": "show spanning-tree", "get_transceivers": "show optical all", "get_cpu": "show cpu monitor", "get_memory": "show memory utilization", "get_fans": "show system fan", "get_power": "show system power", "get_clock": "show clock", "get_running_config": "show running-config", "get_startup_config": "show startup-config"},
}

PLATFORM_ACTION_COMMANDS["cisco_ios"].update({
    "get_route_table_vrf": "show ip route vrf {{vrf}}",
    "get_arp_table_vrf": "show ip arp vrf {{vrf}}",
    "get_mac_table_vrf": "show mac address-table vrf {{vrf}}",
    "get_bgp_neighbors_vrf": "show ip bgp vrf {{vrf}} summary",
})
PLATFORM_ACTION_COMMANDS["huawei_vrp"].update({
    "get_route_table_vrf": "display ip routing-table vpn-instance {{vrf}}",
    "get_arp_table_vrf": "display arp vpn-instance {{vrf}}",
    "get_mac_table_vrf": "display mac-address vpn-instance {{vrf}}",
    "get_bgp_neighbors_vrf": "display bgp vpnv4 vpn-instance {{vrf}} peer",
})
PLATFORM_ACTION_COMMANDS["h3c_comware"].update({
    "get_route_table_vrf": "display ip routing-table vpn-instance {{vrf}}",
    "get_arp_table_vrf": "display arp vpn-instance {{vrf}}",
    "get_mac_table_vrf": "display mac-address vpn-instance {{vrf}}",
    "get_bgp_neighbors_vrf": "display bgp peer ipv4 vpn-instance {{vrf}}",
})
PLATFORM_ACTION_COMMANDS["arista_eos"].update({
    "get_route_table_vrf": "show ip route vrf {{vrf}}",
    "get_arp_table_vrf": "show arp vrf {{vrf}}",
    "get_mac_table_vrf": "show mac address-table vrf {{vrf}}",
    "get_bgp_neighbors_vrf": "show ip bgp vrf {{vrf}} summary",
    "get_bgp_routes": "show ip bgp",
    "get_bgp_routes_vrf": "show ip bgp vrf {{vrf}}",
})
PLATFORM_ACTION_COMMANDS["cisco_ios"].update({"get_bgp_routes": "show ip bgp", "get_bgp_routes_vrf": "show ip bgp vrf {{vrf}}"})
PLATFORM_ACTION_COMMANDS["huawei_vrp"].update({"get_bgp_routes": "display bgp routing-table", "get_bgp_routes_vrf": "display bgp vpnv4 vpn-instance {{vrf}} routing-table"})
PLATFORM_ACTION_COMMANDS["h3c_comware"].update({"get_bgp_routes": "display bgp routing-table ipv4 unicast", "get_bgp_routes_vrf": "display bgp vpnv4 vpn-instance {{vrf}} routing-table"})
PLATFORM_ACTION_COMMANDS["ruijie_rgos"].update({"get_bgp_routes": "show ip bgp", "get_bgp_routes_vrf": "show ip bgp vrf {{vrf}}"})

# Huawei VRP V8 uses the same published action catalog as the legacy VRP
# family while retaining a distinct parser namespace in the registry.
PLATFORM_ACTION_COMMANDS["huawei_vrpv8"] = dict(PLATFORM_ACTION_COMMANDS["huawei_vrp"])
PLATFORM_ACTION_COMMANDS["huawei_vrpv8"]["get_fans"] = "display fan"

# A parser platform describes the parser/driver family.  A platform profile
# is the concrete vendor + product/version identity.  Comware V5 has a small
# but important CLI difference from V7/V9 (notably BGP and ARP), so keep its
# action catalog explicit instead of making the transport driver decide it.
PROFILE_ACTION_COMMANDS: dict[str, dict[str, str]] = {
    "h3c_comware": {
        **PLATFORM_ACTION_COMMANDS["h3c_comware"],
        # The V7 grammar/fixture is registered for the command without the
        # optional ``unicast`` suffix. Keep the action and parser command
        # identical so a published action cannot bind the wrong grammar.
        "get_bgp_routes": "display bgp routing-table ipv4",
    },
}
# ``hp_comware`` is Netmiko's legacy H3C/Comware V5 driver name and is also a
# legacy system profile code in this application.  The explicit V5 profile
# uses the same catalog so old and new device bindings remain consistent.
PROFILE_ACTION_COMMANDS["hp_comware"] = {
    **PLATFORM_ACTION_COMMANDS["h3c_comware"],
    "get_arp_table": "display arp all",
    "get_bgp_neighbors": "display bgp peer",
    "get_bgp_routes": "display bgp routing-table",
}
PROFILE_ACTION_COMMANDS["h3c_comware_v5"] = dict(PROFILE_ACTION_COMMANDS["hp_comware"])
# Comware V3 is an older CLI generation.  Until a version-specific fixture
# is available, use the verified legacy V5 command forms rather than the V7
# address-family variants.
PROFILE_ACTION_COMMANDS["h3c_comware_v3"] = dict(PROFILE_ACTION_COMMANDS["hp_comware"])
PROFILE_ACTION_COMMANDS["h3c_comware9"] = dict(PROFILE_ACTION_COMMANDS["h3c_comware"])


def get_profile_action_commands(profile: dict[str, Any]) -> dict[str, str]:
    """Return the command catalog for one concrete profile.

    Profile-specific mappings are intentionally preferred over the parser
    family mapping.  Custom profiles have no implicit action catalog and must
    be mapped explicitly in their Draft Release.
    """
    platform_code = str(profile.get("platform_code") or "").strip().lower()
    if platform_code in PROFILE_ACTION_COMMANDS:
        return dict(PROFILE_ACTION_COMMANDS[platform_code])
    parser_platform = str(profile.get("parser_platform") or "").strip().lower()
    return dict(PLATFORM_ACTION_COMMANDS.get(parser_platform, {}))

_SENSITIVE_OUTPUT_PATTERNS = (
    re.compile(r"(\b(?:password|passwd|secret|community|token|api[-_ ]?key|private[-_ ]?key)\s*[:=]?\s*)([^\s,;]+)", re.IGNORECASE),
    re.compile(r"(\bsnmp-server\s+community\s+)([^\s]+)", re.IGNORECASE),
    re.compile(r"(\bauthorization\s+key\s+)([^\s]+)", re.IGNORECASE),
)
_ACTION_PARAMETER_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")
_ACTION_PARAMETER_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")

_ALLOWED_COMMAND_PREFIXES_BY_DRIVER = {
    "juniper_junos": {"show"},
    "cisco_ios": {"show", "get"},
    "huawei_vrp": {"display", "dis", "show", "get"},
    "hp_comware": {"display", "dis", "show", "get"},
    "arista_eos": {"show", "get"},
    "zte_zxros": {"show", "get"},
    "ruijie_os": {"show", "get"},
    "dptech_ios": {"show", "get"},
    "maipu": {"show", "get"},
    "netmiko": {"show", "display", "get"},
    "scrapli": {"show", "display", "get"},
    "mock": {"show", "display", "get"},
}

_ACTION_PARAMETER_ALLOWLIST = {
    "get_route_table": {"target", "vrf"},
    "get_arp_table": {"target", "vrf"},
    "get_mac_table": {"target", "mac", "vrf"},
    "get_bgp_neighbors": {"vrf"},
    "get_route_table_vrf": {"vrf"},
    "get_arp_table_vrf": {"vrf"},
    "get_mac_table_vrf": {"vrf"},
    "get_bgp_neighbors_vrf": {"vrf"},
    "get_bgp_routes_vrf": {"vrf"},
}


def _validate_action_parameter_contract(action_code: str, command: str) -> None:
    placeholders = set(_ACTION_PARAMETER_RE.findall(str(command or "")))
    allowed = _ACTION_PARAMETER_ALLOWLIST.get(action_code, set())
    unknown = sorted(placeholders - allowed)
    if unknown:
        raise PlatformRegistryError(
            "UNSUPPORTED_ACTION_PARAMETERS",
            f"Action {action_code} does not declare parameter(s): {', '.join(unknown)}",
        )

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "vendor": ("vendor", "vendor_name", "manufacturer", "manufacturer_name"),
    "model": ("model", "model_name", "product_model", "device"),
    "version": ("version", "software_version", "version_string", "release"),
    "interface": ("interface", "interface_name", "intf", "port", "port_name", "destination_port"),
    "local_interface": ("local_interface", "local_intf", "local_port", "local_port_name", "interface"),
    "remote_interface": ("remote_interface", "remote_intf", "remote_port", "neighbor_interface"),
    "remote_device": ("remote_device", "remote_hostname", "remote_system_name", "neighbor", "neighbor_name", "system_name"),
    # H3C/Huawei brief tables expose the two interface states as LINK and
    # PROTOCOL. Keep the registry contract in vendor-neutral names so the
    # same action can validate Comware V5/V7/V9 output.
    "admin_status": ("admin_status", "admin_state", "admin", "link", "phy"),
    "oper_status": ("oper_status", "oper_state", "line_protocol", "protocol_status", "protocol", "proto", "operate_status"),
    "status": ("status", "state", "health", "phy_status"),
    "ip_address": ("ip_address", "ip_addr", "ipv4_address", "primary_ip", "main_ip", "address"),
    "prefix_length": ("prefix_length", "prefix_len", "mask_length"),
    "mac_address": ("mac_address", "mac_addr", "hardware_address", "mac"),
    "description": ("description", "desc", "interface_description"),
    "speed": ("speed", "bandwidth", "link_speed"),
    "group": ("group", "bundle", "aggregation_group", "aggregate_interface", "trunk"),
    "member": ("member", "member_interface", "member_port", "ports", "interface"),
    "ip": ("ip", "ip_address", "ip_addr", "address"),
    "mac": ("mac", "mac_address", "mac_addr", "hardware_address", "destination_address"),
    "vlan": ("vlan", "vlan_id", "vlanid"),
    "name": ("name", "interface_name", "sensor_name", "module", "fan_id", "power_id", "device_id", "vlan_name"),
    "prefix": ("prefix", "network", "destination", "route"),
    "usage": ("usage", "cpu_5_sec", "system_cpu", "dataplane_cpu", "used_rate", "memory_using_percentage", "memory_using_pct"),
    "total": ("total", "total_kb", "total_bytes", "system_total_memory"),
    "next_hop": ("next_hop", "nexthop", "next_hop_ip", "gateway"),
    "neighbor": ("neighbor", "neighbor_id", "peer", "peer_address"),
    "asn": ("asn", "remote_as", "remote_asn", "peer_as"),
    "state": ("state", "status", "peer_state", "session_state"),
    "clock": ("clock", "time", "current_time"),
    "timezone": ("timezone", "time_zone", "tz"),
    "configuration": ("configuration", "config", "running_config", "output"),
}


class PlatformRegistryError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _checksum(value: Any) -> str:
    raw = value if isinstance(value, str) else _json(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def redact_raw_output(output: str) -> str:
    """Redact common credential material before raw output leaves the resolver."""
    redacted = str(output or "")
    for pattern in _SENSITIVE_OUTPUT_PATTERNS:
        redacted = pattern.sub(r"\1<redacted>", redacted)
    return redacted


def normalize_platform_code(value: str) -> str:
    code = str(value or "").strip().lower()
    return PLATFORM_ALIASES.get(code, code)


def platform_codes_match(device_platform: Any, profile_platform: Any, parser_platform: Any = None) -> bool:
    """Compare a public device platform with a Profile's parser platform.

    ``platform_code`` identifies a concrete Profile and may therefore differ
    between Comware generations.  It is not the value stored on the device.
    Callers that have the full Profile should pass ``parser_platform``;
    accepting the concrete system code as a fallback keeps this helper useful
    for small registry/import callers without exposing that code as a public
    platform alias.
    """
    device_code = str(device_platform or "").strip().lower()
    profile_code = str(profile_platform or "").strip().lower()
    parser_code = str(parser_platform or "").strip().lower()
    if not device_code or not (profile_code or parser_code):
        return False
    profile_parser_codes = {
        str(item.get("platform_code") or "").strip().lower(): str(item.get("parser_platform") or "").strip().lower()
        for item in SYSTEM_PROFILES
    }
    # A device normally stores the concrete Profile code (for example
    # ``param_lab`` or ``hp_comware``), while older rows may store the shared
    # parser/driver family. Accept either identity after normalisation; a
    # custom Profile must not be rejected merely because its parser family is
    # Cisco/Huawei/etc.
    candidates = {
        normalize_platform_code(value)
        for value in (profile_code, parser_code)
        if value
    }
    for value in (profile_code, parser_code):
        metadata = PLATFORM_CATALOG_METADATA.get(value)
        if not metadata:
            continue
        family = str(metadata.get("platform_family") or "").strip().lower()
        if family:
            candidates.add(family)
            candidates.update(PLATFORM_FAMILY_ALIASES.get(family, ()))
            if family.endswith("_unknown"):
                candidates.add(family[:-8])
    candidates.update(
        profile_parser_codes.get(value, value)
        for value in (profile_code, parser_code)
        if value
    )
    if device_code in {"h3c", "comware", "h3c_comware", "h3c_comware_v3", "h3c_comware_v5", "h3c_comware_v7", "h3c_comware_v9"}:
        device_code = "h3c_comware"
    candidates = {
        "h3c_comware" if value in {"h3c", "comware", "h3c_comware", "h3c_comware_v3", "h3c_comware_v5", "h3c_comware_v7", "h3c_comware_v9"} else value
        for value in candidates
    }
    return device_code in candidates or normalize_platform_code(device_code) in candidates


def validate_platform_code(value: str) -> str:
    code = str(value or "").strip().lower()
    if not PLATFORM_CODE_RE.fullmatch(code):
        raise PlatformRegistryError("INVALID_PLATFORM_CODE", "platform_code must match ^[a-z][a-z0-9_]{2,63}$")
    return code


def validate_template_code(value: str) -> str:
    code = str(value or "").strip().upper()
    if not TEMPLATE_CODE_RE.fullmatch(code):
        raise PlatformRegistryError("INVALID_TEMPLATE_CODE", "template_code must match ^[A-Z][A-Z0-9_]{0,63}$")
    return code


def is_safe_read_command(command: str, connection_driver: str) -> bool:
    command = str(command or "").strip()
    if not command or "\n" in command or "\r" in command or ";" in command or "&&" in command or "||" in command or "|" in command:
        return False
    if re.search(r"[<>`$]", command):
        return False
    prefix = command.split(None, 1)[0].lower()
    allowed_prefixes = _ALLOWED_COMMAND_PREFIXES_BY_DRIVER.get(connection_driver, {"show", "display", "get"})
    if prefix not in allowed_prefixes:
        return False
    return True


def _render_action_command(command: str, parameters: dict[str, Any] | None = None) -> str:
    """Render only explicitly declared scalar action parameters.

    Release commands may contain ``{{parameter}}`` placeholders.  Values are
    deliberately restricted to token-safe characters so parameterized actions
    cannot turn the resolver into a command injection surface.
    """
    template = str(command or "").strip()
    supplied = parameters or {}
    if not isinstance(supplied, dict):
        raise PlatformRegistryError("INVALID_ACTION_PARAMETERS", "Action parameters must be an object")
    if len(supplied) > 16:
        raise PlatformRegistryError("INVALID_ACTION_PARAMETERS", "Too many action parameters")
    placeholders = set(_ACTION_PARAMETER_RE.findall(template))
    unknown = sorted(str(key) for key in supplied if str(key) not in placeholders)
    if unknown:
        raise PlatformRegistryError("UNSUPPORTED_ACTION_PARAMETERS", f"Unsupported action parameters: {', '.join(unknown)}")
    missing = sorted(placeholders - {str(key) for key in supplied})
    if missing:
        raise PlatformRegistryError("MISSING_ACTION_PARAMETERS", f"Missing action parameters: {', '.join(missing)}")

    rendered = template
    for key in placeholders:
        value = supplied.get(key)
        if isinstance(value, bool) or value is None:
            raise PlatformRegistryError("INVALID_ACTION_PARAMETERS", f"Action parameter {key} must be a scalar token")
        token = str(value).strip()
        if not _ACTION_PARAMETER_VALUE_RE.fullmatch(token):
            raise PlatformRegistryError("INVALID_ACTION_PARAMETERS", f"Action parameter {key} contains unsafe characters")
        rendered = re.sub(r"\{\{\s*" + re.escape(key) + r"\s*\}\}", token, rendered)
    return rendered


def _row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class PlatformActionSession:
    """Hold one read-only driver context for several registry actions.

    The public action boundary remains action-scoped for authorization,
    parser validation, and audit telemetry.  A trusted collector can opt into
    this private session only when several read-only actions belong to the
    same device/release, avoiding a fresh SSH login for every command.
    """

    def __init__(self, device_id: str, user: dict[str, Any], driver_factory=None):
        self.device_id = str(device_id)
        self.user = user or {}
        self.driver_factory = driver_factory
        self._driver = None
        self._release_id = ''
        self._connection_driver = ''
        self._parser_platform = ''

    def __enter__(self):
        conn = get_db_connection()
        try:
            row = conn.execute(
                """SELECT d.*, p.platform_code, p.connection_driver, p.parser_platform,
                          p.current_release_id, r.release_number
                   FROM devices d
                   LEFT JOIN platform_profiles p ON p.id = d.platform_profile_id
                   LEFT JOIN platform_releases r
                     ON r.id = p.current_release_id AND r.status = 'PUBLISHED'
                   WHERE d.id = ?""",
                (self.device_id,),
            ).fetchone()
            device = _row_dict(row)
            if not device:
                raise PlatformRegistryError("DEVICE_NOT_FOUND", "Device not found", status_code=404)

            tenant_id = str(self.user.get("tenant_id") or "")
            if tenant_id and device.get("tenant_id") and tenant_id != str(device["tenant_id"]):
                raise PlatformRegistryError("DEVICE_SCOPE_DENIED", "Device is outside the current tenant scope", status_code=403)
            if self.user.get("role") != "Administrator" and device.get("tenant_id") and tenant_id != str(device["tenant_id"]):
                raise PlatformRegistryError("DEVICE_SCOPE_DENIED", "A tenant-scoped user is required for this device", status_code=403)
            from core.rbac import authorize_resource
            if not authorize_resource(
                self.user,
                "command",
                "execute",
                tenant_id=device.get("tenant_id"),
                site_id=device.get("site_id") or device.get("site"),
                device_group_id=device.get("device_group_id"),
            ):
                raise PlatformRegistryError("DEVICE_SCOPE_DENIED", "Device is outside the current resource scope", status_code=403)
            if not platform_codes_match(device.get("platform"), device.get("platform_code"), device.get("parser_platform")):
                raise PlatformRegistryError(
                    "PLATFORM_PROFILE_MISMATCH",
                    "Device platform does not match its bound platform Profile",
                    status_code=409,
                )
            if not device.get("current_release_id") or not device.get("release_number"):
                raise PlatformRegistryError("NO_PUBLISHED_RELEASE", "Device has no published platform release")

            from services.vault_service import resolve_collector_credentials
            collector_credentials = resolve_collector_credentials(device, ssh_role="normal")
            ssh_credentials = collector_credentials["ssh"]
            device["username"] = ssh_credentials["username"] or ""
            device["password"] = ssh_credentials["password"] or ""
            device["enable_password"] = ssh_credentials["enable_password"] or ""
            driver_type = CONNECTION_DRIVER_TO_IMPLEMENTATION.get(
                device.get("connection_driver"), device.get("connection_driver")
            )
            device["driver_type"] = driver_type
            # parser_platform selects TextFSM; connection_driver selects the
            # actual Netmiko/Scrapli device implementation.  Custom Profiles
            # may deliberately use a custom parser namespace on top of an
            # existing connection driver and must not fall back to Cisco.
            device["platform"] = device.get("connection_driver") or device.get("platform")
            if self.driver_factory is None:
                from drivers.factory import DriverFactory
                self.driver_factory = DriverFactory
            self._driver = self.driver_factory.get_driver(driver_type, device)
            try:
                self._driver.__enter__()
            except Exception as exc:
                try:
                    self._driver.__exit__(type(exc), exc, exc.__traceback__)
                finally:
                    self._driver = None
                raise
            self._release_id = str(device.get("current_release_id") or "")
            self._connection_driver = str(device.get("connection_driver") or "")
            self._parser_platform = str(device.get("parser_platform") or "")
            return self
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._driver is not None:
            try:
                return self._driver.__exit__(exc_type, exc_val, exc_tb)
            finally:
                self._driver = None
        return None

    def matches(self, device: dict[str, Any]) -> bool:
        return (
            str(device.get("current_release_id") or "") == self._release_id
            and str(device.get("connection_driver") or "") == self._connection_driver
            and str(device.get("parser_platform") or "") == self._parser_platform
        )

    def send_command(self, command: str):
        if self._driver is None:
            raise PlatformRegistryError("ACTION_SESSION_CLOSED", "Platform action session is closed")
        return self._driver.send_command(command)


def _profile_scope_clause(user: dict[str, Any]) -> tuple[str, list[Any]]:
    tenant_id = str(user.get("tenant_id") or "")
    if tenant_id:
        return "AND (p.tenant_id IS NULL OR p.tenant_id = ?)", [tenant_id]
    return "", []


def _device_stats_join(user: dict[str, Any]) -> tuple[str, list[Any]]:
    """Return tenant-scoped device aggregates for registry read views.

    System profiles are visible to a tenant, but their device counts must not
    disclose devices belonging to another tenant.  Administrators without a
    tenant context retain the existing all-scope behaviour.
    """
    tenant_id = str(user.get("tenant_id") or "")
    return (
        """
        LEFT JOIN (
            SELECT d.platform_profile_id,
                   COUNT(*) AS bound_device_count,
                   SUM(CASE WHEN LOWER(COALESCE(d.status, '')) IN ('online', 'active', 'up') THEN 1 ELSE 0 END) AS online_device_count
            FROM devices d
            WHERE (? = '' OR d.tenant_id = ?)
            GROUP BY d.platform_profile_id
        ) device_stats ON device_stats.platform_profile_id = p.id
        """,
        [tenant_id, tenant_id],
    )


def _assert_profile_access(conn, profile_id: str, user: dict[str, Any]) -> dict[str, Any]:
    profile = _row_dict(conn.execute("SELECT * FROM platform_profiles WHERE id = ?", (profile_id,)).fetchone())
    if not profile:
        raise PlatformRegistryError("PLATFORM_NOT_FOUND", "Platform profile not found", status_code=404)
    user_tenant = str(user.get("tenant_id") or "")
    profile_tenant = str(profile.get("tenant_id") or "")
    if profile_tenant and profile_tenant != user_tenant and user.get("role") != "Administrator":
        raise PlatformRegistryError("PLATFORM_SCOPE_DENIED", "Platform profile is outside the current tenant scope", status_code=403)
    return profile


def list_profiles(user: dict[str, Any]) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        scope_sql, params = _profile_scope_clause(user)
        device_stats_sql, device_stats_params = _device_stats_join(user)
        rows = conn.execute(
            f"""SELECT p.*, r.release_number AS current_release_number, r.checksum AS current_release_checksum,
                       r.status AS current_release_status, r.validation_status AS current_release_validation_status,
                       (SELECT COUNT(*) FROM platform_release_actions ra WHERE ra.release_id = p.current_release_id) AS current_action_count,
                       COALESCE(device_stats.bound_device_count, 0) AS bound_device_count,
                       COALESCE(device_stats.online_device_count, 0) AS online_device_count
                FROM platform_profiles p LEFT JOIN platform_releases r ON r.id = p.current_release_id
                {device_stats_sql}
                WHERE p.status <> 'ARCHIVED' {scope_sql} ORDER BY p.source, p.platform_code""",
            [*device_stats_params, *params],
        ).fetchall()
        return [_with_platform_catalog_metadata(_row_dict(row) or {}) for row in rows]
    finally:
        conn.close()


def get_profile(profile_id: str, user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        scope_sql, params = _profile_scope_clause(user)
        device_stats_sql, device_stats_params = _device_stats_join(user)
        row = conn.execute(
            f"""SELECT p.*, r.release_number AS current_release_number, r.checksum AS current_release_checksum,
                       r.status AS current_release_status, r.validation_status AS current_release_validation_status,
                       (SELECT COUNT(*) FROM platform_release_actions ra WHERE ra.release_id = p.current_release_id) AS current_action_count,
                       COALESCE(device_stats.bound_device_count, 0) AS bound_device_count,
                       COALESCE(device_stats.online_device_count, 0) AS online_device_count
                FROM platform_profiles p LEFT JOIN platform_releases r ON r.id = p.current_release_id
                {device_stats_sql}
                WHERE p.id = ? {scope_sql}""",
            [*device_stats_params, profile_id, *params],
        ).fetchone()
        if not row:
            raise PlatformRegistryError("PLATFORM_NOT_FOUND", "Platform profile not found", status_code=404)
        result = _row_dict(row) or {}
        result["releases"] = [_row_dict(item) for item in conn.execute("SELECT * FROM platform_releases WHERE profile_id = ? ORDER BY release_number DESC", (profile_id,)).fetchall()]
        result["identification_rules"] = [
            _row_dict(item) for item in conn.execute(
                """SELECT id, command, match_type, pattern, logic_group, rule_order,
                          confidence, negate, enabled FROM platform_identification_rules
                   WHERE platform_profile_id = ? ORDER BY rule_order, id""",
                (profile_id,),
            ).fetchall()
        ]
        return result
    finally:
        conn.close()


def create_profile(payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    code = validate_platform_code(payload.get("platform_code"))
    driver = str(payload.get("connection_driver") or "").strip().lower()
    if driver not in ALLOWED_CONNECTION_DRIVERS:
        raise PlatformRegistryError("INVALID_CONNECTION_DRIVER", "connection_driver is not in the system allowlist")
    tenant_id = str(user.get("tenant_id") or payload.get("tenant_id") or "") or None
    if not tenant_id and user.get("role") != "Administrator":
        raise PlatformRegistryError("TENANT_REQUIRED", "Tenant users must create tenant-scoped profiles")
    profile_id = str(uuid.uuid4())
    now = _now()
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO platform_profiles (id, tenant_id, platform_code, name_zh, name_en, vendor, connection_driver, parser_platform, source, status, description, created_by, created_at, updated_at, lock_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'CUSTOM', 'ACTIVE', ?, ?, ?, ?, 1)""",
            (profile_id, tenant_id, code, payload.get("name_zh") or code, payload.get("name_en") or code, payload.get("vendor") or "", driver, payload.get("parser_platform") or code, payload.get("description") or "", user.get("id") or user.get("username") or "", now, now),
        )
        conn.commit()
        return get_profile(profile_id, user)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _assert_profile_active(profile: dict[str, Any]) -> None:
    if str(profile.get("status") or "ACTIVE").upper() == "ARCHIVED":
        raise PlatformRegistryError(
            "PROFILE_ARCHIVED",
            "Archived platform profiles cannot be changed",
            status_code=409,
        )


def _assert_profile_writable(profile: dict[str, Any]) -> None:
    _assert_profile_active(profile)
    source = str(profile.get("source") or "CUSTOM").upper()
    if source == "SYSTEM":
        raise PlatformRegistryError(
            "SYSTEM_PROFILE_READ_ONLY",
            "System platform profiles are read-only",
            status_code=403,
        )


def _profile_bound_device_count(conn, profile_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM devices WHERE platform_profile_id = ?",
        (profile_id,),
    ).fetchone()
    return int(row["count"] if row else 0)


def _lock_profile_for_write(conn, profile_id: str) -> None:
    """Serialize profile mutations with device binding and other writers."""
    import database as _database

    if _database._USE_PG:
        conn.execute("SELECT id FROM platform_profiles WHERE id = ? FOR UPDATE", (profile_id,)).fetchone()
    else:
        conn.execute("BEGIN IMMEDIATE")


def update_profile(profile_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Update a custom profile while protecting bound device identity."""
    conn = get_db_connection()
    try:
        _lock_profile_for_write(conn, profile_id)
        profile = _assert_profile_access(conn, profile_id, user)
        _assert_profile_writable(profile)

        allowed_fields = (
            "platform_code", "name_zh", "name_en", "vendor",
            "connection_driver", "parser_platform", "description",
        )
        updates: dict[str, Any] = {
            key: payload[key]
            for key in allowed_fields
            if key in payload
        }
        if not updates:
            return profile

        if "platform_code" in updates:
            updates["platform_code"] = validate_platform_code(updates["platform_code"])
        if "connection_driver" in updates:
            driver = str(updates["connection_driver"] or "").strip().lower()
            if driver not in ALLOWED_CONNECTION_DRIVERS:
                raise PlatformRegistryError(
                    "INVALID_CONNECTION_DRIVER",
                    "connection_driver is not in the system allowlist",
                )
            updates["connection_driver"] = driver
        if "parser_platform" in updates:
            parser_platform = str(updates["parser_platform"] or "").strip().lower()
            if not parser_platform:
                raise PlatformRegistryError("INVALID_PARSER_PLATFORM", "parser_platform is required")
            updates["parser_platform"] = parser_platform
        for key in ("name_zh", "name_en", "vendor", "description"):
            if key in updates:
                updates[key] = str(updates[key] or "").strip()

        bound_count = _profile_bound_device_count(conn, profile_id)
        identity_fields = {"platform_code", "connection_driver", "parser_platform"}
        identity_changed = any(
            key in updates and str(updates[key]) != str(profile.get(key) or "")
            for key in identity_fields
        )
        if bound_count and identity_changed:
            raise PlatformRegistryError(
                "PLATFORM_IDENTITY_LOCKED",
                f"Platform identity cannot change while {bound_count} device(s) are bound",
                status_code=409,
            )

        if "platform_code" in updates and updates["platform_code"] != profile.get("platform_code"):
            tenant_id = profile.get("tenant_id")
            duplicate = conn.execute(
                """SELECT id FROM platform_profiles
                   WHERE id <> ? AND platform_code = ?
                     AND ((tenant_id = ?) OR (tenant_id IS NULL AND ? IS NULL))
                   LIMIT 1""",
                (profile_id, updates["platform_code"], tenant_id, tenant_id),
            ).fetchone()
            if duplicate:
                raise PlatformRegistryError(
                    "PLATFORM_CODE_CONFLICT",
                    "A platform with this code already exists in the same scope",
                    status_code=409,
                )

        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = [updates[key] for key in updates]
        now = _now()
        conn.execute(
            f"UPDATE platform_profiles SET {assignments}, updated_at = ?, lock_version = lock_version + 1 WHERE id = ?",
            (*values, now, profile_id),
        )
        conn.commit()
        invalidate_platform_registry_cache()
        return get_profile(profile_id, user)
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_profile(profile_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Archive a custom profile; bound profiles and system profiles are protected."""
    conn = get_db_connection()
    try:
        _lock_profile_for_write(conn, profile_id)
        profile = _assert_profile_access(conn, profile_id, user)
        _assert_profile_writable(profile)
        bound_count = _profile_bound_device_count(conn, profile_id)
        if bound_count:
            raise PlatformRegistryError(
                "PLATFORM_BOUND_DEVICES",
                f"Platform has {bound_count} bound device(s) and cannot be deleted",
                status_code=409,
            )

        now = _now()
        conn.execute(
            "UPDATE platform_profiles SET status = 'ARCHIVED', updated_at = ?, lock_version = lock_version + 1 WHERE id = ?",
            (now, profile_id),
        )
        conn.commit()
        invalidate_platform_registry_cache()
        return {
            "id": profile_id,
            "status": "ARCHIVED",
            "deleted": True,
            "bound_device_count": 0,
        }
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_release(profile_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    profile = get_profile(profile_id, user)
    _assert_profile_writable(profile)
    now = _now()
    conn = get_db_connection()
    try:
        import database as _database
        if _database._USE_PG:
            # Serialize release-number allocation per profile on PostgreSQL.
            conn.execute("SELECT id FROM platform_profiles WHERE id = ? FOR UPDATE", (profile_id,)).fetchone()
        else:
            # SQLite's writer lock closes the MAX()+1 race for local installs.
            conn.execute("BEGIN IMMEDIATE")

        # A profile can have at most one working draft from the operator's
        # point of view.  Reusing it makes the button idempotent and avoids a
        # pile of indistinguishable empty releases when the user only wants to
        # change one action mapping.
        existing = conn.execute(
            "SELECT * FROM platform_releases WHERE profile_id = ? AND status = 'DRAFT' ORDER BY release_number DESC LIMIT 1",
            (profile_id,),
        ).fetchone()
        if existing:
            existing_dict = _row_dict(existing) or {}
            action_count = conn.execute(
                "SELECT COUNT(*) AS count FROM platform_release_actions WHERE release_id = ?",
                (existing_dict.get("id"),),
            ).fetchone()["count"]
            if not action_count:
                # Repair drafts created by older builds: copy the currently
                # published snapshot so editing one action cannot accidentally
                # publish a release with all other mappings missing.
                published = None
                current_release_id = str(profile.get("current_release_id") or "").strip()
                if current_release_id:
                    published = conn.execute(
                        "SELECT id FROM platform_releases WHERE id = ? AND profile_id = ? AND status = 'PUBLISHED'",
                        (current_release_id, profile_id),
                    ).fetchone()
                if not published:
                    published = conn.execute(
                        "SELECT id FROM platform_releases WHERE profile_id = ? AND status = 'PUBLISHED' ORDER BY release_number DESC LIMIT 1",
                        (profile_id,),
                    ).fetchone()
                if published:
                    source_actions = conn.execute(
                        """SELECT action_code, command, field_contract_json, command_checksum
                           FROM platform_release_actions
                           WHERE release_id = ? ORDER BY action_code""",
                        (published["id"],),
                    ).fetchall()
                    for action in source_actions:
                        conn.execute(
                            """INSERT INTO platform_release_actions
                               (id, release_id, action_code, command,
                                field_contract_json, command_checksum,
                                created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                str(uuid.uuid4()), existing_dict["id"], action["action_code"], action["command"],
                                action["field_contract_json"], action["command_checksum"], now, now,
                            ),
                        )
                    copied_actions = [
                        dict(row)
                        for row in conn.execute(
                            """SELECT action_code, command, field_contract_json
                               FROM platform_release_actions WHERE release_id = ?
                               ORDER BY action_code""",
                            (existing_dict["id"],),
                        ).fetchall()
                    ]
                    conn.execute(
                        "UPDATE platform_releases SET checksum = ?, updated_at = ?, lock_version = lock_version + 1 WHERE id = ?",
                        (_checksum(copied_actions), now, existing_dict["id"]),
                    )
            conn.commit()
            return _row_dict(conn.execute("SELECT * FROM platform_releases WHERE id = ?", (existing_dict["id"],)).fetchone()) or {}

        release_id = str(uuid.uuid4())
        next_number = conn.execute("SELECT COALESCE(MAX(release_number), 0) + 1 AS next_number FROM platform_releases WHERE profile_id = ?", (profile_id,)).fetchone()["next_number"]
        # A new draft starts as a copy of the currently published release.  A
        # later PUT then changes only the selected action_code while preserving
        # every other command mapping.
        published = None
        current_release_id = str(profile.get("current_release_id") or "").strip()
        if current_release_id:
            published = conn.execute(
                "SELECT id, safety_policy_json FROM platform_releases WHERE id = ? AND profile_id = ? AND status = 'PUBLISHED'",
                (current_release_id, profile_id),
            ).fetchone()
        if not published:
            published = conn.execute(
                "SELECT id, safety_policy_json FROM platform_releases WHERE profile_id = ? AND status = 'PUBLISHED' ORDER BY release_number DESC LIMIT 1",
                (profile_id,),
            ).fetchone()
        source_actions = []
        if published:
            source_actions = conn.execute(
                """SELECT action_code, command, field_contract_json, command_checksum
                   FROM platform_release_actions WHERE release_id = ?
                   ORDER BY action_code""",
                (published["id"],),
            ).fetchall()
        copied_actions = [dict(row) for row in source_actions]
        safety_policy = payload.get("safety_policy") or (published["safety_policy_json"] if published else None)
        if isinstance(safety_policy, str):
            try:
                safety_policy = json.loads(safety_policy)
            except (TypeError, ValueError):
                safety_policy = {"read_only": True}
        safety_policy = safety_policy or {"read_only": True}
        conn.execute(
            """INSERT INTO platform_releases (id, profile_id, release_number, status, connection_driver, parser_platform, safety_policy_json, checksum, created_by, created_at, updated_at, lock_version)
               VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?, 1)""",
            (release_id, profile_id, next_number, profile["connection_driver"], profile["parser_platform"], _json(safety_policy), _checksum(copied_actions), user.get("id") or user.get("username") or "", now, now),
        )
        for action in source_actions:
            conn.execute(
                """INSERT INTO platform_release_actions
                   (id, release_id, action_code, command, field_contract_json,
                    command_checksum, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), release_id, action["action_code"], action["command"],
                    action["field_contract_json"], action["command_checksum"], now, now,
                ),
            )
        conn.commit()
        return _row_dict(conn.execute("SELECT * FROM platform_releases WHERE id = ?", (release_id,)).fetchone()) or {}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_release_actions(profile_id: str, user: dict[str, Any], release_id: str | None = None) -> list[dict[str, Any]]:
    profile = get_profile(profile_id, user)
    target_release_id = str(release_id or profile.get("current_release_id") or "").strip()
    conn = get_db_connection()
    try:
        if target_release_id:
            release = conn.execute(
                "SELECT id, profile_id FROM platform_releases WHERE id = ?",
                (target_release_id,),
            ).fetchone()
            if not release or str(release["profile_id"]) != str(profile_id):
                raise PlatformRegistryError("RELEASE_NOT_FOUND", "Platform release not found", status_code=404)
        rows = conn.execute(
            """SELECT d.*, a.command, a.field_contract_json, a.command_checksum
               FROM action_definitions d LEFT JOIN platform_release_actions a
                 ON a.action_code = d.action_code AND a.release_id = ?
               ORDER BY d.action_code""",
            (target_release_id or None,),
        ).fetchall()
        return [_row_dict(row) for row in rows]
    finally:
        conn.close()


@lru_cache(maxsize=1024)
def _resolve_action_mapping_cached(canonical: str, action_code: str) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT p.platform_code, p.connection_driver, p.parser_platform, r.id AS platform_release_id,
                      r.release_number, r.checksum AS release_checksum, a.command,
                      a.field_contract_json, a.command_checksum
               FROM platform_profiles p JOIN platform_releases r ON r.id = p.current_release_id AND r.status = 'PUBLISHED'
               JOIN platform_release_actions a ON a.release_id = r.id
               WHERE p.platform_code = ? AND a.action_code = ? AND p.source = 'SYSTEM'""",
            (canonical, action_code),
        ).fetchone()
        if not row:
            raise PlatformRegistryError("UNSUPPORTED_ACTION", f"No published mapping for {canonical}/{action_code}")
        return _row_dict(row) or {}
    finally:
        conn.close()


def preview_platform_migration(user: dict[str, Any]) -> dict[str, Any]:
    """Return a read-only migration preview without changing the legacy path.

    The preview deliberately reports data-quality conflicts instead of trying
    to repair them implicitly.  This lets an administrator review legacy
    platform values and file-based templates before enabling any write flow.
    """
    conn = get_db_connection()
    try:
        tenant_id = str(user.get("tenant_id") or "")
        device_scope = "WHERE (? = '' OR d.tenant_id = ?)"
        device_rows = conn.execute(
            f"""SELECT d.id, d.hostname, d.platform, d.platform_profile_id,
                       d.platform_source, d.platform_locked, d.tenant_id,
                       p.platform_code AS bound_platform_code,
                       p.source AS bound_profile_source
                FROM devices d
                LEFT JOIN platform_profiles p ON p.id = d.platform_profile_id
                {device_scope}
                ORDER BY d.hostname, d.id""",
            (tenant_id, tenant_id),
        ).fetchall()

        known_aliases = set(PLATFORM_ALIASES)
        known_aliases.update(PLATFORM_ALIASES.values())
        device_conflicts: list[dict[str, Any]] = []
        counts = {
            "total": len(device_rows),
            "bound": 0,
            "unbound": 0,
            "legacy_platform_values": 0,
            "unknown_platform_values": 0,
            "locked": 0,
        }
        for row in device_rows:
            item = _row_dict(row) or {}
            platform = str(item.get("platform") or "").strip().lower()
            bound = str(item.get("platform_profile_id") or "").strip()
            if bound:
                counts["bound"] += 1
            else:
                counts["unbound"] += 1
            if bool(item.get("platform_locked")):
                counts["locked"] += 1
            if platform:
                counts["legacy_platform_values"] += 1
                if platform not in known_aliases:
                    counts["unknown_platform_values"] += 1
                    device_conflicts.append({
                        "kind": "UNKNOWN_PLATFORM",
                        "device_id": item.get("id"),
                        "hostname": item.get("hostname") or "",
                        "platform": item.get("platform") or "",
                    })
            if bound and not item.get("bound_platform_code"):
                device_conflicts.append({
                    "kind": "MISSING_PROFILE",
                    "device_id": item.get("id"),
                    "hostname": item.get("hostname") or "",
                    "platform_profile_id": bound,
                })

        template_root = Path(__file__).resolve().parents[2] / "data" / "textfsm_templates"
        template_files = sorted(template_root.glob("*.textfsm")) if template_root.exists() else []
        known_parser_platforms = {str(item.get("parser_platform") or "") for item in SYSTEM_PROFILES}
        template_conflicts = []
        for path in template_files:
            stem = path.stem.lower()
            if not any(stem.startswith(f"{platform.lower()}_") for platform in known_parser_platforms):
                template_conflicts.append({
                    "kind": "UNKNOWN_TEMPLATE_PLATFORM",
                    "filename": path.name,
                })

        return {
            "read_only": True,
            "legacy_compatibility_unchanged": True,
            "canonical_platform": "h3c_comware",
            "devices": counts,
            "device_conflicts": device_conflicts,
            "file_templates": {
                "count": len(template_files),
                "conflicts": template_conflicts,
            },
            "summary": {
                "conflict_count": len(device_conflicts) + len(template_conflicts),
                "safe_to_review": True,
            },
        }
    finally:
        conn.close()


def invalidate_platform_registry_cache() -> None:
    """Invalidate immutable release/action lookups after a publication change."""
    _resolve_action_mapping_cached.cache_clear()


def resolve_action_mapping(platform_code: str, action_code: str) -> dict[str, Any]:
    """Resolve a system profile action for legacy consumers that only have a platform key.

    It is intentionally strict: an absent mapping is an unsupported action,
    never a Cisco command fallback.
    """
    canonical = normalize_platform_code(platform_code)
    return dict(_resolve_action_mapping_cached(canonical, action_code))


def resolve_device_action_code(device_id: str, command: str) -> str | None:
    """Find an exact action mapping for a device's published release.

    This is deliberately exact and returns ``None`` when the device is not
    registry-bound, so legacy custom inspection commands cannot be silently
    reinterpreted as a different logical action.
    """
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT a.action_code
               FROM devices d
               JOIN platform_profiles p ON p.id = d.platform_profile_id
               JOIN platform_releases r ON r.id = p.current_release_id AND r.status = 'PUBLISHED'
               JOIN platform_release_actions a ON a.release_id = r.id
               WHERE d.id = ? AND LOWER(TRIM(a.command)) = LOWER(TRIM(?))""",
            (device_id, command),
        ).fetchone()
        return str(row["action_code"]) if row else None
    finally:
        conn.close()


def preview_platform_action(
    device_id: str,
    action_code: str,
    *,
    user: dict[str, Any],
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a published action without opening a device connection."""
    if not action_code or not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", action_code):
        raise PlatformRegistryError("INVALID_ACTION_CODE", "Invalid action_code")
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT d.*, p.id AS profile_id, p.platform_code, p.connection_driver, p.parser_platform, p.current_release_id,
                      r.release_number, r.checksum AS release_checksum, a.command, a.command_checksum,
                      def.sensitive_level
               FROM devices d
               LEFT JOIN platform_profiles p ON p.id = d.platform_profile_id
               LEFT JOIN platform_releases r ON r.id = p.current_release_id AND r.status = 'PUBLISHED'
               LEFT JOIN platform_release_actions a ON a.release_id = r.id AND a.action_code = ?
               LEFT JOIN action_definitions def ON def.action_code = ?
               WHERE d.id = ?""",
            (action_code, action_code, device_id),
        ).fetchone()
        if not row:
            raise PlatformRegistryError("DEVICE_NOT_FOUND", "Device not found", status_code=404)
        device = _row_dict(row) or {}
        tenant_id = str(user.get("tenant_id") or "")
        if tenant_id and device.get("tenant_id") and tenant_id != str(device["tenant_id"]):
            raise PlatformRegistryError("DEVICE_SCOPE_DENIED", "Device is outside the current tenant scope", status_code=403)
        if user.get("role") != "Administrator" and device.get("tenant_id") and tenant_id != str(device["tenant_id"]):
            raise PlatformRegistryError("DEVICE_SCOPE_DENIED", "A tenant-scoped user is required for this device", status_code=403)
        from core.rbac import authorize_resource
        if not authorize_resource(
            user,
            "command",
            "execute",
            tenant_id=device.get("tenant_id"),
            site_id=device.get("site_id") or device.get("site"),
            device_group_id=device.get("device_group_id"),
        ):
            raise PlatformRegistryError("DEVICE_SCOPE_DENIED", "Device is outside the current resource scope", status_code=403)
        if not platform_codes_match(device.get("platform"), device.get("platform_code"), device.get("parser_platform")):
            raise PlatformRegistryError(
                "PLATFORM_PROFILE_MISMATCH",
                "Device platform does not match its bound platform Profile",
                status_code=409,
            )
        if not device.get("current_release_id") or not device.get("release_number"):
            raise PlatformRegistryError("NO_PUBLISHED_RELEASE", "Device has no published platform release")
        if not device.get("command"):
            raise PlatformRegistryError("UNSUPPORTED_ACTION", "The current platform release does not map this action")
        _validate_action_parameter_contract(action_code, device["command"])
        resolved_command = _render_action_command(device["command"], parameters)
        if not is_safe_read_command(resolved_command, device.get("connection_driver") or ""):
            raise PlatformRegistryError("UNSAFE_COMMAND", "Release contains an unsafe command")
        if device.get("sensitive_level") == "sensitive" and user.get("role") != "Administrator":
            raise PlatformRegistryError("SENSITIVE_ACTION_FORBIDDEN", "Sensitive action requires Administrator permission", status_code=403)
        return {
            "success": True,
            "action_code": action_code,
            "platform_release_id": device["current_release_id"],
            "release_number": device["release_number"],
            "release_checksum": device["release_checksum"],
            "command": resolved_command,
            "command_checksum": device.get("command_checksum"),
            "resolved_command_checksum": _checksum(resolved_command),
        }
    finally:
        conn.close()


def _record_platform_action_run(conn, device: dict[str, Any], metadata: dict[str, Any], raw_output: str = "") -> None:
    """Persist non-sensitive action telemetry; raw failure output is encrypted only."""
    raw_ciphertext = None
    raw_placeholder = "{}"
    raw_expiry = None
    retention_days = 7
    try:
        policy = conn.execute(
            "SELECT raw_output_retention_days, failure_output_retention_days "
            "FROM action_definitions WHERE action_code = ?",
            (metadata.get("action_code"),),
        ).fetchone()
        if policy:
            selected_retention = policy[1] if not metadata.get("success") else policy[0]
            retention_days = max(1, min(3650, int(selected_retention or retention_days)))
    except Exception:
        # Older isolated test schemas may not have the policy columns yet. The
        # safe failure retention default remains bounded and encrypted.
        retention_days = 7
    if raw_output and not metadata.get("success"):
        raw_ciphertext, raw_placeholder, raw_expiry, _encrypted = protect_output(
            raw_output,
            retention_days=retention_days,
        )
    conn.execute(
        """INSERT INTO platform_action_runs
           (id, tenant_id, device_id, platform_profile_id, platform_release_id,
            action_code, status, failure_stage,
            error_code, record_count, duration_ms, output_bytes, raw_output,
            raw_output_encrypted, raw_output_expires_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()), device.get("tenant_id"), device.get("id"), device.get("profile_id"),
            metadata.get("platform_release_id"), metadata.get("action_code"),
            "SUCCESS" if metadata.get("success") else "FAILED",
            metadata.get("failure_stage"), metadata.get("error_code"), int(metadata.get("record_count") or 0),
            int(metadata.get("duration_ms") or 0), int(metadata.get("output_bytes") or 0), raw_placeholder,
            raw_ciphertext, raw_expiry, _now(),
        ),
    )


def _release_for_id(conn, release_id: str, *, lock: bool = False) -> dict[str, Any]:
    # SQLite does not support PostgreSQL's row-lock syntax; the migration and
    # publish path remain transactional there while PostgreSQL gets FOR UPDATE.
    import database as _database
    suffix = " FOR UPDATE" if lock and _database._USE_PG else ""
    row = conn.execute(f"SELECT * FROM platform_releases WHERE id = ?{suffix}", (release_id,)).fetchone()
    if not row:
        raise PlatformRegistryError("RELEASE_NOT_FOUND", "Platform release not found", status_code=404)
    return _row_dict(row) or {}


def delete_release(release_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Delete an editable draft release and its action snapshot."""
    conn = get_db_connection()
    try:
        import database as _database
        if not _database._USE_PG:
            conn.execute("BEGIN IMMEDIATE")
        release = _release_for_id(conn, release_id, lock=_database._USE_PG)
        profile = _assert_profile_access(conn, release["profile_id"], user)
        _assert_profile_writable(profile)
        if release["status"] != "DRAFT":
            raise PlatformRegistryError("RELEASE_IMMUTABLE", "Only draft releases can be deleted")
        if str(profile.get("current_release_id") or "") == str(release_id):
            raise PlatformRegistryError("RELEASE_DELETE_CURRENT", "The current published release cannot be deleted", status_code=409)
        conn.execute("DELETE FROM platform_releases WHERE id = ?", (release_id,))
        conn.commit()
        invalidate_platform_registry_cache()
        return {"id": release_id, "profile_id": release["profile_id"], "deleted": True}
    except PlatformRegistryError:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_release_action(release_id: str, action_code: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        import database as _database
        if not _database._USE_PG:
            conn.execute("BEGIN IMMEDIATE")
        release = _release_for_id(conn, release_id, lock=_database._USE_PG)
        profile = _assert_profile_access(conn, release["profile_id"], user)
        _assert_profile_writable(profile)
        if release["status"] != "DRAFT":
            raise PlatformRegistryError("RELEASE_IMMUTABLE", "Only draft releases can be edited")
        definition = conn.execute("SELECT * FROM action_definitions WHERE action_code = ?", (action_code,)).fetchone()
        if not definition:
            raise PlatformRegistryError("UNSUPPORTED_ACTION", "Unknown action_code")
        command = str(payload.get("command") or "").strip()
        if not is_safe_read_command(command, profile["connection_driver"]):
            raise PlatformRegistryError("UNSAFE_COMMAND", "Only one read-only show/display command is allowed")
        _validate_action_parameter_contract(action_code, command)
        # TextFSM is deliberately not part of a platform Release.  The parser
        # is selected at execution time from the device's concrete profile
        # version and exact command.
        contract = payload.get("field_contract") or {"required": json.loads(definition["required_fields_json"] or "[]"), "optional": json.loads(definition["optional_fields_json"] or "[]")}
        now = _now()
        action_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO platform_release_actions
               (id, release_id, action_code, command, field_contract_json,
                command_checksum, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(release_id, action_code) DO UPDATE SET
                 command=excluded.command,
                 field_contract_json=excluded.field_contract_json,
                 command_checksum=excluded.command_checksum,
                 updated_at=excluded.updated_at""",
            (action_id, release_id, action_code, command, _json(contract), _checksum(command), now, now),
        )
        actions = [dict(row) for row in conn.execute(
            "SELECT action_code, command, field_contract_json FROM platform_release_actions WHERE release_id = ? ORDER BY action_code",
            (release_id,),
        ).fetchall()]
        conn.execute("UPDATE platform_releases SET checksum = ?, updated_at = ?, lock_version = lock_version + 1 WHERE id = ?", (_checksum(actions), now, release_id))
        conn.commit()
        invalidate_platform_registry_cache()
        return _row_dict(conn.execute(
            """SELECT id, release_id, action_code, command, field_contract_json,
                      command_checksum, created_at, updated_at
               FROM platform_release_actions
               WHERE release_id = ? AND action_code = ?""",
            (release_id, action_code),
        ).fetchone()) or {}
    except PlatformRegistryError:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def validate_release(release_id: str, user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        release = _release_for_id(conn, release_id)
        profile = _assert_profile_access(conn, release["profile_id"], user)
        _assert_profile_writable(profile)
        actions = conn.execute("SELECT a.*, d.max_output_bytes, d.max_records FROM platform_release_actions a JOIN action_definitions d ON d.action_code = a.action_code WHERE a.release_id = ?", (release_id,)).fetchall()
        errors: list[dict[str, str]] = []
        regression: list[dict[str, Any]] = []
        for action in actions:
            if not is_safe_read_command(action["command"], profile.get("connection_driver", "")):
                errors.append({"code": "UNSAFE_COMMAND", "action_code": action["action_code"]})
        if not actions:
            errors.append({"code": "NO_ACTIONS", "message": "Release must contain at least one action"})
        result = {"valid": not errors, "errors": errors, "action_count": len(actions), "regression": regression, "checksum": release.get("checksum")}
        conn.execute("UPDATE platform_releases SET validation_status = ?, validation_result_json = ?, updated_at = ? WHERE id = ?", ("PASSED" if not errors else "FAILED", _json(result), _now(), release_id))
        conn.commit()
        return result
    finally:
        conn.close()


def transition_release(release_id: str, event: str, user: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
    target = {
        "submit": ("DRAFT", "IN_REVIEW"),
        "withdraw": ("IN_REVIEW", "DRAFT"),
        "approve": ("IN_REVIEW", "APPROVED"),
        "reject": ("IN_REVIEW", "DRAFT"),
        "publish": ("APPROVED", "PUBLISHED"),
    }.get(event)
    if not target:
        raise PlatformRegistryError("INVALID_RELEASE_EVENT", "Unsupported release transition")
    conn = get_db_connection()
    try:
        import database as _database
        if not _database._USE_PG:
            conn.execute("BEGIN IMMEDIATE")
        release = _release_for_id(conn, release_id, lock=True)
        profile = _assert_profile_access(conn, release["profile_id"], user)
        _assert_profile_writable(profile)
        if event == "publish" and _database._USE_PG:
            conn.execute("SELECT id FROM platform_profiles WHERE id = ? FOR UPDATE", (release["profile_id"],)).fetchone()
        if release["status"] != target[0]:
            raise PlatformRegistryError("INVALID_RELEASE_STATE", f"Release must be {target[0]} before {event}")
        if event == "withdraw":
            actor = str(user.get("id") or user.get("username") or "")
            authors = {
                str(release.get("submitted_by") or ""),
                str(release.get("created_by") or ""),
            } - {""}
            if actor not in authors:
                raise PlatformRegistryError(
                    "RELEASE_WITHDRAW_FORBIDDEN",
                    "Only the release submitter can withdraw an in-review release",
                    status_code=403,
                )
            from core.rbac import authorize_resource
            if not authorize_resource(user, "platform", "submit", tenant_id=profile.get("tenant_id")):
                raise PlatformRegistryError(
                    "RELEASE_ROLE_FORBIDDEN",
                    "Platform submit permission is required to withdraw a release",
                    status_code=403,
                )
        if event in {"approve", "reject"} and release.get("created_by") == (user.get("id") or user.get("username")):
            if event == "approve":
                raise PlatformRegistryError("SELF_APPROVAL_FORBIDDEN", "The creator cannot approve their own release", status_code=403)
            raise PlatformRegistryError("SELF_REVIEW_FORBIDDEN", "The creator cannot reject their own release", status_code=403)
        if event in {"approve", "reject", "publish"}:
            from core.rbac import authorize_resource
            permission = "approve" if event == "reject" else event
            if not authorize_resource(user, "platform", permission, tenant_id=profile.get("tenant_id")):
                raise PlatformRegistryError("RELEASE_ROLE_FORBIDDEN", f"Platform permission is required to {permission} a release", status_code=403)
        now = _now()

        if event == "reject":
            # Rejection is a review decision, not a validation run.  Return
            # the release to the editable draft state and let the author fix
            # the selected action before submitting it again.
            conn.execute(
                """UPDATE platform_releases
                   SET status = 'DRAFT', validation_status = 'PENDING',
                       validation_result_json = '{}', approved_by = '',
                       updated_at = ?, lock_version = lock_version + 1
                   WHERE id = ?""",
                (now, release_id),
            )
            metadata = {"from": target[0], "to": target[1]}
            if str(reason or "").strip():
                metadata["reason"] = str(reason).strip()[:2000]
            conn.execute(
                """INSERT INTO platform_release_audit_logs
                   (id, release_id, event_type, actor_id, actor_username,
                    metadata_json, created_at)
                   VALUES (?, ?, 'REJECT', ?, ?, ?, ?)""",
                (str(uuid.uuid4()), release_id, user.get("id"), user.get("username"), _json(metadata), now),
            )
            conn.commit()
            invalidate_platform_registry_cache()
            return _release_for_id(conn, release_id)

        if event == "withdraw":
            now = _now()
            conn.execute(
                """UPDATE platform_releases
                   SET status = 'DRAFT', validation_status = 'PENDING',
                       validation_result_json = '{}', approved_by = '',
                       updated_at = ?, lock_version = lock_version + 1
                   WHERE id = ?""",
                (now, release_id),
            )
            conn.execute(
                """INSERT INTO platform_release_audit_logs
                   (id, release_id, event_type, actor_id, actor_username,
                    metadata_json, created_at)
                   VALUES (?, ?, 'WITHDRAW', ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), release_id, user.get("id"),
                    user.get("username"), _json({"from": target[0], "to": target[1]}), now,
                ),
            )
            conn.commit()
            invalidate_platform_registry_cache()
            return _release_for_id(conn, release_id)

        # Validate the exact action rows held by the same transaction that
        # changes status.  This removes the old validate-then-publish race.
        actions = conn.execute(
            "SELECT a.command, a.action_code FROM platform_release_actions a WHERE a.release_id = ?",
            (release_id,),
        ).fetchall()
        errors: list[dict[str, str]] = []
        regression: list[dict[str, Any]] = []
        for action in actions:
            if not is_safe_read_command(action["command"], profile.get("connection_driver", "")):
                errors.append({"code": "UNSAFE_COMMAND", "action_code": action["action_code"]})
        if not actions:
            errors.append({"code": "NO_ACTIONS", "message": "Release must contain at least one action"})
        validation = {"valid": not errors, "errors": errors, "action_count": len(actions), "regression": regression, "checksum": release.get("checksum")}
        conn.execute(
            "UPDATE platform_releases SET validation_status = ?, validation_result_json = ?, updated_at = ? WHERE id = ?",
            ("PASSED" if not errors else "FAILED", _json(validation), now, release_id),
        )
        if errors:
            conn.commit()
            raise PlatformRegistryError("RELEASE_VALIDATION_FAILED", "Release validation failed")
        if event == "submit":
            conn.execute(
                "UPDATE platform_releases SET status = ?, submitted_by = ?, updated_at = ?, lock_version = lock_version + 1 WHERE id = ?",
                (target[1], user.get("id") or user.get("username") or "", now, release_id),
            )
        elif event == "approve":
            conn.execute(
                "UPDATE platform_releases SET status = ?, approved_by = ?, updated_at = ?, lock_version = lock_version + 1 WHERE id = ?",
                (target[1], user.get("id") or user.get("username") or "", now, release_id),
            )
        else:
            conn.execute(
                "UPDATE platform_releases SET status = ?, published_by = ?, updated_at = ?, lock_version = lock_version + 1 WHERE id = ?",
                (target[1], user.get("id") or user.get("username") or "", now, release_id),
            )
        metadata = {"from": target[0], "to": target[1]}
        if str(reason or "").strip():
            metadata["reason"] = str(reason).strip()[:2000]
        conn.execute("INSERT INTO platform_release_audit_logs (id, release_id, event_type, actor_id, actor_username, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), release_id, event.upper(), user.get("id"), user.get("username"), _json(metadata), now))
        if event == "publish":
            conn.execute("UPDATE platform_releases SET status = 'DEPRECATED', updated_at = ? WHERE profile_id = ? AND status = 'PUBLISHED' AND id <> ?", (now, release["profile_id"], release_id))
            conn.execute("UPDATE platform_profiles SET current_release_id = ?, updated_at = ?, lock_version = lock_version + 1 WHERE id = ?", (release_id, now, release["profile_id"]))
        conn.commit()
        invalidate_platform_registry_cache()
        return _release_for_id(conn, release_id)
    except PlatformRegistryError:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rollback_profile(profile_id: str, release_id: str | None, user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        import database as _database
        if _database._USE_PG:
            conn.execute("SELECT id FROM platform_profiles WHERE id = ? FOR UPDATE", (profile_id,)).fetchone()
        else:
            conn.execute("BEGIN IMMEDIATE")
        profile = _assert_profile_access(conn, profile_id, user)
        _assert_profile_writable(profile)
        from core.rbac import authorize_resource
        if not authorize_resource(user, "platform", "rollback", tenant_id=profile.get("tenant_id")):
            raise PlatformRegistryError("RELEASE_ROLE_FORBIDDEN", "Platform rollback permission is required", status_code=403)
        target = release_id or conn.execute("SELECT id FROM platform_releases WHERE profile_id = ? AND status = 'DEPRECATED' ORDER BY release_number DESC LIMIT 1", (profile_id,)).fetchone()
        target_id = release_id or (target["id"] if target else None)
        if not target_id:
            raise PlatformRegistryError("NO_ROLLBACK_TARGET", "No previously published release is available")
        target_row = _row_dict(conn.execute("SELECT * FROM platform_releases WHERE id = ? AND profile_id = ? AND status IN ('PUBLISHED', 'DEPRECATED')", (target_id, profile_id)).fetchone())
        if not target_row:
            raise PlatformRegistryError("INVALID_ROLLBACK_TARGET", "Rollback target must be a release from this profile")
        now = _now()
        conn.execute("UPDATE platform_releases SET status = 'DEPRECATED', updated_at = ? WHERE profile_id = ? AND status = 'PUBLISHED'", (now, profile_id))
        conn.execute("UPDATE platform_releases SET status = 'PUBLISHED', updated_at = ? WHERE id = ?", (now, target_id))
        conn.execute("UPDATE platform_profiles SET current_release_id = ?, updated_at = ?, lock_version = lock_version + 1 WHERE id = ?", (target_id, now, profile_id))
        conn.execute("INSERT INTO platform_release_audit_logs (id, release_id, event_type, actor_id, actor_username, metadata_json, created_at) VALUES (?, ?, 'ROLLBACK', ?, ?, ?, ?)", (str(uuid.uuid4()), target_id, user.get("id"), user.get("username"), _json({"profile_id": profile_id}), now))
        conn.commit()
        invalidate_platform_registry_cache()
        return _row_dict(conn.execute("SELECT * FROM platform_releases WHERE id = ?", (target_id,)).fetchone()) or {}
    finally:
        conn.close()


def _canonical_field_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _normalize_records(
    records: list[dict[str, Any]],
    max_records: int,
    *,
    expected_fields: set[str] | None = None,
) -> list[dict[str, Any]]:
    result = []
    expected = {_canonical_field_name(item) for item in (expected_fields or set())}
    for record in records[:max_records]:
        normalized = {}
        for key, value in (record or {}).items():
            canonical = _canonical_field_name(key)
            normalized[canonical] = value.strip() if isinstance(value, str) else value
        for target in expected:
            if target in normalized:
                continue
            for alias in _FIELD_ALIASES.get(target, (target,)):
                alias_key = _canonical_field_name(alias)
                if alias_key in normalized and normalized[alias_key] not in (None, ""):
                    normalized[target] = normalized[alias_key]
                    break

        # A few vendor grammars intentionally keep compact columns instead of
        # inventing fields that are not present in the CLI output. Expand only
        # when the published action contract asks for the normalized field.
        if "usage" in expected and normalized.get("usage") in (None, ""):
            free_ratio = str(normalized.get("free_ratio") or "").strip()
            if free_ratio.endswith("%"):
                try:
                    normalized["usage"] = f"{100 - float(free_ratio[:-1]):g}%"
                except ValueError:
                    pass
        if "metric" in expected or "as_path" in expected:
            attributes = str(normalized.get("attributes") or "").strip()
            if attributes:
                tokens = attributes.split()
                if "metric" in expected and normalized.get("metric") in (None, "") and tokens:
                    normalized["metric"] = tokens[0]
                if "as_path" in expected and normalized.get("as_path") in (None, ""):
                    if len(tokens) >= 4:
                        normalized["as_path"] = " ".join(tokens[3:])
                    elif len(tokens) == 3:
                        normalized["as_path"] = tokens[2]
                    elif len(tokens) == 2:
                        normalized["as_path"] = tokens[1]
        result.append(normalized)
    return result


def _field_contract(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        contract = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        raise PlatformRegistryError("INVALID_FIELD_CONTRACT", "Field contract must be valid JSON")
    if not isinstance(contract, dict):
        raise PlatformRegistryError("INVALID_FIELD_CONTRACT", "Field contract must be an object")
    required = contract.get("required") or contract.get("required_fields") or []
    optional = contract.get("optional") or contract.get("optional_fields") or []
    types = contract.get("types") or contract.get("field_types") or {}
    if not isinstance(required, list) or not isinstance(optional, list) or not isinstance(types, dict):
        raise PlatformRegistryError("INVALID_FIELD_CONTRACT", "Field contract has an invalid shape")
    return {
        "required": [_canonical_field_name(item) for item in required if str(item).strip()],
        "optional": [_canonical_field_name(item) for item in optional if str(item).strip()],
        "types": {_canonical_field_name(key): str(kind).lower() for key, kind in types.items()},
    }


def _coerce_field_types(records: list[dict[str, Any]], contract: dict[str, Any]) -> None:
    """Convert scalar TextFSM strings to the declared contract types."""
    for record in records:
        for field, kind in (contract.get("types") or {}).items():
            value = record.get(field)
            if value in (None, "") or not isinstance(value, str):
                continue
            stripped = value.strip()
            try:
                if kind == "integer" and re.fullmatch(r"[-+]?\d+", stripped):
                    record[field] = int(stripped)
                elif kind == "number" and re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", stripped):
                    record[field] = float(stripped) if "." in stripped else int(stripped)
                elif kind == "boolean" and stripped.lower() in {"true", "yes", "up", "on", "1"}:
                    record[field] = True
                elif kind == "boolean" and stripped.lower() in {"false", "no", "down", "off", "0"}:
                    record[field] = False
            except (TypeError, ValueError):
                continue


def _validate_field_contract(records: list[dict[str, Any]], contract: dict[str, Any]) -> None:
    if not contract:
        return
    required = set(contract.get("required") or [])
    types = contract.get("types") or {}
    for index, record in enumerate(records):
        missing = sorted(field for field in required if record.get(field) in (None, ""))
        if missing:
            raise PlatformRegistryError("FIELD_CONTRACT_VIOLATION", f"Record {index} is missing required fields: {', '.join(missing)}")
        for field, kind in types.items():
            if field not in record or record[field] in (None, ""):
                continue
            value = record[field]
            valid = {
                "string": isinstance(value, str),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "number": isinstance(value, (int, float)) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
            }.get(kind)
            if valid is False:
                raise PlatformRegistryError("FIELD_CONTRACT_VIOLATION", f"Record {index} field {field} has invalid type")


def _parser_label(template: Any) -> str:
    """Return a parser status label before the direct file matcher runs."""
    return "platform-parser"


def execute_platform_action(
    device_id: str,
    action_code: str,
    *,
    user: dict[str, Any],
    parameters: dict[str, Any] | None = None,
    connection_options: dict[str, Any] | None = None,
    driver_factory=None,
    include_raw_output: bool = False,
    _session: PlatformActionSession | None = None,
) -> dict[str, Any]:
    """Execute one action from the device's immutable current release."""
    if not action_code or not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", action_code):
        raise PlatformRegistryError("INVALID_ACTION_CODE", "Invalid action_code")
    conn = get_db_connection()
    started_at = time.perf_counter()

    def _audit(event_type: str, metadata: dict[str, Any], raw_output: str = "") -> None:
        metadata = {
            **metadata,
            "duration_ms": max(0, int((time.perf_counter() - started_at) * 1000)),
            "output_bytes": len(raw_output.encode("utf-8", errors="ignore")) if raw_output else 0,
        }
        try:
            _record_platform_action_run(conn, device, metadata, raw_output)
        except Exception:
            conn.rollback()
            logger.warning("Failed to persist platform action telemetry", exc_info=True)
        try:
            conn.execute(
                "INSERT INTO platform_release_audit_logs (id, release_id, event_type, actor_id, actor_username, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), str(metadata.get("platform_release_id") or ""), event_type, user.get("id"), user.get("username"), _json(metadata), _now()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.warning("Failed to write platform action audit", exc_info=True)
    try:
        row = conn.execute(
            """SELECT d.*, p.id AS profile_id, p.platform_code, p.connection_driver, p.parser_platform, p.current_release_id, r.checksum AS release_checksum,
                      r.release_number, a.command, a.field_contract_json, a.command_checksum,
                      def.required_fields_json, def.optional_fields_json, def.field_types_json,
                      def.max_output_bytes, def.max_records, def.timeout_seconds, def.sensitive_level
               FROM devices d LEFT JOIN platform_profiles p ON p.id = d.platform_profile_id
               LEFT JOIN platform_releases r ON r.id = p.current_release_id AND r.status = 'PUBLISHED'
               LEFT JOIN platform_release_actions a ON a.release_id = r.id AND a.action_code = ?
               LEFT JOIN action_definitions def ON def.action_code = ? WHERE d.id = ?""",
            (action_code, action_code, device_id),
        ).fetchone()
        if not row:
            raise PlatformRegistryError("DEVICE_NOT_FOUND", "Device not found", status_code=404)
        device = _row_dict(row) or {}
        tenant_id = str(user.get("tenant_id") or "")
        if tenant_id and device.get("tenant_id") and tenant_id != str(device["tenant_id"]):
            raise PlatformRegistryError("DEVICE_SCOPE_DENIED", "Device is outside the current tenant scope", status_code=403)
        if user.get("role") != "Administrator" and device.get("tenant_id") and tenant_id != str(device["tenant_id"]):
            raise PlatformRegistryError("DEVICE_SCOPE_DENIED", "A tenant-scoped user is required for this device", status_code=403)
        from core.rbac import authorize_resource
        if not authorize_resource(
            user,
            "command",
            "execute",
            tenant_id=device.get("tenant_id"),
            site_id=device.get("site_id") or device.get("site"),
            device_group_id=device.get("device_group_id"),
        ):
            raise PlatformRegistryError("DEVICE_SCOPE_DENIED", "Device is outside the current resource scope", status_code=403)
        if not platform_codes_match(device.get("platform"), device.get("platform_code"), device.get("parser_platform")):
            raise PlatformRegistryError(
                "PLATFORM_PROFILE_MISMATCH",
                "Device platform does not match its bound platform Profile",
                status_code=409,
            )
        if not device.get("current_release_id") or not device.get("release_number"):
            raise PlatformRegistryError("NO_PUBLISHED_RELEASE", "Device has no published platform release")
        if not device.get("command"):
            raise PlatformRegistryError("UNSUPPORTED_ACTION", "The current platform release does not map this action")
        if device.get("sensitive_level") == "sensitive" and user.get("role") != "Administrator":
            raise PlatformRegistryError("SENSITIVE_ACTION_FORBIDDEN", "get_running_config requires Administrator permission", status_code=403)
        _validate_action_parameter_contract(action_code, device["command"])
        resolved_command = _render_action_command(device["command"], parameters)
        if not is_safe_read_command(resolved_command, device.get("connection_driver") or ""):
            raise PlatformRegistryError("UNSAFE_COMMAND", "Release contains an unsafe command")
        if _session is not None:
            if not _session.matches(device):
                raise PlatformRegistryError("ACTION_SESSION_STALE", "Platform action session no longer matches the current release")
            result = _session.send_command(resolved_command)
        else:
            if driver_factory is None:
                from drivers.factory import DriverFactory
                driver_factory = DriverFactory
            # Every registry action is a network read and must use the same
            # credential contract as topology, inspection, and other collectors.
            # The row above intentionally selects ``d.*`` for scope and audit
            # metadata, but its legacy credential columns may be empty when the
            # device is bound to a shared credential-center entry. Resolve the
            # ordinary SSH account before handing the device to a driver; never
            # pass the raw database password field through this boundary.
            from services.vault_service import resolve_collector_credentials

            collector_credentials = resolve_collector_credentials(device, ssh_role="normal")
            ssh_credentials = collector_credentials["ssh"]
            device["username"] = ssh_credentials["username"] or ""
            device["password"] = ssh_credentials["password"] or ""
            device["enable_password"] = ssh_credentials["enable_password"] or ""
            driver_type = CONNECTION_DRIVER_TO_IMPLEMENTATION.get(device.get("connection_driver"), device.get("connection_driver"))
            device["driver_type"] = driver_type
            device["platform"] = device.get("connection_driver") or device.get("platform")
            # Scheduled configuration backup supplies one effective transport
            # budget. The registry action re-reads the device row, so preserve
            # those options explicitly instead of losing them at this
            # boundary.
            if connection_options:
                for key in (
                    "conn_timeout",
                    "timeout",
                    "banner_timeout",
                    "auth_timeout",
                    "blocking_timeout",
                    "session_timeout",
                    "read_timeout",
                    "command_read_timeout",
                ):
                    value = connection_options.get(key)
                    if value is not None:
                        device[key] = int(value)
            driver = driver_factory.get_driver(driver_type, device)
            with driver:
                result = driver.send_command(resolved_command)
        output = str(getattr(result, "output", "") or "")
        if not getattr(result, "success", False):
            response = {"success": False, "error_code": "CONNECTION_OR_COMMAND_FAILED", "error": getattr(result, "error", "Command execution failed"), "action_code": action_code, "platform_release_id": device["current_release_id"], "release_number": device["release_number"], "command": resolved_command, "resolved_command_checksum": _checksum(resolved_command), "parser": _parser_label(None)}
            _audit("ACTION_EXECUTED", {"platform_release_id": device["current_release_id"], "device_id": device_id, "action_code": action_code, "success": False, "failure_stage": "connection", "error_code": response["error_code"], "command": resolved_command, "command_checksum": device.get("command_checksum"), "resolved_command_checksum": _checksum(resolved_command)})
            return response
        max_bytes = int(device.get("max_output_bytes") or 2_000_000)
        if len(output.encode("utf-8", errors="ignore")) > max_bytes:
            response = {"success": False, "error_code": "OUTPUT_LIMIT_EXCEEDED", "error": "Command output exceeds the action limit", "action_code": action_code, "platform_release_id": device["current_release_id"], "parser": _parser_label(None)}
            _audit("ACTION_EXECUTED", {"platform_release_id": device["current_release_id"], "device_id": device_id, "action_code": action_code, "success": False, "failure_stage": "output_limit", "error_code": response["error_code"], "command": resolved_command, "command_checksum": device.get("command_checksum"), "resolved_command_checksum": _checksum(resolved_command)}, output)
            return response
        try:
            from services.operational_data_service import parse_device_cli_output

            max_records = int(device.get("max_records") or 1000)
            auto_parse = parse_device_cli_output(
                device,
                resolved_command,
                output,
                max_records=max_records,
            )
            records = auto_parse.get("records") or []
            parser_label = auto_parse.get("parser") or _parser_label(None)
            try:
                contract = _field_contract(device.get("field_contract_json"))
                if not contract and device.get("required_fields_json"):
                    contract = _field_contract({
                        "required": json.loads(device["required_fields_json"] or "[]"),
                        "optional": json.loads(device.get("optional_fields_json") or "[]"),
                        "types": json.loads(device.get("field_types_json") or "{}"),
                    })
            except Exception:
                # Contracts are hints for field naming/type coercion.  A bad
                # contract must not hide a valid command response.
                logger.info("Ignoring invalid action field contract action=%s", action_code, exc_info=True)
                contract = {}
            expected_fields = set(contract.get("required") or []) | set(contract.get("optional") or []) | set((contract.get("types") or {}).keys())
            normalized_records = _normalize_records(
                records,
                int(device.get("max_records") or 1000),
                expected_fields=expected_fields,
            )
            _coerce_field_types(normalized_records, contract)
        except Exception as parse_exc:
            logger.warning(
                "Automatic action parser failed action=%s device=%s: %s",
                action_code,
                device_id,
                parse_exc,
            )
            auto_parse = {
                "records": [],
                "parse_status": "failed",
                "parser": "platform-parser",
                "parser_platform": device.get("parser_platform") or device.get("platform"),
                "template": None,
                "template_source": None,
                "message": str(parse_exc),
            }
            normalized_records = []
            parser_label = "platform-parser"
        parse_status = auto_parse.get("parse_status") or ("matched" if normalized_records else "unmatched")
        response = {
            "success": True,
            "error_code": None,
            "action_code": action_code,
            "platform_release_id": device["current_release_id"],
            "release_number": device["release_number"],
            "release_checksum": device["release_checksum"],
            "command": resolved_command,
            "command_checksum": device.get("command_checksum"),
            "resolved_command_checksum": _checksum(resolved_command),
            "parser": parser_label,
            "parser_selection": "automatic",
            "parser_platform": auto_parse.get("parser_platform"),
            "template": auto_parse.get("template"),
            "template_source": auto_parse.get("template_source"),
            "template_action_code": auto_parse.get("template_action_code"),
            "template_action_match": (
                not auto_parse.get("template_action_code")
                or auto_parse.get("template_action_code") == action_code
            ),
            "parse_status": parse_status,
            "parser_message": auto_parse.get("message") or None,
                "records": normalized_records,
            "raw_output": redact_raw_output(output) if include_raw_output else None,
        }
        _audit("ACTION_EXECUTED", {"platform_release_id": device["current_release_id"], "device_id": device_id, "action_code": action_code, "success": True, "record_count": len(normalized_records), "parse_status": parse_status, "parser": parser_label, "command": resolved_command, "command_checksum": device.get("command_checksum"), "resolved_command_checksum": _checksum(resolved_command)}, output)
        return response
    finally:
        conn.close()
