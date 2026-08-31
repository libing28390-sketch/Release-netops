from __future__ import annotations

from backend.tests import pg_catalog_assertions as pg_catalog

from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0105_ai_security_operations_graph import upgrade


def test_security_operations_graph_migration_is_idempotent_on_postgresql():
    conn = postgresql_test_driver.connect()
    conn.execute("CREATE TABLE alert_events (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE pam_sessions (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE ai_model (model_code TEXT, name TEXT, thinking_supported INTEGER)")
    upgrade(conn.cursor(), True)
    conn.commit()
    # DDL and seed operations must be safe to run again during an interrupted
    # bootstrap/retry.
    upgrade(conn.cursor(), True)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM ai_model_capabilities").fetchone()[0] == 2
    assert "pending_since" in pg_catalog.table_columns(conn, "alert_events")
    assert conn.execute("SELECT enabled FROM ai_kill_switch WHERE id = 1").fetchone()[0] == 0

