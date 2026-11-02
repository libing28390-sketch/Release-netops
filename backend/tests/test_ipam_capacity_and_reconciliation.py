from __future__ import annotations

from datetime import datetime, timezone

from backend.tests.pg_test_utils import postgresql_test_driver
from services import ipam_discovery_service, ipam_service


def _connection() -> postgresql_test_driver.Connection:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    endpoint_seen_at = datetime.now(timezone.utc).isoformat()
    conn.executescript(
        f'''
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
            network_type TEXT,
            gateway TEXT DEFAULT '',
            gateway_device_id TEXT DEFAULT '',
            gateway_interface_id TEXT DEFAULT ''
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
            interface_id TEXT,
            site_id TEXT,
            purpose TEXT,
            created_at TEXT
        );
        CREATE TABLE interfaces (
            id TEXT PRIMARY KEY,
            interface_type TEXT,
            interface_role TEXT
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
            '{endpoint_seen_at}', 'arp', '95%', 1
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


def _add_utilization_scope_prefixes(conn: postgresql_test_driver.Connection) -> None:
    conn.execute(
        '''INSERT INTO prefixes (id, prefix, name, status, site_id, network_type)
           VALUES
             ('prefix-server', '10.1.0.0/24', 'Servers', 'active', 'site-1', 'server'),
             ('prefix-transit30', '10.2.0.0/30', 'Router link', 'active', 'site-1', 'transit'),
             ('prefix-wan', '10.3.0.0/24', 'WAN', 'active', 'site-1', 'wan'),
             ('prefix-management', '10.4.0.0/24', 'Management', 'active', 'site-1', 'management'),
             ('prefix-service', '10.5.0.0/24', 'Network service', 'active', 'site-1', 'network_service'),
             ('prefix-unclassified', '10.6.0.0/24', 'Unclassified', 'active', 'site-1', 'unclassified'),
             ('prefix-legacy', '10.7.0.0/24', 'Legacy type', 'active', 'site-1', ''),
             ('prefix-container-network', '10.8.0.0/24', 'Container network', 'active', 'site-1', 'container')'''
    )
    conn.execute(
        '''INSERT INTO ip_addresses
           (id, subnet_id, address, status, created_at)
           VALUES
             ('ip-transit30', 'prefix-transit30', '10.2.0.1', 'active', '2026-07-22T10:00:00+00:00'),
             ('ip-server', 'prefix-server', '10.1.0.10', 'active', '2026-07-23T10:00:00+00:00'),
             ('ip-management', 'prefix-management', '10.4.0.10', 'active', '2026-07-24T10:00:00+00:00')'''
    )


def test_utilization_business_scope_uses_network_type_for_all_aggregates(monkeypatch):
    conn = _connection()
    _add_utilization_scope_prefixes(conn)
    monkeypatch.setattr(ipam_service, 'get_db_connection', lambda: conn)

    business = ipam_service.get_utilization_analytics(network_scope='business')

    assert business['network_scope'] == 'business'
    assert business['overview']['network_scope'] == 'business'
    assert business['overview']['prefixes_count'] == 4
    assert business['overview']['scope_excluded_prefixes_count'] == 8
    assert business['overview']['interconnect_prefixes_excluded_count'] == 3
    assert business['overview']['total_ips'] == 762
    assert business['overview']['used_ips'] == 2
    assert {item['prefix'] for item in business['items']} == {
        '10.0.0.0/24', '10.1.0.0/24', '10.8.0.0/24', '10.0.0.0/16',
    }
    assert all(
        item['network_type'] in ipam_service.BUSINESS_UTILIZATION_NETWORK_TYPES | {'user'}
        for item in business['items']
    )
    assert {item['prefix'] for item in business['top_utilized_prefixes']} == {
        '10.0.0.0/24', '10.1.0.0/24', '10.8.0.0/24',
    }
    assert {item['network_type'] for item in business['top_utilized_prefixes']} == {'user', 'server', 'container'}
    assert business['site_breakdown'] == [{
        'site': 'Shanghai DC', 'total_ips': 762, 'used_ips': 2,
        'utilization': round(2 / 762 * 100, 1),
    }]
    assert business['forecast_trend'] == [
        {'day': '2026-07-20', 'allocated': 1},
        {'day': '2026-07-23', 'allocated': 2},
    ]
    conn.close()

    all_conn = _connection()
    _add_utilization_scope_prefixes(all_conn)
    monkeypatch.setattr(ipam_service, 'get_db_connection', lambda: all_conn)
    all_prefixes = ipam_service.get_utilization_analytics(network_scope='all')
    assert all_prefixes['overview']['scope_excluded_prefixes_count'] == 0
    assert any(item['prefix'] == '10.2.0.0/30' for item in all_prefixes['top_utilized_prefixes'])
    assert all_prefixes['overview']['total_ips'] > business['overview']['total_ips']
    all_conn.close()


def test_reconciliation_delegates_to_independent_discovery_evidence(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(ipam_service, 'get_db_connection', lambda: conn)
    captured = {}
    expected = {
        'undocumented_endpoints': [{
            'observation_id': 'arp-observation', 'source_device_id': 'device-1',
            'source_device_name': 'access-sw-01', 'source_type': 'arp',
            'ip': '10.0.0.20', 'mac': 'aa:bb:cc:dd:ee:20',
        }],
        'stale_ip_addresses': [], 'mismatched_endpoints': [],
        'never_observed': [], 'unscoped': [], 'unavailable': [],
        'summary': {'coverage_status': 'partial'},
    }

    def build(conn_arg, **kwargs):
        captured['conn'] = conn_arg
        captured['kwargs'] = kwargs
        return expected

    monkeypatch.setattr(ipam_discovery_service, 'build_ipam_reconciliation', build)

    data = ipam_service.get_ipam_reconciliation()

    assert data == expected
    assert captured['conn'] is conn
    assert captured['kwargs']['active_tab'] == ''


def test_ip_inventory_merges_discovered_endpoints_by_site_and_prefix(monkeypatch):
    # This fixture isolates legacy endpoint inventory; CLI snapshots have separate integration coverage.
    monkeypatch.setattr(ipam_service, '_current_cmdb_interface_ip_observations', lambda _conn: [])
    conn = _connection()
    monkeypatch.setattr(ipam_service, 'get_db_connection', lambda: conn)

    data = ipam_service.list_ip_inventory(prefix_id='prefix-capacity')

    assert data['summary'] == {'total': 2, 'discovered': 1, 'manual': 1, 'gateways': 0, 'prefixes': 4, 'interface_observed': 0, 'interface_observed_networks': 0, 'interface_unmatched_prefix': 0, 'interface_vrf_review': 0, 'interface_global_default': 0, 'interface_matched': 0}
    assert {item['address'] for item in data['items']} == {'10.0.0.10', '10.0.0.20'}
    discovered = next(item for item in data['items'] if item['address'] == '10.0.0.20')
    assert discovered['is_discovered'] is True
    assert discovered['site_name'] == 'Shanghai DC'
    assert discovered['switch_name'] == 'access-sw-01'
    assert discovered['switch_port'] == 'Gi1/0/20'
    assert discovered['vlan'] == '100'
    assert data['sites'][0]['count'] == 4
    assert data['sites'][0]['ip_count'] == 2
