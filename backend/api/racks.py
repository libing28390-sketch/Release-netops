"""
racks.py — Rack Management API

Provides REST endpoints for managing racks, device types, and rack device installations.
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from database import get_db_connection
from core.rbac import require_role
from schemas.schemas import (
    RackCreate, RackUpdate, RackTypeCreate, RackTypeUpdate,
    DeviceTypeCreate, DeviceTypeUpdate,
    RackDeviceCreate, RackDeviceUpdate,
)
from services import rack_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Racks ──────────────────────────────────────────────

@router.get("/racks")
def api_list_racks(site_id: str = Query('', description="Filter by site"),
                   datacenter: str = Query('', include_in_schema=False),
                   _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        racks = rack_service.list_racks(conn, site_id=site_id, datacenter=datacenter)
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


# 鈹€鈹€鈹€ Rack Types 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.get("/rack-types")
def api_list_rack_types(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        types = rack_service.list_rack_types(conn)
        return {"success": True, "data": types, "message": ""}
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
        return {"success": True, "data": rt, "message": "Rack type created"}
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.put("/rack-types/{rack_type_id}")
def api_update_rack_type(rack_type_id: str, body: RackTypeUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        rt = rack_service.update_rack_type(conn, rack_type_id, **body.model_dump(exclude_unset=True))
        return {"success": True, "data": rt, "message": "Rack type updated"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.delete("/rack-types/{rack_type_id}")
def api_delete_rack_type(rack_type_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        rack_service.delete_rack_type(conn, rack_type_id)
        return {"success": True, "data": None, "message": "Rack type deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.get("/racks/validate-u")
def api_validate_u_position(
    rack: str = Query(..., description="Rack name or rack_code"),
    start_u: int = Query(..., description="Start U position"),
    u_height: int = Query(..., description="U height"),
    exclude_asset_id: str = Query('', description="Asset ID to exclude"),
    _user=require_role("Viewer")
):
    conn = get_db_connection()
    try:
        rack_row = conn.execute("SELECT id, total_u FROM racks WHERE name = ? OR rack_name = ?", (rack, rack)).fetchone()
        if not rack_row:
            return {"success": False, "reason": f"机柜 '{rack}' 不存在"}

        rack_id = rack_row['id']
        total_u = rack_row['total_u']
        end_u = start_u + u_height - 1

        if start_u < 1:
            return {"success": False, "reason": f"起始 U 位必须大于或等于 1 (当前: {start_u})"}
        if end_u > total_u:
            return {"success": False, "reason": f"设备超出机柜高度范围：占用 U{start_u}-U{end_u}，但机柜总高度仅有 {total_u}U"}

        exclude_device_id = ''
        if exclude_asset_id:
            rd_row = conn.execute("SELECT id FROM rack_devices WHERE asset_id = ?", (exclude_asset_id,)).fetchone()
            if rd_row:
                exclude_device_id = rd_row['id']

        query = """
            SELECT rd.name, rd.start_u, dt.u_height
            FROM rack_devices rd
            JOIN device_types dt ON rd.device_type_id = dt.id
            WHERE rd.rack_id = ? AND rd.position = 'front'
        """
        params = [rack_id]
        if exclude_device_id:
            query += " AND rd.id != ?"
            params.append(exclude_device_id)

        existing = conn.execute(query, params).fetchall()
        for dev in existing:
            existing_start = dev['start_u']
            existing_end = existing_start + dev['u_height'] - 1
            if start_u <= existing_end and end_u >= existing_start:
                return {
                    "success": False,
                    "reason": f"U位冲突：U{start_u}-U{end_u} 与已上架设备 '{dev['name']}' (U{existing_start}-U{existing_end}) 空间重叠。"
                }

        return {"success": True, "reason": ""}
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


@router.post("/racks/batch")
def api_batch_create_racks(body: List[RackCreate], user=require_role("Operator")):
    conn = get_db_connection()
    try:
        conn.execute("BEGIN")
        created_racks = []
        for i, rack_data in enumerate(body):
            try:
                rack = rack_service.create_rack(conn, commit=False, **rack_data.model_dump())
                created_racks.append(rack)
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"导入第 {i+1} 行机柜数据失败: {str(e)}")
        conn.commit()
        return {"success": True, "data": created_racks, "message": f"成功导入 {len(created_racks)} 个机柜"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
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
