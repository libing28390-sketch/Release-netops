"""Read-only optical metadata projection from LibreNMS native results."""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_OPTICAL_CONTEXT = re.compile(r"\b(transceiver|xcvr|optic|optical|dom)\b", re.IGNORECASE)
_OPTICAL_CLASSES = {"dbm", "temperature", "temp", "voltage", "current"}
_ROW_FIELDS = (
    "sensor_id", "sensor_class", "device_id", "sensor_oid", "sensor_index",
    "sensor_type", "sensor_descr", "group", "sensor_current", "lastupdate",
    "entPhysicalIndex", "entPhysicalIndex_measured", "data_origin", "value_status",
    "freshness", "sample_age_seconds", "observed_at",
)


def _run_async(coro: Any) -> Any:
    """Run the async native API service from legacy synchronous callers."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _native_optical_rows(sensors: Any) -> list[dict[str, Any]]:
    """Keep LibreNMS values and identity fields unchanged; do no OID probing."""
    if not isinstance(sensors, list):
        return []
    rows: list[dict[str, Any]] = []
    for sensor in sensors:
        if not isinstance(sensor, Mapping):
            continue
        sensor_class = str(sensor.get("sensor_class") or "").strip().casefold()
        label = " ".join((str(sensor.get("sensor_descr") or ""), str(sensor.get("group") or "")))
        if sensor_class not in _OPTICAL_CLASSES or (
            sensor_class not in {"dbm"} and not _OPTICAL_CONTEXT.search(label)
        ):
            continue
        rows.append({field: sensor.get(field) for field in _ROW_FIELDS if field in sensor})
    return rows


def collect_librenms_optical(device_info: dict[str, Any]) -> dict[str, Any]:
    """Return native optical sensor rows for an explicitly bound device.

    The operation never resolves SNMP credentials or sends a hardware OID
    request. LibreNMS supplies sensor values, units/types, and sample times;
    the consumer receives those native fields without vendor conversion.
    """
    device = device_info if isinstance(device_info, dict) else {}
    adapter = {
        "mode": "librenms_native",
        "supported": False,
        "reason": "optical values are read from an explicit LibreNMS device binding",
    }
    try:
        from services.librenms_diagnostic_service import diagnose_librenms_hardware

        diagnostic = _run_async(diagnose_librenms_hardware(device))
    except Exception as exc:
        logger.info(
            "LibreNMS native optical read failed for %s (%s)",
            device.get("hostname") or device.get("id") or "device",
            type(exc).__name__,
        )
        return {
            "success": False,
            "source": "librenms_native",
            "adapter": adapter,
            "records": [],
            "transceivers": [],
            "count": 0,
            "error_code": "LIBRENMS_NATIVE_READ_FAILED",
            "error": "LibreNMS native optical results are unavailable",
        }

    sensors = _native_optical_rows(diagnostic.get("hardware_sensors"))
    transceivers = [
        dict(row)
        for row in diagnostic.get("transceivers", [])
        if isinstance(row, Mapping)
    ]
    state = str(diagnostic.get("state") or "unknown")
    connected_states = {"available", "metadata_only", "no_native_hardware_data"}
    adapter["supported"] = bool(sensors or transceivers)
    adapter["native_state"] = state
    success = state in connected_states
    result = {
        "success": success,
        "source": "librenms_native",
        "adapter": adapter,
        "records": sensors,
        "transceivers": transceivers,
        "count": len(sensors),
        "native_device_id": (diagnostic.get("identity") or {}).get("native_device_id"),
    }
    if not sensors and not transceivers:
        result.update({
            "error_code": "NO_NATIVE_OPTICAL_DATA",
            "error": "LibreNMS returned no optical sensor rows for this device",
        })
    return result


__all__ = ["collect_librenms_optical"]
