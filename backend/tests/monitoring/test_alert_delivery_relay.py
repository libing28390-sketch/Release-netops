from __future__ import annotations

from services import alert_delivery_relay_service as relay


def test_relay_publishes_only_delivery_reference_to_matching_priority_queue(monkeypatch) -> None:
    published = []
    marked = []
    monkeypatch.setattr(
        relay,
        '_claim_ready_deliveries',
        lambda **kwargs: [
            {'id': 'delivery-critical', 'dispatch_generation': 7, 'priority': 'critical', 'redrive': False},
            {'id': 'delivery-normal', 'dispatch_generation': 2, 'priority': 'normal', 'redrive': True},
        ],
    )
    monkeypatch.setattr(relay.app, 'send_task', lambda *args, **kwargs: published.append((args, kwargs)))
    monkeypatch.setattr(relay, '_mark_published', lambda **kwargs: marked.append(kwargs) or True)

    result = relay.publish_ready_alert_deliveries(limit=5)

    assert result == {'claimed': 2, 'published': 2, 'failed': 0}
    assert [item[0][0] for item in published] == [relay.TASK_NAME, relay.TASK_NAME]
    assert published[0][1]['args'] == ['delivery-critical', 7]
    assert published[0][1]['queue'] == relay.ALERT_NOTIFY_CRITICAL_QUEUE
    assert published[1][1]['args'] == ['delivery-normal', 2]
    assert published[1][1]['queue'] == relay.ALERT_NOTIFY_NORMAL_QUEUE
    assert all('payload' not in str(item) for item in published)
    assert marked[1]['redrive'] is True


def test_relay_publish_failure_is_returned_to_postgres_backoff(monkeypatch) -> None:
    released = []
    monkeypatch.setattr(
        relay,
        '_claim_ready_deliveries',
        lambda **kwargs: [{'id': 'delivery-failure', 'dispatch_generation': 4, 'priority': 'normal', 'redrive': False}],
    )

    def fail_publish(*_args, **_kwargs):
        raise RuntimeError('broker password must not be persisted')

    monkeypatch.setattr(relay.app, 'send_task', fail_publish)
    monkeypatch.setattr(relay, '_release_publish_failure', lambda **kwargs: released.append(kwargs))

    result = relay.publish_ready_alert_deliveries(limit=1)

    assert result == {'claimed': 1, 'published': 0, 'failed': 1}
    assert released[0]['delivery_id'] == 'delivery-failure'
    assert released[0]['generation'] == 4
    assert released[0]['error_code'] == 'broker_publish_RuntimeError'
    assert 'password' not in released[0]['error_code']


def test_relay_cycle_recovers_expired_execution_before_publishing(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        'services.monitoring_notification_outbox_service.recover_expired_alert_delivery_leases',
        lambda *, limit: calls.append(('recover', limit)) or {'recovered': 3, 'failed': 1},
    )
    monkeypatch.setattr(
        relay,
        'publish_ready_alert_deliveries',
        lambda *, limit: calls.append(('publish', limit)) or {'claimed': 2, 'published': 2, 'failed': 0},
    )

    result = relay.relay_alert_deliveries_once(limit=8)

    assert result == {
        'claimed': 2,
        'published': 2,
        'failed': 0,
        'recovered': 3,
        'terminal_failures': 1,
    }
    assert calls == [('recover', 8), ('publish', 8)]
