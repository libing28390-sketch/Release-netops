"""Add explicit device-local routing-context to address-space mappings."""

from __future__ import annotations


VERSION = 312
NAME = "ipam_device_routing_contexts"


_EXPECTED_COLUMNS = {
    "id": ("text", "NO"),
    "device_id": ("text", "NO"),
    "context_source": ("text", "NO"),
    "context_type": ("text", "NO"),
    "local_context_key": ("text", "NO"),
    "local_context_name": ("text", "NO"),
    "address_space_id": ("text", "NO"),
    "status": ("text", "NO"),
    "revision": ("integer", "NO"),
    "last_verified_at": ("timestamp with time zone", "YES"),
    "created_at": ("timestamp with time zone", "NO"),
    "updated_at": ("timestamp with time zone", "NO"),
}


def _ensure_mapping_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_device_routing_contexts (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL
                REFERENCES devices(id) ON DELETE CASCADE,
            context_source TEXT NOT NULL
                CHECK (context_source IN ('cli', 'snmp')),
            context_type TEXT NOT NULL
                CHECK (context_type IN ('vrf', 'global')),
            local_context_key TEXT NOT NULL
                CHECK (btrim(local_context_key) <> ''),
            local_context_name TEXT NOT NULL DEFAULT '',
            address_space_id TEXT NOT NULL
                REFERENCES ipam_address_spaces(id) ON DELETE RESTRICT,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'disabled')),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            last_verified_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_ipam_device_routing_context_identity
                UNIQUE (device_id, context_source, context_type, local_context_key)
        )
        """
    )

    cursor.execute(
        """
        SELECT column_name, data_type, is_nullable
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'ipam_device_routing_contexts'
        """
    )
    columns = {
        str(row[0]): (str(row[1]), str(row[2]))
        for row in cursor.fetchall()
    }
    if any(columns.get(name) != shape for name, shape in _EXPECTED_COLUMNS.items()):
        raise RuntimeError(
            "IPAM routing-context migration blocked: existing "
            "ipam_device_routing_contexts columns have an incompatible definition"
        )

    cursor.execute(
        """
        SELECT constraint_row.contype,
               ARRAY(
                   SELECT attribute.attname::text
                     FROM unnest(constraint_row.conkey)
                          WITH ORDINALITY AS key_column(attnum, position)
                     JOIN pg_attribute AS attribute
                       ON attribute.attrelid = constraint_row.conrelid
                      AND attribute.attnum = key_column.attnum
                    ORDER BY key_column.position
               ),
               constraint_row.convalidated
          FROM pg_constraint AS constraint_row
         WHERE constraint_row.conrelid = 'ipam_device_routing_contexts'::regclass
           AND constraint_row.conname = 'uq_ipam_device_routing_context_identity'
        """
    )
    unique_constraint = cursor.fetchone()
    expected_identity = [
        "device_id", "context_source", "context_type", "local_context_key",
    ]
    if unique_constraint is None:
        cursor.execute(
            """
            ALTER TABLE ipam_device_routing_contexts
                ADD CONSTRAINT uq_ipam_device_routing_context_identity
                UNIQUE (device_id, context_source, context_type, local_context_key)
            """
        )
    elif (
        str(unique_constraint[0]) != "u"
        or list(unique_constraint[1] or []) != expected_identity
        or not bool(unique_constraint[2])
    ):
        raise RuntimeError(
            "IPAM routing-context migration blocked: existing identity "
            "constraint has an incompatible definition"
        )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ipam_device_routing_contexts_space_status
            ON ipam_device_routing_contexts(address_space_id, status, device_id)
        """
    )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM routing-context mappings require PostgreSQL")
    _ensure_mapping_table(cursor)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Explicit operator mappings may already be referenced by current
    # projections. Retain the additive mapping table on application rollback.
    return None
