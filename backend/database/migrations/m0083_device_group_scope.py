"""Add the device-group resource scope column used by P0 authorization checks."""

from __future__ import annotations


VERSION = 83
NAME = "device_group_scope"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}



def upgrade(cursor, use_pg: bool) -> None:
    if "device_group_id" not in _columns(cursor, "devices", use_pg):
        cursor.execute("ALTER TABLE devices ADD COLUMN device_group_id TEXT DEFAULT ''")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_devices_device_group_id ON devices(device_group_id)")
