"""Authenticated API for reusable topology device icons."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.rbac import require_role
from services.topology_icon_service import (
    DEVICE_TYPES,
    MAX_ICON_SIZE_BYTES,
    TopologyIconError,
    create_topology_icon,
    get_topology_icon_content,
    list_topology_icons,
    set_topology_device_icon,
    set_topology_icon_default,
)


router = APIRouter(
    prefix="/topology/icons",
    tags=["topology-icons"],
    dependencies=[require_role("Viewer")],
)


class IconAssignmentRequest(BaseModel):
    icon_id: str | None = Field(..., max_length=36)


class DeviceIconAssignmentRequest(IconAssignmentRequest):
    device_type: str = Field(..., min_length=1, max_length=40)


def _raise_http_error(error: TopologyIconError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _actor_id(user: dict[str, Any]) -> str:
    return str(user.get("user_id") or user.get("id") or "")


@router.get("")
def get_topology_icons(request: Request) -> dict[str, Any]:
    try:
        catalog = list_topology_icons()
    except TopologyIconError as error:
        _raise_http_error(error)
    user = getattr(request.state, "nexora_session_auth_user", {}) or {}
    catalog["can_manage"] = str(user.get("role") or "") in {"Operator", "Administrator"}
    catalog["device_types"] = sorted(DEVICE_TYPES)
    return catalog


@router.post("")
def upload_topology_icon(
    device_type: str = Form(..., min_length=1, max_length=40),
    name: str = Form(..., min_length=1, max_length=80),
    file: UploadFile = File(...),
    _operator=require_role("Operator"),
) -> dict[str, Any]:
    try:
        content = file.file.read(MAX_ICON_SIZE_BYTES + 1)
        if len(content) > MAX_ICON_SIZE_BYTES:
            raise TopologyIconError("Icon file must be 4 MiB or smaller")
        icon = create_topology_icon(
            device_type=device_type,
            name=name,
            filename=file.filename or "",
            content_type=file.content_type,
            content=content,
            actor_id=_actor_id(_operator),
        )
        return icon
    except TopologyIconError as error:
        _raise_http_error(error)
    finally:
        file.file.close()


@router.get("/{icon_id}/content")
def read_topology_icon_content(icon_id: str) -> Response:
    try:
        content, content_type = get_topology_icon_content(icon_id)
    except TopologyIconError as error:
        _raise_http_error(error)
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            "Content-Disposition": "inline",
        },
    )


@router.put("/defaults/{device_type}")
def put_topology_icon_default(
    device_type: str,
    payload: IconAssignmentRequest,
    _operator=require_role("Operator"),
) -> dict[str, bool]:
    try:
        set_topology_icon_default(device_type=device_type, icon_id=payload.icon_id, actor_id=_actor_id(_operator))
    except TopologyIconError as error:
        _raise_http_error(error)
    return {"success": True}


@router.put("/devices/{device_id}")
def put_topology_device_icon(
    device_id: str,
    payload: DeviceIconAssignmentRequest,
    _operator=require_role("Operator"),
) -> dict[str, bool]:
    try:
        set_topology_device_icon(
            device_id=device_id,
            device_type=payload.device_type,
            icon_id=payload.icon_id,
            actor_id=_actor_id(_operator),
        )
    except TopologyIconError as error:
        _raise_http_error(error)
    return {"success": True}


__all__ = ["router"]
