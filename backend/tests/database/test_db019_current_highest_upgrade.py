from __future__ import annotations

from pathlib import Path

import yaml

from database import get_db_connection
from database.migrations import build_migration_plan, discover_migrations, get_applied_records, run_migrations


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-019-UPGRADE-TEST-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-019-UPGRADE-TEST-CONTRACT.md"
SCHEMA = ROOT / "backend" / "database" / "schema.py"
CONTRACT_DIR = ROOT / "docs" / "knowledge-engine" / "architecture"


def _load() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _index_snapshot(conn) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT indexname FROM pg_indexes "
        "WHERE schemaname = current_schema() ORDER BY indexname"
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def test_db019_task_discovery_and_v2_contract_target_are_frozen(isolated_db):
    data = _load()
    assert data["task_id"] == "DB-019"
    assert data["priority"] == "P0"
    assert data["status"] == "implemented_upgrade_harness_contract"
    modules = discover_migrations()
    versions = [int(module.VERSION) for module in modules]
    assert versions == sorted(set(versions))
    assert max(versions) >= data["upgrade_fixture"]["legacy_highest_version"] == 115
    assert data["upgrade_fixture"]["snapshot_version"] == 114
    for task_id in data["v2_contract_target"]["required_docs"]:
        assert list(CONTRACT_DIR.glob(f"{task_id}*.yaml")), task_id
    assert "contract_only" in data["v2_contract_target"]["physical_schema_status"]


def test_db019_fresh_baseline_has_every_discovered_version_and_v1_tables(isolated_db):
    conn = get_db_connection()
    try:
        applied = get_applied_records(conn)
        discovered = {int(module.VERSION): str(module.NAME) for module in discover_migrations()}
        assert set(applied) == set(discovered)
        assert all(applied[version] == name for version, name in discovered.items())
        for table in ("schema_migrations", "users", "devices", "ai_document", "ai_document_chunk"):
            assert conn.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = ?",
                (table,),
            ).fetchone()
        assert build_migration_plan(conn, use_pg=True).pending_versions == ()
    finally:
        conn.close()


def test_db019_test_only_114_to_115_upgrade_applies_once(isolated_db):
    conn = get_db_connection()
    try:
        before = get_applied_records(conn)
        before_indexes = _index_snapshot(conn)
        current_version = max(before)
        assert current_version >= 115
        conn.execute("DELETE FROM schema_migrations WHERE version = ?", (current_version,))
        conn.commit()
        snapshot = get_applied_records(conn)
        assert max(snapshot) == current_version - 1
        plan = build_migration_plan(conn, use_pg=True)
        assert plan.pending_versions == (current_version,)
        assert plan.safe is True
        assert run_migrations(conn, use_pg=True, strict_history=True) == 1
        after = get_applied_records(conn)
        assert set(after) == set(before)
        assert _index_snapshot(conn) == before_indexes
        assert run_migrations(conn, use_pg=True, strict_history=True) == 0
        assert get_applied_records(conn) == after
    finally:
        conn.close()


def test_db019_schema_bootstrap_calls_strict_runner_and_preserves_v1():
    source = SCHEMA.read_text(encoding="utf-8")
    assert "run_migrations(conn, _USE_PG, strict_history=True)" in source
    data = _load()
    assert "prior_tracking_rows_and_V1_tables_remain_unchanged" in data["decision"]["invariants"]
    assert "required_tables_unchanged" in data["checks"]["upgrade"]
    assert "tracking_count_unchanged" in data["checks"]["repeat"]


def test_legacy_textfsm_migration_339_is_reconciled_before_applying_347(isolated_db):
    conn = get_db_connection()
    try:
        reference = get_applied_records(conn)
        conn.execute("ALTER TABLE ai_messages DROP COLUMN cached_tokens")
        conn.execute(
            "UPDATE schema_migrations SET name = ? WHERE version = 339",
            ("h3c_v7_bgp_vrf_route_command",),
        )
        conn.execute("DELETE FROM schema_migrations WHERE version = 347")
        conn.commit()

        plan = build_migration_plan(conn, use_pg=True)
        assert plan.safe
        assert plan.pending_versions == (339, 347)
        assert run_migrations(conn, use_pg=True, strict_history=True) == 2
        assert get_applied_records(conn) == reference
        assert conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
            "AND table_name = 'ai_messages' AND column_name = 'cached_tokens'"
        ).fetchone()
        assert run_migrations(conn, use_pg=True, strict_history=True) == 0
    finally:
        conn.close()


def test_db019_failure_drift_and_evidence_boundaries_are_explicit():
    data = _load()
    assert "module_exception_rolls_back_data" in data["checks"]["failure"]
    assert "unknown_version_or_name_drift_returns_zero" in data["checks"]["drift"]
    assert "production_database_mutation" in data["upgrade_fixture"]["forbidden"]
    assert "fake_vector_extension" in data["upgrade_fixture"]["forbidden"]
    assert "raw_document" in data["evidence"]["redaction"]
    assert "database_maintenance_identity" in data["security_and_governance"]["authorization"]
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("DB-019", "115", "114", "V2", "fresh", "upgrade", "idempot", "rollback", "schema_migrations", "DB-020", "MIG", "V1", "Final Conclusion: PASS"):
        assert marker in report, marker
