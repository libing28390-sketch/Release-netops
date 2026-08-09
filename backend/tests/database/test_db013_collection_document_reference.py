from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-013-COLLECTION-DOCUMENT-REFERENCE.yaml"
REPORT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-013-COLLECTION-DOCUMENT-REFERENCE.md"
ER_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-001-core-er-model.yaml"
M0103 = ROOT / "backend" / "database" / "migrations" / "m0103_ai_platform_tables.py"
M0105 = ROOT / "backend" / "database" / "migrations" / "m0105_ai_security_operations_graph.py"
M0112 = ROOT / "backend" / "database" / "migrations" / "m0112_ai_knowledge_directories.py"
KNOWLEDGE_SERVICE = ROOT / "backend" / "ai" / "services" / "knowledge_service.py"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_db013_freezes_additive_membership_entity_without_changing_canonical_entities():
    data = _load(CONTRACT)
    assert data["task_id"] == "DB-013"
    assert data["priority"] == "P0"
    assert data["status"] == "frozen_for_implementation"
    assert data["decision"]["choice"] == "additive_tenant_scoped_collection_document_membership"
    entity = data["membership_entity"]
    assert entity["name"] == "kb_collection_document"
    assert entity["unique_keys"] == [["tenant_id", "collection_id", "document_id", "membership_kind"]]
    assert {"collection_id", "document_id", "membership_kind", "status"}.issubset(set(entity["required_columns"]))
    er = {item["name"]: item for item in _load(ER_CONTRACT)["entities"]}
    assert data["canonical_entities"]["kb_collection"]["required_columns"] == er["kb_collection"]["required_columns"]
    assert data["canonical_entities"]["kb_document"]["required_columns"] == er["kb_document"]["required_columns"]


def test_db013_membership_kinds_lifecycle_and_idempotency_are_explicit():
    entity = _load(CONTRACT)["membership_entity"]
    assert set(entity["membership_kinds"]) == {"primary", "secondary", "curated", "system", "temporary"}
    assert entity["membership_kind_rule"] == "unknown_kind_rejected_before_persist"
    assert {"draft", "active", "disabled", "archived", "deleted", "purged"}.issubset(set(entity["lifecycle_statuses"]))
    assert entity["unique_keys"] == [["tenant_id", "collection_id", "document_id", "membership_kind"]]
    behavior = _load(CONTRACT)["reference_behavior"]
    assert behavior["idempotency"].startswith("same_tenant_collection_document_kind_attach")
    assert behavior["concurrency"] == "lock_collection_then_document; compare_and_set_status_and_updated_at"
    assert "never_delete_document" in behavior["detach_behavior"]


def test_db013_acl_scope_and_retrieval_join_are_intersection_only():
    data = _load(CONTRACT)
    access = data["access_and_retrieval"]
    assert access["authorization_formula"].startswith("tenant_match AND collection_acl_allows")
    assert access["acl_precedence"] == "deny_in_any_collection_or_document_acl_wins; membership_never_grants"
    assert access["retrieval_predicate"] == "collection_document.status = active AND collection.status = active AND document.status = active"
    assert "metadata_json_collection_ids" in access["no_shortcuts"]
    assert "document_metadata_acl_override" in access["no_shortcuts"]
    assert data["canonical_metadata_boundary"]["read_model"].startswith("collection_document_view_may_project")


def test_db013_canonical_metadata_and_scope_mutations_are_forbidden():
    boundary = _load(CONTRACT)["canonical_metadata_boundary"]
    assert {"metadata_json", "acl_json", "original_content", "content_hash", "product_model_id", "software_version_id"}.issubset(set(boundary["protected_fields"]))
    forbidden = set(boundary["forbidden_mutations"])
    assert "copy_document_metadata_into_membership" in forbidden
    assert "overwrite_document_collection_id_on_secondary_attach" in forbidden
    assert "put_authorization_in_membership_metadata_json" in forbidden
    assert "collection_id" in boundary["allowed_membership_fields"]
    assert "document_id" in boundary["allowed_membership_fields"]


def test_db013_audits_real_v1_collection_document_and_directory_paths():
    data = _load(CONTRACT)
    m0103 = M0103.read_text(encoding="utf-8")
    m0105 = M0105.read_text(encoding="utf-8")
    m0112 = M0112.read_text(encoding="utf-8")
    service = KNOWLEDGE_SERVICE.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS ai_knowledge_base" in m0103
    assert "CREATE TABLE IF NOT EXISTS ai_document" in m0103
    assert "knowledge_base_id" in m0103
    for field in ("tenant_id", "acl_json"):
        assert field in m0105
    for table_marker in ("ai_knowledge_directory", "knowledge_base_id", "parent_id", "path"):
        assert table_marker in m0112
    for marker in ("create_knowledge_base", "list_knowledge_bases", "list_documents", "get_document_detail", "delete_document", "batch_delete_documents"):
        assert marker in service
    assert data["legacy_gap_audit"]["ai_knowledge_directory"]["mapping"] == "directory_tree_is_collection_ui_organization; directory_path_in_document_metadata_is_not_authoritative_membership"


def test_db013_tenant_permissions_and_audit_events_are_complete():
    security = _load(CONTRACT)["tenant_security_and_audit"]
    assert security["tenant_scope"].startswith("composite_tenant_id_plus_parent_id_foreign_keys")
    assert {"kb.collection.read", "kb.collection.manage", "kb.document.link", "kb.document.unlink", "kb.export"}.issubset(set(security["permissions"]))
    assert "cross_tenant_parent" in security["deny_conditions"]
    assert {"collection_document_attached", "collection_document_detached", "collection_document_reordered", "cross_tenant_reference_denied"}.issubset(set(security["audit_events"]))
    assert "no_source_content" in security["sensitive_data"]
    assert security["collection_acl_change"].startswith("separate_audited_operation")


def test_db013_migration_backfill_and_rollback_preserve_v1_and_source_facts():
    data = _load(CONTRACT)
    migration = data["migration_contract"]
    assert migration["status"] == "contract_only_no_production_ddl_in_db_013"
    assert migration["backfill"].startswith("report_legacy_knowledge_base_document_pairs")
    assert migration["idempotence"]
    assert migration["data_loss_policy"] == "no_canonical_metadata_rewrite_and_no_document_source_delete"
    assert data["rollback"]["runtime"]
    assert "retain_all_document_document_version_metadata" in data["rollback"]["data"]


def test_db013_report_has_reference_boundary_security_migration_and_v1_evidence():
    report = REPORT.read_text(encoding="utf-8")
    for marker in (
        "DB-013", "Collection", "Collection Document", "kb_collection_document", "kb_collection", "kb_document",
        "ACL", "Metadata", "tenant", "RBAC", "DB-009", "DB-014", "回滚", "V1", "Final Conclusion: PASS",
    ):
        assert marker in report, marker
