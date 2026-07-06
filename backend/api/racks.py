"""
racks.py — Rack Management API

Provides REST endpoints for managing racks, device types, and rack device installations.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from database import get_db_connection
from core.rbac import require_role
from schemas.schemas import (
    RackCreate, RackUpdate,
    DeviceTypeCreate, DeviceTypeUpdate,
    RackDeviceCreate, RackDeviceUpdate,
)
from services import rack_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Racks ──────────────────────────────────────────────

@router.get("/racks")
def api_list_racks(datacenter: str = Query('', description="Filter by datacenter"),
                   _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        racks = rack_service.list_racks(conn, datacenter=datacenter)
        return {"success": True, "data": racks, "message": ""}
    finally:
        conn.close()


@router.get("/racks/stats")
def api_rack_stats(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        stats = rack_service.get_rack_stats(conn)
        return {"success": True, "data": stats, "message": ""}
    finally:
        conn.close()


@router.get("/racks/{rack_id}")
def api_get_rack(rack_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        rack = rack_service.get_rack(conn, rack_id)
        return {"success": True, "data": rack, "message": ""}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()


@router.get("/racks/{rack_id}/layout")
def api_get_rack_layout(rack_id: str, _user=require_role("Viewer")):
    """Full rack layout including devices and occupancy stats."""
    conn = get_db_connection()
    try:
        layout = rack_service.get_rack_layout(conn, rack_id)
        return {"success": True, "data": layout, "message": ""}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()


@router.post("/racks")
def api_create_rack(body: RackCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        rack = rack_service.create_rack(conn, **body.model_dump())
        return {"success": True, "data": rack, "message": "Rack created"}
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.put("/racks/{rack_id}")
def api_update_rack(rack_id: str, body: RackUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        rack = rack_service.update_rack(conn, rack_id, **body.model_dump(exclude_unset=True))
        return {"success": True, "data": rack, "message": "Rack updated"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.delete("/racks/{rack_id}")
def api_delete_rack(rack_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        rack_service.delete_rack(conn, rack_id)
        return {"success": True, "data": None, "message": "Rack deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


# ─── Device Types ───────────────────────────────────────

@router.get("/device-types")
def api_list_device_types(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        types = rack_service.list_device_types(conn)
        return {"success": True, "data": types, "message": ""}
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
        return {"success": True, "data": dt, "message": "Device type created"}
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.put("/device-types/{dt_id}")
def api_update_device_type(dt_id: str, body: DeviceTypeUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        dt = rack_service.update_device_type(conn, dt_id, **body.model_dump(exclude_unset=True))
        return {"success": True, "data": dt, "message": "Device type updated"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.delete("/device-types/{dt_id}")
def api_delete_device_type(dt_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        rack_service.delete_device_type(conn, dt_id)
        return {"success": True, "data": None, "message": "Device type deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


# ─── Rack Devices ───────────────────────────────────────

@router.get("/racks/{rack_id}/devices")
def api_list_rack_devices(rack_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        devices = rack_service.list_rack_devices(conn, rack_id)
        return {"success": True, "data": devices, "message": ""}
    finally:
        conn.close()


@router.post("/rack-devices")
def api_create_rack_device(body: RackDeviceCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        device = rack_service.create_rack_device(conn, **body.model_dump())
        return {"success": True, "data": device, "message": "Device installed"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.put("/rack-devices/{device_id}")
def api_update_rack_device(device_id: str, body: RackDeviceUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        device = rack_service.update_rack_device(conn, device_id, **body.model_dump(exclude_unset=True))
        return {"success": True, "data": device, "message": "Device updated"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.delete("/rack-devices/{device_id}")
def api_delete_rack_device(device_id: str, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        rack_service.delete_rack_device(conn, device_id)
        return {"success": True, "data": None, "message": "Device removed"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
