from __future__ import annotations

import pytest
import ipaddress
import hashlib
import json
from datetime import datetime, timedelta, timezone

from database import get_db_connection
from services.ipam_address_space_service import create_address_space
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


def _endpoint(*, address: str = '10.254.120.10', vrf: str = 'BLUE', site: str = 'SW-NAME-IS-NOT-A-SITE', device: str = 'device-scope', hostname: str = 'observed-host', seen_at: datetime | None = None, vrf_context: str | None = None) -> None:
    observed_at = (seen_at or datetime.now(timezone.utc)).isoformat()
    observed_ip = str(ipaddress.ip_address(address))
    source_version = f'test:{device}:{observed_ip}:{vrf}:{observed_at}'
    snapshot_id = f'snapshot-{hashlib.sha256(source_version.encode()).hexdigest()[:24]}'
    observation_id = f'observation-{hashlib.sha256((source_version + hostname).encode()).hexdigest()[:24]}'
    with get_db_connection() as conn:
        conn.execute(
            '''INSERT INTO network_endpoints
                   (id, ip, mac, hostname, switch_id, switch_port, vrf, site, first_seen, last_seen, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)''',
            (f'endpoint-{address}-{vrf}-{device}', address, '00:11:22:33:44:55', hostname, device, 'Ethernet1', vrf, site,
            observed_at, observed_at),
        )
        device_row = conn.execute(
            '''SELECT d.id, d.hostname, d.tenant_id, d.site_id, d.site, pa.site_id AS asset_site_id
                 FROM devices d LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                WHERE d.id = ?''',
            (device,),
        ).fetchone()
        tenant_id = str(device_row['tenant_id'] or 'tenant-default') if device_row else None
        site_id = str((device_row['asset_site_id'] or device_row['site_id'] or '') if device_row else '')
        vrf_id = ''
        vrf_context_status = vrf_context or 'unknown'
        if vrf_context_status == 'auto' or (vrf_context is None and vrf):
            vrf_row = conn.execute(
                'SELECT id FROM vrfs WHERE tenant_id = ? AND (id = ? OR vrf_name = ?)',
                (tenant_id or 'tenant-default', vrf, vrf),
            ).fetchone() if device_row else None
            if vrf_row:
                vrf_id = str(vrf_row['id'])
                vrf_context_status = 'explicit_vrf'
            else:
                vrf_context_status = 'unknown'
        elif vrf_context_status in {'global', 'explicit_global'}:
            vrf_context_status = 'explicit_global'
        else:
            vrf_context_status = 'unknown'
        scope_status = 'resolved' if device_row and site_id and tenant_id and vrf_context_status in {'explicit_vrf', 'explicit_global'} else 'scope_pending'
        if not site_id:
            tenant_id = None
        identity = hashlib.sha256(json.dumps([
            'arp', device, tenant_id, site_id or None, vrf_id if vrf_context_status == 'explicit_global' else vrf_id or None,
            observed_ip, '00:11:22:33:44:55', 'Ethernet1', '100', vrf_context_status, scope_status,
        ], separators=(',', ':')).encode()).hexdigest()
        source_device_name = str(device_row['hostname'] or device) if device_row else device
        projected_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            '''INSERT INTO ipam_discovery_snapshots (
                   id, collector, device_id, source_device_name, tenant_id, site_id, vrf_id,
                   vrf_context_status, scope_status, source_run_id, source_version,
                   source_status, coverage_status, coverage_complete, coverage_reason,
                   entry_count, observed_at, projected_at
               ) VALUES (?, 'arp', ?, ?, ?, ?, ?, ?, ?, '', ?, 'success', 'unavailable', 0,
                         'test_positive_only', 1, ?, ?)''',
            (snapshot_id, device, source_device_name, tenant_id, site_id or None,
             vrf_id if vrf_context_status == 'explicit_global' else vrf_id or None,
             vrf_context_status, scope_status, source_version, observed_at, projected_at),
        )
        conn.execute(
            '''INSERT INTO ipam_discovery_observations (
                   id, snapshot_id, source_type, source_device_id, source_device_name,
                   tenant_id, site_id, vrf_id, vrf_context_status, scope_status,
                   ip, mac, interface_name, vlan, source_identity_key,
                   source_observed_at, timestamp_status, projected_at
               ) VALUES (?, ?, 'arp', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Ethernet1', '100', ?, ?, 'valid', ?)''',
            (observation_id, snapshot_id, device, source_device_name, tenant_id, site_id or None,
             vrf_id if vrf_context_status == 'explicit_global' else vrf_id or None, vrf_context_status,
             scope_status, observed_ip, '00:11:22:33:44:55', identity, observed_at, projected_at),
        )
        conn.commit()


def _global_space_id(tenant: str = 'tenant-default') -> str:
    name = f'Inventory Scope Test Global {tenant}'
    with get_db_connection() as conn:
        row = conn.execute(
            'SELECT id FROM ipam_address_spaces WHERE security_tenant_id = ? AND name = ? AND kind = ? LIMIT 1',
            (tenant, name, 'global'),
        ).fetchone()
    if row:
        return str(row['id'])
    return str(create_address_space(
        name=name,
        kind='global',
        vrf_id=None,
        security_tenant_id=tenant,
    )['id'])


def _prefix(*, tenant: str = 'tenant-default', site: str = 'site-scope-a', vrf: str = 'vrf-scope-a', prefix: str = '10.254.120.0/24') -> dict:
    return create_subnet(
        prefix=prefix,
        tenant_id=tenant,
        vrf_id=vrf or None,
        address_space_id=None if vrf else _global_space_id(tenant),
        site_id=site or None,
    )


@pytest.mark.parametrize('observed_vrf', ['BLUE', 'vrf-scope-a'])
def test_same_ip_vrf_name_without_device_mapping_remains_unscoped(isolated_db, observed_vrf) -> None:
    _seed_scope()
    _seed_scope(site='site-scope-b', vrf='vrf-scope-b', vrf_name='RED')
    _device()
    first = create_address(_prefix()['id'], address='10.254.120.10')
    second = create_address(_prefix(site='site-scope-b', vrf='vrf-scope-b')['id'], address='10.254.120.10')
    _endpoint(vrf=observed_vrf)

    inventory = list_ip_inventory(q='10.254.120.10')
    items = {item['id']: item for item in inventory['items']}
    assert inventory['total'] == 3
    assert items[first['id']]['source'] == items[second['id']]['source'] == 'manual'
    assert items[second['id']]['hostname'] == ''
    assert items[second['id']]['mac_address'] == ''
    discovered = next(item for item in inventory['items'] if item['is_discovered'])
    assert discovered['scope_status'] == 'scope_pending'
    assert discovered['address_space_id'] == ''
    assert discovered['subnet_id'] == ''
    assert discovered['hostname'] == 'observed-host'
    assert discovered['device_id'] == 'device-scope'
    assert discovered['interface_name'] == 'Ethernet1'
    assert discovered['mac_address'] == '00:11:22:33:44:55'
    assert discovered['switch_name'] == 'SW-NAME-IS-NOT-A-SITE'
    assert discovered['switch_port'] == 'Ethernet1'
    assert discovered['site_name'] == '站点 site-scope-a'
    assert list_ip_inventory(prefix_id=items[second['id']]['subnet_id'])['total'] == 1
    # Query enrichment must never write discovered fields into authoritative rows.
    with get_db_connection() as conn:
        assert conn.execute('SELECT hostname FROM ip_addresses WHERE id = ?', (first['id'],)).fetchone()['hostname'] == ''


def test_unmapped_endpoint_cache_does_not_infer_mismatch_or_stale(isolated_db) -> None:
    _seed_scope()
    _seed_scope(vrf='vrf-scope-b', vrf_name='RED')
    _device()
    first = create_address(_prefix()['id'], address='10.254.120.10', hostname='documented-a', mac_address='00:11:22:33:44:66')
    second = create_address(_prefix(vrf='vrf-scope-b')['id'], address='10.254.120.11', hostname='documented-b')

    empty_observation = get_ipam_reconciliation()
    assert empty_observation['stale_ip_addresses'] == []
    old_observation = datetime.now(timezone.utc) - timedelta(days=8)
    _endpoint(address='10.254.120.11', vrf='RED', seen_at=old_observation)
    _endpoint()
    result = get_ipam_reconciliation()
    assert result['stale_ip_addresses'] == []
    assert result['mismatched_endpoints'] == []
    assert result['undocumented_endpoints'] == []
    assert {item['ip'] for item in result['unscoped']} == {'10.254.120.10', '10.254.120.11'}
    assert result['summary']['coverage_source_set_known'] is False
    assert [item['ipam_address_id'] for item in result['never_observed']] == []
    paginated = get_ipam_reconciliation(active_tab='unscoped', page=1, page_size=1)
    assert paginated['result_total'] == 2
    assert len(paginated['unscoped']) == 1


def test_same_vrf_name_in_two_tenants_does_not_merge_addresses(isolated_db) -> None:
    _seed_scope(tenant='tenant-scope-a', vrf='vrf-tenant-a')
    _seed_scope(tenant='tenant-scope-b', site='site-scope-b', vrf='vrf-tenant-b')
    _device(tenant='tenant-scope-b', site='site-scope-b')
    first = create_address(_prefix(tenant='tenant-scope-a', vrf='vrf-tenant-a')['id'], address='10.254.120.10')
    second = create_address(_prefix(tenant='tenant-scope-b', site='site-scope-b', vrf='vrf-tenant-b')['id'], address='10.254.120.10')
    _endpoint()

    items = {item['id']: item for item in list_ip_inventory()['items']}
    assert items[first['id']]['source'] == 'manual'
    assert items[second['id']]['source'] == 'manual'
    discovered = next(item for item in items.values() if item['is_discovered'])
    assert discovered['scope_status'] == 'scope_pending'
    assert discovered['address_space_id'] == ''
    assert get_ipam_reconciliation()['stale_ip_addresses'] == []


@pytest.mark.parametrize('observed_vrf', ['', 'UNKNOWN-VRF'])
def test_missing_or_unknown_vrf_context_does_not_merge_named_vrf_records(isolated_db, observed_vrf) -> None:
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
    assert result['stale_ip_addresses'] == []
    assert result['undocumented_endpoints'] == []
    assert result['summary']['total_unscoped'] == 1


def test_legacy_global_label_without_device_context_mapping_remains_unscoped(isolated_db) -> None:
    _seed_scope()
    _device()
    subnet = _prefix(vrf='')
    address = create_address(subnet['id'], address='10.254.120.10')

    # A legacy endpoint-cache row does not store the protocol/context_type
    # identity required to prove Global, even if its old discovery metadata
    # carries a global-looking label.
    _endpoint(address='10.254.120.10', vrf='', vrf_context='global')
    legacy_global = get_ipam_reconciliation()
    assert legacy_global['undocumented_endpoints'] == []
    assert legacy_global['summary']['active_endpoint_count'] == 1
    assert len(legacy_global['unscoped']) == 1
    assert legacy_global['unscoped'][0]['reason'] == 'routing_context_mapping_missing'

    _endpoint(address='10.254.120.20', vrf='', device='device-scope', vrf_context='unknown')
    unknown = get_ipam_reconciliation()
    assert unknown['summary']['total_unscoped'] == 2
    assert unknown['undocumented_endpoints'] == []
    assert unknown['mismatched_endpoints'] == []
    assert address['id']


@pytest.mark.parametrize('observed_vrf', ['', 'default', 'global', 'public'])
def test_unmapped_endpoint_vrf_aliases_do_not_match_global_prefix(isolated_db, observed_vrf) -> None:
    _seed_scope(vrf='')
    _device()
    _prefix(vrf='')
    seen_at = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        conn.execute(
            '''INSERT INTO network_endpoints
                   (id, ip, mac, hostname, switch_id, switch_port, vrf, site, first_seen, last_seen, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)''',
            (f"endpoint-unmapped-vrf-{observed_vrf or 'empty'}", '10.254.120.10',
             '00:11:22:33:44:55', 'observed-host', 'device-scope', 'Ethernet1',
             observed_vrf, 'site-scope-a', seen_at, seen_at),
        )
        conn.commit()

    discovered = [item for item in list_ip_inventory()['items'] if item['is_discovered']]
    assert len(discovered) == 1
    assert discovered[0]['address'] == '10.254.120.10'
    assert discovered[0]['subnet_id'] == ''
    assert discovered[0]['subnet_prefix'] == ''


def test_registered_only_ip_list_excludes_read_only_observations_and_virtual_gateway(isolated_db) -> None:
    _seed_scope()
    _device()
    subnet = create_subnet(
        prefix='10.254.120.0/24', tenant_id='tenant-default',
        site_id='site-scope-a', vrf_id='vrf-scope-a', gateway='10.254.120.1',
    )
    manual = create_address(subnet['id'], address='10.254.120.10')
    interface_generated = create_address(
        subnet['id'], address='10.254.120.11', source_type='interface_cli',
        source_ref='cmdb-generation:42', device_id='device-scope',
    )
    _endpoint(address='10.254.120.20')

    registered = list_ip_inventory(prefix_id=subnet['id'], registered_only=True)
    assert registered['total'] == 2
    assert {item['id'] for item in registered['items']} == {manual['id'], interface_generated['id']}
    assert {item.get('source_type') for item in registered['items']} == {'manual', 'interface_cli'}
    assert all(item['source'] == 'manual' and not item['is_discovered'] for item in registered['items'])
    assert all(item['address'] != '10.254.120.20' for item in registered['items'])
    assert all(item['address'] != '10.254.120.1' for item in registered['items'])


def test_endpoint_vrf_name_does_not_select_longest_prefix_without_mapping(isolated_db) -> None:
    _seed_scope()
    _seed_scope(vrf='vrf-scope-b', vrf_name='RED')
    _device()
    correct = _prefix()
    wrong = _prefix(vrf='vrf-scope-b', prefix='10.254.120.0/25')
    _endpoint()

    item = next(item for item in list_ip_inventory()['items'] if item['is_discovered'])
    assert item['subnet_id'] == ''
    assert item['scope_status'] == 'scope_pending'
    assert list_ip_inventory(prefix_id=wrong['id'])['total'] == 0
    assert correct['address_space_id'] != wrong['address_space_id']


def test_legacy_endpoint_hostname_site_is_resolved_through_live_cmdb(isolated_db) -> None:
    _seed_scope()
    _seed_scope(site='site-scope-b', vrf='vrf-scope-b', vrf_name='RED')
    _device()
    _endpoint(address='203.0.113.50')
    item = list_ip_inventory()['items'][0]
    assert (item['site_id'], item['site_name']) == ('site-scope-a', '站点 site-scope-a')
    assert item['subnet_id'] == ''
    reconciliation = get_ipam_reconciliation()
    assert reconciliation['undocumented_endpoints'] == []
    pending = next(item for item in reconciliation['unscoped'] if item['ip'] == '203.0.113.50')
    assert pending['site_id'] == 'site-scope-a'
    assert pending['reason'] == 'routing_context_mapping_missing'

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
    summary = get_ipam_reconciliation()['summary']
    assert {
        key: summary[key]
        for key in ('total_undocumented', 'total_stale', 'total_mismatched', 'total_unscoped')
    } == {'total_undocumented': 0, 'total_stale': 0, 'total_mismatched': 0, 'total_unscoped': 1}
    assert summary['endpoint_cache_fresh'] is False
    assert summary['latest_endpoint_seen']
    assert summary['current_window_minutes'] >= 20
    assert summary['stale_after_days'] == 0
    assert summary['coverage_source_set_known'] is False


def test_missing_parent_keeps_address_vrf_while_global_parent_remains_global() -> None:
    row = {'address': '192.0.2.10', 'tenant_id': 'tenant-a', 'vrf_id': 'vrf-a', 'prefix_vrf_id': None}
    assert manual_address_key(row) == ('tenant-a', 'legacy-vrf:vrf-a', '192.0.2.10')
    row['subnet_prefix'] = '192.0.2.0/24'
    assert manual_address_key(row) == ('tenant-a', 'legacy-unresolved', '192.0.2.10')


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
    _seed_scope(vrf='')
    _seed_scope(site='site-scope-b', vrf='')
    _device(site='')
    global_a = create_address_space(
        name='Scope Ambiguity Global A',
        kind='global',
        vrf_id=None,
        security_tenant_id='tenant-default',
    )
    global_b = create_address_space(
        name='Scope Ambiguity Global B',
        kind='global',
        vrf_id=None,
        security_tenant_id='tenant-default',
    )
    create_subnet(
        prefix='10.254.120.0/24', tenant_id='tenant-default',
        site_id='site-scope-a', address_space_id=global_a['id'],
    )
    create_subnet(
        prefix='10.254.120.0/24', tenant_id='tenant-default',
        site_id='site-scope-b', address_space_id=global_b['id'],
    )
    _endpoint(vrf='global', vrf_context='explicit_global')
    item = list_ip_inventory()['items'][0]
    assert item['subnet_id'] == ''
    assert item['site_id'] == ''
    reconciliation = get_ipam_reconciliation()
    assert reconciliation['undocumented_endpoints'] == []
    assert reconciliation['summary']['total_unscoped'] == 1


def test_ipv6_scoped_matching_normalizes_address_text(isolated_db) -> None:
    _seed_scope()
    _device()
    subnet = _prefix(prefix='2001:db8:1234::/64')
    manual = create_address(subnet['id'], address='2001:db8:1234::10')
    _endpoint(address='2001:0db8:1234:0000:0000:0000:0000:0010')
    inventory = list_ip_inventory()
    assert inventory['total'] == 2
    items = {item['id']: item for item in inventory['items']}
    assert items[manual['id']]['source'] == 'manual'
    discovered = next(item for item in inventory['items'] if item['is_discovered'])
    assert discovered['address'] == '2001:db8:1234::10'
    assert discovered['scope_status'] == 'scope_pending'
    assert get_ipam_reconciliation()['summary']['total_stale'] == 0


def test_empty_inventory_and_reconciliation_keep_response_shape(isolated_db) -> None:
    assert list_ip_inventory()['total'] == 0
    result = get_ipam_reconciliation()
    summary = result['summary']
    assert summary['ipam_address_record_count'] == 0
    assert summary['allocated_ipam_address_count'] == 0
    assert summary['active_endpoint_count'] == 0
    assert summary['interface_snapshot_ip_count'] == 0
    assert summary['total_undocumented'] == summary['total_stale'] == 0
    assert summary['total_mismatched'] == summary['total_unscoped'] == 0
    assert summary['total_never_observed'] == summary['total_unavailable'] == 0
    assert summary['endpoint_cache_fresh'] is False
    assert summary['coverage_status'] == 'no_inputs'
    assert summary['coverage_source_set_known'] is False
