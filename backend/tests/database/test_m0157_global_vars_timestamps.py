from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0157_global_vars_timestamps import upgrade


def test_m0157_adds_global_var_timestamps_idempotently():
    conn = postgresql_test_driver.connect()
    conn.execute(
        """
        CREATE TABLE global_vars (
            id TEXT PRIMARY KEY,
            key TEXT UNIQUE,
            value TEXT
        )
        """
    )

    upgrade(conn, use_pg=True)
    upgrade(conn, use_pg=True)

    columns = pg_catalog.table_columns(conn, "global_vars")
    conn.execute(
        "INSERT INTO global_vars (id, key, value, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("gv-1", "tftp_backup_settings", "{}", "now", "now"),
    )
    row = conn.execute(
        "SELECT created_at, updated_at FROM global_vars WHERE id = 'gv-1'"
    ).fetchone()
    conn.close()

    assert {"created_at", "updated_at"}.issubset(columns)
    assert tuple(row) == ("now", "now")
