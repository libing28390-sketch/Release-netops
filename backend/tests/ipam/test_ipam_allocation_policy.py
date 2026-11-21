from __future__ import annotations

import ipaddress

import pytest

from api.ipam import ReservationRequest, api_next_available_ip
from api.devices import read_devices
from database import get_db_connection
from pydantic import ValidationError
from services.cmdb_snapshot_service import begin_snapshot_attempt, complete_snapshot
from services.ipam_address_space_service import create_address_space
from services.ipam_service import (
    allocate_next_address,
    create_address,
    create_subnet,
    get_next_available_ip,
    get_next_available_ip_details,
    get_next_available_prefix,
    list_ip_inventory,
    release_address,
    reserve_address,
    _first_free_address,
    _first_available_child_prefix,
    _space_gateway_reservations,
)


def _test_global_space_id() -> str:
    with get_db_connection() as conn:
        row = conn.execute(
            """SELECT id FROM ipam_address_spaces
                 WHERE security_tenant_id = 'tenant-default'
                   AND name = 'Allocation Policy Test Global' AND kind = 'global'"""
        ).fetchone()
    if row:
        return str(row['id'])
    return str(create_address_space(
        name='Allocation Policy Test Global',
        kind='global',
        vrf_id=None,
        security_tenant_id='tenant-default',
    )['id'])


def _create_test_prefix(
    *,
    prefix: str = '10.254.100.0/29',
    gateway: str = '10.254.100.1',
    vrf_id: str | None = None,
    site_id: str | None = None,
) -> dict:
    if site_id:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO sites(id, site_code, site_name, tenant_id) VALUES (?, ?, ?, 'tenant-default') ON CONFLICT(id) DO NOTHING",
                (site_id, site_id.upper(), site_id),
            )
            conn.commit()
    return create_subnet(
        prefix=prefix,
        address_space_id=None if vrf_id else _test_global_space_id(),
        gateway=gateway,
        vrf_id=vrf_id,
        site_id=site_id,
        network_type='management',
        name='IPAM allocation policy test prefix',
    )


def _publish_cmdb_interface_ip(
    device_id: str,
    ip: str,
    *,
    site_id: str | None,
    tenant_id: str = 'tenant-default',
    interface: str = 'Vlan-interface100',
    mask: int = 29,
    observed_at: str = '2026-11-05T10:00:00+00:00',
) -> None:
    with get_db_connection() as conn:
        if tenant_id != 'tenant-default':
            conn.execute(
                "INSERT INTO tenants(id, name) VALUES (?, ?) ON CONFLICT(id) DO NOTHING",
                (tenant_id, tenant_id),
            )
        if site_id:
            conn.execute(
                "INSERT INTO sites(id, site_code, site_name, tenant_id) VALUES (?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (site_id, site_id.upper(), site_id, tenant_id),
            )
        conn.execute(
            "INSERT INTO devices(id, hostname, tenant_id, site_id, status) VALUES (?, ?, ?, ?, 'online') ON CONFLICT(id) DO NOTHING",
            (device_id, device_id, tenant_id, site_id),
        )
        conn.commit()
    attempt = begin_snapshot_attempt(device_id, 'interface_inventory')
    with get_db_connection() as conn:
        conn.execute(
            '''INSERT INTO cmdb_device_interface_observations (
                   device_id, normalized_interface_name, interface_name, description,
                   admin_status, oper_status, ip_address, ip_prefix_length,
                   interface_type, generation, observed_at, run_id, metadata_json
               ) VALUES (?, ?, ?, '', 'up', 'up', ?, ?, 'svi', ?, ?, ?, '{}')
               ON CONFLICT (device_id, normalized_interface_name) DO UPDATE SET
                   interface_name = EXCLUDED.interface_name,
                   admin_status = EXCLUDED.admin_status,
                   oper_status = EXCLUDED.oper_status,
                   ip_address = EXCLUDED.ip_address,
                   ip_prefix_length = EXCLUDED.ip_prefix_length,
                   interface_type = EXCLUDED.interface_type,
                   generation = EXCLUDED.generation,
                   observed_at = EXCLUDED.observed_at,
                   run_id = EXCLUDED.run_id,
                   metadata_json = EXCLUDED.metadata_json''',
            (device_id, interface.lower(), interface, ip, mask, attempt['generation'],
             observed_at, attempt['run_id']),
        )
        assert complete_snapshot(
            conn, attempt, observed_at=observed_at,
            transport='test', record_count=1,
        )
        conn.commit()


def _insert_endpoint(
    ip: str,
    *,
    device_id: str,
    vrf: str,
    device_tenant: str = 'tenant-default',
    site_id: str | None = None,
    hostname: str = 'observed-host',
    mac: str = '00:11:22:33:44:55',
    switch_port: str = 'GigabitEthernet1/0/1',
    create_device: bool = True,
) -> None:
    with get_db_connection() as conn:
        if device_tenant and device_tenant != 'tenant-default':
            conn.execute(
                "INSERT INTO tenants(id, name) VALUES (?, ?) ON CONFLICT(id) DO NOTHING",
                (device_tenant, device_tenant),
            )
        if site_id:
            conn.execute(
                "INSERT INTO sites(id, site_code, site_name) VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (site_id, site_id.upper(), site_id),
            )
        if device_id and create_device:
            conn.execute(
                "INSERT INTO devices(id, hostname, tenant_id, site_id, status) VALUES (?, ?, ?, ?, 'online')",
                (device_id, f'endpoint-{device_id}', device_tenant, site_id),
            )
        conn.execute(
            '''INSERT INTO network_endpoints (
                   id, ip, mac, hostname, switch_id, switch_port, first_seen, last_seen, is_active, vrf, site
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                f'endpoint-{ip.replace(":", "-").replace(".", "-")}', ip,
                mac, hostname, device_id or 'unlinked-device', switch_port,
                '2026-09-02T00:00:00+00:00', '2026-09-02T00:00:00+00:00', 1, vrf, site_id or '',
            ),
        )
        conn.commit()


def test_manual_ip_allocation_protects_system_addresses_and_persists_purpose(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix()

    with pytest.raises(ValueError, match='Network address'):
        create_address(subnet['id'], address='10.254.100.0', purpose='business')

    with pytest.raises(ValueError, match='Broadcast address'):
        create_address(subnet['id'], address='10.254.100.7', purpose='business')

    with pytest.raises(ValueError, match='Gateway address'):
        create_address(subnet['id'], address='10.254.100.1', purpose='management', device_type='device')

    gateway = create_address(
        subnet['id'],
        address='10.254.100.1',
        purpose='infrastructure',
        device_type='gateway',
        hostname='gw-01',
    )
    business = create_address(
        subnet['id'],
        address='10.254.100.3',
        purpose='business',
        device_type='server',
        hostname='app-01',
    )

    assert gateway['address'] == '10.254.100.1'
    assert business['address'] == '10.254.100.3'

    with get_db_connection() as conn:
        rows = conn.execute(
            'SELECT address, device_type, purpose FROM ip_addresses WHERE subnet_id = ? ORDER BY address',
            (subnet['id'],),
        ).fetchall()

    assert [dict(row) for row in rows] == [
        {'address': '10.254.100.1', 'device_type': 'gateway', 'purpose': 'infrastructure'},
        {'address': '10.254.100.3', 'device_type': 'server', 'purpose': 'business'},
    ]

    business_inventory = list_ip_inventory(prefix_id=subnet['id'], purpose='business', page=1, page_size=20)
    assert [item['address'] for item in business_inventory['items']] == ['10.254.100.3']


def test_auto_allocation_skips_gateway_and_keeps_role_separate_from_purpose(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix()

    assert get_next_available_ip(subnet['id']) == '10.254.100.2'

    allocated = allocate_next_address(
        subnet['id'],
        device_type='device',
        purpose='management',
        hostname='switch-01',
        status='active',
    )

    assert allocated['address'] == '10.254.100.2'
    assert get_next_available_ip(subnet['id']) == '10.254.100.3'

    with get_db_connection() as conn:
        row = conn.execute(
            'SELECT device_type, purpose FROM ip_addresses WHERE id = ?',
            (allocated['id'],),
        ).fetchone()

    assert dict(row) == {'device_type': 'device', 'purpose': 'management'}


def test_suggestions_and_auto_allocation_skip_current_resolved_endpoint(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix(site_id='allocation-site')
    _insert_endpoint(
        '10.254.100.2', device_id='device-edge-001', vrf='global',
        site_id='allocation-site',
    )

    assert get_next_available_ip(subnet['id']) == '10.254.100.3'

    allocated = allocate_next_address(
        subnet['id'],
        device_type='server',
        purpose='business',
        hostname='app-01',
        status='active',
    )
    assert allocated['address'] == '10.254.100.3'


def test_legacy_active_endpoint_with_resolved_scope_still_reserves_ip(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix(site_id='allocation-site-legacy')
    _insert_endpoint(
        '10.254.100.2', device_id='device-legacy-resolved', vrf='global',
        site_id='allocation-site-legacy',
    )

    assert get_next_available_ip(subnet['id']) == '10.254.100.3'
    assert allocate_next_address(subnet['id'])['address'] == '10.254.100.3'


@pytest.mark.parametrize('vrf', ['MISSING-VRF', ''])
def test_current_endpoint_with_unknown_vrf_is_pending_in_matching_site(isolated_db, vrf) -> None:
    del isolated_db
    subnet = _create_test_prefix(site_id='allocation-site-legacy-unresolved')
    _insert_endpoint(
        '10.254.100.2', device_id='device-legacy-unresolved',
        vrf=vrf, site_id='allocation-site-legacy-unresolved',
    )

    assert get_next_available_ip_details(subnet['id']) == {
        'next_available_ip': '10.254.100.3', 'pending_discovery_count': 1,
    }
    assert allocate_next_address(subnet['id'])['address'] == '10.254.100.3'


def test_unlinked_explicit_global_endpoint_without_context_mapping_remains_pending(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix(site_id='allocation-site-unlinked-global')
    _insert_endpoint(
        '10.254.100.2', device_id='', vrf='global',
        site_id='allocation-site-unlinked-global',
    )

    assert get_next_available_ip_details(subnet['id']) == {
        'next_available_ip': '10.254.100.3', 'pending_discovery_count': 1,
    }


def test_unknown_vrf_active_endpoint_is_pending_and_is_reported(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix(site_id='allocation-site-pending')
    _insert_endpoint(
        '10.254.100.2', device_id='device-pending-vrf', vrf='MISSING-VRF',
        site_id='allocation-site-pending',
    )

    details = get_next_available_ip_details(subnet['id'])
    assert details == {'next_available_ip': '10.254.100.3', 'pending_discovery_count': 1}
    assert get_next_available_ip(subnet['id']) == '10.254.100.3'
    assert api_next_available_ip(subnet['id']) == {
        'subnet_id': subnet['id'],
        'next_available_ip': '10.254.100.3',
        'pending_discovery_count': 1,
    }
    assert allocate_next_address(subnet['id'])['address'] == '10.254.100.3'

    create_address(subnet['id'], address='10.254.100.2')
    registered_details = get_next_available_ip_details(subnet['id'])
    assert registered_details == {'next_available_ip': '10.254.100.4', 'pending_discovery_count': 0}


def test_unlinked_current_endpoint_with_resolved_site_is_pending(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix(site_id='allocation-site-unlinked')
    _insert_endpoint(
        '10.254.100.2', device_id='', vrf='MISSING-VRF',
        site_id='allocation-site-unlinked',
    )

    details = get_next_available_ip_details(subnet['id'])
    assert details == {'next_available_ip': '10.254.100.3', 'pending_discovery_count': 1}


@pytest.mark.parametrize(('device_id', 'device_tenant', 'device_site'), [
    ('device-no-site', 'tenant-default', None),
    ('device-other-site', 'tenant-default', 'allocation-site-other'),
    ('device-other-tenant', 'tenant-other', 'allocation-site-scope'),
    ('', 'tenant-default', None),
])
def test_unknown_tenant_or_site_current_endpoint_does_not_freeze_target(isolated_db, device_id, device_tenant, device_site) -> None:
    del isolated_db
    subnet = _create_test_prefix(site_id='allocation-site-scope')
    _insert_endpoint(
        '10.254.100.2',
        device_id=device_id,
        device_tenant=device_tenant,
        site_id=device_site,
        vrf='MISSING-VRF',
    )

    assert get_next_available_ip(subnet['id']) == '10.254.100.2'
    assert allocate_next_address(subnet['id'])['address'] == '10.254.100.2'


def test_current_cmdb_interface_snapshot_uses_latest_success_and_pending_host(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix(site_id='allocation-site-cmdb')
    _publish_cmdb_interface_ip(
        'device-cmdb-current', '10.254.100.2', site_id='allocation-site-cmdb',
        observed_at='2026-11-05T10:00:00+00:00',
    )
    _publish_cmdb_interface_ip(
        'device-cmdb-current', '10.254.100.3', site_id='allocation-site-cmdb',
        observed_at='2026-11-05T11:00:00+00:00',
    )

    details = get_next_available_ip_details(subnet['id'])
    assert details == {'next_available_ip': '10.254.100.2', 'pending_discovery_count': 1}
    assert allocate_next_address(subnet['id'])['address'] == '10.254.100.2'
    # Only the latest successful interface generation remains in the current
    # page view; the prior generation's .2 is no longer a pending reservation.
    assert get_next_available_ip_details(subnet['id']) == {
        'next_available_ip': '10.254.100.4', 'pending_discovery_count': 1,
    }


@pytest.mark.parametrize(('tenant_id', 'site_id'), [
    ('tenant-default', None),
    ('tenant-default', 'allocation-site-cmdb-other'),
    ('tenant-other', 'allocation-site-cmdb-scope'),
])
def test_cmdb_interface_pending_requires_matching_tenant_and_site(isolated_db, tenant_id, site_id) -> None:
    del isolated_db
    subnet = _create_test_prefix(site_id='allocation-site-cmdb-scope')
    _publish_cmdb_interface_ip(
        'device-cmdb-unscoped', '10.254.100.2', site_id=site_id, tenant_id=tenant_id,
    )

    assert get_next_available_ip_details(subnet['id']) == {
        'next_available_ip': '10.254.100.2', 'pending_discovery_count': 0,
    }


def test_unmapped_vrf_label_stays_pending_in_matching_site(isolated_db) -> None:
    del isolated_db
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO vrfs(id, vrf_name, tenant_id) VALUES ('target-vrf', 'TARGET-VRF', 'tenant-default')"
        )
        conn.execute(
            "INSERT INTO vrfs(id, vrf_name, tenant_id) VALUES ('foreign-vrf', 'FOREIGN-VRF', 'tenant-default')"
        )
        conn.commit()
    subnet = _create_test_prefix(
        prefix='10.254.110.0/29', gateway='10.254.110.1', vrf_id='target-vrf',
        site_id='allocation-site-target-vrf',
    )
    _insert_endpoint(
        '10.254.110.2', device_id='device-foreign-vrf', site_id='allocation-site-target-vrf',
        vrf='FOREIGN-VRF',
    )

    assert get_next_available_ip_details(subnet['id']) == {
        'next_available_ip': '10.254.110.3', 'pending_discovery_count': 1,
    }
    assert allocate_next_address(subnet['id'])['address'] == '10.254.110.3'


def test_unmapped_vrf_label_does_not_reserve_across_sites(isolated_db) -> None:
    del isolated_db
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO vrfs(id, vrf_name, tenant_id) VALUES ('shared-vrf', 'SHARED-VRF', 'tenant-default')"
        )
        for site_id in ('allocation-site-a', 'allocation-site-b'):
            conn.execute(
                "INSERT INTO sites(id, site_code, site_name) VALUES (?, ?, ?)",
                (site_id, site_id.upper(), site_id),
            )
        conn.commit()
    subnet = _create_test_prefix(
        prefix='10.254.120.0/29', gateway='10.254.120.1', vrf_id='shared-vrf',
        site_id='allocation-site-a',
    )
    _insert_endpoint(
        '10.254.120.2', device_id='device-shared-vrf-site-b', site_id='allocation-site-b',
        vrf='SHARED-VRF',
    )

    assert get_next_available_ip_details(subnet['id']) == {
        'next_available_ip': '10.254.120.2', 'pending_discovery_count': 0,
    }


def test_manual_inventory_keeps_observed_endpoint_fields_out_of_ledger_owner(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix()
    with get_db_connection() as conn:
        conn.execute(
            '''INSERT INTO physical_assets (
                   id, asset_type, asset_tag, serial_number, vendor, model, hostname,
                   management_ip, business_ip, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                'asset-observed-switch-001', 'network_device', 'OBS-SW-001', 'SN-OBS-001',
                'H3C', 'S6850', 'observed-switch', '10.254.100.254', '',
                '2026-09-02T00:00:00+00:00', '2026-09-02T00:00:00+00:00',
            ),
        )
        conn.execute(
            '''INSERT INTO devices (id, asset_id, hostname, tenant_id, status)
               VALUES (?, ?, ?, ?, ?)''',
            ('device-observed-switch-001', 'asset-observed-switch-001', 'observed-switch', 'tenant-default', 'online'),
        )
        conn.commit()
    _insert_endpoint(
        '10.254.100.2', device_id='device-observed-switch-001', vrf='global',
        hostname='observed-client', mac='00:AA:BB:CC:DD:EE', switch_port='GigabitEthernet1/0/24',
        create_device=False,
    )
    registered = create_address(
        subnet['id'], address='10.254.100.2',
        hostname='', device_id='', interface_id='', interface_name='', mac_address='',
    )

    inventory = list_ip_inventory(prefix_id=subnet['id'], page=1, page_size=20)
    items = [item for item in inventory['items'] if item['id'] == registered['id']]
    assert len(items) == 1
    item = items[0]
    assert item['source'] == 'manual'
    assert item['device_id'] is None
    assert item['interface_id'] is None
    assert item['interface_name'] == ''
    assert item['mac_address'] == ''
    assert item['hostname'] == ''
    assert item.get('linked_asset_id') in ('', None)
    assert item.get('asset_tag') in ('', None)
    all_current = list_ip_inventory(q='10.254.100.2')['items']
    discovered = next(row for row in all_current if row['is_discovered'])
    assert discovered['scope_status'] == 'scope_pending'
    assert discovered['subnet_id'] == ''
    assert discovered['hostname'] == 'observed-client'
    assert discovered['mac_address'] == '00:AA:BB:CC:DD:EE'
    assert discovered['switch_port'] == 'GigabitEthernet1/0/24'
    assert discovered['linked_asset_id'] == ''
    assert discovered['asset_tag'] == ''
    assert discovered['observed_linked_asset_id'] == 'asset-observed-switch-001'
    assert discovered['observed_asset_tag'] == 'OBS-SW-001'


def test_inventory_surfaces_the_asset_linked_to_a_device(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix()

    with get_db_connection() as conn:
        conn.execute(
            '''INSERT INTO physical_assets (
                   id, asset_type, asset_tag, serial_number, vendor, model, hostname,
                   management_ip, business_ip, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                'asset-ipam-link-001', 'network_device', 'SW-EDGE-001', 'SN-EDGE-001',
                'H3C', 'S6850', 'edge-sw-01', '10.254.100.2', '',
                '2026-09-02T00:00:00+00:00', '2026-09-02T00:00:00+00:00',
            ),
        )
        conn.execute(
            '''INSERT INTO devices (id, asset_id, hostname, ip_address, status, site)
               VALUES (?, ?, ?, ?, ?, ?)''',
            ('device-ipam-link-001', 'asset-ipam-link-001', 'edge-sw-01', '10.254.100.2', 'pending', 'test-site'),
        )
        conn.commit()

    create_address(
        subnet['id'],
        address='10.254.100.2',
        device_id='device-ipam-link-001',
        device_type='device',
        purpose='management',
    )

    inventory = list_ip_inventory(prefix_id=subnet['id'], q='SW-EDGE-001', page=1, page_size=20)

    assert len(inventory['items']) == 1
    assert inventory['items'][0]['linked_asset_id'] == 'asset-ipam-link-001'
    assert inventory['items'][0]['asset_tag'] == 'SW-EDGE-001'
    assert inventory['items'][0]['asset_serial_number'] == 'SN-EDGE-001'

    device_candidates = read_devices(
        mode='light',
        search='SW-EDGE-001',
        platform=None,
        role=None,
        role_exact=False,
        status=None,
        site=None,
        vendor=None,
        device_category=None,
        sort_key=None,
        sort_direction='asc',
        page=None,
        page_size=None,
        include_facets=False,
        asset_type='all',
    )
    assert len(device_candidates) == 1
    assert device_candidates[0]['id'] == 'device-ipam-link-001'
    assert device_candidates[0]['asset_tag'] == 'SW-EDGE-001'
    assert device_candidates[0]['asset_serial_number'] == 'SN-EDGE-001'


@pytest.mark.parametrize('prefix, addresses', [
    ('10.254.101.0/31', ('10.254.101.0', '10.254.101.1')),
    ('10.254.102.10/32', ('10.254.102.10',)),
])
def test_point_to_point_and_host_prefixes_keep_all_addresses_allocatable(isolated_db, prefix, addresses) -> None:
    del isolated_db
    subnet = _create_test_prefix(prefix=prefix, gateway='')

    for address in addresses:
        result = create_address(
            subnet['id'],
            address=address,
            purpose='transit' if len(addresses) == 2 else 'loopback',
            device_type='transit' if len(addresses) == 2 else 'loopback',
        )
        assert result['address'] == address


@pytest.mark.parametrize(('prefix', 'expected'), [
    ('2001:db8:100::/64', '2001:db8:100::1'),
    ('2001:db8:101::/127', '2001:db8:101::'),
    ('2001:db8:102::1/128', '2001:db8:102::1'),
])
def test_ipv6_suggestion_and_allocation_use_identical_candidate_bounds(
    isolated_db, prefix: str, expected: str,
) -> None:
    del isolated_db
    subnet = _create_test_prefix(prefix=prefix, gateway='')

    assert get_next_available_ip(subnet['id']) == expected
    allocated = allocate_next_address(subnet['id'])
    assert allocated['address'] == expected


def test_ipv6_64_first_free_search_does_not_iterate_the_network(monkeypatch) -> None:
    def reject_network_iteration(_network):
        pytest.fail('first-free selection must not enumerate IPv6 addresses')

    monkeypatch.setattr(ipaddress.IPv6Network, '__iter__', reject_network_iteration)
    network = ipaddress.ip_network('2001:db8:ffff::/64')

    assert _first_free_address(network, set()) == '2001:db8:ffff::1'


def test_first_free_address_searches_past_ten_thousand_occupied_hosts() -> None:
    network = ipaddress.ip_network('10.21.0.0/16')
    first_host = int(network.network_address) + 1
    occupied = {
        str(ipaddress.ip_address(first_host + offset))
        for offset in range(10000)
    }

    assert _first_free_address(network, occupied) == '10.21.39.17'


def test_next_available_ip_service_finds_free_host_after_ten_thousand_records(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix(prefix='10.24.0.0/16', gateway='')
    network = ipaddress.ip_network(subnet['prefix'])
    rows = []
    for offset in range(1, 10001):
        address = str(ipaddress.ip_address(int(network.network_address) + offset))
        rows.append((
            f'a15-address-{offset:05d}', subnet['id'], address, address,
            subnet['address_space_id'], 'tenant-default', '', 'active', 'now', 'now',
        ))
    with get_db_connection() as conn:
        conn.executemany(
            """INSERT INTO ip_addresses
                   (id, subnet_id, address, address_inet, address_space_id,
                    tenant_id, site_id, status, created_at, updated_at)
               VALUES (?, ?, ?, ?::inet, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()

    assert get_next_available_ip(subnet['id']) == '10.24.39.17'


def test_first_available_child_prefix_searches_past_one_thousand_occupied_subnets() -> None:
    parent = ipaddress.ip_network('2001:db8:100::/48')
    existing = list(parent.subnets(new_prefix=64))[:1000]

    assert _first_available_child_prefix(parent, 64, existing) == '2001:db8:100:3e8::/64'


def test_first_available_child_prefix_skips_ranges_inside_an_existing_child() -> None:
    parent = ipaddress.ip_network('10.22.0.0/24')
    existing = [ipaddress.ip_network('10.22.0.0/25')]

    assert _first_available_child_prefix(parent, 26, existing) == '10.22.0.128/26'


def test_next_available_prefix_finds_child_after_one_thousand_existing_prefixes(isolated_db) -> None:
    del isolated_db
    parent = _create_test_prefix(prefix='10.23.0.0/16', gateway='')
    parent_net = ipaddress.ip_network(parent['prefix'])
    occupied_children = list(parent_net.subnets(new_prefix=26))[:1000]
    with get_db_connection() as conn:
        for index, child in enumerate(occupied_children):
            cidr = str(child)
            conn.execute(
                """INSERT INTO prefixes
                       (id, prefix, prefix_cidr, address_space_id, vrf_id, site_id,
                        tenant_id, status, name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, NULL, NULL, 'tenant-default', 'active', '', 'now', 'now')""",
                (f'a15-existing-child-{index:04d}', cidr, cidr, parent['address_space_id']),
            )
        conn.commit()

    assert get_next_available_prefix(parent['id'], 26) == '10.23.250.0/26'


def test_manual_create_and_reserve_reject_cidr_suffixed_host(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix(gateway='')

    with pytest.raises(ValueError, match='without a CIDR prefix length'):
        create_address(subnet['id'], address='10.254.100.3/29')
    with pytest.raises(ValueError, match='without a CIDR prefix length'):
        reserve_address(subnet['id'], address='10.254.100.4/29')
    with pytest.raises(ValidationError, match='host IP without a CIDR prefix length'):
        ReservationRequest(address='2001:db8::1/64')


def test_manual_registration_can_claim_pending_observed_host(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix(site_id='manual-claim-site')
    _insert_endpoint(
        '10.254.100.2', device_id='manual-claim-edge', vrf='unknown-vrf',
        site_id='manual-claim-site',
    )

    suggestion = get_next_available_ip_details(subnet['id'])
    assert suggestion['next_available_ip'] == '10.254.100.3'
    assert suggestion['pending_discovery_count'] == 1

    registered = create_address(
        subnet['id'], address='10.254.100.2', device_type='server', purpose='business',
    )
    assert registered['address'] == '10.254.100.2'
    assert get_next_available_ip(subnet['id']) == '10.254.100.3'


def test_manual_address_cannot_reuse_gateway_from_another_prefix_in_same_space(isolated_db) -> None:
    del isolated_db
    parent = _create_test_prefix(prefix='10.254.103.0/24', gateway='10.254.103.1')
    child = create_subnet(
        prefix='10.254.103.64/26',
        address_space_id=_test_global_space_id(),
        gateway='10.254.103.70',
        network_type='management',
        name='IPAM allocation policy child prefix',
    )

    with pytest.raises(ValueError, match='Gateway address 10.254.103.70'):
        create_address(
            parent['id'], address='10.254.103.70', device_type='server', purpose='business',
        )
    with pytest.raises(ValueError, match='Gateway address 10.254.103.70'):
        create_address(
            parent['id'], address='10.254.103.70', device_type='gateway', purpose='gateway',
        )

    gateway = create_address(
        child['id'], address='10.254.103.70', device_type='gateway', purpose='infrastructure',
    )
    assert gateway['address'] == '10.254.103.70'


def test_invalid_configured_gateway_is_not_reserved(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix(prefix='10.254.104.0/24', gateway='10.254.104.0')

    with get_db_connection() as conn:
        prefix_row = conn.execute(
            'SELECT * FROM prefixes WHERE id = ?', (subnet['id'],)
        ).fetchone()
        assert _space_gateway_reservations(
            conn, prefix_row, ipaddress.ip_network(subnet['prefix']),
        ) == set()


def test_released_address_is_blocked_until_quarantine_expires(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix(prefix='10.254.105.0/29', gateway='10.254.105.1')
    created = create_address(subnet['id'], address='10.254.105.3')

    assert release_address(created['id'], expected_revision=1)
    with pytest.raises(ValueError, match='quarantined until'):
        create_address(subnet['id'], address='10.254.105.3')

    with get_db_connection() as conn:
        released = conn.execute(
            'SELECT status, available_after FROM ip_addresses WHERE id = ?', (created['id'],),
        ).fetchone()
        conn.execute(
            "UPDATE ip_addresses SET available_after = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (created['id'],),
        )
        conn.commit()
    assert released['status'] == 'released'

    reused = create_address(subnet['id'], address='10.254.105.3')
    assert reused['id'] == created['id']
    assert reused['status'] == 'active'
