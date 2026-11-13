"""Read chassis serials from complete SNMP ENTITY-MIB snapshots.

Only ENTITY-MIB rows explicitly classified as chassis can produce members.
Vendor-specific observations are supporting evidence; they never promote a
module or an unassociated vendor row into a chassis member.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.snmp_entity_model_service import _walk_credential


_ENTITY_BASE = "1.3.6.1.2.1.47.1.1.1.1"
_ENTITY_CLASS = 5
_ENTITY_PARENT = 4
_ENTITY_SERIAL = 11
_ENTITY_NAME = 7
_ENTITY_DESCRIPTION = 2
_ENTITY_MODEL = 13
_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
_ENTITY_LAST_CHANGE = "1.3.6.1.2.1.47.1.4.1.0"
_MAX_ROWS = 2000
_MAX_DEVICE_SECONDS = 60.0
_WALK_TIMEOUT_SECONDS = 20.0
_GET_TIMEOUT_SECONDS = 2.0
_MAX_IN_FLIGHT = 3
_SOURCE = "snmp_entity_discovery"
_SNMP_MISSING = {"nosuchinstance", "nosuchobject", "nosuchoid", "endofmibview"}
_INVALID_SERIALS = {
    "", "-", "--", "none", "null", "unknown", "n/a", "na", "not available",
    "not applicable", "no serial", "no serial number", "no such instance",
    "no such object", "no such name", "unspecified", "nil", "0",
    "to be filled by o.e.m.",
}

_H3C_FRAME_COLUMNS = (
    "1.3.6.1.4.1.25506.8.35.18.4.2.1.6",
    "1.3.6.1.4.1.2011.10.8.35.18.4.2.1.6",
)


@dataclass
class _ColumnRead:
    rows: list[tuple[str, Any]] = field(default_factory=list)
    octets: dict[str, bytes] = field(default_factory=dict)
    complete: bool = False


@dataclass
class _ScalarRead:
    value: str | None = None
    sampled_at: float | None = None


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_version(settings: Mapping[str, Any]) -> str | None:
    value = str(settings.get("version") or "").strip().casefold()
    if value in {"2c", "v2c", "2"}:
        return "2c"
    if value in {"3", "v3", "snmpv3"}:
        return "3"
    return None


def _valid_ip_and_port(ip: str, settings: Mapping[str, Any]) -> tuple[str, int] | None:
    target = str(ip or "").strip()
    try:
        ipaddress.ip_address(target)
        port = int(settings.get("port") or 161)
    except (TypeError, ValueError):
        return None
    if not 1 <= port <= 65535:
        return None
    return target, port


def _raw_text(value: Any, octets: bytes | None = None) -> str | None:
    if octets is not None:
        try:
            text = octets.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
    else:
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
    if "\x00" in text or any(unicodedata.category(char) in {"Cc", "Cs"} for char in text):
        return None
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    return text.strip()


def _is_missing(value: Any) -> bool:
    name = type(value).__name__.casefold()
    if name in _SNMP_MISSING:
        return True
    raw = getattr(value, "value", value)
    if raw is None:
        return True
    if isinstance(raw, (bytes, bytearray, memoryview)):
        text = bytes(raw).decode("ascii", errors="ignore").strip().casefold()
    else:
        text = str(raw).strip().casefold()
    return text in _SNMP_MISSING


def _integer(value: Any) -> int | None:
    text = _raw_text(value)
    if text is None:
        return None
    text = text.strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    # Some SNMP libraries render INTEGER enumerations as ``chassis(3)``.
    match = re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*\s*\(\s*(-?\d+)\s*\)", text)
    return int(match.group(1)) if match else None


def _serial(value: Any, octets: bytes | None = None) -> tuple[str, str]:
    """Return (valid|absent|invalid, normalized serial text)."""
    if _is_missing(value):
        return "absent", ""
    text = _raw_text(value, octets)
    if text is None:
        return "invalid", ""
    text = text.strip()
    folded = text.casefold()
    if not text:
        return "absent", ""
    folded = " ".join(folded.split())
    if folded in _INVALID_SERIALS or folded.startswith(("no such ", "not available")):
        return "invalid", ""
    compact = re.sub(r"[\s:-]", "", folded)
    if len(text) > 128 or len(compact) < 3 or re.fullmatch(r"0+|f+", compact):
        return "invalid", ""
    return "valid", text


def _row_index(value: Any) -> int | None:
    text = str(value or "").strip().strip(".")
    if not re.fullmatch(r"[1-9]\d*", text):
        return None
    try:
        index = int(text)
        return index if index <= 2**31 - 1 else None
    except ValueError:
        return None


def _indexed_column(column: _ColumnRead, parser) -> tuple[dict[int, Any], bool]:
    indexed: dict[int, Any] = {}
    valid = True
    for suffix, value in column.rows:
        index = _row_index(suffix)
        if index is None or index in indexed:
            valid = False
            continue
        parsed = parser(value)
        if parsed is None:
            valid = False
        indexed[index] = parsed
    return indexed, valid


def _parent_chain_is_valid(index: int, classes: Mapping[int, int | None], parents: Mapping[int, int | None]) -> bool:
    seen = {index}
    current = index
    while True:
        parent = parents.get(current)
        if parent is None or parent < 0:
            return False
        if parent == 0:
            return True
        if parent in seen:
            return False
        parent_class = classes.get(parent)
        if parent_class is None:
            return False
        # Nested class-3 chassis rows are not independent physical members.
        if parent_class == 3:
            return False
        seen.add(parent)
        current = parent


def _entity_lineage_present(index: int, classes: Mapping[int, int | None], parents: Mapping[int, int | None]) -> bool:
    """Require known, acyclic ancestry without rejecting a module inside a chassis."""
    seen: set[int] = set()
    current = index
    while current not in seen:
        seen.add(current)
        parent = parents.get(current)
        if parent is None or parent < 0:
            return False
        if parent == 0:
            return True
        if parent not in classes:
            return False
        current = parent
    return False


def _read_result(
    status: str,
    observed_at: str,
    *,
    members: list[dict[str, Any]] | None = None,
    discovered_indices: list[int] | None = None,
    discovery_complete: bool = False,
    serial_complete: bool = False,
    absent_indices: list[int] | None = None,
    failed_indices: list[int] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    diagnostics: list[str] | None = None,
    snapshot_consistency: str = "unknown",
) -> dict[str, Any]:
    return {
        "status": status,
        "source": _SOURCE,
        "observed_at": observed_at,
        "members": members or [],
        "discovered_indices": sorted(set(discovered_indices or [])),
        "discovery_complete": bool(discovery_complete),
        "serial_complete": bool(serial_complete),
        "absent_indices": sorted(set(absent_indices or [])),
        "failed_indices": sorted(set(failed_indices or [])),
        "candidates": candidates or [],
        "diagnostics": diagnostics or [],
        "snapshot_consistency": snapshot_consistency,
    }


async def read_chassis_serials(ip: str, settings: Mapping[str, Any], *, vendor: str = "") -> dict[str, Any]:
    """Discover standard ENTITY-MIB chassis serials with bounded evidence reads.

    The device is sampled before and after collection. Each ENTITY-MIB walk is
    bounded to 2,000 rows, no more than three SNMP operations run at once, and
    the entire operation has a 60-second deadline.
    """
    observed_at = _utc_iso(datetime.now(timezone.utc))
    if not isinstance(settings, Mapping):
        return _read_result("failed", observed_at, diagnostics=["invalid_settings"])
    target = _valid_ip_and_port(ip, settings)
    version = _normalize_version(settings)
    if target is None or version is None:
        return _read_result("failed", observed_at, diagnostics=["invalid_target_or_snmp_version"])
    target_ip, port = target
    credential = _walk_credential(settings, version)
    if credential is None:
        return _read_result("failed", observed_at, diagnostics=["snmp_credentials_missing"])

    from puresnmp import PyWrapper
    from services import snmp_service
    from services.network_access_limiter import get_network_access_limiter

    loop = asyncio.get_running_loop()
    deadline = loop.time() + _MAX_DEVICE_SECONDS
    gate = asyncio.Semaphore(_MAX_IN_FLIGHT)

    async def read_scalar(oid: str) -> _ScalarRead:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return _ScalarRead()
        try:
            async with gate:
                async with get_network_access_limiter().async_snmp():
                    client = PyWrapper(
                        snmp_service._build_versioned_snmp_client(target_ip, credential, port, version)
                    )
                    response = await asyncio.wait_for(
                        client.get(oid), timeout=min(_GET_TIMEOUT_SECONDS, max(0.01, deadline - loop.time()))
                    )
            if _is_missing(response):
                return _ScalarRead()
            text = _raw_text(response)
            return _ScalarRead(text, loop.time()) if text is not None and text else _ScalarRead()
        except asyncio.CancelledError:
            raise
        except Exception:
            return _ScalarRead()

    async def read_text_observation(oid: str, *, timeout: float | None = None) -> tuple[bool, str]:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False, ""
        request_timeout = min(timeout or _GET_TIMEOUT_SECONDS, remaining)
        try:
            async with gate:
                async with get_network_access_limiter().async_snmp():
                    client = PyWrapper(
                        snmp_service._build_versioned_snmp_client(target_ip, credential, port, version)
                    )
                    response = await asyncio.wait_for(client.get(oid), timeout=max(0.01, request_timeout))
            if _is_missing(response):
                return True, ""
            text = _raw_text(response)
            return (text is not None), text or ""
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if type(exc).__name__.casefold() in _SNMP_MISSING:
                return True, ""
            return False, ""

    async def read_text(oid: str, *, timeout: float | None = None) -> str:
        return (await read_text_observation(oid, timeout=timeout))[1]

    async def read_column(oid: str, *, timeout: float | None = None) -> _ColumnRead:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return _ColumnRead()
        request_timeout = min(timeout or _WALK_TIMEOUT_SECONDS, remaining)
        try:
            async with gate:
                rows = await snmp_service._snmp_walk(
                    target_ip,
                    credential,
                    oid,
                    port,
                    timeout=request_timeout,
                    max_rows=_MAX_ROWS,
                    version=version,
                    raise_on_error=True,
                    preserve_octets=True,
                    prefer_bulk=True,
                )
            values = list(rows)
            octets = getattr(rows, "octet_values", {})
            return _ColumnRead(
                values,
                {str(suffix): bytes(value) for suffix, value in dict(octets or {}).items()},
                not bool(getattr(rows, "truncated", False)),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            partial = getattr(exc, "partial_results", None)
            values = list(partial) if isinstance(partial, (list, tuple)) else []
            octets = getattr(partial, "octet_values", {})
            return _ColumnRead(
                values,
                {str(suffix): bytes(value) for suffix, value in dict(octets or {}).items()},
                False,
            )

    async def settle(tasks: list[asyncio.Task], until: float) -> list[Any]:
        if not tasks:
            return []
        remaining = max(0.0, until - loop.time())
        try:
            done, pending = await asyncio.wait(tasks, timeout=remaining)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        output: list[Any] = []
        for task in tasks:
            if task not in done:
                output.append(None)
                continue
            try:
                output.append(task.result())
            except asyncio.CancelledError:
                output.append(None)
            except Exception:
                output.append(None)
        return output

    async def read_snapshot_pair() -> dict[str, _ScalarRead]:
        names = ("uptime", "last_change")
        oids = (_SYS_UPTIME, _ENTITY_LAST_CHANGE)
        tasks = [asyncio.create_task(read_scalar(oid)) for oid in oids]
        results = await settle(tasks, deadline)
        return {
            name: result if isinstance(result, _ScalarRead) else _ScalarRead()
            for name, result in zip(names, results)
        }

    diagnostics: list[str] = []
    before = await read_snapshot_pair()
    core_oids = tuple(f"{_ENTITY_BASE}.{column}" for column in (_ENTITY_CLASS, _ENTITY_PARENT, _ENTITY_SERIAL))
    core_tasks = [asyncio.create_task(read_column(oid)) for oid in core_oids]
    core_results = await settle(core_tasks, deadline)
    class_column, parent_column, serial_column = (
        result if isinstance(result, _ColumnRead) else _ColumnRead() for result in core_results
    )

    class_rows, class_rows_valid = _indexed_column(class_column, _integer)
    parent_rows, parent_rows_valid = _indexed_column(parent_column, _integer)
    serial_rows, serial_rows_valid = _indexed_column(serial_column, lambda value: value)
    discovered_indices = sorted(index for index, value in class_rows.items() if value == 3)
    class_parent_columns_complete = (
        class_column.complete
        and parent_column.complete
        and class_rows_valid
        and parent_rows_valid
        and set(class_rows) == set(parent_rows)
    )

    vendor_key = str(vendor or "").strip().casefold().split("（", 1)[0].split("(", 1)[0].strip()
    h3c = vendor_key in {
        "h3c", "华三", "新华三"
    }
    huawei = vendor_key in {"huawei", "华为"}
    private_columns: list[_ColumnRead] = []
    if h3c:
        private_tasks = [asyncio.create_task(read_column(oid, timeout=12.0)) for oid in _H3C_FRAME_COLUMNS]
        private_results = await settle(private_tasks, deadline)
        private_columns = [
            result if isinstance(result, _ColumnRead) else _ColumnRead() for result in private_results
        ]
        for oid, column in zip(_H3C_FRAME_COLUMNS, private_columns):
            if not column.complete:
                diagnostics.append(f"h3c_private_frame_walk_incomplete:{oid}")

    # Names are needed only for class-3 rows and only to resolve an explicitly
    # named H3C frame ID. Metadata is never used to decide the physical class.
    names_by_index: dict[int, str] = {}
    huawei_module_data: dict[int, dict[str, str]] = {}
    huawei_metadata_complete = True
    if h3c and discovered_indices and class_parent_columns_complete:
        reserve_after_snapshot = min(2 * _GET_TIMEOUT_SECONDS + 0.25, _MAX_DEVICE_SECONDS / 4)
        name_deadline = max(loop.time(), deadline - reserve_after_snapshot)
        name_tasks = [
            asyncio.create_task(read_text(f"{_ENTITY_BASE}.{_ENTITY_NAME}.{index}"))
            for index in discovered_indices
        ]
        name_values = await settle(name_tasks, name_deadline)
        names_by_index = {
            index: value
            for index, value in zip(discovered_indices, name_values)
            if isinstance(value, str) and value
        }

    if huawei and class_parent_columns_complete and serial_column.complete and serial_rows_valid:
        module_indexes = []
        for index, entity_class in class_rows.items():
            if entity_class != 9 or index not in serial_rows:
                continue
            if _serial(serial_rows[index], serial_column.octets.get(str(index)))[0] == "valid":
                module_indexes.append(index)
        if module_indexes:
            reserve_after_snapshot = min(2 * _GET_TIMEOUT_SECONDS + 0.25, _MAX_DEVICE_SECONDS / 4)
            module_deadline = max(loop.time(), deadline - reserve_after_snapshot)
            module_tasks = [
                asyncio.create_task(read_text_observation(f"{_ENTITY_BASE}.{column}.{index}"))
                for index in module_indexes
                for column in (_ENTITY_NAME, _ENTITY_MODEL)
            ]
            module_values = await settle(module_tasks, module_deadline)
            for position, index in enumerate(module_indexes):
                name_result = module_values[position * 2] if position * 2 < len(module_values) else None
                model_result = module_values[position * 2 + 1] if position * 2 + 1 < len(module_values) else None
                if not (
                    isinstance(name_result, tuple)
                    and name_result[0]
                    and isinstance(model_result, tuple)
                    and model_result[0]
                ):
                    huawei_metadata_complete = False
                huawei_module_data[index] = {
                    "name": name_result[1] if isinstance(name_result, tuple) else "",
                    "model": model_result[1] if isinstance(model_result, tuple) else "",
                }
    if huawei and not huawei_metadata_complete:
        diagnostics.append("huawei_module_identity_metadata_incomplete")

    after = await read_snapshot_pair()
    consistency = _snapshot_consistency(before, after)
    if consistency == "unknown":
        diagnostics.append("snapshot_objects_unavailable_or_unparseable")
    elif consistency == "changed":
        diagnostics.append("entity_table_changed_during_collection")
    elif consistency == "restarted":
        diagnostics.append("device_uptime_reset_or_discontinuity")

    if not class_column.complete or not parent_column.complete:
        diagnostics.append("entity_class_or_parent_walk_incomplete")
    elif not class_rows_valid or not parent_rows_valid or set(class_rows) != set(parent_rows):
        diagnostics.append("entity_class_parent_rows_do_not_match")
    if not serial_column.complete:
        diagnostics.append("entity_serial_walk_incomplete")
    elif not serial_rows_valid:
        diagnostics.append("entity_serial_rows_invalid_or_duplicated")

    relation_valid: dict[int, bool] = {}
    for index in discovered_indices:
        relation_valid[index] = (
            class_parent_columns_complete
            and index in parent_rows
            and _parent_chain_is_valid(index, class_rows, parent_rows)
        )
    discovery_complete = (
        class_parent_columns_complete
        and all(relation_valid.values())
        and consistency not in {"changed", "restarted"}
    )

    standard_serials: dict[int, tuple[str, str]] = {}
    for index in discovered_indices:
        if not serial_column.complete or not serial_rows_valid:
            standard_serials[index] = ("unknown", "")
        elif index not in serial_rows:
            # A completed subtree with no row for this chassis is an explicit
            # absent serial. An incomplete subtree never creates this evidence.
            standard_serials[index] = ("absent", "")
        else:
            raw_value = serial_rows[index]
            standard_serials[index] = _serial(
                raw_value,
                serial_column.octets.get(str(index)),
            )

    serial_to_entities: dict[str, list[int]] = defaultdict(list)
    for index, (outcome, serial_number) in standard_serials.items():
        if outcome == "valid":
            serial_to_entities[serial_number.casefold()].append(index)

    private_rows: list[dict[str, Any]] = []
    if h3c:
        for oid, column in zip(_H3C_FRAME_COLUMNS, private_columns):
            for suffix, raw_value in column.rows:
                index = _row_index(suffix)
                if index is None:
                    diagnostics.append(f"h3c_private_frame_index_invalid:{oid}")
                    continue
                state, serial_number = _serial(raw_value, column.octets.get(str(suffix)))
                if state == "valid":
                    private_rows.append({
                        "source": oid,
                        "index": index,
                        "serial_number": serial_number,
                    })

    private_serial_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    private_frame_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in private_rows:
        private_serial_rows[row["serial_number"].casefold()].append(row)
        private_frame_rows[row["index"]].append(row)

    def explicit_frame_id(name: str) -> int | None:
        match = re.search(r"\b(?:frame|chassis)\s*(?:id\s*)?[#:=_-]?\s*(\d+)\b", name, re.IGNORECASE)
        if match is None:
            match = re.search(r"(?:机框|机箱)\s*(?:编号\s*)?[#:=_-]?\s*(\d+)", name)
        return int(match.group(1)) if match else None

    h3c_conflicts: set[int] = set()
    corroborated: set[int] = set()
    if h3c:
        for index, (outcome, serial_number) in standard_serials.items():
            name = names_by_index.get(index, "")
            frame_id = explicit_frame_id(name)
            frame_observations = private_frame_rows.get(frame_id, []) if frame_id is not None else []
            frame_serials = {row["serial_number"].casefold() for row in frame_observations}
            if len(frame_serials) > 1:
                h3c_conflicts.add(index)
            elif frame_serials and outcome == "valid":
                private_serial = next(iter(frame_serials))
                if private_serial != serial_number.casefold():
                    h3c_conflicts.add(index)
                else:
                    corroborated.add(index)
            elif frame_serials and outcome != "valid":
                # A standard name tied this chassis to a private frame row,
                # but ENTITY-MIB supplied no usable serial to agree with it.
                h3c_conflicts.add(index)
            if outcome == "valid" and len(serial_to_entities.get(serial_number.casefold(), [])) == 1:
                matching_private = private_serial_rows.get(serial_number.casefold(), [])
                if len({row["index"] for row in matching_private}) == 1:
                    corroborated.add(index)

    huawei_stack_candidates: list[dict[str, Any]] = []
    if huawei and huawei_metadata_complete and class_parent_columns_complete and serial_column.complete and serial_rows_valid:
        module_candidates: list[dict[str, Any]] = []
        for index, entity_class in class_rows.items():
            if entity_class != 9 or index not in serial_rows:
                continue
            serial_state, serial_number = _serial(serial_rows[index], serial_column.octets.get(str(index)))
            if serial_state != "valid" or not _entity_lineage_present(index, class_rows, parent_rows):
                continue
            identity = huawei_module_data.get(index, {})
            model = identity.get("model", "").strip()
            name = identity.get("name", "").strip()
            if not re.fullmatch(r"S\d{4}[A-Za-z0-9]*(?:-[A-Za-z0-9]+)*", model, re.IGNORECASE):
                continue
            label = re.fullmatch(r"(?:HUAWEI\s+)?(" + re.escape(model) + r")\s+(\d+)", name, re.IGNORECASE)
            if label is None or label.group(1).casefold() != model.casefold():
                continue
            module_candidates.append({
                "entity_index": index,
                "entity_class": 9,
                "serial_number": serial_number,
                "model": model,
                "member_id": label.group(2),
            })
        # A stack can contain different S-series models. Match each entity to
        # its own explicit product name, rather than requiring identical models.
        if len(module_candidates) > 1:
            member_ids = [item["member_id"] for item in module_candidates]
            serials = [item["serial_number"].casefold() for item in module_candidates]
            if len(set(member_ids)) != len(member_ids) or len(set(serials)) != len(serials):
                huawei_metadata_complete = False
                diagnostics.append("huawei_module_member_identity_conflict")
            else:
                huawei_stack_candidates.extend(module_candidates)

    members: list[dict[str, Any]] = []
    absent_indices: list[int] = []
    failed_indices: set[int] = set()
    stable_for_confirmation = consistency not in {"changed", "restarted"}
    core_walks_complete = class_parent_columns_complete and serial_column.complete and serial_rows_valid
    can_confirm_any = core_walks_complete and stable_for_confirmation

    for index in discovered_indices:
        outcome, serial_number = standard_serials[index]
        if not relation_valid.get(index, False):
            failed_indices.add(index)
            continue
        if index in h3c_conflicts:
            failed_indices.add(index)
            continue
        if consistency in {"changed", "restarted"}:
            failed_indices.add(index)
            continue
        if not serial_column.complete or not serial_rows_valid:
            failed_indices.add(index)
            continue
        if outcome == "absent":
            absent_indices.append(index)
            continue
        if outcome != "valid" or index in h3c_conflicts:
            failed_indices.add(index)
            continue
        if not can_confirm_any:
            failed_indices.add(index)
            continue
        members.append({
            "entity_index": index,
            "serial_number": serial_number,
            "entity_name": names_by_index.get(index, "") if h3c else "",
            "entity_description": "",
            "model": "",
        })

    candidates: list[dict[str, Any]] = []
    for index, entity_class in sorted(class_rows.items()):
        if entity_class != 9 or parent_rows.get(index) != 0:
            continue
        if index not in serial_rows or not serial_column.complete or not serial_rows_valid:
            continue
        state, serial_number = _serial(serial_rows[index], serial_column.octets.get(str(index)))
        if state == "valid":
            candidates.append({
                "entity_index": index,
                "entity_class": 9,
                "serial_number": serial_number,
                "reason": "root_module_requires_verified_chassis_rule",
            })
    if h3c:
        for index in sorted(corroborated):
            diagnostics.append(f"h3c_private_serial_corroborated:{index}")
        for row in private_rows:
            serial_key = row["serial_number"].casefold()
            matched_entities = serial_to_entities.get(serial_key, [])
            if matched_entities and not any(index in h3c_conflicts for index in matched_entities):
                continue
            candidates.append({
                "entity_index": None,
                "entity_class": None,
                "serial_number": row["serial_number"],
                "reason": "h3c_private_frame_unmatched_or_conflicting",
                "source": row["source"],
                "private_index": row["index"],
            })
    for candidate in huawei_stack_candidates:
        candidates.append({
            **candidate,
            "reason": "huawei_s_series_member_requires_verified_stack_mapping",
        })

    # Enrich confirmed chassis only. H3C names fetched earlier are reused for
    # frame correlation; other metadata is fetched only after standard proof.
    async def enrich_member(member: dict[str, Any]) -> None:
        index = member["entity_index"]
        fields = (
            ("entity_name", _ENTITY_NAME),
            ("entity_description", _ENTITY_DESCRIPTION),
            ("model", _ENTITY_MODEL),
        )
        tasks: list[asyncio.Task] = []
        keys: list[str] = []
        for key, column in fields:
            if key == "entity_name" and member.get("entity_name"):
                continue
            keys.append(key)
            tasks.append(asyncio.create_task(read_text(f"{_ENTITY_BASE}.{column}.{index}")))
        values = await settle(tasks, deadline)
        for key, value in zip(keys, values):
            if isinstance(value, str) and value:
                member[key] = value

    if members:
        # A small worker pool avoids creating unbounded request tasks when a
        # device reports an unusually large number of chassis rows.
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for member in members:
            queue.put_nowait(member)

        async def enrich_worker() -> None:
            while True:
                try:
                    member = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await enrich_member(member)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(enrich_worker()) for _ in range(_MAX_IN_FLIGHT)]
        await settle(workers, deadline)

    serial_complete = (
        discovery_complete
        and serial_column.complete
        and serial_rows_valid
        and stable_for_confirmation
        and not candidates
        and (not huawei or huawei_metadata_complete)
        and bool(discovered_indices)
        and not failed_indices
        and not absent_indices
        and {member["entity_index"] for member in members} == set(discovered_indices)
        and len(members) == len(discovered_indices)
    )
    if serial_complete:
        status = "success"
    elif members or candidates or discovered_indices:
        status = "partial"
    else:
        status = "failed"
    return _read_result(
        status,
        observed_at,
        members=members,
        discovered_indices=discovered_indices,
        discovery_complete=discovery_complete,
        serial_complete=serial_complete,
        absent_indices=absent_indices,
        failed_indices=sorted(failed_indices),
        candidates=candidates,
        diagnostics=diagnostics,
        snapshot_consistency=consistency,
    )


def _snapshot_consistency(before: Mapping[str, _ScalarRead], after: Mapping[str, _ScalarRead]) -> str:
    """Return stable, unknown, changed, or restarted from standard scalars."""
    def integer(item: _ScalarRead | None) -> int | None:
        if item is None or not item.value:
            return None
        match = re.fullmatch(r"\s*(?:TimeTicks:\s*)?\(?\s*(\d+)\s*\)?(?:\s+.*)?", item.value, re.IGNORECASE)
        return int(match.group(1)) if match else None

    old_change = integer(before.get("last_change"))
    new_change = integer(after.get("last_change"))
    old_uptime = integer(before.get("uptime"))
    new_uptime = integer(after.get("uptime"))
    old_sample = before.get("uptime").sampled_at if before.get("uptime") else None
    new_sample = after.get("uptime").sampled_at if after.get("uptime") else None

    if old_uptime is not None and new_uptime is not None and old_sample is not None and new_sample is not None:
        elapsed = max(0.0, new_sample - old_sample)
        delta = (new_uptime - old_uptime) % (2**32)
        if abs(delta / 100.0 - elapsed) > max(5.0, elapsed * 0.2):
            return "restarted"
    if old_change is not None and new_change is not None and old_change != new_change:
        return "changed"
    if None in (old_change, new_change, old_uptime, new_uptime):
        return "unknown"
    return "stable"
