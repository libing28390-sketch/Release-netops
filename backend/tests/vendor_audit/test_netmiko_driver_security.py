from __future__ import annotations

import logging

import pytest

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


class FakeCommandConnection:
    def send_command(self, _command: str, **_kwargs) -> str:
        return "SW#show lldp neighbors\n% Invalid input detected at '^' marker.\nSW#"


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
    assert "username='user'" not in caplog.text
    assert "pwd_len" not in caplog.text
    assert "Secret set" not in caplog.text


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


def test_engine_driver_passes_explicit_ssh_algorithm_profile(monkeypatch) -> None:
    connection = FakeEngineConnection()
    captured: dict = {}

    def fake_connect_handler(**kwargs):
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(engine_netmiko_driver, "ConnectHandler", fake_connect_handler)
    driver = engine_netmiko_driver.NetmikoDriver(
        {
            "ip_address": "10.255.0.6",
            "platform": "huawei_vrp",
            "username": "user",
            "password": "login-password",
            "ssh_algorithm_profile": "legacy_break_glass",
            "use_pool": False,
        }
    )
    driver.connect()

    assert captured["disabled_algorithms"] == {}
    assert captured["disable_sha2_fix"] is False


def test_connect_failure_log_identifies_ruijie_session_preparation_without_secret(monkeypatch, caplog) -> None:
    def fail_connect_handler(**_kwargs):
        raise RuntimeError(
            "Failed to enter enable mode. Please ensure you pass the 'secret' argument to ConnectHandler."
        )

    monkeypatch.setattr(netmiko_driver, "ConnectHandler", fail_connect_handler)
    caplog.set_level(logging.INFO, logger=netmiko_driver.__name__)

    driver = netmiko_driver.NetmikoDriver(
        {
            "ip_address": "192.0.2.101",
            "hostname": "ruijie-test",
            "platform": "ruijie_rgos",
            "username": "operator",
            "password": "login-password",
        }
    )

    with pytest.raises(Exception, match="Connection failed"):
        driver.connect()

    assert "event=connect_start" in caplog.text
    assert "platform=ruijie_rgos" in caplog.text
    assert "device_type=ruijie_os" in caplog.text
    assert "ruijie_session_auto_enable=True" in caplog.text
    assert "secret_configured=False" in caplog.text
    assert "Failed to enter enable mode" in caplog.text
    assert "login-password" not in caplog.text


def test_cli_error_log_exposes_command_quote_context_without_credentials(monkeypatch, caplog) -> None:
    connection = FakeCommandConnection()
    caplog.set_level(logging.INFO, logger=netmiko_driver.__name__)

    driver = netmiko_driver.NetmikoDriver(
        {
            "ip_address": "192.0.2.101",
            "hostname": "ruijie-test",
            "platform": "ruijie_rgos",
            "username": "operator",
            "password": "login-password",
        }
    )
    driver.conn = connection

    result = driver.send_command('"show lldp neighbors"')

    assert result.success is False
    assert result.error == "CLI error: % Invalid input detected at '^' marker."
    assert "event=command_start" in caplog.text
    assert "event=command_cli_error" in caplog.text
    assert "contains_double_quote=True" in caplog.text
    assert 'command=\'"show lldp neighbors"\'' in caplog.text
    assert "output_bytes=" in caplog.text
    assert "login-password" not in caplog.text
