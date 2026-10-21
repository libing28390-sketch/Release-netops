"""Add automatic prefix discovery, evidence, classification, and aging fields."""

from __future__ import annotations


VERSION = 32
NAME = "prefix_discovery_evidence"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    )
    return {row[0] for row in cursor.fetchall()}



def _ensure_columns(cursor, table: str, definitions: list[tuple[str, str]], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    for name, definition in definitions:
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_columns(
        cursor,
        "prefixes",
        [
            ("classification_status", "TEXT DEFAULT 'auto'"),
            ("classification_source", "TEXT DEFAULT 'auto'"),
            ("classification_confidence", "REAL DEFAULT 0"),
            ("classification_rule_version", "TEXT DEFAULT 'prefix-classification-v1'"),
            ("manual_override", "INTEGER DEFAULT 0"),
            ("manual_network_type", "TEXT DEFAULT ''"),
            ("mixed_network", "INTEGER DEFAULT 0"),
            ("address_roles_json", "TEXT DEFAULT '[]'"),
            ("discovered_devices_json", "TEXT DEFAULT '[]'"),
            ("observed_interfaces_json", "TEXT DEFAULT '[]'"),
            ("observed_vlans_json", "TEXT DEFAULT '[]'"),
            ("observed_vrfs_json", "TEXT DEFAULT '[]'"),
            ("evidence_json", "TEXT DEFAULT '[]'"),
            ("candidate_scores_json", "TEXT DEFAULT '{}'"),
            ("conflict_status", "TEXT DEFAULT ''"),
            ("conflict_json", "TEXT DEFAULT '{}'"),
            ("first_seen_at", "TEXT"),
            ("last_seen_at", "TEXT"),
            ("miss_count", "INTEGER DEFAULT 0"),
            ("is_active", "INTEGER DEFAULT 1"),
        ],
        use_pg,
    )
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prefix_observations (
            id TEXT PRIMARY KEY, prefix_id TEXT NOT NULL, collection_run_id TEXT NOT NULL,
            source_device_id TEXT DEFAULT '', source_type TEXT NOT NULL, observed_value TEXT NOT NULL,
            evidence_json TEXT DEFAULT '{}', confidence REAL DEFAULT 0,
            first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
            miss_count INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1
        )
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_prefix_observation_identity ON prefix_observations(prefix_id, source_device_id, source_type, observed_value)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prefix_observations_active ON prefix_observations(prefix_id, is_active, last_seen_at)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prefix_classification_history (
            id TEXT PRIMARY KEY, prefix_id TEXT NOT NULL, collection_run_id TEXT DEFAULT '',
            previous_type TEXT DEFAULT '', next_type TEXT DEFAULT '', confidence REAL DEFAULT 0,
            source TEXT DEFAULT '', evidence_json TEXT DEFAULT '{}', created_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prefix_class_history_prefix ON prefix_classification_history(prefix_id, created_at)")
