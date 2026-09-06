from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ai.api import providers as providers_api
from ai.gateway.exceptions import AISecurityBlockedException
from ai.gateway.llm_gateway import LLMGateway
from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy


class _Cursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = list(rows)

    def execute(self, *_args, **_kwargs):
        return self

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None


class _Connection:
    def __init__(self) -> None:
        self._cursor = _Cursor(
            [
                ("prov-test", "DeepSeek", "deepseek", 1, None, "unknown"),
                ("model-test", "deepseek-v4-flash"),
            ]
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor

    def execute(self, *_args, **_kwargs):
        return self._cursor

    def commit(self) -> None:
        return None


@pytest.mark.anyio
async def test_provider_probe_declares_public_classification(monkeypatch):
    probe = AsyncMock(return_value={"content": "ok"})
    monkeypatch.setattr(providers_api, "get_db_connection", lambda: _Connection())
    monkeypatch.setattr(providers_api.llm_gateway, "chat", probe)

    result = await providers_api.test_provider_connection(
        "prov-test",
        {"username": "admin", "tenant_id": "tenant-default"},
    )

    assert result.success is True
    assert result.model_tested == "deepseek-v4-flash"
    assert probe.call_args.kwargs["data_classification"] == "PUBLIC"
    assert probe.call_args.kwargs["max_tokens"] == 64
    assert probe.call_args.kwargs["messages"] == [{"role": "user", "content": "Reply with one short word: ok"}]


def test_public_provider_boundary_accepts_only_explicit_public_probe_label():
    gateway = AISecurityGateway(
        policy=SecurityPolicy(external_ai_enabled=True),
    )
    messages = [{"role": "user", "content": "Reply with one short word: ok"}]

    with pytest.raises(SecurityBlocked) as missing_label:
        gateway.protect(messages, provider_type="deepseek", provider_allowed_classification="PUBLIC")
    assert missing_label.value.reason_code == "AI_SECURITY_CLASSIFICATION_DENIED"

    payload = gateway.protect(
        messages,
        provider_type="deepseek",
        provider_allowed_classification="PUBLIC",
        data_classification="PUBLIC",
    )
    assert payload.metadata["classification"] == "PUBLIC"


@pytest.mark.anyio
async def test_gateway_preserves_specific_security_reason_code(monkeypatch):
    class _BlockingGateway:
        policy = SecurityPolicy(external_ai_enabled=True)

        def protect(self, *_args, **_kwargs):
            raise SecurityBlocked(
                "classification boundary",
                reason_code="AI_SECURITY_CLASSIFICATION_DENIED",
            )

    gateway = LLMGateway(security_gateway=_BlockingGateway())
    monkeypatch.setattr(
        gateway,
        "_get_model_details",
        lambda _model: {
            "id": "model-test",
            "model_code": "deepseek-v4-flash",
            "provider_id": "prov-test",
            "provider_type": "deepseek",
            "allowed_data_classification": "PUBLIC",
            "data_region": "unknown",
            "model_type": "chat",
            "enabled": True,
            "tool_call_supported": False,
            "json_supported": False,
            "thinking_supported": False,
            "stream_supported": True,
            "default_temperature": 0.7,
            "default_max_tokens": 2048,
        },
    )
    monkeypatch.setattr(gateway, "_authorize_model", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        gateway,
        "_apply_model_capabilities",
        lambda _info, **kwargs: (
            kwargs.get("tools"),
            kwargs.get("response_format"),
            kwargs.get("thinking", False),
            kwargs.get("reasoning_effort"),
        ),
    )
    monkeypatch.setattr(gateway, "_log_request", lambda **_kwargs: None)
    monkeypatch.setattr(gateway, "_log_security_audit", lambda **_kwargs: None)

    with pytest.raises(AISecurityBlockedException) as blocked:
        await gateway.chat(
            scene="provider_test",
            model_id="model-test",
            messages=[{"role": "user", "content": "hello"}],
            user_id="admin",
            tenant_id="tenant-default",
        )

    assert blocked.value.code == "AI_SECURITY_CLASSIFICATION_DENIED"
