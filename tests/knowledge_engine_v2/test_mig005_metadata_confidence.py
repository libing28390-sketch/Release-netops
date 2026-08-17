"""MIG-005 metadata confidence contract and PostgreSQL tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_mig005_metadata_confidence_check.py"
SPEC = importlib.util.spec_from_file_location("mig005_metadata", SCRIPT)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE := importlib.util.module_from_spec(SPEC))


def _row(metadata: object, **overrides: object) -> dict:
    row = {
        "id": "legacy", "tenant_id": "tenant", "document_id": "semantic", "metadata_json": metadata,
        "metadata_parse_status": "parsed", "metadata_parse_error": "", "status": "active",
        "exclude_from_rag": 0, "source_trust_level": "internal",
    }
    row.update(overrides)
    return row


def _complete() -> dict:
    return {
        "schema_version": "1.0", "document_id": "doc-1", "title": "title", "vendor": "Huawei",
        "product_type": "switch", "document_category": "hardware", "source_type": "official",
        "official_only": True, "status": "active", "product_model": "CE6885",
    }


def test_mig005_contract_defines_exactly_three_grades() -> None:
    contract = MODULE.load_contract()
    assert contract["task_id"] == "MIG-005"
    assert contract["authority"] == "PostgreSQL"
    assert contract["sqlite"] == "forbidden_for_acceptance"
    assert set(contract["grades"]) == {"trusted", "needs_validation", "unusable"}


def test_mig005_classifies_trusted_needs_validation_and_unusable() -> None:
    trusted = MODULE.classify_metadata(_row(_complete()))
    needs = MODULE.classify_metadata(_row({**_complete(), "product_model": "UNKNOWN"}))
    unusable = MODULE.classify_metadata(_row({**_complete(), "secret": "sk-abcdefghijklmnopqrstuvwxyz"}))
    assert trusted["grade"] == "trusted"
    assert needs["grade"] == "needs_validation"
    assert "unknown_applicability" in needs["reason_codes"]
    assert unusable["grade"] == "unusable"
    assert "server_owned_key" in unusable["reason_codes"]
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in json.dumps(unusable)


def test_mig005_missing_or_invalid_metadata_is_not_trusted() -> None:
    missing = MODULE.classify_metadata(_row(None, metadata_parse_status="missing"))
    malformed = MODULE.classify_metadata(_row("{bad", metadata_parse_status="failed", metadata_parse_error="parser detail"))
    assert missing["grade"] == "unusable"
    assert malformed["grade"] == "unusable"
    assert "parser detail" not in json.dumps(malformed)


def test_mig005_live_postgresql_probe_is_read_only_and_three_way() -> None:
    probe, entries, counts, digest = MODULE._postgres_probe()
    assert probe["status"] == "PASS"
    assert probe["database"] == "PostgreSQL"
    assert probe["transaction_read_only"] is True
    assert probe["production_database_write"] is False
    assert probe["sqlite"] == "forbidden"
    assert len(entries) == counts["legacy_documents"]
    assert set(entry["grade"] for entry in entries) <= {"trusted", "needs_validation", "unusable"}
    assert len(digest) == 64
