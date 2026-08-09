from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-009-DOCUMENT-SCOPE-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-009-DOCUMENT-SCOPE-CONTRACT.md"
ER_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-001-core-er-model.yaml"
COMMON_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-002-COMMON-COLUMN-SEMANTICS.yaml"
LIFECYCLE_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-003-LIFECYCLE-POLICY.yaml"
M0103 = ROOT / "backend" / "database" / "migrations" / "m0103_ai_platform_tables.py"
M0105 = ROOT / "backend" / "database" / "migrations" / "m0105_ai_security_operations_graph.py"
M0113 = ROOT / "backend" / "database" / "migrations" / "m0113_rag_metadata_v2.py"
M0111 = ROOT / "backend" / "database" / "migrations" / "m0111_ai_chunking_v2.py"
KNOWLEDGE_SERVICE = ROOT / "backend" / "ai" / "services" / "knowledge_service.py"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_db009_freezes_document_version_and_scope_entities():
    data = _load(CONTRACT)
    assert data["task_id"] == "DB-009"
    assert data["status"] == "frozen_for_implementation"
    assert data["decision"]["choice"] == "immutable_document_identity_plus_versioned_facts_and_explicit_scope_links"
    assert list(data["entities"]) == ["kb_document", "kb_document_version", "kb_document_product", "kb_document_software"]
    assert data["entities"]["kb_document"]["unique_keys"] == [["tenant_id", "collection_id", "canonical_key"]]
    assert data["entities"]["kb_document_version"]["unique_keys"] == [["tenant_id", "document_id", "version_no"], ["tenant_id", "document_id", "content_hash"]]
    assert data["entities"]["kb_document_product"]["unique_keys"] == [["tenant_id", "document_version_id", "product_model_id", "applicability_kind"]]
    assert data["entities"]["kb_document_software"]["unique_keys"] == [["tenant_id", "document_version_id", "os_generation_id", "software_version_id", "cli_platform"]]


def test_db009_matches_db001_db002_and_lifecycle_contracts():
    data = _load(CONTRACT)
    er_entities = {entity["name"]: entity for entity in _load(ER_CONTRACT)["entities"]}
    common = _load(COMMON_CONTRACT)
    source_statuses = set(_load(LIFECYCLE_CONTRACT)["entity_policies"]["source_and_document_facts"]["allowed"])
    for name, entity in data["entities"].items():
        assert name in er_entities
        assert set(entity["required_columns"]) == set(er_entities[name]["required_columns"])
        assert entity["unique_keys"] == er_entities[name]["unique_keys"]
        assert set(common["columns"]).issuperset({"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by", "status"})
    for name in ("kb_document", "kb_document_version"):
        assert set(data["entities"][name]["lifecycle_statuses"]) == source_statuses
    assert data["document_scope"]["no_separate_kb_document_scope_table"] is True


def test_db009_scope_is_explicit_and_unknown_or_all_cannot_match():
    data = _load(CONTRACT)
    scope = data["document_scope"]
    assert set(scope["composed_of"]) == {
        "kb_document.collection_id_and_collection_acl", "kb_document_product", "kb_document_software"
    }
    assert "product_or_version_arrays_as_authoritative_scope" in scope["forbidden_shortcuts"]
    assert "all_or_unknown_sentinel_as_cross_scope_match" in scope["forbidden_shortcuts"]
    product = data["entities"]["kb_document_product"]
    software = data["entities"]["kb_document_software"]
    assert product["rules"]["product_model_id_required"] is True
    assert software["rules"]["all_sentinel_forbidden"] is True
    assert software["nullable_by_contract"]["software_version_id"]
    assert software["rules"]["platform_mapping"]


def test_db009_content_provenance_and_rebuild_boundaries_are_immutable():
    data = _load(CONTRACT)
    version = data["entities"]["kb_document_version"]
    assert "original_content" in version["immutability"]["fact_fields"]
    assert "content_hash" in version["immutability"]["fact_fields"]
    assert "normalized_content" in version["immutability"]["derived_fields"]
    assert version["immutability"]["update_rule"] == "append_new_version_and_never_overwrite_original_or_hash"
    assert data["metadata_and_provenance"]["provenance_requirements"]["source_version_reference"]
    assert data["metadata_and_provenance"]["provenance_requirements"]["parser_name_and_version"]
    assert "acl_in_metadata_json" in data["document_scope"]["forbidden_shortcuts"]


def test_db009_audits_real_v1_document_and_chunk_paths():
    data = _load(CONTRACT)
    m0103 = M0103.read_text(encoding="utf-8")
    m0105 = M0105.read_text(encoding="utf-8")
    m0113 = M0113.read_text(encoding="utf-8")
    m0111 = M0111.read_text(encoding="utf-8")
    service = KNOWLEDGE_SERVICE.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS ai_document" in m0103
    assert "CREATE TABLE IF NOT EXISTS ai_document_chunk" in m0103
    for field in ("tenant_id", "acl_json", "source_trust_level", "knowledge_source_type"):
        assert field in m0105
    for field in ("original_content", "product_family", "os_family", "software_release"):
        assert field in m0113
    assert "content_hash" in m0111
    assert "ai_document_and_chunk" in data["legacy_gap_audit"]["knowledge_service_delete_paths"]["observed"] or data["legacy_gap_audit"]["knowledge_service_delete_paths"]["observed"]
    assert "DELETE FROM ai_document_chunk" in service
    assert "DELETE FROM ai_document" in service
    assert data["legacy_gap_audit"]["ai_document_chunk"]["classification"] == "derived_retrieval_output_handled_by_DB-010"


def test_db009_tenant_security_migration_rollback_and_v1_gates():
    data = _load(CONTRACT)
    security = data["tenant_security_and_audit"]
    assert security["tenant_fk_strategy"] == "composite_tenant_id_plus_parent_id_foreign_keys"
    assert security["authorization"]
    assert security["audit_events"]
    assert security["untrusted_content"]
    assert data["migration_contract"]["status"] == "contract_only_no_production_ddl_in_db_009"
    assert data["migration_contract"]["rollback"]
    assert data["migration_contract"]["data_loss_policy"] == "no_original_content_delete_and_no_legacy_metadata_rewrite"


def test_db009_report_has_document_scope_security_migration_and_v1_evidence():
    report = REPORT.read_text(encoding="utf-8")
    for marker in (
        "DB-009", "kb_document", "kb_document_version", "kb_document_product", "kb_document_software",
        "Document Scope", "ACL", "content hash", "ai_document", "DB-010", "DB-013", "tenant",
        "回滚", "V1", "Final Conclusion: PASS",
    ):
        assert marker in report, marker
