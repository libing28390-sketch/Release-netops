"""Add a B-tree index for exact NSOT device lookup by management IP."""

from __future__ import annotations


VERSION = 230
NAME = "devices_ip_lookup_index"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("devices_ip_lookup_index requires PostgreSQL")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_devices_ip_address ON devices(ip_address)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("devices_ip_lookup_index requires PostgreSQL")
    cursor.execute("DROP INDEX IF EXISTS idx_devices_ip_address")
