def test_m0169_adds_token_source_column(isolated_db) -> None:
    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_messages)").fetchall()}
    assert "token_source" in columns
