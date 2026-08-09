"""Backup, source-manifest, and restore-rehearsal primitives.

The module keeps backup execution explicit and environment-owned. PostgreSQL
production dumps continue to use the existing `pg_dump` operational script;
this module adds a credential-free command plan and a deterministic source
manifest. SQLite backup/restore is implemented with the standard online
backup API for isolated development and rehearsal fixtures. No function here
deletes a source database or restores over an unspecified path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import _USE_PG, get_db_connection


logger = logging.getLogger(__name__)
MANIFEST_FORMAT = "nexora-knowledge-source-manifest/v2"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hash(value: Any) -> str:
    if value is None:
        value = ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(str(value).encode("utf-8", "replace")).hexdigest()


def _table_columns(conn: Any, table: str, *, use_pg: bool) -> set[str]:
    try:
        if use_pg:
            rows = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                (table,),
            ).fetchall()
            return {str(row[0]) for row in rows}
        rows = conn.execute(f"PRAGMA table_info(\"{table.replace(chr(34), chr(34) * 2)}\")").fetchall()
        return {str(row[1]) for row in rows}
    except Exception:
        return set()


def _table_exists(conn: Any, table: str, *, use_pg: bool) -> bool:
    return bool(_table_columns(conn, table, use_pg=use_pg))


def _schema_version(conn: Any, *, use_pg: bool) -> int | None:
    if not _table_exists(conn, "schema_migrations", use_pg=use_pg):
        return None
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _source_rows(conn: Any, *, use_pg: bool, tenant_id: str | None) -> list[dict[str, Any]]:
    if not _table_exists(conn, "ai_document", use_pg=use_pg):
        return []
    columns = _table_columns(conn, "ai_document", use_pg=use_pg)
    selected = [
        name for name in (
            "id", "document_id", "name", "source", "vendor", "platform", "version", "status",
            "tenant_id", "knowledge_source_type", "source_trust_level", "content_hash",
            "original_content", "normalized_content", "metadata_json", "updated_at",
        ) if name in columns
    ]
    if "id" not in selected:
        return []
    where = ""
    params: list[Any] = []
    if tenant_id is not None and "tenant_id" in columns:
        where = " WHERE tenant_id = ?"
        params.append(str(tenant_id))
    cursor = conn.execute(
        f"SELECT {', '.join(selected)} FROM ai_document{where} ORDER BY id",
        params,
    )
    descriptions = [str(item[0]) for item in (cursor.description or [])]
    return [dict(zip(descriptions, row)) for row in cursor.fetchall()]


def export_source_manifest(
    conn: Any | None = None,
    *,
    output_path: str | os.PathLike[str] | None = None,
    tenant_id: str | None = None,
    use_pg: bool | None = None,
) -> dict[str, Any]:
    """Export deterministic source facts without raw content or identifiers."""
    own_conn = conn is None
    connection = conn or get_db_connection()
    backend_pg = _USE_PG if use_pg is None else bool(use_pg)
    try:
        rows = _source_rows(connection, use_pg=backend_pg, tenant_id=tenant_id)
        records: list[dict[str, Any]] = []
        tenant_hashes: set[str] = set()
        for row in rows:
            tenant = row.get("tenant_id") or "tenant-default"
            tenant_hashes.add(_hash(tenant))
            raw_content = row.get("original_content")
            if raw_content is None:
                raw_content = row.get("normalized_content")
            content_hash = row.get("content_hash") or _hash(raw_content or "")
            metadata = row.get("metadata_json")
            try:
                metadata = json.loads(str(metadata)) if isinstance(metadata, str) else metadata
            except (TypeError, ValueError):
                metadata = {"_malformed": True}
            records.append({
                "document_key_hash": _hash(f"{tenant}|{row.get('id') or ''}"),
                "external_document_id_hash": _hash(row.get("document_id") or row.get("id") or ""),
                "name_hash": _hash(row.get("name") or ""),
                "source_ref_hash": _hash(row.get("source") or ""),
                "content_hash": str(content_hash),
                "metadata_hash": _hash(metadata or {}),
                "tenant_hash": _hash(tenant),
                "vendor_hash": _hash(row.get("vendor") or "all"),
                "platform_hash": _hash(row.get("platform") or "all"),
                "status": str(row.get("status") or "unknown"),
                "source_type": str(row.get("knowledge_source_type") or "user_document"),
                "source_trust_level": str(row.get("source_trust_level") or "unknown"),
                "updated_at": str(row.get("updated_at") or ""),
            })
        canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        chunk_count = 0
        if _table_exists(connection, "ai_document_chunk", use_pg=backend_pg):
            try:
                if tenant_id is not None and _table_exists(connection, "ai_document", use_pg=backend_pg):
                    row = connection.execute(
                        "SELECT COUNT(*) FROM ai_document_chunk c JOIN ai_document d ON d.id = c.document_id WHERE d.tenant_id = ?",
                        (str(tenant_id),),
                    ).fetchone()
                else:
                    row = connection.execute("SELECT COUNT(*) FROM ai_document_chunk").fetchone()
                chunk_count = int(row[0] or 0) if row else 0
            except Exception:
                chunk_count = 0
        manifest = {
            "format": MANIFEST_FORMAT,
            "generated_at": _now(),
            "database_backend": "postgresql" if backend_pg else "sqlite",
            "schema_version": _schema_version(connection, use_pg=backend_pg),
            "tenant_scope": "filtered" if tenant_id is not None else "all",
            "tenant_count": len(tenant_hashes),
            "document_count": len(records),
            "chunk_count": chunk_count,
            "source_manifest_digest": _hash(canonical),
            "documents": records,
            "redaction": [
                "raw_document_id_omitted", "raw_document_name_omitted", "raw_source_omitted",
                "raw_content_omitted", "raw_metadata_omitted", "raw_tenant_id_omitted",
            ],
        }
        if output_path is not None:
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    finally:
        if own_conn:
            connection.close()


def backup_sqlite(source_path: str | os.PathLike[str], backup_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Create a consistent SQLite backup without mutating the source path."""
    source = Path(source_path)
    target = Path(backup_path)
    if not source.is_file():
        raise FileNotFoundError(str(source))
    if source.resolve() == target.resolve():
        raise ValueError("backup target must differ from source")
    if target.exists():
        raise FileExistsError(str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(str(source))
    target_conn = sqlite3.connect(str(target))
    try:
        source_conn.backup(target_conn)
        integrity = target_conn.execute("PRAGMA integrity_check").fetchone()[0]
        target_conn.commit()
        if str(integrity).lower() != "ok":
            raise RuntimeError("SQLite backup integrity check failed")
        return {"backend": "sqlite", "source": str(source), "backup": str(target), "integrity": "ok"}
    finally:
        source_conn.close()
        target_conn.close()


def restore_rehearsal_sqlite(
    backup_path: str | os.PathLike[str],
    rehearsal_path: str | os.PathLike[str] | None = None,
    *,
    expected_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Restore a backup into an explicit rehearsal path and verify its digest."""
    backup = Path(backup_path)
    if not backup.is_file():
        raise FileNotFoundError(str(backup))
    if rehearsal_path is None:
        handle = tempfile.NamedTemporaryFile(prefix="nexora-restore-rehearsal-", suffix=".db", delete=False)
        handle.close()
        rehearsal = Path(handle.name)
        rehearsal.unlink(missing_ok=True)
    else:
        rehearsal = Path(rehearsal_path)
        if rehearsal.exists():
            raise FileExistsError(str(rehearsal))
    result = backup_sqlite(backup, rehearsal)
    conn = sqlite3.connect(str(rehearsal))
    try:
        manifest = export_source_manifest(conn=conn, use_pg=False)
        if expected_manifest is not None and manifest["source_manifest_digest"] != expected_manifest.get("source_manifest_digest"):
            raise RuntimeError("restore rehearsal source manifest digest mismatch")
        result.update({
            "rehearsal": str(rehearsal),
            "document_count": manifest["document_count"],
            "chunk_count": manifest["chunk_count"],
            "source_manifest_digest": manifest["source_manifest_digest"],
            "restore_verified": True,
        })
        return result
    finally:
        conn.close()


def build_postgres_backup_plan(
    *,
    backup_path: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Return an executable, credential-free PG backup/restore plan."""
    backup = str(Path(backup_path))
    manifest = str(Path(manifest_path))
    return {
        "backend": "postgresql",
        "backup": {
            "tool": "pg_dump",
            "argv": ["pg_dump", "--format=custom", "--no-owner", "--file", backup, "${DATABASE_URL}"],
            "credential_source": "DATABASE_URL_environment_only",
        },
        "manifest": {
            "tool": "python -m database.backup manifest",
            "argv": ["python", "-m", "database.backup", "manifest", "--output", manifest],
            "credential_source": "DATABASE_URL_environment_only",
        },
        "restore_rehearsal": {
            "tool": "pg_restore",
            "argv_template": ["pg_restore", "--exit-on-error", "--no-owner", "--dbname", "${REHEARSAL_DATABASE_URL}", backup],
            "requires": ["isolated_rehearsal_database", "approved_operator", "manifest_digest_comparison"],
            "production_restore": "forbidden_by_DB-023_cli",
        },
        "secrets_in_plan": False,
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Nexora Knowledge Engine V2 backup and manifest tools")
    sub = parser.add_subparsers(dest="command", required=True)
    manifest_parser = sub.add_parser("manifest")
    manifest_parser.add_argument("--output", required=True)
    manifest_parser.add_argument("--tenant-id")
    sqlite_backup = sub.add_parser("backup-sqlite")
    sqlite_backup.add_argument("--source", required=True)
    sqlite_backup.add_argument("--output", required=True)
    rehearsal = sub.add_parser("restore-rehearsal")
    rehearsal.add_argument("--backup", required=True)
    rehearsal.add_argument("--output")
    rehearsal.add_argument("--manifest")
    args = parser.parse_args()
    if args.command == "manifest":
        print(json.dumps(export_source_manifest(output_path=args.output, tenant_id=args.tenant_id), ensure_ascii=False, indent=2))
    elif args.command == "backup-sqlite":
        print(json.dumps(backup_sqlite(args.source, args.output), ensure_ascii=False))
    else:
        expected = None
        if args.manifest:
            expected = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        print(json.dumps(restore_rehearsal_sqlite(args.backup, args.output, expected_manifest=expected), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "MANIFEST_FORMAT", "backup_sqlite", "build_postgres_backup_plan",
    "export_source_manifest", "restore_rehearsal_sqlite",
]
