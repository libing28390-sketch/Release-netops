from __future__ import annotations

import pytest
from fastapi import HTTPException

from api import ipam as ipam_api


def test_gateway_candidates_route_forwards_address_space_and_preserves_site_scope(monkeypatch):
    service_calls: list[dict] = []
    scope_calls: list[dict] = []
    monkeypatch.setattr(
        ipam_api,
        'get_prefix_gateway_candidates',
        lambda **kwargs: service_calls.append(kwargs) or {'status': 'ok'},
    )
    monkeypatch.setattr(
        ipam_api,
        'enforce_resource_scope',
        lambda user, resource, action, **scope: scope_calls.append({
            'user': user, 'resource': resource, 'action': action, **scope,
        }),
    )
    user = {'id': 'gateway-route-user', 'role': 'Viewer', 'tenant_id': 'tenant-default'}

    result = ipam_api.api_prefix_gateway_candidates(
        prefix='192.0.2.0/24',
        site_id='gateway-site-a',
        gateway_ip='192.0.2.1',
        address_space_id='as-global-selected',
        user=user,
    )

    assert result == {'status': 'ok'}
    assert service_calls == [{
        'prefix': '192.0.2.0/24',
        'site_id': 'gateway-site-a',
        'tenant_id': 'tenant-default',
        'gateway_ip': '192.0.2.1',
        'address_space_id': 'as-global-selected',
    }]
    assert scope_calls == [{
        'user': user,
        'resource': 'prefix',
        'action': 'view',
        'tenant_id': 'tenant-default',
        'site_id': 'gateway-site-a',
    }]


def test_gateway_candidates_route_maps_invalid_selection_to_422(monkeypatch):
    monkeypatch.setattr(
        ipam_api,
        'get_prefix_gateway_candidates',
        lambda **_kwargs: (_ for _ in ()).throw(ValueError('Address space does not own the requested Prefix')),
    )

    with pytest.raises(HTTPException) as rejected:
        ipam_api.api_prefix_gateway_candidates(
            prefix='192.0.2.0/24',
            site_id=None,
            gateway_ip=None,
            address_space_id='as-global-wrong',
            user={'id': 'gateway-route-user', 'role': 'Administrator'},
        )

    assert rejected.value.status_code == 422
    assert rejected.value.detail == 'Address space does not own the requested Prefix'
