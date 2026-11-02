from __future__ import annotations

from database import get_db_connection
from services import ip_locator_service


def _insert_site(conn, site_id: str, site_code: str, site_name: str) -> None:
    conn.execute(
        """INSERT INTO sites (id, site_code, site_name, status)
           VALUES (?, ?, ?, 'active')""",
        (site_id, site_code, site_name),
    )


def _insert_device(conn, device_id: str, hostname: str, site_id: str = '') -> None:
    conn.execute(
        """INSERT INTO devices
           (id, hostname, ip_address, platform, status, role, site, site_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            device_id,
            hostname,
            f'192.0.2.{len(device_id) % 200 + 1}',
            'cisco_ios',
            'online',
            'switch',
            hostname,
            site_id,
        ),
    )


def _insert_interface(
    conn,
    interface_id: str,
    device_id: str,
    interface_name: str,
    *,
    interface_type: str = 'physical',
    switchport_mode: str = 'access',
    access_vlan: int | None = None,
    ip_address: str = '',
    vrf_id: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, interface_type, switchport_mode, access_vlan, ip_address, vrf_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (interface_id, device_id, interface_name, interface_type, switchport_mode, access_vlan, ip_address, vrf_id),
    )


def _insert_vlan_prefix_vrf(
    conn,
    site_id: str,
    vrf_id: str,
    vrf_name: str,
    prefix_id: str,
    *,
    include_vlan: bool = True,
) -> None:
    if include_vlan:
        conn.execute(
            "INSERT INTO vlans (id, vlan_id, name, site_id, status, tenant_id) VALUES (?, ?, ?, ?, 'active', ?)",
            ('vlan-scope-10', 10, 'VLAN 10', site_id, 'tenant-default'),
        )
    conn.execute(
        "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES (?, ?, ?)",
        (vrf_id, vrf_name, 'tenant-default'),
    )
    conn.execute(
        """INSERT INTO prefixes
           (id, prefix, prefix_cidr, vrf_id, vlan_id, site_id, tenant_id, status, network_type)
           VALUES (?, '198.51.100.0/24', '198.51.100.0/24', ?, 'vlan-scope-10', ?, ?, 'active', 'user_access')""",
        (prefix_id, vrf_id, site_id, 'tenant-default'),
    )


def _patch_collector(monkeypatch, devices, arp_entries, mac_records):
    monkeypatch.setattr(ip_locator_service, 'run_arp_sweep', lambda **_kwargs: None)
    monkeypatch.setattr(
        ip_locator_service,
        'get_arp_table',
        lambda: {'entries': list(arp_entries)},
    )
    monkeypatch.setattr(ip_locator_service, '_load_eligible_devices', lambda **_kwargs: list(devices))
    monkeypatch.setattr(
        ip_locator_service,
        'filter_devices',
        lambda selected, *_args, **_kwargs: list(selected),
    )
    monkeypatch.setattr(ip_locator_service, 'should_collect', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        ip_locator_service,
        '_collect_full_mac_table_from_device',
        lambda device: {
            'success': True,
            'transport': 'snmp',
            'records': [
                dict(record)
                for record in mac_records
                if str(record.get('switch_id') or '') == str(device.get('id') or '')
            ],
        },
    )
    monkeypatch.setattr(
        ip_locator_service,
        '_persist_mac_table_records',
        lambda records: len(records),
    )
    monkeypatch.setattr(ip_locator_service, 'sync_ip_inventory', lambda: None)
    monkeypatch.setattr(ip_locator_service, 'lookup_vendor', lambda _mac: '')


def _endpoint_rows():
    conn = get_db_connection()
    try:
        return conn.execute(
            "SELECT ip, switch_id, switch_port, vlan, vrf, site, is_active, confidence "
            "FROM network_endpoints ORDER BY ip"
        ).fetchall()
    finally:
        conn.close()


def test_collector_uses_cmdb_site_id_for_arp_fallback_and_best_mac(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-arp', 'SITE-ARP', 'ARP Site')
        _insert_site(conn, 'site-mac', 'SITE-MAC', 'MAC Site')
        _insert_device(conn, 'device-arp', 'SW-ARP', 'site-arp')
        _insert_device(conn, 'device-mac', 'SW-MAC', 'site-mac')
        conn.commit()
    finally:
        conn.close()

    devices = [
        {'id': 'device-arp', 'hostname': 'SW-ARP', 'platform': 'cisco_ios', 'role': 'switch'},
        {'id': 'device-mac', 'hostname': 'SW-MAC', 'platform': 'cisco_ios', 'role': 'switch'},
    ]
    arp_entries = [
        {
            'ip': '198.51.100.10',
            'mac_raw': '0011.2233.4455',
            'device_id': 'device-arp',
            'device': 'SW-ARP',
            'interface': 'Vlan10',
            'vlan': '10',
            'vrf': 'global',
        },
        {
            'ip': '198.51.100.11',
            'mac_raw': '0066.7788.99aa',
            'device_id': 'device-mac',
            'device': 'SW-MAC',
            'interface': 'Vlan20',
            'vlan': '20',
            'vrf': 'global',
        },
    ]
    mac_records = [
        {
            'mac': '0066778899aa',
            'switch_id': 'device-mac',
            'switch_name': 'SW-MAC',
            'port': 'Gi1/0/10',
            'vlan': '20',
            'vrf': 'global',
            'type': 'dynamic',
        },
    ]
    conn = get_db_connection()
    try:
        _insert_interface(conn, 'interface-mac-access', 'device-mac', 'Gi1/0/10', access_vlan=20)
        conn.commit()
    finally:
        conn.close()
    _patch_collector(monkeypatch, devices, arp_entries, mac_records)

    ip_locator_service.run_endpoint_collector()

    rows = {row['ip']: row for row in _endpoint_rows()}
    assert rows['198.51.100.10']['site'] == 'site-arp'
    assert rows['198.51.100.11']['site'] == 'site-mac'
    assert rows['198.51.100.10']['switch_id'] == ''
    assert rows['198.51.100.10']['switch_port'] == ''
    assert rows['198.51.100.11']['switch_id'] == 'device-mac'
    assert rows['198.51.100.11']['switch_port'] == 'Gi1/0/10'
    assert rows['198.51.100.10']['site'] != 'SW-ARP'
    assert rows['198.51.100.11']['site'] != 'SW-MAC'


def test_collector_does_not_project_unassigned_device_scope(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        _insert_device(conn, 'device-unassigned', 'SW-UNASSIGNED')
        conn.commit()
    finally:
        conn.close()

    devices = [
        {
            'id': 'device-unassigned',
            'hostname': 'SW-UNASSIGNED',
            'platform': 'cisco_ios',
            'role': 'switch',
        },
    ]
    _patch_collector(
        monkeypatch,
        devices,
        [
            {
                'ip': '198.51.100.20',
                'mac_raw': '00aa.bbcc.ddee',
                'device_id': 'device-unassigned',
                'device': 'SW-UNASSIGNED',
                'interface': 'Vlan30',
            },
        ],
        [{
            'mac': '00aabbccddee',
            'switch_id': 'device-unassigned',
            'switch_name': 'SW-UNASSIGNED',
            'port': 'Gi1/0/30',
            'vlan': '30',
            'type': 'dynamic',
        }],
    )

    ip_locator_service.run_endpoint_collector()

    assert _endpoint_rows() == []


def test_collector_refreshes_site_id_after_device_site_move(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-before', 'SITE-BEFORE', 'Before')
        _insert_site(conn, 'site-after', 'SITE-AFTER', 'After')
        _insert_device(conn, 'device-move', 'SW-MOVE', 'site-before')
        conn.commit()
    finally:
        conn.close()

    devices = [
        {'id': 'device-move', 'hostname': 'SW-MOVE', 'platform': 'cisco_ios', 'role': 'switch'},
    ]
    arp_entries = [
        {
            'ip': '198.51.100.30',
            'mac_raw': '00de.adbe.ef01',
            'device_id': 'device-move',
            'device': 'SW-MOVE',
            'interface': 'Vlan40',
            'vlan': '40',
            'vrf': 'global',
        },
    ]
    _patch_collector(monkeypatch, devices, arp_entries, [{
        'mac': '00deadbeef01',
        'switch_id': 'device-move',
        'switch_name': 'SW-MOVE',
        'port': 'Gi1/0/40',
        'vlan': '40',
        'vrf': 'global',
        'type': 'dynamic',
    }])
    conn = get_db_connection()
    try:
        _insert_interface(conn, 'interface-move-access', 'device-move', 'Gi1/0/40', access_vlan=40)
        conn.commit()
    finally:
        conn.close()

    ip_locator_service.run_endpoint_collector()
    assert _endpoint_rows()[0]['site'] == 'site-before'

    conn = get_db_connection()
    try:
        conn.execute("UPDATE devices SET site_id = ?, site = ? WHERE id = ?", ('site-after', 'After', 'device-move'))
        conn.commit()
    finally:
        conn.close()

    ip_locator_service.run_endpoint_collector()

    # The table is globally unique by IP. A site move is an explicit scope
    # change, so the previous row is preserved instead of borrowing first_seen.
    assert _endpoint_rows()[0]['site'] == 'site-before'
    assert _endpoint_rows()[0]['is_active'] == 1


def test_collector_does_not_join_mac_from_another_site(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-source', 'SITE-SOURCE', 'Source')
        _insert_site(conn, 'site-other', 'SITE-OTHER', 'Other')
        _insert_device(conn, 'device-source', 'SW-SOURCE', 'site-source')
        _insert_device(conn, 'device-other', 'SW-OTHER', 'site-other')
        _insert_interface(conn, 'interface-other-access', 'device-other', 'Gi1/0/1', access_vlan=10)
        conn.commit()
    finally:
        conn.close()

    _patch_collector(
        monkeypatch,
        [
            {'id': 'device-source', 'hostname': 'SW-SOURCE', 'platform': 'cisco_ios', 'role': 'switch'},
            {'id': 'device-other', 'hostname': 'SW-OTHER', 'platform': 'cisco_ios', 'role': 'switch'},
        ],
        [{
            'ip': '198.51.100.60', 'mac_raw': '00aa.bbcc.ddee',
            'device_id': 'device-source', 'vlan': '10', 'vrf': 'global',
        }],
        [{
            'mac': '00aabbccddee', 'switch_id': 'device-other', 'port': 'Gi1/0/1',
            'vlan': '10', 'vrf': 'global', 'type': 'dynamic',
        }],
    )

    ip_locator_service.run_endpoint_collector()

    row = _endpoint_rows()[0]
    assert row['site'] == 'site-source'
    assert row['switch_id'] == ''
    assert row['switch_port'] == ''


def test_collector_does_not_join_mac_from_another_tenant(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-tenant-scope', 'SITE-TENANT', 'Tenant Site')
        conn.execute("INSERT INTO tenants (id, name) VALUES (?, ?)", ('tenant-other', 'Other Tenant'))
        _insert_device(conn, 'device-tenant-a', 'SW-TENANT-A', 'site-tenant-scope')
        _insert_device(conn, 'device-tenant-b', 'SW-TENANT-B', 'site-tenant-scope')
        conn.execute("UPDATE devices SET tenant_id = ? WHERE id = ?", ('tenant-other', 'device-tenant-b'))
        _insert_interface(conn, 'interface-tenant-access', 'device-tenant-b', 'Gi1/0/1', access_vlan=10)
        conn.commit()
    finally:
        conn.close()

    _patch_collector(
        monkeypatch,
        [
            {'id': 'device-tenant-a', 'hostname': 'SW-TENANT-A', 'platform': 'cisco_ios', 'role': 'switch'},
            {'id': 'device-tenant-b', 'hostname': 'SW-TENANT-B', 'platform': 'cisco_ios', 'role': 'switch', 'tenant_id': 'tenant-other'},
        ],
        [{
            'ip': '198.51.100.67', 'mac_raw': '00aa.bbcc.ddf7',
            'device_id': 'device-tenant-a', 'vlan': '10', 'vrf': 'global',
        }],
        [{
            'mac': '00aabbccddf7', 'switch_id': 'device-tenant-b', 'port': 'Gi1/0/1',
            'vlan': '10', 'vrf': 'global', 'type': 'dynamic',
        }],
    )

    ip_locator_service.run_endpoint_collector()

    row = _endpoint_rows()[0]
    assert row['site'] == 'site-tenant-scope'
    assert row['switch_id'] == ''
    assert row['switch_port'] == ''


def test_collector_requires_vlan_and_explicit_vrf_match(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-vlan-scope', 'SITE-VLAN', 'VLAN Site')
        _insert_device(conn, 'device-vlan-scope', 'SW-VLAN', 'site-vlan-scope')
        _insert_interface(conn, 'interface-vlan-access', 'device-vlan-scope', 'Gi1/0/2', access_vlan=20)
        conn.commit()
    finally:
        conn.close()

    common_devices = [{
        'id': 'device-vlan-scope', 'hostname': 'SW-VLAN', 'platform': 'cisco_ios', 'role': 'switch',
    }]
    _patch_collector(
        monkeypatch,
        common_devices,
        [{
            'ip': '198.51.100.61', 'mac_raw': '00aa.bbcc.ddf0',
            'device_id': 'device-vlan-scope', 'vlan': '10', 'vrf': 'global',
        }],
        [{
            'mac': '00aabbccddf0', 'switch_id': 'device-vlan-scope', 'port': 'Gi1/0/2',
            'vlan': '20', 'vrf': 'global', 'type': 'dynamic',
        }],
    )
    ip_locator_service.run_endpoint_collector()
    first = _endpoint_rows()[0]
    assert first['switch_id'] == ''
    assert first['switch_port'] == ''

    _patch_collector(
        monkeypatch,
        common_devices,
        [{
            'ip': '198.51.100.62', 'mac_raw': '00aa.bbcc.ddf1',
            'device_id': 'device-vlan-scope', 'vlan': '20',
        }],
        [{
            'mac': '00aabbccddf1', 'switch_id': 'device-vlan-scope', 'port': 'Gi1/0/2',
            'vlan': '20', 'vrf': 'global', 'type': 'dynamic',
        }],
    )
    ip_locator_service.run_endpoint_collector()
    rows = {item['ip']: item for item in _endpoint_rows()}
    assert rows['198.51.100.62']['switch_id'] == ''
    assert rows['198.51.100.62']['switch_port'] == ''


def test_collector_resolves_vrf_for_l2_mac_from_unique_active_vlan_prefix(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-vlan-vrf', 'SITE-VLAN-VRF', 'VLAN VRF Site')
        _insert_device(conn, 'device-vlan-vrf', 'SW-VLAN-VRF', 'site-vlan-vrf')
        _insert_interface(conn, 'interface-vlan-vrf', 'device-vlan-vrf', 'Gi1/0/10', access_vlan=10)
        _insert_vlan_prefix_vrf(conn, 'site-vlan-vrf', 'vrf-blue', 'Blue', 'prefix-vrf-blue')
        conn.commit()
    finally:
        conn.close()

    _patch_collector(
        monkeypatch,
        [{'id': 'device-vlan-vrf', 'hostname': 'SW-VLAN-VRF', 'platform': 'cisco_ios', 'role': 'switch'}],
        [{
            'ip': '198.51.100.68', 'mac_raw': '00aa.bbcc.ddf8',
            'device_id': 'device-vlan-vrf', 'vlan': '10', 'vrf': 'Blue',
        }],
        [{
            'mac': '00aabbccddf8', 'switch_id': 'device-vlan-vrf', 'port': 'Gi1/0/10',
            'vlan': '10', 'type': 'dynamic',
        }],
    )

    ip_locator_service.run_endpoint_collector()

    row = _endpoint_rows()[0]
    assert row['switch_id'] == 'device-vlan-vrf'
    assert row['switch_port'] == 'Gi1/0/10'
    assert row['vrf'] == 'vrf-blue'


def test_collector_rejects_vlan_to_multiple_vrf_associations(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-vlan-ambiguous', 'SITE-VLAN-AMB', 'Ambiguous VLAN Site')
        _insert_device(conn, 'device-vlan-ambiguous', 'SW-VLAN-AMB', 'site-vlan-ambiguous')
        _insert_interface(conn, 'interface-vlan-amb', 'device-vlan-ambiguous', 'Gi1/0/10', access_vlan=10)
        _insert_vlan_prefix_vrf(
            conn, 'site-vlan-ambiguous', 'vrf-blue-amb', 'Blue', 'prefix-vrf-blue-amb',
        )
        _insert_vlan_prefix_vrf(
            conn, 'site-vlan-ambiguous', 'vrf-red-amb', 'Red', 'prefix-vrf-red-amb',
            include_vlan=False,
        )
        conn.commit()
    finally:
        conn.close()

    _patch_collector(
        monkeypatch,
        [{'id': 'device-vlan-ambiguous', 'hostname': 'SW-VLAN-AMB', 'platform': 'cisco_ios', 'role': 'switch'}],
        [{
            'ip': '198.51.100.69', 'mac_raw': '00aa.bbcc.ddf9',
            'device_id': 'device-vlan-ambiguous', 'vlan': '10', 'vrf': 'Blue',
        }],
        [{
            'mac': '00aabbccddf9', 'switch_id': 'device-vlan-ambiguous', 'port': 'Gi1/0/10',
            'vlan': '10', 'type': 'dynamic',
        }],
    )

    ip_locator_service.run_endpoint_collector()

    row = _endpoint_rows()[0]
    assert row['switch_id'] == ''
    assert row['switch_port'] == ''


def test_collector_does_not_assign_a_trunk_as_an_access_port(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-trunk', 'SITE-TRUNK', 'Trunk Site')
        _insert_device(conn, 'device-trunk', 'SW-TRUNK', 'site-trunk')
        _insert_interface(
            conn, 'interface-trunk', 'device-trunk', 'Gi1/0/48',
            switchport_mode='trunk',
        )
        conn.commit()
    finally:
        conn.close()

    _patch_collector(
        monkeypatch,
        [{'id': 'device-trunk', 'hostname': 'SW-TRUNK', 'platform': 'cisco_ios', 'role': 'switch'}],
        [{
            'ip': '198.51.100.63', 'mac_raw': '00aa.bbcc.ddf2',
            'device_id': 'device-trunk', 'vlan': '30', 'vrf': 'global',
        }],
        [{
            'mac': '00aabbccddf2', 'switch_id': 'device-trunk', 'port': 'Gi1/0/48',
            'vlan': '30', 'vrf': 'global', 'type': 'dynamic',
        }],
    )

    ip_locator_service.run_endpoint_collector()

    row = _endpoint_rows()[0]
    assert row['switch_id'] == ''
    assert row['switch_port'] == ''


def test_collector_excludes_device_interface_addresses(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-interface-ip', 'SITE-IFIP', 'Interface IP Site')
        _insert_device(conn, 'device-interface-ip', 'SW-IFIP', 'site-interface-ip')
        _insert_interface(
            conn, 'interface-own-ip', 'device-interface-ip', 'Vlan50',
            interface_type='svi', switchport_mode='edge', ip_address='198.51.100.64/24',
        )
        _insert_interface(
            conn, 'interface-host-access', 'device-interface-ip', 'Gi1/0/5', access_vlan=50,
        )
        conn.commit()
    finally:
        conn.close()

    _patch_collector(
        monkeypatch,
        [{'id': 'device-interface-ip', 'hostname': 'SW-IFIP', 'platform': 'cisco_ios', 'role': 'switch'}],
        [
            {
                'ip': '198.51.100.64', 'mac_raw': '00aa.bbcc.ddf3',
                'device_id': 'device-interface-ip', 'vlan': '50', 'vrf': 'global',
            },
            {
                'ip': '198.51.100.65', 'mac_raw': '00aa.bbcc.ddf4',
                'device_id': 'device-interface-ip', 'vlan': '50', 'vrf': 'global',
            },
        ],
        [{
            'mac': '00aabbccddf4', 'switch_id': 'device-interface-ip', 'port': 'Gi1/0/5',
            'vlan': '50', 'vrf': 'global', 'type': 'dynamic',
        }],
    )

    ip_locator_service.run_endpoint_collector()

    rows = {row['ip']: row for row in _endpoint_rows()}
    assert '198.51.100.64' not in rows
    assert rows['198.51.100.65']['switch_port'] == 'Gi1/0/5'


def test_interface_address_exclusion_does_not_cross_vrfs(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-vrf-interface', 'SITE-VRF-IF', 'VRF Interface Site')
        _insert_device(conn, 'device-vrf-interface', 'SW-VRF-IF', 'site-vrf-interface')
        conn.execute(
            "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES (?, ?, ?)",
            ('vrf-blue-exclusion', 'Blue', 'tenant-default'),
        )
        conn.execute(
            "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES (?, ?, ?)",
            ('vrf-red-exclusion', 'Red', 'tenant-default'),
        )
        _insert_interface(
            conn, 'interface-blue-own-ip', 'device-vrf-interface', 'Vlan10',
            interface_type='svi', ip_address='198.51.100.70/24', vrf_id='vrf-blue-exclusion',
        )
        _insert_interface(
            conn, 'interface-red-access', 'device-vrf-interface', 'Gi1/0/10',
            access_vlan=10, vrf_id='vrf-red-exclusion',
        )
        conn.commit()
    finally:
        conn.close()

    _patch_collector(
        monkeypatch,
        [{'id': 'device-vrf-interface', 'hostname': 'SW-VRF-IF', 'platform': 'cisco_ios', 'role': 'switch'}],
        [{
            'ip': '198.51.100.70', 'mac_raw': '00aa.bbcc.ddf5',
            'device_id': 'device-vrf-interface', 'vlan': '10', 'vrf': 'Red',
        }],
        [{
            'mac': '00aabbccddf5', 'switch_id': 'device-vrf-interface', 'port': 'Gi1/0/10',
            'vlan': '10', 'type': 'dynamic',
        }],
    )

    ip_locator_service.run_endpoint_collector()

    rows = _endpoint_rows()
    assert len(rows) == 1
    assert rows[0]['ip'] == '198.51.100.70'
    assert rows[0]['vrf'] == 'vrf-red-exclusion'
    assert rows[0]['switch_port'] == ''


def test_collector_skips_same_ip_from_multiple_scopes_in_one_batch(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-duplicate-a', 'SITE-DUP-A', 'Duplicate A')
        _insert_site(conn, 'site-duplicate-b', 'SITE-DUP-B', 'Duplicate B')
        _insert_device(conn, 'device-duplicate-a', 'SW-DUP-A', 'site-duplicate-a')
        _insert_device(conn, 'device-duplicate-b', 'SW-DUP-B', 'site-duplicate-b')
        _insert_interface(conn, 'interface-duplicate-a', 'device-duplicate-a', 'Gi1/0/1', access_vlan=10)
        _insert_interface(conn, 'interface-duplicate-b', 'device-duplicate-b', 'Gi1/0/2', access_vlan=20)
        conn.commit()
    finally:
        conn.close()

    _patch_collector(
        monkeypatch,
        [
            {'id': 'device-duplicate-a', 'hostname': 'SW-DUP-A', 'platform': 'cisco_ios', 'role': 'switch'},
            {'id': 'device-duplicate-b', 'hostname': 'SW-DUP-B', 'platform': 'cisco_ios', 'role': 'switch'},
        ],
        [
            {
                'ip': '198.51.100.66', 'mac_raw': '00aa.bbcc.ddf5',
                'device_id': 'device-duplicate-a', 'vlan': '10', 'vrf': 'global',
            },
            {
                'ip': '198.51.100.66', 'mac_raw': '00aa.bbcc.ddf6',
                'device_id': 'device-duplicate-b', 'vlan': '20', 'vrf': 'global',
            },
        ],
        [
            {
                'mac': '00aabbccddf5', 'switch_id': 'device-duplicate-a', 'port': 'Gi1/0/1',
                'vlan': '10', 'vrf': 'global', 'type': 'dynamic',
            },
            {
                'mac': '00aabbccddf6', 'switch_id': 'device-duplicate-b', 'port': 'Gi1/0/2',
                'vlan': '20', 'vrf': 'global', 'type': 'dynamic',
            },
        ],
    )

    ip_locator_service.run_endpoint_collector()

    assert _endpoint_rows() == []


def test_direct_endpoint_cache_save_uses_validated_cmdb_site_id(isolated_db):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-direct', 'SITE-DIRECT', 'Direct Site')
        _insert_device(conn, 'device-direct', 'SW-DIRECT', 'site-direct')
        conn.commit()
    finally:
        conn.close()

    ip_locator_service._set_cached_endpoint(
        ip='198.51.100.40',
        mac='00ff.eedd.ccbb',
        device_id='device-direct',
        port='Gi1/0/1',
        site='SW-DIRECT',
        source_type='path_traced',
    )

    rows = _endpoint_rows()
    assert len(rows) == 1
    assert rows[0]['site'] == 'site-direct'


def test_direct_endpoint_cache_does_not_overwrite_another_scope(isolated_db):
    conn = get_db_connection()
    try:
        _insert_site(conn, 'site-direct-a', 'SITE-DIRECT-A', 'Direct A')
        _insert_site(conn, 'site-direct-b', 'SITE-DIRECT-B', 'Direct B')
        _insert_device(conn, 'device-direct-a', 'SW-DIRECT-A', 'site-direct-a')
        _insert_device(conn, 'device-direct-b', 'SW-DIRECT-B', 'site-direct-b')
        conn.commit()
    finally:
        conn.close()

    ip_locator_service._set_cached_endpoint(
        ip='198.51.100.41', mac='00ff.eedd.cc01', device_id='device-direct-a',
        port='Gi1/0/1', vlan='10', vrf='blue', source_type='path_traced',
    )
    ip_locator_service._set_cached_endpoint(
        ip='198.51.100.41', mac='00ff.eedd.cc02', device_id='device-direct-b',
        port='Gi1/0/2', vlan='20', vrf='blue', source_type='path_traced',
    )

    rows = _endpoint_rows()
    assert len(rows) == 1
    assert rows[0]['switch_id'] == 'device-direct-a'
    assert rows[0]['site'] == 'site-direct-a'
    assert rows[0]['vlan'] == '10'
