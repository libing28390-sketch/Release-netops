"""Link change orders to monitoring incidents for operational handoff."""

from __future__ import annotations


VERSION = 63
NAME = "change_order_incident_link"


def upgrade(cursor, use_pg: bool) -> None:
    if use_pg:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? AND column_name = ?",
            ("change_orders", "incident_id"),
        )
        exists = cursor.fetchone() is not None
    else:
        exists = any(
            row[1] == "incident_id"
            for row in cursor.execute("PRAGMA table_info(change_orders)").fetchall()
        )
    if not exists:
        cursor.execute("ALTER TABLE change_orders ADD COLUMN incident_id TEXT")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_change_orders_incident_id "
        "ON change_orders(incident_id)"
    )
