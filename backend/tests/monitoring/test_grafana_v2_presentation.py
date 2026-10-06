"""Regression checks for the Grafana V2 presentation source and its final catalog."""

from __future__ import annotations

import json
import re

import pytest

from monitoring.grafana.generate_dashboards import (
    PRESENTATION_CONFIG_PATH,
    build_dashboard_catalog,
    iter_panels,
)


GREEN = "#22C55E"
BLUE = "#3B82F6"
CYAN = "#22D3EE"
AMBER = "#F59E0B"
ORANGE = "#F97316"
RED = "#F43F5E"
GRAY = "#64748B"
NO_DATA = "暂无采集数据"

EXPECTED_DASHBOARD_UIDS = {
    "nexora-network-overview",
    "nexora-network-device",
    "nexora-network-wireless",
    "nexora-network-interface",
    "nexora-monitoring-health",
    "nexora-network-outbound",
    "nexora-linux-metrics",
    "nexora-windows-metrics",
    "nexora-interface-detail",
    "nexora-platform-health",
    "nexora-outbound-probe-quality",
    "nexora-alert-operations",
}

IF_OPER_STATUS = {
    "1": ("Up", GREEN),
    "2": ("Down", RED),
    "3": ("Testing", BLUE),
    "4": ("Unknown", GRAY),
    "5": ("Dormant", BLUE),
    "6": ("Not present", BLUE),
    "7": ("Lower layer down", RED),
}


@pytest.fixture(scope="module")
def presentation_source():
    with PRESENTATION_CONFIG_PATH.open(encoding="utf-8") as source_file:
        return json.load(source_file)


@pytest.fixture(scope="module")
def catalog():
    # Build in memory so the assertions exercise the effective presentation
    # without depending on the generated dashboard files on disk.
    return {
        dashboard["uid"]: dashboard
        for _, dashboard in build_dashboard_catalog()
    }


def _panel(catalog, uid: str, panel_id: int):
    matches = [
        panel
        for panel in iter_panels(catalog[uid].get("panels", []))
        if panel.get("id") == panel_id
    ]
    assert len(matches) == 1, f"{uid}/{panel_id}: expected one panel"
    return matches[0]


def _panels_by_id(dashboard):
    panels = list(iter_panels(dashboard.get("panels", [])))
    return {str(panel["id"]): panel for panel in panels}


def _matching_overrides(panel, *, matcher_id: str, options: str):
    return [
        override
        for override in panel.get("fieldConfig", {}).get("overrides", [])
        if override.get("matcher", {}).get("id") == matcher_id
        and override.get("matcher", {}).get("options") == options
    ]


def _override(panel, field_name: str):
    matches = _matching_overrides(
        panel, matcher_id="byName", options=field_name
    )
    assert len(matches) == 1, (
        f"{panel.get('title')}: expected one byName override for {field_name!r}"
    )
    return matches[0]


def _property(override, property_id: str):
    matches = [
        item
        for item in override.get("properties", [])
        if item.get("id") == property_id
    ]
    assert len(matches) == 1, (
        f"{override.get('matcher')}: expected one {property_id!r} property"
    )
    return matches[0]["value"]


def _value_mapping(mappings):
    matches = [mapping for mapping in mappings if mapping.get("type") == "value"]
    assert len(matches) == 1, f"expected one exact-value mapping, got {matches}"
    return matches[0].get("options", {})


def _assert_gray_no_data_mappings(mappings):
    specials = {
        item.get("options", {}).get("match"): item.get("options", {}).get("result")
        for item in mappings
        if item.get("type") == "special"
    }
    for value in ("null", "nan"):
        assert specials.get(value) == {"text": NO_DATA, "color": GRAY}


def _assert_fixed_color(panel, matcher_id: str, options: str, expected: str):
    matches = _matching_overrides(panel, matcher_id=matcher_id, options=options)
    assert len(matches) == 1, (
        f"{panel.get('title')}: expected one {matcher_id} matcher for {options!r}"
    )
    color = _property(matches[0], "color")
    assert color == {"mode": "fixed", "fixedColor": expected}


def _mapping_and_cell_mode(panel, field_name: str):
    override = _override(panel, field_name)
    return (
        _property(override, "mappings"),
        _property(override, "custom.cellOptions"),
    )


def test_catalog_covers_the_complete_v2_dashboard_set(catalog):
    assert set(catalog) == EXPECTED_DASHBOARD_UIDS

    panels = [
        panel
        for dashboard in catalog.values()
        for panel in iter_panels(dashboard.get("panels", []))
    ]
    row_count = sum(panel.get("type") == "row" for panel in panels)
    stat_count = sum(panel.get("type") == "stat" for panel in panels)
    assert len(panels) == 257
    assert row_count == 54
    assert len(panels) - row_count == 203
    assert stat_count == 92


def test_generated_catalog_uses_every_effective_source_field_config(
    catalog, presentation_source
):
    configured_dashboards = presentation_source["dashboards"]
    assert set(configured_dashboards) == EXPECTED_DASHBOARD_UIDS

    for uid, configured_dashboard in configured_dashboards.items():
        generated_panels = _panels_by_id(catalog[uid])
        configured_panels = configured_dashboard["panels"]
        assert set(generated_panels) == set(configured_panels), uid

        for panel_id, configured_panel in configured_panels.items():
            panel = generated_panels[panel_id]
            assert panel.get("title", "") == configured_panel.get("title", "")
            assert panel.get("type", "") == configured_panel.get("type", "")
            if "fieldConfig" in configured_panel:
                assert panel.get("fieldConfig") == configured_panel["fieldConfig"], (
                    f"{uid}/{panel_id}: final fieldConfig differs from V2 source"
                )
            else:
                assert "fieldConfig" not in panel, f"{uid}/{panel_id}"


def test_all_stat_panels_render_null_and_nan_as_gray_no_data(catalog):
    stat_panels = [
        panel
        for dashboard in catalog.values()
        for panel in iter_panels(dashboard.get("panels", []))
        if panel.get("type") == "stat"
    ]
    assert len(stat_panels) == 92

    for panel in stat_panels:
        defaults = panel.get("fieldConfig", {}).get("defaults", {})
        assert defaults.get("noValue") == NO_DATA, panel.get("title")
        _assert_gray_no_data_mappings(defaults.get("mappings", []))


def test_if_mib_oper_status_uses_exact_rfc_state_colors(catalog):
    status_panels = (
        ("nexora-network-device", 23),
        ("nexora-network-interface", 14),
        ("nexora-interface-detail", 14),
    )
    for uid, panel_id in status_panels:
        panel = _panel(catalog, uid, panel_id)
        mappings, cell_options = _mapping_and_cell_mode(panel, "运行状态")
        values = _value_mapping(mappings)
        assert set(values) == set(IF_OPER_STATUS), f"{uid}/{panel_id}"
        assert {
            value: (entry.get("text"), entry.get("color"))
            for value, entry in values.items()
        } == IF_OPER_STATUS
        _assert_gray_no_data_mappings(mappings)
        assert cell_options == {"type": "color-text"}


def test_if_mib_admin_status_only_maps_defined_values(catalog):
    panel = _panel(catalog, "nexora-network-interface", 14)
    mappings, cell_options = _mapping_and_cell_mode(panel, "管理状态")
    values = _value_mapping(mappings)
    assert set(values) == {"1", "2", "3"}
    assert {
        key: (entry.get("text"), entry.get("color"))
        for key, entry in values.items()
    } == {
        "1": ("启用", BLUE),
        "2": ("停用", BLUE),
        "3": ("测试中", BLUE),
    }
    _assert_gray_no_data_mappings(mappings)
    assert cell_options == {"type": "color-text"}


def test_mapped_tables_use_text_colors_and_have_no_duplicate_matchers(catalog):
    table_panels = [
        panel
        for dashboard in catalog.values()
        for panel in iter_panels(dashboard.get("panels", []))
        if panel.get("type") == "table"
    ]
    assert table_panels

    for panel in table_panels:
        field_config = panel.get("fieldConfig", {})
        assert "color-background" not in json.dumps(field_config), panel.get("title")

        seen_matchers = set()
        seen_properties = set()
        for override in field_config.get("overrides", []):
            matcher_key = json.dumps(override.get("matcher", {}), sort_keys=True)
            assert matcher_key not in seen_matchers, (
                f"{panel.get('title')}: duplicate matcher {matcher_key}"
            )
            seen_matchers.add(matcher_key)

            for property_item in override.get("properties", []):
                property_key = (matcher_key, property_item.get("id"))
                assert property_key not in seen_properties, (
                    f"{panel.get('title')}: duplicate matcher property {property_key}"
                )
                seen_properties.add(property_key)


def test_cmdb_utilization_keeps_gradient_gauges_without_visual_alarm_bands(catalog):
    expected_colors = {
        ("nexora-network-interface", 6): BLUE,
        ("nexora-network-interface", 7): CYAN,
        ("nexora-network-interface", 8): BLUE,
        ("nexora-interface-detail", 8): BLUE,
    }
    for (uid, panel_id), expected_color in expected_colors.items():
        panel = _panel(catalog, uid, panel_id)
        utilization = _override(panel, "利用率 (%)")
        assert _property(utilization, "unit") == "percent"
        assert _property(utilization, "min") == 0
        assert _property(utilization, "max") == 100
        assert _property(utilization, "custom.cellOptions") == {
            "type": "gauge",
            "mode": "gradient",
        }
        assert _property(utilization, "color") == {
            "mode": "fixed",
            "fixedColor": expected_color,
        }
        thresholds = _property(utilization, "thresholds")
        assert thresholds.get("mode") == "absolute"
        assert thresholds.get("steps") == [{"color": expected_color, "value": None}]

        role_mapping = _property(_override(panel, "接口用途"), "mappings")
        assert _value_mapping(role_mapping).get("unclassified") == {
            "text": "用途待确认",
            "color": GRAY,
        }


def test_detail_cmdb_threshold_state_remains_the_authoritative_status(catalog):
    panel = _panel(catalog, "nexora-interface-detail", 16)
    mappings, cell_options = _mapping_and_cell_mode(panel, "阈值状态")
    assert _value_mapping(mappings) == {
        "0": {"text": "NORMAL", "color": GREEN},
        "1": {"text": "WARNING", "color": AMBER},
        "2": {"text": "HIGH", "color": ORANGE},
        "3": {"text": "CRITICAL", "color": RED},
    }
    assert cell_options == {"type": "color-text"}


@pytest.mark.parametrize(
    ("uid", "panel_id"),
    [
        ("nexora-network-interface", 9),
        ("nexora-interface-detail", 11),
    ],
)
def test_packet_quality_categories_and_zero_values_keep_semantic_colors(
    catalog, uid, panel_id
):
    panel = _panel(catalog, uid, panel_id)
    value_mapping = _property(_override(panel, "百分比 (%)"), "mappings")
    assert _value_mapping(value_mapping).get("0") == {"text": "0%", "color": GREEN}

    category_mappings, cell_options = _mapping_and_cell_mode(panel, "质量指标")
    assert _value_mapping(category_mappings) == {
        "错误包百分比": {"text": "错误包百分比", "color": AMBER},
        "丢弃包百分比": {"text": "丢弃包百分比", "color": RED},
    }
    assert cell_options == {"type": "color-text"}


def test_wan_health_uses_only_the_real_health_enum(catalog):
    panel = _panel(catalog, "nexora-outbound-probe-quality", 17)
    expected_colors = {
        "healthy": GREEN,
        "degraded": AMBER,
        "warning": AMBER,
        "critical": RED,
        "unavailable": RED,
        "unknown": GRAY,
    }
    overrides = panel.get("fieldConfig", {}).get("overrides", [])
    by_name = {
        item.get("matcher", {}).get("options"): _property(item, "color").get(
            "fixedColor"
        )
        for item in overrides
        if item.get("matcher", {}).get("id") == "byName"
    }
    assert by_name == expected_colors
    assert all(item.get("matcher", {}).get("id") == "byName" for item in overrides)
    assert panel["targets"][0].get("legendFormat") == "{{status}}"


def _matching_status_colors(panel, state: str):
    sample_series_name = f"test-channel / {state}"
    colors = []
    for override in panel.get("fieldConfig", {}).get("overrides", []):
        matcher = override.get("matcher", {})
        if matcher.get("id") != "byRegexp":
            continue
        try:
            matched = re.search(matcher.get("options", ""), sample_series_name) is not None
        except re.error as error:
            pytest.fail(f"invalid Grafana byRegexp matcher {matcher}: {error}")
        if matched:
            colors.append(_property(override, "color").get("fixedColor"))
    return colors


def test_alert_delivery_and_outbox_use_their_real_state_enums(catalog):
    delivery = _panel(catalog, "nexora-alert-operations", 9)
    expected_delivery_colors = {
        "queued": AMBER,
        "sending": AMBER,
        "succeeded": GREEN,
        "retrying": AMBER,
        "failed": RED,
        "skipped": BLUE,
        "unknown": GRAY,
    }
    delivery_overrides = delivery.get("fieldConfig", {}).get("overrides", [])
    delivery_patterns = [
        item.get("matcher", {}).get("options", "")
        for item in delivery_overrides
        if item.get("matcher", {}).get("id") == "byRegexp"
    ]
    assert not any(
        re.search(r"success|error", pattern, re.IGNORECASE)
        for pattern in delivery_patterns
    )
    for state, expected_color in expected_delivery_colors.items():
        assert _matching_status_colors(delivery, state) == [expected_color], state
    for invalid_state in ("success", "error", "up", "down"):
        assert _matching_status_colors(delivery, invalid_state) == [], invalid_state
    assert delivery["targets"][0].get("legendFormat") == "{{channel}} / {{status}}"

    outbox = _panel(catalog, "nexora-alert-operations", 10)
    expected_outbox_colors = {
        "pending": AMBER,
        "processing": AMBER,
        "succeeded": GREEN,
        "failed": RED,
        "unknown": GRAY,
    }
    outbox_overrides = outbox.get("fieldConfig", {}).get("overrides", [])
    by_name = {
        item.get("matcher", {}).get("options"): _property(item, "color").get(
            "fixedColor"
        )
        for item in outbox_overrides
        if item.get("matcher", {}).get("id") == "byName"
    }
    assert by_name == expected_outbox_colors
    assert all(item.get("matcher", {}).get("id") == "byName" for item in outbox_overrides)
    assert outbox["targets"][0].get("legendFormat") == "{{status}}"


@pytest.mark.parametrize(
    ("uid", "panel_id", "field_name"),
    [
        ("nexora-network-wireless", 9, "状态"),
        ("nexora-network-wireless", 10, "客户端数"),
        ("nexora-network-wireless", 12, "客户端数"),
        ("nexora-network-wireless", 13, "客户端数"),
        ("nexora-linux-metrics", 11, "磁盘使用率"),
        ("nexora-linux-metrics", 13, "活跃连接数"),
        ("nexora-windows-metrics", 7, "剩余空间 (%)"),
        ("nexora-windows-metrics", 10, "服务状态"),
        ("nexora-windows-metrics", 11, "服务状态"),
    ],
)
def test_by_name_matchers_follow_organized_value_field_names(
    catalog, uid, panel_id, field_name
):
    panel = _panel(catalog, uid, panel_id)
    organize_steps = [
        item
        for item in panel.get("transformations", [])
        if item.get("id") == "organize"
    ]
    assert len(organize_steps) == 1, f"{uid}/{panel_id}"
    rename_by_name = organize_steps[0].get("options", {}).get("renameByName", {})
    assert rename_by_name.get("Value") == field_name, f"{uid}/{panel_id}"

    matching = _matching_overrides(panel, matcher_id="byName", options=field_name)
    assert len(matching) == 1, f"{uid}/{panel_id}: {field_name}"
    assert not _matching_overrides(panel, matcher_id="byName", options="Value")


def _link_field_references(panel):
    references = []
    for override in panel.get("fieldConfig", {}).get("overrides", []):
        for property_item in override.get("properties", []):
            if property_item.get("id") != "links":
                continue
            for link in property_item.get("value", []):
                references.extend(
                    re.findall(r"\$\{__data\.fields\[\"([^\"]+)\"\]\}", link.get("url", ""))
                )
    return references


def _organize_options(panel):
    matches = [
        item
        for item in panel.get("transformations", [])
        if item.get("id") == "organize"
    ]
    return matches[0].get("options", {}) if matches else {}


def test_interface_flap_links_reference_fields_that_survive_organize(catalog):
    panel = _panel(catalog, "nexora-network-interface", 12)
    references = set(_link_field_references(panel))
    assert references == {
        "站点",
        "vendor",
        "role",
        "设备名称",
        "interface_role",
        "接口全称",
    }

    organize = _organize_options(panel)
    renamed_fields = organize.get("renameByName", {})
    excluded_fields = organize.get("excludeByName", {})
    assert {"站点", "设备名称", "接口全称"} <= set(renamed_fields.values())
    assert not {"vendor", "role", "interface_role"} & set(renamed_fields)
    assert not {"vendor", "role", "interface_role"} & {
        name for name, excluded in excluded_fields.items() if excluded
    }

    query_labels = set()
    for target in panel.get("targets", []):
        query_labels.update(
            re.findall(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*(?:=~|!~|!=|=)\s*\"", target.get("expr", ""))
        )
    assert {"site_name", "vendor", "role", "hostname", "interface_role", "ifName"} <= query_labels


@pytest.mark.parametrize(
    ("uid", "panel_id", "color"),
    [
        ("nexora-network-interface", 1, CYAN),
        ("nexora-network-interface", 2, BLUE),
        ("nexora-network-outbound", 1, CYAN),
        ("nexora-network-outbound", 2, BLUE),
        ("nexora-interface-detail", 1, CYAN),
        ("nexora-interface-detail", 2, BLUE),
    ],
)
def test_traffic_stat_direction_colors(catalog, uid, panel_id, color):
    panel = _panel(catalog, uid, panel_id)
    steps = panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
    assert steps[0]["color"] == color


@pytest.mark.parametrize(
    ("uid", "panel_id", "matcher_id", "matcher_options", "color"),
    [
        ("nexora-network-overview", 7, "byName", "入流量", CYAN),
        ("nexora-network-overview", 7, "byName", "出流量", BLUE),
        ("nexora-network-device", 25, "byRegexp", ".*入流量$", CYAN),
        ("nexora-network-device", 25, "byRegexp", ".*出流量$", BLUE),
        ("nexora-network-interface", 5, "byRegexp", ".*入向$", CYAN),
        ("nexora-network-interface", 5, "byRegexp", ".*出向$", BLUE),
        ("nexora-interface-detail", 7, "byName", "入向带宽", CYAN),
        ("nexora-interface-detail", 7, "byName", "出向带宽", BLUE),
        ("nexora-linux-metrics", 12, "byRegexp", ".*接收.*", CYAN),
        ("nexora-linux-metrics", 12, "byRegexp", ".*发送.*", BLUE),
        ("nexora-windows-metrics", 9, "byRegexp", ".*接收.*", CYAN),
        ("nexora-windows-metrics", 9, "byRegexp", ".*发送.*", BLUE),
    ],
)
def test_directional_traffic_series_keep_cyan_in_and_blue_out(
    catalog, uid, panel_id, matcher_id, matcher_options, color
):
    _assert_fixed_color(
        _panel(catalog, uid, panel_id), matcher_id, matcher_options, color
    )
