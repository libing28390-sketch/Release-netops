"""MIG-007 source/catalog seed preflight tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_mig007_source_seed_preflight.py"
SPEC = importlib.util.spec_from_file_location("mig007_source_seed_preflight", SCRIPT)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE := importlib.util.module_from_spec(SPEC))


def test_candidate_fixture_matches_allowlist_and_is_verified_only_in_memory() -> None:
    allowlist, snapshot = MODULE.load_inputs()
    result = MODULE.candidate_preflight(allowlist, snapshot)
    assert result["candidate_fixture_grade"] == "verified"
    source_entries = snapshot.get("source_versions") or snapshot.get("source_refs")
    assert result["allowlisted_source_count"] == len(source_entries)
    assert "CATALOG_OWNER_REVIEW_REQUIRED" in result["reasons"]
    assert "SOURCE_VERSION_FACTS_MISSING" in result["reasons"]


def test_live_postgresql_preflight_is_read_only_and_remains_blocked() -> None:
    result = MODULE.run_gate()
    assert result["status"] == "BLOCKED"
    assert result["authority"] == "PostgreSQL"
    assert result["sqlite"] == "forbidden"
    assert result["live"]["transaction_read_only"] is True
    assert result["production_database_write"] is False
    assert result["provider_calls"] == 0
    assert "SOURCE_REGISTRY_BINDING_MISSING" in result["blocker_reasons"]
    assert "SOURCE_VERSION_BINDING_MISSING" in result["blocker_reasons"]
