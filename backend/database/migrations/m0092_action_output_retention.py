"""Add per-action raw output retention policy columns."""

from __future__ import annotations


VERSION = 92
NAME = "action_output_retention"


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
    columns = _columns(cursor, "action_definitions", use_pg)
    if "raw_output_retention_days" not in columns:
        cursor.execute(
            "ALTER TABLE action_definitions ADD COLUMN raw_output_retention_days INTEGER NOT NULL DEFAULT 1"
        )
    if "failure_output_retention_days" not in columns:
        cursor.execute(
            "ALTER TABLE action_definitions ADD COLUMN failure_output_retention_days INTEGER NOT NULL DEFAULT 7"
        )
    cursor.execute(
        "UPDATE action_definitions SET raw_output_retention_days = CASE "
        "WHEN raw_output_retention_days < 1 THEN 1 WHEN raw_output_retention_days > 3650 THEN 3650 "
        "ELSE raw_output_retention_days END, "
        "failure_output_retention_days = CASE WHEN failure_output_retention_days < 1 THEN 1 "
        "WHEN failure_output_retention_days > 3650 THEN 3650 ELSE failure_output_retention_days END"
    )
