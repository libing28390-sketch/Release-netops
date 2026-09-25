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
    assert "group_left(ifAlias) (ifAlias{" in port_status_query
    assert "ifDescr{" not in port_status_query
    assert organize["renameByName"]["ifName"] == "接口全称"
    assert organize["renameByName"]["ifAlias"] == "接口描述"
    assert organize["excludeByName"]["ifDescr"] is True

    for filename in (
        "nexora-network-device.json",
        "nexora-network-interface.json",
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
        assert all("group_left(ifAlias) (ifAlias{" in expr for expr in joined_expressions)
        assert all("or on(instance, ifIndex) (ifName{" in expr for expr in joined_expressions)
        assert all("ifDescr{" not in expr for expr in joined_expressions)
        assert all(
            "ifName=~" not in expr.split("group_left(ifAlias) (ifAlias{", 1)[1].split("}", 1)[0]
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
