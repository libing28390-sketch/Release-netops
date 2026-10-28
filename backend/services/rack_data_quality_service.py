"""RackVision data-quality audit and issue lifecycle helpers.

The service deliberately keeps audit results separate from the placement write
path.  Normal rack writes reject invalid placements; the audit path records
legacy rows that pre-date the canonical contract so operators can repair them
without losing the original evidence.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from services import rack_placement_service


ISSUE_CODES = frozenset({
    "RACK_NOT_FOUND",
    "RACK_NOT_UNIQUE",
    "RACK_TYPE_NOT_FOUND",
    "DEVICE_TYPE_NOT_FOUND",
    "ASSET_NOT_FOUND",
    "DUPLICATE_ASSET_INSTALLATION",
    "INVALID_POSITION",
    "U_OVERFLOW",
    "U_CONFLICT",
    "LEGACY_LOCATION_CONFLICT",
    "UNKNOWN_HEIGHT",
    "UNKNOWN_MOUNT",
    "POWER_FIELD_CONFLICT",
    "SITE_SCOPE_MISSING",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        values = dict(row)
    elif hasattr(row, "keys"):
        values = {key: row[key] for key in row.keys()}
    else:
        values = dict(row)
    return {
        key: float(value) if isinstance(value, Decimal) else value
        for key, value in values.items()
    }


def _decode_details(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError):
        return {"raw": str(value)}
    return decoded if isinstance(decoded, dict) else {"value": decoded}


def _json_expression() -> str:
    from database import _USE_PG

    return "CAST(? AS JSONB)" if _USE_PG else "?"


def _issue_id(entity_type: str, entity_id: str, issue_code: str) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"rackvision:quality:{entity_type}:{entity_id}:{issue_code}",
    ))


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _power_conflict(row: dict[str, Any]) -> dict[str, Any] | None:
    """Return the power-field discrepancy that must be reviewed.

    ``power_capacity_watts`` is the canonical field.  A zero/NULL canonical
    value is a legacy-schema default and is intentionally not considered a
    conflict when the old field has a usable value.  Two different non-zero
    values, however, cannot be reconciled without recording which source was
    observed.
    """

    canonical = _as_int(row.get("power_capacity_watts"))
    legacy = _as_int(row.get("power_capacity_w"))
    if canonical in (None, 0) or legacy in (None, 0) or canonical == legacy:
        return None
    return {
        "power_capacity_watts": canonical,
        "power_capacity_w": legacy,
        "effective_source": "power_capacity_watts",
    }


def _normalized(value: Any) -> str:
    return str(value or "").strip().casefold()


def upsert_issue(
    conn,
    *,
    entity_type: str,
    entity_id: str,
    issue_code: str,
    severity: str = "warning",
    details: dict[str, Any] | None = None,
    status: str = "open",
    commit: bool = False,
) -> dict[str, Any]:
    """Insert or refresh a deterministic issue row.

    Deterministic IDs make repeated audits idempotent and allow a later
    resolution to remain visible when the audit runs again.  Resolved issues
    are not reopened by a routine audit unless the caller explicitly passes
    ``status='open'`` for a remediation workflow.
    """
    normalized_code = str(issue_code or "").strip().upper()
    if normalized_code not in ISSUE_CODES:
        raise ValueError(f"Unsupported rack data quality issue code: {normalized_code}")
    normalized_entity_type = str(entity_type or "").strip().lower()
    normalized_entity_id = str(entity_id or "").strip()
    if not normalized_entity_type or not normalized_entity_id:
        raise ValueError("entity_type and entity_id are required")
    issue_id = _issue_id(normalized_entity_type, normalized_entity_id, normalized_code)
    details_json = json.dumps(details or {}, ensure_ascii=False, sort_keys=True, default=str)
    json_expression = _json_expression()
    conn.execute(
        f"""INSERT INTO rack_data_quality_issues (
                    id, entity_type, entity_id, issue_code, severity,
                    details_json, status, detected_at
                ) VALUES (?, ?, ?, ?, ?, {json_expression}, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    severity = excluded.severity,
                    details_json = excluded.details_json,
                    detected_at = excluded.detected_at
            """,
        (
            issue_id,
            normalized_entity_type,
            normalized_entity_id,
            normalized_code,
            str(severity or "warning").lower(),
            details_json,
            str(status or "open").lower(),
            _utc_now(),
        ),
    )
    if commit:
        conn.commit()
    return get_issue(conn, issue_id)


def get_issue(conn, issue_id: str) -> dict[str, Any]:
    row = conn.execute(
        """SELECT id, entity_type, entity_id, issue_code, severity,
                         details_json, status, detected_at, resolved_at,
                         resolved_by, resolution_note
                    FROM rack_data_quality_issues
                   WHERE id = ?""",
        (issue_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Rack data quality issue not found: {issue_id}")
    result = _row_to_dict(row)
    result["details"] = _decode_details(result.pop("details_json", None))
    return result


def _rack_scope_sql(
    rack_id: str,
    rack_ids: tuple[str, ...] | None = None,
) -> tuple[str, list[Any]]:
    if not rack_id:
        if rack_ids is None:
            return "", []
        if not rack_ids:
            return " AND 1 = 0", []
        placeholders = ",".join("?" for _ in rack_ids)
        return (
            " AND ("
            f" (q.entity_type = 'rack' AND q.entity_id IN ({placeholders}))"
            " OR (q.entity_type = 'rack_device' AND EXISTS ("
            "      SELECT 1 FROM rack_devices rd_scope"
            f"       WHERE rd_scope.id = q.entity_id AND rd_scope.rack_id IN ({placeholders})))"
            " OR (q.entity_type = 'physical_asset' AND EXISTS ("
            "      SELECT 1 FROM rack_devices rd_asset_scope"
            f"       WHERE rd_asset_scope.asset_id = q.entity_id AND rd_asset_scope.rack_id IN ({placeholders})))"
            ")",
            [*rack_ids, *rack_ids, *rack_ids],
        )
    return (
        " AND ("
        " (q.entity_type = 'rack' AND q.entity_id = ?)"
        " OR (q.entity_type = 'rack_device' AND EXISTS ("
        "      SELECT 1 FROM rack_devices rd_scope"
        "       WHERE rd_scope.id = q.entity_id AND rd_scope.rack_id = ?))"
        " OR (q.entity_type = 'physical_asset' AND EXISTS ("
        "      SELECT 1 FROM rack_devices rd_asset_scope"
        "       WHERE rd_asset_scope.asset_id = q.entity_id AND rd_asset_scope.rack_id = ?))"
        ")",
        [rack_id, rack_id, rack_id],
    )


def list_issues(
    conn,
    *,
    rack_id: str = "",
    status: str = "open",
    issue_code: str = "",
    entity_type: str = "",
    severity: str = "",
    page: int = 1,
    page_size: int = 100,
    rack_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    page = max(1, int(page))
    page_size = min(500, max(1, int(page_size)))
    filters: list[str] = []
    params: list[Any] = []
    if status and status != "all":
        filters.append("q.status = ?")
        params.append(status.lower())
    if issue_code:
        filters.append("q.issue_code = ?")
        params.append(issue_code.strip().upper())
    if entity_type:
        filters.append("q.entity_type = ?")
        params.append(entity_type.strip().lower())
    if severity:
        filters.append("q.severity = ?")
        params.append(severity.strip().lower())
    scope_sql, scope_params = _rack_scope_sql(rack_id.strip(), rack_ids)
    where_sql = f" WHERE {' AND '.join(filters)}" if filters else " WHERE 1=1"
    where_sql += scope_sql
    count_row = conn.execute(
        f"SELECT COUNT(*) AS total FROM rack_data_quality_issues q{where_sql}",
        tuple([*params, *scope_params]),
    ).fetchone()
    total = int(count_row["total"] if hasattr(count_row, "keys") else count_row[0])
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"""SELECT q.id, q.entity_type, q.entity_id, q.issue_code, q.severity,
                          q.details_json, q.status, q.detected_at, q.resolved_at,
                          q.resolved_by, q.resolution_note
                     FROM rack_data_quality_issues q
                     {where_sql}
                    ORDER BY CASE q.status WHEN 'open' THEN 0 ELSE 1 END,
                             q.detected_at DESC, q.id
                    LIMIT ? OFFSET ?""",
        tuple([*params, *scope_params, page_size, offset]),
    ).fetchall()
    items = []
    for row in rows:
        item = _row_to_dict(row)
        item["details"] = _decode_details(item.pop("details_json", None))
        items.append(item)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def summarize(
    conn,
    *,
    rack_id: str = "",
    rack_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    result = list_issues(
        conn,
        rack_id=rack_id,
        rack_ids=rack_ids,
        status="all",
        page=1,
        page_size=500,
    )
    by_code: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    open_count = 0
    for item in result["items"]:
        by_code[item["issue_code"]] = by_code.get(item["issue_code"], 0) + 1
        by_severity[item["severity"]] = by_severity.get(item["severity"], 0) + 1
        if item["status"] == "open":
            open_count += 1
    return {
        "total": result["total"],
        "open": open_count,
        "by_code": by_code,
        "by_severity": by_severity,
    }


def resolve_issue(
    conn,
    issue_id: str,
    *,
    resolved_by: str = "",
    resolution_note: str = "",
    commit: bool = True,
) -> dict[str, Any]:
    get_issue(conn, issue_id)
    conn.execute(
        """UPDATE rack_data_quality_issues
              SET status = 'resolved', resolved_at = ?, resolved_by = ?,
                  resolution_note = ?
            WHERE id = ?""",
        (_utc_now(), str(resolved_by or "").strip(), str(resolution_note or "").strip(), issue_id),
    )
    if commit:
        conn.commit()
    return get_issue(conn, issue_id)


def audit_rack(conn, rack_id: str, *, commit: bool = False) -> dict[str, Any]:
    """Audit one rack's existing rows and upsert actionable quality issues."""
    rack = conn.execute(
        """SELECT r.id, r.site_id, r.rack_type_id, r.total_u,
                         r.power_capacity_w, r.power_capacity_watts,
                         s.id AS site_row_id, s.tenant_id AS site_tenant_id,
                         rt.id AS rack_type_row_id
                    FROM racks r
                    LEFT JOIN sites s ON s.id = r.site_id
                    LEFT JOIN rack_types rt ON rt.id = r.rack_type_id
                   WHERE r.id = ?""",
        (rack_id,),
    ).fetchone()
    if not rack:
        raise ValueError(f"Rack not found: {rack_id}")
    rack_row = _row_to_dict(rack)
    rows = conn.execute(
        """SELECT rd.id, rd.rack_id, rd.device_type_id, rd.asset_id,
                         rd.start_u, rd.position, rd.mount_kind, rd.height_u,
                         rd.placement_status, rd.location_note, dt.u_height,
                         dt.default_mount_kind, pa.id AS physical_asset_row_id,
                         pa.rack_id AS projected_rack_id,
                         pa.rack_position AS projected_position,
                         pa.rack_mount_kind AS projected_mount_kind,
                         pa.rack_location_status AS projected_status,
                         pa.planned_start_u AS projected_start_u
                    FROM rack_devices rd
                    LEFT JOIN device_types dt ON dt.id = rd.device_type_id
                    LEFT JOIN physical_assets pa ON pa.id = rd.asset_id
                   WHERE rd.rack_id = ?
                   ORDER BY rd.id""",
        (rack_id,),
    ).fetchall()
    issues: list[dict[str, Any]] = []

    if (
        not _normalized(rack_row.get("site_id"))
        or not _normalized(rack_row.get("site_row_id"))
        or not _normalized(rack_row.get("site_tenant_id"))
    ):
        issues.append(upsert_issue(
            conn,
            entity_type="rack",
            entity_id=str(rack_id),
            issue_code="SITE_SCOPE_MISSING",
            severity="error",
            details={
                "rack_id": rack_id,
                "site_id": rack_row.get("site_id"),
                "site_row_id": rack_row.get("site_row_id"),
                "site_tenant_id": rack_row.get("site_tenant_id"),
            },
        ))
    if _normalized(rack_row.get("rack_type_id")) and not _normalized(rack_row.get("rack_type_row_id")):
        issues.append(upsert_issue(
            conn,
            entity_type="rack",
            entity_id=str(rack_id),
            issue_code="RACK_TYPE_NOT_FOUND",
            severity="error",
            details={
                "rack_id": rack_id,
                "rack_type_id": rack_row.get("rack_type_id"),
            },
        ))
    power_conflict = _power_conflict(rack_row)
    if power_conflict:
        issues.append(upsert_issue(
            conn,
            entity_type="rack",
            entity_id=str(rack_id),
            issue_code="POWER_FIELD_CONFLICT",
            severity="error",
            details=power_conflict,
        ))

    for raw in rows:
        row = _row_to_dict(raw)
        if not row.get("device_type_id") or row.get("u_height") is None:
            issues.append(upsert_issue(
                conn,
                entity_type="rack_device",
                entity_id=str(row["id"]),
                issue_code="DEVICE_TYPE_NOT_FOUND" if not row.get("u_height") else "UNKNOWN_HEIGHT",
                severity="error",
                details={"rack_id": rack_id, "device_type_id": row.get("device_type_id")},
            ))
            continue
        mount_kind = str(row.get("mount_kind") or row.get("default_mount_kind") or "u_mount").lower()
        position = str(row.get("position") or "unknown").lower()
        start_u = row.get("start_u")
        height_u = row.get("height_u") or row.get("u_height")
        result = rack_placement_service.validate(
            conn,
            rack_id=rack_id,
            device_type_id=str(row["device_type_id"]),
            start_u=start_u,
            position=position,
            mount_kind=mount_kind,
            height_u=height_u,
            exclude_device_id=str(row["id"]),
            location_note=row.get("location_note") or "",
            placement_status=row.get("placement_status") or "unknown",
            check_asset=False,
        )
        for error in result.get("errors") or []:
            text = str(error)
            if "conflict" in text.lower():
                code = "U_CONFLICT"
            elif "exceed" in text.lower() or "capacity" in text.lower():
                code = "U_OVERFLOW"
            elif "position" in text.lower() or "mount" in text.lower():
                code = "INVALID_POSITION"
            elif "height" in text.lower():
                code = "UNKNOWN_HEIGHT"
            else:
                code = "LEGACY_LOCATION_CONFLICT"
            issues.append(upsert_issue(
                conn,
                entity_type="rack_device",
                entity_id=str(row["id"]),
                issue_code=code,
                severity="error",
                details={"rack_id": rack_id, "message": text, "row": row},
            ))

        asset_id = _normalized(row.get("asset_id"))
        if asset_id and not _normalized(row.get("physical_asset_row_id")):
            issues.append(upsert_issue(
                conn,
                entity_type="rack_device",
                entity_id=str(row["id"]),
                issue_code="ASSET_NOT_FOUND",
                severity="error",
                details={"rack_id": rack_id, "asset_id": row.get("asset_id")},
            ))
        elif asset_id:
            expected_projection = {
                "rack_id": rack_id,
                "rack_position": position,
                "rack_mount_kind": mount_kind,
                "rack_location_status": row.get("placement_status") or "unknown",
                "planned_start_u": start_u if mount_kind == "u_mount" else None,
            }
            actual_projection = {
                "rack_id": row.get("projected_rack_id"),
                "rack_position": row.get("projected_position"),
                "rack_mount_kind": row.get("projected_mount_kind"),
                "rack_location_status": row.get("projected_status"),
                "planned_start_u": row.get("projected_start_u"),
            }
            projection_mismatches = {
                key: {"expected": expected_projection[key], "actual": actual_projection[key]}
                for key in expected_projection
                if (
                    _normalized(expected_projection[key]) != _normalized(actual_projection[key])
                    if key != "planned_start_u"
                    else _as_int(expected_projection[key]) != _as_int(actual_projection[key])
                )
            }
            if projection_mismatches:
                issues.append(upsert_issue(
                    conn,
                    entity_type="physical_asset",
                    entity_id=str(row.get("physical_asset_row_id") or row.get("asset_id")),
                    issue_code="LEGACY_LOCATION_CONFLICT",
                    severity="warning",
                    details={
                        "rack_id": rack_id,
                        "asset_id": row.get("asset_id"),
                        "projection_mismatches": projection_mismatches,
                    },
                ))

    duplicate_rows = conn.execute(
        """SELECT TRIM(asset_id) AS asset_id, COUNT(*) AS item_count
             FROM rack_devices
            WHERE rack_id = ? AND asset_id IS NOT NULL AND TRIM(asset_id) <> ''
            GROUP BY TRIM(asset_id)
           HAVING COUNT(*) > 1""",
        (rack_id,),
    ).fetchall()
    for duplicate in duplicate_rows:
        asset_id = str(duplicate["asset_id"] if hasattr(duplicate, "keys") else duplicate[0]).strip()
        issues.append(upsert_issue(
            conn,
            entity_type="physical_asset",
            entity_id=asset_id,
            issue_code="DUPLICATE_ASSET_INSTALLATION",
            severity="error",
            details={"rack_id": rack_id, "count": int(duplicate["item_count"] if hasattr(duplicate, "keys") else duplicate[1])},
        ))
    if commit:
        conn.commit()
    return {
        "rack_id": rack_id,
        "checked_devices": len(rows),
        "issues_detected": len(issues),
        "issues": issues,
        "summary": summarize(conn, rack_id=rack_id),
    }


def audit_all(
    conn,
    *,
    rack_ids: tuple[str, ...] | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """Audit the RackVision data graph without changing business records.

    The quality table is the audit sink; ``racks``, ``rack_devices`` and
    ``physical_assets`` themselves are never repaired here.  This is the
    report used before applying a backfill or adding production constraints.
    ``rack_ids`` is an authorization boundary for callers that only see a
    tenant/site subset.
    """

    normalized_rack_ids = tuple(sorted({str(value).strip() for value in (rack_ids or ()) if str(value).strip()}))
    scope_sql = ""
    scope_params: list[Any] = []
    if rack_ids is not None:
        if not normalized_rack_ids:
            return {
                "mode": "audit",
                "racks_checked": 0,
                "rack_devices_checked": 0,
                "physical_assets_checked": 0,
                "issues_detected": 0,
                "by_code": {},
                "by_entity_type": {},
                "issues": [],
                "summary": {"total": 0, "open": 0, "by_code": {}, "by_severity": {}},
            }
        placeholders = ",".join("?" for _ in normalized_rack_ids)
        scope_sql = f" AND r.id IN ({placeholders})"
        scope_params.extend(normalized_rack_ids)

    rack_rows = conn.execute(
        f"SELECT r.id FROM racks r WHERE 1 = 1{scope_sql} ORDER BY r.id",
        tuple(scope_params),
    ).fetchall()
    rack_ids_to_check = [str(row["id"] if hasattr(row, "keys") else row[0]) for row in rack_rows]

    issues: list[dict[str, Any]] = []
    seen_issue_keys: set[tuple[str, str, str]] = set()

    def collect(item: dict[str, Any]) -> None:
        key = (
            str(item.get("entity_type") or ""),
            str(item.get("entity_id") or ""),
            str(item.get("issue_code") or ""),
        )
        if key not in seen_issue_keys:
            seen_issue_keys.add(key)
            issues.append(item)

    checked_devices = 0
    for current_rack_id in rack_ids_to_check:
        result = audit_rack(conn, current_rack_id, commit=False)
        checked_devices += int(result.get("checked_devices") or 0)
        for item in result.get("issues") or []:
            collect(item)

    rd_scope_sql = ""
    rd_scope_params: list[Any] = []
    if rack_ids is not None:
        placeholders = ",".join("?" for _ in normalized_rack_ids)
        rd_scope_sql = f" AND rd.rack_id IN ({placeholders})"
        rd_scope_params.extend(normalized_rack_ids)

    def record_global(
        *,
        entity_type: str,
        entity_id: str,
        issue_code: str,
        details: dict[str, Any],
        severity: str = "error",
    ) -> None:
        collect(upsert_issue(
            conn,
            entity_type=entity_type,
            entity_id=entity_id,
            issue_code=issue_code,
            severity=severity,
            details=details,
        ))

    duplicate_rows = conn.execute(
        f"""SELECT TRIM(rd.asset_id) AS asset_id, COUNT(*) AS item_count
               FROM rack_devices rd
              WHERE rd.asset_id IS NOT NULL AND TRIM(rd.asset_id) <> ''{rd_scope_sql}
              GROUP BY TRIM(rd.asset_id)
             HAVING COUNT(*) > 1""",
        tuple(rd_scope_params),
    ).fetchall()
    for duplicate in duplicate_rows:
        asset_id = str(duplicate["asset_id"] if hasattr(duplicate, "keys") else duplicate[0]).strip()
        installation_rows = conn.execute(
            f"""SELECT id, rack_id, start_u, position
                   FROM rack_devices rd
                  WHERE TRIM(rd.asset_id) = ?{rd_scope_sql}
                  ORDER BY id""",
            tuple([asset_id, *rd_scope_params]),
        ).fetchall()
        record_global(
            entity_type="physical_asset",
            entity_id=asset_id,
            issue_code="DUPLICATE_ASSET_INSTALLATION",
            details={
                "asset_id": asset_id,
                "count": int(duplicate["item_count"] if hasattr(duplicate, "keys") else duplicate[1]),
                "installations": [_row_to_dict(row) for row in installation_rows],
            },
        )

    orphan_device_rows = conn.execute(
        f"""SELECT rd.id, rd.rack_id, rd.device_type_id
               FROM rack_devices rd
               LEFT JOIN racks r ON r.id = rd.rack_id
              WHERE r.id IS NULL{rd_scope_sql}""",
        tuple(rd_scope_params),
    ).fetchall()
    for row in orphan_device_rows:
        item = _row_to_dict(row)
        record_global(
            entity_type="rack_device",
            entity_id=str(item.get("id")),
            issue_code="RACK_NOT_FOUND",
            details={"rack_id": item.get("rack_id"), "device_type_id": item.get("device_type_id")},
        )

    missing_type_rows = conn.execute(
        f"""SELECT rd.id, rd.rack_id, rd.device_type_id
               FROM rack_devices rd
               LEFT JOIN device_types dt ON dt.id = rd.device_type_id
              WHERE dt.id IS NULL{rd_scope_sql}""",
        tuple(rd_scope_params),
    ).fetchall()
    for row in missing_type_rows:
        item = _row_to_dict(row)
        record_global(
            entity_type="rack_device",
            entity_id=str(item.get("id")),
            issue_code="DEVICE_TYPE_NOT_FOUND",
            details={"rack_id": item.get("rack_id"), "device_type_id": item.get("device_type_id")},
        )

    missing_asset_rows = conn.execute(
        f"""SELECT rd.id, rd.rack_id, rd.asset_id
               FROM rack_devices rd
               LEFT JOIN physical_assets pa ON pa.id = rd.asset_id
              WHERE rd.asset_id IS NOT NULL
                AND TRIM(rd.asset_id) <> ''
                AND pa.id IS NULL{rd_scope_sql}""",
        tuple(rd_scope_params),
    ).fetchall()
    for row in missing_asset_rows:
        item = _row_to_dict(row)
        record_global(
            entity_type="rack_device",
            entity_id=str(item.get("id")),
            issue_code="ASSET_NOT_FOUND",
            details={"rack_id": item.get("rack_id"), "asset_id": item.get("asset_id")},
        )

    rack_scope_asset_sql = ""
    rack_scope_asset_params: list[Any] = []
    if rack_ids is not None:
        placeholders = ",".join("?" for _ in normalized_rack_ids)
        rack_scope_asset_sql = f" AND pa.rack_id IN ({placeholders})"
        rack_scope_asset_params.extend(normalized_rack_ids)
    orphan_projection_rows = conn.execute(
        f"""SELECT pa.id, pa.rack_id, pa.rack_position, pa.rack_mount_kind
               FROM physical_assets pa
               LEFT JOIN racks r ON r.id = pa.rack_id
              WHERE pa.rack_id IS NOT NULL
                AND TRIM(pa.rack_id) <> ''
                AND r.id IS NULL{rack_scope_asset_sql}""",
        tuple(rack_scope_asset_params),
    ).fetchall()
    for row in orphan_projection_rows:
        item = _row_to_dict(row)
        record_global(
            entity_type="physical_asset",
            entity_id=str(item.get("id")),
            issue_code="RACK_NOT_FOUND",
            details={"rack_id": item.get("rack_id"), "source": "physical_assets.rack_id"},
        )

    unbacked_projection_rows = conn.execute(
        f"""SELECT pa.id, pa.rack_id, pa.rack_position, pa.rack_mount_kind,
                      pa.rack_location_status
               FROM physical_assets pa
               JOIN racks r ON r.id = pa.rack_id
              WHERE pa.rack_id IS NOT NULL
                AND TRIM(pa.rack_id) <> ''
                AND NOT EXISTS (
                    SELECT 1 FROM rack_devices rd
                     WHERE rd.asset_id = pa.id
                ){rack_scope_asset_sql}""",
        tuple(rack_scope_asset_params),
    ).fetchall()
    for row in unbacked_projection_rows:
        item = _row_to_dict(row)
        record_global(
            entity_type="physical_asset",
            entity_id=str(item.get("id")),
            issue_code="LEGACY_LOCATION_CONFLICT",
            severity="warning",
            details={
                "rack_id": item.get("rack_id"),
                "source": "physical_assets_without_rack_device",
                "projection": {
                    "rack_position": item.get("rack_position"),
                    "rack_mount_kind": item.get("rack_mount_kind"),
                    "rack_location_status": item.get("rack_location_status"),
                },
            },
        )

    power_scope_sql = ""
    power_scope_params: list[Any] = []
    if rack_ids is not None:
        placeholders = ",".join("?" for _ in normalized_rack_ids)
        power_scope_sql = f" WHERE r.id IN ({placeholders})"
        power_scope_params.extend(normalized_rack_ids)
    power_rows = conn.execute(
        f"""SELECT r.id, r.power_capacity_w, r.power_capacity_watts
               FROM racks r{power_scope_sql}""",
        tuple(power_scope_params),
    ).fetchall()
    for row in power_rows:
        item = _row_to_dict(row)
        conflict = _power_conflict(item)
        if conflict:
            record_global(
                entity_type="rack",
                entity_id=str(item.get("id")),
                issue_code="POWER_FIELD_CONFLICT",
                details=conflict,
            )

    asset_count_sql = ""
    asset_count_params: list[Any] = []
    if rack_ids is not None:
        placeholders = ",".join("?" for _ in normalized_rack_ids)
        # Assets are site-scoped even when they are currently unplaced.  Count
        # all assets in the authorized rack sites so the report exposes the
        # uninstalled/legacy population that a later backfill must reconcile.
        asset_count_sql = (
            f" JOIN racks r_asset_count ON r_asset_count.site_id = pa.site_id"
            f" AND r_asset_count.id IN ({placeholders})"
        )
        asset_count_params.extend(normalized_rack_ids)
    asset_count_row = conn.execute(
        f"SELECT COUNT(DISTINCT pa.id) AS item_count FROM physical_assets pa{asset_count_sql}",
        tuple(asset_count_params),
    ).fetchone()
    asset_count = int(asset_count_row["item_count"] if hasattr(asset_count_row, "keys") else asset_count_row[0])

    by_code: dict[str, int] = {}
    by_entity_type: dict[str, int] = {}
    for item in issues:
        code = str(item.get("issue_code") or "")
        entity_type = str(item.get("entity_type") or "")
        by_code[code] = by_code.get(code, 0) + 1
        by_entity_type[entity_type] = by_entity_type.get(entity_type, 0) + 1
    if commit:
        conn.commit()
    return {
        "mode": "audit",
        "racks_checked": len(rack_ids_to_check),
        "rack_devices_checked": checked_devices,
        "physical_assets_checked": asset_count,
        "issues_detected": len(issues),
        "by_code": by_code,
        "by_entity_type": by_entity_type,
        "issues": issues,
        "summary": summarize(conn, rack_ids=normalized_rack_ids if rack_ids is not None else None),
    }


__all__ = [
    "ISSUE_CODES", "audit_all", "audit_rack", "get_issue", "list_issues", "resolve_issue",
    "summarize", "upsert_issue",
]
