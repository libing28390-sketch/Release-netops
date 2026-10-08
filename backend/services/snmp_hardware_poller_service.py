"""Nexora-native SNMP discovery and polling for normalized hardware inventory.

LibreNMS rule bundles are used only as local, versioned OID definitions. All
SNMP requests, discovery state, samples, and metrics remain inside Nexora.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from database import get_db_connection
from services.snmp_hardware_inventory_service import (
    list_hardware_sensors,
    upsert_discovery_run,
)

logger = logging.getLogger(__name__)

DISCOVERY_INTERVAL_SECONDS = 24 * 60 * 60
PARTIAL_DISCOVERY_RETRY_SECONDS = 60 * 60
FAILED_DISCOVERY_RETRY_SECONDS = 15 * 60
SAMPLE_INTERVAL_SECONDS = 5 * 60
DISCOVERY_VERSION = "nexora-native-snmp-hardware-v1"

_SERVER_PLATFORMS = {"linux", "ubuntu", "debian", "centos", "rhel", "redhat", "server"}


def _as_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return {}


def _is_server_asset(device: Mapping[str, Any]) -> bool:
    asset_type = str(device.get("asset_type") or "").strip().casefold()
    platform = str(device.get("platform") or "").strip().casefold()
    category = str(device.get("device_category") or "").strip().casefold()
    return asset_type == "server" or platform in _SERVER_PLATFORMS or "server" in category


def _version_key(value: Any) -> str:
    version = str(value or "2c").strip().casefold()
    if version in {"1", "v1"}:
        return "1"
    if version in {"2", "2c", "v2c"}:
        return "2c"
    if version in {"3", "v3", "snmpv3"}:
        return "3"
    return ""


def _seconds_since(value: Any, now: datetime) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds())


def _latest_discovery(device_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT last_status, last_attempt_at
              FROM snmp_hardware_capabilities
             WHERE device_id = ? AND source_type <> 'librenms_native'
             ORDER BY last_attempt_at DESC,
                      CASE last_status
                          WHEN 'failed' THEN 0
                          WHEN 'partial' THEN 1
                          WHEN 'unsupported' THEN 2
                          ELSE 3
                      END,
                      component_class
             LIMIT 1
            """,
            (device_id,),
        ).fetchone()
        return _as_dict(row) if row else None
    finally:
        conn.close()


def _discovery_due(device_id: str, now: datetime) -> bool:
    latest = _latest_discovery(device_id)
    if not latest:
        return True
    status = str(latest.get("last_status") or "").casefold()
    if status in {"failed", "unsupported"}:
        interval = FAILED_DISCOVERY_RETRY_SECONDS
    elif status == "partial":
        interval = PARTIAL_DISCOVERY_RETRY_SECONDS
    else:
        interval = DISCOVERY_INTERVAL_SECONDS
    age = _seconds_since(latest.get("last_attempt_at"), now)
    return age is None or age >= interval


def _load_active_sensors(device_id: str) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = list_hardware_sensors(conn, device_id, include_retired=False)
        return [
            row for row in rows
            if str(row.get("data_origin") or "legacy_snmp").casefold() != "librenms_native"
            and row.get("enabled") is not False
        ]
    finally:
        conn.close()


def _poll_due(sensors: list[Mapping[str, Any]], now: datetime) -> bool:
    if not sensors:
        return False
    for sensor in sensors:
        age = _seconds_since(sensor.get("last_sample_at"), now)
        if age is None or age >= SAMPLE_INTERVAL_SECONDS:
            return True
    return False


def _resolve_identity_and_rule(
    *,
    device: Mapping[str, Any],
    sys_object_id: str,
    sys_descr: str,
    sys_name: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from services.librenms_rule_service import resolve_rule
    from services.snmp_discovery_service import resolve_snmp_vendor_identity

    conn = get_db_connection()
    try:
        identity = resolve_snmp_vendor_identity(
            conn,
            sys_object_id=sys_object_id,
            sys_descr=sys_descr,
            sys_name=sys_name,
            asset_vendor=device.get("vendor"),
            asset_platform=device.get("platform"),
            asset_model=device.get("model"),
        )
        rule = resolve_rule(
            conn,
            {
                "sys_object_id": sys_object_id,
                "sys_descr": sys_descr,
                "sys_name": sys_name,
            },
        )
        if str(identity.get("status") or "").casefold() == "conflict":
            rule = None
        if rule:
            identity["vendor"] = rule.get("vendor") or identity.get("vendor") or ""
            identity["platform"] = rule.get("platform") or identity.get("platform") or ""
            identity["os_key"] = rule.get("os_key") or ""
            identity["rule_id"] = rule.get("id") or ""
        identity["role"] = device.get("role") or ""
        identity["asset_platform"] = device.get("platform") or ""
        identity["model"] = identity.get("model") or device.get("model") or ""
        return identity, rule
    finally:
        conn.close()


def _persist_discovery(
    *,
    device_id: str,
    rule: Mapping[str, Any] | None,
    sensors: list[dict[str, Any]],
    category_results: list[dict[str, Any]],
    observed_at: datetime,
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        rule_version = str((rule or {}).get("source_commit") or "bundled-snmp-rules")
        outcome = upsert_discovery_run(
            conn,
            device_id,
            uuid.uuid4().hex,
            rule_version,
            sensors,
            category_results,
            observed_at,
            discovery_version=DISCOVERY_VERSION,
            artifact_version=str((rule or {}).get("source_path") or "nexora-standard-mibs"),
            started_at=observed_at,
        )
        conn.commit()
        return outcome
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def _discover_device(
    *,
    device: Mapping[str, Any],
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    version: str,
) -> dict[str, Any]:
    from services.librenms_rule_service import ensure_rules_available
    from services.snmp_hardware_probe_service import (
        probe_librenms_hardware,
        probe_standard_hardware,
    )
    from services.snmp_service import (
        SYS_DESCR,
        SYS_NAME,
        SYS_OBJECT_ID,
        _snmp_get_versioned,
    )

    await asyncio.to_thread(ensure_rules_available)
    sys_name, sys_descr, sys_object_id = await asyncio.gather(
        _snmp_get_versioned(ip, community, SYS_NAME, port, version),
        _snmp_get_versioned(ip, community, SYS_DESCR, port, version),
        _snmp_get_versioned(ip, community, SYS_OBJECT_ID, port, version),
    )
    observed_at = datetime.now(timezone.utc)
    identity, rule = await asyncio.to_thread(
        _resolve_identity_and_rule,
        device=device,
        sys_object_id=str(sys_object_id or ""),
        sys_descr=str(sys_descr or ""),
        sys_name=str(sys_name or ""),
    )

    sensors: list[dict[str, Any]] = []
    category_results: list[dict[str, Any]] = []
    probe_errors: list[str] = []
    try:
        standard = await probe_standard_hardware(
            ip,
            community,
            port,
            version=version,
            cisco_iosxr=bool(rule and str(rule.get("os_key") or "").casefold() == "iosxr"),
        )
        sensors.extend(standard.get("sensors") or [])
        category_results.extend(standard.get("category_results") or [])
    except Exception as exc:  # keep a failed category visible and retryable
        logger.warning("Standard hardware discovery failed for device %s (%s)", device.get("id"), type(exc).__name__)
        probe_errors.append(type(exc).__name__)
        category_results.append({
            "source_type": "nexora_snmp",
            "component_class": "standard_hardware",
            "status": "failed",
            "coverage_complete": False,
            "reason_code": "standard_hardware_probe_error",
            "reason": f"Standard MIB discovery failed: {type(exc).__name__}",
        })

    if rule and str(identity.get("status") or "").casefold() != "conflict":
        try:
            native = await probe_librenms_hardware(
                ip,
                community,
                port,
                rule=rule,
                identity=identity,
                version=version,
            )
            sensors.extend(native.get("sensors") or [])
            category_results.extend(native.get("category_results") or [])
        except Exception as exc:
            logger.warning("Rule-based hardware discovery failed for device %s (%s)", device.get("id"), type(exc).__name__)
            probe_errors.append(type(exc).__name__)
            category_results.append({
                "source_type": "nexora_snmp",
                "component_class": "rule_hardware",
                "status": "failed",
                "coverage_complete": False,
                "reason_code": "rule_hardware_probe_error",
                "reason": f"Rule-based hardware discovery failed: {type(exc).__name__}",
            })

    if not category_results:
        has_identity = bool(sys_object_id or sys_descr or sys_name)
        category_results.append({
            "source_type": "nexora_snmp",
            "component_class": "hardware_inventory",
            "status": "not_found" if rule else "unsupported" if has_identity else "failed",
            "coverage_complete": False,
            "reason_code": "no_hardware_definition" if rule is None else "no_hardware_sensors",
            "reason": (
                "No bundled hardware definition matched the observed SNMP identity"
                if rule is None and has_identity
                else "SNMP system identity could not be read"
                if not has_identity
                else "The matched definition returned no hardware sensor rows"
            ),
        })

    outcome = await asyncio.to_thread(
        _persist_discovery,
        device_id=str(device.get("id") or ""),
        rule=rule,
        sensors=sensors,
        category_results=category_results,
        observed_at=observed_at,
    )
    status = (
        "failed" if probe_errors and not sensors
        else "partial" if probe_errors
        else "success" if sensors
        else "no_sensors"
    )
    return {
        "status": status,
        "sensor_count": len(sensors),
        "category_results": outcome.get("results") or [],
    }


async def collect_device_hardware(device_row: Any) -> dict[str, Any]:
    """Discover and poll due hardware for one online network device."""
    device = _as_dict(device_row)
    device_id = str(device.get("id") or "").strip()
    if not device_id or _is_server_asset(device):
        return {"status": "skipped"}

    try:
        from services.vault_service import resolve_collector_credentials

        credentials = resolve_collector_credentials(device).get("snmp") or {}
    except Exception as exc:
        logger.warning("SNMP credential lookup failed for device %s (%s)", device_id, type(exc).__name__)
        return {"status": "credential_error"}

    community = str(credentials.get("community") or "")
    ip = str(credentials.get("server") or device.get("ip_address") or "").strip()
    version = _version_key(credentials.get("version") or device.get("snmp_version"))
    try:
        port = int(credentials.get("port") or device.get("snmp_port") or 161)
    except (TypeError, ValueError):
        port = 161
    if not ip:
        return {"status": "not_configured"}
    if not version:
        return {"status": "unsupported_version"}
    configuration_error = str(credentials.get("configuration_error") or "").strip()
    configured = credentials.get("configured")
    if configured is None:
        configured = bool(community)
    if not configured or configuration_error:
        return {
            "status": "invalid_credentials" if configuration_error else "not_configured",
            "reason_code": configuration_error or "snmp_credentials_missing",
        }
    if version == "3":
        community_or_profile: str | Mapping[str, Any] = credentials
    else:
        if not community:
            return {"status": "not_configured"}
        community_or_profile = community
    if not 1 <= port <= 65535:
        return {"status": "invalid_port"}

    now = datetime.now(timezone.utc)
    discovery: dict[str, Any] | None = None
    try:
        if await asyncio.to_thread(_discovery_due, device_id, now):
            discovery = await _discover_device(
                device=device,
                ip=ip,
                community=community_or_profile,
                port=port,
                version=version,
            )
    except Exception as exc:
        logger.warning("SNMP hardware discovery failed for device %s (%s)", device_id, type(exc).__name__)
        discovery = {
            "status": "failed",
            "sensor_count": 0,
            "category_results": [{
                "source_type": "nexora_snmp",
                "component_class": "hardware_inventory",
                "status": "failed",
                "coverage_complete": False,
                "reason_code": "snmp_discovery_error",
                "reason": f"SNMP discovery failed: {type(exc).__name__}",
            }],
        }
        try:
            await asyncio.to_thread(
                _persist_discovery,
                device_id=device_id,
                rule=None,
                sensors=[],
                category_results=discovery["category_results"],
                observed_at=datetime.now(timezone.utc),
            )
            discovery["failure_persisted"] = True
        except Exception as persist_exc:
            logger.warning(
                "SNMP hardware discovery failure state could not be persisted for device %s (%s)",
                device_id,
                type(persist_exc).__name__,
            )
            discovery["failure_persisted"] = False

    try:
        sensors = await asyncio.to_thread(_load_active_sensors, device_id)
        if _poll_due(sensors, datetime.now(timezone.utc)):
            from services.snmp_hardware_probe_service import poll_hardware_inventory

            sample_result = await poll_hardware_inventory(
                ip,
                community_or_profile,
                port,
                version,
                sensors,
            )
        else:
            sample_result = {"good": 0, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    except Exception as exc:
        logger.warning("SNMP hardware polling failed for device %s (%s)", device_id, type(exc).__name__)
        return {"status": "poll_failed", "discovery": discovery}

    if discovery and discovery.get("status") == "failed" and not sample_result.get("good"):
        collection_status = "discovery_failed"
    else:
        collection_status = "collected" if discovery or sensors else "idle"
    return {
        "status": collection_status,
        "discovery": discovery,
        "sample": sample_result,
    }


__all__ = ["collect_device_hardware"]
