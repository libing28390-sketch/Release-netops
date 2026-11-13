"""Add generic asset Web access profiles and PAM Web session metadata."""

from __future__ import annotations


VERSION = 130
NAME = "pam_web_access"


def _ensure_column(cursor, table: str, column: str, definition: str, use_pg: bool) -> None:
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
    return



def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_web_access_profiles (
            id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            profile_name TEXT NOT NULL DEFAULT 'Web management',
            scheme TEXT NOT NULL DEFAULT 'https',
            port INTEGER NOT NULL DEFAULT 443,
            path TEXT NOT NULL DEFAULT '/',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (asset_id) REFERENCES physical_assets(id) ON DELETE CASCADE,
            UNIQUE (asset_id, scheme, port, path)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_web_profiles_asset ON asset_web_access_profiles(asset_id, enabled)"
    )

    for column, definition in (
        ("session_kind", "TEXT DEFAULT 'ssh_terminal'"),
        ("web_profile_id", "TEXT DEFAULT ''"),
    ):
        _ensure_column(cursor, "pam_access_requests", column, definition, use_pg)

    for column, definition in (
        ("session_kind", "TEXT DEFAULT 'ssh_terminal'"),
        ("target_scheme", "TEXT DEFAULT ''"),
        ("target_path", "TEXT DEFAULT '/'"),
        ("web_profile_id", "TEXT DEFAULT ''"),
        ("agent_id", "TEXT DEFAULT ''"),
        ("agent_token_hash", "TEXT DEFAULT ''"),
        ("last_heartbeat_at", "TEXT"),
        ("recording_status", "TEXT DEFAULT 'not_started'"),
    ):
        _ensure_column(cursor, "pam_sessions", column, definition, use_pg)


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    # Migrations are forward-only in production.  Leaving the additive fields
    # in place preserves old PAM audit rows during a rollback of application code.
    return None
