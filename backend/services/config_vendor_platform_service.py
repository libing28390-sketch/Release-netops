"""Canonical vendor/platform relationships for configuration templates."""

from __future__ import annotations


VENDOR_PLATFORM_CATALOG: dict[str, tuple[str, ...]] = {
    "Cisco": (
        "cisco_ios", "cisco_iosxe", "cisco_xe", "cisco_nxos",
        "cisco_iosxr", "cisco_xr", "cisco_asa",
    ),
    "Huawei": (
        "huawei_vrp", "huawei_vrpv8", "huawei_smartax", "huawei_usg",
    ),
    "H3C": ("hp_comware", "h3c_comware", "h3c_comware9"),
    "Arista": ("arista_eos",),
    "Juniper": ("juniper_junos",),
    "Ruijie": ("ruijie_rgos", "ruijie_os"),
    "ZTE": ("zte_zxros",),
    "Maipu": ("maipu", "maipu_network", "maipu_mypower"),
    "DPtech": ("dptech_ios", "dptech_conplat", "dptech_conplat_fw"),
    "Fortinet": ("fortinet",),
    "Palo Alto": ("paloalto_panos",),
    "Hillstone": ("hillstone_stoneos",),
    "FiberHome": ("fiberhome_fengine",),
    "Custom": ("custom",),
}

# A platform is the command dialect/OS family.  Hardware model and series are
# deliberately kept as compatibility profiles so that one parser/template
# family can cover several appliances without pretending that every model is a
# new platform.  Patterns are intentionally conservative: they are hints for
# matching and pre-checks, never permission to skip device-side validation.
PLATFORM_PROFILES: dict[str, tuple[dict[str, object], ...]] = {
    "ruijie_rgos": (
        {"series": "RG-S switching", "model_patterns": (r"^RG-(?:S|CS|NBS)",), "roles": ("switch",)},
        {"series": "RG-R / RSR routing", "model_patterns": (r"^(?:RG-R|RSR)",), "roles": ("router",)},
        {"series": "RG-EG gateway", "model_patterns": (r"^RG-EG",), "roles": ("router", "firewall")},
    ),
    "zte_zxros": (
        {"series": "ZXR10 5900/5960", "model_patterns": (r"^(?:ZXR10\s*)?(?:5900|5960)",), "roles": ("switch",)},
        {"series": "ZXR10 M6000", "model_patterns": (r"^(?:ZXR10\s*)?M6000",), "roles": ("router",)},
        {"series": "ZXR10 9900", "model_patterns": (r"^(?:ZXR10\s*)?9900",), "roles": ("switch",)},
        {"series": "ZXCTN 6700", "model_patterns": (r"^ZXCTN\s*6700",), "roles": ("router", "switch")},
    ),
    "maipu": (
        {"series": "MyPower access/aggregation", "model_patterns": (r"^(?:S|NSS|S33|S35|S58|S59)",), "roles": ("switch",)},
        {"series": "MyPower router", "model_patterns": (r"^(?:MP|MyPower|MP\s*)",), "roles": ("router",)},
        {"series": "MPSec firewall", "model_patterns": (r"^(?:MSG|MPSec|IFW)",), "roles": ("firewall",)},
    ),
    "dptech_conplat": (
        {"series": "LSW switching", "model_patterns": (r"^LSW",), "roles": ("switch",)},
        {"series": "DPtech routing platform", "model_patterns": (r"^(?:X|MSR|XR)",), "roles": ("router",)},
    ),
    "dptech_conplat_fw": (
        {"series": "FW firewall", "model_patterns": (r"^(?:FW|FW1000|FW2000)",), "roles": ("firewall",)},
        {"series": "UAG/security gateway", "model_patterns": (r"^(?:UAG|FW)",), "roles": ("firewall", "load_balancer")},
    ),
}

_VENDOR_ALIASES = {
    "cisco": "Cisco",
    "思科": "Cisco",
    "huawei": "Huawei",
    "华为": "Huawei",
    "h3c": "H3C",
    "hp": "H3C",
    "华三": "H3C",
    "arista": "Arista",
    "juniper": "Juniper",
    "ruijie": "Ruijie",
    "锐捷": "Ruijie",
    "zte": "ZTE",
    "中兴": "ZTE",
    "maipu": "Maipu",
    "迈普": "Maipu",
    "dptech": "DPtech",
    "迪普": "DPtech",
    "fortinet": "Fortinet",
    "palo alto": "Palo Alto",
    "paloalto": "Palo Alto",
    "hillstone": "Hillstone",
    "fiberhome": "FiberHome",
    "烽火": "FiberHome",
    "custom": "Custom",
    "思科": "Cisco",
    "华为": "Huawei",
    "华三": "H3C",
    "锐捷": "Ruijie",
    "中兴": "ZTE",
    "迈普": "Maipu",
    "迪普": "DPtech",
    "烽火": "FiberHome",
}

_PLATFORM_ALIASES = {
    "cisco ios xe": "cisco_iosxe",
    "ios xe": "cisco_iosxe",
    "huawei vrp": "huawei_vrp",
    "huawei vrpv8": "huawei_vrpv8",
    "h3c comware": "h3c_comware",
    "ruijie os": "ruijie_rgos",
    "rgos": "ruijie_rgos",
    "zte zxros": "zte_zxros",
    "中兴 zxros": "zte_zxros",
    "mypower": "maipu",
    "dptech": "dptech_conplat",
    "dptech conplat": "dptech_conplat",
    "dptech conplat firewall": "dptech_conplat_fw",
}

_CANONICAL_PLATFORM = {
    "ruijie_os": "ruijie_rgos",
    "h3c_comware9": "h3c_comware",
    "hp_comware": "h3c_comware",
    "maipu_network": "maipu",
    "maipu_mypower": "maipu",
    "dptech": "dptech_conplat",
    "dptech_ios": "dptech_conplat",
}


def canonical_vendor(vendor: str) -> str:
    value = str(vendor or "").strip()
    return _VENDOR_ALIASES.get(value.lower(), value or "Custom")


def allowed_platforms(vendor: str) -> tuple[str, ...]:
    return VENDOR_PLATFORM_CATALOG.get(canonical_vendor(vendor), ())


def validate_vendor_platform(vendor: str, platform: str) -> tuple[str, str]:
    """Return canonical values or raise for a known vendor/platform mismatch."""
    canonical = canonical_vendor(vendor)
    raw_platform = str(platform or "").strip()
    selected_input = _PLATFORM_ALIASES.get(raw_platform.lower(), raw_platform)
    options = allowed_platforms(canonical)
    if not options:
        return canonical, selected_input
    selected = selected_input or options[0]
    if selected.lower() not in {option.lower() for option in options}:
        supported = ", ".join(options)
        raise ValueError(f"厂商 {canonical} 不支持平台 {selected}；可选平台：{supported}")
    return canonical, next(option for option in options if option.lower() == selected.lower())


def platform_profiles(vendor: str = "", platform: str = "") -> list[dict[str, object]]:
    """Return model/series hints for a canonical vendor/platform pair."""
    canonical_vendor_name, canonical_platform = validate_vendor_platform(vendor, platform)
    del canonical_vendor_name
    profile_platform = _CANONICAL_PLATFORM.get(canonical_platform, canonical_platform)
    return [dict(profile) for profile in PLATFORM_PROFILES.get(profile_platform, ())]


def match_platform_profile(vendor: str, platform: str, model: str = "") -> dict[str, object] | None:
    """Match a device model to a profile without changing its platform value."""
    profiles = platform_profiles(vendor, platform)
    value = str(model or "").strip()
    if not value:
        return None
    import re

    for profile in profiles:
        if any(re.search(str(pattern), value, re.I) for pattern in profile.get("model_patterns", ())):
            return profile
    return None
