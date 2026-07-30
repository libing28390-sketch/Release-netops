import sqlite3

from services.cmdb_service import list_cmdb_devices


def test_cmdb_device_interface_count_uses_vendor_neutral_identity() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE devices (
            id TEXT PRIMARY KEY, hostname TEXT, ip_address TEXT, platform TEXT,
            status TEXT, role TEXT, site TEXT, vendor TEXT, lifecycle_status TEXT,
            asset_id TEXT, site_id TEXT, rack_id TEXT
        );
        CREATE TABLE physical_assets (
            id TEXT PRIMARY KEY, asset_tag TEXT, serial_number TEXT, site_id TEXT,
            rack TEXT, rack_unit TEXT, management_ip TEXT, business_ip TEXT,
            lifecycle_status TEXT
        );
        CREATE TABLE sites (
            id TEXT PRIMARY KEY, site_code TEXT, site_name TEXT, country TEXT,
            state_province TEXT, city TEXT, district TEXT
        );
        CREATE TABLE rack_devices (asset_id TEXT, rack_id TEXT);
        CREATE TABLE racks (
            id TEXT PRIMARY KEY, site_id TEXT, rack_code TEXT, rack_name TEXT,
            name TEXT, floor TEXT, room TEXT, row TEXT
        );
        CREATE TABLE interfaces (
            id TEXT PRIMARY KEY, device_id TEXT, interface_name TEXT
        );
        CREATE TABLE ip_addresses (device_id TEXT);
        CREATE TABLE topology_links (source_device_id TEXT, target_device_id TEXT);
        INSERT INTO devices VALUES
            ('dev-1', 'S6850-1', '10.254.0.1', 'hp_comware', 'online',
             'core', '', 'H3C', 'active', NULL, '', NULL);
        INSERT INTO interfaces VALUES
            ('i-1', 'dev-1', 'GE1/0/1'),
            ('i-2', 'dev-1', 'GigabitEthernet1/0/1'),
            ('i-3', 'dev-1', 'XGE1/0/49'),
            ('i-4', 'dev-1', 'Ten-GigabitEthernet1/0/49'),
            ('i-5', 'dev-1', 'Vlan7');
        """
    )

    rows = list_cmdb_devices(conn)

    assert len(rows) == 1
    assert rows[0]["interface_count"] == 3
