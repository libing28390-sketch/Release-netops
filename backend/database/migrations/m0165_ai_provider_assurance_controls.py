"""Record provider assurance evidence required for INTERNAL cloud egress."""

from __future__ import annotations


VERSION = 165
NAME = "ai_provider_assurance_controls"


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
    existing = _columns(cursor, "ai_provider", use_pg)
    if not existing:
        return
    definitions = {
        "no_training_confirmed": "INTEGER DEFAULT 0",
        "retention_days": "INTEGER",
        "data_processing_agreement_ref": "TEXT",
        "agreement_reviewed_at": "TEXT",
        "approved_endpoint_patterns_json": "TEXT DEFAULT '[]'",
    }
    for name, definition in definitions.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE ai_provider ADD COLUMN {name} {definition}")


__all__ = ["VERSION", "NAME", "upgrade"]
