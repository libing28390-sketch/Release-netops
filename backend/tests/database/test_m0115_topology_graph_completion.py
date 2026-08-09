from __future__ import annotations

import sqlite3

from database.migrations.m0105_ai_security_operations_graph import upgrade as upgrade_graph_base
from database.migrations.m0115_topology_graph_completion import upgrade


def test_topology_graph_completion_migration_is_idempotent_and_additive():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE alert_events (id TEXT)")
    conn.execute("CREATE TABLE pam_sessions (id TEXT)")
    conn.execute("CREATE TABLE ai_model (model_code TEXT, name TEXT, thinking_supported INTEGER)")
    upgrade_graph_base(conn.cursor(), False)
    upgrade(conn.cursor(), False)
    upgrade(conn.cursor(), False)
    conn.commit()

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    assert {
        "topology_protocol_observations", "topology_relations", "topology_groups",
        "topology_group_members", "topology_history", "topology_edge_history",
    } <= tables
    edge_columns = {row[1] for row in conn.execute("PRAGMA table_info(topology_edges)").fetchall()}
    evidence_columns = {row[1] for row in conn.execute("PRAGMA table_info(topology_edge_evidence)").fetchall()}
    assert {"manual_confirmed", "semantic_relation", "rank_excluded"} <= edge_columns
    assert {"evidence_type", "source_device_id", "first_seen", "last_seen", "collector"} <= evidence_columns

