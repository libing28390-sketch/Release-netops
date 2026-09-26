from backend.services.metric_provider import (
    ALLOWED_METRICS,
    CANONICAL_PROMQL,
    VictoriaMetricsMetricProvider,
)
from backend.services.monitoring_oid_catalog import BUILTIN_OID_CATALOG
import os
import json


def test_allowed_metrics_includes_wireless():
    assert "wireless_ap_online_count" in ALLOWED_METRICS
    assert "wireless_client_online_count" in ALLOWED_METRICS


def test_promql_selector_domestic_vendors():
    selector = VictoriaMetricsMetricProvider._selector("cpu_usage_percent", "device-123")
    assert "zteCpuRate" in selector
    assert "mpCpuUtilization5Min" in selector
    assert "dptechCpuUsage" in selector
    assert "hillstoneCPUUtilization" in selector
    assert "sangforCpuUsage" in selector
    assert "dcnCpuUsage" in selector

    mem_selector = VictoriaMetricsMetricProvider._selector("memory_usage_percent", "device-123")
    assert "zteMemRate" in mem_selector
    assert "mpMemoryUtilization" in mem_selector
    assert "dptechMemUsage" in mem_selector
    assert "hillstoneMemoryUtilization" in mem_selector
    assert "sangforMemUsage" in mem_selector
    assert "dcnMemUsage" in mem_selector


def test_promql_selector_wireless_metrics():
    ap_selector = VictoriaMetricsMetricProvider._selector("wireless_ap_online_count", "wlc-1")
    assert "hwWlanCurOnlineApNum" in ap_selector
    assert "hh3cDot11CurrOnlineAPNum" in ap_selector
    assert "ruijieApcOnlineApNum" in ap_selector
    assert "cLApTotalUpAPs" in ap_selector
    assert "wlsxSysExtAccessPointsNum" in ap_selector
    assert "ruckusZDTotalNumAP" in ap_selector

    client_selector = VictoriaMetricsMetricProvider._selector("wireless_client_online_count", "wlc-1")
    assert "hwWlanCurAssocUserNum" in client_selector
    assert "hh3cDot11CurrAssocUserNum" in client_selector
    assert "ruijieApcTotalStaNum" in client_selector
    assert "cLSysTotalNumOfClients" in client_selector
    assert "wlsxSysExtStationsNum" in client_selector
    assert "ruckusZDTotalNumSta" in client_selector


def test_oid_catalog_has_domestic_and_wireless():
    keys = {item["module_key"] for item in BUILTIN_OID_CATALOG}
    expected = {
        "zte_common", "maipu_common", "dptech_common",
        "hillstone_common", "sangfor_common", "dcn_common",
        "huawei_wireless", "h3c_wireless", "ruijie_wireless",
        "cisco_wireless", "aruba_wireless", "ruckus_wireless",
    }
    missing = expected - keys
    assert not missing, f"Missing expected modules in catalog: {missing}"


def test_dashboards_suite_completeness():
    dashboard_dir = os.path.join("monitoring", "grafana", "dashboards")
    expected_files = [
        "nexora-network-overview.json",
        "nexora-network-device.json",
        "nexora-network-wireless.json",
        "nexora-network-interface.json",
        "nexora-interface-detail.json",
        "nexora-monitoring-health.json",
        "nexora-network-outbound.json",
        "nexora-linux-metrics.json",
        "nexora-windows-metrics.json",
    ]
    for filename in expected_files:
        path = os.path.join(dashboard_dir, filename)
        assert os.path.exists(path), f"Dashboard file {filename} missing"
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert "uid" in data
            assert len(data.get("panels", [])) > 0

    device_dashboard_path = os.path.join(dashboard_dir, "nexora-network-device.json")
    with open(device_dashboard_path, "r", encoding="utf-8") as f:
        device_dashboard = json.load(f)
    port_status_panel = next(panel for panel in device_dashboard["panels"] if panel["id"] == 8)
    port_status_query = port_status_panel["targets"][0]["expr"]
    organize = next(
        transformation["options"]
        for transformation in port_status_panel["transformations"]
        if transformation.get("id") == "organize"
    )
    assert "group_left(ifName, ifAlias)" in port_status_query
    assert "group_left(ifAlias) (max by (instance, ifIndex, ifAlias) (ifAlias{" in port_status_query
    assert "ifDescr{" not in port_status_query
    assert organize["renameByName"]["ifName"] == "接口全称"
    assert organize["renameByName"]["ifAlias"] == "接口描述"
    assert organize["excludeByName"]["ifDescr"] is True

    overview_path = os.path.join(dashboard_dir, "nexora-network-overview.json")
    with open(overview_path, "r", encoding="utf-8") as f:
        overview_dashboard = json.load(f)
    interface_count_panel = next(panel for panel in overview_dashboard["panels"] if panel["id"] == 6)
    interface_count_query = interface_count_panel["targets"][0]["expr"]
    assert interface_count_panel["title"] == "启用但链路未连通接口数"
    assert 'ifAdminStatus{' in interface_count_query and "== 1" in interface_count_query
    assert 'ifOperStatus{' in interface_count_query and "== 2" in interface_count_query
    assert "!= 1" not in interface_count_query
    assert "不代表接口刚刚发生故障" in interface_count_panel["description"]
    interface_candidates_panel = next(panel for panel in overview_dashboard["panels"] if panel["id"] == 14)
    candidate_query = interface_candidates_panel["targets"][0]["expr"]
    assert interface_candidates_panel["title"] == "启用但链路未连通 Top20"
    assert 'ifAdminStatus{' in candidate_query and "== 1" in candidate_query
    assert 'ifOperStatus{' in candidate_query and "== 2" in candidate_query
    assert "不是近期故障事件列表" in interface_candidates_panel["description"]
    candidate_role_override = next(
        override
        for override in interface_candidates_panel["fieldConfig"]["overrides"]
        if override["matcher"].get("options") == "接口用途"
    )
    assert candidate_role_override["properties"][0]["value"][0]["options"]["unclassified"]["text"] == "用途待确认"
    wireless_client_panel = next(panel for panel in overview_dashboard["panels"] if panel["id"] == 4)
    assert "or vector(0)" not in wireless_client_panel["targets"][0]["expr"]
    assert "不代表当前客户端数为 0" in wireless_client_panel["description"]

    wireless_path = os.path.join(dashboard_dir, "nexora-network-wireless.json")
    with open(wireless_path, "r", encoding="utf-8") as f:
        wireless_dashboard = json.load(f)
    for panel_id in range(1, 5):
        panel = next(panel for panel in wireless_dashboard["panels"] if panel["id"] == panel_id)
        assert "or vector(0)" not in panel["targets"][0]["expr"]
        assert "不代表 AP 或客户端数量为 0" in panel["description"]

    interface_dashboard_path = os.path.join(dashboard_dir, "nexora-network-interface.json")
    with open(interface_dashboard_path, "r", encoding="utf-8") as f:
        interface_dashboard = json.load(f)
    utilization_panel = next(panel for panel in interface_dashboard["panels"] if panel["id"] == 6)
    role_override = next(
        override
        for override in utilization_panel["fieldConfig"]["overrides"]
        if override["matcher"].get("options") == "接口用途"
    )
    assert role_override["properties"][0]["value"][0]["options"]["unclassified"]["text"] == "用途待确认"

    for filename in (
        "nexora-network-device.json",
        "nexora-network-interface.json",
        "nexora-interface-detail.json",
        "nexora-network-outbound.json",
    ):
        with open(os.path.join(dashboard_dir, filename), "r", encoding="utf-8") as f:
            dashboard = json.load(f)
        joined_expressions = [
            target.get("expr", "")
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
            if "group_left(ifName, ifAlias)" in target.get("expr", "")
        ]
        assert joined_expressions
        assert all("group_left(ifAlias) (max by (instance, ifIndex, ifAlias) (ifAlias{" in expr for expr in joined_expressions)
        assert all("or on(instance, ifIndex) (max by (instance, ifIndex, ifName) (ifName{" in expr for expr in joined_expressions)
        assert all("ifDescr{" not in expr for expr in joined_expressions)
        assert all(
            "ifName=~" not in expr.split("group_left(ifAlias) (max by (instance, ifIndex, ifAlias) (ifAlias{", 1)[1].split("}", 1)[0]
            for expr in joined_expressions
        )

        for panel in dashboard["panels"]:
            if not any("group_left(ifName, ifAlias)" in target.get("expr", "") for target in panel.get("targets", [])):
                continue
            organize = next(
                (
                    transformation["options"]
                    for transformation in panel.get("transformations", [])
                    if transformation.get("id") == "organize"
                ),
                None,
            )
            if organize:
                assert organize["renameByName"].get("ifAlias") == "接口描述"
                assert organize["excludeByName"].get("ifDescr") is True


def test_dashboard_device_variables_use_current_up_targets():
    dashboard_dir = os.path.join("monitoring", "grafana", "dashboards")
    network_dashboards = (
        "nexora-network-overview.json",
        "nexora-network-device.json",
        "nexora-network-wireless.json",
        "nexora-network-interface.json",
        "nexora-interface-detail.json",
        "nexora-network-outbound.json",
    )
    network_variable_specs = {
        "site": ("site_name", '/.*site_name="([^\"]+)".*/'),
        "vendor": ("vendor", '/.*vendor="([^\"]+)".*/'),
        "role": ("role", '/.*role="([^\"]+)".*/'),
        "device": ("hostname", '/.*hostname="([^\"]+)".*/'),
    }

    for filename in network_dashboards:
        with open(os.path.join(dashboard_dir, filename), "r", encoding="utf-8") as dashboard_file:
            dashboard = json.load(dashboard_file)
        variables = {variable["name"]: variable for variable in dashboard["templating"]["list"]}
        for variable_name, (label, regex) in network_variable_specs.items():
            variable = variables[variable_name]
            query = variable["query"]["query"]
            assert variable["definition"] == query
            assert query.startswith(f"query_result(count by ({label}) (up{{job=\"network_snmp\"")
            assert variable["regex"] == regex
            assert "label_values(" not in query
            assert "== 1" not in query  # Keep configured targets selectable when SNMP is down.

    for filename, job in (
        ("nexora-linux-metrics.json", "linux_servers"),
        ("nexora-windows-metrics.json", "windows_servers"),
    ):
        with open(os.path.join(dashboard_dir, filename), "r", encoding="utf-8") as dashboard_file:
            dashboard = json.load(dashboard_file)
        variables = {variable["name"]: variable for variable in dashboard["templating"]["list"]}
        device_query = variables["device"]["query"]["query"]
        assert device_query.startswith(f"query_result(count by (hostname) (up{{job=\"{job}\"")
        assert variables["device"]["regex"] == '/.*hostname="([^\"]+)".*/'
        assert "label_values(" not in device_query
        assert "== 1" not in device_query
