import sqlite3

from database.migrations.m0046_arp_collection_resilience import upgrade
from database.migrations.m0047_collector_sweep_state import upgrade as upgrade_sweep_state


def test_arp_resilience_migration_is_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE device_collection_status (
            device_id TEXT NOT NULL,
            collector TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'unknown',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (device_id, collector)
        )
        """
    )
    try:
        upgrade(conn.cursor(), use_pg=False)
        upgrade(conn.cursor(), use_pg=False)
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(device_collection_status)").fetchall()
        }
        assert {"next_retry_at", "failure_class", "circuit_state", "last_failure_at"} <= columns
    finally:
        conn.close()


def test_collector_sweep_state_migration_is_idempotent():
    conn = sqlite3.connect(":memory:")
    try:
        upgrade_sweep_state(conn.cursor(), use_pg=False)
        upgrade_sweep_state(conn.cursor(), use_pg=False)
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(collector_sweep_state)").fetchall()
        }
        assert {
            "collector", "cursor_position", "last_run_id", "last_started_at",
            "last_completed_at", "last_eligible", "last_selected",
            "last_batch_size", "last_successful", "last_failed",
            "last_collected", "updated_at",
        } <= columns
    finally:
        conn.close()
