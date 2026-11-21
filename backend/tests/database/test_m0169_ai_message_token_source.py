def test_m0169_adds_token_source_column(isolated_db) -> None:
    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                ("ai_messages",),
            ).fetchall()
        }
    assert "token_source" in columns
