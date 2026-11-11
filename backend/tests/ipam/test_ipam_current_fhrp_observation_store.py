from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from database import get_db_connection
from database.migrations import discover_migrations
from database.migrations.m0318_ipam_current_fhrp_observations import VERSION, upgrade
from services.ipam_current_fhrp_observation_service import (
    begin_current_fhrp_collection,
    finish_current_fhrp_collection,
    get_current_fhrp_collection_states,
    list_current_fhrp_observations,
)


_FORBIDDEN_DML = re.compile(r"\b(insert|update|delete|truncate)\b", re.IGNORECASE)
_FORMAL_IPAM_TABLES = ("ip_addresses", "ipam_vips")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _seed_device(device_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING"
        )
        conn.execute(
            """INSERT INTO devices (id, hostname, tenant_id, status)
                   VALUES (?, ?, 'tenant-default', 'online')""",
            (device_id, device_id),
        )
        conn.commit()


def _collect(
    *, device_id: str, protocol: str, observations: list[dict],
    status: str = "complete", error_code: str = "",
) -> tuple[int, int]:
    attempted_at = _now()
    with get_db_connection() as conn:
        generation = begin_current_fhrp_collection(
            conn,
            device_id=device_id,
            protocol=protocol,
            attempted_at=attempted_at,
            run_id=f"{device_id}-{protocol}-{attempted_at}",
        )
        conn.commit()
    with get_db_connection() as conn:
        count = finish_current_fhrp_collection(
            conn,
            device_id=device_id,
            protocol=protocol,
            generation=generation,
            status=status,
            attempted_at=attempted_at,
            completed_at=_now(),
            observations=observations,
            run_id=f"{device_id}-{protocol}-{attempted_at}",
            error_code=error_code,
        )
        conn.commit()
    return generation, count


def _observation(
    *, interface: str = "GigabitEthernet0/1", virtual_ip: str | None = "192.0.2.1",
    family: int = 4, group_id: int = 10,
) -> dict:
    return {
        "group_id": group_id,
        "address_family": family,
        "interface_name": interface,
        "priority": 110,
        "state": "Active",
        "master_address": "192.0.2.10" if family == 4 else None,
        "virtual_ip": virtual_ip,
        "virtual_mac": "0000.0c9f.f00a" if virtual_ip else None,
        "metadata": {"source": "fixture"},
    }


class _SQLGuard:
    def __init__(self, connection, *, history_tables: tuple[str, ...]):
        self._connection = connection
        self._history_tables = tuple(name.casefold() for name in history_tables)
        self.statements: list[str] = []

    def execute(self, statement, *args, **kwargs):
        sql = str(statement)
        lowered = sql.casefold()
        forbidden_history = [name for name in self._history_tables if name in lowered]
        assert not forbidden_history, f"FHRP current store touched discovery history: {forbidden_history}"
        if _FORBIDDEN_DML.search(lowered):
            assert not any(table in lowered for table in _FORMAL_IPAM_TABLES), (
                f"FHRP current store wrote formal IPAM rows: {sql}"
            )
        self.statements.append(sql)
        return self._connection.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _history_table_names(conn) -> tuple[str, ...]:
    rows = conn.execute(
        """SELECT table_name
             FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_type = 'BASE TABLE'
              AND table_name ILIKE '%discovery%'"""
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def test_m0318_creates_current_fhrp_tables_and_is_idempotent(isolated_db):
    del isolated_db
    with get_db_connection() as conn:
        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        observation_columns = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                """SELECT column_name, udt_name, is_nullable
                     FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'ipam_current_fhrp_observations'"""
            ).fetchall()
        }
    assert VERSION in {int(module.VERSION) for module in discover_migrations()}
    assert observation_columns["master_address"] == ("inet", "YES")
    assert observation_columns["virtual_ip"] == ("inet", "YES")
    assert observation_columns["virtual_ip_key"] == ("text", "NO")
    assert observation_columns["metadata_json"] == ("jsonb", "NO")
    assert "ip_address" not in observation_columns


def test_m0318_hsrp_catalog_failure_rolls_back_and_retry_is_idempotent(isolated_db):
    del isolated_db
    with get_db_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS ipam_current_fhrp_observations")
        conn.execute("DROP TABLE IF EXISTS ipam_current_fhrp_collection_states")
        conn.commit()

    def fail_after_m0318_ddl(cursor, use_pg: bool) -> None:
        upgrade(cursor, use_pg)
        raise RuntimeError("synthetic m0318 failure after DDL")

    with get_db_connection() as conn:
        with pytest.raises(RuntimeError, match="synthetic m0318 failure after DDL"):
            fail_after_m0318_ddl(conn.cursor(), use_pg=True)
        conn.rollback()
        assert conn.execute(
            "SELECT to_regclass('ipam_current_fhrp_collection_states')"
        ).fetchone()[0] is None
        assert conn.execute(
            "SELECT to_regclass('ipam_current_fhrp_observations')"
        ).fetchone()[0] is None

        def catalog_snapshot() -> tuple:
            columns = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT table_name, column_name, udt_name, is_nullable, column_default
                         FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name IN (
                              'ipam_current_fhrp_collection_states',
                              'ipam_current_fhrp_observations'
                          )
                        ORDER BY table_name, ordinal_position"""
                ).fetchall()
            )
            constraints = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT conrelid::regclass::text, conname,
                              pg_get_constraintdef(oid, true)
                         FROM pg_constraint
                        WHERE conrelid IN (
                            'ipam_current_fhrp_collection_states'::regclass,
                            'ipam_current_fhrp_observations'::regclass
                        )
                        ORDER BY conrelid::regclass::text, conname"""
                ).fetchall()
            )
            indexes = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT tablename, indexname, indexdef FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND tablename IN (
                              'ipam_current_fhrp_collection_states',
                              'ipam_current_fhrp_observations'
                          )
                        ORDER BY tablename, indexname"""
                ).fetchall()
            )
            return columns, constraints, indexes

        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        first_catalog = catalog_snapshot()
        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        assert first_catalog == catalog_snapshot()
        assert VERSION in {int(module.VERSION) for module in discover_migrations()}

    device_id = "m0318-hsrp-unknown-device"
    _seed_device(device_id)
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_current_fhrp_collection_states (device_id, protocol)
               VALUES (?, 'hsrp')""",
            (device_id,),
        )
        conn.execute(
            """INSERT INTO ipam_current_fhrp_observations (
                   device_id, protocol, group_id, address_family, interface_name,
                   normalized_interface_name, priority, state, master_address,
                   virtual_ip, virtual_ip_key, virtual_mac, generation, observed_at,
                   run_id, metadata_json
               ) VALUES (
                   ?, 'hsrp', 10, 4, 'Vlan10', 'vlan10', 110, 'active',
                   NULL, '192.0.2.1'::inet, '192.0.2.1', NULL, 1,
                   CURRENT_TIMESTAMP, 'm0318-unknown-run', '{}'::jsonb
               )""",
            (device_id,),
        )
        conn.commit()
        row = conn.execute(
            """SELECT protocol, group_id, address_family, virtual_ip_key
                 FROM ipam_current_fhrp_observations WHERE device_id = ?""",
            (device_id,),
        ).fetchone()
    assert tuple(row) == ("hsrp", 10, 4, "192.0.2.1")

def test_current_fhrp_identity_isolated_by_device_protocol_family_interface_and_vip(isolated_db):
    del isolated_db
    device_a = "current-fhrp-device-a"
    device_b = "current-fhrp-device-b"
    _seed_device(device_a)
    _seed_device(device_b)

    _collect(
        device_id=device_a,
        protocol="hsrp",
        observations=[
            _observation(interface="GigabitEthernet0/1", virtual_ip="192.0.2.1"),
            _observation(interface="GigabitEthernet0/2", virtual_ip="192.0.2.1"),
            _observation(interface="GigabitEthernet0/1", virtual_ip="192.0.2.2"),
            _observation(interface="GigabitEthernet0/1", virtual_ip="2001:db8::1", family=6),
        ],
    )
    _collect(
        device_id=device_a,
        protocol="vrrp",
        observations=[_observation(interface="GigabitEthernet0/1", virtual_ip="192.0.2.1")],
    )
    _collect(
        device_id=device_b,
        protocol="hsrp",
        observations=[_observation(interface="GigabitEthernet0/1", virtual_ip="192.0.2.1")],
    )

    with get_db_connection() as conn:
        all_rows = list_current_fhrp_observations(conn)
        device_a_hsrp = list_current_fhrp_observations(conn, device_id=device_a, protocol="hsrp")
    assert len(all_rows) == 6
    assert len(device_a_hsrp) == 4
    assert {row["normalized_interface_name"] for row in device_a_hsrp} >= {"gi0/1", "gi0/2"}
    assert {row["virtual_ip_key"] for row in device_a_hsrp} == {
        "192.0.2.1", "192.0.2.2", "2001:db8::1",
    }
    assert {row["address_family"] for row in device_a_hsrp} == {4, 6}
    assert {row["protocol"] for row in all_rows} == {"hsrp", "vrrp"}
    assert {row["device_id"] for row in all_rows} == {device_a, device_b}


def test_complete_replaces_only_one_pair_and_empty_complete_clears_it(isolated_db):
    del isolated_db
    device_a = "current-fhrp-replace-a"
    device_b = "current-fhrp-replace-b"
    _seed_device(device_a)
    _seed_device(device_b)
    _collect(device_id=device_a, protocol="hsrp", observations=[_observation(), _observation(interface="Vlan20", virtual_ip="192.0.2.20")])
    _collect(device_id=device_a, protocol="vrrp", observations=[_observation(virtual_ip="192.0.2.30")])
    _collect(device_id=device_b, protocol="hsrp", observations=[_observation(virtual_ip="192.0.2.40")])

    second_generation, second_count = _collect(
        device_id=device_a,
        protocol="hsrp",
        observations=[_observation(virtual_ip="192.0.2.2")],
    )
    assert second_count == 1
    with get_db_connection() as conn:
        rows_after_replace = list_current_fhrp_observations(conn)
    assert len(rows_after_replace) == 3
    replaced_rows = [row for row in rows_after_replace if row["device_id"] == device_a and row["protocol"] == "hsrp"]
    assert [row["virtual_ip_key"] for row in replaced_rows] == ["192.0.2.2"]
    assert replaced_rows[0]["generation"] == second_generation

    empty_generation, empty_count = _collect(device_id=device_a, protocol="hsrp", observations=[])
    assert empty_count == 0
    with get_db_connection() as conn:
        final_rows = list_current_fhrp_observations(conn)
        states = get_current_fhrp_collection_states(conn, device_id=device_a, protocol="hsrp")
    assert len(final_rows) == 2
    assert not [row for row in final_rows if row["device_id"] == device_a and row["protocol"] == "hsrp"]
    assert states[0]["latest_status"] == "complete"
    assert states[0]["last_success_generation"] == empty_generation
    assert states[0]["current_row_count"] == 0


@pytest.mark.parametrize("status", ["partial", "failed", "unsupported"])
def test_incomplete_fhrp_attempts_retain_previous_rows(isolated_db, status):
    del isolated_db
    device_id = f"current-fhrp-retain-{status}"
    _seed_device(device_id)
    successful_generation, _ = _collect(
        device_id=device_id,
        protocol="hsrp",
        observations=[_observation()],
    )
    _, retained_count = _collect(
        device_id=device_id,
        protocol="hsrp",
        observations=[],
        status=status,
        error_code="fixture_error",
    )
    with get_db_connection() as conn:
        rows = list_current_fhrp_observations(conn, device_id=device_id)
        states = get_current_fhrp_collection_states(conn, device_id=device_id)
    assert retained_count == 1
    assert len(rows) == 1
    assert rows[0]["generation"] == successful_generation
    assert states[0]["latest_status"] == status
    assert states[0]["last_success_generation"] == successful_generation
    assert states[0]["last_error_code"] == "fixture_error"


def test_stale_fhrp_generation_is_fenced(isolated_db):
    del isolated_db
    device_id = "current-fhrp-stale"
    _seed_device(device_id)
    attempted_at = _now()
    with get_db_connection() as conn:
        older_generation = begin_current_fhrp_collection(
            conn, device_id=device_id, protocol="vrrp", attempted_at=attempted_at,
        )
        conn.commit()
    with get_db_connection() as conn:
        current_generation = begin_current_fhrp_collection(
            conn, device_id=device_id, protocol="vrrp", attempted_at=_now(),
        )
        conn.commit()

    with get_db_connection() as conn:
        with pytest.raises(ValueError, match="collection_generation_superseded"):
            finish_current_fhrp_collection(
                conn,
                device_id=device_id,
                protocol="vrrp",
                generation=older_generation,
                status="complete",
                attempted_at=attempted_at,
                completed_at=_now(),
                observations=[_observation()],
            )
        conn.rollback()
    with get_db_connection() as conn:
        assert finish_current_fhrp_collection(
            conn,
            device_id=device_id,
            protocol="vrrp",
            generation=current_generation,
            status="complete",
            attempted_at=attempted_at,
            completed_at=_now(),
            observations=[_observation()],
        ) == 1
        conn.commit()


@pytest.mark.parametrize(
    ("protocol", "record", "attempted_at", "error"),
    [
        ("glbp", _observation(), None, "protocol_invalid"),
        ("hsrp", _observation(family=5), None, "address_family_invalid"),
        ("hsrp", {**_observation(), "virtual_ip": "2001:db8::1"}, None, "virtual_ip_family_mismatch"),
        ("hsrp", {**_observation(), "master_address": "192.0.2.999"}, None, "master_address_invalid"),
        ("hsrp", {**_observation(), "virtual_mac": "not-a-mac"}, None, "virtual_mac_invalid"),
        ("hsrp", _observation(family=0), None, "virtual_ip_family_mismatch"),
        ("hsrp", _observation(), "2026-11-09T12:00:00", "attempted_at_timezone_required"),
    ],
)
def test_invalid_fhrp_input_is_rejected(isolated_db, protocol, record, attempted_at, error):
    del isolated_db
    device_id = "current-fhrp-invalid"
    _seed_device(device_id)
    attempt_value = attempted_at or _now()
    if error == "protocol_invalid":
        with get_db_connection() as conn:
            with pytest.raises(ValueError, match=error):
                begin_current_fhrp_collection(
                    conn, device_id=device_id, protocol=protocol, attempted_at=attempt_value,
                )
        return

    with get_db_connection() as conn:
        generation = begin_current_fhrp_collection(
            conn, device_id=device_id, protocol=protocol, attempted_at=_now(),
        )
        conn.commit()
    with get_db_connection() as conn:
        with pytest.raises(ValueError, match=error):
            finish_current_fhrp_collection(
                conn,
                device_id=device_id,
                protocol=protocol,
                generation=generation,
                status="complete",
                attempted_at=attempt_value,
                completed_at=_now(),
                observations=[record],
            )
        conn.rollback()


def test_duplicate_fhrp_identity_is_rejected(isolated_db):
    del isolated_db
    device_id = "current-fhrp-duplicate"
    _seed_device(device_id)
    attempted_at = _now()
    with get_db_connection() as conn:
        generation = begin_current_fhrp_collection(
            conn, device_id=device_id, protocol="hsrp", attempted_at=attempted_at,
        )
        conn.commit()
    with get_db_connection() as conn:
        with pytest.raises(ValueError, match="duplicate_observation_identity"):
            finish_current_fhrp_collection(
                conn,
                device_id=device_id,
                protocol="hsrp",
                generation=generation,
                status="complete",
                attempted_at=attempted_at,
                completed_at=_now(),
                observations=[_observation(), _observation()],
            )
        conn.rollback()


def test_current_fhrp_store_sql_stays_out_of_history_and_formal_ipam(isolated_db):
    del isolated_db
    device_id = "current-fhrp-sql-guard"
    _seed_device(device_id)
    with get_db_connection() as conn:
        history_tables = _history_table_names(conn)
        before = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in _FORMAL_IPAM_TABLES
        }
        guard = _SQLGuard(conn, history_tables=history_tables)
        attempted_at = _now()
        generation = begin_current_fhrp_collection(
            guard, device_id=device_id, protocol="hsrp", attempted_at=attempted_at,
        )
        finish_current_fhrp_collection(
            guard,
            device_id=device_id,
            protocol="hsrp",
            generation=generation,
            status="complete",
            attempted_at=attempted_at,
            completed_at=_now(),
            observations=[_observation()],
        )
        listed = list_current_fhrp_observations(guard, device_id=device_id)
        states = get_current_fhrp_collection_states(guard, device_id=device_id)
        conn.commit()
        after = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in _FORMAL_IPAM_TABLES
        }
    assert len(listed) == 1
    assert len(states) == 1
    assert all(table not in statement.casefold() for statement in guard.statements for table in history_tables)
    assert before == after
