"""RAG retrieval V2 engine (review item M9, refactor phase 1).

Runs against the full migrated PostgreSQL schema and writes documents through
the normal ingestion path, so the m0330 ACL trigger, search_text and
embedding_vector projections are the real ones.
"""

from __future__ import annotations

import pytest

from ai.services.rag_policy import document_is_visible
from ai.services.rag_retriever import RAGRetriever, RetrievalRequest, _trgm_terms


TOPICS = {
    "OSPF": "# OSPF\n\n## Verification\n\nUse display ospf peer to check OSPF neighbor state Full.\n\n## Troubleshooting\n\nOSPF neighbor stuck in ExStart usually means an MTU mismatch.",
    "VLAN": "# VLAN\n\n## Configuration\n\nvlan batch 10 20 creates VLANs; port link-type trunk allows tagged frames.",
    "BGP": "# BGP\n\n## Verification\n\ndisplay bgp peer shows BGP session state Established and received routes.",
    "NTP": "# NTP\n\n## Configuration\n\nntp-service unicast-server sets the NTP server for clock synchronization.",
    "SSH": "# SSH\n\n## Configuration\n\nstelnet server enable and ssh user configure secure management access.",
    "ACL": "# ACL\n\n## Configuration\n\nacl number 3000 with rule permit ip source filters traffic on interfaces.",
}


def _metadata(vendor: str, feature: str) -> dict:
    # vendor / product_family / product_series are required, otherwise the
    # document is held for metadata review and excluded from RAG.
    metadata = {
        "vendor": vendor,
        "product_family": "Campus Switch" if vendor == "Huawei" else "Catalyst",
        "product_series": "S5700" if vendor == "Huawei" else "Catalyst 9300",
        "cli_platform": "huawei_vrp" if vendor == "Huawei" else "cisco_ios",
        "product_model": "S5700" if vendor == "Huawei" else "C9300",
        "software_release": "V200R023" if vendor == "Huawei" else "17.9",
        "source_type": "user_document",
        "document_category": "configuration",
    }
    if feature:
        metadata["feature"] = feature.lower()
    return metadata


@pytest.fixture
def corpus(isolated_db):
    from ai.services.knowledge_service import knowledge_service
    from database.core import get_db_connection

    knowledge_base = knowledge_service.create_knowledge_base("RAG V2 test corpus", tenant_id="tenant-default")
    created: dict[str, str] = {}

    def add(name: str, content: str, *, vendor: str = "Huawei", feature: str = "", acl: dict | None = None) -> str:
        result = knowledge_service.add_document_and_chunk(
            knowledge_base_id=knowledge_base["id"],
            name=name,
            content=content,
            vendor=vendor,
            platform="huawei_vrp" if vendor == "Huawei" else "cisco_ios",
            tenant_id="tenant-default",
            acl=acl,
            metadata=_metadata(vendor, feature),
            invalidate_cache=False,
        )
        document_id = str(result["document_id"])
        created[name] = document_id
        return document_id

    for topic, content in TOPICS.items():
        add(f"Huawei {topic}", content, feature=topic)
    add("Cisco OSPF", TOPICS["OSPF"], vendor="Cisco", feature="OSPF")
    add(
        "Huawei restricted runbook",
        "# Restricted\n\n## Procedure\n\nquantum flux capacitor maintenance procedure for core routers.",
        acl={"roles": ["Administrator"]},
    )

    with get_db_connection() as conn:
        excluded = conn.execute("SELECT name FROM ai_document WHERE COALESCE(exclude_from_rag, 0) <> 0").fetchall()
    assert not excluded, f"test documents were held for metadata review: {excluded}"
    return created


def _search(query: str, *, roles=None, user_id: str | None = "alice", vendor: str | None = "Huawei", embedder=None):
    retriever = RAGRetriever(cache_enabled=False, embedder=embedder)
    return retriever.search(
        RetrievalRequest(query=query, vendor=vendor, top_k=5, tenant_id="tenant-default", user_id=user_id, roles=roles or ["Operator"]),
        min_relevance=0.0,
    )


def _ids(result) -> list[str]:
    return [str(item.get("storage_document_id")) for item in result["results"]]


@pytest.fixture
def force_v2(monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "v2")
    monkeypatch.setenv("AI_RETRIEVAL_V2_EXACT_THRESHOLD", "0")


# ── m0330: ACL projection ─────────────────────────────────────────────────


def test_acl_principals_trigger_matches_the_python_policy(isolated_db):
    from database.core import get_db_connection

    cases = {
        "": ["*"],
        "{}": ["*"],
        '{"roles": ["Operator"]}': ["r:Operator"],
        '{"users": ["alice"], "sites": ["sh-01"]}': ["s:sh-01", "u:alice"],
        '{"user_ids": [" bob "], "site_ids": "bj-02"}': ["s:bj-02", "u:bob"],
        '{"unknown": ["x"]}': [],
        '{"roles": []}': [],
        "[]": [],
        "null": [],
        "not json": [],
    }
    probes = [(None, [], []), ("alice", [], []), ("bob", [], []), (None, ["Operator"], []), (None, [], ["sh-01"]), (None, [], ["bj-02"])]
    with get_db_connection() as conn:
        for raw, expected in cases.items():
            projected = conn.execute("SELECT nexora_rag_acl_principals(?)", (raw,)).fetchone()[0] or []
            assert sorted(projected) == expected, raw
            for user_id, roles, sites in probes:
                principals = {"*"} | ({f"u:{user_id}"} if user_id else set()) | {f"r:{r}" for r in roles} | {f"s:{s}" for s in sites}
                sql_visible = bool(principals & set(projected))
                python_visible = document_is_visible({"acl_json": raw}, user_id=user_id, roles=roles, site_ids=sites)
                assert sql_visible == python_visible, (raw, user_id, roles, sites)


def test_acl_principals_follow_updates(corpus):
    from database.core import get_db_connection

    document_id = corpus["Huawei OSPF"]
    with get_db_connection() as conn:
        assert conn.execute("SELECT acl_principals FROM ai_document WHERE id = ?", (document_id,)).fetchone()[0] == ["*"]
        conn.execute("UPDATE ai_document SET acl_json = ? WHERE id = ?", ('{"roles": ["Auditor"]}', document_id))
        conn.commit()
        assert conn.execute("SELECT acl_principals FROM ai_document WHERE id = ?", (document_id,)).fetchone()[0] == ["r:Auditor"]


# ── V2 engine ─────────────────────────────────────────────────────────────


def test_v2_indexed_path_agrees_with_v1_on_the_top_document(corpus, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "v1")
    v1 = _search("display ospf peer neighbor state")
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "v2")
    monkeypatch.setenv("AI_RETRIEVAL_V2_EXACT_THRESHOLD", "0")
    v2 = _search("display ospf peer neighbor state")

    assert v1["debug"]["retrieval_engine"] == "v1"
    assert v2["debug"]["retrieval_engine"] == "v2_indexed"
    assert _ids(v1) and _ids(v2)
    assert _ids(v2)[0] == _ids(v1)[0] == corpus["Huawei OSPF"]
    legs = v2["debug"]["v2_legs"]
    assert legs and any(item["status"] == "ok" and item["candidates"] > 0 for item in legs.values())


def test_v2_never_crosses_the_vendor_boundary(corpus, force_v2):
    result = _search("display ospf peer neighbor state Full")
    assert corpus["Cisco OSPF"] not in _ids(result)


def test_v2_enforces_acl_in_sql_and_python(corpus, force_v2):
    restricted = corpus["Huawei restricted runbook"]
    as_operator = _search("quantum flux capacitor maintenance procedure", roles=["Operator"])
    assert restricted not in _ids(as_operator)
    assert as_operator["debug"]["acl_stage"] == "sql_and_python"
    as_admin = _search("quantum flux capacitor maintenance procedure", roles=["Administrator"])
    assert _ids(as_admin) and _ids(as_admin)[0] == restricted


def test_v2_small_candidate_sets_use_the_exact_path(corpus, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "v2")
    monkeypatch.delenv("AI_RETRIEVAL_V2_EXACT_THRESHOLD", raising=False)
    result = _search("display ospf peer")
    assert result["debug"]["retrieval_engine"] == "v2_exact_small_set"
    assert _ids(result)[0] == corpus["Huawei OSPF"]


def test_shadow_serves_v1_and_reports_the_v2_comparison(corpus, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "v1")
    v1 = _search("display bgp peer established")
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "shadow")
    monkeypatch.setenv("AI_RETRIEVAL_SHADOW_MODE", "sync")
    monkeypatch.setenv("AI_RETRIEVAL_V2_EXACT_THRESHOLD", "0")
    shadow = _search("display bgp peer established")

    assert _ids(shadow) == _ids(v1)
    report = shadow["debug"]["shadow_v2"]
    assert report["status"] == "ok"
    assert report["engine"] == "v2_indexed"
    assert report["top1_match"] is True
    assert 0.0 <= report["overlap_at_k"] <= 1.0


class _BrokenEmbedder:
    model_id = "broken"

    def embed_query(self, _text):
        raise RuntimeError("embedding service unavailable")

    embed_text = embed_query


def test_v2_degrades_to_lexical_legs_without_a_query_embedding(corpus, force_v2):
    result = _search("display bgp peer established", embedder=_BrokenEmbedder())
    assert "QUERY_EMBEDDING_UNAVAILABLE" in result["debug"]["capability_degraded"]
    assert _ids(result) and _ids(result)[0] == corpus["Huawei BGP"]


def test_v2_expands_context_from_sibling_chunks(corpus, force_v2):
    result = _search("OSPF neighbor stuck in ExStart MTU mismatch")
    top = result["results"][0]
    assert top["storage_document_id"] == corpus["Huawei OSPF"]
    assert int(top.get("context_chunk_count") or 0) >= 1
    assert result["debug"]["v2_context_documents"] >= 1


# ── leg tuning (2026-11-22 benchmark): trigram terms ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query, expected",
    [
        ("Eth-Trunk LACP 成员口 Selected", {"eth-trunk", "成员口"}),
        ("ip route-static 默认路由 下一跳", {"route-static", "默认路由", "下一跳"}),
        ("S5700 GigabitEthernet0/0/1 shutdown", {"s5700", "gigabitethernet0/0/1"}),
        ("链路聚合 速率 双工 一致", {"链路聚合", "速率", "双工", "一致"}),
    ],
)
def test_trgm_terms_keep_identifiers_and_cjk(query, expected):
    assert set(_trgm_terms(query)) == expected


def test_trgm_terms_leave_plain_words_to_fts():
    assert _trgm_terms("OSPF neighbor stuck in ExStart MTU") == []
    assert len(_trgm_terms("a-1 b-2 c-3 d-4 e-5 f-6 g-7 h-8")) == 6


# ── m0332 ─────────────────────────────────────────────────────────────────


def _index(conn, create: bool) -> None:
    if create:
        conn.execute("CREATE INDEX IF NOT EXISTS ix_ai_chunk_search_tsv ON ai_document_chunk USING GIN (search_tsv)")
    else:
        conn.execute("DROP INDEX IF EXISTS ix_ai_chunk_search_tsv")
    conn.commit()


def test_trigger_keeps_search_tsv_equal_to_the_m0138_expression(corpus):
    from database.core import get_db_connection

    expected = "to_tsvector('simple', COALESCE(search_text, ''))"
    with get_db_connection() as conn:
        total, drift = conn.execute(
            f"SELECT COUNT(*), COUNT(*) FILTER (WHERE search_tsv IS DISTINCT FROM {expected}) FROM ai_document_chunk"
        ).fetchone()
        assert total > 0 and drift == 0
        chunk_id = conn.execute("SELECT id FROM ai_document_chunk ORDER BY id LIMIT 1").fetchone()[0]
        conn.execute("UPDATE ai_document_chunk SET search_text = ? WHERE id = ?", ("zebra quokka 斑马", chunk_id))
        conn.commit()
        stored = conn.execute("SELECT search_tsv::text FROM ai_document_chunk WHERE id = ?", (chunk_id,)).fetchone()[0]
    assert "zebra" in stored and "quokka" in stored


def test_fts_leg_uses_the_stored_column_only_when_its_index_is_valid(corpus, force_v2):
    from database.core import get_db_connection

    with get_db_connection() as conn:
        _index(conn, create=False)
    without_index = _search("display ospf peer neighbor state")
    assert without_index["debug"]["v2_fts_source"] == "expression"

    with get_db_connection() as conn:
        _index(conn, create=True)
    try:
        with_index = _search("display ospf peer neighbor state")
        assert with_index["debug"]["v2_fts_source"] == "search_tsv"
        assert _ids(with_index) == _ids(without_index)
        assert _ids(with_index)[0] == corpus["Huawei OSPF"]
    finally:
        with get_db_connection() as conn:
            _index(conn, create=False)


def test_fts_source_can_be_forced_back_to_the_expression(corpus, force_v2, monkeypatch):
    from database.core import get_db_connection

    with get_db_connection() as conn:
        _index(conn, create=True)
    try:
        monkeypatch.setenv("AI_RETRIEVAL_FTS_SOURCE", "expression")
        assert _search("display ospf peer")["debug"]["v2_fts_source"] == "expression"
    finally:
        with get_db_connection() as conn:
            _index(conn, create=False)


# ── trigram leg and ranking ───────────────────────────────────────────────


def test_trgm_leg_skips_plain_word_queries_and_runs_for_identifiers(corpus, force_v2, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_TRGM_MODE", "terms")
    plain = _search("display ospf peer neighbor state")
    assert plain["debug"]["v2_legs"]["trgm"]["status"] == "skipped_no_terms"
    identifiers = _search("ntp-service unicast-server clock")
    assert identifiers["debug"]["v2_legs"]["trgm"]["status"] == "ok"
    assert _ids(identifiers)[0] == corpus["Huawei NTP"]


def test_default_trgm_mode_skips_plain_word_queries(corpus, force_v2, monkeypatch):
    monkeypatch.delenv("AI_RETRIEVAL_TRGM_MODE", raising=False)
    plain = _search("display ospf peer neighbor state")
    assert plain["debug"]["v2_trgm_mode"] == "auto"
    assert plain["debug"]["v2_legs"]["trgm"]["status"] == "skipped_no_terms"
    assert _ids(plain)[0] == corpus["Huawei OSPF"]
    # A hyphenated command keeps the whole-query fuzzy match.
    command = _search("ntp-service unicast-server clock")
    assert command["debug"]["v2_legs"]["trgm"]["status"] in {"ok", "degraded"}
    assert command["debug"].get("v2_trgm_terms") is None
    assert _ids(command)[0] == corpus["Huawei NTP"]


def test_query_trgm_mode_always_runs_the_whole_query_match(corpus, force_v2, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_TRGM_MODE", "query")
    result = _search("display ospf peer neighbor state")
    assert result["debug"]["v2_legs"]["trgm"]["status"] in {"ok", "degraded"}


def test_unknown_trgm_mode_falls_back_to_auto(corpus, force_v2, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_TRGM_MODE", "bogus")
    assert _search("display ospf peer")["debug"]["v2_trgm_mode"] == "auto"


def test_recall_leg_scores_do_not_change_v2_ranking_against_v1(corpus, monkeypatch):
    queries = ["display ospf peer neighbor state", "vlan batch trunk", "ntp-service unicast-server", "acl number 3000 rule permit"]
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "v1")
    v1 = {query: _ids(_search(query)) for query in queries}
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "v2")
    monkeypatch.setenv("AI_RETRIEVAL_V2_EXACT_THRESHOLD", "0")
    for query in queries:
        assert _ids(_search(query))[:1] == v1[query][:1], query


# ── ranking cost (2026-11-22 benchmark: 186 ms of Python ranking) ─────────


def test_v2_scores_every_loaded_row_in_sql(corpus, force_v2):
    result = _search("display ospf peer neighbor state")
    debug = result["debug"]
    assert "VECTOR_SCORE_QUERY_FAILED" not in debug["capability_degraded"]
    assert debug.get("v2_vector_scored_rows", 0) > 0
    # No row needed its JSON vector parsed or a Python cosine.
    assert debug["rank_python_vector_rows"] == 0
    timing = debug["v2_timing_ms"]
    assert {"rank_filter", "rank_keyword", "rank_vector", "rank_score", "rank_item", "rank_post"} <= set(timing)


def test_sql_vector_scores_match_the_python_cosine(corpus, monkeypatch):
    query = "display ospf peer neighbor state"
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "v1")
    v1 = _search(query)
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "v2")
    monkeypatch.setenv("AI_RETRIEVAL_V2_EXACT_THRESHOLD", "0")
    v2 = _search(query)
    assert _ids(v2) == _ids(v1)
    for left, right in zip(v1["results"], v2["results"]):
        assert abs(float(left["vector_score"]) - float(right["vector_score"])) <= 1e-3
        assert abs(float(left["relevance_score"]) - float(right["relevance_score"])) <= 1e-3


# ── phase 5: shadow comparisons in the background, stored in m0333 ───────


def _shadow_rows():
    from database.core import get_db_connection

    with get_db_connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT status, error_code, v2_engine, top1_match, overlap_at_k, v1_result_count, v2_result_count, "
                "v1_document_ids, v2_document_ids, query_hash, query_preview FROM ai_retrieval_shadow_comparison ORDER BY id"
            ).fetchall()
        ]


@pytest.fixture
def shadow_env(monkeypatch):
    from ai.services import rag_retriever as retriever_module

    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "shadow")
    monkeypatch.setenv("AI_RETRIEVAL_V2_EXACT_THRESHOLD", "0")
    yield retriever_module
    retriever_module.wait_for_shadow_jobs(30)
    retriever_module.shutdown_shadow_executor(wait=True)


def test_shadow_comparison_is_stored_without_the_query_text(corpus, shadow_env, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_SHADOW_MODE", "sync")
    result = _search("display bgp peer established")
    assert result["debug"]["shadow_v2"]["status"] == "ok"
    rows = _shadow_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "ok" and row["v2_engine"] == "v2_indexed" and row["top1_match"] is True
    assert row["v1_document_ids"] and row["v1_document_ids"][0] == row["v2_document_ids"][0] == corpus["Huawei BGP"]
    assert len(row["query_hash"]) == 32 and row["query_preview"] is None


def test_shadow_query_preview_is_opt_in(corpus, shadow_env, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_SHADOW_MODE", "sync")
    monkeypatch.setenv("AI_RETRIEVAL_SHADOW_STORE_QUERY", "1")
    _search("display bgp peer established")
    assert "display bgp peer" in (_shadow_rows()[0]["query_preview"] or "")


def test_async_shadow_does_not_change_or_delay_the_served_result(corpus, shadow_env, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "v1")
    v1 = _search("display ospf peer neighbor state")
    monkeypatch.setenv("AI_RETRIEVAL_ENGINE", "shadow")
    monkeypatch.delenv("AI_RETRIEVAL_SHADOW_MODE", raising=False)
    served = _search("display ospf peer neighbor state")
    assert served["debug"]["shadow_v2"] == {"status": "scheduled"}
    assert _ids(served) == _ids(v1)
    assert shadow_env.wait_for_shadow_jobs(30)
    rows = _shadow_rows()
    assert len(rows) == 1 and rows[0]["status"] == "ok" and rows[0]["top1_match"] is True


def test_shadow_sampling_and_pending_cap(corpus, shadow_env, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_SHADOW_SAMPLE_RATE", "0")
    assert _search("display bgp peer")["debug"]["shadow_v2"] == {"status": "sampled_out"}
    monkeypatch.setenv("AI_RETRIEVAL_SHADOW_SAMPLE_RATE", "1")
    monkeypatch.setenv("AI_RETRIEVAL_SHADOW_MAX_PENDING", "1")
    monkeypatch.setitem(shadow_env._SHADOW_STATE, "pending", 1)
    try:
        assert _search("display bgp peer")["debug"]["shadow_v2"] == {"status": "dropped_busy"}
    finally:
        shadow_env._SHADOW_STATE["pending"] = 0
    assert _shadow_rows() == []


def test_v2_failure_in_shadow_is_recorded_and_v1_is_still_served(corpus, shadow_env, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_SHADOW_MODE", "sync")

    def broken(*_args, **_kwargs):
        raise RuntimeError("v2 broke")

    monkeypatch.setattr(RAGRetriever, "_candidates_v2", broken)
    result = _search("display bgp peer established")
    assert _ids(result)[0] == corpus["Huawei BGP"]
    assert result["debug"]["shadow_v2"]["error_code"] == "RETRIEVAL_V2_SHADOW_FAILED"
    rows = _shadow_rows()
    assert rows[0]["status"] == "error" and rows[0]["error_code"] == "RETRIEVAL_V2_SHADOW_FAILED"


def _shadow_report_module():
    import importlib.util
    import sys
    from pathlib import Path

    name = "nexora_rag_shadow_report"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parents[3] / "scripts" / "rag_shadow_report.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_shadow_report_counts_only_the_indexed_path(isolated_db):
    from database.core import get_db_connection

    report_module = _shadow_report_module()
    insert = (
        "INSERT INTO ai_retrieval_shadow_comparison (query_hash, status, error_code, v2_engine, top1_match, overlap_at_k, "
        "v1_result_count, v2_result_count, v1_latency_ms, v2_latency_ms, v1_document_ids, v2_document_ids) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    with get_db_connection() as conn:
        empty = report_module.summarize(conn)
        assert empty["status"] == "NO_DATA"
        conn.execute(insert, ["e" * 32, "ok", None, "v2_exact_small_set", True, 1.0, 3, 3, 10, 12, ["d1"], ["d1"]])
        conn.commit()
        assert report_module.summarize(conn)["status"] == "ONLY_EXACT_PATH"
        for index in range(9):
            conn.execute(insert, [f"{index:032d}", "ok", None, "v2_indexed", True, 1.0, 3, 3, 900, 400, ["d1", "d2"], ["d1", "d2"]])
        conn.execute(insert, ["f" * 32, "ok", None, "v2_indexed", False, 0.5, 3, 3, 900, 400, ["d1", "d2"], ["d3", "d1"]])
        conn.commit()
        few = report_module.summarize(conn, min_indexed=200)
        assert few["status"] == "INSUFFICIENT_DATA"
        report = report_module.summarize(conn, min_indexed=5)
    assert report["indexed"]["comparisons"] == 10
    assert report["indexed"]["top1_match_rate"] == 0.9
    assert report["status"] == "NOT_READY" and report["checks"]["top1_agreement"] is False
    assert report["worst_queries"][0]["query_hash"] == "f" * 32
    assert report["worst_queries"][0]["v2_top"] == ["d3", "d1"]
    assert report["worst_queries"][0]["v1_top"] == ["d1", "d2"]
    assert report["by_engine"] == {"v2_indexed": 10, "v2_exact_small_set": 1}
    assert "RAG 影子对比报告" in report_module.markdown(report)
    with get_db_connection() as conn:
        assert report_module.summarize(conn, min_indexed=5, min_top1=0.9)["status"] == "READY"
