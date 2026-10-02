"""Canonical rack placement rules and persistence helpers.

``rack_devices`` is the source of truth for installation location.  The
service owns placement validation, asset uniqueness, rack/asset projection
synchronization, and layout revision bumps so the asset API, rack API and
future import jobs cannot drift into separate interpretations of a rack.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

MOUNT_KINDS = frozenset({"u_mount", "zero_u", "side_mount", "floor", "unknown"})
POSITIONS = frozenset({"front", "rear", "full_depth", "left_side", "right_side", "unknown"})
PLACEMENT_STATUSES = frozenset({"confirmed", "estimated", "unknown", "invalid"})
PLACEMENT_SOURCES = frozenset({
    "manual", "asset_import", "legacy_rack_device", "legacy_asset", "discovery", "migration",
})
DIMENSION_STATUSES = frozenset({"confirmed", "estimated", "unknown", "pending_verification"})


class RackPlacementError(ValueError):
    """A safe, serializable domain failure for rack placement operations."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if hasattr(row, "keys"):
        try:
            value = row[key]
            return default if value is None else value
        except (KeyError, IndexError, TypeError):
            return default
    if isinstance(row, dict):
        value = row.get(key, default)
        return default if value is None else value
    return default


def _dict_row(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_mount_kind(value: Any) -> str:
    mount_kind = _normalize_text(value).lower()
    return mount_kind or "u_mount"


def _normalize_position(value: Any, mount_kind: str) -> str:
    position = _normalize_text(value).lower()
    if position:
        return position
    if mount_kind == "side_mount":
        return "unknown"
    if mount_kind in {"zero_u", "floor", "unknown"}:
        return "unknown"
    return "front"


def _effective_height(raw_height: Any, device_type: dict[str, Any]) -> tuple[int | None, bool]:
    """Return height and whether it was inherited from the type template."""
    if raw_height not in (None, ""):
        try:
            height = int(raw_height)
        except (TypeError, ValueError):
            return None, False
        return (height if height >= 1 else None), False
    try:
        type_height = int(device_type.get("u_height") or 0)
    except (TypeError, ValueError):
        type_height = 0
    return (type_height if type_height >= 1 else None), True


def _load_rack(conn, rack_id: str) -> dict[str, Any]:
    row = conn.execute(
        """SELECT id, name, rack_name, rack_code, total_u, mount_policy,
                  allow_front_rear_mount, layout_revision
             FROM racks WHERE id = ?""",
        (rack_id,),
    ).fetchone()
    if not row:
        raise RackPlacementError(
            "RACK_NOT_FOUND",
            f"Rack not found: {rack_id}",
            status_code=404,
            details={"rack_id": rack_id},
        )
    rack = _dict_row(row)
    if not _normalize_text(rack.get("mount_policy")):
        rack["mount_policy"] = "front_rear" if rack.get("allow_front_rear_mount", 1) else "front_only"
    return rack


def _load_device_type(conn, device_type_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM device_types WHERE id = ?", (device_type_id,)).fetchone()
    if not row:
        raise RackPlacementError(
            "DEVICE_TYPE_NOT_FOUND",
            f"DeviceType not found: {device_type_id}",
            status_code=404,
            details={"device_type_id": device_type_id},
        )
    return _dict_row(row)


def _lock_rack(conn, rack_id: str) -> None:
    from database import _USE_PG

    if _USE_PG:
        conn.execute("SELECT id FROM racks WHERE id = ? FOR UPDATE", (rack_id,))


def _lock_asset_identity(conn, asset_id: str) -> None:
    normalized = _normalize_text(asset_id)
    if not normalized:
        return
    from database import _USE_PG

    if _USE_PG:
        # Serialize even legacy/free-text asset IDs that have no physical_assets
        # row.  The physical row lock adds protection for canonical CMDB data.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (normalized,))
        conn.execute("SELECT id FROM physical_assets WHERE id = ? FOR UPDATE", (normalized,))


def ensure_asset_available(conn, asset_id: str, *, exclude_device_id: str = "") -> None:
    normalized = _normalize_text(asset_id)
    if not normalized:
        return
    _lock_asset_identity(conn, normalized)
    query = """SELECT id, name, rack_id FROM rack_devices
                 WHERE asset_id IS NOT NULL AND TRIM(asset_id) = ?"""
    params: list[Any] = [normalized]
    if exclude_device_id:
        query += " AND id != ?"
        params.append(exclude_device_id)
    existing = conn.execute(query + " LIMIT 1", tuple(params)).fetchone()
    if existing:
        row = _dict_row(existing)
        raise ValueError(
            f"资产已上架：'{normalized}' 当前位于设备 '{row.get('name') or row.get('id')}'，"
            "不能重复安装到其他机柜。"
        )


def _placement_conflicts(
    conn,
    *,
    rack_id: str,
    position: str,
    start_u: int,
    end_u: int,
    exclude_device_id: str = "",
) -> list[dict[str, Any]]:
    query = """SELECT rd.id, rd.name, rd.start_u, rd.height_u,
                      rd.position, rd.mount_kind, rd.placement_status,
                      dt.u_height
                 FROM rack_devices rd
                 JOIN device_types dt ON dt.id = rd.device_type_id
                WHERE rd.rack_id = ?"""
    params: list[Any] = [rack_id]
    if exclude_device_id:
        query += " AND rd.id != ?"
        params.append(exclude_device_id)

    conflicts = []
    for raw in conn.execute(query, tuple(params)).fetchall():
        row = _dict_row(raw)
        other_mount = _normalize_mount_kind(row.get("mount_kind"))
        other_start = row.get("start_u")
        if other_mount != "u_mount" or other_start in (None, ""):
            continue
        try:
            other_start_int = int(other_start)
            other_height = int(row.get("height_u") or row.get("u_height") or 0)
        except (TypeError, ValueError):
            continue
        if other_start_int < 1 or other_height < 1:
            continue
        other_end = other_start_int + other_height - 1
        if other_end < start_u or end_u < other_start_int:
            continue
        other_position = _normalize_position(row.get("position"), other_mount)
        if (
            position == "full_depth"
            or other_position == "full_depth"
            or position == other_position
        ):
            conflicts.append({
                "id": row.get("id"),
                "name": row.get("name") or row.get("id"),
                "start_u": other_start_int,
                "end_u": other_end,
                "position": other_position,
            })
    return conflicts


def validate(
    conn,
    *,
    rack_id: str,
    device_type_id: str,
    start_u: int | None = None,
    position: str | None = None,
    mount_kind: str | None = None,
    height_u: int | None = None,
    asset_id: str = "",
    exclude_device_id: str = "",
    location_note: str = "",
    placement_status: str | None = None,
    placement_source: str | None = None,
    dimension_status: str | None = None,
    model_key: str = "",
    check_asset: bool = True,
    require_asset_record: bool = False,
) -> dict[str, Any]:
    """Validate a placement without mutating the database.

    The returned normalized payload is the exact shape consumed by ``install``
    and ``move``.  In particular, non-U placements never receive a synthetic
    U1/start or 1U height.
    """
    errors: list[str] = []
    warnings: list[str] = []
    try:
        rack = _load_rack(conn, _normalize_text(rack_id))
    except ValueError as exc:
        return {"valid": False, "errors": [str(exc)], "warnings": [], "normalized": {}}

    normalized_device_type_id = _normalize_text(device_type_id)
    if normalized_device_type_id:
        try:
            device_type = _load_device_type(conn, normalized_device_type_id)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "warnings": [], "normalized": {}}
    else:
        # Compatibility callers of the old rack_service helper already have
        # an explicit height and only need the shared rack/conflict rules.
        device_type = {"u_height": height_u, "default_mount_kind": "u_mount", "dimension_status": "unknown"}

    normalized_mount = _normalize_mount_kind(mount_kind or device_type.get("default_mount_kind"))
    normalized_position = _normalize_position(position, normalized_mount)
    note = _normalize_text(location_note)
    status = _normalize_text(placement_status).lower() or ""
    source = _normalize_text(placement_source).lower() or "manual"
    dimension = _normalize_text(dimension_status).lower() or _normalize_text(device_type.get("dimension_status")).lower() or "unknown"
    if normalized_mount not in MOUNT_KINDS:
        errors.append(f"mount_kind must be one of {sorted(MOUNT_KINDS)}")
    if normalized_position not in POSITIONS:
        errors.append(f"position must be one of {sorted(POSITIONS)}")
    if status and status not in PLACEMENT_STATUSES:
        errors.append(f"placement_status must be one of {sorted(PLACEMENT_STATUSES)}")
    if source not in PLACEMENT_SOURCES:
        errors.append(f"placement_source must be one of {sorted(PLACEMENT_SOURCES)}")
    if dimension not in DIMENSION_STATUSES:
        errors.append(f"dimension_status must be one of {sorted(DIMENSION_STATUSES)}")

    inherited_height = False
    effective_height: int | None = None
    normalized_start: int | None = None
    end_u: int | None = None
    if normalized_mount == "u_mount":
        if normalized_position not in {"front", "rear", "full_depth"}:
            errors.append("u_mount placement must use front, rear, or full_depth position")
        if start_u in (None, ""):
            errors.append("u_mount placement requires start_u")
        else:
            try:
                normalized_start = int(start_u)
            except (TypeError, ValueError):
                errors.append("start_u must be an integer")
            if normalized_start is not None and normalized_start < 1:
                errors.append("start_u must be >= 1")
        effective_height, inherited_height = _effective_height(height_u, device_type)
        if effective_height is None:
            errors.append("u_mount placement requires a known height_u")
        if normalized_start is not None and effective_height is not None:
            end_u = normalized_start + effective_height - 1
            try:
                total_u = int(rack.get("total_u") or 0)
            except (TypeError, ValueError):
                total_u = 0
            if end_u > total_u:
                errors.append(f"placement exceeds rack capacity: U{normalized_start}-U{end_u}, rack has {total_u}U")
            if not errors:
                conflicts = _placement_conflicts(
                    conn,
                    rack_id=_normalize_text(rack_id),
                    position=normalized_position,
                    start_u=normalized_start,
                    end_u=end_u,
                    exclude_device_id=exclude_device_id,
                )
                for conflict in conflicts:
                    errors.append(
                        f"U conflict with '{conflict['name']}' ({conflict['position']} "
                        f"U{conflict['start_u']}-U{conflict['end_u']})"
                    )
        if inherited_height and not errors:
            warnings.append("height_u inherited from device type; verify the physical dimensions")
        if not status:
            status = "estimated" if inherited_height else "confirmed"
    else:
        # 0U, side-mounted, floor and unknown devices are visible placements,
        # but do not consume standard U capacity.
        if start_u not in (None, ""):
            warnings.append("start_u ignored for non-U placement")
        normalized_start = None
        effective_height = None
        end_u = None
        if normalized_mount == "side_mount" and normalized_position not in {"left_side", "right_side"}:
            errors.append("side_mount placement requires left_side or right_side position")
        if normalized_mount == "zero_u" and normalized_position not in {"rear", "left_side", "right_side", "unknown"}:
            errors.append("zero_u placement requires rear, left_side, right_side, or unknown position")
        if normalized_mount == "zero_u" and normalized_position == "unknown" and not note:
            errors.append("zero_u placement requires an explicit position or location_note")
        if normalized_mount == "floor" and not note:
            errors.append("floor placement requires location_note")
        if normalized_mount == "unknown" and normalized_position == "unknown" and not note:
            warnings.append("unknown placement should include location_note for physical verification")
        if not status:
            status = "unknown"

    if normalized_position in {"rear", "full_depth"} and rack.get("mount_policy") == "front_only":
        errors.append("rack mount_policy is front_only; rear/full_depth placement is not allowed")

    if check_asset:
        try:
            ensure_asset_available(conn, asset_id, exclude_device_id=exclude_device_id)
        except ValueError as exc:
            errors.append(str(exc))
    if require_asset_record and _normalize_text(asset_id):
        asset_row = conn.execute(
            "SELECT id FROM physical_assets WHERE id = ?",
            (_normalize_text(asset_id),),
        ).fetchone()
        if not asset_row:
            errors.append(f"Asset not found: {_normalize_text(asset_id)}")

    if normalized_mount == "u_mount" and status == "unknown" and not errors:
        warnings.append("U placement has unknown status; verify the imported physical location")
    if normalized_mount != "u_mount" and not errors and normalized_mount in {"zero_u", "side_mount", "unknown"}:
        warnings.append("placement is visible but excluded from standard U capacity")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "normalized": {
            "mount_kind": normalized_mount,
            "position": normalized_position,
            "start_u": normalized_start,
            "height_u": effective_height,
            "end_u": end_u,
            "placement_status": status,
            "placement_source": source,
            "dimension_status": dimension,
            "location_note": note,
            "model_key": _normalize_text(model_key) or f"{_normalize_text(device_type.get('vendor'))}:{_normalize_text(device_type.get('model'))}",
        },
    }


def raise_validation_failure(result: dict[str, Any]) -> None:
    """Raise a stable domain error for an invalid placement result.

    Validation is intentionally side-effect free, but callers still need the
    same error taxonomy as install/move.  Keep the classifier public so HTTP
    adapters do not reach into a private implementation detail.
    """
    if result.get("valid"):
        return
    errors = result.get("errors") or ["invalid rack placement"]
    normalized = result.get("normalized") or {}
    message = "; ".join(str(error) for error in errors)
    lowered = message.casefold()
    if "asset not found" in lowered or "资产不存在" in lowered:
        code, status_code = "ASSET_NOT_FOUND", 404
    elif ("asset" in lowered or "资产" in lowered) and any(token in lowered for token in ("上架", "already installed", "重复安装")):
        code, status_code = "ASSET_ALREADY_INSTALLED", 409
    elif "exceeds rack capacity" in lowered or "overflow" in lowered:
        code, status_code = "RACK_U_OVERFLOW", 409
    elif "u conflict" in lowered or "冲突" in lowered:
        code = (
            "FULL_DEPTH_CONFLICT"
            if normalized.get("position") == "full_depth" or "full_depth" in lowered
            else "RACK_U_CONFLICT"
        )
        status_code = 409
    elif "zero_u placement requires" in lowered:
        code, status_code = "ZERO_U_POSITION_REQUIRED", 422
    elif "front_only" in lowered or "position" in lowered and "requires" in lowered:
        code, status_code = "POSITION_NOT_ALLOWED", 422
    elif "device type not found" in lowered:
        code, status_code = "DEVICE_TYPE_NOT_FOUND", 404
    elif "rack not found" in lowered:
        code, status_code = "RACK_NOT_FOUND", 404
    else:
        code, status_code = "VALIDATION_ERROR", 422
    raise RackPlacementError(
        code,
        message,
        status_code=status_code,
        details={
            "errors": [str(error) for error in errors],
            "warnings": [str(warning) for warning in (result.get("warnings") or [])],
            "normalized": normalized,
        },
    )


# Kept for older internal callers while the public name becomes the canonical
# adapter used by APIs and import jobs.
_raise_validation_failure = raise_validation_failure


def sync_asset_projection(
    conn,
    *,
    asset_id: str,
    rack: dict[str, Any] | None,
    placement: dict[str, Any] | None,
) -> None:
    """Mirror canonical placement to physical_assets in the same transaction."""
    normalized_asset = _normalize_text(asset_id)
    if not normalized_asset:
        return

    # Legacy/free-text rack devices may intentionally have no physical asset
    # row.  They remain readable in rack_devices without creating a phantom
    # asset projection.
    asset_row = conn.execute("SELECT id FROM physical_assets WHERE id = ?", (normalized_asset,)).fetchone()
    if not asset_row:
        return

    now = _utc_now()
    if not rack or not placement:
        conn.execute(
            """UPDATE physical_assets
                  SET rack_id = NULL, rack_position = NULL, rack_mount_kind = NULL,
                      rack_location_status = 'unplaced', rack = '', rack_unit = '',
                      planned_start_u = NULL, updated_at = ?
                WHERE id = ?""",
            (now, normalized_asset),
        )
        return

    mount_kind = placement.get("mount_kind") or "unknown"
    position = placement.get("position") or "unknown"
    start_u = placement.get("start_u")
    height_u = placement.get("height_u")
    end_u = placement.get("end_u")
    if mount_kind == "u_mount" and start_u is not None:
        legacy_unit = f"U{start_u}" if not height_u or int(height_u) <= 1 else f"U{start_u}-U{end_u}"
        planned_start = int(start_u)
    else:
        legacy_unit = position
        planned_start = None
    rack_label = _normalize_text(rack.get("name") or rack.get("rack_name") or rack.get("rack_code"))
    status = placement.get("placement_status") or "unknown"
    conn.execute(
        """UPDATE physical_assets
              SET rack_id = ?, rack_position = ?, rack_mount_kind = ?,
                  rack_location_status = ?, rack = ?, rack_unit = ?,
                  planned_start_u = ?, updated_at = ?
            WHERE id = ?""",
        (
            rack.get("id"), position, mount_kind, status, rack_label,
            legacy_unit, planned_start, now, normalized_asset,
        ),
    )


def _bump_layout_revision(conn, rack_ids: set[str]) -> None:
    now = _utc_now()
    for rack_id in sorted({_normalize_text(value) for value in rack_ids if _normalize_text(value)}):
        conn.execute(
            """UPDATE racks
                  SET layout_revision = COALESCE(layout_revision, 0) + 1,
                      updated_at = ?
                WHERE id = ?""",
            (now, rack_id),
        )


def install(
    conn,
    *,
    name: str,
    rack_id: str,
    device_type_id: str,
    start_u: int | None = None,
    position: str = "front",
    mount_kind: str | None = None,
    height_u: int | None = None,
    placement_status: str | None = None,
    placement_source: str = "manual",
    dimension_status: str | None = None,
    location_note: str = "",
    model_key: str = "",
    status: str = "active",
    serial_number: str = "",
    asset_id: str = "",
    require_asset_record: bool = False,
    commit: bool = True,
) -> dict[str, Any]:
    _lock_rack(conn, rack_id)
    rack = _load_rack(conn, rack_id)
    device_type = _load_device_type(conn, device_type_id)
    result = validate(
        conn,
        rack_id=rack_id,
        device_type_id=device_type_id,
        start_u=start_u,
        position=position,
        mount_kind=mount_kind,
        height_u=height_u,
        asset_id=asset_id,
        location_note=location_note,
        placement_status=placement_status,
        placement_source=placement_source,
        dimension_status=dimension_status,
        model_key=model_key,
        require_asset_record=require_asset_record,
    )
    raise_validation_failure(result)
    placement = result["normalized"]
    device_id = str(uuid.uuid4())
    now = _utc_now()
    conn.execute(
        """INSERT INTO rack_devices (
               id, name, rack_id, device_type_id, start_u, position, mount_kind,
               height_u, placement_status, placement_source, dimension_status,
               location_note, model_key, status, serial_number, asset_id,
               created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            device_id, _normalize_text(name), rack_id, device_type_id,
            placement.get("start_u"), placement.get("position"), placement.get("mount_kind"),
            placement.get("height_u"), placement.get("placement_status"), placement.get("placement_source"),
            placement.get("dimension_status"), placement.get("location_note"), placement.get("model_key"),
            _normalize_text(status) or "active", _normalize_text(serial_number), _normalize_text(asset_id),
            now, now,
        ),
    )
    sync_asset_projection(conn, asset_id=asset_id, rack=rack, placement=placement)
    _bump_layout_revision(conn, {rack_id})
    if commit:
        conn.commit()
    return get_placement(conn, device_id)


def get_placement(conn, device_id: str) -> dict[str, Any]:
    row = conn.execute(
        """SELECT rd.*, dt.model, dt.vendor, dt.u_height, dt.device_role,
                         dt.is_full_depth, dt.power_watts, dt.depth_class,
                         dt.width_mm, dt.depth_mm, dt.height_mm, dt.weight_kg,
                         dt.dimension_status AS type_dimension_status,
                         dt.default_mount_kind, dt.model_family, dt.catalog_key,
                         pa.asset_tag AS physical_asset_tag,
                         pa.serial_number AS physical_serial_number,
                         pa.hostname AS physical_hostname,
                         (SELECT d.id FROM devices d
                           WHERE d.asset_id = rd.asset_id
                           ORDER BY d.id LIMIT 1) AS network_device_id,
                         (SELECT d.hostname FROM devices d
                           WHERE d.asset_id = rd.asset_id
                           ORDER BY d.id LIMIT 1) AS network_hostname,
                         (SELECT d.sn FROM devices d
                           WHERE d.asset_id = rd.asset_id
                           ORDER BY d.id LIMIT 1) AS network_sn
                    FROM rack_devices rd
                    JOIN device_types dt ON dt.id = rd.device_type_id
                    LEFT JOIN physical_assets pa ON pa.id = rd.asset_id
                   WHERE rd.id = ?""",
        (device_id,),
    ).fetchone()
    if not row:
        raise RackPlacementError(
            "RACK_DEVICE_NOT_FOUND",
            f"Rack device not found: {device_id}",
            status_code=404,
            details={"placement_id": device_id},
        )
    return _dict_row(row)


def move(conn, device_id: str, *, commit: bool = True, **fields) -> dict[str, Any]:
    existing = get_placement(conn, device_id)
    require_asset_record = bool(fields.pop("require_asset_record", False))
    old_rack_id = _normalize_text(existing.get("rack_id"))
    new_rack_id = _normalize_text(fields.get("rack_id") or old_rack_id)
    rack_ids = {old_rack_id, new_rack_id}
    # Lock both parents in deterministic order to avoid deadlocks when two
    # concurrent moves exchange racks.
    for rack_id in sorted(rack_ids):
        if rack_id:
            _lock_rack(conn, rack_id)
    rack = _load_rack(conn, new_rack_id)
    device_type_id = _normalize_text(fields.get("device_type_id") or existing.get("device_type_id"))
    result = validate(
        conn,
        rack_id=new_rack_id,
        device_type_id=device_type_id,
        start_u=fields["start_u"] if "start_u" in fields else existing.get("start_u"),
        position=fields.get("position") or existing.get("position"),
        mount_kind=fields.get("mount_kind") or existing.get("mount_kind"),
        height_u=fields["height_u"] if "height_u" in fields else existing.get("height_u"),
        asset_id=fields["asset_id"] if "asset_id" in fields else existing.get("asset_id") or "",
        exclude_device_id=device_id,
        location_note=fields.get("location_note") if "location_note" in fields else existing.get("location_note") or "",
        placement_status=fields.get("placement_status") if "placement_status" in fields else existing.get("placement_status"),
        placement_source=fields.get("placement_source") if "placement_source" in fields else existing.get("placement_source"),
        dimension_status=fields.get("dimension_status") if "dimension_status" in fields else existing.get("dimension_status"),
        model_key=fields.get("model_key") if "model_key" in fields else existing.get("model_key") or "",
        require_asset_record=require_asset_record,
    )
    raise_validation_failure(result)
    placement = result["normalized"]
    update_fields = {
        "name": _normalize_text(fields.get("name")) if "name" in fields else existing.get("name") or "",
        "rack_id": new_rack_id,
        "device_type_id": device_type_id,
        "start_u": placement.get("start_u"),
        "position": placement.get("position"),
        "mount_kind": placement.get("mount_kind"),
        "height_u": placement.get("height_u"),
        "placement_status": placement.get("placement_status"),
        "placement_source": placement.get("placement_source"),
        "dimension_status": placement.get("dimension_status"),
        "location_note": placement.get("location_note"),
        "model_key": placement.get("model_key"),
        "status": fields.get("status") if "status" in fields else existing.get("status") or "active",
        "serial_number": fields.get("serial_number") if "serial_number" in fields else existing.get("serial_number") or "",
        "asset_id": _normalize_text(fields.get("asset_id")) if "asset_id" in fields else existing.get("asset_id") or "",
    }
    assignments = ", ".join(f"{key} = ?" for key in update_fields)
    conn.execute(
        f"UPDATE rack_devices SET {assignments}, updated_at = ? WHERE id = ?",
        (*update_fields.values(), _utc_now(), device_id),
    )
    asset_id = update_fields["asset_id"]
    if old_rack_id != new_rack_id:
        # A single asset can only have one canonical installation.  Updating
        # the projection to the new rack is sufficient; old rack occupancy is
        # derived from the updated rack_devices row.
        pass
    sync_asset_projection(conn, asset_id=asset_id, rack=rack, placement=placement)
    _bump_layout_revision(conn, rack_ids)
    if commit:
        conn.commit()
    return get_placement(conn, device_id)


def update(conn, device_id: str, *, commit: bool = True, **fields) -> dict[str, Any]:
    return move(conn, device_id, commit=commit, **fields)


def uninstall(conn, device_id: str, *, commit: bool = True) -> None:
    existing = get_placement(conn, device_id)
    rack_id = _normalize_text(existing.get("rack_id"))
    _lock_rack(conn, rack_id)
    conn.execute("DELETE FROM rack_devices WHERE id = ?", (device_id,))
    sync_asset_projection(conn, asset_id=existing.get("asset_id") or "", rack=None, placement=None)
    _bump_layout_revision(conn, {rack_id})
    if commit:
        conn.commit()


__all__ = [
    "DIMENSION_STATUSES", "MOUNT_KINDS", "PLACEMENT_SOURCES", "PLACEMENT_STATUSES", "POSITIONS",
    "RackPlacementError",
    "ensure_asset_available", "get_placement", "install", "move", "sync_asset_projection",
    "uninstall", "update", "validate",
]
