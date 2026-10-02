from __future__ import annotations

from backend.tests.pg_test_utils import postgresql_test_driver
from services import ipam_service


def _connection() -> postgresql_test_driver.Connection:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    conn.executescript(
        '''
        CREATE TABLE sites (
            id TEXT PRIMARY KEY,
            site_name TEXT,
            site_code TEXT
        );
        CREATE TABLE prefixes (
            id TEXT PRIMARY KEY,
            prefix TEXT NOT NULL,
            name TEXT,
            status TEXT,
            site_id TEXT,
            network_type TEXT
        );
        CREATE TABLE ip_addresses (
            id TEXT PRIMARY KEY,
            subnet_id TEXT NOT NULL,
            address TEXT NOT NULL,
            hostname TEXT,
            device_id TEXT DEFAULT '',
            mac_address TEXT,
            status TEXT,
            device_type TEXT,
            interface_name TEXT,
            created_at TEXT
        );
        CREATE TABLE devices (
            id TEXT PRIMARY KEY,
            hostname TEXT,
            site TEXT DEFAULT '',
            asset_id TEXT DEFAULT ''
        );
        CREATE TABLE physical_assets (
            id TEXT PRIMARY KEY,
            asset_tag TEXT DEFAULT '',
            serial_number TEXT DEFAULT '',
            hostname TEXT DEFAULT '',
            vendor TEXT DEFAULT '',
            model TEXT DEFAULT '',
            management_ip TEXT DEFAULT '',
            business_ip TEXT DEFAULT ''
        );
        CREATE TABLE network_endpoints (
            id TEXT PRIMARY KEY,
            ip TEXT,
            mac TEXT,
            hostname TEXT,
            vendor TEXT,
            switch_id TEXT,
            switch_port TEXT,
            vlan TEXT,
            vrf TEXT,
            site TEXT,
            last_seen TEXT,
            source_type TEXT,
            confidence TEXT,
            is_active INTEGER
        );

        INSERT INTO sites VALUES ('site-1', 'Shanghai DC', 'SHA');
        INSERT INTO prefixes VALUES
            ('prefix-capacity', '10.0.0.0/24', 'Users', 'active', 'site-1', 'user'),
            ('prefix-p2p', '10.0.1.0/31', 'Transit', 'active', 'site-1', 'transit'),
            ('prefix-host', '10.0.2.1/32', 'Loopback', 'active', 'site-1', 'loopback'),
            ('prefix-container', '10.0.0.0/16', 'Container', 'container', 'site-1', 'container');
        INSERT INTO ip_addresses (
            id, subnet_id, address, hostname, device_id, mac_address, status,
            device_type, interface_name, created_at
        ) VALUES
            ('ip-1', 'prefix-capacity', '10.0.0.10', 'host-1', '', 'aa:bb:cc:dd:ee:01', 'active', 'host', '', '2026-07-20T10:00:00+00:00'),
            ('ip-2', 'prefix-host', '10.0.2.1', 'loopback-1', '', '', 'active', 'loopback', 'Loopback0', '2026-07-21T10:00:00+00:00');

        INSERT INTO devices (id, hostname) VALUES ('device-1', 'access-sw-01');
        INSERT INTO network_endpoints VALUES (
            'endpoint-1', '10.0.0.20', 'aa:bb:cc:dd:ee:20', 'host-20', 'Example',
            'device-1', 'Gi1/0/20', '100', 'default', 'SHA',
            '2026-07-28T08:00:00+00:00', 'arp', '95%', 1
        );

        CREATE TABLE vrfs (id TEXT PRIMARY KEY, vrf_name TEXT, tenant_id TEXT);
        ALTER TABLE prefixes ADD COLUMN tenant_id TEXT DEFAULT 'tenant-default';
        ALTER TABLE prefixes ADD COLUMN vrf_id TEXT DEFAULT '';
        ALTER TABLE ip_addresses ADD COLUMN tenant_id TEXT DEFAULT 'tenant-default';
        ALTER TABLE ip_addresses ADD COLUMN vrf_id TEXT DEFAULT '';
        ALTER TABLE devices ADD COLUMN tenant_id TEXT DEFAULT 'tenant-default';
        ALTER TABLE devices ADD COLUMN site_id TEXT DEFAULT '';
        ALTER TABLE physical_assets ADD COLUMN site_id TEXT DEFAULT '';
        '''
    )
    return conn


def test_utilization_excludes_container_point_to_point_and_host_routes(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(ipam_service, 'get_db_connection', lambda: conn)

    data = ipam_service.get_utilization_analytics()

    assert data['overview']['total_ips'] == 254
    assert data['overview']['used_ips'] == 1
    assert data['overview']['capacity_prefixes_count'] == 1
    assert data['overview']['excluded_prefixes_count'] == 3
    assert [item['prefix'] for item in data['top_utilized_prefixes']] == ['10.0.0.0/24']
    assert data['forecast_trend'] == [{'day': '2026-07-20', 'allocated': 1}]
    exclusions = {
        item['prefix']: item['capacity_excluded_reason']
        for item in data['items']
        if not item['capacity_eligible']
    }
    assert exclusions == {
        '10.0.0.0/16': 'container_prefix',
        '10.0.1.0/31': 'point_to_point',
        '10.0.2.1/32': 'host_route',
    }


def test_reconciliation_returns_readable_switch_and_evidence(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(ipam_service, 'get_db_connection', lambda: conn)

    data = ipam_service.get_ipam_reconciliation()

    endpoint = data['undocumented_endpoints'][0]
    assert endpoint['switch_id'] == 'device-1'
    assert endpoint['switch_name'] == 'access-sw-01'
    assert endpoint['source_type'] == 'arp'
    assert endpoint['confidence'] == '95%'


def test_ip_inventory_merges_discovered_endpoints_by_site_and_prefix(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(ipam_service, 'get_db_connection', lambda: conn)

    data = ipam_service.list_ip_inventory(prefix_id='prefix-capacity')

    assert data['summary'] == {'total': 2, 'discovered': 1, 'manual': 1, 'prefixes': 4}
    assert {item['address'] for item in data['items']} == {'10.0.0.10', '10.0.0.20'}
    discovered = next(item for item in data['items'] if item['address'] == '10.0.0.20')
    assert discovered['is_discovered'] is True
    assert discovered['site_name'] == 'Shanghai DC'
    assert discovered['switch_name'] == 'access-sw-01'
    assert discovered['switch_port'] == 'Gi1/0/20'
    assert discovered['vlan'] == '100'
    assert data['sites'][0]['count'] == 4
    assert data['sites'][0]['ip_count'] == 2
