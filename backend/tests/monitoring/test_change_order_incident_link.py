def test_change_order_incident_link_migration_is_idempotent_on_sqlite_compatibility_path() -> None:
    import sqlite3

    from database.migrations.m0063_change_order_incident_link import upgrade

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE change_orders (id TEXT PRIMARY KEY, title TEXT NOT NULL)")
        upgrade(conn, use_pg=False)
        upgrade(conn, use_pg=False)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(change_orders)")}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(change_orders)")}
    finally:
        conn.close()

    assert "incident_id" in columns
    assert "idx_change_orders_incident_id" in indexes
