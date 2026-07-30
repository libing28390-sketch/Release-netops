import sqlite3

from database.migrations.m0051_config_drift_baselines import upgrade


def test_baseline_migration_is_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE config_drift_results (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            checked_at TEXT NOT NULL
        )
        """
    )
    try:
        upgrade(conn, use_pg=False)
        upgrade(conn, use_pg=False)
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(config_drift_results)")
        }
        indexes = {
            row["name"] for row in conn.execute("PRAGMA index_list(config_baselines)")
        }
    finally:
        conn.close()

    assert {"baseline_source", "diff_mode"}.issubset(columns)
    assert "idx_config_baselines_snapshot" in indexes
