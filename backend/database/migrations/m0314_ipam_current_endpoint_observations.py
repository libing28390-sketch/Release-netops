"""Store the latest successful per-device ARP projection for IPAM."""

from __future__ import annotations


VERSION = 314
NAME = "ipam_current_endpoint_observations"


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

_OBSERVATION_COLUMNS = {
    "source_device_id": ("text", "NO"),
    "observation_source": ("text", "NO"),
    "context_source": ("text", "NO"),
    "context_type": ("text", "NO"),
    "local_context_key": ("text", "NO"),
    "local_context_name": ("text", "NO"),
    "ip_address": ("inet", "NO"),
    "mac_address": ("text", "NO"),
    "interface_name": ("text", "NO"),
    "normalized_interface_name": ("text", "NO"),
    "vlan_key": ("smallint", "NO"),
    "generation": ("bigint", "NO"),
    "observed_at": ("timestamp with time zone", "NO"),
    "run_id": ("text", "NO"),
    "metadata_json": ("jsonb", "NO"),
}


def _ensure_state_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_endpoint_collection_states (
            device_id TEXT NOT NULL
                REFERENCES devices(id) ON DELETE CASCADE,
            observation_source TEXT NOT NULL
                CHECK (observation_source IN ('arp')),
            context_source TEXT NOT NULL
                CHECK (context_source IN ('cli', 'snmp')),
            context_type TEXT NOT NULL
                CHECK (context_type IN ('vrf', 'global', 'unknown')),
            local_context_key TEXT NOT NULL DEFAULT '',
            latest_attempt_generation BIGINT NOT NULL DEFAULT 0
                CHECK (latest_attempt_generation >= 0),
            latest_status TEXT NOT NULL DEFAULT 'unsupported'
                CHECK (latest_status IN (
                    'running', 'complete', 'partial', 'failed', 'unsupported', 'scope_unknown'
                )),
            last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_success_generation BIGINT NOT NULL DEFAULT 0
                CHECK (last_success_generation >= 0),
            last_success_at TIMESTAMPTZ,
            current_row_count INTEGER NOT NULL DEFAULT 0
                CHECK (current_row_count >= 0),
            last_error_code TEXT NOT NULL DEFAULT '',
            last_run_id TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_ipam_endpoint_state_generation_order
                CHECK (last_success_generation <= latest_attempt_generation),
            CONSTRAINT ck_ipam_endpoint_state_context_key CHECK (
                context_type = 'unknown'
                OR (context_type IN ('vrf', 'global') AND btrim(local_context_key) <> '')
            ),
            CONSTRAINT pk_ipam_endpoint_collection_states
                PRIMARY KEY (
                    device_id, observation_source, context_source,
                    context_type, local_context_key
                )
        )
        """
    )
    _validate_columns(cursor, "ipam_endpoint_collection_states", _STATE_COLUMNS)
    _ensure_primary_key(
        cursor,
        "ipam_endpoint_collection_states",
        "pk_ipam_endpoint_collection_states",
        [
            "device_id", "observation_source", "context_source",
            "context_type", "local_context_key",
        ],
    )


def _ensure_observation_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_current_endpoint_observations (
            source_device_id TEXT NOT NULL
                REFERENCES devices(id) ON DELETE CASCADE,
            observation_source TEXT NOT NULL
                CHECK (observation_source IN ('arp')),
            context_source TEXT NOT NULL
                CHECK (context_source IN ('cli', 'snmp')),
            context_type TEXT NOT NULL
                CHECK (context_type IN ('vrf', 'global', 'unknown')),
            local_context_key TEXT NOT NULL DEFAULT '',
            local_context_name TEXT NOT NULL DEFAULT '',
            ip_address INET NOT NULL,
            mac_address TEXT NOT NULL,
            interface_name TEXT NOT NULL DEFAULT '',
            normalized_interface_name TEXT NOT NULL DEFAULT '',
            vlan_key SMALLINT NOT NULL DEFAULT 0
                CHECK (vlan_key BETWEEN 0 AND 4094),
            generation BIGINT NOT NULL CHECK (generation > 0),
            observed_at TIMESTAMPTZ NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_ipam_current_endpoint_context_key CHECK (
                context_type = 'unknown'
                OR (context_type IN ('vrf', 'global') AND btrim(local_context_key) <> '')
            ),
            CONSTRAINT pk_ipam_current_endpoint_observations PRIMARY KEY (
                source_device_id, observation_source, context_source, context_type,
                local_context_key, ip_address, mac_address,
                normalized_interface_name, vlan_key
            )
        )
        """
    )
    _validate_columns(cursor, "ipam_current_endpoint_observations", _OBSERVATION_COLUMNS)
    _ensure_primary_key(
        cursor,
        "ipam_current_endpoint_observations",
        "pk_ipam_current_endpoint_observations",
        [
            "source_device_id", "observation_source", "context_source", "context_type",
            "local_context_key", "ip_address", "mac_address",
            "normalized_interface_name", "vlan_key",
        ],
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ipam_current_endpoint_observations_ip
            ON ipam_current_endpoint_observations(ip_address)
        """
    )


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
            f"IPAM endpoint migration blocked: {table_name} has incompatible columns"
        )


def _ensure_primary_key(
    cursor,
    table_name: str,
    constraint_name: str,
    expected_columns: list[str],
) -> None:
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
            f"({', '.join(expected_columns)})"
        )
        return
    if (
        str(primary_key[0]) != "p"
        or list(primary_key[1] or []) != expected_columns
        or not bool(primary_key[2])
    ):
        raise RuntimeError(
            f"IPAM endpoint migration blocked: {table_name} has an incompatible primary key"
        )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM current endpoint observations require PostgreSQL")
    _ensure_state_table(cursor)
    _ensure_observation_table(cursor)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # This is the current replaceable projection; retain it through rollback.
    return None
