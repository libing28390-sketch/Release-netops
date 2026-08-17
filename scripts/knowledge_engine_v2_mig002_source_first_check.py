"""MIG-002 PostgreSQL read-only source-first admissibility gate.

The probe classifies legacy rows without copying or mutating them.  It reads
source content only long enough to calculate an in-process SHA-256 comparison;
the report contains counts and classifications, never IDs, content, DSNs or
credentials.  Chunks and embeddings are explicitly non-admissible for direct
copy even when their legacy columns are populated.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "MIG-002"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "MIG-002-SOURCE-FIRST-MIGRATION-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-002-source-first-v1.json"


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("MIG-002 contract task mismatch")
    if payload.get("authority") != "PostgreSQL" or payload.get("sqlite") != "forbidden_for_acceptance":
        raise AssertionError("MIG-002 PostgreSQL-only authority is missing")
    if payload.get("automatic_direct_copy") is not False:
        raise AssertionError("MIG-002 must disable automatic direct copy")
    for layer in ("source_document_policy", "chunk_policy", "embedding_policy"):
        if not isinstance(payload.get(layer), dict):
            raise AssertionError(f"MIG-002 missing {layer}")
    if payload["chunk_policy"].get("direct_copy") != "forbidden":
        raise AssertionError("MIG-002 chunk direct copy must be forbidden")
    if payload["embedding_policy"].get("direct_copy") != "forbidden":
        raise AssertionError("MIG-002 embedding direct copy must be forbidden")
    return payload


def _classify_documents(conn) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT tenant_id, source, original_content, normalized_content, content_hash, status, exclude_from_rag "
        "FROM ai_document"
    ).fetchall()
    result = {
        "total": len(rows),
        "original_content_present": 0,
        "source_provenance_present": 0,
        "declared_hash_present": 0,
        "original_hash_match": 0,
        "normalized_hash_match": 0,
        "active": 0,
        "excluded_from_rag": 0,
        "trusted_source_candidates": 0,
        "conditional_reconciliation_required": 0,
        "untrusted_or_quarantined": 0,
    }
    for row in rows:
        tenant_id = str(row[0] or "").strip()
        source = str(row[1] or "").strip()
        original = str(row[2] or "")
        normalized = str(row[3] or "")
        declared_hash = str(row[4] or "").strip().lower()
        status = str(row[5] or "").strip().lower()
        excluded = bool(int(row[6] or 0))
        original_present = bool(original.strip())
        source_present = bool(source)
        hash_present = len(declared_hash) == 64
        original_match = hash_present and hashlib.sha256(original.encode("utf-8")).hexdigest() == declared_hash
        normalized_match = hash_present and bool(normalized) and hashlib.sha256(normalized.encode("utf-8")).hexdigest() == declared_hash
        result["original_content_present"] += int(original_present)
        result["source_provenance_present"] += int(source_present)
        result["declared_hash_present"] += int(hash_present)
        result["original_hash_match"] += int(original_match)
        result["normalized_hash_match"] += int(normalized_match)
        result["active"] += int(status == "active")
        result["excluded_from_rag"] += int(excluded)
        trusted = original_present and source_present and original_match and bool(tenant_id) and status == "active" and not excluded
        conditional = original_present and source_present and not trusted and not excluded
        result["trusted_source_candidates"] += int(trusted)
        result["conditional_reconciliation_required"] += int(conditional)
        result["untrusted_or_quarantined"] += int(not original_present or not source_present or excluded)
    return result


def _classify_derivatives(conn) -> dict[str, Any]:
    row = conn.execute(
        "SELECT COUNT(*), "
        "COUNT(*) FILTER (WHERE COALESCE(raw_content, '') <> ''), "
        "COUNT(*) FILTER (WHERE COALESCE(content_hash, '') <> ''), "
        "COUNT(*) FILTER (WHERE COALESCE(embedding, '') <> ''), "
        "COUNT(*) FILTER (WHERE embedding_vector IS NOT NULL), "
        "COUNT(*) FILTER (WHERE COALESCE(embedding_dimensions, 0) > 0), "
        "COUNT(*) FILTER (WHERE COALESCE(is_retrieval_candidate, 0) = 1) "
        "FROM ai_document_chunk"
    ).fetchone()
    return {
        "total_chunks": int(row[0]),
        "raw_content_present": int(row[1]),
        "chunk_hash_present": int(row[2]),
        "legacy_embedding_text_present": int(row[3]),
        "pgvector_value_present": int(row[4]),
        "embedding_dimension_present": int(row[5]),
        "retrieval_candidates": int(row[6]),
        "direct_chunk_copy_allowed": False,
        "direct_embedding_copy_allowed": False,
        "required_action": "rebuild_from_trusted_document_version",
    }


def postgres_probe() -> dict[str, Any]:
    from database import core

    if not core._USE_PG:
        raise RuntimeError("MIG-002 requires PostgreSQL; SQLite is forbidden")
    conn = core.get_db_connection()
    try:
        conn.execute("BEGIN READ ONLY")
        read_only = str(conn.execute("SHOW transaction_read_only").fetchone()[0]).lower() == "on"
        documents = _classify_documents(conn)
        derivatives = _classify_derivatives(conn)
        legacy_tables = {
            name: bool(
                conn.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?",
                    (name,),
                ).fetchone()
            )
            for name in ("ai_document", "ai_document_chunk")
        }
        conn.rollback()
    finally:
        conn.close()
    return {
        "status": "PASS" if read_only and all(legacy_tables.values()) else "FAIL",
        "database": "PostgreSQL",
        "transaction_read_only": read_only,
        "legacy_tables": legacy_tables,
        "documents": documents,
        "derivatives": derivatives,
        "production_database_write": False,
        "rollback": "read_only_transaction_rollback",
        "sqlite": "forbidden",
    }


def run_gate() -> dict[str, Any]:
    started = time.perf_counter()
    contract = load_contract()
    probe = postgres_probe()
    return {
        "status": "PASS" if probe["status"] == "PASS" else "FAIL",
        "task_id": TASK_ID,
        "authority": "PostgreSQL",
        "sqlite": "forbidden",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "source_first": True,
        "automatic_direct_copy": False,
        "probe": probe,
        "classification": {
            "trusted_documents_only_after_hash_manifest": True,
            "conditional_documents_require_reconciliation": True,
            "chunks_direct_migration": "forbidden",
            "embeddings_direct_migration": "forbidden",
        },
        "rollback": "v1_adapter_or_previous_ready_generation",
        "report_redacted": True,
        "contract_sha256": hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
        "contract_layers": sorted(contract),
    }


def main() -> int:
    try:
        report = run_gate()
    except Exception as exc:
        report = {"status": "ERROR", "task_id": TASK_ID, "error_type": type(exc).__name__}
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
