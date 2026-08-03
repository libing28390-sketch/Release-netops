"""P1 tenant-scoped TextFSM registry development API."""

from __future__ import annotations

import os
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.rbac import require_permission
from services.parser_template_service import (
    create_template,
    create_version,
    approve_version,
    create_sample,
    list_templates,
    list_samples,
    list_versions,
    fork_template,
    publish_version,
    regression_test_template,
    submit_version,
    test_version,
)
from services.platform_registry_service import PlatformRegistryError


router = APIRouter(prefix="/parser-templates", tags=["parser-templates"])
logger = logging.getLogger(__name__)


class ParserTemplateCreateRequest(BaseModel):
    platform_code: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-z][a-z0-9_]{2,63}$")
    template_code: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    name: str = Field(default="", max_length=128)
    source_filename: str = Field(default="", max_length=255)
    platform_profile_id: str | None = Field(default=None, max_length=128)


class ParserTemplateForkRequest(BaseModel):
    template_code: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    name: str = Field(default="", max_length=128)
    source_filename: str = Field(default="", max_length=255)
    platform_profile_id: str | None = Field(default=None, max_length=128)


class ParserVersionCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=256_000)
    field_contract: dict[str, Any] = Field(default_factory=dict)


class ParserVersionTestRequest(BaseModel):
    sample_output: str = Field(..., min_length=1, max_length=2_000_000)


class ParserSampleCreateRequest(BaseModel):
    sample_output: str = Field(..., min_length=1, max_length=2_000_000)
    sample_name: str = Field(default="", max_length=128)
    expected_records: list[Any] = Field(default_factory=list)


class ParserRegressionTestRequest(BaseModel):
    version_id: str | None = Field(default=None, max_length=128)


def _enabled() -> None:
    if os.environ.get("PLATFORM_REGISTRY_ENABLED", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "PLATFORM_REGISTRY_DISABLED",
                "message": "Parser template development APIs are disabled",
            },
        )


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except PlatformRegistryError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    except Exception as exc:
        logger.exception("Parser template API operation failed")
        raise HTTPException(status_code=500, detail={"code": "PARSER_TEMPLATE_ERROR", "message": "Parser template operation failed"}) from exc


@router.get("")
def api_list_templates(
    platform_code: str = Query("", max_length=64),
    user=require_permission("textfsm", "view"),
):
    return {"success": True, "data": _call(list_templates, user, platform_code=platform_code), "message": ""}


@router.post("", status_code=201)
def api_create_template(payload: ParserTemplateCreateRequest, user=require_permission("textfsm", "create")):
    _enabled()
    return {"success": True, "data": _call(create_template, payload.model_dump(), user), "message": "Parser template created"}


@router.get("/{template_id}/versions")
def api_list_versions(template_id: str, user=require_permission("textfsm", "view")):
    return {"success": True, "data": _call(list_versions, template_id, user), "message": ""}


@router.post("/{template_id}/fork", status_code=201)
def api_fork_template(template_id: str, payload: ParserTemplateForkRequest, user=require_permission("textfsm", "create")):
    _enabled()
    return {"success": True, "data": _call(fork_template, template_id, payload.model_dump(), user), "message": "SYSTEM parser template forked"}


@router.post("/{template_id}/versions", status_code=201)
def api_create_version(template_id: str, payload: ParserVersionCreateRequest, user=require_permission("textfsm", "edit_draft")):
    _enabled()
    return {"success": True, "data": _call(create_version, template_id, payload.model_dump(), user), "message": "Parser template draft created"}


@router.post("/versions/{version_id}/test")
def api_test_version(version_id: str, payload: ParserVersionTestRequest, user=require_permission("textfsm", "test")):
    _enabled()
    return {"success": True, "data": _call(test_version, version_id, payload.model_dump(), user), "message": "Parser template tested"}


@router.post("/versions/{version_id}/submit")
def api_submit_version(version_id: str, user=require_permission("textfsm", "submit")):
    _enabled()
    return {"success": True, "data": _call(submit_version, version_id, user), "message": "Parser template submitted"}


@router.post("/versions/{version_id}/approve")
def api_approve_version(version_id: str, user=require_permission("textfsm", "approve")):
    _enabled()
    return {"success": True, "data": _call(approve_version, version_id, user), "message": "Parser template approved"}


@router.post("/versions/{version_id}/publish")
def api_publish_version(version_id: str, user=require_permission("textfsm", "publish")):
    _enabled()
    return {"success": True, "data": _call(publish_version, version_id, user), "message": "Parser template published"}


@router.post("/versions/{version_id}/samples", status_code=201)
def api_create_sample(version_id: str, payload: ParserSampleCreateRequest, user=require_permission("sample_output", "upload")):
    _enabled()
    return {"success": True, "data": _call(create_sample, version_id, payload.model_dump(), user), "message": "Parser test sample stored"}


@router.get("/versions/{version_id}/samples")
def api_list_samples(version_id: str, user=require_permission("sample_output", "view")):
    return {"success": True, "data": _call(list_samples, version_id, user), "message": ""}


@router.post("/{template_id}/regression-test")
def api_regression_test(
    template_id: str,
    payload: ParserRegressionTestRequest = ParserRegressionTestRequest(),
    user=require_permission("textfsm", "test"),
):
    _enabled()
    return {
        "success": True,
        "data": _call(regression_test_template, template_id, user, version_id=payload.version_id or ""),
        "message": "Parser regression test passed",
    }
