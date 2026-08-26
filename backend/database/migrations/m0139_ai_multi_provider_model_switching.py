"""Additive PostgreSQL contract for multi-provider and model switching.

The legacy AI tables remain intact.  This migration adds health, capability,
secret-rotation, model-visibility, route metadata and per-message model
provenance fields.  PostgreSQL is the production authority; the migration
keeps a small SQLite-compatible DDL path only for existing compatibility
fixtures and never uses it as a release gate.
"""

from __future__ import annotations

VERSION = 139
NAME = "ai_multi_provider_model_switching"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]) for row in rows}
    rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _add_columns(cursor, table: str, definitions: dict[str, str], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    if not existing:
        return
    for name, definition in definitions.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    _add_columns(
        cursor,
        "ai_provider",
        {
            "health_status": "TEXT DEFAULT 'unknown'",
            "last_health_check_at": "TEXT",
            "last_success_at": "TEXT",
            "last_error_code": "TEXT",
            "last_error_at": "TEXT",
            "tags_json": "TEXT DEFAULT '{}'",
            "data_region": "TEXT DEFAULT 'unknown'",
            "allowed_data_classification": "TEXT DEFAULT 'PUBLIC'",
            "adapter_key_version": "INTEGER DEFAULT 1",
            "disabled_reason": "TEXT",
        },
        use_pg,
    )
    _add_columns(
        cursor,
        "ai_model",
        {
            "stream_supported": "INTEGER DEFAULT 1",
            "display_name": "TEXT",
            "cost_input_per_1k": "REAL DEFAULT 0",
            "cost_output_per_1k": "REAL DEFAULT 0",
            "health_status": "TEXT DEFAULT 'unknown'",
            "last_latency_ms": "INTEGER",
            "last_success_at": "TEXT",
            "last_error_code": "TEXT",
        },
        use_pg,
    )
    _add_columns(cursor, "ai_model_route", {"priority": "INTEGER DEFAULT 10", "data_classification": "TEXT DEFAULT 'PUBLIC'"}, use_pg)
    _add_columns(cursor, "ai_conversations", {"selected_model_id": "TEXT", "model_locked": "INTEGER DEFAULT 0"}, use_pg)
    _add_columns(
        cursor,
        "ai_messages",
        {
            "requested_model_id": "TEXT",
            "actual_model_id": "TEXT",
            "provider_id": "TEXT",
            "route_reason": "TEXT",
            "fallback_used": "INTEGER DEFAULT 0",
        },
        use_pg,
    )

    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_provider_name ON ai_provider(name)"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_model_provider_code ON ai_model(provider_id, model_code)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_provider_health ON ai_provider(health_status, enabled)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_model_health ON ai_model(health_status, enabled)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_model_route_priority ON ai_model_route(scene, priority, enabled)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_messages_actual_model ON ai_messages(actual_model_id, provider_id)")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_provider_key_rotation (
            id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            key_version INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            api_key_encrypted TEXT,
            api_key_masked TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            retired_at TEXT,
            invalidated_at TEXT,
            FOREIGN KEY (provider_id) REFERENCES ai_provider(id) ON DELETE CASCADE,
            UNIQUE (provider_id, key_version)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_key_rotation_provider ON ai_provider_key_rotation(provider_id, status)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_model_acl (
            id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            allow_access INTEGER NOT NULL DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (model_id, tenant_id, subject_type, subject_id),
            FOREIGN KEY (model_id) REFERENCES ai_model(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_model_acl_lookup ON ai_model_acl(tenant_id, subject_type, subject_id, model_id)")


def downgrade(cursor, use_pg: bool) -> None:
    # Additive fields and provenance tables are retained to preserve audit and
    # V1 compatibility.  Release rollback disables the new route instead of
    # deleting key history or model-selection evidence.
    return None
