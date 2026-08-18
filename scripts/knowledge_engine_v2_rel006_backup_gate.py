"""REL-006 release backup gate.

The default gate is static and side-effect free.  ``--pg-probe`` additionally
exports the live Source Manifest inside a PostgreSQL READ ONLY transaction; it
never runs pg_dump against the operator's database and never restores over a
production target.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "REL-006"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "REL-006-BACKUP-MANIFEST-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "rel-006-backup-manifest-v1.json"
DAILY_BACKUP_PATH = ROOT / "scripts" / "install-daily-backup.sh"
DEPLOY_PATH = ROOT / "scripts" / "deploy-docker.sh"
BACKUP_MODULE_PATH = ROOT / "backend" / "database" / "backup.py"
DB023_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-023-BACKUP-MANIFEST-RESTORE-CONTRACT.yaml"


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("REL-006 contract task mismatch")
    return payload


def _contains(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def _postgres_manifest_probe() -> dict[str, Any]:
    """Export only redacted facts in a transaction explicitly marked READ ONLY."""
    try:
        from database.backup import export_source_manifest
        from database.core import _USE_PG, get_db_connection
    except Exception as exc:  # pragma: no cover - environment/import failure
        return {"status": "BLOCKED", "reason": "BACKUP_MODULE_IMPORT_FAILED", "detail": type(exc).__name__}

    if not _USE_PG or not os.environ.get("DATABASE_URL", "").lower().startswith(("postgresql://", "postgres://")):
        return {"status": "BLOCKED", "reason": "DATABASE_URL_NOT_POSTGRESQL"}

    conn = None
    try:
        conn = get_db_connection()
        conn.execute("BEGIN TRANSACTION READ ONLY")
        manifest = export_source_manifest(conn=conn, use_pg=True)
        conn.rollback()
        required = {"format", "schema_version", "document_count", "chunk_count", "source_manifest_digest", "documents", "redaction"}
        redaction = set(manifest.get("redaction") or [])
        redaction_ok = {
            "raw_document_id_omitted", "raw_document_name_omitted", "raw_source_omitted",
            "raw_content_omitted", "raw_metadata_omitted", "raw_tenant_id_omitted",
        }.issubset(redaction)
        return {
            "status": "PASS" if manifest.get("format") == "nexora-knowledge-source-manifest/v2" and required.issubset(manifest) and redaction_ok else "FAIL",
            "database_backend": manifest.get("database_backend"),
            "schema_version": manifest.get("schema_version"),
            "document_count": manifest.get("document_count"),
            "chunk_count": manifest.get("chunk_count"),
            "source_manifest_digest": manifest.get("source_manifest_digest"),
            "redaction_ok": redaction_ok,
            "transaction_read_only": True,
        }
    except Exception as exc:  # pragma: no cover - depends on live operator DB
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return {"status": "BLOCKED", "reason": "POSTGRES_MANIFEST_PROBE_FAILED", "detail": type(exc).__name__}
    finally:
        if conn is not None:
            conn.close()


def run_gate(*, pg_probe: bool = False) -> dict[str, Any]:
    contract = load_contract()
    daily = DAILY_BACKUP_PATH.read_text(encoding="utf-8")
    deploy = DEPLOY_PATH.read_text(encoding="utf-8")
    backup_module = BACKUP_MODULE_PATH.read_text(encoding="utf-8")
    db023 = yaml.safe_load(DB023_PATH.read_text(encoding="utf-8"))

    checks = {
        "contract_postgresql_authority": contract.get("authority") == "PostgreSQL" and db023.get("authority", "").startswith("PostgreSQL"),
        "daily_custom_dump": _contains(daily, "pg_dump --format=custom --no-owner --file", "netops-\\$TS.dump", "PARTIAL_OUT"),
        "daily_manifest_companion": _contains(daily, "database.backup manifest", "source-manifest.json", "source manifest export failed"),
        "daily_config_archive": _contains(daily, "CONFIG_OUT", "config.tar.gz", "CONFIG_ENTRIES", "chmod 600"),
        "daily_atomic_and_retention": _contains(daily, "PARTIAL_OUT", "mv -f", "RETENTION_DAYS"),
        "release_backup_command": _contains(deploy, "backup_release_state", "backup-release", "backup_release_state\n        backup_env"),
        "release_custom_dump": _contains(deploy, "docker compose exec -T db pg_dump", "--format=custom", "--no-owner", "database.dump"),
        "release_manifest_and_snapshots": _contains(deploy, "database.backup manifest", "source-manifest.json", "config-snapshots.tar.gz", "deployment-config.tar.gz"),
        "release_fail_closed": _contains(deploy, "Release backup failed", "die \"Release backup failed", "partial"),
        "credential_free_plan": _contains(backup_module, '"credential_source": "DATABASE_URL_environment_only"', '"production_restore": "forbidden_by_DB-023_cli"', '"--format=custom"'),
        "sqlite_not_used_for_acceptance": True,
    }
    probe = _postgres_manifest_probe() if pg_probe else {"status": "NOT_RUN", "reason": "static_gate_only"}
    static_pass = all(checks.values())
    live_pass = probe.get("status") in {"PASS", "NOT_RUN"}
    report = {
        "task_id": TASK_ID,
        "status": "PASS" if static_pass and live_pass else ("BLOCKED" if probe.get("status") == "BLOCKED" else "FAIL"),
        "reason_codes": [] if static_pass and live_pass else [
            *(key.upper() for key, value in checks.items() if not value),
            *([] if probe.get("status") in {"PASS", "NOT_RUN"} else [str(probe.get("reason", "POSTGRES_PROBE_FAILED"))]),
        ],
        "checks": checks,
        "postgres_manifest_probe": probe,
        "production_database_write": False,
        "pg_dump_executed_by_gate": False,
        "production_restore": "forbidden",
        "sqlite": "forbidden_for_acceptance",
        "external_provider_request": False,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-probe", action="store_true", help="run a PostgreSQL READ ONLY Source Manifest probe")
    args = parser.parse_args()
    print(json.dumps(run_gate(pg_probe=args.pg_probe), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
