"""Persist named resource-role profiles without removing legacy coarse roles."""

from __future__ import annotations


VERSION = 93
NAME = "user_role_profiles"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]).lower() for row in rows}
    return {str(row[1]).lower() for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    if "role_profile" not in _columns(cursor, "users", use_pg):
        cursor.execute("ALTER TABLE users ADD COLUMN role_profile TEXT NOT NULL DEFAULT ''")
