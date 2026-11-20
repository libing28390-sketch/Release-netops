from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api import ipam as ipam_api
from database import get_db_connection
from database.migrations.m0319_ipam_fhrp_groups import VERSION, upgrade
from schemas.schemas import IPAMFHRPGroupCreate, IPAMFHRPGroupUpdate
from services import ipam_fhrp_group_service as group_service
from services.ipam_current_fhrp_observation_service import (
    begin_current_fhrp_collection,
    finish_current_fhrp_collection,
)
from services.ipam_address_space_service import create_address_space
from services.ipam_service import create_address, delete_vip, update_vip


def _id(prefix: str) -> str:
    return f'{prefix}-{uuid.uuid4().hex[:12]}'


def _tenant(tenant_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            'INSERT INTO tenants (id, name) VALUES (?, ?) ON CONFLICT (id) DO NOTHING',
            (tenant_id, tenant_id),
        )
        conn.commit()


def _site(site_id: str, tenant_id: str = 'tenant-default') -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, tenant_id)
               VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING""",
            (site_id, site_id.upper(), site_id, tenant_id),
        )
        conn.commit()


def _space(name: str, *, tenant_id: str = 'tenant-default') -> dict:
    if tenant_id != 'tenant-default':
        _tenant(tenant_id)
    return create_address_space(
        name=name,
        kind='global',
        vrf_id=None,
        security_tenant_id=tenant_id,
    )


def _prefix(
    space: dict,
    *, tenant_id: str = 'tenant-default', site_id: str | None = None,
    cidr: str = '172.16.0.0/24',
) -> tuple[str, int]:
    if site_id is None:
        site_id = _id('fhrp-site')
    _site(site_id, tenant_id)
    prefix_id = _id('fhrp-prefix')
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO prefixes
                   (id, prefix, prefix_cidr, address_space_id, vrf_id, site_id,
                    tenant_id, status, name, created_at, updated_at)
               VALUES (?, ?, ?, ?, NULL, ?, ?, 'active', ?, '2026-11-09', '2026-11-09')""",
            (prefix_id, cidr, cidr, space['id'], site_id, tenant_id, prefix_id),
        )
        conn.commit()
    return prefix_id, 0


def _device(
    *, tenant_id: str = 'tenant-default', site_id: str | None = None,
) -> tuple[str, str]:
    if tenant_id != 'tenant-default':
        _tenant(tenant_id)
    if site_id is None:
        site_id = _id('fhrp-device-site')
        _site(site_id, tenant_id)
    device_id = _id('fhrp-device')
    host_number = int(uuid.uuid4().hex[:6], 16) % (256 * 256)
    ip_address = f'198.18.{host_number // 256}.{host_number % 256}'
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices
                   (id, hostname, ip_address, platform, status, site_id, tenant_id)
               VALUES (?, ?, ?, 'cisco_ios', 'online', ?, ?)""",
            (device_id, device_id, ip_address, site_id, tenant_id),
        )
        conn.commit()
    return device_id, site_id


def _interface(device_id: str, name: str) -> str:
    interface_id = _id('fhrp-interface')
    with get_db_connection() as conn:
        conn.execute(
            'INSERT INTO interfaces (id, device_id, interface_name) VALUES (?, ?, ?)',
            (interface_id, device_id, name),
        )
        conn.commit()
    return interface_id


def _vip(
    *, vip_id: str, prefix_id: str, address: str,
    space_id: str, tenant_id: str = 'tenant-default', protocol: str = 'vrrp',
) -> str:
    now = '2026-11-09T00:00:00+00:00'
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_vips
                   (id, address, address_inet, prefix_id, address_space_id,
                    vip_type, status, tenant_id, created_at, updated_at)
               VALUES (?, ?, CAST(? AS inet), ?, ?, ?, 'active', ?, ?, ?)""",
            (vip_id, address, address, prefix_id, space_id, protocol, tenant_id, now, now),
        )
        conn.commit()
    return vip_id


def _group(
    space: dict,
    *, group_type: str = 'fhrp', protocol: str = 'vrrp',
    group_id: str = '17', tenant_id: str = 'tenant-default',
    family: int = 4, display_name: str = '', key: str | None = None,
) -> dict:
    return group_service.create_fhrp_group(
        address_space_id=space['id'],
        security_tenant_id=tenant_id,
        group_type=group_type,
        protocol=protocol,
        group_id=group_id,
        address_family=family,
        display_name=display_name,
        idempotency_key=key,
        audit_context={
            'actor_username': 'fhrp-test-operator',
            'actor_role': 'Operator',
        },
    )


def _add_member(
    group: dict,
    *,
    device_id: str,
    interface_name: str,
    interface_id: str | None = None,
    role: str | None = None,
    priority: int | None = None,
    expected_revision: int | None = None,
    key: str | None = None,
    tenant_id: str = 'tenant-default',
) -> dict:
    return group_service.add_fhrp_group_member(
        group['id'],
        security_tenant_id=tenant_id,
        expected_revision=expected_revision or int(group['revision']),
        device_id=device_id,
        interface_name=interface_name,
        interface_id=interface_id,
        role=role,
        priority=priority,
        idempotency_key=key,
        audit_context={
            'actor_username': 'fhrp-test-operator',
            'actor_role': 'Operator',
        },
    )


def _attach_vip(
    group: dict, vip_id: str, *, expected_revision: int | None = None,
    key: str | None = None, tenant_id: str = 'tenant-default',
) -> dict:
    return group_service.attach_fhrp_group_vip(
        group['id'],
        security_tenant_id=tenant_id,
        expected_revision=expected_revision or int(group['revision']),
        vip_id=vip_id,
        idempotency_key=key,
        audit_context={
            'actor_username': 'fhrp-test-operator',
            'actor_role': 'Operator',
        },
    )


def test_m0319_fresh_install_and_repeat_upgrade_are_idempotent(isolated_db):
    del isolated_db
    with get_db_connection() as conn:
        applied = conn.execute(
            'SELECT name FROM schema_migrations WHERE version = ?', (VERSION,),
        ).fetchone()
        assert applied and applied['name'] == 'ipam_fhrp_groups'

        cursor = conn.cursor()
        upgrade(cursor, True)
        conn.commit()
        upgrade(cursor, True)
        conn.commit()

        tables = {
            str(row['table_name'])
            for row in conn.execute(
                """SELECT table_name FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name IN (
                        'ipam_fhrp_groups', 'ipam_fhrp_group_members',
                        'ipam_fhrp_group_vips'
                      )"""
            ).fetchall()
        }
        assert tables == {
            'ipam_fhrp_groups', 'ipam_fhrp_group_members', 'ipam_fhrp_group_vips',
        }
        group_indexes = conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() AND tablename = 'ipam_fhrp_groups'"
        ).fetchall()
    assert not any(
        'UNIQUE' in str(row['indexdef']).upper()
        and 'PROTOCOL' in str(row['indexdef']).upper()
        and 'GROUP_ID' in str(row['indexdef']).upper()
        for row in group_indexes
    )


def test_m0319_global_catalog_failure_rolls_back_and_retry_is_idempotent(isolated_db):
    from database.migrations import discover_migrations

    del isolated_db
    tables = (
        "ipam_fhrp_group_vips",
        "ipam_fhrp_group_members",
        "ipam_fhrp_groups",
    )
    with get_db_connection() as conn:
        for table_name in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute("DROP INDEX IF EXISTS uq_ipam_address_spaces_id_tenant")
        conn.commit()

    def fail_after_m0319_ddl(cursor, use_pg: bool) -> None:
        upgrade(cursor, use_pg)
        raise RuntimeError("synthetic m0319 failure after DDL")

    with get_db_connection() as conn:
        with pytest.raises(RuntimeError, match="synthetic m0319 failure after DDL"):
            fail_after_m0319_ddl(conn.cursor(), use_pg=True)
        conn.rollback()
        for table_name in tables:
            assert conn.execute(
                "SELECT to_regclass(?)", (table_name,),
            ).fetchone()[0] is None
        assert conn.execute(
            """SELECT 1 FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname = 'uq_ipam_address_spaces_id_tenant'"""
        ).fetchone() is None

        def catalog_snapshot() -> tuple:
            columns = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT table_name, column_name, data_type, is_nullable, column_default
                         FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name IN (
                              'ipam_fhrp_groups', 'ipam_fhrp_group_members',
                              'ipam_fhrp_group_vips'
                          )
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
                            'ipam_fhrp_groups'::regclass,
                            'ipam_fhrp_group_members'::regclass,
                            'ipam_fhrp_group_vips'::regclass
                        )
                        ORDER BY conrelid::regclass::text, conname"""
                ).fetchall()
            )
            indexes = tuple(
                tuple(row)
                for row in conn.execute(
                    """SELECT tablename, indexname, indexdef FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND (tablename IN (
                              'ipam_fhrp_groups', 'ipam_fhrp_group_members',
                              'ipam_fhrp_group_vips'
                          ) OR indexname = 'uq_ipam_address_spaces_id_tenant')
                        ORDER BY tablename, indexname"""
                ).fetchall()
            )
            return columns, constraints, indexes

        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        first_catalog = catalog_snapshot()
        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        assert first_catalog == catalog_snapshot()
        assert VERSION in {int(module.VERSION) for module in discover_migrations()}

    global_space = _space(_id("m0319-global-space"))
    group = _group(
        global_space, group_type="fhrp", protocol="hsrp",
        group_id="319-global", family=4,
    )
    assert group["address_space_id"] == global_space["id"]
    assert group["protocol"] == "hsrp"
    with get_db_connection() as conn:
        stored_space = conn.execute(
            "SELECT kind, vrf_id FROM ipam_address_spaces WHERE id = ?",
            (global_space["id"],),
        ).fetchone()
    assert stored_space["kind"] == "global"
    assert stored_space["vrf_id"] is None

def test_vrrp_member_roles_preserve_group_and_multi_vip_relations(isolated_db):
    del isolated_db
    space = _space(_id('vrrp-space'))
    prefix_id, _ = _prefix(space)
    group = _group(space, group_id='17')
    vip_ids = [
        _vip(
            vip_id=_id('vrrp-vip'), prefix_id=prefix_id,
            address=f'172.16.0.{host}', space_id=space['id'],
        )
        for host in (10, 11)
    ]
    _attach_vip(group, vip_ids[0], expected_revision=1)
    _attach_vip(group, vip_ids[1], expected_revision=2)

    first_device, _ = _device()
    first_interface = _interface(first_device, 'GigabitEthernet0/1')
    second_device, _ = _device()
    second_interface = _interface(second_device, 'Ethernet1/1')
    first_member = _add_member(
        group,
        device_id=first_device,
        interface_name='Gi0/1',
        interface_id=first_interface,
        role='master',
        priority=120,
        expected_revision=3,
    )
    second_member = _add_member(
        group,
        device_id=second_device,
        interface_name='Eth1/1',
        interface_id=second_interface,
        role='backup',
        priority=100,
        expected_revision=4,
    )

    detail = group_service.get_fhrp_group(group['id'])
    assert detail['id'] == group['id']
    assert detail['group_id'] == '17'
    assert {item['vip_id'] for item in detail['vips']} == set(vip_ids)
    assert {item['id'] for item in detail['members']} == {first_member['id'], second_member['id']}
    assert {item['role'] for item in detail['members']} == {'master', 'backup'}
    assert {item['normalized_interface_name'] for item in detail['members']} == {'gi0/1', 'eth1/1'}
    assert detail['revision'] == 5

    duplicate_local_id = _group(space, group_id='17')
    assert duplicate_local_id['id'] != group['id']
    other_space = _space(_id('vrrp-other-space'))
    other_scope_duplicate = _group(other_space, group_id='17')
    assert other_scope_duplicate['id'] != duplicate_local_id['id']


def test_anycast_one_formal_vip_and_multiple_members(isolated_db):
    del isolated_db
    space = _space(_id('anycast-space'))
    prefix_id, _ = _prefix(space)
    group = _group(space, group_type='anycast', protocol='anycast', group_id='fabric-edge-a')
    vip_id = _vip(
        vip_id=_id('anycast-vip'), prefix_id=prefix_id,
        address='172.16.0.20', space_id=space['id'], protocol='anycast',
    )
    _attach_vip(group, vip_id, expected_revision=1)
    with pytest.raises(ValueError, match='conflicts with an active VIP'):
        create_address(prefix_id, address='172.16.0.20')

    other_space = _space(_id('anycast-isolated-space'))
    other_prefix, _ = _prefix(other_space)
    same_host_other_space = _vip(
        vip_id=_id('anycast-isolated-vip'), prefix_id=other_prefix,
        address='172.16.0.20', space_id=other_space['id'], protocol='anycast',
    )
    with get_db_connection() as conn:
        other_space_vip = conn.execute(
            'SELECT address_space_id FROM ipam_vips WHERE id = ?',
            (same_host_other_space,),
        ).fetchone()
    assert other_space_vip['address_space_id'] == other_space['id']

    second_vip_id = _vip(
        vip_id=_id('anycast-vip'), prefix_id=prefix_id,
        address='172.16.0.21', space_id=space['id'], protocol='anycast',
    )
    with pytest.raises(ValueError, match='one formal IPAM VIP'):
        _attach_vip(group, second_vip_id, expected_revision=2)

    members = []
    for role in ('peer-a', 'peer-b'):
        device_id, _ = _device()
        interface_name = 'Ethernet1/1' if role == 'peer-a' else 'Ethernet1/2'
        _interface(device_id, interface_name)
        members.append(_add_member(
            group,
            device_id=device_id,
            interface_name=interface_name,
            role=role,
            expected_revision=1 + len(members) + 1,
        ))

    detail = group_service.get_fhrp_group(group['id'])
    assert detail['group_type'] == 'anycast'
    assert detail['protocol'] == 'anycast'
    assert [item['vip_id'] for item in detail['vips']] == [vip_id]
    assert len(detail['members']) == 2
    assert {item['id'] for item in detail['members']} == {item['id'] for item in members}
    with get_db_connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS count FROM ipam_vips WHERE id = ?', (vip_id,)).fetchone()['count'] == 1
        assert conn.execute('SELECT COUNT(*) AS count FROM ipam_fhrp_group_vips WHERE vip_id = ?', (vip_id,)).fetchone()['count'] == 1


def test_tenant_space_vip_and_interface_device_mismatches_are_rejected(isolated_db):
    del isolated_db
    default_space = _space(_id('mismatch-default'))
    other_space = _space(_id('mismatch-other'), tenant_id='tenant-other')
    group = _group(default_space)
    with pytest.raises(ValueError, match='security tenant'):
        _group(other_space, tenant_id='tenant-default')

    other_prefix, _ = _prefix(other_space, tenant_id='tenant-other')
    wrong_space_vip = _vip(
        vip_id=_id('mismatch-vip'), prefix_id=other_prefix,
        address='172.16.0.21', space_id=other_space['id'],
        tenant_id='tenant-other',
    )
    with pytest.raises(ValueError, match='same address space'):
        _attach_vip(group, wrong_space_vip, expected_revision=1)

    default_prefix, _ = _prefix(default_space)
    wrong_tenant_same_space_vip = _vip(
        vip_id=_id('mismatch-tenant-vip'), prefix_id=default_prefix,
        address='172.16.0.22', space_id=default_space['id'],
        tenant_id='tenant-other',
    )
    with pytest.raises(ValueError, match='same security tenant'):
        _attach_vip(group, wrong_tenant_same_space_vip, expected_revision=1)

    other_device, _ = _device(tenant_id='tenant-other')
    other_interface = _interface(other_device, 'GigabitEthernet0/1')
    with pytest.raises(ValueError, match='security tenant'):
        _add_member(
            group, device_id=other_device, interface_name='Gi0/1',
            interface_id=other_interface, expected_revision=1,
        )

    local_device, _ = _device()
    foreign_device, _ = _device()
    _interface(local_device, 'GigabitEthernet0/1')
    foreign_interface = _interface(foreign_device, 'GigabitEthernet0/1')
    with pytest.raises(ValueError, match='does not exist on the specified device'):
        _add_member(
            group, device_id=local_device, interface_name='Gi0/1',
            interface_id=foreign_interface, expected_revision=1,
        )


def test_vip_protocol_and_family_must_match_group(isolated_db):
    del isolated_db
    space = _space(_id('vip-protocol-space'))
    prefix_id, _ = _prefix(space)
    group = _group(space, protocol='vrrp', family=4)
    hsrp_vip = _vip(
        vip_id=_id('hsrp-vip'), prefix_id=prefix_id,
        address='172.16.0.31', space_id=space['id'], protocol='hsrp',
    )
    with pytest.raises(ValueError, match='protocol must match'):
        _attach_vip(group, hsrp_vip, expected_revision=1)

    ipv6_prefix_id, _ = _prefix(space, cidr='2001:db8::/64')
    ipv6_vip = _vip(
        vip_id=_id('ipv6-vip'), prefix_id=ipv6_prefix_id,
        address='2001:db8::31', space_id=space['id'], protocol='vrrp',
    )
    with pytest.raises(ValueError, match='address family'):
        _attach_vip(group, ipv6_vip, expected_revision=1)


def test_linked_vip_update_preserves_group_contract_and_allows_description(isolated_db):
    del isolated_db
    space = _space(_id('linked-vip-space'))
    prefix_id, _ = _prefix(space)
    ipv6_prefix_id, _ = _prefix(space, cidr='2001:db8::/64')
    other_space = _space(_id('linked-vip-other-space'))
    other_prefix_id, _ = _prefix(other_space)
    group = _group(space, protocol='vrrp', family=4)
    vip_id = _vip(
        vip_id=_id('linked-vip'), prefix_id=prefix_id,
        address='172.16.0.60', space_id=space['id'],
    )
    _attach_vip(group, vip_id, expected_revision=1)

    with pytest.raises(ValueError, match='group address space'):
        update_vip(
            vip_id,
            expected_revision=1,
            prefix_id=other_prefix_id,
            address='172.16.0.61',
        )
    with pytest.raises(ValueError, match='protocol must match'):
        update_vip(vip_id, expected_revision=1, vip_type='hsrp')
    with pytest.raises(ValueError, match='address family'):
        update_vip(
            vip_id,
            expected_revision=1,
            prefix_id=ipv6_prefix_id,
            address='2001:db8::60',
        )
    with pytest.raises(ValueError, match='detach it first'):
        update_vip(vip_id, expected_revision=1, status='released')

    with get_db_connection() as conn:
        before = dict(conn.execute(
            'SELECT address, address_space_id, vip_type, revision FROM ipam_vips WHERE id = ?',
            (vip_id,),
        ).fetchone())
    assert before == {
        'address': '172.16.0.60',
        'address_space_id': space['id'],
        'vip_type': 'vrrp',
        'revision': 1,
    }

    assert update_vip(
        vip_id,
        expected_revision=1,
        description='updated unrelated service note',
        audit_context={
            'actor_username': 'fhrp-test-operator',
            'actor_role': 'Operator',
        },
    )
    with get_db_connection() as conn:
        after = conn.execute(
            'SELECT description, revision FROM ipam_vips WHERE id = ?', (vip_id,),
        ).fetchone()
        relation = conn.execute(
            'SELECT vip_id FROM ipam_fhrp_group_vips WHERE group_id = ?',
            (group['id'],),
        ).fetchone()
    assert after['description'] == 'updated unrelated service note'
    assert int(after['revision']) == 2
    assert relation['vip_id'] == vip_id


def test_linked_vip_delete_returns_clear_conflict_and_preserves_relationship(isolated_db):
    del isolated_db
    space = _space(_id('linked-vip-delete-space'))
    prefix_id, _ = _prefix(space)
    group = _group(space, protocol='vrrp', family=4)
    vip_id = _vip(
        vip_id=_id('linked-vip-delete'), prefix_id=prefix_id,
        address='172.16.0.70', space_id=space['id'],
    )
    _attach_vip(group, vip_id, expected_revision=1)

    admin = {
        'id': 'linked-vip-delete-admin',
        'username': 'linked-vip-delete-admin',
        'role': 'Administrator',
        'tenant_id': 'tenant-default',
    }
    with pytest.raises(HTTPException) as api_error:
        ipam_api.api_delete_vip(vip_id, expected_revision=1, user=admin)
    assert api_error.value.status_code == 409

    with pytest.raises(ValueError, match='detach it first'):
        delete_vip(vip_id, expected_revision=1)

    with get_db_connection() as conn:
        vip = conn.execute('SELECT id, revision FROM ipam_vips WHERE id = ?', (vip_id,)).fetchone()
        relation = conn.execute(
            'SELECT group_id FROM ipam_fhrp_group_vips WHERE vip_id = ?', (vip_id,),
        ).fetchone()
    assert vip and int(vip['revision']) == 1
    assert relation and relation['group_id'] == group['id']


def test_inactive_vip_cannot_be_attached_to_a_formal_group(isolated_db):
    del isolated_db
    space = _space(_id('inactive-vip-space'))
    prefix_id, _ = _prefix(space)
    group = _group(space, protocol='vrrp')
    vip_id = _vip(
        vip_id=_id('inactive-vip'), prefix_id=prefix_id,
        address='172.16.0.80', space_id=space['id'],
    )
    with get_db_connection() as conn:
        conn.execute("UPDATE ipam_vips SET status = 'released' WHERE id = ?", (vip_id,))
        conn.commit()

    with pytest.raises(ValueError, match='Inactive VIPs cannot be linked'):
        _attach_vip(group, vip_id, expected_revision=1)


def test_group_revision_cas_and_idempotency_replay_conflict(isolated_db):
    del isolated_db
    space = _space(_id('revision-space'))
    created = _group(space, key='fhrp-create-replay', display_name='initial')
    replay = _group(space, key='fhrp-create-replay', display_name='initial')
    assert replay == created
    with pytest.raises(ValueError, match='different request body'):
        _group(space, key='fhrp-create-replay', display_name='changed')

    update_request = {
        'security_tenant_id': 'tenant-default',
        'expected_revision': 1,
        'display_name': 'updated',
        'idempotency_key': 'fhrp-update-replay',
    }
    updated = group_service.update_fhrp_group(created['id'], **update_request)
    assert updated['revision'] == 2
    assert group_service.update_fhrp_group(created['id'], **update_request) == updated
    with pytest.raises(ValueError, match='different request body'):
        group_service.update_fhrp_group(
            created['id'],
            security_tenant_id='tenant-default',
            expected_revision=1,
            display_name='changed',
            idempotency_key='fhrp-update-replay',
        )
    with pytest.raises(ValueError, match='revision is stale'):
        group_service.update_fhrp_group(
            created['id'],
            security_tenant_id='tenant-default',
            expected_revision=1,
            display_name='stale',
        )


def test_new_groups_require_active_explicit_address_spaces(isolated_db):
    del isolated_db
    space = _space(_id('inactive-space'))
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE ipam_address_spaces SET status = 'inactive' WHERE id = ?",
            (space['id'],),
        )
        conn.commit()
    with pytest.raises(ValueError, match='active explicit address space'):
        _group(space)


def test_member_and_vip_idempotency_replay_before_revision_check(isolated_db):
    del isolated_db
    space = _space(_id('idempotent-rel-space'))
    prefix_id, _ = _prefix(space)
    group = _group(space)
    device_id, _ = _device()
    interface_id = _interface(device_id, 'GigabitEthernet0/3')
    first_member = _add_member(
        group, device_id=device_id, interface_name='Gi0/3',
        interface_id=interface_id, expected_revision=1, key='member-add-replay',
    )
    replay_member = _add_member(
        group, device_id=device_id, interface_name='Gi0/3',
        interface_id=interface_id, expected_revision=1, key='member-add-replay',
    )
    assert replay_member == first_member

    vip_id = _vip(
        vip_id=_id('idempotent-vip'), prefix_id=prefix_id,
        address='172.16.0.40', space_id=space['id'],
    )
    attached = _attach_vip(group, vip_id, expected_revision=2, key='vip-attach-replay')
    replayed_attach = _attach_vip(group, vip_id, expected_revision=2, key='vip-attach-replay')
    assert replayed_attach == attached
    with pytest.raises(ValueError, match='different request body'):
        group_service.attach_fhrp_group_vip(
            group['id'], security_tenant_id='tenant-default',
            expected_revision=3, vip_id=vip_id, idempotency_key='vip-attach-replay',
        )


def test_audit_failure_rolls_back_group_and_relation_without_touching_vip(isolated_db, monkeypatch):
    del isolated_db
    space = _space(_id('audit-space'))

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError('audit write failed')

    write_ipam_audit = group_service._write_ipam_audit
    monkeypatch.setattr(group_service, '_write_ipam_audit', fail_audit)
    with pytest.raises(RuntimeError, match='audit write failed'):
        _group(space, key='rolled-back-group')
    with get_db_connection() as conn:
        assert conn.execute(
            'SELECT 1 FROM ipam_fhrp_groups WHERE address_space_id = ?', (space['id'],),
        ).fetchone() is None
        assert conn.execute(
            """SELECT 1 FROM ipam_idempotency_records
                 WHERE operation = 'ipam.fhrp_group.create'
                   AND idempotency_key = 'rolled-back-group'""",
        ).fetchone() is None

    monkeypatch.setattr(group_service, '_write_ipam_audit', write_ipam_audit)
    group = _group(space)
    prefix_id, _ = _prefix(space)
    vip_id = _vip(
        vip_id=_id('audit-vip'), prefix_id=prefix_id,
        address='172.16.0.41', space_id=space['id'],
    )
    with get_db_connection() as conn:
        vip_before = dict(conn.execute(
            'SELECT revision, updated_at, vip_type FROM ipam_vips WHERE id = ?', (vip_id,),
        ).fetchone())
    monkeypatch.setattr(group_service, '_write_ipam_audit', fail_audit)
    with pytest.raises(RuntimeError, match='audit write failed'):
        _attach_vip(group, vip_id, expected_revision=1, key='rolled-back-link')
    with get_db_connection() as conn:
        assert conn.execute(
            'SELECT 1 FROM ipam_fhrp_group_vips WHERE vip_id = ?', (vip_id,),
        ).fetchone() is None
        group_row = conn.execute(
            'SELECT revision FROM ipam_fhrp_groups WHERE id = ?', (group['id'],),
        ).fetchone()
        vip_after = dict(conn.execute(
            'SELECT revision, updated_at, vip_type FROM ipam_vips WHERE id = ?', (vip_id,),
        ).fetchone())
    assert int(group_row['revision']) == 1
    assert vip_after == vip_before

    monkeypatch.setattr(group_service, '_write_ipam_audit', write_ipam_audit)
    # A successful relation write leaves the existing VIP row untouched.
    _attach_vip(group, vip_id, expected_revision=1)
    with get_db_connection() as conn:
        vip_after_success = dict(conn.execute(
            'SELECT revision, updated_at, vip_type FROM ipam_vips WHERE id = ?', (vip_id,),
        ).fetchone())
        event = conn.execute(
            """SELECT 1 FROM audit_events
                 WHERE event_type = 'ipam.fhrp_group.vip.attach'
                   AND target_type = 'ipam_fhrp_group_vip'""",
        ).fetchone()
    assert vip_after_success == vip_before
    assert event


def test_referenced_group_delete_is_rejected_then_explicit_detach_allows_delete(isolated_db):
    del isolated_db
    space = _space(_id('delete-space'))
    prefix_id, _ = _prefix(space)
    group = _group(space)
    device_id, _ = _device()
    interface_id = _interface(device_id, 'GigabitEthernet0/4')
    member = _add_member(
        group, device_id=device_id, interface_name='Gi0/4',
        interface_id=interface_id, expected_revision=1,
    )
    vip_id = _vip(
        vip_id=_id('delete-vip'), prefix_id=prefix_id,
        address='172.16.0.50', space_id=space['id'],
    )
    _attach_vip(group, vip_id, expected_revision=2)
    with pytest.raises(ValueError, match='members or VIP links remain'):
        group_service.delete_fhrp_group(
            group['id'], security_tenant_id='tenant-default', expected_revision=3,
        )

    removed = group_service.remove_fhrp_group_member(
        group['id'], member['id'], security_tenant_id='tenant-default',
        expected_revision=3, idempotency_key='member-remove-replay',
    )
    assert group_service.remove_fhrp_group_member(
        group['id'], member['id'], security_tenant_id='tenant-default',
        expected_revision=3, idempotency_key='member-remove-replay',
    ) == removed
    detached = group_service.detach_fhrp_group_vip(
        group['id'], vip_id, security_tenant_id='tenant-default',
        expected_revision=4, idempotency_key='vip-detach-replay',
    )
    assert group_service.detach_fhrp_group_vip(
        group['id'], vip_id, security_tenant_id='tenant-default',
        expected_revision=4, idempotency_key='vip-detach-replay',
    ) == detached
    deleted = group_service.delete_fhrp_group(
        group['id'], security_tenant_id='tenant-default', expected_revision=5,
        idempotency_key='delete-group-replay',
    )
    assert deleted == {'ok': True, 'id': group['id'], 'revision': 5}
    assert group_service.delete_fhrp_group(
        group['id'], security_tenant_id='tenant-default', expected_revision=5,
        idempotency_key='delete-group-replay',
    ) == deleted


def test_group_id_sql_looking_values_are_stored_as_data(isolated_db):
    del isolated_db
    space = _space(_id('parameter-space'))
    unsafe_looking_id = "17'); DROP TABLE ipam_fhrp_groups;--"
    group = _group(space, group_id=unsafe_looking_id)
    assert group['group_id'] == unsafe_looking_id
    with get_db_connection() as conn:
        row = conn.execute(
            'SELECT group_id FROM ipam_fhrp_groups WHERE id = ?', (group['id'],),
        ).fetchone()
        still_there = conn.execute(
            "SELECT to_regclass('ipam_fhrp_groups') AS table_name",
        ).fetchone()
    assert row['group_id'] == unsafe_looking_id
    assert still_there['table_name'] == 'ipam_fhrp_groups'


def test_routes_apply_tenant_and_resource_scope(isolated_db, make_user):
    del isolated_db
    space = _space(_id('route-space'))
    body = IPAMFHRPGroupCreate(
        address_space_id=space['id'], group_type='fhrp', protocol='vrrp',
        group_id='22', address_family=4,
    )
    created = ipam_api.api_create_fhrp_group(
        body, idempotency_key='route-create',
        user={'id': 'route-operator', 'username': 'route-operator', 'role': 'Operator', 'tenant_id': 'tenant-default'},
    )
    assert created['group_id'] == '22'
    assert 'members' in created and 'vips' in created

    restricted_row = make_user(
        'fhrp-restricted-operator', role='Operator', tenant_id='tenant-default',
    )
    restricted_user = {
        'id': restricted_row['user_id'],
        'username': restricted_row['username'],
        'role': 'Operator',
        'tenant_id': 'tenant-default',
        'scope_mode': 'restricted',
    }
    blocked_body = IPAMFHRPGroupCreate(
        address_space_id=space['id'], group_type='fhrp', protocol='hsrp',
        group_id='23', address_family=4,
    )
    with pytest.raises(HTTPException) as error:
        ipam_api.api_create_fhrp_group(blocked_body, user=restricted_user)
    assert error.value.status_code == 403


def test_group_list_search_paginates_after_site_scope_filter(isolated_db, make_user):
    del isolated_db
    visible_space = _space('visible-search-space')
    hidden_space = _space('hidden-search-space')
    visible_site = _id('fhrp-visible-site')
    hidden_site = _id('fhrp-hidden-site')
    _prefix(visible_space, site_id=visible_site)
    _prefix(hidden_space, site_id=hidden_site)

    visible_first = _group(visible_space, group_id='needle-id-1', display_name='core')
    visible_second = _group(visible_space, group_id='second-id', display_name='needle-title')
    _group(hidden_space, group_id='needle-hidden-id', display_name='needle-secret')

    user_row = make_user(
        'fhrp-scoped-viewer', role='Viewer', tenant_id='tenant-default',
    )
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO user_resource_scopes
                   (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES (?, ?, 'prefix', 'site', ?, ?, CURRENT_TIMESTAMP)""",
            (_id('fhrp-list-scope'), user_row['user_id'], visible_site, json.dumps(['view'])),
        )
        conn.commit()
    user = {
        'id': user_row['user_id'],
        'username': user_row['username'],
        'role': 'Viewer',
        'tenant_id': 'tenant-default',
        'scope_mode': 'restricted',
    }
    assert ipam_api._address_space_scope_allowed(
        user, visible_space['id'], 'tenant-default', 'view',
    )
    with get_db_connection() as conn:
        visible_prefix = conn.execute(
            'SELECT address_space_id, site_id, tenant_id FROM prefixes WHERE address_space_id = ?',
            (visible_space['id'],),
        ).fetchone()
    assert visible_prefix['site_id'] == visible_site
    assert visible_prefix['tenant_id'] == 'tenant-default'
    direct_page = group_service.list_fhrp_groups(
        q='needle', allowed_address_space_ids=[visible_space['id']],
        page=1, page_size=20,
    )
    assert direct_page['total'] == 2

    first_page = ipam_api.api_list_fhrp_groups(
        q='needle', page=1, page_size=1, user=user,
    )
    second_page = ipam_api.api_list_fhrp_groups(
        q='needle', page=2, page_size=1, user=user,
    )
    assert first_page['total'] == 2
    assert first_page['page'] == 1
    assert first_page['page_size'] == 1
    assert first_page['total_pages'] == 2
    assert [item['id'] for item in first_page['items']] == [visible_first['id']]
    assert [item['id'] for item in second_page['items']] == [visible_second['id']]
    assert 'members' not in first_page['items'][0]
    assert 'vips' not in first_page['items'][0]

    hidden_group_results = ipam_api.api_list_fhrp_groups(
        q='needle-secret', page=1, page_size=20, user=user,
    )
    hidden_space_results = ipam_api.api_list_fhrp_groups(
        q='hidden-search-space', page=1, page_size=20, user=user,
    )
    visible_space_results = ipam_api.api_list_fhrp_groups(
        q='visible-search-space', page=1, page_size=20, user=user,
    )
    assert hidden_group_results['total'] == 0
    assert hidden_space_results['total'] == 0
    assert visible_space_results['total'] == 2


def test_current_group_route_returns_only_member_current_snapshot_and_coverage(isolated_db, monkeypatch):
    del isolated_db
    space = _space(_id('current-group-space'))
    group = _group(space, group_id='17', protocol='vrrp')
    prefix_id, _ = _prefix(space)
    vip_id = _vip(
        vip_id=_id('current-group-vip'), prefix_id=prefix_id,
        address='172.16.0.254', space_id=space['id'], protocol='vrrp',
    )
    _attach_vip(group, vip_id, expected_revision=1)
    device_id, _site_id = _device()
    interface_id = _interface(device_id, 'GigabitEthernet0/1')
    _add_member(
        group, device_id=device_id, interface_name='GigabitEthernet0/1',
        interface_id=interface_id, expected_revision=2,
    )
    attempted = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with get_db_connection() as conn:
        generation = begin_current_fhrp_collection(
            conn, device_id=device_id, protocol='vrrp',
            attempted_at=attempted, run_id='current-group-test',
        )
        conn.commit()
    with get_db_connection() as conn:
        finish_current_fhrp_collection(
            conn, device_id=device_id, protocol='vrrp', generation=generation,
            status='complete', attempted_at=attempted, completed_at=attempted,
            run_id='current-group-test', observations=[{
                'group_id': 17,
                'address_family': 4,
                'interface_name': 'GigabitEthernet0/1',
                'priority': 110,
                'state': 'master',
                'master_address': '172.16.0.1',
                'virtual_ip': '172.16.0.254',
            }],
        )
        conn.commit()
    monkeypatch.setattr(
        'services.ipam_service._current_cmdb_interface_ip_observations',
        lambda _conn: [{
            'device_id': device_id,
            'normalized_interface_name': 'gi0/1',
            'ip_address': '172.16.0.2',
            'tenant_id': 'tenant-default',
            'device_site_id': _site_id,
            'address_space_id': space['id'],
            'address_space_name': space['name'],
            'context_type': 'global',
        }],
    )
    user = {
        'id': 'current-fhrp-admin', 'username': 'current-fhrp-admin',
        'role': 'Administrator', 'tenant_id': 'tenant-default',
    }

    result = ipam_api.api_list_current_fhrp_group_observations(group['id'], user=user)

    assert len(result['items']) == 1
    assert result['items'][0]['virtual_ip'] == '172.16.0.254'
    assert result['items'][0]['state'] == 'master'
    assert result['items'][0]['group_scope_status'] == 'resolved'
    assert result['collection_states'][0]['latest_status'] == 'complete'
    assert result['collection_states'][0]['current_row_count'] == 1
    before_switch = group_service.get_fhrp_group(group['id'])
    assert before_switch['revision'] == 3
    assert [item['vip_id'] for item in before_switch['vips']] == [vip_id]

    next_attempt = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with get_db_connection() as conn:
        next_generation = begin_current_fhrp_collection(
            conn, device_id=device_id, protocol='vrrp',
            attempted_at=next_attempt, run_id='current-group-master-switch',
        )
        conn.commit()
    with get_db_connection() as conn:
        finish_current_fhrp_collection(
            conn, device_id=device_id, protocol='vrrp', generation=next_generation,
            status='complete', attempted_at=next_attempt, completed_at=next_attempt,
            run_id='current-group-master-switch', observations=[{
                'group_id': 17,
                'address_family': 4,
                'interface_name': 'GigabitEthernet0/1',
                'priority': 110,
                'state': 'backup',
                'master_address': '172.16.0.3',
                'virtual_ip': '172.16.0.254',
            }],
        )
        conn.commit()
    after_switch = ipam_api.api_list_current_fhrp_group_observations(group['id'], user=user)
    group_after_switch = group_service.get_fhrp_group(group['id'])
    assert after_switch['items'][0]['state'] == 'backup'
    assert after_switch['items'][0]['virtual_ip'] == '172.16.0.254'
    assert group_after_switch['revision'] == 3
    assert [item['vip_id'] for item in group_after_switch['vips']] == [vip_id]


def test_current_group_route_keeps_unknown_interface_scope_pending(isolated_db, monkeypatch):
    del isolated_db
    space = _space(_id('current-pending-group-space'))
    group = _group(space, group_id='18', protocol='vrrp')
    device_id, _site_id = _device()
    interface_id = _interface(device_id, 'GigabitEthernet0/2')
    _add_member(
        group, device_id=device_id, interface_name='GigabitEthernet0/2',
        interface_id=interface_id,
    )
    attempted = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with get_db_connection() as conn:
        generation = begin_current_fhrp_collection(
            conn, device_id=device_id, protocol='vrrp',
            attempted_at=attempted, run_id='current-group-pending-test',
        )
        conn.commit()
    with get_db_connection() as conn:
        finish_current_fhrp_collection(
            conn, device_id=device_id, protocol='vrrp', generation=generation,
            status='complete', attempted_at=attempted, completed_at=attempted,
            run_id='current-group-pending-test', observations=[{
                'group_id': 18,
                'address_family': 4,
                'interface_name': 'GigabitEthernet0/2',
                'state': 'backup',
                'virtual_ip': '172.16.0.253',
            }],
        )
        conn.commit()
    monkeypatch.setattr(
        'services.ipam_service._current_cmdb_interface_ip_observations',
        lambda _conn: [],
    )
    user = {
        'id': 'current-fhrp-pending-admin', 'username': 'current-fhrp-pending-admin',
        'role': 'Administrator', 'tenant_id': 'tenant-default',
    }

    result = ipam_api.api_list_current_fhrp_group_observations(group['id'], user=user)

    assert len(result['items']) == 1
    assert result['items'][0]['virtual_ip'] == '172.16.0.253'
    assert result['items'][0]['group_scope_status'] == 'scope_pending'


def test_delete_route_replays_after_group_removal(isolated_db):
    del isolated_db
    space = _space(_id('route-delete-space'))
    group = _group(space)
    admin = {
        'id': 'fhrp-delete-admin',
        'username': 'fhrp-delete-admin',
        'role': 'Administrator',
        'tenant_id': 'tenant-default',
    }
    first = ipam_api.api_delete_fhrp_group(
        group['id'], expected_revision=1,
        idempotency_key='api-delete-replay', user=admin,
    )
    replay = ipam_api.api_delete_fhrp_group(
        group['id'], expected_revision=1,
        idempotency_key='api-delete-replay', user=admin,
    )
    assert replay == first
    with pytest.raises(HTTPException) as error:
        ipam_api.api_delete_fhrp_group(
            group['id'], expected_revision=2,
            idempotency_key='api-delete-replay', user=admin,
        )
    assert error.value.status_code == 409


def test_fhrp_schemas_reject_invalid_protocols_and_empty_updates():
    with pytest.raises(ValidationError):
        IPAMFHRPGroupCreate(
            address_space_id='space', group_type='anycast', protocol='vrrp',
            group_id='42', address_family=4,
        )
    with pytest.raises(ValidationError):
        IPAMFHRPGroupUpdate(expected_revision=1)
    with pytest.raises(ValidationError):
        IPAMFHRPGroupUpdate(expected_revision=1, display_name=None)
