"""MIG-006 contract and PostgreSQL-only validation tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_mig006_official_entity_validation_check.py"
SPEC = importlib.util.spec_from_file_location("mig006_official", SCRIPT)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE := importlib.util.module_from_spec(SPEC))


def _allowlist() -> dict:
    return MODULE.load_allowlist()


def _row(**overrides: object) -> dict:
    row = {
        "id": "legacy-1", "tenant_id": "tenant-1", "source": "official-source-1",
        "source_status": "active", "source_validation_status": "valid",
        "source_url": "https://support.huawei.com/enterprise/en/doc/EDOC1100463796/page",
        "vendor": "Huawei", "product_family": "CloudEngine 6800", "product_series": "CE68xx",
        "product_model": "CE6885", "os_family": "VRP8", "os_generation": "VRP8",
        "software_train": "V300", "software_release": "V300R024C10SPC500", "cli_platform": "huawei_vrp",
        "metadata_json": {"vendor": "Huawei", "product_model": "CE6885"},
    }
    row.update(overrides)
    return row


def test_mig006_contract_is_postgresql_only_and_body_inference_forbidden() -> None:
    contract = MODULE.load_contract()
    assert contract["task_id"] == "MIG-006"
    assert contract["authority"] == "PostgreSQL"
    assert contract["sqlite"] == "forbidden_for_acceptance"
    assert contract["production_database_write"] is False
    assert contract["source_authority"]["body_text_inference"] == "forbidden"


def test_exact_official_fixture_is_verified_only_when_catalog_is_available() -> None:
    result = MODULE.classify_entity(_row(), _allowlist(), catalog_available=True)
    assert result["grade"] == "verified"
    assert result["reason_codes"] == []
    assert result["metadata_hash"]


def test_upload_unknown_and_missing_official_evidence_fail_closed() -> None:
    result = MODULE.classify_entity(_row(source="upload", source_status="", source_validation_status="", source_url="", product_model="UNKNOWN", software_release="UNKNOWN"), _allowlist(), catalog_available=True)
    assert result["grade"] == "needs_validation"
    assert "SOURCE_REGISTRY_UNRESOLVED" in result["reason_codes"]
    assert "OFFICIAL_EVIDENCE_MISSING" in result["reason_codes"]
    assert "PRODUCT_UNKNOWN" in result["reason_codes"]
    assert "SOFTWARE_VERSION_UNKNOWN" in result["reason_codes"]


def test_vendor_and_scope_conflict_is_unusable_without_body_inference() -> None:
    result = MODULE.classify_entity(_row(vendor="Cisco", product_family="CloudEngine 6800"), _allowlist(), catalog_available=True)
    assert result["grade"] == "unusable"
    assert "PRODUCT_NOT_CANONICAL" in result["reason_codes"]
    assert "VENDOR_NOT_CANONICAL" not in result["reason_codes"]
    assert "Cisco" not in json.dumps(result)


def test_manifest_is_redacted_and_hash_only_for_tenant_identity() -> None:
    entries, counts, digest = MODULE.build_manifest_entries([_row()], _allowlist(), catalog_available=False)
    assert counts["legacy_documents"] == 1
    assert entries[0]["tenant_id_hash"] != "tenant-1"
    assert "source_url" not in entries[0]
    assert "original_content" not in entries[0]
    assert len(digest) == 64


def test_live_postgresql_probe_is_read_only_and_no_sqlite_acceptance() -> None:
    probe, entries, counts, digest = MODULE._postgres_probe(_allowlist())
    assert probe["status"] == "PASS"
    assert probe["database"] == "PostgreSQL"
    assert probe["transaction_read_only"] is True
    assert probe["production_database_write"] is False
    assert probe["sqlite"] == "forbidden"
    assert len(entries) == counts["legacy_documents"]
    assert set(entry["validation_grade"] for entry in entries) <= {"verified", "needs_validation", "unusable"}
    assert len(digest) == 64
