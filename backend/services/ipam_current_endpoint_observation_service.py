"""Persist the current successful per-device endpoint observation projection.

This module stores replaceable current ARP and IPv6 ND projections plus one
collection-state row per device/source/context. It does not read or retain IPAM
discovery history. Routing-context mappings are resolved by exact identity at
read time so an unknown context never becomes Global implicitly.
"""

from __future__ import annotations

import ipaddress
import json
import re
from datetime import datetime, timezone
from typing import Any

from core.interface_utils import normalize_interface_name


_ADDRESS_OBSERVATION_SOURCES = {"arp", "ndp"}
_COLLECTION_STATUSES = {
    "running", "complete", "partial", "failed", "unsupported", "scope_unknown",
}
_REPLACE_STATUSES = {"complete", "scope_unknown"}
_CONTEXT_SOURCES = {"cli", "snmp"}
_CONTEXT_TYPES = {"vrf", "global", "unknown"}


def _iso_datetime(value: Any, *, field: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field}_required")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field}_timezone_required")
    return parsed.astimezone(timezone.utc).isoformat()


def _metadata_json(value: Any) -> str:
    try:
        return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata_invalid") from exc


def _normalize_mac(value: Any) -> str:
    raw = str(value or "").strip().lower()
    hex_digits = re.sub(r"[^0-9a-f]", "", raw)
    unseparated = raw.replace(":", "").replace("-", "").replace(".", "")
    if len(hex_digits) not in {12, 16} or len(hex_digits) != len(unseparated):
        raise ValueError("mac_address_invalid")
    return hex_digits


def _normalize_vlan_key(record: dict[str, Any]) -> int:
    raw = record.get("vlan_key")
    if raw is None:
        raw = record.get("vlan_id")
    if raw is None:
        raw = record.get("vlan")
    if raw is None or str(raw).strip() == "":
        return 0
    try:
        vlan_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("vlan_id_invalid") from exc
    if not 1 <= vlan_id <= 4094:
        raise ValueError("vlan_id_invalid")
    return vlan_id


def _normalize_observation(
    record: dict[str, Any],
    *,
    device_id: str,
    observation_source: str,
    generation: int,
    observed_at: str,
    run_id: str,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("observation_invalid")
    try:
        parsed_address = ipaddress.ip_address(str(record.get("ip_address") or record.get("ip") or "").strip())
    except ValueError as exc:
        raise ValueError("ip_address_invalid") from exc
    if observation_source == "arp" and parsed_address.version != 4:
        raise ValueError("arp_requires_ipv4")
    if observation_source == "ndp" and parsed_address.version != 6:
        raise ValueError("ndp_requires_ipv6")
    address = str(parsed_address)

    mac = _normalize_mac(record.get("mac_address") or record.get("mac") or record.get("mac_raw"))
    context_source = str(record.get("context_source") or "cli").strip().lower()
    context_type = str(record.get("context_type") or "unknown").strip().lower()
    local_context_key = str(record.get("local_context_key") or "").strip()
    if context_source not in _CONTEXT_SOURCES:
        raise ValueError("context_source_invalid")
    if context_type not in _CONTEXT_TYPES:
        raise ValueError("context_type_invalid")
    if context_type in {"vrf", "global"} and not local_context_key:
        raise ValueError("known_context_key_required")

    interface_name = str(record.get("interface_name") or record.get("interface") or "").strip()
    normalized_interface_name = normalize_interface_name(interface_name).strip().lower()
    vlan_key = _normalize_vlan_key(record)
    row_observed_at = _iso_datetime(record.get("observed_at") or observed_at, field="observed_at")
    metadata = record.get("metadata_json", record.get("metadata"))
    if isinstance(metadata, str):
        try:
            decoded = json.loads(metadata)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata_invalid") from exc
        metadata = decoded

    return {
        "source_device_id": device_id,
        "observation_source": observation_source,
        "context_source": context_source,
        "context_type": context_type,
        "local_context_key": local_context_key,
        "local_context_name": str(record.get("local_context_name") or "").strip(),
        "ip_address": address,
        "mac_address": mac,
        "interface_name": interface_name,
        "normalized_interface_name": normalized_interface_name,
        # Zero is a storage sentinel for an unknown VLAN; API readers should
        # expose it as NULL rather than as a VLAN ID.
        "vlan_key": vlan_key,
        "generation": generation,
        "observed_at": row_observed_at,
        "run_id": str(record.get("run_id") or run_id or "").strip(),
        "metadata_json": _metadata_json(metadata),
    }


def _normalize_context_identity(
    context_source: str,
    context_type: str,
    local_context_key: str,
) -> tuple[str, str, str]:
    source = str(context_source or "").strip().lower()
    kind = str(context_type or "").strip().lower()
    key = str(local_context_key or "").strip()
    if source not in _CONTEXT_SOURCES:
        raise ValueError("context_source_invalid")
    if kind not in _CONTEXT_TYPES:
        raise ValueError("context_type_invalid")
    if kind in {"vrf", "global"} and not key:
        raise ValueError("known_context_key_required")
    return source, kind, key


def _normalize_observation_source(value: Any) -> str:
    source = str(value or "").strip().lower()
    if source not in _ADDRESS_OBSERVATION_SOURCES:
        raise ValueError("observation_source_invalid")
    return source


def _ensure_state_row(
    conn,
    device_id: str,
    observation_source: str,
    context_source: str,
    context_type: str,
    local_context_key: str,
) -> None:
    conn.execute(
        """INSERT INTO ipam_endpoint_collection_states (
                   device_id, observation_source, context_source, context_type,
                   local_context_key
               ) VALUES (?, ?, ?, ?, ?)
             ON CONFLICT (
                 device_id, observation_source, context_source,
                 context_type, local_context_key
             ) DO NOTHING""",
        (
            device_id, observation_source, context_source,
            context_type, local_context_key,
        ),
    )


def begin_current_endpoint_collection(
    conn,
    *,
    device_id: str,
    observation_source: str = "arp",
    context_source: str = "cli",
    context_type: str = "unknown",
    local_context_key: str = "",
    attempted_at: str | datetime,
    run_id: str = "",
) -> int:
    """Reserve the next device/source generation before collection starts.

    The caller owns and commits the transaction. Reserving before device I/O
    fences a slower older run from replacing a newer result.
    """
    normalized_device_id = str(device_id or "").strip()
    if not normalized_device_id:
        raise ValueError("device_id_required")
    normalized_source = _normalize_observation_source(observation_source)
    normalized_context = _normalize_context_identity(
        context_source, context_type, local_context_key,
    )
    attempted = _iso_datetime(attempted_at, field="attempted_at")
    _ensure_state_row(conn, normalized_device_id, normalized_source, *normalized_context)
    row = conn.execute(
        """SELECT latest_attempt_generation
             FROM ipam_endpoint_collection_states
            WHERE device_id = ? AND observation_source = ?
              AND context_source = ? AND context_type = ? AND local_context_key = ?
            FOR UPDATE""",
        (normalized_device_id, normalized_source, *normalized_context),
    ).fetchone()
    generation = int(row["latest_attempt_generation"] or 0) + 1
    conn.execute(
        """UPDATE ipam_endpoint_collection_states
              SET latest_attempt_generation = ?, latest_status = 'running',
                  last_attempt_at = ?, last_run_id = ?, last_error_code = '',
                  updated_at = CURRENT_TIMESTAMP
            WHERE device_id = ? AND observation_source = ?
              AND context_source = ? AND context_type = ? AND local_context_key = ?""",
        (
            generation, attempted, str(run_id or "").strip(), normalized_device_id,
            normalized_source, *normalized_context,
        ),
    )
    return generation


def finish_current_endpoint_collection(
    conn,
    *,
    device_id: str,
    observation_source: str = "arp",
    context_source: str = "cli",
    context_type: str = "unknown",
    local_context_key: str = "",
    generation: int,
    status: str,
    attempted_at: str | datetime,
    completed_at: str | datetime,
    observations: list[dict[str, Any]] | None = None,
    run_id: str = "",
    error_code: str = "",
) -> int:
    """Record an attempt and atomically replace rows for complete snapshots.

    ``complete`` and ``scope_unknown`` both represent a fully parsed current
    host set. Unknown-context rows are retained with an empty local key and
    will not match any explicit routing-context mapping. ``partial``,
    ``failed`` and ``unsupported`` leave the last successful rows untouched.
    The caller owns commit/rollback for the full transaction.
    """
    normalized_device_id = str(device_id or "").strip()
    if not normalized_device_id:
        raise ValueError("device_id_required")
    normalized_source = _normalize_observation_source(observation_source)
    normalized_context = _normalize_context_identity(
        context_source, context_type, local_context_key,
    )
    try:
        normalized_generation = int(generation)
    except (TypeError, ValueError) as exc:
        raise ValueError("generation_invalid") from exc
    if normalized_generation < 1:
        raise ValueError("generation_invalid")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in _COLLECTION_STATUSES - {"running"}:
        raise ValueError("collection_status_invalid")
    if normalized_status == "scope_unknown" and normalized_context[1] != "unknown":
        raise ValueError("scope_unknown_requires_unknown_context")
    if normalized_status == "complete" and normalized_context[1] == "unknown":
        raise ValueError("unknown_context_requires_scope_unknown")
    attempted = _iso_datetime(attempted_at, field="attempted_at")
    completed = _iso_datetime(completed_at, field="completed_at")
    input_rows = observations or []
    if not isinstance(input_rows, list):
        raise ValueError("observations_invalid")
    if normalized_status not in _REPLACE_STATUSES and input_rows:
        raise ValueError("incomplete_snapshot_must_not_include_observations")

    normalized_rows = [
        _normalize_observation(
            item,
            device_id=normalized_device_id,
            observation_source=normalized_source,
            generation=normalized_generation,
            observed_at=completed,
            run_id=run_id,
        )
        for item in input_rows
    ] if normalized_status in _REPLACE_STATUSES else []
    if any(
        (
            row["context_source"], row["context_type"], row["local_context_key"],
        ) != normalized_context
        for row in normalized_rows
    ):
        raise ValueError("observation_context_mismatch")
    row_identities = {
        (
            row["context_source"], row["context_type"], row["local_context_key"],
            row["ip_address"], row["mac_address"], row["normalized_interface_name"],
            row["vlan_key"],
        )
        for row in normalized_rows
    }
    if len(row_identities) != len(normalized_rows):
        raise ValueError("duplicate_observation_identity")

    state = conn.execute(
        """SELECT latest_attempt_generation, latest_status, current_row_count
             FROM ipam_endpoint_collection_states
            WHERE device_id = ? AND observation_source = ?
              AND context_source = ? AND context_type = ? AND local_context_key = ?
            FOR UPDATE""",
        (normalized_device_id, normalized_source, *normalized_context),
    ).fetchone()
    if (
        not state
        or int(state["latest_attempt_generation"] or 0) != normalized_generation
        or str(state["latest_status"] or "") != "running"
    ):
        raise ValueError("collection_generation_superseded")

    if normalized_status in _REPLACE_STATUSES:
        conn.execute(
            """DELETE FROM ipam_current_endpoint_observations
                WHERE source_device_id = ? AND observation_source = ?
                  AND context_source = ? AND context_type = ? AND local_context_key = ?""",
            (normalized_device_id, normalized_source, *normalized_context),
        )
        for row in normalized_rows:
            conn.execute(
                """INSERT INTO ipam_current_endpoint_observations (
                       source_device_id, observation_source, context_source,
                       context_type, local_context_key, local_context_name,
                       ip_address, mac_address, interface_name,
                       normalized_interface_name, vlan_key, generation,
                       observed_at, run_id, metadata_json
                   ) VALUES (
                       ?, ?, ?, ?, ?, ?, ?::inet, ?, ?, ?, ?, ?, ?, ?, ?::jsonb
                   )""",
                (
                    row["source_device_id"], row["observation_source"], row["context_source"],
                    row["context_type"], row["local_context_key"], row["local_context_name"],
                    row["ip_address"], row["mac_address"], row["interface_name"],
                    row["normalized_interface_name"], row["vlan_key"], row["generation"],
                    row["observed_at"], row["run_id"], row["metadata_json"],
                ),
            )

    conn.execute(
        """UPDATE ipam_endpoint_collection_states
              SET latest_status = ?, last_attempt_at = ?, last_run_id = ?,
                  last_error_code = ?,
                  last_success_generation = CASE WHEN ? THEN ? ELSE last_success_generation END,
                  last_success_at = CASE WHEN ? THEN ? ELSE last_success_at END,
                  current_row_count = CASE WHEN ? THEN ? ELSE current_row_count END,
                  updated_at = CURRENT_TIMESTAMP
            WHERE device_id = ? AND observation_source = ?
              AND context_source = ? AND context_type = ? AND local_context_key = ?""",
        (
            normalized_status, attempted, str(run_id or "").strip(), str(error_code or "").strip(),
            normalized_status in _REPLACE_STATUSES, normalized_generation,
            normalized_status in _REPLACE_STATUSES, completed,
            normalized_status in _REPLACE_STATUSES, len(normalized_rows),
            normalized_device_id, normalized_source, *normalized_context,
        ),
    )
    return len(normalized_rows) if normalized_status in _REPLACE_STATUSES else int(
        state["current_row_count"] or 0
    )


def list_current_endpoint_observations(
    conn,
    *,
    device_id: str | None = None,
    observation_source: str = "arp",
) -> list[dict[str, Any]]:
    """Read current ARP/ND rows and resolve only exact active context mappings."""
    normalized_source = _normalize_observation_source(observation_source)
    params: tuple[Any, ...] = (normalized_source,)
    device_filter = ""
    if device_id:
        device_filter = " AND observation.source_device_id = ?"
        params = (normalized_source, str(device_id))
    rows = conn.execute(
        f"""SELECT observation.source_device_id, observation.observation_source,
                   observation.context_source, observation.context_type,
                   observation.local_context_key, observation.local_context_name,
                   host(observation.ip_address) AS ip_address,
                   observation.mac_address, observation.interface_name,
                   observation.normalized_interface_name,
                   NULLIF(observation.vlan_key, 0) AS vlan_id,
                   observation.generation, observation.observed_at,
                   observation.run_id, observation.metadata_json,
                   state.latest_status, state.latest_attempt_generation,
                   state.last_attempt_at, state.last_success_generation,
                   state.last_success_at, state.current_row_count,
                   state.last_error_code,
                   device.hostname AS source_device_name,
                   COALESCE(NULLIF(btrim(device.tenant_id), ''), 'tenant-default') AS tenant_id,
                   device.site_id AS device_site_id, device.site AS device_site,
                   asset.site_id AS asset_site_id,
                   resolved_mapping.mapping_id AS routing_context_mapping_id,
                   resolved_mapping.address_space_id,
                   resolved_mapping.context_type AS resolved_context_type,
                   resolved_space.name AS address_space_name,
                   resolved_space.vrf_id AS mapped_vrf_id
              FROM ipam_current_endpoint_observations AS observation
              JOIN ipam_endpoint_collection_states AS state
                ON state.device_id = observation.source_device_id
               AND state.observation_source = observation.observation_source
               AND state.context_source = observation.context_source
               AND state.context_type = observation.context_type
               AND state.local_context_key = observation.local_context_key
               AND state.last_success_generation = observation.generation
              JOIN devices AS device
                ON device.id = observation.source_device_id
              LEFT JOIN physical_assets AS asset ON asset.id = device.asset_id
              LEFT JOIN LATERAL (
                  SELECT MIN(candidate.mapping_id) AS mapping_id,
                         MIN(candidate.address_space_id) AS address_space_id,
                         MIN(candidate.context_type) AS context_type
                    FROM (
                        SELECT mapping.id AS mapping_id,
                               address_space.id AS address_space_id,
                               mapping.context_type
                          FROM ipam_device_routing_contexts AS mapping
                          JOIN ipam_address_spaces AS address_space
                            ON address_space.id = mapping.address_space_id
                           AND address_space.status = 'active'
                           AND COALESCE(
                                   NULLIF(btrim(address_space.security_tenant_id), ''),
                                   'tenant-default'
                               ) = COALESCE(
                                   NULLIF(btrim(device.tenant_id), ''), 'tenant-default'
                               )
                           AND (
                               (mapping.context_type = 'global' AND address_space.kind = 'global')
                               OR (mapping.context_type = 'vrf' AND address_space.kind = 'vrf')
                           )
                         WHERE mapping.device_id = observation.source_device_id
                           AND mapping.context_source = observation.context_source
                           AND mapping.local_context_key = observation.local_context_key
                           AND mapping.status = 'active'
                           AND mapping.context_type IN ('vrf', 'global')
                           AND (
                               observation.context_type = 'unknown'
                               OR mapping.context_type = observation.context_type
                           )
                    ) AS candidate
                   HAVING COUNT(*) = 1
              ) AS resolved_mapping ON TRUE
              LEFT JOIN ipam_address_spaces AS resolved_space
                ON resolved_space.id = resolved_mapping.address_space_id
             WHERE observation.observation_source = ?{device_filter}
             ORDER BY observation.source_device_id, observation.ip_address,
                      observation.context_source, observation.context_type,
                      observation.local_context_key, observation.mac_address,
                      observation.normalized_interface_name""",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def get_current_endpoint_collection_states(
    conn,
    *,
    device_id: str | None = None,
    observation_source: str = "arp",
    context_source: str | None = None,
    context_type: str | None = None,
    local_context_key: str | None = None,
) -> list[dict[str, Any]]:
    """Return the latest attempt/success state per device/source/context."""
    normalized_source = _normalize_observation_source(observation_source)
    filters = ["observation_source = ?"]
    params: list[Any] = [normalized_source]
    if device_id:
        filters.append("device_id = ?")
        params.append(str(device_id))
    if context_source:
        filters.append("context_source = ?")
        params.append(str(context_source).strip().lower())
    if context_type:
        filters.append("context_type = ?")
        params.append(str(context_type).strip().lower())
    if local_context_key is not None:
        filters.append("local_context_key = ?")
        params.append(str(local_context_key).strip())
    rows = conn.execute(
        f"""SELECT * FROM ipam_endpoint_collection_states
             WHERE {' AND '.join(filters)}
             ORDER BY device_id, context_source, context_type, local_context_key""",
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]
