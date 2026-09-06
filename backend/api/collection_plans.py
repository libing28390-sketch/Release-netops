"""Device collection-plan APIs used by the built-in inspection workflow."""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException

from core.rbac import require_role
from database import get_db_connection
from services.collection_plan_service import (
    collection_catalog,
    parse_collection_policy,
    resolve_collection_plan,
    validate_policy,
)


router = APIRouter(prefix="/collection-plans", tags=["collection-plans"])


def _device_row(device_id: str):
    conn = get_db_connection()
    try:
        return conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    finally:
        conn.close()


@router.get("/catalog")
def get_collection_catalog(_user=require_role("Viewer")):
    return {"success": True, "data": collection_catalog(), "message": ""}


@router.get("/devices")
def list_device_collection_plans(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, hostname, ip_address, platform, role, status, collection_policy_json "
            "FROM devices ORDER BY hostname"
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
def get_device_collection_plan(device_id: str, _user=require_role("Viewer")):
    row = _device_row(device_id)
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


@router.put("/devices/{device_id}")
def update_device_collection_plan(
    device_id: str,
    body: dict = Body(...),
    _user=require_role("Operator"),
):
    row = _device_row(device_id)
    if not row:
        raise HTTPException(status_code=404, detail="设备不存在")
    payload = body.get("policy", body)
    try:
        normalized = validate_policy(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE devices SET collection_policy_json = ? WHERE id = ?",
            (json.dumps({"collectors": normalized["collectors"]}, ensure_ascii=False), device_id),
        )
        conn.commit()
        updated = dict(conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone())
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
def reset_device_collection_plan(device_id: str, _user=require_role("Operator")):
    row = _device_row(device_id)
    if not row:
        raise HTTPException(status_code=404, detail="设备不存在")
    conn = get_db_connection()
    try:
        conn.execute("UPDATE devices SET collection_policy_json = '{}' WHERE id = ?", (device_id,))
        conn.commit()
        updated = dict(conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone())
    finally:
        conn.close()
    return {"success": True, "data": resolve_collection_plan(updated), "message": "已恢复角色默认采集计划"}
