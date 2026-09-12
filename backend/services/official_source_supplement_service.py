"""Durable review/import/recheck loop for allow-listed official source suggestions."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from services.official_source_suggestion_service import suggest_official_sources
from services.official_url_import_service import OfficialUrlImportError, import_single_official_url


class OfficialSourceSupplementError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _text(value: Any, maximum: int = 4096) -> str:
    return str(value or "").strip()[:maximum]


def _row(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


def record_official_source_suggestions(
    request: Any,
    *,
    tenant_id: str,
    trace_id: str,
    request_id: str = "",
    query: str = "",
) -> list[dict[str, Any]]:
    suggestions = suggest_official_sources(request, limit=3)
    if not suggestions:
        return []
    now = _now()
    vendor = _text(getattr(request, "vendor", ""), 128)
    model = _text(getattr(request, "product_model", "") or getattr(request, "product_series", ""), 256)
    release = _text(getattr(request, "software_release", "") or getattr(request, "software_train", ""), 128)
    feature = _text(getattr(request, "feature", "") or getattr(request, "feature_domain", ""), 128)
    query_hash = hashlib.sha256(str(query or "").encode("utf-8", errors="replace")).hexdigest()
    with get_db_connection() as conn:
        for suggestion in suggestions:
            suggestion_key = f"{tenant_id}:{trace_id}:{suggestion['url']}"
            suggestion_id = f"oss_{uuid.uuid5(uuid.NAMESPACE_URL, suggestion_key).hex[:24]}"
            conn.execute(
                """
                INSERT INTO official_source_suggestion (
                    id, tenant_id, trace_id, request_id, query_hash, vendor,
                    product_model, software_release, feature, label, suggested_url,
                    source_kind, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT (tenant_id, trace_id, suggested_url) DO NOTHING
                """,
                (
                    suggestion_id, tenant_id, trace_id, request_id or None, query_hash,
                    vendor, model or None, release or None, feature or None,
                    _text(suggestion.get("label"), 256), _text(suggestion.get("url")),
                    _text(suggestion.get("source_kind"), 64), now, now,
                ),
            )
        conn.commit()
    return list_official_source_suggestions(tenant_id=tenant_id, trace_id=trace_id, page=1, page_size=10)["items"]


def list_official_source_suggestions(
    *, tenant_id: str, status: str = "all", search: str = "", trace_id: str = "", page: int = 1, page_size: int = 20
) -> dict[str, Any]:
    clauses = ["tenant_id = ?"]
    params: list[Any] = [tenant_id]
    if status and status != "all":
        clauses.append("status = ?")
        params.append(status)
    if trace_id:
        clauses.append("trace_id = ?")
        params.append(trace_id)
    if search:
        pattern = f"%{search.strip().lower()}%"
        clauses.append("(LOWER(vendor) LIKE ? OR LOWER(COALESCE(product_model, '')) LIKE ? OR LOWER(COALESCE(feature, '')) LIKE ? OR LOWER(suggested_url) LIKE ?)")
        params.extend([pattern] * 4)
    where = " AND ".join(clauses)
    bounded_page = max(1, int(page or 1))
    bounded_size = max(1, min(100, int(page_size or 20)))
    with get_db_connection() as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM official_source_suggestion WHERE {where}", params).fetchone()[0])
        rows = conn.execute(
            f"SELECT * FROM official_source_suggestion WHERE {where} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, bounded_size, (bounded_page - 1) * bounded_size],
        ).fetchall()
    return {"items": [dict(item) for item in rows], "total": total, "page": bounded_page, "page_size": bounded_size, "total_pages": max(1, (total + bounded_size - 1) // bounded_size)}


def review_official_source_suggestion(
    suggestion_id: str, *, tenant_id: str, user: dict[str, Any], decision: str, fields: dict[str, Any]
) -> dict[str, Any]:
    with get_db_connection() as conn:
        current = _row(conn.execute("SELECT * FROM official_source_suggestion WHERE id = ? AND tenant_id = ?", (suggestion_id, tenant_id)).fetchone())
    if not current:
        raise OfficialSourceSupplementError("OFFICIAL_SUGGESTION_NOT_FOUND", "Official source suggestion was not found", status_code=404)
    if current["status"] not in {"pending", "failed"}:
        raise OfficialSourceSupplementError("OFFICIAL_SUGGESTION_ALREADY_REVIEWED", "Official source suggestion has already been reviewed", status_code=409)
    reviewer = _text(user.get("id") or user.get("username") or "system", 256)
    now = _now()
    if decision == "reject":
        with get_db_connection() as conn:
            conn.execute("UPDATE official_source_suggestion SET status = 'rejected', reviewer_id = ?, reviewed_at = ?, updated_at = ? WHERE id = ? AND tenant_id = ?", (reviewer, now, now, suggestion_id, tenant_id))
            conn.commit()
        return {**current, "status": "rejected", "reviewer_id": reviewer, "reviewed_at": now}
    if decision != "approve":
        raise OfficialSourceSupplementError("OFFICIAL_SUGGESTION_DECISION_INVALID", "Decision must be approve or reject")

    vendor = _text(fields.get("vendor") or current.get("vendor"), 128)
    model = _text(fields.get("product_model") or current.get("product_model"), 256)
    release = _text(fields.get("software_release") or current.get("software_release"), 128)
    feature = _text(fields.get("feature") or current.get("feature"), 128)
    reviewed_url = _text(fields.get("url") or current.get("suggested_url"))
    if not all((vendor, model, release, feature, reviewed_url)):
        raise OfficialSourceSupplementError("OFFICIAL_SUGGESTION_SCOPE_INCOMPLETE", "Vendor, model, software release, feature and official URL must all be confirmed")
    source_kind = _text(fields.get("source_kind") or current.get("source_kind"), 64)
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE official_source_suggestion SET vendor = ?, product_model = ?, software_release = ?, feature = ?, reviewed_url = ?, source_kind = ?, status = 'approved', reviewer_id = ?, reviewed_at = ?, updated_at = ?, error_code = NULL WHERE id = ? AND tenant_id = ?",
            (vendor, model, release, feature, reviewed_url, source_kind, reviewer, now, now, suggestion_id, tenant_id),
        )
        conn.commit()
    try:
        result = import_single_official_url(
            user,
            {
                "url": reviewed_url,
                "source_kind": source_kind,
                "vendor": vendor,
                "product_family": model,
                "version_scope": {"primary": release, "compatibility": release},
                # The administrator's explicit approval is the terms gate for
                # this reviewed official URL.  Keep the value aligned with the
                # import boundary contract (approved/waived/not_required).
                "terms_review_status": "approved",
                "reviewer": reviewer,
                "reviewed_at": now,
                "name": f"{vendor} {model} {feature}",
                "description": f"Approved from retrieval miss {current['trace_id']}",
                "request_id": current.get("request_id") or "",
                "publish_to_knowledge_base": True,
            },
        )
    except OfficialUrlImportError as exc:
        with get_db_connection() as conn:
            conn.execute("UPDATE official_source_suggestion SET status = 'failed', error_code = ?, updated_at = ? WHERE id = ? AND tenant_id = ?", (exc.code, _now(), suggestion_id, tenant_id))
            conn.commit()
        raise OfficialSourceSupplementError(exc.code, exc.message, status_code=exc.status_code) from exc

    source = result.get("source") or {}
    job = result.get("job") or {}
    document = result.get("published_document") or result.get("document") or {}
    status = "imported" if result.get("success") and not result.get("continuation_required") else "collecting"
    recheck_status = "pending"
    recheck_trace_id = ""
    if status == "imported":
        try:
            from ai.services.assistant import ai_assistant_service
            recheck_query = " ".join(part for part in (vendor, model, release, feature) if part)
            recheck = ai_assistant_service.retrieve_knowledge(
                recheck_query,
                {"metadata": {"vendor": vendor, "product_model": model, "software_release": release, "feature": feature}},
                tenant_id=tenant_id,
                user_id=reviewer,
                request_id=f"recheck-{suggestion_id}",
            )
            recheck_trace_id = _text(recheck.get("retrieval_trace_id"), 128)
            recheck_status = "hit" if recheck.get("results") else "no_match"
        except Exception:
            recheck_status = "error"
    with get_db_connection() as conn:
        conn.execute(
            """UPDATE official_source_suggestion SET status = ?, source_registry_id = ?, ingestion_job_id = ?, document_id = ?,
               recheck_trace_id = ?, recheck_status = ?, error_code = NULL, updated_at = ? WHERE id = ? AND tenant_id = ?""",
            (status, source.get("id"), job.get("id"), document.get("id") or document.get("document_id"), recheck_trace_id or None, recheck_status, _now(), suggestion_id, tenant_id),
        )
        conn.commit()
        updated = _row(conn.execute("SELECT * FROM official_source_suggestion WHERE id = ? AND tenant_id = ?", (suggestion_id, tenant_id)).fetchone())
    return updated or current


__all__ = ["OfficialSourceSupplementError", "list_official_source_suggestions", "record_official_source_suggestions", "review_official_source_suggestion"]
