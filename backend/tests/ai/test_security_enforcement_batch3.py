"""Regression tests for the third batch of AI review fixes (medium risk).

M1   A requested/routed model that is missing is an error, not silently replaced.
M2   Model ACL lookup failures deny access.
M5   AI_BUDGET_FAIL_CLOSED is a real setting and defaults to fail closed.
M6   Configuration blocks no longer open one "high" incident per request.
M7   Request logs / usage / cost need ai.usage.view (Administrator by default).
M8   Policy and kill-switch changes need ai.security.manage and are audited.
M13  Embedding egress evidence is bounded.
M15  Copilot has a per-user daily request limit.
M18  Public web search is off unless enabled.
L8   Security dry runs always use the caller's tenant.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from ai.gateway import llm_gateway as gateway_module
from ai.gateway.exceptions import AIModelNotFoundException
from ai.gateway.llm_gateway import LLMGateway
from ai.security.gateway import AISecurityGateway, SecurityPolicy, ai_security_gateway
from ai.security.permissions import ROLE_AI_PERMISSIONS
from core.config import settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── M1 ────────────────────────────────────────────────────────────────────


def _insert_model(*, provider_enabled: int = 1, model_enabled: int = 1) -> str:
    from database.core import get_db_connection

    provider_id = f"prov_{uuid.uuid4().hex[:10]}"
    model_id = f"model_{uuid.uuid4().hex[:10]}"
    now = _now()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ai_provider (id, name, provider_type, base_url, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (provider_id, f"P-{provider_id}", "openai_compatible", "https://example.invalid/v1", provider_enabled, now, now),
        )
        conn.execute(
            "INSERT INTO ai_model (id, provider_id, name, model_code, model_type, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, 'chat', ?, ?, ?)",
            (model_id, provider_id, f"M-{model_id}", f"code-{model_id}", model_enabled, now, now),
        )
        conn.commit()
    return model_id


def test_m1_unknown_model_is_not_replaced(isolated_db):
    _insert_model()
    with pytest.raises(AIModelNotFoundException):
        LLMGateway()._get_model_details("model-that-does-not-exist")


def test_m1_model_on_a_disabled_provider_is_not_replaced(isolated_db):
    model_id = _insert_model(provider_enabled=0)
    with pytest.raises(AIModelNotFoundException):
        LLMGateway()._get_model_details(model_id)


def test_m1_existing_model_is_returned(isolated_db):
    model_id = _insert_model()
    assert LLMGateway()._get_model_details(model_id)["id"] == model_id


def test_m1_no_request_still_uses_the_system_default(isolated_db):
    _insert_model()
    info = LLMGateway()._get_model_details(None)
    assert info["id"]


# ── M2 ────────────────────────────────────────────────────────────────────


def test_m2_acl_lookup_failure_denies(monkeypatch):
    def broken():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(gateway_module, "get_db_connection", broken)
    with pytest.raises(AIModelNotFoundException):
        LLMGateway()._authorize_model({"id": "m"}, tenant_id="tenant-default", user_id="alice", roles=["Operator"])


# ── M5 ────────────────────────────────────────────────────────────────────


def test_m5_budget_fails_closed_when_spend_cannot_be_read(monkeypatch):
    def broken():
        raise RuntimeError("database unavailable")

    assert settings.AI_BUDGET_FAIL_CLOSED is True
    monkeypatch.setattr(settings, "AI_DAILY_BUDGET_USD", 10.0)
    monkeypatch.setattr(gateway_module, "get_db_connection", broken)
    assert LLMGateway()._budget_exceeded(provider_id="p", model_id="m") is True


def test_m5_no_budget_never_blocks(monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_BUDGET_USD", 0.0)
    assert LLMGateway()._budget_exceeded(provider_id="p", model_id="m") is False


# ── M6 ────────────────────────────────────────────────────────────────────


@pytest.fixture
def audit_sinks(monkeypatch):
    incidents: list[dict] = []

    def broken():
        raise RuntimeError("no audit table in this unit test")

    monkeypatch.setattr(gateway_module, "get_db_connection", broken)
    monkeypatch.setattr(gateway_module, "record_security_event", lambda **_k: "event")
    monkeypatch.setattr(gateway_module, "create_security_incident", lambda **kwargs: incidents.append(kwargs) or {})
    return incidents


def _audit(gateway: LLMGateway, error_code: str) -> None:
    gateway._log_security_audit(
        request_id="r1", tenant_id="tenant-default", task_id="t1", scene="chat",
        provider_type="openai", model_code="m", decision="BLOCK", status="blocked", error_code=error_code,
    )


@pytest.mark.parametrize("code", ["AI_SECURITY_BLOCKED", "AI_SECURITY_POLICY_DISABLED", "AI_SECURITY_KILL_SWITCH", "AI_SECURITY_PROVIDER_DENIED", "AI_SECURITY_SCOPE_DENIED"])
def test_m6_configuration_blocks_do_not_open_incidents(audit_sinks, code):
    _audit(LLMGateway(security_gateway=AISecurityGateway(policy=SecurityPolicy())), code)
    assert audit_sinks == []


@pytest.mark.parametrize("code", ["AI_SECURITY_SENSITIVE_DATA", "AI_SECURITY_DLP_FAILED", "AI_SECURITY_UNSAFE_TOOL"])
def test_m6_content_blocks_still_open_incidents(audit_sinks, code):
    _audit(LLMGateway(security_gateway=AISecurityGateway(policy=SecurityPolicy())), code)
    assert len(audit_sinks) == 1


# ── M7 ────────────────────────────────────────────────────────────────────


def test_m7_usage_endpoints_require_usage_view():
    from ai.api import usage

    source = inspect.getsource(usage)
    assert source.count('require_ai_permission("ai.usage.view")') == 3
    assert 'require_ai_permission("ai.audit.view")' not in source


def test_m7_only_administrators_get_usage_view_by_default():
    assert "ai.usage.view" in ROLE_AI_PERMISSIONS["Administrator"]
    assert "ai.usage.view" not in ROLE_AI_PERMISSIONS["Operator"]
    assert "ai.usage.view" not in ROLE_AI_PERMISSIONS["Viewer"]


# ── M8 / L8 ───────────────────────────────────────────────────────────────


def test_m8_policy_and_kill_switch_need_security_manage():
    from ai.api import security

    source = inspect.getsource(security)
    assert 'def update_security_policy(payload: SecurityPolicyUpdateRequest, user=Depends(require_ai_permission("ai.security.manage")))' in source
    assert 'def set_kill_switch(payload: SecurityKillSwitchRequest, user=Depends(require_ai_permission("ai.security.manage")))' in source


def test_m8_kill_switch_change_is_audited(isolated_db, monkeypatch):
    from ai.api import security
    from api.knowledge_contracts import SecurityKillSwitchRequest

    # Keep the process-wide policy unchanged for the rest of the suite.
    for name in ("policy", "_synced_policy", "_synced_fingerprint"):
        monkeypatch.setattr(ai_security_gateway, name, getattr(ai_security_gateway, name))
    events: list[dict] = []
    monkeypatch.setattr(security, "log_audit_event", lambda **kwargs: events.append(kwargs) or "audit")

    security.set_kill_switch(SecurityKillSwitchRequest(enabled=False, reason="drill"), user={"username": "admin", "role": "Administrator"})

    assert [event["event_type"] for event in events] == ["AI_KILL_SWITCH_DISABLE"]
    assert events[0]["category"] == "ai_security"
    assert events[0]["details"] == {"reason": "drill"}
    assert events[0]["actor_username"] == "admin"


def test_l8_dry_run_uses_the_callers_tenant(monkeypatch):
    from ai.api import security
    from api.knowledge_contracts import SecurityTestPayloadRequest

    seen: dict = {}

    class _Result:
        action = type("A", (), {"value": "ALLOW"})()
        level = 1
        metadata: dict = {}

        def as_provider_json(self) -> str:
            return "{}"

    def fake_protect(messages, **kwargs):
        seen.update(kwargs)
        return _Result()

    monkeypatch.setattr(security.ai_security_gateway, "protect", fake_protect)
    payload = SecurityTestPayloadRequest.model_validate({"messages": [{"role": "user", "content": "hello"}], "tenant_id": "tenant-b"})
    security.test_payload(payload, user={"username": "alice", "tenant_id": "tenant-a", "role": "Operator"})
    assert seen["tenant_id"] == "tenant-a"


# ── M13 ───────────────────────────────────────────────────────────────────


def test_m13_embedding_evidence_is_bounded():
    gateway = AISecurityGateway(policy=SecurityPolicy())
    assert gateway._egress_audit_events.maxlen == 1000


# ── M15 ───────────────────────────────────────────────────────────────────


@pytest.fixture
def quota_exhausted(monkeypatch):
    from ai.security import rate_limit

    async def deny(*_a, **_k):
        return False, 0

    monkeypatch.setattr(rate_limit.ai_rate_limiter, "is_allowed_async", deny)


def test_m15_copilot_chat_enforces_the_daily_limit(quota_exhausted):
    from ai.api import assistant as assistant_api

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(assistant_api.chat_assistant(assistant_api.ChatRequest(message="hello"), user={"username": "alice", "role": "Operator"}))
    assert exc_info.value.status_code == 429


def test_m15_copilot_stream_enforces_the_daily_limit_and_frees_the_stream(quota_exhausted):
    from ai.api import assistant as assistant_api

    assistant_api.sse_stream_registry.clear()
    request = assistant_api.ChatRequest(message="hello", stream_id="sse_quota_test")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(assistant_api.chat_assistant_stream(request, user={"username": "alice", "role": "Operator"}))
    assert exc_info.value.status_code == 429
    # The stream id is released so the user can retry later.
    with pytest.raises(HTTPException) as again:
        asyncio.run(assistant_api.chat_assistant_stream(request, user={"username": "alice", "role": "Operator"}))
    assert again.value.status_code == 429


# ── M18 ───────────────────────────────────────────────────────────────────


def test_m18_web_search_is_off_by_default():
    from core import config
    from ai.services import web_retrieval

    assert "AI_WEB_SEARCH_ENABLED: bool = False" in inspect.getsource(config)
    assert 'getattr(settings, "AI_WEB_SEARCH_ENABLED", True)' not in inspect.getsource(web_retrieval)
