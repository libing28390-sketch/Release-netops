"""Focused checks for generated Grafana query and presentation contracts."""

from __future__ import annotations

import re
from copy import deepcopy

import pytest

from monitoring.grafana.generate_dashboards import (
    DASHBOARD_VERSION,
    WIRELESS_DEVICE_LABELS,
    build_dashboard_catalog,
    iter_panels,
    validate_dashboard,
    validate_query_delimiters,
)


@pytest.fixture(scope="module")
def catalog():
    return {
        dashboard["uid"]: (filename, dashboard)
        for filename, dashboard in build_dashboard_catalog()
    }


def _panels_by_id(dashboard):
    return {
        panel["id"]: panel
        for panel in iter_panels(dashboard.get("panels", []))
    }


def test_all_generated_dashboards_validate_the_complete_panel_catalog(catalog):
    assert len(catalog) == 13

    panel_count = 0
    for filename, dashboard in catalog.values():
        panels = list(iter_panels(dashboard.get("panels", [])))
        panel_count += len(panels)
        validate_dashboard(filename, dashboard)

    assert panel_count == 271


@pytest.mark.parametrize(
    "query",
    [
        r'metric{label="right ) bracket ] brace } and quote: \" text", pattern=~"(?i)(edge|core)[(]"}',
        "sum(rate(metric[5m])) # ) ] } unmatched-looking comment\n + other_metric",
        r"metric{label=`literal ) ] }`}",
    ],
)
def test_delimiter_check_ignores_grouping_characters_inside_strings_regex_and_comments(
    query,
):
    validate_query_delimiters(query, "valid query")


@pytest.mark.parametrize(
    "query",
    [
        "sum(rate(metric[5m]))]",
        "sum(metric])",
        "sum(rate(metric[5m])",
        'metric{label="unterminated}',
    ],
)
def test_delimiter_check_rejects_unmatched_or_unclosed_grouping(query):
    with pytest.raises(ValueError, match="invalid query"):
        validate_query_delimiters(query, "invalid query")


def test_dashboard_validation_reports_the_bad_target_context():
    dashboard = {
        "uid": "invalid-dashboard",
        "title": "Invalid dashboard",
        "version": DASHBOARD_VERSION,
        "panels": [
            {
                "id": 41,
                "gridPos": {"x": 0, "y": 0, "w": 24, "h": 8},
                "targets": [{"expr": "sum(metric))", "refId": "A"}],
            }
        ],
    }

    with pytest.raises(ValueError, match=r"invalid\.json: panel 41/A"):
        validate_dashboard("invalid.json", dashboard)


def test_generator_validates_every_dashboard_before_writing_any_output(
    catalog, monkeypatch, tmp_path
):
    from monitoring.grafana import generate_dashboards

    valid_name, valid_dashboard = catalog["nexora-network-device"]
    invalid_name, invalid_dashboard = catalog["nexora-network-wireless"]
    invalid_dashboard = deepcopy(invalid_dashboard)
    bad_panel = _panels_by_id(invalid_dashboard)[4]
    bad_panel["targets"][0]["expr"] += ")"
    monkeypatch.setattr(generate_dashboards, "DASHBOARDS_DIR", tmp_path)
    monkeypatch.setattr(
        generate_dashboards, "build_dashboard_catalog",
        lambda: [(valid_name, valid_dashboard), (invalid_name, invalid_dashboard)],
    )

    with pytest.raises(ValueError, match=r"nexora-network-wireless\.json: panel 4/A"):
        generate_dashboards.main([])
    assert list(tmp_path.iterdir()) == []


def test_overview_and_wireless_share_the_client_query_without_zero_fallback(catalog):
    overview = _panels_by_id(catalog["nexora-network-overview"][1])
    wireless = _panels_by_id(catalog["nexora-network-wireless"][1])

    overview_query = overview[4]["targets"][0]["expr"]
    wireless_query = wireless[4]["targets"][0]["expr"]

    assert overview_query == wireless_query
    assert 'source_type=~"librenms_rule|librenms_mib_rule"' in overview_query
    assert 'component_class="wireless_controller",sensor_class="clients"' in overview_query
    assert 'component_class="wireless_ssid",sensor_class="clients"' in overview_query
    assert "or on(site_name,vendor,role,hostname)" in overview_query
    assert "unless on(site_name,vendor,role,hostname)" not in overview_query
    assert "vector(0)" not in overview_query


def test_platform_container_last_seen_uses_epoch_milliseconds_for_grafana(catalog):
    platform = _panels_by_id(catalog["nexora-platform-health"][1])
    panel = platform[20]

    assert panel["targets"][0]["expr"] == (
        'max by (name) (container_last_seen{name!=""}) * 1000'
    )
    timestamp_units = [
        prop["value"]
        for override in panel["fieldConfig"]["overrides"]
        for prop in override["properties"]
        if prop.get("id") == "unit"
    ]
    assert "dateTimeAsIso" in timestamp_units


def test_platform_scrape_failure_stat_shows_zero_without_masking_missing_samples(catalog):
    platform = _panels_by_id(catalog["nexora-platform-health"][1])
    query = platform[2]["targets"][0]["expr"]

    assert query == (
        'sum(up{job=~"platform_api|platform_victoriametrics|platform_vmagent|'
        'platform_snmp_exporter|platform_grafana|platform_cadvisor"} == bool 0)'
    )
    assert "vector(0)" not in query
    assert "无样本时仍显示暂无数据" in platform[2]["description"]


def test_postgres_performance_uses_verified_metrics_and_bounded_queryid_topk(catalog):
    dashboard = catalog["nexora-postgres-performance"][1]
    panels = _panels_by_id(dashboard)

    assert panels[1]["targets"][0]["expr"] == (
        'min(up{job="platform_postgres_exporter"})'
    )
    assert panels[2]["targets"][0]["expr"] == (
        'min(pg_scrape_collector_success{job="platform_postgres_exporter",'
        'collector="stat_statements"})'
    )
    expected_health_thresholds = [
        {"color": "#64748B", "value": None},
        {"color": "#F43F5E", "value": 0},
        {"color": "#22C55E", "value": 1},
    ]
    for panel_id in (1, 2):
        assert panels[panel_id]["fieldConfig"]["defaults"]["thresholds"]["steps"] == (
            expected_health_thresholds
        )
    assert "pg_stat_statements_calls_total" in panels[3]["targets"][0]["expr"]
    assert "pg_stat_statements_seconds_total" in panels[4]["targets"][0]["expr"]
    assert "pg_stat_statements_rows_total" in panels[6]["targets"][0]["expr"]
    cache_query = panels[7]["targets"][0]["expr"]
    assert "pg_stat_database_blks_hit" in cache_query
    assert "pg_stat_database_blks_read" in cache_query
    assert "单条 SQL" in panels[7]["description"]

    top_queries = [
        panels[10]["targets"][0]["expr"],
        panels[11]["targets"][0]["expr"],
    ]
    for query in top_queries:
        assert query.startswith("topk(10,")
        assert "sum by (datname, user, queryid)" in query
        assert "pg_stat_statements_query_id" not in query
        assert not re.search(r"(?<![A-Za-z0-9_])query\s*(?:=|=~|!=|!~)", query)

    reset_note = panels[12]["options"]["content"]
    assert "pg_stat_statements_reset()" in reset_note
    assert "无法显示具体重置时点" in reset_note


@pytest.mark.parametrize(
    ("panel_id", "metric"),
    [
        (9, "nexora_hw_cpu_usage_percent"),
        (10, "nexora_hw_memory_usage_percent"),
        (11, "nexora_hw_temperature_celsius"),
    ],
)
def test_overview_hardware_coverage_counts_native_samples_without_snmp_exporter_gate(
    catalog, panel_id, metric
):
    overview = _panels_by_id(catalog["nexora-network-overview"][1])
    query = overview[panel_id]["targets"][0]["expr"]

    assert query == (
        f'count(count by (asset_id) ({metric}'
        '{asset_id!="",site_name=~"$site",vendor=~"$vendor",'
        'role=~"$role",hostname=~"$device"}))'
    )
    assert 'up{job="network_snmp"' not in query
    assert "vector(0)" not in query


@pytest.mark.parametrize(
    ("panel_id", "component_class", "expected_vendor_matchers"),
    [(12, "wireless_bss", 1), (13, "wireless_ssid", 2)],
)
def test_wireless_ssid_and_bss_queries_use_only_the_selected_vendor(
    catalog, panel_id, component_class, expected_vendor_matchers
):
    wireless = _panels_by_id(catalog["nexora-network-wireless"][1])
    query = wireless[panel_id]["targets"][0]["expr"]

    assert f'component_class="{component_class}"' in query
    vendor_matchers = re.findall(r'\bvendor\s*=~\s*"([^"]+)"', query)
    assert vendor_matchers == ["$vendor"] * expected_vendor_matchers
    assert not re.search(r"huawei|h3c|comware", query, re.IGNORECASE)

    if panel_id == 13:
        bss_component = 'component_class="wireless_bss"'
        ssid_component = 'component_class="wireless_ssid"'
        identity_labels = f"{WIRELESS_DEVICE_LABELS},ssid"
        assert query.startswith("topk(20, ")
        assert ssid_component in query and bss_component in query
        assert query.index(ssid_component) < query.index(bss_component)
        assert 'ssid!=""' in query
        assert f"or on({identity_labels})" in query
        assert 'hwWlanCurAssocUserNum{' not in query
        assert 'hh3cDot11CurrAssocUserNum{' not in query


def test_device_hardware_trends_use_compact_legends_and_keep_sensor_query_scope(
    catalog,
):
    device = _panels_by_id(catalog["nexora-network-device"][1])
    expected_metrics = {
        8: "nexora_hw_cpu_usage_percent",
        9: "nexora_hw_memory_usage_percent",
        10: "nexora_hw_temperature_celsius",
        11: "nexora_hw_fan_speed_rpm",
        12: "nexora_hw_power_watts",
        27: "nexora_hw_optical_power_dbm",
    }
    assert 30 not in device
    assert 31 not in device

    for panel_id, metric in expected_metrics.items():
        panel = device[panel_id]
        assert panel["options"]["legend"] == {
            "displayMode": "list",
            "placement": "bottom",
            "showLegend": True,
            "calcs": [],
        }
        assert len(panel["targets"]) == 1
        target = panel["targets"][0]
        query = target["expr"]

        assert target["refId"] == "A"
        assert metric in query
        assert 'asset_id="$asset_id"' in query
        assert 'asset_id!=""' in query
        assert "group_left(sensor_name, group, index, component_class" in query
        assert "{{sensor_name}} · {{group}}" in target["legendFormat"]

        if panel_id == 8:
            assert query.startswith("topk(10, max by (")
            assert ", window) (" in query
            assert "{{window}}" in target["legendFormat"]
        else:
            assert query.startswith("max by (")


def test_uptime_and_if_last_change_queries_cover_the_900_second_system_scrape(catalog):
    device = _panels_by_id(catalog["nexora-network-device"][1])
    uptime_query = device[2]["targets"][0]["expr"]
    assert "last_over_time(sysUpTime{" in uptime_query
    assert "[20m])" in uptime_query
    assert "time() - timestamp(last_over_time(sysUpTime{" in uptime_query
    assert "* 100) / 100" in uptime_query

    for dashboard_name in ("nexora-network-interface", "nexora-interface-detail"):
        expressions = [
            target.get("expr", "")
            for panel in _panels_by_id(catalog[dashboard_name][1]).values()
            for target in panel.get("targets", [])
            if "sysUpTime" in target.get("expr", "")
        ]
        assert expressions, dashboard_name
        assert all(
            "last_over_time(sysUpTime{" in expr
            and "[20m])" in expr
            and "time() - timestamp(last_over_time(sysUpTime{" in expr
            for expr in expressions
        )
