from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.tests.pg_test_utils import drop_test_database, postgresql_test_driver
from database import get_db_connection
from database.migrations import discover_migrations
from database.migrations.m0314_ipam_current_endpoint_observations import VERSION, upgrade
from services.ipam_address_space_service import create_address_space
from services.ipam_current_endpoint_observation_service import (
    begin_current_endpoint_collection,
    finish_current_endpoint_collection,
    get_current_endpoint_collection_states,
    list_current_endpoint_observations,
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def test_m0314_creates_only_current_arp_state_and_identity_idempotently() -> None:
    connection = postgresql_test_driver.connect()
    target = connection._target
    try:
        connection.execute("CREATE TABLE devices (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO devices (id) VALUES ('arp-device')")
        connection.commit()

        upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        assert VERSION in {int(module.VERSION) for module in discover_migrations()}
        observation_columns = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                """SELECT column_name, data_type, is_nullable
                     FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'ipam_current_endpoint_observations'"""
            ).fetchall()
        }
        assert observation_columns["ip_address"] == ("inet", "NO")
        assert observation_columns["local_context_key"] == ("text", "NO")
        assert "address_space_id" not in observation_columns

        connection.execute(
            """INSERT INTO ipam_endpoint_collection_states (
                   device_id, observation_source, context_source,
                   context_type, local_context_key
               ) VALUES
                   ('arp-device', 'arp', 'cli', 'global', 'default'),
                   ('arp-device', 'arp', 'cli', 'global', 'route-blue'),
                   ('arp-device', 'arp', 'cli', 'unknown', ''),
                   ('arp-device', 'arp', 'cli', 'unknown', 'global-alias')"""
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM ipam_endpoint_collection_states"
        ).fetchone()[0] == 4

        values = (
            "arp-device", "arp", "cli", "global", "default", "Default routing table",
            "198.51.100.44", "001122334455", "Vlan10", "vlan10", 10,
            1, _now(), "run-1", "{}",
        )
        insert_sql = """INSERT INTO ipam_current_endpoint_observations (
                           source_device_id, observation_source, context_source,
                           context_type, local_context_key, local_context_name,
                           ip_address, mac_address, interface_name,
                           normalized_interface_name, vlan_key, generation,
                           observed_at, run_id, metadata_json
                       ) VALUES (?, ?, ?, ?, ?, ?, ?::inet, ?, ?, ?, ?, ?, ?, ?, ?::jsonb)"""
        connection.execute(insert_sql, values)
        connection.execute(
            insert_sql,
            (values[0], values[1], values[2], "vrf", "BLUE", "Blue", *values[6:]),
        )
        connection.commit()
        assert connection.execute(
            "SELECT COUNT(*) FROM ipam_current_endpoint_observations"
        ).fetchone()[0] == 2

        with pytest.raises(postgresql_test_driver.IntegrityError):
            connection.execute(insert_sql, values)
        connection.rollback()
        assert connection.execute(
            "SELECT COUNT(*) FROM ipam_current_endpoint_observations"
        ).fetchone()[0] == 2
    finally:
        connection.close()
        drop_test_database(target)


def _insert_device(device_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices
                   (id, hostname, ip_address, platform, status, site_id, tenant_id)
               VALUES (?, ?, '192.0.2.44', 'cisco_ios', 'online', 'site-arp-current', 'tenant-default')""",
            (device_id, device_id),
        )
        conn.commit()


def _map_context(
    device_id: str,
    key: str,
    address_space_id: str,
    *,
    context_source: str = "cli",
    context_type: str = "global",
) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts
                   (id, device_id, context_source, context_type, local_context_key,
                    local_context_name, address_space_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                f'mapping-{device_id}-{context_source}-{context_type}-{key}',
                device_id, context_source, context_type, key, key, address_space_id,
            ),
        )
        conn.commit()


def test_current_projection_preserves_scopes_unknowns_and_last_success(isolated_db) -> None:
    device_id = "arp-current-device"
    _insert_device(device_id)
    first_space = create_address_space(
        name="ARP Test Global A", kind="global", vrf_id=None,
        security_tenant_id="tenant-default",
    )
    second_space = create_address_space(
        name="ARP Test Global B", kind="global", vrf_id=None,
        security_tenant_id="tenant-default",
    )
    _map_context(device_id, "default", first_space["id"])
    _map_context(device_id, "routing-table-2", second_space["id"])

    contexts = [
        ("global", "default", "complete", 10, "Vlan10"),
        ("global", "routing-table-2", "complete", 20, "Vlan20"),
        ("unknown", "", "scope_unknown", 30, "Vlan30"),
    ]
    generations: dict[tuple[str, str], int] = {}
    for context_type, context_key, status, vlan, interface in contexts:
        attempted_at = _now()
        with get_db_connection() as conn:
            generation = begin_current_endpoint_collection(
                conn,
                device_id=device_id,
                context_source="cli",
                context_type=context_type,
                local_context_key=context_key,
                attempted_at=attempted_at,
                run_id=f"arp-{context_key or 'unknown'}-1",
            )
            conn.commit()
        generations[(context_type, context_key)] = generation
        observation = {
            "ip": "198.51.100.44", "mac": "00:11:22:33:44:55", "vlan_id": vlan,
            "interface": interface, "context_source": "cli", "context_type": context_type,
            "local_context_key": context_key,
        }
        with get_db_connection() as conn:
            assert finish_current_endpoint_collection(
                conn,
                device_id=device_id,
                context_source="cli",
                context_type=context_type,
                local_context_key=context_key,
                generation=generation,
                status=status,
                attempted_at=attempted_at,
                completed_at=_now(),
                observations=[observation],
                run_id=f"arp-{context_key or 'unknown'}-1",
            ) == 1
            conn.commit()

    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id)
        state = get_current_endpoint_collection_states(conn, device_id=device_id)[0]
    assert len(rows) == 3
    assert {row["address_space_id"] for row in rows if row["context_type"] == "global"} == {
        first_space["id"], second_space["id"],
    }
    unknown = next(row for row in rows if row["context_type"] == "unknown")
    assert unknown["local_context_key"] == ""
    assert unknown["address_space_id"] is None
    assert all(row["ip_address"] == "198.51.100.44" for row in rows)
    with get_db_connection() as conn:
        states = {
            (row["context_type"], row["local_context_key"]): row
            for row in get_current_endpoint_collection_states(conn, device_id=device_id)
        }
    assert state["latest_status"] in {"complete", "scope_unknown"}
    assert states[("global", "default")]["latest_status"] == "complete"
    assert states[("global", "routing-table-2")]["latest_status"] == "complete"
    assert states[("unknown", "")]["latest_status"] == "scope_unknown"
    assert states[("global", "default")]["last_success_generation"] == generations[("global", "default")]
    assert states[("unknown", "")]["current_row_count"] == 1

    failed_generation = None
    with get_db_connection() as conn:
        failed_generation = begin_current_endpoint_collection(
            conn, device_id=device_id, context_source="cli", context_type="global",
            local_context_key="routing-table-2", attempted_at=_now(), run_id="arp-run-2",
        )
        conn.commit()
    with get_db_connection() as conn:
        assert finish_current_endpoint_collection(
            conn,
            device_id=device_id,
            context_source="cli",
            context_type="global",
            local_context_key="routing-table-2",
            generation=failed_generation,
            status="failed",
            attempted_at=_now(),
            completed_at=_now(),
            observations=[],
            run_id="arp-run-2",
            error_code="ssh_failed",
        ) == 1
        conn.commit()
    with get_db_connection() as conn:
        preserved = list_current_endpoint_observations(conn, device_id=device_id)
        failed_state = next(
            row for row in get_current_endpoint_collection_states(conn, device_id=device_id)
            if row["context_type"] == "global" and row["local_context_key"] == "routing-table-2"
        )
    assert len(preserved) == 3
    assert {
        row["latest_status"] for row in preserved
        if row["local_context_key"] == "routing-table-2"
    } == {"failed"}
    assert {
        row["latest_status"] for row in preserved
        if row["local_context_key"] == "default"
    } == {"complete"}
    assert {
        row["latest_status"] for row in preserved
        if row["context_type"] == "unknown"
    } == {"scope_unknown"}
    assert failed_state["last_success_generation"] == generations[("global", "routing-table-2")]
    assert failed_state["latest_attempt_generation"] == failed_generation
    assert failed_state["last_error_code"] == "ssh_failed"

    empty_generation = None
    with get_db_connection() as conn:
        empty_generation = begin_current_endpoint_collection(
            conn, device_id=device_id, context_source="cli", context_type="global",
            local_context_key="default", attempted_at=_now(), run_id="arp-run-3",
        )
        conn.commit()
    with get_db_connection() as conn:
        assert finish_current_endpoint_collection(
            conn,
            device_id=device_id,
            context_source="cli",
            context_type="global",
            local_context_key="default",
            generation=empty_generation,
            status="complete",
            attempted_at=_now(),
            completed_at=_now(),
            observations=[],
            run_id="arp-run-3",
        ) == 0
        conn.commit()
    with get_db_connection() as conn:
        remaining = list_current_endpoint_observations(conn, device_id=device_id)
        empty_state = next(
            row for row in get_current_endpoint_collection_states(conn, device_id=device_id)
            if row["context_type"] == "global" and row["local_context_key"] == "default"
        )
    assert len(remaining) == 2
    assert {row["local_context_key"] for row in remaining} == {"routing-table-2", ""}
    assert empty_state["latest_status"] == "complete"
    assert empty_state["last_success_generation"] == empty_generation
    assert empty_state["current_row_count"] == 0


def test_current_projection_fences_runs_and_preserves_unknown_raw_context(isolated_db) -> None:
    device_id = "arp-current-fence-device"
    _insert_device(device_id)
    with get_db_connection() as conn, pytest.raises(ValueError, match="known_context_key_required"):
        begin_current_endpoint_collection(
            conn, device_id=device_id, context_source="cli", context_type="global",
            local_context_key="", attempted_at=_now(), run_id="missing-key",
        )
    with get_db_connection() as conn:
        old_generation = begin_current_endpoint_collection(
            conn, device_id=device_id, context_source="cli", context_type="unknown",
            local_context_key="looks-global", attempted_at=_now(), run_id="old",
        )
        conn.commit()
    with get_db_connection() as conn:
        current_generation = begin_current_endpoint_collection(
            conn, device_id=device_id, context_source="cli", context_type="unknown",
            local_context_key="looks-global", attempted_at=_now(), run_id="current",
        )
        conn.commit()
    with get_db_connection() as conn, pytest.raises(ValueError, match="superseded"):
        finish_current_endpoint_collection(
            conn,
            device_id=device_id,
            context_source="cli",
            context_type="unknown",
            local_context_key="looks-global",
            generation=old_generation,
            status="scope_unknown",
            attempted_at=_now(),
            completed_at=_now(),
            observations=[],
            run_id="old",
        )

    with get_db_connection() as conn:
        assert finish_current_endpoint_collection(
            conn,
            device_id=device_id,
            context_source="cli",
            context_type="unknown",
            local_context_key="looks-global",
            generation=current_generation,
            status="scope_unknown",
            attempted_at=_now(),
            completed_at=_now(),
            observations=[{
                "ip": "198.51.100.45", "mac": "001122334466",
                "context_source": "cli", "context_type": "unknown",
                "local_context_key": "looks-global",
            }],
            run_id="current",
        ) == 1
        conn.commit()

    with get_db_connection() as conn:
        row = list_current_endpoint_observations(conn, device_id=device_id)[0]
        state = get_current_endpoint_collection_states(
            conn, device_id=device_id, context_source="cli", context_type="unknown",
            local_context_key="looks-global",
        )[0]
    assert row["local_context_key"] == "looks-global"
    assert row["address_space_id"] is None
    assert row["routing_context_mapping_id"] is None
    assert state["latest_status"] == "scope_unknown"


def test_unknown_raw_context_resolves_only_to_one_valid_active_mapping(isolated_db) -> None:
    device_id = "arp-current-mapping-device"
    _insert_device(device_id)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES ('tenant-arp-other', 'ARP Other') ON CONFLICT (id) DO NOTHING"
        )
        conn.execute(
            "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES ('vrf-arp-kind', 'ARP Kind VRF', 'tenant-default')"
        )
        conn.commit()

    good_space = create_address_space(
        name="ARP Mapping Good", kind="global", vrf_id=None,
        security_tenant_id="tenant-default",
    )
    foreign_space = create_address_space(
        name="ARP Mapping Foreign", kind="global", vrf_id=None,
        security_tenant_id="tenant-arp-other",
    )
    inactive_space = create_address_space(
        name="ARP Mapping Inactive", kind="global", vrf_id=None,
        security_tenant_id="tenant-default",
    )
    vrf_space = create_address_space(
        name="ARP Mapping VRF", kind="vrf", vrf_id="vrf-arp-kind",
        security_tenant_id="tenant-default",
    )
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE ipam_address_spaces SET status = 'inactive' WHERE id = ?",
            (inactive_space["id"],),
        )
        conn.commit()

    _map_context(device_id, "good", good_space["id"])
    _map_context(device_id, "foreign", foreign_space["id"])
    _map_context(device_id, "inactive", inactive_space["id"])
    _map_context(device_id, "wrong-kind", vrf_space["id"])
    _map_context(device_id, "global-alias", good_space["id"])
    _map_context(device_id, "ambiguous", good_space["id"], context_type="global")
    _map_context(device_id, "ambiguous", vrf_space["id"], context_type="vrf")

    test_contexts = [
        ("global", "good", "complete"),
        ("global", "foreign", "complete"),
        ("global", "inactive", "complete"),
        ("global", "wrong-kind", "complete"),
        ("unknown", "global-alias", "scope_unknown"),
        ("unknown", "ambiguous", "scope_unknown"),
        ("unknown", "unmapped", "scope_unknown"),
    ]
    for context_type, context_key, status in test_contexts:
        attempted_at = _now()
        with get_db_connection() as conn:
            generation = begin_current_endpoint_collection(
                conn, device_id=device_id, context_source="cli", context_type=context_type,
                local_context_key=context_key, attempted_at=attempted_at,
                run_id=f"mapping-{context_key}",
            )
            conn.commit()
        with get_db_connection() as conn:
            assert finish_current_endpoint_collection(
                conn,
                device_id=device_id,
                context_source="cli",
                context_type=context_type,
                local_context_key=context_key,
                generation=generation,
                status=status,
                attempted_at=attempted_at,
                completed_at=_now(),
                observations=[{
                    "ip": "198.51.100.90", "mac": "001122334490",
                    "interface": "Vlan90", "vlan_id": 90,
                    "context_source": "cli", "context_type": context_type,
                    "local_context_key": context_key,
                }],
                run_id=f"mapping-{context_key}",
            ) == 1
            conn.commit()

    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id)
    by_context = {(row["context_type"], row["local_context_key"]): row for row in rows}
    assert by_context[("global", "good")]["address_space_id"] == good_space["id"]
    assert by_context[("global", "good")]["routing_context_mapping_id"] is not None
    assert by_context[("unknown", "global-alias")]["address_space_id"] == good_space["id"]
    assert by_context[("unknown", "global-alias")]["resolved_context_type"] == "global"
    for key in ("foreign", "inactive", "wrong-kind"):
        assert by_context[("global", key)]["address_space_id"] is None
        assert by_context[("global", key)]["routing_context_mapping_id"] is None
    for key in ("ambiguous", "unmapped"):
        assert by_context[("unknown", key)]["address_space_id"] is None
        assert by_context[("unknown", key)]["routing_context_mapping_id"] is None
    assert foreign_space["id"] not in {row["address_space_id"] for row in rows}

def test_m0314_unknown_context_catalog_failure_rolls_back_and_retry_is_idempotent() -> None:
    connection = postgresql_test_driver.connect()
    target = connection._target
    try:
        connection.execute("CREATE TABLE devices (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO devices (id) VALUES ('m0314-unknown-device')")
        connection.commit()

        def fail_after_m0314_ddl(cursor, use_pg: bool) -> None:
            upgrade(cursor, use_pg)
            raise RuntimeError("synthetic m0314 failure after DDL")

        with pytest.raises(RuntimeError, match="synthetic m0314 failure after DDL"):
            fail_after_m0314_ddl(connection.cursor(), use_pg=True)
        connection.rollback()
        assert connection.execute(
            "SELECT to_regclass('ipam_endpoint_collection_states')"
        ).fetchone()[0] is None
        assert connection.execute(
            "SELECT to_regclass('ipam_current_endpoint_observations')"
        ).fetchone()[0] is None

        def catalog_snapshot() -> tuple:
            columns = tuple(
                tuple(row)
                for row in connection.execute(
                    """SELECT table_name, column_name, data_type, is_nullable, column_default
                         FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name IN (
                              'ipam_endpoint_collection_states',
                              'ipam_current_endpoint_observations'
                          )
                        ORDER BY table_name, ordinal_position"""
                ).fetchall()
            )
            constraints = tuple(
                tuple(row)
                for row in connection.execute(
                    """SELECT conrelid::regclass::text, conname,
                              pg_get_constraintdef(oid, true)
                         FROM pg_constraint
                        WHERE conrelid IN (
                            'ipam_endpoint_collection_states'::regclass,
                            'ipam_current_endpoint_observations'::regclass
                        )
                        ORDER BY conrelid::regclass::text, conname"""
                ).fetchall()
            )
            indexes = tuple(
                tuple(row)
                for row in connection.execute(
                    """SELECT tablename, indexname, indexdef FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND tablename IN (
                              'ipam_endpoint_collection_states',
                              'ipam_current_endpoint_observations'
                          )
                        ORDER BY tablename, indexname"""
                ).fetchall()
            )
            return columns, constraints, indexes

        upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        first_catalog = catalog_snapshot()
        upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        second_catalog = catalog_snapshot()
        assert first_catalog == second_catalog
        assert VERSION in {int(module.VERSION) for module in discover_migrations()}

        connection.execute(
            """INSERT INTO ipam_endpoint_collection_states (
                   device_id, observation_source, context_source, context_type,
                   local_context_key
               ) VALUES ('m0314-unknown-device', 'arp', 'cli', 'unknown', '')"""
        )
        connection.execute(
            """INSERT INTO ipam_current_endpoint_observations (
                   source_device_id, observation_source, context_source, context_type,
                   local_context_key, local_context_name, ip_address, mac_address,
                   interface_name, normalized_interface_name, vlan_key, generation,
                   observed_at, run_id, metadata_json
               ) VALUES (
                   'm0314-unknown-device', 'arp', 'cli', 'unknown', '', '',
                   '192.0.2.10'::inet, '001122334455', 'Vlan10', 'vlan10', 0, 1,
                   CURRENT_TIMESTAMP, 'unknown-run', '{}'::jsonb
               )"""
        )
        connection.commit()
        migrated = connection.execute(
            """SELECT context_type, local_context_key, host(ip_address), generation
                 FROM ipam_current_endpoint_observations"""
        ).fetchone()
        assert tuple(migrated) == ("unknown", "", "192.0.2.10", 1)
    finally:
        connection.close()
        drop_test_database(target)
