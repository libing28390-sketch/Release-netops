def test_m0209_creates_uat_signoff_tables_and_indexes(isolated_db) -> None:
    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        signoff_columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                ("ai_uat_case_signoffs",),
            ).fetchall()
        }
        event_columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                ("ai_uat_case_signoff_events",),
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = current_schema() AND tablename IN (?, ?)",
                ("ai_uat_case_signoffs", "ai_uat_case_signoff_events"),
            ).fetchall()
        }

    assert {"tenant_id", "campaign_id", "case_id", "status", "reviewer_id", "signed_at"}.issubset(signoff_columns)
    assert {"previous_status", "new_status", "reviewer_id", "created_at"}.issubset(event_columns)
    assert "ix_ai_uat_case_signoffs_tenant_campaign" in indexes
    assert "ix_ai_uat_case_signoff_events_case" in indexes
