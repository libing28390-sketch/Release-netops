from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai.gateway import llm_gateway as gateway_module
from ai.gateway.exceptions import (
    AICircuitOpenException,
    AINetworkException,
    AIOutputTruncatedException,
    AIRateLimitException,
    AIProviderTimeoutException,
    AIQuotaExceededException,
)
from ai.gateway.limits import AILimitManager
from ai.gateway.llm_gateway import LLMGateway
from ai.security.gateway import AISecurityGateway, SecurityPolicy


def _model(model_id: str, provider_id: str = "provider-primary") -> dict:
    return {
        "id": model_id,
        "model_code": model_id,
        "provider_id": provider_id,
        "provider_type": "openai",
        "allowed_data_classification": "PUBLIC",
        "data_region": "unknown",
        "model_type": "chat",
        "enabled": True,
        "tool_call_supported": False,
        "json_supported": True,
        "thinking_supported": False,
        "stream_supported": True,
        "default_temperature": 0.0,
        "default_max_tokens": 128,
    }


def _gateway(monkeypatch: pytest.MonkeyPatch, models: dict[str, dict], providers: dict[str, object]) -> LLMGateway:
    limits = AILimitManager()
    limits.failure_threshold = 10
    monkeypatch.setattr(gateway_module, "ai_limits", limits)
    gateway = LLMGateway(
        security_gateway=AISecurityGateway(
            policy=SecurityPolicy(external_ai_enabled=True),
        ),
    )
    monkeypatch.setattr(gateway, "_get_model_details", lambda model_id: models[str(model_id)])
    monkeypatch.setattr(gateway, "_authorize_model", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gateway, "_get_provider_instance", lambda provider_id: providers[str(provider_id)])
    monkeypatch.setattr(gateway, "_budget_exceeded", lambda **_kwargs: False)
    monkeypatch.setattr(gateway, "_log_request", lambda **_kwargs: None)
    monkeypatch.setattr(gateway, "_log_security_audit", lambda **_kwargs: None)
    return gateway


@pytest.mark.anyio
async def test_gateway_retries_provider_429_once_and_returns_success(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = SimpleNamespace(
        max_retries=1,
        chat=AsyncMock(side_effect=[
            AIRateLimitException(),
            {"content": "ok", "input_tokens": 3, "output_tokens": 2},
        ]),
    )
    gateway = _gateway(monkeypatch, {"model-primary": _model("model-primary")}, {"provider-primary": provider})
    monkeypatch.setattr(gateway_module.asyncio, "sleep", AsyncMock())

    result = await gateway.chat(
        scene="provider_test",
        model_id="model-primary",
        messages=[{"role": "user", "content": "Reply with ok"}],
        user_id="admin",
        tenant_id="tenant-default",
        data_classification="PUBLIC",
    )

    assert result["content"] == "ok"
    assert provider.chat.await_count == 2


@pytest.mark.anyio
async def test_gateway_retries_provider_timeout_once_and_keeps_stable_error_if_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = SimpleNamespace(
        max_retries=1,
        chat=AsyncMock(side_effect=[AIProviderTimeoutException(), AIProviderTimeoutException()]),
    )
    gateway = _gateway(monkeypatch, {"model-primary": _model("model-primary")}, {"provider-primary": provider})
    monkeypatch.setattr(gateway_module.asyncio, "sleep", AsyncMock())

    with pytest.raises(AIProviderTimeoutException) as exc_info:
        await gateway.chat(
            scene="provider_test",
            model_id="model-primary",
            messages=[{"role": "user", "content": "Reply with ok"}],
            user_id="admin",
            tenant_id="tenant-default",
            data_classification="PUBLIC",
        )

    assert exc_info.value.code == "AI_PROVIDER_TIMEOUT"
    assert provider.chat.await_count == 2


@pytest.mark.anyio
async def test_gateway_does_not_retry_or_open_circuit_on_output_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = SimpleNamespace(
        max_retries=3,
        chat=AsyncMock(side_effect=AIOutputTruncatedException()),
    )
    gateway = _gateway(monkeypatch, {"model-primary": _model("model-primary")}, {"provider-primary": provider})
    monkeypatch.setattr(gateway_module.asyncio, "sleep", AsyncMock())

    with pytest.raises(AIOutputTruncatedException) as exc_info:
        await gateway.chat(
            scene="provider_test",
            model_id="model-primary",
            messages=[{"role": "user", "content": "Reply with ok"}],
            user_id="admin",
            tenant_id="tenant-default",
            data_classification="PUBLIC",
        )

    assert exc_info.value.code == "AI_OUTPUT_TRUNCATED"
    assert provider.chat.await_count == 1
    assert gateway_module.ai_limits._circuits == {}


@pytest.mark.anyio
async def test_gateway_uses_policy_compatible_fallback_after_primary_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    models = {
        "model-primary": _model("model-primary", "provider-primary"),
        "model-fallback": _model("model-fallback", "provider-fallback"),
    }
    primary = SimpleNamespace(max_retries=0, chat=AsyncMock(side_effect=AINetworkException()))
    fallback = SimpleNamespace(max_retries=0, chat=AsyncMock(return_value={"content": "fallback ok"}))
    gateway = _gateway(
        monkeypatch,
        models,
        {"provider-primary": primary, "provider-fallback": fallback},
    )
    monkeypatch.setattr(
        gateway_module.model_router,
        "resolve_route_policy",
        lambda _scene: ("model-primary", "model-fallback", "scene_route", None),
    )

    result = await gateway.chat(
        scene="provider_test",
        messages=[{"role": "user", "content": "Reply with ok"}],
        user_id="admin",
        tenant_id="tenant-default",
        data_classification="PUBLIC",
    )

    assert result["content"] == "fallback ok"
    assert result["fallback_used"] is True
    assert primary.chat.await_count == 1
    assert fallback.chat.await_count == 1


@pytest.mark.anyio
async def test_gateway_limits_nested_provider_slot_by_user_and_tenant() -> None:
    limits = AILimitManager()
    limits.provider_limit = 1
    limits.tenant_limit = 1
    limits.user_limit = 1
    limits.acquire_timeout = 0.01

    async with limits.slot(provider_id="provider-a", tenant_id="tenant-a", user_id="alice"):
        with pytest.raises(AIQuotaExceededException):
            async with limits.slot(provider_id="provider-a", tenant_id="tenant-a", user_id="alice"):
                raise AssertionError("nested slot should not be acquired")


@pytest.mark.anyio
async def test_gateway_stream_retries_bounded_transient_failure_before_first_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def chat_stream(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls < 4:
            raise AIProviderTimeoutException()
        yield "stream-ok"

    provider = SimpleNamespace(max_retries=99, chat_stream=chat_stream)
    gateway = _gateway(monkeypatch, {"model-primary": _model("model-primary")}, {"provider-primary": provider})
    monkeypatch.setattr(gateway_module.asyncio, "sleep", AsyncMock())

    chunks = [
        chunk
        async for chunk in gateway.chat_stream(
            scene="provider_stream_test",
            model_id="model-primary",
            messages=[{"role": "user", "content": "Reply with ok"}],
            user_id="admin",
            tenant_id="tenant-default",
            data_classification="PUBLIC",
        )
    ]

    assert chunks == ["stream-ok"]
    assert calls == 4  # max_retries is capped at three


@pytest.mark.anyio
async def test_gateway_stream_does_not_retry_after_partial_output(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def chat_stream(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        yield "partial"
        raise AIProviderTimeoutException()

    provider = SimpleNamespace(max_retries=3, chat_stream=chat_stream)
    gateway = _gateway(monkeypatch, {"model-primary": _model("model-primary")}, {"provider-primary": provider})
    monkeypatch.setattr(gateway_module.asyncio, "sleep", AsyncMock())

    chunks = []
    with pytest.raises(AIProviderTimeoutException):
        async for chunk in gateway.chat_stream(
            scene="provider_stream_test",
            model_id="model-primary",
            messages=[{"role": "user", "content": "Reply with ok"}],
            user_id="admin",
            tenant_id="tenant-default",
            data_classification="PUBLIC",
        ):
            chunks.append(chunk)

    assert chunks == ["partial"]
    assert calls == 1


@pytest.mark.anyio
async def test_provider_circuit_opens_after_consecutive_failures_and_resets_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    limits = AILimitManager()
    limits.failure_threshold = 2
    limits.cooldown_seconds = 60
    limits.record_failure("provider-a")
    limits.record_failure("provider-a")

    with pytest.raises(AICircuitOpenException) as opened:
        async with limits.slot(provider_id="provider-a", tenant_id="tenant-a", user_id="alice"):
            raise AssertionError("an open circuit must not acquire a provider slot")
    assert opened.value.code == "AI_PROVIDER_CIRCUIT_OPEN"

    limits.record_success("provider-a")
    async with limits.slot(provider_id="provider-a", tenant_id="tenant-a", user_id="alice"):
        pass
