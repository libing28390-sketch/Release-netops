from __future__ import annotations

from api.assets import _normalize_asset_platform, _platform_from_vendor
from core.platform_utils import normalize_device_platform
from core.textfsm import parse_with_textfsm, resolve_textfsm_platform
from services.normalizers.factory import NormalizerFactory
from services.platform_registry_service import (
    CONNECTION_DRIVER_TO_IMPLEMENTATION,
    PLATFORM_ACTION_COMMANDS,
    SYSTEM_PROFILES,
)
from services.snmp_service import VENDOR_OIDS, _resolve_platform


RAW_VERSION = """Raisecom Operating System Software
Copyright (c) 2006-2021 Raisecom Science & Technology Development Co.,Ltd

Product Name: ISCOM S5600-28C-EI
Hardware Version: A.00
Software Version: 3.60.317(Compiled Apr 28 2020 12:42:15)
ROS Version: ROS_5.2.1_20200428
REAP Version:3.0
Bootrom Version: 1.4.9
"""


def test_raisecom_asset_and_platform_normalization_never_uses_cisco() -> None:
    assert _platform_from_vendor("瑞斯康达") == "raisecom_ros"
    assert _normalize_asset_platform("Raisecom", "") == "raisecom_ros"
    assert normalize_device_platform("瑞斯康达", "cisco_ios") == "raisecom_ros"
    assert normalize_device_platform("瑞斯康达", "") == "raisecom_ros"


def test_raisecom_version_parser_and_textfsm_template() -> None:
    device = NormalizerFactory.get_normalizer("瑞斯康达").parse_device_info("dev-raisecom", RAW_VERSION)
    assert (device.vendor, device.platform, device.model, device.version) == (
        "Raisecom", "raisecom_ros", "ISCOM S5600-28C-EI", "3.60.317"
    )
    assert resolve_textfsm_platform("raisecom") == "raisecom_ros"
    records = parse_with_textfsm("raisecom_ros", "show version", RAW_VERSION)
    assert records and records[0]["MODEL"] == "ISCOM S5600-28C-EI"


def test_raisecom_registry_and_snmp_baseline_are_explicit() -> None:
    profile = next(item for item in SYSTEM_PROFILES if item["platform_code"] == "raisecom_ros")
    assert profile["connection_driver"] == "raisecom_ros"
    assert CONNECTION_DRIVER_TO_IMPLEMENTATION["raisecom_ros"] == "netmiko"
    assert PLATFORM_ACTION_COMMANDS["raisecom_ros"]["get_version"] == "show version"
    assert PLATFORM_ACTION_COMMANDS["raisecom_ros"]["get_interface_brief"] == "show interface brief"
    assert _resolve_platform("瑞斯康达") == "raisecom_ros"
    assert VENDOR_OIDS["raisecom_ros"]["cpu"] == "1.3.6.1.2.1.25.3.3.1.2"
