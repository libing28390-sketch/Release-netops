"""P0 platform registry API.

HTTP handlers only validate authorization/status; release and execution rules
live in ``services.platform_registry_service`` so background consumers can use
the same boundary.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException, Path

from core.rbac import require_permission
from services.platform_registry_service import (
    PlatformRegistryError,
    create_profile,
    create_release,
    execute_platform_action,
    get_profile,
    list_profiles,
    list_release_actions,
    rollback_profile,
    transition_release,
    update_release_action,
    validate_release,
)

router = APIRouter(prefix="/platform-registry", tags=["platform-registry"])
logger = logging.getLogger(__name__)


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


@router.get("/profiles")
def api_list_profiles(user=require_permission("platform", "read")):
    return {"success": True, "data": _call(list_profiles, user), "message": ""}


@router.post("/profiles")
def api_create_profile(payload: dict = Body(...), user=require_permission("platform", "create")):
    return {"success": True, "data": _call(create_profile, payload, user), "message": "Platform profile created"}


@router.get("/profiles/{profile_id}")
def api_get_profile(profile_id: str = Path(..., min_length=1), user=require_permission("platform", "read")):
    return {"success": True, "data": _call(get_profile, profile_id, user), "message": ""}


@router.post("/profiles/{profile_id}/releases")
def api_create_release(profile_id: str, payload: dict = Body(default={}), user=require_permission("platform", "edit_draft")):
    return {"success": True, "data": _call(create_release, profile_id, payload, user), "message": "Draft release created"}


@router.get("/profiles/{profile_id}/actions")
def api_list_actions(profile_id: str, user=require_permission("command", "view")):
    return {"success": True, "data": _call(list_release_actions, profile_id, user), "message": ""}


@router.put("/releases/{release_id}/actions/{action_code}")
def api_update_action(release_id: str, action_code: str, payload: dict = Body(...), user=require_permission("command", "edit_draft")):
    return {"success": True, "data": _call(update_release_action, release_id, action_code, payload, user), "message": "Action mapping saved"}


@router.post("/releases/{release_id}/validate")
def api_validate_release(release_id: str, user=require_permission("platform", "edit_draft")):
    return {"success": True, "data": _call(validate_release, release_id, user), "message": ""}


@router.post("/releases/{release_id}/submit")
def api_submit_release(release_id: str, user=require_permission("platform", "submit")):
    return {"success": True, "data": _call(transition_release, release_id, "submit", user), "message": "Release submitted"}


@router.post("/releases/{release_id}/approve")
def api_approve_release(release_id: str, user=require_permission("platform", "approve")):
    return {"success": True, "data": _call(transition_release, release_id, "approve", user), "message": "Release approved"}


@router.post("/releases/{release_id}/publish")
def api_publish_release(release_id: str, user=require_permission("platform", "publish")):
    return {"success": True, "data": _call(transition_release, release_id, "publish", user), "message": "Release published"}


@router.post("/profiles/{profile_id}/rollback")
def api_rollback_profile(profile_id: str, payload: dict = Body(default={}), user=require_permission("platform", "rollback")):
    return {"success": True, "data": _call(rollback_profile, profile_id, payload.get("release_id"), user), "message": "Platform rolled back"}


@router.post("/actions/execute")
def api_execute_action(payload: dict = Body(...), user=require_permission("command", "execute")):
    device_id = str(payload.get("device_id") or "").strip()
    action_code = str(payload.get("action_code") or "").strip()
    if not device_id or not action_code:
        raise HTTPException(status_code=400, detail={"code": "INVALID_ACTION_REQUEST", "message": "device_id and action_code are required"})
    return {"success": True, "data": _call(execute_platform_action, device_id, action_code, user=user), "message": ""}
