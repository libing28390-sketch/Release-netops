"""Collect and persist current IPv6 neighbors without touching discovery history."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from services.ipam_current_endpoint_observation_service import (
    begin_current_endpoint_collection,
    finish_current_endpoint_collection,
)
from services.snmp_collection_policy_service import is_snmp_collection_enabled
from services import snmp_service, vault_service


logger = logging.getLogger(__name__)

_SOURCE = "ndp"
_UNKNOWN_CONTEXT = {
    "context_source": "snmp",
    "context_type": "unknown",
    "local_context_key": "",
    "local_context_name": "",
}
_DEVICE_SELECT = """
    SELECT id, hostname, ip_address, status, platform, snmp_collection_enabled,
           snmp_port, snmp_credential_id, credential_id, admin_credential_id,
           asset_id, credential_source, vault_path, snmp_community,
           auth_model, username, password, normal_username, normal_password,
           admin_username, admin_password, enable_password
      FROM devices
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _version_key(profile: dict[str, Any]) -> str:
    value = str(profile.get("version") or "2c").strip().casefold()
    if value in {"3", "v3", "snmpv3"}:
        return "3"
    if value in {"1", "v1", "snmpv1"}:
        return "1"
    return "2c"


def _load_current_collection_inputs(
    device_ids: set[str] | None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    conn = get_db_connection()
    try:
        sql = _DEVICE_SELECT
        params: tuple[Any, ...] = ()
        if device_ids is not None:
            if not device_ids:
                return [], {}
            placeholders = ", ".join("?" for _ in device_ids)
            sql += f" WHERE id IN ({placeholders})"
            params = tuple(sorted(device_ids))
        sql += " ORDER BY hostname, id"
        devices = [dict(row) for row in conn.execute(sql, params).fetchall()]
        if not devices:
            return [], {}
        selected_ids = [str(row["id"]) for row in devices]
        placeholders = ", ".join("?" for _ in selected_ids)
        mapping_rows = conn.execute(
            f"""SELECT device_id, context_type, local_context_key, local_context_name
                  FROM ipam_device_routing_contexts
                 WHERE context_source = 'snmp' AND status = 'active'
                   AND device_id IN ({placeholders})
                 ORDER BY device_id, context_type, local_context_key""",
            tuple(selected_ids),
        ).fetchall()
        contexts: dict[str, list[dict[str, Any]]] = {}
        for row in mapping_rows:
            mapping = dict(row)
            contexts.setdefault(str(mapping["device_id"]), []).append(mapping)
        return devices, contexts
    finally:
        conn.close()


def _context_specs(
    mappings: list[dict[str, Any]],
    *,
    version: str,
    profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """Build one request per context key and retain ambiguous keys as unknown."""
    if version != "3":
        # v1/v2c has no SNMP context selection, so it cannot cover any active
        # routing-context mapping, even when a mapping is named Global.
        return [{**_UNKNOWN_CONTEXT, "request_context_name": ""}], len(mappings)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for mapping in mappings:
        key = str(mapping.get("local_context_key") or "").strip()
        grouped.setdefault(key, []).append(mapping)

    specs: list[dict[str, Any]] = []
    uncovered = 0
    for key, candidates in sorted(grouped.items()):
        uniquely_mapped = len(candidates) == 1
        mapping = candidates[0] if uniquely_mapped else {}
        mapping_type = str(mapping.get("context_type") or "").strip().lower()
        is_mapped = uniquely_mapped and mapping_type in {"vrf", "global"} and bool(key)
        if not is_mapped:
            # The SNMP context key is still exact and can be collected once,
            # but multiple address-space mappings make its scope ambiguous.
            uncovered += len(candidates)
        specs.append({
            "context_source": "snmp",
            "context_type": mapping_type if is_mapped else "unknown",
            "local_context_key": key,
            "local_context_name": (
                str(mapping.get("local_context_name") or "").strip() if is_mapped else ""
            ),
            "request_context_name": key,
            "mapping_count": len(candidates),
            "mapped_unique": bool(is_mapped),
        })

    configured_context = str(profile.get("context_name") or "").strip()
    if configured_context and configured_context not in grouped:
        specs.append({
            "context_source": "snmp",
            "context_type": "unknown",
            "local_context_key": configured_context,
            "local_context_name": "",
            "request_context_name": configured_context,
            "mapping_count": 0,
            "mapped_unique": False,
        })
    if not specs:
        specs.append({
            **_UNKNOWN_CONTEXT,
            "request_context_name": configured_context,
            "mapping_count": 0,
            "mapped_unique": False,
        })
    return specs, uncovered


def _reserve_generations(
    *,
    device_id: str,
    context_specs: list[dict[str, Any]],
    attempted_at: str,
    run_id: str,
) -> dict[tuple[str, str, str], int]:
    conn = get_db_connection()
    try:
        generations: dict[tuple[str, str, str], int] = {}
        for spec in context_specs:
            identity = (
                str(spec["context_source"]),
                str(spec["context_type"]),
                str(spec["local_context_key"]),
            )
            generations[identity] = begin_current_endpoint_collection(
                conn,
                device_id=device_id,
                observation_source=_SOURCE,
                context_source=identity[0],
                context_type=identity[1],
                local_context_key=identity[2],
                attempted_at=attempted_at,
                run_id=run_id,
            )
        # Fence old runs before the first SNMP request is made.
        conn.commit()
        return generations
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _finish_context(
    *,
    device_id: str,
    spec: dict[str, Any],
    generation: int,
    status: str,
    attempted_at: str,
    completed_at: str,
    observations: list[dict[str, Any]] | None,
    run_id: str,
    error_code: str = "",
) -> int:
    conn = get_db_connection()
    try:
        row_count = finish_current_endpoint_collection(
            conn,
            device_id=device_id,
            observation_source=_SOURCE,
            context_source=str(spec["context_source"]),
            context_type=str(spec["context_type"]),
            local_context_key=str(spec["local_context_key"]),
            generation=generation,
            status=status,
            attempted_at=attempted_at,
            completed_at=completed_at,
            observations=observations,
            run_id=run_id,
            error_code=error_code,
        )
        conn.commit()
        return row_count
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _failure_status(error: Exception) -> tuple[str, str]:
    kind = type(error).__name__.casefold()
    message = str(error).casefold()
    if any(marker in f"{kind} {message}" for marker in (
        "nosuchname", "nosuchobject", "nosuchinstance", "unknownobjectidentifier",
        "notimplemented", "unsupported",
    )):
        return "unsupported", "snmp_table_unsupported"
    if any(marker in message for marker in (
        "incomplete", "do not cover the same row", "malformed", "invalid",
        "did not map", "duplicate row keys",
    )):
        return "partial", "snmp_table_partial"
    return "failed", "snmp_collection_failed"


def _normalized_observations(
    records: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for record in records:
        observations.append({
            "ip_address": record["ip_address"],
            "mac_address": record["mac_address"],
            "interface_name": record["interface"],
            "context_source": spec["context_source"],
            "context_type": spec["context_type"],
            "local_context_key": spec["local_context_key"],
            "local_context_name": spec["local_context_name"],
            # IP-MIB does not expose a VLAN here. Keep it NULL instead of
            # deriving a VLAN from the interface label.
            "vlan_id": None,
            "metadata": {
                "collector": "ip-mib.ipNetToPhysicalTable",
                "if_index": record["if_index"],
                "inet_address_type": record["inet_address_type"],
                "zone_index": record["zone_index"],
                "neighbor_type": record["type"],
                "neighbor_state": record["state"],
            },
        })
    return observations


def _collect_context(
    *,
    device: dict[str, Any],
    spec: dict[str, Any],
    generation: int,
    profile: dict[str, Any],
    configured: bool,
    version: str,
    attempted_at: str,
    run_id: str,
) -> dict[str, Any]:
    device_id = str(device["id"])
    context_type = str(spec["context_type"])
    context_key = str(spec["local_context_key"])
    result: dict[str, Any] = {
        "device_id": device_id,
        "context_type": context_type,
        "local_context_key": context_key,
        "status": "failed",
        "entry_count": 0,
    }
    if not configured:
        error_code = "snmp_not_configured"
        _finish_context(
            device_id=device_id, spec=spec, generation=generation,
            status="failed", attempted_at=attempted_at, completed_at=_utc_now(),
            observations=None, run_id=run_id, error_code=error_code,
        )
        result.update({"error_code": error_code})
        return result

    target_ip = str(profile.get("server") or device.get("ip_address") or "").strip()
    if not target_ip:
        error_code = "snmp_target_missing"
        _finish_context(
            device_id=device_id, spec=spec, generation=generation,
            status="failed", attempted_at=attempted_at, completed_at=_utc_now(),
            observations=None, run_id=run_id, error_code=error_code,
        )
        result.update({"error_code": error_code})
        return result

    community_or_profile: str | dict[str, Any]
    if version == "3":
        community_or_profile = dict(profile)
        community_or_profile["context_name"] = str(spec.get("request_context_name") or "")
    else:
        community_or_profile = str(profile.get("community") or "")
    try:
        records = asyncio.run(snmp_service.collect_ipv6_neighbor_table(
            target_ip,
            community_or_profile,
            port=int(profile.get("port") or device.get("snmp_port") or 161),
            version=version,
        ))
        status = "complete" if context_type != "unknown" else "scope_unknown"
        observations = _normalized_observations(records, spec=spec)
        row_count = _finish_context(
            device_id=device_id, spec=spec, generation=generation,
            status=status, attempted_at=attempted_at, completed_at=_utc_now(),
            observations=observations, run_id=run_id,
        )
        result.update({"status": status, "entry_count": row_count})
        return result
    except ValueError as exc:
        # A slower run must never overwrite a newer generation's state.
        if str(exc) == "collection_generation_superseded":
            result.update({"status": "superseded", "error_code": "generation_superseded"})
            return result
        error_status, error_code = _failure_status(exc)
        result.update({"status": error_status, "error_code": error_code})
    except Exception as exc:  # noqa: BLE001
        error_status, error_code = _failure_status(exc)
        logger.info(
            "Current IPv6 neighbor collection failed for device %s (%s)",
            device_id,
            type(exc).__name__,
        )
        result.update({"status": error_status, "error_code": error_code})

    try:
        _finish_context(
            device_id=device_id, spec=spec, generation=generation,
            status=result["status"], attempted_at=attempted_at, completed_at=_utc_now(),
            observations=None, run_id=run_id, error_code=result["error_code"],
        )
    except ValueError as exc:
        if str(exc) == "collection_generation_superseded":
            result.update({"status": "superseded", "error_code": "generation_superseded"})
            return result
        raise
    return result


def run_current_ndp_collection(
    *,
    device_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    collection_run_id: str = "",
) -> dict[str, Any]:
    """Refresh the replaceable current IPv6 neighbor projection only.

    This service deliberately does not invoke any discovery-history projector
    or read, clear, or backfill historical IPAM observations.
    """
    normalized_ids = None if device_ids is None else {
        str(device_id).strip() for device_id in device_ids if str(device_id).strip()
    }
    devices, mappings_by_device = _load_current_collection_inputs(normalized_ids)
    run_id = str(collection_run_id or uuid.uuid4())
    results: list[dict[str, Any]] = []
    total_contexts = 0
    total_entries = 0
    uncovered_contexts = 0
    skipped_contexts = 0
    skipped_devices = 0
    eligible_devices = 0

    for device in devices:
        device_id = str(device.get("id") or "").strip()
        mappings = mappings_by_device.get(device_id, [])
        if str(device.get("status") or "").strip().casefold() != "online":
            skipped_contexts += len(mappings)
            skipped_devices += 1
            results.append({
                "device_id": device_id,
                "status": "skipped",
                "context_count": 0,
                "uncovered_contexts": len(mappings),
                "entry_count": 0,
            })
            continue
        if not is_snmp_collection_enabled(device):
            skipped_contexts += len(mappings)
            skipped_devices += 1
            results.append({
                "device_id": device_id,
                "status": "skipped",
                "context_count": 0,
                "uncovered_contexts": len(mappings),
                "entry_count": 0,
                "error_code": "snmp_collection_disabled",
            })
            continue

        try:
            profile = dict((vault_service.resolve_collector_credentials(device).get("snmp") or {}))
            credential_error = ""
        except Exception as exc:  # noqa: BLE001
            profile = {}
            credential_error = type(exc).__name__
        if credential_error or not profile.get("configured"):
            uncovered = len(mappings)
            uncovered_contexts += uncovered
            skipped_devices += 1
            result_status = "partial" if uncovered else "skipped"
            results.append({
                "device_id": device_id,
                "status": result_status,
                "context_count": 0,
                "uncovered_contexts": uncovered,
                "entry_count": 0,
                "error_code": (
                    "credential_resolution_failed" if credential_error
                    else "snmp_not_configured"
                ),
            })
            continue
        eligible_devices += 1
        version = _version_key(profile)
        specs, uncovered = _context_specs(mappings, version=version, profile=profile)
        attempted_at = _utc_now()
        try:
            generations = _reserve_generations(
                device_id=device_id,
                context_specs=specs,
                attempted_at=attempted_at,
                run_id=run_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Unable to reserve current IPv6 neighbor generations for device %s (%s)",
                device_id,
                type(exc).__name__,
            )
            skipped_contexts += len(mappings)
            results.append({
                "device_id": device_id,
                "status": "failed",
                "context_count": 0,
                "uncovered_contexts": len(mappings),
                "entry_count": 0,
                "error_code": "generation_reservation_failed",
            })
            continue

        context_results: list[dict[str, Any]] = []
        for spec in specs:
            identity = (
                str(spec["context_source"]),
                str(spec["context_type"]),
                str(spec["local_context_key"]),
            )
            generation = generations[identity]
            context_result = _collect_context(
                device=device,
                spec=spec,
                generation=generation,
                profile=profile,
                configured=True,
                version=version,
                attempted_at=attempted_at,
                run_id=run_id,
            )
            context_results.append(context_result)
            total_contexts += 1
            total_entries += int(context_result.get("entry_count") or 0)

        uncovered_contexts += uncovered
        context_failed = any(
            item.get("status") not in {"complete", "scope_unknown"}
            for item in context_results
        )
        result_status = "partial" if context_failed or uncovered else (
            "scope_unknown" if any(item.get("status") == "scope_unknown" for item in context_results)
            else "complete"
        )
        results.append({
            "device_id": device_id,
            "status": result_status,
            "context_count": len(context_results),
            "uncovered_contexts": uncovered,
            "entry_count": sum(int(item.get("entry_count") or 0) for item in context_results),
            "context_results": context_results,
        })

    overall_partial = uncovered_contexts > 0 or skipped_contexts > 0 or skipped_devices > 0 or any(
        item.get("status") not in {"complete", "scope_unknown", "skipped"}
        for item in results
    )
    not_collected = (
        total_contexts == 0
        and uncovered_contexts == 0
        and skipped_contexts == 0
        and all(item.get("status") == "skipped" for item in results)
    )
    if not devices or not_collected:
        status = "skipped"
        coverage_status = "not_collected"
    elif overall_partial:
        status = "partial"
        coverage_status = "partial"
    elif any(item.get("status") == "scope_unknown" for item in results):
        status = "success"
        coverage_status = "scope_unknown"
    else:
        status = "success"
        coverage_status = "complete"
    return {
        "collection_run_id": run_id,
        "status": status,
        "coverage_status": coverage_status,
        "devices_seen": len(devices),
        "eligible_devices": eligible_devices,
        "devices_skipped": skipped_devices,
        "contexts_attempted": total_contexts,
        "contexts_uncovered": uncovered_contexts + skipped_contexts,
        "collected_entries": total_entries,
        "device_results": results,
    }
