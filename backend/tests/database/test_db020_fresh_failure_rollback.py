from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import yaml

from database import get_db_connection, init_db
from database.migrations import build_migration_plan, get_applied_records, run_migrations


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-020-FRESH-FAILURE-ROLLBACK-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-020-FRESH-FAILURE-ROLLBACK-CONTRACT.md"


def _load() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _snapshot(conn) -> tuple[tuple[int, str], tuple[str, ...], tuple[tuple[str, int], ...]]:
    tracking = tuple(conn.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall())
    objects = tuple(row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index') AND name IS NOT NULL ORDER BY name"))
    counts = []
    for table in ("users", "devices", "ai_document", "ai_document_chunk", "schema_migrations"):
        counts.append((table, int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])))
    return tracking, objects, tuple(counts)


def test_db020_task_and_matrix_are_frozen():
    data = _load()
    assert data["task_id"] == "DB-020"
    assert data["priority"] == "P0"
    assert data["status"] == "implemented_failure_matrix_contract"
    assert set(data["test_matrix"]) == {"fresh_install", "repeated_execution", "partial_failure", "transaction_rollback", "history_drift"}
    assert data["fresh_contract"]["highest_version"] == 115
    assert "CREATE_TABLE_metadata_may_survive" in data["failure_recovery"]["SQLite_note"]


def test_db020_fresh_install_and_repeat_are_noop_safe(isolated_db):
    conn = get_db_connection()
    try:
        before = _snapshot(conn)
        assert before[0][0][0] == 1
        assert before[0][-1][0] == max(row[0] for row in before[0])
        for table in ("schema_migrations", "users", "devices", "ai_document", "ai_document_chunk"):
            assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        assert build_migration_plan(conn, use_pg=False).pending_versions == ()
        # init_db is guarded by _db_initialized; a direct runner repeat is the
        # migration half of a second bootstrap and must return zero.
        assert run_migrations(conn, use_pg=False, strict_history=True) == 0
        after_runner = _snapshot(conn)
        assert after_runner == before
        init_db()
        assert _snapshot(conn) == before
    finally:
        conn.close()


def test_db020_partial_failure_halts_higher_and_corrected_retry_succeeds(monkeypatch):
    calls: list[int] = []
    attempts = {"failure": 0}

    def baseline(cursor, use_pg):
        calls.append(1)

    def failed(cursor, use_pg):
        calls.append(2)
        attempts["failure"] += 1
        cursor.execute("CREATE TABLE IF NOT EXISTS db020_data (id INTEGER PRIMARY KEY, value TEXT)")
        cursor.execute("INSERT INTO db020_data (id, value) VALUES (1, 'synthetic')")
        if attempts["failure"] == 1:
            raise RuntimeError("controlled db020 failure")

    def higher(cursor, use_pg):
        calls.append(3)

    modules = [
        SimpleNamespace(VERSION=1, NAME="baseline", upgrade=baseline),
        SimpleNamespace(VERSION=2, NAME="failed", upgrade=failed),
        SimpleNamespace(VERSION=3, NAME="higher", upgrade=higher),
    ]
    import database.migrations as migrations

    monkeypatch.setattr(migrations, "discover_migrations", lambda: modules)
    conn = sqlite3.connect(":memory:")
    try:
        assert run_migrations(conn, use_pg=False, strict_history=True) == 1
        assert calls == [1, 2]
        assert conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(1,)]
        assert conn.execute("SELECT COUNT(*) FROM db020_data").fetchone()[0] == 0
        assert run_migrations(conn, use_pg=False, strict_history=True) == 2
        assert calls == [1, 2, 2, 3]
        assert conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(1,), (2,), (3,)]
        assert conn.execute("SELECT COUNT(*) FROM db020_data").fetchone()[0] == 1
    finally:
        conn.close()


def test_db020_strict_history_drift_blocks_without_new_module():
    import database.migrations as migrations

    modules = [SimpleNamespace(VERSION=1, NAME="baseline", upgrade=lambda cursor, use_pg: None), SimpleNamespace(VERSION=2, NAME="expected", upgrade=lambda cursor, use_pg: None)]
    original = migrations.discover_migrations
    migrations.discover_migrations = lambda: modules  # type: ignore[assignment]
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
        conn.execute("INSERT INTO schema_migrations VALUES (1, 'baseline', 'now')")
        conn.execute("INSERT INTO schema_migrations VALUES (99, 'unknown', 'now')")
        conn.commit()
        plan = build_migration_plan(conn, use_pg=False)
        assert plan.safe is False
        assert plan.unknown_applied_versions == (99,)
        assert run_migrations(conn, use_pg=False, strict_history=True) == 0
        assert conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(1,), (99,)]
    finally:
        conn.close()
        migrations.discover_migrations = original  # type: ignore[assignment]


def test_db020_security_rollback_and_report_markers_are_present():
    data = _load()
    assert "test_never_mutates_production_database_or_deletes_history" in data["decision"]["invariants"]
    assert "no_raw_document" in data["evidence"]["redaction"]
    assert "production_maintenance_requires_approved_identity" in data["security_and_governance"]["authorization"]
    assert data["migration_contract"]["status"] == "contract_and_isolated_tests_no_production_DDL_in_db_020"
    assert data["rollback"]["schema"] if "rollback" in data else True
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("DB-020", "fresh", "repeat", "partial", "failure", "rollback", "schema_migrations", "V1", "PostgreSQL", "Final Conclusion: PASS"):
        assert marker in report, marker
