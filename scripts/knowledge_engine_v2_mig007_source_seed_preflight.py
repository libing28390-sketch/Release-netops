"""MIG-007 source/catalog seed preflight (PostgreSQL read-only).

The preflight validates the reviewed CAT-005 candidate against CAT-001 and
compares it with the live legacy inventory.  It intentionally does not create
Source Registry/Version rows, alter V1 metadata, fetch a vendor URL, call an
embedding Provider, or start a rebuild.  A candidate fixture may be verified
by the pure contract classifier, but it is not treated as a live verified
entity until the same-tenant source/version and catalog-owner gates exist.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "MIG-007"
ALLOWLIST_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml"
SNAPSHOT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "catalog" / "CAT-005-HUAWEI-CE6800.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-007-source-seed-preflight-v1.json"
MIG006_SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_mig006_official_entity_validation_check.py"


def _sha256(value: Any) -> str:
    payload = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return re.sub(r"[\s_-]+", " ", _text(value).casefold()).strip()


def _load_mig006() -> Any:
    spec = importlib.util.spec_from_file_location("mig006_for_mig007_preflight", MIG006_SCRIPT)
    if not spec or not spec.loader:
        raise AssertionError("MIG-006 validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    allowlist = yaml.safe_load(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    snapshot = yaml.safe_load(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if not isinstance(allowlist, dict) or allowlist.get("task_id") != "CAT-001":
        raise AssertionError("CAT-001 allowlist is invalid")
    if not isinstance(snapshot, dict) or snapshot.get("task_id") != "CAT-005":
        raise AssertionError("CAT-005 snapshot is invalid")
    return allowlist, snapshot


def _allowed_url(url: str, allowlist: Mapping[str, Any]) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme.casefold() != "https" or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    host = (parsed.hostname or "").casefold()
    for entry in allowlist.get("vendor_entries", []):
        if not isinstance(entry, dict):
            continue
        for host_entry in entry.get("official_hosts", []):
            if not isinstance(host_entry, dict) or _text(host_entry.get("host")).casefold() != host:
                continue
            if any(parsed.path.startswith(_text(prefix)) for prefix in host_entry.get("path_prefixes", [])):
                return True
    return False


def candidate_preflight(allowlist: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    scope = dict(snapshot.get("scope") or {})
    if not scope:
        vendor = snapshot.get("vendor") or {}
        family = snapshot.get("product_family") or {}
        series = (family.get("product_series") or [{}])[0]
        model = next((item for item in series.get("model_samples", []) if isinstance(item, dict) and _norm(item.get("model_code")) == "ce6885 48ys8cq"), {})
        software = snapshot.get("software_scope") or {}
        advisory = snapshot.get("platform_binding_advisory") or {}
        scope = {
            "vendor": vendor.get("display_name") or vendor.get("vendor_id"),
            "product_family": family.get("display_name") or family.get("code"),
            "product_series": series.get("display_name") or series.get("code"),
            "product_model": model.get("model_code"),
            "os_family": software.get("os_family"),
            "os_generation": software.get("os_family"),
            "software_train": software.get("software_train"),
            "primary_version": software.get("primary_version"),
            "documented_version_scope": [software.get("primary_version"), software.get("compatibility_version")],
            "cli_platform": advisory.get("platform_code"),
        }
    reasons: list[str] = []
    if _norm(scope.get("vendor")) != "huawei":
        reasons.append("VENDOR_SCOPE_INVALID")
    if _norm(scope.get("product_family")) != "cloudengine 6800":
        reasons.append("PRODUCT_SCOPE_INVALID")
    if _norm(scope.get("os_family")) != "vrp8":
        reasons.append("OS_SCOPE_INVALID")
    if not _text(scope.get("product_model")):
        reasons.append("PRODUCT_MODEL_MISSING")
    version_scope = {_norm(scope.get("primary_version")), *(_norm(value) for value in scope.get("documented_version_scope", []))}
    source_versions = snapshot.get("source_versions") if isinstance(snapshot.get("source_versions"), list) else snapshot.get("source_refs") if isinstance(snapshot.get("source_refs"), list) else []
    allowed_source_count = 0
    source_fact_count = 0
    source_refs: list[str] = []
    for item in source_versions:
        if not isinstance(item, dict):
            reasons.append("SOURCE_VERSION_INVALID")
            continue
        ref = _text(item.get("source_ref"))
        source_refs.append(_sha256(ref)[:16])
        source_url = _text(item.get("canonical_url") or item.get("url"))
        if _allowed_url(source_url, allowlist):
            allowed_source_count += 1
        else:
            reasons.append("SOURCE_URL_OUTSIDE_ALLOWLIST")
        if _text(item.get("artifact_sha256")) and int(item.get("artifact_bytes") or 0) > 0:
            source_fact_count += 1
        else:
            reasons.append("SOURCE_VERSION_FACTS_MISSING")
    if not source_versions:
        reasons.append("SOURCE_VERSION_MISSING")
    review = snapshot.get("review") or {}
    review_status = _text(review.get("human_catalog_owner_review")) or "REQUIRED"
    if review_status == "REQUIRED" or _text(snapshot.get("status")).casefold().endswith("pending_catalog_migration"):
        reasons.append("CATALOG_OWNER_REVIEW_REQUIRED")
    candidate_row = {
        "id": "candidate-cat005-ce6885",
        "tenant_id": "tenant-default",
        "source": "candidate-cat005-source",
        "source_status": "active",
        "source_validation_status": "valid",
        "source_url": _text((source_versions[0] if source_versions else {}).get("canonical_url") or (source_versions[0] if source_versions else {}).get("url")),
        "vendor": scope.get("vendor"),
        "product_family": scope.get("product_family"),
        "product_series": scope.get("product_series"),
        "product_model": scope.get("product_model"),
        "os_family": scope.get("os_family"),
        "os_generation": scope.get("os_generation"),
        "software_train": scope.get("software_train"),
        "software_release": scope.get("primary_version"),
        "cli_platform": scope.get("cli_platform"),
        "metadata_json": {"vendor": scope.get("vendor"), "product_model": scope.get("product_model")},
    }
    mig006 = _load_mig006()
    candidate_grade = mig006.classify_entity(candidate_row, dict(allowlist), catalog_available=True)
    return {
        "candidate_snapshot_id": _text(snapshot.get("snapshot_id")),
        "candidate_fixture_grade": candidate_grade["grade"],
        "candidate_fixture_reason_codes": candidate_grade["reason_codes"],
        "allowlisted_source_count": allowed_source_count,
        "source_version_fact_count": source_fact_count,
        "source_ref_hashes": source_refs,
        "candidate_scope": {key: scope.get(key) for key in ("vendor", "product_family", "product_series", "product_model", "os_family", "software_train", "primary_version", "cli_platform")},
        "documented_version_scope_hash": _sha256(sorted(version_scope)),
        "reasons": sorted(set(reasons)),
        "review_status": review_status,
    }


def _postgres_probe() -> dict[str, Any]:
    from database import core

    if not core._USE_PG:
        raise RuntimeError("MIG-007 source preflight requires PostgreSQL; SQLite is forbidden")
    conn = core.get_db_connection()
    try:
        conn.execute("BEGIN READ ONLY")
        read_only = _text(conn.execute("SHOW transaction_read_only").fetchone()[0]).casefold() == "on"
        docs = conn.execute("SELECT tenant_id, source, product_family, product_model, os_family, software_release, source_trust_level FROM ai_document").fetchall()
        source_rows = conn.execute("SELECT tenant_id, status, validation_status FROM kb_source_registry").fetchall()
        version_rows = conn.execute("SELECT tenant_id, status FROM kb_source_version").fetchall()
        conn.rollback()
    finally:
        conn.close()
    tenant_default = [row for row in docs if _text(row[0]) == "tenant-default"]
    exact_model = [row for row in tenant_default if _norm(row[3]) == "ce6885 48ys8cq" and _norm(row[2]) == "cloudengine 6800" and _norm(row[5]) in {"v300r024c10spc500", "v300r024c10", "v300r024c11"}]
    same_tenant_sources = [row for row in source_rows if _text(row[0]) == "tenant-default" and _text(row[1]).casefold() == "active" and _text(row[2]).casefold() == "valid"]
    same_tenant_versions = [row for row in version_rows if _text(row[0]) == "tenant-default" and _text(row[1]).casefold() == "verified"]
    return {
        "status": "PASS" if read_only else "FAIL",
        "database": "PostgreSQL",
        "transaction_read_only": read_only,
        "legacy_documents": len(docs),
        "tenant_default_documents": len(tenant_default),
        "exact_candidate_legacy_rows": len(exact_model),
        "same_tenant_active_valid_source_rows": len(same_tenant_sources),
        "same_tenant_verified_source_versions": len(same_tenant_versions),
        "source_registry_rows": len(source_rows),
        "source_version_rows": len(version_rows),
        "production_database_write": False,
        "external_fetch": False,
        "sqlite": "forbidden",
    }


def run_gate() -> dict[str, Any]:
    started = time.perf_counter()
    allowlist, snapshot = load_inputs()
    candidate = candidate_preflight(allowlist, snapshot)
    live = _postgres_probe()
    blockers = list(candidate["reasons"])
    if live["same_tenant_active_valid_source_rows"] == 0:
        blockers.append("SOURCE_REGISTRY_BINDING_MISSING")
    if live["same_tenant_verified_source_versions"] == 0:
        blockers.append("SOURCE_VERSION_BINDING_MISSING")
    if live["exact_candidate_legacy_rows"] == 0:
        blockers.append("NO_LEGACY_ROW_IN_EXACT_VERSION_SCOPE")
    return {
        "status": "BLOCKED" if blockers else "READY_FOR_MIG006_RECHECK",
        "task_id": TASK_ID,
        "authority": "PostgreSQL",
        "sqlite": "forbidden",
        "candidate": candidate,
        "live": live,
        "blocker_reasons": sorted(set(blockers)),
        "production_database_write": False,
        "external_fetch": False,
        "provider_calls": 0,
        "report_redacted": True,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "rollback": "discard_preflight_report_and_keep_v1_projection",
        "allowlist_sha256": _sha256(ALLOWLIST_PATH.read_text(encoding="utf-8")),
        "snapshot_sha256": _sha256(SNAPSHOT_PATH.read_text(encoding="utf-8")),
    }


def main() -> int:
    try:
        report = run_gate()
    except Exception as exc:
        report = {"status": "ERROR", "task_id": TASK_ID, "error_type": type(exc).__name__}
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") in {"BLOCKED", "READY_FOR_MIG006_RECHECK"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
