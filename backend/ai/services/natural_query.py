"""
AI Service for Natural Language Asset and Device Information Queries
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from database.core import get_db_connection
from ai.gateway.llm_gateway import llm_gateway
from ai.security.sanitizer import sanitize_data

logger = logging.getLogger(__name__)


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _count_values(values: List[str]) -> Dict[str, int]:
    counts = Counter(value or "(empty)" for value in values)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bucket_table(title: str, key_label: str, buckets: Dict[str, int], total: int) -> List[str]:
    lines = [
        f"### {title}",
        "",
        f"| {key_label} | \u6570\u91cf | \u5360\u6bd4 |",
        "|---|---:|---:|",
    ]
    for key, count in buckets.items():
        ratio = f"{count / total * 100:.1f}%" if total else "-"
        lines.append(f"| {key} | {count} | {ratio} |")
    return lines


def render_asset_analysis(query: str, analysis: Dict[str, Any]) -> str:
    """Render a factual CMDB report without asking an LLM to invent fields."""
    total = int(analysis.get("total_devices", 0))
    lines = [
        "## Nexora CMDB \u8d44\u4ea7\u6838\u5bf9\u7ed3\u679c",
        "",
        f"> \u67e5\u8be2\uff1a{query}",
        f"> \u6570\u636e\u6765\u6e90\uff1aPostgreSQL `devices`/`sites` \u53ca `alert_events` \u53ea\u8bfb\u5feb\u7167\uff1b\u672c\u6b21\u5339\u914d **{total}** \u53f0\u8bbe\u5907\u3002",
        "",
    ]

    lines.extend(_bucket_table("\u4e00\u3001\u5382\u5546\u5206\u5e03", "\u5382\u5546", analysis.get("by_vendor", {}), total))
    lines.extend(["", *_bucket_table("\u4e8c\u3001\u8bbe\u5907\u89d2\u8272\u5206\u5e03", "\u89d2\u8272", analysis.get("by_role", {}), total)])
    lines.extend(["", *_bucket_table("\u4e09\u3001\u8bbe\u5907\u7c7b\u578b\u5206\u5e03", "\u7c7b\u578b", analysis.get("by_type", {}), total)])
    lines.extend(["", *_bucket_table("\u56db\u3001\u533a\u57df\u5206\u5e03", "\u533a\u57df/\u673a\u623f", analysis.get("by_site", {}), total)])

    lines.extend(["", "### \u4e94\u3001\u8f6f\u4ef6\u7248\u672c\u6982\u89c8", "", "| \u5382\u5546 | \u578b\u53f7 | \u7248\u672c | \u6570\u91cf |", "|---|---|---|---:|"])
    for item in analysis.get("by_version", []):
        lines.append(f"| {item['vendor']} | {item['model']} | {item['version']} | {item['count']} |")
    missing_version = analysis.get("data_quality", {}).get("missing_version", 0)
    if missing_version:
        lines.append(f"| \u7248\u672c\u672a\u586b\u5199 | - | - | {missing_version} |")

    health = analysis.get("health", {})
    alerts = analysis.get("alerts", {})
    psu_distribution = ", ".join(
        f"{key} {value}" for key, value in health.get("psu_status", {}).items()
    ) or "\u65e0\u6570\u636e"
    lifecycle_distribution = ", ".join(
        f"{key} {value}" for key, value in analysis.get("by_lifecycle", {}).items()
    ) or "\u65e0\u6570\u636e"
    lines.extend([
        "",
        "### \u516d\u3001\u72b6\u6001\u4e0e\u544a\u8b66\uff08\u4ec5\u57fa\u4e8e\u5b9e\u9645\u5b57\u6bb5\uff09",
        "",
        f"- \u8bbe\u5907\u72b6\u6001\uff1a{health.get('online_devices', 0)} \u53f0 online / {total} \u53f0\u603b\u6570\u3002",
        f"- \u5f53\u524d\u672a\u6062\u590d\u544a\u8b66\uff1a{alerts.get('active_count', 0)} \u6761\uff1b\u6700\u8fd1 24 \u5c0f\u65f6\u65b0\u589e\uff1a{alerts.get('recent_24h_count', 0)} \u6761\u3002",
        f"- CPU \u5feb\u7167\uff1a{health.get('cpu_observed_devices', 0)} \u53f0\u6709\u6570\u503c\uff0c\u6700\u5927\u503c {health.get('max_cpu', '-')}; \u8fd9\u4e0d\u7b49\u4e8e\u5df2\u5224\u5b9a\u4e3a\u8d85\u9608\u503c\u3002",
        f"- PSU \u5b57\u6bb5\u5206\u5e03\uff1a{psu_distribution}\u3002",
    ])

    lines.extend([
        "",
        "### \u4e03\u3001\u6570\u636e\u8d28\u91cf\u548c\u8fb9\u754c",
        "",
        f"- \u751f\u547d\u5468\u671f\u5b57\u6bb5\u5206\u5e03\uff1a{lifecycle_distribution}\u3002",
        "- \u672c\u6b21\u6570\u636e\u6ca1\u6709\u53ef\u7528\u7684\u5382\u5546 EOL \u65e5\u671f\u6216\u751f\u547d\u5468\u671f\u76ee\u5f55\uff0c\u4e0d\u80fd\u4ec5\u51ed\u7248\u672c\u53f7\u5224\u5b9a\u201cEOL\u8bbe\u5907\u201d\u3002",
        f"- \u7248\u672c\u7f3a\u5931\uff1a{missing_version} \u53f0\uff1b\u533a\u57df\u7f3a\u5931\uff1a{analysis.get('data_quality', {}).get('missing_site', 0)} \u53f0\u3002",
    ])

    lines.extend(["", "### \u516b\u3001\u8bbe\u5907\u660e\u7ec6", "", "| \u4e3b\u673a\u540d | \u5382\u5546 | \u578b\u53f7 | \u7248\u672c | \u89d2\u8272 | \u7c7b\u578b | \u533a\u57df | \u72b6\u6001 |", "|---|---|---|---|---|---|---|---|"])
    for item in analysis.get("devices", []):
        lines.append(
            f"| {item['hostname']} | {item['vendor']} | {item['model']} | {item['version']} | "
            f"{item['role']} | {item['device_type']} | {item['site']} | {item['status']} |"
        )

    lines.extend(["", "> \u6ce8\uff1a\u4ee5\u4e0a\u7edf\u8ba1\u7531\u7cfb\u7edf\u5bf9 PostgreSQL \u8fd4\u56de\u8bb0\u5f55\u76f4\u63a5\u805a\u5408\u751f\u6210\uff0c\u6ca1\u6709\u5c06\u672a\u67e5\u5230\u7684\u4fe1\u606f\u5f53\u4f5c\u4e8b\u5b9e\u3002"])
    return "\n".join(lines)


def render_alert_analysis(query: str, analysis: Dict[str, Any]) -> str:
    """Render alert aggregates without exposing alert records."""
    raw_query = str(query or "")
    alerts = analysis.get("alerts") if isinstance(analysis.get("alerts"), dict) else {}
    total = int(alerts.get("total_count", 0) or 0)
    active = int(alerts.get("active_count", 0) or 0)
    recent = int(alerts.get("recent_24h_count", 0) or 0)
    scope = analysis.get("scope") if isinstance(analysis.get("scope"), dict) else {}
    scope_parts = [part for part in (scope.get("vendor"), scope.get("time_range"), scope.get("status")) if part]
    vendor_prefix = f"{scope['vendor']} 设备" if scope.get("vendor") else "当前范围"
    direct_verdict = (
        f"**有告警**：{vendor_prefix}当前共有 **{active}** 条未恢复告警（最近 24 小时新增 **{recent}** 条）。"
        if active > 0
        else f"**无未恢复告警**：{vendor_prefix}当前没有未恢复告警（最近 24 小时共记录 **{recent}** 条历史告警）。"
    )
    lines = [
        "## Nexora 告警查询结果",
        "",
        direct_verdict,
        "",
        "> 数据来源：PostgreSQL `alert_events` 与设备只读快照；不调用外部模型（0 Token）。",
        "",
    ]
    if any(marker in raw_query for marker in ("在线设备", "离线设备", "多少台", "设备数", "设备总数")):
        try:
            with get_db_connection() as conn:
                dev_rows = conn.execute(
                    "SELECT LOWER(COALESCE(status, 'unknown')), COUNT(*) FROM devices GROUP BY 1"
                ).fetchall()
            status_counts = {str(r[0]): int(r[1] or 0) for r in dev_rows}
            total_devs = sum(status_counts.values())
            online_devs = status_counts.get("online", 0) + status_counts.get("up", 0)
            offline_devs = status_counts.get("offline", 0) + status_counts.get("down", 0)
            lines.append(
                f"- 当前纳管设备：**{total_devs}** 台（在线 **{online_devs}** 台，离线 **{offline_devs}** 台）。"
            )
        except Exception as exc:
            logger.debug("Alert summary inventory counts unavailable: %s", type(exc).__name__)
    if scope_parts:
        lines.append(f"- 查询范围：{' · '.join(scope_parts)}，共 **{total}** 条。")
        by_status = alerts.get("by_workflow_status") if isinstance(alerts.get("by_workflow_status"), dict) else {}
        if by_status and not scope.get("status"):
            lines.append("- 按处理状态：" + "，".join(f"{name} {count} 条" for name, count in by_status.items()) + "。")
    lines.extend([
        f"- 当前未恢复告警：**{active}** 条。",
        f"- 最近 24 小时新增告警：**{recent}** 条。",
    ])
    if not scope_parts:
        lines.append(f"- 当前查询范围内告警总数：**{total}** 条。")

    active_by_severity = alerts.get("active_by_severity") if isinstance(alerts.get("active_by_severity"), dict) else {}
    recent_by_severity = alerts.get("recent_24h_by_severity") if isinstance(alerts.get("recent_24h_by_severity"), dict) else {}
    if active_by_severity:
        lines.extend(["", *_bucket_table("当前未恢复告警严重级别", "严重级别", active_by_severity, active)])
    if recent_by_severity:
        lines.extend(["", *_bucket_table("最近 24 小时新增告警严重级别", "严重级别", recent_by_severity, recent)])
    by_severity = alerts.get("by_severity") if isinstance(alerts.get("by_severity"), dict) else {}
    if scope_parts and by_severity and not (by_severity == active_by_severity and total == active):
        lines.extend(["", *_bucket_table("查询范围内告警严重级别", "严重级别", by_severity, total)])
    records = analysis.get("records") if isinstance(analysis.get("records"), list) else []
    if records:
        shown = len(records)
        heading = f"### 告警明细（最新 {shown} 条" + (f"，共 {total} 条" if total > shown else "") + "）"
        lines.extend(["", heading, "", "| 时间 | 级别 | 设备 | 接口 | 告警 | 状态 |", "|---|---|---|---|---|---|"])
        for item in records:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"| {item.get('created_at', '-')} | {item.get('severity', '-')} | {item.get('hostname', '-')} | "
                f"{item.get('interface', '-')} | {item.get('title', '-')} | {item.get('status', '-')} |"
            )
        if total > shown:
            lines.extend(["", "> 完整列表请到「告警中心」按相同条件筛选。"])
    if not total:
        lines.extend(["", "当前查询范围内没有匹配的告警记录。"])
    lines.extend([
        "",
        "> 以上为系统按实际告警字段聚合的只读统计；未查询到的告警不会被补写或推断。",
    ])
    return "\n".join(lines)


def _relative_alert_start(value: Any) -> Optional[datetime]:
    """Parse only an unambiguous bounded relative alert window."""
    window = _alert_time_window(value)
    return window[0] if window else None


_ALERT_WINDOW_ALIASES = {
    "last_24h": "24h", "recent_24h": "24h", "最近24小时": "24h", "最近 24 小时": "24h",
    "过去24小时": "24h", "过去 24 小时": "24h", "今天": "today", "今日": "today",
    "昨天": "yesterday", "昨日": "yesterday", "本周": "this_week", "this week": "this_week",
}
_ALERT_STATUS_LABELS = {
    "unhandled": "未处理（未恢复且未确认）",
    "active": "未恢复",
    "acknowledged": "已确认、未恢复",
    "investigating": "处理中",
    "suppressed": "已屏蔽",
    "resolved": "已恢复",
}
_WORKFLOW_LABELS = {
    "open": "未处理", "acknowledged": "已确认", "investigating": "处理中",
    "suppressed": "已屏蔽", "resolved": "已恢复",
}
ALERT_LIST_LIMIT = 20


def _alert_time_window(value: Any, now: Optional[datetime] = None) -> Optional[tuple[datetime, Optional[datetime], str]]:
    """(start_utc, end_utc or None, label) for a normalised window token.

    Calendar windows (today / yesterday / this week) use the server's local
    timezone, which is the operators' timezone for an on-premises deployment.
    """
    import re

    normalized = " ".join(str(value or "").lower().split())
    normalized = _ALERT_WINDOW_ALIASES.get(normalized, normalized)
    if not normalized:
        return None
    local_now = (now or datetime.now(timezone.utc)).astimezone()
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    if normalized == "today":
        return midnight.astimezone(timezone.utc), None, f"今天（{midnight:%m-%d} 00:00 起）"
    if normalized == "yesterday":
        start = midnight - timedelta(days=1)
        return start.astimezone(timezone.utc), midnight.astimezone(timezone.utc), f"昨天（{start:%m-%d}）"
    if normalized == "this_week":
        start = midnight - timedelta(days=midnight.weekday())
        return start.astimezone(timezone.utc), None, f"本周（{start:%m-%d} 起）"
    match = re.fullmatch(r"(\d{1,3})\s*([hd])", normalized)
    if match:
        amount = int(match.group(1))
        if match.group(2) == "h":
            amount = max(1, min(amount, 720))
            return local_now.astimezone(timezone.utc) - timedelta(hours=amount), None, f"最近 {amount} 小时"
        amount = max(1, min(amount, 90))
        return local_now.astimezone(timezone.utc) - timedelta(days=amount), None, f"最近 {amount} 天"
    return None


def _alert_status_condition(status: Any) -> Optional[str]:
    return {
        "unhandled": "a.resolved_at IS NULL AND COALESCE(a.workflow_status, 'open') = 'open'",
        "active": "a.resolved_at IS NULL",
        "acknowledged": "a.resolved_at IS NULL AND a.workflow_status = 'acknowledged'",
        "investigating": "a.resolved_at IS NULL AND a.workflow_status = 'investigating'",
        "suppressed": "a.resolved_at IS NULL AND a.workflow_status = 'suppressed'",
        "resolved": "a.resolved_at IS NOT NULL",
    }.get(_text(status).lower())


def _format_alert_time(value: Any) -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return _text(value, "-")[:19]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%m-%d %H:%M")


def _table_cell(value: Any, limit: int = 80) -> str:
    text = " ".join(_text(value, "-").split()).replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1] + "…"


class NaturalQueryService:
    """Safely executes structured asset queries based on natural language intent."""

    def search_devices(self, filters: Dict[str, Any], tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search the single-organization device inventory.

        ``tenant_id`` remains accepted for callers on the legacy contract, but
        stored tenant labels no longer partition device visibility.
        """
        del tenant_id
        results = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT id, hostname, ip_address, platform, vendor, model, version, role, site, device_category, status FROM devices WHERE 1 = 1"
                params: list[Any] = []
                
                if filters.get("vendor"):
                    query += " AND LOWER(vendor) LIKE ?"
                    params.append(f"%{filters['vendor'].lower()}%")
                if filters.get("role"):
                    query += " AND LOWER(role) LIKE ?"
                    params.append(f"%{filters['role'].lower()}%")
                if filters.get("status"):
                    query += " AND LOWER(status) = ?"
                    params.append(filters["status"].lower())
                if filters.get("keyword"):
                    query += " AND (LOWER(hostname) LIKE ? OR ip_address LIKE ?)"
                    kw = f"%{filters['keyword'].lower()}%"
                    params.extend([kw, kw])
                
                query += " LIMIT 50"
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
                for r in rows:
                    results.append({
                        "id": r[0], "hostname": r[1], "ip_address": r[2],
                        "platform": r[3], "vendor": r[4], "model": r[5], "version": r[6],
                        "role": r[7], "site": r[8], "device_category": r[9], "status": r[10]
                    })
        except Exception as exc:
            logger.warning("Natural-language device search failed; returning no results code=AI_NATURAL_QUERY_DEVICE_SEARCH_FAILED error=%s", type(exc).__name__)
        return results

    async def execute_asset_analysis(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a deterministic, single-organization CMDB report from PostgreSQL facts."""
        filters = filters or {}
        conditions: list[str] = []
        params: List[Any] = []

        for column in ("vendor", "role", "status", "device_category"):
            value = _text(filters.get(column))
            if value:
                conditions.append(f"LOWER(COALESCE(d.{column}, '')) LIKE ?")
                params.append(f"%{value.lower()}%")

        site_filter = _text(filters.get("site"))
        if site_filter:
            conditions.append("LOWER(COALESCE(s.site_name, s.site_code, d.site, d.site_id, '')) LIKE ?")
            params.append(f"%{site_filter.lower()}%")

        where_clause = " AND ".join(conditions) if conditions else "1 = 1"
        rows: List[Any] = []
        alert_rows: List[Any] = []
        try:
            with get_db_connection() as conn:
                rows = conn.execute(
                    f"""
                    SELECT d.id, d.hostname, d.ip_address, d.vendor, d.model, d.version,
                           d.os_version, d.firmware_version, d.role, d.device_category,
                           d.status, d.site_id, d.site, d.lifecycle_status, d.cpu_usage,
                           d.psu_status,
                           COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''),
                                    NULLIF(d.site, ''), NULLIF(d.site_id, ''), '(unassigned)') AS site_name
                    FROM devices d
                    LEFT JOIN sites s ON s.id = d.site_id OR s.id = d.site
                    WHERE {where_clause}
                    ORDER BY d.hostname
                    """,
                    tuple(params),
                ).fetchall()
                matched_ids_list = sorted({str(_row_value(row, "id")) for row in rows if _row_value(row, "id")})
                if matched_ids_list:
                    placeholders = ", ".join("?" for _ in matched_ids_list)
                    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                    alert_rows = conn.execute(
                        f"""
                        SELECT a.created_at, a.resolved_at, a.severity, a.device_id
                        FROM alert_events a
                        WHERE a.device_id IN ({placeholders})
                          AND (a.resolved_at IS NULL OR a.created_at >= ?)
                        """,
                        (*matched_ids_list, since_24h),
                    ).fetchall()
                else:
                    alert_rows = []
        except Exception as exc:
            logger.exception("Deterministic CMDB asset analysis failed")
            error_analysis = {
                "total_devices": 0,
                "by_vendor": {}, "by_role": {}, "by_type": {}, "by_site": {},
                "by_version": [], "by_lifecycle": {}, "devices": [],
                "alerts": {"active_count": 0, "recent_24h_count": 0},
                "health": {"online_devices": 0, "cpu_observed_devices": 0, "max_cpu": None, "psu_status": {}},
                "data_quality": {"missing_version": 0, "missing_site": 0},
                "error": "CMDB read failed",
            }
            return {
                "query": query,
                "matched_count": 0,
                "data": [],
                "analysis": error_analysis,
                "summary": "## Nexora CMDB \u67e5\u8be2\u5931\u8d25\n\n\u53ea\u8bfb\u6570\u636e\u8bfb\u53d6\u5931\u8d25\uff0c\u672c\u6b21\u672a\u751f\u6210\u8bbe\u5907\u7edf\u8ba1\u3002",
                "error": str(exc),
            }

        matched_device_ids = {str(_row_value(row, "id")) for row in rows}
        alert_rows = [
            row for row in alert_rows
            if str(_row_value(row, "device_id")) in matched_device_ids
        ]

        devices: List[Dict[str, Any]] = []
        for row in rows:
            version = next(
                (value for value in (
                    _text(_row_value(row, "version")),
                    _text(_row_value(row, "os_version")),
                    _text(_row_value(row, "firmware_version")),
                ) if value),
                "(empty)",
            )
            devices.append({
                "id": _row_value(row, "id"),
                "hostname": _text(_row_value(row, "hostname"), "(unnamed)"),
                "ip_address": _text(_row_value(row, "ip_address")),
                "vendor": _text(_row_value(row, "vendor"), "(empty)"),
                "model": _text(_row_value(row, "model"), "(empty)"),
                "version": version,
                "role": _text(_row_value(row, "role"), "(empty)"),
                "device_type": _text(_row_value(row, "device_category"), "(empty)"),
                "site": _text(_row_value(row, "site_name"), "(unassigned)"),
                "site_id": _text(_row_value(row, "site_id")),
                "status": _text(_row_value(row, "status"), "(empty)"),
                "lifecycle_status": _text(_row_value(row, "lifecycle_status"), "(empty)"),
                "cpu_usage": _row_value(row, "cpu_usage"),
                "psu_status": _text(_row_value(row, "psu_status"), "(empty)"),
            })

        total = len(devices)
        by_version_counter = Counter((item["vendor"], item["model"], item["version"]) for item in devices)
        by_version = [
            {"vendor": vendor, "model": model, "version": version, "count": count}
            for (vendor, model, version), count in sorted(
                by_version_counter.items(), key=lambda item: (-item[1], item[0])
            )
            if version != "(empty)"
        ]
        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(hours=24)
        active_alerts = [row for row in alert_rows if not _text(_row_value(row, "resolved_at"))]
        recent_alerts = [
            row for row in alert_rows
            if (created_at := _parse_timestamp(_row_value(row, "created_at"))) is not None
            and created_at >= recent_cutoff
        ]
        cpu_values = [row["cpu_usage"] for row in devices if isinstance(row.get("cpu_usage"), (int, float))]
        analysis = {
            "total_devices": total,
            "by_vendor": _count_values([item["vendor"] for item in devices]),
            "by_role": _count_values([item["role"] for item in devices]),
            "by_type": _count_values([item["device_type"] for item in devices]),
            "by_site": _count_values([item["site"] for item in devices]),
            "by_lifecycle": _count_values([item["lifecycle_status"] for item in devices]),
            "by_version": by_version,
            "devices": devices,
            "health": {
                "online_devices": sum(item["status"].lower() == "online" for item in devices),
                "cpu_observed_devices": len(cpu_values),
                "max_cpu": max(cpu_values) if cpu_values else None,
                "psu_status": _count_values([item["psu_status"] for item in devices]),
            },
            "alerts": {
                "total_count": len(alert_rows),
                "active_count": len(active_alerts),
                "recent_24h_count": len(recent_alerts),
                "active_by_severity": _count_values([_text(_row_value(row, "severity"), "(empty)") for row in active_alerts]),
                "recent_24h_by_severity": _count_values([_text(_row_value(row, "severity"), "(empty)") for row in recent_alerts]),
            },
            "data_quality": {
                "missing_version": sum(item["version"] == "(empty)" for item in devices),
                "missing_site": sum(item["site"] == "(unassigned)" for item in devices),
            },
            "eol_available": False,
            "evidence": [
                {"source_type": "cmdb", "source_id": "devices", "record_count": total},
                {"source_type": "cmdb", "source_id": "sites"},
                {"source_type": "alert_events", "source_id": "alert_events", "record_count": len(alert_rows)},
            ],
        }
        safe_analysis = sanitize_data(analysis)
        return {
            "query": query,
            "matched_count": total,
            "data": sanitize_data(devices),
            "analysis": safe_analysis,
            "summary": render_asset_analysis(query, safe_analysis),
            "citations": [
                {"document": "Nexora CMDB devices", "document_id": "devices", "section": "asset aggregation", "trust": "system"},
                {"document": "Nexora alert events", "document_id": "alert_events", "section": "health and alerts", "trust": "system"},
            ],
        }

    async def execute_alert_analysis(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a deterministic, single-organization alert aggregate from PostgreSQL facts."""
        filters = filters or {}
        conditions: list[str] = []
        params: List[Any] = []

        alarm_id = _text(filters.get("alarm_id"))
        if alarm_id:
            conditions.append("a.id = ?")
            params.append(alarm_id)

        device_id = _text(filters.get("device_id"))
        if device_id:
            conditions.append("a.device_id = ?")
            params.append(device_id)

        device_identifier = _text(filters.get("device_identifier") or filters.get("device_name"))
        if device_identifier and not device_id:
            conditions.append("(d.id = ? OR LOWER(COALESCE(d.hostname, '')) = ?)")
            params.extend([device_identifier, device_identifier.lower()])

        vendor = _text(filters.get("vendor"))
        if vendor:
            conditions.append("LOWER(COALESCE(d.vendor, '')) LIKE ?")
            params.append(f"%{vendor.lower()}%")

        site_filter = _text(filters.get("site"))
        if site_filter:
            conditions.append("LOWER(COALESCE(s.site_name, s.site_code, d.site, d.site_id, '')) LIKE ?")
            params.append(f"%{site_filter.lower()}%")

        window = _alert_time_window(filters.get("time_range"))
        if window is not None:
            conditions.append("a.created_at >= ?")
            params.append(window[0].isoformat())
            if window[1] is not None:
                conditions.append("a.created_at < ?")
                params.append(window[1].isoformat())
        status_filter = _text(filters.get("status")).lower()
        status_condition = _alert_status_condition(status_filter)
        if status_condition:
            conditions.append(f"({status_condition})")

        where_clause = " AND ".join(conditions) if conditions else "1 = 1"
        alert_rows: List[Any] = []
        try:
            with get_db_connection() as conn:
                alert_rows = conn.execute(
                    f"""
                    SELECT a.created_at, a.resolved_at, a.severity, a.device_id,
                           a.workflow_status, a.title, a.interface_name,
                           d.hostname
                    FROM alert_events a
                    JOIN devices d ON d.id = a.device_id
                    LEFT JOIN sites s ON s.id = d.site_id OR s.id = d.site
                    WHERE {where_clause}
                    ORDER BY a.created_at DESC
                    """,
                    tuple(params),
                ).fetchall()
        except Exception as exc:
            logger.exception("Deterministic alert analysis failed")
            error_analysis = {
                "alerts": {
                    "total_count": 0,
                    "active_count": 0,
                    "recent_24h_count": 0,
                    "active_by_severity": {},
                    "recent_24h_by_severity": {},
                },
                "error": "alert_read_failed",
                "evidence": [],
            }
            return {
                "query": query,
                "matched_count": 0,
                "data": [],
                "analysis": error_analysis,
                "summary": "## Nexora 告警查询失败\n\n只读告警数据读取失败，本次未生成告警统计。",
                "error": str(exc),
            }

        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        active_alerts = [row for row in alert_rows if not _text(_row_value(row, "resolved_at"))]
        recent_alerts = [
            row
            for row in alert_rows
            if (created_at := _parse_timestamp(_row_value(row, "created_at"))) is not None
            and created_at >= recent_cutoff
        ]
        analysis = {
            "alerts": {
                "total_count": len(alert_rows),
                "active_count": len(active_alerts),
                "recent_24h_count": len(recent_alerts),
                "active_by_severity": _count_values([
                    _text(_row_value(row, "severity"), "(empty)") for row in active_alerts
                ]),
                "by_severity": _count_values([
                    _text(_row_value(row, "severity"), "(empty)") for row in alert_rows
                ]),
                "by_workflow_status": _count_values([
                    _WORKFLOW_LABELS.get(
                        "resolved" if _text(_row_value(row, "resolved_at")) else _text(_row_value(row, "workflow_status"), "open"),
                        _text(_row_value(row, "workflow_status"), "(empty)"),
                    )
                    for row in alert_rows
                ]),
                "recent_24h_by_severity": _count_values([
                    _text(_row_value(row, "severity"), "(empty)") for row in recent_alerts
                ]),
            },
            "scope": {
                "vendor": vendor.upper() if vendor else "",
                "time_range": window[2] if window else "",
                "status": _ALERT_STATUS_LABELS.get(status_filter, ""),
            },
            # Prefer showing active (unresolved) alerts first so operators asking
            # "华三的设备有告警没有" immediately see the actual active alarms.
            "records": [
                {
                    "created_at": _format_alert_time(_row_value(row, "created_at")),
                    "severity": _table_cell(_row_value(row, "severity"), 16),
                    "hostname": _table_cell(_row_value(row, "hostname"), 40),
                    "interface": _table_cell(_row_value(row, "interface_name"), 32),
                    "title": _table_cell(_row_value(row, "title"), 80),
                    "status": "已恢复" if _text(_row_value(row, "resolved_at")) else _WORKFLOW_LABELS.get(
                        _text(_row_value(row, "workflow_status"), "open"), _text(_row_value(row, "workflow_status"))
                    ),
                }
                for row in (active_alerts + [r for r in alert_rows if _text(_row_value(r, "resolved_at"))])[:ALERT_LIST_LIMIT]
            ],
            "evidence": [
                {"source_type": "alert_events", "source_id": "alert_events", "record_count": len(alert_rows)},
            ],
        }
        safe_analysis = sanitize_data(analysis)
        return {
            "query": query,
            "matched_count": len(alert_rows),
            # The alert route is aggregate-only; do not return alert/device
            # records to the Assistant or to a provider context.
            "data": [],
            "analysis": safe_analysis,
            "summary": render_alert_analysis(query, safe_analysis),
            "citations": [
                {"document": "Nexora alert events", "document_id": "alert_events", "section": "alert aggregation", "trust": "system"},
            ],
        }

    async def execute_query(self, query: str, filters: Dict[str, Any], user_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        # Perform safe parameterized database query
        device_facts = self.search_devices(filters, tenant_id=tenant_id)
        sanitized_facts = sanitize_data(device_facts)

        sys_prompt = (
            "You are a network asset management assistant for Nexora. "
            "Given the actual facts queried from the Nexora database, summarize the answer to the user in a clear, concise manner."
        )
        user_prompt = f"User Question: {query}\nDatabase Facts:\n{json.dumps(sanitized_facts, ensure_ascii=False)}"
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        res = await llm_gateway.chat(
            scene="natural_query",
            messages=messages,
            user_id=user_id,
            # CMDB facts may contain hostnames and management IPs.  Keep the
            # provider boundary at INTERNAL while allowing the security
            # gateway to tokenize those identifiers before egress.
            data_classification="INTERNAL",
        )

        return {
            "query": query,
            "matched_count": len(device_facts),
            "data": sanitized_facts,
            "summary": res.get("content", ""),
            "request_id": res.get("request_id")
        }


natural_query_service = NaturalQueryService()
