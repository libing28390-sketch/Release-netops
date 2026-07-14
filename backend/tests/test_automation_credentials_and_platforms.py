from api.automation import _resolve_execution_credentials
from services.operational_data_service import (
    PLATFORM_DEVICE_TYPE_MAP,
    _normalize_platform,
    _resolve_commands,
)
from drivers.netmiko_driver import NetmikoDriver as LegacyNetmikoDriver
from engine.drivers.netmiko_driver import NetmikoDriver as EngineNetmikoDriver


def test_execute_auto_credentials_use_paired_primary_then_admin_then_normal():
    device = {
        "username": "",
        "password": "",
        "admin_username": "admin",
        "admin_password": "admin-pass",
        "normal_username": "user",
        "normal_password": "user-pass",
    }

    creds = _resolve_execution_credentials(device, "auto")

    assert creds["username"] == "admin"
    assert creds["password"] == "admin-pass"


def test_execute_normal_credentials_keep_username_password_pairing():
    device = {
        "username": "primary",
        "password": "primary-pass",
        "admin_username": "admin",
        "admin_password": "admin-pass",
        "normal_username": "user",
        "normal_password": "",
    }

    creds = _resolve_execution_credentials(device, "normal")

    assert creds["username"] == "primary"
    assert creds["password"] == "primary-pass"


def test_execute_default_credentials_are_normal_first_for_automation_tasks():
    device = {
        "username": "primary",
        "password": "primary-pass",
        "admin_username": "admin",
        "admin_password": "admin-pass",
        "normal_username": "user",
        "normal_password": "user-pass",
    }

    creds = _resolve_execution_credentials(device)

    assert creds["username"] == "user"
    assert creds["password"] == "user-pass"


def test_execute_admin_credentials_are_admin_first_for_explicit_admin_tasks():
    device = {
        "username": "primary",
        "password": "primary-pass",
        "admin_username": "admin",
        "admin_password": "admin-pass",
        "normal_username": "user",
        "normal_password": "user-pass",
    }

    creds = _resolve_execution_credentials(device, "admin")

    assert creds["username"] == "admin"
    assert creds["password"] == "admin-pass"


def test_h3c_platform_uses_comware_operational_commands():
    platform = _normalize_platform("h3c")
    commands = _resolve_commands(platform, ["interfaces", "routing_table"])

    assert platform == "h3c_comware"
    assert commands["interfaces"] == ["display interface brief"]
    assert commands["routing_table"] == ["display ip routing-table"]


def test_h3c_platform_maps_to_hp_comware_for_both_netmiko_drivers():
    legacy_driver = LegacyNetmikoDriver({"ip_address": "192.0.2.10", "platform": "h3c"})
    engine_driver = EngineNetmikoDriver({"ip_address": "192.0.2.10", "platform": "h3c"})

    assert legacy_driver.device_type == "hp_comware"
    assert engine_driver.device_type == "hp_comware"


def test_common_vendor_aliases_normalize_to_canonical_operational_platforms():
    expected = {
        "cisco": "cisco_ios",
        "iosxe": "cisco_ios",
        "nxos": "cisco_nxos",
        "huawei": "huawei_vrp",
        "vrp": "huawei_vrp",
        "ce": "huawei_vrp",
        "h3c": "h3c_comware",
        "comware": "h3c_comware",
        "juniper": "juniper_junos",
        "junos": "juniper_junos",
        "arista": "arista_eos",
        "eos": "arista_eos",
        "ruijie": "ruijie_rgos",
        "rgos": "ruijie_rgos",
    }

    for alias, canonical in expected.items():
        assert _normalize_platform(alias) == canonical


def test_common_vendor_aliases_map_to_netmiko_device_types():
    expected = {
        "cisco": "cisco_ios",
        "iosxe": "cisco_ios",
        "nxos": "cisco_nxos",
        "huawei": "huawei",
        "vrp": "huawei",
        "ce": "huawei",
        "h3c": "hp_comware",
        "comware": "hp_comware",
        "juniper": "juniper_junos",
        "junos": "juniper_junos",
        "arista": "arista_eos",
        "eos": "arista_eos",
        "ruijie": "ruijie_os",
        "rgos": "ruijie_os",
    }

    for alias, device_type in expected.items():
        canonical = _normalize_platform(alias)
        assert PLATFORM_DEVICE_TYPE_MAP[canonical] == device_type
        assert LegacyNetmikoDriver({"ip_address": "192.0.2.10", "platform": alias}).device_type == device_type
        assert EngineNetmikoDriver({"ip_address": "192.0.2.10", "platform": alias}).device_type == device_type
