"""Deterministic, read-only local PostgreSQL operational queries (0 LLM tokens).

Covers high-frequency network operations queries directly against PostgreSQL:
1. IPAM prefix / subnet utilization (`prefixes`, `ip_addresses`)
2. Topology neighbor lookup (`topology_links`, `devices`)
3. Interface anomalies / down / admin-down snapshot (`interfaces`, `devices`)
4. Recent configuration backups / changes (`config_backups`, `devices`)
"""

from __future__ import annotations

import ipaddress
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ai.security.sanitizer import sanitize_data
from database.core import get_db_connection

logger = logging.getLogger(__name__)

_CIDR_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}\b")
_DEVICE_TOKEN_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_-]{2,40})\b")


def _extract_cidr(text: str) -> Optional[str]:
    match = _CIDR_RE.search(str(text or ""))
    return match.group(0) if match else None


def _extract_device_hint(text: str) -> Optional[str]:
    ignore = {
        "lldp", "cdp", "ipam", "cmdb", "ospf", "bgp", "vlan", "stp", "mac", "arp",
        "crc", "down", "up", "admin", "status", "list", "show", "all", "top",
        "neighbors", "interfaces", "changes", "backup", "config",
    }
    for match in _DEVICE_TOKEN_RE.finditer(str(text or "")):
        token = match.group(1)
        if token.lower() not in ignore and (any(c.isdigit() for c in token) or "-" in token or "_" in token):
            return token
    return None


def query_ipam_prefix_usage(query: str, *, prefix_hint: Optional[str] = None) -> Dict[str, Any]:
    """Read-only IPAM prefix capacity & utilization report from PostgreSQL."""
    cidr = prefix_hint or _extract_cidr(query)
    rows: List[Dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            if cidr:
                prefix_rows = conn.execute(
                    "SELECT id, prefix, name, status, gateway, description FROM prefixes WHERE prefix = ? ORDER BY prefix LIMIT 20",
                    (cidr,),
                ).fetchall()
            else:
                prefix_rows = conn.execute(
                    "SELECT id, prefix, name, status, gateway, description FROM prefixes ORDER BY created_at DESC LIMIT 20"
                ).fetchall()
            for r in prefix_rows:
                pid, pfx, name, status, gw, desc = r[0], str(r[1] or ""), str(r[2] or ""), str(r[3] or "active"), str(r[4] or ""), str(r[5] or "")
                used_row = conn.execute(
                    "SELECT COUNT(*) FROM ip_addresses WHERE subnet_id = ? AND LOWER(COALESCE(status, 'active')) NOT IN ('deprecated', 'available', 'free')",
                    (pid,),
                ).fetchone()
                used = int((used_row[0] if used_row else 0) or 0)
                total_hosts = 0
                try:
                    net = ipaddress.ip_network(pfx, strict=False)
                    total_hosts = max(1, net.num_addresses - (2 if net.version == 4 and net.prefixlen < 31 else 0))
                except ValueError:
                    total_hosts = 0
                free = max(0, total_hosts - used) if total_hosts else 0
                pct = round((used / total_hosts) * 100, 1) if total_hosts else 0.0
                rows.append({
                    "prefix": pfx,
                    "name": name or desc or "-",
                    "status": status,
                    "gateway": gw or "-",
                    "used": used,
                    "free": free,
                    "total": total_hosts,
                    "utilization_pct": pct,
                })
    except Exception as exc:
        logger.warning("Local IPAM query failed: %s", type(exc).__name__)
        return {
            "matched_count": 0,
            "summary": "## Nexora IPAM 网段核对\n\n本地 IPAM 只读查询失败，请稍后重试。",
            "citations": [{"document": "Nexora IPAM prefixes", "document_id": "prefixes", "trust": "system"}],
        }

    safe_rows = sanitize_data(rows)
    if not safe_rows:
        target_note = f"未在 IPAM 中找到网段 `{cidr}`。" if cidr else "当前 IPAM 中暂无已登记网段。"
        return {
            "matched_count": 0,
            "summary": f"## Nexora IPAM 网段利用率（本地只读）\n\n{target_note}",
            "citations": [{"document": "Nexora IPAM prefixes", "document_id": "prefixes", "trust": "system"}],
        }

    lines = [
        "## Nexora IPAM 网段利用率（本地只读）",
        f"数据来源：PostgreSQL `prefixes` / `ip_addresses` 只读快照；匹配 {len(safe_rows)} 个网段。",
        "",
        "| 网段 | 名称/用途 | 状态 | 已用 | 可用 | 总可用数 | 利用率 |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for item in safe_rows:
        lines.append(
            f"| `{item['prefix']}` | {item['name']} | {item['status']} | {item['used']} | {item['free']} | {item['total']} | {item['utilization_pct']}% |"
        )
    lines.append("\n注：以上结果由系统直接从本地 PostgreSQL 实时计算，未调用外部大模型（0 Token）。")
    return {
        "matched_count": len(safe_rows),
        "summary": "\n".join(lines),
        "citations": [{"document": "Nexora IPAM prefixes", "document_id": "prefixes", "trust": "system"}],
    }


def query_topology_neighbors(query: str, *, device_hint: Optional[str] = None) -> Dict[str, Any]:
    """Read-only LLDP/CDP topology neighbor report from PostgreSQL."""
    target = (device_hint or _extract_device_hint(query) or "").strip()
    links: List[Dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            if target:
                pattern = f"%{target.lower()}%"
                raw_rows = conn.execute(
                    """
                    SELECT source_hostname, source_port, target_hostname, target_port, discovery_source, status, last_seen
                    FROM topology_links
                    WHERE LOWER(COALESCE(source_hostname, '')) LIKE ?
                       OR LOWER(COALESCE(target_hostname, '')) LIKE ?
                       OR LOWER(COALESCE(source_device_id, '')) LIKE ?
                       OR LOWER(COALESCE(target_device_id, '')) LIKE ?
                    ORDER BY updated_at DESC LIMIT 50
                    """,
                    (pattern, pattern, pattern, pattern),
                ).fetchall()
            else:
                raw_rows = conn.execute(
                    """
                    SELECT source_hostname, source_port, target_hostname, target_port, discovery_source, status, last_seen
                    FROM topology_links
                    ORDER BY updated_at DESC LIMIT 30
                    """
                ).fetchall()
            for r in raw_rows:
                links.append({
                    "source": str(r[0] or "-"),
                    "source_port": str(r[1] or "-"),
                    "target": str(r[2] or "-"),
                    "target_port": str(r[3] or "-"),
                    "protocol": str(r[4] or "lldp"),
                    "status": str(r[5] or "up"),
                })
    except Exception as exc:
        logger.warning("Local topology neighbor query failed: %s", type(exc).__name__)
        return {
            "matched_count": 0,
            "summary": "## Nexora 拓扑邻居查询\n\n本地拓扑表只读查询失败，请稍后重试。",
            "citations": [{"document": "Nexora topology_links", "document_id": "topology_links", "trust": "system"}],
        }

    safe_links = sanitize_data(links)
    if not safe_links:
        note = f"未找到与 `{target}` 相关的拓扑链路记录。" if target else "当前拓扑表中暂无链路记录。"
        return {
            "matched_count": 0,
            "summary": f"## Nexora 拓扑邻居核对（本地只读）\n\n{note}",
            "citations": [{"document": "Nexora topology_links", "document_id": "topology_links", "trust": "system"}],
        }

    scope_desc = f"设备关键字 `{target}`" if target else "全网最近发现链路"
    lines = [
        "## Nexora 拓扑邻居核对（本地只读）",
        f"范围：{scope_desc}；数据来源：PostgreSQL `topology_links` 只读快照，共匹配 {len(safe_links)} 条互联链路。",
        "",
        "| 本端设备 | 本端端口 | 对端设备 | 对端端口 | 发现协议 | 状态 |",
        "|---|---|---|---|---|---|",
    ]
    for item in safe_links[:30]:
        lines.append(
            f"| {item['source']} | {item['source_port']} | {item['target']} | {item['target_port']} | {item['protocol']} | {item['status']} |"
        )
    lines.append("\n注：以上拓扑邻接关系由本地 PostgreSQL 直接输出，未调用外部大模型（0 Token）。")
    return {
        "matched_count": len(safe_links),
        "summary": "\n".join(lines),
        "citations": [{"document": "Nexora topology_links", "document_id": "topology_links", "trust": "system"}],
    }


def query_interface_anomalies(query: str, *, device_hint: Optional[str] = None) -> Dict[str, Any]:
    """Read-only interface status / down-port snapshot from PostgreSQL."""
    target = (device_hint or _extract_device_hint(query) or "").strip()
    lower_q = str(query or "").lower()
    only_down = any(m in lower_q for m in ("down", "异常", "故障", "断开", "离线", "告警"))
    rows: List[Dict[str, Any]] = []
    total_interfaces = 0
    down_count = 0
    try:
        with get_db_connection() as conn:
            where = []
            params: list[Any] = []
            if target:
                where.append("LOWER(COALESCE(d.hostname, '')) LIKE ?")
                params.append(f"%{target.lower()}%")
            where_sql = f"WHERE {' AND '.join(where)}" if where else ""
            stats = conn.execute(
                f"""
                SELECT COUNT(*),
                       SUM(CASE WHEN LOWER(COALESCE(i.oper_status, 'down')) != 'up' THEN 1 ELSE 0 END)
                FROM interfaces i
                LEFT JOIN devices d ON d.id = i.device_id
                {where_sql}
                """,
                tuple(params),
            ).fetchone()
            total_interfaces = int((stats[0] if stats else 0) or 0)
            down_count = int((stats[1] if stats else 0) or 0)

            detail_where = list(where)
            if only_down:
                detail_where.append("LOWER(COALESCE(i.oper_status, 'down')) != 'up'")
            detail_where_sql = f"WHERE {' AND '.join(detail_where)}" if detail_where else ""
            raw = conn.execute(
                f"""
                SELECT COALESCE(d.hostname, i.device_id), i.interface_name, i.admin_status, i.oper_status,
                       i.interface_role, i.description, i.last_flapped
                FROM interfaces i
                LEFT JOIN devices d ON d.id = i.device_id
                {detail_where_sql}
                ORDER BY CASE WHEN LOWER(COALESCE(i.oper_status, 'down')) != 'up' THEN 0 ELSE 1 END,
                         d.hostname, i.interface_name
                LIMIT 30
                """,
                tuple(params),
            ).fetchall()
            for r in raw:
                rows.append({
                    "hostname": str(r[0] or "-"),
                    "interface": str(r[1] or "-"),
                    "admin": str(r[2] or "-"),
                    "oper": str(r[3] or "-"),
                    "role": str(r[4] or "-"),
                    "desc": str(r[5] or "-")[:40],
                })
    except Exception as exc:
        logger.warning("Local interface query failed: %s", type(exc).__name__)
        return {
            "matched_count": 0,
            "summary": "## Nexora 接口状态快照\n\n本地接口表只读查询失败，请稍后重试。",
            "citations": [{"document": "Nexora interfaces", "document_id": "interfaces", "trust": "system"}],
        }

    safe_rows = sanitize_data(rows)
    scope_desc = f"设备 `{target}`" if target else "全网纳管设备"
    lines = [
        "## Nexora 接口状态快照（本地只读）",
        f"范围：{scope_desc}；接口总数 **{total_interfaces}**，当前非 UP（down/异常）接口 **{down_count}** 个。",
    ]
    if safe_rows:
        lines.extend([
            "",
            "| 设备 | 接口 | 管理状态 | 物理状态 | 角色 | 描述 |",
            "|---|---|---|---|---|---|",
        ])
        for item in safe_rows:
            lines.append(
                f"| {item['hostname']} | {item['interface']} | {item['admin']} | {item['oper']} | {item['role']} | {item['desc']} |"
            )
    else:
        lines.append("\n当前范围内无匹配的接口记录。")
    lines.append("\n注：以上结果由本地 PostgreSQL `interfaces` 表实时统计，未调用外部大模型（0 Token）。")
    return {
        "matched_count": len(safe_rows),
        "summary": "\n".join(lines),
        "citations": [{"document": "Nexora interfaces", "document_id": "interfaces", "trust": "system"}],
    }


def query_recent_config_changes(query: str, *, device_hint: Optional[str] = None) -> Dict[str, Any]:
    """Read-only recent configuration backup / snapshot history from PostgreSQL."""
    target = (device_hint or _extract_device_hint(query) or "").strip()
    lower_q = str(query or "").lower()
    days = 7
    if any(m in lower_q for m in ("24小时", "24h", "今天", "今日", "最近1天")):
        days = 1
    elif any(m in lower_q for m in ("30天", "一个月", "本月")):
        days = 30
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows: List[Dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            params: list[Any] = [cutoff]
            where = ["b.backup_time >= ?"]
            if target:
                where.append("LOWER(COALESCE(d.hostname, '')) LIKE ?")
                params.append(f"%{target.lower()}%")
            raw = conn.execute(
                f"""
                SELECT COALESCE(d.hostname, b.device_id), COALESCE(d.vendor, '-'), b.config_type, b.backup_time, b.config_hash
                FROM config_backups b
                LEFT JOIN devices d ON d.id = b.device_id
                WHERE {' AND '.join(where)}
                ORDER BY b.backup_time DESC LIMIT 30
                """,
                tuple(params),
            ).fetchall()
            for r in raw:
                rows.append({
                    "hostname": str(r[0] or "-"),
                    "vendor": str(r[1] or "-"),
                    "config_type": str(r[2] or "running"),
                    "backup_time": str(r[3] or "-"),
                    "hash": str(r[4] or "-")[:12],
                })
    except Exception as exc:
        logger.warning("Local config backup query failed: %s", type(exc).__name__)
        return {
            "matched_count": 0,
            "summary": "## Nexora 配置备份与变更记录\n\n本地配置备份表只读查询失败，请稍后重试。",
            "citations": [{"document": "Nexora config_backups", "document_id": "config_backups", "trust": "system"}],
        }

    safe_rows = sanitize_data(rows)
    if not safe_rows:
        return {
            "matched_count": 0,
            "summary": f"## Nexora 配置备份与变更记录（本地只读）\n\n最近 {days} 天内未查到匹配的配置备份/变更记录。",
            "citations": [{"document": "Nexora config_backups", "document_id": "config_backups", "trust": "system"}],
        }

    lines = [
        "## Nexora 配置备份与变更记录（本地只读）",
        f"时间窗口：最近 {days} 天；数据来源：PostgreSQL `config_backups` 只读快照，共 {len(safe_rows)} 条记录。",
        "",
        "| 设备 | 厂商 | 配置类型 | 备份时间 | 摘要 Hash |",
        "|---|---|---|---|---|",
    ]
    for item in safe_rows:
        lines.append(
            f"| {item['hostname']} | {item['vendor']} | {item['config_type']} | {item['backup_time']} | `{item['hash']}` |"
        )
    lines.append("\n注：以上配置记录直接来自本地 PostgreSQL，未调用外部大模型（0 Token）。")
    return {
        "matched_count": len(safe_rows),
        "summary": "\n".join(lines),
        "citations": [{"document": "Nexora config_backups", "document_id": "config_backups", "trust": "system"}],
    }


def execute_local_ops_query(operation: str, query: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Dispatch a deterministic zero-token local ops query."""
    f = filters or {}
    if operation == "ipam_prefix":
        return query_ipam_prefix_usage(query, prefix_hint=f.get("prefix"))
    if operation == "topology_neighbors":
        return query_topology_neighbors(query, device_hint=f.get("device"))
    if operation == "interface_anomalies":
        return query_interface_anomalies(query, device_hint=f.get("device"))
    if operation == "config_changes":
        return query_recent_config_changes(query, device_hint=f.get("device"))
    return {
        "matched_count": 0,
        "summary": "## 本地查询\n\n未识别的本地只读操作类型。",
        "citations": [],
    }
