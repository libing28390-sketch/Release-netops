from __future__ import annotations

from ai.services.rag_retriever import RAGRetriever, RetrievalRequest
from core.config import settings


def _request() -> RetrievalRequest:
    return RetrievalRequest(query="show version", tenant_id="tenant-a", top_k=3)


def test_mig009_shadow_keeps_v1_results_and_only_exposes_bounded_hashes(monkeypatch):
    retriever = RAGRetriever(cache_enabled=False)
    monkeypatch.setattr(settings, "KNOWLEDGE_V2_SHADOW_READ", True)
    monkeypatch.setattr(settings, "KNOWLEDGE_V2_ENABLED", False)
    monkeypatch.setattr(retriever, "_active_index_generation", lambda tenant_id: {"id": "gen-a", "tenant_id": tenant_id, "index_version": "v2-test"})

    def fake_once(request, min_relevance=0.20, *, active_generation=None):
        if active_generation:
            return {"results": [{"storage_document_id": "v2-doc", "chunk_id": "v2-chunk", "relevance_score": 0.9}], "debug": {"index_source": "shadow"}}
        return {"results": [{"storage_document_id": "v1-doc", "chunk_id": "v1-chunk", "relevance_score": 0.8}], "debug": {"index_source": "v1"}}

    monkeypatch.setattr(retriever, "_search_once", fake_once)
    result = retriever.search(_request())
    assert [item["storage_document_id"] for item in result["results"]] == ["v1-doc"]
    shadow = result["debug"]["shadow"]
    assert shadow["user_answer_source"] == "v1"
    assert shadow["v1_result_count"] == 1 and shadow["v2_result_count"] == 1
    assert "v1-doc" not in str(shadow) and "v2-doc" not in str(shadow)
    assert shadow["status"] == "ok"


def test_mig009_shadow_failure_is_degraded_without_replacing_v1(monkeypatch):
    retriever = RAGRetriever(cache_enabled=False)
    monkeypatch.setattr(settings, "KNOWLEDGE_V2_SHADOW_READ", True)
    monkeypatch.setattr(retriever, "_active_index_generation", lambda tenant_id: {"id": "gen-a", "tenant_id": tenant_id, "index_version": "v2-test"})

    def fake_once(request, min_relevance=0.20, *, active_generation=None):
        if active_generation:
            return {"results": [], "debug": {"error_code": "RETRIEVAL_EXECUTION_FAILED"}}
        return {"results": [{"storage_document_id": "v1-doc", "chunk_id": "v1-chunk"}], "debug": {"index_source": "v1"}}

    monkeypatch.setattr(retriever, "_search_once", fake_once)
    result = retriever.search(_request())
    assert result["results"][0]["storage_document_id"] == "v1-doc"
    assert result["debug"]["shadow"]["status"] == "degraded"
    assert result["debug"]["shadow"]["error_code"] == "RETRIEVAL_V2_SHADOW_FAILED"


def test_mig009_v2_is_not_selected_without_explicit_enable(monkeypatch):
    retriever = RAGRetriever(cache_enabled=False)
    monkeypatch.setattr(settings, "KNOWLEDGE_V2_SHADOW_READ", False)
    monkeypatch.setattr(settings, "KNOWLEDGE_V2_ENABLED", False)
    monkeypatch.setattr(retriever, "_active_index_generation", lambda tenant_id: {"id": "gen-a", "tenant_id": tenant_id, "index_version": "v2-test"})
    sources = []

    def fake_once(request, min_relevance=0.20, *, active_generation=None):
        sources.append("v2" if active_generation else "v1")
        return {"results": [], "debug": {"index_source": sources[-1]}}

    monkeypatch.setattr(retriever, "_search_once", fake_once)
    retriever.search(_request())
    assert sources == ["v1"]
