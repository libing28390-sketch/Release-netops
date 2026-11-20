from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api import ipam as ipam_api
from database import get_db_connection
from schemas.schemas import IPAMRoutingContextCreate, IPAMRoutingContextUpdate
from services.ipam_address_space_service import create_address_space
from services.ipam_routing_context_service import (
    create_device_routing_context,
    list_device_routing_contexts,
    update_device_routing_context,
)


def _id(prefix: str) -> str:
    return f'{prefix}-{uuid.uuid4().hex[:10]}'


def _space(name: str, *, tenant_id: str = 'tenant-default', kind: str = 'global') -> dict:
    return create_address_space(
        name=name,
        kind=kind,
        vrf_id=None,
        security_tenant_id=tenant_id,
    )


def _device(device_id: str, *, tenant_id: str = 'tenant-default', site_id: str | None = None) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices
                   (id, hostname, ip_address, platform, status, site_id, tenant_id)
               VALUES (?, ?, '192.0.2.10', 'cisco_ios', 'online', ?, ?)""",
            (device_id, device_id, site_id, tenant_id),
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


def _tenant(tenant_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES (?, ?) ON CONFLICT (id) DO NOTHING",
            (tenant_id, tenant_id),
        )
        conn.commit()


def _prefix(prefix_id: str, cidr: str, address_space_id: str, site_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO prefixes
                   (id, prefix, prefix_cidr, address_space_id, vrf_id, site_id,
                    tenant_id, status, name, created_at, updated_at)
               VALUES (?, ?, ?, ?, NULL, ?, 'tenant-default', 'active', ?, 'now', 'now')""",
            (prefix_id, cidr, cidr, address_space_id, site_id, prefix_id),
        )
        conn.commit()


def test_create_routing_context_is_explicit_kind_checked_and_audited(isolated_db):
    device_id = _id('routing-device')
    space = _space(_id('routing-global'))
    _device(device_id)

    result = create_device_routing_context(
        device_id=device_id,
        context_source='cli',
        context_type='global',
        local_context_key='  Global  ',
        local_context_name='  Main table  ',
        address_space_id=space['id'],
        security_tenant_id='tenant-default',
        audit_context={
            'actor_id': 'routing-context-operator',
            'actor_username': 'routing-context-operator',
            'actor_role': 'Operator',
        },
    )

    assert result['local_context_key'] == 'Global'
    assert result['local_context_name'] == 'Main table'
    assert result['address_space_id'] == space['id']
    assert result['revision'] == 1
    assert result['status'] == 'active'
    assert result['last_verified_at'] is None
    assert set(result) >= {'device_name', 'address_space_name', 'address_space_kind', 'vrf_id'}

    with get_db_connection() as conn:
        event = conn.execute(
            """SELECT target_id, after_json FROM audit_events
                 WHERE event_type = 'ipam.device_routing_context.create'
                   AND target_id = ?""",
            (result['id'],),
        ).fetchone()
        assert event
        assert json.loads(event['after_json'])['address_space_id'] == space['id']

    with pytest.raises(ValueError, match='kind vrf'):
        create_device_routing_context(
            device_id=device_id,
            context_source='snmp',
            context_type='vrf',
            local_context_key='Blue',
            address_space_id=space['id'],
            security_tenant_id='tenant-default',
        )
    assert len(list_device_routing_contexts(device_id=device_id)) == 1


def test_routing_context_write_rejects_tenant_mismatch_and_update_uses_revision_cas(isolated_db):
    device_id = _id('routing-device')
    _device(device_id, tenant_id='tenant-default')
    _tenant('tenant-other')
    other_space = _space(_id('routing-other-space'), tenant_id='tenant-other')
    same_tenant_space = _space(_id('routing-same-space'))

    with pytest.raises(ValueError, match='security tenant'):
        create_device_routing_context(
            device_id=device_id,
            context_source='snmp',
            context_type='global',
            local_context_key='default',
            address_space_id=other_space['id'],
            security_tenant_id='tenant-default',
        )
    with pytest.raises(ValueError, match='security tenant'):
        create_device_routing_context(
            device_id=device_id,
            context_source='snmp',
            context_type='global',
            local_context_key='default',
            address_space_id=same_tenant_space['id'],
            security_tenant_id='tenant-other',
        )

    created = create_device_routing_context(
        device_id=device_id,
        context_source='snmp',
        context_type='global',
        local_context_key='default',
        address_space_id=same_tenant_space['id'],
        security_tenant_id='tenant-default',
    )
    with pytest.raises(ValueError, match='security tenant'):
        update_device_routing_context(
            created['id'],
            expected_revision=1,
            security_tenant_id='tenant-default',
            address_space_id=other_space['id'],
        )

    updated = update_device_routing_context(
        created['id'],
        expected_revision=1,
        security_tenant_id='tenant-default',
        local_context_name='Disabled source',
        status='disabled',
        update_local_context_name=True,
        update_status=True,
    )
    assert updated['revision'] == 2
    assert updated['local_context_name'] == 'Disabled source'
    assert updated['status'] == 'disabled'

    with pytest.raises(ValueError, match='revision is stale'):
        update_device_routing_context(
            created['id'],
            expected_revision=1,
            security_tenant_id='tenant-default',
            status='active',
            update_status=True,
        )


def test_routing_context_schemas_trim_identity_and_reject_empty_or_unknown_fields():
    body = IPAMRoutingContextCreate(
        device_id=' device-a ',
        context_source='cli',
        context_type='vrf',
        local_context_key=' Blue ',
        address_space_id=' as-vrf-a ',
    )
    assert body.device_id == 'device-a'
    assert body.local_context_key == 'Blue'
    assert body.local_context_name == ''
    with pytest.raises(ValidationError):
        IPAMRoutingContextCreate(
            device_id='device-a', context_source='cli', context_type='vrf',
            local_context_key='  ', address_space_id='space-a',
        )
    with pytest.raises(ValidationError):
        IPAMRoutingContextUpdate(expected_revision=1, unexpected='value')
    with pytest.raises(ValidationError):
        IPAMRoutingContextUpdate(expected_revision=1)


def test_list_requires_both_device_and_address_space_site_scope(isolated_db, make_user):
    site_a, site_b = _id('routing-site-a'), _id('routing-site-b')
    device_id = _id('routing-device')
    space = _space(_id('routing-scoped-space'))
    _site(site_a)
    _site(site_b)
    _device(device_id, site_id=site_a)
    _prefix(_id('routing-prefix-b'), '198.51.100.0/24', space['id'], site_b)
    create_device_routing_context(
        device_id=device_id,
        context_source='cli',
        context_type='global',
        local_context_key='global',
        address_space_id=space['id'],
        security_tenant_id='tenant-default',
    )

    user_row = make_user('routing-viewer', role='Viewer', tenant_id='tenant-default')
    user = {
        'id': user_row['user_id'],
        'username': user_row['username'],
        'role': 'Viewer',
        'tenant_id': 'tenant-default',
        'scope_mode': 'restricted',
    }
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO user_resource_scopes
                   (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES (?, ?, 'prefix', 'site', ?, ?, CURRENT_TIMESTAMP)""",
            (_id('routing-scope'), user['id'], site_a, json.dumps(['view'])),
        )
        conn.commit()

    assert ipam_api.api_list_routing_contexts(device_id=device_id, user=user)['items'] == []

    _prefix(_id('routing-prefix-a'), '203.0.113.0/24', space['id'], site_a)
    response = ipam_api.api_list_routing_contexts(device_id=device_id, user=user)
    assert len(response['items']) == 1
    assert response['items'][0]['device_id'] == device_id
    assert set(response['items'][0]) == {
        'id', 'device_id', 'device_name', 'context_source', 'context_type',
        'local_context_key', 'local_context_name', 'address_space_id',
        'address_space_name', 'address_space_kind', 'vrf_id', 'status',
        'revision', 'last_verified_at', 'created_at', 'updated_at',
    }


def test_create_route_requires_address_space_permission_in_addition_to_device_scope(isolated_db, make_user):
    site_a, site_b = _id('routing-site-a'), _id('routing-site-b')
    device_id = _id('routing-device')
    space = _space(_id('routing-scoped-space'))
    _site(site_a)
    _site(site_b)
    _device(device_id, site_id=site_a)
    _prefix(_id('routing-prefix-b'), '198.51.101.0/24', space['id'], site_b)

    user_row = make_user('routing-operator', role='Operator', tenant_id='tenant-default')
    user = {
        'id': user_row['user_id'],
        'username': user_row['username'],
        'role': 'Operator',
        'tenant_id': 'tenant-default',
        'scope_mode': 'restricted',
    }
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO user_resource_scopes
                   (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES (?, ?, 'prefix', 'site', ?, ?, CURRENT_TIMESTAMP)""",
            (_id('routing-scope'), user['id'], site_a, json.dumps(['view', 'create', 'update'])),
        )
        conn.commit()

    request = IPAMRoutingContextCreate(
        device_id=device_id,
        context_source='cli',
        context_type='global',
        local_context_key='global',
        address_space_id=space['id'],
    )
    with pytest.raises(HTTPException) as denied:
        ipam_api.api_create_routing_context(request, user=user)
    assert denied.value.status_code == 403
    assert list_device_routing_contexts(device_id=device_id) == []
