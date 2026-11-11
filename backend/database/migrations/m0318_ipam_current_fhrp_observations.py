"""Add replaceable current HSRP/VRRP observations for IPAM."""

from __future__ import annotations


VERSION = 318
NAME = "ipam_current_fhrp_observations"


_STATE_COLUMNS = {
    "device_id": ("text", "NO"),
    "protocol": ("text", "NO"),
    "latest_attempt_generation": ("int8", "NO"),
    "latest_status": ("text", "NO"),
    "last_attempt_at": ("timestamptz", "NO"),
    "last_completed_at": ("timestamptz", "YES"),
    "last_success_generation": ("int8", "NO"),
    "last_success_at": ("timestamptz", "YES"),
    "current_row_count": ("int4", "NO"),
    "last_error_code": ("text", "NO"),
    "last_run_id": ("text", "NO"),
    "updated_at": ("timestamptz", "NO"),
}

_OBSERVATION_COLUMNS = {
    "device_id": ("text", "NO"),
    "protocol": ("text", "NO"),
    "group_id": ("int4", "NO"),
    "address_family": ("int2", "NO"),
    "interface_name": ("text", "NO"),
    "normalized_interface_name": ("text", "NO"),
    "priority": ("int2", "YES"),
    "state": ("text", "NO"),
    "master_address": ("inet", "YES"),
    "virtual_ip": ("inet", "YES"),
    "virtual_ip_key": ("text", "NO"),
    "virtual_mac": ("text", "YES"),
    "generation": ("int8", "NO"),
    "observed_at": ("timestamptz", "NO"),
    "run_id": ("text", "NO"),
    "metadata_json": ("jsonb", "NO"),
}


def _validate_columns(cursor, table_name: str, expected: dict[str, tuple[str, str]]) -> None:
    cursor.execute(
        """
        SELECT column_name, udt_name, is_nullable
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
            f"IPAM current FHRP migration blocked: {table_name} has incompatible columns"
        )


def _validate_primary_key(cursor, table_name: str, constraint_name: str, columns: list[str]) -> None:
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
    if (
        primary_key is None
        or str(primary_key[0]) != "p"
        or list(primary_key[1] or []) != columns
        or not bool(primary_key[2])
    ):
        raise RuntimeError(
            f"IPAM current FHRP migration blocked: {table_name} has an incompatible primary key"
        )


def _validate_constraints(cursor, table_name: str, names: tuple[str, ...]) -> None:
    cursor.execute(
        """
        SELECT conname, contype, convalidated
          FROM pg_constraint
         WHERE conrelid = ?::regclass
           AND conname = ANY(?::text[])
        """,
        (table_name, list(names)),
    )
    found = {str(row[0]): (str(row[1]), bool(row[2])) for row in cursor.fetchall()}
    if any(found.get(name) != ("c", True) for name in names):
        raise RuntimeError(
            f"IPAM current FHRP migration blocked: {table_name} has incompatible checks"
        )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM current FHRP observations require PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_current_fhrp_collection_states (
            device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            protocol TEXT NOT NULL,
            latest_attempt_generation BIGINT NOT NULL DEFAULT 0,
            latest_status TEXT NOT NULL DEFAULT 'never',
            last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_completed_at TIMESTAMPTZ,
            last_success_generation BIGINT NOT NULL DEFAULT 0,
            last_success_at TIMESTAMPTZ,
            current_row_count INTEGER NOT NULL DEFAULT 0,
            last_error_code TEXT NOT NULL DEFAULT '',
            last_run_id TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT pk_ipam_current_fhrp_collection_states
                PRIMARY KEY (device_id, protocol),
            CONSTRAINT ck_ipam_current_fhrp_collection_state_protocol
                CHECK (protocol IN ('hsrp', 'vrrp')),
            CONSTRAINT ck_ipam_current_fhrp_collection_state_status
                CHECK (latest_status IN ('never', 'running', 'complete', 'partial', 'failed', 'unsupported')),
            CONSTRAINT ck_ipam_current_fhrp_collection_state_generation
                CHECK (latest_attempt_generation >= 0 AND last_success_generation >= 0),
            CONSTRAINT ck_ipam_current_fhrp_collection_state_count
                CHECK (current_row_count >= 0)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_current_fhrp_observations (
            device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            protocol TEXT NOT NULL,
            group_id INTEGER NOT NULL,
            address_family SMALLINT NOT NULL,
            interface_name TEXT NOT NULL,
            normalized_interface_name TEXT NOT NULL,
            priority SMALLINT,
            state TEXT NOT NULL,
            master_address INET,
            virtual_ip INET,
            virtual_ip_key TEXT NOT NULL DEFAULT '',
            virtual_mac TEXT,
            generation BIGINT NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT pk_ipam_current_fhrp_observations PRIMARY KEY (
                device_id, protocol, address_family, group_id,
                normalized_interface_name, virtual_ip_key
            ),
            CONSTRAINT ck_ipam_current_fhrp_observation_protocol
                CHECK (protocol IN ('hsrp', 'vrrp')),
            CONSTRAINT ck_ipam_current_fhrp_observation_group
                CHECK (group_id >= 0),
            CONSTRAINT ck_ipam_current_fhrp_observation_family
                CHECK (address_family IN (0, 4, 6)),
            CONSTRAINT ck_ipam_current_fhrp_observation_priority
                CHECK (priority IS NULL OR priority BETWEEN 0 AND 255),
            CONSTRAINT ck_ipam_current_fhrp_observation_state
                CHECK (btrim(state) <> '' AND btrim(interface_name) <> '' AND btrim(normalized_interface_name) <> ''),
            CONSTRAINT ck_ipam_current_fhrp_observation_addresses
                CHECK (
                    (master_address IS NULL OR (address_family <> 0 AND family(master_address) = address_family))
                    AND (virtual_ip IS NULL OR (address_family <> 0 AND family(virtual_ip) = address_family))
                ),
            CONSTRAINT ck_ipam_current_fhrp_observation_virtual_ip_key
                CHECK ((virtual_ip IS NULL AND virtual_ip_key = '') OR (virtual_ip IS NOT NULL AND virtual_ip_key <> '')),
            CONSTRAINT ck_ipam_current_fhrp_observation_virtual_mac
                CHECK (virtual_mac IS NULL OR virtual_mac ~ '^[0-9a-f]{2}(:[0-9a-f]{2}){5}$'),
            CONSTRAINT ck_ipam_current_fhrp_observation_generation
                CHECK (generation > 0)
        )
        """
    )

    _validate_columns(cursor, "ipam_current_fhrp_collection_states", _STATE_COLUMNS)
    _validate_columns(cursor, "ipam_current_fhrp_observations", _OBSERVATION_COLUMNS)
    _validate_primary_key(
        cursor,
        "ipam_current_fhrp_collection_states",
        "pk_ipam_current_fhrp_collection_states",
        ["device_id", "protocol"],
    )
    _validate_primary_key(
        cursor,
        "ipam_current_fhrp_observations",
        "pk_ipam_current_fhrp_observations",
        [
            "device_id", "protocol", "address_family", "group_id",
            "normalized_interface_name", "virtual_ip_key",
        ],
    )
    _validate_constraints(
        cursor,
        "ipam_current_fhrp_collection_states",
        (
            "ck_ipam_current_fhrp_collection_state_protocol",
            "ck_ipam_current_fhrp_collection_state_status",
            "ck_ipam_current_fhrp_collection_state_generation",
            "ck_ipam_current_fhrp_collection_state_count",
        ),
    )
    _validate_constraints(
        cursor,
        "ipam_current_fhrp_observations",
        (
            "ck_ipam_current_fhrp_observation_protocol",
            "ck_ipam_current_fhrp_observation_group",
            "ck_ipam_current_fhrp_observation_family",
            "ck_ipam_current_fhrp_observation_priority",
            "ck_ipam_current_fhrp_observation_state",
            "ck_ipam_current_fhrp_observation_addresses",
            "ck_ipam_current_fhrp_observation_virtual_ip_key",
            "ck_ipam_current_fhrp_observation_virtual_mac",
            "ck_ipam_current_fhrp_observation_generation",
        ),
    )
    cursor.execute(
        """CREATE INDEX IF NOT EXISTS idx_ipam_current_fhrp_observations_vip
               ON ipam_current_fhrp_observations(virtual_ip_key)
             WHERE virtual_ip_key <> ''"""
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Retain current FHRP rows and their constraints through rollback.
    return None
