from __future__ import annotations


def test_m0120_adds_tenant_scoped_append_only_refresh_observations(isolated_db):
    from database.migrations.m0120_knowledge_v2_source_freshness import upgrade

    conn = isolated_db["module"].get_db_connection()
    try:
        upgrade(conn.cursor(), False)
        conn.commit()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(kb_source_refresh_observation)").fetchall()}
        assert {"tenant_id", "source_registry_id", "source_version_id", "checked_at", "outcome", "content_hash", "source_etag", "source_last_modified", "error_json", "metadata_json"} <= columns
        indexes = {str(row[1]) for row in conn.execute("PRAGMA index_list(kb_source_refresh_observation)").fetchall()}
        assert "ix_kb_source_refresh_source_time" in indexes
        assert "ix_kb_source_refresh_outcome" in indexes
    finally:
        conn.close()


def test_m0120_is_idempotent_and_tracked(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        from database.migrations.m0120_knowledge_v2_source_freshness import upgrade

        upgrade(conn.cursor(), False)
        conn.commit()
        upgrade(conn.cursor(), False)
        conn.commit()
        assert conn.execute("SELECT name FROM schema_migrations WHERE version = 120").fetchone()[0] == "knowledge_v2_source_freshness"
    finally:
        conn.close()

