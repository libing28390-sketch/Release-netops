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
