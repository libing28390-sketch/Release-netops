"""Add a replaceable current FDB projection alongside current ARP rows."""

from __future__ import annotations


VERSION = 316
NAME = "ipam_current_fdb_observations"


_STATE_COLUMNS = {
    "device_id": ("text", "NO"),
    "observation_source": ("text", "NO"),
    "context_source": ("text", "NO"),
    "context_type": ("text", "NO"),
    "local_context_key": ("text", "NO"),
    "latest_attempt_generation": ("bigint", "NO"),
    "latest_status": ("text", "NO"),
    "last_attempt_at": ("timestamp with time zone", "NO"),
    "last_success_generation": ("bigint", "NO"),
    "last_success_at": ("timestamp with time zone", "YES"),
    "current_row_count": ("integer", "NO"),
    "last_error_code": ("text", "NO"),
    "last_run_id": ("text", "NO"),
    "updated_at": ("timestamp with time zone", "NO"),
}

_FDB_COLUMNS = {
    "source_device_id": ("text", "NO"),
    "observation_source": ("text", "NO"),
    "context_source": ("text", "NO"),
    "context_type": ("text", "NO"),
    "local_context_key": ("text", "NO"),
    "local_context_name": ("text", "NO"),
    "mac_address": ("text", "NO"),
    "interface_name": ("text", "NO"),
    "normalized_interface_name": ("text", "NO"),
    "vlan_key": ("smallint", "NO"),
    "entry_type": ("text", "NO"),
    "generation": ("bigint", "NO"),
    "observed_at": ("timestamp with time zone", "NO"),
    "run_id": ("text", "NO"),
    "metadata_json": ("jsonb", "NO"),
}


def _validate_columns(cursor, table_name: str, expected: dict[str, tuple[str, str]]) -> None:
    cursor.execute(
        """
        SELECT column_name, data_type, is_nullable
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = ?
        """,
        (table_name,),
    )
    columns = {
        str(row[0]): (str(row[1]), str(row[2]))
        for row in cursor.fetchall()
    }
    if any(columns.get(name) != shape for name, shape in expected.items()):
        raise RuntimeError(
            f"IPAM current FDB migration blocked: {table_name} has incompatible columns"
        )


def _ensure_primary_key(cursor, table_name: str, constraint_name: str, columns: list[str]) -> None:
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
         WHERE constraint_row.conrelid = ?::regclass
           AND constraint_row.conname = ?
        """,
        (table_name, constraint_name),
    )
    primary_key = cursor.fetchone()
    if primary_key is None:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} PRIMARY KEY "
            f"({', '.join(columns)})"
        )
        return
    if (
        str(primary_key[0]) != "p"
        or list(primary_key[1] or []) != columns
        or not bool(primary_key[2])
    ):
        raise RuntimeError(
            f"IPAM current FDB migration blocked: {table_name} has an incompatible primary key"
        )


def _allow_fdb_collection_states(cursor) -> None:
    cursor.execute(
        "ALTER TABLE ipam_endpoint_collection_states "
        "DROP CONSTRAINT IF EXISTS ipam_endpoint_collection_states_observation_source_check"
    )
    cursor.execute(
        "ALTER TABLE ipam_endpoint_collection_states "
        "DROP CONSTRAINT IF EXISTS ck_ipam_endpoint_state_source"
    )
    cursor.execute(
        """ALTER TABLE ipam_endpoint_collection_states
               ADD CONSTRAINT ck_ipam_endpoint_state_source
               CHECK (observation_source IN ('arp', 'fdb'))"""
    )


def _ensure_fdb_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_current_fdb_observations (
            source_device_id TEXT NOT NULL
                REFERENCES devices(id) ON DELETE CASCADE,
            observation_source TEXT NOT NULL CHECK (observation_source = 'fdb'),
            context_source TEXT NOT NULL CHECK (context_source IN ('cli', 'snmp')),
            context_type TEXT NOT NULL CHECK (context_type IN ('vrf', 'global', 'unknown')),
            local_context_key TEXT NOT NULL DEFAULT '',
            local_context_name TEXT NOT NULL DEFAULT '',
            mac_address TEXT NOT NULL,
            interface_name TEXT NOT NULL DEFAULT '',
            normalized_interface_name TEXT NOT NULL DEFAULT '',
            vlan_key SMALLINT NOT NULL DEFAULT 0 CHECK (vlan_key BETWEEN 0 AND 4094),
            entry_type TEXT NOT NULL DEFAULT '',
            generation BIGINT NOT NULL CHECK (generation > 0),
            observed_at TIMESTAMPTZ NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_ipam_current_fdb_context_key CHECK (
                context_type = 'unknown'
                OR (context_type IN ('vrf', 'global') AND btrim(local_context_key) <> '')
            ),
            CONSTRAINT pk_ipam_current_fdb_observations PRIMARY KEY (
                source_device_id, observation_source, context_source, context_type,
                local_context_key, mac_address, normalized_interface_name, vlan_key
            )
        )
        """
    )
    _validate_columns(cursor, "ipam_current_fdb_observations", _FDB_COLUMNS)
    _ensure_primary_key(
        cursor,
        "ipam_current_fdb_observations",
        "pk_ipam_current_fdb_observations",
        [
            "source_device_id", "observation_source", "context_source", "context_type",
            "local_context_key", "mac_address", "normalized_interface_name", "vlan_key",
        ],
    )
    cursor.execute(
        """CREATE INDEX IF NOT EXISTS idx_ipam_current_fdb_observations_mac_vlan
               ON ipam_current_fdb_observations(mac_address, vlan_key)"""
    )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM current FDB observations require PostgreSQL")
    cursor.execute("SELECT to_regclass(?)", ("ipam_endpoint_collection_states",))
    if cursor.fetchone()[0] is None:
        raise RuntimeError("IPAM current FDB migration blocked: collection state table is missing")
    _validate_columns(cursor, "ipam_endpoint_collection_states", _STATE_COLUMNS)
    _allow_fdb_collection_states(cursor)
    _ensure_fdb_table(cursor)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep current FDB rows and the widened state constraint through rollback.
    return None
