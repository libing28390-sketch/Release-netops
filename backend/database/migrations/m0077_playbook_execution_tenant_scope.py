"""Add tenant ownership to Playbook executions for read and action isolation."""

from __future__ import annotations


VERSION = 77
NAME = "playbook_execution_tenant_scope"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}



def upgrade(cursor, use_pg: bool) -> None:
    columns = _columns(cursor, "playbook_executions", use_pg)
    if "tenant_id" not in columns:
        cursor.execute("ALTER TABLE playbook_executions ADD COLUMN tenant_id TEXT")
        columns.add("tenant_id")
    index_columns = "tenant_id, created_at" if "created_at" in columns else "tenant_id"
    cursor.execute(f"CREATE INDEX IF NOT EXISTS ix_playbook_executions_tenant_created ON playbook_executions({index_columns})")
