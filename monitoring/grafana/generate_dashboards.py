import json
import os
from pathlib import Path

false = False
true = True
null = None

ROOT_DIR = Path(__file__).resolve().parents[2]
DASHBOARDS_DIR = ROOT_DIR / "monitoring" / "grafana" / "dashboards"
DS_UID = "victoriametrics"

DEV_JOIN = "* on(instance) group_left(sysName) (last_over_time(sysName{sysName=~\"$device\"}[1d]) * 0 + 1)"
IF_JOIN = "* on(instance, ifIndex) group_left(ifName) (ifName * 0 + 1)"

def stat_panel(pid, title, expr, x, y, w=4, h=4, unit="", color="green", thresholds=None):
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
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": steps}
            },
            "overrides": []
        },
        "options": {
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto"
        },
        "targets": [{"expr": expr, "refId": "A"}]
    }

def timeseries_panel(pid, title, targets, x, y, w=12, h=8, unit=""):
    return {
        "id": pid,
        "title": title,
        "type": "timeseries",
        "datasource": {"type": "prometheus", "uid": DS_UID},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "color": {"mode": "palette-classic"},
                "custom": {"drawStyle": "line", "lineInterpolation": "smooth", "fillOpacity": 10}
            },
            "overrides": []
        },
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"}
        },
        "targets": targets
    }

def clean_organize_transformation(value_col_name="数值", extra_renames=None):
    renames = {
        "sysName": "设备名称",
        "hostname": "设备名称",
        "instance": "管理 IP",
        "ifName": "接口全称",
        "ifDescr": "接口描述",
        "vendor": "厂商",
        "role": "角色",
        "Value": value_col_name,
    }
    if extra_renames:
        renames.update(extra_renames)
    return [
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
                    "site_name": True,
                    "platform": True,
                },
                "indexByName": {
                    "sysName": 0,
                    "hostname": 1,
                    "instance": 2,
                    "ifName": 3,
                    "ifDescr": 4,
                    "vendor": 5,
                    "role": 6,
                    "Value": 7,
                },
                "renameByName": renames,
            }
        }
    ]

def table_panel(pid, title, expr, x, y, w=12, h=8, unit="", transformations=None, value_col_name="数值"):
    overrides = []
    if unit:
        overrides.append({
            "matcher": {"id": "byName", "options": value_col_name},
            "properties": [{"id": "unit", "value": unit}]
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
                "color": {"mode": "thresholds"}
            },
            "overrides": overrides
        },
        "options": {
            "cellHeight": "sm",
            "showHeader": True,
            "footer": {"show": False}
        },
        "targets": [{"expr": expr, "format": "table", "instant": True, "refId": "A"}]
    }
    if transformations:
        panel["transformations"] = transformations
    return panel

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
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "#E0B400", "value": 70},
                        {"color": "red", "value": 85}
                    ]
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

def make_network_variables(multi_device=True, include_all_device=True):
    return [
        make_query_variable("site", "站点", 'label_values({__name__=~"sysName|ifOperStatus|up"}, site_name)'),
        make_query_variable("vendor", "厂商", 'label_values({__name__=~"sysName|ifOperStatus|up",site_name=~"$site"}, vendor)'),
        make_query_variable("role", "角色", 'label_values({__name__=~"sysName|ifOperStatus|up",site_name=~"$site",vendor=~"$vendor"}, role)'),
        make_query_variable("device", "设备", 'label_values({__name__=~"sysName",site_name=~"$site",vendor=~"$vendor",role=~"$role"}, sysName)', multi=multi_device, include_all=include_all_device),
    ]

# 1. Overview Dashboard
def build_overview_dashboard():
    sel = 'site_name=~"$site",vendor=~"$vendor",role=~"$role"'
    cpu_expr = (
        "max by (instance, vendor) ("
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
        f") {DEV_JOIN}"
    )
    mem_expr = (
        "max by (instance, vendor) ("
        f"hh3cEntityExtMemUsage{{{sel}}} or "
        f"hwEntityMemUsage{{{sel}}} or "
        f"ruijieMemoryPoolCurrentUtilization{{{sel}}} or "
        f"jnxOperatingBuffer{{{sel}}} or "
        f"fnSysMemUsage{{{sel}}} or "
        f"zteMemRate{{{sel}}} or "
        f"mpMemoryUtilization{{{sel}}} or "
        f"dptechMemUsage{{{sel}}} or "
        f"hillstoneMemoryUtilization{{{sel}}} or "
        f"sangforMemUsage{{{sel}}} or "
        f"dcnMemUsage{{{sel}}}"
        f") {DEV_JOIN}"
    )
    ap_online_expr = (
        f"sum((hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or "
        f"ruijieApcTotalApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}) {DEV_JOIN}) or vector(0)"
    )
    client_online_expr = (
        f"sum((hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or "
        f"cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}}) {DEV_JOIN}) or vector(0)"
    )

    panels = [
        stat_panel(1, "纳管设备数", 'count(count by (instance) (ifOperStatus))', 0, 0, 4, 4, color="#3274D9"),
        stat_panel(2, "监控站点数", 'count(count by (site_name) (ifOperStatus{site_name!=""}))', 4, 0, 4, 4, color="#A352CC"),
        stat_panel(3, "全网在线数", 'count(count by (instance) (ifOperStatus == 1))', 8, 0, 4, 4, color="#56A64B"),
        stat_panel(4, "无线在线客户端数", client_online_expr, 12, 0, 4, 4, color="#37872D"),
        stat_panel(5, "采集接口总数", f"count(ifOperStatus{{{sel}}} {DEV_JOIN})", 16, 0, 4, 4, color="#3274D9"),
        stat_panel(6, "异常/Down接口数", f"(count(ifOperStatus{{{sel}}} != 1 {DEV_JOIN})) or vector(0)", 20, 0, 4, 4, thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 1},
            {"color": "#F2495C", "value": 5}
        ]),
        timeseries_panel(7, "网络接口总流量", [
            {"expr": f"sum(rate(ifHCInOctets{{{sel}}}[5m]) {DEV_JOIN}) * 8", "legendFormat": "入流量", "refId": "A"},
            {"expr": f"sum(rate(ifHCOutOctets{{{sel}}}[5m]) {DEV_JOIN}) * 8", "legendFormat": "出流量", "refId": "B"}
        ], 0, 4, 12, 8, unit="bps"),
        timeseries_panel(8, "全网无线终端与 AP 规模趋势", [
            {"expr": f"sum((hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}}) {DEV_JOIN})", "legendFormat": "无线客户端总数", "refId": "A"},
            {"expr": f"sum((hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or ruijieApcTotalApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}) {DEV_JOIN})", "legendFormat": "在线 AP 总数", "refId": "B"}
        ], 12, 4, 12, 8, unit="short"),
        timeseries_panel(9, "设备 CPU 使用率", [
            {"expr": cpu_expr, "legendFormat": "{{sysName}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 0, 12, 12, 8, unit="percent"),
        timeseries_panel(10, "设备内存使用率", [
            {"expr": mem_expr, "legendFormat": "{{sysName}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 12, 12, 8, unit="percent"),
        timeseries_panel(11, "设备温度", [
            {"expr": f"max by (instance, vendor) (hh3cEntityExtTemperature{{{sel}}} or hwEntityTemperature{{{sel}}} or ruijieDeviceTemperature{{{sel}}} or jnxOperatingTemp{{{sel}}} or entSensorValue{{{sel}}} or zteTemperature{{{sel}}} or mpTemperature{{{sel}}} or dptechTemperature{{{sel}}} or dcnTemperature{{{sel}}}) {DEV_JOIN}", "legendFormat": "{{sysName}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 0, 20, 12, 8, unit="celsius"),
        table_panel(
            12, "设备接口流量排行 Top 10",
            f"topk(10, sum by (sysName, instance, vendor) ((rate(ifHCInOctets{{{sel}}}[5m]) + rate(ifHCOutOctets{{{sel}}}[5m])) * 8 {DEV_JOIN}))",
            12, 20, 12, 8, unit="bps",
            transformations=clean_organize_transformation("总流量")
        ),
        timeseries_panel(13, "接口错误与丢弃统计", [
            {"expr": f"sum(rate(ifInErrors{{{sel}}}[5m]) {DEV_JOIN}) + sum(rate(ifOutErrors{{{sel}}}[5m]) {DEV_JOIN})", "legendFormat": "错误包/秒", "refId": "A"},
            {"expr": f"sum(rate(ifInDiscards{{{sel}}}[5m]) {DEV_JOIN}) + sum(rate(ifOutDiscards{{{sel}}}[5m]) {DEV_JOIN})", "legendFormat": "丢弃包/秒", "refId": "B"}
        ], 0, 28, 24, 8, unit="pps")
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
        "tags": ["nexora", "network", "overview"],
        "templating": {
            "list": make_network_variables()
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "01 网络总览 (Network Overview)",
        "uid": "nexora-network-overview",
        "version": 6
    }

# 2. Network Device Detail Dashboard
def build_device_dashboard():
    panels = [
        stat_panel(1, "系统运行时间 (Uptime)", f"sysUpTime / 100 {DEV_JOIN}", 0, 0, 6, 4, unit="s", color="#3274D9"),
        stat_panel(2, "当前 CPU 使用率", (
            "max("
            "cpmCPUTotal1minRev or hh3cEntityExtCpuUsage or "
            "hwEntityCpuUsage or ruijieCpuCostRate or "
            "jnxOperatingCPU or fnSysCpuUsage or "
            "zteCpuRate or mpCpuUtilization5Min or "
            "dptechCpuUsage or hillstoneCPUUtilization or "
            "sangforCpuUsage or dcnCpuUsage"
            f") {DEV_JOIN}"
        ), 6, 0, 6, 4, unit="percent", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 70}, {"color": "red", "value": 85}]),
        stat_panel(3, "当前内存使用率", (
            "max("
            "hh3cEntityExtMemUsage or hwEntityMemUsage or "
            "ruijieMemoryPoolCurrentUtilization or jnxOperatingBuffer or "
            "fnSysMemUsage or zteMemRate or "
            "mpMemoryUtilization or dptechMemUsage or "
            "hillstoneMemoryUtilization or sangforMemUsage or "
            "dcnMemUsage"
            f") {DEV_JOIN}"
        ), 12, 0, 6, 4, unit="percent", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 75}, {"color": "red", "value": 90}]),
        stat_panel(4, "设备整机温度", (
            "max("
            "hh3cEntityExtTemperature or hwEntityTemperature or "
            "ruijieDeviceTemperature or jnxOperatingTemp or "
            "entSensorValue or zteTemperature or "
            "mpTemperature or dptechTemperature or "
            "dcnTemperature"
            f") {DEV_JOIN}"
        ), 18, 0, 6, 4, unit="celsius", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 55}, {"color": "red", "value": 70}]),
        timeseries_panel(5, "CPU 负载走势 (多核/主备控)", [
            {"expr": f"(cpmCPUTotal1minRev or hh3cEntityExtCpuUsage or hwEntityCpuUsage or ruijieCpuCostRate or jnxOperatingCPU or fnSysCpuUsage or zteCpuRate or mpCpuUtilization5Min or dptechCpuUsage or hillstoneCPUUtilization or sangforCpuUsage or dcnCpuUsage) {DEV_JOIN}", "legendFormat": "{{sysName}} ({{instance}})", "refId": "A"}
        ], 0, 4, 12, 8, unit="percent"),
        timeseries_panel(6, "内存使用率与池走势", [
            {"expr": f"(hh3cEntityExtMemUsage or hwEntityMemUsage or ruijieMemoryPoolCurrentUtilization or jnxOperatingBuffer or fnSysMemUsage or zteMemRate or mpMemoryUtilization or dptechMemUsage or hillstoneMemoryUtilization or sangforMemUsage or dcnMemUsage) {DEV_JOIN}", "legendFormat": "{{sysName}} ({{instance}})", "refId": "A"}
        ], 12, 4, 12, 8, unit="percent"),
        timeseries_panel(7, "板卡与环境温度传感器监控", [
            {"expr": f"(hh3cEntityExtTemperature or hwEntityTemperature or ruijieDeviceTemperature or jnxOperatingTemp or entSensorValue or zteTemperature or mpTemperature or dptechTemperature or dcnTemperature) {DEV_JOIN}", "legendFormat": "{{sysName}} ({{instance}})", "refId": "A"}
        ], 0, 12, 12, 8, unit="celsius"),
        table_panel(
            8, "设备端口实时状态清单", f"ifOperStatus {DEV_JOIN} {IF_JOIN}", 12, 12, 12, 8,
            transformations=clean_organize_transformation("运行状态 (1=Up, 2=Down)")
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
        "tags": ["nexora", "network", "device"],
        "templating": {
            "list": make_network_variables(multi_device=False, include_all_device=False)
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "02 网络设备详情 (Network Device Detail)",
        "uid": "nexora-network-device",
        "version": 3
    }

# 3. Wireless Monitoring Dashboard
def build_wireless_dashboard():
    sel = 'site_name=~"$site",vendor=~"$vendor"'
    panels = [
        stat_panel(1, "全网纳管 AP 总数", f"sum((hwWlanApTotalNum{{{sel}}} or hh3cDot11TotalAPNum{{{sel}}} or ruijieApcTotalApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}) {DEV_JOIN}) or vector(0)", 0, 0, 6, 4, color="#3274D9"),
        stat_panel(2, "当前在线 AP 总数", f"sum((hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}) {DEV_JOIN}) or vector(0)", 6, 0, 6, 4, color="#56A64B"),
        stat_panel(3, "当前离线 AP 数量", f"(sum((hwWlanApTotalNum{{{sel}}} or hh3cDot11TotalAPNum{{{sel}}} or ruijieApcTotalApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}) {DEV_JOIN}) - sum((hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}) {DEV_JOIN})) or vector(0)", 12, 0, 6, 4, thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 1}, {"color": "red", "value": 5}]),
        stat_panel(4, "全网在线关联无线终端", f"sum((hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}}) {DEV_JOIN}) or vector(0)", 18, 0, 6, 4, color="#A352CC"),
        timeseries_panel(5, "无线 AP 在线规模趋势", [
            {"expr": f"sum((hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}) {DEV_JOIN})", "legendFormat": "在线 AP 数", "refId": "A"}
        ], 0, 4, 12, 8, unit="short"),
        timeseries_panel(6, "关联终端客户数走势", [
            {"expr": f"sum((hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}}) {DEV_JOIN})", "legendFormat": "关联终端数", "refId": "A"}
        ], 12, 4, 12, 8, unit="short"),
        table_panel(
            7, "AP 负载与终端数排行 Top 10",
            f"topk(10, (hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}}) {DEV_JOIN})",
            0, 12, 12, 8, unit="short",
            transformations=clean_organize_transformation("终端数量")
        ),
        table_panel(
            8, "无线信道利用率排行 Top 10",
            f"topk(10, (hh3cDot11ChannelUsage{{{sel}}} or ruijieRadioChannelUsage{{{sel}}}) {DEV_JOIN})",
            12, 12, 12, 8, unit="percent",
            transformations=clean_organize_transformation("信道利用率")
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
        "version": 3
    }

# 4. Interface Traffic & Health Dashboard
def build_interface_dashboard():
    sel = 'site_name=~"$site",vendor=~"$vendor",role=~"$role"'
    panels = [
        stat_panel(1, "全网聚合入流量 (Inbound)", f"sum(rate(ifHCInOctets{{{sel}}}[5m]) {DEV_JOIN}) * 8", 0, 0, 6, 4, unit="bps", color="#3274D9"),
        stat_panel(2, "全网聚合出流量 (Outbound)", f"sum(rate(ifHCOutOctets{{{sel}}}[5m]) {DEV_JOIN}) * 8", 6, 0, 6, 4, unit="bps", color="#56A64B"),
        stat_panel(3, "实时错误包总速率", f"sum(rate(ifInErrors{{{sel}}}[5m]) {DEV_JOIN} + rate(ifOutErrors{{{sel}}}[5m]) {DEV_JOIN})", 12, 0, 6, 4, unit="pps", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 10}, {"color": "red", "value": 100}]),
        stat_panel(4, "实时丢弃包总速率", f"sum(rate(ifInDiscards{{{sel}}}[5m]) {DEV_JOIN} + rate(ifOutDiscards{{{sel}}}[5m]) {DEV_JOIN})", 18, 0, 6, 4, unit="pps", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 10}, {"color": "red", "value": 100}]),
        timeseries_panel(5, "高负荷端口入流量 Top 10", [
            {"expr": f"topk(10, rate(ifHCInOctets{{{sel}}}[5m]) * 8 {DEV_JOIN} {IF_JOIN})", "legendFormat": "{{sysName}} {{instance}} {{ifName}}", "refId": "A"}
        ], 0, 4, 12, 8, unit="bps"),
        timeseries_panel(6, "高负荷端口出流量 Top 10", [
            {"expr": f"topk(10, rate(ifHCOutOctets{{{sel}}}[5m]) * 8 {DEV_JOIN} {IF_JOIN})", "legendFormat": "{{sysName}} {{instance}} {{ifName}}", "refId": "A"}
        ], 12, 4, 12, 8, unit="bps"),
        table_panel(
            7, "端口带宽利用率 Top 20",
            f"topk(20, ((rate(ifHCInOctets{{{sel}}}[5m]) * 8) / (ifHighSpeed * 1000000) * 100) {IF_JOIN} {DEV_JOIN})",
            0, 12, 12, 8, unit="percent",
            transformations=clean_organize_transformation("带宽利用率"),
            value_col_name="带宽利用率"
        ),
        table_panel(
            8, "端口错误与丢弃排行 Top 20",
            f"topk(20, (rate(ifInErrors{{{sel}}}[5m]) + rate(ifOutErrors{{{sel}}}[5m]) + rate(ifInDiscards{{{sel}}}[5m])) {IF_JOIN} {DEV_JOIN})",
            12, 12, 12, 8, unit="pps",
            transformations=clean_organize_transformation("错误/丢弃率 (pps)"),
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
        "tags": ["nexora", "network", "interface"],
        "templating": {
            "list": make_network_variables()
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "04 接口流量与健康 (Interface Traffic & Health)",
        "uid": "nexora-network-interface",
        "version": 3
    }

# 5. Monitoring Engine Health Dashboard
def build_health_dashboard():
    panels = [
        stat_panel(1, "探针在线目标 (Scrape Up)", "sum(up)", 0, 0, 6, 4, color="#56A64B"),
        stat_panel(2, "探测失败目标 (Scrape Down)", "sum(up == 0) or vector(0)", 6, 0, 6, 4, thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}]),
        stat_panel(3, "平均 SNMP 采集耗时", "avg(scrape_duration_seconds)", 12, 0, 6, 4, unit="s", color="#3274D9"),
        stat_panel(4, "最大 SNMP 采集耗时", "max(scrape_duration_seconds)", 18, 0, 6, 4, unit="s", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 5}, {"color": "red", "value": 15}]),
        timeseries_panel(5, "各设备 SNMP 采集耗时分布 (秒)", [
            {"expr": "scrape_duration_seconds", "legendFormat": "{{instance}} ({{job}})", "refId": "A"}
        ], 0, 4, 12, 8, unit="s"),
        timeseries_panel(6, "抓取指标量统计 (Samples Scraped)", [
            {"expr": "scrape_samples_scraped", "legendFormat": "{{instance}}", "refId": "A"}
        ], 12, 4, 12, 8, unit="short"),
        table_panel(
            7, "采集失败设备清单 (Target Scrape Failure)", "up == 0", 0, 12, 12, 8,
            transformations=clean_organize_transformation("探测状态")
        ),
        table_panel(
            8, "采集最慢目标排行 Top 10", "topk(10, scrape_duration_seconds)", 12, 12, 12, 8, unit="s",
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
        "version": 3
    }

# 6. Internet Outbound & WAN Dashboard
def build_outbound_dashboard():
    sel = 'site_name=~"$site",vendor=~"$vendor"'
    comb_sel = f'{sel}'

    panels = [
        stat_panel(1, "出口总入向实时带宽 (Inbound)", f"sum(rate(ifHCInOctets{{{comb_sel}}}[5m]) {DEV_JOIN}) * 8", 0, 0, 6, 4, unit="bps", color="#3274D9"),
        stat_panel(2, "出口总出向实时带宽 (Outbound)", f"sum(rate(ifHCOutOctets{{{comb_sel}}}[5m]) {DEV_JOIN}) * 8", 6, 0, 6, 4, unit="bps", color="#56A64B"),
        stat_panel(3, "出口最高端口带宽利用率", f"max(((rate(ifHCInOctets{{{comb_sel}}}[5m]) * 8) / (ifHighSpeed * 1000000) * 100) {DEV_JOIN}) or vector(0)", 12, 0, 6, 4, unit="percent", thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 70},
            {"color": "red", "value": 85}
        ]),
        stat_panel(4, "出口链路错误与丢弃总速率", f"sum((rate(ifInErrors{{{comb_sel}}}[5m]) + rate(ifOutErrors{{{comb_sel}}}[5m]) + rate(ifInDiscards{{{comb_sel}}}[5m])) {DEV_JOIN}) or vector(0)", 18, 0, 6, 4, unit="pps", thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 10},
            {"color": "red", "value": 100}
        ]),
        timeseries_panel(5, "出口边界各设备入向流量趋势 (Inbound bps)", [
            {"expr": f"sum by (sysName, instance) (rate(ifHCInOctets{{{comb_sel}}}[5m]) * 8 {DEV_JOIN})", "legendFormat": "{{sysName}} ({{instance}}) 入向", "refId": "A"}
        ], 0, 4, 12, 8, unit="bps"),
        timeseries_panel(6, "出口边界各设备出向流量趋势 (Outbound bps)", [
            {"expr": f"sum by (sysName, instance) (rate(ifHCOutOctets{{{comb_sel}}}[5m]) * 8 {DEV_JOIN})", "legendFormat": "{{sysName}} ({{instance}}) 出向", "refId": "A"}
        ], 12, 4, 12, 8, unit="bps"),
        timeseries_panel(7, "出口端口带宽利用率走势 (In/Out Top 10)", [
            {"expr": f"topk(10, ((rate(ifHCInOctets{{{comb_sel}}}[5m]) * 8) / (ifHighSpeed * 1000000) * 100) {IF_JOIN} {DEV_JOIN})", "legendFormat": "{{sysName}} {{instance}} {{ifName}} 入向利用率", "refId": "A"},
            {"expr": f"topk(10, ((rate(ifHCOutOctets{{{comb_sel}}}[5m]) * 8) / (ifHighSpeed * 1000000) * 100) {IF_JOIN} {DEV_JOIN})", "legendFormat": "{{sysName}} {{instance}} {{ifName}} 出向利用率", "refId": "B"}
        ], 0, 12, 12, 8, unit="percent"),
        timeseries_panel(8, "出口链路接口丢包与错包时序 (PPS)", [
            {"expr": f"sum by (sysName, instance) ((rate(ifInErrors{{{comb_sel}}}[5m]) + rate(ifOutErrors{{{comb_sel}}}[5m])) {DEV_JOIN})", "legendFormat": "{{sysName}} {{instance}} 错包/秒", "refId": "A"},
            {"expr": f"sum by (sysName, instance) (rate(ifInDiscards{{{comb_sel}}}[5m]) * 8 {DEV_JOIN})", "legendFormat": "{{sysName}} {{instance}} 丢弃/秒", "refId": "B"}
        ], 12, 12, 12, 8, unit="pps"),
        table_panel(
            9, "出口端口带宽利用率排行 Top 10",
            f"topk(10, ((rate(ifHCInOctets{{{comb_sel}}}[5m]) * 8) / (ifHighSpeed * 1000000) * 100) {IF_JOIN} {DEV_JOIN})",
            0, 20, 12, 8, unit="percent",
            transformations=clean_organize_transformation("带宽利用率"),
            value_col_name="带宽利用率"
        ),
        table_panel(
            10, "出口端口错误与丢弃排行 Top 10",
            f"topk(10, (rate(ifInErrors{{{comb_sel}}}[5m]) + rate(ifOutErrors{{{comb_sel}}}[5m]) + rate(ifInDiscards{{{comb_sel}}}[5m])) {IF_JOIN} {DEV_JOIN})",
            12, 20, 12, 8, unit="pps",
            transformations=clean_organize_transformation("错误/丢弃率 (pps)"),
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
            "list": make_network_variables()
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "06 互联网出口与 WAN (Internet Outbound & WAN Traffic)",
        "uid": "nexora-network-outbound",
        "version": 2
    }

def build_linux_dashboard():
    srv_sel = 'instance=~"$device"'
    panels = [
        stat_panel(1, "受纳管 Linux 主机数", 'count(count by (instance) (node_uname_info or node_load1 or up{job="linux_servers"})) or vector(0)', 0, 0, 4, 4, unit="none", color="blue"),
        stat_panel(2, "系统平均运行时间 (Uptime)", f'avg(time() - node_boot_time_seconds{{{srv_sel}}}) or vector(0)', 4, 0, 4, 4, unit="s", color="#3274D9"),
        stat_panel(3, "平均 CPU 使用率", f'avg(100 - (rate(node_cpu_seconds_total{{{srv_sel},mode="idle"}}[5m]) * 100)) or vector(0)', 8, 0, 4, 4, unit="percent", thresholds=[
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
        stat_panel(6, "文件句柄利用率", f'avg(node_filefd_allocated{{{srv_sel}}} / node_filefd_maximum{{{srv_sel}}} * 100) or vector(0)', 20, 0, 4, 4, unit="percent", thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 70},
            {"color": "red", "value": 85}
        ]),

        timeseries_panel(7, "CPU 利用率与平均负载趋势", [
            {"expr": f'100 - (rate(node_cpu_seconds_total{{{srv_sel},mode="idle"}}[5m]) * 100)', "legendFormat": "{{instance}} CPU利用率 (%)", "refId": "A"},
            {"expr": f'node_load1{{{srv_sel}}}', "legendFormat": "{{instance}} 1分钟负载 (Load1)", "refId": "B"},
            {"expr": f'node_load5{{{srv_sel}}}', "legendFormat": "{{instance}} 5分钟负载 (Load5)", "refId": "C"},
            {"expr": f'node_load15{{{srv_sel}}}', "legendFormat": "{{instance}} 15分钟负载 (Load15)", "refId": "D"}
        ], 0, 4, 12, 8, unit="percent"),
        timeseries_panel(8, "物理内存与 Swap 空间消耗走势", [
            {"expr": f'(1 - (node_memory_MemAvailable_bytes{{{srv_sel}}} / node_memory_MemTotal_bytes{{{srv_sel}}})) * 100', "legendFormat": "{{instance}} 内存利用率 (%)", "refId": "A"},
            {"expr": f'node_memory_MemTotal_bytes{{{srv_sel}}} - node_memory_MemAvailable_bytes{{{srv_sel}}}', "legendFormat": "{{instance}} 内存已用量", "refId": "B"},
            {"expr": f'(1 - (node_memory_SwapFree_bytes{{{srv_sel}}} / node_memory_SwapTotal_bytes{{{srv_sel}}})) * 100', "legendFormat": "{{instance}} Swap 利用率 (%)", "refId": "C"}
        ], 12, 4, 12, 8, unit="percent"),

        table_panel(
            9, "主机磁盘空间利用率 Top 10",
            f'topk(10, max by (instance, mountpoint) ((1 - (node_filesystem_avail_bytes{{{srv_sel},fstype!~"tmpfs|iso9660|squashfs"}} / node_filesystem_size_bytes{{{srv_sel}}})) * 100))',
            0, 12, 12, 8, unit="percent",
            transformations=clean_organize_transformation("磁盘使用率", {"mountpoint": "挂载点"})
        ),
        timeseries_panel(10, "磁盘读写吞吐速率 (Bytes/s)", [
            {"expr": f'sum by (instance, device) (rate(node_disk_read_bytes_total{{{srv_sel},device!~"loop.*"}}[5m]))', "legendFormat": "{{instance}} - {{device}} 读吞吐", "refId": "A"},
            {"expr": f'sum by (instance, device) (rate(node_disk_written_bytes_total{{{srv_sel},device!~"loop.*"}}[5m]))', "legendFormat": "{{instance}} - {{device}} 写吞吐", "refId": "B"}
        ], 12, 12, 12, 8, unit="Bps"),

        timeseries_panel(11, "服务器网卡流量走势 (bps)", [
            {"expr": f'sum by (instance, device) (rate(node_network_receive_bytes_total{{{srv_sel},device!~"lo|docker.*|veth.*|br-.*"}}[5m]) * 8)', "legendFormat": "{{instance}} - {{device}} 接收 (bps)", "refId": "A"},
            {"expr": f'sum by (instance, device) (rate(node_network_transmit_bytes_total{{{srv_sel},device!~"lo|docker.*|veth.*|br-.*"}}[5m]) * 8)', "legendFormat": "{{instance}} - {{device}} 发送 (bps)", "refId": "B"}
        ], 0, 20, 12, 8, unit="bps"),
        timeseries_panel(12, "网卡丢包与错包速率 (PPS)", [
            {"expr": f'sum by (instance, device) (rate(node_network_receive_drop_total{{{srv_sel},device!~"lo|docker.*|veth.*|br-.*"}}[5m]) + rate(node_network_transmit_drop_total{{{srv_sel},device!~"lo|docker.*|veth.*|br-.*"}}[5m]))', "legendFormat": "{{instance}} - {{device}} 丢包/秒", "refId": "A"},
            {"expr": f'sum by (instance, device) (rate(node_network_receive_errs_total{{{srv_sel},device!~"lo|docker.*|veth.*|br-.*"}}[5m]) + rate(node_network_transmit_errs_total{{{srv_sel},device!~"lo|docker.*|veth.*|br-.*"}}[5m]))', "legendFormat": "{{instance}} - {{device}} 错包/秒", "refId": "B"}
        ], 12, 20, 12, 8, unit="pps"),

        table_panel(
            13, "主机 TCP 活跃连接数 Top 10",
            f'topk(10, sum by (instance) (node_netstat_Tcp_CurrEstab{{{srv_sel}}}))',
            0, 28, 12, 8, unit="none",
            transformations=clean_organize_transformation("活跃连接数")
        ),
        timeseries_panel(14, "系统进程调度与阻塞情况", [
            {"expr": f'node_procs_running{{{srv_sel}}}', "legendFormat": "{{instance}} 正在运行进程数", "refId": "A"},
            {"expr": f'node_procs_blocked{{{srv_sel}}}', "legendFormat": "{{instance}} 阻塞/等待I/O进程数", "refId": "B"}
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
                make_query_variable("site", "站点", 'label_values({job="linux_servers"} or {__name__=~"node_.*"}, site_name)'),
                make_query_variable("device", "服务器", 'label_values({job="linux_servers",site_name=~"$site"} or {__name__=~"node_.*",site_name=~"$site"}, instance)'),
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "07 Linux 服务器监控 (Linux Server Metrics)",
        "uid": "nexora-linux-metrics",
        "version": 3
    }

def build_windows_dashboard():
    srv_sel = 'instance=~"$device"'
    panels = [
        stat_panel(1, "受纳管 Windows 主机数", 'count(count by (instance) (windows_cpu_time_total or windows_os_info or up{job="windows_servers"})) or vector(0)', 0, 0, 6, 4, unit="none", color="blue"),
        stat_panel(2, "平均 CPU 使用率", f'avg(100 - (rate(windows_cpu_time_total{{{srv_sel},mode="idle"}}[5m]) * 100)) or vector(0)', 6, 0, 6, 4, unit="percent", thresholds=[
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
            {"expr": f'100 - (rate(windows_cpu_time_total{{{srv_sel},mode="idle"}}[5m]) * 100)', "legendFormat": "{{instance}} CPU 利用率", "refId": "A"}
        ], 0, 4, 12, 8, unit="percent"),
        timeseries_panel(6, "可用物理内存与已提交字节走势", [
            {"expr": f'windows_os_physical_memory_free_bytes{{{srv_sel}}}', "legendFormat": "{{instance}} 可用物理内存", "refId": "A"},
            {"expr": f'windows_os_committed_bytes{{{srv_sel}}}', "legendFormat": "{{instance}} 已提交字节", "refId": "B"}
        ], 12, 4, 12, 8, unit="bytes"),

        table_panel(
            7, "逻辑磁盘剩余空间百分比 Top 10",
            f'topk(10, min by (instance, volume) ((windows_logical_disk_free_bytes{{{srv_sel}}} / windows_logical_disk_size_bytes{{{srv_sel}}}) * 100))',
            0, 12, 12, 8, unit="percent",
            transformations=clean_organize_transformation("剩余空间 (%)", {"volume": "盘符"})
        ),
        timeseries_panel(8, "系统进程数与线程数", [
            {"expr": f'windows_system_processes{{{srv_sel}}}', "legendFormat": "{{instance}} 进程数", "refId": "A"},
            {"expr": f'windows_system_threads{{{srv_sel}}}', "legendFormat": "{{instance}} 线程数", "refId": "B"}
        ], 12, 12, 12, 8, unit="short"),

        timeseries_panel(9, "网卡收发流量走势 (bps)", [
            {"expr": f'sum by (instance, nic) (rate(windows_net_bytes_received_total{{{srv_sel}}}[5m]) * 8)', "legendFormat": "{{instance}} - {{nic}} 接收", "refId": "A"},
            {"expr": f'sum by (instance, nic) (rate(windows_net_bytes_sent_total{{{srv_sel}}}[5m]) * 8)', "legendFormat": "{{instance}} - {{nic}} 发送", "refId": "B"}
        ], 0, 20, 12, 8, unit="bps"),
        table_panel(
            10, "系统关键服务运行状态",
            f'windows_service_status{{{srv_sel},state="running"}}',
            12, 20, 12, 8, unit="none",
            transformations=clean_organize_transformation("服务状态", {"name": "服务名"})
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
                make_query_variable("site", "站点", 'label_values({job="windows_servers"} or {__name__=~"windows_.*"}, site_name)'),
                make_query_variable("device", "服务器", 'label_values({job="windows_servers",site_name=~"$site"} or {__name__=~"windows_.*",site_name=~"$site"}, instance)'),
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "08 Windows 服务器监控 (Windows Server Metrics)",
        "uid": "nexora-windows-metrics",
        "version": 3
    }

def main():
    DASHBOARDS_DIR.mkdir(parents=True, exist_ok=True)
    dashboards = [
        ("nexora-network-overview.json", "network-overview.json", build_overview_dashboard()),
        ("nexora-network-device.json", "network-device.json", build_device_dashboard()),
        ("nexora-network-wireless.json", "network-wireless.json", build_wireless_dashboard()),
        ("nexora-network-interface.json", "network-interface.json", build_interface_dashboard()),
        ("nexora-monitoring-health.json", "monitoring-health.json", build_health_dashboard()),
        ("nexora-network-outbound.json", "network-outbound.json", build_outbound_dashboard()),
        ("nexora-linux-metrics.json", "linux-metrics.json", build_linux_dashboard()),
        ("nexora-windows-metrics.json", "windows-metrics.json", build_windows_dashboard()),
    ]
    for fn1, fn2, data in dashboards:
        for fname in [fn1, fn2]:
            path = DASHBOARDS_DIR / fname
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"Generated {path}")

if __name__ == "__main__":
    main()

