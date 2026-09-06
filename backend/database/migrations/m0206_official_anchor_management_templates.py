"""Add official-source templates for management and fast-detection anchors.

These rows close three semantic gaps that were previously represented by
broader or unrelated templates: Huawei OSPF/BFD, Huawei ``super password``,
and Cisco IOS-XE AAA login authentication. The bodies are concise,
source-backed command summaries; they are not copied vendor manuals.
"""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 206
NAME = "official_anchor_management_templates"


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
        "id": "official-huawei-ospf-bfd-basic",
        "name": "OSPF 联动 BFD 配置与核验（华为 VRP）",
        "category": "routing",
        "vendor": "Huawei",
        "platform": "huawei_vrp",
        "version": "VRP 8 / V200R023-V300R024",
        "description": "OSPF 与 BFD 联动的配置骨架和会话核验命令；进程、接口、定时器与版本支持必须按官方指南复核。",
        "content": """system-view
bfd
ospf {{ process_id | default(1) }}
 bfd all-interfaces enable
quit
return

display ospf {{ process_id | default(1) }} bfd session all
display ospf peer
display bfd session all""",
        "rollback": """system-view
ospf {{ process_id | default(1) }}
 undo bfd all-interfaces enable
quit
return""",
        "reference": "https://info.support.huawei.com/hedex/api/pages/EDOC1100149311/AZJ0713J/18/resources/admin/sec_admin_router_ospf_0065.html",
    },
    {
        "id": "official-huawei-super-password-basic",
        "name": "super password 权限级别（华为 VRP）",
        "category": "security",
        "vendor": "Huawei",
        "platform": "huawei_vrp",
        "version": "VRP 8 / V200R023-V300R024",
        "description": "设置 VRP super password 权限级别的命令结构；认证值只使用脱敏占位符，权限和变更流程须由授权管理员确认。",
        "content": """system-view
super password level {{ privilege_level | default(3) }} cipher <REDACTED>
return

display current-configuration | include super
display users""",
        "rollback": """system-view
undo super password
return""",
        "reference": "https://info.support.huawei.com/hedex/api/pages/EDOC1100149308/AEJ0713J/18/resources/cli_vrp/super_password_pesudo.html",
    },
    {
        "id": "official-cisco-aaa-authentication-basic",
        "name": "AAA 登录认证与本地回退（Cisco IOS-XE）",
        "category": "security",
        "vendor": "Cisco",
        "platform": "cisco_iosxe",
        "version": "IOS XE 17.x",
        "description": "AAA 登录认证方法列表与 TACACS+ 到本地回退的配置骨架；服务器组、VTY 应用和授权策略必须按目标设备核对。",
        "content": """configure terminal
aaa new-model
aaa authentication login default group tacacs+ local
aaa authorization exec default local
end

show running-config | include aaa
show aaa servers""",
        "rollback": """configure terminal
no aaa authorization exec default local
no aaa authentication login default group tacacs+ local
no aaa new-model
end""",
        "reference": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/sec/b_1713_sec_9300_cg/configuring_authentication.html",
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
