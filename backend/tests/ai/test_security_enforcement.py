"""Regression tests for the AI egress enforcement fixes (review items H1-H5).

H1  Deployment flags (AI_ENABLED / EXTERNAL_AI_ENABLED / AI_KILL_SWITCH) are a
    hard ceiling on the database policy.
H2  Policy and kill-switch changes reach every worker process.
H3  Fallback models pass the same egress checks as the primary model.
H4  A caller-declared classification can be raised, never lowered.
H5  Changing a Provider endpoint never carries the stored API key along, and
    the deployment-level endpoint allowlist is enforced.
"""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from ai.gateway import llm_gateway as gateway_module
from ai.gateway.exceptions import AINetworkException, AISecurityBlockedException
from ai.gateway.limits import AILimitManager
from ai.gateway.llm_gateway import LLMGateway
from ai.security.gateway import (
    AISecurityGateway,
    SecurityBlocked,
    SecurityPolicy,
    apply_deployment_limits,
    deployment_endpoint_allowed,
)
from core.config import settings


# ── helpers ────────────────────────────────────────────────────────────────


@pytest.fixture
def deployment_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "EXTERNAL_AI_ENABLED", True)
    monkeypatch.setattr(settings, "AI_KILL_SWITCH", False)


def _enforcing_gateway(monkeypatch: pytest.MonkeyPatch, policy: SecurityPolicy) -> AISecurityGateway:
    gateway = AISecurityGateway(policy=policy, enforce_deployment_flags=True)
    # Unit tests do not exercise the database refresh path here.
    monkeypatch.setattr(gateway, "_maybe_refresh_policy", lambda: None)
    return gateway


def _model(model_id: str, provider_id: str, *, region: str = "unknown") -> dict:
    return {
        "id": model_id,
        "model_code": model_id,
        "provider_id": provider_id,
        "provider_type": "openai",
        "allowed_data_classification": "INTERNAL",
        "data_region": region,
        "model_type": "chat",
        "enabled": True,
        "tool_call_supported": False,
        "json_supported": True,
        "thinking_supported": False,
        "stream_supported": True,
        "default_temperature": 0.0,
        "default_max_tokens": 128,
    }


def _llm_gateway(monkeypatch, security_gateway, models: dict, providers: dict) -> LLMGateway:
    limits = AILimitManager()
    limits.failure_threshold = 10
    monkeypatch.setattr(gateway_module, "ai_limits", limits)
    gateway = LLMGateway(security_gateway=security_gateway)
    monkeypatch.setattr(gateway, "_get_model_details", lambda model_id: models[str(model_id)])
    monkeypatch.setattr(gateway, "_authorize_model", lambda *_a, **_k: None)
    monkeypatch.setattr(gateway, "_get_provider_instance", lambda provider_id: providers[str(provider_id)])
    monkeypatch.setattr(gateway, "_budget_exceeded", lambda **_k: False)
    monkeypatch.setattr(gateway, "_log_request", lambda **_k: None)
    monkeypatch.setattr(gateway, "_log_security_audit", lambda **_k: None)
    monkeypatch.setattr(gateway_module.asyncio, "sleep", AsyncMock())
    return gateway


def _route_with_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        gateway_module.model_router,
        "resolve_route_policy",
        lambda scene: ("model-primary", "model-fallback", "scene_route", None),
    )


MESSAGES = [{"role": "user", "content": "Reply with ok"}]


# ── H1: deployment flags are a hard ceiling ───────────────────────────────


def test_h1_env_disable_caps_a_db_policy_that_enables_egress(monkeypatch):
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "EXTERNAL_AI_ENABLED", False)
    monkeypatch.setattr(settings, "AI_KILL_SWITCH", False)
    capped = apply_deployment_limits(SecurityPolicy(external_ai_enabled=True))
    assert capped.external_ai_enabled is False


def test_h1_ai_disabled_caps_egress(monkeypatch):
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    monkeypatch.setattr(settings, "EXTERNAL_AI_ENABLED", True)
    monkeypatch.setattr(settings, "AI_KILL_SWITCH", False)
    assert apply_deployment_limits(SecurityPolicy(external_ai_enabled=True)).external_ai_enabled is False


def test_h1_env_kill_switch_wins_over_db(monkeypatch, deployment_on):
    monkeypatch.setattr(settings, "AI_KILL_SWITCH", True)
    capped = apply_deployment_limits(SecurityPolicy(external_ai_enabled=True, kill_switch=False))
    assert capped.kill_switch is True


def test_h1_env_flags_cannot_enable_what_the_db_disabled(deployment_on):
    capped = apply_deployment_limits(SecurityPolicy(external_ai_enabled=False, kill_switch=True))
    assert capped.external_ai_enabled is False
    assert capped.kill_switch is True


def test_h1_protect_blocks_when_env_kill_switch_is_set(monkeypatch, deployment_on):
    monkeypatch.setattr(settings, "AI_KILL_SWITCH", True)
    gateway = _enforcing_gateway(monkeypatch, SecurityPolicy(external_ai_enabled=True))
    with pytest.raises(SecurityBlocked) as exc_info:
        gateway.protect(MESSAGES)
    assert exc_info.value.reason_code == "AI_SECURITY_KILL_SWITCH"


def test_h1_protect_blocks_when_env_disables_external_ai(monkeypatch, deployment_on):
    monkeypatch.setattr(settings, "EXTERNAL_AI_ENABLED", False)
    gateway = _enforcing_gateway(monkeypatch, SecurityPolicy(external_ai_enabled=True))
    with pytest.raises(SecurityBlocked) as exc_info:
        gateway.protect(MESSAGES)
    assert exc_info.value.reason_code == "AI_SECURITY_POLICY_DISABLED"


def test_h1_explicit_policy_passed_to_enforcing_gateway_is_also_capped(monkeypatch, deployment_on):
    monkeypatch.setattr(settings, "AI_KILL_SWITCH", True)
    gateway = _enforcing_gateway(monkeypatch, SecurityPolicy())
    with pytest.raises(SecurityBlocked):
        gateway.protect(MESSAGES, policy=SecurityPolicy(external_ai_enabled=True))


def test_h1_process_wide_gateway_enforces_deployment_flags():
    from ai.security.gateway import ai_security_gateway

    assert ai_security_gateway.enforce_deployment_flags is True


@pytest.mark.anyio
async def test_h1_llm_gateway_blocks_before_any_provider_call(monkeypatch, deployment_on):
    monkeypatch.setattr(settings, "EXTERNAL_AI_ENABLED", False)
    provider = SimpleNamespace(max_retries=0, chat=AsyncMock(return_value={"content": "ok"}))
    security = _enforcing_gateway(monkeypatch, SecurityPolicy(external_ai_enabled=True))
    gateway = _llm_gateway(monkeypatch, security, {"m": _model("m", "p")}, {"p": provider})
    with pytest.raises(AISecurityBlockedException):
        await gateway.chat(scene="provider_test", model_id="m", messages=MESSAGES, data_classification="PUBLIC")
    provider.chat.assert_not_awaited()


# ── H2: policy changes reach every worker ──────────────────────────────────


def _refreshing_gateway(monkeypatch, initial: SecurityPolicy, fingerprint, *, reloaded: SecurityPolicy, current_fp):
    import ai.api.security as security_api

    gateway = AISecurityGateway(enforce_deployment_flags=True)
    gateway.install_policy(initial, fingerprint=fingerprint)
    monkeypatch.setattr(settings, "AI_POLICY_REFRESH_SECONDS", 0)
    calls = {"reload": 0}

    def fake_reload() -> None:
        calls["reload"] += 1
        gateway.install_policy(reloaded, fingerprint=current_fp)

    monkeypatch.setattr(security_api, "read_policy_fingerprint", lambda: current_fp)
    monkeypatch.setattr(security_api, "load_persisted_security_policy", fake_reload)
    return gateway, calls


def test_h2_kill_switch_set_by_another_worker_is_picked_up(monkeypatch, deployment_on):
    gateway, calls = _refreshing_gateway(
        monkeypatch,
        SecurityPolicy(external_ai_enabled=True),
        ("v1",),
        reloaded=SecurityPolicy(external_ai_enabled=True, kill_switch=True),
        current_fp=("v2",),
    )
    assert gateway.effective_policy().kill_switch is True
    assert calls["reload"] == 1


def test_h2_unchanged_fingerprint_does_not_reload(monkeypatch, deployment_on):
    gateway, calls = _refreshing_gateway(
        monkeypatch,
        SecurityPolicy(external_ai_enabled=True),
        ("v1",),
        reloaded=SecurityPolicy(kill_switch=True),
        current_fp=("v1",),
    )
    assert gateway.effective_policy().kill_switch is False
    assert calls["reload"] == 0


def test_h2_failed_startup_load_recovers_when_database_returns(monkeypatch, deployment_on):
    gateway, calls = _refreshing_gateway(
        monkeypatch,
        SecurityPolicy(external_ai_enabled=False, kill_switch=True),
        ("load_failed",),
        reloaded=SecurityPolicy(external_ai_enabled=True),
        current_fp=("v1",),
    )
    assert gateway.effective_policy().external_ai_enabled is True
    assert calls["reload"] == 1


def test_h2_policy_replaced_outside_install_is_left_alone(monkeypatch, deployment_on):
    gateway, calls = _refreshing_gateway(
        monkeypatch,
        SecurityPolicy(external_ai_enabled=True),
        ("v1",),
        reloaded=SecurityPolicy(kill_switch=True),
        current_fp=("v2",),
    )
    gateway.policy = SecurityPolicy(external_ai_enabled=True)  # e.g. a fixture or operator tool
    assert gateway.effective_policy().kill_switch is False
    assert calls["reload"] == 0


def test_h2_policy_endpoints_no_longer_assign_the_singleton_directly():
    import ai.api.security as security_api

    source = inspect.getsource(security_api)
    assert "ai_security_gateway.policy = " not in source
    assert source.count("install_policy(") >= 4


# ── H3: fallback passes the same egress checks ────────────────────────────


@pytest.mark.anyio
async def test_h3_fallback_to_kill_switched_provider_is_refused(monkeypatch):
    _route_with_fallback(monkeypatch)
    primary = SimpleNamespace(max_retries=0, chat=AsyncMock(side_effect=AINetworkException()))
    fallback = SimpleNamespace(max_retries=0, chat=AsyncMock(return_value={"content": "leaked", "input_tokens": 1, "output_tokens": 1}))
    security = AISecurityGateway(policy=SecurityPolicy(external_ai_enabled=True, provider_kill_switches={"provider-fallback": True}))
    gateway = _llm_gateway(
        monkeypatch,
        security,
        {"model-primary": _model("model-primary", "provider-primary"), "model-fallback": _model("model-fallback", "provider-fallback")},
        {"provider-primary": primary, "provider-fallback": fallback},
    )
    with pytest.raises(AINetworkException):
        await gateway.chat(scene="chat", messages=MESSAGES, data_classification="PUBLIC")
    fallback.chat.assert_not_awaited()


@pytest.mark.anyio
async def test_h3_fallback_in_a_disallowed_region_is_refused(monkeypatch):
    _route_with_fallback(monkeypatch)
    primary = SimpleNamespace(max_retries=0, chat=AsyncMock(side_effect=AINetworkException()))
    fallback = SimpleNamespace(max_retries=0, chat=AsyncMock(return_value={"content": "leaked", "input_tokens": 1, "output_tokens": 1}))
    security = AISecurityGateway(policy=SecurityPolicy(external_ai_enabled=True, allowed_data_regions=("cn",)))
    gateway = _llm_gateway(
        monkeypatch,
        security,
        {
            "model-primary": _model("model-primary", "provider-primary", region="cn"),
            "model-fallback": _model("model-fallback", "provider-fallback", region="us"),
        },
        {"provider-primary": primary, "provider-fallback": fallback},
    )
    with pytest.raises(AINetworkException):
        await gateway.chat(scene="chat", messages=MESSAGES, data_classification="PUBLIC")
    fallback.chat.assert_not_awaited()


@pytest.mark.anyio
async def test_h3_eligible_fallback_still_works(monkeypatch):
    _route_with_fallback(monkeypatch)
    primary = SimpleNamespace(max_retries=0, chat=AsyncMock(side_effect=AINetworkException()))
    fallback = SimpleNamespace(max_retries=0, chat=AsyncMock(return_value={"content": "ok", "input_tokens": 1, "output_tokens": 1}))
    security = AISecurityGateway(policy=SecurityPolicy(external_ai_enabled=True))
    gateway = _llm_gateway(
        monkeypatch,
        security,
        {"model-primary": _model("model-primary", "provider-primary"), "model-fallback": _model("model-fallback", "provider-fallback")},
        {"provider-primary": primary, "provider-fallback": fallback},
    )
    result = await gateway.chat(scene="chat", messages=MESSAGES, data_classification="PUBLIC")
    assert result["fallback_used"] is True
    fallback.chat.assert_awaited_once()


def test_h3_assert_egress_allowed_checks_provider_kill_switch_by_id():
    gateway = AISecurityGateway(policy=SecurityPolicy(external_ai_enabled=True, provider_kill_switches={"prov_x": True}))
    with pytest.raises(SecurityBlocked) as exc_info:
        gateway.assert_egress_allowed(provider_type="openai", provider_id="prov_x")
    assert exc_info.value.reason_code == "AI_SECURITY_KILL_SWITCH"


# ── H4: declared classification can only be raised ───────────────────────


IDENTIFIER_MESSAGES = [{"role": "user", "content": "Explain why device 10.20.30.40 lost its uplink"}]


def test_h4_public_declaration_with_identifiers_is_raised_to_internal():
    gateway = AISecurityGateway(policy=SecurityPolicy(external_ai_enabled=True))
    payload = gateway.protect(
        IDENTIFIER_MESSAGES,
        data_classification="PUBLIC",
        provider_allowed_classification="INTERNAL",
    )
    assert payload.metadata["classification"] == "INTERNAL"


def test_h4_public_only_provider_rejects_identifier_content_declared_public():
    gateway = AISecurityGateway(policy=SecurityPolicy(external_ai_enabled=True))
    with pytest.raises(SecurityBlocked) as exc_info:
        gateway.protect(
            IDENTIFIER_MESSAGES,
            data_classification="PUBLIC",
            provider_allowed_classification="PUBLIC",
        )
    assert exc_info.value.reason_code == "AI_SECURITY_CLASSIFICATION_DENIED"


def test_h4_plain_text_keeps_its_public_declaration():
    gateway = AISecurityGateway(policy=SecurityPolicy(external_ai_enabled=True))
    payload = gateway.protect(MESSAGES, data_classification="PUBLIC", provider_allowed_classification="PUBLIC")
    assert payload.metadata["classification"] == "PUBLIC"


def test_h4_agent_runner_no_longer_declares_public():
    from ai.agents import runner

    source = inspect.getsource(runner)
    assert 'data_classification="PUBLIC"' not in source


# ── H5: endpoint change and deployment allowlist ──────────────────────────


def test_h5_deployment_allowlist_matching(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "api.deepseek.com, *.openai.azure.com")
    assert deployment_endpoint_allowed("https://api.deepseek.com")
    assert deployment_endpoint_allowed("https://my-res.openai.azure.com/openai")
    assert not deployment_endpoint_allowed("https://attacker.example.com")
    assert not deployment_endpoint_allowed("https://api.deepseek.com.attacker.example")


def test_h5_empty_deployment_allowlist_adds_no_limit(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "")
    assert deployment_endpoint_allowed("https://anything.example.com")


def _create_provider_with_key(base_url: str):
    from ai.api.providers import create_provider
    from ai.schemas.provider import AIProviderCreate
    from database.core import get_db_connection

    user = {"username": "admin", "role": "Administrator"}
    created = create_provider(
        AIProviderCreate(name=f"Compat-{uuid.uuid4().hex[:6]}", provider_type="openai_compatible", base_url=base_url),
        user=user,
    )
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE ai_provider SET api_key_encrypted = ?, api_key_masked = ? WHERE id = ?",
            ("stored-ciphertext", "sk-****abcd", created.id),
        )
        conn.commit()
    return created, user


def test_h5_changing_the_host_clears_the_stored_key_and_audits(isolated_db):
    from ai.api.providers import update_provider
    from ai.schemas.provider import AIProviderUpdate
    from database.core import get_db_connection

    created, user = _create_provider_with_key("https://api.example-a.com/v1")
    updated = update_provider(created.id, AIProviderUpdate(base_url="https://api.example-b.com/v1"), user=user)

    assert updated.base_url == "https://api.example-b.com/v1"
    assert not updated.api_key_masked
    with get_db_connection() as conn:
        stored = conn.execute("SELECT api_key_encrypted FROM ai_provider WHERE id = ?", (created.id,)).fetchone()
        audit = conn.execute(
            "SELECT action, reason_code FROM ai_provider_key_audit WHERE provider_id = ?",
            (created.id,),
        ).fetchall()
    assert stored[0] is None
    assert ("invalidate", "endpoint_changed") in [tuple(row) for row in audit]


def test_h5_changing_the_type_clears_the_stored_key(isolated_db):
    from ai.api.providers import update_provider
    from ai.schemas.provider import AIProviderUpdate

    created, user = _create_provider_with_key("https://api.example-a.com/v1")
    updated = update_provider(created.id, AIProviderUpdate(provider_type="openai"), user=user)
    assert not updated.api_key_masked


def test_h5_same_host_path_change_keeps_the_key(isolated_db):
    from ai.api.providers import update_provider
    from ai.schemas.provider import AIProviderUpdate

    created, user = _create_provider_with_key("https://api.example-a.com/v1")
    updated = update_provider(created.id, AIProviderUpdate(base_url="https://api.example-a.com/v2"), user=user)
    assert updated.api_key_masked == "sk-****abcd"


def test_h5_unrelated_edit_keeps_the_key(isolated_db):
    from ai.api.providers import update_provider
    from ai.schemas.provider import AIProviderUpdate

    created, user = _create_provider_with_key("https://api.example-a.com/v1")
    updated = update_provider(created.id, AIProviderUpdate(timeout=45), user=user)
    assert updated.api_key_masked == "sk-****abcd"


def test_h5_create_outside_the_deployment_allowlist_is_rejected(isolated_db, monkeypatch):
    from ai.api.providers import create_provider
    from ai.schemas.provider import AIProviderCreate

    monkeypatch.setattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "api.example-a.com")
    with pytest.raises(HTTPException) as exc_info:
        create_provider(
            AIProviderCreate(name=f"Compat-{uuid.uuid4().hex[:6]}", provider_type="openai_compatible", base_url="https://api.example-b.com/v1"),
            user={"username": "admin", "role": "Administrator"},
        )
    assert exc_info.value.status_code == 400


def test_h5_update_to_a_host_outside_the_deployment_allowlist_is_rejected(isolated_db, monkeypatch):
    from ai.api.providers import update_provider
    from ai.schemas.provider import AIProviderUpdate

    created, user = _create_provider_with_key("https://api.example-a.com/v1")
    monkeypatch.setattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "api.example-a.com")
    with pytest.raises(HTTPException) as exc_info:
        update_provider(created.id, AIProviderUpdate(base_url="https://attacker.example.com/v1"), user=user)
    assert exc_info.value.status_code == 400
