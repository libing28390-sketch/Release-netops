from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-015-QUERY-INDEX-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-015-QUERY-INDEX-CONTRACT.md"
M0113 = ROOT / "backend" / "database" / "migrations" / "m0113_rag_metadata_v2.py"
RESOLVER = ROOT / "backend" / "ai" / "services" / "product_resolver.py"
RETRIEVER = ROOT / "backend" / "ai" / "services" / "rag_retriever.py"


def _load() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_db015_task_and_index_policy_are_frozen():
    data = _load()
    assert data["task_id"] == "DB-015"
    assert data["priority"] == "P0"
    assert data["status"] == "frozen_for_implementation"
    assert data["authority"] == "PostgreSQL"
    assert set(data["depends_on"]) >= {"DB-001", "DB-006", "DB-009", "DB-014"}
    policy = data["index_naming_and_build_policy"]
    assert policy["tenant_first"] is True
    assert policy["lower_snake_case"] is True
    assert policy["build"].startswith("CREATE_INDEX_CONCURRENTLY")
    assert "no_long_table_rewrite" in policy["lock_budget"]
    assert policy["rollback"].startswith("drop_only_the_new_index")


def test_db015_normalization_and_query_class_semantics_are_explicit():
    data = _load()
    normalization = data["normalization"]
    assert normalization["canonical_expression"] == "lower(btrim(value))"
    assert "Unicode_casefold" in normalization["unicode_policy"]
    assert normalization["null_policy"].startswith("null_is_not_empty")
    assert "kb_product_alias" in normalization["aliases"]["canonical_column"] or normalization["aliases"]["canonical_column"] == "normalized_alias"
    classes = data["query_classes"]
    assert classes["exact"]["required_keys"] == ["tenant_id", "status_or_active_predicate"]
    assert "metadata_json" in classes["exact"]["no_fallback"]
    assert "normalized_alias" in classes["alias"]["required_keys"]
    assert classes["alias"]["ambiguity"].startswith("resolver_must_return_candidates")
    assert classes["prefix"]["operator_class"] == "varchar_pattern_ops"
    assert classes["prefix"]["minimum_length"]
    assert "pg_trgm_similarity" in data["explain_and_acceptance"]["defer_to_db016"]


def test_db015_inventory_covers_exact_alias_prefix_and_catalog_joins():
    inventory = _load()["index_inventory"]
    expected_tables = {
        "kb_vendor",
        "kb_product_family",
        "kb_product_series",
        "kb_product_model",
        "kb_product_alias",
        "kb_os_family_and_generation",
        "kb_release_train_and_software_version",
        "kb_document_and_version",
        "kb_document_product_and_software",
        "kb_collection_document",
    }
    assert expected_tables == set(inventory)
    all_indexes = [item for entries in inventory.values() for item in entries]
    assert len(all_indexes) >= 20
    assert all(item["name"].startswith(("ix_v2_", "ux_v2_")) for item in all_indexes)
    assert all(item["columns"][0] == "tenant_id" for item in all_indexes)
    assert any(item["kind"] == "btree_pattern_ops" for item in all_indexes)
    assert any(item["kind"] == "unique_btree" and item["predicate"] == "status = 'active'" for item in all_indexes)
    alias_names = {item["name"] for item in inventory["kb_product_alias"]}
    assert "ux_v2_kb_product_alias_tenant_alias_kind_active" in alias_names
    assert "ix_v2_kb_product_alias_tenant_kind_prefix" in alias_names
    scope_columns = [item["columns"] for item in inventory["kb_document_product_and_software"]]
    assert any({"product_model_id", "software_version_id"}.issubset(columns) for columns in scope_columns)


def test_db015_tenant_status_vendor_product_version_order_is_reviewable():
    data = _load()
    joins = data["query_classes"]["vendor_product_version"]
    assert joins["join_order"][:4] == ["tenant_id", "vendor_id", "family_id", "series_id"]
    assert "product_model_id" in joins["join_order"]
    assert "software_version_id" in joins["join_order"]
    assert joins["unknown_policy"].startswith("unresolved_or_unknown")
    for entries in data["index_inventory"].values():
        for item in entries:
            assert item["columns"][0] == "tenant_id"
            if item["predicate"]:
                assert "status" in item["predicate"]
            assert item["supports"]


def test_db015_legacy_indexes_and_advisory_resolver_are_audited():
    data = _load()
    m0113 = M0113.read_text(encoding="utf-8")
    resolver = RESOLVER.read_text(encoding="utf-8")
    retriever = RETRIEVER.read_text(encoding="utf-8")
    for marker in ("ux_ai_document_document_id", "ix_ai_document_vendor", "ix_ai_document_status", "metadata_gin"):
        assert marker in m0113
    for marker in ("SERIES_ALIASES", "_canonical_series", "_series_matches", "vendor", "software_train"):
        assert marker in resolver
    for marker in ("tenant_id", "status", "product_series", "product_model", "metadata_json"):
        assert marker in retriever
    audit = data["legacy_and_adapter_audit"]
    assert "retain_V1_indexes" in audit["m0113_rag_metadata_v2"]["decision"]
    assert "static_aliases_are_seed_or_fallback_only" in audit["product_resolver"]["decision"]
    assert "legacy_JSON_fallback_is_adapter_only" in audit["rag_retriever"]["decision"]


def test_db015_explain_gate_has_all_required_query_plans_and_metrics():
    explain = _load()["explain_and_acceptance"]
    required = set(explain["required_plans"])
    assert {"exact_vendor", "exact_model", "alias_exact", "model_prefix", "version_prefix"}.issubset(required)
    assert "tenant_status_listing" in required
    assert "product_version_document_join" in required
    assert explain["explain_format"].startswith("EXPLAIN_(ANALYZE")
    for metric in ("p95_latency_and_buffer_budget_are_recorded", "index_size_and_write_amplification_are_recorded_before_release", "cross_tenant_rows_are_zero_in_result_and_plan_predicates"):
        assert metric in explain["acceptance"]


def test_db015_migration_security_rollback_and_report_evidence_are_present():
    data = _load()
    migration = data["migration_contract"]
    assert migration["status"] == "contract_only_no_production_ddl_in_db_015"
    assert migration["order"][0] == "add_normalized_columns_nullable"
    assert "validate_normalization_and_collisions" in migration["order"]
    assert "explain_gate" in migration["order"]
    security = data["security_and_governance"]
    assert security["authorization"].startswith("tenant_id_and_acl_scope")
    assert "raw_prompt" in security["no_secret_in_index"]
    assert "index_plan_review" in security["audit_events"]
    rollback = data["rollback"]
    assert rollback["schema"].startswith("drop_only_DB-015_indexes")
    assert rollback["data"].startswith("no_data_deletion")
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("DB-015", "Exact", "Alias", "Prefix", "tenant_id", "status", "vendor", "product", "version", "varchar_pattern_ops", "EXPLAIN", "DB-016", "rollback", "V1", "Final Conclusion: PASS"):
        assert marker in report, marker
