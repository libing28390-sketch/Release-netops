"""REL-002 PostgreSQL extension, migration-history, and startup gate.

The gate is deliberately read-only.  It does not call ``build_migration_plan``
because that compatibility API creates ``schema_migrations`` when absent.  A
release audit must never mutate the target database merely to inspect it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "REL-002"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "REL-002-POSTGRES-MIGRATION-STARTUP-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "rel-002-postgres-gate-v1.json"
EXTENSIONS_PATH = ROOT / "backend" / "database" / "postgres_extensions.py"
MIGRATIONS_PATH = ROOT / "backend" / "database" / "migrations" / "__init__.py"
SCHEMA_PATH = ROOT / "backend" / "database" / "schema.py"


def _safe_error(exc: BaseException) -> str:
    """Return a stable, secret-free error marker."""

    return type(exc).__name__


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("REL-002 contract task mismatch")
    if payload.get("authority") != "PostgreSQL" or payload.get("sqlite") != "forbidden_for_acceptance":
        raise AssertionError("REL-002 PostgreSQL-only authority is missing")
    if payload.get("production_database_write") is not False:
        raise AssertionError("REL-002 gate must be read-only")
    return payload


def _static_gate() -> dict[str, Any]:
    extensions = EXTENSIONS_PATH.read_text(encoding="utf-8")
    migrations = MIGRATIONS_PATH.read_text(encoding="utf-8")
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    required = {
        "required_extensions_allowlist": 'REQUIRED_V2_EXTENSIONS: tuple[str, ...] = ("vector", "pg_trgm")' in extensions,
        "extension_inspection": "pg_extension" in extensions and "pg_available_extensions" in extensions,
        "extension_failure_codes": all(code in extensions for code in ("POSTGRES_EXTENSION_INSPECTION_FAILED", "POSTGRES_EXTENSION_MISSING", "POSTGRES_EXTENSION_INSTALL_FAILED")),
        "strict_runner_call": "run_migrations(conn, _USE_PG, strict_history=True)" in schema,
        "unsafe_history_rejected": "migration_plan.safe_for(strict_history=True)" in schema and "Database migration history is unsafe" in schema,
        "pending_rejected": "if migration_plan.pending_versions" in schema and "Database migrations are incomplete" in schema,
        "ordered_discovery": "found.sort(key=lambda m: int(m.VERSION))" in migrations,
        "history_drift_detection": "name_drift" in migrations and "unknown_applied_versions" in migrations,
        "failure_rollback": "conn.rollback()" in migrations and "halt" in migrations,
    }
    return {"status": "PASS" if all(required.values()) else "BLOCKED", "checks": required}


def _history_snapshot(conn) -> dict[str, Any]:
    from database.migrations import discover_migrations

    discovered_modules = discover_migrations()
    discovered = {int(module.VERSION): str(module.NAME) for module in discovered_modules}
    rows = conn.execute(
        "SELECT version, name FROM schema_migrations ORDER BY version"
    ).fetchall()
    applied = {int(row[0]): str(row[1]) for row in rows}
    unknown = sorted(set(applied) - set(discovered))
    drift = []
    for version in sorted(set(applied) & set(discovered)):
        module = next(module for module in discovered_modules if int(module.VERSION) == version)
        legacy_names = getattr(module, "LEGACY_NAMES", ())
        if isinstance(legacy_names, str):
            legacy_names = (legacy_names,)
        accepted = {str(module.NAME), *(str(value) for value in legacy_names)}
        if applied[version] not in accepted:
            drift.append({"version": version, "recorded_name": applied[version], "expected_name": str(module.NAME)})
    if applied and 1 not in applied:
        drift.append({"version": 1, "recorded_name": "<missing>", "expected_name": discovered.get(1, "baseline")})
    pending = sorted(set(discovered) - set(applied))
    return {
        "discovered_count": len(discovered),
        "discovered_highest": max(discovered) if discovered else None,
        "applied_count": len(applied),
        "applied_highest": max(applied) if applied else None,
        "pending_versions": pending,
        "unknown_applied_versions": unknown,
        "name_drift": drift,
        "history_safe": not unknown and not drift,
        "pending_empty": not pending,
    }


def _postgres_probe() -> dict[str, Any]:
    from database import core
    from database.postgres_extensions import inspect_extensions

    if not core._USE_PG:
        raise RuntimeError("REL-002 requires PostgreSQL; SQLite is forbidden")
    conn = core.get_db_connection()
    try:
        conn.execute("BEGIN READ ONLY")
        read_only = str(conn.execute("SHOW transaction_read_only").fetchone()[0]).lower() == "on"
        extension_state = inspect_extensions(conn, use_pg=True)
        history = _history_snapshot(conn)
        return {
            "database": "postgresql",
            "transaction_read_only": read_only,
            "extensions": {
                "required": ["vector", "pg_trgm"],
                "installed": dict(extension_state.installed),
                "available": dict(extension_state.available),
                "missing": list(extension_state.missing),
                "ok": extension_state.ok,
            },
            "history": history,
            "production_database_write": False,
            "sqlite": "forbidden",
        }
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def run_gate() -> dict[str, Any]:
    load_contract()
    static = _static_gate()
    reasons: list[str] = []
    try:
        probe = _postgres_probe()
    except Exception as exc:
        probe = {
            "database": "postgresql",
            "transaction_read_only": False,
            "production_database_write": False,
            "sqlite": "forbidden",
            "error_type": _safe_error(exc),
        }
        reasons.append("POSTGRES_PROBE_FAILED")
    if not static["checks"] or static["status"] != "PASS":
        reasons.append("STARTUP_STATIC_CONTRACT_FAILED")
    if probe.get("extensions", {}).get("missing"):
        reasons.append("POSTGRES_EXTENSION_MISSING")
    history = probe.get("history", {})
    if history.get("unknown_applied_versions"):
        reasons.append("MIGRATION_UNKNOWN_APPLIED_VERSION")
    if history.get("name_drift"):
        reasons.append("MIGRATION_NAME_DRIFT")
    if history.get("pending_versions"):
        reasons.append("MIGRATION_PENDING")
    if probe.get("transaction_read_only") is not True:
        reasons.append("READ_ONLY_TRANSACTION_NOT_CONFIRMED")
    status = "PASS" if not reasons else "BLOCKED"
    report = {
        "task_id": TASK_ID,
        "status": status,
        "reason_codes": sorted(set(reasons)),
        "static": static,
        "postgres": probe,
        "external_calls": False,
        "production_database_write": False,
        "sqlite": "forbidden_for_acceptance",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run_gate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
