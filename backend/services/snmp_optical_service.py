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
ENTITY_PHYSICAL_NAME_OID = "1.3.6.1.2.1.47.1.1.1.1.7"

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
    if profile.get("entity_name"):
        oids["entity_name"] = profile["entity_name"]
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


def _records(vendor: str, kind: str, profile: dict[str, Any], walks: dict[str, Any], collected_at: str) -> list[dict[str, Any]]:
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
