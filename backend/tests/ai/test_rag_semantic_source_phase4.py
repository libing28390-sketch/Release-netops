"""Semantic vector source and tunable weights (RAG refactor phase 4).

A concept-based fake provider stands in for bge-m3: a Chinese colloquial
question and an English document about the same feature get similar vectors
although they share no words, which is exactly what the lexical signals
cannot do.
"""

from __future__ import annotations

import math

import pytest

from ai.providers import embedding as embedding_module
from ai.providers.embedding import BaseEmbeddingProvider, EmbeddingProviderError
from ai.services import semantic_vectors
from ai.services.rag_retriever import RAGRetriever, RetrievalRequest
from ai.services.retrieval_contract import DEFAULT_SCORE_WEIGHTS, ScoreComponents, parse_score_weights, score_weights

CONCEPTS = {
    "ospf": ("ospf", "动态路由", "邻居"),
    "vlan": ("vlan", "广播域", "隔离"),
    "bgp": ("bgp", "运营商", "对等体"),
    "ntp": ("ntp", "时钟", "时间"),
}


class ConceptProvider(BaseEmbeddingProvider):
    model_id = "bge-m3"
    version = "bge-m3-int8-v1"
    dimensions = 1024
    mode = "local_semantic"

    def __init__(self, fail_queries: bool = False) -> None:
        self.fail_queries = fail_queries

    def _vector(self, text: str) -> list[float]:
        lowered = str(text).lower()
        vector = [0.0] * self.dimensions
        for index, words in enumerate(CONCEPTS.values()):
            vector[index] = float(sum(lowered.count(word) for word in words))
        vector[self.dimensions - 1] = 0.05  # never a zero vector
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector]

    def embed_documents(self, texts, **_):
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        if self.fail_queries:
            raise EmbeddingProviderError("Embedding sidecar unavailable: TIMEOUT")
        return self._vector(text)

    def embed_text(self, text, dimensions=None):
        return self._vector(text)


DOCS = {
    "OSPF": "# OSPF\n\n## Verification\n\nUse display ospf peer to verify OSPF adjacency state Full on both routers.",
    "VLAN": "# VLAN\n\n## Configuration\n\nvlan batch 10 20 separates departments into different VLAN segments.",
    "BGP": "# BGP\n\n## Verification\n\ndisplay bgp peer shows the BGP session with the upstream provider.",
    "NTP": "# NTP\n\n## Configuration\n\nntp-service unicast-server keeps the device clock in sync.",
}


@pytest.fixture
def provider_state(monkeypatch):
    embedding_module._EMBEDDING_IDEMPOTENCY_CACHE.clear()
    state = {"provider": ConceptProvider()}
    monkeypatch.setattr(semantic_vectors, "semantic_embedding_provider", lambda: state["provider"])
    monkeypatch.setattr(embedding_module, "semantic_embedding_provider", lambda: state["provider"])
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "v2")
    monkeypatch.setenv("AI_RETRIEVAL_V2_EXACT_THRESHOLD", "0")
    monkeypatch.delenv("AI_RETRIEVAL_SCORE_WEIGHTS", raising=False)
    yield state
    embedding_module._EMBEDDING_IDEMPOTENCY_CACHE.clear()


@pytest.fixture
def corpus(isolated_db, provider_state):
    from ai.services.knowledge_service import knowledge_service

    knowledge_base = knowledge_service.create_knowledge_base("Semantic source corpus", tenant_id="tenant-default")
    created = {}
    for name, content in DOCS.items():
        result = knowledge_service.add_document_and_chunk(
            knowledge_base_id=knowledge_base["id"],
            name=f"Huawei {name}",
            content=content,
            vendor="Huawei",
            platform="huawei_vrp",
            tenant_id="tenant-default",
            metadata={
                "vendor": "Huawei",
                "product_family": "Campus Switch",
                "product_series": "S5700",
                "cli_platform": "huawei_vrp",
                "source_type": "user_document",
                "document_category": "configuration",
            },
            invalidate_cache=False,
        )
        created[name] = str(result["document_id"])
    return created


def _search(query: str):
    retriever = RAGRetriever(cache_enabled=False)
    return retriever.search(
        RetrievalRequest(query=query, vendor="Huawei", top_k=3, tenant_id="tenant-default", user_id="u1", roles=["Operator"]),
        min_relevance=0.0,
    )


def _ids(result):
    return [str(item.get("storage_document_id")) for item in result["results"]]


# ── vector source ─────────────────────────────────────────────────────────


def test_semantic_source_finds_a_keyword_free_chinese_question(corpus, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_VECTOR_SOURCE", "semantic")
    result = _search("两台路由器的动态路由邻居一直起不来")
    assert result["debug"]["vector_source"] == "semantic"
    assert result["debug"]["vector_stage"] == "native_pgvector_semantic"
    assert _ids(result)[0] == corpus["OSPF"]
    top = result["results"][0]
    assert top["score_components"]["vector"] > 0.5


def test_legacy_source_is_the_default(corpus, monkeypatch):
    monkeypatch.delenv("AI_RETRIEVAL_VECTOR_SOURCE", raising=False)
    result = _search("两台路由器的动态路由邻居一直起不来")
    assert result["debug"]["vector_source"] == "legacy"


def test_query_embedding_failure_falls_back_to_legacy_for_all_rows(corpus, provider_state, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_VECTOR_SOURCE", "semantic")
    provider_state["provider"] = ConceptProvider(fail_queries=True)
    result = _search("display ospf peer")
    assert result["debug"]["vector_source"] == "legacy_fallback"
    assert "SEMANTIC_QUERY_EMBEDDING_UNAVAILABLE" in result["debug"]["capability_degraded"]
    assert result["debug"].get("vector_stage") != "native_pgvector_semantic"
    assert _ids(result)[0] == corpus["OSPF"]  # lexical signals still answer


def test_rows_without_a_current_semantic_vector_score_zero(corpus, monkeypatch):
    from database.core import get_db_connection

    with get_db_connection() as conn:
        conn.execute("UPDATE ai_document_chunk SET embedding_v2_version = 'old' WHERE document_id = ?", (corpus["OSPF"],))
        conn.commit()
    monkeypatch.setenv("AI_RETRIEVAL_VECTOR_SOURCE", "semantic")
    result = _search("display ospf peer adjacency")
    ospf = next(item for item in result["results"] if item["storage_document_id"] == corpus["OSPF"])
    assert ospf["score_components"]["vector"] == 0.0
    assert result["debug"]["semantic_missing_chunks"] >= 1


def test_exact_small_set_path_also_uses_semantic_scores(corpus, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_VECTOR_SOURCE", "semantic")
    monkeypatch.delenv("AI_RETRIEVAL_V2_EXACT_THRESHOLD", raising=False)
    result = _search("不同部门的电脑想隔离开")
    assert result["debug"]["retrieval_engine"] == "v2_exact_small_set"
    assert result["debug"]["vector_source"] == "semantic"
    assert _ids(result)[0] == corpus["VLAN"]


def test_v1_engine_ignores_the_vector_source(corpus, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "v1")
    monkeypatch.setenv("AI_RETRIEVAL_VECTOR_SOURCE", "semantic")
    result = _search("display ospf peer")
    assert result["debug"]["retrieval_engine"] == "v1"
    assert "vector_source" not in result["debug"]


# ── weights ───────────────────────────────────────────────────────────────


def test_weights_parse_and_validate():
    assert parse_score_weights("") == DEFAULT_SCORE_WEIGHTS
    weights = parse_score_weights("lexical=0.35, vector=0.35, metadata=0.15, trust=0.10, version=0.05")
    assert weights["vector"] == 0.35
    for bad in (
        "lexical=0.5,vector=0.5",                                         # missing keys
        "lexical=0.45,vector=0.25,metadata=0.15,trust=0.10,version=0.10",  # sum 1.05
        "lexical=0.45,vector=0.25,metadata=0.15,trust=0.10,bonus=0.05",    # unknown key
        "lexical=-0.1,vector=0.6,metadata=0.3,trust=0.1,version=0.1",      # negative
        "lexical=abc,vector=0.25,metadata=0.15,trust=0.10,version=0.05",
    ):
        with pytest.raises(ValueError):
            parse_score_weights(bad)


def test_invalid_env_weights_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_SCORE_WEIGHTS", "lexical=1")
    assert score_weights() == DEFAULT_SCORE_WEIGHTS


def test_custom_weights_change_the_total_and_are_reported():
    default = ScoreComponents(lexical=1.0, vector=0.0, metadata=0.0, trust=0.0, version=0.0)
    custom = ScoreComponents(
        lexical=1.0, vector=0.0, metadata=0.0, trust=0.0, version=0.0,
        weights=parse_score_weights("lexical=0.30,vector=0.40,metadata=0.15,trust=0.10,version=0.05"),
    )
    assert default.total == pytest.approx(0.45)
    assert custom.total == pytest.approx(0.30)
    assert custom.to_dict()["weights"]["vector"] == 0.40


def test_weights_reach_the_ranking(corpus, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_VECTOR_SOURCE", "semantic")
    monkeypatch.setenv("AI_RETRIEVAL_SCORE_WEIGHTS", "lexical=0.10,vector=0.70,metadata=0.10,trust=0.05,version=0.05")
    result = _search("两台路由器的动态路由邻居一直起不来")
    assert result["results"][0]["score_components"]["weights"]["vector"] == 0.70
