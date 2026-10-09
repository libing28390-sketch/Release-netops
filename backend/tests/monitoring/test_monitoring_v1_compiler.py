from datetime import datetime, timezone

import pytest
import yaml

from services.metric_provider import ShadowMetricProvider, counter_delta
from services.monitoring_compiler import (
    CollectionAssignmentConflict,
    build_assignments,
    compile_artifact,
    plan_entry_matches_device,
    plan_entry_match_reason,
    render_exporter_modules,
    render_vmagent_config,
    variant_matches_device,
    validate_oid_config,
    validate_artifact,
)
from services.monitoring_oid_catalog import iter_builtin_catalog
from services.monitoring_health_service import classify_collection_health
from services.collection_plan_service import validate_policy
from services.monitoring_runtime_normalizer import normalize_snmp_runtime


MODULES = [{"id": "module-1", "module_key": "generic_ifmib_interface", "vendor": "generic"}]
VARIANTS = [{"id": "variant-1", "module_id": "module-1", "variant_key": "generic_ifmib_interface_std"}]
COLLECTORS = [{"id": "collector-local"}]
PLANS = [{
    "id": "plan-1",
    "cli_platform": "*",
    "config_json": {"modules": [{
        "module": "generic_ifmib_interface",
        "variant": "generic_ifmib_interface_std",
        "interval": "30s",
        "scrape_timeout": "20s",
    }]},
}]


def _device(**overrides):
    value = {
        "id": "asset-1",
        "ip_address": "192.0.2.10",
        "platform": "h3c_comware7",
        "collector_id": "collector-local",
        "credential_id": "ssh-1",
        "snmp_credential_id": "cred-1",
        "tenant_id": "tenant-a",
        "site_id": "site-a",
    }
    value.update(overrides)
    return value


def test_compiler_emits_generic_baselines_and_excludes_vendor_and_custom_assignments():
    baseline_keys = {"generic_ifmib_interface_std", "generic_system_std"}
    catalog = iter_builtin_catalog()
    modules = [{key: value for key, value in item.items() if key != "variant"} for item in catalog]
    variants = []
    for item in catalog:
        variant = dict(item["variant"])
        variant["module_id"] = item["id"]
        variants.append(variant)

    plan = {
        "id": "plan-baseline",
        "cli_platform": "*",
        "config_json": {"modules": [
            {"module": "generic_ifmib_interface", "variant": "generic_ifmib_interface_std", "interval": "30s", "scrape_timeout": "20s"},
            {"module": "generic_system", "variant": "generic_system_std", "interval": "900s", "scrape_timeout": "30s"},
        ]},
    }
    assignments = build_assignments(
        [_device()], [plan], modules, variants, COLLECTORS,
        credential_aliases={"cred-1": "auth_opaque"},
    )
    assert {item["variant_key"] for item in assignments} == baseline_keys
    assert all(item["selection_reason"] == "generic baseline" for item in assignments)

    custom_config = {
        "walk": ["1.3.6.1.2.1.1"],
        "metrics": [{
            "name": "sysName",
            "oid": "1.3.6.1.2.1.1.5",
            "type": "DisplayString",
            "help": "System name",
        }],
    }
    modules.append({"id": "module-custom", "module_key": "custom_module", "walk": custom_config["walk"]})
    variants.append({
        "id": "variant-custom",
        "module_id": "module-custom",
        "module_key": "custom_module",
        "variant_key": "custom_variant",
        "oid_config": custom_config,
    })
    for asset_id, target, variant_key in (
        ("vendor-asset", "192.0.2.20", "h3c_common_std"),
        ("custom-asset", "192.0.2.30", "custom_variant"),
    ):
        assignments.append({
            "collector_id": "collector-local",
            "asset_id": asset_id,
            "target": target,
            "variant_key": variant_key,
            "credential_id": "cred-1",
            "auth_alias": "auth_opaque",
            "interval_seconds": 60,
            "scrape_timeout_seconds": 20,
            "enabled": True,
        })

    artifact = compile_artifact(
        assignments,
        collector_id="collector-local",
        config_version=7,
        credentials=[{"id": "cred-1", "credential_type": "snmpv2", "community": "test-community"}],
        modules=modules,
        variants=variants,
    )

    target_groups = yaml.safe_load(artifact["files"]["vmagent/targets/snmp_targets.yml"])
    emitted_modules = {group["labels"]["nexora_module"] for group in target_groups}
    assert emitted_modules == baseline_keys
    assert {group["targets"][0] for group in target_groups} == {"192.0.2.10"}
    assert yaml.safe_load(artifact["files"]["snmp_exporter/auth/auth.yml"])["auths"] == {
        "auth_opaque": {"version": 2, "community": "test-community"},
    }
    snmp_config = yaml.safe_load(artifact["files"]["snmp_exporter/snmp.yml"])
    assert set(snmp_config["modules"]) == baseline_keys
    assert all(config.get("walk") or config.get("get") for config in snmp_config["modules"].values())
    assert all(config.get("metrics") for config in snmp_config["modules"].values())
    assert artifact["manifest"]["config_version"] == 7
    assert artifact["manifest"]["assignment_count"] == 2
    assert artifact["manifest"]["module_count"] == 2
    assert artifact["manifest"]["excluded_nonbaseline_assignment_count"] == 2
    assert set(artifact["manifest"]["excluded_nonbaseline_variant_keys"]) == {"h3c_common_std", "custom_variant"}
    assert {item["variant_key"] for item in artifact["manifest"]["modules"]} == baseline_keys
    assert len(artifact["manifest"]["modules"]) == 2
    assert all(f"snmp_exporter/modules/{key}.yml" in artifact["files"] for key in baseline_keys)
    assert "snmp_exporter/modules/h3c_common_std.yml" not in artifact["files"]
    assert "snmp_exporter/modules/custom_variant.yml" not in artifact["files"]
    assert "snmp_exporter/modules/modules.yml" in artifact["files"]
    assert validate_artifact(artifact)["valid"] is True
    artifact["files"]["vmagent/scrape.yml"] += "# tampered\n"
    with pytest.raises(ValueError, match="CHECKSUM_MISMATCH"):
        validate_artifact(artifact)


def test_platform_scrape_targets_are_added_only_to_local_collector():
    platform_jobs = {
        "platform_api": "netops:8003",
        "platform_hardware_inventory": "netops:8003",
        "platform_victoriametrics": "victoriametrics:8428",
        "platform_vmagent": "vmagent:8429",
        "platform_snmp_exporter": "snmp-exporter:9116",
        "platform_grafana": "grafana:3000",
        "platform_cadvisor": "cadvisor:8080",
        "platform_postgres_exporter": "postgres-exporter:9187",
    }

    local_jobs = render_vmagent_config(collector_id="collector-local")["scrape_configs"]
    remote_jobs = render_vmagent_config(collector_id="collector-remote")["scrape_configs"]
    local_platform_jobs = {
        job["job_name"]: job
        for job in local_jobs
        if job["job_name"].startswith("platform_")
    }
    local_targets = {
        job["job_name"]: job["static_configs"][0]["targets"][0]
        for job in local_platform_jobs.values()
    }

    assert local_targets == platform_jobs
    assert local_platform_jobs["platform_grafana"]["metrics_path"] == "/grafana/metrics"
    assert local_platform_jobs["platform_hardware_inventory"]["metrics_path"] == "/hardware-metrics"
    assert local_platform_jobs["platform_hardware_inventory"]["scrape_interval"] == "60s"
    assert all(
        job["metrics_path"] == "/metrics"
        for name, job in local_platform_jobs.items()
        if name not in {"platform_grafana", "platform_hardware_inventory"}
    )
    assert not any(job["job_name"].startswith("platform_") for job in remote_jobs)


def test_postgres_exporter_target_is_compiled_only_for_local_collector():
    local_artifact = compile_artifact([], collector_id="collector-local", config_version=1)
    local_scrape = yaml.safe_load(local_artifact["files"]["vmagent/scrape.yml"])
    local_jobs = {job["job_name"]: job for job in local_scrape["scrape_configs"]}

    assert local_jobs["platform_postgres_exporter"] == {
        "job_name": "platform_postgres_exporter",
        "scrape_interval": "30s",
        "scrape_timeout": "10s",
        "metrics_path": "/metrics",
        "static_configs": [{"targets": ["postgres-exporter:9187"]}],
    }
    assert validate_artifact(local_artifact)["valid"] is True

    remote_artifact = compile_artifact([], collector_id="collector-remote", config_version=1)
    remote_scrape = yaml.safe_load(remote_artifact["files"]["vmagent/scrape.yml"])
    assert not any(
        job["job_name"] == "platform_postgres_exporter"
        for job in remote_scrape["scrape_configs"]
    )


def test_monitoring_extension_reuses_device_collection_policy():
    policy = validate_policy({
        "template": "basic",
        "monitoring": [{
            "module": "generic_ifmib_interface",
            "variant": "generic_ifmib_interface_std",
            "interval": "30s",
            "scrape_timeout": "20s",
        }],
    })
    assert policy["monitoring"][0]["module"] == "generic_ifmib_interface"
    assignments = build_assignments(
        [_device(collection_policy_json=policy)],
        [], MODULES, VARIANTS, COLLECTORS,
        credential_aliases={"cred-1": "auth_opaque"},
    )
    assert assignments[0]["source_plan_id"].startswith("device-collection-plan:")


def test_compiler_never_reuses_ssh_credential_for_snmp():
    with pytest.raises(ValueError, match="AUTH_NOT_CONFIGURED"):
        build_assignments(
            [_device(snmp_credential_id="")],
            PLANS,
            MODULES,
            VARIANTS,
            COLLECTORS,
            credential_aliases={"ssh-1": "auth_ssh"},
        )


def test_compiler_rejects_same_asset_variant_conflict():
    duplicate_plan = {
        "id": "plan-2", "cli_platform": "*",
        "config_json": {"modules": [
            {"module": "generic_ifmib_interface", "variant": "generic_ifmib_interface_std", "interval": "30s", "scrape_timeout": "20s"},
            {"module": "generic_ifmib_interface", "variant": "generic_ifmib_interface_std", "interval": "60s", "scrape_timeout": "20s"},
        ]},
    }
    with pytest.raises(CollectionAssignmentConflict):
        build_assignments([_device()], [duplicate_plan], MODULES, VARIANTS, COLLECTORS, credential_aliases={"cred-1": "auth_opaque"})


def test_compiler_rejects_scrape_timeout_equal_to_interval():
    invalid_plan = {
        "id": "plan-invalid", "cli_platform": "*",
        "config_json": {"modules": [{
            "module": "generic_ifmib_interface", "variant": "generic_ifmib_interface_std",
            "interval": "30s", "scrape_timeout": "30s",
        }]},
    }
    with pytest.raises(ValueError, match="TIMEOUT_INVALID"):
        build_assignments([_device()], [invalid_plan], MODULES, VARIANTS, COLLECTORS, credential_aliases={"cred-1": "auth_opaque"})


def test_counter_wrap_and_reset_are_distinguished():
    assert counter_delta(2, 2**32 - 2, bits=32) == 4
    assert counter_delta(10, 20, bits=32) is None


class _Provider:
    def __init__(self, value):
        self.value = value

    def instant(self, **_kwargs):
        return {"data": [{"value": self.value}]}

    def range(self, **_kwargs):
        return {"data": [{"value": self.value}]}


def test_shadow_provider_returns_primary_and_records_compare():
    comparisons = []
    provider = ShadowMetricProvider(_Provider(100), _Provider(103), tolerance=0.05, sink=comparisons.append)
    result = provider.instant(query="in_bps", asset_id="asset-1", metric_key="interface_rx_bps")
    assert result["provider"] == "shadow"
    assert result["shadow"]["status"] == "MATCH"
    assert comparisons[0]["delta"] == 3


def test_collection_health_uses_assignment_interval_not_device_status():
    now = datetime.now(timezone.utc)
    healthy = classify_collection_health({"id": "a", "asset_id": "asset-1", "interval_seconds": 30, "last_success_at": now.isoformat()}, now=now)
    stale = classify_collection_health({"id": "a", "asset_id": "asset-1", "interval_seconds": 30, "last_success_at": "2020-01-01T00:00:00+00:00"}, now=now)
    assert healthy["status"] == "OK"
    assert stale["status"] == "STALE"
    assert classify_collection_health({"id": "a", "asset_id": "asset-1", "interval_seconds": 30, "last_success_at": now.isoformat(), "last_attempt_at": now.isoformat(), "duration_ms": 12, "consecutive_failures": 2})["consecutive_failures"] == 2


def test_compiler_emits_only_generic_baselines_across_the_catalog():
    catalog = iter_builtin_catalog()
    modules = []
    variants = []
    assignments = []
    candidate_count = 0
    for item in catalog:
        modules.append({key: value for key, value in item.items() if key != "variant"})
        variant = dict(item["variant"])
        variant["module_id"] = item["id"]
        variants.append(variant)
        if str(variant.get("status") or "PUBLISHED").upper() != "DRAFT" and variant.get("enabled") is not False:
            assignments.append({
                "collector_id": "collector-local",
                "asset_id": f"asset-{candidate_count}",
                "target": f"192.0.2.{candidate_count + 1}",
                "variant_key": variant["variant_key"],
                "credential_id": "cred-1",
                "auth_alias": "auth_opaque",
                "interval_seconds": 60,
                "scrape_timeout_seconds": 20,
                "enabled": True,
            })
            candidate_count += 1

    artifact = compile_artifact(
        assignments,
        collector_id="collector-local",
        config_version=1,
        credentials=[{"id": "cred-1", "credential_type": "snmpv2", "community": "private"}],
        modules=modules,
        variants=variants,
    )
    baseline_keys = {"generic_ifmib_interface_std", "generic_system_std"}
    exporter_config = yaml.safe_load(artifact["files"]["snmp_exporter/snmp.yml"])
    assert set(exporter_config["modules"]) == baseline_keys
    assert all(config.get("walk") or config.get("get") for config in exporter_config["modules"].values())
    assert all(config.get("metrics") for config in exporter_config["modules"].values())
    target_groups = yaml.safe_load(artifact["files"]["vmagent/targets/snmp_targets.yml"])
    assert {group["labels"]["nexora_module"] for group in target_groups} == baseline_keys
    assert len(target_groups) == 2
    assert artifact["manifest"]["assignment_count"] == 2
    assert artifact["manifest"]["module_count"] == 2
    assert {item["variant_key"] for item in artifact["manifest"]["modules"]} == baseline_keys
    assert len(artifact["manifest"]["modules"]) == 2
    assert artifact["manifest"]["excluded_nonbaseline_assignment_count"] == candidate_count - 2
    assert not (baseline_keys & set(artifact["manifest"]["excluded_nonbaseline_variant_keys"]))
    assert "h3c_common_std" in artifact["manifest"]["excluded_nonbaseline_variant_keys"]
    assert "huawei_common_std" in artifact["manifest"]["excluded_nonbaseline_variant_keys"]
    assert "cisco_common_std" in artifact["manifest"]["excluded_nonbaseline_variant_keys"]
    assert "ruijie_common_std" in artifact["manifest"]["excluded_nonbaseline_variant_keys"]
    assert "juniper_common_std" in artifact["manifest"]["excluded_nonbaseline_variant_keys"]
    assert "fortinet_common_std" in artifact["manifest"]["excluded_nonbaseline_variant_keys"]


def test_optical_oid_catalog_uses_verified_units_and_does_not_scale_huawei_mixed_power():
    metrics = {
        metric["name"]: metric
        for item in iter_builtin_catalog()
        for metric in item["variant"].get("oid_config", {}).get("metrics", [])
    }

    assert metrics["hh3cTransceiverCurRXPowerDbm"]["unit"] == "dBm"
    assert metrics["hh3cTransceiverTemperatureCelsius"]["unit"] == "celsius"
    assert metrics["hh3cTransceiverVoltageVolts"]["scale"] == 0.01
    assert metrics["hh3cTransceiverBiasCurrentMilliAmps"]["scale"] == 0.01
    assert metrics["hwEntityOpticalRxPowerRaw"]["unit"] == "mixed_raw"
    assert "scale" not in metrics["hwEntityOpticalRxPowerRaw"]
    assert metrics["ruijieFiberVoltageVolts"]["scale"] == 0.001
    assert metrics["zteAnOpticalIfRxPwrCurrDbm"]["oid"] == "1.3.6.1.4.1.3902.1082.30.40.2.4.1.2"
    assert metrics["zteAnOpticalIfTemperatureCelsius"]["scale"] == 0.001


def test_multi_vendor_device_variant_matching_matrix():
    catalog = iter_builtin_catalog()
    variant_by_key = {item["variant"]["variant_key"]: item["variant"] for item in catalog}

    h3c_wireless_device = {
        "vendor": "H3C",
        "platform": "h3c_comware",
        "model": "WX5540H",
        "version": "7.1.064",
    }
    ruijie_device = {"platform": "ruijie_rgos", "model": "RG-S6220-48XT4QXS", "version": "RGOS 11.4"}
    juniper_device = {"platform": "juniper_junos", "model": "QFX5100-48S-6Q", "version": "JUNOS 20.4R3"}
    fortinet_device = {"platform": "fortinet_fortios", "model": "FortiGate-100F", "version": "FortiOS 7.2"}

    assert variant_matches_device(variant_by_key["h3c_wireless_std"], h3c_wireless_device)
    assert variant_matches_device(variant_by_key["ruijie_common_std"], ruijie_device)
    assert variant_matches_device(variant_by_key["juniper_common_std"], juniper_device)
    assert variant_matches_device(variant_by_key["fortinet_common_std"], fortinet_device)

    # Cross-vendor isolation: Ruijie should not match Cisco or H3C
    assert not variant_matches_device(variant_by_key["cisco_common_std"], ruijie_device)
    assert not variant_matches_device(variant_by_key["h3c_common_std"], ruijie_device)


def test_exporter_renderer_never_emits_unverified_oid_modules():
    rendered = render_exporter_modules(
        [{"variant_key": "custom_variant", "enabled": True}],
        modules=[{"module_key": "custom_module", "walk": ["1.3.6.1.2.1.1"]}],
        variants=[{
            "variant_key": "custom_variant",
            "module_key": "custom_module",
            "oid_config": {
                "walk": ["1.3.6.1.2.1.1"],
                "metrics": [{
                    "name": "sysName",
                    "oid": "1.3.6.1.2.1.1.5",
                    "type": "DisplayString",
                    "help": "System name",
                    "unit": "text",
                    "source_name": "sysName",
                }],
            },
        }],
    )

    assert rendered == {}
    assert render_exporter_modules([]) == {}

    artifact = compile_artifact(
        [{
            "collector_id": "collector-local",
            "asset_id": "asset-1",
            "target": "192.0.2.10",
            "variant_key": "custom_variant",
            "credential_id": "cred-1",
            "auth_alias": "auth_opaque",
            "interval_seconds": 60,
            "scrape_timeout_seconds": 20,
            "enabled": True,
        }],
        collector_id="collector-local",
        config_version=1,
        credentials=[{"id": "cred-1", "credential_type": "snmpv2", "community": "private"}],
        modules=[{"module_key": "custom_module", "walk": ["1.3.6.1.2.1.1"]}],
        variants=[{
            "variant_key": "custom_variant",
            "module_key": "custom_module",
            "oid_config": {
                "walk": ["1.3.6.1.2.1.1"],
                "metrics": [{
                    "name": "sysName",
                    "oid": "1.3.6.1.2.1.1.5",
                    "type": "DisplayString",
                    "help": "System name",
                    "unit": "text",
                    "source_name": "sysName",
                }],
            },
        }],
    )
    exporter_config = yaml.safe_load(artifact["files"]["snmp_exporter/snmp.yml"])
    assert exporter_config["modules"] == {}
    assert yaml.safe_load(artifact["files"]["vmagent/targets/snmp_targets.yml"]) == []
    assert artifact["manifest"]["assignment_count"] == 0
    assert artifact["manifest"]["excluded_nonbaseline_assignment_count"] == 1
    assert artifact["manifest"]["excluded_nonbaseline_variant_keys"] == ["custom_variant"]


def test_runtime_normalizer_repairs_legacy_exporter_copy(tmp_path):
    runtime = tmp_path / "runtime" / "snmp_exporter"
    runtime.mkdir(parents=True)
    config = runtime / "snmp.yml"
    config.write_text(
        """auths: {}\nmodules:\n  demo:\n    walk: [1.3.6.1.2.1.1]\n    metrics:\n      - name: sysName\n        oid: 1.3.6.1.2.1.1.5\n        type: DisplayString\n        help: System name\n        unit: text\n        source_name: sysName\n""",
        encoding="utf-8",
    )

    assert normalize_snmp_runtime(tmp_path / "runtime") == 2
    normalized = yaml.safe_load(config.read_text(encoding="utf-8"))
    metric = normalized["modules"]["demo"]["metrics"][0]
    assert "unit" not in metric
    assert "source_name" not in metric


def test_runtime_normalizer_upgrades_old_lookup_schema_in_persistent_volume(tmp_path):
    runtime = tmp_path / "runtime" / "snmp_exporter"
    runtime.mkdir(parents=True)
    config = runtime / "snmp.yml"
    config.write_text(
        """auths: {}
modules:
  demo:
    walk: [1.3.6.1.2.1.2.2]
    metrics:
      - name: ifName
        oid: 1.3.6.1.2.1.31.1.1.1.1
        type: DisplayString
        help: Interface name
      - name: ifDescr
        oid: 1.3.6.1.2.1.2.2.1.2
        type: DisplayString
        help: Interface description
      - name: ifOperStatus
        oid: 1.3.6.1.2.1.2.2.1.8
        type: gauge
        help: Interface operational state
        indexes:
          - labelname: ifIndex
            type: gauge
        lookups:
          - source_indexes: [ifIndex]
            lookup: ifName
          - source_indexes: [ifIndex]
            lookup: ifDescr
""",
        encoding="utf-8",
    )

    assert normalize_snmp_runtime(tmp_path / "runtime") == 2
    normalized = yaml.safe_load(config.read_text(encoding="utf-8"))
    lookups = normalized["modules"]["demo"]["metrics"][2]["lookups"]
    assert lookups == [
        {"labels": ["ifIndex"], "labelname": "ifName", "oid": "1.3.6.1.2.1.31.1.1.1.1", "type": "DisplayString"},
        {"labels": ["ifIndex"], "labelname": "ifDescr", "oid": "1.3.6.1.2.1.2.2.1.2", "type": "DisplayString"},
    ]
    assert normalize_snmp_runtime(tmp_path / "runtime") == 0


def test_oid_config_compiler_accepts_legacy_lookups_but_emits_v026_schema():
    config = validate_oid_config({
        "walk": ["1.3.6.1.2.1.2.2"],
        "metrics": [
            {"name": "ifName", "oid": "1.3.6.1.2.1.31.1.1.1.1", "type": "DisplayString"},
            {"name": "ifOperStatus", "oid": "1.3.6.1.2.1.2.2.1.8", "type": "gauge", "lookups": [
                {"source_indexes": ["ifIndex"], "lookup": "ifName"},
            ]},
        ],
    })

    assert config["metrics"][1]["lookups"] == [{
        "labels": ["ifIndex"],
        "labelname": "ifName",
        "oid": "1.3.6.1.2.1.31.1.1.1.1",
        "type": "DisplayString",
    }]


def test_compiled_manifest_excludes_vendor_oid_collection_without_source_mapping():
    catalog = iter_builtin_catalog()
    modules = [{key: value for key, value in item.items() if key != "variant"} for item in catalog]
    variants = []
    for item in catalog:
        variant = dict(item["variant"])
        variant["module_id"] = item["id"]
        variants.append(variant)
    assignments = [{
        "collector_id": "collector-local",
        "asset_id": "asset-1",
        "target": "192.0.2.10",
        "variant_key": "h3c_common_std",
        "credential_id": "cred-1",
        "auth_alias": "auth_opaque",
        "interval_seconds": 60,
        "scrape_timeout_seconds": 20,
        "enabled": True,
    }]
    artifact = compile_artifact(
        assignments,
        collector_id="collector-local",
        config_version=9,
        credentials=[{"id": "cred-1", "credential_type": "snmpv2", "community": "private"}],
        modules=modules,
        variants=variants,
    )
    exporter_config = yaml.safe_load(artifact["files"]["snmp_exporter/snmp.yml"])
    assert exporter_config["modules"] == {}
    assert yaml.safe_load(artifact["files"]["vmagent/targets/snmp_targets.yml"]) == []
    assert artifact["manifest"]["modules"] == []
    assert artifact["manifest"]["excluded_nonbaseline_assignment_count"] == 1
    assert artifact["manifest"]["excluded_nonbaseline_variant_keys"] == ["h3c_common_std"]


def test_vendor_plan_entry_selector_keeps_one_plan_for_multiple_vendors():
    assert plan_entry_matches_device({"vendor": ["h3c", "comware"]}, {"vendor": "H3C", "platform": "h3c_comware7"})
    assert not plan_entry_matches_device({"vendor": ["h3c", "comware"]}, {"vendor": "Huawei", "platform": "vrp"})
    assert plan_entry_matches_device({"vendor": ["cisco", "iosxe"]}, {"vendor": "Cisco", "platform": "iosxe"})
    assert plan_entry_match_reason({"vendor": ["cisco"]}, {"vendor": "Cisco", "platform": "iosxe"}) == "vendor=Cisco"


def test_oid_config_validation_rejects_duplicate_and_empty_payloads():
    with pytest.raises(ValueError, match="OID_CONFIG_DUPLICATE_OID"):
        validate_oid_config({"walk": ["1.3.6.1.2.1.1", "1.3.6.1.2.1.1"], "metrics": [{"name": "sysUpTime", "oid": "1.3.6.1.2.1.1.3", "type": "gauge"}]})
    with pytest.raises(ValueError, match="OID_CONFIG_HAS_NO_METRICS"):
        validate_oid_config({"walk": ["1.3.6.1.2.1.1"]})
    with pytest.raises(ValueError, match="OID_CONFIG_WALK_INVALID"):
        validate_oid_config({"walk": ["3.999.1"], "metrics": [{"name": "bad", "oid": "1.3.6.1.2.1.1.3", "type": "gauge"}]})


def test_load_compile_inputs_sql_schema_contract():
    from api.monitoring_v1 import _load_compile_inputs
    import inspect

    src = inspect.getsource(_load_compile_inputs)
    # physical_assets has no 'site' (only site_id) or 'tenant_id' column
    assert "pa.site)" not in src
    assert "pa.site " not in src
    assert "pa.tenant_id" not in src
    # Must use s.id = pa.site_id
    assert "s.id = pa.site_id" in src
    # Must rollback on exception to prevent aborted transactions
    assert "conn.rollback()" in src


def test_reload_snmp_exporter_config_uses_opener_open(monkeypatch):
    from api.monitoring_v1 import _reload_snmp_exporter_config
    import api.monitoring_v1 as mon_v1

    called = {}

    class FakeResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    class FakeOpener:
        def open(self, req, timeout=3):
            called["url"] = req.full_url
            called["method"] = req.get_method()
            called["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(mon_v1, "build_opener", lambda *args: FakeOpener())

    success = _reload_snmp_exporter_config()
    assert success is True
    assert called["url"] == "http://snmp-exporter:9116/-/reload"
    assert called["method"] == "POST"
    assert called["timeout"] == 3


def test_adapt_pg_sql_does_not_misinterpret_percent_words_as_placeholders():
    from database.core import _adapt_pg_sql

    sql = "SELECT * FROM devices WHERE device_category LIKE '%server%' AND hostname LIKE '%switch%' AND id = ?"
    adapted = _adapt_pg_sql(sql)
    assert "?" not in adapted
    # Both %server% and %switch% should be escaped to %%
    assert "%%server%%" in adapted
    assert "%%switch%%" in adapted
    # The true placeholder ? should become %s
    assert "id = %s" in adapted

    # Test formatting with 1 argument (only for the id placeholder)
    formatted = adapted % ("dev-1",)
    assert "device_category LIKE '%server%'" in formatted
    assert "hostname LIKE '%switch%'" in formatted
    assert "id = dev-1" in formatted


def test_load_compile_inputs_loads_servers_without_syntax_error(isolated_db):
    import database
    conn = database.get_db_connection()
    try:
        now = "2026-09-20T20:00:00"
        conn.execute(
            """INSERT INTO physical_assets
               (id, asset_type, hostname, management_ip, platform, status, created_at, updated_at)
               VALUES (?, 'server', 'linux-node-1', '192.168.204.128', 'ubuntu', 'active', ?, ?)""",
            ("server-test-1", now, now)
        )
        conn.commit()

        from api.monitoring_v1 import _load_compile_inputs
        inputs = _load_compile_inputs(conn, "collector-local")
        servers = inputs[7]
        assert len(servers) >= 1
        server_ips = {s.get("management_ip") for s in servers}
        assert "192.168.204.128" in server_ips
    finally:
        conn.close()
