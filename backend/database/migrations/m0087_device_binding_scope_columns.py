"""Ensure device binding has stable Site and device-group scope columns."""

from __future__ import annotations


VERSION = 87
NAME = "device_binding_scope_columns"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}



def upgrade(cursor, use_pg: bool) -> None:
    columns = _columns(cursor, "devices", use_pg)
    if "site_id" not in columns:
        cursor.execute("ALTER TABLE devices ADD COLUMN site_id TEXT DEFAULT ''")
    if "site" not in columns:
        cursor.execute("ALTER TABLE devices ADD COLUMN site TEXT DEFAULT ''")
    if "device_group_id" not in columns:
        cursor.execute("ALTER TABLE devices ADD COLUMN device_group_id TEXT DEFAULT ''")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_devices_site_binding ON devices(site_id, device_group_id)")
    cursor.execute(
        "UPDATE devices SET site_id = COALESCE(NULLIF(site_id, ''), site, '') "
        "WHERE COALESCE(site_id, '') = ''"
    )
