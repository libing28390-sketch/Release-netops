"""Add credential bindings reserved for managed Web login automation."""

from __future__ import annotations


VERSION = 132
NAME = "web_profile_credentials"


def _ensure_column(cursor, column: str, definition: str, use_pg: bool) -> None:
    if use_pg:
        cursor.execute(
            f"ALTER TABLE asset_web_access_profiles ADD COLUMN IF NOT EXISTS {column} {definition}"
        )
        return
    columns = {
        str(row[1])
        for row in cursor.execute("PRAGMA table_info(asset_web_access_profiles)").fetchall()
    }
    if column not in columns:
        cursor.execute(f"ALTER TABLE asset_web_access_profiles ADD COLUMN {column} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    for column, definition in (
        ("credential_mode", "TEXT NOT NULL DEFAULT 'inherit_asset'"),
        ("normal_username", "TEXT NOT NULL DEFAULT ''"),
        ("normal_password", "TEXT NOT NULL DEFAULT ''"),
        ("admin_username", "TEXT NOT NULL DEFAULT ''"),
        ("admin_password", "TEXT NOT NULL DEFAULT ''"),
        ("credential_id", "TEXT NOT NULL DEFAULT ''"),
        ("admin_credential_id", "TEXT NOT NULL DEFAULT ''"),
    ):
        _ensure_column(cursor, column, definition, use_pg)


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
