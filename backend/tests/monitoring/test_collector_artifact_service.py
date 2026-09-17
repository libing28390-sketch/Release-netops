import pytest

from services.collector_artifact_service import ArtifactStoreError, CollectorArtifactStore
from services.monitoring_compiler import compile_artifact


def _artifact(root, version):
    return compile_artifact(
        [{
            "asset_id": "asset-1",
            "target": "192.0.2.10",
            "collector_id": "collector-local",
            "variant_key": "generic_ifmib_interface_std",
            "auth_alias": "auth_opaque",
            "credential_id": "cred-1",
            "interval_seconds": 30,
            "scrape_timeout_seconds": 20,
            "enabled": True,
        }],
        collector_id="collector-local",
        config_version=version,
        credentials=[{"id": "cred-1", "credential_type": "snmpv2", "community": "private"}],
        output_root=root,
    )


def test_collector_artifact_store_keeps_previous_and_rolls_back(tmp_path):
    root = tmp_path / "collector"
    first = _artifact(root, 1)
    store = CollectorArtifactStore(root)
    assert store.publish(first["artifact_path"], config_version=1)["previous_version"] is None
    assert (root / "runtime" / "vmagent" / "targets" / "snmp_targets.yml").is_file()
    assert (root / "runtime" / "snmp_exporter" / "snmp.yml").is_file()

    second = _artifact(root, 2)
    applied = store.publish(second["artifact_path"], config_version=2)
    assert applied["current_version"] == 2
    assert applied["previous_version"] == 1

    rolled_back = store.rollback()
    assert rolled_back["status"] == "ROLLED_BACK"
    assert rolled_back["config_version"] == 1
    assert store.current_version() == 1
    assert (root / "runtime" / "current_version.json").read_text(encoding="utf-8").find('"config_version": 1') >= 0


def test_collector_artifact_store_rejects_invalid_publish(tmp_path):
    root = tmp_path / "collector"
    artifact = _artifact(root, 1)
    target = root / "artifact-v00000001" / "checksums.sha256"
    target.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ArtifactStoreError, match="CHECKSUM"):
        CollectorArtifactStore(root).publish(artifact["artifact_path"], config_version=1)
