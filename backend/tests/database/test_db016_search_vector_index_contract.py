from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-016-SEARCH-VECTOR-INDEX-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-016-SEARCH-VECTOR-INDEX-CONTRACT.md"
M0104 = ROOT / "backend" / "database" / "migrations" / "m0104_ai_pgvector_rag.py"
M0113 = ROOT / "backend" / "database" / "migrations" / "m0113_rag_metadata_v2.py"
RETRIEVER = ROOT / "backend" / "ai" / "services" / "rag_retriever.py"
EMBEDDING = ROOT / "backend" / "ai" / "providers" / "embedding.py"


def _load() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_db016_capability_matrix_and_retrieval_order_are_frozen():
    data = _load()
    assert data["task_id"] == "DB-016"
    assert data["priority"] == "P0"
    assert data["status"] == "frozen_with_explain_gate"
    assert data["capability_matrix"]["pg_trgm"]["extension"] == "pg_trgm"
    assert data["capability_matrix"]["pgvector"]["extension"] == "vector"
    assert data["capability_matrix"]["inspection"]["helper"].endswith("postgres_extensions.py")
    assert data["retrieval_order"]["stages"] == ["tenant_acl_scope", "exact_catalog", "alias_exact", "anchored_prefix", "fts", "pg_trgm_fallback", "vector"]
    assert "no_silent_degradation" in data["retrieval_order"]


def test_db016_fts_index_and_query_contract_are_explicit():
    fts = _load()["index_definitions"]["fts"]
    assert set(fts["source_tables"]) == {"kb_document_version", "kb_chunk"}
    assert all(column["type"] == "tsvector" for column in fts["typed_columns"])
    assert all("to_tsvector('simple'" in column["expression"] for column in fts["typed_columns"])
    assert len(fts["indexes"]) == 2
    assert all(item["kind"] == "gin" for item in fts["indexes"])
    assert all("CREATE INDEX CONCURRENTLY" in item["sql"] for item in fts["indexes"])
    assert "websearch_to_tsquery" in fts["query_contract"]["operator"]
    assert "raw_to_tsquery_from_untrusted_input" in fts["query_contract"]["forbidden"]


def test_db016_trgm_and_jsonb_indexes_are_bounded_and_registered():
    data = _load()["index_definitions"]
    trgm = data["pg_trgm"]
    assert trgm["operator_class"] == "gin_trgm_ops"
    assert len(trgm["indexes"]) == 2
    assert all("status = 'active'" in item["sql"] for item in trgm["indexes"])
    assert trgm["query_contract"]["threshold"].startswith("tenant_policy_default")
    assert "unbounded_substring_scan" in trgm["query_contract"]["forbidden"]
    jsonb = data["jsonb"]
    assert jsonb["registered_paths"]
    assert {"metadata_json", "acl_json", "retrieval_trace_json"} <= {item["path"] for item in jsonb["registered_paths"]}
    assert any(item["kind"] == "gin_jsonb_path_ops" for item in jsonb["indexes"])
    assert any(item["kind"] == "expression_gin_jsonb" for item in jsonb["indexes"])
    assert "typed_software_version_join_remains_authoritative" in jsonb["indexes"][1]["filter_rule"]
    assert "raw_prompt_or_secret_indexing" in jsonb["query_contract"]["forbidden"]


def test_db016_pgvector_dimension_generation_and_index_options_are_frozen():
    vector = _load()["index_definitions"]["pgvector"]
    contract = vector["column_contract"]
    assert contract["type"] == "vector(dimension)"
    assert contract["dimension_source"] == "kb_embedding_model.dimension"
    assert set(contract["compatibility_key"]) >= {"tenant_id", "embedding_model_id", "index_version_id", "generation_no"}
    assert len(vector["indexes"]) == 2
    hnsw, ivf = vector["indexes"]
    assert hnsw["kind"] == "hnsw_vector_cosine"
    assert "m = 16" in hnsw["sql"]
    assert "ef_construction = 64" in hnsw["sql"]
    assert ivf["kind"] == "ivfflat_vector_cosine"
    assert "lists = 100" in ivf["sql"]
    assert "mixed_dimension_index" in vector["query_contract"]["forbidden"]
    assert "recall_at_k" in vector["query_contract"]["recall"]


def test_db016_explain_gate_covers_all_four_accelerators_and_metrics():
    gate = _load()["explain_gate"]
    assert gate["format"].startswith("EXPLAIN (ANALYZE, BUFFERS")
    assert gate["transaction"].startswith("read_only_transaction")
    names = {fixture["name"] for fixture in gate["fixtures"]}
    assert names == {"fts_tenant_document_search", "trgm_alias_fallback", "jsonb_registered_applicable_version", "vector_same_generation_search"}
    expected = {fixture["expected_index"] for fixture in gate["fixtures"]}
    assert any("search_active" in value for value in expected)
    assert any("trgm" in value for value in expected)
    assert any("applicable_versions" in value for value in expected)
    assert any("hnsw" in value or "ivfflat" in value for value in expected)
    for marker in ("required_index_or_reviewed_statistics_reason_is_present", "p95_latency_buffers_wal_and_index_size_are_recorded", "vector_recall_at_k_meets_model_contract", "zero_cross_tenant_rows_and_zero_acl_denials_leaking_content"):
        assert marker in gate["acceptance"]


def test_db016_audits_existing_extensions_migrations_retriever_and_embedding_contract():
    data = _load()
    m0104 = M0104.read_text(encoding="utf-8")
    m0113 = M0113.read_text(encoding="utf-8")
    retriever = RETRIEVER.read_text(encoding="utf-8")
    embedding = EMBEDDING.read_text(encoding="utf-8")
    for marker in ("ensure_required_extensions", "vector", "pg_trgm"):
        assert marker in m0104
    for marker in ("metadata_json", "metadata_gin", "JSONB"):
        assert marker in m0113
    for marker in ("tenant_id", "status", "metadata_json", "embedding_provider", "_cosine"):
        assert marker in retriever
    for marker in ("model_id", "dimensions", "version", "assert_embedding_compatible"):
        assert marker in embedding
    audit = data["legacy_gap_audit"]
    assert "retain_extension_gate" in audit["m0104_ai_pgvector_rag"]["decision"]
    assert "registered_JSONB_paths" in audit["m0113_rag_metadata_v2"]["decision"]
    assert "shadowed_before_read_switch" in audit["rag_retriever"]["decision"]
    assert "never_mix_vectors" in audit["embedding_provider"]["decision"]


def test_db016_security_migration_rollback_and_report_markers_are_present():
    data = _load()
    security = data["security_and_governance"]
    assert security["authorization"].startswith("tenant_and_acl_scope")
    assert "raw_prompt_answer_document_or_secret" in security["redaction"]
    assert "vector_model_mismatch" in security["audit_events"]
    assert "no_unbounded_jsonb_or_trigram_fallback_is_allowed" in data["explain_gate"]["acceptance"]
    migration = data["migration_contract"]
    assert migration["status"] == "contract_only_no_production_DDL_in_db_016"
    assert migration["order"][0] == "inspect_extensions"
    assert "capture_EXPLAIN" in migration["order"]
    assert "CREATE_INDEX_CONCURRENTLY_and_DROP_INDEX_CONCURRENTLY_outside_transaction" in migration["transaction_rules"]
    assert data["rollback"]["schema"].startswith("drop_only_DB016_indexes")
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("DB-016", "FTS", "pg_trgm", "JSONB", "pgvector", "EXPLAIN", "tenant", "ACL", "rollback", "DB-017", "V1", "Final Conclusion: PASS"):
        assert marker in report, marker
