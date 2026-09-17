from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_fixed_collector_stack_and_queue_contract():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert services["victoriametrics"]["image"] == "victoriametrics/victoria-metrics:v1.103.0"
    assert services["vmagent"]["image"] == "victoriametrics/vmagent:v1.103.0"
    assert services["snmp-exporter"]["image"] == "prom/snmp-exporter:v0.26.0"
    assert services["grafana"]["image"] == "grafana/grafana:12.1.0"
    command = services["vmagent"]["command"]
    assert any("-remoteWrite.tmpDataPath=" in item for item in command)
    assert any("-remoteWrite.maxDiskUsagePerURL=" in item for item in command)
    assert any("nexora-vmagent-queue" in item for item in services["vmagent"]["volumes"])
    assert any("nexora-monitoring-artifacts:/app/artifacts/monitoring" in item for item in services["netops"]["volumes"])
    assert any("nexora-monitoring-artifacts:/etc/nexora-collector" in item for item in services["vmagent"]["volumes"])
    assert any("nexora-monitoring-artifacts:/etc/snmp_exporter" in item for item in services["snmp-exporter"]["volumes"])
    assert any("runtime/vmagent/scrape.yml" in item for item in command)
    assert any("runtime/snmp_exporter/snmp.yml" in item for item in services["snmp-exporter"]["command"])
    assert any("MONITORING_METRIC_BACKEND=${MONITORING_METRIC_BACKEND:-victoriametrics}" in item for item in services["netops"]["environment"])
    assert any("monitoring/grafana/provisioning" in item for item in services["grafana"]["volumes"])
    assert any("monitoring/grafana/dashboards" in item for item in services["grafana"]["volumes"])


def test_static_vmagent_and_generic_ifmib_contract():
    scrape = yaml.safe_load((ROOT / "monitoring" / "vmagent" / "scrape.yml").read_text(encoding="utf-8"))
    relabel = scrape["scrape_configs"][0]["relabel_configs"]
    labels = {item.get("target_label") for item in relabel}
    assert {"__param_target", "__param_module", "__param_auth", "__scrape_interval__", "__scrape_timeout__", "asset_id", "tenant_id"} <= labels
    assert any(item.get("action") == "labeldrop" and "nexora_auth" in item.get("regex", "") for item in relabel)

    exporter = yaml.safe_load((ROOT / "monitoring" / "snmp-exporter" / "snmp.yml").read_text(encoding="utf-8"))
    walk = exporter["modules"]["generic_ifmib_interface_std"]["walk"]
    assert "1.3.6.1.2.1.2.2" in walk
    assert "1.3.6.1.2.1.31.1.1" in walk
    assert "1.3.6.1.2.1.10.7.2.1" in walk
    assert "ifHCInOctets" not in str(walk)  # OIDs are intentionally module-owned, not raw label text
    generic_metrics = {item["name"] for item in exporter["modules"]["generic_ifmib_interface_std"]["metrics"]}
    assert {"ifHCInUcastPkts", "ifHCInMulticastPkts", "ifHCOutUcastPkts", "ifPhysAddress"} <= generic_metrics
    assert {"h3c_common_std", "huawei_common_std", "cisco_common_std"} <= set(exporter["modules"])
    assert all(exporter["modules"][key].get("metrics") for key in ("h3c_common_std", "huawei_common_std", "cisco_common_std"))
    h3c_metrics = {item["name"] for item in exporter["modules"]["h3c_common_std"]["metrics"]}
    assert {"hh3cDevMFanStatus", "hh3cDevMPowerStatus", "hh3cFlhPartSpace", "hh3cEntityExtMacAddressCount"} <= h3c_metrics
    h3c_metric_types = {item["name"]: item["type"] for item in exporter["modules"]["h3c_common_std"]["metrics"]}
    assert h3c_metric_types["hh3cEntityExtOperStatus"] == "EnumAsInfo"
    assert h3c_metric_types["hh3cEntityExtErrorStatus"] == "EnumAsInfo"
    h3c = exporter["modules"]["h3c_common_std"]
    assert {"1.3.6.1.4.1.25506.2.6.1.2.1.1", "1.3.6.1.4.1.25506.2.5.1.1.4.1.1", "1.3.6.1.4.1.25506.8.35.9.1.1.1", "1.3.6.1.4.1.25506.8.35.9.1.2.1"} <= set(h3c["walk"])
    assert h3c["retries"] == 3 and h3c["timeout"] == "5s"


def test_shared_runtime_path_is_used_by_the_compiled_scrape_config():
    scrape = yaml.safe_load((ROOT / "monitoring" / "vmagent" / "scrape.yml").read_text(encoding="utf-8"))
    snapshot_path = scrape["scrape_configs"][0]["file_sd_configs"][0]["files"][0]
    assert snapshot_path == "/etc/nexora-collector/runtime/vmagent/targets/snmp_targets.yml"
    assert (ROOT / "Dockerfile").read_text(encoding="utf-8").count("/app/artifacts/monitoring/runtime") >= 1
