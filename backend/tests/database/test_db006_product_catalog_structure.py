from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-006-PRODUCT-CATALOG-STRUCTURE.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-006-PRODUCT-CATALOG-STRUCTURE.md"
ER_CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-001-core-er-model.yaml"
COMMON_CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-002-COMMON-COLUMN-SEMANTICS.yaml"
LIFECYCLE_CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-003-LIFECYCLE-POLICY.yaml"
SCHEMA = ROOT / "backend" / "database" / "schema.py"
RESOLVER = ROOT / "backend" / "ai" / "services" / "product_resolver.py"
RAG_MIGRATION = ROOT / "backend" / "database" / "migrations" / "m0113_rag_metadata_v2.py"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_db006_freezes_the_db001_four_level_hierarchy():
    data = _load(CONTRACT)
    assert data["task_id"] == "DB-006"
    assert data["status"] == "frozen_for_implementation"
    assert data["decision"]["choice"] == "additive_tenant_scoped_four_level_product_catalog"
    assert list(data["entities"]) == ["kb_product_family", "kb_product_series", "kb_product_model", "kb_product_alias"]
    assert data["entities"]["kb_product_family"]["unique_keys"] == [["tenant_id", "vendor_id", "code"]]
    assert data["entities"]["kb_product_series"]["unique_keys"] == [["tenant_id", "family_id", "code"]]
    assert data["entities"]["kb_product_model"]["unique_keys"] == [["tenant_id", "series_id", "model_code"]]
    assert data["entities"]["kb_product_alias"]["unique_keys"] == [["tenant_id", "normalized_alias", "alias_kind"]]


def test_db006_matches_db001_entities_and_db002_tenant_scope():
    data = _load(CONTRACT)
    er = _load(ER_CONTRACT)
    common = _load(COMMON_CONTRACT)
    er_entities = {entity["name"]: entity for entity in er["entities"]}
    for name, entity in data["entities"].items():
        assert name in er_entities
        assert set(entity["required_columns"]) == set(er_entities[name]["required_columns"])
        assert entity["unique_keys"] == er_entities[name]["unique_keys"]
        assert entity["foreign_keys"]
        assert set(common["columns"]).issuperset({"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by", "status"})
    scoped = set(_load(COMMON_CONTRACT)["scope_matrix"]["tenant_scoped_entities"])
    assert {"kb_product_family", "kb_product_series", "kb_product_model", "kb_product_alias"} <= scoped


def test_db006_lifecycle_and_alias_contracts_fail_closed():
    data = _load(CONTRACT)
    lifecycle = _load(LIFECYCLE_CONTRACT)
    expected_statuses = set(lifecycle["entity_policies"]["catalog_facts"]["allowed"])
    for entity in data["entities"].values():
        assert set(entity["lifecycle_statuses"]) == expected_statuses
    alias = data["entities"]["kb_product_alias"]
    assert set(alias["alias_kinds"]) == {"exact", "canonical", "prefix", "trigram"}
    assert alias["normalization"]["deterministic"] is True
    assert alias["normalization"]["original_alias_is_preserved"] is True
    assert alias["conflict_rules"]["no_first_match_fallback"] is True
    assert data["catalog_resolution_boundary"]["ambiguity_behavior"] == "return_candidates_and_require_clarification"


def test_db006_audits_legacy_device_types_and_rag_fields_without_conflating_them():
    data = _load(CONTRACT)
    schema = SCHEMA.read_text(encoding="utf-8")
    rag = RAG_MIGRATION.read_text(encoding="utf-8")
    resolver = RESOLVER.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS device_types" in schema
    for column in ("vendor", "model", "part_number", "device_role", "created_at", "updated_at"):
        assert column in schema
    assert data["legacy_gap_audit"]["device_types"]["classification"] == "inventory_hardware_type_not_canonical_knowledge_product"
    for field in ("product_family", "product_series", "product_model"):
        assert field in rag
        assert field in data["legacy_gap_audit"]["rag_metadata"]["observed_fields"]
    assert "SERIES_ALIASES" in resolver
    assert data["legacy_gap_audit"]["static_resolver_aliases"]["classification"] == "advisory_runtime_aliases"
    assert "forbidden_action" in data["legacy_gap_audit"]["device_types"]


def test_db006_tenant_and_storage_boundaries_are_explicit():
    data = _load(CONTRACT)
    assert data["tenant_and_constraints"]["tenant_fk_strategy"] == "composite_tenant_id_plus_parent_id_foreign_keys"
    assert "tenant_id" in data["tenant_and_constraints"]["common_columns"]
    forbidden = set(data["tenant_and_constraints"]["forbidden_storage"])
    assert "product_family_in_metadata_json_as_canonical_identity" in forbidden
    assert "vendor_text_join_without_kb_vendor_id" in forbidden
    assert "cli_platform_or_software_train_as_product_parent" in forbidden
    assert data["migration_contract"]["status"] == "contract_only_no_production_ddl_in_db_006"
    assert data["migration_contract"]["rollback"]
    assert data["migration_contract"]["data_loss_policy"] == "no_destructive_delete_and_no_legacy_metadata_rewrite"


def test_db006_report_has_security_migration_rollback_and_v1_evidence():
    report = REPORT.read_text(encoding="utf-8")
    for marker in (
        "DB-006", "kb_product_family", "kb_product_series", "kb_product_model", "kb_product_alias",
        "device_types", "ai_document", "ProductResolver.SERIES_ALIASES", "tenant", "回滚",
        "V1", "Final Conclusion: PASS",
    ):
        assert marker in report, marker
