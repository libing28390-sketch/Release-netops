"""MIG-008 consistency and permission audit tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_mig008_consistency_audit_check.py"
SPEC = importlib.util.spec_from_file_location("mig008_audit", SCRIPT)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE := importlib.util.module_from_spec(SPEC))


def _doc(**overrides: object) -> dict:
    row = {"id": "doc-1", "tenant_id": "tenant-1", "content_hash": "", "normalized_content": "body", "document_version": "v1", "index_version": "idx1", "embedding_model": "model", "embedding_dimensions": 3, "acl_json": {}, "status": "active", "ingestion_status": "ready", "exclude_from_rag": False}
    row["content_hash"] = MODULE._sha256("body")
    row.update(overrides)
    return row


def _chunk(**overrides: object) -> dict:
    row = {"id": "chunk-1", "document_id": "doc-1", "tenant_id": "tenant-1", "content_hash": "h", "ordinal": 0, "document_version": "v1", "index_version": "idx1", "embedding_model": "model", "embedding_dimensions": 3, "embedding": [0.1, 0.2, 0.3], "metadata_json": {}}
    row.update(overrides)
    return row


def test_mig008_contract_is_postgresql_only_and_redacted() -> None:
    contract = MODULE.load_contract()
    assert contract["task_id"] == "MIG-008"
    assert contract["authority"] == "PostgreSQL"
    assert contract["sqlite"] == "forbidden_for_acceptance"
    assert contract["production_database_write"] is False
    assert "raw_content" in contract["security"]["forbidden_report_fields"]


def test_consistent_fixture_passes() -> None:
    result = MODULE.audit_rows([_doc()], [_chunk()], expected_documents=1)
    assert result["status"] == "PASS"
    assert result["reason_codes"] == []
    assert result["counts"]["documents"] == 1
    assert len(result["audit_digest"]) == 64


def test_hash_version_orphan_and_permission_findings_block() -> None:
    result = MODULE.audit_rows([_doc(content_hash="bad", tenant_id="")], [_chunk(document_id="missing", metadata_json={"tenant_id": "tenant-1"})], expected_documents=1)
    assert result["status"] == "BLOCKED"
    assert "DOCUMENT_HASH_MISMATCH" in result["reason_codes"]
    assert "DOCUMENT_TENANT_MISSING" in result["reason_codes"]
    assert "CHUNK_ORPHAN" in result["reason_codes"]
    assert result["counts"].get("chunk_metadata_identity_leak", 0) == 0


def test_quarantined_document_missing_derived_facts_is_reported_but_not_blocking() -> None:
    result = MODULE.audit_rows(
        [_doc(content_hash="", normalized_content="", status="quarantined", ingestion_status="quarantined")],
        [_chunk(content_hash="", embedding=None, embedding_model="", embedding_dimensions=None)],
        expected_documents=1,
    )
    assert result["status"] == "PASS"
    assert result["reason_codes"] == []
    assert result["counts"]["excluded_document_hash_unverifiable"] == 1
    assert result["counts"]["excluded_chunk_hash_unverifiable"] == 1
    assert result["counts"]["excluded_chunk_embedding_unavailable"] == 1


def test_chunk_identity_metadata_leak_is_blocking_and_values_are_not_echoed() -> None:
    result = MODULE.audit_rows([_doc()], [_chunk(metadata_json={"tenant_id": "secret-tenant", "acl_json": {"role": "admin"}})], expected_documents=1)
    assert result["status"] == "BLOCKED"
    assert "CHUNK_METADATA_IDENTITY_LEAK" in result["reason_codes"]
    assert "secret-tenant" not in json.dumps(result)
    assert "admin" not in json.dumps(result)


def test_live_postgresql_probe_reports_current_audit_without_sqlite() -> None:
    result = MODULE._postgres_probe(MODULE.load_expected_document_count())
    assert result["probe"]["database"] == "PostgreSQL"
    assert result["probe"]["transaction_read_only"] is True
    assert result["probe"]["sqlite"] == "forbidden"
    assert result["probe"]["status"] == "PASS"
    assert result["counts"]["documents"] == 156
    assert result["counts"]["chunks"] == 474
    assert result["status"] == "PASS"
    assert result["reason_codes"] == []
    assert result["counts"]["excluded_document_hash_unverifiable"] == 2
    assert result["counts"]["excluded_chunk_hash_unverifiable"] == 2
    assert result["counts"]["excluded_chunk_embedding_unavailable"] == 2
