from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core.config import settings
from ai.api.security import set_dev_passthrough
from api.knowledge_v2_contracts import DevPassthroughRequest
from ai.security.dev_passthrough import dev_passthrough
from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy
from ai.security.tokenization import ScopedTokenVault


def _gateway() -> AISecurityGateway:
    return AISecurityGateway(
        vault=ScopedTokenVault(ttl_seconds=120),
        policy=SecurityPolicy(external_ai_enabled=True),
    )


def test_dev_passthrough_is_disabled_outside_development(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "AI_DEV_PASSTHROUGH_ENABLED", True)
    dev_passthrough.disable()

    assert dev_passthrough.is_supported() is False
    with pytest.raises(RuntimeError):
        dev_passthrough.enable(1)


def test_dev_passthrough_is_explicit_and_time_limited(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "AI_DEV_PASSTHROUGH_ENABLED", True)
    monkeypatch.setattr(settings, "AI_DEV_PASSTHROUGH_MAX_MINUTES", 15)
    dev_passthrough.disable()

    status = dev_passthrough.enable(1)
    assert status["enabled"] is True
    assert 0 < status["remaining_seconds"] <= 60

    dev_passthrough.disable()
    assert dev_passthrough.status()["enabled"] is False


def test_passthrough_keeps_raw_identifiers_but_not_credentials(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "AI_DEV_PASSTHROUGH_ENABLED", True)
    dev_passthrough.disable()
    dev_passthrough.enable(1)
    try:
        payload = _gateway().protect(
            [{"role": "user", "content": "设备 10.0.0.2 hostname edge-r01"}],
            provider_allowed_classification="INTERNAL",
        )
        encoded = payload.as_provider_json()
        assert "10.0.0.2" in encoded
        assert "edge-r01" in encoded
        assert payload.metadata["dev_passthrough"] is True

        with pytest.raises(SecurityBlocked) as blocked:
            _gateway().protect(
                [{"role": "user", "content": "password=NeverExposeThis"}],
                provider_allowed_classification="INTERNAL",
            )
        assert blocked.value.reason_code == "AI_SECURITY_DLP_FAILED"
    finally:
        dev_passthrough.disable()


def test_dev_passthrough_requires_a_real_authenticated_request(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "AI_DEV_PASSTHROUGH_ENABLED", True)
    dev_passthrough.disable()
    request = Request({"type": "http", "method": "POST", "path": "/api/ai/security/dev-passthrough", "headers": []})

    with pytest.raises(HTTPException) as blocked:
        set_dev_passthrough(DevPassthroughRequest(enabled=True, duration_minutes=1), request)

    assert blocked.value.status_code == 401
