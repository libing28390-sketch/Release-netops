from __future__ import annotations

from datetime import datetime, timezone

import pytest

from database import get_db_connection
from database.migrations import discover_migrations
from database.migrations.m0316_ipam_current_fdb_observations import VERSION, upgrade
from services.ipam_address_space_service import create_address_space
from services.ipam_current_fdb_observation_service import (
    begin_current_fdb_collection,
    finish_current_fdb_collection,
    get_current_fdb_collection_states,
    list_current_fdb_observations,
)
from services.ipam_routing_context_service import create_device_routing_context


_FORBIDDEN_SQL_TOKENS = (
    "ipam_discovery_observations",
    "ipam_discovery_snapshots",
    "ipam_discovery_scope_assertions",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class _HistoryReadGuard:
    def __init__(self, connection):
        self._connection = connection
        self.statements: list[str] = []

    def execute(self, statement, *args, **kwargs):
        sql = str(statement)
        lowered = sql.casefold()
        if any(token in lowered for token in _FORBIDDEN_SQL_TOKENS):
            raise AssertionError(f"current FDB reader accessed history SQL: {sql}")
        self.statements.append(sql)
        return self._connection.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _seed_device(device_id: str, site_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING"
        )
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, tenant_id)
                   VALUES (?, ?, ?, 'tenant-default') ON CONFLICT(id) DO NOTHING""",
            (site_id, site_id.upper(), f"Site {site_id}"),
        )
        conn.execute(
            """INSERT INTO devices (id, hostname, tenant_id, site_id, status)
                   VALUES (?, ?, 'tenant-default', ?, 'online')""",
            (device_id, device_id, site_id),
        )
        conn.commit()


def _publish(
    *, device_id: str, context_source: str, context_type: str,
    local_context_key: str, status: str, observations: list[dict], run_id: str,
) -> int:
    attempted_at = _now()
    with get_db_connection() as conn:
        generation = begin_current_fdb_collection(
            conn,
            device_id=device_id,
            context_source=context_source,
            context_type=context_type,
            local_context_key=local_context_key,
            attempted_at=attempted_at,
            run_id=run_id,
        )
        conn.commit()
    with get_db_connection() as conn:
        count = finish_current_fdb_collection(
            conn,
            device_id=device_id,
            context_source=context_source,
            context_type=context_type,
            local_context_key=local_context_key,
            generation=generation,
            status=status,
            attempted_at=attempted_at,
            completed_at=_now(),
            observations=observations,
            run_id=run_id,
        )
        conn.commit()
    if status in {"complete", "scope_unknown"}:
        assert count == len(observations)
    return generation


def test_m0316_creates_fdb_projection_and_is_idempotent(isolated_db):
    del isolated_db
    from backend.database.migrations.m0316_ipam_current_fdb_observations import upgrade as upgrade_again

    with get_db_connection() as conn:
        upgrade_again(conn.cursor(), use_pg=True)
        conn.commit()
        columns = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                """SELECT column_name, data_type, is_nullable
                     FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'ipam_current_fdb_observations'"""
            ).fetchall()
        }
        state_source_check = conn.execute(
            """SELECT pg_get_constraintdef(oid)
                 FROM pg_constraint
                WHERE conrelid = 'ipam_endpoint_collection_states'::regclass
                  AND conname = 'ck_ipam_endpoint_state_source'"""
        ).fetchone()[0]
    assert VERSION in {int(module.VERSION) for module in discover_migrations()}
    assert columns["mac_address"] == ("text", "NO")
    assert "ip_address" not in columns
    assert "fdb" in state_source_check


def test_m0316_unknown_context_catalog_failure_rolls_back_and_retry_is_idempotent(
    isolated_db,
) -> None:
    del isolated_db
    _seed_device("m0316-unknown-device", "m0316-unknown-site")
    with get_db_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS ipam_current_fdb_observations")
        conn.execute(
            "ALTER TABLE ipam_endpoint_collection_states "
            "DROP CONSTRAINT IF EXISTS ck_ipam_endpoint_state_source"
        )
        conn.execute(
            "ALTER TABLE ipam_endpoint_collection_states "
            "DROP CONSTRAINT IF EXISTS ipam_endpoint_collection_states_observation_source_check"
        )
        conn.execute(
            """ALTER TABLE ipam_endpoint_collection_states
                   ADD CONSTRAINT ipam_endpoint_collection_states_observation_source_check
                   CHECK (observation_source = 'arp')"""
        )
        conn.commit()

    def fail_after_m0316_ddl(cursor, use_pg: bool) -> None:
        upgrade(cursor, use_pg)
        raise RuntimeError("synthetic m0316 failure after DDL")

    with get_db_connection() as conn:
        with pytest.raises(RuntimeError, match="synthetic m0316 failure after DDL"):
            fail_after_m0316_ddl(conn.cursor(), use_pg=True)
        conn.rollback()
        assert conn.execute(
            "SELECT to_regclass('ipam_current_fdb_observations')"
        ).fetchone()[0] is None
        state_check = conn.execute(
            """SELECT pg_get_constraintdef(oid)
                 FROM pg_constraint
                WHERE conrelid = 'ipam_endpoint_collection_states'::regclass
                  AND conname = 'ipam_endpoint_collection_states_observation_source_check'"""
        ).fetchone()[0]
        assert "observation_source = 'arp'" in state_check
        assert conn.execute(
            """SELECT 1 FROM pg_constraint
                WHERE conrelid = 'ipam_endpoint_collection_states'::regclass
                  AND conname = 'ck_ipam_endpoint_state_source'"""
        ).fetchone() is None

        def catalog_snapshot() -> tuple:
            state_constraints = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT conname, pg_get_constraintdef(oid, true)
                         FROM pg_constraint
                        WHERE conrelid = 'ipam_endpoint_collection_states'::regclass
                          AND conname IN (
                              'ipam_endpoint_collection_states_observation_source_check',
                              'ck_ipam_endpoint_state_source'
                          )
                        ORDER BY conname"""
                ).fetchall()
            )
            fdb_columns = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT column_name, data_type, is_nullable, column_default
                         FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'ipam_current_fdb_observations'
                        ORDER BY ordinal_position"""
                ).fetchall()
            )
            fdb_constraints = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT conname, pg_get_constraintdef(oid, true)
                         FROM pg_constraint
                        WHERE conrelid = 'ipam_current_fdb_observations'::regclass
                        ORDER BY conname"""
                ).fetchall()
            )
            fdb_indexes = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT indexname, indexdef FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND tablename = 'ipam_current_fdb_observations'
                        ORDER BY indexname"""
                ).fetchall()
            )
            return state_constraints, fdb_columns, fdb_constraints, fdb_indexes

        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        first_catalog = catalog_snapshot()
        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        assert first_catalog == catalog_snapshot()

        conn.execute(
            """INSERT INTO ipam_endpoint_collection_states (
                   device_id, observation_source, context_source, context_type,
                   local_context_key
               ) VALUES ('m0316-unknown-device', 'fdb', 'cli', 'unknown', '')"""
        )
        conn.execute(
            """INSERT INTO ipam_current_fdb_observations (
                   source_device_id, observation_source, context_source, context_type,
                   local_context_key, local_context_name, mac_address, interface_name,
                   normalized_interface_name, vlan_key, entry_type, generation,
                   observed_at, run_id, metadata_json
               ) VALUES (
                   'm0316-unknown-device', 'fdb', 'cli', 'unknown', '', '',
                   '001122334455', 'Port-channel1', 'port-channel1', 10, 'dynamic', 1,
                   CURRENT_TIMESTAMP, 'unknown-fdb-run', '{}'::jsonb
               )"""
        )
        conn.commit()
        assert conn.execute(
            """SELECT COUNT(*) FROM ipam_current_fdb_observations
                WHERE source_device_id = 'm0316-unknown-device'
                  AND context_type = 'unknown' AND local_context_key = ''"""
        ).fetchone()[0] == 1

def test_current_fdb_preserves_context_rows_and_only_replaces_complete_scope(isolated_db):
    del isolated_db
    device_id = "current-fdb-device"
    site_id = "current-fdb-site"
    _seed_device(device_id, site_id)
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO vrfs (id, vrf_name, tenant_id)
                   VALUES ('current-fdb-vrf', 'Blue', 'tenant-default')"""
        )
        conn.commit()
    vrf = create_address_space(
        name="Current FDB Blue", kind="vrf", vrf_id="current-fdb-vrf",
        security_tenant_id="tenant-default",
    )
    create_device_routing_context(
        device_id=device_id,
        context_source="snmp",
        context_type="vrf",
        local_context_key="Blue-context",
        local_context_name="Blue",
        address_space_id=vrf["id"],
        security_tenant_id="tenant-default",
    )

    blue_generation = _publish(
        device_id=device_id, context_source="snmp", context_type="vrf",
        local_context_key="Blue-context", status="complete", run_id="fdb-blue-1",
        observations=[
            {"mac": "00:11:22:33:44:55", "vlan_id": 10, "interface": "TenGigabitEthernet1/0/1", "type": "dynamic"},
            {"mac": "00:11:22:33:44:55", "vlan_id": 20, "interface": "TenGigabitEthernet1/0/2", "type": "dynamic"},
        ],
    )
    unknown_generation = _publish(
        device_id=device_id, context_source="cli", context_type="unknown",
        local_context_key="global-alias", status="scope_unknown", run_id="fdb-unknown-1",
        observations=[{"mac": "00:11:22:33:44:55", "vlan_id": 10, "interface": "Port-channel1"}],
    )

    with get_db_connection() as conn:
        guarded = _HistoryReadGuard(conn)
        rows = list_current_fdb_observations(guarded, device_id=device_id)
        states = get_current_fdb_collection_states(guarded, device_id=device_id)
    assert len(rows) == 3
    blue_rows = [row for row in rows if row["local_context_key"] == "Blue-context"]
    unknown = next(row for row in rows if row["local_context_key"] == "global-alias")
    assert {row["address_space_id"] for row in blue_rows} == {vrf["id"]}
    assert unknown["address_space_id"] is None
    assert unknown["resolved_context_type"] is None
    assert {row["generation"] for row in blue_rows} == {blue_generation}
    assert unknown["generation"] == unknown_generation
    assert {row["vlan_id"] for row in blue_rows} == {10, 20}
    assert {state["latest_status"] for state in states} == {"complete", "scope_unknown"}
    assert all(not any(token in sql.casefold() for token in _FORBIDDEN_SQL_TOKENS) for sql in guarded.statements)

    attempted_at = _now()
    with get_db_connection() as conn:
        failed_generation = begin_current_fdb_collection(
            conn, device_id=device_id, context_source="snmp", context_type="vrf",
            local_context_key="Blue-context", attempted_at=attempted_at, run_id="fdb-blue-failed",
        )
        conn.commit()
    with get_db_connection() as conn:
        assert finish_current_fdb_collection(
            conn, device_id=device_id, context_source="snmp", context_type="vrf",
            local_context_key="Blue-context", generation=failed_generation,
            status="failed", attempted_at=attempted_at, completed_at=_now(),
            observations=[], run_id="fdb-blue-failed", error_code="qbridge_partial",
        ) == 2
        conn.commit()

    with get_db_connection() as conn:
        after_failure = list_current_fdb_observations(conn, device_id=device_id)
    assert len(after_failure) == 3
    assert {row["generation"] for row in after_failure if row["context_type"] == "vrf"} == {blue_generation}
    assert {row["latest_status"] for row in after_failure if row["context_type"] == "vrf"} == {"failed"}
    assert {row["generation"] for row in after_failure if row["context_type"] == "unknown"} == {unknown_generation}

    empty_attempt = _now()
    with get_db_connection() as conn:
        empty_generation = begin_current_fdb_collection(
            conn, device_id=device_id, context_source="snmp", context_type="vrf",
            local_context_key="Blue-context", attempted_at=empty_attempt, run_id="fdb-blue-empty",
        )
        conn.commit()
    with get_db_connection() as conn:
        assert finish_current_fdb_collection(
            conn, device_id=device_id, context_source="snmp", context_type="vrf",
            local_context_key="Blue-context", generation=empty_generation,
            status="complete", attempted_at=empty_attempt, completed_at=_now(),
            observations=[], run_id="fdb-blue-empty",
        ) == 0
        conn.commit()
    with get_db_connection() as conn:
        remaining = list_current_fdb_observations(conn, device_id=device_id)
        final_states = get_current_fdb_collection_states(conn, device_id=device_id)
    assert len(remaining) == 1
    assert remaining[0]["local_context_key"] == "global-alias"
    blue_state = next(state for state in final_states if state["local_context_key"] == "Blue-context")
    assert blue_state["latest_status"] == "complete"
    assert blue_state["last_success_generation"] == empty_generation
    assert blue_state["current_row_count"] == 0


def test_current_fdb_generation_fencing_and_invalid_rows(isolated_db):
    del isolated_db
    device_id = "current-fdb-fence-device"
    _seed_device(device_id, "current-fdb-fence-site")
    attempted_at = _now()
    with get_db_connection() as conn:
        old_generation = begin_current_fdb_collection(
            conn, device_id=device_id, context_source="cli", context_type="unknown",
            local_context_key="raw-key", attempted_at=attempted_at, run_id="old-fdb-run",
        )
        conn.commit()
    newer_attempt = _now()
    with get_db_connection() as conn:
        new_generation = begin_current_fdb_collection(
            conn, device_id=device_id, context_source="cli", context_type="unknown",
            local_context_key="raw-key", attempted_at=newer_attempt, run_id="new-fdb-run",
        )
        conn.commit()
    with get_db_connection() as conn, pytest.raises(ValueError, match="collection_generation_superseded"):
        finish_current_fdb_collection(
            conn, device_id=device_id, context_source="cli", context_type="unknown",
            local_context_key="raw-key", generation=old_generation,
            status="scope_unknown", attempted_at=attempted_at, completed_at=_now(),
            observations=[{"mac": "001122334455", "interface": "Ethernet1/1", "vlan": 10}],
            run_id="old-fdb-run",
        )
    with get_db_connection() as conn:
        conn.rollback()
        with pytest.raises(ValueError, match="mac_address_invalid"):
            finish_current_fdb_collection(
                conn, device_id=device_id, context_source="cli", context_type="unknown",
                local_context_key="raw-key", generation=new_generation,
                status="scope_unknown", attempted_at=newer_attempt, completed_at=_now(),
                observations=[{"mac": "not-a-mac", "interface": "Ethernet1/1", "vlan": 10}],
                run_id="new-fdb-run",
            )
        conn.rollback()
        assert finish_current_fdb_collection(
            conn, device_id=device_id, context_source="cli", context_type="unknown",
            local_context_key="raw-key", generation=new_generation,
            status="scope_unknown", attempted_at=newer_attempt, completed_at=_now(),
            observations=[], run_id="new-fdb-run",
        ) == 0
        conn.commit()
