from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from database import get_db_connection
from database.capacity import (
    DEFAULTS,
    collect_postgres_relation_stats,
    estimate_scale,
    run_capacity_evaluation,
)


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-024-CAPACITY-BLOAT-INDEX-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-024-CAPACITY-BLOAT-INDEX-CONTRACT.md"


def _load() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_db024_contract_and_report_markers_are_frozen():
    data = _load()
    assert data["task_id"] == "DB-024"
    assert data["priority"] == "P2"
    assert data["status"] == "implemented_read_only_capacity_evaluation"
    assert [(item["documents"], item["chunks"]) for item in data["scenarios"]] == [(10000, 100000), (10000, 1000000)]
    assert data["assumptions"]["embedding_dimensions"] == 1536
    assert data["probe"]["write_operations"] == "forbidden"
    assert "production_probe_is_read_only_catalog_only" in data["decision"]["invariants"]
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("DB-024", "10,000", "100,000", "1,000,000", "pg_total_relation_size", "pg_indexes_size", "dead/live", "SQLite", "V1", "Final Conclusion: PASS"):
        assert marker in report, marker


def test_db024_scale_estimates_are_monotonic_and_explicit():
    hundred_k = estimate_scale(document_count=10_000, chunk_count=100_000)
    million = estimate_scale(document_count=10_000, chunk_count=1_000_000)
    assert hundred_k["status"] == "PASS"
    assert million["estimated_relation_bytes"] > hundred_k["estimated_relation_bytes"]
    assert million["raw_embedding_bytes"] > hundred_k["raw_embedding_bytes"]
    assert million["index_bytes"]["vector_index_estimate"] > hundred_k["index_bytes"]["vector_index_estimate"]
    assert set(DEFAULTS).issubset(million["assumptions"])
    assert million["assumption_warning"]


def test_db024_rejects_invalid_scale_inputs():
    with pytest.raises(ValueError):
        estimate_scale(document_count=-1, chunk_count=1)
    with pytest.raises(ValueError):
        estimate_scale(document_count=1, chunk_count=1, assumptions={"embedding_dimensions": 0})


def test_db024_sqlite_is_not_production_bloat_evidence_and_does_not_write():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ai_document (id TEXT PRIMARY KEY)")
    before = tuple(row[0] for row in conn.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall())
    stats = collect_postgres_relation_stats(conn, use_pg=False)
    report = run_capacity_evaluation(conn, use_pg=False)
    after = tuple(row[0] for row in conn.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall())
    try:
        assert stats["status"] == "NOT_APPLICABLE"
        assert report["read_only"] is True
        assert report["relation_stats"]["status"] == "NOT_APPLICABLE"
        assert report["no_synthetic_production_rows"] is True
        assert after == before
    finally:
        conn.close()


def test_db024_postgres_catalog_probe_is_read_only_and_safe(isolated_db):
    conn = get_db_connection()
    try:
        before = tuple(row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall())
        stats = collect_postgres_relation_stats(conn, use_pg=False)
        report = run_capacity_evaluation(conn, use_pg=False)
        assert stats["backend"] == "sqlite"
        assert report["backend"] == "sqlite"
        assert report["scenarios"][0]["document_count"] == 10_000
        assert report["scenarios"][1]["chunk_count"] == 1_000_000
        after = tuple(row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall())
        assert before == after
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    finally:
        conn.close()


def test_db024_local_postgres_probe_emits_only_relation_stats():
    import database.capacity as capacity
    import database

    if not database._USE_PG:
        pytest.skip("local test fixture is SQLite")
    conn = database.get_db_connection()
    try:
        report = run_capacity_evaluation(conn, use_pg=True)
        assert report["backend"] == "postgresql"
        assert report["read_only"] is True
        assert report["no_synthetic_production_rows"] is True
        assert "password" not in json.dumps(report).lower()
    finally:
        conn.close()
