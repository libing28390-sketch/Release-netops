"""Add IPAM write revisions, references, assignments, and idempotency storage."""

from __future__ import annotations


VERSION = 311
NAME = "ipam_write_revisions_and_pool_assignment"

_REVISION_TABLES = (
    "prefixes",
    "ip_addresses",
    "ipam_pools",
    "ipam_vips",
    "ipam_dhcp_leases",
)
_IP_ADDRESS_FOREIGN_KEYS = (
    ("fk_ip_addresses_device", "device_id", "devices", "id", "SET NULL"),
    ("fk_ip_addresses_interface", "interface_id", "interfaces", "id", "SET NULL"),
)


def _ensure_revision_column(cursor, table_name: str) -> None:
    cursor.execute(
        f"ALTER TABLE {table_name} "
        "ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1"
    )

    cursor.execute(
        f"""
        SELECT attribute.atttypid = 'integer'::regtype,
               attribute.attnotnull,
               pg_get_expr(default_value.adbin, default_value.adrelid)
          FROM pg_attribute AS attribute
          LEFT JOIN pg_attrdef AS default_value
            ON default_value.adrelid = attribute.attrelid
           AND default_value.adnum = attribute.attnum
         WHERE attribute.attrelid = '{table_name}'::regclass
           AND attribute.attname = 'revision'
           AND attribute.attnum > 0
           AND NOT attribute.attisdropped
        """
    )
    column = cursor.fetchone()
    if column is None or not bool(column[0]):
        raise RuntimeError(
            f"IPAM write revision migration blocked: {table_name}.revision "
            "must have PostgreSQL INTEGER type"
        )

    cursor.execute(f"ALTER TABLE {table_name} ALTER COLUMN revision SET DEFAULT 1")
    cursor.execute(f"ALTER TABLE {table_name} ALTER COLUMN revision SET NOT NULL")

    cursor.execute(
        f"""
        SELECT attribute.attnotnull,
               pg_get_expr(default_value.adbin, default_value.adrelid)
          FROM pg_attribute AS attribute
          LEFT JOIN pg_attrdef AS default_value
            ON default_value.adrelid = attribute.attrelid
           AND default_value.adnum = attribute.attnum
         WHERE attribute.attrelid = '{table_name}'::regclass
           AND attribute.attname = 'revision'
           AND attribute.attnum > 0
           AND NOT attribute.attisdropped
        """
    )
    column = cursor.fetchone()
    if column is None or not bool(column[0]) or str(column[1]) != "1":
        raise RuntimeError(
            f"IPAM write revision migration blocked: {table_name}.revision "
            "could not be made NOT NULL DEFAULT 1"
        )


def _ensure_ip_address_pool_fk(cursor) -> None:
    cursor.execute(
        "ALTER TABLE ip_addresses ADD COLUMN IF NOT EXISTS pool_id TEXT"
    )
    cursor.execute(
        """
        SELECT format_type(attribute.atttypid, attribute.atttypmod),
               attribute.attnotnull
          FROM pg_attribute AS attribute
         WHERE attribute.attrelid = 'ip_addresses'::regclass
           AND attribute.attname = 'pool_id'
           AND attribute.attnum > 0
           AND NOT attribute.attisdropped
        """
    )
    column = cursor.fetchone()
    if column is None or str(column[0]) != "text" or bool(column[1]):
        raise RuntimeError(
            "IPAM Pool assignment migration blocked: ip_addresses.pool_id "
            "must be nullable PostgreSQL TEXT"
        )

    _ensure_ip_address_foreign_key(
        cursor,
        constraint_name="fk_ip_addresses_pool",
        source_column="pool_id",
        target_table="ipam_pools",
        target_column="id",
        delete_action="RESTRICT",
        not_valid=False,
    )


def _ensure_ip_address_foreign_key(
    cursor,
    *,
    constraint_name: str,
    source_column: str,
    target_table: str,
    target_column: str,
    delete_action: str,
    not_valid: bool,
) -> None:
    cursor.execute("ALTER TABLE ip_addresses ALTER COLUMN device_id SET DEFAULT NULL")
    cursor.execute("ALTER TABLE ip_addresses ALTER COLUMN interface_id SET DEFAULT NULL")
    cursor.execute(
        f"""
        SELECT constraint_row.contype,
               constraint_row.confdeltype,
               constraint_row.confrelid = '{target_table}'::regclass,
               ARRAY(
                   SELECT source_attribute.attname::text
                     FROM unnest(constraint_row.conkey)
                          WITH ORDINALITY AS source_key(attnum, position)
                     JOIN pg_attribute AS source_attribute
                       ON source_attribute.attrelid = constraint_row.conrelid
                      AND source_attribute.attnum = source_key.attnum
                    ORDER BY source_key.position
               ),
               ARRAY(
                   SELECT target_attribute.attname::text
                     FROM unnest(constraint_row.confkey)
                          WITH ORDINALITY AS target_key(attnum, position)
                     JOIN pg_attribute AS target_attribute
                       ON target_attribute.attrelid = constraint_row.confrelid
                      AND target_attribute.attnum = target_key.attnum
                    ORDER BY target_key.position
               ),
               constraint_row.convalidated
          FROM pg_constraint AS constraint_row
         WHERE constraint_row.conrelid = 'ip_addresses'::regclass
           AND constraint_row.conname = '{constraint_name}'
        """
    )
    constraint = cursor.fetchone()
    if constraint is not None:
        expected = (
            str(constraint[0]) == "f"
            and str(constraint[1]) == _delete_action_code(delete_action)
            and bool(constraint[2])
            and list(constraint[3] or []) == [source_column]
            and list(constraint[4] or []) == [target_column]
        )
        if not expected:
            raise RuntimeError(
                f"IPAM assignment migration blocked: existing {constraint_name} "
                "constraint has an incompatible definition"
            )
        if not not_valid and not bool(constraint[5]):
            cursor.execute(
                "ALTER TABLE ip_addresses "
                f"VALIDATE CONSTRAINT {constraint_name}"
            )
        return

    validation_clause = " NOT VALID" if not_valid else ""
    cursor.execute(
        f"ALTER TABLE ip_addresses ADD CONSTRAINT {constraint_name} "
        f"FOREIGN KEY ({source_column}) REFERENCES {target_table}({target_column}) "
        f"ON DELETE {delete_action}{validation_clause}"
    )


def _delete_action_code(delete_action: str) -> str:
    return {
        "RESTRICT": "r",
        "SET NULL": "n",
    }[delete_action]


def _ensure_idempotency_records_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_idempotency_records (
            tenant_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json JSONB NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_ipam_idempotency_records_tenant_operation_key
                UNIQUE (tenant_id, operation, idempotency_key)
        )
        """
    )

    cursor.execute(
        """
        SELECT column_name, data_type, is_nullable
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'ipam_idempotency_records'
        """
    )
    columns = {
        str(row[0]): (str(row[1]), str(row[2]))
        for row in cursor.fetchall()
    }
    expected_columns = {
        "tenant_id": ("text", "NO"),
        "operation": ("text", "NO"),
        "idempotency_key": ("text", "NO"),
        "request_hash": ("text", "NO"),
        "response_json": ("jsonb", "NO"),
        "resource_type": ("text", "NO"),
        "resource_id": ("text", "NO"),
        "created_at": ("timestamp with time zone", "NO"),
    }
    if any(columns.get(name) != shape for name, shape in expected_columns.items()):
        raise RuntimeError(
            "IPAM idempotency migration blocked: existing "
            "ipam_idempotency_records columns have an incompatible definition"
        )

    cursor.execute(
        "ALTER TABLE ipam_idempotency_records "
        "ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP"
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
         WHERE constraint_row.conrelid = 'ipam_idempotency_records'::regclass
           AND constraint_row.conname =
               'uq_ipam_idempotency_records_tenant_operation_key'
        """
    )
    constraint = cursor.fetchone()
    if constraint is None:
        cursor.execute(
            """
            ALTER TABLE ipam_idempotency_records
                ADD CONSTRAINT uq_ipam_idempotency_records_tenant_operation_key
                UNIQUE (tenant_id, operation, idempotency_key)
            """
        )
        return

    if (
        str(constraint[0]) != "u"
        or list(constraint[1] or [])
        != ["tenant_id", "operation", "idempotency_key"]
        or not bool(constraint[2])
    ):
        raise RuntimeError(
            "IPAM idempotency migration blocked: existing identity constraint "
            "has an incompatible definition"
        )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM write revisions and Pool assignment require PostgreSQL")

    for table_name in _REVISION_TABLES:
        _ensure_revision_column(cursor, table_name)

    _ensure_ip_address_pool_fk(cursor)
    for (
        constraint_name,
        source_column,
        target_table,
        target_column,
        delete_action,
    ) in _IP_ADDRESS_FOREIGN_KEYS:
        _ensure_ip_address_foreign_key(
            cursor,
            constraint_name=constraint_name,
            source_column=source_column,
            target_table=target_table,
            target_column=target_column,
            delete_action=delete_action,
            not_valid=True,
        )
    _ensure_idempotency_records_table(cursor)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Revision, assignment, reference, and idempotency state must survive
    # application rollback.
    return None
