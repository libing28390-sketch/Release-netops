from __future__ import annotations

from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations import m0192_knowledge_v1_current_version_projection as migration


def test_m0192_adds_and_backfills_current_version_pointer():
    conn = postgresql_test_driver.connect()
    try:
        conn.executescript(
            """
            CREATE TABLE ai_document (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL
            );
            CREATE TABLE ai_document_revision (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                revision_no INTEGER NOT NULL,
                record_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO ai_document (id, tenant_id, name) VALUES ('doc-1', 'tenant-1', 'Guide');
            INSERT INTO ai_document_revision
                (id, tenant_id, document_id, revision_no, record_type, created_at)
            VALUES
                ('rev-1', 'tenant-1', 'doc-1', 1, 'document_revision', '2026-01-01'),
                ('rev-2', 'tenant-1', 'doc-1', 2, 'document_revision', '2026-01-02'),
                ('obs-1', 'tenant-1', 'doc-1', 3, 'source_observation', '2026-01-03');
            """
        )
        migration.upgrade(conn.cursor(), use_pg=True)
        migration.upgrade(conn.cursor(), use_pg=True)
        assert conn.execute(
            "SELECT current_version_id FROM ai_document WHERE id = 'doc-1'"
        ).fetchone()[0] == "rev-2"
    finally:
        conn.close()
