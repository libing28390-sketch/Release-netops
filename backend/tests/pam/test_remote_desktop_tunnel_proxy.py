from __future__ import annotations

import pytest

from api import remote_desktop
from services.guacamole_service import GuacamoleConnection


def test_instruction_diagnostics_keep_only_known_opcodes():
    counts: dict[str, int] = {}

    remote_desktop._record_instruction_diagnostics(
        counts,
        "5.ready,2.id;9.clipboard,14.secret-payload;",
    )

    assert counts == {"ready": 1, "other": 1}
    assert "secret-payload" not in repr(counts)


def test_instruction_diagnostics_label_internal_uuid_without_recording_value():
    counts: dict[str, int] = {}

    remote_desktop._record_instruction_diagnostics(
        counts,
        "0.,36.00000000-0000-0000-0000-000000000000;",
    )

    assert counts == {"internal": 1}
    assert "00000000" not in repr(counts)


def test_guacamole_websocket_subprotocol_must_be_explicitly_requested():
    assert remote_desktop._supports_guacamole_subprotocol("other, guacamole")
    assert not remote_desktop._supports_guacamole_subprotocol("other")
    assert not remote_desktop._supports_guacamole_subprotocol(None)


def test_guacamole_ready_or_first_screen_sync_marks_interactive_session():
    assert remote_desktop._is_interactive_session_instruction({"ready"})
    assert remote_desktop._is_interactive_session_instruction({"sync"})
    assert not remote_desktop._is_interactive_session_instruction({"args", "size"})


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
