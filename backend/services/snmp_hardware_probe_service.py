"""SNMP probes for hardware definitions in the pinned LibreNMS YAML bundle.

The probes retain complete table indexes and only claim discovery coverage when
the requested SNMP walks completed.  Measurement values are normalized before
they enter the hardware inventory; unsupported rule semantics stay explicit.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
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
from services.librenms_source_policy import (
    LIBRENMS_BUNDLE_ROOT,
    PINNED_LIBRENMS_COMMIT,
    verified_librenms_mib_source_entries,
    verify_bundled_rule,
)

logger = logging.getLogger(__name__)

_ENTITY_NAME_OID = "1.3.6.1.2.1.47.1.1.1.1.7"
_POLL_EXCLUDED_MEASUREMENT_TYPES = frozenset({
    "voltage_volts",
    "current_amperes",
    "sensor_value",
})

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
    octet_values: dict[str, bytes] = field(default_factory=dict)


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
    module_name = ""
    symbol = raw
    if "::" in raw:
        module_name, symbol = raw.rsplit("::", 1)
        module_name = module_name.strip()
    symbol = symbol.strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", symbol):
        if cache is not None:
            cache[cache_key] = ""
        return ""
    if conn is None:
        if cache is not None:
            cache[cache_key] = ""
        return ""
    try:
        rows = conn.execute(
            """
            SELECT n.oid, m.relative_path, m.sha256
              FROM snmp_mib_nodes n
              JOIN snmp_mibs m ON m.id = n.mib_id
             WHERE m.is_active = 1 AND m.source_type = 'librenms'
               AND m.source_commit = ? AND LOWER(n.node_name) = LOWER(?)
               AND TRIM(COALESCE(n.oid, '')) <> ''
            """,
            (PINNED_LIBRENMS_COMMIT, symbol),
        ).fetchall()
    except Exception:
        if cache is not None:
            cache[cache_key] = ""
        return ""

    resolved_oids: set[str] = set()
    for row in rows or []:
        try:
            oid_value, relative_path, file_hash = row[0], row[1], row[2]
        except (TypeError, IndexError, KeyError):
            continue
        verified_entries = verified_librenms_mib_source_entries(
            module_name=module_name,
            relative_path=str(relative_path or ""),
            sha256=str(file_hash or ""),
        )
        if len(verified_entries) != 1:
            continue
        resolved = _numeric_oid(oid_value)
        if resolved:
            resolved_oids.add(resolved)

    # If an unqualified symbol is shared by multiple pinned MIBs, accept it
    # only when every verified source resolves to the same numeric OID.
    if len(resolved_oids) != 1:
        if cache is not None:
            cache[cache_key] = ""
        return ""
    resolved = next(iter(resolved_oids))
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
    # LibreNMS' explicit `value` is the sampled object. `num_oid` is a
    # fallback only when no value object was defined; `oid` is a table hint,
    # never a substitute for an unresolved explicit value source.
    candidates = (
        ("value_oid", definition.get("value_oid")),
        ("num_oid", definition.get("num_oid")),
        ("numeric_oid_prefix", definition.get("numeric_oid_prefix")),
        ("table_oid", definition.get("table_oid")),
    )
    for _field, candidate in candidates:
        if candidate in (None, ""):
            continue
        numeric = _numeric_oid(candidate)
        if numeric:
            return numeric
        resolved = _resolve_mib_symbol(conn, candidate, vendor=vendor, cache=cache)
        if resolved:
            return resolved
        # An explicit but unknown source cannot fall back to a different OID.
        return ""
    return ""


async def _walk(
    ip: str,
    community: str | Mapping[str, Any],
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
                version=version, raise_on_error=True, preserve_octets=True,
            )
        octet_values = dict(getattr(rows, "octet_values", {}) or {})
        normalized: list[tuple[str, str]] = []
        for suffix, raw in rows or []:
            suffix_text = str(suffix or "").strip().strip(".")
            normalized.append((suffix_text, str(raw)))
        # The walker caps row counts.  Reaching its cap cannot establish full
        # table coverage, so absence retirement stays disabled for this run.
        return WalkResult(normalized, len(normalized) < 2000, octet_values=octet_values)
    except Exception as exc:
        partial = getattr(exc, "partial_results", []) or []
        return WalkResult(
            [(str(index).strip("."), str(raw)) for index, raw in partial],
            False,
            type(exc).__name__,
        )


async def _walk_many(
    ip: str,
    community: str | Mapping[str, Any],
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
    community: str | Mapping[str, Any],
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


def _wireless_channel_frequency(value: Any, *, aruba_instant_encoding: bool = False) -> float | None:
    raw = str(value or "").strip()
    if aruba_instant_encoding:
        digits = re.sub(r"\D", "", raw)
        if not digits:
            return None
        channel = int(digits) & 0xFF
    else:
        number = _number(raw)
        if number is None:
            match = re.search(r"\((-?\d+(?:\.\d+)?)\)\s*$", raw)
            number = _number(match.group(1)) if match else None
        if number is None or not number.is_integer() or number <= 0:
            return None
        channel = int(number) & 0xFF
    if channel == 14:
        return 2484.0
    if 1 <= channel <= 13:
        return float(2407 + 5 * channel)
    if 32 <= channel <= 196:
        return float(5000 + 5 * channel)
    return None


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




@functools.lru_cache(maxsize=128)
def _read_pinned_hardware_definition(
    os_key: str,
    mtime_ns: int,
    size: int,
) -> dict[str, Any] | None:
    """Parse one hardware profile directly from the pinned YAML bundle."""
    from services.librenms_rule_service import (
        _load_yaml_result,
        _parse_hardware_definitions,
    )

    source_path = f"resources/definitions/os_discovery/{os_key}.yaml"
    target = LIBRENMS_BUNDLE_ROOT / source_path
    try:
        discovery, diagnostics = _load_yaml_result(target)
        hardware = _parse_hardware_definitions(discovery, source_path=source_path)
    except Exception:
        return None
    if diagnostics:
        compatibility = hardware.get("compatibility")
        if isinstance(compatibility, dict):
            compatibility.setdefault("diagnostics", []).extend(diagnostics)
            source_errors = [
                item for item in diagnostics
                if item.get("code") != "yaml_recovered_upstream_format"
            ]
            if source_errors and compatibility.get("level") == "supported":
                compatibility["level"] = "partial"
    return hardware


def _pinned_hardware_definition_matches(rule: Mapping[str, Any]) -> bool:
    os_key = str(rule.get("os_key") or "").strip().casefold()
    hardware = rule.get("hardware_definitions")
    if not os_key or not isinstance(hardware, Mapping):
        return False
    target = LIBRENMS_BUNDLE_ROOT / "resources" / "definitions" / "os_discovery" / f"{os_key}.yaml"
    try:
        stat = target.stat()
    except OSError:
        return not target.exists() and not any(
            isinstance(hardware.get(section), list) and hardware.get(section)
            for section in ("processors", "mempools", "sensors")
        )
    pinned = _read_pinned_hardware_definition(os_key, stat.st_mtime_ns, stat.st_size)
    return isinstance(pinned, Mapping) and dict(hardware) == pinned


@functools.lru_cache(maxsize=1)
def _librenms_source_manifest() -> dict[str, Any]:
    path = LIBRENMS_BUNDLE_ROOT / "source-manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _librenms_os_rule_lineage(os_key: str) -> dict[str, Any] | None:
    manifest = _librenms_source_manifest()
    source_commit = str(manifest.get("upstream_commit") or "")
    if os_key == "ios":
        primary = "LibreNMS/OS/Ios.php"
        adapters = [primary, "LibreNMS/OS/Shared/Cisco.php"]
        mib_sources = [
            "mibs/cisco/CISCO-ENHANCED-MEMPOOL-MIB",
            "mibs/cisco/CISCO-ENTITY-QFP-MIB",
            "mibs/cisco/CISCO-MEMORY-POOL-MIB",
            "mibs/cisco/CISCO-PROCESS-MIB",
            "mibs/cisco/OLD-CISCO-CPU-MIB",
            "mibs/ENTITY-MIB",
        ]
    elif os_key == "comware":
        primary = "LibreNMS/OS/Comware.php"
        adapters = [
            primary,
            "includes/discovery/sensors/temperature/comware.inc.php",
            "includes/discovery/sensors/dbm/comware.inc.php",
            "includes/discovery/sensors/voltage/comware.inc.php",
            "includes/discovery/sensors/current/comware.inc.php",
        ]
        mib_sources = [
            "mibs/comware/HH3C-ENTITY-EXT-MIB",
            "mibs/comware/HH3C-TRANSCEIVER-INFO-MIB",
            "mibs/ENTITY-MIB",
            "mibs/IF-MIB",
        ]
    else:
        return None
    return {
        "source_commit": source_commit,
        "source_path": primary,
        "os_key": os_key,
        "adapter_source_files": adapters,
        "mib_source_files": mib_sources,
    }


def _resolve_pinned_librenms_mib_symbol(
    conn: Any,
    upstream_path: str,
    symbol: str,
    *,
    cache: dict[tuple[str, str], str] | None = None,
) -> str:
    """Resolve a symbol only from the exact verified MIB file in the pinned bundle."""
    key = (str(upstream_path), str(symbol).casefold())
    if cache is not None and key in cache:
        return cache[key]
    if conn is None:
        return ""
    try:
        entries = verified_librenms_mib_source_entries(upstream_path=upstream_path)
        if len(entries) != 1:
            return ""
        entry = entries[0]
        bundle_path = str(entry.get("bundle_path") or "").replace("\\", "/")
        relative_path = bundle_path[5:] if bundle_path.startswith("mibs/") else bundle_path
        expected_hash = str(entry.get("sha256") or "")
        source_commit = str(_librenms_source_manifest().get("upstream_commit") or "")
        if not relative_path or len(expected_hash) != 64 or not source_commit:
            return ""
        row = conn.execute(
            """
            SELECT n.oid
              FROM snmp_mib_nodes n
              JOIN snmp_mibs m ON m.id = n.mib_id
             WHERE m.source_type = 'librenms' AND m.is_active = 1
               AND m.source_commit = ? AND m.relative_path = ? AND m.sha256 = ?
               AND LOWER(n.node_name) = LOWER(?)
               AND TRIM(COALESCE(n.oid, '')) <> ''
             ORDER BY m.updated_at DESC
             LIMIT 1
            """,
            (source_commit, relative_path, expected_hash, symbol),
        ).fetchone()
        resolved = _numeric_oid(row[0]) if row else ""
    except Exception:
        resolved = ""
    if cache is not None:
        cache[key] = resolved
    return resolved


def _snmp_numeric(value: Any) -> float | None:
    number = _number(value)
    if number is not None:
        return number
    text = str(value or "").strip()
    if ":" in text:
        text = text.split(":", 1)[1].strip()
    number = _number(text)
    if number is not None:
        return number
    match = re.fullmatch(
        r"(?:INTEGER(?:32)?|Gauge32|Unsigned32|Counter(?:32|64)?|CounterBasedGauge64):\\s*([-+]?(?:\\d+(?:\\.\\d*)?|\\.\\d+))",
        text,
        flags=re.IGNORECASE,
    )
    return _number(match.group(1)) if match else None


def _snmp_true(value: Any) -> bool:
    token = str(value or "").strip().casefold()
    return token in {"1", "true", "true(1)", "yes"}


def _snmp_interface_admin_up(value: Any) -> bool:
    token = str(value or "").strip().casefold().replace(" ", "")
    return token in {"1", "up", "up(1)"}


def _microwatt_to_dbm(value: Any) -> float | None:
    """Convert the microwatt value produced by LibreNMS' Comware /10 step."""
    microwatts = _snmp_numeric(value)
    if microwatts is None or microwatts <= 0:
        return None
    return 10.0 * math.log10(microwatts / 1000.0)


def _lineage_sensor_metadata(lineage: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    return {**dict(lineage), "collection_engine": "librenms_os_rule", **extra}


async def probe_librenms_os_hardware(
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str = "2c",
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None = None,
) -> dict[str, Any]:
    """Collect pinned LibreNMS OS-class and sensor-discovery hardware rules."""
    from services.librenms_source_policy import verify_librenms_os_rule

    os_key = str(rule.get("os_key") or "").strip().casefold()
    lineage = _librenms_os_rule_lineage(os_key)
    if (
        lineage is None
        or not verify_bundled_rule(rule)
        or not verify_librenms_os_rule({"source_type": "librenms_os_rule", **lineage})
    ):
        return {
            "sensors": [],
            "category_results": [_category_result(
                "nexora_snmp", "librenms_os_rule", status="unsupported",
                reason_code="unverified_librenms_os_rule",
                reason="The LibreNMS OS class and its MIB dependencies do not match the pinned bundle.",
            )],
        }

    mib_paths = {str(item).rsplit("/", 1)[-1]: item for item in lineage["mib_source_files"]}
    symbols: dict[str, str] = {}
    missing_symbols: list[str] = []
    missing_comware_symbols: dict[str, list[str]] = {}
    db_conn = None
    try:
        db_conn = get_db_connection()
    except Exception:
        db_conn = None
    try:
        requests: dict[str, tuple[str, str]] = {}
        if os_key == "ios":
            requests = {
                "cpu_rev": (mib_paths["CISCO-PROCESS-MIB"], "cpmCPUTotal5minRev"),
                "cpu_5min": (mib_paths["CISCO-PROCESS-MIB"], "cpmCPUTotal5min"),
                "cpu_physical": (mib_paths["CISCO-PROCESS-MIB"], "cpmCPUTotalPhysicalIndex"),
                "cpu_core": (mib_paths["CISCO-PROCESS-MIB"], "cpmCore5min"),
                "cpu_mem_free": (mib_paths["CISCO-PROCESS-MIB"], "cpmCPUMemoryFree"),
                "cpu_mem_used": (mib_paths["CISCO-PROCESS-MIB"], "cpmCPUMemoryUsed"),
                "cpu_mem_hc_used": (mib_paths["CISCO-PROCESS-MIB"], "cpmCPUMemoryHCUsed"),
                "cpu_mem_hc_free": (mib_paths["CISCO-PROCESS-MIB"], "cpmCPUMemoryHCFree"),
                "old_cpu": (mib_paths["OLD-CISCO-CPU-MIB"], "avgBusy5"),
                "cemp_used": (mib_paths["CISCO-ENHANCED-MEMPOOL-MIB"], "cempMemPoolUsed"),
                "cemp_valid": (mib_paths["CISCO-ENHANCED-MEMPOOL-MIB"], "cempMemPoolValid"),
                "cemp_name": (mib_paths["CISCO-ENHANCED-MEMPOOL-MIB"], "cempMemPoolName"),
                "cemp_hc_used": (mib_paths["CISCO-ENHANCED-MEMPOOL-MIB"], "cempMemPoolHCUsed"),
                "cemp_free": (mib_paths["CISCO-ENHANCED-MEMPOOL-MIB"], "cempMemPoolFree"),
                "cemp_hc_free": (mib_paths["CISCO-ENHANCED-MEMPOOL-MIB"], "cempMemPoolHCFree"),
                "cmp_used": (mib_paths["CISCO-MEMORY-POOL-MIB"], "ciscoMemoryPoolUsed"),
                "cmp_free": (mib_paths["CISCO-MEMORY-POOL-MIB"], "ciscoMemoryPoolFree"),
                "cmp_name": (mib_paths["CISCO-MEMORY-POOL-MIB"], "ciscoMemoryPoolName"),
                "qfp_cpu": (mib_paths["CISCO-ENTITY-QFP-MIB"], "ceqfpUtilProcessingLoad"),
                "entity_name": (mib_paths["ENTITY-MIB"], "entPhysicalName"),
            }
        else:
            requests = {
                "h3c_cpu": (mib_paths["HH3C-ENTITY-EXT-MIB"], "hh3cEntityExtCpuUsage"),
                "h3c_mem": (mib_paths["HH3C-ENTITY-EXT-MIB"], "hh3cEntityExtMemUsage"),
                "h3c_mem_size": (mib_paths["HH3C-ENTITY-EXT-MIB"], "hh3cEntityExtMemSize"),
                "h3c_temp": (mib_paths["HH3C-ENTITY-EXT-MIB"], "hh3cEntityExtTemperature"),
                "h3c_temp_threshold": (mib_paths["HH3C-ENTITY-EXT-MIB"], "hh3cEntityExtTemperatureThreshold"),
                "entity_name": (mib_paths["ENTITY-MIB"], "entPhysicalName"),
                "entity_class": (mib_paths["ENTITY-MIB"], "entPhysicalClass"),
                "if_admin": (mib_paths["IF-MIB"], "ifAdminStatus"),
                "if_name": (mib_paths["IF-MIB"], "ifName"),
                "if_descr": (mib_paths["IF-MIB"], "ifDescr"),
                "xcvr_temp": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverTemperature"),
                "xcvr_diagnostic": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverDiagnostic"),
                "xcvr_temp_hi_alarm": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverTempHiAlarm"),
                "xcvr_temp_lo_alarm": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverTempLoAlarm"),
                "xcvr_temp_hi_warn": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverTempHiWarn"),
                "xcvr_temp_lo_warn": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverTempLoWarn"),
                "xcvr_rx_power": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverCurRXPower"),
                "xcvr_tx_power": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverCurTXPower"),
                "xcvr_rx_hi_alarm": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverRcvPwrHiAlarm"),
                "xcvr_rx_lo_alarm": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverRcvPwrLoAlarm"),
                "xcvr_rx_hi_warn": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverRcvPwrHiWarn"),
                "xcvr_rx_lo_warn": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverRcvPwrLoWarn"),
                "xcvr_tx_hi_alarm": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverPwrOutHiAlarm"),
                "xcvr_tx_lo_alarm": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverPwrOutLoAlarm"),
                "xcvr_tx_hi_warn": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverPwrOutHiWarn"),
                "xcvr_tx_lo_warn": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverPwrOutLoWarn"),
                "xcvr_voltage": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverVoltage"),
                "xcvr_voltage_hi_alarm": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverVccHiAlarm"),
                "xcvr_voltage_lo_alarm": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverVccLoAlarm"),
                "xcvr_voltage_hi_warn": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverVccHiWarn"),
                "xcvr_voltage_lo_warn": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverVccLoWarn"),
                "xcvr_bias_current": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverBiasCurrent"),
                "xcvr_current_hi_alarm": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverBiasHiAlarm"),
                "xcvr_current_lo_alarm": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverBiasLoAlarm"),
                "xcvr_current_hi_warn": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverBiasHiWarn"),
                "xcvr_current_lo_warn": (mib_paths["HH3C-TRANSCEIVER-INFO-MIB"], "hh3cTransceiverBiasLoWarn"),
            }
        mib_cache: dict[tuple[str, str], str] = {}
        for key, (mib_path, symbol) in requests.items():
            oid = _resolve_pinned_librenms_mib_symbol(db_conn, mib_path, symbol, cache=mib_cache)
            if oid:
                symbols[key] = oid
            else:
                missing_item = f"{mib_path}::{symbol}"
                if os_key == "comware":
                    sensor_groups = {"temperature", "optical_power", "voltage", "current"}
                    if key == "h3c_cpu":
                        groups = {"processor"}
                    elif key in {"h3c_mem", "h3c_mem_size", "entity_class"}:
                        groups = {"memory_pool", "temperature"} if key == "entity_class" else {"memory_pool"}
                    elif key == "entity_name":
                        groups = {"memory_pool", "temperature"}
                    elif key in {"if_admin", "if_name", "if_descr", "xcvr_diagnostic"}:
                        groups = sensor_groups
                    elif key.startswith(("h3c_temp", "xcvr_temp")):
                        groups = {"temperature"}
                    elif key.startswith(("xcvr_rx", "xcvr_tx")):
                        groups = {"optical_power"}
                    elif key.startswith("xcvr_voltage"):
                        groups = {"voltage"}
                    elif key.startswith(("xcvr_current", "xcvr_bias")):
                        groups = {"current"}
                    else:
                        groups = {"hardware"}
                    for group in groups:
                        missing_comware_symbols.setdefault(group, []).append(missing_item)
                else:
                    missing_symbols.append(missing_item)
    finally:
        if db_conn is not None:
            try:
                db_conn.close()
            except Exception:
                pass

    if not symbols:
        return {
            "sensors": [],
            "category_results": [_category_result(
                "librenms_os_rule", "source", status="unsupported",
                reason_code="pinned_mib_symbols_unavailable",
                reason="The pinned LibreNMS MIB files are verified, but their symbol indexes are unavailable.",
            )],
        }

    reads = await _walk_many(
        ip, community,
        {oid for key, oid in symbols.items() if key != "old_cpu"},
        port, version, walk_func=walk_func,
    )
    rows = {key: _row_map(reads.get(oid)) for key, oid in symbols.items()}
    walk_complete = {
        key: bool(reads.get(oid) and reads[oid].complete and not reads[oid].reason)
        for key, oid in symbols.items()
    }
    entity_names = rows.get("entity_name", {})
    sensors: list[dict[str, Any]] = []
    category_results: list[dict[str, Any]] = []

    def add_sensor(
        *, component_class: str, measurement_type: str, source_id: str,
        oid: str, suffix: str, raw_value: Any, value: float | None,
        name: str, metadata: Mapping[str, Any], poll_plan: Mapping[str, Any],
        unit: str = "percent", thresholds: Mapping[str, Any] | None = None,
        index_labels: Mapping[str, Any] | None = None,
        entity_name: str = "", group_name: str = "",
    ) -> None:
        sensor = _sensor(
            source_type="librenms_os_rule", source_id=source_id,
            component_class=component_class, measurement_type=measurement_type,
            oid=oid, suffix=suffix, raw_value=raw_value, value=value,
            unit=unit, sensor_name=name, entity_name=entity_name,
            group_name=group_name, quality="good" if value is not None else "missing",
            thresholds=thresholds,
            metadata=_lineage_sensor_metadata(lineage, **dict(metadata)),
            poll_plan=poll_plan,
        )
        if sensor:
            if index_labels:
                sensor["index_labels"].update(dict(index_labels))
            sensors.append(sensor)

    if os_key == "comware":
        cpu_rows = rows.get("h3c_cpu", {})
        for suffix, raw in sorted(cpu_rows.items()):
            value = _snmp_numeric(raw)
            if value is None or value == 0:
                continue
            name = entity_names.get(suffix) or f"Processor {suffix}"
            add_sensor(
                component_class="processor", measurement_type="cpu_usage_percent",
                source_id=f"comware:processor:{suffix}", oid=symbols["h3c_cpu"],
                suffix=suffix, raw_value=raw, value=value, name=name,
                entity_name=name, group_name="processor",
                metadata={"librenms_mempool_type": "comware", "window": "unknown"},
                poll_plan={"kind": "direct", "oid": symbols["h3c_cpu"], "index": suffix},
            )
        cpu_ok = bool(walk_complete.get("h3c_cpu"))
        category_results.append(_category_result(
            "librenms_os_rule", "processor",
            status="success" if cpu_ok and any(s.get("component_class") == "processor" for s in sensors) else "not_found" if cpu_ok else "partial",
            complete=cpu_ok,
            reason_code="librenms_comware_cpu" if cpu_ok else "librenms_comware_cpu_walk_incomplete",
            reason="LibreNMS Comware CPU values exclude zero rows." if cpu_ok else "The Comware CPU walk did not complete.",
        ))

        mem_rows = rows.get("h3c_mem", {})
        mem_size = rows.get("h3c_mem_size", {})
        entity_classes = rows.get("entity_class", {})
        memory_count = 0
        for suffix, raw in sorted(mem_rows.items()):
            usage = _snmp_numeric(raw)
            class_value = str(entity_classes.get(suffix) or "").strip().casefold()
            class_is_module = class_value in {"9", "module", "module(9)"}
            if usage is None or usage <= 0 or not class_is_module:
                continue
            name = entity_names.get(suffix) or f"Entity {suffix}"
            add_sensor(
                component_class="memory_pool", measurement_type="memory_usage_percent",
                source_id=f"comware:mempool:{suffix}", oid=symbols["h3c_mem"],
                suffix=suffix, raw_value=raw, value=usage, name=name,
                entity_name=name, group_name="system",
                metadata={
                    "librenms_mempool_type": "comware",
                    "librenms_mem_size_bytes": mem_size.get(suffix),
                    "librenms_entity_class": class_value,
                },
                poll_plan={"kind": "direct", "oid": symbols["h3c_mem"], "index": suffix},
            )
            memory_count += 1
        memory_complete = all(walk_complete.get(key, False) for key in ("h3c_mem", "h3c_mem_size", "entity_name", "entity_class"))
        category_results.append(_category_result(
            "librenms_os_rule", "memory_pool",
            status="success" if memory_count and memory_complete else "partial" if memory_count else "not_found" if memory_complete else "failed",
            complete=memory_complete,
            reason_code="librenms_comware_mempool" if memory_count else "no_comware_module_memory" if memory_complete else "librenms_comware_mempool_walk_incomplete",
            reason="LibreNMS Comware memory requires module entities with nonzero usage." if memory_count else "No Comware module entity returned nonzero memory usage." if memory_complete else "The Comware memory/entity walks did not complete.",
        ))

        # LibreNMS keeps Comware sensor discovery in separate PHP rule files.
        # Python follows those fixed sources; it never executes the PHP files.
        sensor_class_values = {"8", "9", "sensor", "sensor(8)", "module", "module(9)"}
        temperature_count = 0
        entity_temperatures = rows.get("h3c_temp", {})
        entity_temp_thresholds = rows.get("h3c_temp_threshold", {})
        for suffix, raw in sorted(entity_temperatures.items()):
            value = _snmp_numeric(raw)
            entity_class = str(entity_classes.get(suffix) or "").strip().casefold()
            if value is None or value == 65535 or entity_class not in sensor_class_values:
                continue
            name = entity_names.get(suffix) or f"Entity {suffix}"
            upper = _snmp_numeric(entity_temp_thresholds.get(suffix))
            add_sensor(
                component_class="temperature", measurement_type="temperature_celsius",
                source_id=f"comware:temperature:entity:{suffix}", oid=symbols["h3c_temp"],
                suffix=suffix, raw_value=raw, value=value, name=name, entity_name=name,
                group_name="chassis", unit="celsius",
                thresholds={"critical_upper": upper} if upper is not None and upper != 65535 else {},
                metadata={"librenms_sensor_source": "HH3C-ENTITY-EXT-MIB::hh3cEntityExtTemperature"},
                poll_plan={"kind": "direct", "oid": symbols["h3c_temp"], "index": suffix},
            )
            temperature_count += 1

        admin_rows = rows.get("if_admin", {})
        if_name_rows = rows.get("if_name", {})
        if_descr_rows = rows.get("if_descr", {})
        diagnostic_rows = rows.get("xcvr_diagnostic", {})

        def active_transceiver_indices(value_key: str) -> list[str]:
            return [
                suffix for suffix, raw in sorted(rows.get(value_key, {}).items())
                if _snmp_numeric(raw) is not None
                and _snmp_numeric(raw) != 2147483647
                and suffix in diagnostic_rows
                and _snmp_interface_admin_up(admin_rows.get(suffix))
            ]

        def interface_label(suffix: str) -> str:
            return str(if_name_rows.get(suffix) or if_descr_rows.get(suffix) or f"Port {suffix}")[:300]

        def threshold_values(
            suffix: str,
            *,
            low_alarm: str,
            low_warn: str,
            high_warn: str,
            high_alarm: str,
            divisor: float,
        ) -> dict[str, float]:
            result: dict[str, float] = {}
            for field, row_key in (
                ("critical_lower", low_alarm), ("warning_lower", low_warn),
                ("warning_upper", high_warn), ("critical_upper", high_alarm),
            ):
                number = _snmp_numeric(rows.get(row_key, {}).get(suffix))
                if number is not None and number != 2147483647:
                    result[field] = number / divisor
            return result

        transceiver_categories: dict[str, tuple[str, str, str, str, float]] = {
            "temperature": ("xcvr_temp", "temperature_celsius", "celsius", "transceiver", 1.0),
            "optical_power": ("xcvr_rx_power", "optical_power_dbm", "dBm", "rx", 100.0),
            "voltage": ("xcvr_voltage", "voltage_volts", "volts", "transceiver", 100.0),
            "current": ("xcvr_bias_current", "current_amperes", "amperes", "transceiver", 100000.0),
        }
        for category, (value_key, measurement, unit, variant, divisor) in transceiver_categories.items():
            if category == "temperature":
                threshold_fields = (
                    "xcvr_temp_lo_alarm", "xcvr_temp_lo_warn",
                    "xcvr_temp_hi_warn", "xcvr_temp_hi_alarm",
                )
                threshold_divisor = 1000.0
            elif category == "optical_power":
                threshold_fields = (
                    "xcvr_rx_lo_alarm", "xcvr_rx_lo_warn",
                    "xcvr_rx_hi_warn", "xcvr_rx_hi_alarm",
                )
                threshold_divisor = 1.0
            elif category == "voltage":
                threshold_fields = (
                    "xcvr_voltage_lo_alarm", "xcvr_voltage_lo_warn",
                    "xcvr_voltage_hi_warn", "xcvr_voltage_hi_alarm",
                )
                threshold_divisor = 10000.0
            else:
                threshold_fields = (
                    "xcvr_current_lo_alarm", "xcvr_current_lo_warn",
                    "xcvr_current_hi_warn", "xcvr_current_hi_alarm",
                )
                threshold_divisor = 1000000.0

            indices = (
                sorted(set(active_transceiver_indices("xcvr_rx_power")) | set(active_transceiver_indices("xcvr_tx_power")))
                if category == "optical_power"
                else active_transceiver_indices(value_key)
            )
            for suffix in indices:
                if category == "optical_power":
                    for rx_tx, current_key, threshold_prefix in (
                        ("rx", "xcvr_rx_power", "xcvr_rx"),
                        ("tx", "xcvr_tx_power", "xcvr_tx"),
                    ):
                        tx_number = _snmp_numeric(rows.get(current_key, {}).get(suffix))
                        if tx_number is None or tx_number == 2147483647:
                            continue
                        port_name = interface_label(suffix)
                        thresholds = threshold_values(
                            suffix,
                            low_alarm=f"{threshold_prefix}_lo_alarm",
                            low_warn=f"{threshold_prefix}_lo_warn",
                            high_warn=f"{threshold_prefix}_hi_warn",
                            high_alarm=f"{threshold_prefix}_hi_alarm",
                            divisor=10.0,
                        )
                        thresholds = {
                            threshold: _microwatt_to_dbm(value)
                            for threshold, value in thresholds.items()
                        }
                        thresholds = {key: value for key, value in thresholds.items() if value is not None}
                        sensor_value = tx_number / divisor
                        add_sensor(
                            component_class="optical_power", measurement_type=measurement,
                            source_id=f"comware:transceiver:{rx_tx}:{suffix}",
                            oid=symbols[current_key], suffix=suffix, raw_value=rows[current_key][suffix],
                            value=sensor_value, name=f"{port_name} {'Receive' if rx_tx == 'rx' else 'Transmit'} Power",
                            entity_name=port_name, group_name="transceiver", unit=unit,
                            thresholds=thresholds,
                            metadata={
                                "librenms_sensor_source": f"HH3C-TRANSCEIVER-INFO-MIB::{('hh3cTransceiverCurRXPower' if rx_tx == 'rx' else 'hh3cTransceiverCurTXPower')}",
                                "series_variant": rx_tx,
                                "ent_physical_index_measured": "ports",
                            },
                            index_labels={"ifindex": suffix, "series_variant": rx_tx},
                            poll_plan={"kind": "direct", "oid": symbols[current_key], "index": suffix, "factor": 0.01},
                        )
                    continue
                raw = rows[value_key][suffix]
                number = _snmp_numeric(raw)
                if number is None or number == 2147483647:
                    continue
                port_name = interface_label(suffix)
                if category == "temperature":
                    thresholds = threshold_values(
                        suffix,
                        low_alarm=threshold_fields[0], low_warn=threshold_fields[1],
                        high_warn=threshold_fields[2], high_alarm=threshold_fields[3],
                        divisor=threshold_divisor,
                    )
                    sensor_name = f"{port_name} Module"
                else:
                    thresholds = threshold_values(
                        suffix,
                        low_alarm=threshold_fields[0], low_warn=threshold_fields[1],
                        high_warn=threshold_fields[2], high_alarm=threshold_fields[3],
                        divisor=threshold_divisor,
                    )
                    sensor_name = f"{port_name} {'Supply Voltage' if category == 'voltage' else 'Bias Current'}"
                add_sensor(
                    component_class="temperature" if category == "temperature" else category,
                    measurement_type=measurement, source_id=f"comware:transceiver:{category}:{suffix}",
                    oid=symbols[value_key], suffix=suffix, raw_value=raw,
                    value=number / divisor, name=sensor_name, entity_name=port_name,
                    group_name="transceiver", unit=unit, thresholds=thresholds,
                    metadata={
                        "librenms_sensor_source": f"HH3C-TRANSCEIVER-INFO-MIB::{value_key}",
                        "ent_physical_index_measured": "ports",
                    },
                    index_labels={"ifindex": suffix},
                    poll_plan={"kind": "direct", "oid": symbols[value_key], "index": suffix, "factor": 1.0 / divisor},
                )

            if category == "optical_power":
                # The PHP discovery file checks TX and RX independently. Count
                # each valid direction when reporting discovery completeness.
                category_sensor_count = sum(
                    1 for sensor in sensors
                    if sensor.get("source_id", "").startswith("comware:transceiver:rx:")
                    or sensor.get("source_id", "").startswith("comware:transceiver:tx:")
                )
                complete_keys = (
                    "if_admin", "if_name", "if_descr", "xcvr_diagnostic",
                    "xcvr_rx_power", "xcvr_tx_power", "xcvr_rx_hi_alarm", "xcvr_rx_lo_alarm",
                    "xcvr_rx_hi_warn", "xcvr_rx_lo_warn", "xcvr_tx_hi_alarm", "xcvr_tx_lo_alarm",
                    "xcvr_tx_hi_warn", "xcvr_tx_lo_warn",
                )
            else:
                category_sensor_count = sum(
                    1 for sensor in sensors
                    if sensor.get("source_id", "").startswith(f"comware:transceiver:{category}:")
                    or (category == "temperature" and sensor.get("source_id", "").startswith("comware:temperature:entity:"))
                )
                complete_keys = {
                    "temperature": (
                        "h3c_temp", "h3c_temp_threshold", "entity_name", "entity_class",
                        "if_admin", "if_name", "if_descr", "xcvr_diagnostic", "xcvr_temp",
                        "xcvr_temp_hi_alarm", "xcvr_temp_lo_alarm", "xcvr_temp_hi_warn", "xcvr_temp_lo_warn",
                    ),
                    "voltage": (
                        "if_admin", "if_name", "if_descr", "xcvr_diagnostic", "xcvr_voltage",
                        "xcvr_voltage_hi_alarm", "xcvr_voltage_lo_alarm", "xcvr_voltage_hi_warn", "xcvr_voltage_lo_warn",
                    ),
                    "current": (
                        "if_admin", "if_name", "if_descr", "xcvr_diagnostic", "xcvr_bias_current",
                        "xcvr_current_hi_alarm", "xcvr_current_lo_alarm", "xcvr_current_hi_warn", "xcvr_current_lo_warn",
                    ),
                }[category]
            is_complete = all(walk_complete.get(key, False) for key in complete_keys)
            category_result = _category_result(
                "librenms_os_rule", category,
                status="success" if category_sensor_count and is_complete else "partial" if category_sensor_count else "not_found" if is_complete else "failed",
                complete=is_complete,
                reason_code=f"librenms_comware_{category}" if category_sensor_count else f"no_comware_{category}_sensors" if is_complete else f"librenms_comware_{category}_walk_incomplete",
                reason=f"LibreNMS Comware {category} discovery returned {category_sensor_count} sensor(s)." if category_sensor_count else f"No Comware {category} sensors were returned by the pinned LibreNMS OID chain." if is_complete else f"One or more Comware {category} walks did not complete.",
            )
            if category in missing_comware_symbols:
                category_result["status"] = "partial" if category_sensor_count else "failed"
                category_result["coverage_complete"] = False
                category_result["reason_code"] = "pinned_mib_symbols_incomplete"
                category_result["reason"] = f"Pinned MIB symbol resolution is incomplete ({len(missing_comware_symbols[category])} symbol(s))."
            category_results.append(category_result)
    else:
        cpu_indices = set(rows.get("cpu_rev", {})) | set(rows.get("cpu_5min", {}))
        cpu_indices |= set(rows.get("cpu_physical", {}))
        cpu_indices |= set(rows.get("cpu_mem_free", {}))
        core_rows = rows.get("cpu_core", {})
        for suffix in sorted(cpu_indices):
            rev = rows.get("cpu_rev", {}).get(suffix)
            fallback = rows.get("cpu_5min", {}).get(suffix)
            raw = rev if _snmp_numeric(rev) is not None else fallback
            value = _snmp_numeric(raw)
            if value is None:
                continue
            physical_index = str(rows.get("cpu_physical", {}).get(suffix) or suffix).strip()
            name = entity_names.get(physical_index) or f"Processor {suffix}"
            cores = [
                (core_suffix, core_raw)
                for core_suffix, core_raw in sorted(core_rows.items())
                if core_suffix.startswith(f"{suffix}.") and _snmp_numeric(core_raw) is not None
            ]
            if cores:
                for core_suffix, core_raw in cores:
                    core_index = core_suffix.split(".", 1)[1]
                    core_value = _snmp_numeric(core_raw)
                    add_sensor(
                        component_class="processor", measurement_type="cpu_usage_percent",
                        source_id=f"ios:processor:core:{core_suffix}", oid=symbols["cpu_core"],
                        suffix=core_suffix, raw_value=core_raw, value=core_value,
                        name=f"{name}: Core {core_index}", entity_name=name, group_name="processor",
                        metadata={"librenms_processor_index": suffix, "librenms_core_index": core_index, "window": "5m"},
                        poll_plan={"kind": "direct", "oid": symbols["cpu_core"], "index": core_suffix},
                    )
            else:
                cpu_oid = symbols["cpu_rev"] if _snmp_numeric(rev) is not None else symbols["cpu_5min"]
                add_sensor(
                    component_class="processor", measurement_type="cpu_usage_percent",
                    source_id=f"ios:processor:{suffix}", oid=cpu_oid,
                    suffix=suffix, raw_value=raw, value=value, name=name,
                    entity_name=name, group_name="processor",
                    metadata={"librenms_processor_index": suffix, "librenms_physical_index": physical_index, "window": "5m"},
                    poll_plan={"kind": "direct", "oid": cpu_oid, "index": suffix},
                )

        cpu_complete = all(walk_complete.get(key, False) for key in ("cpu_rev", "cpu_5min", "cpu_physical", "cpu_core", "qfp_cpu"))
        if not any(s.get("component_class") == "processor" for s in sensors) and symbols.get("old_cpu"):
            scalar_oid = f"{symbols['old_cpu']}.0"
            scalar = await _get_many(ip, community, {scalar_oid}, port, version)
            raw = scalar.get(scalar_oid)
            value = _snmp_numeric(raw)
            if value is not None:
                add_sensor(
                    component_class="processor", measurement_type="cpu_usage_percent",
                    source_id="ios:processor:avgBusy5", oid=scalar_oid, suffix="0",
                    raw_value=raw, value=value, name="Processor", entity_name="Processor",
                    group_name="processor", metadata={"librenms_fallback": "OLD-CISCO-CPU-MIB::avgBusy5", "window": "5m"},
                    poll_plan={"kind": "get", "oid": scalar_oid},
                )

        for suffix, raw in sorted(rows.get("qfp_cpu", {}).items()):
            parts = _index_parts(suffix)
            value = _snmp_numeric(raw)
            if not parts or len(parts) < 2 or parts[-1] != 3 or value is None:
                continue
            entity_index = str(parts[0])
            name = entity_names.get(entity_index) or f"QFP {entity_index}"
            add_sensor(
                component_class="processor", measurement_type="cpu_usage_percent",
                source_id=f"ios:processor:qfp:{suffix}", oid=symbols["qfp_cpu"],
                suffix=suffix, raw_value=raw, value=value, name=f"{name}: QFP",
                entity_name=name, group_name="processor",
                metadata={"librenms_qfp_interval": "fiveMinutes", "librenms_physical_index": entity_index, "window": "5m"},
                poll_plan={"kind": "direct", "oid": symbols["qfp_cpu"], "index": suffix},
            )
        cpu_sensors = [s for s in sensors if s.get("component_class") == "processor"]
        category_results.append(_category_result(
            "librenms_os_rule", "processor",
            status="success" if cpu_sensors and cpu_complete else "partial" if cpu_sensors else "not_found" if cpu_complete else "failed",
            complete=cpu_complete,
            reason_code="librenms_cisco_cpu" if cpu_sensors else "no_cisco_processor_rows" if cpu_complete else "librenms_cisco_cpu_walk_incomplete",
            reason="LibreNMS Cisco CPU selection prefers five-minute process/core and QFP data, then avgBusy5." if cpu_sensors else "No Cisco CPU row was returned by the pinned LibreNMS OID chain." if cpu_complete else "One or more Cisco CPU walks did not complete.",
        ))

        memory_sensors: list[dict[str, Any]] = []

        def add_memory(
            *, pool_type: str, suffix: str, name: str,
            used_oid: str, free_oid: str, used_raw: Any, free_raw: Any,
            mib: str,
        ) -> None:
            used_value = _snmp_numeric(used_raw)
            free_value = _snmp_numeric(free_raw)
            ratio = None
            if used_value is not None and free_value is not None and used_value >= 0 and free_value >= 0 and used_value + free_value > 0:
                ratio = normalize_percentage(100.0 * used_value / (used_value + free_value))
            sensor_start = len(sensors)
            add_sensor(
                component_class="memory_pool", measurement_type="memory_usage_percent",
                source_id=f"ios:mempool:{pool_type}:{suffix}", oid=used_oid,
                suffix=suffix, raw_value=used_raw, value=ratio, name=name,
                entity_name=name, group_name="system",
                metadata={"librenms_mempool_type": pool_type, "librenms_memory_mib": mib},
                poll_plan={
                    "kind": "memory_ratio",
                    "used": {"oid": used_oid, "index": suffix, "factor": 1.0, "offset": 0.0},
                    "free": {"oid": free_oid, "index": suffix, "factor": 1.0, "offset": 0.0},
                },
            )
            if len(sensors) > sensor_start:
                memory_sensors.append(sensors[-1])

        cemp_rows = rows.get("cemp_used", {})
        cemp_valid = rows.get("cemp_valid", {})
        accepted_cemp: list[str] = []
        for suffix, raw in sorted(cemp_rows.items()):
            if _snmp_numeric(raw) is None or not _snmp_true(cemp_valid.get(suffix)):
                continue
            accepted_cemp.append(suffix)
        if accepted_cemp:
            for suffix in accepted_cemp:
                used_map = rows.get("cemp_hc_used", {})
                free_map = rows.get("cemp_hc_free", {})
                used_oid = symbols["cemp_hc_used"] if suffix in used_map else symbols["cemp_used"]
                free_oid = symbols["cemp_hc_free"] if suffix in free_map else symbols["cemp_free"]
                used_raw = used_map.get(suffix) if suffix in used_map else rows.get("cemp_used", {}).get(suffix)
                free_raw = free_map.get(suffix) if suffix in free_map else rows.get("cemp_free", {}).get(suffix)
                pool_name = str(rows.get("cemp_name", {}).get(suffix) or "Memory")
                physical_index = suffix.split(".", 1)[0]
                entity = entity_names.get(physical_index) or ""
                label = " - ".join(item for item in (entity, pool_name) if item).strip() or f"Memory pool {suffix}"
                add_memory(
                    pool_type="cemp", suffix=suffix, name=label,
                    used_oid=used_oid, free_oid=free_oid, used_raw=used_raw,
                    free_raw=free_raw, mib="CISCO-ENHANCED-MEMPOOL-MIB",
                )
        else:
            cmp_rows = rows.get("cmp_used", {})
            accepted_cmp = [suffix for suffix, raw in cmp_rows.items() if _snmp_numeric(raw) is not None and _index_parts(suffix)]
            if accepted_cmp:
                for suffix in sorted(accepted_cmp):
                    name = str(rows.get("cmp_name", {}).get(suffix) or f"Memory pool {suffix}")
                    add_memory(
                        pool_type="cmp", suffix=suffix, name=name,
                        used_oid=symbols["cmp_used"], free_oid=symbols["cmp_free"],
                        used_raw=cmp_rows.get(suffix), free_raw=rows.get("cmp_free", {}).get(suffix),
                        mib="CISCO-MEMORY-POOL-MIB",
                    )
            else:
                free_map = rows.get("cpu_mem_free", {})
                hc_used_map = rows.get("cpu_mem_hc_used", {})
                hc_free_map = rows.get("cpu_mem_hc_free", {})
                used_map = rows.get("cpu_mem_used", {})
                for suffix, free_raw in sorted(free_map.items()):
                    if _snmp_numeric(free_raw) is None or not _index_parts(suffix):
                        continue
                    hc_used = _snmp_numeric(hc_used_map.get(suffix))
                    hc_free = _snmp_numeric(hc_free_map.get(suffix))
                    use_hc = bool(hc_used)
                    free_hc = bool(hc_free)
                    used_oid = symbols["cpu_mem_hc_used"] if use_hc else symbols["cpu_mem_used"]
                    selected_free_oid = symbols["cpu_mem_hc_free"] if free_hc else symbols["cpu_mem_free"]
                    used_raw = hc_used_map.get(suffix) if use_hc else used_map.get(suffix)
                    selected_free_raw = hc_free_map.get(suffix) if free_hc else free_raw
                    physical_index = str(rows.get("cpu_physical", {}).get(suffix) or suffix)
                    entity = entity_names.get(physical_index) or f"Processor {suffix}"
                    add_memory(
                        pool_type="cpm", suffix=suffix, name=f"{entity} Memory",
                        used_oid=used_oid, free_oid=selected_free_oid,
                        used_raw=used_raw, free_raw=selected_free_raw,
                        mib="CISCO-PROCESS-MIB",
                    )

        if memory_sensors:
            mem_complete = all(
                walk_complete.get(key, False)
                for key in ("cemp_used", "cemp_valid", "cemp_name", "cemp_hc_used", "cemp_free", "cemp_hc_free")
            ) if accepted_cemp else all(
                walk_complete.get(key, False)
                for key in ("cmp_used", "cmp_free", "cmp_name")
            ) if any(s.get("metadata", {}).get("librenms_mempool_type") == "cmp" for s in memory_sensors) else all(
                walk_complete.get(key, False)
                for key in ("cpu_mem_free", "cpu_mem_used", "cpu_mem_hc_used", "cpu_mem_hc_free")
            )
            mem_status = "success" if mem_complete else "partial"
        else:
            mem_complete = all(walk_complete.get(key, False) for key in (
                "cemp_used", "cemp_valid", "cemp_name", "cemp_hc_used",
                "cemp_free", "cemp_hc_free", "cmp_used", "cmp_free",
                "cmp_name", "cpu_mem_free", "cpu_mem_used",
                "cpu_mem_hc_used", "cpu_mem_hc_free",
            ))
            mem_status = "not_found" if mem_complete else "failed"
        category_results.append(_category_result(
            "librenms_os_rule", "memory_pool", status=mem_status,
            complete=mem_complete,
            reason_code="librenms_cisco_mempool" if memory_sensors else "no_cisco_memory_pool" if mem_complete else "librenms_cisco_mempool_walk_incomplete",
            reason="LibreNMS Cisco memory priority is CEMP, Cisco Memory Pool MIB, then processor memory." if memory_sensors else "No Cisco memory-pool rows were returned by the pinned LibreNMS OID chain." if mem_complete else "One or more Cisco memory walks did not complete.",
        ))

    if missing_symbols:
        for result in category_results:
            result["coverage_complete"] = False
            result["reason_code"] = "pinned_mib_symbols_incomplete"
            result["reason"] = f"Pinned MIB symbol resolution is incomplete ({len(missing_symbols)} symbol(s))."
    return {"sensors": sensors, "category_results": category_results}




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
    # LibreNMS fillMissingRatio represents a percent-only pool as a 100-unit
    # total and derives used/free from that ratio.
    if roles == {"percent_used"}:
        return {"used", "total", "percent_used"}
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


def _librenms_round(value: float, precision: int = 0) -> float:
    quantizer = Decimal(1).scaleb(-precision)
    return float(Decimal(str(value)).quantize(quantizer, rounding=ROUND_HALF_UP))


def _normalize_librenms_mempool_percent(value: Any) -> float | None:
    """Mirror LibreNMS Number::normalizePercent() for mempool values."""
    percent = _number(value)
    if percent is None:
        return None
    while percent > 100:
        percent /= 10.0
    return _librenms_round(percent, 2)


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
    scaled_percent = normalize_scaled_value(percent_raw, factor, offset) if percent_raw is not None else None
    percent = _normalize_librenms_mempool_percent(scaled_percent)

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
        else:
            # LibreNMS Number::fillMissingRatio() uses a 100-unit denominator
            # when only the used percentage is available.
            quantities["total"] = 100.0
            quantities["used"] = percent
            quantities["free"] = 100.0 - percent
            if unit_factor is not None:
                byte_values["total"] = 100.0 * precision * unit_factor
                byte_values["used"] = percent * precision * unit_factor
                byte_values["free"] = (100.0 - percent) * precision * unit_factor

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
        "used": _librenms_round(byte_values["used"], 2) if byte_values["used"] is not None else None,
        "total": _librenms_round(byte_values["total"], 2) if byte_values["total"] is not None else None,
        # LibreNMS' Mempool model rounds mempool_perc to an integer on assignment.
        "percent_used": _librenms_round(percent) if percent is not None else None,
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
        for raw, state_value in states.items():
            generic_value = (
                state_value.get("generic")
                if isinstance(state_value, Mapping)
                else state_value
            )
            generic_code = _generic_state_code(generic_value)
            if generic_code is not None:
                mapping[str(raw)] = generic_code
    value = next(
        (generic for raw, generic in mapping.items() if _skip_values_equal(raw_value, raw)),
        None,
    )
    return (float(value) if value is not None else None), mapping, "good" if value is not None else "unsupported_mapping"


def _mapped_numeric_value(raw_value: Any, value_map: Any) -> float | None:
    """Normalize a direct numeric sensor through an explicit raw-value map."""
    if not isinstance(value_map, Mapping) or raw_value is None:
        return None
    raw_token = str(raw_value).strip().casefold()
    for raw, mapped in value_map.items():
        if raw_token == str(raw).strip().casefold():
            return _number(mapped)
    return None


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








































async def probe_librenms_hardware(
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str = "2c",
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None = None,
) -> dict[str, Any]:
    """Probe every structured OS rule row and retain each returned index."""
    if not verify_bundled_rule(rule) or not _pinned_hardware_definition_matches(rule):
        return {
            "sensors": [],
            "category_results": [_category_result(
                "librenms_rule", "source", status="unsupported",
                reason_code="unverified_librenms_rule",
                reason="The OS rule source or parsed hardware definitions do not match the pinned LibreNMS bundle.",
            )],
        }
    hardware = rule.get("hardware_definitions")
    if not isinstance(hardware, Mapping):
        hardware = {}
    vendor = str(rule.get("vendor") or identity.get("vendor") or "").strip().casefold()
    definitions: list[dict[str, Any]] = []
    for section in ("processors", "mempools", "sensors"):
        rows = hardware.get(section)
        if isinstance(rows, list):
            definitions.extend(dict(item) for item in rows if isinstance(item, Mapping))
    if not definitions:
        return {
            "sensors": [],
            "category_results": [_category_result(
                "librenms_rule", "source", status="unsupported",
                reason_code="unsupported_librenms_rule",
                reason="The pinned LibreNMS YAML rule has no hardware definitions supported by this executor.",
            )],
        }

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
            )
            item["_probe_oid"] = oid
            if oid:
                needed_oids.add(oid)
            template_oids: dict[str, str] = {}
            for template in (item.get("descr"), item.get("index")):
                for match in re.finditer(r"\{\{\s*([A-Za-z0-9_-]+::[A-Za-z0-9_-]+(?::[0-9]+(?:\.[0-9]+)*)?)\s*\}\}", str(template or "")):
                    token = match.group(1)
                    mib_symbol = re.sub(r":[0-9]+(?:\.[0-9]+)*$", "", token)
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
                        source_type="librenms_rule", source_id=rule_id,
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
                source_type="librenms_rule", source_id=source_id,
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
            status, reason_code, reason = "unsupported", "unsupported_definition", "One or more LibreNMS YAML definitions use unsupported semantics or an unresolved OID"
        else:
            status, reason_code, reason = "failed", "snmp_walk_failed", "SNMP returned an incomplete walk for this hardware category"
        category_results.append(_category_result(
            "librenms_rule", component_class, status=status,
            complete=bool(summary["complete"] and summary["supported"]),
            reason_code=reason_code, reason=reason,
        ))
    return {
        "sensors": sensors,
        "category_results": category_results,
    }


async def poll_hardware_inventory(
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    version: str,
    sensors: list[Mapping[str, Any]],
    *,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None = None,
) -> dict[str, int]:
    """Poll every active sensor with exact-instance GET batches, then persist samples."""
    sensors = [
        sensor for sensor in sensors
        if (
            str(sensor.get("measurement_type") or "").strip().casefold()
            not in _POLL_EXCLUDED_MEASUREMENT_TYPES
        )
    ]
    if not sensors:
        return {"good": 0, "missing": 0, "invalid": 0, "unsupported_mapping": 0}

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
                    "value_map": plan.get("value_map"),
                    "value_transform": str(plan.get("value_transform") or "").strip().casefold(),
                    "value_max": _number(plan.get("value_max")),
                    "raw_definition": plan.get("raw_definition", metadata.get("raw_definition", {})),
                    "index_suffix": plan.get("index_suffix") or plan.get("index") or "",
                }
        elif kind == "table_value":
            oid = _clean_oid(plan.get("oid"))
            index = str(plan.get("index") or ".".join(map(str, sensor.get("index") or []))).strip().strip(".")
            if oid and re.fullmatch(r"\d+(?:\.\d+)*", index):
                plans[str(sensor.get("sensor_key") or "")] = {
                    "kind": kind,
                    "oid": oid,
                    "index": index,
                    "factor": _number(plan.get("factor")) if _number(plan.get("factor")) is not None else 1.0,
                    "offset": _number(plan.get("offset")) if _number(plan.get("offset")) is not None else 0.0,
                    "fallback_value": _number(plan.get("fallback_value")),
                    "skip_values": plan.get("skip_values", metadata.get("skip_values")),
                    "skip_conditions_supported": plan.get("skip_conditions_supported", metadata.get("skip_conditions_supported", True)),
                    "transform_supported": plan.get("transform_supported", metadata.get("native_transform_supported", True)),
                }
        elif kind in {"table_count", "table_group_count", "table_sum", "table_group_sum"}:
            oid = _clean_oid(plan.get("oid"))
            if oid:
                raw_label_oids = plan.get("label_oids") if isinstance(plan.get("label_oids"), Mapping) else {}
                label_oids = {
                    str(name): clean_oid
                    for name, label_oid in raw_label_oids.items()
                    if (clean_oid := _clean_oid(label_oid))
                }
                raw_group_labels = plan.get("group_labels") if isinstance(plan.get("group_labels"), Mapping) else {}
                factor = _number(plan.get("factor"))
                plans[str(sensor.get("sensor_key") or "")] = {
                    "kind": kind,
                    "oid": oid,
                    "label_oids": label_oids,
                    "group_value": str(plan.get("group_value") or ""),
                    "group_labels": {
                        str(name): str(label).strip()
                        for name, label in raw_group_labels.items()
                        if label is not None
                    },
                    "factor": factor if factor is not None else 1.0,
                }
        elif kind == "table_multi_sum":
            # Wireless rules such as LibreNMS VRP pass an OID list to the
            # `sum` sensor and use the same encoded table index across bands.
            raw_oids = plan.get("oids") if isinstance(plan.get("oids"), (list, tuple, set)) else []
            oids = list(dict.fromkeys(
                clean_oid for raw_oid in raw_oids
                if (clean_oid := _clean_oid(raw_oid))
            ))
            raw_index = plan.get("index") if "index" in plan else ".".join(map(str, sensor.get("index") or []))
            index = str(raw_index or "").strip().strip(".")
            factor = _number(plan.get("factor"))
            if oids and (not index or re.fullmatch(r"\d+(?:\.\d+)*", index)):
                plans[str(sensor.get("sensor_key") or "")] = {
                    "kind": kind,
                    "oids": oids,
                    "index": index,
                    "factor": factor if factor is not None else 1.0,
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


    requested_instances: dict[str, set[tuple[str, str]]] = {}
    table_walk_oids: set[str] = set()
    for plan in plans.values():
        if plan["kind"] in {"table_value", "table_count", "table_group_count", "table_sum", "table_group_sum"}:
            table_walk_oids.add(plan["oid"])
            table_walk_oids.update(plan.get("label_oids", {}).values())
        elif plan["kind"] == "table_multi_sum":
            table_walk_oids.update(plan["oids"])

    def request_instance(base_oid: Any, suffix: Any = "") -> None:
        oid = _clean_oid(base_oid)
        index = str(suffix or "").strip().strip(".")
        if not oid or (index and not re.fullmatch(r"\d+(?:\.\d+)*", index)):
            return
        instance_oid = f"{oid}.{index}" if index else oid
        requested_instances.setdefault(instance_oid, set()).add((oid, index))

    def plan_index(plan: Mapping[str, Any], sensor: Mapping[str, Any]) -> str:
        if plan.get("index") not in (None, ""):
            return str(plan.get("index"))
        for dependency_name in ("used", "total", "free"):
            dependency = plan.get(dependency_name)
            if isinstance(dependency, Mapping) and dependency.get("index") not in (None, ""):
                return str(dependency.get("index"))
        return ".".join(map(str, sensor.get("index") or []))

    for sensor in sensors:
        sensor_key = str(sensor.get("sensor_key") or "")
        plan = plans.get(sensor_key)
        if not plan:
            continue
        kind = plan["kind"]
        suffix = plan_index(plan, sensor)
        if kind == "direct":
            request_instance(plan.get("oid"), suffix)
        elif kind == "get":
            request_instance(plan.get("oid"))
        elif kind in {"memory_ratio", "memory_component", "memory_sum"}:
            for name in ("used", "total", "free"):
                dependency = plan.get(name)
                if isinstance(dependency, Mapping):
                    request_instance(dependency.get("oid"), dependency.get("index") or suffix)
        elif kind == "memory_pool":
            for relation in plan.get("relations", {}).values():
                if isinstance(relation, Mapping) and relation.get("kind") == "oid":
                    request_instance(relation.get("oid"), relation.get("index") or suffix)
            if plan.get("unit_oid"):
                request_instance(plan.get("unit_oid"), suffix)


        raw_conditions = plan.get("skip_values")
        conditions = raw_conditions if isinstance(raw_conditions, list) else [raw_conditions]
        for condition in conditions:
            if not isinstance(condition, Mapping) or not condition.get("_oid"):
                continue
            if condition.get("_value_oid") or condition.get("_index"):
                continue
            request_instance(
                condition.get("_oid"),
                condition.get("_target_index") or suffix,
            )

    maps: dict[str, dict[str, str]] = {}
    complete_oids: set[str] = set()
    scalar_values: dict[str, str | None] = {}
    if walk_func is not None:
        # Keep the injectable walker contract for deterministic table fixtures.
        oids = {base_oid for pairs in requested_instances.values() for base_oid, _ in pairs}
        oids.update(table_walk_oids)
        reads = await _walk_many(ip, community, oids, port, version, walk_func=walk_func)
        maps = {oid: _row_map(read) for oid, read in reads.items()}
        complete_oids = {
            oid for oid, read in reads.items()
            if read.complete and not read.reason
        }
        get_oids = {
            plan["oid"] for plan in plans.values()
            if plan["kind"] == "get"
        }
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
    elif requested_instances:
        from services.snmp_service import _snmp_get_many_versioned

        raw_instances = await _snmp_get_many_versioned(
            ip, community, sorted(requested_instances), port, version,
        )
        requested_by_base: dict[str, list[str]] = {}
        for instance_oid, pairs in requested_instances.items():
            raw_value = raw_instances.get(instance_oid)
            for base_oid, suffix in pairs:
                requested_by_base.setdefault(base_oid, []).append(instance_oid)
                if raw_value is None:
                    continue
                if suffix:
                    maps.setdefault(base_oid, {})[suffix] = str(raw_value)
                else:
                    scalar_values[base_oid] = str(raw_value)
        complete_oids = {
            base_oid
            for base_oid, instance_oids in requested_by_base.items()
            if instance_oids and all(raw_instances.get(instance_oid) is not None for instance_oid in instance_oids)
        }
        # Aggregate LibreNMS wireless tables need a full walk on every poll;
        # their row set can change independently of the discovery snapshot.
        if table_walk_oids:
            table_reads = await _walk_many(ip, community, table_walk_oids, port, version)
            maps.update({oid: _row_map(read) for oid, read in table_reads.items()})
            complete_oids.update(
                oid for oid, read in table_reads.items()
                if read.complete and not read.reason
            )
    elif table_walk_oids:
        # A table-only poll still walks dynamically even though there are no
        # exact-instance GETs to issue.
        table_reads = await _walk_many(ip, community, table_walk_oids, port, version)
        maps.update({oid: _row_map(read) for oid, read in table_reads.items()})
        complete_oids.update(
            oid for oid, read in table_reads.items()
            if read.complete and not read.reason
        )
    now = datetime.now(timezone.utc)
    good = missing = invalid = unsupported = 0
    samples_to_persist: list[dict[str, Any]] = []
    for sensor in sensors:
            sensor_key = str(sensor.get("sensor_key") or "")
            plan = plans.get(sensor_key)
            if not plan:
                continue
            quality = "good"
            value: float | None = None
            raw_value: str | None = None
            try:
                if plan["kind"] in {"direct", "get", "table_value"}:
                    if plan["kind"] == "get":
                        raw_value = scalar_values.get(plan["oid"])
                    else:
                        table_complete = plan["kind"] != "table_value" or plan["oid"] in complete_oids
                        raw_value = maps.get(plan["oid"], {}).get(plan["index"]) if table_complete else None
                        if plan["kind"] == "table_value" and table_complete and raw_value is None and plan.get("fallback_value") is not None:
                            raw_value = str(plan["fallback_value"])
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
                        if measurement_type == "component_state":
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
                            if plan.get("value_map") is not None:
                                value = _mapped_numeric_value(raw_value, plan.get("value_map"))
                                if value is None:
                                    quality = "unsupported_mapping"
                            else:
                                value_transform = str(plan.get("value_transform") or "")
                                if value_transform == "channel_to_frequency":
                                    number = _wireless_channel_frequency(raw_value)
                                    if number is None:
                                        quality = "invalid"
                                elif value_transform == "aruba_instant_channel_to_frequency":
                                    number = _wireless_channel_frequency(raw_value, aruba_instant_encoding=True)
                                    if number is None:
                                        quality = "invalid"
                                elif value_transform:
                                    number = None
                                    quality = "unsupported_mapping"
                                elif plan.get("extract_percent") and raw_value is not None:
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
                                    if value is not None and plan.get("value_max") is not None:
                                        value = min(value, plan["value_max"])
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
                                elif quality == "good":
                                    quality = "missing"
                elif plan["kind"] == "table_multi_sum":
                    # Recompute the LibreNMS OID-list sum on every poll. A
                    # missing row in one complete source table contributes no
                    # value; incomplete walks must never produce a subtotal.
                    source_oids = set(plan["oids"])
                    if not source_oids.issubset(complete_oids):
                        quality = "missing"
                    else:
                        index = str(plan.get("index") or "")
                        if index:
                            raw_values = [
                                maps.get(oid, {}).get(index)
                                for oid in plan["oids"]
                                if maps.get(oid, {}).get(index) is not None
                            ]
                        else:
                            raw_values = [
                                raw
                                for oid in plan["oids"]
                                for raw in maps.get(oid, {}).values()
                            ]
                        if not raw_values:
                            quality = "missing"
                        else:
                            numbers = [_number(raw) for raw in raw_values]
                            if any(number is None for number in numbers):
                                quality = "invalid"
                            else:
                                total = sum(number for number in numbers if number is not None)
                                raw_value = str(total)
                                value = normalize_scaled_value(total, plan["factor"], 0.0)
                                if value is None:
                                    quality = "invalid"
                elif plan["kind"] in {"table_count", "table_group_count", "table_sum", "table_group_sum"}:
                    required_oids = {plan["oid"], *plan.get("label_oids", {}).values()}
                    if not required_oids.issubset(complete_oids):
                        # Partial table results are never recorded as good
                        # aggregates, even when their observed subtotal is valid.
                        quality = "missing"
                    elif plan["kind"] == "table_count":
                        row_count = len(maps.get(plan["oid"], {}))
                        raw_value = str(row_count)
                        value = float(row_count)
                    elif plan["kind"] == "table_group_count":
                        group_value = str(plan.get("group_value") or "")
                        row_count = sum(
                            1 for raw in maps.get(plan["oid"], {}).values()
                            if str(raw).strip() == group_value
                        )
                        raw_value = str(row_count)
                        value = float(row_count)
                    else:
                        table_rows = maps.get(plan["oid"], {})
                        group_labels = plan.get("group_labels", {})
                        label_oids = plan.get("label_oids", {})
                        matched_count = 0
                        numeric_values: list[float] = []
                        for row_suffix, raw in table_rows.items():
                            matches = True
                            if plan["kind"] == "table_group_sum":
                                for label_name, expected_label in group_labels.items():
                                    # LibreNMS wireless profiles use the row
                                    # suffix when a companion label row is absent.
                                    actual_label = maps.get(label_oids.get(label_name, ""), {}).get(row_suffix, row_suffix)
                                    if str(actual_label).strip().casefold() != str(expected_label).strip().casefold():
                                        matches = False
                                        break
                            if not matches:
                                continue
                            matched_count += 1
                            number = _number(raw)
                            if number is not None:
                                numeric_values.append(number)
                        if matched_count and not numeric_values:
                            quality = "invalid"
                        else:
                            raw_total = sum(numeric_values)
                            raw_value = str(raw_total)
                            value = normalize_scaled_value(raw_total, plan["factor"], 0.0)
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
            sample = {
                "device_id": str(sensor.get("device_id") or ""),
                "sensor_key": sensor_key,
                "value": value,
                "raw_value": raw_value,
                "quality": quality,
                "observed_at": now,
            }
            if str(sensor.get("measurement_type") or "").casefold() == "component_state":
                sample["presence_status"] = (
                    _state_presence(raw_value, sensor.get("states")) if quality == "good" else None
                )
            samples_to_persist.append(sample)
    await asyncio.to_thread(_persist_hardware_sensor_samples, samples_to_persist)
    return {"good": good, "missing": missing, "invalid": invalid, "unsupported_mapping": unsupported}


def _persist_hardware_sensor_samples(samples: list[dict[str, Any]]) -> None:
    """Persist one device's sample batch outside the async SNMP event loop."""
    if not samples:
        return
    from database import get_db_connection
    from services.snmp_hardware_inventory_service import record_sensor_samples_batch

    conn = get_db_connection()
    try:
        record_sensor_samples_batch(conn, samples)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = ["probe_librenms_hardware", "probe_librenms_os_hardware", "poll_hardware_inventory"]
