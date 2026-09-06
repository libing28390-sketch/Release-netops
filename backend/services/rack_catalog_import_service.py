"""Dry-run-first import of the reviewed RackVision device catalog.

The workbook-derived catalog is a source artifact, not a replacement for the
CMDB.  This service deliberately imports only the network-device sheet into
``device_types`` and keeps the operation additive:

* vendor/model identity is never rewritten;
* non-empty operator-maintained fields are never overwritten;
* missing catalog metadata may be filled in when it is unambiguous;
* dimension conflicts are reported and left for review; and
* no database write happens unless the caller explicitly requests ``apply``.

The service accepts a connection from the caller so an API/use-case layer can
own the transaction boundary.  The maintenance CLI uses the same boundary and
commits only for ``--apply``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_DEVICE_ROLES = {
    "switch",
    "router",
    "firewall",
    "server",
    "storage",
    "pdu",
    "ups",
    "patch_panel",
    "other",
}
DIMENSION_STATUSES = {"confirmed", "estimated", "unknown", "pending_verification"}
MOUNT_KINDS = {"u_mount", "zero_u", "side_mount", "floor", "unknown"}
DEPTH_CLASSES = {"half", "full", "unknown"}


class RackCatalogImportError(ValueError):
    """Raised when the machine-readable catalog cannot be safely imported."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _key(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _positive_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _role(value: Any) -> str:
    candidate = _text(value).casefold()
    return candidate if candidate in ALLOWED_DEVICE_ROLES else "other"


def _normalize_record(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RackCatalogImportError(f"catalog row {index} must be an object")

    vendor = _key(raw.get("vendor"))
    model = _text(raw.get("exact_model"))
    catalog_key = _text(raw.get("catalog_key"))
    if not vendor or not model or not catalog_key:
        raise RackCatalogImportError(
            f"catalog row {index} requires vendor, exact_model and catalog_key"
        )

    height_u = _positive_int(raw.get("height_u"))
    dimension_status = _text(raw.get("dimension_status")).casefold() or "unknown"
    if dimension_status not in DIMENSION_STATUSES:
        raise RackCatalogImportError(
            f"catalog row {index} has invalid dimension_status={dimension_status!r}"
        )

    widths = {
        field: _positive_int(raw.get(field))
        for field in ("width_mm", "depth_mm", "height_mm")
    }
    return {
        "catalog_key": catalog_key,
        "vendor": vendor,
        "model": model,
        "device_role": _role(raw.get("device_type")),
        # ``0`` is intentional for an unknown height.  It prevents the legacy
        # default of 1U from turning an unverified model into a valid mount.
        "u_height": height_u or 0,
        "is_full_depth": 0,
        "depth_class": "unknown",
        **widths,
        "weight_kg": None,
        "dimension_status": dimension_status,
        "default_mount_kind": "u_mount" if height_u else "unknown",
        "model_family": _text(raw.get("family")),
        "description": _text(raw.get("notes")) or _text(raw.get("blender_features")),
        "source_row": raw.get("source_row", index),
        "source_title": _text(raw.get("source_title")),
        "source_url": _text(raw.get("source_url")),
        "source_version": _text(raw.get("source_version")),
    }


def load_catalog(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load and validate the generated ``network_devices.json`` file."""

    source = Path(path).resolve()
    if not source.is_file():
        raise RackCatalogImportError(f"catalog file not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RackCatalogImportError("catalog file is not valid UTF-8 JSON") from exc
    if not isinstance(payload, list) or not payload:
        raise RackCatalogImportError("network_devices.json must contain at least one row")

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], int] = {}
    for index, raw in enumerate(payload, start=1):
        try:
            row = _normalize_record(raw, index)
        except RackCatalogImportError as exc:
            errors.append({"row": index, "code": "CATALOG_ROW_INVALID", "message": str(exc)})
            continue
        identity = (_key(row["vendor"]), _key(row["model"]))
        if identity in seen:
            errors.append({
                "row": index,
                "code": "CATALOG_DUPLICATE_MODEL",
                "message": f"duplicate vendor/model; first row is {seen[identity]}",
                "vendor": row["vendor"],
                "model": row["model"],
            })
            continue
        seen[identity] = index
        rows.append(row)

    raw_bytes = source.read_bytes()
    metadata = {
        "path": str(source),
        "file_name": source.name,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "row_count": len(payload),
        "valid_row_count": len(rows),
        "invalid_row_count": len(errors),
        "errors": errors,
    }
    return rows, metadata


def _row_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def _existing_device_types(conn) -> dict[tuple[str, str], list[dict[str, Any]]]:
    rows = conn.execute(
        "SELECT id, vendor, model, u_height, device_role, is_full_depth, "
        "depth_class, width_mm, depth_mm, height_mm, weight_kg, dimension_status, "
        "default_mount_kind, model_family, catalog_key, description "
        "FROM device_types ORDER BY vendor, model, id"
    ).fetchall()
    indexed: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        item = _row_dict(row)
        indexed.setdefault((_key(item.get("vendor")), _key(item.get("model"))), []).append(item)
    return indexed


def _missing(value: Any) -> bool:
    return value is None or _text(value) == ""


def _safe_updates(existing: dict[str, Any], incoming: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updates: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []

    # Only fill fields that are absent or explicitly unknown.  Existing
    # non-empty values are operator-owned, even when the catalog disagrees.
    if _missing(existing.get("catalog_key")):
        updates["catalog_key"] = incoming["catalog_key"]
    elif _key(existing.get("catalog_key")) != _key(incoming["catalog_key"]):
        conflicts.append({
            "field": "catalog_key",
            "existing": existing.get("catalog_key"),
            "catalog": incoming["catalog_key"],
        })

    if _missing(existing.get("model_family")) and incoming.get("model_family"):
        updates["model_family"] = incoming["model_family"]

    existing_status = _text(existing.get("dimension_status")).casefold() or "unknown"
    if existing_status in {"", "unknown"} and incoming["dimension_status"] != "unknown":
        updates["dimension_status"] = incoming["dimension_status"]

    existing_mount = _text(existing.get("default_mount_kind")).casefold() or "unknown"
    if existing_mount == "unknown" and incoming["default_mount_kind"] != "unknown":
        updates["default_mount_kind"] = incoming["default_mount_kind"]

    if (existing.get("u_height") is None or int(existing.get("u_height") or 0) <= 0) and incoming["u_height"] > 0:
        updates["u_height"] = incoming["u_height"]

    for field in ("width_mm", "depth_mm", "height_mm", "weight_kg"):
        current = existing.get(field)
        candidate = incoming.get(field)
        if _missing(current) and candidate is not None:
            updates[field] = candidate
        elif current is not None and candidate is not None and str(current) != str(candidate):
            conflicts.append({"field": field, "existing": current, "catalog": candidate})

    if _missing(existing.get("description")) and incoming.get("description"):
        updates["description"] = incoming["description"]

    return updates, conflicts


def _insert_device_type(conn, incoming: dict[str, Any]) -> str:
    device_type_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        """INSERT INTO device_types (
               id, vendor, model, part_number, u_height, device_role, is_full_depth,
               depth_class, width_mm, depth_mm, height_mm, weight_kg, dimension_status,
               default_mount_kind, model_family, catalog_key, description, power_watts,
               created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            device_type_id,
            incoming["vendor"],
            incoming["model"],
            "",
            incoming["u_height"],
            incoming["device_role"],
            incoming["is_full_depth"],
            incoming["depth_class"],
            incoming["width_mm"],
            incoming["depth_mm"],
            incoming["height_mm"],
            incoming["weight_kg"],
            incoming["dimension_status"],
            incoming["default_mount_kind"],
            incoming["model_family"],
            incoming["catalog_key"],
            incoming["description"],
            0,
            now,
            now,
        ),
    )
    return device_type_id


def import_device_catalog(conn, source: str | Path, *, apply: bool = False, commit: bool = False) -> dict[str, Any]:
    """Preview or apply catalog rows without overwriting CMDB-owned values."""

    rows, source_meta = load_catalog(source)
    existing = _existing_device_types(conn)
    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "dry_run": not apply,
        "applied": False,
        "source": source_meta,
        "summary": {
            "catalog_rows": source_meta["row_count"],
            "valid_rows": len(rows),
            "invalid_rows": source_meta["invalid_row_count"],
            "new": 0,
            "updated": 0,
            "unchanged": 0,
            "conflicts": 0,
        },
        "rows": [],
    }

    if source_meta["invalid_row_count"]:
        # A partial import would make the result dependent on row ordering and
        # is not safe for a catalog.  Return the full validation report first.
        report["rows"].extend(source_meta["errors"])

    planned_inserts: list[dict[str, Any]] = []
    planned_updates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for incoming in rows:
        identity = (_key(incoming["vendor"]), _key(incoming["model"]))
        matches = existing.get(identity, [])
        if len(matches) > 1:
            report["summary"]["conflicts"] += 1
            report["rows"].append({
                "row": incoming["source_row"],
                "status": "conflict",
                "code": "DUPLICATE_EXISTING_DEVICE_TYPE",
                "vendor": incoming["vendor"],
                "model": incoming["model"],
                "device_type_ids": [item["id"] for item in matches],
            })
            continue
        if not matches:
            report["summary"]["new"] += 1
            planned_inserts.append(incoming)
            report["rows"].append({
                "row": incoming["source_row"],
                "status": "new",
                "vendor": incoming["vendor"],
                "model": incoming["model"],
                "catalog_key": incoming["catalog_key"],
            })
            continue

        current = matches[0]
        updates, conflicts = _safe_updates(current, incoming)
        if conflicts:
            report["summary"]["conflicts"] += len(conflicts)
        if updates:
            report["summary"]["updated"] += 1
            planned_updates.append((current, updates))
            status = "updated_with_conflicts" if conflicts else "updated"
        else:
            report["summary"]["unchanged"] += 1
            status = "unchanged_with_conflicts" if conflicts else "unchanged"
        report["rows"].append({
            "row": incoming["source_row"],
            "status": status,
            "device_type_id": current["id"],
            "vendor": incoming["vendor"],
            "model": incoming["model"],
            "updates": updates,
            "conflicts": conflicts,
        })

    if not apply:
        return report
    if source_meta["invalid_row_count"] or report["summary"]["conflicts"]:
        # Operators may inspect the conflicts and fix the source/CMDB before a
        # later apply.  Do not silently create a partially reviewed catalog.
        report["apply_blocked"] = True
        report["apply_block_reason"] = "catalog validation or existing-value conflicts require review"
        return report

    try:
        for incoming in planned_inserts:
            device_type_id = _insert_device_type(conn, incoming)
            for item in report["rows"]:
                if item.get("status") == "new" and item.get("row") == incoming["source_row"]:
                    item["device_type_id"] = device_type_id
                    break
        for current, updates in planned_updates:
            assignments = [f"{field} = ?" for field in updates]
            values = list(updates.values()) + [_now(), current["id"]]
            conn.execute(
                f"UPDATE device_types SET {', '.join(assignments)}, updated_at = ? WHERE id = ?",
                values,
            )
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise

    report["applied"] = True
    report["dry_run"] = False
    return report

