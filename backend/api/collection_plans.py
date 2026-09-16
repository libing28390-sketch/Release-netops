"""Device collection-plan APIs used by the built-in inspection workflow."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

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
    validate_nsot_template_payload,
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


class NSOTCollectionTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_zh: str
    name_en: str
    description_zh: str = ""
    description_en: str = ""
    collector_keys: list[str] = Field(default_factory=list)


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
    conn = get_db_connection()
    try:
        templates = collection_templates(conn)
    finally:
        conn.close()
    return {"success": True, "data": collection_catalog(), "templates": templates, "message": ""}


def _managed_template_response(conn, template_id: str) -> dict:
    for template in collection_templates(conn):
        if str(template.get("id") or "") == template_id:
            return template
    raise HTTPException(status_code=404, detail="NSOT 采集模板不存在")


@router.get("/templates")
def list_nsot_collection_templates(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        templates = collection_templates(conn)
    finally:
        conn.close()
    return {"success": True, "data": templates, "message": ""}


@router.post("/templates")
def create_nsot_collection_template(
    body: NSOTCollectionTemplateRequest,
    request: Request,
    user=require_role("Operator"),
):
    try:
        payload = validate_nsot_template_payload(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    template_id = f"nsot-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO nsot_collection_templates
              (id, name_zh, name_en, description_zh, description_en,
               collector_keys, builtin, created_by, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
            (
                template_id,
                payload["name_zh"],
                payload["name_en"],
                payload["description_zh"],
                payload["description_en"],
                json.dumps(payload["collector_keys"], ensure_ascii=False),
                str(user.get("username") or ""),
                now,
                now,
            ),
        )
        conn.commit()
        created = _managed_template_response(conn, template_id)
    finally:
        conn.close()
    log_audit_event(
        event_type="NSOT_COLLECTION_TEMPLATE_CREATED",
        category="automation",
        severity="info",
        status="success",
        summary=f"Created NSOT collection template {template_id}",
        actor_username=user.get("username", "unknown"),
        actor_role=user.get("role", "Operator"),
        source_ip=request.client.host if request.client else None,
        target_type="nsot_collection_template",
        target_name=template_id,
        details={"collector_keys": payload["collector_keys"]},
    )
    return {"success": True, "data": created, "message": "NSOT 采集模板已创建"}


@router.put("/templates/{template_id}")
def update_nsot_collection_template(
    template_id: str,
    body: NSOTCollectionTemplateRequest,
    request: Request,
    user=require_role("Operator"),
):
    try:
        payload = validate_nsot_template_payload(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn = get_db_connection()
    try:
        existing = conn.execute(
            "SELECT builtin FROM nsot_collection_templates WHERE id = ?",
            (template_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="NSOT 采集模板不存在")
        conn.execute(
            """UPDATE nsot_collection_templates
                  SET name_zh = ?, name_en = ?, description_zh = ?, description_en = ?,
                      collector_keys = ?, updated_at = ?
                WHERE id = ?""",
            (
                payload["name_zh"],
                payload["name_en"],
                payload["description_zh"],
                payload["description_en"],
                json.dumps(payload["collector_keys"], ensure_ascii=False),
                now,
                template_id,
            ),
        )
        conn.commit()
        updated = _managed_template_response(conn, template_id)
    finally:
        conn.close()
    log_audit_event(
        event_type="NSOT_COLLECTION_TEMPLATE_UPDATED",
        category="automation",
        severity="info",
        status="success",
        summary=f"Updated NSOT collection template {template_id}",
        actor_username=user.get("username", "unknown"),
        actor_role=user.get("role", "Operator"),
        source_ip=request.client.host if request.client else None,
        target_type="nsot_collection_template",
        target_name=template_id,
        details={"collector_keys": payload["collector_keys"]},
    )
    return {"success": True, "data": updated, "message": "NSOT 采集模板已更新"}


@router.delete("/templates/{template_id}")
def delete_nsot_collection_template(
    template_id: str,
    request: Request,
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        existing = conn.execute(
            "SELECT builtin FROM nsot_collection_templates WHERE id = ?",
            (template_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="NSOT 采集模板不存在")
        conn.execute("DELETE FROM nsot_collection_templates WHERE id = ?", (template_id,))
        conn.commit()
    finally:
        conn.close()
    log_audit_event(
        event_type="NSOT_COLLECTION_TEMPLATE_DELETED",
        category="automation",
        severity="medium",
        status="success",
        summary=f"Deleted NSOT collection template {template_id}",
        actor_username=user.get("username", "unknown"),
        actor_role=user.get("role", "Operator"),
        source_ip=request.client.host if request.client else None,
        target_type="nsot_collection_template",
        target_name=template_id,
        details={"builtin": bool(existing["builtin"])},
    )
    return {"success": True, "message": "NSOT 采集模板已删除"}


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
        previous_policy = parse_collection_policy(row.get("collection_policy_json"))
        monitoring = normalized.get("monitoring")
        if monitoring is None:
            monitoring = previous_policy.get("monitoring") or previous_policy.get("monitoring_modules")
        if monitoring is not None:
            stored_policy["monitoring"] = monitoring
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
