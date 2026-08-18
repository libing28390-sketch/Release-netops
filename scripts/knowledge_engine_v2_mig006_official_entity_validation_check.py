"""MIG-006 PostgreSQL read-only official entity validation gate.

The gate validates migrated metadata against the reviewed CAT-001 scope.  It
does not fetch external URLs or mutate production tables; unresolved evidence
is deliberately reported as ``needs_validation`` rather than guessed.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "MIG-006"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "MIG-006-OFFICIAL-ENTITY-VALIDATION-CONTRACT.yaml"
ALLOWLIST_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-006-official-entity-validation-report-v1.json"
MANIFEST_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-006-official-entity-validation-manifest-v1.json"
MANIFEST_VERSION = "nexora-knowledge-engine-v2-official-entity-validation-manifest/v1"
ENTITY_FIELDS = (
    "vendor", "product_family", "product_series", "product_model", "os_family",
    "os_generation", "software_train", "software_release", "cli_platform",
)
UNKNOWN_TOKENS = {"", "unknown", "unk", "n/a", "na", "none", "null", "unset", "-", "未知", "未指定", "不明"}
SERVER_OWNED_KEYS = {"tenant_id", "workspace_id", "user_id", "created_by", "updated_by", "acl", "acl_json", "permissions", "roles", "authorization", "api_key", "password", "secret", "token", "private_key", "raw_content", "original_content", "content", "body"}
SECRET_RE = re.compile(r"(?i)(?:sk-[a-z0-9]{16,}|bearer\s+[a-z0-9._-]{12,}|akia[0-9a-z]{16}|-----begin\s+[^\n]+private key-----)")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return re.sub(r"[\s_-]+", " ", _text(value).casefold()).strip()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("MIG-006 contract task mismatch")
    if payload.get("authority") != "PostgreSQL" or payload.get("sqlite") != "forbidden_for_acceptance":
        raise AssertionError("MIG-006 PostgreSQL-only authority is missing")
    if payload.get("production_database_write") is not False:
        raise AssertionError("MIG-006 must not write production data")
    return payload


def load_allowlist() -> dict[str, Any]:
    payload = yaml.safe_load(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != "CAT-001":
        raise AssertionError("CAT-001 allowlist contract mismatch")
    entries = payload.get("vendor_entries")
    if not isinstance(entries, list) or {str(item.get("vendor_key")) for item in entries if isinstance(item, dict)} != {"huawei", "cisco"}:
        raise AssertionError("CAT-001 must define the first Huawei/Cisco scope")
    return payload


def _metadata(row: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    value = row.get("metadata_json")
    if isinstance(value, dict):
        return value, []
    if value is None:
        return {}, []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None, ["METADATA_INVALID"]
    if isinstance(value, dict):
        return value, []
    return None, ["METADATA_INVALID"]


def _walk(value: Any, *, keys: list[str], texts: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append(str(key).casefold())
            _walk(child, keys=keys, texts=texts)
    elif isinstance(value, list):
        for child in value:
            _walk(child, keys=keys, texts=texts)
    elif isinstance(value, str):
        texts.append(value)


def _scope_index(allowlist: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in allowlist.get("vendor_entries", []):
        if not isinstance(entry, dict):
            continue
        result[_norm(entry.get("vendor_key"))] = {
            "vendor": _norm(entry.get("vendor_key")),
            "family": _norm(entry.get("product_family")),
            "model_pattern": _norm(entry.get("model_pattern")),
            "platform": _norm(entry.get("platform_code")),
            "os_family": _norm(entry.get("os_family")),
            "primary_version": _norm(entry.get("primary_version")),
            "compatibility_version": _norm(entry.get("compatibility_version")),
            "aliases": {_norm(entry.get("vendor")), _norm(entry.get("vendor_key"))},
            "hosts": {str(item.get("host", "")).casefold() for item in entry.get("official_hosts", []) if isinstance(item, dict)},
            "paths": [str(prefix) for item in entry.get("official_hosts", []) if isinstance(item, dict) for prefix in item.get("path_prefixes", [])],
        }
    return result


def _value(row: Mapping[str, Any], metadata: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if value is None or not _text(value):
        value = metadata.get(field)
    return _text(value)


def _official_url_allowed(url: str, scope: Mapping[str, Any]) -> bool:
    if not url:
        return False
    parsed = urlsplit(url)
    if parsed.scheme.casefold() != "https" or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    host = (parsed.hostname or "").casefold()
    return host in scope.get("hosts", set()) and any(parsed.path.startswith(prefix) for prefix in scope.get("paths", []))


def classify_entity(row: Mapping[str, Any], allowlist: Mapping[str, Any] | None = None, *, catalog_available: bool = False) -> dict[str, Any]:
    """Classify without body inference; safe for unit fixtures and the PG gate."""
    scopes = _scope_index(allowlist or {"vendor_entries": []})
    metadata, reasons = _metadata(row)
    if metadata is None:
        return {"grade": "unusable", "reason_codes": sorted(set(reasons)), "action": "quarantine_and_exclude", "metadata_hash": ""}
    metadata_hash = hashlib.sha256(_canonical_json(metadata)).hexdigest()
    keys: list[str] = []
    texts: list[str] = []
    _walk(metadata, keys=keys, texts=texts)
    if any(key in SERVER_OWNED_KEYS for key in keys) or any(SECRET_RE.search(value) for value in texts):
        reasons.append("SECURITY_VALUE_REJECTED")
    source_id = _text(row.get("source"))
    source_status = _text(row.get("source_status")).casefold()
    source_validation = _text(row.get("source_validation_status")).casefold()
    source_url = _text(row.get("source_url"))
    vendor = _norm(_value(row, metadata, "vendor"))
    if vendor in UNKNOWN_TOKENS:
        reasons.append("VENDOR_UNKNOWN")
    elif vendor not in scopes:
        reasons.append("VENDOR_NOT_CANONICAL")
    # A contract-only allowlist is not a product catalog.  Do not call a
    # legacy value a conflict merely because the runtime has no reviewed
    # catalog snapshot; absence of that snapshot is a review condition.  Unit
    # fixtures (and a future populated catalog) explicitly opt in through
    # ``catalog_available`` before field-level scope comparisons are applied.
    scope = scopes.get(vendor) if catalog_available else None
    if not source_id or source_id.casefold() in {"upload", "manual", "local"}:
        reasons.append("SOURCE_REGISTRY_UNRESOLVED")
    elif source_status != "active" or source_validation != "valid":
        reasons.append("SOURCE_NOT_ACTIVE_OR_VALID")
    if not source_url:
        reasons.append("OFFICIAL_EVIDENCE_MISSING")
    elif scope and not _official_url_allowed(source_url, scope):
        reasons.append("OFFICIAL_EVIDENCE_MISSING")
    if scope:
        family = _norm(_value(row, metadata, "product_family"))
        model = _norm(_value(row, metadata, "product_model"))
        os_family = _norm(_value(row, metadata, "os_family"))
        platform = _norm(_value(row, metadata, "cli_platform"))
        release = _norm(_value(row, metadata, "software_release"))
        if family in UNKNOWN_TOKENS or not family:
            reasons.append("PRODUCT_UNKNOWN")
        elif family != scope["family"]:
            reasons.append("PRODUCT_NOT_CANONICAL")
        if model in UNKNOWN_TOKENS or not model:
            reasons.append("PRODUCT_UNKNOWN")
        elif scope["model_pattern"] and scope["model_pattern"].replace("xx", "") not in model.replace(" ", ""):
            reasons.append("PRODUCT_NOT_CANONICAL")
        if os_family in UNKNOWN_TOKENS or not os_family:
            reasons.append("OS_UNKNOWN")
        elif os_family != scope["os_family"]:
            reasons.append("OS_SCOPE_CONFLICT")
        if platform in UNKNOWN_TOKENS or not platform:
            reasons.append("PLATFORM_UNKNOWN")
        elif platform != scope["platform"]:
            reasons.append("PLATFORM_NOT_BOUND")
        if release in UNKNOWN_TOKENS or not release:
            reasons.append("SOFTWARE_VERSION_UNKNOWN")
        elif not (release == scope["primary_version"] or release == scope["compatibility_version"] or (scope["compatibility_version"].endswith("x") and release.startswith(scope["compatibility_version"].rstrip("x")))):
            reasons.append("SOFTWARE_VERSION_NOT_CANONICAL")
    if not catalog_available:
        reasons.append("CATALOG_SNAPSHOT_UNAVAILABLE")
    reasons = sorted(set(reasons))
    conflict_reasons = {"VENDOR_NOT_CANONICAL", "VENDOR_CONFLICT", "OS_SCOPE_CONFLICT", "SOFTWARE_VERSION_NOT_CANONICAL", "SECURITY_VALUE_REJECTED", "METADATA_INVALID"}
    if conflict_reasons.intersection(reasons):
        grade, action = "unusable", "quarantine_and_exclude"
    elif reasons:
        grade, action = "needs_validation", "review_or_source_revalidation"
    else:
        grade, action = "verified", "eligible_for_v2_migration"
    return {"grade": grade, "reason_codes": reasons, "action": action, "metadata_hash": metadata_hash}


def build_manifest_entries(rows: Iterable[Mapping[str, Any]], allowlist: Mapping[str, Any], *, catalog_available: bool = False) -> tuple[list[dict[str, Any]], dict[str, int], str]:
    entries: list[dict[str, Any]] = []
    counts = {"legacy_documents": 0, "verified": 0, "needs_validation": 0, "unusable": 0}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        tenant, legacy_id = _text(row.get("tenant_id")), _text(row.get("id"))
        if not tenant or not legacy_id or (tenant, legacy_id) in seen:
            raise ValueError("MIG-006 tenant-scoped legacy identity is missing or duplicated")
        seen.add((tenant, legacy_id))
        classification = classify_entity(row, allowlist, catalog_available=catalog_available)
        entry = {
            "legacy_id": legacy_id,
            "tenant_id_hash": _sha256(tenant),
            "metadata_hash": classification["metadata_hash"],
            "validation_grade": classification["grade"],
            "reason_codes": classification["reason_codes"],
            "action": classification["action"],
        }
        entries.append(entry)
        counts["legacy_documents"] += 1
        counts[classification["grade"]] += 1
    entries.sort(key=lambda item: (item["tenant_id_hash"], item["legacy_id"]))
    digest = hashlib.sha256(_canonical_json(entries)).hexdigest()
    return entries, counts, digest


def _table_exists(conn: Any, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?", (table,)).fetchone()
    return bool(row)


def _postgres_probe(allowlist: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int], str]:
    from database import core

    if not core._USE_PG:
        raise RuntimeError("MIG-006 requires PostgreSQL; SQLite is forbidden")
    conn = core.get_db_connection()
    try:
        conn.execute("BEGIN READ ONLY")
        read_only = _text(conn.execute("SHOW transaction_read_only").fetchone()[0]).casefold() == "on"
        catalog_tables = [table for table in ("kb_vendor", "kb_product_family", "kb_product_series", "kb_product_model", "kb_os_family", "kb_os_generation", "kb_release_train", "kb_software_version") if _table_exists(conn, table)]
        source_rows = conn.execute("SELECT id,status,validation_status,canonical_url,allowed_host FROM kb_source_registry").fetchall()
        source_map = {row[0]: {"source_status": row[1], "source_validation_status": row[2], "source_url": row[3], "allowed_host": row[4]} for row in source_rows}
        rows: list[dict[str, Any]] = []
        for row in conn.execute("SELECT id,tenant_id,source,vendor,platform,version,status,metadata_json,product_family,product_series,product_model,os_family,os_generation,software_train,software_release,cli_platform FROM ai_document ORDER BY tenant_id,id").fetchall():
            source = source_map.get(row[2], {})
            rows.append({"id": row[0], "tenant_id": row[1], "source": row[2], "vendor": row[3], "cli_platform": row[4], "software_release": row[5], "status": row[6], "metadata_json": row[7], "product_family": row[8], "product_series": row[9], "product_model": row[10], "os_family": row[11], "os_generation": row[12], "software_train": row[13], "source_status": source.get("source_status"), "source_validation_status": source.get("source_validation_status"), "source_url": source.get("source_url")})
        entries, counts, digest = build_manifest_entries(rows, allowlist, catalog_available=bool(catalog_tables))
        conn.rollback()
    finally:
        conn.close()
    probe = {"status": "PASS" if read_only else "FAIL", "database": "PostgreSQL", "transaction_read_only": read_only, "legacy_document_rows": len(rows), "catalog_tables_present": catalog_tables, "source_registry_rows": len(source_rows), "production_database_write": False, "rollback": "read_only_transaction_rollback", "sqlite": "forbidden"}
    return probe, entries, counts, digest


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    body = {key: value for key, value in manifest.items() if key not in {"generated_at", "manifest_sha256"}}
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def run_gate() -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    contract, allowlist = load_contract(), load_allowlist()
    probe, entries, counts, digest = _postgres_probe(allowlist)
    manifest: dict[str, Any] = {"manifest_version": MANIFEST_VERSION, "task_id": TASK_ID, "source_authority": "PostgreSQL", "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "entries": entries, "counts": counts, "entry_digest": digest, "redaction": {"raw_metadata": "omitted", "original_content": "omitted", "normalized_content": "omitted", "source_url": "omitted", "acl": "omitted", "secrets": "omitted", "database_url": "omitted"}}
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    report = {"status": "PASS" if probe["status"] == "PASS" and len(entries) == counts["legacy_documents"] else "FAIL", "task_id": TASK_ID, "authority": "PostgreSQL", "sqlite": "forbidden", "duration_seconds": round(time.perf_counter() - started, 3), "manifest_version": MANIFEST_VERSION, "manifest_sha256": manifest["manifest_sha256"], "entry_digest": digest, "counts": counts, "probe": probe, "decision": {"verified": "eligible_for_v2_migration", "needs_validation": "review_or_source_revalidation", "unusable": "quarantine_and_exclude"}, "production_database_write": False, "rollback": "retain_v1_metadata_and_disable_v2_migration_wave", "report_redacted": True, "contract_sha256": _sha256(CONTRACT_PATH.read_text(encoding="utf-8")), "allowlist_sha256": _sha256(ALLOWLIST_PATH.read_text(encoding="utf-8"))}
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
