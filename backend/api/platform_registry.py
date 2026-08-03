"""P0 platform registry API.

HTTP handlers only validate authorization/status; release and execution rules
live in ``services.platform_registry_service`` so background consumers can use
the same boundary.
"""

from __future__ import annotations

import logging
import os
from pydantic import BaseModel, Field

from fastapi import APIRouter, Body, HTTPException, Path, Query

from core.rbac import require_permission, require_role
from services.platform_registry_service import (
    PlatformRegistryError,
    create_profile,
    create_release,
    execute_platform_action,
    get_profile,
    list_profiles,
    list_release_actions,
    preview_platform_migration,
    preview_platform_action,
    rollback_profile,
    transition_release,
    update_release_action,
    validate_release,
)
from services.platform_identification_service import (
    bind_device,
    identify_device,
    identify_device_live,
    list_identification_conflicts,
)
from services.platform_registry_health_service import create_sample_from_failed_run, get_profile_health

router = APIRouter(prefix="/platform-registry", tags=["platform-registry"])
logger = logging.getLogger(__name__)


class PlatformIdentifyRequest(BaseModel):
    observations: dict[str, str] = Field(..., min_length=1)
    platform_code: str = Field(default="", max_length=64)


class PlatformBindingRequest(BaseModel):
    platform_profile_id: str = Field(..., min_length=1, max_length=128)
    lock: bool = False
    force: bool = False


class PlatformDetectRequest(BaseModel):
    observations: dict[str, str] = Field(default_factory=dict)
    platform_code: str = Field(default="", max_length=64)


# Compatibility endpoints keep device-facing consumers independent from the
# registry namespace while the registry-specific routes remain available.
device_registry_router = APIRouter(tags=["platform-registry"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except PlatformRegistryError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Platform registry operation failed")
        raise HTTPException(status_code=500, detail={"code": "PLATFORM_REGISTRY_ERROR", "message": "Platform registry operation failed"}) from exc


def _require_registry_enabled() -> None:
    enabled = os.environ.get("PLATFORM_REGISTRY_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "PLATFORM_REGISTRY_DISABLED",
                "message": "Platform registry write and execution APIs are disabled",
            },
        )


@router.get("/profiles")
def api_list_profiles(user=require_permission("platform", "read")):
    return {"success": True, "data": _call(list_profiles, user), "message": ""}


@router.get("/migration/preview")
def api_preview_platform_migration(user=require_permission("platform", "read")):
    """Preview legacy device/template migration conflicts without mutation."""
    return {"success": True, "data": _call(preview_platform_migration, user), "message": ""}


@router.get("/profiles/{profile_id}/health")
def api_get_profile_health(
    profile_id: str = Path(..., min_length=1),
    range_hours: int = Query(default=168, ge=1, le=720),
    user=require_permission("platform", "read"),
):
    return {"success": True, "data": _call(get_profile_health, profile_id, user, range_hours=range_hours), "message": ""}


@router.get("/identification-conflicts")
def api_list_identification_conflicts(
    status: str = Query(default="OPEN", min_length=3, max_length=16),
    limit: int = Query(default=100, ge=1, le=500),
    user=require_permission("platform", "view"),
):
    return {"success": True, "data": _call(list_identification_conflicts, user, status=status, limit=limit), "message": ""}


@router.post("/profiles")
def api_create_profile(payload: dict = Body(...), user=require_permission("platform", "create")):
    _require_registry_enabled()
    return {"success": True, "data": _call(create_profile, payload, user), "message": "Platform profile created"}


@router.get("/profiles/{profile_id}")
def api_get_profile(profile_id: str = Path(..., min_length=1), user=require_permission("platform", "read")):
    return {"success": True, "data": _call(get_profile, profile_id, user), "message": ""}


@router.post("/profiles/{profile_id}/releases")
def api_create_release(profile_id: str, payload: dict = Body(default={}), user=require_permission("platform", "edit_draft")):
    _require_registry_enabled()
    return {"success": True, "data": _call(create_release, profile_id, payload, user), "message": "Draft release created"}


@router.get("/profiles/{profile_id}/actions")
def api_list_actions(profile_id: str, user=require_permission("command", "view")):
    return {"success": True, "data": _call(list_release_actions, profile_id, user), "message": ""}


@router.put("/releases/{release_id}/actions/{action_code}")
def api_update_action(release_id: str, action_code: str, payload: dict = Body(...), user=require_permission("command", "edit_draft")):
    _require_registry_enabled()
    return {"success": True, "data": _call(update_release_action, release_id, action_code, payload, user), "message": "Action mapping saved"}


@router.post("/releases/{release_id}/validate")
def api_validate_release(release_id: str, user=require_permission("platform", "edit_draft")):
    _require_registry_enabled()
    return {"success": True, "data": _call(validate_release, release_id, user), "message": ""}


@router.post("/releases/{release_id}/submit")
def api_submit_release(release_id: str, user=require_permission("platform", "submit")):
    _require_registry_enabled()
    return {"success": True, "data": _call(transition_release, release_id, "submit", user), "message": "Release submitted"}


@router.post("/releases/{release_id}/approve")
def api_approve_release(release_id: str, user=require_permission("platform", "approve")):
    _require_registry_enabled()
    return {"success": True, "data": _call(transition_release, release_id, "approve", user), "message": "Release approved"}


@router.post("/releases/{release_id}/publish")
def api_publish_release(release_id: str, user=require_permission("platform", "publish")):
    _require_registry_enabled()
    return {"success": True, "data": _call(transition_release, release_id, "publish", user), "message": "Release published"}


@router.post("/profiles/{profile_id}/rollback")
def api_rollback_profile(profile_id: str, payload: dict = Body(default={}), user=require_permission("platform", "rollback")):
    _require_registry_enabled()
    return {"success": True, "data": _call(rollback_profile, profile_id, payload.get("release_id"), user), "message": "Platform rolled back"}


@router.post("/actions/execute")
def api_execute_action(payload: dict = Body(...), user=require_permission("command", "execute")):
    _require_registry_enabled()
    device_id = str(payload.get("device_id") or "").strip()
    action_code = str(payload.get("action_code") or "").strip()
    if not device_id or not action_code:
        raise HTTPException(status_code=400, detail={"code": "INVALID_ACTION_REQUEST", "message": "device_id and action_code are required"})
    parameters = payload.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise HTTPException(status_code=400, detail={"code": "INVALID_ACTION_PARAMETERS", "message": "parameters must be an object"})
    return {"success": True, "data": _call(execute_platform_action, device_id, action_code, user=user, parameters=parameters), "message": ""}


@router.post("/actions/preview")
def api_preview_action(payload: dict = Body(...), user=require_permission("command", "execute")):
    """Resolve a published action and parameters without opening a device connection."""
    _require_registry_enabled()
    device_id = str(payload.get("device_id") or "").strip()
    action_code = str(payload.get("action_code") or "").strip()
    parameters = payload.get("parameters") or {}
    if not device_id or not action_code:
        raise HTTPException(status_code=400, detail={"code": "INVALID_ACTION_REQUEST", "message": "device_id and action_code are required"})
    if not isinstance(parameters, dict):
        raise HTTPException(status_code=400, detail={"code": "INVALID_ACTION_PARAMETERS", "message": "parameters must be an object"})
    return {"success": True, "data": _call(preview_platform_action, device_id, action_code, user=user, parameters=parameters), "message": ""}


@router.post("/runs/{run_id}/parser-sample")
def api_create_sample_from_failed_run(
    run_id: str = Path(..., min_length=1),
    payload: dict = Body(default={}),
    user=require_permission("sample_output", "upload"),
):
    _require_registry_enabled()
    return {
        "success": True,
        "data": _call(create_sample_from_failed_run, run_id, payload, user),
        "message": "Redacted failure output stored as an encrypted parser sample",
    }


@router.post("/devices/{device_id}/identify")
def api_identify_device(device_id: str, payload: PlatformIdentifyRequest, user=require_permission("platform", "view")):
    return {
        "success": True,
        "data": _call(identify_device, device_id, payload.observations, user, platform_code=payload.platform_code),
        "message": "",
    }


@router.post("/devices/{device_id}/binding")
def api_bind_device(device_id: str, payload: PlatformBindingRequest, user=require_permission("platform", "bind_device")):
    _require_registry_enabled()
    return {
        "success": True,
        "data": _call(
            bind_device,
            device_id,
            payload.platform_profile_id,
            user,
            lock=payload.lock,
            force=payload.force,
        ),
        "message": "Device platform binding saved",
    }


@router.post("/devices/{device_id}/identify-live")
def api_identify_device_live(device_id: str, user=require_permission("platform", "view")):
    _require_registry_enabled()
    return {"success": True, "data": _call(identify_device_live, device_id, user), "message": ""}


@device_registry_router.post("/devices/{device_id}/platform-detect")
def api_device_platform_detect(
    device_id: str,
    payload: PlatformDetectRequest = PlatformDetectRequest(),
    user=require_permission("platform", "view"),
):
    _require_registry_enabled()
    if payload.observations:
        data = _call(identify_device, device_id, payload.observations, user, platform_code=payload.platform_code)
    else:
        data = _call(identify_device_live, device_id, user)
    return {"success": True, "data": data, "message": ""}


@device_registry_router.put("/devices/{device_id}/platform-binding")
def api_device_platform_binding(
    device_id: str,
    payload: PlatformBindingRequest,
    user=require_permission("platform", "bind_device"),
):
    _require_registry_enabled()
    return {
        "success": True,
        "data": _call(
            bind_device,
            device_id,
            payload.platform_profile_id,
            user,
            lock=payload.lock,
            force=payload.force,
        ),
        "message": "Device platform binding saved",
    }
