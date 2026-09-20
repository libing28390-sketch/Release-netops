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
