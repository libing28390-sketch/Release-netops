"""CRUD, preview and execution endpoints for configuration-backup policies."""

from __future__ import annotations

import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core.rbac import require_role
from database import get_db_connection
from services.audit_service import log_audit_event
from services import config_backup_policy_service as policy_service
from services.file_transfer_service import SUPPORTED_TRANSFER_PROTOCOLS


router = APIRouter(prefix="/configs/backup-policies", tags=["config-backup-policies"])


class BackupScope(BaseModel):
    site_ids: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    vendors: list[str] = Field(default_factory=list)
    device_ids: list[str] = Field(default_factory=list)
    exclude_device_ids: list[str] = Field(default_factory=list)
    tag_expression: dict | None = None


class BackupPolicyPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    enabled: bool = True
    cron_expr: str = "0 2 * * *"
    timezone: str = "Asia/Shanghai"
    priority: int = Field(default=100, ge=1, le=1000)
    scope: BackupScope = Field(default_factory=BackupScope)
    config_types: list[str] = Field(default_factory=lambda: ["running"])
    change_only: bool = True
    retention_days: int = Field(default=90, ge=1, le=3650)
    max_versions_per_device: int = Field(default=30, ge=1, le=5000)
    concurrency: int = Field(default=10, ge=1, le=50)
    retry_count: int = Field(default=1, ge=0, le=5)
    timeout_seconds: int = Field(default=30, ge=5, le=300)
    collect_startup_config: bool = False
    tftp_enabled: bool = False
    tftp_server: str = ""
    tftp_port: int = Field(default=69, ge=1, le=65535)
    tftp_path_prefix: str = Field(default="backups", max_length=200)
    # Kept under the legacy tftp_* API names for backward compatibility.  The
    # UI presents this as generic remote file archive, not as TFTP-only.
    tftp_protocol: str = "tftp"
    tftp_username: str = Field(default="", max_length=200)
    tftp_password: str = Field(default="", max_length=500)

    @field_validator("cron_expr")
    @classmethod
    def validate_cron(cls, value: str) -> str:
        value = value.strip()
        if not croniter.is_valid(value):
            raise ValueError("Invalid cron expression")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        value = value.strip()
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Invalid IANA timezone") from exc
        return value

    @field_validator("config_types")
    @classmethod
    def validate_config_types(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(str(item).strip().lower() for item in value if str(item).strip()))
        unsupported = set(normalized).difference({"running", "startup"})
        if unsupported or not normalized:
            raise ValueError("Supported configuration types are 'running' and 'startup'")
        return normalized

    @field_validator("tftp_protocol")
    @classmethod
    def validate_tftp_protocol(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in SUPPORTED_TRANSFER_PROTOCOLS:
            raise ValueError(f"Supported archive protocols are: {', '.join(SUPPORTED_TRANSFER_PROTOCOLS)}")
        return normalized


class BackupPolicyPatch(BackupPolicyPayload):
    pass


def _refresh_scheduler() -> None:
    from api.configs import reschedule_backup_policies
    reschedule_backup_policies()


@router.get("")
def list_backup_policies(
    search: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        return {"success": True, "data": policy_service.list_policies(
            conn, search=search, page=page, page_size=page_size,
        )}
    finally:
        conn.close()


@router.post("/preview")
def preview_unsaved_policy(
    payload: BackupPolicyPayload,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default=""),
    _user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        policy = payload.model_dump()
        return {"success": True, "data": policy_service.preview_policy(
            conn, policy, search=search, page=page, page_size=page_size,
        )}
    finally:
        conn.close()


@router.post("")
def create_backup_policy(
    payload: BackupPolicyPayload,
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        try:
            policy = policy_service.create_policy(
                conn,
                payload.model_dump(),
                actor=user.get("username", ""),
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(status_code=409, detail="备份策略名称已存在") from exc
            raise
        log_audit_event(
            conn=conn,
            event_type="CONFIG_BACKUP_POLICY_CREATE",
            category="configuration",
            severity="medium",
            status="success",
            summary=f"Created backup policy {policy['name']}",
            actor_username=user.get("username", ""),
            actor_role=user.get("role", ""),
            target_type="config_backup_policy",
            target_id=policy["id"],
            details={"cron_expr": policy["cron_expr"], "scope": policy["scope"]},
        )
        _refresh_scheduler()
        return {"success": True, "data": policy}
    finally:
        conn.close()


@router.get("/{policy_id}")
def get_backup_policy(policy_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        policy = policy_service.get_policy(conn, policy_id)
        if not policy:
            raise HTTPException(status_code=404, detail="Backup policy not found")
        return {"success": True, "data": policy}
    finally:
        conn.close()


@router.get("/{policy_id}/preview")
def preview_saved_policy(
    policy_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default=""),
    _user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        policy = policy_service.get_policy(conn, policy_id)
        if not policy:
            raise HTTPException(status_code=404, detail="Backup policy not found")
        return {"success": True, "data": policy_service.preview_policy(
            conn, policy, search=search, page=page, page_size=page_size,
        )}
    finally:
        conn.close()


@router.put("/{policy_id}")
def update_backup_policy(
    policy_id: str,
    payload: BackupPolicyPatch,
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        policy = policy_service.update_policy(
            conn,
            policy_id,
            payload.model_dump(),
            actor=user.get("username", ""),
        )
        if not policy:
            raise HTTPException(status_code=404, detail="Backup policy not found")
        log_audit_event(
            conn=conn,
            event_type="CONFIG_BACKUP_POLICY_UPDATE",
            category="configuration",
            severity="medium",
            status="success",
            summary=f"Updated backup policy {policy['name']}",
            actor_username=user.get("username", ""),
            actor_role=user.get("role", ""),
            target_type="config_backup_policy",
            target_id=policy_id,
            details={"cron_expr": policy["cron_expr"], "scope": policy["scope"]},
        )
        _refresh_scheduler()
        return {"success": True, "data": policy}
    finally:
        conn.close()


@router.delete("/{policy_id}")
def delete_backup_policy(
    policy_id: str,
    user=require_role("Administrator"),
):
    conn = get_db_connection()
    try:
        try:
            deleted = policy_service.delete_policy(conn, policy_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Backup policy not found")
        log_audit_event(
            conn=conn,
            event_type="CONFIG_BACKUP_POLICY_DELETE",
            category="configuration",
            severity="warning",
            status="success",
            summary=f"Deleted backup policy {policy_id}",
            actor_username=user.get("username", ""),
            actor_role=user.get("role", ""),
            target_type="config_backup_policy",
            target_id=policy_id,
        )
        _refresh_scheduler()
        return {"success": True}
    finally:
        conn.close()


@router.post("/{policy_id}/run")
async def run_backup_policy_now(
    policy_id: str,
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        if not policy_service.get_policy(conn, policy_id):
            raise HTTPException(status_code=404, detail="Backup policy not found")
    finally:
        conn.close()
    import asyncio
    from api.configs import run_scheduled_backup
    run_id = uuid.uuid4().hex
    asyncio.create_task(
        run_scheduled_backup(
            run_id=run_id,
            policy_id=policy_id,
            author=user.get("username", "operator"),
        )
    )
    return {"success": True, "data": {"run_id": run_id, "status": "started"}}
