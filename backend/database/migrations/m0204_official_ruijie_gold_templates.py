"""Seed source-backed Ruijie RGOS templates used by the 50-anchor corpus.

The six entries in this migration are intentionally narrow.  They correspond
to the six Ruijie Gold IDs already present in the frozen anchor set, carry an
official Ruijie source URL, and are projected into the searchable corpus with
explicit feature/category metadata.  They are not a license to apply the
commands blindly: the source pages and target model/version still need to be
checked before a production change.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone


VERSION = 204
NAME = "official_ruijie_gold_templates"


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
        "id": "ruijie-rgos-vlan-access",
        "name": "VLAN 与 Access 端口（锐捷 RGOS）",
        "category": "switching",
        "vendor": "Ruijie",
        "platform": "ruijie_rgos",
        "version": "RGOS 10.x/11.x",
        "description": "创建业务 VLAN 并将交换机端口配置为 Access；精确命令须按 RG-S6220/目标 RGOS 版本复核。",
        "content": """enable
configure terminal
vlan {{ vlan_id | default(10) }}
 name {{ vlan_name | default(\"USERS\") }}
exit
interface {{ interface_name | default(\"GigabitEthernet 0/1\") }}
 switchport mode access
 switchport access vlan {{ vlan_id | default(10) }}
exit
end

show vlan
show interfaces status""",
        "rollback": """configure terminal
interface {{ interface_name | default(\"GigabitEthernet 0/1\") }}
 no switchport access vlan
exit
no vlan {{ vlan_id | default(10) }}
end""",
        "reference": "https://www.ruijie.com.cn/fw/wt/35635/",
    },
    {
        "id": "ruijie-rgos-aggregateport",
        "name": "AggregatePort/LACP 链路聚合（锐捷 RGOS）",
        "category": "switching",
        "vendor": "Ruijie",
        "platform": "ruijie_rgos",
        "version": "RGOS 10.x/11.x",
        "description": "使用 AggregatePort 和 active 模式建立链路聚合；成员口、聚合模式和型号能力须先复核。",
        "content": """enable
configure terminal
interface range {{ member_interfaces | default(\"GigabitEthernet 0/1-2\") }}
 port-group {{ aggregate_id | default(1) }} mode active
exit
interface aggregateport {{ aggregate_id | default(1) }}
 description {{ aggregate_description | default(\"UPLINK_LAG\") }}
exit
end

show aggregateport {{ aggregate_id | default(1) }} summary
show interface aggregateport {{ aggregate_id | default(1) }}""",
        "rollback": """configure terminal
interface aggregateport {{ aggregate_id | default(1) }}
 no description
exit
interface range {{ member_interfaces | default(\"GigabitEthernet 0/1-2\") }}
 no port-group {{ aggregate_id | default(1) }}
exit
end""",
        "reference": "https://www.ruijie.com.cn/fw/wt/90880/",
    },
    {
        "id": "ruijie-rgos-show-route",
        "name": "IPv4 路由表查看（锐捷 RGOS）",
        "category": "routing",
        "vendor": "Ruijie",
        "platform": "ruijie_rgos",
        "version": "RGOS 10.x/11.x",
        "description": "查看 RGOS IPv4 路由表并区分静态、OSPF 等来源；这是只读核验条目。",
        "content": """show ip route
show ip route static
show ip route ospf""",
        "rollback": "",
        "reference": "https://www.ruijie.com.cn/fw/wt/37267/",
    },
    {
        "id": "ruijie-rgos-ospf",
        "name": "OSPF 基础配置与邻居核验（锐捷 RGOS）",
        "category": "routing",
        "vendor": "Ruijie",
        "platform": "ruijie_rgos",
        "version": "RGOS 10.x/11.x",
        "description": "配置 OSPF 进程和 network 宣告并查看邻居；进程、区域和接口参数须按型号复核。",
        "content": """enable
configure terminal
router ospf {{ process_id | default(1) }}
 network {{ network | default(\"192.0.2.0\") }} {{ wildcard | default(\"0.0.0.255\") }} area {{ area | default(0) }}
exit
end

show ip ospf neighbor
show ip route ospf""",
        "rollback": """configure terminal
no router ospf {{ process_id | default(1) }}
end""",
        "reference": "https://www.ruijie.com.cn/fw/wt/32518/",
    },
    {
        "id": "ruijie-rgos-show-lldp",
        "name": "LLDP 邻居信息查看（锐捷 RGOS）",
        "category": "switching",
        "vendor": "Ruijie",
        "platform": "ruijie_rgos",
        "version": "RGOS 10.x/11.x",
        "description": "查看 LLDP 状态和邻居信息；show 命令的详细参数须按目标 RGOS 型号命令参考复核。",
        "content": """show lldp
show lldp neighbor
show lldp neighbor interface {{ interface_name | default(\"GigabitEthernet 0/1\") }} detail
show lldp status""",
        "rollback": "",
        "reference": "https://www.ruijie.com.cn/fw/wt/18543/",
    },
    {
        "id": "ruijie-rgos-acl",
        "name": "Standard IPv4 ACL（锐捷 RGOS）",
        "category": "security",
        "vendor": "Ruijie",
        "platform": "ruijie_rgos",
        "version": "RGOS 10.x/11.x",
        "description": "创建并查看 IPv4 standard access-list；应用到接口前必须核对方向和业务影响。",
        "content": """enable
configure terminal
ip access-list standard {{ acl_number | default(1) }}
 {{ sequence | default(1) }} permit {{ source | default(\"any\") }}
exit
end

show access-lists {{ acl_number | default(1) }}
show ip access-group""",
        "rollback": """configure terminal
no ip access-list standard {{ acl_number | default(1) }}
end""",
        "reference": "https://www.ruijie.com.cn/fw/wt/37269/",
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


def _upsert_compatibility(cursor, item: dict[str, str]) -> None:
    model_pattern = r"^(?:RG-(?:S|CS|NBS)|RG-R|RSR|RG-EG)"
    cursor.execute(
        """
        DELETE FROM config_template_compatibility
        WHERE template_id = ? AND vendor = ? AND platform = ? AND model_pattern = ?
        """,
        (item["id"], item["vendor"], item["platform"], model_pattern),
    )
    cursor.execute(
        """
        INSERT INTO config_template_compatibility
        (id, template_id, vendor, platform, model_pattern, min_version, max_version,
         required_capabilities_json, excluded_versions_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "compat-{}-{}".format(
                item["id"], hashlib.sha1(model_pattern.encode("utf-8")).hexdigest()[:10]
            ),
            item["id"], item["vendor"], item["platform"], model_pattern,
            "", "", '["cli"]', "[]",
        ),
    )


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    _ensure_columns(cursor)
    for item in _TEMPLATES:
        _upsert_template(cursor, item)
        _upsert_compatibility(cursor, item)


__all__ = ["VERSION", "NAME", "upgrade"]
