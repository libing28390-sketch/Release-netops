"""Read-only SNMP identity and per-device OID discovery.

The service deliberately keeps discovery evidence separate from operator-created
metric profiles. A profile can describe a family of devices, while this module
records which table columns and row indexes the current device actually exposes.
Generic standards-based hardware probes run independently of vendor recognition;
private OIDs require a matching LibreNMS rule, catalog, or reviewed adapter.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from database import get_db_connection
from services.snmp_vendor_registry import (
    ASSET_VENDOR_ENTERPRISE_PREFIXES,
    ASSET_NETWORK_VENDORS,
    ASSET_SECURITY_VENDORS,
    adapter_descriptor,
    normalize_asset_vendor,
    vendor_from_asset_platform,
)
from services.librenms_rule_service import (
    ensure_rules_available,
    identity_snmp_probe_plan,
    resolve_rule,
)

logger = logging.getLogger(__name__)

RULE_VERSION = "snmp-discovery-catalog-2"
# v2 adds Comware processor/mempool adapters; v3 persists H3C HH3C-DOT11 tables.
# v4 scopes wireless probes to controller identities and adds VRP per-SSID clients.
HARDWARE_DISCOVERY_VERSION = "nexora.hardware.discovery.v4"
HARDWARE_ARTIFACT_VERSION = "nexora.hardware.direct-poll.v1"
_DISCOVERY_CACHE_TTL_SECONDS = 30.0
_discovery_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_discovery_cache_lock = threading.Lock()

SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"

_CISCO_PREFIX = "1.3.6.1.4.1.9."
_OBSERVED_VENDOR_PREFIXES = ASSET_VENDOR_ENTERPRISE_PREFIXES
_CISCO_CPU_COLUMNS = (
    ("cpmCPUTotal5minRev", "1.3.6.1.4.1.9.9.109.1.1.1.1.8"),
    ("cpmCPUTotal5min", "1.3.6.1.4.1.9.9.109.1.1.1.1.5"),
    ("cpmCPUTotal1minRev", "1.3.6.1.4.1.9.9.109.1.1.1.1.7"),
    ("cpmCPUTotal1min", "1.3.6.1.4.1.9.9.109.1.1.1.1.6"),
    ("avgBusy5", "1.3.6.1.4.1.9.2.1.58.0"),
)
_CISCO_MEMORY_PAIRS = (
    (
        "cempMemPoolHC",
        "1.3.6.1.4.1.9.9.221.1.1.1.1.18",
        "1.3.6.1.4.1.9.9.221.1.1.1.1.20",
    ),
    (
        "ciscoMemoryPool",
        "1.3.6.1.4.1.9.9.48.1.1.1.5",
        "1.3.6.1.4.1.9.9.48.1.1.1.6",
    ),
    (
        "cpmCPUMemoryHC",
        "1.3.6.1.4.1.9.9.109.1.1.1.1.17",
        "1.3.6.1.4.1.9.9.109.1.1.1.1.19",
    ),
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _numeric_rows(rows: list[tuple[str, Any]]) -> list[tuple[str, float]]:
    output: list[tuple[str, float]] = []
    for suffix, raw in rows:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value == value and value not in {float("inf"), float("-inf")}:
            normalized_suffix = str(suffix or "").strip().strip(".")
            if normalized_suffix:
                output.append((normalized_suffix, value))
    return output


def _pair_rows(left: list[tuple[str, Any]], right: list[tuple[str, Any]]) -> list[str]:
    left_map = {suffix: value for suffix, value in _numeric_rows(left)}
    right_map = {suffix: value for suffix, value in _numeric_rows(right)}
    return sorted(set(left_map).intersection(right_map))


def _metric_config(
    *,
    mode: str,
    oid: str = "",
    used_oid: str = "",
    free_oid: str = "",
    selector: str = "",
    unit: str = "%",
    aggregation: str = "first",
) -> dict[str, Any]:
    return {
        "mode": mode,
        "oid": normalize_oid(oid),
        "used_oid": normalize_oid(used_oid),
        "free_oid": normalize_oid(free_oid),
        "selector": selector,
        "unit": unit,
        "aggregation": aggregation,
        "scale": 1.0,
        "offset": 0.0,
        "discovery_source": "snmp_walk",
        "discovery_rule_version": RULE_VERSION,
    }


def _cisco_cpu_window(metric_name: str) -> str:
    token = str(metric_name or "").casefold()
    return "1m" if "1min" in token else "5m"


def _index_parts(suffix: str) -> list[int] | None:
    token = str(suffix or "").strip().strip(".")
    if not token or not re.fullmatch(r"\d+(?:\.\d+)*", token):
        return None
    return [int(part) for part in token.split(".")]


def _cisco_sensor(
    *,
    source_id: str,
    component_class: str,
    measurement_type: str,
    oid: str,
    suffix: str,
    sensor_name: str,
    group_name: str,
    unit: str,
    poll_plan: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
    states: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Build a per-instance Cisco inventory definition for the normal poller."""
    scalar = bool(poll_plan.get("kind") == "get")
    index = [] if scalar else _index_parts(suffix)
    if index is None:
        return None
    info = dict(metadata or {})
    info["poll_plan"] = dict(poll_plan)
    return {
        "source_type": "cisco_adapter",
        "source_id": source_id,
        "component_class": component_class,
        "measurement_type": measurement_type,
        "index": index,
        "index_labels": {"index": suffix or "scalar"},
        "oid": normalize_oid(oid),
        "unit": unit,
        "scale": 1.0,
        "offset": 0.0,
        "states": dict(states or {}),
        "thresholds": {},
        "metadata": info,
        "sensor_name": sensor_name,
        "entity_name": "",
        "group_name": group_name,
    }


def _build_cisco_cpu_sensors(
    rows_by_metric: Mapping[str, list[tuple[str, float]]],
) -> list[dict[str, Any]]:
    """Keep the preferred Cisco CPU source for each real sample window.

    Enhanced/legacy five-minute columns are alternatives for one window, not
    separate series. One-minute and five-minute sources remain independent.
    The scalar avgBusy5 source is used only when no five-minute table exists.
    """
    selected_by_window: dict[str, tuple[str, str, list[tuple[str, float]]]] = {}
    for metric_name, oid in _CISCO_CPU_COLUMNS:
        rows = rows_by_metric.get(metric_name) or []
        if not rows:
            continue
        window = _cisco_cpu_window(metric_name)
        if window not in selected_by_window:
            selected_by_window[window] = (metric_name, oid, rows)

    sensors: list[dict[str, Any]] = []
    for window, (metric_name, oid, rows) in sorted(selected_by_window.items()):
        scalar = metric_name == "avgBusy5"
        for suffix, _value in rows:
            poll_plan = (
                {"kind": "get", "oid": oid}
                if scalar
                else {"kind": "direct", "oid": oid, "index": suffix, "factor": 1.0, "offset": 0.0}
            )
            index_label = "scalar" if scalar else suffix
            sensor = _cisco_sensor(
                source_id=metric_name,
                component_class="processor",
                measurement_type="cpu_usage_percent",
                oid=oid,
                suffix="" if scalar else suffix,
                sensor_name=f"CPU {window}" if scalar else f"CPU {window} {index_label}",
                group_name="CPU",
                unit="percent",
                poll_plan=poll_plan,
                metadata={"window": window, "metric_name": metric_name},
            )
            if sensor:
                sensors.append(sensor)
    return sensors


def _build_cisco_memory_sensors(
    family: str,
    used_oid: str,
    free_oid: str,
    suffixes: list[str],
) -> list[dict[str, Any]]:
    """Create canonical used/total/ratio measurements for each paired pool."""
    sensors: list[dict[str, Any]] = []
    for suffix in suffixes:
        used = {"oid": used_oid, "index": suffix, "factor": 1.0, "offset": 0.0}
        free = {"oid": free_oid, "index": suffix, "factor": 1.0, "offset": 0.0}
        measurements = (
            (
                "memory_used_bytes",
                "bytes",
                {"kind": "memory_component", "used": used},
            ),
            (
                "memory_total_bytes",
                "bytes",
                {"kind": "memory_sum", "used": used, "free": free},
            ),
            (
                "memory_usage_percent",
                "percent",
                {"kind": "memory_ratio", "used": used, "free": free},
            ),
        )
        for measurement_type, unit, poll_plan in measurements:
            sensor = _cisco_sensor(
                source_id=family,
                component_class="memory_pool",
                measurement_type=measurement_type,
                oid=used_oid,
                suffix=suffix,
                sensor_name=f"{family} memory pool {suffix}",
                group_name="Memory",
                unit=unit,
                poll_plan=poll_plan,
                metadata={"family": family, "pool_index": suffix},
            )
            if sensor:
                sensors.append(sensor)
    return sensors


_CISCO_ENVIRONMENT_STATES = {
    "1": "normal",
    "2": "warning",
    "3": "critical",
    "4": "critical",
    "5": "unknown",
    "6": "critical",
}


def _build_cisco_environment_sensors(
    metric_key: str,
    oid: str,
    rows: list[tuple[str, float]],
) -> list[dict[str, Any]]:
    is_temperature = metric_key == "temperature"
    component_class = (
        "temperature" if is_temperature else
        "fan_state" if metric_key == "fan" else
        "power_supply_state"
    )
    sensors: list[dict[str, Any]] = []
    for suffix, _value in rows:
        sensor = _cisco_sensor(
            source_id=f"ciscoEnvMon{metric_key.title().replace('_', '')}",
            component_class=component_class,
            measurement_type="temperature_celsius" if is_temperature else "component_state",
            oid=oid,
            suffix=suffix,
            sensor_name=f"{'Temperature' if is_temperature else 'Fan' if metric_key == 'fan' else 'Power supply'} {suffix}",
            group_name="Environment",
            unit="celsius" if is_temperature else "state",
            poll_plan={"kind": "direct", "oid": oid, "index": suffix, "factor": 1.0, "offset": 0.0},
            metadata={"metric_name": metric_key, "source_mib": "CISCO-ENVMON-MIB"},
            states={} if is_temperature else _CISCO_ENVIRONMENT_STATES,
        )
        if sensor:
            sensors.append(sensor)
    return sensors


def build_cisco_exporter_module(
    cpu: Mapping[str, Any] | None,
    memory: Mapping[str, Any] | None,
    extras: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a strict snmp_exporter module from selected Cisco table columns."""

    metrics: list[dict[str, Any]] = []
    walk: list[str] = []
    if cpu and cpu.get("oid"):
        base = str(cpu["oid"]).rsplit(".", 1)[0]
        walk.append(base)
        metric = {
            "name": str(cpu.get("metric_name") or "cpmCPUTotal5minRev"),
            "oid": str(cpu["oid"]),
            "type": "gauge",
            "help": "Cisco CPU utilization selected from the device CPU table.",
        }
        if not str(cpu["oid"]).endswith(".0"):
            metric["indexes"] = [{"labelname": "cpu_index", "type": "gauge"}]
        metrics.append(metric)
    if memory and memory.get("used_oid") and memory.get("free_oid"):
        used = str(memory["used_oid"])
        free = str(memory["free_oid"])
        walk.extend([used.rsplit(".", 1)[0], free.rsplit(".", 1)[0]])
        index_name = "cpu_index" if str(memory.get("family")) == "cpmCPUMemoryHC" else "memory_pool_index"
        metrics.extend(
            [
                {
                    "name": "ciscoMemoryPoolUsed" if index_name == "memory_pool_index" else "cpmCPUMemoryHCUsed",
                    "oid": used,
                    "type": "gauge",
                    "help": "Cisco memory used selected from the device memory table.",
                    "indexes": [{"labelname": index_name, "type": "gauge"}],
                },
                {
                    "name": "ciscoMemoryPoolFree" if index_name == "memory_pool_index" else "cpmCPUMemoryHCFree",
                    "oid": free,
                    "type": "gauge",
                    "help": "Cisco memory free selected from the device memory table.",
                    "indexes": [{"labelname": index_name, "type": "gauge"}],
                },
            ]
        )
    for metric_key, definition in (extras or {}).items():
        oid = str(definition.get("oid") or "")
        if not oid:
            continue
        base = oid.rsplit(".", 1)[0]
        walk.append(base)
        metric_name = {
            "temperature": "entSensorValue",
            "fan": "ciscoEnvMonFanState",
            "power_supply": "ciscoEnvMonSupplyState",
        }.get(metric_key, metric_key)
        index_name = {
            "temperature": "sensor_index",
            "fan": "fan_index",
            "power_supply": "psu_index",
        }.get(metric_key, f"{metric_key}_index")
        metrics.append(
            {
                "name": metric_name,
                "oid": oid,
                "type": "gauge",
                "help": f"Cisco {metric_key} value selected from the device sensor table.",
                "indexes": [{"labelname": index_name, "type": "gauge"}],
            }
        )
    unique_walk = list(dict.fromkeys(item for item in walk if item))
    return {"walk": unique_walk, "metrics": metrics} if metrics else {}


def _catalog_metric_category(name: str) -> str | None:
    token = str(name or "").casefold()
    if any(item in token for item in ("cpu", "processor", "duty", "cpurate", "cpuload")):
        return "cpu"
    if any(item in token for item in ("memory", "mem", "buffer")):
        return "memory"
    if any(item in token for item in ("temperature", "temp")):
        return "temperature"
    if "fan" in token:
        return "fan"
    if any(item in token for item in ("powersupply", "powerstatus", "power_state", "psu")):
        return "power_supply"
    if any(item in token for item in ("onlineap", "accesspoints", "totalapnum", "apnum")):
        return "wireless_ap_online_count"
    if any(item in token for item in ("assocuser", "clients", "stations", "numofclients", "totalsta")):
        return "wireless_client_online_count"
    return None


def _catalog_vendor_match(module_vendor: Any, identity_vendor: Any) -> bool:
    module_key = str(module_vendor or "").strip().casefold()
    identity_key = normalize_vendor(identity_vendor).casefold()
    aliases = {
        "hpe": "h3c",
        "hp": "h3c",
        "comware": "h3c",
        "vrp": "huawei",
        "fortios": "fortinet",
        "stoneos": "hillstone",
        "sangforos": "sangfor",
        "rgos": "ruijie",
        "zxros": "zte",
        "mypower": "maipu",
        "conplat": "dptech",
        "dcos": "dcn",
        "smartzone": "ruckus",
        "fiberhome": "fiberhome",
        "nokia": "nokia",
        "extreme": "extreme networks",
        "extremenetworks": "extreme networks",
        "mikrotik": "mikrotik",
        "ubiquiti": "ubiquiti",
        "dlink": "d-link",
        "d-link": "d-link",
        "tplink": "tp-link",
        "tp-link": "tp-link",
        "dell": "dell",
        "brocade": "brocade",
        "ciena": "ciena",
        "alcatel": "alcatel-lucent enterprise",
        "alcatel-lucent enterprise": "alcatel-lucent enterprise",
        "allied": "allied telesis",
        "allied telesis": "allied telesis",
        "edgecore": "edgecore",
        "arista": "arista",
        "raisecom": "raisecom",
    }
    return aliases.get(module_key, module_key) == aliases.get(identity_key, identity_key)


def _catalog_variant_for_identity(identity: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    from services.monitoring_oid_catalog import iter_builtin_catalog

    vendor = identity.get("vendor")
    platform = str(identity.get("platform") or "").casefold()
    candidates: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for item in iter_builtin_catalog():
        module = dict(item)
        variant = dict(module.get("variant") or {})
        if not bool(variant.get("enabled", True)) or str(variant.get("status") or "PUBLISHED").upper() not in {"TESTED", "PUBLISHED"}:
            continue
        if not _catalog_vendor_match(module.get("vendor"), vendor):
            continue
        feature_domain = str(module.get("feature_domain") or "").casefold()
        if feature_domain not in {"hardware", "wireless"}:
            continue
        supported = [str(value).casefold() for value in variant.get("supported_platforms") or []]
        score = 20 if feature_domain == "hardware" else 10
        if feature_domain == "wireless" and any(token in platform for token in ("wireless", "wlan", "wlc", "smartzone", "aireos")):
            score += 60
        if supported and platform:
            if not any(value == platform or value in platform or platform in value for value in supported):
                continue
            score += 50
        candidates.append((score, module, variant))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], str(item[1].get("module_key") or "")))
    return candidates[0][1], candidates[0][2]


def _build_catalog_exporter_module(selected: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    metrics: list[dict[str, Any]] = []
    walk: list[str] = []
    for category, definition in selected.items():
        oid = str(definition.get("oid") or "")
        if not oid:
            continue
        metric = dict(definition.get("exporter_metric") or {})
        metric.setdefault("name", str(definition.get("metric_name") or category))
        metric.setdefault("oid", oid)
        metric.setdefault("type", "gauge")
        metric.setdefault("help", f"Vendor {category} metric discovered from the device table.")
        metrics.append(metric)
        walk.append(oid if oid.endswith(".0") else oid.rsplit(".", 1)[0])
    return {"walk": list(dict.fromkeys(walk)), "metrics": metrics} if metrics else {}


async def _discover_catalog_device(
    ip: str,
    community: str,
    port: int,
    *,
    identity: Mapping[str, Any],
    snmp_version: str,
) -> dict[str, Any]:
    """Discover health columns from the versioned vendor catalog."""

    from services.snmp_service import DEFAULT_INTERFACE_CONFIG, _snmp_get_versioned, _snmp_walk_versioned

    catalog_match = _catalog_variant_for_identity(identity)
    selected: dict[str, dict[str, Any]] = {}
    module_key = ""
    variant_key = ""
    if catalog_match:
        module, variant = catalog_match
        module_key = str(module.get("module_key") or "")
        variant_key = str(variant.get("variant_key") or "")
        oid_config = variant.get("oid_config") or {}
        seen_categories: set[str] = set()
        for metric in oid_config.get("metrics") or []:
            if not isinstance(metric, Mapping):
                continue
            category = _catalog_metric_category(str(metric.get("name") or metric.get("source_name") or ""))
            oid = normalize_oid(metric.get("oid"))
            if not category or not oid or category in seen_categories:
                continue
            if oid.endswith(".0"):
                value = await _snmp_get_versioned(ip, community, oid, port, snmp_version)
                try:
                    valid = value is not None and float(value) == float(value)
                except (TypeError, ValueError):
                    valid = False
                rows = [("0", value)] if valid else []
            else:
                rows = await _snmp_walk_versioned(ip, community, oid, port, snmp_version)
                rows = _numeric_rows(rows)
            if not rows:
                continue
            selector = "" if oid.endswith(".0") else str(rows[0][0])
            mode = "direct_value" if category in {"temperature", "wireless_ap_online_count", "wireless_client_online_count"} else "status_code" if category in {"fan", "power_supply"} else "direct_percent"
            unit = "°C" if category == "temperature" else "count" if category.startswith("wireless_") else "%"
            definition = _metric_config(
                mode=mode,
                oid=oid,
                selector=selector,
                unit=unit,
                aggregation="max" if category == "temperature" else "first",
            )
            exporter_metric = {
                key: value
                for key, value in dict(metric).items()
                if key in {"name", "oid", "type", "help", "indexes", "lookups", "enum_values"}
            }
            exporter_metric["oid"] = oid.lstrip(".")
            definition.update({"metric_name": str(metric.get("name") or category), "exporter_metric": exporter_metric, "rows": len(rows)})
            selected[category] = definition
            seen_categories.add(category)

    interface: dict[str, Any] = {}
    try:
        interface = deepcopy(DEFAULT_INTERFACE_CONFIG)
        names = await _snmp_walk_versioned(ip, community, interface["if_name_oid"], port, snmp_version)
        if not names:
            names = await _snmp_walk_versioned(ip, community, interface["if_descr_oid"], port, snmp_version)
        hc_in = await _snmp_walk_versioned(ip, community, interface["if_hc_in_octets_oid"], port, snmp_version)
        hc_out = await _snmp_walk_versioned(ip, community, interface["if_hc_out_octets_oid"], port, snmp_version)
        interface["counter_mode"] = "64" if _numeric_rows(hc_in) and _numeric_rows(hc_out) else "32"
        interface["discovery_source"] = "snmp_walk"
        interface["interface_rows"] = len(names)
        if not names:
            interface = {}
    except Exception as exc:
        logger.debug("Generic vendor interface discovery failed for %s: %s", ip, exc)

    exporter_module = _build_catalog_exporter_module(selected)
    status = "matched" if selected and interface else "partial" if selected or interface else "no_supported_oid"
    reason = (
        f"catalog variant {variant_key or module_key} returned device rows"
        if selected
        else "vendor identity was known but no catalog health rows were returned"
    )
    return {
        "status": status,
        "reason": reason,
        "rule_version": RULE_VERSION,
        "rule_source": "builtin_generated",
        "catalog_module": module_key,
        "catalog_variant": variant_key,
        "adapter": adapter_descriptor(identity.get("vendor"), catalog_available=bool(catalog_match), static_available=False),
        "identity": dict(identity),
        "metrics": selected,
        "interface": interface,
        "exporter_module": exporter_module,
        "observed_at": _now(),
    }


async def _discover_static_platform_device(
    ip: str,
    community: str,
    port: int,
    *,
    identity: Mapping[str, Any],
    snmp_version: str,
) -> dict[str, Any] | None:
    """Use the existing platform OID map for catalog gaps such as Arista/Raisecom."""

    from services.snmp_service import DEFAULT_INTERFACE_CONFIG, VENDOR_OIDS, _snmp_get_versioned, _snmp_walk_versioned

    platform = str(identity.get("platform") or "").casefold()
    platform_aliases = {
        "raisecom": "raisecom_ros",
        "raisecom-ros": "raisecom_ros",
        "raisecom_ros": "raisecom_ros",
    }
    platform_key = platform_aliases.get(platform, platform)
    if platform_key not in VENDOR_OIDS:
        platform_key = ""
    if not platform_key:
        return None
    raw = VENDOR_OIDS[platform_key]
    selected: dict[str, dict[str, Any]] = {}

    async def read_numeric(oid: Any) -> tuple[str, int] | None:
        normalized = normalize_oid(oid)
        if not normalized:
            return None
        if normalized.endswith(".0"):
            value = await _snmp_get_versioned(ip, community, normalized, port, snmp_version)
            try:
                return "", int(float(value))
            except (TypeError, ValueError):
                return None
        rows = _numeric_rows(await _snmp_walk_versioned(ip, community, normalized, port, snmp_version))
        return (rows[0][0], int(rows[0][1])) if rows else None

    for category, key, mode, unit in (
        ("cpu", "cpu", "direct_percent", "%"),
        ("memory", "mem", "direct_percent", "%"),
        ("temperature", "temp", "direct_value", "°C"),
        ("fan", "fan", "status_code", "%"),
        ("power_supply", "psu", "status_code", "%"),
    ):
        hit = await read_numeric(raw.get(key))
        if not hit:
            continue
        selector, _ = hit
        selected[category] = _metric_config(mode=mode, oid=str(raw.get(key) or ""), selector=selector, unit=unit)

    if raw.get("mem_used") and raw.get("mem_free"):
        used = await read_numeric(raw.get("mem_used"))
        free = await read_numeric(raw.get("mem_free"))
        if used and free and used[0] == free[0]:
            selected["memory"] = _metric_config(
                mode="used_free_percent",
                used_oid=str(raw["mem_used"]),
                free_oid=str(raw["mem_free"]),
                selector=used[0],
            )
    elif raw.get("mem_used") and raw.get("mem_size"):
        used = await read_numeric(raw.get("mem_used"))
        total = await read_numeric(raw.get("mem_size"))
        if used and total and used[0] == total[0]:
            selected["memory"] = _metric_config(
                mode="used_total_percent",
                used_oid=str(raw["mem_used"]),
                oid=str(raw["mem_used"]),
                selector=used[0],
            ) | {"total_oid": normalize_oid(raw["mem_size"])}

    interface: dict[str, Any] = {}
    try:
        interface = deepcopy(DEFAULT_INTERFACE_CONFIG)
        names = await _snmp_walk_versioned(ip, community, interface["if_name_oid"], port, snmp_version)
        if not names:
            names = await _snmp_walk_versioned(ip, community, interface["if_descr_oid"], port, snmp_version)
        hc_in = await _snmp_walk_versioned(ip, community, interface["if_hc_in_octets_oid"], port, snmp_version)
        hc_out = await _snmp_walk_versioned(ip, community, interface["if_hc_out_octets_oid"], port, snmp_version)
        interface["counter_mode"] = "64" if _numeric_rows(hc_in) and _numeric_rows(hc_out) else "32"
        interface["interface_rows"] = len(names)
        if not names:
            interface = {}
    except Exception as exc:
        logger.debug("Static platform interface discovery failed for %s: %s", ip, exc)

    exporter = _build_catalog_exporter_module(selected)
    return {
        "status": "matched" if selected and interface else "partial" if selected or interface else "no_supported_oid",
        "reason": f"static platform OID map {platform_key} returned device rows" if selected else f"platform {platform_key} returned no supported health rows",
        "rule_version": RULE_VERSION,
        "rule_source": "builtin_generated",
        "catalog_module": platform_key,
        "catalog_variant": "",
        "adapter": adapter_descriptor(identity.get("vendor"), static_available=True),
        "identity": dict(identity),
        "metrics": selected,
        "interface": interface,
        "exporter_module": exporter,
        "observed_at": _now(),
    }


async def _discover_librenms_rule(
    ip: str,
    community: str,
    port: int,
    *,
    identity: Mapping[str, Any],
    rule: Mapping[str, Any],
    snmp_version: str,
) -> dict[str, Any]:
    """Probe numeric candidates parsed from a LibreNMS OS discovery rule."""
    from services.snmp_service import DEFAULT_INTERFACE_CONFIG, _snmp_get_versioned, _snmp_walk_versioned
    from services.snmp_hardware_probe_service import probe_librenms_hardware

    selected: dict[str, dict[str, Any]] = {}
    for candidate in rule.get("oid_candidates") or []:
        category = str(candidate.get("category") or "other")
        oid = normalize_oid(candidate.get("oid"))
        if category not in {"cpu", "memory", "temperature", "fan", "power_supply", "wireless_ap_online_count", "wireless_client_online_count"} or not oid or category in selected:
            continue
        if oid.endswith(".0"):
            value = await _snmp_get_versioned(ip, community, oid, port, snmp_version)
            try:
                valid = value is not None and float(value) == float(value)
            except (TypeError, ValueError):
                valid = False
            rows = [("0", value)] if valid else []
        else:
            rows = _numeric_rows(await _snmp_walk_versioned(ip, community, oid, port, snmp_version))
        if not rows:
            continue
        selector = "" if oid.endswith(".0") else rows[0][0]
        mode = "direct_value" if category in {"temperature", "wireless_ap_online_count", "wireless_client_online_count"} else "status_code" if category in {"fan", "power_supply"} else "direct_percent"
        selected[category] = _metric_config(
            mode=mode,
            oid=oid,
            selector=selector,
            unit="°C" if category == "temperature" else "count" if category.startswith("wireless_") else "%",
        ) | {"source": "librenms", "rule_id": rule.get("id"), "context": candidate.get("context") or ""}

    interface: dict[str, Any] = {}
    try:
        interface = deepcopy(DEFAULT_INTERFACE_CONFIG)
        names = await _snmp_walk_versioned(ip, community, interface["if_name_oid"], port, snmp_version)
        if not names:
            names = await _snmp_walk_versioned(ip, community, interface["if_descr_oid"], port, snmp_version)
        hc_in = await _snmp_walk_versioned(ip, community, interface["if_hc_in_octets_oid"], port, snmp_version)
        hc_out = await _snmp_walk_versioned(ip, community, interface["if_hc_out_octets_oid"], port, snmp_version)
        interface["counter_mode"] = "64" if _numeric_rows(hc_in) and _numeric_rows(hc_out) else "32"
        interface["interface_rows"] = len(names)
        interface["discovery_source"] = "librenms"
        if not names:
            interface = {}
    except Exception as exc:
        logger.debug("LibreNMS interface discovery failed for %s: %s", ip, exc)

    exporter = _build_catalog_exporter_module(selected)
    hardware_probe = await probe_librenms_hardware(
        ip,
        community,
        port,
        rule=rule,
        identity=identity,
        version=snmp_version,
    )
    hardware_sensors = hardware_probe.get("sensors") or []
    category_results = hardware_probe.get("category_results") or []
    compatibility = rule.get("compatibility") or {}
    compatibility_level = str(
        compatibility.get("hardware_level") or compatibility.get("level") or "partial"
    ).casefold()
    support_rank = {"supported": 0, "partial": 1, "requires_adapter": 2, "unsupported": 3}
    hardware_support_status = compatibility_level if compatibility_level in support_rank else "partial"
    for category in category_results:
        category_status = str(category.get("status") or "partial").casefold()
        observed_level = (
            "requires_adapter" if category_status == "unsupported"
            else "partial" if category_status in {"partial", "failed"}
            else "supported"
        )
        if support_rank[observed_level] > support_rank[hardware_support_status]:
            hardware_support_status = observed_level
    reason_by_status = {
        "supported": "LibreNMS hardware definitions and probed categories are supported",
        "partial": "LibreNMS hardware support is partial; inspect per-category discovery results",
        "requires_adapter": "One or more LibreNMS hardware definitions need a native adapter or resolvable mapping",
        "unsupported": "The LibreNMS hardware contract is not supported by the native probe",
    }
    hardware_support_reason = reason_by_status[hardware_support_status]
    return {
        "status": "matched" if (selected or hardware_sensors) and interface else "partial" if selected or interface or hardware_sensors else "no_supported_oid",
        "reason": f"LibreNMS rule {rule.get('os_key') or rule.get('id')} returned {len(hardware_sensors)} hardware measurements" if hardware_sensors else f"LibreNMS rule {rule.get('os_key') or rule.get('id')} returned device rows" if selected else "LibreNMS rule matched but no candidate rows were returned",
        "rule_version": str(rule.get("source_commit") or RULE_VERSION),
        "rule_source": "librenms",
        "librenms_rule_id": rule.get("id") or "",
        "librenms_source_path": rule.get("source_path") or "",
        "hardware_rule_version": str(rule.get("source_commit") or RULE_VERSION),
        "hardware_rule_contract_version": str(rule.get("rule_contract_version") or ""),
        "hardware_compatibility": rule.get("compatibility") or {},
        "hardware_support_status": hardware_support_status,
        "hardware_discovery_version": HARDWARE_DISCOVERY_VERSION,
        "hardware_artifact_version": HARDWARE_ARTIFACT_VERSION,
        "hardware_sensors": hardware_sensors,
        "hardware_category_results": category_results,
        "adapter": {
            "vendor": identity.get("vendor") or "",
            "mode": "librenms",
            "supported": hardware_support_status in {"supported", "partial"},
            "support_status": hardware_support_status,
            "reason": hardware_support_reason,
        },
        "identity": dict(identity),
        "metrics": selected,
        "interface": interface,
        "exporter_module": exporter,
        "observed_at": _now(),
    }


def _merge_hardware_discovery(target: dict[str, Any], *sources: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge independent hardware sources without dropping partial categories."""
    sensors: list[dict[str, Any]] = []
    seen_sensors: set[tuple[str, str, str, str, str]] = set()
    categories: dict[tuple[str, str], dict[str, Any]] = {}
    for source in (target, *sources):
        if not isinstance(source, Mapping):
            continue
        for sensor_value in source.get("hardware_sensors") or source.get("sensors") or []:
            if not isinstance(sensor_value, Mapping):
                continue
            sensor = dict(sensor_value)
            index = json.dumps(sensor.get("index") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            metadata = sensor.get("metadata") if isinstance(sensor.get("metadata"), Mapping) else {}
            series_variant = str(sensor.get("series_variant") or metadata.get("series_variant") or "")
            if str(sensor.get("measurement_type") or "") == "cpu_usage_percent" and not series_variant:
                series_variant = str(metadata.get("window") or "unknown")
            key = (
                str(sensor.get("source_type") or ""),
                str(sensor.get("component_class") or ""),
                str(sensor.get("measurement_type") or ""),
                index,
                series_variant,
            )
            if key in seen_sensors:
                continue
            seen_sensors.add(key)
            sensors.append(sensor)
        for category_value in source.get("hardware_category_results") or source.get("category_results") or []:
            if not isinstance(category_value, Mapping):
                continue
            category = dict(category_value)
            key = (str(category.get("source_type") or ""), str(category.get("component_class") or ""))
            if key:
                categories[key] = category
        for key, value in (source.get("metrics") or {}).items():
            target.setdefault("metrics", {}).setdefault(key, value)
        if not target.get("interface") and source.get("interface"):
            target["interface"] = source.get("interface")
        if not target.get("exporter_module", {}).get("metrics") and source.get("exporter_module", {}).get("metrics"):
            target["exporter_module"] = source.get("exporter_module")
        for field in ("librenms_rule_id", "librenms_source_path", "hardware_rule_version", "hardware_rule_contract_version", "hardware_compatibility", "hardware_support_status", "hardware_discovery_version", "hardware_artifact_version"):
            if not target.get(field) and source.get(field):
                target[field] = source[field]

    target["hardware_sensors"] = sensors
    target["hardware_category_results"] = [categories[key] for key in sorted(categories)]
    if sensors and target.get("status") in {"no_supported_oid", "identity_missing", "unsupported_vendor", "identified"}:
        target["status"] = "partial"
        target["reason"] = "Standard or LibreNMS hardware tables returned per-component measurements"
    if sensors:
        target["hardware_discovery_version"] = HARDWARE_DISCOVERY_VERSION
        target.setdefault("hardware_artifact_version", HARDWARE_ARTIFACT_VERSION)
    return target


async def discover_device_oid_config(
    ip: str,
    community: str,
    port: int,
    *,
    vendor: Any = "",
    platform: Any = "",
    model: Any = "",
    version: Any = "",
    role: Any = "",
    snmp_version: str = "2c",
) -> dict[str, Any]:
    """Probe identity and Cisco CPU/memory tables without changing the device."""

    from services.snmp_service import (
        SYS_DESCR,
        SYS_NAME,
        SYS_UPTIME,
        _snmp_get_versioned,
        _snmp_walk_versioned,
    )

    values = await __import__("asyncio").gather(
        _snmp_get_versioned(ip, community, SYS_NAME, port, snmp_version),
        _snmp_get_versioned(ip, community, SYS_DESCR, port, snmp_version),
        _snmp_get_versioned(ip, community, SYS_OBJECT_ID, port, snmp_version),
        _snmp_get_versioned(ip, community, SYS_UPTIME, port, snmp_version),
    )
    identity = classify_identity(
        vendor=vendor,
        platform=platform,
        model=model,
        version=version,
        sys_object_id=values[2],
        sys_descr=values[1],
        sys_name=values[0],
    )
    identity["role"] = _text(role, 64)
    identity["uptime_raw"] = _text(values[3], 128)

    # Resolve LibreNMS OS rules against observed SNMP fields before the legacy
    # static vendor classifier rejects an unknown enterprise root. Asset
    # metadata remains separate and an actual vendor conflict still blocks the
    # vendor-specific rule.
    librenms_rule = None
    try:
        await __import__("asyncio").to_thread(ensure_rules_available)
        conn = get_db_connection()
        try:
            librenms_rule = await _resolve_live_librenms_rule(
                conn,
                ip=ip,
                community=community,
                port=port,
                snmp_version=snmp_version,
                identity=identity,
            )
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("LibreNMS rule resolution unavailable for %s: %s", ip, type(exc).__name__)

    if librenms_rule and str(librenms_rule.get("vendor") or "").strip():
        rule_vendor = normalize_vendor(librenms_rule.get("vendor"))
        declared_vendor = normalize_vendor(vendor) or vendor_from_asset_platform(platform)
        observed_vendor = normalize_vendor(identity.get("vendor"))
        conflict_vendors = {
            normalize_vendor(item.get("vendor"))
            for item in (librenms_rule.get("identity_match") or {}).get("conflicts", [])
            if isinstance(item, Mapping) and item.get("vendor")
        }
        if declared_vendor and rule_vendor and declared_vendor != rule_vendor:
            identity["status"] = "conflict"
            identity["reason"] = f"asset vendor {declared_vendor} conflicts with LibreNMS rule vendor {rule_vendor}"
        elif observed_vendor and observed_vendor not in {"unknown", rule_vendor}:
            identity["status"] = "conflict"
            identity["reason"] = f"observed {observed_vendor} identity conflicts with LibreNMS rule vendor {rule_vendor}"
        elif any(value and value != rule_vendor for value in conflict_vendors):
            identity["status"] = "conflict"
            identity["reason"] = "LibreNMS identity matched equally ranked rules from different vendors"
        else:
            identity["vendor"] = rule_vendor
            identity["platform"] = _text(librenms_rule.get("platform"), 128) or identity.get("platform")
            if identity.get("status") in {"unsupported_vendor", "identity_missing"}:
                identity["status"] = "identified"
                identity["reason"] = "LibreNMS OS detection rule matched observed SNMP identity"
        identity["librenms_rule_id"] = librenms_rule.get("id") or ""
        identity["librenms_os_key"] = librenms_rule.get("os_key") or ""
        identity["identity_match"] = librenms_rule.get("identity_match") or {}
        identity["identity_rule_compatibility"] = librenms_rule.get("compatibility") or {}

    result: dict[str, Any] = {
        "status": identity["status"],
        "reason": identity["reason"],
        "rule_version": RULE_VERSION,
        "rule_source": "builtin_generated",
        "identity": identity,
        "metrics": {},
        "interface": {},
        "exporter_module": {},
        "hardware_sensors": [],
        "hardware_category_results": [],
        "hardware_rule_version": str((librenms_rule or {}).get("source_commit") or RULE_VERSION),
        "hardware_rule_contract_version": str((librenms_rule or {}).get("rule_contract_version") or ""),
        "hardware_discovery_version": HARDWARE_DISCOVERY_VERSION,
        "hardware_artifact_version": HARDWARE_ARTIFACT_VERSION,
        "adapter": adapter_descriptor(identity.get("vendor"), catalog_available=False, static_available=False),
        "observed_at": _now(),
    }
    from services.snmp_hardware_probe_service import probe_standard_hardware

    standard_result: dict[str, Any] = {"sensors": [], "category_results": []}
    try:
        standard_result = await probe_standard_hardware(
            ip,
            community,
            port,
            version=snmp_version,
            cisco_iosxr=bool(
                librenms_rule
                and str(librenms_rule.get("os_key") or "").casefold() == "iosxr"
                and str(identity.get("vendor") or "").casefold() == "cisco"
                and identity.get("status") != "conflict"
            ),
        )
    except Exception as exc:
        logger.debug("Standard MIB hardware discovery failed for %s: %s", ip, type(exc).__name__)
    rule_result: dict[str, Any] | None = None
    if librenms_rule and identity.get("status") != "conflict":
        rule_result = await _discover_librenms_rule(
            ip,
            community,
            port,
            identity=identity,
            rule=librenms_rule,
            snmp_version=snmp_version,
        )
    if identity["status"] in {"unsupported_vendor", "identity_missing", "conflict"}:
        return _merge_hardware_discovery(result, standard_result, rule_result)
    if str(identity.get("vendor") or "") != "Cisco":
        catalog_result = await _discover_catalog_device(
            ip,
            community,
            port,
            identity=identity,
            snmp_version=snmp_version,
        )
        static_result = await _discover_static_platform_device(
            ip,
            community,
            port,
            identity=identity,
            snmp_version=snmp_version,
        )
        if rule_result and (rule_result.get("metrics") or rule_result.get("exporter_module") or rule_result.get("hardware_sensors")):
            selected = rule_result
        elif catalog_result.get("metrics") or catalog_result.get("exporter_module"):
            selected = catalog_result
        else:
            selected = static_result or catalog_result
        return _merge_hardware_discovery(selected, standard_result, rule_result, catalog_result, static_result)

    cpu_choice: dict[str, Any] | None = None
    cpu_rows_by_metric: dict[str, list[tuple[str, float]]] = {}
    for metric_name, oid in _CISCO_CPU_COLUMNS:
        if oid.endswith(".0"):
            scalar = await _snmp_get_versioned(ip, community, oid, port, snmp_version)
            try:
                scalar_value = float(scalar) if scalar is not None else None
            except (TypeError, ValueError):
                scalar_value = None
            valid = [("0", scalar_value)] if scalar_value is not None else []
        else:
            rows = await _snmp_walk_versioned(ip, community, oid, port, snmp_version)
            valid = _numeric_rows(rows)
        if valid:
            cpu_rows_by_metric[metric_name] = valid
            if cpu_choice is None:
                suffix, _ = valid[0]
                selector = "" if oid.endswith(".0") else suffix
                cpu_choice = {
                    "metric_name": metric_name,
                    "oid": oid,
                    "selector": selector,
                    "rows": len(valid),
                }
                result["metrics"]["cpu"] = _metric_config(
                    mode="direct_percent",
                    oid=oid,
                    selector=selector,
                    aggregation="max",
                ) | {"metric_name": metric_name, "rows": len(valid)}

    cisco_cpu_sensors = _build_cisco_cpu_sensors(cpu_rows_by_metric)
    if cisco_cpu_sensors:
        result["hardware_sensors"].extend(cisco_cpu_sensors)
        result["hardware_category_results"].append({
            "source_type": "cisco_adapter",
            "component_class": "processor",
            "status": "success",
            "coverage_complete": True,
            "reason_code": "cisco_cpu_rows",
            "reason": "Cisco CPU rows were discovered for each supported measurement window",
        })

    memory_choice: dict[str, Any] | None = None
    cisco_memory_sensors: list[dict[str, Any]] = []
    for family, used_oid, free_oid in _CISCO_MEMORY_PAIRS:
        used_rows = await _snmp_walk_versioned(ip, community, used_oid, port, snmp_version)
        free_rows = await _snmp_walk_versioned(ip, community, free_oid, port, snmp_version)
        selectors = _pair_rows(used_rows, free_rows)
        if selectors:
            selector = selectors[0]
            memory_choice = {"family": family, "used_oid": used_oid, "free_oid": free_oid, "selector": selector}
            result["metrics"]["memory"] = _metric_config(
                mode="used_free_percent",
                used_oid=used_oid,
                free_oid=free_oid,
                selector=selector,
            ) | {"family": family, "rows": len(selectors)}
            cisco_memory_sensors = _build_cisco_memory_sensors(family, used_oid, free_oid, selectors)
            break

    if cisco_memory_sensors:
        result["hardware_sensors"].extend(cisco_memory_sensors)
        result["hardware_category_results"].append({
            "source_type": "cisco_adapter",
            "component_class": "memory_pool",
            "status": "success",
            "coverage_complete": True,
            "reason_code": "cisco_memory_pools",
            "reason": "Cisco used/free memory columns returned matched pool indexes",
        })

    sensor_candidates = {
        "temperature": ("1.3.6.1.4.1.9.9.13.1.3.1.3", "direct_value", "°C"),
        "fan": ("1.3.6.1.4.1.9.9.13.1.4.1.3", "status_code", "bool"),
        "power_supply": ("1.3.6.1.4.1.9.9.13.1.5.1.3", "status_code", "bool"),
    }
    sensor_definitions: dict[str, dict[str, Any]] = {}
    cisco_environment_sensors: list[dict[str, Any]] = []
    for metric_key, (oid, mode, unit) in sensor_candidates.items():
        sensor_rows = await _snmp_walk_versioned(ip, community, oid, port, snmp_version)
        valid_sensor_rows = _numeric_rows(sensor_rows)
        if valid_sensor_rows:
            selector = valid_sensor_rows[0][0]
            sensor_definitions[metric_key] = _metric_config(
                mode=mode,
                oid=oid,
                selector=selector,
                unit=unit,
                aggregation="max" if metric_key == "temperature" else "first",
            ) | {"rows": len(valid_sensor_rows)}
            cisco_environment_sensors.extend(
                _build_cisco_environment_sensors(metric_key, oid, valid_sensor_rows)
            )

    if cisco_environment_sensors:
        result["hardware_sensors"].extend(cisco_environment_sensors)
        for component_class in sorted({str(item["component_class"]) for item in cisco_environment_sensors}):
            count = sum(1 for item in cisco_environment_sensors if item["component_class"] == component_class)
            result["hardware_category_results"].append({
                "source_type": "cisco_adapter",
                "component_class": component_class,
                "status": "success",
                "coverage_complete": True,
                "reason_code": "cisco_environment_rows",
                "reason": f"Cisco environmental table returned {count} {component_class} rows",
            })
    result["metrics"].update(sensor_definitions)

    try:
        from services.snmp_service import DEFAULT_INTERFACE_CONFIG

        interface_config = deepcopy(DEFAULT_INTERFACE_CONFIG)
        name_rows = await _snmp_walk_versioned(ip, community, interface_config["if_name_oid"], port, snmp_version)
        if not name_rows:
            name_rows = await _snmp_walk_versioned(ip, community, interface_config["if_descr_oid"], port, snmp_version)
        hc_in = await _snmp_walk_versioned(ip, community, interface_config["if_hc_in_octets_oid"], port, snmp_version)
        hc_out = await _snmp_walk_versioned(ip, community, interface_config["if_hc_out_octets_oid"], port, snmp_version)
        interface_config["counter_mode"] = "64" if _numeric_rows(hc_in) and _numeric_rows(hc_out) else "32"
        interface_config["discovery_source"] = "snmp_walk"
        interface_config["interface_rows"] = len(name_rows)
        result["interface"] = interface_config if name_rows else {}
    except Exception as exc:
        logger.debug("SNMP interface capability discovery failed for %s: %s", ip, exc)

    result["exporter_module"] = build_cisco_exporter_module(cpu_choice, memory_choice, sensor_definitions)
    result["adapter"] = adapter_descriptor("Cisco")
    if librenms_rule:
        result["librenms_rule_id"] = librenms_rule.get("id") or ""
        result["librenms_source_path"] = librenms_rule.get("source_path") or ""
        result["oid_source"] = "librenms"
        result["rule_source"] = "librenms"
    if result["metrics"].get("cpu") and result["metrics"].get("memory"):
        result["status"] = "matched"
        result["reason"] = "Cisco CPU and memory tables returned usable rows"
    elif result["metrics"] or result["interface"]:
        result["status"] = "partial"
        result["reason"] = "Cisco identity matched but only a subset of metric tables returned usable rows"
    else:
        result["status"] = "no_supported_oid"
        result["reason"] = "Cisco identity matched but no supported CPU, memory, or interface rows were returned"
    return _merge_hardware_discovery(result, standard_result, rule_result)


def persist_discovery(device_id: str, payload: Mapping[str, Any]) -> None:
    identity = dict(payload.get("identity") or {})
    if payload.get("adapter"):
        identity["adapter"] = payload.get("adapter")
    if payload.get("rule_source"):
        identity["rule_source"] = payload.get("rule_source")
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO snmp_device_discoveries
              (device_id, vendor, platform, model, software_version, sys_object_id,
               sys_descr, sys_name, status, reason, rule_version, identity_json,
               metrics_json, interface_json, exporter_json, observed_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (device_id) DO UPDATE SET
              vendor = excluded.vendor, platform = excluded.platform,
              model = excluded.model, software_version = excluded.software_version,
              sys_object_id = excluded.sys_object_id, sys_descr = excluded.sys_descr,
              sys_name = excluded.sys_name, status = excluded.status,
              reason = excluded.reason, rule_version = excluded.rule_version,
              identity_json = excluded.identity_json, metrics_json = excluded.metrics_json,
              interface_json = excluded.interface_json, exporter_json = excluded.exporter_json,
              observed_at = excluded.observed_at, updated_at = excluded.updated_at
            """,
            (
                str(device_id),
                str(identity.get("vendor") or ""),
                str(identity.get("platform") or ""),
                str(identity.get("model") or ""),
                str(identity.get("software_version") or ""),
                str(identity.get("sys_object_id") or ""),
                str(identity.get("sys_descr") or ""),
                str(identity.get("sys_name") or ""),
                str(payload.get("status") or "pending"),
                str(payload.get("reason") or ""),
                str(payload.get("rule_version") or RULE_VERSION),
                json.dumps(identity, ensure_ascii=False, sort_keys=True),
                json.dumps(payload.get("metrics") or {}, ensure_ascii=False, sort_keys=True),
                json.dumps(payload.get("interface") or {}, ensure_ascii=False, sort_keys=True),
                json.dumps(payload.get("exporter_module") or {}, ensure_ascii=False, sort_keys=True),
                payload.get("observed_at") or _now(),
                _now(),
            ),
        )
        hardware_sensors = payload.get("hardware_sensors") or []
        hardware_categories = payload.get("hardware_category_results") or []
        if hardware_categories:
            import hashlib

            from services.snmp_hardware_inventory_service import upsert_discovery_run

            observed_at = payload.get("observed_at") or _now()
            run_payload = {
                "device_id": str(device_id),
                "observed_at": str(observed_at),
                "rule_version": str(payload.get("hardware_rule_version") or payload.get("rule_version") or RULE_VERSION),
                "sensors": hardware_sensors,
                "categories": hardware_categories,
            }
            run_id = hashlib.sha256(
                json.dumps(run_payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            upsert_discovery_run(
                conn,
                str(device_id),
                run_id,
                str(payload.get("hardware_rule_version") or payload.get("rule_version") or RULE_VERSION),
                hardware_sensors,
                hardware_categories,
                observed_at,
                discovery_version=str(payload.get("hardware_discovery_version") or HARDWARE_DISCOVERY_VERSION),
                artifact_version=str(payload.get("hardware_artifact_version") or ""),
                started_at=payload.get("started_at") or observed_at,
            )
        conn.commit()
        with _discovery_cache_lock:
            _discovery_cache.pop(str(device_id), None)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _decode(row: Any) -> dict[str, Any]:
    def parse(value: Any, default: Any) -> Any:
        try:
            return json.loads(value or "")
        except (TypeError, ValueError):
            return default

    identity = parse(row.get("identity_json") if hasattr(row, "get") else row[11], {})
    return {
        "device_id": str(row.get("device_id") if hasattr(row, "get") else row[0]),
        "vendor": str(row.get("vendor") if hasattr(row, "get") else row[1] or ""),
        "platform": str(row.get("platform") if hasattr(row, "get") else row[2] or ""),
        "model": str(row.get("model") if hasattr(row, "get") else row[3] or ""),
        "software_version": str(row.get("software_version") if hasattr(row, "get") else row[4] or ""),
        "sys_object_id": str(row.get("sys_object_id") if hasattr(row, "get") else row[5] or ""),
        "sys_descr": str(row.get("sys_descr") if hasattr(row, "get") else row[6] or ""),
        "sys_name": str(row.get("sys_name") if hasattr(row, "get") else row[7] or ""),
        "status": str(row.get("status") if hasattr(row, "get") else row[8] or "pending"),
        "reason": str(row.get("reason") if hasattr(row, "get") else row[9] or ""),
        "rule_version": str(row.get("rule_version") if hasattr(row, "get") else row[10] or ""),
        "identity": identity,
        "adapter": identity.get("adapter") or {},
        "metrics": parse(row.get("metrics_json") if hasattr(row, "get") else row[12], {}),
        "interface": parse(row.get("interface_json") if hasattr(row, "get") else row[13], {}),
        "exporter_module": parse(row.get("exporter_json") if hasattr(row, "get") else row[14], {}),
        "observed_at": row.get("observed_at") if hasattr(row, "get") else row[15],
        "updated_at": row.get("updated_at") if hasattr(row, "get") else row[16],
    }


def load_discovery(device_id: str) -> dict[str, Any] | None:
    import time

    cache_key = str(device_id)
    now = time.monotonic()
    with _discovery_cache_lock:
        cached = _discovery_cache.get(cache_key)
        if cached and cached[0] > now:
            return deepcopy(cached[1]) if cached[1] else None
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM snmp_device_discoveries WHERE device_id = ?", (str(device_id),)).fetchone()
        value = _decode(row) if row else None
        with _discovery_cache_lock:
            _discovery_cache[cache_key] = (now + _DISCOVERY_CACHE_TTL_SECONDS, value)
        return deepcopy(value) if value else None
    finally:
        conn.close()


def load_discoveries(conn: Any, device_ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = [str(item).strip() for item in device_ids if str(item).strip()]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(f"SELECT * FROM snmp_device_discoveries WHERE device_id IN ({placeholders})", tuple(ids)).fetchall()
    return {item["device_id"]: _decode(item) for item in rows}
