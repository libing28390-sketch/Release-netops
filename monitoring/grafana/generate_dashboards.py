import json
import os

false = False
true = True
null = None

DASHBOARDS_DIR = r"D:\netops\netsops-main\monitoring\grafana\dashboards"
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

def table_panel(pid, title, expr, x, y, w=12, h=8, unit=""):
    return {
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

# 1. Overview Dashboard
def build_overview_dashboard():
    cpu_expr = (
        "max by (hostname, instance, vendor) ("
        "cpmCPUTotal1minRev{site_id=~\"$site\",instance=~\"$device\"} or "
        "hh3cEntityExtCpuUsage{site_id=~\"$site\",instance=~\"$device\"} or "
        "hwEntityCpuUsage{site_id=~\"$site\",instance=~\"$device\"} or "
        "ruijieCpuCostRate{site_id=~\"$site\",instance=~\"$device\"} or "
        "jnxOperatingCPU{site_id=~\"$site\",instance=~\"$device\"} or "
        "fnSysCpuUsage{site_id=~\"$site\",instance=~\"$device\"} or "
        "zteCpuRate{site_id=~\"$site\",instance=~\"$device\"} or "
        "mpCpuUtilization5Min{site_id=~\"$site\",instance=~\"$device\"} or "
        "dptechCpuUsage{site_id=~\"$site\",instance=~\"$device\"} or "
        "hillstoneCPUUtilization{site_id=~\"$site\",instance=~\"$device\"} or "
        "sangforCpuUsage{site_id=~\"$site\",instance=~\"$device\"} or "
        "dcnCpuUsage{site_id=~\"$site\",instance=~\"$device\"}"
        ")"
    )
    mem_expr = (
        "max by (hostname, instance, vendor) ("
        "hh3cEntityExtMemUsage{site_id=~\"$site\",instance=~\"$device\"} or "
        "hwEntityMemUsage{site_id=~\"$site\",instance=~\"$device\"} or "
        "ruijieMemoryPoolCurrentUtilization{site_id=~\"$site\",instance=~\"$device\"} or "
        "jnxOperatingBuffer{site_id=~\"$site\",instance=~\"$device\"} or "
        "fnSysMemUsage{site_id=~\"$site\",instance=~\"$device\"} or "
        "zteMemRate{site_id=~\"$site\",instance=~\"$device\"} or "
        "mpMemoryUtilization{site_id=~\"$site\",instance=~\"$device\"} or "
        "dptechMemUsage{site_id=~\"$site\",instance=~\"$device\"} or "
        "hillstoneMemoryUtilization{site_id=~\"$site\",instance=~\"$device\"} or "
        "sangforMemUsage{site_id=~\"$site\",instance=~\"$device\"} or "
        "dcnMemUsage{site_id=~\"$site\",instance=~\"$device\"}"
        ")"
    )
    ap_online_expr = (
        "sum(hwWlanCurOnlineApNum or hh3cDot11CurrOnlineAPNum or ruijieApcOnlineApNum or "
        "ruijieApcTotalApNum or cLApTotalUpAPs or wlsxSysExtAccessPointsNum or ruckusZDTotalNumAP) or vector(0)"
    )
    client_online_expr = (
        "sum(hwWlanCurAssocUserNum or hh3cDot11CurrAssocUserNum or ruijieApcTotalStaNum or "
        "cLSysTotalNumOfClients or wlsxSysExtStationsNum or ruckusZDTotalNumSta) or vector(0)"
    )

    panels = [
        stat_panel(1, "纳管设备数", "count(count by (instance) (ifOperStatus{site_id=~\"$site\",instance=~\"$device\"}))", 0, 0, 4, 4, color="#3274D9"),
        stat_panel(2, "监控站点数", "count(count by (site_id) (ifOperStatus))", 4, 0, 4, 4, color="#A352CC"),
        stat_panel(3, "全网在线 AP 数", ap_online_expr, 8, 0, 4, 4, color="#56A64B"),
        stat_panel(4, "无线在线客户端数", client_online_expr, 12, 0, 4, 4, color="#37872D"),
        stat_panel(5, "采集接口总数", "count(ifOperStatus{site_id=~\"$site\",instance=~\"$device\"})", 16, 0, 4, 4, color="#3274D9"),
        stat_panel(6, "异常/Down接口数", "count(ifOperStatus{site_id=~\"$site\",instance=~\"$device\"} != 1) or vector(0)", 20, 0, 4, 4, thresholds=[
            {"color": "green", "value": None},
            {"color": "#E0B400", "value": 1},
            {"color": "#F2495C", "value": 5}
        ]),
        timeseries_panel(7, "网络接口总流量", [
            {"expr": "sum(rate(ifHCInOctets{site_id=~\"$site\",instance=~\"$device\"}[5m])) * 8", "legendFormat": "入流量", "refId": "A"},
            {"expr": "sum(rate(ifHCOutOctets{site_id=~\"$site\",instance=~\"$device\"}[5m])) * 8", "legendFormat": "出流量", "refId": "B"}
        ], 0, 4, 12, 8, unit="bps"),
        timeseries_panel(8, "全网无线终端与 AP 规模趋势", [
            {"expr": "sum(hwWlanCurAssocUserNum or hh3cDot11CurrAssocUserNum or ruijieApcTotalStaNum or cLSysTotalNumOfClients or wlsxSysExtStationsNum or ruckusZDTotalNumSta)", "legendFormat": "无线客户端总数", "refId": "A"},
            {"expr": "sum(hwWlanCurOnlineApNum or hh3cDot11CurrOnlineAPNum or ruijieApcOnlineApNum or ruijieApcTotalApNum or cLApTotalUpAPs or wlsxSysExtAccessPointsNum or ruckusZDTotalNumAP)", "legendFormat": "在线 AP 总数", "refId": "B"}
        ], 12, 4, 12, 8, unit="short"),
        timeseries_panel(9, "设备 CPU 使用率", [
            {"expr": cpu_expr, "legendFormat": "{{hostname}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 0, 12, 12, 8, unit="percent"),
        timeseries_panel(10, "设备内存使用率", [
            {"expr": mem_expr, "legendFormat": "{{hostname}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 12, 12, 12, 8, unit="percent"),
        timeseries_panel(11, "设备温度", [
            {"expr": "max by (hostname, instance, vendor) (hh3cEntityExtTemperature{site_id=~\"$site\",instance=~\"$device\"} or hwEntityTemperature{site_id=~\"$site\",instance=~\"$device\"} or ruijieDeviceTemperature{site_id=~\"$site\",instance=~\"$device\"} or jnxOperatingTemp{site_id=~\"$site\",instance=~\"$device\"} or entSensorValue{site_id=~\"$site\",instance=~\"$device\"} or zteTemperature{site_id=~\"$site\",instance=~\"$device\"} or mpTemperature{site_id=~\"$site\",instance=~\"$device\"} or dptechTemperature{site_id=~\"$site\",instance=~\"$device\"} or dcnTemperature{site_id=~\"$site\",instance=~\"$device\"})", "legendFormat": "{{hostname}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 0, 20, 12, 8, unit="celsius"),
        table_panel(12, "设备接口流量排行 Top 10", "topk(10, sum by (hostname, instance, vendor) (rate(ifHCInOctets{site_id=~\"$site\",instance=~\"$device\"}[5m]) * 8 + rate(ifHCOutOctets{site_id=~\"$site\",instance=~\"$device\"}[5m]) * 8))", 12, 20, 12, 8, unit="bps"),
        timeseries_panel(13, "接口错误与丢弃统计", [
            {"expr": "sum(rate(ifInErrors{site_id=~\"$site\",instance=~\"$device\"}[5m])) + sum(rate(ifOutErrors{site_id=~\"$site\",instance=~\"$device\"}[5m]))", "legendFormat": "错误包/秒", "refId": "A"},
            {"expr": "sum(rate(ifInDiscards{site_id=~\"$site\",instance=~\"$device\"}[5m])) + sum(rate(ifOutDiscards{site_id=~\"$site\",instance=~\"$device\"}[5m]))", "legendFormat": "丢弃包/秒", "refId": "B"}
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
                {
                    "allValue": ".*",
                    "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
                    "definition": "label_values(ifOperStatus, site_id)",
                    "includeAll": True,
                    "label": "站点",
                    "multi": True,
                    "name": "site",
                    "options": [],
                    "query": {"query": "label_values(ifOperStatus, site_id)", "refId": "StandardVariableQuery"},
                    "refresh": 1,
                    "type": "query"
                },
                {
                    "allValue": ".*",
                    "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
                    "definition": "label_values(ifOperStatus{site_id=~\"$site\"}, instance)",
                    "includeAll": True,
                    "label": "设备",
                    "multi": True,
                    "name": "device",
                    "options": [],
                    "query": {"query": "label_values(ifOperStatus{site_id=~\"$site\"}, instance)", "refId": "StandardVariableQuery"},
                    "refresh": 1,
                    "type": "query"
                }
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "01 网络总览 (Network Overview)",
        "uid": "nexora-network-overview",
        "version": 4
    }

# 2. Network Device Detail Dashboard
def build_device_dashboard():
    panels = [
        stat_panel(1, "系统运行时间 (Uptime)", "sysUpTime{instance=~\"$device\"} / 100", 0, 0, 6, 4, unit="s", color="#3274D9"),
        stat_panel(2, "当前 CPU 使用率", (
            "max(cpmCPUTotal1minRev{instance=~\"$device\"} or hh3cEntityExtCpuUsage{instance=~\"$device\"} or "
            "hwEntityCpuUsage{instance=~\"$device\"} or ruijieCpuCostRate{instance=~\"$device\"} or "
            "jnxOperatingCPU{instance=~\"$device\"} or fnSysCpuUsage{instance=~\"$device\"} or "
            "zteCpuRate{instance=~\"$device\"} or mpCpuUtilization5Min{instance=~\"$device\"} or "
            "dptechCpuUsage{instance=~\"$device\"} or hillstoneCPUUtilization{instance=~\"$device\"} or "
            "sangforCpuUsage{instance=~\"$device\"} or dcnCpuUsage{instance=~\"$device\"})"
        ), 6, 0, 6, 4, unit="percent", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 70}, {"color": "red", "value": 85}]),
        stat_panel(3, "当前内存使用率", (
            "max(hh3cEntityExtMemUsage{instance=~\"$device\"} or hwEntityMemUsage{instance=~\"$device\"} or "
            "ruijieMemoryPoolCurrentUtilization{instance=~\"$device\"} or jnxOperatingBuffer{instance=~\"$device\"} or "
            "fnSysMemUsage{instance=~\"$device\"} or zteMemRate{instance=~\"$device\"} or "
            "mpMemoryUtilization{instance=~\"$device\"} or dptechMemUsage{instance=~\"$device\"} or "
            "hillstoneMemoryUtilization{instance=~\"$device\"} or sangforMemUsage{instance=~\"$device\"} or "
            "dcnMemUsage{instance=~\"$device\"})"
        ), 12, 0, 6, 4, unit="percent", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 75}, {"color": "red", "value": 90}]),
        stat_panel(4, "设备整机温度", (
            "max(hh3cEntityExtTemperature{instance=~\"$device\"} or hwEntityTemperature{instance=~\"$device\"} or "
            "ruijieDeviceTemperature{instance=~\"$device\"} or jnxOperatingTemp{instance=~\"$device\"} or "
            "entSensorValue{instance=~\"$device\"} or zteTemperature{instance=~\"$device\"} or "
            "mpTemperature{instance=~\"$device\"} or dptechTemperature{instance=~\"$device\"} or "
            "dcnTemperature{instance=~\"$device\"})"
        ), 18, 0, 6, 4, unit="celsius", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 55}, {"color": "red", "value": 70}]),
        timeseries_panel(5, "CPU 负载走势 (多核/主备控)", [
            {"expr": "cpmCPUTotal1minRev{instance=~\"$device\"} or hh3cEntityExtCpuUsage{instance=~\"$device\"} or hwEntityCpuUsage{instance=~\"$device\"} or ruijieCpuCostRate{instance=~\"$device\"} or jnxOperatingCPU{instance=~\"$device\"} or fnSysCpuUsage{instance=~\"$device\"} or zteCpuRate{instance=~\"$device\"} or mpCpuUtilization5Min{instance=~\"$device\"} or dptechCpuUsage{instance=~\"$device\"} or hillstoneCPUUtilization{instance=~\"$device\"} or sangforCpuUsage{instance=~\"$device\"} or dcnCpuUsage{instance=~\"$device\"}", "legendFormat": "Slot/Core {{entPhysicalName}} ({{instance}})", "refId": "A"}
        ], 0, 4, 12, 8, unit="percent"),
        timeseries_panel(6, "内存使用率与池走势", [
            {"expr": "hh3cEntityExtMemUsage{instance=~\"$device\"} or hwEntityMemUsage{instance=~\"$device\"} or ruijieMemoryPoolCurrentUtilization{instance=~\"$device\"} or jnxOperatingBuffer{instance=~\"$device\"} or fnSysMemUsage{instance=~\"$device\"} or zteMemRate{instance=~\"$device\"} or mpMemoryUtilization{instance=~\"$device\"} or dptechMemUsage{instance=~\"$device\"} or hillstoneMemoryUtilization{instance=~\"$device\"} or sangforMemUsage{instance=~\"$device\"} or dcnMemUsage{instance=~\"$device\"}", "legendFormat": "Pool/Slot {{entPhysicalName}} ({{instance}})", "refId": "A"}
        ], 12, 4, 12, 8, unit="percent"),
        timeseries_panel(7, "板卡与环境温度传感器监控", [
            {"expr": "hh3cEntityExtTemperature{instance=~\"$device\"} or hwEntityTemperature{instance=~\"$device\"} or ruijieDeviceTemperature{instance=~\"$device\"} or jnxOperatingTemp{instance=~\"$device\"} or entSensorValue{instance=~\"$device\"} or zteTemperature{instance=~\"$device\"} or mpTemperature{instance=~\"$device\"} or dptechTemperature{instance=~\"$device\"} or dcnTemperature{instance=~\"$device\"}", "legendFormat": "Sensor {{entPhysicalName}} ({{instance}})", "refId": "A"}
        ], 0, 12, 12, 8, unit="celsius"),
        table_panel(8, "设备端口实时状态清单", "ifOperStatus{instance=~\"$device\"}", 12, 12, 12, 8)
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
                {
                    "allValue": ".*",
                    "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
                    "definition": "label_values(ifOperStatus, instance)",
                    "includeAll": False,
                    "label": "设备",
                    "multi": False,
                    "name": "device",
                    "options": [],
                    "query": {"query": "label_values(ifOperStatus, instance)", "refId": "StandardVariableQuery"},
                    "refresh": 1,
                    "type": "query"
                }
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "02 网络设备详情 (Network Device Detail)",
        "uid": "nexora-network-device",
        "version": 1
    }

# 3. Wireless Monitoring Dashboard
def build_wireless_dashboard():
    panels = [
        stat_panel(1, "全网纳管 AP 总数", "sum(hwWlanApTotalNum or hh3cDot11TotalAPNum or ruijieApcTotalApNum or cLApTotalUpAPs or wlsxSysExtAccessPointsNum or ruckusZDTotalNumAP) or vector(0)", 0, 0, 6, 4, color="#3274D9"),
        stat_panel(2, "当前在线 AP 总数", "sum(hwWlanCurOnlineApNum or hh3cDot11CurrOnlineAPNum or ruijieApcOnlineApNum or cLApTotalUpAPs or wlsxSysExtAccessPointsNum or ruckusZDTotalNumAP) or vector(0)", 6, 0, 6, 4, color="#56A64B"),
        stat_panel(3, "当前离线 AP 数量", "(sum(hwWlanApTotalNum or hh3cDot11TotalAPNum or ruijieApcTotalApNum or cLApTotalUpAPs or wlsxSysExtAccessPointsNum or ruckusZDTotalNumAP) - sum(hwWlanCurOnlineApNum or hh3cDot11CurrOnlineAPNum or ruijieApcOnlineApNum or cLApTotalUpAPs or wlsxSysExtAccessPointsNum or ruckusZDTotalNumAP)) or vector(0)", 12, 0, 6, 4, thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 1}, {"color": "red", "value": 5}]),
        stat_panel(4, "全网在线关联无线终端", "sum(hwWlanCurAssocUserNum or hh3cDot11CurrAssocUserNum or ruijieApcTotalStaNum or cLSysTotalNumOfClients or wlsxSysExtStationsNum or ruckusZDTotalNumSta) or vector(0)", 18, 0, 6, 4, color="#A352CC"),
        timeseries_panel(5, "各无线控制器在线终端时序趋势", [
            {"expr": "hwWlanCurAssocUserNum or hh3cDot11CurrAssocUserNum or ruijieApcTotalStaNum or cLSysTotalNumOfClients or wlsxSysExtStationsNum or ruckusZDTotalNumSta", "legendFormat": "{{hostname}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 0, 4, 12, 8, unit="short"),
        timeseries_panel(6, "各控制器纳管在线 AP 波动趋势", [
            {"expr": "hwWlanCurOnlineApNum or hh3cDot11CurrOnlineAPNum or ruijieApcOnlineApNum or cLApTotalUpAPs or wlsxSysExtAccessPointsNum or ruckusZDTotalNumAP", "legendFormat": "{{hostname}} ({{instance}}) · {{vendor}}", "refId": "A"}
        ], 12, 4, 12, 8, unit="short"),
        bar_gauge_panel(7, "各无线控制器客户端负载 Top 榜", "hwWlanCurAssocUserNum or hh3cDot11CurrAssocUserNum or ruijieApcTotalStaNum or cLSysTotalNumOfClients or wlsxSysExtStationsNum or ruckusZDTotalNumSta", 0, 12, 12, 8, unit="short"),
        table_panel(8, "全网无线控制器 AC 状态清单", "hwWlanCurOnlineApNum or hh3cDot11CurrOnlineAPNum or ruijieApcOnlineApNum or cLApTotalUpAPs or wlsxSysExtAccessPointsNum or ruckusZDTotalNumAP", 12, 12, 12, 8)
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
                {
                    "allValue": ".*",
                    "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
                    "definition": "label_values(ifOperStatus, site_id)",
                    "includeAll": True,
                    "label": "站点",
                    "multi": True,
                    "name": "site",
                    "options": [],
                    "query": {"query": "label_values(ifOperStatus, site_id)", "refId": "StandardVariableQuery"},
                    "refresh": 1,
                    "type": "query"
                }
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "03 无线专网监控 (Wireless AP & Clients)",
        "uid": "nexora-network-wireless",
        "version": 1
    }

# 4. Interface Traffic & Health Dashboard
def build_interface_dashboard():
    panels = [
        stat_panel(1, "全网聚合入流量 (Inbound)", "sum(rate(ifHCInOctets[5m])) * 8", 0, 0, 6, 4, unit="bps", color="#3274D9"),
        stat_panel(2, "全网聚合出流量 (Outbound)", "sum(rate(ifHCOutOctets[5m])) * 8", 6, 0, 6, 4, unit="bps", color="#56A64B"),
        stat_panel(3, "实时错误包总速率", "sum(rate(ifInErrors[5m]) + rate(ifOutErrors[5m]))", 12, 0, 6, 4, unit="pps", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 10}, {"color": "red", "value": 100}]),
        stat_panel(4, "实时丢弃包总速率", "sum(rate(ifInDiscards[5m]) + rate(ifOutDiscards[5m]))", 18, 0, 6, 4, unit="pps", thresholds=[{"color": "green", "value": None}, {"color": "#E0B400", "value": 10}, {"color": "red", "value": 100}]),
        timeseries_panel(5, "高负荷端口入流量 Top 10", [
            {"expr": "topk(10, rate(ifHCInOctets{site_id=~\"$site\",instance=~\"$device\"}[5m]) * 8)", "legendFormat": "{{instance}} - {{ifName}}", "refId": "A"}
        ], 0, 4, 12, 8, unit="bps"),
        timeseries_panel(6, "高负荷端口出流量 Top 10", [
            {"expr": "topk(10, rate(ifHCOutOctets{site_id=~\"$site\",instance=~\"$device\"}[5m]) * 8)", "legendFormat": "{{instance}} - {{ifName}}", "refId": "A"}
        ], 12, 4, 12, 8, unit="bps"),
        table_panel(7, "端口带宽利用率 Top 20", "topk(20, (rate(ifHCInOctets{site_id=~\"$site\",instance=~\"$device\"}[5m]) * 8) / (ifHighSpeed * 1000000) * 100)", 0, 12, 12, 8, unit="percent"),
        table_panel(8, "端口错误与丢弃排行 Top 20", "topk(20, rate(ifInErrors{site_id=~\"$site\",instance=~\"$device\"}[5m]) + rate(ifOutErrors{site_id=~\"$site\",instance=~\"$device\"}[5m]) + rate(ifInDiscards{site_id=~\"$site\",instance=~\"$device\"}[5m]))", 12, 12, 12, 8, unit="pps")
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
                {
                    "allValue": ".*",
                    "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
                    "definition": "label_values(ifOperStatus, site_id)",
                    "includeAll": True,
                    "label": "站点",
                    "multi": True,
                    "name": "site",
                    "options": [],
                    "query": {"query": "label_values(ifOperStatus, site_id)", "refId": "StandardVariableQuery"},
                    "refresh": 1,
                    "type": "query"
                },
                {
                    "allValue": ".*",
                    "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
                    "definition": "label_values(ifOperStatus{site_id=~\"$site\"}, instance)",
                    "includeAll": True,
                    "label": "设备",
                    "multi": True,
                    "name": "device",
                    "options": [],
                    "query": {"query": "label_values(ifOperStatus{site_id=~\"$site\"}, instance)", "refId": "StandardVariableQuery"},
                    "refresh": 1,
                    "type": "query"
                }
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "04 接口流量与健康 (Interface Traffic & Health)",
        "uid": "nexora-network-interface",
        "version": 1
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
        table_panel(7, "采集失败设备清单 (Target Scrape Failure)", "up == 0", 0, 12, 12, 8),
        table_panel(8, "采集最慢目标排行 Top 10", "topk(10, scrape_duration_seconds)", 12, 12, 12, 8, unit="s")
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
    }
    for filename, data in dashboards.items():
        path = os.path.join(DASHBOARDS_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Generated {filename} -> {path}")

if __name__ == "__main__":
    main()
