from __future__ import annotations

import sqlite3
import uuid

from database.migrations.m0105_ai_security_operations_graph import upgrade as upgrade_graph_base
from database.migrations import m0115_topology_graph_completion as migration
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


def test_protocol_action_seed_handles_legacy_deterministic_id_collision(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE action_definitions (
            action_code TEXT PRIMARY KEY, name_zh TEXT, name_en TEXT, purpose TEXT,
            risk_level TEXT, device_types_json TEXT, required_fields_json TEXT,
            optional_fields_json TEXT, field_types_json TEXT, max_output_bytes INTEGER,
            max_records INTEGER, timeout_seconds INTEGER, sensitive_level TEXT,
            consumers_json TEXT, read_only INTEGER, created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE platform_release_actions (
            id TEXT PRIMARY KEY, release_id TEXT NOT NULL, action_code TEXT NOT NULL,
            command TEXT NOT NULL, field_contract_json TEXT NOT NULL,
            command_checksum TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE (release_id, action_code)
        )"""
    )

    release_id = "system-release-test-v1"
    action_code = "get_stp"
    colliding_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:{release_id}:{action_code}"))
    conn.execute(
        """INSERT INTO platform_release_actions
           (id, release_id, action_code, command, field_contract_json, command_checksum, created_at, updated_at)
           VALUES (?, 'legacy-release', 'legacy-action', 'legacy', '{}', 'legacy', 'now', 'now')""",
        (colliding_id,),
    )

    import services.platform_registry_service as registry

    monkeypatch.setattr(registry, "SYSTEM_PROFILES", [{"platform_code": "test"}])
    monkeypatch.setattr(registry, "get_profile_action_commands", lambda _: {action_code: "show stp"})
    monkeypatch.setattr(
        registry,
        "iter_action_definitions",
        lambda: [{"action_code": action_code, "name_zh": "STP", "name_en": "STP"}],
    )

    migration._seed_protocol_actions(conn.cursor())
    migration._seed_protocol_actions(conn.cursor())

    seeded = conn.execute(
        "SELECT id, command FROM platform_release_actions WHERE release_id = ? AND action_code = ?",
        (release_id, action_code),
    ).fetchone()
    assert seeded[0] != colliding_id
    assert seeded[1] == "show stp"
    assert conn.execute("SELECT COUNT(*) FROM platform_release_actions").fetchone()[0] == 2
