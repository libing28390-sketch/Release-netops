from __future__ import annotations

import pytest
from fastapi import HTTPException

from api import ipam as ipam_api
from database import get_db_connection
from schemas.schemas import PrefixAddressSpaceBatchPreviewRequest, PrefixUpdate
from services.cmdb_service import create_vlan, create_vrf
from services.ipam_address_space_service import create_address_space
from services.ipam_discovery_service import _supersede_older_endpoint_context_observations
from services.ipam_service import (
    create_address,
    create_pool,
    create_subnet,
    delete_subnet,
    delete_subnets,
    release_address,
    update_subnet,
)
from services.prefix_discovery_service import persist_prefix_candidates


def _ensure_tenant(tenant_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tenants(id, name) VALUES (?, ?) ON CONFLICT(id) DO NOTHING",
            (tenant_id, tenant_id),
        )
        conn.commit()


def _ensure_site(site_id: str, tenant_id: str = 'tenant-default') -> None:
    _ensure_tenant(tenant_id)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO sites(id, site_code, site_name, tenant_id) VALUES (?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
            (site_id, site_id.upper(), site_id, tenant_id),
        )
        conn.commit()


def test_discovery_does_not_partially_map_legacy_prefix_without_child_ips(isolated_db) -> None:
    with get_db_connection() as conn:
        vrf = create_vrf(conn, vrf_name='VRF-LEGACY-SYNC', rd='65001:100', tenant_id='tenant-default')
        conn.execute(
            """INSERT INTO prefixes
               (id, prefix, prefix_cidr, address_space_id, vrf_id, tenant_id, status, network_type, ip_version, prefix_len)
               VALUES (?, ?, ?, NULL, ?, ?, 'active', 'user', 4, 24)""",
            ('prefix-legacy-1', '10.90.1.0/24', '10.90.1.0/24', vrf['id'], 'tenant-default'),
        )
        conn.execute(
            """INSERT INTO ip_addresses
               (id, subnet_id, address, address_inet, address_space_id, vrf_id, tenant_id, status, created_at, updated_at)
               VALUES (?, ?, ?, CAST(? AS inet), NULL, ?, ?, 'allocated', '2026-11-19T00:00:00Z', '2026-11-19T00:00:00Z')""",
            ('ip-legacy-1', 'prefix-legacy-1', '10.90.1.10', '10.90.1.10', vrf['id'], 'tenant-default'),
        )
        conn.commit()

    result = persist_prefix_candidates(
        [{
            'prefix': '10.90.1.0/24',
            'tenant_id': 'tenant-default',
            'vrf_id': vrf['id'],
            'network_type': 'user',
            'confidence': 0.9,
            'observed_devices': ['dev-1'],
            'observed_interfaces': ['Vlan10'],
            'observed_vlans': ['10'],
            'observed_vrfs': ['VRF-LEGACY-SYNC'],
            'evidence': {'source': 'test'},
        }],
        collection_run_id='run-legacy-sync',
    )

    assert result['scope_pending'] == 1
    assert result['updated'] == 0
    with get_db_connection() as conn:
        prefix_row = conn.execute(
            'SELECT address_space_id FROM prefixes WHERE id = ?',
            ('prefix-legacy-1',),
        ).fetchone()
        ip_row = conn.execute(
            'SELECT address_space_id FROM ip_addresses WHERE id = ?',
            ('ip-legacy-1',),
        ).fetchone()
    assert prefix_row['address_space_id'] is None
    assert ip_row['address_space_id'] is None


def test_delete_prefix_blocks_active_ips_and_pools_and_rebuilds_hierarchy_atomically(isolated_db) -> None:
    space = create_address_space(name='Batch1-Delete-Space', kind='global', vrf_id=None, security_tenant_id='tenant-default')
    parent = create_subnet(prefix='10.91.0.0/16', address_space_id=space['id'], tenant_id='tenant-default')
    mid = create_subnet(prefix='10.91.1.0/24', address_space_id=space['id'], tenant_id='tenant-default')
    child = create_subnet(prefix='10.91.1.0/25', address_space_id=space['id'], tenant_id='tenant-default')

    with get_db_connection() as conn:
        child_row = conn.execute('SELECT parent_prefix_id FROM prefixes WHERE id = ?', (child['id'],)).fetchone()
    assert child_row['parent_prefix_id'] == mid['id']

    ip_row = create_address(mid['id'], address='10.91.1.200', status='allocated')
    with pytest.raises(ValueError, match='active formal IP addresses'):
        delete_subnet(mid['id'], expected_revision=1)
    with pytest.raises(ValueError, match='active formal IP addresses'):
        delete_subnets([mid['id']], expected_revisions={mid['id']: 1})

    release_address(ip_row['id'], released_by='tester', expected_revision=1)

    pool = create_pool(
        prefix_id=mid['id'],
        name='pool-block-delete',
        start_ip='10.91.1.210',
        end_ip='10.91.1.220',
        management_mode='local_static',
        allocation_allowed=True,
    )
    with pytest.raises(ValueError, match='IP pools'):
        delete_subnet(mid['id'], expected_revision=1)

    with get_db_connection() as conn:
        conn.execute('DELETE FROM ipam_pools WHERE id = ?', (pool['id'],))
        conn.commit()

    assert delete_subnet(mid['id'], expected_revision=1) is True
    with get_db_connection() as conn:
        reparented = conn.execute('SELECT parent_prefix_id FROM prefixes WHERE id = ?', (child['id'],)).fetchone()
    assert reparented['parent_prefix_id'] == parent['id']


def test_update_subnet_rejects_cidr_shrink_excluding_active_ip_or_pool(isolated_db) -> None:
    space = create_address_space(name='Batch1-Shrink-Space', kind='global', vrf_id=None, security_tenant_id='tenant-default')
    subnet = create_subnet(prefix='10.92.0.0/24', address_space_id=space['id'], tenant_id='tenant-default')
    create_address(subnet['id'], address='10.92.0.200', status='allocated')

    with pytest.raises(ValueError, match='does not contain existing formal IP address 10.92.0.200'):
        update_subnet(subnet['id'], prefix='10.92.0.0/25', expected_revision=1)

    # Expanding to /23 still contains 10.92.0.200 and succeeds
    assert update_subnet(subnet['id'], prefix='10.92.0.0/23', expected_revision=1) is True


def test_endpoint_supersede_preserves_distinct_address_spaces_and_isolates_unknown_devices() -> None:
    space_a = {
        'id': 'obs-a',
        'source_type': 'arp',
        'tenant_id': 'tenant-default',
        'site_id': 'site-1',
        'ip': '10.10.1.50',
        'mac': 'aa:bb:cc:dd:ee:01',
        'vlan': '10',
        'scope_status': 'resolved',
        'address_space_id': 'space-a',
        'vrf_id': 'vrf-a',
        'source_device_id': 'dev-a',
        'context_source': 'snmp',
        'context_type': 'vrf',
        'local_context_key': 'vrf-a',
        'observed_at': '2026-11-19T01:00:00Z',
    }
    space_b = {
        **space_a,
        'id': 'obs-b',
        'address_space_id': 'space-b',
        'vrf_id': 'vrf-b',
        'source_device_id': 'dev-b',
        'local_context_key': 'vrf-b',
        'observed_at': '2026-11-19T02:00:00Z',
    }
    kept = _supersede_older_endpoint_context_observations([space_a, space_b])
    assert {item['id'] for item in kept} == {'obs-a', 'obs-b'}

    # Same explicit address space: newer supersedes older
    space_a_newer = {
        **space_a,
        'id': 'obs-a-new',
        'local_context_key': 'vrf-a-renamed',
        'observed_at': '2026-11-19T03:00:00Z',
    }
    kept_same_space = _supersede_older_endpoint_context_observations([space_a, space_a_newer])
    assert [item['id'] for item in kept_same_space] == ['obs-a-new']

    # Unknown scope on dev-1 is not superseded by dev-2, but IS superseded by newer dev-1
    unk_dev1 = {
        **space_a,
        'id': 'obs-unk-1',
        'scope_status': 'scope_pending',
        'address_space_id': '',
        'vrf_id': '',
        'source_device_id': 'dev-1',
        'local_context_key': 'unknown',
        'observed_at': '2026-11-19T01:00:00Z',
    }
    unk_dev2 = {
        **unk_dev1,
        'id': 'obs-unk-2',
        'source_device_id': 'dev-2',
        'observed_at': '2026-11-19T02:00:00Z',
    }
    kept_unknown = _supersede_older_endpoint_context_observations([unk_dev1, unk_dev2])
    assert {item['id'] for item in kept_unknown} == {'obs-unk-1', 'obs-unk-2'}

    resolved_dev1 = {
        **unk_dev1,
        'id': 'obs-res-1',
        'scope_status': 'resolved',
        'address_space_id': 'space-a',
        'vrf_id': 'vrf-a',
        'local_context_key': 'vrf-a',
        'observed_at': '2026-11-19T03:00:00Z',
    }
    kept_migrated = _supersede_older_endpoint_context_observations([unk_dev1, resolved_dev1])
    assert [item['id'] for item in kept_migrated] == ['obs-res-1']


def test_prefix_vlan_scope_and_target_site_authorization_and_mixed_tenant_batch(isolated_db, make_user) -> None:
    _ensure_site('site-a', 'tenant-default')
    _ensure_site('site-b', 'tenant-default')
    _ensure_site('site-other-tenant', 'tenant-other')

    with get_db_connection() as conn:
        vlan_a = create_vlan(conn, vlan_id=101, name='VLAN-A', site_id='site-a', tenant_id='tenant-default')
        vlan_b = create_vlan(conn, vlan_id=102, name='VLAN-B', site_id='site-b', tenant_id='tenant-default')
        vlan_global = create_vlan(conn, vlan_id=103, name='VLAN-GLOBAL', site_id=None, tenant_id='tenant-default')
        vlan_other_tenant = create_vlan(conn, vlan_id=104, name='VLAN-OTHER', site_id='site-other-tenant', tenant_id='tenant-other')

    space = create_address_space(name='Batch1-VLAN-Space', kind='global', vrf_id=None, security_tenant_id='tenant-default')

    # Cross-site VLAN rejected
    with pytest.raises(ValueError, match='different site'):
        create_subnet(
            prefix='10.93.1.0/24',
            address_space_id=space['id'],
            tenant_id='tenant-default',
            site_id='site-a',
            vlan_id=vlan_b['id'],
        )

    # Cross-tenant VLAN rejected
    with pytest.raises(ValueError, match='different security tenant'):
        create_subnet(
            prefix='10.93.2.0/24',
            address_space_id=space['id'],
            tenant_id='tenant-default',
            site_id='site-a',
            vlan_id=vlan_other_tenant['id'],
        )

    # Site-scoped VLAN on siteless prefix rejected
    with pytest.raises(ValueError, match='without a matching site'):
        create_subnet(
            prefix='10.93.3.0/24',
            address_space_id=space['id'],
            tenant_id='tenant-default',
            site_id=None,
            vlan_id=vlan_a['id'],
        )

    # Matching site VLAN & tenant-global VLAN allowed
    sub_a = create_subnet(
        prefix='10.93.4.0/24',
        address_space_id=space['id'],
        tenant_id='tenant-default',
        site_id='site-a',
        vlan_id=vlan_a['id'],
    )
    sub_global_vlan = create_subnet(
        prefix='10.93.5.0/24',
        address_space_id=space['id'],
        tenant_id='tenant-default',
        site_id='site-a',
        vlan_id=vlan_global['id'],
    )
    assert sub_global_vlan['id']

    # Site-restricted user cannot move Prefix from site-a to unauthorized site-b
    user_row = make_user('ops-site-a', role='Operator', tenant_id='tenant-default')
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO user_resource_scopes
                   (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES (?, ?, 'prefix', 'site', ?, '["view","update"]', CURRENT_TIMESTAMP)""",
            ('scope-site-a-prefix', user_row['user_id'], 'site-a'),
        )
        conn.commit()
    site_a_user = {
        'id': user_row['user_id'],
        'username': user_row['username'],
        'role': 'Operator',
        'tenant_id': 'tenant-default',
        'scope_mode': 'restricted',
    }
    with pytest.raises(HTTPException) as exc_info:
        ipam_api.api_update_subnet(
            sub_global_vlan['id'],
            PrefixUpdate(expected_revision=1, site_id='site-b'),
            user=site_a_user,
        )
    assert exc_info.value.status_code == 403

    # Mixed-tenant batch preview rejected at API entry
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO prefixes
               (id, prefix, prefix_cidr, address_space_id, tenant_id, site_id, status, network_type, ip_version, prefix_len)
               VALUES (?, ?, ?, NULL, ?, ?, 'active', 'user', 4, 24)""",
            ('prefix-t1', '10.94.1.0/24', '10.94.1.0/24', 'tenant-default', 'site-a'),
        )
        conn.execute(
            """INSERT INTO prefixes
               (id, prefix, prefix_cidr, address_space_id, tenant_id, site_id, status, network_type, ip_version, prefix_len)
               VALUES (?, ?, ?, NULL, ?, ?, 'active', 'user', 4, 24)""",
            ('prefix-t2', '10.94.2.0/24', '10.94.2.0/24', 'tenant-other', 'site-other-tenant'),
        )
        conn.commit()

    super_admin = {
        'id': 'admin-1',
        'username': 'admin',
        'role': 'Administrator',
        'tenant_id': 'tenant-default',
    }
    with pytest.raises(HTTPException) as batch_exc:
        ipam_api.api_preview_prefix_address_space_batch(
            PrefixAddressSpaceBatchPreviewRequest(
                ids=['prefix-t1', 'prefix-t2'],
                address_space_id=space['id'],
            ),
            user=super_admin,
        )
    assert batch_exc.value.status_code == 409
    assert 'same security tenant' in str(batch_exc.value.detail)
