def test_m0167_creates_official_source_suggestion_table(isolated_db) -> None:
    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                ("official_source_suggestion",),
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = current_schema() AND tablename = ?",
                ("official_source_suggestion",),
            ).fetchall()
        }
    assert {"trace_id", "suggested_url", "status", "recheck_trace_id", "recheck_status"}.issubset(columns)
    assert "ix_official_source_suggestion_tenant_status" in indexes
