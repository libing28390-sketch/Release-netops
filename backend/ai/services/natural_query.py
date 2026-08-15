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


class NaturalQueryService:
    """Safely executes structured asset queries based on natural language intent."""

    def search_devices(self, filters: Dict[str, Any], tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        results = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT id, hostname, ip_address, platform, vendor, model, version, role, site, device_category, status FROM devices WHERE (tenant_id = ? OR tenant_id IS NULL)"
                params = [tenant_id or "tenant-default"]
                
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
        except Exception:
            pass
        return results

    async def execute_asset_analysis(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a deterministic, tenant-scoped CMDB report from PostgreSQL facts."""
        filters = filters or {}
        effective_tenant = tenant_id or "tenant-default"
        conditions = ["(d.tenant_id = ? OR d.tenant_id IS NULL)"]
        params: List[Any] = [effective_tenant]

        for column in ("vendor", "role", "status", "device_category"):
            value = _text(filters.get(column))
            if value:
                conditions.append(f"LOWER(COALESCE(d.{column}, '')) LIKE ?")
                params.append(f"%{value.lower()}%")

        site_filter = _text(filters.get("site"))
        if site_filter:
            conditions.append("LOWER(COALESCE(s.site_name, s.site_code, d.site, d.site_id, '')) LIKE ?")
            params.append(f"%{site_filter.lower()}%")

        where_clause = " AND ".join(conditions)
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
                alert_rows = conn.execute(
                    """
                    SELECT a.created_at, a.resolved_at, a.severity, a.device_id
                    FROM alert_events a
                    LEFT JOIN devices d ON d.id = a.device_id
                    WHERE (d.tenant_id = ? OR d.tenant_id IS NULL)
                    """,
                    (effective_tenant,),
                ).fetchall()
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
            user_id=user_id
        )

        return {
            "query": query,
            "matched_count": len(device_facts),
            "data": sanitized_facts,
            "summary": res.get("content", ""),
            "request_id": res.get("request_id")
        }


natural_query_service = NaturalQueryService()
