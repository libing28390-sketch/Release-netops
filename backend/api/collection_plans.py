"""Device collection-plan APIs used by the built-in inspection workflow."""

from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from core.rbac import require_role
from database import get_db_connection
from services.audit_service import log_audit_event
from services.collection_plan_service import (
    BulkSnapshotConflict,
    MultipleDevicesForIPAddress,
    apply_bulk_collection_plan,
    bulk_collection_plan_options,
    collection_catalog,
    collection_templates,
    collection_plan_for_ip,
    normalize_device_ip,
    parse_collection_policy,
    preview_bulk_collection_plan,
    resolve_collection_plan,
    validate_policy,
)
from services.nsot_collection_preview_service import (
    NSOTPreviewPermissionError,
    build_operation_catalog,
)


router = APIRouter(prefix="/collection-plans", tags=["collection-plans"])
logger = logging.getLogger(__name__)


class BulkCollectionPlanFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str | None = None
    role: str | None = None
    category: str | None = None
    platform: str | None = None


class BulkCollectionPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["apply", "reset"]
    template_id: str | None = None
    filters: BulkCollectionPlanFilters


class BulkCollectionPlanApplyRequest(BulkCollectionPlanRequest):
    snapshot_token: str


def _device_scope_clauses(
    tenant_id: str | None,
    site_ids: tuple[str, ...] | None,
    *,
    alias: str = "d",
) -> tuple[list[str], list[str]]:
    """Build the tenant/site predicates used by device policy read/write APIs."""
    clauses: list[str] = []
    params: list[str] = []
    if tenant_id:
        clauses.append(f"{alias}.tenant_id = ?")
        params.append(tenant_id)
    if site_ids is not None:
        normalized_site_ids = tuple(sorted({str(site_id) for site_id in site_ids if str(site_id)}))
        if not normalized_site_ids:
            clauses.append("1 = 0")
        else:
            clauses.append(
                f"{alias}.site_id IN ({','.join('?' for _ in normalized_site_ids)})"
            )
            params.extend(normalized_site_ids)
    return clauses, params


def _device_row(
    conn,
    device_id: str,
    *,
    tenant_id: str | None,
    site_ids: tuple[str, ...] | None,
):
    clauses, params = _device_scope_clauses(tenant_id, site_ids)
    where = ["d.id = ?", *clauses]
    return conn.execute(
        "SELECT d.* FROM devices d WHERE " + " AND ".join(where),
        (device_id, *params),
    ).fetchone()


def _bulk_collection_access_scope(conn, user: dict, action: str) -> tuple[str | None, tuple[str, ...] | None]:
    """Resolve bulk operation scope; tenant-less administrators remain global."""
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.get("role") == "Administrator":
        return None, None

    tenant_id = str(user.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Authenticated user is not assigned to a tenant")

    from services.rack_scope_service import allowed_resource_scope

    scope = allowed_resource_scope(conn, user, "asset", action)
    if scope.site_ids == ():
        raise HTTPException(status_code=403, detail="Insufficient permission for the device scope")
    return scope.tenant_id or tenant_id, scope.site_ids


def _device_ip_lookup_scope(conn, user: dict) -> tuple[str | None, tuple[str, ...] | None]:
    """Resolve asset:view scope while masking scope-denied IP lookups as misses."""
    if not isinstance(user, dict):
        return None, ()
    if user.get("role") == "Administrator":
        return None, None

    tenant_id = str(user.get("tenant_id") or "").strip()
    if not tenant_id:
        return None, ()

    from services.rack_scope_service import allowed_resource_scope

    scope = allowed_resource_scope(conn, user, "asset", "view")
    return scope.tenant_id or tenant_id, scope.site_ids


@router.get("/catalog")
def get_collection_catalog(_user=require_role("Viewer")):
    return {
        "success": True,
        "data": collection_catalog(),
        "templates": collection_templates(),
        "message": "",
    }


@router.get("/operation-catalog")
def get_nsot_collection_operation_catalog(
    platform_profile_id: str | None = Query(default=None, min_length=1, max_length=128),
    role: str = Query(default="switch", min_length=1, max_length=64),
    user=require_role("Viewer"),
):
    """Read the NSOT template → Quick Ops category → versioned command catalog."""
    conn = get_db_connection()
    try:
        try:
            data = build_operation_catalog(
                conn,
                user,
                platform_profile_id=platform_profile_id,
                role=role,
            )
        except NSOTPreviewPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    finally:
        conn.close()
    return {"success": True, "data": data, "message": ""}


@router.get("/bulk-options")
def get_bulk_collection_plan_options(user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        tenant_id, site_ids = _bulk_collection_access_scope(conn, user, "view")
        options = bulk_collection_plan_options(conn, tenant_id=tenant_id, site_ids=site_ids)
    finally:
        conn.close()
    return {"success": True, "data": options, "message": ""}


@router.get("/devices/by-ip")
def get_device_collection_plan_by_ip(ip: str, user=require_role("Viewer")):
    try:
        normalize_device_ip(ip)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    conn = get_db_connection()
    try:
        tenant_id, site_ids = _device_ip_lookup_scope(conn, user)
        try:
            result = collection_plan_for_ip(
                conn,
                ip,
                tenant_id=tenant_id,
                site_ids=site_ids,
            )
        except MultipleDevicesForIPAddress as exc:
            raise HTTPException(status_code=409, detail="多个授权设备使用该 IP") from exc
    finally:
        conn.close()

    if result is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    return {"success": True, "data": result, "message": ""}


@router.post("/bulk-preview")
def preview_bulk_collection_plan_api(
    body: BulkCollectionPlanRequest,
    user=require_role("Operator"),
):
    filters = body.filters.model_dump(exclude_none=True)
    conn = get_db_connection()
    try:
        try:
            tenant_id, site_ids = _bulk_collection_access_scope(conn, user, "update")
            preview = preview_bulk_collection_plan(
                conn,
                operation=body.operation,
                template_id=body.template_id,
                filters=filters,
                tenant_id=tenant_id,
                site_ids=site_ids,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()
    return {"success": True, "data": preview, "message": ""}


@router.post("/bulk-apply")
def apply_bulk_collection_plan_api(
    request: Request,
    body: BulkCollectionPlanApplyRequest,
    user=require_role("Operator"),
):
    filters = body.filters.model_dump(exclude_none=True)
    conn = get_db_connection()
    try:
        try:
            tenant_id, site_ids = _bulk_collection_access_scope(conn, user, "update")
            result = apply_bulk_collection_plan(
                conn,
                operation=body.operation,
                template_id=body.template_id,
                filters=filters,
                snapshot_token=body.snapshot_token,
                tenant_id=tenant_id,
                site_ids=site_ids,
            )
        except BulkSnapshotConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            # Do not expose database diagnostics or stored device policy data.
            raise HTTPException(status_code=500, detail="批量采集计划应用失败") from exc
    finally:
        conn.close()
    actor = user if isinstance(user, dict) else {}
    try:
        log_audit_event(
            event_type="COLLECTION_PLAN_BULK_UPDATED",
            category="automation",
            severity="medium",
            status="success",
            summary=f"Bulk collection plan {result['operation']} affected {result['affected_count']} device(s)",
            actor_username=actor.get("username", "unknown"),
            actor_role=actor.get("role", "Operator"),
            source_ip=request.client.host if request.client else None,
            target_type="device_collection_plan",
            target_name="bulk device scope",
            details={
                "operation": result["operation"],
                "template_id": result["template_id"],
                "filters": filters,
                "tenant_id": tenant_id,
                "site_ids": None if site_ids is None else list(site_ids),
                "affected_count": result["affected_count"],
            },
        )
    except Exception:
        # The policy transaction is already committed. Keep its response truthful
        # while making an audit backend failure visible to service operators.
        logger.exception("Failed to write audit event for bulk collection plan update")
    return {
        "success": True,
        "data": result,
        "message": "批量采集计划已应用，设备级 collector overrides 已清除",
    }


@router.get("/devices")
def list_device_collection_plans(user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        tenant_id, site_ids = _bulk_collection_access_scope(conn, user, "view")
        clauses, params = _device_scope_clauses(tenant_id, site_ids)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = conn.execute(
            "SELECT d.id, d.hostname, d.ip_address, d.platform, d.role, d.status, d.collection_policy_json "
            "FROM devices d" + where + " ORDER BY d.hostname",
            params,
        ).fetchall()
    finally:
        conn.close()
    items = []
    for row in rows:
        device = dict(row)
        plan = resolve_collection_plan(device)
        items.append(
            {
                "device": {
                    "id": device.get("id"),
                    "hostname": device.get("hostname") or device.get("ip_address") or "",
                    "ip_address": device.get("ip_address") or "",
                    "platform": device.get("platform") or "",
                    "role": device.get("role") or "",
                    "status": device.get("status") or "",
                },
                "plan": plan,
            }
        )
    return {"success": True, "data": items, "message": ""}


@router.get("/devices/{device_id}")
def get_device_collection_plan(device_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        tenant_id, site_ids = _bulk_collection_access_scope(conn, user, "view")
        row = _device_row(conn, device_id, tenant_id=tenant_id, site_ids=site_ids)
        if not row:
            raise HTTPException(status_code=404, detail="设备不存在")
        device = dict(row)
        return {
            "success": True,
            "data": {
                "device": {
                    "id": device.get("id"),
                    "hostname": device.get("hostname") or device.get("ip_address") or "",
                    "ip_address": device.get("ip_address") or "",
                    "platform": device.get("platform") or "",
                    "role": device.get("role") or "",
                    "status": device.get("status") or "",
                },
                "policy": parse_collection_policy(device.get("collection_policy_json")),
                "plan": resolve_collection_plan(device),
            },
            "message": "",
        }
    finally:
        conn.close()


@router.put("/devices/{device_id}")
def update_device_collection_plan(
    device_id: str,
    body: dict = Body(...),
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        tenant_id, site_ids = _bulk_collection_access_scope(conn, user, "update")
        row = _device_row(conn, device_id, tenant_id=tenant_id, site_ids=site_ids)
        if not row:
            raise HTTPException(status_code=404, detail="设备不存在")
        payload = body.get("policy", body)
        try:
            normalized = validate_policy(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Legacy PUT requests only carried collectors. Preserve a previously
        # selected template; when switching templates, old overrides are retained
        # only if the request explicitly supplies a collectors object.
        template_id = (
            normalized["template"]
            if "template" in payload
            else resolve_collection_plan(dict(row))["template_id"]
        )
        collector_overrides = normalized["collectors"]
        if "template" in payload and "collectors" not in payload:
            collector_overrides = {}

        stored_policy = {"template": template_id, "collectors": collector_overrides}
        clauses, scope_params = _device_scope_clauses(tenant_id, site_ids)
        where = ["id = ?", *clauses]
        cursor = conn.execute(
            "UPDATE devices SET collection_policy_json = ? WHERE " + " AND ".join(where),
            (json.dumps(stored_policy, ensure_ascii=False), device_id, *scope_params),
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="设备不存在")
        conn.commit()
        updated = dict(_device_row(conn, device_id, tenant_id=tenant_id, site_ids=site_ids))
    finally:
        conn.close()

    return {
        "success": True,
        "data": {
            "device_id": device_id,
            "policy": parse_collection_policy(updated.get("collection_policy_json")),
            "plan": resolve_collection_plan(updated),
            "ignored_keys": normalized["ignored_keys"],
        },
        "message": "采集计划已更新",
    }


@router.delete("/devices/{device_id}")
def reset_device_collection_plan(device_id: str, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        tenant_id, site_ids = _bulk_collection_access_scope(conn, user, "update")
        row = _device_row(conn, device_id, tenant_id=tenant_id, site_ids=site_ids)
        if not row:
            raise HTTPException(status_code=404, detail="设备不存在")
        clauses, scope_params = _device_scope_clauses(tenant_id, site_ids)
        where = ["id = ?", *clauses]
        cursor = conn.execute(
            "UPDATE devices SET collection_policy_json = ? WHERE " + " AND ".join(where),
            (
                json.dumps({"template": "role_default", "collectors": {}}, ensure_ascii=False),
                device_id,
                *scope_params,
            ),
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="设备不存在")
        conn.commit()
        updated = dict(_device_row(conn, device_id, tenant_id=tenant_id, site_ids=site_ids))
    finally:
        conn.close()
    return {"success": True, "data": resolve_collection_plan(updated), "message": "已恢复角色默认采集计划"}
