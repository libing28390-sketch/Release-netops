from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core.config import settings
from ai.api.security import set_dev_passthrough
from api.knowledge_contracts import DevPassthroughRequest
from ai.security.dev_passthrough import dev_passthrough
from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy
from ai.security.tokenization import ScopedTokenVault


def _gateway() -> AISecurityGateway:
    return AISecurityGateway(
        vault=ScopedTokenVault(ttl_seconds=120),
        policy=SecurityPolicy(external_ai_enabled=True),
    )


def _enable_ai_test_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "EXTERNAL_AI_ENABLED", True)


def test_temporary_test_mode_is_available_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    _enable_ai_test_mode(monkeypatch)
    dev_passthrough.disable()

    assert dev_passthrough.is_supported() is True
    status = dev_passthrough.enable(1)
    assert status["enabled"] is True
    assert status["environment"] == "production"
    assert status["mode"] == "blacklist"
    dev_passthrough.disable()


def test_temporary_test_mode_requires_ai_enablement(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    monkeypatch.setattr(settings, "EXTERNAL_AI_ENABLED", False)
    dev_passthrough.disable()

    assert dev_passthrough.is_supported() is False
    with pytest.raises(RuntimeError):
        dev_passthrough.enable(1)


def test_passthrough_keeps_raw_identifiers_but_not_credentials(monkeypatch):
    _enable_ai_test_mode(monkeypatch)
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
        assert payload.metadata["security_mode"] == "blacklist"

        with pytest.raises(SecurityBlocked) as blocked:
            _gateway().protect(
                [{"role": "user", "content": "password=NeverExposeThis"}],
                provider_allowed_classification="INTERNAL",
            )
        assert blocked.value.reason_code == "AI_SECURITY_DLP_FAILED"
    finally:
        dev_passthrough.disable()


def test_passthrough_relaxes_classification_and_tokenization_but_blocks_writes(monkeypatch):
    _enable_ai_test_mode(monkeypatch)
    dev_passthrough.disable()
    dev_passthrough.enable(1)
    try:
        payload = _gateway().protect(
            [{"role": "user", "content": "send the full CMDB for 10.0.0.2"}],
            data_classification="CONFIDENTIAL",
            provider_allowed_classification="PUBLIC",
        )
        encoded = payload.as_provider_json()
        assert payload.action.value == "ALLOW"
        assert "10.0.0.2" in encoded
        assert "full CMDB" in encoded
        assert payload.metadata["classification"] == "CONFIDENTIAL"

        for write_request in ("configure terminal", "修改配置"):
            with pytest.raises(SecurityBlocked) as blocked:
                _gateway().protect(
                    [{"role": "user", "content": write_request}],
                    data_classification="CONFIDENTIAL",
                    provider_allowed_classification="PUBLIC",
                )
            assert blocked.value.reason_code == "AI_SECURITY_UNSAFE_TOOL"
    finally:
        dev_passthrough.disable()


def test_passthrough_blocks_opaque_credential_fields(monkeypatch):
    _enable_ai_test_mode(monkeypatch)
    dev_passthrough.disable()
    dev_passthrough.enable(1)
    try:
        with pytest.raises(SecurityBlocked) as blocked:
            _gateway().protect(
                [{"role": "user", "content": "inspect"}],
                tools=[{"name": "safe_lookup", "arguments": {"api_key": "opaque"}}],
            )
        assert blocked.value.reason_code == "AI_SECURITY_DLP_FAILED"
        assert "opaque" not in blocked.value.user_message
    finally:
        dev_passthrough.disable()


def test_passthrough_does_not_bypass_provider_region_or_tenant_controls(monkeypatch):
    _enable_ai_test_mode(monkeypatch)
    dev_passthrough.disable()
    dev_passthrough.enable(1)
    try:
        with pytest.raises(SecurityBlocked) as provider:
            _gateway().protect([{"role": "user", "content": "hello"}], provider_type="not-approved")
        assert provider.value.reason_code == "AI_SECURITY_PROVIDER_DENIED"

        with pytest.raises(SecurityBlocked) as region:
            _gateway().protect([{"role": "user", "content": "hello"}], data_region="mars")
        assert region.value.reason_code == "AI_SECURITY_SCOPE_DENIED"

        tenant_gateway = AISecurityGateway(
            vault=ScopedTokenVault(ttl_seconds=120),
            policy=SecurityPolicy(
                external_ai_enabled=True,
                tenant_kill_switches={"tenant-a": True},
            ),
        )
        with pytest.raises(SecurityBlocked) as tenant:
            tenant_gateway.protect([{"role": "user", "content": "hello"}], tenant_id="tenant-a")
        assert tenant.value.reason_code == "AI_SECURITY_KILL_SWITCH"
    finally:
        dev_passthrough.disable()


def test_dev_passthrough_requires_a_real_authenticated_request(monkeypatch):
    _enable_ai_test_mode(monkeypatch)
    dev_passthrough.disable()
    request = Request({"type": "http", "method": "POST", "path": "/api/ai/security/dev-passthrough", "headers": []})

    with pytest.raises(HTTPException) as blocked:
        set_dev_passthrough(DevPassthroughRequest(enabled=True, duration_minutes=1), request)

    assert blocked.value.status_code == 401
