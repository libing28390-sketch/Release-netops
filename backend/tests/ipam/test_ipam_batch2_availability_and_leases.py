from __future__ import annotations

import pytest

from database import get_db_connection
from services.ipam_address_space_service import create_address_space
from services.ipam_service import (
    allocate_next_address,
    audit_ipam_scope_integrity,
    create_address,
    create_lease,
    create_pool,
    create_subnet,
    get_next_available_ip_details,
    get_subnets_tree,
    get_utilization_analytics,
    list_leases,
    list_subnets,
    preview_delete_subnet,
)


def test_external_dhcp_pool_and_overlapping_prefix_availability_consistency(isolated_db) -> None:
    space = create_address_space(
        name='Batch2-Avail-Space',
        kind='global',
        vrf_id=None,
        security_tenant_id='tenant-default',
    )
    # 10.95.0.0/29 has 6 usable host IPs: .1 .. .6
    prefix = create_subnet(
        prefix='10.95.0.0/29',
        address_space_id=space['id'],
        tenant_id='tenant-default',
        network_type='user',
        name='DHCP-Full',
    )
    create_pool(
        prefix_id=prefix['id'],
        name='ext-dhcp-full',
        start_ip='10.95.0.1',
        end_ip='10.95.0.6',
        management_mode='external_dhcp',
        allocation_allowed=False,
    )

    listed = list_subnets()
    row = next(item for item in listed if item['id'] == prefix['id'])
    tree = get_subnets_tree()
    tree_row = next(item for item in tree if item['id'] == prefix['id'])
    analytics = get_utilization_analytics(network_scope='business')
    analytics_row = next(item for item in analytics['items'] if item['id'] == prefix['id'])

    for view in (row, tree_row, analytics_row):
        assert view['total_ips'] == 6
        assert view['used_ips'] == 0
        assert view['registered_utilization'] == 0.0
        assert view['reserved_ips'] == 6
        assert view['allocatable_free_ips'] == 0
        assert view['effective_utilization'] == 100.0

    assert analytics['overview']['free_ips'] == 0
    assert analytics['overview']['allocatable_free_ips'] == 0
    assert analytics['overview']['reserved_ips'] == 6
    assert analytics['overview']['effective_utilization_rate'] == 100.0
    assert get_next_available_ip_details(prefix['id'])['next_available_ip'] is None
    with pytest.raises(ValueError, match='No available IP addresses'):
        allocate_next_address(prefix['id'])


def test_ipv6_short_prefix_denominator_and_allocate_next_contract(isolated_db) -> None:
    space = create_address_space(
        name='Batch2-IPv6-Space',
        kind='global',
        vrf_id=None,
        security_tenant_id='tenant-default',
    )
    # /126 has 3 usable hosts in _prefix_host_bounds: ::1, ::2, ::3
    prefix = create_subnet(
        prefix='2001:db8:95::/126',
        address_space_id=space['id'],
        tenant_id='tenant-default',
        network_type='server',
    )
    listed = next(item for item in list_subnets() if item['id'] == prefix['id'])
    assert listed['total_ips'] == 3
    assert listed['allocatable_free_ips'] == 3

    allocated_addresses = []
    for remaining in (2, 1, 0):
        suggested = get_next_available_ip_details(prefix['id'])['next_available_ip']
        assert suggested is not None
        allocated = allocate_next_address(prefix['id'], hostname=f'v6-host-{remaining}')
        assert allocated['address'] == suggested
        assert allocated['subnet_id'] == prefix['id']
        assert allocated['address_space_id'] == space['id']
        allocated_addresses.append(allocated['address'])
        refreshed = next(item for item in list_subnets() if item['id'] == prefix['id'])
        assert refreshed['allocatable_free_ips'] == remaining

    assert allocated_addresses == ['2001:db8:95::1', '2001:db8:95::2', '2001:db8:95::3']
    assert get_next_available_ip_details(prefix['id'])['next_available_ip'] is None
    with pytest.raises(ValueError, match='No available IP addresses'):
        allocate_next_address(prefix['id'])


def test_container_prefix_utilization_and_allocation_block(isolated_db) -> None:
    space = create_address_space(
        name='Batch2-Container-Space',
        kind='global',
        vrf_id=None,
        security_tenant_id='tenant-default',
    )
    container = create_subnet(
        prefix='10.96.0.0/24',
        address_space_id=space['id'],
        tenant_id='tenant-default',
        status='container',
        network_type='server',
    )
    create_subnet(
        prefix='10.96.0.0/25',
        address_space_id=space['id'],
        tenant_id='tenant-default',
        network_type='server',
    )

    row = next(item for item in list_subnets() if item['id'] == container['id'])
    assert row['container_child_ips'] == 128
    assert row['container_utilization'] == 50.0
    assert row['utilization'] == 50.0
    assert row['allocatable_free_ips'] == 0
    assert row['allocation_blocked_reason'] == 'container_prefix'
    assert get_next_available_ip_details(container['id'])['next_available_ip'] is None
    with pytest.raises(ValueError, match='Container prefixes cannot allocate'):
        allocate_next_address(container['id'])


def test_delete_preview_and_scope_integrity_audit(isolated_db) -> None:
    space = create_address_space(
        name='Batch2-Audit-Space',
        kind='global',
        vrf_id=None,
        security_tenant_id='tenant-default',
    )
    prefix = create_subnet(
        prefix='10.97.0.0/24',
        address_space_id=space['id'],
        tenant_id='tenant-default',
    )
    create_address(prefix['id'], address='10.97.0.10', status='allocated')
    create_pool(
        prefix_id=prefix['id'],
        name='audit-pool',
        start_ip='10.97.0.100',
        end_ip='10.97.0.110',
        management_mode='local_static',
        allocation_allowed=True,
    )

    preview = preview_delete_subnet(prefix['id'])
    assert preview is not None
    assert preview['active_ip_count'] == 1
    assert preview['pool_count'] == 1
    assert preview['can_delete'] is False
    assert len(preview['blockers']) == 2

    # Inject a drifted child IP with NULL address_space_id to confirm read-only audit catches it
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ip_addresses
               (id, subnet_id, address, address_inet, address_space_id, tenant_id, status, created_at, updated_at)
               VALUES ('ip-drift-1', ?, '10.97.0.20', CAST('10.97.0.20' AS inet), NULL, 'tenant-default', 'allocated',
                       '2026-11-19T00:00:00Z', '2026-11-19T00:00:00Z')""",
            (prefix['id'],),
        )
        conn.commit()

    audit = audit_ipam_scope_integrity()
    assert audit['summary']['healthy'] is False
    assert audit['summary']['prefix_ip_space_mismatch_count'] == 1
    assert audit['prefix_ip_space_mismatches'][0]['ip_id'] == 'ip-drift-1'


def test_dhcp_lease_effective_state_derives_expiry_from_lease_end(isolated_db) -> None:
    expired_lease = create_lease(
        address='10.98.0.10',
        mac_address='00:11:22:33:44:10',
        dhcp_server='dhcp-01',
        lease_state='active',
        lease_start='2020-01-01T00:00:00Z',
        lease_end='2020-01-02T00:00:00Z',
    )
    active_lease = create_lease(
        address='10.98.0.11',
        mac_address='00:11:22:33:44:11',
        dhcp_server='dhcp-01',
        lease_state='active',
        lease_start='2026-11-19T00:00:00Z',
        lease_end='2099-01-01T00:00:00Z',
    )

    assert expired_lease['source_lease_state'] == 'active'
    assert expired_lease['effective_state'] == 'expired'
    assert expired_lease['is_expired'] is True
    assert active_lease['effective_state'] == 'active'
    assert active_lease['is_expired'] is False

    active_rows = list_leases(state='active')
    expired_rows = list_leases(state='expired')
    assert [row['id'] for row in active_rows] == [active_lease['id']]
    assert [row['id'] for row in expired_rows] == [expired_lease['id']]
