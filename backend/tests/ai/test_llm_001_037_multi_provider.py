from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai.gateway.llm_gateway import LLMGateway, _resolve_approved_endpoint_patterns
from ai.providers.registry import ADAPTER_REGISTRY, AzureOpenAIProvider, OllamaProvider, provider_adapter
from ai.schemas.model import AIModelCreate
from ai.schemas.provider import AIProviderCreate
from ai.security.crypto import has_configured_master_key


def test_llm_001_002_005_provider_contract_is_extensible_and_instance_safe():
    first = AIProviderCreate(name="OpenAI A", provider_type="openai_compatible", base_url="https://a.example", api_key=None)
    second = AIProviderCreate(name="OpenAI B", provider_type="openai_compatible", base_url="https://b.example", api_key=None)
    assert first.provider_type == second.provider_type == "openai_compatible"
    assert first.name != second.name
    with pytest.raises(ValueError):
        AIProviderCreate(name="bad", provider_type="unknown_adapter", base_url="https://x.example")


def test_llm_006_008_adapter_registry_covers_deepseek_openai_azure_ollama_local():
    assert provider_adapter("deepseek").__name__ == "DeepSeekProvider"
    assert provider_adapter("openai-compatible").__name__ == "OpenAICompatibleProvider"
    assert ADAPTER_REGISTRY["azure_openai"] is AzureOpenAIProvider
    assert ADAPTER_REGISTRY["ollama"] is OllamaProvider


def test_llm_legacy_empty_cloud_endpoint_allowlist_falls_back_to_exact_base_url():
    assert _resolve_approved_endpoint_patterns("[]", "https://api.deepseek.com/", "deepseek") == [
        "https://api.deepseek.com"
    ]
    assert _resolve_approved_endpoint_patterns("{}", "https://api.openai.com/v1", "openai") == [
        "https://api.openai.com/v1"
    ]
    assert _resolve_approved_endpoint_patterns("[]", "http://127.0.0.1:11434/v1", "ollama") == []
    assert _resolve_approved_endpoint_patterns("[]", "http://api.example.test/v1", "openai") == []


def test_llm_013_018_model_scope_capabilities_and_types_are_not_deepseek_only():
    model = AIModelCreate(provider_id="provider-openai", name="GPT", model_code="gpt-4o", model_type="reasoning", thinking_supported=True, stream_supported=True)
    assert model.model_code == "gpt-4o"
    assert model.model_type == "reasoning"
    for model_type in ("chat", "reasoning", "embedding", "rerank"):
        assert AIModelCreate(provider_id="p", name=model_type, model_code=f"{model_type}-1", model_type=model_type).model_type == model_type
    with pytest.raises(ValueError):
        AIModelCreate(provider_id="p", name="bad", model_code="bad", model_type="completion")


def test_llm_003_master_key_placeholder_is_not_accepted(monkeypatch):
    from core import config
    monkeypatch.setattr(config.settings, "CREDENTIAL_ENCRYPTION_KEY", "change-me-to-a-random-secret")
    assert has_configured_master_key() is False
    monkeypatch.setattr(config.settings, "CREDENTIAL_ENCRYPTION_KEY", "a-real-test-master-key-123456")
    assert has_configured_master_key() is True


def test_llm_017_capability_guard_drops_unsupported_request_parameters():
    gateway = LLMGateway(security_gateway=SimpleNamespace())
    info = {"id": "m1", "model_type": "chat", "tool_call_supported": False, "json_supported": False, "thinking_supported": False}
    tools, response_format, thinking, reasoning = gateway._apply_model_capabilities(info, tools=[{"type": "function"}], response_format={"type": "json_object"}, thinking=True, reasoning_effort="high")
    assert tools is None and response_format is None and thinking is False and reasoning is None
    with pytest.raises(Exception):
        gateway._apply_model_capabilities({"id": "m2", "model_type": "embedding"}, tools=None, response_format=None, thinking=False, reasoning_effort=None)


def test_llm_032_errors_are_stable_codes_not_provider_response_bodies():
    from ai.gateway.exceptions import (
        AIAuthFailedException, AIRateLimitException, AIProviderTimeoutException,
        AINetworkException, AIInvalidRequestException, AIModelNotFoundException,
        AICircuitOpenException, AIQuotaExceededException,
    )
    assert {AIAuthFailedException().code, AIRateLimitException().code, AIProviderTimeoutException().code, AINetworkException().code, AIInvalidRequestException().code, AIModelNotFoundException().code, AICircuitOpenException().code, AIQuotaExceededException().code} == {
        "AI_AUTH_FAILED", "AI_RATE_LIMIT", "AI_PROVIDER_TIMEOUT", "AI_NETWORK_ERROR", "AI_INVALID_REQUEST", "AI_MODEL_NOT_FOUND", "AI_PROVIDER_CIRCUIT_OPEN", "AI_QUOTA_EXCEEDED"
    }


def test_llm_030_033_fallback_classification_and_circuit_are_fail_closed():
    gateway = LLMGateway(security_gateway=SimpleNamespace())
    primary = {"model_type": "chat", "allowed_data_classification": "CONFIDENTIAL"}
    assert gateway._fallback_is_compatible(primary, {"model_type": "chat", "allowed_data_classification": "CONFIDENTIAL"})
    assert not gateway._fallback_is_compatible(primary, {"model_type": "chat", "allowed_data_classification": "PUBLIC"})
    assert not gateway._fallback_is_compatible(primary, {"model_type": "embedding", "allowed_data_classification": "CONFIDENTIAL"})


def test_llm_033_circuit_opens_after_provider_failures():
    from ai.gateway.limits import AILimitManager
    from ai.gateway.exceptions import AICircuitOpenException

    limits = AILimitManager()
    limits.failure_threshold = 2
    limits.cooldown_seconds = 60
    limits.record_failure("provider-a")
    limits.record_failure("provider-a")
    with pytest.raises(AICircuitOpenException):
        limits._check_circuit("provider-a")
