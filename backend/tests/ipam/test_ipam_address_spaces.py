from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from psycopg2.errors import CheckViolation

from api import ipam as ipam_api
from database import get_db_connection
from database.migrations.m0308_ipam_address_spaces import upgrade as upgrade_address_spaces
from schemas.schemas import (
    AddressSpaceCreate,
    PrefixAddressSpaceBatchPreviewRequest,
    ResolvePrefixAddressSpaceBatchRequest,
    ResolvePrefixAddressSpaceRequest,
)
import services.ipam_address_space_service as ipam_address_space_service
from services.cmdb_service import create_vrf, delete_vrf, update_vrf
from services.ipam_address_space_service import (
    create_address_space,
    list_address_spaces,
    preview_prefix_address_space,
    preview_prefix_address_space_batch,
    resolve_prefix_address_space,
    resolve_prefix_address_space_batch,
)
from services.ipam_service import (
    allocate_next_address,
    create_address,
    create_pool,
    create_subnet,
    get_next_available_ip_details,
)


def _global_space(name: str = 'Test Global A', tenant_id: str = 'tenant-default') -> dict:
    return create_address_space(
        name=name,
        kind='global',
        vrf_id=None,
        security_tenant_id=tenant_id,
    )


def _ensure_site(site_id: str, tenant_id: str = 'tenant-default') -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO sites(id, site_code, site_name, tenant_id) VALUES (?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
            (site_id, site_id.upper(), site_id, tenant_id),
        )
        conn.commit()


def _legacy_prefix(prefix_id: str, prefix: str, *, site_id: str | None = None,
                   tenant_id: str | None = 'tenant-default', vrf_id: str | None = None) -> None:
    if site_id:
        _ensure_site(site_id, tenant_id or 'tenant-default')
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO prefixes
                   (id, prefix, prefix_cidr, address_space_id, vrf_id, site_id, tenant_id,
                    status, name, created_at, updated_at)
               VALUES (?, ?, ?, NULL, ?, ?, ?, 'active', 'Legacy pending', '2026-11-05', '2026-11-05')""",
            (prefix_id, prefix, prefix, vrf_id, site_id, tenant_id),
        )
        conn.commit()


def _legacy_pool(pool_id: str, prefix_id: str, start_ip: str, end_ip: str,
                 *, tenant_id: str = 'tenant-default') -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_pools
                   (id, name, prefix_id, start_ip, end_ip, tenant_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'now', 'now')""",
            (pool_id, pool_id, prefix_id, start_ip, end_ip, tenant_id),
        )
        conn.commit()


def test_m0308_backfills_only_unambiguous_explicit_vrf_and_is_idempotent(isolated_db):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants(id, name) VALUES ('tenant-other', 'Other') ON CONFLICT DO NOTHING")
        for site_id in ('m308-site-a', 'm308-site-b'):
            conn.execute(
                """INSERT INTO sites(id, site_code, site_name, tenant_id)
                   VALUES (?, ?, ?, 'tenant-default') ON CONFLICT(id) DO NOTHING""",
                (site_id, site_id.upper(), site_id),
            )
        conn.execute(
            "INSERT INTO vrfs(id, vrf_name, tenant_id) VALUES ('m308-explicit-vrf', 'M308-VRF', 'tenant-default')"
        )
        conn.execute(
            """INSERT INTO prefixes
                   (id, prefix, prefix_cidr, address_space_id, vrf_id, site_id, tenant_id,
                    status, name, created_at, updated_at)
               VALUES
                   ('m308-unique', '198.51.100.0/24', '198.51.100.0/24', NULL,
                    'm308-explicit-vrf', 'm308-site-a', 'tenant-default', 'active', '', 'now', 'now'),
                   ('m308-dup-a', '192.0.2.0/24', '192.0.2.0/24', NULL,
                    'm308-explicit-vrf', 'm308-site-a', 'tenant-default', 'active', '', 'now', 'now'),
                   ('m308-dup-b', '192.0.2.0/24', '192.0.2.0/24', NULL,
                    'm308-explicit-vrf', 'm308-site-b', 'tenant-default', 'active', '', 'now', 'now'),
                   ('m308-global-pending', '203.0.113.0/24', '203.0.113.0/24', NULL,
                    NULL, 'm308-site-a', 'tenant-default', 'active', '', 'now', 'now'),
                   ('m308-tenant-mismatch', '203.0.114.0/24', '203.0.114.0/24', NULL,
                    'm308-explicit-vrf', 'm308-site-a', 'tenant-other', 'active', '', 'now', 'now')"""
        )
        conn.execute(
            """INSERT INTO ip_addresses
                   (id, subnet_id, address, created_at, updated_at, address_inet)
               VALUES ('m308-address', 'm308-unique', '198.51.100.10', 'now', 'now', '198.51.100.10')"""
        )
        conn.commit()

        upgrade_address_spaces(conn.cursor(), True)
        upgrade_address_spaces(conn.cursor(), True)

        rows = {
            row['id']: dict(row)
            for row in conn.execute(
                "SELECT id, address_space_id FROM prefixes WHERE id LIKE 'm308-%'"
            ).fetchall()
        }
        assert rows['m308-unique']['address_space_id'] == 'as-vrf:m308-explicit-vrf'
        assert rows['m308-dup-a']['address_space_id'] is None
        assert rows['m308-dup-b']['address_space_id'] is None
        assert rows['m308-global-pending']['address_space_id'] is None
        assert rows['m308-tenant-mismatch']['address_space_id'] is None
        address = conn.execute(
            "SELECT address_space_id FROM ip_addresses WHERE id = 'm308-address'"
        ).fetchone()
        assert address['address_space_id'] == 'as-vrf:m308-explicit-vrf'

        indexes = {
            row['indexname']
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
            ).fetchall()
        }
        assert 'uq_prefixes_address_space_cidr' in indexes
        assert 'uq_prefixes_legacy_scope_cidr' in indexes
        assert 'uq_ip_addresses_space_active' in indexes
        assert 'uq_ip_addresses_legacy_scope_active' in indexes
        conn.commit()


def test_m0308_conflict_preflight_reports_sample_ids_before_index_rebuild(isolated_db):
    with get_db_connection() as conn:
        conn.execute('DROP INDEX IF EXISTS uq_prefixes_legacy_scope_cidr')
        conn.execute('DROP INDEX IF EXISTS uq_prefixes_scope_cidr')
        conn.execute(
            """INSERT INTO prefixes
                   (id, prefix, prefix_cidr, address_space_id, vrf_id, site_id, tenant_id,
                    status, name, created_at, updated_at)
               VALUES
                   ('m308-duplicate-a', '192.0.2.0/24', '192.0.2.0/24', NULL,
                    NULL, NULL, 'tenant-default', 'active', '', 'now', 'now'),
                   ('m308-duplicate-b', '192.0.2.0/24', '192.0.2.0/24', NULL,
                    NULL, NULL, 'tenant-default', 'active', '', 'now', 'now')"""
        )
        conn.commit()
        with pytest.raises(RuntimeError, match='sample row IDs') as blocked:
            upgrade_address_spaces(conn.cursor(), True)
        assert 'm308-duplicate-a' in str(blocked.value)
        assert 'm308-duplicate-b' in str(blocked.value)
        conn.rollback()


def test_new_prefix_requires_explicit_global_space_and_site_is_not_identity(isolated_db):
    first_space = _global_space()
    second_space = _global_space('Test Global B')
    with pytest.raises(ValueError, match='explicit Global address space'):
        create_subnet(prefix='10.70.0.0/24', site_id='p2a-site-a')

    _ensure_site('p2a-site-a')
    first = create_subnet(
        prefix='10.70.0.0/24', address_space_id=first_space['id'],
        site_id='p2a-site-a',
    )
    second = create_subnet(
        prefix='10.70.0.0/24', address_space_id=second_space['id'],
        site_id='p2a-site-a',
    )
    assert first['address_space_id'] == first_space['id']
    assert second['address_space_id'] == second_space['id']
    assert create_address(first['id'], address='10.70.0.10')
    assert create_address(second['id'], address='10.70.0.10')


def test_same_address_space_rejects_cross_site_duplicate_prefix_but_other_space_allows_reuse(isolated_db):
    primary_space = _global_space('Cross-site uniqueness primary')
    reused_space = _global_space('Cross-site uniqueness secondary')
    _ensure_site('cross-site-unique-a')
    _ensure_site('cross-site-unique-b')

    primary = create_subnet(
        prefix='10.70.10.0/24', address_space_id=primary_space['id'],
        site_id='cross-site-unique-a',
    )
    with pytest.raises(ValueError, match='already exists in this address space'):
        create_subnet(
            prefix='10.70.10.0/24', address_space_id=primary_space['id'],
            site_id='cross-site-unique-b',
        )

    reused = create_subnet(
        prefix='10.70.10.0/24', address_space_id=reused_space['id'],
        site_id='cross-site-unique-b',
    )
    assert primary['address_space_id'] == primary_space['id']
    assert reused['address_space_id'] == reused_space['id']
    assert primary['id'] != reused['id']


def test_ipv6_equivalent_host_text_is_canonical_and_cidr_suffix_is_rejected(isolated_db):
    space = _global_space('IPv6 canonicalization Global')
    prefix = create_subnet(prefix='2001:db8:10::/64', address_space_id=space['id'])
    registered = create_address(prefix['id'], address='2001:db8:10::1')
    assert registered['address'] == '2001:db8:10::1'

    equivalent_forms = (
        '2001:0db8:0010:0000:0000:0000:0000:0001',
        '2001:DB8:10::1',
        '2001:db8:10:0:0:0:0:1',
        '2001:0DB8:0010:0:0000::0001',
    )
    for address in equivalent_forms:
        with pytest.raises(ValueError, match='already allocated in this address space'):
            create_address(prefix['id'], address=address)
    with pytest.raises(ValueError, match='host address without a CIDR prefix length'):
        create_address(prefix['id'], address='2001:db8:10::2/128')


def test_manual_registration_rejects_ipv6_zone_identifiers(isolated_db):
    space = _global_space('IPv6 scoped-address rejection Global')
    prefix = create_subnet(prefix='fe80::/64', address_space_id=space['id'])

    for zone_id in ('eth0', '3'):
        with pytest.raises(ValueError, match='IPv6 zone identifier'):
            create_address(prefix['id'], address=f'fe80::1%{zone_id}')


def test_allocator_uses_same_address_space_across_parent_and_child_prefixes(isolated_db):
    space = _global_space()
    parent = create_subnet(prefix='10.71.0.0/24', address_space_id=space['id'])
    child = create_subnet(prefix='10.71.0.0/28', address_space_id=space['id'])
    create_address(child['id'], address='10.71.0.1')

    assert get_next_available_ip_details(parent['id'])['next_available_ip'] == '10.71.0.2'
    assert allocate_next_address(parent['id'])['address'] == '10.71.0.2'


def test_unmapped_prefix_manual_registration_allowed_but_automatic_allocation_blocked(isolated_db):
    _legacy_prefix('legacy-pending-ipam', '10.72.0.0/24', site_id='p2a-site')
    create_address('legacy-pending-ipam', address='10.72.0.10')
    with pytest.raises(ValueError, match='Resolve the Prefix address space'):
        allocate_next_address('legacy-pending-ipam')
    assert get_next_available_ip_details('legacy-pending-ipam')['next_available_ip'] is None


def test_prefix_resolution_preview_and_confirm_maps_pool_scope_atomically(isolated_db):
    del isolated_db
    space = _global_space('Legacy Pool Mapping Global')
    _legacy_prefix('legacy-pool-mapping-prefix', '10.76.0.0/24')
    _legacy_pool(
        'legacy-pool-mapping-row', 'legacy-pool-mapping-prefix',
        '10.76.0.20', '10.76.0.30',
    )

    preview = preview_prefix_address_space(
        'legacy-pool-mapping-prefix', address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )
    assert preview['can_confirm'] is True
    assert preview['impact']['pools'] == 1
    assert preview['impact']['pools_to_map'] == 1
    assert preview['impact']['pool_samples'] == [{
        'pool_id': 'legacy-pool-mapping-row',
        'start_ip': '10.76.0.20',
        'end_ip': '10.76.0.30',
        'management_mode': None,
        'policy_pending': True,
    }]

    result = resolve_prefix_address_space(
        'legacy-pool-mapping-prefix', address_space_id=space['id'],
        expected_updated_at=preview['expected_updated_at'], confirmed=True,
        security_tenant_id='tenant-default',
    )
    assert result['impact']['pools_mapped'] == 1
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT address_space_id, management_mode, allocation_allowed "
            "FROM ipam_pools WHERE id = 'legacy-pool-mapping-row'"
        ).fetchone()
    assert row['address_space_id'] == space['id']
    # Scope is explicit now, while legacy management policy remains pending.
    assert row['management_mode'] is None
    assert row['allocation_allowed'] is None


def test_prefix_resolution_preview_blocks_pool_tenant_and_range_mismatches(isolated_db):
    del isolated_db
    space = _global_space('Legacy Pool Blockers Global')
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants(id, name) VALUES ('tenant-other', 'Other') ON CONFLICT DO NOTHING")
        conn.commit()
    _legacy_prefix('legacy-pool-blockers-prefix', '10.77.0.0/24')
    _legacy_pool(
        'legacy-pool-cross-tenant', 'legacy-pool-blockers-prefix',
        '10.77.0.20', '10.77.0.30', tenant_id='tenant-other',
    )
    _legacy_pool(
        'legacy-pool-invalid-range', 'legacy-pool-blockers-prefix',
        '10.77.0.40', '10.78.0.1',
    )

    preview = preview_prefix_address_space(
        'legacy-pool-blockers-prefix', address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )
    assert preview['can_confirm'] is False
    blocker_codes = {item['code'] for item in preview['blockers']}
    assert 'pool_tenant_mismatch' in blocker_codes
    assert 'pool_range_invalid' in blocker_codes
    with pytest.raises(ValueError, match='tenant|range'):
        resolve_prefix_address_space(
            'legacy-pool-blockers-prefix', address_space_id=space['id'],
            expected_updated_at=preview['expected_updated_at'], confirmed=True,
            security_tenant_id='tenant-default',
        )
    with get_db_connection() as conn:
        prefix = conn.execute(
            "SELECT address_space_id FROM prefixes WHERE id = 'legacy-pool-blockers-prefix'"
        ).fetchone()
        pools = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE prefix_id = 'legacy-pool-blockers-prefix'"
        ).fetchall()
    assert prefix['address_space_id'] is None
    assert all(row['address_space_id'] is None for row in pools)


def test_prefix_resolution_preview_blocks_pool_overlap_in_target_space(isolated_db):
    del isolated_db
    space = _global_space('Legacy Pool Overlap Global')
    parent = create_subnet(
        prefix='10.78.0.0/24', address_space_id=space['id'],
        name='Mapped parent with Pool',
    )
    _legacy_prefix('legacy-pool-overlap-child', '10.78.0.0/25')
    _legacy_pool('legacy-pool-target-existing', parent['id'], '10.78.0.20', '10.78.0.30')
    _legacy_pool('legacy-pool-target-candidate', 'legacy-pool-overlap-child', '10.78.0.25', '10.78.0.35')

    preview = preview_prefix_address_space(
        'legacy-pool-overlap-child', address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )
    assert preview['can_confirm'] is False
    assert any(item['code'] == 'pool_range_overlap' for item in preview['blockers'])
    assert preview['impact']['pool_conflicts'] == [{
        'pool_id': 'legacy-pool-target-candidate',
        'conflicting_pool_id': 'legacy-pool-target-existing',
        'start_ip': '10.78.0.25',
        'end_ip': '10.78.0.35',
    }]


def test_prefix_resolution_rechecks_pool_overlap_after_preview_before_commit(isolated_db):
    del isolated_db
    space = _global_space('Legacy Pool Stale Preview Global')
    mapped_parent = create_subnet(
        prefix='10.79.0.0/24', address_space_id=space['id'],
        name='Mapped parent for stale Pool preview',
    )
    _legacy_prefix('legacy-pool-stale-child', '10.79.0.0/25')
    _legacy_pool('legacy-pool-stale-candidate', 'legacy-pool-stale-child', '10.79.0.20', '10.79.0.30')

    preview = preview_prefix_address_space(
        'legacy-pool-stale-child', address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )
    assert preview['can_confirm'] is True
    create_pool(
        name='Inserted after preview', prefix_id=mapped_parent['id'],
        start_ip='10.79.0.25', end_ip='10.79.0.35',
        management_mode='reserved', allocation_allowed=False,
    )

    with pytest.raises(ValueError, match='overlap'):
        resolve_prefix_address_space(
            'legacy-pool-stale-child', address_space_id=space['id'],
            expected_updated_at=preview['expected_updated_at'], confirmed=True,
            security_tenant_id='tenant-default',
        )
    with get_db_connection() as conn:
        prefix = conn.execute(
            "SELECT address_space_id FROM prefixes WHERE id = 'legacy-pool-stale-child'"
        ).fetchone()
        pool = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE id = 'legacy-pool-stale-candidate'"
        ).fetchone()
    assert prefix['address_space_id'] is None
    assert pool['address_space_id'] is None


def test_address_space_api_rejects_client_tenant_and_applies_resource_scopes(isolated_db, monkeypatch):
    with pytest.raises(ValidationError):
        AddressSpaceCreate(
            name='forged',
            kind='global',
            tenant_id='tenant-other',
        )
    with pytest.raises(ValidationError):
        AddressSpaceCreate(
            name='forged',
            kind='global',
            security_tenant_id='tenant-other',
        )

    user = {'id': 'space-viewer', 'username': 'space-viewer', 'role': 'Administrator'}
    monkeypatch.setattr(ipam_api, 'authorize_resource', lambda *args, **kwargs: False)
    assert ipam_api.api_list_address_spaces(user=user)['items'] == []

    def deny(*args, **kwargs):
        raise HTTPException(status_code=403, detail='denied')

    monkeypatch.setattr(ipam_api, 'enforce_resource_scope', deny)
    with pytest.raises(HTTPException) as denied:
        ipam_api.api_create_address_space(
            AddressSpaceCreate(name='Denied Global', kind='global'),
            user=user,
        )
    assert denied.value.status_code == 403
    assert list_address_spaces(security_tenant_id='tenant-default') == []


def test_vrf_create_materializes_space_and_scope_changes_or_delete_are_blocked(isolated_db):
    with get_db_connection() as conn:
        vrf = create_vrf(
            conn,
            vrf_name='P2A-CREATED-VRF',
            tenant_id='tenant-default',
        )
        assert conn.execute(
            'SELECT id FROM ipam_address_spaces WHERE vrf_id = ?',
            (vrf['id'],),
        ).fetchone()
        with pytest.raises(ValueError, match='tenant cannot change'):
            update_vrf(conn, vrf['id'], tenant_id='tenant-other')
        with pytest.raises(ValueError, match='address-space mapping'):
            delete_vrf(conn, vrf['id'])


def test_prefix_address_space_resolution_requires_fresh_explicit_confirmation(isolated_db, monkeypatch):
    space = _global_space('Resolve Pending')
    _legacy_prefix('legacy-resolve', '10.73.0.0/24', site_id='p2a-site')
    address = create_address('legacy-resolve', address='10.73.0.10')
    user = {'id': 'prefix-admin', 'username': 'prefix-admin', 'role': 'Administrator'}
    monkeypatch.setattr(ipam_api, 'enforce_resource_scope', lambda *args, **kwargs: user)
    preview = ipam_api.api_preview_prefix_address_space(
        'legacy-resolve',
        address_space_id=space['id'],
        user=user,
    )
    assert preview['can_confirm'] is True
    assert preview['target_space']['id'] == space['id']
    assert preview['impact']['ip_addresses'] == 1

    with pytest.raises(HTTPException) as unconfirmed:
        ipam_api.api_resolve_prefix_address_space(
            'legacy-resolve',
            ResolvePrefixAddressSpaceRequest(
                address_space_id=space['id'],
                expected_updated_at=preview['expected_updated_at'],
                expected_revision=preview['expected_revision'],
                confirmed=False,
            ),
            user=user,
        )
    assert unconfirmed.value.status_code == 409

    with pytest.raises(HTTPException) as stale:
        ipam_api.api_resolve_prefix_address_space(
            'legacy-resolve',
            ResolvePrefixAddressSpaceRequest(
                address_space_id=space['id'],
                expected_updated_at='stale-revision',
                expected_revision=preview['expected_revision'],
                confirmed=True,
            ),
            user=user,
        )
    assert stale.value.status_code == 409

    result = ipam_api.api_resolve_prefix_address_space(
        'legacy-resolve',
        ResolvePrefixAddressSpaceRequest(
            address_space_id=space['id'],
            expected_updated_at=preview['expected_updated_at'],
            expected_revision=preview['expected_revision'],
            confirmed=True,
        ),
        user=user,
    )
    assert result['address_space_id'] == space['id']
    with get_db_connection() as conn:
        row = conn.execute(
            'SELECT address_space_id, tenant_id FROM ip_addresses WHERE id = ?',
            (address['id'],),
        ).fetchone()
        prefix = conn.execute(
            'SELECT address_space_id, vrf_id FROM prefixes WHERE id = ?',
            ('legacy-resolve',),
        ).fetchone()
    assert row['address_space_id'] == space['id']
    assert row['tenant_id'] == 'tenant-default'
    assert prefix['address_space_id'] == space['id']
    assert prefix['vrf_id'] is None


def test_prefix_resolution_preview_blocks_duplicate_cidr_in_target_space(isolated_db):
    space = _global_space('Duplicate Target')
    create_subnet(prefix='10.74.0.0/24', address_space_id=space['id'])
    _legacy_prefix('legacy-duplicate', '10.74.0.0/24', site_id='other-site')

    preview = ipam_api.api_preview_prefix_address_space(
        'legacy-duplicate',
        address_space_id=space['id'],
        user={'id': 'admin', 'username': 'admin', 'role': 'Administrator'},
    )
    assert preview['can_confirm'] is False
    assert any(blocker['code'] == 'duplicate_prefix_cidr' for blocker in preview['blockers'])


def test_batch_address_space_preview_blocks_duplicate_cidrs_and_reports_each_prefix(isolated_db):
    space = _global_space('Batch duplicate review')
    _legacy_prefix('batch-duplicate-a', '10.83.10.0/24', site_id='batch-site-a')
    _legacy_prefix('batch-duplicate-b', '10.83.10.0/24', site_id='batch-site-b')

    preview = preview_prefix_address_space_batch(
        ['batch-duplicate-a', 'batch-duplicate-b'],
        address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )
    assert preview['can_confirm'] is False
    assert preview['selected_count'] == 2
    assert {item['prefix_id'] for item in preview['blockers']} == {
        'batch-duplicate-a', 'batch-duplicate-b',
    }
    assert {item['code'] for item in preview['blockers']} == {'duplicate_prefix_cidr_in_batch'}
    assert {item['network'] for item in preview['blockers']} == {'10.83.10.0/24'}
    assert {item['duplicate_count'] for item in preview['blockers']} == {2}


def test_batch_address_space_preview_blocks_overlapping_pools_across_selected_prefixes(isolated_db):
    space = _global_space('Batch overlapping pool review')
    _legacy_prefix('batch-pool-a', '10.84.10.0/24')
    _legacy_prefix('batch-pool-b', '10.84.10.0/25')
    _legacy_pool('batch-pool-row-a', 'batch-pool-a', '10.84.10.20', '10.84.10.50')
    _legacy_pool('batch-pool-row-b', 'batch-pool-b', '10.84.10.40', '10.84.10.60')
    preview = preview_prefix_address_space_batch(
        ['batch-pool-a', 'batch-pool-b'],
        address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )
    assert preview['can_confirm'] is False
    assert any(item['code'] == 'pool_range_overlap_in_batch' for item in preview['blockers'])


def test_batch_address_space_confirm_maps_prefixes_ips_and_pools_together(isolated_db):
    space = _global_space('Batch confirmation target')
    _legacy_prefix('batch-confirm-a', '10.85.10.0/24', site_id='batch-site-a')
    _legacy_prefix('batch-confirm-b', '10.85.20.0/24', site_id='batch-site-b')
    address = create_address('batch-confirm-a', address='10.85.10.12')
    _legacy_pool('batch-confirm-pool', 'batch-confirm-b', '10.85.20.30', '10.85.20.40')
    preview = preview_prefix_address_space_batch(
        ['batch-confirm-a', 'batch-confirm-b'],
        address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )
    assert preview['can_confirm'] is True
    assert preview['expected_target_revision'] == space['revision']
    assert preview['totals']['ip_addresses'] == 1
    assert preview['totals']['pools_to_map'] == 1

    result = resolve_prefix_address_space_batch(
        [
            {
                'prefix_id': item['prefix_id'],
                'expected_updated_at': item['expected_updated_at'],
                'expected_revision': item['expected_revision'],
            }
            for item in preview['items']
        ],
        address_space_id=space['id'],
        expected_target_revision=preview['expected_target_revision'],
        confirmed=True,
        security_tenant_id='tenant-default',
    )
    assert result['updated'] == 2
    assert result['totals']['pools_mapped'] == 1
    with get_db_connection() as conn:
        mapped_prefixes = conn.execute(
            "SELECT id, address_space_id FROM prefixes WHERE id IN ('batch-confirm-a', 'batch-confirm-b') ORDER BY id"
        ).fetchall()
        mapped_address = conn.execute(
            'SELECT address_space_id FROM ip_addresses WHERE id = ?', (address['id'],)
        ).fetchone()
        mapped_pool = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE id = 'batch-confirm-pool'"
        ).fetchone()
    assert [row['address_space_id'] for row in mapped_prefixes] == [space['id'], space['id']]
    assert mapped_address['address_space_id'] == space['id']
    assert mapped_pool['address_space_id'] == space['id']


def test_batch_address_space_confirm_rolls_back_all_prefixes_on_late_audit_failure(isolated_db, monkeypatch):
    space = _global_space('Batch atomic target')
    _legacy_prefix('batch-atomic-a', '10.86.10.0/24')
    _legacy_prefix('batch-atomic-b', '10.86.20.0/24')
    preview = preview_prefix_address_space_batch(
        ['batch-atomic-a', 'batch-atomic-b'],
        address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )
    calls = 0

    def fail_on_second_audit(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('synthetic batch audit failure')

    monkeypatch.setattr(ipam_address_space_service, 'log_audit_event', fail_on_second_audit)
    with pytest.raises(RuntimeError, match='synthetic batch audit failure'):
        resolve_prefix_address_space_batch(
            [
                {
                    'prefix_id': item['prefix_id'],
                    'expected_updated_at': item['expected_updated_at'],
                    'expected_revision': item['expected_revision'],
                }
                for item in preview['items']
            ],
            address_space_id=space['id'],
            expected_target_revision=preview['expected_target_revision'],
            confirmed=True,
            security_tenant_id='tenant-default',
            audit_context={'actor_id': 'operator-1', 'actor_username': 'operator', 'actor_role': 'Administrator'},
        )

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, address_space_id FROM prefixes WHERE id IN ('batch-atomic-a', 'batch-atomic-b') ORDER BY id"
        ).fetchall()
    assert all(row['address_space_id'] is None for row in rows)


def test_batch_address_space_api_enforces_scope_for_every_selected_prefix(isolated_db, monkeypatch):
    space = _global_space('Batch API target')
    _legacy_prefix('batch-api-site-a', '10.87.10.0/24', site_id='batch-api-a')
    _legacy_prefix('batch-api-site-b', '10.87.20.0/24', site_id='batch-api-b')
    seen_sites = []

    def enforce(user, resource, action, **scope):
        seen_sites.append(scope.get('site_id'))
        if scope.get('site_id') == 'batch-api-b':
            raise HTTPException(status_code=403, detail='denied')

    monkeypatch.setattr(ipam_api, 'enforce_resource_scope', enforce)
    with pytest.raises(HTTPException) as denied:
        ipam_api.api_preview_prefix_address_space_batch(
            PrefixAddressSpaceBatchPreviewRequest(
                ids=['batch-api-site-a', 'batch-api-site-b'],
                address_space_id=space['id'],
            ),
            user={'id': 'limited', 'username': 'limited', 'role': 'Administrator'},
        )
    assert denied.value.status_code == 403
    assert seen_sites == ['batch-api-a', 'batch-api-b']


def test_batch_prefix_address_space_preview_and_confirm_are_atomic(isolated_db):
    space = _global_space('Batch Mapping Global')
    _legacy_prefix('batch-map-a', '10.80.10.0/24', site_id='batch-site-a')
    _legacy_prefix('batch-map-b', '10.80.20.0/24', site_id='batch-site-b')
    address = create_address('batch-map-a', address='10.80.10.10')
    _legacy_pool('batch-map-pool', 'batch-map-b', '10.80.20.10', '10.80.20.20')

    preview = preview_prefix_address_space_batch(
        ['batch-map-a', 'batch-map-b'],
        address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )
    assert preview['can_confirm'] is True
    assert preview['selected_count'] == 2
    assert preview['totals']['ip_addresses'] == 1
    assert preview['totals']['pools_to_map'] == 1

    result = resolve_prefix_address_space_batch(
        [
            {
                'prefix_id': item['prefix_id'],
                'expected_updated_at': item['expected_updated_at'],
                'expected_revision': item['expected_revision'],
            }
            for item in preview['items']
        ],
        address_space_id=space['id'],
        expected_target_revision=preview['expected_target_revision'],
        confirmed=True,
        security_tenant_id='tenant-default',
    )
    assert result['updated'] == 2
    with get_db_connection() as conn:
        prefixes = conn.execute(
            "SELECT id, address_space_id FROM prefixes WHERE id IN ('batch-map-a', 'batch-map-b') ORDER BY id"
        ).fetchall()
        mapped_address = conn.execute(
            "SELECT address_space_id FROM ip_addresses WHERE id = ?", (address['id'],)
        ).fetchone()
        mapped_pool = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE id = 'batch-map-pool'"
        ).fetchone()
    assert [row['address_space_id'] for row in prefixes] == [space['id'], space['id']]
    assert mapped_address['address_space_id'] == space['id']
    assert mapped_pool['address_space_id'] == space['id']


def test_batch_prefix_address_space_preview_blocks_duplicate_selected_cidrs(isolated_db):
    space = _global_space('Batch Duplicate Global')
    _legacy_prefix('batch-duplicate-a', '10.81.10.0/24', site_id='batch-site-a')
    _legacy_prefix('batch-duplicate-b', '10.81.10.0/24', site_id='batch-site-b')

    preview = preview_prefix_address_space_batch(
        ['batch-duplicate-a', 'batch-duplicate-b'],
        address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )
    assert preview['can_confirm'] is False
    assert {
        item['code']
        for item in preview['blockers']
    } == {'duplicate_prefix_cidr_in_batch'}
    assert {item['prefix_id'] for item in preview['blockers']} == {
        'batch-duplicate-a', 'batch-duplicate-b',
    }


def test_batch_prefix_address_space_confirmation_rolls_back_every_prefix_on_late_failure(
    isolated_db, monkeypatch,
):
    space = _global_space('Batch Atomic Global')
    _legacy_prefix('batch-atomic-a', '10.82.10.0/24')
    _legacy_prefix('batch-atomic-b', '10.82.20.0/24')
    create_address('batch-atomic-a', address='10.82.10.10')
    _legacy_pool('batch-atomic-pool', 'batch-atomic-b', '10.82.20.10', '10.82.20.20')
    preview = preview_prefix_address_space_batch(
        ['batch-atomic-a', 'batch-atomic-b'],
        address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )
    calls = 0
    original_log_audit_event = ipam_address_space_service.log_audit_event

    def commit_first_audit_then_fail_second(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('synthetic audit failure')
        return original_log_audit_event(**kwargs)

    monkeypatch.setattr(
        ipam_address_space_service, 'log_audit_event', commit_first_audit_then_fail_second,
    )
    with pytest.raises(RuntimeError, match='synthetic audit failure'):
        resolve_prefix_address_space_batch(
            [
                {
                    'prefix_id': item['prefix_id'],
                    'expected_updated_at': item['expected_updated_at'],
                    'expected_revision': item['expected_revision'],
                }
                for item in preview['items']
            ],
            address_space_id=space['id'],
            expected_target_revision=preview['expected_target_revision'],
            confirmed=True,
            security_tenant_id='tenant-default',
            audit_context={'actor_id': 'operator-1', 'actor_username': 'operator', 'actor_role': 'Administrator'},
        )

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, address_space_id FROM prefixes WHERE id IN ('batch-atomic-a', 'batch-atomic-b') ORDER BY id"
        ).fetchall()
        addresses = conn.execute(
            "SELECT address_space_id FROM ip_addresses WHERE subnet_id = 'batch-atomic-a'"
        ).fetchall()
        pools = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE id = 'batch-atomic-pool'"
        ).fetchall()
        audit_rows = conn.execute(
            """SELECT id FROM audit_events
                 WHERE event_type = 'ipam.prefix.resolve_address_space'
                   AND target_id IN ('batch-atomic-a', 'batch-atomic-b')"""
        ).fetchall()
    assert all(row['address_space_id'] is None for row in rows)
    assert all(row['address_space_id'] is None for row in addresses)
    assert all(row['address_space_id'] is None for row in pools)
    assert audit_rows == []


def _prepare_batch_failure_case(*, second_prefix_has_ip: bool = False):
    space = _global_space('Batch failure matrix Global')
    _legacy_prefix('batch-failure-a', '10.82.50.0/24')
    _legacy_prefix('batch-failure-b', '10.82.60.0/24')
    create_address('batch-failure-a', address='10.82.50.10')
    if second_prefix_has_ip:
        create_address('batch-failure-b', address='10.82.60.10')
    _legacy_pool('batch-failure-pool', 'batch-failure-a', '10.82.50.20', '10.82.50.30')
    preview = preview_prefix_address_space_batch(
        ['batch-failure-a', 'batch-failure-b'],
        address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )
    assert preview['can_confirm'] is True
    return space, preview


def _confirm_batch_failure_case(space: dict, preview: dict) -> dict:
    return resolve_prefix_address_space_batch(
        [
            {
                'prefix_id': item['prefix_id'],
                'expected_updated_at': item['expected_updated_at'],
                'expected_revision': item['expected_revision'],
            }
            for item in preview['items']
        ],
        address_space_id=space['id'],
        expected_target_revision=preview['expected_target_revision'],
        confirmed=True,
        security_tenant_id='tenant-default',
        audit_context={
            'actor_id': 'operator-1',
            'actor_username': 'operator',
            'actor_role': 'Administrator',
        },
    )


def _assert_batch_failure_case_rolled_back() -> None:
    prefix_ids = ('batch-failure-a', 'batch-failure-b')
    placeholders = ', '.join('?' for _ in prefix_ids)
    with get_db_connection() as conn:
        prefixes = conn.execute(
            f'SELECT id, address_space_id FROM prefixes WHERE id IN ({placeholders})',
            prefix_ids,
        ).fetchall()
        addresses = conn.execute(
            f'SELECT subnet_id, address_space_id FROM ip_addresses WHERE subnet_id IN ({placeholders})',
            prefix_ids,
        ).fetchall()
        pools = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE id = 'batch-failure-pool'"
        ).fetchall()
        audit_rows = conn.execute(
            f"""SELECT id FROM audit_events
                  WHERE event_type = 'ipam.prefix.resolve_address_space'
                    AND target_id IN ({placeholders})""",
            prefix_ids,
        ).fetchall()
    assert len(prefixes) == len(prefix_ids)
    assert all(row['address_space_id'] is None for row in prefixes)
    assert all(row['address_space_id'] is None for row in addresses)
    assert len(pools) == 1 and pools[0]['address_space_id'] is None
    assert audit_rows == []


def test_batch_prefix_mapping_rolls_back_when_second_prefix_update_violates_constraint(isolated_db):
    del isolated_db
    space, preview = _prepare_batch_failure_case()
    constraint = 'ipam_test_batch_prefix_update_failure'
    with get_db_connection() as conn:
        conn.execute(
            f"""ALTER TABLE prefixes ADD CONSTRAINT {constraint}
                 CHECK (id <> 'batch-failure-b' OR address_space_id IS NULL)"""
        )
        conn.commit()

    with pytest.raises(CheckViolation) as exc_info:
        _confirm_batch_failure_case(space, preview)

    assert exc_info.value.diag.constraint_name == constraint
    _assert_batch_failure_case_rolled_back()


def test_batch_prefix_mapping_rolls_back_when_second_ip_update_violates_constraint(isolated_db):
    del isolated_db
    space, preview = _prepare_batch_failure_case(second_prefix_has_ip=True)
    constraint = 'ipam_test_batch_ip_update_failure'
    with get_db_connection() as conn:
        conn.execute(
            f"""ALTER TABLE ip_addresses ADD CONSTRAINT {constraint}
                 CHECK (subnet_id <> 'batch-failure-b' OR address_space_id IS NULL)"""
        )
        conn.commit()

    with pytest.raises(CheckViolation) as exc_info:
        _confirm_batch_failure_case(space, preview)

    assert exc_info.value.diag.constraint_name == constraint
    _assert_batch_failure_case_rolled_back()


def test_batch_prefix_mapping_rolls_back_when_pool_rowcount_mismatches_preview(
    isolated_db, monkeypatch,
):
    del isolated_db
    space, preview = _prepare_batch_failure_case()
    original_factory = ipam_address_space_service.get_db_connection

    class _RowcountZeroCursor:
        def __init__(self, cursor):
            self._cursor = cursor

        @property
        def rowcount(self):
            return 0

        def __getattr__(self, name):
            return getattr(self._cursor, name)

    class _PoolRowcountMismatchConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, statement, params=None):
            cursor = self._connection.execute(statement, params)
            if 'UPDATE ipam_pools' in str(statement):
                return _RowcountZeroCursor(cursor)
            return cursor

        def __getattr__(self, name):
            return getattr(self._connection, name)

    monkeypatch.setattr(
        ipam_address_space_service,
        'get_db_connection',
        lambda: _PoolRowcountMismatchConnection(original_factory()),
    )
    with pytest.raises(ValueError, match='Pool rows for Prefix'):
        _confirm_batch_failure_case(space, preview)

    _assert_batch_failure_case_rolled_back()


def test_batch_prefix_mapping_rolls_back_when_commit_fails(isolated_db, monkeypatch):
    del isolated_db
    space, preview = _prepare_batch_failure_case(second_prefix_has_ip=True)
    original_factory = ipam_address_space_service.get_db_connection

    class _CommitFailureConnection:
        def __init__(self, connection):
            self._connection = connection

        def commit(self):
            raise RuntimeError('synthetic batch commit failure')

        def __getattr__(self, name):
            return getattr(self._connection, name)

    monkeypatch.setattr(
        ipam_address_space_service,
        'get_db_connection',
        lambda: _CommitFailureConnection(original_factory()),
    )
    with pytest.raises(RuntimeError, match='synthetic batch commit failure'):
        _confirm_batch_failure_case(space, preview)

    _assert_batch_failure_case_rolled_back()


def test_concurrent_batch_confirmation_commit_failure_is_atomic_and_retry_wins(
    isolated_db, monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event, local

    del isolated_db
    space, preview = _prepare_batch_failure_case(second_prefix_has_ip=True)
    original_factory = ipam_address_space_service.get_db_connection
    actor_context = local()
    start_together = Barrier(2)
    commit_failure_started = Event()
    retry_waiting_for_scope = Event()

    class _ConcurrentCommitFailureConnection:
        def __init__(self, connection):
            self._connection = connection

        def commit(self):
            if getattr(actor_context, 'actor', '') == 'failing-operator':
                commit_failure_started.set()
                if not retry_waiting_for_scope.wait(timeout=15):
                    raise RuntimeError('retry did not contend on the IPAM scope lock')
                raise RuntimeError('synthetic concurrent batch commit failure')
            return self._connection.commit()

        def __getattr__(self, name):
            return getattr(self._connection, name)

    def connection_for_actor():
        conn = original_factory()
        conn.execute("SET lock_timeout = '10s'")
        conn.execute("SET statement_timeout = '15s'")
        if getattr(actor_context, 'actor', '') == 'failing-operator':
            return _ConcurrentCommitFailureConnection(conn)
        return conn

    monkeypatch.setattr(
        ipam_address_space_service, 'get_db_connection', connection_for_actor,
    )
    original_scope_lock = ipam_address_space_service.lock_ipam_scope

    def signal_retry_scope_lock(conn, **kwargs):
        if getattr(actor_context, 'actor', '') == 'retrying-operator':
            retry_waiting_for_scope.set()
        return original_scope_lock(conn, **kwargs)

    monkeypatch.setattr(
        ipam_address_space_service, 'lock_ipam_scope', signal_retry_scope_lock,
    )

    def confirm(actor_username: str) -> dict:
        actor_context.actor = actor_username
        start_together.wait(timeout=8)
        if actor_username == 'retrying-operator':
            assert commit_failure_started.wait(timeout=15)
        try:
            result = resolve_prefix_address_space_batch(
                [
                    {
                        'prefix_id': item['prefix_id'],
                        'expected_updated_at': item['expected_updated_at'],
                        'expected_revision': item['expected_revision'],
                    }
                    for item in preview['items']
                ],
                address_space_id=space['id'],
                expected_target_revision=preview['expected_target_revision'],
                confirmed=True,
                security_tenant_id='tenant-default',
                audit_context={
                    'actor_id': actor_username,
                    'actor_username': actor_username,
                    'actor_role': 'Administrator',
                },
            )
            return {'actor': actor_username, 'status': 'committed', 'updated': result['updated']}
        except Exception as exc:
            return {'actor': actor_username, 'status': 'failed', 'error': str(exc)}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(confirm, actor)
            for actor in ('failing-operator', 'retrying-operator')
        ]
        outcomes = [future.result(timeout=45) for future in futures]

    assert [item['status'] for item in outcomes].count('committed') == 1
    assert [item['status'] for item in outcomes].count('failed') == 1
    assert any(
        'synthetic concurrent batch commit failure' in item.get('error', '')
        for item in outcomes
    )
    with get_db_connection() as conn:
        prefixes = conn.execute(
            "SELECT id, address_space_id FROM prefixes WHERE id IN ('batch-failure-a', 'batch-failure-b') ORDER BY id"
        ).fetchall()
        addresses = conn.execute(
            "SELECT subnet_id, address_space_id FROM ip_addresses WHERE subnet_id IN ('batch-failure-a', 'batch-failure-b') ORDER BY subnet_id"
        ).fetchall()
        pool = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE id = 'batch-failure-pool'"
        ).fetchone()
        audits = conn.execute(
            """SELECT target_id FROM audit_events
                 WHERE event_type = 'ipam.prefix.resolve_address_space'
                   AND target_id IN ('batch-failure-a', 'batch-failure-b') ORDER BY target_id"""
        ).fetchall()

    assert len(prefixes) == 2
    assert all(row['address_space_id'] == space['id'] for row in prefixes)
    assert len(addresses) == 2
    assert all(row['address_space_id'] == space['id'] for row in addresses)
    assert pool['address_space_id'] == space['id']
    assert [row['target_id'] for row in audits] == ['batch-failure-a', 'batch-failure-b']


def test_concurrent_batch_confirmation_late_failure_is_atomic_and_retry_wins(
    isolated_db, monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock

    del isolated_db
    space, preview = _prepare_batch_failure_case(second_prefix_has_ip=True)
    original_factory = ipam_address_space_service.get_db_connection

    def bounded_connection():
        conn = original_factory()
        conn.execute("SET lock_timeout = '10s'")
        conn.execute("SET statement_timeout = '15s'")
        return conn

    monkeypatch.setattr(ipam_address_space_service, 'get_db_connection', bounded_connection)
    original_log = ipam_address_space_service.log_audit_event
    failure_audit_calls = 0
    failure_counter_lock = Lock()

    def fail_second_audit_for_one_actor(**kwargs):
        nonlocal failure_audit_calls
        if kwargs.get('actor_username') == 'failing-operator':
            with failure_counter_lock:
                failure_audit_calls += 1
                should_fail = failure_audit_calls == 2
            if should_fail:
                raise RuntimeError('synthetic concurrent batch audit failure')
        return original_log(**kwargs)

    monkeypatch.setattr(
        ipam_address_space_service, 'log_audit_event', fail_second_audit_for_one_actor,
    )
    start_together = Barrier(2)

    def confirm(actor_username: str) -> dict:
        start_together.wait(timeout=8)
        try:
            result = resolve_prefix_address_space_batch(
                [
                    {
                        'prefix_id': item['prefix_id'],
                        'expected_updated_at': item['expected_updated_at'],
                        'expected_revision': item['expected_revision'],
                    }
                    for item in preview['items']
                ],
                address_space_id=space['id'],
                expected_target_revision=preview['expected_target_revision'],
                confirmed=True,
                security_tenant_id='tenant-default',
                audit_context={
                    'actor_id': actor_username,
                    'actor_username': actor_username,
                    'actor_role': 'Administrator',
                },
            )
            return {'actor': actor_username, 'status': 'committed', 'updated': result['updated']}
        except Exception as exc:
            return {'actor': actor_username, 'status': 'failed', 'error': str(exc)}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(confirm, actor)
            for actor in ('failing-operator', 'retrying-operator')
        ]
        outcomes = [future.result(timeout=45) for future in futures]

    assert [item['status'] for item in outcomes].count('committed') == 1
    assert [item['status'] for item in outcomes].count('failed') == 1
    assert failure_audit_calls in {0, 2}
    with get_db_connection() as conn:
        prefixes = conn.execute(
            """SELECT id, address_space_id FROM prefixes
                 WHERE id IN ('batch-failure-a', 'batch-failure-b') ORDER BY id"""
        ).fetchall()
        addresses = conn.execute(
            """SELECT subnet_id, address_space_id FROM ip_addresses
                 WHERE subnet_id IN ('batch-failure-a', 'batch-failure-b') ORDER BY subnet_id"""
        ).fetchall()
        pool = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE id = 'batch-failure-pool'"
        ).fetchone()
        audits = conn.execute(
            """SELECT target_id FROM audit_events
                 WHERE event_type = 'ipam.prefix.resolve_address_space'
                   AND target_id IN ('batch-failure-a', 'batch-failure-b')
                 ORDER BY target_id"""
        ).fetchall()

    assert len(prefixes) == 2
    assert all(row['address_space_id'] == space['id'] for row in prefixes)
    assert len(addresses) == 2
    assert all(row['address_space_id'] == space['id'] for row in addresses)
    assert pool['address_space_id'] == space['id']
    assert [row['target_id'] for row in audits] == ['batch-failure-a', 'batch-failure-b']


def test_concurrent_batch_confirmation_late_pool_failure_is_atomic_and_retry_wins(
    isolated_db, monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock, local

    del isolated_db
    space, preview = _prepare_batch_failure_case(second_prefix_has_ip=True)
    original_factory = ipam_address_space_service.get_db_connection
    actor_context = local()
    pool_failure_calls = 0
    failure_counter_lock = Lock()
    pool_update_started = Event()
    retry_waiting_for_scope = Event()

    class _LatePoolFailureConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, statement, params=None):
            nonlocal pool_failure_calls
            cursor = self._connection.execute(statement, params)
            if 'UPDATE ipam_pools' in str(statement) and cursor.rowcount > 0:
                with failure_counter_lock:
                    pool_failure_calls += 1
                pool_update_started.set()
                if not retry_waiting_for_scope.wait(timeout=15):
                    raise RuntimeError('retry did not contend on the IPAM scope lock')
                raise RuntimeError('synthetic concurrent batch pool failure')
            return cursor

        def __getattr__(self, name):
            return getattr(self._connection, name)

    def connection_for_actor():
        conn = original_factory()
        conn.execute("SET lock_timeout = '10s'")
        conn.execute("SET statement_timeout = '15s'")
        if getattr(actor_context, 'actor', '') == 'failing-operator':
            return _LatePoolFailureConnection(conn)
        return conn

    monkeypatch.setattr(
        ipam_address_space_service, 'get_db_connection', connection_for_actor,
    )
    original_scope_lock = ipam_address_space_service.lock_ipam_scope

    def signal_retry_scope_lock(conn, **kwargs):
        if getattr(actor_context, 'actor', '') == 'retrying-operator':
            retry_waiting_for_scope.set()
        return original_scope_lock(conn, **kwargs)

    monkeypatch.setattr(
        ipam_address_space_service, 'lock_ipam_scope', signal_retry_scope_lock,
    )

    def confirm(actor_username: str) -> dict:
        actor_context.actor = actor_username
        if actor_username == 'retrying-operator':
            assert pool_update_started.wait(timeout=15)
        try:
            result = resolve_prefix_address_space_batch(
                [
                    {
                        'prefix_id': item['prefix_id'],
                        'expected_updated_at': item['expected_updated_at'],
                        'expected_revision': item['expected_revision'],
                    }
                    for item in preview['items']
                ],
                address_space_id=space['id'],
                expected_target_revision=preview['expected_target_revision'],
                confirmed=True,
                security_tenant_id='tenant-default',
                audit_context={
                    'actor_id': actor_username,
                    'actor_username': actor_username,
                    'actor_role': 'Administrator',
                },
            )
            return {'actor': actor_username, 'status': 'committed', 'updated': result['updated']}
        except Exception as exc:
            return {'actor': actor_username, 'status': 'failed', 'error': str(exc)}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(confirm, actor)
            for actor in ('failing-operator', 'retrying-operator')
        ]
        outcomes = [future.result(timeout=45) for future in futures]

    assert [item['status'] for item in outcomes].count('committed') == 1
    assert [item['status'] for item in outcomes].count('failed') == 1
    assert pool_failure_calls == 1
    assert any('synthetic concurrent batch pool failure' in item.get('error', '') for item in outcomes)

    with get_db_connection() as conn:
        prefixes = conn.execute(
            """SELECT id, address_space_id FROM prefixes
                 WHERE id IN ('batch-failure-a', 'batch-failure-b') ORDER BY id"""
        ).fetchall()
        addresses = conn.execute(
            """SELECT subnet_id, address_space_id FROM ip_addresses
                 WHERE subnet_id IN ('batch-failure-a', 'batch-failure-b') ORDER BY subnet_id"""
        ).fetchall()
        pool = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE id = 'batch-failure-pool'"
        ).fetchone()
        audits = conn.execute(
            """SELECT target_id FROM audit_events
                 WHERE event_type = 'ipam.prefix.resolve_address_space'
                   AND target_id IN ('batch-failure-a', 'batch-failure-b')
                 ORDER BY target_id"""
        ).fetchall()

    assert len(prefixes) == 2
    assert all(row['address_space_id'] == space['id'] for row in prefixes)
    assert len(addresses) == 2
    assert all(row['address_space_id'] == space['id'] for row in addresses)
    assert pool['address_space_id'] == space['id']
    assert [row['target_id'] for row in audits] == ['batch-failure-a', 'batch-failure-b']


def test_concurrent_batch_confirmation_late_second_ip_failure_is_atomic_and_retry_wins(
    isolated_db, monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock, local

    del isolated_db
    space, preview = _prepare_batch_failure_case(second_prefix_has_ip=True)
    original_factory = ipam_address_space_service.get_db_connection
    actor_context = local()
    ip_update_calls = 0
    failure_counter_lock = Lock()
    second_ip_update_started = Event()
    retry_waiting_for_scope = Event()

    class _LateSecondIPFailureConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, statement, params=None):
            nonlocal ip_update_calls
            cursor = self._connection.execute(statement, params)
            if 'UPDATE ip_addresses' in str(statement) and cursor.rowcount > 0:
                with failure_counter_lock:
                    ip_update_calls += 1
                    should_fail = ip_update_calls == 2
                if should_fail:
                    second_ip_update_started.set()
                    if not retry_waiting_for_scope.wait(timeout=15):
                        raise RuntimeError('retry did not contend on the IPAM scope lock')
                    raise RuntimeError('synthetic concurrent second IP update failure')
            return cursor

        def __getattr__(self, name):
            return getattr(self._connection, name)

    def connection_for_actor():
        conn = original_factory()
        conn.execute("SET lock_timeout = '10s'")
        conn.execute("SET statement_timeout = '15s'")
        if getattr(actor_context, 'actor', '') == 'failing-operator':
            return _LateSecondIPFailureConnection(conn)
        return conn

    monkeypatch.setattr(
        ipam_address_space_service, 'get_db_connection', connection_for_actor,
    )
    original_scope_lock = ipam_address_space_service.lock_ipam_scope

    def signal_retry_scope_lock(conn, **kwargs):
        if getattr(actor_context, 'actor', '') == 'retrying-operator':
            retry_waiting_for_scope.set()
        return original_scope_lock(conn, **kwargs)

    monkeypatch.setattr(
        ipam_address_space_service, 'lock_ipam_scope', signal_retry_scope_lock,
    )

    def confirm(actor_username: str) -> dict:
        actor_context.actor = actor_username
        if actor_username == 'retrying-operator':
            assert second_ip_update_started.wait(timeout=15)
        try:
            result = resolve_prefix_address_space_batch(
                [
                    {
                        'prefix_id': item['prefix_id'],
                        'expected_updated_at': item['expected_updated_at'],
                        'expected_revision': item['expected_revision'],
                    }
                    for item in preview['items']
                ],
                address_space_id=space['id'],
                expected_target_revision=preview['expected_target_revision'],
                confirmed=True,
                security_tenant_id='tenant-default',
                audit_context={
                    'actor_id': actor_username,
                    'actor_username': actor_username,
                    'actor_role': 'Administrator',
                },
            )
            return {'actor': actor_username, 'status': 'committed', 'updated': result['updated']}
        except Exception as exc:
            return {'actor': actor_username, 'status': 'failed', 'error': str(exc)}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(confirm, actor)
            for actor in ('failing-operator', 'retrying-operator')
        ]
        outcomes = [future.result(timeout=45) for future in futures]

    assert [item['status'] for item in outcomes].count('committed') == 1
    assert [item['status'] for item in outcomes].count('failed') == 1
    assert ip_update_calls == 2
    assert any(
        'synthetic concurrent second IP update failure' in item.get('error', '')
        for item in outcomes
    )

    with get_db_connection() as conn:
        prefixes = conn.execute(
            """SELECT id, address_space_id FROM prefixes
                 WHERE id IN ('batch-failure-a', 'batch-failure-b') ORDER BY id"""
        ).fetchall()
        addresses = conn.execute(
            """SELECT subnet_id, address_space_id FROM ip_addresses
                 WHERE subnet_id IN ('batch-failure-a', 'batch-failure-b') ORDER BY subnet_id"""
        ).fetchall()
        pool = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE id = 'batch-failure-pool'"
        ).fetchone()
        audits = conn.execute(
            """SELECT target_id FROM audit_events
                 WHERE event_type = 'ipam.prefix.resolve_address_space'
                   AND target_id IN ('batch-failure-a', 'batch-failure-b')
                 ORDER BY target_id"""
        ).fetchall()

    assert len(prefixes) == 2
    assert all(row['address_space_id'] == space['id'] for row in prefixes)
    assert len(addresses) == 2
    assert all(row['address_space_id'] == space['id'] for row in addresses)
    assert pool['address_space_id'] == space['id']
    assert [row['target_id'] for row in audits] == ['batch-failure-a', 'batch-failure-b']

def test_concurrent_three_prefix_batch_late_failure_is_atomic_and_retry_wins(
    isolated_db, monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock, local

    del isolated_db
    space = _global_space("Concurrent three-prefix Global")
    prefix_rows = (
        ("batch-three-a", "10.82.80.0/24", "10.82.80.10"),
        ("batch-three-b", "10.82.90.0/24", "10.82.90.10"),
        ("batch-three-c", "10.82.100.0/24", "10.82.100.10"),
    )
    for prefix_id, cidr, address in prefix_rows:
        _legacy_prefix(prefix_id, cidr)
        create_address(prefix_id, address=address)
    _legacy_pool(
        "batch-three-pool", "batch-three-a", "10.82.80.20", "10.82.80.30",
    )
    prefix_ids = [prefix_id for prefix_id, _cidr, _address in prefix_rows]
    preview = preview_prefix_address_space_batch(
        prefix_ids,
        address_space_id=space["id"],
        security_tenant_id="tenant-default",
    )
    assert preview["can_confirm"] is True

    original_factory = ipam_address_space_service.get_db_connection
    actor_context = local()
    ip_update_calls = 0
    counter_lock = Lock()
    third_ip_update_started = Event()
    retry_waiting_for_scope = Event()

    class _LateThirdIPFailureConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, statement, params=None):
            nonlocal ip_update_calls
            cursor = self._connection.execute(statement, params)
            if "UPDATE ip_addresses" in str(statement) and cursor.rowcount > 0:
                with counter_lock:
                    ip_update_calls += 1
                    should_fail = ip_update_calls == 3
                if should_fail:
                    third_ip_update_started.set()
                    if not retry_waiting_for_scope.wait(timeout=15):
                        raise RuntimeError("retry did not contend on the IPAM scope lock")
                    raise RuntimeError("synthetic concurrent third IP update failure")
            return cursor

        def __getattr__(self, name):
            return getattr(self._connection, name)

    def connection_for_actor():
        conn = original_factory()
        conn.execute("SET lock_timeout = '10s'")
        conn.execute("SET statement_timeout = '15s'")
        if getattr(actor_context, "actor", "") == "failing-operator":
            return _LateThirdIPFailureConnection(conn)
        return conn

    monkeypatch.setattr(
        ipam_address_space_service, "get_db_connection", connection_for_actor,
    )
    original_scope_lock = ipam_address_space_service.lock_ipam_scope

    def signal_retry_scope_lock(conn, **kwargs):
        if getattr(actor_context, "actor", "") == "retrying-operator":
            retry_waiting_for_scope.set()
        return original_scope_lock(conn, **kwargs)

    monkeypatch.setattr(
        ipam_address_space_service, "lock_ipam_scope", signal_retry_scope_lock,
    )

    def confirm(actor_username: str) -> dict:
        actor_context.actor = actor_username
        if actor_username == "retrying-operator":
            assert third_ip_update_started.wait(timeout=15)
        try:
            result = resolve_prefix_address_space_batch(
                [
                    {
                        "prefix_id": item["prefix_id"],
                        "expected_updated_at": item["expected_updated_at"],
                        "expected_revision": item["expected_revision"],
                    }
                    for item in preview["items"]
                ],
                address_space_id=space["id"],
                expected_target_revision=preview["expected_target_revision"],
                confirmed=True,
                security_tenant_id="tenant-default",
                audit_context={
                    "actor_id": actor_username,
                    "actor_username": actor_username,
                    "actor_role": "Administrator",
                },
            )
            return {"actor": actor_username, "status": "committed", "updated": result["updated"]}
        except Exception as exc:
            return {"actor": actor_username, "status": "failed", "error": str(exc)}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(confirm, actor)
            for actor in ("failing-operator", "retrying-operator")
        ]
        outcomes = [future.result(timeout=45) for future in futures]

    assert [item["status"] for item in outcomes].count("committed") == 1
    assert [item["status"] for item in outcomes].count("failed") == 1
    assert ip_update_calls == 3
    assert any(
        "synthetic concurrent third IP update failure" in item.get("error", "")
        for item in outcomes
    )

    placeholders = ", ".join("?" for _ in prefix_ids)
    with get_db_connection() as conn:
        prefixes = conn.execute(
            f"SELECT id, address_space_id FROM prefixes WHERE id IN ({placeholders}) ORDER BY id",
            tuple(prefix_ids),
        ).fetchall()
        addresses = conn.execute(
            f"SELECT subnet_id, address_space_id FROM ip_addresses WHERE subnet_id IN ({placeholders}) ORDER BY subnet_id",
            tuple(prefix_ids),
        ).fetchall()
        pool = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE id = 'batch-three-pool'"
        ).fetchone()
        audits = conn.execute(
            f"""SELECT target_id FROM audit_events
                  WHERE event_type = 'ipam.prefix.resolve_address_space'
                    AND target_id IN ({placeholders}) ORDER BY target_id""",
            tuple(prefix_ids),
        ).fetchall()

    assert len(prefixes) == 3
    assert all(row["address_space_id"] == space["id"] for row in prefixes)
    assert len(addresses) == 3
    assert all(row["address_space_id"] == space["id"] for row in addresses)
    assert pool["address_space_id"] == space["id"]
    assert [row["target_id"] for row in audits] == sorted(prefix_ids)

def test_batch_prefix_address_space_confirmation_rolls_back_after_pool_constraint_failure(
    isolated_db,
):
    space = _global_space('Batch Pool Constraint Global')
    _legacy_prefix('batch-pool-failure-a', '10.82.30.0/24')
    _legacy_prefix('batch-pool-failure-b', '10.82.40.0/24')
    create_address('batch-pool-failure-a', address='10.82.30.10')
    _legacy_pool('batch-pool-failure-pool', 'batch-pool-failure-b', '10.82.40.10', '10.82.40.20')
    preview = preview_prefix_address_space_batch(
        ['batch-pool-failure-a', 'batch-pool-failure-b'],
        address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )

    with get_db_connection() as conn:
        conn.execute(
            """ALTER TABLE ipam_pools ADD CONSTRAINT ipam_test_batch_pool_mapping_failure
                 CHECK (id <> 'batch-pool-failure-pool' OR address_space_id IS NULL)"""
        )
        conn.commit()

    with pytest.raises(CheckViolation) as exc_info:
        resolve_prefix_address_space_batch(
            [
                {
                    'prefix_id': item['prefix_id'],
                    'expected_updated_at': item['expected_updated_at'],
                    'expected_revision': item['expected_revision'],
                }
                for item in preview['items']
            ],
            address_space_id=space['id'],
            expected_target_revision=preview['expected_target_revision'],
            confirmed=True,
            security_tenant_id='tenant-default',
            audit_context={'actor_id': 'operator-1', 'actor_username': 'operator', 'actor_role': 'Administrator'},
        )
    assert exc_info.value.diag.constraint_name == 'ipam_test_batch_pool_mapping_failure'

    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT id, address_space_id FROM prefixes
                 WHERE id IN ('batch-pool-failure-a', 'batch-pool-failure-b') ORDER BY id"""
        ).fetchall()
        addresses = conn.execute(
            "SELECT address_space_id FROM ip_addresses WHERE subnet_id = 'batch-pool-failure-a'"
        ).fetchall()
        pools = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE id = 'batch-pool-failure-pool'"
        ).fetchall()
        audit_rows = conn.execute(
            """SELECT id FROM audit_events
                 WHERE event_type = 'ipam.prefix.resolve_address_space'
                   AND target_id IN ('batch-pool-failure-a', 'batch-pool-failure-b')"""
        ).fetchall()
    assert all(row['address_space_id'] is None for row in rows)
    assert all(row['address_space_id'] is None for row in addresses)
    assert all(row['address_space_id'] is None for row in pools)
    assert audit_rows == []



@pytest.mark.parametrize(
    ('prefix_count', 'failure_ordinal'),
    ((4, 3), (5, 4), (6, 6), (8, 8), (10, 10), (12, 12), (16, 16), (100, 100)),
    ids=(
        'four-prefix-fails-on-third-ip',
        'five-prefix-fails-on-fourth-ip',
        'six-prefix-fails-on-sixth-ip',
        'eight-prefix-fails-on-eighth-ip',
        'ten-prefix-fails-on-tenth-ip',
        'twelve-prefix-fails-on-twelfth-ip',
        'sixteen-prefix-fails-on-sixteenth-ip',
        'maximum-batch-fails-on-hundredth-ip',
    ),
)
def test_concurrent_batch_confirmation_late_nth_ip_failure_is_atomic_and_retry_wins(
    isolated_db, monkeypatch, prefix_count: int, failure_ordinal: int,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock, local

    del isolated_db
    space = _global_space(f"Concurrent {prefix_count}-prefix Global")
    prefix_rows = []
    for index in range(prefix_count):
        third_octet = 80 + index
        prefix_id = f"batch-large-{prefix_count}-{index}"
        cidr = f"10.84.{third_octet}.0/24"
        address = f"10.84.{third_octet}.10"
        _legacy_prefix(prefix_id, cidr)
        create_address(prefix_id, address=address)
        prefix_rows.append((prefix_id, third_octet))

    pool_id = f"batch-large-pool-{prefix_count}"
    first_prefix_id, first_third_octet = prefix_rows[0]
    _legacy_pool(
        pool_id,
        first_prefix_id,
        f"10.84.{first_third_octet}.20",
        f"10.84.{first_third_octet}.30",
    )
    prefix_ids = [prefix_id for prefix_id, _third_octet in prefix_rows]
    preview = preview_prefix_address_space_batch(
        prefix_ids,
        address_space_id=space["id"],
        security_tenant_id="tenant-default",
    )
    assert preview["can_confirm"] is True

    original_factory = ipam_address_space_service.get_db_connection
    actor_context = local()
    ip_update_calls = 0
    counter_lock = Lock()
    nth_ip_update_started = Event()
    retry_waiting_for_scope = Event()

    class _LateNthIPFailureConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, statement, params=None):
            nonlocal ip_update_calls
            cursor = self._connection.execute(statement, params)
            if "UPDATE ip_addresses" in str(statement) and cursor.rowcount > 0:
                with counter_lock:
                    ip_update_calls += 1
                    should_fail = ip_update_calls == failure_ordinal
                if should_fail:
                    nth_ip_update_started.set()
                    if not retry_waiting_for_scope.wait(timeout=max(15, prefix_count * 2)):
                        raise RuntimeError("retry did not contend on the IPAM scope lock")
                    raise RuntimeError(
                        f"synthetic concurrent IP update failure at ordinal {failure_ordinal}"
                    )
            return cursor

        def __getattr__(self, name):
            return getattr(self._connection, name)

    def connection_for_actor():
        conn = original_factory()
        conn.execute("SET lock_timeout = '10s'")
        conn.execute("SET statement_timeout = '15s'")
        if getattr(actor_context, "actor", "") == "failing-operator":
            return _LateNthIPFailureConnection(conn)
        return conn

    monkeypatch.setattr(
        ipam_address_space_service, "get_db_connection", connection_for_actor,
    )
    original_scope_lock = ipam_address_space_service.lock_ipam_scope

    def signal_retry_scope_lock(conn, **kwargs):
        if getattr(actor_context, "actor", "") == "retrying-operator":
            retry_waiting_for_scope.set()
        return original_scope_lock(conn, **kwargs)

    monkeypatch.setattr(
        ipam_address_space_service, "lock_ipam_scope", signal_retry_scope_lock,
    )

    def confirm(actor_username: str) -> dict:
        actor_context.actor = actor_username
        if actor_username == "retrying-operator":
            assert nth_ip_update_started.wait(timeout=max(15, prefix_count * 2))
        try:
            result = resolve_prefix_address_space_batch(
                [
                    {
                        "prefix_id": item["prefix_id"],
                        "expected_updated_at": item["expected_updated_at"],
                        "expected_revision": item["expected_revision"],
                    }
                    for item in preview["items"]
                ],
                address_space_id=space["id"],
                expected_target_revision=preview["expected_target_revision"],
                confirmed=True,
                security_tenant_id="tenant-default",
                audit_context={
                    "actor_id": actor_username,
                    "actor_username": actor_username,
                    "actor_role": "Administrator",
                },
            )
            return {"actor": actor_username, "status": "committed", "updated": result["updated"]}
        except Exception as exc:
            return {"actor": actor_username, "status": "failed", "error": str(exc)}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(confirm, actor)
            for actor in ("failing-operator", "retrying-operator")
        ]
        outcomes = [future.result(timeout=max(45, prefix_count * 4)) for future in futures]

    assert [item["status"] for item in outcomes].count("committed") == 1
    assert [item["status"] for item in outcomes].count("failed") == 1
    assert ip_update_calls == failure_ordinal
    assert any(
        f"synthetic concurrent IP update failure at ordinal {failure_ordinal}"
        in item.get("error", "")
        for item in outcomes
    )

    placeholders = ", ".join("?" for _ in prefix_ids)
    with get_db_connection() as conn:
        prefixes = conn.execute(
            f"SELECT id, address_space_id FROM prefixes WHERE id IN ({placeholders}) ORDER BY id",
            tuple(prefix_ids),
        ).fetchall()
        addresses = conn.execute(
            f"SELECT subnet_id, address_space_id FROM ip_addresses WHERE subnet_id IN ({placeholders}) ORDER BY subnet_id",
            tuple(prefix_ids),
        ).fetchall()
        pool = conn.execute(
            "SELECT address_space_id FROM ipam_pools WHERE id = ?",
            (pool_id,),
        ).fetchone()
        audits = conn.execute(
            f"""SELECT target_id FROM audit_events
                  WHERE event_type = 'ipam.prefix.resolve_address_space'
                    AND target_id IN ({placeholders}) ORDER BY target_id""",
            tuple(prefix_ids),
        ).fetchall()

    assert len(prefixes) == prefix_count
    assert all(row["address_space_id"] == space["id"] for row in prefixes)
    assert len(addresses) == prefix_count
    assert all(row["address_space_id"] == space["id"] for row in addresses)
    assert pool["address_space_id"] == space["id"]
    assert [row["target_id"] for row in audits] == sorted(prefix_ids)
