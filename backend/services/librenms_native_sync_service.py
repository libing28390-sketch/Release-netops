"""Project LibreNMS-native hardware snapshots into the Nexora inventory.

LibreNMS owns device discovery and sampling. This adapter only maps its native
snapshot rows into the existing hardware inventory contract and records the
native timestamps it receives.
"""

from __future__ import annotations

import asyncio
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from core.crypto import decrypt_credential
from database import get_db_connection
from services.librenms_runtime_client import LibreNMSAPIError, LibreNMSRuntimeClient
from services.snmp_hardware_inventory_service import (
    build_sensor_key,
    record_sensor_samples_batch,
    upsert_discovery_run,
)


SOURCE_TYPE = "librenms_native"
DATA_ORIGIN = "librenms_native"
DISCOVERY_VERSION = "librenms-native-snapshot-v1"
_MAX_NATIVE_ROWS = 2000
_READ_SEMAPHORE = asyncio.Semaphore(4)

_TRANSCEIVER_FIELDS = (
    "port_id", "ifName", "ifDescr", "ifIndex", "entity_index", "entPhysicalIndex",
    "vendor", "serial", "part_number", "revision", "date_code",
)
_SENSOR_CLASS_MAP: dict[str, tuple[str, str, str]] = {
    "temp": ("temperature", "temperature_celsius", "celsius"),
    "temperature": ("temperature", "temperature_celsius", "celsius"),
    "fan": ("fan", "fan_speed_rpm", "rpm"),
    "fanspeed": ("fan", "fan_speed_rpm", "rpm"),
    "fan_speed": ("fan", "fan_speed_rpm", "rpm"),
    "voltage": ("voltage", "voltage_volts", "volts"),
    "current": ("current", "current_amperes", "amperes"),
    "power": ("power_measurement", "power_watts", "watts"),
    "power_supply": ("power_measurement", "power_watts", "watts"),
    "dbm": ("optical_power", "optical_power_dbm", "dBm"),
}


def _parse_native_timestamp(value: Any) -> datetime | None:
    """Parse an upstream timestamp without substituting local request time."""
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _primitive(value: Any) -> str | int | float | bool | None:
    """Keep metadata JSON-safe and reject non-finite or driver-specific data."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _metadata(row: Mapping[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {
        field: cleaned
        for field in fields
        if field in row and (cleaned := _primitive(row.get(field))) is not None
    }


def _rows(snapshot: Any, attribute: str) -> list[Mapping[str, Any]]:
    rows = getattr(snapshot, attribute, None)
    if not isinstance(rows, (list, tuple)):
        return []
    return [row for row in rows[:_MAX_NATIVE_ROWS] if isinstance(row, Mapping)]


def _row_identity_index(
    *, instance_id: str, native_device_id: str, row_kind: str, row_id: str,
) -> dict[str, str]:
    return {
        "instance_id": instance_id,
        "native_device_id": native_device_id,
        "row_kind": row_kind,
        "row_id": row_id,
    }


def _base_sensor_record(
    row: Mapping[str, Any],
    *,
    device_id: str,
    instance_id: str,
    native_device_id: str,
    row_kind: str,
    row_id: Any,
    component_class: str,
    measurement_type: str,
    value_field: str | None,
    unit: str,
    metadata_fields: Sequence[str],
    name_field: str,
    oid_field: str = "",
    thresholds: Mapping[str, Any] | None = None,
    index_labels: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    resolved_row_id = "" if row_id is None else str(row_id).strip()
    if not resolved_row_id:
        return None

    native_at = _parse_native_timestamp(row.get("lastupdate"))
    source_value = row.get(value_field) if value_field else None
    numeric_value = _finite_number(source_value) if value_field else None
    raw_value = None if source_value is None else str(source_value)
    if native_at is None:
        # A native value without its own sample timestamp is metadata only.
        numeric_value = None
        raw_value = None
        quality = "missing"
    elif source_value is None:
        quality = "missing"
    elif numeric_value is None:
        quality = "invalid"
    else:
        quality = "good"

    native_entity_id = f"{row_kind}:{resolved_row_id}"
    record = {
        "source_type": SOURCE_TYPE,
        "data_origin": DATA_ORIGIN,
        "native_instance_id": instance_id,
        "native_device_id": native_device_id,
        "native_entity_id": native_entity_id,
        "source_id": native_entity_id,
        "component_class": component_class,
        "measurement_type": measurement_type,
        "series_variant": "unknown" if measurement_type == "cpu_usage_percent" else "",
        "index": _row_identity_index(
            instance_id=instance_id,
            native_device_id=native_device_id,
            row_kind=row_kind,
            row_id=resolved_row_id,
        ),
        "index_labels": dict(index_labels or {}),
        "oid": str(row.get(oid_field) or "") if oid_field else "",
        "unit": unit,
        "scale": 1,
        "offset": 0,
        "thresholds": dict(thresholds or {}),
        "metadata": _metadata(row, metadata_fields),
        "sensor_name": str(row.get(name_field) or resolved_row_id),
        "entity_name": str(row.get(name_field) or ""),
        "group_name": str(row.get("group") or ""),
        "value": numeric_value,
        "raw_value": raw_value,
        "quality": quality,
        "sample_at": native_at,
        "device_id": device_id,
    }
    return record


def _standard_sensor_record(
    row: Mapping[str, Any], *, device_id: str, instance_id: str, native_device_id: str,
) -> tuple[dict[str, Any] | None, str]:
    raw_class = str(row.get("sensor_class") or "unknown").strip().casefold() or "unknown"
    mapped = _SENSOR_CLASS_MAP.get(raw_class)
    if mapped:
        component_class, measurement_type, unit = mapped
    else:
        component_class, measurement_type = raw_class, "sensor_value"
        native_unit = next(
            (row.get(field) for field in ("sensor_unit", "sensor_units", "unit", "units") if row.get(field) is not None),
            "",
        )
        unit = str(native_unit or "")[:100]

    thresholds: dict[str, Any] = {}
    for key, raw_value in {
        "limit": row.get("sensor_limit"),
        "limit_warn": row.get("sensor_limit_warn"),
        "limit_low": row.get("sensor_limit_low"),
        "limit_low_warn": row.get("sensor_limit_low_warn"),
        "alert": row.get("sensor_alert"),
    }.items():
        value = _primitive(raw_value)
        if value is not None:
            thresholds[key] = value
    metadata_fields = (
        "sensor_class", "sensor_type", "sensor_index", "poller_type", "entPhysicalIndex",
        "entPhysicalIndex_measured",
    )
    record = _base_sensor_record(
        row,
        device_id=device_id,
        instance_id=instance_id,
        native_device_id=native_device_id,
        row_kind="sensor",
        row_id=row.get("sensor_id"),
        component_class=component_class,
        measurement_type=measurement_type,
        value_field="sensor_current",
        unit=unit,
        metadata_fields=metadata_fields,
        name_field="sensor_descr",
        oid_field="sensor_oid",
        thresholds=thresholds,
        index_labels={
            field: _primitive(row.get(field))
            for field in ("sensor_index", "entPhysicalIndex", "entPhysicalIndex_measured")
            if _primitive(row.get(field)) is not None
        },
    )
    return record, component_class


def _health_sensor_record(
    row: Mapping[str, Any],
    *,
    device_id: str,
    instance_id: str,
    native_device_id: str,
    row_kind: str,
    row_id_field: str,
    component_class: str,
    measurement_type: str,
    value_field: str,
    name_field: str,
    metadata_fields: Sequence[str],
    threshold_field: str,
) -> dict[str, Any] | None:
    warning = _primitive(row.get(threshold_field))
    thresholds = {threshold_field: warning} if warning is not None else {}
    index_labels = {
        field: _primitive(row.get(field))
        for field in ("processor_index", "mempool_index", "entPhysicalIndex", "hrDeviceIndex")
        if _primitive(row.get(field)) is not None
    }
    return _base_sensor_record(
        row,
        device_id=device_id,
        instance_id=instance_id,
        native_device_id=native_device_id,
        row_kind=row_kind,
        row_id=(
            row.get(row_id_field)
            if row.get(row_id_field) not in (None, "")
            else row.get("sensor_id")
        ),
        component_class=component_class,
        measurement_type=measurement_type,
        value_field=value_field,
        unit="%",
        metadata_fields=metadata_fields,
        name_field=name_field,
        oid_field="processor_oid" if row_kind == "processor" else "",
        thresholds=thresholds,
        index_labels=index_labels,
    )


def _wireless_sensor_record(
    row: Mapping[str, Any], *, device_id: str, instance_id: str, native_device_id: str,
) -> dict[str, Any] | None:
    native_class = str(row.get("sensor_class") or "unknown").strip().casefold() or "unknown"
    native_unit = next(
        (row.get(field) for field in ("sensor_unit", "sensor_units", "unit", "units") if row.get(field) is not None),
        "",
    )
    labels = {
        field: _primitive(row.get(field))
        for field in (
            "sensor_index", "radio_number", "ssid", "bssid", "ap_name", "ap_id",
            "access_point_id",
        )
        if _primitive(row.get(field)) is not None
    }
    record = _base_sensor_record(
        row,
        device_id=device_id,
        instance_id=instance_id,
        native_device_id=native_device_id,
        row_kind="wireless_sensor",
        row_id=row.get("sensor_id"),
        component_class="wireless_sensor",
        measurement_type="wireless_sensor_value",
        value_field="sensor_current",
        unit=str(native_unit or "")[:100],
        metadata_fields=(
            "sensor_class", "sensor_type", "sensor_index", "radio_number", "ssid", "bssid",
            "ap_name", "ap_id", "access_point_id",
        ),
        name_field="sensor_descr",
        index_labels=labels,
    )
    if record is not None:
        record["metadata"]["wireless_sensor_class"] = native_class
    return record


def _transceiver_record(
    row: Mapping[str, Any], *, device_id: str, instance_id: str, native_device_id: str,
) -> dict[str, Any] | None:
    row_id = next(
        (row.get(field) for field in ("port_id", "ifIndex", "entity_index", "entPhysicalIndex") if row.get(field) is not None),
        None,
    )
    labels = {
        field: _primitive(row.get(field))
        for field in ("ifName", "ifDescr", "ifIndex", "entity_index", "entPhysicalIndex")
        if _primitive(row.get(field)) is not None
    }
    return _base_sensor_record(
        row,
        device_id=device_id,
        instance_id=instance_id,
        native_device_id=native_device_id,
        row_kind="transceiver",
        row_id=row_id,
        component_class="transceiver",
        measurement_type="sensor_value",
        value_field=None,
        unit="",
        metadata_fields=_TRANSCEIVER_FIELDS,
        name_field="ifName",
        index_labels=labels,
    )


def snapshot_to_inventory_records(
    snapshot: Any,
    *,
    device_id: str,
    instance_id: str,
    native_device_id: str,
    existing_component_classes: Iterable[str] = (),
) -> dict[str, Any]:
    """Convert a native snapshot into inventory records without reading time.

    Descriptions and other display fields are retained as labels only. The
    sensor index contains the complete native row identity so same-named rows
    in different instances, devices, or row families remain independent.
    """
    resolved_device_id = str(device_id or "").strip()
    resolved_instance_id = str(instance_id or "").strip()
    resolved_native_device_id = str(native_device_id or "").strip()
    if not all((resolved_device_id, resolved_instance_id, resolved_native_device_id)):
        raise ValueError("device and native instance identities are required")

    native_device = getattr(snapshot, "device", {})
    if not isinstance(native_device, Mapping):
        native_device = {}
    poll_interval = _finite_number(
        native_device.get("poller_interval") or native_device.get("poller_seconds")
    ) or 300
    poll_interval_seconds = max(1, min(86400, int(poll_interval)))

    sensors: list[dict[str, Any]] = []
    row_counts: dict[str, int] = {}
    omitted_by_class: dict[str, int] = {}

    def add(record: dict[str, Any] | None, component_class: str) -> None:
        row_counts[component_class] = row_counts.get(component_class, 0) + 1
        if record is None:
            omitted_by_class[component_class] = omitted_by_class.get(component_class, 0) + 1
        else:
            sensors.append(record)

    for row in _rows(snapshot, "sensors"):
        record, component_class = _standard_sensor_record(
            row,
            device_id=resolved_device_id,
            instance_id=resolved_instance_id,
            native_device_id=resolved_native_device_id,
        )
        add(record, component_class)

    for row in _rows(snapshot, "processor_sensors"):
        record = _health_sensor_record(
            row,
            device_id=resolved_device_id,
            instance_id=resolved_instance_id,
            native_device_id=resolved_native_device_id,
            row_kind="processor",
            row_id_field="processor_id",
            component_class="processor",
            measurement_type="cpu_usage_percent",
            value_field="processor_usage",
            name_field="processor_descr",
            metadata_fields=(
                "processor_type", "processor_index", "processor_precision", "entPhysicalIndex",
                "hrDeviceIndex",
            ),
            threshold_field="processor_perc_warn",
        )
        add(record, "processor")

    for row in _rows(snapshot, "memory_pools"):
        record = _health_sensor_record(
            row,
            device_id=resolved_device_id,
            instance_id=resolved_instance_id,
            native_device_id=resolved_native_device_id,
            row_kind="memory_pool",
            row_id_field="mempool_id",
            component_class="memory_pool",
            measurement_type="memory_usage_percent",
            value_field="mempool_perc",
            name_field="mempool_descr",
            metadata_fields=(
                "mempool_index", "mempool_type", "mempool_class", "mempool_precision",
                "entPhysicalIndex",
            ),
            threshold_field="mempool_perc_warn",
        )
        add(record, "memory_pool")

    for row in _rows(snapshot, "wireless_sensors"):
        add(
            _wireless_sensor_record(
                row,
                device_id=resolved_device_id,
                instance_id=resolved_instance_id,
                native_device_id=resolved_native_device_id,
            ),
            "wireless_sensor",
        )

    for row in _rows(snapshot, "transceivers"):
        add(
            _transceiver_record(
                row,
                device_id=resolved_device_id,
                instance_id=resolved_instance_id,
                native_device_id=resolved_native_device_id,
            ),
            "transceiver",
        )

    # A duplicate native ID is malformed upstream data. Keep the most recent
    # timestamp deterministically so the inventory's stable key remains unique.
    by_sensor_key: dict[str, dict[str, Any]] = {}
    for sensor in sensors:
        key = build_sensor_key(
            sensor["source_type"], sensor["component_class"], sensor["measurement_type"],
            sensor["index"], sensor.get("series_variant", ""),
        )
        previous = by_sensor_key.get(key)
        if previous is None or (
            sensor["sample_at"] is not None
            and (previous["sample_at"] is None or sensor["sample_at"] >= previous["sample_at"])
        ):
            by_sensor_key[key] = sensor
    sensors = list(by_sensor_key.values())
    for sensor in sensors:
        metadata = sensor.get("metadata")
        if isinstance(metadata, dict):
            metadata["poll_interval_seconds"] = poll_interval_seconds

    observed_classes = set(row_counts) | {
        str(item).strip().casefold()
        for item in existing_component_classes
        if str(item).strip()
    }
    if not observed_classes:
        observed_classes.add("native_snapshot")

    category_results: list[dict[str, Any]] = []
    sensors_by_class: dict[str, int] = {}
    for sensor in sensors:
        component_class = sensor["component_class"]
        sensors_by_class[component_class] = sensors_by_class.get(component_class, 0) + 1
    for component_class in sorted(observed_classes):
        omitted = omitted_by_class.get(component_class, 0)
        if omitted:
            status, coverage_complete = "partial", False
            reason_code = "native_row_identity_missing"
            reason = "Some native rows had no stable row identifier and were skipped."
        elif row_counts.get(component_class, 0) or sensors_by_class.get(component_class, 0):
            status, coverage_complete = "success", True
            reason_code, reason = "", ""
        else:
            status, coverage_complete = "not_found", True
            reason_code, reason = "native_category_empty", "LibreNMS returned no native rows in this category."
        category_results.append({
            "source_type": SOURCE_TYPE,
            "component_class": component_class,
            "status": status,
            "coverage_complete": coverage_complete,
            "reason_code": reason_code,
            "reason": reason,
        })

    sample_rows = [
        {
            "device_id": sensor["device_id"],
            "sensor_key": build_sensor_key(
                sensor["source_type"], sensor["component_class"], sensor["measurement_type"],
                sensor["index"], sensor.get("series_variant", ""),
            ),
            "value": sensor["value"],
            "raw_value": sensor["raw_value"],
            "quality": sensor["quality"],
            "observed_at": sensor["sample_at"],
        }
        for sensor in sensors
        if sensor["sample_at"] is not None
    ]
    return {
        "sensors": sensors,
        "category_results": category_results,
        "sample_rows": sample_rows,
        "native_last_polled": _parse_native_timestamp(native_device.get("last_polled")),
        "native_last_discovered": _parse_native_timestamp(native_device.get("last_discovered")),
        "omitted_row_count": sum(omitted_by_class.values()),
    }


def _binding_rows(device_id: str) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT b.id AS binding_id, b.tenant_id, b.asset_id, b.device_id,
                   b.instance_id, b.librenms_device_id, b.sync_status,
                   b.last_sync_at, b.last_discovery_at, b.last_poll_at,
                   i.base_url, i.enabled AS instance_enabled,
                   i.engine_version, i.engine_commit,
                   i.token_credential_id, c.credential_type, c.encrypted_password
              FROM librenms_device_bindings AS b
              JOIN librenms_instances AS i ON i.id = b.instance_id
              LEFT JOIN credentials AS c ON c.id = i.token_credential_id
             WHERE b.device_id = ?
               AND b.desired_state = 'enabled'
               AND i.enabled = TRUE
             ORDER BY b.updated_at DESC
             LIMIT 2
            """,
            (device_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _inventory_state(device_id: str, instance_id: str, native_device_id: str) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        sample_row = conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM snmp_hardware_sensors
                 WHERE device_id = ? AND data_origin = 'librenms_native'
                   AND native_instance_id = ? AND native_device_id = ?
                   AND last_sample_at IS NOT NULL
                   AND lifecycle_status <> 'retired'
            ) AS has_sample
            """,
            (device_id, instance_id, native_device_id),
        ).fetchone()
        class_rows = conn.execute(
            """
            SELECT DISTINCT component_class
              FROM snmp_hardware_sensors
             WHERE device_id = ? AND data_origin = 'librenms_native'
               AND lifecycle_status <> 'retired'
            """,
            (device_id,),
        ).fetchall()
        has_sample = bool(sample_row["has_sample"] if isinstance(sample_row, Mapping) else sample_row[0])
        classes = {
            str(row["component_class"] if isinstance(row, Mapping) else row[0]).strip().casefold()
            for row in class_rows
            if str(row["component_class"] if isinstance(row, Mapping) else row[0]).strip()
        }
        return {"has_sample": has_sample, "component_classes": classes}
    finally:
        conn.close()


def _lock_enabled_binding(conn, binding_id: str) -> bool:
    row = conn.execute(
        """
        SELECT b.id, b.desired_state, i.enabled AS instance_enabled
          FROM librenms_device_bindings AS b
          JOIN librenms_instances AS i ON i.id = b.instance_id
         WHERE b.id = ?
         FOR UPDATE OF b, i
        """,
        (binding_id,),
    ).fetchone()
    if row is None:
        return False
    desired = row["desired_state"] if isinstance(row, Mapping) else row[1]
    instance_enabled = row["instance_enabled"] if isinstance(row, Mapping) else row[2]
    return str(desired or "").casefold() == "enabled" and bool(instance_enabled)


def _mark_failed(binding_id: str, error_code: str) -> None:
    conn = get_db_connection()
    now = datetime.now(timezone.utc)
    try:
        if not _lock_enabled_binding(conn, binding_id):
            conn.rollback()
            return
        conn.execute(
            """
            UPDATE librenms_device_bindings
               SET sync_status = 'failed', last_sync_at = ?,
                   last_error_code = ?, last_error_text = '', updated_at = ?
             WHERE id = ?
            """,
            (now, error_code, now, binding_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _mark_unchanged(binding_id: str) -> bool:
    conn = get_db_connection()
    now = datetime.now(timezone.utc)
    try:
        if not _lock_enabled_binding(conn, binding_id):
            conn.rollback()
            return False
        conn.execute(
            """
            UPDATE librenms_device_bindings
               SET sync_status = 'synced', last_sync_at = ?,
                   last_error_code = '', last_error_text = '', updated_at = ?
             WHERE id = ?
            """,
            (now, now, binding_id),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _persist_snapshot(
    *,
    binding: Mapping[str, Any],
    converted: Mapping[str, Any],
    started_at: datetime,
) -> dict[str, Any] | None:
    conn = get_db_connection()
    finished_at = datetime.now(timezone.utc)
    try:
        binding_id = str(binding["binding_id"])
        if not _lock_enabled_binding(conn, binding_id):
            conn.rollback()
            return None

        inventory_outcome = upsert_discovery_run(
            conn,
            device_id=str(binding["device_id"]),
            run_id=str(uuid.uuid4()),
            rule_version=DISCOVERY_VERSION,
            sensors=converted["sensors"],
            category_results=converted["category_results"],
            observed_at=finished_at,
            started_at=started_at,
            discovery_version=DISCOVERY_VERSION,
            artifact_version=str(binding.get("engine_version") or ""),
        )
        updated_sample_count = record_sensor_samples_batch(conn, converted["sample_rows"])

        native_discovery_at = converted.get("native_last_discovered")
        native_poll_at = converted.get("native_last_polled")
        conn.execute(
            """
            UPDATE librenms_device_bindings
               SET sync_status = 'synced', last_sync_at = ?,
                   last_discovery_at = CASE
                       WHEN CAST(? AS TIMESTAMPTZ) IS NULL THEN last_discovery_at
                       ELSE GREATEST(COALESCE(last_discovery_at, ?), ?)
                   END,
                   last_poll_at = CASE
                       WHEN CAST(? AS TIMESTAMPTZ) IS NULL THEN last_poll_at
                       ELSE GREATEST(COALESCE(last_poll_at, ?), ?)
                   END,
                   last_error_code = '', last_error_text = '', updated_at = ?
             WHERE id = ?
            """,
            (
                finished_at,
                native_discovery_at, native_discovery_at, native_discovery_at,
                native_poll_at, native_poll_at, native_poll_at,
                finished_at, binding_id,
            ),
        )
        conn.commit()
        return {
            "inventory": inventory_outcome,
            "updated_sample_count": int(updated_sample_count or 0),
            "synced_at": finished_at,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _error_code(exc: BaseException) -> str:
    code = exc.code if isinstance(exc, LibreNMSAPIError) else "sync_error"
    safe_code = re.sub(r"[^a-z0-9_]+", "_", str(code or "").casefold()).strip("_")
    return safe_code[:80] or "sync_error"


async def _fail(binding_id: str, exc: BaseException) -> dict[str, Any]:
    error_code = _error_code(exc)
    try:
        await asyncio.to_thread(_mark_failed, binding_id, error_code)
    except Exception:
        # Do not include database exception text, which may contain connection data.
        pass
    return {"status": "failed", "error_code": error_code, "sensor_count": 0, "sample_count": 0}


async def sync_bound_device_hardware(device_id: str) -> dict[str, Any]:
    """Sync one enabled Nexora binding from its LibreNMS native snapshot."""
    resolved_device_id = str(device_id or "").strip()
    if not resolved_device_id:
        return {"status": "failed", "error_code": "invalid_device_id", "sensor_count": 0, "sample_count": 0}

    try:
        bindings = await asyncio.to_thread(_binding_rows, resolved_device_id)
    except Exception as exc:
        return {"status": "failed", "error_code": _error_code(exc), "sensor_count": 0, "sample_count": 0}
    if not bindings:
        return {"status": "not_enabled", "sensor_count": 0, "sample_count": 0}
    if len(bindings) != 1:
        return {"status": "binding_conflict", "sensor_count": 0, "sample_count": 0}

    binding = bindings[0]
    binding_id = str(binding.get("binding_id") or "")
    native_device_id = str(binding.get("librenms_device_id") or "").strip()
    instance_id = str(binding.get("instance_id") or "").strip()
    if not binding_id or not native_device_id or not instance_id:
        return await _fail(binding_id, LibreNMSAPIError("native_binding_incomplete")) if binding_id else {
            "status": "failed", "error_code": "native_binding_incomplete", "sensor_count": 0, "sample_count": 0,
        }
    if str(binding.get("credential_type") or "").casefold() != "api_token":
        return await _fail(binding_id, LibreNMSAPIError("credential_unavailable"))

    try:
        token = await asyncio.to_thread(
            lambda: decrypt_credential(str(binding.get("encrypted_password") or "")) or ""
        )
    except Exception:
        return await _fail(binding_id, LibreNMSAPIError("credential_unavailable"))
    if not token:
        return await _fail(binding_id, LibreNMSAPIError("credential_unavailable"))

    started_at = datetime.now(timezone.utc)
    try:
        async with _READ_SEMAPHORE:
            async with LibreNMSRuntimeClient(str(binding.get("base_url") or ""), str(token)) as client:
                native_device = await client.get_device(native_device_id)
                if not native_device:
                    raise LibreNMSAPIError("native_device_not_found", http_status=404)
                returned_id = str(native_device.get("device_id") or native_device_id)
                if returned_id != native_device_id:
                    raise LibreNMSAPIError("native_device_mismatch")

                native_last_polled = _parse_native_timestamp(native_device.get("last_polled"))
                binding_last_polled = _parse_native_timestamp(binding.get("last_poll_at"))
                native_identity = await asyncio.to_thread(
                    _inventory_state, resolved_device_id, instance_id, native_device_id,
                )
                if (
                    native_last_polled is not None
                    and binding_last_polled is not None
                    and native_last_polled == binding_last_polled
                    and native_identity["has_sample"]
                ):
                    unchanged = await asyncio.to_thread(_mark_unchanged, binding_id)
                    if not unchanged:
                        return {"status": "not_enabled", "sensor_count": 0, "sample_count": 0}
                    return {
                        "status": "unchanged",
                        "native_last_polled": native_last_polled.isoformat(),
                        "sensor_count": 0,
                        "sample_count": 0,
                    }

                snapshot = await client.read_device_snapshot(native_device_id)
    except Exception as exc:
        return await _fail(binding_id, exc)

    snapshot_device = getattr(snapshot, "device", {})
    if not isinstance(snapshot_device, Mapping):
        snapshot_device = {}
    snapshot_native_id = str(snapshot_device.get("device_id") or native_device_id)
    if snapshot_native_id != native_device_id:
        return await _fail(binding_id, LibreNMSAPIError("native_device_mismatch"))

    try:
        converted = snapshot_to_inventory_records(
            snapshot,
            device_id=resolved_device_id,
            instance_id=instance_id,
            native_device_id=native_device_id,
            existing_component_classes=native_identity["component_classes"],
        )
        persisted = await asyncio.to_thread(
            _persist_snapshot,
            binding=binding,
            converted=converted,
            started_at=started_at,
        )
        if persisted is None:
            return {"status": "not_enabled", "sensor_count": 0, "sample_count": 0}
    except Exception as exc:
        return await _fail(binding_id, exc)

    return {
        "status": "synced",
        "sensor_count": len(converted["sensors"]),
        "sample_count": len(converted["sample_rows"]),
        "updated_sample_count": persisted["updated_sample_count"],
        "omitted_row_count": converted["omitted_row_count"],
        "native_last_polled": (
            converted["native_last_polled"].isoformat()
            if converted["native_last_polled"] is not None else None
        ),
        "discovery": persisted["inventory"],
    }


__all__ = ["snapshot_to_inventory_records", "sync_bound_device_hardware"]
