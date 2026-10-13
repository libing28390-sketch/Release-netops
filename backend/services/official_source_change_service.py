"""Apply official-source change signals on the V1 knowledge projection.

Source-change evidence is stored in ``ai_document_revision``. The same row
also carries bounded application state so quarantine can be retried without
bringing back the retired V2 action tables.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from core.rbac import authorize_resource
from database import get_db_connection
from services.document_lifecycle_service import DocumentLifecycleError, transition_document_lifecycle
from services.knowledge_v1_source_service import (
    SourceRegistryError,
    get_source,
    quarantine_source_for_change,
)


_OFFICIAL_KINDS = {
    "official_url", "product_page", "configuration_guide", "command_reference",
    "release_note", "troubleshooting_guide", "product_support",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _actor(user: dict[str, Any]) -> str:
    return str(user.get("id") or user.get("user_id") or user.get("username") or "system")[:256]


def _safe_code(value: Any, default: str) -> str:
    code = str(value or default).strip().upper()
    return code[:128] if code.replace("_", "").isalnum() else default


def _json_load(value: Any, default: Any = None) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return default if default is not None else {}


def _db_json(value: dict[str, Any]) -> Any:
    try:
        from database import _USE_PG

        if _USE_PG:
            from psycopg2.extras import Json

            return Json(value, dumps=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str))
    except ImportError:
        pass
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _is_official(source: dict[str, Any]) -> bool:
    return (
        str(source.get("source_type") or "").startswith("official_")
        or str(source.get("source_kind") or "") in _OFFICIAL_KINDS
    )


def _observation_state(source: dict[str, Any], observation_id: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not observation_id:
        return None, {}
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM ai_document_revision WHERE tenant_id = ? AND id = ? "
            "AND record_type = 'source_observation' LIMIT 1",
            (str(source.get("tenant_id") or ""), observation_id),
        ).fetchone()
        if not row:
            return None, {}
        item = {str(key): row[key] for key in row.keys()} if hasattr(row, "keys") else dict(row)
    metadata = _json_load(item.get("metadata_json"), {})
    return item, metadata if isinstance(metadata, dict) else {}


def _write_observation_state(source: dict[str, Any], observation_id: str, state: dict[str, Any]) -> None:
    if not observation_id:
        return
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT metadata_json FROM ai_document_revision WHERE tenant_id = ? AND id = ? "
            "AND record_type = 'source_observation' LIMIT 1",
            (str(source.get("tenant_id") or ""), observation_id),
        ).fetchone()
        if not row:
            return
        existing = _json_load(row[0], {})
        metadata = dict(existing) if isinstance(existing, dict) else {}
        metadata["change_application"] = {
            "status": str(state.get("status") or "failed")[:32],
            "attempt_count": max(0, int(state.get("attempt_count") or 0)),
            "last_error_code": _safe_code(state.get("last_error_code"), "") if state.get("last_error_code") else "",
            "updated_at": str(state.get("updated_at") or _now())[:128],
            "applied_at": str(state.get("applied_at") or "")[:128],
        }
        conn.execute(
            "UPDATE ai_document_revision SET metadata_json = ? WHERE tenant_id = ? AND id = ?",
            (_db_json(metadata), str(source.get("tenant_id") or ""), observation_id),
        )
        conn.commit()


def _claim_observation(source: dict[str, Any], observation_id: str) -> tuple[dict[str, Any], str]:
    row, metadata = _observation_state(source, observation_id)
    if not row:
        return {"status": "applying", "attempt_count": 1, "last_error_code": "", "updated_at": _now()}, "claimed"
    previous = metadata.get("change_application") if isinstance(metadata.get("change_application"), dict) else {}
    if str(previous.get("status") or "") == "applied":
        return dict(previous), "applied"
    state = {
        "status": "applying",
        "attempt_count": int(previous.get("attempt_count") or 0) + 1,
        "last_error_code": "",
        "updated_at": _now(),
    }
    _write_observation_state(source, observation_id, state)
    return state, "claimed"


def _finish_observation(source: dict[str, Any], observation_id: str, state: dict[str, Any], *, status: str, error_code: str = "") -> dict[str, Any]:
    finished = dict(state)
    finished.update({
        "status": status,
        "last_error_code": _safe_code(error_code, "") if error_code else "",
        "updated_at": _now(),
        "applied_at": _now() if status == "applied" else "",
    })
    _write_observation_state(source, observation_id, finished)
    return finished


def _linked_documents(source: dict[str, Any]) -> list[dict[str, Any]]:
    tenant_id = str(source.get("tenant_id") or "")
    source_id = str(source.get("id") or "")
    source_document_id = str(source.get("source_document_id") or source_id)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT d.id, d.status, d.lifecycle_status FROM ai_document AS d "
            "WHERE d.tenant_id = ? AND ("
            "d.id = ? OR CAST(d.metadata_json AS TEXT) LIKE ? OR EXISTS ("
            "SELECT 1 FROM ai_document_revision AS r "
            "WHERE r.tenant_id = d.tenant_id AND r.document_id = d.id "
            "AND r.record_type = 'document_revision' "
            "AND (r.legacy_source_id = ? OR CAST(r.metadata_json AS TEXT) LIKE ?)"
            ")) ORDER BY d.id",
            (tenant_id, source_document_id, f"%{source_id}%", source_id, f"%{source_id}%"),
        ).fetchall()
    return [
        {
            "id": str(row[0] or ""),
            "status": str(row[1] or ""),
            "lifecycle_status": str(row[2] or row[1] or ""),
        }
        for row in rows
        if str(row[0] or "")
    ]


def _latest_document_revision_id(document_id: str, tenant_id: str) -> str:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? "
            "AND record_type = 'document_revision' ORDER BY is_current DESC, revision_no DESC, created_at DESC, id DESC LIMIT 1",
            (tenant_id, document_id),
        ).fetchone()
    return str(row[0] or "") if row else ""


def apply_official_source_detection(
    source_id: str,
    user: dict[str, Any],
    *,
    detection_type: str,
    reason_code: str,
    replacement_url: str = "",
    source_version_id: str = "",
    refresh_observation_id: str = "",
) -> dict[str, Any]:
    detection_type = str(detection_type or "").strip().lower()
    if detection_type not in {"removed", "replacement", "version_updated"}:
        raise SourceRegistryError("INVALID_DETECTION_TYPE", "Official source detection type is invalid")
    source = get_source(source_id, user)
    tenant_id = str(source.get("tenant_id") or user.get("tenant_id") or "tenant-default")
    if not authorize_resource(user, "knowledge_source", "update", tenant_id=tenant_id):
        raise SourceRegistryError("SOURCE_CHANGE_PERMISSION_DENIED", "Insufficient permission to apply source change", status_code=403)
    if not _is_official(source):
        return {
            "source_id": source_id,
            "applied": False,
            "detection_type": detection_type,
            "reason": "non_official_source",
            "documents_quarantined": 0,
            "document_errors": [],
        }
    reason = _safe_code(reason_code, "OFFICIAL_SOURCE_CHANGED")
    if detection_type == "version_updated":
        return {
            "source_id": source_id,
            "applied": True,
            "detection_type": detection_type,
            "reason_code": reason,
            "source_status": str(source.get("status") or ""),
            "source_version_id": str(source_version_id or ""),
            "documents_quarantined": 0,
            "document_errors": [],
            "action_status": "applied",
        }

    observation_id = str(refresh_observation_id or "")
    application_state, claim_status = _claim_observation(source, observation_id)
    if claim_status == "applied":
        return {
            "source_id": source_id,
            "applied": True,
            "idempotent": True,
            "detection_type": detection_type,
            "reason_code": reason,
            "action_id": "v1change-" + observation_id,
            "action_status": "applied",
            "documents_quarantined": 0,
            "document_errors": [],
        }

    source_was_quarantined = str(source.get("lifecycle_status") or source.get("status") or "").lower() == "quarantined"
    # Calls without a durable refresh observation are the synchronous/manual
    # compatibility path.  Once the source is already quarantined, replaying
    # that path must not recount the source identity or invoke the downstream
    # lifecycle transition a second time.
    if not observation_id and source_was_quarantined:
        return {
            "source_id": source_id,
            "applied": True,
            "idempotent": True,
            "detection_type": detection_type,
            "reason_code": reason,
            "source_status": str(source.get("status") or "quarantined"),
            "source_version_id": str(source_version_id or ""),
            "refresh_observation_id": "",
            "action_id": "v1change-",
            "action_status": "applied",
            "documents_quarantined": 0,
            "document_errors": [],
        }
    try:
        updated_source = quarantine_source_for_change(
            source_id,
            user,
            detection_type=detection_type,
            reason_code=reason,
            replacement_url=str(replacement_url or ""),
            refresh_observation_id=observation_id,
        )
    except SourceRegistryError as exc:
        state = _finish_observation(source, observation_id, application_state, status="failed", error_code=exc.code)
        return {
            "source_id": source_id,
            "applied": False,
            "detection_type": detection_type,
            "reason_code": reason,
            "action_id": "v1change-" + observation_id,
            "action_status": "failed",
            "error_code": str(state.get("last_error_code") or "SOURCE_CHANGE_APPLY_FAILED"),
            "documents_quarantined": 0,
            "document_errors": [],
        }

    errors: list[dict[str, str]] = []
    # In V1 the registry identity and its source document are the same row.
    # Count that row as the quarantined searchable document when this is the
    # first application; V2 used to keep those identities in separate tables.
    quarantined = 0 if source_was_quarantined else 1
    source_document_id = str(source.get("source_document_id") or source_id)
    for document in _linked_documents(source):
        document_id = document["id"]
        current = str(document.get("lifecycle_status") or document.get("status") or "").lower()
        is_source_identity = document_id == source_document_id
        # The V1 source identity is already moved to quarantined by the
        # source operation.  Still pass its current revision through the
        # lifecycle boundary so a dependency failure is durable and retryable
        # exactly like a published projection.
        if current == "quarantined" and not is_source_identity:
            continue
        version_id = _latest_document_revision_id(document_id, tenant_id)
        if not version_id:
            if not is_source_identity:
                errors.append({"document_id": document_id, "code": "DOCUMENT_VERSION_NOT_FOUND"})
            continue
        request_id = f"ing019:{source_id}:{version_id}:{detection_type}"
        try:
            result = transition_document_lifecycle(
                document_id,
                "quarantined",
                user,
                document_version_id=version_id,
                reason=reason,
                request_id=request_id,
            )
            if not result.get("idempotent") and (not is_source_identity or source_was_quarantined):
                quarantined += 1
        except DocumentLifecycleError as exc:
            errors.append({"document_id": document_id, "code": _safe_code(exc.code, "DOCUMENT_CHANGE_APPLY_FAILED")})
        except Exception:
            errors.append({"document_id": document_id, "code": "DOCUMENT_CHANGE_APPLY_FAILED"})

    error_code = str((errors[0] if errors else {}).get("code") or "")
    final_state = _finish_observation(
        source,
        observation_id,
        application_state,
        status="failed" if errors else "applied",
        error_code=error_code,
    )
    return {
        "source_id": source_id,
        "applied": not errors,
        "idempotent": False,
        "detection_type": detection_type,
        "reason_code": reason,
        "source_status": str(updated_source.get("status") or ""),
        "replacement_present": bool(replacement_url),
        "source_version_id": str(source_version_id or ""),
        "refresh_observation_id": observation_id,
        "action_id": "v1change-" + observation_id,
        "action_status": str(final_state.get("status") or "failed"),
        "documents_quarantined": quarantined,
        "document_errors": errors[:50],
    }


__all__ = [
    "DocumentLifecycleError",
    "transition_document_lifecycle",
    "apply_official_source_detection",
]
