from pathlib import Path

import pytest

from database import reset


def test_parse_postgresql_target_decodes_connection_fields():
    target = reset.parse_database_target("postgresql://netops%20user:secret@db.example:5544/cmdb%20prod")

    assert target.backend == "postgresql"
    assert target.host == "db.example"
    assert target.port == 5544
    assert target.database == "cmdb prod"
    assert target.username == "netops user"


def test_backup_directory_uses_project_data_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(reset.core, "PROJECT_ROOT", str(tmp_path))

    assert reset.backup_directory() == tmp_path / "data" / "backups" / "database-reset"


def test_reset_rejects_mismatched_confirmation(monkeypatch):
    target = reset.DatabaseTarget("postgresql", "localhost", 5432, "netops_test", "tester")
    monkeypatch.setattr(reset, "inspect_target", lambda: target)

    with pytest.raises(reset.DatabaseResetError, match="does not match"):
        reset.reset_database("wrong-name")


def test_create_backup_blocks_reset_when_pg_dump_is_missing(monkeypatch, tmp_path):
    target = reset.DatabaseTarget("postgresql", "localhost", 5432, "netops_test", "tester")
    monkeypatch.setattr(reset, "_find_pg_dump", lambda: None)

    with pytest.raises(reset.DatabaseResetError, match="pg_dump was not found"):
        reset.create_backup(target, tmp_path)


def test_create_backup_does_not_put_password_in_command(monkeypatch, tmp_path):
    target = reset.DatabaseTarget("postgresql", "localhost", 5432, "netops_test", "tester")
    captured = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        backup_path = Path(command[command.index("--file") + 1])
        backup_path.write_bytes(b"backup")
        return Result()

    monkeypatch.setattr(reset, "_find_pg_dump", lambda: "pg_dump")
    monkeypatch.setattr(reset, "_database_url", lambda: "postgresql://tester:s3cret@localhost/netops_test")
    monkeypatch.setattr(reset.subprocess, "run", fake_run)

    backup_path = reset.create_backup(target, tmp_path)

    assert backup_path.exists()
    assert "s3cret" not in " ".join(captured["command"])
    assert captured["environment"]["PGPASSWORD"] == "s3cret"


def test_reset_runs_backup_before_schema_reset(monkeypatch, tmp_path):
    target = reset.DatabaseTarget("postgresql", "localhost", 5432, "netops_test", "tester")
    events = []
    backup_path = tmp_path / "backup.dump"
    backup_path.write_bytes(b"backup")
    monkeypatch.setattr(reset, "inspect_target", lambda: target)
    monkeypatch.setattr(reset, "create_backup", lambda _target: events.append("backup") or backup_path)
    monkeypatch.setattr(reset, "_reset_postgresql_schema", lambda _target: events.append("reset") or 2)
    monkeypatch.setattr(
        reset,
        "_initialize_and_verify",
        lambda _target: events.append("verify") or {"table_count": 10, "migration_count": 5},
    )

    result = reset.reset_database("netops_test")

    assert events == ["backup", "reset", "verify"]
    assert result["terminated_connections"] == 2
    assert result["backup_path"] == str(backup_path)
