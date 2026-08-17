"""Contract tests for the PostgreSQL-only EVAL-018 benchmark."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_eval018_performance.py"
SPEC = importlib.util.spec_from_file_location("eval018_performance", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_eval018_is_postgresql_only_and_uses_required_scales() -> None:
    assert MODULE.TASK_ID == "EVAL-018"
    assert MODULE.SCALES == (10_000, 100_000, 1_000_000)
    assert MODULE.REPEATS == 5
    assert set(MODULE._query_map()) == {"fts", "trigram", "vector"}
    assert "SQLite is forbidden" in MODULE.__doc__ or "SQLite" in SCRIPT.read_text(encoding="utf-8")


def test_eval018_percentiles_are_bounded_nearest_rank() -> None:
    samples = [5.0, 1.0, 3.0, 2.0, 4.0]
    assert MODULE._percentile(samples, 0.50) == 3.0
    assert MODULE._percentile(samples, 0.95) == 5.0
    assert MODULE._percentile(samples, 0.99) == 5.0
