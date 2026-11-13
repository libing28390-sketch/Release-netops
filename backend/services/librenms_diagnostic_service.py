"""Read-only diagnostics for Nexora's locally collected SNMP hardware inventory."""

from __future__ import annotations

import asyncio
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database import get_db_connection

logger = logging.getLogger(__name__)

_MAX_ROWS = 2000


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _parse_inventory_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        local_zone_name = str(os.getenv("TZ") or "UTC").strip() or "UTC"
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(local_zone_name))
        except ZoneInfoNotFoundError:
            return None
    return parsed.astimezone(timezone.utc)


def _base_result(device: Mapping[str, Any], *, state: str, message: str) -> dict[str, Any]:
    return {
        "source": "nexora_snmp",
        "state": state,
        "message": message,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matched_device_id": str(device.get("id") or ""),
        "matched_hostname": str(device.get("hostname") or device.get("ip_address") or ""),
        # Keep the legacy response shape while making it explicit that local
        # inventory diagnostics have no external instance binding.
        "binding": None,
        "engine": {
            "instance_id": "",
            "name": "Nexora SNMP collector",
            "version": "native",
            "commit": "",
            "health_state": "unknown",
        },
        "identity": {
            "hostname": str(device.get("hostname") or device.get("ip_address") or ""),
            "display": str(device.get("display_name") or device.get("hostname") or ""),
            "os": str(device.get("platform") or ""),
            "version": str(device.get("version") or ""),
            "hardware": str(device.get("model") or ""),
            "sysObjectID": "",
        },
        "collection": {
            "engine_status": "local",
            "sample_status": state,
            "export_status": "unverified",
            "sync_status": "not_applicable",
            "last_discovered": None,
            "last_polled": None,
            "poll_interval_seconds": None,
            "stale_after_seconds": None,
        },
        "capabilities": [],
        "health_graphs": [],
        "hardware_sensors": [],
        "processor_sensors": [],
        "memory_pools": [],
        "transceivers": [],
        "wireless_sensors": [],
        "sensor_count": 0,
        "active_sensor_count": 0,
        "omitted_sensor_count": 0,
        "metric_summary": [],
        "live_poll_status": "not_run",
        "background_snapshot_status": state,
    }


def _local_hardware_snapshot(device: Mapping[str, Any]) -> dict[str, Any]:
    """Build a diagnostic view from Nexora's persisted SNMP hardware inventory."""
    from services.snmp_hardware_inventory_service import (
        list_hardware_capabilities,
        list_hardware_sensors,
    )
    from services.librenms_source_policy import is_trusted_hardware_sensor
    from services.snmp_hardware_poller_service import (
        DISCOVERY_VERSION,
        hardware_stale_after_seconds,
        hardware_sample_interval_seconds,
    )

    device_id = str(device.get("id") or "").strip()
    if not device_id:
        return _base_result(
            device,
            state="unavailable",
            message="A managed device ID is required to read local hardware inventory",
        )

    conn = get_db_connection()
    try:
        sensors = list_hardware_sensors(conn, device_id, include_retired=True)
        capabilities = list_hardware_capabilities(conn, device_id)
    finally:
        conn.close()

    # Show only inventory discovered by the current collector version and
    # validated against the bundled LibreNMS source rules. Older inventory
    # remains stored for history but is not presented as current hardware.
    sensors = [
        sensor for sensor in sensors
        if str((sensor.get("metadata") or {}).get("collection_version") or "") == DISCOVERY_VERSION
        and is_trusted_hardware_sensor(sensor)
    ]
    capabilities = [
        capability for capability in capabilities
        if str(capability.get("discovery_version") or "") == DISCOVERY_VERSION
        and str(capability.get("source_type") or "").casefold() in {
            "librenms_rule", "librenms_os_rule", "librenms_mib_rule", "nexora_snmp",
        }
    ]

    now = datetime.now(timezone.utc)
    poll_interval_seconds = max(1, int(hardware_sample_interval_seconds()))
    stale_after_seconds = max(
        1,
        int(max(
            (hardware_stale_after_seconds(sensor) for sensor in sensors),
            default=hardware_stale_after_seconds({}),
        )),
    )
    normalized: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    latest_success: datetime | None = None

    total_sensor_count = len(sensors)
    for sensor in sensors[:_MAX_ROWS]:
        metadata = sensor.get("metadata") if isinstance(sensor.get("metadata"), Mapping) else {}
        registered_interval = _finite_number(metadata.get("poll_interval_seconds"))
        registered_poll_interval = (
            max(1, min(86400, int(registered_interval)))
            if registered_interval is not None and registered_interval > 0
            else None
        )
        sensor_stale_after_seconds = max(1, int(hardware_stale_after_seconds(sensor)))
        current = _finite_number(sensor.get("last_value"))
        quality = str(sensor.get("last_quality") or "missing").casefold()
        if quality != "good":
            current = None

        sample_at = (
            _parse_inventory_time(sensor.get("last_success"))
            or _parse_inventory_time(sensor.get("last_sample_at"))
        )
        age = max(0.0, (now - sample_at).total_seconds()) if sample_at else None
        freshness = "unknown" if age is None else "stale" if age > sensor_stale_after_seconds else "fresh"
        index = sensor.get("index") if isinstance(sensor.get("index"), (dict, list)) else []
        index_text = ".".join(str(part) for part in index) if isinstance(index, list) else str(index)
        source_type = str(sensor.get("source_type") or "")
        component_class = str(sensor.get("component_class") or "sensor")
        measurement_type = str(sensor.get("measurement_type") or "sensor_value")
        labels = sensor.get("index_labels") if isinstance(sensor.get("index_labels"), Mapping) else {}
        enabled = bool(sensor.get("enabled"))
        lifecycle_status = str(sensor.get("lifecycle_status") or "unknown")
        discovery_status = str(sensor.get("discovery_status") or "unknown")
        active = (
            enabled
            and lifecycle_status.casefold() == "active"
            and discovery_status.casefold() == "present"
        )
        if active and current is not None and sample_at:
            latest_success = max(latest_success, sample_at) if latest_success else sample_at
        source_path = str(metadata.get("source_path") or "")
        source_commit = str(metadata.get("source_commit") or "")
        row = {
            "sensor_id": str(sensor.get("sensor_key") or ""),
            "sensor_class": component_class,
            "device_id": device_id,
            "poller_type": "nexora_snmp",
            "source": source_type,
            "source_type": source_type,
            "source_id": str(sensor.get("source_id") or ""),
            "source_path": source_path,
            "source_commit": source_commit,
            "rule_version": str(sensor.get("rule_version") or ""),
            "data_origin": str(sensor.get("data_origin") or ""),
            "sensor_oid": sensor.get("oid") or "",
            "sensor_index": index_text,
            "sensor_type": measurement_type,
            "sensor_descr": sensor.get("sensor_name") or sensor.get("entity_name") or measurement_type,
            "group": sensor.get("group_name") or component_class,
            "sensor_current": current,
            "raw_value": sensor.get("last_raw_value"),
            "lastupdate": sample_at.isoformat() if sample_at else None,
            "last_sample_at": sensor.get("last_sample_at"),
            "last_success": sensor.get("last_success"),
            "unit": sensor.get("unit") or "",
            "states": sensor.get("states") or {},
            "thresholds": sensor.get("thresholds") or {},
            "quality": quality,
            "last_quality": quality,
            "value_status": "available" if current is not None else "missing",
            "freshness": freshness,
            "sample_age_seconds": round(age, 1) if age is not None else None,
            "observed_at": sample_at.isoformat() if sample_at else None,
            "poll_interval_seconds": poll_interval_seconds,
            "registered_poll_interval_seconds": registered_poll_interval,
            "enabled": enabled,
            "lifecycle_status": lifecycle_status,
            "discovery_status": discovery_status,
            "missing_success_count": int(sensor.get("missing_success_count") or 0),
            "presence_status": str(sensor.get("presence_status") or ""),
            "first_seen": sensor.get("first_seen"),
            "last_seen": sensor.get("last_seen"),
            "index_labels": dict(labels),
            "active": active,
        }
        normalized.append(row)

        group_key = (source_type, component_class)
        bucket = groups.setdefault(group_key, {
            "key": f"{source_type}:{component_class}",
            "source": source_type,
            "source_type": source_type,
            "component_class": component_class,
            "measurement_type": measurement_type,
            "unit": str(sensor.get("unit") or ""),
            "entity_count": 0,
            "enabled_count": 0,
            "active_count": 0,
            "value_count": 0,
            "fresh_count": 0,
            "latest_sample_at": None,
            "poll_interval_seconds": poll_interval_seconds,
            "status": "missing",
        })
        bucket["entity_count"] += 1
        if enabled:
            bucket["enabled_count"] += 1
        if active:
            bucket["active_count"] += 1
        if current is not None and active:
            bucket["value_count"] += 1
        if current is not None and freshness == "fresh" and active:
            bucket["fresh_count"] += 1
        if sample_at and active:
            previous = _parse_inventory_time(bucket["latest_sample_at"])
            if previous is None or sample_at > previous:
                bucket["latest_sample_at"] = sample_at.isoformat()

    for bucket in groups.values():
        if bucket["fresh_count"]:
            bucket["status"] = "available"
        elif bucket["value_count"] and any(
            row["active"]
            and row["source_type"] == bucket["source_type"]
            and row["sensor_class"] == bucket["component_class"]
            and row["freshness"] == "stale"
            for row in normalized
        ):
            bucket["status"] = "stale"
        elif bucket["value_count"]:
            bucket["status"] = "unknown"
        else:
            bucket["status"] = "missing"

    capability_rows: list[dict[str, Any]] = []
    for item in capabilities:
        source_type = str(item.get("source_type") or "")
        source_commit = str(item.get("rule_version") or "")
        source_path = str(item.get("artifact_version") or "")
        capability_rows.append({
            "source_type": source_type,
            "component_class": str(item.get("component_class") or ""),
            "status": str(item.get("last_status") or "unknown"),
            "last_status": str(item.get("last_status") or "unknown"),
            "coverage_complete": bool(item.get("coverage_complete")),
            "active_sensor_count": int(item.get("active_sensor_count") or 0),
            "last_discovered_count": int(item.get("last_discovered_count") or 0),
            "rule_version": source_commit,
            "source_commit": source_commit,
            "discovery_version": str(item.get("discovery_version") or ""),
            "artifact_version": source_path,
            "source_path": source_path,
            "last_attempt_at": item.get("last_attempt_at"),
            "last_success_at": item.get("last_success_at"),
            "reason_code": str(item.get("reason_code") or ""),
            "reason": str(item.get("reason") or ""),
        })

    latest_discovery = max(
        (
            parsed for item in capability_rows
            if (parsed := _parse_inventory_time(item.get("last_attempt_at"))) is not None
        ),
        default=None,
    )
    has_values = any(row["active"] and row["value_status"] == "available" for row in normalized)
    has_active_sensors = any(row["active"] for row in normalized)
    has_failed_discovery = any(
        item["last_status"].casefold() in {"failed", "partial"}
        for item in capability_rows
    )

    if has_values:
        state = "available"
        message = "已读取 Nexora 本地 LibreNMS 规则驱动的 SNMP 硬件库存"
        sample_status = "available"
    elif has_active_sensors:
        state = "metadata_only"
        message = "本地硬件实体已发现，但当前没有质量为 good 的有效数值样本"
        sample_status = "metadata_only"
    elif has_failed_discovery:
        state = "pending"
        message = "本地硬件发现最近失败或未完整完成；后台会按计划重试"
        sample_status = "pending"
    elif normalized:
        state = "metadata_only"
        message = "本地库存中只有已停用或退役的硬件实体"
        sample_status = "metadata_only"
    elif capability_rows:
        state = "no_native_hardware_data"
        message = "本地发现记录未检出可用硬件传感器"
        sample_status = "no_data"
    else:
        state = "pending"
        message = "尚无本地 SNMP 硬件发现记录；此诊断只读取已保存库存，不触发即时采集"
        sample_status = "pending"

    result = _base_result(device, state=state, message=message)
    result.update(
        capabilities=capability_rows,
        hardware_sensors=[
            row for row in normalized
            if row["sensor_class"] not in {"processor", "memory_pool"}
        ],
        processor_sensors=[
            {**row, "processor_usage": row.get("sensor_current"), "processor_descr": row.get("sensor_descr")}
            for row in normalized if row["sensor_class"] == "processor"
        ],
        memory_pools=[
            {**row, "mempool_perc": row.get("sensor_current"), "mempool_descr": row.get("sensor_descr")}
            for row in normalized if row["sensor_class"] == "memory_pool"
        ],
        wireless_sensors=[
            {
                **row,
                "ssid": row["index_labels"].get("ssid"),
                "ap_name": row["index_labels"].get("ap_name"),
            }
            for row in normalized
            if "wireless" in row["sensor_class"].casefold()
            or "wireless" in row["sensor_type"].casefold()
        ],
        sensor_count=len(normalized),
        active_sensor_count=sum(1 for row in normalized if row["active"]),
        omitted_sensor_count=max(0, total_sensor_count - len(normalized)),
        metric_summary=sorted(groups.values(), key=lambda item: item["key"]),
        engine={
            "instance_id": "",
            "name": "Nexora SNMP collector",
            "version": "native",
            "commit": "",
            "health_state": "unknown",
        },
        collection={
            **result["collection"],
            "engine_status": "local",
            "sample_status": sample_status,
            "sync_status": "not_applicable",
            "last_discovered": latest_discovery.isoformat() if latest_discovery else None,
            "last_polled": latest_success.isoformat() if latest_success else None,
            "poll_interval_seconds": poll_interval_seconds,
            "stale_after_seconds": stale_after_seconds,
        },
        background_snapshot_status=sample_status,
    )
    return result


async def diagnose_librenms_hardware(device: Mapping[str, Any]) -> dict[str, Any]:
    """Read Nexora's local hardware inventory; never contacts or binds an instance."""
    try:
        return await asyncio.to_thread(_local_hardware_snapshot, device)
    except Exception as exc:
        logger.warning("Local SNMP hardware snapshot failed: %s", type(exc).__name__)
        result = _base_result(
            device,
            state="unavailable",
            message="Nexora local SNMP hardware inventory is temporarily unavailable",
        )
        result["collection"].update(engine_status="error", sample_status="unavailable")
        result["engine"]["health_state"] = "error"
        result["background_snapshot_status"] = "unavailable"
        return result


__all__ = ["diagnose_librenms_hardware"]
