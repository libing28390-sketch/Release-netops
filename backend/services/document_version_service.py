"""V1 document-revision API.

This module keeps the historical import name for callers while the persisted
version facts live in ``ai_document_revision``.  It intentionally contains no
dependency on the retired document/version tables.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from typing import Any

from core.rbac import authorize_resource
from database import get_db_connection
from services.knowledge_v1_source_service import (
    SourceRegistryError,
    _decode_revision,
    get_source,
    record_document_version as _record_document_version,
)


_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class DocumentVersionError(ValueError):
    """Stable, user-safe document revision error."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _tenant(user: dict[str, Any]) -> str:
    tenant_id = str(user.get("tenant_id") or "tenant-default").strip()
    if not tenant_id or len(tenant_id) > 256 or _CONTROL_RE.search(tenant_id):
        raise DocumentVersionError("DOCUMENT_TENANT_INVALID", "tenant_id is invalid")
    return tenant_id


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_load(value: Any, default: Any = None) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return default if default is not None else {}
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default if default is not None else {}


def _row_dict(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    return dict(row)


def _decode_v1(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = _json_load(result.pop("metadata_json", None), {})
    result["source_metadata"] = _json_load(result.pop("source_metadata_json", None), {})
    result["fetch_metadata"] = _json_load(result.pop("fetch_metadata_json", None), {})
    result["version_no"] = int(
        (result["metadata"] or {}).get("document_version_no", result.get("revision_no") or 1)
        if isinstance(result["metadata"], dict)
        else (result.get("revision_no") or 1)
    )
    result["lifecycle_status"] = _text(result.get("lifecycle_status") or result.get("status"))
    result["document_version_id"] = _text(result.get("id"))
    result["source_version_id"] = _text(result.get("legacy_source_version_id"))
    result["source_registry_id"] = _text(result.get("legacy_source_id"))
    if not _text(result.get("original_content")):
        result["original_content_ref"] = f"source-version://{_text(result.get('legacy_source_version_id') or result.get('id'))}"
    return result


def _raise(exc: BaseException) -> None:
    if isinstance(exc, DocumentVersionError):
        raise exc
    if isinstance(exc, SourceRegistryError):
        raise DocumentVersionError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc
    raise exc


def record_document_version(
    source: dict[str, Any],
    source_version: dict[str, Any],
    user: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    original_content: str | bytes | None = None,
    normalized_content: str | None = None,
    collection_id: str | None = None,
    document_kind: str = "official_manual",
) -> dict[str, Any]:
    del collection_id
    source_tenant = _text(source.get("tenant_id"))
    actor_tenant = _tenant(user)
    if source_tenant and source_tenant != actor_tenant:
        raise DocumentVersionError("DOCUMENT_TENANT_CONFLICT", "source and actor tenant do not match", status_code=403)
    try:
        return _record_document_version(
            source,
            source_version,
            user,
            metadata=metadata,
            original_content=original_content,
            normalized_content=normalized_content,
            document_kind=document_kind,
        )
    except Exception as exc:  # preserve the former stable error contract
        _raise(exc)
        raise AssertionError("unreachable")


def list_document_versions(document_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    tenant_id = _tenant(user)
    if not authorize_resource(user, "knowledge_source", "read", tenant_id=tenant_id):
        raise DocumentVersionError("DOCUMENT_PERMISSION_DENIED", "Insufficient permission for document revision read", status_code=403)
    document_id = _text(document_id)
    if not document_id:
        raise DocumentVersionError("DOCUMENT_ID_REQUIRED", "document_id is required")
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? "
            "AND record_type = 'document_revision' ORDER BY revision_no DESC, created_at DESC, id DESC",
            (tenant_id, document_id),
        ).fetchall()
        return [_decode_v1(_row_dict(row) or {}) for row in rows]


def compare_document_versions(
    document_id: str,
    left_version_id: str,
    right_version_id: str,
    user: dict[str, Any],
) -> dict[str, Any]:
    tenant_id = _tenant(user)
    if not authorize_resource(user, "knowledge_source", "read", tenant_id=tenant_id):
        raise DocumentVersionError("DOCUMENT_PERMISSION_DENIED", "Insufficient permission for document revision read", status_code=403)
    document_id = _text(document_id)
    left_id = _text(left_version_id)
    right_id = _text(right_version_id)
    if not document_id or not left_id or not right_id:
        raise DocumentVersionError("DOCUMENT_COMPARE_INPUT_INVALID", "document_id and two revision ids are required")
    if left_id == right_id:
        raise DocumentVersionError("DOCUMENT_COMPARE_SAME_VERSION", "two different versions are required")
    with get_db_connection() as conn:
        rows: list[dict[str, Any]] = []
        for version_id in (left_id, right_id):
            row = _row_dict(conn.execute(
                "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? "
                "AND id = ? AND record_type = 'document_revision'",
                (tenant_id, document_id, version_id),
            ).fetchone())
            if not row:
                raise DocumentVersionError("DOCUMENT_VERSION_NOT_FOUND", "document revision was not found", status_code=404)
            rows.append(row)

    def summary(row: dict[str, Any]) -> dict[str, Any]:
        metadata = _json_load(row.get("metadata_json"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "id": _text(row.get("id")),
            "version_no": int(row.get("revision_no") or 0),
            "status": _text(row.get("status")),
            "lifecycle_status": _text(row.get("lifecycle_status") or row.get("status")),
            "content_hash": _text(row.get("content_hash")),
            "metadata_hash": hashlib.sha256(json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest(),
            "normalized_content_hash": _text(row.get("normalized_content_hash")),
            "byte_size": int(row.get("byte_size") or 0),
            "parser_name": _text(row.get("parser_name")),
            "parser_version": _text(row.get("parser_version")),
            "trust_level": _text(_json_load(row.get("source_metadata_json"), {}).get("trust_level") if isinstance(_json_load(row.get("source_metadata_json"), {}), dict) else ""),
            "metadata_keys": sorted(str(key) for key in metadata.keys())[:100],
            "created_at": row.get("created_at"),
        }

    left, right = rows
    left_summary, right_summary = summary(left), summary(right)
    comparable = ("content_hash", "metadata_hash", "normalized_content_hash", "byte_size", "parser_name", "parser_version", "trust_level", "metadata_keys")
    changed_fields = [field for field in comparable if left_summary.get(field) != right_summary.get(field)]
    left_content = str(left.get("normalized_content") or "")
    right_content = str(right.get("normalized_content") or "")
    max_diff_bytes = 2 * 1024 * 1024
    if len(left_content.encode("utf-8")) <= max_diff_bytes and len(right_content.encode("utf-8")) <= max_diff_bytes:
        left_lines, right_lines = left_content.splitlines(), right_content.splitlines()
        matcher = difflib.SequenceMatcher(a=left_lines, b=right_lines, autojunk=False)
        added = removed = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in {"replace", "delete"}:
                removed += i2 - i1
            if tag in {"replace", "insert"}:
                added += j2 - j1
        diff_available = True
    else:
        left_lines = right_lines = []
        added = removed = 0
        diff_available = False
    return {
        "document_id": document_id,
        "left": left_summary,
        "right": right_summary,
        "changed_fields": changed_fields,
        "content_changed": left_summary["content_hash"] != right_summary["content_hash"],
        "metadata_changed": left_summary["metadata_hash"] != right_summary["metadata_hash"],
        "line_diff": {
            "available": diff_available,
            "left_lines": len(left_lines),
            "right_lines": len(right_lines),
            "added_lines": added,
            "removed_lines": removed,
        },
        "raw_content_included": False,
    }


__all__ = ["DocumentVersionError", "record_document_version", "list_document_versions", "compare_document_versions"]
