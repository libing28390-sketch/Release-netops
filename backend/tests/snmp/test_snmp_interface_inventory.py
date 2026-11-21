from __future__ import annotations

import asyncio

from services import snmp_service


def test_interface_inventory_reads_only_if_name_table(monkeypatch) -> None:
    calls = []

    async def fake_bulk_walk(ip, community, oid, port=161, *, version='2c'):
        assert version == '2c'
        calls.append((ip, community, oid, port))
        return [("17", "GigabitEthernet0/0"), ("18", "GigabitEthernet0/1")]

    monkeypatch.setattr(snmp_service, "_snmp_bulk_walk", fake_bulk_walk)

    result = asyncio.run(snmp_service.collect_interface_inventory("192.0.2.5", "read-only-test", 1161))

    assert result == [
        {"name": "GigabitEthernet0/0", "if_index": 17, "status": "unknown", "admin_status": "unknown", "description": ""},
        {"name": "GigabitEthernet0/1", "if_index": 18, "status": "unknown", "admin_status": "unknown", "description": ""},
    ]
    assert calls == [("192.0.2.5", "read-only-test", snmp_service.IF_NAME, 1161)]


def test_interface_inventory_falls_back_to_if_descr_and_drops_invalid_indexes(monkeypatch) -> None:
    calls = []

    async def fake_bulk_walk(ip, community, oid, port=161, *, version='2c'):
        assert version == '2c'
        calls.append(oid)
        if oid == snmp_service.IF_NAME:
            return []
        return [("0", "GigabitEthernet0/0"), ("21", "TenGigabitEthernet0/1")]

    monkeypatch.setattr(snmp_service, "_snmp_bulk_walk", fake_bulk_walk)

    result = asyncio.run(snmp_service.collect_interface_inventory("192.0.2.5", "read-only-test"))

    assert result == [{"name": "TenGigabitEthernet0/1", "if_index": 21, "status": "unknown", "admin_status": "unknown", "description": ""}]
    assert calls == [snmp_service.IF_NAME, snmp_service.IF_DESCR]
