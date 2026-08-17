"""MIG-005 PostgreSQL read-only metadata confidence grading gate."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "MIG-005"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "MIG-005-METADATA-CONFIDENCE-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-005-metadata-confidence-report-v1.json"
MANIFEST_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-005-metadata-confidence-manifest-v1.json"
MANIFEST_VERSION = "nexora-knowledge-engine-v2-metadata-confidence-manifest/v1"
REQUIRED_FIELDS = ("schema_version", "document_id", "title", "vendor", "product_type", "document_category", "source_type", "official_only", "status")
ALLOWED_CATEGORIES = {"hardware", "command", "configuration", "cli_output", "troubleshooting", "example", "release_note", "reference", "guide", "sop", "product", "other"}
ALLOWED_LIFECYCLE = {"draft", "active", "published", "quarantined", "superseded", "disabled", "archived", "deprecated"}
ALLOWED_TRUST = {"official", "reviewed", "internal"}
UNKNOWN_TOKENS = {"unknown", "n/a", "na", "none", "null", "unset", "-", "未知", "未指定", "不明"}
APPLICABILITY_FIELDS = {"product_family", "product_series", "product_model", "os_family", "os_generation", "software_train", "software_release", "cli_platform"}
SERVER_OWNED_KEYS = {"tenant_id", "workspace_id", "user_id", "created_by", "updated_by", "acl", "acl_json", "permissions", "roles", "authorization", "api_key", "password", "secret", "token", "private_key", "raw_content", "original_content", "content", "body"}
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SECRET_RE = re.compile(r"(?i)(?:sk-[a-z0-9]{16,}|bearer\s+[a-z0-9._-]{12,}|akia[0-9a-z]{16}|-----begin\s+[^\n]+private key-----)")
INSTRUCTION_RE = re.compile(r"(?i)(?:ignore\s+(?:all\s+)?previous|system\s+prompt|tool\s+call|execute\s+(?:this\s+)?command|override\s+policy)")


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("MIG-005 contract task mismatch")
    if payload.get("authority") != "PostgreSQL" or payload.get("sqlite") != "forbidden_for_acceptance":
        raise AssertionError("MIG-005 PostgreSQL-only authority is missing")
    if payload.get("production_database_write") is not False:
        raise AssertionError("MIG-005 must not write production data")
    grades = payload.get("grades") or {}
    if set(grades) != {"trusted", "needs_validation", "unusable"}:
        raise AssertionError("MIG-005 must define exactly three grades")
    return payload


def _text(value: Any) -> str:
    return str(value or "").strip()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _walk(value: Any, *, keys: list[str], texts: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append(str(key).lower())
            _walk(child, keys=keys, texts=texts)
    elif isinstance(value, list):
        for child in value:
            _walk(child, keys=keys, texts=texts)
    elif isinstance(value, str):
        texts.append(value)


def _parse_metadata(raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    if isinstance(raw, dict):
        return raw, []
    if raw is None:
        return None, ["metadata_missing"]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None, ["metadata_invalid_json"]
        if isinstance(parsed, dict):
            return parsed, []
    return None, ["metadata_not_object"]


def classify_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    metadata, reasons = _parse_metadata(row.get("metadata_json"))
    if metadata is None:
        return {"grade": "unusable", "metadata_hash": "", "reason_codes": sorted(set(reasons)), "action": "quarantine_and_exclude"}
    canonical = _canonical_json(metadata)
    metadata_hash = hashlib.sha256(canonical).hexdigest()
    if len(canonical) > 65536:
        reasons.append("metadata_oversized")
    keys: list[str] = []
    texts: list[str] = []
    _walk(metadata, keys=keys, texts=texts)
    if any(key in SERVER_OWNED_KEYS for key in keys):
        reasons.append("server_owned_key")
    if any(SECRET_RE.search(text) for text in texts):
        reasons.append("secret_shaped_value")
    if any(INSTRUCTION_RE.search(text) for text in texts):
        reasons.append("instruction_like_value")
    if any(not KEY_RE.fullmatch(key) for key in keys):
        reasons.append("metadata_key_invalid")
    missing = [field for field in REQUIRED_FIELDS if field not in metadata]
    if missing:
        reasons.append("required_field_missing")
    for field in APPLICABILITY_FIELDS:
        value = metadata.get(field)
        if isinstance(value, str) and value.strip().lower() in UNKNOWN_TOKENS:
            reasons.append("unknown_applicability")
    official_only = metadata.get("official_only")
    if not isinstance(official_only, bool):
        reasons.append("official_only_type_invalid")
    category = _text(metadata.get("document_category")).lower()
    if category and category not in ALLOWED_CATEGORIES and category not in UNKNOWN_TOKENS:
        reasons.append("document_category_invalid")
    lifecycle = _text(metadata.get("status")).lower()
    if lifecycle and lifecycle not in ALLOWED_LIFECYCLE and lifecycle not in UNKNOWN_TOKENS:
        reasons.append("metadata_status_invalid")
    priority = metadata.get("rag_priority")
    if priority is not None and (isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 100):
        reasons.append("rag_priority_invalid")
    parse_status = _text(row.get("metadata_parse_status")).lower()
    parse_error = _text(row.get("metadata_parse_error"))
    if parse_status not in {"parsed", "validated", "verified"}:
        reasons.append("metadata_parse_status_unverified")
    if parse_error:
        reasons.append("metadata_parse_error_present")
    source_trust = _text(row.get("source_trust_level")).lower()
    if source_trust not in ALLOWED_TRUST:
        reasons.append("source_trust_unallowlisted")
    row_status = _text(row.get("status")).lower()
    if row_status != "active" or bool(int(row.get("exclude_from_rag") or 0)):
        reasons.append("lifecycle_not_active")
    reasons = sorted(set(reasons))
    security_reasons = {"server_owned_key", "secret_shaped_value", "instruction_like_value", "metadata_invalid_json", "metadata_not_object", "metadata_oversized", "metadata_parse_error_present"}
    if security_reasons.intersection(reasons):
        grade = "unusable"
        action = "quarantine_and_exclude"
    elif reasons:
        grade = "needs_validation"
        action = "review_and_reconcile_before_migration"
    else:
        grade = "trusted"
        action = "eligible_for_metadata_reconciliation_wave"
    return {"grade": grade, "metadata_hash": metadata_hash, "reason_codes": reasons, "action": action}


def build_manifest_entries(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int], str]:
    entries: list[dict[str, Any]] = []
    counts = {"legacy_documents": 0, "trusted": 0, "needs_validation": 0, "unusable": 0, "metadata_hashes": 0}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        tenant = _text(row.get("tenant_id"))
        legacy_id = _text(row.get("id"))
        document_id = _text(row.get("document_id"))
        if not tenant or not legacy_id or not document_id or (tenant, legacy_id) in seen:
            raise ValueError("MIG-005 tenant-scoped legacy identity is missing or duplicated")
        seen.add((tenant, legacy_id))
        classification = classify_metadata(row)
        entry = {
            "legacy_id": legacy_id,
            "legacy_document_id": document_id,
            "tenant_id_hash": _sha256_text(tenant),
            "grade": classification["grade"],
            "metadata_hash": classification["metadata_hash"],
            "parse_status": _text(row.get("metadata_parse_status")).lower() or "missing",
            "reason_codes": classification["reason_codes"],
            "action": classification["action"],
        }
        entries.append(entry)
        counts["legacy_documents"] += 1
        counts[classification["grade"]] += 1
        counts["metadata_hashes"] += int(bool(classification["metadata_hash"]))
    entries.sort(key=lambda item: (item["tenant_id_hash"], item["legacy_id"]))
    digest_input = _canonical_json(entries)
    return entries, counts, hashlib.sha256(digest_input).hexdigest()


def _postgres_probe() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int], str]:
    from database import core

    if not core._USE_PG:
        raise RuntimeError("MIG-005 requires PostgreSQL; SQLite is forbidden")
    conn = core.get_db_connection()
    try:
        conn.execute("BEGIN READ ONLY")
        read_only = _text(conn.execute("SHOW transaction_read_only").fetchone()[0]).lower() == "on"
        rows = [
            {
                "id": row[0], "tenant_id": row[1], "document_id": row[2], "metadata_json": row[3],
                "metadata_parse_status": row[4], "metadata_parse_error": row[5], "status": row[6],
                "exclude_from_rag": row[7], "source_trust_level": row[8],
            }
            for row in conn.execute(
                "SELECT id, tenant_id, document_id, metadata_json, metadata_parse_status, metadata_parse_error, status, exclude_from_rag, source_trust_level "
                "FROM ai_document ORDER BY tenant_id, id"
            ).fetchall()
        ]
        entries, counts, entry_digest = build_manifest_entries(rows)
        conn.rollback()
    finally:
        conn.close()
    probe = {
        "status": "PASS" if read_only else "FAIL",
        "database": "PostgreSQL",
        "transaction_read_only": read_only,
        "legacy_document_rows": len(rows),
        "production_database_write": False,
        "rollback": "read_only_transaction_rollback",
        "sqlite": "forbidden",
    }
    return probe, entries, counts, entry_digest


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    body = {key: value for key, value in manifest.items() if key not in {"generated_at", "manifest_sha256"}}
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def run_gate() -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    contract = load_contract()
    probe, entries, counts, entry_digest = _postgres_probe()
    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "task_id": TASK_ID,
        "source_authority": "PostgreSQL",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entries": entries,
        "counts": counts,
        "entry_digest": entry_digest,
        "redaction": {"raw_metadata": "omitted", "original_content": "omitted", "normalized_content": "omitted", "acl": "omitted", "secrets": "omitted", "database_url": "omitted"},
    }
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    report = {
        "status": "PASS" if probe["status"] == "PASS" and len(entries) == counts["legacy_documents"] else "FAIL",
        "task_id": TASK_ID,
        "authority": "PostgreSQL",
        "sqlite": "forbidden",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "manifest_version": MANIFEST_VERSION,
        "manifest_sha256": manifest["manifest_sha256"],
        "entry_digest": entry_digest,
        "counts": counts,
        "probe": probe,
        "grades": {"trusted": "safe_complete_metadata", "needs_validation": "review_before_migration", "unusable": "quarantine_exclude"},
        "production_database_write": False,
        "rollback": "retain_original_metadata_and_disable_typed_projection",
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
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
