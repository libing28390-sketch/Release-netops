"""MIG-007 rebuild gate and PostgreSQL-only tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_mig007_rebuild_gate_check.py"
SPEC = importlib.util.spec_from_file_location("mig007_rebuild", SCRIPT)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE := importlib.util.module_from_spec(SPEC))


def test_mig007_contract_is_postgresql_only_and_has_full_phase_order() -> None:
    contract = MODULE.load_contract()
    assert contract["task_id"] == "MIG-007"
    assert contract["authority"] == "PostgreSQL"
    assert contract["sqlite"] == "forbidden_for_acceptance"
    assert contract["production_database_write"] is False
    assert tuple(contract["phase_order"]) == MODULE.PHASE_ORDER


def test_verified_row_gets_deterministic_parse_to_index_plan() -> None:
    entries = [{"legacy_id": "doc-1", "tenant_id_hash": "a" * 64, "metadata_hash": "b" * 64, "validation_grade": "verified"}]
    plan = MODULE.build_rebuild_plan(entries)
    assert plan["status"] == "READY"
    assert plan["eligible_rows"] == 1
    assert plan["skipped_rows"] == 0
    assert plan["provider_calls"] == 0
    assert plan["entries"][0]["phases"] == list(MODULE.PHASE_ORDER)
    assert "doc-1" in json.dumps(plan)


def test_unverified_rows_are_blocked_without_provider_or_side_effect() -> None:
    entries = [
        {"legacy_id": "doc-1", "tenant_id_hash": "a" * 64, "metadata_hash": "b" * 64, "validation_grade": "needs_validation", "reason_codes": ["SOURCE_REGISTRY_UNRESOLVED"]},
        {"legacy_id": "doc-2", "tenant_id_hash": "c" * 64, "metadata_hash": "d" * 64, "validation_grade": "unusable", "reason_codes": ["SECURITY_VALUE_REJECTED"]},
    ]
    plan = MODULE.build_rebuild_plan(entries)
    assert plan["status"] == "BLOCKED"
    assert plan["blocked_reason"] == "BLOCKED_NO_VERIFIED_SOURCE_ENTITIES"
    assert plan["eligible_rows"] == 0
    assert plan["skipped_rows"] == 2
    assert plan["provider_calls"] == 0
    assert plan["production_database_write"] is False
    assert "SOURCE_REGISTRY_UNRESOLVED" not in json.dumps(plan)
    assert "SECURITY_VALUE_REJECTED" not in json.dumps(plan)


def test_manifest_loader_rejects_duplicate_or_unredacted_identity() -> None:
    manifest = {"task_id": "MIG-006", "entries": [{"legacy_id": "doc", "tenant_id_hash": "a" * 64, "validation_grade": "verified"}, {"legacy_id": "doc", "tenant_id_hash": "a" * 64, "validation_grade": "verified"}]}
    try:
        MODULE.validate_manifest_payload(manifest)
    except AssertionError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate manifest was accepted")


def test_live_postgresql_gate_is_read_only_and_currently_blocked() -> None:
    manifest = MODULE.load_manifest()
    probe, plan = MODULE._postgres_probe(manifest)
    assert probe["status"] == "PASS"
    assert probe["database"] == "PostgreSQL"
    assert probe["transaction_read_only"] is True
    assert probe["production_database_write"] is False
    assert probe["provider_calls"] == 0
    assert plan["status"] == "BLOCKED"
    assert plan["blocked_reason"] == "BLOCKED_NO_VERIFIED_SOURCE_ENTITIES"
    assert plan["eligible_rows"] == 0
