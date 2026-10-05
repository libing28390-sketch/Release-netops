"""Add the device software-version field to databases created before it existed."""

from __future__ import annotations


VERSION = 274
NAME = "add_device_version_column"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Device version migration requires PostgreSQL")

    # Fresh schemas already define this column; deployed legacy schemas may not.
    cursor.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS version TEXT")
