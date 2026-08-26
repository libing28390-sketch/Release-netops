"""MIG-001 strategy and PostgreSQL catalog gate tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_mig001_strategy_check.py"
SPEC = importlib.util.spec_from_file_location("mig001_strategy", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_mig001_contract_freezes_four_layer_order_and_no_automatic_copy() -> None:
    contract = MODULE.load_contract()
    assert contract["task_id"] == "MIG-001"
    assert contract["authority"] == "PostgreSQL"
    assert contract["sqlite"] == "forbidden_for_acceptance"
    assert contract["automatic_migration_allowed"] is False
    assert tuple(contract["layers"]) == ("document", "metadata", "chunk", "embedding")
    assert contract["layers"]["document"]["strategy"].startswith("preserve_original")
    assert "do_not_copy_legacy_vectors" in contract["layers"]["embedding"]["strategy"]
    assert contract["execution_order"][0] == "W0_authoritative_postgresql_inventory"


def test_mig001_postgresql_catalog_probe_is_read_only_and_legacy_authority_exists() -> None:
    result = MODULE._catalog_probe()
    assert result["status"] == "PASS"
    assert result["database"] == "PostgreSQL"
    assert result["transaction_read_only"] is True
    assert result["production_database_write"] is False
    assert result["sqlite"] == "forbidden"
    assert result["tables"]["ai_document"]["exists"] is True
    assert result["tables"]["ai_document_chunk"]["exists"] is True
