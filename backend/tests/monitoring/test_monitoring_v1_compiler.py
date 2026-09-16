from datetime import datetime, timezone

import pytest

from services.metric_provider import ShadowMetricProvider, counter_delta
from services.monitoring_compiler import (
    CollectionAssignmentConflict,
    build_assignments,
    compile_artifact,
    validate_artifact,
)
from services.monitoring_health_service import classify_collection_health
from services.collection_plan_service import validate_policy


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


def test_compiler_builds_secret_free_snapshot_and_artifact():
    assignments = build_assignments([_device()], PLANS, MODULES, VARIANTS, COLLECTORS, credential_aliases={"cred-1": "auth_opaque"})
    artifact = compile_artifact(assignments, collector_id="collector-local", config_version=7, credentials=[{"id": "cred-1", "credential_type": "snmpv2", "community": "private"}])

    assert assignments[0]["auth_alias"] == "auth_opaque"
    assert "private" not in artifact["files"]["vmagent/targets/snmp_targets.yml"]
    assert "auth_opaque" in artifact["files"]["vmagent/targets/snmp_targets.yml"]
    assert artifact["manifest"]["config_version"] == 7
    assert validate_artifact(artifact)["valid"] is True
    artifact["files"]["vmagent/scrape.yml"] += "# tampered\n"
    with pytest.raises(ValueError, match="CHECKSUM_MISMATCH"):
        validate_artifact(artifact)


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
    result = provider.instant(query="cpu_usage_percent", asset_id="asset-1", metric_key="cpu_usage_percent")
    assert result["provider"] == "shadow"
    assert result["shadow"]["status"] == "MATCH"
    assert comparisons[0]["delta"] == 3


def test_collection_health_uses_assignment_interval_not_device_status():
    now = datetime.now(timezone.utc)
    healthy = classify_collection_health({"id": "a", "asset_id": "asset-1", "interval_seconds": 30, "last_success_at": now.isoformat()}, now=now)
    stale = classify_collection_health({"id": "a", "asset_id": "asset-1", "interval_seconds": 30, "last_success_at": "2020-01-01T00:00:00+00:00"}, now=now)
    assert healthy["status"] == "OK"
    assert stale["status"] == "STALE"
