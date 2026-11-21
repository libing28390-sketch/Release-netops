"""Keep alert storm counters accurate with bounded PostgreSQL query counts."""

from datetime import datetime, timedelta, timezone

import pytest

from api import alerts
from database import get_db_connection


class _TrackedConnection:
    def __init__(self, connection):
        self.connection = connection
        self.queries = []

    def execute(self, sql, params=()):
        self.queries.append(sql)
        return self.connection.execute(sql, params)

    def close(self):
        self.connection.close()


@pytest.mark.parametrize('tenant_scoped', [False, True])
def test_storm_statistics_preserve_counts_with_one_aggregate_scan(isolated_db, monkeypatch, tenant_scoped):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    old = now - timedelta(days=2)
    tenant = 'tenant-storm-statistics'
    connection = get_db_connection()
    try:
        connection.execute('INSERT INTO tenants (id, name) VALUES (?, ?)', (tenant, tenant))
        connection.execute(
            'INSERT INTO devices (id, hostname, ip_address, tenant_id) VALUES (?, ?, ?, ?)',
            ('device-storm', 'storm-fixture', '192.0.2.100', tenant),
        )
        rows = []
        # 500 alerts spread across workflow/severity states; one old resolved
        # alert per group stays outside the 24-hour summary.
        for index in range(500):
            state = ('open', 'acknowledged', 'investigating', 'suppressed', 'resolved')[index % 5]
            created = old if state == 'resolved' else now - timedelta(minutes=10)
            resolved = old + timedelta(minutes=20) if state == 'resolved' else None
            ack = created + timedelta(minutes=5) if state == 'acknowledged' else None
            rows.append((
                f'storm-{index}', f'storm-key-{index}', 'network_monitor',
                'CRITICAL' if state in {'open', 'suppressed'} else 'major' if state == 'acknowledged' else 'warning',
                'Synthetic storm', 'Synthetic test alert', 'device-storm',
                created.isoformat(), resolved.isoformat() if resolved else None,
                state, 'operator' if state in {'acknowledged', 'suppressed'} else '',
                ack.isoformat() if ack else None,
            ))
        connection.executemany('''
            INSERT INTO alert_events
                (id, dedupe_key, source, severity, title, message, device_id,
                 created_at, resolved_at, workflow_status, assignee, ack_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', rows)
        connection.commit()
    finally:
        connection.close()

    tracked = []

    def connect():
        item = _TrackedConnection(get_db_connection())
        tracked.append(item)
        return item

    monkeypatch.setattr(alerts, 'get_db_connection', connect)
    user = {'role': 'Viewer', 'tenant_id': tenant} if tenant_scoped else {'role': 'Administrator'}
    summary = alerts.get_alert_summary(user=user)
    assert summary == {
        'open_count': 300, 'critical_open': 100, 'major_open': 100,
        'warning_open': 100, 'acknowledged_open': 100, 'suppressed_open': 100,
        'assigned_open': 200, 'alerts_24h': 400, 'resolved_24h': 0,
        'avg_mttr_minutes': None, 'avg_mtta_minutes': 5.0,
    }
    assert len(tracked[-1].queries) == 3  # counters + bounded MTTR/MTTA samples
    listing = alerts.list_alerts(
        status='all', severity='all', notification_status='all', search='',
        site='all', assignee='all', page=1, page_size=10,
        created_from='', created_to='', user=user,
    )
    assert listing['total'] == 500
    assert len(listing['items']) == 10
    assert listing['status_counts'] == {
        'open': 100, 'acknowledged': 100, 'investigating': 100,
        'suppressed': 100, 'resolved': 100, 'all_active': 400, 'all': 500,
    }
    assert len(tracked[-1].queries) == 5  # page count, rows, filters, counters


def test_empty_alert_statistics_return_zeroes(isolated_db):
    summary = alerts.get_alert_summary(user={'role': 'Administrator'})
    assert summary['open_count'] == summary['alerts_24h'] == summary['resolved_24h'] == 0
    assert summary['avg_mttr_minutes'] is None
    assert summary['avg_mtta_minutes'] is None
