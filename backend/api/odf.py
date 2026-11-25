"""
odf.py — ODF 光纤配线架 CMDB REST API

Mounted under ``/api/odf`` with full RBAC + tenant/site scope enforcement
matching ``api/racks.py`` and TTL read-cache invalidation.
"""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.rbac import require_role
from core.read_cache import RACK_CACHE_TTL_SECONDS, invalidate_read_cache, read_cache
from database import get_db_connection
from services import odf_service, rack_scope_service

logger = logging.getLogger(__name__)
router = APIRouter()


class OdfFrameCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    site_id: str = Field(default='', max_length=64)
    frame_code: str = Field(default='', max_length=64)
    vendor: str = Field(default='Huawei', max_length=80)
    model: str = Field(default='GPX147-576F', max_length=120)
    floor: str = Field(default='', max_length=100)
    room: str = Field(default='', max_length=100)
    row: str = Field(default='', max_length=50)
    rack_id: str = Field(default='', max_length=64)
    tray_count: int = Field(default=12, ge=1, le=24)
    ports_per_tray: int = Field(default=48, ge=12, le=96)
    connector_type: str = Field(default='LC/UPC', max_length=24)
    fiber_mode: str = Field(default='OS2', max_length=24)
    status: str = Field(default='active', max_length=24)
    remarks: str = Field(default='', max_length=1000)


class OdfFrameUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    site_id: Optional[str] = Field(default=None, max_length=64)
    frame_code: Optional[str] = Field(default=None, max_length=64)
    vendor: Optional[str] = Field(default=None, max_length=80)
    model: Optional[str] = Field(default=None, max_length=120)
    floor: Optional[str] = Field(default=None, max_length=100)
    room: Optional[str] = Field(default=None, max_length=100)
    row: Optional[str] = Field(default=None, max_length=50)
    rack_id: Optional[str] = Field(default=None, max_length=64)
    connector_type: Optional[str] = Field(default=None, max_length=24)
    fiber_mode: Optional[str] = Field(default=None, max_length=24)
    status: Optional[str] = Field(default=None, max_length=24)
    remarks: Optional[str] = Field(default=None, max_length=1000)


class OdfTrayUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=160)
    fiber_mode: Optional[str] = Field(default=None, max_length=24)
    connector_type: Optional[str] = Field(default=None, max_length=24)
    status: Optional[str] = Field(default=None, max_length=24)
    remarks: Optional[str] = Field(default=None, max_length=500)


class OdfPortUpsert(BaseModel):
    status: str = Field(default='occupied', max_length=24)
    fiber_type: str = Field(default='', max_length=24)
    connector_type: str = Field(default='', max_length=24)
    a_device_id: str = Field(default='', max_length=64)
    a_device_name: str = Field(default='', max_length=160)
    a_interface_name: str = Field(default='', max_length=120)
    a_rack_name: str = Field(default='', max_length=120)
    z_endpoint_type: str = Field(default='device', max_length=24)
    z_device_id: str = Field(default='', max_length=64)
    z_device_name: str = Field(default='', max_length=160)
    z_interface_name: str = Field(default='', max_length=120)
    z_odf_frame_id: str = Field(default='', max_length=64)
    z_odf_port_code: str = Field(default='', max_length=48)
    z_peer_label: str = Field(default='', max_length=200)
    cable_tag: str = Field(default='', max_length=120)
    circuit_id: str = Field(default='', max_length=120)
    attenuation_db: Optional[float] = None
    remarks: str = Field(default='', max_length=1000)
    pair_next: bool = False


def _enforce_frame_scope(user, frame: dict, action: str) -> None:
    rack_scope_service.enforce_loaded_rack(user, frame, action)


@router.get("/odf/frames")
def api_list_odf_frames(
    site_id: str = Query('', max_length=64),
    keyword: str = Query('', max_length=200),
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        odf_service.ensure_odf_tables(conn)
        scope = rack_scope_service.allowed_rack_scope(conn, user, "view")
        cache_key = f"frames:{scope.cache_key}:{site_id}:{keyword}"
        hit, cached = read_cache.get("odf_page", cache_key)
        if hit:
            return cached
        items = odf_service.list_odf_frames(
            conn,
            site_id=site_id,
            keyword=keyword,
            tenant_id=scope.tenant_id,
            allowed_site_ids=scope.site_ids,
        )
        resp = {"success": True, "data": items, "message": ""}
        read_cache.set("odf_page", cache_key, resp, RACK_CACHE_TTL_SECONDS)
        return resp
    finally:
        conn.close()


@router.get("/odf/stats")
def api_odf_stats(user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        odf_service.ensure_odf_tables(conn)
        scope = rack_scope_service.allowed_rack_scope(conn, user, "view")
        cache_key = f"stats:{scope.cache_key}"
        hit, cached = read_cache.get("odf_page", cache_key)
        if hit:
            return cached
        stats = odf_service.get_odf_stats(
            conn,
            tenant_id=scope.tenant_id,
            allowed_site_ids=scope.site_ids,
        )
        resp = {"success": True, "data": stats, "message": ""}
        read_cache.set("odf_page", cache_key, resp, RACK_CACHE_TTL_SECONDS)
        return resp
    finally:
        conn.close()


@router.get("/odf/trace")
def api_trace_odf(
    q: str = Query('', max_length=200),
    limit: int = Query(100, ge=1, le=200),
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        odf_service.ensure_odf_tables(conn)
        scope = rack_scope_service.allowed_rack_scope(conn, user, "view")
        items = odf_service.trace_odf_links(
            conn,
            query=q,
            tenant_id=scope.tenant_id,
            allowed_site_ids=scope.site_ids,
            limit=limit,
        )
        return {"success": True, "data": items, "message": ""}
    finally:
        conn.close()


@router.get("/odf/lookup/devices")
def api_lookup_odf_devices(
    q: str = Query('', max_length=120),
    limit: int = Query(80, ge=1, le=200),
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        scope = rack_scope_service.allowed_rack_scope(conn, user, "view")
        items = odf_service.lookup_bindable_devices(
            conn,
            keyword=q,
            tenant_id=scope.tenant_id,
            allowed_site_ids=scope.site_ids,
            limit=limit,
        )
        return {"success": True, "data": items, "message": ""}
    finally:
        conn.close()


@router.get("/odf/lookup/devices/{device_id}/interfaces")
def api_lookup_odf_device_interfaces(device_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        items = odf_service.lookup_device_interfaces(conn, device_id)
        return {"success": True, "data": items, "message": ""}
    finally:
        conn.close()


@router.post("/odf/frames", status_code=201)
def api_create_odf_frame(body: OdfFrameCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        odf_service.ensure_odf_tables(conn)
        if body.site_id:
            rack_scope_service.enforce_site(conn, user, body.site_id, "create")
        detail = odf_service.create_odf_frame(conn, **body.model_dump())
        _enforce_frame_scope(user, detail, "create")
        invalidate_read_cache("odf_page")
        return {"success": True, "data": detail, "message": "ODF frame created"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/odf/frames/{frame_id}/detail")
def api_get_odf_frame_detail(frame_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        odf_service.ensure_odf_tables(conn)
        frame = odf_service.get_odf_frame(conn, frame_id)
        _enforce_frame_scope(user, frame, "view")
        cache_key = f"detail:{frame_id}"
        hit, cached = read_cache.get("odf_page", cache_key)
        if hit:
            return cached
        detail = odf_service.get_odf_frame_detail(conn, frame_id)
        resp = {"success": True, "data": detail, "message": ""}
        read_cache.set("odf_page", cache_key, resp, RACK_CACHE_TTL_SECONDS)
        return resp
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()


@router.put("/odf/frames/{frame_id}")
def api_update_odf_frame(frame_id: str, body: OdfFrameUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        odf_service.ensure_odf_tables(conn)
        existing = odf_service.get_odf_frame(conn, frame_id)
        _enforce_frame_scope(user, existing, "update")
        detail = odf_service.update_odf_frame(conn, frame_id, **body.model_dump(exclude_unset=True))
        invalidate_read_cache("odf_page")
        return {"success": True, "data": detail, "message": "ODF frame updated"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.delete("/odf/frames/{frame_id}")
def api_delete_odf_frame(
    frame_id: str,
    force: bool = Query(False),
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        odf_service.ensure_odf_tables(conn)
        existing = odf_service.get_odf_frame(conn, frame_id)
        _enforce_frame_scope(user, existing, "delete")
        odf_service.delete_odf_frame(conn, frame_id, force=force)
        invalidate_read_cache("odf_page")
        return {"success": True, "data": None, "message": "ODF frame deleted"}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        conn.close()


@router.put("/odf/trays/{tray_id}")
def api_update_odf_tray(tray_id: str, body: OdfTrayUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        odf_service.ensure_odf_tables(conn)
        row = conn.execute("SELECT frame_id FROM odf_trays WHERE id = ?", (tray_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="ODF tray not found")
        frame = odf_service.get_odf_frame(conn, row['frame_id'] if hasattr(row, 'keys') else row[0])
        _enforce_frame_scope(user, frame, "update")
        tray = odf_service.update_odf_tray(conn, tray_id, **body.model_dump(exclude_unset=True))
        invalidate_read_cache("odf_page")
        return {"success": True, "data": tray, "message": "ODF tray updated"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.put("/odf/frames/{frame_id}/ports/{tray_no}/{port_no}")
def api_upsert_odf_port(
    frame_id: str,
    tray_no: int,
    port_no: int,
    body: OdfPortUpsert,
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        odf_service.ensure_odf_tables(conn)
        existing = odf_service.get_odf_frame(conn, frame_id)
        _enforce_frame_scope(user, existing, "update")
        actor = str(user.get('username') or user.get('user_id') or 'operator') if isinstance(user, dict) else 'operator'
        saved = odf_service.upsert_odf_port(
            conn,
            frame_id=frame_id,
            tray_no=tray_no,
            port_no=port_no,
            updated_by=actor,
            **body.model_dump(),
        )
        invalidate_read_cache("odf_page")
        return {"success": True, "data": saved, "message": "ODF port updated"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()
