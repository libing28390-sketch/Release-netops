"""Seed the reviewed Cisco IOS XE HSRP configuration starter.

HSRP is a distinct first-hop redundancy protocol from VRRP.  Keeping a
separate reviewed template and feature label prevents an HSRP request from
being satisfied by a VRRP document merely because both are gateway-redundancy
features.
"""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 203
NAME = "official_cisco_hsrp_template"


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


_TEMPLATE = {
    "id": "official-cisco-hsrp-basic",
    "name": "HSRP 网关冗余（Cisco IOS XE）",
    "category": "reliability",
    "vendor": "Cisco",
    "platform": "cisco_iosxe",
    "version": "IOS XE 17.x",
    "description": "在 SVI 上配置 HSRP 虚拟网关、优先级和抢占延时；目标设备与 IOS XE 版本须先核对。",
    "content": """enable
configure terminal
interface Vlan{{ vlan_id | default(10) }}
 ip address {{ gateway_ip | default(\"192.0.2.2\") }} {{ netmask | default(\"255.255.255.0\") }}
 standby {{ hsrp_group | default(1) }} priority {{ priority | default(110) }}
 standby {{ hsrp_group | default(1) }} preempt delay minimum {{ preempt_delay | default(30) }}
 standby {{ hsrp_group | default(1) }} ip {{ virtual_ip | default(\"192.0.2.1\") }}
 no shutdown
end

show standby brief""",
    "rollback": """configure terminal
interface Vlan{{ vlan_id | default(10) }}
 no standby {{ hsrp_group | default(1) }} ip {{ virtual_ip | default(\"192.0.2.1\") }}
 no standby {{ hsrp_group | default(1) }} preempt
 no standby {{ hsrp_group | default(1) }} priority
 no ip address
 no shutdown
end""",
    "reference": "https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ntw-servs/b-network-services/m_fhp-hsrp-0.html",
}


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    _ensure_columns(cursor)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    item = _TEMPLATE
    values = (
        item["name"], "cli", item["category"], item["vendor"], item["content"],
        item["rollback"], item["description"], item["platform"], item["version"],
        item["reference"], "official_reference_reviewed", "official", "low",
        "published", "1.0", now, now,
    )
    existing = cursor.execute(
        "SELECT id FROM templates WHERE id = ? LIMIT 1", (item["id"],)
    ).fetchone()
    if existing:
        cursor.execute(
            """
            UPDATE templates
            SET name = ?, type = ?, category = ?, vendor = ?, content = ?, rollback = ?,
                description = ?, platform_family = ?, software_version = ?,
                official_reference = ?, validation_status = ?, source_type = ?,
                risk_level = ?, status = ?, current_version = ?,
                is_official = 1, updated_at = ?
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


__all__ = ["VERSION", "NAME", "upgrade"]
