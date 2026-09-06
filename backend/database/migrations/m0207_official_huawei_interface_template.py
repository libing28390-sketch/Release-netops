"""Add the source-backed Huawei CE6885 interface-status template.

``ANCHOR-003`` asks for interface state and uplink configuration.  The
existing access and trunk templates cover the configuration branches, but a
separate read-only interface-status identity is needed so the Gold set does
not silently treat an operational query as a configuration-only hit.
"""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 207
NAME = "official_huawei_interface_status_template"


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
    "id": "official-huawei-ce6885-interface-status-diagnostic",
    "name": "接口状态与上联核验（华为 CE6885）",
    "category": "operations",
    "vendor": "Huawei",
    "platform": "huawei_vrp",
    "version": "VRP 8 / V200R023-V300R024",
    "description": "读取 CE6885 接口摘要、指定上联接口和 IP 接口状态；型号、板卡接口名称和 VRP 版本必须按官方命令参考复核。",
    "content": """display interface brief
display interface {{ interface_name | default(\"GigabitEthernet 0/1/1\") }}
display ip interface brief

display interface brief
display interface {{ interface_name | default(\"GigabitEthernet 0/1/1\") }}""",
    "rollback": "",
    "reference": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100333403/cdd85713/basic-interface-configuration-commands",
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
