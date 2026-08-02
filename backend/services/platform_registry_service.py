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
import uuid
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection

logger = logging.getLogger(__name__)

PLATFORM_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
TEMPLATE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
ALLOWED_CONNECTION_DRIVERS = {
    "netmiko", "scrapli", "mock", "cisco_ios", "huawei_vrp", "hp_comware",
    "juniper_junos", "arista_eos", "zte_zxros", "ruijie_os", "dptech_ios", "maipu",
}
CONNECTION_DRIVER_TO_IMPLEMENTATION = {
    "cisco_ios": "netmiko", "huawei_vrp": "netmiko", "hp_comware": "netmiko",
    "juniper_junos": "netmiko", "arista_eos": "netmiko", "zte_zxros": "netmiko",
    "ruijie_os": "netmiko", "dptech_ios": "netmiko", "maipu": "netmiko",
}

ACTION_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"action_code": "get_version", "name_zh": "获取版本", "name_en": "Get Version", "purpose": "设备版本和型号", "risk": "low", "consumers": ["discovery", "inspection", "automation"], "fields": ["vendor", "model", "version"], "max_records": 8},
    {"action_code": "get_lldp_neighbors", "name_zh": "获取 LLDP 邻居", "name_en": "Get LLDP Neighbors", "purpose": "拓扑邻居发现", "risk": "low", "consumers": ["topology", "discovery"], "fields": ["local_interface", "remote_device", "remote_interface"], "max_records": 5000},
    {"action_code": "get_interface_brief", "name_zh": "获取接口摘要", "name_en": "Get Interface Brief", "purpose": "接口状态采集", "risk": "low", "consumers": ["cmdb", "inspection"], "fields": ["interface", "admin_status", "oper_status", "ip_address"], "max_records": 2000},
    {"action_code": "get_interfaces", "name_zh": "获取接口详情", "name_en": "Get Interfaces", "purpose": "接口详情采集", "risk": "low", "consumers": ["cmdb", "inspection"], "fields": ["interface", "description", "speed", "mac_address"], "max_records": 2000},
    {"action_code": "get_ip_interfaces", "name_zh": "获取三层接口", "name_en": "Get IP Interfaces", "purpose": "接口 IP 采集", "risk": "low", "consumers": ["cmdb", "ip_locator"], "fields": ["interface", "ip_address", "prefix_length"], "max_records": 2000},
    {"action_code": "get_link_aggregation", "name_zh": "获取链路聚合", "name_en": "Get Link Aggregation", "purpose": "聚合口采集", "risk": "low", "consumers": ["topology", "cmdb"], "fields": ["group", "interface", "member"], "max_records": 1000},
    {"action_code": "get_arp_table", "name_zh": "获取 ARP 表", "name_en": "Get ARP Table", "purpose": "ARP 采集", "risk": "low", "consumers": ["ip_locator", "collection"], "fields": ["ip", "mac", "interface"], "max_records": 10000},
    {"action_code": "get_mac_table", "name_zh": "获取 MAC 表", "name_en": "Get MAC Table", "purpose": "MAC 采集", "risk": "low", "consumers": ["ip_locator", "collection"], "fields": ["mac", "vlan", "interface"], "max_records": 10000},
    {"action_code": "get_vlan_table", "name_zh": "获取 VLAN 表", "name_en": "Get VLAN Table", "purpose": "VLAN 采集", "risk": "low", "consumers": ["collection", "inspection"], "fields": ["vlan", "name", "status"], "max_records": 4096},
    {"action_code": "get_route_table", "name_zh": "获取路由表", "name_en": "Get Route Table", "purpose": "路由采集", "risk": "low", "consumers": ["collection", "inspection"], "fields": ["prefix", "next_hop", "interface"], "max_records": 20000},
    {"action_code": "get_bgp_neighbors", "name_zh": "获取 BGP 邻居", "name_en": "Get BGP Neighbors", "purpose": "BGP 邻居采集", "risk": "low", "consumers": ["inspection"], "fields": ["neighbor", "asn", "state"], "max_records": 1000},
    {"action_code": "get_ospf_neighbors", "name_zh": "获取 OSPF 邻居", "name_en": "Get OSPF Neighbors", "purpose": "OSPF 邻居采集", "risk": "low", "consumers": ["inspection"], "fields": ["neighbor", "state", "interface"], "max_records": 1000},
    {"action_code": "get_transceivers", "name_zh": "获取光模块", "name_en": "Get Transceivers", "purpose": "光模块采集", "risk": "low", "consumers": ["inspection"], "fields": ["interface", "vendor", "serial"], "max_records": 2000},
    {"action_code": "get_cpu", "name_zh": "获取 CPU", "name_en": "Get CPU", "purpose": "CPU 健康度", "risk": "low", "consumers": ["inspection", "monitoring"], "fields": ["usage"], "max_records": 32},
    {"action_code": "get_memory", "name_zh": "获取内存", "name_en": "Get Memory", "purpose": "内存健康度", "risk": "low", "consumers": ["inspection", "monitoring"], "fields": ["usage", "total"], "max_records": 32},
    {"action_code": "get_fans", "name_zh": "获取风扇", "name_en": "Get Fans", "purpose": "风扇健康度", "risk": "low", "consumers": ["inspection"], "fields": ["name", "status"], "max_records": 128},
    {"action_code": "get_power", "name_zh": "获取电源", "name_en": "Get Power", "purpose": "电源健康度", "risk": "low", "consumers": ["inspection"], "fields": ["name", "status"], "max_records": 128},
    {"action_code": "get_temperature", "name_zh": "获取温度", "name_en": "Get Temperature", "purpose": "温度健康度", "risk": "low", "consumers": ["inspection", "monitoring"], "fields": ["sensor", "temperature", "status"], "max_records": 128},
    {"action_code": "get_clock", "name_zh": "获取时钟", "name_en": "Get Clock", "purpose": "设备时间", "risk": "low", "consumers": ["inspection"], "fields": ["clock", "timezone"], "max_records": 8},
    {"action_code": "get_running_config", "name_zh": "获取运行配置", "name_en": "Get Running Config", "purpose": "配置备份和审计", "risk": "sensitive", "consumers": ["configuration", "inspection"], "fields": ["configuration"], "max_records": 1},
)

SYSTEM_PROFILES: tuple[dict[str, Any], ...] = (
    {"platform_code": "cisco_ios", "name_zh": "Cisco IOS", "name_en": "Cisco IOS", "vendor": "Cisco", "connection_driver": "cisco_ios", "parser_platform": "cisco_ios"},
    {"platform_code": "huawei_vrp", "name_zh": "Huawei VRP", "name_en": "Huawei VRP", "vendor": "Huawei", "connection_driver": "huawei_vrp", "parser_platform": "huawei_vrp"},
    {"platform_code": "h3c_comware", "name_zh": "H3C Comware", "name_en": "H3C Comware", "vendor": "H3C", "connection_driver": "hp_comware", "parser_platform": "hp_comware"},
    {"platform_code": "juniper_junos", "name_zh": "Juniper Junos", "name_en": "Juniper Junos", "vendor": "Juniper", "connection_driver": "juniper_junos", "parser_platform": "juniper_junos"},
    {"platform_code": "arista_eos", "name_zh": "Arista EOS", "name_en": "Arista EOS", "vendor": "Arista", "connection_driver": "arista_eos", "parser_platform": "arista_eos"},
    {"platform_code": "zte_5900_v6", "name_zh": "中兴 5900 V6", "name_en": "ZTE 5900 V6", "vendor": "ZTE", "connection_driver": "zte_zxros", "parser_platform": "zte_zxros"},
    {"platform_code": "zte_zsrv2_v3", "name_zh": "中兴 ZSRV2 V3", "name_en": "ZTE ZSRV2 V3", "vendor": "ZTE", "connection_driver": "zte_zxros", "parser_platform": "zte_zxros"},
    {"platform_code": "ruijie_s6k_rgos12", "name_zh": "锐捷 S6K RGOS 12", "name_en": "Ruijie S6K RGOS 12", "vendor": "Ruijie", "connection_driver": "ruijie_os", "parser_platform": "ruijie_rgos"},
    {"platform_code": "ruijie_eg_rgos11", "name_zh": "锐捷 EG RGOS 11", "name_en": "Ruijie EG RGOS 11", "vendor": "Ruijie", "connection_driver": "ruijie_os", "parser_platform": "ruijie_rgos"},
    {"platform_code": "dptech_fw_s211", "name_zh": "迪普 FW S211", "name_en": "DPtech FW S211", "vendor": "DPtech", "connection_driver": "dptech_ios", "parser_platform": "dptech_ios"},
    {"platform_code": "maipu_s3330_v9", "name_zh": "迈普 S3330 V9", "name_en": "Maipu S3330 V9", "vendor": "Maipu", "connection_driver": "maipu", "parser_platform": "maipu"},
)

PLATFORM_ALIASES = {
    "cisco": "cisco_ios", "ios": "cisco_ios", "huawei": "huawei_vrp", "vrp": "huawei_vrp",
    "huawei_vrpv8": "huawei_vrp", "h3c": "h3c_comware", "comware": "h3c_comware",
    "hp_comware": "h3c_comware", "comware9": "h3c_comware", "juniper": "juniper_junos",
    "junos": "juniper_junos", "arista": "arista_eos", "eos": "arista_eos", "zte": "zte_5900_v6",
    "zte_zxros": "zte_5900_v6", "ruijie": "ruijie_s6k_rgos12", "ruijie_os": "ruijie_s6k_rgos12",
    "ruijie_rgos": "ruijie_s6k_rgos12", "dptech": "dptech_fw_s211", "dptech_ios": "dptech_fw_s211",
    "maipu": "maipu_s3330_v9",
}

# The commands are explicit data, never inferred from a requested vendor and
# never allowed to silently fall back to Cisco.
PLATFORM_ACTION_COMMANDS: dict[str, dict[str, str]] = {
    "cisco_ios": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbors detail", "get_interface_brief": "show ip interface brief", "get_interfaces": "show interfaces", "get_ip_interfaces": "show ip interface", "get_link_aggregation": "show etherchannel summary", "get_arp_table": "show ip arp", "get_mac_table": "show mac address-table", "get_vlan_table": "show vlan brief", "get_route_table": "show ip route", "get_bgp_neighbors": "show ip bgp neighbors", "get_ospf_neighbors": "show ip ospf neighbor", "get_transceivers": "show interfaces transceiver", "get_cpu": "show processes cpu", "get_memory": "show processes memory", "get_fans": "show environment fan", "get_power": "show environment power", "get_temperature": "show environment temperature", "get_clock": "show clock", "get_running_config": "show running-config"},
    "huawei_vrp": {"get_version": "display version", "get_lldp_neighbors": "display lldp neighbor brief", "get_interface_brief": "display interface brief", "get_interfaces": "display interface", "get_ip_interfaces": "display ip interface brief", "get_link_aggregation": "display eth-trunk", "get_arp_table": "display arp", "get_mac_table": "display mac-address", "get_vlan_table": "display vlan", "get_route_table": "display ip routing-table", "get_bgp_neighbors": "display bgp peer", "get_ospf_neighbors": "display ospf peer brief", "get_transceivers": "display transceiver interface", "get_cpu": "display cpu-usage", "get_memory": "display memory-usage", "get_fans": "display fan", "get_power": "display power", "get_temperature": "display temperature", "get_clock": "display clock", "get_running_config": "display current-configuration"},
    "h3c_comware": {"get_version": "display version", "get_lldp_neighbors": "display lldp neighbor-information list", "get_interface_brief": "display interface brief", "get_interfaces": "display interface", "get_ip_interfaces": "display ip interface brief", "get_link_aggregation": "display link-aggregation verbose", "get_arp_table": "display arp all", "get_mac_table": "display mac-address", "get_vlan_table": "display vlan brief", "get_route_table": "display ip routing-table", "get_bgp_neighbors": "display bgp peer ipv4", "get_ospf_neighbors": "display ospf peer", "get_transceivers": "display transceiver interface", "get_cpu": "display cpu-usage", "get_memory": "display memory", "get_fans": "display fan", "get_power": "display power", "get_temperature": "display environment", "get_clock": "display clock", "get_running_config": "display current-configuration"},
    "juniper_junos": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbors detail", "get_interfaces": "show interfaces detail", "get_interface_brief": "show interfaces terse", "get_ip_interfaces": "show interfaces terse", "get_route_table": "show route", "get_clock": "show system uptime", "get_running_config": "show configuration"},
    "arista_eos": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbors detail", "get_interface_brief": "show ip interface brief", "get_interfaces": "show interfaces", "get_ip_interfaces": "show ip interface", "get_link_aggregation": "show port-channel summary", "get_arp_table": "show arp", "get_mac_table": "show mac address-table", "get_vlan_table": "show vlan", "get_route_table": "show ip route", "get_bgp_neighbors": "show ip bgp summary", "get_ospf_neighbors": "show ip ospf neighbor", "get_transceivers": "show interfaces transceiver", "get_cpu": "show processes top once", "get_memory": "show version", "get_clock": "show clock", "get_running_config": "show running-config"},
    "ruijie_rgos": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbors", "get_interface_brief": "show interface brief", "get_interfaces": "show interfaces", "get_ip_interfaces": "show ip interface brief", "get_arp_table": "show arp", "get_mac_table": "show mac address-table", "get_vlan_table": "show vlan", "get_route_table": "show ip route", "get_bgp_neighbors": "show ip bgp neighbors", "get_ospf_neighbors": "show ip ospf neighbor", "get_transceivers": "show interfaces transceiver", "get_cpu": "show cpu", "get_memory": "show memory", "get_fans": "show fan", "get_power": "show power", "get_temperature": "show temperature", "get_clock": "show clock"},
    "zte_zxros": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbor", "get_interface_brief": "show interface brief", "get_ip_interfaces": "show ip interface brief", "get_arp_table": "show arp", "get_mac_table": "show mac table", "get_route_table": "show ip forwarding route", "get_bgp_neighbors": "show ip bgp neighbors", "get_ospf_neighbors": "show ip ospf neighbor", "get_transceivers": "show opticalinfo brief", "get_fans": "show fan", "get_power": "show power", "get_temperature": "show temperature detail", "get_clock": "show clock"},
    "dptech_ios": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbors", "get_interface_brief": "show interface brief", "get_ip_interfaces": "show ip interface brief", "get_arp_table": "show arp all", "get_mac_table": "show mac address-table", "get_vlan_table": "show vlan", "get_route_table": "show ip route", "get_cpu": "show cpu usage", "get_memory": "show memory", "get_clock": "show clock"},
    "maipu": {"get_version": "show version", "get_lldp_neighbors": "show lldp neighbors", "get_interface_brief": "show interface brief", "get_ip_interfaces": "show ip interface brief", "get_arp_table": "show arp", "get_mac_table": "show mac address all", "get_vlan_table": "show vlan", "get_route_table": "show ip route", "get_bgp_neighbors": "show ip bgp summary", "get_ospf_neighbors": "show ip ospf neighbor", "get_transceivers": "show optical all", "get_cpu": "show cpu monitor", "get_memory": "show memory utilization", "get_fans": "show system fan", "get_power": "show system power", "get_clock": "show clock"},
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


def normalize_platform_code(value: str) -> str:
    code = str(value or "").strip().lower()
    return PLATFORM_ALIASES.get(code, code)


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
    if prefix not in {"show", "display", "get"}:
        return False
    if connection_driver in {"juniper_junos"} and prefix != "show":
        return False
    return True


def _row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _profile_scope_clause(user: dict[str, Any]) -> tuple[str, list[Any]]:
    tenant_id = str(user.get("tenant_id") or "")
    if tenant_id:
        return "AND (p.tenant_id IS NULL OR p.tenant_id = ?)", [tenant_id]
    return "", []


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
        rows = conn.execute(
            f"""SELECT p.*, r.release_number AS current_release_number, r.checksum AS current_release_checksum
                FROM platform_profiles p LEFT JOIN platform_releases r ON r.id = p.current_release_id
                WHERE p.status <> 'ARCHIVED' {scope_sql} ORDER BY p.source, p.platform_code""",
            params,
        ).fetchall()
        return [_row_dict(row) for row in rows]
    finally:
        conn.close()


def get_profile(profile_id: str, user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        scope_sql, params = _profile_scope_clause(user)
        row = conn.execute(
            f"SELECT p.*, r.release_number AS current_release_number, r.checksum AS current_release_checksum FROM platform_profiles p LEFT JOIN platform_releases r ON r.id = p.current_release_id WHERE p.id = ? {scope_sql}",
            [profile_id, *params],
        ).fetchone()
        if not row:
            raise PlatformRegistryError("PLATFORM_NOT_FOUND", "Platform profile not found", status_code=404)
        result = _row_dict(row) or {}
        result["releases"] = [_row_dict(item) for item in conn.execute("SELECT * FROM platform_releases WHERE profile_id = ? ORDER BY release_number DESC", (profile_id,)).fetchall()]
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


def create_release(profile_id: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    profile = get_profile(profile_id, user)
    release_id = str(uuid.uuid4())
    now = _now()
    conn = get_db_connection()
    try:
        next_number = conn.execute("SELECT COALESCE(MAX(release_number), 0) + 1 AS next_number FROM platform_releases WHERE profile_id = ?", (profile_id,)).fetchone()["next_number"]
        conn.execute(
            """INSERT INTO platform_releases (id, profile_id, release_number, status, connection_driver, parser_platform, safety_policy_json, checksum, created_by, created_at, updated_at, lock_version)
               VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?, 1)""",
            (release_id, profile_id, next_number, profile["connection_driver"], profile["parser_platform"], _json(payload.get("safety_policy") or {"read_only": True}), _checksum({"profile_id": profile_id, "release_number": next_number, "actions": []}), user.get("id") or user.get("username") or "", now, now),
        )
        conn.commit()
        return _row_dict(conn.execute("SELECT * FROM platform_releases WHERE id = ?", (release_id,)).fetchone()) or {}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_release_actions(profile_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    get_profile(profile_id, user)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT d.*, a.command, a.parser_template_version_id, a.field_contract_json, a.command_checksum
               FROM action_definitions d LEFT JOIN platform_release_actions a
                 ON a.action_code = d.action_code AND a.release_id = (SELECT current_release_id FROM platform_profiles WHERE id = ?)
               ORDER BY d.action_code""",
            (profile_id,),
        ).fetchall()
        return [_row_dict(row) for row in rows]
    finally:
        conn.close()


def resolve_action_mapping(platform_code: str, action_code: str) -> dict[str, Any]:
    """Resolve a system profile action for legacy consumers that only have a platform key.

    It is intentionally strict: an absent mapping is an unsupported action,
    never a Cisco command fallback.
    """
    canonical = normalize_platform_code(platform_code)
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT p.platform_code, p.connection_driver, p.parser_platform, r.id AS platform_release_id,
                      r.release_number, r.checksum AS release_checksum, a.command, a.parser_template_version_id,
                      a.field_contract_json
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


def _release_for_id(conn, release_id: str, *, lock: bool = False) -> dict[str, Any]:
    # SQLite does not support PostgreSQL's row-lock syntax; the migration and
    # publish path remain transactional there while PostgreSQL gets FOR UPDATE.
    import database as _database
    suffix = " FOR UPDATE" if lock and _database._USE_PG else ""
    row = conn.execute(f"SELECT * FROM platform_releases WHERE id = ?{suffix}", (release_id,)).fetchone()
    if not row:
        raise PlatformRegistryError("RELEASE_NOT_FOUND", "Platform release not found", status_code=404)
    return _row_dict(row) or {}


def update_release_action(release_id: str, action_code: str, payload: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        release = _release_for_id(conn, release_id)
        profile = _assert_profile_access(conn, release["profile_id"], user)
        if release["status"] != "DRAFT":
            raise PlatformRegistryError("RELEASE_IMMUTABLE", "Only draft releases can be edited")
        definition = conn.execute("SELECT * FROM action_definitions WHERE action_code = ?", (action_code,)).fetchone()
        if not definition:
            raise PlatformRegistryError("UNSUPPORTED_ACTION", "Unknown action_code")
        command = str(payload.get("command") or "").strip()
        if not is_safe_read_command(command, profile["connection_driver"]):
            raise PlatformRegistryError("UNSAFE_COMMAND", "Only one read-only show/display command is allowed")
        parser_version_id = payload.get("parser_template_version_id") or None
        if parser_version_id:
            exists = conn.execute("SELECT 1 FROM parser_template_versions WHERE id = ?", (parser_version_id,)).fetchone()
            if not exists:
                raise PlatformRegistryError("PARSER_VERSION_NOT_FOUND", "Parser template version not found", status_code=404)
        contract = payload.get("field_contract") or {"required": json.loads(definition["required_fields_json"] or "[]"), "optional": json.loads(definition["optional_fields_json"] or "[]")}
        now = _now()
        action_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO platform_release_actions (id, release_id, action_code, command, parser_template_version_id, field_contract_json, command_checksum, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(release_id, action_code) DO UPDATE SET command=excluded.command, parser_template_version_id=excluded.parser_template_version_id, field_contract_json=excluded.field_contract_json, command_checksum=excluded.command_checksum, updated_at=excluded.updated_at""",
            (action_id, release_id, action_code, command, parser_version_id, _json(contract), _checksum(command), now, now),
        )
        actions = [dict(row) for row in conn.execute("SELECT action_code, command, parser_template_version_id, field_contract_json FROM platform_release_actions WHERE release_id = ? ORDER BY action_code", (release_id,)).fetchall()]
        conn.execute("UPDATE platform_releases SET checksum = ?, updated_at = ?, lock_version = lock_version + 1 WHERE id = ?", (_checksum(actions), now, release_id))
        conn.commit()
        return _row_dict(conn.execute("SELECT * FROM platform_release_actions WHERE release_id = ? AND action_code = ?", (release_id, action_code)).fetchone()) or {}
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
        actions = conn.execute("SELECT a.*, d.max_output_bytes, d.max_records FROM platform_release_actions a JOIN action_definitions d ON d.action_code = a.action_code WHERE a.release_id = ?", (release_id,)).fetchall()
        errors: list[dict[str, str]] = []
        for action in actions:
            if not is_safe_read_command(action["command"], profile.get("connection_driver", "")):
                errors.append({"code": "UNSAFE_COMMAND", "action_code": action["action_code"]})
        if not actions:
            errors.append({"code": "NO_ACTIONS", "message": "Release must contain at least one action"})
        result = {"valid": not errors, "errors": errors, "action_count": len(actions), "checksum": release.get("checksum")}
        conn.execute("UPDATE platform_releases SET validation_status = ?, validation_result_json = ?, updated_at = ? WHERE id = ?", ("PASSED" if not errors else "FAILED", _json(result), _now(), release_id))
        conn.commit()
        return result
    finally:
        conn.close()


def transition_release(release_id: str, event: str, user: dict[str, Any]) -> dict[str, Any]:
    target = {"submit": ("DRAFT", "IN_REVIEW"), "approve": ("IN_REVIEW", "APPROVED"), "publish": ("APPROVED", "PUBLISHED")}.get(event)
    if not target:
        raise PlatformRegistryError("INVALID_RELEASE_EVENT", "Unsupported release transition")
    validation = validate_release(release_id, user)
    if event in {"submit", "approve", "publish"} and not validation["valid"]:
        raise PlatformRegistryError("RELEASE_VALIDATION_FAILED", "Release validation failed")
    conn = get_db_connection()
    try:
        release = _release_for_id(conn, release_id, lock=True)
        _assert_profile_access(conn, release["profile_id"], user)
        if release["status"] != target[0]:
            raise PlatformRegistryError("INVALID_RELEASE_STATE", f"Release must be {target[0]} before {event}")
        if event == "approve" and release.get("created_by") == (user.get("id") or user.get("username")):
            raise PlatformRegistryError("SELF_APPROVAL_FORBIDDEN", "The creator cannot approve their own release", status_code=403)
        now = _now()
        conn.execute("UPDATE platform_releases SET status = ?, updated_at = ?, lock_version = lock_version + 1, approved_by = CASE WHEN ? = 'APPROVED' THEN ? ELSE approved_by END, published_by = CASE WHEN ? = 'PUBLISHED' THEN ? ELSE published_by END WHERE id = ?", (target[1], now, target[1], user.get("id") or user.get("username") or "", target[1], user.get("id") or user.get("username") or "", release_id))
        conn.execute("INSERT INTO platform_release_audit_logs (id, release_id, event_type, actor_id, actor_username, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), release_id, event.upper(), user.get("id"), user.get("username"), _json({"from": target[0], "to": target[1]}), now))
        if event == "publish":
            conn.execute("UPDATE platform_releases SET status = 'DEPRECATED', updated_at = ? WHERE profile_id = ? AND status = 'PUBLISHED' AND id <> ?", (now, release["profile_id"], release_id))
            conn.execute("UPDATE platform_profiles SET current_release_id = ?, updated_at = ?, lock_version = lock_version + 1 WHERE id = ?", (release_id, now, release["profile_id"]))
        conn.commit()
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
        profile = _assert_profile_access(conn, profile_id, user)
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
        return _row_dict(conn.execute("SELECT * FROM platform_releases WHERE id = ?", (target_id,)).fetchone()) or {}
    finally:
        conn.close()


def _normalize_records(records: list[dict[str, Any]], max_records: int) -> list[dict[str, Any]]:
    result = []
    for record in records[:max_records]:
        normalized = {}
        for key, value in (record or {}).items():
            canonical = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")
            normalized[canonical] = value.strip() if isinstance(value, str) else value
        result.append(normalized)
    return result


def execute_platform_action(device_id: str, action_code: str, *, user: dict[str, Any], driver_factory=None) -> dict[str, Any]:
    """Execute one action from the device's immutable current release."""
    if not action_code or not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", action_code):
        raise PlatformRegistryError("INVALID_ACTION_CODE", "Invalid action_code")
    conn = get_db_connection()
    def _audit(event_type: str, metadata: dict[str, Any]) -> None:
        try:
            conn.execute(
                "INSERT INTO platform_release_audit_logs (id, release_id, event_type, actor_id, actor_username, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), str(metadata.get("platform_release_id") or ""), event_type, user.get("id"), user.get("username"), _json(metadata)),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.warning("Failed to write platform action audit", exc_info=True)
    try:
        row = conn.execute(
            """SELECT d.*, p.id AS profile_id, p.platform_code, p.connection_driver, p.parser_platform, p.current_release_id, r.checksum AS release_checksum,
                      r.release_number, a.command, a.parser_template_version_id, a.field_contract_json, a.command_checksum, def.max_output_bytes, def.max_records, def.sensitive_level
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
        if not device.get("current_release_id") or not device.get("release_number"):
            raise PlatformRegistryError("NO_PUBLISHED_RELEASE", "Device has no published platform release")
        if not device.get("command"):
            raise PlatformRegistryError("UNSUPPORTED_ACTION", "The current platform release does not map this action")
        if device.get("sensitive_level") == "sensitive" and user.get("role") != "Administrator":
            raise PlatformRegistryError("SENSITIVE_ACTION_FORBIDDEN", "get_running_config requires Administrator permission", status_code=403)
        if not is_safe_read_command(device["command"], device.get("connection_driver") or ""):
            raise PlatformRegistryError("UNSAFE_COMMAND", "Release contains an unsafe command")
        if driver_factory is None:
            from drivers.factory import DriverFactory
            driver_factory = DriverFactory
        driver_type = CONNECTION_DRIVER_TO_IMPLEMENTATION.get(device.get("connection_driver"), device.get("connection_driver"))
        device["driver_type"] = driver_type
        device["platform"] = device.get("parser_platform") or device.get("platform")
        driver = driver_factory.get_driver(driver_type, device)
        with driver:
            result = driver.send_command(device["command"])
        output = str(getattr(result, "output", "") or "")
        if not getattr(result, "success", False):
            response = {"success": False, "error_code": "CONNECTION_OR_COMMAND_FAILED", "error": getattr(result, "error", "Command execution failed"), "action_code": action_code, "platform_release_id": device["current_release_id"], "release_number": device["release_number"], "command": device["command"]}
            _audit("ACTION_EXECUTED", {"platform_release_id": device["current_release_id"], "device_id": device_id, "action_code": action_code, "success": False, "error_code": response["error_code"]})
            return response
        max_bytes = int(device.get("max_output_bytes") or 2_000_000)
        if len(output.encode("utf-8", errors="ignore")) > max_bytes:
            response = {"success": False, "error_code": "OUTPUT_LIMIT_EXCEEDED", "error": "Command output exceeds the action limit", "action_code": action_code, "platform_release_id": device["current_release_id"]}
            _audit("ACTION_EXECUTED", {"platform_release_id": device["current_release_id"], "device_id": device_id, "action_code": action_code, "success": False, "error_code": response["error_code"]})
            return response
        try:
            from core.textfsm import parse_with_template_content, smart_parse_cli
            if device.get("parser_template_version_id"):
                template = conn.execute("SELECT content FROM parser_template_versions WHERE id = ?", (device["parser_template_version_id"],)).fetchone()
                records = parse_with_template_content(template["content"], output) if template else []
            else:
                parsed = smart_parse_cli(output=output, command=device["command"], platform=device.get("parser_platform"))
                records = parsed.get("data") or [] if parsed.get("success") else []
        except Exception as parse_exc:
            logger.warning("Platform action parse failed action=%s device=%s: %s", action_code, device_id, parse_exc)
            response = {"success": False, "error_code": "TEMPLATE_NOT_MATCHED", "error": "Parser template failed", "action_code": action_code, "platform_release_id": device["current_release_id"]}
            _audit("ACTION_EXECUTED", {"platform_release_id": device["current_release_id"], "device_id": device_id, "action_code": action_code, "success": False, "error_code": response["error_code"]})
            return response
        if not records and action_code not in {"get_running_config", "get_clock"}:
            response = {"success": False, "error_code": "TEMPLATE_NOT_MATCHED", "error": "Parser returned no records", "action_code": action_code, "platform_release_id": device["current_release_id"]}
            _audit("ACTION_EXECUTED", {"platform_release_id": device["current_release_id"], "device_id": device_id, "action_code": action_code, "success": False, "error_code": response["error_code"]})
            return response
        response = {"success": True, "error_code": None, "action_code": action_code, "platform_release_id": device["current_release_id"], "release_number": device["release_number"], "release_checksum": device["release_checksum"], "command": device["command"], "records": _normalize_records(records, int(device.get("max_records") or 1000)), "raw_output": output if action_code == "get_running_config" else None}
        _audit("ACTION_EXECUTED", {"platform_release_id": device["current_release_id"], "device_id": device_id, "action_code": action_code, "success": True, "command_checksum": device.get("command_checksum")})
        return response
    finally:
        conn.close()
