"""Add immutable Playbook version snapshots for execution traceability."""

from __future__ import annotations


VERSION = 74
NAME = "playbook_version_snapshots"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]).lower() for row in rows}
    return {str(row[1]).lower() for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS playbook_versions (
            id TEXT PRIMARY KEY,
            playbook_id TEXT NOT NULL,
            tenant_id TEXT,
            version_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'DRAFT',
            name TEXT NOT NULL DEFAULT '',
            definition_json TEXT NOT NULL DEFAULT '{}',
            checksum TEXT NOT NULL,
            validation_status TEXT NOT NULL DEFAULT 'PENDING',
            validation_result_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT DEFAULT '',
            submitted_by TEXT,
            approved_by TEXT,
            published_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            published_at TEXT,
            lock_version INTEGER NOT NULL DEFAULT 1,
            UNIQUE (playbook_id, version_number),
            CHECK (status IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'PUBLISHED', 'DEPRECATED', 'SNAPSHOT'))
        )
        """
    )
    if "playbook_version_id" not in _columns(cursor, "playbook_executions", use_pg):
        cursor.execute("ALTER TABLE playbook_executions ADD COLUMN playbook_version_id TEXT")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_playbook_versions_playbook ON playbook_versions(playbook_id, version_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_playbook_versions_checksum ON playbook_versions(checksum)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_playbook_executions_version ON playbook_executions(playbook_version_id)")
