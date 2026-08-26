"""Add per-asset SSH host-key fingerprint storage for PAM sessions."""

from __future__ import annotations

VERSION = 109
NAME = "pam_host_key_fingerprints"


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


def upgrade(cursor, use_pg: bool) -> None:
    for table in ("physical_assets", "devices"):
        if "ssh_host_key_fingerprint" not in _columns(cursor, table, use_pg):
            cursor.execute(
                f"ALTER TABLE {table} ADD COLUMN ssh_host_key_fingerprint TEXT DEFAULT ''"
            )
