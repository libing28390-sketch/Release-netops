"""CHK-016 is a deterministic in-memory experiment, with no SQLite fallback."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[2] / "scripts" / "knowledge_engine_v2_chk016_offline_experiment.py"
_SPEC = importlib.util.spec_from_file_location("chk016_experiment", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
run_experiment = _MODULE.run_experiment


def test_chk016_offline_experiment_is_reproducible_and_structurally_valid() -> None:
    report = run_experiment()
    assert report["status"] == "PASS"
    assert report["database"] == "none"
    assert report["deterministic_repeat"] is True
    assert report["all_configurations_valid"] is True
    assert report["recommendation"] == "baseline_v2"
    assert len(report["configurations"]) == 4
    assert all(item["lineage_complete"] for item in report["configurations"])
    assert all(item["parent_child_valid"] and item["neighbor_symmetric"] for item in report["configurations"])
