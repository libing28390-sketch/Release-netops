from __future__ import annotations

import ipaddress
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api import ipam as ipam_api
from api.ipam import AllocationRequest, ReservationRequest
from database import get_db_connection
from database.migrations import run_migrations
from database.schema import _init_db_logic
from database.migrations.m0309_ipam_pool_range_policies import upgrade as upgrade_pool_policies
from schemas.schemas import IPAddressCreate, IPPoolCreate, IPPoolUpdate
from services.ipam_address_space_service import create_address_space
from services.ipam_service import (
    allocate_next_address,
    create_address,
    create_lease,
    create_pool,
    create_vip,
    create_subnet,
    get_next_available_ip_details,
    list_pools,
    reserve_address,
    update_pool,
)


def _space(name: str | None = None, *, tenant_id: str = 'tenant-default') -> dict:
    return create_address_space(
        name=name or f"Pool test {uuid.uuid4().hex[:8]}",
        kind='global',
        vrf_id=None,
        security_tenant_id=tenant_id,
    )


def _prefix(
    prefix: str,
    *,
    space: dict,
    gateway: str = '',
    tenant_id: str = 'tenant-default',
) -> dict:
    return create_subnet(
        prefix=prefix,
        address_space_id=space['id'],
        tenant_id=tenant_id,
        gateway=gateway,
        network_type='management',
        name='IPAM pool test prefix',
    )


def _pool(
    prefix_id: str,
    start_ip: str,
    end_ip: str,
    *,
    management_mode: str = 'local_static',
    allocation_allowed: bool = True,
    mark_populated: bool = False,
    mark_utilized: bool = False,
    status: str = 'active',
) -> dict:
    return create_pool(
        name=f"Pool {uuid.uuid4().hex[:8]}",
        prefix_id=prefix_id,
        start_ip=start_ip,
        end_ip=end_ip,
        management_mode=management_mode,
        allocation_allowed=allocation_allowed,
        mark_populated=mark_populated,
        mark_utilized=mark_utilized,
        status=status,
    )


def _insert_unmapped_prefix(prefix_id: str, prefix: str, tenant_id: str = 'tenant-default') -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO prefixes
                   (id, prefix, prefix_cidr, address_space_id, vrf_id, site_id, tenant_id,
                    status, name, created_at, updated_at)
               VALUES (?, ?, ?, NULL, NULL, NULL, ?, 'active', 'Legacy pool prefix', 'now', 'now')""",
            (prefix_id, prefix, prefix, tenant_id),
        )
        conn.commit()


def _insert_pool_row(
    pool_id: str,
    prefix_id: str,
    start_ip: str,
    end_ip: str,
    *,
    tenant_id: str = 'tenant-default',
) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_pools
                   (id, name, prefix_id, start_ip, end_ip, tenant_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'now', 'now')""",
            (pool_id, pool_id, prefix_id, start_ip, end_ip, tenant_id),
        )
        conn.commit()


def test_pool_create_requires_explicit_policy_and_rejects_external_allocation() -> None:
    with pytest.raises(ValidationError):
        IPPoolCreate(
            name='Missing policy', prefix_id='prefix',
            start_ip='192.0.2.1', end_ip='192.0.2.5',
        )

    with pytest.raises(ValidationError, match='must not allow local allocation'):
        IPPoolCreate(
            name='External DHCP', prefix_id='prefix',
            start_ip='192.0.2.1', end_ip='192.0.2.5',
            management_mode='external_dhcp', allocation_allowed=True,
        )

    with pytest.raises(ValidationError, match='Extra inputs are not permitted'):
        IPPoolCreate(
            name='Forged scope', prefix_id='prefix',
            start_ip='192.0.2.1', end_ip='192.0.2.5',
            management_mode='local_static', allocation_allowed=True,
            tenant_id='tenant-other', address_space_id='foreign-space',
        )


def test_pool_is_bound_to_prefix_space_and_lists_independent_policies(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.201.0.0/29', space=space, gateway='10.201.0.1')

    created = _pool(
        prefix['id'], '10.201.0.2', '10.201.0.4',
        mark_utilized=True,
    )

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT address_space_id, tenant_id, management_mode, allocation_allowed, mark_populated, mark_utilized "
            "FROM ipam_pools WHERE id = ?",
            (created['id'],),
        ).fetchone()
    assert row['address_space_id'] == space['id']
    assert row['tenant_id'] == 'tenant-default'
    assert row['management_mode'] == 'local_static'
    assert row['allocation_allowed'] is True
    assert row['mark_populated'] is False
    assert row['mark_utilized'] is True

    listed = list_pools(prefix_id=prefix['id'])
    assert len(listed) == 1
    assert listed[0]['address_space_id'] == space['id']
    assert listed[0]['policy_pending'] is False
    assert listed[0]['used_ips'] == 0
    assert listed[0]['utilization'] == 100.0


def test_parent_pool_utilization_counts_formal_addresses_bound_to_child_prefix(isolated_db) -> None:
    del isolated_db
    space = _space()
    parent = _prefix('10.212.0.0/24', space=space)
    child = _prefix('10.212.0.0/25', space=space)
    _pool(parent['id'], '10.212.0.20', '10.212.0.29')
    create_address(child['id'], address='10.212.0.25')

    listed = list_pools(prefix_id=parent['id'])
    assert listed[0]['used_ips'] == 1
    assert listed[0]['utilization'] == 10.0


def test_m0309_backfills_only_pools_with_mapped_same_tenant_prefix(isolated_db) -> None:
    del isolated_db
    space = _space()
    mapped = _prefix('10.202.0.0/24', space=space)
    _insert_unmapped_prefix('legacy-pool-prefix', '10.203.0.0/24')
    _insert_pool_row('legacy-mapped-pool', mapped['id'], '10.202.0.20', '10.202.0.30')
    _insert_pool_row('legacy-unmapped-pool', 'legacy-pool-prefix', '10.203.0.20', '10.203.0.30')

    with get_db_connection() as conn:
        upgrade_pool_policies(conn.cursor(), True)
        upgrade_pool_policies(conn.cursor(), True)
        rows = {
            row['id']: dict(row)
            for row in conn.execute(
                """SELECT id, address_space_id, management_mode, allocation_allowed,
                          mark_populated, mark_utilized
                     FROM ipam_pools WHERE id IN ('legacy-mapped-pool', 'legacy-unmapped-pool')"""
            ).fetchall()
        }
        conn.commit()

    assert rows['legacy-mapped-pool']['address_space_id'] == space['id']
    assert rows['legacy-unmapped-pool']['address_space_id'] is None
    for row in rows.values():
        assert row['management_mode'] is None
        assert row['allocation_allowed'] is None
        assert row['mark_populated'] is False
        assert row['mark_utilized'] is False


def test_m0309_upgrades_legacy_pool_catalog_preserves_row_and_is_idempotent(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix("10.208.0.0/24", space=space)
    legacy_pool_id = "m309-legacy-catalog-pool"
    added_columns = (
        "address_space_id", "management_mode", "allocation_allowed",
        "mark_populated", "mark_utilized",
    )
    constraints = (
        "fk_ipam_pools_address_space",
        "ck_ipam_pools_management_mode",
        "ck_ipam_pools_mode_allocation",
    )

    with get_db_connection() as conn:
        conn.execute("DROP INDEX IF EXISTS idx_ipam_pools_space_status")
        for constraint in constraints:
            conn.execute(f"ALTER TABLE ipam_pools DROP CONSTRAINT IF EXISTS {constraint}")
        for column in added_columns:
            conn.execute(f"ALTER TABLE ipam_pools DROP COLUMN IF EXISTS {column} CASCADE")
        conn.commit()

    _insert_pool_row(
        legacy_pool_id, prefix["id"], "10.208.0.20", "10.208.0.29",
    )
    with get_db_connection() as conn:
        legacy_columns = {
            row["column_name"]
            for row in conn.execute(
                """SELECT column_name FROM information_schema.columns
                     WHERE table_schema = current_schema()
                       AND table_name = 'ipam_pools'"""
            ).fetchall()
        }
        assert set(added_columns).isdisjoint(legacy_columns)

        upgrade_pool_policies(conn.cursor(), True)
        first_catalog = _m0309_pool_catalog_snapshot(conn)
        upgrade_pool_policies(conn.cursor(), True)
        second_catalog = _m0309_pool_catalog_snapshot(conn)
        row = conn.execute(
            """SELECT id, name, prefix_id, address_space_id, start_ip, end_ip,
                      tenant_id, management_mode, allocation_allowed,
                      mark_populated, mark_utilized
                 FROM ipam_pools WHERE id = ?""",
            (legacy_pool_id,),
        ).fetchone()
        conn.commit()

    assert first_catalog == second_catalog
    assert row["id"] == legacy_pool_id
    assert row["name"] == legacy_pool_id
    assert row["prefix_id"] == prefix["id"]
    assert row["address_space_id"] == space["id"]
    assert row["start_ip"] == "10.208.0.20"
    assert row["end_ip"] == "10.208.0.29"
    assert row["tenant_id"] == "tenant-default"
    assert row["management_mode"] is None
    assert row["allocation_allowed"] is None
    assert row["mark_populated"] is False
    assert row["mark_utilized"] is False


def _m0309_pool_catalog_snapshot(conn) -> tuple:
    columns = tuple(
        tuple(row)
        for row in conn.execute(
            """SELECT column_name, data_type, is_nullable, column_default
                 FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'ipam_pools'
                ORDER BY ordinal_position"""
        ).fetchall()
    )
    constraints = tuple(
        tuple(row)
        for row in conn.execute(
            """SELECT conname, pg_get_constraintdef(oid)
                 FROM pg_constraint
                WHERE conrelid = 'ipam_pools'::regclass
                ORDER BY conname"""
        ).fetchall()
    )
    indexes = tuple(
        tuple(row)
        for row in conn.execute(
            """SELECT indexname, indexdef FROM pg_indexes
                WHERE schemaname = current_schema() AND tablename = 'ipam_pools'
                ORDER BY indexname"""
        ).fetchall()
    )
    return columns, constraints, indexes


def test_m0309_fails_closed_on_parent_child_pool_range_overlap(isolated_db) -> None:
    del isolated_db
    space = _space()
    parent = _prefix('10.216.0.0/24', space=space)
    child = _prefix('10.216.0.0/25', space=space)
    _insert_pool_row('m309-overlap-parent', parent['id'], '10.216.0.20', '10.216.0.30')
    _insert_pool_row('m309-overlap-child', child['id'], '10.216.0.25', '10.216.0.35')

    with get_db_connection() as conn:
        with pytest.raises(RuntimeError, match='inclusive range overlap') as blocked:
            upgrade_pool_policies(conn.cursor(), True)
        assert 'm309-overlap-parent' in str(blocked.value)
        assert 'm309-overlap-child' in str(blocked.value)
        conn.rollback()


def test_adjacent_parent_child_pool_ranges_are_allowed(isolated_db) -> None:
    del isolated_db
    space = _space()
    parent = _prefix('10.218.0.0/24', space=space)
    child = _prefix('10.218.0.0/25', space=space)

    first = _pool(parent['id'], '10.218.0.20', '10.218.0.29')
    adjacent = _pool(child['id'], '10.218.0.30', '10.218.0.39')

    assert first['id'] != adjacent['id']
    listed = list_pools()
    scoped = {row['id']: row for row in listed if row['id'] in {first['id'], adjacent['id']}}
    assert set(scoped) == {first['id'], adjacent['id']}
    assert scoped[first['id']]['address_space_id'] == space['id']
    assert scoped[adjacent['id']]['address_space_id'] == space['id']


def test_pool_ranges_conflict_across_parent_child_prefixes_but_not_spaces(isolated_db) -> None:
    del isolated_db
    space_a = _space()
    parent = _prefix('10.204.0.0/24', space=space_a)
    child = _prefix('10.204.0.0/25', space=space_a)
    first = _pool(parent['id'], '10.204.0.20', '10.204.0.29')

    with pytest.raises(ValueError, match='overlaps existing Pool'):
        _pool(child['id'], '10.204.0.29', '10.204.0.35')

    space_b = _space()
    other_prefix = _prefix('10.204.0.0/24', space=space_b)
    second = _pool(other_prefix['id'], '10.204.0.20', '10.204.0.29')
    assert first['id'] != second['id']


@pytest.mark.parametrize(
    ('management_mode', 'allocation_allowed', 'mark_populated'),
    [
        ('reserved', False, False),
        ('external_dhcp', False, False),
        ('external_other', False, False),
        ('local_static', False, False),
        ('local_static', True, True),
    ],
)
def test_prefix_allocator_and_manual_create_respect_blocking_pool_policy(
    isolated_db, management_mode, allocation_allowed, mark_populated,
) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.205.0.0/29', space=space, gateway='10.205.0.1')
    _pool(
        prefix['id'], '10.205.0.2', '10.205.0.3',
        management_mode=management_mode,
        allocation_allowed=allocation_allowed,
        mark_populated=mark_populated,
    )

    assert get_next_available_ip_details(prefix['id'])['next_available_ip'] == '10.205.0.4'
    assert allocate_next_address(prefix['id'])['address'] == '10.205.0.4'
    with pytest.raises(ValueError, match='Pool that does not allow local allocation'):
        create_address(prefix['id'], address='10.205.0.2')


def test_policy_pending_range_blocks_automation_but_keeps_approved_manual_claim(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.206.0.0/29', space=space, gateway='10.206.0.1')
    _insert_pool_row('pending-policy-pool', prefix['id'], '10.206.0.2', '10.206.0.3')

    assert get_next_available_ip_details(prefix['id'])['next_available_ip'] == '10.206.0.4'
    listed = list_pools(prefix_id=prefix['id'])
    assert listed[0]['policy_pending'] is True
    assert create_address(prefix['id'], address='10.206.0.2')['address'] == '10.206.0.2'


@pytest.mark.parametrize('status', ['reserved', 'deprecated'])
def test_non_active_pool_status_blocks_automation_and_manual_registration(isolated_db, status: str) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.209.0.0/29', space=space, gateway='10.209.0.1')
    _pool(
        prefix['id'], '10.209.0.2', '10.209.0.3',
        status=status,
    )

    assert get_next_available_ip_details(prefix['id'])['next_available_ip'] == '10.209.0.4'
    with pytest.raises(ValueError, match='Pool that does not allow local allocation'):
        create_address(prefix['id'], address='10.209.0.2')


def test_blocking_pool_policies_cannot_hide_active_formal_addresses(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.213.0.0/29', space=space, gateway='10.213.0.1')
    create_address(prefix['id'], address='10.213.0.4')

    with pytest.raises(ValueError, match='1 active IP record.*ip-'):
        _pool(
            prefix['id'], '10.213.0.4', '10.213.0.5',
            management_mode='reserved', allocation_allowed=False,
        )

    pool = _pool(prefix['id'], '10.213.0.2', '10.213.0.3')
    create_address(prefix['id'], address='10.213.0.2')
    assert update_pool(pool['id'], mark_utilized=True) is True
    with pytest.raises(ValueError, match='1 active IP record.*ip-'):
        update_pool(pool['id'], mark_populated=True)
    with pytest.raises(ValueError, match='1 active IP record.*ip-'):
        update_pool(pool['id'], management_mode='external_dhcp', allocation_allowed=False)

    with get_db_connection() as conn:
        row = conn.execute(
            'SELECT management_mode, allocation_allowed, mark_populated, mark_utilized FROM ipam_pools WHERE id = ?',
            (pool['id'],),
        ).fetchone()
    assert row['management_mode'] == 'local_static'
    assert row['allocation_allowed'] is True
    assert row['mark_populated'] is False
    assert row['mark_utilized'] is True


def test_unknown_legacy_pool_status_is_fail_closed(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.210.0.0/29', space=space, gateway='10.210.0.1')
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_pools
                   (id, name, prefix_id, address_space_id, start_ip, end_ip, status,
                    management_mode, allocation_allowed, tenant_id, created_at, updated_at)
               VALUES ('unknown-status-pool', 'Unknown status', ?, ?, ?, ?, 'unexpected',
                       'local_static', TRUE, 'tenant-default', 'now', 'now')""",
            (prefix['id'], space['id'], '10.210.0.2', '10.210.0.3'),
        )
        conn.commit()

    assert get_next_available_ip_details(prefix['id'])['next_available_ip'] == '10.210.0.4'


def test_pool_list_update_and_delete_enforce_parent_prefix_scope(isolated_db, monkeypatch) -> None:
    del isolated_db
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants(id, name) VALUES ('tenant-other', 'Other') ON CONFLICT DO NOTHING")
        conn.commit()
    default_space = _space('Authorized Pool Global')
    other_space = _space('Other Pool Global', tenant_id='tenant-other')
    default_prefix = _prefix('10.211.0.0/24', space=default_space)
    other_prefix = _prefix(
        '10.211.0.0/24', space=other_space, tenant_id='tenant-other',
    )
    default_pool = _pool(default_prefix['id'], '10.211.0.10', '10.211.0.19')
    other_pool = create_pool(
        name='Other tenant pool', prefix_id=other_prefix['id'],
        start_ip='10.211.0.10', end_ip='10.211.0.19',
        management_mode='local_static', allocation_allowed=True,
    )
    user = {'id': 'pool-scope-user', 'username': 'pool-scope-user', 'role': 'Operator'}

    monkeypatch.setattr(
        ipam_api,
        'authorize_resource',
        lambda _user, _resource, _permission, **scope: scope.get('tenant_id') == 'tenant-default',
    )

    def deny_other_tenant(_user, _resource, _permission, **scope):
        if scope.get('tenant_id') != 'tenant-default':
            raise HTTPException(status_code=403, detail='denied')

    monkeypatch.setattr(ipam_api, 'enforce_resource_scope', deny_other_tenant)

    listed = ipam_api.api_list_pools(user=user)
    assert {item['id'] for item in listed} == {default_pool['id']}
    filtered = ipam_api.api_list_pools(
        q='Pool', status='active', prefix_id=default_prefix['id'],
        page=1, page_size=10, user=user,
    )
    assert {item['id'] for item in filtered['items']} == {default_pool['id']}
    with pytest.raises(HTTPException) as denied_list:
        ipam_api.api_list_pools(prefix_id=other_prefix['id'], user=user)
    assert denied_list.value.status_code == 403
    with pytest.raises(HTTPException) as denied_update:
        ipam_api.api_update_pool(
            other_pool['id'], IPPoolUpdate(name='Not visible', expected_revision=1), user=user,
        )
    assert denied_update.value.status_code == 403
    with pytest.raises(HTTPException) as denied_delete:
        ipam_api.api_delete_pool(other_pool['id'], expected_revision=1, user=user)
    assert denied_delete.value.status_code == 403

    with get_db_connection() as conn:
        other = conn.execute(
            'SELECT name FROM ipam_pools WHERE id = ?', (other_pool['id'],)
        ).fetchone()
    assert other['name'] == 'Other tenant pool'


def test_pool_id_next_and_allocate_require_scope_to_both_prefixes(isolated_db, monkeypatch) -> None:
    del isolated_db
    space = _space()
    with get_db_connection() as conn:
        for site_id in ('pool-scope-target-site', 'pool-scope-parent-site'):
            conn.execute(
                """INSERT INTO sites(id, site_code, site_name, tenant_id)
                   VALUES (?, ?, ?, 'tenant-default') ON CONFLICT(id) DO NOTHING""",
                (site_id, site_id.upper(), site_id),
            )
        conn.commit()
    parent = create_subnet(
        prefix='10.214.0.0/24', address_space_id=space['id'],
        site_id='pool-scope-parent-site', name='Pool scope parent',
    )
    target = create_subnet(
        prefix='10.214.0.0/25', address_space_id=space['id'],
        site_id='pool-scope-target-site', name='Pool scope child',
    )
    pool = _pool(parent['id'], '10.214.0.20', '10.214.0.29')
    user = {'id': 'pool-site-user', 'username': 'pool-site-user', 'role': 'Operator'}
    checked_scopes: list[tuple[str, str]] = []

    def deny_parent_site(_user, _resource, _permission, **scope):
        site = str(scope.get('site_id') or '')
        checked_scopes.append((str(scope.get('tenant_id') or ''), site))
        if site == 'pool-scope-parent-site':
            raise HTTPException(status_code=403, detail='pool parent site denied')

    monkeypatch.setattr(ipam_api, 'enforce_resource_scope', deny_parent_site)

    with pytest.raises(HTTPException) as denied_get:
        ipam_api.api_next_available_ip(
            target['id'], pool_id=pool['id'], _user=user,
        )
    assert denied_get.value.status_code == 403

    with pytest.raises(HTTPException) as denied_allocate:
        ipam_api.api_allocate_next_address(
            target['id'], body=AllocationRequest(pool_id=pool['id']), user=user,
        )
    assert denied_allocate.value.status_code == 403
    with pytest.raises(HTTPException) as denied_manual_create:
        ipam_api.api_create_address(
            target['id'],
            body=IPAddressCreate(address='10.214.0.20', pool_id=pool['id']),
            user=user,
        )
    assert denied_manual_create.value.status_code == 403
    with pytest.raises(HTTPException) as denied_manual_reserve:
        ipam_api.api_reserve_address(
            target['id'],
            body=ReservationRequest(address='10.214.0.20', pool_id=pool['id']),
            user=user,
        )
    assert denied_manual_reserve.value.status_code == 403
    assert ('tenant-default', 'pool-scope-target-site') in checked_scopes
    assert ('tenant-default', 'pool-scope-parent-site') in checked_scopes

    with get_db_connection() as conn:
        count = conn.execute('SELECT COUNT(*) AS count FROM ip_addresses').fetchone()
    assert int(count['count']) == 0

    with pytest.raises(HTTPException) as missing_pool:
        ipam_api.api_next_available_ip(
            target['id'], pool_id='missing-pool-id', _user=user,
        )
    assert missing_pool.value.status_code == 404


def test_mark_utilized_does_not_block_pool_allocation_and_pool_id_bounds_candidate(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.207.0.0/29', space=space, gateway='10.207.0.1')
    pool = _pool(
        prefix['id'], '10.207.0.2', '10.207.0.4', mark_utilized=True,
    )

    assert get_next_available_ip_details(prefix['id'])['next_available_ip'] == '10.207.0.2'
    assert get_next_available_ip_details(prefix['id'], pool_id=pool['id'])['next_available_ip'] == '10.207.0.2'
    create_address(prefix['id'], address='10.207.0.2')
    assert get_next_available_ip_details(prefix['id'], pool_id=pool['id'])['next_available_ip'] == '10.207.0.3'
    assert allocate_next_address(prefix['id'], pool_id=pool['id'])['address'] == '10.207.0.3'

    with pytest.raises(ValueError, match='not active in this address space'):
        allocate_next_address(prefix['id'], pool_id='missing-pool')
    with pytest.raises(ValueError, match='must not allow local allocation'):
        update_pool(pool['id'], management_mode='external_dhcp', allocation_allowed=True)


def test_manual_create_and_reserve_with_pool_id_are_bounded(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.215.0.0/29', space=space, gateway='10.215.0.1')
    pool = _pool(prefix['id'], '10.215.0.2', '10.215.0.3')

    registered = create_address(
        prefix['id'], address='10.215.0.2', pool_id=pool['id'],
    )
    reserved = reserve_address(
        prefix['id'], address='10.215.0.3', pool_id=pool['id'],
    )
    assert registered['address'] == '10.215.0.2'
    assert reserved['address'] == '10.215.0.3'
    with pytest.raises(ValueError, match='outside the selected Pool range'):
        create_address(prefix['id'], address='10.215.0.4', pool_id=pool['id'])
    with pytest.raises(ValueError, match='outside the selected Pool range'):
        reserve_address(prefix['id'], address='10.215.0.5', pool_id=pool['id'])

    other_space = _space()
    other_prefix = _prefix('10.215.0.0/29', space=other_space)
    with pytest.raises(ValueError, match='not in this address space'):
        create_address(other_prefix['id'], address='10.215.0.2', pool_id=pool['id'])


def test_ipv6_64_pool_candidate_is_bounded_without_enumerating_subnet(isolated_db, monkeypatch) -> None:
    del isolated_db

    def reject_network_iteration(_network):
        pytest.fail('pool candidate selection must not enumerate an IPv6 /64')

    monkeypatch.setattr(ipaddress.IPv6Network, '__iter__', reject_network_iteration)
    space = _space()
    prefix = _prefix('2001:db8:212::/64', space=space)
    pool = _pool(prefix['id'], '2001:db8:212::10', '2001:db8:212::20')

    assert get_next_available_ip_details(prefix['id'], pool_id=pool['id'])['next_available_ip'] == '2001:db8:212::10'
    assert allocate_next_address(prefix['id'], pool_id=pool['id'])['address'] == '2001:db8:212::10'


@pytest.mark.parametrize(
    ('cidr', 'start_ip', 'end_ip'),
    [
        ('198.51.100.20/31', '198.51.100.20', '198.51.100.21'),
        ('198.51.100.22/32', '198.51.100.22', '198.51.100.22'),
        ('2001:db8:212:1::/127', '2001:db8:212:1::', '2001:db8:212:1::1'),
        ('2001:db8:212:1::2/128', '2001:db8:212:1::2', '2001:db8:212:1::2'),
    ],
    ids=['ipv4-31-both-hosts', 'ipv4-32-single-host', 'ipv6-127-both-hosts', 'ipv6-128-single-host'],
)
def test_pool_range_accepts_minimum_ipv4_ipv6_prefix_boundaries(
    isolated_db, cidr: str, start_ip: str, end_ip: str,
) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix(cidr, space=space)

    pool = _pool(prefix['id'], start_ip, end_ip)

    assert pool['id']
    listed = list_pools(prefix_id=prefix['id'])
    assert len(listed) == 1
    assert listed[0]['start_ip'] == start_ip
    assert listed[0]['end_ip'] == end_ip


def test_pool_range_update_rechecks_cross_prefix_overlap_and_space_move(isolated_db) -> None:
    del isolated_db
    space_a = _space()
    parent = _prefix('10.208.0.0/24', space=space_a)
    child = _prefix('10.208.0.0/25', space=space_a)
    first = _pool(parent['id'], '10.208.0.20', '10.208.0.29')
    second = _pool(parent['id'], '10.208.0.40', '10.208.0.49')

    with pytest.raises(ValueError, match='overlaps existing Pool'):
        update_pool(second['id'], start_ip='10.208.0.29', end_ip='10.208.0.39')

    with get_db_connection() as conn:
        unchanged = conn.execute(
            'SELECT prefix_id, start_ip, end_ip FROM ipam_pools WHERE id = ?',
            (second['id'],),
        ).fetchone()
    assert unchanged['prefix_id'] == parent['id']
    assert unchanged['start_ip'] == '10.208.0.40'

    moved_within_space = update_pool(
        second['id'], prefix_id=child['id'], start_ip='10.208.0.70', end_ip='10.208.0.79',
    )
    assert moved_within_space is True

    space_b = _space()
    other_prefix = _prefix('10.208.0.0/24', space=space_b)
    with pytest.raises(ValueError, match='requires an explicit mapping preview'):
        update_pool(second['id'], prefix_id=other_prefix['id'], start_ip='10.208.0.80', end_ip='10.208.0.89')



def _ipam_migration_catalog_snapshot(conn) -> dict[str, tuple]:
    tables = (
        "prefixes",
        "ip_addresses",
        "ipam_pools",
        "ipam_vips",
        "ipam_dhcp_leases",
        "ipam_idempotency_records",
    )
    snapshot = {}
    for table in tables:
        columns = tuple(
            tuple(row)
            for row in conn.execute(
                """SELECT column_name, data_type, is_nullable, column_default
                     FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = ?
                    ORDER BY column_name""",
                (table,),
            ).fetchall()
        )
        constraints = tuple(
            tuple(row)
            for row in conn.execute(
                """SELECT conname, pg_get_constraintdef(oid), convalidated
                     FROM pg_constraint
                    WHERE conrelid = to_regclass(?)
                    ORDER BY conname""",
                (table,),
            ).fetchall()
        )
        indexes = tuple(
            tuple(row)
            for row in conn.execute(
                """SELECT indexname, indexdef
                     FROM pg_indexes
                    WHERE schemaname = current_schema() AND tablename = ?
                    ORDER BY indexname""",
                (table,),
            ).fetchall()
        )
        snapshot[table] = (columns, constraints, indexes)
    return snapshot


def test_m0309_m0310_m0311_adjacent_global_upgrade_preserves_legacy_rows(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix("10.217.0.0/24", space=space, gateway="10.217.0.1")
    address = create_address(prefix["id"], address="10.217.0.10")
    pool = _pool(
        prefix["id"], "10.217.0.20", "10.217.0.29",
        management_mode="external_dhcp", allocation_allowed=False,
    )
    vip = create_vip(
        address="10.217.0.30", vip_type="vrrp", prefix_id=prefix["id"],
    )
    lease = create_lease(
        address="10.217.0.21", mac_address="00:11:22:33:44:55",
        hostname="legacy-dhcp-host", dhcp_server="dhcp-global",
        pool_id=pool["id"], external_id="legacy-global-lease",
    )

    with get_db_connection() as conn:
        original_catalog = _ipam_migration_catalog_snapshot(conn)
        for constraint in (
            "fk_ipam_pools_address_space",
            "ck_ipam_pools_management_mode",
            "ck_ipam_pools_mode_allocation",
            "fk_ip_addresses_pool",
            "fk_ip_addresses_device",
            "fk_ip_addresses_interface",
        ):
            pool_constraints = constraint.startswith(("fk_ipam_pools", "ck_ipam_pools"))
            table = "ipam_pools" if pool_constraints else "ip_addresses"
            conn.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        for column in (
            "address_space_id", "management_mode", "allocation_allowed",
            "mark_populated", "mark_utilized",
        ):
            conn.execute(f"ALTER TABLE ipam_pools DROP COLUMN IF EXISTS {column} CASCADE")
        for column in ("address_inet", "prefix_id", "address_space_id"):
            conn.execute(f"ALTER TABLE ipam_vips DROP COLUMN IF EXISTS {column} CASCADE")
        for column in ("address_space_id", "pool_id", "external_id", "scope_status"):
            conn.execute(f"ALTER TABLE ipam_dhcp_leases DROP COLUMN IF EXISTS {column} CASCADE")
        for table in ("prefixes", "ip_addresses", "ipam_pools", "ipam_vips", "ipam_dhcp_leases"):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS revision CASCADE")
        conn.execute("ALTER TABLE ip_addresses DROP COLUMN IF EXISTS pool_id CASCADE")
        conn.execute("DROP TABLE ipam_idempotency_records CASCADE")
        conn.execute("DELETE FROM schema_migrations WHERE version IN (309, 310, 311)")
        conn.commit()
        _init_db_logic(conn, allow_legacy_import=False)
        conn.commit()

        assert run_migrations(conn, use_pg=True, strict_history=True) == 3
        upgraded_catalog = _ipam_migration_catalog_snapshot(conn)
        assert run_migrations(conn, use_pg=True, strict_history=True) == 0
        repeated_catalog = _ipam_migration_catalog_snapshot(conn)
        rows = {
            "prefix": conn.execute(
                "SELECT address_space_id, revision FROM prefixes WHERE id = ?",
                (prefix["id"],),
            ).fetchone(),
            "address": conn.execute(
                "SELECT address, revision, pool_id FROM ip_addresses WHERE id = ?",
                (address["id"],),
            ).fetchone(),
            "pool": conn.execute(
                """SELECT address_space_id, management_mode, allocation_allowed,
                          mark_populated, mark_utilized, revision
                     FROM ipam_pools WHERE id = ?""",
                (pool["id"],),
            ).fetchone(),
            "vip": conn.execute(
                """SELECT address, address_inet, prefix_id, address_space_id, revision
                     FROM ipam_vips WHERE id = ?""",
                (vip["id"],),
            ).fetchone(),
            "lease": conn.execute(
                """SELECT address, address_space_id, pool_id, external_id,
                          scope_status, revision
                     FROM ipam_dhcp_leases WHERE id = ?""",
                (lease["id"],),
            ).fetchone(),
        }
        conn.commit()

    for table_name, original_parts in original_catalog.items():
        upgraded_parts = upgraded_catalog[table_name]
        for part_name, original_part, upgraded_part in zip(
            ("columns", "constraints", "indexes"), original_parts, upgraded_parts,
        ):
            assert upgraded_part == original_part, (
                f"{table_name} {part_name} differ after m0309-m0311: "
                f"expected={original_part!r}; actual={upgraded_part!r}"
            )
    assert upgraded_catalog == repeated_catalog
    assert rows["prefix"]["address_space_id"] == space["id"]
    assert rows["prefix"]["revision"] == 1
    assert rows["address"]["address"] == "10.217.0.10"
    assert rows["address"]["revision"] == 1
    assert rows["address"]["pool_id"] is None
    assert rows["pool"]["address_space_id"] == space["id"]
    assert rows["pool"]["management_mode"] is None
    assert rows["pool"]["allocation_allowed"] is None
    assert rows["pool"]["mark_populated"] is False
    assert rows["pool"]["mark_utilized"] is False
    assert rows["pool"]["revision"] == 1
    assert rows["vip"]["address"] == "10.217.0.30"
    assert rows["vip"]["address_inet"] is None
    assert rows["vip"]["prefix_id"] is None
    assert rows["vip"]["address_space_id"] is None
    assert rows["vip"]["revision"] == 1
    assert rows["lease"]["address"] == "10.217.0.21"
    assert rows["lease"]["address_space_id"] is None
    assert rows["lease"]["pool_id"] is None
    assert rows["lease"]["external_id"] is None
    assert rows["lease"]["scope_status"] == "scope_unknown"
    assert rows["lease"]["revision"] == 1
