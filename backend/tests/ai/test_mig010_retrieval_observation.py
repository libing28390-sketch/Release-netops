from __future__ import annotations


def test_mig010_shadow_compare_records_candidates_final_chunks_latency_and_diff_without_raw_ids():
    from ai.services.rag_retriever import RAGRetriever

    v1 = {
        "results": [
            {
                "storage_document_id": "doc-v1",
                "document_id": "semantic-v1",
                "chunk_id": "chunk-v1",
                "relevance_score": 0.81,
                "context_chunk_ids": ["chunk-v1", "neighbor-v1"],
                "context_chunk_count": 2,
            },
        ],
        "debug": {
            "candidate_snapshot": [
                {
                    "storage_document_id": "doc-v1",
                    "chunk_id": "chunk-v1",
                    "relevance_score": 0.81,
                    "score_components": {"lexical": 0.8, "vector": 0.7, "total": 0.81},
                },
            ],
        },
    }
    v2 = {
        "results": [
            {
                "storage_document_id": "doc-v2",
                "document_id": "semantic-v2",
                "chunk_id": "chunk-v2",
                "relevance_score": 0.93,
                "context_chunk_ids": ["chunk-v2"],
                "context_chunk_count": 1,
            },
        ],
        "debug": {
            "candidate_snapshot": [
                {
                    "storage_document_id": "doc-v2",
                    "chunk_id": "chunk-v2",
                    "relevance_score": 0.93,
                    "score_components": {"lexical": 0.9, "vector": 0.8, "total": 0.93},
                },
            ],
        },
    }
    shadow = RAGRetriever._shadow_compare(
        v1,
        v2,
        v1_latency_ms=17,
        v2_latency_ms=29,
        generation={"index_version": "v2-index-1"},
    )

    assert shadow["user_answer_source"] == "v1"
    assert shadow["v1_latency_ms"] == 17 and shadow["v2_latency_ms"] == 29
    assert shadow["v1_candidates"][0]["relevance_score"] == 0.81
    assert shadow["v2_final_chunks"][0]["context_chunk_count"] == 1
    assert shadow["difference"]["added_hashes"]
    assert shadow["difference"]["removed_hashes"]
    rendered = str(shadow)
    for raw in ("doc-v1", "doc-v2", "semantic-v1", "semantic-v2", "chunk-v1", "chunk-v2", "neighbor-v1"):
        assert raw not in rendered


def test_mig010_trace_projection_keeps_shadow_detail_hash_only_and_bounded():
    from ai.services.retrieval_trace_store import clear_retrieval_traces, get_retrieval_trace, record_retrieval_trace

    clear_retrieval_traces()
    trace_id = record_retrieval_trace(
        tenant_id="tenant-mig010",
        user_id="operator-a",
        query="show ospf peer",
        trace={"status": "hit"},
        observation={
            "normalized_query": "show ospf peer",
            "entities": {"vendor": "Huawei", "product_model": "CE6885"},
            "shadow": {
                "mode": "v1_primary_v2_shadow",
                "status": "ok",
                "user_answer_source": "v1",
                "v1_latency_ms": 12,
                "v2_latency_ms": 18,
                "v1_candidates": [{"candidate_hash": "a" * 32, "relevance_score": 0.8, "document_id": "must-drop"}],
                "v2_candidates": [{"candidate_hash": "b" * 32, "relevance_score": 0.9}],
                "v1_final_chunks": [{"chunk_hash": "c" * 32, "context_chunk_count": 2, "content": "must-drop"}],
                "v2_final_chunks": [{"chunk_hash": "d" * 32, "context_chunk_count": 1}],
                "difference": {
                    "added_hashes": ["d" * 32],
                    "removed_hashes": ["c" * 32],
                    "score_deltas": [{"chunk_hash": "c" * 32, "v1_score": 0.8, "v2_score": 0.7, "delta": -0.1}],
                },
            },
        },
    )
    item = get_retrieval_trace(tenant_id="tenant-mig010", trace_id=trace_id)
    assert item is not None
    shadow = item["observation"]["shadow"]
    assert shadow["v1_latency_ms"] == 12 and shadow["v2_latency_ms"] == 18
    assert shadow["v1_candidates"][0]["candidate_hash"] == "a" * 32
    assert shadow["v1_final_chunks"][0]["context_chunk_count"] == 2
    assert shadow["difference"]["score_deltas"][0]["delta"] == -0.1
    rendered = str(item)
    assert "must-drop" not in rendered
    assert "tenant-mig010" in rendered


def test_mig010_citation_update_records_v1_source_and_count():
    from ai.services.retrieval_trace_store import clear_retrieval_traces, get_retrieval_trace, record_retrieval_trace, update_retrieval_trace

    clear_retrieval_traces()
    trace_id = record_retrieval_trace(
        tenant_id="tenant-mig010-citations",
        user_id="operator-a",
        query="show version",
        trace={
            "status": "hit",
            "runtime": {"shadow": {"mode": "v1_primary_v2_shadow", "v2_citation_count": 0}},
        },
    )
    update_retrieval_trace(
        trace_id,
        citations=[{"citation_id": "cite-1", "validation": "validated_official"}],
    )
    item = get_retrieval_trace(tenant_id="tenant-mig010-citations", trace_id=trace_id)
    assert item is not None
    shadow = item["runtime"]["shadow"]
    assert shadow["citation_source"] == "v1"
    assert shadow["v1_citation_count"] == 1
    assert shadow["v2_citation_count"] == 0

