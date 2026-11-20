from backend.tests import pg_catalog_assertions as pg_catalog
def test_change_order_incident_link_migration_is_idempotent_on_postgresql() -> None:
    from backend.tests.pg_test_utils import postgresql_test_driver
    from database.migrations.m0063_change_order_incident_link import upgrade

    conn = postgresql_test_driver.connect()
    try:
        conn.execute("CREATE TABLE change_orders (id TEXT PRIMARY KEY, title TEXT NOT NULL)")
        upgrade(conn.cursor(), use_pg=True)
        upgrade(conn.cursor(), use_pg=True)
        columns = pg_catalog.table_columns(conn, "change_orders")
        indexes = pg_catalog.index_names(conn, "change_orders")
    finally:
        conn.close()

    assert "incident_id" in columns
    assert "idx_change_orders_incident_id" in indexes
