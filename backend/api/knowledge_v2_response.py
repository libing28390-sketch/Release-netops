"""Shared pagination and error response primitives for stable API contracts."""

from __future__ import annotations

import math
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field


class PaginationQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1, le=100_000)
    page_size: int = Field(default=20, ge=1, le=100)
    sort_by: str = Field(default="created_at", min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    sort_order: Literal["asc", "desc"] = "desc"


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    sort_by: str
    sort_order: Literal["asc", "desc"]


# Stable list projections.  Detail-only fields must never be added to a list
# response by accident: documents expose bodies/chunks through the document
# detail endpoint, while source versions and refresh observations expose only
# bounded operational facts.  Keep these as tuples (rather than a permissive
# blacklist) so a newly added service column cannot silently become public API.
DOCUMENT_SUMMARY_FIELDS: tuple[str, ...] = (
    "id", "knowledge_base_id", "name", "source", "vendor", "platform",
    "cli_platform", "document_id", "document_category", "product_family",
    "product_series", "product_model", "os_family", "os_generation",
    "software_train", "software_release", "feature_domain", "feature",
    "subfeature", "risk_level", "verification_level", "rag_priority",
    "metadata_parse_status", "exclude_from_rag", "status",
    "knowledge_source_type", "tenant_id", "acl", "source_trust_level",
    "created_at", "chunk_count",
)

SOURCE_SUMMARY_FIELDS: tuple[str, ...] = (
    "id", "tenant_id", "source_type", "source_kind", "name", "description",
    "canonical_url", "allowed_host", "trust_level", "status", "fetch_enabled",
    "validation_status", "created_at", "updated_at",
)

SOURCE_VERSION_SUMMARY_FIELDS: tuple[str, ...] = (
    "id", "tenant_id", "source_registry_id", "fetched_at", "content_hash",
    "byte_size", "parser_name", "parser_version", "source_etag",
    "source_last_modified", "fetch_url", "response_content_type", "http_status",
    "verification_method", "error_code", "status", "created_at", "updated_at",
)

REFRESH_OBSERVATION_SUMMARY_FIELDS: tuple[str, ...] = (
    "id", "tenant_id", "source_registry_id", "source_version_id", "checked_at",
    "request_method", "http_status", "outcome", "content_hash", "byte_size",
    "source_etag", "source_last_modified", "fetch_url", "response_content_type",
    "error_code", "detection_type", "replacement_url", "version_signal",
)


def project_summary(item: Mapping[str, Any], *, fields: Sequence[str]) -> dict[str, Any]:
    """Project one service row into an explicit, detail-free list summary."""

    return {field: item[field] for field in fields if field in item}


def project_summary_items(
    payload: Mapping[str, Any],
    *,
    item_key: str = "items",
    fields: Sequence[str],
) -> dict[str, Any]:
    """Project a list nested in a response while preserving its envelope."""

    result = dict(payload)
    values = payload.get(item_key) or []
    result[item_key] = [project_summary(item, fields=fields) for item in values if isinstance(item, Mapping)]
    return result


def paginate_items(
    items: Iterable[Mapping[str, Any]],
    *,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    allowed_sort_fields: set[str] | frozenset[str] = frozenset({"created_at"}),
) -> tuple[list[dict[str, Any]], PaginationMeta]:
    """Sort and page an already tenant-filtered list with a safe field allowlist."""

    normalized_page = max(1, int(page))
    normalized_size = min(100, max(1, int(page_size)))
    normalized_sort = str(sort_by or "created_at").strip().lower()
    if normalized_sort not in allowed_sort_fields:
        normalized_sort = "created_at"
    normalized_order = "asc" if str(sort_order).lower() == "asc" else "desc"
    rows = [dict(item) for item in items]
    rows.sort(key=lambda row: (str(row.get(normalized_sort) or "").lower(), str(row.get("id") or "")), reverse=normalized_order == "desc")
    total = len(rows)
    total_pages = max(1, math.ceil(total / normalized_size))
    actual_page = min(normalized_page, total_pages)
    start = (actual_page - 1) * normalized_size
    end = start + normalized_size
    return rows[start:end], PaginationMeta(
        page=actual_page,
        page_size=normalized_size,
        total=total,
        total_pages=total_pages,
        sort_by=normalized_sort,
        sort_order=normalized_order,
    )


def attach_pagination(payload: dict[str, Any], meta: PaginationMeta, *, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Add additive response metadata without changing existing data fields."""

    result = dict(payload)
    result["meta"] = {
        "pagination": meta.model_dump(),
        "filters": {key: value for key, value in (filters or {}).items() if value not in (None, "", [], {})},
    }
    return result


def is_stable_api_path(path: str) -> bool:
    return path.startswith(("/api/v2/kb", "/api/knowledge-v2", "/api/v1/ai", "/api/ai"))


def stable_error_payload(status_code: int, detail: Any, *, request_id: str = "") -> dict[str, Any]:
    if isinstance(detail, dict):
        code = str(detail.get("code") or _status_code(status_code))
        message = str(detail.get("message") or detail.get("detail") or "请求失败")
        details = detail.get("details")
    else:
        code = _status_code(status_code)
        message = str(detail or "请求失败")
        details = None
    error: dict[str, Any] = {"code": code, "message": message, "request_id": request_id or None}
    if details is not None:
        error["details"] = details
    return {"success": False, "error": error, "detail": message}


def _status_code(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "AUTHENTICATION_REQUIRED",
        403: "PERMISSION_DENIED",
        404: "RESOURCE_NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
    }.get(status_code, "API_ERROR")


__all__ = [
    "PaginationQuery", "PaginationMeta", "DOCUMENT_SUMMARY_FIELDS",
    "SOURCE_SUMMARY_FIELDS", "SOURCE_VERSION_SUMMARY_FIELDS",
    "REFRESH_OBSERVATION_SUMMARY_FIELDS", "project_summary",
    "project_summary_items", "paginate_items", "attach_pagination",
    "is_stable_api_path", "stable_error_payload",
]
