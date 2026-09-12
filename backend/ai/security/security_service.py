"""Durable, redacted Security Gateway and Copilot evidence helpers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from database.core import get_db_connection
from ai.security.sanitizer import sanitize_text
from ai.security.tokenization import opaque_user_id


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value: Any, default: Any) -> str:
    try:
        return json.dumps(value if value is not None else default, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        return json.dumps(default, ensure_ascii=False)


def _safe_comment(value: Any, limit: int = 500) -> str:
    text = sanitize_text(str(value or ""))
    return text[:limit]


def record_security_event(
    *,
    request_id: str,
    tenant_id: str,
    policy_version: str,
    classification: str,
    data_region: str,
    decision: str,
    disposition: str,
    finding_categories: Iterable[str] = (),
    provider_id: str | None = None,
    model_id: str | None = None,
    payload_bytes: int = 0,
    error_code: str | None = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
    site_id: str | None = None,
    department: str | None = None,
    document_scope: str | None = None,
    user_role: str | None = None,
) -> str:
    """Persist metadata only; raw content is never accepted by this API."""
    event_id = f"sec_evt_{uuid.uuid4().hex[:20]}"
    categories = sorted({str(item)[:80] for item in finding_categories if item})[:50]
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_security_events
                (id, request_id, tenant_id, workspace_id, site_id, department,
                 document_scope, user_role, user_id_opaque, policy_version,
                 classification, data_region, decision, disposition,
                 provider_id, model_id, finding_categories_json, payload_bytes,
                 error_code, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id, str(request_id), str(tenant_id), workspace_id, site_id,
                department, document_scope, user_role,
                opaque_user_id(user_id, tenant_id=str(tenant_id), task_id=str(request_id)) if user_id else None,
                str(policy_version), str(classification), str(data_region), str(decision), str(disposition),
                provider_id, model_id, _json(categories, []), max(0, int(payload_bytes or 0)),
                str(error_code)[:120] if error_code else None, _now(),
            ),
        )
        conn.commit()
    return event_id


def _security_event_filters(
    *, tenant_id: str, search: str = "", decision: str = "", classification: str = "",
) -> tuple[str, list[Any]]:
    where = ["tenant_id = ?"]
    params: list[Any] = [str(tenant_id)]
    normalized_search = sanitize_text(str(search or "").strip())[:256].casefold()
    normalized_decision = sanitize_text(str(decision or "").strip())[:32].casefold()
    normalized_classification = sanitize_text(str(classification or "").strip())[:32].casefold()
    if normalized_search:
        where.append(
            "(LOWER(COALESCE(request_id, '')) LIKE ? OR LOWER(COALESCE(provider_id, '')) LIKE ? "
            "OR LOWER(COALESCE(model_id, '')) LIKE ? OR LOWER(COALESCE(error_code, '')) LIKE ?)"
        )
        needle = f"%{normalized_search}%"
        params.extend([needle, needle, needle, needle])
    if normalized_decision:
        where.append("LOWER(COALESCE(decision, '')) = ?")
        params.append(normalized_decision)
    if normalized_classification:
        where.append("LOWER(COALESCE(classification, '')) = ?")
        params.append(normalized_classification)
    return " AND ".join(where), params


def list_security_events(
    *, tenant_id: str, limit: int = 100, offset: int = 0,
    search: str = "", decision: str = "", classification: str = "",
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    where, params = _security_event_filters(
        tenant_id=tenant_id, search=search, decision=decision, classification=classification,
    )
    with get_db_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, request_id, policy_version, classification, data_region,
                   decision, disposition, provider_id, model_id,
                   finding_categories_json, payload_bytes, error_code, created_at
            FROM ai_security_events
            WHERE {where}
            ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
    result = []
    for row in rows:
        try:
            categories = row[9] if isinstance(row[9], (list, tuple)) else json.loads(row[9] or "[]")
        except Exception:
            categories = []
        result.append({
            "id": row[0], "request_id": row[1], "policy_version": row[2],
            "classification": row[3], "data_region": row[4], "decision": row[5],
            "disposition": row[6], "provider_id": row[7], "model_id": row[8],
            "finding_categories": categories if isinstance(categories, list) else [],
            "payload_bytes": row[10], "error_code": row[11], "created_at": row[12],
        })
    return result


def count_security_events(
    *, tenant_id: str, search: str = "", decision: str = "", classification: str = "",
) -> int:
    where, params = _security_event_filters(
        tenant_id=tenant_id, search=search, decision=decision, classification=classification,
    )
    with get_db_connection() as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM ai_security_events WHERE {where}", tuple(params)).fetchone()
    return int(row[0] or 0) if row else 0


def export_security_events(*, tenant_id: str) -> str:
    """Return a redacted CSV export; only metadata fields are included."""
    rows = list_security_events(tenant_id=tenant_id, limit=500)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "id", "request_id", "policy_version", "classification", "data_region",
        "decision", "disposition", "provider_id", "model_id",
        "finding_categories", "payload_bytes", "error_code", "created_at",
    ])
    writer.writeheader()
    for row in rows:
        row = dict(row)
        row["finding_categories"] = _json(row.get("finding_categories"), [])
        writer.writerow(row)
    return output.getvalue()


_INCIDENT_TYPES = {"policy_violation", "secret_egress", "adapter_bypass", "cross_tenant", "provider_compromise", "attachment", "prompt_injection", "diagnostic"}
_INCIDENT_SEVERITIES = {"low", "medium", "high", "critical"}
_INCIDENT_STATUSES = {"open", "investigating", "resolved"}
_SAFE_EVIDENCE_KEYS = {
    "event_id", "request_id", "provider_id", "model_id", "policy_version",
    "classification", "data_region", "decision", "disposition", "error_code",
    "finding_categories", "adapter_bypass_count", "source_path_count",
}


def _safe_incident_evidence(evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Keep incident evidence metadata-only and bounded.

    The incident table predates the V2 gateway and is deliberately reused for
    response workflow.  Only allowlisted scalar metadata is persisted; raw
    prompts, terminal output, attachment bodies and credentials cannot enter
    this path even if a caller supplies them.
    """
    safe: dict[str, Any] = {}
    for key, value in (evidence or {}).items():
        if str(key) not in _SAFE_EVIDENCE_KEYS:
            continue
        if isinstance(value, (list, tuple, set)):
            safe[str(key)] = [sanitize_text(str(item))[:120] for item in list(value)[:20]]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = sanitize_text(str(value))[:240] if isinstance(value, str) else value
    return safe


def create_security_incident(
    *,
    tenant_id: str,
    incident_type: str,
    severity: str = "high",
    category: str = "policy",
    task_id: str | None = None,
    request_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_type = str(incident_type or "").strip().lower()
    normalized_severity = str(severity or "high").strip().lower()
    if normalized_type not in _INCIDENT_TYPES:
        raise ValueError("unsupported incident type")
    if normalized_severity not in _INCIDENT_SEVERITIES:
        raise ValueError("unsupported incident severity")
    incident_id = f"sec_inc_{uuid.uuid4().hex[:20]}"
    now = _now()
    safe_evidence = _safe_incident_evidence(evidence)
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_security_incidents
                (id, tenant_id, task_id, request_id, incident_type, severity,
                 category, evidence_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (incident_id, str(tenant_id), task_id, request_id, normalized_type,
             normalized_severity, sanitize_text(str(category or "policy"))[:80],
             _json(safe_evidence, {}), now),
        )
        conn.commit()
    return {
        "id": incident_id,
        "tenant_id": str(tenant_id),
        "incident_type": normalized_type,
        "severity": normalized_severity,
        "category": sanitize_text(str(category or "policy"))[:80],
        "status": "open",
        "evidence_keys": sorted(safe_evidence),
        "created_at": now,
    }


def _security_incident_filters(
    *, tenant_id: str, status: str | None = None, severity: str = "", search: str = "",
) -> tuple[str, list[Any]]:
    normalized_status = str(status or "").strip().lower() or None
    if normalized_status and normalized_status not in _INCIDENT_STATUSES:
        raise ValueError("unsupported incident status")
    where = "tenant_id = ?"
    params: list[Any] = [str(tenant_id)]
    if normalized_status:
        where += " AND status = ?"
        params.append(normalized_status)
    normalized_severity = str(severity or "").strip().lower()
    if normalized_severity and normalized_severity not in _INCIDENT_SEVERITIES:
        raise ValueError("unsupported incident severity")
    if normalized_severity:
        where += " AND severity = ?"
        params.append(normalized_severity)
    normalized_search = sanitize_text(str(search or "").strip())[:256].casefold()
    if normalized_search:
        where += (
            " AND (LOWER(COALESCE(request_id, '')) LIKE ? OR LOWER(COALESCE(task_id, '')) LIKE ? "
            "OR LOWER(COALESCE(incident_type, '')) LIKE ? OR LOWER(COALESCE(category, '')) LIKE ?)"
        )
        needle = f"%{normalized_search}%"
        params.extend([needle, needle, needle, needle])
    return where, params


def list_security_incidents(
    *, tenant_id: str, status: str | None = None, limit: int = 100, offset: int = 0,
    severity: str = "", search: str = "",
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    where, params = _security_incident_filters(
        tenant_id=tenant_id, status=status, severity=severity, search=search,
    )
    params.extend([limit, offset])
    with get_db_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, task_id, request_id, incident_type, severity, category,
                   status, created_at, resolved_at, resolved_by
            FROM ai_security_incidents
            WHERE {where}
            ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def count_security_incidents(
    *, tenant_id: str, status: str | None = None, severity: str = "", search: str = "",
) -> int:
    where, params = _security_incident_filters(
        tenant_id=tenant_id, status=status, severity=severity, search=search,
    )
    with get_db_connection() as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM ai_security_incidents WHERE {where}", tuple(params)).fetchone()
    return int(row[0] or 0) if row else 0


def resolve_security_incident(*, tenant_id: str, incident_id: str, resolved_by: str) -> dict[str, Any]:
    now = _now()
    with get_db_connection() as conn:
        result = conn.execute(
            """
            UPDATE ai_security_incidents
            SET status = 'resolved', resolved_at = ?, resolved_by = ?
            WHERE id = ? AND tenant_id = ? AND status <> 'resolved'
            """,
            (now, sanitize_text(str(resolved_by or "operator"))[:120], str(incident_id), str(tenant_id)),
        )
        if not result.rowcount:
            row = conn.execute(
                "SELECT id, status FROM ai_security_incidents WHERE id = ? AND tenant_id = ?",
                (str(incident_id), str(tenant_id)),
            ).fetchone()
            if not row:
                raise LookupError("security incident not found")
        conn.commit()
    return {"id": str(incident_id), "tenant_id": str(tenant_id), "status": "resolved", "resolved_at": now}


def audit_provider_adapters(*, project_root: str | Path | None = None) -> dict[str, Any]:
    """Static, metadata-only audit for direct network calls bypassing Gateway.

    It intentionally returns paths and counts only.  Source text is never
    exposed through the API or written to the audit log.
    """
    root = Path(project_root or Path(__file__).resolve().parents[3])
    ai_root = root / "backend" / "ai"
    allowed_files = {
        (ai_root / "gateway" / "llm_gateway.py").resolve(),
        (ai_root / "providers" / "embedding.py").resolve(),
        (ai_root / "providers" / "openai_compatible.py").resolve(),
        (ai_root / "security" / "security_service.py").resolve(),
    }
    suspicious: list[str] = []
    if ai_root.exists():
        for path in ai_root.rglob("*.py"):
            resolved = path.resolve()
            if resolved in allowed_files or "tests" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(marker in text for marker in ("httpx.AsyncClient", "requests.request", "requests.get(", "requests.post(")):
                suspicious.append(path.relative_to(root).as_posix())
    return {
        "audit_version": "sec-adapter-audit.v1",
        "checked_root": "backend/ai",
        "bypass_count": len(suspicious),
        "bypass_paths": suspicious[:100],
        "gateway_boundaries": ["backend/ai/gateway/llm_gateway.py", "backend/ai/providers/embedding.py", "backend/ai/providers/openai_compatible.py"],
        "decision": "PASS" if not suspicious else "REVIEW",
        "generated_at": _now(),
    }


def record_feedback(*, tenant_id: str, conversation_id: str, message_id: str, user_id: str, rating: str, reasons: Iterable[str] = (), comment: str = "") -> dict[str, Any]:
    normalized = str(rating or "").lower().strip()
    if normalized not in {"positive", "negative"}:
        raise ValueError("rating must be positive or negative")
    allowed_reasons = {"model_wrong", "version_wrong", "command_wrong", "insufficient_evidence", "stale", "irrelevant"}
    selected = sorted({str(item) for item in reasons if str(item) in allowed_reasons})[:8]
    feedback_id = f"fb_{uuid.uuid4().hex[:20]}"
    owner_opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id="conversation-owner")
    with get_db_connection() as conn:
        owned = conn.execute(
            """SELECT c.id
               FROM ai_conversations c
               JOIN ai_messages m ON m.conversation_id = c.id
               WHERE c.id = ? AND m.id = ? AND c.tenant_id = ? AND c.user_id_opaque = ?""",
            (str(conversation_id), str(message_id), str(tenant_id), owner_opaque),
        ).fetchone()
        if not owned:
            raise LookupError("conversation message not found")
        conn.execute(
            """
            INSERT INTO ai_conversation_feedback
                (id, tenant_id, conversation_id, message_id, user_id_opaque,
                 rating, reasons_json, comment_safe, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (tenant_id, conversation_id, message_id, user_id_opaque)
            DO UPDATE SET rating = excluded.rating, reasons_json = excluded.reasons_json,
                          comment_safe = excluded.comment_safe, created_at = excluded.created_at
            """,
            (feedback_id, tenant_id, conversation_id, message_id,
             opaque_user_id(user_id, tenant_id=tenant_id, task_id=conversation_id), normalized,
             _json(selected, []), _safe_comment(comment), _now()),
        )
        conn.commit()
    return {"id": feedback_id, "rating": normalized, "reasons": selected}


def create_diagnostic_case(*, tenant_id: str, user_id: str, title: str, symptom: str = "", conversation_id: str | None = None, scope: dict[str, Any] | None = None, plan: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    case_id = f"case_{uuid.uuid4().hex[:20]}"
    now = _now()
    owner_opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id="diagnostic-owner")
    with get_db_connection() as conn:
        if conversation_id:
            conversation_owner = opaque_user_id(user_id, tenant_id=tenant_id, task_id="conversation-owner")
            linked_conversation = conn.execute(
                "SELECT id FROM ai_conversations WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?",
                (str(conversation_id), str(tenant_id), conversation_owner),
            ).fetchone()
            if not linked_conversation:
                raise LookupError("conversation not found")
        try:
            conn.execute(
                """
                INSERT INTO ai_diagnostic_cases
                    (id, tenant_id, conversation_id, title, status, symptom_safe,
                     scope_json, plan_json, created_by, created_by_opaque, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?)
                """,
                (case_id, tenant_id, conversation_id, _safe_comment(title, 160), _safe_comment(symptom, 2000), _json(scope, {}), _json(plan, []), owner_opaque, owner_opaque, now, now),
            )
        except Exception:
            conn.rollback()
            conn.execute(
                """
                INSERT INTO ai_diagnostic_cases
                    (id, tenant_id, conversation_id, title, status, symptom_safe,
                     scope_json, plan_json, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)
                """,
                (case_id, tenant_id, conversation_id, _safe_comment(title, 160), _safe_comment(symptom, 2000), _json(scope, {}), _json(plan, []), owner_opaque, now, now),
            )
        conn.commit()
    return {"id": case_id, "tenant_id": tenant_id, "title": _safe_comment(title, 160), "status": "open", "created_at": now}


def handoff_case(*, tenant_id: str, case_id: str, user_id: str, handoff: dict[str, Any]) -> dict[str, Any]:
    safe = {
        "summary": _safe_comment(handoff.get("summary"), 2000),
        "assignee": _safe_comment(handoff.get("assignee"), 120),
        "ticket_draft": _safe_comment(handoff.get("ticket_draft"), 3000),
    }
    now = _now()
    owner_opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id="diagnostic-owner")
    with get_db_connection() as conn:
        row = conn.execute("SELECT id FROM ai_diagnostic_cases WHERE id = ? AND tenant_id = ? AND created_by_opaque = ?", (case_id, tenant_id, owner_opaque)).fetchone()
        if not row:
            raise LookupError("diagnostic case not found")
        conn.execute("UPDATE ai_diagnostic_cases SET status = 'investigating', handoff_json = ?, updated_at = ? WHERE id = ? AND tenant_id = ?", (_json(safe, {}), now, case_id, tenant_id))
        conn.commit()
    return {"case_id": case_id, "status": "investigating", "handoff": safe, "updated_at": now}


def ensure_diagnostic_case_access(*, tenant_id: str, case_id: str, user_id: str) -> None:
    """Fail closed before any diagnostic work can use another user's case."""
    owner_opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id="diagnostic-owner")
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id FROM ai_diagnostic_cases WHERE id = ? AND tenant_id = ? AND created_by_opaque = ?",
            (str(case_id), str(tenant_id), owner_opaque),
        ).fetchone()
    if not row:
        raise LookupError("diagnostic case not found")


def stable_digest(value: Any) -> str:
    return hashlib.sha256(_json(value, {}).encode("utf-8")).hexdigest()


def persist_diagnostic_run(*, tenant_id: str, user_id: str | None = None, case_id: str | None, result: dict[str, Any], playbook_code: str, vendor: str | None = None, platform: str | None = None, device_id: str | None = None) -> None:
    """Persist only bounded step evidence and stable error codes."""
    run_id = str(result.get("run_id") or f"dia_{uuid.uuid4().hex[:16]}")
    started = _now()
    owner_opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id="diagnostic-owner") if user_id else None
    with get_db_connection() as conn:
        if case_id and owner_opaque:
            case = conn.execute("SELECT id FROM ai_diagnostic_cases WHERE id = ? AND tenant_id = ? AND created_by_opaque = ?", (case_id, tenant_id, owner_opaque)).fetchone()
            if not case:
                raise LookupError("diagnostic case not found")
        try:
            conn.execute(
                """
                INSERT INTO ai_diagnostic_runs
                    (id, case_id, tenant_id, user_id_opaque, state, playbook_code, vendor, platform, device_id, read_only, started_at, finished_at, error_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET state = excluded.state, finished_at = excluded.finished_at, error_code = excluded.error_code
                """,
                (run_id, case_id or "", tenant_id, owner_opaque, str(result.get("state") or "failed"), playbook_code, vendor, platform, device_id, started, _now(), next((str(step.get("error_code")) for step in result.get("steps", []) if step.get("error_code")), None)),
            )
        except Exception:
            conn.rollback()
            conn.execute(
                """
                INSERT INTO ai_diagnostic_runs
                    (id, case_id, tenant_id, state, playbook_code, vendor, platform, device_id, read_only, started_at, finished_at, error_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET state = excluded.state, finished_at = excluded.finished_at, error_code = excluded.error_code
                """,
                (run_id, case_id or "", tenant_id, str(result.get("state") or "failed"), playbook_code, vendor, platform, device_id, started, _now(), next((str(step.get("error_code")) for step in result.get("steps", []) if step.get("error_code")), None)),
            )
        for step in result.get("steps") or []:
            conn.execute(
                """
                INSERT INTO ai_diagnostic_steps
                    (id, run_id, tenant_id, user_id_opaque, step_no, purpose, command_safe, target_safe, status, evidence_json, duration_ms, error_code, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id, step_no) DO UPDATE SET status = excluded.status, evidence_json = excluded.evidence_json, duration_ms = excluded.duration_ms, error_code = excluded.error_code
                """,
                (
                    f"{run_id}_step_{int(step.get('step_no') or 0)}", run_id, tenant_id, owner_opaque,
                    int(step.get("step_no") or 0), _safe_comment(step.get("purpose"), 160),
                    _safe_comment(step.get("command"), 240), _safe_comment(step.get("target"), 160),
                    str(step.get("status") or "failed"), _json(step.get("evidence") or [], []),
                    max(0, int(step.get("duration_ms") or 0)), str(step.get("error_code") or "") or None, _now(),
                ),
            )
        conn.commit()
