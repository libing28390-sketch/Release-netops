import json
import uuid

import pytest

from database import get_db_connection
from services import notification_service as service


class _TrackedConnection:
    def __init__(self, connection):
        self.connection = connection
        self.close_count = 0

    def __getattr__(self, name):
        assert self.close_count == 0
        return getattr(self.connection, name)

    def close(self):
        self.close_count += 1
        self.connection.close()


def _seed_recipient():
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (id, username, password, role, status, tenant_id,
                               email, notification_channels, preferred_language)
            VALUES (?, 'notify-test', 'x', 'Viewer', 'active', 'tenant-default',
                    'notify-test@example.com', ?, 'zh')
            """,
            (str(uuid.uuid4()), json.dumps({
                'feishu': {'enabled': True, 'webhook_url': 'https://hooks.invalid/test'},
                'email': {'enabled': True},
            })),
        )
        connection.commit()


@pytest.mark.parametrize('profile_id,legacy_primary', [(None, False), (None, True), ('smtp-test', False)])
def test_dispatch_loads_all_inputs_and_releases_connection_before_sends(
    isolated_db, monkeypatch, profile_id, legacy_primary,
):
    _seed_recipient()
    monkeypatch.setattr(service, 'automatic_notifications_enabled', lambda: True)
    connections = []
    profile_options = []
    sends = []

    def tracked_connection():
        connection = _TrackedConnection(get_db_connection())
        connections.append(connection)
        return connection

    def profiles(connection, tenant_id, **kwargs):
        assert connection.close_count == 0
        assert tenant_id == 'tenant-default'
        profile_options.append(kwargs)
        return [{'id': 'smtp-test', 'name': 'primary', 'enabled': True}]

    def webhook(_url, _alert):
        assert connections[-1].close_count == 1
        sends.append('feishu')
        return True, ''

    def email(_config, recipients, _alert):
        assert connections[-1].close_count == 1
        assert recipients == ['notify-test@example.com']
        sends.append('email')
        return {'success': True, 'recipient_count': 1}

    monkeypatch.setattr(service, 'get_db_connection', tracked_connection)
    monkeypatch.setattr(service, 'get_email_profiles_for_dispatch', profiles)
    monkeypatch.setattr(service, 'send_feishu', webhook)
    monkeypatch.setattr(service, 'send_email', email)
    result = service.dispatch_to_tenant_users(
        {'status': 'active', 'title': 'test alert'}, 'tenant-default',
        channels={'feishu', 'email'}, profile_id=profile_id, legacy_primary=legacy_primary,
    )

    assert sends == ['feishu', 'email']
    assert len(result) == 2
    assert all(item['success'] for item in result)
    assert len(connections) == 1
    assert connections[0].close_count == 1
    expected_option = (
        {'profile_id': profile_id} if profile_id else
        {'legacy_primary': True} if legacy_primary else {'enabled_only': True}
    )
    assert profile_options == [expected_option]


def test_failed_send_does_not_hold_or_double_close_connection(isolated_db, monkeypatch):
    _seed_recipient()
    monkeypatch.setattr(service, 'automatic_notifications_enabled', lambda: True)
    tracked = _TrackedConnection(get_db_connection())
    monkeypatch.setattr(service, 'get_db_connection', lambda: tracked)

    def failed_send(_url, _alert):
        assert tracked.close_count == 1
        raise RuntimeError('synthetic sender failure')

    monkeypatch.setattr(service, 'send_feishu', failed_send)
    with pytest.raises(RuntimeError, match='synthetic sender failure'):
        service.dispatch_to_tenant_users(
            {'status': 'active'}, 'tenant-default', channels={'feishu'}, raise_on_error=True,
        )
    assert tracked.close_count == 1


@pytest.mark.parametrize('raise_on_error', [False, True])
def test_email_profile_lookup_failure_preserves_webhook_delivery(
    isolated_db, monkeypatch, raise_on_error,
):
    _seed_recipient()
    monkeypatch.setattr(service, 'automatic_notifications_enabled', lambda: True)
    tracked = _TrackedConnection(get_db_connection())
    monkeypatch.setattr(service, 'get_db_connection', lambda: tracked)
    sends = []

    def failed_profiles(*_args, **_kwargs):
        raise RuntimeError('synthetic SMTP lookup failure')

    def webhook(_url, _alert):
        assert tracked.close_count == 1
        sends.append('feishu')
        return True, ''

    monkeypatch.setattr(service, 'get_email_profiles_for_dispatch', failed_profiles)
    monkeypatch.setattr(service, 'send_feishu', webhook)
    args = ({'status': 'active'}, 'tenant-default')
    kwargs = {'channels': {'feishu', 'email'}, 'raise_on_error': raise_on_error}
    if raise_on_error:
        with pytest.raises(RuntimeError, match='synthetic SMTP lookup failure'):
            service.dispatch_to_tenant_users(*args, **kwargs)
    else:
        assert service.dispatch_to_tenant_users(*args, **kwargs) == []
    assert sends == ['feishu']
    assert tracked.close_count == 1
