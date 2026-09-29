"""Canonical asset-vendor coverage for SNMP discovery.

This registry separates vendor identity coverage from metric adapter coverage so
an asset can be recognized safely even when no vendor-specific OID source has
been approved yet. ``standard_only`` means IF-MIB/system discovery is allowed;
the compiler must not publish a guessed vendor module.
"""

from __future__ import annotations

from typing import Any


ASSET_NETWORK_VENDORS = (
    "Cisco", "Huawei", "H3C", "Arista", "Juniper", "Ruijie", "ZTE", "Raisecom", "Maipu",
    "DPtech", "DCN", "FiberHome", "Nokia", "Aruba", "Extreme Networks", "Ruckus", "MikroTik",
    "Ubiquiti", "D-Link", "TP-Link", "Dell", "Brocade", "Ciena", "Alcatel-Lucent Enterprise",
    "Allied Telesis", "Edgecore",
)

ASSET_SECURITY_VENDORS = (
    "Fortinet", "Palo Alto", "Hillstone", "Sangfor", "Check Point", "Sophos", "SonicWall",
    "WatchGuard", "F5", "A10 Networks", "Barracuda", "Venustech", "NSFOCUS", "Topsec", "Qi An Xin",
)

# Concrete platform codes from VENDOR_PLATFORMS in
# src/pages/AssetManagement/constants.ts. Platform is a stronger hint than an
# OS family label for OEM/rebranded devices (for example Edgecore OcNOS).
ASSET_PLATFORM_VENDOR_OVERRIDES = {
    "cisco_ios": "Cisco", "cisco_nxos": "Cisco", "cisco_xe": "Cisco",
    "cisco_iosxr": "Cisco", "cisco_asa": "Cisco",
    "huawei_vrp": "Huawei", "huawei_vrpv8": "Huawei",
    "huawei_smartax": "Huawei", "huawei_usg": "Huawei",
    "h3c_comware": "H3C", "arista_eos": "Arista",
    "juniper_junos": "Juniper", "juniper_srx": "Juniper",
    "ruijie_rgos": "Ruijie", "zte_zxros": "ZTE", "raisecom_ros": "Raisecom",
    "maipu": "Maipu", "dptech_conplat": "DPtech", "dptech_conplat_fw": "DPtech",
    "dcn_network": "DCN", "fiberhome_fengine": "FiberHome", "nokia_sros": "Nokia",
    "aruba_aos_cx": "Aruba", "aruba_aos": "Aruba",
    "extreme_exos": "Extreme Networks", "extreme_voss": "Extreme Networks",
    "ruckus_fastiron": "Ruckus", "mikrotik_routeros": "MikroTik",
    "ubiquiti_edgeswitch": "Ubiquiti", "ubiquiti_unifi": "Ubiquiti",
    "dlink_network": "D-Link", "tplink_omada": "TP-Link", "dell_os10": "Dell",
    "brocade_fastiron": "Brocade", "ciena_saos": "Ciena",
    "ale_aos": "Alcatel-Lucent Enterprise", "allied_telesis_awplus": "Allied Telesis",
    "edgecore_ocnos": "Edgecore",
    "fortinet": "Fortinet", "paloalto_panos": "Palo Alto",
    "hillstone_stoneos": "Hillstone", "sangfor_ngaf": "Sangfor",
    "check_point_gaia": "Check Point", "sophos_firewall": "Sophos",
    "sonicwall_sonicos": "SonicWall", "watchguard_fireware": "WatchGuard",
    "f5_bigip": "F5", "a10_acos": "A10 Networks",
    "barracuda_cloudgen": "Barracuda", "venustech_usg": "Venustech",
    "nsfocus_firewall": "NSFOCUS", "topsec_firewall": "Topsec",
    "qianxin_firewall": "Qi An Xin",
}

# This list mirrors NETWORK_VENDOR_NAMES and SECURITY_VENDOR_NAMES in
# src/pages/AssetManagement/constants.ts. LibreNMS detects OS families while
# Nexora assets store the catalog's business-vendor names.
# Keep the bridge here so rule import, identity resolution, and adapters use
# the exact canonical names accepted by the asset system.
LIBRENMS_OS_VENDOR_OVERRIDES = {
    # Cisco IOS family and derived platforms
    "ios": "Cisco", "iosxe": "Cisco", "iosxr": "Cisco", "nxos": "Cisco",
    "cisco": "Cisco", "ciscosb": "Cisco", "ciscoasa": "Cisco", "ciscowlc": "Cisco",
    "aireos": "Cisco", "ciscowap": "Cisco", "catalystcenter": "Cisco",
    # Huawei and H3C expose different OS families despite shared OEM history.
    "vrp": "Huawei", "huawei": "Huawei", "huawei-wlc": "Huawei", "huaweiolt": "Huawei",
    "comware": "H3C", "h3c": "H3C", "h3c-msr": "H3C",
    "arista": "Arista", "eos": "Arista",
    "junos": "Juniper", "junos-evo": "Juniper",
    "ruijie": "Ruijie", "rgos": "Ruijie",
    "zxros": "ZTE", "zte": "ZTE", "zxr10": "ZTE",
    "raisecom": "Raisecom", "raisecom-ros": "Raisecom",
    "maipu": "Maipu", "dptech": "DPtech", "dcn": "DCN",
    "fiberhome": "FiberHome", "nokia": "Nokia", "timos": "Nokia", "sros": "Nokia",
    "arubaos": "Aruba", "arubaos-cx": "Aruba", "aruba-instant": "Aruba",
    "procurve": "Aruba", "extreme": "Extreme Networks", "exos": "Extreme Networks",
    "xos": "Extreme Networks", "ruckus": "Ruckus", "smartzone": "Ruckus",
    "routeros": "MikroTik", "swos": "MikroTik", "mikrotik": "MikroTik",
    "airos": "Ubiquiti", "unifi": "Ubiquiti", "ubiquiti": "Ubiquiti",
    "edgeswitch": "Ubiquiti", "edgeos": "Ubiquiti",
    "dlink": "D-Link", "dlink-dgs1250": "D-Link", "dlinkap": "D-Link",
    "tplink": "TP-Link", "jetstream": "TP-Link",
    "dell": "Dell", "dell-os10": "Dell", "dell-sonic": "Dell",
    "brocade": "Brocade", "fastiron": "Brocade", "icx": "Brocade",
    "ciena-saos": "Ciena", "ciena-sds": "Ciena", "ciena-rls": "Ciena",
    "ciena-waveserver": "Ciena", "saos": "Ciena",
    "alcatel": "Alcatel-Lucent Enterprise", "omnipcx": "Alcatel-Lucent Enterprise",
    "aos": "Alcatel-Lucent Enterprise", "aos6": "Alcatel-Lucent Enterprise",
    "aos7": "Alcatel-Lucent Enterprise", "stellar": "Alcatel-Lucent Enterprise",
    "ale": "Alcatel-Lucent Enterprise",
    "allied": "Allied Telesis", "allied-tq": "Allied Telesis", "awplus": "Allied Telesis",
    "edgecore": "Edgecore", "edgecos": "Edgecore",
    "arista_eos": "Arista", "dcn-software": "DCN", "fiberhome-switch": "FiberHome",
    "nokia-1830": "Nokia", "nokia-isam": "Nokia",
    "extremeware": "Extreme Networks", "fs-ruijie": "Ruijie",
    # Security and application delivery vendors from the asset catalog.
    "fortios": "Fortinet", "fortigate": "Fortinet", "panos": "Palo Alto",
    "paloalto": "Palo Alto", "hillstone": "Hillstone", "sangfor": "Sangfor",
    "checkpoint": "Check Point", "check-point": "Check Point", "sophos": "Sophos",
    "sonicwall": "SonicWall", "watchguard": "WatchGuard", "f5": "F5",
    "bigip": "F5", "a10": "A10 Networks", "a10networks": "A10 Networks",
    "barracuda": "Barracuda", "venustech": "Venustech", "nsfocus": "NSFOCUS",
    "topsec": "Topsec", "qianxin": "Qi An Xin",
}

# Enterprise roots are identity evidence only. Hardware metrics still come
# from an applicable LibreNMS rule, standard MIB, or reviewed Nexora adapter.
ASSET_VENDOR_ENTERPRISE_PREFIXES = {
    "1.3.6.1.4.1.9.": "Cisco",
    "1.3.6.1.4.1.2011.": "Huawei",
    "1.3.6.1.4.1.25506.": "H3C",
    "1.3.6.1.4.1.4881.": "Ruijie",
    "1.3.6.1.4.1.2636.": "Juniper",
    "1.3.6.1.4.1.12356.": "Fortinet",
    "1.3.6.1.4.1.3902.": "ZTE",
    "1.3.6.1.4.1.5651.": "Maipu",
    "1.3.6.1.4.1.31648.": "DPtech",
    "1.3.6.1.4.1.35047.": "Sangfor",
    "1.3.6.1.4.1.6339.": "DCN",
    "1.3.6.1.4.1.14823.": "Aruba",
    "1.3.6.1.4.1.25053.": "Ruckus",
    "1.3.6.1.4.1.3807.": "FiberHome",
    "1.3.6.1.4.1.11408.": "FiberHome",
    "1.3.6.1.4.1.7483.": "Nokia",
    "1.3.6.1.4.1.6527.": "Nokia",
    "1.3.6.1.4.1.1916.": "Extreme Networks",
    "1.3.6.1.4.1.14988.": "MikroTik",
    "1.3.6.1.4.1.41112.": "Ubiquiti",
    "1.3.6.1.4.1.171.": "D-Link",
    "1.3.6.1.4.1.11863.": "TP-Link",
    "1.3.6.1.4.1.16972.": "TP-Link",
    "1.3.6.1.4.1.674.": "Dell",
    "1.3.6.1.4.1.1588.": "Brocade",
    "1.3.6.1.4.1.562.": "Ciena",
    "1.3.6.1.4.1.6486.": "Alcatel-Lucent Enterprise",
    "1.3.6.1.4.1.207.": "Allied Telesis",
    "1.3.6.1.4.1.30065.": "Arista",
    "1.3.6.1.4.1.8886.": "Raisecom",
    "1.3.6.1.4.1.2620.": "Check Point",
    "1.3.6.1.4.1.2604.": "Sophos",
    "1.3.6.1.4.1.8741.": "SonicWall",
    "1.3.6.1.4.1.3097.": "WatchGuard",
    "1.3.6.1.4.1.3375.": "F5",
    "1.3.6.1.4.1.12276.": "F5",
    "1.3.6.1.4.1.22610.": "A10 Networks",
    "1.3.6.1.4.1.20632.": "Barracuda",
    "1.3.6.1.4.1.10704.": "Barracuda",
    "1.3.6.1.4.1.28557.": "Hillstone",
}

# ``catalog`` is populated by monitoring_oid_catalog; the explicit entries here
# document the adapters that do not come from that catalog.
EXPLICIT_ADAPTER_MODES = {
    "Cisco": "specialized",
    "Arista": "platform_map",
    "Raisecom": "platform_map",
}


def normalize_asset_vendor(value: Any) -> str:
    raw = " ".join(str(value or "").strip().split())
    aliases = {
        "思科": "Cisco", "华为": "Huawei", "华三": "H3C", "阿里斯塔": "Arista",
        "瞻博": "Juniper", "锐捷": "Ruijie", "中兴": "ZTE",
        "瑞斯康达": "Raisecom", "瑞斯康达通信": "Raisecom",
        "迈普": "Maipu", "迪普": "DPtech", "神州数码": "DCN", "飞塔": "Fortinet",
        "山石": "Hillstone", "深信服": "Sangfor", "检查点": "Check Point", "帕洛阿尔托": "Palo Alto",
        "烽火": "FiberHome", "诺基亚": "Nokia", "极进": "Extreme Networks", "友讯": "D-Link",
        "普联": "TP-Link", "戴尔": "Dell", "博科": "Brocade", "思亚": "Ciena",
        "阿尔卡特": "Alcatel-Lucent Enterprise", "安奈特": "Allied Telesis", "智邦": "Edgecore",
        "优比快": "Ubiquiti", "检查点科技": "Check Point", "奇安信": "Qi An Xin",
        "绿盟": "NSFOCUS", "天融信": "Topsec", "启明星辰": "Venustech",
    }
    if raw in aliases:
        return aliases[raw]
    folded = raw.casefold()
    normalized_aliases = {
        "cisco": "Cisco", "huawei": "Huawei", "h3c": "H3C", "comware": "H3C",
        "arista": "Arista", "juniper": "Juniper", "ruijie": "Ruijie", "zte": "ZTE",
        "raisecom": "Raisecom", "maipu": "Maipu", "dptech": "DPtech", "dcn": "DCN",
        "fiberhome": "FiberHome", "nokia": "Nokia", "aruba": "Aruba",
        "extreme networks": "Extreme Networks", "extreme": "Extreme Networks",
        "ruckus": "Ruckus", "mikrotik": "MikroTik", "ubiquiti": "Ubiquiti",
        "d-link": "D-Link", "dlink": "D-Link", "tp-link": "TP-Link", "tplink": "TP-Link",
        "dell": "Dell", "brocade": "Brocade", "ciena": "Ciena",
        "alcatel": "Alcatel-Lucent Enterprise", "alcatel-lucent": "Alcatel-Lucent Enterprise",
        "alcatel-lucent enterprise": "Alcatel-Lucent Enterprise", "allied telesis": "Allied Telesis",
        "edgecore": "Edgecore", "fortinet": "Fortinet", "palo alto": "Palo Alto",
        "hillstone": "Hillstone", "sangfor": "Sangfor", "check point": "Check Point",
        "checkpoint": "Check Point", "sophos": "Sophos", "sonicwall": "SonicWall",
        "watchguard": "WatchGuard", "f5": "F5", "a10 networks": "A10 Networks",
        "a10": "A10 Networks", "barracuda": "Barracuda", "venustech": "Venustech",
        "nsfocus": "NSFOCUS", "topsec": "Topsec", "qi an xin": "Qi An Xin",
        "qianxin": "Qi An Xin",
    }
    return normalized_aliases.get(folded, raw)


def vendor_from_asset_platform(value: Any) -> str:
    """Return the catalog vendor for an exact Asset Management platform code."""
    token = " ".join(str(value or "").strip().casefold().split())
    return ASSET_PLATFORM_VENDOR_OVERRIDES.get(token, "")


def infer_librenms_vendor(os_key: Any, detection: Any) -> str:
    """Map an upstream OS rule to an asset vendor using key, label, then OID evidence."""
    key = " ".join(str(os_key or "").strip().casefold().split())
    override = LIBRENMS_OS_VENDOR_OVERRIDES.get(key)
    if override:
        return override

    text_parts: list[str] = [key]
    detection_group = ""
    if isinstance(detection, dict):
        for field in ("group", "text", "os", "vendor"):
            value = detection.get(field)
            if isinstance(value, (str, int, float)):
                text_parts.append(str(value))
                if field == "group":
                    detection_group = str(value)
        oid_values: list[str] = []

        def collect_oids(value: Any, field: str = "") -> None:
            if isinstance(value, dict):
                for child_key, child in value.items():
                    folded = str(child_key).casefold()
                    if folded in {"sysobjectid", "sysobjectid_regex"}:
                        collect_oids(child, folded)
                    elif folded in {"prefix", "value", "values", "any"} and field == "sysobjectid":
                        collect_oids(child, field)
                    elif field == "sysobjectid":
                        collect_oids(child, field)
                    elif isinstance(child, (dict, list, tuple)):
                        collect_oids(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    collect_oids(child, field)
            elif field == "sysobjectid" and value is not None:
                oid_values.append(str(value))

        collect_oids(detection)

    registered = set((*ASSET_NETWORK_VENDORS, *ASSET_SECURITY_VENDORS))
    group_vendor = normalize_asset_vendor(detection_group)
    if group_vendor in registered:
        return group_vendor

    searchable = " | ".join(text_parts).casefold()
    aliases = {
        "cisco": "Cisco", "思科": "Cisco", "huawei": "Huawei", "华为": "Huawei",
        "comware": "H3C", "h3c": "H3C", "华三": "H3C", "arista": "Arista",
        "juniper": "Juniper", "ruijie": "Ruijie", "锐捷": "Ruijie", "zte": "ZTE",
        "中兴": "ZTE", "raisecom": "Raisecom", "maipu": "Maipu", "dptech": "DPtech",
        "dcn": "DCN", "fiberhome": "FiberHome", "nokia": "Nokia", "aruba": "Aruba",
        "extreme": "Extreme Networks", "ruckus": "Ruckus", "mikrotik": "MikroTik",
        "ubiquiti": "Ubiquiti", "d-link": "D-Link", "dlink": "D-Link", "tp-link": "TP-Link",
        "tplink": "TP-Link", "dell": "Dell", "brocade": "Brocade", "ciena": "Ciena",
        "alcatel-lucent enterprise": "Alcatel-Lucent Enterprise", "alcatel omnipcx": "Alcatel-Lucent Enterprise",
        "allied telesis": "Allied Telesis",
        "edgecore": "Edgecore", "fortinet": "Fortinet", "fortigate": "Fortinet",
        "palo alto": "Palo Alto", "pan-os": "Palo Alto", "hillstone": "Hillstone",
        "sangfor": "Sangfor", "check point": "Check Point", "checkpoint": "Check Point",
        "sophos": "Sophos", "sonicwall": "SonicWall", "watchguard": "WatchGuard",
        "big-ip": "F5", "f5": "F5", "a10": "A10 Networks", "barracuda": "Barracuda",
        "venustech": "Venustech", "nsfocus": "NSFOCUS", "topsec": "Topsec",
        "qianxin": "Qi An Xin", "奇安信": "Qi An Xin", "绿盟": "NSFOCUS",
    }
    for alias in sorted(aliases, key=len, reverse=True):
        if alias in searchable:
            return aliases[alias]

    # Enterprise roots are a weak fallback only after the OS group and
    # human-readable label have had a chance to disambiguate OEM products.
    oid_vendors: set[str] = set()
    for raw_oid in oid_values if isinstance(detection, dict) else ():
        normalized_oid = raw_oid.strip().strip(".")
        for prefix, vendor in ASSET_VENDOR_ENTERPRISE_PREFIXES.items():
            root = prefix.rstrip(".")
            if normalized_oid == root or normalized_oid.startswith(prefix):
                oid_vendors.add(vendor)
    if len(oid_vendors) == 1:
        return next(iter(oid_vendors))
    return ""


def adapter_descriptor(vendor: Any, *, catalog_available: bool = False, static_available: bool = False) -> dict[str, Any]:
    canonical = normalize_asset_vendor(vendor)
    if canonical in EXPLICIT_ADAPTER_MODES:
        mode = EXPLICIT_ADAPTER_MODES[canonical]
        return {"vendor": canonical, "mode": mode, "supported": True, "reason": "explicit vendor discovery adapter"}
    if catalog_available:
        return {"vendor": canonical, "mode": "catalog", "supported": True, "reason": "built-in OID catalog variant"}
    if static_available:
        return {"vendor": canonical, "mode": "platform_map", "supported": True, "reason": "platform OID map"}
    if canonical in ASSET_NETWORK_VENDORS or canonical in ASSET_SECURITY_VENDORS:
        return {
            "vendor": canonical,
            "mode": "standard_only",
            "supported": False,
            "generic_hardware_probe": "HOST-RESOURCES-MIB/ENTITY-SENSOR-MIB",
            "reason": "no vendor-specific OID adapter is approved; the generic standard-MIB hardware probe still runs",
        }
    return {"vendor": canonical, "mode": "unknown", "supported": False, "reason": "vendor is not in the asset catalog"}
