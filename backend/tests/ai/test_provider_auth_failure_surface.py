from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from ai.gateway.exceptions import AICircuitOpenException, AIAuthFailedException
from ai.gateway.limits import AILimitManager
from ai.gateway.llm_gateway import LLMGateway
from ai.providers.openai_compatible import OpenAICompatibleProvider
from ai.security.gateway import AISecurityGateway, SecurityPolicy


class _Response:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _Client:
    def __init__(self, response: _Response, **_kwargs):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **_kwargs):
        return self.response


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_openai_compatible_provider_maps_auth_status_to_stable_auth_code(monkeypatch, status_code):
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: _Client(_Response(status_code), **kwargs),
    )
    provider = OpenAICompatibleProvider(
        {"id": "prov-test", "name": "test", "provider_type": "openai", "base_url": "https://api.example.com"},
        api_key="intentionally-wrong",
    )

    with pytest.raises(AIAuthFailedException) as exc_info:
        await provider.chat(
            [{"role": "user", "content": "Reply with one short word: ok"}],
            model="test-model",
        )

    assert exc_info.value.code == "AI_AUTH_FAILED"


@pytest.mark.asyncio
async def test_llm_gateway_does_not_retry_or_open_circuit_for_auth_failure(monkeypatch):
    import importlib

    llm_module = importlib.import_module("ai.gateway.llm_gateway")
    limits = AILimitManager()
    monkeypatch.setattr(llm_module, "ai_limits", limits)

    gateway = LLMGateway(
        security_gateway=AISecurityGateway(
            policy=SecurityPolicy(external_ai_enabled=True),
        ),
    )
    model = {
        "id": "model-test",
        "model_code": "test-model",
        "provider_id": "prov-test",
        "provider_type": "openai",
        "allowed_data_classification": "PUBLIC",
        "data_region": "unknown",
        "model_type": "chat",
        "enabled": True,
        "tool_call_supported": False,
        "json_supported": False,
        "thinking_supported": False,
        "stream_supported": True,
        "default_temperature": 0.7,
        "default_max_tokens": 128,
    }
    provider = SimpleNamespace(
        max_retries=3,
        chat=AsyncMock(side_effect=AIAuthFailedException()),
    )
    monkeypatch.setattr(gateway, "_get_model_details", lambda _model: model)
    monkeypatch.setattr(gateway, "_authorize_model", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gateway, "_get_provider_instance", lambda _provider_id: provider)
    monkeypatch.setattr(gateway, "_budget_exceeded", lambda **_kwargs: False)
    monkeypatch.setattr(gateway, "_log_request", lambda **_kwargs: None)
    monkeypatch.setattr(gateway, "_log_security_audit", lambda **_kwargs: None)

    with pytest.raises(AIAuthFailedException) as exc_info:
        await gateway.chat(
            scene="provider_test",
            model_id="model-test",
            messages=[{"role": "user", "content": "Reply with one short word: ok"}],
            user_id="admin",
            tenant_id="tenant-default",
            data_classification="PUBLIC",
        )

    assert exc_info.value.code == "AI_AUTH_FAILED"
    assert provider.chat.await_count == 1
    assert limits._circuits.get("prov-test") is None


def test_provider_config_change_resets_open_circuit():
    limits = AILimitManager()
    limits.failure_threshold = 1
    limits.cooldown_seconds = 60
    limits.record_failure("prov-test")

    with pytest.raises(AICircuitOpenException):
        limits._check_circuit("prov-test")

    limits.reset_provider("prov-test")
    limits._check_circuit("prov-test")
