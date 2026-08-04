"""Add tenant ownership to user-defined Playbook scenarios."""

from __future__ import annotations


VERSION = 75
NAME = "custom_scenario_tenant_scope"


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
        """CREATE TABLE IF NOT EXISTS custom_scenarios (
            id TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            tenant_id TEXT,
            created_by TEXT DEFAULT 'admin',
            created_at TEXT,
            updated_at TEXT
        )"""
    )
    if "tenant_id" not in _columns(cursor, "custom_scenarios", use_pg):
        cursor.execute("ALTER TABLE custom_scenarios ADD COLUMN tenant_id TEXT")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_custom_scenarios_tenant ON custom_scenarios(tenant_id, updated_at)")
