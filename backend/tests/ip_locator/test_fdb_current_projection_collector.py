from __future__ import annotations

import asyncio

import pytest

from database import get_db_connection
from services import ip_locator_service, snmp_service, vault_service
from services.ipam_address_space_service import create_address_space
from services.ipam_current_fdb_observation_service import (
    begin_current_fdb_collection,
    finish_current_fdb_collection,
    get_current_fdb_collection_states,
    list_current_fdb_observations,
)


def _now() -> str:
    return ip_locator_service._beijing_now_iso()


def _insert_device(device_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices
                   (id, hostname, ip_address, platform, status, site_id, tenant_id)
               VALUES (?, ?, '192.0.2.10', 'cisco_ios', 'online', 'site-fdb-current', 'tenant-default')""",
            (device_id, device_id),
        )
        conn.commit()


def _insert_vrf_mapping(device_id: str, context_key: str) -> str:
    vrf_id = f"vrf-fdb-{device_id}-{context_key}"
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES (?, ?, 'tenant-default')",
            (vrf_id, context_key),
        )
        conn.commit()
    space = create_address_space(
        name=f"FDB {device_id} {context_key}",
        kind="vrf",
        vrf_id=vrf_id,
        security_tenant_id="tenant-default",
    )
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts
                   (id, device_id, context_source, context_type, local_context_key,
                    local_context_name, address_space_id, status)
               VALUES (?, ?, 'snmp', 'vrf', ?, ?, ?, 'active')""",
            (f"mapping-{device_id}-{context_key}", device_id, context_key, context_key, space["id"]),
        )
        conn.commit()
    return space["id"]


def _seed_fdb_context(
    device_id: str,
    context_type: str,
    context_key: str,
    *,
    mac: str,
    context_source: str = "snmp",
) -> int:
    attempted_at = _now()
    context = {
        "context_source": context_source,
        "context_type": context_type,
        "local_context_key": context_key,
    }
    observation = {
        "mac": mac,
        "vlan": 10,
        "port": "GigabitEthernet1/0/2",
        "type": "dynamic",
    }
    with get_db_connection() as conn:
        generation = begin_current_fdb_collection(
            conn, device_id=device_id, **context, attempted_at=attempted_at, run_id="seed-fdb",
        )
        conn.commit()
    with get_db_connection() as conn:
        finish_current_fdb_collection(
            conn, device_id=device_id, **context, generation=generation,
            status="complete" if context_type != "unknown" else "scope_unknown",
            attempted_at=attempted_at, completed_at=_now(), observations=[observation],
            run_id="seed-fdb",
        )
        conn.commit()
    return generation


def _configure_v3(monkeypatch, *, context_name: str = "") -> None:
    monkeypatch.setattr(ip_locator_service, "is_snmp_collection_enabled", lambda _device: True)
    monkeypatch.setattr(vault_service, "resolve_collector_credentials", lambda _device: {
        "snmp": {
            "configured": True,
            "version": "3",
            "server": "192.0.2.10",
            "port": 161,
            "username": "fixture-user",
            "security_level": "noAuthNoPriv",
            "context_name": context_name,
        },
    })


def _configure_v2(monkeypatch) -> None:
    monkeypatch.setattr(ip_locator_service, "is_snmp_collection_enabled", lambda _device: True)
    monkeypatch.setattr(vault_service, "resolve_collector_credentials", lambda _device: {
        "snmp": {
            "configured": True,
            "version": "2c",
            "server": "192.0.2.10",
            "port": 161,
            "community": "fixture-community",
        },
    })


def _fdb_row(mac: str, *, vlan: int = 10, port: str = "GigabitEthernet1/0/2") -> dict:
    return {"mac": mac, "vlan": vlan, "port": port, "type": "dynamic"}


def test_snmp_context_is_begun_before_collection_and_persisted(isolated_db, monkeypatch):
    device_id = "fdb-begin-before-io"
    _insert_device(device_id)
    address_space_id = _insert_vrf_mapping(device_id, "Blue")
    _configure_v3(monkeypatch)
    calls = []

    async def collect(_ip, credentials, port, *, version, timeout=120):
        calls.append((credentials["context_name"], version))
        with get_db_connection() as conn:
            state = get_current_fdb_collection_states(conn, device_id=device_id)[0]
        assert state["latest_status"] == "running"
        assert state["latest_attempt_generation"] == 1
        return [_fdb_row("001122334455")]

    monkeypatch.setattr(snmp_service, "collect_bridge_mac_table", collect)
    result = ip_locator_service._collect_full_mac_table_from_device(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10"}, snmp_only=True,
    )

    assert result["success"] is True, (
        result.get("error"), result.get("failure_class"), result.get("coverage_status"), calls
    )
    assert result["legacy_replace_safe"] is True
    assert calls == [("Blue", "3")]
    with get_db_connection() as conn:
        observations = list_current_fdb_observations(conn, device_id=device_id)
        states = get_current_fdb_collection_states(conn, device_id=device_id)
    assert observations[0]["address_space_id"] == address_space_id
    assert observations[0]["local_context_key"] == "Blue"
    assert states[0]["latest_status"] == "complete"
    assert states[0]["last_success_generation"] == 1


def test_complete_empty_replaces_only_its_context(isolated_db, monkeypatch):
    device_id = "fdb-empty-context"
    _insert_device(device_id)
    _insert_vrf_mapping(device_id, "A")
    _insert_vrf_mapping(device_id, "B")
    _seed_fdb_context(device_id, "vrf", "A", mac="0011223344aa")
    _seed_fdb_context(device_id, "vrf", "B", mac="0011223344bb")
    _configure_v3(monkeypatch)

    async def collect(_ip, credentials, port, *, version, timeout=120):
        if credentials["context_name"] == "A":
            return []
        return [_fdb_row("0011223344bc")]

    monkeypatch.setattr(snmp_service, "collect_bridge_mac_table", collect)
    result = ip_locator_service._collect_full_mac_table_from_device(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10"}, snmp_only=True,
    )

    assert result["success"] is False, result
    assert result["current_state_success"] is True
    assert result["coverage_status"] == "partial"
    with get_db_connection() as conn:
        observations = list_current_fdb_observations(conn, device_id=device_id)
        states = {row["local_context_key"]: row for row in get_current_fdb_collection_states(conn, device_id=device_id)}
    assert {row["local_context_key"] for row in observations} == {"B"}
    assert states["A"]["latest_status"] == "complete"
    assert states["A"]["last_success_generation"] == 2
    assert states["A"]["current_row_count"] == 0
    assert states["B"]["latest_status"] == "complete"
    assert states["B"]["last_success_generation"] == 2


def test_context_failure_preserves_last_success_while_other_context_advances(isolated_db, monkeypatch):
    device_id = "fdb-context-failure"
    _insert_device(device_id)
    _insert_vrf_mapping(device_id, "A")
    _insert_vrf_mapping(device_id, "B")
    _seed_fdb_context(device_id, "vrf", "A", mac="0011223344aa")
    _seed_fdb_context(device_id, "vrf", "B", mac="0011223344bb")
    _configure_v3(monkeypatch)

    async def collect(_ip, credentials, port, *, version, timeout=120):
        if credentials["context_name"] == "A":
            raise RuntimeError("fixture timeout")
        return [_fdb_row("0011223344bc")]

    monkeypatch.setattr(snmp_service, "collect_bridge_mac_table", collect)
    result = ip_locator_service._collect_full_mac_table_from_device(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10"}, snmp_only=True,
    )

    assert result["coverage_status"] == "partial"
    with get_db_connection() as conn:
        observations = {row["local_context_key"]: row for row in list_current_fdb_observations(conn, device_id=device_id)}
        states = {row["local_context_key"]: row for row in get_current_fdb_collection_states(conn, device_id=device_id)}
    assert observations["A"]["mac_address"] == "0011223344aa"
    assert observations["A"]["generation"] == 1
    assert observations["B"]["mac_address"] == "0011223344bc"
    assert observations["B"]["generation"] == 2
    assert states["A"]["latest_status"] == "failed"
    assert states["A"]["last_success_generation"] == 1
    assert states["B"]["latest_status"] == "complete"
    assert states["B"]["last_success_generation"] == 2


def test_unknown_profile_alias_is_retained_without_global_inference(isolated_db, monkeypatch):
    device_id = "fdb-unknown-global-alias"
    _insert_device(device_id)
    _configure_v3(monkeypatch, context_name="global")

    async def collect(_ip, credentials, port, *, version, timeout=120):
        assert credentials["context_name"] == "global"
        return [_fdb_row("001122334455")]

    monkeypatch.setattr(snmp_service, "collect_bridge_mac_table", collect)
    result = ip_locator_service._collect_full_mac_table_from_device(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10"}, snmp_only=True,
    )

    assert result["success"] is False, result
    with get_db_connection() as conn:
        observations = list_current_fdb_observations(conn, device_id=device_id)
        state = get_current_fdb_collection_states(conn, device_id=device_id)[0]
    assert observations[0]["local_context_key"] == "global"
    assert observations[0]["context_type"] == "unknown"
    assert observations[0]["address_space_id"] is None
    assert state["latest_status"] == "scope_unknown"


def test_snmp_failure_then_cli_failure_updates_independent_source_states(isolated_db, monkeypatch):
    device_id = "fdb-transport-independent"
    _insert_device(device_id)
    _configure_v2(monkeypatch)

    async def fail_snmp(*_args, **_kwargs):
        raise RuntimeError("fixture SNMP failure")

    monkeypatch.setattr(snmp_service, "collect_bridge_mac_table", fail_snmp)
    monkeypatch.setattr(ip_locator_service, "_send_command", lambda *_args: (_ for _ in ()).throw(RuntimeError("fixture CLI failure")))
    result = ip_locator_service._collect_full_mac_table_from_device(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10", "platform": "cisco_ios"},
    )

    assert result["success"] is False, result
    with get_db_connection() as conn:
        states = {
            row["context_source"]: row
            for row in get_current_fdb_collection_states(conn, device_id=device_id)
        }
    assert states["snmp"]["latest_status"] == "failed"
    assert states["cli"]["latest_status"] == "failed"


def test_cli_raw_context_key_is_not_published_after_collection(isolated_db, monkeypatch):
    device_id = "fdb-cli-raw-context-fence"
    _insert_device(device_id)
    _seed_fdb_context(device_id, "unknown", "Blue", mac="0011223344aa", context_source="cli")
    monkeypatch.setattr(ip_locator_service, "is_snmp_collection_enabled", lambda _device: False)
    monkeypatch.setattr(vault_service, "resolve_collector_credentials", lambda _device: {"snmp": {}})
    io_state = []

    def fake_platform_action(*_args, **_kwargs):
        with get_db_connection() as conn:
            states = get_current_fdb_collection_states(conn, device_id=device_id)
        io_state.extend(states)
        return {
            "success": True,
            "parse_status": "matched",
            "records": [_fdb_row("0011223344bb") | {"local_context_key": "Blue"}],
        }

    monkeypatch.setattr("services.platform_registry_service.execute_platform_action", fake_platform_action)
    result = ip_locator_service._collect_full_mac_table_from_device({
        "id": device_id,
        "hostname": device_id,
        "ip_address": "192.0.2.10",
        "platform_profile_id": "fixture-profile",
    })

    assert io_state and io_state[0]["local_context_key"] == ""
    assert io_state[0]["latest_status"] == "running"
    assert result["success"] is False
    assert result["coverage_status"] == "partial"
    with get_db_connection() as conn:
        observations = list_current_fdb_observations(conn, device_id=device_id)
        states = {
            row["local_context_key"]: row
            for row in get_current_fdb_collection_states(conn, device_id=device_id)
        }
    assert len(observations) == 1
    assert observations[0]["local_context_key"] == "Blue"
    assert observations[0]["mac_address"] == "0011223344aa"
    assert states["Blue"]["latest_status"] == "scope_unknown"
    assert states["Blue"]["latest_attempt_generation"] == 1
    assert states["Blue"]["last_success_generation"] == 1
    assert states[""]["latest_status"] == "partial"


def test_malformed_snmp_rows_do_not_replace_last_success(isolated_db, monkeypatch):
    device_id = "fdb-malformed-row"
    _insert_device(device_id)
    _seed_fdb_context(device_id, "unknown", "", mac="001122334455")
    _configure_v2(monkeypatch)

    async def collect(*_args, **_kwargs):
        return [{"mac": "not-a-mac", "vlan": 10, "port": "GigabitEthernet1/0/2"}]

    monkeypatch.setattr(snmp_service, "collect_bridge_mac_table", collect)
    result = ip_locator_service._collect_full_mac_table_from_device(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10"}, snmp_only=True,
    )

    assert result["success"] is False, result
    with get_db_connection() as conn:
        observations = list_current_fdb_observations(conn, device_id=device_id)
        state = get_current_fdb_collection_states(conn, device_id=device_id)[0]
    assert len(observations) == 1
    assert observations[0]["mac_address"] == "001122334455"
    assert observations[0]["generation"] == 1
    assert state["latest_status"] == "failed"
    assert state["last_success_generation"] == 1


def test_explicit_success_empty_legacy_snapshot_clears_only_that_device(isolated_db):
    _insert_device("fdb-legacy-a")
    _insert_device("fdb-legacy-b")
    with get_db_connection() as conn:
        for device_id, row_id in (("fdb-legacy-a", "legacy-a-row"), ("fdb-legacy-b", "legacy-b-row")):
            conn.execute(
                """INSERT INTO mac_table
                       (id, device_id, mac_address, interface_name, vlan_id, entry_type, last_updated)
                   VALUES (?, ?, '001122334455', 'Gi1/0/2', 10, 'dynamic', ?)""",
                (row_id, device_id, _now()),
            )
        conn.commit()

    ip_locator_service._persist_mac_table_records([{
        "device_id": "fdb-legacy-a", "success": True, "records": [], "legacy_replace_safe": True,
    }])

    with get_db_connection() as conn:
        rows = conn.execute("SELECT device_id FROM mac_table ORDER BY device_id").fetchall()
    assert [row["device_id"] for row in rows] == ["fdb-legacy-b"]

    ip_locator_service._persist_mac_table_records([{
        "device_id": "fdb-legacy-b", "success": False, "records": [], "legacy_replace_safe": False,
    }])
    with get_db_connection() as conn:
        rows = conn.execute("SELECT device_id FROM mac_table ORDER BY device_id").fetchall()
    assert [row["device_id"] for row in rows] == ["fdb-legacy-b"]


def test_snmp_fdb_accepts_empty_only_after_all_four_walks_succeed(monkeypatch):
    walked = []

    async def walk(_ip, _credentials, oid, *_args, **_kwargs):
        walked.append(oid)
        return []

    monkeypatch.setattr(snmp_service, "_snmp_bulk_walk_complete", walk)
    assert asyncio.run(snmp_service.collect_bridge_mac_table("192.0.2.1", "fixture")) == []
    assert len(walked) == 4

    async def one_primary_table_missing(_ip, _credentials, oid, *_args, **_kwargs):
        if oid == snmp_service.DOT1Q_TP_FDB_PORT:
            return [("0.0.17.0.17.34.51.68.85", 3)]
        return []

    monkeypatch.setattr(snmp_service, "_snmp_bulk_walk_complete", one_primary_table_missing)
    with pytest.raises(RuntimeError, match="port/status tables"):
        asyncio.run(snmp_service.collect_bridge_mac_table("192.0.2.1", "fixture"))


def test_snmp_fdb_empty_primary_walks_fail_if_an_ancillary_walk_errors(monkeypatch):
    async def failing_walk(_ip, _credentials, oid, *_args, **_kwargs):
        if oid == snmp_service.DOT1Q_VLAN_FDB_ID:
            raise RuntimeError("fixture walk failure")
        return []

    monkeypatch.setattr(snmp_service, "_snmp_bulk_walk_complete", failing_walk)
    with pytest.raises(RuntimeError, match="fixture walk failure"):
        asyncio.run(snmp_service.collect_bridge_mac_table("192.0.2.1", "fixture"))
