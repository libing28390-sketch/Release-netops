"""Add validation, approval and optimistic-lock fields to Playbook versions."""

from __future__ import annotations


VERSION = 76
NAME = "playbook_version_lifecycle"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}



def upgrade(cursor, use_pg: bool) -> None:
    columns = _columns(cursor, "playbook_versions", use_pg)
    additions = (
        ("validation_status", "TEXT NOT NULL DEFAULT 'PENDING'"),
        ("validation_result_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("submitted_by", "TEXT"),
        ("approved_by", "TEXT"),
        ("published_by", "TEXT"),
        ("lock_version", "INTEGER NOT NULL DEFAULT 1"),
    )
    for name, definition in additions:
        if name not in columns:
            cursor.execute(f"ALTER TABLE playbook_versions ADD COLUMN {name} {definition}")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_playbook_versions_status ON playbook_versions(playbook_id, tenant_id, status)")
