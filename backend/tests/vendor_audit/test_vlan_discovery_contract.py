from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
import pytest

from database.migrations.m0044_vlan_discovery_metadata import upgrade
from services.cmdb_service import (
    create_vlan_business_binding,
    export_vlans,
    get_vlan_details,
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
    conn = postgresql_test_driver.connect()
    conn.execute("CREATE TABLE vlans (id TEXT PRIMARY KEY, vlan_id INTEGER, name TEXT)")
    upgrade(conn.cursor(), True)
    upgrade(conn.cursor(), True)
    columns = pg_catalog.table_columns(conn, "vlans")
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
        ("intf-svi-10", "device-svi-1", "Vlanif10", "Finance gateway", "svi", "routed", "10.0.10.1", "10.0.10.1", True, "2026-07-29T00:00:00+00:00"),
    )
    conn.commit()
    result = sync_observed_vlans()
    row = conn.execute("SELECT vlan_id, name, discovery_source, last_discovered_at FROM vlans WHERE vlan_id = 10").fetchone()
    assert result["created"] == 1
    assert row[0] == 10
    assert row[1] == "VLAN 10"
    assert row[2] == "interface_svi"
    assert row[3] == "2026-07-29T00:00:00+00:00"
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


def test_device_scoped_vlan_keeps_unassigned_separate_and_retains_endpoint_only_device(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO sites (id, site_code, site_name, status) VALUES (?, ?, ?, ?)",
        ("site-vlan-scope", "VLAN-SCOPE", "VLAN Scope", "active"),
    )
    conn.execute(
        "INSERT INTO devices (id, hostname, ip_address, status, site_id) VALUES (?, ?, ?, ?, ?)",
        ("device-vlan-other-site", "SW-other-site", "192.0.2.70", "online", "site-vlan-scope"),
    )
    conn.execute(
        "INSERT INTO vlans (id, vlan_id, name, site_id, tenant_id) VALUES (?, ?, ?, ?, ?)",
        ("vlan-unassigned-70", 70, "Unassigned 70", None, "tenant-default"),
    )
    conn.execute(
        "INSERT INTO vlans (id, vlan_id, name, site_id, tenant_id) VALUES (?, ?, ?, ?, ?)",
        ("vlan-site-71", 71, "Endpoint only 71", "site-vlan-scope", "tenant-default"),
    )
    conn.execute(
        """INSERT INTO arp_table
           (id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("arp-other-site-vlan-70", "device-vlan-other-site", "192.0.2.70", "005079666870", "GE1/0/1", 70, "2026-10-27T01:00:00+00:00"),
    )
    conn.execute(
        """INSERT INTO mac_table
           (id, device_id, mac_address, interface_name, vlan_id, last_updated)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("mac-endpoint-only-vlan-71", "device-vlan-other-site", "005079666871", "GE1/0/2", 71, "2026-10-27T01:00:01+00:00"),
    )
    conn.commit()

    result = list_vlans(conn, device_scoped=True, page=1, page_size=100)
    conn.close()
    unassigned = next(row for row in result["items"] if row["vlan_id"] == 70)
    endpoint_only = next(row for row in result["items"] if row["vlan_id"] == 71)
    assert unassigned["device_count"] == 0
    assert unassigned["arp_count"] == 0
    assert endpoint_only["device_hostname"] == "SW-other-site"
    assert endpoint_only["device_ip"] == "192.0.2.70"
    assert endpoint_only["port_count"] == 0
    assert endpoint_only["mac_count"] == 1


def test_vlan_list_omits_full_details_and_details_lookup_is_device_scoped(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO sites (id, site_code, site_name, status) VALUES (?, ?, ?, ?)",
        ("site-vlan-details", "VLAN-DETAILS", "VLAN Details", "active"),
    )
    conn.execute(
        "INSERT INTO vlans (id, vlan_id, name, site_id, tenant_id) VALUES (?, ?, ?, ?, ?)",
        ("vlan-details-70", 70, "Details 70", "site-vlan-details", "tenant-default"),
    )
    for device_id, hostname, interface_id, interface_name, ip_address, mac_address in (
        ("device-details-a", "SW-details-a", "interface-details-a", "Gi0/1", "192.0.2.70", "005079000070"),
        ("device-details-b", "SW-details-b", "interface-details-b", "Gi0/2", "192.0.2.71", "005079000071"),
    ):
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, status, site_id) VALUES (?, ?, ?, ?, ?)",
            (device_id, hostname, "192.0.2.1", "online", "site-vlan-details"),
        )
        conn.execute(
            """INSERT INTO interfaces
               (id, device_id, interface_name, description, access_vlan, last_seen)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (interface_id, device_id, interface_name, f"port {hostname}", 70, "2026-10-27T00:00:00+00:00"),
        )
        conn.execute(
            """INSERT INTO arp_table
               (id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (f"arp-{device_id}", device_id, ip_address, mac_address, interface_name, 70, "2026-10-27T00:00:01+00:00"),
        )
        conn.execute(
            """INSERT INTO mac_table
               (id, device_id, mac_address, interface_name, vlan_id, last_updated)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (f"mac-{device_id}", device_id, mac_address, interface_name, 70, "2026-10-27T00:00:02+00:00"),
        )
    conn.execute(
        "INSERT INTO devices (id, hostname, status, site_id) VALUES (?, ?, ?, ?)",
        ("device-details-other-site", "SW-other", "online", "site-other"),
    )
    conn.commit()

    result = list_vlans(
        conn,
        device_scoped=True,
        page=1,
        page_size=20,
        include_details=False,
    )
    row = next(
        item for item in result["items"]
        if item["id"] == "vlan-details-70" and item.get("device_id") == "device-details-a"
    )
    assert row["port_count"] == 1
    assert row["arp_count"] == 1
    assert row["mac_count"] == 1
    assert "port_detail_rows" not in row
    assert "endpoint_details" not in row
    assert "port_details" not in row

    details = get_vlan_details(
        conn,
        "vlan-details-70",
        site_id="site-vlan-details",
        device_id="device-details-a",
    )
    assert [item["interface_name"] for item in details["port_detail_rows"]] == ["Gi0/1"]
    assert [item["ip_address"] for item in details["endpoint_details"] if item["source"] == "arp"] == ["192.0.2.70"]
    assert [item["mac_address"] for item in details["endpoint_details"] if item["source"] == "mac"] == ["005079000070"]
    assert details["meta"]["arp_count"] == 1
    assert details["meta"]["mac_count"] == 1

    with pytest.raises(ValueError, match="requested scope"):
        get_vlan_details(
            conn,
            "vlan-details-70",
            site_id="site-vlan-details",
            device_id="device-details-other-site",
        )
    conn.close()


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
           VALUES (?, ?, ?, '', 'physical', 'access', ?, False, ?)""",
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


def test_vlan_svi_gateway_deduction_with_cidr_and_mask_fallback(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, ip_address, status, site_id, site) VALUES (?, ?, ?, ?, ?, ?)",
        ("dev-s6850-1", "S6850-1", "10.254.0.1", "online", "site-1", "SITE-1"),
    )
    conn.execute(
        "INSERT INTO sites (id, site_code, site_name, status) VALUES (?, ?, ?, ?)",
        ("site-1", "SITE-1", "SITE-1", "active"),
    )
    conn.execute(
        "INSERT INTO vlans (id, vlan_id, name, site_id) VALUES (?, ?, ?, ?)",
        ("vlan-100", 100, "FIREWALL-INSIDE", "site-1"),
    )
    conn.execute(
        "INSERT INTO vlans (id, vlan_id, name, site_id) VALUES (?, ?, ?, ?)",
        ("vlan-112", 112, "OSPF-TO-S6850-2", "site-1"),
    )
    # SVI 100: primary_ip without prefix length in interfaces, but with CIDR in raw string
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, description, interface_type, switchport_mode,
            primary_ip, ip_address, ip_prefix_length, is_l3, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("intf-vlan-100", "dev-s6850-1", "Vlan-interface100", "FIREWALL-INSIDE", "svi", "l3", "10.254.100.4", "10.254.100.4", None, True, "2026-08-28T15:00:00+08:00"),
    )
    # SVI 112: primary_ip with CIDR slash directly
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, description, interface_type, switchport_mode,
            primary_ip, ip_address, ip_prefix_length, is_l3, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("intf-vlan-112", "dev-s6850-1", "Vlan-interface112", "OSPF-TO-S6850-2", "svi", "l3", "10.254.12.1/30", "10.254.12.1/30", 30, True, "2026-08-28T15:00:00+08:00"),
    )
    # Provide inventory mask for Vlan-interface100
    conn.execute(
        """INSERT INTO ip_inventory (device_id, ip, mask, interface, type, last_seen)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("dev-s6850-1", "10.254.100.4", "255.255.255.248", "Vlan-interface100", "interface", "2026-08-28T15:00:00+08:00"),
    )
    conn.commit()

    result = list_vlans(conn, device_scoped=True, page=1, page_size=20)
    lightweight_result = list_vlans(
        conn,
        device_scoped=True,
        page=1,
        page_size=20,
        include_details=False,
    )
    items = result["items"] if isinstance(result, dict) else result
    lightweight_items = lightweight_result["items"] if isinstance(lightweight_result, dict) else lightweight_result
    conn.close()

    vlan_100_item = next(item for item in items if item["vlan_id"] == 100)
    assert vlan_100_item["gateway"] == "10.254.100.4"
    assert vlan_100_item["gateway_device"] == "S6850-1"
    assert vlan_100_item["gateway_interface"] == "Vlan-interface100"
    assert "10.254.100.0/29" in vlan_100_item["prefixes"]

    lightweight_vlan_100 = next(item for item in lightweight_items if item["vlan_id"] == 100)
    assert "10.254.100.0/29" in lightweight_vlan_100["prefixes"]
    assert "port_detail_rows" not in lightweight_vlan_100
    assert "endpoint_details" not in lightweight_vlan_100

    vlan_112_item = next(item for item in items if item["vlan_id"] == 112)
    assert vlan_112_item["gateway"] == "10.254.12.1"
    assert vlan_112_item["gateway_device"] == "S6850-1"
    assert "10.254.12.0/30" in vlan_112_item["prefixes"]


def test_paginated_vlan_candidates_match_full_rows_and_keep_scope_aggregates(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO sites (id, site_code, site_name, status) VALUES (?, ?, ?, ?)",
        ("site-vlan-page", "VLAN-PAGE", "VLAN Page", "active"),
    )
    conn.execute(
        """INSERT INTO physical_assets
           (id, asset_type, site_id, device_category, device_role, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("asset-vlan-page-server", "server", "site-vlan-page", "server", "database", "2026-10-27", "2026-10-27"),
    )
    for device_id, hostname, device_ip, asset_id in (
        ("device-vlan-page-a", "SW-page-a", "192.0.2.81", None),
        ("device-vlan-page-b", "SW-page-b", "192.0.2.82", "asset-vlan-page-server"),
        ("device-vlan-page-arp", "SW-page-arp", "192.0.2.83", None),
        ("device-vlan-page-mac", "SW-page-mac", "192.0.2.84", None),
    ):
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, status, site_id, asset_id)
               VALUES (?, ?, ?, 'online', ?, ?)""",
            (device_id, hostname, device_ip, "site-vlan-page", asset_id),
        )
    for vlan_id, name in ((10, "Page VLAN 10"), (20, "Page VLAN 20"), (30, "No evidence VLAN")):
        conn.execute(
            "INSERT INTO vlans (id, vlan_id, name, site_id, tenant_id) VALUES (?, ?, ?, ?, ?)",
            (f"vlan-page-{vlan_id}", vlan_id, name, "site-vlan-page", "tenant-default"),
        )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, description, interface_type,
            primary_ip, ip_address, ip_prefix_length, access_vlan, allowed_vlans, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("interface-vlan-page-svi", "device-vlan-page-a", "Vlan-interface10", "Page gateway", "svi",
         "10.20.10.1", "10.20.10.1", None, None, None, "2026-10-27T00:00:00+00:00"),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, description, interface_type, access_vlan, allowed_vlans, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("interface-vlan-page-a", "device-vlan-page-a", "GE0/0/1", "A trunk", "physical", 10, "20", "2026-10-27T00:00:01+00:00"),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, description, interface_type, native_vlan, allowed_vlans, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("interface-vlan-page-b", "device-vlan-page-b", "GE0/0/2", "B trunk", "physical", 10, "20-21", "2026-10-27T00:00:02+00:00"),
    )
    conn.execute(
        """INSERT INTO ip_inventory (device_id, ip, mask, interface, type, last_seen)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("device-vlan-page-a", "10.20.10.1", "255.255.255.0", "Vlan-interface10", "interface", "2026-10-27T00:00:00+00:00"),
    )
    conn.execute(
        """INSERT INTO prefixes (id, prefix, prefix_cidr, vlan_id, gateway, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("prefix-vlan-page-no-evidence", "192.0.2.0/24", "192.0.2.0/24", "vlan-page-30", "192.0.2.254", "active"),
    )
    conn.execute(
        """INSERT INTO arp_table
           (id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("arp-vlan-page-a", "device-vlan-page-a", "10.20.10.11", "005079000010", "GE0/0/1", 10, "2026-10-27T00:00:03+00:00"),
    )
    conn.execute(
        """INSERT INTO arp_table
           (id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("arp-vlan-page-only", "device-vlan-page-arp", "10.20.10.12", "005079000011", "GE0/0/3", 10, "2026-10-27T00:00:04+00:00"),
    )
    conn.execute(
        """INSERT INTO mac_table
           (id, device_id, mac_address, interface_name, vlan_id, last_updated)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("mac-vlan-page-only", "device-vlan-page-mac", "005079000020", "GE0/0/4", 20, "2026-10-27T00:00:05+00:00"),
    )
    conn.commit()

    full = list_vlans(conn, device_scoped=True, include_details=False)
    first = list_vlans(conn, device_scoped=True, page=1, page_size=2, include_details=False)
    pages = [first]
    for page_number in range(2, (first["total"] + first["page_size"] - 1) // first["page_size"] + 1):
        pages.append(list_vlans(conn, device_scoped=True, page=page_number, page_size=2, include_details=False))
    paged_items = [item for page_result in pages for item in page_result["items"]]
    assert paged_items == full
    assert all(page_result["summary"] == first["summary"] for page_result in pages)
    assert all(page_result["site_summary"] == first["site_summary"] for page_result in pages)
    assert all(page_result["tree"] == first["tree"] for page_result in pages)
    assert first["summary"] == {"total": 3, "gateways": 2, "arp": 2, "mac": 1, "unbound": 7}

    svi_row = next(item for item in full if item.get("device_id") == "device-vlan-page-a" and item["vlan_id"] == 10)
    assert svi_row["prefixes"] == "10.20.10.0/24"
    assert svi_row["port_count"] == 1
    assert svi_row["svi_count"] == 1
    assert any(item.get("device_id") == "device-vlan-page-arp" for item in full)
    assert any(item.get("device_id") == "device-vlan-page-mac" for item in full)
    no_evidence = next(item for item in full if item["vlan_id"] == 30)
    assert no_evidence.get("device_id") is None
    assert no_evidence["gateway"] == "192.0.2.254"
    assert no_evidence["gateway_device"] is None
    assert no_evidence["gateway_interface"] is None

    server_page = list_vlans(
        conn, device_scoped=True, page=1, page_size=2, asset_type="server", include_details=False
    )
    assert all(item["asset_type"] == "server" for item in server_page["items"])
    assert server_page["total"] == 2
    assert server_page["summary"]["total"] == 2
    assert server_page["tree"] == first["tree"]
    assert server_page["site_summary"][0]["count"] == 2

    full_with_details = list_vlans(conn, device_scoped=True, include_details=True)
    class TrackingConnection:
        def __init__(self, inner):
            self.inner = inner
            self.wide_interface_queries = []

        def execute(self, sql, params=()):
            normalized_sql = " ".join(str(sql).lower().split())
            if "i.ip_prefix_length" in normalized_sql:
                self.wide_interface_queries.append((normalized_sql, tuple(params)))
            return self.inner.execute(sql, params)

    tracked_conn = TrackingConnection(conn)
    detail_page = list_vlans(tracked_conn, device_scoped=True, page=2, page_size=1, include_details=True)
    assert detail_page["items"] == [full_with_details[1]]
    assert [item["device_hostname"] for item in detail_page["items"][0]["endpoint_details"]] == ["SW-page-a"]
    assert all(row["device_id"] == "device-vlan-page-a" for row in detail_page["items"][0]["port_detail_rows"])
    assert detail_page["summary"] == first["summary"]
    assert detail_page["tree"] == first["tree"]
    assert len(tracked_conn.wide_interface_queries) == 1
    wide_sql, wide_params = tracked_conn.wide_interface_queries[0]
    assert "where i.id in" in wide_sql
    assert set(wide_params) == {"interface-vlan-page-a", "interface-vlan-page-svi"}

    conn.close()

