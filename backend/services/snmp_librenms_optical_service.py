"""On-demand optical records projected from the local LibreNMS hardware probe."""

from __future__ import annotations

import asyncio
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_DIRECTION = re.compile(r"\b(rx|receive|tx|transmit)\b", re.IGNORECASE)
_OPTICAL_CONTEXT = re.compile(r"\b(transceiver|xcvr|optic|optical|dom)\b", re.IGNORECASE)


def _run_async(coro: Any) -> Any:
    """Run the shared async discovery flow from synchronous API services."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _sensor_text(sensor: Mapping[str, Any]) -> str:
    metadata = sensor.get("metadata") if isinstance(sensor.get("metadata"), Mapping) else {}
    raw = metadata.get("raw_definition") if isinstance(metadata.get("raw_definition"), Mapping) else {}
    return " ".join(
        str(value or "")
        for value in (
            sensor.get("sensor_name"), sensor.get("entity_name"), sensor.get("group_name"),
            raw.get("descr"), raw.get("group"), raw.get("value"), raw.get("num_oid"),
        )
    ).strip()


def _direction(text: str) -> str:
    match = _DIRECTION.search(text)
    if not match:
        return ""
    return "rx" if match.group(1).casefold() in {"rx", "receive"} else "tx"


def _rule_has_optical_definitions(rule: Any) -> bool:
    if not isinstance(rule, Mapping):
        return False
    hardware = rule.get("hardware_definitions") if isinstance(rule.get("hardware_definitions"), Mapping) else {}
    definitions = hardware.get("sensors") if isinstance(hardware.get("sensors"), list) else []
    for definition in definitions:
        if not isinstance(definition, Mapping):
            continue
        source_class = str(definition.get("source_class") or "").casefold()
        group = str(definition.get("group") or "")
        descr = str(definition.get("descr") or "")
        if source_class == "dbm" or _OPTICAL_CONTEXT.search(group) or _OPTICAL_CONTEXT.search(descr):
            return True
    return str(rule.get("os_key") or "").casefold() == "comware"


def _sensors_have_optical_data(sensors: Any) -> bool:
    if not isinstance(sensors, list):
        return False
    return any(
        isinstance(sensor, Mapping)
        and (
            str(sensor.get("measurement_type") or "").casefold() == "optical_power_dbm"
            or _OPTICAL_CONTEXT.search(_sensor_text(sensor))
        )
        for sensor in sensors
    )


def _interface_label(sensor: Mapping[str, Any], text: str, if_index: int | None, entity_index: int | None) -> str:
    labels = sensor.get("index_labels") if isinstance(sensor.get("index_labels"), Mapping) else {}
    explicit = str(labels.get("if_name") or "").strip()
    if explicit:
        return explicit

    # When the upstream description names a real port, retain that label. YAML
    # placeholders remain unresolved and fall through to an explicit index.
    for value in (sensor.get("sensor_name"), sensor.get("entity_name")):
        candidate = str(value or "").strip()
        if candidate and not candidate.startswith("Entity sensor ") and not "{{" in candidate:
            return candidate
    if if_index is not None:
        return f"ifIndex{if_index}"
    if entity_index is not None:
        return f"Entity {entity_index}"
    return "Optical sensor"


def _optical_records(sensors: Any, vendor: str, collected_at: str) -> list[dict[str, Any]]:
    if not isinstance(sensors, list):
        return []
    grouped: dict[tuple[str, int | None, int | None, int | None], dict[str, Any]] = {}
    for sensor in sensors:
        if not isinstance(sensor, Mapping) or str(sensor.get("quality") or "").casefold() != "good":
            continue
        value = _number(sensor.get("value"))
        if value is None:
            continue
        metadata = sensor.get("metadata") if isinstance(sensor.get("metadata"), Mapping) else {}
        labels = sensor.get("index_labels") if isinstance(sensor.get("index_labels"), Mapping) else {}
        index = sensor.get("index") if isinstance(sensor.get("index"), list) else []
        text = _sensor_text(sensor)
        raw_definition = metadata.get("raw_definition") if isinstance(metadata.get("raw_definition"), Mapping) else {}
        group_text = " ".join((str(sensor.get("group_name") or ""), str(raw_definition.get("group") or "")))
        measurement = str(sensor.get("measurement_type") or "").casefold()
        is_optical_group = bool(_OPTICAL_CONTEXT.search(group_text) or _OPTICAL_CONTEXT.search(text))

        # ENTITY-MIB entPhysicalIndex is a hardware entity identifier, not an
        # IF-MIB ifIndex. Only expose ifIndex when discovery explicitly mapped
        # the sensor to an interface.
        if_index_value = labels.get("if_index")
        try:
            if_index = int(if_index_value) if if_index_value not in (None, "") else None
        except (TypeError, ValueError):
            if_index = None
        entity_value = metadata.get("ent_physical_index") or labels.get("ent_physical_index")
        if entity_value in (None, "") and str(sensor.get("source_type") or "").casefold() == "standard_mib":
            source_id = str(sensor.get("source_id") or "").casefold()
            if "entity-sensor-mib::entphysensorvalue" in source_id and index:
                entity_value = index[0]
        try:
            entity_index = int(entity_value) if entity_value not in (None, "") else None
        except (TypeError, ValueError):
            entity_index = None
        lane_index = None
        if len(index) > 1:
            try:
                lane_index = int(index[1])
            except (TypeError, ValueError):
                lane_index = None

        field = ""
        if measurement == "optical_power_dbm":
            direction = _direction(text)
            if direction:
                field = f"{direction}_power_dbm"
            elif not is_optical_group:
                continue
        elif is_optical_group:
            if measurement == "temperature_celsius":
                field = "temperature_c"
            elif measurement == "voltage_volts":
                field = "voltage_v"
            elif measurement == "current_amperes":
                field = "bias_ma"
                value *= 1000.0
        if not field:
            continue

        interface = _interface_label(sensor, text, if_index, entity_index)
        key = (interface, if_index, entity_index, lane_index)
        record = grouped.setdefault(key, {
            "interface": interface,
            "vendor": vendor,
            "collected_at": collected_at,
            "source": "snmp",
        })
        if if_index is not None:
            record["ifIndex"] = if_index
        if entity_index is not None:
            record["entityIndex"] = entity_index
        if lane_index is not None:
            record["laneIndex"] = lane_index
        record[field] = round(value, 3)
    return list(grouped.values())


async def _probe_local_hardware(
    server: str,
    community: str,
    port: int,
    version: str,
    device: Mapping[str, Any],
) -> dict[str, Any]:
    """Run only standard MIB and pinned LibreNMS hardware probes."""
    from database import get_db_connection
    from services.librenms_rule_service import ensure_rules_available
    from services.snmp_discovery_service import (
        SYS_DESCR,
        SYS_NAME,
        SYS_OBJECT_ID,
        _merge_hardware_discovery,
        _resolve_live_librenms_rule,
        classify_identity,
    )
    from services.snmp_hardware_probe_service import probe_librenms_hardware, probe_standard_hardware
    from services.snmp_service import _snmp_get_versioned
    from services.snmp_vendor_registry import normalize_asset_vendor, vendor_from_asset_platform

    sys_name, sys_descr, sys_object_id = await asyncio.gather(
        _snmp_get_versioned(server, community, SYS_NAME, port, version),
        _snmp_get_versioned(server, community, SYS_DESCR, port, version),
        _snmp_get_versioned(server, community, SYS_OBJECT_ID, port, version),
    )
    identity = classify_identity(
        vendor=device.get("vendor") or "",
        platform=device.get("platform") or "",
        model=device.get("model") or "",
        version=device.get("software_version") or device.get("version") or "",
        sys_object_id=sys_object_id,
        sys_descr=sys_descr,
        sys_name=sys_name,
    )
    await asyncio.to_thread(ensure_rules_available)
    conn = get_db_connection()
    try:
        rule = await _resolve_live_librenms_rule(
            conn,
            ip=server,
            community=community,
            port=port,
            snmp_version=version,
            identity=identity,
        )
    finally:
        conn.close()

    if rule and str(rule.get("vendor") or "").strip():
        rule_vendor = normalize_asset_vendor(rule.get("vendor"))
        declared_vendor = normalize_asset_vendor(device.get("vendor")) or vendor_from_asset_platform(device.get("platform"))
        observed_vendor = normalize_asset_vendor(identity.get("vendor"))
        conflicts = {
            normalize_asset_vendor(item.get("vendor"))
            for item in (rule.get("identity_match") or {}).get("conflicts", [])
            if isinstance(item, Mapping) and item.get("vendor")
        }
        if declared_vendor and rule_vendor and declared_vendor != rule_vendor:
            identity["status"] = "conflict"
        elif observed_vendor and observed_vendor not in {"unknown", rule_vendor}:
            identity["status"] = "conflict"
        elif any(value and value != rule_vendor for value in conflicts):
            identity["status"] = "conflict"
        else:
            identity["vendor"] = rule_vendor
            identity["platform"] = str(rule.get("platform") or identity.get("platform") or "")
            if identity.get("status") in {"unsupported_vendor", "identity_missing"}:
                identity["status"] = "identified"
        identity["librenms_rule_id"] = rule.get("id") or ""
        identity["librenms_os_key"] = rule.get("os_key") or ""
        identity["identity_match"] = rule.get("identity_match") or {}
        identity["identity_rule_compatibility"] = rule.get("compatibility") or {}

    cisco_iosxr = bool(
        rule
        and str(rule.get("os_key") or "").casefold() == "iosxr"
        and str(identity.get("vendor") or "").casefold() == "cisco"
        and identity.get("status") != "conflict"
    )
    standard = await probe_standard_hardware(
        server, community, port, version=version, cisco_iosxr=cisco_iosxr,
    )
    librenms: dict[str, Any] | None = None
    if rule and identity.get("status") != "conflict":
        librenms = await probe_librenms_hardware(
            server,
            community,
            port,
            rule=rule,
            identity=identity,
            version=version,
        )
    merged = _merge_hardware_discovery(
        {"hardware_sensors": [], "hardware_category_results": []},
        standard,
        librenms,
    )
    return {
        "identity": identity,
        "librenms_rule": rule,
        "hardware_sensors": merged.get("hardware_sensors") or [],
        "hardware_category_results": merged.get("hardware_category_results") or [],
    }


def collect_librenms_optical(device_info: dict[str, Any]) -> dict[str, Any]:
    """Collect optical DOM through the pinned LibreNMS and standard-MIB probe."""
    device = device_info if isinstance(device_info, dict) else {}
    vendor = str(device.get("vendor") or "unknown").strip() or "unknown"
    adapter = {
        "vendor": vendor,
        "supported": True,
        "reason": "project-local LibreNMS OS rules and standard hardware probes",
        "mode": "librenms",
    }
    try:
        from services.vault_service import resolve_collector_credentials

        credentials = resolve_collector_credentials(device)
        snmp = credentials.get("snmp") if isinstance(credentials, Mapping) else None
        snmp = snmp if isinstance(snmp, Mapping) else {}
        community = str(snmp.get("community") or "")
        if not snmp.get("configured") or not community:
            return {
                "success": False, "source": "snmp", "adapter": adapter,
                "records": [], "count": 0, "error_code": "SNMP_CREDENTIALS_MISSING",
                "error": "SNMP credentials are not configured",
            }
        server = str(snmp.get("server") or device.get("ip_address") or "").strip()
        if not server:
            return {
                "success": False, "source": "snmp", "adapter": adapter,
                "records": [], "count": 0, "error_code": "SNMP_TARGET_MISSING",
                "error": "SNMP target address is missing",
            }
        port = int(snmp.get("port") or device.get("snmp_port") or 161)
        version = str(snmp.get("version") or "2c")
        discovery = _run_async(_probe_local_hardware(server, community, port, version, device))
        identity = discovery.get("identity") if isinstance(discovery.get("identity"), Mapping) else {}
        rule = discovery.get("librenms_rule")
        observed_vendor = str(identity.get("vendor") or vendor).strip() or vendor
        support_status = str(((rule or {}).get("compatibility") or {}).get("hardware_level") or "partial")
        if support_status not in {"supported", "partial", "requires_adapter", "unsupported"}:
            support_status = "partial"
        sensors_have_optics = _sensors_have_optical_data(discovery.get("hardware_sensors"))
        has_optical_support = _rule_has_optical_definitions(rule) or sensors_have_optics
        adapter.update({
            "vendor": observed_vendor,
            "support_status": support_status,
            "supported": has_optical_support and support_status in {"supported", "partial"},
            "os_key": str(identity.get("librenms_os_key") or ""),
            "rule_id": str(identity.get("librenms_rule_id") or ""),
        })
        collected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        records = _optical_records(discovery.get("hardware_sensors"), observed_vendor, collected_at)
        conflict = str(identity.get("status") or "").casefold() == "conflict"
        success = not conflict and has_optical_support and support_status in {"supported", "partial"}
        result = {
            "success": success,
            "source": "snmp",
            "adapter": adapter,
            "records": records,
            "count": len(records),
        }
        if conflict:
            result.update({"error_code": "SNMP_IDENTITY_CONFLICT", "error": "Observed SNMP identity conflicts with the device asset"})
        elif not success:
            result.update({"error_code": "UNSUPPORTED_VENDOR", "error": "No supported standard or LibreNMS hardware rule was identified"})
        return result
    except Exception:
        logger.info("LibreNMS optical SNMP collection failed for %s", device.get("hostname") or device.get("id") or "device")
        return {
            "success": False,
            "source": "snmp",
            "adapter": adapter,
            "records": [],
            "count": 0,
            "error_code": "SNMP_COLLECTION_ERROR",
            "error": "LibreNMS hardware collection failed",
        }


__all__ = ["collect_librenms_optical"]
