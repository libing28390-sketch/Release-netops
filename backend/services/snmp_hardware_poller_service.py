"""Nexora-native SNMP discovery and polling for normalized hardware inventory.

LibreNMS rule bundles are used only as local, versioned OID definitions. All
SNMP requests, discovery state, samples, and metrics remain inside Nexora.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
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
SAMPLE_INTERVAL_SECONDS = 60
DISCOVERY_VERSION = "nexora-librenms-rules-hardware-v8"
_POLL_EXCLUDED_MEASUREMENT_TYPES = frozenset({
    "voltage_volts",
    "current_amperes",
    "sensor_value",
})


def hardware_sample_interval_seconds() -> int:
    """Keep polling configurable without coupling it to discovery cadence."""
    try:
        interval = int(os.environ.get("SNMP_HARDWARE_SAMPLE_INTERVAL_SECONDS", SAMPLE_INTERVAL_SECONDS))
    except (TypeError, ValueError):
        interval = SAMPLE_INTERVAL_SECONDS
    return max(15, min(3600, interval))


def hardware_stale_after_seconds(sensor: Mapping[str, Any] | None = None) -> float:
    """Use one freshness threshold for diagnostics and time-series export."""
    metadata = (sensor or {}).get("metadata") or {}
    try:
        registered = float(metadata.get("poll_interval_seconds") or 0)
    except (TypeError, ValueError):
        registered = 0.0
    try:
        configured = float(os.environ.get("SNMP_HARDWARE_STALE_SECONDS", 180))
    except (TypeError, ValueError):
        configured = 180.0
    return max(180.0, configured, 3.0 * max(hardware_sample_interval_seconds(), registered))

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
            SELECT last_status, last_attempt_at, discovery_version
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
    if latest.get("discovery_version") != DISCOVERY_VERSION:
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
    from services.librenms_source_policy import (
        hardware_sensor_trust_cache_key,
        is_trusted_hardware_sensor,
    )

    conn = get_db_connection()
    try:
        rows = list_hardware_sensors(conn, device_id, include_retired=False)
        trust_by_provenance: dict[tuple[Any, ...], bool] = {}
        active_sensors: list[dict[str, Any]] = []
        for row in rows:
            if row.get("enabled") is False:
                continue
            measurement_type = str(row.get("measurement_type") or "").strip().casefold()
            if measurement_type in _POLL_EXCLUDED_MEASUREMENT_TYPES:
                continue
            if (row.get("metadata") or {}).get("collection_version") != DISCOVERY_VERSION:
                continue

            trust_key = hardware_sensor_trust_cache_key(row)
            trusted = trust_by_provenance.get(trust_key)
            if trusted is None:
                trusted = is_trusted_hardware_sensor(row)
                trust_by_provenance[trust_key] = trusted
            if trusted:
                active_sensors.append(row)
        return active_sensors
    finally:
        conn.close()


def _poll_due(sensors: list[Mapping[str, Any]], now: datetime) -> bool:
    if not sensors:
        return False
    for sensor in sensors:
        measurement_type = str(sensor.get("measurement_type") or "").strip().casefold()
        if measurement_type in _POLL_EXCLUDED_MEASUREMENT_TYPES:
            continue
        age = _seconds_since(sensor.get("last_sample_at"), now)
        if age is None or age >= hardware_sample_interval_seconds():
            return True
    return False


def _device_sensor_poll_state(device_id: str, now: datetime) -> tuple[bool, bool]:
    """Check whether current inventory has any sensor and whether one is due.

    The frequent sampling loop uses this narrow aggregate query to avoid
    decoding every sensor's JSON metadata and resolving credentials on ticks
    where no sample is due.
    """
    cutoff = now - timedelta(seconds=hardware_sample_interval_seconds())
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) > 0 AS has_active,
                   COALESCE(BOOL_OR(last_sample_at IS NULL OR last_sample_at <= ?), FALSE) AS has_due
              FROM snmp_hardware_sensors
             WHERE device_id = ?
               AND enabled IS TRUE
               AND LOWER(TRIM(COALESCE(measurement_type, ''))) NOT IN (
                   'voltage_volts', 'current_amperes', 'sensor_value'
               )
               AND metadata_json->>'collection_version' = ?
            """,
            (cutoff, device_id, DISCOVERY_VERSION),
        ).fetchone()
        values = _as_dict(row)
        return bool(values.get("has_active")), bool(values.get("has_due"))
    finally:
        conn.close()


def _resolve_identity_and_rule(
    *,
    device: Mapping[str, Any],
    sys_object_id: str,
    sys_descr: str,
    sys_name: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from services.librenms_rule_service import resolve_rule
    from services.librenms_source_policy import verify_bundled_rule
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
        elif ((rule or {}).get("identity_match") or {}).get("conflicts"):
            # Never select an arbitrary OS rule when multiple pinned LibreNMS
            # definitions match at the same score. Import identification
            # already fails closed on this condition; scheduled discovery must
            # use the same rule-selection contract.
            identity["status"] = "ambiguous"
            identity["reason_code"] = "ambiguous_librenms_rule"
            rule = None
        if rule and not verify_bundled_rule(rule):
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
        from services.librenms_source_policy import is_trusted_hardware_sensor

        trusted_sensors = []
        for sensor in sensors:
            if not is_trusted_hardware_sensor(sensor):
                continue
            trusted = dict(sensor)
            trusted["metadata"] = {
                **(sensor.get("metadata") or {}),
                "collection_version": DISCOVERY_VERSION,
                "poll_interval_seconds": hardware_sample_interval_seconds(),
            }
            trusted_sensors.append(trusted)
        rule_version = str((rule or {}).get("source_commit") or "bundled-snmp-rules")
        outcome = upsert_discovery_run(
            conn,
            device_id,
            uuid.uuid4().hex,
            rule_version,
            trusted_sensors,
            category_results,
            observed_at,
            discovery_version=DISCOVERY_VERSION,
            artifact_version=str((rule or {}).get("source_path") or "librenms-rule-unavailable"),
            started_at=observed_at,
        )
        # Keep history recoverable, but never keep polling a superseded plan.
        # Retirement follows accepted discovery, so a failed attempt cannot
        # remove the last valid inventory for this collection version.
        if trusted_sensors:
            conn.execute(
                """
                UPDATE snmp_hardware_sensors
                   SET enabled = FALSE, lifecycle_status = 'retired', updated_at = ?
                 WHERE device_id = ?
                   AND data_origin <> 'librenms_native'
                   AND metadata_json->>'collection_version' IS DISTINCT FROM ?
                """,
                (observed_at, device_id, DISCOVERY_VERSION),
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
    persist: bool = True,
) -> dict[str, Any]:
    from services.librenms_rule_service import ensure_rules_available
    from services.snmp_hardware_probe_service import (
        probe_librenms_hardware,
        probe_librenms_os_hardware,
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
        if str(rule.get("os_key") or "").strip().casefold() in {"ios", "comware"}:
            try:
                os_hardware = await probe_librenms_os_hardware(
                    ip,
                    community,
                    port,
                    rule=rule,
                    identity=identity,
                    version=version,
                )
                sensors.extend(os_hardware.get("sensors") or [])
                category_results.extend(os_hardware.get("category_results") or [])
            except Exception as exc:
                logger.warning("LibreNMS OS hardware discovery failed for device %s (%s)", device.get("id"), type(exc).__name__)
                probe_errors.append(type(exc).__name__)
                category_results.append({
                    "source_type": "nexora_snmp",
                    "component_class": "librenms_os_rule",
                    "status": "failed",
                    "coverage_complete": False,
                    "reason_code": "librenms_os_hardware_probe_error",
                    "reason": f"LibreNMS OS hardware discovery failed: {type(exc).__name__}",
                })

        from services.librenms_wireless_rule_service import WIRELESS_RULE_OS_KEYS

        if str(rule.get("os_key") or "").strip().casefold() in WIRELESS_RULE_OS_KEYS:
            try:
                from services.librenms_wireless_rule_service import probe_librenms_wireless_hardware

                wireless = await probe_librenms_wireless_hardware(
                    ip,
                    community,
                    port,
                    rule=rule,
                    identity=identity,
                    version=version,
                )
                sensors.extend(wireless.get("sensors") or [])
                category_results.extend(wireless.get("category_results") or [])
            except Exception as exc:
                logger.warning("LibreNMS wireless discovery failed for device %s (%s)", device.get("id"), type(exc).__name__)
                probe_errors.append(type(exc).__name__)
                category_results.append({
                    "source_type": "nexora_snmp",
                    "component_class": "wireless_access_point",
                    "status": "failed",
                    "coverage_complete": False,
                    "reason_code": "librenms_mib_wireless_probe_error",
                    "reason": f"LibreNMS MIB wireless discovery failed: {type(exc).__name__}",
                })

    from services.librenms_source_policy import is_trusted_hardware_sensor
    sensors = [sensor for sensor in sensors if is_trusted_hardware_sensor(sensor)]

    if not category_results:
        has_identity = bool(sys_object_id or sys_descr or sys_name)
        ambiguous_rule = str(identity.get("reason_code") or "").casefold() == "ambiguous_librenms_rule"
        category_results.append({
            "source_type": "nexora_snmp",
            "component_class": "hardware_inventory",
            "status": "not_found" if rule else "unsupported" if has_identity else "failed",
            "coverage_complete": False,
            "reason_code": (
                "ambiguous_librenms_rule" if ambiguous_rule
                else "no_hardware_definition" if rule is None
                else "no_hardware_sensors"
            ),
            "reason": (
                "Multiple pinned LibreNMS OS definitions matched; discovery was skipped to avoid selecting the wrong rule"
                if ambiguous_rule
                else "No bundled hardware definition matched the observed SNMP identity"
                if rule is None and has_identity
                else "SNMP system identity could not be read"
                if not has_identity
                else "The matched definition returned no hardware sensor rows"
            ),
        })

    if persist:
        outcome = await asyncio.to_thread(
            _persist_discovery,
            device_id=str(device.get("id") or ""),
            rule=rule,
            sensors=sensors,
            category_results=category_results,
            observed_at=observed_at,
        )
        persisted_results = outcome.get("results") or []
    else:
        persisted_results = category_results
    status = (
        "failed" if probe_errors and not sensors
        else "partial" if probe_errors
        else "success" if sensors
        else "no_sensors"
    )
    return {
        "status": status,
        "sensor_count": len(sensors),
        "category_results": persisted_results,
        "identity": {
            **identity,
            "sys_name": str(sys_name or ""),
            "sys_descr": str(sys_descr or ""),
            "sys_object_id": str(sys_object_id or ""),
        },
        "rule": ({
            "id": str(rule.get("id") or ""),
            "os_key": str(rule.get("os_key") or ""),
            "vendor": str(rule.get("vendor") or ""),
            "platform": str(rule.get("platform") or ""),
            "source_path": str(rule.get("discovery_source_path") or rule.get("source_path") or ""),
            "source_commit": str(rule.get("source_commit") or ""),
        } if rule else None),
        "sensors": sensors if not persist else [],
    }


async def inspect_librenms_hardware_rules(device_row: Any) -> dict[str, Any]:
    """Run the same pinned LibreNMS discovery path once without persisting it."""
    device = _as_dict(device_row)
    device_id = str(device.get("id") or "").strip()
    if not device_id or _is_server_asset(device):
        return {"status": "unsupported_device", "sensor_count": 0, "category_results": [], "sensors": []}

    try:
        from services.vault_service import resolve_collector_credentials

        credentials = resolve_collector_credentials(device).get("snmp") or {}
    except Exception as exc:
        logger.warning("SNMP credential lookup failed for rule diagnostic %s (%s)", device_id, type(exc).__name__)
        return {"status": "credential_error", "reason_code": "snmp_credential_lookup_failed", "sensor_count": 0, "category_results": [], "sensors": []}

    ip = str(credentials.get("server") or device.get("ip_address") or "").strip()
    version = _version_key(credentials.get("version") or device.get("snmp_version"))
    try:
        port = int(credentials.get("port") or device.get("snmp_port") or 161)
    except (TypeError, ValueError):
        return {"status": "invalid_port", "sensor_count": 0, "category_results": [], "sensors": []}
    if not ip:
        return {"status": "not_configured", "sensor_count": 0, "category_results": [], "sensors": []}
    if not version:
        return {"status": "unsupported_version", "sensor_count": 0, "category_results": [], "sensors": []}
    if not 1 <= port <= 65535:
        return {"status": "invalid_port", "sensor_count": 0, "category_results": [], "sensors": []}
    configuration_error = str(credentials.get("configuration_error") or "").strip()
    configured = credentials.get("configured")
    if configured is None:
        configured = bool(credentials.get("community")) or version == "3"
    if not configured or configuration_error:
        return {
            "status": "invalid_credentials" if configuration_error else "not_configured",
            "reason_code": configuration_error or "snmp_credentials_missing",
            "sensor_count": 0,
            "category_results": [],
            "sensors": [],
        }
    if version == "3":
        community: str | Mapping[str, Any] = credentials
    else:
        community_value = str(credentials.get("community") or "")
        if not community_value:
            return {"status": "not_configured", "sensor_count": 0, "category_results": [], "sensors": []}
        community = community_value

    return await _discover_device(
        device=device,
        ip=ip,
        community=community,
        port=port,
        version=version,
        persist=False,
    )


async def collect_device_hardware(
    device_row: Any, *, discovery_only: bool = False, poll_only: bool = False,
) -> dict[str, Any]:
    """Run discovery or sampling independently; both remain available to callers."""
    if discovery_only and poll_only:
        raise ValueError("discovery_only and poll_only are mutually exclusive")
    device = _as_dict(device_row)
    device_id = str(device.get("id") or "").strip()
    if not device_id or _is_server_asset(device):
        return {"status": "skipped"}

    if poll_only:
        try:
            has_active_sensors, has_due_sensors = await asyncio.to_thread(
                _device_sensor_poll_state,
                device_id,
                datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.warning("SNMP hardware poll schedule lookup failed for device %s (%s)", device_id, type(exc).__name__)
            return {"status": "poll_failed", "discovery": None}
        if not has_active_sensors or not has_due_sensors:
            return {
                "status": "idle",
                "discovery": None,
                "sample": {"good": 0, "missing": 0, "invalid": 0, "unsupported_mapping": 0},
            }

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
        if not poll_only and await asyncio.to_thread(_discovery_due, device_id, now):
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

    if discovery_only:
        return {
            "status": "discovery_failed" if discovery and discovery.get("status") == "failed" else "discovered" if discovery else "idle",
            "discovery": discovery,
        }

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
