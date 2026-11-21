from __future__ import annotations

import pytest


def _configured_device_credentials(monkeypatch, device, credentials=None):
    from services import interface_collection_service, vault_service

    monkeypatch.setattr(interface_collection_service, "_load_device", lambda _device_id: device)
    monkeypatch.setattr(
        vault_service,
        "resolve_collector_credentials",
        lambda _device: credentials or {
            "snmp": {
                "configured": True,
                "community": "read-only-test",
                "server": "192.0.2.25",
                "port": 1161,
            }
        },
    )


def test_refresh_snmp_interface_inventory_persists_only_valid_indexed_ports(monkeypatch) -> None:
    from services import interface_collection_service, snmp_service

    device = {"id": "device-a", "ip_address": "192.0.2.10"}
    _configured_device_credentials(monkeypatch, device)
    collection_calls = []
    persisted = []

    async def fake_collect(ip, community, port, version='2c'):
        collection_calls.append((ip, community, port, version))
        return [
            {"name": "GigabitEthernet0/0", "if_index": 17},
            {"name": "GigabitEthernet0/1", "if_index": 0},
        ]

    monkeypatch.setattr(snmp_service, "collect_interface_inventory", fake_collect)
    monkeypatch.setattr(
        interface_collection_service,
        "_upsert_snmp_interfaces",
        lambda target, rows: persisted.extend(rows) or len(rows),
    )

    result = interface_collection_service.refresh_snmp_interface_inventory("device-a")

    assert collection_calls == [("192.0.2.25", "read-only-test", 1161, "2c")]
    assert result == {"device_id": "device-a", "interface_count": 1, "updated_count": 1}
    assert [row["if_index"] for row in persisted] == [17]


def test_refresh_snmp_interface_inventory_reports_poll_failure_without_secret(monkeypatch) -> None:
    from services import interface_collection_service, snmp_service

    device = {"id": "device-a", "ip_address": "192.0.2.10"}
    _configured_device_credentials(monkeypatch, device)

    async def fail_collect(_ip, community, _port, version='2c'):
        del version
        raise TimeoutError(f"poll timeout for {community}")

    monkeypatch.setattr(snmp_service, "collect_interface_inventory", fail_collect)

    with pytest.raises(interface_collection_service.InterfaceInventorySyncError) as error:
        interface_collection_service.refresh_snmp_interface_inventory("device-a")

    assert error.value.code == "snmp_interface_read_failed"
    assert "read-only-test" not in str(error.value)
    assert "只读权限" in str(error.value)


def test_refresh_snmp_interface_inventory_rejects_empty_or_invalid_interface_data(monkeypatch) -> None:
    from services import interface_collection_service, snmp_service

    device = {"id": "device-a", "ip_address": "192.0.2.10"}
    _configured_device_credentials(monkeypatch, device)

    async def no_valid_interfaces(ip, community, port, version='2c'):
        assert ip == "192.0.2.25"
        assert community == "read-only-test"
        assert port == 1161
        assert version == "2c"
        return [{"name": "GigabitEthernet0/0", "if_index": 0}]

    monkeypatch.setattr(snmp_service, "collect_interface_inventory", no_valid_interfaces)

    with pytest.raises(interface_collection_service.InterfaceInventorySyncError) as error:
        interface_collection_service.refresh_snmp_interface_inventory("device-a")

    assert error.value.code == "snmp_no_valid_interfaces"
    assert "IF-MIB" in str(error.value)


def test_refresh_snmp_interface_inventory_rejects_missing_read_only_community(monkeypatch) -> None:
    from services import interface_collection_service

    device = {"id": "device-a", "ip_address": "192.0.2.10"}
    _configured_device_credentials(monkeypatch, device, {"snmp": {"configured": False}})

    with pytest.raises(interface_collection_service.InterfaceInventorySyncError) as error:
        interface_collection_service.refresh_snmp_interface_inventory("device-a")

    assert error.value.code == "snmp_not_configured"
    assert "SNMP 只读凭据" in str(error.value)
