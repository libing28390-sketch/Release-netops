from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-014-RELATIONAL-JSONB-BOUNDARY.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-014-RELATIONAL-JSONB-BOUNDARY.md"
M0103 = ROOT / "backend" / "database" / "migrations" / "m0103_ai_platform_tables.py"
M0105 = ROOT / "backend" / "database" / "migrations" / "m0105_ai_security_operations_graph.py"
M0113 = ROOT / "backend" / "database" / "migrations" / "m0113_rag_metadata_v2.py"
RAG_RETRIEVER = ROOT / "backend" / "ai" / "services" / "rag_retriever.py"
KNOWLEDGE_SERVICE = ROOT / "backend" / "ai" / "services" / "knowledge_service.py"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_db014_freezes_task_and_mandatory_relational_authority():
    data = _load(CONTRACT)
    assert data["task_id"] == "DB-014"
    assert data["priority"] == "P0"
    assert data["status"] == "frozen_for_implementation"
    assert data["decision"]["choice"] == "typed_relational_authority_with_bounded_jsonb_extension_payloads"
    mandatory = data["boundary_rules"]["mandatory_relational_authority"]
    assert {"id", "tenant_id", "status", "created_by", "updated_by"}.issubset(set(mandatory["identity_and_join"]) | set(mandatory["lifecycle_and_security"]))
    assert {"document_id", "document_version_id", "collection_id", "chunk_id", "request_trace_id"}.issubset(set(mandatory["identity_and_join"]))
    assert {"total_count", "failed_count", "retry_count", "latency_ms"}.issubset(set(mandatory["high_frequency_counters"]))
    assert mandatory["rule"] == "never_accept_only_json_key_for_any_mandatory_relational_authority_field"


def test_db014_jsonb_payloads_are_purpose_bound_and_cannot_be_authority():
    allowed = _load(CONTRACT)["boundary_rules"]["jsonb_allowed_extension_payloads"]
    assert set(allowed) == {"metadata_json", "acl_json", "scope_json", "error_json", "evidence_json", "retrieval_trace_json", "derived_context_json"}
    assert "tenant_id" in allowed["metadata_json"]["forbidden"]
    assert "ACL_decision" in allowed["metadata_json"]["forbidden"]
    assert "implicit_tenant" in allowed["acl_json"]["forbidden"]
    assert "retry_counter" in allowed["scope_json"]["forbidden"]
    assert "last_error_code" in allowed["error_json"]["required_relational_projections"]
    assert "sole_product_id" in allowed["evidence_json"]["forbidden"]
    assert "raw_query" in allowed["retrieval_trace_json"]["forbidden"]


def test_db014_table_matrix_keeps_identity_filters_and_permissions_typed():
    matrix = _load(CONTRACT)["table_boundary_matrix"]
    assert {"tenant_id", "code", "status"}.issubset(set(matrix["kb_vendor"]["relational_authority"]))
    assert {"tenant_id", "canonical_key", "content_hash", "source_registry_id", "status"}.issubset(set(matrix["kb_document_and_version"]["relational_authority"]))
    assert {"product_model_id", "os_generation_id", "software_version_id", "cli_platform", "status"}.issubset(set(matrix["kb_document_product_and_software"]["relational_authority"]))
    assert {"tenant_id", "collection_id", "document_id", "membership_kind", "status"}.issubset(set(matrix["kb_collection_document"]["relational_authority"]))
    assert {"tenant_id", "job_kind", "phase", "retry_count", "idempotency_key"}.issubset(set(matrix["kb_import_job"]["relational_authority"]))
    assert "acl_json" in matrix["kb_collection"]["jsonb_allowed"]
    assert "capabilities_json" in matrix["ai_provider_model_route"]["jsonb_allowed"]


def test_db014_json_schema_limits_and_promotion_gate_are_explicit():
    data = _load(CONTRACT)
    limits = data["jsonb_schema_and_limits"]
    assert limits["storage_type"].startswith("PostgreSQL_JSONB")
    assert limits["version_field"] == "payload_schema_version_required_for_new_contract_payloads"
    assert "per_payload_bytes_tenant_policy" in limits["size_limits"]
    assert "max_nesting_depth_tenant_policy" in limits["size_limits"]
    assert limits["redaction"] == "recursive_secret_redaction_before_persist_and_before_export"
    assert limits["null_semantics"] == "null_is_not_unknown_or_all_and_must_not_expand_scope"
    promotion = data["promotion_policy"]
    assert "uniqueness_requirement" in promotion["trigger"]
    assert promotion["process"][0] == "inventory_keys"
    assert "collision_report" in promotion["process"]
    assert "query_plan_uses_typed_index" in promotion["acceptance"]
    assert promotion["forbidden"]


def test_db014_audits_real_json_usage_and_typed_legacy_columns():
    data = _load(CONTRACT)
    m0113 = M0113.read_text(encoding="utf-8")
    rag = RAG_RETRIEVER.read_text(encoding="utf-8")
    service = KNOWLEDGE_SERVICE.read_text(encoding="utf-8")
    m0103 = M0103.read_text(encoding="utf-8")
    m0105 = M0105.read_text(encoding="utf-8")
    for marker in ("metadata_json", "JSONB", "metadata_gin", "ix_ai_document_vendor", "ix_ai_document_status"):
        assert marker in m0113
    for marker in ("metadata_json", "product_series", "product_model", "cli_platform", "tenant_id", "status"):
        assert marker in rag or marker in service
    for marker in ("metadata_json", "acl_json", "knowledge_base_id"):
        assert marker in m0103 or marker in m0105
    assert data["legacy_gap_audit"]["m0113_rag_metadata_v2"]["boundary_decision"].startswith("typed_high_frequency_columns")
    assert data["legacy_gap_audit"]["rag_retriever"]["boundary_decision"].startswith("legacy_JSON_fallback_only")


def test_db014_security_forbids_secrets_and_json_authorization_shortcuts():
    data = _load(CONTRACT)
    security = data["security_and_governance"]
    assert "api_key" in security["no_secret"]
    assert "raw_prompt" in security["no_secret"]
    assert security["authorization"].startswith("permission_subject_and_tenant_scope_must_be_relational")
    assert security["fail_closed"].startswith("malformed_json_unknown_status")
    assert "record_promotion_backfill_collision_quarantine" in security["audit"]
    assert "only_redacted_registered_keys" in security["JSONB_export"]


def test_db014_migration_rollback_and_report_evidence_are_present():
    data = _load(CONTRACT)
    migration = data["migration_contract"]
    assert migration["status"] == "contract_only_no_production_ddl_in_db_014"
    assert migration["fresh_upgrade"]
    assert migration["idempotence"]
    assert migration["downgrade"]
    assert data["rollback"]["runtime"]
    report = REPORT.read_text(encoding="utf-8")
    for marker in (
        "DB-014", "关系字段", "JSONB", "typed", "metadata_json", "acl_json", "scope_json", "error_json",
        "tenant", "唯一性", "权限", "EXPLAIN", "DB-015", "DB-016", "回滚", "V1", "Final Conclusion: PASS",
    ):
        assert marker in report, marker
