"""Persist monitoring dimensions without treating missing telemetry as zero."""

from __future__ import annotations


VERSION = 60
NAME = "monitoring_health_dimensions"


def upgrade(cursor, use_pg: bool) -> None:
    schema_clause = "table_schema = current_schema() AND " if use_pg else ""
    cursor.execute(
        f"SELECT column_name FROM information_schema.columns WHERE {schema_clause}table_name = ?",
        ("device_health_samples",),
    )
    existing = {row[0] for row in cursor.fetchall()}

    columns = (
        ("health_score_available", "INTEGER NOT NULL DEFAULT 1"),
        ("availability_status", "TEXT NOT NULL DEFAULT 'unknown'"),
        ("collection_status", "TEXT NOT NULL DEFAULT 'unknown'"),
        ("data_confidence", "INTEGER NOT NULL DEFAULT 0"),
    )
    for name, definition in columns:
        if name not in existing:
            cursor.execute(f"ALTER TABLE device_health_samples ADD COLUMN {name} {definition}")

    cursor.execute(
        """
        UPDATE device_health_samples
        SET availability_status = CASE
                WHEN status = 'online' THEN 'online'
                WHEN status = 'offline' THEN 'offline'
                ELSE 'unknown'
            END
        WHERE availability_status = 'unknown'
        """
    )
