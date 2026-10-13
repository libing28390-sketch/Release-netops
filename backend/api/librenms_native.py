"""Administrator control plane and tenant-scoped bindings for native LibreNMS."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.crypto import decrypt_credential
from core.rbac import authorize_resource, require_role
from database import get_db_connection
from services.audit_service import log_audit_event
from services.librenms_runtime_client import (
    LibreNMSAPIError,
    LibreNMSRuntimeClient,
    normalize_librenms_base_url,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/librenms-native", tags=["librenms-native"])


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InstanceCreate(_StrictRequest):
    display_name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=512)
    token_credential_id: str = Field(min_length=1, max_length=128)
    enabled: bool = False

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display_name is required")
        return value

    @field_validator("token_credential_id")
    @classmethod
    def clean_credential_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("token_credential_id is required")
        return value


class InstanceUpdate(_StrictRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    token_credential_id: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None


class BindingUpsert(_StrictRequest):
    instance_id: str = Field(min_length=1, max_length=128)
    native_device_id: str = Field(min_length=1, max_length=128)
    native_hostname: str = Field(default="", max_length=255)
    collector_id: str = Field(default="", max_length=128)
    poller_group: str = Field(default="", max_length=128)
    desired_state: str = "enabled"

    @field_validator("desired_state")
    @classmethod
    def valid_state(cls, value: str) -> str:
        value = value.strip().casefold()
        if value not in {"enabled", "disabled"}:
            raise ValueError("desired_state must be enabled or disabled")
        return value


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_instance(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data.get("id"),
        "display_name": data.get("display_name"),
        "base_url": data.get("base_url"),
        "token_credential_id": data.get("token_credential_id"),
        "has_token": bool(data.get("has_token")),
        "engine_version": data.get("engine_version") or "",
        "engine_commit": data.get("engine_commit") or "",
        "enabled": bool(data.get("enabled")),
        "health_state": data.get("health_state") or "unknown",
        "health_checked_at": data.get("health_checked_at"),
        "health_error_code": data.get("health_error_code") or "",
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


def _require_api_token(conn, credential_id: str) -> dict[str, Any]:
    row = conn.execute(
        """SELECT id, credential_type, encrypted_password
             FROM credentials WHERE id = ? LIMIT 1""",
        (credential_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="LibreNMS API token credential not found")
    if str(row["credential_type"] or "").casefold() != "api_token":
        raise HTTPException(status_code=400, detail="Credential must use the API token type")
    if not str(row["encrypted_password"] or "").strip():
        raise HTTPException(status_code=400, detail="API token credential has no secret")
    return dict(row)


def _load_instance(conn, instance_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT i.*, (c.encrypted_password IS NOT NULL AND c.encrypted_password <> '') AS has_token
             FROM librenms_instances i
             LEFT JOIN credentials c ON c.id = i.token_credential_id
            WHERE i.id = ? LIMIT 1""",
        (instance_id,),
    ).fetchone()
    return dict(row) if row else None


def _instance_secret(instance: dict[str, Any]) -> str:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT c.credential_type, c.encrypted_password
                 FROM librenms_instances i
                 JOIN credentials c ON c.id = i.token_credential_id
                WHERE i.id = ? LIMIT 1""",
            (instance["id"],),
        ).fetchone()
        if not row or str(row["credential_type"] or "").casefold() != "api_token":
            raise HTTPException(status_code=409, detail="LibreNMS API token credential is unavailable")
        token = decrypt_credential(str(row["encrypted_password"] or "")) or ""
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("LibreNMS API token could not be decrypted: %s", type(exc).__name__)
        token = ""
    finally:
        conn.close()
    if not token:
        raise HTTPException(status_code=409, detail="LibreNMS API token credential is unavailable")
    return token


def _target_for_binding(conn, device_id: str, user: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute(
        """SELECT d.id, d.asset_id, d.tenant_id, d.site_id, d.hostname,
                  pa.site_id AS asset_site_id, s.tenant_id AS site_tenant_id
             FROM devices d
             LEFT JOIN physical_assets pa ON pa.id = d.asset_id
             LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
            WHERE d.id = ? LIMIT 1""",
        (device_id,),
    ).fetchone()
    if not row or not str(row["asset_id"] or "").strip():
        raise HTTPException(status_code=404, detail="Managed network device asset not found")
    target = dict(row)
    tenant_id = str(target.get("tenant_id") or target.get("site_tenant_id") or "tenant-default").strip()
    site_id = str(target.get("asset_site_id") or target.get("site_id") or "").strip()
    if str(user.get("role") or "") != "Administrator" and str(user.get("tenant_id") or "tenant-default") != tenant_id:
        raise HTTPException(status_code=404, detail="Managed network device asset not found")
    if not authorize_resource(user, "asset", "update", tenant_id=tenant_id, site_id=site_id or None):
        raise HTTPException(status_code=403, detail="Insufficient permission for this asset")
    target["tenant_id"] = tenant_id
    target["site_id"] = site_id
    return target


@router.get("/instances")
def list_instances(_user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT i.*, (c.encrypted_password IS NOT NULL AND c.encrypted_password <> '') AS has_token
                 FROM librenms_instances i
                 LEFT JOIN credentials c ON c.id = i.token_credential_id
                ORDER BY i.display_name, i.id"""
        ).fetchall()
        return {"success": True, "data": [_safe_instance(row) for row in rows]}
    finally:
        conn.close()


@router.post("/instances", status_code=201)
def create_instance(payload: InstanceCreate, _user=require_role("Administrator")):
    if payload.enabled:
        raise HTTPException(status_code=409, detail="Health-check the LibreNMS instance before enabling it")
    try:
        base_url = normalize_librenms_base_url(payload.base_url)
    except LibreNMSAPIError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": "LibreNMS base URL is not allowed"}) from exc
    instance_id = f"lnms-{uuid.uuid4().hex[:16]}"
    now = _now()
    conn = get_db_connection()
    try:
        _require_api_token(conn, payload.token_credential_id)
        conn.execute(
            """INSERT INTO librenms_instances
               (id, display_name, base_url, token_credential_id, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (instance_id, payload.display_name, base_url, payload.token_credential_id, False, now, now),
        )
        log_audit_event(
            event_type="librenms.instance.create", category="integration", severity="medium",
            status="success", summary=f"Created LibreNMS instance {payload.display_name}",
            actor_id=str(_user.get("id") or "") or None,
            actor_username=_user.get("username"), actor_role=_user.get("role"),
            target_type="librenms_instance", target_id=instance_id,
            details={"base_url": base_url, "token_credential_id": payload.token_credential_id,
                     "enabled": payload.enabled}, conn=conn,
        )
        conn.commit()
        row = _load_instance(conn, instance_id)
        return {"success": True, "data": _safe_instance(row)}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        logger.warning("LibreNMS instance creation failed: %s", type(exc).__name__)
        raise HTTPException(status_code=409, detail="LibreNMS instance could not be created") from exc
    finally:
        conn.close()


@router.patch("/instances/{instance_id}")
def update_instance(
    instance_id: str = Path(min_length=1, max_length=128),
    payload: InstanceUpdate = Body(...),
    _user=require_role("Administrator"),
):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No instance fields were supplied")
    if "display_name" in fields and fields["display_name"] is not None:
        fields["display_name"] = fields["display_name"].strip()
        if not fields["display_name"]:
            raise HTTPException(status_code=400, detail="display_name is required")
    if "base_url" in fields and fields["base_url"] is not None:
        try:
            fields["base_url"] = normalize_librenms_base_url(fields["base_url"])
        except LibreNMSAPIError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": "LibreNMS base URL is not allowed"}) from exc

    conn = get_db_connection()
    try:
        if not _load_instance(conn, instance_id):
            raise HTTPException(status_code=404, detail="LibreNMS instance not found")
        if fields.get("token_credential_id"):
            _require_api_token(conn, fields["token_credential_id"])
        current = _load_instance(conn, instance_id)
        connection_changed = "base_url" in fields or "token_credential_id" in fields
        if fields.get("enabled") is True and str(current.get("health_state") or "unknown") != "healthy":
            raise HTTPException(status_code=409, detail="Health-check the LibreNMS instance before enabling it")
        mutable_fields = {key: value for key, value in fields.items() if key != "enabled"}
        assignments = [f"{key} = ?" for key in mutable_fields]
        values = list(mutable_fields.values())
        assignments.extend([
            "updated_at = ?",
            "health_state = CASE WHEN ? THEN 'unknown' ELSE health_state END",
        ])
        values.extend([_now(), connection_changed])
        if "enabled" in fields:
            assignments.append("enabled = CASE WHEN ? THEN FALSE ELSE ? END")
            values.extend([connection_changed, fields["enabled"]])
        else:
            assignments.append("enabled = CASE WHEN ? THEN FALSE ELSE enabled END")
            values.append(connection_changed)
        values.append(instance_id)
        conn.execute(
            f"UPDATE librenms_instances SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
        log_audit_event(
            event_type="librenms.instance.update", category="integration", severity="medium",
            status="success", summary=f"Updated LibreNMS instance {instance_id}",
            actor_id=str(_user.get("id") or "") or None,
            actor_username=_user.get("username"), actor_role=_user.get("role"),
            target_type="librenms_instance", target_id=instance_id,
            details={"changed_fields": sorted(fields)}, conn=conn,
        )
        conn.commit()
        return {"success": True, "data": _safe_instance(_load_instance(conn, instance_id))}
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/instances/{instance_id}/health-check")
async def check_instance_health(
    instance_id: str = Path(min_length=1, max_length=128),
    _user=require_role("Administrator"),
):
    conn = get_db_connection()
    try:
        instance = _load_instance(conn, instance_id)
    finally:
        conn.close()
    if not instance:
        raise HTTPException(status_code=404, detail="LibreNMS instance not found")

    state, code, version, commit = "healthy", "", "", ""
    try:
        token = _instance_secret(instance)
        async with LibreNMSRuntimeClient(str(instance["base_url"]), token) as client:
            system = await client.get_system_info()
        version = str(system.get("local_ver") or "")
        commit = str(system.get("local_sha") or "")
    except HTTPException:
        state, code = "error", "credential_unavailable"
    except LibreNMSAPIError as exc:
        state, code = "unavailable", exc.code
    except Exception as exc:
        logger.warning("LibreNMS health check failed: %s", type(exc).__name__)
        state, code = "error", "unexpected_error"

    conn = get_db_connection()
    try:
        conn.execute(
            """UPDATE librenms_instances
                  SET health_state = ?, health_checked_at = ?, health_error_code = ?,
                      engine_version = ?, engine_commit = ?, updated_at = ?,
                      enabled = CASE WHEN ? = 'healthy' THEN enabled ELSE FALSE END
                WHERE id = ?""",
            (state, _now(), code, version, commit, _now(), state, instance_id),
        )
        conn.commit()
        updated = _load_instance(conn, instance_id)
    finally:
        conn.close()
    return {"success": state == "healthy", "data": _safe_instance(updated)}


@router.get("/instances/{instance_id}/devices")
async def list_native_devices(
    instance_id: str = Path(min_length=1, max_length=128),
    _user=require_role("Administrator"),
):
    conn = get_db_connection()
    try:
        instance = _load_instance(conn, instance_id)
    finally:
        conn.close()
    if not instance:
        raise HTTPException(status_code=404, detail="LibreNMS instance not found")
    try:
        token = _instance_secret(instance)
        async with LibreNMSRuntimeClient(str(instance["base_url"]), token) as client:
            devices = await client.get_devices()
    except HTTPException:
        raise
    except LibreNMSAPIError as exc:
        raise HTTPException(status_code=502, detail={"code": exc.code, "message": "Unable to list LibreNMS devices"}) from exc
    return {"success": True, "data": devices}


@router.put("/devices/{device_id}/binding")
async def upsert_device_binding(
    device_id: str = Path(min_length=1, max_length=128),
    payload: BindingUpsert = Body(...),
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        target = _target_for_binding(conn, device_id, user)
        instance = _load_instance(conn, payload.instance_id)
    finally:
        conn.close()
    if (
        not instance
        or not bool(instance.get("enabled"))
        or str(instance.get("health_state") or "unknown") != "healthy"
    ):
        raise HTTPException(status_code=409, detail="A healthy, enabled LibreNMS instance is required")

    try:
        token = _instance_secret(instance)
        async with LibreNMSRuntimeClient(str(instance["base_url"]), token) as client:
            native_device = await client.get_device(payload.native_device_id)
    except HTTPException:
        raise
    except LibreNMSAPIError as exc:
        status_code = 404 if exc.http_status == 404 else 502
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": "LibreNMS device could not be verified"}) from exc
    if not native_device:
        raise HTTPException(status_code=404, detail="LibreNMS device not found")
    returned_id = str(native_device.get("device_id") or "").strip()
    if returned_id and returned_id != payload.native_device_id:
        raise HTTPException(status_code=409, detail="LibreNMS returned a different native device ID")

    now = _now()
    binding_id = f"lnmb-{uuid.uuid4().hex[:16]}"
    native_hostname = payload.native_hostname.strip() or str(native_device.get("hostname") or "")
    sync_status = "pending" if payload.desired_state == "enabled" else "disabled"
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO librenms_device_bindings
               (id, tenant_id, asset_id, device_id, instance_id, librenms_device_id,
                librenms_hostname, collector_id, poller_group, desired_state, sync_status,
                last_sync_at, last_error_code, last_error_text, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '', '', ?, ?)
               ON CONFLICT (device_id) DO UPDATE SET
                 tenant_id = excluded.tenant_id,
                 asset_id = excluded.asset_id,
                 instance_id = excluded.instance_id,
                 librenms_device_id = excluded.librenms_device_id,
                 librenms_hostname = excluded.librenms_hostname,
                 collector_id = excluded.collector_id,
                 poller_group = excluded.poller_group,
                 desired_state = excluded.desired_state,
                 sync_status = excluded.sync_status,
                 last_sync_at = NULL,
                 last_discovery_at = NULL,
                 last_poll_at = NULL,
                 last_error_code = '',
                 last_error_text = '',
                 updated_at = excluded.updated_at""",
            (
                binding_id, target["tenant_id"], target["asset_id"], device_id,
                payload.instance_id, returned_id or payload.native_device_id,
                native_hostname, payload.collector_id.strip(), payload.poller_group.strip(),
                payload.desired_state, sync_status, now, now,
            ),
        )
        row = conn.execute(
            """SELECT id, tenant_id, asset_id, device_id, instance_id, librenms_device_id,
                      librenms_hostname, collector_id, poller_group, desired_state, sync_status,
                      last_sync_at, last_error_code, created_at, updated_at
                 FROM librenms_device_bindings WHERE device_id = ? LIMIT 1""",
            (device_id,),
        ).fetchone()
        log_audit_event(
            event_type="librenms.binding.upsert", category="integration", severity="medium",
            status="success", summary=f"Bound asset {target['asset_id']} to LibreNMS device {returned_id or payload.native_device_id}",
            actor_id=str(user.get("id") or "") or None,
            actor_username=user.get("username"), actor_role=user.get("role"),
            target_type="librenms_binding", target_id=str(row["id"]), device_id=device_id,
            details={"asset_id": target["asset_id"], "instance_id": payload.instance_id,
                     "native_device_id": returned_id or payload.native_device_id,
                     "desired_state": payload.desired_state}, conn=conn,
        )
        conn.commit()
        return {"success": True, "data": dict(row)}
    except Exception as exc:
        conn.rollback()
        if isinstance(exc, HTTPException):
            raise
        logger.warning("LibreNMS binding save failed: %s", type(exc).__name__)
        raise HTTPException(status_code=409, detail="LibreNMS device binding could not be saved") from exc
    finally:
        conn.close()


@router.delete("/devices/{device_id}/binding")
def disable_device_binding(device_id: str, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        _target_for_binding(conn, device_id, user)
        result = conn.execute(
            """UPDATE librenms_device_bindings
                  SET desired_state = 'disabled', sync_status = 'disabled', updated_at = ?
                WHERE device_id = ?""",
            (_now(), device_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="LibreNMS device binding not found")
        log_audit_event(
            event_type="librenms.binding.disable", category="integration", severity="medium",
            status="success", summary=f"Disabled LibreNMS binding for device {device_id}",
            actor_id=str(user.get("id") or "") or None,
            actor_username=user.get("username"), actor_role=user.get("role"),
            target_type="librenms_binding", target_id=device_id, device_id=device_id,
            details={"desired_state": "disabled"}, conn=conn,
        )
        conn.commit()
        return {"success": True, "data": {"device_id": device_id, "desired_state": "disabled"}}
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/bindings")
def list_bindings(user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        from services.rack_scope_service import allowed_resource_scope

        scope = allowed_resource_scope(conn, user, "asset", "view")
        where_parts: list[str] = []
        params: list[Any] = []
        if scope.tenant_id:
            where_parts.append("b.tenant_id = ?")
            params.append(scope.tenant_id)
        if scope.site_ids is not None:
            if not scope.site_ids:
                return {"success": True, "data": []}
            placeholders = ", ".join("?" for _ in scope.site_ids)
            where_parts.append(
                f"COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, '')) IN ({placeholders})"
            )
            params.extend(scope.site_ids)
        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        rows = conn.execute(
            f"""SELECT b.id, b.tenant_id, b.asset_id, b.device_id, b.instance_id,
                       b.librenms_device_id, b.librenms_hostname, b.collector_id,
                       b.poller_group, b.desired_state, b.sync_status, b.last_sync_at,
                       b.last_discovery_at, b.last_poll_at, b.last_error_code,
                       i.display_name AS instance_name, d.hostname
                  FROM librenms_device_bindings b
                  JOIN librenms_instances i ON i.id = b.instance_id
                  JOIN devices d ON d.id = b.device_id
                  LEFT JOIN physical_assets pa ON pa.id = b.asset_id
                  {where_clause}
                 ORDER BY b.updated_at DESC, b.id""",
            tuple(params),
        ).fetchall()
        return {"success": True, "data": [dict(row) for row in rows]}
    finally:
        conn.close()


__all__ = ["router"]
