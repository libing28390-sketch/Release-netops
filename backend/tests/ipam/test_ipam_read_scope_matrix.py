from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException

from api import ipam as ipam_api
from database import get_db_connection
from schemas.schemas import (
    PrefixCreate,
    PrefixAddressSpaceBatchPreviewRequest,
    PrefixAddressSpaceBatchItem,
    ResolvePrefixAddressSpaceBatchRequest,
    ResolvePrefixAddressSpaceRequest,
)
from services import ipam_service
from services.ipam_address_space_service import create_address_space
from services.ipam_routing_context_service import create_device_routing_context
from services.ipam_service import create_address, create_subnet, detect_conflicts


def _id(label: str) -> str:
    return f'{label}-{uuid.uuid4().hex[:10]}'


def _site(site_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, tenant_id)
               VALUES (?, ?, ?, 'tenant-default') ON CONFLICT (id) DO NOTHING""",
            (site_id, site_id.upper(), site_id),
        )
        conn.commit()


def _restricted_viewer(
    make_user, site_id: str, *, update: bool = False, create: bool = False,
    role: str = 'Viewer',
) -> dict:
    row = make_user(_id('ipam-scope-viewer'), role=role, tenant_id='tenant-default')
    actions = ['view']
    if update:
        actions.append('update')
    if create:
        actions.append('create')
    with get_db_connection() as conn:
        for resource_type in ('prefix', 'ip_address'):
            conn.execute(
                """INSERT INTO user_resource_scopes
                       (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
                   VALUES (?, ?, ?, 'site', ?, ?, CURRENT_TIMESTAMP)""",
                (_id('ipam-scope-grant'), row['user_id'], resource_type, site_id, json.dumps(actions)),
            )
        conn.commit()
    return {
        'id': row['user_id'],
        'username': row['username'],
        'role': role,
        'tenant_id': 'tenant-default',
        'scope_mode': 'restricted',
    }


def _prefix(prefix: str, *, space_id: str, site_id: str, name: str) -> dict:
    return create_subnet(
        prefix=prefix,
        address_space_id=space_id,
        tenant_id='tenant-default',
        site_id=site_id,
        name=name,
    )


def test_restricted_user_lists_aggregates_and_next_available_are_site_scoped(isolated_db, make_user, monkeypatch):
    del isolated_db
    site_a, site_b = _id('ipam-site-a'), _id('ipam-site-b')
    _site(site_a)
    _site(site_b)
    space = create_address_space(
        name=_id('ipam-global'), kind='global', vrf_id=None,
        security_tenant_id='tenant-default',
    )
    prefix_a = _prefix('198.18.11.0/24', space_id=space['id'], site_id=site_a, name='Site A Prefix')
    prefix_b = _prefix('198.18.12.0/24', space_id=space['id'], site_id=site_b, name='Site B Prefix')
    create_address(prefix_a['id'], address='198.18.11.10', mac_address='00:11:22:33:44:55')
    create_address(prefix_b['id'], address='198.18.12.10', mac_address='00:11:22:33:44:55')
    user = _restricted_viewer(make_user, site_a)

    subnets = ipam_api.api_list_subnets(
        user=user, page=1, page_size=100, classification='all',
    )
    assert [item['id'] for item in subnets['items']] == [prefix_a['id']]
    assert subnets['total'] == 1

    classification = ipam_api.api_prefix_classification_summary(user=user, family='all')
    assert classification['total'] == 1
    summary = ipam_api.api_ipam_summary(_user=user)
    assert summary['total_subnets'] == 1
    assert summary['total_addresses'] == 1

    inventory = ipam_api.api_list_ip_inventory(
        _user=user, page=1, page_size=100, registered_only=False,
    )
    assert inventory['total'] == 1
    assert [item['subnet_id'] for item in inventory['items']] == [prefix_a['id']]
    assert {site['id'] for site in inventory['sites']} == {site_a}
    assert inventory['summary']['prefixes'] == 1

    analytics = ipam_api.api_get_analytics(_user=user, network_scope='all')
    assert analytics['overview']['prefixes_count'] == 1
    assert analytics['overview']['ips_count'] == 1
    assert {item['id'] for item in analytics['items']} == {prefix_a['id']}
    assert {item['id'] for item in ipam_api.api_get_subnets_tree(_user=user)} == {prefix_a['id']}

    assert ipam_api.api_detect_conflicts(_user=user)['total_conflicts'] == 0
    assert detect_conflicts()['total_conflicts'] == 1
    assert ipam_api.api_list_addresses(
        prefix_a['id'], _user=user, page=1, page_size=20,
        status='all', device_type='all', purpose='all',
    )['total'] == 1
    for scoped_suggestion in (
        lambda: ipam_api.api_next_available_ip(prefix_a['id'], _user=user),
        lambda: ipam_api.api_next_available_prefix(prefix_a['id'], prefix_len=25, _user=user),
    ):
        with pytest.raises(HTTPException) as denied:
            scoped_suggestion()
        assert denied.value.status_code == 403
    for hidden_call in (
        lambda: ipam_api.api_list_addresses(prefix_b['id'], _user=user, page=1),
        lambda: ipam_api.api_next_available_ip(prefix_b['id'], _user=user),
        lambda: ipam_api.api_next_available_prefix(prefix_b['id'], prefix_len=25, _user=user),
    ):
        with pytest.raises(HTTPException) as denied:
            hidden_call()
        assert denied.value.status_code == 404

    monkeypatch.setattr(
        ipam_api, 'get_current_discovered_endpoint',
        lambda _observation_id: {'tenant_id': 'tenant-default', 'site_id': site_b},
    )
    with pytest.raises(HTTPException) as hidden_evidence:
        ipam_api.api_get_discovered_endpoint('foreign-observation', user=user)
    assert hidden_evidence.value.status_code == 404


def test_address_space_previews_require_complete_target_scope(isolated_db, make_user):
    del isolated_db
    site_a, site_b = _id('ipam-target-site-a'), _id('ipam-target-site-b')
    _site(site_a)
    _site(site_b)
    space_a = create_address_space(
        name=_id('ipam-target-space-a'), kind='global', vrf_id=None,
        security_tenant_id='tenant-default',
    )
    space_b = create_address_space(
        name=_id('ipam-target-space-b'), kind='global', vrf_id=None,
        security_tenant_id='tenant-default',
    )
    prefix_a = _prefix('198.18.21.0/24', space_id=space_a['id'], site_id=site_a, name='Source Prefix')
    _prefix('198.18.22.0/24', space_id=space_b['id'], site_id=site_b, name='Target Prefix')
    context_device_id = _id('ipam-context-site-b')
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices
                   (id, hostname, ip_address, platform, status, site_id, tenant_id)
               VALUES (?, ?, '192.0.2.33', 'cisco_ios', 'online', ?, 'tenant-default')""",
            (context_device_id, context_device_id, site_b),
        )
        conn.commit()
    create_device_routing_context(
        device_id=context_device_id,
        context_source='cli',
        context_type='global',
        local_context_key='Global',
        address_space_id=space_a['id'],
        security_tenant_id='tenant-default',
    )
    user = _restricted_viewer(make_user, site_a, update=True)

    with pytest.raises(HTTPException) as context_preview_denied:
        ipam_api.api_preview_prefix_address_space(
            prefix_a['id'], address_space_id=space_a['id'], user=user,
        )
    assert context_preview_denied.value.status_code == 403

    with pytest.raises(HTTPException) as preview_denied:
        ipam_api.api_preview_prefix_address_space(
            prefix_a['id'], address_space_id=space_b['id'], user=user,
        )
    assert preview_denied.value.status_code == 403

    with pytest.raises(HTTPException) as resolve_denied:
        ipam_api.api_resolve_prefix_address_space(
            prefix_a['id'],
            ResolvePrefixAddressSpaceRequest(
                address_space_id=space_b['id'], expected_updated_at='unused', confirmed=True,
                expected_revision=1,
            ),
            user=user,
        )
    assert resolve_denied.value.status_code == 403

    with pytest.raises(HTTPException) as batch_preview_denied:
        ipam_api.api_preview_prefix_address_space_batch(
            PrefixAddressSpaceBatchPreviewRequest(
                ids=[prefix_a['id']], address_space_id=space_b['id'],
            ),
            user=user,
        )
    assert batch_preview_denied.value.status_code == 403

    with pytest.raises(HTTPException) as batch_resolve_denied:
        ipam_api.api_resolve_prefix_address_space_batch(
            ResolvePrefixAddressSpaceBatchRequest(
                address_space_id=space_b['id'], expected_target_revision=1,
                items=[PrefixAddressSpaceBatchItem(
                    prefix_id=prefix_a['id'], expected_updated_at='unused', expected_revision=1,
                )],
                confirmed=True,
            ),
            user=user,
        )
    assert batch_resolve_denied.value.status_code == 403

    create_user = _restricted_viewer(make_user, site_a, create=True, role='Operator')
    with pytest.raises(HTTPException) as create_denied:
        ipam_api.api_create_subnet(
            PrefixCreate(
                prefix='198.18.23.0/24', address_space_id=space_b['id'],
                site_id=site_a, name='Out-of-scope target space',
            ),
            user=create_user,
        )
    assert create_denied.value.status_code == 403


def test_interface_candidate_preview_and_generation_are_site_scoped(isolated_db, make_user, monkeypatch):
    del isolated_db
    site_a, site_b = _id('ipam-candidate-site-a'), _id('ipam-candidate-site-b')
    _site(site_a)
    _site(site_b)
    user = _restricted_viewer(make_user, site_a, create=True, role='Operator')
    candidates = [
        {
            'candidate_id': 'candidate-site-a', 'prefix': '198.18.31.0/24',
            'tenant_id': 'tenant-default', 'site_id': site_a, 'address_space_id': None,
            'status': 'to_create', 'vrf_scope_pending': False, 'vrf_scope_defaulted': False,
            'interface_count': 1, 'ip_count': 1, 'interfaces': [],
        },
        {
            'candidate_id': 'candidate-site-b', 'prefix': '198.18.32.0/24',
            'tenant_id': 'tenant-default', 'site_id': site_b, 'address_space_id': None,
            'status': 'to_create', 'vrf_scope_pending': False, 'vrf_scope_defaulted': False,
            'interface_count': 1, 'ip_count': 1, 'interfaces': [],
        },
    ]
    monkeypatch.setattr(
        ipam_service, '_load_interface_prefix_candidates',
        lambda _conn, **_kwargs: {
            'source': 'cmdb_interface_snapshot', 'source_label': 'current snapshot',
            'candidate_count': 2, 'existing_count': 0, 'to_create_count': 2,
            'interface_count': 2, 'scope_pending_count': 0, 'vrf_pending_count': 0,
            'vrf_defaulted_count': 0, 'skipped_count': 0, 'candidates': candidates,
            'skipped': [], 'skipped_truncated_count': 0,
        },
    )

    preview = ipam_api.api_preview_interface_prefixes(
        user=user, page=1, page_size=100, status='all',
    )
    assert [item['candidate_id'] for item in preview['candidates']] == ['candidate-site-a']
    assert preview['candidate_count'] == 1
    assert preview['skipped_count'] == 0

    with pytest.raises(HTTPException) as hidden_candidate:
        ipam_api.api_generate_interface_prefixes(
            ipam_api.InterfacePrefixGenerateRequest(candidate_ids=['candidate-site-b']),
            user=user,
            idempotency_key=None,
        )
    assert hidden_candidate.value.status_code == 404

    with pytest.raises(ValueError, match='候选不存在或无权访问'):
        ipam_service.generate_interface_prefixes(
            candidate_ids=['candidate-site-b'],
            allowed_scopes={('tenant-default', site_a)},
        )

    captured: dict = {}
    monkeypatch.setattr(
        ipam_api, 'generate_interface_prefixes',
        lambda **kwargs: captured.update(kwargs) or {'ok': True},
    )
    result = ipam_api.api_generate_interface_prefixes(
        ipam_api.InterfacePrefixGenerateRequest(all_pending=True),
        user=user,
        idempotency_key=None,
    )
    assert result['ok'] is True
    assert captured['allowed_scopes'] == {('tenant-default', site_a)}
