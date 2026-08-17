import sqlite3

from database.migrations import m0145_knowledge_document_actions as migration


def test_m0145_is_idempotent_and_keeps_action_ledger_metadata_only():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE ai_knowledge_reindex_job (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            scope_json TEXT NOT NULL DEFAULT '{}',
            dry_run INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'queued',
            total INTEGER NOT NULL DEFAULT 0,
            parsed INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            updated INTEGER NOT NULL DEFAULT 0,
            rechunked INTEGER NOT NULL DEFAULT 0,
            embedding_success INTEGER NOT NULL DEFAULT 0,
            embedding_failed INTEGER NOT NULL DEFAULT 0,
            error_log_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    migration.upgrade(conn, use_pg=False)
    migration.upgrade(conn, use_pg=False)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_knowledge_document_action)")}
    job_columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_knowledge_reindex_job)")}
    assert {"tenant_id", "document_id", "action", "confirmed", "impact_json", "recovery_json"} <= columns
    assert {"operation", "action_id"} <= job_columns
    conn.execute(
        """INSERT INTO ai_knowledge_document_action
        (id, tenant_id, document_id, action, confirmed, impact_json, recovery_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("a-1", "tenant-a", "doc-1", "disable", 1, '{"chunks":2}', '{"recovery":"enable"}', "now"),
    )
    row = conn.execute("SELECT tenant_id, action, confirmed FROM ai_knowledge_document_action").fetchone()
    assert tuple(row) == ("tenant-a", "disable", 1)
