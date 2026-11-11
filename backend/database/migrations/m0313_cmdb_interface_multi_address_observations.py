"""Store every current CLI interface address separately from interface state."""

from __future__ import annotations


VERSION = 313
NAME = "cmdb_interface_multi_address_observations"


_EXPECTED_COLUMNS = {
    "device_id": ("text", "NO"),
    "normalized_interface_name": ("text", "NO"),
    "interface_name": ("text", "NO"),
    "context_source": ("text", "NO"),
    "context_type": ("text", "NO"),
    "local_context_key": ("text", "NO"),
    "local_context_name": ("text", "NO"),
    "ip_address": ("inet", "NO"),
    "ip_prefix_length": ("smallint", "NO"),
    "generation": ("bigint", "NO"),
    "observed_at": ("timestamp with time zone", "NO"),
    "run_id": ("text", "NO"),
    "metadata_json": ("jsonb", "NO"),
}


def _ensure_interface_address_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cmdb_device_interface_address_observations (
            device_id TEXT NOT NULL
                REFERENCES devices(id) ON DELETE CASCADE,
            normalized_interface_name TEXT NOT NULL
                CHECK (normalized_interface_name <> ''),
            interface_name TEXT NOT NULL,
            context_source TEXT NOT NULL
                CHECK (context_source IN ('cli', 'snmp')),
            context_type TEXT NOT NULL
                CHECK (context_type IN ('vrf', 'global', 'unknown')),
            local_context_key TEXT NOT NULL DEFAULT '',
            local_context_name TEXT NOT NULL DEFAULT '',
            ip_address INET NOT NULL,
            ip_prefix_length SMALLINT NOT NULL
                CHECK (ip_prefix_length BETWEEN 0 AND 128),
            generation BIGINT NOT NULL CHECK (generation > 0),
            observed_at TIMESTAMPTZ NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT cmdb_interface_address_context_key_chk CHECK (
                (context_type = 'unknown' AND local_context_key = '')
                OR (context_type <> 'unknown' AND btrim(local_context_key) <> '')
            ),
            CONSTRAINT uq_cmdb_interface_address_observation_identity
                PRIMARY KEY (
                    device_id, normalized_interface_name, context_source,
                    context_type, local_context_key, ip_address, ip_prefix_length
                )
        )
        """
    )

    cursor.execute(
        """
        SELECT column_name, data_type, is_nullable
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'cmdb_device_interface_address_observations'
        """
    )
    columns = {
        str(row[0]): (str(row[1]), str(row[2]))
        for row in cursor.fetchall()
    }
    if any(columns.get(name) != shape for name, shape in _EXPECTED_COLUMNS.items()):
        raise RuntimeError(
            "CMDB interface multi-address migration blocked: existing "
            "cmdb_device_interface_address_observations columns are incompatible"
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
         WHERE constraint_row.conrelid =
               'cmdb_device_interface_address_observations'::regclass
           AND constraint_row.conname =
               'uq_cmdb_interface_address_observation_identity'
        """
    )
    primary_key = cursor.fetchone()
    expected_key = [
        "device_id", "normalized_interface_name", "context_source",
        "context_type", "local_context_key", "ip_address", "ip_prefix_length",
    ]
    if primary_key is None:
        cursor.execute(
            """
            ALTER TABLE cmdb_device_interface_address_observations
                ADD CONSTRAINT uq_cmdb_interface_address_observation_identity
                PRIMARY KEY (
                    device_id, normalized_interface_name, context_source,
                    context_type, local_context_key, ip_address, ip_prefix_length
                )
            """
        )
    elif (
        str(primary_key[0]) != "p"
        or list(primary_key[1] or []) != expected_key
        or not bool(primary_key[2])
    ):
        raise RuntimeError(
            "CMDB interface multi-address migration blocked: existing "
            "identity key is incompatible"
        )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_cmdb_interface_addresses_device_ip
            ON cmdb_device_interface_address_observations(device_id, ip_address)
        """
    )

    cursor.execute("SELECT to_regclass('cmdb_device_interface_observations')")
    has_legacy_current_snapshot = cursor.fetchone()[0] is not None
    cursor.execute("SELECT to_regclass('cmdb_collection_snapshots')")
    has_snapshot_generation = cursor.fetchone()[0] is not None
    if has_legacy_current_snapshot and has_snapshot_generation:
        # m0299 keeps only the last-good row per device/interface. Materialize
        # that current source into the address child table as unknown-context;
        # never inspect or import IPAM discovery history.
        cursor.execute(
            """
            INSERT INTO cmdb_device_interface_address_observations (
                device_id, normalized_interface_name, interface_name,
                context_source, context_type, local_context_key,
                local_context_name, ip_address, ip_prefix_length,
                generation, observed_at, run_id, metadata_json
            )
            SELECT observation.device_id,
                   observation.normalized_interface_name,
                   observation.interface_name,
                   'cli', 'unknown', '', '', observation.ip_address::inet,
                   observation.ip_prefix_length,
                   observation.generation,
                   COALESCE(
                       NULLIF(observation.observed_at, '')::timestamptz,
                       CURRENT_TIMESTAMP
                   ),
                   observation.run_id,
                   '{}'::jsonb
              FROM cmdb_device_interface_observations AS observation
              JOIN cmdb_collection_snapshots AS snapshot
                ON snapshot.device_id = observation.device_id
               AND snapshot.domain = 'interface_inventory'
               AND snapshot.successful_generation = observation.generation
             WHERE snapshot.successful_generation > 0
               AND NULLIF(btrim(observation.ip_address), '') IS NOT NULL
               AND observation.ip_prefix_length IS NOT NULL
            ON CONFLICT ON CONSTRAINT uq_cmdb_interface_address_observation_identity
            DO NOTHING
            """
        )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("CMDB interface multi-address snapshots require PostgreSQL")
    _ensure_interface_address_table(cursor)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # This table is the current, replaceable projection used by IPAM. Keep it
    # through application rollback so a newer collector cannot lose facts.
    return None
