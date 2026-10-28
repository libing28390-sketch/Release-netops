"""Tie CMDB VLAN snapshots to their owning device lifecycle."""

from __future__ import annotations


VERSION = 300
NAME = "cmdb_vlan_device_lifecycle"

_DEVICE_OWNED_TABLES = (
    "cmdb_collection_snapshots",
    "cmdb_device_vlan_observations",
)


def _quote_identifier(value: str) -> str:
    """Quote a catalog-derived PostgreSQL identifier."""
    return '"' + value.replace('"', '""') + '"'


def _device_foreign_keys(cursor, table_name: str) -> list[tuple[str, str]]:
    cursor.execute(
        """
        SELECT tc.constraint_name, rc.delete_rule
          FROM information_schema.table_constraints tc
          JOIN information_schema.key_column_usage kcu
            ON tc.constraint_schema = kcu.constraint_schema
           AND tc.constraint_name = kcu.constraint_name
           AND tc.table_name = kcu.table_name
          JOIN information_schema.constraint_column_usage ccu
            ON tc.constraint_schema = ccu.constraint_schema
           AND tc.constraint_name = ccu.constraint_name
          JOIN information_schema.referential_constraints rc
            ON tc.constraint_schema = rc.constraint_schema
           AND tc.constraint_name = rc.constraint_name
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
    return [(str(row[0]), str(row[1]).upper()) for row in cursor.fetchall()]


def _repair_device_cascade(cursor, table_name: str) -> None:
    constraints = _device_foreign_keys(cursor, table_name)
    cascading = [name for name, delete_rule in constraints if delete_rule == "CASCADE"]
    if len(constraints) == 1 and len(cascading) == 1:
        return

    for constraint_name, _delete_rule in constraints:
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


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("CMDB VLAN lifecycle migration requires PostgreSQL")

    # Repair prerequisites for installations that recorded earlier migration
    # versions while one or more tables were missing or incomplete.
    from database.migrations.m0299_cmdb_cli_fact_isolation import upgrade as upgrade_cli_facts

    upgrade_cli_facts(cursor, use_pg)

    # Remove disposable cache rows that cannot belong to a live device before
    # enforcing the device lifecycle constraints. Port rows are tied to the
    # parent VLAN observation by m0299; the explicit NOT EXISTS also repairs
    # installations where that constraint was absent.
    cursor.execute(
        """DELETE FROM cmdb_device_vlan_port_observations p
           WHERE NOT EXISTS (
               SELECT 1 FROM devices d WHERE d.id = p.device_id
           ) OR NOT EXISTS (
               SELECT 1 FROM cmdb_device_vlan_observations o
               WHERE o.device_id = p.device_id AND o.vlan_id = p.vlan_id
           )"""
    )
    cursor.execute(
        """DELETE FROM cmdb_device_vlan_observations o
           WHERE NOT EXISTS (
               SELECT 1 FROM devices d WHERE d.id = o.device_id
           )"""
    )
    cursor.execute(
        """DELETE FROM cmdb_collection_snapshots s
           WHERE NOT EXISTS (
               SELECT 1 FROM devices d WHERE d.id = s.device_id
           )"""
    )

    for table_name in _DEVICE_OWNED_TABLES:
        _repair_device_cascade(cursor, table_name)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep the cascade semantics during application rollback. These tables are
    # disposable device-owned snapshots and reverting would recreate orphans.
    return None
