"""Add an indexed ARP cache source device column for bounded snapshot writes."""

from __future__ import annotations

import json


VERSION = 49
NAME = "arp_cache_source_index"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        )
        return {row[0] for row in cursor.fetchall()}
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    if "source_device_id" not in _columns(cursor, "arp_cache", use_pg):
        cursor.execute("ALTER TABLE arp_cache ADD COLUMN source_device_id TEXT DEFAULT ''")

    rows = cursor.execute(
        "SELECT target_ip, arp_source FROM arp_cache WHERE source_device_id IS NULL OR source_device_id = ''"
    ).fetchall()
    for row in rows:
        try:
            source = json.loads(row[1] or "{}")
        except (TypeError, ValueError):
            source = {}
        source_id = str(source.get("device_id") or "")
        if source_id:
            cursor.execute(
                "UPDATE arp_cache SET source_device_id = %s WHERE target_ip = %s"
                if use_pg else
                "UPDATE arp_cache SET source_device_id = ? WHERE target_ip = ?",
                (source_id, row[0]),
            )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_arp_cache_source_device ON arp_cache(source_device_id)")
