from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-017-MIGRATION-ORDER-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-017-MIGRATION-ORDER-CONTRACT.md"
RUNNER = ROOT / "backend" / "database" / "migrations" / "__init__.py"
M0111 = ROOT / "backend" / "database" / "migrations" / "m0111_ai_chunking_v2.py"
M0113 = ROOT / "backend" / "database" / "migrations" / "m0113_rag_metadata_v2.py"


def _load() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_db017_task_and_expand_backfill_enforce_order_are_frozen():
    data = _load()
    assert data["task_id"] == "DB-017"
    assert data["priority"] == "P0"
    assert data["status"] == "frozen_for_execution"
    phases = [item["phase"] for item in data["phase_order"]]
    assert phases == ["inventory", "expand_nullable", "backfill", "validate", "prepare_indexes_and_constraints", "validate_constraints", "enforce", "cleanup_deferred"]
    assert phases.index("expand_nullable") < phases.index("backfill") < phases.index("validate") < phases.index("enforce")
    assert "ADD_COLUMN_NOT_NULL_on_populated_table" in data["phase_order"][1]["forbidden"]
    assert "SET_NOT_NULL_only_after_zero_nulls" in data["phase_order"][6]["actions"]


def test_db017_field_classes_cover_identity_status_query_jsonb_and_vector():
    fields = _load()["field_classification"]
    assert set(fields) == {"identity_tenant_permission_scope", "lifecycle_status", "high_frequency_query_field", "JSONB_projection", "vector_or_search_projection"}
    for name, contract in fields.items():
        assert contract["expand"] == "nullable"
        assert contract["backfill"]
        assert contract["validate"]
        assert contract["enforce"]
    assert "cross_tenant" in fields["identity_tenant_permission_scope"]["validate"]
    assert "terminal_purge_rule" in fields["lifecycle_status"]["validate"]
    assert "normalization_hash" in fields["high_frequency_query_field"]["validate"]
    assert "never_use_JSONB_alone" in fields["JSONB_projection"]["enforce"]
    assert "dimension" in " ".join(fields["vector_or_search_projection"]["validate"])


def test_db017_constraint_and_batch_patterns_are_operationally_safe():
    data = _load()
    patterns = data["constraint_patterns"]
    assert "ADD_CONSTRAINT_NOT_VALID" in patterns["check"]
    assert "VALIDATE_CONSTRAINT" in patterns["foreign_key"]
    assert "CREATE_UNIQUE_INDEX_CONCURRENTLY" in patterns["unique"]
    assert "no_default_that_converts_unknown_to_active" in patterns["default"]
    batch = data["batch_and_checkpoint"]
    assert batch["cursor"].startswith("stable_primary_key")
    assert batch["page_size"] == "tenant_policy_bounded_max_5000"
    assert "lease_owner" in batch["job_fields"]
    assert "heartbeat_at" in batch["job_fields"]
    assert batch["restart"].startswith("resume_from_last_committed_checkpoint")
    assert "mapping_version" in batch["audit"]


def test_db017_failure_recovery_and_legacy_exceptions_are_explicit():
    data = _load()
    recovery = data["failure_and_recovery"]
    assert recovery["ordinary_error"].startswith("rollback_current_batch")
    assert recovery["validation_failure"].startswith("leave_constraint_absent")
    assert "cancel_statement" in recovery["lock_timeout"]
    assert "not_marked_applied" in recovery["partial_failure"]
    assert "after_three_same_approach_attempts" in recovery["repeated_failure"]
    audit = data["legacy_audit"]
    assert "commit_per_migration" in audit["migration_runner"]["observed"]
    assert "halt_higher_versions_after_failure" in audit["migration_runner"]["observed"]
    assert "nullable_normalized_content" in audit["m0111_ai_chunking_v2"]["observed"]
    assert "exclude_from_rag_not_null_default_is_legacy_compatibility_behavior" in audit["m0113_rag_metadata_v2"]["exception"]


def test_db017_real_runner_and_migrations_are_audited():
    runner = RUNNER.read_text(encoding="utf-8")
    m0111 = M0111.read_text(encoding="utf-8")
    m0113 = M0113.read_text(encoding="utf-8")
    for marker in ("discover_migrations", "schema_migrations", "commit()", "conn.rollback()", "halt"):
        assert marker in runner
    for marker in ("normalized_content", "content_hash", "chunking_version", "ALTER TABLE"):
        assert marker in m0111
    for marker in ("metadata_json", "JSONB", "exclude_from_rag", "DEFAULT 0"):
        assert marker in m0113


def test_db017_security_migration_rollback_and_report_markers_are_present():
    data = _load()
    security = data["security_and_governance"]
    assert security["authorization"].startswith("migration_actor_and_tenant_scope")
    assert "raw_prompt" in security["secret_policy"]
    assert "checkpoint_stores_hashes" in security["data_minimization"]
    migration = data["migration_contract"]
    assert migration["status"] == "contract_only_no_production_DDL_in_db_017"
    assert migration["upgrade"] == "expand_nullable_then_backfill_then_validate_then_enforce"
    assert migration["idempotence"]
    assert data["rollback"]["schema"].startswith("do_not_drop_legacy_columns")
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("DB-017", "nullable", "backfill", "validate", "enforce", "NOT NULL", "NOT VALID", "V1", "rollback", "DB-018", "Final Conclusion: PASS"):
        assert marker in report, marker
