from __future__ import annotations

from backend.tests import pg_catalog_assertions as pg_catalog


def test_m0191_fresh_install_leaves_only_the_v1_knowledge_projection(isolated_db):
    from database import get_db_connection

    retired_tables = (
        "kb_source_registry",
        "kb_source_version",
        "kb_document",
        "kb_document_version",
        "kb_document_source",
        "kb_document_lifecycle_event",
        "kb_source_refresh_observation",
        "kb_source_change_action",
        "kb_site_anomaly_alert",
        "ai_retrieval_index_shadow_chunk",
        "ai_retrieval_index_generation",
        "ai_retrieval_rollout_flag",
    )
    conn = get_db_connection()
    try:
        for table in retired_tables:
            assert not pg_catalog.table_exists(conn, table), table
        assert pg_catalog.table_exists(conn, "ai_document_revision")
        columns = pg_catalog.table_columns(conn, "ai_document")
        assert "current_version_id" in columns
        applied = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT version, name FROM schema_migrations WHERE version IN (191, 192)"
            ).fetchall()
        }
    finally:
        conn.close()
    assert applied == {
        191: "knowledge_v1_finalize_cleanup",
        192: "knowledge_v1_current_version_projection",
    }


def test_m0191_replay_is_idempotent_after_retired_schema_is_gone(isolated_db):
    from database import get_db_connection
    from database.migrations import m0191_knowledge_v1_finalize_cleanup as migration

    conn = get_db_connection()
    try:
        before = {
            "documents": conn.execute("SELECT COUNT(*) FROM ai_document").fetchone()[0],
            "chunks": conn.execute("SELECT COUNT(*) FROM ai_document_chunk").fetchone()[0],
            "revisions": conn.execute("SELECT COUNT(*) FROM ai_document_revision").fetchone()[0],
        }
        migration.upgrade(conn.cursor(), use_pg=True)
        migration.upgrade(conn.cursor(), use_pg=True)
        after = {
            "documents": conn.execute("SELECT COUNT(*) FROM ai_document").fetchone()[0],
            "chunks": conn.execute("SELECT COUNT(*) FROM ai_document_chunk").fetchone()[0],
            "revisions": conn.execute("SELECT COUNT(*) FROM ai_document_revision").fetchone()[0],
        }
    finally:
        conn.close()
    assert after == before
