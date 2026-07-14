import sqlite3

import pytest

from services import cmdb_service
from services import ipam_service


def _conn(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _init_ipam_db(path):
    conn = _conn(path)
    conn.execute(
        """CREATE TABLE prefixes (
            id TEXT PRIMARY KEY,
            prefix TEXT NOT NULL,
            vrf_id TEXT,
            vlan_id TEXT,
            site_id TEXT,
            tenant_id TEXT,
            status TEXT,
            name TEXT,
            gateway TEXT,
            description TEXT,
            network_type TEXT,
            gateway_device_id TEXT,
            gateway_interface_id TEXT,
            traceable INTEGER,
            parent_prefix_id TEXT,
            prefix_cidr TEXT DEFAULT '',
            ip_version INTEGER DEFAULT 0,
            prefix_len INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE ip_addresses (
            id TEXT PRIMARY KEY,
            subnet_id TEXT NOT NULL,
            address TEXT NOT NULL,
            hostname TEXT DEFAULT '',
            device_id TEXT DEFAULT '',
            interface_name TEXT DEFAULT '',
            interface_id TEXT DEFAULT '',
            mac_address TEXT DEFAULT '',
            device_type TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            description TEXT DEFAULT '',
            last_seen TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            ip_address TEXT DEFAULT '',
            prefix_id TEXT DEFAULT '',
            vrf_id TEXT DEFAULT '',
            address_inet TEXT DEFAULT '',
            ip_version INTEGER DEFAULT 0
        )"""
    )
    conn.execute("CREATE UNIQUE INDEX idx_ip_addr_unique ON ip_addresses(subnet_id, address)")
    conn.commit()
    conn.close()


def _connect_ipam(path):
    conn = _conn(path)
    return conn


def test_ipam_rejects_sibling_overlap_but_allows_child(monkeypatch, tmp_path):
    db_path = str(tmp_path / "ipam.db")
    _init_ipam_db(db_path)
    monkeypatch.setattr(ipam_service, "get_db_connection", lambda: _connect_ipam(db_path))

    parent = ipam_service.create_subnet(prefix="10.0.0.0/24", tenant_id="t1", vrf_id="v1", site_id="s1")
    child = ipam_service.create_subnet(prefix="10.0.0.0/25", tenant_id="t1", vrf_id="v1", site_id="s1")

    assert parent["prefix"] == "10.0.0.0/24"
    assert parent["ip_version"] == 4
    assert parent["prefix_len"] == 24
    assert child["prefix"] == "10.0.0.0/25"
    with pytest.raises(ValueError, match="already exists"):
        ipam_service.create_subnet(prefix="10.0.0.0/24", tenant_id="t1", vrf_id="v1", site_id="s1")
    reused = ipam_service.create_subnet(prefix="10.0.0.0/24", tenant_id="t1", vrf_id="v2", site_id="s1")
    assert reused["prefix"] == "10.0.0.0/24"


def test_ipam_allocate_next_and_release_lifecycle(monkeypatch, tmp_path):
    db_path = str(tmp_path / "ipam.db")
    _init_ipam_db(db_path)
    monkeypatch.setattr(ipam_service, "get_db_connection", lambda: _connect_ipam(db_path))

    subnet = ipam_service.create_subnet(prefix="192.0.2.0/30", tenant_id="t1", vrf_id="v1", site_id="s1")
    first = ipam_service.allocate_next_address(subnet["id"], hostname="host-a", requested_by="tester")
    second = ipam_service.allocate_next_address(subnet["id"], hostname="host-b", requested_by="tester")

    assert first["address"] == "192.0.2.1"
    assert second["address"] == "192.0.2.2"

    assert ipam_service.release_address(first["id"], released_by="tester") is True
    check = _connect_ipam(db_path)
    row = check.execute("SELECT status, device_id, interface_id FROM ip_addresses WHERE id = ?", (first["id"],)).fetchone()
    assert row["status"] == "released"
    assert row["device_id"] == ""
    assert row["interface_id"] == ""
    check.close()


def test_cmdb_field_authority_quality_counts_issues():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for ddl in (
        "CREATE TABLE devices (id TEXT, site TEXT, site_id TEXT, asset_id TEXT, ip_address TEXT)",
        "CREATE TABLE sites (id TEXT, site_name TEXT, site_code TEXT)",
        "CREATE TABLE physical_assets (id TEXT, management_ip TEXT)",
        "CREATE TABLE interfaces (id TEXT, device_id TEXT, interface_name TEXT)",
        "CREATE TABLE ip_addresses (id TEXT, device_id TEXT, interface_name TEXT, interface_id TEXT)",
        "CREATE TABLE topology_links (source_port TEXT, source_interface_id TEXT, target_port TEXT, target_interface_id TEXT)",
    ):
        conn.execute(ddl)
    conn.execute("INSERT INTO devices VALUES ('d1', 'OldSite', '', 'missing-asset', '10.0.0.1')")
    conn.execute("INSERT INTO interfaces VALUES ('i1', 'd1', 'Gi0/1')")
    conn.execute("INSERT INTO ip_addresses VALUES ('ip1', 'd1', 'Gi0/1', '')")
    conn.execute("INSERT INTO topology_links VALUES ('Gi0/1', '', 'Gi0/2', '')")

    quality = cmdb_service.get_field_authority_quality(conn)

    assert quality["summary"]["devices"] == 1
    assert quality["issues"]["site_id_missing"] == 1
    assert quality["issues"]["asset_id_orphaned"] == 1
    assert quality["issues"]["ip_missing_interface_id"] == 1
    assert quality["issues"]["topology_missing_interface_id"] == 1
