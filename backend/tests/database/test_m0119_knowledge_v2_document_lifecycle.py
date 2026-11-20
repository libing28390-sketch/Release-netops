from __future__ import annotations

from backend.tests import pg_catalog_assertions as pg_catalog


def test_m0119_lifecycle_state_is_projected_to_v1_documents_and_revisions(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        assert not pg_catalog.table_exists(conn, "kb_document_lifecycle_event")
        document_columns = pg_catalog.table_columns(conn, "ai_document")
        assert {
            "lifecycle_status",
            "lifecycle_revision",
            "lifecycle_reason",
            "current_version_id",
        } <= document_columns
        revision_columns = pg_catalog.table_columns(conn, "ai_document_revision")
        assert {"record_type", "lifecycle_status", "lifecycle_reason"} <= revision_columns
        applied = conn.execute(
            "SELECT name FROM schema_migrations WHERE version = 119"
        ).fetchone()
        assert applied[0] == "knowledge_v2_document_lifecycle"
    finally:
        conn.close()


def test_m0119_final_lifecycle_projection_has_no_retired_event_boundary(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 119"
        ).fetchone()[0] == 1
        assert not pg_catalog.table_exists(conn, "kb_document_lifecycle_event")
        assert not pg_catalog.table_exists(conn, "kb_document")
        assert "ix_ai_document_revision_document" in pg_catalog.index_names(
            conn, "ai_document_revision"
        )
    finally:
        conn.close()
