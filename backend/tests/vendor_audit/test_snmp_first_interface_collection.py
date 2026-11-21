import pytest
from core.interface_utils import normalize_interface_name
from database import get_db_connection
from services.interface_collection_service import (
    _collect_snmp_interfaces,
    _upsert_snmp_interfaces,
    _upsert_interfaces,
)


@pytest.fixture
def mock_device():
    return {
        "id": "test-sw-snmp-01",
        "hostname": "H3C-S6800-Core",
        "ip_address": "192.168.10.1",
        "vendor": "h3c",
        "platform": "h3c_comware",
    }


def test_snmp_first_collection_upserts_l2_and_l3_interfaces(mock_device, monkeypatch):
    """Verify SNMP IF-MIB collector ingests physical/L2 ports with correct admin/oper status."""
    mock_creds = {
        "snmp": {
            "version": "2c",
            "server": "192.168.10.1",
            "community": "public-test",
            "port": 161,
            "configured": True,
        }
    }
    monkeypatch.setattr(
        "services.vault_service.resolve_collector_credentials",
        lambda dev: mock_creds,
    )

    mock_snmp_data = [
        {
            "name": "GigabitEthernet1/0/1",
            "status": "up",
            "admin_status": "up",
            "speed_mbps": 1000,
            "description": "Uplink-To-Spine",
            "if_index": 1,
        },
        {
            "name": "GigabitEthernet1/0/2",
            "status": "down",
            "admin_status": "down",
            "speed_mbps": 1000,
            "description": "Unused-Access",
            "if_index": 2,
        },
        {
            "name": "Vlan-interface10",
            "status": "up",
            "admin_status": "up",
            "speed_mbps": 0,
            "description": "Mgmt-VLAN",
            "if_index": 10,
        },
    ]

    async def mock_collect_interface_data(*args, **kwargs):
        return mock_snmp_data

    monkeypatch.setattr(
        "services.snmp_service.collect_interface_status_data",
        mock_collect_interface_data,
    )

    conn = get_db_connection()
    try:
        # Ensure device exists to satisfy foreign key
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, vendor, platform, status)
               VALUES (?, ?, ?, ?, ?, 'online')
               ON CONFLICT(id) DO NOTHING""",
            (mock_device["id"], mock_device["hostname"], mock_device["ip_address"], mock_device["vendor"], mock_device["platform"]),
        )
        conn.execute("DELETE FROM interfaces WHERE device_id = ?", (mock_device["id"],))
        conn.commit()

        # 1. Test collection
        interfaces = _collect_snmp_interfaces(mock_device)
        assert interfaces is not None
        assert len(interfaces) == 3

        # 2. Test upsert
        updated = _upsert_snmp_interfaces(mock_device, interfaces)
        assert updated == 3

        rows = conn.execute(
            "SELECT interface_name, if_index, admin_status, oper_status, speed, description FROM interfaces WHERE device_id = ?",
            (mock_device["id"],),
        ).fetchall()

        by_name = {r["interface_name"]: dict(r) for r in rows}
        assert "GigabitEthernet1/0/1" in by_name
        assert by_name["GigabitEthernet1/0/1"]["admin_status"] == "up"
        assert by_name["GigabitEthernet1/0/1"]["oper_status"] == "up"
        assert by_name["GigabitEthernet1/0/1"]["speed"] == 1_000_000_000
        assert by_name["GigabitEthernet1/0/1"]["description"] == "Uplink-To-Spine"
        assert by_name["GigabitEthernet1/0/1"]["if_index"] == 1

        assert "GigabitEthernet1/0/2" in by_name
        assert by_name["GigabitEthernet1/0/2"]["admin_status"] == "down"
        assert by_name["GigabitEthernet1/0/2"]["oper_status"] == "down"
        assert by_name["GigabitEthernet1/0/2"]["if_index"] == 2

        # 3. Test that subsequent CLI L3 collection does NOT clobber GE1/0/1 or GE1/0/2 to unknown
        cli_l3_rows = [
            {
                "interface_name": "Vlan-interface10",
                "interface_ip": "192.168.10.1",
                "prefix_length": 24,
                "admin_status": "up",
                "oper_status": "up",
                "description": "Mgmt-VLAN",
            }
        ]

        _upsert_interfaces(mock_device, cli_l3_rows)

        # Re-verify GE1/0/1 is STILL up and NOT unknown
        rows_after_cli = conn.execute(
            "SELECT interface_name, admin_status, oper_status, primary_ip FROM interfaces WHERE device_id = ?",
            (mock_device["id"],),
        ).fetchall()
        by_name_after = {r["interface_name"]: dict(r) for r in rows_after_cli}

        assert by_name_after["GigabitEthernet1/0/1"]["admin_status"] == "up"
        assert by_name_after["GigabitEthernet1/0/1"]["oper_status"] == "up"
        assert by_name_after["GigabitEthernet1/0/2"]["admin_status"] == "down"
        assert by_name_after["GigabitEthernet1/0/2"]["oper_status"] == "down"
        assert by_name_after["Vlan-interface10"]["primary_ip"] == "192.168.10.1"

        # Clean up
        conn.execute("DELETE FROM interfaces WHERE device_id = ?", (mock_device["id"],))
        conn.execute("DELETE FROM devices WHERE id = ?", (mock_device["id"],))
        conn.commit()
    finally:
        conn.close()


def test_on_demand_wan_interface_refresh_collects_and_persists_one_device(monkeypatch):
    import asyncio

    from services import interface_collection_service

    device = {
        "id": "wan-refresh-device",
        "hostname": "edge-router",
        "ip_address": "192.0.2.10",
    }
    credentials = {
        "snmp": {
            "configured": True,
            "server": "192.0.2.11",
            "community": "test-only-community",
            "port": 1161,
        }
    }
    calls = {}
    collected = [{"name": "GigabitEthernet0/0", "if_index": 42, "status": "up", "speed_mbps": 1000}]

    monkeypatch.setattr(interface_collection_service, "_load_device", lambda device_id: device)
    monkeypatch.setattr("services.vault_service.resolve_collector_credentials", lambda _device: credentials)

    async def fake_collect(ip, community, port, version='2c'):
        calls["collector"] = (ip, community, port, version)
        return collected

    monkeypatch.setattr("services.snmp_service.collect_interface_inventory", fake_collect)
    monkeypatch.setattr(interface_collection_service, "_run_async", lambda coroutine: asyncio.run(coroutine))

    def capture_upsert(upsert_device, interfaces):
        calls["upsert"] = (upsert_device, interfaces)
        return len(interfaces)

    monkeypatch.setattr(interface_collection_service, "_upsert_snmp_interfaces", capture_upsert)

    result = interface_collection_service.refresh_snmp_interface_inventory("wan-refresh-device")

    assert result == {"device_id": "wan-refresh-device", "interface_count": 1, "updated_count": 1}
    assert calls["collector"] == ("192.0.2.11", "test-only-community", 1161, "2c")
    assert calls["upsert"][0] is device
    assert calls["upsert"][1][0]["if_index"] == 42
