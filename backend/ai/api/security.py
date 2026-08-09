"""AI security policy, dry-run and metadata-only audit endpoints."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from database.core import get_db_connection
from ai.security.gateway import SecurityBlocked, SecurityPolicy, ai_security_gateway
from ai.security.permissions import require_ai_permission

router = APIRouter(prefix="/security", tags=["AI Security Gateway"])


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_persisted_security_policy() -> None:
    """Load the last operator policy after migrations, fail-closed on errors."""
    try:
        with get_db_connection() as conn:
            policy_row = conn.execute(
                "SELECT external_ai_enabled, rules_json, provider_allowlist_json FROM ai_security_policies WHERE status = 'active' ORDER BY version DESC LIMIT 1"
            ).fetchone()
            kill_row = conn.execute("SELECT enabled FROM ai_kill_switch WHERE id = 1").fetchone()
        current = ai_security_gateway.policy
        external_enabled = bool(policy_row[0]) if policy_row else current.external_ai_enabled
        allow_sensitive = current.allow_sensitive_minimization
        allowed = current.allowed_provider_types
        if policy_row:
            try:
                rules = json.loads(policy_row[1] or '{}')
                allow_sensitive = bool(rules.get('allow_sensitive_minimization', allow_sensitive))
            except Exception:
                pass
            try:
                candidate = tuple(str(item).lower() for item in json.loads(policy_row[2] or '[]'))
                if candidate and set(candidate) <= {'deepseek'}:
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
    }


@router.put("/policy", response_model=Dict[str, Any])
def update_security_policy(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.provider.manage"))):
    allowed = tuple(str(item).lower() for item in payload.get("allowed_provider_types", ["deepseek"]))
    if not allowed or any(item != "deepseek" for item in allowed):
        raise HTTPException(status_code=400, detail="Only the approved DeepSeek provider is allowed")
    policy = SecurityPolicy(
        external_ai_enabled=bool(payload.get("external_ai_enabled", False)),
        kill_switch=bool(payload.get("kill_switch", False)),
        max_payload_bytes=max(1024, min(int(payload.get("max_payload_bytes", 256000)), 2_000_000)),
        identifiers_must_be_tokenized=True,
        allow_sensitive_minimization=bool(payload.get("allow_sensitive_minimization", True)),
        allowed_provider_types=allowed,
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
                json.dumps({"allow_sensitive_minimization": policy.allow_sensitive_minimization}),
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
            provider_type="deepseek",
        )
        return {
            "decision": result.action.value,
            "max_data_level": f"L{int(result.level)}",
            "finding_categories": result.metadata.get("finding_categories", []),
            "payload_bytes": len(result.as_provider_json().encode("utf-8")),
            "external_call_made": False,
        }
    except SecurityBlocked as exc:
        return {
            "decision": "BLOCK",
            "max_data_level": "L4" if any(item.level >= 4 for item in exc.findings) else "unknown",
            "finding_categories": sorted({item.category for item in exc.findings}),
            "reason": "policy_block",
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
    )
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE ai_kill_switch SET enabled = ?, reason = ?, changed_by = ?, changed_at = ? WHERE id = 1",
            (int(enabled), str(payload.get("reason") or "operator change"), user.get("username", "admin"), _now()),
        )
        conn.commit()
    return {"enabled": enabled}
