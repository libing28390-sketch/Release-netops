"""Add official OSPF seed templates for campus and data-center switches."""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 158
NAME = "official_switch_routing_templates"


def _columns(cursor, use_pg: bool) -> set[str]:
    cursor.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'templates'
        """
    )
    return {str(row[0]) for row in cursor.fetchall()}



def _ensure_columns(cursor, use_pg: bool) -> None:
    definitions = {
        "description": "TEXT DEFAULT ''",
        "platform_family": "TEXT DEFAULT ''",
        "software_version": "TEXT DEFAULT ''",
        "official_reference": "TEXT DEFAULT ''",
        "validation_status": "TEXT DEFAULT 'draft'",
        "source_type": "TEXT DEFAULT 'custom'",
        "risk_level": "TEXT DEFAULT 'low'",
        "status": "TEXT DEFAULT 'draft'",
        "current_version": "TEXT DEFAULT '1.0'",
        "is_official": "INTEGER DEFAULT 0",
        "created_by": "TEXT DEFAULT ''",
        "created_at": "TEXT DEFAULT ''",
        "updated_at": "TEXT DEFAULT ''",
    }
    existing = _columns(cursor, use_pg)
    for column, definition in definitions.items():
        if column not in existing:
            cursor.execute(f"ALTER TABLE templates ADD COLUMN {column} {definition}")


_TEMPLATES = (
    {
        "id": "official-huawei-s5700-ospf-basic",
        "name": "华为 S5700/S6700 OSPF 基础配置（VRP）",
        "vendor": "Huawei",
        "platform": "huawei_vrp",
        "version": "V200R023/V200R024",
        "description": "适用于华为 S5700/S6700 园区交换机 VRP 的单区域 OSPF 基础配置，包含 Router ID、区域与网段发布。",
        "content": """system-view
sysname {{ hostname | default(\"S5700\") }}
ospf {{ process_id | default(1) }} router-id {{ router_id | default(\"192.0.2.1\") }}
 area 0.0.0.0
  network {{ network | default(\"192.0.2.0\") }} {{ wildcard | default(\"0.0.0.255\") }}
quit
return

display ospf peer brief""",
        "rollback": """system-view
undo ospf {{ process_id | default(1) }}
return""",
        "reference": "https://support.huawei.com/enterprise/en/doc/EDOC1100459443/d770f3cd/configuring-ospf-attributes-on-different-types-of-networks",
    },
    {
        "id": "official-h3c-comware-ospf-basic",
        "name": "H3C Comware 7 园区/数据中心 OSPF 基础配置",
        "vendor": "H3C",
        "platform": "h3c_comware",
        "version": "Comware 7",
        "description": "适用于 H3C S5130、S6520X、S6800、S9825/S9855 等 Comware 7 交换机的 OSPF 基础配置。",
        "content": """system-view
sysname {{ hostname | default(\"H3C-SW\") }}
router id {{ router_id | default(\"192.0.2.2\") }}
ospf {{ process_id | default(1) }}
 area 0.0.0.0
  network {{ network | default(\"192.0.2.0\") }} {{ wildcard | default(\"0.0.0.255\") }}
quit
return

display ospf peer brief""",
        "rollback": """system-view
undo ospf {{ process_id | default(1) }}
undo router id
return""",
        "reference": "https://www.h3c.com/en/d_201903/1159013_294551_0.htm",
    },
    {
        "id": "official-cisco-c9300-ospf-basic",
        "name": "Cisco Catalyst 9300 IOS XE OSPF 基础配置",
        "vendor": "Cisco",
        "platform": "cisco_iosxe",
        "version": "IOS XE 17.13",
        "description": "适用于 Cisco Catalyst 9300 园区交换机 IOS XE 的单区域 OSPF 基础配置与邻居验证。",
        "content": """enable
configure terminal
router ospf {{ process_id | default(1) }}
 router-id {{ router_id | default(\"192.0.2.3\") }}
 network {{ network | default(\"192.0.2.0\") }} {{ wildcard | default(\"0.0.0.255\") }} area 0
 passive-interface default
 no passive-interface {{ uplink_interface | default(\"GigabitEthernet1/0/48\") }}
end

show ip ospf neighbor""",
        "rollback": """configure terminal
no router ospf {{ process_id | default(1) }}
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/rtng/b_1713_rtng_9300_cg/configuring_ospf.html",
    },
    {
        "id": "official-cisco-nexus-ospf-basic",
        "name": "Cisco Nexus 3000/9000 NX-OS OSPF 基础配置",
        "vendor": "Cisco",
        "platform": "cisco_nxos",
        "version": "NX-OS 9.x/10.x",
        "description": "适用于 Cisco Nexus 3000/9000 数据中心交换机 NX-OS 的 OSPF 基础配置与接口启用。",
        "content": """configure terminal
feature ospf
router ospf {{ process_id | default(1) }}
 router-id {{ router_id | default(\"192.0.2.4\") }}
interface {{ interface_name | default(\"Ethernet1/1\") }}
 ip router ospf {{ process_id | default(1) }} area 0.0.0.0
exit
copy running-config startup-config

show ip ospf neighbors""",
        "rollback": """configure terminal
interface {{ interface_name | default(\"Ethernet1/1\") }}
 no ip router ospf {{ process_id | default(1) }} area 0.0.0.0
exit
no feature ospf""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus3000/sw/unicast/602_u1_1/l3_nx-os/l3_ospf.html",
    },
)


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_columns(cursor, use_pg)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for item in _TEMPLATES:
        existing = cursor.execute("SELECT id FROM templates WHERE id = ?", (item["id"],)).fetchone()
        values = (
            item["name"], "cli", "routing", item["vendor"], item["content"], item["rollback"],
            item["description"], item["platform"], item["version"], item["reference"],
            "official_reference_reviewed", "official", "low", "published", "1.0", 1,
            "system", now, now,
        )
        if existing:
            cursor.execute(
                """
                UPDATE templates
                SET name = ?, type = ?, category = ?, vendor = ?, content = ?, rollback = ?,
                    description = ?, platform_family = ?, software_version = ?, official_reference = ?,
                    validation_status = ?, source_type = ?, risk_level = ?, status = ?,
                    current_version = ?, is_official = ?, created_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (*values[:17], values[18], item["id"]),
            )
        else:
            cursor.execute(
                """
                INSERT INTO templates (
                    id, name, type, category, vendor, content, rollback, last_used,
                    description, platform_family, software_version, official_reference,
                    validation_status, source_type, risk_level, status, current_version,
                    is_official, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item["id"], *values),
            )


__all__ = ["VERSION", "NAME", "upgrade"]
