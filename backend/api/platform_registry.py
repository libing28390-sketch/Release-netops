"""P0 platform registry API.

HTTP handlers only validate authorization/status; release and execution rules
live in ``services.platform_registry_service`` so background consumers can use
the same boundary.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from fastapi import APIRouter, HTTPException, Path, Query

from core.rbac import require_permission
from services.platform_registry_service import (
    ALLOWED_CONNECTION_DRIVERS,
    PlatformRegistryError,
    create_profile,
    create_release,
    delete_release,
    execute_platform_action,
    get_profile,
    list_compatible_parser_versions,
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
    bind_devices_batch,
    identify_device,
    identify_device_live,
    list_identification_conflicts,
)
from services.platform_registry_health_service import create_sample_from_failed_run, get_profile_health

router = APIRouter(prefix="/platform-registry", tags=["platform-registry"])
logger = logging.getLogger(__name__)


class _PlatformRequestModel(BaseModel):
    """Keep registry write contracts explicit and reject silent typos."""

    model_config = ConfigDict(extra="forbid")


def _validate_observations(value: dict[str, str]) -> dict[str, str]:
    if len(value) > 16:
        raise ValueError("observations must contain at most 16 command outputs")
    for command, output in value.items():
        if len(str(command)) > 128:
            raise ValueError("observation command is too long")
        if len(str(output)) > 2_000_000:
            raise ValueError("observation output is too large")
    return value


class PlatformProfileCreateRequest(_PlatformRequestModel):
    platform_code: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-z][a-z0-9_]{2,63}$")
    name_zh: str = Field(default="", max_length=128)
    name_en: str = Field(default="", max_length=128)
    vendor: str = Field(default="", max_length=128)
    connection_driver: str = Field(..., min_length=1, max_length=64)
    parser_platform: str = Field(..., min_length=1, max_length=64)
    description: str = Field(default="", max_length=2_000)
    tenant_id: str | None = Field(default=None, max_length=128)


class PlatformReleaseCreateRequest(_PlatformRequestModel):
    safety_policy: dict[str, Any] = Field(default_factory=lambda: {"read_only": True})


class PlatformReleaseReviewRequest(_PlatformRequestModel):
    reason: str = Field(default="", max_length=2_000)


class PlatformActionUpdateRequest(_PlatformRequestModel):
    command: str = Field(..., min_length=1, max_length=512)
    parser_template_version_id: str | None = Field(default=None, max_length=128)
    field_contract: dict[str, Any] = Field(default_factory=dict)


class PlatformRollbackRequest(_PlatformRequestModel):
    release_id: str | None = Field(default=None, max_length=128)


class PlatformActionRequest(_PlatformRequestModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    action_code: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-z][a-z0-9_]{2,63}$")
    parameters: dict[str, Any] = Field(default_factory=dict)


class PlatformFailureSampleRequest(_PlatformRequestModel):
    sample_name: str = Field(default="", max_length=128)
    expected_records: list[Any] = Field(default_factory=list, max_length=10_000)


class PlatformIdentifyRequest(BaseModel):
    observations: dict[str, str] = Field(..., min_length=1)
    platform_code: str = Field(default="", max_length=64)

    model_config = ConfigDict(extra="forbid")

    _observations_limit = field_validator("observations")(_validate_observations)


class PlatformBindingRequest(BaseModel):
    platform_profile_id: str = Field(..., min_length=1, max_length=128)
    lock: bool = False
    force: bool = False

    model_config = ConfigDict(extra="forbid")


class PlatformBatchBindingRequest(BaseModel):
    device_ids: list[str] = Field(..., min_length=1, max_length=200)
    platform_profile_id: str = Field(..., min_length=1, max_length=128)
    lock: bool = False
    force: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator("device_ids")
    @classmethod
    def validate_device_ids(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("device_ids must contain non-empty values")
        if len(set(normalized)) != len(normalized):
            raise ValueError("device_ids must not contain duplicates")
        return normalized


class PlatformDetectRequest(BaseModel):
    observations: dict[str, str] = Field(default_factory=dict)
    platform_code: str = Field(default="", max_length=64)

    model_config = ConfigDict(extra="forbid")

    _observations_limit = field_validator("observations")(_validate_observations)


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


@router.get("/capabilities")
def api_registry_capabilities(user=require_permission("platform", "read")):
    enabled = os.environ.get("PLATFORM_REGISTRY_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "success": True,
        "data": {
            "write_enabled": enabled,
            "allowed_connection_drivers": sorted(ALLOWED_CONNECTION_DRIVERS),
            "legacy_textfsm_fallback_enabled": os.environ.get("LEGACY_TEXTFSM_FILE_FALLBACK_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"},
            "legacy_command_catalog_enabled": os.environ.get("LEGACY_COMMAND_CATALOG_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"},
        },
        "message": "",
    }


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
def api_create_profile(payload: PlatformProfileCreateRequest, user=require_permission("platform", "create")):
    _require_registry_enabled()
    return {"success": True, "data": _call(create_profile, payload.model_dump(exclude_none=True), user), "message": "Platform profile created"}


@router.get("/profiles/{profile_id}")
def api_get_profile(profile_id: str = Path(..., min_length=1), user=require_permission("platform", "read")):
    return {"success": True, "data": _call(get_profile, profile_id, user), "message": ""}


@router.get("/profiles/{profile_id}/parser-versions")
def api_list_compatible_parser_versions(
    profile_id: str = Path(..., min_length=1),
    user=require_permission("command", "view"),
):
    """Return only published parser versions accepted by this profile."""
    return {
        "success": True,
        "data": _call(list_compatible_parser_versions, profile_id, user),
        "message": "",
    }


@router.post("/profiles/{profile_id}/releases")
def api_create_release(profile_id: str, payload: PlatformReleaseCreateRequest | None = None, user=require_permission("platform", "edit_draft")):
    _require_registry_enabled()
    return {"success": True, "data": _call(create_release, profile_id, (payload or PlatformReleaseCreateRequest()).model_dump(), user), "message": "Draft release created"}


@router.get("/profiles/{profile_id}/actions")
def api_list_actions(
    profile_id: str,
    release_id: str | None = Query(default=None, min_length=1, max_length=128),
    user=require_permission("command", "view"),
):
    return {"success": True, "data": _call(list_release_actions, profile_id, user, release_id), "message": ""}


@router.delete("/releases/{release_id}")
def api_delete_release(release_id: str, user=require_permission("platform", "edit_draft")):
    _require_registry_enabled()
    return {"success": True, "data": _call(delete_release, release_id, user), "message": "Draft release deleted"}


@router.put("/releases/{release_id}/actions/{action_code}")
def api_update_action(release_id: str, action_code: str, payload: PlatformActionUpdateRequest, user=require_permission("command", "edit_draft")):
    _require_registry_enabled()
    return {"success": True, "data": _call(update_release_action, release_id, action_code, payload.model_dump(exclude_none=True), user), "message": "Action mapping saved"}


@router.post("/releases/{release_id}/validate")
def api_validate_release(release_id: str, user=require_permission("platform", "edit_draft")):
    _require_registry_enabled()
    return {"success": True, "data": _call(validate_release, release_id, user), "message": ""}


@router.post("/releases/{release_id}/submit")
def api_submit_release(release_id: str, user=require_permission("platform", "submit")):
    _require_registry_enabled()
    return {"success": True, "data": _call(transition_release, release_id, "submit", user), "message": "Release submitted"}


@router.post("/releases/{release_id}/withdraw")
def api_withdraw_release(release_id: str, user=require_permission("platform", "submit")):
    """Let the original submitter return an in-review release to draft."""
    _require_registry_enabled()
    return {"success": True, "data": _call(transition_release, release_id, "withdraw", user), "message": "Release withdrawn"}


@router.post("/releases/{release_id}/approve")
def api_approve_release(release_id: str, user=require_permission("platform", "approve")):
    _require_registry_enabled()
    return {"success": True, "data": _call(transition_release, release_id, "approve", user), "message": "Release approved"}


@router.post("/releases/{release_id}/reject")
def api_reject_release(
    release_id: str,
    payload: PlatformReleaseReviewRequest | None = None,
    user=require_permission("platform", "approve"),
):
    _require_registry_enabled()
    return {
        "success": True,
        "data": _call(
            transition_release,
            release_id,
            "reject",
            user,
            reason=(payload.reason if payload else ""),
        ),
        "message": "Release rejected",
    }


@router.post("/releases/{release_id}/publish")
def api_publish_release(release_id: str, user=require_permission("platform", "publish")):
    _require_registry_enabled()
    return {"success": True, "data": _call(transition_release, release_id, "publish", user), "message": "Release published"}


@router.post("/profiles/{profile_id}/rollback")
def api_rollback_profile(profile_id: str, payload: PlatformRollbackRequest | None = None, user=require_permission("platform", "rollback")):
    _require_registry_enabled()
    return {"success": True, "data": _call(rollback_profile, profile_id, payload.release_id if payload else None, user), "message": "Platform rolled back"}


@router.post("/actions/execute")
def api_execute_action(payload: PlatformActionRequest, user=require_permission("command", "execute")):
    _require_registry_enabled()
    return {"success": True, "data": _call(execute_platform_action, payload.device_id.strip(), payload.action_code.strip(), user=user, parameters=payload.parameters), "message": ""}


@router.post("/actions/preview")
def api_preview_action(payload: PlatformActionRequest, user=require_permission("command", "execute")):
    """Resolve a published action and parameters without opening a device connection."""
    _require_registry_enabled()
    return {"success": True, "data": _call(preview_platform_action, payload.device_id.strip(), payload.action_code.strip(), user=user, parameters=payload.parameters), "message": ""}


@router.post("/runs/{run_id}/parser-sample")
def api_create_sample_from_failed_run(
    run_id: str = Path(..., min_length=1),
    payload: PlatformFailureSampleRequest | None = None,
    user=require_permission("sample_output", "upload"),
):
    _require_registry_enabled()
    return {
        "success": True,
        "data": _call(create_sample_from_failed_run, run_id, (payload or PlatformFailureSampleRequest()).model_dump(), user),
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
    payload: PlatformDetectRequest | None = None,
    user=require_permission("platform", "view"),
):
    _require_registry_enabled()
    request = payload or PlatformDetectRequest()
    if request.observations:
        data = _call(identify_device, device_id, request.observations, user, platform_code=request.platform_code)
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


@device_registry_router.post("/devices/platform-binding/batch")
def api_device_platform_binding_batch(
    payload: PlatformBatchBindingRequest,
    user=require_permission("platform", "bind_device"),
):
    _require_registry_enabled()
    return {
        "success": True,
        "data": _call(
            bind_devices_batch,
            payload.device_ids,
            payload.platform_profile_id,
            user,
            lock=payload.lock,
            force=payload.force,
        ),
        "message": "Batch device platform binding saved",
    }
