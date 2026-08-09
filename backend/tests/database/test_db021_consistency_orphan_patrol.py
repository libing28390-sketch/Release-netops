from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import yaml

from database.consistency import (
    discover_foreign_keys,
    run_consistency_patrol,
    run_scheduled_consistency_patrol,
)
from database import get_db_connection


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-021-CONSISTENCY-ORPHAN-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-021-CONSISTENCY-ORPHAN-CONTRACT.md"


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _synthetic_connection(*, foreign_keys: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")
    conn.executescript(
        """
        CREATE TABLE parent (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL);
        CREATE TABLE child (
            id TEXT PRIMARY KEY,
            parent_id TEXT,
            tenant_id TEXT NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES parent(id)
        );
        """
    )
    return conn


def test_db021_contract_and_report_are_frozen():
    data = _contract()
    assert data["task_id"] == "DB-021"
    assert data["priority"] == "P1"
    assert data["status"] == "implemented_read_only_patrol"
    assert data["decision"]["choice"] == "catalog_driven_read_only_foreign_key_and_tenant_scope_patrol"
    assert data["schedule"]["job_id"] == "database_consistency_patrol"
    assert data["checks"]["limits"]["max_checks_default"] == 200
    assert "read_only_no_commit_or_ddl" in data["decision"]["invariants"]

    report = REPORT.read_text(encoding="utf-8")
    for marker in (
        "DB-021", "PRAGMA foreign_key_list", "PostgreSQL", "NOT_APPLICABLE",
        "tenant_id", "SHA-256", "read-only", "02:25", "V1", "Final Conclusion: PASS",
    ):
        assert marker in report, marker


def test_db021_discovers_declared_relationships_and_skips_composites():
    conn = _synthetic_connection()
    try:
        relationships = discover_foreign_keys(conn, use_pg=False)
        assert relationships == [
            {
                "constraint": "sqlite:child:0",
                "child_schema": "main",
                "child_table": "child",
                "child_column": "parent_id",
                "parent_schema": "main",
                "parent_table": "parent",
                "parent_column": "id",
                "column_count": 1,
            }
        ]
        conn.executescript(
            """
            CREATE TABLE composite_parent (a TEXT, b TEXT, PRIMARY KEY(a, b));
            CREATE TABLE composite_child (
                a TEXT, b TEXT,
                FOREIGN KEY (a, b) REFERENCES composite_parent(a, b)
            );
            """
        )
        report = run_consistency_patrol(conn, use_pg=False)
        composite = [item for item in report["checks"] if item.get("child_table") == "composite_child"]
        assert composite and composite[0]["status"] == "NOT_APPLICABLE"
    finally:
        conn.close()


def test_db021_clean_database_passes_and_is_read_only():
    conn = _synthetic_connection()
    try:
        conn.execute("INSERT INTO parent VALUES ('parent-1', 'tenant-a')")
        conn.execute("INSERT INTO child VALUES ('child-1', 'parent-1', 'tenant-a')")
        conn.commit()
        before = conn.execute("SELECT COUNT(*) FROM child").fetchone()[0]
        report = run_consistency_patrol(conn, use_pg=False, tenant_id="tenant-a")
        assert report["status"] == "PASS"
        assert report["failure_count"] == 0
        assert report["read_only"] is True
        assert conn.execute("SELECT COUNT(*) FROM child").fetchone()[0] == before
    finally:
        conn.close()


def test_db021_orphan_is_fail_closed_and_redacted():
    conn = _synthetic_connection(foreign_keys=False)
    try:
        conn.execute("INSERT INTO child VALUES ('secret-child-id', 'missing-parent-id', 'tenant-a')")
        conn.commit()
        report = run_consistency_patrol(conn, use_pg=False)
        orphan = next(item for item in report["checks"] if item.get("kind") == "orphan")
        assert report["status"] == "FAIL"
        assert orphan["count"] == 1
        assert orphan["sample_fingerprints"] == [
            hashlib.sha256("child|parent_id|missing-parent-id".encode()).hexdigest()[:16]
        ]
        serialized = repr(report)
        assert "secret-child-id" not in serialized
        assert "missing-parent-id" not in serialized
    finally:
        conn.close()


def test_db021_tenant_scope_mismatch_is_detected_without_cross_tenant_output():
    conn = _synthetic_connection()
    try:
        conn.execute("INSERT INTO parent VALUES ('parent-1', 'tenant-b')")
        conn.execute("INSERT INTO child VALUES ('child-1', 'parent-1', 'tenant-a')")
        conn.commit()
        report = run_consistency_patrol(conn, use_pg=False, tenant_id="tenant-a")
        scope = next(item for item in report["checks"] if item.get("kind") == "tenant_scope")
        assert report["status"] == "FAIL"
        assert scope["count"] == 1
        assert report["tenant_id"] == "tenant-a"
        assert "tenant-b" not in repr(report)
    finally:
        conn.close()


def test_db021_bounds_checks_and_preserves_v1_schema(isolated_db):
    conn = get_db_connection()
    try:
        before_tables = tuple(
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        )
        report = run_consistency_patrol(conn, use_pg=False, max_checks=4, sample_limit=1)
        assert report["read_only"] is True
        assert report["check_count"] <= 4
        assert report["truncated"] is True or report["relationship_count"] <= 3
        after_tables = tuple(
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        )
        assert after_tables == before_tables
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    finally:
        conn.close()


def test_db021_scheduler_entrypoint_returns_redacted_report(isolated_db):
    report = run_scheduled_consistency_patrol()
    assert report["scope"] == "database_consistency"
    assert report["read_only"] is True
    assert "DATABASE_URL" not in repr(report)
