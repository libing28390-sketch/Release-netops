"""Read-only, tenant-scoped diagnostics for LibreNMS-native hardware results.

This service never opens an SNMP session. It resolves one explicit Nexora
binding, calls the bound LibreNMS API, and exposes only an allowlisted subset of
the native response. LibreNMS remains responsible for discovery and polling.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.crypto import decrypt_credential
from database import get_db_connection
from services.librenms_runtime_client import (
    LibreNMSAPIError,
    LibreNMSRuntimeClient,
)

logger = logging.getLogger(__name__)

_DEVICE_FIELDS = (
    "device_id", "hostname", "display", "os", "version", "hardware", "sysObjectID",
    "last_discovered", "last_polled", "poller_group", "status", "disabled", "ignore",
)
_SENSOR_FIELDS = (
    "sensor_id", "sensor_class", "device_id", "poller_type", "sensor_oid", "sensor_index",
    "sensor_type", "sensor_descr", "group", "sensor_current", "sensor_limit",
    "sensor_limit_warn", "sensor_limit_low", "sensor_limit_low_warn", "sensor_alert",
    "entPhysicalIndex", "entPhysicalIndex_measured", "lastupdate",
)
_WIRELESS_FIELDS = (
    "sensor_id", "device_id", "sensor_class", "sensor_index", "sensor_descr", "sensor_current",
    "sensor_prev", "lastupdate", "radio_number", "ssid", "bssid", "ap_name", "ap_id",
)
_TRANSCEIVER_FIELDS = (
    "port_id", "ifName", "ifDescr", "ifIndex", "entity_index", "entPhysicalIndex",
    "vendor", "serial", "part_number", "revision", "date_code",
)
_PROCESSOR_FIELDS = (
    "processor_id", "device_id", "processor_type", "processor_usage", "processor_oid",
    "processor_index", "processor_descr", "processor_precision", "processor_perc_warn",
    "entPhysicalIndex", "hrDeviceIndex", "lastupdate", "unit",
)
_MEMORY_POOL_FIELDS = (
    "mempool_id", "device_id", "mempool_index", "mempool_type", "mempool_class",
    "mempool_precision", "mempool_descr", "mempool_perc", "mempool_used", "mempool_free",
    "mempool_total", "mempool_largestfree", "mempool_lowestfree", "mempool_perc_warn",
    "entPhysicalIndex", "lastupdate", "unit",
)
_NUMERIC_FIELDS = {
    "sensor_current", "sensor_limit", "sensor_limit_warn", "sensor_limit_low",
    "sensor_limit_low_warn", "sensor_alert", "sensor_prev",
}
_MAX_ROWS = 2000


def _safe_row(row: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: row.get(field) for field in fields if field in row}


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _parse_native_time(value: Any) -> datetime | None:
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


def _binding_for_device(device: Mapping[str, Any]) -> dict[str, Any] | None:
    device_id = str(device.get("id") or "").strip()
    if not device_id:
        return None

    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            WITH target AS (
                SELECT d.id, d.asset_id,
                       COALESCE(NULLIF(d.tenant_id, ''), NULLIF(s.tenant_id, ''), 'tenant-default') AS tenant_id
                  FROM devices d
                  LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                  LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
                 WHERE d.id = ?
            )
            SELECT b.id AS binding_id, b.tenant_id, b.asset_id, b.device_id,
                   b.instance_id, b.librenms_device_id, b.librenms_hostname,
                   b.collector_id, b.poller_group, b.desired_state, b.sync_status,
                   b.last_sync_at, b.last_discovery_at, b.last_poll_at,
                   b.last_error_code,
                   i.display_name AS instance_name, i.base_url, i.enabled AS instance_enabled,
                   i.engine_version, i.engine_commit, i.health_state AS instance_health_state,
                   i.token_credential_id, c.credential_type, c.encrypted_password
              FROM librenms_device_bindings b
              JOIN librenms_instances i ON i.id = b.instance_id
              LEFT JOIN credentials c ON c.id = i.token_credential_id
              JOIN target t ON t.id = b.device_id
             WHERE b.tenant_id = t.tenant_id AND b.asset_id = t.asset_id
             ORDER BY b.updated_at DESC
             LIMIT 2
            """,
            (device_id,),
        ).fetchall()
        if len(rows) != 1:
            if len(rows) > 1:
                return {"binding_conflict": True}
            stale = conn.execute(
                "SELECT id FROM librenms_device_bindings WHERE device_id = ? LIMIT 1",
                (device_id,),
            ).fetchone()
            return {"binding_conflict": True} if stale else None
        return dict(rows[0])
    finally:
        conn.close()


def _base_result(device: Mapping[str, Any], *, state: str, message: str) -> dict[str, Any]:
    return {
        "source": "librenms_native",
        "state": state,
        "message": message,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matched_device_id": str(device.get("id") or ""),
        "matched_hostname": str(device.get("hostname") or device.get("ip_address") or ""),
        "binding": None,
        "engine": None,
        "identity": {},
        "collection": {
            "engine_status": "unknown",
            "sample_status": "unknown",
            "export_status": "unverified",
            "sync_status": "unknown",
            "last_discovered": None,
            "last_polled": None,
            "stale_after_seconds": None,
        },
        "health_graphs": [],
        "hardware_sensors": [],
        "processor_sensors": [],
        "memory_pools": [],
        "transceivers": [],
        "wireless_sensors": [],
        "sensor_count": 0,
        "metric_summary": [],
        "live_poll_status": "not_run",
        "background_snapshot_status": state,
    }


def _public_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(binding.get("binding_id") or ""),
        "instance_id": str(binding.get("instance_id") or ""),
        "instance_name": str(binding.get("instance_name") or ""),
        "native_device_id": str(binding.get("librenms_device_id") or ""),
        "native_hostname": str(binding.get("librenms_hostname") or ""),
        "collector_id": str(binding.get("collector_id") or ""),
        "poller_group": str(binding.get("poller_group") or ""),
        "desired_state": str(binding.get("desired_state") or ""),
        "sync_status": str(binding.get("sync_status") or ""),
        "last_sync_at": binding.get("last_sync_at"),
        "last_discovery_at": binding.get("last_discovery_at"),
        "last_poll_at": binding.get("last_poll_at"),
        "last_error_code": str(binding.get("last_error_code") or ""),
    }


def _summarize_sensor_rows(
    rows: list[dict[str, Any]], *, observed_at: datetime, stale_after_seconds: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized: list[dict[str, Any]] = []
    buckets: dict[str, dict[str, Any]] = {}
    for raw_row in rows[:_MAX_ROWS]:
        sensor = _safe_row(raw_row, _SENSOR_FIELDS)
        current = _finite_number(sensor.get("sensor_current"))
        if "sensor_current" in sensor:
            sensor["sensor_current"] = current
        native_at = _parse_native_time(sensor.get("lastupdate"))
        age_seconds = max(0.0, (observed_at - native_at).total_seconds()) if native_at else None
        freshness = "unknown" if age_seconds is None else "stale" if age_seconds > stale_after_seconds else "fresh"
        sensor.update(
            data_origin="librenms_native",
            value_status="available" if current is not None else "missing",
            freshness=freshness,
            sample_age_seconds=round(age_seconds, 1) if age_seconds is not None else None,
            observed_at=native_at.isoformat() if native_at else None,
        )
        normalized.append(sensor)

        category = str(sensor.get("sensor_class") or "unknown").strip().casefold() or "unknown"
        bucket = buckets.setdefault(category, {
            "key": category,
            "measurement_type": category,
            "unit": "",
            "source": "librenms_native",
            "entity_count": 0,
            "value_count": 0,
            "fresh_count": 0,
            "latest_sample_at": None,
            "status": "missing",
        })
        bucket["entity_count"] += 1
        if current is not None:
            bucket["value_count"] += 1
            if freshness == "fresh":
                bucket["fresh_count"] += 1
            if native_at:
                latest = _parse_native_time(bucket["latest_sample_at"])
                if latest is None or native_at > latest:
                    bucket["latest_sample_at"] = native_at.isoformat()
    for bucket in buckets.values():
        if bucket["fresh_count"]:
            bucket["status"] = "available"
        elif any(
            sensor["freshness"] == "stale"
            for sensor in normalized
            if str(sensor.get("sensor_class") or "unknown").strip().casefold() == bucket["key"]
        ):
            bucket["status"] = "stale"
        elif bucket["value_count"]:
            bucket["status"] = "unknown"
        else:
            bucket["status"] = "missing"
    return normalized, sorted(buckets.values(), key=lambda item: item["key"])


def _normalize_native_health_rows(
    rows: list[dict[str, Any]],
    *,
    health_type: str,
    observed_at: datetime,
    stale_after_seconds: int,
) -> list[dict[str, Any]]:
    """Normalize LibreNMS processor/mempool rows without inventing units.

    The API has no per-row timestamp for these tables in current LibreNMS
    versions. When it does return a native ``lastupdate``, it is preserved;
    otherwise freshness remains unknown rather than borrowing request time or
    the device's independent polling metadata.
    """
    normalized: list[dict[str, Any]] = []
    is_processor = health_type == "processor"
    fields = _PROCESSOR_FIELDS if is_processor else _MEMORY_POOL_FIELDS
    value_field = "processor_usage" if is_processor else "mempool_perc"
    id_field = "processor_id" if is_processor else "mempool_id"
    descr_field = "processor_descr" if is_processor else "mempool_descr"

    for raw_row in rows[:_MAX_ROWS]:
        row = _safe_row(raw_row, fields)
        current = _finite_number(raw_row.get(value_field))
        if current is None:
            current = _finite_number(raw_row.get("sensor_current"))
        native_at = _parse_native_time(raw_row.get("lastupdate"))
        age_seconds = max(0.0, (observed_at - native_at).total_seconds()) if native_at else None
        freshness = "unknown" if age_seconds is None else "stale" if age_seconds > stale_after_seconds else "fresh"
        native_unit = raw_row.get("unit")
        row.update(
            sensor_id=raw_row.get(id_field, raw_row.get("sensor_id")),
            sensor_descr=raw_row.get(descr_field, raw_row.get("sensor_descr")),
            sensor_class=health_type,
            sensor_current=current,
            unit=native_unit if isinstance(native_unit, str) and native_unit.strip() else None,
            lastupdate=raw_row.get("lastupdate"),
            data_origin="librenms_native",
            value_status="available" if current is not None else "missing",
            freshness=freshness,
            sample_age_seconds=round(age_seconds, 1) if age_seconds is not None else None,
            observed_at=native_at.isoformat() if native_at else None,
        )
        normalized.append(row)
    return normalized


def _summarize_health_rows(
    rows: list[dict[str, Any]],
    *,
    key: str,
) -> dict[str, Any]:
    value_rows = [row for row in rows if row.get("value_status") == "available"]
    fresh_count = sum(1 for row in value_rows if row.get("freshness") == "fresh")
    stale_count = sum(1 for row in value_rows if row.get("freshness") == "stale")
    latest = max(
        (parsed for row in rows if (parsed := _parse_native_time(row.get("lastupdate"))) is not None),
        default=None,
    )
    status = "available" if fresh_count else "stale" if stale_count else "unknown" if value_rows else "missing"
    unit = next((row.get("unit") for row in rows if row.get("unit")), "")
    return {
        "key": key,
        "measurement_type": key,
        "unit": unit,
        "source": "librenms_native",
        "entity_count": len(rows),
        "value_count": len(value_rows),
        "fresh_count": fresh_count,
        "latest_sample_at": latest.isoformat() if latest else None,
        "status": status,
    }


async def diagnose_librenms_hardware(device: Mapping[str, Any]) -> dict[str, Any]:
    """Return the latest allowlisted native snapshot for one authorized device."""
    result = _base_result(device, state="not_bound", message="该设备尚未绑定 LibreNMS 原生实例")
    try:
        binding = _binding_for_device(device)
    except Exception as exc:
        logger.warning("LibreNMS binding lookup failed: %s", type(exc).__name__)
        result.update(state="unavailable", message="LibreNMS 绑定信息暂不可用")
        result["collection"]["sync_status"] = "unavailable"
        return result

    binding_resolution: dict[str, Any] | None = None
    if binding is None:
        try:
            from services.librenms_binding_service import auto_bind_device_by_management_ip

            binding_resolution = await auto_bind_device_by_management_ip(device)
        except Exception as exc:
            logger.warning("LibreNMS auto-binding failed: %s", type(exc).__name__)
            binding_resolution = {
                "status": "lookup_unavailable",
                "message": "无法自动确认 LibreNMS 设备关联，请检查实例配置或使用管理员手动关联",
            }
        result["binding_resolution"] = {"status": binding_resolution.get("status")}
        if binding_resolution.get("status") not in {"bound", "already_bound"}:
            result.update(
                state="not_bound",
                message=str(binding_resolution.get("message") or "未能自动关联到唯一的 LibreNMS 原生设备"),
            )
            return result
        try:
            binding = _binding_for_device(device)
        except Exception as exc:
            logger.warning("LibreNMS binding reload failed: %s", type(exc).__name__)
            binding = None
        if binding is None:
            result.update(state="unavailable", message="自动关联已完成，但本地绑定暂不可读取")
            result["collection"]["sync_status"] = "unavailable"
            return result
    if binding.get("binding_conflict"):
        result.update(state="binding_conflict", message="该设备存在多个 LibreNMS 绑定，需要先修正绑定关系")
        return result

    result["binding"] = _public_binding(binding)
    result["collection"]["sync_status"] = str(binding.get("sync_status") or "unknown")
    if str(binding.get("desired_state") or "").casefold() != "enabled":
        result.update(state="disabled", message="LibreNMS 资产绑定已停用")
        return result
    if not bool(binding.get("instance_enabled")):
        result.update(state="instance_disabled", message="LibreNMS 实例已停用")
        return result
    if not str(binding.get("librenms_device_id") or "").strip():
        result.update(state="native_device_missing", message="绑定尚未关联 LibreNMS 原生设备 ID")
        return result
    # LibreNMS uses the existing encrypted API-token credential type. Do not
    # introduce a parallel secret store or return its plaintext to the UI.
    if str(binding.get("credential_type") or "").casefold() != "api_token":
        result.update(state="credential_unavailable", message="LibreNMS API 凭据未配置或凭据类型不正确")
        return result
    try:
        token = decrypt_credential(str(binding.get("encrypted_password") or "")) or ""
    except Exception as exc:
        logger.warning("LibreNMS API token decryption failed: %s", type(exc).__name__)
        token = ""
    if not token:
        result.update(state="credential_unavailable", message="LibreNMS API 凭据不可用")
        return result

    now = datetime.now(timezone.utc)
    try:
        async with LibreNMSRuntimeClient(str(binding.get("base_url") or ""), token) as client:
            snapshot = await client.read_device_snapshot(str(binding["librenms_device_id"]))
            system = await client.get_system_info()
    except LibreNMSAPIError as exc:
        result.update(state="engine_unavailable", message="无法从 LibreNMS 读取当前原生结果")
        result["collection"].update(engine_status="error", error_code=exc.code)
        return result
    except Exception as exc:
        logger.warning("LibreNMS native diagnostic failed: %s", type(exc).__name__)
        result.update(state="engine_unavailable", message="无法从 LibreNMS 读取当前原生结果")
        result["collection"].update(engine_status="error", error_code="unexpected_error")
        return result

    raw_device = snapshot.device if isinstance(snapshot.device, Mapping) else {}
    safe_device = _safe_row(raw_device, _DEVICE_FIELDS)
    native_id = str(raw_device.get("device_id") or binding.get("librenms_device_id") or "")
    poll_period = _finite_number(raw_device.get("poller_interval") or raw_device.get("poller_seconds")) or 300
    stale_after_seconds = max(60, int(poll_period * 3))
    sensors_raw = [row for row in snapshot.sensors if isinstance(row, Mapping)]
    normalized_sensors, summary = _summarize_sensor_rows(
        [dict(row) for row in sensors_raw], observed_at=now, stale_after_seconds=stale_after_seconds,
    )
    processor_rows = [row for row in getattr(snapshot, "processor_sensors", []) if isinstance(row, Mapping)]
    memory_pool_rows = [row for row in getattr(snapshot, "memory_pools", []) if isinstance(row, Mapping)]
    processor_sensors = _normalize_native_health_rows(
        [dict(row) for row in processor_rows],
        health_type="processor", observed_at=now, stale_after_seconds=stale_after_seconds,
    )
    memory_pools = _normalize_native_health_rows(
        [dict(row) for row in memory_pool_rows],
        health_type="mempool", observed_at=now, stale_after_seconds=stale_after_seconds,
    )
    summary.extend([
        _summarize_health_rows(processor_sensors, key="processor"),
        _summarize_health_rows(memory_pools, key="mempool"),
    ])
    native_health_graphs = getattr(snapshot, "health_graphs", {})
    health_graphs = [
        {"health_type": category, **_safe_row(row, ("name", "desc"))}
        for category, rows in native_health_graphs.items()
        if isinstance(rows, list)
        for row in rows
        if isinstance(row, Mapping)
    ] if isinstance(native_health_graphs, Mapping) else []
    wireless_rows = [
        _safe_row(row, _WIRELESS_FIELDS)
        for row in snapshot.wireless_sensors
        if isinstance(row, Mapping)
    ][:_MAX_ROWS]
    transceiver_rows = [
        _safe_row(row, _TRANSCEIVER_FIELDS)
        for row in snapshot.transceivers
        if isinstance(row, Mapping)
    ][:_MAX_ROWS]

    system_row = system[0] if isinstance(system, list) and system and isinstance(system[0], Mapping) else system
    if not isinstance(system_row, Mapping):
        system_row = {}
    engine = {
        "instance_id": str(binding.get("instance_id") or ""),
        "name": str(binding.get("instance_name") or ""),
        "version": str(system_row.get("local_ver") or binding.get("engine_version") or ""),
        "commit": str(system_row.get("local_sha") or binding.get("engine_commit") or ""),
        "health_state": str(binding.get("instance_health_state") or "unknown"),
    }
    identity = {
        "native_device_id": native_id,
        "hostname": str(raw_device.get("hostname") or binding.get("librenms_hostname") or ""),
        "display": str(raw_device.get("display") or ""),
        "os": str(raw_device.get("os") or ""),
        "version": str(raw_device.get("version") or ""),
        "hardware": str(raw_device.get("hardware") or ""),
        "sysObjectID": str(raw_device.get("sysObjectID") or ""),
    }
    has_numeric = any(
        sensor.get("value_status") == "available"
        for sensor in [*normalized_sensors, *processor_sensors, *memory_pools]
    )
    has_hardware_metadata = bool(
        normalized_sensors or processor_sensors or memory_pools or health_graphs or wireless_rows or transceiver_rows
    )
    if has_numeric:
        state = "available"
        message = "已读取 LibreNMS 原生采样结果；各项保留 API 提供的采样时间，未提供时间的记录标为未知"
        sample_status = "available"
    elif has_hardware_metadata:
        state = "metadata_only"
        message = "LibreNMS 已提供硬件实体或健康图表元数据，但当前 API 响应没有可用数值样本"
        sample_status = "metadata_only"
    else:
        state = "no_native_hardware_data"
        message = "LibreNMS 当前未返回硬件实体；这表示暂无原生结果，不等于设备已确认不支持"
        sample_status = "no_data"

    if binding_resolution and binding_resolution.get("status") == "bound":
        message = f"已按唯一管理 IP 自动关联。{message}"

    result.update(
        state=state,
        message=message,
        **({"binding_resolution": {"status": binding_resolution.get("status")}} if binding_resolution else {}),
        engine=engine,
        identity=identity,
        health_graphs=health_graphs,
        hardware_sensors=normalized_sensors,
        processor_sensors=processor_sensors,
        memory_pools=memory_pools,
        transceivers=transceiver_rows,
        wireless_sensors=wireless_rows,
        sensor_count=len(normalized_sensors) + len(processor_sensors) + len(memory_pools),
        metric_summary=summary,
        live_poll_status="not_run",
        background_snapshot_status=sample_status,
    )
    result["collection"].update(
        engine_status="connected",
        sample_status=sample_status,
        sync_status=str(binding.get("sync_status") or "unknown"),
        last_discovered=safe_device.get("last_discovered"),
        last_polled=safe_device.get("last_polled"),
        stale_after_seconds=stale_after_seconds,
    )
    return result


__all__ = ["diagnose_librenms_hardware"]
