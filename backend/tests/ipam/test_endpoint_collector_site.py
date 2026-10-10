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
            "SELECT ip, switch_id, site, is_active FROM network_endpoints ORDER BY ip"
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
        },
        {
            'ip': '198.51.100.11',
            'mac_raw': '0066.7788.99aa',
            'device_id': 'device-mac',
            'device': 'SW-MAC',
            'interface': 'Vlan20',
        },
    ]
    mac_records = [
        {
            'mac': '0066778899aa',
            'switch_id': 'device-mac',
            'switch_name': 'SW-MAC',
            'port': 'Gi1/0/10',
            'vlan': '20',
            'type': 'dynamic',
        },
    ]
    _patch_collector(monkeypatch, devices, arp_entries, mac_records)

    ip_locator_service.run_endpoint_collector()

    rows = {row['ip']: row for row in _endpoint_rows()}
    assert rows['198.51.100.10']['site'] == 'site-arp'
    assert rows['198.51.100.11']['site'] == 'site-mac'
    assert rows['198.51.100.10']['site'] != 'SW-ARP'
    assert rows['198.51.100.11']['site'] != 'SW-MAC'


def test_collector_leaves_unassigned_device_site_empty(isolated_db, monkeypatch):
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

    rows = _endpoint_rows()
    assert len(rows) == 1
    assert rows[0]['site'] == ''


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
        },
    ]
    _patch_collector(monkeypatch, devices, arp_entries, [{
        'mac': '00deadbeef01',
        'switch_id': 'device-move',
        'switch_name': 'SW-MOVE',
        'port': 'Gi1/0/40',
        'vlan': '40',
        'type': 'dynamic',
    }])

    ip_locator_service.run_endpoint_collector()
    assert _endpoint_rows()[0]['site'] == 'site-before'

    conn = get_db_connection()
    try:
        conn.execute("UPDATE devices SET site_id = ?, site = ? WHERE id = ?", ('site-after', 'After', 'device-move'))
        conn.commit()
    finally:
        conn.close()

    ip_locator_service.run_endpoint_collector()

    assert _endpoint_rows()[0]['site'] == 'site-after'


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
