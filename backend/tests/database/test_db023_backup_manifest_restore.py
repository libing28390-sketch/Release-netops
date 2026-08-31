from __future__ import annotations

import json
from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from pathlib import Path

import pytest
import yaml

from database import get_db_connection
from database.backup import MANIFEST_FORMAT, build_postgres_backup_plan, export_source_manifest


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-023-BACKUP-MANIFEST-RESTORE-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-023-BACKUP-MANIFEST-RESTORE-CONTRACT.md"
BACKUP_SCRIPT = ROOT / "scripts" / "install-daily-backup.sh"


def _load() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _source_db(path: Path) -> postgresql_test_driver.Connection:
    conn = postgresql_test_driver.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL);
        INSERT INTO schema_migrations VALUES (115, 'topology_graph_completion', '2026-08-09T00:00:00+00:00');
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            name TEXT,
            source TEXT,
            vendor TEXT,
            platform TEXT,
            version TEXT,
            status TEXT,
            tenant_id TEXT,
            knowledge_source_type TEXT,
            source_trust_level TEXT,
            content_hash TEXT,
            original_content TEXT,
            normalized_content TEXT,
            metadata_json TEXT,
            updated_at TEXT
        );
        CREATE TABLE ai_document_chunk (id TEXT PRIMARY KEY, document_id TEXT, content TEXT);
        INSERT INTO ai_document VALUES
          ('doc-secret-id', 'external-1', 'Private Runbook Name', 'https://internal.example/runbook', 'H3C', 'h3c_comware', '7.0', 'active', 'tenant-a', 'user_document', 'internal', NULL, 'RAW SECRET DOCUMENT BODY', '# Heading', '{"path":"private/path"}', '2026-08-09T00:00:00+00:00');
        INSERT INTO ai_document_chunk VALUES ('chunk-1', 'doc-secret-id', 'RAW SECRET DOCUMENT BODY');
        """
    )
    conn.commit()
    return conn


def test_db023_contract_and_report_markers_are_frozen():
    data = _load()
    assert data["task_id"] == "DB-023"
    assert data["priority"] == "P1"
    assert data["status"] == "implemented_backup_restore_rehearsal"
    assert data["backup"]["postgres"]["credential_source"] == "DATABASE_URL_environment_only"
    assert data["manifest"]["digest"] == "sha256_canonical_sorted_records"
    assert "restore_rehearsal_is_isolated_and_never_targets_production" in data["decision"]["invariants"]
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("DB-023", "pg_dump", "Source Manifest", "SHA-256", "integrity_check", "pg_restore", "production", "V1", "Final Conclusion: PASS"):
        assert marker in report, marker
    script = BACKUP_SCRIPT.read_text(encoding="utf-8")
    for marker in ("source-manifest.json", "database.backup manifest", "source manifest export failed", "DATABASE_URL"):
        assert marker in script, marker


def test_db023_manifest_is_redacted_and_digest_is_deterministic(tmp_path):
    source = tmp_path / "source.db"
    conn = _source_db(source)
    try:
        first = export_source_manifest(conn=conn)
        second = export_source_manifest(conn=conn)
        assert first["format"] == MANIFEST_FORMAT
        assert first["schema_version"] == 115
        assert first["document_count"] == 1
        assert first["chunk_count"] == 1
        assert first["source_manifest_digest"] == second["source_manifest_digest"]
        serialized = json.dumps(first, ensure_ascii=False)
        for raw in ("doc-secret-id", "Private Runbook Name", "https://internal.example/runbook", "RAW SECRET DOCUMENT BODY", "private/path", "tenant-a"):
            assert raw not in serialized
        record = first["documents"][0]
        assert set(record) >= {"document_key_hash", "source_ref_hash", "content_hash", "metadata_hash", "tenant_hash"}
        assert all(len(str(record[key])) >= 16 for key in ("document_key_hash", "source_ref_hash", "content_hash", "metadata_hash"))
        filtered = export_source_manifest(conn=conn, tenant_id="tenant-a")
        assert filtered["document_count"] == 1
        assert filtered["tenant_scope"] == "filtered"
    finally:
        conn.close()


def test_db023_postgres_plan_is_credential_free_and_restore_isolated(tmp_path):
    plan = build_postgres_backup_plan(
        backup_path=tmp_path / "netops.dump",
        manifest_path=tmp_path / "netops.manifest.json",
    )
    serialized = json.dumps(plan, ensure_ascii=False)
    assert plan["backend"] == "postgresql"
    assert plan["secrets_in_plan"] is False
    assert "${DATABASE_URL}" in serialized
    assert "${REHEARSAL_DATABASE_URL}" in serialized
    assert "password" not in serialized.lower()
    assert plan["restore_rehearsal"]["production_restore"] == "forbidden_by_DB-023_cli"


def test_db023_v1_isolated_schema_and_manifest_export_are_non_mutating(isolated_db, tmp_path):
    conn = get_db_connection()
    try:
        before = tuple(sorted(pg_catalog.table_names(conn)))
        manifest_path = tmp_path / "v1-manifest.json"
        manifest = export_source_manifest(conn=conn, output_path=manifest_path)
        assert manifest_path.is_file()
        current_version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        assert manifest["schema_version"] == current_version
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == current_version
        after = tuple(sorted(pg_catalog.table_names(conn)))
        assert after == before
        assert "devices" in after and "ai_document" in after
    finally:
        conn.close()
