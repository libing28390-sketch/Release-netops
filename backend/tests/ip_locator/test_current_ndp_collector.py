from __future__ import annotations

import asyncio
import ipaddress
from datetime import datetime, timezone

import pytest

from database import get_db_connection
from services import ipam_current_ndp_collection_service as ndp_service
from services import snmp_service
from services.ipam_address_space_service import create_address_space
from services.ipam_current_endpoint_observation_service import (
    begin_current_endpoint_collection,
    finish_current_endpoint_collection,
    get_current_endpoint_collection_states,
    list_current_endpoint_observations,
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _insert_device(device_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices
                   (id, hostname, ip_address, platform, status, site_id, tenant_id)
               VALUES (?, ?, '192.0.2.10', 'cisco_ios', 'online', 'site-ndp-current', 'tenant-default')""",
            (device_id, device_id),
        )
        conn.commit()


def _insert_context_mapping(device_id: str, key: str, *, context_type: str = "vrf") -> str:
    vrf_id = None
    if context_type == "vrf":
        vrf_id = f"vrf-ndp-{device_id}-{key}"
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES (?, ?, 'tenant-default')",
                (vrf_id, key),
            )
            conn.commit()
    space = create_address_space(
        name=f"NDP {device_id} {context_type} {key}",
        kind="vrf" if context_type == "vrf" else "global",
        vrf_id=vrf_id,
        security_tenant_id="tenant-default",
    )
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts
                   (id, device_id, context_source, context_type, local_context_key,
                    local_context_name, address_space_id, status)
               VALUES (?, ?, 'snmp', ?, ?, ?, ?, 'active')""",
            (f"mapping-{device_id}-{context_type}-{key}", device_id, context_type, key, key, space["id"]),
        )
        conn.commit()
    return space["id"]


def _seed_current(
    device_id: str,
    *,
    ip: str = "2001:db8::10",
    mac: str = "00:11:22:33:44:55",
    interface: str = "Ethernet1",
    context_type: str = "vrf",
    context_key: str = "Blue",
) -> int:
    attempted = _now()
    context = {
        "context_source": "snmp",
        "context_type": context_type,
        "local_context_key": context_key,
    }
    with get_db_connection() as conn:
        generation = begin_current_endpoint_collection(
            conn,
            device_id=device_id,
            observation_source="ndp",
            **context,
            attempted_at=attempted,
            run_id="seed-ndp",
        )
        conn.commit()
    with get_db_connection() as conn:
        finish_current_endpoint_collection(
            conn,
            device_id=device_id,
            observation_source="ndp",
            **context,
            generation=generation,
            status="complete" if context_type != "unknown" else "scope_unknown",
            attempted_at=attempted,
            completed_at=_now(),
            observations=[{
                "ip_address": ip,
                "mac_address": mac,
                "interface_name": interface,
                **context,
            }],
            run_id="seed-ndp",
        )
        conn.commit()
    return generation


def _set_v3_credentials(monkeypatch, *, context_name: str = "") -> None:
    monkeypatch.setattr(ndp_service.vault_service, "resolve_collector_credentials", lambda _device: {
        "snmp": {
            "configured": True,
            "version": "3",
            "server": "192.0.2.10",
            "port": 161,
            "username": "fixture-user",
            "context_name": context_name,
        },
    })


def _set_v2_credentials(monkeypatch) -> None:
    monkeypatch.setattr(ndp_service.vault_service, "resolve_collector_credentials", lambda _device: {
        "snmp": {
            "configured": True,
            "version": "2c",
            "server": "192.0.2.10",
            "port": 161,
            "community": "fixture-community",
        },
    })


def _record(
    ip: str,
    mac: str,
    interface: str,
    *,
    if_index: int = 7,
    zone_index: int | None = None,
) -> dict:
    return {
        "ip_address": ip,
        "mac_address": mac,
        "interface": interface,
        "if_index": if_index,
        "inet_address_type": 4 if zone_index is not None else 2,
        "zone_index": zone_index,
        "type": "dynamic",
        "state": "reachable",
    }


def _oid_index(if_index: int, address: str, *, address_type: int = 2, zone_index: int | None = None) -> str:
    octets = list(ipaddress.IPv6Address(address).packed)
    if address_type == 4:
        octets.extend(int(zone_index or 0).to_bytes(4, "big"))
    return ".".join(str(value) for value in (if_index, address_type, len(octets), *octets))


def test_ip_net_to_physical_ipv6z_index_and_ifindex_mapping(monkeypatch):
    suffix = _oid_index(7, "fe80::1", address_type=4, zone_index=7)
    columns = {
        snmp_service.IP_NET_TO_PHYSICAL_PHYS_ADDRESS: [(suffix, bytes.fromhex("001122334455"))],
        snmp_service.IP_NET_TO_PHYSICAL_TYPE: [(suffix, 3)],
        snmp_service.IP_NET_TO_PHYSICAL_STATE: [(suffix, 1)],
        snmp_service.IF_NAME: [("7", b"Ethernet7")],
    }

    async def fake_walk(_ip, _credentials, oid, _port, **_kwargs):
        return columns[oid]

    monkeypatch.setattr(snmp_service, "_snmp_bulk_walk_complete", fake_walk)
    rows = asyncio.run(snmp_service.collect_ipv6_neighbor_table(
        "192.0.2.10", {"context_name": "Blue"}, version="3",
    ))

    assert rows == [{
        "ip_address": "fe80::1",
        "mac_address": "00:11:22:33:44:55",
        "interface": "Ethernet7",
        "if_index": 7,
        "inet_address_type": 4,
        "zone_index": 7,
        "type": "dynamic",
        "state": "reachable",
    }]
    assert snmp_service._decode_ip_net_to_physical_index(suffix)["if_index"] == 7


@pytest.mark.parametrize("suffix", ["7.4.19.1", "7.4.20." + ".".join(["256"] * 20), "broken"])
def test_bad_inetaddress_index_is_rejected(suffix):
    with pytest.raises(RuntimeError, match="IP-MIB"):
        snmp_service._decode_ip_net_to_physical_index(suffix)


def test_ip_net_to_physical_column_mismatch_and_walk_failure_are_rejected(monkeypatch):
    suffix = _oid_index(7, "2001:db8::7")
    other_suffix = _oid_index(8, "2001:db8::8")
    columns = {
        snmp_service.IP_NET_TO_PHYSICAL_PHYS_ADDRESS: [(suffix, bytes.fromhex("001122334455"))],
        snmp_service.IP_NET_TO_PHYSICAL_TYPE: [(suffix, 3)],
        snmp_service.IP_NET_TO_PHYSICAL_STATE: [(other_suffix, 1)],
        snmp_service.IF_NAME: [("7", "Ethernet7")],
    }

    async def fake_mismatch(_ip, _credentials, oid, _port, **_kwargs):
        return columns[oid]

    monkeypatch.setattr(snmp_service, "_snmp_bulk_walk_complete", fake_mismatch)
    with pytest.raises(RuntimeError, match="same row keys"):
        asyncio.run(snmp_service.collect_ipv6_neighbor_table("192.0.2.10", "fixture-community"))

    async def fake_failure(_ip, _credentials, oid, _port, **_kwargs):
        if oid == snmp_service.IP_NET_TO_PHYSICAL_STATE:
            raise TimeoutError("fixture timeout")
        return columns[oid]

    monkeypatch.setattr(snmp_service, "_snmp_bulk_walk_complete", fake_failure)
    with pytest.raises(TimeoutError, match="fixture timeout"):
        asyncio.run(snmp_service.collect_ipv6_neighbor_table("192.0.2.10", "fixture-community"))


def test_ip_net_to_physical_complete_empty_and_invalid_mac_state_type(monkeypatch):
    empty_columns = {
        snmp_service.IP_NET_TO_PHYSICAL_PHYS_ADDRESS: [],
        snmp_service.IP_NET_TO_PHYSICAL_TYPE: [],
        snmp_service.IP_NET_TO_PHYSICAL_STATE: [],
    }

    async def fake_empty(_ip, _credentials, oid, _port, **_kwargs):
        return empty_columns[oid]

    monkeypatch.setattr(snmp_service, "_snmp_bulk_walk_complete", fake_empty)
    assert asyncio.run(snmp_service.collect_ipv6_neighbor_table(
        "192.0.2.10", "fixture-community",
    )) == []

    suffix = _oid_index(7, "2001:db8::7")
    rows = {
        snmp_service.IP_NET_TO_PHYSICAL_PHYS_ADDRESS: [(suffix, b"\x01")],
        snmp_service.IP_NET_TO_PHYSICAL_TYPE: [(suffix, 3)],
        snmp_service.IP_NET_TO_PHYSICAL_STATE: [(suffix, 1)],
        snmp_service.IF_NAME: [("7", "Ethernet7")],
    }

    async def fake_row(_ip, _credentials, oid, _port, **_kwargs):
        return rows[oid]

    monkeypatch.setattr(snmp_service, "_snmp_bulk_walk_complete", fake_row)
    with pytest.raises(RuntimeError, match="physical address"):
        asyncio.run(snmp_service.collect_ipv6_neighbor_table("192.0.2.10", "fixture-community"))

    rows[snmp_service.IP_NET_TO_PHYSICAL_PHYS_ADDRESS] = [
        (suffix, bytes.fromhex("001122334455")),
    ]
    rows[snmp_service.IP_NET_TO_PHYSICAL_STATE] = [(suffix, 99)]
    with pytest.raises(RuntimeError, match="type or state"):
        asyncio.run(snmp_service.collect_ipv6_neighbor_table("192.0.2.10", "fixture-community"))


def test_complete_empty_replaces_only_one_context(isolated_db, monkeypatch):
    device_id = "ndp-empty-one-context"
    _insert_device(device_id)
    _insert_context_mapping(device_id, "A")
    _insert_context_mapping(device_id, "B")
    _seed_current(device_id, context_key="A", ip="2001:db8::a", mac="0011223344aa")
    _seed_current(device_id, context_key="B", ip="2001:db8::b", mac="0011223344bb")
    _set_v3_credentials(monkeypatch)

    async def fake_collect(_ip, profile, *, port=161, version, timeout=120):
        assert version == "3"
        assert timeout == 120
        assert port == 161
        if profile["context_name"] == "A":
            return []
        return [_record("2001:db8::b", "00:11:22:33:44:bc", "Ethernet2")]

    monkeypatch.setattr(snmp_service, "collect_ipv6_neighbor_table", fake_collect)
    result = ndp_service.run_current_ndp_collection(device_ids={device_id})

    assert result["coverage_status"] == "complete"
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id, observation_source="ndp")
        states = {
            row["local_context_key"]: row
            for row in get_current_endpoint_collection_states(
                conn, device_id=device_id, observation_source="ndp",
            )
        }
    assert [(row["local_context_key"], row["ip_address"]) for row in rows] == [("B", "2001:db8::b")]
    assert states["A"]["latest_status"] == "complete"
    assert states["A"]["last_success_generation"] == 2
    assert states["A"]["current_row_count"] == 0
    assert states["B"]["last_success_generation"] == 2


def test_partial_context_retains_current_snapshot(isolated_db, monkeypatch):
    device_id = "ndp-partial-preserves"
    _insert_device(device_id)
    _insert_context_mapping(device_id, "Blue")
    _seed_current(device_id, context_key="Blue", ip="fe80::10", mac="001122334410")
    _set_v3_credentials(monkeypatch)

    async def fake_collect(*_args, **_kwargs):
        raise RuntimeError("IP-MIB row index is malformed")

    monkeypatch.setattr(snmp_service, "collect_ipv6_neighbor_table", fake_collect)
    result = ndp_service.run_current_ndp_collection(device_ids={device_id})

    assert result["coverage_status"] == "partial"
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id, observation_source="ndp")
        state = get_current_endpoint_collection_states(
            conn, device_id=device_id, observation_source="ndp",
        )[0]
    assert [(row["ip_address"], row["mac_address"], row["generation"]) for row in rows] == [
        ("fe80::10", "001122334410", 1),
    ]
    assert state["latest_status"] == "partial"
    assert state["last_success_generation"] == 1


def test_same_link_local_address_is_kept_per_context_and_interface(isolated_db, monkeypatch):
    device_id = "ndp-link-local-scopes"
    _insert_device(device_id)
    _insert_context_mapping(device_id, "Blue")
    _insert_context_mapping(device_id, "Red")
    _set_v3_credentials(monkeypatch)

    async def fake_collect(_ip, profile, *, port=161, version, timeout=120):
        if profile["context_name"] == "Blue":
            return [
                _record("fe80::abcd", "00:11:22:33:44:01", "Ethernet1", if_index=1, zone_index=1),
                _record("fe80::abcd", "00:11:22:33:44:02", "Ethernet2", if_index=2, zone_index=2),
            ]
        return [_record("fe80::abcd", "00:11:22:33:44:03", "Ethernet3", if_index=3, zone_index=3)]

    monkeypatch.setattr(snmp_service, "collect_ipv6_neighbor_table", fake_collect)
    result = ndp_service.run_current_ndp_collection(device_ids={device_id})

    assert result["coverage_status"] == "complete"
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id, observation_source="ndp")
    assert len(rows) == 3
    assert {
        (row["local_context_key"], row["ip_address"], row["interface_name"], row["mac_address"])
        for row in rows
    } == {
        ("Blue", "fe80::abcd", "Ethernet1", "001122334401"),
        ("Blue", "fe80::abcd", "Ethernet2", "001122334402"),
        ("Red", "fe80::abcd", "Ethernet3", "001122334403"),
    }
    assert all(row["vlan_id"] is None for row in rows)


def test_v2c_with_active_mappings_stays_unknown_and_reports_partial(isolated_db, monkeypatch):
    device_id = "ndp-v2-unknown-context"
    _insert_device(device_id)
    _insert_context_mapping(device_id, "global", context_type="global")
    _insert_context_mapping(device_id, "Blue")
    _seed_current(
        device_id,
        context_type="global",
        context_key="global",
        ip="2001:db8::1",
        mac="001122334401",
    )
    _seed_current(
        device_id,
        context_type="vrf",
        context_key="Blue",
        ip="2001:db8::2",
        mac="001122334402",
    )
    _set_v2_credentials(monkeypatch)
    seen = []

    async def fake_collect(_ip, community, *, port=161, version, timeout=120):
        assert port == 161
        seen.append((community, version))
        return [_record("fe80::20", "00:11:22:33:44:20", "Ethernet20")]

    monkeypatch.setattr(snmp_service, "collect_ipv6_neighbor_table", fake_collect)
    result = ndp_service.run_current_ndp_collection(device_ids={device_id})

    assert seen == [("fixture-community", "2c")]
    assert result["coverage_status"] == "partial"
    assert result["contexts_uncovered"] == 2
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id, observation_source="ndp")
        states = get_current_endpoint_collection_states(
            conn, device_id=device_id, observation_source="ndp",
        )
    assert {row["context_type"] for row in rows} == {"unknown", "global", "vrf"}
    unknown = next(row for row in rows if row["context_type"] == "unknown")
    assert unknown["address_space_id"] is None
    assert unknown["local_context_key"] == ""
    assert {row["local_context_key"] for row in states if row["context_type"] != "unknown"} == {
        "global", "Blue",
    }
    assert all(row["last_success_generation"] == 1 for row in states if row["context_type"] != "unknown")


def test_ambiguous_v3_context_key_is_collected_once_as_unknown(isolated_db, monkeypatch):
    device_id = "ndp-ambiguous-context-key"
    _insert_device(device_id)
    global_space = _insert_context_mapping(device_id, "Blue", context_type="global")
    vrf_space = _insert_context_mapping(device_id, "Blue", context_type="vrf")
    _seed_current(
        device_id, context_type="global", context_key="Blue",
        ip="2001:db8::1", mac="001122334401",
    )
    _seed_current(
        device_id, context_type="vrf", context_key="Blue",
        ip="2001:db8::2", mac="001122334402",
    )
    _set_v3_credentials(monkeypatch)
    seen_contexts = []

    async def fake_collect(_ip, profile, *, port=161, version, timeout=120):
        seen_contexts.append(profile["context_name"])
        return [_record("fe80::30", "00:11:22:33:44:30", "Ethernet30")]

    monkeypatch.setattr(snmp_service, "collect_ipv6_neighbor_table", fake_collect)
    result = ndp_service.run_current_ndp_collection(device_ids={device_id})

    assert seen_contexts == ["Blue"]
    assert result["coverage_status"] == "partial"
    assert result["contexts_uncovered"] == 2
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id, observation_source="ndp")
        states = get_current_endpoint_collection_states(
            conn, device_id=device_id, observation_source="ndp",
        )
    ambiguous = next(row for row in rows if row["context_type"] == "unknown")
    assert ambiguous["local_context_key"] == "Blue"
    assert ambiguous["address_space_id"] is None
    assert {row["address_space_id"] for row in rows if row["context_type"] != "unknown"} == {
        global_space, vrf_space,
    }
    assert {
        (row["context_type"], row["local_context_key"], row["last_success_generation"])
        for row in states if row["context_type"] != "unknown"
    } == {("global", "Blue", 1), ("vrf", "Blue", 1)}


def test_no_eligible_snmp_device_is_not_reported_complete(isolated_db, monkeypatch):
    device_id = "ndp-no-snmp-device"
    _insert_device(device_id)
    monkeypatch.setattr(ndp_service.vault_service, "resolve_collector_credentials", lambda _device: {
        "snmp": {"configured": False, "version": "2c", "community": ""},
    })

    result = ndp_service.run_current_ndp_collection(device_ids={device_id})
    empty_result = ndp_service.run_current_ndp_collection(device_ids=set())

    assert result["eligible_devices"] == 0
    assert result["status"] == "skipped"
    assert result["coverage_status"] == "not_collected"
    assert result["contexts_attempted"] == 0
    assert empty_result["status"] == "skipped"
    assert empty_result["coverage_status"] == "not_collected"
    assert empty_result["devices_seen"] == 0


def test_generation_fencing_preserves_newer_current_snapshot(isolated_db, monkeypatch):
    device_id = "ndp-generation-fencing"
    _insert_device(device_id)
    _insert_context_mapping(device_id, "Blue")
    _seed_current(device_id, context_key="Blue", ip="2001:db8::1", mac="001122334401")
    _set_v3_credentials(monkeypatch)

    async def fake_collect(_ip, _profile, *, port=161, version, timeout=120):
        attempted = _now()
        context = {"context_source": "snmp", "context_type": "vrf", "local_context_key": "Blue"}
        with get_db_connection() as conn:
            newer_generation = begin_current_endpoint_collection(
                conn,
                device_id=device_id,
                observation_source="ndp",
                **context,
                attempted_at=attempted,
                run_id="newer-ndp-run",
            )
            conn.commit()
        with get_db_connection() as conn:
            finish_current_endpoint_collection(
                conn,
                device_id=device_id,
                observation_source="ndp",
                **context,
                generation=newer_generation,
                status="complete",
                attempted_at=attempted,
                completed_at=_now(),
                observations=[{
                    "ip_address": "2001:db8::2",
                    "mac_address": "00:11:22:33:44:02",
                    "interface_name": "Ethernet2",
                    **context,
                }],
                run_id="newer-ndp-run",
            )
            conn.commit()
        return [_record("2001:db8::3", "00:11:22:33:44:03", "Ethernet3")]

    monkeypatch.setattr(snmp_service, "collect_ipv6_neighbor_table", fake_collect)
    result = ndp_service.run_current_ndp_collection(device_ids={device_id})

    assert result["coverage_status"] == "partial"
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id, observation_source="ndp")
        state = get_current_endpoint_collection_states(
            conn, device_id=device_id, observation_source="ndp",
        )[0]
    assert [(row["ip_address"], row["generation"]) for row in rows] == [("2001:db8::2", 3)]
    assert state["latest_attempt_generation"] == 3
    assert state["last_run_id"] == "newer-ndp-run"


def test_current_ndp_collection_does_not_call_historical_projectors(isolated_db, monkeypatch):
    device_id = "ndp-current-only"
    _insert_device(device_id)
    _insert_context_mapping(device_id, "Blue")
    _set_v3_credentials(monkeypatch)

    async def fake_collect(*_args, **_kwargs):
        return [_record("2001:db8::10", "00:11:22:33:44:10", "Ethernet10")]

    monkeypatch.setattr(snmp_service, "collect_ipv6_neighbor_table", fake_collect)
    from services import ip_locator_service, ipam_discovery_service

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("historical IPAM projection must not run from the current NDP collector")

    monkeypatch.setattr(ip_locator_service, "project_endpoint_evidence", fail_if_called)
    monkeypatch.setattr(ipam_discovery_service, "run_ipam_discovery_projection", fail_if_called)
    result = ndp_service.run_current_ndp_collection(device_ids={device_id})

    assert result["status"] == "success"
    with get_db_connection() as conn:
        rows = list_current_endpoint_observations(conn, device_id=device_id, observation_source="ndp")
    assert len(rows) == 1
