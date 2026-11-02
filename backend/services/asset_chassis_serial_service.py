"""Confirmed ENTITY-MIB chassis serial observations and asset projection."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from services.snmp_vendor_registry import normalize_asset_vendor


logger = logging.getLogger(__name__)

_ASSET_MEMBER_QUERY_BATCH_SIZE = 500
_AUTO_SERIAL_NUMBER_SOURCE = "snmp_entity_discovery"
_AUTO_SERIAL_NUMBER_SOURCES = {_AUTO_SERIAL_NUMBER_SOURCE, "snmp_entity_fixed_get"}
_SAFE_MESSAGES = {
    "synced": "机箱序列号信息已更新。",
    "partial": "已保存可确认的机箱信息，部分采集结果仍不完整。",
    "conflict": "机箱信息已保存，但资产序列号与现有资产冲突，未覆盖标量序列号。",
    "superseded": "资产或设备信息已变化，已忽略过期采集结果。",
    "failed": "机箱序列号采集或保存失败。",
}


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _valid_db_text(value: Any) -> str | None:
    """Return trimmed, UTF-8 encodable text that PostgreSQL can store safely."""
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    if raw is None:
        return ""
    if isinstance(raw, (bytes, bytearray, memoryview)):
        try:
            text = bytes(raw).decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
    else:
        text = str(raw)
    if "\x00" in text:
        return None
    if any(unicodedata.category(character) == "Cs" for character in text):
        return None
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    return text.strip()


async def read_chassis_serials(ip: str, settings: Mapping[str, Any], *, vendor: str = "") -> dict[str, Any]:
    """Read confirmed SN evidence without changing other asset identity fields."""
    from services.snmp_chassis_serial_reader import read_chassis_serials as read_snapshot

    return await read_snapshot(ip, settings, vendor=vendor)


def _row_value(row: Any, key: str, position: int, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        if hasattr(row, "keys"):
            return row[key]
        return row[position]
    except (IndexError, KeyError, TypeError):
        return default


def _sync_result(
    status: str,
    *,
    members_count: int = 0,
    serial_number: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "members_count": int(members_count),
        "synced_serial_number": serial_number,
        "serial_number_source": "",
        "message": _SAFE_MESSAGES[status],
    }


def _clean_member(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    index_value = raw.get("entity_index")
    if isinstance(index_value, bool) or not re.fullmatch(r"[0-9]+", str(index_value)):
        return None
    try:
        index = int(index_value)
    except (TypeError, ValueError):
        return None
    if not 0 < index <= 2147483647:
        return None
    serial_number = _valid_db_text(raw.get("serial_number"))
    if not serial_number or not _valid_serial_number(serial_number):
        return None
    fields: dict[str, str] = {}
    for key in ("entity_name", "entity_description", "model"):
        value = _valid_db_text(raw.get(key))
        fields[key] = value if value is not None else ""
    return {
        "entity_index": index,
        "serial_number": serial_number,
        **fields,
    }


def _valid_serial_number(value: str) -> bool:
    """Use the standalone collector's placeholder and printable-SN policy."""
    if len(value) > 128 or any(ord(character) < 32 for character in value):
        return False
    folded = " ".join(value.casefold().split())
    if folded in {
        "", "-", "--", "none", "null", "unknown", "n/a", "na", "not available",
        "not applicable", "no serial", "no serial number", "unspecified", "nil", "0",
        "to be filled by o.e.m.",
    } or folded.startswith(("no such ", "not available")):
        return False
    compact = re.sub(r"[\s:\-]", "", folded)
    return len(compact) >= 3 and re.fullmatch(r"0+|f+", compact) is None


def _confirmed_indexes(raw_indexes: Any) -> set[int]:
    if not isinstance(raw_indexes, Sequence) or isinstance(raw_indexes, (str, bytes)):
        return set()
    result: set[int] = set()
    for value in raw_indexes:
        if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
            continue
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 0 < index <= 2147483647:
            result.add(index)
    return result


def sync_asset_chassis_members(
    conn: Any,
    asset_id: str,
    snapshot: Mapping[str, Any],
    *,
    device_id: str,
    management_ip: str,
) -> dict[str, Any]:
    """Persist confirmed chassis observations inside the caller transaction."""
    normalized_asset_id = str(asset_id or "").strip()
    normalized_device_id = str(device_id or "").strip()
    normalized_ip = str(management_ip or "").strip()
    if not isinstance(snapshot, Mapping):
        return _sync_result("failed")

    asset_row = conn.execute(
        """SELECT id, asset_type, vendor, management_ip,
                  serial_number, serial_number_source, chassis_observed_at
             FROM physical_assets WHERE id = ? FOR UPDATE""",
        (normalized_asset_id,),
    ).fetchone()
    if asset_row is None:
        return _sync_result("superseded")

    # Keep the lock order aligned with other asset/device identity writers.
    device_row = conn.execute(
        """SELECT id, asset_id, ip_address, vendor, snmp_collection_enabled
             FROM devices WHERE id = ? FOR UPDATE""",
        (normalized_device_id,),
    ).fetchone()
    if device_row is None:
        return _sync_result("superseded")

    asset_type = str(_row_value(asset_row, "asset_type", 1, "") or "").strip().casefold()
    asset_vendor = normalize_asset_vendor(_row_value(asset_row, "vendor", 2, ""))
    current_asset_ip = str(_row_value(asset_row, "management_ip", 3, "") or "").strip()
    current_serial = str(_row_value(asset_row, "serial_number", 4, "") or "")
    current_source = str(_row_value(asset_row, "serial_number_source", 5, "") or "")
    asset_observed_at = _parse_datetime(_row_value(asset_row, "chassis_observed_at", 6))
    current_device_asset = str(_row_value(device_row, "asset_id", 1, "") or "").strip()
    current_device_ip = str(_row_value(device_row, "ip_address", 2, "") or "").strip()
    device_vendor = normalize_asset_vendor(_row_value(device_row, "vendor", 3, ""))
    collection_enabled = bool(_row_value(device_row, "snmp_collection_enabled", 4, False))
    observed_vendors = [vendor for vendor in (asset_vendor, device_vendor) if vendor]
    if (
        current_device_asset != normalized_asset_id
        or not normalized_ip
        or current_asset_ip != normalized_ip
        or current_device_ip != normalized_ip
        or asset_type != "network_device"
        or not collection_enabled
        or len(set(observed_vendors)) > 1
    ):
        return _sync_result("superseded", serial_number=current_serial)

    status = str(snapshot.get("status") or "").strip().casefold()
    if status not in {"success", "partial", "failed"}:
        return _sync_result("failed", serial_number=current_serial)

    observed_at = _parse_datetime(snapshot.get("observed_at"))
    if observed_at is None:
        return _sync_result("failed", serial_number=current_serial)

    existing_latest = conn.execute(
        "SELECT MAX(collected_at) AS collected_at FROM asset_chassis_members WHERE asset_id = ?",
        (normalized_asset_id,),
    ).fetchone()
    latest_at = _parse_datetime(_row_value(existing_latest, "collected_at", 0))
    if (
        (asset_observed_at is not None and asset_observed_at > observed_at)
        or (latest_at is not None and latest_at > observed_at)
    ):
        count_row = conn.execute(
            "SELECT COUNT(*) AS member_count FROM asset_chassis_members WHERE asset_id = ?",
            (normalized_asset_id,),
        ).fetchone()
        return _sync_result(
            "superseded",
            members_count=int(_row_value(count_row, "member_count", 0, 0) or 0),
            serial_number=current_serial,
        )

    count_row = conn.execute(
        "SELECT COUNT(*) AS member_count FROM asset_chassis_members WHERE asset_id = ?",
        (normalized_asset_id,),
    ).fetchone()
    prior_count = int(_row_value(count_row, "member_count", 0, 0) or 0)
    if status == "failed":
        result = _sync_result("failed", members_count=prior_count, serial_number=current_serial)
        result["serial_number_source"] = current_source
        return result

    raw_members = snapshot.get("members")
    if not isinstance(raw_members, Sequence) or isinstance(raw_members, (str, bytes)):
        raw_members = []
    members: list[dict[str, Any]] = []
    invalid_member_indices: set[int] = set()
    invalid_metadata = False
    member_indexes: set[int] = set()
    for raw_member in raw_members:
        cleaned = _clean_member(raw_member)
        if cleaned is None:
            if isinstance(raw_member, Mapping):
                try:
                    candidate_index = int(raw_member.get("entity_index"))
                except (TypeError, ValueError):
                    candidate_index = 0
                if 0 < candidate_index <= 2147483647:
                    invalid_member_indices.add(candidate_index)
            continue
        if any(
            _valid_db_text(raw_member.get(key)) is None
            for key in ("entity_name", "entity_description", "model")
        ):
            invalid_metadata = True
        index = cleaned["entity_index"]
        if index in member_indexes:
            invalid_member_indices.add(index)
            continue
        member_indexes.add(index)
        members.append(cleaned)

    if invalid_member_indices:
        members = [member for member in members if member["entity_index"] not in invalid_member_indices]
        member_indexes = {member["entity_index"] for member in members}

    absent_indexes = _confirmed_indexes(snapshot.get("absent_indices"))
    failed_indexes = _confirmed_indexes(snapshot.get("failed_indices")) | invalid_member_indices
    absent_indexes -= member_indexes | failed_indexes

    # SN confirmation does not prove optional descriptive fields were read.
    # Preserve existing member metadata when this is the same physical SN.
    if members:
        member_placeholders = ", ".join("?" for _ in members)
        prior_rows = conn.execute(
            f"""SELECT entity_index, serial_number, entity_name,
                          entity_description, model
                     FROM asset_chassis_members
                    WHERE asset_id = ? AND entity_index IN ({member_placeholders})""",
            (normalized_asset_id, *(member["entity_index"] for member in members)),
        ).fetchall()
        prior_by_index = {
            int(_row_value(row, "entity_index", 0, 0) or 0): row
            for row in prior_rows
        }
        for member in members:
            prior = prior_by_index.get(member["entity_index"])
            prior_serial = str(_row_value(prior, "serial_number", 1, "") or "")
            if prior is None or prior_serial.strip().casefold() != member["serial_number"].strip().casefold():
                continue
            for key, position in (
                ("entity_name", 2),
                ("entity_description", 3),
                ("model", 4),
            ):
                previous_value = str(_row_value(prior, key, position, "") or "")
                if not member[key] and previous_value:
                    member[key] = previous_value

    for member in members:
        conn.execute(
            """INSERT INTO asset_chassis_members (
                   asset_id, entity_index, serial_number, entity_name,
                   entity_description, model, collected_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (asset_id, entity_index) DO UPDATE SET
                   serial_number = EXCLUDED.serial_number,
                   entity_name = EXCLUDED.entity_name,
                   entity_description = EXCLUDED.entity_description,
                   model = EXCLUDED.model,
                   collected_at = EXCLUDED.collected_at""",
            (
                normalized_asset_id,
                member["entity_index"],
                member["serial_number"],
                member["entity_name"],
                member["entity_description"],
                member["model"],
                observed_at,
            ),
        )

    discovered_indexes = _confirmed_indexes(snapshot.get("discovered_indices"))
    raw_discovered = snapshot.get("discovered_indices")
    valid_discovery = (
        isinstance(raw_discovered, Sequence)
        and not isinstance(raw_discovered, (str, bytes))
        and len(discovered_indexes) == len(raw_discovered)
    )
    complete_serial_read = (
        snapshot.get("discovery_complete") is True
        and snapshot.get("serial_complete") is True
        and valid_discovery
        and not failed_indexes
        and not invalid_metadata
        and not invalid_member_indices
        and not snapshot.get("candidates")
        and member_indexes == discovered_indexes
    )
    # Only an authoritative full snapshot can remove members no longer present.
    # Partial walks, unknown module ownership and conflicts retain prior evidence.
    if complete_serial_read:
        if member_indexes:
            placeholders = ", ".join("?" for _ in member_indexes)
            conn.execute(
                f"DELETE FROM asset_chassis_members WHERE asset_id = ? AND entity_index NOT IN ({placeholders})",
                (normalized_asset_id, *sorted(member_indexes)),
            )
        else:
            conn.execute("DELETE FROM asset_chassis_members WHERE asset_id = ?", (normalized_asset_id,))

    distinct_member_serials = {
        member["serial_number"].strip().casefold()
        for member in members
        if member["serial_number"].strip()
    }
    if complete_serial_read and len(distinct_member_serials) == 1 and (
        not current_serial.strip() or current_source in _AUTO_SERIAL_NUMBER_SOURCES
    ):
        serial_to_sync = members[0]["serial_number"]
        conn.execute(
            """UPDATE physical_assets
                  SET serial_number = ?, serial_number_source = ?
                WHERE id = ?""",
            (serial_to_sync, _AUTO_SERIAL_NUMBER_SOURCE, normalized_asset_id),
        )
        current_serial = serial_to_sync
        current_source = _AUTO_SERIAL_NUMBER_SOURCE
    elif complete_serial_read and len(distinct_member_serials) != 1 and current_source in _AUTO_SERIAL_NUMBER_SOURCES:
        conn.execute(
            """UPDATE physical_assets
                  SET serial_number = '', serial_number_source = ''
                WHERE id = ?""",
            (normalized_asset_id,),
        )
        current_serial = ""
        current_source = ""

    if complete_serial_read or member_indexes:
        conn.execute(
            "UPDATE physical_assets SET chassis_observed_at = ? WHERE id = ?",
            (observed_at, normalized_asset_id),
        )

    final_count_row = conn.execute(
        "SELECT COUNT(*) AS member_count FROM asset_chassis_members WHERE asset_id = ?",
        (normalized_asset_id,),
    ).fetchone()
    final_count = int(_row_value(final_count_row, "member_count", 0, 0) or 0)
    if status == "partial" or failed_indexes or invalid_member_indices or invalid_metadata or not complete_serial_read:
        final_status = "partial"
    else:
        final_status = "synced"
    result = _sync_result(final_status, members_count=final_count, serial_number=current_serial)
    result["serial_number_source"] = current_source
    return result


def get_asset_chassis_members_map(conn: Any, asset_ids: Sequence[Any]) -> dict[str, list[dict[str, Any]]]:
    """Batch-load chassis members for an asset projection."""
    normalized_ids = list(
        dict.fromkeys(str(asset_id or "").strip() for asset_id in asset_ids if str(asset_id or "").strip())
    )
    result: dict[str, list[dict[str, Any]]] = {asset_id: [] for asset_id in normalized_ids}
    if not normalized_ids:
        return result
    for start in range(0, len(normalized_ids), _ASSET_MEMBER_QUERY_BATCH_SIZE):
        batch = normalized_ids[start : start + _ASSET_MEMBER_QUERY_BATCH_SIZE]
        placeholders = ", ".join("?" for _ in batch)
        rows = conn.execute(
            f"""SELECT asset_id, entity_index, serial_number, entity_name,
                          entity_description, model, collected_at
                     FROM asset_chassis_members
                    WHERE asset_id IN ({placeholders})
                    ORDER BY asset_id, entity_index""",
            tuple(batch),
        ).fetchall()
        for row in rows:
            asset_key = str(_row_value(row, "asset_id", 0, "") or "")
            collected_at = _parse_datetime(_row_value(row, "collected_at", 6))
            if asset_key not in result or collected_at is None:
                continue
            result[asset_key].append(
                {
                    "entity_index": int(_row_value(row, "entity_index", 1, 0) or 0),
                    "serial_number": str(_row_value(row, "serial_number", 2, "") or ""),
                    "entity_name": str(_row_value(row, "entity_name", 3, "") or ""),
                    "entity_description": str(_row_value(row, "entity_description", 4, "") or ""),
                    "model": str(_row_value(row, "model", 5, "") or ""),
                    "collected_at": _utc_iso(collected_at),
                }
            )
    return result


__all__ = [
    "get_asset_chassis_members_map",
    "read_chassis_serials",
    "sync_asset_chassis_members",
]
