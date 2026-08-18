"""MIG-008 PostgreSQL-only migration consistency and permission audit."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "MIG-008"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "MIG-008-CONSISTENCY-AUDIT-CONTRACT.yaml"
MIG006_MANIFEST_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-006-official-entity-validation-manifest-v1.json"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-008-consistency-audit-report-v1.json"
MANIFEST_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-008-consistency-audit-manifest-v1.json"
FORBIDDEN_CHUNK_METADATA_KEYS = {"tenant_id", "workspace_id", "user_id", "created_by", "updated_by", "acl", "acl_json", "permissions", "roles", "authorization", "api_key", "password", "secret", "token", "private_key"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: str | bytes) -> str:
    payload = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_object(value: Any) -> tuple[dict[str, Any] | None, bool]:
    if isinstance(value, dict):
        return value, True
    if value is None or value == "":
        return {}, True
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return None, False
    return (decoded, isinstance(decoded, dict))


def _metadata_keys(value: Any) -> set[str]:
    decoded, valid = _json_object(value)
    return {str(key).casefold() for key in decoded} if valid and decoded else set()


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("MIG-008 contract task mismatch")
    if payload.get("authority") != "PostgreSQL" or payload.get("sqlite") != "forbidden_for_acceptance":
        raise AssertionError("MIG-008 PostgreSQL-only authority is missing")
    if payload.get("production_database_write") is not False:
        raise AssertionError("MIG-008 audit must not write production data")
    return payload


def load_expected_document_count() -> int:
    payload = json.loads(MIG006_MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise AssertionError("MIG-008 requires MIG-006 manifest entries")
    return len(entries)


def audit_rows(documents: Iterable[Mapping[str, Any]], chunks: Iterable[Mapping[str, Any]], *, expected_documents: int) -> dict[str, Any]:
    docs = list(documents)
    chunk_rows = list(chunks)
    doc_by_id = {_text(row.get("id")): row for row in docs if _text(row.get("id"))}
    counts: Counter[str] = Counter()
    counts["documents"] = len(docs)
    counts["chunks"] = len(chunk_rows)
    counts["expected_documents"] = int(expected_documents)
    if len(docs) != expected_documents:
        counts["document_count_mismatch"] = 1
    if len(doc_by_id) != len(docs):
        counts["document_id_duplicate"] = len(docs) - len(doc_by_id)
    for row in docs:
        if not _text(row.get("tenant_id")):
            counts["document_tenant_missing"] += 1
        declared_hash = _text(row.get("content_hash"))
        normalized = row.get("normalized_content")
        if not declared_hash or normalized in (None, ""):
            counts["document_hash_unverifiable"] += 1
        elif _sha256(str(normalized)) != declared_hash:
            counts["document_hash_mismatch"] += 1
        _, acl_valid = _json_object(row.get("acl_json"))
        if not acl_valid:
            counts["document_acl_invalid"] += 1
    ordinal_keys: Counter[tuple[str, str]] = Counter()
    content_hash_keys: Counter[tuple[str, str]] = Counter()
    for row in chunk_rows:
        document_id = _text(row.get("document_id"))
        if document_id not in doc_by_id:
            counts["chunk_orphan"] += 1
            continue
        parent = doc_by_id[document_id]
        declared_chunk_hash = _text(row.get("content_hash"))
        if not declared_chunk_hash:
            counts["chunk_hash_unverifiable"] += 1
        ordinal_keys[(document_id, _text(row.get("ordinal")))] += 1
        if declared_chunk_hash:
            content_hash_keys[(document_id, declared_chunk_hash)] += 1
        for child_field, parent_field, counter_name in (("document_version", "document_version", "chunk_document_version_mismatch"), ("index_version", "index_version", "chunk_index_version_mismatch"), ("embedding_model", "embedding_model", "chunk_embedding_contract_mismatch"), ("embedding_dimensions", "embedding_dimensions", "chunk_embedding_contract_mismatch")):
            child_value, parent_value = _text(row.get(child_field)), _text(parent.get(parent_field))
            if child_value and parent_value and child_value != parent_value:
                counts[counter_name] += 1
        if row.get("embedding") in (None, "") or not _text(row.get("embedding_model")) or row.get("embedding_dimensions") is None:
            counts["chunk_embedding_unavailable"] += 1
        if _text(row.get("tenant_id")) and _text(row.get("tenant_id")) != _text(parent.get("tenant_id")):
            counts["chunk_tenant_inheritance_mismatch"] += 1
        if _metadata_keys(row.get("metadata_json")).intersection(FORBIDDEN_CHUNK_METADATA_KEYS):
            counts["chunk_metadata_identity_leak"] += 1
    counts["chunk_duplicate_ordinal_groups"] = sum(1 for value in ordinal_keys.values() if value > 1)
    counts["chunk_duplicate_content_hash_groups"] = sum(1 for value in content_hash_keys.values() if value > 1)
    blocking_keys = {"document_count_mismatch", "document_id_duplicate", "document_tenant_missing", "document_hash_mismatch", "document_hash_unverifiable", "chunk_orphan", "chunk_hash_unverifiable", "chunk_document_version_mismatch", "chunk_index_version_mismatch", "chunk_embedding_contract_mismatch", "document_acl_invalid", "chunk_metadata_identity_leak", "chunk_tenant_inheritance_mismatch"}
    reason_codes = sorted(key.upper() for key in blocking_keys if counts.get(key, 0))
    status = "PASS" if not reason_codes else "BLOCKED"
    safe_counts = {key: int(value) for key, value in sorted(counts.items())}
    digest = _sha256(_canonical_json({"counts": safe_counts, "reason_codes": reason_codes}))
    return {"status": status, "reason_codes": reason_codes, "counts": safe_counts, "audit_digest": digest, "report_redacted": True, "production_database_write": False, "sqlite": "forbidden"}


def _postgres_probe(expected_documents: int) -> dict[str, Any]:
    from database import core

    if not core._USE_PG:
        raise RuntimeError("MIG-008 requires PostgreSQL; SQLite is forbidden")
    conn = core.get_db_connection()
    try:
        conn.execute("BEGIN READ ONLY")
        read_only = _text(conn.execute("SHOW transaction_read_only").fetchone()[0]).casefold() == "on"
        doc_columns = {str(row[0]) for row in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='ai_document'").fetchall()}
        chunk_columns = {str(row[0]) for row in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='ai_document_chunk'").fetchall()}
        doc_fields = ["id", "tenant_id", "content_hash", "normalized_content", "document_version", "index_version", "embedding_model", "embedding_dimensions", "acl_json"]
        chunk_fields = ["id", "document_id", "tenant_id", "content_hash", "ordinal", "document_version", "index_version", "embedding_model", "embedding_dimensions", "embedding", "metadata_json"]
        selected_doc_fields = [field for field in doc_fields if field in doc_columns]
        selected_chunk_fields = [field for field in chunk_fields if field in chunk_columns]
        docs = []
        for row in conn.execute("SELECT " + ",".join(selected_doc_fields) + " FROM ai_document ORDER BY id").fetchall():
            item = dict(zip(selected_doc_fields, row))
            item.update({field: None for field in doc_fields if field not in item})
            docs.append(item)
        chunks = []
        for row in conn.execute("SELECT " + ",".join(selected_chunk_fields) + " FROM ai_document_chunk ORDER BY id").fetchall():
            item = dict(zip(selected_chunk_fields, row))
            item.update({field: None for field in chunk_fields if field not in item})
            chunks.append(item)
        audit = audit_rows(docs, chunks, expected_documents=expected_documents)
        conn.rollback()
    finally:
        conn.close()
    audit["probe"] = {"database": "PostgreSQL", "transaction_read_only": read_only, "status": "PASS" if read_only else "FAIL", "document_schema_fields_present": {field: field in doc_columns for field in doc_fields}, "chunk_schema_fields_present": {field: field in chunk_columns for field in chunk_fields}, "sqlite": "forbidden"}
    return audit


def run_gate() -> dict[str, Any]:
    started = time.perf_counter()
    contract = load_contract()
    audit = _postgres_probe(load_expected_document_count())
    report = {"status": "PASS" if audit["probe"]["status"] == "PASS" else "FAIL", "task_id": TASK_ID, "authority": "PostgreSQL", "sqlite": "forbidden", "duration_seconds": round(time.perf_counter() - started, 3), "audit_status": audit["status"], "reason_codes": audit["reason_codes"], "counts": audit["counts"], "audit_digest": audit["audit_digest"], "probe": audit["probe"], "production_database_write": False, "report_redacted": True, "rollback": "discard_local_audit_and_keep_v1_projection", "contract_sha256": _sha256(CONTRACT_PATH.read_text(encoding="utf-8")), "contract_layers": sorted(contract)}
    manifest = {"manifest_version": "nexora-knowledge-engine-v2-consistency-audit-manifest/v1", "task_id": TASK_ID, "authority": "PostgreSQL", "audit_status": audit["status"], "reason_codes": audit["reason_codes"], "counts": audit["counts"], "audit_digest": audit["audit_digest"], "redaction": {"raw_content": "omitted", "acl_values": "omitted", "credentials": "omitted", "secrets": "omitted", "dsn": "omitted", "exception_text": "omitted"}}
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    try:
        report = run_gate()
    except Exception as exc:
        report = {"status": "ERROR", "task_id": TASK_ID, "error_type": type(exc).__name__}
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
