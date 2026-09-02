from __future__ import annotations

import pytest

from api.devices import read_devices
from database import get_db_connection
from services.ipam_service import (
    allocate_next_address,
    create_address,
    create_subnet,
    get_next_available_ip,
    list_ip_inventory,
)


def _create_test_prefix(*, prefix: str = '10.254.100.0/29', gateway: str = '10.254.100.1') -> dict:
    return create_subnet(
        prefix=prefix,
        gateway=gateway,
        network_type='management',
        name='IPAM allocation policy test prefix',
    )


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


def test_suggestions_and_auto_allocation_skip_active_discovered_endpoints(isolated_db) -> None:
    del isolated_db
    subnet = _create_test_prefix()

    with get_db_connection() as conn:
        conn.execute(
            '''INSERT INTO network_endpoints (
                   id, ip, mac, switch_id, switch_port, first_seen, last_seen, is_active
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                'endpoint-ipam-occupied-001', '10.254.100.2', '00:11:22:33:44:55',
                'device-edge-001', 'GigabitEthernet1/0/1',
                '2026-09-02T00:00:00+00:00', '2026-09-02T00:00:00+00:00', 1,
            ),
        )
        conn.commit()

    assert get_next_available_ip(subnet['id']) == '10.254.100.3'

    allocated = allocate_next_address(
        subnet['id'],
        device_type='server',
        purpose='business',
        hostname='app-01',
        status='active',
    )
    assert allocated['address'] == '10.254.100.3'


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
        status=None,
        sort_key=None,
        sort_direction='asc',
        page=None,
        page_size=None,
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
