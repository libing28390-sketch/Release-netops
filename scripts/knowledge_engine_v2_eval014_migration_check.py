"""Run the PostgreSQL-only EVAL-014 migration and recovery gate.

The gate creates one uniquely named temporary PostgreSQL database, runs the
real V1 bootstrap and all discovered migrations there, and drops that database
in a finally block.  The configured application database is used only as the
PostgreSQL server authority; it is never written by this probe.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "EVAL-014-MIGRATION-RECOVERY-CONTRACT.yaml"
RUNNER_PATH = ROOT / "backend" / "database" / "migrations" / "__init__.py"
SCHEMA_PATH = ROOT / "backend" / "database" / "schema.py"
BACKFILL_PATH = ROOT / "backend" / "database" / "migrations" / "m0148_ai_provider_tags_json_normalization.py"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-migration-recovery-v1.manifest.json"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing EVAL-014 authority: {path}"
    return path.read_text(encoding="utf-8")


def _require(text: str, marker: str, label: str) -> None:
    assert marker in text, f"{label} missing marker: {marker}"


def validate_migration_coverage() -> dict[str, Any]:
    contract = _read(CONTRACT_PATH)
    runner = _read(RUNNER_PATH)
    schema = _read(SCHEMA_PATH)
    backfill = _read(BACKFILL_PATH)
    for marker in ("authority: PostgreSQL", "sqlite: forbidden", "temporary_database: required", "production_database_write: false"):
        _require(contract, marker, "EVAL-014 contract")
    for marker in ("discover_migrations", "build_migration_plan", "strict_history", "conn.rollback()", "halt"):
        _require(runner, marker, "migration runner")
    for marker in ("_init_db_logic", "run_migrations", "allow_legacy_import=False", "strict_history=True"):
        _require(schema, marker, "V1 bootstrap")
    for marker in ("tags_json", "TRIM", "LOWER", "'[]'"):
        _require(backfill, marker, "m0148 backfill")
    assert "sqlite3" not in (runner + schema + backfill).lower(), "SQLite implementation is not allowed in EVAL-014 authority"
    return {
        "status": "PASS",
        "task_id": "EVAL-014",
        "database": "postgresql",
        "sqlite": "not_used",
        "coverage": {
            "fresh_install": True,
            "repeated_execution": True,
            "backfill": True,
            "constraints": True,
            "rollback": True,
            "recovery": True,
        },
        "production_database_write": False,
        "source_sha256": {
            "contract": hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            "runner": hashlib.sha256(runner.encode("utf-8")).hexdigest(),
            "schema": hashlib.sha256(schema.encode("utf-8")).hexdigest(),
            "backfill": hashlib.sha256(backfill.encode("utf-8")).hexdigest(),
        },
    }


def _require_pg_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url.lower().startswith(("postgresql://", "postgres://")):
        raise RuntimeError("EVAL-014 requires a PostgreSQL DATABASE_URL; SQLite is forbidden")
    return url


def _dsn_for_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


def _open_wrapped(dsn: str):
    from database import core

    raw = psycopg2.connect(dsn, connect_timeout=10, client_encoding="UTF8")
    return core._PgRawConnection(raw)


def _table_exists(conn: Any, table: str) -> bool:
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?)",
        (table,),
    ).fetchone()
    return bool(row[0])


def _count(conn: Any, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _fresh_install_and_repeat(conn: Any) -> dict[str, Any]:
    from database.migrations import build_migration_plan, get_applied_records, run_migrations
    from database.schema import _init_db_logic

    before_tracking = _table_exists(conn, "schema_migrations")
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    conn.commit()
    _init_db_logic(conn, allow_legacy_import=False)
    conn.commit()
    baseline_records = get_applied_records(conn)
    first_count = run_migrations(conn, use_pg=True, strict_history=True)
    first_plan = build_migration_plan(conn, use_pg=True)
    v1_tables = ("users", "devices", "ai_document", "ai_document_chunk")
    before_v1_counts = {table: _count(conn, table) for table in v1_tables}
    second_count = run_migrations(conn, use_pg=True, strict_history=True)
    second_plan = build_migration_plan(conn, use_pg=True)
    after_v1_counts = {table: _count(conn, table) for table in v1_tables}
    if before_tracking:
        raise AssertionError("temporary database was not fresh before bootstrap")
    if baseline_records:
        raise AssertionError(f"fresh V1 bootstrap unexpectedly had migration history: {baseline_records}")
    if first_count <= 0 or first_plan.pending_versions:
        raise AssertionError(f"fresh install did not finish migrations: {first_plan}")
    if second_count != 0 or second_plan.pending_versions or not second_plan.safe:
        raise AssertionError(f"repeat migration was not a no-op: {second_plan}")
    if before_v1_counts != after_v1_counts:
        raise AssertionError("repeat migration changed V1 row counts")
    return {
        "status": "PASS",
        "fresh_database_before_bootstrap": True,
        "baseline_marker": 1 if 1 in first_plan.applied_versions else None,
        "first_applied": first_count,
        "history_versions": len(first_plan.applied_versions),
        "pending_after_first": list(first_plan.pending_versions),
        "second_applied": second_count,
        "pending_after_second": list(second_plan.pending_versions),
        "v1_tables": list(v1_tables),
        "v1_counts_unchanged": True,
    }


def _backfill_and_rollback(conn: Any) -> dict[str, Any]:
    from database.migrations import m0148_ai_provider_tags_json_normalization as migration

    conn.execute("CREATE TEMP TABLE ai_provider (id TEXT PRIMARY KEY, tags_json TEXT) ON COMMIT DROP")
    conn.execute(
        "INSERT INTO ai_provider (id, tags_json) VALUES (?, ?), (?, ?), (?, ?), (?, ?)",
        ("empty", "{}", "null", "null", "blank", "", "valid", '["network"]'),
    )
    migration.upgrade(conn.cursor(), use_pg=True)
    migration.upgrade(conn.cursor(), use_pg=True)
    rows = dict(conn.execute("SELECT id, tags_json FROM ai_provider").fetchall())
    expected = {"empty": "[]", "null": "[]", "blank": "[]", "valid": '["network"]'}
    if rows != expected:
        raise AssertionError(f"m0148 backfill mismatch: {rows}")
    conn.rollback()
    if _table_exists(conn, "ai_provider") and conn.execute("SELECT to_regclass('pg_temp.ai_provider')").fetchone()[0] is not None:
        raise AssertionError("m0148 temporary backfill survived rollback")
    return {
        "status": "PASS",
        "migration": "m0148_ai_provider_tags_json_normalization",
        "rows_after_repeat": rows,
        "idempotent": True,
        "rollback": True,
    }


def _expect_pg_error(conn: Any, operation: Callable[[], None], label: str) -> str:
    try:
        operation()
    except psycopg2.Error as exc:
        code = str(getattr(exc, "pgcode", "PG_ERROR"))
        conn.rollback()
        return code
    conn.rollback()
    raise AssertionError(f"constraint did not reject {label}")


def _seed_registry(conn: Any, *, registry_id: str, tenant_id: str, canonical_url: str) -> None:
    now = "2026-08-17T00:00:00+00:00"
    conn.execute(
        "INSERT INTO kb_source_registry (id, tenant_id, source_type, source_kind, name, canonical_url, allowed_host, trust_level, collection_policy_json, created_at, updated_at, created_by, updated_by) "
        "VALUES (?, ?, 'official_vendor', 'official_url', 'EVAL-014', ?, 'support.example.com', 'official', '{}'::jsonb, ?, ?, 'eval-014', 'eval-014')",
        (registry_id, tenant_id, canonical_url, now, now),
    )


def _seed_version(conn: Any, *, version_id: str, tenant_id: str, registry_id: str, byte_size: int = 10) -> None:
    now = "2026-08-17T00:00:00+00:00"
    conn.execute(
        "INSERT INTO kb_source_version (id, tenant_id, source_registry_id, fetched_at, content_hash, byte_size, parser_name, parser_version, status, created_at, updated_at, created_by, updated_by) "
        "VALUES (?, ?, ?, ?, ?, ?, 'eval-parser', '1', 'verified', ?, ?, 'eval-014', 'eval-014')",
        (version_id, tenant_id, registry_id, now, "a" * 64, byte_size, now, now),
    )


def _constraint_probe(conn: Any) -> dict[str, Any]:
    checks: dict[str, str] = {}
    checks["source_type_check"] = _expect_pg_error(
        conn,
        lambda: conn.execute(
            "INSERT INTO kb_source_registry (id, tenant_id, source_type, canonical_url, allowed_host, trust_level, collection_policy_json, created_at, updated_at, created_by, updated_by) VALUES ('eval014-invalid-type', 'tenant-a', 'invalid', 'https://support.example.com/invalid', 'support.example.com', 'official', '{}'::jsonb, '2026-08-17T00:00:00+00:00', '2026-08-17T00:00:00+00:00', 'eval-014', 'eval-014')"
        ),
        "invalid source_type",
    )
    checks["tenant_canonical_unique"] = _expect_pg_error(
        conn,
        lambda: (
            _seed_registry(conn, registry_id="eval014-reg-a", tenant_id="tenant-a", canonical_url="https://support.example.com/same"),
            _seed_registry(conn, registry_id="eval014-reg-b", tenant_id="tenant-a", canonical_url="https://support.example.com/same"),
        ),
        "duplicate tenant canonical URL",
    )
    checks["nonnegative_byte_size"] = _expect_pg_error(
        conn,
        lambda: (_seed_registry(conn, registry_id="eval014-reg-c", tenant_id="tenant-c", canonical_url="https://support.example.com/size"), _seed_version(conn, version_id="eval014-ver-c", tenant_id="tenant-c", registry_id="eval014-reg-c", byte_size=-1)),
        "negative source byte_size",
    )
    checks["tenant_source_fk"] = _expect_pg_error(
        conn,
        lambda: (_seed_registry(conn, registry_id="eval014-reg-d", tenant_id="tenant-d", canonical_url="https://support.example.com/fk"), _seed_version(conn, version_id="eval014-ver-d", tenant_id="tenant-other", registry_id="eval014-reg-d")),
        "cross-tenant source version FK",
    )
    def immutable_update() -> None:
        _seed_registry(conn, registry_id="eval014-reg-e", tenant_id="tenant-e", canonical_url="https://support.example.com/immutable")
        _seed_version(conn, version_id="eval014-ver-e", tenant_id="tenant-e", registry_id="eval014-reg-e")
        conn.execute("UPDATE kb_source_version SET content_hash=? WHERE id=?", ("b" * 64, "eval014-ver-e"))
    checks["immutable_source_fact"] = _expect_pg_error(conn, immutable_update, "immutable source content_hash")
    return {"status": "PASS", "checks": checks, "all_rejected": all(checks.values())}


def _recovery_probe(conn: Any) -> dict[str, Any]:
    from database import migrations
    from database.migrations import run_migrations

    conn.execute("CREATE TEMP TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_migrations VALUES (1, 'baseline', 'now')")
    conn.commit()
    calls: list[int] = []
    attempts = {"failed": 0}

    def baseline(cursor: Any, use_pg: bool) -> None:
        calls.append(1)

    def failing(cursor: Any, use_pg: bool) -> None:
        calls.append(2)
        attempts["failed"] += 1
        cursor.execute("CREATE TABLE eval014_partial (id TEXT PRIMARY KEY)")
        cursor.execute("INSERT INTO eval014_partial (id) VALUES ('partial')")
        if attempts["failed"] == 1:
            raise RuntimeError("controlled EVAL-014 failure")

    def higher(cursor: Any, use_pg: bool) -> None:
        calls.append(3)

    modules = [
        SimpleNamespace(VERSION=1, NAME="baseline", upgrade=baseline),
        SimpleNamespace(VERSION=2, NAME="failing", upgrade=failing),
        SimpleNamespace(VERSION=3, NAME="higher", upgrade=higher),
    ]
    original_discover = migrations.discover_migrations
    migrations.discover_migrations = lambda: modules
    try:
        first = run_migrations(conn, use_pg=True, strict_history=True)
        partial_after_failure = conn.execute("SELECT to_regclass('eval014_partial')").fetchone()[0]
        first_history = [int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()]
        second = run_migrations(conn, use_pg=True, strict_history=True)
        second_history = [int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()]
        conn.execute("INSERT INTO schema_migrations VALUES (999, 'unknown', 'now')")
        conn.commit()
        drift_blocked = run_migrations(conn, use_pg=True, strict_history=True)
    finally:
        migrations.discover_migrations = original_discover
        conn.rollback()
    if first != 0 or calls[:1] != [2] or partial_after_failure is not None or first_history != [1]:
        raise AssertionError(f"failed migration was not rolled back safely: {first}, {calls}, {first_history}, {partial_after_failure}")
    if second != 2 or calls != [2, 2, 3] or second_history != [1, 2, 3] or drift_blocked != 0:
        raise AssertionError(f"migration recovery/drift gate failed: {second}, {calls}, {second_history}, {drift_blocked}")
    return {
        "status": "PASS",
        "first_attempt_applied": first,
        "higher_version_not_called_after_failure": 3 not in calls[:1],
        "partial_ddl_rolled_back": partial_after_failure is None,
        "corrected_retry_applied": second,
        "history_after_retry": second_history,
        "history_drift_fail_closed": drift_blocked == 0,
    }


def run_postgresql_migration_matrix() -> dict[str, Any]:
    url = _require_pg_url()
    parts = urlsplit(url)
    if not re.fullmatch(r"[A-Za-z0-9_]+", parts.path.lstrip("/")):
        raise RuntimeError("EVAL-014 requires a simple PostgreSQL database name")
    name = f"nexora_eval014_{uuid.uuid4().hex[:12]}"
    admin = psycopg2.connect(_dsn_for_database(url, "postgres"), connect_timeout=10, client_encoding="UTF8")
    admin.autocommit = True
    conn = None
    dropped = False
    try:
        admin.cursor().execute(f'CREATE DATABASE "{name}"')
        conn = _open_wrapped(_dsn_for_database(url, name))
        fresh = _fresh_install_and_repeat(conn)
        backfill = _backfill_and_rollback(conn)
        constraints = _constraint_probe(conn)
        recovery = _recovery_probe(conn)
        return {
            "status": "PASS",
            "task_id": "EVAL-014",
            "database": "postgresql",
            "sqlite": "not_used",
            "temporary_database": name,
            "temporary_database_dropped": True,
            "fresh_install": fresh,
            "repeated_execution": {"status": fresh["status"], "second_applied": fresh["second_applied"]},
            "backfill": backfill,
            "constraints": constraints,
            "rollback": {"status": "PASS", "backfill_transaction": backfill["rollback"], "failed_migration": recovery["partial_ddl_rolled_back"]},
            "recovery": recovery,
            "production_database_write": False,
            "external_network_call": False,
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        try:
            admin.cursor().execute(f'DROP DATABASE IF EXISTS "{name}"')
            dropped = True
        finally:
            admin.close()
        if not dropped:
            raise RuntimeError("EVAL-014 temporary PostgreSQL database cleanup failed")


def main() -> int:
    coverage = validate_migration_coverage()
    matrix = run_postgresql_migration_matrix()
    output = {**coverage, "matrix": matrix, "rollback_or_cleanup": True}
    REPORT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
