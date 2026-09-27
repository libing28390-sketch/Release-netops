from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from database import get_db_connection
from services import alert_rule_service
from services import background_monitor_service, monitoring_notification_outbox_service as outbox
from services import notification_service


def _insert_notification_user(
    connection,
    *,
    username: str,
    tenant_id: str,
    group_name: str,
    email: str,
) -> None:
    channels = {
        'feishu': {'webhook_url': f'https://hooks.invalid/{username}', 'enabled': True},
        'email': {'enabled': True},
    }
    connection.execute(
        '''
        INSERT INTO users (
            id, username, password, role, status, created_at, group_name,
            notification_channels, preferred_language, email, tenant_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            str(uuid.uuid4()), username, 'x', 'operator', 'active',
            datetime.now(timezone.utc).isoformat(), group_name,
            json.dumps(channels), 'zh', email, tenant_id,
        ),
    )


def test_ping_rule_resolution_includes_device_tenant(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(background_monitor_service, '_refresh_runtime_alert_rules', lambda _tenant_id: [{'id': 'rule-1'}])

    def select_rule(rules, metric_type, context):
        captured.update(metric_type=metric_type, context=context)
        return {'id': 'rule-1'}

    monkeypatch.setattr(background_monitor_service.alert_rule_service, 'select_rule', select_rule)

    result = background_monitor_service.resolve_alert_rule(
        'ping_unreachable',
        device_row={'id': 'device-1', 'hostname': 'edge-1', 'site': 'HQ', 'tenant_id': 'tenant-acme'},
        ip_address='192.0.2.10',
    )

    assert result == {'id': 'rule-1'}
    assert captured['metric_type'] == 'ping_unreachable'
    assert captured['context'] == {
        'tenant_id': 'tenant-acme',
        'device_id': 'device-1',
        'hostname': 'edge-1',
        'ip_address': '192.0.2.10',
        'site': 'HQ',
        'role': '',
        'category': 'Network',
        'device_category': '',
        'platform': '',
        'interface_name': '',
    }
    assert background_monitor_service.metric_type_from_dedupe_key('dev_offline:device-1') == 'ping_unreachable'


def test_tag_scoped_rule_loads_device_tags_before_selection(monkeypatch) -> None:
    scoped_rule = {
        'id': 'tag-rule',
        'metric_type': 'interface_down',
        'scope_type': 'tag',
        'scope_value': json.dumps({
            'version': 2,
            'expression': {'operator': 'and', 'negated': False, 'tag_ids': ['network-ops'], 'groups': []},
        }),
    }
    monkeypatch.setattr(background_monitor_service, '_refresh_runtime_alert_rules', lambda _tenant_id: [scoped_rule])
    monkeypatch.setattr(background_monitor_service, '_get_alert_device_tag_ids', lambda device_id: {'network-ops'} if device_id == 'device-1' else set())

    result = background_monitor_service.resolve_alert_rule(
        'interface_down',
        device_row={'id': 'device-1', 'tenant_id': 'tenant-acme', 'role': 'core'},
        ip_address='192.0.2.10',
        interface_name='Gi0/1',
    )

    assert result is scoped_rule


def test_runtime_alert_rule_cache_isolated_by_tenant(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(background_monitor_service, 'current_alert_rules_by_tenant', {})

    def get_runtime_rules(*, tenant_id):
        calls.append(tenant_id)
        return [{'tenant_id': tenant_id}]

    monkeypatch.setattr(background_monitor_service.alert_rule_service, 'get_runtime_rules', get_runtime_rules)

    rules_a = background_monitor_service._refresh_runtime_alert_rules('tenant-a', force=True)
    rules_b = background_monitor_service._refresh_runtime_alert_rules('tenant-b', force=True)
    cached_a = background_monitor_service._refresh_runtime_alert_rules('tenant-a')

    assert rules_a == [{'tenant_id': 'tenant-a'}]
    assert rules_b == [{'tenant_id': 'tenant-b'}]
    assert cached_a == rules_a
    assert calls == ['tenant-a', 'tenant-b']


def test_device_reachability_uses_configured_rule_and_suppresses_without_match(monkeypatch) -> None:
    configured_rule = {
        'id': 'ping-rule',
        'severity': 'major',
        'notification_channels': ['email'],
        'notification_group_names': ['network-ops'],
    }
    captured = []
    monkeypatch.setattr(background_monitor_service, 'resolve_alert_rule', lambda *_args, **_kwargs: configured_rule)
    monkeypatch.setattr(background_monitor_service, 'set_alert_state', lambda *args, **kwargs: captured.append((args, kwargs)))

    device = {'id': 'device-1', 'hostname': 'edge-1', 'tenant_id': 'tenant-acme'}
    background_monitor_service._set_device_reachability_alert(device, '192.0.2.10', reachable=False)
    active_args, active_kwargs = captured[-1]
    assert active_args[0:3] == ('dev_offline:device-1', True, 'major')
    assert active_kwargs['rule'] is configured_rule
    assert active_kwargs['notify'] is True

    monkeypatch.setattr(background_monitor_service, 'resolve_alert_rule', lambda *_args, **_kwargs: None)
    background_monitor_service._set_device_reachability_alert(device, '192.0.2.10', reachable=False)
    _, unmatched_kwargs = captured[-1]
    assert unmatched_kwargs['rule'] is None
    assert unmatched_kwargs['notify'] is False


def test_rule_groups_intersect_tenant_webhook_and_smtp_recipients(isolated_db, monkeypatch) -> None:
    connection = get_db_connection()
    try:
        _insert_notification_user(
            connection,
            username='alert-group-match', tenant_id='tenant-acme',
            group_name='network-ops', email='match@example.invalid',
        )
        _insert_notification_user(
            connection,
            username='alert-group-other', tenant_id='tenant-acme',
            group_name='application-ops', email='other@example.invalid',
        )
        _insert_notification_user(
            connection,
            username='alert-group-other-tenant', tenant_id='tenant-other',
            group_name='network-ops', email='other-tenant@example.invalid',
        )
        connection.commit()
    finally:
        connection.close()

    sent_webhooks: list[str] = []
    sent_emails: list[list[str]] = []
    monkeypatch.setattr(notification_service, 'automatic_notifications_enabled', lambda: True)
    monkeypatch.setattr(
        notification_service,
        'send_feishu',
        lambda url, _alert: (sent_webhooks.append(url) or True, ''),
    )
    monkeypatch.setattr(
        notification_service,
        'get_email_profiles_for_dispatch',
        lambda *_args, **_kwargs: [{
            'id': 'smtp-primary', 'name': 'primary', 'enabled': True,
            'recipient_targets_json': '[]',
        }],
    )
    monkeypatch.setattr(
        notification_service,
        'send_email',
        lambda _profile, recipients, _alert: (
            sent_emails.append(list(recipients))
            or {'success': True, 'recipient_count': len(recipients)}
        ),
    )

    results = notification_service.dispatch_to_tenant_users(
        {
            'title': 'Device alert',
            'status': 'active',
            'notification_group_names': ['network-ops'],
        },
        'tenant-acme',
        channels={'feishu', 'email'},
        legacy_primary=True,
        raise_on_error=True,
    )

    assert sent_webhooks == ['https://hooks.invalid/alert-group-match']
    assert sent_emails == [['match@example.invalid']]
    assert all(result['success'] for result in results)


def test_host_rule_retains_internal_channel_and_rejects_notification_group(isolated_db) -> None:
    connection = get_db_connection()
    try:
        _insert_notification_user(
            connection,
            username='host-alert-group-member', tenant_id='tenant-default',
            group_name='host-ops', email='host-ops@example.invalid',
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match='cannot target notification groups'):
        alert_rule_service.create_rule(
            {
                'name': 'Host CPU group alert',
                'metric_type': 'host_cpu',
                'scope_type': 'global',
                'scope_match_mode': 'exact',
                'severity': 'major',
                'threshold': 85,
                'notification_channels': ['workspace'],
                'notification_group_names': ['host-ops'],
            },
            tenant_id='tenant-default',
        )

    created = alert_rule_service.create_rule(
        {
            'name': 'Host CPU threshold',
            'metric_type': 'host_cpu',
            'scope_type': 'global',
            'scope_match_mode': 'exact',
            'severity': 'major',
            'threshold': 85,
            'notification_channels': ['workspace'],
            'notification_group_names': [],
        },
        tenant_id='tenant-default',
    )
    assert created['notification_channels'] == ['workspace']
    assert created['notification_group_names'] == []


def test_legacy_rule_without_channel_uses_internal_compatibility_channel(monkeypatch) -> None:
    queued: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(notification_service, 'automatic_notifications_enabled', lambda: True)
    monkeypatch.setattr(background_monitor_service, '_db_quick', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        'services.monitoring_notification_outbox_service.enqueue_alert_delivery',
        lambda *, delivery_key, channel, payload: queued.append((delivery_key, channel, payload)),
    )

    dedupe_key = 'legacy-network-default-workspace'
    background_monitor_service.webhook_last_sent.pop(dedupe_key, None)
    background_monitor_service.maybe_notify_webhook(
        dedupe_key,
        'major',
        'Legacy network alert',
        'Interface is down',
        '2026-09-27T00:00:00+00:00',
        rule={'id': 'legacy-network-rule'},
    )

    assert [channel for _key, channel, _payload in queued] == ['workspace']


def test_missing_rule_group_members_are_terminal_without_retry(isolated_db, monkeypatch) -> None:
    delivery_key = 'alert:group-without-users:active:workspace'
    outbox.enqueue_alert_delivery(
        delivery_key=delivery_key,
        channel='workspace',
        payload={
            'tenant_id': 'tenant-acme',
            'title': 'Unroutable alert',
            'notification_group_names': ['deleted-group'],
        },
    )
    monkeypatch.setattr(notification_service, 'automatic_notifications_enabled', lambda: True)

    result = outbox.process_alert_delivery_outbox(limit=1)

    assert result == {'claimed': 1, 'succeeded': 0, 'retried': 0, 'failed': 1}
    connection = get_db_connection()
    try:
        delivery = connection.execute(
            'SELECT id, status, last_error FROM alert_delivery_outbox WHERE delivery_key = ?',
            (delivery_key,),
        ).fetchone()
        assert delivery['status'] == 'failed'
        assert delivery['last_error'] == 'notification_group_no_recipients'
        attempt = connection.execute(
            "SELECT status, error_code FROM alert_delivery_attempts WHERE delivery_id = ? AND status <> 'sending' ORDER BY created_at DESC, id DESC LIMIT 1",
            (delivery['id'],),
        ).fetchone()
        assert tuple(attempt) == ('skipped', 'notification_group_no_recipients')
    finally:
        connection.close()


def test_malformed_rule_group_selection_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(notification_service, 'automatic_notifications_enabled', lambda: True)

    for malformed_groups in ('not-json', None, {'name': 'noc'}, ['']):
        results = notification_service.dispatch_to_tenant_users(
            {'notification_group_names': malformed_groups},
            'tenant-acme',
            channels={'email'},
        )
        assert results == [{
            'platform': 'notification_group',
            'success': False,
            'error': 'notification_group_invalid',
        }]
