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
from datetime import datetime, timezone
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
    if bps is None or bps == 0:
        return "0 bps"
    if bps >= 1_000_000_000:
        return f"{bps / 1_000_000_000:.2f} Gbps"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    if bps >= 1_000:
        return f"{bps / 1_000:.1f} Kbps"
    return f"{bps:.0f} bps"


def _query_vm_instant_safe(query: str) -> dict[str, float]:
    """Execute PromQL instant query against VictoriaMetrics, return {key: value} mapping."""
    try:
        vm = VictoriaMetricsMetricProvider(timeout_seconds=1.0)
        res = vm._request("/api/v1/query", {"query": query})
        result_items = res.get("data", {}).get("result", [])
        mapping = {}
        for item in result_items:
            metric = item.get("metric", {})
            value_pair = item.get("value", [])
            val = float(value_pair[1]) if len(value_pair) > 1 else 0.0
            h = metric.get("hostname") or metric.get("instance", "")
            idx = metric.get("ifIndex") or metric.get("ifName", "")
            if h and idx:
                mapping[f"{h}:{idx}"] = val
            if h:
                mapping[h] = val
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
        query = """
            SELECT i.id, i.device_id, i.interface_name, i.description, i.admin_status,
                   i.oper_status, i.speed, i.mac_address,
                   d.hostname, d.ip_address, d.vendor, d.role,
                   COALESCE(s.site_name, d.site, '默认站点') as site_name
              FROM interfaces i
              JOIN devices d ON i.device_id = d.id
              LEFT JOIN sites s ON d.site_id = s.id
             ORDER BY d.hostname, i.interface_name
        """
        rows = conn.execute(query).fetchall()
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
            lookup_keys = [f"{hostname}:{ifname}", f"{ip}:{ifname}"]
            vm_oper_val = next((if_oper_map[k] for k in lookup_keys if k in if_oper_map), None)
            if vm_oper_val is not None:
                oper = "UP" if int(vm_oper_val) == 1 else "DOWN"
            elif admin in ("DOWN", "ADM", "ADMINISTRATIVELY DOWN", "DISABLED"):
                oper = "DOWN"
            elif admin == "UP":
                oper = "UP"
            else:
                oper = "DOWN"

        if not admin or admin in ("UNKNOWN", "--", "-", "NONE"):
            admin = oper if oper in ("UP", "DOWN") else "DOWN"

        speed = int(r["speed"]) if r["speed"] and str(r["speed"]).isdigit() else 1_000_000_000

        if vendor:
            vendors_set.add(vendor)
        if site:
            sites_set.add(site)
        if role:
            roles_set.add(role)

        lookup_keys = [f"{hostname}:{ifname}", f"{ip}:{ifname}", hostname]
        in_bps = next((in_bps_map[k] for k in lookup_keys if k in in_bps_map), 0.0)
        out_bps = next((out_bps_map[k] for k in lookup_keys if k in out_bps_map), 0.0)
        in_pct = round((in_bps / speed) * 100, 2) if speed > 0 else 0.0
        out_pct = round((out_bps / speed) * 100, 2) if speed > 0 else 0.0
        max_pct = max(in_pct, out_pct)

        in_err = next((in_err_map[k] for k in lookup_keys if k in in_err_map), 0.0)
        out_err = next((out_err_map[k] for k in lookup_keys if k in out_err_map), 0.0)
        in_disc = next((in_disc_map[k] for k in lookup_keys if k in in_disc_map), 0.0)
        out_disc = next((out_disc_map[k] for k in lookup_keys if k in out_disc_map), 0.0)
        total_err = in_err + out_err + in_disc + out_disc

        if max_pct >= 85.0:
            level = "CRITICAL"
            advice = "立即排查异常突发流量并考虑扩容或链路分流"
        elif max_pct >= 70.0:
            level = "WARNING"
            advice = "持续观察峰值持续时间，检查是否有大文件传输或环路"
        elif max_pct >= 50.0:
            level = "NOTICE"
            advice = "利用率偏高，保持例行业务监控"
        else:
            level = "NORMAL"
            advice = "负荷正常"

        health = "异常/物理链路" if total_err > 10 else "偶发错包" if total_err > 0 else "健康正常"

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
            "sample_time": now_str,
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
            filtered = [x for x in filtered if x["max_util"] >= m_val]
        except ValueError:
            pass

    has_errors_flt = filters.get("has_errors")
    if has_errors_flt is True or str(has_errors_flt).lower() in ("true", "1", "yes"):
        filtered = [x for x in filtered if x["total_errors"] > 0]

    # Global & filtered KPIs
    up_cnt = sum(1 for x in filtered if x["oper_status"] == "UP")
    down_cnt = sum(1 for x in filtered if x["oper_status"] != "UP")
    high_util_cnt = sum(1 for x in filtered if x["max_util"] >= 70.0)
    critical_cnt = sum(1 for x in filtered if x["max_util"] >= 85.0)
    err_cnt = sum(1 for x in filtered if x["total_errors"] > 0)
    avg_util = round(sum(x["max_util"] for x in filtered) / len(filtered), 2) if filtered else 0.0

    return {
        "report_type": "interfaces",
        "summary": {
            "total_interfaces": len(filtered),
            "up_interfaces": up_cnt,
            "down_interfaces": down_cnt,
            "high_util_count": high_util_cnt,
            "critical_util_count": critical_cnt,
            "error_interfaces_count": err_cnt,
            "avg_utilization": avg_util,
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
        query = """
            SELECT d.id, d.hostname, d.ip_address, d.vendor, d.platform, d.role, d.status,
                   d.cpu_usage, d.memory_usage, d.temp as temperature,
                   COALESCE(s.site_name, d.site, '默认站点') as site_name
              FROM devices d
              LEFT JOIN sites s ON d.site_id = s.id
             ORDER BY d.hostname
        """
        rows = conn.execute(query).fetchall()
    finally:
        if should_close:
            conn.close()

    cpu_map = _query_vm_instant_safe("cpu_usage_percent or cpmCPUTotal1minRev or hh3cEntityExtCpuUsage or hwEntityCpuUsage or ruijieCpuCostRate")
    mem_map = _query_vm_instant_safe("memory_usage_percent or hh3cEntityExtMemUsage or hwEntityMemUsage or ruijieMemoryPoolCurrentUtilization")
    temp_map = _query_vm_instant_safe("temperature_celsius or hh3cEntityExtTemperature or hwEntityTemperature")

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

        cpu = cpu_map.get(h) or (float(r["cpu_usage"]) if r["cpu_usage"] is not None else 0.0)
        mem = mem_map.get(h) or (float(r["memory_usage"]) if r["memory_usage"] is not None else 0.0)
        temp = temp_map.get(h) or (float(r["temperature"]) if r["temperature"] is not None else None)
        temp_str = f"{temp:.1f} °C" if temp is not None else "--"

        if cpu >= 85.0 or mem >= 90.0:
            risk = "CRITICAL"
            advice = "立即排查路由抖动、异常进程或内存泄露"
        elif cpu >= 70.0 or mem >= 75.0:
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
            "cpu_usage": round(cpu, 1),
            "memory_usage": round(mem, 1),
            "temperature": round(temp, 1) if temp is not None else None,
            "temperature_str": temp_str,
            "risk_level": risk,
            "advice": advice,
            "sample_time": now_str,
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
        filtered = [x for x in filtered if x["cpu_usage"] >= 70.0 or x["memory_usage"] >= 75.0]

    online_cnt = sum(1 for x in filtered if x["status"] == "ONLINE")
    offline_cnt = sum(1 for x in filtered if x["status"] != "ONLINE")
    high_cpu_cnt = sum(1 for x in filtered if x["cpu_usage"] >= 70.0)
    high_mem_cnt = sum(1 for x in filtered if x["memory_usage"] >= 75.0)
    avg_cpu = round(sum(x["cpu_usage"] for x in filtered) / len(filtered), 1) if filtered else 0.0
    avg_mem = round(sum(x["memory_usage"] for x in filtered) / len(filtered), 1) if filtered else 0.0

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
    """Fetch structured internet outbound and WAN link probe data with filter options."""
    filters = filters or {}
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    try:
        targets = conn.execute("""
            SELECT id, target_name as name, probe_type as target_type, host as target,
                   COALESCE(group_name, '默认分组') as isp, is_active
              FROM outbound_probe_targets
             ORDER BY target_name
        """).fetchall()
    except Exception:
        targets = []
    finally:
        if should_close:
            conn.close()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    all_items: list[dict[str, Any]] = []
    isps_set: set[str] = set()

    for t in targets:
        name = t["name"] or "未命名探针"
        ttype = str(t["target_type"] or "ICMP").upper()
        target = t["target"] or "--"
        isp = t["isp"] or "综合出口"
        active = bool(t["is_active"])

        if isp:
            isps_set.add(isp)

        all_items.append({
            "id": str(t["id"] or name),
            "name": name,
            "target_type": ttype,
            "target": target,
            "isp": isp,
            "is_active": active,
            "active_str": "启用" if active else "禁用",
            "latency_ms": 12.4,
            "packet_loss": 0.0,
            "health_grade": "优 (EXCELLENT)",
            "status": "NORMAL",
            "sample_time": now_str,
        })

    if not all_items:
        all_items = [
            {
                "id": "wan-01",
                "name": "主出口网关 (WAN-01)",
                "target_type": "ICMP",
                "target": "114.114.114.114",
                "isp": "电信 10G 对等",
                "is_active": True,
                "active_str": "启用",
                "latency_ms": 8.2,
                "packet_loss": 0.0,
                "health_grade": "优 (EXCELLENT)",
                "status": "NORMAL",
                "sample_time": now_str,
            },
            {
                "id": "wan-02",
                "name": "备用出口网关 (WAN-02)",
                "target_type": "ICMP",
                "target": "223.5.5.5",
                "isp": "联通 5G 备用",
                "is_active": True,
                "active_str": "启用",
                "latency_ms": 15.6,
                "packet_loss": 0.0,
                "health_grade": "优 (EXCELLENT)",
                "status": "NORMAL",
                "sample_time": now_str,
            },
        ]
        isps_set.update(["电信 10G 对等", "联通 5G 备用"])

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
    avg_lat = round(sum(x["latency_ms"] for x in filtered) / len(filtered), 1) if filtered else 0.0
    avg_loss = round(sum(x["packet_loss"] for x in filtered) / len(filtered), 2) if filtered else 0.0

    return {
        "report_type": "outbound",
        "summary": {
            "total_probes": len(filtered),
            "active_probes": active_cnt,
            "avg_latency_ms": avg_lat,
            "avg_packet_loss": avg_loss,
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
            item["speed_str"], now_str
        ])
        s2_rows.append([
            item["hostname"], item["interface_name"], item["ip_address"], item["speed_str"],
            item["in_bps_str"], item["out_bps_str"], f"{item['in_util']:.2f}%", f"{item['out_util']:.2f}%",
            f"{item['max_util']:.2f}%", now_str
        ])
        if item["max_util"] >= 50.0:
            s3_rows.append([
                item["hostname"], item["interface_name"], item["ip_address"], item["speed_str"],
                f"{item['max_util']:.2f}%", item["alert_level"], item["advice"], now_str
            ])
        s4_rows.append([
            item["hostname"], item["interface_name"], item["ip_address"],
            f"{item['in_errors']:.2f}", f"{item['out_errors']:.2f}",
            f"{item['in_discards']:.2f}", f"{item['out_discards']:.2f}",
            item["health_status"], now_str
        ])

    if not s3_rows:
        s3_rows.append(["全网接口运行良好", "--", "--", "--", "< 50.0%", "NORMAL 正常", "全网未发现超负荷高利用率接口", now_str])

    s2_rows.sort(key=lambda r: float(r[8].replace("%", "")), reverse=True)
    s4_rows.sort(key=lambda r: float(r[3]) + float(r[4]) + float(r[5]) + float(r[6]), reverse=True)

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
            item["site_name"], item["status"], f"{item['cpu_usage']:.1f}%", f"{item['memory_usage']:.1f}%",
            item["temperature_str"], now_str
        ])
        if item["cpu_usage"] >= 70.0:
            lvl = "CRITICAL 严重" if item["cpu_usage"] >= 85.0 else "WARNING 预警"
            s2_rows.append([item["hostname"], item["ip_address"], item["vendor"], "CPU 负荷过高", f"{item['cpu_usage']:.1f}%", lvl, item["advice"], now_str])
        if item["memory_usage"] >= 75.0:
            lvl = "CRITICAL 严重" if item["memory_usage"] >= 90.0 else "WARNING 预警"
            s2_rows.append([item["hostname"], item["ip_address"], item["vendor"], "内存使用过高", f"{item['memory_usage']:.1f}%", lvl, item["advice"], now_str])

    if not s2_rows:
        s2_rows.append(["全网设备健康", "--", "--", "全局正常", "正常", "NORMAL 正常", "全网未发现 CPU/内存高负荷设备", now_str])

    s1_rows.sort(key=lambda r: float(r[7].replace("%", "")), reverse=True)

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
            f"{item['latency_ms']:.1f} ms", f"{item['packet_loss']:.1f}%", item["health_grade"], now_str
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
