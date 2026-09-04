import time

from ai.services.rag_retriever import RetrievalRequest
from ai.services.retrieval_contract import (
    BoundedReranker,
    ScoreComponents,
    build_minimal_context,
    build_retrieval_explanation,
    retrieval_cache_key,
    version_compatibility,
)


def test_version_compatibility_is_fail_closed_on_conflict_and_explicit_on_match():
    assert version_compatibility(requested_release="V300R019", actual_release="V300R019")[0] == 1.0
    score, evidence = version_compatibility(requested_train="V300", actual_train="V600")
    assert score == 0.0 and evidence == "train_conflict"
    score, evidence = version_compatibility(
        requested_train="V200",
        actual_train="V200R023 / V300R024",
    )
    assert score == 0.82 and evidence == "same_train"
    score, evidence = version_compatibility(requested_release="V300R019", actual_release="", applicable_versions=["V300R019"])
    assert score == 0.95 and evidence == "applicable_release"


def test_score_fusion_exposes_all_required_signals():
    components = ScoreComponents(lexical=1.0, vector=0.8, metadata=1.0, trust=1.0, version=1.0)
    data = components.to_dict()
    assert data["total"] == 0.95
    assert set(data["weights"]) == {"lexical", "vector", "metadata", "trust", "version"}


def test_cache_key_contains_access_and_all_version_dimensions():
    base = RetrievalRequest(query="show ospf peer", tenant_id="t1", user_id="u1", roles=["reader"])
    first = retrieval_cache_key(base, document_version="d1", metadata_version="m1", index_version="i1")
    second = retrieval_cache_key(base, document_version="d2", metadata_version="m1", index_version="i1")
    third = retrieval_cache_key(RetrievalRequest(query=base.query, tenant_id="t2", user_id="u1", roles=["reader"]), document_version="d1", metadata_version="m1", index_version="i1")
    assert len(first) == 64 and first != second and first != third


def test_reranker_timeout_degrades_without_changing_candidate_safety():
    class Slow:
        name = "slow-test"

        def rank(self, query, candidates):
            time.sleep(0.05)
            return [1.0] * len(candidates)

    candidates = [{"document_id": "d1", "relevance_score": 0.4}]
    result, debug = BoundedReranker(Slow(), timeout_ms=1).apply("q", candidates)
    assert result == candidates
    assert debug["stage"] == "degraded"
    assert debug["reason"] == "timeout"


def test_context_builder_selects_primary_parent_neighbors_under_budget():
    chunks = [
        {"chunk_id": "c0", "content": "parent", "section": "Parent", "ordinal": 0},
        {"chunk_id": "c1", "content": "primary", "section": "Primary", "ordinal": 1, "parent_chunk_id": "c0"},
        {"chunk_id": "c2", "content": "neighbor", "section": "Neighbor", "ordinal": 2},
        {"chunk_id": "c3", "content": "far" * 100, "section": "Far", "ordinal": 3},
    ]
    context = build_minimal_context(chunks[1], chunks, max_chars=120)
    assert "c1" in context["context_chunk_ids"]
    assert "c0" in context["context_chunk_ids"]
    assert context["context_char_count"] <= 120


def test_explanation_is_bounded_and_does_not_echo_raw_query():
    request = RetrievalRequest(query="secret-token show ospf peer", vendor="Huawei")
    explanation = build_retrieval_explanation(
        request,
        {"candidate_count": 2, "metadata_candidate_documents": 1, "fts_stage": "native_postgresql"},
        [{"document_id": "d1", "chunk_id": "c1", "relevance_score": 0.9, "content": "secret-token"}],
    )
    assert explanation["contract_version"] == "ret-explanation-v1"
    assert "secret-token" not in str(explanation)
    assert explanation["candidates"][0]["document_id"] == "d1"
