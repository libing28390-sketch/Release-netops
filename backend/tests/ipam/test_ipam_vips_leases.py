from __future__ import annotations

import ipaddress
import json
import uuid

import pytest
from fastapi import HTTPException

from api import ipam as ipam_api
from core import rbac, tenant_policy
from database import get_db_connection
from database.migrations.m0310_ipam_vip_lease_scopes import upgrade as upgrade_vip_lease_scopes
from schemas.schemas import DHCPLeaseUpdate, VIPCreate, VIPUpdate
from services import ipam_service
from services.ipam_address_space_service import create_address_space
from services.ipam_service import (
    create_address,
    create_lease,
    create_pool,
    create_subnet,
    create_vip,
    update_lease,
)


def _space(*, tenant_id: str = 'tenant-default') -> dict:
    return create_address_space(
        name=f"VIP/lease test {uuid.uuid4().hex[:8]}",
        kind='global',
        vrf_id=None,
        security_tenant_id=tenant_id,
    )


def _prefix(prefix: str, *, space: dict, tenant_id: str = 'tenant-default', site_id: str | None = None) -> dict:
    return create_subnet(
        prefix=prefix,
        address_space_id=space['id'],
        tenant_id=tenant_id,
        site_id=site_id,
        name=f"VIP/lease prefix {uuid.uuid4().hex[:6]}",
    )


def _pool(prefix_id: str, start: str, end: str, *, mode: str = 'external_dhcp') -> dict:
    name = f"DHCP pool {uuid.uuid4().hex[:8]}"
    result = create_pool(
        name=name,
        prefix_id=prefix_id,
        start_ip=start,
        end_ip=end,
        management_mode=mode,
        allocation_allowed=False,
    )
    return {**result, 'name': name}


def _insert_legacy_vip(vip_id: str, address: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_vips
                   (id, address, vip_type, status, tenant_id, created_at, updated_at)
               VALUES (?, ?, 'vrrp', 'active', 'tenant-default', 'old', 'old')""",
            (vip_id, address),
        )
        conn.commit()


def _insert_legacy_lease(lease_id: str, address: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_dhcp_leases
                   (id, address, mac_address, hostname, dhcp_server, lease_state,
                    tenant_id, lease_start, lease_end, created_at, updated_at)
               VALUES (?, ?, '00:11:22:33:44:55', 'legacy', 'dhcp-old', 'active',
                       'tenant-default', '', '', 'old', 'old')""",
            (lease_id, address),
        )
        conn.commit()


def test_m0310_is_idempotent_and_keeps_legacy_vip_lease_pending(isolated_db) -> None:
    del isolated_db
    _insert_legacy_vip('legacy-vip-pending', '10.230.0.20')
    _insert_legacy_lease('legacy-lease-pending', '10.230.0.21')

    with get_db_connection() as conn:
        upgrade_vip_lease_scopes(conn.cursor(), True)
        upgrade_vip_lease_scopes(conn.cursor(), True)
        conn.commit()
        vip = conn.execute(
            "SELECT prefix_id, address_space_id, address_inet FROM ipam_vips WHERE id = ?",
            ('legacy-vip-pending',),
        ).fetchone()
        lease = conn.execute(
            "SELECT pool_id, address_space_id, external_id, scope_status FROM ipam_dhcp_leases WHERE id = ?",
            ('legacy-lease-pending',),
        ).fetchone()

    assert vip['prefix_id'] is None
    assert vip['address_space_id'] is None
    assert vip['address_inet'] is None
    assert lease['pool_id'] is None
    assert lease['address_space_id'] is None
    assert lease['external_id'] is None
    assert lease['scope_status'] == 'scope_unknown'


def test_m0310_legacy_vip_lease_catalog_failure_rolls_back_and_retry_is_idempotent(
    isolated_db,
) -> None:
    del isolated_db
    vip_columns = ("address_inet", "prefix_id", "address_space_id")
    lease_columns = ("address_space_id", "pool_id", "external_id", "scope_status")
    for index_name in (
        "uq_ipam_vips_space_host_active",
        "uq_ipam_dhcp_external_identity",
        "idx_ipam_vips_space_status",
        "idx_ipam_leases_scope_pool_state",
    ):
        with get_db_connection() as conn:
            conn.execute(f"DROP INDEX IF EXISTS {index_name}")
            conn.commit()
    for table_name, columns, constraints in (
        (
            "ipam_vips",
            vip_columns,
            (
                "fk_ipam_vips_prefix", "fk_ipam_vips_address_space",
                "ck_ipam_vips_scope_pair",
            ),
        ),
        (
            "ipam_dhcp_leases",
            lease_columns,
            (
                "fk_ipam_lease_address_space", "fk_ipam_lease_pool",
                "ck_ipam_lease_scope_status", "ck_ipam_lease_scope_link",
            ),
        ),
    ):
        with get_db_connection() as conn:
            for constraint in constraints:
                conn.execute(
                    f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS {constraint}"
                )
            for column in columns:
                conn.execute(
                    f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS {column} CASCADE"
                )
            conn.commit()

    _insert_legacy_vip("m0310-legacy-vip-rollback", "10.240.0.20")
    _insert_legacy_lease("m0310-legacy-lease-rollback", "10.240.0.21")

    def fail_after_m0310_ddl(cursor, use_pg: bool) -> None:
        upgrade_vip_lease_scopes(cursor, use_pg)
        raise RuntimeError("synthetic m0310 failure after DDL")

    with get_db_connection() as conn:
        with pytest.raises(RuntimeError, match="synthetic m0310 failure after DDL"):
            fail_after_m0310_ddl(conn.cursor(), use_pg=True)
        conn.rollback()
        vip_after_failure = {
            row["column_name"]
            for row in conn.execute(
                """SELECT column_name FROM information_schema.columns
                     WHERE table_schema = current_schema() AND table_name = 'ipam_vips'"""
            ).fetchall()
        }
        lease_after_failure = {
            row["column_name"]
            for row in conn.execute(
                """SELECT column_name FROM information_schema.columns
                     WHERE table_schema = current_schema() AND table_name = 'ipam_dhcp_leases'"""
            ).fetchall()
        }
        assert set(vip_columns).isdisjoint(vip_after_failure)
        assert set(lease_columns).isdisjoint(lease_after_failure)
        legacy_vip = conn.execute(
            "SELECT address, vip_type FROM ipam_vips WHERE id = ?",
            ("m0310-legacy-vip-rollback",),
        ).fetchone()
        legacy_lease = conn.execute(
            "SELECT address, mac_address FROM ipam_dhcp_leases WHERE id = ?",
            ("m0310-legacy-lease-rollback",),
        ).fetchone()
        assert legacy_vip["address"] == "10.240.0.20"
        assert legacy_vip["vip_type"] == "vrrp"
        assert legacy_lease["address"] == "10.240.0.21"
        assert legacy_lease["mac_address"] == "00:11:22:33:44:55"

        def catalog_snapshot() -> tuple:
            columns = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT table_name, column_name, data_type, is_nullable, column_default
                         FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name IN ('ipam_vips', 'ipam_dhcp_leases')
                        ORDER BY table_name, ordinal_position"""
                ).fetchall()
            )
            constraints = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT conrelid::regclass::text, conname,
                              pg_get_constraintdef(oid, true)
                         FROM pg_constraint
                        WHERE conrelid IN (
                            'ipam_vips'::regclass, 'ipam_dhcp_leases'::regclass
                        )
                        ORDER BY conrelid::regclass::text, conname"""
                ).fetchall()
            )
            indexes = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT tablename, indexname, indexdef FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND tablename IN ('ipam_vips', 'ipam_dhcp_leases')
                        ORDER BY tablename, indexname"""
                ).fetchall()
            )
            return columns, constraints, indexes

        upgrade_vip_lease_scopes(conn.cursor(), True)
        conn.commit()
        first_catalog = catalog_snapshot()
        upgrade_vip_lease_scopes(conn.cursor(), True)
        conn.commit()
        assert first_catalog == catalog_snapshot()
        vip = conn.execute(
            """SELECT address_inet, prefix_id, address_space_id
                 FROM ipam_vips WHERE id = ?""",
            ("m0310-legacy-vip-rollback",),
        ).fetchone()
        lease = conn.execute(
            """SELECT address_space_id, pool_id, external_id, scope_status
                 FROM ipam_dhcp_leases WHERE id = ?""",
            ("m0310-legacy-lease-rollback",),
        ).fetchone()

    assert tuple(vip) == (None, None, None)
    assert tuple(lease) == (None, None, None, "scope_unknown")

def test_vips_conflict_with_active_ip_and_vip_in_same_space_across_prefixes(isolated_db) -> None:
    del isolated_db
    space = _space()
    parent = _prefix('10.231.0.0/24', space=space)
    child = _prefix('10.231.0.0/25', space=space)
    create_address(child['id'], address='10.231.0.20')

    with pytest.raises(ValueError, match='allocated IP'):
        create_vip(address='10.231.0.20', vip_type='vrrp', prefix_id=parent['id'])

    first = create_vip(address='10.231.0.21', vip_type='vrrp', prefix_id=parent['id'])
    assert first['prefix_id'] == parent['id']
    assert first['address_space_id'] == space['id']
    assert first['prefix_cidr'] == parent['prefix']
    assert first['scope_pending'] is False
    with pytest.raises(ValueError, match='already registered'):
        create_vip(address='10.231.0.21', vip_type='vrrp', prefix_id=child['id'])


def test_same_vip_host_is_allowed_in_different_address_spaces_and_legacy_vip_does_not_block(isolated_db) -> None:
    del isolated_db
    _insert_legacy_vip('legacy-vip-same-host', '10.232.0.20')
    space_a = _space()
    space_b = _space()
    prefix_a = _prefix('10.232.0.0/24', space=space_a)
    prefix_b = _prefix('10.232.0.0/24', space=space_b)

    first = create_vip(address='10.232.0.20', vip_type='vrrp', prefix_id=prefix_a['id'])
    second = create_vip(address='10.232.0.20', vip_type='vrrp', prefix_id=prefix_b['id'])

    assert first['address_space_id'] == space_a['id']
    assert second['address_space_id'] == space_b['id']
    assert first['id'] != second['id']


def test_disabled_vip_does_not_occupy_or_block_its_address(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.238.0.0/24', space=space)
    disabled = create_vip(
        address='10.238.0.20', vip_type='vrrp', prefix_id=prefix['id'], status='disabled',
    )
    active = create_vip(
        address='10.238.0.20', vip_type='vrrp', prefix_id=prefix['id'], status='active',
    )
    assert disabled['id'] != active['id']
    with get_db_connection() as conn:
        subnet = dict(conn.execute('SELECT * FROM prefixes WHERE id = ?', (prefix['id'],)).fetchone())
        occupied, _ = ipam_service._current_allocation_occupancy(
            conn,
            subnet,
            ipaddress.ip_network(prefix['prefix']),
        )
    assert '10.238.0.20' in occupied

    released = ipam_service.update_vip(active['id'], status='disabled')
    assert released is True
    created = create_address(prefix['id'], address='10.238.0.20')
    assert created['address'] == '10.238.0.20'


def test_dhcp_lease_without_pool_is_pending_and_does_not_block_static_assignment(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.233.0.0/24', space=space)
    lease = create_lease(
        address='10.233.0.25', mac_address='00:11:22:33:44:55',
    )

    assert lease['pool_id'] is None
    assert lease['address_space_id'] is None
    assert lease['scope_status'] == 'scope_unknown'
    assert lease['scope_pending'] is True
    assigned = create_address(prefix['id'], address='10.233.0.25')
    assert assigned['address'] == '10.233.0.25'


def test_expired_or_unscoped_lease_never_releases_existing_static_address(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.239.0.0/24', space=space)
    address = create_address(prefix['id'], address='10.239.0.25')
    lease = create_lease(
        address='10.239.0.25',
        mac_address='00:11:22:33:44:55',
        lease_state='active',
        lease_start='2020-01-01T00:00:00+00:00',
        lease_end='2020-01-01T01:00:00+00:00',
    )
    assert lease['scope_status'] == 'scope_unknown'

    assert update_lease(
        lease['id'],
        expected_revision=1,
        lease_state='expired',
        lease_end='2020-01-01T01:00:00+00:00',
    )
    with get_db_connection() as conn:
        stored = conn.execute(
            'SELECT id, status, subnet_id FROM ip_addresses WHERE id = ?',
            (address['id'],),
        ).fetchone()
        stored_lease = conn.execute(
            'SELECT lease_state, scope_status FROM ipam_dhcp_leases WHERE id = ?',
            (lease['id'],),
        ).fetchone()

    assert stored['status'] == 'active'
    assert stored['subnet_id'] == prefix['id']
    assert stored_lease['lease_state'] == 'expired'
    assert stored_lease['scope_status'] == 'scope_unknown'


def test_external_dhcp_pool_lease_is_observation_and_external_id_is_idempotent(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.234.0.0/24', space=space)
    pool = _pool(prefix['id'], '10.234.0.20', '10.234.0.29')

    lease = create_lease(
        address='10.234.0.22', mac_address='00:11:22:33:44:55',
        dhcp_server='dhcp-east', external_id='lease-22', pool_id=pool['id'],
    )
    repeated = create_lease(
        address='10.234.0.22', mac_address='00:11:22:33:44:55',
        dhcp_server='dhcp-east', external_id='lease-22', pool_id=pool['id'],
    )
    assert lease['id'] == repeated['id']
    assert repeated['reused'] is True
    assert lease['pool_id'] == pool['id']
    assert lease['address_space_id'] == space['id']
    assert lease['scope_status'] == 'scope_resolved'
    assert lease['scope_pending'] is False
    assert lease['pool_name'] == pool['name']

    with get_db_connection() as conn:
        subnet = dict(conn.execute('SELECT * FROM prefixes WHERE id = ?', (prefix['id'],)).fetchone())
        occupied, _ = ipam_service._current_allocation_occupancy(
            conn,
            subnet,
            ipaddress.ip_network(prefix['prefix']),
        )
    assert '10.234.0.22' not in occupied
    with pytest.raises(ValueError, match='Pool'):
        create_address(prefix['id'], address='10.234.0.22')


def test_lease_pool_validation_update_and_empty_pool_clears_scope(isolated_db) -> None:
    del isolated_db
    space = _space()
    prefix = _prefix('10.235.0.0/24', space=space)
    pool = _pool(prefix['id'], '10.235.0.20', '10.235.0.29')
    wrong_policy = _pool(prefix['id'], '10.235.0.40', '10.235.0.49', mode='local_static')

    with pytest.raises(ValueError, match='external_dhcp'):
        create_lease(
            address='10.235.0.42', mac_address='00:11:22:33:44:55', pool_id=wrong_policy['id'],
        )
    with pytest.raises(ValueError, match='outside'):
        create_lease(
            address='10.235.0.42', mac_address='00:11:22:33:44:55', pool_id=pool['id'],
        )

    pending = create_lease(address='10.235.0.10', mac_address='00:11:22:33:44:55')
    assert update_lease(pending['id'], address='10.235.0.22', pool_id=pool['id'])
    with get_db_connection() as conn:
        mapped = conn.execute(
            'SELECT pool_id, address_space_id, scope_status FROM ipam_dhcp_leases WHERE id = ?',
            (pending['id'],),
        ).fetchone()
    assert mapped['pool_id'] == pool['id']
    assert mapped['address_space_id'] == space['id']
    assert mapped['scope_status'] == 'scope_resolved'

    assert update_lease(pending['id'], pool_id='')
    with get_db_connection() as conn:
        cleared = conn.execute(
            'SELECT pool_id, address_space_id, scope_status FROM ipam_dhcp_leases WHERE id = ?',
            (pending['id'],),
        ).fetchone()
    assert cleared['pool_id'] is None
    assert cleared['address_space_id'] is None
    assert cleared['scope_status'] == 'scope_unknown'
    with pytest.raises(ValueError, match='outside'):
        update_lease(pending['id'], address='10.235.0.40', pool_id=pool['id'])

    payload = DHCPLeaseUpdate(pool_id='', expected_revision=1)
    assert payload.model_dump(exclude_none=True) == {'pool_id': '', 'expected_revision': 1}


def test_api_tenant_scope_blocks_cross_tenant_vip_and_lease_crud(isolated_db, monkeypatch) -> None:
    del isolated_db
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-other', 'Other') ON CONFLICT (id) DO NOTHING")
        conn.commit()

    space_default = _space(tenant_id='tenant-default')
    space_other = _space(tenant_id='tenant-other')
    own_prefix = _prefix('10.236.0.0/24', space=space_default, tenant_id='tenant-default')
    foreign_prefix = _prefix('10.237.0.0/24', space=space_other, tenant_id='tenant-other')
    foreign_vip = create_vip(address='10.237.0.20', vip_type='vrrp', prefix_id=foreign_prefix['id'])
    foreign_pool = _pool(foreign_prefix['id'], '10.237.0.30', '10.237.0.39')
    foreign_lease = create_lease(
        address='10.237.0.31', mac_address='00:11:22:33:44:55',
        pool_id=foreign_pool['id'], tenant_id='tenant-other',
    )

    monkeypatch.setattr(tenant_policy, 'TENANT_ISOLATION_ENABLED', True)
    monkeypatch.setattr(rbac, 'TENANT_ISOLATION_ENABLED', True)
    user = {
        'id': f"tenant-scope-{uuid.uuid4().hex[:8]}",
        'role': 'Operator',
        'tenant_id': 'tenant-default',
        'scope_mode': 'legacy',
    }

    assert ipam_api.api_list_vips(
        q='', vip_type='', status='', prefix_id='', page=None, page_size=20, user=user,
    ) == []
    with pytest.raises(HTTPException) as create_denied:
        ipam_api.api_create_vip(
            VIPCreate(address='10.237.0.21', vip_type='vrrp', prefix_id=foreign_prefix['id']),
            user=user,
        )
    assert create_denied.value.status_code == 403
    with pytest.raises(HTTPException) as update_denied:
        ipam_api.api_update_vip(foreign_vip['id'], VIPUpdate(description='x', expected_revision=1), user=user)
    assert update_denied.value.status_code == 403
    with pytest.raises(HTTPException) as delete_denied:
        ipam_api.api_delete_vip(foreign_vip['id'], expected_revision=1, user=user)
    assert delete_denied.value.status_code == 403

    with pytest.raises(HTTPException) as lease_update_denied:
        ipam_api.api_update_lease(foreign_lease['id'], DHCPLeaseUpdate(hostname='x', expected_revision=1), user=user)
    assert lease_update_denied.value.status_code == 403
    with pytest.raises(HTTPException) as lease_create_denied:
        ipam_api.api_create_lease(
            body=ipam_api.DHCPLeaseCreate(
                address='10.237.0.32', mac_address='00:11:22:33:44:66', pool_id=foreign_pool['id'],
            ),
            user=user,
        )
    assert lease_create_denied.value.status_code == 403

    admin = {**user, 'role': 'Administrator'}
    with pytest.raises(HTTPException) as lease_delete_denied:
        ipam_api.api_delete_lease(foreign_lease['id'], expected_revision=1, user=admin)
    assert lease_delete_denied.value.status_code == 403
