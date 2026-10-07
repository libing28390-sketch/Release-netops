"""Resolve SNMP vendor and platform identity for Nexora device records.

Hardware discovery and polling are performed by the bound LibreNMS runtime.
This module only classifies device identity from system fields and rules.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from services.snmp_vendor_registry import (
    ASSET_NETWORK_VENDORS,
    ASSET_SECURITY_VENDORS,
    ASSET_VENDOR_ENTERPRISE_PREFIXES,
    normalize_asset_vendor,
    vendor_from_asset_platform,
)
from services.librenms_rule_service import ensure_rules_available, identity_snmp_probe_plan, resolve_rule

SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
_OBSERVED_VENDOR_PREFIXES = ASSET_VENDOR_ENTERPRISE_PREFIXES


def _text(value: Any, limit: int = 512) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def normalize_oid(value: Any) -> str:
    raw = _text(value, 256).strip().strip(".")
    raw = re.sub(r"^(?:OID\s*:\s*|iso\.)", "", raw, flags=re.IGNORECASE)
    if "::" in raw:
        raw = raw.rsplit("::", 1)[-1]
    raw = re.sub(r"^enterprises\.", "1.3.6.1.4.1.", raw, flags=re.IGNORECASE)
    if not raw or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", raw):
        return ""
    return "." + raw


def normalize_vendor(value: Any) -> str:
    raw = _text(value, 128)
    canonical = normalize_asset_vendor(raw)
    if canonical in set((*ASSET_NETWORK_VENDORS, *ASSET_SECURITY_VENDORS)):
        return canonical
    token = raw.casefold()
    if token in {"alcatel lucent enterprise", "alcatel-lucent enterprise", "ale"}:
        return "Alcatel-Lucent Enterprise"
    if token in {"cisco", "思科"} or "cisco" in token:
        return "Cisco"
    if token in {"huawei", "华为"} or "huawei" in token:
        return "Huawei"
    if "aruba" in token or "procurve" in token:
        return "Aruba"
    if token in {"h3c", "华三", "hpe", "hp"} or "comware" in token:
        return "H3C"
    registered_vendors = (*ASSET_NETWORK_VENDORS, *ASSET_SECURITY_VENDORS)
    for registered_vendor in sorted(registered_vendors, key=len, reverse=True):
        if registered_vendor.casefold() in token:
            return registered_vendor
    aliases = (
        (("juniper", "瞻博"), "Juniper"),
        (("fiberhome", "烽火", "fiber home"), "FiberHome"),
        (("nokia", "诺基亚"), "Nokia"),
        (("extreme", "极进"), "Extreme Networks"),
        (("mikrotik", "mikro tik"), "MikroTik"),
        (("ubiquiti", "优比快", "ubnt"), "Ubiquiti"),
        (("d-link", "dlink", "友讯"), "D-Link"),
        (("tp-link", "tplink", "普联"), "TP-Link"),
        (("dell", "戴尔"), "Dell"),
        (("brocade", "博科"), "Brocade"),
        (("ciena", "思亚"), "Ciena"),
        (("alcatel", "阿尔卡特"), "Alcatel-Lucent Enterprise"),
        (("启明星辰", "venustech"), "Venustech"),
        (("绿盟", "nsfocus"), "NSFOCUS"),
        (("天融信", "topsec"), "Topsec"),
        (("奇安信", "qianxin"), "Qi An Xin"),
        (("allied", "allied telesis", "安奈特"), "Allied Telesis"),
        (("edgecore", "edge core", "智邦"), "Edgecore"),
        (("arista", "阿里斯塔"), "Arista"),
        (("raisecom", "瑞斯康达", "瑞斯康达通信"), "Raisecom"),
        (("迈普", "maipu"), "Maipu"),
        (("迪普", "dptech"), "DPtech"),
        (("神州数码", "dcn"), "DCN"),
        (("锐捷", "ruijie"), "Ruijie"),
        (("中兴", "zte"), "ZTE"),
        (("checkpoint", "check point", "检查点"), "Check Point"),
        (("paloalto", "palo alto", "palo alto networks", "帕洛阿尔托"), "Palo Alto"),
        (("sonicwall", "sonic wall"), "SonicWall"),
        (("watchguard", "watch guard"), "WatchGuard"),
        (("a10 networks", "a10网络", "a10"), "A10 Networks"),
        (("f5 networks", "f5 big-ip", "big-ip", "bigip", "f5"), "F5"),
        (("barracuda networks", "barracuda"), "Barracuda"),
        (("sophos xg", "sophos firewall", "sophos"), "Sophos"),
    )
    for needles, canonical in aliases:
        if any(needle in token for needle in needles):
            return canonical
    return _text(value, 128)


def _version_from_descr(descr: str) -> str:
    match = re.search(r"\bversion\s+([\w.()\-/]+)", descr, re.IGNORECASE)
    return match.group(1) if match else ""


def _model_from_descr(descr: str) -> str:
    for pattern in (
        r"\b(WS-C\d[\w-]*)\b",
        r"\b(C\d{3,4}[\w-]*)\b",
        r"\b(Catalyst\s+\d{3,4})\b",
        r"\b(Nexus\s+[\w-]+)\b",
    ):
        match = re.search(pattern, descr, re.IGNORECASE)
        if match:
            return _text(match.group(1), 256)
    return ""


def classify_identity(
    *,
    vendor: Any = "",
    platform: Any = "",
    model: Any = "",
    version: Any = "",
    sys_object_id: Any = "",
    sys_descr: Any = "",
    sys_name: Any = "",
) -> dict[str, Any]:
    """Classify a device using observed SNMP identity and asset metadata."""

    observed_oid = normalize_oid(sys_object_id)
    descr = _text(sys_descr, 2048)
    declared_vendor = normalize_vendor(vendor) or vendor_from_asset_platform(platform)
    observed_vendor = ""
    if observed_oid:
        observed_vendor = next(
            (name for prefix, name in _OBSERVED_VENDOR_PREFIXES.items() if observed_oid.startswith("." + prefix)),
            "unknown",
        )
    if not observed_vendor and "cisco" in descr.casefold():
        observed_vendor = "Cisco"
    effective_vendor = declared_vendor if observed_vendor == "unknown" and declared_vendor else observed_vendor or declared_vendor
    version_value = _text(version, 128) or _version_from_descr(descr)
    platform_text = _text(platform, 128).casefold()
    model_value = _text(model, 256) or _model_from_descr(descr)
    lower_descr = descr.casefold()

    if declared_vendor == "Cisco" and observed_vendor == "unknown":
        return {
            "status": "conflict",
            "vendor": declared_vendor,
            "platform": _text(platform, 128),
            "model": model_value,
            "software_version": version_value,
            "sys_object_id": observed_oid,
            "sys_descr": descr,
            "sys_name": _text(sys_name, 256),
            "reason": "asset is marked Cisco but sysObjectID belongs to another vendor",
        }

    if not effective_vendor:
        return {
            "status": "identity_missing",
            "vendor": "",
            "platform": _text(platform, 128),
            "model": model_value,
            "software_version": version_value,
            "sys_object_id": observed_oid,
            "sys_descr": descr,
            "sys_name": _text(sys_name, 256),
            "reason": "vendor identity is missing from asset and SNMP system data",
        }

    if effective_vendor not in set(_OBSERVED_VENDOR_PREFIXES.values()) and effective_vendor != declared_vendor:
        return {
            "status": "unsupported_vendor" if effective_vendor else "identity_missing",
            "vendor": effective_vendor,
            "platform": _text(platform, 128),
            "model": model_value,
            "software_version": version_value,
            "sys_object_id": observed_oid,
            "sys_descr": descr,
            "sys_name": _text(sys_name, 256),
            "reason": "no vendor OID discovery adapter is enabled for this asset vendor",
        }

    conflict = bool(observed_vendor and observed_vendor not in {"unknown", ""} and declared_vendor and declared_vendor != observed_vendor)
    if effective_vendor != "Cisco":
        family = _text(platform, 128) or effective_vendor.casefold()
    elif "ios xr" in lower_descr or "ios-xr" in lower_descr or "iosxr" in lower_descr:
        family = "cisco_iosxr"
    elif "nx-os" in lower_descr or "nxos" in lower_descr or "nexus" in lower_descr or "nxos" in platform_text:
        family = "cisco_nxos"
    elif "ios xe" in lower_descr or "ios-xe" in lower_descr or "iosxe" in lower_descr or "cisco_xe" in platform_text:
        family = "cisco_iosxe"
    else:
        family = "cisco_ios"

    return {
        "status": "conflict" if conflict else "identified",
        "vendor": effective_vendor,
        "platform": family,
        "model": model_value,
        "software_version": version_value,
        "sys_object_id": observed_oid,
        "sys_descr": descr,
        "sys_name": _text(sys_name, 256),
        "reason": (
            f"asset vendor conflicts with observed {observed_vendor} identity"
            if conflict
            else "vendor identity matched; vendor catalog discovery will select the metric tables"
            if effective_vendor != "Cisco"
            else "Cisco identity matched"
        ),
    }


def _vendor_from_sys_descr(sys_descr: Any) -> str:
    """Return a canonical asset vendor observed in sysDescr, if any."""
    text = _text(sys_descr, 2048)
    if not text:
        return ""
    folded = text.casefold()
    # Prefer the same canonical names used by the asset import template.  The
    # aliases in normalize_vendor cover common vendor spellings and Chinese
    # names; the catalog scan covers the remaining registered vendors.
    for candidate in (*ASSET_NETWORK_VENDORS, *ASSET_SECURITY_VENDORS):
        if str(candidate).casefold() in folded:
            return normalize_asset_vendor(candidate)
    for needle, canonical in (
        ("思科", "Cisco"), ("华为", "Huawei"), ("华三", "H3C"),
        ("锐捷", "Ruijie"), ("中兴", "ZTE"), ("迈普", "Maipu"),
        ("迪普", "DPtech"), ("飞塔", "Fortinet"), ("山石", "Hillstone"),
        ("深信服", "Sangfor"), ("检查点", "Check Point"),
        ("帕洛阿尔托", "Palo Alto"), ("启明星辰", "Venustech"),
        ("绿盟", "NSFOCUS"), ("天融信", "Topsec"), ("奇安信", "Qi An Xin"),
    ):
        if needle in text:
            return canonical
    normalized = normalize_vendor(text)
    if normalized in set((*ASSET_NETWORK_VENDORS, *ASSET_SECURITY_VENDORS)):
        return normalize_asset_vendor(normalized)
    return ""


async def _resolve_live_librenms_rule(
    conn: Any,
    *,
    ip: str,
    community: str,
    port: int,
    snmp_version: str,
    identity: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Resolve system identity first, then only plausible LibreNMS GET/WALK clauses."""
    from services.snmp_service import _snmp_get_versioned, _snmp_walk_versioned

    base = {
        "vendor": "",
        "platform": "",
        "sys_object_id": identity.get("sys_object_id", ""),
        "sys_descr": identity.get("sys_descr", ""),
        "sys_name": identity.get("sys_name", ""),
        "sys_contact": identity.get("sys_contact", ""),
        "sys_location": identity.get("sys_location", ""),
    }
    best_system_rule = resolve_rule(conn, base)
    best_score = int(((best_system_rule or {}).get("identity_match") or {}).get("score") or 0)
    planned = identity_snmp_probe_plan(conn, identity, minimum_score=best_score)
    if not planned:
        return best_system_rule

    asyncio_module = __import__("asyncio")
    semaphore = asyncio_module.Semaphore(8)

    async def read(item: Mapping[str, Any]) -> tuple[str, str, Any]:
        field = str(item.get("field") or "")
        oid = str(item.get("oid") or "")
        async with semaphore:
            try:
                if field == "snmp_get":
                    value = await _snmp_get_versioned(ip, community, oid, port, snmp_version)
                    return field, oid, value
                rows = await _snmp_walk_versioned(ip, community, oid, port, snmp_version)
                values = [str(value) for _row_oid, value in rows if value is not None]
                return field, oid, values
            except Exception as exc:
                logger.debug("LibreNMS identity %s %s failed: %s", field, oid, type(exc).__name__)
                return field, oid, None

    reads = await asyncio_module.gather(*(read(item) for item in planned))
    enriched = dict(base)
    enriched["snmp_get"] = {}
    enriched["snmp_walk"] = {}
    for field, oid, value in reads:
        if value is not None:
            enriched[field][oid] = value
    resolved = resolve_rule(conn, enriched)
    return resolved or best_system_rule


def _resolve_optional_identity_rule(conn: Any, identity: Mapping[str, Any]) -> dict[str, Any] | None:
    """Resolve an optional LibreNMS rule without poisoning the caller transaction."""
    savepoint = "snmp_identity_rule_resolution"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        rule = resolve_rule(conn, identity)
    except Exception as exc:
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception as recovery_exc:
            # All current callers open a read-only identity lookup connection.
            # If the adapter cannot restore the savepoint, clear the failed
            # transaction so later inventory reads can still proceed.
            logger.warning(
                "Savepoint recovery failed after LibreNMS identity lookup: %s",
                type(recovery_exc).__name__,
            )
            conn.rollback()
        logger.debug("LibreNMS identity resolution unavailable: %s", type(exc).__name__)
        return None
    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    return rule


def resolve_snmp_vendor_identity(
    conn: Any,
    *,
    sys_object_id: Any = "",
    sys_descr: Any = "",
    sys_name: Any = "",
    asset_vendor: Any = "",
    asset_platform: Any = "",
    asset_model: Any = "",
) -> dict[str, Any]:
    """Resolve fresh SNMP identity without exposing transport credentials.

    LibreNMS rules are evaluated first.  Built-in enterprise OID mappings and
    sysDescr matching are used only when no persisted rule matches.  Asset
    metadata is returned separately and never presented as observed SNMP
    evidence.
    """
    observed_oid = normalize_oid(sys_object_id)
    descr = _text(sys_descr, 2048)
    name = _text(sys_name, 256)
    canonical_asset_vendor = normalize_asset_vendor(asset_vendor) or vendor_from_asset_platform(asset_platform)
    asset_platform_value = _text(asset_platform, 128)
    model_value = _text(asset_model, 256) or _model_from_descr(descr)
    observed_vendor = ""
    source = "none"
    platform = asset_platform_value
    reason = "SNMP identity did not contain a recognized vendor"
    rule = None

    try:
        # Keep the first-use path aligned with the regular discovery flow:
        # LibreNMS definitions are fetched/indexed before resolving a rule.
        # Async API callers run this service through ``asyncio.to_thread`` so
        # a repository fetch never blocks the event loop.
        ensure_rules_available()
    except Exception as exc:
        logger.debug("LibreNMS rule bootstrap unavailable: %s", type(exc).__name__)

    rule = _resolve_optional_identity_rule(
        conn,
        {
            "vendor": "",
            "platform": "",
            "sys_object_id": observed_oid,
            "sys_descr": descr,
            "sys_name": name,
        },
    )

    if rule and str(rule.get("vendor") or "").strip():
        observed_vendor = normalize_asset_vendor(rule.get("vendor"))
        source = "librenms"
        platform = _text(rule.get("platform"), 128) or platform
        reason = "matched LibreNMS sysObjectID/sysDescr detection rule"
    else:
        observed_vendor = next(
            (
                normalize_asset_vendor(vendor)
                for prefix, vendor in _OBSERVED_VENDOR_PREFIXES.items()
                if observed_oid.startswith("." + prefix)
            ),
            "",
        )
        if observed_vendor:
            source = "sysObjectID"
            reason = "matched built-in enterprise sysObjectID mapping"
        else:
            observed_vendor = _vendor_from_sys_descr(descr)
            if observed_vendor:
                source = "sysDescr"
                reason = "matched registered vendor name in sysDescr"

    observed_vendor = normalize_asset_vendor(observed_vendor)
    # Only registered asset vendors are valid canonical output.  This also
    # prevents a stale LibreNMS rule from introducing a second naming scheme.
    valid_vendors = set((*ASSET_NETWORK_VENDORS, *ASSET_SECURITY_VENDORS))
    if observed_vendor not in valid_vendors:
        observed_vendor = ""
        source = "none"
        platform = asset_platform_value
        reason = "SNMP identity did not match an asset-import vendor"

    if observed_vendor and canonical_asset_vendor and observed_vendor != canonical_asset_vendor:
        status = "conflict"
        reason = f"asset vendor conflicts with observed {observed_vendor} identity"
    elif observed_vendor:
        status = "identified"
    else:
        status = "unidentified"

    if rule and source == "librenms":
        model_value = model_value or _text(rule.get("display_name"), 256)
    return {
        "status": status,
        "vendor": observed_vendor,
        "asset_vendor": canonical_asset_vendor,
        "source": source,
        "platform": platform,
        "sys_object_id": observed_oid,
        "model": model_value,
        "reason": reason,
        "sys_descr": descr,
        "sys_name": name,
    }
