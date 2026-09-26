from __future__ import annotations

from api.assets import _normalize_asset_platform, _platform_from_vendor
from core.platform_utils import normalize_device_platform
from services.config_vendor_platform_service import validate_vendor_platform


def test_hillstone_vendor_always_maps_to_stoneos_without_cisco_fallback() -> None:
    for vendor in ("Hillstone", "StoneOS", "山石"):
        assert _platform_from_vendor(vendor) == "hillstone_stoneos"
        assert _normalize_asset_platform(vendor, "") == "hillstone_stoneos"
        assert _normalize_asset_platform(vendor, "cisco_ios") == "hillstone_stoneos"
        assert normalize_device_platform(vendor, "cisco_ios") == "hillstone_stoneos"

    assert normalize_device_platform("", "StoneOS") == "hillstone_stoneos"
    assert normalize_device_platform("Arista", "cisco_ios") == "arista_eos"


def test_hillstone_platform_aliases_are_accepted_by_config_vendor_contract() -> None:
    for platform in (
        "hillstone_stoneos",
        "Hillstone",
        "Hillstone StoneOS",
        "StoneOS",
        "山石",
        "山石 StoneOS",
    ):
        assert _normalize_asset_platform("Hillstone", platform) == "hillstone_stoneos"
        assert validate_vendor_platform("Hillstone", platform) == ("Hillstone", "hillstone_stoneos")

    assert validate_vendor_platform("StoneOS", "StoneOS") == ("Hillstone", "hillstone_stoneos")
