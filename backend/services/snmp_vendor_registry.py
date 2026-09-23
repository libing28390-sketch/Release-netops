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
        "思科": "Cisco", "华为": "Huawei", "华三": "H3C", "锐捷": "Ruijie", "中兴": "ZTE",
        "迈普": "Maipu", "迪普": "DPtech", "神州数码": "DCN", "飞塔": "Fortinet", "飞腾": "Fortinet",
        "山石": "Hillstone", "深信服": "Sangfor", "检查点": "Check Point", "帕洛阿尔托": "Palo Alto",
    }
    return aliases.get(raw, raw)


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
        return {"vendor": canonical, "mode": "standard_only", "supported": False, "reason": "identity and IF-MIB discovery only; vendor OID adapter is not approved"}
    return {"vendor": canonical, "mode": "unknown", "supported": False, "reason": "vendor is not in the asset catalog"}
