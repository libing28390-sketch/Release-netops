from __future__ import annotations

import pytest

from services.cmdb_service import (
    export_vlans,
    get_vlan_details,
    list_cmdb_interfaces,
    list_vlans,
)
from services import cmdb_cli_collection_service
from database import get_db_connection


_NOW = '2026-10-27T08:00:00+00:00'


def _site_asset_device(conn, *, device_id: str, site_id: str = 'site-cli') -> None:
    conn.execute(
        "INSERT INTO sites (id, site_code, site_name, status) VALUES (?, ?, ?, ?)",
        (site_id, site_id.upper(), site_id, 'active'),
    )
    conn.execute(
        """INSERT INTO physical_assets (id, asset_type, site_id, created_at, updated_at)
           VALUES (?, 'network_device', ?, ?, ?)""",
        (f'asset-{device_id}', site_id, _NOW, _NOW),
    )
    conn.execute(
        """INSERT INTO devices
           (id, hostname, ip_address, status, platform, vendor, tenant_id,
            site_id, site, asset_id)
           VALUES (?, ?, ?, 'online', 'h3c_comware', 'h3c', 'tenant-default', ?, ?, ?)""",
        (device_id, device_id, '192.0.2.10', 'stale-device-site', 'STALE-LABEL', f'asset-{device_id}'),
    )


def _insert_interface(
    conn,
    *,
    interface_id: str,
    device_id: str,
    name: str,
    description: str = '',
    admin_status: str = 'down',
    oper_status: str = 'down',
    primary_ip: str = '',
    ip_address: str = '',
    ip_prefix_length: int | None = None,
    access_vlan: int | None = None,
    interface_role: str = 'unclassified',
    speed: float = 0,
    bandwidth: float = 0,
) -> None:
    conn.execute(
        """INSERT INTO interfaces (
               id, device_id, interface_name, description, admin_status, oper_status,
               mac_address, speed, bandwidth, interface_type, switchport_mode,
               access_vlan, native_vlan, allowed_vlans, primary_ip, ip_address,
               ip_prefix_length, ip_enabled, interface_role,
               utilization_warn_pct, utilization_high_pct, utilization_critical_pct
           ) VALUES (?, ?, ?, ?, ?, ?, '00:11:22:33:44:55', ?, ?, 'physical', 'access',
                     ?, NULL, '', ?, ?, ?, 1, ?, 70, 80, 90)""",
        (
            interface_id, device_id, name, description, admin_status, oper_status,
            speed, bandwidth, access_vlan, primary_ip, ip_address, ip_prefix_length,
            interface_role,
        ),
    )


def _snapshot_attempt(conn, device_id: str, domain: str) -> None:
    conn.execute(
        """INSERT INTO cmdb_collection_snapshots (
               device_id, domain, attempt_generation, successful_generation,
               attempt_status, run_id, last_attempt_at, last_success_at, observed_at,
               transport, record_count, failure_code, metadata_json
           ) VALUES (?, ?, 2, 1, 'failed', ?, ?, ?, ?, 'ssh', 2, 'command_failed', '{}')""",
        (device_id, domain, f'run-{domain}-{device_id}', _NOW, _NOW, _NOW),
    )


def test_interface_projection_uses_last_good_snapshot_before_pagination_and_preserves_shared_fields(isolated_db):
    conn = get_db_connection()
    try:
        _site_asset_device(conn, device_id='device-cli')
        _site_asset_device(conn, device_id='device-legacy', site_id='site-legacy')
        _insert_interface(
            conn,
            interface_id='shared-cli-interface',
            device_id='device-cli',
            name='GE0/0/1',
            description='stale shared description',
            admin_status='down',
            oper_status='down',
            primary_ip='192.0.2.99',
            ip_address='192.0.2.99',
            interface_role='uplink',
            speed=1000,
            bandwidth=2000,
        )
        _insert_interface(
            conn,
            interface_id='shared-cli-empty-interface',
            device_id='device-cli',
            name='GE0/0/3',
            description='stale description must not fill empty CLI description',
            primary_ip='192.0.2.39',
            ip_address='192.0.2.39',
        )
        conn.execute(
            "INSERT INTO topology_links (id, source_interface_id) VALUES (?, ?)",
            ('shared-link', 'shared-cli-interface'),
        )
        conn.execute(
            """INSERT INTO prefixes (id, prefix, prefix_cidr, tenant_id, site_id)
               VALUES ('prefix-cli', '192.0.2.0/24', '192.0.2.0/24',
                       'tenant-default', 'site-cli')"""
        )
        conn.execute(
            """INSERT INTO ip_addresses (
                   id, subnet_id, address, device_id, interface_name, interface_id,
                   ip_address, address_inet, created_at, updated_at
               ) VALUES ('ip-cli', 'prefix-cli', '192.0.2.99', 'device-cli',
                         'GE0/0/1', 'shared-cli-interface', '192.0.2.99', '192.0.2.99', ?, ?)""",
            (_NOW, _NOW),
        )
        conn.execute(
            """INSERT INTO ip_addresses (
                   id, subnet_id, address, device_id, interface_name, interface_id,
                   ip_address, address_inet, created_at, updated_at
               ) VALUES ('ip-cli-stale', 'prefix-cli', '192.0.2.39', 'device-cli',
                         'GE0/0/3', 'shared-cli-empty-interface', '192.0.2.39', '192.0.2.39', ?, ?)""",
            (_NOW, _NOW),
        )
        _insert_interface(
            conn,
            interface_id='shared-legacy-interface',
            device_id='device-legacy',
            name='GE0/0/9',
            description='legacy shared port',
        )
        conn.execute(
            """INSERT INTO ip_inventory (ip, mask, device_id, interface, type, last_seen)
               VALUES ('198.51.100.9', '255.255.255.0', 'device-legacy',
                       'GE0/0/10', 'physical', ?)""",
            (_NOW,),
        )
        _snapshot_attempt(conn, 'device-cli', 'interface_inventory')
        conn.execute(
            """INSERT INTO cmdb_device_interface_observations (
                   device_id, normalized_interface_name, interface_name, description,
                   admin_status, oper_status, ip_address, ip_prefix_length,
                   interface_type, generation, observed_at, run_id, metadata_json
               ) VALUES
               ('device-cli', 'gi0/0/1', 'GigabitEthernet0/0/1', 'current CLI description',
                'up', 'up', '198.51.100.1', 24, 'physical', 1, ?, 'run-good', '{}'),
               ('device-cli', 'gi0/0/3', 'GigabitEthernet0/0/3', '',
                'up', 'up', '', NULL, 'physical', 1, ?, 'run-good', '{}'),
               ('device-cli', 'te0/0/2', 'TenGigabitEthernet0/0/2', 'CLI only port',
                'up', 'up', '', NULL, 'physical', 1, ?, 'run-good', '{}')""",
            (_NOW, _NOW, _NOW),
        )
        conn.commit()

        shared_before = tuple(conn.execute(
            """SELECT id, description, admin_status, oper_status, primary_ip, ip_address,
                      interface_role, speed, bandwidth, utilization_warn_pct,
                      utilization_high_pct, utilization_critical_pct
               FROM interfaces WHERE id = 'shared-cli-interface'"""
        ).fetchone())
        first = list_cmdb_interfaces(
            conn, page=1, page_size=1, tenant_id='tenant-default', site_ids=('site-cli',),
        )
        second = list_cmdb_interfaces(
            conn, page=2, page_size=1, tenant_id='tenant-default', site_ids=('site-cli',),
        )
        third = list_cmdb_interfaces(
            conn, page=3, page_size=1, tenant_id='tenant-default', site_ids=('site-cli',),
        )
        with_ip = list_cmdb_interfaces(
            conn, has_ip=True, page=1, page_size=10,
            tenant_id='tenant-default', site_ids=('site-cli',),
        )
        without_ip = list_cmdb_interfaces(
            conn, has_ip=False, page=1, page_size=10,
            tenant_id='tenant-default', site_ids=('site-cli',),
        )
        by_cli_description = list_cmdb_interfaces(
            conn, search='current CLI description', page=1, page_size=10,
            tenant_id='tenant-default', site_ids=('site-cli',),
        )
        unpaged = list_cmdb_interfaces(conn, device_id='device-cli')
        legacy_shared = list_cmdb_interfaces(conn, device_id='device-legacy')
        legacy_inventory = list_cmdb_interfaces(conn, has_ip=True, device_id='device-legacy')
        shared_after = tuple(conn.execute(
            """SELECT id, description, admin_status, oper_status, primary_ip, ip_address,
                      interface_role, speed, bandwidth, utilization_warn_pct,
                      utilization_high_pct, utilization_critical_pct
               FROM interfaces WHERE id = 'shared-cli-interface'"""
        ).fetchone())
    finally:
        conn.close()

    assert first['total'] == 3
    assert first['summary']['with_ip'] == 1
    assert first['summary']['oper_up'] == 3
    observed_shared = first['items'][0]
    assert observed_shared['id'] == 'shared-cli-interface'
    assert observed_shared['interface_source'] == 'cmdb_cli_snapshot'
    assert observed_shared['profile_editable'] is True
    assert observed_shared['description'] == 'current CLI description'
    assert observed_shared['admin_status'] == observed_shared['oper_status'] == 'up'
    assert observed_shared['interface_ip'] == '198.51.100.1'
    assert observed_shared['mac_address'] == '00:11:22:33:44:55'
    assert observed_shared['speed'] == 1000
    assert observed_shared['bandwidth'] == 2000
    assert observed_shared['interface_role'] == 'uplink'
    assert observed_shared['utilization_warn_pct'] == 70
    assert observed_shared['ip_count'] == 1
    assert observed_shared['link_count'] == 1
    assert second['items'][0]['id'] == 'shared-cli-empty-interface'
    assert second['items'][0]['profile_editable'] is True
    assert second['items'][0]['description'] == ''
    assert second['items'][0]['interface_ip'] == ''
    assert second['items'][0]['ip_count'] == 1
    assert third['items'][0]['id'] == 'cmdb-interface-observed:device-cli:te0/0/2'
    assert third['items'][0]['profile_editable'] is False
    assert third['items'][0]['interface_source'] == 'cmdb_cli_snapshot'
    assert with_ip['total'] == 1
    assert with_ip['items'][0]['interface_ip'] == '198.51.100.1'
    assert without_ip['total'] == 2
    assert {row['interface_name'] for row in without_ip['items']} == {
        'GigabitEthernet0/0/3', 'TenGigabitEthernet0/0/2',
    }
    assert by_cli_description['total'] == 1
    assert len(unpaged) == 3
    assert any(row['interface_name'] == 'GE0/0/9' for row in legacy_shared)
    assert any(row['interface_ip'] == '198.51.100.9' for row in legacy_inventory)
    assert shared_after == shared_before


def test_vlan_projection_uses_current_snapshot_for_synthetic_list_detail_and_export(isolated_db):
    conn = get_db_connection()
    observed_vlan_id = 'cmdb-vlan-observed:site-cli:219'
    try:
        _site_asset_device(conn, device_id='device-vlan-cli')
        _insert_interface(
            conn,
            interface_id='shared-vlan-port',
            device_id='device-vlan-cli',
            name='GE0/0/1',
            description='stale port description',
            access_vlan=999,
        )
        _insert_interface(
            conn,
            interface_id='stale-vlan-port',
            device_id='device-vlan-cli',
            name='GE0/0/2',
            description='stale-only member',
            access_vlan=219,
        )
        _insert_interface(
            conn,
            interface_id='shared-vlan-svi',
            device_id='device-vlan-cli',
            name='Vlan-interface 219',
            description='stale gateway description',
            primary_ip='192.0.2.219',
            ip_address='192.0.2.219',
            ip_prefix_length=24,
        )
        _snapshot_attempt(conn, 'device-vlan-cli', 'interface_inventory')
        _snapshot_attempt(conn, 'device-vlan-cli', 'vlan_inventory')
        conn.execute(
            """INSERT INTO cmdb_device_interface_observations (
                   device_id, normalized_interface_name, interface_name, description,
                   admin_status, oper_status, ip_address, ip_prefix_length,
                   interface_type, generation, observed_at, run_id, metadata_json
               ) VALUES
               ('device-vlan-cli', 'vlan219', 'Vlan-interface 219', 'CLI gateway',
                'up', 'up', '10.219.0.1', 24, 'svi', 1, ?, 'run-if-good', '{}'),
               ('device-vlan-cli', 'gi0/0/1', 'GE0/0/1', 'CLI port description',
                'up', 'up', '', NULL, 'physical', 1, ?, 'run-if-good', '{}')""",
            (_NOW, _NOW),
        )
        conn.execute(
            """INSERT INTO cmdb_device_vlan_observations (
                   device_id, vlan_id, site_id, vlan_name, vlan_status,
                   generation, observed_at, run_id
               ) VALUES ('device-vlan-cli', 219, 'site-cli', 'CLI-VLAN-219', 'active', 1, ?, 'run-vlan-good')""",
            (_NOW,),
        )
        conn.execute(
            """INSERT INTO cmdb_device_vlan_port_observations (
                   device_id, vlan_id, normalized_interface_name, interface_name,
                   port_mode, tagging, generation, observed_at, run_id, metadata_json
               ) VALUES ('device-vlan-cli', 219, 'gi0/0/1', 'GE0/0/1',
                         'access', 'untagged', 1, ?, 'run-vlan-good', '{}')""",
            (_NOW,),
        )
        conn.execute(
            """INSERT INTO arp_table
               (id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated)
               VALUES ('arp-cli-vlan', 'device-vlan-cli', '10.219.0.9',
                       '00:aa:bb:cc:dd:ee', 'GE0/0/1', 219, ?)""",
            (_NOW,),
        )
        conn.execute(
            """INSERT INTO mac_table
               (id, device_id, mac_address, interface_name, vlan_id, last_updated)
               VALUES ('mac-cli-vlan', 'device-vlan-cli', '00:aa:bb:cc:dd:ff',
                       'GE0/0/1', 219, ?)""",
            (_NOW,),
        )
        conn.commit()

        paged = list_vlans(
            conn,
            site_id='site-cli',
            tenant_id='tenant-default',
            device_scoped=True,
            page=1,
            page_size=10,
            include_details=True,
        )
        unpaged = list_vlans(
            conn, site_id='site-cli', tenant_id='tenant-default', device_scoped=True,
        )
        details = get_vlan_details(
            conn, observed_vlan_id, site_id='site-cli', device_id='device-vlan-cli',
        )
        export_rows = export_vlans(conn, site_id='site-cli', tenant_id='tenant-default')
        shared_after = [tuple(row) for row in conn.execute(
            """SELECT id, interface_name, description, access_vlan, primary_ip, ip_address
               FROM interfaces WHERE device_id = 'device-vlan-cli' ORDER BY id"""
        ).fetchall()]
    finally:
        conn.close()

    assert paged['total'] == 1
    row = paged['items'][0]
    assert row['id'] == observed_vlan_id
    assert row['cmdb_observed_only'] is True
    assert row['site_id'] == 'site-cli'
    assert row['name'] == 'CLI-VLAN-219'
    assert row['device_vlan_name'] == 'CLI-VLAN-219'
    assert row['device_vlan_generation'] == 1
    assert row['port_count'] == 1
    assert row['svi_interfaces'] == 'Vlan-interface 219'
    assert row['gateway'] == '10.219.0.1'
    assert row['prefixes'] == '10.219.0.0/24'
    assert row['port_detail_rows'] == [{
        'device_id': 'device-vlan-cli',
        'device_hostname': 'device-vlan-cli',
        'device_ip': '192.0.2.10',
        'interface_name': 'GE0/0/1',
        'description': 'CLI port description',
        'port_mode': 'access',
        'tagging': 'untagged',
        'source': 'cmdb_cli_snapshot',
    }]
    assert row['arp_count'] == 1
    assert row['mac_count'] == 1
    assert len(unpaged) == 1 and unpaged[0]['cmdb_observed_only'] is True
    assert details['cmdb_observed_only'] is True
    assert details['port_detail_rows'][0]['description'] == 'CLI port description'
    assert details['port_detail_rows'][0]['port_mode'] == 'access'
    assert details['port_detail_rows'][0]['tagging'] == 'untagged'
    assert details['meta']['arp_count'] == 1
    assert details['meta']['mac_count'] == 1
    assert len(export_rows) == 1
    assert export_rows[0]['VLAN ID'] == 219
    assert export_rows[0]['接入接口'] == 'GE0/0/1'
    assert export_rows[0]['接口描述'] == 'CLI port description'
    assert 'stale-only member' not in export_rows[0]['接口描述']
    assert shared_after == [
        ('shared-vlan-port', 'GE0/0/1', 'stale port description', 999, '', ''),
        ('shared-vlan-svi', 'Vlan-interface 219', 'stale gateway description', None, '192.0.2.219', '192.0.2.219'),
        ('stale-vlan-port', 'GE0/0/2', 'stale-only member', 219, '', ''),
    ]

    conn = get_db_connection()
    try:
        with pytest.raises(ValueError, match='scope'):
            get_vlan_details(conn, observed_vlan_id, site_id='unassigned', device_id='device-vlan-cli')
    finally:
        conn.close()


def test_vlan_and_interface_readers_keep_legacy_fallback_for_never_successful_device(isolated_db):
    conn = get_db_connection()
    try:
        _site_asset_device(conn, device_id='device-legacy-fallback', site_id='site-legacy-fallback')
        _insert_interface(
            conn,
            interface_id='legacy-svi',
            device_id='device-legacy-fallback',
            name='Vlan220',
            description='legacy gateway',
            primary_ip='10.220.0.1',
            ip_address='10.220.0.1',
            ip_prefix_length=24,
        )
        _insert_interface(
            conn,
            interface_id='legacy-port',
            device_id='device-legacy-fallback',
            name='GE0/0/9',
            description='legacy access port',
            access_vlan=220,
        )
        conn.execute(
            "INSERT INTO vlans (id, vlan_id, name, site_id, status, tenant_id) VALUES (?, ?, ?, ?, ?, ?)",
            ('vlan-legacy-fallback', 220, 'Legacy VLAN 220', 'site-legacy-fallback', 'active', 'tenant-default'),
        )
        conn.execute(
            """INSERT INTO ip_inventory (ip, mask, device_id, interface, type, last_seen)
               VALUES ('198.51.100.220', '255.255.255.0', 'device-legacy-fallback',
                       'GE0/0/9', 'physical', ?)""",
            (_NOW,),
        )
        conn.commit()

        interfaces = list_cmdb_interfaces(conn, has_ip=True, device_id='device-legacy-fallback')
        vlans = list_vlans(
            conn, site_id='site-legacy-fallback', tenant_id='tenant-default', device_scoped=True,
        )
        exported = export_vlans(conn, site_id='site-legacy-fallback', tenant_id='tenant-default')
    finally:
        conn.close()

    assert any(row['interface_ip'] == '198.51.100.220' for row in interfaces)
    vlan = next(row for row in vlans if row['vlan_id'] == 220)
    assert vlan['id'] == 'vlan-legacy-fallback'
    assert vlan['port_count'] == 1
    assert vlan['port_detail_rows'][0]['description'] == 'legacy access port'
    assert vlan['gateway'] == '10.220.0.1'
    assert exported[0]['VLAN ID'] == 220
    assert exported[0]['接口描述'] == 'legacy access port'


def test_vlan_snapshot_without_name_fails_closed_and_preserves_last_good(isolated_db):
    from services.cmdb_snapshot_service import begin_snapshot_attempt, fail_snapshot_attempt
    from services.cmdb_version_service import read_versions

    device_id = 'device-vlan-missing-name'
    conn = get_db_connection()
    try:
        _site_asset_device(conn, device_id=device_id, site_id='site-vlan-missing-name')
        conn.commit()
    finally:
        conn.close()

    valid_attempt = begin_snapshot_attempt(device_id, 'vlan_inventory')
    cmdb_cli_collection_service._persist_vlan_snapshot(
        device_id,
        [{'VLAN_ID': '219', 'VLAN_NAME': 'APP-NET'}],
        valid_attempt,
        observed_at=_NOW,
        metadata={'fixture': 'valid-name'},
    )

    invalid_attempt = begin_snapshot_attempt(device_id, 'vlan_inventory')
    with pytest.raises(RuntimeError, match='VLAN CLI快照包含缺少名称的记录'):
        cmdb_cli_collection_service._persist_vlan_snapshot(
            device_id,
            [{'VLAN_ID': '219', 'PORTS': 'GE1/0/1'}],
            invalid_attempt,
            observed_at='2026-10-27T09:00:00+00:00',
            metadata={'fixture': 'missing-name'},
        )
    fail_snapshot_attempt(
        invalid_attempt,
        error_code='RuntimeError',
        metadata={'message': 'VLAN snapshot completeness validation failed'},
    )

    conn = get_db_connection()
    try:
        snapshot = conn.execute(
            """SELECT attempt_generation, successful_generation, attempt_status,
                      last_success_at, failure_code
               FROM cmdb_collection_snapshots
               WHERE device_id = ? AND domain = 'vlan_inventory'""",
            (device_id,),
        ).fetchone()
        observations = conn.execute(
            """SELECT vlan_id, vlan_name, generation
               FROM cmdb_device_vlan_observations WHERE device_id = ?""",
            (device_id,),
        ).fetchall()
        revisions = read_versions(conn, ('vlans', 'bindings', 'interfaces'))
    finally:
        conn.close()

    assert tuple(snapshot) == (
        invalid_attempt['generation'], valid_attempt['generation'], 'failed', _NOW, 'RuntimeError',
    )
    assert [tuple(row) for row in observations] == [
        (219, 'APP-NET', valid_attempt['generation']),
    ]
    assert revisions == {'bindings': 1, 'interfaces': 1, 'vlans': 1}
