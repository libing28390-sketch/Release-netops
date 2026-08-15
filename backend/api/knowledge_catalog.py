"""CAT-013 Product Catalog and Alias management read boundary."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from core.rbac import require_permission
from database import get_db_connection
from services.audit_service import log_audit_event
from services.catalog_version_service import (
    CatalogVersionError,
    import_catalog_version,
    list_catalog_versions,
    preview_catalog_version,
    rollback_catalog_version,
)
from services.product_catalog_service import (
    ProductCatalogError,
    list_product_aliases,
    list_product_catalog,
    resolve_product_alias_dry_run,
)


router = APIRouter(prefix="/knowledge-v2/catalog", tags=["knowledge-v2-product-catalog"])
logger = logging.getLogger(__name__)


class CatalogResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=256)
    limit: int = Field(default=20, ge=1, le=50)


class CatalogVersionBundleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(..., min_length=1, max_length=64)
    models: list[dict[str, Any]] = Field(..., min_length=1, max_length=5000)
    aliases: list[dict[str, Any]] = Field(..., max_length=10000)


class CatalogVersionImportRequest(CatalogVersionBundleRequest):
    expected_active_version_id: str = Field(default="", max_length=128)
    confirm: bool = False


class CatalogVersionRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_active_version_id: str = Field(default="", max_length=128)
    confirm: bool = False


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ProductCatalogError, CatalogVersionError) as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Knowledge product catalog operation failed")
        raise HTTPException(status_code=500, detail={"code": "CATALOG_ERROR", "message": "Product catalog operation failed"}) from exc


def _audit_version_operation(user: dict[str, Any], operation: str, details: dict[str, Any]) -> str:
    """Persist a redacted CAT-015 audit event before version state is committed."""
    conn = get_db_connection()
    try:
        event_id = log_audit_event(
            event_type=f"catalog_version_{operation}",
            category="knowledge_catalog",
            severity="info",
            status="success",
            summary=f"Knowledge catalog version {operation}",
            actor_id=str(user.get("id") or user.get("user_id") or user.get("username") or "system"),
            actor_username=str(user.get("username") or user.get("id") or "system"),
            actor_role=str(user.get("role") or "system"),
            target_type="knowledge_catalog_version",
            target_id=str(details.get("after_version_id") or details.get("before_version_id") or ""),
            details=details,
            conn=conn,
        )
        conn.commit()
        return event_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("")
@router.get("/")
def api_list_catalog(
    vendor_id: str = Query(default="", max_length=64),
    family_code: str = Query(default="", max_length=64),
    series_code: str = Query(default="", max_length=64),
    model: str = Query(default="", max_length=128),
    software_version: str = Query(default="", max_length=128),
    status: str = Query(default="all", max_length=32),
    user=require_permission("knowledge_catalog", "read"),
):
    return {"success": True, "data": _call(list_product_catalog, user, vendor_id=vendor_id, family_code=family_code, series_code=series_code, model=model, software_version=software_version, status=status), "message": ""}


@router.get("/aliases")
def api_list_catalog_aliases(
    alias: str = Query(default="", max_length=256),
    alias_kind: str = Query(default="", max_length=32),
    conflict_status: str = Query(default="all", max_length=64),
    user=require_permission("knowledge_catalog", "read"),
):
    return {"success": True, "data": _call(list_product_aliases, user, alias=alias, alias_kind=alias_kind, conflict_status=conflict_status), "message": ""}


@router.post("/resolve")
def api_resolve_catalog_alias(payload: CatalogResolveRequest = Body(...), user=require_permission("knowledge_catalog", "resolve")):
    return {"success": True, "data": _call(resolve_product_alias_dry_run, user, payload.query, limit=payload.limit), "message": "Alias dry-run completed"}


@router.get("/versions")
def api_list_catalog_versions(user=require_permission("knowledge_catalog", "read")):
    return {"success": True, "data": _call(list_catalog_versions, user), "message": ""}


@router.post("/versions/preview")
def api_preview_catalog_version(payload: CatalogVersionBundleRequest = Body(...), user=require_permission("knowledge_catalog", "review")):
    return {"success": True, "data": _call(preview_catalog_version, user, payload.model_dump()), "message": "Catalog version diff preview completed"}


@router.post("/versions/import")
def api_import_catalog_version(payload: CatalogVersionImportRequest = Body(...), user=require_permission("knowledge_catalog", "import")):
    data = payload.model_dump()
    return {
        "success": True,
        "data": _call(
            import_catalog_version,
            user,
            {"version": data["version"], "models": data["models"], "aliases": data["aliases"]},
            expected_active_version_id=data["expected_active_version_id"],
            confirm=data["confirm"],
            audit_writer=lambda operation, details: _audit_version_operation(user, operation, details),
        ),
        "message": "Catalog version imported",
    }


@router.post("/versions/{version_id}/rollback")
def api_rollback_catalog_version(
    version_id: str = Path(..., min_length=1, max_length=128),
    payload: CatalogVersionRollbackRequest = Body(...),
    user=require_permission("knowledge_catalog", "rollback"),
):
    return {
        "success": True,
        "data": _call(
            rollback_catalog_version,
            user,
            version_id,
            expected_active_version_id=payload.expected_active_version_id,
            confirm=payload.confirm,
            audit_writer=lambda operation, details: _audit_version_operation(user, operation, details),
        ),
        "message": "Catalog version rolled back",
    }
