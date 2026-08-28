from __future__ import annotations


def test_m0118_creates_idempotent_source_observation_boundary(isolated_db):
    from database.migrations.m0118_knowledge_v2_document_sources import upgrade

    conn = isolated_db["module"].get_db_connection()
    try:
        upgrade(conn.cursor(), True)
        conn.commit()
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                ("kb_document_source",),
            ).fetchall()
        }
        assert {
            "tenant_id", "document_id", "document_version_id", "source_registry_id",
            "source_version_id", "canonical_url", "content_hash", "observation_count",
        } <= columns
        assert conn.execute("SELECT name FROM schema_migrations WHERE version = 118").fetchone()[0] == "knowledge_v2_document_sources"
    finally:
        conn.close()


def test_m0118_has_tenant_and_source_version_unique_guards(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        index_names = {
            str(row[0])
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = current_schema() AND tablename = ?",
                ("kb_document_source",),
            ).fetchall()
        }
        assert any("source_version" in name for name in index_names)
        assert any("document_version" in name for name in index_names)
        assert "ix_kb_document_source_hash" in index_names
    finally:
        conn.close()

