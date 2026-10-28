"""Read a device chassis model from the standard ENTITY-MIB tables."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Mapping

_ENTITY_PHYSICAL_MODEL_NAME_OID = "1.3.6.1.2.1.47.1.1.1.1.13"
_ENTITY_PHYSICAL_CLASS_OID = "1.3.6.1.2.1.47.1.1.1.1.5"
_ENTITY_PHYSICAL_CONTAINED_IN_OID = "1.3.6.1.2.1.47.1.1.1.1.4"
_WALK_TIMEOUT_SECONDS = 3
# H3C HCL S6850 agents expose 259 ENTITY-MIB rows. Allow larger physical
# inventories while keeping each walk bounded and rejecting partial tables.
_WALK_MAX_ROWS = 2000


def _entity_index(value: Any) -> int | None:
    text = str(value or "").strip().strip(".")
    if not re.fullmatch(r"\d+", text):
        return None
    index = int(text)
    return index if index > 0 else None


def _column_map(rows: Any) -> dict[int, str] | None:
    """Validate one complete walk and retain values by ENTITY-MIB index."""
    if not isinstance(rows, (list, tuple)) or not rows:
        return None
    if bool(getattr(rows, "truncated", False)) or len(rows) >= _WALK_MAX_ROWS:
        return None

    values: dict[int, str] = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            return None
        index = _entity_index(row[0])
        if index is None:
            return None
        value = str(row[1] if row[1] is not None else "").strip()
        previous = values.get(index)
        if previous is not None and previous != value:
            return None
        values[index] = value
    return values or None


def _entity_integer(value: Any) -> int | None:
    text = str(value or "").strip().casefold()
    if not text:
        return None
    if text == "chassis":
        return 3
    if text == "stack":
        return 11
    if text.isdigit():
        return int(text)
    enum_match = re.fullmatch(r"[a-z][a-z0-9-]*\s*\(\s*(\d+)\s*\)", text)
    if enum_match:
        return int(enum_match.group(1))
    return None


def _select_chassis_model(
    model_rows: Any,
    class_rows: Any,
    contained_in_rows: Any,
) -> str:
    """Select a model only when the ENTITY-MIB hierarchy identifies it safely."""
    models = _column_map(model_rows)
    classes = _column_map(class_rows)
    parents = _column_map(contained_in_rows)
    if models is None or classes is None or parents is None:
        return ""

    parsed_classes: dict[int, int] = {}
    for index, raw_class in classes.items():
        entity_class = _entity_integer(raw_class)
        if entity_class is None:
            return ""
        parsed_classes[index] = entity_class

    chassis_indexes = [
        index for index, entity_class in parsed_classes.items() if entity_class == 3
    ]
    if chassis_indexes:
        root_models = {
            models[index]
            for index in chassis_indexes
            if parents.get(index) is not None
            and _entity_integer(parents[index]) == 0
            and models.get(index, "")
        }
        if root_models:
            return next(iter(root_models)) if len(root_models) == 1 else ""

        # Without a root chassis, accept only one class-3 entity row. This
        # avoids treating a module or whichever row appeared first as chassis.
        if len(chassis_indexes) == 1:
            model = models.get(chassis_indexes[0], "")
            return model if model else ""
        return ""

    # Some agents expose only a logical stack row. Use it only when no chassis
    # rows exist and all root stack entries agree on one non-empty model.
    root_stack_models = {
        models[index]
        for index, entity_class in parsed_classes.items()
        if entity_class == 11
        and parents.get(index) is not None
        and _entity_integer(parents[index]) == 0
        and models.get(index, "")
    }
    return next(iter(root_stack_models)) if len(root_stack_models) == 1 else ""


def _walk_credential(settings: Mapping[str, Any], version: str) -> str | dict[str, str] | None:
    if version == "2c":
        community = str(settings.get("community") or "")
        return community or None

    username = str(settings.get("username") or "")
    if not username:
        return None
    return {
        "username": username,
        "security_level": str(settings.get("security_level") or ""),
        "auth_password": str(settings.get("auth_password") or ""),
        "auth_protocol": str(settings.get("auth_method") or ""),
        "priv_password": str(settings.get("priv_password") or ""),
        "priv_protocol": str(settings.get("priv_method") or ""),
        "context_name": str(settings.get("context_name") or ""),
    }


async def read_chassis_model(ip: str, settings: Mapping[str, Any]) -> str:
    """Read a chassis model using bounded SNMP walks; return empty on uncertainty."""
    version_value = str(settings.get("version") or "").strip().casefold()
    if version_value in {"2c", "v2c", "2"}:
        version = "2c"
    elif version_value in {"3", "v3", "snmpv3"}:
        version = "3"
    else:
        return ""

    credential = _walk_credential(settings, version)
    if credential is None:
        return ""
    try:
        port = int(settings.get("port") or 161)
    except (TypeError, ValueError):
        return ""
    if not 1 <= port <= 65535:
        return ""

    from services import snmp_service

    oids = (
        _ENTITY_PHYSICAL_MODEL_NAME_OID,
        _ENTITY_PHYSICAL_CLASS_OID,
        _ENTITY_PHYSICAL_CONTAINED_IN_OID,
    )
    try:
        results = await asyncio.gather(
            *(
                snmp_service._snmp_walk(
                    ip,
                    credential,
                    oid,
                    port=port,
                    timeout=_WALK_TIMEOUT_SECONDS,
                    max_rows=_WALK_MAX_ROWS,
                    version=version,
                    raise_on_error=True,
                )
                for oid in oids
            ),
            return_exceptions=True,
        )
    except asyncio.CancelledError:
        raise

    for result in results:
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, BaseException):
            return ""
    chassis_model = _select_chassis_model(results[0], results[1], results[2])
    if not chassis_model:
        return ""
    # ENTITY-MIB model strings sometimes include the manufacturer even
    # though the CMDB stores vendor separately. Normalize only a recognized
    # leading vendor label and preserve the product model itself.
    from services.snmp_discovery_service import normalize_model_name, normalize_vendor

    return normalize_model_name(normalize_vendor(chassis_model), chassis_model)


__all__ = ["read_chassis_model"]
