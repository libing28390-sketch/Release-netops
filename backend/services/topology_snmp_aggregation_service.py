"""SNMP-only operational link aggregation discovery.

The standard ``dot3adAggPortAttachedAggID`` table exposes the current
operational member-to-aggregator relationship.  It is intentionally kept
separate from the topology persistence layer: callers decide whether a
complete snapshot is safe to persist, while this module only validates and
normalizes the device snapshot.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Iterable

from core.interface_utils import normalize_interface_name


SOURCE = "snmp"
# ``MAX_ROWS`` is retained as a compatibility sentinel for existing callers;
# complete inventory walks do not stop at a row count.
MAX_ROWS = None
WALK_TIMEOUT_SECONDS = 30.0

IF_NAME_OID = "1.3.6.1.2.1.31.1.1.1.1"
IF_DESCR_OID = "1.3.6.1.2.1.2.2.1.2"
IF_TYPE_OID = "1.3.6.1.2.1.2.2.1.3"
IF_OPER_STATUS_OID = "1.3.6.1.2.1.2.2.1.8"
IF_HIGH_SPEED_OID = "1.3.6.1.2.1.31.1.1.1.15"
ATTACHED_AGG_ID_OID = "1.2.840.10006.300.43.1.2.1.1.13"
IF_STACK_STATUS_OID = "1.3.6.1.2.1.31.1.2.1.3"

LAG_IF_TYPE = 161
# Common IF-MIB interface types that represent physical Ethernet members.
# Keeping this allow-list prevents VLANs, subinterfaces and software tunnels
# from being emitted as LAG members merely because they have an ifIndex.
PHYSICAL_MEMBER_IF_TYPES = frozenset({6, 7, 26, 62, 69, 117})


class _AggregationCollectionError(RuntimeError):
    """Safe, non-sensitive collection failure with a stable error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def latebound_snmp_walk(
    ip: str,
    community: str | dict[str, Any],
    oid: str,
    *,
    port: int,
    version: str,
    max_rows: int | None = MAX_ROWS,
    timeout: float = WALK_TIMEOUT_SECONDS,
) -> list[tuple[str, str]]:
    """Call the shared complete SNMP walker at runtime without row caps.

    Importing the transport lazily keeps this collector cheap to import and
    lets callers replace the shared walker without opening a connection.
    ``max_rows`` is ignored for compatibility with older internal callers.
    """

    from services.snmp_service import _snmp_bulk_walk_complete, _snmp_text_value

    rows = await _snmp_bulk_walk_complete(
        ip,
        community,
        oid,
        port=port,
        timeout=timeout,
        version=version,
    )
    def stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (bytes, bytearray, memoryview)):
            return _snmp_text_value(value)
        # Preserve integer zero: it means "not attached" in the LAG MIB.
        return str(value).strip()

    return [(str(index), stringify(value)) for index, value in rows]


def _result(
    status: str,
    *,
    records: list[dict[str, Any]] | None = None,
    parents: list[dict[str, Any]] | None = None,
    detail: str = "",
    membership_source: str = "none",
) -> dict[str, Any]:
    return {
        "status": status,
        "source": SOURCE,
        "records": records or [],
        "parents": parents or [],
        "detail": detail,
        "membership_source": membership_source,
    }


def _normalized_version(value: Any) -> str | None:
    version = str(value or "").strip().lower()
    if version in {"1", "v1"}:
        return "1"
    if version in {"2", "2c", "v2c"}:
        return "2c"
    if version in {"3", "v3", "snmpv3"}:
        return "3"
    return None


def _validated_target(
    device: dict[str, Any],
    collector_credentials: dict[str, Any] | None,
) -> tuple[str, str | dict[str, Any], int, str] | None:
    snmp = (collector_credentials or {}).get("snmp") or {}
    ip = str(snmp.get("server") or device.get("ip_address") or "").strip()
    if not ip:
        return None

    raw_port = snmp.get("port", 161)
    if isinstance(raw_port, bool):
        return None
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        return None
    if not 1 <= port <= 65535:
        return None

    version = _normalized_version(snmp.get("version", "2c"))
    if version is None:
        return None
    if version == "3":
        if not snmp.get("configured") or not str(snmp.get("username") or "").strip():
            return None
        return ip, dict(snmp), port, version
    community = str(snmp.get("community") or "").strip()
    if not community:
        return None
    return ip, community, port, version


def _rows(value: Iterable[Any]) -> tuple[list[tuple[str, str]], bool]:
    """Normalize walker rows and report malformed row shape."""

    normalized: list[tuple[str, str]] = []
    malformed = False
    for row in value or []:
        if isinstance(row, dict):
            index = row.get("oid") or row.get("index") or row.get("suffix")
            raw_value = row.get("value")
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            index, raw_value = row[0], row[1]
        else:
            malformed = True
            continue
        if index in (None, ""):
            malformed = True
            continue
        normalized.append((str(index).strip(), "" if raw_value is None else str(raw_value).strip()))
    return normalized, malformed


def _if_index(value: Any) -> int | None:
    text = str(value or "").strip().lstrip(".")
    if not text.isdigit():
        return None
    parsed = int(text)
    return parsed if parsed > 0 else None


def _stack_indexes(value: Any) -> tuple[int, int] | None:
    parts = [part for part in str(value or "").strip().lstrip(".").split(".") if part]
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    higher, lower = (int(part) for part in parts)
    if higher < 0 or lower < 0:
        return None
    return higher, lower


def _integer(value: Any) -> int | None:
    text = str(value or "")
    # pysnmp and vendor agents commonly render enumerations as
    # ``ieee8023adLag(161)``; prefer the enum value over digits in the label.
    match = re.search(r"\((\d+)\)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(?<!\d)(\d+)(?!\d)", text)
    return int(match.group(1)) if match else None


def _oper_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    code = _integer(raw)
    aliases = {
        1: "up",
        2: "down",
        3: "testing",
        4: "unknown",
        5: "dormant",
        6: "not_present",
        7: "lower_layer_down",
    }
    if code in aliases and (raw.isdigit() or "(" in raw):
        return aliases[code]
    if raw in {"up", "down", "testing", "unknown", "dormant", "not_present", "lower_layer_down"}:
        return raw
    return "unknown"


def _is_active_stack(value: Any) -> bool:
    raw = str(value or "").strip().lower()
    return raw == "1" or raw.startswith("active(") or raw == "active"


def _if_type(value: Any) -> int | None:
    text = str(value or "").strip()
    enum_match = re.search(r"\((\d+)\)\s*$", text)
    if enum_match:
        return int(enum_match.group(1))
    numeric_match = re.fullmatch(r"(?:INTEGER:\s*)?(\d+)", text, flags=re.IGNORECASE)
    return int(numeric_match.group(1)) if numeric_match else None


def _speed_mbps(value: Any) -> float | None:
    raw = str(value or "").strip()
    if not raw or not re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return None
    speed = float(raw)
    return speed if speed > 0 else None


def _interface_name(index: int, names: dict[int, str], descriptions: dict[int, str]) -> str:
    return str(names.get(index) or descriptions.get(index) or "").strip()


def _parent_rows(
    indexes: dict[int, int],
    names: dict[int, str],
    descriptions: dict[int, str],
    statuses: dict[int, str],
    speeds: dict[int, float | None],
) -> tuple[list[dict[str, Any]], str | None]:
    parents: list[dict[str, Any]] = []
    for if_index, if_type in sorted(indexes.items()):
        if if_type != LAG_IF_TYPE:
            continue
        interface_name = _interface_name(if_index, names, descriptions)
        if not interface_name or not normalize_interface_name(interface_name):
            return [], "SNMP_LAG_PARENT_NAME_MISSING"
        parents.append({
            "interface_name": interface_name,
            "if_index": if_index,
            "oper_status": statuses.get(if_index, "unknown"),
            "speed_mbps": speeds.get(if_index),
        })
    return parents, None


def _member_record(
    parent: dict[str, Any],
    member_index: int,
    names: dict[int, str],
    descriptions: dict[int, str],
    types: dict[int, int],
    statuses: dict[int, str],
    speeds: dict[int, float | None],
) -> dict[str, Any] | None:
    member_name = _interface_name(member_index, names, descriptions)
    # Keep the device spelling for display, but validate through the shared
    # topology canonicalizer so aliases follow the same identity rules as
    # persistence.
    if not member_name or not normalize_interface_name(member_name):
        return None
    if types.get(member_index) not in PHYSICAL_MEMBER_IF_TYPES:
        return None
    return {
        "aggregation_name": parent["interface_name"],
        "aggregation_if_index": parent["if_index"],
        "aggregation_oper_status": parent["oper_status"],
        "member_interface": member_name,
        "member_if_index": member_index,
        "member_oper_status": statuses.get(member_index, "unknown"),
        "member_speed_mbps": speeds.get(member_index),
        "aggregation_protocol": "",
    }


async def collect_snmp_aggregation_inventory(
    device: dict[str, Any],
    collector_credentials: dict[str, Any] | None,
) -> dict[str, Any]:
    """Collect the current SNMP LAG member inventory without CLI fallback."""

    target = _validated_target(device, collector_credentials)
    if target is None:
        return _result("unavailable", detail="SNMP_CREDENTIALS_OR_TARGET_INVALID")
    ip, community, port, version = target

    try:
        name_raw = await latebound_snmp_walk(ip, community, IF_NAME_OID, port=port, version=version)
        type_raw = await latebound_snmp_walk(ip, community, IF_TYPE_OID, port=port, version=version)
    except _AggregationCollectionError as exc:
        return _result("failed", detail=exc.code)
    except asyncio.TimeoutError:
        return _result("failed", detail="SNMP_REQUIRED_WALK_TIMEOUT")
    except Exception:
        return _result("failed", detail="SNMP_REQUIRED_WALK_FAILED")

    names_rows, names_malformed = _rows(name_raw)
    type_rows, type_malformed = _rows(type_raw)
    if names_malformed or type_malformed:
        return _result("partial", detail="SNMP_REQUIRED_ROW_MALFORMED")

    names: dict[int, str] = {}
    for raw_index, value in names_rows:
        index = _if_index(raw_index)
        if index is None:
            return _result("partial", detail="SNMP_IF_NAME_INDEX_MALFORMED")
        if value:
            if index in names and names[index] != value:
                return _result("partial", detail="SNMP_IF_NAME_INDEX_CONFLICT")
            names[index] = value
    types: dict[int, int] = {}
    for raw_index, value in type_rows:
        index = _if_index(raw_index)
        parsed_type = _if_type(value)
        if index is None or parsed_type is None:
            return _result("partial", detail="SNMP_IF_TYPE_ROW_MALFORMED")
        if index in types and types[index] != parsed_type:
            return _result("partial", detail="SNMP_IF_TYPE_INDEX_CONFLICT")
        types[index] = parsed_type

    if not types:
        return _result("partial", detail="SNMP_IF_TYPE_TABLE_EMPTY")

    # A complete ifName table makes ifDescr unnecessary.  It is retained as a
    # fallback for agents that expose only ifDescr or omit names for some
    # rows.
    if set(types).issubset(names):
        descr_raw = []
    else:
        try:
            descr_raw = await latebound_snmp_walk(ip, community, IF_DESCR_OID, port=port, version=version)
        except Exception:
            descr_raw = []
    descr_rows, descr_malformed = _rows(descr_raw)
    if descr_malformed:
        return _result("partial", detail="SNMP_IF_DESCR_ROW_MALFORMED")
    descriptions: dict[int, str] = {}
    for raw_index, value in descr_rows:
        index = _if_index(raw_index)
        if index is None:
            return _result("partial", detail="SNMP_IF_DESCR_INDEX_MALFORMED")
        if value:
            if index in descriptions and descriptions[index] != value:
                return _result("partial", detail="SNMP_IF_DESCR_INDEX_CONFLICT")
            descriptions[index] = value

    # Every named row must have a corresponding interface type.  Without this
    # check a missing ifType walk can look like a valid no-LAG snapshot and
    # detach a previous inventory.
    named_indexes = set(names) | set(descriptions)
    if not named_indexes.issubset(types):
        return _result("partial", detail="SNMP_IF_TYPE_INDEX_MISSING")
    if not set(types).issubset(named_indexes):
        return _result("partial", detail="SNMP_INTERFACE_NAME_INDEX_MISSING")
    if not names and not descriptions:
        return _result("partial", detail="SNMP_INTERFACE_NAMES_MISSING")

    canonical_names: dict[str, int] = {}
    for index in sorted(named_indexes):
        interface_name = _interface_name(index, names, descriptions)
        canonical = normalize_interface_name(interface_name).lower()
        if not canonical:
            continue
        previous = canonical_names.get(canonical)
        if previous is not None and previous != index:
            return _result("partial", detail="SNMP_INTERFACE_NAME_CONFLICT")
        canonical_names[canonical] = index

    statuses: dict[int, str] = {}
    speeds: dict[int, float | None] = {}
    try:
        status_raw = await latebound_snmp_walk(ip, community, IF_OPER_STATUS_OID, port=port, version=version)
        status_rows, status_malformed = _rows(status_raw)
        if status_malformed:
            return _result("partial", detail="SNMP_IF_OPER_STATUS_ROW_MALFORMED")
        for raw_index, value in status_rows:
            index = _if_index(raw_index)
            if index is not None:
                statuses[index] = _oper_status(value)
    except Exception:
        # ifOperStatus is optional; unknown must remain unknown.
        statuses = {}

    try:
        speed_raw = await latebound_snmp_walk(ip, community, IF_HIGH_SPEED_OID, port=port, version=version)
        speed_rows, speed_malformed = _rows(speed_raw)
        if speed_malformed:
            return _result("partial", detail="SNMP_IF_HIGH_SPEED_ROW_MALFORMED")
        for raw_index, value in speed_rows:
            index = _if_index(raw_index)
            if index is not None:
                speeds[index] = _speed_mbps(value)
    except Exception:
        speeds = {}

    parents, parent_error = _parent_rows(types, names, descriptions, statuses, speeds)
    if parent_error:
        return _result("partial", parents=parents, detail=parent_error)

    try:
        attached_raw = await latebound_snmp_walk(ip, community, ATTACHED_AGG_ID_OID, port=port, version=version)
    except _AggregationCollectionError as exc:
        return _result("failed", parents=parents, detail=exc.code)
    except asyncio.TimeoutError:
        return _result("failed", parents=parents, detail="SNMP_MEMBERSHIP_WALK_TIMEOUT")
    except Exception:
        return _result("unavailable", parents=parents, detail="SNMP_ATTACHED_AGG_ID_UNAVAILABLE")

    attached_rows, attached_malformed = _rows(attached_raw)
    if attached_malformed:
        return _result("partial", parents=parents, detail="SNMP_ATTACHED_AGG_ID_ROW_MALFORMED")

    attached_values: list[tuple[int, int]] = []
    attached_by_member: dict[int, int] = {}
    for raw_member, raw_parent in attached_rows:
        member_index = _if_index(raw_member)
        parent_index = _if_index(raw_parent) if str(raw_parent or "").strip() not in {"0", ".0"} else 0
        if member_index is None or parent_index is None:
            return _result("partial", parents=parents, detail="SNMP_ATTACHED_AGG_ID_INDEX_MALFORMED")
        previous_parent = attached_by_member.get(member_index)
        if previous_parent is not None and previous_parent != parent_index:
            return _result("partial", parents=parents, detail="SNMP_AGGREGATION_INDEX_CONFLICT")
        if previous_parent is not None:
            continue
        attached_by_member[member_index] = parent_index
        attached_values.append((member_index, parent_index))

    if attached_values:
        # A non-empty table whose rows are all unattached is a complete,
        # authoritative empty-members snapshot and is safe for detachment.
        if all(parent_index == 0 for _, parent_index in attached_values):
            if any(
                not _interface_name(member_index, names, descriptions)
                or types.get(member_index) not in PHYSICAL_MEMBER_IF_TYPES
                for member_index, _ in attached_values
            ):
                return _result("partial", parents=parents, detail="SNMP_AGGREGATION_MEMBER_INVALID")
            return _result(
                "success",
                parents=parents,
                membership_source="dot3adAggPortAttachedAggID",
            )

        parent_by_index = {parent["if_index"]: parent for parent in parents}
        records: list[dict[str, Any]] = []
        seen: dict[int, int] = {}
        for member_index, parent_index in attached_values:
            if parent_index == 0:
                continue
            parent = parent_by_index.get(parent_index)
            if parent is None:
                return _result("partial", parents=parents, detail="SNMP_AGGREGATION_PARENT_ORPHAN")
            if member_index in seen and seen[member_index] != parent_index:
                return _result("partial", parents=parents, detail="SNMP_AGGREGATION_INDEX_CONFLICT")
            seen[member_index] = parent_index
            record = _member_record(parent, member_index, names, descriptions, types, statuses, speeds)
            if record is None:
                return _result("partial", parents=parents, detail="SNMP_AGGREGATION_MEMBER_INVALID")
            records.append(record)
        return _result(
            "success",
            records=records,
            parents=parents,
            membership_source="dot3adAggPortAttachedAggID",
        )

    # The standard table is empty.  Only use ifStack as an operational
    # fallback; it must point from a named 802.3ad aggregator to a named
    # non-aggregator interface and must be active.
    if not parents:
        return _result("success", parents=[], membership_source="no_aggregation")
    try:
        stack_raw = await latebound_snmp_walk(ip, community, IF_STACK_STATUS_OID, port=port, version=version)
    except _AggregationCollectionError as exc:
        return _result("failed", parents=parents, detail=exc.code)
    except Exception:
        return _result("unavailable", parents=parents, detail="SNMP_IF_STACK_UNAVAILABLE")
    stack_rows, stack_malformed = _rows(stack_raw)
    if stack_malformed:
        return _result("partial", parents=parents, detail="SNMP_IF_STACK_ROW_MALFORMED")

    parent_by_index = {parent["if_index"]: parent for parent in parents}
    records = []
    seen_members: dict[int, int] = {}
    for raw_index, raw_status in stack_rows:
        indexes = _stack_indexes(raw_index)
        if indexes is None:
            return _result("partial", parents=parents, detail="SNMP_IF_STACK_INDEX_MALFORMED")
        if 0 in indexes:
            # IF-MIB uses 0.x/x.0 to represent a missing layer endpoint.
            continue
        if not _is_active_stack(raw_status):
            continue
        higher, lower = indexes
        higher_type = types.get(higher)
        if higher_type is None:
            return _result("partial", parents=parents, detail="SNMP_IF_STACK_PARENT_INVALID")
        # A known non-LAG higher layer describes another interface hierarchy
        # (for example VLAN/subinterface); it is unrelated to LAG membership.
        if higher_type != LAG_IF_TYPE:
            continue
        parent = parent_by_index.get(higher)
        if parent is None:
            return _result("partial", parents=parents, detail="SNMP_IF_STACK_PARENT_INVALID")
        if lower not in types or lower in parent_by_index or not _interface_name(lower, names, descriptions):
            return _result("partial", parents=parents, detail="SNMP_IF_STACK_MEMBER_INVALID")
        if types.get(lower) not in PHYSICAL_MEMBER_IF_TYPES:
            return _result("partial", parents=parents, detail="SNMP_IF_STACK_MEMBER_INVALID")
        if lower in seen_members and seen_members[lower] != higher:
            return _result("partial", parents=parents, detail="SNMP_AGGREGATION_INDEX_CONFLICT")
        if lower in seen_members:
            continue
        seen_members[lower] = higher
        record = _member_record(parent, lower, names, descriptions, types, statuses, speeds)
        if record is None:
            return _result("partial", parents=parents, detail="SNMP_IF_STACK_MEMBER_INVALID")
        records.append(record)

    # An empty/entirely inactive ifStack table does not prove that the
    # aggregator has no members. Preserve the last persisted binding until a
    # valid operational membership source is available.
    if not records:
        return _result(
            "unavailable",
            parents=parents,
            detail="SNMP_MEMBERSHIP_TABLE_EMPTY",
            membership_source="ifStackStatus",
        )

    return _result(
        "success",
        records=records,
        parents=parents,
        membership_source="ifStackStatus",
    )
