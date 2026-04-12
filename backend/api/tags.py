"""
Tags API — 设备标签管理

GET    /api/tags/definitions            — 获取所有标签定义 (可选 ?category=vendor)
GET    /api/tags/definitions/{tag_id}   — 获取单个标签定义
POST   /api/tags/definitions            — 创建自定义标签
PUT    /api/tags/definitions/{tag_id}   — 更新标签
DELETE /api/tags/definitions/{tag_id}   — 删除自定义标签
GET    /api/tags/statistics             — 标签使用统计

GET    /api/tags/devices/{device_id}                — 获取设备的所有标签
PUT    /api/tags/devices/{device_id}                — 设置设备标签 (全量替换)
POST   /api/tags/devices/{device_id}/{tag_id}       — 给设备添加单个标签
DELETE /api/tags/devices/{device_id}/{tag_id}        — 移除设备的单个标签
POST   /api/tags/devices/batch                       — 批量给设备添加标签

GET    /api/tags/query                               — 按标签查找设备
POST   /api/tags/seed                                — 重新播种内置标签
"""

import logging
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from database import get_db_connection
from core.rbac import require_role
from services.audit_service import log_audit_event
from services import tag_service
from schemas.schemas import (
    TagDefinitionCreate,
    TagDefinitionUpdate,
    DeviceTagsUpdate,
    BatchDeviceTagsUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tags", tags=["tags"])


# ─── Tag Definitions ─────────────────────────

@router.get("/definitions")
def list_definitions(
    category: Optional[str] = Query(default=None, description="Filter by category"),
    current_user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        rows = tag_service.list_tag_definitions(conn, category)
        return {"success": True, "data": rows}
    finally:
        conn.close()


@router.get("/definitions/{tag_id}")
def get_definition(tag_id: str, current_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        tag = tag_service.get_tag_definition(conn, tag_id)
        if not tag:
            raise HTTPException(status_code=404, detail="Tag definition not found")
        return {"success": True, "data": tag}
    finally:
        conn.close()


@router.post("/definitions")
def create_definition(req: TagDefinitionCreate, current_user=require_role("Operator")):
    conn = get_db_connection()
    try:
        tag = tag_service.create_tag_definition(
            conn,
            category=req.category,
            value=req.value,
            label=req.label,
            label_zh=req.label_zh,
            color=req.color,
            icon=req.icon,
            description=req.description,
            sort_order=req.sort_order,
        )
        log_audit_event(
            conn=conn,
            event_type="create_tag",
            category="tags",
            severity="info",
            status="success",
            summary=f"Created tag {req.category}/{req.value}",
            actor_username=current_user.get('username', ''),
            actor_role=current_user.get('role', ''),
            target_type="tag_definition",
            target_id=tag["id"],
            details={"category": req.category, "value": req.value},
        )
        return {"success": True, "data": tag, "message": "Tag created"}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create tag: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        conn.close()


@router.put("/definitions/{tag_id}")
def update_definition(tag_id: str, req: TagDefinitionUpdate, current_user=require_role("Operator")):
    conn = get_db_connection()
    try:
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        tag = tag_service.update_tag_definition(conn, tag_id, **updates)
        if not tag:
            raise HTTPException(status_code=404, detail="Tag definition not found")
        log_audit_event(
            conn=conn,
            event_type="update_tag",
            category="tags",
            severity="info",
            status="success",
            summary=f"Updated tag {tag_id}",
            actor_username=current_user.get('username', ''),
            actor_role=current_user.get('role', ''),
            target_type="tag_definition",
            target_id=tag_id,
            details=updates,
        )
        return {"success": True, "data": tag}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update tag {tag_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        conn.close()


@router.delete("/definitions/{tag_id}")
def delete_definition(tag_id: str, current_user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        tag_service.delete_tag_definition(conn, tag_id)
        log_audit_event(
            conn=conn,
            event_type="delete_tag",
            category="tags",
            severity="warning",
            status="success",
            summary=f"Deleted tag {tag_id}",
            actor_username=current_user.get('username', ''),
            actor_role=current_user.get('role', ''),
            target_type="tag_definition",
            target_id=tag_id,
        )
        return {"success": True, "message": "Tag deleted"}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete tag {tag_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        conn.close()


@router.get("/statistics")
def tag_statistics(current_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        stats = tag_service.get_tag_statistics(conn)
        return {"success": True, "data": stats}
    finally:
        conn.close()


# ─── Device ↔ Tag associations ───────────────

@router.get("/devices/{device_id}")
def get_device_tags(device_id: str, current_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        tags = tag_service.get_device_tags(conn, device_id)
        return {"success": True, "data": tags}
    finally:
        conn.close()


@router.put("/devices/{device_id}")
def set_device_tags(device_id: str, req: DeviceTagsUpdate, current_user=require_role("Operator")):
    conn = get_db_connection()
    try:
        tags = tag_service.set_device_tags(conn, device_id, req.tag_ids, current_user.get('username', ''))
        log_audit_event(
            conn=conn,
            event_type="set_device_tags",
            category="tags",
            severity="info",
            status="success",
            summary=f"Set tags for device {device_id}",
            actor_username=current_user.get('username', ''),
            actor_role=current_user.get('role', ''),
            target_type="device",
            target_id=device_id,
            details={"tag_ids": req.tag_ids},
        )
        return {"success": True, "data": tags}
    finally:
        conn.close()


@router.post("/devices/{device_id}/{tag_id}")
def add_device_tag(device_id: str, tag_id: str, current_user=require_role("Operator")):
    conn = get_db_connection()
    try:
        added = tag_service.add_device_tag(conn, device_id, tag_id, current_user.get('username', ''))
        if not added:
            return {"success": True, "message": "Tag already assigned"}
        log_audit_event(
            conn=conn,
            event_type="add_device_tag",
            category="tags",
            severity="info",
            status="success",
            summary=f"Added tag {tag_id} to device {device_id}",
            actor_username=current_user.get('username', ''),
            actor_role=current_user.get('role', ''),
            target_type="device",
            target_id=device_id,
            details={"tag_id": tag_id},
        )
        return {"success": True, "message": "Tag added"}
    finally:
        conn.close()


@router.delete("/devices/{device_id}/{tag_id}")
def remove_device_tag(device_id: str, tag_id: str, current_user=require_role("Operator")):
    conn = get_db_connection()
    try:
        removed = tag_service.remove_device_tag(conn, device_id, tag_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Tag not assigned to device")
        log_audit_event(
            conn=conn,
            event_type="remove_device_tag",
            category="tags",
            severity="info",
            status="success",
            summary=f"Removed tag {tag_id} from device {device_id}",
            actor_username=current_user.get('username', ''),
            actor_role=current_user.get('role', ''),
            target_type="device",
            target_id=device_id,
            details={"tag_id": tag_id},
        )
        return {"success": True, "message": "Tag removed"}
    finally:
        conn.close()


@router.post("/devices/batch")
def batch_add_tags(req: BatchDeviceTagsUpdate, current_user=require_role("Operator")):
    conn = get_db_connection()
    try:
        count = tag_service.batch_set_device_tags(conn, req.device_ids, req.tag_ids, current_user.get('username', ''))
        log_audit_event(
            conn=conn,
            event_type="batch_add_tags",
            category="tags",
            severity="info",
            status="success",
            summary=f"Batch assigned tags to {len(req.device_ids)} devices",
            actor_username=current_user.get('username', ''),
            actor_role=current_user.get('role', ''),
            target_type="device",
            target_id=f"{len(req.device_ids)}_devices",
            details={"device_count": len(req.device_ids), "tag_ids": req.tag_ids, "assigned": count},
        )
        return {"success": True, "data": {"assigned": count}, "message": f"Assigned {count} tag(s)"}
    finally:
        conn.close()


# ─── Query by Tags ───────────────────────────

@router.get("/query")
def query_devices_by_tags(
    tag_ids: str = Query(description="Comma-separated tag IDs"),
    match_all: bool = Query(default=True, description="True=AND, False=OR"),
    current_user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        ids = [t.strip() for t in tag_ids.split(",") if t.strip()]
        if not ids:
            return {"success": True, "data": []}
        device_ids = tag_service.find_devices_by_tags(conn, ids, match_all)
        return {"success": True, "data": device_ids}
    finally:
        conn.close()


# ─── Seed / Re-seed built-in tags ────────────

@router.post("/seed")
def seed_tags(current_user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        count = tag_service.seed_builtin_tags(conn)
        return {"success": True, "data": {"inserted": count}, "message": f"Seeded {count} new tag(s)"}
    finally:
        conn.close()
