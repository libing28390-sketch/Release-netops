from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-008-SOURCE-REGISTRY-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-008-SOURCE-REGISTRY-CONTRACT.md"
ER_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-001-core-er-model.yaml"
COMMON_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-002-COMMON-COLUMN-SEMANTICS.yaml"
LIFECYCLE_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-003-LIFECYCLE-POLICY.yaml"
M0103 = ROOT / "backend" / "database" / "migrations" / "m0103_ai_platform_tables.py"
M0105 = ROOT / "backend" / "database" / "migrations" / "m0105_ai_security_operations_graph.py"
VENDOR_SCOPE = ROOT / "docs" / "knowledge-engine-v2" / "governance" / "vendor-scope.yaml"
POC_SCOPE = ROOT / "docs" / "knowledge-engine-v2" / "governance" / "poc-scope.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_db008_freezes_source_registry_and_version_entities():
    data = _load(CONTRACT)
    assert data["task_id"] == "DB-008"
    assert data["status"] == "frozen_for_implementation"
    assert data["decision"]["choice"] == "explicit_tenant_scoped_source_registry_and_immutable_fetch_manifest"
    assert list(data["entities"]) == ["kb_source_registry", "kb_source_version"]
    assert data["entities"]["kb_source_registry"]["unique_keys"] == [["tenant_id", "canonical_url"]]
    assert data["entities"]["kb_source_version"]["unique_keys"] == [["tenant_id", "source_registry_id", "content_hash"]]


def test_db008_matches_db001_db002_and_db003_source_contracts():
    data = _load(CONTRACT)
    er_entities = {entity["name"]: entity for entity in _load(ER_CONTRACT)["entities"]}
    common = _load(COMMON_CONTRACT)
    source_policy = _load(LIFECYCLE_CONTRACT)["entity_policies"]["source_and_document_facts"]
    allowed_statuses = set(source_policy["allowed"])
    for name, entity in data["entities"].items():
        assert name in er_entities
        assert set(entity["required_columns"]) == set(er_entities[name]["required_columns"])
        assert entity["unique_keys"] == er_entities[name]["unique_keys"]
        assert set(entity["lifecycle_statuses"]) == allowed_statuses
        assert set(common["columns"]).issuperset({"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by", "status"})
    assert "allowed_host_and_trust_level_are_server_authorized" in er_entities["kb_source_registry"]["security"]


def test_db008_url_allowlist_and_ssrf_gate_is_fail_closed():
    data = _load(CONTRACT)
    gate = data["url_and_ssrf_gate"]
    assert gate["parse_before_network"] is True
    assert gate["host_allowlist"]["exact_match_default"] is True
    assert gate["host_allowlist"]["wildcard_hosts"] == "forbidden"
    assert gate["host_allowlist"]["allowed_host_must_match_canonical_url"] is True
    assert gate["network_safety"]["tls_certificate_validation"] == "required"
    assert gate["network_safety"]["dns_re_resolve_before_connect"] == "required"
    assert gate["network_safety"]["block_loopback_private_link_local_multicast_and_cloud_metadata"] is True
    assert gate["network_safety"]["outbound_method_allowlist"] == ["GET", "HEAD"]
    assert data["resolution_boundary"]["unknown_or_unallowlisted"] == "reject_before_network"
    assert data["entities"]["kb_source_registry"]["redirect_policy"]["revalidate_every_hop"] is True


def test_db008_policy_and_manifest_immutability_are_explicit():
    data = _load(CONTRACT)
    registry = data["entities"]["kb_source_registry"]
    version = data["entities"]["kb_source_version"]
    assert set(registry["policy_fields"]["relational_security_fields"]) >= {"allowed_host", "max_bytes", "timeout_seconds", "redirect_limit", "fetch_enabled"}
    assert registry["policy_fields"]["json_only_extensions"]
    assert version["immutability"]["update_rule"] == "append_new_version_and_never_overwrite_fact_fields"
    assert version["immutability"]["hash_algorithm"] == "sha256_lowercase_hex"
    assert "source_registry_id" in version["immutability"]["fact_fields"]
    assert data["collection_policy"]["retry"]["retry_4xx"] is False
    assert data["collection_policy"]["parser"]["parser_name_and_version_pinned"] is True


def test_db008_audits_real_v1_source_hints_and_governance_urls():
    data = _load(CONTRACT)
    m0103 = M0103.read_text(encoding="utf-8")
    m0105 = M0105.read_text(encoding="utf-8")
    vendor_scope = VENDOR_SCOPE.read_text(encoding="utf-8")
    poc_scope = POC_SCOPE.read_text(encoding="utf-8")
    for field in ("source", "knowledge_source_type", "source_trust_level"):
        assert field in m0103 or field in m0105
    for marker in ("source_url", "source_title", "source_section"):
        assert marker in data["legacy_gap_audit"]["ai_document_metadata"]["observed_fields"]
    assert "https://" in vendor_scope
    assert "scope_id: GOV-010" in poc_scope
    assert data["legacy_gap_audit"]["governance_sources"]["observed"]
    assert data["legacy_gap_audit"]["config_templates"]["classification"] == "display_reference_not_collection_authority"


def test_db008_tenant_security_migration_rollback_and_secret_rules():
    data = _load(CONTRACT)
    assert data["tenant_security_and_audit"]["tenant_fk_strategy"] == "composite_tenant_id_plus_parent_id_foreign_keys"
    assert data["tenant_security_and_audit"]["authorization"]
    assert data["tenant_security_and_audit"]["audit_events"]
    forbidden = set(data["tenant_security_and_audit"]["secret_policy"]["forbidden"])
    assert "url_userinfo" in forbidden
    assert "api_key_in_query" in forbidden
    assert data["migration_contract"]["status"] == "contract_only_no_production_ddl_in_db_008"
    assert data["migration_contract"]["rollback"]
    assert data["migration_contract"]["data_loss_policy"] == "no_remote_fetch_from_unallowlisted_target_and_no_source_fact_rewrite"


def test_db008_report_has_registry_ssrf_security_migration_and_v1_evidence():
    report = REPORT.read_text(encoding="utf-8")
    for marker in (
        "DB-008", "kb_source_registry", "kb_source_version", "allowed_host", "SSRF", "TLS",
        "ai_document", "vendor-scope.yaml", "tenant", "回滚", "V1", "Final Conclusion: PASS",
    ):
        assert marker in report, marker
