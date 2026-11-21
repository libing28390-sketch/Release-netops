from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_wan_circuit_scope_hides_cross_tenant_and_site_rows(monkeypatch) -> None:
    from api import monitoring

    user = {'role': 'Viewer', 'tenant_id': 'tenant-a'}
    scope = SimpleNamespace(tenant_id='tenant-a', site_ids=('site-a',))
    monkeypatch.setattr(monitoring, '_wan_effective_scope', lambda _user, _action='view': scope)

    for item in (
        {'id': 'other-tenant', 'tenant_id': 'tenant-b', 'site_id': 'site-a'},
        {'id': 'other-site', 'tenant_id': 'tenant-a', 'site_id': 'site-b'},
    ):
        with pytest.raises(HTTPException) as error:
            monitoring._enforce_wan_link_scope(user, item)
        assert error.value.status_code == 404
        assert error.value.detail['code'] == 'WAN_LINK_NOT_FOUND'


def test_wan_circuit_scope_returns_only_a_link_inside_the_effective_scope(monkeypatch) -> None:
    from api import monitoring

    user = {'role': 'Viewer', 'tenant_id': 'tenant-a'}
    item = {'id': 'allowed', 'tenant_id': 'tenant-a', 'site_id': 'site-a'}
    scope = SimpleNamespace(tenant_id='tenant-a', site_ids=('site-a',))
    monkeypatch.setattr(monitoring, '_wan_effective_scope', lambda _user, _action='view': scope)

    assert monitoring._enforce_wan_link_scope(user, item) is item


def test_wan_circuit_scope_keeps_role_action_denial_as_forbidden(monkeypatch) -> None:
    from api import monitoring

    user = {'role': 'Viewer', 'tenant_id': 'tenant-a'}
    item = {'id': 'allowed', 'tenant_id': 'tenant-a', 'site_id': 'site-a'}
    monkeypatch.setattr(
        monitoring,
        '_wan_effective_scope',
        lambda _user, _action='view': SimpleNamespace(tenant_id='tenant-a', site_ids=('site-a',)),
    )

    with pytest.raises(HTTPException) as error:
        monitoring._enforce_wan_link_scope(user, item, 'update')
    assert error.value.status_code == 403


def test_legacy_wan_list_routes_forward_tenant_and_site_scope(monkeypatch) -> None:
    from api import monitoring
    from services import wan_link_service, wan_p1_service, wan_p2_service

    user = {'role': 'Viewer', 'tenant_id': 'tenant-a'}
    scope = SimpleNamespace(tenant_id='tenant-a', site_ids=('site-a',))
    monkeypatch.setattr(monitoring, '_wan_effective_scope', lambda _user, _action='view': scope)
    seen: dict[str, dict] = {}

    def capture(name):
        def handler(*args, **kwargs):
            seen[name] = kwargs
            return {}
        return handler

    monkeypatch.setattr(wan_link_service, 'list_wan_alert_events', capture('alerts'))
    monkeypatch.setattr(wan_p1_service, 'list_wan_maintenance_windows', capture('maintenance'))
    monkeypatch.setattr(wan_p1_service, 'list_wan_reports', capture('reports'))
    monkeypatch.setattr(wan_p1_service, 'list_wan_link_groups', capture('groups'))
    monkeypatch.setattr(wan_p2_service, 'list_probe_bindings', capture('bindings'))
    monkeypatch.setattr(wan_p2_service, 'list_wan_correlation_events', capture('correlations'))
    monkeypatch.setattr(wan_p2_service, 'list_wan_capacity_recommendations', capture('capacity'))
    monkeypatch.setattr(wan_p2_service, 'get_wan_cockpit', capture('cockpit'))

    monitoring.get_monitoring_wan_alert_events(site_id='', user=user)
    monitoring.get_monitoring_wan_maintenance_windows(user=user)
    monitoring.get_monitoring_wan_reports(user=user)
    monitoring.get_monitoring_wan_link_groups(user=user)
    monitoring.get_monitoring_wan_probe_bindings(user=user)
    monitoring.get_monitoring_wan_correlations(site_id='', user=user)
    monitoring.get_monitoring_wan_capacity_recommendations(user=user)
    monitoring.get_monitoring_wan_cockpit(user=user)

    assert set(seen) == {'alerts', 'maintenance', 'reports', 'groups', 'bindings', 'correlations', 'capacity', 'cockpit'}
    for kwargs in seen.values():
        assert kwargs['tenant_id'] == 'tenant-a'
        assert kwargs['site_ids'] == ('site-a',)


def test_scoped_actor_carries_effective_server_side_scope(monkeypatch) -> None:
    from api import monitoring

    user = {'role': 'Operator', 'tenant_id': 'tenant-a', 'site_ids': ('client-site',)}
    scope = SimpleNamespace(tenant_id='tenant-a', site_ids=('authorized-site',))
    monkeypatch.setattr(monitoring, '_wan_effective_scope', lambda _user, _action='update': scope)

    actor = monitoring._wan_scoped_actor(user)

    assert actor['tenant_id'] == 'tenant-a'
    assert actor['site_ids'] == ('authorized-site',)


def test_scoped_actor_and_global_recompute_refuse_empty_or_limited_scope(monkeypatch) -> None:
    from api import monitoring

    user = {'role': 'Operator', 'tenant_id': 'tenant-a'}
    empty_scope = SimpleNamespace(tenant_id='tenant-a', site_ids=())
    monkeypatch.setattr(monitoring, '_wan_effective_scope', lambda _user, _action='update': empty_scope)
    with pytest.raises(HTTPException) as no_sites:
        monitoring._wan_scoped_actor(user)
    assert no_sites.value.status_code == 404

    limited_scope = SimpleNamespace(tenant_id='tenant-a', site_ids=('site-a',))
    monkeypatch.setattr(monitoring, '_wan_effective_scope', lambda _user, _action='update': limited_scope)
    with pytest.raises(HTTPException) as limited_global:
        monitoring._wan_require_global_scope(user)
    assert limited_global.value.status_code == 403


def test_global_recompute_requires_cross_tenant_scope(monkeypatch) -> None:
    from api import monitoring

    user = {'role': 'Administrator'}
    monkeypatch.setattr(
        monitoring,
        '_wan_effective_scope',
        lambda _user, _action='update': SimpleNamespace(tenant_id=None, site_ids=None),
    )

    monitoring._wan_require_global_scope(user)


def test_sla_policy_accepts_zero_version_for_first_policy_creation() -> None:
    from api.monitoring import WanSlaPolicyPayload

    payload = WanSlaPolicyPayload()

    assert payload.expected_version == 0


def test_circuit_sla_route_returns_line_context_evidence(monkeypatch) -> None:
    from api import monitoring
    from services import wan_circuit_service, wan_line_probe_service

    user = {'role': 'Viewer', 'tenant_id': 'tenant-a'}
    link = {'id': 'line-a', 'tenant_id': 'tenant-a', 'site_id': 'site-a'}
    monkeypatch.setattr(monitoring, '_enforce_wan_link_scope', lambda _user, item, _action='view': item)
    monkeypatch.setattr(monitoring, '_wan_tenant_filter', lambda _user: 'tenant-a')
    monkeypatch.setattr(wan_circuit_service, 'get_wan_circuit', lambda *_args, **_kwargs: link)
    monkeypatch.setattr(wan_line_probe_service, 'get_wan_line_sla', lambda *args, **kwargs: {
        'link_id': args[0], 'status': 'insufficient_data', 'reason_code': 'path_evidence_unavailable',
        'availability': {'value': None, 'lower_bound': None, 'upper_bound': None},
        'observed_availability': None, 'coverage_percent': 0.0, 'slot_stats': {'up': 0, 'down': 0, 'unknown': 5},
        'slots': 5, 'evidence': {'path_proven': False},
    })

    result = monitoring.get_monitoring_wan_circuit_sla('line-a', window='24h', user=user)

    assert result['status'] == 'insufficient_data'
    assert result['reason_code'] == 'path_evidence_unavailable'
    assert result['coverage_pct'] == 0.0
    assert result['slots'] == {'up': 0, 'down': 0, 'unknown': 5, 'maintenance': 0}
    assert result['evidence']['path_proven'] is False


def test_endpoint_history_route_enforces_circuit_scope(monkeypatch) -> None:
    from api import monitoring
    from services import wan_circuit_service

    user = {'role': 'Viewer', 'tenant_id': 'tenant-a'}
    link = {'id': 'line-a', 'tenant_id': 'tenant-a', 'site_id': 'site-a'}
    history = [{'side': 'A', 'endpoint_version': 1, 'valid_to': None}]
    calls = []
    monkeypatch.setattr(monitoring, '_enforce_wan_link_scope', lambda _user, item, _action='view': item)
    monkeypatch.setattr(monitoring, '_wan_tenant_filter', lambda _user: 'tenant-a')
    monkeypatch.setattr(wan_circuit_service, 'get_wan_circuit', lambda *_args, **_kwargs: link)
    monkeypatch.setattr(wan_circuit_service, 'list_wan_circuit_endpoint_history', lambda *args, **kwargs: calls.append((args, kwargs)) or history)

    result = monitoring.get_monitoring_wan_circuit_endpoint_history('line-a', user=user)

    assert result == {'items': history, 'total': 1}
    assert calls[0][1]['tenant_id'] == 'tenant-a'
