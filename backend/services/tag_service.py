"""Unified metadata/tag service.

Tags are first-class metadata objects.  A tag has a stable ``code`` and can
be assigned to any supported resource through ``tag_assignments``.  Device
helpers remain as a small convenience API for the existing asset screens.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

TAG_CATEGORIES = (
    {"code": "business", "label": "Business", "label_zh": "业务属性", "description": "业务用途和归属", "exclusive": 0, "sort_order": 10},
    {"code": "environment", "label": "Environment", "label_zh": "环境", "description": "开发、测试、生产等环境", "exclusive": 1, "sort_order": 20},
    {"code": "network_zone", "label": "Network Zone", "label_zh": "网络区域", "description": "核心区、DMZ、管理区等网络区域", "exclusive": 0, "sort_order": 30},
    {"code": "operations", "label": "Operations", "label_zh": "运维属性", "description": "巡检、备份、变更和维护策略", "exclusive": 0, "sort_order": 40},
    {"code": "security", "label": "Security", "label_zh": "安全属性", "description": "安全等级、合规和自动化保护", "exclusive": 0, "sort_order": 50},
    {"code": "project", "label": "Project", "label_zh": "项目", "description": "项目和交付批次", "exclusive": 0, "sort_order": 60},
    {"code": "lifecycle", "label": "Lifecycle", "label_zh": "生命周期", "description": "规划、上线、维护和退役", "exclusive": 1, "sort_order": 70},
    {"code": "system_auto", "label": "System Auto", "label_zh": "系统自动", "description": "系统状态和系统派生标签", "exclusive": 0, "sort_order": 90, "is_system": 1},
    {"code": "technology", "label": "Technology", "label_zh": "技术平台", "description": "设备厂商与操作系统平台属性", "exclusive": 0, "sort_order": 80},
)

BUILTIN_TAGS = [
    {"category": "technology", "code": "vendor.cisco", "label": "Cisco", "label_zh": "思科", "color": "#2563eb", "exclusive_group": "technology.vendor", "sort_order": 1},
    {"category": "technology", "code": "vendor.huawei", "label": "Huawei", "label_zh": "华为", "color": "#dc2626", "exclusive_group": "technology.vendor", "sort_order": 2},
    {"category": "technology", "code": "vendor.h3c", "label": "H3C", "label_zh": "华三", "color": "#ea580c", "exclusive_group": "technology.vendor", "sort_order": 3},
    {"category": "technology", "code": "vendor.arista", "label": "Arista", "label_zh": "Arista", "color": "#7c3aed", "exclusive_group": "technology.vendor", "sort_order": 4},
    {"category": "technology", "code": "vendor.juniper", "label": "Juniper", "label_zh": "瞻博", "color": "#059669", "exclusive_group": "technology.vendor", "sort_order": 5},
    {"category": "technology", "code": "vendor.ruijie", "label": "Ruijie", "label_zh": "锐捷", "color": "#0891b2", "exclusive_group": "technology.vendor", "sort_order": 6},
    {"category": "technology", "code": "vendor.fortinet", "label": "Fortinet", "label_zh": "飞塔", "color": "#f97316", "exclusive_group": "technology.vendor", "sort_order": 7},
    {"category": "technology", "code": "vendor.paloalto", "label": "Palo Alto", "label_zh": "帕洛阿尔托", "color": "#0f766e", "exclusive_group": "technology.vendor", "sort_order": 8},
    {"category": "technology", "code": "vendor.zte", "label": "ZTE", "label_zh": "中兴", "color": "#4f46e5", "exclusive_group": "technology.vendor", "sort_order": 9},
    {"category": "technology", "code": "vendor.maipu", "label": "Maipu", "label_zh": "迈普", "color": "#64748b", "exclusive_group": "technology.vendor", "sort_order": 10},
    {"category": "technology", "code": "vendor.dptech", "label": "DPTech", "label_zh": "迪普", "color": "#06b6d4", "exclusive_group": "technology.vendor", "sort_order": 11},
    {"category": "technology", "code": "vendor.dell", "label": "Dell", "label_zh": "戴尔", "color": "#0284c7", "exclusive_group": "technology.vendor", "sort_order": 12},
    {"category": "technology", "code": "vendor.hp", "label": "HP", "label_zh": "惠普", "color": "#0369a1", "exclusive_group": "technology.vendor", "sort_order": 13},
    {"category": "technology", "code": "vendor.lenovo", "label": "Lenovo", "label_zh": "联想", "color": "#e11d48", "exclusive_group": "technology.vendor", "sort_order": 14},
    {"category": "technology", "code": "vendor.inspur", "label": "Inspur", "label_zh": "浪潮", "color": "#2563eb", "exclusive_group": "technology.vendor", "sort_order": 15},
    {"category": "technology", "code": "vendor.dcn", "label": "DCN", "label_zh": "神州数码", "color": "#6366f1", "exclusive_group": "technology.vendor", "sort_order": 16},
    {"category": "technology", "code": "vendor.fiberhome", "label": "FiberHome", "label_zh": "烽火", "color": "#0d9488", "exclusive_group": "technology.vendor", "sort_order": 17},
    {"category": "technology", "code": "vendor.generic", "label": "Generic", "label_zh": "通用/白牌", "color": "#64748b", "exclusive_group": "technology.vendor", "sort_order": 18},
    {"category": "technology", "code": "platform.cisco_ios", "label": "Cisco IOS", "label_zh": "思科 IOS", "color": "#60a5fa", "exclusive_group": "technology.platform", "sort_order": 20},
    {"category": "technology", "code": "platform.cisco_nxos", "label": "Cisco NX-OS", "label_zh": "思科 NX-OS", "color": "#60a5fa", "exclusive_group": "technology.platform", "sort_order": 21},
    {"category": "technology", "code": "platform.cisco_xe", "label": "Cisco IOS-XE", "label_zh": "思科 IOS-XE", "color": "#60a5fa", "exclusive_group": "technology.platform", "sort_order": 22},
    {"category": "technology", "code": "platform.huawei_vrp", "label": "Huawei VRPv5", "label_zh": "华为 VRPv5", "color": "#f87171", "exclusive_group": "technology.platform", "sort_order": 23},
    {"category": "technology", "code": "platform.huawei_vrpv8", "label": "Huawei VRPv8", "label_zh": "华为 VRPv8", "color": "#f87171", "exclusive_group": "technology.platform", "sort_order": 24},
    {"category": "technology", "code": "platform.h3c_comware", "label": "H3C Comware", "label_zh": "华三 Comware", "color": "#fb923c", "exclusive_group": "technology.platform", "sort_order": 25},
    {"category": "technology", "code": "platform.arista_eos", "label": "Arista EOS", "label_zh": "Arista EOS", "color": "#a78bfa", "exclusive_group": "technology.platform", "sort_order": 28},
    {"category": "technology", "code": "platform.juniper_junos", "label": "Juniper JunOS", "label_zh": "瞻博 JunOS", "color": "#34d399", "exclusive_group": "technology.platform", "sort_order": 29},
    {"category": "technology", "code": "platform.ruijie_rgos", "label": "Ruijie RGOS", "label_zh": "锐捷 RGOS", "color": "#22d3ee", "exclusive_group": "technology.platform", "sort_order": 30},
    {"category": "technology", "code": "platform.fortinet", "label": "FortiOS", "label_zh": "FortiOS", "color": "#fb923c", "exclusive_group": "technology.platform", "sort_order": 31},
    {"category": "technology", "code": "platform.paloalto_panos", "label": "PAN-OS", "label_zh": "PAN-OS", "color": "#2dd4bf", "exclusive_group": "technology.platform", "sort_order": 32},
    {"category": "technology", "code": "platform.zte_zxros", "label": "ZTE ZXROS", "label_zh": "中兴 ZXROS", "color": "#818cf8", "exclusive_group": "technology.platform", "sort_order": 33},
    {"category": "technology", "code": "platform.maipu", "label": "Maipu Network OS", "label_zh": "迈普网络系统", "color": "#94a3b8", "exclusive_group": "technology.platform", "sort_order": 34},
    {"category": "technology", "code": "platform.dptech_conplat", "label": "DPTech Conplat (Switch)", "label_zh": "迪普 Conplat 交换机", "color": "#06b6d4", "exclusive_group": "technology.platform", "sort_order": 35},
    {"category": "technology", "code": "platform.dptech_conplat_fw", "label": "DPTech Conplat FW (Firewall)", "label_zh": "迪普 Conplat 防火墙", "color": "#0891b2", "exclusive_group": "technology.platform", "sort_order": 36},
    {"category": "technology", "code": "platform.linux", "label": "Linux", "label_zh": "Linux", "color": "#84cc16", "exclusive_group": "technology.platform", "sort_order": 40},
    {"category": "technology", "code": "platform.windows", "label": "Windows Server", "label_zh": "Windows Server", "color": "#38bdf8", "exclusive_group": "technology.platform", "sort_order": 41},
    {"category": "technology", "code": "platform.esxi", "label": "VMware ESXi", "label_zh": "VMware ESXi", "color": "#f59e0b", "exclusive_group": "technology.platform", "sort_order": 42},
    {"category": "technology", "code": "platform.ubuntu", "label": "Ubuntu", "label_zh": "Ubuntu", "color": "#ea580c", "exclusive_group": "technology.platform", "sort_order": 43},
    {"category": "technology", "code": "platform.centos", "label": "CentOS", "label_zh": "CentOS", "color": "#16a34a", "exclusive_group": "technology.platform", "sort_order": 44},
    {"category": "technology", "code": "platform.debian", "label": "Debian", "label_zh": "Debian", "color": "#d97706", "exclusive_group": "technology.platform", "sort_order": 45},
    {"category": "technology", "code": "platform.redhat", "label": "Red Hat (RHEL)", "label_zh": "红帽 RHEL", "color": "#dc2626", "exclusive_group": "technology.platform", "sort_order": 46},
    {"category": "environment", "code": "env.production", "label": "Production", "label_zh": "生产", "color": "#ef4444", "exclusive_group": "environment", "sort_order": 1},
    {"category": "environment", "code": "env.staging", "label": "Staging", "label_zh": "预发布", "color": "#f59e0b", "exclusive_group": "environment", "sort_order": 2},
    {"category": "environment", "code": "env.testing", "label": "Testing", "label_zh": "测试", "color": "#3b82f6", "exclusive_group": "environment", "sort_order": 3},
    {"category": "environment", "code": "env.development", "label": "Development", "label_zh": "开发", "color": "#8b5cf6", "exclusive_group": "environment", "sort_order": 4},
    {"category": "network_zone", "code": "zone.core", "label": "Core Zone", "label_zh": "核心区", "color": "#dc2626", "sort_order": 1},
    {"category": "network_zone", "code": "zone.aggregation", "label": "Aggregation Zone", "label_zh": "汇聚区", "color": "#ea580c", "sort_order": 2},
    {"category": "network_zone", "code": "zone.access", "label": "Access Zone", "label_zh": "接入区", "color": "#0891b2", "sort_order": 3},
    {"category": "network_zone", "code": "zone.dmz", "label": "DMZ", "label_zh": "DMZ", "color": "#7c3aed", "sort_order": 4},
    {"category": "network_zone", "code": "zone.management", "label": "Management Zone", "label_zh": "管理区", "color": "#475569", "sort_order": 5},
    {"category": "operations", "code": "ops.change-freeze", "label": "Change Freeze", "label_zh": "变更冻结", "color": "#be123c", "sort_order": 1},
    {"category": "operations", "code": "ops.priority-inspection", "label": "Priority Inspection", "label_zh": "重点巡检", "color": "#0e7490", "sort_order": 2},
    {"category": "operations", "code": "ops.backup-exception", "label": "Backup Exception", "label_zh": "备份例外", "color": "#64748b", "sort_order": 3},
    {"category": "security", "code": "security.high-sensitivity", "label": "High Sensitivity", "label_zh": "高敏感", "color": "#b91c1c", "sort_order": 1},
    {"category": "security", "code": "security.no-auto-change", "label": "No Automatic Change", "label_zh": "禁止自动变更", "color": "#991b1b", "sort_order": 2},
    {"category": "security", "code": "security.compliance", "label": "Compliance Scope", "label_zh": "合规范围", "color": "#7e22ce", "sort_order": 3},
    {"category": "lifecycle", "code": "lifecycle.planned", "label": "Planned", "label_zh": "规划中", "color": "#64748b", "exclusive_group": "lifecycle", "sort_order": 1},
    {"category": "lifecycle", "code": "lifecycle.in-service", "label": "In Service", "label_zh": "在用", "color": "#16a34a", "exclusive_group": "lifecycle", "sort_order": 2},
    {"category": "lifecycle", "code": "lifecycle.maintenance", "label": "Maintenance", "label_zh": "维护中", "color": "#d97706", "exclusive_group": "lifecycle", "sort_order": 3},
    {"category": "lifecycle", "code": "lifecycle.decommissioned", "label": "Decommissioned", "label_zh": "待下线", "color": "#64748b", "exclusive_group": "lifecycle", "sort_order": 4},
    {"category": "system_auto", "code": "system.status.online", "label": "Online", "label_zh": "在线", "color": "#10b981", "is_system": 1, "source_type": "system", "sort_order": 1},
    {"category": "system_auto", "code": "system.status.offline", "label": "Offline", "label_zh": "离线", "color": "#ef4444", "is_system": 1, "source_type": "system", "sort_order": 2},
]

_CODE_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_RESOURCE_TYPES = {"device", "site", "rack", "interface", "vlan", "vrf", "link"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_code(code: str) -> str:
    code = (code or "").strip().lower()
    if not code or len(code) > 96 or not _CODE_RE.fullmatch(code):
        raise ValueError("Tag code must match ^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$ and be <= 96 characters")
    return code


def _record_history(conn, resource_type: str, resource_id: str, tag_id: str, action: str,
                    source_type: str, operator: str = "", rule_id: str = "", reason: str = "") -> None:
    conn.execute(
        '''INSERT INTO tag_assignment_history
           (id, resource_type, resource_id, tag_id, action, source_type, rule_id, operator, reason, occurred_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), resource_type, resource_id, tag_id, action, source_type, rule_id, operator, reason, _now()),
    )


def _seed_categories(conn) -> None:
    for category in TAG_CATEGORIES:
        conn.execute(
            '''INSERT INTO tag_categories
               (code, label, label_zh, description, exclusive, sort_order, is_system, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT (code) DO UPDATE SET label=excluded.label, label_zh=excluded.label_zh,
                 description=excluded.description, exclusive=excluded.exclusive, sort_order=excluded.sort_order''',
            (category["code"], category["label"], category["label_zh"], category["description"],
             category.get("exclusive", 0), category["sort_order"], category.get("is_system", 0)),
        )


def seed_builtin_tags(conn) -> int:
    _seed_categories(conn)
    inserted = 0
    now = _now()
    for tag in BUILTIN_TAGS:
        try:
            cur = conn.execute(
                '''INSERT INTO tag_definitions
                   (id, category, code, label, label_zh, color, icon, description, resource_types,
                    exclusive_group, priority, source_type, is_system, is_active, sort_order, built_in, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 1, ?, 1, ?, ?)
                   ON CONFLICT (code) DO UPDATE SET label=excluded.label, label_zh=excluded.label_zh,
                     color=excluded.color, exclusive_group=excluded.exclusive_group, is_system=excluded.is_system,
                     source_type=excluded.source_type, is_active=1, updated_at=excluded.updated_at''',
                (f"builtin-{tag['code']}", tag["category"], tag["code"], tag["label"], tag.get("label_zh", ""),
                 tag.get("color", ""), tag.get("icon", ""), tag.get("description", ""), '["device"]',
                 tag.get("exclusive_group", ""), tag.get("source_type", "system" if tag.get("is_system") else "manual"),
                 tag.get("is_system", 0), tag.get("sort_order", 0), now, now),
            )
            if getattr(cur, "rowcount", 1) > 0:
                inserted += 1
        except Exception:
            logger.exception("Failed to seed tag %s", tag.get("code"))
            raise
    conn.commit()
    return inserted


def _ensure_status_tag_ids(conn) -> dict[str, str]:
    seed_builtin_tags(conn)
    rows = conn.execute(
        "SELECT id, code FROM tag_definitions WHERE code IN ('system.status.online', 'system.status.offline')"
    ).fetchall()
    return {str(row["code"]).rsplit(".", 1)[-1]: str(row["id"]) for row in rows}


def _system_status_value(device_status: str | None) -> str:
    return "online" if str(device_status or "").lower() == "online" else "offline"


def sync_device_status_tag(conn, device_id: str, device_status: str | None, created_by: str = "system") -> bool:
    tag_ids = _ensure_status_tag_ids(conn)
    target_id = tag_ids[_system_status_value(device_status)]
    current = conn.execute(
        '''SELECT ta.tag_id FROM tag_assignments ta JOIN tag_definitions td ON td.id = ta.tag_id
           WHERE ta.resource_type='device' AND ta.resource_id=? AND td.category='system_auto' AND td.is_system=1''',
        (device_id,),
    ).fetchall()
    current_ids = {str(row["tag_id"]) for row in current}
    if current_ids == {target_id}:
        return False
    conn.execute(
        '''DELETE FROM tag_assignments WHERE resource_type='device' AND resource_id=?
           AND tag_id IN (SELECT id FROM tag_definitions WHERE category='system_auto' AND is_system=1)''',
        (device_id,),
    )
    conn.execute(
        '''INSERT INTO tag_assignments
           (resource_type, resource_id, tag_id, source_type, created_at, created_by)
           VALUES ('device', ?, ?, 'system', ?, ?)''',
        (device_id, target_id, _now(), created_by),
    )
    _record_history(conn, "device", device_id, target_id, "replace", "system", created_by, reason="device status")
    return True


def sync_all_device_status_tags(conn) -> int:
    rows = conn.execute("SELECT id, status FROM devices").fetchall()
    changed = sum(sync_device_status_tag(conn, str(row["id"]), row["status"]) for row in rows)
    conn.commit()
    return changed


def list_tag_definitions(conn, category: str | None = None, include_inactive: bool = True) -> list[dict]:
    clauses, params = [], []
    if category:
        clauses.append("td.category = ?")
        params.append(category)
    if not include_inactive:
        clauses.append("td.is_active = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f'''SELECT td.*, tc.label AS category_label, tc.label_zh AS category_label_zh,
                   COALESCE((
                       SELECT COUNT(*)
                       FROM tag_assignments ta
                       WHERE ta.tag_id = td.id
                   ), 0) AS assignment_count
            FROM tag_definitions td LEFT JOIN tag_categories tc ON tc.code=td.category
            {where} ORDER BY td.category, td.sort_order, td.code''',
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def list_tag_categories(conn) -> list[dict]:
    return [dict(row) for row in conn.execute("SELECT * FROM tag_categories WHERE is_active=1 ORDER BY sort_order, code").fetchall()]


def get_tag_definition(conn, tag_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM tag_definitions WHERE id=?", (tag_id,)).fetchone()
    return dict(row) if row else None


def get_tag_definition_by_code(conn, code: str) -> dict | None:
    row = conn.execute("SELECT * FROM tag_definitions WHERE code=?", (_validate_code(code),)).fetchone()
    return dict(row) if row else None


def create_tag_definition(conn, category: str, code: str, label: str, **kwargs) -> dict:
    code = _validate_code(code)
    category_row = conn.execute("SELECT code FROM tag_categories WHERE code=? AND is_active=1", (category,)).fetchone()
    if not category_row or category == "system_auto":
        raise ValueError("Only active user-managed categories can create tags")
    now = _now()
    tag_id = f"tag-{uuid.uuid4()}"
    try:
        conn.execute(
            '''INSERT INTO tag_definitions
               (id, category, code, label, label_zh, color, icon, description, resource_types,
                exclusive_group, priority, source_type, is_system, is_active, sort_order, built_in, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', 0, 1, ?, 0, ?, ?)''',
            (tag_id, category, code, label.strip(), kwargs.get("label_zh", ""), kwargs.get("color", ""),
             kwargs.get("icon", ""), kwargs.get("description", ""), json.dumps(kwargs.get("resource_types", ["device"])),
             kwargs.get("exclusive_group", ""), int(kwargs.get("priority", 0)), int(kwargs.get("sort_order", 0)), now, now),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if "UNIQUE" in str(exc).upper():
            raise ValueError(f"Tag code '{code}' already exists") from exc
        raise
    return get_tag_definition(conn, tag_id) or {}


def update_tag_definition(conn, tag_id: str, **kwargs) -> dict | None:
    existing = get_tag_definition(conn, tag_id)
    if not existing:
        return None
    if existing["is_system"]:
        raise ValueError("System tags cannot be edited")
    allowed = ["label", "label_zh", "color", "icon", "description", "exclusive_group", "priority", "sort_order", "is_active"]
    sets, params = [], []
    for key in allowed:
        if key in kwargs:
            sets.append(f"{key}=?")
            params.append(kwargs[key])
    if not sets:
        return existing
    sets.append("updated_at=?")
    params.extend([_now(), tag_id])
    conn.execute(f"UPDATE tag_definitions SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    return get_tag_definition(conn, tag_id)


def delete_tag_definition(conn, tag_id: str) -> bool:
    existing = get_tag_definition(conn, tag_id)
    if not existing:
        return False
    if existing["is_system"]:
        raise ValueError("System tags cannot be deleted")
    usage = conn.execute("SELECT COUNT(*) FROM tag_assignments WHERE tag_id=?", (tag_id,)).fetchone()[0]
    if usage:
        raise ValueError("Tag is in use; deactivate it instead of deleting")
    conn.execute("DELETE FROM tag_assignment_history WHERE tag_id=?", (tag_id,))
    conn.execute("DELETE FROM tag_definitions WHERE id=?", (tag_id,))
    conn.commit()
    return True


def _load_assignable_tags(conn, tag_ids: list[str]) -> list[dict]:
    unique_ids = list(dict.fromkeys(tag_ids))
    if not unique_ids:
        return []
    marks = ",".join("?" for _ in unique_ids)
    rows = conn.execute(f"SELECT * FROM tag_definitions WHERE id IN ({marks})", unique_ids).fetchall()
    tags = [dict(row) for row in rows]
    if len(tags) != len(unique_ids):
        raise ValueError("One or more tags do not exist")
    if any(not tag["is_active"] for tag in tags):
        raise ValueError("Inactive tags cannot be assigned")
    if any(tag["is_system"] for tag in tags):
        raise ValueError("System tags are managed automatically")
    groups: dict[str, str] = {}
    for tag in tags:
        group = tag.get("exclusive_group") or ""
        if group and group in groups and groups[group] != tag["id"]:
            raise ValueError(f"Tags in exclusive group '{group}' cannot be assigned together")
        if group:
            groups[group] = tag["id"]
    return tags


def get_resource_tags(conn, resource_type: str, resource_id: str) -> list[dict]:
    rows = conn.execute(
        '''SELECT td.*, ta.source_type AS assignment_source, ta.rule_id, ta.inherited_from_type,
                  ta.inherited_from_id, ta.expires_at, ta.created_at AS assigned_at, ta.created_by
           FROM tag_assignments ta JOIN tag_definitions td ON td.id=ta.tag_id
           WHERE ta.resource_type=? AND ta.resource_id=? AND td.is_active=1
           ORDER BY td.category, td.sort_order, td.code''',
        (resource_type, resource_id),
    ).fetchall()
    return [dict(row) for row in rows]


def get_device_tags(conn, device_id: str) -> list[dict]:
    return get_resource_tags(conn, "device", device_id)


def set_resource_tags(conn, resource_type: str, resource_id: str, tag_ids: list[str], created_by: str = "") -> list[dict]:
    if resource_type not in _RESOURCE_TYPES:
        raise ValueError(f"Unsupported resource type: {resource_type}")
    tags = _load_assignable_tags(conn, tag_ids)
    existing = conn.execute(
        "SELECT tag_id FROM tag_assignments WHERE resource_type=? AND resource_id=? AND source_type='manual'",
        (resource_type, resource_id),
    ).fetchall()
    old_ids = {str(row["tag_id"]) for row in existing}
    conn.execute("DELETE FROM tag_assignments WHERE resource_type=? AND resource_id=? AND source_type='manual'", (resource_type, resource_id))
    for tag in tags:
        conn.execute(
            '''INSERT INTO tag_assignments
               (resource_type, resource_id, tag_id, source_type, created_at, created_by)
               VALUES (?, ?, ?, 'manual', ?, ?)''',
            (resource_type, resource_id, tag["id"], _now(), created_by),
        )
    for tag_id in old_ids - {tag["id"] for tag in tags}:
        _record_history(conn, resource_type, resource_id, tag_id, "remove", "manual", created_by)
    for tag in tags:
        _record_history(conn, resource_type, resource_id, tag["id"], "add" if tag["id"] not in old_ids else "replace", "manual", created_by)
    if resource_type == "device":
        row = conn.execute("SELECT status FROM devices WHERE id=?", (resource_id,)).fetchone()
        if row:
            sync_device_status_tag(conn, resource_id, row["status"], "system")
    conn.commit()
    return get_resource_tags(conn, resource_type, resource_id)


def set_device_tags(conn, device_id: str, tag_ids: list[str], created_by: str = "") -> list[dict]:
    if not conn.execute("SELECT 1 FROM devices WHERE id=?", (device_id,)).fetchone():
        raise ValueError("Device not found")
    return set_resource_tags(conn, "device", device_id, tag_ids, created_by)


def add_resource_tag(conn, resource_type: str, resource_id: str, tag_id: str, created_by: str = "") -> bool:
    tag = _load_assignable_tags(conn, [tag_id])[0]
    group = tag.get("exclusive_group") or ""
    if group:
        conflict = conn.execute(
            '''SELECT td.code FROM tag_assignments ta JOIN tag_definitions td ON td.id=ta.tag_id
               WHERE ta.resource_type=? AND ta.resource_id=? AND td.exclusive_group=? AND ta.tag_id<>?''',
            (resource_type, resource_id, group, tag_id),
        ).fetchone()
        if conflict:
            raise ValueError(f"Exclusive tag conflict with {conflict['code']}")
    try:
        conn.execute(
            '''INSERT INTO tag_assignments
               (resource_type, resource_id, tag_id, source_type, created_at, created_by)
               VALUES (?, ?, ?, 'manual', ?, ?)''',
            (resource_type, resource_id, tag_id, _now(), created_by),
        )
        _record_history(conn, resource_type, resource_id, tag_id, "add", "manual", created_by)
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        if "UNIQUE" in str(exc).upper():
            return False
        raise


def add_device_tag(conn, device_id: str, tag_id: str, created_by: str = "") -> bool:
    return add_resource_tag(conn, "device", device_id, tag_id, created_by)


def remove_resource_tag(conn, resource_type: str, resource_id: str, tag_id: str, created_by: str = "") -> bool:
    tag = get_tag_definition(conn, tag_id)
    if tag and tag["is_system"]:
        raise ValueError("System tags are managed automatically")
    cur = conn.execute("DELETE FROM tag_assignments WHERE resource_type=? AND resource_id=? AND tag_id=?", (resource_type, resource_id, tag_id))
    if cur.rowcount:
        _record_history(conn, resource_type, resource_id, tag_id, "remove", "manual", created_by)
        conn.commit()
        return True
    conn.commit()
    return False


def remove_device_tag(conn, device_id: str, tag_id: str) -> bool:
    return remove_resource_tag(conn, "device", device_id, tag_id)


def batch_set_device_tags(conn, device_ids: list[str], tag_ids: list[str], created_by: str = "") -> int:
    _load_assignable_tags(conn, tag_ids)
    count = 0
    for device_id in device_ids:
        for tag_id in tag_ids:
            if add_device_tag(conn, device_id, tag_id, created_by):
                count += 1
    return count


def resolve_device_ids_by_expression(conn, expression: dict | None) -> list[str]:
    """Resolve a recursively nested AND/OR/NOT tag expression."""
    if not isinstance(expression, dict):
        return []

    device_rows = conn.execute("SELECT id FROM devices").fetchall()
    device_ids = [str(row["id"]) for row in device_rows]
    assignments = conn.execute(
        "SELECT resource_id, tag_id FROM tag_assignments WHERE resource_type='device'"
    ).fetchall()
    tags_by_device: dict[str, set[str]] = {device_id: set() for device_id in device_ids}
    for row in assignments:
        resource_id = str(row["resource_id"])
        if resource_id in tags_by_device:
            tags_by_device[resource_id].add(str(row["tag_id"]))

    evaluated_nodes = 0

    def matches(group: object, device_tags: set[str], depth: int = 0) -> bool:
        nonlocal evaluated_nodes
        evaluated_nodes += 1
        if evaluated_nodes > 4096 or depth > 16 or not isinstance(group, dict):
            return False

        tag_ids = [
            str(tag_id).strip()
            for tag_id in (group.get("tag_ids") or [])
            if str(tag_id).strip()
        ]
        child_groups = group.get("groups") or []
        values = [tag_id in device_tags for tag_id in tag_ids]
        if isinstance(child_groups, list):
            values.extend(matches(child, device_tags, depth + 1) for child in child_groups)
        if not values:
            return False

        result = any(values) if str(group.get("operator") or "and").lower() == "or" else all(values)
        return not result if group.get("negated") is True else result

    result: list[str] = []
    for device_id in device_ids:
        evaluated_nodes = 0
        if matches(expression, tags_by_device[device_id]):
            result.append(device_id)
    return sorted(result)


def resolve_device_ids_by_condition_groups(
    conn,
    condition_groups: list[dict] | None = None,
    exclude_tag_ids: list[str] | None = None,
) -> list[str]:
    """Resolve automation tag groups using the shared AND/OR/NOT semantics.

    Tags inside one group are ORed. Every ``and`` group must match, at least
    one ``or`` group must match when OR groups exist, and any ``not`` group
    match excludes the device. ``exclude_tag_ids`` remains supported for
    saved filters created before group operators were introduced.
    """
    normalized: list[tuple[str, list[str]]] = []
    for raw_group in condition_groups or []:
        if not isinstance(raw_group, dict):
            continue
        tag_ids = list(dict.fromkeys(
            str(tag_id).strip()
            for tag_id in (raw_group.get("tag_ids") or [])
            if str(tag_id).strip()
        ))
        if not tag_ids:
            continue
        operator = str(raw_group.get("operator") or "and").strip().lower()
        if operator not in {"and", "or", "not"}:
            operator = "and"
        normalized.append((operator, tag_ids))

    excluded = list(dict.fromkeys(
        str(tag_id).strip()
        for tag_id in (exclude_tag_ids or [])
        if str(tag_id).strip()
    ))
    if excluded:
        normalized.append(("not", excluded))

    root = {
        "operator": "and",
        "negated": False,
        "tag_ids": [],
        "groups": [],
    }
    or_tag_ids: list[str] = []
    for operator, tag_ids in normalized:
        if operator == "or":
            or_tag_ids.extend(tag_ids)
            continue
        root["groups"].append({
            "operator": "or",
            "negated": operator == "not",
            "tag_ids": tag_ids,
            "groups": [],
        })
    if or_tag_ids:
        root["groups"].append({
            "operator": "or",
            "negated": False,
            "tag_ids": list(dict.fromkeys(or_tag_ids)),
            "groups": [],
        })
    return resolve_device_ids_by_expression(conn, root)


def resolve_device_ids_by_filter(conn, include_groups: list[list[str]] | None = None,
                                 exclude_tag_ids: list[str] | None = None) -> list[str]:
    """Backward-compatible AND-of-OR tag group resolver."""
    conditions = [
        {"operator": "and", "tag_ids": list(group)}
        for group in (include_groups or [])
        if group
    ]
    return resolve_device_ids_by_condition_groups(conn, conditions, exclude_tag_ids)


def find_devices_by_tags(conn, tag_ids: list[str], match_all: bool = True) -> list[str]:
    if not tag_ids:
        return []
    groups = [[tag_id] for tag_id in tag_ids] if match_all else [tag_ids]
    return resolve_device_ids_by_filter(conn, groups)


def get_tag_statistics(conn) -> dict:
    category_counts = conn.execute("SELECT category, COUNT(*) AS count FROM tag_definitions WHERE is_active=1 GROUP BY category ORDER BY category").fetchall()
    definition_counts = conn.execute(
        '''SELECT COUNT(*) AS total_definitions,
                  COALESCE(SUM(CASE WHEN EXISTS (
                      SELECT 1 FROM tag_assignments ta WHERE ta.tag_id = td.id
                  ) THEN 1 ELSE 0 END), 0) AS used_definitions
           FROM tag_definitions td
           WHERE td.is_active=1'''
    ).fetchone()
    usage_counts = conn.execute(
        '''SELECT td.id, td.category, td.code, td.label, td.label_zh, COUNT(ta.resource_id) AS device_count
           FROM tag_definitions td JOIN tag_assignments ta ON ta.tag_id=td.id
           WHERE td.is_active=1 AND ta.resource_type='device'
           GROUP BY td.id, td.category, td.code, td.label, td.label_zh
           ORDER BY COUNT(ta.resource_id) DESC LIMIT 20'''
    ).fetchall()
    return {
        "total_definitions": conn.execute("SELECT COUNT(*) FROM tag_definitions WHERE is_active=1").fetchone()[0],
        "used_definitions": definition_counts["used_definitions"] if definition_counts else 0,
        "unused_definitions": (
            definition_counts["total_definitions"] - definition_counts["used_definitions"]
            if definition_counts
            else 0
        ),
        "total_assignments": conn.execute("SELECT COUNT(*) FROM tag_assignments").fetchone()[0],
        "tagged_devices": conn.execute("SELECT COUNT(DISTINCT resource_id) FROM tag_assignments WHERE resource_type='device'").fetchone()[0],
        "categories": {row["category"]: row["count"] for row in category_counts},
        "top_used": [dict(row) for row in usage_counts],
    }
