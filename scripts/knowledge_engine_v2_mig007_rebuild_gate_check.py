"""MIG-007 PostgreSQL-only gate for the derived-data rebuild wave.

This gate plans the V2 rebuild but deliberately does not call a provider or
write a job/document/chunk row.  The current MIG-006 manifest has no verified
documents, so processing it would violate source-first migration policy.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "MIG-007"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "MIG-007-REBUILD-GATE-CONTRACT.yaml"
INPUT_MANIFEST_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-006-official-entity-validation-manifest-v1.json"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-007-rebuild-gate-report-v1.json"
PLAN_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-007-rebuild-plan-v1.json"
PHASE_ORDER = ("parsed", "normalized", "classified", "chunked", "embedded", "indexed", "validated", "committed", "completed")
ALLOWED_GRADES = {"verified", "needs_validation", "unusable"}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: str | bytes) -> str:
    payload = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("MIG-007 contract task mismatch")
    if payload.get("authority") != "PostgreSQL" or payload.get("sqlite") != "forbidden_for_acceptance":
        raise AssertionError("MIG-007 PostgreSQL-only authority is missing")
    if payload.get("production_database_write") is not False:
        raise AssertionError("MIG-007 gate must not write production data")
    if tuple(payload.get("phase_order") or ()) != PHASE_ORDER:
        raise AssertionError("MIG-007 phase order drift")
    return payload


def validate_manifest_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("task_id") != "MIG-006":
        raise AssertionError("MIG-007 requires a MIG-006 manifest")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise AssertionError("MIG-006 manifest entries are missing")
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise AssertionError("MIG-006 manifest entry is not an object")
        legacy_id, tenant_hash = _text(entry.get("legacy_id")), _text(entry.get("tenant_id_hash"))
        grade = _text(entry.get("validation_grade"))
        if not legacy_id or len(tenant_hash) != 64 or grade not in ALLOWED_GRADES:
            raise AssertionError("MIG-006 manifest entry identity or grade is invalid")
        key = (tenant_hash, legacy_id)
        if key in seen:
            raise AssertionError("MIG-006 manifest has duplicate tenant-scoped identity")
        seen.add(key)
    return payload


def load_manifest() -> dict[str, Any]:
    return validate_manifest_payload(json.loads(INPUT_MANIFEST_PATH.read_text(encoding="utf-8")))


def build_rebuild_plan(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    safe_entries = list(entries)
    eligible = [entry for entry in safe_entries if _text(entry.get("validation_grade")) == "verified"]
    skipped = [entry for entry in safe_entries if _text(entry.get("validation_grade")) != "verified"]
    plan_entries = [
        {
            "legacy_id": _text(entry.get("legacy_id")),
            "tenant_id_hash": _text(entry.get("tenant_id_hash")),
            "metadata_hash": _text(entry.get("metadata_hash")),
            "validation_grade": "verified",
            "phases": list(PHASE_ORDER),
        }
        for entry in eligible
    ]
    status = "READY" if eligible else "BLOCKED"
    return {
        "status": status,
        "blocked_reason": None if eligible else "BLOCKED_NO_VERIFIED_SOURCE_ENTITIES",
        "total_manifest_rows": len(safe_entries),
        "eligible_rows": len(eligible),
        "skipped_rows": len(skipped),
        "phase_order": list(PHASE_ORDER),
        "entries": plan_entries,
        "provider_calls": 0,
        "production_database_write": False,
        "rollback": "stop_rebuild_worker_and_route_reads_to_v1_projection",
    }


def _table_columns(conn: Any, table: str) -> set[str]:
    rows = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? ORDER BY ordinal_position", (table,)).fetchall()
    return {str(row[0]) for row in rows}


def _postgres_probe(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    from database import core

    if not core._USE_PG:
        raise RuntimeError("MIG-007 requires PostgreSQL; SQLite is forbidden")
    conn = core.get_db_connection()
    try:
        conn.execute("BEGIN READ ONLY")
        read_only = _text(conn.execute("SHOW transaction_read_only").fetchone()[0]).casefold() == "on"
        doc_columns = _table_columns(conn, "ai_document")
        chunk_columns = _table_columns(conn, "ai_document_chunk")
        doc_count = int(conn.execute("SELECT COUNT(*) FROM ai_document").fetchone()[0])
        chunk_count = int(conn.execute("SELECT COUNT(*) FROM ai_document_chunk").fetchone()[0])
        plan = build_rebuild_plan(manifest.get("entries") or [])
        conn.rollback()
    finally:
        conn.close()
    probe = {
        "status": "PASS" if read_only else "FAIL",
        "database": "PostgreSQL",
        "transaction_read_only": read_only,
        "legacy_document_rows": doc_count,
        "legacy_chunk_rows": chunk_count,
        "required_document_columns_present": {field: field in doc_columns for field in ("original_content", "normalized_content", "metadata_json", "content_hash")},
        "required_chunk_columns_present": {field: field in chunk_columns for field in ("content", "content_hash", "embedding", "embedding_model", "embedding_dimensions", "index_version")},
        "provider_calls": int(plan["provider_calls"]),
        "production_database_write": False,
        "rollback": "read_only_transaction_rollback",
        "sqlite": "forbidden",
    }
    return probe, plan


def run_gate() -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    contract = load_contract()
    manifest = load_manifest()
    probe, plan = _postgres_probe(manifest)
    plan["manifest_entry_digest"] = _sha256(_canonical_json(manifest.get("entries") or []))
    plan["contract_sha256"] = _sha256(CONTRACT_PATH.read_text(encoding="utf-8"))
    report = {
        "status": "PASS" if probe["status"] == "PASS" and plan["production_database_write"] is False else "FAIL",
        "task_id": TASK_ID,
        "authority": "PostgreSQL",
        "sqlite": "forbidden",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "probe": probe,
        "plan_status": plan["status"],
        "blocked_reason": plan["blocked_reason"],
        "counts": {key: plan[key] for key in ("total_manifest_rows", "eligible_rows", "skipped_rows", "provider_calls")},
        "phase_order": list(PHASE_ORDER),
        "manifest_entry_digest": plan["manifest_entry_digest"],
        "production_database_write": False,
        "external_provider_request": False,
        "report_redacted": True,
        "rollback": "stop_rebuild_worker_and_route_reads_to_v1_projection",
        "contract_layers": sorted(contract),
    }
    return report, plan


def main() -> int:
    try:
        report, plan = run_gate()
    except Exception as exc:
        report = {"status": "ERROR", "task_id": TASK_ID, "error_type": type(exc).__name__}
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    # The gate itself passes; a blocked plan is an intentional, auditable
    # outcome and must not be confused with a successful rebuild.
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
