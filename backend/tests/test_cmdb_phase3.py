import uuid
import pytest
from database import get_db_connection
from services.ipam_service import get_subnets_tree, rebuild_prefixes_hierarchy

def test_cmdb_phase3_tables_and_columns(isolated_db):
    conn = get_db_connection()
    try:
        # 1. Verify tables exist
        for table in ['tenants', 'roles', 'sites', 'racks', 'device_types', 'vrfs', 'vlans', 'prefixes', 'ip_addresses']:
            cursor = conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            assert cursor.fetchone() is not None, f"Table {table} must exist"

        # 2. Verify new columns exist on devices
        cursor = conn.execute("PRAGMA table_info(devices)")
        cols = {row['name'] for row in cursor.fetchall()}
        for col in ['tenant_id', 'site_id', 'rack_id', 'device_type_id', 'asset_tag', 'serial_number', 'os_version']:
            assert col in cols, f"Column {col} must exist on devices table"

        # 3. Verify new columns exist on ip_addresses
        cursor = conn.execute("PRAGMA table_info(ip_addresses)")
        cols = {row['name'] for row in cursor.fetchall()}
        for col in ['ip_address', 'prefix_id', 'vrf_id', 'interface_id']:
            assert col in cols, f"Column {col} must exist on ip_addresses table"
    finally:
        conn.close()

def test_cmdb_phase3_data_migration_and_hierarchy(isolated_db):
    conn = get_db_connection()
    try:
        # Clear ip_inventory, prefixes, ip_addresses
        conn.execute("DELETE FROM ip_inventory")
        conn.execute("DELETE FROM ip_addresses")
        conn.execute("DELETE FROM prefixes")
        conn.execute("DELETE FROM interfaces")
        conn.execute("DELETE FROM devices")

        # 1. Insert a device and an interface
        dev_id = "test-dev-1"
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, platform, status, site) VALUES (?, ?, ?, ?, ?, ?)",
            (dev_id, "router-1", "10.0.0.1", "cisco_ios", "online", "Beijing Datacenter")
        )
        intf_id = "intf-1"
        conn.execute(
            "INSERT INTO interfaces (id, device_id, interface_name, admin_status, oper_status) VALUES (?, ?, ?, ?, ?)",
            (intf_id, dev_id, "GigabitEthernet1", "up", "up")
        )

        # 2. Insert into ip_inventory
        conn.execute(
            "INSERT INTO ip_inventory (ip, mask, device_id, interface, type, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
            ("10.1.1.1", "255.255.255.0", dev_id, "GigabitEthernet1", "active", "2026-06-13T12:00:00")
        )
        conn.commit()
    finally:
        conn.close()

    # Re-run init_db/logic via schema init to trigger the data migration
    from database.schema import _init_db_logic
    conn = get_db_connection()
    try:
        _init_db_logic(conn)
        conn.commit()
        
        # 3. Verify site Beijing Datacenter was created and device linked
        site_row = conn.execute("SELECT id, site_code, site_name FROM sites WHERE site_name = 'Beijing Datacenter'").fetchone()
        assert site_row is not None
        assert site_row['site_code'] == 'SITE_BEIJING_DATACENTER'
        
        dev_row = conn.execute("SELECT site_id FROM devices WHERE id = ?", (dev_id,)).fetchone()
        assert dev_row['site_id'] == site_row['id']

        # 4. Verify ip_inventory migrated to prefixes and ip_addresses
        prefix_row = conn.execute("SELECT id, prefix FROM prefixes WHERE prefix = '10.1.1.0/24'").fetchone()
        assert prefix_row is not None
        
        ip_row = conn.execute("SELECT id, address, ip_address, prefix_id, device_id, interface_id FROM ip_addresses WHERE address = '10.1.1.1'").fetchone()
        assert ip_row is not None
        assert ip_row['ip_address'] == '10.1.1.1/24'
        assert ip_row['prefix_id'] == prefix_row['id']
        assert ip_row['device_id'] == dev_id
        assert ip_row['interface_id'] == intf_id

    finally:
        conn.close()

def test_ipam_prefix_parent_child_hierarchy(isolated_db):
    conn = get_db_connection()
    try:
        # Seed prefixes in prefixes table to test the get_subnets_tree() logic
        conn.execute("DELETE FROM prefixes")
        conn.execute("DELETE FROM ip_addresses")
        
        # 10.0.0.0/8 (parent)
        conn.execute(
            "INSERT INTO prefixes (id, prefix, name, status, tenant_id) VALUES (?, ?, ?, 'active', 'tenant-default')",
            ("sub-1", "10.0.0.0/8", "Corp WAN")
        )
        # 10.1.0.0/16 (child)
        conn.execute(
            "INSERT INTO prefixes (id, prefix, name, status, tenant_id) VALUES (?, ?, ?, 'active', 'tenant-default')",
            ("sub-2", "10.1.0.0/16", "Beijing Region")
        )
        # 10.1.1.0/24 (grandchild)
        conn.execute(
            "INSERT INTO prefixes (id, prefix, name, status, tenant_id) VALUES (?, ?, ?, 'active', 'tenant-default')",
            ("sub-3", "10.1.1.0/24", "Beijing Office")
        )
        # 192.168.1.0/24 (independent)
        conn.execute(
            "INSERT INTO prefixes (id, prefix, name, status, tenant_id) VALUES (?, ?, ?, 'active', 'tenant-default')",
            ("sub-4", "192.168.1.0/24", "Home Lab")
        )
        conn.commit()
    finally:
        conn.close()

    # Rebuild hierarchy since we manually inserted raw prefix records bypassing create_subnet
    rebuild_prefixes_hierarchy()

    # Get tree
    tree = get_subnets_tree()
    # Should contain 2 root elements: 10.0.0.0/8 and 192.168.1.0/24
    assert len(tree) == 2
    
    roots = {r['id']: r for r in tree}
    assert "sub-1" in roots
    assert "sub-4" in roots
    
    # Check children of 10.0.0.0/8
    sub1_children = roots["sub-1"]["children"]
    assert len(sub1_children) == 1
    assert sub1_children[0]["id"] == "sub-2"
    
    # Check children of 10.1.0.0/16 (child of 10.0.0.0/8)
    sub2_children = sub1_children[0]["children"]
    assert len(sub2_children) == 1
    assert sub2_children[0]["id"] == "sub-3"
    assert len(sub2_children[0]["children"]) == 0
