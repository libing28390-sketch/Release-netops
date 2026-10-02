from __future__ import annotations

import pytest
import ipaddress

from database import get_db_connection
from services.ipam_service import create_address, create_subnet, get_ipam_reconciliation, list_ip_inventory
from services.ipam_inventory_scope import manual_address_key, match_inventory_prefix


def _seed_scope(*, tenant: str = 'tenant-default', site: str = 'site-scope-a', vrf: str = 'vrf-scope-a', vrf_name: str = 'BLUE') -> None:
    with get_db_connection() as conn:
        conn.execute('INSERT INTO tenants (id, name) VALUES (?, ?) ON CONFLICT(id) DO NOTHING', (tenant, tenant))
        conn.execute(
            'INSERT INTO sites (id, site_code, site_name) VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING',
            (site, site.upper(), f'站点 {site}'),
        )
        if vrf:
            conn.execute(
                'INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING',
                (vrf, vrf_name, tenant),
            )
        conn.commit()


def _device(*, tenant: str = 'tenant-default', site: str = 'site-scope-a', device_id: str = 'device-scope') -> None:
    with get_db_connection() as conn:
        conn.execute(
            'INSERT INTO devices (id, hostname, tenant_id, site_id, status) VALUES (?, ?, ?, ?, ?)',
            (device_id, 'SW-NAME-IS-NOT-A-SITE', tenant, site, 'online'),
        )
        conn.commit()


def _endpoint(*, address: str = '10.254.120.10', vrf: str = 'BLUE', site: str = 'SW-NAME-IS-NOT-A-SITE', device: str = 'device-scope', hostname: str = 'observed-host') -> None:
    with get_db_connection() as conn:
        conn.execute(
            '''INSERT INTO network_endpoints
                   (id, ip, mac, hostname, switch_id, switch_port, vrf, site, first_seen, last_seen, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)''',
            (f'endpoint-{address}', address, '00:11:22:33:44:55', hostname, device, 'Ethernet1', vrf, site,
             '2026-10-02T00:00:00+00:00', '2026-10-02T00:00:00+00:00'),
        )
        conn.commit()


def _prefix(*, tenant: str = 'tenant-default', site: str = 'site-scope-a', vrf: str = 'vrf-scope-a', prefix: str = '10.254.120.0/24') -> dict:
    return create_subnet(prefix=prefix, tenant_id=tenant, vrf_id=vrf or None, site_id=site or None)


@pytest.mark.parametrize('observed_vrf', ['BLUE', 'vrf-scope-a'])
def test_same_ip_in_two_vrfs_is_preserved_and_only_matching_scope_is_enriched(isolated_db, observed_vrf) -> None:
    _seed_scope()
    _seed_scope(site='site-scope-b', vrf='vrf-scope-b', vrf_name='RED')
    _device()
    first = create_address(_prefix()['id'], address='10.254.120.10')
    second = create_address(_prefix(site='site-scope-b', vrf='vrf-scope-b')['id'], address='10.254.120.10')
    _endpoint(vrf=observed_vrf)

    inventory = list_ip_inventory(q='10.254.120.10')
    items = {item['id']: item for item in inventory['items']}
    assert inventory['total'] == 2
    assert set(items) == {first['id'], second['id']}
    assert items[first['id']]['source'] == 'manual+discovered'
    assert items[first['id']]['hostname'] == 'observed-host'
    assert items[first['id']]['site_name'] == '站点 site-scope-a'
    assert items[second['id']]['source'] == 'manual'
    assert items[second['id']]['hostname'] == ''
    assert items[second['id']]['mac_address'] == ''
    assert list_ip_inventory(prefix_id=items[second['id']]['subnet_id'])['total'] == 1
    # Query enrichment must never write discovered fields into authoritative rows.
    with get_db_connection() as conn:
        assert conn.execute('SELECT hostname FROM ip_addresses WHERE id = ?', (first['id'],)).fetchone()['hostname'] == ''


def test_reconciliation_preserves_both_vrf_records_and_finding_identity(isolated_db) -> None:
    _seed_scope()
    _seed_scope(vrf='vrf-scope-b', vrf_name='RED')
    _device()
    first = create_address(_prefix()['id'], address='10.254.120.10', hostname='documented-a')
    second = create_address(_prefix(vrf='vrf-scope-b')['id'], address='10.254.120.10', hostname='documented-b')

    empty_observation = get_ipam_reconciliation()
    assert {item['id'] for item in empty_observation['stale_ip_addresses']} == {first['id'], second['id']}
    _endpoint()
    result = get_ipam_reconciliation()
    assert [item['id'] for item in result['stale_ip_addresses']] == [second['id']]
    assert [item['ipam_address_id'] for item in result['mismatched_endpoints']] == [first['id']]
    assert result['undocumented_endpoints'] == []
    paginated = get_ipam_reconciliation(active_tab='stale', page=1, page_size=1)
    assert paginated['result_total'] == 1
    assert paginated['stale_ip_addresses'][0]['id'] == second['id']


def test_same_vrf_name_in_two_tenants_does_not_merge_addresses(isolated_db) -> None:
    _seed_scope(tenant='tenant-scope-a', vrf='vrf-tenant-a')
    _seed_scope(tenant='tenant-scope-b', site='site-scope-b', vrf='vrf-tenant-b')
    _device(tenant='tenant-scope-b', site='site-scope-b')
    first = create_address(_prefix(tenant='tenant-scope-a', vrf='vrf-tenant-a')['id'], address='10.254.120.10')
    second = create_address(_prefix(tenant='tenant-scope-b', site='site-scope-b', vrf='vrf-tenant-b')['id'], address='10.254.120.10')
    _endpoint()

    items = {item['id']: item for item in list_ip_inventory()['items']}
    assert items[first['id']]['source'] == 'manual'
    assert items[second['id']]['source'] == 'manual+discovered'
    assert [item['id'] for item in get_ipam_reconciliation()['stale_ip_addresses']] == [first['id']]


@pytest.mark.parametrize('observed_vrf', ['', 'UNKNOWN-VRF'])
def test_unknown_or_global_observation_does_not_merge_named_vrf_records(isolated_db, observed_vrf) -> None:
    _seed_scope()
    _seed_scope(vrf='vrf-scope-b', vrf_name='RED')
    _device()
    first = create_address(_prefix()['id'], address='10.254.120.10')
    second = create_address(_prefix(vrf='vrf-scope-b')['id'], address='10.254.120.10')
    _endpoint(vrf=observed_vrf)

    inventory = list_ip_inventory()
    assert inventory['total'] == 3
    assert all(item['source'] == 'manual' for item in inventory['items'] if item['id'] in (first['id'], second['id']))
    discovered = next(item for item in inventory['items'] if item['is_discovered'])
    assert discovered['subnet_id'] == ''
    result = get_ipam_reconciliation()
    assert len(result['stale_ip_addresses']) == 2
    assert len(result['undocumented_endpoints']) == 1
    assert result['undocumented_endpoints'][0]['subnet_id'] == ''


def test_longest_prefix_match_stays_in_endpoint_vrf(isolated_db) -> None:
    _seed_scope()
    _seed_scope(vrf='vrf-scope-b', vrf_name='RED')
    _device()
    correct = _prefix()
    wrong = _prefix(vrf='vrf-scope-b', prefix='10.254.120.0/25')
    _endpoint()

    item = list_ip_inventory()['items'][0]
    assert item['subnet_id'] == correct['id']
    assert list_ip_inventory(prefix_id=wrong['id'])['total'] == 0
    assert get_ipam_reconciliation()['undocumented_endpoints'][0]['subnet_id'] == correct['id']


def test_legacy_endpoint_hostname_site_is_resolved_through_live_cmdb(isolated_db) -> None:
    _seed_scope()
    _seed_scope(site='site-scope-b', vrf='vrf-scope-b', vrf_name='RED')
    _device()
    _endpoint(address='203.0.113.50')
    item = list_ip_inventory()['items'][0]
    assert (item['site_id'], item['site_name']) == ('site-scope-a', '站点 site-scope-a')
    assert item['subnet_id'] == ''
    assert get_ipam_reconciliation()['undocumented_endpoints'][0]['site'] == '站点 site-scope-a'

    with get_db_connection() as conn:
        conn.execute('UPDATE devices SET site_id = ? WHERE id = ?', ('site-scope-b', 'device-scope'))
        conn.commit()
    assert list_ip_inventory()['items'][0]['site_name'] == '站点 site-scope-b'
    with get_db_connection() as conn:
        conn.execute('UPDATE devices SET site_id = ?, site = ? WHERE id = ?', ('', '', 'device-scope'))
        conn.commit()
    item = list_ip_inventory()['items'][0]
    assert item['site_id'] == ''
    assert item['site_name'] == '未分配站点'


def test_unassigned_device_does_not_inherit_stale_cached_site(isolated_db) -> None:
    _seed_scope()
    _device(site='')
    _endpoint(address='203.0.113.50', site='site-scope-a')
    item = list_ip_inventory()['items'][0]
    assert item['site_id'] == ''
    assert item['site_name'] == '未分配站点'


def test_orphan_endpoint_never_uses_switch_name_as_site(isolated_db) -> None:
    _endpoint(address='203.0.113.50', device='deleted-switch')
    item = list_ip_inventory()['items'][0]
    assert item['site_id'] == ''
    assert item['site_name'] == '未分配站点'


def test_orphan_endpoint_cannot_assume_default_tenant_and_enrich_same_ip(isolated_db) -> None:
    _seed_scope()
    _seed_scope(tenant='tenant-other', site='site-scope-b', vrf='vrf-other')
    first = create_address(_prefix()['id'], address='10.254.120.10')
    second = create_address(_prefix(tenant='tenant-other', site='site-scope-b', vrf='vrf-other')['id'], address='10.254.120.10')
    _endpoint(device='deleted-switch')
    inventory = list_ip_inventory()
    items = {item['id']: item for item in inventory['items']}
    assert items[first['id']]['source'] == items[second['id']]['source'] == 'manual'
    discovered = next(item for item in inventory['items'] if item['is_discovered'])
    assert discovered['tenant_id'] == ''
    assert discovered['subnet_id'] == ''
    assert get_ipam_reconciliation()['summary'] == {
        'total_undocumented': 1, 'total_stale': 2, 'total_mismatched': 0,
    }


def test_missing_parent_keeps_address_vrf_while_global_parent_remains_global() -> None:
    row = {'address': '192.0.2.10', 'tenant_id': 'tenant-a', 'vrf_id': 'vrf-a', 'prefix_vrf_id': None}
    assert manual_address_key(row) == ('tenant-a', 'vrf-a', '192.0.2.10')
    row['subnet_prefix'] = '192.0.2.0/24'
    assert manual_address_key(row) == ('tenant-a', '', '192.0.2.10')


def test_prefix_with_invalid_site_assignment_is_not_treated_as_site_independent() -> None:
    prefix = {
        'tenant_id': 'tenant-default', 'vrf_id': '', 'site_id': '',
        'invalid_site_assignment': True, 'network': ipaddress.ip_network('192.0.2.0/24'),
    }
    assert match_inventory_prefix('192.0.2.10', ('tenant-default', '', '192.0.2.10'), 'site-a', [prefix]) is None


def test_linked_asset_site_is_used_as_canonical_placement(isolated_db) -> None:
    _seed_scope()
    _seed_scope(site='site-scope-b', vrf='vrf-scope-b', vrf_name='RED')
    _device()
    with get_db_connection() as conn:
        conn.execute(
            '''INSERT INTO physical_assets (id, asset_type, site_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)''',
            ('asset-scope', 'network_device', 'site-scope-b', '2026-10-02', '2026-10-02'),
        )
        conn.execute('UPDATE devices SET asset_id = ? WHERE id = ?', ('asset-scope', 'device-scope'))
        conn.commit()
    _endpoint(address='203.0.113.50')
    item = list_ip_inventory()['items'][0]
    assert (item['site_id'], item['site_name']) == ('site-scope-b', '站点 site-scope-b')


def test_equal_prefixes_without_known_site_are_not_assigned_arbitrarily(isolated_db) -> None:
    _seed_scope()
    _seed_scope(site='site-scope-b')
    _device(site='')
    _prefix()
    _prefix(site='site-scope-b')
    _endpoint()
    item = list_ip_inventory()['items'][0]
    assert item['subnet_id'] == ''
    assert item['site_id'] == ''
    assert get_ipam_reconciliation()['undocumented_endpoints'][0]['subnet_id'] == ''


def test_ipv6_scoped_matching_normalizes_address_text(isolated_db) -> None:
    _seed_scope()
    _device()
    subnet = _prefix(prefix='2001:db8:1234::/64')
    manual = create_address(subnet['id'], address='2001:db8:1234::10')
    _endpoint(address='2001:0db8:1234:0000:0000:0000:0000:0010')
    inventory = list_ip_inventory()
    assert inventory['total'] == 1
    assert inventory['items'][0]['id'] == manual['id']
    assert inventory['items'][0]['source'] == 'manual+discovered'
    assert get_ipam_reconciliation()['summary']['total_stale'] == 0


def test_empty_inventory_and_reconciliation_keep_response_shape(isolated_db) -> None:
    assert list_ip_inventory()['total'] == 0
    assert get_ipam_reconciliation()['summary'] == {
        'total_undocumented': 0, 'total_stale': 0, 'total_mismatched': 0,
    }
