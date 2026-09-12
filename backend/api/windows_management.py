"""Windows WinRM HTTPS management API."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from core.rbac import require_permission
from services.windows_management_service import WindowsManagementError, service

router = APIRouter()


class WindowsServiceActionRequest(BaseModel):
    action: Literal["start", "stop", "restart"]
    confirm: bool = False
    reason: str = Field(default="", max_length=2_000)


def _raise_api_error(exc: WindowsManagementError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    ) from exc


@router.post("/windows/assets/{asset_id}/test")
def test_windows_asset(asset_id: str, user=require_permission("pam", "view")):
    try:
        return service.test_connection(asset_id, user)
    except WindowsManagementError as exc:
        _raise_api_error(exc)

@router.get("/windows/assets/{asset_id}/summary")
def windows_asset_summary(asset_id: str, user=require_permission("pam", "view")):
    try:
        return service.get_summary(asset_id, user)
    except WindowsManagementError as exc:
        _raise_api_error(exc)


@router.get("/windows/assets/{asset_id}/services")
def windows_asset_services(
    asset_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    search: str = Query(default="", max_length=200),
    status: str = Query(default="", max_length=40),
    user=require_permission("pam", "view"),
):
    try:
        return service.list_services(asset_id, user, page=page, page_size=page_size, search=search, status=status)
    except WindowsManagementError as exc:
        _raise_api_error(exc)


@router.post("/windows/assets/{asset_id}/services/{service_name}/actions")
def windows_asset_service_action(
    asset_id: str,
    service_name: str,
    body: WindowsServiceActionRequest = Body(...),
    user=require_permission("pam", "create_change"),
):
    try:
        return service.action_service(
            asset_id,
            service_name,
            body.action,
            confirm=body.confirm,
            reason=body.reason,
            user=user,
        )
    except WindowsManagementError as exc:
        _raise_api_error(exc)
