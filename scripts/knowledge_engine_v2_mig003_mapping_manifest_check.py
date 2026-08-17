"""MIG-003 PostgreSQL read-only legacy-to-V2 mapping and manifest gate.

The generated manifest is an offline review artifact.  It never inserts V2
rows and never copies source/metadata/chunk/embedding bodies.  Mapping IDs are
stable UUID5 values so a later dry-run can join legacy rows without creating a
second identity for the same tenant-scoped legacy key.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "MIG-003"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "MIG-003-ID-MAPPING-MANIFEST-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-003-migration-manifest-v1.json"
MANIFEST_VERSION = "nexora-knowledge-engine-v2-migration-manifest/v1"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://nexora.invalid/knowledge-engine-v2/mig003/v1")
DOC_NAMESPACE = uuid.uuid5(NAMESPACE, "document")
VERSION_NAMESPACE = uuid.uuid5(NAMESPACE, "document-version")


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("MIG-003 contract task mismatch")
    if payload.get("authority") != "PostgreSQL" or payload.get("sqlite") != "forbidden_for_acceptance":
        raise AssertionError("MIG-003 PostgreSQL-only authority is missing")
    if payload.get("production_database_write") is not False:
        raise AssertionError("MIG-003 must not write the production database")
    identity = payload.get("identity") or {}
    if identity.get("legacy_key") != ["ai_document.tenant_id", "ai_document.id"]:
        raise AssertionError("MIG-003 legacy identity key changed")
    manifest = payload.get("manifest") or {}
    if manifest.get("format") != MANIFEST_VERSION or manifest.get("digest_rule") is None:
        raise AssertionError("MIG-003 manifest contract is incomplete")
    return payload


def _text(value: Any) -> str:
    return str(value or "").strip()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def deterministic_ids(tenant_id: str, legacy_id: str, declared_hash: str = "") -> tuple[str, str]:
    """Return stable V2 IDs; no database state or random UUID is consulted."""
    tenant = _text(tenant_id)
    old_id = _text(legacy_id)
    if not tenant or not old_id:
        raise ValueError("tenant_id and legacy_id are required")
    key = f"{tenant}\x00{old_id}"
    document_id = str(uuid.uuid5(DOC_NAMESPACE, key))
    version_key = f"{key}\x00{_text(declared_hash).lower() or 'pending'}"
    version_id = str(uuid.uuid5(VERSION_NAMESPACE, version_key))
    return document_id, version_id


def _admissibility(row: Mapping[str, Any]) -> tuple[str, list[str], bool, bool]:
    tenant = _text(row.get("tenant_id"))
    source = _text(row.get("source"))
    original = str(row.get("original_content") or "")
    normalized = str(row.get("normalized_content") or "")
    declared_hash = _text(row.get("content_hash")).lower()
    status = _text(row.get("status")).lower()
    excluded = bool(int(row.get("exclude_from_rag") or 0))
    original_present = bool(original.strip())
    source_present = bool(source)
    hash_present = len(declared_hash) == 64
    original_match = hash_present and _sha256(original) == declared_hash
    normalized_match = hash_present and bool(normalized) and _sha256(normalized) == declared_hash
    actions: list[str] = []
    if not source_present:
        actions.append("reconcile_source_provenance")
    if not hash_present or not original_match:
        actions.append("reconcile_original_content_hash")
    if status != "active" or excluded:
        actions.append("review_lifecycle_or_exclusion")
    if original_present and source_present and original_match and tenant and status == "active" and not excluded:
        return "trusted", actions, original_match, normalized_match
    if original_present and source_present and not excluded:
        return "conditional_reconciliation", actions, original_match, normalized_match
    return "untrusted_or_quarantined", actions, original_match, normalized_match


def build_entries(rows: Iterable[Mapping[str, Any]], source_registry_keys: set[tuple[str, str]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    entries: list[dict[str, Any]] = []
    seen_legacy: set[tuple[str, str]] = set()
    seen_v2: set[str] = set()
    counts = {
        "legacy_documents": 0,
        "trusted": 0,
        "conditional_reconciliation": 0,
        "untrusted_or_quarantined": 0,
        "source_registry_resolved": 0,
        "source_registry_unresolved": 0,
        "v2_id_collisions": 0,
    }
    for row in rows:
        tenant = _text(row.get("tenant_id"))
        legacy_id = _text(row.get("id"))
        old_document_id = _text(row.get("document_id"))
        if not tenant or not legacy_id or not old_document_id:
            raise ValueError("MIG-003 requires tenant-scoped legacy id and document_id")
        legacy_key = (tenant, legacy_id)
        if legacy_key in seen_legacy:
            raise ValueError("duplicate tenant-scoped legacy key")
        seen_legacy.add(legacy_key)
        declared_hash = _text(row.get("content_hash")).lower()
        v2_document_id, v2_version_id = deterministic_ids(tenant, legacy_id, declared_hash)
        if v2_document_id in seen_v2:
            counts["v2_id_collisions"] += 1
            raise ValueError("deterministic V2 document ID collision")
        seen_v2.add(v2_document_id)
        admissibility, actions, original_match, normalized_match = _admissibility(row)
        registry_resolved = (tenant, _text(row.get("source"))) in source_registry_keys
        if registry_resolved:
            counts["source_registry_resolved"] += 1
        else:
            counts["source_registry_unresolved"] += 1
            if "reconcile_source_registry" not in actions:
                actions.append("reconcile_source_registry")
        counts[admissibility] += 1
        counts["legacy_documents"] += 1
        entries.append(
            {
                "legacy_table": "ai_document",
                "legacy_id": legacy_id,
                "legacy_document_id": old_document_id,
                "tenant_id_hash": _sha256(tenant),
                "v2_document_id": v2_document_id,
                "v2_document_version_id": v2_version_id,
                "admissibility": admissibility,
                "source_registry_resolution": "resolved" if registry_resolved else "unresolved",
                "source_provenance_hash": _sha256(_text(row.get("source"))) if _text(row.get("source")) else "",
                "declared_content_hash": declared_hash if len(declared_hash) == 64 else "",
                "original_hash_match": bool(original_match),
                "normalized_hash_match": bool(normalized_match),
                "actions": sorted(set(actions)),
            }
        )
    entries.sort(key=lambda item: (item["tenant_id_hash"], item["legacy_id"]))
    return entries, counts


def _canonical_manifest_body(manifest: Mapping[str, Any]) -> bytes:
    body = {key: value for key, value in manifest.items() if key not in {"generated_at", "manifest_sha256"}}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_only_probe() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    from database import core

    if not core._USE_PG:
        raise RuntimeError("MIG-003 requires PostgreSQL; SQLite is forbidden")
    conn = core.get_db_connection()
    try:
        conn.execute("BEGIN READ ONLY")
        read_only = _text(conn.execute("SHOW transaction_read_only").fetchone()[0]).lower() == "on"
        legacy_exists = bool(conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='ai_document'").fetchone())
        if not legacy_exists:
            raise RuntimeError("ai_document table is missing")
        rows = [
            {
                "id": row[0], "tenant_id": row[1], "document_id": row[2], "source": row[3],
                "content_hash": row[4], "original_content": row[5], "normalized_content": row[6],
                "status": row[7], "exclude_from_rag": row[8],
            }
            for row in conn.execute(
                "SELECT id, tenant_id, document_id, source, content_hash, original_content, normalized_content, status, exclude_from_rag "
                "FROM ai_document ORDER BY tenant_id, id"
            ).fetchall()
        ]
        source_registry_keys = {
            (_text(row[0]), _text(row[1]))
            for row in conn.execute("SELECT tenant_id, id FROM kb_source_registry").fetchall()
        }
        entries, counts = build_entries(rows, source_registry_keys)
        conn.rollback()
    finally:
        conn.close()
    probe = {
        "status": "PASS" if read_only else "FAIL",
        "database": "PostgreSQL",
        "transaction_read_only": read_only,
        "legacy_document_rows": len(rows),
        "source_registry_rows": len(source_registry_keys),
        "production_database_write": False,
        "rollback": "read_only_transaction_rollback",
        "sqlite": "forbidden",
    }
    return probe, entries, counts


def run_gate() -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    contract = load_contract()
    probe, entries, counts = _read_only_probe()
    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "task_id": TASK_ID,
        "source_authority": "PostgreSQL",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entries": entries,
        "counts": counts,
        "redaction": {
            "raw_content": "omitted",
            "metadata": "omitted",
            "acl": "omitted",
            "secrets": "omitted",
            "database_url": "omitted",
        },
    }
    manifest["manifest_sha256"] = hashlib.sha256(_canonical_manifest_body(manifest)).hexdigest()
    report = {
        "status": "PASS" if probe["status"] == "PASS" and len(entries) == counts["legacy_documents"] and counts["v2_id_collisions"] == 0 else "FAIL",
        "task_id": TASK_ID,
        "authority": "PostgreSQL",
        "sqlite": "forbidden",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "manifest_version": MANIFEST_VERSION,
        "manifest_sha256": manifest["manifest_sha256"],
        "mapping_entries": len(entries),
        "counts": counts,
        "probe": probe,
        "mapping_strategy": "deterministic_uuid5_tenant_scoped_legacy_key",
        "production_database_write": False,
        "rollback": "discard_artifact_without_target_mutation",
        "report_redacted": True,
        "contract_sha256": hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
        "contract_layers": sorted(contract),
    }
    return report, manifest


def main() -> int:
    try:
        report, manifest = run_gate()
    except Exception as exc:
        report = {"status": "ERROR", "task_id": TASK_ID, "error_type": type(exc).__name__}
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1
    REPORT_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path = REPORT_PATH.with_name("mig-003-migration-report-v1.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
