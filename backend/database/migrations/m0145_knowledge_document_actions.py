"""KUI-012: tenant-scoped, confirmed knowledge-document actions.

The action ledger is additive.  It records the operator's confirmation and
the bounded impact/recovery contract without copying document bodies, chunks,
credentials or internal storage paths.  Reindex jobs gain an explicit
operation/action link so Reparse, Rechunk and Reindex cannot be conflated.
"""

from __future__ import annotations


VERSION = 145
NAME = "knowledge_document_actions"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    try:
        if use_pg:
            rows = cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                (table,),
            ).fetchall()
            return {str(row[0]) for row in rows}
        rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row[1]) for row in rows}
    except Exception:
        return set()


def _ensure_columns(cursor, table: str, definitions: dict[str, str], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    if not existing:
        return
    for name, definition in definitions.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    json_type = "JSONB" if use_pg else "TEXT"
    json_default = "'{}'::jsonb" if use_pg else "'{}'"
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS ai_knowledge_document_action (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('delete', 'disable', 'enable', 'reparse', 'rechunk', 'reindex')),
            status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
            confirmed INTEGER NOT NULL DEFAULT 0,
            actor_id TEXT,
            actor_username TEXT,
            reason TEXT NOT NULL DEFAULT '',
            job_id TEXT,
            impact_json {json_type} NOT NULL DEFAULT {json_default},
            recovery_json {json_type} NOT NULL DEFAULT {json_default},
            error_code TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_kb_doc_action_tenant_created "
        "ON ai_knowledge_document_action(tenant_id, created_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_kb_doc_action_document "
        "ON ai_knowledge_document_action(tenant_id, document_id, created_at DESC)"
    )
    _ensure_columns(
        cursor,
        "ai_knowledge_reindex_job",
        {
            "operation": "TEXT NOT NULL DEFAULT 'reindex'",
            "action_id": "TEXT",
        },
        use_pg,
    )
    if _columns(cursor, "ai_knowledge_reindex_job", use_pg):
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_ai_knowledge_reindex_job_operation "
            "ON ai_knowledge_reindex_job(tenant_id, operation, created_at)"
        )


def downgrade(cursor, use_pg: bool) -> None:
    # The ledger is audit evidence.  Rollback is an operational feature flag
    # / worker stop; dropping it would destroy evidence and is intentionally
    # not supported by a routine migration downgrade.
    return None
