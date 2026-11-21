from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-007-OS-SOFTWARE-STRUCTURE.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-007-OS-SOFTWARE-STRUCTURE.md"
ER_CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-001-core-er-model.yaml"
COMMON_CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-002-COMMON-COLUMN-SEMANTICS.yaml"
LIFECYCLE_CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-003-LIFECYCLE-POLICY.yaml"
RAG_MIGRATION = ROOT / "backend" / "database" / "migrations" / "m0113_rag_metadata_v2.py"
INTENT_PARSER = ROOT / "backend" / "ai" / "services" / "intent_parser.py"
PLATFORM_MIGRATION = ROOT / "backend" / "database" / "migrations" / "m0072_platform_registry_p0.py"
VENDOR_SCOPE = ROOT / "docs" / "knowledge-engine" / "governance" / "vendor-scope.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_db007_freezes_the_db001_os_and_software_hierarchies():
    data = _load(CONTRACT)
    assert data["task_id"] == "DB-007"
    assert data["status"] == "frozen_for_implementation"
    assert data["decision"]["choice"] == "additive_orthogonal_os_and_software_catalog"
    assert list(data["entities"]) == ["kb_os_family", "kb_os_generation", "kb_release_train", "kb_software_version"]
    assert data["entities"]["kb_os_family"]["unique_keys"] == [["tenant_id", "vendor_id", "code"]]
    assert data["entities"]["kb_os_generation"]["unique_keys"] == [["tenant_id", "os_family_id", "code"]]
    assert data["entities"]["kb_release_train"]["unique_keys"] == [["tenant_id", "vendor_id", "code"]]
    assert data["entities"]["kb_software_version"]["unique_keys"] == [["tenant_id", "release_train_id", "normalized_version"]]


def test_db007_matches_db001_db002_and_db003_contracts():
    data = _load(CONTRACT)
    er_entities = {entity["name"]: entity for entity in _load(ER_CONTRACT)["entities"]}
    common = _load(COMMON_CONTRACT)
    catalog_statuses = set(_load(LIFECYCLE_CONTRACT)["entity_policies"]["catalog_facts"]["allowed"])
    for name, entity in data["entities"].items():
        assert name in er_entities
        assert set(entity["required_columns"]) == set(er_entities[name]["required_columns"])
        assert entity["unique_keys"] == er_entities[name]["unique_keys"]
        assert set(entity["lifecycle_statuses"]) == catalog_statuses
        assert set(common["columns"]).issuperset({"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by", "status"})


def test_db007_keeps_cli_platform_and_software_identity_orthogonal():
    data = _load(CONTRACT)
    migration = PLATFORM_MIGRATION.read_text(encoding="utf-8")
    assert "platform_profiles" in migration
    assert "connection_driver" in migration
    assert "parser_platform" in migration
    assert "software_train" not in migration
    assert "kb_product_model" in data["orthogonality_contract"]["software_train"]["forbidden_parent"]
    assert "platform_profiles" in data["orthogonality_contract"]["software_train"]["forbidden_parent"]
    assert data["orthogonality_contract"]["cli_platform"]["forbidden_inference"]
    parser = INTENT_PARSER.read_text(encoding="utf-8")
    assert "Never infer cli_platform solely from software_train" in parser


def test_db007_version_normalization_and_unknown_behavior_are_fail_closed():
    data = _load(CONTRACT)
    version = data["entities"]["kb_software_version"]["version_rules"]
    assert version["original_version_string"] == "immutable_source_fact"
    assert version["normalized_version"] == "deterministic_derived_value_used_for_exact_lookup"
    assert "never_plain_lexicographic_comparison" in version["ordering"]
    assert "unknown" in version
    assert "not_an_active_catalog_row" in version["unknown"]
    assert data["orthogonality_contract"]["version_resolution"]["unsupported_or_unknown"]
    assert data["normalization_and_validation"]["software_version"]["preserve_original_version_string"] is True
    assert data["normalization_and_validation"]["software_version"]["invalid_value"]


def test_db007_audits_real_legacy_os_and_version_fields_and_governance_seeds():
    data = _load(CONTRACT)
    rag = RAG_MIGRATION.read_text(encoding="utf-8")
    parser = INTENT_PARSER.read_text(encoding="utf-8")
    scope = VENDOR_SCOPE.read_text(encoding="utf-8")
    for field in ("os_family", "os_generation", "software_train", "software_release"):
        assert field in rag
        assert field in data["legacy_gap_audit"]["rag_metadata"]["observed_fields"]
    for marker in ("train_match", "release_match", "os_family", "os_generation"):
        assert marker in parser
    for marker in ("os_family:", "primary_version:", "compatibility_version:"):
        assert marker in scope
    assert data["legacy_gap_audit"]["inventory_devices"]["classification"] == "asset_snapshot_not_software_catalog_fact"
    assert data["legacy_gap_audit"]["config_templates"]["classification"] == "compatibility_range_input"


def test_db007_has_tenant_security_migration_rollback_and_v1_gates():
    data = _load(CONTRACT)
    assert data["tenant_and_security"]["tenant_fk_strategy"] == "composite_tenant_id_plus_parent_id_foreign_keys"
    assert data["tenant_and_security"]["authorization"]
    assert data["tenant_and_security"]["audit"]
    forbidden = set(data["tenant_and_security"]["forbidden_storage"])
    assert "software_version_as_authorization_scope" in forbidden
    assert "raw_provider_secret_or_endpoint_in_catalog_metadata" in forbidden
    assert data["migration_contract"]["status"] == "contract_only_no_production_ddl_in_db_007"
    assert data["migration_contract"]["rollback"]
    assert data["migration_contract"]["data_loss_policy"] == "no_destructive_delete_and_no_original_version_rewrite"


def test_db007_report_has_structure_security_migration_rollback_and_v1_evidence():
    report = REPORT.read_text(encoding="utf-8")
    for marker in (
        "DB-007", "kb_os_family", "kb_os_generation", "kb_release_train", "kb_software_version",
        "cli_platform", "UNKNOWN", "ai_document", "intent_parser.py", "tenant", "回滚",
        "V1", "Final Conclusion: PASS",
    ):
        assert marker in report, marker
