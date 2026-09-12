"""PostgreSQL backup, source-manifest, and restore-rehearsal primitives.

The module keeps backup execution explicit and environment-owned. PostgreSQL
production dumps use `pg_dump`; this module adds a credential-free command
plan and a deterministic source manifest. No function here deletes a source
database or restores over an unspecified target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import get_db_connection


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


def _table_columns(conn: Any, table: str) -> set[str]:
    try:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]) for row in rows}
    except Exception:
        return set()


def _table_exists(conn: Any, table: str) -> bool:
    return bool(_table_columns(conn, table))


def _schema_version(conn: Any) -> int | None:
    if not _table_exists(conn, "schema_migrations"):
        return None
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _source_rows(conn: Any, *, tenant_id: str | None) -> list[dict[str, Any]]:
    if not _table_exists(conn, "ai_document"):
        return []
    columns = _table_columns(conn, "ai_document")
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
) -> dict[str, Any]:
    """Export deterministic source facts without raw content or identifiers."""
    own_conn = conn is None
    connection = conn or get_db_connection()
    try:
        rows = _source_rows(connection, tenant_id=tenant_id)
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
        if _table_exists(connection, "ai_document_chunk"):
            try:
                if tenant_id is not None and _table_exists(connection, "ai_document"):
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
            "database_backend": "postgresql",
            "schema_version": _schema_version(connection),
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
    parser = argparse.ArgumentParser(description="Nexora Knowledge Engine backup and manifest tools")
    sub = parser.add_subparsers(dest="command", required=True)
    manifest_parser = sub.add_parser("manifest")
    manifest_parser.add_argument("--output", required=True)
    manifest_parser.add_argument("--tenant-id")
    args = parser.parse_args()
    print(json.dumps(export_source_manifest(output_path=args.output, tenant_id=args.tenant_id), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "MANIFEST_FORMAT", "build_postgres_backup_plan", "export_source_manifest",
]
