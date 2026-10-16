from __future__ import annotations

from api import remote_desktop


class _StubConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_legacy_disabled_environment_value_does_not_disable_remote_desktop_profiles(monkeypatch):
    connection = _StubConnection()
    monkeypatch.setenv("NETOPS_REMOTE_DESKTOP_ENABLED", "0")
    monkeypatch.setattr(remote_desktop, "get_db_connection", lambda: connection)
    monkeypatch.setattr(remote_desktop, "list_scoped_profiles", lambda _conn, _user, _ids: [])

    result = remote_desktop.get_batch_remote_desktop_profiles(asset_ids="", user={"username": "admin"})

    assert result == {"success": True, "data": []}
    assert connection.closed
