from __future__ import annotations

from backend.tests import pg_catalog_assertions as pg_catalog


def test_m0120_refresh_evidence_is_projected_to_v1_observations(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        assert not pg_catalog.table_exists(conn, "kb_source_refresh_observation")
        columns = pg_catalog.table_columns(conn, "ai_document_revision")
        assert {
            "record_type",
            "source_observation_id",
            "checked_at",
            "observation_outcome",
            "detection_type",
            "error_code",
            "replacement_url",
            "request_method",
        } <= columns
        indexes = pg_catalog.index_names(conn, "ai_document_revision")
        assert "ix_ai_document_revision_observation" in indexes
        assert "ux_ai_document_revision_source_observation" in indexes
    finally:
        conn.close()


def test_m0120_history_is_tracked_without_recreating_refresh_tables(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        assert conn.execute(
            "SELECT name FROM schema_migrations WHERE version = 120"
        ).fetchone()[0] == "knowledge_v2_source_freshness"
        assert conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 120"
        ).fetchone()[0] == 1
        assert not pg_catalog.table_exists(conn, "kb_source_refresh_observation")
    finally:
        conn.close()
