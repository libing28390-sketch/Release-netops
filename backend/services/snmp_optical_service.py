"""Synchronous, SNMP-only optical transceiver collection.

The public :func:`collect_optical_snmp` contract is intentionally small and
safe for callers that also have a CLI based collection path.  It never calls
an interactive device driver and never returns resolved credentials::

    {
        "success": bool,
        "source": "snmp",
        "adapter": {"vendor": str, "supported": bool, "reason": str},
        "records": [
            {
                "interface": str, "ifIndex": int | None, "vendor": str,
                "rx_power_dbm": float, "tx_power_dbm": float,
                "temperature_c": float, "voltage_v": float,
                "bias_ma": float, "collected_at": str, "source": "snmp",
            }
        ],
        "count": int,
        "error_code": str,  # present on failures
        "error": str,       # safe, non-secret diagnostic
    }

Only fields backed by a finite, non-sentinel SNMP value are included in a
record.  A record with no valid optical value is discarded.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from services import snmp_service as _snmp_service

logger = logging.getLogger(__name__)

IF_NAME_OID = "1.3.6.1.2.1.31.1.1.1.1"
IF_DESCR_OID = "1.3.6.1.2.1.2.2.1.2"
IF_ADMIN_STATUS_OID = "1.3.6.1.2.1.2.2.1.7"
ENTITY_PHYSICAL_NAME_OID = "1.3.6.1.2.1.47.1.1.1.1.7"
ENTITY_PHYSICAL_DESCR_OID = "1.3.6.1.2.1.47.1.1.1.1.2"
ENTITY_PHYSICAL_CLASS_OID = "1.3.6.1.2.1.47.1.1.1.1.5"
ENTITY_PHYSICAL_CONTAINED_IN_OID = "1.3.6.1.2.1.47.1.1.1.1.4"
ENTITY_ALIAS_MAPPING_IDENTIFIER_OID = "1.3.6.1.2.1.47.1.3.2.1.2"
ENTITY_SENSOR_TYPE_OID = "1.3.6.1.2.1.99.1.1.1.1"
ENTITY_SENSOR_SCALE_OID = "1.3.6.1.2.1.99.1.1.1.2"
ENTITY_SENSOR_PRECISION_OID = "1.3.6.1.2.1.99.1.1.1.3"
ENTITY_SENSOR_VALUE_OID = "1.3.6.1.2.1.99.1.1.1.4"
ENTITY_SENSOR_STATUS_OID = "1.3.6.1.2.1.99.1.1.1.5"
CISCO_ENTITY_SENSOR_TYPE_OID = "1.3.6.1.4.1.9.9.91.1.1.1.1.1"
CISCO_ENTITY_SENSOR_SCALE_OID = "1.3.6.1.4.1.9.9.91.1.1.1.1.2"
CISCO_ENTITY_SENSOR_PRECISION_OID = "1.3.6.1.4.1.9.9.91.1.1.1.1.3"
CISCO_ENTITY_SENSOR_VALUE_OID = "1.3.6.1.4.1.9.9.91.1.1.1.1.4"
CISCO_ENTITY_SENSOR_STATUS_OID = "1.3.6.1.4.1.9.9.91.1.1.1.1.5"

# The table roots and column numbers are the vendor MIB definitions.  Keep
# these numeric so this collector does not depend on a local MIB compiler.
H3C_OPTICAL_BASE_OID = "1.3.6.1.4.1.25506.2.70.1.1.1"
JUNIPER_OPTICAL_BASE_OID = "1.3.6.1.4.1.2636.3.60.1.1.1.1"
RUIJIE_OPTICAL_BASE_OID = "1.3.6.1.4.1.4881.1.1.10.2.105.1.1.1"
ZTE_OPTICAL_BASE_OID = "1.3.6.1.4.1.3902.1082.30.40.2.4.1"
HUAWEI_OPTICAL_BASE_OID = "1.3.6.1.4.1.2011.5.25.31.1.1.3.1"
MAX_OPTICAL_WALK_ROWS = 4096
RAISECOM_LEGACY_DDM_BASE_OID = "1.3.6.1.4.1.8886.1.18.2.2.1"
RAISECOM_ROS_DDM_BASE_OID = "1.3.6.1.4.1.8886.60.18.1.2.2.1"
NOKIA_1830_DDM_BASE_OID = "1.3.6.1.4.1.7483.2.2.7.3.1.4.1.2"

_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_SENTINELS = {2147483647.0, -2147483648.0, -32768.0, -1000000.0}

async def _snmp_walk(*args: Any, **kwargs: Any) -> list[tuple[str, str]]:
    """Delegate to the shared SNMP transport while keeping a test seam."""
    return await _snmp_service._snmp_walk(*args, **kwargs)


def _run_async(coro: Any) -> Any:
    """Run a coroutine from both ordinary and already-running-loop callers."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    match = _NUMBER.search(str(value).strip())
    if not match:
        return None
    try:
        result = float(match.group(0))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result in _SENTINELS:
        return None
    return result


def _rows_by_suffix(rows: Any) -> dict[str, Any]:
    """Normalize the current SNMP walk tuple contract and test doubles."""
    result: dict[str, Any] = {}
    if not rows:
        return result
    if isinstance(rows, dict):
        rows = rows.items()
    for row in rows:
        suffix: Any = None
        value: Any = None
        if isinstance(row, (tuple, list)) and len(row) >= 2:
            suffix, value = row[0], row[1]
        elif isinstance(row, dict):
            suffix = row.get("suffix") or row.get("oid") or row.get("index")
            value = row.get("value")
        if suffix is None:
            continue
        result[str(suffix).strip().lstrip(".")] = value
    return result


def _index(suffix: Any) -> int | None:
    """Return the ifIndex component, safely ignoring lane/parameter suffixes."""
    tokens = [part for part in str(suffix or "").strip().lstrip(".").split(".") if part]
    if not tokens or not tokens[0].isdigit():
        return None
    try:
        value = int(tokens[0])
    except ValueError:
        return None
    return value if value > 0 else None


def _param_index(suffix: Any) -> tuple[int | None, int | None]:
    tokens = [part for part in str(suffix or "").strip().lstrip(".").split(".") if part]
    if len(tokens) < 2 or not tokens[0].isdigit() or not tokens[1].isdigit():
        return None, None
    return int(tokens[0]), int(tokens[1])


def _is_valid_status(value: Any) -> bool:
    number = _number(value)
    if number is not None:
        return int(number) == 1
    return str(value or "").strip().lower() in {"valid", "normal", "ok", "true", "yes"}


def _supported_vendor(device: dict[str, Any]) -> tuple[str, str] | None:
    vendor = str(device.get("vendor") or "").strip().lower().replace("-", "_")
    platform = str(device.get("platform") or "").strip().lower().replace("-", "_")
    # The platform check prevents a generic model name from selecting a MIB.
    if vendor == "h3c" and platform in {
        "h3c_comware", "h3c_comware3", "h3c_comware5", "h3c_comware7", "h3c_comware9",
        "h3c_comware_v3", "h3c_comware_v5", "h3c_comware_v7", "h3c_comware_v9", "hp_comware",
    }:
        return "H3C", "h3c"
    if vendor == "huawei" and platform in {"huawei_vrp", "huawei_vrp5", "huawei_vrp8", "huawei_vrpv8"}:
        return "Huawei", "huawei_vrp"
    if vendor == "juniper" and platform in {"juniper_junos", "junos"}:
        return "Juniper", "juniper"
    if vendor == "ruijie" and platform in {
        "ruijie_rgos", "ruijie_os", "rgos", "ruijie_s6k_rgos12", "ruijie_eg_rgos11",
        "ruijie_rgos_v10", "ruijie_rgos_v11", "ruijie_rgos_v12",
    }:
        return "Ruijie", "ruijie"
    if vendor == "zte" and platform in {"zte_zxros", "zte_5900_v6", "zxros"}:
        return "ZTE", "zte"
    if vendor == "raisecom" and platform in {
        "raisecom_ros", "raisecom_ros5", "raisecom_ros_5", "raisecom_ros_legacy", "raisecom_legacy", "ros", "legacy"
    }:
        return "Raisecom", "raisecom_ros" if platform in {"raisecom_ros", "ros"} else "raisecom_legacy"
    if vendor == "cisco" and platform in {"cisco_ios", "cisco_iosxe", "cisco_iosxr", "cisco_nxos"}:
        return "Cisco", "cisco_entity_sensor"
    if vendor == "arista" and platform == "arista_eos":
        return "Arista", "arista_entity_sensor"
    if vendor == "nokia" and platform == "nokia_1830":
        return "Nokia", "nokia_1830"
    return None


def _profile(kind: str) -> dict[str, Any]:
    if kind == "h3c":
        base = H3C_OPTICAL_BASE_OID
        return {
            "metrics": {
                "tx_power_dbm": (f"{base}.9", 100),
                "rx_power_dbm": (f"{base}.12", 100),
                "temperature_c": (f"{base}.15", 1),
                "voltage_v": (f"{base}.16", 100),
                "bias_ma": (f"{base}.17", 100),
            }
        }
    if kind == "juniper":
        base = JUNIPER_OPTICAL_BASE_OID
        return {"metrics": {"rx_power_dbm": (f"{base}.5", 100), "tx_power_dbm": (f"{base}.7", 100)}}
    if kind == "huawei_vrp":
        return {
            "metrics": {
                "rx_power_dbm": (f"{HUAWEI_OPTICAL_BASE_OID}.8", 1),
                "tx_power_dbm": (f"{HUAWEI_OPTICAL_BASE_OID}.9", 1),
            },
            # Admin status 12 is an entPhysical table column.  LibreNMS
            # excludes entries whose module is administratively unavailable.
            "admin_status": f"{HUAWEI_OPTICAL_BASE_OID}.12",
            "entity_name": ENTITY_PHYSICAL_NAME_OID,
            "serial": f"{HUAWEI_OPTICAL_BASE_OID}.4",
            "huawei_dual_encoding": True,
        }
    if kind == "ruijie":
        return {
            "metrics": {
                "rx_power_dbm": (f"{RUIJIE_OPTICAL_BASE_OID}.76", 100),
                "tx_power_dbm": (f"{RUIJIE_OPTICAL_BASE_OID}.81", 100),
                "temperature_c": (f"{RUIJIE_OPTICAL_BASE_OID}.17", 1),
                "voltage_v": (f"{RUIJIE_OPTICAL_BASE_OID}.19", 1000),
                "bias_ma": (f"{RUIJIE_OPTICAL_BASE_OID}.21", 1000),
            },
            "ddm": f"{RUIJIE_OPTICAL_BASE_OID}.15",
        }
    if kind == "zte":
        return {
            "metrics": {
                "rx_power_dbm": (f"{ZTE_OPTICAL_BASE_OID}.2", 1000),
                "tx_power_dbm": (f"{ZTE_OPTICAL_BASE_OID}.3", 1000),
                "bias_ma": (f"{ZTE_OPTICAL_BASE_OID}.5", 1000),
                "voltage_v": (f"{ZTE_OPTICAL_BASE_OID}.6", 1000),
                "temperature_c": (f"{ZTE_OPTICAL_BASE_OID}.8", 1000),
            }
        }
    if kind == "cisco_entity_sensor":
        return {
            "entity_sensor": True,
            "metrics": {"entity_sensor_value": (CISCO_ENTITY_SENSOR_VALUE_OID, 1)},
            "entity_sensor_type": CISCO_ENTITY_SENSOR_TYPE_OID,
            "entity_sensor_scale": CISCO_ENTITY_SENSOR_SCALE_OID,
            "entity_sensor_precision": CISCO_ENTITY_SENSOR_PRECISION_OID,
            "entity_sensor_status": CISCO_ENTITY_SENSOR_STATUS_OID,
            "entity_name": ENTITY_PHYSICAL_NAME_OID,
            "entity_descr": ENTITY_PHYSICAL_DESCR_OID,
            "entity_class": ENTITY_PHYSICAL_CLASS_OID,
            "entity_contained_in": ENTITY_PHYSICAL_CONTAINED_IN_OID,
            "entity_alias": ENTITY_ALIAS_MAPPING_IDENTIFIER_OID,
            "cisco_entity_sensor": True,
        }
    if kind == "arista_entity_sensor":
        return {
            "entity_sensor": True,
            "metrics": {"entity_sensor_value": (ENTITY_SENSOR_VALUE_OID, 1)},
            "entity_sensor_type": ENTITY_SENSOR_TYPE_OID,
            "entity_sensor_scale": ENTITY_SENSOR_SCALE_OID,
            "entity_sensor_precision": ENTITY_SENSOR_PRECISION_OID,
            "entity_sensor_status": ENTITY_SENSOR_STATUS_OID,
            "entity_name": ENTITY_PHYSICAL_NAME_OID,
            "entity_descr": ENTITY_PHYSICAL_DESCR_OID,
            "arista_entity_sensor": True,
        }
    if kind == "nokia_1830":
        return {
            "metrics": {
                "tx_power_dbm": (f"{NOKIA_1830_DDM_BASE_OID}.4", 10),
                "rx_power_dbm": (f"{NOKIA_1830_DDM_BASE_OID}.5", 10),
            },
            "admin_status": IF_ADMIN_STATUS_OID,
            "nokia_1830": True,
        }
    base = RAISECOM_ROS_DDM_BASE_OID if kind == "raisecom_ros" else RAISECOM_LEGACY_DDM_BASE_OID
    return {
        "raisecom": True,
        "value": f"{base}.2",
        # Column 11 is the number of valid 24-hour intervals.  The MIB's
        # DDMValidStatus is column 12 (valid(1), invalid(2)).
        "status": f"{base}.12",
    }


async def _collect_walks(server: str, community: str, port: int, profile: dict[str, Any]) -> dict[str, Any]:
    oids = {"if_name": IF_NAME_OID, "if_descr": IF_DESCR_OID}
    for field, (oid, _scale) in profile.get("metrics", {}).items():
        oids[field] = oid
    if profile.get("ddm"):
        oids["ddm"] = profile["ddm"]
    if profile.get("admin_status"):
        oids["admin_status"] = profile["admin_status"]
    if profile.get("entity_sensor_type"):
        oids["entity_sensor_type"] = profile["entity_sensor_type"]
    if profile.get("entity_sensor_scale"):
        oids["entity_sensor_scale"] = profile["entity_sensor_scale"]
    if profile.get("entity_sensor_precision"):
        oids["entity_sensor_precision"] = profile["entity_sensor_precision"]
    if profile.get("entity_sensor_status"):
        oids["entity_sensor_status"] = profile["entity_sensor_status"]
    if profile.get("entity_name"):
        oids["entity_name"] = profile["entity_name"]
    if profile.get("entity_descr"):
        oids["entity_descr"] = profile["entity_descr"]
    if profile.get("entity_class"):
        oids["entity_class"] = profile["entity_class"]
    if profile.get("entity_contained_in"):
        oids["entity_contained_in"] = profile["entity_contained_in"]
    if profile.get("entity_alias"):
        oids["entity_alias"] = profile["entity_alias"]
    if profile.get("serial"):
        oids["serial"] = profile["serial"]
    if profile.get("raisecom"):
        oids["value"] = profile["value"]
        oids["status"] = profile["status"]
    async def one(name: str, oid: str) -> tuple[str, Any]:
        return name, await _snmp_walk(
            server,
            community,
            oid,
            port=port,
            version="2c",
            max_rows=MAX_OPTICAL_WALK_ROWS,
            raise_on_error=True,
        )
    pairs = await asyncio.gather(*(one(name, oid) for name, oid in oids.items()), return_exceptions=True)
    result: dict[str, Any] = {}
    failed: list[str] = []
    for requested_name, pair in zip(oids, pairs):
        if isinstance(pair, Exception):
            failed.append(requested_name)
            continue
        name, rows = pair
        result[name] = _rows_by_suffix(rows)
    metric_names = set(profile.get("metrics", {}))
    if profile.get("raisecom"):
        metric_names = {"value"}
    if not metric_names.intersection(result):
        raise RuntimeError("all optical metric SNMP walks failed")
    result["_failed_walks"] = failed
    return result


def _exact_tokens(suffix: Any, count: int) -> tuple[str, ...] | None:
    tokens = tuple(part for part in str(suffix or "").strip().lstrip(".").split(".") if part)
    if len(tokens) != count or not all(token.isdigit() and int(token) > 0 for token in tokens):
        return None
    return tokens


def _entity_row(mapping: dict[str, Any], index: str) -> Any:
    return mapping.get(index, mapping.get(f"{index}.0"))


def _status_up(value: Any) -> bool:
    number = _number(value)
    if number is not None:
        return int(number) == 1
    return str(value or "").strip().lower() in {"up", "active", "running", "ok"}


def _entity_port_mapping(index: str, walks: dict[str, Any]) -> tuple[str, int] | None:
    """Resolve a Cisco entity sensor to an IF-MIB port using LibreNMS' path."""
    names = walks.get("entity_name", {})
    descriptions = walks.get("entity_descr", {})
    classes = walks.get("entity_class", {})
    contained = walks.get("entity_contained_in", {})
    aliases = walks.get("entity_alias", {})
    if_names = walks.get("if_name", {})
    if_descr = walks.get("if_descr", {})
    reverse_names = {str(value).strip(): int(key) for key, value in if_names.items() if str(key).isdigit() and str(value).strip()}

    current = str(index)
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        entity_name = str(_entity_row(names, current) or "").strip()
        entity_descr = str(_entity_row(descriptions, current) or "").strip()
        for candidate in (entity_name, entity_descr):
            if candidate in reverse_names:
                if_index = reverse_names[candidate]
                return str(if_names.get(str(if_index)) or if_descr.get(str(if_index)) or candidate), if_index

        entity_class_value = _entity_row(classes, current)
        entity_class = str(entity_class_value or "").strip().lower()
        is_port = entity_class == "port" or (_number(entity_class_value) is not None and int(_number(entity_class_value) or 0) == 10)
        if is_port:
            alias_identifier = str(_entity_row(aliases, current) or "").strip().lstrip(".")
            match = re.search(r"ifindex\.(\d+)", alias_identifier, re.IGNORECASE)
            if match is None:
                # puresnmp returns OBJECT IDENTIFIER values numerically while
                # LibreNMS' MIB-aware walker renders the same RowPointer as
                # ``ifIndex.<n>``. Accept only the IF-MIB ifIndex object OID.
                match = re.fullmatch(r"1\.3\.6\.1\.2\.1\.2\.2\.1\.1\.(\d+)", alias_identifier)
            if match and int(match.group(1)) > 0:
                if_index = int(match.group(1))
                name = str(if_names.get(str(if_index)) or if_descr.get(str(if_index)) or "").strip()
                if name:
                    return name, if_index

        parent = str(contained.get(current) or "").strip().lstrip(".")
        if not parent.isdigit() or int(parent) == 0:
            break
        current = parent
    return None


def _entity_fields(index: str, walks: dict[str, Any]) -> tuple[str, str, str]:
    name = str(_entity_row(walks.get("entity_name", {}), index) or "").strip()
    descr = str(_entity_row(walks.get("entity_descr", {}), index) or "").strip()
    return name, descr, " ".join(part for part in (name, descr) if part)


def _entity_if_mapping(index: str, walks: dict[str, Any]) -> tuple[str, int] | None:
    """Match an entity label to a real IF-MIB ifName without guessing."""
    name, descr, text = _entity_fields(index, walks)
    if_names = walks.get("if_name", {})
    candidates = [(str(value).strip(), int(key)) for key, value in if_names.items() if str(key).isdigit() and str(value).strip()]
    for if_name, if_index in candidates:
        if text == if_name or name == if_name or descr == if_name:
            return if_name, if_index
    matches = [item for item in candidates if re.search(rf"(?<![\w/.-]){re.escape(item[0])}(?![\w/.-])", text)]
    if len(matches) == 1:
        return matches[0]
    return None


def _entity_sensor_status_is_valid(index: str, walks: dict[str, Any]) -> bool:
    status = walks.get("entity_sensor_status", {}).get(index)
    if status is None:
        return False
    normalized = str(status).strip().lower()
    # ENTITY-SENSOR-MIB uses valid(1), unavailable(2), nonoperational(3),
    # notPresent(4), and uninitialized(5). Unknown values fail closed.
    return normalized in {"1", "ok", "valid", "normal", "true"}


def _entity_sensor_type(value: Any, *, cisco: bool) -> str:
    normalized = str(value or "").strip().lower()
    number = _number(value)
    if number is not None:
        code = int(number)
        if cisco and code == 14:
            return "dbm"
        return {1: "other", 2: "unknown", 6: "watts"}.get(code, normalized)
    return normalized


def _cisco_entity_value(index: str, value: float, walks: dict[str, Any]) -> float | None:
    scale = str(walks.get("entity_sensor_scale", {}).get(index) or "units").strip().lower()
    scale_divisors = {
        "yocto": 10**24, "zepto": 10**21, "atto": 10**18,
        "femto": 10**15, "pico": 10**12, "nano": 10**9,
        "micro": 10**6, "milli": 1000, "units": 1,
        "kilo": 1 / 1000, "mega": 1 / 1000000, "giga": 1 / 1000000000,
        "tera": 1 / 10**12, "exa": 1 / 10**15, "peta": 1 / 10**18,
        "zetta": 1 / 10**21, "yotta": 1 / 10**24,
    }
    scale_codes = {
        1: "yocto", 2: "zepto", 3: "atto", 4: "femto", 5: "pico",
        6: "nano", 7: "micro", 8: "milli", 9: "units", 10: "kilo",
        11: "mega", 12: "giga", 13: "tera", 14: "exa", 15: "peta",
        16: "zetta", 17: "yotta",
    }
    scale_number = _number(scale)
    if scale_number is not None and scale_number.is_integer():
        scale = scale_codes.get(int(scale_number), "")
    divisor = scale_divisors.get(scale)
    if divisor is None:
        return None
    precision = _number(walks.get("entity_sensor_precision", {}).get(index))
    if precision is not None and precision > 0 and precision != 1615384784:
        if not precision.is_integer() or precision > 18:
            return None
        divisor *= 10**int(precision)
    result = value / divisor
    return result if math.isfinite(result) else None


def _records(vendor: str, kind: str, profile: dict[str, Any], walks: dict[str, Any], collected_at: str) -> list[dict[str, Any]]:
    if kind in {"cisco_entity_sensor", "arista_entity_sensor"}:
        records: list[dict[str, Any]] = []
        values = walks.get("entity_sensor_value", {})
        types = walks.get("entity_sensor_type", {})
        for index, raw in values.items():
            index = str(index)
            number = _number(raw)
            if number is None or not _entity_sensor_status_is_valid(index, walks):
                continue
            entity_name, entity_descr, description = _entity_fields(index, walks)
            if kind == "cisco_entity_sensor":
                if _entity_sensor_type(types.get(index), cisco=True) != "dbm":
                    continue
                if number == -127:
                    continue
                number = _cisco_entity_value(index, number, walks)
                if number is None:
                    continue
                mapping = _entity_port_mapping(index, walks)
                if mapping is None:
                    # A dBm entity is useful only when it can be tied to a
                    # real port.  Do not invent interface or ifIndex fields.
                    continue
                interface, if_index = mapping
                record: dict[str, Any] = {
                    "interface": interface,
                    "ifIndex": if_index,
                    "vendor": vendor,
                    "rx_power_dbm": number if re.search(r"\b(?:rx|receive)\b", description, re.IGNORECASE) else None,
                    "tx_power_dbm": number if re.search(r"\b(?:tx|transmit)\b", description, re.IGNORECASE) else None,
                    "collected_at": collected_at,
                    "source": "snmp",
                }
                record = {key: value for key, value in record.items() if value is not None}
                if "rx_power_dbm" not in record and "tx_power_dbm" not in record:
                    continue
                records.append(record)
                continue

            direction = re.search(r"\bDOM\s+(Rx|Tx)\s+Power\b", description, re.IGNORECASE)
            sensor_type = _entity_sensor_type(types.get(index), cisco=False)
            if not direction or sensor_type not in {"other", "power", "watt", "watts"} or number <= 0:
                continue
            mapping = _entity_if_mapping(index, walks)
            if mapping is None:
                continue
            dbm = 10 * math.log10(number / 10000)
            if not math.isfinite(dbm):
                continue
            records.append({
                "interface": mapping[0],
                "ifIndex": mapping[1],
                "vendor": vendor,
                "rx_power_dbm" if direction.group(1).lower() == "rx" else "tx_power_dbm": round(dbm, 3),
                "collected_at": collected_at,
                "source": "snmp",
            })
        return records

    if kind == "nokia_1830":
        values: dict[int, dict[str, float]] = {}
        for field, (_oid, scale) in profile.get("metrics", {}).items():
            for suffix, raw in walks.get(field, {}).items():
                parts = _exact_tokens(suffix, 1)
                number = _number(raw)
                if parts is None or number is None or number == 0:
                    continue
                if_index = parts[0]
                if not _status_up(walks.get("admin_status", {}).get(if_index)):
                    continue
                values.setdefault(int(if_index), {})[field] = number / scale
        records = []
        for if_index, metrics in sorted(values.items()):
            interface = walks.get("if_name", {}).get(str(if_index)) or walks.get("if_descr", {}).get(str(if_index))
            if not interface:
                interface = f"ifIndex{if_index}"
            records.append({
                "interface": str(interface),
                "ifIndex": if_index,
                "vendor": vendor,
                **metrics,
                "collected_at": collected_at,
                "source": "snmp",
            })
        return records

    names = walks.get("entity_name", {}) if kind == "huawei_vrp" else walks.get("if_name", {})
    descriptions = {} if kind == "huawei_vrp" else walks.get("if_descr", {})
    values: dict[int, dict[str, float]] = {}
    if profile.get("raisecom"):
        for suffix, raw in walks.get("value", {}).items():
            if not _is_valid_status(walks.get("status", {}).get(suffix)):
                continue
            if_index, parameter = _param_index(suffix)
            number = _number(raw)
            if if_index is None or parameter not in {3, 4} or number is None:
                continue
            values.setdefault(if_index, {})["tx_power_dbm" if parameter == 3 else "rx_power_dbm"] = number / 1000
    else:
        for field, (_oid, scale) in profile.get("metrics", {}).items():
            for suffix, raw in walks.get(field, {}).items():
                if_index = _index(suffix)
                number = _number(raw)
                if if_index is None or number is None:
                    continue
                # LibreNMS does not treat a zero optical power reading as a
                # valid dBm value for Juniper; skip the unsupported sentinel.
                if kind == "juniper" and number == 0:
                    continue
                if profile.get("huawei_dual_encoding"):
                    admin_status = walks.get("admin_status", {}).get(suffix)
                    if admin_status is not None and int(_number(admin_status) or 0) == 12:
                        continue
                    # Huawei VRP returns positive values in microwatts and
                    # negative values as hundredths of a dBm.  Preserve both
                    # encodings exactly as LibreNMS does.
                    if number >= 0:
                        # Huawei documents the positive encoding in µW:
                        # dBm = 10 * log10(µW / 1000). Some releases expose
                        # negative values directly in hundredths of dBm.
                        number = 10 * math.log10(number / 1000) if number > 0 else None
                    else:
                        number = number / 100
                    if number is None or not math.isfinite(number):
                        continue
                # Ruijie uses -10000 as an invalid value; _number filters it.
                if kind == "ruijie":
                    ddm = walks["ddm"].get(suffix)
                    if number == -10000 or not _is_valid_status(ddm):
                        continue
                values.setdefault(if_index, {}).setdefault(field, number / scale)

    records: list[dict[str, Any]] = []
    serials = walks.get("serial", {})
    for index in sorted(values):
        metrics = {key: value for key, value in values[index].items() if math.isfinite(value)}
        if not metrics:
            continue
        fallback = f"entityIndex{index}" if kind == "huawei_vrp" else f"ifIndex{index}"
        name = names.get(str(index)) or descriptions.get(str(index)) or fallback
        record: dict[str, Any] = {
            "interface": str(name),
            "vendor": vendor,
            **metrics,
            "collected_at": collected_at,
            "source": "snmp",
        }
        if kind == "huawei_vrp":
            record["entityIndex"] = index
            serial = serials.get(str(index))
            if serial not in (None, ""):
                record["serial"] = str(serial)
        else:
            record["ifIndex"] = index
        records.append(record)
    return records


def collect_optical_snmp(device_info: dict[str, Any]) -> dict[str, Any]:
    """Collect optical DOM values through SNMP WALK only.

    ``device_info`` is an ordinary device mapping.  Credentials are resolved
    with ``resolve_collector_credentials``; an absent or empty SNMP community
    returns ``SNMP_CREDENTIALS_MISSING``.  Supported records are normalized to
    ``interface``, ``ifIndex``, ``vendor``, any valid metric fields,
    ``collected_at`` and ``source='snmp'``.  Unsupported vendors and all
    failures are structured responses and never contain the community string.
    """
    device = device_info if isinstance(device_info, dict) else {}
    selected = _supported_vendor(device)
    if selected is None:
        vendor = str(device.get("vendor") or "unknown").strip() or "unknown"
        return {
            "success": False,
            "source": "snmp",
            "adapter": {"vendor": vendor, "supported": False, "reason": "optical SNMP adapter is not confirmed"},
            "records": [],
            "count": 0,
            "error_code": "UNSUPPORTED_VENDOR",
            "error": "optical SNMP collection is unsupported for this vendor/platform",
        }

    vendor, kind = selected
    adapter = {"vendor": vendor, "supported": True, "reason": "confirmed SNMP optical MIB"}
    try:
        from services.vault_service import resolve_collector_credentials

        credentials = resolve_collector_credentials(device)
        snmp = credentials.get("snmp") if isinstance(credentials, dict) else None
        snmp = snmp if isinstance(snmp, dict) else {}
        community = str(snmp.get("community") or "")
        if not snmp.get("configured") or not community:
            return {
                "success": False,
                "source": "snmp",
                "adapter": adapter,
                "records": [],
                "count": 0,
                "error_code": "SNMP_CREDENTIALS_MISSING",
                "error": "SNMP credentials are not configured",
            }
        server = str(snmp.get("server") or device.get("ip_address") or "").strip()
        if not server:
            return {
                "success": False,
                "source": "snmp",
                "adapter": adapter,
                "records": [],
                "count": 0,
                "error_code": "SNMP_TARGET_MISSING",
                "error": "SNMP target address is missing",
            }
        port = int(snmp.get("port") or device.get("snmp_port") or 161)
        profile = _profile(kind)
        walks = _run_async(_collect_walks(server, community, port, profile))
        collected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        records = _records(vendor, kind, profile, walks, collected_at)
        failed_walks = walks.get("_failed_walks") or []
        return {
            "success": True,
            "source": "snmp",
            "adapter": adapter,
            "records": records,
            "count": len(records),
            **({"warning_code": "SNMP_WALK_PARTIAL", "failed_walks": failed_walks} if failed_walks else {}),
        }
    except Exception:
        # Deliberately avoid exception text: third-party SNMP errors may echo
        # the community or target details.
        logger.info("Optical SNMP collection failed for %s", device.get("hostname") or device.get("id") or "device")
        return {
            "success": False,
            "source": "snmp",
            "adapter": adapter,
            "records": [],
            "count": 0,
            "error_code": "SNMP_COLLECTION_ERROR",
            "error": "SNMP optical collection failed",
        }


__all__ = ["collect_optical_snmp"]
