"""Add the source-backed Cisco switchport interface template.

The Cisco interface guide describes Layer 2 switchports as either access or
trunk ports.  Keeping that scope in one official template gives the
``interface switchport`` anchor a precise document identity while retaining
the access/trunk feature scope in the evaluation dataset.
"""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 208
NAME = "official_cisco_interface_switchport_template"


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


_TEMPLATE = {
    "id": "official-cisco-interface-switchport-basic",
    "name": "接口 switchport 配置范围（Cisco IOS XE）",
    "category": "switching",
    "vendor": "Cisco",
    "platform": "cisco_iosxe",
    "version": "IOS XE 17.x",
    "description": "配置 Cisco 二层 switchport 的 access 或 trunk 模式，并核对接口实际状态；接口、VLAN 和版本能力必须按官方指南复核。",
    "content": """configure terminal
interface {{ interface_name | default(\"GigabitEthernet1/0/1\") }}
 switchport
 switchport mode {{ mode | default(\"access\") }}
 switchport access vlan {{ access_vlan | default(10) }}
 switchport trunk allowed vlan {{ allowed_vlans | default(\"10,20\") }}
end

show interfaces {{ interface_name | default(\"GigabitEthernet1/0/1\") }} switchport
show interfaces status""",
    "rollback": """configure terminal
interface {{ interface_name | default(\"GigabitEthernet1/0/1\") }}
 no switchport access vlan
 no switchport trunk allowed vlan
 switchport mode access
end""",
    "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/infra/interface-characteristics/interface-characteristics-configuration-guide.html",
}


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
    _upsert_template(cursor, _TEMPLATE)


__all__ = ["VERSION", "NAME", "upgrade"]
