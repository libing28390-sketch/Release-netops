from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0051_config_drift_baselines import upgrade


def test_baseline_migration_is_idempotent() -> None:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
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
        upgrade(conn, use_pg=True)
        upgrade(conn, use_pg=True)
        columns = pg_catalog.table_columns(conn, "config_drift_results")
        indexes = pg_catalog.index_names(conn, "config_baselines")
    finally:
        conn.close()

    assert {"baseline_source", "diff_mode"}.issubset(columns)
    assert "idx_config_baselines_snapshot" in indexes
