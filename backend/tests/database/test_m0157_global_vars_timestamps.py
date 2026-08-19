import sqlite3

from database.migrations.m0157_global_vars_timestamps import upgrade


def test_m0157_adds_global_var_timestamps_idempotently():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE global_vars (
            id TEXT PRIMARY KEY,
            key TEXT UNIQUE,
            value TEXT
        )
        """
    )

    upgrade(conn, use_pg=False)
    upgrade(conn, use_pg=False)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(global_vars)")}
    conn.execute(
        "INSERT INTO global_vars (id, key, value, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("gv-1", "tftp_backup_settings", "{}", "now", "now"),
    )
    row = conn.execute(
        "SELECT created_at, updated_at FROM global_vars WHERE id = 'gv-1'"
    ).fetchone()
    conn.close()

    assert {"created_at", "updated_at"}.issubset(columns)
    assert row == ("now", "now")
