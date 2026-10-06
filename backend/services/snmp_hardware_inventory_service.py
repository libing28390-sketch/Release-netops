"""PostgreSQL persistence and Prometheus rendering for discovered hardware."""

from __future__ import annotations

import hashlib
import json
from itertools import islice
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence


_DISCOVERY_STATUSES = {"success", "partial", "failed", "unsupported", "not_found"}
_QUALITY_VALUES = {"good", "missing", "invalid", "stale", "unsupported_mapping"}
_PRESENCE_VALUES = {"present", "not_present"}
_SENSOR_SAMPLE_BATCH_SIZE = 500
_METRIC_FAMILIES = {
    "cpu_usage_percent": "nexora_hw_cpu_usage_percent",
    "memory_used_bytes": "nexora_hw_memory_used_bytes",
    "memory_total_bytes": "nexora_hw_memory_total_bytes",
    "memory_usage_percent": "nexora_hw_memory_usage_percent",
    "temperature_celsius": "nexora_hw_temperature_celsius",
    "fan_speed_rpm": "nexora_hw_fan_speed_rpm",
    "component_state": "nexora_hw_component_state",
    "component_present": "nexora_hw_component_present",
    "power_watts": "nexora_hw_power_watts",
    "voltage_volts": "nexora_hw_voltage_volts",
    "current_amperes": "nexora_hw_current_amperes",
    "optical_power_dbm": "nexora_hw_optical_power_dbm",
    "sensor_value": "nexora_hw_sensor_value",
    "wireless_sensor_value": "nexora_wireless_sensor_value",
}
_FAMILY_HELP = {
    "nexora_hw_sensor_info": "Discovered hardware sensor metadata.",
    "nexora_hw_sensor_quality": "Current quality state for a hardware sensor.",
    "nexora_hw_sensor_last_success_timestamp_seconds": "Unix timestamp of the last valid hardware sample.",
    "nexora_hw_cpu_usage_percent": "CPU utilization percentage for one processor measurement.",
    "nexora_hw_memory_used_bytes": "Memory used in bytes for one memory pool.",
    "nexora_hw_memory_total_bytes": "Memory total in bytes for one memory pool.",
    "nexora_hw_memory_usage_percent": "Memory utilization percentage for one memory pool.",
    "nexora_hw_temperature_celsius": "Temperature in degrees Celsius for one sensor.",
    "nexora_hw_fan_speed_rpm": "Fan speed in revolutions per minute.",
    "nexora_hw_component_state": "Normalized state code for one hardware component.",
    "nexora_hw_component_present": "Explicit hardware component presence state.",
    "nexora_hw_power_watts": "Power measurement in watts.",
    "nexora_hw_voltage_volts": "Voltage measurement in volts.",
    "nexora_hw_current_amperes": "Current measurement in amperes.",
    "nexora_hw_optical_power_dbm": "Optical receive or transmit power in dBm.",
    "nexora_hw_sensor_value": "Numeric LibreNMS sensor value without Nexora unit conversion.",
    "nexora_wireless_sensor_value": "Current LibreNMS-compatible wireless sensor value for one controller, AP, radio, or BSS entity.",
    "nexora_wireless_station_info": "Current associated H3C wireless station identity and access-point relation.",
}


class HardwareInventoryError(ValueError):
    """Invalid hardware inventory data or persistence request."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: Any, *, default: datetime | None = None) -> datetime:
    if value is None:
        if default is not None:
            return default
        return _utc_now()
    if isinstance(value, datetime):
        resolved = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise HardwareInventoryError("timestamp must not be empty")
        try:
            resolved = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HardwareInventoryError("timestamp must be ISO-8601") from exc
    else:
        raise HardwareInventoryError("timestamp must be a datetime or ISO-8601 string")
    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _clean_text(value: Any, *, field: str, limit: int = 500, required: bool = False) -> str:
    text = ("" if value is None else str(value)).strip()
    if required and not text:
        raise HardwareInventoryError(f"{field} must not be empty")
    return "".join(char for char in text if char >= " " or char in "\t\n\r")[:limit]


def _json_value(value: Any, *, field: str, default: Any) -> Any:
    if value is None:
        return default
    try:
        # Round-trip here rejects driver-specific objects and non-finite floats,
        # while producing a plain value that can be persisted as JSONB.
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise HardwareInventoryError(f"{field} must be JSON serializable") from exc


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _finite_number(value: Any, *, field: str, default: float | None = None) -> float | None:
    if value is None and default is None:
        return None
    try:
        number = float(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise HardwareInventoryError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise HardwareInventoryError(f"{field} must be finite")
    return number


def _row_value(row: Any, key: str, position: int) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return row[position]


def _canonical_index(value: Any) -> tuple[Any, str]:
    normalized = _json_value(value, field="index", default=[])
    return normalized, _json_text(normalized)


def build_sensor_key(
    source_type: str,
    component_class: str,
    measurement_type: str,
    index: Any,
    series_variant: str = "",
) -> str:
    """Return a stable key for one source, measurement, full index, and variant."""
    source = _clean_text(source_type, field="source_type", required=True).lower()
    component = _clean_text(component_class, field="component_class", required=True).lower()
    measurement = _clean_text(measurement_type, field="measurement_type", required=True).lower()
    variant = _clean_text(series_variant, field="series_variant", limit=100).lower()
    _, canonical = _canonical_index(index)
    identity = _json_text([source, component, measurement, json.loads(canonical), variant])
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    slug = re.sub(r"[^a-z0-9]+", "_", measurement).strip("_")[:28] or "measurement"
    return f"hw_{slug}_{digest}"


def _normalize_category_result(result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise HardwareInventoryError("each category result must be a mapping")
    source_type = _clean_text(result.get("source_type"), field="source_type", required=True).lower()
    component_class = _clean_text(result.get("component_class"), field="component_class", required=True).lower()
    status = _clean_text(result.get("status"), field="status", required=True).lower()
    if status not in _DISCOVERY_STATUSES:
        raise HardwareInventoryError(f"unsupported discovery status: {status}")
    coverage_complete = bool(result.get("coverage_complete", False)) and status in {"success", "not_found"}
    return {
        "source_type": source_type,
        "component_class": component_class,
        "status": status,
        "coverage_complete": coverage_complete,
        "reason_code": _clean_text(result.get("reason_code"), field="reason_code", limit=100),
        "reason": _clean_text(result.get("reason"), field="reason", limit=1000),
    }


def _normalize_sensor(sensor: Mapping[str, Any], observed_at: datetime) -> dict[str, Any]:
    if not isinstance(sensor, Mapping):
        raise HardwareInventoryError("each sensor must be a mapping")
    source_type = _clean_text(sensor.get("source_type"), field="source_type", required=True).lower()
    component_class = _clean_text(sensor.get("component_class"), field="component_class", required=True).lower()
    measurement_type = _clean_text(sensor.get("measurement_type"), field="measurement_type", required=True).lower()
    index, index_text = _canonical_index(sensor.get("index", []))
    index_labels = _json_value(sensor.get("index_labels"), field="index_labels", default={})
    states = _json_value(sensor.get("states"), field="states", default={})
    thresholds = _json_value(sensor.get("thresholds"), field="thresholds", default={})
    metadata = _json_value(sensor.get("metadata"), field="metadata", default={})
    if not isinstance(index_labels, dict):
        raise HardwareInventoryError("index_labels must be a JSON object")
    if not isinstance(states, (dict, list)):
        raise HardwareInventoryError("states must be a JSON object or array")
    if not isinstance(thresholds, (dict, list)):
        raise HardwareInventoryError("thresholds must be a JSON object or array")
    if not isinstance(metadata, dict):
        raise HardwareInventoryError("metadata must be a JSON object")
    variant_source = sensor.get("series_variant") or metadata.get("series_variant")
    if not variant_source and measurement_type == "cpu_usage_percent":
        variant_source = metadata.get("window") or "unknown"
    series_variant = _clean_text(variant_source, field="series_variant", limit=100).lower()
    presence_status = _clean_text(sensor.get("presence_status", "present"), field="presence_status").lower()
    if presence_status not in _PRESENCE_VALUES:
        raise HardwareInventoryError(f"unsupported presence_status: {presence_status}")
    oid = _clean_text(sensor.get("oid"), field="oid", limit=500)
    if not oid:
        raise HardwareInventoryError("sensor oid must not be empty")
    scale = _finite_number(sensor.get("scale", 1), field="scale", default=1.0)
    offset = _finite_number(sensor.get("offset", 0), field="offset", default=0.0)
    assert scale is not None and offset is not None
    sensor_key = build_sensor_key(source_type, component_class, measurement_type, index, series_variant)
    initial_quality = _clean_text(sensor.get("quality", "missing"), field="quality").lower()
    if initial_quality not in _QUALITY_VALUES:
        raise HardwareInventoryError(f"unsupported sample quality: {initial_quality}")
    initial_value = _finite_number(sensor.get("value"), field="value")
    raw_value = sensor.get("raw_value")
    if raw_value is not None:
        raw_value = _clean_text(raw_value, field="raw_value", limit=500)
    return {
        "source_type": source_type,
        "source_id": _clean_text(sensor.get("source_id"), field="source_id", limit=200),
        "component_class": component_class,
        "measurement_type": measurement_type,
        "series_variant": series_variant,
        "index": index,
        "index_text": index_text,
        "index_labels": index_labels,
        "sensor_key": sensor_key,
        "oid": oid,
        "unit": _clean_text(sensor.get("unit"), field="unit", limit=100),
        "scale": scale,
        "offset": offset,
        "states": states,
        "thresholds": thresholds,
        "metadata": metadata,
        "sensor_name": _clean_text(sensor.get("sensor_name"), field="sensor_name", limit=300),
        "entity_name": _clean_text(sensor.get("entity_name"), field="entity_name", limit=300),
        "group_name": _clean_text(sensor.get("group_name"), field="group_name", limit=200),
        "presence_status": presence_status,
        "value": initial_value,
        "raw_value": raw_value,
        "quality": initial_quality,
        "sample_at": _timestamp(sensor.get("sample_at"), default=observed_at) if sensor.get("value") is not None or raw_value is not None else None,
    }


def _get_sensor_key(row: Mapping[str, Any]) -> str:
    return str(row.get("sensor_key") or build_sensor_key(
        str(row.get("source_type") or ""),
        str(row.get("component_class") or ""),
        str(row.get("measurement_type") or ""),
        row.get("index", row.get("index_json", [])),
        str(row.get("series_variant") or ""),
    ))


def _active_count(conn, device_id: str, source_type: str, component_class: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*)
          FROM snmp_hardware_sensors
         WHERE device_id = ? AND source_type = ? AND component_class = ?
           AND lifecycle_status = 'active' AND discovery_status = 'present' AND enabled = TRUE
        """,
        (device_id, source_type, component_class),
    ).fetchone()
    return int(_row_value(row, "count", 0) or 0)


def _upsert_sensor(conn, *, device: Mapping[str, Any], sensor: Mapping[str, Any], rule_version: str, run_id: str, observed_at: datetime) -> None:
    initial_last_success = sensor["sample_at"] if sensor["value"] is not None and sensor["quality"] == "good" else None
    conn.execute(
        """
        INSERT INTO snmp_hardware_sensors (
            sensor_id, tenant_id, asset_id, device_id, sensor_key, source_type, source_id,
            component_class, measurement_type, series_variant, index_json, index_labels_json, oid, unit,
            scale, value_offset, states_json, thresholds_json, metadata_json, sensor_name,
            entity_name, group_name, rule_version, discovery_status, lifecycle_status,
            missing_success_count, last_missing_run_id, enabled, last_value, last_raw_value,
            last_quality, first_seen, last_seen, last_success, last_run_id, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, ?, ?, ?, ?::jsonb,
            ?::jsonb, ?::jsonb, ?, ?, ?, ?, ?, 'active', 0, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT (device_id, sensor_key)
        DO UPDATE SET
            tenant_id = EXCLUDED.tenant_id,
            asset_id = EXCLUDED.asset_id,
            source_id = EXCLUDED.source_id,
            index_labels_json = EXCLUDED.index_labels_json,
            oid = EXCLUDED.oid,
            unit = EXCLUDED.unit,
            scale = EXCLUDED.scale,
            value_offset = EXCLUDED.value_offset,
            states_json = EXCLUDED.states_json,
            thresholds_json = EXCLUDED.thresholds_json,
            metadata_json = EXCLUDED.metadata_json,
            sensor_name = EXCLUDED.sensor_name,
            entity_name = EXCLUDED.entity_name,
            group_name = EXCLUDED.group_name,
            rule_version = EXCLUDED.rule_version,
            discovery_status = EXCLUDED.discovery_status,
            lifecycle_status = 'active',
            missing_success_count = 0,
            last_missing_run_id = '',
            enabled = EXCLUDED.enabled,
            last_value = CASE
                WHEN EXCLUDED.last_seen >= snmp_hardware_sensors.last_seen AND EXCLUDED.last_value IS NOT NULL
                THEN EXCLUDED.last_value ELSE snmp_hardware_sensors.last_value END,
            last_raw_value = CASE
                WHEN EXCLUDED.last_seen >= snmp_hardware_sensors.last_seen AND EXCLUDED.last_raw_value IS NOT NULL
                THEN EXCLUDED.last_raw_value ELSE snmp_hardware_sensors.last_raw_value END,
            last_quality = CASE
                WHEN EXCLUDED.last_seen >= snmp_hardware_sensors.last_seen
                     AND (EXCLUDED.last_value IS NOT NULL OR EXCLUDED.last_raw_value IS NOT NULL)
                THEN EXCLUDED.last_quality ELSE snmp_hardware_sensors.last_quality END,
            first_seen = LEAST(snmp_hardware_sensors.first_seen, EXCLUDED.first_seen),
            last_seen = GREATEST(snmp_hardware_sensors.last_seen, EXCLUDED.last_seen),
            last_success = CASE
                WHEN EXCLUDED.last_success IS NULL THEN snmp_hardware_sensors.last_success
                WHEN snmp_hardware_sensors.last_success IS NULL THEN EXCLUDED.last_success
                ELSE GREATEST(snmp_hardware_sensors.last_success, EXCLUDED.last_success)
            END,
            last_run_id = EXCLUDED.last_run_id,
            updated_at = EXCLUDED.updated_at
        """,
        (
            str(uuid.uuid4()), device.get("tenant_id"), device.get("asset_id"), device["id"],
            sensor["sensor_key"], sensor["source_type"], sensor["source_id"],
            sensor["component_class"], sensor["measurement_type"], sensor["series_variant"],
            _json_text(sensor["index"]),
            _json_text(sensor["index_labels"]), sensor["oid"], sensor["unit"], sensor["scale"],
            sensor["offset"], _json_text(sensor["states"]), _json_text(sensor["thresholds"]),
            _json_text(sensor["metadata"]), sensor["sensor_name"], sensor["entity_name"],
            sensor["group_name"], rule_version, sensor["presence_status"],
            sensor["presence_status"] == "present", sensor["value"], sensor["raw_value"],
            sensor["quality"], observed_at, observed_at, initial_last_success, run_id,
            observed_at, observed_at,
        ),
    )


def _record_sensor_sample(
    conn,
    *,
    device_id: str,
    sensor_key: str,
    value: float | None,
    raw_value: str | None,
    quality: str,
    observed_at: datetime,
    presence_status: str | None = None,
) -> bool:
    presence_value = _normalize_sample_presence(quality, presence_status)
    existing = conn.execute(
        """
        SELECT last_seen FROM snmp_hardware_sensors
         WHERE device_id = ? AND sensor_key = ?
         FOR UPDATE
        """,
        (device_id, sensor_key),
    ).fetchone()
    if existing is None:
        return False
    previous_seen = _row_value(existing, "last_seen", 0)
    if previous_seen is not None and previous_seen > observed_at:
        # The target exists, but this older sample must not replace current data.
        return True

    cursor = conn.execute(
        """
        UPDATE snmp_hardware_sensors
           SET last_value = ?,
               last_raw_value = ?,
               last_quality = ?,
               last_seen = CASE WHEN last_seen IS NULL THEN ? ELSE GREATEST(last_seen, ?) END,
               lifecycle_status = CASE WHEN ? = 'good' THEN 'active' ELSE lifecycle_status END,
               discovery_status = CASE
                   WHEN ? = 'good' AND ? <> '' THEN ? ELSE discovery_status END,
               missing_success_count = CASE WHEN ? = 'good' THEN 0 ELSE missing_success_count END,
               last_missing_run_id = CASE WHEN ? = 'good' THEN '' ELSE last_missing_run_id END,
               enabled = CASE WHEN ? = 'good' THEN TRUE ELSE enabled END,
               last_success = CASE
                   WHEN ? <> 'good' THEN last_success
                   WHEN last_success IS NULL THEN ?
                   ELSE GREATEST(last_success, ?)
               END,
               updated_at = GREATEST(updated_at, ?)
         WHERE device_id = ? AND sensor_key = ?
        """,
        (
            value, raw_value, quality, observed_at, observed_at,
            quality, quality, presence_value, presence_value,
            quality, quality, quality, quality,
            observed_at, observed_at, observed_at, device_id, sensor_key,
        ),
    )
    return int(getattr(cursor, "rowcount", 0) or 0) > 0


def _normalize_sample_presence(quality: str, presence_status: Any) -> str:
    presence_value = str(presence_status or ("present" if quality == "good" else "")).strip().casefold()
    if presence_value and presence_value not in _PRESENCE_VALUES:
        raise HardwareInventoryError(f"unsupported presence_status: {presence_value}")
    return presence_value


def _normalize_sensor_sample(
    *,
    device_id: Any,
    sensor_key: Any,
    value: Any,
    raw_value: Any,
    quality: Any,
    observed_at: Any,
    presence_status: Any = None,
) -> dict[str, Any]:
    resolved_value = _finite_number(value, field="value")
    quality_value = _clean_text(quality, field="quality", required=True).lower()
    if quality_value not in _QUALITY_VALUES:
        raise HardwareInventoryError(f"unsupported sample quality: {quality_value}")
    raw_text = None if raw_value is None else _clean_text(raw_value, field="raw_value", limit=500)
    return {
        "device_id": _clean_text(device_id, field="device_id", required=True),
        "sensor_key": _clean_text(sensor_key, field="sensor_key", required=True),
        "value": resolved_value,
        "raw_value": raw_text,
        "quality": quality_value,
        "observed_at": _timestamp(observed_at),
        "presence_status": _normalize_sample_presence(quality_value, presence_status),
    }


def _update_sensor_sample_batch(conn, samples: Sequence[Mapping[str, Any]]) -> int:
    """Update one bounded set of normalized sensor samples in PostgreSQL."""
    if not samples:
        return 0
    # Explicitly type the numeric column: a chunk containing only NULL values
    # otherwise leaves PostgreSQL unable to infer the VALUES column type.
    values_sql = ", ".join(["(?, ?, CAST(? AS DOUBLE PRECISION), ?, ?, ?, ?)"] * len(samples))
    cursor = conn.execute(
        f"""
        UPDATE snmp_hardware_sensors AS sensor
           SET last_value = sample.value,
               last_raw_value = sample.raw_value,
               last_quality = sample.quality,
               last_seen = GREATEST(sensor.last_seen, sample.observed_at),
               lifecycle_status = CASE
                   WHEN sample.quality = 'good' THEN 'active' ELSE sensor.lifecycle_status END,
               discovery_status = CASE
                   WHEN sample.quality = 'good' AND sample.presence_status <> ''
                   THEN sample.presence_status ELSE sensor.discovery_status END,
               missing_success_count = CASE
                   WHEN sample.quality = 'good' THEN 0 ELSE sensor.missing_success_count END,
               last_missing_run_id = CASE
                   WHEN sample.quality = 'good' THEN '' ELSE sensor.last_missing_run_id END,
               enabled = CASE
                   WHEN sample.quality = 'good' THEN TRUE ELSE sensor.enabled END,
               last_success = CASE
                   WHEN sample.quality <> 'good' THEN sensor.last_success
                   WHEN sensor.last_success IS NULL THEN sample.observed_at
                   ELSE GREATEST(sensor.last_success, sample.observed_at)
               END,
               updated_at = GREATEST(sensor.updated_at, sample.observed_at)
          FROM (VALUES {values_sql}) AS sample(
              device_id, sensor_key, value, raw_value, quality, observed_at, presence_status
          )
         WHERE sensor.device_id = sample.device_id
           AND sensor.sensor_key = sample.sensor_key
           AND (sensor.last_seen IS NULL OR sensor.last_seen <= sample.observed_at)
        """,
        tuple(
            value
            for sample in samples
            for value in (
                sample["device_id"],
                sample["sensor_key"],
                sample["value"],
                sample["raw_value"],
                sample["quality"],
                sample["observed_at"],
                sample["presence_status"],
            )
        ),
    )
    return max(0, int(getattr(cursor, "rowcount", 0) or 0))


def _retire_unseen_sensors(
    conn,
    *,
    device_id: str,
    source_type: str,
    component_class: str,
    seen_sensor_keys: set[str],
    run_id: str,
    observed_at: datetime,
) -> None:
    rows = conn.execute(
        """
        SELECT sensor_key, missing_success_count, last_missing_run_id
          FROM snmp_hardware_sensors
         WHERE device_id = ? AND source_type = ? AND component_class = ?
           AND lifecycle_status <> 'retired'
         FOR UPDATE
        """,
        (device_id, source_type, component_class),
    ).fetchall()
    for row in rows:
        sensor_key = str(_row_value(row, "sensor_key", 0))
        if sensor_key in seen_sensor_keys or str(_row_value(row, "last_missing_run_id", 2) or "") == run_id:
            continue
        missing_count = int(_row_value(row, "missing_success_count", 1) or 0) + 1
        lifecycle_status = "retired" if missing_count >= 2 else "pending_retirement"
        conn.execute(
            """
            UPDATE snmp_hardware_sensors
               SET missing_success_count = ?, last_missing_run_id = ?,
                   lifecycle_status = ?, enabled = FALSE, updated_at = ?
             WHERE device_id = ? AND sensor_key = ?
            """,
            (missing_count, run_id, lifecycle_status, observed_at, device_id, sensor_key),
        )


def upsert_discovery_run(
    conn,
    device_id: str,
    run_id: str,
    rule_version: str,
    sensors: Sequence[Mapping[str, Any]],
    category_results: Sequence[Mapping[str, Any]],
    observed_at: Any,
    *,
    started_at: Any = None,
    discovery_version: str = "",
    artifact_version: str = "",
) -> dict[str, Any]:
    """Persist one device's per-source/category discovery attempt atomically.

    ``category_results`` is authoritative for coverage. Sensors are upserted for
    successful/partial scopes. Retirement requires a complete result with
    ``coverage_complete=True``; this includes an authoritative empty
    ``not_found`` result. Two distinct complete runs must miss a sensor.
    The caller owns the connection transaction and should commit or roll back.
    """
    resolved_device_id = _clean_text(device_id, field="device_id", required=True)
    resolved_run_id = _clean_text(run_id, field="run_id", limit=200, required=True)
    resolved_rule_version = _clean_text(rule_version, field="rule_version", limit=200)
    at = _timestamp(observed_at)
    started = _timestamp(started_at, default=at)
    if started > at:
        raise HardwareInventoryError("started_at must not be later than observed_at")
    results = [_normalize_category_result(result) for result in category_results]
    if not results:
        raise HardwareInventoryError("category_results must contain at least one result")
    result_by_scope: dict[tuple[str, str], dict[str, Any]] = {}
    for result in results:
        scope = (result["source_type"], result["component_class"])
        if scope in result_by_scope:
            raise HardwareInventoryError("category_results contains a duplicate source/category scope")
        result_by_scope[scope] = result

    normalized_sensors = [_normalize_sensor(sensor, at) for sensor in sensors]
    sensor_by_scope: dict[tuple[str, str], list[dict[str, Any]]] = {}
    identities: set[tuple[str, str, str, str, str]] = set()
    for sensor in normalized_sensors:
        scope = (sensor["source_type"], sensor["component_class"])
        result = result_by_scope.get(scope)
        if result is None:
            raise HardwareInventoryError("every sensor must have a matching category_results entry")
        if result["status"] not in {"success", "partial"}:
            raise HardwareInventoryError("failed/unsupported/not_found scopes cannot contain sensors")
        identity = (
            sensor["source_type"], sensor["component_class"],
            sensor["measurement_type"], sensor["index_text"], sensor["series_variant"],
        )
        if identity in identities:
            raise HardwareInventoryError("duplicate sensor identity in discovery input")
        identities.add(identity)
        sensor_by_scope.setdefault(scope, []).append(sensor)

    device_row = conn.execute(
        "SELECT id, tenant_id, asset_id FROM devices WHERE id = ? FOR UPDATE",
        (resolved_device_id,),
    ).fetchone()
    if device_row is None:
        raise HardwareInventoryError(f"device does not exist: {resolved_device_id}")
    device = {
        "id": str(_row_value(device_row, "id", 0)),
        "tenant_id": _row_value(device_row, "tenant_id", 1),
        "asset_id": _row_value(device_row, "asset_id", 2),
    }

    accepted_scopes: set[tuple[str, str]] = set()
    replayed_scopes: list[dict[str, str]] = []
    stale_scopes: list[dict[str, str]] = []
    for result in results:
        scope = (result["source_type"], result["component_class"])
        discovered = sensor_by_scope.get(scope, [])
        cursor = conn.execute(
            """
            INSERT INTO snmp_hardware_discovery_runs (
                attempt_id, run_id, device_id, tenant_id, asset_id, source_type,
                component_class, status, coverage_complete, discovered_count,
                rule_version, discovery_version, artifact_version, reason_code,
                reason, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (run_id, device_id, source_type, component_class) DO NOTHING
            RETURNING attempt_id
            """,
            (
                str(uuid.uuid4()), resolved_run_id, resolved_device_id, device["tenant_id"],
                device["asset_id"], result["source_type"], result["component_class"],
                result["status"], result["coverage_complete"], len(discovered),
                resolved_rule_version, _clean_text(discovery_version, field="discovery_version", limit=200),
                _clean_text(artifact_version, field="artifact_version", limit=200),
                result["reason_code"], result["reason"], started, at,
            ),
        )
        if cursor.fetchone() is None:
            replayed_scopes.append({"source_type": scope[0], "component_class": scope[1]})
            continue
        current = conn.execute(
            """
            SELECT last_attempt_at FROM snmp_hardware_capabilities
             WHERE device_id = ? AND source_type = ? AND component_class = ?
             FOR UPDATE
            """,
            (resolved_device_id, scope[0], scope[1]),
        ).fetchone()
        if current is not None and _row_value(current, "last_attempt_at", 0) > at:
            # Keep out-of-order results for diagnostics, but never let an older
            # run undo a newer inventory or capability state.
            stale_scopes.append({"source_type": scope[0], "component_class": scope[1]})
            continue
        accepted_scopes.add(scope)
        if result["status"] in {"success", "partial"}:
            for sensor in discovered:
                _upsert_sensor(
                    conn,
                    device=device,
                    sensor=sensor,
                    rule_version=resolved_rule_version,
                    run_id=resolved_run_id,
                    observed_at=at,
                )
            if result["status"] in {"success", "not_found"} and result["coverage_complete"]:
                _retire_unseen_sensors(
                    conn,
                    device_id=resolved_device_id,
                    source_type=scope[0],
                    component_class=scope[1],
                    seen_sensor_keys={sensor["sensor_key"] for sensor in discovered},
                    run_id=resolved_run_id,
                    observed_at=at,
                )

        active_count = _active_count(conn, resolved_device_id, scope[0], scope[1])
        conn.execute(
            """
            INSERT INTO snmp_hardware_capabilities (
                device_id, tenant_id, asset_id, source_type, component_class, last_status,
                coverage_complete, active_sensor_count, last_discovered_count, rule_version,
                discovery_version, artifact_version, last_run_id, last_attempt_at,
                last_success_at, reason_code, reason, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (device_id, source_type, component_class) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                asset_id = EXCLUDED.asset_id,
                last_status = EXCLUDED.last_status,
                coverage_complete = EXCLUDED.coverage_complete,
                active_sensor_count = EXCLUDED.active_sensor_count,
                last_discovered_count = CASE
                    WHEN EXCLUDED.last_status IN ('success', 'partial')
                      OR (EXCLUDED.last_status = 'not_found' AND EXCLUDED.coverage_complete)
                    THEN EXCLUDED.last_discovered_count
                    ELSE snmp_hardware_capabilities.last_discovered_count
                END,
                rule_version = EXCLUDED.rule_version,
                discovery_version = EXCLUDED.discovery_version,
                artifact_version = EXCLUDED.artifact_version,
                last_run_id = EXCLUDED.last_run_id,
                last_attempt_at = EXCLUDED.last_attempt_at,
                last_success_at = CASE
                    WHEN EXCLUDED.last_status IN ('success', 'not_found') AND EXCLUDED.coverage_complete
                    THEN CASE
                        WHEN snmp_hardware_capabilities.last_success_at IS NULL
                        THEN EXCLUDED.last_attempt_at
                        ELSE GREATEST(snmp_hardware_capabilities.last_success_at, EXCLUDED.last_attempt_at)
                    END
                    ELSE snmp_hardware_capabilities.last_success_at
                END,
                reason_code = EXCLUDED.reason_code,
                reason = EXCLUDED.reason,
                updated_at = EXCLUDED.updated_at
            """,
            (
                resolved_device_id, device["tenant_id"], device["asset_id"], scope[0], scope[1],
                result["status"], result["coverage_complete"], active_count,
                len(discovered) if result["status"] in {"success", "partial"} else 0,
                resolved_rule_version, _clean_text(discovery_version, field="discovery_version", limit=200),
                _clean_text(artifact_version, field="artifact_version", limit=200), resolved_run_id,
                at, at if result["status"] in {"success", "not_found"} and result["coverage_complete"] else None,
                result["reason_code"], result["reason"], at,
            ),
        )

    return {
        "run_id": resolved_run_id,
        "device_id": resolved_device_id,
        "accepted_scopes": [
            {"source_type": source, "component_class": category}
            for source, category in sorted(accepted_scopes)
        ],
        "replayed_scopes": replayed_scopes,
        "stale_scopes": stale_scopes,
        "results": [
            {
                "source_type": result["source_type"],
                "component_class": result["component_class"],
                "status": result["status"],
                "coverage_complete": result["coverage_complete"],
                "discovered_count": len(sensor_by_scope.get((result["source_type"], result["component_class"]), [])),
                "active_sensor_count": _active_count(conn, resolved_device_id, result["source_type"], result["component_class"]),
                "reason_code": result["reason_code"],
                "reason": result["reason"],
            }
            for result in results
        ],
    }


def record_sensor_sample(
    conn,
    device_id: str,
    sensor_key: str,
    value: Any,
    raw_value: Any,
    quality: str,
    observed_at: Any,
    presence_status: str | None = None,
) -> bool:
    """Store the latest normalized value and the corresponding raw value."""
    return _record_sensor_sample(
        conn,
        **_normalize_sensor_sample(
            device_id=device_id,
            sensor_key=sensor_key,
            value=value,
            raw_value=raw_value,
            quality=quality,
            observed_at=observed_at,
            presence_status=presence_status,
        ),
    )


def record_sensor_samples_batch(conn, samples: Iterable[Mapping[str, Any]]) -> int:
    """Persist normalized samples with bounded PostgreSQL multi-row updates.

    Samples are validated with the same rules as :func:`record_sensor_sample`.
    Missing targets and stale samples are skipped. The caller owns transaction
    commit and rollback behavior.
    """
    updated_count = 0
    iterator = iter(samples)
    while raw_chunk := list(islice(iterator, _SENSOR_SAMPLE_BATCH_SIZE)):
        normalized_chunk: list[dict[str, Any]] = []
        for sample in raw_chunk:
            if not isinstance(sample, Mapping):
                raise HardwareInventoryError("each sensor sample must be a mapping")
            normalized_chunk.append(
                _normalize_sensor_sample(
                    device_id=sample.get("device_id"),
                    sensor_key=sample.get("sensor_key"),
                    value=sample.get("value"),
                    raw_value=sample.get("raw_value"),
                    quality=sample.get("quality"),
                    observed_at=sample.get("observed_at"),
                    presence_status=sample.get("presence_status"),
                )
            )

        # PostgreSQL UPDATE ... FROM must not match a target row more than once.
        # Keep the last sample at the newest timestamp for each target, which
        # matches sequential record_sensor_sample calls within this chunk.
        newest_by_sensor: dict[tuple[str, str], dict[str, Any]] = {}
        for sample in normalized_chunk:
            key = (sample["device_id"], sample["sensor_key"])
            previous = newest_by_sensor.get(key)
            if previous is None or sample["observed_at"] >= previous["observed_at"]:
                newest_by_sensor[key] = sample
        updated_count += _update_sensor_sample_batch(conn, tuple(newest_by_sensor.values()))
    return updated_count


def mark_sensor_poll_success(conn, device_id: str, sensor_key: str, observed_at: Any) -> bool:
    """Advance last_success after a valid poll that did not change the value."""
    at = _timestamp(observed_at)
    target = conn.execute(
        """
        SELECT last_seen FROM snmp_hardware_sensors
         WHERE device_id = ? AND sensor_key = ?
         FOR UPDATE
        """,
        (device_id, sensor_key),
    ).fetchone()
    if target is None:
        return False
    previous_seen = _row_value(target, "last_seen", 0)
    if previous_seen is not None and previous_seen > at:
        return True
    cursor = conn.execute(
        """
        UPDATE snmp_hardware_sensors
           SET last_seen = CASE WHEN last_seen IS NULL THEN ? ELSE GREATEST(last_seen, ?) END,
               last_success = CASE WHEN last_success IS NULL THEN ? ELSE GREATEST(last_success, ?) END,
               last_quality = 'good', lifecycle_status = 'active',
               discovery_status = 'present', missing_success_count = 0,
               last_missing_run_id = '', enabled = TRUE,
               updated_at = GREATEST(updated_at, ?)
         WHERE device_id = ? AND sensor_key = ?
        """,
        (at, at, at, at, at, device_id, sensor_key),
    )
    return int(getattr(cursor, "rowcount", 0) or 0) > 0


def _decode_json_field(value: Any, *, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


def list_hardware_sensors(
    conn,
    device_id: str,
    *,
    component_class: str | None = None,
    include_retired: bool = True,
) -> list[dict[str, Any]]:
    """Read inventory rows in a JSON-decoded, stable integration shape."""
    clauses = ["device_id = ?"]
    params: list[Any] = [_clean_text(device_id, field="device_id", required=True)]
    if component_class:
        clauses.append("component_class = ?")
        params.append(_clean_text(component_class, field="component_class", required=True).lower())
    if not include_retired:
        clauses.append("lifecycle_status <> 'retired'")
    rows = conn.execute(
        f"""
        SELECT * FROM snmp_hardware_sensors
         WHERE {' AND '.join(clauses)}
         ORDER BY component_class, source_type, sensor_name, sensor_key
        """,
        tuple(params),
    ).fetchall()
    json_fields = {
        "index_json": "index",
        "index_labels_json": "index_labels",
        "states_json": "states",
        "thresholds_json": "thresholds",
        "metadata_json": "metadata",
    }
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for database_field, public_field in json_fields.items():
            item[public_field] = _decode_json_field(item.pop(database_field, None), fallback={} if public_field != "index" else [])
        result.append(item)
    return result


def list_hardware_metric_rows(conn) -> list[dict[str, Any]]:
    """Load active sensors with safe device labels for the internal metrics API."""
    rows = conn.execute(
        """
        SELECT s.*, d.hostname, d.platform, d.vendor, d.role,
               d.tenant_id AS device_tenant_id, d.asset_id AS device_asset_id,
               COALESCE(NULLIF(si.site_name, ''), NULLIF(si.site_code, ''), NULLIF(d.site, ''), '') AS site_name
          FROM snmp_hardware_sensors s
          JOIN devices d ON d.id = s.device_id
          LEFT JOIN physical_assets pa ON pa.id = d.asset_id
          LEFT JOIN sites si ON si.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
         WHERE s.lifecycle_status <> 'retired' AND s.enabled = TRUE
         ORDER BY s.device_id, s.component_class, s.sensor_key
        """
    ).fetchall()
    json_fields = {
        "index_json": ("index", []),
        "index_labels_json": ("index_labels", {}),
        "states_json": ("states", {}),
        "thresholds_json": ("thresholds", {}),
        "metadata_json": ("metadata", {}),
    }
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for db_field, (public_field, fallback) in json_fields.items():
            item[public_field] = _decode_json_field(item.get(db_field), fallback=fallback)
            item.pop(db_field, None)
        item["tenant_id"] = item.pop("tenant_id", None) or item.pop("device_tenant_id", None)
        item["asset_id"] = item.pop("asset_id", None) or item.pop("device_asset_id", None) or item.get("device_id")
        result.append(item)
    return result


def list_hardware_discovery_runs(
    conn,
    device_id: str,
    *,
    component_class: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List per-source/category discovery attempts, newest first."""
    cap = max(1, min(int(limit), 500))
    clauses = ["device_id = ?"]
    params: list[Any] = [_clean_text(device_id, field="device_id", required=True)]
    if component_class:
        clauses.append("component_class = ?")
        params.append(_clean_text(component_class, field="component_class", required=True).lower())
    params.append(cap)
    rows = conn.execute(
        f"""
        SELECT * FROM snmp_hardware_discovery_runs
         WHERE {' AND '.join(clauses)}
         ORDER BY started_at DESC, attempt_id DESC
         LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]


def list_hardware_capabilities(conn, device_id: str) -> list[dict[str, Any]]:
    """Return the latest discovery state for each source/category pair."""
    rows = conn.execute(
        """
        SELECT * FROM snmp_hardware_capabilities
         WHERE device_id = ?
         ORDER BY component_class, source_type
        """,
        (_clean_text(device_id, field="device_id", required=True),),
    ).fetchall()
    return [dict(row) for row in rows]


def _prom_escape(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _epoch_seconds(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return _timestamp(value).timestamp()
    except (HardwareInventoryError, OverflowError, OSError):
        return None


def _metric_value(value: Any) -> str | None:
    number = _finite_number(value, field="metric value")
    if number is None:
        return None
    if number == 0:
        return "0"
    return format(number, ".15g")


def _state_description(raw_value: Any, states: Any) -> str:
    raw_token = str(raw_value).strip()
    if isinstance(states, list):
        for item in states:
            if not isinstance(item, Mapping) or item.get("value") is None:
                continue
            if str(item.get("value")).strip() == raw_token:
                return _clean_text(item.get("descr") or item.get("description"), field="state description", limit=120)
    elif isinstance(states, Mapping):
        item = states.get(raw_token)
        if isinstance(item, Mapping):
            return _clean_text(item.get("descr") or item.get("description"), field="state description", limit=120)
    return ""


def _presence_metric_value(description: str) -> str | None:
    token = re.sub(r"[\s_-]+", " ", str(description).casefold()).strip()
    if any(value in token for value in ("not install", "not present", "not installed", "absent", "uninstalled")):
        return "0"
    if token in {"active", "installed", "present", "online", "running", "normal", "ok"}:
        return "1"
    return None


def _labels_text(labels: Mapping[str, Any], *, include_empty: bool = False) -> str:
    entries = [
        f'{name}="{_prom_escape(value)}"'
        for name, value in sorted(labels.items())
        if value is not None and (include_empty or str(value) != "")
    ]
    return "{" + ",".join(entries) + "}"


def render_hardware_metrics(sensors: Sequence[Mapping[str, Any]], device_labels: Mapping[str, Any]) -> str:
    """Render inventory metadata and current canonical values as Prometheus text.

    Values must already be normalized to the unit specified by the metric
    contract. Raw values and failure reasons are never emitted as labels.
    """
    if not isinstance(device_labels, Mapping):
        raise HardwareInventoryError("device_labels must be a mapping")
    allowed_device_labels = ("tenant_id", "asset_id", "device_id", "hostname", "site_name", "vendor", "platform", "role")
    lines_by_family: dict[str, list[tuple[str, str]]] = {}
    wireless_station_samples: dict[tuple[str, ...], dict[str, Any]] = {}

    def add(
        family: str,
        labels: Mapping[str, Any],
        value: str,
        *,
        include_empty: bool = False,
    ) -> None:
        lines_by_family.setdefault(family, []).append((
            _labels_text(labels, include_empty=include_empty), value,
        ))

    for sensor in sensors:
        if not isinstance(sensor, Mapping):
            raise HardwareInventoryError("each renderer sensor must be a mapping")
        lifecycle = str(sensor.get("lifecycle_status") or "active")
        if lifecycle == "retired" or sensor.get("enabled") is False:
            continue
        base = {name: device_labels.get(name) for name in allowed_device_labels}
        for name in ("tenant_id", "asset_id", "device_id"):
            if sensor.get(name) not in (None, ""):
                base[name] = sensor[name]
        sensor_key = _get_sensor_key(sensor)
        base["sensor_key"] = sensor_key
        base["source_type"] = sensor.get("source_type", "")
        base["component_class"] = sensor.get("component_class", "")
        base["measurement_type"] = sensor.get("measurement_type", "")
        metadata = _decode_json_field(sensor.get("metadata", sensor.get("metadata_json")), fallback={})
        index_labels = _decode_json_field(sensor.get("index_labels", sensor.get("index_labels_json")), fallback={})
        if isinstance(index_labels, dict) and index_labels.get("ent_physical_index") not in (None, ""):
            base["ent_physical_index"] = index_labels["ent_physical_index"]
        if isinstance(index_labels, dict):
            for label_name in ("ap_id", "ap_name", "ap_model", "ap_ip", "ap_mac", "ap_serial", "radio_id", "radio_index", "radio_ifindex", "radio_mac", "radio_mode", "wlan_id", "ssid", "ssid_index", "radio_band", "bssid", "vlan_id"):
                label_value = index_labels.get(label_name)
                if label_value not in (None, ""):
                    base[label_name] = _clean_text(label_value, field=label_name, limit=120)
        if isinstance(metadata, dict) and metadata.get("ent_physical_index_measured"):
            base["measured_entity_type"] = metadata["ent_physical_index_measured"]
        if sensor.get("rule_version"):
            base["rule_version"] = sensor.get("rule_version")
        explicit_window = metadata.get("window") if isinstance(metadata, dict) else None
        base["window"] = _clean_text(explicit_window, field="window", limit=100) or "unknown"

        info_labels = dict(base)
        for label_name, field_name in (
            ("source_id", "source_id"),
            ("sensor_name", "sensor_name"),
            ("entity_name", "entity_name"),
            ("group_name", "group_name"),
            ("unit", "unit"),
            ("discovery_status", "discovery_status"),
            ("lifecycle_status", "lifecycle_status"),
        ):
            info_labels[label_name] = sensor.get(field_name, "")
        info_labels["group"] = sensor.get("group_name", "")
        index_value = _decode_json_field(sensor.get("index", sensor.get("index_json")), fallback=[])
        info_labels["index"] = _json_text(index_value)
        if isinstance(index_labels, dict):
            info_labels["index_labels"] = _json_text(index_labels)
        add("nexora_hw_sensor_info", info_labels, "1")

        quality = str(sensor.get("last_quality") or "missing").lower()
        if quality not in _QUALITY_VALUES:
            quality = "invalid"
        quality_labels = dict(base)
        quality_labels["quality"] = quality
        add("nexora_hw_sensor_quality", quality_labels, "1")

        success_timestamp = _epoch_seconds(sensor.get("last_success"))
        if success_timestamp is not None:
            add(
                "nexora_hw_sensor_last_success_timestamp_seconds",
                base,
                _metric_value(success_timestamp) or "0",
            )

        measurement_type = str(sensor.get("measurement_type") or "").lower()
        if (
            measurement_type == "wireless_station_attribute"
            and str(sensor.get("source_type") or "").lower() == "h3c_wireless"
            and str(sensor.get("component_class") or "").lower() == "wireless_station"
            and quality == "good"
            and str(sensor.get("discovery_status") or "present").lower() == "present"
        ):
            last_success = _epoch_seconds(sensor.get("last_success"))
            station_mac = _clean_text(
                metadata.get("station_mac"), field="station MAC", limit=32,
            )
            if last_success is not None and station_mac:
                station_context = {
                    name: base[name]
                    for name in allowed_device_labels
                    if base.get(name) not in (None, "")
                }
                station_identity = tuple(
                    str(station_context.get(name) or "")
                    for name in allowed_device_labels
                ) + (station_mac,)
                station = wireless_station_samples.setdefault(station_identity, {
                    "context": station_context,
                    "fields": {
                        "station_mac": station_mac,
                        "station_ip": "",
                        "ap_name": "",
                        "ssid": "",
                        "radio_id": "",
                        "wlan_id": "",
                        "vlan_id": "",
                    },
                    "field_timestamps": {},
                })
                fields = station["fields"]
                field_timestamps = station["field_timestamps"]
                for field_name in ("ap_name", "radio_id", "wlan_id", "vlan_id"):
                    label_value = index_labels.get(field_name)
                    if label_value is None:
                        continue
                    if last_success >= field_timestamps.get(field_name, float("-inf")):
                        fields[field_name] = _clean_text(
                            label_value, field=field_name, limit=120,
                        )
                        field_timestamps[field_name] = last_success
                series_variant = str(sensor.get("series_variant") or "").lower()
                field_name = {"station_ip": "station_ip", "ssid": "ssid"}.get(series_variant)
                if field_name:
                    raw_value = sensor.get("last_raw_value")
                    if raw_value is not None and last_success >= field_timestamps.get(field_name, float("-inf")):
                        fields[field_name] = _clean_text(
                            raw_value, field=field_name, limit=300,
                        )
                        field_timestamps[field_name] = last_success

        family = _METRIC_FAMILIES.get(measurement_type)
        if family and quality == "good":
            value = _metric_value(sensor.get("last_value"))
            if value is not None:
                sample_labels = dict(base)
                if measurement_type in {"optical_power_dbm", "sensor_value"}:
                    sample_labels["unit"] = sensor.get("unit", "")
                if measurement_type == "wireless_sensor_value":
                    sample_labels["sensor_class"] = _clean_text(
                        metadata.get("wireless_sensor_class"), field="wireless sensor class", limit=64,
                    )
                    sample_labels["unit"] = sensor.get("unit", "")
                if measurement_type == "component_state":
                    raw_state = sensor.get("last_raw_value")
                    state_description = _state_description(raw_state, sensor.get("states"))
                    if state_description:
                        sample_labels["raw_state"] = _clean_text(raw_state, field="raw state", limit=64)
                        sample_labels["state_description"] = state_description
                        presence_value = _presence_metric_value(state_description)
                        if presence_value is not None:
                            add("nexora_hw_component_present", sample_labels, presence_value)
                add(family, sample_labels, value)

    for _station_identity, station in sorted(wireless_station_samples.items()):
        labels = {**station["context"], **station["fields"]}
        station_mac = station["fields"]["station_mac"]
        labels["station_mac"] = station_mac
        add("nexora_wireless_station_info", labels, "1", include_empty=True)

    output: list[str] = []
    for family in sorted(lines_by_family):
        output.append(f"# HELP {family} {_FAMILY_HELP[family]}")
        output.append(f"# TYPE {family} gauge")
        for labels_text, value in sorted(lines_by_family[family]):
            output.append(f"{family}{labels_text} {value}")
    return "\n".join(output) + ("\n" if output else "")


__all__ = [
    "HardwareInventoryError",
    "build_sensor_key",
    "upsert_discovery_run",
    "record_sensor_sample",
    "record_sensor_samples_batch",
    "mark_sensor_poll_success",
    "list_hardware_sensors",
    "list_hardware_metric_rows",
    "list_hardware_discovery_runs",
    "list_hardware_capabilities",
    "render_hardware_metrics",
]
