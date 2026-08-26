"""MIG-002 source-first admissibility gate tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_mig002_source_first_check.py"
SPEC = importlib.util.spec_from_file_location("mig002_source_first", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_mig002_contract_is_source_first_and_direct_derivative_copy_is_forbidden() -> None:
    contract = MODULE.load_contract()
    assert contract["task_id"] == "MIG-002"
    assert contract["authority"] == "PostgreSQL"
    assert contract["automatic_direct_copy"] is False
    assert contract["source_document_policy"]["trusted_document_requires"]
    assert contract["chunk_policy"]["direct_copy"] == "forbidden"
    assert contract["embedding_policy"]["direct_copy"] == "forbidden"
    assert "sha256_original_content_matches_declared_hash" in contract["source_document_policy"]["trusted_document_requires"]


def test_mig002_postgresql_probe_classifies_sources_and_never_admits_direct_derivatives() -> None:
    result = MODULE.postgres_probe()
    assert result["status"] == "PASS"
    assert result["transaction_read_only"] is True
    assert result["production_database_write"] is False
    assert result["documents"]["total"] >= 0
    assert result["derivatives"]["direct_chunk_copy_allowed"] is False
    assert result["derivatives"]["direct_embedding_copy_allowed"] is False
