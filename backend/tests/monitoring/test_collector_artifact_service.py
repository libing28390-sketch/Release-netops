import json
import shutil
from pathlib import Path

import pytest

from services import collector_artifact_service
from services.collector_artifact_service import (
    ArtifactStoreError,
    CollectorArtifactStore,
    collector_artifact_is_current,
)
from services.monitoring_compiler import compile_artifact, validate_artifact


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


def test_collector_artifact_is_current_after_publish(tmp_path):
    root = tmp_path / "collector"
    artifact = _artifact(root, 1)
    CollectorArtifactStore(root).publish(artifact["artifact_path"], config_version=1)

    assert collector_artifact_is_current(
        artifact["artifact_path"],
        config_version=1,
        checksum=artifact["manifest"]["checksum"],
    ) is True


def test_pending_runtime_becomes_current_after_mark_runtime_applied(tmp_path):
    root = tmp_path / "collector"
    artifact = _artifact(root, 1)
    store = CollectorArtifactStore(root)
    published = store.publish(
        artifact["artifact_path"],
        config_version=1,
        runtime_status="RELOAD_PENDING",
    )

    assert published["status"] == "RELOAD_PENDING"
    assert collector_artifact_is_current(
        artifact["artifact_path"],
        config_version=1,
        checksum=artifact["manifest"]["checksum"],
    ) is False

    assert store.mark_runtime_applied(1)["status"] == "APPLIED"
    assert collector_artifact_is_current(
        artifact["artifact_path"],
        config_version=1,
        checksum=artifact["manifest"]["checksum"],
    ) is True


def test_republishing_same_pending_version_preserves_previous_lkg(tmp_path):
    root = tmp_path / "collector"
    store = CollectorArtifactStore(root)
    first = _artifact(root, 1)
    second = _artifact(root, 2)
    store.publish(first["artifact_path"], config_version=1)
    store.publish(second["artifact_path"], config_version=2, runtime_status="RELOAD_PENDING")

    store.publish(second["artifact_path"], config_version=2, runtime_status="RELOAD_PENDING")

    assert store.current_version() == 2
    assert store.previous_version() == 1


def test_new_publish_preserves_previous_when_current_version_is_reload_pending(tmp_path):
    root = tmp_path / "collector"
    store = CollectorArtifactStore(root)
    first = _artifact(root, 1)
    second = _artifact(root, 2)
    third = _artifact(root, 3)
    store.publish(first["artifact_path"], config_version=1)
    store.publish(second["artifact_path"], config_version=2, runtime_status="RELOAD_PENDING")

    store.publish(third["artifact_path"], config_version=3, runtime_status="RELOAD_PENDING")

    assert store.current_version() == 3
    assert store.previous_version() == 1


def test_new_publish_preserves_previous_when_runtime_marker_is_missing(tmp_path):
    root = tmp_path / "collector"
    store = CollectorArtifactStore(root)
    first = _artifact(root, 1)
    second = _artifact(root, 2)
    third = _artifact(root, 3)
    store.publish(first["artifact_path"], config_version=1)
    store.publish(second["artifact_path"], config_version=2, runtime_status="RELOAD_PENDING")
    (root / "runtime" / "current_version.json").unlink()

    store.publish(third["artifact_path"], config_version=3, runtime_status="RELOAD_PENDING")

    assert store.current_version() == 3
    assert store.previous_version() == 1


def test_republish_repairs_corrupt_current_without_replacing_previous_lkg(tmp_path):
    root = tmp_path / "collector"
    store = CollectorArtifactStore(root)
    first = _artifact(root, 1)
    second = _artifact(root, 2)
    store.publish(first["artifact_path"], config_version=1)
    store.publish(second["artifact_path"], config_version=2, runtime_status="RELOAD_PENDING")
    (root / "current" / "checksums.sha256").write_text("tampered\n", encoding="utf-8")

    store.publish(second["artifact_path"], config_version=2, runtime_status="RELOAD_PENDING")

    assert store.current_version() == 2
    assert store.previous_version() == 1
    assert validate_artifact(root / "current")["valid"] is True


@pytest.mark.parametrize("directory", ["current", "runtime"])
@pytest.mark.parametrize("damage", ["missing", "invalid"])
def test_collector_artifact_is_not_current_when_runtime_copy_is_unavailable_or_invalid(tmp_path, directory, damage):
    root = tmp_path / "collector"
    artifact = _artifact(root, 1)
    CollectorArtifactStore(root).publish(artifact["artifact_path"], config_version=1)
    target = root / directory

    if damage == "missing":
        shutil.rmtree(target)
    else:
        (target / "checksums.sha256").write_text("tampered\n", encoding="utf-8")

    assert collector_artifact_is_current(
        artifact["artifact_path"],
        config_version=1,
        checksum=artifact["manifest"]["checksum"],
    ) is False


@pytest.mark.parametrize("mismatch", ["manifest-version", "collector-id", "runtime-version", "status", "checksum"])
def test_collector_artifact_is_not_current_when_metadata_does_not_match(tmp_path, mismatch):
    root = tmp_path / "collector"
    artifact = _artifact(root, 1)
    CollectorArtifactStore(root).publish(artifact["artifact_path"], config_version=1)
    expected_checksum = artifact["manifest"]["checksum"]

    if mismatch == "manifest-version":
        manifest_path = root / "artifact-v00000001" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["config_version"] = 2
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif mismatch == "collector-id":
        manifest_path = root / "current" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["collector_id"] = "collector-other"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif mismatch in {"runtime-version", "status"}:
        state_path = root / "runtime" / "current_version.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["config_version" if mismatch == "runtime-version" else "status"] = 2 if mismatch == "runtime-version" else "ROLLED_BACK"
        state_path.write_text(json.dumps(state), encoding="utf-8")
    else:
        expected_checksum = "0" * 64

    assert collector_artifact_is_current(
        artifact["artifact_path"],
        config_version=1,
        checksum=expected_checksum,
    ) is False


def test_collector_artifact_is_not_current_when_source_is_missing_without_creating_directories(tmp_path):
    root = tmp_path / "missing-collector"

    assert collector_artifact_is_current(
        root / "artifact-v00000001",
        config_version=1,
        checksum="0" * 64,
    ) is False
    assert not root.exists()


@pytest.mark.parametrize("artifact_path", ["", Path("")])
def test_empty_collector_artifact_path_is_rejected_without_validation(artifact_path, monkeypatch):
    validation_calls = []
    monkeypatch.setattr(
        collector_artifact_service,
        "validate_artifact",
        lambda path: validation_calls.append(path),
    )

    assert collector_artifact_is_current(artifact_path, config_version=1, checksum="0" * 64) is False
    assert validation_calls == []
