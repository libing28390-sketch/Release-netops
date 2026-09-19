"""Monitoring V1 control-plane APIs.

These endpoints expose only metadata and secret-free target labels.  SNMP
credentials are resolved into an opaque alias during compilation and are never
returned by this module.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest, ProxyHandler, build_opener

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from core.rbac import require_role
from core.metrics import metrics_registry
from core.crypto import decrypt_credential
from database import get_db_connection
from services.audit_service import log_audit_event
from services.metric_provider import ShadowMetricProvider, provider_from_environment
from services.vault_service import resolve_collector_credentials
from services.monitoring_export_service import (
    generate_interfaces_report,
    generate_devices_report,
    generate_outbound_report,
    fetch_interfaces_report_data,
    fetch_devices_report_data,
    fetch_outbound_report_data,
)
from services.monitoring_compiler import (
    CompileError,
    build_assignments,
    compile_artifact,
    duration_seconds,
    opaque_auth_alias,
    plan_entry_matches_device,
    plan_entry_match_reason,
    variant_match_reason,
    variant_matches_device,
    plan_target_matches_device,
    render_exporter_modules,
    validate_oid_config,
    validate_assignments,
    validate_artifact,
)
from services.monitoring_health_service import classify_collection_health, summarize_collection_health
from services.collector_artifact_service import ArtifactStoreError, CollectorArtifactStore


router = APIRouter(prefix="/monitoring", tags=["monitoring-v1"])
logger = logging.getLogger(__name__)

CANONICAL_PLAN_ID = "plan-generic-ifmib"
CANONICAL_PLAN_NAME = "SNMP 基线采集计划"
CANONICAL_PLAN_NAME_ALIASES = {CANONICAL_PLAN_NAME, "Generic IF-MIB baseline"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _audit(user: Any, event_type: str, summary: str, *, target_type: str, target_id: str, details: dict[str, Any] | None = None) -> None:
    """Persist a redacted control-plane audit event without leaking secrets."""
    try:
        log_audit_event(
            event_type=event_type,
            category="monitoring",
            severity="info",
            status="success",
            summary=summary,
            actor_id=(user or {}).get("id") if isinstance(user, dict) else None,
            actor_username=(user or {}).get("username", "system") if isinstance(user, dict) else "system",
            actor_role=(user or {}).get("role", "system") if isinstance(user, dict) else "system",
            target_type=target_type,
            target_id=target_id,
            details=details or {},
        )
    except Exception:
        logger.warning("Monitoring audit event could not be persisted", exc_info=True)


def _dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def _parse_json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def _scope_list(value: Any, *, field: str, max_items: int = 128) -> list[str]:
    """Normalize a user supplied compatibility scope to a bounded string list."""

    if value in (None, ""):
        return []
    raw = value
    if isinstance(value, str):
        parsed = _parse_json(value, None)
        raw = parsed if isinstance(parsed, list) else value.replace("，", ",").replace(";", ",").split(",")
    if not isinstance(raw, (list, tuple, set)):
        raise HTTPException(status_code=422, detail=f"{field} must be a list or comma-separated string")
    result: list[str] = []
    for item in raw:
        text = " ".join(str(item or "").strip().split())
        if text and text not in result:
            result.append(text[:160])
    if len(result) > max_items:
        raise HTTPException(status_code=422, detail=f"{field} has too many entries")
    return result


def _tenant_id(user: Any) -> str | None:
    if not isinstance(user, dict) or str(user.get("role") or "") == "Administrator":
        return None
    return str(user.get("tenant_id") or "tenant-default").strip() or "tenant-default"


def _assert_asset_visible(asset_id: str, user: Any) -> None:
    tenant = _tenant_id(user)
    if tenant is None:
        return
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id FROM devices WHERE id = ? AND COALESCE(tenant_id, 'tenant-default') = ?",
            (asset_id, tenant),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Device not found")
    finally:
        conn.close()


def _validate_remote_write_endpoint(value: str) -> str:
    endpoint = str(value or "").strip()
    if not endpoint:
        return ""
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise HTTPException(status_code=422, detail="remote_write_endpoint must be an http(s) URL without embedded credentials")
    return endpoint


def _safe_collector_view(row: Any) -> dict[str, Any]:
    item = _dict(row)
    endpoint = str(item.get("remote_write_endpoint") or "")
    try:
        parsed = urlparse(endpoint)
        if parsed.username or parsed.password:
            item["remote_write_endpoint"] = "[REDACTED]"
    except ValueError:
        item["remote_write_endpoint"] = "[REDACTED]"
    return item


def _safe_variant_view(row: Any) -> dict[str, Any]:
    """Return variant metadata with parsed, secret-free OID configuration."""
    item = _dict(row)
    item["oid_config"] = _parse_json(item.pop("oid_config_json", "{}"), {})
    for key in ("supported_platforms", "supported_models", "supported_version_scope", "verified_models", "verified_versions"):
        item[key] = _parse_json(item.get(key), [])
        if not isinstance(item[key], list):
            item[key] = []
    return item


def _oid_config_hashes(config: Mapping[str, Any]) -> tuple[str, str]:
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    mib_sources = json.dumps(config.get("mib_sources") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), hashlib.sha256(mib_sources.encode("utf-8")).hexdigest()


def _is_canonical_plan(value: Mapping[str, Any]) -> bool:
    return str(value.get("id") or "") == CANONICAL_PLAN_ID or str(value.get("name") or "") in CANONICAL_PLAN_NAME_ALIASES


def _reload_snmp_exporter_config() -> bool:
    """Ask the local Compose exporter to reload its published config."""
    request = UrlRequest("http://snmp-exporter:9116/-/reload", method="POST")
    try:
        with build_opener(ProxyHandler({}))(request, timeout=3) as response:
            return 200 <= int(response.status) < 300
    except Exception:
        logger.warning("SNMP exporter configuration reload is pending", exc_info=True)
        return False


class ModuleRequest(BaseModel):
    module_key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=200)
    vendor: str = ""
    cli_platform: str = ""
    feature_domain: str = ""
    description: str = ""
    metric_group: str = ""
    walk_fingerprint: str = ""
    enabled: bool = True


class VariantRequest(BaseModel):
    module_id: str = Field(min_length=1, max_length=100)
    variant_key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=200)
    max_repetitions: int = Field(default=25, ge=1, le=1000)
    retries: int = Field(default=2, ge=0, le=10)
    request_timeout_ms: int = Field(default=3000, ge=100, le=120000)
    scrape_timeout_ms: int = Field(default=20000, ge=1000, le=300000)
    supported_platforms: list[str] = Field(default_factory=list, max_length=128)
    supported_models: list[str] = Field(default_factory=list, max_length=128)
    supported_version_scope: list[str] = Field(default_factory=list, max_length=128)
    oid_config: dict[str, Any] = Field(default_factory=dict)
    status: str = "DRAFT"
    enabled: bool = True


class CollectorRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code: str = Field(min_length=1, max_length=160)
    site_id: str = ""
    collector_type: str = "LOCAL"
    management_address: str = ""
    remote_write_endpoint: str = ""
    max_concurrency: int = Field(default=8, ge=1, le=1024)
    queue_disk_limit_mb: int = Field(default=2048, ge=128, le=1048576)
    enabled: bool = True


class PlanRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    cli_platform: str = ""
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class CompileRequest(BaseModel):
    config_version: int | None = Field(default=None, ge=1)


@router.get("/provider")
def monitoring_provider(provider: str | None = Query(default=None), _user=require_role("Viewer")):
    selected = str(provider or os.environ.get("MONITORING_METRIC_BACKEND", "native")).lower()
    if selected not in {"native", "shadow", "victoriametrics"}:
        raise HTTPException(status_code=422, detail="Unsupported monitoring metric provider")
    return {"provider": selected, "supported": ["native", "shadow", "victoriametrics"]}


@router.get("/modules")
def list_modules(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM snmp_modules ORDER BY module_key").fetchall()
        return {"items": [_dict(row) for row in rows]}
    finally:
        conn.close()


@router.post("/modules")
def create_module(body: ModuleRequest, _user=require_role("Operator")):
    module_id = f"module-{uuid.uuid4().hex[:16]}"
    now = _now()
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO snmp_modules
               (id, module_key, display_name, vendor, cli_platform, feature_domain,
                description, metric_group, walk_fingerprint, enabled, built_in, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (module_id, body.module_key, body.display_name, body.vendor, body.cli_platform,
             body.feature_domain, body.description, body.metric_group, body.walk_fingerprint,
             int(body.enabled), now, now),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail=f"Module already exists or is invalid: {exc}") from exc
    finally:
        conn.close()
    _audit(_user, "MONITORING_MODULE_CREATED", f"Created monitoring module {module_id}", target_type="snmp_module", target_id=module_id, details={"module_key": body.module_key})
    return {"id": module_id, **body.model_dump(), "built_in": False, "created_at": now, "updated_at": now}


@router.get("/modules/{module_id}")
def get_module(module_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM snmp_modules WHERE id = ?", (module_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Module not found")
        return _dict(row)
    finally:
        conn.close()


@router.patch("/modules/{module_id}")
def update_module(module_id: str, body: dict[str, Any], _user=require_role("Operator")):
    allowed = {"display_name", "vendor", "cli_platform", "feature_domain", "description", "metric_group", "walk_fingerprint", "enabled"}
    updates = {key: value for key, value in body.items() if key in allowed}
    if not updates:
        raise HTTPException(status_code=422, detail="No module fields to update")
    updates["updated_at"] = _now()
    conn = get_db_connection()
    try:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(f"UPDATE snmp_modules SET {assignments} WHERE id = ?", tuple(updates.values()) + (module_id,))
        if conn.execute("SELECT 1 FROM snmp_modules WHERE id = ?", (module_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Module not found")
        conn.commit()
        result = get_module(module_id, _user=_user)
        _audit(_user, "MONITORING_MODULE_UPDATED", f"Updated monitoring module {module_id}", target_type="snmp_module", target_id=module_id, details={"fields": sorted(updates)})
        return result
    finally:
        conn.close()


@router.delete("/modules/{module_id}")
def delete_module(module_id: str, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id, module_key, built_in FROM snmp_modules WHERE id = ?", (module_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Module not found")
        module = _dict(row)
        if bool(module.get("built_in")):
            raise HTTPException(status_code=409, detail="Built-in modules cannot be deleted")
        references = []
        for plan_row in conn.execute("SELECT id, name, config_json FROM monitoring_collection_plans").fetchall():
            plan = _dict(plan_row)
            config = _parse_json(plan.get("config_json"), {})
            entries = config.get("modules") if isinstance(config, dict) else []
            if any(str(_dict(entry).get("module") or _dict(entry).get("module_key") or "") == str(module.get("module_key")) for entry in entries if isinstance(entry, dict)):
                references.append(str(plan.get("name") or plan.get("id") or ""))
        if references:
            raise HTTPException(status_code=409, detail=f"Module is used by collection plans: {', '.join(references[:5])}")
        conn.execute("DELETE FROM snmp_modules WHERE id = ?", (module_id,))
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail=f"Module deletion failed: {exc}") from exc
    finally:
        conn.close()
    _audit(_user, "MONITORING_MODULE_DELETED", f"Deleted monitoring module {module_id}", target_type="snmp_module", target_id=module_id, details={"module_key": module.get("module_key", "")})
    return {"id": module_id, "deleted": True}


@router.get("/module-variants")
def list_module_variants(module_id: str | None = Query(default=None), _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        if module_id:
            rows = conn.execute("SELECT * FROM snmp_module_variants WHERE module_id = ? ORDER BY variant_key", (module_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM snmp_module_variants ORDER BY variant_key").fetchall()
        return {"items": [_safe_variant_view(row) for row in rows]}
    finally:
        conn.close()


@router.get("/module-variants/{variant_id}")
def get_module_variant(variant_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM snmp_module_variants WHERE id = ?", (variant_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Module variant not found")
        return _safe_variant_view(row)
    finally:
        conn.close()


@router.patch("/module-variants/{variant_id}")
def update_module_variant(variant_id: str, body: dict[str, Any], _user=require_role("Operator")):
    allowed = {"display_name", "max_repetitions", "retries", "request_timeout_ms", "scrape_timeout_ms", "status", "enabled"}
    updates = {key: value for key, value in body.items() if key in allowed}
    for key in ("supported_platforms", "supported_models", "supported_version_scope"):
        if key in body:
            updates[key] = json.dumps(_scope_list(body.get(key), field=key), ensure_ascii=False)
    if "oid_config" in body:
        if not isinstance(body["oid_config"], dict):
            raise HTTPException(status_code=422, detail="oid_config must be an object")
        try:
            validated_oid_config = validate_oid_config(body["oid_config"])
        except CompileError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        generator_hash, mib_hash = _oid_config_hashes(validated_oid_config)
        updates["oid_config_json"] = json.dumps(validated_oid_config, ensure_ascii=False, sort_keys=True)
        updates["generator_config_hash"] = generator_hash
        updates["mib_hash"] = mib_hash
    if not updates:
        raise HTTPException(status_code=422, detail="No module variant fields to update")
    if "status" in updates:
        updates["status"] = str(updates["status"]).upper()
    updates["updated_at"] = _now()
    conn = get_db_connection()
    try:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(f"UPDATE snmp_module_variants SET {assignments} WHERE id = ?", tuple(updates.values()) + (variant_id,))
        if conn.execute("SELECT 1 FROM snmp_module_variants WHERE id = ?", (variant_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Module variant not found")
        conn.commit()
        result = get_module_variant(variant_id, _user=_user)
        _audit(_user, "MONITORING_VARIANT_UPDATED", f"Updated monitoring module variant {variant_id}", target_type="snmp_module_variant", target_id=variant_id, details={"fields": sorted(updates)})
        return result
    finally:
        conn.close()


@router.delete("/module-variants/{variant_id}")
def delete_module_variant(variant_id: str, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id, variant_key FROM snmp_module_variants WHERE id = ?", (variant_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Module variant not found")
        variant = _dict(row)
        references = []
        for plan_row in conn.execute("SELECT id, name, config_json FROM monitoring_collection_plans").fetchall():
            plan = _dict(plan_row)
            config = _parse_json(plan.get("config_json"), {})
            entries = config.get("modules") if isinstance(config, dict) else []
            if any(str(_dict(entry).get("variant") or _dict(entry).get("variant_key") or "") == str(variant.get("variant_key")) for entry in entries if isinstance(entry, dict)):
                references.append(str(plan.get("name") or plan.get("id") or ""))
        if references:
            raise HTTPException(status_code=409, detail=f"Module variant is used by collection plans: {', '.join(references[:5])}")
        conn.execute("DELETE FROM snmp_module_variants WHERE id = ?", (variant_id,))
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail=f"Module variant deletion failed: {exc}") from exc
    finally:
        conn.close()
    _audit(_user, "MONITORING_VARIANT_DELETED", f"Deleted monitoring module variant {variant_id}", target_type="snmp_module_variant", target_id=variant_id, details={"variant_key": variant.get("variant_key", "")})
    return {"id": variant_id, "deleted": True}


@router.post("/module-variants")
def create_module_variant(body: VariantRequest, _user=require_role("Operator")):
    try:
        validated_oid_config = validate_oid_config(body.oid_config)
    except CompileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    variant_id = f"variant-{uuid.uuid4().hex[:16]}"
    generator_hash, mib_hash = _oid_config_hashes(validated_oid_config)
    now = _now()
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO snmp_module_variants
               (id, module_id, variant_key, display_name, max_repetitions, retries,
                request_timeout_ms, scrape_timeout_ms, supported_platforms,
                supported_models, supported_version_scope, status, enabled,
                oid_config_json, generator_config_hash, mib_hash, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (variant_id, body.module_id, body.variant_key, body.display_name, body.max_repetitions,
             body.retries, body.request_timeout_ms, body.scrape_timeout_ms,
             json.dumps(_scope_list(body.supported_platforms, field="supported_platforms"), ensure_ascii=False),
             json.dumps(_scope_list(body.supported_models, field="supported_models"), ensure_ascii=False),
             json.dumps(_scope_list(body.supported_version_scope, field="supported_version_scope"), ensure_ascii=False),
             body.status.upper(), int(body.enabled),
             json.dumps(validated_oid_config, ensure_ascii=False, sort_keys=True), generator_hash, mib_hash, now, now),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail=f"Module variant is invalid: {exc}") from exc
    finally:
        conn.close()
    _audit(_user, "MONITORING_VARIANT_CREATED", f"Created monitoring module variant {variant_id}", target_type="snmp_module_variant", target_id=variant_id, details={"variant_key": body.variant_key, "module_id": body.module_id})
    return {"id": variant_id, **body.model_dump(), "status": body.status.upper(), "created_at": now, "updated_at": now}


@router.post("/module-variants/{variant_id}/test")
def test_module_variant(variant_id: str, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id, status, enabled, max_repetitions, retries, request_timeout_ms, oid_config_json FROM snmp_module_variants WHERE id = ?", (variant_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Module variant not found")
        item = _dict(row)
        oid_error = None
        oid_metric_count = 0
        try:
            oid_config = validate_oid_config(item.get("oid_config_json") or "{}")
            oid_metric_count = len(oid_config.get("metrics") or [])
        except CompileError as exc:
            oid_error = str(exc)
        valid = bool(item.get("enabled")) and str(item.get("status") or "").upper() not in {"FAILED", "DEPRECATED"} and oid_error is None
        return {"variant_id": variant_id, "status": "SUCCESS" if valid else "FAILED", "samples": 0, "duration_seconds": 0, "snmp_retries": int(item.get("retries") or 0), "oid_metric_count": oid_metric_count, "error_code": oid_error or (None if valid else "MODULE_ERROR")}
    finally:
        conn.close()


@router.post("/module-variants/{variant_id}/publish")
def publish_module_variant(variant_id: str, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id, oid_config_json FROM snmp_module_variants WHERE id = ?", (variant_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Module variant not found")
        try:
            validate_oid_config(row["oid_config_json"] if hasattr(row, "keys") else row[1])
        except CompileError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        conn.execute("UPDATE snmp_module_variants SET status = 'PUBLISHED', enabled = 1, updated_at = ? WHERE id = ?", (_now(), variant_id))
        conn.commit()
        _audit(_user, "MONITORING_VARIANT_PUBLISHED", f"Published monitoring module variant {variant_id}", target_type="snmp_module_variant", target_id=variant_id)
        return {"status": "PUBLISHED", "variant_id": variant_id}
    finally:
        conn.close()


@router.post("/modules/{module_id}/validate")
def validate_module(module_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        module = conn.execute("SELECT * FROM snmp_modules WHERE id = ?", (module_id,)).fetchone()
        if not module:
            raise HTTPException(status_code=404, detail="Module not found")
        variants = conn.execute("SELECT * FROM snmp_module_variants WHERE module_id = ? AND enabled = 1", (module_id,)).fetchall()
        return {"valid": bool(variants), "module": _dict(module), "variant_count": len(variants), "errors": [] if variants else ["MODULE_HAS_NO_ENABLED_VARIANT"]}
    finally:
        conn.close()


@router.post("/modules/{module_id}/test")
def test_module(module_id: str, _user=require_role("Operator")):
    validation = validate_module(module_id, _user=_user)
    return {
        "module_id": module_id,
        "status": "SUCCESS" if validation["valid"] else "FAILED",
        "variant_count": validation["variant_count"],
        "samples": 0,
        "duration_seconds": 0,
        "error_code": None if validation["valid"] else "MODULE_ERROR",
    }


@router.post("/modules/{module_id}/publish")
def publish_module(module_id: str, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        module = conn.execute("SELECT id FROM snmp_modules WHERE id = ?", (module_id,)).fetchone()
        if not module:
            raise HTTPException(status_code=404, detail="Module not found")
        conn.execute("UPDATE snmp_modules SET enabled = 1, updated_at = ? WHERE id = ?", (_now(), module_id))
        conn.commit()
        _audit(_user, "MONITORING_MODULE_PUBLISHED", f"Published monitoring module {module_id}", target_type="snmp_module", target_id=module_id)
        return {"status": "PUBLISHED", "module_id": module_id}
    finally:
        conn.close()


@router.get("/collectors")
def list_collectors(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM monitoring_collectors ORDER BY code").fetchall()
        return {"items": [_safe_collector_view(row) for row in rows]}
    finally:
        conn.close()


@router.get("/collectors/{collector_id}")
def get_collector(collector_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM monitoring_collectors WHERE id = ?", (collector_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Collector not found")
        return _safe_collector_view(row)
    finally:
        conn.close()


@router.patch("/collectors/{collector_id}")
def update_collector(collector_id: str, body: dict[str, Any], _user=require_role("Operator")):
    allowed = {"name", "site_id", "collector_type", "management_address", "remote_write_endpoint", "max_concurrency", "queue_disk_limit_mb", "enabled"}
    updates = {key: value for key, value in body.items() if key in allowed}
    if not updates:
        raise HTTPException(status_code=422, detail="No collector fields to update")
    if "collector_type" in updates:
        updates["collector_type"] = str(updates["collector_type"]).upper()
    if str(updates.get("remote_write_endpoint") or "") == "[REDACTED]":
        updates.pop("remote_write_endpoint", None)
    if "remote_write_endpoint" in updates:
        updates["remote_write_endpoint"] = _validate_remote_write_endpoint(str(updates["remote_write_endpoint"]))
    updates["updated_at"] = _now()
    conn = get_db_connection()
    try:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(f"UPDATE monitoring_collectors SET {assignments} WHERE id = ?", tuple(updates.values()) + (collector_id,))
        if conn.execute("SELECT 1 FROM monitoring_collectors WHERE id = ?", (collector_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Collector not found")
        conn.commit()
        result = get_collector(collector_id, _user=_user)
        _audit(_user, "MONITORING_COLLECTOR_UPDATED", f"Updated monitoring collector {collector_id}", target_type="monitoring_collector", target_id=collector_id, details={"fields": sorted(updates)})
        return result
    finally:
        conn.close()


@router.delete("/collectors/{collector_id}")
def delete_collector(collector_id: str, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id, code FROM monitoring_collectors WHERE id = ?", (collector_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Collector not found")
        assignment_count = int(_dict(conn.execute("SELECT COUNT(*) AS count FROM monitoring_collection_assignments WHERE collector_id = ?", (collector_id,)).fetchone()).get("count") or 0)
        config_count = int(_dict(conn.execute("SELECT COUNT(*) AS count FROM monitoring_config_versions WHERE collector_id = ?", (collector_id,)).fetchone()).get("count") or 0)
        if assignment_count or config_count:
            raise HTTPException(status_code=409, detail="Collector has assignments or configuration history and cannot be deleted")
        conn.execute("DELETE FROM monitoring_collectors WHERE id = ?", (collector_id,))
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail=f"Collector deletion failed: {exc}") from exc
    finally:
        conn.close()
    collector = _dict(row)
    _audit(_user, "MONITORING_COLLECTOR_DELETED", f"Deleted monitoring collector {collector_id}", target_type="monitoring_collector", target_id=collector_id, details={"code": collector.get("code", "")})
    return {"id": collector_id, "deleted": True}


@router.post("/collectors")
def create_collector(body: CollectorRequest, _user=require_role("Operator")):
    remote_write_endpoint = _validate_remote_write_endpoint(body.remote_write_endpoint)
    collector_id = f"collector-{uuid.uuid4().hex[:16]}"
    now = _now()
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO monitoring_collectors
               (id, name, code, site_id, collector_type, enabled, management_address,
                remote_write_endpoint, max_concurrency, queue_disk_limit_mb, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (collector_id, body.name, body.code, body.site_id, body.collector_type.upper(), int(body.enabled),
             body.management_address, remote_write_endpoint, body.max_concurrency,
             body.queue_disk_limit_mb, now, now),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail=f"Collector already exists or is invalid: {exc}") from exc
    finally:
        conn.close()
    _audit(_user, "MONITORING_COLLECTOR_CREATED", f"Created monitoring collector {collector_id}", target_type="monitoring_collector", target_id=collector_id, details={"code": body.code})
    return {"id": collector_id, **body.model_dump(), "collector_type": body.collector_type.upper(), "status": "UNKNOWN", "created_at": now, "updated_at": now}


@router.post("/collectors/{collector_id}/test")
def test_collector(collector_id: str, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id, code, enabled, status, last_heartbeat_at FROM monitoring_collectors WHERE id = ?", (collector_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Collector not found")
        item = _dict(row)
        return {"collector_id": collector_id, "status": "PASS" if item.get("enabled") else "DISABLED", "last_heartbeat_at": item.get("last_heartbeat_at")}
    finally:
        conn.close()


@router.post("/collectors/{collector_id}/validate")
def validate_collector_config(collector_id: str, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT config_version, status, artifact_path, manifest_json, checksum FROM monitoring_config_versions WHERE collector_id = ? ORDER BY config_version DESC LIMIT 1", (collector_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Collector configuration not found")
        item = _dict(row)
        manifest = _parse_json(item.get("manifest_json"), {})
        errors = []
        if not manifest.get("schema_version"):
            errors.append("MANIFEST_SCHEMA_MISSING")
        if int(manifest.get("config_version") or 0) != int(item.get("config_version") or 0):
            errors.append("MANIFEST_VERSION_MISMATCH")
        if item.get("artifact_path"):
            try:
                validate_artifact(str(item["artifact_path"]))
            except CompileError as exc:
                errors.append(str(exc))
        return {"collector_id": collector_id, "config_version": item.get("config_version"), "valid": not errors, "errors": errors, "status": item.get("status")}
    finally:
        conn.close()


@router.get("/collection-plans")
def list_monitoring_plans(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM monitoring_collection_plans ORDER BY name").fetchall()
        result = []
        for row in rows:
            item = _dict(row)
            item["config"] = _parse_json(item.pop("config_json", "{}"), {})
            item["is_canonical"] = _is_canonical_plan(item)
            result.append(item)
        return {"items": result}
    finally:
        conn.close()


@router.get("/collection-plans/{plan_id}/preview")
def preview_monitoring_plan(plan_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        plan = conn.execute("SELECT * FROM monitoring_collection_plans WHERE id = ?", (plan_id,)).fetchone()
        if not plan:
            raise HTTPException(status_code=404, detail="Collection plan not found")
        row = _dict(plan)
        config = _parse_json(row.pop("config_json", "{}"), {})
        row["is_canonical"] = _is_canonical_plan(row)
        try:
            device_sql = "SELECT id, hostname, vendor, platform, cli_platform, model, version, os_version, firmware_version, role, device_role, device_category, site, site_id, ip_address, management_address, status FROM devices WHERE (status IS NULL OR LOWER(status) = 'online')"
            device_params: tuple[Any, ...] = ()
            tenant = _tenant_id(_user)
            if tenant is not None:
                device_sql += " AND COALESCE(tenant_id, 'tenant-default') = ?"
                device_params = (tenant,)
            devices = conn.execute(device_sql, device_params).fetchall()
        except Exception:
            # Read-only preview remains useful on an installation where CMDB
            # access is temporarily unavailable; the compile/apply path still
            # fails closed when it needs real device rows.
            devices = []
        entries = config.get("modules") if isinstance(config, dict) else []
        module_rows = {
            str(item["module_key"]): _dict(item)
            for item in conn.execute("SELECT * FROM snmp_modules WHERE enabled = 1").fetchall()
            if item["module_key"]
        }
        variant_rows = {
            str(item["variant_key"]): _dict(item)
            for item in conn.execute("SELECT * FROM snmp_module_variants WHERE enabled = 1").fetchall()
            if item["variant_key"]
        }
        matched_devices = []
        matched_variants: dict[str, int] = {}
        for device_row in devices:
            device = _dict(device_row)
            if not plan_target_matches_device(device, config):
                continue
            selected = []
            if isinstance(entries, list):
                for raw_entry in entries:
                    if not isinstance(raw_entry, dict) or raw_entry.get("enabled", True) is False:
                        continue
                    entry = _dict(raw_entry)
                    if not plan_entry_matches_device(entry, device):
                        continue
                    variant_key = str(entry.get("variant") or entry.get("variant_key") or "")
                    variant = variant_rows.get(variant_key) or {}
                    module_key = str(entry.get("module") or entry.get("module_key") or "")
                    module = module_rows.get(module_key) or {}
                    if variant and not variant_matches_device(variant, device, module):
                        continue
                    selected.append(entry)
            if not selected:
                continue
            for entry in selected:
                variant_key = str(entry.get("variant") or entry.get("variant_key") or "")
                if variant_key:
                    matched_variants[variant_key] = matched_variants.get(variant_key, 0) + 1
            match_reasons: set[str] = set()
            for entry in selected:
                variant_key = str(entry.get("variant") or entry.get("variant_key") or "")
                module_key = str(entry.get("module") or entry.get("module_key") or "")
                variant = variant_rows.get(variant_key) or {}
                module = module_rows.get(module_key) or {}
                reason = plan_entry_match_reason(entry, device)
                variant_reason = variant_match_reason(variant, device, module)
                match_reasons.add(reason if variant_reason == "variant scope unrestricted" else f"{reason}; {variant_reason}")
            matched_devices.append({
                "id": device.get("id"),
                "hostname": device.get("hostname") or device.get("id"),
                "vendor": device.get("vendor") or "",
                "platform": device.get("platform") or device.get("cli_platform") or "",
                "variants": sorted({str(entry.get("variant") or entry.get("variant_key") or "") for entry in selected if entry.get("variant") or entry.get("variant_key")}),
                "match_reasons": sorted(match_reasons),
            })
        coverage = {
            "target_count": len(matched_devices),
            "variant_hits": matched_variants,
            "unmatched_online_devices": max(len(devices) - len(matched_devices), 0),
        }
        return {"plan": {**row, "config": config, "coverage": coverage}, "preview": "read-only"}
    finally:
        conn.close()


@router.post("/collection-plans/{plan_id}/compile-test")
def compile_test_monitoring_plan(plan_id: str, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM monitoring_collection_plans WHERE id = ?", (plan_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Collection plan not found")
        plan = _dict(row)
        config = _parse_json(plan.get("config_json"), {})
        modules = conn.execute("SELECT * FROM snmp_modules WHERE enabled = 1").fetchall()
        variants = conn.execute("SELECT * FROM snmp_module_variants WHERE enabled = 1").fetchall()
        entries = config.get("modules") if isinstance(config, dict) else []
        errors: list[str] = []
        if not isinstance(entries, list) or not entries:
            errors.append("PLAN_HAS_NO_MODULES")
        module_keys = {str(_dict(item).get("module_key") or "") for item in modules}
        variant_keys = {str(_dict(item).get("variant_key") or "") for item in variants}
        variant_statuses = {str(_dict(item).get("variant_key") or ""): str(_dict(item).get("status") or "DRAFT").upper() for item in variants}
        for entry in entries if isinstance(entries, list) else []:
            item = _dict(entry)
            if str(item.get("module") or item.get("module_key") or "") not in module_keys:
                errors.append(f"MODULE_NOT_FOUND:{item.get('module') or item.get('module_key')}")
            if str(item.get("variant") or item.get("variant_key") or "") not in variant_keys:
                errors.append(f"MODULE_VARIANT_NOT_FOUND:{item.get('variant') or item.get('variant_key')}")
            elif variant_statuses.get(str(item.get("variant") or item.get("variant_key") or "")) not in {"TESTED", "PUBLISHED"}:
                errors.append(f"MODULE_VARIANT_NOT_PUBLISHED:{item.get('variant') or item.get('variant_key')}")
            try:
                interval = duration_seconds(item.get("interval", 60), field="interval")
                timeout = duration_seconds(item.get("scrape_timeout", 20), field="scrape_timeout")
                if timeout >= interval:
                    errors.append("TIMEOUT_INVALID")
            except CompileError as exc:
                errors.append(str(exc))
        try:
            render_exporter_modules(
                [{"variant_key": _dict(item).get("variant") or _dict(item).get("variant_key"), "enabled": _dict(item).get("enabled", True)} for item in entries if isinstance(item, dict)],
                modules=[_dict(item) for item in modules],
                variants=[_dict(item) for item in variants],
            )
        except CompileError as exc:
            errors.append(str(exc))
        target_scope = config.get("target_scope") if isinstance(config, dict) and isinstance(config.get("target_scope"), dict) else {}
        target_ips = {str(value).strip() for value in (config.get("target_ips") or []) if str(value).strip()} if isinstance(config, dict) else set()
        target_device_ids = {str(value).strip() for value in (config.get("device_ids") or []) if str(value).strip()} if isinstance(config, dict) else set()
        matched_targets: list[dict[str, Any]] = []
        if target_scope or target_ips or target_device_ids:
            device_rows = conn.execute(
                "SELECT id, hostname, ip_address, management_address, vendor, platform, cli_platform, model, version, os_version, firmware_version, role, device_role, device_category, site, site_id, status FROM devices WHERE status IS NULL OR LOWER(status) = 'online'"
            ).fetchall()
            module_lookup = {str(_dict(item).get("module_key") or ""): _dict(item) for item in modules}
            variant_lookup = {str(_dict(item).get("variant_key") or ""): _dict(item) for item in variants}
            try:
                from services.tag_service import get_device_tags
            except Exception:
                get_device_tags = None
            for device_row in device_rows:
                item = _dict(device_row)
                if get_device_tags:
                    try:
                        item["tag_ids"] = [str(tag.get("id") or "") for tag in get_device_tags(conn, str(item.get("id") or "")) if tag.get("id")]
                    except Exception:
                        item["tag_ids"] = []
                if plan_target_matches_device(item, {"target_scope": target_scope, "target_ips": target_ips, "device_ids": target_device_ids}):
                    scope_matches = []
                    for raw_entry in entries if isinstance(entries, list) else []:
                        entry = _dict(raw_entry)
                        if entry.get("enabled", True) is False or not plan_entry_matches_device(entry, item):
                            continue
                        variant_key = str(entry.get("variant") or entry.get("variant_key") or "")
                        module_key = str(entry.get("module") or entry.get("module_key") or "")
                        variant = variant_lookup.get(variant_key) or {}
                        module = module_lookup.get(module_key) or {}
                        if variant and variant_matches_device(variant, item, module):
                            scope_matches.append(variant_key)
                    if entries and not scope_matches:
                        errors.append(f"MODULE_VARIANT_SCOPE_NO_MATCH:{item.get('id')}")
                    matched_targets.append({
                        "id": item.get("id"),
                        "hostname": item.get("hostname") or item.get("id"),
                        "ip_address": item.get("ip_address") or item.get("management_address"),
                        "platform": item.get("platform") or "",
                    })
            known_ips = {str(item.get("ip_address") or "").strip() for item in matched_targets}
            missing_ips = sorted(target_ips - known_ips)
            errors.extend(f"TARGET_IP_NOT_FOUND:{value}" for value in missing_ips)
            if target_device_ids and not matched_targets:
                errors.append("TARGET_DEVICE_NOT_FOUND")
        return {
            "plan_id": plan_id,
            "valid": not errors,
            "errors": sorted(set(errors)),
            "module_count": len(entries) if isinstance(entries, list) else 0,
            "target_count": len(matched_targets) if (target_scope or target_ips or target_device_ids) else None,
            "targets": matched_targets,
        }
    finally:
        conn.close()


@router.post("/collection-plans")
def create_monitoring_plan(body: PlanRequest, _user=require_role("Operator")):
    plan_id = f"plan-{uuid.uuid4().hex[:16]}"
    now = _now()
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO monitoring_collection_plans
               (id, name, cli_platform, description, config_json, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (plan_id, body.name, body.cli_platform, body.description, json.dumps(body.config, ensure_ascii=False), int(body.enabled), now, now),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail=f"Collection plan already exists or is invalid: {exc}") from exc
    finally:
        conn.close()
    _audit(_user, "MONITORING_PLAN_CREATED", f"Created monitoring collection plan {plan_id}", target_type="monitoring_collection_plan", target_id=plan_id, details={"name": body.name, "cli_platform": body.cli_platform, "module_count": len(body.config.get("modules") or [])})
    return {"id": plan_id, "name": body.name, "cli_platform": body.cli_platform, "description": body.description, "config": body.config, "enabled": body.enabled, "created_at": now, "updated_at": now}


@router.put("/collection-plans/{plan_id}")
def update_monitoring_plan(plan_id: str, body: PlanRequest, _user=require_role("Operator")):
    now = _now()
    conn = get_db_connection()
    try:
        existing = conn.execute("SELECT id FROM monitoring_collection_plans WHERE id = ?", (plan_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Collection plan not found")
        conn.execute(
            """UPDATE monitoring_collection_plans
                  SET name = ?, cli_platform = ?, description = ?, config_json = ?, enabled = ?, updated_at = ?
                WHERE id = ?""",
            (body.name, body.cli_platform, body.description, json.dumps(body.config, ensure_ascii=False), int(body.enabled), now, plan_id),
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail=f"Collection plan update failed: {exc}") from exc
    finally:
        conn.close()
    _audit(_user, "MONITORING_PLAN_UPDATED", f"Updated monitoring collection plan {plan_id}", target_type="monitoring_collection_plan", target_id=plan_id, details={"name": body.name, "cli_platform": body.cli_platform, "module_count": len(body.config.get("modules") or [])})
    return {"id": plan_id, "name": body.name, "cli_platform": body.cli_platform, "description": body.description, "config": body.config, "enabled": body.enabled, "updated_at": now}


@router.post("/collection-plans/{plan_id}/apply")
def apply_monitoring_plan(plan_id: str, _user=require_role("Operator")):
    """Save-and-apply entry point for the normal plan workflow.

    Users do not need to reason about the intermediate compiler state.  The
    control plane still keeps the versioned compile/publish records and calls
    the same audited operations used by collector administration.
    """

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, name, enabled FROM monitoring_collection_plans WHERE id = ?",
            (plan_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Collection plan not found")
        if not bool(row["enabled"] if hasattr(row, "keys") else row[2]):
            raise HTTPException(status_code=409, detail="Disabled collection plan cannot be applied")
        tenant = _tenant_id(_user)
        if tenant is None:
            collector_rows = conn.execute("SELECT id FROM monitoring_collectors WHERE enabled = 1 ORDER BY id").fetchall()
        else:
            collector_rows = conn.execute(
                "SELECT c.id FROM monitoring_collectors c WHERE c.enabled = 1 AND (c.id = 'collector-local' OR c.site_id IN (SELECT DISTINCT site_id FROM devices WHERE COALESCE(tenant_id, 'tenant-default') = ?)) ORDER BY c.id",
                (tenant,),
            ).fetchall()
        collectors = [str(item["id"] if hasattr(item, "keys") else item[0]) for item in collector_rows]
    finally:
        conn.close()

    if not collectors:
        raise HTTPException(status_code=409, detail="No enabled collector is available")
    results = []
    try:
        for collector_id in collectors:
            compiled = compile_collector(collector_id, _user=_user)
            published = publish_collector(collector_id, _user=_user)
            results.append({"collector_id": collector_id, "config_version": published.get("config_version"), "status": published.get("status"), "assignment_count": compiled.get("assignment_count", 0)})
    except HTTPException as exc:
        detail = exc.detail
        raise HTTPException(status_code=exc.status_code, detail={"code": "PLAN_APPLY_FAILED", "plan_id": plan_id, "collector_results": results, "cause": detail}) from exc
    _audit(
        _user,
        "MONITORING_PLAN_APPLIED",
        f"Applied monitoring collection plan {plan_id}",
        target_type="monitoring_collection_plan",
        target_id=plan_id,
        details={"plan_id": plan_id, "collector_count": len(results), "status": "APPLIED"},
    )
    return {"plan_id": plan_id, "status": "APPLIED", "collectors": results}


@router.delete("/collection-plans/{plan_id}")
def delete_monitoring_plan(plan_id: str, _user=require_role("Operator")):
    """Delete a plan and the assignments compiled exclusively from it.

    Assignments do not have a database foreign key to plans, so they must be
    removed in the same transaction; otherwise a deleted plan could continue
    to be collected until a later compilation run.
    """
    conn = get_db_connection()
    try:
        existing = conn.execute("SELECT id, name FROM monitoring_collection_plans WHERE id = ?", (plan_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Collection plan not found")
        existing_plan = _dict(existing)
        if _is_canonical_plan(existing_plan):
            raise HTTPException(status_code=409, detail="The canonical SNMP baseline plan cannot be deleted")
        removed_assignments = conn.execute(
            "DELETE FROM monitoring_collection_assignments WHERE source_type = ? AND source_plan_id = ?",
            ("PLAN", plan_id),
        ).rowcount
        conn.execute("DELETE FROM monitoring_collection_plans WHERE id = ?", (plan_id,))
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail=f"Collection plan deletion failed: {exc}") from exc
    finally:
        conn.close()
    plan = _dict(existing)
    _audit(_user, "MONITORING_PLAN_DELETED", f"Deleted monitoring collection plan {plan_id}", target_type="monitoring_collection_plan", target_id=plan_id, details={"name": plan.get("name", ""), "removed_assignment_count": removed_assignments or 0})
    return {"id": plan_id, "deleted": True, "removed_assignment_count": removed_assignments or 0}


@router.get("/assignments")
def list_assignments(collector_id: str | None = Query(default=None), asset_id: str | None = Query(default=None), _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        clauses, params = ["1=1"], []
        tenant = _tenant_id(_user)
        join = ""
        if tenant is not None:
            join = " JOIN devices d ON d.id = a.asset_id"
            clauses.append("COALESCE(d.tenant_id, 'tenant-default') = ?")
            params.append(tenant)
        if collector_id:
            clauses.append("a.collector_id = ?"); params.append(collector_id)
        if asset_id:
            clauses.append("a.asset_id = ?"); params.append(asset_id)
        rows = conn.execute(f"SELECT a.* FROM monitoring_collection_assignments a{join} WHERE {' AND '.join(clauses)} ORDER BY a.asset_id, a.module_variant_id", tuple(params)).fetchall()
        return {"items": [_dict(row) for row in rows]}
    finally:
        conn.close()


@router.get("/devices/{device_id}/assignments")
def device_assignments(device_id: str, _user=require_role("Viewer")):
    _assert_asset_visible(device_id, _user)
    return list_assignments(collector_id=None, asset_id=device_id, _user=_user)


@router.post("/devices/{device_id}/preview-assignments")
def preview_device_assignments(device_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        device = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        _assert_asset_visible(device_id, _user)
        inputs = _load_compile_inputs(conn, str(_dict(device).get("collector_id") or "collector-local"), _user)
        device_rows = [_dict(device)]
        device_rows[0].setdefault("collector_id", "collector-local")
        assignments = build_assignments(device_rows, *inputs[1:5], credential_aliases=inputs[-1])
        return {"device_id": device_id, "items": assignments}
    except CompileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()


def _load_compile_inputs(conn, collector_id: str, user: Any = None):
    tenant = _tenant_id(user)
    device_sql = """
        SELECT d.*,
               COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), CASE WHEN SUBSTR(COALESCE(d.site, ''), 1, 5) = 'site-' THEN '' ELSE COALESCE(d.site, '') END, '') AS site_name
        FROM devices d
        LEFT JOIN sites s ON (s.id = d.site_id OR s.id = d.site OR s.site_code = d.site OR s.site_name = d.site)
        WHERE d.status IS NULL OR LOWER(d.status) = 'online'
    """
    device_params: tuple[Any, ...] = ()
    if tenant is not None:
        device_sql += " AND COALESCE(d.tenant_id, 'tenant-default') = ?"
        device_params = (tenant,)
    devices = [_dict(row) for row in conn.execute(device_sql, device_params).fetchall()]
    server_sql = """
        SELECT pa.*,
               COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), '') AS site_name
        FROM physical_assets pa
        LEFT JOIN sites s ON (s.id = pa.site_id OR s.id = pa.site)
        WHERE pa.asset_type = 'server'
          AND (pa.status IS NULL OR pa.status = 'active')
    """
    server_params: tuple[Any, ...] = ()
    if tenant is not None:
        server_sql += " AND COALESCE(pa.tenant_id, 'tenant-default') = ?"
        server_params = (tenant,)
    try:
        servers = [_dict(row) for row in conn.execute(server_sql, server_params).fetchall()]
    except Exception:
        servers = []
    try:
        from services.tag_service import get_device_tags
        for device in devices:
            device["tag_ids"] = [str(item.get("id") or "") for item in get_device_tags(conn, str(device.get("id") or "")) if item.get("id")]
    except Exception:
        for device in devices:
            device.setdefault("tag_ids", [])
    modules = [_dict(row) for row in conn.execute("SELECT * FROM snmp_modules WHERE enabled = 1").fetchall()]
    variants = [_dict(row) for row in conn.execute("SELECT * FROM snmp_module_variants WHERE enabled = 1").fetchall()]
    collectors = [_dict(row) for row in conn.execute("SELECT * FROM monitoring_collectors WHERE enabled = 1").fetchall()]
    plans = [_dict(row) for row in conn.execute("SELECT * FROM monitoring_collection_plans WHERE enabled = 1").fetchall()]
    credentials = []
    try:
        credentials = []
        for row in conn.execute("""SELECT id, credential_type, username, snmp_community,
                                         encrypted_password, snmp_security_level,
                                         snmp_auth_protocol, snmp_auth_password,
                                         snmp_priv_protocol, snmp_priv_password,
                                         snmp_context_name
                                    FROM credentials""").fetchall():
            item = _dict(row)
            # Secrets are decrypted only inside the compiler boundary so they
            # can be written to the protected collector artifact.  They are
            # never placed in assignments, labels, manifests, or responses.
            item["community"] = decrypt_credential(item.pop("snmp_community", "") or "") or ""
            item["password"] = decrypt_credential(item.pop("encrypted_password", "") or "") or ""
            item["auth_protocol"] = item.pop("snmp_auth_protocol", "SHA") or "SHA"
            item["security_level"] = item.pop("snmp_security_level", "authPriv") or "authPriv"
            item["priv_protocol"] = item.pop("snmp_priv_protocol", "AES") or "AES"
            item["context_name"] = item.pop("snmp_context_name", "") or ""
            item["priv_password"] = decrypt_credential(item.pop("snmp_priv_password", "") or "") or ""
            item["auth_password"] = decrypt_credential(item.pop("snmp_auth_password", "") or "") or ""
            if item.get("auth_password"):
                item["password"] = item["auth_password"]
            credentials.append(item)
    except Exception:
        pass
    aliases = {str(item["id"]): opaque_auth_alias(str(item["id"])) for item in credentials if item.get("id")}
    for device in devices:
        device.setdefault("collector_id", collector_id)
        # The vault is the sole credential resolution boundary.  Do not read
        # device-local communities directly when a credential binding exists.
        try:
            resolved = resolve_collector_credentials(device)
            # SNMP credentials are independent from SSH credentials. Never
            # fall back to the device's management credential here.
            credential_id = str(device.get("snmp_credential_id") or "")
            resolved_community = str((resolved.get("snmp") or {}).get("community") or "")
            if not credential_id and resolved_community:
                # Legacy/device-local SNMP Community is a valid alternative to
                # a credential-center binding. Keep it ephemeral and opaque so
                # the plaintext secret never enters assignments or the DB.
                asset_key = str(device.get("asset_id") or device.get("id") or "")
                credential_id = f"inline-snmp-{opaque_auth_alias(asset_key)}"
                device["snmp_credential_id"] = credential_id
                credentials.append({
                    "id": credential_id,
                    "credential_type": "snmpv2",
                    "community": resolved_community,
                })
                aliases[credential_id] = opaque_auth_alias(credential_id)
            if credential_id:
                for item in credentials:
                    if str(item.get("id") or "") == credential_id:
                        item["community"] = resolved_community or str(item.get("community") or "")
                        break
        except Exception:
            # A legacy/incomplete CMDB row is left for the compiler to mark as
            # unconfigured; no plaintext fallback is introduced here.
            pass
    return devices, plans, modules, variants, collectors, credentials, aliases, servers


@router.post("/collectors/{collector_id}/compile")
def compile_collector(collector_id: str, body: CompileRequest | None = None, _user=require_role("Operator")):
    compile_started = time.perf_counter()
    compile_succeeded = False
    assignment_count = 0
    conn = get_db_connection()
    try:
        collector = conn.execute("SELECT * FROM monitoring_collectors WHERE id = ?", (collector_id,)).fetchone()
        if not collector:
            raise HTTPException(status_code=404, detail="Collector not found")
        inputs = _load_compile_inputs(conn, collector_id, _user)
        assignments = build_assignments(*inputs[:5], credential_aliases=inputs[6])
        assignment_count = len(assignments)
        validation_errors = validate_assignments(assignments)
        if validation_errors:
            raise HTTPException(status_code=422, detail={"code": "COMPILE_FAILED", "errors": validation_errors})
        version_row = conn.execute("SELECT COALESCE(MAX(config_version), 0) AS version FROM monitoring_config_versions WHERE collector_id = ?", (collector_id,)).fetchone()
        requested = body.config_version if body else None
        version = int(requested or ((version_row["version"] if version_row else 0) or 0) + 1)
        used_credentials = {str(item.get("credential_id") or "") for item in assignments}
        artifact_credentials = [item for item in inputs[5] if str(item.get("id") or "") in used_credentials]
        artifact_root = os.environ.get("MONITORING_ARTIFACT_ROOT") or os.path.join(os.getcwd(), "artifacts", "monitoring")
        artifact = compile_artifact(
            assignments,
            collector_id=collector_id,
            config_version=version,
            credentials=artifact_credentials,
            modules=inputs[2],
            variants=inputs[3],
            servers=inputs[7],
            output_root=artifact_root,
        )
        validate_artifact(artifact)
        manifest = artifact["manifest"]
        now = _now()
        config_id = f"config-{uuid.uuid4().hex[:16]}"
        conn.execute("UPDATE monitoring_collection_assignments SET enabled = 0, updated_at = ? WHERE collector_id = ?", (now, collector_id))
        for assignment in assignments:
            conn.execute(
                """INSERT INTO monitoring_collection_assignments
                   (id, asset_id, collector_id, module_variant_id, credential_id, auth_alias,
                    interval_seconds, scrape_timeout_seconds, enabled, source_type, source_plan_id,
                    assignment_hash, last_compiled_at, last_config_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (id) DO UPDATE SET enabled = 1, last_compiled_at = excluded.last_compiled_at,
                     last_config_version = excluded.last_config_version, updated_at = excluded.updated_at""",
                (assignment["id"], assignment["asset_id"], assignment["collector_id"], assignment["module_variant_id"], assignment.get("credential_id", ""), assignment.get("auth_alias", ""), assignment["interval_seconds"], assignment["scrape_timeout_seconds"], assignment["source_type"], assignment["source_plan_id"], assignment["assignment_hash"], now, version, now, now),
            )
        snapshot_json = json.dumps(artifact["snapshot"], ensure_ascii=False, sort_keys=True)
        # A compiled artifact is not Last Known Good until the collector
        # validation/publish step succeeds; the previous snapshot remains the
        # runtime fallback while this version is being reviewed.
        conn.execute("INSERT INTO monitoring_target_snapshots (id, collector_id, config_version, snapshot_json, checksum, is_last_known_good, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)", (f"snapshot-{uuid.uuid4().hex[:16]}", collector_id, version, snapshot_json, manifest["checksum"], now))
        conn.execute("INSERT INTO monitoring_config_versions (id, collector_id, config_version, status, artifact_path, manifest_json, checksum, created_at) VALUES (?, ?, ?, 'COMPILED', ?, ?, ?, ?)", (config_id, collector_id, version, artifact.get("artifact_path") or "", json.dumps(manifest, ensure_ascii=False), manifest["checksum"], now))
        conn.execute("UPDATE monitoring_collectors SET last_config_version = ?, last_config_status = 'COMPILED', updated_at = ? WHERE id = ?", (version, now, collector_id))
        conn.commit()
        compile_succeeded = True
        _audit(_user, "MONITORING_CONFIG_COMPILED", f"Compiled monitoring config {collector_id} v{version}", target_type="monitoring_config", target_id=f"{collector_id}:{version}", details={"collector_id": collector_id, "config_version": version, "assignment_count": len(assignments), "duration_ms": round((time.perf_counter() - compile_started) * 1000, 2), "status": "COMPILED"})
        return {"status": "COMPILED", "collector_id": collector_id, "config_version": version, "assignment_count": len(assignments), "manifest": manifest, "artifact_path": artifact.get("artifact_path")}
    except HTTPException:
        raise
    except CompileError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Config compile failed: {exc}") from exc
    finally:
        metrics_registry.record_monitoring_compile(success=compile_succeeded, assignment_count=assignment_count)
        conn.close()


@router.post("/collectors/{collector_id}/rollback")
def rollback_collector(collector_id: str, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT config_version FROM monitoring_config_versions WHERE collector_id = ? AND status IN ('APPLIED', 'COMPILED') ORDER BY config_version DESC LIMIT 2", (collector_id,)).fetchall()
        if len(rows) < 2:
            raise HTTPException(status_code=409, detail="No previous collector configuration is available")
        target = int(rows[1]["config_version"])
        current_config = conn.execute("SELECT artifact_path FROM monitoring_config_versions WHERE collector_id = ? AND config_version = ?", (collector_id, int(rows[0]["config_version"]))).fetchone()
        target_path = conn.execute("SELECT artifact_path FROM monitoring_config_versions WHERE collector_id = ? AND config_version = ?", (collector_id, target)).fetchone()
        artifact_path = str((current_config or {}).get("artifact_path") if hasattr(current_config, "get") else (current_config[0] if current_config else "") or "")
        target_artifact_path = str((target_path or {}).get("artifact_path") if hasattr(target_path, "get") else (target_path[0] if target_path else "") or "")
        if artifact_path and target_artifact_path:
            try:
                CollectorArtifactStore(str(Path(artifact_path).parent)).rollback()
            except ArtifactStoreError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            exporter_reload = _reload_snmp_exporter_config()
        else:
            exporter_reload = None
        now = _now()
        conn.execute("UPDATE monitoring_config_versions SET status = 'ROLLED_BACK', rolled_back_at = ? WHERE collector_id = ? AND config_version > ?", (now, collector_id, target))
        conn.execute("UPDATE monitoring_config_versions SET status = 'APPLIED', applied_at = ? WHERE collector_id = ? AND config_version = ?", (now, collector_id, target))
        conn.execute("UPDATE monitoring_target_snapshots SET is_last_known_good = CASE WHEN config_version = ? THEN 1 ELSE 0 END WHERE collector_id = ?", (target, collector_id))
        conn.execute("UPDATE monitoring_collectors SET last_config_version = ?, last_config_status = 'ROLLED_BACK', updated_at = ? WHERE id = ?", (target, now, collector_id))
        conn.commit()
        _audit(_user, "MONITORING_CONFIG_ROLLED_BACK", f"Rolled back monitoring config {collector_id} to v{target}", target_type="monitoring_config", target_id=f"{collector_id}:{target}", details={"collector_id": collector_id, "config_version": target, "status": "ROLLED_BACK"})
        return {"status": "ROLLED_BACK", "collector_id": collector_id, "config_version": target, "snmp_exporter_reload": exporter_reload}
    finally:
        conn.close()


@router.get("/collectors/{collector_id}/configs")
def list_collector_configs(collector_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT id, collector_id, config_version, status, artifact_path, manifest_json, checksum, error_code, error_message, created_at, applied_at, rolled_back_at FROM monitoring_config_versions WHERE collector_id = ? ORDER BY config_version DESC", (collector_id,)).fetchall()
        result = []
        for row in rows:
            item = _dict(row)
            item["manifest"] = _parse_json(item.pop("manifest_json", "{}"), {})
            result.append(item)
        return {"items": result}
    finally:
        conn.close()


@router.get("/collectors/{collector_id}/snapshot")
def collector_target_snapshot(collector_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT collector_id, config_version, snapshot_json, checksum, is_last_known_good, created_at
                 FROM monitoring_target_snapshots
                WHERE collector_id = ?
                ORDER BY is_last_known_good DESC, config_version DESC LIMIT 1""",
            (collector_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Collector target snapshot not found")
        item = _dict(row)
        item["targets"] = _parse_json(item.pop("snapshot_json", "[]"), [])
        return item
    finally:
        conn.close()


@router.post("/collectors/{collector_id}/publish")
def publish_collector(collector_id: str, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        latest = conn.execute("SELECT config_version, artifact_path FROM monitoring_config_versions WHERE collector_id = ? ORDER BY config_version DESC LIMIT 1", (collector_id,)).fetchone()
        if not latest:
            raise HTTPException(status_code=409, detail="Compile a collector configuration before publishing")
        version = int(latest["config_version"])
        artifact_path = str(latest.get("artifact_path") or "") if hasattr(latest, "get") else str(latest[1] or "")
        if artifact_path:
            try:
                CollectorArtifactStore(str(Path(artifact_path).parent)).publish(artifact_path, config_version=version)
            except ArtifactStoreError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            exporter_reload = _reload_snmp_exporter_config()
        else:
            exporter_reload = None
        now = _now()
        conn.execute("UPDATE monitoring_config_versions SET status = 'APPLIED', applied_at = ? WHERE collector_id = ? AND config_version = ?", (now, collector_id, version))
        conn.execute("UPDATE monitoring_target_snapshots SET is_last_known_good = CASE WHEN config_version = ? THEN 1 ELSE 0 END WHERE collector_id = ?", (version, collector_id))
        conn.execute("UPDATE monitoring_collectors SET status = 'ONLINE', last_config_status = 'APPLIED', last_config_version = ?, last_config_applied_at = ?, updated_at = ? WHERE id = ?", (version, now, now, collector_id))
        conn.commit()
        _audit(_user, "MONITORING_CONFIG_PUBLISHED", f"Published monitoring config {collector_id} v{version}", target_type="monitoring_config", target_id=f"{collector_id}:{version}", details={"collector_id": collector_id, "config_version": version, "status": "APPLIED"})
        return {"status": "APPLIED", "collector_id": collector_id, "config_version": version, "snmp_exporter_reload": exporter_reload}
    finally:
        conn.close()


@router.get("/metrics/latest")
def metrics_latest(asset_id: str, metric_key: str, provider: str | None = Query(default=None), _user=require_role("Viewer")):
    _assert_asset_visible(asset_id, _user)
    started = time.perf_counter()
    try:
        result = provider_from_environment(mode=provider).latest(asset_id=asset_id, metric_key=metric_key)
        metrics_registry.record_monitoring_query((time.perf_counter() - started) * 1000, success=result.get("status", "success") != "error")
        return result
    except ValueError as exc:
        metrics_registry.record_monitoring_query((time.perf_counter() - started) * 1000, success=False)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/metrics/range")
def metrics_range(asset_id: str, metric_key: str, hours: int = Query(default=24, ge=1, le=720), step_seconds: int = Query(default=60, ge=1, le=86400), provider: str | None = Query(default=None), _user=require_role("Viewer")):
    _assert_asset_visible(asset_id, _user)
    end = datetime.now(timezone.utc)
    started = time.perf_counter()
    try:
        result = provider_from_environment(mode=provider).range(query=metric_key, metric_key=metric_key, asset_id=asset_id, start=end - timedelta(hours=hours), end=end, step_seconds=step_seconds)
        metrics_registry.record_monitoring_query((time.perf_counter() - started) * 1000, success=result.get("status", "success") != "error")
        return result
    except ValueError as exc:
        metrics_registry.record_monitoring_query((time.perf_counter() - started) * 1000, success=False)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/metrics/device")
def metrics_device(asset_id: str, metric_key: str = "cpu_usage_percent", provider: str | None = Query(default=None), _user=require_role("Viewer")):
    provider_value = provider if isinstance(provider, str) else None
    return metrics_latest(asset_id=asset_id, metric_key=metric_key, provider=provider_value, _user=_user)


@router.get("/metrics/interface")
def metrics_interface(asset_id: str, metric_key: str = "interface_rx_bps", hours: int = Query(default=24, ge=1, le=720), provider: str | None = Query(default=None), _user=require_role("Viewer")):
    hours_value = hours if isinstance(hours, int) and not isinstance(hours, bool) else 24
    provider_value = provider if isinstance(provider, str) else None
    return metrics_range(asset_id=asset_id, metric_key=metric_key, hours=hours_value, provider=provider_value, _user=_user)


@router.get("/metrics/availability")
def metrics_availability(asset_id: str, metric_key: str, provider: str | None = Query(default=None), window_seconds: int = Query(default=300, ge=1, le=86400), _user=require_role("Viewer")):
    _assert_asset_visible(asset_id, _user)
    try:
        return provider_from_environment(mode=provider).availability(asset_id=asset_id, metric_key=metric_key, window_seconds=window_seconds)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/collection-health")
def collection_health(collector_id: str | None = Query(default=None), _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        clauses, params = ["1=1"], []
        tenant = _tenant_id(_user)
        if tenant is not None:
            clauses.append("COALESCE(d.tenant_id, 'tenant-default') = ?")
            params.append(tenant)
        if collector_id:
            clauses.append("a.collector_id = ?")
            params.append(collector_id)
        rows = conn.execute(
            f"""SELECT a.id, a.asset_id, a.collector_id, a.module_variant_id, a.interval_seconds, a.enabled,
                       a.last_compiled_at, d.status AS device_health,
                       cs.status AS collection_status, cs.last_success_at, cs.error_code
                FROM monitoring_collection_assignments a
                JOIN devices d ON d.id = a.asset_id
                LEFT JOIN LATERAL (
                    SELECT status, last_attempt_at, last_success_at, duration_ms, consecutive_failures, error_code
                      FROM device_collection_status
                     WHERE device_id = a.asset_id AND collector LIKE 'snmp_%'
                     ORDER BY updated_at DESC LIMIT 1
                ) cs ON TRUE
               WHERE {' AND '.join(clauses)}
               ORDER BY a.collector_id, a.asset_id, a.module_variant_id""",
            tuple(params),
        ).fetchall()
        items = []
        for row in rows:
            item = _dict(row)
            item["error_code"] = item.pop("error_code", "") or ("COLLECTION_FAILED" if str(item.pop("collection_status", "")).lower() == "failed" else "")
            items.append(classify_collection_health(item))
        return {"items": items, "summary": summarize_collection_health(items), "provider": str(os.environ.get("MONITORING_METRIC_BACKEND", "native")).lower()}
    finally:
        conn.close()


@router.get("/reports/data")
def get_monitoring_report_data(
    report_type: str = Query(default="interfaces"),
    keyword: str | None = Query(default=None),
    vendor: str | None = Query(default=None),
    site: str | None = Query(default=None),
    role: str | None = Query(default=None),
    status: str | None = Query(default=None),
    min_util: float | None = Query(default=None),
    has_errors: bool | None = Query(default=None),
    high_load_only: bool | None = Query(default=None),
    isp: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    _user=require_role("Viewer"),
):
    filters = {
        "tenant_id": None if str(_user.get("role") or "") == "Administrator" else str(_user.get("tenant_id") or "tenant-default"),
        "keyword": keyword,
        "vendor": vendor,
        "site": site,
        "role": role,
        "status": status,
        "min_util": min_util,
        "has_errors": has_errors,
        "high_load_only": high_load_only,
        "isp": isp,
        "target_type": target_type,
    }
    if report_type == "devices":
        return fetch_devices_report_data(filters=filters)
    elif report_type == "outbound":
        return fetch_outbound_report_data(filters=filters)
    return fetch_interfaces_report_data(filters=filters)


@router.get("/export/interfaces")
def export_interfaces_report(
    format: str = Query(default="xlsx"),
    keyword: str | None = Query(default=None),
    vendor: str | None = Query(default=None),
    site: str | None = Query(default=None),
    role: str | None = Query(default=None),
    status: str | None = Query(default=None),
    min_util: float | None = Query(default=None),
    has_errors: bool | None = Query(default=None),
    _user=require_role("Viewer"),
):
    filters = {
        "tenant_id": None if str(_user.get("role") or "") == "Administrator" else str(_user.get("tenant_id") or "tenant-default"),
        "keyword": keyword,
        "vendor": vendor,
        "site": site,
        "role": role,
        "status": status,
        "min_util": min_util,
        "has_errors": has_errors,
    }
    content, filename, media_type = generate_interfaces_report(format_type=format, filters=filters)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/export/devices")
def export_devices_report(
    format: str = Query(default="xlsx"),
    keyword: str | None = Query(default=None),
    vendor: str | None = Query(default=None),
    site: str | None = Query(default=None),
    role: str | None = Query(default=None),
    status: str | None = Query(default=None),
    high_load_only: bool | None = Query(default=None),
    _user=require_role("Viewer"),
):
    filters = {
        "tenant_id": None if str(_user.get("role") or "") == "Administrator" else str(_user.get("tenant_id") or "tenant-default"),
        "keyword": keyword,
        "vendor": vendor,
        "site": site,
        "role": role,
        "status": status,
        "high_load_only": high_load_only,
    }
    content, filename, media_type = generate_devices_report(format_type=format, filters=filters)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/export/outbound")
def export_outbound_report(
    format: str = Query(default="xlsx"),
    keyword: str | None = Query(default=None),
    isp: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    _user=require_role("Viewer"),
):
    filters = {
        "tenant_id": None if str(_user.get("role") or "") == "Administrator" else str(_user.get("tenant_id") or "tenant-default"),
        "keyword": keyword,
        "isp": isp,
        "target_type": target_type,
    }
    content, filename, media_type = generate_outbound_report(format_type=format, filters=filters)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/shadow-comparisons")
def shadow_comparisons(asset_id: str | None = Query(default=None), metric_key: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=1000), _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        clauses, params = ["1=1"], []
        tenant = _tenant_id(_user)
        if tenant is not None:
            clauses.append("COALESCE(d.tenant_id, 'tenant-default') = ?")
            params.append(tenant)
        if asset_id:
            clauses.append("s.asset_id = ?")
            params.append(asset_id)
        if metric_key:
            clauses.append("s.metric_key = ?")
            params.append(metric_key)
        params.append(limit)
        rows = conn.execute(
            f"""SELECT s.id, s.asset_id, s.metric_key, s.native_value, s.vm_value, s.delta,
                       s.tolerance, s.status, s.sampled_at
                  FROM monitoring_shadow_comparisons s
                  LEFT JOIN devices d ON d.id = s.asset_id
                 WHERE {' AND '.join(clauses)}
                 ORDER BY s.sampled_at DESC LIMIT ?""",
            tuple(params),
        ).fetchall()
        return {"items": [_dict(row) for row in rows]}
    finally:
        conn.close()


@router.post("/shadow-comparisons/run")
def run_shadow_compare(asset_id: str, _user=require_role("Operator")):
    _assert_asset_visible(asset_id, _user)
    provider = provider_from_environment(mode="shadow")
    if not isinstance(provider, ShadowMetricProvider):
        raise HTTPException(status_code=500, detail="Shadow provider is unavailable")
    return {"asset_id": asset_id, "items": provider.compare_metrics(asset_id=asset_id)}
