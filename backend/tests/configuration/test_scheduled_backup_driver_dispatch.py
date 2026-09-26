from contextlib import nullcontext

import pytest

from core.platform_utils import normalize_device_platform
from engine.drivers.netmiko_driver import NetmikoDriver
from engine.registry import DriverRegistry
from services.automation_service import AutomationService
from services.config_backup_command_service import (
    get_config_backup_platform,
    get_default_config_backup_commands,
)


class _FakeNetworkAccessLimiter:
    def ssh(self, *_args, **_kwargs):
        return nullcontext()


@pytest.mark.parametrize(
    ("vendor", "inventory_platform", "expected_platform", "expected_netmiko_type"),
    [
        ("Cisco", "cisco_ios", "cisco_ios", "cisco_ios"),
        ("Huawei", "huawei_vrp", "huawei_vrp", "huawei"),
        ("H3C", "h3c_comware", "h3c_comware", "hp_comware"),
    ],
)
def test_scheduled_backup_routes_cmdb_network_asset_to_vendor_driver(
    monkeypatch,
    vendor,
    inventory_platform,
    expected_platform,
    expected_netmiko_type,
):
    observed = {}

    def fake_execute(self, mode, content, **_kwargs):
        observed["platform"] = self.platform
        observed["netmiko_type"] = self.device_type
        observed["command"] = content
        observed["mode"] = mode.value
        return {"success": True, "stdout": "mock running configuration"}

    monkeypatch.setattr(NetmikoDriver, "execute", fake_execute)
    monkeypatch.setattr(
        "services.network_access_limiter.get_network_access_limiter",
        lambda: _FakeNetworkAccessLimiter(),
    )

    normalized_platform = normalize_device_platform(vendor, inventory_platform)
    platform = get_config_backup_platform(vendor, normalized_platform)
    commands = get_default_config_backup_commands(vendor, platform)
    assert commands is not None
    assert platform == expected_platform

    device = {
        "asset_type": "network_device",
        "vendor": vendor,
        "platform": platform,
        "ip_address": "192.0.2.10",
        "username": "backup-test",
        "password": "not-a-real-password",
        "use_pool": False,
    }
    results = AutomationService(driver_type="netmiko").execute_commands(
        device,
        [commands["get_running_config"]],
    )

    assert results[0]["success"] is True
    assert observed == {
        "platform": expected_platform,
        "netmiko_type": expected_netmiko_type,
        "command": commands["get_running_config"],
        "mode": "command",
    }


def test_unknown_asset_type_still_returns_an_explicit_driver_error():
    with pytest.raises(ValueError, match="No driver found for asset_type: unsupported_kind"):
        DriverRegistry.get_driver("unsupported_kind", {})
