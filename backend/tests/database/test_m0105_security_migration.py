from __future__ import annotations

import sqlite3

from database.migrations.m0105_ai_security_operations_graph import upgrade


def test_security_operations_graph_migration_is_idempotent_on_sqlite():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE alert_events (id TEXT)")
    conn.execute("CREATE TABLE pam_sessions (id TEXT)")
    conn.execute("CREATE TABLE ai_model (model_code TEXT, name TEXT, thinking_supported INTEGER)")
    upgrade(conn.cursor(), False)
    conn.commit()
    # DDL and seed operations must be safe to run again during an interrupted
    # bootstrap/retry.
    upgrade(conn.cursor(), False)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM ai_model_capabilities").fetchone()[0] == 2
    assert "pending_since" in {
        row[1] for row in conn.execute("PRAGMA table_info(alert_events)").fetchall()
    }
    assert conn.execute("SELECT enabled FROM ai_kill_switch WHERE id = 1").fetchone()[0] == 0

