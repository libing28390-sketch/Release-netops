"""Link change orders to monitoring incidents for operational handoff."""

from __future__ import annotations


VERSION = 63
NAME = "change_order_incident_link"


def upgrade(cursor, use_pg: bool) -> None:
    schema_clause = "table_schema = current_schema() AND " if use_pg else ""
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE {schema_clause}table_name = ? AND column_name = ?",
        ("change_orders", "incident_id"),
    )
    exists = cursor.fetchone() is not None
    if not exists:
        cursor.execute("ALTER TABLE change_orders ADD COLUMN incident_id TEXT")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_change_orders_incident_id "
        "ON change_orders(incident_id)"
    )
