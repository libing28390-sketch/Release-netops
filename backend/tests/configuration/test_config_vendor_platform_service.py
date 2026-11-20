import pytest

from services.config_vendor_platform_service import (
    allowed_platforms,
    canonical_vendor,
    match_platform_profile,
    platform_profiles,
    validate_vendor_platform,
)


def test_model_series_is_a_profile_not_a_new_platform() -> None:
    assert validate_vendor_platform("ZTE", "中兴 ZXROS") == ("ZTE", "zte_zxros")
    profile = match_platform_profile("ZTE", "zte_zxros", "5960X-56QU-HF")
    assert profile and profile["series"] == "ZXR10 5900/5960"
    assert len(platform_profiles("Ruijie", "ruijie_os")) >= 2


def test_known_vendor_platforms_are_catalogued() -> None:
    assert "cisco_iosxe" in allowed_platforms("Cisco")
    assert "huawei_vrpv8" in allowed_platforms("Huawei")
    assert allowed_platforms("H3C") == ("h3c_comware",)
    assert "paloalto_panos" in allowed_platforms("Palo Alto")
    assert "fiberhome_fengine" in allowed_platforms("FiberHome")
    assert allowed_platforms("瑞斯康达") == ("raisecom_ros",)


def test_vendor_platform_is_normalized_and_aliases_are_supported() -> None:
    vendor, platform = validate_vendor_platform("cisco", "CISCO_IOSXE")
    assert (vendor, platform) == ("Cisco", "cisco_iosxe")

    vendor, platform = validate_vendor_platform("", "")
    assert (vendor, platform) == ("Custom", "custom")
    assert canonical_vendor("华三") == "H3C"
    assert canonical_vendor("新华三") == "H3C"


def test_mismatched_known_vendor_platform_is_rejected() -> None:
    with pytest.raises(ValueError, match="不支持平台"):
        validate_vendor_platform("Huawei", "cisco_nxos")


def test_raisecom_model_profile_uses_ros_platform() -> None:
    vendor, platform = validate_vendor_platform("瑞斯康达", "瑞斯康达 ROS")
    assert (vendor, platform) == ("Raisecom", "raisecom_ros")
