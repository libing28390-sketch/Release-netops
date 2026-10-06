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
    exporter_command = " ".join(str(item) for item in services["snmp-exporter"]["command"])
    assert "runtime/snmp_exporter/snmp.yml" in exporter_command
    assert "current_version.json" not in exporter_command
    assert any("MONITORING_METRIC_BACKEND=${MONITORING_METRIC_BACKEND:-victoriametrics}" in item for item in services["netops"]["environment"])
    assert any("monitoring/grafana/provisioning" in item for item in services["grafana"]["volumes"])
    assert any("provisioning/datasources:/etc/grafana/provisioning/datasources" in item for item in services["grafana"]["volumes"])
    assert any("provisioning/dashboards:/etc/grafana/provisioning/dashboards" in item for item in services["grafana"]["volumes"])
    assert any("monitoring/grafana/dashboards" in item for item in services["grafana"]["volumes"])
    assert "GF_SERVER_SERVE_FROM_SUB_PATH=true" in services["grafana"]["environment"]
    assert "GF_AUTH_PROXY_ENABLE_LOGIN_TOKEN=false" in services["grafana"]["environment"]
    assert "HTTP_PROXY=" in services["grafana"]["environment"]
    assert "HTTPS_PROXY=" in services["grafana"]["environment"]
    assert "ALL_PROXY=" in services["grafana"]["environment"]
    assert "victoriametrics" in next(item for item in services["grafana"]["environment"] if item.startswith("NO_PROXY="))
    healthcheck = services["grafana"]["healthcheck"]
    assert "curl -fsS http://127.0.0.1:3000/api/health" in healthcheck["test"][1]
    assert healthcheck["start_period"] == "60s"


def test_vmagent_and_cadvisor_bypass_proxy_for_internal_targets():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    vmagent_environment = services["vmagent"]["environment"]
    cadvisor_environment = services["cadvisor"]["environment"]
    for environment in (vmagent_environment, cadvisor_environment):
        for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            assert f"{variable}=" in environment

    for variable, expected_hosts in (
        (
            "vmagent",
            {"netops", "victoriametrics", "snmp-exporter", "vmagent", "grafana", "cadvisor"},
        ),
        ("cadvisor", {"docker-socket-proxy"}),
    ):
        environment = services[variable]["environment"]
        for proxy_variable in ("NO_PROXY", "no_proxy"):
            entry = next(item for item in environment if item.startswith(f"{proxy_variable}="))
            hosts = set(entry.split("=", 1)[1].split(","))
            assert expected_hosts <= hosts

    cadvisor_command = " ".join(str(item) for item in services["cadvisor"]["command"])
    assert "accelerator" not in cadvisor_command
    docker_root_mount = next(
        item for item in services["cadvisor"]["volumes"]
        if isinstance(item, dict) and item.get("target") == "/var/lib/docker"
    )
    assert docker_root_mount["source"] == "${CADVISOR_DOCKER_ROOT_DIR:-/var/lib/docker}"
    assert docker_root_mount["read_only"] is True
    assert docker_root_mount["bind"]["create_host_path"] is False


def test_grafana_subpath_is_preserved_and_native_session_cookie_is_stripped():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    grafana_environment = compose["services"]["grafana"]["environment"]
    assert "GF_SERVER_SERVE_FROM_SUB_PATH=true" in grafana_environment
    assert "GF_AUTH_PROXY_ENABLE_LOGIN_TOKEN=false" in grafana_environment
    assert any(
        item.startswith("GF_SERVER_ROOT_URL=") and "/grafana/" in item
        for item in grafana_environment
    )

    nginx = (ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    https_server = nginx.split("server {\n    listen 443 ssl;", 1)[1].split("\n}", 1)[0]
    assert "http2 on;" in https_server

    upgrade_map = nginx.split("map $http_upgrade $grafana_connection_upgrade {", 1)[1].split("\n}", 1)[0]
    assert "default upgrade;" in upgrade_map
    assert "''      '';" in upgrade_map

    auth_location = nginx.split("location = /_grafana_auth {", 1)[1].split("\n    location", 1)[0]
    assert "internal;" in auth_location
    assert "proxy_http_version 1.1;" in auth_location
    assert 'proxy_set_header Connection              "";' in auth_location
    assert 'proxy_set_header Authorization       "Bearer $cookie_nexora_grafana_session";' in auth_location
    assert 'proxy_set_header Cookie              "";' in auth_location

    grafana_location = nginx.split("location ^~ /grafana/ {", 1)[1].split("\n    location", 1)[0]
    assert "auth_request /_grafana_auth;" in grafana_location
    assert "proxy_http_version 1.1;" in grafana_location
    assert "proxy_pass http://grafana_backend;" in grafana_location
    assert 'proxy_set_header Cookie              "";' in grafana_location
    assert 'proxy_set_header Authorization      "";' in grafana_location
    assert "proxy_set_header X-WEBAUTH-USER     $grafana_auth_user;" in grafana_location
    assert "proxy_set_header X-WEBAUTH-ROLE     $grafana_auth_role;" in grafana_location
    assert "proxy_set_header Upgrade           $http_upgrade;" in grafana_location
    assert "proxy_set_header Connection        $grafana_connection_upgrade;" in grafana_location
    assert "X-Forwarded-Prefix" not in grafana_location


def test_netops_liveness_probe_bypasses_proxy_and_allows_cold_start():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    healthcheck = compose["services"]["netops"]["healthcheck"]
    command = " ".join(str(value) for value in healthcheck["test"])

    assert "127.0.0.1:8003/api/health/live" in command
    assert "ProxyHandler({})" in command
    assert healthcheck["start_period"] == "120s"

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--start-period=120s" in dockerfile
    assert "ProxyHandler({})" in dockerfile
    assert "127.0.0.1:8003/api/health/live" in dockerfile


def test_netops_bypasses_proxy_for_internal_seaweedfs_s3_endpoint():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    environment = compose["services"]["netops"]["environment"]

    for variable in ("NO_PROXY", "no_proxy"):
        entry = next(item for item in environment if item.startswith(f"{variable}="))
        assert "seaweedfs" in entry
        assert "nexora-seaweedfs" in entry


def test_static_vmagent_and_generic_ifmib_contract():
    scrape = yaml.safe_load((ROOT / "monitoring" / "vmagent" / "scrape.yml").read_text(encoding="utf-8"))
    jobs_by_name = {job["job_name"]: job for job in scrape["scrape_configs"]}
    assert jobs_by_name["platform_grafana"]["metrics_path"] == "/grafana/metrics"
    assert jobs_by_name["platform_cadvisor"]["metrics_path"] == "/metrics"
    relabel = scrape["scrape_configs"][0]["relabel_configs"]
    labels = {item.get("target_label") for item in relabel}
    assert {"__param_target", "__param_module", "__param_auth", "__scrape_interval__", "__scrape_timeout__", "asset_id", "tenant_id"} <= labels
    assert any(item.get("action") == "labeldrop" and "nexora_auth" in item.get("regex", "") for item in relabel)

    exporter = yaml.safe_load((ROOT / "monitoring" / "snmp-exporter" / "snmp.yml").read_text(encoding="utf-8"))
    assert exporter["auths"]["bootstrap_disabled_v2"]["version"] == 2
    assert exporter["auths"]["bootstrap_disabled_v2"]["community"] == "__nexora_bootstrap_disabled__"
    walk = exporter["modules"]["generic_ifmib_interface_std"]["walk"]
    assert "1.3.6.1.2.1.2.2" in walk
    assert "1.3.6.1.2.1.31.1.1" in walk
    assert "1.3.6.1.2.1.10.7.2.1" in walk
    assert "ifHCInOctets" not in str(walk)  # OIDs are intentionally module-owned, not raw label text
    assert not {"source_indexes", "lookup"} & {
        key
        for module in exporter["modules"].values()
        for metric in module.get("metrics", [])
        for lookup in metric.get("lookups", [])
        for key in lookup
    }
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
