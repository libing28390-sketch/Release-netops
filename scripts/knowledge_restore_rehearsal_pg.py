"""Restore a knowledge backup into an isolated PostgreSQL database and upgrade it.

The rehearsal database name is generated internally, validated, and always
dropped in ``finally``. Credentials stay in the environment-owned DATABASE_URL
loaded by ``database.core`` and are never printed.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from database import core  # noqa: E402
from database.migrations import discover_migrations, run_migrations  # noqa: E402


_REHEARSAL_NAME = re.compile(r"^nexora_knowledge_restore_[0-9]{14}_[0-9a-f]{6}$")
_RETIRED_TABLES = (
    "kb_source_registry",
    "kb_source_version",
    "kb_document",
    "kb_document_version",
    "kb_document_source",
    "kb_document_lifecycle_event",
    "kb_source_refresh_observation",
    "kb_source_change_action",
    "kb_site_anomaly_alert",
    "ai_retrieval_index_shadow_chunk",
    "ai_retrieval_index_generation",
    "ai_retrieval_rollout_flag",
)


def _find_pg_restore() -> str:
    executable = shutil.which("pg_restore")
    if executable:
        return executable
    candidates = sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin\pg_restore.exe"), reverse=True)
    if not candidates:
        raise RuntimeError("pg_restore was not found")
    return candidates[0]


def _database_url(name: str) -> str:
    parsed = urlparse(core._DATABASE_URL)
    if parsed.scheme not in {"postgresql", "postgres"} or not parsed.hostname:
        raise RuntimeError("DATABASE_URL must select PostgreSQL")
    return urlunparse(parsed._replace(path=f"/{name}"))


def _scalar(conn, sql: str, params=()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row else 0


def run_rehearsal(backup: Path) -> dict[str, object]:
    if not backup.is_file() or backup.stat().st_size <= 0:
        raise FileNotFoundError(str(backup))
    name = "nexora_knowledge_restore_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:6]
    if not _REHEARSAL_NAME.fullmatch(name):
        raise RuntimeError("generated rehearsal database name is unsafe")

    admin_url = _database_url("postgres")
    target_url = _database_url(name)
    admin = core._pg_connect(dsn=admin_url)
    admin.autocommit = True
    created = False
    try:
        from psycopg2 import sql

        with admin.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cursor.fetchone():
                raise RuntimeError("rehearsal database already exists")
            cursor.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
            created = True

        completed = subprocess.run(
            [
                _find_pg_restore(),
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                target_url,
                str(backup.resolve()),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "pg_restore failed")[-2000:]
            raise RuntimeError(f"pg_restore failed with exit {completed.returncode}: {tail}")

        raw = core._pg_connect(dsn=target_url)
        conn = core._PgRawConnection(raw)
        try:
            before = {
                "schema_version": _scalar(conn, "SELECT MAX(version) FROM schema_migrations"),
                "documents": _scalar(conn, "SELECT COUNT(*) FROM ai_document"),
                "chunks": _scalar(conn, "SELECT COUNT(*) FROM ai_document_chunk"),
            }
            applied = run_migrations(conn, True, strict_history=True)
            expected_schema_version = max(int(module.VERSION) for module in discover_migrations())
            after = {
                "schema_version": _scalar(conn, "SELECT MAX(version) FROM schema_migrations"),
                "documents": _scalar(conn, "SELECT COUNT(*) FROM ai_document"),
                "chunks": _scalar(conn, "SELECT COUNT(*) FROM ai_document_chunk"),
                "revisions": _scalar(conn, "SELECT COUNT(*) FROM ai_document_revision"),
                "retired_tables_remaining": [
                    table
                    for table in _RETIRED_TABLES
                    if conn.execute("SELECT to_regclass(?)", (table,)).fetchone()[0] is not None
                ],
            }
            if after["schema_version"] != expected_schema_version:
                raise RuntimeError(
                    "rehearsal upgrade stopped at schema "
                    f"{after['schema_version']} (expected {expected_schema_version})"
                )
            if after["documents"] < before["documents"] or after["chunks"] < before["chunks"]:
                raise RuntimeError("rehearsal upgrade lost document or chunk rows")
            if after["retired_tables_remaining"]:
                raise RuntimeError("rehearsal upgrade retained retired tables")
            return {
                "status": "PASS",
                "backup": str(backup.resolve()),
                "backup_bytes": backup.stat().st_size,
                "rehearsal_database": name,
                "restored": before,
                "migrations_applied": applied,
                "upgraded": after,
                "dropped_after_verification": True,
            }
        finally:
            conn.close()
    finally:
        if created:
            with admin.cursor() as cursor:
                cursor.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,))
                from psycopg2 import sql

                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        admin.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated PostgreSQL knowledge restore rehearsal")
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()
    result = run_rehearsal(Path(args.backup))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
