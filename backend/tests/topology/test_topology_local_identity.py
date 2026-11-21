from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock

from services import topology_local_identity_service as service


def run(coro):
    return asyncio.run(coro)


def device(**overrides):
    value = {"id": "device-1", "ip_address": "192.0.2.10", "tenant_id": "tenant-1"}
    value.update(overrides)
    return value


def credentials():
    return {
        "snmp": {
            "server": "192.0.2.10",
            "community": "private-ro",
            "port": 1161,
            "version": "1",
        },
        "ssh": {"username": "operator", "password": "password-for-test"},
    }


def test_snmp_ip_mib_indexes_collect_ipv4_and_ipv6(monkeypatch):
    calls = []

    async def fake_walk(ip, community, oid, **kwargs):
        calls.append((ip, community, oid, kwargs))
        if oid == service.IP_AD_ENT_ADDR_OID:
            return [("192.0.2.10", "192.0.2.10"), ("127.0.0.1", "127.0.0.1")]
        return [
            ("1.4.192.0.2.20", "3"),
            ("2.16.32.1.13.184.0.0.0.0.0.0.0.0.0.0.0.1", "4"),
        ]

    monkeypatch.setattr(service, "_snmp_walk", fake_walk)
    result = run(service.collect_topology_local_identity(device(), credentials()))

    assert result == {
        "ip_addresses": ["192.0.2.10", "192.0.2.20", "2001:db8::1"],
        "collection_sources": ["snmp"],
        "status": "success",
    }
    assert [item[2] for item in calls] == [service.IP_AD_ENT_ADDR_OID, service.IP_ADDRESS_IF_INDEX_OID]
    assert all(item[1] == "private-ro" for item in calls)
    assert all(item[3]["port"] == 1161 and item[3]["version"] == "1" for item in calls)
    assert all(item[3]["timeout"] <= service.SNMP_TIMEOUT_SECONDS for item in calls)
    assert all(item[3]["max_rows"] == service.MAX_IP_ADDRESSES for item in calls)
    assert all(item[3]["raise_on_error"] is True for item in calls)


def test_snmp_malformed_index_lengths_are_not_decoded_as_identity():
    assert service._ip_from_ip_address_if_index_suffix("1.4.192.0.2.20.99") is None
    assert service._ip_from_ip_address_if_index_suffix("2.16.32.1.13.184.0.0.0.0.0.0.0.0.0.0.0.1.99") is None
    assert service._ip_from_ip_address_if_index_suffix("1.192.0.2.20.99") is None
    assert service._ip_from_ip_address_if_index_suffix("2.32.1.13.184.0.0.0.0.0.0.0.0.0.0.0.1.99") is None


def test_bound_platform_action_extracts_multiple_vendor_canonical_fields(monkeypatch):
    observed = {}

    def fake_execute(device_id, action_code, **kwargs):
        observed.update(device_id=device_id, action_code=action_code, kwargs=kwargs)
        return {
            "success": True,
            "records": [
                {"INTERFACE": "Vlan100", "IP_ADDRESS": "10.0.0.1/24", "PRIMARY_IP": "2001:db8::10/64"},
                {"interface": "Vlan200", "IPv4": "10.0.0.2", "secondary_ip": "127.0.0.1"},
            ],
        }

    async def no_snmp(*_args, **_kwargs):
        return []

    monkeypatch.setattr(service, "_snmp_walk", no_snmp)
    monkeypatch.setattr(service, "execute_platform_action", fake_execute)
    result = run(
        service.collect_topology_local_identity(
            device(platform_profile_id="profile-1"), credentials(), platform_action_session="session"
        )
    )

    assert result["ip_addresses"] == ["10.0.0.1", "2001:db8::10", "10.0.0.2"]
    assert result["collection_sources"] == ["ssh"]
    assert result["status"] == "success"
    assert observed["action_code"] == "get_ip_interfaces"
    assert observed["kwargs"]["user"]["role"] == "Operator"
    assert observed["kwargs"]["user"]["tenant_id"] == "tenant-1"
    assert observed["kwargs"]["_session"] == "session"


def test_cli_identity_ignores_remote_and_gateway_ip_fields(monkeypatch):
    async def no_snmp(*_args, **_kwargs):
        return []

    monkeypatch.setattr(service, "_snmp_walk", no_snmp)
    monkeypatch.setattr(
        service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [{
                "key": "interfaces",
                "success": True,
                "records": [{
                    "interface": "Vlan100",
                    "IP-Address": "10.0.0.1/24",
                    "ipv4_address": "10.0.0.2",
                    "gateway_ip": "10.0.0.254",
                    "neighbor_ip": "10.0.0.3",
                    "peer_ipv4": "10.0.0.4",
                    "destination_ip": "10.0.0.5",
                    "network_ip": "10.0.0.0",
                }],
            }]
        },
    )

    result = run(service.collect_topology_local_identity(device(), credentials()))

    assert result["ip_addresses"] == ["10.0.0.1", "10.0.0.2"]
    assert result["collection_sources"] == ["ssh"]
    assert service._is_explicit_ip_field("IP-Address")
    assert service._is_explicit_ip_field("ip_addresses")
    assert not service._is_explicit_ip_field("gateway_ip")
    assert not service._is_explicit_ip_field("neighbor_ip")
    assert not service._is_explicit_ip_field("peer_ipv4")


def test_snmp_failed_skips_snmp_and_falls_back_to_unbound_cli(monkeypatch):
    calls = {"snmp": 0, "cli": 0}

    async def fail_if_called(*_args, **_kwargs):
        calls["snmp"] += 1
        raise AssertionError("SNMP must be skipped after this-run failure")

    def fake_collect(*_args, **kwargs):
        calls["cli"] += 1
        assert kwargs["categories"] == ["interfaces"]
        assert kwargs["auth_role"] == "normal"
        return {"categories": [{"key": "interfaces", "success": True, "records": [{"ip": "10.10.10.1/32"}]}]}

    monkeypatch.setattr(service, "_snmp_walk", fail_if_called)
    monkeypatch.setattr(service, "collect_operational_data", fake_collect)
    result = run(
        service.collect_topology_local_identity(
            device(), credentials(), protocol_results={"snmp": {"status": "failed"}}
        )
    )

    assert result["ip_addresses"] == ["10.10.10.1"]
    assert result["collection_sources"] == ["ssh"]
    assert calls == {"snmp": 0, "cli": 1}


def test_snmp_table_error_and_empty_table_fall_back_to_cli(monkeypatch):
    walked_oids = []

    async def fake_walk(_ip, _community, oid, **kwargs):
        assert kwargs["raise_on_error"] is True
        walked_oids.append(oid)
        if oid == service.IP_AD_ENT_ADDR_OID:
            raise TimeoutError("timeout details must not be logged")
        return []

    monkeypatch.setattr(service, "_snmp_walk", fake_walk)
    monkeypatch.setattr(
        service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [{"key": "interfaces", "success": True, "records": [{"IP_ADDRESS": "10.20.30.1/24"}]}]
        },
    )

    result = run(service.collect_topology_local_identity(device(), credentials()))

    assert walked_oids == [service.IP_AD_ENT_ADDR_OID, service.IP_ADDRESS_IF_INDEX_OID]
    assert result == {
        "ip_addresses": ["10.20.30.1"],
        "collection_sources": ["ssh"],
        "status": "success",
    }


def test_snmp_truncated_table_is_discarded_before_identity_extraction(monkeypatch):
    async def fake_walk(_ip, _community, oid, **_kwargs):
        if oid == service.IP_AD_ENT_ADDR_OID:
            return [(f"192.0.2.{index % 254 + 1}", "") for index in range(service.MAX_IP_ADDRESSES)]
        return [("1.4.198.51.100.1", "")]

    monkeypatch.setattr(service, "_snmp_walk", fake_walk)
    result = run(service.collect_topology_local_identity(device(), credentials()))

    assert result["ip_addresses"] == ["198.51.100.1"]
    assert result["collection_sources"] == ["snmp"]


def test_ssh_failed_skips_cli_when_snmp_has_no_data(monkeypatch):
    calls = {"snmp": 0, "cli": 0}

    async def empty_walk(*_args, **_kwargs):
        calls["snmp"] += 1
        return []

    def fail_if_called(*_args, **_kwargs):
        calls["cli"] += 1
        raise AssertionError("SSH must be skipped after this-run failure")

    monkeypatch.setattr(service, "_snmp_walk", empty_walk)
    monkeypatch.setattr(service, "collect_operational_data", fail_if_called)
    result = run(
        service.collect_topology_local_identity(
            device(), credentials(), protocol_results={"ssh": {"status": "failed"}}
        )
    )

    assert result == {"ip_addresses": [], "collection_sources": [], "status": "unavailable"}
    assert calls == {"snmp": 2, "cli": 0}


def test_all_failed_protocols_are_skipped(monkeypatch):
    async def fail_snmp(*_args, **_kwargs):
        raise AssertionError("failed SNMP protocol must not be retried")

    def fail_ssh(*_args, **_kwargs):
        raise AssertionError("failed SSH protocol must not be retried")

    monkeypatch.setattr(service, "_snmp_walk", fail_snmp)
    monkeypatch.setattr(service, "collect_operational_data", fail_ssh)
    monkeypatch.setattr(service, "execute_platform_action", fail_ssh)
    result = run(
        service.collect_topology_local_identity(
            device(platform_profile_id="profile-1"),
            credentials(),
            protocol_results={"snmp": {"status": "failed"}, "ssh": {"status": "failed"}},
        )
    )
    assert result["status"] == "unavailable"


@pytest.mark.parametrize("platform_profile_id", ["", "profile-1"])
def test_snmp_only_collection_does_not_open_cli_for_missing_local_ips(monkeypatch, platform_profile_id):
    async def empty_walk(*_args, **_kwargs):
        return []

    cli_collection = AsyncMock(return_value=["192.0.2.10"])
    monkeypatch.setattr(service, "_snmp_walk", empty_walk)
    monkeypatch.setattr(service, "_collect_ssh_ips", cli_collection)

    result = run(
        service.collect_topology_local_identity(
            device(platform_profile_id=platform_profile_id),
            credentials(),
            protocol_results={"snmp": {"status": "success"}, "ssh": {"status": "not_attempted"}},
        )
    )

    assert result == {"ip_addresses": [], "collection_sources": [], "status": "unavailable"}
    cli_collection.assert_not_awaited()


def test_missing_community_never_uses_secret_fallback(monkeypatch):
    calls = []

    async def fake_walk(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("SNMP must not run without an explicit community")

    monkeypatch.setattr(service, "_snmp_walk", fake_walk)
    monkeypatch.setattr(
        service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {"categories": [{"key": "interfaces", "success": True, "records": []}]},
    )
    result = run(
        service.collect_topology_local_identity(
            device(), {"snmp": {"server": "192.0.2.10", "port": 161, "version": "2c"}, "ssh": credentials()["ssh"]}
        )
    )
    assert result == {"ip_addresses": [], "collection_sources": [], "status": "unavailable"}
    assert calls == []
