from __future__ import annotations

import pytest

from backend.tests.pg_test_utils import drop_test_database, postgresql_test_driver
from database.migrations import discover_migrations
from database.migrations.m0311_ipam_write_revisions_and_pool_assignment import (
    VERSION,
    upgrade,
)


_REVISION_TABLES = (
    "prefixes",
    "ip_addresses",
    "ipam_pools",
    "ipam_vips",
    "ipam_dhcp_leases",
)


def _expect_integrity_error(
    connection,
    sql: str,
    values: tuple[object, ...],
    savepoint: str,
) -> None:
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        with pytest.raises(postgresql_test_driver.IntegrityError):
            connection.execute(sql, values)
    finally:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")


def test_m0311_adds_write_revisions_and_optional_pool_assignment() -> None:
    connection = postgresql_test_driver.connect()
    target = connection._target
    try:
        connection.execute("CREATE TABLE prefixes (id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE ipam_pools (id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE devices (id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE interfaces (id TEXT PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE ip_addresses ("
            "id TEXT PRIMARY KEY, address TEXT, device_id TEXT, interface_id TEXT)"
        )
        connection.execute("CREATE TABLE ipam_vips (id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE ipam_dhcp_leases (id TEXT PRIMARY KEY)")
        connection.execute(
            "INSERT INTO ip_addresses (id, address, device_id, interface_id) "
            "VALUES (?, ?, ?, ?)",
            ("legacy-address", "192.0.2.10", "legacy-device", "legacy-interface"),
        )
        connection.execute("INSERT INTO ipam_pools (id) VALUES (?)", ("pool-1",))
        connection.execute("INSERT INTO devices (id) VALUES (?)", ("device-1",))
        connection.execute("INSERT INTO interfaces (id) VALUES (?)", ("interface-1",))
        connection.commit()

        def fail_after_m0311_ddl(cursor, use_pg: bool) -> None:
            upgrade(cursor, use_pg)
            raise RuntimeError("synthetic m0311 failure after DDL")

        with pytest.raises(RuntimeError, match="synthetic m0311 failure after DDL"):
            fail_after_m0311_ddl(connection.cursor(), use_pg=True)
        connection.rollback()

        for table_name in _REVISION_TABLES:
            assert connection.execute(
                """SELECT 1 FROM information_schema.columns
                     WHERE table_schema = current_schema()
                       AND table_name = ? AND column_name = 'revision'""",
                (table_name,),
            ).fetchone() is None
        assert connection.execute(
            """SELECT 1 FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = 'ip_addresses' AND column_name = 'pool_id'"""
        ).fetchone() is None
        assert connection.execute(
            "SELECT to_regclass('ipam_idempotency_records')"
        ).fetchone()[0] is None
        legacy_after_failure = connection.execute(
            "SELECT address, device_id, interface_id FROM ip_addresses WHERE id = ?",
            ("legacy-address",),
        ).fetchone()
        assert tuple(legacy_after_failure) == (
            "192.0.2.10", "legacy-device", "legacy-interface",
        )
        assert connection.execute(
            "SELECT id FROM ipam_pools WHERE id = ?", ("pool-1",)
        ).fetchone() is not None

        upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        assert VERSION in {int(module.VERSION) for module in discover_migrations()}

        for table_name in _REVISION_TABLES:
            column = connection.execute(
                """
                SELECT data_type, is_nullable, column_default
                  FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = ?
                   AND column_name = 'revision'
                """,
                (table_name,),
            ).fetchone()
            assert column is not None
            assert column[0] == "integer"
            assert column[1] == "NO"
            assert str(column[2]) == "1"

            row_id = f"revision-default-{table_name}"
            connection.execute(
                f"INSERT INTO {table_name} (id) VALUES (?)",
                (row_id,),
            )
            revision = connection.execute(
                f"SELECT revision FROM {table_name} WHERE id = ?",
                (row_id,),
            ).fetchone()[0]
            assert revision == 1

        legacy = connection.execute(
            "SELECT revision, pool_id, device_id, interface_id "
            "FROM ip_addresses WHERE id = ?",
            ("legacy-address",),
        ).fetchone()
        assert legacy[0] == 1
        assert legacy[1] is None
        assert legacy[2] == "legacy-device"
        assert legacy[3] == "legacy-interface"

        pool_fk = connection.execute(
            """
            SELECT confdeltype, pg_get_constraintdef(oid, true), convalidated
              FROM pg_constraint
             WHERE conrelid = 'ip_addresses'::regclass
               AND conname = 'fk_ip_addresses_pool'
            """
        ).fetchone()
        assert pool_fk is not None
        assert pool_fk[0] == "r"
        assert pool_fk[2] is True
        assert (
            "FOREIGN KEY (pool_id) REFERENCES ipam_pools(id) ON DELETE RESTRICT"
            in pool_fk[1]
        )

        for constraint_name in (
            "fk_ip_addresses_device",
            "fk_ip_addresses_interface",
        ):
            assignment_fk = connection.execute(
                """
                SELECT convalidated, confdeltype, pg_get_constraintdef(oid, true)
                  FROM pg_constraint
                 WHERE conrelid = 'ip_addresses'::regclass
                   AND conname = ?
                """,
                (constraint_name,),
            ).fetchone()
            assert assignment_fk is not None
            assert assignment_fk[0] is False
            assert assignment_fk[1] == "n"
            assert "ON DELETE SET NULL" in assignment_fk[2]

        _expect_integrity_error(
            connection,
            "INSERT INTO ip_addresses (id, address, device_id) VALUES (?, ?, ?)",
            ("invalid-device", "192.0.2.20", "missing-device"),
            "m0311_invalid_device",
        )
        _expect_integrity_error(
            connection,
            "INSERT INTO ip_addresses (id, address, interface_id) VALUES (?, ?, ?)",
            ("invalid-interface", "192.0.2.21", "missing-interface"),
            "m0311_invalid_interface",
        )

        connection.execute(
            "INSERT INTO ip_addresses (id, address, pool_id) VALUES (?, ?, ?)",
            ("assigned-address", "192.0.2.11", "pool-1"),
        )
        _expect_integrity_error(
            connection,
            "INSERT INTO ip_addresses (id, address, pool_id) VALUES (?, ?, ?)",
            ("invalid-pool", "192.0.2.12", "missing-pool"),
            "m0311_invalid_pool",
        )
        _expect_integrity_error(
            connection,
            "DELETE FROM ipam_pools WHERE id = ?",
            ("pool-1",),
            "m0311_pool_restrict",
        )

        connection.execute(
            "INSERT INTO ip_addresses (id, address, device_id, interface_id) "
            "VALUES (?, ?, ?, ?)",
            ("linked-address", "192.0.2.13", "device-1", "interface-1"),
        )
        connection.execute("DELETE FROM interfaces WHERE id = ?", ("interface-1",))
        assert connection.execute(
            "SELECT interface_id FROM ip_addresses WHERE id = ?", ("linked-address",)
        ).fetchone()[0] is None
        connection.execute("DELETE FROM devices WHERE id = ?", ("device-1",))
        assert connection.execute(
            "SELECT device_id FROM ip_addresses WHERE id = ?", ("linked-address",)
        ).fetchone()[0] is None

        idempotency_count = connection.execute(
            "SELECT COUNT(*) FROM ipam_idempotency_records"
        ).fetchone()[0]
        assert idempotency_count == 0
        idempotency_columns = connection.execute(
            """
            SELECT column_name, data_type, is_nullable
              FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'ipam_idempotency_records'
            """
        ).fetchall()
        idempotency_shapes = {
            str(row[0]): (str(row[1]), str(row[2]))
            for row in idempotency_columns
        }
        assert idempotency_shapes == {
            "tenant_id": ("text", "NO"),
            "operation": ("text", "NO"),
            "idempotency_key": ("text", "NO"),
            "request_hash": ("text", "NO"),
            "response_json": ("jsonb", "NO"),
            "resource_type": ("text", "NO"),
            "resource_id": ("text", "NO"),
            "created_at": ("timestamp with time zone", "NO"),
        }
        identity_constraint = connection.execute(
            """
            SELECT contype, convalidated, pg_get_constraintdef(oid, true)
              FROM pg_constraint
             WHERE conrelid = 'ipam_idempotency_records'::regclass
               AND conname = 'uq_ipam_idempotency_records_tenant_operation_key'
            """
        ).fetchone()
        assert identity_constraint is not None
        assert identity_constraint[0] == "u"
        assert identity_constraint[1] is True
        assert (
            "UNIQUE (tenant_id, operation, idempotency_key)"
            in identity_constraint[2]
        )

        record_values = (
            "tenant-a",
            "allocate_ip",
            "request-1",
            "sha256:request-1",
            '{"id":"ip-address-1"}',
            "ip_address",
            "ip-address-1",
        )
        insert_record_sql = """
            INSERT INTO ipam_idempotency_records (
                tenant_id, operation, idempotency_key, request_hash, response_json,
                resource_type, resource_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        connection.execute(insert_record_sql, record_values)
        stored_record = connection.execute(
            """
            SELECT response_json ->> 'id', created_at IS NOT NULL
              FROM ipam_idempotency_records
             WHERE tenant_id = ? AND operation = ? AND idempotency_key = ?
            """,
            record_values[:3],
        ).fetchone()
        assert stored_record[0] == "ip-address-1"
        assert stored_record[1] is True
        _expect_integrity_error(
            connection,
            insert_record_sql,
            record_values,
            "m0311_duplicate_idempotency",
        )
        connection.execute(
            insert_record_sql,
            ("tenant-b", *record_values[1:]),
        )
        connection.execute(
            insert_record_sql,
            (record_values[0], "reserve_ip", *record_values[2:]),
        )
    finally:
        try:
            connection._force_close()
        finally:
            drop_test_database(target)
