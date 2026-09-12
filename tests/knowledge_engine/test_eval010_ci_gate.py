"""EVAL-010 PostgreSQL-only Knowledge Engine CI and release gate contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[2] / "scripts" / "knowledge_eval_ci_gate_check.py"
_SPEC = importlib.util.spec_from_file_location("eval010_ci_gate", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_eval010_ci_and_release_use_postgresql_and_profiles() -> None:
    report = _MODULE.validate_ci_gate()
    assert report["status"] == "PASS"
    assert report["task_id"] == "EVAL-010"
    assert report["small_ci_profile"] == "small"
    assert report["full_release_profile"] == "full"
    assert report["database_url_scheme"] == "postgresql"
    assert report["postgres_service"] is True
    assert report["database_contract"] == "postgresql_only"
    assert report["isolated_anchor_evidence"] is True
    assert report["automated_source_review_evidence"] is True
    assert report["signed_anchor_dataset_evidence"] is True
    assert report["postgres_ci_image"] == "repository_dockerfile_with_pgvector_and_pg_trgm"
    assert report["ci_node_version"] == "22.22.2"
    assert report["windows_pgvector_version"] == "0.8.6"
    assert report["windows_node_install"] == "official_msi"


def test_eval010_small_profile_is_fixed_and_deterministic() -> None:
    offline_path = Path(__file__).parents[2] / "scripts" / "knowledge_eval_offline.py"
    spec = importlib.util.spec_from_file_location("eval010_offline", offline_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    first = module.run_offline_evaluation(profile="small")
    second = module.run_offline_evaluation(profile="small")
    assert first == second
    assert first["status"] == "PASS"
    assert first["profile"] == "small"
    assert first["component_count"] == 4
    assert [item["task_id"] for item in first["components"]] == [
        "EVAL-001",
        "EVAL-003",
        "EVAL-005",
        "EVAL-007",
    ]
    assert first["database"] == "none"
    assert first["sqlite"] == "not_used"
    assert first["external_network"] == "not_used"
    assert first["production_write"] is False
