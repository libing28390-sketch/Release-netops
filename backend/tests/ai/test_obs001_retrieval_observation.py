from __future__ import annotations


def test_obs001_records_bounded_retrieval_observation_without_raw_payloads():
    from ai.services.retrieval_trace_store import clear_retrieval_traces, get_retrieval_trace, record_retrieval_trace

    clear_retrieval_traces()
    raw = "show ospf peer api_key=super-secret-token"
    trace_id = record_retrieval_trace(
        tenant_id="tenant-obs001",
        user_id="alice",
        query=raw,
        trace={"source": "local_rag", "status": "hit", "resolution": {"evidence": "exact"}},
        observation={
            "raw_query": raw,
            "normalized_query": "show ospf peer api_key=<redacted>",
            "entities": {"vendor": "Huawei", "product_model": "CE6885", "intent": "cli_output"},
            "filters": {"vendor": "Huawei", "cli_platform": "huawei_vrp", "tenant_id": "must-not-copy"},
            "candidates": [
                {"document_id": "doc-private", "chunk_id": "chunk-private", "relevance_score": 0.91, "score_components": {"lexical": 0.9, "vector": 0.8, "metadata": 1.0, "trust": 1.0, "version": 0.8, "total": 0.91}},
            ],
            "final_chunks": [{"document_id": "doc-private", "chunk_id": "chunk-private", "context_chunk_ids": ["chunk-private", "chunk-neighbor"], "context_chunk_count": 2, "relevance_score": 0.91}],
        },
    )
    item = get_retrieval_trace(tenant_id="tenant-obs001", trace_id=trace_id)
    assert item is not None
    observation = item["observation"]
    assert observation["schema"] == "nxa.retrieval.observation.v1"
    assert observation["query"]["raw_query_captured"] is True
    assert observation["query"]["raw_query_retention"] == "request_scope_only"
    assert observation["query"]["raw_query_length"] == len(raw)
    assert observation["query"]["normalized_query"] == "show ospf peer api_key=<redacted>"
    assert observation["entities"]["vendor"] == "Huawei"
    assert observation["filters"]["vendor"] == "Huawei"
    assert observation["candidates"][0]["relevance_score"] == 0.91
    assert observation["final_chunks"][0]["context_chunk_count"] == 2
    rendered = str(item)
    assert raw not in rendered
    assert "super-secret-token" not in rendered
    assert "doc-private" not in rendered
    assert "chunk-private" not in rendered


def test_obs001_observation_remains_tenant_scoped_and_bounded():
    from ai.services.retrieval_trace_store import clear_retrieval_traces, get_retrieval_trace, record_retrieval_trace

    clear_retrieval_traces()
    trace_id = record_retrieval_trace(
        tenant_id="tenant-obs001-a",
        user_id="alice",
        query="show arp",
        trace={"status": "no_match"},
        observation={"candidates": [{"document_id": str(index), "relevance_score": index / 100} for index in range(150)]},
    )
    assert get_retrieval_trace(tenant_id="tenant-obs001-b", trace_id=trace_id) is None
    item = get_retrieval_trace(tenant_id="tenant-obs001-a", trace_id=trace_id)
    assert item is not None
    assert len(item["observation"]["candidates"]) == 100
    assert len(item["observation"]["scores"]) == 100


def test_obs002_runtime_projection_records_reranker_citations_latency_tokens_provider_model_and_security():
    from ai.services.retrieval_trace_store import clear_retrieval_traces, get_retrieval_trace, record_retrieval_trace, update_retrieval_trace

    clear_retrieval_traces()
    trace_id = record_retrieval_trace(
        tenant_id="tenant-obs002",
        user_id="alice",
        query="show ospf",
        trace={
            "status": "hit",
            "runtime": {
                "reranker": {"stage": "applied", "name": "none", "candidate_count": 3, "timeout_ms": 120, "cost_units": 3},
                "latency": {"retrieval_ms": 7},
            },
        },
    )
    update_retrieval_trace(
        trace_id,
        citations=[{"citation_id": "c1", "validation": "validated_official"}, {"citation_id": "c2", "validation": "failed"}],
        citation_warnings=[{"code": "STALE"}],
        runtime={
            "provider_id": "provider-a",
            "model_id": "model-a",
            "requested_model_id": "model-a",
            "route_reason": "user_default_model",
            "fallback_used": False,
            "security_result": "allow",
            "security": {"decision": "allow", "result_code": "AI_SECURITY_ALLOWED"},
            "latency": {"llm_ms": 18, "total_ms": 30},
            "tokens": {"input": 100, "output": 25},
        },
    )
    item = get_retrieval_trace(tenant_id="tenant-obs002", trace_id=trace_id)
    assert item is not None
    runtime = item["runtime"]
    assert runtime["reranker"]["stage"] == "applied"
    assert runtime["citation"] == {"count": 2, "warning_count": 1, "verified_count": 1, "failed_count": 1}
    assert runtime["latency"]["retrieval_ms"] == 7
    assert runtime["latency"]["llm_ms"] == 18
    assert runtime["tokens"] == {"input": 100, "output": 25, "total": 125}
    assert runtime["provider"]["provider_id"] == "provider-a"
    assert runtime["provider"]["model_id"] == "model-a"
    assert runtime["security"]["decision"] == "allow"


def test_obs003_trace_projection_and_log_sanitizer_drop_raw_secrets_before_write():
    from ai.security.sanitizer import sanitize_log_text
    from ai.services.retrieval_trace_store import clear_retrieval_traces, get_retrieval_trace, record_retrieval_trace
    from core.logging import SanitizeFilter
    import logging

    clear_retrieval_traces()
    raw = "show bgp password=trace-secret api_key=provider-secret"
    trace_id = record_retrieval_trace(
        tenant_id="tenant-obs003",
        user_id="alice",
        query=raw,
        trace={"status": "error"},
        observation={
            "raw_query": raw,
            "normalized_query": "show bgp password=trace-secret token=provider-secret",
            "entities": {"intent": "password=trace-secret"},
        },
    )
    item = get_retrieval_trace(tenant_id="tenant-obs003", trace_id=trace_id)
    assert item is not None
    rendered = str(item)
    assert "trace-secret" not in rendered
    assert "provider-secret" not in rendered
    assert sanitize_log_text("provider failed password=trace-secret Bearer abc.def") == "provider failed password=<REDACTED> Bearer <REDACTED>"
    assert "PRIVATE-DATA" not in sanitize_log_text("-----BEGIN RSA PRIVATE KEY-----PRIVATE-DATA-----END RSA PRIVATE KEY-----")
    record = logging.LogRecord("obs003", logging.ERROR, __file__, 1, "provider failed %s", ("api_key=provider-secret",), None)
    assert SanitizeFilter().filter(record) is True
    assert "provider-secret" not in record.getMessage()


def test_obs004_shadow_rank_delta_is_hashed_and_retained():
    from ai.services.retrieval_trace_store import clear_retrieval_traces, get_retrieval_trace, record_retrieval_trace

    clear_retrieval_traces()
    trace_id = record_retrieval_trace(
        tenant_id="tenant-obs004",
        user_id="alice",
        query="show ospf",
        trace={
            "runtime": {
                "shadow": {
                    "stage": "shadow_observed",
                    "name": "mock-reranker",
                    "mode": "shadow",
                    "baseline_top_ids": ["doc-a", "doc-b"],
                    "shadow_top_ids": ["doc-b", "doc-a"],
                    "order_changed": True,
                    "latency_ms": 12,
                },
            },
        },
    )
    item = get_retrieval_trace(tenant_id="tenant-obs004", trace_id=trace_id)
    shadow = item["runtime"]["shadow"]
    assert shadow["stage"] == "shadow_observed"
    assert shadow["order_changed"] is True
    assert shadow["baseline_top_hashes"][0] != "doc-a"
    assert shadow["rank_deltas"]
    assert "doc-a" not in str(shadow)
