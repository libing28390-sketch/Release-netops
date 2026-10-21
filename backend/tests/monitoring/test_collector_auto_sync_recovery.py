import json
import shutil
from pathlib import Path

import pytest

from api import monitoring_v1
from services import collector_sync_service


@pytest.fixture
def recovery_runtime(isolated_db, monkeypatch, tmp_path):
    database = isolated_db["module"]
    monkeypatch.setattr(monitoring_v1, "get_db_connection", database.get_db_connection)
    monkeypatch.setattr(collector_sync_service, "get_db_connection", database.get_db_connection)
    monkeypatch.setattr(monitoring_v1, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(monitoring_v1, "_reload_snmp_exporter_config", lambda: True)
    monkeypatch.setenv("MONITORING_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setattr(monitoring_v1, "_load_compile_inputs", lambda *args: (
        [], [], [], [], [], [], {},
        [{"id": "server-test", "management_ip": "192.0.2.10", "platform": "linux"}], [],
    ))
    conn = database.get_db_connection()
    try:
        conn.execute("UPDATE monitoring_collectors SET enabled = 1 WHERE id = 'collector-local'")
        conn.commit()
    finally:
        conn.close()
    return tmp_path, database


def _sync():
    result = collector_sync_service.sync_all_monitoring_collectors()
    return result, result["results"][0]


def test_auto_sync_initializes_and_skips_verified_runtime(recovery_runtime):
    root, _ = recovery_runtime
    result, first = _sync()
    assert result["status"] == "SUCCESS"
    assert first["status"] == "APPLIED"
    before = (root / "runtime" / "current_version.json").stat().st_mtime_ns
    result, second = _sync()
    assert result["status"] == "SUCCESS"
    assert second["status"] == "UNCHANGED"
    assert second["config_version"] == first["config_version"]
    assert (root / "runtime" / "current_version.json").stat().st_mtime_ns == before


@pytest.mark.parametrize("damage", ["runtime_missing", "current_missing", "runtime_payload", "marker_missing", "marker_version"])
def test_auto_sync_repairs_runtime_without_manual_publish(recovery_runtime, damage):
    root, _ = recovery_runtime
    _, first = _sync()
    expected = (root / "runtime" / "vmagent" / "targets" / "linux_targets.yml").read_bytes()
    if damage == "runtime_missing":
        shutil.rmtree(root / "runtime")
    elif damage == "current_missing":
        shutil.rmtree(root / "current")
    elif damage == "runtime_payload":
        (root / "runtime" / "vmagent" / "targets" / "linux_targets.yml").write_text("[]\n")
    elif damage == "marker_missing":
        (root / "runtime" / "current_version.json").unlink()
    else:
        (root / "runtime" / "current_version.json").write_text(json.dumps({"status": "APPLIED", "config_version": 999}))
    result, repaired = _sync()
    assert result["status"] == "SUCCESS"
    assert repaired["status"] == "APPLIED"
    assert repaired["config_version"] == first["config_version"]
    assert (root / "runtime" / "vmagent" / "targets" / "linux_targets.yml").read_bytes() == expected
    assert _sync()[1]["status"] == "UNCHANGED"


@pytest.mark.parametrize("missing", [True, False])
def test_auto_sync_rebuilds_lost_or_corrupt_version_artifact(recovery_runtime, missing):
    root, _ = recovery_runtime
    _, first = _sync()
    source = root / f"artifact-v{first['config_version']:08d}"
    if missing:
        shutil.rmtree(source)
    else:
        (source / "checksums.sha256").write_text("corrupt\n")
    result, repaired = _sync()
    assert result["status"] == "SUCCESS"
    assert repaired["status"] == "APPLIED"
    assert repaired["config_version"] == first["config_version"] + 1
    assert _sync()[1]["status"] == "UNCHANGED"


def test_reload_failure_remains_retryable_even_with_applied_database(recovery_runtime, monkeypatch):
    root, database = recovery_runtime
    _, first = _sync()
    shutil.rmtree(root / "runtime")
    monkeypatch.setattr(monitoring_v1, "_reload_snmp_exporter_config", lambda: False)
    result, failed = _sync()
    assert result["status"] == "FAILED"
    assert failed["status"] == "FAILED"
    marker = json.loads((root / "runtime" / "current_version.json").read_text())
    assert marker["status"] == "RELOAD_PENDING"
    conn = database.get_db_connection()
    try:
        row = conn.execute("SELECT last_config_status FROM monitoring_collectors WHERE id = 'collector-local'").fetchone()
        assert row["last_config_status"] == "APPLIED"
    finally:
        conn.close()
    monkeypatch.setattr(monitoring_v1, "_reload_snmp_exporter_config", lambda: True)
    result, repaired = _sync()
    assert result["status"] == "SUCCESS"
    assert repaired["status"] == "APPLIED"
    assert repaired["config_version"] == first["config_version"]
    assert _sync()[1]["status"] == "UNCHANGED"


@pytest.mark.parametrize("bad_ids,expected", [({"a", "b"}, "FAILED"), ({"a"}, "PARTIAL_FAILURE"), (set(), "SUCCESS")])
def test_auto_sync_summarizes_collector_failures(monkeypatch, bad_ids, expected):
    class Connection:
        def execute(self, *args):
            return self

        def fetchall(self):
            return [{"id": "a"}, {"id": "b"}]

        def close(self):
            pass

    monkeypatch.setattr(collector_sync_service, "get_db_connection", Connection)
    monkeypatch.setattr(monitoring_v1, "compile_collector", lambda *args, **kwargs: {"status": "COMPILED"})

    def publish(collector_id, **kwargs):
        if collector_id in bad_ids:
            raise RuntimeError("simulated dependency failure")
        return {"status": "APPLIED"}

    monkeypatch.setattr(monitoring_v1, "publish_collector", publish)
    result = collector_sync_service.sync_all_monitoring_collectors()
    assert result["status"] == expected
    assert sum(row["status"] == "FAILED" for row in result["results"]) == len(bad_ids)
