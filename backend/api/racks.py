"""
racks.py — Rack Management API

Provides REST endpoints for managing racks, device types, and rack device installations.
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from database import get_db_connection
from core.rbac import require_role
from core.read_cache import (
    RACK_CACHE_TTL_SECONDS,
    invalidate_read_cache,
    read_cache,
)
from schemas.schemas import (
    RackCreate, RackUpdate, RackTypeCreate, RackTypeUpdate,
    DeviceTypeCreate, DeviceTypeUpdate,
    RackDeviceCreate, RackDeviceUpdate, RackPlacementCreate, RackPlacementValidate,
)
from services import rack_service
from services import rack_asset_resolver
from services import rack_placement_service
from services import rack_data_quality_service
from services import rack_scope_service

logger = logging.getLogger(__name__)

router = APIRouter()


class RackQualityIssueResolution(BaseModel):
    resolution_note: str = Field(default='', max_length=2000)


def _rack_http_exception(exc: ValueError, *, default_status: int = 400) -> HTTPException:
    """Convert rack domain failures to a stable error contract.

    The service remains usable by older Python callers that expect
    ``ValueError`` (``RackPlacementError`` subclasses it), while HTTP clients
    receive an explicit code and safe details instead of a free-form SQL or
    Python exception string.
    """

    if isinstance(exc, rack_placement_service.RackPlacementError):
        return HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message, "details": exc.details},
        )

    message = str(exc) or "Rack operation failed"
    lowered = message.casefold()
    if "rack not found" in lowered:
        code, status_code = "RACK_NOT_FOUND", 404
    elif "rack type not found" in lowered:
        code, status_code = "RACK_TYPE_NOT_FOUND", 404
    elif "device type not found" in lowered:
        code, status_code = "DEVICE_TYPE_NOT_FOUND", 404
    elif "site not found" in lowered:
        code, status_code = "SITE_NOT_FOUND", 404
    elif "rack device not found" in lowered:
        code, status_code = "RACK_DEVICE_NOT_FOUND", 404
    elif "cannot delete" in lowered or "in use" in lowered:
        code, status_code = "RESOURCE_IN_USE", 409
    elif ("asset" in lowered or "资产" in lowered) and "上架" in lowered:
        code, status_code = "ASSET_ALREADY_INSTALLED", 409
    elif "conflict" in lowered or "冲突" in lowered:
        code, status_code = "RACK_U_CONFLICT", 409
    else:
        code, status_code = "VALIDATION_ERROR", default_status
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _rack_internal_exception(operation: str) -> HTTPException:
    return HTTPException(
        status_code=500,
        detail={
            "code": "RACK_INTERNAL_ERROR",
            "message": f"{operation} failed; see server logs",
        },
    )


def _rack_payload_with_reconciled_power(body: RackCreate) -> dict:
    """Keep legacy and canonical power columns identical on every new write."""

    payload = body.model_dump()
    fields_set = getattr(body, "model_fields_set", set())
    if "power_capacity_watts" in fields_set:
        effective = body.power_capacity_watts
    elif "power_capacity_w" in fields_set:
        effective = body.power_capacity_w
    else:
        effective = body.power_capacity_watts
    payload["power_capacity_watts"] = effective
    payload["power_capacity_w"] = effective
    return payload


# ─── Racks ──────────────────────────────────────────────

@router.get("/racks")
def api_list_racks(site_id: str = Query('', description="Filter by site"),
                   datacenter: str = Query('', include_in_schema=False),
                   user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        scope = rack_scope_service.allowed_rack_scope(conn, user, "view")
        cache_key = f'list:{scope.cache_key}:{site_id}:{datacenter}'
        cache_hit, cached = read_cache.get('rack_page', cache_key)
        if cache_hit:
            return cached
        racks = rack_service.list_racks(
            conn,
            site_id=site_id,
            datacenter=datacenter,
            tenant_id=scope.tenant_id,
            allowed_site_ids=scope.site_ids,
        )
        response = {"success": True, "data": racks, "message": ""}
        read_cache.set('rack_page', cache_key, response, RACK_CACHE_TTL_SECONDS)
        return response
    finally:
        conn.close()


@router.get("/racks/summary")
def api_list_rack_summaries(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    keyword: str = Query('', max_length=200),
    site_id: str = Query(''),
    floor: str = Query('', max_length=100),
    room: str = Query('', max_length=100),
    row: str = Query('', max_length=50),
    status: str = Query('', max_length=20),
    health: str = Query('', pattern='^(|healthy|offline|partial|unknown|empty)$'),
    _user=require_role("Viewer"),
):
    """Paged rack summaries for read-only workbenches and large inventories."""
    user = _user
    conn = get_db_connection()
    try:
        scope = rack_scope_service.allowed_rack_scope(conn, user, "view")
        cache_key = ':'.join((
            'summary', scope.cache_key, str(page), str(page_size), keyword, site_id,
            floor, room, row, status, health,
        ))
        cache_hit, cached = read_cache.get('rack_page', cache_key)
        if cache_hit:
            return cached
        result = rack_service.list_rack_summaries(
            conn,
            page=page,
            page_size=page_size,
            keyword=keyword,
            site_id=site_id,
            floor=floor,
            room=room,
            row=row,
            status=status,
            health=health,
            tenant_id=scope.tenant_id,
            allowed_site_ids=scope.site_ids,
        )
        response = {"success": True, "data": result, "message": ""}
        read_cache.set('rack_page', cache_key, response, RACK_CACHE_TTL_SECONDS)
        return response
    finally:
        conn.close()


@router.get("/racks/stats")
def api_rack_stats(user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        scope = rack_scope_service.allowed_rack_scope(conn, user, "view")
        cache_key = f'stats:{scope.cache_key}'
        cache_hit, cached = read_cache.get('rack_page', cache_key)
        if cache_hit:
            return cached
        stats = rack_service.get_rack_stats(
            conn,
            tenant_id=scope.tenant_id,
            allowed_site_ids=scope.site_ids,
        )
        response = {"success": True, "data": stats, "message": ""}
        read_cache.set('rack_page', cache_key, response, RACK_CACHE_TTL_SECONDS)
        return response
    finally:
        conn.close()


# 鈹€鈹€鈹€ Rack Types 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.get("/rack-types")
def api_list_rack_types(_user=require_role("Viewer")):
    cache_hit, cached = read_cache.get('rack_page', 'rack-types')
    if cache_hit:
        return cached
    conn = get_db_connection()
    try:
        types = rack_service.list_rack_types(conn)
        response = {"success": True, "data": types, "message": ""}
        read_cache.set('rack_page', 'rack-types', response, RACK_CACHE_TTL_SECONDS)
        return response
    finally:
        conn.close()


@router.get("/rack-types/{rack_type_id}")
def api_get_rack_type(rack_type_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        rt = rack_service.get_rack_type(conn, rack_type_id)
        return {"success": True, "data": rt, "message": ""}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()


@router.post("/rack-types")
def api_create_rack_type(body: RackTypeCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        rt = rack_service.create_rack_type(conn, **body.model_dump())
        invalidate_read_cache('rack_page')
        return {"success": True, "data": rt, "message": "Rack type created"}
    except ValueError as e:
        raise _rack_http_exception(e) from e
    except Exception:
        logger.exception("Rack type creation failed")
        raise _rack_internal_exception("Rack type creation")
    finally:
        conn.close()


@router.put("/rack-types/{rack_type_id}")
def api_update_rack_type(rack_type_id: str, body: RackTypeUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        rt = rack_service.update_rack_type(conn, rack_type_id, **body.model_dump(exclude_unset=True))
        invalidate_read_cache('rack_page')
        return {"success": True, "data": rt, "message": "Rack type updated"}
    except ValueError as e:
        raise _rack_http_exception(e) from e
    finally:
        conn.close()


@router.delete("/rack-types/{rack_type_id}")
def api_delete_rack_type(rack_type_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        rack_service.delete_rack_type(conn, rack_type_id)
        invalidate_read_cache('rack_page')
        return {"success": True, "data": None, "message": "Rack type deleted"}
    except ValueError as e:
        raise _rack_http_exception(e) from e
    finally:
        conn.close()


@router.get("/racks/validate-u")
def api_validate_u_position(
    rack: str = Query(..., description="Rack name or rack_code"),
    start_u: int = Query(..., description="Start U position"),
    u_height: int = Query(..., description="U height"),
    exclude_asset_id: str = Query('', description="Asset ID to exclude"),
    position: str = Query('front', description="front, rear, or full_depth"),
    mount_kind: str = Query('u_mount', description="Placement mount kind"),
    _user=require_role("Viewer")
):
    conn = get_db_connection()
    try:
        rack_row = rack_service.resolve_rack_reference(conn, rack)
        if not rack_row:
            return {"success": False, "reason": f"机柜 '{rack}' 不存在"}

        rack_id = rack_row['id']
        rack_scope_service.enforce_loaded_rack(
            _user,
            rack_service.get_rack(conn, rack_id),
            "view",
        )

        exclude_device_id = ''
        if exclude_asset_id:
            rd_row = conn.execute("SELECT id FROM rack_devices WHERE asset_id = ?", (exclude_asset_id,)).fetchone()
            if rd_row:
                exclude_device_id = rd_row['id']

        result = rack_placement_service.validate(
            conn,
            rack_id=rack_id,
            device_type_id='',
            start_u=start_u,
            position=position,
            mount_kind=mount_kind,
            height_u=u_height,
            exclude_device_id=exclude_device_id,
            check_asset=False,
        )
        return {
            "success": bool(result.get("valid")),
            "reason": '; '.join(result.get("errors") or []),
            "warnings": result.get("warnings") or [],
        }
    except ValueError as exc:
        raise _rack_http_exception(exc) from exc
    finally:
        conn.close()


@router.get("/racks/{rack_id}")
def api_get_rack(rack_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        rack = rack_service.get_rack(conn, rack_id)
        rack_scope_service.enforce_loaded_rack(user, rack, "view")
        return {"success": True, "data": rack, "message": ""}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()


@router.get("/racks/{rack_id}/quality-issues")
def api_list_rack_quality_issues(
    rack_id: str,
    status: str = Query('open', pattern='^(open|resolved|all)$'),
    issue_code: str = Query('', max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        # Resolve the rack first so a typo cannot silently return an empty
        # issue page that looks like a clean rack.
        rack = rack_service.get_rack(conn, rack_id)
        rack_scope_service.enforce_loaded_rack(user, rack, "view")
        result = rack_data_quality_service.list_issues(
            conn,
            rack_id=rack_id,
            status=status,
            issue_code=issue_code,
            page=page,
            page_size=page_size,
        )
        return {
            "success": True,
            "data": {
                **result,
                "summary": rack_data_quality_service.summarize(
                    conn,
                    rack_id=rack_id,
                ),
            },
            "message": "",
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()


@router.post("/racks/{rack_id}/quality-issues/audit")
def api_audit_rack_quality(rack_id: str, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        rack = rack_service.get_rack(conn, rack_id)
        rack_scope_service.enforce_loaded_rack(user, rack, "update")
        result = rack_data_quality_service.audit_rack(conn, rack_id, commit=True)
        invalidate_read_cache('rack_page')
        return {"success": True, "data": result, "message": "Rack data quality audit completed"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()


@router.post("/rack-data-quality/audit")
def api_audit_rack_data_quality(
    rack_id: str = Query('', max_length=128),
    user=require_role("Operator"),
):
    """Run a scoped, non-repairing RackVision data quality audit."""

    conn = get_db_connection()
    try:
        if rack_id:
            rack = rack_service.get_rack(conn, rack_id)
            rack_scope_service.enforce_loaded_rack(user, rack, "update")
            allowed_racks = (str(rack_id),)
        else:
            scope = rack_scope_service.allowed_rack_scope(conn, user, "update")
            allowed_racks = tuple(
                str(item["id"])
                for item in rack_service.list_racks(
                    conn,
                    tenant_id=scope.tenant_id,
                    allowed_site_ids=scope.site_ids,
                )
            )
        result = rack_data_quality_service.audit_all(
            conn,
            rack_ids=allowed_racks,
            commit=True,
        )
        invalidate_read_cache('rack_page')
        return {
            "success": True,
            "data": result,
            "message": "Rack data quality audit completed",
        }
    except ValueError as exc:
        raise _rack_http_exception(exc, default_status=404) from exc
    finally:
        conn.close()


@router.get("/rack-data-quality/issues")
def api_list_quality_issues(
    rack_id: str = Query('', max_length=128),
    status: str = Query('open', pattern='^(open|resolved|all)$'),
    issue_code: str = Query('', max_length=64),
    entity_type: str = Query('', max_length=64),
    severity: str = Query('', pattern='^(|info|warning|error|critical)$'),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        scope = rack_scope_service.allowed_rack_scope(conn, user, "view")
        allowed_racks = None
        if rack_id:
            rack = rack_service.get_rack(conn, rack_id)
            rack_scope_service.enforce_loaded_rack(user, rack, "view")
        else:
            allowed_racks = tuple(
                str(item["id"])
                for item in rack_service.list_racks(
                    conn,
                    tenant_id=scope.tenant_id,
                    allowed_site_ids=scope.site_ids,
                )
            )
        result = rack_data_quality_service.list_issues(
            conn,
            rack_id=rack_id,
            rack_ids=allowed_racks,
            status=status,
            issue_code=issue_code,
            entity_type=entity_type,
            severity=severity,
            page=page,
            page_size=page_size,
        )
        return {
            "success": True,
            "data": {
                **result,
                "summary": rack_data_quality_service.summarize(
                    conn,
                    rack_id=rack_id,
                    rack_ids=allowed_racks,
                ),
            },
            "message": "",
        }
    finally:
        conn.close()


@router.put("/rack-data-quality/issues/{issue_id}/resolve")
def api_resolve_quality_issue(
    issue_id: str,
    body: RackQualityIssueResolution,
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        issue_preview = rack_data_quality_service.get_issue(conn, issue_id)
        if issue_preview.get("entity_type") == "rack":
            rack = rack_service.get_rack(conn, str(issue_preview.get("entity_id") or ""))
        elif issue_preview.get("entity_type") == "rack_device":
            rack_row = conn.execute(
                "SELECT rack_id FROM rack_devices WHERE id = ?",
                (str(issue_preview.get("entity_id") or ""),),
            ).fetchone()
            rack = rack_service.get_rack(conn, rack_row["rack_id"] if rack_row else "")
        elif issue_preview.get("entity_type") == "physical_asset":
            rack_row = conn.execute(
                """SELECT rd.rack_id
                     FROM rack_devices rd
                    WHERE rd.asset_id = ?
                    ORDER BY rd.id
                    LIMIT 1""",
                (str(issue_preview.get("entity_id") or ""),),
            ).fetchone()
            rack = rack_service.get_rack(conn, rack_row["rack_id"] if rack_row else "")
        else:
            raise HTTPException(
                status_code=422,
                detail={"code": "RACK_SCOPE_UNRESOLVED", "message": "Quality issue is not linked to a rack"},
            )
        rack_scope_service.enforce_loaded_rack(user, rack, "update")
        issue = rack_data_quality_service.resolve_issue(
            conn,
            issue_id,
            resolved_by=str(user.get('username') or user.get('user_id') or 'operator'),
            resolution_note=body.resolution_note,
        )
        invalidate_read_cache('rack_page')
        return {"success": True, "data": issue, "message": "Rack data quality issue resolved"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()


@router.get("/racks/{rack_id}/layout")
def api_get_rack_layout(rack_id: str, user=require_role("Viewer")):
    """Full rack layout including devices and occupancy stats."""
    conn = get_db_connection()
    try:
        rack = rack_service.get_rack(conn, rack_id)
        rack_scope_service.enforce_loaded_rack(user, rack, "view")
        revision_row = conn.execute(
            "SELECT layout_revision FROM racks WHERE id = ?",
            (rack_id,),
        ).fetchone()
        if not revision_row:
            raise HTTPException(status_code=404, detail={"code": "RACK_NOT_FOUND", "message": "Rack not found"})
        revision = int(revision_row['layout_revision'] if hasattr(revision_row, 'keys') else revision_row[0])
        cache_key = f'layout:{rack_id}:{revision}'
        cache_hit, cached = read_cache.get('rack_page', cache_key)
        if cache_hit:
            return cached
        layout = rack_service.get_rack_layout(conn, rack_id)
        response = {
            "success": True,
            "data": layout,
            "message": "",
            "meta": {
                "schema_version": "rack-layout-v1",
                "layout_revision": revision,
            },
        }
        read_cache.set('rack_page', cache_key, response, RACK_CACHE_TTL_SECONDS)
        return response
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()


@router.post("/racks")
def api_create_rack(body: RackCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        requested_site_id = rack_scope_service.resolve_site_id(
            conn,
            str(body.site_id or ""),
            body.datacenter,
        )
        if requested_site_id:
            rack_scope_service.enforce_site(conn, user, requested_site_id, "create")
        rack = rack_service.create_rack(conn, **_rack_payload_with_reconciled_power(body))
        rack_scope_service.enforce_loaded_rack(user, rack, "create")
        invalidate_read_cache('rack_page')
        return {"success": True, "data": rack, "message": "Rack created"}
    except ValueError as e:
        raise _rack_http_exception(e) from e
    except Exception:
        logger.exception("Rack creation failed")
        raise _rack_internal_exception("Rack creation")
    finally:
        conn.close()


@router.post("/racks/batch")
def api_batch_create_racks(body: List[RackCreate], user=require_role("Operator")):
    conn = get_db_connection()
    try:
        conn.execute("BEGIN")
        created_racks = []
        for i, rack_data in enumerate(body):
            try:
                requested_site_id = rack_scope_service.resolve_site_id(
                    conn,
                    str(rack_data.site_id or ""),
                    rack_data.datacenter,
                )
                if requested_site_id:
                    rack_scope_service.enforce_site(conn, user, requested_site_id, "create")
                rack = rack_service.create_rack(
                    conn,
                    commit=False,
                    **_rack_payload_with_reconciled_power(rack_data),
                )
                created_racks.append(rack)
            except HTTPException:
                conn.rollback()
                raise
            except ValueError as e:
                conn.rollback()
                mapped = _rack_http_exception(e)
                details = mapped.detail if isinstance(mapped.detail, dict) else {"message": str(mapped.detail)}
                details["details"] = {
                    **(details.get("details") or {}),
                    "row": i + 1,
                }
                raise HTTPException(status_code=mapped.status_code, detail=details) from e
            except Exception as e:
                conn.rollback()
                logger.exception("Rack batch row %s creation failed", i + 1)
                raise _rack_internal_exception(f"Rack batch row {i + 1} creation") from e
        conn.commit()
        return {"success": True, "data": created_racks, "message": f"成功导入 {len(created_racks)} 个机柜"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.exception("Rack batch creation failed")
        raise _rack_internal_exception("Rack batch creation") from e
    finally:
        conn.close()


@router.put("/racks/{rack_id}")
def api_update_rack(rack_id: str, body: RackUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        existing = rack_service.get_rack(conn, rack_id)
        rack_scope_service.enforce_loaded_rack(user, existing, "update")
        if body.site_id is not None or body.datacenter is not None:
            requested_site_id = rack_scope_service.resolve_site_id(
                conn,
                str(body.site_id or ""),
                str(body.datacenter or ""),
            )
            if requested_site_id:
                rack_scope_service.enforce_site(conn, user, requested_site_id, "update")
        rack = rack_service.update_rack(conn, rack_id, **body.model_dump(exclude_unset=True))
        invalidate_read_cache('rack_page')
        return {"success": True, "data": rack, "message": "Rack updated"}
    except ValueError as e:
        raise _rack_http_exception(e) from e
    finally:
        conn.close()


@router.delete("/racks/{rack_id}")
def api_delete_rack(rack_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        existing = rack_service.get_rack(conn, rack_id)
        rack_scope_service.enforce_loaded_rack(user, existing, "delete")
        rack_service.delete_rack(conn, rack_id)
        invalidate_read_cache('rack_page')
        return {"success": True, "data": None, "message": "Rack deleted"}
    except ValueError as e:
        raise _rack_http_exception(e) from e
    finally:
        conn.close()


# ─── Device Types ───────────────────────────────────────

@router.get("/device-types")
def api_list_device_types(_user=require_role("Viewer")):
    cache_hit, cached = read_cache.get('rack_page', 'device-types')
    if cache_hit:
        return cached
    conn = get_db_connection()
    try:
        types = rack_service.list_device_types(conn)
        response = {"success": True, "data": types, "message": ""}
        read_cache.set('rack_page', 'device-types', response, RACK_CACHE_TTL_SECONDS)
        return response
    finally:
        conn.close()


@router.get("/device-types/{dt_id}")
def api_get_device_type(dt_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        dt = rack_service.get_device_type(conn, dt_id)
        return {"success": True, "data": dt, "message": ""}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()


@router.post("/device-types")
def api_create_device_type(body: DeviceTypeCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        dt = rack_service.create_device_type(conn, **body.model_dump())
        invalidate_read_cache('rack_page')
        return {"success": True, "data": dt, "message": "Device type created"}
    except ValueError as e:
        raise _rack_http_exception(e) from e
    except Exception:
        logger.exception("Device type creation failed")
        raise _rack_internal_exception("Device type creation")
    finally:
        conn.close()


@router.put("/device-types/{dt_id}")
def api_update_device_type(dt_id: str, body: DeviceTypeUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        dt = rack_service.update_device_type(conn, dt_id, **body.model_dump(exclude_unset=True))
        invalidate_read_cache('rack_page')
        return {"success": True, "data": dt, "message": "Device type updated"}
    except ValueError as e:
        raise _rack_http_exception(e) from e
    finally:
        conn.close()


@router.delete("/device-types/{dt_id}")
def api_delete_device_type(dt_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        rack_service.delete_device_type(conn, dt_id)
        invalidate_read_cache('rack_page')
        return {"success": True, "data": None, "message": "Device type deleted"}
    except ValueError as e:
        raise _rack_http_exception(e) from e
    finally:
        conn.close()


# ─── Rack 3D Asset Registry ─────────────────────────────

@router.get("/rack-assets/catalog")
def api_list_rack_visual_assets(
    vendor: str = Query('', max_length=64),
    device_type: str = Query('', max_length=64),
    status: str = Query('', pattern='^(|draft|review|approved|deprecated)$'),
    _user=require_role("Viewer"),
):
    """Return the read-only GLB/procedural asset registry used by RackVision."""
    return {
        "success": True,
        "data": {
            "items": rack_asset_resolver.list_catalog(
                vendor=vendor,
                device_type=device_type,
                status=status,
            ),
            "source": "assets/catalog/asset_registry.json",
        },
        "message": "",
    }


@router.get("/rack-assets/resolve")
def api_resolve_rack_visual_asset(
    vendor: str = Query('', max_length=128),
    model: str = Query('', max_length=128),
    device_type: str = Query('other', max_length=64),
    height_u: Optional[int] = Query(None, ge=1, le=60),
    model_key: str = Query('', max_length=128),
    _user=require_role("Viewer"),
):
    """Resolve a device to exact/family/vendor/generic visual metadata."""
    result = rack_asset_resolver.resolve_asset(
        vendor=vendor,
        model=model,
        device_type=device_type,
        height_u=height_u,
        model_key=model_key,
    )
    return {"success": True, "data": result, "message": ""}


# ─── Rack Devices ───────────────────────────────────────

@router.post("/racks/{rack_id}/placements", status_code=201)
def api_create_rack_placement(
    rack_id: str,
    body: RackPlacementCreate,
    _user=require_role("Operator"),
):
    """Create a canonical installation relation for one rack."""

    body_rack_id = str(body.rack_id or '').strip()
    if body_rack_id and body_rack_id != rack_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RACK_SCOPE_MISMATCH",
                "message": "rack_id in the request body does not match the URL",
                "details": {"path_rack_id": rack_id, "body_rack_id": body_rack_id},
            },
        )
    conn = get_db_connection()
    try:
        rack = rack_service.get_rack(conn, rack_id)
        rack_scope_service.enforce_loaded_rack(_user, rack, "update")
        payload = body.model_dump(exclude={'rack_id'})
        placement = rack_service.create_rack_device(
            conn,
            rack_id=rack_id,
            require_asset_record=True,
            **payload,
        )
        invalidate_read_cache('rack_page')
        return {"success": True, "data": placement, "message": "Placement created"}
    except ValueError as exc:
        raise _rack_http_exception(exc) from exc
    finally:
        conn.close()


@router.post("/racks/{rack_id}/validate-placement")
def api_validate_rack_placement(
    rack_id: str,
    body: RackPlacementValidate,
    _user=require_role("Viewer"),
):
    """Validate a placement without writing rack_devices or projections."""

    conn = get_db_connection()
    try:
        rack = rack_service.get_rack(conn, rack_id)
        rack_scope_service.enforce_loaded_rack(_user, rack, "view")
        result = rack_placement_service.validate(
            conn,
            rack_id=rack_id,
            device_type_id=body.device_type_id,
            start_u=body.start_u,
            position=body.position,
            mount_kind=body.mount_kind,
            height_u=body.height_u,
            asset_id=body.asset_id,
            exclude_device_id=body.exclude_placement_id,
            location_note=body.location_note,
            placement_status=body.placement_status,
            placement_source=body.placement_source,
            dimension_status=body.dimension_status,
            model_key=body.model_key,
            require_asset_record=True,
        )
        if result.get('valid'):
            return {"success": True, "data": result, "message": "Placement is valid"}
        try:
            rack_placement_service.raise_validation_failure(result)
        except rack_placement_service.RackPlacementError as exc:
            return {
                "success": False,
                "data": result,
                "error": {"code": exc.code, "message": exc.message, "details": exc.details},
                "message": "Placement is invalid",
            }
    finally:
        conn.close()


@router.patch("/rack-placements/{placement_id}")
def api_update_rack_placement(
    placement_id: str,
    body: RackDeviceUpdate,
    _user=require_role("Operator"),
):
    """Update a canonical installation relation through the shared service."""

    conn = get_db_connection()
    try:
        existing = rack_service.get_rack_device(conn, placement_id)
        old_rack = rack_service.get_rack(conn, str(existing.get("rack_id") or ""))
        rack_scope_service.enforce_loaded_rack(_user, old_rack, "update")
        target_rack_id = str(body.rack_id or existing.get("rack_id") or "")
        if target_rack_id != str(existing.get("rack_id") or ""):
            target_rack = rack_service.get_rack(conn, target_rack_id)
            rack_scope_service.enforce_loaded_rack(_user, target_rack, "update")
        placement = rack_service.update_rack_device(
            conn,
            placement_id,
            require_asset_record=True,
            **body.model_dump(exclude_unset=True),
        )
        invalidate_read_cache('rack_page')
        return {"success": True, "data": placement, "message": "Placement updated"}
    except ValueError as exc:
        raise _rack_http_exception(exc) from exc
    finally:
        conn.close()


@router.delete("/rack-placements/{placement_id}")
def api_delete_rack_placement(
    placement_id: str,
    _user=require_role("Operator"),
):
    """Delete a placement and clear its physical asset projection."""

    conn = get_db_connection()
    try:
        existing = rack_service.get_rack_device(conn, placement_id)
        rack = rack_service.get_rack(conn, str(existing.get("rack_id") or ""))
        rack_scope_service.enforce_loaded_rack(_user, rack, "delete")
        rack_service.delete_rack_device(conn, placement_id)
        invalidate_read_cache('rack_page')
        return {"success": True, "data": None, "message": "Placement deleted"}
    except ValueError as exc:
        raise _rack_http_exception(exc) from exc
    finally:
        conn.close()


@router.get("/racks/{rack_id}/devices")
def api_list_rack_devices(rack_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        # Do not turn a typo or unauthorized object lookup into a successful
        # empty list; callers need a distinguishable 404 for reconciliation.
        rack = rack_service.get_rack(conn, rack_id)
        rack_scope_service.enforce_loaded_rack(_user, rack, "view")
        devices = rack_service.list_rack_devices(conn, rack_id)
        return {"success": True, "data": devices, "message": ""}
    except ValueError as exc:
        raise _rack_http_exception(exc, default_status=404) from exc
    finally:
        conn.close()


@router.post("/rack-devices")
def api_create_rack_device(body: RackDeviceCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        rack = rack_service.get_rack(conn, body.rack_id)
        rack_scope_service.enforce_loaded_rack(user, rack, "update")
        device = rack_service.create_rack_device(conn, **body.model_dump())
        invalidate_read_cache('rack_page')
        return {"success": True, "data": device, "message": "Device installed"}
    except ValueError as e:
        raise _rack_http_exception(e) from e
    finally:
        conn.close()


@router.put("/rack-devices/{device_id}")
def api_update_rack_device(device_id: str, body: RackDeviceUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        existing = rack_service.get_rack_device(conn, device_id)
        rack = rack_service.get_rack(conn, str(existing.get("rack_id") or ""))
        rack_scope_service.enforce_loaded_rack(user, rack, "update")
        if body.rack_id and body.rack_id != existing.get("rack_id"):
            target = rack_service.get_rack(conn, body.rack_id)
            rack_scope_service.enforce_loaded_rack(user, target, "update")
        device = rack_service.update_rack_device(conn, device_id, **body.model_dump(exclude_unset=True))
        invalidate_read_cache('rack_page')
        return {"success": True, "data": device, "message": "Device updated"}
    except ValueError as e:
        raise _rack_http_exception(e) from e
    finally:
        conn.close()


@router.delete("/rack-devices/{device_id}")
def api_delete_rack_device(device_id: str, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        existing = rack_service.get_rack_device(conn, device_id)
        rack = rack_service.get_rack(conn, str(existing.get("rack_id") or ""))
        rack_scope_service.enforce_loaded_rack(user, rack, "delete")
        rack_service.delete_rack_device(conn, device_id)
        invalidate_read_cache('rack_page')
        return {"success": True, "data": None, "message": "Device removed"}
    except ValueError as e:
        raise _rack_http_exception(e) from e
    finally:
        conn.close()
