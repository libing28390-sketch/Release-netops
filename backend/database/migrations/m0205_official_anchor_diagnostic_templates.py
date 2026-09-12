"""Add official-source templates for the six semantically mismatched anchors.

The original anchor set pointed several read-only diagnostics at unrelated
configuration templates. These source-backed rows provide the correct corpus
identities; dataset review remains a separate, auditable step.
"""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 205
NAME = "official_anchor_diagnostic_templates"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _columns(cursor) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'templates'"
    )
    return {str(row[0]) for row in cursor.fetchall()}


def _ensure_columns(cursor) -> None:
    definitions = {
        "description": "TEXT DEFAULT ''",
        "platform_family": "TEXT DEFAULT ''",
        "software_version": "TEXT DEFAULT ''",
        "official_reference": "TEXT DEFAULT ''",
        "validation_status": "TEXT DEFAULT 'draft'",
        "source_type": "TEXT DEFAULT 'user'",
        "risk_level": "TEXT DEFAULT 'low'",
        "status": "TEXT DEFAULT 'draft'",
        "current_version": "TEXT DEFAULT '1.0'",
        "is_official": "INTEGER DEFAULT 0",
        "created_by": "TEXT DEFAULT ''",
        "created_at": "TEXT DEFAULT ''",
        "updated_at": "TEXT DEFAULT ''",
    }
    existing = _columns(cursor)
    for column, definition in definitions.items():
        if column not in existing:
            cursor.execute(f"ALTER TABLE templates ADD COLUMN {column} {definition}")


_TEMPLATES = (
    {
        "id": "official-huawei-ce12800-vxlan-evpn-basic",
        "name": "VXLAN EVPN 集中式网关（华为 CE12800）",
        "category": "overlay",
        "vendor": "Huawei",
        "platform": "huawei_vrp",
        "version": "CloudEngine 12800 V200R024C00",
        "description": "CE12800 VXLAN EVPN 集中式网关配置骨架；VTEP、VPN 实例和网关部署方式必须按版本化官方指南核对。",
        "content": """system-view
bridge-domain {{ bridge_domain | default(10) }}
 vxlan vni {{ vni | default(10010) }}
quit
interface Nve1
 source {{ loopback_interface | default(\"LoopBack0\") }}
 vni {{ vni | default(10010) }} head-end peer-list {{ peer_vtep | default(\"192.0.2.12\") }}
quit
bgp {{ local_as | default(65000) }}
 l2vpn-family evpn
  peer {{ peer_ip | default(\"192.0.2.12\") }} as-number {{ peer_as | default(65000) }}
  peer {{ peer_ip | default(\"192.0.2.12\") }} enable
quit
return

display vxlan tunnel
display bgp evpn peer""",
        "rollback": """system-view
undo bgp {{ local_as | default(65000) }}
interface Nve1
 undo vni {{ vni | default(10010) }}
quit
undo bridge-domain {{ bridge_domain | default(10) }}
return""",
        "reference": "https://info.support.huawei.com/enterprise/zh/doc/EDOC1100420462/b4590a84",
    },
    {
        "id": "official-huawei-port-security-basic",
        "name": "端口安全与动态 MAC 限制（华为 VRP）",
        "category": "security",
        "vendor": "Huawei",
        "platform": "huawei_vrp",
        "version": "VRP 8 / V200R023-V300R024",
        "description": "启用端口安全并限制安全动态 MAC 数量；端口类型、违规动作和版本支持须按目标型号复核。",
        "content": """system-view
interface {{ interface_name | default(\"GigabitEthernet 0/0/1\") }}
 port-security enable
 port-security maximum {{ maximum_mac | default(2) }}
 port-security protect-action {{ protect_action | default(\"restrict\") }}
quit
return

display current-configuration interface {{ interface_name | default(\"GigabitEthernet 0/0/1\") }}
display mac-address interface {{ interface_name | default(\"GigabitEthernet 0/0/1\") }}""",
        "rollback": """system-view
interface {{ interface_name | default(\"GigabitEthernet 0/0/1\") }}
 undo port-security protect-action
 undo port-security maximum
 undo port-security enable
quit
return""",
        "reference": "https://info.support.huawei.com/hedex/api/pages/EDOC1000053358/YEF0907R/25/resources/en-us_task_0133020498.html",
    },
    {
        "id": "official-huawei-cpu-memory-diagnostic",
        "name": "CPU 与内存状态排障命令（华为 VRP）",
        "category": "operations",
        "vendor": "Huawei",
        "platform": "huawei_vrp",
        "version": "VRP 8 / V200R023-V300R024",
        "description": "使用 display cpu-usage、display memory-usage 和设备状态命令进行只读排障；单次采样不能替代趋势分析。",
        "content": """display cpu-usage
display memory-usage
display memory-usage threshold
display device
display logbuffer""",
        "rollback": "",
        "reference": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100333828/91652f17/device-status-checking-commands",
    },
    {
        "id": "official-cisco-arp-mac-diagnostic",
        "name": "ARP 与 MAC 表排障命令（Cisco IOS XE）",
        "category": "operations",
        "vendor": "Cisco",
        "platform": "cisco_iosxe",
        "version": "IOS XE 17.x",
        "description": "分别查看三层 ARP 解析和二层 MAC 学习，并结合接口状态定位问题；这是只读诊断条目。",
        "content": """show ip arp
show ip arp {{ ip_address | default(\"192.0.2.10\") }}
show mac address-table
show mac address-table dynamic
show interfaces status
show interfaces {{ interface_name | default(\"GigabitEthernet1/0/1\") }} switchport""",
        "rollback": "",
        "reference": "https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_arp/configuration/xe-3s/arp-xe-3s-book.pdf",
    },
    {
        "id": "official-h3c-interface-brief-diagnostic",
        "name": "display interface brief 状态查看（H3C Comware 7）",
        "category": "operations",
        "vendor": "H3C",
        "platform": "h3c_comware",
        "version": "Comware 7",
        "description": "查看路由接口和桥接口的摘要状态，并按 Link、Protocol、速率、Type、PVID 等字段排障。",
        "content": """display interface brief
display interface {{ interface_name | default(\"GigabitEthernet 1/0/1\") }}
display counters inbound interface {{ interface_name | default(\"GigabitEthernet 1/0/1\") }}
display logbuffer""",
        "rollback": "",
        "reference": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Routers/00-Public/Reference_Guides/Command_References/H3C_MSR_Comware_7_CR-R0615/03/202210/1709588_294551_0.htm",
    },
    {
        "id": "official-h3c-arp-mac-diagnostic",
        "name": "ARP 与 MAC 表排障命令（H3C Comware 7）",
        "category": "operations",
        "vendor": "H3C",
        "platform": "h3c_comware",
        "version": "Comware 7",
        "description": "分别查看 ARP 解析和 MAC 学习表，并结合 VLAN、接口和网关角色定位问题；这是只读诊断条目。",
        "content": """display arp
display arp all
display mac-address
display mac-address vlan {{ vlan_id | default(10) }}
display mac-address interface {{ interface_name | default(\"GigabitEthernet 1/0/1\") }}
display interface brief""",
        "rollback": "",
        "reference": "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Security/00-Public/Reference_Guides/Command_References/H3C_IPS_Comware_7_CR%28R8560_R8660%29/10/202205/1607637_294551_0.htm",
    },
)


def _upsert_template(cursor, item: dict[str, str]) -> None:
    now = _now()
    values = (
        item["name"], "cli", item["category"], item["vendor"], item["content"],
        item["rollback"], item["description"], item["platform"], item["version"],
        item["reference"], "official_reference_reviewed", "official", "low",
        "published", "1.0", now, now,
    )
    existing = cursor.execute("SELECT id FROM templates WHERE id = ?", (item["id"],)).fetchone()
    if existing:
        cursor.execute(
            """
            UPDATE templates
            SET name = ?, type = ?, category = ?, vendor = ?, content = ?, rollback = ?,
                description = ?, platform_family = ?, software_version = ?,
                official_reference = ?, validation_status = ?, source_type = ?,
                risk_level = ?, status = ?, current_version = ?, is_official = 1,
                updated_at = ?
            WHERE id = ?
            """,
            (*values[:15], values[16], item["id"]),
        )
        return
    cursor.execute(
        """
        INSERT INTO templates
        (id, name, type, category, vendor, content, rollback, last_used,
         description, platform_family, software_version, official_reference,
         validation_status, source_type, risk_level, status, current_version,
         is_official, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'system', ?, ?)
        """,
        (item["id"], *values),
    )


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    _ensure_columns(cursor)
    for item in _TEMPLATES:
        _upsert_template(cursor, item)


__all__ = ["VERSION", "NAME", "upgrade"]
