import json
import os
from pathlib import Path

false = False
true = True
null = None

ROOT_DIR = Path(__file__).resolve().parents[2]
DASHBOARDS_DIR = ROOT_DIR / "monitoring" / "grafana" / "dashboards"
DS_UID = "victoriametrics"

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
        "hostname": "设备名称",
        "instance": "管理 IP",
        "ifName": "端口编号",
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
                    "ifIndex": True,
                },
                "indexByName": {
                    "hostname": 0,
                    "instance": 1,
                    "ifName": 2,
                    "vendor": 3,
                    "role": 4,
                    "Value": 5,
                },
                "renameByName": renames,
            }
        }
    ]

def table_panel(pid, title, expr, x, y, w=12, h=8, unit="", transformations=None):
    panel = {
        "id": pid,
        "title": title,
        "type": "table",
        "datasource": {"type": "prometheus", "uid": DS_UID},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "color": {"mode": "thresholds"}
            },
            "overrides": []
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
        "targets": [{"expr": expr, "legendFormat": "{{hostname}} ({{instance}})", "refId": "A"}]
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

# 1. Overview Dashboard
def build_overview_dashboard():
    sel = 'site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    cpu_expr = (
        "max by (hostname, instance, vendor) ("
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
        "max by (hostname, instance, vendor) ("
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
        ")"
    )
    ap_online_expr = (
        f"sum(hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or "
        f"ruijieApcTotalApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}) or vector(0)"
    )
    client_online_expr = (
        f"sum(hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or "
        f"cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}}) or vector(0)"
    )

    panels = [
        stat_panel(1, "纳管设备数", 'count(count by (instance) (ifOperStatus or up{job="network_snmp"} or {job=~".*snmp.*"}))', 0, 0, 4, 4, color="#3274D9"),
        stat_panel(2, "监控站点数", 'count(count by (site_name) (ifOperStatus{site_name!=""} or up{site_name!=""} or {site_name!=""}))', 4, 0, 4, 4, color="#A352CC"),
        stat_panel(3, "全网在线 AP 数", ap_online_expr, 8, 0, 4, 4, color="#56A64B"),
        stat_panel(4, "无线在线客户端数", client_online_expr, 12, 0, 4, 4, color="#37872D"),
        stat_panel(5, "采集接口总数", f"count(ifOperStatus{{{sel}}})", 16, 0, 4, 4, color="#3274D9"),
        stat_panel(6, "异常/Down接口数", f"count(ifOperStatus{{{sel}}} != 1) or vector(0)", 20, 0, 4, 4, thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 1},
            {"color": "#F2495C", "value": 5}
        ]),
        timeseries_panel(7, "网络接口总流量", [
            {"expr": f"sum(rate(ifHCInOctets{{{sel}}}[5m])) * 8", "legendFormat": "入流量", "refId": "A"},
            {"expr": f"sum(rate(ifHCOutOctets{{{sel}}}[5m])) * 8", "legendFormat": "出流量", "refId": "B"}
        ], 0, 4, 12, 8, unit="bps"),
        timeseries_panel(8, "全网无线终端与 AP 规模趋势", [
            {"expr": f"sum(hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}})", "legendFormat": "无线客户端总数", "refId": "A"},
            {"expr": f"sum(hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or ruijieApcTotalApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}})", "legendFormat": "在线 AP 总数", "refId": "B"}
        ], 12, 4, 12, 8, unit="short"),
        timeseries_panel(9, "设备 CPU 使用率", [
            {"expr": cpu_expr, "legendFormat": "{{hostname}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 0, 12, 12, 8, unit="percent"),
        timeseries_panel(10, "设备内存使用率", [
            {"expr": mem_expr, "legendFormat": "{{hostname}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 12, 12, 8, unit="percent"),
        timeseries_panel(11, "设备温度", [
            {"expr": f"max by (hostname, instance, vendor) (hh3cEntityExtTemperature{{{sel}}} or hwEntityTemperature{{{sel}}} or ruijieDeviceTemperature{{{sel}}} or jnxOperatingTemp{{{sel}}} or entSensorValue{{{sel}}} or zteTemperature{{{sel}}} or mpTemperature{{{sel}}} or dptechTemperature{{{sel}}} or dcnTemperature{{{sel}}})", "legendFormat": "{{hostname}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 0, 20, 12, 8, unit="celsius"),
        table_panel(
            12, "设备接口流量排行 Top 10",
            f"topk(10, sum by (hostname, instance, vendor) (rate(ifHCInOctets{{{sel}}}[5m]) * 8 + rate(ifHCOutOctets{{{sel}}}[5m]) * 8))",
            12, 20, 12, 8, unit="bps",
            transformations=clean_organize_transformation("总流量")
        ),
        timeseries_panel(13, "接口错误与丢弃统计", [
            {"expr": f"sum(rate(ifInErrors{{{sel}}}[5m])) + sum(rate(ifOutErrors{{{sel}}}[5m]))", "legendFormat": "错误包/秒", "refId": "A"},
            {"expr": f"sum(rate(ifInDiscards{{{sel}}}[5m])) + sum(rate(ifOutDiscards{{{sel}}}[5m]))", "legendFormat": "丢弃包/秒", "refId": "B"}
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
            "list": [
                make_query_variable("site", "站点", "label_values(site_name)"),
                make_query_variable("vendor", "厂商", 'label_values({site_name=~"$site"}, vendor)'),
                make_query_variable("role", "角色", 'label_values({site_name=~"$site",vendor=~"$vendor"}, role)'),
                make_query_variable("device", "设备", 'label_values({site_name=~"$site",vendor=~"$vendor"}, hostname)'),
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "01 网络总览 (Network Overview)",
        "uid": "nexora-network-overview",
        "version": 5
    }

# 2. Network Device Detail Dashboard
def build_device_dashboard():
    dev_sel = 'hostname=~"$device"'
    panels = [
        stat_panel(1, "系统运行时间 (Uptime)", f"sysUpTime{{{dev_sel}}} / 100", 0, 0, 6, 4, unit="s", color="#3274D9"),
        stat_panel(2, "当前 CPU 使用率", (
            f"max(cpmCPUTotal1minRev{{{dev_sel}}} or hh3cEntityExtCpuUsage{{{dev_sel}}} or "
            f"hwEntityCpuUsage{{{dev_sel}}} or ruijieCpuCostRate{{{dev_sel}}} or "
            f"jnxOperatingCPU{{{dev_sel}}} or fnSysCpuUsage{{{dev_sel}}} or "
            f"zteCpuRate{{{dev_sel}}} or mpCpuUtilization5Min{{{dev_sel}}} or "
            f"dptechCpuUsage{{{dev_sel}}} or hillstoneCPUUtilization{{{dev_sel}}} or "
            f"sangforCpuUsage{{{dev_sel}}} or dcnCpuUsage{{{dev_sel}}})"
        ), 6, 0, 6, 4, unit="percent", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 70}, {"color": "red", "value": 85}]),
        stat_panel(3, "当前内存使用率", (
            f"max(hh3cEntityExtMemUsage{{{dev_sel}}} or hwEntityMemUsage{{{dev_sel}}} or "
            f"ruijieMemoryPoolCurrentUtilization{{{dev_sel}}} or jnxOperatingBuffer{{{dev_sel}}} or "
            f"fnSysMemUsage{{{dev_sel}}} or zteMemRate{{{dev_sel}}} or "
            f"mpMemoryUtilization{{{dev_sel}}} or dptechMemUsage{{{dev_sel}}} or "
            f"hillstoneMemoryUtilization{{{dev_sel}}} or sangforMemUsage{{{dev_sel}}} or "
            f"dcnMemUsage{{{dev_sel}}})"
        ), 12, 0, 6, 4, unit="percent", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 75}, {"color": "red", "value": 90}]),
        stat_panel(4, "设备整机温度", (
            f"max(hh3cEntityExtTemperature{{{dev_sel}}} or hwEntityTemperature{{{dev_sel}}} or "
            f"ruijieDeviceTemperature{{{dev_sel}}} or jnxOperatingTemp{{{dev_sel}}} or "
            f"entSensorValue{{{dev_sel}}} or zteTemperature{{{dev_sel}}} or "
            f"mpTemperature{{{dev_sel}}} or dptechTemperature{{{dev_sel}}} or "
            f"dcnTemperature{{{dev_sel}}})"
        ), 18, 0, 6, 4, unit="celsius", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 55}, {"color": "red", "value": 70}]),
        timeseries_panel(5, "CPU 负载走势 (多核/主备控)", [
            {"expr": f"cpmCPUTotal1minRev{{{dev_sel}}} or hh3cEntityExtCpuUsage{{{dev_sel}}} or hwEntityCpuUsage{{{dev_sel}}} or ruijieCpuCostRate{{{dev_sel}}} or jnxOperatingCPU{{{dev_sel}}} or fnSysCpuUsage{{{dev_sel}}} or zteCpuRate{{{dev_sel}}} or mpCpuUtilization5Min{{{dev_sel}}} or dptechCpuUsage{{{dev_sel}}} or hillstoneCPUUtilization{{{dev_sel}}} or sangforCpuUsage{{{dev_sel}}} or dcnCpuUsage{{{dev_sel}}}", "legendFormat": "Slot/Core {{entPhysicalName}} ({{instance}})", "refId": "A"}
        ], 0, 4, 12, 8, unit="percent"),
        timeseries_panel(6, "内存使用率与池走势", [
            {"expr": f"hh3cEntityExtMemUsage{{{dev_sel}}} or hwEntityMemUsage{{{dev_sel}}} or ruijieMemoryPoolCurrentUtilization{{{dev_sel}}} or jnxOperatingBuffer{{{dev_sel}}} or fnSysMemUsage{{{dev_sel}}} or zteMemRate{{{dev_sel}}} or mpMemoryUtilization{{{dev_sel}}} or dptechMemUsage{{{dev_sel}}} or hillstoneMemoryUtilization{{{dev_sel}}} or sangforMemUsage{{{dev_sel}}} or dcnMemUsage{{{dev_sel}}}", "legendFormat": "Pool/Slot {{entPhysicalName}} ({{instance}})", "refId": "A"}
        ], 12, 4, 12, 8, unit="percent"),
        timeseries_panel(7, "板卡与环境温度传感器监控", [
            {"expr": f"hh3cEntityExtTemperature{{{dev_sel}}} or hwEntityTemperature{{{dev_sel}}} or ruijieDeviceTemperature{{{dev_sel}}} or jnxOperatingTemp{{{dev_sel}}} or entSensorValue{{{dev_sel}}} or zteTemperature{{{dev_sel}}} or mpTemperature{{{dev_sel}}} or dptechTemperature{{{dev_sel}}} or dcnTemperature{{{dev_sel}}}", "legendFormat": "Sensor {{entPhysicalName}} ({{instance}})", "refId": "A"}
        ], 0, 12, 12, 8, unit="celsius"),
        table_panel(
            8, "设备端口实时状态清单", f"ifOperStatus{{{dev_sel}}}", 12, 12, 12, 8,
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
            "list": [
                make_query_variable("site", "站点", "label_values(site_name)"),
                make_query_variable("vendor", "厂商", 'label_values({site_name=~"$site"}, vendor)'),
                make_query_variable("device", "设备", 'label_values({site_name=~"$site",vendor=~"$vendor"}, hostname)', multi=False, include_all=False),
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "02 网络设备详情 (Network Device Detail)",
        "uid": "nexora-network-device",
        "version": 2
    }

# 3. Wireless Monitoring Dashboard
def build_wireless_dashboard():
    sel = 'site_name=~"$site",vendor=~"$vendor",hostname=~"$device"'
    panels = [
        stat_panel(1, "全网纳管 AP 总数", f"sum(hwWlanApTotalNum{{{sel}}} or hh3cDot11TotalAPNum{{{sel}}} or ruijieApcTotalApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}) or vector(0)", 0, 0, 6, 4, color="#3274D9"),
        stat_panel(2, "当前在线 AP 总数", f"sum(hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}) or vector(0)", 6, 0, 6, 4, color="#56A64B"),
        stat_panel(3, "当前离线 AP 数量", f"(sum(hwWlanApTotalNum{{{sel}}} or hh3cDot11TotalAPNum{{{sel}}} or ruijieApcTotalApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}) - sum(hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}})) or vector(0)", 12, 0, 6, 4, thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 1}, {"color": "red", "value": 5}]),
        stat_panel(4, "全网在线关联无线终端", f"sum(hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}}) or vector(0)", 18, 0, 6, 4, color="#A352CC"),
        timeseries_panel(5, "各无线控制器在线终端时序趋势", [
            {"expr": f"hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}}", "legendFormat": "{{hostname}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 0, 4, 12, 8, unit="short"),
        timeseries_panel(6, "各控制器纳管在线 AP 波动趋势", [
            {"expr": f"hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}", "legendFormat": "{{hostname}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 12, 4, 12, 8, unit="short"),
        bar_gauge_panel(7, "各无线控制器客户端负载 Top 榜", f"hwWlanCurAssocUserNum{{{sel}}} or hh3cDot11CurrAssocUserNum{{{sel}}} or ruijieApcTotalStaNum{{{sel}}} or cLSysTotalNumOfClients{{{sel}}} or wlsxSysExtStationsNum{{{sel}}} or ruckusZDTotalNumSta{{{sel}}}", 0, 12, 12, 8, unit="short"),
        table_panel(
            8, "全网无线控制器 AC 状态清单",
            f"hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}",
            12, 12, 12, 8,
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
            "list": [
                make_query_variable("site", "站点", "label_values(site_name)"),
                make_query_variable("vendor", "厂商", 'label_values({site_name=~"$site"}, vendor)'),
                make_query_variable("device", "设备", 'label_values({site_name=~"$site",vendor=~"$vendor"}, hostname)'),
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "03 无线专网监控 (Wireless AP & Clients)",
        "uid": "nexora-network-wireless",
        "version": 2
    }

# 4. Interface Traffic & Health Dashboard
def build_interface_dashboard():
    sel = 'site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    panels = [
        stat_panel(1, "全网聚合入流量 (Inbound)", f"sum(rate(ifHCInOctets{{{sel}}}[5m])) * 8", 0, 0, 6, 4, unit="bps", color="#3274D9"),
        stat_panel(2, "全网聚合出流量 (Outbound)", f"sum(rate(ifHCOutOctets{{{sel}}}[5m])) * 8", 6, 0, 6, 4, unit="bps", color="#56A64B"),
        stat_panel(3, "实时错误包总速率", f"sum(rate(ifInErrors{{{sel}}}[5m]) + rate(ifOutErrors{{{sel}}}[5m]))", 12, 0, 6, 4, unit="pps", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 10}, {"color": "red", "value": 100}]),
        stat_panel(4, "实时丢弃包总速率", f"sum(rate(ifInDiscards{{{sel}}}[5m]) + rate(ifOutDiscards{{{sel}}}[5m]))", 18, 0, 6, 4, unit="pps", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 10}, {"color": "red", "value": 100}]),
        timeseries_panel(5, "高负荷端口入流量 Top 10", [
            {"expr": f"topk(10, rate(ifHCInOctets{{{sel}}}[5m]) * 8)", "legendFormat": "{{hostname}} ({{instance}}) - {{ifName}}", "refId": "A"}
        ], 0, 4, 12, 8, unit="bps"),
        timeseries_panel(6, "高负荷端口出流量 Top 10", [
            {"expr": f"topk(10, rate(ifHCOutOctets{{{sel}}}[5m]) * 8)", "legendFormat": "{{hostname}} ({{instance}}) - {{ifName}}", "refId": "A"}
        ], 12, 4, 12, 8, unit="bps"),
        table_panel(
            7, "端口带宽利用率 Top 20",
            f"topk(20, max by (hostname, instance, ifName) ((rate(ifHCInOctets{{{sel}}}[5m]) * 8) / (ifHighSpeed * 1000000) * 100))",
            0, 12, 12, 8, unit="percent",
            transformations=clean_organize_transformation("带宽利用率")
        ),
        table_panel(
            8, "端口错误与丢弃排行 Top 20",
            f"topk(20, sum by (hostname, instance, ifName) (rate(ifInErrors{{{sel}}}[5m]) + rate(ifOutErrors{{{sel}}}[5m]) + rate(ifInDiscards{{{sel}}}[5m])))",
            12, 12, 12, 8, unit="pps",
            transformations=clean_organize_transformation("错误/丢弃率 (pps)")
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
            "list": [
                make_query_variable("site", "站点", "label_values(site_name)"),
                make_query_variable("vendor", "厂商", 'label_values({site_name=~"$site"}, vendor)'),
                make_query_variable("role", "角色", 'label_values({site_name=~"$site",vendor=~"$vendor"}, role)'),
                make_query_variable("device", "设备", 'label_values({site_name=~"$site",vendor=~"$vendor"}, hostname)'),
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "04 接口流量与健康 (Interface Traffic & Health)",
        "uid": "nexora-network-interface",
        "version": 2
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
        "version": 2
    }

# 6. Internet Outbound & WAN Dashboard
def build_outbound_dashboard():
    sel = 'site_name=~"$site",vendor=~"$vendor",hostname=~"$device"'
    role_filter = 'role=~"gateway|firewall|wan|border|.*"'
    comb_sel = f'{sel},{role_filter}'

    panels = [
        stat_panel(1, "出口总入向实时带宽 (Inbound)", f"sum(rate(ifHCInOctets{{{comb_sel}}}[5m])) * 8 or sum(rate(ifHCInOctets{{{sel}}}[5m])) * 8", 0, 0, 6, 4, unit="bps", color="#3274D9"),
        stat_panel(2, "出口总出向实时带宽 (Outbound)", f"sum(rate(ifHCOutOctets{{{comb_sel}}}[5m])) * 8 or sum(rate(ifHCOutOctets{{{sel}}}[5m])) * 8", 6, 0, 6, 4, unit="bps", color="#56A64B"),
        stat_panel(3, "出口最高端口带宽利用率", f"max((rate(ifHCInOctets{{{comb_sel}}}[5m]) * 8) / (ifHighSpeed * 1000000) * 100) or vector(0)", 12, 0, 6, 4, unit="percent", thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 70},
            {"color": "red", "value": 85}
        ]),
        stat_panel(4, "出口链路错误与丢弃总速率", f"sum(rate(ifInErrors{{{comb_sel}}}[5m]) + rate(ifOutErrors{{{comb_sel}}}[5m]) + rate(ifInDiscards{{{comb_sel}}}[5m])) or vector(0)", 18, 0, 6, 4, unit="pps", thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 10},
            {"color": "red", "value": 100}
        ]),
        timeseries_panel(5, "出口边界各设备入向流量趋势 (Inbound bps)", [
            {"expr": f"sum by (hostname, instance) (rate(ifHCInOctets{{{comb_sel}}}[5m]) * 8)", "legendFormat": "{{hostname}} ({{instance}}) 入向", "refId": "A"}
        ], 0, 4, 12, 8, unit="bps"),
        timeseries_panel(6, "出口边界各设备出向流量趋势 (Outbound bps)", [
            {"expr": f"sum by (hostname, instance) (rate(ifHCOutOctets{{{comb_sel}}}[5m]) * 8)", "legendFormat": "{{hostname}} ({{instance}}) 出向", "refId": "A"}
        ], 12, 4, 12, 8, unit="bps"),
        timeseries_panel(7, "出口端口带宽利用率走势 (In/Out Top 10)", [
            {"expr": f"topk(10, (rate(ifHCInOctets{{{comb_sel}}}[5m]) * 8) / (ifHighSpeed * 1000000) * 100)", "legendFormat": "{{hostname}} - {{ifName}} 入向利用率", "refId": "A"},
            {"expr": f"topk(10, (rate(ifHCOutOctets{{{comb_sel}}}[5m]) * 8) / (ifHighSpeed * 1000000) * 100)", "legendFormat": "{{hostname}} - {{ifName}} 出向利用率", "refId": "B"}
        ], 0, 12, 12, 8, unit="percent"),
        timeseries_panel(8, "出口链路接口丢包与错包时序 (PPS)", [
            {"expr": f"sum by (hostname, instance) (rate(ifInErrors{{{comb_sel}}}[5m]) + rate(ifOutErrors{{{comb_sel}}}[5m]))", "legendFormat": "{{hostname}} ({{instance}}) 错包/秒", "refId": "A"},
            {"expr": f"sum by (hostname, instance) (rate(ifInDiscards{{{comb_sel}}}[5m]) + rate(ifOutDiscards{{{comb_sel}}}[5m]))", "legendFormat": "{{hostname}} ({{instance}}) 丢弃/秒", "refId": "B"}
        ], 12, 12, 12, 8, unit="pps"),
        table_panel(
            9, "出口端口带宽利用率排行 Top 10",
            f"topk(10, max by (hostname, instance, ifName) ((rate(ifHCInOctets{{{comb_sel}}}[5m]) * 8) / (ifHighSpeed * 1000000) * 100))",
            0, 20, 12, 8, unit="percent",
            transformations=clean_organize_transformation("带宽利用率")
        ),
        table_panel(
            10, "出口端口错误与丢弃排行 Top 10",
            f"topk(10, sum by (hostname, instance, ifName) (rate(ifInErrors{{{comb_sel}}}[5m]) + rate(ifOutErrors{{{comb_sel}}}[5m]) + rate(ifInDiscards{{{comb_sel}}}[5m])))",
            12, 20, 12, 8, unit="pps",
            transformations=clean_organize_transformation("错误/丢弃率 (pps)")
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
            "list": [
                make_query_variable("site", "站点", "label_values(site_name)"),
                make_query_variable("vendor", "厂商", 'label_values({site_name=~"$site"}, vendor)'),
                make_query_variable("device", "出口设备", 'label_values({site_name=~"$site",vendor=~"$vendor"}, hostname)'),
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "06 互联网出口与 WAN (Internet Outbound & WAN Traffic)",
        "uid": "nexora-network-outbound",
        "version": 1
    }

def build_linux_dashboard():
    srv_sel = 'site_name=~"$site",hostname=~"$device"'
    panels = [
        stat_panel(1, "受纳管 Linux 主机数", 'count(count by (hostname) (node_load1 or node_uname_info)) or vector(0)', 0, 0, 6, 4, unit="none", color="blue"),
        stat_panel(2, "平均 CPU 使用率", f'avg(100 - (rate(node_cpu_seconds_total{{{srv_sel},mode="idle"}}[5m]) * 100) or host_cpu_util{{{srv_sel}}}) or vector(0)', 6, 0, 6, 4, unit="percent", thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 70},
            {"color": "red", "value": 85}
        ]),
        stat_panel(3, "平均物理内存利用率", f'avg((1 - (node_memory_MemAvailable_bytes{{{srv_sel}}} / node_memory_MemTotal_bytes{{{srv_sel}}})) * 100 or host_mem_util{{{srv_sel}}}) or vector(0)', 12, 0, 6, 4, unit="percent", thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 80},
            {"color": "red", "value": 90}
        ]),
        stat_panel(4, "TCP 活跃连接总数", f'sum(node_netstat_Tcp_CurrEstab{{{srv_sel}}} or host_tcp_estab{{{srv_sel}}}) or vector(0)', 18, 0, 6, 4, unit="none", color="purple"),

        timeseries_panel(5, "CPU 利用率与平均负载趋势", [
            {"expr": f'100 - (rate(node_cpu_seconds_total{{{srv_sel},mode="idle"}}[5m]) * 100) or host_cpu_util{{{srv_sel}}}', "legendFormat": "{{hostname}} CPU利用率 (%)", "refId": "A"},
            {"expr": f'node_load1{{{srv_sel}}} or host_cpu_load1{{{srv_sel}}}', "legendFormat": "{{hostname}} 1分钟负载 (Load1)", "refId": "B"},
            {"expr": f'node_load5{{{srv_sel}}} or host_cpu_load5{{{srv_sel}}}', "legendFormat": "{{hostname}} 5分钟负载 (Load5)", "refId": "C"}
        ], 0, 4, 12, 8, unit="percent"),
        timeseries_panel(6, "物理内存与 Swap 空间消耗走势", [
            {"expr": f'(1 - (node_memory_MemAvailable_bytes{{{srv_sel}}} / node_memory_MemTotal_bytes{{{srv_sel}}})) * 100 or host_mem_util{{{srv_sel}}}', "legendFormat": "{{hostname}} 内存利用率 (%)", "refId": "A"},
            {"expr": f'(1 - (node_memory_SwapFree_bytes{{{srv_sel}}} / node_memory_SwapTotal_bytes{{{srv_sel}}})) * 100 or host_swap_util{{{srv_sel}}}', "legendFormat": "{{hostname}} Swap 利用率 (%)", "refId": "B"}
        ], 12, 4, 12, 8, unit="percent"),

        table_panel(
            7, "主机磁盘空间利用率 Top 10",
            f'topk(10, max by (hostname, instance, mountpoint) ((1 - (node_filesystem_avail_bytes{{{srv_sel},fstype!~"tmpfs|iso9660|squashfs"}} / node_filesystem_size_bytes{{{srv_sel}}})) * 100 or host_disk_util{{{srv_sel}}}))',
            0, 12, 12, 8, unit="percent",
            transformations=clean_organize_transformation("磁盘使用率", {"mountpoint": "挂载点"})
        ),
        timeseries_panel(8, "磁盘读写 IOPS 走势", [
            {"expr": f'sum by (hostname, device) (rate(node_disk_reads_completed_total{{{srv_sel},device!~"loop.*"}}[5m]))', "legendFormat": "{{hostname}} - {{device}} 读 IOPS", "refId": "A"},
            {"expr": f'sum by (hostname, device) (rate(node_disk_writes_completed_total{{{srv_sel},device!~"loop.*"}}[5m]))', "legendFormat": "{{hostname}} - {{device}} 写 IOPS", "refId": "B"}
        ], 12, 12, 12, 8, unit="iops"),

        timeseries_panel(9, "服务器网卡流量走势 (bps)", [
            {"expr": f'sum by (hostname, device) (rate(node_network_receive_bytes_total{{{srv_sel},device!~"lo|docker.*|veth.*|br-.*"}}[5m]) * 8 or rate(ifHCInOctets{{{srv_sel}}}[5m]) * 8)', "legendFormat": "{{hostname}} - {{device}} 接收", "refId": "A"},
            {"expr": f'sum by (hostname, device) (rate(node_network_transmit_bytes_total{{{srv_sel},device!~"lo|docker.*|veth.*|br-.*"}}[5m]) * 8 or rate(ifHCOutOctets{{{srv_sel}}}[5m]) * 8)', "legendFormat": "{{hostname}} - {{device}} 发送", "refId": "B"}
        ], 0, 20, 12, 8, unit="bps"),
        table_panel(
            10, "主机 TCP 活跃连接数 Top 10",
            f'topk(10, sum by (hostname, instance) (node_netstat_Tcp_CurrEstab{{{srv_sel}}} or host_tcp_conns{{{srv_sel}}}))',
            12, 20, 12, 8, unit="none",
            transformations=clean_organize_transformation("活跃连接数")
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
        "tags": ["nexora", "server", "linux", "metrics"],
        "templating": {
            "list": [
                make_query_variable("site", "站点", 'label_values(node_load1 or host_cpu_util or hrProcessorLoad or up, site_name)'),
                make_query_variable("device", "服务器", 'label_values({site_name=~"$site"}, hostname)'),
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "07 Linux 服务器监控 (Linux Server Metrics)",
        "uid": "nexora-linux-metrics",
        "version": 1
    }

def build_windows_dashboard():
    srv_sel = 'site_name=~"$site",hostname=~"$device"'
    panels = [
        stat_panel(1, "受纳管 Windows 主机数", 'count(count by (hostname) (windows_cpu_time_total or windows_os_info)) or vector(0)', 0, 0, 6, 4, unit="none", color="blue"),
        stat_panel(2, "平均 CPU 使用率", f'avg(100 - (rate(windows_cpu_time_total{{{srv_sel},mode="idle"}}[5m]) * 100) or hrProcessorLoad{{{srv_sel}}}) or vector(0)', 6, 0, 6, 4, unit="percent", thresholds=[
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

        timeseries_panel(5, "Windows CPU 使用率走势 (%)", [
            {"expr": f'100 - (rate(windows_cpu_time_total{{{srv_sel},mode="idle"}}[5m]) * 100) or hrProcessorLoad{{{srv_sel}}}', "legendFormat": "{{hostname}} ({{core}}) CPU", "refId": "A"}
        ], 0, 4, 12, 8, unit="percent"),
        timeseries_panel(6, "物理内存使用率与可用内存走势", [
            {"expr": f'(1 - (windows_os_physical_memory_free_bytes{{{srv_sel}}} / windows_cs_physical_memory_bytes{{{srv_sel}}})) * 100', "legendFormat": "{{hostname}} 内存使用率 (%)", "refId": "A"},
            {"expr": f'windows_os_physical_memory_free_bytes{{{srv_sel}}}', "legendFormat": "{{hostname}} 可用内存 (Bytes)", "refId": "B"}
        ], 12, 4, 12, 8, unit="percent"),

        table_panel(
            7, "逻辑磁盘驱动器空间利用率 Top 10",
            f'topk(10, max by (hostname, instance, volume) ((1 - (windows_logical_disk_free_bytes{{{srv_sel}}} / windows_logical_disk_size_bytes{{{srv_sel}}})) * 100))',
            0, 12, 12, 8, unit="percent",
            transformations=clean_organize_transformation("卷使用率", {"volume": "驱动器盘符"})
        ),
        timeseries_panel(8, "逻辑磁盘读写延迟走势 (秒)", [
            {"expr": f'rate(windows_logical_disk_read_seconds_total{{{srv_sel}}}[5m]) / (rate(windows_logical_disk_reads_total{{{srv_sel}}}[5m]) > 0)', "legendFormat": "{{hostname}} - {{volume}} 读延迟", "refId": "A"},
            {"expr": f'rate(windows_logical_disk_write_seconds_total{{{srv_sel}}}[5m]) / (rate(windows_logical_disk_writes_total{{{srv_sel}}}[5m]) > 0)', "legendFormat": "{{hostname}} - {{volume}} 写延迟", "refId": "B"}
        ], 12, 12, 12, 8, unit="s"),

        timeseries_panel(9, "网络适配器吞吐走势 (bps)", [
            {"expr": f'sum by (hostname, nic) (rate(windows_net_bytes_received_total{{{srv_sel}}}[5m]) * 8)', "legendFormat": "{{hostname}} - {{nic}} 接收", "refId": "A"},
            {"expr": f'sum by (hostname, nic) (rate(windows_net_bytes_sent_total{{{srv_sel}}}[5m]) * 8)', "legendFormat": "{{hostname}} - {{nic}} 发送", "refId": "B"}
        ], 0, 20, 12, 8, unit="bps"),
        table_panel(
            10, "主机运行时间清单 (Uptime)",
            f'windows_system_system_up_time{{{srv_sel}}}',
            12, 20, 12, 8, unit="s",
            transformations=clean_organize_transformation("已运行时间 (秒)")
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
                make_query_variable("site", "站点", 'label_values(windows_cpu_time_total or windows_os_info or hrProcessorLoad or up, site_name)'),
                make_query_variable("device", "服务器", 'label_values({site_name=~"$site"}, hostname)'),
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "08 Windows 主机监控 (Windows Host Metrics)",
        "uid": "nexora-windows-metrics",
        "version": 1
    }

def main():
    os.makedirs(DASHBOARDS_DIR, exist_ok=True)
    dashboards = {
        "nexora-network-overview.json": build_overview_dashboard(),
        "network-device.json": build_device_dashboard(),
        "network-wireless.json": build_wireless_dashboard(),
        "network-interface.json": build_interface_dashboard(),
        "monitoring-health.json": build_health_dashboard(),
        "network-outbound.json": build_outbound_dashboard(),
        "linux-metrics.json": build_linux_dashboard(),
        "windows-metrics.json": build_windows_dashboard(),
    }
    for filename, data in dashboards.items():
        path = os.path.join(DASHBOARDS_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Generated {filename} -> {path}")

if __name__ == "__main__":
    main()
