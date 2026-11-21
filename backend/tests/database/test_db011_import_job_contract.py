from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-011-IMPORT-JOB-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-011-IMPORT-JOB-CONTRACT.md"
ER_CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-001-core-er-model.yaml"
COMMON_CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-002-COMMON-COLUMN-SEMANTICS.yaml"
LIFECYCLE_CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-003-LIFECYCLE-POLICY.yaml"
M0113 = ROOT / "backend" / "database" / "migrations" / "m0113_rag_metadata_v2.py"
REINDEX_SERVICE = ROOT / "backend" / "ai" / "services" / "knowledge_reindex_service.py"
SCHEMA = ROOT / "backend" / "database" / "schema.py"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_db011_freezes_tenant_scoped_import_job_entity():
    data = _load(CONTRACT)
    assert data["task_id"] == "DB-011"
    assert data["priority"] == "P0"
    assert data["status"] == "frozen_for_implementation"
    assert data["decision"]["choice"] == "tenant_scoped_import_job_with_phase_state_machine_and_audited_progress"
    entity = data["entity"]
    er_entity = next(item for item in _load(ER_CONTRACT)["entities"] if item["name"] == "kb_import_job")
    assert entity["name"] == "kb_import_job"
    assert entity["required_columns"] == er_entity["required_columns"]
    assert entity["unique_keys"] == er_entity["unique_keys"]
    assert {"execution_state", "phase", "processed_count", "progress_percent", "max_retries", "idempotency_key", "lease_owner"}.issubset(
        {item["name"] for item in entity["optional_columns"]}
    )


def test_db011_common_columns_and_lifecycle_are_aligned():
    data = _load(CONTRACT)
    common = set(_load(COMMON_CONTRACT)["columns"])
    required = set(data["entity"]["required_columns"])
    assert {"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by", "status"}.issubset(required)
    assert common.issuperset({"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by", "status"})
    jobs_policy = _load(LIFECYCLE_CONTRACT)["entity_policies"]["jobs_and_observability"]
    assert data["entity"]["lifecycle_statuses"] == jobs_policy["allowed"]
    assert data["decision"]["invariants"][1] == "lifecycle_status_and_execution_state_are_not_conflated"


def test_db011_execution_states_and_phase_order_are_explicit_and_fail_closed():
    data = _load(CONTRACT)
    machine = data["execution_state_machine"]
    assert machine["initial"] == "queued"
    assert set(machine["terminal"]) == {"cancelled", "succeeded", "failed"}
    transitions = {(item["from"], item["to"]): item["operation"] for item in machine["transitions"] if item["from"] != "terminal"}
    assert ("queued", "running") in transitions
    assert ("running", "retry_wait") in transitions
    assert ("running", "cancel_requested") in transitions
    assert ("cancel_requested", "cancelled") in transitions
    assert "succeeded_to_running" in machine["forbidden_transitions"]
    phases = data["phase_contract"]["order"]
    assert phases[0] == "accepted" and phases[-1] == "completed"
    assert phases.index("chunked") < phases.index("embedded") < phases.index("indexed") < phases.index("completed")
    assert data["phase_contract"]["transition_rule"] == "monotonic_forward_or_explicit_retry_to_same_phase; no_silent_phase_regression"


def test_db011_progress_counters_and_server_derived_percent_have_invariants():
    progress = _load(CONTRACT)["progress_contract"]
    assert {"total_count", "processed_count", "parsed_count", "failed_count", "succeeded_count"}.issubset(set(progress["counters"]))
    assert "all_counters_are_non_negative" in progress["required_invariants"]
    assert "processed_count_less_than_or_equal_to_total_count" in progress["required_invariants"]
    assert "succeeded_terminal_requires_processed_count_equal_to_total_count" in progress["required_invariants"]
    assert progress["calculation"].startswith("progress_percent = 100_when_total_zero")
    assert progress["read_model"] == "API_may_expose_progress_snapshot_but_client_cannot_write_counters"


def test_db011_retry_cancellation_error_and_lease_contracts_are_safe():
    data = _load(CONTRACT)
    retry = data["retry_contract"]
    cancel = data["cancellation_contract"]
    errors = data["error_contract"]
    lease = data["lease_and_recovery"]
    assert retry["max_retries"] == "non_negative_bounded_by_tenant_policy"
    assert "tenant_id_plus_idempotency_key_unique" in retry["idempotency"]
    assert cancel["behavior"] == "stop_new_work_then_finish_current_transaction_and_mark_cancelled"
    assert cancel["idempotency"].startswith("repeated_cancel_request_returns_current_state")
    assert {"code", "safe_message", "phase", "attempt_no", "retryable"}.issubset(set(errors["error_json_shape"]))
    assert errors["redaction"] == "sanitize_before_log_persist_or_API_response"
    assert lease["claim"].startswith("atomic_update_where_execution_state_in_queued")
    assert lease["stale_worker"] == "cannot_update_after_lease_fencing_token_changes"


def test_db011_tenant_permissions_source_gate_and_audit_events_are_explicit():
    security = _load(CONTRACT)["tenant_security_and_audit"]
    assert security["tenant_scope"].startswith("tenant_id_is_required_in_create_select_update")
    assert {"kb.import.create", "kb.import.read", "kb.import.cancel", "kb.import.retry"}.issubset(set(security["permissions"]))
    assert "unknown_phase" in security["deny_conditions"]
    assert security["source_gate"] == "source_registry_allowlist_tls_ssrf_and_parser_policy_from_DB-008"
    assert {"phase_changed", "progress_updated", "retry_scheduled", "job_cancelled", "job_succeeded"}.issubset(set(security["audit_events"]))
    assert "no_plaintext_secret" in security["sensitive_data"]


def test_db011_audits_v1_reindex_and_generic_jobs_without_merging_them():
    data = _load(CONTRACT)
    m0113 = M0113.read_text(encoding="utf-8")
    service = REINDEX_SERVICE.read_text(encoding="utf-8")
    schema = SCHEMA.read_text(encoding="utf-8")
    legacy = data["legacy_gap_audit"]["ai_knowledge_reindex_job"]
    assert "CREATE TABLE IF NOT EXISTS ai_knowledge_reindex_job" in m0113
    for field in ("scope_json", "dry_run", "status", "total", "parsed", "failed", "error_log_json"):
        assert field in m0113
        assert field in legacy["observed_columns"] or field in ("total", "parsed", "failed")
    for marker in ("def create_job", "def run_job", "def retry", "_record_failure", "embedding_failed"):
        assert marker in service
    generic = data["legacy_gap_audit"]["generic_jobs"]
    assert "CREATE TABLE IF NOT EXISTS jobs" in schema
    assert generic["classification"] == "network_operation_job_not_canonical_knowledge_import"
    assert generic["mapping"] == "no_direct_merge; preserve_device_job_semantics_and_use_explicit_adapter_only"


def test_db011_migration_rollback_and_report_evidence_are_present():
    data = _load(CONTRACT)
    assert data["migration_contract"]["status"] == "contract_only_no_production_ddl_in_db_011"
    assert data["migration_contract"]["idempotence"]
    assert data["migration_contract"]["downgrade"]
    assert data["migration_contract"]["data_loss_policy"].startswith("no_document_source")
    assert data["rollback"]["runtime"]
    report = REPORT.read_text(encoding="utf-8")
    for marker in (
        "DB-011", "Import Job", "execution_state", "phase", "重试", "取消", "错误", "进度",
        "kb_import_job", "ai_knowledge_reindex_job", "tenant", "RBAC", "回滚", "V1", "DB-012",
        "Final Conclusion: PASS",
    ):
        assert marker in report, marker
