"""Add a per-device master switch for SNMP collection."""

from __future__ import annotations


VERSION = 296
NAME = "device_snmp_collection_switch"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Device SNMP collection settings require PostgreSQL")

    cursor.execute(
        "ALTER TABLE devices "
        "ADD COLUMN IF NOT EXISTS snmp_collection_enabled BOOLEAN NOT NULL DEFAULT TRUE"
    )
