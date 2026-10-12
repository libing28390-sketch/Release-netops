from __future__ import annotations

import json

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


def test_relay_postgresql_batch_shares_preserve_normal_and_fill_idle_priority(isolated_db, monkeypatch) -> None:
    database = isolated_db['module']
    monkeypatch.setattr(relay, 'get_db_connection', database.get_db_connection)
    published = []
    monkeypatch.setattr(relay.app, 'send_task', lambda *args, **kwargs: published.append((args, kwargs)))

    def insert_deliveries(*, prefix: str, critical: int, normal: int, severity_critical: int = 0) -> None:
        connection = database.get_db_connection()
        try:
            for index in range(critical):
                delivery_id = f'{prefix}-critical-{index}'
                priority = 'normal' if index < severity_critical else 'critical'
                severity = 'p1' if index < severity_critical else 'warning'
                connection.execute(
                    """
                    INSERT INTO alert_delivery_outbox (id, delivery_key, channel, payload, priority)
                    VALUES (?, ?, 'workspace', ?::jsonb, ?)
                    """,
                    (delivery_id, f'{prefix}:{delivery_id}', json.dumps({'severity': severity}), priority),
                )
            for index in range(normal):
                delivery_id = f'{prefix}-normal-{index}'
                connection.execute(
                    """
                    INSERT INTO alert_delivery_outbox (id, delivery_key, channel, payload, priority)
                    VALUES (?, ?, 'workspace', ?::jsonb, 'normal')
                    """,
                    (delivery_id, f'{prefix}:{delivery_id}', json.dumps({'severity': 'warning'})),
                )
            connection.commit()
        finally:
            connection.close()

    def clear_pending() -> None:
        connection = database.get_db_connection()
        try:
            connection.execute(
                "UPDATE alert_delivery_outbox SET status = 'succeeded' WHERE status = 'pending'"
            )
            connection.commit()
        finally:
            connection.close()

    def publish_batch(*, limit: int) -> tuple[dict[str, int], list[tuple]]:
        start = len(published)
        result = relay.publish_ready_alert_deliveries(limit=limit)
        assert result['claimed'] <= limit
        assert result['published'] == result['claimed']
        return result, published[start:]

    # A continuous critical backlog must still leave two of every eight slots
    # for normal deliveries. One normal-priority row is critical by severity.
    insert_deliveries(prefix='share', critical=20, normal=6, severity_critical=1)
    for _ in range(3):
        result, batch = publish_batch(limit=8)
        assert result == {'claimed': 8, 'published': 8, 'failed': 0}
        priorities = [item[1]['queue'] for item in batch]
        assert priorities.count(relay.ALERT_NOTIFY_CRITICAL_QUEUE) == 6
        assert priorities.count(relay.ALERT_NOTIFY_NORMAL_QUEUE) == 2

    # When normal is idle, the remaining critical rows can use its reserved slots.
    clear_pending()
    insert_deliveries(prefix='critical-only', critical=12, normal=0)
    result, batch = publish_batch(limit=8)
    assert result == {'claimed': 8, 'published': 8, 'failed': 0}
    assert all(item[1]['queue'] == relay.ALERT_NOTIFY_CRITICAL_QUEUE for item in batch)

    # A small critical backlog is included even with a larger normal backlog;
    # normal rows then fill the unused critical allocation to the batch limit.
    clear_pending()
    insert_deliveries(prefix='mixed-short-critical', critical=2, normal=12)
    result, batch = publish_batch(limit=8)
    assert result == {'claimed': 8, 'published': 8, 'failed': 0}
    priorities = [item[1]['queue'] for item in batch]
    assert priorities.count(relay.ALERT_NOTIFY_CRITICAL_QUEUE) == 2
    assert priorities.count(relay.ALERT_NOTIFY_NORMAL_QUEUE) == 6

    # When critical is idle, normal rows can use the entire batch.
    clear_pending()
    insert_deliveries(prefix='normal-only', critical=0, normal=12)
    result, batch = publish_batch(limit=8)
    assert result == {'claimed': 8, 'published': 8, 'failed': 0}
    assert all(item[1]['queue'] == relay.ALERT_NOTIFY_NORMAL_QUEUE for item in batch)

    # A one-item batch retains critical-first compatibility without claiming
    # a durable fairness guarantee for both priorities.
    clear_pending()
    insert_deliveries(prefix='single-slot', critical=1, normal=1)
    result, batch = publish_batch(limit=1)
    assert result == {'claimed': 1, 'published': 1, 'failed': 0}
    assert batch[0][1]['queue'] == relay.ALERT_NOTIFY_CRITICAL_QUEUE
