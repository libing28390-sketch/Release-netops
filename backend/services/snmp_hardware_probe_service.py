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
        "coverage_complete": bool(complete and status == "success"),
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
    return scale * multiplier / divisor, offset


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
    definitions: list[dict[str, Any]] = []
    for section in ("processors", "mempools", "sensors"):
        rows = hardware.get(section)
        if isinstance(rows, list):
            definitions.extend(dict(item) for item in rows if isinstance(item, Mapping))
    if not definitions:
        if h3c_comware:
            return await _probe_h3c_comware_transceivers(
                ip, community, port, rule=rule, version=version, walk_func=walk_func,
            )
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
            skip_conditions, skip_oids, skip_supported = _compile_skip_conditions(
                item.get("skip_values"), db_conn=db_conn, vendor=vendor,
                identity=identity,
                cache=mib_cache,
            )
            for condition in skip_conditions:
                if isinstance(condition, dict) and condition.get("_oid") == oid:
                    condition["_value_oid"] = True
            item["_skip_conditions"] = skip_conditions
            item["_skip_conditions_supported"] = skip_supported
            needed_oids.update(skip_oids)
            memory = item.get("memory") if isinstance(item.get("memory"), Mapping) else {}
            for key in ("used_oid", "free_oid", "total_oid", "percent_used_oid"):
                memory_oid = _numeric_oid(memory.get(key))
                if not memory_oid and db_conn is not None:
                    memory_oid = _resolve_mib_symbol(
                        db_conn,
                        memory.get(key),
                        vendor=vendor,
                        cache=mib_cache,
                    )
                item[f"_{key}"] = memory_oid
                if memory_oid:
                    needed_oids.add(memory_oid)
            item["_allocation_unit"] = memory.get("allocation_unit")
            item["_allocation_unit_oid"] = ""
            if isinstance(memory.get("allocation_unit"), str):
                unit_oid = _numeric_oid(memory.get("allocation_unit"))
                if not unit_oid and db_conn is not None:
                    unit_oid = _resolve_mib_symbol(
                        db_conn,
                        memory.get("allocation_unit"),
                        vendor=vendor,
                        cache=mib_cache,
                    )
                item["_allocation_unit_oid"] = unit_oid
                if unit_oid:
                    needed_oids.add(unit_oid)
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
        if not oid or not measurement_info:
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
        if str(definition.get("source_module") or "") == "mempools":
            deps: dict[str, dict[str, Any]] = {}
            for key in ("used_oid", "total_oid", "free_oid"):
                dep_oid = str(definition.get(f"_{key}") or "")
                if dep_oid:
                    deps[key.removesuffix("_oid")] = {"oid": dep_oid, "factor": 1.0, "offset": 0.0}
            percent_oid = str(definition.get("_percent_used_oid") or "")
            unit_factor = _number(definition.get("_allocation_unit"))
            if unit_factor is None:
                unit_token = str(definition.get("_allocation_unit") or "").casefold()
                unit_factor = {"byte": 1.0, "bytes": 1.0, "kilobyte": 1024.0, "kilobytes": 1024.0, "megabyte": 1048576.0, "megabytes": 1048576.0}.get(unit_token)
            unit_oid = str(definition.get("_allocation_unit_oid") or "")
            if unit_oid:
                deps["allocation_unit"] = {"oid": unit_oid, "factor": 1.0, "offset": 0.0}
            used_oid = str(definition.get("_used_oid") or "")
            total_oid = str(definition.get("_total_oid") or "")
            free_oid = str(definition.get("_free_oid") or "")
            all_indices = set(rows_by_oid.get(used_oid, {})) | set(rows_by_oid.get(total_oid, {})) | set(rows_by_oid.get(free_oid, {})) | set(rows_by_oid.get(percent_oid, {}))
            if not all_indices and oid:
                all_indices = set(rows_by_oid.get(oid, {}))
            if not all_indices:
                read_complete = all(reads.get(item.get("oid"), WalkResult([], False)).complete for item in deps.values()) if deps else reads.get(oid, WalkResult([], False)).complete
                scope["complete"] = scope["complete"] and read_complete
                continue
            factor, offset = transform
            for suffix in sorted(all_indices):
                used_raw = rows_by_oid.get(used_oid, {}).get(suffix)
                total_raw = rows_by_oid.get(total_oid, {}).get(suffix)
                free_raw = rows_by_oid.get(free_oid, {}).get(suffix)
                percent_raw = rows_by_oid.get(percent_oid, {}).get(suffix)
                condition_values, condition_complete = _condition_values_at_index(
                    skip_conditions, suffix=suffix, raw_value=used_raw,
                    rows_by_oid=rows_by_oid, complete_oids=complete_oids,
                )
                skip_result = _skip_value(
                    used_raw, skip_conditions, condition_values=condition_values,
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
                if not native_transform_supported and memory_quality == "good":
                    memory_quality = "unsupported_mapping"
                if memory_quality == "unsupported_mapping":
                    scope["supported"] = False
                if total_raw is None and used_raw is not None and free_raw is not None:
                    total_number = (_number(used_raw) or 0) + (_number(free_raw) or 0)
                    total_raw = str(total_number)
                used_value = _number(used_raw)
                total_value = _number(total_raw)
                if unit_oid and unit_factor is None:
                    unit_factor = _number(rows_by_oid.get(unit_oid, {}).get(suffix))
                effective_unit = unit_factor or 1.0
                memory_metrics: list[tuple[str, str, Any, float | None, str, dict[str, Any]]] = []
                if used_raw is not None and unit_factor is not None:
                    memory_metrics.append(("memory_used_bytes", used_oid, used_raw, used_value * factor * unit_factor + offset if used_value is not None else None, "bytes", {"kind": "direct", "oid": used_oid, "index": suffix, "factor": factor * unit_factor, "offset": offset}))
                if total_raw is not None and unit_factor is not None:
                    if total_oid:
                        total_plan = {"kind": "direct", "oid": total_oid, "index": suffix, "factor": factor * unit_factor, "offset": offset}
                    else:
                        total_plan = {"kind": "memory_sum", "used": {"oid": used_oid, "index": suffix, "factor": factor * unit_factor, "offset": offset}, "free": {"oid": free_oid, "index": suffix, "factor": factor * unit_factor, "offset": offset}}
                    memory_metrics.append(("memory_total_bytes", total_oid or used_oid, total_raw, total_value * factor * unit_factor + offset if total_oid and total_value is not None else ((_number(used_raw) or 0) + (_number(free_raw) or 0)) * factor * unit_factor + offset if used_raw is not None and free_raw is not None else None, "bytes", total_plan))
                if percent_raw is not None:
                    percent_number = _number(percent_raw)
                    memory_metrics.append(("memory_usage_percent", percent_oid, percent_raw, percent_number * factor + offset if percent_number is not None else None, "percent", {"kind": "direct", "oid": percent_oid, "index": suffix, "factor": factor, "offset": offset}))
                elif used_value is not None and total_value is not None and total_value > 0:
                    if total_oid:
                        total_dep = {"oid": total_oid, "index": suffix, "factor": factor, "offset": offset}
                        ratio_plan = {"kind": "memory_ratio", "used": {"oid": used_oid, "index": suffix, "factor": factor, "offset": offset}, "total": total_dep}
                    elif free_oid:
                        ratio_plan = {"kind": "memory_ratio", "used": {"oid": used_oid, "index": suffix, "factor": factor, "offset": offset}, "free": {"oid": free_oid, "index": suffix, "factor": factor, "offset": offset}}
                    else:
                        ratio_plan = {}
                    memory_metrics.append(("memory_usage_percent", used_oid, used_raw, 100.0 * used_value / total_value, "percent", ratio_plan))
                elif used_raw is not None and total_raw is None:
                    scope["supported"] = False
                index = _index_parts(suffix)
                if index is None:
                    continue
                entity_name = _name_at(entity_names, index, f"Memory pool {suffix}")
                for memory_measurement, sample_oid, raw_value, sample_value, sample_unit, poll_plan in memory_metrics:
                    if memory_quality != "good":
                        sample_value = None
                    enriched_plan = {
                        **poll_plan,
                        "skip_values": skip_conditions,
                        "skip_conditions_supported": skip_supported,
                    }
                    sensor = _sensor(
                        source_type="librenms", source_id=rule_id,
                        component_class="memory_pool", measurement_type=memory_measurement,
                        oid=sample_oid, suffix=suffix, raw_value=raw_value,
                        value=sample_value, unit=sample_unit,
                        sensor_name=entity_name, entity_name=entity_name,
                        group_name=str(definition.get("group") or definition.get("memory", {}).get("pool_class") or "memory"),
                        quality=memory_quality,
                        states={}, thresholds=definition.get("limits"),
                        metadata={"rule_id": rule_id, "source_commit": source_commit, "source_path": source_path, "os_key": rule.get("os_key"), "definition_index": definition_index, "raw_definition": raw_definition, "allocation_unit": definition.get("_allocation_unit"), "index_suffix": suffix, "skip_values": skip_conditions, "skip_conditions_supported": skip_supported},
                        poll_plan={**enriched_plan, "transform_supported": native_transform_supported},
                    )
                    if sensor:
                        _apply_ent_physical_metadata(sensor, definition, suffix)
                        sensors.append(sensor)
                        scope["rows"] += 1
            required_oids = {oid, used_oid, total_oid, free_oid, percent_oid, unit_oid} - {""}
            scope["complete"] = scope["complete"] and all(reads.get(item, WalkResult([], False)).complete for item in required_oids)
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
            display = str(definition.get("descr") or "")
            sensor_name = entity_name if entity_name and not entity_name.startswith("Entity sensor ") else display or fallback
            source_id = f"{rule_id}:{definition.get('source_module')}:{definition.get('source_class')}:{oid}"
            sensor = _sensor(
                source_type="librenms", source_id=source_id,
                component_class=component_class, measurement_type=measurement_type,
                oid=oid, suffix=suffix, raw_value=raw_value, value=value,
                unit=unit, sensor_name=sensor_name,
                entity_name=entity_name, group_name=str(definition.get("group") or component_class),
                quality=quality, states=state_definitions or states_map,
                thresholds=definition.get("limits"),
                presence_status=presence_status,
                metadata={"rule_id": rule_id, "source_commit": source_commit, "source_path": source_path, "os_key": rule.get("os_key"), "definition_index": definition_index, "index_suffix": suffix, "skip_values": skip_conditions, "skip_conditions_supported": skip_supported, "precision": definition.get("precision"), "window": _explicit_cpu_window(definition) if measurement_type == "cpu_usage_percent" else "", "raw_definition": raw_definition},
                poll_plan={**_direct_plan(oid, suffix, factor=poll_factor, offset=poll_offset), "skip_values": skip_conditions, "skip_conditions_supported": skip_supported, "transform_supported": native_transform_supported, "user_func": user_func, "raw_definition": raw_definition, "index_suffix": suffix},
            )
            if sensor:
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
            complete=bool(summary["rows"] and summary["complete"] and summary["supported"]),
            reason_code=reason_code, reason=reason,
        ))
    if h3c_comware:
        transceiver_result = await _probe_h3c_comware_transceivers(
            ip, community, port, rule=rule, version=version, walk_func=walk_func,
        )
        existing = {
            (
                str(sensor.get("oid") or ""),
                tuple(sensor.get("index") or []),
                str(sensor.get("measurement_type") or ""),
            )
            for sensor in sensors
            if isinstance(sensor, Mapping)
        }
        for sensor in transceiver_result.get("sensors") or []:
            key = (
                str(sensor.get("oid") or ""),
                tuple(sensor.get("index") or []),
                str(sensor.get("measurement_type") or ""),
            )
            if key not in existing:
                sensors.append(sensor)
                existing.add(key)
        category_results.extend(transceiver_result.get("category_results") or [])
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
                    "raw_definition": plan.get("raw_definition", metadata.get("raw_definition", {})),
                    "index_suffix": plan.get("index_suffix") or plan.get("index") or "",
                }
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
                        if str(sensor.get("measurement_type") or "").casefold() == "component_state":
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
                            number = _number(raw_value)
                            if number is not None:
                                value = normalize_scaled_value(number, plan["factor"], plan["offset"])
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
                                quality = "missing"
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
                    if value is None:
                        quality = "invalid"
                if quality == "good" and (value is None or not math.isfinite(value)):
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
