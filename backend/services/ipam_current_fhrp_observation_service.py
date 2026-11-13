"""Store and read replaceable current HSRP/VRRP observations for IPAM."""

from __future__ import annotations

import ipaddress
import json
import re
from datetime import datetime, timezone
from typing import Any

from core.interface_utils import normalize_interface_name


_PROTOCOLS = {"hsrp", "vrrp"}
_COLLECTION_STATUSES = {"complete", "partial", "failed", "unsupported"}
_MAC_SEPARATOR = ":"


def _normalize_protocol(value: Any) -> str:
    protocol = str(value or "").strip().lower()
    if protocol not in _PROTOCOLS:
        raise ValueError("protocol_invalid")
    return protocol


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


def _normalize_group_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("group_id_invalid")
    raw = "" if value is None else str(value).strip()
    if not re.fullmatch(r"\d+", raw):
        raise ValueError("group_id_invalid")
    return int(raw)


def _normalize_address_family(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("address_family_invalid")
    try:
        family = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("address_family_invalid") from exc
    if str(value).strip() not in {"0", "4", "6"} or family not in {0, 4, 6}:
        raise ValueError("address_family_invalid")
    return family


def _normalize_priority(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        raise ValueError("priority_invalid")
    raw = str(value).strip()
    if not re.fullmatch(r"\d+", raw):
        raise ValueError("priority_invalid")
    priority = int(raw)
    if not 0 <= priority <= 255:
        raise ValueError("priority_invalid")
    return priority


def _normalize_ip(value: Any, *, field: str, family: int) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        address = ipaddress.ip_address(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field}_invalid") from exc
    if family == 0 or address.version != family:
        raise ValueError(f"{field}_family_mismatch")
    return str(address)


def _normalize_mac(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    raw = str(value).strip().lower()
    compact = raw.replace(":", "").replace("-", "").replace(".", "")
    if not re.fullmatch(r"[0-9a-f]{12}", compact):
        raise ValueError("virtual_mac_invalid")
    return _MAC_SEPARATOR.join(compact[index : index + 2] for index in range(0, 12, 2))


def _metadata_json(value: Any) -> str:
    if value is None:
        value = {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata_invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("metadata_invalid")
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata_invalid") from exc


def _normalize_observation(
    record: dict[str, Any],
    *,
    device_id: str,
    protocol: str,
    generation: int,
    observed_at: str,
    run_id: str,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("observation_invalid")
    group_id = _normalize_group_id(record.get("group_id"))
    address_family = _normalize_address_family(record.get("address_family"))
    interface_name = str(
        record.get("interface_name") or record.get("interface") or ""
    ).strip()
    if not interface_name:
        raise ValueError("interface_name_required")
    normalized_interface_name = str(normalize_interface_name(interface_name) or "").strip().lower()
    if not normalized_interface_name:
        raise ValueError("interface_name_invalid")
    state = str(record.get("state") or "").strip().lower()
    if not state:
        raise ValueError("state_required")

    master_address = _normalize_ip(
        record.get("master_address"), field="master_address", family=address_family,
    )
    virtual_ip = _normalize_ip(
        record.get("virtual_ip"), field="virtual_ip", family=address_family,
    )
    virtual_mac = _normalize_mac(record.get("virtual_mac"))
    row_observed_at = _iso_datetime(
        record.get("observed_at") or observed_at,
        field="observed_at",
    )
    metadata = record.get("metadata_json", record.get("metadata"))

    return {
        "device_id": device_id,
        "protocol": protocol,
        "group_id": group_id,
        "address_family": address_family,
        "interface_name": interface_name,
        "normalized_interface_name": normalized_interface_name,
        "priority": _normalize_priority(record.get("priority")),
        "state": state,
        "master_address": master_address,
        "virtual_ip": virtual_ip,
        "virtual_ip_key": virtual_ip or "",
        "virtual_mac": virtual_mac,
        "generation": generation,
        "observed_at": row_observed_at,
        "run_id": str(record.get("run_id") or run_id or "").strip(),
        "metadata_json": _metadata_json(metadata),
    }


def begin_current_fhrp_collection(
    conn,
    *,
    device_id: str,
    protocol: str,
    attempted_at: str | datetime,
    run_id: str = "",
) -> int:
    """Reserve a per-device/protocol generation before any device I/O."""
    normalized_device_id = str(device_id or "").strip()
    if not normalized_device_id:
        raise ValueError("device_id_required")
    normalized_protocol = _normalize_protocol(protocol)
    attempted = _iso_datetime(attempted_at, field="attempted_at")
    normalized_run_id = str(run_id or "").strip()

    conn.execute(
        """INSERT INTO ipam_current_fhrp_collection_states (device_id, protocol)
             VALUES (?, ?)
             ON CONFLICT (device_id, protocol) DO NOTHING""",
        (normalized_device_id, normalized_protocol),
    )
    state = conn.execute(
        """SELECT latest_attempt_generation
             FROM ipam_current_fhrp_collection_states
            WHERE device_id = ? AND protocol = ?
            FOR UPDATE""",
        (normalized_device_id, normalized_protocol),
    ).fetchone()
    generation = int(state["latest_attempt_generation"] or 0) + 1
    conn.execute(
        """UPDATE ipam_current_fhrp_collection_states
              SET latest_attempt_generation = ?, latest_status = 'running',
                  last_attempt_at = ?, last_run_id = ?, last_error_code = '',
                  updated_at = CURRENT_TIMESTAMP
            WHERE device_id = ? AND protocol = ?""",
        (generation, attempted, normalized_run_id, normalized_device_id, normalized_protocol),
    )
    return generation


def finish_current_fhrp_collection(
    conn,
    *,
    device_id: str,
    protocol: str,
    generation: int,
    status: str,
    attempted_at: str | datetime,
    completed_at: str | datetime,
    observations: list[dict[str, Any]] | None = None,
    run_id: str = "",
    error_code: str = "",
) -> int:
    """Replace one device/protocol only on a complete snapshot."""
    normalized_device_id = str(device_id or "").strip()
    if not normalized_device_id:
        raise ValueError("device_id_required")
    normalized_protocol = _normalize_protocol(protocol)
    if isinstance(generation, bool):
        raise ValueError("generation_invalid")
    try:
        normalized_generation = int(generation)
    except (TypeError, ValueError) as exc:
        raise ValueError("generation_invalid") from exc
    if normalized_generation < 1 or str(generation).strip() != str(normalized_generation):
        raise ValueError("generation_invalid")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in _COLLECTION_STATUSES:
        raise ValueError("collection_status_invalid")
    attempted = _iso_datetime(attempted_at, field="attempted_at")
    completed = _iso_datetime(completed_at, field="completed_at")
    if not isinstance(observations, (list, type(None))):
        raise ValueError("observations_invalid")
    input_rows = observations or []
    if normalized_status != "complete" and input_rows:
        raise ValueError("incomplete_snapshot_must_not_include_observations")

    normalized_rows = [
        _normalize_observation(
            item,
            device_id=normalized_device_id,
            protocol=normalized_protocol,
            generation=normalized_generation,
            observed_at=completed,
            run_id=run_id,
        )
        for item in input_rows
    ] if normalized_status == "complete" else []
    identities = {
        (
            row["device_id"], row["protocol"], row["address_family"], row["group_id"],
            row["normalized_interface_name"], row["virtual_ip_key"],
        )
        for row in normalized_rows
    }
    if len(identities) != len(normalized_rows):
        raise ValueError("duplicate_observation_identity")

    state = conn.execute(
        """SELECT latest_attempt_generation, latest_status, current_row_count
             FROM ipam_current_fhrp_collection_states
            WHERE device_id = ? AND protocol = ?
            FOR UPDATE""",
        (normalized_device_id, normalized_protocol),
    ).fetchone()
    if (
        not state
        or int(state["latest_attempt_generation"] or 0) != normalized_generation
        or str(state["latest_status"] or "") != "running"
    ):
        raise ValueError("collection_generation_superseded")

    if normalized_status == "complete":
        conn.execute(
            """DELETE FROM ipam_current_fhrp_observations
                WHERE device_id = ? AND protocol = ?""",
            (normalized_device_id, normalized_protocol),
        )
        for row in normalized_rows:
            conn.execute(
                """INSERT INTO ipam_current_fhrp_observations (
                       device_id, protocol, group_id, address_family,
                       interface_name, normalized_interface_name, priority, state,
                       master_address, virtual_ip, virtual_ip_key, virtual_mac,
                       generation, observed_at, run_id, metadata_json
                   ) VALUES (
                       ?, ?, ?, ?, ?, ?, ?, ?, ?::inet, ?::inet, ?, ?,
                       ?, ?, ?, ?::jsonb
                   )""",
                (
                    row["device_id"], row["protocol"], row["group_id"], row["address_family"],
                    row["interface_name"], row["normalized_interface_name"], row["priority"],
                    row["state"], row["master_address"], row["virtual_ip"],
                    row["virtual_ip_key"], row["virtual_mac"], row["generation"],
                    row["observed_at"], row["run_id"], row["metadata_json"],
                ),
            )

    normalized_run_id = str(run_id or "").strip()
    normalized_error_code = str(error_code or "").strip()
    conn.execute(
        """UPDATE ipam_current_fhrp_collection_states
              SET latest_status = ?, last_attempt_at = ?, last_completed_at = ?,
                  last_run_id = ?, last_error_code = ?,
                  last_success_generation = CASE WHEN ? THEN ? ELSE last_success_generation END,
                  last_success_at = CASE WHEN ? THEN ? ELSE last_success_at END,
                  current_row_count = CASE WHEN ? THEN ? ELSE current_row_count END,
                  updated_at = CURRENT_TIMESTAMP
            WHERE device_id = ? AND protocol = ?""",
        (
            normalized_status, attempted, completed, normalized_run_id, normalized_error_code,
            normalized_status == "complete", normalized_generation,
            normalized_status == "complete", completed,
            normalized_status == "complete", len(normalized_rows),
            normalized_device_id, normalized_protocol,
        ),
    )
    if normalized_status == "complete":
        return len(normalized_rows)
    return int(state["current_row_count"] or 0)


def list_current_fhrp_observations(
    conn,
    *,
    device_id: str | None = None,
    device_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    protocol: str | None = None,
) -> list[dict[str, Any]]:
    """List the replaceable current FHRP rows, without resolving address scope."""
    filters: list[str] = []
    params: list[Any] = []
    if device_id is not None:
        normalized_device_id = str(device_id or "").strip()
        if not normalized_device_id:
            raise ValueError("device_id_required")
        filters.append("device_id = ?")
        params.append(normalized_device_id)
    if device_ids is not None:
        normalized_device_ids = sorted({str(value or "").strip() for value in device_ids if str(value or "").strip()})
        if not normalized_device_ids:
            return []
        filters.append(f"device_id IN ({', '.join('?' for _ in normalized_device_ids)})")
        params.extend(normalized_device_ids)
    if protocol is not None:
        filters.append("protocol = ?")
        params.append(_normalize_protocol(protocol))
    where_sql = f" WHERE {' AND '.join(filters)}" if filters else ""
    rows = conn.execute(
        f"""SELECT device_id, protocol, group_id, address_family,
                   interface_name, normalized_interface_name, priority, state,
                   master_address, virtual_ip, virtual_ip_key, virtual_mac,
                   generation, observed_at, run_id, metadata_json
              FROM ipam_current_fhrp_observations{where_sql}
             ORDER BY device_id, protocol, address_family, group_id,
                      normalized_interface_name, virtual_ip_key""",
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]


def get_current_fhrp_collection_states(
    conn,
    *,
    device_id: str | None = None,
    device_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    protocol: str | None = None,
) -> list[dict[str, Any]]:
    """Return the latest attempt and last successful generation per pair."""
    filters: list[str] = []
    params: list[Any] = []
    if device_id is not None:
        normalized_device_id = str(device_id or "").strip()
        if not normalized_device_id:
            raise ValueError("device_id_required")
        filters.append("device_id = ?")
        params.append(normalized_device_id)
    if device_ids is not None:
        normalized_device_ids = sorted({str(value or "").strip() for value in device_ids if str(value or "").strip()})
        if not normalized_device_ids:
            return []
        filters.append(f"device_id IN ({', '.join('?' for _ in normalized_device_ids)})")
        params.extend(normalized_device_ids)
    if protocol is not None:
        filters.append("protocol = ?")
        params.append(_normalize_protocol(protocol))
    where_sql = f" WHERE {' AND '.join(filters)}" if filters else ""
    rows = conn.execute(
        f"""SELECT device_id, protocol, latest_attempt_generation, latest_status,
                   last_attempt_at, last_completed_at, last_success_generation,
                   last_success_at, current_row_count, last_error_code, last_run_id,
                   updated_at
              FROM ipam_current_fhrp_collection_states{where_sql}
             ORDER BY device_id, protocol""",
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]
