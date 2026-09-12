"""Add per-device collection policy overrides."""

from __future__ import annotations


VERSION = 34
NAME = "device_collection_policy"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    )
    return {row[0] for row in cursor.fetchall()}



def upgrade(cursor, use_pg: bool) -> None:
    if "collection_policy_json" not in _columns(cursor, "devices", use_pg):
        cursor.execute("ALTER TABLE devices ADD COLUMN collection_policy_json TEXT DEFAULT '{}'")
    cursor.execute(
        "UPDATE devices SET collection_policy_json = '{}' "
        "WHERE collection_policy_json IS NULL OR TRIM(collection_policy_json) = ''"
    )
