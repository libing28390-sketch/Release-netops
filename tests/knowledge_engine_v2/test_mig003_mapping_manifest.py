"""MIG-003 deterministic identity mapping and PostgreSQL gate tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_mig003_mapping_manifest_check.py"
SPEC = importlib.util.spec_from_file_location("mig003_mapping", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_mig003_contract_and_ids_are_deterministic() -> None:
    contract = MODULE.load_contract()
    assert contract["task_id"] == "MIG-003"
    assert contract["authority"] == "PostgreSQL"
    assert contract["sqlite"] == "forbidden_for_acceptance"
    first = MODULE.deterministic_ids("tenant-a", "legacy-a", "a" * 64)
    second = MODULE.deterministic_ids("tenant-a", "legacy-a", "a" * 64)
    other_tenant = MODULE.deterministic_ids("tenant-b", "legacy-a", "a" * 64)
    assert first == second
    assert first != other_tenant


def test_mig003_manifest_classifies_without_raw_content_or_secrets() -> None:
    rows = [
        {
            "id": "legacy-1", "tenant_id": "tenant-1", "document_id": "semantic-1", "source": "upload",
            "content_hash": "b" * 64, "original_content": "private body", "normalized_content": "private body",
            "status": "active", "exclude_from_rag": 0,
        }
    ]
    entries, counts = MODULE.build_entries(rows, set())
    assert counts["legacy_documents"] == 1
    assert counts["conditional_reconciliation"] == 1
    assert entries[0]["source_registry_resolution"] == "unresolved"
    rendered = str(entries)
    assert "private body" not in rendered
    assert "tenant-1" not in rendered
    assert entries[0]["tenant_id_hash"]
    assert entries[0]["v2_document_id"]


def test_mig003_live_postgresql_probe_is_read_only_and_one_to_one() -> None:
    probe, entries, counts = MODULE._read_only_probe()
    assert probe["status"] == "PASS"
    assert probe["database"] == "PostgreSQL"
    assert probe["transaction_read_only"] is True
    assert probe["production_database_write"] is False
    assert probe["sqlite"] == "forbidden"
    assert len(entries) == counts["legacy_documents"]
    assert counts["v2_id_collisions"] == 0
