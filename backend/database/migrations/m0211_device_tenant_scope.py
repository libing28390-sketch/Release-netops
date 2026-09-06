"""Make device tenant ownership explicit for all newly written records.

The baseline schema historically created ``devices.tenant_id`` with an empty
default, and the legacy bootstrap only backfilled rows that existed during
startup.  This migration repairs those rows and makes the PostgreSQL default
match the tenant assigned to the built-in deployment.
"""

from __future__ import annotations


VERSION = 211
NAME = "device_tenant_scope"

DEFAULT_TENANT_ID = "tenant-default"


def _columns(cursor, table_name: str, use_pg: bool) -> set[str]:
    if use_pg:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s",
            (table_name,),
        )
        return {str(row[0]) for row in cursor.fetchall()}

    cursor.execute(f"PRAGMA table_info({table_name})")
    return {str(row[1]) for row in cursor.fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    """Backfill legacy device rows and prevent future empty defaults."""
    if "tenant_id" not in _columns(cursor, "devices", use_pg):
        cursor.execute(
            "ALTER TABLE devices ADD COLUMN tenant_id TEXT DEFAULT 'tenant-default'"
        )

    if use_pg:
        cursor.execute(
            "ALTER TABLE devices ALTER COLUMN tenant_id "
            "SET DEFAULT 'tenant-default'"
        )

    cursor.execute(
        "UPDATE devices SET tenant_id = ? "
        "WHERE tenant_id IS NULL OR TRIM(tenant_id) = ''",
        (DEFAULT_TENANT_ID,),
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_devices_tenant_id ON devices(tenant_id)"
    )
