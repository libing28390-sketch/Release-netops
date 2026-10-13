from __future__ import annotations

import pytest

from api import remote_desktop
from services.guacamole_service import GuacamoleConnection


@pytest.mark.anyio
async def test_internal_guacamole_tunnel_bypasses_environment_proxy(monkeypatch):
    captured: dict[str, object] = {}
    expected_tunnel = object()

    async def fake_connect(uri: str, **kwargs):
        captured["uri"] = uri
        captured.update(kwargs)
        return expected_tunnel

    monkeypatch.setattr(remote_desktop.websockets, "connect", fake_connect)
    connection = GuacamoleConnection(
        auth_token="opaque-test-token",
        data_source="json",
        connection_id="91",
        websocket_url="ws://guacamole:8080/guacamole/websocket-tunnel",
    )

    tunnel = await remote_desktop._connect_guacamole_tunnel(connection)

    assert tunnel is expected_tunnel
    assert captured["uri"] == connection.websocket_url
    assert captured["proxy"] is None
    assert captured["origin"] == "http://guacamole:8080"
    assert captured["subprotocols"] == ["guacamole"]
