"""Telemetry management API backed by the PostgreSQL control plane."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core.rbac import require_role
from schemas.telemetry import (
    TelemetryDeviceConfigUpsert,
    TelemetrySubscriptionCreate,
    TelemetrySubscriptionTemplateCreate,
    TelemetrySubscriptionTemplateDraftUpdate,
    TelemetryTLSProfileInput,
)
from services import telemetry_config_service as service

router = APIRouter(prefix="/monitoring/telemetry", tags=["telemetry"])
logger = logging.getLogger("api.telemetry")


class ReceiverStatusItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription_id: str = Field(min_length=1, max_length=160)
    last_received_at: str | None = None
    last_valid_at: str | None = None
    active_series: int = Field(default=0, ge=0)
    sample_rate: float = Field(default=0, ge=0)
    dropped_samples: int = Field(default=0, ge=0)
    clock_skew_ms: int | None = None
    error_code: str = Field(default="", max_length=120)
    connection_state: str = Field(default="CONNECTED", max_length=32)
    data_state: str = Field(default="NO_DATA", max_length=32)


class ReceiverStatusBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collector_id: str = Field(min_length=1, max_length=160)
    items: list[ReceiverStatusItem] = Field(default_factory=list, max_length=500)


def _raise_service_error(exc: service.TelemetryServiceError) -> None:
    raise HTTPException(status_code=exc.status_code,
                        detail={"code": exc.code, "message": exc.message}) from exc


@router.get("/profiles")
def telemetry_profiles(_user=require_role("Viewer")):
    try:
        return service.list_profiles()
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.get("/collectors")
def telemetry_collectors(_user=require_role("Viewer")):
    try:
        return service.list_telemetry_collectors(_user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.post("/collectors/{collector_id}/endpoint/validate")
def validate_telemetry_collector_endpoint(collector_id: str, _user=require_role("Operator")):
    """Validate the environment-backed endpoint; API requests never edit .env."""
    try:
        return service.validate_collector_endpoint(collector_id, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.get("/templates")
def telemetry_templates(page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100),
                        _user=require_role("Viewer")):
    try:
        return service.list_templates(_user, page, page_size)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.post("/templates", status_code=201)
def create_telemetry_template(body: TelemetrySubscriptionTemplateCreate, _user=require_role("Operator")):
    try:
        return service.create_template(body, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.get("/templates/{template_id}")
def get_telemetry_template(template_id: str, _user=require_role("Viewer")):
    try:
        return service.get_template(template_id, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.patch("/templates/{template_id}")
def update_telemetry_template(template_id: str, body: TelemetrySubscriptionTemplateDraftUpdate,
                              _user=require_role("Operator")):
    try:
        return service.update_template_draft(template_id, body, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.post("/templates/{template_id}/publish")
def publish_telemetry_template(template_id: str, _user=require_role("Operator")):
    try:
        return service.publish_template(template_id, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.get("/tls-profiles")
def telemetry_tls_profiles(_user=require_role("Viewer")):
    try:
        return service.list_tls_profiles(_user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.post("/tls-profiles", status_code=201)
def create_telemetry_tls_profile(body: TelemetryTLSProfileInput, _user=require_role("Operator")):
    try:
        return service.create_tls_profile(body, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.get("/devices/{device_id}/config")
def get_telemetry_device_config(device_id: str, _user=require_role("Viewer")):
    try:
        return service.get_device_config(device_id, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.put("/devices/{device_id}/config")
def upsert_telemetry_device_config(device_id: str, body: TelemetryDeviceConfigUpsert,
                                   background_tasks: BackgroundTasks,
                                   _user=require_role("Operator")):
    try:
        result = service.upsert_device_config(device_id, body, _user)
        publish_job = result.get("publish_job")
        if publish_job and publish_job.get("job_id"):
            background_tasks.add_task(_run_publish_job, publish_job["job_id"])
        return result
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.post("/devices/{device_id}/validate")
def validate_telemetry_device_config(device_id: str, body: TelemetryDeviceConfigUpsert,
                                     _user=require_role("Operator")):
    try:
        return service.validate_device_config(device_id, body, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.post("/devices/{device_id}/subscriptions", status_code=201)
def create_telemetry_subscription(device_id: str, body: TelemetrySubscriptionCreate,
                                  _user=require_role("Operator")):
    try:
        return service.create_subscription(device_id, body, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.get("/subscriptions")
def telemetry_subscriptions(page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
                            _user=require_role("Viewer")):
    try:
        return service.list_subscriptions(_user, page, page_size)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.get("/subscriptions/{subscription_id}/status")
def telemetry_subscription_status(subscription_id: str, _user=require_role("Viewer")):
    try:
        item = service._subscription_by_id(subscription_id, _user)
        return item.get("runtime") or {}
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


def _run_publish_job(job_id: str) -> None:
    try:
        service.process_publish_job(job_id)
    except Exception:
        # No device payload or credential data is included in this log.
        logger.exception("Telemetry config publish failed job_id=%s", job_id)


def _queue_subscription_action(subscription_id: str, enabled: bool,
                               background_tasks: BackgroundTasks, user: dict[str, Any]) -> dict[str, Any]:
    result = service.set_subscription_enabled(subscription_id, enabled, user)
    background_tasks.add_task(_run_publish_job, result["job_id"])
    return result


@router.post("/subscriptions/{subscription_id}/enable", status_code=202)
def enable_telemetry_subscription(subscription_id: str, background_tasks: BackgroundTasks,
                                  _user=require_role("Operator")):
    try:
        return _queue_subscription_action(subscription_id, True, background_tasks, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.post("/subscriptions/{subscription_id}/disable", status_code=202)
def disable_telemetry_subscription(subscription_id: str, background_tasks: BackgroundTasks,
                                   _user=require_role("Operator")):
    try:
        return _queue_subscription_action(subscription_id, False, background_tasks, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.post("/subscriptions/{subscription_id}/retry", status_code=202)
def retry_telemetry_subscription(subscription_id: str, background_tasks: BackgroundTasks,
                                 _user=require_role("Operator")):
    try:
        result = service.retry_subscription(subscription_id, _user)
        background_tasks.add_task(_run_publish_job, result["job_id"])
        return result
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.delete("/subscriptions/{subscription_id}", status_code=202)
def delete_telemetry_subscription(subscription_id: str, background_tasks: BackgroundTasks,
                                  _user=require_role("Operator")):
    try:
        result = service.delete_subscription(subscription_id, _user)
        background_tasks.add_task(_run_publish_job, result["job_id"])
        return result
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.get("/collectors/{collector_id}/capacity")
def telemetry_collector_capacity(collector_id: str, _user=require_role("Viewer")):
    try:
        return service.collector_capacity(collector_id, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.get("/jobs/{job_id}")
def telemetry_job(job_id: str, _user=require_role("Viewer")):
    try:
        return service.get_job(job_id, _user)
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)


@router.post("/internal/status")
def telemetry_receiver_status(body: ReceiverStatusBatch, x_telemetry_token: str = Header(default="")):
    if not service.validate_receiver_status_token(x_telemetry_token):
        raise HTTPException(status_code=401, detail={"code": "TELEMETRY_STATUS_UNAUTHORIZED", "message": "Receiver status authentication failed"})
    try:
        return service.record_receiver_status(body.collector_id, [item.model_dump(mode="json") for item in body.items])
    except service.TelemetryServiceError as exc:
        _raise_service_error(exc)
