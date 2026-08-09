from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-005-VENDOR-REGISTRY-BOUNDARY.yaml"
REPORT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-005-VENDOR-REGISTRY-BOUNDARY.md"
ER_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-001-core-er-model.yaml"
COMMON_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-002-COMMON-COLUMN-SEMANTICS.yaml"
PLATFORM_MIGRATION = ROOT / "backend" / "database" / "migrations" / "m0072_platform_registry_p0.py"
PLATFORM_SERVICE = ROOT / "backend" / "services" / "platform_registry_service.py"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_db005_freezes_kb_vendor_and_reuses_execution_registry_only():
    data = _load(CONTRACT)
    assert data["task_id"] == "DB-005"
    assert data["status"] == "frozen_for_implementation"
    assert data["decision"]["choice"] == "create_kb_vendor_and_reuse_platform_profiles_for_execution_identity"
    assert data["canonical_kb_vendor"]["table"] == "kb_vendor"
    assert data["canonical_kb_vendor"]["api_resource"] == "kb_vendors"
    assert data["existing_network_registry"]["table"] == "platform_profiles"
    assert data["explicit_mapping"]["table"] == "kb_vendor_platform"
    assert data["explicit_mapping"]["status"] == "planned_schema_contract_no_production_ddl_in_db_005"


def test_db005_is_consistent_with_db001_and_db002_common_fields():
    data = _load(CONTRACT)
    er = _load(ER_CONTRACT)
    common = _load(COMMON_CONTRACT)
    vendor = next(entity for entity in er["entities"] if entity["name"] == "kb_vendor")
    required = set(data["canonical_kb_vendor"]["required_columns"])
    assert required == set(vendor["required_columns"])
    assert set(common["columns"]).issuperset(required - {"code", "name"})
    assert vendor["unique_keys"] == [["tenant_id", "code"]]
    assert data["canonical_kb_vendor"]["identity_rules"]["unique_key"] == ["tenant_id", "code"]


def test_db005_audits_the_real_platform_registry_and_system_seeds():
    data = _load(CONTRACT)
    migration = PLATFORM_MIGRATION.read_text(encoding="utf-8")
    service = PLATFORM_SERVICE.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS platform_profiles" in migration
    for field in ("platform_code", "connection_driver", "parser_platform", "source", "status", "current_release_id"):
        assert field in migration
        assert field in data["existing_network_registry"]["authoritative_fields"]
    assert "SYSTEM_PROFILES" in service
    assert "PLATFORM_ALIASES" in service
    assert data["seed_and_backfill"]["system_profile_source"].startswith("services/platform_registry_service.py")
    assert set(data["seed_and_backfill"]["deterministic_vendor_codes"]) == {
        "Cisco", "Huawei", "H3C", "Juniper", "Arista", "ZTE", "Ruijie", "DPtech", "Maipu"
    }


def test_db005_forbids_free_text_and_ai_provider_inference():
    data = _load(CONTRACT)
    forbidden = set(data["existing_network_registry"]["vendor_column"]["forbidden_uses"])
    assert {"authorization", "foreign_key_resolution", "command_or_driver_inference"} <= forbidden
    separation = data["separation_contract"]
    assert separation["ai_provider_table"] == "ai_provider"
    assert separation["ai_provider_role"]
    assert "ai_provider_as_kb_vendor" in separation["prohibited_reuse"]
    assert "provider_name_as_network_authorization_scope" in separation["prohibited_reuse"]
    assert "ambiguous_result" in data["explicit_mapping"]["resolution"]
    assert "quarantined" in data["explicit_mapping"]["resolution"]["ambiguous_result"]
    assert "unknown_result" in data["explicit_mapping"]["resolution"]


def test_db005_has_tenant_security_migration_and_rollback_gates_without_ddl():
    data = _load(CONTRACT)
    mapping = data["explicit_mapping"]
    assert "tenant_id" in mapping["columns"]
    assert "created_by" in mapping["columns"]
    assert "updated_by" in mapping["columns"]
    assert "tenant_mapping_cannot_cross_tenant_boundaries" in mapping["constraints"]
    assert data["migration_and_rollback"]["preconditions"]
    assert data["migration_and_rollback"]["rollback"]
    assert data["migration_and_rollback"]["data_loss_policy"] == "no_destructive_delete_and_no_platform_profile_rewrite"
    assert data["implementation_boundary"]["db_005_deliverables"][-1].startswith("do_not_modify_production_schema")


def test_db005_report_contains_decision_boundary_and_final_conclusion():
    report = REPORT.read_text(encoding="utf-8")
    for marker in (
        "DB-005", "kb_vendor", "kb_vendors", "platform_profiles", "kb_vendor_platform",
        "SYSTEM_PROFILES", "ai_provider", "回滚", "PostgreSQL", "Final Conclusion: PASS",
    ):
        assert marker in report, marker
