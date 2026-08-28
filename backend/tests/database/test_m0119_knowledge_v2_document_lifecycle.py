from __future__ import annotations


def test_m0119_adds_lifecycle_projection_and_event_boundary(isolated_db):
    from database.migrations.m0119_knowledge_v2_document_lifecycle import upgrade

    conn = isolated_db["module"].get_db_connection()
    try:
        upgrade(conn.cursor(), True)
        conn.commit()
        for table in ("kb_document", "kb_document_version"):
            columns = {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = ?",
                    (table,),
                ).fetchall()
            }
            assert {"lifecycle_status", "lifecycle_revision", "lifecycle_reason", "published_at", "quarantined_at", "superseded_by_version_id", "disabled_at"} <= columns
        event_columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                ("kb_document_lifecycle_event",),
            ).fetchall()
        }
        assert {"tenant_id", "document_id", "document_version_id", "request_id", "from_status", "to_status", "result_json"} <= event_columns
        assert conn.execute("SELECT name FROM schema_migrations WHERE version = 119").fetchone()[0] == "knowledge_v2_document_lifecycle"
    finally:
        conn.close()


def test_m0119_is_idempotent_and_indexes_are_tenant_scoped(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        from database.migrations.m0119_knowledge_v2_document_lifecycle import upgrade

        upgrade(conn.cursor(), True)
        conn.commit()
        upgrade(conn.cursor(), True)
        conn.commit()
        index_names = {
            str(row[0])
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = current_schema() AND tablename = ?",
                ("kb_document_lifecycle_event",),
            ).fetchall()
        }
        assert "ix_kb_document_lifecycle_event_document" in index_names
        assert "ix_kb_document_lifecycle_event_version" in index_names
    finally:
        conn.close()

