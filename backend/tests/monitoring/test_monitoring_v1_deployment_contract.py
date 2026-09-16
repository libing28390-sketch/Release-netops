from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_fixed_collector_stack_and_queue_contract():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert services["victoriametrics"]["image"] == "victoriametrics/victoria-metrics:v1.103.0"
    assert services["vmagent"]["image"] == "victoriametrics/vmagent:v1.103.0"
    assert services["snmp-exporter"]["image"] == "prom/snmp-exporter:v0.26.0"
    command = services["vmagent"]["command"]
    assert any("-remoteWrite.tmpDataPath=" in item for item in command)
    assert any("-remoteWrite.maxDiskUsagePerURL=" in item for item in command)
    assert any("nexora-vmagent-queue" in item for item in services["vmagent"]["volumes"])


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
    assert "ifHCInOctets" not in str(walk)  # OIDs are intentionally module-owned, not raw label text
