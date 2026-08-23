def test_m0167_creates_official_source_suggestion_table(isolated_db) -> None:
    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(official_source_suggestion)").fetchall()}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(official_source_suggestion)").fetchall()}
    assert {"trace_id", "suggested_url", "status", "recheck_trace_id", "recheck_status"}.issubset(columns)
    assert "ix_official_source_suggestion_tenant_status" in indexes
