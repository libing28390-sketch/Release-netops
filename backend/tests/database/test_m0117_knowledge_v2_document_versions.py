from __future__ import annotations

from backend.tests import pg_catalog_assertions as pg_catalog


def test_m0117_history_is_preserved_while_v1_revision_is_authoritative(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        # m0191 is the destructive boundary: the historical migration remains
        # auditable, but its retired shadow tables must not be recreated.
        assert not pg_catalog.table_exists(conn, "kb_document")
        assert not pg_catalog.table_exists(conn, "kb_document_version")

        revision_columns = pg_catalog.table_columns(conn, "ai_document_revision")
        assert {
            "id",
            "tenant_id",
            "document_id",
            "revision_no",
            "content_hash",
            "original_content",
            "normalized_content",
            "metadata_json",
            "created_at",
            "legacy_document_version_id",
        } <= revision_columns

        applied = conn.execute(
            "SELECT name FROM schema_migrations WHERE version = 117"
        ).fetchone()
        assert applied[0] == "knowledge_v2_document_versions"
    finally:
        conn.close()


def test_m0117_final_revision_identity_indexes_replace_retired_fact_guard(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        indexes = pg_catalog.index_names(conn, "ai_document_revision")
        assert "ux_ai_document_revision_content" in indexes
        assert "ix_ai_document_revision_hash" in indexes
        assert not pg_catalog.table_exists(conn, "kb_source_version")
        assert not pg_catalog.table_exists(conn, "kb_source_registry")

        guard = conn.execute(
            "SELECT 1 FROM pg_proc WHERE proname = ? LIMIT 1",
            ("kb_document_version_fact_immutable_guard",),
        ).fetchone()
        assert guard is None
    finally:
        conn.close()
