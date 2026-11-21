from __future__ import annotations

from datetime import datetime, timezone

import pytest

from database import get_db_connection
from database.migrations import discover_migrations
from database.migrations.m0317_ipam_current_ndp_observations import VERSION, upgrade
from services.ipam_current_endpoint_observation_service import (
    begin_current_endpoint_collection,
    finish_current_endpoint_collection,
    get_current_endpoint_collection_states,
    list_current_endpoint_observations,
)
from services.ipam_routing_context_service import create_device_routing_context
from services.ipam_address_space_service import create_address_space


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def test_m0317_adds_ndp_source_checks_idempotently(isolated_db):
    del isolated_db
    with get_db_connection() as conn:
        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        state_check = conn.execute(
            """SELECT pg_get_constraintdef(oid) FROM pg_constraint
                WHERE conrelid = 'ipam_endpoint_collection_states'::regclass
                  AND conname = 'ck_ipam_endpoint_state_source'"""
        ).fetchone()[0]
        observation_check = conn.execute(
            """SELECT pg_get_constraintdef(oid) FROM pg_constraint
                WHERE conrelid = 'ipam_current_endpoint_observations'::regclass
                  AND conname = 'ck_ipam_current_endpoint_observation_source'"""
        ).fetchone()[0]
        address_family_check = conn.execute(
            """SELECT pg_get_constraintdef(oid) FROM pg_constraint
                WHERE conrelid = 'ipam_current_endpoint_observations'::regclass
                  AND conname = 'ck_ipam_current_endpoint_address_family'"""
        ).fetchone()[0]
    assert VERSION in {int(module.VERSION) for module in discover_migrations()}
    assert all(source in state_check for source in ("arp", "fdb", "ndp"))
    assert all(source in observation_check for source in ("arp", "ndp"))
    assert "family(ip_address)" in address_family_check
    assert all(value in address_family_check for value in ("arp", "ndp", "4", "6"))


def test_m0317_unknown_ndp_old_checks_failure_rolls_back_and_retry_is_idempotent(isolated_db):
    del isolated_db
    device_id = "m0317-unknown-ndp-device"
    _seed_device(device_id, "m0317-unknown-ndp-site")
    with get_db_connection() as conn:
        conn.execute(
            "ALTER TABLE ipam_endpoint_collection_states "
            "DROP CONSTRAINT IF EXISTS ck_ipam_endpoint_state_source"
        )
        conn.execute(
            """ALTER TABLE ipam_endpoint_collection_states
                   ADD CONSTRAINT ck_ipam_endpoint_state_source
                   CHECK (observation_source IN ('arp', 'fdb'))"""
        )
        conn.execute(
            "ALTER TABLE ipam_current_endpoint_observations "
            "DROP CONSTRAINT IF EXISTS ck_ipam_current_endpoint_observation_source"
        )
        conn.execute(
            """ALTER TABLE ipam_current_endpoint_observations
                   ADD CONSTRAINT ck_ipam_current_endpoint_observation_source
                   CHECK (observation_source = 'arp')"""
        )
        conn.execute(
            "ALTER TABLE ipam_current_endpoint_observations "
            "DROP CONSTRAINT IF EXISTS ck_ipam_current_endpoint_address_family"
        )
        conn.execute(
            "ALTER TABLE ipam_current_endpoint_observations "
            "DROP CONSTRAINT IF EXISTS ck_ipam_current_endpoint_ndp_ipv6"
        )
        conn.execute(
            """ALTER TABLE ipam_current_endpoint_observations
                   ADD CONSTRAINT ck_ipam_current_endpoint_address_family
                   CHECK (family(ip_address) = 4)"""
        )
        conn.commit()

    def fail_after_m0317_checks(cursor, use_pg: bool) -> None:
        upgrade(cursor, use_pg)
        raise RuntimeError("synthetic m0317 failure after check replacement")

    with get_db_connection() as conn:
        with pytest.raises(RuntimeError, match="synthetic m0317 failure after check replacement"):
            fail_after_m0317_checks(conn.cursor(), use_pg=True)
        conn.rollback()
        old_state_check = conn.execute(
            """SELECT pg_get_constraintdef(oid)
                 FROM pg_constraint
                WHERE conrelid = 'ipam_endpoint_collection_states'::regclass
                  AND conname = 'ck_ipam_endpoint_state_source'"""
        ).fetchone()[0]
        old_source_check = conn.execute(
            """SELECT pg_get_constraintdef(oid)
                 FROM pg_constraint
                WHERE conrelid = 'ipam_current_endpoint_observations'::regclass
                  AND conname = 'ck_ipam_current_endpoint_observation_source'"""
        ).fetchone()[0]
        old_family_check = conn.execute(
            """SELECT pg_get_constraintdef(oid)
                 FROM pg_constraint
                WHERE conrelid = 'ipam_current_endpoint_observations'::regclass
                  AND conname = 'ck_ipam_current_endpoint_address_family'"""
        ).fetchone()[0]
        assert "'fdb'" in old_state_check and "'ndp'" not in old_state_check
        assert "'arp'" in old_source_check and "'ndp'" not in old_source_check
        assert "family(ip_address) = 4" in old_family_check

        def checks_snapshot() -> tuple:
            state_check = conn.execute(
                """SELECT pg_get_constraintdef(oid, true)
                     FROM pg_constraint
                    WHERE conrelid = 'ipam_endpoint_collection_states'::regclass
                      AND conname = 'ck_ipam_endpoint_state_source'"""
            ).fetchone()[0]
            source_check = conn.execute(
                """SELECT pg_get_constraintdef(oid, true)
                     FROM pg_constraint
                    WHERE conrelid = 'ipam_current_endpoint_observations'::regclass
                      AND conname = 'ck_ipam_current_endpoint_observation_source'"""
            ).fetchone()[0]
            family_check = conn.execute(
                """SELECT pg_get_constraintdef(oid, true)
                     FROM pg_constraint
                    WHERE conrelid = 'ipam_current_endpoint_observations'::regclass
                      AND conname = 'ck_ipam_current_endpoint_address_family'"""
            ).fetchone()[0]
            return state_check, source_check, family_check

        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        first_checks = checks_snapshot()
        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        assert first_checks == checks_snapshot()

        conn.execute(
            """INSERT INTO ipam_endpoint_collection_states (
                   device_id, observation_source, context_source, context_type,
                   local_context_key
               ) VALUES (?, 'ndp', 'snmp', 'unknown', 'raw-local-key')""",
            (device_id,),
        )
        conn.execute(
            """INSERT INTO ipam_current_endpoint_observations (
                   source_device_id, observation_source, context_source, context_type,
                   local_context_key, local_context_name, ip_address, mac_address,
                   interface_name, normalized_interface_name, vlan_key, generation,
                   observed_at, run_id, metadata_json
               ) VALUES (
                   ?, 'ndp', 'snmp', 'unknown', 'raw-local-key', 'raw-local-key',
                   'fe80::1'::inet, '001122334455', 'GigabitEthernet1/0/1',
                   'gi1/0/1', 10, 1, CURRENT_TIMESTAMP, 'm0317-unknown-run',
                   '{}'::jsonb
               )""",
            (device_id,),
        )
        conn.commit()
        row = conn.execute(
            """SELECT observation_source, context_type, local_context_key,
                      host(ip_address), family(ip_address)
                 FROM ipam_current_endpoint_observations
                WHERE source_device_id = ? AND observation_source = 'ndp'""",
            (device_id,),
        ).fetchone()
    assert tuple(row) == ("ndp", "unknown", "raw-local-key", "fe80::1", 6)

def test_current_ndp_keeps_link_local_interfaces_scoped_and_arp_isolated(isolated_db):
    del isolated_db
    device_id = "current-ndp-device"
    site_id = "current-ndp-site"
    _seed_device(device_id, site_id)
    vrf_id = "current-ndp-vrf"
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES (?, 'Blue', 'tenant-default')",
            (vrf_id,),
        )
        conn.commit()
    space = create_address_space(
        name="Current NDP Blue", kind="vrf", vrf_id=vrf_id,
        security_tenant_id="tenant-default",
    )
    create_device_routing_context(
        device_id=device_id,
        context_source="snmp",
        context_type="vrf",
        local_context_key="Blue-context",
        local_context_name="Blue",
        address_space_id=space["id"],
        security_tenant_id="tenant-default",
    )
    attempted_at = _now()
    observations = [
        {
            "ip_address": "fe80::1",
            "mac_address": "00:11:22:33:44:55",
            "interface_name": "GigabitEthernet1/0/1",
            "context_source": "snmp",
            "context_type": "vrf",
            "local_context_key": "Blue-context",
            "vlan_id": 10,
        },
        {
            "ip_address": "fe80::1",
            "mac_address": "00:11:22:33:44:66",
            "interface_name": "GigabitEthernet1/0/2",
            "context_source": "snmp",
            "context_type": "vrf",
            "local_context_key": "Blue-context",
            "vlan_id": 20,
        },
    ]
    with get_db_connection() as conn:
        generation = begin_current_endpoint_collection(
            conn, device_id=device_id, observation_source="ndp",
            context_source="snmp", context_type="vrf",
            local_context_key="Blue-context", attempted_at=attempted_at, run_id="ndp-run-1",
        )
        conn.commit()
    with get_db_connection() as conn:
        finish_current_endpoint_collection(
            conn, device_id=device_id, observation_source="ndp",
            context_source="snmp", context_type="vrf",
            local_context_key="Blue-context", generation=generation,
            status="complete", attempted_at=attempted_at, completed_at=_now(),
            observations=observations, run_id="ndp-run-1",
        )
        conn.commit()

    with get_db_connection() as conn:
        arp_rows = list_current_endpoint_observations(conn, device_id=device_id)
        ndp_rows = list_current_endpoint_observations(
            conn, device_id=device_id, observation_source="ndp",
        )
        ndp_states = get_current_endpoint_collection_states(
            conn, device_id=device_id, observation_source="ndp",
        )
    assert arp_rows == []
    assert len(ndp_rows) == 2
    assert {row["ip_address"] for row in ndp_rows} == {"fe80::1"}
    assert {row["normalized_interface_name"] for row in ndp_rows} == {
        "gi1/0/1", "gi1/0/2",
    }
    assert {row["address_space_id"] for row in ndp_rows} == {space["id"]}
    assert {row["observation_source"] for row in ndp_rows} == {"ndp"}
    assert len(ndp_states) == 1 and ndp_states[0]["latest_status"] == "complete"

    with get_db_connection() as conn, pytest.raises(ValueError, match="ndp_requires_ipv6"):
        finish_current_endpoint_collection(
            conn, device_id=device_id, observation_source="ndp",
            context_source="snmp", context_type="vrf",
            local_context_key="Blue-context", generation=generation,
            status="complete", attempted_at=attempted_at, completed_at=_now(),
            observations=[{
                **observations[0],
                "ip_address": "192.0.2.10",
            }], run_id="ndp-invalid-v4",
        )


def test_current_ndp_complete_empty_and_failure_are_context_local(isolated_db):
    del isolated_db
    device_id = "current-ndp-empty-device"
    _seed_device(device_id, "current-ndp-empty-site")
    for context_key, ip_address, interface in (
        ("Blue", "fe80::10", "GigabitEthernet1/0/1"),
        ("Green", "fe80::10", "GigabitEthernet1/0/2"),
    ):
        attempted_at = _now()
        with get_db_connection() as conn:
            generation = begin_current_endpoint_collection(
                conn, device_id=device_id, observation_source="ndp",
                context_source="snmp", context_type="unknown",
                local_context_key=context_key, attempted_at=attempted_at, run_id=f"ndp-{context_key}-1",
            )
            conn.commit()
        with get_db_connection() as conn:
            finish_current_endpoint_collection(
                conn, device_id=device_id, observation_source="ndp",
                context_source="snmp", context_type="unknown",
                local_context_key=context_key, generation=generation,
                status="scope_unknown", attempted_at=attempted_at, completed_at=_now(),
                observations=[{
                    "ip_address": ip_address, "mac_address": "00:11:22:33:44:55",
                    "interface_name": interface, "context_source": "snmp",
                    "context_type": "unknown", "local_context_key": context_key,
                }], run_id=f"ndp-{context_key}-1",
            )
            conn.commit()

    arp_attempted_at = _now()
    with get_db_connection() as conn:
        arp_generation = begin_current_endpoint_collection(
            conn, device_id=device_id, observation_source="arp",
            context_source="snmp", context_type="unknown", local_context_key="Blue",
            attempted_at=arp_attempted_at, run_id="arp-blue-before-ndp-empty",
        )
        conn.commit()
    with get_db_connection() as conn:
        finish_current_endpoint_collection(
            conn, device_id=device_id, observation_source="arp",
            context_source="snmp", context_type="unknown", local_context_key="Blue",
            generation=arp_generation, status="scope_unknown",
            attempted_at=arp_attempted_at, completed_at=_now(),
            observations=[{
                "ip_address": "192.0.2.10", "mac_address": "00:11:22:33:44:77",
                "interface_name": "GigabitEthernet1/0/9", "context_source": "snmp",
                "context_type": "unknown", "local_context_key": "Blue",
            }], run_id="arp-blue-before-ndp-empty",
        )
        conn.commit()

    attempted_at = _now()
    with get_db_connection() as conn:
        empty_generation = begin_current_endpoint_collection(
            conn, device_id=device_id, observation_source="ndp",
            context_source="snmp", context_type="unknown", local_context_key="Blue",
            attempted_at=attempted_at, run_id="ndp-blue-empty",
        )
        conn.commit()
    with get_db_connection() as conn:
        assert finish_current_endpoint_collection(
            conn, device_id=device_id, observation_source="ndp",
            context_source="snmp", context_type="unknown", local_context_key="Blue",
            generation=empty_generation, status="scope_unknown", attempted_at=attempted_at,
            completed_at=_now(), observations=[], run_id="ndp-blue-empty",
        ) == 0
        conn.commit()
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(
            conn, device_id=device_id, observation_source="ndp",
        )
    assert len(rows) == 1 and rows[0]["local_context_key"] == "Green"
    green_generation = int(rows[0]["generation"])
    with get_db_connection() as conn:
        arp_rows = list_current_endpoint_observations(
            conn, device_id=device_id, observation_source="arp",
        )
    assert len(arp_rows) == 1
    assert arp_rows[0]["local_context_key"] == "Blue"
    assert arp_rows[0]["ip_address"] == "192.0.2.10"

    failed_attempted_at = _now()
    with get_db_connection() as conn:
        failed_generation = begin_current_endpoint_collection(
            conn, device_id=device_id, observation_source="ndp",
            context_source="snmp", context_type="unknown", local_context_key="Green",
            attempted_at=failed_attempted_at, run_id="ndp-green-failed",
        )
        conn.commit()
    with get_db_connection() as conn:
        assert finish_current_endpoint_collection(
            conn, device_id=device_id, observation_source="ndp",
            context_source="snmp", context_type="unknown", local_context_key="Green",
            generation=failed_generation, status="failed",
            attempted_at=failed_attempted_at, completed_at=_now(),
            observations=[], run_id="ndp-green-failed", error_code="snmp_timeout",
        ) == 1
        conn.commit()
    with get_db_connection() as conn:
        retained_ndp_rows = list_current_endpoint_observations(
            conn, device_id=device_id, observation_source="ndp",
        )
        ndp_states = get_current_endpoint_collection_states(
            conn, device_id=device_id, observation_source="ndp",
        )
    assert len(retained_ndp_rows) == 1
    assert retained_ndp_rows[0]["local_context_key"] == "Green"
    assert int(retained_ndp_rows[0]["generation"]) == green_generation
    green_state = next(state for state in ndp_states if state["local_context_key"] == "Green")
    assert green_state["latest_status"] == "failed"
    assert green_state["last_success_generation"] == green_generation
    assert green_state["latest_attempt_generation"] == failed_generation
    assert green_state["last_error_code"] == "snmp_timeout"
