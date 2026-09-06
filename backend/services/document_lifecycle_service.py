"""V1 document lifecycle operations backed by ``ai_document``.

Lifecycle events are retained as bounded records in ``ai_document_revision``;
there is no separate document-lifecycle table in the single-track model.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import database as _database
from core.rbac import authorize_resource
from database import get_db_connection
from services.audit_service import log_audit_event
from services.document_version_service import list_document_versions


_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
LIFECYCLE_STATUSES = {"draft", "published", "quarantined", "superseded", "disabled", "active", "archived", "deleted", "purged", "failed"}
_STATUS_PROJECTION = {
    "draft": "draft", "published": "active", "quarantined": "quarantined",
    "superseded": "archived", "disabled": "disabled", "active": "active",
    "archived": "archived", "deleted": "deleted", "purged": "purged", "failed": "draft",
}
_ALLOWED_TRANSITIONS = {
    "draft": {"published", "quarantined", "disabled"},
    "published": {"quarantined", "superseded", "disabled"},
    "active": {"published", "quarantined", "superseded", "disabled"},
    "quarantined": {"published", "disabled"},
    "disabled": {"published", "quarantined"},
    "archived": {"published", "disabled"},
    "failed": {"draft", "quarantined", "disabled"},
    "deleted": {"published"},
    "superseded": set(),
    "purged": set(),
}


class DocumentLifecycleError(ValueError):
    """Stable, bounded lifecycle error returned to API callers."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tenant(user: dict[str, Any]) -> str:
    tenant = str(user.get("tenant_id") or "tenant-default").strip()
    if not tenant or len(tenant) > 256 or _CONTROL_RE.search(tenant):
        raise DocumentLifecycleError("DOCUMENT_TENANT_INVALID", "tenant_id is invalid")
    return tenant


def _actor(user: dict[str, Any]) -> str:
    actor = str(user.get("id") or user.get("user_id") or user.get("username") or "system").strip()
    if not actor or len(actor) > 256 or _CONTROL_RE.search(actor):
        raise DocumentLifecycleError("DOCUMENT_ACTOR_INVALID", "actor is invalid")
    return actor


def _text(value: Any, *, field: str, maximum: int = 512, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_FIELD_REQUIRED", f"{field} is required")
    if len(text) > maximum or _CONTROL_RE.search(text):
        raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_FIELD_INVALID", f"{field} is invalid")
    return text


def _json_load(value: Any, default: Any = None) -> Any:
    if isinstance(value, (dict, list)):
        return value
    adapted = getattr(value, "adapted", None)
    if adapted is not None and adapted is not value:
        return _json_load(adapted, default)
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return default if default is not None else {}


def _db_json(value: dict[str, Any]) -> Any:
    if _database._USE_PG:
        try:
            from psycopg2.extras import Json

            return Json(value, dumps=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str))
        except ImportError:
            pass
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _row_dict(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    return dict(row)


def _decode(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    result = dict(row)
    for key in ("metadata_json", "acl_json"):
        if key in result:
            result[key[:-5]] = _json_load(result.pop(key), {})
    result["lifecycle_status"] = str(result.get("lifecycle_status") or result.get("status") or "draft")
    result["retrieval_eligible"] = result["lifecycle_status"] in {"published", "active"} and str(result.get("status") or "") == "active"
    return result


def _authorize(user: dict[str, Any], tenant_id: str, action: str) -> None:
    if not authorize_resource(user, "knowledge_source", action, tenant_id=tenant_id):
        raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_PERMISSION_DENIED", "Insufficient permission for document lifecycle operation", status_code=403)


def _table_columns(conn, table: str) -> set[str]:
    cursor = conn.execute(f"SELECT * FROM {table} WHERE 1 = 0")
    return {str(item[0]) for item in (cursor.description or ())}


def _event_summary(*, event_id: str, document: dict[str, Any], version: dict[str, Any], operation: str, from_status: str, to_status: str, request_id: str, idempotent: bool = False) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "request_id": request_id,
        "document_id": str(document.get("id") or ""),
        "document_version_id": str(version.get("id") or ""),
        "operation": operation,
        "from_status": from_status,
        "to_status": to_status,
        "idempotent": idempotent,
    }


def _audit(user: dict[str, Any], tenant_id: str, summary: dict[str, Any]) -> None:
    try:
        log_audit_event(
            event_type="document_lifecycle_transition",
            category="knowledge_document",
            severity="warning" if summary.get("to_status") == "quarantined" else "info",
            status="success",
            summary="Knowledge document lifecycle transition recorded",
            actor_id=_actor(user),
            actor_username=str(user.get("username") or _actor(user))[:256],
            actor_role=str(user.get("role") or "system")[:64],
            target_type="knowledge_document",
            target_id=summary.get("document_id"),
            request_id=summary.get("request_id"),
            details={"tenant_id": tenant_id, **summary},
        )
    except Exception:
        return


def _revision(conn, tenant_id: str, document_id: str, version_id: str = "") -> dict[str, Any] | None:
    params: list[Any] = [tenant_id, document_id]
    clause = ""
    if version_id:
        clause = " AND id = ?"
        params.append(version_id)
    row = conn.execute(
        "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? "
        "AND record_type = 'document_revision'" + clause + " ORDER BY revision_no DESC, created_at DESC, id DESC LIMIT 1",
        tuple(params),
    ).fetchone()
    return _row_dict(row)


def _record_lifecycle_event(conn, *, tenant_id: str, document: dict[str, Any], version: dict[str, Any], summary: dict[str, Any], reason: str, actor: str, now: str) -> None:
    row = conn.execute(
        "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM ai_document_revision WHERE tenant_id = ? AND document_id = ?",
        (tenant_id, str(document.get("id") or "")),
    ).fetchone()
    revision_no = max(1, int(row[0] or 1))
    event_id = str(summary.get("event_id") or ("v1life-" + uuid.uuid4().hex))
    metadata = {"event": summary, "reason": reason}
    values = {
        "id": event_id,
        "tenant_id": tenant_id,
        "document_id": str(document.get("id") or ""),
        "revision_no": revision_no,
        "canonical_url": str(document.get("canonical_url") or document.get("source") or ""),
        "source_kind": str(document.get("source_kind") or ""),
        "fetch_url": "",
        "content_hash": "",
        "normalized_content_hash": "",
        "original_content": "",
        "normalized_content": "",
        "metadata_json": _db_json(metadata),
        "source_metadata_json": _db_json({}),
        "fetch_metadata_json": _db_json({}),
        "parser_name": "",
        "parser_version": "",
        "cleaner_name": "",
        "cleaner_version": "",
        "mime_type": "",
        "byte_size": 0,
        "source_etag": "",
        "source_last_modified": "",
        "http_status": None,
        "fetched_at": now,
        "status": "observed",
        "lifecycle_status": str(summary.get("to_status") or ""),
        "lifecycle_reason": reason,
        "is_current": False if _database._USE_PG else 0,
        "legacy_source_id": "",
        "legacy_source_version_id": "",
        "legacy_document_id": str(document.get("id") or ""),
        "legacy_document_version_id": str(version.get("id") or ""),
        "created_at": now,
        "created_by": actor,
        "record_type": "lifecycle_event",
        "observation_outcome": "",
        "detection_type": "none",
        "error_code": "",
        "replacement_url": "",
        "request_method": "",
        "checked_at": None,
        "source_observation_id": "",
        "legacy_action_id": "",
    }
    names = list(values)
    conn.execute(
        f"INSERT INTO ai_document_revision ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
        tuple(values[name] for name in names),
    )


def get_document_lifecycle(document_id: str, user: dict[str, Any]) -> dict[str, Any]:
    tenant_id = _tenant(user)
    _authorize(user, tenant_id, "read")
    document_id = _text(document_id, field="document_id", maximum=256, required=True)
    with get_db_connection() as conn:
        document = _row_dict(conn.execute("SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?", (tenant_id, document_id)).fetchone())
        if not document:
            raise DocumentLifecycleError("DOCUMENT_NOT_FOUND", "document was not found", status_code=404)
        version = _revision(conn, tenant_id, document_id)
        events = conn.execute(
            "SELECT id, metadata_json, lifecycle_status, lifecycle_reason, created_by, created_at "
            "FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? AND record_type = 'lifecycle_event' "
            "ORDER BY created_at DESC, id DESC LIMIT 50",
            (tenant_id, document_id),
        ).fetchall()
        decoded_events = []
        for row in events:
            value = _row_dict(row) or {}
            metadata = _json_load(value.get("metadata_json"), {})
            event = metadata.get("event") if isinstance(metadata, dict) and isinstance(metadata.get("event"), dict) else {}
            decoded_events.append({**event, "id": value.get("id"), "reason": value.get("lifecycle_reason"), "actor_id": value.get("created_by"), "created_at": value.get("created_at")})
        return {"document": _decode(document), "document_version": _decode_revision(version), "events": decoded_events}


def _decode_revision(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    result = dict(row)
    result["metadata"] = _json_load(result.pop("metadata_json", None), {})
    result["source_metadata"] = _json_load(result.pop("source_metadata_json", None), {})
    result["fetch_metadata"] = _json_load(result.pop("fetch_metadata_json", None), {})
    result["document_version_id"] = str(result.get("id") or "")
    result["version_no"] = int(result.get("revision_no") or 1)
    result["lifecycle_status"] = str(result.get("lifecycle_status") or result.get("status") or "draft")
    return result


def transition_document_lifecycle(
    document_id: str,
    target_status: str,
    user: dict[str, Any],
    *,
    document_version_id: str | None = None,
    expected_status: str | None = None,
    expected_updated_at: str | None = None,
    reason: str = "",
    request_id: str | None = None,
    replacement_version_id: str | None = None,
) -> dict[str, Any]:
    tenant_id = _tenant(user)
    _authorize(user, tenant_id, "update")
    document_id = _text(document_id, field="document_id", maximum=256, required=True)
    target = _text(target_status, field="target_status", maximum=32, required=True).lower()
    if target not in {"draft", "published", "quarantined", "superseded", "disabled"}:
        raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_STATUS_INVALID", "target lifecycle status is not allowlisted")
    reason = _text(reason, field="reason", maximum=2_000)
    request = _text(request_id or str(uuid.uuid4()), field="request_id", maximum=256, required=True)
    requested_version_id = _text(document_version_id or "", field="document_version_id", maximum=256)
    replacement_id = _text(replacement_version_id or "", field="replacement_version_id", maximum=256)
    expected = _text(expected_status or "", field="expected_status", maximum=32)
    expected_updated = _text(expected_updated_at or "", field="expected_updated_at", maximum=128)
    actor = _actor(user)
    now = _now()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        prior = cursor.execute(
            "SELECT metadata_json FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? "
            "AND record_type = 'lifecycle_event' AND CAST(metadata_json AS TEXT) LIKE ? "
            "ORDER BY created_at DESC LIMIT 1",
            (tenant_id, document_id, f'%request_id%{request}%'),
        ).fetchone()
        document = _row_dict(cursor.execute("SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?", (tenant_id, document_id)).fetchone())
        if not document:
            raise DocumentLifecycleError("DOCUMENT_NOT_FOUND", "document was not found", status_code=404)
        version = _revision(cursor, tenant_id, document_id, requested_version_id)
        if not version:
            raise DocumentLifecycleError("DOCUMENT_VERSION_NOT_FOUND", "document revision was not found", status_code=404)
        if prior:
            value = _json_load(prior[0], {})
            summary = value.get("event") if isinstance(value, dict) and isinstance(value.get("event"), dict) else {}
            summary["idempotent"] = True
            conn.rollback()
            return {"document": _decode(document), "document_version": _decode_revision(version), "event": summary, "idempotent": True}
        current = str(document.get("lifecycle_status") or document.get("status") or "draft").lower()
        if expected and current != expected.lower():
            raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_STALE", "document lifecycle status changed", status_code=409, details={"expected_status": expected, "actual_status": current})
        if expected_updated and str(document.get("updated_at") or "") != expected_updated:
            raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_STALE", "document was changed by another request", status_code=409)
        if target == "superseded" and not replacement_id:
            raise DocumentLifecycleError("DOCUMENT_REPLACEMENT_REQUIRED", "superseded transition requires replacement_version_id", status_code=409)
        if target != current and target not in _ALLOWED_TRANSITIONS.get(current, set()):
            raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_TRANSITION_INVALID", "requested lifecycle transition is not allowed", status_code=409, details={"from_status": current, "to_status": target})
        replacement = None
        if target == "superseded":
            replacement = _revision(cursor, tenant_id, document_id, replacement_id)
            if not replacement or replacement_id == str(version.get("id") or ""):
                raise DocumentLifecycleError("DOCUMENT_REPLACEMENT_INVALID", "replacement revision is invalid", status_code=409)
            replacement_state = str(replacement.get("lifecycle_status") or replacement.get("status") or "").lower()
            if replacement_state not in {"published", "active"}:
                raise DocumentLifecycleError("DOCUMENT_REPLACEMENT_INVALID", "replacement revision must be published", status_code=409)
        if target == current and target not in {"published", "disabled", "quarantined"}:
            raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_NOOP", "requested lifecycle transition is not applicable", status_code=409)
        # ``superseded`` is a state of the selected revision, not of the
        # document identity: the replacement remains the document's active
        # projection.  Other transitions project directly to ai_document.
        document_target = "published" if target == "superseded" else target
        projected_version = replacement if target == "superseded" and replacement else version
        projected = _STATUS_PROJECTION[document_target]
        columns = _table_columns(conn, "ai_document")
        fields: dict[str, Any] = {"status": projected, "lifecycle_status": document_target, "lifecycle_revision": int(document.get("lifecycle_revision") or 0) + 1, "lifecycle_changed_at": now, "lifecycle_changed_by": actor, "lifecycle_reason": reason, "updated_at": now}
        if document_target == "published":
            fields["current_version_id"] = projected_version.get("id")
            fields["content_hash"] = projected_version.get("normalized_content_hash") or projected_version.get("content_hash")
            fields["normalized_content"] = projected_version.get("normalized_content") or ""
            fields["original_content"] = projected_version.get("original_content") or ""
            fields["metadata_json"] = _db_json(_json_load(projected_version.get("metadata_json"), {}) if isinstance(_json_load(projected_version.get("metadata_json"), {}), dict) else {})
        filtered = {key: value for key, value in fields.items() if key in columns}
        assignments = ", ".join(f"{key} = ?" for key in filtered)
        updated = cursor.execute(
            f"UPDATE ai_document SET {assignments} WHERE tenant_id = ? AND id = ? AND lifecycle_revision = ?",
            tuple(filtered.values()) + (tenant_id, document_id, int(document.get("lifecycle_revision") or 0)),
        ).rowcount
        if updated != 1:
            raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_STALE", "document was changed by another request", status_code=409)
        if target == "published":
            cursor.execute("UPDATE ai_document_revision SET is_current = ? WHERE tenant_id = ? AND document_id = ? AND record_type = 'document_revision'", (False if _database._USE_PG else 0, tenant_id, document_id))
            cursor.execute("UPDATE ai_document_revision SET is_current = ?, status = 'active', lifecycle_status = 'published' WHERE tenant_id = ? AND id = ?", (True if _database._USE_PG else 1, tenant_id, str(version.get("id") or "")))
        else:
            version_status = "archived" if target == "superseded" else projected
            cursor.execute(
                "UPDATE ai_document_revision SET is_current = ?, status = ?, lifecycle_status = ?, lifecycle_reason = ? "
                "WHERE tenant_id = ? AND id = ?",
                (
                    False if _database._USE_PG else 0,
                    version_status,
                    target,
                    reason,
                    tenant_id,
                    str(version.get("id") or ""),
                ),
            )
        event_id = "v1life-" + uuid.uuid4().hex
        summary = _event_summary(event_id=event_id, document=document, version=version, operation="publish" if target == "published" else target, from_status=current, to_status=target, request_id=request)
        _record_lifecycle_event(conn, tenant_id=tenant_id, document=document, version=version, summary=summary, reason=reason, actor=actor, now=now)
        document = _row_dict(cursor.execute("SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?", (tenant_id, document_id)).fetchone()) or document
        version = _revision(cursor, tenant_id, document_id, str(version.get("id") or "")) or version
        conn.commit()
    _audit(user, tenant_id, summary)
    return {"document": _decode(document), "document_version": _decode_revision(version), "event": summary, "idempotent": False}


def rollback_document_version(
    document_id: str,
    target_version_id: str,
    user: dict[str, Any],
    *,
    reason: str = "",
    request_id: str | None = None,
) -> dict[str, Any]:
    tenant_id = _tenant(user)
    _authorize(user, tenant_id, "update")
    document_id = _text(document_id, field="document_id", maximum=256, required=True)
    target_version_id = _text(target_version_id, field="target_version_id", maximum=256, required=True)
    request = _text(request_id or str(uuid.uuid4()), field="request_id", maximum=256, required=True)
    actor = _actor(user)
    now = _now()
    reason = _text(reason, field="reason", maximum=2_000)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        document = _row_dict(cursor.execute("SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?", (tenant_id, document_id)).fetchone())
        target = _revision(cursor, tenant_id, document_id, target_version_id)
        if not document:
            raise DocumentLifecycleError("DOCUMENT_NOT_FOUND", "document was not found", status_code=404)
        if not target:
            raise DocumentLifecycleError("DOCUMENT_VERSION_NOT_FOUND", "document revision was not found", status_code=404)
        prior = cursor.execute(
            "SELECT metadata_json FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? "
            "AND record_type = 'lifecycle_event' AND CAST(metadata_json AS TEXT) LIKE ? "
            "ORDER BY created_at DESC LIMIT 1",
            (tenant_id, document_id, f'%request_id%{request}%'),
        ).fetchone()
        if prior:
            value = _json_load(prior[0], {})
            summary = value.get("event") if isinstance(value, dict) and isinstance(value.get("event"), dict) else {}
            summary["idempotent"] = True
            conn.rollback()
            return {
                "document": _decode(document),
                "document_version": _decode_revision(target),
                "event": summary,
                "idempotent": True,
            }
        if str(target.get("status") or "") in {"observed", "failed", "quarantined", "disabled"}:
            raise DocumentLifecycleError("DOCUMENT_ROLLBACK_TARGET_INVALID", "rollback target is not publishable", status_code=409)
        columns = _table_columns(conn, "ai_document")
        fields: dict[str, Any] = {"status": "active", "lifecycle_status": "published", "lifecycle_revision": int(document.get("lifecycle_revision") or 0) + 1, "lifecycle_changed_at": now, "lifecycle_changed_by": actor, "lifecycle_reason": reason, "updated_at": now, "current_version_id": target_version_id, "content_hash": target.get("normalized_content_hash") or target.get("content_hash"), "normalized_content": target.get("normalized_content") or "", "original_content": target.get("original_content") or ""}
        metadata = _json_load(target.get("metadata_json"), {})
        if isinstance(metadata, dict):
            fields["metadata_json"] = _db_json(metadata)
        filtered = {key: value for key, value in fields.items() if key in columns}
        assignments = ", ".join(f"{key} = ?" for key in filtered)
        if cursor.execute(f"UPDATE ai_document SET {assignments} WHERE tenant_id = ? AND id = ?", tuple(filtered.values()) + (tenant_id, document_id)).rowcount != 1:
            raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_STALE", "document was changed by another request", status_code=409)
        cursor.execute("UPDATE ai_document_revision SET is_current = ? WHERE tenant_id = ? AND document_id = ? AND record_type = 'document_revision'", (False if _database._USE_PG else 0, tenant_id, document_id))
        cursor.execute("UPDATE ai_document_revision SET is_current = ?, status = 'active', lifecycle_status = 'published' WHERE tenant_id = ? AND id = ?", (True if _database._USE_PG else 1, tenant_id, target_version_id))
        summary = _event_summary(event_id="v1life-" + uuid.uuid4().hex, document=document, version=target, operation="rollback", from_status=str(document.get("lifecycle_status") or document.get("status") or "draft"), to_status="published", request_id=request)
        _record_lifecycle_event(conn, tenant_id=tenant_id, document=document, version=target, summary=summary, reason=reason, actor=actor, now=now)
        document = _row_dict(cursor.execute("SELECT * FROM ai_document WHERE tenant_id = ? AND id = ?", (tenant_id, document_id)).fetchone()) or document
        target = _revision(cursor, tenant_id, document_id, target_version_id) or target
        conn.commit()
    _audit(user, tenant_id, summary)
    return {"document": _decode(document), "document_version": _decode_revision(target), "event": summary, "idempotent": False}


def list_document_lifecycle_events(document_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    return list(get_document_lifecycle(document_id, user).get("events") or [])


__all__ = ["DocumentLifecycleError", "LIFECYCLE_STATUSES", "get_document_lifecycle", "transition_document_lifecycle", "rollback_document_version", "list_document_lifecycle_events"]
