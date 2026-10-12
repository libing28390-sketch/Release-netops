"""Explicit, dry-run-first migration of legacy rack locations.

This module is intentionally not imported by application startup.  Operators
run it from ``backend/scripts/rackvision_backfill.py`` after taking the normal
PostgreSQL backup.  The default mode is report-only; ``apply=True`` performs
all accepted changes in the caller's transaction and leaves ambiguous rows in
the quality-issue table for manual resolution.
"""

from __future__ import annotations

from typing import Any

from services import rack_data_quality_service as quality
from services import rack_placement_service
from services import rack_service


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def _as_int(value: Any) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _legacy_location(row: dict[str, Any]) -> tuple[str, int | None]:
    rack_label = str(row.get("rack") or "").strip()
    start_u = _as_int(row.get("planned_start_u"))
    if start_u is None:
        raw_unit = str(row.get("rack_unit") or "").strip()
        if raw_unit.isdigit():
            start_u = _as_int(raw_unit)
        else:
            # Accept common forms such as U12 and U12-U14, but do not infer a
            # value from arbitrary descriptive text.
            import re
            match = re.match(r"^U\s*(\d+)(?:\s*[-~]\s*U?\d+)?$", raw_unit, re.IGNORECASE)
            if match:
                start_u = _as_int(match.group(1))
    return rack_label, start_u


def _resolve_rack(conn, *, rack_id: Any, rack_label: str) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    requested_id = str(rack_id or "").strip()
    requested_label = str(rack_label or "").strip()
    if requested_id:
        rows = conn.execute(
            "SELECT id, name, rack_name, rack_code FROM racks WHERE id = ? OR rack_code = ?",
            (requested_id, requested_id),
        ).fetchall()
    elif requested_label:
        rows = conn.execute(
            """SELECT id, name, rack_name, rack_code
                 FROM racks
                WHERE name = ? OR rack_name = ? OR rack_code = ?
                ORDER BY id""",
            (requested_label, requested_label, requested_label),
        ).fetchall()
    else:
        rows = []
    matches = [_row_to_dict(row) for row in rows]
    if len(matches) == 1:
        return str(matches[0]["id"]), None, matches
    if not matches:
        return None, "RACK_NOT_FOUND", matches
    return None, "RACK_NOT_UNIQUE", matches


def _issue(
    *,
    entity_type: str,
    entity_id: str,
    issue_code: str,
    details: dict[str, Any],
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "issue_code": issue_code,
        "severity": severity,
        "details": details,
    }


def _record_or_preview(conn, item: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    if apply:
        return quality.upsert_issue(
            conn,
            entity_type=item["entity_type"],
            entity_id=item["entity_id"],
            issue_code=item["issue_code"],
            severity=item["severity"],
            details=item["details"],
        )
    return item


def run_backfill(
    conn,
    *,
    rack_id: str = "",
    apply: bool = False,
    commit: bool = False,
) -> dict[str, Any]:
    """Report or apply safe legacy-location conversions.

    Returns counts suitable for a change record and a machine-readable list
    of issues.  When ``apply`` is true, ``commit`` defaults to false so the
    caller can still wrap the run in a backup/approval transaction explicitly.
    """
    normalized_rack_id = str(rack_id or "").strip()
    filters = " WHERE rd.rack_id = ?" if normalized_rack_id else ""
    rack_params: tuple[Any, ...] = (normalized_rack_id,) if normalized_rack_id else ()
    rack_device_rows = conn.execute(
        f"""SELECT rd.*, dt.u_height, dt.default_mount_kind, dt.dimension_status AS type_dimension_status
               FROM rack_devices rd
               LEFT JOIN device_types dt ON dt.id = rd.device_type_id
               {filters}
              ORDER BY rd.id""",
        rack_params,
    ).fetchall()

    # A rack-scoped run still needs to inspect label-only legacy rows because
    # those rows have no canonical rack_id to filter on.  Resolve and scope
    # them below instead of using ``rack_id = ? OR rack <> ''`` here, which
    # would silently process every labelled asset in the database.
    asset_filter = " WHERE pa.rack_id IS NOT NULL OR pa.rack <> ''"
    asset_params: tuple[Any, ...] = ()
    asset_rows = conn.execute(
        f"""SELECT pa.*
               FROM physical_assets pa
              {asset_filter}
              ORDER BY pa.id""",
        asset_params,
    ).fetchall()

    existing_asset_ids = {
        str(_row_to_dict(row).get("asset_id") or "").strip()
        for row in rack_device_rows
        if str(_row_to_dict(row).get("asset_id") or "").strip()
    }

    issues: list[dict[str, Any]] = []
    accepted = 0
    estimated = 0
    confirmed = 0
    unknown = 0
    invalid = 0

    # First normalize existing rack_devices rows.  This is the least
    # ambiguous source because it already identifies rack_id/device_type_id.
    for raw in rack_device_rows:
        row = _row_to_dict(raw)
        entity_id = str(row.get("id"))
        mount_kind = str(row.get("mount_kind") or row.get("default_mount_kind") or "u_mount").strip().lower()
        position = str(row.get("position") or ("front" if mount_kind == "u_mount" else "unknown")).strip().lower()
        start_u = _as_int(row.get("start_u"))
        height_u = _as_int(row.get("height_u")) or _as_int(row.get("u_height"))
        status = str(row.get("placement_status") or "").strip().lower()
        if not status:
            status = "estimated" if height_u else "unknown"
        result = rack_placement_service.validate(
            conn,
            rack_id=str(row.get("rack_id")),
            device_type_id=str(row.get("device_type_id") or ""),
            start_u=start_u,
            position=position,
            mount_kind=mount_kind,
            height_u=height_u,
            exclude_device_id=entity_id,
            location_note=row.get("location_note") or "",
            placement_status=status,
            placement_source="legacy_rack_device",
            dimension_status=row.get("dimension_status") or row.get("type_dimension_status") or "unknown",
            check_asset=False,
        )
        if not result.get("valid"):
            invalid += 1
            for message in result.get("errors") or []:
                text = str(message)
                code = "U_CONFLICT" if "conflict" in text.lower() else (
                    "U_OVERFLOW" if "capacity" in text.lower() or "exceed" in text.lower() else (
                        "UNKNOWN_HEIGHT" if "height" in text.lower() else "INVALID_POSITION"
                    )
                )
                issues.append(_issue(
                    entity_type="rack_device",
                    entity_id=entity_id,
                    issue_code=code,
                    details={"message": text, "source": "rack_devices", "row": row},
                ))
            continue
        accepted += 1
        if status == "confirmed":
            confirmed += 1
        elif status == "estimated":
            estimated += 1
        else:
            unknown += 1
        if apply:
            try:
                rack_service.update_rack_device(
                    conn,
                    entity_id,
                    mount_kind=result["normalized"]["mount_kind"],
                    position=result["normalized"]["position"],
                    start_u=result["normalized"]["start_u"],
                    height_u=result["normalized"]["height_u"],
                    placement_status=result["normalized"]["placement_status"],
                    placement_source="legacy_rack_device",
                    dimension_status=result["normalized"]["dimension_status"],
                    location_note=result["normalized"]["location_note"],
                    model_key=result["normalized"]["model_key"],
                    commit=False,
                )
            except ValueError as exc:
                invalid += 1
                accepted -= 1
                issues.append(_issue(
                    entity_type="rack_device",
                    entity_id=entity_id,
                    issue_code="LEGACY_LOCATION_CONFLICT",
                    details={"message": str(exc), "source": "rack_devices", "row": row},
                ))

    # Then materialize physical_assets rows that have a legacy location but no
    # rack_devices installation. Never create a placement for an ambiguous or
    # unknown source location.
    for raw in asset_rows:
        asset = _row_to_dict(raw)
        asset_id = str(asset.get("id") or "").strip()
        if not asset_id or asset_id in existing_asset_ids:
            continue
        label, start_u = _legacy_location(asset)
        canonical_rack_id = str(asset.get("rack_id") or "").strip()
        if not canonical_rack_id and not label:
            continue
        if normalized_rack_id and canonical_rack_id and canonical_rack_id != normalized_rack_id:
            continue
        resolved_rack_id, resolution_issue, matches = _resolve_rack(
            conn,
            rack_id=canonical_rack_id,
            rack_label=label,
        )
        if normalized_rack_id and resolved_rack_id and resolved_rack_id != normalized_rack_id:
            continue
        if resolution_issue:
            invalid += 1
            issues.append(_issue(
                entity_type="physical_asset",
                entity_id=asset_id,
                issue_code=resolution_issue,
                details={"rack": label, "rack_id": canonical_rack_id, "matches": matches},
            ))
            continue
        dt = conn.execute(
            """SELECT id, u_height, default_mount_kind, dimension_status
                 FROM device_types WHERE vendor = ? AND model = ?""",
            (str(asset.get("vendor") or "").strip(), str(asset.get("model") or "").strip()),
        ).fetchone()
        if not dt:
            invalid += 1
            issues.append(_issue(
                entity_type="physical_asset",
                entity_id=asset_id,
                issue_code="DEVICE_TYPE_NOT_FOUND",
                details={"vendor": asset.get("vendor"), "model": asset.get("model")},
            ))
            continue
        device_type = _row_to_dict(dt)
        explicit_mount = str(asset.get("rack_mount_kind") or "").strip().lower()
        mount_kind = explicit_mount or str(device_type.get("default_mount_kind") or "u_mount").lower()
        explicit_position = str(asset.get("rack_position") or "").strip().lower()
        position = explicit_position or ("front" if mount_kind == "u_mount" else "unknown")
        if mount_kind == "u_mount" and start_u is None:
            invalid += 1
            issues.append(_issue(
                entity_type="physical_asset",
                entity_id=asset_id,
                issue_code="UNKNOWN_HEIGHT" if not device_type.get("u_height") else "INVALID_POSITION",
                details={"rack": label, "planned_start_u": asset.get("planned_start_u"), "rack_unit": asset.get("rack_unit")},
            ))
            continue
        height_u = _as_int(asset.get("rack_height_u")) or _as_int(asset.get("u_height")) or _as_int(device_type.get("u_height"))
        result = rack_placement_service.validate(
            conn,
            rack_id=str(resolved_rack_id),
            device_type_id=str(device_type["id"]),
            start_u=start_u,
            position=position,
            mount_kind=mount_kind,
            height_u=height_u,
            asset_id=asset_id,
            location_note=asset.get("rack_location_note") or "",
            placement_status=asset.get("rack_placement_status") or "estimated",
            placement_source="legacy_asset",
            dimension_status=asset.get("rack_dimension_status") or device_type.get("dimension_status") or "unknown",
            check_asset=True,
        )
        if not result.get("valid"):
            invalid += 1
            for message in result.get("errors") or []:
                text = str(message)
                code = "DUPLICATE_ASSET_INSTALLATION" if "已上架" in text or "duplicate" in text.lower() else (
                    "U_CONFLICT" if "conflict" in text.lower() else (
                        "U_OVERFLOW" if "capacity" in text.lower() or "exceed" in text.lower() else "INVALID_POSITION"
                    )
                )
                issues.append(_issue(
                    entity_type="physical_asset",
                    entity_id=asset_id,
                    issue_code=code,
                    details={"message": text, "source": "physical_assets", "rack_id": resolved_rack_id},
                ))
            continue
        accepted += 1
        estimated += 1
        if apply:
            try:
                rack_service.create_rack_device(
                    conn,
                    name=str(asset.get("hostname") or asset.get("asset_tag") or asset_id),
                    rack_id=str(resolved_rack_id),
                    device_type_id=str(device_type["id"]),
                    start_u=result["normalized"]["start_u"],
                    position=result["normalized"]["position"],
                    mount_kind=result["normalized"]["mount_kind"],
                    height_u=result["normalized"]["height_u"],
                    placement_status=result["normalized"]["placement_status"],
                    placement_source="legacy_asset",
                    dimension_status=result["normalized"]["dimension_status"],
                    location_note=result["normalized"]["location_note"],
                    model_key=result["normalized"]["model_key"],
                    serial_number=str(asset.get("serial_number") or ""),
                    asset_id=asset_id,
                    status=str(asset.get("status") or "active"),
                    commit=False,
                )
            except ValueError as exc:
                invalid += 1
                accepted -= 1
                issues.append(_issue(
                    entity_type="physical_asset",
                    entity_id=asset_id,
                    issue_code="LEGACY_LOCATION_CONFLICT",
                    details={"message": str(exc), "source": "physical_assets", "rack_id": resolved_rack_id},
                ))

    persisted_issues = []
    if apply:
        for item in issues:
            persisted_issues.append(_record_or_preview(conn, item, apply=True))
        if commit:
            conn.commit()

    return {
        "mode": "apply" if apply else "dry_run",
        "rack_id": normalized_rack_id or None,
        "source_rack_device_rows": len(rack_device_rows),
        "source_asset_rows": len(asset_rows),
        "accepted": accepted,
        "confirmed": confirmed,
        "estimated": estimated,
        "unknown": unknown,
        "invalid": invalid,
        "issues": persisted_issues if apply else issues,
        "issue_count": len(issues),
    }


__all__ = ["run_backfill"]
