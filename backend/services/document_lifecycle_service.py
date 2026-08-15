"""Tenant-scoped lifecycle transitions for the V2 Document boundary (ING-015)."""

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


_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
LIFECYCLE_STATUSES = {
    "draft",
    "published",
    "quarantined",
    "superseded",
    "disabled",
    "active",
    "archived",
    "deleted",
    "purged",
    "failed",
}
_TERMINAL = {"purged", "superseded"}
_STATUS_PROJECTION = {
    "draft": "draft",
    "published": "active",
    "quarantined": "quarantined",
    "superseded": "archived",
    "disabled": "disabled",
    "active": "active",
    "archived": "archived",
    "deleted": "deleted",
    "purged": "purged",
    "failed": "failed",
}
_ALLOWED_TRANSITIONS = {
    "draft": {"published", "quarantined", "disabled"},
    "published": {"quarantined", "superseded", "disabled"},
    "quarantined": {"published", "disabled"},
    "disabled": {"published", "quarantined"},
    "active": {"published", "quarantined", "superseded", "disabled"},
    "archived": {"published", "disabled"},
    "deleted": {"published"},
    "superseded": set(),
    "purged": {"purged"},
    "failed": {"draft", "quarantined", "disabled"},
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
    value = str(user.get("id") or user.get("user_id") or user.get("username") or "system").strip()
    if not value or len(value) > 256 or _CONTROL_RE.search(value):
        raise DocumentLifecycleError("DOCUMENT_ACTOR_INVALID", "actor is invalid")
    return value


def _text(value: Any, *, field: str, maximum: int = 512, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_FIELD_REQUIRED", f"{field} is required")
    if len(text) > maximum or _CONTROL_RE.search(text):
        raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_FIELD_INVALID", f"{field} is invalid")
    return text


def _json_load(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _db_json(value: dict[str, Any]) -> Any:
    if _database._USE_PG:
        try:
            from psycopg2.extras import Json

            return Json(value, dumps=_json_dump)
        except ImportError:
            pass
    return _json_dump(value)


def _row_dict(row) -> dict[str, Any] | None:
    return dict(row) if row else None


def _decode(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    result = dict(row)
    for key in ("metadata_json", "acl_json"):
        if key in result:
            result[key[:-5]] = _json_load(result.pop(key), {})
    result["lifecycle_status"] = str(result.get("lifecycle_status") or result.get("status") or "draft")
    result["retrieval_eligible"] = result["lifecycle_status"] == "published"
    return result


def _authorize(user: dict[str, Any], tenant_id: str, action: str) -> None:
    if not authorize_resource(user, "knowledge_source", action, tenant_id=tenant_id):
        raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_PERMISSION_DENIED", "Insufficient permission for document lifecycle operation", status_code=403)


def _event_summary(*, event_id: str, document: dict[str, Any], version: dict[str, Any], operation: str, from_status: str, to_status: str, idempotent: bool = False) -> dict[str, Any]:
    return {
        "event_id": event_id,
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
            severity="warning" if summary["to_status"] == "quarantined" else "info",
            status="success",
            summary="Knowledge document lifecycle transition recorded",
            actor_id=_actor(user),
            actor_username=str(user.get("username") or _actor(user))[:256],
            actor_role=str(user.get("role") or "system")[:64],
            resource_type="kb_document",
            resource_id=summary["document_id"],
            tenant_id=tenant_id,
            details={
                "event_id": summary["event_id"],
                "document_version_id": summary["document_version_id"],
                "operation": summary["operation"],
                "from_status": summary["from_status"],
                "to_status": summary["to_status"],
            },
        )
    except Exception:
        # The transition is already durable; audit-provider failure must not
        # expose internals or make an immutable lifecycle decision disappear.
        return


def _transition_fields(target: str, *, actor: str, now: str, reason: str, replacement_version_id: str | None) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "lifecycle_status": target,
        "lifecycle_changed_at": now,
        "lifecycle_changed_by": actor,
        "lifecycle_reason": reason,
    }
    if target == "published":
        fields.update({"published_at": now, "published_by": actor, "approved_at": now, "approved_by": actor})
    elif target == "quarantined":
        fields.update({"quarantined_at": now, "quarantined_by": actor, "quarantine_reason": reason})
    elif target == "superseded":
        fields.update({"superseded_at": now, "superseded_by": actor, "superseded_by_version_id": replacement_version_id or ""})
    elif target == "disabled":
        fields.update({"disabled_at": now, "disabled_by": actor, "disable_reason": reason})
    return fields


def _projected_status(target: str) -> str:
    try:
        return _STATUS_PROJECTION[target]
    except KeyError as exc:
        raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_STATUS_INVALID", "lifecycle status is not allowlisted") from exc


def get_document_lifecycle(document_id: str, user: dict[str, Any]) -> dict[str, Any]:
    tenant_id = _tenant(user)
    _authorize(user, tenant_id, "read")
    document_id = _text(document_id, field="document_id", maximum=256, required=True)
    with get_db_connection() as conn:
        document = _row_dict(conn.execute("SELECT * FROM kb_document WHERE tenant_id = ? AND id = ?", (tenant_id, document_id)).fetchone())
        if not document:
            raise DocumentLifecycleError("DOCUMENT_NOT_FOUND", "document was not found", status_code=404)
        version = _row_dict(conn.execute(
            "SELECT * FROM kb_document_version WHERE tenant_id = ? AND document_id = ? ORDER BY version_no DESC LIMIT 1",
            (tenant_id, document_id),
        ).fetchone())
        events = conn.execute(
            "SELECT id, request_id, operation, from_status, to_status, reason, actor_id, created_at FROM kb_document_lifecycle_event WHERE tenant_id = ? AND document_id = ? ORDER BY created_at DESC LIMIT 50",
            (tenant_id, document_id),
        ).fetchall()
        return {
            "document": _decode(document),
            "document_version": _decode(version),
            "events": [_row_dict(row) or {} for row in events],
        }


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
    """Perform one tenant/CAS/idempotent lifecycle transition."""
    tenant_id = _tenant(user)
    _authorize(user, tenant_id, "update")
    document_id = _text(document_id, field="document_id", maximum=256, required=True)
    target = _text(target_status, field="target_status", maximum=32, required=True).lower()
    if target not in {"draft", "published", "quarantined", "superseded", "disabled"}:
        raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_STATUS_INVALID", "target lifecycle status is not allowlisted")
    reason = _text(reason, field="reason", maximum=2_000)
    request = _text(request_id or str(uuid.uuid4()), field="request_id", maximum=256, required=True)
    version_id = _text(document_version_id or "", field="document_version_id", maximum=256)
    replacement_id = _text(replacement_version_id or "", field="replacement_version_id", maximum=256)
    expected = _text(expected_status or "", field="expected_status", maximum=32)
    expected_updated = _text(expected_updated_at or "", field="expected_updated_at", maximum=128)
    actor = _actor(user)
    now = _now()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        prior = cursor.execute(
            "SELECT result_json FROM kb_document_lifecycle_event WHERE tenant_id = ? AND request_id = ?",
            (tenant_id, request),
        ).fetchone()
        if prior:
            summary = _json_load(prior[0], {})
            if not isinstance(summary, dict):
                raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_EVENT_INVALID", "lifecycle event record is invalid", status_code=409)
            document = _row_dict(cursor.execute("SELECT * FROM kb_document WHERE tenant_id = ? AND id = ?", (tenant_id, document_id)).fetchone())
            if not document:
                raise DocumentLifecycleError("DOCUMENT_NOT_FOUND", "document was not found", status_code=404)
            version = _row_dict(cursor.execute("SELECT * FROM kb_document_version WHERE tenant_id = ? AND id = ?", (tenant_id, summary.get("document_version_id"))).fetchone()) or {}
            summary["idempotent"] = True
            return {"document": _decode(document), "document_version": _decode(version), "event": summary, "idempotent": True}

        document = _row_dict(cursor.execute("SELECT * FROM kb_document WHERE tenant_id = ? AND id = ?", (tenant_id, document_id)).fetchone())
        if not document:
            raise DocumentLifecycleError("DOCUMENT_NOT_FOUND", "document was not found", status_code=404)
        selected_version = _row_dict(cursor.execute(
            "SELECT * FROM kb_document_version WHERE tenant_id = ? AND document_id = ? AND (? = '' OR id = ?) ORDER BY version_no DESC LIMIT 1",
            (tenant_id, document_id, version_id, version_id),
        ).fetchone())
        if not selected_version:
            raise DocumentLifecycleError("DOCUMENT_VERSION_NOT_FOUND", "document version was not found", status_code=404)
        if str(selected_version.get("document_id") or "") != document_id:
            raise DocumentLifecycleError("DOCUMENT_VERSION_SCOPE_CONFLICT", "document version is outside the document scope", status_code=403)
        current = str(selected_version.get("lifecycle_status") or selected_version.get("status") or "draft").lower()
        if expected and current != expected.lower():
            raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_STALE", "document lifecycle status changed", status_code=409, details={"expected_status": expected, "actual_status": current})
        if expected_updated and str(document.get("updated_at") or "") != expected_updated:
            raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_STALE", "document was changed by another request", status_code=409)
        if target == "superseded" and not replacement_id:
            raise DocumentLifecycleError("DOCUMENT_REPLACEMENT_REQUIRED", "superseded transition requires replacement_version_id")
        if target == current:
            if target != "published" and target != "disabled" and target != "quarantined":
                raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_NOOP", "requested lifecycle transition is not applicable", status_code=409)
        elif target not in _ALLOWED_TRANSITIONS.get(current, set()):
            raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_TRANSITION_INVALID", "requested lifecycle transition is not allowed", status_code=409, details={"from_status": current, "to_status": target})
        if current in _TERMINAL and target != current:
            raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_TERMINAL", "terminal lifecycle state cannot be changed", status_code=409)
        if target == "superseded":
            replacement = _row_dict(cursor.execute(
                "SELECT * FROM kb_document_version WHERE tenant_id = ? AND id = ? AND document_id = ?",
                (tenant_id, replacement_id, document_id),
            ).fetchone())
            if not replacement or replacement_id == str(selected_version.get("id") or ""):
                raise DocumentLifecycleError("DOCUMENT_REPLACEMENT_INVALID", "replacement version is invalid", status_code=409)
            replacement_status = str(replacement.get("lifecycle_status") or replacement.get("status") or "draft").lower()
            if replacement_status != "published":
                raise DocumentLifecycleError("DOCUMENT_REPLACEMENT_NOT_PUBLISHED", "replacement version must be published", status_code=409)

        projected = _projected_status(target)
        fields = _transition_fields(target, actor=actor, now=now, reason=reason, replacement_version_id=replacement_id or None)
        fields["status"] = projected
        fields["lifecycle_revision"] = int(selected_version.get("lifecycle_revision") or 0) + 1
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values())
        version_id_value = str(selected_version.get("id") or "")
        updated_version = cursor.execute(
            f"UPDATE kb_document_version SET {assignments}, updated_at = ?, updated_by = ? WHERE tenant_id = ? AND id = ? AND lifecycle_revision = ? AND lifecycle_status = ?",
            (*values, now, actor, tenant_id, version_id_value, int(selected_version.get("lifecycle_revision") or 0), current),
        ).rowcount
        if updated_version != 1:
            raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_STALE", "document version was changed by another request", status_code=409)

        document_target = target
        document_replacement = None
        if target == "superseded":
            replacement_row = _row_dict(cursor.execute("SELECT * FROM kb_document_version WHERE tenant_id = ? AND id = ?", (tenant_id, replacement_id)).fetchone()) or {}
            document_target = str(replacement_row.get("lifecycle_status") or "published")
            document_replacement = replacement_id
        document_current = str(document.get("lifecycle_status") or document.get("status") or "draft").lower()
        document_fields = _transition_fields(document_target, actor=actor, now=now, reason=reason, replacement_version_id=document_replacement)
        document_fields.pop("approved_at", None)
        document_fields.pop("approved_by", None)
        document_fields["status"] = _projected_status(document_target)
        document_fields["lifecycle_revision"] = int(document.get("lifecycle_revision") or 0) + 1
        doc_assignments = ", ".join(f"{key} = ?" for key in document_fields)
        doc_values = list(document_fields.values())
        updated_document = cursor.execute(
            f"UPDATE kb_document SET {doc_assignments}, updated_at = ?, updated_by = ? WHERE tenant_id = ? AND id = ? AND lifecycle_revision = ?",
            (*doc_values, now, actor, tenant_id, document_id, int(document.get("lifecycle_revision") or 0)),
        ).rowcount
        if updated_document != 1:
            raise DocumentLifecycleError("DOCUMENT_LIFECYCLE_STALE", "document was changed by another request", status_code=409)

        event_id = str(uuid.uuid4())
        operation = "publish" if target == "published" else target
        summary = _event_summary(event_id=event_id, document=document, version=selected_version, operation=operation, from_status=current, to_status=target)
        cursor.execute(
            "INSERT INTO kb_document_lifecycle_event (id, tenant_id, document_id, document_version_id, request_id, operation, from_status, to_status, reason, actor_id, created_at, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, tenant_id, document_id, version_id_value, request, operation, current, target, reason, actor, now, _db_json(summary)),
        )
        document = _row_dict(cursor.execute("SELECT * FROM kb_document WHERE tenant_id = ? AND id = ?", (tenant_id, document_id)).fetchone()) or document
        selected_version = _row_dict(cursor.execute("SELECT * FROM kb_document_version WHERE tenant_id = ? AND id = ?", (tenant_id, version_id_value)).fetchone()) or selected_version
        conn.commit()
    decoded_document = _decode(document) or {}
    decoded_version = _decode(selected_version) or {}
    summary["idempotent"] = False
    _audit(user, tenant_id, summary)
    return {"document": decoded_document, "document_version": decoded_version, "event": summary, "idempotent": False}


def list_document_lifecycle_events(document_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    result = get_document_lifecycle(document_id, user)
    return list(result.get("events") or [])


__all__ = [
    "DocumentLifecycleError",
    "LIFECYCLE_STATUSES",
    "get_document_lifecycle",
    "transition_document_lifecycle",
    "list_document_lifecycle_events",
]
