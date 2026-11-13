"""Add provider-neutral storage metadata for PAM recordings and snapshots."""

from __future__ import annotations


VERSION = 247
NAME = "storage_provider_fields"


_STORAGE_COLUMNS = (
    ("storage_backend", "TEXT NOT NULL DEFAULT 'local'"),
    ("storage_bucket", "TEXT NOT NULL DEFAULT ''"),
    ("object_key", "TEXT NOT NULL DEFAULT ''"),
    ("object_version_id", "TEXT NOT NULL DEFAULT ''"),
    ("object_size", "INTEGER NOT NULL DEFAULT 0"),
    ("object_sha256", "TEXT NOT NULL DEFAULT ''"),
    ("content_type", "TEXT NOT NULL DEFAULT ''"),
    ("storage_status", "TEXT NOT NULL DEFAULT 'LEGACY'"),
    ("storage_error", "TEXT NOT NULL DEFAULT ''"),
    ("storage_updated_at", "TEXT NOT NULL DEFAULT ''"),
)


def _add_columns(cursor, table: str, *, recording_spool: bool = False) -> None:
    if recording_spool:
        cursor.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS recording_spool_path TEXT NOT NULL DEFAULT ''"
        )
    for column, definition in _STORAGE_COLUMNS:
        cursor.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"
        )


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    _add_columns(cursor, "pam_sessions", recording_spool=True)
    _add_columns(cursor, "config_snapshots")
    cursor.execute(
        "ALTER TABLE config_snapshots ADD COLUMN IF NOT EXISTS storage_spool_path TEXT NOT NULL DEFAULT ''"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_pam_sessions_storage_status "
        "ON pam_sessions(storage_status, storage_updated_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_snapshots_storage_status "
        "ON config_snapshots(storage_status, storage_updated_at DESC)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Additive fields are intentionally retained during rollback so existing
    # recordings and snapshots remain readable.
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
