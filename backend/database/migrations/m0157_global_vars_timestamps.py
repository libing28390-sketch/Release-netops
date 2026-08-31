"""Add timestamps required by the persisted file-transfer settings."""

from __future__ import annotations


VERSION = 157
NAME = "global_vars_timestamps"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}



def upgrade(cursor, use_pg: bool) -> None:
    columns = _columns(cursor, "global_vars", use_pg)
    if "created_at" not in columns:
        cursor.execute("ALTER TABLE global_vars ADD COLUMN created_at TEXT DEFAULT ''")
    if "updated_at" not in columns:
        cursor.execute("ALTER TABLE global_vars ADD COLUMN updated_at TEXT DEFAULT ''")


def downgrade(cursor, use_pg: bool) -> None:
    # Additive compatibility migration: retaining the columns is safer for
    # databases that may already contain persisted transfer settings.
    return None
