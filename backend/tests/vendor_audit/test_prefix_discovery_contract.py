from services.prefix_discovery_service import build_prefix_candidates
import json
import sqlite3

import services.prefix_discovery_service as prefix_service
from services.read_only_collection_adapter import READ_ONLY_EVIDENCE_CATEGORIES


def test_read_only_evidence_categories_are_explicit_and_vendor_neutral() -> None:
    assert READ_ONLY_EVIDENCE_CATEGORIES == (
        'interfaces', 'interface_description', 'vlan', 'routing_table', 'neighbors', 'arp', 'mac_table'
    )


def test_empty_discovery_prefix_binds_to_higher_level_svi_gateway() -> None:
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE prefixes (
            id TEXT PRIMARY KEY, gateway TEXT, gateway_device_id TEXT,
            gateway_interface_id TEXT, manual_override INTEGER, source_type TEXT,
            updated_at TEXT
        );
        CREATE TABLE devices (id TEXT PRIMARY KEY, hostname TEXT, role TEXT);
        CREATE TABLE interfaces (
            id TEXT PRIMARY KEY, device_id TEXT, interface_name TEXT,
            primary_ip TEXT, ip_address TEXT, ip_prefix_length INTEGER,
            interface_type TEXT, is_l3 INTEGER
        );
    ''')
    conn.execute("INSERT INTO prefixes VALUES (?, ?, ?, ?, ?, ?, ?)", ('prefix-1', '', '', '', 0, 'discovery', ''))
    conn.executemany(
        "INSERT INTO devices VALUES (?, ?, ?)",
        [('lsw5', 'LSW5', 'distribution'), ('lsw7', 'LSW7', 'access')],
    )
    conn.executemany(
        "INSERT INTO interfaces VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ('if-lsw5', 'lsw5', 'Vlanif20', '10.253.20.1', '10.253.20.1', 24, 'svi', 1),
            ('if-lsw7', 'lsw7', 'Vlanif20', '10.253.20.2', '10.253.20.2', 24, 'svi', 1),
        ],
    )
    candidate = {
        'prefix': '10.253.20.0/24',
        'observed_devices': ['lsw5', 'lsw7'],
        'observed_interfaces': ['Vlanif20'],
    }

    assert prefix_service._bind_discovered_gateway(conn, 'prefix-1', candidate, 'now') is True
    row = conn.execute(
        'SELECT gateway, gateway_device_id, gateway_interface_id FROM prefixes WHERE id = ?',
        ('prefix-1',),
    ).fetchone()
    assert dict(row) == {
        'gateway': '10.253.20.1',
        'gateway_device_id': 'lsw5',
        'gateway_interface_id': 'if-lsw5',
    }


def test_prefix_discovery_does_not_default_unproven_networks_to_server() -> None:
    payload = {
        'device': {'id': 'dev-1', 'hostname': 'access-01'},
        'categories': [
            {'key': 'interfaces', 'records': [
                {'INTERFACE': 'Vlan100', 'IP_ADDRESS': '192.0.2.1/24'},
            ]},
        ],
    }
    candidates = build_prefix_candidates(payload, site_id='site-a')
    assert candidates[0]['prefix'] == '192.0.2.0/24'
    assert candidates[0]['network_type'] == 'user_access'


def test_point_to_point_prefix_requires_neighbor_evidence_for_transit() -> None:
    payload = {
        'device': {'id': 'dev-1', 'hostname': 'core-01'},
        'categories': [
            {'key': 'interfaces', 'records': [
                {'INTERFACE': 'GigabitEthernet1/0/1', 'IP_ADDRESS': '198.51.100.1/30'},
            ]},
            {'key': 'neighbors', 'records': [
                {'LOCAL_INTERFACE': 'GigabitEthernet1/0/1', 'NEIGHBOR_NAME': 'core-02'},
            ]},
        ],
    }
    candidates = build_prefix_candidates(payload, site_id='site-a')
    assert candidates[0]['network_type'] == 'transit'


def test_mixed_interface_roles_are_flagged_without_promoting_confidence() -> None:
    payload = {
        'device': {'id': 'dev-1', 'hostname': 'edge-01'},
        'categories': [{'key': 'interfaces', 'records': [
            {'INTERFACE': 'Vlan100', 'IP_ADDRESS': '192.0.2.1/24'},
            {'INTERFACE': 'Management0', 'IP_ADDRESS': '192.0.2.2/24'},
        ]}],
    }
    candidate = build_prefix_candidates(payload)[0]
    assert candidate['mixed_network'] == 1
    assert candidate['confidence'] <= 0.65


def test_loopback_is_strongly_classified() -> None:
    payload = {
        'device': {'id': 'dev-1', 'hostname': 'router-01'},
        'categories': [{'key': 'interfaces', 'records': [
            {'INTERFACE': 'Loopback0', 'IP_ADDRESS': '203.0.113.10/32'},
        ]}],
    }
    candidates = build_prefix_candidates(payload)
    assert candidates[0]['network_type'] == 'loopback'


def test_loopback_without_mask_is_inferred_as_host_prefix() -> None:
    payload = {
        'device': {'id': 'dev-1', 'hostname': 'core-sw-01'},
        'categories': [{'key': 'interfaces', 'records': [
            {'INTERFACE': 'Loopback0', 'IP_ADDRESS': '1.1.1.1'},
        ]}],
    }
    candidates = build_prefix_candidates(payload)
    assert candidates[0]['prefix'] == '1.1.1.1/32'
    assert candidates[0]['network_type'] == 'loopback'
    assert candidates[0]['evidence'][0]['source_type'] == 'interface_loopback_host'


def test_interface_snapshot_bridge_upserts_loopback_prefix(monkeypatch) -> None:
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE devices (
            id TEXT PRIMARY KEY, hostname TEXT, ip_address TEXT, platform TEXT,
            site_id TEXT, tenant_id TEXT
        );
        CREATE TABLE interfaces (
            device_id TEXT, interface_name TEXT, primary_ip TEXT, ip_address TEXT,
            ip_prefix_length INTEGER, vrf_id TEXT
        );
        CREATE TABLE ip_inventory (
            device_id TEXT, interface TEXT, ip TEXT, mask TEXT, last_seen TEXT
        );
    ''')
    conn.execute(
        "INSERT INTO devices VALUES (?, ?, ?, ?, ?, ?)",
        ('dev-1', 'core-sw-01', '192.168.18.201', 'cisco_ios', 'site-a', 'tenant-default'),
    )
    conn.execute(
        "INSERT INTO interfaces VALUES (?, ?, ?, ?, ?, ?)",
        ('dev-1', 'Loopback0', '1.1.1.1', '1.1.1.1', None, ''),
    )

    class NonClosingConnection:
        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            return None

    captured: list[dict] = []
    monkeypatch.setattr(prefix_service, 'get_db_connection', lambda: NonClosingConnection())
    monkeypatch.setattr(
        prefix_service,
        'persist_prefix_candidates',
        lambda candidates, collection_run_id=None: captured.extend(candidates) or {
            'created': len(candidates), 'updated': 0,
        },
    )

    result = prefix_service.discover_prefixes_from_interface_snapshot('dev-1', collection_run_id='run-1')
    assert result['created'] == 1
    assert captured[0]['prefix'] == '1.1.1.1/32'
    assert captured[0]['network_type'] == 'loopback'


def test_interface_snapshot_bridge_falls_back_to_ip_inventory(monkeypatch) -> None:
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE devices (
            id TEXT PRIMARY KEY, hostname TEXT, ip_address TEXT, platform TEXT,
            site_id TEXT, tenant_id TEXT
        );
        CREATE TABLE interfaces (
            device_id TEXT, interface_name TEXT, primary_ip TEXT, ip_address TEXT,
            ip_prefix_length INTEGER, vrf_id TEXT
        );
        CREATE TABLE ip_inventory (
            device_id TEXT, interface TEXT, ip TEXT, mask TEXT, last_seen TEXT
        );
    ''')
    conn.execute(
        "INSERT INTO devices VALUES (?, ?, ?, ?, ?, ?)",
        ('dev-1', 'core-sw-01', '192.168.18.201', 'cisco_ios', 'site-a', 'tenant-default'),
    )
    conn.execute(
        "INSERT INTO ip_inventory VALUES (?, ?, ?, ?, ?)",
        ('dev-1', 'Loopback0', '1.1.1.1', '255.255.255.255', 'now'),
    )

    class NonClosingConnection:
        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            return None

    captured: list[dict] = []
    monkeypatch.setattr(prefix_service, 'get_db_connection', lambda: NonClosingConnection())
    monkeypatch.setattr(
        prefix_service,
        'persist_prefix_candidates',
        lambda candidates, collection_run_id=None: captured.extend(candidates) or {
            'created': len(candidates), 'updated': 0,
        },
    )

    result = prefix_service.discover_prefixes_from_interface_snapshot('dev-1', collection_run_id='run-2')
    assert result['created'] == 1
    assert captured[0]['prefix'] == '1.1.1.1/32'
    assert captured[0]['network_type'] == 'loopback'


def test_interface_snapshot_matches_h3c_svi_alias_and_dotted_mask(monkeypatch) -> None:
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE devices (
            id TEXT PRIMARY KEY, hostname TEXT, ip_address TEXT, platform TEXT,
            site_id TEXT, tenant_id TEXT
        );
        CREATE TABLE interfaces (
            device_id TEXT, interface_name TEXT, primary_ip TEXT, ip_address TEXT,
            ip_prefix_length INTEGER, vrf_id TEXT
        );
        CREATE TABLE ip_inventory (
            device_id TEXT, interface TEXT, ip TEXT, mask TEXT, last_seen TEXT
        );
    ''')
    conn.execute(
        "INSERT INTO devices VALUES (?, ?, ?, ?, ?, ?)",
        ('dev-h3c', 'S6850-6', '10.254.0.6', 'hp_comware', 'site-a', 'tenant-default'),
    )
    conn.execute(
        "INSERT INTO interfaces VALUES (?, ?, ?, ?, ?, ?)",
        ('dev-h3c', 'Vlan8', '172.16.6.1', '172.16.6.1', None, ''),
    )
    conn.execute(
        "INSERT INTO ip_inventory VALUES (?, ?, ?, ?, ?)",
        ('dev-h3c', 'Vlan-interface8', '172.16.6.1', '255.255.255.0', 'now'),
    )

    class NonClosingConnection:
        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            return None

    captured: list[dict] = []
    monkeypatch.setattr(prefix_service, 'get_db_connection', lambda: NonClosingConnection())
    monkeypatch.setattr(
        prefix_service,
        'persist_prefix_candidates',
        lambda candidates, collection_run_id=None: captured.extend(candidates) or {
            'created': len(candidates), 'updated': 0,
        },
    )

    result = prefix_service.discover_prefixes_from_interface_snapshot('dev-h3c', collection_run_id='run-h3c')
    assert result['created'] == 1
    assert captured[0]['prefix'] == '172.16.6.0/24'


def test_prefix_classification_summary_returns_sql_row(monkeypatch) -> None:
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('''
        CREATE TABLE prefixes (
            classification_status TEXT, manual_override INTEGER, source_type TEXT,
            network_type TEXT, mixed_network INTEGER, conflict_status TEXT,
            is_active INTEGER, status TEXT
        )
    ''')
    conn.execute(
        "INSERT INTO prefixes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ('auto', 0, 'interface_collection', 'loopback', 0, '', 1, 'active'),
    )

    class NonClosingConnection:
        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            return None

    monkeypatch.setattr(prefix_service, 'get_db_connection', lambda: NonClosingConnection())
    summary = prefix_service.get_prefix_classification_summary()
    assert summary['total'] == 1
    assert summary['auto_count'] == 1
    assert summary['unclassified_count'] == 0


def test_arp_and_mac_evidence_enrich_existing_interface_prefix() -> None:
    payload = {
        'device': {'id': 'dev-1', 'hostname': 'access-01'},
        'categories': [
            {'key': 'interfaces', 'records': [
                {'INTERFACE': 'Vlan100', 'IP_ADDRESS': '192.0.2.1/24'},
            ]},
            {'key': 'arp', 'records': [
                {'IP_ADDRESS': '192.0.2.20', 'MAC_ADDRESS': '0011.2233.4455', 'INTERFACE': 'Ethernet1'},
            ]},
            {'key': 'mac_table', 'records': [
                {'VLAN': '100', 'MAC_ADDRESS': '0011.2233.4455', 'INTERFACE': 'Ethernet1'},
            ]},
        ],
    }
    candidate = build_prefix_candidates(payload)[0]
    assert candidate['observed_vlans'] == ['100']
    assert {item['source_type'] for item in candidate['evidence']} == {'interface', 'arp', 'mac_table'}


def test_persist_is_idempotent_and_does_not_default_to_server(monkeypatch) -> None:
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE prefixes (
            id TEXT PRIMARY KEY, prefix TEXT, prefix_cidr TEXT, vrf_id TEXT, site_id TEXT, tenant_id TEXT,
            status TEXT, name TEXT, network_type TEXT, traceable INTEGER, source_type TEXT,
            source_ref TEXT, confidence REAL, last_observed_at TEXT,
            classification_status TEXT, classification_source TEXT, classification_confidence REAL,
            classification_rule_version TEXT, manual_override INTEGER, mixed_network INTEGER,
            address_roles_json TEXT,
            discovered_devices_json TEXT, observed_interfaces_json TEXT, observed_vlans_json TEXT,
            observed_vrfs_json TEXT, evidence_json TEXT, candidate_scores_json TEXT,
            first_seen_at TEXT, last_seen_at TEXT, miss_count INTEGER, is_active INTEGER,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE prefix_observations (
            id TEXT PRIMARY KEY, prefix_id TEXT, collection_run_id TEXT, source_device_id TEXT,
            source_type TEXT, observed_value TEXT, evidence_json TEXT, confidence REAL,
            first_seen_at TEXT, last_seen_at TEXT, miss_count INTEGER, is_active INTEGER
        );
        CREATE UNIQUE INDEX uq_prefix_observation_identity
            ON prefix_observations(prefix_id, source_device_id, source_type, observed_value);
    ''')
    class NonClosingConnection:
        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            return None

    wrapped = NonClosingConnection()
    monkeypatch.setattr(prefix_service, 'get_db_connection', lambda: wrapped)
    candidate = build_prefix_candidates({
        'device': {'id': 'dev-1', 'hostname': 'access-01'},
        'categories': [{'key': 'interfaces', 'records': [
            {'INTERFACE': 'Ethernet1', 'IP_ADDRESS': '192.0.2.1/24'},
        ]}],
    })[0]
    first = prefix_service.persist_prefix_candidates([candidate], collection_run_id='run-1')
    second = prefix_service.persist_prefix_candidates([candidate], collection_run_id='run-2')
    assert first['created'] == 1
    assert second['updated'] == 1
    row = conn.execute('SELECT network_type FROM prefixes').fetchone()
    assert row['network_type'] == 'unclassified'
    assert conn.execute('SELECT COUNT(*) FROM prefixes').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM prefix_observations').fetchone()[0] == 1


def test_persist_attaches_vip_address_role_without_changing_prefix_type(monkeypatch) -> None:
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE prefixes (
            id TEXT PRIMARY KEY, prefix TEXT, prefix_cidr TEXT, vrf_id TEXT, site_id TEXT, tenant_id TEXT,
            status TEXT, name TEXT, network_type TEXT, traceable INTEGER, source_type TEXT,
            source_ref TEXT, confidence REAL, last_observed_at TEXT,
            classification_status TEXT, classification_source TEXT, classification_confidence REAL,
            classification_rule_version TEXT, manual_override INTEGER, mixed_network INTEGER,
            address_roles_json TEXT, discovered_devices_json TEXT, observed_interfaces_json TEXT,
            observed_vlans_json TEXT, observed_vrfs_json TEXT, evidence_json TEXT, candidate_scores_json TEXT,
            first_seen_at TEXT, last_seen_at TEXT,
            miss_count INTEGER, is_active INTEGER, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE prefix_observations (
            id TEXT PRIMARY KEY, prefix_id TEXT, collection_run_id TEXT, source_device_id TEXT,
            source_type TEXT, observed_value TEXT, evidence_json TEXT, confidence REAL,
            first_seen_at TEXT, last_seen_at TEXT, miss_count INTEGER, is_active INTEGER
        );
        CREATE UNIQUE INDEX uq_prefix_observation_identity
            ON prefix_observations(prefix_id, source_device_id, source_type, observed_value);
        CREATE TABLE ipam_vips (
            address TEXT, vip_type TEXT, status TEXT, tenant_id TEXT
        );
        CREATE TABLE ipam_dhcp_leases (
            address TEXT, mac_address TEXT, hostname TEXT, dhcp_server TEXT, lease_state TEXT,
            tenant_id TEXT DEFAULT 'tenant-default'
        );
    ''')
    conn.execute(
        "INSERT INTO ipam_vips(address, vip_type, status, tenant_id) VALUES (?, ?, ?, ?)",
        ('192.0.2.10', 'virtual_service', 'active', 'tenant-default'),
    )
    conn.execute(
        "INSERT INTO ipam_dhcp_leases(address, mac_address, hostname, dhcp_server, lease_state) VALUES (?, ?, ?, ?, ?)",
        ('192.0.2.20', '0011.2233.4455', 'client-01', 'dhcp-01', 'active'),
    )

    class NonClosingConnection:
        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            return None

    monkeypatch.setattr(prefix_service, 'get_db_connection', lambda: NonClosingConnection())
    candidate = build_prefix_candidates({
        'device': {'id': 'dev-1', 'hostname': 'access-01'},
        'categories': [{'key': 'interfaces', 'records': [
            {'INTERFACE': 'Vlan100', 'IP_ADDRESS': '192.0.2.1/24'},
        ]}],
    })[0]

    prefix_service.persist_prefix_candidates([candidate], collection_run_id='run-vip')
    row = conn.execute('SELECT network_type, address_roles_json FROM prefixes').fetchone()
    assert row['network_type'] == 'user_access'
    assert json.loads(row['address_roles_json']) == [
        {
            'address': '192.0.2.10',
            'address_role': 'virtual_service',
            'status': 'active',
        },
        {
            'address': '192.0.2.20',
            'address_role': 'dhcp_lease',
            'status': 'active',
            'mac_address': '0011.2233.4455',
            'hostname': 'client-01',
            'dhcp_server': 'dhcp-01',
        },
    ]
