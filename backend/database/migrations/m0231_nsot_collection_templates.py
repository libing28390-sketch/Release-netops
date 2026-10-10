"""Persist operator-managed NSOT collection template definitions."""

from __future__ import annotations

import json
from datetime import datetime, timezone


VERSION = 231
NAME = "nsot_collection_templates"


_BUILTINS = (
    {
        "id": "role_default",
        "name_zh": "按角色默认",
        "name_en": "Role default",
        "description_zh": "按设备角色、SVI 事实和设备级覆盖动态决定。",
        "description_en": "Resolved dynamically from device role, SVI facts, and device overrides.",
        "collector_keys": [],
    },
    {
        "id": "basic",
        "name_zh": "基础监控",
        "name_en": "Basic monitoring",
        "description_zh": "基础接口状态和接口 IP 事实。",
        "description_en": "Basic interface status and interface IP facts.",
        "collector_keys": ["interface_status", "interface_ip"],
    },
    {
        "id": "layer2_switch",
        "name_zh": "二层交换机",
        "name_en": "Layer 2 switch",
        "description_zh": "接口与拓扑、MAC/VLAN 和终端定位事实。",
        "description_en": "Interfaces, topology, MAC/VLAN, and endpoint facts.",
        "collector_keys": ["interface_status", "interface_ip", "lldp", "mac_table", "vlan"],
    },
    {
        "id": "layer3_gateway",
        "name_zh": "三层/网关设备",
        "name_en": "Layer 3 / gateway",
        "description_zh": "接口、LLDP、ARP 与路由事实。",
        "description_en": "Interfaces, LLDP, ARP, and routing facts.",
        "collector_keys": ["interface_status", "interface_ip", "lldp", "arp", "routes"],
    },
    {
        "id": "firewall",
        "name_zh": "防火墙",
        "name_en": "Firewall",
        "description_zh": "基础接口、LLDP、ARP 与适用的路由事实。",
        "description_en": "Basic interfaces, LLDP, ARP, and applicable routing facts.",
        "collector_keys": ["interface_status", "interface_ip", "lldp", "arp", "routes"],
    },
    {
        "id": "wireless",
        "name_zh": "无线设备",
        "name_en": "Wireless device",
        "description_zh": "基础接口与 LLDP 事实。",
        "description_en": "Basic interfaces and LLDP facts.",
        "collector_keys": ["interface_status", "interface_ip", "lldp"],
    },
    {
        "id": "custom",
        "name_zh": "自定义",
        "name_en": "Custom",
        "description_zh": "以角色默认值为起点，并应用设备单项覆盖。",
        "description_en": "Starts from role defaults and applies device-level overrides.",
        "collector_keys": [],
    },
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS nsot_collection_templates (
            id TEXT PRIMARY KEY,
            name_zh TEXT NOT NULL,
            name_en TEXT NOT NULL,
            description_zh TEXT NOT NULL DEFAULT '',
            description_en TEXT NOT NULL DEFAULT '',
            collector_keys TEXT NOT NULL DEFAULT '[]',
            builtin INTEGER NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_nsot_collection_templates_builtin
        ON nsot_collection_templates (builtin, updated_at)
        """
    )
    now = _now()
    for item in _BUILTINS:
        cursor.execute(
            """
            INSERT INTO nsot_collection_templates
              (id, name_zh, name_en, description_zh, description_en,
               collector_keys, builtin, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, 'system', ?, ?)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                item["id"],
                item["name_zh"],
                item["name_en"],
                item["description_zh"],
                item["description_en"],
                json.dumps(item["collector_keys"], ensure_ascii=False),
                now,
                now,
            ),
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute("DROP TABLE IF EXISTS nsot_collection_templates")
