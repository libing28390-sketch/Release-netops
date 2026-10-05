import json
import os
from copy import deepcopy
from pathlib import Path

false = False
true = True
null = None

ROOT_DIR = Path(__file__).resolve().parents[2]
DASHBOARDS_DIR = ROOT_DIR / "monitoring" / "grafana" / "dashboards"
PRESENTATION_CONFIG_PATH = ROOT_DIR / "monitoring" / "grafana" / "dashboard_presentation_v2.json"
DS_UID = "victoriametrics"
DASHBOARD_VERSION = 30
NO_VALUE_TEXT = "暂无采集数据"

# Nexora NOC Dark V2 palette. These defaults also keep newly authored panels
# aligned with the checked-in V2 presentation source below.
INFO_COLOR = "#3B82F6"
PRIMARY_BLUE_COLOR = INFO_COLOR
CYAN_COLOR = "#22D3EE"
HEALTHY_COLOR = "#22C55E"
PURPLE_COLOR = "#A78BFA"
WARNING_COLOR = "#F59E0B"
HIGH_COLOR = "#F97316"
CRITICAL_COLOR = "#F43F5E"
NEUTRAL_COLOR = "#64748B"
SOFT_GRAY_COLOR = "#94A3B8"
CLIENT_COLOR = PURPLE_COLOR

# Direction and fault colors are fixed by the V2 semantic palette.
INBOUND_COLOR = CYAN_COLOR
OUTBOUND_COLOR = PRIMARY_BLUE_COLOR
ERROR_COLOR = WARNING_COLOR
DISCARD_COLOR = CRITICAL_COLOR
MULTICAST_COLOR = PURPLE_COLOR
BROADCAST_COLOR = WARNING_COLOR
PPS_COLOR = CYAN_COLOR
UNKNOWN_COLOR = NEUTRAL_COLOR

ALERT_SEVERITY_LABELS = (
    ("critical", "严重"),
    ("major", "主要"),
    ("warning", "警告"),
    ("minor", "次要"),
    ("high", "高"),
    ("medium", "中"),
    ("low", "低"),
    ("info", "提示"),
    ("unknown", "未知"),
)

ALERT_SEVERITY_COLORS = {
    "critical": CRITICAL_COLOR,
    "major": HIGH_COLOR,
    "warning": WARNING_COLOR,
    "minor": PURPLE_COLOR,
    "high": HIGH_COLOR,
    "medium": WARNING_COLOR,
    "low": NEUTRAL_COLOR,
    "info": INFO_COLOR,
    "unknown": NEUTRAL_COLOR,
}


def alert_severity_thresholds(severity):
    """Color an open-alert count by severity without coloring zero as bad."""
    color = ALERT_SEVERITY_COLORS.get(severity, NEUTRAL_COLOR)
    steps = [{"color": HEALTHY_COLOR, "value": None}]
    if color != HEALTHY_COLOR:
        steps.append({"color": color, "value": 1})
    return steps

NO_COMPLETED_DELIVERY_VALUE_MAPPINGS = [
    {
        "type": "value",
        "options": {
            "-1": {"text": "暂无已完成投递", "color": NEUTRAL_COLOR},
        },
    },
]

UTILIZATION_THRESHOLDS = [
    {"color": HEALTHY_COLOR, "value": None},
    {"color": WARNING_COLOR, "value": 60},
    {"color": HIGH_COLOR, "value": 75},
    {"color": CRITICAL_COLOR, "value": 90},
]

OFFLINE_COUNT_THRESHOLDS = [
    {"color": HEALTHY_COLOR, "value": None},
    {"color": WARNING_COLOR, "value": 1},
    {"color": CRITICAL_COLOR, "value": 5},
]

AP_STATE_VALUE_MAPPINGS = [
    {
        "type": "value",
        "options": {
            "associated": {"text": "在线", "color": HEALTHY_COLOR},
            "run": {"text": "在线", "color": HEALTHY_COLOR},
            "active": {"text": "在线", "color": HEALTHY_COLOR},
            "deassociated": {"text": "离线", "color": CRITICAL_COLOR},
            "idle": {"text": "离线", "color": CRITICAL_COLOR},
            "down": {"text": "离线", "color": CRITICAL_COLOR},
            "join": {"text": "接入中", "color": WARNING_COLOR},
            "joining": {"text": "接入中", "color": WARNING_COLOR},
            "joinack": {"text": "接入中", "color": WARNING_COLOR},
            "config": {"text": "接入中", "color": WARNING_COLOR},
            "data check": {"text": "接入中", "color": WARNING_COLOR},
            "image load": {"text": "接入中", "color": WARNING_COLOR},
            "downloading image": {"text": "接入中", "color": WARNING_COLOR},
        },
    },
]

STATUS_VALUE_MAPPINGS = [
    {
        "type": "value",
        "options": {
            "1": {"text": "Up", "color": HEALTHY_COLOR},
            "2": {"text": "down", "color": CRITICAL_COLOR},
            "0": {"text": "UNKNOWN", "color": NEUTRAL_COLOR},
            "3": {"text": "UNKNOWN", "color": NEUTRAL_COLOR},
            "4": {"text": "UNKNOWN", "color": NEUTRAL_COLOR},
            "5": {"text": "UNKNOWN", "color": NEUTRAL_COLOR},
            "6": {"text": "UNKNOWN", "color": NEUTRAL_COLOR},
            "7": {"text": "UNKNOWN", "color": NEUTRAL_COLOR},
        },
    },
    {
        "type": "special",
        "options": {
            "match": "null",
            "result": {"text": "UNKNOWN", "color": NEUTRAL_COLOR},
        },
    },
    {
        "type": "special",
        "options": {
            "match": "nan",
            "result": {"text": "UNKNOWN", "color": NEUTRAL_COLOR},
        },
    },
]

ADMIN_STATUS_VALUE_MAPPINGS = [
    {
        "type": "value",
        "options": {
            "1": {"text": "启用"},
            "2": {"text": "停用"},
            "3": {"text": "测试中"},
            "0": {"text": "未知"},
            "4": {"text": "未知"},
            "5": {"text": "未知"},
            "6": {"text": "未知"},
            "7": {"text": "未知"},
        },
    },
    {
        "type": "special",
        "options": {
            "match": "null",
            "result": {"text": "未知"},
        },
    },
    {
        "type": "special",
        "options": {
            "match": "nan",
            "result": {"text": "未知"},
        },
    },
]

RECENT_CHANGE_VALUE_MAPPINGS = [
    {
        "type": "value",
        "options": {
            "0": {"text": "当前无近期变化", "color": HEALTHY_COLOR},
        },
    },
]

INTERFACE_ROLE_LABEL = "接口用途"
INTERFACE_ROLE_VALUE_MAPPINGS = [
    {
        "type": "value",
        "options": {
            "unclassified": {"text": "用途待确认", "color": NEUTRAL_COLOR},
        },
    },
]

DEV_JOIN = ""
IF_JOIN = "* on(instance, ifIndex) group_left(ifName) ((ifName * 0 + 1) or on(instance, ifIndex) (ifOperStatus * 0 + 1))"
NETWORK_JOB = 'job="network_snmp"'
HARDWARE_INVENTORY_JOB = 'job="platform_hardware_inventory"'
WIRELESS_DEVICE_LABELS = "site_name,vendor,role,hostname"


def wireless_clients_by_device(network_selector, inventory_selector):
    """Return the shared controller/SSID client contract by device.

    The normalized inventory can expose both a controller total and one row
    per SSID. Prefer the controller series, fall back to the SSID aggregate,
    and only use the legacy SNMP counters when inventory has no client
    series. Grouping on the four stable device labels prevents duplicate
    controller/SSID rows from being counted together. No zero fallback is
    introduced, so a missing source remains No data while a real zero stays
    visible as zero.
    """
    legacy_clients = (
        f"sum by ({WIRELESS_DEVICE_LABELS}) ("
        f"hwWlanCurAssocUserNum{{{network_selector}}} or "
        f"hh3cDot11CurrAssocUserNum{{{network_selector}}} or "
        f"ruijieApcTotalStaNum{{{network_selector}}} or "
        f"cLSysTotalNumOfClients{{{network_selector}}} or "
        f"wlsxSysExtStationsNum{{{network_selector}}} or "
        f"ruckusZDTotalNumSta{{{network_selector}}})"
    )
    controller_clients = (
        f"sum by ({WIRELESS_DEVICE_LABELS}) ("
        f"nexora_wireless_sensor_value{{{inventory_selector},"
        'component_class="wireless_controller",sensor_class="clients"})'
        ")"
    )
    ssid_clients = (
        f"sum by ({WIRELESS_DEVICE_LABELS}) ("
        f"nexora_wireless_sensor_value{{{inventory_selector},"
        'component_class="wireless_ssid",sensor_class="clients"})'
        ")"
    )
    inventory_clients = (
        f"({controller_clients} or on({WIRELESS_DEVICE_LABELS}) {ssid_clients})"
    )
    expression = (
        f"(({legacy_clients} unless on({WIRELESS_DEVICE_LABELS}) "
        f"({inventory_clients})) or on({WIRELESS_DEVICE_LABELS}) "
        f"({inventory_clients}))"
    )
    # Keep the query contract executable and reviewable: this guard catches a
    # future edit that accidentally drops the SSID fallback or fabricates 0.
    assert f"sum by ({WIRELESS_DEVICE_LABELS})" in expression
    assert 'component_class="wireless_controller",sensor_class="clients"' in expression
    assert 'component_class="wireless_ssid",sensor_class="clients"' in expression
    assert "vector(0)" not in expression
    return expression


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
    # CMDB label changes can leave multiple series for the same interface
    # identity, differing only in enriched labels. Normalize metadata before
    # group_left so every (instance, ifIndex) has a unique join side.
    name_expr = f"max by (instance, ifIndex, ifName) (ifName{{{selector}}} * 0 + 1)"
    alias_selector = alias_selector or selector
    alias_source = f"max by (instance, ifIndex, ifAlias) (ifAlias{{{alias_selector}}} * 0 + 1)"
    metadata_expr = (
        f"(({name_expr}) * on(instance, ifIndex) group_left(ifAlias) "
        f"({alias_source})) or on(instance, ifIndex) ({name_expr})"
    )
    if fallback_status:
        status_fallback = f"max by (instance, ifIndex) (ifOperStatus{{{selector}}} * 0 + 1)"
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
    return f'label_replace({empty_selection}, "ifName", "近24h无近期变化", "", "")'

def stat_panel(
    pid,
    title,
    expr,
    x,
    y,
    w=4,
    h=4,
    unit="",
    color=INFO_COLOR,
    thresholds=None,
    description=None,
    graph_mode="none",
    value_mappings=None,
    no_value=None,
):
    steps = [{"color": color, "value": None}]
    if thresholds:
        steps = thresholds
    no_value_text = NO_VALUE_TEXT if no_value is None else no_value
    mappings = deepcopy(value_mappings or [])
    mapped_specials = {
        (item.get("options") or {}).get("match")
        for item in mappings
        if item.get("type") == "special"
    }
    for match in ("null", "nan"):
        if match not in mapped_specials:
            mappings.append({
                "type": "special",
                "options": {
                    "match": match,
                    "result": {"text": no_value_text, "color": NEUTRAL_COLOR},
                },
            })

    panel = {
        "id": pid,
        "title": title,
        "type": "stat",
        "datasource": {"type": "prometheus", "uid": DS_UID},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "noValue": no_value_text,
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": steps}
            },
            "overrides": []
        },
        "options": {
            "colorMode": "value",
            "graphMode": graph_mode,
            "justifyMode": "center",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto"
        },
        # Stat cards represent current state or a rolling aggregate's current
        # sample; a range query plus lastNotNull can retain a stale value after
        # the source series disappears.
        "targets": [{"expr": expr, "refId": "A", "instant": True}]
    }
    if mappings:
        panel["fieldConfig"]["defaults"]["mappings"] = mappings
    if description:
        panel["description"] = description
    return panel


def gauge_panel(pid, title, expr, x, y, w=6, h=5, unit="percent", thresholds=None, description=None):
    """Render one selected device's current hardware utilization as a Gauge."""
    steps = thresholds or [
        {"color": HEALTHY_COLOR, "value": None},
        {"color": WARNING_COLOR, "value": 70},
        {"color": CRITICAL_COLOR, "value": 85},
    ]
    panel = {
        "id": pid,
        "title": title,
        "type": "gauge",
        "datasource": {"type": "prometheus", "uid": DS_UID},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "min": 0,
                "max": 100,
                "noValue": NO_VALUE_TEXT,
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": steps},
            },
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showThresholdLabels": False,
            "showThresholdMarkers": True,
        },
        "targets": [{"expr": expr, "instant": True, "refId": "A"}],
    }
    if description:
        panel["description"] = description
    return panel

def timeseries_color_override(matcher_id, matcher_options, color):
    return {
        "matcher": {"id": matcher_id, "options": matcher_options},
        "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}],
    }


def timeseries_panel(
    pid,
    title,
    targets,
    x,
    y,
    w=12,
    h=8,
    unit="",
    color_overrides=None,
    legend_display_mode="table",
    legend_placement="right",
    legend_calcs=None,
    description=None,
    line_interpolation="linear",
):
    panel = {
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
                    "lineInterpolation": line_interpolation,
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
                "displayMode": legend_display_mode,
                "placement": legend_placement,
                "showLegend": True,
                "calcs": legend_calcs if legend_calcs is not None else ["lastNotNull", "max", "mean"],
            },
            "tooltip": {"mode": "multi", "sort": "desc"}
        },
        "targets": targets
    }
    if description:
        panel["description"] = description
    return panel

def clean_organize_transformation(
    value_col_name="数值",
    extra_renames=None,
    extra_indices=None,
    *,
    interface_description_label="ifDescr",
    keep_asset_id=False,
    extra_excludes=None,
):
    description_index = interface_description_label
    renames = {
        "sysName": "设备名称",
        "hostname": "设备名称",
        "instance": "采集目标",
        "site_name": "站点",
        "ifName": "接口全称",
        interface_description_label: "接口描述",
        "vendor": "厂商",
        "role": "角色",
        "interface_role": INTERFACE_ROLE_LABEL,
        "utilization_warn_pct": "预警阈值 (%)",
        "utilization_high_pct": "高位阈值 (%)",
        "utilization_critical_pct": "严重阈值 (%)",
        "Value": value_col_name,
    }
    if keep_asset_id:
        renames["asset_id"] = "资产 ID"
    if extra_renames:
        renames.update(extra_renames)
    index_by_name = {
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
    }
    if keep_asset_id:
        index_by_name["asset_id"] = 2
    if extra_indices:
        index_by_name.update(extra_indices)
    excludes = {
        "Time": True,
        "__name__": True,
        "ifIndex": True,
        "asset_id": not keep_asset_id,
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
    }
    if extra_excludes:
        excludes.update(extra_excludes)
    result = [
        {
            "id": "organize",
            "options": {
                "excludeByName": excludes,
                "indexByName": index_by_name,
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
    device_detail_link=False,
    color_mapped_cells=False,
    mapped_cell_mode="color-text",
    extra_value_mappings=None,
    description=None,
    map_interface_role=None,
    extra_color_mapped_cells=None,
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
                "value": {"type": mapped_cell_mode},
            }],
        })
    for field_name, mappings in (extra_value_mappings or {}).items():
        overrides.append({
            "matcher": {"id": "byName", "options": field_name},
            "properties": [{"id": "mappings", "value": mappings}],
        })
    for field_name, cell_mode in (extra_color_mapped_cells or {}).items():
        overrides.append({
            "matcher": {"id": "byName", "options": field_name},
            "properties": [{
                "id": "custom.cellOptions",
                "value": {"type": cell_mode},
            }],
        })
    if detail_link:
        overrides.append({
            "matcher": {"id": "byName", "options": "接口全称"},
            "properties": [{
                "id": "links",
                "value": [{
                    "title": "打开接口详情",
                    "url": "/d/nexora-interface-detail/interface-detail?var-site=${__data.fields[\"站点\"]}&var-vendor=${__data.fields[\"厂商\"]}&var-role=${__data.fields[\"角色\"]}&var-device=${__data.fields[\"设备名称\"]}&var-interface_role=${__data.fields[\"接口用途\"]}&var-interface=${__data.fields[\"接口全称\"]}&from=${__from}&to=${__to}",
                    "targetBlank": False,
                }],
            }],
        })
    if device_detail_link:
        overrides.append({
            "matcher": {"id": "byName", "options": "资产 ID"},
            "properties": [{
                "id": "links",
                "value": [{
                    "title": "打开设备详情",
                    "url": "/d/nexora-network-device/device-detail?var-asset_id=${__data.fields[\"资产 ID\"]}&from=${__from}&to=${__to}",
                    "targetBlank": False,
                }],
            }],
        })
    query_sources = [expr] + [target.get("expr", "") for target in (targets or [])]
    if map_interface_role is None:
        map_interface_role = "interface_role" in " ".join(query_sources)
    if map_interface_role:
        overrides.append({
            "matcher": {"id": "byName", "options": INTERFACE_ROLE_LABEL},
            "properties": [{"id": "mappings", "value": INTERFACE_ROLE_VALUE_MAPPINGS}],
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
    if description:
        panel["description"] = description
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
    existing_ids = {panel.get("id") for panel in panels}
    next_row_id = 900
    for title, before_y in sorted(sections, key=lambda item: item[1]):
        shift = sum(1 for _, prior_y in sections if prior_y < before_y)
        row_y = before_y + shift
        while next_row_id in existing_ids:
            next_row_id += 1
        rows.append(row_panel(next_row_id, title, row_y))
        existing_ids.add(next_row_id)
        next_row_id += 1
        for panel in panels:
            grid = panel.get("gridPos") or {}
            if int(grid.get("y", -1)) >= before_y:
                grid["y"] = int(grid["y"]) + 1
    return sorted([*panels, *rows], key=lambda panel: (panel.get("gridPos", {}).get("y", 0), panel.get("gridPos", {}).get("x", 0)))


def normalize_summary_cards(panels, target_height=4):
    """Give the first row of Stat/Gauge summaries enough vertical room for clear values."""
    summary_panels = [panel for panel in panels if panel.get("type") in {"stat", "gauge"}]
    if not summary_panels:
        return panels

    summary_y = min(int((panel.get("gridPos") or {}).get("y", 0)) for panel in summary_panels)
    summary_row = [
        panel for panel in summary_panels
        if int((panel.get("gridPos") or {}).get("y", 0)) == summary_y
    ]
    old_bottom = max(
        int((panel.get("gridPos") or {}).get("y", 0))
        + int((panel.get("gridPos") or {}).get("h", 0))
        for panel in summary_row
    )
    target_bottom = summary_y + max(
        target_height,
        max(int((panel.get("gridPos") or {}).get("h", 0)) for panel in summary_row),
    )
    shift = target_bottom - old_bottom

    for panel in summary_row:
        grid = panel.setdefault("gridPos", {})
        grid["h"] = max(target_height, int(grid.get("h", 0)))
    if shift > 0:
        summary_ids = {panel.get("id") for panel in summary_row}
        for panel in panels:
            if panel.get("id") in summary_ids:
                continue
            grid = panel.get("gridPos") or {}
            if int(grid.get("y", -1)) >= old_bottom:
                grid["y"] = int(grid["y"]) + shift
    return panels

def bar_gauge_panel(
    pid,
    title,
    expr,
    x,
    y,
    w=12,
    h=8,
    unit="percent",
    *,
    legend_format="{{sysName}} {{instance}}",
    thresholds=None,
    max_value=100,
    color=None,
    color_overrides=None,
    instant=False,
    description=None,
):
    defaults = {"unit": unit, "min": 0, "noValue": NO_VALUE_TEXT}
    if max_value is not None:
        defaults["max"] = max_value
    if color:
        defaults["color"] = {"mode": "fixed", "fixedColor": color}
    else:
        defaults["color"] = {"mode": "thresholds"}
    threshold_steps = thresholds if thresholds is not None else UTILIZATION_THRESHOLDS
    if threshold_steps:
        defaults["thresholds"] = {"mode": "absolute", "steps": threshold_steps}
    panel = {
        "id": pid,
        "title": title,
        "type": "bargauge",
        "datasource": {"type": "prometheus", "uid": DS_UID},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": defaults,
            "overrides": color_overrides or []
        },
        "options": {
            "displayMode": "gradient",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "values": false}
        },
        "targets": [{
            "expr": expr,
            "legendFormat": legend_format,
            "instant": instant,
            "refId": "A",
        }],
    }
    if description:
        panel["description"] = description
    return panel

def make_query_variable(name, label, query_str, multi=True, include_all=True, regex=None):
    variable = {
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
    if regex is not None:
        variable["regex"] = regex
    return variable


def make_admin_down_variable():
    """Expose intentionally disabled interfaces on demand in the status table."""
    return {
        "current": {"selected": True, "text": "隐藏管理停用", "value": "0"},
        "hide": 0,
        "includeAll": False,
        "label": "接口范围",
        "multi": False,
        "name": "show_admin_down",
        "options": [
            {"selected": True, "text": "隐藏管理停用", "value": "0"},
            {"selected": False, "text": "显示管理停用", "value": "1"},
        ],
        "query": "隐藏管理停用 : 0,显示管理停用 : 1",
        "skipUrlSync": False,
        "type": "custom",
    }

def make_network_variables(multi_device=True, include_all_device=True, device_label="设备"):
    network_targets = 'up{job="network_snmp"'
    return [
        make_query_variable(
            "site", "站点",
            f'query_result(count by (site_name) ({network_targets}}}))',
            regex='/.*site_name="([^"]+)".*/',
        ),
        make_query_variable(
            "vendor", "厂商",
            f'query_result(count by (vendor) ({network_targets},site_name=~"$site"}}))',
            regex='/.*vendor="([^"]+)".*/',
        ),
        make_query_variable(
            "role", "角色",
            f'query_result(count by (role) ({network_targets},site_name=~"$site",vendor=~"$vendor"}}))',
            regex='/.*role="([^"]+)".*/',
        ),
        make_query_variable(
            "device", device_label,
            f'query_result(count by (hostname) ({network_targets},site_name=~"$site",vendor=~"$vendor",role=~"$role"}}))',
            multi=multi_device,
            include_all=include_all_device,
            regex='/.*hostname="([^"]+)".*/',
        ),
    ]

def make_interface_variables(
    multi_device=True,
    include_all_device=True,
    include_all_interface=True,
    interface_label="接口",
    device_label="设备",
    multi_interface=True,
    include_threshold_values=False,
    include_admin_down_selector=False,
):
    vars = make_network_variables(multi_device=multi_device, include_all_device=include_all_device, device_label=device_label)
    vars.append(
        make_query_variable(
            "interface_role",
            INTERFACE_ROLE_LABEL,
            f'label_values({{__name__=~"ifName",{NETWORK_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"}}, interface_role)',
        )
    )
    if include_admin_down_selector:
        vars.append(make_admin_down_variable())
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
    inventory_sel = f'{HARDWARE_INVENTORY_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    hardware_target_sel = f'{target_sel},asset_id!=""'
    target_site_sel = f'{NETWORK_JOB},site_name!="",site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    in_rate = counter_rate_expr("ifHCInOctets", "ifInOctets", sel)
    out_rate = counter_rate_expr("ifHCOutOctets", "ifOutOctets", sel)
    hardware_sel = 'asset_id!="",site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    hardware_info_labels = (
        "tenant_id, asset_id, sensor_key, sensor_name, group, index, "
        "component_class, source_id, hostname, site_name, vendor, role, platform"
    )

    def hardware_metric(metric):
        info = (
            f"max by ({hardware_info_labels}) "
            f"(nexora_hw_sensor_info{{{hardware_sel}}})"
        )
        return (
            f"({metric}{{{hardware_sel}}} "
            "* on(tenant_id, asset_id, sensor_key) "
            "group_left(sensor_name, group, index, component_class, source_id) "
            f"({info}))"
        )

    cpu_metric = f'nexora_hw_cpu_usage_percent{{{hardware_sel}}}'
    memory_metric = f'nexora_hw_memory_usage_percent{{{hardware_sel}}}'
    temperature_metric = f'nexora_hw_temperature_celsius{{{hardware_sel}}}'
    cpu_expr = (
        "max by (tenant_id, asset_id, hostname, site_name, vendor, role, window) "
        f"({cpu_metric})"
    )
    mem_expr = hardware_metric("nexora_hw_memory_usage_percent")
    temperature_expr = hardware_metric("nexora_hw_temperature_celsius")
    online_devices_expr = f'count(count by (instance) (up{{{target_sel}}} == 1))'

    def online_metric_device_count(metric_expr):
        covered_devices = (
            f'count(count by (asset_id) (({metric_expr}) '
            f'and on(asset_id) (up{{{hardware_target_sel}}} == 1)))'
        )
        no_metric_fallback = f'(({online_devices_expr} > 0) * 0)'
        return f'{covered_devices} or on() {no_metric_fallback}'

    ap_online_expr = (
        f"sum((hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or "
        f"ruijieApcTotalApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}))"
    )
    client_online_by_device = wireless_clients_by_device(sel, inventory_sel)
    client_online_expr = f"sum({client_online_by_device})"
    anomaly_rows = (
        f'((changes(ifOperStatus{{{sel}}}[24h]) > 0) '
        f'and on(instance, ifIndex) (ifOperStatus{{{sel}}} == 2) '
        f'and on(instance, ifIndex) '
        f'max by (instance, ifIndex) (ifAdminStatus{{{sel}}} == 1))'
        f' * on(instance, ifIndex) group_left(ifName) '
        f'(max by (instance, ifIndex, ifName) (ifName{{{sel}}} * 0 + 1))'
    )
    anomaly_fallback = interface_empty_fallback(f"ifOperStatus{{{sel}}}", anomaly_rows)
    hardware_asset_excludes = {
        "tenant_id": True,
        "device_id": True,
        "sensor_key": True,
        "component_class": True,
        "source_type": True,
        "source_id": True,
        "rule_version": True,
        "measurement_type": True,
    }
    cpu_overview_transform = clean_organize_transformation(
        "CPU 使用率 (%)",
        extra_renames={"window": "CPU 窗口"},
        extra_indices={
            "site_name": 0, "hostname": 1, "asset_id": 2,
            "vendor": 3, "role": 4, "window": 5, "Value": 6,
        },
        keep_asset_id=True,
        extra_excludes=hardware_asset_excludes,
    )
    hardware_sensor_transform = clean_organize_transformation(
        extra_renames={
            "asset_id": "资产 ID", "sensor_name": "部件名称",
            "group": "部件分组",
        },
        extra_indices={
            "site_name": 0, "hostname": 1, "asset_id": 2,
            "vendor": 3, "role": 4, "sensor_name": 5,
            "group": 6, "Value": 7,
        },
        keep_asset_id=True,
        extra_excludes={**hardware_asset_excludes, "window": True, "index": True},
    )

    panels = [
        stat_panel(1, "纳管设备数", f'count(count by (instance) (up{{{target_sel}}}))', 0, 0, 4, 3),
        stat_panel(2, "监控站点数", f'count(count by (site_name) (up{{{target_site_sel}}}))', 4, 0, 4, 3),
        stat_panel(3, "全网在线数", f'count(count by (instance) (up{{{target_sel}}} == 1)) or on() ((count(up{{{target_sel}}}) > 0) * 0)', 8, 0, 4, 3),
        stat_panel(
            4, "控制器汇总在线终端数", client_online_expr, 12, 0, 4, 3,
        ),
        stat_panel(5, "采集接口总数", f"count(count by (instance, ifIndex) (ifOperStatus{{{sel}}}))", 16, 0, 4, 3),
        stat_panel(6, "近24h变动且当前 Down 接口数", f'count({anomaly_rows}) or on() ((count(ifOperStatus{{{sel}}}) > 0) * 0)', 20, 0, 4, 3, thresholds=[
            {"color": NEUTRAL_COLOR, "value": None},
            {"color": WARNING_COLOR, "value": 1},
            {"color": CRITICAL_COLOR, "value": 5}
        ], description="只统计已启用、当前 Down 且24小时内状态有变化的接口。"),
        timeseries_panel(7, "接口总流量趋势", [
            {"expr": f"sum({in_rate}) * 8", "legendFormat": "入流量", "refId": "A"},
            {"expr": f"sum({out_rate}) * 8", "legendFormat": "出流量", "refId": "B"}
        ], 0, 3, 12, 8, unit="bps", legend_display_mode="list", legend_placement="bottom", legend_calcs=[], color_overrides=[
            timeseries_color_override("byName", "入流量", INBOUND_COLOR),
            timeseries_color_override("byName", "出流量", OUTBOUND_COLOR),
        ]),
        timeseries_panel(8, "全网无线终端与 AP 规模趋势", [
            {"expr": f"sum({client_online_by_device})", "legendFormat": "控制器统计的在线终端", "refId": "A"},
            {"expr": f"sum((hwWlanCurOnlineApNum{{{sel}}} or hh3cDot11CurrOnlineAPNum{{{sel}}} or ruijieApcOnlineApNum{{{sel}}} or ruijieApcTotalApNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}}))", "legendFormat": "在线 AP 总数", "refId": "B"}
        ], 12, 3, 12, 8, unit="short", legend_display_mode="list", legend_placement="bottom", legend_calcs=[]),
        stat_panel(
            9, "CPU 指标覆盖设备数", online_metric_device_count(cpu_metric), 0, 11, 8, 3,
            description=None,
        ),
        stat_panel(
            10, "内存指标覆盖设备数", online_metric_device_count(memory_metric), 8, 11, 8, 3,
            description="没有采到指标不代表使用率为 0。",
        ),
        stat_panel(
            11, "温度指标覆盖设备数", online_metric_device_count(temperature_metric), 16, 11, 8, 3,
            description="温度阈值因设备而异，请查看设备详情。",
        ),
        table_panel(
            15, "设备 CPU 使用率 Top10（按 window）", f"topk by (window) (10, {cpu_expr})", 0, 14, 8, 8,
            unit="percent",
            transformations=cpu_overview_transform,
            value_col_name="CPU 使用率 (%)",
            device_detail_link=True,
            description="按采样窗口分别排名，不混合不同窗口。",
        ),
        table_panel(
            16, "内存池使用率 Top10", f"topk(10, {mem_expr})", 8, 14, 8, 8,
            unit="percent",
            transformations=hardware_sensor_transform,
            value_col_name="数值",
            device_detail_link=True,
            description=None,
        ),
        table_panel(
            25, "温度传感器 Top10", f"topk(10, {temperature_expr})", 16, 14, 8, 8,
            unit="celsius",
            transformations=hardware_sensor_transform,
            value_col_name="数值",
            device_detail_link=True,
            description=None,
        ),
        table_panel(
            12, "设备总吞吐速率 Top10",
            f"topk(10, (sum by (hostname, site_name, instance, vendor) ({in_rate} * 8) + sum by (hostname, site_name, instance, vendor) ({out_rate} * 8)))",
            0, 22, 12, 8, unit="bps",
            transformations=clean_organize_transformation("总速率 (bit/s)"),
            value_col_name="总速率 (bit/s)",
            description="按近5分钟吞吐速率排序；这是速率，不是累计流量。",
        ),
        timeseries_panel(13, "错误/丢弃趋势", [
            {"expr": f"sum(rate(ifInErrors{{{sel}}}[5m])) + sum(rate(ifOutErrors{{{sel}}}[5m]))", "legendFormat": "错误包/秒", "refId": "A"},
            {"expr": f"sum(rate(ifInDiscards{{{sel}}}[5m])) + sum(rate(ifOutDiscards{{{sel}}}[5m]))", "legendFormat": "丢弃包/秒", "refId": "B"}
        ], 12, 22, 12, 8, unit="pps", legend_display_mode="list", legend_placement="bottom", legend_calcs=[], color_overrides=[
            timeseries_color_override("byName", "错误包/秒", ERROR_COLOR),
            timeseries_color_override("byName", "丢弃包/秒", DISCARD_COLOR),
        ]),
        table_panel(
            14, "近24h状态变动且当前仍 Down Top20",
            f"topk(20, {anomaly_rows}) or {anomaly_fallback}",
            0, 30, 24, 8,
            transformations=clean_organize_transformation("24h变化次数"),
            value_col_name="24h变化次数",
            value_mappings=RECENT_CHANGE_VALUE_MAPPINGS,
            detail_link=True,
            description="只列当前 Down 且24小时内状态变动过的接口；长期 Down 不在此列。",
            map_interface_role=True,
        )
    ]

    panels = insert_section_rows(panels, [
        ("网络健康与规模", 0),
        ("趋势与设备健康", 3),
        ("资源覆盖与设备热点", 11),
        ("流量排行与链路质量", 22),
        ("近期链路状态变动", 30),
    ])
    panels = normalize_summary_cards(panels)

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
        "description": "硬件概览使用 LibreNMS 规则采集后规范化的 nexora_hw_* 指标展示在线设备 CPU、内存池和温度传感器覆盖及热点排行。CPU Top10 按实际 window 分组，设备取窗口内最高处理器读数；内存池和温度按各自部件排序，不跨部件求平均。排行表资产 ID 可打开单设备详情。接口异常列表仅列出过去24小时状态有变化且当前仍为 Down 的管理启用接口；长期稳定 Down 的接口可在设备或接口详情查看。",
        "uid": "nexora-network-overview",
        "version": DASHBOARD_VERSION
    }

# 2. Network Device Detail Dashboard
def build_device_dashboard():
    dev_sel = f'{NETWORK_JOB},asset_id="$asset_id",asset_id!=""'
    in_rate = counter_rate_expr("ifHCInOctets", "ifInOctets", dev_sel)
    out_rate = counter_rate_expr("ifHCOutOctets", "ifOutOctets", dev_sel)
    dev_if_join = filtered_interface_join(dev_sel)

    # The sensor info metric carries presentation labels. Keep its join unique
    # and match raw samples on the complete tenant/asset/sensor identity.
    info_labels = (
        "tenant_id, asset_id, sensor_key, sensor_name, group, index, "
        "component_class, source_id, hostname, site_name, vendor, platform, "
        "ent_physical_index, measured_entity_type"
    )
    info_filters = (
        'asset_id="$asset_id",asset_id!="",group=~"$hardware_group",'
        'sensor_name=~"$sensor_name",component_class=~"$component_class"'
    )

    def sensor_info(extra_filters=""):
        return (
            f"max by ({info_labels}) "
            f"(nexora_hw_sensor_info{{{info_filters}{extra_filters}}})"
        )

    def hardware_metric(metric, extra_info_filters="", raw_extra_filters=""):
        return (
            f"({metric}{{asset_id=\"$asset_id\",asset_id!=\"\"{raw_extra_filters}}} "
            " * on(tenant_id, asset_id, sensor_key) "
            "group_left(sensor_name, group, index, component_class, source_id, hostname, site_name, vendor, platform, ent_physical_index, measured_entity_type) "
            f"({sensor_info(extra_info_filters)}))"
        )

    cpu = hardware_metric(
        "nexora_hw_cpu_usage_percent", raw_extra_filters=',window="$cpu_window"'
    )
    memory = hardware_metric("nexora_hw_memory_usage_percent")
    memory_used = hardware_metric("nexora_hw_memory_used_bytes")
    memory_total = hardware_metric("nexora_hw_memory_total_bytes")
    temperature = hardware_metric("nexora_hw_temperature_celsius")
    fan_speed = hardware_metric("nexora_hw_fan_speed_rpm")
    component_state = hardware_metric("nexora_hw_component_state")
    component_present = hardware_metric("nexora_hw_component_present")
    power = hardware_metric("nexora_hw_power_watts")
    optical_power = hardware_metric("nexora_hw_optical_power_dbm")
    generic_sensor = hardware_metric("nexora_hw_sensor_value")
    quality = hardware_metric("nexora_hw_sensor_quality")
    component_state_quality = hardware_metric(
        "nexora_hw_sensor_quality", raw_extra_filters=',measurement_type="component_state"'
    )
    last_success_age = (
        f"(time() - {hardware_metric('nexora_hw_sensor_last_success_timestamp_seconds')})"
    )

    optical_filter = ',group=~"(?i).*(transceiver|optical).*"'
    non_optical_filter = ',group!~"(?i).*(transceiver|optical).*"'
    non_optical_temp = hardware_metric(
        "nexora_hw_temperature_celsius", non_optical_filter
    )
    optical_temp = hardware_metric("nexora_hw_temperature_celsius", optical_filter)
    temperature_peak = (
        f"topk(1, {non_optical_temp}) or on() "
        f"(topk(1, {optical_temp}) unless on() count({non_optical_temp}))"
    )
    cpu_top = f"topk(1, {cpu})"
    memory_top = f"topk(1, {memory})"
    cpu_sensor_count = (
        f"count(max by (tenant_id, asset_id, sensor_key, window) ({cpu}))"
    )
    cpu_overflow_count = f"clamp_min(({cpu_sensor_count}) - 10, 0)"
    abnormal_count = (
        f"count(({component_state} == 1) or ({component_state} == 2)) "
        f"or on() ((count({component_state}) > 0) * 0)"
    )
    unknown_count = (
        f"count({component_state} == 3) "
        f"or on() ((count({component_state}) > 0) * 0)"
    )

    def details_transform(value_name=None, *, keep_asset_id=False):
        excludes = {
            "Time": True,
            "__name__": True,
            "tenant_id": True,
            "asset_id": not keep_asset_id,
            "sensor_key": True,
            "source_id": True,
            "source_type": True,
            "rule_version": True,
            "index": True,
            "ent_physical_index": True,
            "measured_entity_type": True,
            "measurement_type": True,
            "instance": True,
            "hostname": True,
            "site_name": True,
            "vendor": True,
            "platform": True,
        }
        rename = {
            "sensor_name": "部件名称",
            "group": "分组",
            "component_class": "部件类别",
            "unit": "单位",
            "window": "CPU窗口",
        }
        order = {
            "sensor_name": 0,
            "group": 1,
            "component_class": 2,
            "unit": 3,
            "window": 4,
            "Value": 5,
        }
        if value_name:
            rename["Value"] = value_name
        return [{
            "id": "organize",
            "options": {
                "excludeByName": excludes,
                "indexByName": order,
                "renameByName": rename,
            },
        }]

    def current_table(pid, title, expr, x, y, w=12, *, unit="", value_name="当前值", description=None, mappings=None):
        return table_panel(
            pid,
            title,
            expr,
            x,
            y,
            w,
            8,
            unit=unit,
            transformations=details_transform(value_name),
            value_col_name=value_name,
            value_mappings=mappings,
            color_mapped_cells=bool(mappings),
            description=description,
        )

    state_mappings = [{
        "type": "value",
        "options": {
            "0": {"text": "正常", "color": HEALTHY_COLOR},
            "1": {"text": "警告", "color": WARNING_COLOR},
            "2": {"text": "严重", "color": CRITICAL_COLOR},
            "3": {"text": "未知", "color": NEUTRAL_COLOR},
        },
    }]
    identity_panel = table_panel(
        1,
        "设备身份与 SNMP 连通性",
        f"up{{{dev_sel}}}",
        0,
        0,
        24,
        4,
        transformations=[{
            "id": "organize",
            "options": {
                "excludeByName": {
                    "Time": True,
                    "__name__": True,
                    "job": True,
                    "site_id": True,
                    "tenant_id": True,
                },
                "indexByName": {
                    "hostname": 0, "asset_id": 1, "instance": 2, "site_name": 3,
                    "vendor": 4, "platform": 5, "role": 6, "Value": 7,
                },
                "renameByName": {
                    "hostname": "设备名称", "asset_id": "资产 ID", "instance": "采集目标",
                    "site_name": "站点", "vendor": "厂商", "platform": "系统平台",
                    "role": "角色", "Value": "SNMP 连通",
                },
            },
        }],
        value_col_name="SNMP 连通",
        value_mappings=[{
            "type": "value",
            "options": {
                "0": {"text": "不可达", "color": CRITICAL_COLOR},
                "1": {"text": "在线", "color": HEALTHY_COLOR},
            },
        }],
        color_mapped_cells=True,
        description="仅显示所选设备；SNMP 不可达与指标缺失分开呈现。",
    )
    cpu_gauge = gauge_panel(
        3,
        "所选 CPU 采样窗口最高部件使用率",
        cpu_top,
        4,
        3,
        4,
        3,
        thresholds=[
            {"color": HEALTHY_COLOR, "value": None},
            {"color": WARNING_COLOR, "value": 70},
            {"color": CRITICAL_COLOR, "value": 85},
        ],
        description=None,
    )
    cpu_gauge["targets"][0]["legendFormat"] = "{{sensor_name}} · {{group}} · {{window}}"
    memory_gauge = gauge_panel(
        4,
        "最高内存池使用率",
        memory_top,
        8,
        3,
        4,
        3,
        thresholds=[
            {"color": HEALTHY_COLOR, "value": None},
            {"color": WARNING_COLOR, "value": 75},
            {"color": CRITICAL_COLOR, "value": 90},
        ],
        description=None,
    )
    memory_gauge["targets"][0]["legendFormat"] = "{{sensor_name}} · {{group}}"
    temp_stat = stat_panel(
        5,
        "最高温度",
        temperature_peak,
        12,
        3,
        4,
        3,
        unit="celsius",
        color=NEUTRAL_COLOR,
        description=None,
        graph_mode="none",
    )
    temp_stat["targets"][0]["legendFormat"] = "{{sensor_name}} · {{group}}"
    memory_pool_labels = (
        "tenant_id, asset_id, device_id, source_type, "
        "sensor_name, group, index, component_class"
    )
    memory_pool_join_labels = [
        "tenant_id", "asset_id", "device_id", "source_type",
        "sensor_name", "group", "index", "component_class",
    ]
    memory_detail_table = table_panel(
        14,
        "内存池当前读数",
        memory,
        12,
        30,
        12,
        8,
        targets=[
            {
                "expr": f"max by ({memory_pool_labels}) ({memory_used})",
                "format": "table", "instant": True, "refId": "A",
            },
            {
                "expr": f"max by ({memory_pool_labels}) ({memory_total})",
                "format": "table", "instant": True, "refId": "B",
            },
            {
                "expr": f"max by ({memory_pool_labels}) ({memory})",
                "format": "table", "instant": True, "refId": "C",
            },
        ],
        transformations=[
            {"id": "joinByLabels", "options": {"labels": memory_pool_join_labels}},
            {
                "id": "organize",
                "options": {
                    "excludeByName": {
                        "Time": True, "__name__": True, "tenant_id": True,
                        "device_id": True, "sensor_key": True, "source_type": True,
                        "source_id": True, "rule_version": True, "index": True,
                        "ent_physical_index": True, "measured_entity_type": True,
                        "measurement_type": True,
                        "hostname": True, "site_name": True, "vendor": True,
                        "platform": True, "role": True, "window": True,
                    },
                    "indexByName": {
                        "asset_id": 0, "sensor_name": 1, "group": 2,
                        "component_class": 3, "Value #A": 4,
                        "Value #B": 5, "Value #C": 6,
                    },
                    "renameByName": {
                        "asset_id": "资产 ID", "sensor_name": "内存池",
                        "group": "分组",
                        "component_class": "部件类别",
                        "Value #A": "已用容量", "Value #B": "总容量",
                        "Value #C": "使用率 (%)",
                    },
                },
            },
        ],
        description="分别显示各内存池的已用容量、总容量和使用率。",
    )
    memory_detail_table["fieldConfig"]["overrides"].extend([
        {
            "matcher": {"id": "byName", "options": "已用容量"},
            "properties": [{"id": "unit", "value": "bytes"}],
        },
        {
            "matcher": {"id": "byName", "options": "总容量"},
            "properties": [{"id": "unit", "value": "bytes"}],
        },
        {
            "matcher": {"id": "byName", "options": "使用率 (%)"},
            "properties": [
                {"id": "unit", "value": "percent"},
                {"id": "min", "value": 0},
                {"id": "max", "value": 100},
                {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "gradient"}},
            ],
        },
    ])
    component_state_identity = (
        "tenant_id, asset_id, device_id, sensor_key, sensor_name, group, "
        "index, component_class"
    )
    component_state_join_labels = [
        "tenant_id", "asset_id", "device_id", "sensor_key", "sensor_name",
        "group", "index", "component_class",
    ]
    component_state_value_labels = f"{component_state_identity}, raw_state, state_description"
    component_presence_expr = (
        f"(max by ({component_state_value_labels}) ({component_present}) "
        f"or on({component_state_identity}) "
        f"(max by ({component_state_identity}) ({component_state}) * 0 - 1))"
    )
    presence_state_mappings = [{
        "type": "value",
        "options": {
            "0": {"text": "未安装", "color": CRITICAL_COLOR},
            "1": {"text": "已安装", "color": HEALTHY_COLOR},
            "-1": {"text": "无法判断", "color": NEUTRAL_COLOR},
        },
    }]
    component_state_table = table_panel(
        17,
        "风扇、电源与部件状态、原始值及存在性",
        component_state,
        0,
        46,
        16,
        8,
        targets=[
            {
                "expr": f"max by ({component_state_value_labels}) ({component_state})",
                "format": "table", "instant": True, "refId": "A",
            },
            {
                "expr": f"max by ({component_state_identity}, quality) ({component_state_quality})",
                "format": "table", "instant": True, "refId": "B",
            },
            {
                "expr": component_presence_expr,
                "format": "table", "instant": True, "refId": "C",
            },
        ],
        transformations=[
            {"id": "joinByLabels", "options": {"labels": component_state_join_labels}},
            {
                "id": "organize",
                "options": {
                    "excludeByName": {
                        "Time": True, "__name__": True, "tenant_id": True,
                        "device_id": True, "sensor_key": True, "source_type": True,
                        "source_id": True, "rule_version": True, "index": True,
                        "ent_physical_index": True, "measured_entity_type": True,
                        "measurement_type": True,
                        "hostname": True, "site_name": True, "vendor": True,
                        "platform": True, "role": True, "window": True,
                        "Value #B": True,
                    },
                    "indexByName": {
                        "asset_id": 0, "sensor_name": 1, "group": 2,
                        "component_class": 3, "raw_state": 4,
                        "state_description": 5, "Value #A": 6,
                        "quality": 7, "Value #C": 8,
                    },
                    "renameByName": {
                        "asset_id": "资产 ID", "sensor_name": "部件名称",
                        "group": "分组",
                        "component_class": "部件类别",
                        "raw_state": "原始状态", "state_description": "状态说明",
                        "Value #A": "规范状态", "quality": "采集质量",
                        "Value #C": "明确存在性",
                    },
                },
            },
        ],
        value_col_name="规范状态",
        value_mappings=state_mappings,
        extra_value_mappings={"明确存在性": presence_state_mappings},
        color_mapped_cells=True,
        description="未识别的状态显示原始值，不作健康判断。",
    )
    component_state_table["fieldConfig"]["overrides"].append({
        "matcher": {"id": "byName", "options": "明确存在性"},
        "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}}],
    })
    capability_selector = 'asset_id="$asset_id",asset_id!=""'
    capability_identity = "tenant_id, asset_id, device_id, source_type, component_class"
    capability_status_expr = (
        f"max by ({capability_identity}, status, coverage_complete) "
        f"(nexora_hw_capability_status{{{capability_selector}}})"
    )
    capability_active_expr = (
        f"max by ({capability_identity}) "
        f"(nexora_hw_capability_active_sensor_count{{{capability_selector}}})"
    )
    capability_discovered_expr = (
        f"max by ({capability_identity}) "
        f"(nexora_hw_capability_last_discovered_count{{{capability_selector}}})"
    )
    capability_info_expr = (
        f"max by ({capability_identity}, reason, reason_code) "
        f"(nexora_hw_capability_info{{{capability_selector}}})"
    )
    capability_success_age_expr = (
        f"(max by ({capability_identity}) "
        f"(time() - nexora_hw_capability_last_success_timestamp_seconds{{{capability_selector}}}) "
        f"or on({capability_identity}) "
        f"(max by ({capability_identity}) "
        f"(nexora_hw_capability_info{{{capability_selector}}}) * 0 - 1))"
    )
    capability_status_mappings = [{
        "type": "value",
        "options": {
            "success": {"text": "成功", "color": HEALTHY_COLOR},
            "partial": {"text": "部分成功", "color": WARNING_COLOR},
            "failed": {"text": "失败", "color": CRITICAL_COLOR},
            "unsupported": {"text": "不支持", "color": NEUTRAL_COLOR},
            "not_found": {"text": "未发现", "color": NEUTRAL_COLOR},
            "unknown": {"text": "未知", "color": NEUTRAL_COLOR},
        },
    }]
    capability_complete_mappings = [{
        "type": "value",
        "options": {
            "true": {"text": "完整", "color": HEALTHY_COLOR},
            "false": {"text": "不完整", "color": WARNING_COLOR},
        },
    }]
    capability_table = table_panel(
        20,
        "硬件发现能力与数量",
        capability_status_expr,
        0,
        54,
        24,
        8,
        targets=[
            {"expr": capability_status_expr, "format": "table", "instant": True, "refId": "A"},
            {"expr": capability_active_expr, "format": "table", "instant": True, "refId": "B"},
            {"expr": capability_discovered_expr, "format": "table", "instant": True, "refId": "C"},
            {"expr": capability_info_expr, "format": "table", "instant": True, "refId": "D"},
            {"expr": capability_success_age_expr, "format": "table", "instant": True, "refId": "E"},
        ],
        transformations=[
            {
                "id": "joinByLabels",
                "options": {"labels": [
                    "tenant_id", "asset_id", "device_id", "source_type", "component_class",
                ]},
            },
            {
                "id": "organize",
                "options": {
                    "excludeByName": {
                        "Time": True, "__name__": True, "tenant_id": True,
                        "device_id": True, "source_type": True,
                        "rule_version": True, "discovery_version": True,
                        "artifact_version": True,
                        "Value #A": True, "Value #D": True,
                    },
                    "indexByName": {
                        "asset_id": 0, "component_class": 1,
                        "status": 2, "coverage_complete": 3, "Value #B": 4,
                        "Value #C": 5, "reason_code": 6, "reason": 7,
                        "Value #E": 8,
                    },
                    "renameByName": {
                        "asset_id": "资产 ID", "component_class": "硬件类别",
                        "status": "发现状态",
                        "coverage_complete": "覆盖完整性",
                        "Value #B": "活动传感器数", "Value #C": "最近发现数",
                        "reason_code": "原因码", "reason": "原因说明",
                        "Value #E": "距最近成功（秒）",
                    },
                },
            },
        ],
        value_col_name="距最近成功（秒）",
        unit="s",
        extra_value_mappings={
            "发现状态": capability_status_mappings,
            "覆盖完整性": capability_complete_mappings,
            "距最近成功（秒）": [{
                "type": "value",
                "options": {"-1": {"text": "无成功记录", "color": NEUTRAL_COLOR}},
            }],
        },
        description="显示各类硬件的发现状态、数量和最近采集时间。",
    )
    capability_table["fieldConfig"]["overrides"].extend([
        {
            "matcher": {"id": "byName", "options": "发现状态"},
            "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}}],
        },
        {
            "matcher": {"id": "byName", "options": "覆盖完整性"},
            "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}}],
        },
        {
            "matcher": {"id": "byName", "options": "距最近成功（秒）"},
            "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}}],
        },
    ])
    panels = [
        identity_panel,
        stat_panel(
            2, "系统运行时长", f"sysUpTime{{{dev_sel}}} / 100", 0, 3, 4, 3,
            unit="dtdhms", color=NEUTRAL_COLOR, graph_mode="none",
        ),
        cpu_gauge,
        memory_gauge,
        temp_stat,
        stat_panel(
            6, "异常部件数", abnormal_count, 16, 3, 4, 3,
            unit="short", thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": CRITICAL_COLOR, "value": 1},
            ],
            description="无异常时显示 0；没有状态数据时显示 —。",
            graph_mode="none",
        ),
        stat_panel(
            7, "状态未知部件数", unknown_count, 20, 3, 4, 3,
            unit="short", color=NEUTRAL_COLOR,
            description="没有未知状态时显示 0；没有状态数据时显示 —。",
            graph_mode="none",
        ),
        timeseries_panel(
            8, "CPU 各部件使用率走势（最多10条）", [{
                "expr": f"topk(10, max by (tenant_id, asset_id, sensor_key, sensor_name, group, index, component_class, window) ({cpu}))",
                "legendFormat": "{{sensor_name}} · {{group}} · {{window}}",
                "refId": "A",
            }],
            0, 6, 9, 8, unit="percent",
            description=None,
        ),
        stat_panel(
            26, "超出10条的 CPU 部件数", cpu_overflow_count,
            9, 6, 3, 8,
            unit="short", thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": WARNING_COLOR, "value": 1},
            ], graph_mode="none",
            description=None,
        ),
        timeseries_panel(
            9, "各内存池使用率走势", [{
                "expr": f"max by (tenant_id, asset_id, sensor_key, sensor_name, group, index, component_class) ({memory})",
                "legendFormat": "{{sensor_name}} · {{group}}",
                "refId": "A",
            }],
            12, 6, 12, 8, unit="percent",
            description=None,
        ),
        timeseries_panel(
            10, "板卡与环境温度走势", [{
                "expr": f"max by (tenant_id, asset_id, sensor_key, sensor_name, group, index, component_class) ({temperature})",
                "legendFormat": "{{sensor_name}} · {{group}}",
                "refId": "A",
            }],
            0, 14, 12, 8, unit="celsius",
            description=None,
        ),
        timeseries_panel(
            11, "风扇转速走势", [{
                "expr": f"max by (tenant_id, asset_id, sensor_key, sensor_name, group, index, component_class) ({fan_speed})",
                "legendFormat": "{{sensor_name}} · {{group}}",
                "refId": "A",
            }],
            12, 14, 12, 8, unit="rpm",
            description=None,
        ),
        timeseries_panel(
            12, "电源功率读数走势", [{
                "expr": f"max by (tenant_id, asset_id, sensor_key, sensor_name, group, index, component_class) ({power})",
                "legendFormat": "{{sensor_name}} · {{group}}",
                "refId": "A",
            }],
            0, 22, 12, 8, unit="watt",
            description=None,
        ),
        timeseries_panel(
            27, "光模块收发功率走势（dBm）", [{
                "expr": f"max by (tenant_id, asset_id, sensor_key, sensor_name, group, index, component_class) ({optical_power})",
                "legendFormat": "{{sensor_name}} · {{group}}",
                "refId": "A",
            }],
            12, 22, 12, 8, unit="dBm",
            description=None,
        ),
        current_table(
            13, "CPU 部件当前读数", cpu, 0, 30,
            unit="percent", value_name="CPU 使用率",
            description=None,
        ),
        memory_detail_table,
        current_table(
            15, "温度传感器明细", temperature, 0, 38,
            unit="celsius", value_name="温度",
            description=None,
        ),
        current_table(
            16, "风扇转速当前读数", fan_speed, 12, 38,
            unit="rpm", value_name="转速",
            description=None,
        ),
        component_state_table,
        current_table(
            18, "电源功率当前读数", power, 16, 46, 8,
            unit="watt", value_name="功率",
            description="功率读数不代表电源状态。",
        ),
        capability_table,
        current_table(
            21, "传感器数据质量", quality, 0, 62, 8,
            value_name="质量值",
            description="显示设备返回的采集质量值，系统不解释未确认的代码。",
        ),
        current_table(
            22, "距最近一次成功采集", last_success_age, 8, 62, 8,
            unit="s", value_name="距上次成功",
            description=None,
        ),
        stat_panel(
            24, "全局硬件指标渲染错误数", "nexora_hw_sensor_render_errors",
            16, 62, 8, 8,
            unit="short", thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": CRITICAL_COLOR, "value": 1},
            ], graph_mode="none",
            description="这是全局 Grafana 硬件指标渲染错误数，不随当前设备筛选变化；0 表示当前无渲染错误。",
        ),
        table_panel(
            23, "设备端口实时状态清单",
            f"ifOperStatus{{{dev_sel}}} {dev_if_join}",
            0, 70, 12, 8,
            transformations=clean_organize_transformation(
                "运行状态", interface_description_label="ifAlias"
            ),
            value_col_name="运行状态",
            value_mappings=STATUS_VALUE_MAPPINGS,
            color_mapped_cells=True,
            mapped_cell_mode="color-background",
            detail_link=True,
            description=None,
        ),
        timeseries_panel(
            25, "设备接口流量走势", [
                {
                    "expr": f"sum by (asset_id, hostname, ifName) ({in_rate} * 8 {dev_if_join})",
                    "legendFormat": "{{hostname}} / {{ifName}} 入流量",
                    "refId": "A",
                },
                {
                    "expr": f"sum by (asset_id, hostname, ifName) ({out_rate} * 8 {dev_if_join})",
                    "legendFormat": "{{hostname}} / {{ifName}} 出流量",
                    "refId": "B",
                },
            ],
            12, 70, 12, 8, unit="bps",
            color_overrides=[
                timeseries_color_override("byRegexp", ".*入流量$", INBOUND_COLOR),
                timeseries_color_override("byRegexp", ".*出流量$", OUTBOUND_COLOR),
            ],
            description=None,
        ),
        current_table(
            28, "光模块功率当前读数（dBm）", optical_power, 0, 78, 12,
            unit="dBm", value_name="光功率",
            description=None,
        ),
        current_table(
            29, "其他 LibreNMS 传感器读数", generic_sensor, 12, 78, 12,
            value_name="当前值",
            description="单位尚未统一，数值按设备原始单位显示。",
        ),
    ]
    # Reserve one additional grid row for the identity table and move all
    # following panels down with it, preserving the dashboard's row spacing.
    for panel in panels[1:]:
        grid = panel.get("gridPos") or {}
        grid["y"] = int(grid.get("y", 0)) + 1
    panels = insert_section_rows(
        panels,
        [
            ("设备身份与健康摘要", 0),
            ("硬件部件趋势", 7),
            ("硬件部件当前读数", 31),
            ("发现状态与采集质量", 55),
            ("接口诊断", 71),
        ],
    )
    panels = normalize_summary_cards(panels)

    asset_query = (
        'query_result(label_join(max by (asset_id,hostname,instance,site_name) '
        '(up{job="network_snmp",asset_id!="",site_name=~"$site",vendor=~"$vendor",role=~"$role"}), '
        '"device_label", " · ", "hostname", "instance", "site_name"))'
    )
    variables = make_network_variables()[:3]
    variables.extend([
        make_query_variable(
            "asset_id",
            "设备",
            asset_query,
            multi=False,
            include_all=False,
            regex='/.*asset_id="(?<value>[^"]+)".*device_label="(?<text>[^"]+)".*/',
        ),
        make_query_variable(
            "cpu_window",
            "CPU 采样窗口",
            'label_values(nexora_hw_cpu_usage_percent{asset_id="$asset_id",asset_id!=""}, window)',
            multi=False,
            include_all=False,
        ),
        make_query_variable(
            "hardware_group",
            "部件分组",
            'label_values(nexora_hw_sensor_info{asset_id="$asset_id",asset_id!=""}, group)',
            multi=False,
            include_all=True,
        ),
        make_query_variable(
            "sensor_name",
            "部件",
            'label_values(nexora_hw_sensor_info{asset_id="$asset_id",asset_id!="",group=~"$hardware_group"}, sensor_name)',
            multi=True,
            include_all=True,
        ),
        make_query_variable(
            "component_class",
            "部件类别",
            'label_values(nexora_hw_sensor_info{asset_id="$asset_id",asset_id!="",group=~"$hardware_group",sensor_name=~"$sensor_name"}, component_class)',
            multi=False,
            include_all=True,
        ),
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
        "tags": ["nexora", "network", "device"],
        "templating": {
            "list": variables
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
    inventory_sel = f'{HARDWARE_INVENTORY_JOB},site_name=~"$site",vendor=~"$vendor",role=~"$role",hostname=~"$device"'
    huawei_inventory_sel = f'{inventory_sel},vendor=~"(?i).*huawei.*"'
    wireless_inventory_sel = f'{inventory_sel},vendor=~"(?i)(h3c|comware|huawei)"'
    # The wireless dashboard combines SNMP-exporter series and normalized
    # hardware-inventory series. Their job labels differ, so device identity
    # must not include `job` when de-duplicating or joining these sources.
    device_labels = WIRELESS_DEVICE_LABELS
    # Prefer the collected per-AP state rows for AP totals and status counts.
    # The controller-level online counters remain a fallback for platforms
    # that do not expose a complete AP state inventory.
    ap_state_selector = f'{inventory_sel},component_class="wireless_access_point"'
    ap_state_rows = f"nexora_hw_component_state{{{ap_state_selector}}}"
    ap_state_online_rows = f'nexora_hw_component_state{{{ap_state_selector},state_description=~"^(associated|run)$"}}'
    ap_state_offline_rows = f'nexora_hw_component_state{{{ap_state_selector},state_description=~"^(deassociated|idle)$"}}'
    ap_state_known_rows = f'nexora_hw_component_state{{{ap_state_selector},state_description=~"^(associated|run|deassociated|idle|downloading image)$"}}'
    ap_state_count = f"count by ({device_labels}) ({ap_state_rows})"
    ap_state_known_count = f"count by ({device_labels}) ({ap_state_known_rows})"
    ap_state_complete = (
        f'max by ({device_labels}) '
        f'(nexora_hw_capability_status{{{inventory_sel},component_class="wireless_access_point",coverage_complete="true"}})'
    )
    ap_state_detail_coverage = (
        f'(({ap_state_known_count}) == on({device_labels}) ({ap_state_count})) '
        f'and on({device_labels}) ({ap_state_complete})'
    )
    ap_state_online_count = f"count by ({device_labels}) ({ap_state_online_rows})"
    ap_state_offline_count = f"count by ({device_labels}) ({ap_state_offline_rows})"
    legacy_ap_online = f"sum by ({device_labels}) (hh3cDot11CurrOnlineAPNum{{{sel}}} or cLApTotalUpAPs{{{sel}}} or wlsxSysExtAccessPointsNum{{{sel}}} or ruckusZDTotalNumAP{{{sel}}})"
    inventory_ap_online = f'sum by ({device_labels}) (nexora_wireless_sensor_value{{{inventory_sel},component_class="wireless_controller",sensor_class="ap-count"}})'
    reported_ap_online = f"({legacy_ap_online} unless on({device_labels}) ({inventory_ap_online})) or on({device_labels}) ({inventory_ap_online})"
    ap_online_from_complete_details = (
        f"(({ap_state_online_count}) and on({device_labels}) ({ap_state_detail_coverage})) "
        f"or on({device_labels}) (({ap_state_detail_coverage}) * 0)"
    )
    ap_online = (
        f"({reported_ap_online} unless on({device_labels}) ({ap_state_detail_coverage})) "
        f"or on({device_labels}) ({ap_online_from_complete_details})"
    )
    ap_offline = (
        f"({ap_state_offline_count}) or on({device_labels}) "
        f"(({ap_state_detail_coverage}) * 0)"
    )
    clients = wireless_clients_by_device(sel, inventory_sel)
    missing_wireless_data_note = "暂无数据不代表数量为 0。"
    ap_total_description = f"统计已采到状态的 AP，不等于控制器配置总数。{missing_wireless_data_note}"
    ap_online_description = "优先按 AP 状态统计；明细不完整时采用控制器上报数。"
    ap_offline_description = "只统计明确离线的 AP，不用总数减在线数推算。"
    ap_client_rows = f'topk(20, nexora_wireless_sensor_value{{{inventory_sel},component_class="wireless_access_point",sensor_class="clients"}})'
    radio_utilization_labels = "site_name,vendor,role,hostname,ap_id,ap_name,radio_id"
    radio_utilization_samples = f'nexora_wireless_sensor_value{{{inventory_sel},component_class="wireless_radio",sensor_class="utilization"}}'
    radio_utilization_rows = f"max by ({radio_utilization_labels}) ({radio_utilization_samples})"
    high_utilization_radio_count = (
        f'count({radio_utilization_rows} >= 75) or on() '
        f'((count({radio_utilization_rows}) > 0) * 0)'
    )
    bss_client_rows = f'topk(20, nexora_wireless_sensor_value{{{wireless_inventory_sel},component_class="wireless_bss",sensor_class="clients"}})'
    huawei_ssid_rows = f'topk(20, sum by ({device_labels},ssid) (nexora_wireless_sensor_value{{{huawei_inventory_sel},component_class="wireless_ssid",sensor_class="clients"}}))'

    panels = [
        stat_panel(1, "采集 AP", f"sum({ap_state_count})", 0, 0, 4, 3, color=NEUTRAL_COLOR, description=ap_total_description, no_value=NO_VALUE_TEXT),
        stat_panel(2, "在线 AP", f"sum({ap_online})", 4, 0, 4, 3, color=HEALTHY_COLOR, description=ap_online_description, no_value=NO_VALUE_TEXT),
        stat_panel(3, "明确离线 AP", f"sum({ap_offline})", 8, 0, 4, 3, thresholds=OFFLINE_COUNT_THRESHOLDS, description=ap_offline_description, no_value=NO_VALUE_TEXT),
        stat_panel(4, "控制器汇总在线终端数", f"sum({clients})", 12, 0, 4, 3, color=NEUTRAL_COLOR, no_value=NO_VALUE_TEXT),
        stat_panel(5, "高利用率 Radio", high_utilization_radio_count, 16, 0, 4, 3, thresholds=OFFLINE_COUNT_THRESHOLDS, description="统计利用率达到 75% 的 Radio，仅用于定位热点。", no_value=NO_VALUE_TEXT),
        stat_panel(6, "平均 Radio 利用率", f"avg({radio_utilization_rows})", 20, 0, 4, 3, unit="percent", thresholds=UTILIZATION_THRESHOLDS, no_value=NO_VALUE_TEXT),
        row_panel(900, "趋势与 AP 状态", 3),
        timeseries_panel(7, "在线 AP 与关联终端趋势", [
            {"expr": f"sum({ap_online})", "legendFormat": "在线 AP", "refId": "A"},
            {"expr": f"sum({clients})", "legendFormat": "关联终端", "refId": "B"},
        ], 0, 4, 14, 7, unit="short", legend_display_mode="list", legend_placement="bottom", legend_calcs=[], color_overrides=[
            timeseries_color_override("byName", "在线 AP", HEALTHY_COLOR),
            timeseries_color_override("byName", "关联终端", CLIENT_COLOR),
        ]),
        bar_gauge_panel(
            8, "采集到的 AP 状态分布", f"count by (state_description) ({ap_state_rows})",
            14, 4, 10, 7, unit="short", legend_format="{{state_description}}", max_value=None,
            thresholds=[], color=NEUTRAL_COLOR, color_overrides=[
                timeseries_color_override("byName", "associated", HEALTHY_COLOR),
                timeseries_color_override("byName", "run", HEALTHY_COLOR),
                timeseries_color_override("byName", "active", HEALTHY_COLOR),
                timeseries_color_override("byName", "deassociated", CRITICAL_COLOR),
                timeseries_color_override("byName", "idle", CRITICAL_COLOR),
                timeseries_color_override("byName", "down", CRITICAL_COLOR),
                timeseries_color_override("byName", "join", WARNING_COLOR),
                timeseries_color_override("byName", "joining", WARNING_COLOR),
                timeseries_color_override("byName", "joinack", WARNING_COLOR),
                timeseries_color_override("byName", "config", WARNING_COLOR),
                timeseries_color_override("byName", "data check", WARNING_COLOR),
                timeseries_color_override("byName", "image load", WARNING_COLOR),
                timeseries_color_override("byName", "downloading image", WARNING_COLOR),
            ], instant=True,
            description=None,
        ),
        row_panel(901, "AP 明细", 11),
        table_panel(
            9, "AP 当前状态明细",
            ap_state_rows,
            0, 12, 14, 9, unit="short",
            transformations=clean_organize_transformation(
                "状态",
                extra_renames={"ap_name": "AP 名称", "ap_ip": "AP 管理 IP", "ap_model": "型号", "state_description": "状态说明"},
                extra_indices={"ap_name": 0, "state_description": 1, "ap_ip": 2, "hostname": 3, "vendor": 4, "ap_model": 5},
                extra_excludes={"Value": True, "source_type": True, "measurement_type": True, "component_class": True, "source_id": True, "sensor_key": True, "window": True, "raw_state": True, "device_id": True, "ap_id": True, "ap_mac": True, "ap_serial": True, "platform": True, "discovery_status": True, "lifecycle_status": True},
            ),
            extra_value_mappings={"状态说明": AP_STATE_VALUE_MAPPINGS},
            extra_color_mapped_cells={"状态说明": "color-background"},
            description=f"只显示已采到状态的 AP。{missing_wireless_data_note}",
        ),
        table_panel(
            10, "AP 当前关联客户端 Top 20",
            ap_client_rows,
            14, 12, 10, 9, unit="short",
            transformations=clean_organize_transformation(
                "客户端数",
                extra_renames={"ap_name": "AP 名称", "ap_ip": "AP 管理 IP", "ap_model": "型号"},
                extra_indices={"ap_name": 0, "hostname": 1, "vendor": 2, "ap_ip": 3, "ap_model": 4, "Value": 5},
                extra_excludes={"source_type": True, "measurement_type": True, "component_class": True, "source_id": True, "sensor_key": True, "window": True, "unit": True, "device_id": True, "ap_id": True, "ap_mac": True, "ap_serial": True, "platform": True, "discovery_status": True, "lifecycle_status": True},
            ),
            description=None,
        ),
        row_panel(902, "Radio 热点", 21),
        bar_gauge_panel(
            11, "Radio 利用率 Top 10", f"topk(10, {radio_utilization_rows})",
            0, 22, 24, 8, unit="percent", legend_format="{{hostname}} / {{ap_name}} / Radio {{radio_id}}",
            thresholds=UTILIZATION_THRESHOLDS, max_value=100, instant=True,
            description=None,
        ),
        row_panel(903, "SSID / BSS 客户端明细（依厂商采集覆盖）", 30),
        table_panel(
            12, "AP 无线单元（BSS）客户端 Top 20",
            bss_client_rows,
            0, 31, 12, 8, unit="short",
            transformations=clean_organize_transformation(
                "客户端数",
                extra_renames={"ap_name": "AP 名称", "radio_id": "Radio", "ssid": "SSID", "hostname": "设备名称", "wlan_id": "WLAN ID"},
                extra_excludes={"source_type": True, "measurement_type": True, "component_class": True, "source_id": True, "sensor_key": True, "window": True, "device_id": True, "ap_id": True, "ap_mac": True, "ap_serial": True, "platform": True, "unit": True},
            ),
            description="当前数据覆盖 H3C 与华为设备。",
        ),
        table_panel(
            13, "华为 SSID 客户端 Top 20",
            huawei_ssid_rows,
            12, 31, 12, 8, unit="short",
            transformations=clean_organize_transformation("客户端数", extra_renames={"ssid": "SSID"}),
            description=None,
        ),
    ]

    panels = insert_section_rows(panels, [("无线覆盖与终端概览", 0)])
    panels = normalize_summary_cards(panels)

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
        "time": {"from": "now-15m", "to": "now"},
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
    state_if_join = filtered_interface_join(if_filter, alias_selector=sel, fallback_status=False)
    admin_enabled = f'(ifAdminStatus{{{if_filter}}} == 1)'
    oper_up = f'(ifOperStatus{{{if_filter}}} == 1)'
    # Traffic panels include enabled interfaces that are currently operational.
    # Health and stability panels retain state_if_join so they can show DOWN states.
    if_join = (
        f"{state_if_join} and on(instance, ifIndex) {admin_enabled} "
        f"and on(instance, ifIndex) {oper_up}"
    )
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
    flap_24h = f"changes(ifOperStatus{{{if_filter}}}[24h]) {state_if_join} and on(instance, ifIndex) {admin_enabled}"
    flap_7d = f"changes(ifOperStatus{{{if_filter}}}[7d]) {state_if_join} and on(instance, ifIndex) {admin_enabled}"
    # IF-MIB TimeTicks and sysUpTime wrap at 2^32 centiseconds. Modulo keeps
    # the elapsed seconds non-negative across one wrap (sampling gaps still
    # limit the flap count resolution).
    last_change_age_raw = (
        f"(((sysUpTime{{{sel}}} - on(instance) group_right(ifIndex, ifName, ifAlias, interface_role, "
        f"utilization_warn_pct, utilization_high_pct, utilization_critical_pct) ifLastChange{{{if_filter}}}) "
        f"+ 4294967296) % 4294967296) / 100"
    )
    last_change_age = f"({last_change_age_raw}) and on(instance, ifIndex) {admin_enabled}"
    admin_status = f"ifAdminStatus{{{if_filter}}}"
    selected_admin_status = (
        f"(({admin_status} != 2) or on(instance, ifIndex) "
        f"(({admin_status} == 2) and on() (vector($show_admin_down) == 1)))"
    )
    status_admin_rows = f"({admin_status} and on(instance, ifIndex) {selected_admin_status}) {state_if_join}"
    status_oper_rows = (
        f"(ifOperStatus{{{if_filter}}} and on(instance, ifIndex) {selected_admin_status}) {state_if_join}"
    )
    rate_identity = "hostname, site_name, instance, ifIndex, ifName, ifAlias"
    in_rate_top10 = f"topk(10, max by ({rate_identity}) ({in_rate} {if_join}) * 8)"
    out_rate_top10 = f"topk(10, max by ({rate_identity}) ({out_rate} {if_join}) * 8)"

    panels = [
        row_panel(901, "实时流量与吞吐", 0),
        stat_panel(1, "接口入流量", f"sum({in_rate} {if_join}) * 8", 0, 1, 6, 3, unit="bps", color=INBOUND_COLOR),
        stat_panel(2, "接口出流量", f"sum({out_rate} {if_join}) * 8", 6, 1, 6, 3, unit="bps", color=OUTBOUND_COLOR),
        stat_panel(3, "错误包速率", f"sum({error_rate})", 12, 1, 6, 3, unit="pps", color=ERROR_COLOR),
        stat_panel(4, "丢弃包速率", f"sum({discard_rate})", 18, 1, 6, 3, unit="pps", color=DISCARD_COLOR),
        timeseries_panel(5, "接口流量趋势", [
            {"expr": f"sum by (hostname, site_name, ifName) ({in_rate} * 8 {if_join})", "legendFormat": "{{site_name}} / {{hostname}} / {{ifName}} 入向", "refId": "A"},
            {"expr": f"sum by (hostname, site_name, ifName) ({out_rate} * 8 {if_join})", "legendFormat": "{{site_name}} / {{hostname}} / {{ifName}} 出向", "refId": "B"},
        ], 0, 4, 24, 7, unit="bps", legend_display_mode="table", legend_placement="bottom",
            legend_calcs=["lastNotNull", "max"], color_overrides=[
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
                        "interface_role": INTERFACE_ROLE_LABEL, "utilization_warn_pct": "预警阈值 (%)",
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
        row_panel(905, "当前速率热点", 26),
        bar_gauge_panel(
            17, "近5分钟入向速率 Top10", in_rate_top10,
            0, 27, 12, 7, unit="bps",
            legend_format="{{site_name}} / {{hostname}} / {{ifName}}",
            thresholds=[], max_value=None, color=INBOUND_COLOR, instant=True,
            description=None,
        ),
        bar_gauge_panel(
            18, "近5分钟出向速率 Top10", out_rate_top10,
            12, 27, 12, 7, unit="bps",
            legend_format="{{site_name}} / {{hostname}} / {{ifName}}",
            thresholds=[], max_value=None, color=OUTBOUND_COLOR, instant=True,
            description=None,
        ),
        row_panel(903, "链路质量", 34),
        table_panel(
            9, "错误包 / 丢弃包百分比 Top20",
            f"topk(20, ({quality_rows}))",
            0, 35, 12, 7, unit="percent",
            transformations=[{
                "id": "organize", "options": {
                    "excludeByName": {"Time": True, "__name__": True, "ifIndex": True, "instance": True, "direction": True, "ifDescr": True},
                    "renameByName": {"quality_type": "质量指标", "ifName": "接口全称", "ifAlias": "接口描述", "hostname": "设备名称", "site_name": "站点", "vendor": "厂商", "role": "设备角色", "interface_role": INTERFACE_ROLE_LABEL, "utilization_warn_pct": "预警阈值 (%)", "utilization_high_pct": "高位阈值 (%)", "utilization_critical_pct": "严重阈值 (%)", "Value": "百分比 (%)"},
                },
            }],
            value_col_name="百分比 (%)", detail_link=True,
        ),
        timeseries_panel(10, "错误与丢弃包速率", [
            {"expr": f"sum by (hostname, site_name) ({error_rate})", "legendFormat": "{{site_name}} / {{hostname}} 错误 PPS", "refId": "A"},
            {"expr": f"sum by (hostname, site_name) ({discard_rate})", "legendFormat": "{{site_name}} / {{hostname}} 丢弃 PPS", "refId": "B"},
        ], 12, 35, 12, 7, unit="pps", color_overrides=[
            timeseries_color_override("byRegexp", ".*错误 PPS$", ERROR_COLOR),
            timeseries_color_override("byRegexp", ".*丢弃 PPS$", DISCARD_COLOR),
        ]),
        timeseries_panel(11, "入向 / 出向 / 单播 / 组播 / 广播 PPS", [
            {"expr": f"sum by (packet_type) ({packet_types})", "legendFormat": "{{packet_type}} PPS", "refId": "A"},
        ], 0, 42, 24, 7, unit="pps", color_overrides=[
            timeseries_color_override("byRegexp", "入向 PPS", INBOUND_COLOR),
            timeseries_color_override("byRegexp", "出向 PPS", OUTBOUND_COLOR),
            timeseries_color_override("byRegexp", "单播 PPS", PPS_COLOR),
            timeseries_color_override("byRegexp", "组播 PPS", MULTICAST_COLOR),
            timeseries_color_override("byRegexp", "广播 PPS", BROADCAST_COLOR),
        ]),
        row_panel(904, "状态与抖动", 49),
        table_panel(
            12, "接口 Flap 次数：24h / 7d",
            flap_24h,
            0, 50, 12, 7,
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
            12, 50, 12, 7, unit="s",
            transformations=clean_organize_transformation("距上次变化 (秒)", interface_description_label="ifAlias"),
            value_col_name="距上次变化 (秒)", detail_link=True,
        ),
        table_panel(
            14, "接口管理与运行状态",
            status_admin_rows,
            0, 57, 24, 7,
            targets=[
                {"expr": status_admin_rows, "format": "table", "instant": True, "refId": "A"},
                {"expr": status_oper_rows, "format": "table", "instant": True, "refId": "B"},
            ],
            transformations=[{
                "id": "joinByLabels",
                "options": {"labels": [
                    "instance", "hostname", "site_name", "vendor", "role", "ifIndex", "ifName", "ifAlias",
                    "interface_role", "utilization_warn_pct", "utilization_high_pct", "utilization_critical_pct",
                ]},
            }] + clean_organize_transformation(
                "运行状态",
                extra_renames={"Value #A": "管理状态", "Value #B": "运行状态"},
                extra_indices={"Value #A": 11, "Value #B": 12},
                interface_description_label="ifAlias",
            ),
            value_col_name="运行状态", value_mappings=STATUS_VALUE_MAPPINGS,
            color_mapped_cells=True, mapped_cell_mode="color-background", detail_link=True,
            extra_value_mappings={"管理状态": ADMIN_STATUS_VALUE_MAPPINGS},
            description="仅将管理启用且运行 Down 的接口列为异常候选。",
        ),
    ]

    panels = normalize_summary_cards(panels)

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
            "list": make_interface_variables(include_admin_down_selector=True)
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "04 接口流量与健康（Interface Traffic & Health）",
        "description": "流量与利用率只统计管理状态启用且运行状态 UP 的接口。健康表默认隐藏管理停用接口，运行 DOWN 的接口作为异常候选；管理停用接口可通过“接口范围”切换显示。接口用途显示“用途待确认”表示 CMDB 尚未配置该端口的用途，不代表接口异常。",
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
            "0": {"text": "NORMAL", "color": HEALTHY_COLOR},
            "1": {"text": "WARNING", "color": WARNING_COLOR},
            "2": {"text": "HIGH", "color": HIGH_COLOR},
            "3": {"text": "CRITICAL", "color": CRITICAL_COLOR},
        },
    }]

    # These vendor OIDs share a confirmed dBm scale and an ifIndex/ifName
    # lookup. Keep Huawei's mixed µW/dBm encoding out of this normalized view;
    # its dedicated SNMP action converts that encoding before returning data.
    optical_labels = "instance, hostname, site_name, vendor, role, ifName"
    optical_sel = f'{base_sel},ifName=~"$interface",interface_role=~"$interface_role"'

    def optical_direction_query(metric_names: tuple[str, ...], invalid_values: dict[str, str]) -> str:
        # snmp_exporter emits raw invalid sentinels as numeric samples. Filter
        # each vendor metric before aggregation so a sentinel cannot win max()
        # or distort the dBm trend. Huawei stays excluded because its power
        # encoding is mixed and cannot share this normalized exporter view.
        expressions = []
        for metric_name in metric_names:
            selector = f'{metric_name}{{{optical_sel}}}'
            invalid = invalid_values.get(metric_name)
            if invalid is not None:
                selector = f'({selector} != {invalid})'
            expressions.append(f'max by ({optical_labels}) ({selector})')
        return " or ".join(expressions)

    optical_rx = optical_direction_query((
        "hh3cTransceiverCurRXPowerDbm",
        "ruijieFiberRXpowerDbm",
        "jnxDomCurrentRxLaserPowerDbm",
        "zteAnOpticalIfRxPwrCurrDbm",
    ), {
        "hh3cTransceiverCurRXPowerDbm": "21474836.47",
        "ruijieFiberRXpowerDbm": "-100",
        "jnxDomCurrentRxLaserPowerDbm": "0",
    })
    optical_tx = optical_direction_query((
        "hh3cTransceiverCurTXPowerDbm",
        "ruijieFiberTXpowerDbm",
        "jnxDomCurrentTxLaserOutputPowerDbm",
        "zteAnOpticalIfTxPwrCurrDbm",
    ), {
        "hh3cTransceiverCurTXPowerDbm": "21474836.47",
        "ruijieFiberTXpowerDbm": "-100",
        "jnxDomCurrentTxLaserOutputPowerDbm": "0",
    })
    optical_power = (
        f'label_replace(({optical_rx}), "direction", "接收", "", "") or '
        f'label_replace(({optical_tx}), "direction", "发送", "", "")'
    )

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
                    "excludeByName": {"Time": True, "__name__": True, "ifIndex": True, "instance": True, "direction": True, "ifDescr": True},
                    "renameByName": {"capacity_stat": "指标", "ifName": "接口全称", "ifAlias": "接口描述", "hostname": "设备名称", "site_name": "站点", "vendor": "厂商", "role": "设备角色", "interface_role": INTERFACE_ROLE_LABEL, "utilization_warn_pct": "预警阈值 (%)", "utilization_high_pct": "高位阈值 (%)", "utilization_critical_pct": "严重阈值 (%)", "Value": "利用率 (%)"},
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
        ], 0, 27, 12, 7, unit="pps", legend_display_mode="list", legend_placement="bottom", legend_calcs=[], color_overrides=[
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
        row_panel(904, "接口状态", 41),
        table_panel(
            11, "错误包 / 丢弃包百分比", quality, 0, 34, 12, 7, unit="percent",
            transformations=[{"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True, "instance": True, "ifIndex": True, "ifDescr": True}, "renameByName": {"quality_type": "质量指标", "ifName": "接口全称", "ifAlias": "接口描述", "hostname": "设备名称", "site_name": "站点", "Value": "百分比 (%)"}}}],
            value_col_name="百分比 (%)",
        ),
        table_panel(
            12, "接口 Flap 次数：24h / 7d", flap_24h, 12, 34, 12, 7,
            targets=[{"expr": flap_24h, "format": "table", "instant": True, "refId": "A"}, {"expr": flap_7d, "format": "table", "instant": True, "refId": "B"}],
            transformations=[{"id": "joinByLabels", "options": {"labels": ["instance", "hostname", "site_name", "ifIndex", "ifName", "ifAlias", "interface_role"]}}, {"id": "organize", "options": {"excludeByName": {"Time": True, "instance": True, "ifIndex": True, "ifDescr": True}, "renameByName": {"ifName": "接口全称", "ifAlias": "接口描述", "hostname": "设备名称", "site_name": "站点", "Value #A": "24h Flap", "Value #B": "7d Flap"}}}],
            value_col_name="24h Flap",
        ),
        table_panel(
            13, "距上次接口状态变化时间", last_change_age, 0, 42, 12, 7, unit="s",
            transformations=clean_organize_transformation("距上次变化 (秒)", interface_description_label="ifAlias"),
            value_col_name="距上次变化 (秒)",
        ),
        table_panel(
            14, "接口运行状态", f"ifOperStatus{{{sel}}} {join}", 12, 42, 12, 7,
            transformations=clean_organize_transformation("运行状态", interface_description_label="ifAlias"),
            value_col_name="运行状态", value_mappings=STATUS_VALUE_MAPPINGS, color_mapped_cells=True,
        ),
        row_panel(905, "CMDB 利用率阈值判断", 49),
        table_panel(
            16, "当前利用率状态（按接口配置阈值）", threshold_state, 0, 50, 24, 7,
            transformations=clean_organize_transformation("阈值状态", interface_description_label="ifAlias"),
            value_col_name="阈值状态", value_mappings=threshold_state_mappings,
            color_mapped_cells=True,
        ),
        row_panel(906, "光模块功率（SNMP DOM）", 57),
        table_panel(
            18, "当前接收 / 发送光功率", optical_power, 0, 58, 24, 7,
            unit="dBm", value_col_name="光功率 (dBm)",
            transformations=[{
                "id": "organize", "options": {
                    "excludeByName": {"Time": True, "__name__": True, "ifIndex": True, "instance": True, "role": True},
                    "indexByName": {"site_name": 0, "hostname": 1, "vendor": 2, "ifName": 3, "direction": 4, "Value": 5},
                    "renameByName": {"site_name": "站点", "hostname": "设备名称", "vendor": "厂商", "ifName": "接口", "direction": "方向", "Value": "光功率 (dBm)"},
                },
            }],
            description="显示实测光功率；告警阈值因模块而异。",
        ),
        timeseries_panel(19, "接收 / 发送光功率趋势", [
            {"expr": optical_rx, "legendFormat": "{{hostname}} / {{ifName}} 接收", "refId": "A"},
            {"expr": optical_tx, "legendFormat": "{{hostname}} / {{ifName}} 发送", "refId": "B"},
        ], 0, 65, 24, 8, unit="dBm", color_overrides=[
            timeseries_color_override("byRegexp", ".*接收$", INBOUND_COLOR),
            timeseries_color_override("byRegexp", ".*发送$", OUTBOUND_COLOR),
        ]),
    ]
    panels = normalize_summary_cards(panels)
    return {
        "annotations": {"list": []}, "editable": false, "fiscalYearStartMonth": 0,
        "graphTooltip": 1, "id": None, "links": [], "panels": panels,
        "refresh": "30s", "schemaVersion": 39,
        "tags": ["nexora", "network", "interface", "detail"],
        "templating": {"list": make_interface_variables(multi_device=False, include_all_device=False, include_all_interface=False, multi_interface=False, include_threshold_values=True)},
        "time": {"from": "now-24h", "to": "now"}, "timezone": "browser",
        "title": "09 接口详情（Interface Detail）",
        "description": "从网络总览或接口排行进入，链接会携带站点、设备、接口筛选和时间范围。“用途待确认”表示 CMDB 尚未配置该端口的用途，不代表接口异常。",
        "uid": "nexora-interface-detail", "version": DASHBOARD_VERSION,
    }

# 5. Monitoring Engine Health Dashboard
def build_health_dashboard():
    panels = [
        stat_panel(1, "SNMP 在线目标", f"count(count by (instance) (up{{{NETWORK_JOB}}} == 1)) or on() ((count(up{{{NETWORK_JOB}}}) > 0) * 0)", 0, 0, 6, 4),
        stat_panel(2, "SNMP 失败目标", f"count(count by (instance) (up{{{NETWORK_JOB}}} == 0)) or on() ((count(up{{{NETWORK_JOB}}}) > 0) * 0)", 6, 0, 6, 4, thresholds=[{"color": NEUTRAL_COLOR, "value": None}, {"color": CRITICAL_COLOR, "value": 1}]),
        stat_panel(3, "平均 SNMP 采集耗时", f"avg(scrape_duration_seconds{{{NETWORK_JOB}}})", 12, 0, 6, 4, unit="s"),
        stat_panel(4, "最大 SNMP 采集耗时", f"max(scrape_duration_seconds{{{NETWORK_JOB}}})", 18, 0, 6, 4, unit="s", thresholds=[{"color": NEUTRAL_COLOR, "value": None}, {"color": WARNING_COLOR, "value": 5}, {"color": CRITICAL_COLOR, "value": 15}]),
        timeseries_panel(5, "各设备 SNMP 采集耗时趋势 (秒)", [
            {"expr": f"scrape_duration_seconds{{{NETWORK_JOB}}}", "legendFormat": "{{site_name}} / {{hostname}}", "refId": "A"}
        ], 0, 4, 12, 8, unit="s", legend_display_mode="list", legend_calcs=[]),
        timeseries_panel(6, "抓取样本量趋势 (Samples Scraped)", [
            {"expr": f"scrape_samples_scraped{{{NETWORK_JOB}}}", "legendFormat": "{{site_name}} / {{hostname}}", "refId": "A"}
        ], 12, 4, 12, 8, unit="short", legend_display_mode="list", legend_calcs=[]),
        table_panel(
            7, "采集失败设备清单 (Target Scrape Failure)", f"up{{{NETWORK_JOB}}} == 0", 0, 12, 12, 8,
            transformations=clean_organize_transformation("探测状态")
        ),
        table_panel(
            8, "采集最慢目标排行 Top 10", f"topk(10, scrape_duration_seconds{{{NETWORK_JOB}}})", 12, 12, 12, 8, unit="s",
            value_col_name="采集耗时 (秒)",
            transformations=clean_organize_transformation("采集耗时 (秒)")
        )
    ]

    panels = insert_section_rows(panels, [
        ("SNMP 采集概览", 0),
        ("采集性能趋势", 4),
        ("异常目标定位", 12),
    ])
    panels = normalize_summary_cards(panels)

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
        stat_panel(1, "出口总入向实时带宽 (Inbound)", f"sum({in_rate} {if_join}) * 8", 0, 0, 4, 4, unit="bps", color=INBOUND_COLOR),
        stat_panel(2, "出口总出向实时带宽 (Outbound)", f"sum({out_rate} {if_join}) * 8", 4, 0, 4, 4, unit="bps", color=OUTBOUND_COLOR),
        stat_panel(3, "出口最高入向利用率", f"max({util_in} {if_join})", 8, 0, 4, 4, unit="percent", thresholds=UTILIZATION_THRESHOLDS),
        stat_panel(4, "出口最高出向利用率", f"max({util_out} {if_join})", 12, 0, 4, 4, unit="percent", thresholds=UTILIZATION_THRESHOLDS),
        stat_panel(5, "出口链路错误与丢弃总速率", f"sum({error_rate} + {discard_rate})", 16, 0, 4, 4, unit="pps", thresholds=[
            {"color": NEUTRAL_COLOR, "value": None}, {"color": WARNING_COLOR, "value": 10}, {"color": CRITICAL_COLOR, "value": 100}
        ]),
        stat_panel(6, "筛选接口数", f"count(count by (instance, ifIndex) (ifOperStatus{{{sel}}} {if_join})) or on() ((count(ifOperStatus{{{sel}}}) > 0) * 0)", 20, 0, 4, 4, unit="none"),
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
        ], 0, 20, 24, 8, unit="pps", legend_display_mode="list", legend_placement="bottom", legend_calcs=[], color_overrides=[
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

    panels = insert_section_rows(panels, [
        ("出口接口概览", 0),
        ("进出流量趋势", 4),
        ("端口利用率热点", 12),
        ("链路质量与异常排行", 20),
    ])
    panels = normalize_summary_cards(panels)

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
        stat_panel(1, "受纳管 Linux 主机数", f'count(count by (hostname) (up{{{srv_sel}}}))', 0, 0, 4, 4, unit="none"),
        stat_panel(2, "系统平均运行时长", f'avg(time() - node_boot_time_seconds{{{srv_sel}}})', 4, 0, 4, 4, unit="dtdhms", graph_mode="none"),
        stat_panel(3, "平均 CPU 使用率", f'avg(100 - (avg by (hostname) (rate(node_cpu_seconds_total{{{srv_sel},mode="idle"}}[5m])) * 100))', 8, 0, 4, 4, unit="percent", thresholds=[
            {"color": HEALTHY_COLOR, "value": None},
            {"color": WARNING_COLOR, "value": 70},
            {"color": CRITICAL_COLOR, "value": 85}
        ]),
        stat_panel(4, "平均物理内存利用率", f'avg((1 - (node_memory_MemAvailable_bytes{{{srv_sel}}} / node_memory_MemTotal_bytes{{{srv_sel}}})) * 100)', 12, 0, 4, 4, unit="percent", thresholds=[
            {"color": HEALTHY_COLOR, "value": None},
            {"color": WARNING_COLOR, "value": 80},
            {"color": CRITICAL_COLOR, "value": 90}
        ]),
        stat_panel(5, "TCP 活跃连接总数", f'sum(node_netstat_Tcp_CurrEstab{{{srv_sel}}})', 16, 0, 4, 4, unit="none"),
        stat_panel(6, "已打开文件句柄数", f'sum(node_filefd_allocated{{{srv_sel}}})', 20, 0, 4, 4, unit="short", thresholds=[
            {"color": NEUTRAL_COLOR, "value": None},
            {"color": WARNING_COLOR, "value": 20000},
            {"color": CRITICAL_COLOR, "value": 100000}
        ]),

        timeseries_panel(7, "CPU 各状态利用率走势 (%)", [
            {"expr": f'100 - (avg by (hostname) (rate(node_cpu_seconds_total{{{srv_sel},mode="idle"}}[5m])) * 100)', "legendFormat": "{{site_name}} / {{hostname}} 整机 CPU 利用率 (%)", "refId": "A"},
            {"expr": f'avg by (hostname) (rate(node_cpu_seconds_total{{{srv_sel},mode="user"}}[5m])) * 100', "legendFormat": "{{site_name}} / {{hostname}} 用户态 (user %)", "refId": "B"},
            {"expr": f'avg by (hostname) (rate(node_cpu_seconds_total{{{srv_sel},mode="system"}}[5m])) * 100', "legendFormat": "{{site_name}} / {{hostname}} 系统态 (system %)", "refId": "C"},
            {"expr": f'avg by (hostname) (rate(node_cpu_seconds_total{{{srv_sel},mode="iowait"}}[5m])) * 100', "legendFormat": "{{site_name}} / {{hostname}} I/O等待 (iowait %)", "refId": "D"}
        ], 0, 4, 12, 8, unit="percent", legend_display_mode="list", legend_placement="bottom", legend_calcs=[]),

        timeseries_panel(8, "物理内存与 Swap 分布走势", [
            {"expr": f'node_memory_MemTotal_bytes{{{srv_sel}}} - node_memory_MemAvailable_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 内存已用量", "refId": "A"},
            {"expr": f'node_memory_MemAvailable_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 可用物理内存", "refId": "B"},
            {"expr": f'node_memory_Cached_bytes{{{srv_sel}}} + node_memory_Buffers_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 缓冲与缓存 (Buffers+Cache)", "refId": "C"},
            {"expr": f'node_memory_SwapTotal_bytes{{{srv_sel}}} - node_memory_SwapFree_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} Swap 已用量", "refId": "D"},
            {"expr": f'node_memory_MemTotal_bytes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 物理内存总量 (Total)", "refId": "E"}
        ], 12, 4, 12, 8, unit="bytes", legend_display_mode="list", legend_placement="bottom", legend_calcs=[]),

        timeseries_panel(9, "系统平均负载走势 (Load1 / Load5 / Load15)", [
            {"expr": f'node_load1{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 1分钟负载 (Load1)", "refId": "A"},
            {"expr": f'node_load5{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 5分钟负载 (Load5)", "refId": "B"},
            {"expr": f'node_load15{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 15分钟负载 (Load15)", "refId": "C"},
            {"expr": f'count by (hostname) (node_cpu_seconds_total{{{srv_sel},mode="idle"}})', "legendFormat": "{{site_name}} / {{hostname}} 逻辑 CPU 核心数 (阈值参考)", "refId": "D"}
        ], 0, 12, 12, 8, unit="short", legend_display_mode="list", legend_placement="bottom", legend_calcs=[]),

        timeseries_panel(10, "磁盘读写吞吐速率 (Bytes/s)", [
            {"expr": f'sum by (hostname, device) (rate(node_disk_read_bytes_total{{{srv_sel},device!~"loop.*|ram.*"}}[5m]))', "legendFormat": "{{site_name}} / {{hostname}} - {{device}} 读吞吐", "refId": "A"},
            {"expr": f'sum by (hostname, device) (rate(node_disk_written_bytes_total{{{srv_sel},device!~"loop.*|ram.*"}}[5m]))', "legendFormat": "{{site_name}} / {{hostname}} - {{device}} 写吞吐", "refId": "B"}
        ], 12, 12, 12, 8, unit="Bps", legend_display_mode="list", legend_placement="bottom", legend_calcs=[]),

        table_panel(
            11, "主机磁盘空间利用率 Top 10",
            f'topk(10, max by (hostname, mountpoint) ((1 - (node_filesystem_avail_bytes{{{srv_sel},fstype!~"tmpfs|iso9660|squashfs",fstype!=""}} / node_filesystem_size_bytes{{{srv_sel}}})) * 100))',
            0, 20, 12, 8, unit="percent",
            value_col_name="磁盘使用率",
            transformations=clean_organize_transformation("磁盘使用率", {"mountpoint": "挂载点"})
        ),

        timeseries_panel(12, "服务器网卡流量走势 (bps)", [
            {"expr": f'sum by (hostname, device) (rate(node_network_receive_bytes_total{{{srv_sel},device!~"lo|docker.*|veth.*|br-.*"}}[5m]) * 8)', "legendFormat": "{{site_name}} / {{hostname}} - {{device}} 接收 (bps)", "refId": "A"},
            {"expr": f'sum by (hostname, device) (rate(node_network_transmit_bytes_total{{{srv_sel},device!~"lo|docker.*|veth.*|br-.*"}}[5m]) * 8)', "legendFormat": "{{site_name}} / {{hostname}} - {{device}} 发送 (bps)", "refId": "B"}
        ], 12, 20, 12, 8, unit="bps", legend_display_mode="list", legend_placement="bottom", legend_calcs=[], color_overrides=[
            timeseries_color_override("byRegexp", ".*接收.*", INBOUND_COLOR),
            timeseries_color_override("byRegexp", ".*发送.*", OUTBOUND_COLOR),
        ]),

        table_panel(
            13, "主机 TCP 活跃连接数 Top 10",
            f'topk(10, sum by (hostname) (node_netstat_Tcp_CurrEstab{{{srv_sel}}}))',
            0, 28, 12, 8, unit="none",
            transformations=clean_organize_transformation("活跃连接数")
        ),
        timeseries_panel(14, "系统进程调度与阻塞情况", [
            {"expr": f'node_procs_running{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 正在运行进程数", "refId": "A"},
            {"expr": f'node_procs_blocked{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 阻塞/等待I/O进程数", "refId": "B"}
        ], 12, 28, 12, 8, unit="short", legend_display_mode="list", legend_placement="bottom", legend_calcs=[])
    ]

    panels = insert_section_rows(panels, [
        ("Linux 主机概览", 0),
        ("CPU 与内存", 4),
        ("系统负载与磁盘 I/O", 12),
        ("磁盘空间、网络与会话", 20),
    ])
    panels = normalize_summary_cards(panels)

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
                make_query_variable(
                    "site", "站点",
                    'query_result(count by (site_name) (up{job="linux_servers"}))',
                    regex='/.*site_name="([^"]+)".*/',
                ),
                make_query_variable(
                    "device", "服务器",
                    'query_result(count by (hostname) (up{job="linux_servers",site_name=~"$site"}))',
                    regex='/.*hostname="([^"]+)".*/',
                ),
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
        stat_panel(1, "受纳管 Windows 主机数", f'count(count by (hostname) (up{{{srv_sel}}}))', 0, 0, 6, 4, unit="none"),
        stat_panel(2, "平均 CPU 使用率", f'avg(100 - (avg by (hostname) (rate(windows_cpu_time_total{{{srv_sel},mode="idle"}}[5m])) * 100))', 6, 0, 6, 4, unit="percent", thresholds=[
            {"color": HEALTHY_COLOR, "value": None},
            {"color": WARNING_COLOR, "value": 70},
            {"color": CRITICAL_COLOR, "value": 85}
        ]),
        stat_panel(3, "平均物理内存使用率", f'avg((1 - (windows_os_physical_memory_free_bytes{{{srv_sel}}} / windows_cs_physical_memory_bytes{{{srv_sel}}})) * 100)', 12, 0, 6, 4, unit="percent", thresholds=[
            {"color": HEALTHY_COLOR, "value": None},
            {"color": WARNING_COLOR, "value": 80},
            {"color": CRITICAL_COLOR, "value": 90}
        ]),
        stat_panel(4, "远程桌面活跃会话", f'sum(windows_terminal_services_active_sessions{{{srv_sel}}})', 18, 0, 6, 4, unit="none"),

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
            value_col_name="剩余空间 (%)",
            transformations=clean_organize_transformation("剩余空间 (%)", {"volume": "盘符"})
        ),
        timeseries_panel(8, "系统进程数与线程数", [
            {"expr": f'windows_system_processes{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 进程数", "refId": "A"},
            {"expr": f'windows_system_threads{{{srv_sel}}}', "legendFormat": "{{site_name}} / {{hostname}} 线程数", "refId": "B"}
        ], 12, 12, 12, 8, unit="short"),

        timeseries_panel(9, "网卡收发流量走势 (bps)", [
            {"expr": f'sum by (hostname, nic) (rate(windows_net_bytes_received_total{{{srv_sel}}}[5m]) * 8)', "legendFormat": "{{site_name}} / {{hostname}} - {{nic}} 接收", "refId": "A"},
            {"expr": f'sum by (hostname, nic) (rate(windows_net_bytes_sent_total{{{srv_sel}}}[5m]) * 8)', "legendFormat": "{{site_name}} / {{hostname}} - {{nic}} 发送", "refId": "B"}
        ], 0, 20, 12, 8, unit="bps", color_overrides=[
            timeseries_color_override("byRegexp", ".*接收.*", INBOUND_COLOR),
            timeseries_color_override("byRegexp", ".*发送.*", OUTBOUND_COLOR),
        ]),
        table_panel(
            10, "系统关键服务运行状态",
            f'windows_service_state{{{srv_sel},state="running"}} == 1',
            0, 28, 24, 8, unit="none",
            transformations=clean_organize_transformation("服务状态", {"name": "服务名"})
        ),
        table_panel(
            11, "非运行关键服务",
            f'windows_service_state{{{srv_sel},state!="running"}} == 1',
            12, 20, 12, 8, unit="none",
            transformations=clean_organize_transformation("服务状态", {"name": "服务名", "state": "服务状态"})
        )
    ]

    panels = insert_section_rows(panels, [
        ("Windows 主机概览", 0),
        ("CPU 与内存", 4),
        ("磁盘与系统进程", 12),
        ("网络与非运行关键服务", 20),
        ("关键服务运行清单", 28),
    ])
    panels = normalize_summary_cards(panels)

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
                make_query_variable(
                    "site", "站点",
                    'query_result(count by (site_name) (up{job="windows_servers"}))',
                    regex='/.*site_name="([^"]+)".*/',
                ),
                make_query_variable(
                    "device", "服务器",
                    'query_result(count by (hostname) (up{job="windows_servers",site_name=~"$site"}))',
                    regex='/.*hostname="([^"]+)".*/',
                ),
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "08 Windows 服务器监控 (Windows Server Metrics)",
        "uid": "nexora-windows-metrics",
        "version": DASHBOARD_VERSION
    }


# 10. Monitoring Platform Health Dashboard
def build_platform_health_dashboard():
    platform_selector = (
        'job=~"platform_api|platform_victoriametrics|platform_vmagent|'
        'platform_snmp_exporter|platform_grafana|platform_cadvisor"'
    )
    platform_up = f"up{{{platform_selector}}}"
    up_value_mappings = [
        {
            "type": "value",
            "options": {
                "1": {"text": "UP", "color": HEALTHY_COLOR},
                "0": {"text": "DOWN", "color": CRITICAL_COLOR},
            },
        },
        {
            "type": "special",
            "options": {
                "match": "null",
                "result": {"text": NO_VALUE_TEXT, "color": UNKNOWN_COLOR},
            },
        },
    ]
    panels = [
        stat_panel(
            1,
            "平台指标端点在线数",
            f"count({platform_up} == 1)",
            0,
            0,
            4,
            4,
            unit="none",
            description="统计可访问的监控端点，不代表容器数。",
        ),
        stat_panel(
            2,
            "平台指标端点失败数",
            f"count({platform_up} == 0)",
            4,
            0,
            4,
            4,
            unit="none",
            thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": CRITICAL_COLOR, "value": 1},
            ],
            description=None,
        ),
        stat_panel(
            3,
            "平台指标端点数",
            f"count({platform_up})",
            8,
            0,
            4,
            4,
            unit="none",
            description=None,
        ),
        stat_panel(
            4,
            "最大采集耗时",
            f"max(scrape_duration_seconds{{{platform_selector}}})",
            12,
            0,
            4,
            4,
            unit="s",
            thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": WARNING_COLOR, "value": 2},
                {"color": CRITICAL_COLOR, "value": 5},
            ],
        ),
        stat_panel(
            5,
            "监控数据库连接",
            "nexora_monitoring_database_available",
            16,
            0,
            4,
            4,
            unit="none",
            thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": CRITICAL_COLOR, "value": 0},
                {"color": HEALTHY_COLOR, "value": 1},
            ],
            description="1 表示连接与查询成功，0 表示失败。",
        ),
        stat_panel(
            6,
            "平均采集耗时",
            f"avg(scrape_duration_seconds{{{platform_selector}}})",
            20,
            0,
            4,
            4,
            unit="s",
        ),
        timeseries_panel(
            7,
            "平台指标端点状态趋势",
            [
                {
                    "expr": f"max by (job) ({platform_up})",
                    "legendFormat": "{{job}}",
                    "refId": "A",
                }
            ],
            0,
            4,
            12,
            8,
            unit="none",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=[],
            description="1 表示可达，0 表示不可达。",
            line_interpolation="stepAfter",
        ),
        timeseries_panel(
            8,
            "平台指标端点采集耗时趋势",
            [
                {
                    "expr": f"scrape_duration_seconds{{{platform_selector}}}",
                    "legendFormat": "{{job}}",
                    "refId": "A",
                }
            ],
            12,
            4,
            12,
            8,
            unit="s",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=[],
        ),
        table_panel(
            9,
            "平台指标端点状态",
            platform_up,
            0,
            12,
            24,
            8,
            value_col_name="状态",
            value_mappings=up_value_mappings,
            color_mapped_cells=True,
            mapped_cell_mode="color-background",
            transformations=[
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {"Time": True, "__name__": True},
                        "indexByName": {"job": 0, "instance": 1, "Value": 2},
                        "renameByName": {
                            "job": "采集作业",
                            "instance": "目标",
                            "Value": "状态",
                        },
                    },
                }
            ],
            description="只反映监控指标端点状态，不代表容器健康。",
        ),
        stat_panel(
            10,
            "vmagent Remote Write 积压",
            "sum(vmagent_remotewrite_pending_data_bytes)",
            0,
            20,
            4,
            4,
            unit="bytes",
            thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": WARNING_COLOR, "value": 104857600},
                {"color": CRITICAL_COLOR, "value": 1073741824},
            ],
            description="显示等待写入的数据量；无数据时状态未知。",
        ),
        stat_panel(
            11,
            "5m Remote Write 推送失败",
            "sum(increase(vmagent_remotewrite_push_failures_total[5m]))",
            4,
            20,
            4,
            4,
            unit="none",
            thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": CRITICAL_COLOR, "value": 1},
            ],
        ),
        stat_panel(
            12,
            "5m Remote Write 丢弃数据块",
            "sum(increase(vmagent_remotewrite_packets_dropped_total[5m]))",
            8,
            20,
            4,
            4,
            unit="none",
            thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": CRITICAL_COLOR, "value": 1},
            ],
        ),
        stat_panel(
            13,
            "VictoriaMetrics 存储可用空间",
            "sum(vm_free_disk_space_bytes)",
            12,
            20,
            4,
            4,
            unit="bytes",
            description=None,
        ),
        stat_panel(
            14,
            "VictoriaMetrics 已用数据量",
            "sum(vm_data_size_bytes)",
            16,
            20,
            4,
            4,
            unit="bytes",
            description="显示监控数据量，不代表磁盘使用率。",
        ),
        stat_panel(
            15,
            "VictoriaMetrics 只读状态（0可写，1只读）",
            "max(vm_storage_is_read_only)",
            20,
            20,
            4,
            4,
            unit="none",
            thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": CRITICAL_COLOR, "value": 1},
            ],
            description="0 表示可写，1 表示只读；无数据时状态未知。",
        ),
        timeseries_panel(
            16,
            "容器 CPU 使用率（单核 = 100%）",
            [{
                "expr": 'sum by (name) (rate(container_cpu_usage_seconds_total{name!=""}[5m])) * 100',
                "legendFormat": "{{name}}",
                "refId": "A",
            }],
            0,
            24,
            12,
            8,
            unit="percent",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=["lastNotNull", "max"],
            description=None,
        ),
        timeseries_panel(
            17,
            "容器内存工作集",
            [{
                "expr": 'sum by (name) (container_memory_working_set_bytes{name!=""})',
                "legendFormat": "{{name}}",
                "refId": "A",
            }],
            12,
            24,
            12,
            8,
            unit="bytes",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=["lastNotNull", "max"],
        ),
        timeseries_panel(
            18,
            "容器磁盘读写速率",
            [
                {
                    "expr": 'sum by (name) (rate(container_fs_reads_bytes_total{name!=""}[5m]))',
                    "legendFormat": "{{name}} read",
                    "refId": "A",
                },
                {
                    "expr": 'sum by (name) (rate(container_fs_writes_bytes_total{name!=""}[5m]))',
                    "legendFormat": "{{name}} write",
                    "refId": "B",
                },
            ],
            0,
            32,
            24,
            8,
            unit="Bps",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=["lastNotNull", "max"],
        ),
        stat_panel(
            19,
            "Docker 容器采集观测数",
            'count(count by (name) (container_last_seen{name!=""}))',
            0,
            40,
            4,
            4,
            unit="none",
            description="统计已观测到的容器，不代表容器健康。",
        ),
        table_panel(
            20,
            "Docker 容器采集观测清单",
            'max by (name) (container_last_seen{name!=""})',
            4,
            40,
            20,
            8,
            unit="dateTimeAsIso",
            value_col_name="最后观测时间",
            transformations=[
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {
                            "Time": True,
                            "__name__": True,
                            "id": True,
                            "instance": True,
                            "job": True,
                        },
                        "indexByName": {"name": 0, "Value": 1},
                        "renameByName": {
                            "name": "容器名称",
                            "Value": "最后观测时间",
                        },
                    },
                }
            ],
            description="最后观测时间不代表容器健康状态。",
        ),
    ]
    panels = insert_section_rows(panels, [
        ("监控端点概况", 0),
        ("采集端点趋势与异常", 4),
        ("存储与 Remote Write", 20),
        ("容器资源与观测", 40),
    ])
    panels = normalize_summary_cards(panels)
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
        "tags": ["nexora", "monitoring", "platform", "health"],
        "templating": {"list": []},
        "time": {"from": "now-1h", "to": "now"},
        "timezone": "browser",
        "title": "10 监控平台健康（Monitoring Platform Health）",
        "description": "覆盖平台服务可用性、remote-write 队列、VictoriaMetrics 存储和应用容器资源。数据库连接来自 API SELECT 1；Docker API 仅通过内网只读代理供 cAdvisor 获取容器元数据，cAdvisor 仅只读访问宿主 /sys cgroup，不挂载宿主根目录。",
        "uid": "nexora-platform-health",
        "version": DASHBOARD_VERSION,
    }


# 11. Internet Probe Quality Dashboard
def build_outbound_probe_quality_dashboard():
    samples_1h = 'nexora_outbound_probe_samples{window="1h"}'
    availability_1h = 'nexora_outbound_probe_availability_ratio{window="1h"}'
    latency_avg_1h = 'nexora_outbound_probe_latency_avg_ms_by_type{window="1h",probe_type="icmp_ping"}'
    latency_max_1h = 'nexora_outbound_probe_latency_max_ms_by_type{window="1h",probe_type="icmp_ping"}'
    samples_24h = 'nexora_outbound_probe_samples{window="24h"}'
    availability_24h = 'nexora_outbound_probe_availability_ratio{window="24h"}'
    latency_avg_24h = 'nexora_outbound_probe_latency_avg_ms_by_type{window="24h",probe_type="icmp_ping"}'
    latency_max_24h = 'nexora_outbound_probe_latency_max_ms_by_type{window="24h",probe_type="icmp_ping"}'
    panels = [
        stat_panel(
            1,
            "1h 拨测样本",
            samples_1h,
            0,
            0,
            6,
            4,
            unit="none",
        ),
        stat_panel(
            2,
            "1h 系统级拨测可用率",
            availability_1h,
            6,
            0,
            6,
            4,
            unit="percentunit",
        ),
        stat_panel(
            3,
            "1h ICMP 平均 RTT",
            latency_avg_1h,
            12,
            0,
            6,
            4,
            unit="ms",
        ),
        stat_panel(
            4,
            "1h ICMP 最大 RTT",
            latency_max_1h,
            18,
            0,
            6,
            4,
            unit="ms",
        ),
        stat_panel(
            5,
            "24h 拨测样本",
            samples_24h,
            0,
            4,
            6,
            4,
            unit="none",
        ),
        stat_panel(
            6,
            "24h 系统级拨测可用率",
            availability_24h,
            6,
            4,
            6,
            4,
            unit="percentunit",
        ),
        stat_panel(
            7,
            "24h ICMP 平均 RTT",
            latency_avg_24h,
            12,
            4,
            6,
            4,
            unit="ms",
        ),
        stat_panel(
            8,
            "24h ICMP 最大 RTT",
            latency_max_24h,
            18,
            4,
            6,
            4,
            unit="ms",
        ),
        timeseries_panel(
            9,
            "系统级拨测可用率趋势（滚动窗口）",
            [
                {
                    "expr": availability_1h,
                    "legendFormat": "1h 可用率",
                    "refId": "A",
                },
                {
                    "expr": availability_24h,
                    "legendFormat": "24h 可用率",
                    "refId": "B",
                },
            ],
            0,
            8,
            12,
            8,
            unit="percentunit",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=[],
        ),
        timeseries_panel(
            10,
            "ICMP RTT 趋势（滚动窗口）",
            [
                {
                    "expr": latency_avg_1h,
                    "legendFormat": "1h 平均 RTT",
                    "refId": "A",
                },
                {
                    "expr": latency_max_1h,
                    "legendFormat": "1h 最大 RTT",
                    "refId": "B",
                },
                {
                    "expr": latency_avg_24h,
                    "legendFormat": "24h 平均 RTT",
                    "refId": "C",
                },
                {
                    "expr": latency_max_24h,
                    "legendFormat": "24h 最大 RTT",
                    "refId": "D",
                },
            ],
            12,
            8,
            12,
            8,
            unit="ms",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=[],
        ),
        timeseries_panel(
            11,
            "各协议拨测成功率（24h）",
            [{
                "expr": 'nexora_outbound_probe_success_ratio_by_type{window="24h"}',
                "legendFormat": "{{probe_type}}",
                "refId": "A",
            }],
            0,
            16,
            12,
            8,
            unit="percentunit",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=["lastNotNull"],
            description=None,
        ),
        timeseries_panel(
            12,
            "各协议平均响应时间（24h）",
            [{
                "expr": 'nexora_outbound_probe_latency_avg_ms_by_type{window="24h"}',
                "legendFormat": "{{probe_type}}",
                "refId": "A",
            }],
            12,
            16,
            12,
            8,
            unit="ms",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=["lastNotNull", "max"],
            description="ICMP 为往返时延；其他协议为自身响应时间。",
        ),
        stat_panel(
            13,
            "24h ICMP 多回显丢包率",
            'nexora_outbound_probe_icmp_packet_loss_ratio{window="24h"}',
            0,
            24,
            6,
            4,
            unit="percentunit",
            description=None,
        ),
        stat_panel(
            14,
            "24h ICMP 包间时延变化",
            'nexora_outbound_probe_icmp_jitter_avg_ms{window="24h"}',
            6,
            24,
            6,
            4,
            unit="ms",
            description=None,
        ),
        stat_panel(
            15,
            "1h WAN 接口采集成功率",
            'nexora_wan_interface_collection_success_ratio{window="1h"}',
            12,
            24,
            6,
            4,
            unit="percentunit",
            description="仅统计已启用的 WAN 接口。",
        ),
        stat_panel(
            16,
            "24h WAN 接口 Oper UP 比例",
            'nexora_wan_interface_oper_up_ratio{window="24h"}',
            18,
            24,
            6,
            4,
            unit="percentunit",
            thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": CRITICAL_COLOR, "value": 0},
                {"color": WARNING_COLOR, "value": 0.95},
                {"color": HEALTHY_COLOR, "value": 0.99},
            ],
            description="只按采集成功样本计算，不代表端到端 SLA。",
        ),
        timeseries_panel(
            17,
            "当前 WAN 接口健康状态",
            [{
                "expr": 'nexora_wan_links_by_health_status',
                "legendFormat": "{{status}}",
                "refId": "A",
            }],
            0,
            28,
            12,
            8,
            unit="short",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=["lastNotNull"],
        ),
        timeseries_panel(
            18,
            "WAN 接口平均上下行流量（24h 滚动）",
            [
                {
                    "expr": 'nexora_wan_interface_avg_download_bps{window="24h"}',
                    "legendFormat": "下行",
                    "refId": "A",
                },
                {
                    "expr": 'nexora_wan_interface_avg_upload_bps{window="24h"}',
                    "legendFormat": "上行",
                    "refId": "B",
                },
            ],
            12,
            28,
            12,
            8,
            unit="bps",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=["lastNotNull", "max"],
            color_overrides=[
                timeseries_color_override("byName", "下行", INBOUND_COLOR),
                timeseries_color_override("byName", "上行", OUTBOUND_COLOR),
            ],
            description="显示启用接口的平均速率，不是线路总流量。",
        ),
        timeseries_panel(
            19,
            "WAN 接口错误与丢弃（24h 累计）",
            [
                {
                    "expr": 'nexora_wan_interface_errors_total{window="24h"}',
                    "legendFormat": "错误",
                    "refId": "A",
                },
                {
                    "expr": 'nexora_wan_interface_discards_total{window="24h"}',
                    "legendFormat": "丢弃",
                    "refId": "B",
                },
            ],
            0,
            36,
            24,
            8,
            unit="short",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=["lastNotNull"],
            color_overrides=[
                timeseries_color_override("byName", "错误", ERROR_COLOR),
                timeseries_color_override("byName", "丢弃", DISCARD_COLOR),
            ],
        ),
        stat_panel(
            20,
            "当前连续 DOWN 的 WAN 接口",
            "nexora_wan_interface_active_down_links",
            0,
            44,
            6,
            4,
            unit="none",
            thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": CRITICAL_COLOR, "value": 1},
            ],
            description="仅统计采集正常、管理启用且运行 Down 的线路。",
        ),
        stat_panel(
            21,
            "连续 DOWN 时长估算（最长）",
            "nexora_wan_interface_continuous_down_estimate_max_seconds",
            6,
            44,
            6,
            4,
            unit="s",
            description="按采样结果估算，实际故障起点可能不同。",
        ),
    ]

    for panel in panels:
        grid = panel.get("gridPos") or {}
        if panel.get("id") in {20, 21}:
            grid["y"] = 8
        elif int(grid.get("y", -1)) >= 8:
            grid["y"] = int(grid["y"]) + 4

    panels = insert_section_rows(panels, [
        ("1h / 24h 拨测概览", 0),
        ("当前 WAN 连续故障", 8),
        ("拨测质量趋势", 12),
        ("WAN 接口健康与流量", 28),
    ])
    panels = normalize_summary_cards(panels)
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
        "tags": ["nexora", "monitoring", "outbound", "probe"],
        "templating": {"list": []},
        "time": {"from": "now-24h", "to": "now"},
        "timezone": "browser",
        "title": "11 WAN 链路健康与拨测质量（WAN Health & Probe Quality）",
        "description": "分开展示 WAN 设备接口采样健康与全局出向 DNS/TCP/HTTP/ICMP 拨测质量。ICMP 使用多回显计算丢包和包间时延变化。探测执行仍未应用 wan_probe_bindings 的逐线路 source-IP 选路，因此接口侧可用率和全局探测结果不能合并解释为单线路端到端 SLA。指标只输出系统聚合值，不带租户、线路、目标或地址标识。",
        "uid": "nexora-outbound-probe-quality",
        "version": DASHBOARD_VERSION,
    }


# 12. Alert Operations & Notification Effectiveness Dashboard
def build_alert_operations_dashboard():
    open_thresholds = [
        {"color": NEUTRAL_COLOR, "value": None},
        {"color": WARNING_COLOR, "value": 1},
        {"color": CRITICAL_COLOR, "value": 5},
    ]
    completed_status_selector = 'nexora_alert_delivery_attempts_24h{status=~"succeeded|retrying|failed"}'
    completed_attempts_expr = f"sum({completed_status_selector})"
    success_rate_expr = (
        f'(((sum(nexora_alert_delivery_attempts_24h{{status="succeeded"}}) / {completed_attempts_expr}) '
        f'and ({completed_attempts_expr} > 0)) or '
        f'(vector(-1) and on() (count({completed_status_selector}) > 0)))'
    )
    panels = [
        stat_panel(
            1,
            "当前打开告警",
            "sum(nexora_alert_open_events)",
            0,
            0,
            4,
            4,
            unit="none",
            thresholds=open_thresholds,
        ),
        stat_panel(
            2,
            "严重 未关闭",
            'nexora_alert_open_events{severity="critical"}',
            4,
            0,
            4,
            4,
            unit="none",
            thresholds=alert_severity_thresholds("critical"),
        ),
        stat_panel(
            3,
            "主要 未关闭",
            'nexora_alert_open_events{severity="major"}',
            8,
            0,
            4,
            4,
            unit="none",
            thresholds=alert_severity_thresholds("major"),
        ),
        stat_panel(
            4,
            "警告 未关闭",
            'nexora_alert_open_events{severity="warning"}',
            12,
            0,
            4,
            4,
            unit="none",
            thresholds=alert_severity_thresholds("warning"),
        ),
        stat_panel(
            5,
            "次要 未关闭",
            'nexora_alert_open_events{severity="minor"}',
            16,
            0,
            4,
            4,
            unit="none",
            thresholds=alert_severity_thresholds("minor"),
        ),
        stat_panel(
            6,
            "24h 告警成功率",
            success_rate_expr,
            20,
            0,
            4,
            4,
            unit="percentunit",
            description="按已完成的通知尝试计算；无完成记录时显示无数据。",
            value_mappings=NO_COMPLETED_DELIVERY_VALUE_MAPPINGS,
        ),
        timeseries_panel(
            7,
            "近 24 小时告警生命周期",
            [
                {
                    "expr": "nexora_alert_events_created_24h",
                    "legendFormat": "新增告警",
                    "refId": "A",
                },
                {
                    "expr": "nexora_alert_events_acknowledged_24h",
                    "legendFormat": "已确认告警",
                    "refId": "B",
                },
                {
                    "expr": "nexora_alert_events_resolved_24h",
                    "legendFormat": "已恢复告警",
                    "refId": "C",
                },
            ],
            0,
            4,
            12,
            8,
            unit="short",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=[],
            description=None,
        ),
        timeseries_panel(
            8,
            "当前未恢复告警严重度分布",
            [
                {
                    "expr": f'sum(nexora_alert_open_events{{severity="{severity}"}})',
                    "legendFormat": label,
                    "refId": chr(ord("A") + index),
                }
                for index, (severity, label) in enumerate(ALERT_SEVERITY_LABELS)
            ],
            12,
            4,
            12,
            8,
            unit="short",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=[],
            color_overrides=[
                timeseries_color_override(
                    "byRegexp", ".*严重.*", ALERT_SEVERITY_COLORS["critical"]
                ),
                timeseries_color_override(
                    "byRegexp", ".*主要.*", ALERT_SEVERITY_COLORS["major"]
                ),
                timeseries_color_override(
                    "byRegexp", ".*警告.*", ALERT_SEVERITY_COLORS["warning"]
                ),
                timeseries_color_override(
                    "byRegexp", ".*次要.*", ALERT_SEVERITY_COLORS["minor"]
                ),
            ],
            description=None,
        ),
        timeseries_panel(
            9,
            "近 24 小时通知投递结果",
            [
                {
                    "expr": "sum by (channel, status) (nexora_alert_delivery_attempts_24h)",
                    "legendFormat": "{{channel}} / {{status}}",
                    "refId": "A",
                }
            ],
            0,
            12,
            12,
            8,
            unit="short",
            legend_display_mode="table",
            legend_placement="right",
            legend_calcs=["lastNotNull", "max"],
            description=None,
        ),
        timeseries_panel(
            10,
            "通知 Outbox 当前状态",
            [
                {
                    "expr": "sum by (status) (nexora_alert_outbox_items)",
                    "legendFormat": "{{status}}",
                    "refId": "A",
                }
            ],
            12,
            12,
            12,
            8,
            unit="short",
            legend_display_mode="table",
            legend_placement="right",
            legend_calcs=["lastNotNull", "max"],
            description=None,
        ),
        stat_panel(
            11,
            "当前最久未恢复时长",
            "nexora_alert_open_duration_oldest_seconds",
            0,
            20,
            4,
            4,
            unit="dtdhms",
            graph_mode="none",
            thresholds=[
                {"color": NEUTRAL_COLOR, "value": None},
                {"color": WARNING_COLOR, "value": 3600},
                {"color": CRITICAL_COLOR, "value": 86400},
            ],
        ),
        stat_panel(
            12,
            "未恢复告警时长 P95",
            "nexora_alert_open_duration_p95_seconds",
            4,
            20,
            4,
            4,
            unit="dtdhms",
            graph_mode="none",
        ),
        stat_panel(
            13,
            "24h MTTA",
            "nexora_alert_mtta_seconds_24h",
            8,
            20,
            4,
            4,
            unit="s",
            description="告警创建到首次确认的平均时间。",
        ),
        stat_panel(
            14,
            "24h MTTR",
            "nexora_alert_mttr_seconds_24h",
            12,
            20,
            4,
            4,
            unit="s",
            description="告警创建到恢复的平均时间。",
        ),
        stat_panel(
            15,
            "重复未恢复告警",
            "nexora_alert_duplicate_open_events",
            16,
            20,
            4,
            4,
            unit="none",
            thresholds=open_thresholds,
            description="相同告警未恢复时，重复记录超出 1 条的数量。",
        ),
        stat_panel(
            16,
            "24h 重试通知数",
            "nexora_alert_retried_deliveries_24h",
            20,
            20,
            4,
            4,
            unit="none",
        ),
        timeseries_panel(
            17,
            "告警处置时长趋势（24h 滚动均值 / P95）",
            [
                {"expr": "nexora_alert_mtta_seconds_24h", "legendFormat": "MTTA 均值", "refId": "A"},
                {"expr": "nexora_alert_mtta_p95_seconds_24h", "legendFormat": "MTTA P95", "refId": "B"},
                {"expr": "nexora_alert_mttr_seconds_24h", "legendFormat": "MTTR 均值", "refId": "C"},
                {"expr": "nexora_alert_mttr_p95_seconds_24h", "legendFormat": "MTTR P95", "refId": "D"},
            ],
            0,
            24,
            12,
            8,
            unit="s",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=["lastNotNull", "max"],
        ),
        timeseries_panel(
            18,
            "未恢复告警持续时长（最久 / P95）",
            [
                {"expr": "nexora_alert_open_duration_oldest_seconds", "legendFormat": "最久未恢复", "refId": "A"},
                {"expr": "nexora_alert_open_duration_p95_seconds", "legendFormat": "未恢复时长 P95", "refId": "B"},
            ],
            12,
            24,
            12,
            8,
            unit="s",
            legend_display_mode="list",
            legend_placement="bottom",
            legend_calcs=["lastNotNull", "max"],
        ),
    ]
    panels = insert_section_rows(panels, [
        ("告警与通知概览", 0),
        ("告警生命周期与投递趋势", 4),
        ("告警处置效率", 20),
    ])
    panels = normalize_summary_cards(panels)

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
        "tags": ["nexora", "monitoring", "alerts", "notifications"],
        "templating": {"list": []},
        "time": {"from": "now-24h", "to": "now"},
        "timezone": "browser",
        "title": "12 告警处置与通知效果（Alert Operations & Notification Effectiveness）",
        "description": "展示系统级告警持续时长、MTTA、MTTR、相同 dedupe key 的并发重复事件，以及通知终态投递成功/失败和重试；不包含租户、设备、告警标题、目标地址或收件人信息。",
        "uid": "nexora-alert-operations",
        "version": DASHBOARD_VERSION,
    }


def iter_panels(panels):
    """Yield dashboard panels recursively, including any nested row panels."""
    for panel in panels or []:
        yield panel
        yield from iter_panels(panel.get("panels"))


def apply_v2_presentation(dashboards):
    """Apply the checked-in V2 field presentation without changing queries."""
    try:
        with PRESENTATION_CONFIG_PATH.open(encoding="utf-8") as source:
            presentation = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Unable to load V2 dashboard presentation config: {PRESENTATION_CONFIG_PATH}"
        ) from exc

    if presentation.get("schema_version") != 1 or presentation.get("skill_version") != "2.0.0":
        raise ValueError("Unsupported or missing V2 dashboard presentation schema/version")

    presentation_dashboards = presentation.get("dashboards")
    if not isinstance(presentation_dashboards, dict):
        raise ValueError("V2 dashboard presentation config must contain a dashboards map")

    catalog_by_uid = {data.get("uid"): (name, data) for name, data in dashboards}
    if set(catalog_by_uid) != set(presentation_dashboards):
        missing = sorted(set(catalog_by_uid) - set(presentation_dashboards))
        unknown = sorted(set(presentation_dashboards) - set(catalog_by_uid))
        raise ValueError(f"V2 dashboard UID mismatch; missing={missing}, unknown={unknown}")

    for uid, expected_dashboard in presentation_dashboards.items():
        source_name, dashboard = catalog_by_uid[uid]
        if dashboard.get("title") != expected_dashboard.get("title"):
            raise ValueError(f"{source_name}: V2 dashboard title mismatch for UID {uid}")

        actual_panels = {}
        for panel in iter_panels(dashboard.get("panels")):
            panel_id = str(panel.get("id"))
            if panel_id in actual_panels:
                raise ValueError(f"{source_name}: duplicate panel ID {panel_id}")
            actual_panels[panel_id] = panel

        expected_panels = expected_dashboard.get("panels")
        if not isinstance(expected_panels, dict) or set(actual_panels) != set(expected_panels):
            expected_ids = set(expected_panels or {})
            actual_ids = set(actual_panels)
            raise ValueError(
                f"{source_name}: V2 panel ID mismatch; "
                f"missing={sorted(expected_ids - actual_ids)}, "
                f"unknown={sorted(actual_ids - expected_ids)}"
            )

        for panel_id, expected_panel in expected_panels.items():
            panel = actual_panels[panel_id]
            if panel.get("title", "") != expected_panel.get("title", ""):
                raise ValueError(f"{source_name}: title mismatch for panel {panel_id}")
            if panel.get("type", "") != expected_panel.get("type", ""):
                raise ValueError(f"{source_name}: type mismatch for panel {panel_id}")
            if "fieldConfig" in expected_panel:
                panel["fieldConfig"] = deepcopy(expected_panel["fieldConfig"])
            else:
                panel.pop("fieldConfig", None)


def validate_dashboard(source_name, dashboard):
    """Validate the generated top-level dashboard contract before writing it."""
    uid = dashboard.get("uid")
    title = dashboard.get("title")
    assert isinstance(uid, str) and uid, f"{source_name}: missing uid"
    assert isinstance(title, str) and title, f"{source_name}: missing title"
    assert dashboard.get("version") == DASHBOARD_VERSION, f"{source_name}: stale version"

    panels = dashboard.get("panels") or []
    panel_ids = [panel.get("id") for panel in iter_panels(panels)]
    assert all(panel_id is not None for panel_id in panel_ids), f"{source_name}: panel without id"
    assert len(panel_ids) == len(set(panel_ids)), f"{source_name}: duplicate panel id"

    occupied = {}
    for panel in panels:
        grid = panel.get("gridPos") or {}
        try:
            x, y, width, height = (int(grid[key]) for key in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError) as exc:
            raise AssertionError(f"{source_name}: invalid grid for panel {panel.get('id')}") from exc
        assert 0 <= x < 24 and 0 < width <= 24 and x + width <= 24, (
            f"{source_name}: panel {panel.get('id')} outside grid width"
        )
        assert y >= 0 and height > 0, f"{source_name}: invalid grid height"
        for cell_y in range(y, y + height):
            for cell_x in range(x, x + width):
                previous = occupied.get((cell_x, cell_y))
                assert previous is None, (
                    f"{source_name}: panel {panel.get('id')} overlaps panel {previous}"
                )
                occupied[(cell_x, cell_y)] = panel.get("id")


def build_dashboard_catalog():
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
        ("nexora-platform-health.json", build_platform_health_dashboard()),
        ("nexora-outbound-probe-quality.json", build_outbound_probe_quality_dashboard()),
        ("nexora-alert-operations.json", build_alert_operations_dashboard()),
    ]
    assert len(dashboards) == 12, "dashboard catalog must contain exactly 12 dashboards"
    uids = [data.get("uid") for _, data in dashboards]
    assert len(uids) == len(set(uids)), "dashboard catalog contains duplicate UIDs"
    apply_v2_presentation(dashboards)
    return dashboards


def main():
    DASHBOARDS_DIR.mkdir(parents=True, exist_ok=True)
    dashboards = build_dashboard_catalog()
    for fname, data in dashboards:
        validate_dashboard(fname, data)
        path = DASHBOARDS_DIR / fname
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Generated {path}")

if __name__ == "__main__":
    main()
