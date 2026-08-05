import sqlite3

import pytest

from database.migrations.m0044_vlan_discovery_metadata import upgrade
from services.cmdb_service import (
    create_vlan_business_binding,
    export_vlans,
    list_vlans,
    update_vlan_business_binding,
)
from services.vlan_discovery_service import (
    is_svi_interface,
    parse_vlan_id_from_interface,
    parse_vlan_values,
    project_vlan_records,
    is_system_default_vlan,
    sync_observed_vlans,
)


def test_default_vlan_policy_keeps_business_vlan_inventory_clean():
    assert is_system_default_vlan(1)
    assert is_system_default_vlan(1002, "fddi-default", platform="cisco_ios")
    assert is_system_default_vlan(1005, "trnet-default")
    assert not is_system_default_vlan(1002, "APP-NET", platform="huawei_vrp")
    assert not is_system_default_vlan(1002, "APP-NET", platform="cisco_ios", discovery_source="manual")


def test_vlanif_and_svi_names_are_normalized_to_vlan_ids():
    vendor_svi_names = {
        "Vlan7": 7,                 # Cisco / Arista / Ruijie
        "Vlanif10": 10,             # Huawei
        "Vlan-interface 20": 20,    # H3C / Comware
        "SVI-30": 30,
        "BVI40": 40,                # Cisco bridge virtual interface
        "BDI50": 50,                # Cisco bridge-domain interface
        "IRB.60": 60,               # Juniper
        "Ve70": 70,                 # Brocade-style virtual Ethernet
        "Bridge80": 80,
    }
    for interface_name, vlan_id in vendor_svi_names.items():
        assert parse_vlan_id_from_interface(interface_name) == vlan_id
        assert is_svi_interface(interface_name)

    assert is_svi_interface("IRB.0")
    assert parse_vlan_id_from_interface("GigabitEthernet1/0/1") is None
    assert not is_svi_interface("GigabitEthernet1/0/1")


def test_allowed_vlan_ranges_are_bounded_and_normalized():
    assert parse_vlan_values("10, 20-22 trunk") == {10, 20, 21, 22}
    assert parse_vlan_values("0, 4095, 100") == {100}


def test_vlan_discovery_migration_is_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE vlans (id TEXT PRIMARY KEY, vlan_id INTEGER, name TEXT)")
    upgrade(conn.cursor(), False)
    upgrade(conn.cursor(), False)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(vlans)").fetchall()}
    assert {"discovery_source", "first_discovered_at", "last_discovered_at", "discovery_run_id"} <= columns


def test_svi_observation_creates_vlan_inventory_record(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, site_id, site) VALUES (?, ?, ?, ?, ?)",
        ("device-svi-1", "gw-01", "online", "", ""),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, description, interface_type, switchport_mode,
            primary_ip, ip_address, is_l3, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("intf-svi-10", "device-svi-1", "Vlanif10", "Finance gateway", "svi", "routed", "10.0.10.1", "10.0.10.1", 1, "2026-07-29T00:00:00+00:00"),
    )
    conn.commit()
    result = sync_observed_vlans()
    row = conn.execute("SELECT vlan_id, name, discovery_source, last_discovered_at FROM vlans WHERE vlan_id = 10").fetchone()
    assert result["created"] == 1
    assert row[0] == 10
    assert row[1] == "VLAN 10"
    assert row[2] == "interface_svi"
    assert row[3]
    summary = list_vlans(conn)
    exported = export_vlans(conn)
    conn.close()
    assert summary[0]["svi_interfaces"] == "Vlanif10"
    assert summary[0]["description"] == "Finance gateway"
    assert summary[0]["port_count"] == 0
    assert summary[0]["port_details"] == ""
    assert exported[0]["VLAN ID"] == 10
    assert set(("站点", "设备名称", "设备IP", "网关", "网段", "接入接口", "ARP/MAC信息", "接口采集时间", "ARP采集时间", "MAC采集时间", "负责人")).issubset(exported[0])


def test_vlan_summary_exposes_endpoint_evidence_for_arp_and_mac(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, site_id, site) VALUES (?, ?, ?, ?, ?)",
        ("device-endpoint-1", "SW-endpoint", "online", "site-endpoint", "SITE-ENDPOINT"),
    )
    conn.execute(
        "INSERT INTO sites (id, site_code, site_name, status) VALUES (?, ?, ?, ?)",
        ("site-endpoint", "SITE-ENDPOINT", "SITE-ENDPOINT", "active"),
    )
    conn.execute(
        "INSERT INTO tenants (id, name, description) VALUES (?, ?, ?)",
        ("tenant-1", "Tenant 1", "VLAN endpoint evidence test"),
    )
    conn.execute(
        "INSERT INTO vlans (id, vlan_id, name, site_id, tenant_id) VALUES (?, ?, ?, ?, ?)",
        ("vlan-endpoint-1", 7, "VPC7-NETWORK", "site-endpoint", "tenant-1"),
    )
    conn.execute(
        """INSERT INTO arp_table
           (id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("arp-endpoint-1", "device-endpoint-1", "10.0.7.10", "005079666807", "Vlan7", 7, "2026-07-29T15:12:58+08:00"),
    )
    conn.execute(
        """INSERT INTO mac_table
           (id, device_id, mac_address, interface_name, vlan_id, last_updated)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("mac-endpoint-1", "device-endpoint-1", "005079666808", "Gi0/1", 7, "2026-07-29T15:12:59+08:00"),
    )
    conn.commit()

    summary = list_vlans(conn)
    conn.close()

    row = next(item for item in summary if item["vlan_id"] == 7)
    assert row["arp_count"] == 1
    assert row["mac_count"] == 1
    assert row["endpoint_last_seen_at"] == "2026-07-29T15:12:59+08:00"
    assert row["endpoint_details"] == [
        {
            "source": "arp",
            "ip_address": "10.0.7.10",
            "mac_address": "005079666807",
            "interface_name": "Vlan7",
            "device_hostname": "SW-endpoint",
            "device_ip": "",
            "last_updated": "2026-07-29T15:12:58+08:00",
        },
        {
            "source": "mac",
            "ip_address": "",
            "mac_address": "005079666808",
            "interface_name": "Gi0/1",
            "device_hostname": "SW-endpoint",
            "device_ip": "",
            "last_updated": "2026-07-29T15:12:59+08:00",
        },
    ]


def test_cisco_and_huawei_vlan_textfsm_records_project_members_to_interfaces(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, site_id, site) VALUES (?, ?, ?, ?, ?)",
        ("device-vlan-1", "SW5", "online", "", ""),
    )
    conn.commit()

    project_vlan_records("device-vlan-1", [{
        "vlan_id": "7",
        "vlan_name": "VPC7-NETWORK",
        "interfaces": ["Gi0/1"],
    }])
    project_vlan_records("device-vlan-1", [{
        "vlan_id": "10",
        "vlan_type": "common",
        "ports": "UT:GE0/0/1(U)      GE0/0/4(U)",
    }])

    rows = conn.execute(
        "SELECT interface_name, access_vlan, switchport_mode FROM interfaces WHERE device_id = ? ORDER BY interface_name",
        ("device-vlan-1",),
    ).fetchall()
    assert [(row["interface_name"], row["access_vlan"], row["switchport_mode"]) for row in rows] == [
        ("GE0/0/1", 10, "access"),
        ("GE0/0/4", 10, "access"),
        ("Gi0/1", 7, "access"),
    ]
    vlans = conn.execute("SELECT vlan_id, name FROM vlans WHERE COALESCE(site_id, '') = '' ORDER BY vlan_id").fetchall()
    assert [(row["vlan_id"], row["name"]) for row in vlans] == [(7, "VPC7-NETWORK"), (10, "VLAN 10")]
    conn.close()


def test_vlan_projection_updates_short_and_long_interface_aliases(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, site_id, site) VALUES (?, ?, ?, ?, ?)",
        ("device-vlan-alias", "SW-alias", "online", "", ""),
    )
    for interface_id, interface_name in (
        ("intf-ge", "GE0/0/4"),
        ("intf-gigabit", "GigabitEthernet0/0/4"),
    ):
        conn.execute(
            """INSERT INTO interfaces
               (id, device_id, interface_name, admin_status, oper_status, interface_type, switchport_mode)
               VALUES (?, ?, ?, 'up', 'up', 'physical', 'access')""",
            (interface_id, "device-vlan-alias", interface_name),
        )
    conn.commit()

    project_vlan_records("device-vlan-alias", [{
        "vlan_id": "20",
        "vlan_name": "USER-NET",
        "interfaces": ["GE0/0/4"],
    }])

    rows = conn.execute(
        "SELECT interface_name, access_vlan, admin_status, oper_status FROM interfaces WHERE device_id = ? ORDER BY interface_name",
        ("device-vlan-alias",),
    ).fetchall()
    assert [(row["interface_name"], row["access_vlan"], row["admin_status"], row["oper_status"]) for row in rows] == [
        ("GE0/0/4", 20, "up", "up"),
        ("GigabitEthernet0/0/4", 20, "up", "up"),
    ]
    conn.close()


def test_default_vlan_facts_are_not_projected_as_business_vlans(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, site_id, site, platform) VALUES (?, ?, ?, ?, ?, ?)",
        ("device-default-vlan", "SW-default", "online", "", "", "cisco_ios"),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, description, interface_type, switchport_mode,
            access_vlan, is_l3, last_seen)
           VALUES (?, ?, ?, '', 'physical', 'access', ?, 0, ?)""",
        ("intf-default-vlan", "device-default-vlan", "Gi0/1", 1, "2026-07-29T00:00:00+00:00"),
    )
    conn.commit()
    result = sync_observed_vlans()
    assert result["observed"] == 0
    assert conn.execute("SELECT COUNT(*) FROM vlans WHERE vlan_id = 1").fetchone()[0] == 0
    conn.close()


def test_vlan_business_binding_requires_a_vlan_in_the_same_site_scope(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO sites (id, site_code, site_name, status) VALUES (?, ?, ?, ?)",
        ("site-vlan-business", "WH", "WH Data Center", "active"),
    )
    conn.execute(
        "INSERT INTO vlans (id, vlan_id, name, site_id, tenant_id) VALUES (?, ?, ?, ?, ?)",
        ("vlan-site-10", 10, "APP-NET", "site-vlan-business", "tenant-default"),
    )
    conn.commit()

    with pytest.raises(ValueError, match="does not exist"):
        create_vlan_business_binding(
            conn,
            site_id="site-vlan-business",
            vrf_id="",
            vlan_id=20,
            business_system="Finance",
            department="财务部",
            owner="Alice",
        )

    binding = create_vlan_business_binding(
        conn,
        site_id="site-vlan-business",
        vrf_id="",
        vlan_id=10,
        business_system="Finance",
        department="财务部",
        owner="Alice",
    )
    assert binding["vlan_id"] == 10
    assert binding["site_id"] == "site-vlan-business"

    with pytest.raises(ValueError, match="does not exist"):
        update_vlan_business_binding(conn, binding["id"], vlan_id=20)
    conn.close()
