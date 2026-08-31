from __future__ import annotations

import pytest


def _trace(status: str = "hit") -> dict:
    return {
        "source": "local_rag",
        "status": status,
        "metadata_candidate_documents": 3,
        "candidate_count": 4,
        "dedup_document_count": 2,
        "final_document_count": 1,
        "vector_top_n": 5,
        "clarification_required": False,
        "cross_platform_search": False,
        "request": {"vendor": "Huawei", "product_model": "CE6885"},
        "resolution": {"ambiguous": False, "platform_candidates": ["huawei_vrp"], "evidence": "exact"},
        "citations": [{
            "citation_id": "cit_1234567890abcdef",
            "vendor": "Huawei",
            "product": "CE6885",
            "software_version": "V600R023",
            "source_type": "official",
            "status": "published",
            "trust": "reviewed",
            "validation": "validated_official",
            "warnings": [],
            "document_id": "must-not-leak",
            "chunk_id": "must-not-leak",
            "url": "https://secret.example/doc?token=secret",
        }],
        "citation_warnings": [],
    }


def test_kui017_store_is_bounded_redacted_and_tenant_scoped():
    from ai.services.retrieval_trace_store import (
        clear_retrieval_traces,
        get_retrieval_trace,
        list_retrieval_traces,
        record_retrieval_trace,
        update_retrieval_trace,
    )

    clear_retrieval_traces()
    trace_id = record_retrieval_trace(
        tenant_id="tenant-kui017",
        user_id="alice",
        query="show secret command",
        trace=_trace(),
    )
    update_retrieval_trace(trace_id, citations=_trace()["citations"], citation_warnings=[])
    item = get_retrieval_trace(tenant_id="tenant-kui017", trace_id=trace_id)
    assert item is not None
    assert item["status"] == "hit"
    assert item["query_hash"] != "show secret command"
    assert item["redaction"]["raw_query_included"] is False
    assert item["redaction"]["raw_chunk_included"] is False
    assert "must-not-leak" not in str(item)
    assert "secret.example" not in str(item)
    assert get_retrieval_trace(tenant_id="tenant-other", trace_id=trace_id) is None
    assert list_retrieval_traces(tenant_id="tenant-other") == []


def test_kui017_api_contract_and_not_found():
    from api.knowledge_traces import api_get_retrieval_trace, router

    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path.endswith("/knowledge/retrieval-traces") and "GET" in methods for path, methods in paths)
    assert any(path.endswith("/knowledge/retrieval-traces/{trace_id}") and "GET" in methods for path, methods in paths)
    with pytest.raises(Exception) as exc:
        api_get_retrieval_trace(trace_id="rt_missing", user={"tenant_id": "tenant-kui017", "role": "Administrator"})
    assert getattr(exc.value, "status_code", None) == 404
