"""Persist per-message AI execution provenance and measured usage."""

from __future__ import annotations

VERSION = 168
NAME = "ai_message_execution_metadata"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]) for row in rows}



def upgrade(cursor, use_pg: bool) -> None:
    existing = _columns(cursor, "ai_messages", use_pg)
    if not existing:
        return

    definitions = {
        "execution_mode": "TEXT",
        "external_egress": "INTEGER",
        "input_tokens": "INTEGER",
        "output_tokens": "INTEGER",
        "latency_ms": "INTEGER",
    }
    for name, definition in definitions.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE ai_messages ADD COLUMN {name} {definition}")

    # Existing messages can only be classified when durable evidence exists.
    # Usage and latency remain NULL because historic audit rows cannot be
    # matched to messages without inventing a correlation.
    cursor.execute(
        """
        UPDATE ai_messages
        SET execution_mode = CASE
                WHEN actual_model_id IS NOT NULL OR provider_id IS NOT NULL THEN 'provider_generated'
                WHEN citations_json IS NOT NULL AND citations_json NOT IN ('', '[]') THEN 'local_knowledge'
                ELSE 'legacy_unknown'
            END,
            external_egress = CASE
                WHEN actual_model_id IS NOT NULL OR provider_id IS NOT NULL THEN 1
                WHEN citations_json IS NOT NULL AND citations_json NOT IN ('', '[]') THEN 0
                ELSE NULL
            END
        WHERE role = 'assistant' AND execution_mode IS NULL
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_messages_execution_mode "
        "ON ai_messages(conversation_id, execution_mode, created_at)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    # Provenance is audit evidence and is intentionally retained on rollback.
    return None
