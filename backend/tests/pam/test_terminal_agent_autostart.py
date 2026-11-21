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
terminal_agent = _load_script("terminal_agent_autostart", ROOT / "scripts" / "terminal_agent.py")


def test_autostart_command_uses_managed_start_for_frozen_agent(monkeypatch, tmp_path):
    executable = tmp_path / "Nexora Terminal Agent.exe"
    executable.write_bytes(b"agent")
    monkeypatch.setattr(terminal_agent.sys, "frozen", True, raising=False)
    monkeypatch.setattr(terminal_agent.sys, "executable", str(executable))

    command = terminal_agent._autostart_command(17891)

    assert str(executable) in command
    assert terminal_agent.MANAGED_START_FLAG in command
    assert "--host 127.0.0.1" in command
    assert "--port 17891" in command


def test_ensure_windows_autostart_registers_only_on_windows(monkeypatch):
    registered: list[int] = []
    monkeypatch.setattr(terminal_agent, "_register_windows_autostart", registered.append)

    monkeypatch.setattr(terminal_agent.sys, "platform", "linux")
    terminal_agent._ensure_windows_autostart(17890)
    assert registered == []

    monkeypatch.setattr(terminal_agent.sys, "platform", "win32")
    terminal_agent._ensure_windows_autostart(17890)
    assert registered == [17890]


def test_ensure_windows_autostart_keeps_agent_running_when_registration_fails(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(terminal_agent.sys, "platform", "win32")
    monkeypatch.setattr(
        terminal_agent,
        "_register_windows_autostart",
        lambda _port: (_ for _ in ()).throw(OSError("access denied")),
    )
    monkeypatch.setattr(terminal_agent, "_show_windows_warning", warnings.append)

    terminal_agent._ensure_windows_autostart(17890)

    assert warnings and "access denied" in warnings[0]
