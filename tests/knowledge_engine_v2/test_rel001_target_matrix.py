"""REL-001 release target matrix tests (filesystem-only, PostgreSQL authority)."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_rel001_target_matrix.py"
SPEC = importlib.util.spec_from_file_location("rel001_target_matrix", SCRIPT)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE := importlib.util.module_from_spec(SPEC))


def test_rel001_contract_is_postgresql_only_and_read_only() -> None:
    contract = MODULE.load_contract()
    assert contract["task_id"] == "REL-001"
    assert contract["authority"] == "PostgreSQL"
    assert contract["sqlite"] == "forbidden_for_acceptance"
    assert contract["production_database_write"] is False
    assert set(contract["targets"]) == {"windows_desktop", "ubuntu_native", "docker_compose", "ci"}


def test_rel001_target_matrix_passes_without_external_calls() -> None:
    result = MODULE.run_gate()
    assert result["status"] == "PASS"
    assert result["authority"] == "PostgreSQL"
    assert result["sqlite"] == "forbidden"
    assert result["production_database_write"] is False
    assert result["external_calls"] is False
    assert result["docker_runtime"] == "3.11"
    assert result["placeholder_scan"]["status"] == "PASS"
    assert result["v1_default_and_rollback_contract"] is True
    assert all(target["status"] for target in result["targets"].values())
