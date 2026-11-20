from __future__ import annotations

from backend.tests import pg_catalog_assertions as pg_catalog


def test_m0118_history_is_projected_into_v1_source_observation_columns(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        assert not pg_catalog.table_exists(conn, "kb_document_source")
        columns = pg_catalog.table_columns(conn, "ai_document_revision")
        assert {
            "record_type",
            "observation_outcome",
            "checked_at",
            "source_observation_id",
            "source_etag",
            "source_last_modified",
            "fetch_metadata_json",
        } <= columns
        applied = conn.execute(
            "SELECT name FROM schema_migrations WHERE version = 118"
        ).fetchone()
        assert applied[0] == "knowledge_v2_document_sources"
    finally:
        conn.close()


def test_m0118_final_observation_indexes_are_tenant_scoped_and_replay_safe(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        index_names = pg_catalog.index_names(conn, "ai_document_revision")
        assert "ix_ai_document_revision_observation" in index_names
        assert "ux_ai_document_revision_source_observation" in index_names
        assert "ix_ai_document_revision_source" in index_names
        assert not pg_catalog.table_exists(conn, "kb_document_source")
    finally:
        conn.close()
