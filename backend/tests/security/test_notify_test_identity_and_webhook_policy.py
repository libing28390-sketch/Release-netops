from __future__ import annotations

import asyncio

import httpx

from api import users
from main import app
from services import notification_service


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_viewer_cannot_test_another_users_notification_destination(monkeypatch):
    actor = {"user_id": "viewer-self", "username": "viewer", "role": "Viewer", "tenant_id": "tenant-a"}
    monkeypatch.setattr(users, "validate_session_token", lambda _token: actor)

    response = _request(
        "POST",
        "/api/users/someone-else/notify-test",
        headers={"Authorization": "Bearer viewer-token"},
        json={"platform": "feishu", "webhook_url": "https://open.feishu.cn/hook/test"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "You may only test your own notification channel"


def test_notification_test_rejects_private_destination_without_network_access(monkeypatch):
    actor = {"user_id": "viewer-self", "username": "viewer", "role": "Viewer", "tenant_id": "tenant-a"}
    monkeypatch.setattr(users, "validate_session_token", lambda _token: actor)
    monkeypatch.setattr(users, "_get_system_name", lambda: "Nexora")
    monkeypatch.setattr(notification_service, "_get_system_name", lambda: "Nexora")

    class FakeResult:
        def fetchone(self):
            return {"username": "viewer"}

    class FakeConnection:
        def execute(self, _query, _params):
            return FakeResult()

        def close(self):
            pass

    monkeypatch.setattr(users, "get_db_connection", FakeConnection)

    response = _request(
        "POST",
        "/api/users/viewer-self/notify-test",
        headers={"Authorization": "Bearer viewer-token"},
        json={"platform": "feishu", "webhook_url": "https://127.0.0.1/private-hook"},
    )

    assert response.status_code == 502
    assert "IP literals are forbidden" in response.json()["detail"]
