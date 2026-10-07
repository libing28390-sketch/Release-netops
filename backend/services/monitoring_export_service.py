"""Monitoring export and tabular reporting service.

Combines CMDB metadata (devices, interfaces, sites, vendors) from PostgreSQL with
live telemetry metrics (traffic bps, utilization %, error/discard rates, CPU/memory)
from VictoriaMetrics / local rollups into:
1. Structured JSON data with KPI aggregations, items, and multi-dimensional filter options
2. Enterprise-grade multi-sheet Excel (.xlsx) workbooks
3. UTF-8 BOM CSV files for universal compatibility
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from database import get_db_connection
from services.metric_provider import VictoriaMetricsMetricProvider

logger = logging.getLogger(__name__)

HEADER_FILL = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
HEADER_FONT = Font(name="Microsoft YaHei", size=11, bold=True, color="FFFFFF")
ZEBRA_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
ALERT_FILL = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")  # soft red
WARN_FILL = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")   # soft yellow
GOOD_FILL = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")   # soft green

THIN_BORDER = Border(
    left=Side(style="thin", color="CBD5E1"),
    right=Side(style="thin", color="CBD5E1"),
    top=Side(style="thin", color="CBD5E1"),
    bottom=Side(style="thin", color="CBD5E1"),
)
CENTER_ALIGN = Alignment(horizontal="center", vertical="center")
LEFT_ALIGN = Alignment(horizontal="left", vertical="center")
RIGHT_ALIGN = Alignment(horizontal="right", vertical="center")


def _format_speed(bps: int | float | None) -> str:
    if not bps or bps <= 0:
        return "--"
    if bps >= 100_000_000_000:
        return f"{bps / 1_000_000_000:.0f}G"
    if bps >= 10_000_000_000:
        return f"{bps / 1_000_000_000:.0f}G"
    if bps >= 1_000_000_000:
        return f"{bps / 1_000_000_000:.1f}G"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.0f}M"
    return f"{bps:.0f} bps"


def _format_bps(bps: int | float | None) -> str:
    if bps is None:
        return "—"
    if bps == 0:
        return "0 bps"
    if bps >= 1_000_000_000:
        return f"{bps / 1_000_000_000:.2f} Gbps"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    if bps >= 1_000:
        return f"{bps / 1_000:.1f} Kbps"
    return f"{bps:.0f} bps"


class _InstantMetricMap(dict[str, float]):
    def __init__(self) -> None:
        super().__init__()
        self.sample_times: dict[str, str] = {}


def _query_vm_instant_safe(query: str) -> _InstantMetricMap:
    """Execute PromQL instant query against VictoriaMetrics, return {key: value} mapping."""
    mapping = _InstantMetricMap()
    try:
        vm = VictoriaMetricsMetricProvider(timeout_seconds=1.0)
        res = vm._request("/api/v1/query", {"query": query})
        result_items = res.get("data", {}).get("result", [])
        for item in result_items:
            metric = item.get("metric", {})
            value_pair = item.get("value", [])
            if len(value_pair) <= 1:
                continue
            val = float(value_pair[1])
            sample_time = None
            try:
                sample_time = datetime.fromtimestamp(float(value_pair[0]), tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OverflowError, OSError):
                pass
            h = metric.get("hostname") or metric.get("instance", "")
            asset_id = str(metric.get("asset_id") or metric.get("nexora_asset_id") or "").strip()
            if_index = str(metric.get("ifIndex") or "").strip()
            if_name = str(metric.get("ifName") or metric.get("ifname") or "").strip()
            keys: list[str] = []
            if asset_id:
                keys.append(f"asset:{asset_id}")
                if if_index:
                    keys.append(f"asset:{asset_id}:ifindex:{if_index}")
                if if_name:
                    keys.append(f"asset:{asset_id}:ifname:{if_name.casefold()}")
            if h:
                keys.append(f"hostname:{h}")
                if if_index:
                    keys.append(f"hostname:{h}:ifindex:{if_index}")
                if if_name:
                    keys.append(f"hostname:{h}:ifname:{if_name.casefold()}")
            for key in keys:
                mapping[key] = val
                if sample_time:
                    mapping.sample_times[key] = sample_time
        return mapping
    except Exception as exc:
        logger.debug("VictoriaMetrics instant query skipped or unavailable: %s", exc)
        return {}


def _style_worksheet(ws: Any, headers: list[str], rows: list[list[Any]], *, align_specs: list[str] | None = None) -> None:
    """Apply styling, freeze panes, borders, and auto-fit column widths to a worksheet."""
    ws.views.sheetView[0].showGridLines = True
    ws.freeze_panes = "A2"

    # Header Row
    ws.append(headers)
    ws.row_dimensions[1].height = 26
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = CENTER_ALIGN
        cell.border = THIN_BORDER

    # Data Rows
    for row_idx, row_data in enumerate(rows, start=2):
        ws.append(row_data)
        ws.row_dimensions[row_idx].height = 20
        is_zebra = (row_idx % 2 == 0)
        for col_idx, val in enumerate(row_data, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = THIN_BORDER
            cell.font = Font(name="Microsoft YaHei", size=10)
            if is_zebra:
                cell.fill = ZEBRA_FILL

            align = align_specs[col_idx - 1] if align_specs and col_idx - 1 < len(align_specs) else "center"
            if align == "left":
                cell.alignment = LEFT_ALIGN
            elif align == "right":
                cell.alignment = RIGHT_ALIGN
            else:
                cell.alignment = CENTER_ALIGN

    # Auto-fit column width
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            char_len = sum(2 if ord(c) > 127 else 1 for c in val_str)
            if char_len > max_len:
                max_len = char_len
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)


def fetch_interfaces_report_data(
    *,
    conn: Any = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch structured interfaces data with telemetry rates, KPI aggregations and filter options."""
    filters = filters or {}
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    try:
        tenant_id = str(filters.get("tenant_id") or "").strip()
        tenant_filter = "WHERE COALESCE(d.tenant_id, 'tenant-default') = ?" if tenant_id else ""
        query = f"""
            SELECT i.id, i.device_id, i.if_index, i.interface_name, i.description, i.admin_status,
                   i.oper_status, i.speed, i.mac_address,
                   d.hostname, d.ip_address, d.vendor, d.role,
                   COALESCE(s.site_name, d.site, '默认站点') as site_name
              FROM interfaces i
              JOIN devices d ON i.device_id = d.id
              LEFT JOIN sites s ON d.site_id = s.id
              {tenant_filter}
             ORDER BY d.hostname, i.interface_name
        """
        rows = conn.execute(query, (tenant_id,) if tenant_id else ()).fetchall()
    finally:
        if should_close:
            conn.close()

    in_bps_map = _query_vm_instant_safe("rate(ifHCInOctets[5m]) * 8")
    out_bps_map = _query_vm_instant_safe("rate(ifHCOutOctets[5m]) * 8")
    in_err_map = _query_vm_instant_safe("rate(ifInErrors[5m])")
    out_err_map = _query_vm_instant_safe("rate(ifOutErrors[5m])")
    in_disc_map = _query_vm_instant_safe("rate(ifInDiscards[5m])")
    out_disc_map = _query_vm_instant_safe("rate(ifOutDiscards[5m])")
    if_oper_map = _query_vm_instant_safe("ifOperStatus")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    all_items: list[dict[str, Any]] = []
    vendors_set: set[str] = set()
    sites_set: set[str] = set()
    roles_set: set[str] = set()

    for r in rows:
        hostname = r["hostname"] or "Unknown"
        ip = r["ip_address"] or "--"
        vendor = r["vendor"] or "Other"
        role = r["role"] or "Access"
        site = r["site_name"] or "默认站点"
        ifname = r["interface_name"] or "--"
        desc = r["description"] or ""
        admin = str(r["admin_status"] or "").strip().upper()
        oper = str(r["oper_status"] or "").strip().upper()

        # If oper is unknown or empty, infer from VictoriaMetrics ifOperStatus or admin_status
        if not oper or oper in ("UNKNOWN", "--", "-", "NONE"):
            try:
                interface_index = str(r["if_index"] or "").strip()
            except (KeyError, IndexError):
                interface_index = ""
            lookup_keys = (
                [f"asset:{r['device_id']}:ifindex:{interface_index}"] if interface_index else []
            )
            lookup_keys.append(f"asset:{r['device_id']}:ifname:{ifname.casefold()}")
            vm_oper_val = next((if_oper_map[k] for k in lookup_keys if k in if_oper_map), None)
            if vm_oper_val is not None:
                oper = "UP" if int(vm_oper_val) == 1 else "DOWN"
            elif admin in ("DOWN", "ADM", "ADMINISTRATIVELY DOWN", "DISABLED"):
                oper = "DOWN"
            elif admin == "UP":
                oper = "UP"
            else:
                oper = "UNKNOWN"

        if not admin or admin in ("UNKNOWN", "--", "-", "NONE"):
            admin = oper if oper in ("UP", "DOWN") else "UNKNOWN"

        speed = int(r["speed"]) if r["speed"] and str(r["speed"]).isdigit() else 1_000_000_000

        if vendor:
            vendors_set.add(vendor)
        if site:
            sites_set.add(site)
        if role:
            roles_set.add(role)

        asset_id = str(r["device_id"] or "")
        try:
            if_index = str(r["if_index"] or "").strip()
        except (KeyError, IndexError):
            if_index = ""
        interface_keys = [f"asset:{asset_id}:ifindex:{if_index}"] if asset_id and if_index else []
        if asset_id:
            interface_keys.append(f"asset:{asset_id}:ifname:{ifname.casefold()}")

        def metric_value(metric_map: _InstantMetricMap) -> float | None:
            return next((metric_map[key] for key in interface_keys if key in metric_map), None)

        in_bps = metric_value(in_bps_map)
        out_bps = metric_value(out_bps_map)
        in_pct = round((in_bps / speed) * 100, 2) if in_bps is not None and speed > 0 else None
        out_pct = round((out_bps / speed) * 100, 2) if out_bps is not None and speed > 0 else None
        utilization_values = [value for value in (in_pct, out_pct) if value is not None]
        max_pct = max(utilization_values) if utilization_values else None

        in_err = metric_value(in_err_map)
        out_err = metric_value(out_err_map)
        in_disc = metric_value(in_disc_map)
        out_disc = metric_value(out_disc_map)
        error_values = [value for value in (in_err, out_err, in_disc, out_disc) if value is not None]
        total_err = sum(error_values) if error_values else None
        measured_at = [
            getattr(metric_map, 'sample_times', {}).get(key)
            for metric_map in (in_bps_map, out_bps_map, in_err_map, out_err_map, in_disc_map, out_disc_map)
            for key in interface_keys
            if key in getattr(metric_map, 'sample_times', {})
        ]
        sample_time = max(measured_at) if measured_at else None
        sample_quality = "current" if sample_time else "no_data"

        if max_pct is not None and max_pct >= 85.0:
            level = "CRITICAL"
            advice = "立即排查异常突发流量并考虑扩容或链路分流"
        elif max_pct is not None and max_pct >= 70.0:
            level = "WARNING"
            advice = "持续观察峰值持续时间，检查是否有大文件传输或环路"
        elif max_pct is not None and max_pct >= 50.0:
            level = "NOTICE"
            advice = "利用率偏高，保持例行业务监控"
        elif max_pct is None:
            level = "NO_DATA"
            advice = "当前没有有效接口遥测样本，请检查采集状态"
        else:
            level = "NORMAL"
            advice = "负荷正常"

        health = (
            "不可用" if total_err is None and max_pct is None
            else "异常/物理链路" if total_err is not None and total_err > 10
            else "偶发错包" if total_err is not None and total_err > 0
            else "健康正常"
        )

        item = {
            "id": str(r["id"] or f"{hostname}-{ifname}"),
            "device_id": str(r["device_id"] or ""),
            "hostname": hostname,
            "ip_address": ip,
            "vendor": vendor,
            "role": role,
            "site_name": site,
            "interface_name": ifname,
            "description": desc,
            "admin_status": admin,
            "oper_status": oper,
            "speed": speed,
            "speed_str": _format_speed(speed),
            "in_bps": in_bps,
            "out_bps": out_bps,
            "in_bps_str": _format_bps(in_bps),
            "out_bps_str": _format_bps(out_bps),
            "in_util": in_pct,
            "out_util": out_pct,
            "max_util": max_pct,
            "in_errors": in_err,
            "out_errors": out_err,
            "in_discards": in_disc,
            "out_discards": out_disc,
            "total_errors": total_err,
            "health_status": health,
            "alert_level": level,
            "advice": advice,
            "sample_quality": sample_quality,
            "sample_time": sample_time,
        }
        all_items.append(item)

    # Filter logic
    filtered = all_items
    kw = (filters.get("keyword") or "").strip().lower()
    if kw:
        filtered = [
            x for x in filtered
            if kw in x["hostname"].lower()
            or kw in x["ip_address"].lower()
            or kw in x["interface_name"].lower()
            or kw in x["description"].lower()
            or kw in x["vendor"].lower()
        ]

    vendor_flt = filters.get("vendor")
    if vendor_flt and vendor_flt != "all":
        filtered = [x for x in filtered if x["vendor"] == vendor_flt]

    site_flt = filters.get("site")
    if site_flt and site_flt != "all":
        filtered = [x for x in filtered if x["site_name"] == site_flt]

    role_flt = filters.get("role")
    if role_flt and role_flt != "all":
        filtered = [x for x in filtered if x["role"] == role_flt]

    status_flt = filters.get("status")
    if status_flt and status_flt != "all":
        filtered = [x for x in filtered if x["oper_status"].upper() == status_flt.upper()]

    min_util = filters.get("min_util")
    if min_util is not None and str(min_util) != "":
        try:
            m_val = float(min_util)
            filtered = [x for x in filtered if x["max_util"] is not None and x["max_util"] >= m_val]
        except ValueError:
            pass

    has_errors_flt = filters.get("has_errors")
    if has_errors_flt is True or str(has_errors_flt).lower() in ("true", "1", "yes"):
        filtered = [x for x in filtered if x["total_errors"] is not None and x["total_errors"] > 0]

    # Global & filtered KPIs
    up_cnt = sum(1 for x in filtered if x["oper_status"] == "UP")
    down_cnt = sum(1 for x in filtered if x["oper_status"] == "DOWN")
    unknown_cnt = sum(1 for x in filtered if x["oper_status"] not in {"UP", "DOWN"})
    high_util_cnt = sum(1 for x in filtered if x["max_util"] is not None and x["max_util"] >= 70.0)
    critical_cnt = sum(1 for x in filtered if x["max_util"] is not None and x["max_util"] >= 85.0)
    err_cnt = sum(1 for x in filtered if x["total_errors"] is not None and x["total_errors"] > 0)
    available_util = [x["max_util"] for x in filtered if x["max_util"] is not None]
    avg_util = round(sum(available_util) / len(available_util), 2) if available_util else None

    return {
        "report_type": "interfaces",
        "summary": {
            "total_interfaces": len(filtered),
            "up_interfaces": up_cnt,
            "down_interfaces": down_cnt,
            "unknown_interfaces": unknown_cnt,
            "high_util_count": high_util_cnt,
            "critical_util_count": critical_cnt,
            "error_interfaces_count": err_cnt,
            "avg_utilization": avg_util,
            "no_data_interfaces": sum(1 for x in filtered if x["sample_quality"] == "no_data"),
        },
        "options": {
            "vendors": sorted(list(vendors_set)),
            "sites": sorted(list(sites_set)),
            "roles": sorted(list(roles_set)),
        },
        "items": filtered,
        "total": len(filtered),
        "generated_at": now_str,
    }


def fetch_devices_report_data(
    *,
    conn: Any = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch structured devices resource data with telemetry CPU/memory and filter options."""
    filters = filters or {}
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    try:
        tenant_id = str(filters.get("tenant_id") or "").strip()
        tenant_filter = "WHERE COALESCE(d.tenant_id, 'tenant-default') = ?" if tenant_id else ""
        query = f"""
            SELECT d.id, d.hostname, d.ip_address, d.vendor, d.platform, d.role, d.status,
                   d.cpu_usage, d.memory_usage, d.temp as temperature,
                   COALESCE(s.site_name, d.site, '默认站点') as site_name
              FROM devices d
              LEFT JOIN sites s ON d.site_id = s.id
              {tenant_filter}
             ORDER BY d.hostname
        """
        rows = conn.execute(query, (tenant_id,) if tenant_id else ()).fetchall()
    finally:
        if should_close:
            conn.close()

    cpu_map = _query_vm_instant_safe("cpu_usage_percent or cpmCPUTotal1minRev or hh3cEntityExtCpuUsage or hwEntityCpuUsage or ruijieCpuCostRate")
    mem_map = _query_vm_instant_safe("memory_usage_percent or hh3cEntityExtMemUsage or hwEntityMemUsage or ruijieMemoryPoolCurrentUtilization")
    temp_map = _query_vm_instant_safe("temperature_celsius or hh3cEntityExtTemperature or hwEntityTemperature")

    hostname_counts: dict[str, int] = {}
    for row in rows:
        hostname_key = str(row["hostname"] or "").strip()
        if hostname_key:
            hostname_counts[hostname_key] = hostname_counts.get(hostname_key, 0) + 1

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    all_items: list[dict[str, Any]] = []
    vendors_set: set[str] = set()
    sites_set: set[str] = set()
    roles_set: set[str] = set()

    for r in rows:
        h = r["hostname"] or "Unknown"
        ip = r["ip_address"] or "--"
        vendor = r["vendor"] or "Other"
        platform = r["platform"] or "--"
        role = r["role"] or "Access"
        site = r["site_name"] or "默认站点"
        status = (r["status"] or "online").upper()

        if vendor:
            vendors_set.add(vendor)
        if site:
            sites_set.add(site)
        if role:
            roles_set.add(role)

        asset_key = f"asset:{r['id']}"
        legacy_host_key = f"hostname:{h}" if hostname_counts.get(h) == 1 else ""

        def current_value(metric_map: _InstantMetricMap) -> float | None:
            if asset_key in metric_map:
                return metric_map[asset_key]
            return metric_map.get(legacy_host_key) if legacy_host_key else None

        cpu_live = current_value(cpu_map)
        mem_live = current_value(mem_map)
        temp_live = current_value(temp_map)
        cpu_snapshot = float(r["cpu_usage"]) if r["cpu_usage"] is not None else None
        mem_snapshot = float(r["memory_usage"]) if r["memory_usage"] is not None else None
        temp_snapshot = float(r["temperature"]) if r["temperature"] is not None else None
        cpu = cpu_live if cpu_live is not None else cpu_snapshot
        mem = mem_live if mem_live is not None else mem_snapshot
        temp = temp_live if temp_live is not None else temp_snapshot
        live_values = [value for value in (cpu_live, mem_live) if value is not None]
        has_snapshot = any(value is not None for value in (cpu_snapshot, mem_snapshot, temp_snapshot))
        sample_quality = (
            "current" if cpu_live is not None and mem_live is not None
            else "partial" if live_values
            else "stale" if has_snapshot
            else "no_data"
        )
        sample_times = [
            getattr(metric_map, 'sample_times', {})[key]
            for metric_map in (cpu_map, mem_map, temp_map)
            for key in (asset_key, legacy_host_key)
            if key and key in getattr(metric_map, 'sample_times', {})
        ]
        sample_time = max(sample_times) if sample_times else None
        temp_str = f"{temp:.1f} °C" if temp is not None else "--"

        if sample_quality == "stale":
            risk = "STALE"
            advice = "仅有 CMDB 缓存值，当前没有有效实时资源样本"
        elif sample_quality == "no_data":
            risk = "NO_DATA"
            advice = "当前没有有效资源样本，请检查设备采集状态"
        elif (cpu_live is not None and cpu_live >= 85.0) or (mem_live is not None and mem_live >= 90.0):
            risk = "CRITICAL"
            advice = "立即排查路由抖动、异常进程或内存泄露"
        elif (cpu_live is not None and cpu_live >= 70.0) or (mem_live is not None and mem_live >= 75.0):
            risk = "WARNING"
            advice = "负荷偏高，排查是否有大流量洪泛或周期脚本"
        else:
            risk = "NORMAL"
            advice = "运行平稳"

        all_items.append({
            "id": str(r["id"] or h),
            "hostname": h,
            "ip_address": ip,
            "vendor": vendor,
            "platform": platform,
            "role": role,
            "site_name": site,
            "status": status,
            "cpu_usage": round(cpu, 1) if cpu is not None else None,
            "memory_usage": round(mem, 1) if mem is not None else None,
            "temperature": round(temp, 1) if temp is not None else None,
            "temperature_str": temp_str,
            "risk_level": risk,
            "advice": advice,
            "sample_quality": sample_quality,
            "sample_time": sample_time,
            "metric_sources": {
                "cpu_usage": "victoriametrics" if cpu_live is not None else "cmdb_snapshot" if cpu_snapshot is not None else "none",
                "memory_usage": "victoriametrics" if mem_live is not None else "cmdb_snapshot" if mem_snapshot is not None else "none",
                "temperature": "victoriametrics" if temp_live is not None else "cmdb_snapshot" if temp_snapshot is not None else "none",
            },
        })

    # Filtering
    filtered = all_items
    kw = (filters.get("keyword") or "").strip().lower()
    if kw:
        filtered = [
            x for x in filtered
            if kw in x["hostname"].lower()
            or kw in x["ip_address"].lower()
            or kw in x["platform"].lower()
            or kw in x["vendor"].lower()
        ]

    vendor_flt = filters.get("vendor")
    if vendor_flt and vendor_flt != "all":
        filtered = [x for x in filtered if x["vendor"] == vendor_flt]

    site_flt = filters.get("site")
    if site_flt and site_flt != "all":
        filtered = [x for x in filtered if x["site_name"] == site_flt]

    role_flt = filters.get("role")
    if role_flt and role_flt != "all":
        filtered = [x for x in filtered if x["role"] == role_flt]

    status_flt = filters.get("status")
    if status_flt and status_flt != "all":
        filtered = [x for x in filtered if x["status"].upper() == status_flt.upper()]

    high_load_only = filters.get("high_load_only")
    if high_load_only is True or str(high_load_only).lower() in ("true", "1", "yes"):
        filtered = [
            x for x in filtered
            if (x["metric_sources"]["cpu_usage"] == "victoriametrics" and x["cpu_usage"] is not None and x["cpu_usage"] >= 70.0)
            or (x["metric_sources"]["memory_usage"] == "victoriametrics" and x["memory_usage"] is not None and x["memory_usage"] >= 75.0)
        ]

    online_cnt = sum(1 for x in filtered if x["status"] == "ONLINE")
    offline_cnt = sum(1 for x in filtered if x["status"] != "ONLINE")
    current_cpu = [x["cpu_usage"] for x in filtered if x["metric_sources"]["cpu_usage"] == "victoriametrics"]
    current_mem = [x["memory_usage"] for x in filtered if x["metric_sources"]["memory_usage"] == "victoriametrics"]
    high_cpu_cnt = sum(1 for value in current_cpu if value is not None and value >= 70.0)
    high_mem_cnt = sum(1 for value in current_mem if value is not None and value >= 75.0)
    avg_cpu = round(sum(current_cpu) / len(current_cpu), 1) if current_cpu else None
    avg_mem = round(sum(current_mem) / len(current_mem), 1) if current_mem else None

    return {
        "report_type": "devices",
        "summary": {
            "total_devices": len(filtered),
            "online_devices": online_cnt,
            "offline_devices": offline_cnt,
            "high_cpu_count": high_cpu_cnt,
            "high_mem_count": high_mem_cnt,
            "avg_cpu": avg_cpu,
            "avg_mem": avg_mem,
            "no_data_devices": sum(1 for x in filtered if x["sample_quality"] == "no_data"),
            "stale_devices": sum(1 for x in filtered if x["sample_quality"] == "stale"),
        },
        "options": {
            "vendors": sorted(list(vendors_set)),
            "sites": sorted(list(sites_set)),
            "roles": sorted(list(roles_set)),
        },
        "items": filtered,
        "total": len(filtered),
        "generated_at": now_str,
    }


def fetch_outbound_report_data(
    *,
    conn: Any = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch probe configuration with the latest real result and recent loss."""
    filters = filters or {}
    tenant_id = str(filters.get("tenant_id") or "").strip()
    recent_cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    where = "WHERE COALESCE(t.tenant_id, 'tenant-default') = ?" if tenant_id else ""
    params: tuple[Any, ...] = (recent_cutoff, tenant_id) if tenant_id else (recent_cutoff,)
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    try:
        targets = conn.execute(
            f"""
            WITH latest AS (
                SELECT DISTINCT ON (target_id)
                       target_id, sampled_at, success, latency_ms, error_type
                  FROM outbound_probe_results
                 ORDER BY target_id, sampled_at DESC, id DESC
            ), recent AS (
                SELECT target_id, COUNT(*) AS sample_count,
                       SUM(CASE WHEN success IS TRUE THEN 1 ELSE 0 END) AS success_count
                  FROM outbound_probe_results
                 WHERE sampled_at >= ?
                 GROUP BY target_id
            )
            SELECT t.id, t.target_name AS name, t.probe_type AS target_type,
                   t.host AS target, COALESCE(t.group_name, '默认分组') AS isp,
                   COALESCE(t.enabled, t.is_active, FALSE) AS is_active,
                   latest.sampled_at, latest.success, latest.latency_ms,
                   latest.error_type, COALESCE(recent.sample_count, 0) AS sample_count,
                   COALESCE(recent.success_count, 0) AS success_count
              FROM outbound_probe_targets t
              LEFT JOIN latest ON latest.target_id = t.id
              LEFT JOIN recent ON recent.target_id = t.id
              {where}
             ORDER BY t.target_name
            """,
            params,
        ).fetchall()
    finally:
        if should_close:
            conn.close()

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    stale_after_seconds = 300
    all_items: list[dict[str, Any]] = []
    isps_set: set[str] = set()

    for row in targets:
        item = dict(row)
        name = item.get("name") or "未命名探针"
        isp = item.get("isp") or "综合出口"
        sampled_at = item.get("sampled_at")
        parsed_at = None
        if sampled_at:
            try:
                parsed_at = datetime.fromisoformat(str(sampled_at).replace("Z", "+00:00"))
                if parsed_at.tzinfo is None:
                    parsed_at = parsed_at.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                parsed_at = None
        active = bool(item.get("is_active"))
        is_stale = parsed_at is None or (now - parsed_at.astimezone(timezone.utc)).total_seconds() > stale_after_seconds
        sample_count = int(item.get("sample_count") or 0)
        success_count = int(item.get("success_count") or 0)
        packet_loss = round((sample_count - success_count) / sample_count * 100, 2) if sample_count else None
        latency = float(item["latency_ms"]) if item.get("success") and item.get("latency_ms") is not None else None

        if not active:
            status, sample_quality, grade = "DISABLED", "disabled", "已禁用"
        elif parsed_at is None:
            status, sample_quality, grade = "NO_DATA", "no_data", "无采样"
        elif is_stale:
            status, sample_quality, grade = "STALE", "stale", "采样过期"
        elif not bool(item.get("success")):
            status, sample_quality, grade = "DEGRADED", "failed", "探测失败"
        else:
            status, sample_quality, grade = "NORMAL", "current", "采样成功"

        if isp:
            isps_set.add(str(isp))
        all_items.append({
            "id": str(item.get("id") or name),
            "name": str(name),
            "target_type": str(item.get("target_type") or "ICMP").upper(),
            "target": item.get("target") or "—",
            "isp": str(isp),
            "is_active": active,
            "active_str": "启用" if active else "禁用",
            "latency_ms": latency,
            "packet_loss": packet_loss,
            "health_grade": grade,
            "status": status,
            "sample_quality": sample_quality,
            "sample_time": parsed_at.astimezone(timezone.utc).isoformat() if parsed_at else None,
            "error_type": item.get("error_type"),
            "recent_sample_count": sample_count,
        })

    # Filtering
    filtered = all_items
    kw = (filters.get("keyword") or "").strip().lower()
    if kw:
        filtered = [
            x for x in filtered
            if kw in x["name"].lower()
            or kw in x["target"].lower()
            or kw in x["isp"].lower()
        ]

    isp_flt = filters.get("isp")
    if isp_flt and isp_flt != "all":
        filtered = [x for x in filtered if x["isp"] == isp_flt]

    ttype_flt = filters.get("target_type")
    if ttype_flt and ttype_flt != "all":
        filtered = [x for x in filtered if x["target_type"] == ttype_flt]

    active_cnt = sum(1 for x in filtered if x["is_active"])
    measured_latency = [x["latency_ms"] for x in filtered if x["latency_ms"] is not None and x["sample_quality"] == "current"]
    measured_loss = [x["packet_loss"] for x in filtered if x["packet_loss"] is not None and x["sample_quality"] == "current"]
    avg_lat = round(sum(measured_latency) / len(measured_latency), 1) if measured_latency else None
    avg_loss = round(sum(measured_loss) / len(measured_loss), 2) if measured_loss else None

    return {
        "report_type": "outbound",
        "summary": {
            "total_probes": len(filtered),
            "active_probes": active_cnt,
            "avg_latency_ms": avg_lat,
            "avg_packet_loss": avg_loss,
            "no_data_probes": sum(1 for x in filtered if x["sample_quality"] == "no_data"),
            "stale_probes": sum(1 for x in filtered if x["sample_quality"] == "stale"),
            "failed_probes": sum(1 for x in filtered if x["sample_quality"] == "failed"),
        },
        "options": {
            "isps": sorted(list(isps_set)),
            "target_types": ["ICMP", "HTTP", "TCP"],
        },
        "items": filtered,
        "total": len(filtered),
        "generated_at": now_str,
    }


def generate_interfaces_report(
    *,
    conn: Any = None,
    format_type: str = "xlsx",
    filters: dict[str, Any] | None = None,
) -> tuple[bytes, str, str]:
    """Generate professional network interface traffic and health report (supports filters)."""
    data = fetch_interfaces_report_data(conn=conn, filters=filters)
    items = data["items"]
    now_str = data["generated_at"]
    date_slug = datetime.now().strftime("%Y%m%d_%H%M")

    s1_headers = ["设备名称", "管理 IP", "厂商", "角色", "站点", "接口名称", "接口描述", "管理状态", "运行状态", "物理速率", "采样时间"]
    s1_rows = []
    s2_headers = ["设备名称", "接口名称", "管理 IP", "端口速率", "入向速率", "出向速率", "入向利用率", "出向利用率", "综合最大利用率", "采样时间"]
    s2_rows = []
    s3_headers = ["设备名称", "接口名称", "管理 IP", "端口速率", "综合利用率", "预警等级", "建议处置措施", "采样时间"]
    s3_rows = []
    s4_headers = ["设备名称", "接口名称", "管理 IP", "入向错包率 (pps)", "出向错包率 (pps)", "入向丢弃率 (pps)", "出向丢弃率 (pps)", "健康状态", "采样时间"]
    s4_rows = []

    for item in items:
        s1_rows.append([
            item["hostname"], item["ip_address"], item["vendor"], item["role"], item["site_name"],
            item["interface_name"], item["description"], item["admin_status"], item["oper_status"],
            item["speed_str"], item["sample_time"] or "—"
        ])
        s2_rows.append([
            item["hostname"], item["interface_name"], item["ip_address"], item["speed_str"],
            item["in_bps_str"], item["out_bps_str"],
            f"{item['in_util']:.2f}%" if item["in_util"] is not None else "—",
            f"{item['out_util']:.2f}%" if item["out_util"] is not None else "—",
            f"{item['max_util']:.2f}%" if item["max_util"] is not None else "—",
            item["sample_time"] or "—"
        ])
        if item["max_util"] is not None and item["max_util"] >= 50.0:
            s3_rows.append([
                item["hostname"], item["interface_name"], item["ip_address"], item["speed_str"],
                f"{item['max_util']:.2f}%", item["alert_level"], item["advice"], item["sample_time"] or "—"
            ])
        s4_rows.append([
            item["hostname"], item["interface_name"], item["ip_address"],
            f"{item['in_errors']:.2f}" if item["in_errors"] is not None else "—",
            f"{item['out_errors']:.2f}" if item["out_errors"] is not None else "—",
            f"{item['in_discards']:.2f}" if item["in_discards"] is not None else "—",
            f"{item['out_discards']:.2f}" if item["out_discards"] is not None else "—",
            item["health_status"], item["sample_time"] or "—"
        ])

    if not s3_rows:
        if all(item["max_util"] is None for item in items):
            s3_rows.append(["无有效接口采样", "—", "—", "—", "—", "NO_DATA", "无法评估接口利用率", "—"])
        else:
            s3_rows.append(["全网接口运行良好", "--", "--", "--", "< 50.0%", "NORMAL 正常", "全网未发现超负荷高利用率接口", now_str])

    s2_rows.sort(key=lambda r: float(r[8].replace("%", "")) if r[8] != "—" else -1, reverse=True)
    s4_rows.sort(key=lambda r: sum(float(value) for value in r[3:7] if value != "—"), reverse=True)

    if format_type.lower() == "csv":
        out = io.StringIO()
        out.write("\ufeff")
        writer = csv.writer(out)
        writer.writerow(["# Nexora 网络接口综合监控报表"])
        writer.writerow([])
        writer.writerow(["## 工作表 1: 流量与利用率统计"])
        writer.writerow(s2_headers)
        writer.writerows(s2_rows)
        writer.writerow([])
        writer.writerow(["## 工作表 2: 接口清单与状态"])
        writer.writerow(s1_headers)
        writer.writerows(s1_rows)
        writer.writerow([])
        writer.writerow(["## 工作表 3: 高利用率预警接口"])
        writer.writerow(s3_headers)
        writer.writerows(s3_rows)
        return out.getvalue().encode("utf-8-sig"), f"nexora_interfaces_{date_slug}.csv", "text/csv; charset=utf-8"

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "接口清单与状态"
    _style_worksheet(ws1, s1_headers, s1_rows, align_specs=["center", "center", "center", "center", "center", "left", "left", "center", "center", "right", "center"])

    ws2 = wb.create_sheet(title="流量与利用率统计")
    _style_worksheet(ws2, s2_headers, s2_rows, align_specs=["center", "left", "center", "right", "right", "right", "right", "right", "right", "center"])

    ws3 = wb.create_sheet(title="高利用率预警接口")
    _style_worksheet(ws3, s3_headers, s3_rows, align_specs=["center", "left", "center", "right", "right", "center", "left", "center"])

    ws4 = wb.create_sheet(title="接口错误与丢弃排行")
    _style_worksheet(ws4, s4_headers, s4_rows, align_specs=["center", "left", "center", "right", "right", "right", "right", "center", "center"])

    out_bio = io.BytesIO()
    wb.save(out_bio)
    out_bio.seek(0)
    return out_bio.getvalue(), f"nexora_interfaces_{date_slug}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def generate_devices_report(
    *,
    conn: Any = None,
    format_type: str = "xlsx",
    filters: dict[str, Any] | None = None,
) -> tuple[bytes, str, str]:
    """Generate professional network devices resource health and capacity workbook (supports filters)."""
    data = fetch_devices_report_data(conn=conn, filters=filters)
    items = data["items"]
    now_str = data["generated_at"]
    date_slug = datetime.now().strftime("%Y%m%d_%H%M")

    s1_headers = ["设备名称", "管理 IP", "厂商", "平台", "设备角色", "所属站点", "在线状态", "CPU 使用率", "内存利用率", "温度 (°C)", "采样时间"]
    s1_rows = []
    s2_headers = ["设备名称", "管理 IP", "厂商", "指标类型", "当前数值", "预警等级", "建议措施", "采样时间"]
    s2_rows = []

    for item in items:
        s1_rows.append([
            item["hostname"], item["ip_address"], item["vendor"], item["platform"], item["role"],
            item["site_name"], item["status"], f"{item['cpu_usage']:.1f}%" if item["cpu_usage"] is not None else "—",
            f"{item['memory_usage']:.1f}%" if item["memory_usage"] is not None else "—",
            item["temperature_str"], item["sample_time"] or "—"
        ])
        if item["metric_sources"]["cpu_usage"] == "victoriametrics" and item["cpu_usage"] is not None and item["cpu_usage"] >= 70.0:
            lvl = "CRITICAL 严重" if item["cpu_usage"] >= 85.0 else "WARNING 预警"
            s2_rows.append([item["hostname"], item["ip_address"], item["vendor"], "CPU 负荷过高", f"{item['cpu_usage']:.1f}%", lvl, item["advice"], item["sample_time"] or "—"])
        if item["metric_sources"]["memory_usage"] == "victoriametrics" and item["memory_usage"] is not None and item["memory_usage"] >= 75.0:
            lvl = "CRITICAL 严重" if item["memory_usage"] >= 90.0 else "WARNING 预警"
            s2_rows.append([item["hostname"], item["ip_address"], item["vendor"], "内存使用过高", f"{item['memory_usage']:.1f}%", lvl, item["advice"], item["sample_time"] or "—"])

    if not s2_rows:
        if all(item["sample_quality"] in {"no_data", "stale"} for item in items):
            s2_rows.append(["无有效资源采样", "—", "—", "不可评估", "—", "NO_DATA", "当前没有有效 VM 采样", "—"])
        else:
            s2_rows.append(["全网设备健康", "--", "--", "全局正常", "正常", "NORMAL 正常", "全网未发现 CPU/内存高负荷设备", now_str])

    s1_rows.sort(key=lambda r: float(r[7].replace("%", "")) if r[7] != "—" else -1, reverse=True)

    if format_type.lower() == "csv":
        out = io.StringIO()
        out.write("\ufeff")
        writer = csv.writer(out)
        writer.writerow(["# Nexora 网络设备运行与资源报表"])
        writer.writerow([])
        writer.writerow(["## 设备资源负荷清单"])
        writer.writerow(s1_headers)
        writer.writerows(s1_rows)
        return out.getvalue().encode("utf-8-sig"), f"nexora_devices_{date_slug}.csv", "text/csv; charset=utf-8"

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "设备运行与资源清单"
    _style_worksheet(ws1, s1_headers, s1_rows, align_specs=["center", "center", "center", "center", "center", "center", "center", "right", "right", "right", "center"])

    ws2 = wb.create_sheet(title="高负荷告警设备")
    _style_worksheet(ws2, s2_headers, s2_rows, align_specs=["center", "center", "center", "center", "right", "center", "left", "center"])

    out_bio = io.BytesIO()
    wb.save(out_bio)
    out_bio.seek(0)
    return out_bio.getvalue(), f"nexora_devices_{date_slug}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def generate_outbound_report(
    *,
    conn: Any = None,
    format_type: str = "xlsx",
    filters: dict[str, Any] | None = None,
) -> tuple[bytes, str, str]:
    """Generate professional internet outbound and WAN link health report (supports filters)."""
    data = fetch_outbound_report_data(conn=conn, filters=filters)
    items = data["items"]
    now_str = data["generated_at"]
    date_slug = datetime.now().strftime("%Y%m%d_%H%M")

    s1_headers = ["探针目标名称", "目标类型", "探测地址/IP", "所属运营商", "探针激活状态", "实时延迟 (ms)", "丢包率 (%)", "链路状态", "采样时间"]
    s1_rows = []

    for item in items:
        s1_rows.append([
            item["name"], item["target_type"], item["target"], item["isp"], item["active_str"],
            f"{item['latency_ms']:.1f} ms" if item["latency_ms"] is not None else "—",
            f"{item['packet_loss']:.1f}%" if item["packet_loss"] is not None else "—",
            item["status"], item["sample_time"] or "—"
        ])

    if format_type.lower() == "csv":
        out = io.StringIO()
        out.write("\ufeff")
        writer = csv.writer(out)
        writer.writerow(["# Nexora 互联网出口与 WAN 链路运行报表"])
        writer.writerow([])
        writer.writerow(s1_headers)
        writer.writerows(s1_rows)
        return out.getvalue().encode("utf-8-sig"), f"nexora_outbound_{date_slug}.csv", "text/csv; charset=utf-8"

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "出口链路与探针状态"
    _style_worksheet(ws1, s1_headers, s1_rows, align_specs=["left", "center", "center", "center", "center", "right", "right", "center", "center"])

    out_bio = io.BytesIO()
    wb.save(out_bio)
    out_bio.seek(0)
    return out_bio.getvalue(), f"nexora_outbound_{date_slug}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
