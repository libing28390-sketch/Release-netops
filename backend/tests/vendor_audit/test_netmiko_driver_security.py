from __future__ import annotations

import logging

from drivers import netmiko_driver
from engine.drivers import netmiko_driver as engine_netmiko_driver
from services.vault_service import resolve_device_credentials


class FakeInteractiveConnection:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self._reads = iter([
            "enable\nPassword:",
            "unit-test-secret\nTrying unit-test-secret...\n% Destination unreachable; gateway or host down\nSW5>",
        ])

    def find_prompt(self) -> str:
        return "SW5>"

    def write_channel(self, data: str) -> None:
        self.writes.append(data)

    def read_channel(self) -> str:
        return next(self._reads)

    def set_base_prompt(self) -> None:
        return None


class FakeEngineConnection:
    def __init__(self) -> None:
        self.enable_called = False

    def enable(self) -> None:
        self.enable_called = True


def test_no_enable_secret_skips_privilege_escalation(monkeypatch, caplog) -> None:
    connection = FakeInteractiveConnection()
    monkeypatch.setattr(netmiko_driver, "ConnectHandler", lambda **_: connection)
    caplog.set_level(logging.INFO, logger=netmiko_driver.__name__)

    driver = netmiko_driver.NetmikoDriver(
        {
            "ip_address": "10.255.0.5",
            "hostname": "SW5",
            "platform": "cisco_ios",
            "username": "user",
            "password": "login-password",
        }
    )
    driver.connect()

    assert connection.writes == []
    assert "No explicit enable secret" in caplog.text
    assert "login-password" not in caplog.text


def test_interactive_enable_response_never_logs_password_or_terminal_buffer(monkeypatch, caplog) -> None:
    connection = FakeInteractiveConnection()
    monkeypatch.setattr(netmiko_driver, "ConnectHandler", lambda **_: connection)
    caplog.set_level(logging.INFO, logger=netmiko_driver.__name__)

    driver = netmiko_driver.NetmikoDriver(
        {
            "ip_address": "10.255.0.5",
            "hostname": "SW5",
            "platform": "cisco_ios",
            "username": "user",
            "password": "login-password",
            "enable_password": "unit-test-secret",
        }
    )
    driver.connect()

    assert connection.writes == ["enable\n", "unit-test-secret\n"]
    assert "unit-test-secret" not in caplog.text
    assert "Trying" not in caplog.text
    assert "Destination unreachable" not in caplog.text
    assert "Privilege response" in caplog.text
    assert "chars=" in caplog.text


def test_credential_resolver_keeps_enable_secret_independent() -> None:
    resolved = resolve_device_credentials(
        {
            "credential_source": "local",
            "username": "user",
            "password": "login-password",
            "normal_username": "user",
            "normal_password": "login-password",
            "admin_username": "admin",
            "admin_password": "admin-password",
            "enable_password": "",
        }
    )

    assert resolved["password"] == "login-password"
    assert resolved["admin_password"] == "admin-password"
    assert resolved["enable_password"] == ""


def test_engine_driver_does_not_call_enable_without_explicit_secret(monkeypatch) -> None:
    connection = FakeEngineConnection()
    captured: dict = {}

    def fake_connect_handler(**kwargs):
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(engine_netmiko_driver, "ConnectHandler", fake_connect_handler)
    driver = engine_netmiko_driver.NetmikoDriver(
        {
            "ip_address": "10.255.0.5",
            "platform": "cisco_ios",
            "username": "user",
            "password": "login-password",
            "use_pool": False,
        }
    )
    driver.connect()

    assert connection.enable_called is False
    assert "secret" not in captured
