"""AI security policy, dry-run and metadata-only audit endpoints."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from database.core import get_db_connection
from ai.security.gateway import SecurityBlocked, SecurityPolicy, ai_security_gateway
from ai.security.classification import DataClassification, normalize_classification
from ai.security.permissions import require_ai_permission
from ai.security.security_service import (
    audit_provider_adapters,
    create_security_incident,
    export_security_events,
    list_security_events,
    list_security_incidents,
    record_security_event,
    resolve_security_incident,
)
from ai.services.document_security_scan import scan_document_security
from services.document_parser_adapters import ParsedBlock, ParsedDocument
from ai.schemas.provider import SUPPORTED_PROVIDER_TYPES

router = APIRouter(prefix="/security", tags=["AI Security Gateway"])


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
    }


@router.put("/policy", response_model=Dict[str, Any])
def update_security_policy(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.provider.manage"))):
    allowed = tuple(str(item).lower().strip().replace('-', '_') for item in payload.get("allowed_provider_types", SUPPORTED_PROVIDER_TYPES))
    if not allowed or any(item not in SUPPORTED_PROVIDER_TYPES for item in allowed):
        raise HTTPException(status_code=400, detail="Provider type is not in the approved adapter allowlist")
    classifications = tuple(str(item).upper().strip() for item in payload.get("allowed_classifications", ("PUBLIC", "INTERNAL", "CONFIDENTIAL")))
    if not classifications or any(normalize_classification(item) is None or item == DataClassification.SECRET.value for item in classifications):
        raise HTTPException(status_code=400, detail="SECRET cannot be enabled for external egress")
    regions = tuple(str(item).lower().strip() for item in payload.get("allowed_data_regions", ("unknown", "global", "cn", "us", "eu")))
    if not regions or any(not item or len(item) > 64 for item in regions):
        raise HTTPException(status_code=400, detail="allowed_data_regions must be explicit")
    provider_kill_switches = {str(key): bool(value) for key, value in (payload.get("provider_kill_switches") or {}).items()}
    tenant_kill_switches = {str(key): bool(value) for key, value in (payload.get("tenant_kill_switches") or {}).items()}
    scope_rules = payload.get("scope_rules") if isinstance(payload.get("scope_rules"), dict) else {}
    policy_version = str(payload.get("policy_version") or f"sec-{uuid.uuid4().hex[:8]}")[:64]
    policy = SecurityPolicy(
        external_ai_enabled=bool(payload.get("external_ai_enabled", False)),
        kill_switch=bool(payload.get("kill_switch", False)),
        max_payload_bytes=max(1024, min(int(payload.get("max_payload_bytes", 256000)), 2_000_000)),
        identifiers_must_be_tokenized=True,
        allow_sensitive_minimization=bool(payload.get("allow_sensitive_minimization", True)),
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


@router.post("/test-payload", response_model=Dict[str, Any])
def test_payload(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.audit.view"))):
    """Run the security pipeline without making an external provider call."""
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(status_code=422, detail="messages must be a list")
    tenant_id = str(payload.get("tenant_id") or user.get("tenant_id") or "tenant-default")
    task_id = str(payload.get("task_id") or "dry-run")
    try:
        result = ai_security_gateway.protect(
            messages,
            tenant_id=tenant_id,
            task_id=task_id,
            user_id=str(user.get("username") or "anonymous"),
            tools=payload.get("tools") if isinstance(payload.get("tools"), list) else None,
            provider_type=str(payload.get("provider_type") or "deepseek"),
            data_classification=payload.get("data_classification"),
            data_region=payload.get("data_region"),
            workspace_id=payload.get("workspace_id"),
            site_id=payload.get("site_id"),
            document_scope=payload.get("document_scope"),
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
def set_kill_switch(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.provider.manage"))):
    enabled = bool(payload.get("enabled", True))
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
            (int(enabled), str(payload.get("reason") or "operator change"), user.get("username", "admin"), _now()),
        )
        conn.commit()
    return {"enabled": enabled}


@router.post("/tenant-kill-switch", response_model=Dict[str, Any])
def set_tenant_kill_switch(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.security.manage"))):
    tenant_id = str(payload.get("tenant_id") or user.get("tenant_id") or "tenant-default")
    enabled = bool(payload.get("enabled", True))
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
            (f"tenant_sec_{uuid.uuid4().hex[:12]}", tenant_id, int(enabled), str(payload.get("reason") or "operator change"), user.get("username", "admin"), _now()),
        )
        conn.commit()
    return {"tenant_id": tenant_id, "enabled": enabled}


@router.get("/events", response_model=List[Dict[str, Any]])
def get_security_events(limit: int = 100, offset: int = 0, user=Depends(require_ai_permission("ai.security.events"))):
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    return list_security_events(tenant_id=tenant_id, limit=limit, offset=offset)


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
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/incidents", response_model=Dict[str, Any])
def open_security_incident(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.security.incident"))):
    try:
        return create_security_incident(
            tenant_id=str(user.get("tenant_id") or "tenant-default"),
            incident_type=str(payload.get("incident_type") or "policy_violation"),
            severity=str(payload.get("severity") or "high"),
            category=str(payload.get("category") or "policy"),
            task_id=str(payload.get("task_id") or "") or None,
            request_id=str(payload.get("request_id") or "") or None,
            evidence=payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
def check_attachment(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.assistant"))):
    """Dry-run attachment scan before a file is placed in Copilot context."""
    text = str(payload.get("text") or "")
    if len(text.encode("utf-8")) > 2_000_000:
        return {"decision": "BLOCK", "reason_code": "ATTACHMENT_TOO_LARGE", "user_message": "附件超过安全大小限制。"}
    document = ParsedDocument(
        format=str(payload.get("format") or "txt"),
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
