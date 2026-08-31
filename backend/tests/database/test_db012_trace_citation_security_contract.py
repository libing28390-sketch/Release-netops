from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-012-TRACE-CITATION-SECURITY-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-012-TRACE-CITATION-SECURITY-CONTRACT.md"
ER_CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-001-core-er-model.yaml"
M0103 = ROOT / "backend" / "database" / "migrations" / "m0103_ai_platform_tables.py"
M0105 = ROOT / "backend" / "database" / "migrations" / "m0105_ai_security_operations_graph.py"
ASSISTANT = ROOT / "backend" / "ai" / "services" / "assistant.py"
GATEWAY = ROOT / "backend" / "ai" / "gateway" / "llm_gateway.py"
AUDIT_SERVICE = ROOT / "backend" / "services" / "audit_service.py"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_db012_freezes_request_trace_spine_and_four_logical_structures():
    data = _load(CONTRACT)
    assert data["task_id"] == "DB-012"
    assert data["priority"] == "P0"
    assert data["status"] == "frozen_for_implementation"
    assert data["decision"]["choice"] == "append_only_request_spine_with_retrieval_rag_citation_and_security_projections"
    spine = data["canonical_spine"]
    er = next(item for item in _load(ER_CONTRACT)["entities"] if item["name"] == "ai_request_trace")
    assert spine["required_columns"] == er["required_columns"]
    assert spine["foreign_keys"] == er["foreign_keys"]
    assert set(data["logical_structures"]) == {"retrieval_log", "rag_trace", "citation_validation", "security_audit"}


def test_db012_retrieval_log_is_structured_hashed_and_generation_aware():
    data = _load(CONTRACT)
    retrieval = data["logical_structures"]["retrieval_log"]
    assert {"request_trace_id", "retrieval_trace_id", "attempt_no", "query_hash", "index_version_id", "chunk_version_id", "candidate_count", "selected_count", "status"}.issubset(set(retrieval["required_fields"]))
    assert retrieval["count_invariants"] == ["candidate_count_gte_selected_count", "selected_count_gte_zero", "latency_ms_gte_zero"]
    assert "query_hash_is_hmac_or_server_salted_sha256" in retrieval["privacy"]
    assert "ACL_and_trust_checked_before_selected_count" in retrieval["relation_rules"]
    assistant = ASSISTANT.read_text(encoding="utf-8")
    for marker in ("_knowledge_retrieval_trace", "metadata_candidate_documents", "candidate_count", "dedup_document_count", "vector_top_n"):
        assert marker in assistant


def test_db012_rag_trace_captures_attempt_chain_without_raw_prompt_or_answer():
    rag = _load(CONTRACT)["logical_structures"]["rag_trace"]
    assert {"request_trace_id", "retrieval_trace_id", "citation_trace_id", "attempt_no", "prompt_id", "prompt_version", "model_id", "index_version_id", "context_hash", "answer_hash", "status"}.issubset(set(rag["required_fields"]))
    assert rag["attempt_chain"] == ["primary_attempt", "fallback_attempts", "final_attempt_id", "all_attempts_same_tenant"]
    assert "prompt_body_forbidden" in rag["privacy"]
    assert rag["completion_rule"].startswith("completed_requires_retrieval_trace")
    assistant = ASSISTANT.read_text(encoding="utf-8")
    for marker in ("knowledge_trace", "citations", "request_id", "fallback"):
        assert marker in assistant


def test_db012_citation_validation_is_source_hash_and_acl_gated():
    citation = _load(CONTRACT)["logical_structures"]["citation_validation"]
    assert {"citation_trace_id", "rag_trace_id", "citation_no", "document_version_id", "chunk_id", "chunk_content_hash", "locator_hash", "claim_hash", "validation_status", "validator_version"}.issubset(set(citation["required_fields"]))
    assert citation["validation_statuses"] == ["verified", "missing", "mismatch", "stale", "acl_denied", "untrusted", "not_checked", "failed"]
    assert citation["validation_order"][-1] == "freshness_policy"
    assert "verified_requires_all_required_steps_and_source_row_is_active_and_tenant_visible" in citation["pass_rule"]
    assert "no_answer_span_body" in citation["privacy"]
    m0105 = M0105.read_text(encoding="utf-8")
    assistant = ASSISTANT.read_text(encoding="utf-8")
    assert "citations_json" in m0105 and "ai_evidence" in m0105
    assert "citations =" in assistant


def test_db012_security_audit_is_metadata_only_and_fail_closed():
    security = _load(CONTRACT)["logical_structures"]["security_audit"]
    assert {"request_trace_id", "event_key", "policy_version", "decision", "data_level", "finding_categories_json", "payload_bytes", "redaction_count"}.issubset(set(security["required_fields"]))
    assert {"allow", "minimize", "redact", "block", "fail_closed", "review"}.issubset(set(security["decision_allowlist"]))
    assert {"D0", "D3", "D6"}.issubset(set(security["data_levels"]))
    assert "no_api_key" in security["privacy"] and "no_raw_device_output" in security["privacy"]
    assert security["redaction_rule"].startswith("redact_before_persist")
    gateway = GATEWAY.read_text(encoding="utf-8")
    audit = AUDIT_SERVICE.read_text(encoding="utf-8")
    for marker in ("_log_security_audit", "ai_outbound_audits", "finding_categories_json", "payload_bytes"):
        assert marker in gateway
    for marker in ("def log_audit_event", "redact_audit_value", "details_json", "request_id"):
        assert marker in audit


def test_db012_relationships_lifecycle_and_tenant_guards_are_explicit():
    data = _load(CONTRACT)
    relationships = data["trace_relationships"]
    assert any(item["from"] == "ai_request_trace" and item["to"] == "kb_retrieval_log" for item in relationships)
    assert any(item["from"] == "kb_rag_trace" and item["to"] == "kb_citation_validation" for item in relationships)
    states = data["state_and_consistency"]
    assert "completed_after_security_decision" in states["monotonic_rules"]
    assert "cross_tenant" in states
    assert states["unknown"].startswith("fail_closed")
    security = data["tenant_security_and_audit"]
    assert security["tenant_scope"].startswith("tenant_id_in_every_insert_select_join")
    assert {"ai.trace.read", "ai.citation.validate", "ai.audit.read"}.issubset(set(security["permissions"]))
    assert security["security_failure"].startswith("audit_write_failure")


def test_db012_legacy_request_message_evidence_and_security_adapters_are_audited():
    data = _load(CONTRACT)
    m0103 = M0103.read_text(encoding="utf-8")
    m0105 = M0105.read_text(encoding="utf-8")
    request_log = data["legacy_gap_audit"]["ai_request_log"]
    for field in ("request_id", "provider_id", "model_id", "input_tokens", "output_tokens", "latency_ms", "error_code"):
        assert field in m0103
        assert field in request_log["observed_columns"]
    for table_marker in ("ai_messages", "ai_evidence", "ai_outbound_audits", "ai_tool_calls"):
        assert table_marker in m0105
    assert data["legacy_gap_audit"]["ai_outbound_audits"]["classification"] == "metadata_only_external_egress_security_adapter"
    assert data["legacy_gap_audit"]["ai_messages_and_evidence"]["classification"] == "conversation_and_tool_evidence_adapter_not_hash_validated_citation_record"


def test_db012_migration_rollback_and_report_evidence_are_present():
    data = _load(CONTRACT)
    migration = data["migration_contract"]
    assert migration["status"] == "contract_only_no_production_ddl_in_db_012"
    assert migration["fresh_upgrade"]
    assert migration["idempotence"]
    assert migration["downgrade"]
    assert data["rollback"]["runtime"]
    report = REPORT.read_text(encoding="utf-8")
    for marker in (
        "DB-012", "Retrieval Log", "RAG Trace", "Citation Validation", "Security Audit", "ai_request_trace",
        "kb_retrieval_log", "kb_rag_trace", "kb_citation_validation", "audit_ai_security_event", "ACL", "hash",
        "RBAC", "回滚", "V1", "DB-013", "Final Conclusion: PASS",
    ):
        assert marker in report, marker
