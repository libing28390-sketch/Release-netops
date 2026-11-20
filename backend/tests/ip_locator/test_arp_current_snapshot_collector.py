from __future__ import annotations

import asyncio
import time

import pytest

from database import get_db_connection
from services import ip_locator_service, snmp_service
from services.ipam_address_space_service import create_address_space
from services.ipam_current_endpoint_observation_service import (
    begin_current_endpoint_collection,
    finish_current_endpoint_collection,
    get_current_endpoint_collection_states,
    list_current_endpoint_observations,
)


def _now() -> str:
    return ip_locator_service._beijing_now_iso()


def _insert_device(device_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices
                   (id, hostname, ip_address, platform, status, site_id, tenant_id)
               VALUES (?, ?, '192.0.2.10', 'cisco_ios', 'online', 'site-arp-current', 'tenant-default')""",
            (device_id, device_id),
        )
        conn.commit()


def _insert_vrf_context(device_id: str, key: str) -> str:
    vrf_id = f"vrf-arp-{device_id}-{key}"
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES (?, ?, 'tenant-default')",
            (vrf_id, key),
        )
        conn.commit()
    space = create_address_space(
        name=f"ARP {device_id} {key}",
        kind="vrf",
        vrf_id=vrf_id,
        security_tenant_id="tenant-default",
    )
    _insert_context_mapping(device_id, key, space["id"], context_type="vrf")
    return space["id"]


def _insert_context_mapping(
    device_id: str,
    key: str,
    address_space_id: str,
    *,
    context_type: str,
    context_source: str = "snmp",
) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts
                   (id, device_id, context_source, context_type, local_context_key,
                    local_context_name, address_space_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active')""",
            (
                f"mapping-{device_id}-{context_source}-{context_type}-{key}",
                device_id, context_source, context_type, key, key, address_space_id,
            ),
        )
        conn.commit()


def _seed_current_context(
    device_id: str,
    context_type: str,
    context_key: str,
    *,
    ip: str,
    mac: str,
) -> int:
    attempted_at = _now()
    context = {
        "context_source": "snmp",
        "context_type": context_type,
        "local_context_key": context_key,
    }
    with get_db_connection() as conn:
        generation = begin_current_endpoint_collection(
            conn,
            device_id=device_id,
            **context,
            attempted_at=attempted_at,
            run_id="seed-current",
        )
        conn.commit()
    with get_db_connection() as conn:
        finish_current_endpoint_collection(
            conn,
            device_id=device_id,
            **context,
            generation=generation,
            status="complete",
            attempted_at=attempted_at,
            completed_at=_now(),
            observations=[{
                "ip": ip,
                "mac": mac,
                "interface": "Vlan10",
                "vlan_id": 10,
                **context,
            }],
            run_id="seed-current",
        )
        conn.commit()
    return generation


def _mock_snmp_v3(monkeypatch, collector) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(ip_locator_service, "is_snmp_collection_enabled", lambda _device: True)
    monkeypatch.setattr(
        "services.vault_service.resolve_collector_credentials",
        lambda _device: {"snmp": {
            "version": "3",
            "server": "192.0.2.10",
            "port": 161,
            "username": "test-user",
            "security_level": "noAuthNoPriv",
            "configured": True,
            "context_name": "",
        }},
    )

    async def fake_collect(ip, community, port, *, version, timeout=120):
        calls.append({"ip": ip, "community": dict(community), "port": port, "version": version})
        return await collector(community.get("context_name", ""))

    monkeypatch.setattr(snmp_service, "collect_arp_table", fake_collect)
    return calls


def _mock_snmp_v2c(monkeypatch, collector) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(ip_locator_service, "is_snmp_collection_enabled", lambda _device: True)
    monkeypatch.setattr(
        "services.vault_service.resolve_collector_credentials",
        lambda _device: {"snmp": {
            "version": "2c",
            "server": "192.0.2.10",
            "port": 161,
            "community": "mock-community",
            "configured": True,
        }},
    )

    async def fake_collect(ip, community, port, *, version, timeout=120):
        calls.append({"ip": ip, "community": community, "port": port, "version": version})
        return await collector()

    monkeypatch.setattr(snmp_service, "collect_arp_table", fake_collect)
    return calls


def test_scheduled_snmp_v3_keeps_same_host_in_each_mapped_context(isolated_db, monkeypatch):
    device_id = "arp-multi-context-device"
    _insert_device(device_id)
    blue_space = _insert_vrf_context(device_id, "Blue")
    red_space = _insert_vrf_context(device_id, "Red")

    async def collector(context_name: str):
        return [{
            "ip_address": "198.51.100.44",
            "mac_address": "00:11:22:33:44:55" if context_name == "Blue" else "00:11:22:33:44:66",
            "interface": "Vlan44",
        }]

    calls = _mock_snmp_v3(monkeypatch, collector)
    result = ip_locator_service._collect_full_arp_result(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10"},
        snmp_only=True,
        collection_run_id="arp-run-multi-context",
    )

    assert result["status"] == "success", result
    assert len(result["entries"]) == 2
    assert {call["community"]["context_name"] for call in calls} == {"Blue", "Red"}
    assert {entry["context_type"] for entry in result["entries"]} == {"vrf"}
    assert {entry["local_context_key"] for entry in result["entries"]} == {"Blue", "Red"}
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id)
        states = get_current_endpoint_collection_states(conn, device_id=device_id)
    assert len(rows) == 2
    assert {row["address_space_id"] for row in rows} == {blue_space, red_space}
    assert {row["latest_status"] for row in rows} == {"complete"}
    assert len(states) == 2


def test_complete_empty_snapshot_replaces_only_its_context(isolated_db, monkeypatch):
    device_id = "arp-empty-context-device"
    _insert_device(device_id)
    global_space = create_address_space(
        name="ARP Empty Global",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    _insert_context_mapping(device_id, "global", global_space["id"], context_type="global")
    _seed_current_context(
        device_id, "global", "global", ip="198.51.100.44", mac="001122334455",
    )

    async def empty_collector(_context_name: str):
        return []

    _mock_snmp_v3(monkeypatch, empty_collector)
    result = ip_locator_service._collect_full_arp_result(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10"},
        snmp_only=True,
        collection_run_id="arp-run-empty",
    )

    assert result["status"] == "success", result
    assert result["entries"] == []
    with get_db_connection() as conn:
        assert list_current_endpoint_observations(conn, device_id=device_id) == []
        state = get_current_endpoint_collection_states(conn, device_id=device_id)[0]
    assert state["latest_status"] == "complete"
    assert state["last_success_generation"] == 2
    assert state["current_row_count"] == 0


def test_context_failure_does_not_replace_its_last_success_when_another_context_succeeds(
    isolated_db, monkeypatch,
):
    device_id = "arp-partial-context-device"
    _insert_device(device_id)
    _insert_vrf_context(device_id, "A")
    _insert_vrf_context(device_id, "B")
    _seed_current_context(device_id, "vrf", "A", ip="198.51.100.10", mac="0011223344aa")
    _seed_current_context(device_id, "vrf", "B", ip="198.51.100.10", mac="0011223344bb")

    async def collector(context_name: str):
        if context_name == "A":
            raise RuntimeError("request timed out")
        return [{
            "ip_address": "198.51.100.10",
            "mac_address": "00:11:22:33:44:bc",
            "interface": "Vlan10",
        }]

    _mock_snmp_v3(monkeypatch, collector)
    result = ip_locator_service._collect_full_arp_result(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10"},
        snmp_only=True,
        collection_run_id="arp-run-partial",
    )

    assert result["status"] == "partial"
    assert result["entries"] == []
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id)
        states = {
            row["local_context_key"]: row
            for row in get_current_endpoint_collection_states(conn, device_id=device_id)
        }
    by_context = {row["local_context_key"]: row for row in rows}
    assert by_context["A"]["mac_address"] == "0011223344aa"
    assert by_context["A"]["generation"] == 1
    assert by_context["A"]["latest_status"] == "failed"
    assert by_context["B"]["mac_address"] == "0011223344bc"
    assert by_context["B"]["generation"] == 2
    assert by_context["B"]["latest_status"] == "complete"
    assert states["A"]["last_success_generation"] == 1
    assert states["B"]["last_success_generation"] == 2


def test_unmapped_snmpv3_global_alias_stays_unknown_with_raw_key(isolated_db, monkeypatch):
    device_id = "arp-unknown-alias-device"
    _insert_device(device_id)

    async def collector(_context_name: str):
        return [{
            "ip_address": "198.51.100.90",
            "mac_address": "00:11:22:33:44:90",
            "interface": "Vlan90",
        }]

    calls = _mock_snmp_v3(monkeypatch, collector)
    credentials = {
        "snmp": {
            "version": "3", "server": "192.0.2.10", "port": 161,
            "username": "test-user", "security_level": "noAuthNoPriv",
            "configured": True, "context_name": "global",
        },
    }
    monkeypatch.setattr(
        "services.vault_service.resolve_collector_credentials",
        lambda _device: credentials,
    )
    result = ip_locator_service._collect_full_arp_result(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10"},
        snmp_only=True,
        collection_run_id="arp-run-unknown-alias",
    )

    assert result["status"] == "success"
    assert calls[0]["community"]["context_name"] == "global"
    entry = result["entries"][0]
    assert entry["context_type"] == "unknown"
    assert entry["local_context_key"] == "global"
    assert entry["vrf"] == ""
    assert entry["vrf_context_status"] == "unknown"
    assert ip_locator_service._explicit_vrf_context(entry, {"platform": "cisco_ios"}) == (
        "unknown", "",
    )
    with get_db_connection() as conn:
        row = list_current_endpoint_observations(conn, device_id=device_id)[0]
    assert row["address_space_id"] is None
    assert row["latest_status"] == "scope_unknown"


def test_unlabelled_snmp_context_preserves_raw_global_alias_for_manual_mapping(isolated_db, monkeypatch):
    device_id = "arp-raw-global-alias-device"
    _insert_device(device_id)

    async def collector(_context_name: str):
        return [{
            "ip_address": "198.51.100.91",
            "mac_address": "00:11:22:33:44:91",
            "interface": "Vlan91",
            "vrf_name": "global",
        }]

    calls = _mock_snmp_v3(monkeypatch, collector)
    result = ip_locator_service._collect_full_arp_result(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10"},
        snmp_only=True,
        collection_run_id="arp-run-raw-global-alias",
    )

    assert result["status"] == "success"
    assert calls[0]["community"]["context_name"] == ""
    assert result["entries"][0]["context_type"] == "unknown"
    assert result["entries"][0]["local_context_key"] == "global"
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id)
    assert len(rows) == 1
    assert rows[0]["context_type"] == "unknown"
    assert rows[0]["local_context_key"] == "global"
    assert rows[0]["address_space_id"] is None


def test_v2c_default_table_uses_global_when_no_vrf_is_configured(isolated_db, monkeypatch):
    device_id = "arp-v2c-unknown-alias-device"
    _insert_device(device_id)

    async def collector():
        return [{
            "ip_address": "198.51.100.91",
            "mac_address": "00:11:22:33:44:91",
            "interface": "Vlan91",
            "vrf_name": "global",
        }]

    calls = _mock_snmp_v2c(monkeypatch, collector)
    result = ip_locator_service._collect_full_arp_result(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10"},
        snmp_only=True,
        collection_run_id="arp-run-v2c-raw-alias",
    )

    assert result["status"] == "success"
    assert calls[0]["version"] == "2c"
    assert calls[0]["community"] == "mock-community"
    entry = result["entries"][0]
    assert entry["context_type"] == "global"
    assert entry["local_context_key"] == "global"
    assert entry["vrf"] == "global"
    assert entry["vrf_context_status"] == "explicit_global"
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id)
        states = get_current_endpoint_collection_states(conn, device_id=device_id)
    row = next(row for row in rows if row["local_context_key"] == "global")
    assert row["address_space_id"] is None
    assert row["latest_status"] == "complete"
    assert {
        (state["context_type"], state["local_context_key"])
        for state in states
    } == {("global", "global")}


def test_credential_resolution_failure_marks_each_active_context_failed(isolated_db, monkeypatch):
    device_id = "arp-credential-failure-device"
    _insert_device(device_id)
    _insert_vrf_context(device_id, "Blue")
    _seed_current_context(device_id, "vrf", "Blue", ip="198.51.100.30", mac="001122334430")
    monkeypatch.setattr(ip_locator_service, "is_snmp_collection_enabled", lambda _device: True)
    monkeypatch.setattr(
        "services.vault_service.resolve_collector_credentials",
        lambda _device: (_ for _ in ()).throw(RuntimeError("credential lookup unavailable")),
    )

    result = ip_locator_service._collect_full_arp_result(
        {"id": device_id, "hostname": device_id, "ip_address": "192.0.2.10"},
        snmp_only=True,
        collection_run_id="arp-run-credential-failure",
    )

    assert result["status"] == "failed"
    assert result["context_results"] == [{
        "context_type": "vrf", "local_context_key": "Blue", "status": "failed",
    }]
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id)
        state = get_current_endpoint_collection_states(conn, device_id=device_id)[0]
    assert rows[0]["mac_address"] == "001122334430"
    assert rows[0]["latest_status"] == "failed"
    assert state["last_success_generation"] == 1
    assert state["latest_status"] == "failed"


def test_partial_device_sweep_does_not_clear_legacy_arp_rows(isolated_db, monkeypatch):
    device_id = "arp-legacy-partial-device"
    _insert_device(device_id)
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO arp_table
                   (id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated)
               VALUES ('legacy-arp-row', ?, '198.51.100.11', '001122334411', 'Vlan11', 11, ?)""",
            (device_id, _now()),
        )
        conn.execute(
            """INSERT INTO arp_cache
                   (target_ip, mac, vlan_id, arp_source, cached_at, expires_at, source_device_id)
               VALUES ('198.51.100.11', '001122334411', 11, '{}', ?, ?, ?)""",
            (_now(), time.time() + 3600, device_id),
        )
        conn.commit()

    monkeypatch.setattr(
        ip_locator_service,
        "_load_arp_sweep_devices",
        lambda *_args, **_kwargs: ([{
            "id": device_id, "hostname": device_id, "ip_address": "192.0.2.10",
        }], 1, 0),
    )
    monkeypatch.setattr(ip_locator_service, "_load_arp_collection_state", lambda: {})
    monkeypatch.setattr(ip_locator_service, "_calc_arp_sweep_workers", lambda _count: 1)
    monkeypatch.setattr(ip_locator_service, "record_collection_results", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ip_locator_service, "complete_collector_sweep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ip_locator_service,
        "_collect_full_arp_result",
        lambda *_args, **_kwargs: {
            "entries": [{
                "ip": "198.51.100.12", "mac": "001122334412",
                "source_device_id": device_id,
            }],
            "status": "partial", "failure_class": "unreachable",
            "error_message": "one SNMP context failed", "transport": "snmp",
        },
    )

    result = ip_locator_service._run_arp_sweep_locked()

    assert result["collected_entries"] == 0
    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS count FROM arp_table WHERE device_id = ?",
            (device_id,),
        ).fetchone()["count"] == 1
        assert conn.execute(
            "SELECT COUNT(*) AS count FROM arp_cache WHERE source_device_id = ?",
            (device_id,),
        ).fetchone()["count"] == 1


def test_collect_arp_table_only_accepts_complete_empty_walks(monkeypatch):
    calls = []

    async def walk(_ip, _community, oid, _port, *, timeout, version):
        calls.append(oid)
        return []

    monkeypatch.setattr(snmp_service, "_snmp_bulk_walk_complete", walk)
    assert asyncio.run(snmp_service.collect_arp_table("192.0.2.10", community="mock")) == []
    assert calls == [
        snmp_service.IP_NET_TO_MEDIA_PHYS_ADDRESS,
        snmp_service.IP_NET_TO_MEDIA_TYPE,
    ]

    async def one_empty_walk(_ip, _community, oid, _port, *, timeout, version):
        if oid == snmp_service.IP_NET_TO_MEDIA_TYPE:
            return [("1.192.0.2.1", 3)]
        return []

    monkeypatch.setattr(snmp_service, "_snmp_bulk_walk_complete", one_empty_walk)
    with pytest.raises(RuntimeError, match="incomplete coverage"):
        asyncio.run(snmp_service.collect_arp_table("192.0.2.10", community="mock"))
