"""Vendor-first default CLI commands used by configuration backup fallbacks."""

from __future__ import annotations

from typing import Any

from core.platform_utils import normalize_device_platform
from services.platform_registry_service import PLATFORM_ACTION_COMMANDS


_VENDOR_PLATFORM_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cisco_ios", ("cisco", "思科")),
    ("huawei_vrp", ("huawei", "华为", "vrp")),
    ("h3c_comware", ("h3c", "华三", "comware")),
    ("juniper_junos", ("juniper", "junos")),
    ("arista_eos", ("arista", "eos")),
    ("ruijie_rgos", ("ruijie", "锐捷", "rgos")),
    ("zte_zxros", ("zte", "中兴", "zxros")),
    ("raisecom_ros", ("raisecom", "瑞斯康达")),
    ("dptech_ios", ("dptech", "迪普")),
    ("maipu", ("maipu", "迈普", "mypower")),
    ("fortinet_fortios", ("fortinet", "fortigate", "fortios")),
    ("hillstone_stoneos", ("hillstone", "stoneos", "山石")),
)

_PLATFORM_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cisco_ios", ("cisco", "nxos")),
    ("huawei_vrp", ("huawei", "vrp")),
    ("h3c_comware", ("h3c", "hp_comware", "comware")),
    ("juniper_junos", ("juniper", "junos")),
    ("arista_eos", ("arista", "eos")),
    ("ruijie_rgos", ("ruijie", "rgos")),
    ("zte_zxros", ("zte", "zxros")),
    ("raisecom_ros", ("raisecom",)),
    ("dptech_ios", ("dptech", "conplat")),
    ("maipu", ("maipu", "mypower")),
    ("fortinet_fortios", ("fortinet", "fortios", "fortigate")),
    ("hillstone_stoneos", ("hillstone_stoneos", "hillstone", "stoneos", "山石")),
)

CONFIG_BACKUP_DEFAULT_IDENTITY_TOKENS = tuple(dict.fromkeys(
    alias
    for _key, aliases in (_VENDOR_PLATFORM_ALIASES + _PLATFORM_ALIASES)
    for alias in aliases
))
CONFIG_BACKUP_DEFAULT_VENDOR_TOKENS = tuple(dict.fromkeys(
    alias
    for _key, aliases in _VENDOR_PLATFORM_ALIASES
    for alias in aliases
))
CONFIG_BACKUP_DEFAULT_PLATFORM_TOKENS = tuple(dict.fromkeys(
    alias
    for _key, aliases in _PLATFORM_ALIASES
    for alias in aliases
))

CONFIG_BACKUP_NETWORK_IDENTITY_TOKENS = (
    "cisco", "思科", "huawei", "华为", "h3c", "华三", "juniper", "junos",
    "山石",
    "arista", "ruijie", "锐捷", "zte", "中兴", "raisecom", "瑞斯康达",
    "dptech", "迪普", "maipu", "迈普", "fortinet", "fortigate", "fortios",
    "palo alto", "paloalto", "panos", "hillstone", "stoneos", "sangfor", "sangforos",
    "check point", "check_point", "sophos", "sonicwall", "watchguard", "fireware",
    "f5", "bigip", "a10", "acos", "barracuda", "venustech", "nsfocus", "topsec",
    "qi an xin", "qianxin", "zte", "中兴", "raisecom", "瑞斯康达", "dptech", "迪普",
    "maipu", "迈普", "dcn", "fiberhome", "烽火", "nokia", "aruba", "extreme",
    "ruckus", "mikrotik", "ubiquiti", "d-link", "dlink", "tp-link", "tplink", "ale",
    "dell", "brocade", "ciena", "alcatel", "allied telesis", "edgecore",
    "centec",
)


def _contains_alias(value: str, token: str) -> bool:
    """Match a vendor/platform alias as a token, not inside an unrelated word."""
    if any(ord(char) > 127 for char in token):
        return token in value
    import re

    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", value) is not None


def _find_platform(value: Any, aliases: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return None
    return next(
        (platform for platform, tokens in aliases if any(_contains_alias(normalized, token) for token in tokens)),
        None,
    )


def get_config_backup_platform(vendor: Any, platform: Any = "") -> str:
    """Resolve a CLI driver family that agrees with the explicit vendor.

    A recognized vendor wins over a conflicting or non-network platform value.
    Compatible platform variants are preserved where the shared normalizer
    knows them. Generic/empty vendors may still use their platform value.
    """
    normalized_vendor = str(vendor or "").strip().lower()
    vendor_key = _find_platform(vendor, _VENDOR_PLATFORM_ALIASES)
    platform_key = _find_platform(platform, _PLATFORM_ALIASES)
    if vendor_key:
        if platform_key == vendor_key:
            return normalize_device_platform(str(vendor or ""), str(platform or ""))
        return vendor_key
    if not normalized_vendor or normalized_vendor == "other":
        if platform_key:
            return normalize_device_platform("", str(platform or ""))
        return str(platform or "").strip()
    return str(platform or "").strip()


def get_default_config_backup_commands(vendor: Any, platform: Any = "") -> dict[str, str] | None:
    """Return running/startup commands selected by vendor, then platform fallback.

    A recognized vendor always wins if the inventory platform field conflicts.
    The platform is consulted only when the vendor field is blank or generic.
    """

    normalized_vendor = str(vendor or "").strip().lower()
    platform_key = _find_platform(vendor, _VENDOR_PLATFORM_ALIASES)
    if not platform_key:
        if normalized_vendor and normalized_vendor != "other":
            return None
        platform_key = _find_platform(platform, _PLATFORM_ALIASES)
    if not platform_key:
        return None

    if platform_key == "fortinet_fortios":
        return {"get_running_config": "show full-configuration", "get_startup_config": "show full-configuration"}
    actions = PLATFORM_ACTION_COMMANDS.get(platform_key) or {}
    running = str(actions.get("get_running_config") or "").strip()
    startup = str(actions.get("get_startup_config") or "").strip()
    if not running or not startup:
        return None
    return {"get_running_config": running, "get_startup_config": startup}


def is_network_device_for_config_backup(vendor: Any, platform: Any = "", asset_type: Any = "") -> bool:
    """Classify backup targets from either inventory identity field."""
    if str(asset_type or "").strip().lower() in {"server", "host", "physical_server"}:
        return False
    identity = f"{str(vendor or '').lower()} {str(platform or '').lower()}"
    return any(_contains_alias(identity, token) for token in CONFIG_BACKUP_NETWORK_IDENTITY_TOKENS)


def is_config_backup_candidate(
    vendor: Any,
    platform: Any = "",
    asset_type: Any = "",
    *,
    has_published_profile_action: bool = False,
    profile_vendor: Any = "",
    profile_platform_code: Any = "",
    profile_parser_platform: Any = "",
) -> bool:
    """Return whether a device has a verified default or published backup action."""
    if str(asset_type or "").strip().lower() in {"server", "host", "physical_server"}:
        return False
    if get_default_config_backup_commands(vendor, platform) is not None:
        return True
    return is_compatible_published_config_action(
        vendor,
        platform,
        profile_vendor,
        profile_platform_code,
        profile_parser_platform,
        has_published_profile_action=has_published_profile_action,
    )


def is_compatible_published_config_action(
    vendor: Any,
    platform: Any,
    profile_vendor: Any,
    profile_platform_code: Any,
    profile_parser_platform: Any,
    *,
    has_published_profile_action: bool,
) -> bool:
    """Require a published profile backup action to agree with inventory identity."""
    if not has_published_profile_action:
        return False
    from services.platform_registry_service import platform_vendors_match, platform_codes_match

    if not platform_vendors_match(vendor, profile_vendor):
        return False
    if not str(platform or "").strip():
        return False
    return platform_codes_match(platform, profile_platform_code, profile_parser_platform)


__all__ = [
    "CONFIG_BACKUP_NETWORK_IDENTITY_TOKENS",
    "CONFIG_BACKUP_DEFAULT_IDENTITY_TOKENS",
    "CONFIG_BACKUP_DEFAULT_VENDOR_TOKENS",
    "CONFIG_BACKUP_DEFAULT_PLATFORM_TOKENS",
    "get_config_backup_platform",
    "get_default_config_backup_commands",
    "is_config_backup_candidate",
    "is_compatible_published_config_action",
    "is_network_device_for_config_backup",
]
