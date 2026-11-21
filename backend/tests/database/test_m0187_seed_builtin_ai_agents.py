from __future__ import annotations

import json

from database import get_db_connection
from database.migrations import m0187_seed_builtin_ai_agents as migration


def test_builtin_troubleshooting_agent_is_seeded_and_idempotent(isolated_db) -> None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, code, name, enabled, allowed_tools FROM ai_agent WHERE code = ?",
            ("troubleshooting_agent",),
        ).fetchone()
        assert row is not None
        assert row[0] == "agent_troubleshooting"
        assert row[2] == "网络排障 Agent"
        assert row[3] == 1
        assert "find_ip_location" in json.loads(row[4])

        conn.execute("DELETE FROM ai_agent WHERE code = ?", ("troubleshooting_agent",))
        migration.upgrade(conn.cursor(), use_pg=True)
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        rows = conn.execute(
            "SELECT id, code FROM ai_agent WHERE code = ?",
            ("troubleshooting_agent",),
        ).fetchall()
        assert [tuple(item) for item in rows] == [
            ("agent_troubleshooting", "troubleshooting_agent")
        ]
