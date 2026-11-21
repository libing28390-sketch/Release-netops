from __future__ import annotations

from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from types import SimpleNamespace
from pathlib import Path

import yaml

from database.migrations import (
    _TRACKING_TABLE,
    build_migration_plan,
    run_migrations,
)


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-018-IDEMPOTENT-FRESH-SYNC-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-018-IDEMPOTENT-FRESH-SYNC-CONTRACT.md"
SCHEMA = ROOT / "backend" / "database" / "schema.py"


def _load() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_db018_contract_and_runtime_api_are_frozen():
    data = _load()
    assert data["task_id"] == "DB-018"
    assert data["priority"] == "P0"
    assert data["status"] == "implemented_and_contract_frozen"
    assert data["runtime_contract"]["plan_api"].endswith("build_migration_plan")
    assert "strict_history_true" in data["runtime_contract"]["production_call"]
    assert "schema_migrations" in data["runtime_contract"]["tracking_table"]
    assert "tracking_row_is_inserted_only_after_successful_upgrade_and_commit" in data["decision"]["invariants"]


def test_db018_fresh_plan_is_read_only_and_ordered(monkeypatch):
    first = SimpleNamespace(VERSION=1, NAME="baseline", upgrade=lambda cursor, use_pg: None)
    second = SimpleNamespace(VERSION=2, NAME="second", upgrade=lambda cursor, use_pg: None)
    import database.migrations as migrations

    monkeypatch.setattr(migrations, "discover_migrations", lambda: [second, first])
    conn = postgresql_test_driver.connect()
    try:
        plan = build_migration_plan(conn, use_pg=True)
        assert plan.fresh_install is True
        assert plan.discovered_versions == (1, 2)
        assert plan.applied_versions == ()
        assert plan.pending_versions == (1, 2)
        assert plan.safe is True
        assert conn.execute(f"SELECT COUNT(*) FROM {_TRACKING_TABLE}").fetchone()[0] == 0
    finally:
        conn.close()


def test_db018_fresh_run_and_repeat_are_idempotent(monkeypatch):
    calls: list[int] = []

    def baseline(cursor, use_pg):
        calls.append(1)

    def second(cursor, use_pg):
        calls.append(2)
        cursor.execute("CREATE TABLE IF NOT EXISTS db018_probe (id INTEGER PRIMARY KEY)")

    modules = [SimpleNamespace(VERSION=1, NAME="baseline", upgrade=baseline), SimpleNamespace(VERSION=2, NAME="second", upgrade=second)]
    import database.migrations as migrations

    monkeypatch.setattr(migrations, "discover_migrations", lambda: modules)
    conn = postgresql_test_driver.connect()
    try:
        assert run_migrations(conn, use_pg=True, strict_history=True) == 2
        assert calls == [1, 2]
        first_rows = conn.execute(f"SELECT version, name FROM {_TRACKING_TABLE} ORDER BY version").fetchall()
        assert [tuple(row) for row in first_rows] == [(1, "baseline"), (2, "second")]
        assert run_migrations(conn, use_pg=True, strict_history=True) == 0
        assert calls == [1, 2]
        assert conn.execute(f"SELECT COUNT(*) FROM {_TRACKING_TABLE}").fetchone()[0] == 2
    finally:
        conn.close()


def test_db018_failure_rolls_back_and_corrected_retry_remains_pending(monkeypatch):
    attempts = {"count": 0}

    def failing(cursor, use_pg):
        attempts["count"] += 1
        cursor.execute("CREATE TABLE IF NOT EXISTS db018_failed_probe (id INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO db018_failed_probe (id) VALUES (1)")
        if attempts["count"] == 1:
            raise RuntimeError("controlled migration probe failure")

    modules = [SimpleNamespace(VERSION=1, NAME="baseline", upgrade=lambda cursor, use_pg: None), SimpleNamespace(VERSION=2, NAME="retryable", upgrade=failing)]
    import database.migrations as migrations

    monkeypatch.setattr(migrations, "discover_migrations", lambda: modules)
    conn = postgresql_test_driver.connect()
    try:
        assert run_migrations(conn, use_pg=True, strict_history=True) == 1
        assert [tuple(row) for row in conn.execute(f"SELECT version FROM {_TRACKING_TABLE}").fetchall()] == [(1,)]
        # SQLite's compatibility driver keeps CREATE TABLE metadata while
        # rolling back the data transaction; PostgreSQL rolls back both. The
        # important invariant is that no row or tracking version leaked.
        assert not pg_catalog.table_exists(conn, "db018_failed_probe")
        assert run_migrations(conn, use_pg=True, strict_history=True) == 1
        assert [tuple(row) for row in conn.execute(f"SELECT version FROM {_TRACKING_TABLE} ORDER BY version").fetchall()] == [(1,), (2,)]
        assert conn.execute("SELECT COUNT(*) FROM db018_failed_probe").fetchone()[0] == 1
        assert attempts["count"] == 2
    finally:
        conn.close()


def test_db018_strict_history_rejects_unknown_versions_and_name_drift(monkeypatch):
    modules = [SimpleNamespace(VERSION=1, NAME="baseline", upgrade=lambda cursor, use_pg: None)]
    import database.migrations as migrations

    monkeypatch.setattr(migrations, "discover_migrations", lambda: modules)
    conn = postgresql_test_driver.connect()
    try:
        conn.execute(f"CREATE TABLE {_TRACKING_TABLE} (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
        conn.execute(f"INSERT INTO {_TRACKING_TABLE} VALUES (1, 'renamed', 'now')")
        conn.execute(f"INSERT INTO {_TRACKING_TABLE} VALUES (99, 'removed', 'now')")
        conn.commit()
        plan = build_migration_plan(conn, use_pg=True)
        assert plan.safe is False
        assert plan.unknown_applied_versions == (99,)
        assert plan.name_drift == ((1, "renamed", "baseline"),)
        assert run_migrations(conn, use_pg=True, strict_history=True) == 0
    finally:
        conn.close()


def test_db018_accepts_explicit_legacy_name_alias(monkeypatch):
    modules = [
        SimpleNamespace(VERSION=1, NAME="baseline", upgrade=lambda cursor, use_pg: None),
        SimpleNamespace(
            VERSION=2,
            NAME="current_name",
            LEGACY_NAMES=("historical_name",),
            upgrade=lambda cursor, use_pg: None,
        ),
    ]
    import database.migrations as migrations

    monkeypatch.setattr(migrations, "discover_migrations", lambda: modules)
    conn = postgresql_test_driver.connect()
    try:
        conn.execute(f"CREATE TABLE {_TRACKING_TABLE} (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
        conn.execute(f"INSERT INTO {_TRACKING_TABLE} VALUES (1, 'baseline', 'now')")
        conn.execute(f"INSERT INTO {_TRACKING_TABLE} VALUES (2, 'historical_name', 'now')")
        conn.commit()
        plan = build_migration_plan(conn, use_pg=True)
        assert plan.name_drift == ()
        assert plan.safe_for(strict_history=True) is True
        assert run_migrations(conn, use_pg=True, strict_history=True) == 0
    finally:
        conn.close()


def test_db018_schema_init_uses_strict_production_history_and_report_markers():
    source = SCHEMA.read_text(encoding="utf-8")
    assert "run_migrations(conn, _USE_PG, strict_history=True)" in source
    data = _load()
    assert data["fresh_schema_sync"]["baseline"]
    assert "second_run_returns_zero" in data["idempotency_contract"]["repeat_probe"]
    assert "unknown_applied_version" in data["history_safety"]["strict_mode"]
    assert "module_exception" in data["failure_recovery"]
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("DB-018", "MigrationPlan", "fresh", "upgrade", "strict", "idempotent", "rollback", "schema_migrations", "DB-019", "DB-020", "V1", "Final Conclusion: PASS"):
        assert marker in report, marker
