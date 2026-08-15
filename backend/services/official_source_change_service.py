"""ING-019 official-source removal, replacement and version signals."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from core.rbac import authorize_resource
from database import get_db_connection
from services.document_lifecycle_service import DocumentLifecycleError, transition_document_lifecycle
from services.source_registry_service import (
    SourceRegistryError,
    get_source,
    quarantine_source_for_change,
)


logger = logging.getLogger(__name__)
_OFFICIAL_KINDS = {
    "official_url",
    "product_page",
    "configuration_guide",
    "command_reference",
    "release_note",
    "product_support",
}


def _is_official(source: dict[str, Any]) -> bool:
    return str(source.get("source_type") or "").startswith("official_") or str(source.get("source_kind") or "") in _OFFICIAL_KINDS


def _safe_code(exc: BaseException, default: str) -> str:
    code = str(getattr(exc, "code", "") or default)
    return code[:128] if code.replace("_", "").isalnum() else default


def _stable_code(value: Any, default: str) -> str:
    code = str(value or default).strip().upper()
    return code[:128] if code.replace("_", "").isalnum() else default


def _actor(user: dict[str, Any]) -> str:
    return str(user.get("id") or user.get("user_id") or user.get("username") or "system")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _claim_change_action(
    *,
    source: dict[str, Any],
    detection_type: str,
    user: dict[str, Any],
    refresh_observation_id: str,
) -> tuple[dict[str, Any], str]:
    tenant_id = str(source.get("tenant_id") or user.get("tenant_id") or "tenant-default")
    if not authorize_resource(user, "knowledge_source", "update", tenant_id=tenant_id):
        raise SourceRegistryError("SOURCE_CHANGE_PERMISSION_DENIED", "Insufficient permission to apply source change", status_code=403)
    conn = get_db_connection()
    try:
        params: list[Any] = [tenant_id, str(source.get("id") or ""), detection_type]
        observation_clause = ""
        if refresh_observation_id:
            observation_clause = " AND action.refresh_observation_id = ?"
            params.append(refresh_observation_id)
        row = conn.execute(
            """
            SELECT action.*, observation.replacement_url,
                   observation.source_version_id AS observed_source_version_id
            FROM kb_source_change_action AS action
            JOIN kb_source_refresh_observation AS observation
              ON observation.tenant_id = action.tenant_id
             AND observation.id = action.refresh_observation_id
            WHERE action.tenant_id = ?
              AND action.source_registry_id = ?
              AND action.detection_type = ?
            """ + observation_clause +
            " ORDER BY action.created_at DESC, action.id DESC LIMIT 1",
            tuple(params),
        ).fetchone()
        if not row:
            raise SourceRegistryError(
                "SOURCE_CHANGE_ACTION_NOT_FOUND",
                "No durable source-change action exists for this detection",
                status_code=409,
            )
        action = dict(row)
        status = str(action.get("status") or "pending")
        if status == "applied":
            return action, "applied"
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(microsecond=0).isoformat()
        updated = conn.execute(
            """
            UPDATE kb_source_change_action
            SET status = 'applying', attempt_count = attempt_count + 1,
                last_error_code = '', updated_at = ?, updated_by = ?
            WHERE tenant_id = ? AND id = ?
              AND (status IN ('pending','failed') OR (status = 'applying' AND updated_at < ?))
            """,
            (_now(), _actor(user), tenant_id, str(action.get("id") or ""), cutoff),
        ).rowcount
        if updated != 1:
            conn.rollback()
            return action, "in_progress"
        conn.commit()
        action["status"] = "applying"
        action["attempt_count"] = int(action.get("attempt_count") or 0) + 1
        return action, "claimed"
    except SourceRegistryError:
        conn.rollback()
        raise
    finally:
        conn.close()


def _finish_change_action(action: dict[str, Any], user: dict[str, Any], *, status: str, error_code: str = "") -> None:
    tenant_id = str(action.get("tenant_id") or "")
    now = _now()
    actor = _actor(user)
    applied = status == "applied"
    conn = get_db_connection()
    try:
        updated = conn.execute(
            """
            UPDATE kb_source_change_action
            SET status = ?, last_error_code = ?, updated_at = ?, updated_by = ?,
                applied_at = ?, applied_by = ?
            WHERE tenant_id = ? AND id = ? AND status = 'applying'
            """,
            (
                status,
                _stable_code(error_code, "") if error_code else "",
                now,
                actor,
                now if applied else None,
                actor if applied else "",
                tenant_id,
                str(action.get("id") or ""),
            ),
        ).rowcount
        if updated != 1:
            raise SourceRegistryError("SOURCE_CHANGE_ACTION_STALE", "Source-change action state changed concurrently", status_code=409)
        conn.commit()
    except SourceRegistryError:
        conn.rollback()
        raise
    finally:
        conn.close()


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
    """Apply a stable change signal without deleting source/document history.

    Removal and replacement quarantine the Source Registry row and currently
    published document versions. Version updates remain active and are left
    for the subsequent metadata/approval workflow; the immutable new source
    version and observation are the evidence for that update.
    """
    detection_type = str(detection_type or "").strip().lower()
    if detection_type not in {"removed", "replacement", "version_updated"}:
        raise SourceRegistryError("INVALID_DETECTION_TYPE", "Official source detection type is invalid")
    source = get_source(source_id, user)
    if not _is_official(source):
        return {
            "source_id": source_id,
            "applied": False,
            "detection_type": detection_type,
            "reason": "non_official_source",
            "documents_quarantined": 0,
            "document_errors": [],
        }
    if detection_type == "version_updated":
        return {
            "source_id": source_id,
            "applied": True,
            "detection_type": detection_type,
            "reason_code": str(reason_code or "VERSION_CONTENT_CHANGED")[:128],
            "source_status": str(source.get("status") or ""),
            "source_version_id": str(source_version_id or ""),
            "documents_quarantined": 0,
            "document_errors": [],
        }

    action, claim_status = _claim_change_action(
        source=source,
        detection_type=detection_type,
        user=user,
        refresh_observation_id=str(refresh_observation_id or ""),
    )
    if claim_status == "applied":
        return {
            "source_id": source_id,
            "applied": True,
            "idempotent": True,
            "detection_type": detection_type,
            "reason_code": _stable_code(reason_code, "OFFICIAL_SOURCE_CHANGED"),
            "action_id": str(action.get("id") or ""),
            "action_status": "applied",
            "documents_quarantined": 0,
            "document_errors": [],
        }
    if claim_status == "in_progress":
        return {
            "source_id": source_id,
            "applied": False,
            "idempotent": True,
            "detection_type": detection_type,
            "reason": "action_in_progress",
            "action_id": str(action.get("id") or ""),
            "action_status": "applying",
            "documents_quarantined": 0,
            "document_errors": [],
        }

    observed_replacement_url = str(action.get("replacement_url") or "")
    if replacement_url and observed_replacement_url and replacement_url != observed_replacement_url:
        _finish_change_action(action, user, status="failed", error_code="SOURCE_CHANGE_EVIDENCE_MISMATCH")
        raise SourceRegistryError("SOURCE_CHANGE_EVIDENCE_MISMATCH", "Source-change evidence does not match the durable observation", status_code=409)
    replacement_url = observed_replacement_url
    source_version_id = str(action.get("observed_source_version_id") or source_version_id or "")
    reason_code = _stable_code(reason_code, "OFFICIAL_SOURCE_CHANGED")

    try:
        updated_source = quarantine_source_for_change(
            source_id,
            user,
            detection_type=detection_type,
            reason_code=reason_code,
            replacement_url=replacement_url,
            refresh_observation_id=str(action.get("refresh_observation_id") or ""),
        )
    except SourceRegistryError as exc:
        _finish_change_action(action, user, status="failed", error_code=_safe_code(exc, "SOURCE_CHANGE_APPLY_FAILED"))
        raise
    tenant_id = str(source.get("tenant_id") or user.get("tenant_id") or "tenant-default")
    errors: list[dict[str, str]] = []
    quarantined = 0
    try:
        with get_db_connection() as conn:
            documents = conn.execute(
                "SELECT id, current_version_id FROM kb_document WHERE tenant_id = ? AND source_registry_id = ? AND lifecycle_status IN ('published','active','draft')",
                (tenant_id, source_id),
            ).fetchall()
    except Exception:
        documents = []
        errors.append({"code": "DOCUMENT_CHANGE_SCAN_FAILED"})

    for row in documents:
        document_id = str(row[0] or "")
        version_id = str(row[1] or "")
        if not document_id:
            continue
        if not version_id:
            try:
                with get_db_connection() as conn:
                    version_row = conn.execute(
                        "SELECT id FROM kb_document_version WHERE tenant_id = ? AND document_id = ? ORDER BY version_no DESC LIMIT 1",
                        (tenant_id, document_id),
                    ).fetchone()
                version_id = str(version_row[0] or "") if version_row else ""
            except Exception:
                version_id = ""
        if not version_id:
            errors.append({"document_id": document_id, "code": "DOCUMENT_VERSION_NOT_FOUND"})
            continue
        request_id = f"ing019:{source_id}:{version_id}:{detection_type}"
        try:
            result = transition_document_lifecycle(
                document_id,
                "quarantined",
                user,
                document_version_id=version_id,
                reason=reason_code,
                request_id=request_id,
            )
            if not result.get("idempotent"):
                quarantined += 1
        except DocumentLifecycleError as exc:
            # A partially upgraded installation must not turn a source signal
            # into a destructive rollback. Preserve a stable error code and
            # continue with the remaining tenant documents.
            errors.append({"document_id": document_id, "code": _safe_code(exc, "DOCUMENT_CHANGE_APPLY_FAILED")})
        except Exception:
            errors.append({"document_id": document_id, "code": "DOCUMENT_CHANGE_APPLY_FAILED"})

    action_error = str((errors[0] if errors else {}).get("code") or "")
    if errors:
        _finish_change_action(action, user, status="failed", error_code=action_error or "DOCUMENT_CHANGE_APPLY_FAILED")
    else:
        _finish_change_action(action, user, status="applied")
    return {
        "source_id": source_id,
        "applied": not errors,
        "idempotent": False,
        "detection_type": detection_type,
        "reason_code": reason_code,
        "source_status": str(updated_source.get("status") or ""),
        "replacement_present": bool(replacement_url),
        "source_version_id": source_version_id,
        "refresh_observation_id": str(action.get("refresh_observation_id") or ""),
        "action_id": str(action.get("id") or ""),
        "action_status": "failed" if errors else "applied",
        "documents_quarantined": quarantined,
        "document_errors": errors[:50],
    }


__all__ = ["apply_official_source_detection"]
