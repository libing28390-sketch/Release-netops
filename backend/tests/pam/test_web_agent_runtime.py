from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).parents[3]
terminal_agent = _load_script("terminal_agent_web_runtime", ROOT / "scripts" / "terminal_agent.py")


def test_web_launch_exchanges_token_and_opens_system_browser(monkeypatch):
    monkeypatch.setenv('NEXORA_AGENT_ALLOWED_ORIGINS', 'https://netops.example.test')
    monkeypatch.setattr(terminal_agent, "_WEB_BROWSER_AVAILABLE", True)
    exchanged = {
        "session_id": "session-1",
        "callback_token": "callback-secret",
        "target_url": "https://192.0.2.10:8443/login",
    }
    opened = {}

    monkeypatch.setattr(terminal_agent, "_exchange_web_session", lambda *args: exchanged)
    monkeypatch.setattr(
        terminal_agent,
        "_start_system_browser",
        lambda target_url: opened.update(target_url=target_url) or (None, None),
    )
    monkeypatch.setattr(terminal_agent, "_monitor_web_session", lambda *args: None)

    terminal_agent._launch_web_window(
        "https://netops.example.test/dashboard", "secret-session-token", "agent-1"
    )

    assert opened["target_url"] == exchanged["target_url"]
    assert "secret-session-token" not in opened["target_url"]


def test_web_launch_requires_a_system_browser(monkeypatch):
    monkeypatch.setenv('NEXORA_AGENT_ALLOWED_ORIGINS', 'https://netops.example.test')
    monkeypatch.setattr(terminal_agent, "_WEB_BROWSER_AVAILABLE", False)
    monkeypatch.setattr(
        terminal_agent,
        "_exchange_web_session",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not exchange without a browser")),
    )

    try:
        terminal_agent._launch_web_window("https://netops.example.test", "secret-token", "agent-1")
    except RuntimeError as exc:
        assert "system browser" in str(exc)
    else:
        raise AssertionError("expected a browser availability error")


def test_web_recording_multipart_body_contains_callback_fields():
    body, content_type = terminal_agent._multipart_body(
        {"callback_token": "callback-secret", "agent_id": "agent-1"},
        "recording.zip",
        "application/zip",
        b"PK-test-recording",
    )
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="callback_token"' in body
    assert b"callback-secret" in body
    assert b'name="agent_id"' in body
    assert b"recording.zip" in body


def test_png_encoder_returns_a_valid_png():
    image = terminal_agent._encode_png(1, 1, bytes((255, 0, 0)))
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert image.endswith(b"IEND\xaeB`\x82")
