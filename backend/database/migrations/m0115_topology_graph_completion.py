"""Complete the evidence-first topology graph and asset semantic model.

The original graph migration introduced the read model, but left protocol
observations, relation metadata, group membership, and history as implicit
JSON.  This migration makes those boundaries durable and keeps the upgrade
safe for installations that already contain LLDP and asset data.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone


VERSION = 115
NAME = "topology_graph_completion"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}


def _ensure_columns(cursor, table: str, definitions: dict[str, str], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    if not existing:
        return
    for name, definition in definitions.items():
        if name.lower() not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _create_graph_tables(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS topology_protocol_observations (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            discovery_run_id TEXT,
            source_device_id TEXT NOT NULL,
            target_device_id TEXT,
            target_identity TEXT DEFAULT '',
            target_ip TEXT DEFAULT '',
            source_interface TEXT DEFAULT '',
            target_interface TEXT DEFAULT '',
            protocol TEXT NOT NULL,
            relation_type TEXT NOT NULL DEFAULT 'UNKNOWN',
            direction TEXT NOT NULL DEFAULT 'undirected',
            observation_json TEXT NOT NULL DEFAULT '{}',
            confidence REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS topology_relations (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            edge_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            semantic_relation TEXT NOT NULL DEFAULT '',
            direction TEXT NOT NULL DEFAULT 'undirected',
            existence_confidence REAL NOT NULL DEFAULT 0,
            semantic_confidence REAL NOT NULL DEFAULT 0,
            rank_excluded INTEGER NOT NULL DEFAULT 0,
            is_manual INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            first_seen TEXT,
            last_seen TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, edge_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS topology_groups (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            node_id TEXT NOT NULL,
            group_type TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            first_seen TEXT,
            last_seen TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, node_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS topology_group_members (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            group_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            member_role TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            first_seen TEXT,
            last_seen TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, group_id, node_id),
            FOREIGN KEY (group_id) REFERENCES topology_groups(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS topology_history (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            source TEXT NOT NULL DEFAULT 'system',
            actor TEXT NOT NULL DEFAULT 'system',
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS topology_edge_history (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            edge_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            source TEXT NOT NULL DEFAULT 'system',
            actor TEXT NOT NULL DEFAULT 'system',
            created_at TEXT NOT NULL,
            FOREIGN KEY (edge_id) REFERENCES topology_edges(id) ON DELETE CASCADE
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_topology_protocol_obs_source ON topology_protocol_observations(source_device_id, is_active, last_seen)",
        "CREATE INDEX IF NOT EXISTS ix_topology_protocol_obs_target ON topology_protocol_observations(target_device_id, protocol, is_active)",
        "CREATE INDEX IF NOT EXISTS ix_topology_protocol_obs_protocol ON topology_protocol_observations(protocol, relation_type, last_seen)",
        "CREATE INDEX IF NOT EXISTS ix_topology_relations_type ON topology_relations(tenant_id, relation_type, status)",
        "CREATE INDEX IF NOT EXISTS ix_topology_group_members_group ON topology_group_members(group_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_topology_history_entity ON topology_history(tenant_id, entity_type, entity_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_topology_history_event ON topology_history(tenant_id, event_type, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_topology_edge_history_edge ON topology_edge_history(tenant_id, edge_id, created_at)",
    ):
        cursor.execute(statement)


def _seed_protocol_actions(cursor) -> None:
    """Backfill topology actions into published system releases.

    Aggregation is part of the topology read model. Including it here also
    repairs installations that stopped at this migration before the registry
    action was persisted for a concrete H3C profile.
    """
    try:
        from services.platform_registry_service import (
            SYSTEM_PROFILES,
            get_profile_action_commands,
            iter_action_definitions,
        )
    except Exception:
        return

    # The migration is also used by isolated schema tests and rolling upgrades.
    # Probe metadata first so a missing optional seed table cannot abort the
    # PostgreSQL transaction that created the graph tables.
    if not _columns(cursor, "action_definitions", True):
        return
    if not _columns(cursor, "platform_release_actions", True):
        return

    now = _now()
    actions = {
        item.get("action_code"): item
        for item in iter_action_definitions()
        if item.get("action_code") in {"get_link_aggregation", "get_stp", "get_isis_neighbors"}
    }
    for action_code, action in actions.items():
        cursor.execute(
            """
            INSERT INTO action_definitions (
                action_code, name_zh, name_en, purpose, risk_level,
                device_types_json, required_fields_json, optional_fields_json,
                field_types_json, max_output_bytes, max_records, timeout_seconds,
                sensitive_level, consumers_json, read_only, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(action_code) DO UPDATE SET
                name_zh = excluded.name_zh,
                name_en = excluded.name_en,
                purpose = excluded.purpose,
                risk_level = excluded.risk_level,
                optional_fields_json = excluded.optional_fields_json,
                field_types_json = excluded.field_types_json,
                max_records = excluded.max_records,
                timeout_seconds = excluded.timeout_seconds,
                consumers_json = excluded.consumers_json
            """,
            (
                action_code, action["name_zh"], action["name_en"],
                action.get("purpose", ""), action.get("risk", "low"),
                json.dumps(action.get("device_types") or [], ensure_ascii=False),
                json.dumps(action.get("fields") or [], ensure_ascii=False),
                json.dumps(action.get("optional_fields") or [], ensure_ascii=False),
                json.dumps(action.get("field_types") or {}, ensure_ascii=False),
                2_000_000, int(action.get("max_records") or 1000),
                int(action.get("timeout_seconds") or 30),
                "normal", json.dumps(action.get("consumers") or [], ensure_ascii=False), now,
            ),
        )
    for profile in SYSTEM_PROFILES:
        profile_code = str(profile.get("platform_code") or "")
        if not profile_code:
            continue
        release_id = f"system-release-{profile_code}-v1"
        for action_code in actions:
            command = get_profile_action_commands(profile).get(action_code)
            if not command:
                continue
            action_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:{release_id}:{action_code}"))
            checksum = hashlib.sha256(command.encode("utf-8")).hexdigest()
            existing = cursor.execute(
                "SELECT id FROM platform_release_actions WHERE release_id = ? AND action_code = ?",
                (release_id, action_code),
            ).fetchone()
            if existing:
                cursor.execute(
                    """UPDATE platform_release_actions
                       SET command = ?, command_checksum = ?, updated_at = ?
                       WHERE id = ?""",
                    (command, checksum, now, existing[0]),
                )
                continue

            # Earlier seed migrations use the same deterministic UUID scheme.
            # A legacy row can therefore own this ID under a different natural
            # key.  Preserve that row and assign this new action a fresh ID.
            id_owner = cursor.execute(
                "SELECT 1 FROM platform_release_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
            if id_owner:
                action_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO platform_release_actions (
                    id, release_id, action_code, command, field_contract_json,
                    command_checksum, created_at, updated_at
                ) VALUES (?, ?, ?, ?, '{}', ?, ?, ?)
                ON CONFLICT(release_id, action_code) DO UPDATE SET
                    command = excluded.command,
                    command_checksum = excluded.command_checksum,
                    updated_at = excluded.updated_at
                """,
                (action_id, release_id, action_code, command, checksum, now, now),
            )


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_columns(
        cursor,
        "physical_assets",
        {
            "function": "TEXT DEFAULT ''",
            "zone": "TEXT DEFAULT 'Unknown'",
        },
        use_pg,
    )
    _ensure_columns(
        cursor,
        "devices",
        {
            "function": "TEXT DEFAULT ''",
            "zone": "TEXT DEFAULT 'Unknown'",
        },
        use_pg,
    )
    _ensure_columns(
        cursor,
        "topology_edges",
        {
            "manual_confirmed": "INTEGER NOT NULL DEFAULT 0",
            "semantic_relation": "TEXT DEFAULT ''",
            "rank_excluded": "INTEGER NOT NULL DEFAULT 0",
        },
        use_pg,
    )
    _ensure_columns(
        cursor,
        "topology_edge_evidence",
        {
            "evidence_type": "TEXT DEFAULT ''",
            "source_device_id": "TEXT DEFAULT ''",
            "source_interface": "TEXT DEFAULT ''",
            "first_seen": "TEXT",
            "last_seen": "TEXT",
            "collector": "TEXT DEFAULT ''",
        },
        use_pg,
    )
    _create_graph_tables(cursor)
    _seed_protocol_actions(cursor)


def downgrade(cursor, use_pg: bool) -> None:
    # The application keeps historical graph facts by design.  Downgrade is
    # intentionally a no-op so a migration rollback cannot destroy evidence.
    return None
