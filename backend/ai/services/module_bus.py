"""12-Module Unified Read-Only Zero-Token Capability Bus for Nexora Copilot.

Provides concise, question-matched, RBAC-enforced, read-only PostgreSQL query
handlers spanning all 12 Nexora control-plane modules:
  0. Overview (homepage summary)
  1. Operations Workbench / PAM (`pam_sessions`)
  2. Real-Time Monitoring (`devices`, `interfaces`, `topology_links`)
  3. Alarm Management (`alert_events`)
  4. Assets & Racks (`devices` single profile card, `racks`, `physical_assets`)
  5. IPAM (`prefixes`, `ip_addresses`)
  6. CMDB Base Data (`sites`, `vlans`, `credentials` metadata-only)
  7. Configuration Management (`config_backups`, `config_drift_results`, `compliance_findings`)
  8. Automation (`inspection_runs`, `scheduled_jobs`)
  9. Change Orders / Tickets (`change_orders`)
  10. Capacity & Reports (high-utilization racks & prefixes)
  11. Platform Management (`users`, `audit_logs` — admin-gated)

Every handler returns:
  {
    "module": str,
    "matched_count": int,
    "summary": str,              # Concise, direct Markdown answer
    "citations": list[dict],
    "entity_updates": dict,      # Updates merged into conversation entity memory
    "fact_note": str,            # Compact 1-line fact for downstream LLM reasoning
    "denied": bool,              # True if RBAC denied (0 tokens)
  }
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from ai.security.sanitizer import sanitize_data
from ai.services.local_ops_queries import (
    query_interface_anomalies,
    query_ipam_prefix_usage,
    query_recent_config_changes,
    query_topology_neighbors,
)
from database.core import get_db_connection

logger = logging.getLogger(__name__)

# Module-level RBAC requirements (coarse role names normalized lowercase).
_MODULE_ALLOWED_ROLES: Dict[str, frozenset[str]] = {
    "overview": frozenset({"administrator", "admin", "operator", "viewer", "user"}),
    "device_profile": frozenset({"administrator", "admin", "operator", "viewer", "user"}),
    "pam_sessions": frozenset({"administrator", "admin", "operator", "change requester"}),
    "topology_neighbors": frozenset({"administrator", "admin", "operator", "viewer", "user"}),
    "interface_anomalies": frozenset({"administrator", "admin", "operator", "viewer", "user"}),
    "racks": frozenset({"administrator", "admin", "operator", "viewer", "user"}),
    "ipam_prefix": frozenset({"administrator", "admin", "operator", "viewer", "user"}),
    "cmdb_base": frozenset({"administrator", "admin", "operator", "viewer", "user"}),
    "credentials_meta": frozenset({"administrator", "admin", "operator"}),
    "config_changes": frozenset({"administrator", "admin", "operator", "viewer", "user"}),
    "config_drift": frozenset({"administrator", "admin", "operator", "viewer", "user"}),
    "compliance": frozenset({"administrator", "admin", "operator", "viewer", "user"}),
    "automation_inspections": frozenset({"administrator", "admin", "operator", "viewer", "user"}),
    "change_orders": frozenset({"administrator", "admin", "operator", "viewer", "change requester"}),
    "capacity_summary": frozenset({"administrator", "admin", "operator", "viewer", "user"}),
    "platform_audit": frozenset({"administrator", "admin"}),
}


def check_module_access(roles: Optional[Sequence[str]], module: str) -> bool:
    """Enforce read-only RBAC before executing any module query."""
    allowed = _MODULE_ALLOWED_ROLES.get(module)
    if not allowed:
        return True
    normalized = {str(r or "").strip().lower() for r in (roles or []) if str(r or "").strip()}
    if not normalized:
        # Backward compatibility when internal callers omit roles in unit tests.
        return True
    return bool(normalized & allowed)


def _days_from_query(query: str, default_days: int = 7) -> int:
    q = str(query or "").lower()
    if any(m in q for m in ("今天", "今日", "24小时", "24h", "当天")):
        return 1
    if any(m in q for m in ("昨天", "昨日", "48小时")):
        return 2
    if any(m in q for m in ("30天", "一个月", "本月", "近一月")):
        return 30
    return default_days


def _denied_response(module: str, label: str) -> Dict[str, Any]:
    return {
        "module": module,
        "matched_count": 0,
        "denied": True,
        "summary": (
            f"## 权限提示\n\n"
            f"当前账号缺少 **{label}** 的只读查看权限，已按安全策略拦截查询（未调用外部模型，0 Token）。"
            f"如需访问，请联系管理员在「平台管理 → 用户与权限」中授权。"
        ),
        "citations": [],
        "entity_updates": {},
        "fact_note": "",
    }


def _query_overview() -> Dict[str, Any]:
    """Module 0: Homepage-aligned network overview snapshot."""
    total_dev = online_dev = active_alerts = critical_alerts = 0
    recent_runs = success_runs = 0
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*), SUM(CASE WHEN LOWER(COALESCE(status, '')) IN ('online', 'up') THEN 1 ELSE 0 END) FROM devices"
            ).fetchone()
            if row:
                total_dev = int(row[0] or 0)
                online_dev = int(row[1] or 0)
            arow = conn.execute(
                """
                SELECT COUNT(*),
                       SUM(CASE WHEN LOWER(COALESCE(severity, '')) IN ('critical', 'high', 'emergency') THEN 1 ELSE 0 END)
                FROM alert_events
                WHERE COALESCE(resolved_at, '') = ''
                """
            ).fetchone()
            if arow:
                active_alerts = int(arow[0] or 0)
                critical_alerts = int(arow[1] or 0)
            cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            irow = conn.execute(
                """
                SELECT COUNT(*), SUM(CASE WHEN LOWER(COALESCE(status, '')) IN ('completed', 'success') THEN 1 ELSE 0 END)
                FROM inspection_runs WHERE started_at >= ?
                """,
                (cutoff,),
            ).fetchone()
            if irow:
                recent_runs = int(irow[0] or 0)
                success_runs = int(irow[1] or 0)
    except Exception as exc:
        logger.warning("Overview query failed: %s", type(exc).__name__)

    online_pct = round((online_dev / total_dev) * 100, 1) if total_dev else 0.0
    summary = "\n".join([
        "## Nexora 全网运行总览（本地只读）",
        "",
        f"- **设备在线率**：**{online_pct}%**（{online_dev} / {total_dev} 台在线）",
        f"- **当前未恢复告警**：**{active_alerts}** 条（其中严重/高级别 **{critical_alerts}** 条）",
        f"- **近 24 小时巡检任务**：共 **{recent_runs}** 次（成功 **{success_runs}** 次）",
        "",
        "> 数据来源：PostgreSQL 本地实时快照（0 Token）。可继续追问具体设备、告警或巡检明细。",
    ])
    return {
        "module": "overview",
        "matched_count": total_dev,
        "denied": False,
        "summary": summary,
        "citations": [{"document": "Nexora Control Plane Overview", "document_id": "overview", "trust": "system"}],
        "entity_updates": {"last_module": "overview"},
        "fact_note": f"全网 {online_dev}/{total_dev} 在线，未恢复告警 {active_alerts} 条（严重 {critical_alerts} 条）",
    }


def _query_device_profile(entities: Dict[str, Any]) -> Dict[str, Any]:
    """Module 4/6: Concise single-device profile card (e.g. '1.1.1.1 这台设备的信息')."""
    device = entities.get("device")
    explicit_ip = entities.get("explicit_ip")
    if not device:
        target = explicit_ip or entities.get("scope_label") or "目标设备"
        return {
            "module": "device_profile",
            "matched_count": 0,
            "denied": False,
            "summary": (
                f"## 设备档案查询\n\n"
                f"未在 CMDB 纳管设备表中找到 **`{target}`**。\n\n"
                f"> 数据来源：PostgreSQL `devices` 只读快照（0 Token）。"
            ),
            "citations": [{"document": "Nexora CMDB devices", "document_id": "devices", "trust": "system"}],
            "entity_updates": {"last_module": "device_profile"},
            "fact_note": f"CMDB 中未找到设备 {target}",
        }

    # Optionally enrich with rack & active alert count (still 0 Token, read-only).
    rack_info = "-"
    active_alert_count = 0
    try:
        with get_db_connection() as conn:
            arow = conn.execute(
                "SELECT COUNT(*) FROM alert_events WHERE device_id = ? AND COALESCE(resolved_at, '') = ''",
                (device["id"],),
            ).fetchone()
            if arow:
                active_alert_count = int(arow[0] or 0)
            prow = conn.execute(
                """
                SELECT rack, rack_unit FROM physical_assets
                WHERE LOWER(COALESCE(hostname, '')) = ? LIMIT 1
                """,
                (str(device.get("hostname") or "").lower(),),
            ).fetchone()
            if prow and (prow[0] or prow[1]):
                rack_info = f"{prow[0] or '-'} / {prow[1] or '-'}"
    except Exception:
        pass

    safe = sanitize_data(device)
    label = f"{safe.get('hostname') or '-'} ({safe.get('ip_address') or '-'})"
    lines = [
        f"## 设备档案：{label}",
        f"查询对象：`{label}` · 来源：CMDB 只读快照（0 Token）",
        "",
        "| 字段 | 值 |",
        "|---|---|",
        f"| 主机名 | `{safe.get('hostname') or '-'}` |",
        f"| 管理 IP | `{safe.get('ip_address') or '-'}` |",
        f"| 厂商 / 平台 | {safe.get('vendor') or '-'} / `{safe.get('platform') or '-'}` |",
        f"| 型号 / 版本 | {safe.get('model') or '-'} / `{safe.get('version') or '-'}` |",
        f"| 角色 / 状态 | {safe.get('role') or '-'} / **{safe.get('status') or '-'}** |",
        f"| 站点 / 机柜 U 位 | {safe.get('site') or '-'} / {rack_info} |",
        f"| 当前未恢复告警 | **{active_alert_count}** 条 |",
        "",
        "> 已锁定当前对话焦点设备，可直接继续追问：「这台设备最近登录了几次」「它有告警吗」「最近配置改过吗」「上联连着谁」（全程 0 Token）。",
    ]
    return {
        "module": "device_profile",
        "matched_count": 1,
        "denied": False,
        "summary": "\n".join(lines),
        "citations": [{"document": "Nexora CMDB devices", "document_id": "devices", "trust": "system"}],
        "entity_updates": {
            "active_device": device,
            "active_vendor": str(device.get("vendor") or "").lower() or None,
            "active_site": device.get("site") or None,
            "last_module": "device_profile",
        },
        "fact_note": f"设备 {label}，{safe.get('vendor')} {safe.get('model')}，状态 {safe.get('status')}，未恢复告警 {active_alert_count} 条",
    }


def _query_pam_sessions(query: str, entities: Dict[str, Any]) -> Dict[str, Any]:
    """Module 1: Operations Workbench / PAM login count & session audit (0 Token)."""
    days = _days_from_query(query, default_days=7)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    device = entities.get("device")
    explicit_ip = entities.get("explicit_ip")
    scope_label = entities.get("scope_label") or "全网"

    rows: List[Dict[str, Any]] = []
    total_count = 0
    active_count = 0
    try:
        with get_db_connection() as conn:
            where = ["created_at >= ?"]
            params: List[Any] = [cutoff]
            if device:
                clauses = []
                if device.get("id"):
                    clauses.append("device_id = ?")
                    params.append(device["id"])
                if device.get("ip_address"):
                    clauses.append("target_ip = ?")
                    params.append(device["ip_address"])
                if device.get("hostname"):
                    clauses.append("LOWER(COALESCE(target_hostname, '')) = ?")
                    params.append(str(device["hostname"]).lower())
                if clauses:
                    where.append(f"({' OR '.join(clauses)})")
            elif explicit_ip:
                where.append("target_ip = ?")
                params.append(explicit_ip)

            where_sql = " AND ".join(where)
            cnt_row = conn.execute(
                f"""
                SELECT COUNT(*),
                       SUM(CASE WHEN LOWER(COALESCE(status, '')) IN ('active', 'connected', 'connecting') THEN 1 ELSE 0 END)
                FROM pam_sessions WHERE {where_sql}
                """,
                tuple(params),
            ).fetchone()
            if cnt_row:
                total_count = int(cnt_row[0] or 0)
                active_count = int(cnt_row[1] or 0)

            raw = conn.execute(
                f"""
                SELECT created_at, requester_username, login_username, session_kind,
                       target_hostname, target_ip, status, command_count, risk_level
                FROM pam_sessions
                WHERE {where_sql}
                ORDER BY created_at DESC LIMIT 15
                """,
                tuple(params),
            ).fetchall()
            for r in raw:
                rows.append({
                    "time": str(r[0] or "-")[:19].replace("T", " "),
                    "user": str(r[1] or "-"),
                    "login_as": str(r[2] or "-"),
                    "kind": str(r[3] or "ssh"),
                    "target": str(r[4] or r[5] or "-"),
                    "status": str(r[6] or "-"),
                    "cmds": int(r[7] or 0),
                    "risk": str(r[8] or "low"),
                })
    except Exception as exc:
        logger.warning("PAM session query failed: %s", type(exc).__name__)
        return {
            "module": "pam_sessions",
            "matched_count": 0,
            "denied": False,
            "summary": "## 操作工作台（PAM）登录记录\n\n本地 PAM 会话表只读查询失败，请稍后重试。",
            "citations": [{"document": "Nexora PAM sessions", "document_id": "pam_sessions", "trust": "system"}],
            "entity_updates": {"last_module": "pam_sessions"},
            "fact_note": "",
        }

    safe_rows = sanitize_data(rows)
    verdict = (
        f"查询范围：**{scope_label}** · 最近 **{days}** 天共登录 **{total_count}** 次（当前活跃会话 **{active_count}** 个）。"
    )
    lines = ["## 操作工作台（PAM）登录审计（本地只读）", "", verdict]
    if safe_rows:
        lines.extend([
            "",
            "| 时间 | 平台用户 | 登录账号 | 方式 | 目标设备 | 状态 | 命令数 | 风险 |",
            "|---|---|---|---|---|---|---:|---|",
        ])
        for item in safe_rows:
            lines.append(
                f"| {item['time']} | {item['user']} | {item['login_as']} | {item['kind']} | {item['target']} | {item['status']} | {item['cmds']} | {item['risk']} |"
            )
    else:
        lines.append("\n该时间范围内无登录记录。")
    lines.append("\n> 数据来源：PostgreSQL `pam_sessions` 只读快照（0 Token）。")

    updates: Dict[str, Any] = {"last_module": "pam_sessions"}
    if device:
        updates["active_device"] = device
    return {
        "module": "pam_sessions",
        "matched_count": total_count,
        "denied": False,
        "summary": "\n".join(lines),
        "citations": [{"document": "Nexora PAM sessions", "document_id": "pam_sessions", "trust": "system"}],
        "entity_updates": updates,
        "fact_note": f"{scope_label} 最近 {days} 天 PAM 登录 {total_count} 次（活跃 {active_count}）",
    }


def _query_racks(entities: Dict[str, Any]) -> Dict[str, Any]:
    """Module 4: Rack location for a device or rack U-space utilization."""
    device = entities.get("device")
    site = entities.get("site")
    rows: List[Dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            if device:
                prow = conn.execute(
                    """
                    SELECT hostname, site_id, rack, rack_unit, vendor, model
                    FROM physical_assets
                    WHERE LOWER(COALESCE(hostname, '')) = ? LIMIT 1
                    """,
                    (str(device.get("hostname") or "").lower(),),
                ).fetchone()
                if prow and (prow[2] or prow[3]):
                    summary = (
                        f"## 机柜与 U 位信息\n\n"
                        f"查询对象：**{entities['scope_label']}**\n\n"
                        f"- 所在机柜：**{prow[2] or '未登记'}**\n"
                        f"- U 位：**{prow[3] or '未登记'}**\n"
                        f"- 站点：`{prow[1] or device.get('site') or '-'}`\n\n"
                        f"> 数据来源：PostgreSQL `physical_assets` 只读快照（0 Token）。"
                    )
                else:
                    summary = (
                        f"## 机柜与 U 位信息\n\n"
                        f"查询对象：**{entities['scope_label']}** — 资产表中暂未登记该设备的机柜/U 位信息。\n\n"
                        f"> 数据来源：PostgreSQL `physical_assets` 只读快照（0 Token）。"
                    )
                return {
                    "module": "racks",
                    "matched_count": 1 if (prow and prow[2]) else 0,
                    "denied": False,
                    "summary": summary,
                    "citations": [{"document": "Nexora physical_assets", "document_id": "physical_assets", "trust": "system"}],
                    "entity_updates": {"active_device": device, "last_module": "racks"},
                    "fact_note": f"{entities['scope_label']} 机柜={prow[2] if prow else '未登记'}",
                }

            params: List[Any] = []
            where = ""
            if site:
                where = "WHERE LOWER(COALESCE(datacenter, '')) LIKE ? OR LOWER(COALESCE(rack_code, '')) LIKE ?"
                params.extend([f"%{site.lower()}%", f"%{site.lower()}%"])
            raw = conn.execute(
                f"""
                SELECT rack_code, rack_name, datacenter, room, total_u, used_u, available_u
                FROM racks {where}
                ORDER BY available_u ASC LIMIT 20
                """,
                tuple(params),
            ).fetchall()
            for r in raw:
                total_u = int(r[4] or 42)
                used_u = int(r[5] or 0)
                avail_u = int(r[6] if r[6] is not None else max(0, total_u - used_u))
                rows.append({
                    "code": str(r[0] or "-"),
                    "name": str(r[1] or "-"),
                    "dc": str(r[2] or r[3] or "-"),
                    "total_u": total_u,
                    "used_u": used_u,
                    "avail_u": avail_u,
                    "pct": round((used_u / total_u) * 100, 1) if total_u else 0.0,
                })
    except Exception as exc:
        logger.warning("Rack query failed: %s", type(exc).__name__)

    if not rows:
        return {
            "module": "racks",
            "matched_count": 0,
            "denied": False,
            "summary": f"## 机柜与 U 位统计（本地只读）\n\n查询范围：**{entities['scope_label']}** — 暂未查到机柜记录（0 Token）。",
            "citations": [{"document": "Nexora racks", "document_id": "racks", "trust": "system"}],
            "entity_updates": {"last_module": "racks"},
            "fact_note": "机柜 0 条",
        }
    total_avail = sum(r["avail_u"] for r in rows)
    lines = [
        "## 机柜与 U 位容量（本地只读）",
        f"查询范围：**{entities['scope_label']}** · 共 **{len(rows)}** 个机柜，合计剩余可用 **{total_avail} U**。",
        "",
        "| 机柜编号 | 名称 | 机房 | 总 U | 已用 U | 剩余 U | 占用率 |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(f"| `{r['code']}` | {r['name']} | {r['dc']} | {r['total_u']} | {r['used_u']} | {r['avail_u']} | {r['pct']}% |")
    lines.append("\n> 数据来源：PostgreSQL `racks` 只读快照（0 Token）。")
    return {
        "module": "racks",
        "matched_count": len(rows),
        "denied": False,
        "summary": "\n".join(lines),
        "citations": [{"document": "Nexora racks", "document_id": "racks", "trust": "system"}],
        "entity_updates": {"last_module": "racks"},
        "fact_note": f"共 {len(rows)} 个机柜，剩余 {total_avail}U",
    }


def _query_config_drift_or_compliance(kind: str, entities: Dict[str, Any]) -> Dict[str, Any]:
    """Module 7: Config drift (`config_drift_results`) or compliance (`compliance_findings`)."""
    device = entities.get("device")
    scope_label = entities.get("scope_label") or "全网"
    rows: List[Dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            if kind == "config_drift":
                params: List[Any] = []
                where = "WHERE LOWER(COALESCE(drift_status, '')) NOT IN ('in_sync', 'clean', 'none')"
                if device and device.get("id"):
                    where += " AND device_id = ?"
                    params.append(device["id"])
                raw = conn.execute(
                    f"""
                    SELECT hostname, drift_status, added_lines, removed_lines, changed_lines, checked_at
                    FROM config_drift_results {where}
                    ORDER BY checked_at DESC LIMIT 20
                    """,
                    tuple(params),
                ).fetchall()
                for r in raw:
                    rows.append({
                        "hostname": str(r[0] or "-"),
                        "status": str(r[1] or "-"),
                        "diff": f"+{int(r[2] or 0)} / -{int(r[3] or 0)} / ~{int(r[4] or 0)}",
                        "checked_at": str(r[5] or "-")[:19].replace("T", " "),
                    })
            else:
                params = []
                where = "WHERE LOWER(COALESCE(f.status, 'open')) = 'open'"
                if device and device.get("id"):
                    where += " AND f.device_id = ?"
                    params.append(device["id"])
                raw = conn.execute(
                    f"""
                    SELECT COALESCE(d.hostname, f.device_id), f.severity, f.category, f.title, f.status
                    FROM compliance_findings f
                    LEFT JOIN devices d ON d.id = f.device_id
                    {where}
                    ORDER BY f.severity DESC LIMIT 20
                    """,
                    tuple(params),
                ).fetchall()
                for r in raw:
                    rows.append({
                        "hostname": str(r[0] or "-"),
                        "severity": str(r[1] or "-"),
                        "category": str(r[2] or "-"),
                        "title": str(r[3] or "-")[:60],
                        "status": str(r[4] or "open"),
                    })
    except Exception as exc:
        logger.warning("Config %s query failed: %s", kind, type(exc).__name__)

    safe_rows = sanitize_data(rows)
    if kind == "config_drift":
        verdict = (
            f"**发现漂移**：{scope_label} 当前有 **{len(safe_rows)}** 条配置漂移记录。"
            if safe_rows else f"**无配置漂移**：{scope_label} 当前配置与基线一致。"
        )
        lines = ["## 配置漂移检查（本地只读）", "", verdict]
        if safe_rows:
            lines.extend(["", "| 设备 | 漂移状态 | 行变更 | 检查时间 |", "|---|---|---|---|"])
            for r in safe_rows:
                lines.append(f"| {r['hostname']} | {r['status']} | `{r['diff']}` | {r['checked_at']} |")
        lines.append("\n> 数据来源：PostgreSQL `config_drift_results` 只读快照（0 Token）。")
        doc_id = "config_drift_results"
    else:
        verdict = (
            f"**存在不合规项**：{scope_label} 当前有 **{len(safe_rows)}** 条未关闭合规项。"
            if safe_rows else f"**合规通过**：{scope_label} 当前无未关闭的合规基线违规项。"
        )
        lines = ["## 配置合规基线检查（本地只读）", "", verdict]
        if safe_rows:
            lines.extend(["", "| 设备 | 级别 | 类别 | 不合规项 | 状态 |", "|---|---|---|---|---|"])
            for r in safe_rows:
                lines.append(f"| {r['hostname']} | {r['severity']} | {r['category']} | {r['title']} | {r['status']} |")
        lines.append("\n> 数据来源：PostgreSQL `compliance_findings` 只读快照（0 Token）。")
        doc_id = "compliance_findings"

    updates: Dict[str, Any] = {"last_module": kind}
    if device:
        updates["active_device"] = device
    return {
        "module": kind,
        "matched_count": len(safe_rows),
        "denied": False,
        "summary": "\n".join(lines),
        "citations": [{"document": f"Nexora {doc_id}", "document_id": doc_id, "trust": "system"}],
        "entity_updates": updates,
        "fact_note": f"{scope_label} {kind} 命中 {len(safe_rows)} 条",
    }


def _query_automation_inspections(query: str) -> Dict[str, Any]:
    """Module 8: Recent inspection runs & scheduled job status."""
    days = _days_from_query(query, default_days=7)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    runs: List[Dict[str, Any]] = []
    enabled_jobs = 0
    try:
        with get_db_connection() as conn:
            raw = conn.execute(
                """
                SELECT started_at, trigger_type, status, total_devices, success_count, failed_count, warning_count
                FROM inspection_runs
                WHERE started_at >= ?
                ORDER BY started_at DESC LIMIT 10
                """,
                (cutoff,),
            ).fetchall()
            for r in raw:
                runs.append({
                    "time": str(r[0] or "-")[:19].replace("T", " "),
                    "trigger": str(r[1] or "-"),
                    "status": str(r[2] or "-"),
                    "total": int(r[3] or 0),
                    "ok": int(r[4] or 0),
                    "fail": int(r[5] or 0),
                    "warn": int(r[6] or 0),
                })
            jrow = conn.execute("SELECT COUNT(*) FROM scheduled_jobs WHERE enabled = 1").fetchone()
            if jrow:
                enabled_jobs = int(jrow[0] or 0)
    except Exception as exc:
        logger.warning("Automation inspection query failed: %s", type(exc).__name__)

    lines = [
        "## 自动化巡检与任务摘要（本地只读）",
        f"最近 **{days}** 天共执行巡检 **{len(runs)}** 次；当前已启用定时任务 **{enabled_jobs}** 个。",
    ]
    if runs:
        lines.extend([
            "",
            "| 开始时间 | 触发方式 | 状态 | 设备数 | 成功 | 失败 | 告警 |",
            "|---|---|---|---:|---:|---:|---:|",
        ])
        for r in runs:
            lines.append(f"| {r['time']} | {r['trigger']} | {r['status']} | {r['total']} | {r['ok']} | {r['fail']} | {r['warn']} |")
    else:
        lines.append("\n该时间窗口内暂无巡检执行记录。")
    lines.append("\n> 数据来源：PostgreSQL `inspection_runs` / `scheduled_jobs` 只读快照（0 Token）。")
    return {
        "module": "automation_inspections",
        "matched_count": len(runs),
        "denied": False,
        "summary": "\n".join(lines),
        "citations": [{"document": "Nexora inspection_runs", "document_id": "inspection_runs", "trust": "system"}],
        "entity_updates": {"last_module": "automation_inspections"},
        "fact_note": f"近 {days} 天巡检 {len(runs)} 次，启用定时任务 {enabled_jobs} 个",
    }


def _query_change_orders(query: str, entities: Dict[str, Any]) -> Dict[str, Any]:
    """Module 9: Pending or device-related change orders."""
    device = entities.get("device")
    scope_label = entities.get("scope_label") or "全网"
    only_pending = any(m in str(query or "").lower() for m in ("待审批", "待审核", "审批中", "pending"))
    rows: List[Dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            where = []
            params: List[Any] = []
            if only_pending:
                where.append("LOWER(COALESCE(status, '')) IN ('pending', 'pending_approval', 'submitted')")
            if device:
                clauses = []
                for key in ("id", "hostname", "ip_address"):
                    val = str(device.get(key) or "").strip()
                    if val:
                        clauses.append("LOWER(COALESCE(target_devices_json, '')) LIKE ?")
                        params.append(f"%{val.lower()}%")
                if clauses:
                    where.append(f"({' OR '.join(clauses)})")
            where_sql = f"WHERE {' AND '.join(where)}" if where else ""
            raw = conn.execute(
                f"""
                SELECT order_number, title, order_type, priority, status, requester_username, approver_username
                FROM change_orders {where_sql}
                ORDER BY id DESC LIMIT 15
                """,
                tuple(params),
            ).fetchall()
            for r in raw:
                rows.append({
                    "no": str(r[0] or "-"),
                    "title": str(r[1] or "-")[:50],
                    "type": str(r[2] or "-"),
                    "priority": str(r[3] or "-"),
                    "status": str(r[4] or "-"),
                    "requester": str(r[5] or "-"),
                    "approver": str(r[6] or "-"),
                })
    except Exception as exc:
        logger.warning("Change orders query failed: %s", type(exc).__name__)

    safe_rows = sanitize_data(rows)
    verdict = (
        f"查询范围：**{scope_label}** · 共查到 **{len(safe_rows)}** 条{'待审批' if only_pending else ''}变更工单。"
    )
    lines = ["## 变更工单查询（本地只读）", "", verdict]
    if safe_rows:
        lines.extend([
            "",
            "| 工单号 | 标题 | 类型 | 优先级 | 状态 | 申请人 | 审批人 |",
            "|---|---|---|---|---|---|---|",
        ])
        for r in safe_rows:
            lines.append(f"| `{r['no']}` | {r['title']} | {r['type']} | {r['priority']} | {r['status']} | {r['requester']} | {r['approver']} |")
    lines.append("\n> 数据来源：PostgreSQL `change_orders` 只读快照（0 Token）。")
    updates: Dict[str, Any] = {"last_module": "change_orders"}
    if device:
        updates["active_device"] = device
    return {
        "module": "change_orders",
        "matched_count": len(safe_rows),
        "denied": False,
        "summary": "\n".join(lines),
        "citations": [{"document": "Nexora change_orders", "document_id": "change_orders", "trust": "system"}],
        "entity_updates": updates,
        "fact_note": f"{scope_label} 关联变更工单 {len(safe_rows)} 条",
    }


def _query_cmdb_base(query: str) -> Dict[str, Any]:
    """Module 6: Sites, VLANs, or Credential metadata (NEVER reads secrets)."""
    q = str(query or "").lower()
    if "凭据" in q or "credential" in q:
        rows = []
        try:
            with get_db_connection() as conn:
                # Strict column whitelist: NEVER select password/private_key/snmp_community.
                raw = conn.execute(
                    "SELECT credential_name, credential_type, account_role, created_at FROM credentials ORDER BY created_at DESC LIMIT 20"
                ).fetchall()
                for r in raw:
                    rows.append((str(r[0] or "-"), str(r[1] or "-"), str(r[2] or "-"), str(r[3] or "-")[:19]))
        except Exception:
            pass
        lines = [
            "## CMDB 凭据目录概览（脱敏只读）",
            f"共登记 **{len(rows)}** 组凭据（仅展示名称与角色元数据，密码/私钥/Community 物理级隔离不读取）。",
        ]
        if rows:
            lines.extend(["", "| 凭据名称 | 类型 | 角色 | 创建时间 |", "|---|---|---|---|"])
            for r in rows:
                lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |")
        lines.append("\n> 数据来源：PostgreSQL `credentials` 元数据（0 Token）。")
        return {
            "module": "credentials_meta",
            "matched_count": len(rows),
            "denied": False,
            "summary": "\n".join(lines),
            "citations": [{"document": "Nexora credentials metadata", "document_id": "credentials", "trust": "system"}],
            "entity_updates": {"last_module": "cmdb_base"},
            "fact_note": f"CMDB 凭据共 {len(rows)} 组",
        }

    # Default: sites overview
    sites = []
    try:
        with get_db_connection() as conn:
            raw = conn.execute(
                "SELECT site_code, site_name, city, status FROM sites ORDER BY site_code LIMIT 30"
            ).fetchall()
            for r in raw:
                sites.append((str(r[0] or "-"), str(r[1] or "-"), str(r[2] or "-"), str(r[3] or "active")))
    except Exception:
        pass
    lines = ["## CMDB 站点目录（本地只读）", f"当前共登记 **{len(sites)}** 个站点。"]
    if sites:
        lines.extend(["", "| 站点编号 | 站点名称 | 城市 | 状态 |", "|---|---|---|---|"])
        for s in sites:
            lines.append(f"| `{s[0]}` | {s[1]} | {s[2]} | {s[3]} |")
    lines.append("\n> 数据来源：PostgreSQL `sites` 只读快照（0 Token）。")
    return {
        "module": "cmdb_base",
        "matched_count": len(sites),
        "denied": False,
        "summary": "\n".join(lines),
        "citations": [{"document": "Nexora sites", "document_id": "sites", "trust": "system"}],
        "entity_updates": {"last_module": "cmdb_base"},
        "fact_note": f"CMDB 站点共 {len(sites)} 个",
    }


def _query_platform_audit() -> Dict[str, Any]:
    """Module 11: Platform user count & recent audit log summary (Admin only)."""
    user_count = 0
    try:
        with get_db_connection() as conn:
            urow = conn.execute("SELECT COUNT(*) FROM users").fetchone()
            if urow:
                user_count = int(urow[0] or 0)
    except Exception:
        pass
    return {
        "module": "platform_audit",
        "matched_count": user_count,
        "denied": False,
        "summary": (
            f"## 平台管理概览（本地只读）\n\n"
            f"- 当前系统登记账号总数：**{user_count}** 个。\n"
            f"- 详细权限变更与系统操作审计请在左侧「平台管理 → 审计日志」中按时间范围检索。\n\n"
            f"> 数据来源：PostgreSQL `users` 只读快照（0 Token）。"
        ),
        "citations": [{"document": "Nexora platform users", "document_id": "users", "trust": "system"}],
        "entity_updates": {"last_module": "platform_audit"},
        "fact_note": f"平台账号 {user_count} 个",
    }


def _query_device_count_summary(query: str, entities: Dict[str, Any]) -> Dict[str, Any]:
    """Concise 0-token CMDB device count & vendor/type/site distribution summary."""
    vendor = str(entities.get("vendor") or "").strip().lower() or None
    role = str(entities.get("role") or "").strip().lower() or None
    status = str(entities.get("status") or "").strip().lower() or None
    if any(m in str(query or "") for m in ("都在线", "全在线", "在线吗", "离线了吗")):
        status = None
    site = str(entities.get("site") or "").strip() or None

    where: List[str] = ["1=1"]
    params: List[Any] = []
    if vendor:
        where.append("LOWER(COALESCE(vendor, '')) = ?")
        params.append(vendor)
    if role:
        where.append("LOWER(COALESCE(role, '')) = ?")
        params.append(role)
    if status:
        if status == "online":
            where.append("LOWER(COALESCE(status, '')) IN ('online', 'up')")
        elif status == "offline":
            where.append("LOWER(COALESCE(status, '')) NOT IN ('online', 'up')")
        else:
            where.append("LOWER(COALESCE(status, '')) = ?")
            params.append(status)
    if site:
        where.append("LOWER(COALESCE(site, '')) = ?")
        params.append(site.lower())

    where_sql = " AND ".join(where)
    rows: List[tuple] = []
    try:
        with get_db_connection() as conn:
            rows = conn.execute(
                f"SELECT hostname, vendor, role, status, site, model FROM devices WHERE {where_sql} ORDER BY hostname ASC",
                tuple(params),
            ).fetchall()
    except Exception as exc:
        logger.warning("Concise device count query failed: %s", type(exc).__name__)
        return {
            "module": "device_count_summary",
            "matched_count": 0,
            "denied": False,
            "summary": "本地 CMDB 设备统计查询暂时失败，请稍后重试。",
            "citations": [{"document": "Nexora CMDB devices", "document_id": "devices", "trust": "system"}],
            "entity_updates": {"last_module": "device_count_summary"},
            "fact_note": "",
        }

    total = len(rows)
    online = sum(1 for r in rows if str(r[3] or "").lower() in {"online", "up"})
    offline = total - online
    scope_parts = [p for p in (vendor.upper() if vendor else None, role, status, site) if p]
    scope_desc = " · ".join(scope_parts) if scope_parts else "全网"

    if total == 0:
        summary = (
            f"当前 **{scope_desc}** 条件下共匹配 **0 台**设备。\n\n"
            f"> 数据来源：PostgreSQL `devices` 只读快照（0 Token）。"
        )
    else:
        from collections import Counter

        v_cnt = Counter(str(r[1] or "未知") for r in rows)
        r_cnt = Counter(str(r[2] or "未知") for r in rows)
        s_cnt = Counter(str(r[4] or "未分配") for r in rows)

        v_str = "、".join(f"{k} {v} 台（{v / total * 100:.1f}%）" for k, v in v_cnt.most_common(6))
        r_str = "、".join(f"{k} {v} 台" for k, v in r_cnt.most_common(6))
        s_str = "、".join(f"{k} {v} 台" for k, v in s_cnt.most_common(6))

        lines = [
            f"当前 **{scope_desc}** 共纳管 **{total} 台**设备（在线 **{online}** 台，离线 **{offline}** 台）：",
            "",
            f"- **厂商分布**：{v_str}",
            f"- **角色分布**：{r_str}",
            f"- **站点分布**：{s_str}",
        ]
        if total <= 10 and scope_parts:
            names = "、".join(f"`{r[0]}`" for r in rows[:10])
            lines.append(f"- **匹配设备**：{names}")
        lines.extend([
            "",
            "> 数据来源：PostgreSQL `devices` 只读快照（0 Token）。如需展开某厂商/站点明细或进一步排查，可直接追问。",
        ])
        summary = "\n".join(lines)

    return {
        "module": "device_count_summary",
        "matched_count": total,
        "denied": False,
        "summary": summary,
        "citations": [{"document": "Nexora CMDB devices", "document_id": "devices", "trust": "system"}],
        "entity_updates": {"last_module": "device_count_summary", "active_device": None},
        "fact_note": f"{scope_desc} 纳管设备 {total} 台（在线 {online} / 离线 {offline}）",
    }


def execute_module_bus_query(
    module: str,
    query: str,
    entities: Dict[str, Any],
    *,
    roles: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Execute a 12-module local read-only query with RBAC enforcement (0 Token)."""
    # Guardrail 2: Ambiguity check
    if entities.get("scope_mode") == "ambiguous":
        cands = entities.get("ambiguous_candidates") or []
        bullet_list = "\n".join(f"- `{c}`" for c in cands)
        return {
            "module": module,
            "matched_count": 0,
            "denied": False,
            "summary": (
                f"## 请确认目标设备\n\n"
                f"上一轮结果包含多个候选设备，为避免查错对象，请指明您要查询哪一台：\n\n"
                f"{bullet_list}\n\n"
                f"> 未调用外部模型（0 Token）。"
            ),
            "citations": [],
            "entity_updates": {},
            "fact_note": "",
        }

    # Guardrail 3: RBAC check
    effective_module = "credentials_meta" if (module == "cmdb_base" and ("凭据" in query.lower() or "credential" in query.lower())) else module
    if not check_module_access(roles, effective_module):
        module_labels = {
            "pam_sessions": "操作工作台（PAM 登录审计）",
            "credentials_meta": "CMDB 凭据目录",
            "platform_audit": "平台管理与系统审计",
        }
        return _denied_response(effective_module, module_labels.get(effective_module, effective_module))

    device = entities.get("device")
    device_hint = (device.get("hostname") if device else None) or entities.get("explicit_ip")

    if module == "overview":
        return _query_overview()
    if module == "device_count_summary":
        return _query_device_count_summary(query, entities)
    if module == "device_profile":
        return _query_device_profile(entities)
    if module == "pam_sessions":
        return _query_pam_sessions(query, entities)
    if module == "racks":
        return _query_racks(entities)
    if module in {"config_drift", "compliance"}:
        return _query_config_drift_or_compliance(module, entities)
    if module == "automation_inspections":
        return _query_automation_inspections(query)
    if module == "change_orders":
        return _query_change_orders(query, entities)
    if module == "cmdb_base":
        return _query_cmdb_base(query)
    if module == "platform_audit":
        return _query_platform_audit()
    if module == "ipam_prefix":
        res = query_ipam_prefix_usage(query, prefix_hint=entities.get("prefix"))
        return {
            "module": "ipam_prefix",
            "matched_count": res["matched_count"],
            "denied": False,
            "summary": res["summary"],
            "citations": res["citations"],
            "entity_updates": {"active_prefix": entities.get("prefix"), "last_module": "ipam_prefix"},
            "fact_note": f"IPAM 匹配 {res['matched_count']} 个网段",
        }
    if module == "topology_neighbors":
        res = query_topology_neighbors(query, device_hint=device_hint)
        # Extract neighbor candidates for Guardrail 2 disambiguation.
        updates: Dict[str, Any] = {"last_module": "topology_neighbors"}
        if device:
            updates["active_device"] = device
        return {
            "module": "topology_neighbors",
            "matched_count": res["matched_count"],
            "denied": False,
            "summary": res["summary"],
            "citations": res["citations"],
            "entity_updates": updates,
            "fact_note": f"{entities.get('scope_label')} 拓扑链路 {res['matched_count']} 条",
        }
    if module == "interface_anomalies":
        res = query_interface_anomalies(query, device_hint=device_hint)
        updates = {"last_module": "interface_anomalies"}
        if device:
            updates["active_device"] = device
        return {
            "module": "interface_anomalies",
            "matched_count": res["matched_count"],
            "denied": False,
            "summary": res["summary"],
            "citations": res["citations"],
            "entity_updates": updates,
            "fact_note": f"{entities.get('scope_label')} 接口匹配 {res['matched_count']} 个",
        }
    if module == "config_changes":
        res = query_recent_config_changes(query, device_hint=device_hint)
        updates = {"last_module": "config_changes"}
        if device:
            updates["active_device"] = device
        return {
            "module": "config_changes",
            "matched_count": res["matched_count"],
            "denied": False,
            "summary": res["summary"],
            "citations": res["citations"],
            "entity_updates": updates,
            "fact_note": f"{entities.get('scope_label')} 近期配置记录 {res['matched_count']} 条",
        }
    if module == "capacity_summary":
        racks_res = _query_racks({"scope_label": entities.get("scope_label") or "全网"})
        ipam_res = query_ipam_prefix_usage(query)
        return {
            "module": "capacity_summary",
            "matched_count": racks_res["matched_count"] + ipam_res["matched_count"],
            "denied": False,
            "summary": racks_res["summary"] + "\n\n---\n\n" + ipam_res["summary"],
            "citations": racks_res["citations"] + ipam_res["citations"],
            "entity_updates": {"last_module": "capacity_summary"},
            "fact_note": "容量概览（机柜 + IPAM）",
        }

    return {
        "module": module,
        "matched_count": 0,
        "denied": False,
        "summary": "## 本地只读查询\n\n暂未匹配到对应模块动作。",
        "citations": [],
        "entity_updates": {},
        "fact_note": "",
    }
