from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "knowledge_engine_v2_rel002_postgres_gate",
    ROOT / "scripts" / "knowledge_engine_v2_rel002_postgres_gate.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_rel002_contract_and_static_startup_gate() -> None:
    contract = MODULE.load_contract()
    assert contract["authority"] == "PostgreSQL"
    assert contract["sqlite"] == "forbidden_for_acceptance"
    result = MODULE._static_gate()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())


def test_rel002_live_postgresql_gate_is_read_only_and_reports_current_history() -> None:
    report = MODULE.run_gate()
    assert report["postgres"]["database"] == "postgresql"
    assert report["postgres"]["transaction_read_only"] is True
    assert report["production_database_write"] is False
    assert report["sqlite"] == "forbidden_for_acceptance"
    # The current database records version 152 under a different migration
    # name.  The gate must surface that mismatch instead of rewriting history
    # or falsely marking REL-002 complete.
    assert report["status"] == "BLOCKED"
    assert "MIGRATION_NAME_DRIFT" in report["reason_codes"]
