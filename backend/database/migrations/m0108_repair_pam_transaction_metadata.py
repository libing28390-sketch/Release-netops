"""Add transaction metadata columns to legacy PAM change tables."""

from __future__ import annotations

VERSION = 108
NAME = "repair_pam_transaction_metadata"


def _columns(cursor, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        ("pam_change_transactions",),
    ).fetchall()
    return {str(row[0]) for row in rows}



def upgrade(cursor, use_pg: bool) -> None:
    definitions = {
        "target_type": "TEXT",
        "target_name": "TEXT",
        "config_diff_id": "TEXT",
        "verification_state": "TEXT DEFAULT 'pending'",
        "rollback_state": "TEXT DEFAULT 'not_requested'",
        "commit_model": "TEXT DEFAULT 'direct'",
    }
    existing = _columns(cursor, use_pg)
    if not existing:
        return
    for column, definition in definitions.items():
        if column not in existing:
            cursor.execute(
                f"ALTER TABLE pam_change_transactions ADD COLUMN {column} {definition}"
            )
