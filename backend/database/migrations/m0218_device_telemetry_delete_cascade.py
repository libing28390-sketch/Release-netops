"""Allow device deletion to remove server telemetry history safely."""

from __future__ import annotations


VERSION = 218
NAME = "device_telemetry_delete_cascade"

_TELEMETRY_TABLES = (
    "device_telemetry_samples",
    "device_telemetry_hourly",
)


def _quote_identifier(value: str) -> str:
    """Quote a catalog-derived PostgreSQL identifier."""
    return '"' + value.replace('"', '""') + '"'


def _device_foreign_keys(cursor, table_name: str) -> list[str]:
    cursor.execute(
        """
        SELECT tc.constraint_name
          FROM information_schema.table_constraints tc
          JOIN information_schema.key_column_usage kcu
            ON tc.constraint_schema = kcu.constraint_schema
           AND tc.constraint_name = kcu.constraint_name
           AND tc.table_name = kcu.table_name
          JOIN information_schema.constraint_column_usage ccu
            ON tc.constraint_schema = ccu.constraint_schema
           AND tc.constraint_name = ccu.constraint_name
         WHERE tc.constraint_schema = current_schema()
           AND tc.table_name = ?
           AND tc.constraint_type = 'FOREIGN KEY'
           AND kcu.column_name = 'device_id'
           AND ccu.table_schema = current_schema()
           AND ccu.table_name = 'devices'
           AND ccu.column_name = 'id'
         ORDER BY tc.constraint_name
        """,
        (table_name,),
    )
    return [str(row[0]) for row in cursor.fetchall()]


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Device telemetry delete cascade migration requires PostgreSQL")

    for table_name in _TELEMETRY_TABLES:
        for constraint_name in _device_foreign_keys(cursor, table_name):
            cursor.execute(
                f"ALTER TABLE {_quote_identifier(table_name)} "
                f"DROP CONSTRAINT {_quote_identifier(constraint_name)}"
            )

        constraint_name = f"{table_name}_device_id_fkey"
        cursor.execute(
            f"ALTER TABLE {_quote_identifier(table_name)} "
            f"ADD CONSTRAINT {_quote_identifier(constraint_name)} "
            "FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE"
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep cascade semantics during an application rollback.  Removing it
    # would reintroduce an undeletable device state on older installations.
    return None
