from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

from api import monitoring_v1
from services import collector_sync_service


def test_update_collector_normalizes_boolean_and_schedules_runtime_sync(isolated_db, monkeypatch):
    database = isolated_db["module"]
    scheduled = []
    monkeypatch.setattr(monitoring_v1, "get_db_connection", database.get_db_connection)
    monkeypatch.setattr(monitoring_v1, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        collector_sync_service,
        "trigger_async_monitoring_sync",
        lambda **kwargs: scheduled.append(kwargs),
    )

    result = monitoring_v1.update_collector(
        "collector-local",
        {"enabled": False},
        _user={"id": "operator-test", "role": "Operator"},
    )

    connection = database.get_db_connection()
    try:
        persisted = connection.execute(
            "SELECT enabled FROM monitoring_collectors WHERE id = ?",
            ("collector-local",),
        ).fetchone()
    finally:
        connection.close()

    assert persisted["enabled"] == 0
    assert result["enabled"] == 0
    assert result["status"] == "DISABLED"
    assert result["configuration_sync"] == "SCHEDULED"
    assert scheduled == [{}]


def test_update_collector_rejects_invalid_enabled_value_before_database_access(monkeypatch):
    monkeypatch.setattr(
        monitoring_v1,
        "get_db_connection",
        lambda: pytest.fail("invalid enabled values must fail before opening a database connection"),
    )

    with pytest.raises(HTTPException) as error:
        monitoring_v1.update_collector(
            "collector-local",
            {"enabled": "sometimes"},
            _user={"role": "Operator"},
        )

    assert error.value.status_code == 422


def test_disabled_local_collector_compiles_and_publishes_empty_targets(
    isolated_db, monkeypatch, tmp_path
):
    database = isolated_db["module"]
    monkeypatch.setattr(monitoring_v1, "get_db_connection", database.get_db_connection)
    monkeypatch.setattr(monitoring_v1, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(monitoring_v1, "_reload_snmp_exporter_config", lambda: True)
    monkeypatch.setenv("MONITORING_ARTIFACT_ROOT", str(tmp_path))

    seed = database.get_db_connection()
    try:
        seed.execute(
            "UPDATE monitoring_collectors SET enabled = 0 WHERE id = ?",
            ("collector-local",),
        )
        now = monitoring_v1._now()
        for version in (1, 2, 3):
            seed.execute(
                """INSERT INTO monitoring_config_versions
                   (id, collector_id, config_version, status, manifest_json, checksum, created_at, applied_at)
                   VALUES (?, ?, ?, 'APPLIED', '{}', ?, ?, ?)""",
                (
                    f"history-{version}",
                    "collector-local",
                    version,
                    f"historical-checksum-{version}",
                    now,
                    now,
                ),
            )
        seed.commit()
    finally:
        seed.close()

    monkeypatch.setattr(
        monitoring_v1,
        "_load_compile_inputs",
        lambda *_args, **_kwargs: (
            [], [], [], [], [], [], {},
            [{"id": "server-test", "management_ip": "192.0.2.10", "platform": "linux"}],
            [],
        ),
    )

    compiled = monitoring_v1.compile_collector(
        "collector-local", _user={"id": "operator-test", "role": "Operator"}
    )
    assert compiled["status"] == "COMPILED"
    assert compiled["config_version"] == 4
    assert compiled["assignment_count"] == 0
    artifact_root = Path(compiled["artifact_path"])
    assert yaml.safe_load(
        (artifact_root / "vmagent" / "targets" / "snmp_targets.yml").read_text(encoding="utf-8")
    ) == []
    assert yaml.safe_load(
        (artifact_root / "vmagent" / "targets" / "linux_targets.yml").read_text(encoding="utf-8")
    ) == []
    assert yaml.safe_load(
        (artifact_root / "vmagent" / "targets" / "windows_targets.yml").read_text(encoding="utf-8")
    ) == []

    published = monitoring_v1.publish_collector(
        "collector-local", _user={"id": "operator-test", "role": "Operator"}
    )
    assert published["status"] == "APPLIED"
    assert published["config_version"] == 4
    assert (tmp_path / "current" / "vmagent" / "targets" / "snmp_targets.yml").read_text(
        encoding="utf-8"
    ).strip() == "[]"

    check = database.get_db_connection()
    try:
        versions = check.execute(
            "SELECT config_version, status FROM monitoring_config_versions WHERE collector_id = ? ORDER BY config_version",
            ("collector-local",),
        ).fetchall()
        enabled = check.execute(
            "SELECT enabled FROM monitoring_collectors WHERE id = ?",
            ("collector-local",),
        ).fetchone()["enabled"]
    finally:
        check.close()

    assert [int(row["config_version"]) for row in versions] == [1, 2, 3, 4]
    assert versions[-1]["status"] == "APPLIED"
    assert enabled == 0


def test_collector_auto_sync_includes_disabled_local_collector(monkeypatch):
    class Result:
        def fetchall(self):
            return [{"id": "collector-local"}]

    class Connection:
        def __init__(self):
            self.statement = ""
            self.closed = False

        def execute(self, statement, params=()):
            self.statement = statement
            assert params == ()
            return Result()

        def close(self):
            self.closed = True

    connection = Connection()
    compiled_collectors = []
    monkeypatch.setattr(collector_sync_service, "get_db_connection", lambda: connection)
    monkeypatch.setattr(
        monitoring_v1,
        "compile_collector",
        lambda collector_id, _user=None: compiled_collectors.append(collector_id)
        or {"status": "UNCHANGED", "already_applied": True, "assignment_count": 0, "config_version": 4},
    )

    result = collector_sync_service.sync_all_monitoring_collectors()

    assert "enabled = 1 OR (enabled = 0 AND UPPER(collector_type) = 'LOCAL')" in connection.statement
    assert connection.closed is True
    assert compiled_collectors == ["collector-local"]
    assert result["status"] == "SUCCESS"
    assert result["results"][0]["status"] == "UNCHANGED"
