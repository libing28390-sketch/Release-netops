import json
import os
from pathlib import Path

false = False
true = True
null = None

ROOT_DIR = Path(__file__).resolve().parents[2]
DASHBOARDS_DIR = ROOT_DIR / "monitoring" / "grafana" / "dashboards"
DS_UID = "victoriametrics"
DASHBOARD_VERSION = 29
NO_VALUE_TEXT = "数据暂不可用"

INBOUND_COLOR = "#3274D9"
OUTBOUND_COLOR = "#56A64B"
ERROR_COLOR = "#FF9830"
DISCARD_COLOR = "#F2495C"
MULTICAST_COLOR = "#A352CC"
BROADCAST_COLOR = "#E0B400"
PPS_COLOR = "#00A6B2"
UNKNOWN_COLOR = "gray"

UTILIZATION_THRESHOLDS = [
    {"color": "green", "value": None},
    {"color": "yellow", "value": 60},
    {"color": "orange", "value": 75},
    {"color": "red", "value": 90},
]

STATUS_VALUE_MAPPINGS = [
    {
        "type": "value",
        "options": {
            "1": {"text": "Up", "color": "green"},
            "2": {"text": "down", "color": "red"},
            "0": {"text": "UNKNOWN", "color": UNKNOWN_COLOR},
            "3": {"text": "UNKNOWN", "color": UNKNOWN_COLOR},
            "4": {"text": "UNKNOWN", "color": UNKNOWN_COLOR},
            "5": {"text": "UNKNOWN", "color": UNKNOWN_COLOR},
            "6": {"text": "UNKNOWN", "color": UNKNOWN_COLOR},
            "7": {"text": "UNKNOWN", "color": UNKNOWN_COLOR},
        },
    },
    {
        "type": "special",
        "options": {
            "match": "null",
            "result": {"text": "UNKNOWN", "color": UNKNOWN_COLOR},
        },
    },
    {
        "type": "special",
        "options": {
            "match": "nan",
            "result": {"text": "UNKNOWN", "color": UNKNOWN_COLOR},
        },
    },
]

ANOMALY_VALUE_MAPPINGS = [
    {
        "type": "value",
        "options": {
            "0": {"text": "正常", "color": "green"},
            "1": {"text": "DOWN", "color": "red"},
        },
    },
]

DEV_JOIN = ""
IF_JOIN = "* on(instance, ifIndex) group_left(ifName) ((ifName * 0 + 1) or on(instance, ifIndex) (ifOperStatus * 0 + 1))"
NETWORK_JOB = 'job="network_snmp"'


def counter_rate_expr(high_capacity_metric, legacy_metric, selector):
    """Return a Counter64-first rate with a Counter32 fallback.

    IF-MIB exposes both counter widths.  ``or`` is intentionally applied after
    ``rate`` so a device that does not expose the high-capacity object still
    contributes traffic instead of disappearing from the dashboard.
    """
    high = f"rate({high_capacity_metric}{{{selector}}}[5m])"
    legacy = f"rate({legacy_metric}{{{selector}}}[5m])"
    return f"({high} or {legacy})"


def filtered_interface_join(selector, *, alias_selector=None, fallback_status=True):
    """Attach the interface name and configured description after filtering.

    ``ifAlias`` is the IF-MIB object populated by a device's interface
    ``description`` command. It is exported as a separate metric with
    ``ifIndex`` and ``ifAlias`` labels, so its selector must not require the
    ``ifName`` lookup label. ``ifIndex`` remains an internal join key; it is
    never exposed as a table column or variable. The name fallback keeps
    rows visible when an interface has no alias series; the optional status
    fallback also handles devices that do not expose an ifName series.
    """
    name_expr = f"ifName{{{selector}}} * 0 + 1"
    alias_selector = alias_selector or selector
    alias_source = f"ifAlias{{{alias_selector}}} * 0 + 1"
    metadata_expr = (
        f"(({name_expr}) * on(instance, ifIndex) group_left(ifAlias) "
        f"({alias_source})) or on(instance, ifIndex) ({name_expr})"
    )
    if fallback_status:
        status_fallback = f"(ifOperStatus{{{selector}}} * 0 + 1)"
        metadata_expr = f"({metadata_expr}) or on(instance, ifIndex) {status_fallback}"
    return f"* on(instance, ifIndex) group_left(ifName, ifAlias) ({metadata_expr})"


def interface_rate_sum(metrics, selector, interface_join):
    """Sum collected counter rates while preserving no-data when all are absent.

    Rate is evaluated before aggregation. A metric-name selector lets a device
    contribute whichever members of an optional counter family it exports,
    without fabricating zero samples when every member is missing.
    """
    labels = "instance, hostname, site_name, ifIndex, ifName, ifAlias, interface_role, utilization_warn_pct, utilization_high_pct, utilization_critical_pct"
    metric_pattern = "|".join(str(metric) for metric in metrics)
    family_rate = f'rate({{__name__=~"^({metric_pattern})$",{selector}}}[5m]) {interface_join}'
    return f"sum by ({labels}) ({family_rate})"


def interface_empty_fallback(status_expr, positive_rows_expr):
    """Return one labelled fallback row when status exists but no rows do.

    The two global counts make this a singleton row for the whole selection.
    If the status metric is absent, the availability gate is empty and Grafana
    correctly keeps the panel in No data state.
    """
    status_available = f"((count({status_expr}) or vector(0)) > 0)"
    rows_absent = f"((count({positive_rows_expr}) or vector(0)) == 0)"
    empty_selection = f"({status_available} and on() {rows_absent}) * 0"
    return f'label_replace({empty_selection}, "ifName", "当前无异常", "", "")'

def stat_panel(pid, title, expr, x, y, w=4, h=4, unit="", color="#3274D9", thresholds=None):
    steps = [{"color": color, "value": None}]
    if thresholds:
        steps = thresholds
    return {
        "id": pid,
        "title": title,
        "type": "stat",
        "datasource": {"type": "prometheus", "uid": DS_UID},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "noValue": NO_VALUE_TEXT,
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": steps}
            },
            "overrides": []
        },
        "options": {
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "center",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto"
        },
        "targets": [{"expr": expr, "refId": "A"}]
    }

def timeseries_color_override(matcher_id, matcher_options, color):
    return {
        "matcher": {"id": matcher_id, "options": matcher_options},
        "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}],
    }


def timeseries_panel(pid, title, targets, x, y, w=12, h=8, unit="", color_overrides=None):
    return {
        "id": pid,
        "title": title,
        "type": "timeseries",
        "datasource": {"type": "prometheus", "uid": DS_UID},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "noValue": NO_VALUE_TEXT,
                "color": {"mode": "palette-classic"},
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "linear",
                    "lineWidth": 2,
                    "fillOpacity": 10,
                    "gradientMode": "none",
                    "showPoints": "never",
                }
            },
            "overrides": color_overrides or []
        },
        "options": {
            "legend": {
                "displayMode": "table",
                "placement": "right",
                "showLegend": True,
                "calcs": ["lastNotNull", "max", "mean"],
            },
            "tooltip": {"mode": "multi", "sort": "desc"}
        },
        "targets": targets
    }

def clean_organize_transformation(
    value_col_name="数值",
    extra_renames=None,
    *,
    interface_description_label="ifDescr",
):
    description_index = interface_description_label
    renames = {
        "sysName": "设备名称",
        "hostname": "设备名称",
        "instance": "管理 IP",
        "site_name": "站点",
        "ifName": "接口全称",
        interface_description_label: "接口描述",
        "vendor": "厂商",
        "role": "角色",
        "interface_role": "接口角色",
        "utilization_warn_pct": "预警阈值 (%)",
        "utilization_high_pct": "高位阈值 (%)",
        "utilization_critical_pct": "严重阈值 (%)",
        "Value": value_col_name,
    }
    if extra_renames:
        renames.update(extra_renames)
    result = [
        {
            "id": "organize",
            "options": {
                "excludeByName": {
                    "Time": True,
                    "__name__": True,
                    "ifIndex": True,
                    "asset_id": True,
                    "nexora_asset_id": True,
                    "nexora_hostname": True,
                    "nexora_module": True,
                    "nexora_platform": True,
                    "nexora_role": True,
                    "nexora_site_id": True,
                    "nexora_site_name": True,
                    "nexora_tenant_id": True,
                    "nexora_vendor": True,
                    "job": True,
                    "tenant_id": True,
                    "site_id": True,
                    "platform": True,
                    "sysName": True,
                    "nexora_interface_role": True,
                },
                "indexByName": {
                    "site_name": 0,
                    "hostname": 1,
                    "instance": 2,
                    "ifName": 3,
                    description_index: 4,
                    "vendor": 5,
                    "role": 6,
                    "interface_role": 7,
                    "utilization_warn_pct": 8,
                    "utilization_high_pct": 9,
                    "utilization_critical_pct": 10,
                    "Value": 11,
                },
                "renameByName": renames,
            }
        }
    ]

    if interface_description_label != "ifDescr":
        result[0]["options"]["excludeByName"]["ifDescr"] = True
    return result

def table_panel(
    pid,
    title,
    expr,
    x,
    y,
    w=12,
    h=8,
    unit="",
    transformations=None,
    value_col_name="数值",
    value_mappings=None,
    gauge=False,
    thresholds=None,
    targets=None,
    detail_link=False,
    color_mapped_cells=False,
):
    overrides = []
    value_properties = []
    if unit:
        value_properties.append({"id": "unit", "value": unit})
    if gauge:
        value_properties.extend([
            {"id": "min", "value": 0},
            {"id": "max", "value": 100},
            {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "gradient"}},
        ])
    if thresholds:
        value_properties.append({
            "id": "thresholds",
            "value": {"mode": "absolute", "steps": thresholds},
        })
    if value_mappings:
        value_properties.append({"id": "mappings", "value": value_mappings})
    if value_properties:
        overrides.append({
            "matcher": {"id": "byName", "options": value_col_name},
            "properties": value_properties,
        })
    if color_mapped_cells:
        overrides.append({
            "matcher": {"id": "byName", "options": value_col_name},
            "properties": [{
                "id": "custom.cellOptions",
                "value": {"type": "color-text"},
            }],
        })
    if detail_link:
        overrides.append({
            "matcher": {"id": "byName", "options": "接口全称"},
            "properties": [{
                "id": "links",
                "value": [{
                    "title": "打开接口详情",
                    "url": "/d/nexora-interface-detail/interface-detail?var-site=${__data.fields[\"站点\"]}&var-vendor=${__data.fields[\"厂商\"]}&var-role=${__data.fields[\"角色\"]}&var-device=${__data.fields[\"设备名称\"]}&var-interface_role=${__data.fields[\"接口角色\"]}&var-interface=${__data.fields[\"接口全称\"]}&from=${__from}&to=${__to}",
                    "targetBlank": False,
                }],
            }],
        })
    panel = {
        "id": pid,
        "title": title,
        "type": "table",
        "datasource": {"type": "prometheus", "uid": DS_UID},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "unit": "none",
                "noValue": NO_VALUE_TEXT,
                "color": {"mode": "thresholds"},
                "custom": {"filterable": True},
            },
            "overrides": overrides
        },
        "options": {
            "cellHeight": "sm",
            "showHeader": True,
            "footer": {"show": False},
            "enablePagination": True,
        },
        "targets": targets or [{"expr": expr, "format": "table", "instant": True, "refId": "A"}]
    }
    if transformations:
        panel["transformations"] = transformations
    return panel


def row_panel(pid, title, y):
    return {
        "id": pid,
        "title": title,
        "type": "row",
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "panels": [],
    }


def insert_section_rows(panels, sections):
    """Insert visible Grafana row headings at existing grid boundaries."""
    rows = []
    for index, (title, before_y) in enumerate(sorted(sections, key=lambda item: item[1])):
        shift = sum(1 for _, prior_y in sections if prior_y < before_y)
        row_y = before_y + shift
        rows.append(row_panel(900 + index, title, row_y))
        for panel in panels:
            grid = panel.get("gridPos") or {}
            if int(grid.get("y", -1)) >= before_y:
                grid["y"] = int(grid["y"]) + 1
    return sorted([*panels, *rows], key=lambda panel: (panel.get("gridPos", {}).get("y", 0), panel.get("gridPos", {}).get("x", 0)))

def bar_gauge_panel(pid, title, expr, x, y, w=12, h=8, unit="percent"):
    return {
        "id": pid,
        "title": title,
        "type": "bargauge",
        "datasource": {"type": "prometheus", "uid": DS_UID},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "min": 0,
                "max": 100,
                "thresholds": {
                    "mode": "absolute",
                    "steps": UTILIZATION_THRESHOLDS
                }
            },
            "overrides": []
        },
        "options": {
            "displayMode": "gradient",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "values": false}
        },
        "targets": [{"expr": expr, "legendFormat": "{{sysName}} {{instance}}", "refId": "A"}]
    }

def make_query_variable(name, label, query_str, multi=True, include_all=True):
    return {
        "allValue": ".*" if include_all else None,
        "current": {"selected": True, "text": ["All"], "value": ["$__all"]} if include_all else {"selected": False, "text": "", "value": ""},
        "definition": query_str,
        "includeAll": include_all,
        "label": label,
        "multi": multi,
        "name": name,
        "options": [],
        "query": {"query": query_str, "refId": "StandardVariableQuery"},
        "refresh": 1,
        "type": "query"
    }

def make_network_variables(multi_device=True, include_all_device=True, device_label="设备"):
    return [
        make_query_variable("site", "站点", f'label_values({{__name__=~"ifOperStatus|up",{NETWORK_JOB}}}, site_name)'),
        make_query_variable("vendor", "厂商", f'label_values({{__name__=~"ifOperStatus|up",{NETWORK_JOB},site_name=~"$site"}}, vendor)'),
        make_query_variable("role", "角色", f'label_values({{__name__=~"ifOperStatus|up",{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor"}}, role)'),
        make_query_variable("device", device_label, f'label_values({{__name__=~"ifOperStatus|up",{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role"}}, hostname)', multi=multi_device, include_all=include_all_device),
    ]

def make_interface_variables(
    multi_device=True,
    include_all_device=True,
    include_all_interface=True,
    interface_label="接口",
    device_label="设备",
    multi_interface=True,
    include_threshold_values=False,
):
    vars = make_network_variables(multi_device=multi_device, include_all_device=include_all_device, device_label=device_label)
    vars.append(
        make_query_variable(
            "interface_role",
            "接口角色",
            f'label_values({{__name__=~"ifName",{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"}}, interface_role)',
        )
    )
    vars.append(
        make_query_variable(
            "interface",
            interface_label,
            f'label_values({{__name__=~"ifName",{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device",interface_role=~"$interface_role"}}, ifName)',
            multi=multi_interface,
            include_all=include_all_interface
        )
    )
    if include_threshold_values:
        threshold_selector = (
            f'{{__name__=~"ifName",{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor",'
            f'role=~"$role",hostname=~"$device",ifName=~"$interface",interface_role=~"$interface_role"}}'
        )
        for variable, label in (
            ("utilization_warn_pct", "预警阈值"),
            ("utilization_high_pct", "高位阈值"),
            ("utilization_critical_pct", "严重阈值"),
        ):
            vars.append(
                make_query_variable(
                    variable,
                    label,
                    f'label_values({threshold_selector}, {variable})',
                    multi=False,
                    include_all=False,
                )
            )
    return vars

# 1. Overview Dashboard
def build_overview_dashboard():
    sel = f'{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    target_sel = f'{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    target_site_sel = f'{NETWORK_JOB},site_name!="",site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    in_rate = counter_rate_expr("ifHCInOctets", "ifInOctets", sel)
    out_rate = counter_rate_expr("ifHCOutOctets", "ifOutOctets", sel)
    cpu_expr = (
        "avg by (hostname, site_name, instance, vendor) ("
        f"cpmCPUTotal1minRev{{{sel}}} or "
        f"hh3cEntityExtCpuUsage{{{sel}}} or "
        f"hwEntityCpuUsage{{{sel}}} or "
        f"ruijieCpuCostRate{{{sel}}} or "
        f"jnxOperatingCPU{{{sel}}} or "
        f"fnSysCpuUsage{{{sel}}} or "
        f"zteCpuRate{{{sel}}} or "
        f"mpCpuUtilization5Min{{{sel}}} or "
        f"dptechCpuUsage{{{sel}}} or "
        f"hillstoneCPUUtilization{{{sel}}} or "
        f"sangforCpuUsage{{{sel}}} or "
        f"dcnCpuUsage{{{sel}}}"
        ")"
    )
    mem_expr = (
        "avg by (hostname, site_name, instance, vendor) ("
        f"hh3cEntityExtMemUsage{{{sel}}} or "
        f"hwEntityMemUsage{{{sel}}} or "
        f"(100 * ciscoMemoryPoolUsed{{{sel}}} / (ciscoMemoryPoolUsed{{{sel}}} + ciscoMemoryPoolFree{{{sel}}})) or "
        f"ruijieMemoryPoolCurrentUtilization{{{sel}}} or "
        f"jnxOperatingBuffer{{{sel}}} or "
        f"fnSysMemUsage{{{sel}}} or "
        f"zteMemRate{{{sel}}} or "
        f"mpMemoryUtilization{{{sel}}} or "
        f"dptechMemUsage{{{sel}}} or "
        f"hillstoneMemoryUtilization{{{sel}}} or "
        f"sangforMemUsage{{{sel}}} or "
        f"dcnMemUsage{{{sel}}}"
        ")"
    )
    ap_online_expr = (
        f"sum((hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or "
        f"ruijieApcTotalApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}})) or vector(0)"
    )
    client_online_expr = (
        f"sum((hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or "
        f"cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}})) or vector(0)"
    )
    anomaly_rows = (
        f'((ifAdminStatus{{{sel}}} == 1) and on(instance, ifIndex) '
        f'(ifOperStatus{{{sel}}} != 1)) * on(instance, ifIndex) '
        f'group_left(ifName) (ifName{{{sel}}} * 0 + 1)'
    )
    anomaly_fallback = interface_empty_fallback(f"ifOperStatus{{{sel}}}", anomaly_rows)

    panels = [
        stat_panel(1, "纳管设备数", f'count(count by (instance) (up{{{target_sel}}})) or vector(0)', 0, 0, 4, 3, color="#3274D9"),
        stat_panel(2, "监控站点数", f'count(count by (site_name) (up{{{target_site_sel}}})) or vector(0)', 4, 0, 4, 3, color="#A352CC"),
        stat_panel(3, "全网在线数", f'count(count by (instance) (up{{{target_sel}}} == 1)) or vector(0)', 8, 0, 4, 3, color="#56A64B"),
        stat_panel(4, "无线在线客户端数", client_online_expr, 12, 0, 4, 3, color="#37872D"),
        stat_panel(5, "采集接口总数", f"count(count by (instance, ifIndex) (ifOperStatus{{{sel}}})) or vector(0)", 16, 0, 4, 3, color="#3274D9"),
        stat_panel(6, "异常/Down接口数", f'count(max by (instance, ifIndex) (ifAdminStatus{{{sel}}} == 1) and on(instance, ifIndex) max by (instance, ifIndex) (ifOperStatus{{{sel}}} != 1)) or vector(0)', 20, 0, 4, 3, thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 1},
            {"color": "#F2495C", "value": 5}
        ]),
        timeseries_panel(7, "接口总流量趋势", [
            {"expr": f"sum({in_rate}) * 8", "legendFormat": "入流量", "refId": "A"},
            {"expr": f"sum({out_rate}) * 8", "legendFormat": "出流量", "refId": "B"}
        ], 0, 3, 12, 8, unit="bps", color_overrides=[
            timeseries_color_override("byName", "入流量", INBOUND_COLOR),
            timeseries_color_override("byName", "出流量", OUTBOUND_COLOR),
        ]),
        timeseries_panel(8, "全网无线终端与 AP 规模趋势", [
            {"expr": f"sum((hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}}))", "legendFormat": "无线客户端总数", "refId": "A"},
            {"expr": f"sum((hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or ruijieApcTotalApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}))", "legendFormat": "在线 AP 总数", "refId": "B"}
        ], 12, 3, 12, 8, unit="short"),
        timeseries_panel(9, "设备平均 CPU 使用率", [
            {"expr": cpu_expr, "legendFormat": "{{site_name}} / {{hostname}} · {{vendor}}", "refId": "A"}
        ], 0, 11, 8, 8, unit="percent"),
        timeseries_panel(10, "设备平均内存使用率", [
            {"expr": mem_expr, "legendFormat": "{{site_name}} / {{hostname}} · {{vendor}}", "refId": "A"}
        ], 8, 11, 8, 8, unit="percent"),
        timeseries_panel(11, "设备温度", [
            {"expr": f"max by (hostname, site_name, instance, vendor) (hh3cEntityExtTemperature{{{sel}}} or hwEntityTemperature{{{sel}}} or ruijieDeviceTemperature{{{sel}}} or jnxOperatingTemp{{{sel}}} or zteTemperature{{{sel}}} or mpTemperature{{{sel}}} or dptechTemperature{{{sel}}} or dcnTemperature{{{sel}}})", "legendFormat": "{{site_name}} / {{hostname}} · {{vendor}}", "refId": "A"}
        ], 16, 11, 8, 8, unit="celsius"),
        table_panel(
            12, "设备总流量 Top10",
            f"topk(10, (sum by (hostname, site_name, instance, vendor) ({in_rate} * 8) + sum by (hostname, site_name, instance, vendor) ({out_rate} * 8)))",
            0, 19, 12, 8, unit="bps",
            transformations=clean_organize_transformation("总流量")
        ),
        timeseries_panel(13, "错误/丢弃趋势", [
            {"expr": f"sum(rate(ifInErrors{{{sel}}}[5m])) + sum(rate(ifOutErrors{{{sel}}}[5m]))", "legendFormat": "错误包/秒", "refId": "A"},
            {"expr": f"sum(rate(ifInDiscards{{{sel}}}[5m])) + sum(rate(ifOutDiscards{{{sel}}}[5m]))", "legendFormat": "丢弃包/秒", "refId": "B"}
        ], 12, 19, 12, 8, unit="pps", color_overrides=[
            timeseries_color_override("byName", "错误包/秒", ERROR_COLOR),
            timeseries_color_override("byName", "丢弃包/秒", DISCARD_COLOR),
        ]),
        table_panel(
            14, "异常接口 Top20",
            f"topk(20, {anomaly_rows}) or {anomaly_fallback}",
            0, 27, 24, 8,
            transformations=clean_organize_transformation("运行状态"),
            value_col_name="运行状态",
            value_mappings=ANOMALY_VALUE_MAPPINGS,
            detail_link=True,
            color_mapped_cells=True,
        )
    ]

    panels = insert_section_rows(panels, [
        ("网络健康与规模", 0),
        ("趋势与设备健康", 3),
        ("流量排行与链路质量", 19),
        ("需要关注的接口", 27),
    ])

    return {
        "annotations": {"list": []},
        "editable": false,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": panels,
        "refresh": "30s",
        "schemaVersion": 39,
        "tags": ["nexora", "network", "overview"],
        "templating": {
            "list": make_network_variables()
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "01 网络总览（Network Overview）",
        "uid": "nexora-network-overview",
        "version": DASHBOARD_VERSION
    }

# 2. Network Device Detail Dashboard
def build_device_dashboard():
    dev_sel = f'{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    in_rate = counter_rate_expr("ifHCInOctets", "ifInOctets", dev_sel)
    out_rate = counter_rate_expr("ifHCOutOctets", "ifOutOctets", dev_sel)
    dev_if_join = filtered_interface_join(dev_sel)
    hw_cpu = (
        f"cpmCPUTotal1minRev{{{dev_sel}}} or hh3cEntityExtCpuUsage{{{dev_sel}}} or "
        f"hwEntityCpuUsage{{{dev_sel}}} or ruijieCpuCostRate{{{dev_sel}}} or "
        f"jnxOperatingCPU{{{dev_sel}}} or fnSysCpuUsage{{{dev_sel}}} or "
        f"zteCpuRate{{{dev_sel}}} or mpCpuUtilization5Min{{{dev_sel}}} or "
        f"dptechCpuUsage{{{dev_sel}}} or hillstoneCPUUtilization{{{dev_sel}}} or "
        f"sangforCpuUsage{{{dev_sel}}} or dcnCpuUsage{{{dev_sel}}}"
    )
    hw_mem = (
        f"hh3cEntityExtMemUsage{{{dev_sel}}} or hwEntityMemUsage{{{dev_sel}}} or "
        f"(100 * ciscoMemoryPoolUsed{{{dev_sel}}} / (ciscoMemoryPoolUsed{{{dev_sel}}} + ciscoMemoryPoolFree{{{dev_sel}}})) or "
        f"ruijieMemoryPoolCurrentUtilization{{{dev_sel}}} or jnxOperatingBuffer{{{dev_sel}}} or "
        f"fnSysMemUsage{{{dev_sel}}} or zteMemRate{{{dev_sel}}} or "
        f"mpMemoryUtilization{{{dev_sel}}} or dptechMemUsage{{{dev_sel}}} or "
        f"hillstoneMemoryUtilization{{{dev_sel}}} or sangforMemUsage{{{dev_sel}}} or "
        f"dcnMemUsage{{{dev_sel}}}"
    )
    hw_temp = (
        f"hh3cEntityExtTemperature{{{dev_sel}}} or hwEntityTemperature{{{dev_sel}}} or "
        f"ruijieDeviceTemperature{{{dev_sel}}} or jnxOperatingTemp{{{dev_sel}}} or "
        f"zteTemperature{{{dev_sel}}} or "
        f"mpTemperature{{{dev_sel}}} or dptechTemperature{{{dev_sel}}} or "
        f"dcnTemperature{{{dev_sel}}}"
    )
    hw_cpu_avg = f"avg by (hostname, site_name, instance, vendor) ({hw_cpu})"
    hw_mem_avg = f"avg by (hostname, site_name, instance, vendor) ({hw_mem})"
    panels = [
        stat_panel(1, "系统运行时间 (Uptime)", f"sysUpTime{{{dev_sel}}} / 100", 0, 0, 6, 4, unit="s", color="#3274D9"),
        stat_panel(2, "平均 CPU 使用率", f"avg({hw_cpu})", 6, 0, 6, 4, unit="percent", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 70}, {"color": "red", "value": 85}]),
        stat_panel(3, "平均内存使用率", f"avg({hw_mem})", 12, 0, 6, 4, unit="percent", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 75}, {"color": "red", "value": 90}]),
        stat_panel(4, "设备整机温度", f"max({hw_temp})", 18, 0, 6, 4, unit="celsius", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 55}, {"color": "red", "value": 70}]),
        timeseries_panel(5, "CPU 平均使用率走势 (多核/主备控)", [
            {"expr": hw_cpu_avg, "legendFormat": "{{site_name}} / {{hostname}} · {{vendor}}", "refId": "A"}
        ], 0, 4, 12, 8, unit="percent"),
        timeseries_panel(6, "内存平均使用率与池走势", [
            {"expr": hw_mem_avg, "legendFormat": "{{site_name}} / {{hostname}} · {{vendor}}", "refId": "A"}
        ], 12, 4, 12, 8, unit="percent"),
        timeseries_panel(7, "板卡与环境温度传感器监控", [
            {"expr": hw_temp, "legendFormat": "{{site_name}} / {{hostname}} · {{vendor}}", "refId": "A"}
        ], 0, 12, 12, 8, unit="celsius"),
        table_panel(
            8, "设备端口实时状态清单", f"ifOperStatus{{{dev_sel}}} {dev_if_join}", 12, 12, 12, 8,
            transformations=clean_organize_transformation(
                "运行状态", interface_description_label="ifAlias"
            ),
            value_col_name="运行状态",
            value_mappings=STATUS_VALUE_MAPPINGS,
            color_mapped_cells=True,
            detail_link=True,
        ),
        timeseries_panel(9, "设备接口流量走势", [
            {"expr": f"sum by (hostname, site_name, ifName) ({in_rate} * 8 {dev_if_join})", "legendFormat": "{{site_name}} / {{hostname}} / {{ifName}} 入流量", "refId": "A"},
            {"expr": f"sum by (hostname, site_name, ifName) ({out_rate} * 8 {dev_if_join})", "legendFormat": "{{site_name}} / {{hostname}} / {{ifName}} 出流量", "refId": "B"}
        ], 0, 20, 24, 8, unit="bps", color_overrides=[
            timeseries_color_override("byRegexp", ".*入流量$", INBOUND_COLOR),
            timeseries_color_override("byRegexp", ".*出流量$", OUTBOUND_COLOR),
        ])
    ]

    return {
        "annotations": {"list": []},
        "editable": false,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": panels,
        "refresh": "30s",
        "schemaVersion": 39,
        "tags": ["nexora", "network", "device"],
        "templating": {
            "list": make_network_variables(multi_device=False, include_all_device=False)
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "02 网络设备详情 (Network Device Detail)",
        "uid": "nexora-network-device",
        "version": DASHBOARD_VERSION
    }

# 3. Wireless Monitoring Dashboard
def build_wireless_dashboard():
    sel = f'{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    # Cisco/Aruba/Ruckus expose active/up APs but not a configured total in the
    # catalog, so they must not be used as the denominator for offline APs.
    ap_all = f"(hwWlanApTotalNum{{{sel}}} or hh3cDot11TotalAPNum{{{sel}}} or ruijieApcTotalApNum{{{sel}}})"
    ap_online = f"(hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}})"
    ap_offline = f"((hwWlanApTotalNum{{{sel}}} - hwWlanCurOnlineApNum{{{sel}}}) or (hh3cDot11TotalAPNum{{{sel}}} - hh3cDot11CurrOnlineAPNum{{{sel}}}) or (ruijieApcTotalApNum{{{sel}}} - ruijieApcOnlineApNum{{{sel}}}))"
    clients = f"(hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}})"
    client_per_ap = f"({clients}) / clamp_min(({ap_online}), 1)"

    panels = [
        stat_panel(1, "已提供总量的 AP 数", f"sum({ap_all}) or vector(0)", 0, 0, 6, 4, color="#3274D9"),
        stat_panel(2, "当前在线 AP 总数", f"sum({ap_online}) or vector(0)", 6, 0, 6, 4, color="#56A64B"),
        stat_panel(3, "可计算的离线 AP 数", f"sum({ap_offline}) or vector(0)", 12, 0, 6, 4, thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 1}, {"color": "red", "value": 5}]),
        stat_panel(4, "全网在线关联无线终端", f"sum({clients}) or vector(0)", 18, 0, 6, 4, color="#A352CC"),
        timeseries_panel(5, "无线 AP 在线规模趋势", [
            {"expr": f"sum({ap_online})", "legendFormat": "在线 AP 数", "refId": "A"}
        ], 0, 4, 12, 8, unit="short"),
        timeseries_panel(6, "关联终端客户数走势", [
            {"expr": f"sum({clients})", "legendFormat": "关联终端数", "refId": "A"}
        ], 12, 4, 12, 8, unit="short"),
        table_panel(
            7, "无线控制器终端数排行 Top 10",
            f"topk(10, {clients})",
            0, 12, 12, 8, unit="short",
            transformations=clean_organize_transformation("终端数量")
        ),
        table_panel(
            8, "无线控制器客户端 / AP 比例 Top 10",
            f"topk(10, {client_per_ap})",
            12, 12, 12, 8, unit="short",
            transformations=clean_organize_transformation("客户端 / AP")
        ),
        stat_panel(9, "在线客户端 / 在线 AP", f"sum({clients}) / clamp_min(sum({ap_online}), 1)", 0, 20, 6, 4, unit="short", color="#A352CC"),
        table_panel(
            10, "无线控制器在线 AP 排行 Top 10",
            f"topk(10, {ap_online})",
            6, 20, 18, 8, unit="short",
            transformations=clean_organize_transformation("在线 AP 数")
        )
    ]

    return {
        "annotations": {"list": []},
        "editable": false,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": panels,
        "refresh": "30s",
        "schemaVersion": 39,
        "tags": ["nexora", "network", "wireless"],
        "templating": {
            "list": make_network_variables()
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "03 无线专网监控 (Wireless AP & Clients)",
        "uid": "nexora-network-wireless",
        "version": DASHBOARD_VERSION
    }

# 4. Interface Traffic & Health Dashboard
def build_interface_dashboard():
    sel = f'{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    if_filter = f'{sel},ifName=~"$interface",interface_role=~"$interface_role"'
    in_rate = counter_rate_expr("ifHCInOctets", "ifInOctets", sel)
    out_rate = counter_rate_expr("ifHCOutOctets", "ifOutOctets", sel)
    if_join = filtered_interface_join(if_filter, alias_selector=sel, fallback_status=False)
    error_rate = interface_rate_sum(["ifInErrors", "ifOutErrors"], sel, if_join)
    discard_rate = interface_rate_sum(["ifInDiscards", "ifOutDiscards"], sel, if_join)
    in_packets = interface_rate_sum(
        ["ifHCInUcastPkts", "ifHCInMulticastPkts", "ifHCInBroadcastPkts"], sel, if_join
    )
    out_packets = interface_rate_sum(
        ["ifHCOutUcastPkts", "ifHCOutMulticastPkts", "ifHCOutBroadcastPkts"], sel, if_join
    )
    total_packets = f"({in_packets} + {out_packets})"
    error_pct = f"(100 * ({error_rate}) / clamp_min(({total_packets}), 1))"
    discard_pct = f"(100 * ({discard_rate}) / clamp_min(({total_packets}), 1))"
    speed_bps = f'(((ifHighSpeed{{{if_filter}}} > 0) * 1000000) or (ifSpeed{{{if_filter}}} > 0))'
    util_in = f'(({in_rate} * 8) / {speed_bps} * 100)'
    util_out = f'(({out_rate} * 8) / {speed_bps} * 100)'
    profile_labels = "instance, hostname, site_name, vendor, role, ifIndex, ifName, ifAlias, interface_role, utilization_warn_pct, utilization_high_pct, utilization_critical_pct"
    def max_across_directions(in_expr, out_expr):
        tagged = (
            f'label_replace({in_expr}, "direction", "in", "", "") or '
            f'label_replace({out_expr}, "direction", "out", "", "")'
        )
        return f"max by ({profile_labels}) ({tagged})"

    current_util = max_across_directions(f"{util_in} {if_join}", f"{util_out} {if_join}")
    peak_util = max_across_directions(
        f"max_over_time(({util_in} {if_join})[24h:])",
        f"max_over_time(({util_out} {if_join})[24h:])",
    )
    p95_util = max_across_directions(
        f"quantile_over_time(0.95, ({util_in} {if_join})[24h:])",
        f"quantile_over_time(0.95, ({util_out} {if_join})[24h:])",
    )
    capacity_bps = f"max by ({profile_labels}) ({speed_bps} {if_join})"
    capacity_rows = " or ".join(
        f'label_replace(({expr}), "capacity_stat", "{label}", "", "")'
        for expr, label in (
            (current_util, "当前利用率"),
            (peak_util, "24h峰值利用率"),
            (p95_util, "24h P95利用率"),
        )
    )
    quality_rows = (
        f'label_replace(({error_pct}), "quality_type", "错误包百分比", "", "") or '
        f'label_replace(({discard_pct}), "quality_type", "丢弃包百分比", "", "")'
    )
    packet_types = " or ".join(
        f'label_replace(({expr}), "packet_type", "{label}", "", "")'
        for expr, label in (
            (in_packets, "入向"),
            (out_packets, "出向"),
            (interface_rate_sum(["ifHCInUcastPkts", "ifHCOutUcastPkts"], sel, if_join), "单播"),
            (interface_rate_sum(["ifHCInMulticastPkts", "ifHCOutMulticastPkts"], sel, if_join), "组播"),
            (interface_rate_sum(["ifHCInBroadcastPkts", "ifHCOutBroadcastPkts"], sel, if_join), "广播"),
        )
    )
    flap_24h = f"changes(ifOperStatus{{{if_filter}}}[24h]) {if_join}"
    flap_7d = f"changes(ifOperStatus{{{if_filter}}}[7d]) {if_join}"
    # IF-MIB TimeTicks and sysUpTime wrap at 2^32 centiseconds. Modulo keeps
    # the elapsed seconds non-negative across one wrap (sampling gaps still
    # limit the flap count resolution).
    last_change_age = (
        f"(((sysUpTime{{{sel}}} - on(instance) group_right(ifIndex, ifName, ifAlias, interface_role, "
        f"utilization_warn_pct, utilization_high_pct, utilization_critical_pct) ifLastChange{{{if_filter}}}) "
        f"+ 4294967296) % 4294967296) / 100"
    )
    status_rows = f"ifOperStatus{{{if_filter}}} {if_join}"

    panels = [
        row_panel(901, "实时流量与吞吐", 0),
        stat_panel(1, "接口入流量", f"sum({in_rate} {if_join}) * 8", 0, 1, 6, 3, unit="bps", color=INBOUND_COLOR),
        stat_panel(2, "接口出流量", f"sum({out_rate} {if_join}) * 8", 6, 1, 6, 3, unit="bps", color=OUTBOUND_COLOR),
        stat_panel(3, "错误包速率", f"sum({error_rate})", 12, 1, 6, 3, unit="pps", color=ERROR_COLOR),
        stat_panel(4, "丢弃包速率", f"sum({discard_rate})", 18, 1, 6, 3, unit="pps", color=DISCARD_COLOR),
        timeseries_panel(5, "接口流量趋势", [
            {"expr": f"sum by (hostname, site_name, ifName) ({in_rate} * 8 {if_join})", "legendFormat": "{{site_name}} / {{hostname}} / {{ifName}} 入向", "refId": "A"},
            {"expr": f"sum by (hostname, site_name, ifName) ({out_rate} * 8 {if_join})", "legendFormat": "{{site_name}} / {{hostname}} / {{ifName}} 出向", "refId": "B"},
        ], 0, 4, 24, 7, unit="bps", color_overrides=[
            timeseries_color_override("byRegexp", ".*入向$", INBOUND_COLOR),
            timeseries_color_override("byRegexp", ".*出向$", OUTBOUND_COLOR),
        ]),
        row_panel(902, "容量与利用率", 11),
        table_panel(
            6, "当前 / 24h 峰值 / 24h P95 利用率",
            capacity_rows,
            0, 12, 12, 7, unit="percent",
            transformations=[{
                "id": "organize",
                "options": {
                    "excludeByName": {"Time": True, "__name__": True, "ifIndex": True, "instance": True, "direction": True, "ifDescr": True},
                    "renameByName": {
                        "capacity_stat": "指标", "ifName": "接口全称", "ifAlias": "接口描述",
                        "hostname": "设备名称", "site_name": "站点", "vendor": "厂商", "role": "设备角色",
                        "interface_role": "接口角色", "utilization_warn_pct": "预警阈值 (%)",
                        "utilization_high_pct": "高位阈值 (%)", "utilization_critical_pct": "严重阈值 (%)",
                        "Value": "利用率 (%)",
                    },
                    "indexByName": {"hostname": 0, "site_name": 1, "ifName": 2, "capacity_stat": 3, "Value": 4, "interface_role": 5, "utilization_warn_pct": 6, "utilization_high_pct": 7, "utilization_critical_pct": 8},
                },
            }],
            value_col_name="利用率 (%)", gauge=True, thresholds=UTILIZATION_THRESHOLDS,
            detail_link=True,
        ),
        table_panel(
            16, "接口配置带宽", capacity_bps, 12, 12, 12, 7, unit="bps",
            transformations=clean_organize_transformation("带宽 (bps)", interface_description_label="ifAlias"),
            value_col_name="带宽 (bps)", detail_link=True,
        ),
        table_panel(
            7, "入向利用率 Top20",
            f"topk(20, {util_in} {if_join})",
            0, 19, 12, 7, unit="percent",
            transformations=clean_organize_transformation("利用率 (%)", interface_description_label="ifAlias"),
            value_col_name="利用率 (%)", gauge=True, thresholds=UTILIZATION_THRESHOLDS, detail_link=True,
        ),
        table_panel(
            8, "出向利用率 Top20",
            f"topk(20, {util_out} {if_join})",
            12, 19, 12, 7, unit="percent",
            transformations=clean_organize_transformation("利用率 (%)", interface_description_label="ifAlias"),
            value_col_name="利用率 (%)", gauge=True, thresholds=UTILIZATION_THRESHOLDS, detail_link=True,
        ),
        row_panel(903, "链路质量", 26),
        table_panel(
            9, "错误包 / 丢弃包百分比 Top20",
            f"topk(20, ({quality_rows}))",
            0, 27, 12, 7, unit="percent",
            transformations=[{
                "id": "organize", "options": {
                    "excludeByName": {"Time": True, "__name__": True, "ifIndex": True, "instance": True, "direction": True, "ifDescr": True},
                    "renameByName": {"quality_type": "质量指标", "ifName": "接口全称", "ifAlias": "接口描述", "hostname": "设备名称", "site_name": "站点", "vendor": "厂商", "role": "设备角色", "interface_role": "接口角色", "utilization_warn_pct": "预警阈值 (%)", "utilization_high_pct": "高位阈值 (%)", "utilization_critical_pct": "严重阈值 (%)", "Value": "百分比 (%)"},
                },
            }],
            value_col_name="百分比 (%)", detail_link=True,
        ),
        timeseries_panel(10, "错误与丢弃包速率", [
            {"expr": f"sum by (hostname, site_name) ({error_rate})", "legendFormat": "{{site_name}} / {{hostname}} 错误 PPS", "refId": "A"},
            {"expr": f"sum by (hostname, site_name) ({discard_rate})", "legendFormat": "{{site_name}} / {{hostname}} 丢弃 PPS", "refId": "B"},
        ], 12, 27, 12, 7, unit="pps", color_overrides=[
            timeseries_color_override("byRegexp", ".*错误 PPS$", ERROR_COLOR),
            timeseries_color_override("byRegexp", ".*丢弃 PPS$", DISCARD_COLOR),
        ]),
        timeseries_panel(11, "入向 / 出向 / 单播 / 组播 / 广播 PPS", [
            {"expr": f"sum by (packet_type) ({packet_types})", "legendFormat": "{{packet_type}} PPS", "refId": "A"},
        ], 0, 34, 24, 7, unit="pps", color_overrides=[
            timeseries_color_override("byRegexp", "入向 PPS", INBOUND_COLOR),
            timeseries_color_override("byRegexp", "出向 PPS", OUTBOUND_COLOR),
            timeseries_color_override("byRegexp", "单播 PPS", PPS_COLOR),
            timeseries_color_override("byRegexp", "组播 PPS", MULTICAST_COLOR),
            timeseries_color_override("byRegexp", "广播 PPS", BROADCAST_COLOR),
        ]),
        row_panel(904, "状态与抖动", 41),
        table_panel(
            12, "接口 Flap 次数：24h / 7d",
            flap_24h,
            0, 42, 12, 7,
            targets=[
                {"expr": flap_24h, "format": "table", "instant": True, "legendFormat": "24h", "refId": "A"},
                {"expr": flap_7d, "format": "table", "instant": True, "legendFormat": "7d", "refId": "B"},
            ],
            transformations=[{
                "id": "joinByLabels", "options": {"labels": ["instance", "hostname", "site_name", "ifIndex", "ifName", "ifAlias", "interface_role", "utilization_warn_pct", "utilization_high_pct", "utilization_critical_pct"]},
            }, {
                "id": "organize", "options": {"excludeByName": {"Time": True, "instance": True, "ifIndex": True, "ifDescr": True}, "renameByName": {"ifName": "接口全称", "ifAlias": "接口描述", "hostname": "设备名称", "site_name": "站点", "Value #A": "24h Flap", "Value #B": "7d Flap"}},
            }],
            value_col_name="24h Flap", detail_link=True,
        ),
        table_panel(
            13, "距上次接口状态变化时间",
            last_change_age,
            12, 42, 12, 7, unit="s",
            transformations=clean_organize_transformation("距上次变化 (秒)", interface_description_label="ifAlias"),
            value_col_name="距上次变化 (秒)", detail_link=True,
        ),
        table_panel(
            14, "接口运行状态",
            status_rows,
            0, 49, 24, 7,
            transformations=clean_organize_transformation("运行状态", interface_description_label="ifAlias"),
            value_col_name="运行状态", value_mappings=STATUS_VALUE_MAPPINGS,
            color_mapped_cells=True, detail_link=True,
        ),
    ]

    return {
        "annotations": {"list": []},
        "editable": false,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": panels,
        "refresh": "30s",
        "schemaVersion": 39,
        "tags": ["nexora", "network", "interface"],
        "templating": {
            "list": make_interface_variables()
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "04 接口流量与健康（Interface Traffic & Health）",
        "uid": "nexora-network-interface",
        "version": DASHBOARD_VERSION
    }

# 4a. Interface detail drill-down dashboard
def build_interface_detail_dashboard():
    base_sel = f'{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    sel = f'{base_sel},ifName=~"$interface",interface_role=~"$interface_role"'
    in_rate = counter_rate_expr("ifHCInOctets", "ifInOctets", sel)
    out_rate = counter_rate_expr("ifHCOutOctets", "ifOutOctets", sel)
    join = filtered_interface_join(sel, alias_selector=base_sel, fallback_status=False)
    error_rate = interface_rate_sum(["ifInErrors", "ifOutErrors"], sel, join)
    discard_rate = interface_rate_sum(["ifInDiscards", "ifOutDiscards"], sel, join)
    in_packets = interface_rate_sum(["ifHCInUcastPkts", "ifHCInMulticastPkts", "ifHCInBroadcastPkts"], sel, join)
    out_packets = interface_rate_sum(["ifHCOutUcastPkts", "ifHCOutMulticastPkts", "ifHCOutBroadcastPkts"], sel, join)
    total_packets = f"({in_packets} + {out_packets})"
    error_pct = f"(100 * ({error_rate}) / clamp_min(({total_packets}), 1))"
    discard_pct = f"(100 * ({discard_rate}) / clamp_min(({total_packets}), 1))"
    speed = f'(((ifHighSpeed{{{sel}}} > 0) * 1000000) or (ifSpeed{{{sel}}} > 0))'
    util_in = f'(({in_rate} * 8) / {speed} * 100)'
    util_out = f'(({out_rate} * 8) / {speed} * 100)'
    labels = "instance, hostname, site_name, vendor, role, ifIndex, ifName, ifAlias, interface_role, utilization_warn_pct, utilization_high_pct, utilization_critical_pct"
    current = f"max by ({labels}) (label_replace({util_in} {join}, \"direction\", \"in\", \"\", \"\") or label_replace({util_out} {join}, \"direction\", \"out\", \"\", \"\"))"
    peak = f"max by ({labels}) (label_replace(max_over_time(({util_in} {join})[24h:]), \"direction\", \"in\", \"\", \"\") or label_replace(max_over_time(({util_out} {join})[24h:]), \"direction\", \"out\", \"\", \"\"))"
    p95 = f"max by ({labels}) (label_replace(quantile_over_time(0.95, ({util_in} {join})[24h:]), \"direction\", \"in\", \"\", \"\") or label_replace(quantile_over_time(0.95, ({util_out} {join})[24h:]), \"direction\", \"out\", \"\", \"\"))"
    packets_by_type = " or ".join(
        f'label_replace(({expr}), "packet_type", "{name}", "", "")'
        for expr, name in (
            (in_packets, "入向"),
            (out_packets, "出向"),
            (interface_rate_sum(["ifHCInUcastPkts", "ifHCOutUcastPkts"], sel, join), "单播"),
            (interface_rate_sum(["ifHCInMulticastPkts", "ifHCOutMulticastPkts"], sel, join), "组播"),
            (interface_rate_sum(["ifHCInBroadcastPkts", "ifHCOutBroadcastPkts"], sel, join), "广播"),
        )
    )
    quality = (
        f'label_replace(({error_pct}), "quality_type", "错误包百分比", "", "") or '
        f'label_replace(({discard_pct}), "quality_type", "丢弃包百分比", "", "")'
    )
    flap_24h = f"changes(ifOperStatus{{{sel}}}[24h]) {join}"
    flap_7d = f"changes(ifOperStatus{{{sel}}}[7d]) {join}"
    last_change_age = (
        f"(((sysUpTime{{{NETWORK_JOB},site_name=~\"$site\",vendor=~\"$vendor\",role=~\"$role\",hostname=~\"$device\"}} "
        f"- on(instance) group_right(ifIndex, ifName, ifAlias, interface_role, utilization_warn_pct, utilization_high_pct, utilization_critical_pct) ifLastChange{{{sel}}}) "
        f"+ 4294967296) % 4294967296) / 100"
    )
    warn = "$utilization_warn_pct"
    high = "$utilization_high_pct"
    critical = "$utilization_critical_pct"
    threshold_state = (
        f"(({current} >= {critical}) * 0 + 3) or "
        f"((({current} < {critical}) and ({current} >= {high})) * 0 + 2) or "
        f"((({current} < {high}) and ({current} >= {warn})) * 0 + 1) or "
        f"(({current} < {warn}) * 0)"
    )
    threshold_state_mappings = [{
        "type": "value",
        "options": {
            "0": {"text": "NORMAL", "color": "green"},
            "1": {"text": "WARNING", "color": "yellow"},
            "2": {"text": "HIGH", "color": "orange"},
            "3": {"text": "CRITICAL", "color": "red"},
        },
    }]

    panels = [
        row_panel(901, "实时状态与流量", 0),
        stat_panel(1, "入向带宽", f"sum({in_rate} {join}) * 8", 0, 1, 4, 3, unit="bps", color=INBOUND_COLOR),
        stat_panel(2, "出向带宽", f"sum({out_rate} {join}) * 8", 4, 1, 4, 3, unit="bps", color=OUTBOUND_COLOR),
        stat_panel(3, "入向利用率", f"max({util_in} {join})", 8, 1, 4, 3, unit="percent", thresholds=UTILIZATION_THRESHOLDS),
        stat_panel(4, "出向利用率", f"max({util_out} {join})", 12, 1, 4, 3, unit="percent", thresholds=UTILIZATION_THRESHOLDS),
        stat_panel(5, "错误包速率", f"sum({error_rate})", 16, 1, 4, 3, unit="pps", color=ERROR_COLOR),
        stat_panel(6, "丢弃包速率", f"sum({discard_rate})", 20, 1, 4, 3, unit="pps", color=DISCARD_COLOR),
        timeseries_panel(7, "接口流量走势", [
            {"expr": f"{in_rate} * 8 {join}", "legendFormat": "入向带宽", "refId": "A"},
            {"expr": f"{out_rate} * 8 {join}", "legendFormat": "出向带宽", "refId": "B"},
        ], 0, 4, 24, 7, unit="bps", color_overrides=[
            timeseries_color_override("byName", "入向带宽", INBOUND_COLOR),
            timeseries_color_override("byName", "出向带宽", OUTBOUND_COLOR),
        ]),
        timeseries_panel(15, "入向 / 出向利用率走势", [
            {"expr": f"{util_in} {join}", "legendFormat": "入向利用率", "refId": "A"},
            {"expr": f"{util_out} {join}", "legendFormat": "出向利用率", "refId": "B"},
        ], 0, 11, 24, 7, unit="percent", color_overrides=[
            timeseries_color_override("byName", "入向利用率", INBOUND_COLOR),
            timeseries_color_override("byName", "出向利用率", OUTBOUND_COLOR),
        ]),
        row_panel(902, "容量画像", 18),
        table_panel(
            8, "当前 / 24h 峰值 / 24h P95 利用率", " or ".join(
                f'label_replace(({expr}), "capacity_stat", "{name}", "", "")'
                for expr, name in ((current, "当前利用率"), (peak, "24h峰值利用率"), (p95, "24h P95利用率"))
            ), 0, 19, 12, 7, unit="percent",
            transformations=[{
                "id": "organize", "options": {
                    "excludeByName": {"Time": True, "__name__": True, "ifIndex": True, "instance": True, "direction": True},
                    "renameByName": {"capacity_stat": "指标", "ifName": "接口全称", "ifAlias": "接口描述", "hostname": "设备名称", "site_name": "站点", "vendor": "厂商", "role": "设备角色", "interface_role": "接口角色", "utilization_warn_pct": "预警阈值 (%)", "utilization_high_pct": "高位阈值 (%)", "utilization_critical_pct": "严重阈值 (%)", "Value": "利用率 (%)"},
                },
            }],
            value_col_name="利用率 (%)", gauge=True, thresholds=UTILIZATION_THRESHOLDS,
        ),
        table_panel(
            17, "接口配置带宽", f"max by ({labels}) ({speed} {join})", 12, 19, 12, 7, unit="bps",
            transformations=clean_organize_transformation("带宽 (bps)", interface_description_label="ifAlias"),
            value_col_name="带宽 (bps)",
        ),
        timeseries_panel(9, "入向 / 出向 / 单播 / 组播 / 广播 PPS", [
            {"expr": f"sum by (packet_type) ({packets_by_type})", "legendFormat": "{{packet_type}} PPS", "refId": "A"},
        ], 0, 27, 12, 7, unit="pps", color_overrides=[
            timeseries_color_override("byRegexp", "入向 PPS", INBOUND_COLOR),
            timeseries_color_override("byRegexp", "出向 PPS", OUTBOUND_COLOR),
            timeseries_color_override("byRegexp", "单播 PPS", PPS_COLOR),
            timeseries_color_override("byRegexp", "组播 PPS", MULTICAST_COLOR),
            timeseries_color_override("byRegexp", "广播 PPS", BROADCAST_COLOR),
        ]),
        timeseries_panel(10, "错误 / 丢弃包速率走势", [
            {"expr": f"sum({error_rate})", "legendFormat": "错误 PPS", "refId": "A"},
            {"expr": f"sum({discard_rate})", "legendFormat": "丢弃 PPS", "refId": "B"},
        ], 12, 27, 12, 7, unit="pps", color_overrides=[
            timeseries_color_override("byRegexp", ".*错误 PPS$", ERROR_COLOR),
            timeseries_color_override("byRegexp", ".*丢弃 PPS$", DISCARD_COLOR),
        ]),
        row_panel(903, "质量与稳定性", 26),
        row_panel(904, "接口状态", 48),
        table_panel(
            11, "错误包 / 丢弃包百分比", quality, 0, 41, 12, 7, unit="percent",
            transformations=[{"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True, "instance": True, "ifIndex": True}, "renameByName": {"quality_type": "质量指标", "ifName": "接口全称", "ifAlias": "接口描述", "hostname": "设备名称", "site_name": "站点", "Value": "百分比 (%)"}}}],
            value_col_name="百分比 (%)",
        ),
        table_panel(
            12, "接口 Flap 次数：24h / 7d", flap_24h, 12, 41, 12, 7,
            targets=[{"expr": flap_24h, "format": "table", "instant": True, "refId": "A"}, {"expr": flap_7d, "format": "table", "instant": True, "refId": "B"}],
            transformations=[{"id": "joinByLabels", "options": {"labels": ["instance", "hostname", "site_name", "ifIndex", "ifName", "ifAlias", "interface_role"]}}, {"id": "organize", "options": {"excludeByName": {"Time": True, "instance": True, "ifIndex": True}, "renameByName": {"ifName": "接口全称", "ifAlias": "接口描述", "hostname": "设备名称", "site_name": "站点", "Value #A": "24h Flap", "Value #B": "7d Flap"}}}],
            value_col_name="24h Flap",
        ),
        table_panel(
            13, "距上次接口状态变化时间", last_change_age, 0, 49, 12, 7, unit="s",
            transformations=clean_organize_transformation("距上次变化 (秒)", interface_description_label="ifAlias"),
            value_col_name="距上次变化 (秒)",
        ),
        table_panel(
            14, "接口运行状态", f"ifOperStatus{{{sel}}} {join}", 12, 49, 12, 7,
            transformations=clean_organize_transformation("运行状态", interface_description_label="ifAlias"),
            value_col_name="运行状态", value_mappings=STATUS_VALUE_MAPPINGS, color_mapped_cells=True,
        ),
        row_panel(905, "CMDB 利用率阈值判断", 56),
        table_panel(
            16, "当前利用率状态（按接口配置阈值）", threshold_state, 0, 57, 24, 7,
            transformations=clean_organize_transformation("阈值状态", interface_description_label="ifAlias"),
            value_col_name="阈值状态", value_mappings=threshold_state_mappings,
            color_mapped_cells=True,
        ),
    ]
    return {
        "annotations": {"list": []}, "editable": false, "fiscalYearStartMonth": 0,
        "graphTooltip": 1, "id": None, "links": [], "panels": panels,
        "refresh": "30s", "schemaVersion": 39,
        "tags": ["nexora", "network", "interface", "detail"],
        "templating": {"list": make_interface_variables(multi_device=False, include_all_device=False, include_all_interface=False, multi_interface=False, include_threshold_values=True)},
        "time": {"from": "now-24h", "to": "now"}, "timezone": "browser",
        "title": "09 接口详情（Interface Detail）",
        "description": "从网络总览或接口排行进入，链接会携带站点、设备、接口筛选和时间范围。",
        "uid": "nexora-interface-detail", "version": DASHBOARD_VERSION,
    }

# 5. Monitoring Engine Health Dashboard
def build_health_dashboard():
    panels = [
        stat_panel(1, "SNMP 在线目标", f"count(count by (instance) (up{{{NETWORK_JOB}}})) or vector(0)", 0, 0, 6, 4, color="#56A64B"),
        stat_panel(2, "SNMP 失败目标", f"count(count by (instance) (up{{{NETWORK_JOB}}} == 0)) or vector(0)", 6, 0, 6, 4, thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}]),
        stat_panel(3, "平均 SNMP 采集耗时", f"avg(scrape_duration_seconds{{{NETWORK_JOB}}}) or vector(0)", 12, 0, 6, 4, unit="s", color="#3274D9"),
        stat_panel(4, "最大 SNMP 采集耗时", f"max(scrape_duration_seconds{{{NETWORK_JOB}}}) or vector(0)", 18, 0, 6, 4, unit="s", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 5}, {"color": "red", "value": 15}]),
        timeseries_panel(5, "各设备 SNMP 采集耗时分布 (秒)", [
            {"expr": f"scrape_duration_seconds{{{NETWORK_JOB}}}", "legendFormat": "{{site_name}} / {{hostname}}", "refId": "A"}
        ], 0, 4, 12, 8, unit="s"),
        timeseries_panel(6, "抓取指标量统计 (Samples Scraped)", [
            {"expr": f"scrape_samples_scraped{{{NETWORK_JOB}}}", "legendFormat": "{{site_name}} / {{hostname}}", "refId": "A"}
        ], 12, 4, 12, 8, unit="short"),
        table_panel(
            7, "采集失败设备清单 (Target Scrape Failure)", f"up{{{NETWORK_JOB}}} == 0", 0, 12, 12, 8,
            transformations=clean_organize_transformation("探测状态")
        ),
        table_panel(
            8, "采集最慢目标排行 Top 10", f"topk(10, scrape_duration_seconds{{{NETWORK_JOB}}})", 12, 12, 12, 8, unit="s",
            transformations=clean_organize_transformation("采集耗时 (秒)")
        )
    ]

    return {
        "annotations": {"list": []},
        "editable": false,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": panels,
        "refresh": "30s",
        "schemaVersion": 39,
        "tags": ["nexora", "monitoring", "health"],
        "templating": {"list": []},
        "time": {"from": "now-1h", "to": "now"},
        "timezone": "browser",
        "title": "05 SNMP 采集健康 (SNMP Scrape Health)",
        "uid": "nexora-monitoring-health",
        "version": DASHBOARD_VERSION
    }

# 6. Internet Outbound & WAN Dashboard
def build_outbound_dashboard():
    # IF-MIB has no authoritative WAN-role label.  Require an explicit device
    # and interface selection instead of silently treating every port as WAN.
    sel = f'{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device",interface_role=~"$interface_role"'
    if_filter = f'{sel},ifName=~"$interface"'
    in_rate = counter_rate_expr("ifHCInOctets", "ifInOctets", sel)
    out_rate = counter_rate_expr("ifHCOutOctets", "ifOutOctets", sel)
    if_join = filtered_interface_join(if_filter, alias_selector=sel, fallback_status=False)
    error_rate = interface_rate_sum(["ifInErrors", "ifOutErrors"], sel, if_join)
    discard_rate = interface_rate_sum(["ifInDiscards", "ifOutDiscards"], sel, if_join)
    error_and_discard_rate = interface_rate_sum(
        ["ifInErrors", "ifOutErrors", "ifInDiscards", "ifOutDiscards"],
        sel,
        if_join,
    )
    speed_bps = f'(((ifHighSpeed{{{sel}}} > 0) * 1000000) or (ifSpeed{{{sel}}} > 0))'
    util_in = f'(({in_rate} * 8) / {speed_bps} * 100)'
    util_out = f'(({out_rate} * 8) / {speed_bps} * 100)'

    panels = [
        stat_panel(1, "出口总入向实时带宽 (Inbound)", f"sum({in_rate} {if_join}) * 8 or vector(0)", 0, 0, 4, 4, unit="bps", color=INBOUND_COLOR),
        stat_panel(2, "出口总出向实时带宽 (Outbound)", f"sum({out_rate} {if_join}) * 8 or vector(0)", 4, 0, 4, 4, unit="bps", color=OUTBOUND_COLOR),
        stat_panel(3, "出口最高入向利用率", f"max({util_in} {if_join}) or vector(0)", 8, 0, 4, 4, unit="percent", thresholds=UTILIZATION_THRESHOLDS),
        stat_panel(4, "出口最高出向利用率", f"max({util_out} {if_join}) or vector(0)", 12, 0, 4, 4, unit="percent", thresholds=UTILIZATION_THRESHOLDS),
        stat_panel(5, "出口链路错误与丢弃总速率", f"sum({error_rate} + {discard_rate}) or vector(0)", 16, 0, 4, 4, unit="pps", thresholds=[
            {"color": "green", "value": None}, {"color": "#E0B400", "value": 10}, {"color": "red", "value": 100}
        ]),
        stat_panel(6, "筛选接口数", f"count(count by (instance, ifIndex) (ifOperStatus{{{sel}}} {if_join})) or vector(0)", 20, 0, 4, 4, unit="none", color="#A352CC"),
        timeseries_panel(7, "出口设备入向流量趋势 (Inbound bps)", [
            {"expr": f"sum by (hostname, site_name) ({in_rate} * 8 {if_join})", "legendFormat": "{{site_name}} / {{hostname}} 入向", "refId": "A"}
        ], 0, 4, 12, 8, unit="bps", color_overrides=[
            timeseries_color_override("byRegexp", ".*入向$", INBOUND_COLOR),
        ]),
        timeseries_panel(8, "出口设备出向流量趋势 (Outbound bps)", [
            {"expr": f"sum by (hostname, site_name) ({out_rate} * 8 {if_join})", "legendFormat": "{{site_name}} / {{hostname}} 出向", "refId": "A"}
        ], 12, 4, 12, 8, unit="bps", color_overrides=[
            timeseries_color_override("byRegexp", ".*出向$", OUTBOUND_COLOR),
        ]),
        timeseries_panel(9, "出口端口入向利用率 Top 10", [
            {"expr": f"topk(10, {util_in} {if_join})", "legendFormat": "{{site_name}} / {{hostname}} / {{ifName}} 入向", "refId": "A"}
        ], 0, 12, 12, 8, unit="percent", color_overrides=[
            timeseries_color_override("byRegexp", ".*入向$", INBOUND_COLOR),
        ]),
        timeseries_panel(10, "出口端口出向利用率 Top 10", [
            {"expr": f"topk(10, {util_out} {if_join})", "legendFormat": "{{site_name}} / {{hostname}} / {{ifName}} 出向", "refId": "A"}
        ], 12, 12, 12, 8, unit="percent", color_overrides=[
            timeseries_color_override("byRegexp", ".*出向$", OUTBOUND_COLOR),
        ]),
        timeseries_panel(11, "出口链路错误与丢弃时序 (PPS)", [
            {"expr": f"sum by (hostname, site_name) ({error_rate})", "legendFormat": "{{site_name}} / {{hostname}} 错包/秒", "refId": "A"},
            {"expr": f"sum by (hostname, site_name) ({discard_rate})", "legendFormat": "{{site_name}} / {{hostname}} 丢弃/秒", "refId": "B"}
        ], 0, 20, 24, 8, unit="pps", color_overrides=[
            timeseries_color_override("byRegexp", ".*错包/秒$", ERROR_COLOR),
            timeseries_color_override("byRegexp", ".*丢弃/秒$", DISCARD_COLOR),
        ]),
        table_panel(
            12, "出口端口入向利用率排行 Top 10",
            f"topk(10, {util_in} {if_join})",
            0, 28, 12, 8, unit="percent",
            transformations=clean_organize_transformation("带宽利用率", interface_description_label="ifAlias"),
            value_col_name="带宽利用率",
            gauge=True,
            thresholds=UTILIZATION_THRESHOLDS,
        ),
        table_panel(
            13, "出口端口出向利用率排行 Top 10",
            f"topk(10, {util_out} {if_join})",
            12, 28, 12, 8, unit="percent",
            transformations=clean_organize_transformation("带宽利用率", interface_description_label="ifAlias"),
            value_col_name="带宽利用率",
            gauge=True,
            thresholds=UTILIZATION_THRESHOLDS,
        ),
        table_panel(
            14, "出口端口错误与丢弃排行 Top 10",
            f"topk(10, {error_and_discard_rate})",
            0, 36, 24, 8, unit="pps",
            transformations=clean_organize_transformation("错误/丢弃率 (pps)", interface_description_label="ifAlias"),
            value_col_name="错误/丢弃率 (pps)"
        )
    ]

    return {
        "annotations": {"list": []},
        "editable": false,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": panels,
        "refresh": "30s",
        "schemaVersion": 39,
        "tags": ["nexora", "network", "outbound", "wan"],
        "templating": {
            "list": make_interface_variables(
                include_all_device=False,
                include_all_interface=False,
                interface_label="出口接口",
                device_label="出口设备",
            )
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "06 互联网出口与 WAN（需选择出口接口） (Select WAN Interface)",
        "description": "此大盘必须先选择出口设备和一个或多个已确认的 WAN 接口；不会默认把全部设备或全部端口当作互联网出口。",
        "uid": "nexora-network-outbound",
        "version": DASHBOARD_VERSION
    }

def build_linux_dashboard():
    srv_sel = 'job="linux_servers",site_name=~"$site",hostname=~"$device"'
    panels = [
        stat_panel(1, "受纳管 Linux 主机数", f'count(count by (hostname) (up{{{srv_sel}}})) or vector(0)', 0, 0, 4, 4, unit="none", color="blue"),
        stat_panel(2, "系统平均运行时间 (Uptime)", f'avg(time() - node_boot_time_seconds{{{srv_sel}}}) or vector(0)', 4, 0, 4, 4, unit="s", color="#3274D9"),
        stat_panel(3, "平均 CPU 使用率", f'avg(100 - (avg by (hostname) (rate(node_cpu_seconds_total{{{srv_sel},mode="idle"}}[5m])) * 100)) or vector(0)', 8, 0, 4, 4, unit="percent", thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 70},
            {"color": "red", "value": 85}
        ]),
        stat_panel(4, "平均物理内存利用率", f'avg((1 - (node_memory_MemAvailable_bytes{{{srv_sel}}} / node_memory_MemTotal_bytes{{{srv_sel}}})) * 100) or vector(0)', 12, 0, 4, 4, unit="percent", thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 80},
            {"color": "red", "value": 90}
        ]),
        stat_panel(5, "TCP 活跃连接总数", f'sum(node_netstat_Tcp_CurrEstab{{{srv_sel}}}) or vector(0)', 16, 0, 4, 4, unit="none", color="purple"),
        stat_panel(6, "已打开文件句柄数", f'sum(node_filefd_allocated{{{srv_sel}}}) or vector(0)', 20, 0, 4, 4, unit="short", color="#56A64B", thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 20000},
            {"color": "red", "value": 100000}
        ]),

        timeseries_panel(7, "CPU 各状态利用率走势 (%)", [
            {"expr": f'100 - (avg by (hostname) (rate(node_cpu_seconds_total{{{srv_sel},mode="idle"}}[5m])) * 100)', "legendFormat": "{{site_name}} / {{hostname}} 整机 CPU 利用率 (%)", "refId": "A"},
            {"expr": f'avg by (hostname) (rate(node_cpu_seconds_total{{{srv_sel},mode="user"}}[5m])) * 100', "legendFormat": "{{site_name}} / {{hostname}} 用户态 (user %)", "refId": "B"},
            {"expr": f'avg by (hostname) (rate(node_cpu_seconds_total{{{srv_sel},mode="system"}}[5m])) * 100', "legendFormat": "{{site_name}} / {{hostname}} 系统态 (system %)", "refId": "C"},
            {"expr": f'avg by (hostname) (rate(node_cpu_seconds_total{{{srv_sel},mode="iowait"}}[5m])) * 100', "legendFormat": "{{site_name}} / {{hostname}} I/O等待 (iowait %)", "refId": "D"}
        ], 0, 4, 12, 8, unit="percent"),

        timeseries_panel(8, "物理内存与 Swap 分布走势", [
            {"expr": f'node_memory_MemTotal_bytes{{{srv_sel}}} - node_memory_MemAvailable_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 内存已用量", "refId": "A"},
            {"expr": f'node_memory_MemAvailable_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 可用物理内存", "refId": "B"},
            {"expr": f'node_memory_Cached_bytes{{{srv_sel}}} + node_memory_Buffers_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 缓冲与缓存 (Buffers+Cache)", "refId": "C"},
            {"expr": f'node_memory_SwapTotal_bytes{{{srv_sel}}} - node_memory_SwapFree_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} Swap 已用量", "refId": "D"},
            {"expr": f'node_memory_MemTotal_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 物理内存总量 (Total)", "refId": "E"}
        ], 12, 4, 12, 8, unit="bytes"),

        timeseries_panel(9, "系统平均负载走势 (Load1 / Load5 / Load15)", [
            {"expr": f'node_load1{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 1分钟负载 (Load1)", "refId": "A"},
            {"expr": f'node_load5{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 5分钟负载 (Load5)", "refId": "B"},
            {"expr": f'node_load15{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 15分钟负载 (Load15)", "refId": "C"},
            {"expr": f'count by (hostname) (node_cpu_seconds_total{{{srv_sel},mode="idle"}})', "legendFormat": "{{site_name}} / {{hostname}} 逻辑 CPU 核心数 (阈值参考)", "refId": "D"}
        ], 0, 12, 12, 8, unit="short"),

        timeseries_panel(10, "磁盘读写吞吐速率 (Bytes/s)", [
            {"expr": f'sum by (hostname, device) (rate(node_disk_read_bytes_total{{{srv_sel},device!~"loop.*|ram.*"}}[5m]))', "legendFormat": "{{site_name}} / {{hostname}} - {{device}} 读吞吐", "refId": "A"},
            {"expr": f'sum by (hostname, device) (rate(node_disk_written_bytes_total{{{srv_sel},device!~"loop.*|ram.*"}}[5m]))', "legendFormat": "{{site_name}} / {{hostname}} - {{device}} 写吞吐", "refId": "B"}
        ], 12, 12, 12, 8, unit="Bps"),

        table_panel(
            11, "主机磁盘空间利用率 Top 10",
            f'topk(10, max by (hostname, mountpoint) ((1 - (node_filesystem_avail_bytes{{{srv_sel},fstype!~"tmpfs|iso9660|squashfs",fstype!=""}} / node_filesystem_size_bytes{{{srv_sel}}})) * 100))',
            0, 20, 12, 8, unit="percent",
            transformations=clean_organize_transformation("磁盘使用率", {"mountpoint": "挂载点"})
        ),

        timeseries_panel(12, "服务器网卡流量走势 (bps)", [
            {"expr": f'sum by (hostname, device) (rate(node_network_receive_bytes_total{{{srv_sel},device!~"lo|docker.*|veth.*|br-.*"}}[5m]) * 8)', "legendFormat": "{{site_name}} / {{hostname}} - {{device}} 接收 (bps)", "refId": "A"},
            {"expr": f'sum by (hostname, device) (rate(node_network_transmit_bytes_total{{{srv_sel},device!~"lo|docker.*|veth.*|br-.*"}}[5m]) * 8)', "legendFormat": "{{site_name}} / {{hostname}} - {{device}} 发送 (bps)", "refId": "B"}
        ], 12, 20, 12, 8, unit="bps"),

        table_panel(
            13, "主机 TCP 活跃连接数 Top 10",
            f'topk(10, sum by (hostname) (node_netstat_Tcp_CurrEstab{{{srv_sel}}}))',
            0, 28, 12, 8, unit="none",
            transformations=clean_organize_transformation("活跃连接数")
        ),
        timeseries_panel(14, "系统进程调度与阻塞情况", [
            {"expr": f'node_procs_running{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 正在运行进程数", "refId": "A"},
            {"expr": f'node_procs_blocked{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 阻塞/等待I/O进程数", "refId": "B"}
        ], 12, 28, 12, 8, unit="short")
    ]

    return {
        "annotations": {"list": []},
        "editable": false,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": panels,
        "refresh": "30s",
        "schemaVersion": 39,
        "tags": ["nexora", "server", "linux", "metrics"],
        "templating": {
            "list": [
                make_query_variable("site", "站点", 'label_values({__name__=~"node_.*|up",job="linux_servers"}, site_name)'),
                make_query_variable("device", "服务器", 'label_values({__name__=~"node_.*|up",job="linux_servers",site_name=~"$site"}, hostname)'),
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "07 Linux 服务器监控 (Linux Server Metrics)",
        "uid": "nexora-linux-metrics",
        "version": DASHBOARD_VERSION
    }

def build_windows_dashboard():
    srv_sel = 'job="windows_servers",site_name=~"$site",hostname=~"$device"'
    panels = [
        stat_panel(1, "受纳管 Windows 主机数", f'count(count by (hostname) (up{{{srv_sel}}})) or vector(0)', 0, 0, 6, 4, unit="none", color="blue"),
        stat_panel(2, "平均 CPU 使用率", f'avg(100 - (avg by (hostname) (rate(windows_cpu_time_total{{{srv_sel},mode="idle"}}[5m])) * 100)) or vector(0)', 6, 0, 6, 4, unit="percent", thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 70},
            {"color": "red", "value": 85}
        ]),
        stat_panel(3, "平均物理内存使用率", f'avg((1 - (windows_os_physical_memory_free_bytes{{{srv_sel}}} / windows_cs_physical_memory_bytes{{{srv_sel}}})) * 100) or vector(0)', 12, 0, 6, 4, unit="percent", thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 80},
            {"color": "red", "value": 90}
        ]),
        stat_panel(4, "远程桌面活跃会话", f'sum(windows_terminal_services_active_sessions{{{srv_sel}}}) or vector(0)', 18, 0, 6, 4, unit="none", color="purple"),

        timeseries_panel(5, "CPU 占用率走势 (%)", [
            {"expr": f'100 - (avg by (hostname) (rate(windows_cpu_time_total{{{srv_sel},mode="idle"}}[5m])) * 100)', "legendFormat": "{{site_name}} / {{hostname}} CPU 利用率 (%)", "refId": "A"}
        ], 0, 4, 12, 8, unit="percent"),
        timeseries_panel(6, "物理内存分配与提交走势", [
            {"expr": f'windows_cs_physical_memory_bytes{{{srv_sel}}} - windows_os_physical_memory_free_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 物理内存已用", "refId": "A"},
            {"expr": f'windows_os_physical_memory_free_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 可用物理内存", "refId": "B"},
            {"expr": f'windows_memory_committed_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 已提交虚拟内存", "refId": "C"},
            {"expr": f'windows_cs_physical_memory_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 物理内存总量 (Total)", "refId": "D"}
        ], 12, 4, 12, 8, unit="bytes"),

        table_panel(
            7, "逻辑磁盘剩余空间最低 Top 10",
            f'bottomk(10, min by (hostname, volume) ((windows_logical_disk_free_bytes{{{srv_sel}}} / windows_logical_disk_size_bytes{{{srv_sel}}}) * 100))',
            0, 12, 12, 8, unit="percent",
            transformations=clean_organize_transformation("剩余空间 (%)", {"volume": "盘符"})
        ),
        timeseries_panel(8, "系统进程数与线程数", [
            {"expr": f'windows_system_processes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 进程数", "refId": "A"},
            {"expr": f'windows_system_threads{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 线程数", "refId": "B"}
        ], 12, 12, 12, 8, unit="short"),

        timeseries_panel(9, "网卡收发流量走势 (bps)", [
            {"expr": f'sum by (hostname, nic) (rate(windows_net_bytes_received_total{{{srv_sel}}}[5m]) * 8)', "legendFormat": "{{site_name}} / {{hostname}} - {{nic}} 接收", "refId": "A"},
            {"expr": f'sum by (hostname, nic) (rate(windows_net_bytes_sent_total{{{srv_sel}}}[5m]) * 8)', "legendFormat": "{{site_name}} / {{hostname}} - {{nic}} 发送", "refId": "B"}
        ], 0, 20, 12, 8, unit="bps"),
        table_panel(
            10, "系统关键服务运行状态",
            f'windows_service_state{{{srv_sel},state="running"}} == 1',
            12, 20, 12, 8, unit="none",
            transformations=clean_organize_transformation("服务状态", {"name": "服务名"})
        ),
        table_panel(
            11, "非运行关键服务",
            f'windows_service_state{{{srv_sel},state!="running"}} == 1',
            0, 28, 24, 8, unit="none",
            transformations=clean_organize_transformation("服务状态", {"name": "服务名", "state": "服务状态"})
        )
    ]

    return {
        "annotations": {"list": []},
        "editable": false,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": panels,
        "refresh": "30s",
        "schemaVersion": 39,
        "tags": ["nexora", "server", "windows", "metrics"],
        "templating": {
            "list": [
                make_query_variable("site", "站点", 'label_values({__name__=~"windows_.*|up",job="windows_servers"}, site_name)'),
                make_query_variable("device", "服务器", 'label_values({__name__=~"windows_.*|up",job="windows_servers",site_name=~"$site"}, hostname)'),
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "08 Windows 服务器监控 (Windows Server Metrics)",
        "uid": "nexora-windows-metrics",
        "version": DASHBOARD_VERSION
    }

def main():
    DASHBOARDS_DIR.mkdir(parents=True, exist_ok=True)
    dashboards = [
        ("nexora-network-overview.json", build_overview_dashboard()),
        ("nexora-network-device.json", build_device_dashboard()),
        ("nexora-network-wireless.json", build_wireless_dashboard()),
        ("nexora-network-interface.json", build_interface_dashboard()),
        ("nexora-interface-detail.json", build_interface_detail_dashboard()),
        ("nexora-monitoring-health.json", build_health_dashboard()),
        ("nexora-network-outbound.json", build_outbound_dashboard()),
        ("nexora-linux-metrics.json", build_linux_dashboard()),
        ("nexora-windows-metrics.json", build_windows_dashboard()),
    ]
    for fname, data in dashboards:
        path = DASHBOARDS_DIR / fname
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Generated {path}")

if __name__ == "__main__":
    main()

