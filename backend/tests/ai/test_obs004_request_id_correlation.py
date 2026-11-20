from __future__ import annotations

from ai.providers.openai_compatible import OpenAICompatibleProvider
from ai.services.assistant import _SSE_CONTEXT, _SSEEventContext, _sse_event
from ai.services.retrieval_trace_store import (
    clear_retrieval_traces,
    get_retrieval_trace,
    record_retrieval_trace,
)
from core.context import request_id_var, resolve_request_id


def test_request_id_is_bounded_and_rejects_header_injection():
    assert resolve_request_id("web_abc-123", prefix="req") == "web_abc-123"
    generated = resolve_request_id("bad\r\nX-Injected: true", prefix="req")
    assert generated.startswith("req_")
    assert "\r" not in generated and "\n" not in generated
    assert len(generated) <= 128


def test_gateway_uses_api_context_for_direct_calls():
    token = request_id_var.set("api_corr_123")
    try:
        from ai.gateway.llm_gateway import LLMGateway

        assert LLMGateway()._generate_request_id() == "api_corr_123"
    finally:
        request_id_var.reset(token)


def test_provider_forwards_request_id_only_as_transport_header():
    provider = OpenAICompatibleProvider(
        {"base_url": "https://provider.example", "provider_type": "openai"},
        api_key="secret-value",
    )
    headers = provider._get_headers("corr_provider_001")
    assert headers["X-Request-ID"] == "corr_provider_001"
    assert headers["Authorization"] == "Bearer secret-value"
    assert "corr_provider_001" not in headers["Authorization"]


def test_retrieval_trace_preserves_request_id_without_raw_query():
    clear_retrieval_traces()
    trace_id = record_retrieval_trace(
        tenant_id="tenant-obs004",
        user_id="alice",
        query="show secret password",
        request_id="corr_rag_004",
        trace={"source": "local_rag", "status": "no_match", "request_id": "corr_rag_004"},
        observation={"raw_query": "show secret password"},
    )
    row = get_retrieval_trace(tenant_id=None, trace_id=trace_id)
    assert row is not None
    assert row["request_id"] == "corr_rag_004"
    assert "show secret password" not in str(row)


def test_stream_envelope_carries_request_id_with_stream_identity():
    token = _SSE_CONTEXT.set(_SSEEventContext("sse_obs004", "corr_sse_004"))
    try:
        event = _sse_event("meta", {"intent": "knowledge"})
    finally:
        _SSE_CONTEXT.reset(token)
    assert '"request_id": "corr_sse_004"' in event
    assert '"stream_id": "sse_obs004"' in event
