"""Persist execution-time approval gates for controlled Playbooks."""

from __future__ import annotations


VERSION = 89
NAME = "playbook_execution_approvals"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}



def upgrade(cursor, use_pg: bool) -> None:
    execution_columns = _columns(cursor, "playbook_executions", use_pg)
    if "status" not in execution_columns:
        cursor.execute(
            "ALTER TABLE playbook_executions "
            "ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
        )
    if "commit_confirmed_ttl" not in execution_columns:
        cursor.execute(
            "ALTER TABLE playbook_executions "
            "ADD COLUMN commit_confirmed_ttl INTEGER NOT NULL DEFAULT 0"
        )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS playbook_execution_approvals (
            id TEXT PRIMARY KEY,
            execution_id TEXT NOT NULL,
            tenant_id TEXT,
            step_path TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            required_role TEXT NOT NULL DEFAULT 'Administrator',
            status TEXT NOT NULL DEFAULT 'PENDING',
            requested_by TEXT NOT NULL DEFAULT '',
            requested_by_username TEXT NOT NULL DEFAULT '',
            requested_by_role TEXT NOT NULL DEFAULT '',
            decided_by TEXT,
            decided_by_username TEXT,
            decision_reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            decided_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE (execution_id, step_path),
            FOREIGN KEY (execution_id) REFERENCES playbook_executions(id) ON DELETE CASCADE,
            CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
            CHECK (required_role IN ('Administrator'))
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_playbook_execution_approvals_execution "
        "ON playbook_execution_approvals(execution_id, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_playbook_execution_approvals_tenant "
        "ON playbook_execution_approvals(tenant_id, created_at)"
    )
