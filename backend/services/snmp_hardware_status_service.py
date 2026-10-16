"""Trusted, fresh hardware component status derived from local SNMP samples."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Mapping

from database import get_db_connection

logger = logging.getLogger(__name__)


def _parse_sample_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value not in (None, ""):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def summarize_hardware_component_statuses(
    sensors: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, str | None]:
    """Return the worst fresh trusted state for each supported component class.

    LibreNMS component-state mappings use 0=ok, 1=warning, 2=failed,
    3=unknown. Unknown or absent samples stay None so callers do not infer
    either a healthy recovery or a failure from missing data.
    """
    from services.librenms_source_policy import is_trusted_hardware_sensor
    from services.snmp_hardware_poller_service import DISCOVERY_VERSION, hardware_stale_after_seconds

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    status_codes = {0: "ok", 1: "warning", 2: "failed", 3: "unknown"}
    priorities = {"ok": 0, "unknown": 1, "warning": 2, "failed": 3}
    by_component: dict[str, list[str]] = {"fan_state": [], "power_supply_state": []}

    for sensor in sensors:
        if not isinstance(sensor, Mapping):
            continue
        component_class = str(sensor.get("component_class") or "").casefold()
        if component_class not in by_component:
            continue
        metadata = sensor.get("metadata") if isinstance(sensor.get("metadata"), Mapping) else {}
        if (
            not bool(sensor.get("enabled"))
            or str(sensor.get("lifecycle_status") or "").casefold() != "active"
            or (
                sensor.get("discovery_status") not in (None, "")
                and str(sensor.get("discovery_status")).casefold() != "present"
            )
            or str(sensor.get("last_quality") or "").casefold() != "good"
            or str(sensor.get("measurement_type") or "").casefold() != "component_state"
            or str(metadata.get("collection_version") or "") != DISCOVERY_VERSION
            or not is_trusted_hardware_sensor(sensor)
        ):
            continue
        sample_at = _parse_sample_time(sensor.get("last_success"))
        if sample_at is None or (current_time - sample_at).total_seconds() > hardware_stale_after_seconds(sensor):
            continue
        try:
            numeric_state = float(sensor.get("last_value"))
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(numeric_state) or not numeric_state.is_integer():
            continue
        status = status_codes.get(int(numeric_state))
        if status is not None:
            by_component[component_class].append(status)

    def combine(values: list[str]) -> str | None:
        return max(values, key=lambda value: priorities[value]) if values else None

    return {
        "fan_status": combine(by_component["fan_state"]),
        "psu_status": combine(by_component["power_supply_state"]),
    }


def current_hardware_component_statuses(conn: Any, device_id: str) -> dict[str, str | None]:
    """Read one device's current hardware state using the caller's connection."""
    try:
        from services.snmp_hardware_inventory_service import list_hardware_sensors

        sensors = [
            sensor
            for component_class in ("fan_state", "power_supply_state")
            for sensor in list_hardware_sensors(
                conn,
                str(device_id),
                component_class=component_class,
                include_retired=False,
            )
        ]
        return summarize_hardware_component_statuses(sensors)
    except Exception as exc:
        logger.debug(
            "Unable to read fresh trusted hardware component status for %s (%s)",
            device_id,
            type(exc).__name__,
        )
        return {"fan_status": None, "psu_status": None}


def load_current_hardware_component_statuses(device_id: str) -> dict[str, str | None]:
    """Open and close a connection while reading one device's current status."""
    conn = get_db_connection()
    try:
        return current_hardware_component_statuses(conn, device_id)
    finally:
        conn.close()
