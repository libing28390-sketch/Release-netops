"""AI security policy, dry-run and metadata-only audit endpoints."""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from database.core import get_db_connection
from ai.security.gateway import SecurityBlocked, SecurityPolicy, ai_security_gateway
from ai.security.dev_passthrough import dev_passthrough
from ai.security.classification import DataClassification, normalize_classification
from ai.security.permissions import require_ai_permission
from core.rbac import _get_current_user
from ai.security.security_service import (
    audit_provider_adapters,
    create_security_incident,
    count_security_events,
    count_security_incidents,
    export_security_events,
    list_security_events,
    list_security_incidents,
    record_security_event,
    resolve_security_incident,
)
from ai.services.document_security_scan import scan_document_security
from services.document_parser_adapters import ParsedBlock, ParsedDocument
from ai.schemas.provider import SUPPORTED_PROVIDER_TYPES
from api.knowledge_contracts import (
    AttachmentCheckRequest,
    SecurityIncidentRequest,
    SecurityKillSwitchRequest,
    DevPassthroughRequest,
    SecurityPolicyUpdateRequest,
    SecurityTestPayloadRequest,
    TenantSecurityKillSwitchRequest,
)

router = APIRouter(prefix="/security", tags=["AI Security Gateway"])
logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_persisted_security_policy() -> None:
    """Load the last operator policy after migrations, fail-closed on errors."""
    try:
        with get_db_connection() as conn:
            policy_row = conn.execute(
                "SELECT version, external_ai_enabled, rules_json, provider_allowlist_json FROM ai_security_policies WHERE status = 'active' ORDER BY version DESC LIMIT 1"
            ).fetchone()
            kill_row = conn.execute("SELECT enabled FROM ai_kill_switch WHERE id = 1").fetchone()
            tenant_rows = conn.execute("SELECT tenant_id, kill_switch FROM ai_tenant_security_controls WHERE kill_switch = 1").fetchall()
        current = ai_security_gateway.policy
        external_enabled = bool(policy_row[1]) if policy_row else current.external_ai_enabled
        allow_sensitive = current.allow_sensitive_minimization
        allowed = current.allowed_provider_types
        policy_version = current.policy_version
        allowed_classifications = current.allowed_classifications
        allowed_regions = current.allowed_data_regions
        provider_kill_switches = current.provider_kill_switches
        tenant_kill_switches = current.tenant_kill_switches
        if tenant_rows:
            tenant_kill_switches = {str(row[0]): bool(row[1]) for row in tenant_rows}
        scope_rules = current.scope_rules
        if policy_row:
            try:
                rules = json.loads(policy_row[2] or '{}')
                allow_sensitive = bool(rules.get('allow_sensitive_minimization', allow_sensitive))
                policy_version = str(rules.get('policy_version') or (policy_row[0] if policy_row else current.policy_version))
                allowed_classifications = tuple(str(item).upper() for item in rules.get('allowed_classifications', current.allowed_classifications))
                allowed_regions = tuple(str(item).lower() for item in rules.get('allowed_data_regions', current.allowed_data_regions))
                provider_kill_switches = {str(key): bool(value) for key, value in (rules.get('provider_kill_switches') or {}).items()}
                tenant_kill_switches = {str(key): bool(value) for key, value in (rules.get('tenant_kill_switches') or {}).items()}
                scope_rules = rules.get('scope_rules') if isinstance(rules.get('scope_rules'), dict) else {}
            except Exception:
                policy_version = current.policy_version
                allowed_classifications = current.allowed_classifications
                allowed_regions = current.allowed_data_regions
                provider_kill_switches = current.provider_kill_switches
                tenant_kill_switches = current.tenant_kill_switches
                scope_rules = current.scope_rules
            try:
                candidate = tuple(str(item).lower().strip().replace('-', '_') for item in json.loads(policy_row[3] or '[]'))
                if candidate and set(candidate) <= set(SUPPORTED_PROVIDER_TYPES):
                    allowed = candidate
            except Exception:
                pass
        ai_security_gateway.policy = SecurityPolicy(
            external_ai_enabled=external_enabled,
            kill_switch=bool(kill_row[0]) if kill_row else current.kill_switch,
            max_payload_bytes=current.max_payload_bytes,
            identifiers_must_be_tokenized=True,
            allow_sensitive_minimization=allow_sensitive,
            allowed_provider_types=allowed,
            policy_version=policy_version,
            allowed_classifications=allowed_classifications,
            allowed_data_regions=allowed_regions,
            provider_kill_switches=provider_kill_switches,
            tenant_kill_switches=tenant_kill_switches,
            scope_rules=scope_rules,
        )
    except Exception:
        # Keep settings defaults (external disabled) if a database is not yet
        # available; never enable external egress because loading failed.
        current = ai_security_gateway.policy
        ai_security_gateway.policy = SecurityPolicy(
            external_ai_enabled=False,
            kill_switch=True,
            max_payload_bytes=current.max_payload_bytes,
            identifiers_must_be_tokenized=True,
            allow_sensitive_minimization=current.allow_sensitive_minimization,
            allowed_provider_types=('deepseek',),
            policy_version=current.policy_version,
            allowed_classifications=current.allowed_classifications,
            allowed_data_regions=current.allowed_data_regions,
            provider_kill_switches=current.provider_kill_switches,
            tenant_kill_switches=current.tenant_kill_switches,
            scope_rules=current.scope_rules,
        )


@router.get("/policy", response_model=Dict[str, Any])
def get_security_policy(user=Depends(require_ai_permission("ai.audit.view"))):
    policy = ai_security_gateway.policy
    return {
        "external_ai_enabled": policy.external_ai_enabled,
        "kill_switch": policy.kill_switch,
        "max_payload_bytes": policy.max_payload_bytes,
        "identifiers_must_be_tokenized": policy.identifiers_must_be_tokenized,
        "allow_sensitive_minimization": policy.allow_sensitive_minimization,
        "allowed_provider_types": list(policy.allowed_provider_types),
        "policy_version": policy.policy_version,
        "allowed_classifications": list(policy.allowed_classifications),
        "allowed_data_regions": list(policy.allowed_data_regions),
        "provider_kill_switches": dict(policy.provider_kill_switches),
        "tenant_kill_switches": dict(policy.tenant_kill_switches),
        "scope_rules": dict(policy.scope_rules),
        "dev_passthrough": dev_passthrough.status(),
    }


@router.put("/policy", response_model=Dict[str, Any])
def update_security_policy(payload: SecurityPolicyUpdateRequest, user=Depends(require_ai_permission("ai.provider.manage"))):
    allowed = tuple(str(item).lower().strip().replace('-', '_') for item in (payload.allowed_provider_types or SUPPORTED_PROVIDER_TYPES))
    if not allowed or any(item not in SUPPORTED_PROVIDER_TYPES for item in allowed):
        raise HTTPException(status_code=400, detail="Provider type is not in the approved adapter allowlist")
    classifications = tuple(str(item).upper().strip() for item in payload.allowed_classifications)
    if not classifications or any(normalize_classification(item) is None or item == DataClassification.SECRET.value for item in classifications):
        raise HTTPException(status_code=400, detail="SECRET cannot be enabled for external egress")
    regions = tuple(str(item).lower().strip() for item in payload.allowed_data_regions)
    if not regions or any(not item or len(item) > 64 for item in regions):
        raise HTTPException(status_code=400, detail="allowed_data_regions must be explicit")
    provider_kill_switches = {str(key): bool(value) for key, value in payload.provider_kill_switches.items()}
    tenant_kill_switches = {str(key): bool(value) for key, value in payload.tenant_kill_switches.items()}
    scope_rules = payload.scope_rules
    policy_version = str(payload.policy_version or f"sec-{uuid.uuid4().hex[:8]}")[:64]
    policy = SecurityPolicy(
        external_ai_enabled=payload.external_ai_enabled,
        kill_switch=payload.kill_switch,
        max_payload_bytes=payload.max_payload_bytes,
        identifiers_must_be_tokenized=True,
        allow_sensitive_minimization=payload.allow_sensitive_minimization,
        allowed_provider_types=allowed,
        policy_version=policy_version,
        allowed_classifications=classifications,
        allowed_data_regions=regions,
        provider_kill_switches=provider_kill_switches,
        tenant_kill_switches=tenant_kill_switches,
        scope_rules=scope_rules,
    )
    ai_security_gateway.policy = policy
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    now = _now()
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_security_policies
                (id, tenant_id, version, status, external_ai_enabled, default_action,
                 rules_json, provider_allowlist_json, approved_by, created_at, updated_at)
            VALUES (?, ?, COALESCE((SELECT MAX(version) + 1 FROM ai_security_policies WHERE tenant_id = ?), 1),
                    'active', ?, 'BLOCK', ?, ?, ?, ?, ?)
            """,
            (
                f"aipol_{uuid.uuid4().hex[:12]}", tenant_id, tenant_id,
                int(policy.external_ai_enabled),
                json.dumps({
                    "allow_sensitive_minimization": policy.allow_sensitive_minimization,
                    "policy_version": policy.policy_version,
                    "allowed_classifications": list(policy.allowed_classifications),
                    "allowed_data_regions": list(policy.allowed_data_regions),
                    "provider_kill_switches": policy.provider_kill_switches,
                    "tenant_kill_switches": policy.tenant_kill_switches,
                    "scope_rules": policy.scope_rules,
                }, ensure_ascii=False),
                json.dumps(list(policy.allowed_provider_types)),
                user.get("username", "admin"), now, now,
            ),
        )
        conn.commit()
    return get_security_policy(user)


@router.post("/dev-passthrough", response_model=Dict[str, Any])
def set_dev_passthrough(
    payload: DevPassthroughRequest,
    request: Request,
    user=Depends(require_ai_permission("ai.security.manage")),
):
    """Enable a short-lived AI test mode from the security page.

    The mode is intentionally not persisted: restarting the process disables
    it. Provider allowlists, external-AI policy, kill switches, payload size,
    unsafe tools, and hard credential DLP checks remain enforced by the
    gateway.
    """
    # `require_ai_permission` intentionally keeps a development fallback for
    # legacy internal endpoints. Do not let that fallback operate this
    # high-impact control: it must have a real, valid Administrator session.
    authenticated_user = _get_current_user(request)
    if not authenticated_user:
        raise HTTPException(status_code=401, detail="Authentication is required to change AI temporary test mode")
    if str(authenticated_user.get("role") or "").strip().lower() not in {"administrator", "admin"}:
        raise HTTPException(status_code=403, detail="Administrator permission is required to change AI temporary test mode")
    user = authenticated_user

    if not dev_passthrough.is_supported():
        raise HTTPException(status_code=403, detail="AI and external AI must be enabled before temporary test mode can be used")
    if payload.enabled and (not ai_security_gateway.policy.external_ai_enabled or ai_security_gateway.policy.kill_switch):
        raise HTTPException(status_code=409, detail="Enable external AI and disable the global Kill Switch before starting temporary test mode")
    try:
        status = dev_passthrough.enable(payload.duration_minutes) if payload.enabled else dev_passthrough.disable()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.warning(
        "AI temporary test mode %s by user=%s expires_at=%s",
        "enabled" if status["enabled"] else "disabled",
        user.get("username", "unknown"),
        status.get("expires_at"),
    )
    return status


@router.post("/test-payload", response_model=Dict[str, Any])
def test_payload(payload: SecurityTestPayloadRequest, user=Depends(require_ai_permission("ai.audit.view"))):
    """Run the security pipeline without making an external provider call."""
    messages = [item.model_dump() for item in payload.messages]
    tenant_id = str(payload.tenant_id or user.get("tenant_id") or "tenant-default")
    task_id = payload.task_id
    try:
        result = ai_security_gateway.protect(
            messages,
            tenant_id=tenant_id,
            task_id=task_id,
            user_id=str(user.get("username") or "anonymous"),
            tools=[item for item in payload.tools] if payload.tools is not None else None,
            provider_type=payload.provider_type,
            data_classification=payload.data_classification,
            data_region=payload.data_region,
            workspace_id=payload.workspace_id,
            site_id=payload.site_id,
            document_scope=payload.document_scope,
        )
        return {
            "decision": result.action.value,
            "max_data_level": f"L{int(result.level)}",
            "finding_categories": result.metadata.get("finding_categories", []),
            "payload_bytes": len(result.as_provider_json().encode("utf-8")),
            "external_call_made": False,
            "policy_version": result.metadata.get("policy_version"),
            "classification": result.metadata.get("classification"),
        }
    except SecurityBlocked as exc:
        return {
            "decision": "BLOCK",
            "max_data_level": "L4" if any(item.level >= 4 for item in exc.findings) else "unknown",
            "finding_categories": sorted({item.category for item in exc.findings}),
            "reason_code": exc.reason_code,
            "user_message": exc.user_message,
            "external_call_made": False,
        }


@router.post("/kill-switch", response_model=Dict[str, Any])
def set_kill_switch(payload: SecurityKillSwitchRequest, user=Depends(require_ai_permission("ai.provider.manage"))):
    enabled = payload.enabled
    current = ai_security_gateway.policy
    ai_security_gateway.policy = SecurityPolicy(
        external_ai_enabled=current.external_ai_enabled,
        kill_switch=enabled,
        max_payload_bytes=current.max_payload_bytes,
        identifiers_must_be_tokenized=True,
        allow_sensitive_minimization=current.allow_sensitive_minimization,
        allowed_provider_types=current.allowed_provider_types,
        policy_version=current.policy_version,
        allowed_classifications=current.allowed_classifications,
        allowed_data_regions=current.allowed_data_regions,
        provider_kill_switches=current.provider_kill_switches,
        tenant_kill_switches=current.tenant_kill_switches,
        scope_rules=current.scope_rules,
    )
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE ai_kill_switch SET enabled = ?, reason = ?, changed_by = ?, changed_at = ? WHERE id = 1",
            (int(enabled), payload.reason, user.get("username", "admin"), _now()),
        )
        conn.commit()
    return {"enabled": enabled}


@router.post("/tenant-kill-switch", response_model=Dict[str, Any])
def set_tenant_kill_switch(payload: TenantSecurityKillSwitchRequest, user=Depends(require_ai_permission("ai.security.manage"))):
    tenant_id = str(payload.tenant_id or user.get("tenant_id") or "tenant-default")
    enabled = payload.enabled
    current = ai_security_gateway.policy
    switches = dict(current.tenant_kill_switches)
    switches[tenant_id] = enabled
    ai_security_gateway.policy = SecurityPolicy(
        external_ai_enabled=current.external_ai_enabled,
        kill_switch=current.kill_switch,
        max_payload_bytes=current.max_payload_bytes,
        identifiers_must_be_tokenized=True,
        allow_sensitive_minimization=current.allow_sensitive_minimization,
        allowed_provider_types=current.allowed_provider_types,
        policy_version=current.policy_version,
        allowed_classifications=current.allowed_classifications,
        allowed_data_regions=current.allowed_data_regions,
        provider_kill_switches=current.provider_kill_switches,
        tenant_kill_switches=switches,
        scope_rules=current.scope_rules,
    )
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_tenant_security_controls (id, tenant_id, kill_switch, reason, changed_by, changed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (tenant_id) DO UPDATE SET kill_switch = excluded.kill_switch, reason = excluded.reason, changed_by = excluded.changed_by, changed_at = excluded.changed_at
            """,
            (f"tenant_sec_{uuid.uuid4().hex[:12]}", tenant_id, int(enabled), payload.reason, user.get("username", "admin"), _now()),
        )
        conn.commit()
    return {"tenant_id": tenant_id, "enabled": enabled}


@router.get("/events", response_model=List[Dict[str, Any]])
def get_security_events(limit: int = 100, offset: int = 0, user=Depends(require_ai_permission("ai.security.events"))):
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    return list_security_events(tenant_id=tenant_id, limit=limit, offset=offset)


@router.get("/events/page", response_model=Dict[str, Any])
def get_security_events_page(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default="", max_length=256),
    decision: str = Query(default="", max_length=32),
    classification: str = Query(default="", max_length=32),
    user=Depends(require_ai_permission("ai.security.events")),
):
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    total = count_security_events(
        tenant_id=tenant_id, search=search, decision=decision, classification=classification,
    )
    total_pages = max(1, math.ceil(total / page_size))
    actual_page = min(page, total_pages)
    items = list_security_events(
        tenant_id=tenant_id, limit=page_size, offset=(actual_page - 1) * page_size,
        search=search, decision=decision, classification=classification,
    )
    return {"items": items, "total": total, "page": actual_page, "page_size": page_size, "total_pages": total_pages}


@router.get("/events/export")
def export_security_event_log(user=Depends(require_ai_permission("ai.security.events"))):
    from fastapi.responses import PlainTextResponse
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    return PlainTextResponse(export_security_events(tenant_id=tenant_id), media_type="text/csv")


@router.get("/incidents", response_model=List[Dict[str, Any]])
def get_security_incidents(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user=Depends(require_ai_permission("ai.security.incident")),
):
    try:
        return list_security_incidents(
            tenant_id=str(user.get("tenant_id") or "tenant-default"),
            status=status,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "SECURITY_INCIDENT_QUERY_INVALID", "message": "Security incident query is invalid"},
        ) from exc


@router.get("/incidents/page", response_model=Dict[str, Any])
def get_security_incidents_page(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None, max_length=32),
    severity: str = Query(default="", max_length=32),
    search: str = Query(default="", max_length=256),
    user=Depends(require_ai_permission("ai.security.incident")),
):
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    try:
        total = count_security_incidents(
            tenant_id=tenant_id, status=status, severity=severity, search=search,
        )
        total_pages = max(1, math.ceil(total / page_size))
        actual_page = min(page, total_pages)
        items = list_security_incidents(
            tenant_id=tenant_id, status=status, severity=severity, search=search,
            limit=page_size, offset=(actual_page - 1) * page_size,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "SECURITY_INCIDENT_QUERY_INVALID", "message": "Security incident query is invalid"},
        ) from exc
    return {"items": items, "total": total, "page": actual_page, "page_size": page_size, "total_pages": total_pages}


@router.post("/incidents", response_model=Dict[str, Any])
def open_security_incident(payload: SecurityIncidentRequest, user=Depends(require_ai_permission("ai.security.incident"))):
    try:
        return create_security_incident(
            tenant_id=str(user.get("tenant_id") or "tenant-default"),
            incident_type=payload.incident_type,
            severity=payload.severity,
            category=payload.category,
            task_id=payload.task_id,
            request_id=payload.request_id,
            evidence=payload.evidence,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "SECURITY_INCIDENT_INVALID", "message": "Security incident fields are invalid"},
        ) from exc


@router.post("/incidents/{incident_id}/resolve", response_model=Dict[str, Any])
def close_security_incident(incident_id: str, user=Depends(require_ai_permission("ai.security.incident"))):
    try:
        return resolve_security_incident(
            tenant_id=str(user.get("tenant_id") or "tenant-default"),
            incident_id=incident_id,
            resolved_by=str(user.get("username") or "operator"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="security incident not found") from exc


@router.get("/adapter-audit", response_model=Dict[str, Any])
def get_provider_adapter_audit(user=Depends(require_ai_permission("ai.security.incident"))):
    return audit_provider_adapters()


@router.post("/attachment-check", response_model=Dict[str, Any])
def check_attachment(payload: AttachmentCheckRequest, user=Depends(require_ai_permission("ai.assistant"))):
    """Dry-run attachment scan before a file is placed in Copilot context."""
    text = payload.text
    if len(text.encode("utf-8")) > 2_000_000:
        return {"decision": "BLOCK", "reason_code": "ATTACHMENT_TOO_LARGE", "user_message": "附件超过安全大小限制。"}
    document = ParsedDocument(
        format=payload.format,
        text=text,
        blocks=(ParsedBlock(text=text),),
        metadata={},
        parser_name="copilot-attachment-preview",
        parser_version="1",
    )
    try:
        result = scan_document_security(document)
    except Exception:
        return {"decision": "BLOCK", "classification": "SECRET", "reason_codes": ["ATTACHMENT_SCAN_FAILED"], "user_message": "附件未通过安全预检，已阻止进入 AI 上下文。"}
    decision = "BLOCK" if result.quarantined else ("MINIMIZE" if result.reason_codes else "ALLOW")
    return {
        "decision": decision,
        "classification": "SECRET" if decision == "BLOCK" else "INTERNAL",
        "reason_codes": list(result.reason_codes),
        "user_message": "附件已通过安全检查。" if decision == "ALLOW" else "附件包含不可外发内容，已阻止进入 AI 上下文。",
    }
