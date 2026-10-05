"""SNMP probes for standard MIB and structured LibreNMS hardware definitions.

The probes retain complete table indexes and only claim discovery coverage when
the requested SNMP walks completed.  Measurement values are normalized before
they enter the hardware inventory; unsupported rule semantics stay explicit.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping

from database import get_db_connection
from services.snmp_hardware_normalization import (
    normalize_percentage,
    normalize_scaled_value,
    normalize_temperature_celsius,
)
from services.librenms_user_functions import (
    apply_librenms_user_func,
    supports_librenms_user_func,
)

logger = logging.getLogger(__name__)

_ENTITY_NAME_OID = "1.3.6.1.2.1.47.1.1.1.1.7"
_ENTITY_CLASS_OID = "1.3.6.1.2.1.47.1.1.1.1.5"
_ENTITY_DESCR_OID = "1.3.6.1.2.1.47.1.1.1.1.2"
_ENTITY_CONTAINED_IN_OID = "1.3.6.1.2.1.47.1.1.1.1.4"
_ENTITY_ALIAS_MAPPING_OID = "1.3.6.1.2.1.47.1.3.2.1.2"
_IF_NAME_OID = "1.3.6.1.2.1.31.1.1.1.1"
_IF_DESCR_OID = "1.3.6.1.2.1.2.2.1.2"
_IF_NAME_OID = "1.3.6.1.2.1.31.1.1.1.1"
_IF_DESCR_OID = "1.3.6.1.2.1.2.2.1.2"
_IF_ADMIN_STATUS_OID = "1.3.6.1.2.1.2.2.1.7"
_H3C_TRANSCEIVER_TABLE_OID = "1.3.6.1.4.1.25506.2.70.1.1.1"
_H3C_DOT11_AC_AP_COUNT_OID = "1.3.6.1.4.1.25506.2.75.1.1.2.21.0"
_H3C_DOT11_AC_CLIENT_COUNT_OID = "1.3.6.1.4.1.25506.2.75.1.1.3.6.0"
_H3C_DOT11_AC_MAC_MODE_OID = "1.3.6.1.4.1.25506.2.75.1.1.1.1.0"
_H3C_DOT11_AC_MAX_AP_COUNT_OID = "1.3.6.1.4.1.25506.2.75.1.1.1.2.0"
_H3C_DOT11_AC_MAX_STATION_COUNT_OID = "1.3.6.1.4.1.25506.2.75.1.1.1.3.0"
_H3C_DOT11_AC_AP_CONNECT_COUNT_OID = "1.3.6.1.4.1.25506.2.75.1.1.2.1.0"
_H3C_DOT11_AC_STATION_CONNECT_COUNT_OID = "1.3.6.1.4.1.25506.2.75.1.1.2.2.0"
_H3C_DOT11_AC_MASTER_AP_COUNT_OID = "1.3.6.1.4.1.25506.2.75.1.1.2.4.0"
_H3C_DOT11_AC_SLAVE_AP_COUNT_OID = "1.3.6.1.4.1.25506.2.75.1.1.2.5.0"
_H3C_DOT11_AC_AUTO_AP_COUNT_OID = "1.3.6.1.4.1.25506.2.75.1.1.2.6.0"
_H3C_DOT11_AC_PERSISTENT_AP_COUNT_OID = "1.3.6.1.4.1.25506.2.75.1.1.2.7.0"
_H3C_DOT11_AP_OBJECT_TABLE = "1.3.6.1.4.1.25506.2.75.2.1.2.1"
_H3C_DOT11_AP_RADIO_TABLE = "1.3.6.1.4.1.25506.2.75.2.1.3.1"
_H3C_DOT11_AP_BSS_TABLE = "1.3.6.1.4.1.25506.2.75.2.1.4.1"
_H3C_DOT11_AP_SYSTEM_LEGACY_TABLE = "1.3.6.1.4.1.25506.2.75.2.1.8.1"
_H3C_DOT11_AP_SYSTEM_TABLE = "1.3.6.1.4.1.25506.2.75.2.1.10.1"
_H3C_DOT11_AP_BRIEF_TABLE = "1.3.6.1.4.1.25506.2.75.2.1.12.1"
_H3C_DOT11_RADIO_RX_STATS = "1.3.6.1.4.1.25506.2.75.2.2.1.1"
_H3C_DOT11_RADIO_TX_STATS = "1.3.6.1.4.1.25506.2.75.2.2.2.1"
_H3C_DOT11_RADIO_ASSOC_STATS = "1.3.6.1.4.1.25506.2.75.2.2.8.1"
_H3C_DOT11_BSS_ASSOC_STATS = "1.3.6.1.4.1.25506.2.75.2.2.6.1"
_H3C_DOT11_STATION_TABLE = "1.3.6.1.4.1.25506.2.75.3.1.1.1"
_H3C_DOT11_STATION_IP_OID = f"{_H3C_DOT11_STATION_TABLE}.2"
_H3C_DOT11_STATION_USERNAME_OID = f"{_H3C_DOT11_STATION_TABLE}.3"
_H3C_DOT11_STATION_TX_RATE_SET_OID = f"{_H3C_DOT11_STATION_TABLE}.4"
_H3C_DOT11_STATION_SSID_OID = f"{_H3C_DOT11_STATION_TABLE}.12"
_H3C_ENTITY_CPU_USAGE_OID = "1.3.6.1.4.1.25506.2.6.1.1.1.1.6"
_H3C_ENTITY_MEM_USAGE_OID = "1.3.6.1.4.1.25506.2.6.1.1.1.1.8"
_H3C_ENTITY_MEM_SIZE_OID = "1.3.6.1.4.1.25506.2.6.1.1.1.1.10"
_H3C_COMWARE_PHP_SOURCE = "LibreNMS/OS/Comware.php"
_H3C_COMWARE_ADAPTER = "librenms_comware_processor_mempool"
_ENTITY_PHYSICAL_CLASS_MODULE = 9
_LIBRENMS_OS_CPU_OIDS = {
    "unifi_frogfoot": "1.3.6.1.4.1.10002.1.1.1.4.2.1.3.2",
    "viptela_idle": "1.3.6.1.4.1.41916.11.1.16.0",
    "smartax_cpu": "1.3.6.1.4.1.2011.2.6.7.1.1.2.1.5.0",
    "smartax_descr": "1.3.6.1.4.1.2011.2.6.7.1.1.2.1.7.0",
    "boss_cpu": "1.3.6.1.4.1.45.1.6.3.8.1.1.6",
    "aruba_instant_cpu": "1.3.6.1.4.1.14823.2.3.3.1.2.1.1.7",
}
_POWERCONNECT_VXWORKS_OID = "1.3.6.1.4.1.674.10895.5000.2.6132.1.1.1.1.4.4.0"
_POWERCONNECT_VXWORKS_55XX_OID = "1.3.6.1.4.1.674.10895.5000.2.6132.1.1.1.1.4.9.0"
_POWERCONNECT_NV_OID = "1.3.6.1.4.1.89.1.7.0"
_POWERCONNECT_55XX_SYSOBJECT_PREFIXES = (
    "1.3.6.1.4.1.674.10895.3020",
    "1.3.6.1.4.1.674.10895.3021",
    "1.3.6.1.4.1.674.10895.3028",
    "1.3.6.1.4.1.674.10895.3030",
    "1.3.6.1.4.1.674.10895.3031",
)
_POWERCONNECT_VXWORKS_9_SYSOBJECT_PREFIXES = (
    "1.3.6.1.4.1.674.10895.3024",
    "1.3.6.1.4.1.674.10895.3042",
    "1.3.6.1.4.1.674.10895.3053",
    "1.3.6.1.4.1.674.10895.3054",
    "1.3.6.1.4.1.674.10895.3056",
    "1.3.6.1.4.1.674.10895.3058",
    "1.3.6.1.4.1.674.10895.3065",
    "1.3.6.1.4.1.674.10895.3046",
    "1.3.6.1.4.1.674.10895.3063",
    "1.3.6.1.4.1.674.10895.3064",
    "1.3.6.1.4.1.674.10895.3066",
    "1.3.6.1.4.1.674.10895.3078",
    "1.3.6.1.4.1.674.10895.3079",
    "1.3.6.1.4.1.674.10895.3080",
    "1.3.6.1.4.1.674.10895.3081",
    "1.3.6.1.4.1.674.10895.3082",
    "1.3.6.1.4.1.674.10895.3083",
)
_VRP_CPU_USAGE_OID = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5"
_VRP_MEM_USAGE_OID = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7"
_VRP_MEM_SIZE_OID = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.9"
_VRP_MEM_SIZE_MEGA_OID = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.19"
_VRP_BOM_DESCRIPTION_OID = "1.3.6.1.4.1.2011.5.25.31.1.1.2.1.2"
_VRP_WLAN_AP_COUNT_OID = "1.3.6.1.4.1.2011.6.139.12.1.2.1.0"
_VRP_WLAN_SSID_CLIENTS_2G_OID = "1.3.6.1.4.1.2011.6.139.17.1.2.1.2"
_VRP_WLAN_SSID_CLIENTS_5G_OID = "1.3.6.1.4.1.2011.6.139.17.1.2.1.3"
_VRP_WLAN_AP_TABLE = "1.3.6.1.4.1.2011.6.139.13.3.3.1"
_VRP_WLAN_AP_SERIAL_OID = f"{_VRP_WLAN_AP_TABLE}.2"
_VRP_WLAN_AP_TYPE_OID = f"{_VRP_WLAN_AP_TABLE}.3"
_VRP_WLAN_AP_NAME_OID = f"{_VRP_WLAN_AP_TABLE}.4"
_VRP_WLAN_AP_MEMORY_USAGE_OID = f"{_VRP_WLAN_AP_TABLE}.40"
_VRP_WLAN_AP_CPU_USAGE_OID = f"{_VRP_WLAN_AP_TABLE}.41"
_VRP_WLAN_RADIO_TABLE = "1.3.6.1.4.1.2011.6.139.16.1.2.1"
_VRP_WLAN_RADIO_TYPE_OID = f"{_VRP_WLAN_RADIO_TABLE}.4"
_VRP_WLAN_RADIO_CHANNEL_OID = f"{_VRP_WLAN_RADIO_TABLE}.7"
_VRP_WLAN_RADIO_MAC_OID = f"{_VRP_WLAN_RADIO_TABLE}.20"
_VRP_WLAN_RADIO_UTILIZATION_OID = f"{_VRP_WLAN_RADIO_TABLE}.25"
_VRP_WLAN_RADIO_INTERFERENCE_OID = f"{_VRP_WLAN_RADIO_TABLE}.29"
_VRP_WLAN_RADIO_EIRP_OID = f"{_VRP_WLAN_RADIO_TABLE}.45"
_VRP_WLAN_VAP_CLIENTS_OID = "1.3.6.1.4.1.2011.6.139.17.1.1.1.9"
_HR_PROCESSOR_LOAD_OID = "1.3.6.1.2.1.25.3.3.1.2"
_HR_STORAGE_TYPE_OID = "1.3.6.1.2.1.25.2.3.1.2"
_HR_STORAGE_DESCR_OID = "1.3.6.1.2.1.25.2.3.1.3"
_HR_STORAGE_UNITS_OID = "1.3.6.1.2.1.25.2.3.1.4"
_HR_STORAGE_SIZE_OID = "1.3.6.1.2.1.25.2.3.1.5"
_HR_STORAGE_USED_OID = "1.3.6.1.2.1.25.2.3.1.6"
_HR_STORAGE_RAM_TYPE = "1.3.6.1.2.1.25.2.1.2"
_ENTITY_SENSOR_TYPE_OID = "1.3.6.1.2.1.99.1.1.1.1"
_ENTITY_SENSOR_SCALE_OID = "1.3.6.1.2.1.99.1.1.1.2"
_ENTITY_SENSOR_PRECISION_OID = "1.3.6.1.2.1.99.1.1.1.3"
_ENTITY_SENSOR_VALUE_OID = "1.3.6.1.2.1.99.1.1.1.4"
_ENTITY_SENSOR_STATUS_OID = "1.3.6.1.2.1.99.1.1.1.5"
_IOSXR_OPTICAL_DIRECTIONS = (
    re.compile(r"\bpower\s+(rx|tx)\b", re.IGNORECASE),
    re.compile(r"\b(rx|tx)\s+power\b", re.IGNORECASE),
    re.compile(r"\b(rx|tx)\s+lane\b", re.IGNORECASE),
)

_SENSOR_TYPE_TO_MEASUREMENT = {
    3: ("voltage", "voltage_volts"),
    4: ("voltage", "voltage_volts"),
    5: ("current", "current_amperes"),
    6: ("power_measurement", "power_watts"),
    8: ("temperature", "temperature_celsius"),
    10: ("fan", "fan_speed_rpm"),
    14: ("optical_power", "optical_power_dbm"),
}
_SENSOR_SCALE_EXPONENT = {
    1: -24, 2: -21, 3: -18, 4: -15, 5: -12, 6: -9, 7: -6, 8: -3, 9: 0,
    10: 3, 11: 6, 12: 9, 13: 12, 14: 15, 15: 18, 16: 21, 17: 24,
}
_GENERIC_STATE_VALUE = {
    "ok": 0, "normal": 0, "good": 0, "running": 0, "up": 0,
    "warning": 1, "warn": 1, "degraded": 1,
    "critical": 2, "error": 2, "failed": 2, "fail": 2, "down": 2,
    "unknown": 3, "unavailable": 3, "unsupported": 3,
}
_SUPPORTED_SKIP_OPERATORS = {
    "=", "==", "eq", "equals", "!=", "!==", "<", "<=", ">", ">=",
    "starts", "ends", "contains", "regex", "in_array", "not_starts",
    "not_ends", "not_contains", "not_regex", "not_in_array", "exists",
}


@dataclass(frozen=True)
class WalkResult:
    rows: list[tuple[str, str]]
    complete: bool
    reason: str = ""


def _clean_oid(value: Any) -> str:
    text = str(value or "").strip().strip(".")
    text = re.sub(r"\{[^}]*\}", "", text).strip().strip(".")
    text = re.sub(r"\{\{[^}]*\}\}", "", text).strip().strip(".")
    if not text or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", text):
        return ""
    return text


def _numeric_oid(value: Any) -> str:
    direct = _clean_oid(value)
    if direct:
        return direct
    text = str(value or "").strip()
    if "::" in text:
        text = text.rsplit("::", 1)[-1]
    text = re.sub(r"\{\{[^}]+\}\}", "", text)
    match = re.search(r"(?:^|[^0-9])(1(?:\.[0-9]+)+)(?:$|[^0-9])", text)
    return match.group(1) if match else ""


def _resolve_mib_symbol(
    conn: Any,
    token: Any,
    *,
    vendor: str = "",
    cache: dict[tuple[str, str], str] | None = None,
) -> str:
    raw = str(token or "").strip()
    if not raw:
        return ""
    cache_key = (raw.casefold(), str(vendor or "").strip().casefold())
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    numeric = _numeric_oid(raw)
    if numeric:
        if cache is not None:
            cache[cache_key] = numeric
        return numeric
    symbol = raw.rsplit("::", 1)[-1].strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", symbol):
        if cache is not None:
            cache[cache_key] = ""
        return ""
    try:
        rows = conn.execute(
            """
            SELECT n.oid, m.vendor, n.node_name
              FROM snmp_mib_nodes n
              JOIN snmp_mibs m ON m.id = n.mib_id
             WHERE m.is_active = 1 AND LOWER(n.node_name) = LOWER(?)
               AND TRIM(COALESCE(n.oid, '')) <> ''
             ORDER BY CASE WHEN LOWER(TRIM(COALESCE(m.vendor, ''))) = LOWER(?) THEN 0
                           WHEN LOWER(TRIM(COALESCE(m.vendor, ''))) = 'standard' THEN 1
                           ELSE 2 END,
                      m.name
             LIMIT 8
            """,
            (symbol, vendor),
        ).fetchall()
    except Exception:
        if cache is not None:
            cache[cache_key] = ""
        return ""
    if not rows:
        if cache is not None:
            cache[cache_key] = ""
        return ""
    resolved = _numeric_oid(rows[0][0])
    if cache is not None:
        cache[cache_key] = resolved
    return resolved


def _resolve_definition_oid(
    conn: Any,
    definition: Mapping[str, Any],
    *,
    vendor: str,
    cache: dict[tuple[str, str], str] | None = None,
) -> str:
    for candidate in (
        definition.get("numeric_oid_prefix"),
        definition.get("num_oid"),
        definition.get("value_oid"),
        definition.get("table_oid"),
    ):
        numeric = _numeric_oid(candidate)
        if numeric:
            return numeric
        resolved = _resolve_mib_symbol(conn, candidate, vendor=vendor, cache=cache)
        if resolved:
            return resolved
    return ""


async def _walk(
    ip: str,
    community: str,
    oid: str,
    port: int,
    version: str,
    *,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None = None,
) -> WalkResult:
    if not oid:
        return WalkResult([], False, "unsupported_oid")
    try:
        if walk_func is not None:
            rows = await walk_func(ip, community, oid, port, version)
        else:
            from services.snmp_service import _snmp_walk

            rows = await _snmp_walk(
                ip, community, oid, port, timeout=5, max_rows=2000,
                version=version, raise_on_error=True,
            )
        normalized: list[tuple[str, str]] = []
        for suffix, raw in rows or []:
            suffix_text = str(suffix or "").strip().strip(".")
            normalized.append((suffix_text, str(raw)))
        # The walker caps row counts.  Reaching its cap cannot establish full
        # table coverage, so absence retirement stays disabled for this run.
        return WalkResult(normalized, len(normalized) < 2000)
    except Exception as exc:
        partial = getattr(exc, "partial_results", []) or []
        return WalkResult(
            [(str(index).strip("."), str(raw)) for index, raw in partial],
            False,
            type(exc).__name__,
        )


async def _walk_many(
    ip: str,
    community: str,
    oids: set[str],
    port: int,
    version: str,
    *,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None = None,
) -> dict[str, WalkResult]:
    semaphore = asyncio.Semaphore(8)

    async def read(oid: str) -> tuple[str, WalkResult]:
        async with semaphore:
            return oid, await _walk(ip, community, oid, port, version, walk_func=walk_func)

    return dict(await asyncio.gather(*(read(oid) for oid in sorted(oids)))) if oids else {}


async def _get_many(
    ip: str,
    community: str,
    oids: set[str],
    port: int,
    version: str,
) -> dict[str, str | None]:
    if not oids:
        return {}
    from services.snmp_service import _snmp_get_versioned

    semaphore = asyncio.Semaphore(8)

    async def read(oid: str) -> tuple[str, str | None]:
        async with semaphore:
            try:
                value = await _snmp_get_versioned(ip, community, oid, port, version)
                return oid, str(value) if value is not None else None
            except Exception as exc:
                logger.debug("Hardware scalar GET %s failed: %s", oid, type(exc).__name__)
                return oid, None

    return dict(await asyncio.gather(*(read(oid) for oid in sorted(oids))))


def _row_map(result: WalkResult | None) -> dict[str, str]:
    return {suffix: raw for suffix, raw in (result.rows if result else [])}


def _number(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _index_parts(suffix: Any) -> list[int] | None:
    text = str(suffix or "").strip().strip(".")
    if not text or not re.fullmatch(r"\d+(?:\.\d+)*", text):
        return None
    return [int(item) for item in text.split(".")]


def _resolved_ent_physical_index(template: Any, suffix: Any) -> str:
    raw = str(template or "").strip()
    index_text = str(suffix or "").strip().strip(".")
    if re.fullmatch(r"\d+", raw):
        return raw
    parts = index_text.split(".") if index_text and re.fullmatch(r"\d+(?:\.\d+)*", index_text) else []
    match = re.fullmatch(r"\{\{\s*\$(index|subindex\d+)\s*\}\}", raw)
    if not match:
        return ""
    token = match.group(1)
    if token == "index":
        return index_text if re.fullmatch(r"\d+", index_text) else ""
    position = int(token.removeprefix("subindex"))
    return parts[position] if position < len(parts) else ""


def _apply_ent_physical_metadata(
    sensor: dict[str, Any],
    definition: Mapping[str, Any],
    suffix: str,
) -> None:
    raw_template = definition.get("entPhysicalIndex")
    measured = str(definition.get("entPhysicalIndex_measured") or "").strip()
    resolved = _resolved_ent_physical_index(raw_template, suffix)
    metadata = sensor.get("metadata") if isinstance(sensor.get("metadata"), dict) else {}
    if raw_template not in (None, ""):
        metadata["ent_physical_index_template"] = raw_template
    if measured:
        metadata["ent_physical_index_measured"] = measured
    if resolved:
        metadata["ent_physical_index"] = resolved
        index_labels = sensor.get("index_labels") if isinstance(sensor.get("index_labels"), dict) else {}
        index_labels["ent_physical_index"] = resolved
        sensor["index_labels"] = index_labels
    sensor["metadata"] = metadata


def _name_at(entity_names: Mapping[str, str], index: list[int], fallback: str) -> str:
    suffix = ".".join(str(item) for item in index)
    return (entity_names.get(suffix) or entity_names.get(str(index[-1])) or fallback)[:300]


def _entity_if_mapping(
    index: str,
    *,
    entity_names: Mapping[str, str],
    entity_descriptions: Mapping[str, str],
    entity_classes: Mapping[str, str],
    contained_in: Mapping[str, str],
    aliases: Mapping[str, str],
    if_names: Mapping[str, str],
    if_descriptions: Mapping[str, str],
) -> tuple[str, int] | None:
    """Follow ENTITY-MIB containment and alias pointers to a real ifIndex."""
    reverse = {
        str(name).strip(): int(if_index)
        for if_index, name in if_names.items()
        if str(if_index).isdigit() and str(name).strip()
    }
    current = str(index)
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        name = str(entity_names.get(current, entity_names.get(f"{current}.0", "")) or "").strip()
        descr = str(entity_descriptions.get(current, entity_descriptions.get(f"{current}.0", "")) or "").strip()
        for candidate in (name, descr):
            if candidate in reverse:
                if_index = reverse[candidate]
                return str(if_names.get(str(if_index)) or if_descriptions.get(str(if_index)) or candidate), if_index

        entity_class = str(entity_classes.get(current, entity_classes.get(f"{current}.0", "")) or "").strip().casefold()
        class_number = _number(entity_class)
        if entity_class == "port" or (class_number is not None and int(class_number) == 10):
            alias = str(aliases.get(current, aliases.get(f"{current}.0", "")) or "").strip().lstrip(".")
            match = re.search(r"ifindex\.(\d+)", alias, re.IGNORECASE)
            if match is None:
                match = re.fullmatch(r"1\.3\.6\.1\.2\.1\.2\.2\.1\.1\.(\d+)", alias)
            if match and int(match.group(1)) > 0:
                if_index = int(match.group(1))
                interface = str(if_names.get(str(if_index)) or if_descriptions.get(str(if_index)) or "").strip()
                if interface:
                    return interface, if_index

        parent = str(contained_in.get(current, contained_in.get(f"{current}.0", "")) or "").strip().lstrip(".")
        if not parent.isdigit() or int(parent) == 0:
            break
        current = parent

    text = " ".join((
        str(entity_names.get(str(index), "") or ""),
        str(entity_descriptions.get(str(index), "") or ""),
    )).strip()
    candidates = [(str(name).strip(), int(if_index)) for if_index, name in if_names.items() if str(if_index).isdigit() and str(name).strip()]
    matches = [item for item in candidates if re.search(rf"(?<![\w/.-]){re.escape(item[0])}(?![\w/.-])", text)]
    if len(matches) == 1:
        if_name, if_index = matches[0]
        return if_name, if_index
    return None


def _category_result(
    source_type: str,
    component_class: str,
    *,
    status: str,
    complete: bool = False,
    reason_code: str = "",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "component_class": component_class,
        "status": status,
        "coverage_complete": bool(complete and status in {"success", "not_found"}),
        "reason_code": reason_code,
        "reason": reason,
    }


def _direct_plan(oid: str, suffix: str, *, factor: float = 1.0, offset: float = 0.0) -> dict[str, Any]:
    return {
        "kind": "direct",
        "oid": oid,
        "index": suffix,
        "factor": factor,
        "offset": offset,
    }


def _sensor(
    *,
    source_type: str,
    source_id: str,
    component_class: str,
    measurement_type: str,
    oid: str,
    suffix: str,
    raw_value: Any,
    value: float | None,
    unit: str,
    sensor_name: str,
    entity_name: str = "",
    group_name: str = "",
    quality: str = "good",
    states: Any = None,
    thresholds: Any = None,
    presence_status: str = "present",
    metadata: Mapping[str, Any] | None = None,
    poll_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    index = _index_parts(suffix)
    if index is None:
        return None
    info = dict(metadata or {})
    if poll_plan:
        info["poll_plan"] = dict(poll_plan)
    return {
        "source_type": source_type,
        "source_id": source_id,
        "component_class": component_class,
        "measurement_type": measurement_type,
        "index": index,
        "index_labels": {"index": suffix},
        "oid": oid,
        "unit": unit,
        "scale": 1.0,
        "offset": 0.0,
        "states": states or {},
        "thresholds": thresholds or {},
        "metadata": info,
        "sensor_name": sensor_name,
        "entity_name": entity_name,
        "group_name": group_name,
        "presence_status": presence_status,
        "value": value,
        "raw_value": str(raw_value)[:500] if raw_value is not None else None,
        "quality": quality,
    }


async def probe_standard_hardware(
    ip: str,
    community: str,
    port: int,
    *,
    version: str = "2c",
    cisco_iosxr: bool = False,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None = None,
) -> dict[str, Any]:
    """Discover HOST-RESOURCES and ENTITY-SENSOR hardware without vendor lists."""
    oids = {
        _ENTITY_NAME_OID, _ENTITY_CLASS_OID, _ENTITY_DESCR_OID,
        _ENTITY_CONTAINED_IN_OID, _ENTITY_ALIAS_MAPPING_OID, _IF_NAME_OID, _IF_DESCR_OID,
        _HR_PROCESSOR_LOAD_OID, _HR_STORAGE_TYPE_OID, _HR_STORAGE_DESCR_OID,
        _HR_STORAGE_UNITS_OID, _HR_STORAGE_SIZE_OID, _HR_STORAGE_USED_OID,
        _ENTITY_SENSOR_TYPE_OID, _ENTITY_SENSOR_SCALE_OID, _ENTITY_SENSOR_PRECISION_OID,
        _ENTITY_SENSOR_VALUE_OID, _ENTITY_SENSOR_STATUS_OID,
    }
    reads = await _walk_many(ip, community, oids, port, version, walk_func=walk_func)
    entity_names = _row_map(reads.get(_ENTITY_NAME_OID))
    entity_classes = _row_map(reads.get(_ENTITY_CLASS_OID))
    entity_descrs = _row_map(reads.get(_ENTITY_DESCR_OID))
    entity_contained_in = _row_map(reads.get(_ENTITY_CONTAINED_IN_OID))
    entity_aliases = _row_map(reads.get(_ENTITY_ALIAS_MAPPING_OID))
    if_names = _row_map(reads.get(_IF_NAME_OID))
    if_descriptions = _row_map(reads.get(_IF_DESCR_OID))
    sensors: list[dict[str, Any]] = []
    category_results: list[dict[str, Any]] = []

    # HOST-RESOURCES processor load is an already-percent value per processor.
    processor_read = reads[_HR_PROCESSOR_LOAD_OID]
    processor_rows = 0
    for suffix, raw in processor_read.rows:
        value = _number(raw)
        if value is None:
            continue
        entity_name = _name_at(entity_names, _index_parts(suffix) or [], f"Processor {suffix}")
        sensor = _sensor(
            source_type="standard_mib", source_id="HOST-RESOURCES-MIB::hrProcessorLoad",
            component_class="processor", measurement_type="cpu_usage_percent",
            oid=_HR_PROCESSOR_LOAD_OID, suffix=suffix, raw_value=raw, value=value,
            unit="percent", sensor_name=entity_name, entity_name=entity_name,
            group_name="processor", metadata={"mib": "HOST-RESOURCES-MIB", "scale_source": "already_percent"},
            poll_plan=_direct_plan(_HR_PROCESSOR_LOAD_OID, suffix),
        )
        if sensor:
            sensors.append(sensor)
            processor_rows += 1
    category_results.append(_category_result(
        "standard_mib", "processor",
        status="success" if processor_rows and processor_read.complete else "partial" if processor_rows else "not_found" if processor_read.complete else "failed",
        complete=bool(processor_rows and processor_read.complete),
        reason_code="hr_processor_load", reason="HOST-RESOURCES hrProcessorLoad table",
    ))

    # HOST-RESOURCES storage has many non-RAM rows. Only hrStorageRam is a
    # valid denominator for this memory pool family; disks and swap are excluded.
    memory_oids = (
        _HR_STORAGE_TYPE_OID, _HR_STORAGE_DESCR_OID, _HR_STORAGE_UNITS_OID,
        _HR_STORAGE_SIZE_OID, _HR_STORAGE_USED_OID,
    )
    memory_maps = {oid: _row_map(reads.get(oid)) for oid in memory_oids}
    memory_complete = all(reads[oid].complete for oid in memory_oids)
    storage_rows = 0
    for suffix, storage_type in memory_maps[_HR_STORAGE_TYPE_OID].items():
        if _numeric_oid(storage_type) != _HR_STORAGE_RAM_TYPE:
            continue
        units = _number(memory_maps[_HR_STORAGE_UNITS_OID].get(suffix))
        size = _number(memory_maps[_HR_STORAGE_SIZE_OID].get(suffix))
        used = _number(memory_maps[_HR_STORAGE_USED_OID].get(suffix))
        if units is None or units <= 0 or size is None or size <= 0 or used is None:
            continue
        descr = memory_maps[_HR_STORAGE_DESCR_OID].get(suffix, "Physical Memory")[:300]
        index = _index_parts(suffix)
        if index is None:
            continue
        total_bytes = size * units
        used_bytes = used * units
        total_oid_map = {"oid": _HR_STORAGE_SIZE_OID, "index": suffix, "factor": units, "offset": 0.0}
        used_oid_map = {"oid": _HR_STORAGE_USED_OID, "index": suffix, "factor": units, "offset": 0.0}
        base_metadata = {
            "mib": "HOST-RESOURCES-MIB",
            "storage_type": "hrStorageRam",
            "allocation_unit_bytes": units,
            "poll_plan": {"kind": "memory_component", "used": used_oid_map, "total": total_oid_map},
        }
        for measurement, oid, raw, value, plan in (
            ("memory_used_bytes", _HR_STORAGE_USED_OID, memory_maps[_HR_STORAGE_USED_OID][suffix], used_bytes, _direct_plan(_HR_STORAGE_USED_OID, suffix, factor=units)),
            ("memory_total_bytes", _HR_STORAGE_SIZE_OID, memory_maps[_HR_STORAGE_SIZE_OID][suffix], total_bytes, _direct_plan(_HR_STORAGE_SIZE_OID, suffix, factor=units)),
            ("memory_usage_percent", _HR_STORAGE_USED_OID, memory_maps[_HR_STORAGE_USED_OID][suffix], (100.0 * used_bytes / total_bytes), {"kind": "memory_ratio", "used": used_oid_map, "total": total_oid_map}),
        ):
            sensor = _sensor(
                source_type="standard_mib", source_id=f"HOST-RESOURCES-MIB::{measurement}",
                component_class="memory_pool", measurement_type=measurement,
                oid=oid, suffix=suffix, raw_value=raw, value=value,
                unit="bytes" if measurement != "memory_usage_percent" else "percent",
                sensor_name=descr, entity_name=descr, group_name="physical_memory",
                metadata=base_metadata, poll_plan=plan,
            )
            if sensor:
                sensors.append(sensor)
        storage_rows += 1
    memory_reads_complete = memory_complete and all(not reads[oid].reason for oid in memory_oids)
    category_results.append(_category_result(
        "standard_mib", "memory_pool",
        status="success" if storage_rows and memory_reads_complete else "partial" if storage_rows else "not_found" if memory_reads_complete else "failed",
        complete=bool(storage_rows and memory_reads_complete),
        reason_code="hr_storage_ram", reason="HOST-RESOURCES hrStorageRam only; storage and swap rows are excluded",
    ))

    # ENTITY-SENSOR units are reconstructed from type, scale and precision.
    entity_reads = [
        reads[_ENTITY_SENSOR_TYPE_OID], reads[_ENTITY_SENSOR_SCALE_OID],
        reads[_ENTITY_SENSOR_PRECISION_OID], reads[_ENTITY_SENSOR_VALUE_OID],
        reads[_ENTITY_SENSOR_STATUS_OID],
    ]
    sensor_maps = {oid: _row_map(reads.get(oid)) for oid in (
        _ENTITY_SENSOR_TYPE_OID, _ENTITY_SENSOR_SCALE_OID, _ENTITY_SENSOR_PRECISION_OID,
        _ENTITY_SENSOR_VALUE_OID, _ENTITY_SENSOR_STATUS_OID,
    )}
    entity_sensor_rows = 0
    unsupported_entity_rows = 0
    for suffix, raw_value in sensor_maps[_ENTITY_SENSOR_VALUE_OID].items():
        sensor_type_value = _number(sensor_maps[_ENTITY_SENSOR_TYPE_OID].get(suffix))
        scale_value = _number(sensor_maps[_ENTITY_SENSOR_SCALE_OID].get(suffix))
        precision_value = _number(sensor_maps[_ENTITY_SENSOR_PRECISION_OID].get(suffix))
        oper_status = _number(sensor_maps[_ENTITY_SENSOR_STATUS_OID].get(suffix))
        numeric_raw = _number(raw_value)
        if (sensor_type_value is None or scale_value is None or precision_value is None
                or numeric_raw is None or int(sensor_type_value) not in _SENSOR_TYPE_TO_MEASUREMENT
                or int(scale_value) not in _SENSOR_SCALE_EXPONENT):
            unsupported_entity_rows += 1
            continue
        sensor_type = int(sensor_type_value)
        component_class, measurement_type = _SENSOR_TYPE_TO_MEASUREMENT[sensor_type]
        precision = int(precision_value)
        if not -8 <= precision <= 9:
            unsupported_entity_rows += 1
            continue
        # RFC 3433 defines precision as decimal places represented in the
        # fixed-point value, so it divides the scaled value by 10**precision.
        factor = 10.0 ** (_SENSOR_SCALE_EXPONENT[int(scale_value)] - precision)
        offset = 0.0
        value = numeric_raw * factor + offset
        if oper_status is None or int(oper_status) != 1:
            quality = "missing"
        else:
            quality = "good"
        index = _index_parts(suffix)
        if index is None:
            unsupported_entity_rows += 1
            continue
        entity_name = _name_at(entity_names, index, f"Entity sensor {suffix}")
        optical_direction = ""
        if cisco_iosxr and sensor_type == 6:
            for pattern in _IOSXR_OPTICAL_DIRECTIONS:
                direction_match = pattern.search(entity_name)
                if direction_match:
                    optical_direction = direction_match.group(1).casefold()
                    break
            if optical_direction:
                component_class = "optical_power"
                measurement_type = "optical_power_dbm"
                if quality == "good":
                    watts = value
                    value = 10.0 * math.log10(watts * 1000.0) if watts is not None and watts > 0 else None
                    if value is None or not math.isfinite(value):
                        quality = "invalid"
        entity_class = entity_classes.get(suffix, "")
        group = {
            "6": "power_supply", "7": "fan", "8": "sensor",
            "9": "module", "10": "port", "11": "stack",
        }.get(entity_class, "hardware")
        if optical_direction:
            group = "transceiver"
        poll_plan = {
            "kind": "entity_sensor", "value_oid": _ENTITY_SENSOR_VALUE_OID,
            "type_oid": _ENTITY_SENSOR_TYPE_OID, "scale_oid": _ENTITY_SENSOR_SCALE_OID,
            "precision_oid": _ENTITY_SENSOR_PRECISION_OID, "status_oid": _ENTITY_SENSOR_STATUS_OID,
            "index": suffix, "expected_type": sensor_type,
        }
        metadata = {
            "mib": "ENTITY-SENSOR-MIB", "entity_class": entity_class,
            "sensor_type": sensor_type, "sensor_scale": int(scale_value),
            "sensor_precision": precision, "oper_status": oper_status,
        }
        if optical_direction:
            poll_plan["value_transform"] = "iosxr_watts_to_dbm"
            metadata.update({
                "adapter": "librenms_cisco_iosxr_entity_sensor",
                "optical_direction": optical_direction,
                "source_path": "includes/discovery/sensors/cisco-entity-sensor.inc.php",
            })
        port_mapping = _entity_if_mapping(
            suffix,
            entity_names=entity_names,
            entity_descriptions=entity_descrs,
            entity_classes=entity_classes,
            contained_in=entity_contained_in,
            aliases=entity_aliases,
            if_names=if_names,
            if_descriptions=if_descriptions,
        )
        if port_mapping:
            metadata["ent_physical_index"] = suffix
            metadata["ent_physical_index_measured"] = "ports"
        sensor = _sensor(
            source_type="standard_mib", source_id="ENTITY-SENSOR-MIB::entPhySensorValue",
            component_class=component_class, measurement_type=measurement_type,
            oid=_ENTITY_SENSOR_VALUE_OID, suffix=suffix, raw_value=raw_value,
            value=value if quality == "good" else None,
            unit={"temperature_celsius": "celsius", "fan_speed_rpm": "rpm", "power_watts": "watts", "voltage_volts": "volts", "current_amperes": "amperes", "optical_power_dbm": "dBm"}[measurement_type],
            sensor_name=entity_name, entity_name=entity_name, group_name=group,
            quality=quality,
            metadata=metadata,
            poll_plan=poll_plan,
        )
        if sensor:
            if port_mapping:
                sensor["index_labels"].update({"if_name": port_mapping[0], "if_index": str(port_mapping[1]), "ent_physical_index": suffix})
            sensors.append(sensor)
            entity_sensor_rows += 1
    entity_reads_complete = all(item.complete and not item.reason for item in entity_reads)
    category_results.append(_category_result(
        "standard_mib", "environmental_sensor",
        status="success" if entity_sensor_rows and entity_reads_complete and not unsupported_entity_rows else "partial" if entity_sensor_rows or unsupported_entity_rows else "not_found" if entity_reads_complete else "failed",
        complete=bool(entity_sensor_rows and entity_reads_complete and not unsupported_entity_rows),
        reason_code="entity_sensor", reason="ENTITY-SENSOR values joined with type, scale, precision and operStatus",
    ))

    return {"sensors": sensors, "category_results": category_results}


def _numeric_transform(definition: Mapping[str, Any]) -> tuple[float, float] | None:
    raw = definition.get("raw") if isinstance(definition.get("raw"), Mapping) else definition
    scale = _number(definition.get("scale") if definition.get("scale") is not None else raw.get("scale", 1))
    multiplier = _number(definition.get("multiplier") if definition.get("multiplier") is not None else raw.get("multiplier", 1))
    divisor = _number(definition.get("divisor") if definition.get("divisor") is not None else raw.get("divisor", 1))
    offset = _number(definition.get("offset") if definition.get("offset") is not None else raw.get("offset", 0))
    if scale is None or multiplier is None or divisor is None or offset is None or divisor == 0:
        return None
    factor = scale * multiplier / divisor
    if str(definition.get("source_module") or "").casefold() == "processors":
        raw_precision = definition.get("precision")
        precision = _number(raw_precision)
        if precision is None:
            if raw_precision not in (None, ""):
                return None
            precision = 1.0
        if precision == 0:
            # LibreNMS Processor::fromYaml treats an empty/zero precision as 1.
            precision = 1.0
        if precision < 0:
            # A negative LibreNMS processor precision means the OID reports
            # idle CPU. Keep the normalization scale positive; complement the
            # scaled value at discovery and poll time.
            factor /= abs(precision)
            offset /= abs(precision)
        elif precision > 1:
            factor /= precision
            offset /= precision
    return factor, offset


def _explicit_cpu_window(definition: Mapping[str, Any]) -> str:
    raw = definition.get("raw") if isinstance(definition.get("raw"), Mapping) else {}
    value = definition.get("window") or definition.get("sample_window") or raw.get("window") or raw.get("sample_window")
    if value in (None, ""):
        return "unknown"
    token = re.sub(r"\s+", "", str(value)).casefold()
    match = re.fullmatch(r"(\d+)(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)", token)
    if match:
        unit = match.group(2)
        unit_key = "s" if unit.startswith("s") else "m" if unit.startswith("m") else "h"
        return f"{int(match.group(1))}{unit_key}"
    return "unknown"


def _render_librenms_index_template(
    template: Any,
    suffix: str,
    raw_value: Any,
    mib_values: Mapping[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """Expand supported LibreNMS index/value/MIB placeholders."""
    source = str(template or "")
    parts = suffix.split(".") if re.fullmatch(r"\d+(?:\.\d+)*", suffix or "") else []
    unresolved: list[str] = []

    def replace(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        if expression == "$index":
            return suffix
        if expression == "$value":
            return str(raw_value) if raw_value is not None else ""
        subindex = re.fullmatch(r"\$subindex(\d+)", expression)
        if subindex:
            position = int(subindex.group(1))
            return parts[position] if position < len(parts) else ""
        if mib_values is not None and expression in mib_values:
            value = mib_values[expression]
            return str(value) if value is not None else ""
        unresolved.append(expression)
        return match.group(0)

    return re.sub(r"\{\{\s*(.*?)\s*\}\}", replace, source).strip(), unresolved


def _template_mib_values(
    definition: Mapping[str, Any],
    suffix: str,
    rows_by_oid: Mapping[str, Mapping[str, str]],
) -> dict[str, str]:
    template_oids = definition.get("_template_oids") if isinstance(definition.get("_template_oids"), Mapping) else {}
    values: dict[str, str] = {}
    for token, oid in template_oids.items():
        rows = rows_by_oid.get(str(oid), {})
        fixed_index = re.fullmatch(
            r"[A-Za-z0-9_-]+::[A-Za-z0-9_-]+:([0-9]+(?:\.[0-9]+)*)",
            str(token),
        )
        if fixed_index:
            value = rows.get(fixed_index.group(1))
        else:
            value = rows.get(suffix)
            if value is None and suffix.isdigit():
                value = rows.get(f"{suffix}.0")
        if value is not None:
            values[str(token)] = str(value)
    return values


def _memory_relation_definition(value: Any) -> dict[str, Any] | None:
    """Normalize a mempool relation value without confusing constants for OIDs."""
    if isinstance(value, Mapping):
        kind = str(value.get("kind") or "").casefold()
        if kind == "constant":
            number = _number(value.get("value"))
            return {"kind": "constant", "value": number} if number is not None else {"kind": "unsupported"}
        if kind == "oid":
            token = str(value.get("value") or "").strip()
            return {"kind": "oid", "value": token} if token else None
        if kind == "unsupported":
            return {"kind": "unsupported"}
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return {"kind": "unsupported"}
    if isinstance(value, (int, float)):
        number = _number(value)
        return {"kind": "constant", "value": number} if number is not None else {"kind": "unsupported"}
    token = str(value).strip()
    if not token:
        return None
    if token.startswith(".") or re.fullmatch(r"\d+(?:\.\d+){2,}", token):
        return {"kind": "oid", "value": token}
    number = _number(token)
    if number is not None:
        return {"kind": "constant", "value": number}
    return {"kind": "oid", "value": token}


def _memory_relations_for_definition(definition: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    memory = definition.get("memory") if isinstance(definition.get("memory"), Mapping) else {}
    typed = memory.get("relations") if isinstance(memory.get("relations"), Mapping) else {}
    raw = definition.get("raw") if isinstance(definition.get("raw"), Mapping) else {}
    relations: dict[str, dict[str, Any]] = {}
    for name in ("used", "total", "free", "percent_used"):
        source = typed.get(name)
        if source is None:
            source = memory.get(f"{name}_oid")
        if source is None:
            source = raw.get(name)
        relation = _memory_relation_definition(source)
        if relation is not None:
            relations[name] = relation
    return relations


def _mempool_targets(relations: Mapping[str, Any]) -> set[str]:
    """Return the byte/percent measurements derivable from configured inputs."""
    roles = {str(name) for name, value in relations.items() if isinstance(value, Mapping) and value.get("kind") in {"oid", "constant"}}
    targets: set[str] = set()
    # LibreNMS accepts a lone percent relation, but byte relations need enough
    # information for fillUsage to build a usable pool (two of used/free/total/
    # percent_used). Do not publish a half-defined pool for a lone byte value.
    if roles == {"percent_used"}:
        return {"percent_used"}
    if len(roles) < 2:
        return targets
    if "percent_used" in roles:
        targets.add("percent_used")
    if "used" in roles and ("total" in roles or "free" in roles or "percent_used" in roles):
        targets.add("used")
    if "total" in roles and ("used" in roles or "free" in roles or "percent_used" in roles):
        targets.add("total")
    if {"total", "percent_used"} <= roles or {"free", "percent_used"} <= roles or {"total", "free"} <= roles:
        targets.add("used")
    if {"used", "percent_used"} <= roles or {"free", "percent_used"} <= roles or {"used", "free"} <= roles:
        targets.add("total")
    if {"used", "total"} <= roles or {"used", "free"} <= roles or {"total", "free"} <= roles:
        targets.add("percent_used")
    return targets


def _mempool_metric_values(
    relation_values: Mapping[str, Any],
    *,
    factor: float,
    offset: float,
    precision: float,
    unit_factor: float | None,
) -> dict[str, float | None]:
    """Normalize and infer current mempool quantities from available relations."""
    quantities: dict[str, float | None] = {name: None for name in ("used", "total", "free")}
    byte_values: dict[str, float | None] = {name: None for name in ("used", "total", "free")}
    for name in quantities:
        raw_number = _number(relation_values.get(name))
        if raw_number is None:
            continue
        normalized = normalize_scaled_value(raw_number, factor, offset)
        quantities[name] = normalized
        if normalized is not None and unit_factor is not None:
            byte_values[name] = normalized * precision * unit_factor

    percent_raw = _number(relation_values.get("percent_used"))
    percent = normalize_percentage(normalize_scaled_value(percent_raw, factor, offset)) if percent_raw is not None else None

    # Match LibreNMS fillUsage's two-of-four inference while keeping the
    # discovery and polling values derived from the current SNMP sample.
    if percent is not None:
        ratio = percent / 100.0
        if quantities["total"] is not None:
            quantities["used"] = quantities["used"] if quantities["used"] is not None else quantities["total"] * ratio
            quantities["free"] = quantities["free"] if quantities["free"] is not None else quantities["total"] - quantities["used"]
            if byte_values["total"] is not None:
                byte_values["used"] = byte_values["used"] if byte_values["used"] is not None else byte_values["total"] * ratio
                byte_values["free"] = byte_values["free"] if byte_values["free"] is not None else byte_values["total"] - byte_values["used"]
        elif quantities["used"] is not None and ratio > 0:
            quantities["total"] = quantities["used"] / ratio
            quantities["free"] = quantities["total"] - quantities["used"]
            if byte_values["used"] is not None:
                byte_values["total"] = byte_values["used"] / ratio
                byte_values["free"] = byte_values["total"] - byte_values["used"]
        elif quantities["free"] is not None and ratio < 1:
            quantities["total"] = quantities["free"] / (1.0 - ratio)
            quantities["used"] = quantities["total"] - quantities["free"]
            if byte_values["free"] is not None:
                byte_values["total"] = byte_values["free"] / (1.0 - ratio)
                byte_values["used"] = byte_values["total"] - byte_values["free"]

    if quantities["used"] is not None and quantities["total"] is not None and quantities["total"] > 0:
        quantities["free"] = quantities["free"] if quantities["free"] is not None else quantities["total"] - quantities["used"]
        if percent is None:
            percent = normalize_percentage(100.0 * quantities["used"] / quantities["total"])
        if byte_values["used"] is not None and byte_values["total"] is not None:
            byte_values["free"] = byte_values["free"] if byte_values["free"] is not None else byte_values["total"] - byte_values["used"]
    elif quantities["used"] is not None and quantities["free"] is not None:
        quantities["total"] = quantities["used"] + quantities["free"]
        if percent is None and quantities["total"] > 0:
            percent = normalize_percentage(100.0 * quantities["used"] / quantities["total"])
        if byte_values["used"] is not None and byte_values["free"] is not None:
            byte_values["total"] = byte_values["used"] + byte_values["free"]
    elif quantities["total"] is not None and quantities["free"] is not None:
        quantities["used"] = quantities["total"] - quantities["free"]
        if percent is None and quantities["total"] > 0:
            percent = normalize_percentage(100.0 * quantities["used"] / quantities["total"])
        if byte_values["total"] is not None and byte_values["free"] is not None:
            byte_values["used"] = byte_values["total"] - byte_values["free"]

    return {
        "used": byte_values["used"],
        "total": byte_values["total"],
        "percent_used": percent,
    }


def _mempool_explicit_index(definition: Mapping[str, Any]) -> str:
    raw = definition.get("raw") if isinstance(definition.get("raw"), Mapping) else {}
    value = definition.get("index") if definition.get("index") is not None else raw.get("index")
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        number = _number(value)
        return str(int(number)) if number is not None and number.is_integer() else ""
    token = str(value).strip().strip(".")
    return token if re.fullmatch(r"\d+(?:\.\d+)*", token) else ""


def _mempool_precision(definition: Mapping[str, Any]) -> tuple[float, bool]:
    raw_precision = definition.get("precision")
    if raw_precision in (None, "", 0, 0.0):
        return 1.0, True
    precision = _number(raw_precision)
    return (precision, precision > 0) if precision is not None else (1.0, False)


def _generic_state_code(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or not float(value).is_integer():
            return None
        code = int(value)
        return code if code in {0, 1, 2, 3} else None
    token = str(value or "").strip().casefold()
    if token in _GENERIC_STATE_VALUE:
        return _GENERIC_STATE_VALUE[token]
    if token in {"0", "1", "2", "3"}:
        return int(token)
    return None


def _mapped_state(raw_value: Any, states: Any) -> tuple[float | None, dict[str, int], str]:
    mapping: dict[str, int] = {}
    if isinstance(states, list):
        for item in states:
            if not isinstance(item, Mapping):
                continue
            raw = item.get("value")
            generic_code = _generic_state_code(item.get("generic"))
            if raw is not None and generic_code is not None:
                mapping[str(raw)] = generic_code
    elif isinstance(states, Mapping):
        for raw, generic_value in states.items():
            generic_code = _generic_state_code(generic_value)
            if generic_code is not None:
                mapping[str(raw)] = generic_code
    value = next(
        (generic for raw, generic in mapping.items() if _skip_values_equal(raw_value, raw)),
        None,
    )
    return (float(value) if value is not None else None), mapping, "good" if value is not None else "unsupported_mapping"


def _state_description(raw_value: Any, states: Any) -> str:
    if isinstance(states, list):
        for item in states:
            if not isinstance(item, Mapping) or item.get("value") is None:
                continue
            if _skip_values_equal(raw_value, item.get("value")):
                description = str(item.get("descr") or item.get("description") or "").strip()
                return description[:120]
    elif isinstance(states, Mapping):
        item = next(
            (item for raw, item in states.items() if _skip_values_equal(raw_value, raw)),
            None,
        )
        if isinstance(item, Mapping):
            return str(item.get("descr") or item.get("description") or "").strip()[:120]
    return ""


def _state_presence(raw_value: Any, states: Any) -> str | None:
    description = re.sub(r"[\s_-]+", " ", _state_description(raw_value, states).casefold()).strip()
    if not description:
        return None
    if any(token in description for token in ("not install", "not present", "not installed", "absent", "uninstalled")):
        return "not_present"
    if description in {"active", "installed", "present", "online", "running", "normal", "ok"}:
        return "present"
    return None


def _skip_value(
    raw_value: Any,
    conditions: Any,
    *,
    condition_values: Mapping[str, Any] | None = None,
) -> bool | None:
    """Return True for a matching skip, False for no match, None if unsupported."""
    if conditions is None or conditions == []:
        return False
    values = conditions if isinstance(conditions, list) else [conditions]
    for item in values:
        if isinstance(item, Mapping):
            op = str(item.get("op") or "!=").strip().casefold()
            if op not in _SUPPORTED_SKIP_OPERATORS:
                return None
            if item.get("device"):
                if "_device_value" not in item:
                    # The identity field was absent or unsupported. Do not
                    # fall back to comparing a device selector to the sensor.
                    return None
                actual = item.get("_device_value")
            elif item.get("oid"):
                condition_oid = str(item.get("_oid") or "")
                if not condition_oid:
                    return None
                if item.get("_index"):
                    if condition_values is None or "__index__" not in condition_values:
                        return None
                    actual = condition_values["__index__"]
                else:
                    if condition_values is None or condition_oid not in condition_values:
                        return None
                    actual = condition_values[condition_oid]
            else:
                actual = raw_value
            expected = item.get("value")
            if op in {"in_array", "not_in_array"} and isinstance(item.get("values"), list):
                expected = item.get("values")
            matched = _compare_skip_values(actual, expected, op)
            if matched is None:
                return None
            if matched:
                return True
        elif _skip_values_equal(raw_value, item):
            return True
    return False


def _skip_values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return _skip_truthy(left) == _skip_truthy(right)
    if left is None or right is None:
        if left is None and right is None:
            return True
        other = right if left is None else left
        return other is False or other == 0 or other == 0.0 or other == ""
    left_number = _number(left)
    right_number = _number(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return str(left).strip() == str(right).strip()


def _skip_truthy(value: Any) -> bool:
    return not (value is None or value is False or value == 0 or value == 0.0 or value == "" or value == "0")


def _skip_number_cast(value: Any) -> float:
    number = _number(value)
    if number is not None:
        return number
    match = re.match(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)", str(value or ""))
    return float(match.group(1)) if match else 0.0


def _compare_skip_values(actual: Any, expected: Any, operator: str) -> bool | None:
    op = str(operator or "!=").strip().casefold()
    if op in {"=", "!=", "==", "!==", "eq", "equals", "<", "<=", ">", ">="}:
        left: Any = actual
        right: Any = expected
        if _number(left) is not None or _number(right) is not None:
            left = _skip_number_cast(left)
            if not isinstance(right, (list, tuple)):
                right = _skip_number_cast(right)
        if op in {"=", "eq", "equals"}:
            return _skip_values_equal(left, right)
        if op == "!=":
            return not _skip_values_equal(left, right)
        if op == "==":
            return type(left) is type(right) and left == right
        if op == "!==":
            return not (type(left) is type(right) and left == right)
        try:
            return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[op]
        except (TypeError, ValueError):
            return False
    if op in {"in_array", "not_in_array"}:
        alternatives = expected if isinstance(expected, (list, tuple)) else []
        matches = any(_skip_values_equal(actual, value) for value in alternatives)
        return not matches if op == "not_in_array" else matches
    if op == "exists":
        expected_exists = _boolean(expected)
        return None if expected_exists is None else (actual is not None) == expected_exists
    if op in {"starts", "not_starts", "ends", "not_ends", "contains", "not_contains"}:
        expected_values = expected if isinstance(expected, (list, tuple)) else [expected]
        if actual is None or not expected_values:
            return None
        actual_text = str(actual)
        if op.removeprefix("not_") == "starts":
            matches = any(actual_text.startswith(str(value)) for value in expected_values)
        elif op.removeprefix("not_") == "ends":
            matches = any(actual_text.endswith(str(value)) for value in expected_values)
        else:
            matches = any(str(value) in actual_text for value in expected_values)
        return not matches if op.startswith("not_") else matches
    if op in {"regex", "not_regex"}:
        if actual is None:
            return None
        regex = _compile_skip_regex(expected)
        if regex is None:
            return None
        matches = regex.search(str(actual)) is not None
        return not matches if op == "not_regex" else matches
    return None


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    normalized = str(value or "").strip().casefold()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return None


def _compile_skip_regex(value: Any) -> re.Pattern[str] | None:
    raw = str(value or "").strip()
    pattern = raw
    flags = 0
    if raw.startswith("/"):
        closing = -1
        for index in range(len(raw) - 1, 0, -1):
            if raw[index] != "/":
                continue
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and raw[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                closing = index
                break
        if closing < 0:
            return None
        modifiers = raw[closing + 1:]
        if any(char not in "imsxu" for char in modifiers):
            return None
        pattern = raw[1:closing]
        if "i" in modifiers:
            flags |= re.IGNORECASE
        if "m" in modifiers:
            flags |= re.MULTILINE
        if "s" in modifiers:
            flags |= re.DOTALL
        if "x" in modifiers:
            flags |= re.VERBOSE
    pattern = re.sub(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>", r"(?P<\1>", pattern)
    try:
        return re.compile(pattern, flags)
    except re.error:
        return None


def _resolve_skip_oid(
    conn: Any,
    token: Any,
    *,
    vendor: str,
    cache: dict[tuple[str, str], str] | None = None,
) -> tuple[str, str | None, bool]:
    """Resolve a condition OID and any explicit LibreNMS row-index suffix."""
    raw = str(token or "").strip()
    if raw.casefold() == "index":
        return "__index__", None, True

    if "::" in raw:
        mib, symbol_path = raw.rsplit("::", 1)
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*)(?:\.([0-9]+(?:\.[0-9]+)*))?", symbol_path)
        if not match:
            return "", None, False
        oid = _resolve_mib_symbol(
            conn,
            f"{mib}::{match.group(1)}",
            vendor=vendor,
            cache=cache,
        )
        if not oid:
            return "", None, False
        return oid, match.group(2), True

    numeric = _numeric_oid(raw)
    if numeric:
        # A trailing .0 is an explicit scalar instance in LibreNMS rules.
        # Walk its object OID and match that fixed index for every sensor row.
        if numeric.endswith(".0") and numeric.count(".") > 2:
            return numeric[:-2], "0", True
        return numeric, None, True

    oid = _resolve_mib_symbol(conn, raw, vendor=vendor, cache=cache)
    return oid, None, bool(oid)


def _compile_skip_conditions(
    conditions: Any,
    *,
    db_conn: Any,
    vendor: str,
    identity: Mapping[str, Any] | None = None,
    cache: dict[tuple[str, str], str] | None = None,
) -> tuple[list[Any], set[str], bool]:
    """Resolve rule skip conditions to walkable OIDs and an honest support bit."""
    if conditions is None or conditions == []:
        return [], set(), True
    source = conditions if isinstance(conditions, list) else [conditions]
    compiled: list[Any] = []
    oids: set[str] = set()
    supported = True
    for condition in source:
        if not isinstance(condition, Mapping):
            compiled.append(condition)
            continue
        item = dict(condition)
        operator = str(item.get("op") or "eq").strip().casefold()
        if operator not in _SUPPORTED_SKIP_OPERATORS:
            supported = False
        if operator in {"in_array", "not_in_array"}:
            alternatives = item.get("values") if isinstance(item.get("values"), list) else item.get("value") if isinstance(item.get("value"), list) else []
            if not alternatives:
                supported = False
        if item.get("device"):
            # LibreNMS device selectors refer to device-level facts, not to the
            # sensor reading. Snapshot only the fields available in the fresh
            # SNMP/asset identity so polling applies the same discovery rule.
            field = str(item.get("device") or "").strip().casefold()
            identity = identity or {}
            if field == "hardware":
                actual = identity.get("hardware") or identity.get("model")
            elif field == "version":
                actual = identity.get("version") or identity.get("software_version")
            else:
                actual = None
            if actual is None or str(actual).strip() == "":
                supported = False
            else:
                item["_device_value"] = str(actual)
        raw_oid = item.get("oid")
        if raw_oid:
            oid, target_index, resolved = _resolve_skip_oid(
                db_conn,
                raw_oid,
                vendor=vendor,
                cache=cache,
            )
            if not resolved:
                supported = False
            else:
                item["_oid"] = oid
                if oid == "__index__":
                    item["_index"] = True
                else:
                    oids.add(oid)
                    if target_index is not None:
                        item["_target_index"] = target_index
        compiled.append(item)
    return compiled, oids, supported


def _condition_values_at_index(
    conditions: Any,
    *,
    suffix: str,
    raw_value: Any,
    rows_by_oid: Mapping[str, Mapping[str, Any]],
    complete_oids: set[str] | None = None,
) -> tuple[dict[str, Any], bool]:
    values: dict[str, Any] = {}
    complete = True
    source = conditions if isinstance(conditions, list) else [conditions]
    for condition in source:
        if not isinstance(condition, Mapping):
            continue
        oid = str(condition.get("_oid") or "")
        if condition.get("_index"):
            values["__index__"] = suffix
            continue
        if not oid:
            continue
        if condition.get("_value_oid"):
            values[oid] = raw_value
            continue
        condition_suffix = str(condition.get("_target_index") or suffix)
        found = rows_by_oid.get(oid, {}).get(condition_suffix)
        if found is None:
            if str(condition.get("op") or "").casefold() == "exists" and complete_oids and oid in complete_oids:
                # A complete walk with no matching row is a known absence,
                # which is meaningful to LibreNMS' exists=false condition.
                values[oid] = None
            else:
                complete = False
        else:
            values[oid] = found
    return values, complete


def _skip_sample_quality(
    raw_value: Any,
    conditions: Any,
    *,
    conditions_supported: bool,
    suffix: str,
    rows_by_oid: Mapping[str, Mapping[str, Any]],
    complete_oids: set[str] | None = None,
) -> str:
    if not conditions_supported:
        return "unsupported_mapping"
    condition_values, complete = _condition_values_at_index(
        conditions, suffix=suffix, raw_value=raw_value, rows_by_oid=rows_by_oid,
        complete_oids=complete_oids,
    )
    if not complete:
        return "missing"
    skipped = _skip_value(raw_value, conditions, condition_values=condition_values)
    if skipped is None:
        return "unsupported_mapping"
    return "missing" if skipped else "good"


def _measurement_for_entry(entry: Mapping[str, Any]) -> tuple[str, str, str] | None:
    module = str(entry.get("source_module") or "").casefold()
    source_class = str(entry.get("source_class") or "").casefold()
    component_class = str(entry.get("component_class") or "sensor").casefold()
    if module == "processors":
        return "processor", "cpu_usage_percent", "percent"
    if module == "mempools":
        return "memory_pool", "memory_pool", ""
    if component_class in {"fan_state", "power_supply_state", "component_state"} or source_class == "state":
        return component_class, "component_state", "state"
    mapping = {
        "temp": ("temperature", "temperature_celsius", "celsius"),
        "temperature": ("temperature", "temperature_celsius", "celsius"),
        "fan": ("fan", "fan_speed_rpm", "rpm"),
        "fanspeed": ("fan", "fan_speed_rpm", "rpm"),
        "fan_speed": ("fan", "fan_speed_rpm", "rpm"),
        "dbm": ("optical_power", "optical_power_dbm", "dBm"),
        "power": ("power_measurement", "power_watts", "watts"),
        "power_supply": ("power_measurement", "power_watts", "watts"),
        "voltage": ("voltage", "voltage_volts", "volts"),
        "current": ("current", "current_amperes", "amperes"),
    }
    known = mapping.get(source_class)
    if known:
        return known
    if not source_class:
        return None
    # Preserve LibreNMS sensor classes Nexora has no canonical unit contract
    # for. The generic gauge carries the exact upstream class and declared unit.
    return component_class, "sensor_value", str(entry.get("unit") or entry.get("units") or "")


def _canonical_unit_transform(measurement_type: str, unit: Any, factor: float, offset: float) -> tuple[float, float, str] | None:
    token = str(unit or "").strip().casefold().replace(" ", "")
    if measurement_type == "optical_power_dbm":
        return (factor, offset, "dBm") if token in {"", "dbm"} else None
    if measurement_type == "temperature_celsius":
        if token in {"", "c", "°c", "celsius", "degc", "degreecelsius"}:
            return factor, offset, "celsius"
        if token in {"f", "°f", "fahrenheit", "degf", "degreefahrenheit"}:
            return factor * 5.0 / 9.0, (offset - 32.0) * 5.0 / 9.0, "celsius"
        return None
    unit_factors = {
        "voltage_volts": {"": 1.0, "v": 1.0, "volt": 1.0, "volts": 1.0, "mv": 0.001, "millivolt": 0.001, "millivolts": 0.001, "kv": 1000.0, "kilovolt": 1000.0},
        "current_amperes": {"": 1.0, "a": 1.0, "amp": 1.0, "ampere": 1.0, "amperes": 1.0, "ma": 0.001, "milliampere": 0.001, "milliamperes": 0.001},
        "power_watts": {"": 1.0, "w": 1.0, "watt": 1.0, "watts": 1.0, "mw": 0.001, "milliwatt": 0.001, "milliwatts": 0.001, "kw": 1000.0, "kilowatt": 1000.0, "kilowatts": 1000.0},
        "fan_speed_rpm": {"": 1.0, "rpm": 1.0, "revolutionsperminute": 1.0},
    }
    allowed = unit_factors.get(measurement_type)
    if allowed is None or token not in allowed:
        return None if allowed is not None else (factor, offset, "")
    return factor * allowed[token], offset * allowed[token], {
        "voltage_volts": "volts", "current_amperes": "amperes",
        "power_watts": "watts", "fan_speed_rpm": "rpm",
    }[measurement_type]


def _h3c_transceiver_value(raw_value: Any, measurement_type: str) -> float | None:
    number = _number(raw_value)
    if number is None or number == 2147483647:
        return None
    if measurement_type == "optical_power_dbm":
        return number / 100.0
    if measurement_type == "temperature_celsius":
        return number
    if measurement_type == "voltage_volts":
        return number / 100.0
    if measurement_type == "current_amperes":
        # The MIB reports hundredths of a milliampere.
        return number / 100000.0
    return None


def _h3c_transceiver_threshold(raw_value: Any, measurement_type: str) -> float | None:
    number = _number(raw_value)
    if number is None or number in {2147483647, -2147483648}:
        return None
    if measurement_type == "optical_power_dbm":
        # LibreNMS divides tenths-of-microwatts by ten, then calls uw_to_dbm.
        microwatts = number / 10.0
        if microwatts < 0:
            return None
        return -60.0 if microwatts == 0 else 10.0 * math.log10(microwatts / 1000.0)
    if measurement_type == "temperature_celsius":
        return number / 1000.0
    if measurement_type == "voltage_volts":
        return number / 10000.0
    if measurement_type == "current_amperes":
        return number / 1000000.0
    return None


async def _probe_h3c_comware_transceivers(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
) -> dict[str, Any]:
    """Apply LibreNMS' Comware transceiver tables to the hardware inventory."""
    table_read, interface_reads = await asyncio.gather(
        _walk(ip, community, _H3C_TRANSCEIVER_TABLE_OID, port, version, walk_func=walk_func),
        _walk_many(
            ip, community,
            {_IF_NAME_OID, _IF_DESCR_OID, _IF_ADMIN_STATUS_OID},
            port, version, walk_func=walk_func,
        ),
    )

    table_complete = table_read.complete and not table_read.reason
    admin_read = interface_reads.get(_IF_ADMIN_STATUS_OID, WalkResult([], False, "missing_read"))
    admin_complete = admin_read.complete and not admin_read.reason
    name_reads = [interface_reads.get(_IF_NAME_OID), interface_reads.get(_IF_DESCR_OID)]
    name_complete = any(read and read.complete and not read.reason for read in name_reads)
    if_names = _row_map(interface_reads.get(_IF_NAME_OID))
    if_descriptions = _row_map(interface_reads.get(_IF_DESCR_OID))
    admin_statuses = _row_map(admin_read)

    table: dict[int, dict[int, str]] = {}
    for suffix, raw_value in table_read.rows:
        parts = _index_parts(suffix)
        if not parts or len(parts) != 2 or parts[0] <= 0 or parts[1] <= 0:
            continue
        column, if_index = parts
        table.setdefault(if_index, {})[column] = raw_value

    # Column IDs, scales, and threshold mappings mirror the pinned LibreNMS
    # comware discovery modules and HH3C-TRANSCEIVER-INFO-MIB definitions.
    metric_definitions = (
        {
            "column": 9, "name": "tx_power_dbm", "measurement": "optical_power_dbm",
            "component": "optical_power", "unit": "dBm", "factor": 0.01,
            "label": "Transmit Power", "thresholds": {"low_alarm": 31, "low_warning": 33, "high_warning": 32, "high_alarm": 30},
        },
        {
            "column": 12, "name": "rx_power_dbm", "measurement": "optical_power_dbm",
            "component": "optical_power", "unit": "dBm", "factor": 0.01,
            "label": "Receive Power", "thresholds": {"low_alarm": 35, "low_warning": 37, "high_warning": 36, "high_alarm": 34},
        },
        {
            "column": 15, "name": "temperature_celsius", "measurement": "temperature_celsius",
            "component": "temperature", "unit": "celsius", "factor": 1.0,
            "label": "Module Temperature", "thresholds": {"low_alarm": 19, "low_warning": 21, "high_warning": 20, "high_alarm": 18},
        },
        {
            "column": 16, "name": "voltage_volts", "measurement": "voltage_volts",
            "component": "voltage", "unit": "volts", "factor": 0.01,
            "label": "Supply Voltage", "thresholds": {"low_alarm": 23, "low_warning": 25, "high_warning": 24, "high_alarm": 22},
        },
        {
            "column": 17, "name": "bias_current_amperes", "measurement": "current_amperes",
            "component": "current", "unit": "amperes", "factor": 0.00001,
            "label": "Bias Current", "thresholds": {"low_alarm": 27, "low_warning": 29, "high_warning": 28, "high_alarm": 26},
        },
    )
    raw_sensor_rows: dict[str, int] = {str(item["component"]): 0 for item in metric_definitions}
    sensors: list[dict[str, Any]] = []
    missing_admin_status = 0
    missing_port_name = 0
    source_commit = str(rule.get("source_commit") or "")
    rule_id = str(rule.get("id") or rule.get("os_key") or "comware")
    source_files = [
        "includes/discovery/sensors/dbm/comware.inc.php",
        "includes/discovery/sensors/temperature/comware.inc.php",
        "includes/discovery/sensors/voltage/comware.inc.php",
        "includes/discovery/sensors/current/comware.inc.php",
    ]

    for if_index, values in sorted(table.items()):
        # LibreNMS checks isset(diagnostic): the field must exist, but its
        # truth value is not otherwise used as a capability gate.
        if 8 not in values:
            continue
        raw_admin_status = admin_statuses.get(str(if_index))
        admin_number = _number(raw_admin_status)
        admin_is_up = (
            admin_number is not None and int(admin_number) == 1
        ) or str(raw_admin_status or "").strip().casefold() in {"up", "up(1)"}
        if raw_admin_status is None:
            missing_admin_status += 1
            continue
        if not admin_is_up:
            continue

        interface_name = str(if_names.get(str(if_index)) or if_descriptions.get(str(if_index)) or "").strip()
        if not interface_name:
            missing_port_name += 1
            interface_name = f"ifIndex{if_index}"

        for definition in metric_definitions:
            column = int(definition["column"])
            raw_value = values.get(column)
            value = _h3c_transceiver_value(raw_value, str(definition["measurement"]))
            if value is None:
                continue

            thresholds: dict[str, float] = {}
            for threshold_name, threshold_column in definition["thresholds"].items():
                threshold_value = _h3c_transceiver_threshold(
                    values.get(int(threshold_column)), str(definition["measurement"]),
                )
                if threshold_value is not None:
                    thresholds[threshold_name] = threshold_value

            metric_name = str(definition["name"])
            measurement_type = str(definition["measurement"])
            oid = f"{_H3C_TRANSCEIVER_TABLE_OID}.{column}"
            sensor = _sensor(
                source_type="librenms_adapter",
                source_id=f"{rule_id}:transceiver:{metric_name}:{if_index}",
                component_class=str(definition["component"]),
                measurement_type=measurement_type,
                oid=oid,
                suffix=str(if_index),
                raw_value=raw_value,
                value=value,
                unit=str(definition["unit"]),
                sensor_name=f"{interface_name} {definition['label']}",
                entity_name=interface_name,
                group_name="transceiver",
                thresholds=thresholds,
                metadata={
                    "rule_id": rule_id,
                    "source_commit": source_commit,
                    "os_key": "comware",
                    "mib": "HH3C-TRANSCEIVER-INFO-MIB",
                    "adapter": "librenms_comware_transceiver",
                    "adapter_source_files": source_files,
                    "if_index": if_index,
                    "ent_physical_index": if_index,
                    "ent_physical_index_measured": "ports",
                    "index_suffix": str(if_index),
                },
                poll_plan=_direct_plan(oid, str(if_index), factor=float(definition["factor"])),
            )
            if sensor:
                sensor["index_labels"].update({
                    "if_index": str(if_index),
                    "if_name": interface_name,
                    "ent_physical_index": str(if_index),
                })
                sensors.append(sensor)
                raw_sensor_rows[str(definition["component"])] += 1

    coverage_complete = table_complete and admin_complete and name_complete and not missing_admin_status and not missing_port_name
    category_results: list[dict[str, Any]] = []
    for component_class, count in sorted(raw_sensor_rows.items()):
        if count:
            status = "success" if coverage_complete else "partial"
            reason_code = "h3c_comware_transceiver_rows"
            reason = f"LibreNMS Comware transceiver table returned {count} {component_class} measurements"
        elif table_complete and admin_complete:
            status, reason_code, reason = "not_found", "no_transceiver_measurements", "No valid transceiver measurements were returned for this category"
        else:
            status, reason_code, reason = "failed", "h3c_comware_transceiver_walk_failed", "Comware transceiver or IF-MIB walks were incomplete"
        category_results.append(_category_result(
            "librenms_adapter", component_class,
            status=status,
            complete=bool(count and coverage_complete),
            reason_code=reason_code,
            reason=reason,
        ))
    return {"sensors": sensors, "category_results": category_results}


def _h3c_dot11_octet_index(suffix: str, *, trailing_parts: int = 0) -> tuple[str, list[int]] | None:
    """Decode the length-prefixed OCTET STRING index used by HH3C-DOT11 tables."""
    parts = _index_parts(suffix)
    if not parts or parts[0] <= 0 or parts[0] > 127:
        return None
    octet_count = parts[0]
    split_at = 1 + octet_count
    if split_at + trailing_parts != len(parts):
        return None
    octets = parts[1:split_at]
    if any(value < 0 or value > 255 for value in octets):
        return None
    try:
        decoded = bytes(octets).decode("utf-8").strip()
    except UnicodeDecodeError:
        decoded = "hex:" + bytes(octets).hex()
    if not decoded or any(not character.isprintable() for character in decoded):
        decoded = "hex:" + bytes(octets).hex()
    return decoded[:128], parts[split_at:]


def _h3c_dot11_mac_index(suffix: str) -> tuple[str, list[int]] | None:
    """Decode the six-octet MacAddress index of HH3C-DOT11-STATION-MIB."""
    parts = _index_parts(suffix)
    if parts is None or len(parts) != 6 or any(value < 0 or value > 255 for value in parts):
        return None
    mac = ":".join(f"{value:02x}" for value in parts)
    return mac, parts


def _h3c_dot11_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^(?:OCTET STRING|STRING|IpAddress|MacAddress|Hex-STRING)\s*:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip().strip('"').strip()
    text = "".join(character for character in text if character >= " " or character in "\t\n\r")
    if re.fullmatch(r"(?:0x)?(?:[0-9a-fA-F]{2}[\s:-]*){6}", text):
        octets = re.findall(r"[0-9a-fA-F]{2}", text.removeprefix("0x"))
        return ":".join(item.lower() for item in octets)
    return text[:300]


def _h3c_dot11_number(value: Any) -> float | None:
    number = _number(value)
    if number is not None:
        return number
    match = re.search(r"(?<!\d)(-?\d+(?:\.\d+)?)\s*\([^)]*\)", str(value or ""))
    return _number(match.group(1)) if match else None


def _h3c_wireless_sensor(
    *,
    rule: Mapping[str, Any],
    component_class: str,
    measurement_type: str,
    sensor_class: str = "",
    oid: str,
    suffix: str,
    raw_value: Any,
    unit: str,
    sensor_name: str,
    entity_name: str,
    series_variant: str,
    index_labels: Mapping[str, Any] | None = None,
    states: Any = None,
    get_scalar: bool = False,
) -> dict[str, Any] | None:
    """Build one persistent sensor from a documented H3C WLAN MIB value."""
    value: float | None = None
    quality = "missing" if raw_value is None else "invalid"
    if raw_value is not None and measurement_type == "component_state":
        value, _mapping, quality = _mapped_state(raw_value, states)
    elif raw_value is not None and measurement_type == "wireless_station_attribute":
        quality = "good" if str(raw_value).strip() else "invalid"
    elif raw_value is not None and measurement_type == "wireless_radio_attribute":
        quality = "good" if str(raw_value).strip() else "invalid"
    elif raw_value is not None:
        number = _h3c_dot11_number(raw_value)
        allow_negative_raw_signal = sensor_class in {
            "signal_strength_average_raw", "signal_strength_max_raw", "signal_strength_min_raw",
        }
        if number is not None and math.isfinite(number) and (number >= 0 or allow_negative_raw_signal):
            if sensor_class in {"utilization", "radio-resource-usage"}:
                if number <= 100:
                    value, quality = number, "good"
            elif measurement_type in {"cpu_usage_percent", "memory_usage_percent"}:
                if number <= 100:
                    value, quality = number, "good"
            else:
                value, quality = number, "good"

    metadata: dict[str, Any] = {
        "adapter": "nexora_h3c_dot11_official_mib",
        "adapter_source_files": [
            "H3C HH3C-DOT11-ACMT-MIB",
            "H3C HH3C-DOT11-APMT-MIB",
            "H3C HH3C-DOT11-STATION-MIB",
        ],
        "os_key": "comware",
        "rule_id": str(rule.get("id") or "comware"),
        "source_commit": str(rule.get("source_commit") or ""),
        "index_suffix": suffix,
        "series_variant": series_variant,
    }
    if sensor_class:
        metadata["wireless_sensor_class"] = sensor_class
    sensor = _sensor(
        source_type="h3c_wireless",
        source_id=f"{metadata['rule_id']}:h3c_dot11:{component_class}:{sensor_class or measurement_type}:{series_variant}:{suffix}",
        component_class=component_class,
        measurement_type=measurement_type,
        oid=oid,
        suffix=suffix,
        raw_value=raw_value,
        value=value,
        unit=unit,
        sensor_name=sensor_name,
        entity_name=entity_name,
        group_name="wireless",
        quality=quality,
        states=states,
        metadata=metadata,
        poll_plan={
            "kind": "get" if get_scalar else "direct",
            "oid": oid,
            "index": suffix,
            "factor": 1.0,
            "offset": 0.0,
        },
    )
    if sensor is not None:
        sensor["series_variant"] = series_variant
        sensor["index_labels"].update(dict(index_labels or {}))
    return sensor


def _h3c_wireless_category(
    component_class: str,
    *,
    reads: Mapping[str, WalkResult],
    required_oids: set[str],
    rows: int,
    empty_is_complete: bool = False,
    reason_code: str,
    reason: str,
) -> dict[str, Any]:
    complete = bool(required_oids) and all(
        reads.get(oid, WalkResult([], False, "missing_read")).complete
        and not reads.get(oid, WalkResult([], False, "missing_read")).reason
        for oid in required_oids
    )
    status = "success" if rows and complete else "partial" if rows else (
        "not_found" if complete and empty_is_complete else "failed"
    )
    result_complete = bool(complete and (rows > 0 or empty_is_complete))
    resolved_reason_code = reason_code
    if not rows and not empty_is_complete:
        resolved_reason_code = f"{reason_code}_walk_failed" if not complete else f"{reason_code}_empty_unconfirmed"
    return _category_result(
        "h3c_wireless", component_class,
        status=status,
        complete=result_complete,
        reason_code=resolved_reason_code,
        reason=reason,
    )


async def _probe_h3c_comware_wireless(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
) -> dict[str, Any]:
    """Collect H3C controller/AP/radio/BSS/station telemetry from official HH3C-DOT11 MIBs.

    LibreNMS Comware has no Wireless*Discovery implementation.  This is an
    explicit Nexora extension, using H3C's documented object semantics.
    """
    # hh3cDot11APObjectTable is keyed by APObjID. The AP Brief table is
    # separately keyed by AP name and is joined only after decoding that name.
    ap_columns = (2, 3, 7, 8, 9)
    ap_brief_columns = (2, 3, 4, 11, 16, 17, 18, 20, 21, 22, 23, 25)
    radio_columns = (3, 4, 5, 6, 7, 10, 11, 12, 25, 26, 30, 31, 32, 33, 34, 35)
    bss_columns = (2, 4, 6)
    system_columns = (2, 3, 4, 5, 7)
    station_column_specs = (
        (_H3C_DOT11_STATION_IP_OID, "station_ip", "IP 地址"),
        (_H3C_DOT11_STATION_USERNAME_OID, "username", "用户名"),
        (_H3C_DOT11_STATION_TX_RATE_SET_OID, "tx_rate_set", "Tx Rate Set"),
        (_H3C_DOT11_STATION_SSID_OID, "ssid", "SSID"),
    )
    error_columns = {
        f"{_H3C_DOT11_RADIO_RX_STATS}.6": "rx_discarded_frames",
        f"{_H3C_DOT11_RADIO_RX_STATS}.8": "rx_fcs_errors",
        f"{_H3C_DOT11_RADIO_TX_STATS}.2": "tx_failures",
        f"{_H3C_DOT11_RADIO_TX_STATS}.7": "tx_ack_failures",
    }
    radio_assoc_oid = f"{_H3C_DOT11_RADIO_ASSOC_STATS}.6"
    bss_assoc_oid = f"{_H3C_DOT11_BSS_ASSOC_STATS}.6"
    station_oids = {oid for oid, _variant, _label in station_column_specs}
    ap_oids = {f"{_H3C_DOT11_AP_OBJECT_TABLE}.{column}" for column in ap_columns}
    ap_brief_oids = {f"{_H3C_DOT11_AP_BRIEF_TABLE}.{column}" for column in ap_brief_columns}
    radio_oids = {f"{_H3C_DOT11_AP_RADIO_TABLE}.{column}" for column in radio_columns}
    bss_oids = {f"{_H3C_DOT11_AP_BSS_TABLE}.{column}" for column in bss_columns}
    system_oids = {f"{_H3C_DOT11_AP_SYSTEM_TABLE}.{column}" for column in system_columns}
    legacy_system_oids = {f"{_H3C_DOT11_AP_SYSTEM_LEGACY_TABLE}.{column}" for column in system_columns}
    all_oids = (
        ap_oids | ap_brief_oids | radio_oids | bss_oids | system_oids | legacy_system_oids
        | set(error_columns) | {radio_assoc_oid, bss_assoc_oid} | station_oids
    )
    reads = await _walk_many(ip, community, all_oids, port, version, walk_func=walk_func)
    rows = {oid: _row_map(read) for oid, read in reads.items()}
    scalar_oids = {
        _H3C_DOT11_AC_AP_COUNT_OID,
        _H3C_DOT11_AC_CLIENT_COUNT_OID,
        _H3C_DOT11_AC_MAC_MODE_OID,
        _H3C_DOT11_AC_MAX_AP_COUNT_OID,
        _H3C_DOT11_AC_MAX_STATION_COUNT_OID,
        _H3C_DOT11_AC_AP_CONNECT_COUNT_OID,
        _H3C_DOT11_AC_STATION_CONNECT_COUNT_OID,
        _H3C_DOT11_AC_MASTER_AP_COUNT_OID,
        _H3C_DOT11_AC_SLAVE_AP_COUNT_OID,
        _H3C_DOT11_AC_AUTO_AP_COUNT_OID,
        _H3C_DOT11_AC_PERSISTENT_AP_COUNT_OID,
    }
    scalar_values = await _get_many(
        ip, community, scalar_oids, port, version,
    )

    sensors: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    controller_count = 0
    controller_sources = (
        ("ap-count", "在线 AP 数", (_H3C_DOT11_AC_AP_COUNT_OID, _H3C_DOT11_AC_AP_CONNECT_COUNT_OID)),
        ("clients", "无线客户端总数", (_H3C_DOT11_AC_CLIENT_COUNT_OID, _H3C_DOT11_AC_STATION_CONNECT_COUNT_OID)),
    )
    controller_selected: dict[str, tuple[str, Any, float]] = {}
    for sensor_class, display, candidates in controller_sources:
        selected: tuple[str, Any, float] | None = None
        for oid in candidates:
            raw_candidate = scalar_values.get(oid)
            candidate_number = _h3c_dot11_number(raw_candidate)
            if candidate_number is not None and candidate_number >= 0:
                selected = (oid, raw_candidate, candidate_number)
                break
        if selected is None:
            continue
        oid, raw, number = selected
        controller_selected[sensor_class] = selected
        sensor = _h3c_wireless_sensor(
            rule=rule, component_class="wireless_controller", measurement_type="wireless_sensor_value",
            sensor_class=sensor_class, oid=oid, suffix="0", raw_value=raw, unit="count",
            sensor_name=display, entity_name="H3C Wireless Controller", series_variant=sensor_class,
            index_labels={"controller": "true"}, get_scalar=True,
        )
        if sensor:
            sensors.append(sensor)
            controller_count += 1
    controller_complete = len(controller_selected) == len(controller_sources)
    controller_ap_count = controller_selected.get("ap-count", ("", None, None))[2]
    confirmed_empty_controller = controller_ap_count == 0
    categories.append(_category_result(
        "h3c_wireless", "wireless_controller",
        status="success" if controller_complete else "partial" if controller_count else "not_found",
        complete=controller_complete,
        reason_code="h3c_dot11_controller_summary",
        reason=(
            "H3C HH3C-DOT11-ACMT-MIB summary GETs; prefer current AP/associated-station counters and fall back to legacy connect counters."
            if controller_count else "No H3C HH3C-DOT11 wireless controller summary objects responded."
        ),
    ))
    controller_detail_specs = (
        (_H3C_DOT11_AC_MAC_MODE_OID, "ac_mac_mode", "enum", "AC MAC 模式"),
        (_H3C_DOT11_AC_MAX_AP_COUNT_OID, "max_ap_count", "count", "AC 最大 AP 数"),
        (_H3C_DOT11_AC_MAX_STATION_COUNT_OID, "max_station_count", "count", "AC 最大无线终端数"),
        (_H3C_DOT11_AC_MASTER_AP_COUNT_OID, "master_ap_count", "count", "主连接 AP 数"),
        (_H3C_DOT11_AC_SLAVE_AP_COUNT_OID, "slave_ap_count", "count", "备连接 AP 数"),
        (_H3C_DOT11_AC_AUTO_AP_COUNT_OID, "auto_ap_count", "count", "自动 AP 数"),
        (_H3C_DOT11_AC_PERSISTENT_AP_COUNT_OID, "persistent_ap_count", "count", "固化 AP 数"),
    )
    for oid, sensor_class, unit, display in controller_detail_specs:
        raw = scalar_values.get(oid)
        if raw is None:
            continue
        sensor = _h3c_wireless_sensor(
            rule=rule, component_class="wireless_controller", measurement_type="wireless_sensor_value",
            sensor_class=sensor_class, oid=oid, suffix="0", raw_value=raw, unit=unit,
            sensor_name=display, entity_name="H3C Wireless Controller", series_variant=sensor_class,
            index_labels={"controller": "true"}, get_scalar=True,
        )
        if sensor:
            sensors.append(sensor)


    ap_suffixes: set[str] = set()
    ap_column_maps = {column: rows.get(f"{_H3C_DOT11_AP_OBJECT_TABLE}.{column}", {}) for column in ap_columns}
    for values in ap_column_maps.values():
        ap_suffixes.update(values)
    ap_by_id: dict[str, dict[str, Any]] = {}
    ap_by_suffix: dict[str, dict[str, Any]] = {}
    for suffix in sorted(ap_suffixes):
        decoded = _h3c_dot11_octet_index(suffix)
        if decoded is None:
            continue
        ap_id, _tail = decoded
        item: dict[str, Any] = {"suffix": suffix, "ap_id": ap_id}
        for column, label in ((2, "ap_ip"), (3, "ap_mac"), (7, "ap_clients"), (8, "ap_name"), (9, "ap_model")):
            value = ap_column_maps[column].get(suffix)
            if value is not None:
                item[label] = _h3c_dot11_text(value)
        ap_by_id[ap_id] = item
        ap_by_suffix[suffix] = item

    # The AP Brief table is indexed by AP name, unlike the AP/radio tables.
    # Join it only through that documented identity and keep its extra values
    # as labels/metadata instead of treating its suffix as an APObjID.
    ap_brief_column_maps = {
        column: rows.get(f"{_H3C_DOT11_AP_BRIEF_TABLE}.{column}", {})
        for column in ap_brief_columns
    }
    ap_brief_suffixes: set[str] = set()
    for values in ap_brief_column_maps.values():
        ap_brief_suffixes.update(values)
    ap_brief_by_name: dict[str, dict[str, str]] = {}
    ap_brief_fields = {
        2: "ap_serial",
        3: "ap_model",
        4: "ap_description",
        11: "ap_element_id",
        16: "ap_ip",
        17: "ap_mac",
        18: "ap_connection_type",
        20: "ap_ac_port_index",
        21: "ap_clients",
        22: "ap_image_name",
        23: "ap_software_version",
        25: "ap_operation_status",
    }
    for suffix in sorted(ap_brief_suffixes):
        decoded = _h3c_dot11_octet_index(suffix)
        if decoded is None:
            continue
        ap_name, _tail = decoded
        brief: dict[str, str] = {}
        brief["ap_name"] = ap_name
        brief["ap_brief_suffix"] = suffix
        for column, label in ap_brief_fields.items():
            raw = ap_brief_column_maps[column].get(suffix)
            if raw is not None:
                brief[label] = _h3c_dot11_text(raw)
        ap_brief_by_name[ap_name.casefold()] = brief
    for item in list(ap_by_id.values()):
        ap_name = str(item.get("ap_name") or "").strip()
        ap_identifier = str(item.get("ap_id") or "").strip()
        brief = ap_brief_by_name.get(ap_name.casefold()) or ap_brief_by_name.get(ap_identifier.casefold())
        if not brief:
            continue
        if not ap_name and brief.get("ap_name"):
            item["ap_name"] = brief["ap_name"]
        for label, value in brief.items():
            if value and not item.get(label):
                item[label] = value
    ap_names_seen = {
        identity.casefold()
        for item in ap_by_id.values()
        for identity in (item.get("ap_name"), item.get("ap_id"))
        if identity
    }
    legacy_ap_items: list[dict[str, Any]] = []
    for ap_name_key, brief in ap_brief_by_name.items():
        if ap_name_key in ap_names_seen:
            continue
        item: dict[str, Any] = dict(brief)
        item["suffix"] = str(brief.get("ap_brief_suffix") or "")
        legacy_ap_items.append(item)
        ap_by_id.setdefault(ap_name_key, item)
    for item in list(ap_by_id.values()):
        ap_name = str(item.get("ap_name") or "").strip()
        if ap_name:
            ap_by_id.setdefault(ap_name, item)
            ap_by_id.setdefault(ap_name.casefold(), item)

    ap_status_states = [
        {"value": "1", "descr": "associated", "generic": "up"},
        {"value": "associated(1)", "descr": "associated", "generic": "up"},
        {"value": "2", "descr": "deassociated", "generic": "down"},
        {"value": "deassociated(2)", "descr": "deassociated", "generic": "down"},
        {"value": "3", "descr": "downloading image", "generic": "warning"},
        {"value": "downloadingImage(3)", "descr": "downloading image", "generic": "warning"},
    ]
    ap_sensor_count = 0
    ap_system_raw = {column: rows.get(f"{_H3C_DOT11_AP_SYSTEM_TABLE}.{column}", {}) for column in system_columns}
    legacy_system_raw = {column: rows.get(f"{_H3C_DOT11_AP_SYSTEM_LEGACY_TABLE}.{column}", {}) for column in system_columns}
    ap_brief_status_oid = f"{_H3C_DOT11_AP_BRIEF_TABLE}.25"
    ap_sensor_items = list(ap_by_suffix.items()) + [
        (str(item.get("suffix") or ""), item) for item in legacy_ap_items if item.get("suffix")
    ]
    for suffix, item in sorted(ap_sensor_items):
        ap_name = str(item.get("ap_name") or "").strip()
        ap_id = str(item.get("ap_id") or "").strip()
        labels = {key: value for key, value in item.items() if key in {"ap_id", "ap_name", "ap_model", "ap_ip", "ap_mac", "ap_serial"} and value}
        entity_name = ap_name or f"AP ID {ap_id}"
        raw_status = ap_system_raw[7].get(suffix)
        status_oid = f"{_H3C_DOT11_AP_SYSTEM_TABLE}.7"
        status_suffix = suffix
        status_states = ap_status_states
        if raw_status is None and item.get("ap_element_id"):
            status_oid = f"{_H3C_DOT11_AP_SYSTEM_LEGACY_TABLE}.7"
            status_suffix = str(item["ap_element_id"])
            raw_status = legacy_system_raw[7].get(status_suffix)
        if raw_status is None and item.get("ap_brief_suffix"):
            status_oid = ap_brief_status_oid
            status_suffix = str(item["ap_brief_suffix"])
            raw_status = ap_brief_column_maps[25].get(status_suffix)
            status_states = [
                {"value": "1", "descr": "run", "generic": "up"},
                {"value": "run(1)", "descr": "run", "generic": "up"},
                {"value": "2", "descr": "idle", "generic": "down"},
                {"value": "idle(2)", "descr": "idle", "generic": "down"},
            ]
        if raw_status is not None:
            sensor = _h3c_wireless_sensor(
                rule=rule, component_class="wireless_access_point", measurement_type="component_state",
                oid=status_oid, suffix=status_suffix, raw_value=raw_status, unit="state",
                sensor_name=f"{entity_name} 状态", entity_name=entity_name, series_variant="ap_status",
                index_labels=labels, states=status_states,
            )
            if sensor:
                sensors.append(sensor)
                ap_sensor_count += 1
        raw_clients = ap_column_maps[7].get(suffix)
        client_oid = f"{_H3C_DOT11_AP_OBJECT_TABLE}.7"
        client_suffix = suffix
        if raw_clients is None and item.get("ap_clients") is not None and item.get("ap_brief_suffix"):
            raw_clients = item["ap_clients"]
            client_oid = f"{_H3C_DOT11_AP_BRIEF_TABLE}.21"
            client_suffix = str(item["ap_brief_suffix"])
        if raw_clients is not None:
            sensor = _h3c_wireless_sensor(
                rule=rule, component_class="wireless_access_point", measurement_type="wireless_sensor_value",
                sensor_class="clients", oid=client_oid, suffix=client_suffix,
                raw_value=raw_clients, unit="count", sensor_name=f"{entity_name} 客户端数",
                entity_name=entity_name, series_variant="clients", index_labels=labels,
            )
            if sensor:
                sensors.append(sensor)
                ap_sensor_count += 1
    ap_object_clients_oid = f"{_H3C_DOT11_AP_OBJECT_TABLE}.7"
    ap_brief_clients_oid = f"{_H3C_DOT11_AP_BRIEF_TABLE}.21"
    ap_object_client_rows = rows.get(ap_object_clients_oid, {})
    ap_brief_client_rows = rows.get(ap_brief_clients_oid, {})
    ap_object_client_read = reads.get(ap_object_clients_oid, WalkResult([], False, "missing_read"))
    if ap_object_client_rows:
        ap_client_coverage_oid = ap_object_clients_oid
    elif ap_brief_client_rows:
        ap_client_coverage_oid = ap_brief_clients_oid
    elif ap_object_client_read.complete and not ap_object_client_read.reason:
        ap_client_coverage_oid = ap_object_clients_oid
    else:
        ap_client_coverage_oid = ap_brief_clients_oid
    if ap_column_maps[8]:
        ap_identity_coverage_oid = f"{_H3C_DOT11_AP_OBJECT_TABLE}.8"
    else:
        ap_brief_identity_column = next(
            (column for column in (2, 3, 16, 17, 25, 21) if ap_brief_column_maps[column]),
            21,
        )
        ap_identity_coverage_oid = f"{_H3C_DOT11_AP_BRIEF_TABLE}.{ap_brief_identity_column}"
    if ap_system_raw[7]:
        ap_status_coverage_oid = f"{_H3C_DOT11_AP_SYSTEM_TABLE}.7"
    elif legacy_system_raw[7]:
        ap_status_coverage_oid = f"{_H3C_DOT11_AP_SYSTEM_LEGACY_TABLE}.7"
    elif ap_brief_column_maps[25]:
        ap_status_coverage_oid = ap_brief_status_oid
    elif ap_by_suffix:
        ap_status_coverage_oid = f"{_H3C_DOT11_AP_SYSTEM_TABLE}.7"
    else:
        ap_status_coverage_oid = ap_brief_status_oid
    categories.append(_h3c_wireless_category(
        "wireless_access_point", reads=reads,
        required_oids={
            ap_identity_coverage_oid,
            ap_status_coverage_oid,
            ap_client_coverage_oid,
        },
        empty_is_complete=confirmed_empty_controller,
        rows=ap_sensor_count, reason_code="h3c_dot11_ap_brief_table",
        reason="AP Object table when present, with AP name-indexed HH3C-DOT11-APMT-MIB AP Brief and version-matched AP system-table fallbacks.",
    ))

    processor_count = memory_count = 0
    processor_specs = ((2, "realtime", "CPU 实时使用率"), (3, "average", "CPU 平均使用率"))
    memory_specs = ((4, "realtime", "内存实时使用率"), (5, "average", "内存平均使用率"))
    use_legacy_ap_system = (
        not any(ap_system_raw[column] for column in (2, 3, 4, 5))
        and any(legacy_system_raw[column] for column in (2, 3, 4, 5))
    )
    metric_system_root = _H3C_DOT11_AP_SYSTEM_LEGACY_TABLE if use_legacy_ap_system else _H3C_DOT11_AP_SYSTEM_TABLE
    metric_system_raw = legacy_system_raw if use_legacy_ap_system else ap_system_raw
    ap_by_element_id = {
        str(item.get("ap_element_id")): item
        for _, item in ap_sensor_items
        if item.get("ap_element_id") not in (None, "")
    }
    for column, variant, display in processor_specs:
        oid = f"{metric_system_root}.{column}"
        for suffix, raw in sorted(metric_system_raw[column].items()):
            if use_legacy_ap_system:
                ap = ap_by_element_id.get(str(suffix), {})
                decoded_ap_id = ""
            else:
                decoded = _h3c_dot11_octet_index(suffix)
                decoded_ap_id = decoded[0] if decoded else ""
                ap = (ap_by_id.get(decoded_ap_id) or ap_by_id.get(decoded_ap_id.casefold(), {})) if decoded else {}
            ap_name = str(ap.get("ap_name") or "").strip()
            ap_id = str(ap.get("ap_id") or decoded_ap_id).strip()
            labels = {key: ap[key] for key in ("ap_id", "ap_name", "ap_model", "ap_ip", "ap_mac", "ap_serial") if ap.get(key)}
            if ap_id:
                labels.setdefault("ap_id", ap_id)
            title = f"{ap_name or f'AP ID {ap_id}'} {display}" if ap_id or ap_name else display
            sensor = _h3c_wireless_sensor(
                rule=rule, component_class="processor", measurement_type="cpu_usage_percent",
                oid=oid, suffix=suffix, raw_value=raw, unit="percent", sensor_name=title,
                entity_name=ap_name or (f"AP ID {ap_id}" if ap_id else ""), series_variant=f"ap_{variant}", index_labels=labels,
            )
            if sensor:
                sensors.append(sensor)
                processor_count += 1
    for column, variant, display in memory_specs:
        oid = f"{metric_system_root}.{column}"
        for suffix, raw in sorted(metric_system_raw[column].items()):
            if use_legacy_ap_system:
                ap = ap_by_element_id.get(str(suffix), {})
                decoded_ap_id = ""
            else:
                decoded = _h3c_dot11_octet_index(suffix)
                decoded_ap_id = decoded[0] if decoded else ""
                ap = (ap_by_id.get(decoded_ap_id) or ap_by_id.get(decoded_ap_id.casefold(), {})) if decoded else {}
            ap_name = str(ap.get("ap_name") or "").strip()
            ap_id = str(ap.get("ap_id") or decoded_ap_id).strip()
            labels = {key: ap[key] for key in ("ap_id", "ap_name", "ap_model", "ap_ip", "ap_mac", "ap_serial") if ap.get(key)}
            if ap_id:
                labels.setdefault("ap_id", ap_id)
            title = f"{ap_name or f'AP ID {ap_id}'} {display}" if ap_id or ap_name else display
            sensor = _h3c_wireless_sensor(
                rule=rule, component_class="memory_pool", measurement_type="memory_usage_percent",
                oid=oid, suffix=suffix, raw_value=raw, unit="percent", sensor_name=title,
                entity_name=ap_name or (f"AP ID {ap_id}" if ap_id else ""), series_variant=f"ap_{variant}", index_labels=labels,
            )
            if sensor:
                sensors.append(sensor)
                memory_count += 1
    categories.append(_h3c_wireless_category(
        "processor", reads=reads, required_oids={f"{metric_system_root}.{column}" for column, _, _ in processor_specs},
        empty_is_complete=confirmed_empty_controller,
        rows=processor_count, reason_code="h3c_dot11_ap_cpu",
        reason="HH3C-DOT11-APMT-MIB AP real-time and average CPU usage (0-100 percent).",
    ))
    categories.append(_h3c_wireless_category(
        "memory_pool", reads=reads, required_oids={f"{metric_system_root}.{column}" for column, _, _ in memory_specs},
        empty_is_complete=confirmed_empty_controller,
        rows=memory_count, reason_code="h3c_dot11_ap_memory",
        reason="HH3C-DOT11-APMT-MIB AP real-time and average memory usage (0-100 percent).",
    ))

    def joined_ap(suffix: str, trailing_parts: int) -> tuple[dict[str, Any], str, list[int]] | None:
        decoded = _h3c_dot11_octet_index(suffix, trailing_parts=trailing_parts)
        if decoded is None:
            return None
        ap_identifier, tail = decoded
        return ap_by_id.get(ap_identifier) or ap_by_id.get(ap_identifier.casefold(), {}), ap_identifier, tail

    radio_scope_oids = radio_oids | {radio_assoc_oid} | set(error_columns)
    radio_suffixes: set[str] = set()
    for oid in radio_scope_oids:
        radio_suffixes.update(rows.get(oid, {}))
    radio_count = 0
    radio_status_states = [
        {"value": "1", "descr": "up", "generic": "up"},
        {"value": "up(1)", "descr": "up", "generic": "up"},
        {"value": "2", "descr": "down", "generic": "down"},
        {"value": "down(2)", "descr": "down", "generic": "down"},
        {"value": "3", "descr": "testing", "generic": "warning"},
        {"value": "testing(3)", "descr": "testing", "generic": "warning"},
        {"value": "4", "descr": "administratively down", "generic": "down"},
        {"value": "admindown(4)", "descr": "administratively down", "generic": "down"},
    ]
    radio_truth_states = [
        {"value": "1", "descr": "enabled", "generic": "up"},
        {"value": "true", "descr": "enabled", "generic": "up"},
        {"value": "true(1)", "descr": "enabled", "generic": "up"},
        {"value": "2", "descr": "disabled", "generic": "down"},
        {"value": "false", "descr": "disabled", "generic": "down"},
        {"value": "false(2)", "descr": "disabled", "generic": "down"},
    ]
    for suffix in sorted(radio_suffixes):
        joined = joined_ap(suffix, 1)
        if joined is None:
            continue
        ap, ap_identifier, tail = joined
        ap_name = str(ap.get("ap_name") or "").strip()
        radio_id = str(tail[0])
        labels = {key: ap[key] for key in ("ap_id", "ap_name", "ap_model", "ap_ip", "ap_mac", "ap_serial") if ap.get(key)}
        labels.setdefault("ap_id", ap_identifier)
        labels["radio_id"] = radio_id
        radio_ifindex = rows.get(f"{_H3C_DOT11_AP_RADIO_TABLE}.7", {}).get(suffix)
        if radio_ifindex is not None:
            labels["radio_ifindex"] = _h3c_dot11_text(radio_ifindex)
        entity_name = f"{ap_name or f'AP ID {ap_identifier}'} Radio {radio_id}"
        for column, variant, label, state_map in (
            (3, "admin_status", "管理状态", radio_truth_states),
            (4, "oper_status", "运行状态", radio_truth_states),
            (25, "oper_status_cm", "运行状态", radio_status_states),
        ):
            oid = f"{_H3C_DOT11_AP_RADIO_TABLE}.{column}"
            raw_status = rows.get(oid, {}).get(suffix)
            if raw_status is None:
                continue
            sensor = _h3c_wireless_sensor(
                rule=rule, component_class="wireless_radio", measurement_type="component_state",
                sensor_class="state", oid=oid, suffix=suffix, raw_value=raw_status,
                unit="state", sensor_name=f"{entity_name} {label}", entity_name=entity_name,
                series_variant=variant, index_labels=labels, states=state_map,
            )
            if sensor:
                sensors.append(sensor)
                radio_count += 1
        for column, sensor_class, unit, variant, label in (
            (5, "channel", "channel", "channel", "信道"),
            (6, "tx_power_level", "level", "tx_power_level", "发射功率等级"),
            (10, "radio-resource-usage", "percent", "radio_resource_usage", "射频资源使用率"),
            (11, "radio_mode", "bitmask", "radio_mode_support", "支持模式位图"),
            (12, "tx_power_level", "level", "tx_power_level_current", "当前发射功率等级"),
            (26, "utilization", "percent", "channel_utilization", "主信道利用率"),
            (30, "radio_type_code", "enum", "radio_type_code", "Radio 类型代码"),
            (31, "radio_oper_code", "enum", "radio_oper_code", "Radio 运行代码"),
            (33, "signal_strength_average_raw", "raw", "signal_strength_average_raw", "平均接收信号强度原始值"),
            (34, "signal_strength_max_raw", "raw", "signal_strength_max_raw", "最大接收信号强度原始值"),
            (35, "signal_strength_min_raw", "raw", "signal_strength_min_raw", "最小接收信号强度原始值"),
        ):
            oid = f"{_H3C_DOT11_AP_RADIO_TABLE}.{column}"
            raw = rows.get(oid, {}).get(suffix)
            number = _h3c_dot11_number(raw)
            if raw is None or number is None or (sensor_class in {"utilization", "radio-resource-usage"} and (number < 0 or number > 100)):
                continue
            sensor = _h3c_wireless_sensor(
                rule=rule, component_class="wireless_radio", measurement_type="wireless_sensor_value",
                sensor_class=sensor_class, oid=oid, suffix=suffix, raw_value=raw, unit=unit,
                sensor_name=f"{entity_name} {label}", entity_name=entity_name,
                series_variant=variant, index_labels=labels,
            )
            if sensor:
                sensors.append(sensor)
                radio_count += 1
        bound_ssids_oid = f"{_H3C_DOT11_AP_RADIO_TABLE}.32"
        raw_bound_ssids = rows.get(bound_ssids_oid, {}).get(suffix)
        if raw_bound_ssids is not None:
            sensor = _h3c_wireless_sensor(
                rule=rule, component_class="wireless_radio", measurement_type="wireless_radio_attribute",
                sensor_class="bound_ssids", oid=bound_ssids_oid, suffix=suffix,
                raw_value=raw_bound_ssids, unit="text", sensor_name=f"{entity_name} 绑定 SSID 原始值",
                entity_name=entity_name, series_variant="bound_ssids_raw", index_labels=labels,
            )
            if sensor:
                sensors.append(sensor)
                radio_count += 1
        raw_clients = rows.get(radio_assoc_oid, {}).get(suffix)
        if raw_clients is not None:
            sensor = _h3c_wireless_sensor(
                rule=rule, component_class="wireless_radio", measurement_type="wireless_sensor_value",
                sensor_class="clients", oid=radio_assoc_oid, suffix=suffix, raw_value=raw_clients,
                unit="count", sensor_name=f"{entity_name} 客户端数", entity_name=entity_name,
                series_variant="clients", index_labels=labels,
            )
            if sensor:
                sensors.append(sensor)
                radio_count += 1
        for oid, variant in error_columns.items():
            raw = rows.get(oid, {}).get(suffix)
            if raw is None:
                continue
            sensor = _h3c_wireless_sensor(
                rule=rule, component_class="wireless_radio", measurement_type="wireless_sensor_value",
                sensor_class="errors", oid=oid, suffix=suffix, raw_value=raw, unit="count",
                sensor_name=f"{entity_name} {variant.replace('_', ' ')}", entity_name=entity_name,
                series_variant=variant, index_labels=labels,
            )
            if sensor:
                sensors.append(sensor)
                radio_count += 1
    radio_required = {
        f"{_H3C_DOT11_AP_RADIO_TABLE}.{column}" for column in radio_columns
    } | {radio_assoc_oid}
    categories.append(_h3c_wireless_category(
        "wireless_radio", reads=reads, required_oids=radio_required, rows=radio_count,
        empty_is_complete=confirmed_empty_controller,
        reason_code="h3c_dot11_radio_tables",
        reason="HH3C-DOT11 radio admin/oper status, channel, transmit power, utilization, mode/type, raw signal-strength columns, bound SSIDs, associated clients and documented error counters.",
    ))

    bss_scope_oids = bss_oids | {bss_assoc_oid}
    bss_suffixes: set[str] = set()
    for oid in bss_scope_oids:
        bss_suffixes.update(rows.get(oid, {}))
    bss_count = 0
    bss_info = {column: rows.get(f"{_H3C_DOT11_AP_BSS_TABLE}.{column}", {}) for column in bss_columns}
    for suffix in sorted(bss_suffixes):
        joined = joined_ap(suffix, 2)
        if joined is None:
            continue
        ap, ap_identifier, tail = joined
        ap_name = str(ap.get("ap_name") or "").strip()
        radio_id, wlan_id = str(tail[0]), str(tail[1])
        labels = {key: ap[key] for key in ("ap_id", "ap_name", "ap_model", "ap_ip", "ap_mac", "ap_serial") if ap.get(key)}
        labels.setdefault("ap_id", ap_identifier)
        labels["radio_id"] = radio_id
        labels["wlan_id"] = wlan_id
        labels["ssid"] = _h3c_dot11_text(bss_info[4].get(suffix))
        labels["bssid"] = _h3c_dot11_text(bss_info[2].get(suffix))
        vlan = _h3c_dot11_number(bss_info[6].get(suffix))
        if vlan is not None:
            labels["vlan_id"] = str(int(vlan))
        ssid_label = labels["ssid"] or f"WLAN {wlan_id}"
        entity_name = f"{ap_name or f'AP ID {ap_identifier}'} / {ssid_label}"
        raw_clients = rows.get(bss_assoc_oid, {}).get(suffix)
        if raw_clients is None:
            continue
        sensor = _h3c_wireless_sensor(
            rule=rule, component_class="wireless_bss", measurement_type="wireless_sensor_value",
            sensor_class="clients", oid=bss_assoc_oid, suffix=suffix, raw_value=raw_clients,
            unit="count", sensor_name=f"{entity_name} 客户端数", entity_name=entity_name,
            series_variant="clients", index_labels=labels,
        )
        if sensor:
            sensors.append(sensor)
            bss_count += 1
    bss_required = {f"{_H3C_DOT11_AP_BSS_TABLE}.{column}" for column in bss_columns} | {bss_assoc_oid}
    categories.append(_h3c_wireless_category(
        "wireless_bss", reads=reads, required_oids=bss_required, rows=bss_count,
        empty_is_complete=confirmed_empty_controller,
        reason_code="h3c_dot11_bss_tables",
        reason="HH3C-DOT11 BSS SSID/BSSID/VLAN identity joined with current associated client count.",
    ))

    station_rows = {oid: rows.get(oid, {}) for oid in station_oids}
    station_suffixes = set().union(*(set(column_rows) for column_rows in station_rows.values()))
    station_count = 0
    for suffix in sorted(station_suffixes):
        decoded_mac = _h3c_dot11_mac_index(suffix)
        if decoded_mac is None:
            continue
        station_mac, _index = decoded_mac
        entity_name = "无线客户端"
        for oid, series_variant, display in station_column_specs:
            raw = _h3c_dot11_text(station_rows.get(oid, {}).get(suffix))
            if not raw:
                continue
            sensor = _h3c_wireless_sensor(
                rule=rule, component_class="wireless_station",
                measurement_type="wireless_station_attribute", sensor_class="identity",
                oid=oid, suffix=suffix, raw_value=raw, unit="text",
                sensor_name=f"无线客户端 {display}", entity_name=entity_name,
                series_variant=series_variant, index_labels={},
            )
            if sensor:
                sensor_labels = sensor.get("index_labels")
                if isinstance(sensor_labels, dict):
                    sensor_labels.clear()
                metadata = sensor.get("metadata")
                if isinstance(metadata, dict):
                    metadata["station_mac"] = station_mac
                    metadata["station_attributes"] = {series_variant: raw[:300]}
                sensor["source_id"] = (
                    f"{rule.get('id') or 'comware'}:h3c_dot11:wireless_station:{series_variant}"
                )
                sensors.append(sensor)
                station_count += 1
    categories.append(_h3c_wireless_category(
        "wireless_station", reads=reads, required_oids=station_oids, rows=station_count,
        empty_is_complete=confirmed_empty_controller,
        reason_code="h3c_dot11_station_associate_table",
        reason=(
            "HH3C-DOT11-STATION-MIB hh3cDot11StationAssociateTable uses the fixed six-octet Station MAC index; "
            "collects client IP, username, TxRateSet, and SSID."
        ),
    ))
    brief_metadata_fields = (
        "ap_description", "ap_element_id", "ap_connection_type",
        "ap_ac_port_index", "ap_image_name", "ap_software_version",
    )
    for sensor in sensors:
        labels = sensor.get("index_labels")
        if not isinstance(labels, dict):
            continue
        ap_identity = str(labels.get("ap_id") or labels.get("ap_name") or "")
        ap = ap_by_id.get(ap_identity) or ap_by_id.get(ap_identity.casefold())
        if not ap:
            continue
        if ap.get("ap_serial"):
            labels.setdefault("ap_serial", ap["ap_serial"])
        metadata = sensor.get("metadata")
        if isinstance(metadata, dict):
            metadata["h3c_ap_brief"] = {
                key: ap[key] for key in brief_metadata_fields if ap.get(key)
            }
    return {"sensors": sensors, "category_results": categories}


def _h3c_module_entity_class(raw_value: Any) -> bool:
    text = str(raw_value or "").strip().casefold()
    if text == "module" or re.fullmatch(r"module\(\s*9\s*\)", text):
        return True
    number = _number(text)
    if number is not None:
        return int(number) == _ENTITY_PHYSICAL_CLASS_MODULE
    enum_number = re.fullmatch(r"\s*(\d+)\s*\([^)]*\)\s*", text)
    if enum_number:
        return int(enum_number.group(1)) == _ENTITY_PHYSICAL_CLASS_MODULE
    enum_label = re.fullmatch(r"\s*[^()]+\((\d+)\)\s*", text)
    return bool(enum_label and int(enum_label.group(1)) == _ENTITY_PHYSICAL_CLASS_MODULE)


def _append_unique_probe_sensors(
    sensors: list[dict[str, Any]],
    additions: Any,
) -> None:
    """Append probe results without duplicating an OID/index/measurement row."""
    existing = {
        (
            str(sensor.get("oid") or ""),
            tuple(sensor.get("index") or []),
            str(sensor.get("measurement_type") or ""),
        )
        for sensor in sensors
        if isinstance(sensor, Mapping)
    }
    for sensor in additions or []:
        if not isinstance(sensor, dict):
            continue
        key = (
            str(sensor.get("oid") or ""),
            tuple(sensor.get("index") or []),
            str(sensor.get("measurement_type") or ""),
        )
        if key not in existing:
            sensors.append(sensor)
            existing.add(key)


async def _probe_h3c_comware_cpu_memory(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
) -> dict[str, Any]:
    """Discover Comware processors and module memory from HH3C-ENTITY-EXT-MIB."""
    reads = await _walk_many(
        ip,
        community,
        {
            _H3C_ENTITY_CPU_USAGE_OID,
            _H3C_ENTITY_MEM_USAGE_OID,
            _H3C_ENTITY_MEM_SIZE_OID,
            _ENTITY_CLASS_OID,
            _ENTITY_NAME_OID,
        },
        port,
        version,
        walk_func=walk_func,
    )
    cpu_read = reads.get(_H3C_ENTITY_CPU_USAGE_OID, WalkResult([], False, "missing_read"))
    memory_reads = {
        _H3C_ENTITY_MEM_USAGE_OID: reads.get(_H3C_ENTITY_MEM_USAGE_OID, WalkResult([], False, "missing_read")),
        _H3C_ENTITY_MEM_SIZE_OID: reads.get(_H3C_ENTITY_MEM_SIZE_OID, WalkResult([], False, "missing_read")),
        _ENTITY_CLASS_OID: reads.get(_ENTITY_CLASS_OID, WalkResult([], False, "missing_read")),
    }
    entity_names = _row_map(reads.get(_ENTITY_NAME_OID))
    entity_classes = _row_map(memory_reads[_ENTITY_CLASS_OID])
    rule_id = str(rule.get("id") or rule.get("os_key") or "comware")
    source_commit = str(rule.get("source_commit") or "")
    sensors: list[dict[str, Any]] = []

    cpu_rows = 0
    malformed_cpu_rows = 0
    for suffix, raw_value in cpu_read.rows:
        index = _index_parts(suffix)
        number = _number(raw_value)
        if index is None or len(index) != 1 or number is None or normalize_percentage(number) is None:
            malformed_cpu_rows += 1
            continue
        # LibreNMS only discovers non-zero processor entities. Once discovered,
        # the direct poll plan intentionally accepts a later zero value.
        if number == 0:
            continue
        entity_index = str(index[0])
        entity_name = _name_at(entity_names, index, f"Processor {entity_index}")
        sensor = _sensor(
            source_type="librenms_adapter",
            source_id=f"{rule_id}:processor:{entity_index}",
            component_class="processor",
            measurement_type="cpu_usage_percent",
            oid=_H3C_ENTITY_CPU_USAGE_OID,
            suffix=entity_index,
            raw_value=raw_value,
            value=normalize_percentage(number),
            unit="percent",
            sensor_name=entity_name,
            entity_name=entity_name,
            group_name="processor",
            metadata={
                "rule_id": rule_id,
                "source_commit": source_commit,
                "source_path": _H3C_COMWARE_PHP_SOURCE,
                "os_key": "comware",
                "adapter": _H3C_COMWARE_ADAPTER,
                "adapter_source_files": [_H3C_COMWARE_PHP_SOURCE],
                "mib": "HH3C-ENTITY-EXT-MIB",
                "ent_physical_index": entity_index,
                "ent_physical_index_measured": "entPhysicalIndex",
                "index_suffix": entity_index,
                "window": "unknown",
            },
            poll_plan=_direct_plan(_H3C_ENTITY_CPU_USAGE_OID, entity_index),
        )
        if sensor:
            sensor["index_labels"]["ent_physical_index"] = entity_index
            sensors.append(sensor)
            cpu_rows += 1

    cpu_complete = cpu_read.complete and not cpu_read.reason
    if cpu_rows:
        cpu_status = "success" if cpu_complete and not malformed_cpu_rows else "partial"
        cpu_reason_code = "h3c_comware_processor_rows" if cpu_status == "success" else "h3c_comware_processor_partial"
        cpu_reason = f"LibreNMS Comware CPU table returned {cpu_rows} non-zero processor measurements"
        if not cpu_complete:
            cpu_reason += "; hh3cEntityExtCpuUsage walk was incomplete"
        if malformed_cpu_rows:
            cpu_reason += f"; skipped {malformed_cpu_rows} malformed processor row(s)"
    elif cpu_complete and not malformed_cpu_rows:
        cpu_status = "not_found"
        cpu_reason_code = "no_nonzero_comware_processors"
        cpu_reason = "Comware CPU walk completed without non-zero processor rows"
    elif cpu_complete:
        cpu_status = "partial"
        cpu_reason_code = "h3c_comware_processor_partial"
        cpu_reason = f"Comware CPU walk completed but {malformed_cpu_rows} processor row(s) were malformed"
    else:
        cpu_status = "failed"
        cpu_reason_code = "h3c_comware_processor_walk_failed"
        cpu_reason = "hh3cEntityExtCpuUsage walk was incomplete"

    memory_usage = _row_map(memory_reads[_H3C_ENTITY_MEM_USAGE_OID])
    memory_sizes = _row_map(memory_reads[_H3C_ENTITY_MEM_SIZE_OID])
    memory_rows = 0
    malformed_memory_rows = 0
    for suffix, raw_usage in memory_usage.items():
        index = _index_parts(suffix)
        usage = _number(raw_usage)
        if index is None or len(index) != 1:
            malformed_memory_rows += 1
            continue
        entity_index = str(index[0])
        if not _h3c_module_entity_class(entity_classes.get(suffix)):
            continue
        if usage is None or normalize_percentage(usage) is None:
            malformed_memory_rows += 1
            continue
        if usage <= 0:
            continue
        raw_size = memory_sizes.get(suffix)
        size = _number(raw_size)
        if size is None or size <= 0:
            malformed_memory_rows += 1
            continue

        entity_name = _name_at(entity_names, index, f"Memory pool {entity_index}")
        sensor_definitions = (
            (
                "memory_usage_percent",
                _H3C_ENTITY_MEM_USAGE_OID,
                raw_usage,
                normalize_percentage(usage),
                "percent",
                "usage",
            ),
            (
                "memory_total_bytes",
                _H3C_ENTITY_MEM_SIZE_OID,
                raw_size,
                size,
                "bytes",
                "total",
            ),
        )
        for measurement_type, oid, raw_value, value, unit, measurement_key in sensor_definitions:
            sensor = _sensor(
                source_type="librenms_adapter",
                source_id=f"{rule_id}:mempool:{entity_index}:{measurement_key}",
                component_class="memory_pool",
                measurement_type=measurement_type,
                oid=oid,
                suffix=entity_index,
                raw_value=raw_value,
                value=value,
                unit=unit,
                sensor_name=entity_name,
                entity_name=entity_name,
                group_name="physical_memory",
                metadata={
                    "rule_id": rule_id,
                    "source_commit": source_commit,
                    "source_path": _H3C_COMWARE_PHP_SOURCE,
                    "os_key": "comware",
                    "adapter": _H3C_COMWARE_ADAPTER,
                    "adapter_source_files": [_H3C_COMWARE_PHP_SOURCE],
                    "mib": "HH3C-ENTITY-EXT-MIB",
                    "ent_physical_index": entity_index,
                    "ent_physical_index_measured": "entPhysicalIndex",
                    "index_suffix": entity_index,
                },
                poll_plan=_direct_plan(oid, entity_index),
            )
            if sensor:
                sensor["index_labels"]["ent_physical_index"] = entity_index
                sensors.append(sensor)
        memory_rows += 1

    memory_complete = all(read.complete and not read.reason for read in memory_reads.values())
    if memory_rows:
        memory_status = "success" if memory_complete and not malformed_memory_rows else "partial"
        memory_reason_code = "h3c_comware_memory_rows" if memory_status == "success" else "h3c_comware_memory_partial"
        memory_reason = f"LibreNMS Comware memory tables returned {memory_rows} module memory pool(s)"
        if not memory_complete:
            incomplete = [
                name for oid, name in (
                    (_H3C_ENTITY_MEM_USAGE_OID, "hh3cEntityExtMemUsage"),
                    (_H3C_ENTITY_MEM_SIZE_OID, "hh3cEntityExtMemSize"),
                    (_ENTITY_CLASS_OID, "entPhysicalClass"),
                )
                if not memory_reads[oid].complete or memory_reads[oid].reason
            ]
            memory_reason += "; incomplete walk(s): " + ", ".join(incomplete)
        if malformed_memory_rows:
            memory_reason += f"; skipped {malformed_memory_rows} malformed memory row(s)"
    elif memory_complete and not malformed_memory_rows:
        memory_status = "not_found"
        memory_reason_code = "no_comware_module_memory"
        memory_reason = "Comware memory walks completed without a positive-usage memory row on an ENTITY-MIB module"
    elif memory_complete:
        memory_status = "partial"
        memory_reason_code = "h3c_comware_memory_partial"
        memory_reason = f"Comware memory walks completed but {malformed_memory_rows} candidate row(s) were malformed"
    else:
        memory_status = "failed"
        memory_reason_code = "h3c_comware_memory_walk_failed"
        incomplete = [
            name for oid, name in (
                (_H3C_ENTITY_MEM_USAGE_OID, "hh3cEntityExtMemUsage"),
                (_H3C_ENTITY_MEM_SIZE_OID, "hh3cEntityExtMemSize"),
                (_ENTITY_CLASS_OID, "entPhysicalClass"),
            )
            if not memory_reads[oid].complete or memory_reads[oid].reason
        ]
        memory_reason = "Incomplete Comware memory discovery walk(s): " + ", ".join(incomplete)

    return {
        "sensors": sensors,
        "category_results": [
            _category_result(
                "librenms_adapter", "processor", status=cpu_status,
                complete=bool(cpu_rows and cpu_complete and not malformed_cpu_rows),
                reason_code=cpu_reason_code, reason=cpu_reason,
            ),
            _category_result(
                "librenms_adapter", "memory_pool", status=memory_status,
                complete=bool(memory_rows and memory_complete and not malformed_memory_rows),
                reason_code=memory_reason_code, reason=memory_reason,
            ),
        ],
    }


def _adapter_has_component(sensors: list[dict[str, Any]], component_class: str) -> bool:
    return any(
        str(sensor.get("component_class") or "").casefold() == component_class
        for sensor in sensors
        if isinstance(sensor, Mapping)
    )


def _adapter_sensor(
    *,
    rule: Mapping[str, Any],
    os_key: str,
    adapter: str,
    source_path: str,
    component_class: str,
    measurement_type: str,
    oid: str,
    suffix: str,
    raw_value: Any,
    value: float | None,
    sensor_name: str,
    poll_plan: Mapping[str, Any],
    processor_index: str = "",
    group_name: str = "",
    unit: str = "percent",
    source_key: str = "",
) -> dict[str, Any] | None:
    rule_id = str(rule.get("id") or os_key)
    sensor_identity = f"{source_key}:{suffix}" if source_key else suffix
    metadata: dict[str, Any] = {
        "rule_id": rule_id,
        "source_commit": str(rule.get("source_commit") or ""),
        "source_path": source_path,
        "os_key": os_key,
        "adapter": adapter,
        "adapter_source_files": [source_path],
        "index_suffix": suffix,
    }
    if processor_index:
        metadata["processor_index"] = processor_index
    return _sensor(
        source_type="librenms_adapter",
        source_id=f"{rule_id}:{adapter}:{component_class}:{sensor_identity}",
        component_class=component_class,
        measurement_type=measurement_type,
        oid=oid,
        suffix=suffix,
        raw_value=raw_value,
        value=value,
        unit=unit,
        sensor_name=sensor_name,
        entity_name=sensor_name,
        group_name=group_name or component_class,
        quality="good" if value is not None else "missing" if raw_value is None else "invalid",
        metadata=metadata,
        poll_plan=poll_plan,
    )


def _adapter_category(
    component_class: str,
    *,
    complete: bool,
    rows: int,
    reason_code: str,
    reason: str = "",
) -> dict[str, Any]:
    status = "success" if complete and rows else "not_found" if complete else "partial"
    if complete and not rows and not reason:
        reason = "The adapter walk completed, but LibreNMS returned no hardware instances."
    return _category_result(
        "librenms_adapter",
        component_class,
        status=status,
        complete=bool(complete),
        reason_code=reason_code if rows else f"{reason_code}_not_found" if complete else f"{reason_code}_partial",
        reason=reason,
    )


async def _probe_unifi_adapter(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
    existing_sensors: list[dict[str, Any]],
) -> dict[str, Any]:
    if _adapter_has_component(existing_sensors, "processor"):
        return {"sensors": [], "category_results": []}
    hr = await _walk_many(ip, community, {_HR_PROCESSOR_LOAD_OID}, port, version, walk_func=walk_func)
    hr_read = hr.get(_HR_PROCESSOR_LOAD_OID, WalkResult([], False, "missing_read"))
    if hr_read.rows:
        return {
            "sensors": [],
            "category_results": [_adapter_category(
                "processor", complete=hr_read.complete and not hr_read.reason, rows=len(hr_read.rows),
                reason_code="unifi_hr_processor_fallback", reason="HR processors exist; the shared HR collector owns these rows.",
            )],
        }
    oid = _LIBRENMS_OS_CPU_OIDS["unifi_frogfoot"]
    raw = (await _get_many(ip, community, {oid}, port, version)).get(oid)
    number = _number(raw)
    sensor = None
    if raw is not None and number is not None:
        sensor = _adapter_sensor(
            rule=rule, os_key="unifi", adapter="librenms_unifi_frogfoot_processor",
            source_path="LibreNMS/OS/Unifi.php", component_class="processor",
            measurement_type="cpu_usage_percent", oid=oid, suffix="0", raw_value=raw,
            value=normalize_percentage(number), sensor_name="Processor",
            poll_plan={"kind": "get", "oid": oid, "factor": 1.0, "offset": 0.0},
            processor_index="0",
        )
    complete = raw is not None and number is not None and hr_read.complete and not hr_read.reason
    return {
        "sensors": [sensor] if sensor else [],
        "category_results": [_adapter_category(
            "processor", complete=complete, rows=1 if sensor else 0,
            reason_code="unifi_frogfoot_processor", reason="Frogfoot fallback is used only when HR processor rows are absent.",
        )],
    }


async def _probe_viptela_adapter(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
    existing_sensors: list[dict[str, Any]],
) -> dict[str, Any]:
    if _adapter_has_component(existing_sensors, "processor"):
        return {"sensors": [], "category_results": []}
    oid = _LIBRENMS_OS_CPU_OIDS["viptela_idle"]
    raw = (await _get_many(ip, community, {oid}, port, version)).get(oid)
    number = _number(raw)
    value = normalize_percentage(100.0 - int(number)) if number is not None else None
    sensor = _adapter_sensor(
        rule=rule, os_key="viptela", adapter="librenms_viptela_idle_cpu",
        source_path="LibreNMS/OS/Viptela.php", component_class="processor",
        measurement_type="cpu_usage_percent", oid=oid, suffix="0", raw_value=raw,
        value=value, sensor_name="Processor",
        poll_plan={"kind": "get", "oid": oid, "factor": -1.0, "offset": 100.0, "integer_truncate": True},
        processor_index="0",
    )
    return {
        "sensors": [sensor] if sensor else [],
        "category_results": [_adapter_category(
            "processor", complete=raw is not None and number is not None, rows=1 if sensor else 0,
            reason_code="viptela_processor", reason="Viptela reports CPU idle; Nexora converts it to used percent.",
        )],
    }


async def _probe_smartax_adapter(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
    existing_sensors: list[dict[str, Any]],
) -> dict[str, Any]:
    if _adapter_has_component(existing_sensors, "processor"):
        return {"sensors": [], "category_results": []}
    cpu_oid = _LIBRENMS_OS_CPU_OIDS["smartax_cpu"]
    descr_oid = _LIBRENMS_OS_CPU_OIDS["smartax_descr"]
    reads = await _walk_many(ip, community, {cpu_oid, descr_oid}, port, version, walk_func=walk_func)
    cpu_read = reads.get(cpu_oid, WalkResult([], False, "missing_read"))
    descr_read = reads.get(descr_oid, WalkResult([], False, "missing_read"))
    descriptions = _row_map(descr_read)
    sensors: list[dict[str, Any]] = []
    for suffix, raw in cpu_read.rows:
        number = _number(raw)
        if number is None or number == -1:
            continue
        index = _index_parts(suffix)
        if index is None:
            continue
        label = descriptions.get(suffix) or f"Processor {suffix}"
        sensor = _adapter_sensor(
            rule=rule, os_key="smartax", adapter="librenms_smartax_processor",
            source_path="LibreNMS/OS/Smartax.php", component_class="processor",
            measurement_type="cpu_usage_percent", oid=cpu_oid, suffix=suffix,
            raw_value=raw, value=normalize_percentage(number),
            sensor_name=f"{label} processor",
            poll_plan={"kind": "direct", "oid": cpu_oid, "index": suffix, "factor": 1.0, "offset": 0.0},
            processor_index=suffix,
        )
        if sensor:
            sensors.append(sensor)
    complete = all(read.complete and not read.reason for read in (cpu_read, descr_read))
    return {
        "sensors": sensors,
        "category_results": [_adapter_category(
            "processor", complete=complete, rows=len(sensors), reason_code="smartax_processor_table",
            reason="SmartAX processors with usage -1 are filtered to match LibreNMS.",
        )],
    }


async def _probe_boss_adapter(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
    existing_sensors: list[dict[str, Any]],
) -> dict[str, Any]:
    if _adapter_has_component(existing_sensors, "processor"):
        return {"sensors": [], "category_results": []}
    oid = _LIBRENMS_OS_CPU_OIDS["boss_cpu"]
    read = (await _walk_many(ip, community, {oid}, port, version, walk_func=walk_func)).get(oid, WalkResult([], False, "missing_read"))
    sensors: list[dict[str, Any]] = []
    for count, (suffix, raw) in enumerate(sorted(read.rows, key=lambda item: _index_parts(item[0]) or []), start=1):
        number = _number(raw)
        if number is None or _index_parts(suffix) is None:
            continue
        processor_index = str(count).zfill(2)
        sensor = _adapter_sensor(
            rule=rule, os_key="boss", adapter="librenms_boss_processor",
            source_path="LibreNMS/OS/Boss.php", component_class="processor",
            measurement_type="cpu_usage_percent", oid=oid, suffix=suffix, raw_value=raw,
            value=normalize_percentage(number), sensor_name=f"Unit {count} processor",
            poll_plan={"kind": "direct", "oid": oid, "index": suffix, "factor": 1.0, "offset": 0.0},
            processor_index=processor_index,
        )
        if sensor:
            sensors.append(sensor)
    return {
        "sensors": sensors,
        "category_results": [_adapter_category(
            "processor", complete=read.complete and not read.reason, rows=len(sensors),
            reason_code="boss_processor_table",
        )],
    }


async def _probe_dlinkap_adapter(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
    existing_sensors: list[dict[str, Any]],
) -> dict[str, Any]:
    object_id = _numeric_oid(identity.get("sys_object_id"))
    if not object_id:
        return {"sensors": [], "category_results": [
            _category_result("librenms_adapter", "processor", status="failed", reason_code="dlinkap_missing_sysobjectid", reason="D-Link AP relative sensor OIDs require the discovered sysObjectID."),
            _category_result("librenms_adapter", "memory_pool", status="failed", reason_code="dlinkap_missing_sysobjectid", reason="D-Link AP relative sensor OIDs require the discovered sysObjectID."),
        ]}
    sensors: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    if not _adapter_has_component(existing_sensors, "processor"):
        cpu_oid = f"{object_id}.5.1.3.0"
        cpu_raw = (await _get_many(ip, community, {cpu_oid}, port, version)).get(cpu_oid)
        cpu_number = _number(cpu_raw)
        sensor = _adapter_sensor(
            rule=rule, os_key="dlinkap", adapter="librenms_dlinkap_processor",
            source_path="LibreNMS/OS/Dlinkap.php", component_class="processor",
            measurement_type="cpu_usage_percent", oid=cpu_oid, suffix="0", raw_value=cpu_raw,
            value=normalize_percentage(cpu_number / 100.0) if cpu_number is not None else None,
            sensor_name="Processor",
            poll_plan={"kind": "get", "oid": cpu_oid, "factor": 0.01, "offset": 0.0},
            processor_index="0",
        )
        if sensor:
            sensors.append(sensor)
        categories.append(_adapter_category("processor", complete=cpu_raw is not None and cpu_number is not None, rows=1 if sensor else 0, reason_code="dlinkap_processor"))
    if not _adapter_has_component(existing_sensors, "memory_pool"):
        memory_oid = f"{object_id}.5.1.4.0"
        memory_raw = (await _get_many(ip, community, {memory_oid}, port, version)).get(memory_oid)
        memory_number = _number(memory_raw)
        sensor = _adapter_sensor(
            rule=rule, os_key="dlinkap", adapter="librenms_dlinkap_mempool",
            source_path="LibreNMS/OS/Dlinkap.php", component_class="memory_pool",
            measurement_type="memory_usage_percent", oid=memory_oid, suffix="0", raw_value=memory_raw,
            value=normalize_percentage(memory_number), sensor_name="Memory",
            poll_plan={"kind": "get", "oid": memory_oid, "factor": 1.0, "offset": 0.0},
            processor_index="", group_name="system",
        )
        if sensor:
            sensors.append(sensor)
        categories.append(_adapter_category("memory_pool", complete=memory_raw is not None and memory_number is not None, rows=1 if sensor else 0, reason_code="dlinkap_mempool_percent"))
    return {"sensors": sensors, "category_results": categories}


async def _probe_aruba_instant_adapter(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
    existing_sensors: list[dict[str, Any]],
) -> dict[str, Any]:
    if _adapter_has_component(existing_sensors, "processor"):
        return {"sensors": [], "category_results": []}
    oid = _LIBRENMS_OS_CPU_OIDS["aruba_instant_cpu"]
    read = (await _walk_many(ip, community, {oid}, port, version, walk_func=walk_func)).get(oid, WalkResult([], False, "missing_read"))
    sensors: list[dict[str, Any]] = []
    for suffix, raw in read.rows:
        index = _index_parts(suffix)
        number = _number(raw)
        if index is None or number is None or len(index) != 6 or any(part < 0 or part > 255 for part in index):
            continue
        mac_hex = "".join(f"{part:02x}" for part in index)
        sensor = _adapter_sensor(
            rule=rule, os_key="aruba-instant", adapter="librenms_aruba_instant_processor",
            source_path="LibreNMS/OS/ArubaInstant.php", component_class="processor",
            measurement_type="cpu_usage_percent", oid=oid, suffix=suffix, raw_value=raw,
            value=normalize_percentage(number), sensor_name=f"AP {mac_hex} processor",
            poll_plan={"kind": "direct", "oid": oid, "index": suffix, "factor": 1.0, "offset": 0.0},
            processor_index=mac_hex,
        )
        if sensor:
            sensors.append(sensor)
    return {
        "sensors": sensors,
        "category_results": [_adapter_category(
            "processor", complete=read.complete and not read.reason, rows=len(sensors), reason_code="aruba_instant_processor_table",
            reason="CPU is keyed by the AP MAC address; the SNMP index is retained for polling.",
        )],
    }


async def _probe_powerconnect_adapter(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
    existing_sensors: list[dict[str, Any]],
) -> dict[str, Any]:
    if _adapter_has_component(existing_sensors, "processor"):
        return {"sensors": [], "category_results": []}
    object_id = _numeric_oid(identity.get("sys_object_id"))
    if object_id and any(object_id.startswith(prefix) for prefix in _POWERCONNECT_55XX_SYSOBJECT_PREFIXES):
        oid = _POWERCONNECT_NV_OID
        extract_percent = False
        adapter = "librenms_powerconnect_nv_processor"
    else:
        oid = _POWERCONNECT_VXWORKS_OID
        if object_id and any(object_id.startswith(prefix) for prefix in _POWERCONNECT_VXWORKS_9_SYSOBJECT_PREFIXES):
            oid = _POWERCONNECT_VXWORKS_55XX_OID
        extract_percent = True
        adapter = "librenms_powerconnect_vxworks_processor"
    raw = (await _get_many(ip, community, {oid}, port, version)).get(oid)
    if extract_percent and raw is not None:
        match = re.search(r"([0-9]+.[0-9]+)%", str(raw))
        value = normalize_percentage(_number(match.group(1)) if match else None)
    else:
        value = normalize_percentage(_number(raw))
    sensor = _adapter_sensor(
        rule=rule, os_key="powerconnect", adapter=adapter,
        source_path="LibreNMS/OS/Powerconnect.php", component_class="processor",
        measurement_type="cpu_usage_percent", oid=oid, suffix="0", raw_value=raw,
        value=value, sensor_name="Processor",
        poll_plan={"kind": "get", "oid": oid, "factor": 1.0, "offset": 0.0, "extract_percent": extract_percent},
        processor_index="0",
    )
    return {
        "sensors": [sensor] if sensor else [],
        "category_results": [_adapter_category(
            "processor", complete=raw is not None and value is not None, rows=1 if sensor else 0,
            reason_code="powerconnect_processor", reason="PowerConnect selects its VxWorks/NV processor OID by sysObjectID.",
        )],
    }


def _wireless_controller_scope(identity: Mapping[str, Any]) -> bool:
    role = str(identity.get("role") or identity.get("device_role") or "").strip().casefold()
    if role:
        return any(token in role for token in ("wireless", "wlan", "wlc", "access point")) or role in {"ap", "ac"}
    platform = str(identity.get("platform") or "").strip().casefold()
    if any(token in platform for token in ("wireless", "wlan", "wlc", "aireos")):
        return True
    vendor = str(identity.get("vendor") or "").strip().casefold()
    model = str(identity.get("model") or "").strip().casefold()
    if vendor in {"h3c", "comware"} and model.startswith("wx"):
        return True
    if vendor == "huawei" and (model.startswith("airengine") or re.match(r"^ac\d", model)):
        return True
    return False


def _vrp_wireless_ssid_index(suffix: str) -> tuple[str, bool] | None:
    """Decode the length-prefixed SSID OCTET STRING index used by VRP."""
    parts = _index_parts(suffix)
    if not parts or parts[0] > 128 or len(parts) != parts[0] + 1:
        return None
    octets = parts[1:]
    if any(value > 255 for value in octets):
        return None
    try:
        ssid = bytes(octets).decode("utf-8")
    except UnicodeDecodeError:
        return "hex:" + bytes(octets).hex(), False
    if any(not character.isprintable() for character in ssid):
        return "hex:" + bytes(octets).hex(), False
    return ssid[:120], True


def _vrp_fixed_mac_index(suffix: str) -> str | None:
    """Decode a table index whose first component is a fixed six-octet MAC."""
    parts = _index_parts(suffix)
    if parts is None or len(parts) != 6 or any(value < 0 or value > 255 for value in parts):
        return None
    return ":".join(f"{value:02x}" for value in parts)


def _vrp_mac_table_index(suffix: str, trailing_parts: int) -> tuple[str, list[int]] | None:
    """Decode a fixed six-octet MAC followed by numeric table indexes."""
    parts = _index_parts(suffix)
    if parts is None or len(parts) != 6 + trailing_parts:
        return None
    if any(value < 0 or value > 255 for value in parts[:6]):
        return None
    return ":".join(f"{value:02x}" for value in parts[:6]), parts[6:]


async def _probe_vrp_wireless_adapter(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
) -> dict[str, Any]:
    """Mirror LibreNMS VRP AP, radio, VAP and per-SSID wireless polling."""
    client_oids = {
        _VRP_WLAN_SSID_CLIENTS_2G_OID: "2.4GHz",
        _VRP_WLAN_SSID_CLIENTS_5G_OID: "5GHz",
    }
    ap_table_oids = {
        _VRP_WLAN_AP_SERIAL_OID,
        _VRP_WLAN_AP_TYPE_OID,
        _VRP_WLAN_AP_NAME_OID,
        _VRP_WLAN_AP_MEMORY_USAGE_OID,
        _VRP_WLAN_AP_CPU_USAGE_OID,
    }
    radio_oids = {
        _VRP_WLAN_RADIO_TYPE_OID,
        _VRP_WLAN_RADIO_CHANNEL_OID,
        _VRP_WLAN_RADIO_MAC_OID,
        _VRP_WLAN_RADIO_UTILIZATION_OID,
        _VRP_WLAN_RADIO_INTERFERENCE_OID,
        _VRP_WLAN_RADIO_EIRP_OID,
    }
    vap_oids = {_VRP_WLAN_VAP_CLIENTS_OID}
    all_walk_oids = set(client_oids) | ap_table_oids | radio_oids | vap_oids
    scalar_values, reads = await asyncio.gather(
        _get_many(ip, community, {_VRP_WLAN_AP_COUNT_OID}, port, version),
        _walk_many(ip, community, all_walk_oids, port, version, walk_func=walk_func),
    )
    sensors: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    ap_raw = scalar_values.get(_VRP_WLAN_AP_COUNT_OID)
    ap_count = _number(ap_raw)
    if ap_count is not None and math.isfinite(ap_count) and ap_count >= 0:
        sensor = _adapter_sensor(
            rule=rule, os_key="vrp", adapter="librenms_vrp_wireless",
            source_path="LibreNMS/OS/Vrp.php", component_class="wireless_controller",
            measurement_type="wireless_sensor_value", oid=_VRP_WLAN_AP_COUNT_OID,
            suffix="0", raw_value=ap_raw, value=ap_count, sensor_name="在线 AP 数",
            unit="count", group_name="wireless",
            poll_plan={"kind": "get", "oid": _VRP_WLAN_AP_COUNT_OID, "factor": 1.0, "offset": 0.0},
        )
        if sensor:
            sensor["series_variant"] = "ap-count"
            sensor["metadata"]["wireless_sensor_class"] = "ap-count"
            sensor["index_labels"].update({"controller": "true"})
            sensors.append(sensor)
    categories.append(_category_result(
        "librenms_adapter", "wireless_controller",
        status="success" if ap_count is not None and math.isfinite(ap_count) and ap_count >= 0 else "failed",
        complete=bool(ap_count is not None and math.isfinite(ap_count) and ap_count >= 0),
        reason_code="vrp_wireless_ap_count",
        reason="LibreNMS Vrp.php WirelessApCountDiscovery uses hwWlanCurJointApNum.",
    ))

    ap_fields = {
        "ap_name": _row_map(reads.get(_VRP_WLAN_AP_NAME_OID)),
        "ap_serial": _row_map(reads.get(_VRP_WLAN_AP_SERIAL_OID)),
        "ap_model": _row_map(reads.get(_VRP_WLAN_AP_TYPE_OID)),
    }
    ap_suffixes = set().union(*(set(values) for values in ap_fields.values()))
    ap_by_mac: dict[str, dict[str, str]] = {}
    for suffix in ap_suffixes:
        ap_mac = _vrp_fixed_mac_index(suffix)
        if not ap_mac:
            continue
        ap_info = {"ap_mac": ap_mac}
        for field, table in ap_fields.items():
            raw_field = table.get(suffix)
            text_field = _h3c_dot11_text(raw_field) if raw_field is not None else ""
            if text_field:
                ap_info[field] = text_field
        ap_by_mac[ap_mac] = ap_info

    for component_class, oid, measurement_type, display in (
        ("processor", _VRP_WLAN_AP_CPU_USAGE_OID, "cpu_usage_percent", "CPU 使用率"),
        ("memory_pool", _VRP_WLAN_AP_MEMORY_USAGE_OID, "memory_usage_percent", "内存使用率"),
    ):
        sensor_count = malformed_rows = 0
        metric_rows = _row_map(reads.get(oid))
        for suffix, raw in metric_rows.items():
            value = _number(raw)
            if value is None or not math.isfinite(value) or value < 0 or value > 100:
                malformed_rows += 1
                continue
            ap_mac = _vrp_fixed_mac_index(suffix)
            if not ap_mac:
                malformed_rows += 1
                continue
            ap_info = ap_by_mac.get(ap_mac, {"ap_mac": ap_mac})
            ap_name = str(ap_info.get("ap_name") or "")
            ap_identity = ap_name or f"AP {ap_mac}"
            sensor = _sensor(
                source_type="huawei_wireless",
                source_id=f"{str(rule.get('id') or 'vrp')}:huawei_wlan_ap:{measurement_type}:{suffix}",
                component_class=component_class,
                measurement_type=measurement_type,
                oid=oid,
                suffix=suffix,
                raw_value=raw,
                value=value,
                unit="percent",
                sensor_name=f"{ap_identity} {display}",
                entity_name=ap_identity,
                group_name="wireless",
                metadata={
                    "adapter": "nexora_huawei_wlan_ap_mib",
                    "adapter_source_files": ["HUAWEI-WLAN-AP-MIB"],
                    "mib": "HUAWEI-WLAN-AP-MIB",
                    "index_key": "hwWlanApMac",
                    "index_suffix": suffix,
                    "rule_id": str(rule.get("id") or "vrp"),
                    "source_commit": str(rule.get("source_commit") or ""),
                },
                poll_plan={"kind": "direct", "oid": oid, "index": suffix, "factor": 1.0, "offset": 0.0},
            )
            if sensor:
                sensor["series_variant"] = "ap_wlan_table"
                sensor["index_labels"].update(ap_info)
                sensors.append(sensor)
                sensor_count += 1
            else:
                malformed_rows += 1
        read = reads.get(oid, WalkResult([], False, "missing_read"))
        complete = bool(
            read.complete and not read.reason and malformed_rows == 0
            and (sensor_count > 0 or ap_count == 0)
        )
        status = "success" if sensor_count and complete else (
            "partial" if sensor_count or malformed_rows else "not_found" if complete else "failed"
        )
        categories.append(_category_result(
            "huawei_wireless", component_class,
            status=status,
            complete=complete,
            reason_code=f"huawei_wlan_ap_{component_class}",
            reason=f"HUAWEI-WLAN-AP-MIB per-AP {display} rows indexed by hwWlanApMac.",
        ))

    radio_value_specs = (
        (_VRP_WLAN_RADIO_TYPE_OID, "radio-type", "bitmask", "Radio type", None),
        (_VRP_WLAN_RADIO_CHANNEL_OID, "channel", "channel", "Working channel", None),
        (_VRP_WLAN_RADIO_UTILIZATION_OID, "utilization", "percent", "Channel utilization", 100),
        (_VRP_WLAN_RADIO_INTERFERENCE_OID, "interference", "percent", "Channel interference", 100),
        (_VRP_WLAN_RADIO_EIRP_OID, "tx-power", "dBm", "Actual EIRP", 127),
    )
    radio_suffixes: set[str] = set()
    for oid in radio_oids:
        radio_suffixes.update(_row_map(reads.get(oid)))
    radio_sensor_count = radio_malformed = radio_missing_fields = 0
    radio_mode_bits = ((1, "b"), (2, "a"), (4, "g"), (8, "n"), (16, "_ac"), (32, "_ax"))
    for suffix in sorted(radio_suffixes):
        decoded_index = _vrp_mac_table_index(suffix, 1)
        if decoded_index is None:
            radio_malformed += 1
            continue
        ap_mac, trailing = decoded_index
        radio_id = trailing[0]
        ap_info = dict(ap_by_mac.get(ap_mac) or {"ap_mac": ap_mac})
        radio_mac_raw = _row_map(reads.get(_VRP_WLAN_RADIO_MAC_OID)).get(suffix)
        radio_mac = _h3c_dot11_text(radio_mac_raw) if radio_mac_raw is not None else ""
        if radio_mac and re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", radio_mac, flags=re.IGNORECASE):
            ap_info["radio_mac"] = radio_mac.casefold()
        ap_name = str(ap_info.get("ap_name") or f"AP {ap_mac}")
        entity_name = f"{ap_name} Radio {radio_id}"
        labels: dict[str, Any] = {**ap_info, "radio_id": str(radio_id)}
        for oid, sensor_class, unit, display, upper_bound in radio_value_specs:
            raw = _row_map(reads.get(oid)).get(suffix)
            if raw is None:
                radio_missing_fields += 1
                continue
            number = _number(raw)
            if number is None or not math.isfinite(number) or number < 0 or not number.is_integer():
                radio_malformed += 1
                continue
            if upper_bound is not None and number > upper_bound:
                # Huawei uses values above 127 as an invalid/disabled EIRP;
                # percentages above 100 are also outside the MIB semantics.
                radio_malformed += 1
                continue
            if sensor_class == "tx-power" and number == 0:
                radio_malformed += 1
                continue
            sensor = _adapter_sensor(
                rule=rule, os_key="vrp", adapter="librenms_vrp_wireless",
                source_path="LibreNMS/OS/Vrp.php", component_class="wireless_radio",
                measurement_type="wireless_sensor_value", oid=oid, suffix=suffix,
                raw_value=raw, value=number, sensor_name=f"{entity_name} {display}",
                unit=unit, group_name="wireless",
                poll_plan={"kind": "direct", "oid": oid, "index": suffix, "factor": 1.0, "offset": 0.0},
                source_key=sensor_class,
            )
            if sensor:
                sensor["series_variant"] = f"radio_{sensor_class}"
                sensor["metadata"]["wireless_sensor_class"] = sensor_class
                sensor["metadata"]["adapter_source_files"] = [
                    "HUAWEI-WLAN-AP-RADIO-MIB", "HUAWEI-WLAN-AP-MIB",
                ]
                sensor["index_labels"].update(labels)
                if sensor_class == "radio-type":
                    mode = "dot11" + "".join(name for bit, name in radio_mode_bits if int(number) & bit)
                    if mode != "dot11":
                        sensor["index_labels"]["radio_mode"] = mode
                sensors.append(sensor)
                radio_sensor_count += 1
            else:
                radio_malformed += 1

    radio_walk_complete = all(
        reads.get(oid, WalkResult([], False, "missing_read")).complete
        and not reads.get(oid, WalkResult([], False, "missing_read")).reason
        for oid in radio_oids
    )
    radio_complete = bool(
        radio_walk_complete and radio_malformed == 0 and radio_missing_fields == 0
        and (radio_sensor_count > 0 or ap_count == 0)
    )
    radio_status = "success" if radio_sensor_count and radio_complete else (
        "partial" if radio_sensor_count else "not_found" if radio_complete else "failed"
    )
    categories.append(_category_result(
        "huawei_wireless", "wireless_radio", status=radio_status,
        complete=radio_complete,
        reason_code="huawei_wlan_radio_metrics",
        reason="LibreNMS Vrp.php polls Huawei radio type, working channel, radio MAC, utilization, interference and EIRP by AP MAC plus radio ID.",
    ))

    vap_read = reads.get(_VRP_WLAN_VAP_CLIENTS_OID, WalkResult([], False, "missing_read"))
    vap_rows = _row_map(vap_read)
    vap_sensor_count = vap_malformed = 0
    for suffix, raw in vap_rows.items():
        decoded_index = _vrp_mac_table_index(suffix, 2)
        count = _number(raw)
        if decoded_index is None or count is None or not math.isfinite(count) or count < 0 or not count.is_integer():
            vap_malformed += 1
            continue
        ap_mac, trailing = decoded_index
        radio_index, wlan_id = trailing
        ap_info = dict(ap_by_mac.get(ap_mac) or {"ap_mac": ap_mac})
        labels = {**ap_info, "radio_id": str(radio_index), "radio_index": str(radio_index), "wlan_id": str(wlan_id)}
        ap_name = str(ap_info.get("ap_name") or f"AP {ap_mac}")
        sensor = _adapter_sensor(
            rule=rule, os_key="vrp", adapter="librenms_vrp_wireless",
            source_path="LibreNMS/OS/Vrp.php", component_class="wireless_bss",
            measurement_type="wireless_sensor_value", oid=_VRP_WLAN_VAP_CLIENTS_OID,
            suffix=suffix, raw_value=raw, value=count,
            sensor_name=f"{ap_name} Radio {radio_index} WLAN {wlan_id} 客户端数",
            unit="count", group_name="wireless",
            poll_plan={"kind": "direct", "oid": _VRP_WLAN_VAP_CLIENTS_OID, "index": suffix, "factor": 1.0, "offset": 0.0},
            source_key="vap-clients",
        )
        if sensor:
            sensor["series_variant"] = "vap_clients"
            sensor["metadata"]["wireless_sensor_class"] = "clients"
            sensor["metadata"]["adapter_source_files"] = ["HUAWEI-WLAN-VAP-MIB", "HUAWEI-WLAN-AP-MIB"]
            sensor["index_labels"].update(labels)
            sensors.append(sensor)
            vap_sensor_count += 1
        else:
            vap_malformed += 1
    vap_complete = bool(
        vap_read.complete and not vap_read.reason and vap_malformed == 0
        and (vap_sensor_count > 0 or ap_count == 0)
    )
    vap_status = "success" if vap_sensor_count and vap_complete else (
        "partial" if vap_sensor_count else "not_found" if vap_complete else "failed"
    )
    categories.append(_category_result(
        "huawei_wireless", "wireless_bss", status=vap_status,
        complete=vap_complete,
        reason_code="huawei_wlan_vap_clients",
        reason="LibreNMS Vrp.php polls hwWlanVapStaOnlineCnt by AP MAC, radio index and WLAN ID; each raw VAP row remains independently pollable.",
    ))

    ssid_sensor_count = 0
    malformed = 0
    table_complete = all(reads[oid].complete and not reads[oid].reason for oid in client_oids)
    for oid, band in client_oids.items():
        for suffix, raw in _row_map(reads.get(oid)).items():
            decoded = _vrp_wireless_ssid_index(suffix)
            count = _number(raw)
            if decoded is None or count is None or not math.isfinite(count) or count < 0:
                malformed += 1
                continue
            ssid, ssid_is_text = decoded
            labels: dict[str, Any] = {"ssid_index": suffix, "radio_band": band}
            if ssid_is_text and ssid:
                labels["ssid"] = ssid
            title = f"SSID {ssid} ({band}) 客户端数" if ssid_is_text and ssid else f"SSID index {suffix} ({band}) 客户端数"
            sensor = _adapter_sensor(
                rule=rule, os_key="vrp", adapter="librenms_vrp_wireless",
                source_path="LibreNMS/OS/Vrp.php", component_class="wireless_ssid",
                measurement_type="wireless_sensor_value", oid=oid, suffix=suffix,
                raw_value=raw, value=count, sensor_name=title,
                unit="count", group_name="wireless",
                poll_plan={"kind": "direct", "oid": oid, "index": suffix, "factor": 1.0, "offset": 0.0},
                source_key=band.casefold(),
            )
            if sensor:
                sensor["series_variant"] = f"clients_{band.casefold()}"
                sensor["metadata"]["wireless_sensor_class"] = "clients"
                sensor["metadata"]["wireless_source_index"] = suffix
                sensor["index_labels"].update(labels)
                sensors.append(sensor)
                ssid_sensor_count += 1
            else:
                malformed += 1

    table_complete = table_complete and malformed == 0
    table_complete = table_complete and (ssid_sensor_count > 0 or ap_count == 0)
    table_status = "success" if ssid_sensor_count and table_complete else (
        "partial" if ssid_sensor_count else "not_found" if table_complete else "failed"
    )
    categories.append(_category_result(
        "librenms_adapter", "wireless_ssid", status=table_status,
        complete=table_complete,
        reason_code="vrp_wireless_ssid_clients",
        reason="LibreNMS Vrp.php discovers 2.4 GHz and 5 GHz client counts per encoded SSID index; dashboard aggregation sums bands and SSIDs.",
    ))
    return {"sensors": sensors, "category_results": categories}


async def _probe_vrp_adapter(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
    existing_sensors: list[dict[str, Any]],
) -> dict[str, Any]:
    need_processors = not _adapter_has_component(existing_sensors, "processor")
    need_mempools = not _adapter_has_component(existing_sensors, "memory_pool")
    oids: set[str] = set()
    if need_processors:
        oids.update({_VRP_CPU_USAGE_OID, _VRP_MEM_SIZE_OID, _VRP_BOM_DESCRIPTION_OID})
    if need_mempools:
        oids.update({
            _VRP_MEM_USAGE_OID,
            _VRP_MEM_SIZE_OID,
            _VRP_MEM_SIZE_MEGA_OID,
            _VRP_BOM_DESCRIPTION_OID,
            _ENTITY_NAME_OID,
        })
    reads = await _walk_many(ip, community, oids, port, version, walk_func=walk_func)
    rows = {oid: _row_map(reads.get(oid)) for oid in oids}
    sensors: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []

    if need_processors:
        cpu_oid = _VRP_CPU_USAGE_OID
        cpu_rows = rows.get(cpu_oid, {})
        size_rows = rows.get(_VRP_MEM_SIZE_OID, {})
        descriptions = rows.get(_VRP_BOM_DESCRIPTION_OID, {})
        cpu_sensors = 0
        malformed = 0
        for suffix, raw in cpu_rows.items():
            index = _index_parts(suffix)
            usage = _number(raw)
            size = _number(size_rows.get(suffix))
            description = str(descriptions.get(suffix) or "").strip()
            if index is None or usage is None or size is None:
                malformed += 1
                continue
            if size == 0 or not description or "No" in description or "No" in str(raw):
                continue
            sensor = _adapter_sensor(
                rule=rule, os_key="vrp", adapter="librenms_vrp_processor",
                source_path="LibreNMS/OS/Vrp.php", component_class="processor",
                measurement_type="cpu_usage_percent", oid=cpu_oid, suffix=suffix,
                raw_value=raw, value=normalize_percentage(usage), sensor_name=description,
                poll_plan={"kind": "direct", "oid": cpu_oid, "index": suffix, "factor": 1.0, "offset": 0.0},
                processor_index=suffix,
            )
            if sensor:
                sensors.append(sensor)
                cpu_sensors += 1
        cpu_complete = all(
            reads.get(oid, WalkResult([], False, "missing_read")).complete
            and not reads.get(oid, WalkResult([], False, "missing_read")).reason
            for oid in (cpu_oid, _VRP_MEM_SIZE_OID, _VRP_BOM_DESCRIPTION_OID)
        ) and malformed == 0
        categories.append(_adapter_category(
            "processor", complete=cpu_complete, rows=cpu_sensors,
            reason_code="vrp_processor_entity_filter",
            reason="Matches LibreNMS entity-size and description filtering for VRP processors.",
        ))

    if need_mempools:
        usage_oid = _VRP_MEM_USAGE_OID
        usage_rows = rows.get(usage_oid, {})
        size_rows = rows.get(_VRP_MEM_SIZE_OID, {})
        mega_rows = rows.get(_VRP_MEM_SIZE_MEGA_OID, {})
        descriptions = rows.get(_VRP_BOM_DESCRIPTION_OID, {})
        entity_names = rows.get(_ENTITY_NAME_OID, {})
        pool_count = 0
        malformed = 0
        for suffix, usage_raw in usage_rows.items():
            index = _index_parts(suffix)
            usage = _number(usage_raw)
            mega_size = _number(mega_rows.get(suffix))
            byte_size = _number(size_rows.get(suffix))
            description = str(entity_names.get(suffix) or descriptions.get(suffix) or "").strip()
            if index is None or usage is None:
                malformed += 1
                continue
            if not description or "No" in description or "No" in str(usage_raw):
                continue
            if mega_size is not None and mega_size != 0:
                total_raw = mega_rows.get(suffix)
                total_oid = _VRP_MEM_SIZE_MEGA_OID
                precision = 1048576.0
                total_number = mega_size
            else:
                total_raw = size_rows.get(suffix)
                total_oid = _VRP_MEM_SIZE_OID
                precision = 1.0
                total_number = byte_size
            if total_number is None or total_number <= 0:
                malformed += 1
                continue
            relation_values = {"total": total_raw, "percent_used": usage_raw}
            metrics = _mempool_metric_values(
                relation_values, factor=1.0, offset=0.0,
                precision=precision, unit_factor=1.0,
            )
            label = f"{description} Memory"[:64]
            relations = {
                "total": {"kind": "oid", "oid": total_oid, "index": suffix},
                "percent_used": {"kind": "oid", "oid": usage_oid, "index": suffix},
            }
            for target, measurement, unit in (
                ("used", "memory_used_bytes", "bytes"),
                ("total", "memory_total_bytes", "bytes"),
                ("percent_used", "memory_usage_percent", "percent"),
            ):
                sample_oid = usage_oid if target in {"used", "percent_used"} else total_oid
                sensor = _adapter_sensor(
                    rule=rule, os_key="vrp", adapter="librenms_vrp_mempool",
                    source_path="LibreNMS/OS/Vrp.php", component_class="memory_pool",
                    measurement_type=measurement, oid=sample_oid, suffix=suffix,
                    raw_value=usage_raw if target == "percent_used" else total_raw,
                    value=metrics.get(target), sensor_name=label,
                    group_name="system", unit=unit,
                    poll_plan={
                        "kind": "memory_pool", "index": suffix, "target": target,
                        "relations": relations, "factor": 1.0, "offset": 0.0,
                        "precision": precision, "precision_supported": True,
                        "unit_factor": 1.0, "unit_supported": True,
                        "skip_conditions_supported": True, "transform_supported": True,
                    },
                )
                if sensor:
                    sensors.append(sensor)
            pool_count += 1
        mem_complete = all(
            reads.get(oid, WalkResult([], False, "missing_read")).complete
            and not reads.get(oid, WalkResult([], False, "missing_read")).reason
            for oid in (usage_oid, _VRP_MEM_SIZE_OID, _VRP_MEM_SIZE_MEGA_OID, _VRP_BOM_DESCRIPTION_OID, _ENTITY_NAME_OID)
        ) and malformed == 0
        categories.append(_adapter_category(
            "memory_pool", complete=mem_complete, rows=pool_count,
            reason_code="vrp_mempool_entity_filter",
            reason="Uses HUAWEI-ENTITY-EXTENT-MIB size and usage, preferring entPhysicalName then BOM description.",
        ))

    if _wireless_controller_scope(identity):
        wireless = await _probe_vrp_wireless_adapter(
            ip, community, port, rule=rule, version=version, walk_func=walk_func,
        )
        sensors.extend(wireless.get("sensors") or [])
        categories.extend(wireless.get("category_results") or [])
    return {"sensors": sensors, "category_results": categories}


_LIBRENMS_OS_HARDWARE_ADAPTERS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "aruba-instant": _probe_aruba_instant_adapter,
    "boss": _probe_boss_adapter,
    "dlinkap": _probe_dlinkap_adapter,
    "powerconnect": _probe_powerconnect_adapter,
    "smartax": _probe_smartax_adapter,
    "unifi": _probe_unifi_adapter,
    "viptela": _probe_viptela_adapter,
    "vrp": _probe_vrp_adapter,
}


async def probe_librenms_hardware(
    ip: str,
    community: str,
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str = "2c",
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None = None,
) -> dict[str, Any]:
    """Probe every structured OS rule row and retain each returned index."""
    hardware = rule.get("hardware_definitions")
    if not isinstance(hardware, Mapping):
        hardware = {}
    vendor = str(rule.get("vendor") or identity.get("vendor") or "").strip().casefold()
    os_key = str(rule.get("os_key") or "").strip().casefold()
    h3c_comware = vendor in {"h3c", "comware"} and os_key == "comware"
    os_adapter = _LIBRENMS_OS_HARDWARE_ADAPTERS.get(os_key)
    definitions: list[dict[str, Any]] = []
    for section in ("processors", "mempools", "sensors"):
        rows = hardware.get(section)
        if isinstance(rows, list):
            definitions.extend(dict(item) for item in rows if isinstance(item, Mapping))
    if not definitions and not h3c_comware and os_adapter is None:
        return {"sensors": [], "category_results": []}

    db_conn = None
    try:
        db_conn = get_db_connection()
    except Exception:
        db_conn = None
    try:
        resolved: list[dict[str, Any]] = []
        needed_oids: set[str] = set()
        mib_cache: dict[tuple[str, str], str] = {}
        for definition in definitions:
            item = dict(definition)
            oid = _resolve_definition_oid(
                db_conn,
                item,
                vendor=vendor,
                cache=mib_cache,
            ) if db_conn is not None else _numeric_oid(
                item.get("numeric_oid_prefix") or item.get("num_oid") or item.get("value_oid") or item.get("table_oid")
            )
            item["_probe_oid"] = oid
            if oid:
                needed_oids.add(oid)
            template_oids: dict[str, str] = {}
            for template in (item.get("descr"), item.get("index")):
                for match in re.finditer(r"\{\{\s*([A-Za-z0-9_-]+::[A-Za-z0-9_-]+(?::[0-9]+(?:\.[0-9]+)*)?)\s*\}\}", str(template or "")):
                    token = match.group(1)
                    mib_symbol = token.split(":", 1)[0]
                    template_oid = _resolve_mib_symbol(
                        db_conn,
                        mib_symbol,
                        vendor=vendor,
                        cache=mib_cache,
                    ) if db_conn is not None else ""
                    if template_oid:
                        template_oids[token] = template_oid
                        needed_oids.add(template_oid)
            item["_template_oids"] = template_oids
            skip_conditions, skip_oids, skip_supported = _compile_skip_conditions(
                item.get("skip_values"), db_conn=db_conn, vendor=vendor,
                identity=identity,
                cache=mib_cache,
            )
            for condition in skip_conditions:
                if (
                    isinstance(condition, dict)
                    and condition.get("_oid") == oid
                    and str(item.get("source_module") or "").casefold() != "mempools"
                ):
                    condition["_value_oid"] = True
            item["_skip_conditions"] = skip_conditions
            item["_skip_conditions_supported"] = skip_supported
            needed_oids.update(skip_oids)
            memory = item.get("memory") if isinstance(item.get("memory"), Mapping) else {}
            memory_relations = _memory_relations_for_definition(item)
            resolved_relations: dict[str, dict[str, Any]] = {}
            for key, relation in memory_relations.items():
                if relation.get("kind") == "constant":
                    resolved_relations[key] = {"kind": "constant", "value": relation.get("value")}
                    continue
                if relation.get("kind") != "oid":
                    resolved_relations[key] = {"kind": "unsupported", "source": relation.get("value")}
                    continue
                relation_token = relation.get("value")
                memory_oid = _numeric_oid(relation_token)
                if not memory_oid and db_conn is not None:
                    memory_oid = _resolve_mib_symbol(
                        db_conn,
                        relation_token,
                        vendor=vendor,
                        cache=mib_cache,
                    )
                if memory_oid:
                    resolved_relations[key] = {"kind": "oid", "oid": memory_oid}
                    item[f"_{key}_oid"] = memory_oid
                    needed_oids.add(memory_oid)
                else:
                    resolved_relations[key] = {"kind": "unsupported", "source": relation_token}
                item.setdefault(f"_{key}_oid", "")
            for key in ("used", "total", "free", "percent_used"):
                item.setdefault(f"_{key}_oid", "")
            item["_memory_relations"] = resolved_relations
            item["_memory_relations_supported"] = all(
                relation.get("kind") in {"oid", "constant"}
                for relation in resolved_relations.values()
            )
            item["_allocation_unit"] = memory.get("allocation_unit")
            item["_allocation_unit_oid"] = ""
            item["_allocation_unit_factor"] = 1.0
            item["_allocation_unit_supported"] = True
            unit_token = memory.get("allocation_unit")
            unit_number = _number(unit_token)
            unit_name = str(unit_token or "").strip().casefold()
            unit_factors = {
                "byte": 1.0, "bytes": 1.0, "b": 1.0,
                "kilobyte": 1024.0, "kilobytes": 1024.0, "kb": 1024.0,
                "kib": 1024.0, "kibibyte": 1024.0, "kibibytes": 1024.0,
                "megabyte": 1048576.0, "megabytes": 1048576.0, "mb": 1048576.0,
                "mib": 1048576.0, "mebibyte": 1048576.0, "mebibytes": 1048576.0,
            }
            if unit_token in (None, ""):
                pass
            elif unit_number is not None:
                item["_allocation_unit_factor"] = unit_number
            elif unit_name in unit_factors:
                item["_allocation_unit_factor"] = unit_factors[unit_name]
            elif isinstance(unit_token, str):
                unit_oid = _numeric_oid(unit_token)
                if not unit_oid and db_conn is not None:
                    unit_oid = _resolve_mib_symbol(
                        db_conn,
                        unit_token,
                        vendor=vendor,
                        cache=mib_cache,
                    )
                item["_allocation_unit_oid"] = unit_oid
                if unit_oid:
                    needed_oids.add(unit_oid)
                else:
                    item["_allocation_unit_supported"] = False
            else:
                item["_allocation_unit_supported"] = False
            resolved.append(item)
        reads = await _walk_many(ip, community, needed_oids, port, version, walk_func=walk_func)
    finally:
        if db_conn is not None:
            db_conn.close()

    rows_by_oid = {oid: _row_map(read) for oid, read in reads.items()}
    complete_oids = {
        oid for oid, read in reads.items()
        if read.complete and not read.reason
    }
    entity_names: dict[str, str] = {}
    # ENTITY-MIB naming data is shared by every vendor's hardware definition.
    if resolved or not h3c_comware:
        try:
            entity_reads = await _walk_many(
                ip, community, {_ENTITY_NAME_OID}, port, version, walk_func=walk_func,
            )
            entity_names = _row_map(entity_reads.get(_ENTITY_NAME_OID))
        except Exception:
            entity_names = {}

    by_class: dict[str, dict[str, Any]] = {}
    sensors: list[dict[str, Any]] = []
    rule_id = str(rule.get("id") or rule.get("os_key") or "librenms")
    source_commit = str(rule.get("source_commit") or "")
    source_path = str(rule.get("discovery_source_path") or rule.get("source_path") or "")
    for definition_index, definition in enumerate(resolved):
        component_info = _measurement_for_entry(definition)
        component_scope = str(definition.get("component_class") or "sensor").casefold()
        scope = by_class.setdefault(component_scope, {"rows": 0, "complete": True, "supported": True, "definitions": 0})
        scope["definitions"] += 1
        oid = str(definition.get("_probe_oid") or "")
        measurement_info = component_info
        is_mempool = str(definition.get("source_module") or "").casefold() == "mempools"
        if (not oid and not is_mempool) or not measurement_info:
            scope["supported"] = False
            scope["complete"] = False
            continue
        component_class, measurement_type, unit = measurement_info
        raw_definition = definition.get("raw") if isinstance(definition.get("raw"), Mapping) else {}
        transform = _numeric_transform(definition)
        user_func = definition.get("user_func")
        native_transform_supported = supports_librenms_user_func(user_func) and not (
            bool(user_func) and str(definition.get("source_module") or "") == "mempools"
        )
        if not native_transform_supported:
            # Unknown PHP symbols stay unavailable; never emit their raw value
            # under a converted metric name.
            scope["supported"] = False
            scope["complete"] = False
        skip_conditions = definition.get("_skip_conditions")
        skip_supported = bool(definition.get("_skip_conditions_supported", True))
        if not skip_supported:
            scope["supported"] = False
            scope["complete"] = False
        condition_oids = {
            str(item.get("_oid")) for item in (skip_conditions or [])
            if isinstance(item, Mapping) and item.get("_oid") and not item.get("_index")
        }
        for condition_oid in condition_oids:
            condition_read = reads.get(condition_oid)
            if condition_read is None or not condition_read.complete or condition_read.reason:
                scope["complete"] = False
        if measurement_type != "component_state" and transform is None:
            scope["supported"] = False
            scope["complete"] = False
            continue

        # Mempools define related OIDs, not a single percentage sensor. Build
        # only measurements with explicit semantics and preserve pool index.
        if is_mempool:
            relations = definition.get("_memory_relations") if isinstance(definition.get("_memory_relations"), Mapping) else {}
            targets = _mempool_targets(relations)
            precision_factor, precision_supported = _mempool_precision(definition)
            if not relations or not targets:
                scope["supported"] = False
                scope["complete"] = False
                continue
            if not definition.get("_memory_relations_supported", True):
                scope["supported"] = False

            relation_oids = {
                str(relation.get("oid") or "")
                for relation in relations.values()
                if isinstance(relation, Mapping) and relation.get("kind") == "oid" and relation.get("oid")
            }
            unit_oid = str(definition.get("_allocation_unit_oid") or "")
            all_indices: set[str] = set()
            for relation_oid in relation_oids:
                all_indices.update(rows_by_oid.get(relation_oid, {}))
            if unit_oid:
                all_indices.update(rows_by_oid.get(unit_oid, {}))
            if not all_indices and oid:
                all_indices.update(rows_by_oid.get(oid, {}))
            if not all_indices:
                explicit_index = _mempool_explicit_index(definition)
                if explicit_index:
                    all_indices.add(explicit_index)
            if not all_indices:
                required_oids = relation_oids | ({unit_oid} if unit_oid else set())
                if not required_oids and oid:
                    required_oids.add(oid)
                read_complete = all(reads.get(item, WalkResult([], False)).complete and not reads.get(item, WalkResult([], False)).reason for item in required_oids)
                scope["complete"] = scope["complete"] and read_complete
                continue

            factor, offset = transform
            relation_plan_base: dict[str, dict[str, Any]] = {}
            for name, relation in relations.items():
                if not isinstance(relation, Mapping):
                    continue
                if relation.get("kind") == "constant":
                    relation_plan_base[name] = {"kind": "constant", "value": relation.get("value")}
                elif relation.get("kind") == "oid" and relation.get("oid"):
                    relation_plan_base[name] = {"kind": "oid", "oid": str(relation["oid"])}
            if not relation_plan_base:
                scope["supported"] = False
                scope["complete"] = False
                continue

            static_unit_factor = _number(definition.get("_allocation_unit_factor"))
            unit_supported = bool(definition.get("_allocation_unit_supported", True))
            for suffix in sorted(all_indices):
                relation_values: dict[str, Any] = {}
                relation_plan: dict[str, dict[str, Any]] = {}
                for name, relation in relation_plan_base.items():
                    if relation.get("kind") == "constant":
                        relation_values[name] = relation.get("value")
                        relation_plan[name] = dict(relation)
                    else:
                        relation_oid = str(relation.get("oid") or "")
                        relation_values[name] = rows_by_oid.get(relation_oid, {}).get(suffix)
                        relation_plan[name] = {**relation, "index": suffix}

                unit_factor = static_unit_factor if static_unit_factor is not None else None
                unit_value_raw = rows_by_oid.get(unit_oid, {}).get(suffix) if unit_oid else None
                if unit_oid:
                    unit_factor = _number(unit_value_raw)
                unit_valid = unit_supported and unit_factor is not None and unit_factor > 0
                preferred_raw = next((relation_values.get(name) for name in ("used", "percent_used", "total", "free") if relation_values.get(name) is not None), None)
                condition_values, condition_complete = _condition_values_at_index(
                    skip_conditions, suffix=suffix, raw_value=preferred_raw,
                    rows_by_oid=rows_by_oid, complete_oids=complete_oids,
                )
                skip_result = _skip_value(
                    preferred_raw, skip_conditions, condition_values=condition_values,
                )
                if skip_result is True:
                    continue
                if not condition_complete:
                    scope["complete"] = False
                memory_quality = (
                    "unsupported_mapping" if not skip_supported or skip_result is None
                    else "missing" if not condition_complete
                    else "good"
                )
                relation_walks_complete = all(
                    reads.get(relation_oid, WalkResult([], False, "missing_read")).complete
                    and not reads.get(relation_oid, WalkResult([], False, "missing_read")).reason
                    for relation_oid in relation_oids
                )
                if memory_quality == "good" and not relation_walks_complete:
                    memory_quality = "missing"
                if memory_quality == "good" and unit_oid:
                    unit_read = reads.get(unit_oid, WalkResult([], False, "missing_read"))
                    if not unit_read.complete or unit_read.reason:
                        memory_quality = "missing"
                if memory_quality == "good" and not definition.get("_memory_relations_supported", True):
                    memory_quality = "unsupported_mapping"
                if not native_transform_supported:
                    memory_quality = "unsupported_mapping"
                if memory_quality == "unsupported_mapping":
                    scope["supported"] = False

                metrics = _mempool_metric_values(
                    relation_values,
                    factor=factor,
                    offset=offset,
                    precision=precision_factor,
                    unit_factor=unit_factor if unit_valid else None,
                )
                index = _index_parts(suffix)
                if index is None:
                    scope["supported"] = False
                    continue
                entity_name = _name_at(entity_names, index, f"Memory pool {suffix}")
                fallback_oid = next(iter(sorted(relation_oids)), unit_oid or oid)
                common_poll_plan = {
                    "kind": "memory_pool",
                    "index": suffix,
                    "relations": relation_plan,
                    "factor": factor,
                    "offset": offset,
                    "precision": precision_factor,
                    "precision_supported": precision_supported,
                    "unit_factor": static_unit_factor,
                    "unit_oid": unit_oid,
                    "unit_supported": unit_supported,
                    "skip_values": skip_conditions,
                    "skip_conditions_supported": skip_supported,
                    "transform_supported": native_transform_supported,
                }
                metric_specs = (
                    ("used", "memory_used_bytes", "bytes"),
                    ("total", "memory_total_bytes", "bytes"),
                    ("percent_used", "memory_usage_percent", "percent"),
                )
                for target, measurement, sample_unit in metric_specs:
                    if target not in targets:
                        continue
                    sample_value = metrics.get(target)
                    sample_quality = memory_quality
                    if sample_quality == "good" and target in {"used", "total"} and not precision_supported:
                        sample_quality = "unsupported_mapping"
                    if sample_quality == "good" and target in {"used", "total"} and not unit_valid:
                        sample_quality = "unsupported_mapping" if not unit_supported else "missing"
                    if sample_quality == "good" and sample_value is None:
                        sample_quality = "missing" if preferred_raw is None else "invalid"
                    sample_oid = str(
                        (relation_plan.get(target) or {}).get("oid")
                        or (relation_plan.get("used") or {}).get("oid")
                        or (relation_plan.get("percent_used") or {}).get("oid")
                        or (relation_plan.get("total") or {}).get("oid")
                        or (relation_plan.get("free") or {}).get("oid")
                        or fallback_oid
                        or ""
                    )
                    if not sample_oid:
                        scope["supported"] = False
                        scope["complete"] = False
                        continue
                    template_values = _template_mib_values(definition, suffix, rows_by_oid)
                    display, descr_unresolved = _render_librenms_index_template(definition.get("descr"), suffix, preferred_raw, template_values)
                    librenms_index, index_unresolved = _render_librenms_index_template(definition.get("index"), suffix, preferred_raw, template_values)
                    sensor_metadata = {
                        "rule_id": rule_id,
                        "source_commit": source_commit,
                        "source_path": source_path,
                        "os_key": rule.get("os_key"),
                        "definition_index": definition_index,
                        "raw_definition": raw_definition,
                        "allocation_unit": definition.get("_allocation_unit"),
                        "precision": definition.get("precision"),
                        "index_suffix": suffix,
                        "skip_values": skip_conditions,
                        "skip_conditions_supported": skip_supported,
                    }
                    if definition.get("index") not in (None, ""):
                        sensor_metadata["librenms_index_template"] = definition.get("index")
                        sensor_metadata["librenms_index"] = librenms_index
                    unresolved_templates = [*(f"descr:{token}" for token in descr_unresolved), *(f"index:{token}" for token in index_unresolved)]
                    if unresolved_templates:
                        sensor_metadata["unresolved_templates"] = unresolved_templates
                        scope["supported"] = False
                    sensor = _sensor(
                        source_type="librenms", source_id=rule_id,
                        component_class="memory_pool", measurement_type=measurement,
                        oid=sample_oid, suffix=suffix,
                        raw_value=relation_values.get(target) if relation_values.get(target) is not None else preferred_raw,
                        value=sample_value if sample_quality == "good" else None,
                        unit=sample_unit,
                        sensor_name=display or entity_name, entity_name=entity_name,
                        group_name=str(definition.get("group") or definition.get("memory", {}).get("pool_class") or "memory"),
                        quality=sample_quality,
                        states={}, thresholds=definition.get("limits"),
                        metadata=sensor_metadata,
                        poll_plan={**common_poll_plan, "target": target},
                    )
                    if sensor:
                        if librenms_index:
                            labels = sensor.get("index_labels") if isinstance(sensor.get("index_labels"), dict) else {}
                            labels["librenms_index"] = librenms_index
                            sensor["index_labels"] = labels
                        _apply_ent_physical_metadata(sensor, definition, suffix)
                        sensors.append(sensor)
                        scope["rows"] += 1

                if not precision_supported or (not unit_supported and any(target in targets for target in ("used", "total"))):
                    scope["supported"] = False

            required_oids = relation_oids | ({unit_oid} if unit_oid else set())
            if not required_oids and oid:
                required_oids.add(oid)
            scope["complete"] = scope["complete"] and all(
                reads.get(item, WalkResult([], False)).complete and not reads.get(item, WalkResult([], False)).reason
                for item in required_oids
            )
            continue

        rows = rows_by_oid.get(oid, {})
        read = reads.get(oid, WalkResult([], False))
        scope["complete"] = scope["complete"] and read.complete and not read.reason
        poll_factor, poll_offset = (transform or (1.0, 0.0))
        user_func_key = str(user_func or "").rsplit("::", 1)[-1].strip("\\").casefold()
        if measurement_type == "temperature_celsius" and user_func_key.endswith("fahrenheit_to_celsius"):
            unit = "celsius"
        elif measurement_type != "component_state":
            converted = _canonical_unit_transform(
                measurement_type,
                definition.get("unit") or definition.get("units"),
                poll_factor,
                poll_offset,
            )
            if converted is None:
                scope["supported"] = False
                scope["complete"] = False
                continue
            poll_factor, poll_offset, canonical_unit = converted
            unit = canonical_unit or unit
        for suffix, raw_value in rows.items():
            condition_values, condition_complete = _condition_values_at_index(
                skip_conditions, suffix=suffix, raw_value=raw_value,
                rows_by_oid=rows_by_oid, complete_oids=complete_oids,
            )
            skipped = _skip_value(
                raw_value, skip_conditions, condition_values=condition_values,
            )
            if skipped is True:
                continue
            if not condition_complete:
                scope["complete"] = False
            if not skip_supported or skipped is None:
                scope["supported"] = False
            value: float | None
            quality = (
                "unsupported_mapping" if not skip_supported or skipped is None
                else "missing" if not condition_complete
                else "good"
            )
            if not native_transform_supported and quality == "good":
                quality = "unsupported_mapping"
            states_map: dict[str, int] = {}
            state_definitions = definition.get("states") or definition.get("state_mapping") or {}
            presence_status = "present"
            if measurement_type == "component_state":
                state_input: Any = raw_value
                if user_func:
                    scaled_input = _number(raw_value)
                    transformed_input = apply_librenms_user_func(
                        user_func,
                        scaled_input * poll_factor + poll_offset if scaled_input is not None else None,
                        raw_value=raw_value,
                        index_suffix=suffix,
                        definition=raw_definition,
                    )
                    if transformed_input is None:
                        quality = "invalid" if native_transform_supported else "unsupported_mapping"
                    else:
                        state_input = transformed_input
                value, states_map, mapped_quality = _mapped_state(state_input, state_definitions)
                if quality == "good":
                    quality = mapped_quality
                presence_status = _state_presence(state_input, state_definitions) or "present"
            else:
                raw_number = _number(raw_value)
                if raw_number is None:
                    value, quality = None, "invalid"
                else:
                    value = raw_number * poll_factor + poll_offset
                    processor_precision = _number(definition.get("precision"))
                    invert_idle_cpu = (
                        measurement_type == "cpu_usage_percent"
                        and str(definition.get("source_module") or "").casefold() == "processors"
                        and processor_precision is not None
                        and processor_precision < 0
                    )
                    if invert_idle_cpu:
                        value = 100.0 - value
                    if user_func:
                        value = apply_librenms_user_func(
                            user_func,
                            value,
                            raw_value=raw_value,
                            index_suffix=suffix,
                            definition=raw_definition,
                        )
                        if value is None:
                            quality = "invalid" if native_transform_supported else "unsupported_mapping"
                        elif measurement_type == "temperature_celsius" and user_func_key.endswith("fahrenheit_to_celsius"):
                            unit = "celsius"
            if quality != "good":
                value = None
            index = _index_parts(suffix)
            if index is None:
                scope["supported"] = False
                continue
            fallback = f"{component_class.replace('_', ' ').title()} {suffix}"
            entity_name = _name_at(entity_names, index, fallback)
            template_values = _template_mib_values(definition, suffix, rows_by_oid)
            display, descr_unresolved = _render_librenms_index_template(definition.get("descr"), suffix, raw_value, template_values)
            librenms_index, index_unresolved = _render_librenms_index_template(definition.get("index"), suffix, raw_value, template_values)
            sensor_name = display or (entity_name if entity_name and not entity_name.startswith("Entity sensor ") else fallback)
            source_id = f"{rule_id}:{definition.get('source_module')}:{definition.get('source_class')}:{oid}"
            sensor_metadata = {
                "rule_id": rule_id,
                "source_commit": source_commit,
                "source_path": source_path,
                "os_key": rule.get("os_key"),
                "definition_index": definition_index,
                "index_suffix": suffix,
                "skip_values": skip_conditions,
                "skip_conditions_supported": skip_supported,
                "precision": definition.get("precision"),
                "window": _explicit_cpu_window(definition) if measurement_type == "cpu_usage_percent" else "",
                "raw_definition": raw_definition,
                "series_variant": f"librenms_index:{librenms_index}" if librenms_index else "",
            }
            if definition.get("index") not in (None, ""):
                sensor_metadata["librenms_index_template"] = definition.get("index")
                sensor_metadata["librenms_index"] = librenms_index
            unresolved_templates = [*(f"descr:{token}" for token in descr_unresolved), *(f"index:{token}" for token in index_unresolved)]
            if unresolved_templates:
                sensor_metadata["unresolved_templates"] = unresolved_templates
                scope["supported"] = False
            sensor = _sensor(
                source_type="librenms", source_id=source_id,
                component_class=component_class, measurement_type=measurement_type,
                oid=oid, suffix=suffix, raw_value=raw_value, value=value,
                unit=unit, sensor_name=sensor_name,
                entity_name=entity_name, group_name=str(definition.get("group") or component_class),
                quality=quality, states=state_definitions or states_map,
                thresholds=definition.get("limits"),
                presence_status=presence_status,
                metadata=sensor_metadata,
                poll_plan={**_direct_plan(oid, suffix, factor=poll_factor, offset=poll_offset), "invert_processor_idle": bool(measurement_type == "cpu_usage_percent" and str(definition.get("source_module") or "").casefold() == "processors" and (_number(definition.get("precision")) or 0) < 0), "skip_values": skip_conditions, "skip_conditions_supported": skip_supported, "transform_supported": native_transform_supported, "user_func": user_func, "raw_definition": raw_definition, "index_suffix": suffix},
            )
            if sensor:
                if librenms_index:
                    labels = sensor.get("index_labels") if isinstance(sensor.get("index_labels"), dict) else {}
                    labels["librenms_index"] = librenms_index
                    sensor["index_labels"] = labels
                _apply_ent_physical_metadata(sensor, definition, suffix)
                sensors.append(sensor)
                scope["rows"] += 1

    category_results: list[dict[str, Any]] = []
    for component_class, summary in sorted(by_class.items()):
        if summary["rows"]:
            status = "success" if summary["complete"] and summary["supported"] else "partial"
            reason_code = "librenms_hardware_rows"
            reason = f"LibreNMS {component_class} definitions returned {summary['rows']} component measurements"
        elif summary["supported"] and summary["complete"]:
            status, reason_code, reason = "not_found", "no_instances", "Definitions were supported, but no table instances were returned"
        elif not summary["supported"]:
            status, reason_code, reason = "unsupported", "unsupported_definition", "One or more rule definitions need an adapter or resolvable OID"
        else:
            status, reason_code, reason = "failed", "snmp_walk_failed", "SNMP returned an incomplete walk for this hardware category"
        category_results.append(_category_result(
            "librenms", component_class, status=status,
            complete=bool(summary["complete"] and summary["supported"]),
            reason_code=reason_code, reason=reason,
        ))
    if h3c_comware:
        cpu_memory_result = await _probe_h3c_comware_cpu_memory(
            ip, community, port, rule=rule, version=version, walk_func=walk_func,
        )
        _append_unique_probe_sensors(sensors, cpu_memory_result.get("sensors"))
        category_results.extend(cpu_memory_result.get("category_results") or [])

        if _wireless_controller_scope(identity):
            wireless_result = await _probe_h3c_comware_wireless(
                ip, community, port, rule=rule, version=version, walk_func=walk_func,
            )
            _append_unique_probe_sensors(sensors, wireless_result.get("sensors"))
            category_results.extend(wireless_result.get("category_results") or [])

        transceiver_result = await _probe_h3c_comware_transceivers(
            ip, community, port, rule=rule, identity=identity,
            version=version, walk_func=walk_func,
        )
        _append_unique_probe_sensors(sensors, transceiver_result.get("sensors"))
        category_results.extend(transceiver_result.get("category_results") or [])
    if os_adapter is not None:
        adapter_result = await os_adapter(
            ip,
            community,
            port,
            rule=rule,
            identity=identity,
            version=version,
            walk_func=walk_func,
            existing_sensors=sensors,
        )
        _append_unique_probe_sensors(sensors, adapter_result.get("sensors"))
        category_results.extend(adapter_result.get("category_results") or [])
    return {"sensors": sensors, "category_results": category_results}


async def poll_hardware_inventory(
    ip: str,
    community: str,
    port: int,
    version: str,
    sensors: list[Mapping[str, Any]],
    *,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None = None,
) -> dict[str, int]:
    """Poll every active sensor with OID walks grouped by table, then persist samples."""
    plans: dict[str, dict[str, Any]] = {}
    for sensor in sensors:
        if str(sensor.get("lifecycle_status") or "active") == "retired" or sensor.get("enabled") is False:
            continue
        metadata = sensor.get("metadata") if isinstance(sensor.get("metadata"), Mapping) else {}
        plan = metadata.get("poll_plan") if isinstance(metadata.get("poll_plan"), Mapping) else {}
        kind = str(plan.get("kind") or "direct")
        if kind in {"direct", "get"}:
            oid = _clean_oid(plan.get("oid") or sensor.get("oid"))
            if oid:
                plans[str(sensor.get("sensor_key") or "")] = {
                    "kind": kind,
                    "oid": oid,
                    "index": "" if kind == "get" else str(plan.get("index") or ".".join(map(str, sensor.get("index") or []))),
                    "factor": _number(plan.get("factor")) or 1.0,
                    "offset": _number(plan.get("offset")) or 0.0,
                    "skip_values": plan.get("skip_values", metadata.get("skip_values")),
                    "skip_conditions_supported": plan.get("skip_conditions_supported", metadata.get("skip_conditions_supported", True)),
                    "transform_supported": plan.get("transform_supported", metadata.get("native_transform_supported", True)),
                    "user_func": plan.get("user_func"),
                    "extract_percent": bool(plan.get("extract_percent", False)),
                    "integer_truncate": bool(plan.get("integer_truncate", False)),
                    "invert_processor_idle": bool(plan.get("invert_processor_idle", False)),
                    "raw_definition": plan.get("raw_definition", metadata.get("raw_definition", {})),
                    "index_suffix": plan.get("index_suffix") or plan.get("index") or "",
                }
        elif kind == "memory_pool":
            relations = plan.get("relations") if isinstance(plan.get("relations"), Mapping) else {}
            normalized_relations: dict[str, dict[str, Any]] = {}
            for name, dependency in relations.items():
                if not isinstance(dependency, Mapping):
                    continue
                relation_kind = str(dependency.get("kind") or "").casefold()
                if relation_kind == "constant":
                    number = _number(dependency.get("value"))
                    if number is not None:
                        normalized_relations[str(name)] = {"kind": "constant", "value": number}
                elif relation_kind == "oid":
                    dep_oid = _clean_oid(dependency.get("oid"))
                    if dep_oid:
                        index = str(dependency.get("index") or plan.get("index") or ".".join(map(str, sensor.get("index") or [])))
                        normalized_relations[str(name)] = {"kind": "oid", "oid": dep_oid, "index": index}
            unit_oid = _clean_oid(plan.get("unit_oid"))
            plan_item = {
                "kind": kind,
                "index": str(plan.get("index") or ".".join(map(str, sensor.get("index") or []))),
                "relations": normalized_relations,
                "target": str(plan.get("target") or sensor.get("measurement_type") or ""),
                "factor": _number(plan.get("factor")) if _number(plan.get("factor")) is not None else 1.0,
                "offset": _number(plan.get("offset")) if _number(plan.get("offset")) is not None else 0.0,
                "precision": _number(plan.get("precision")) if _number(plan.get("precision")) is not None else 1.0,
                "precision_supported": bool(plan.get("precision_supported", True)),
                "unit_factor": _number(plan.get("unit_factor")),
                "unit_oid": unit_oid,
                "unit_supported": bool(plan.get("unit_supported", True)),
                "skip_values": plan.get("skip_values", metadata.get("skip_values")),
                "skip_conditions_supported": plan.get("skip_conditions_supported", metadata.get("skip_conditions_supported", True)),
                "transform_supported": plan.get("transform_supported", metadata.get("native_transform_supported", True)),
            }
            plans[str(sensor.get("sensor_key") or "")] = plan_item
        elif kind in {"memory_ratio", "memory_component", "memory_sum"}:
            plan_item = {
                "kind": kind,
                "skip_values": plan.get("skip_values", metadata.get("skip_values")),
                "skip_conditions_supported": plan.get("skip_conditions_supported", metadata.get("skip_conditions_supported", True)),
                "transform_supported": plan.get("transform_supported", metadata.get("native_transform_supported", True)),
            }
            for name in ("used", "total", "free"):
                dependency = plan.get(name)
                if isinstance(dependency, Mapping):
                    dep_oid = _clean_oid(dependency.get("oid"))
                    if dep_oid:
                        plan_item[name] = {"oid": dep_oid, "index": str(dependency.get("index") or ".".join(map(str, sensor.get("index") or []))), "factor": _number(dependency.get("factor")) or 1.0, "offset": _number(dependency.get("offset")) or 0.0}
            plans[str(sensor.get("sensor_key") or "")] = plan_item
        elif kind == "entity_sensor":
            plan_item = {"kind": kind, "index": str(plan.get("index") or ".".join(map(str, sensor.get("index") or []))), "expected_type": _number(plan.get("expected_type"))}
            if plan.get("value_transform"):
                plan_item["value_transform"] = str(plan.get("value_transform"))
            for name in ("value_oid", "type_oid", "scale_oid", "precision_oid", "status_oid"):
                oid = _clean_oid(plan.get(name))
                if oid:
                    plan_item[name] = oid
            plans[str(sensor.get("sensor_key") or "")] = plan_item

    oids: set[str] = set()
    get_oids: set[str] = set()
    for plan in plans.values():
        if plan["kind"] == "direct":
            oids.add(plan["oid"])
        elif plan["kind"] == "get":
            get_oids.add(plan["oid"])
        elif plan["kind"] in {"memory_ratio", "memory_component", "memory_sum"}:
            oids.update(plan[name]["oid"] for name in ("used", "total", "free") if name in plan)
        elif plan["kind"] == "memory_pool":
            oids.update(
                relation["oid"]
                for relation in plan.get("relations", {}).values()
                if relation.get("kind") == "oid" and relation.get("oid")
            )
            if plan.get("unit_oid"):
                oids.add(plan["unit_oid"])
        elif plan["kind"] == "entity_sensor":
            oids.update(plan[name] for name in ("value_oid", "type_oid", "scale_oid", "precision_oid", "status_oid") if name in plan)
        raw_conditions = plan.get("skip_values")
        conditions = raw_conditions if isinstance(raw_conditions, list) else [raw_conditions]
        for condition in conditions:
            if isinstance(condition, Mapping) and condition.get("_oid"):
                condition_oid = _clean_oid(condition.get("_oid"))
                if condition_oid and not condition.get("_value_oid"):
                    oids.add(condition_oid)
    reads = await _walk_many(ip, community, oids, port, version, walk_func=walk_func)
    maps = {oid: _row_map(read) for oid, read in reads.items()}
    complete_oids = {
        oid for oid, read in reads.items()
        if read.complete and not read.reason
    }
    scalar_values: dict[str, str | None] = {}
    if get_oids:
        from services.snmp_service import _snmp_get_versioned

        semaphore = asyncio.Semaphore(8)

        async def read_scalar(oid: str) -> tuple[str, str | None]:
            async with semaphore:
                try:
                    return oid, await _snmp_get_versioned(ip, community, oid, port, version)
                except Exception as exc:
                    logger.debug("Hardware scalar GET %s failed: %s", oid, type(exc).__name__)
                    return oid, None

        scalar_values = dict(await asyncio.gather(*(read_scalar(oid) for oid in sorted(get_oids))))
    from database import get_db_connection
    from services.snmp_hardware_inventory_service import record_sensor_sample

    now = datetime.now(timezone.utc)
    good = missing = invalid = unsupported = 0
    conn = get_db_connection()
    try:
        for sensor in sensors:
            sensor_key = str(sensor.get("sensor_key") or "")
            plan = plans.get(sensor_key)
            if not plan:
                continue
            quality = "good"
            value: float | None = None
            raw_value: str | None = None
            try:
                if plan["kind"] in {"direct", "get"}:
                    raw_value = (
                        scalar_values.get(plan["oid"])
                        if plan["kind"] == "get"
                        else maps.get(plan["oid"], {}).get(plan["index"])
                    )
                    quality = _skip_sample_quality(
                        raw_value, plan.get("skip_values"),
                        conditions_supported=bool(plan.get("skip_conditions_supported", True)),
                        suffix=plan["index"] or ".".join(map(str, sensor.get("index") or [])),
                        rows_by_oid=maps,
                        complete_oids=complete_oids,
                    )
                    if quality == "good" and not plan.get("transform_supported", True):
                        quality = "unsupported_mapping"
                    if quality == "good":
                        measurement_type = str(sensor.get("measurement_type") or "").casefold()
                        if measurement_type in {"wireless_station_attribute", "wireless_radio_attribute"}:
                            normalized_text = _h3c_dot11_text(raw_value) if raw_value is not None else ""
                            if normalized_text:
                                raw_value = normalized_text
                            else:
                                quality = "invalid" if raw_value is not None else "missing"
                        elif measurement_type == "component_state":
                            state_input: Any = raw_value
                            if plan.get("user_func"):
                                number = _number(raw_value)
                                scaled = normalize_scaled_value(number, plan["factor"], plan["offset"]) if number is not None else None
                                state_input = apply_librenms_user_func(
                                    plan["user_func"], scaled, raw_value=raw_value,
                                    index_suffix=plan.get("index_suffix"),
                                    definition=plan.get("raw_definition") if isinstance(plan.get("raw_definition"), Mapping) else {},
                                    now=now,
                                )
                                if state_input is None:
                                    quality = "invalid"
                            if quality == "good":
                                value, _states, quality = _mapped_state(state_input, sensor.get("states"))
                        else:
                            if plan.get("extract_percent") and raw_value is not None:
                                match = re.search(r"([0-9]+.[0-9]+)%", str(raw_value))
                                number = _number(match.group(1)) if match else None
                                if number is None:
                                    quality = "invalid"
                            else:
                                number = _number(raw_value)
                            if number is not None and plan.get("integer_truncate"):
                                number = float(int(number))
                            if number is not None:
                                value = normalize_scaled_value(number, plan["factor"], plan["offset"])
                                if value is not None and plan.get("invert_processor_idle"):
                                    value = 100.0 - value
                                if plan.get("user_func"):
                                    value = apply_librenms_user_func(
                                        plan["user_func"], value, raw_value=raw_value,
                                        index_suffix=plan.get("index_suffix"),
                                        definition=plan.get("raw_definition") if isinstance(plan.get("raw_definition"), Mapping) else {},
                                        now=now,
                                    )
                                    if value is None:
                                        quality = "invalid"
                            else:
                                if quality == "good":
                                    quality = "missing"
                elif plan["kind"] == "memory_pool":
                    relation_values: dict[str, Any] = {}
                    for name, dependency in plan.get("relations", {}).items():
                        if dependency.get("kind") == "constant":
                            relation_values[name] = dependency.get("value")
                        elif dependency.get("kind") == "oid":
                            relation_values[name] = maps.get(dependency["oid"], {}).get(dependency["index"])
                    suffix = str(plan.get("index") or ".".join(map(str, sensor.get("index") or [])))
                    unit_factor = plan.get("unit_factor")
                    if plan.get("unit_oid"):
                        unit_factor = _number(maps.get(plan["unit_oid"], {}).get(suffix))
                    target = str(plan.get("target") or "")
                    target_key = {
                        "memory_used_bytes": "used",
                        "memory_total_bytes": "total",
                        "memory_usage_percent": "percent_used",
                    }.get(target, target)
                    raw_value = relation_values.get(target_key)
                    if raw_value is None:
                        raw_value = next((relation_values.get(name) for name in ("used", "percent_used", "total", "free") if relation_values.get(name) is not None), None)
                    quality = _skip_sample_quality(
                        raw_value, plan.get("skip_values"),
                        conditions_supported=bool(plan.get("skip_conditions_supported", True)),
                        suffix=suffix,
                        rows_by_oid=maps,
                        complete_oids=complete_oids,
                    )
                    if quality == "good" and not plan.get("transform_supported", True):
                        quality = "unsupported_mapping"
                    if quality == "good" and target_key in {"used", "total"} and not plan.get("precision_supported", True):
                        quality = "unsupported_mapping"
                    if quality == "good" and target_key in {"used", "total"} and (unit_factor is None or unit_factor <= 0):
                        quality = "unsupported_mapping" if not plan.get("unit_supported", True) else "missing"
                    metrics = _mempool_metric_values(
                        relation_values,
                        factor=plan["factor"],
                        offset=plan["offset"],
                        precision=plan["precision"],
                        unit_factor=unit_factor if unit_factor is not None and unit_factor > 0 else None,
                    )
                    if quality == "good":
                        value = metrics.get(target_key)
                        if value is None:
                            has_relation_sample = any(sample is not None for sample in relation_values.values())
                            quality = "invalid" if has_relation_sample else "missing"
                elif plan["kind"] in {"memory_ratio", "memory_component"}:
                    used = plan.get("used")
                    total = plan.get("total")
                    free = plan.get("free")
                    used_raw = maps.get(used["oid"], {}).get(used["index"]) if used else None
                    total_raw = maps.get(total["oid"], {}).get(total["index"]) if total else None
                    free_raw = maps.get(free["oid"], {}).get(free["index"]) if free else None
                    used_num = _number(used_raw)
                    total_num = _number(total_raw)
                    free_num = _number(free_raw)
                    raw_value = used_raw
                    quality = _skip_sample_quality(
                        used_raw, plan.get("skip_values"),
                        conditions_supported=bool(plan.get("skip_conditions_supported", True)),
                        suffix=str(used.get("index") if used else ".".join(map(str, sensor.get("index") or []))),
                        rows_by_oid=maps,
                        complete_oids=complete_oids,
                    )
                    if quality == "good" and not plan.get("transform_supported", True):
                        quality = "unsupported_mapping"
                    if quality != "good":
                        pass
                    elif used_num is None:
                        quality = "missing"
                    elif plan["kind"] == "memory_ratio":
                        if total_num is None and free_num is not None:
                            total_num = used_num + free_num
                            total_scale = used
                        else:
                            total_scale = total
                        used_scaled = normalize_scaled_value(used_num, used["factor"], used["offset"])
                        total_scaled = (
                            normalize_scaled_value(total_num, total_scale["factor"], total_scale["offset"])
                            if total_num is not None and total_scale
                            else None
                        )
                        if total_num is not None and total_num > 0 and used_scaled is not None and total_scaled is not None:
                            value = normalize_percentage(100.0 * used_scaled / total_scaled) if total_scaled > 0 else None
                            if value is None:
                                quality = "invalid"
                        else:
                            quality = "invalid" if used_scaled is None or (total_scale and total_scaled is None) else "missing"
                    else:
                        value = normalize_scaled_value(used_num, used["factor"], used["offset"])
                elif plan["kind"] == "memory_sum":
                    used = plan.get("used")
                    free = plan.get("free")
                    used_raw = maps.get(used["oid"], {}).get(used["index"]) if used else None
                    free_raw = maps.get(free["oid"], {}).get(free["index"]) if free else None
                    used_num = _number(used_raw)
                    free_num = _number(free_raw)
                    raw_value = used_raw
                    quality = _skip_sample_quality(
                        used_raw, plan.get("skip_values"),
                        conditions_supported=bool(plan.get("skip_conditions_supported", True)),
                        suffix=str(used.get("index") if used else ".".join(map(str, sensor.get("index") or []))),
                        rows_by_oid=maps,
                        complete_oids=complete_oids,
                    )
                    if quality == "good" and not plan.get("transform_supported", True):
                        quality = "unsupported_mapping"
                    if quality != "good":
                        pass
                    elif used_num is None or free_num is None or not used or not free:
                        quality = "missing"
                    else:
                        used_scaled = normalize_scaled_value(used_num, used["factor"], used["offset"])
                        free_scaled = normalize_scaled_value(free_num, free["factor"], free["offset"])
                        if used_scaled is None or free_scaled is None:
                            quality = "invalid"
                        else:
                            value = used_scaled + free_scaled
                elif plan["kind"] == "entity_sensor":
                    suffix = plan["index"]
                    raw_value = maps.get(plan["value_oid"], {}).get(suffix)
                    type_value = _number(maps.get(plan["type_oid"], {}).get(suffix))
                    scale_value = _number(maps.get(plan["scale_oid"], {}).get(suffix))
                    precision_value = _number(maps.get(plan["precision_oid"], {}).get(suffix))
                    status_value = _number(maps.get(plan["status_oid"], {}).get(suffix))
                    number = _number(raw_value)
                    if plan.get("expected_type") is not None and type_value is not None and int(type_value) != int(plan["expected_type"]):
                        quality = "unsupported_mapping"
                    elif (number is None or type_value is None or scale_value is None or precision_value is None
                            or int(scale_value) not in _SENSOR_SCALE_EXPONENT):
                        quality = "invalid" if raw_value is not None else "missing"
                    elif status_value is not None and int(status_value) != 1:
                        quality = "missing"
                    else:
                        precision = int(precision_value)
                        if not -8 <= precision <= 9:
                            quality = "unsupported_mapping"
                        else:
                            value = normalize_scaled_value(
                                number,
                                10.0 ** (_SENSOR_SCALE_EXPONENT[int(scale_value)] - precision),
                                0,
                            )
                            if plan.get("value_transform") == "iosxr_watts_to_dbm":
                                if value is None or value <= 0:
                                    value = None
                                    quality = "invalid"
                                else:
                                    value = 10.0 * math.log10(value * 1000.0)
                if quality == "good":
                    measurement_type = str(sensor.get("measurement_type") or "").casefold()
                    if measurement_type in {"cpu_usage_percent", "memory_usage_percent"}:
                        value = normalize_percentage(value)
                    elif measurement_type == "temperature_celsius":
                        value = normalize_temperature_celsius(value)
                    is_text_attribute = measurement_type in {
                        "wireless_station_attribute", "wireless_radio_attribute",
                    }
                    if value is None and not is_text_attribute:
                        quality = "invalid"
                measurement_type = str(sensor.get("measurement_type") or "").casefold()
                if quality == "good" and measurement_type not in {
                    "wireless_station_attribute", "wireless_radio_attribute",
                } and (value is None or not math.isfinite(value)):
                    quality = "invalid"
                    value = None
            except Exception:
                quality, value = "invalid", None
            if quality == "good":
                good += 1
            elif quality == "missing":
                missing += 1
            elif quality == "unsupported_mapping":
                unsupported += 1
            else:
                invalid += 1
            sample = (
                conn, str(sensor.get("device_id") or ""), sensor_key,
                value, raw_value, quality, now,
            )
            if str(sensor.get("measurement_type") or "").casefold() == "component_state":
                presence_status = _state_presence(raw_value, sensor.get("states")) if quality == "good" else None
                record_sensor_sample(*sample, presence_status=presence_status)
            else:
                record_sensor_sample(*sample)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"good": good, "missing": missing, "invalid": invalid, "unsupported_mapping": unsupported}


__all__ = ["probe_standard_hardware", "probe_librenms_hardware", "poll_hardware_inventory"]
