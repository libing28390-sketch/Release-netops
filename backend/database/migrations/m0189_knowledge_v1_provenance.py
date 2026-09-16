"""Converge Knowledge Engine provenance onto the V1 document projection.

The V1 document/chunk tables are already the online retrieval authority.  This
migration gives them the small amount of source and lifecycle state that was
previously kept in the V2 catalog, and folds immutable fetch/document facts
into one V1-named revision table.  It is deliberately additive and idempotent:
the V2 tables remain available until the application cutover and a later
cleanup migration proves that they are no longer referenced.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


VERSION = 189
NAME = "knowledge_v1_provenance"


_DOCUMENT_COLUMNS = {
    "canonical_url": "TEXT NOT NULL DEFAULT ''",
    "source_kind": "TEXT NOT NULL DEFAULT ''",
    "source_content_hash": "TEXT NOT NULL DEFAULT ''",
    "source_fetched_at": "TIMESTAMPTZ",
    "source_etag": "TEXT NOT NULL DEFAULT ''",
    "source_last_modified": "TEXT NOT NULL DEFAULT ''",
    "source_http_status": "INTEGER",
    "source_byte_size": "BIGINT NOT NULL DEFAULT 0",
    "source_parser_name": "TEXT NOT NULL DEFAULT ''",
    "source_parser_version": "TEXT NOT NULL DEFAULT ''",
    "source_raw_content_ref": "TEXT NOT NULL DEFAULT ''",
    "source_validation_status": "TEXT NOT NULL DEFAULT 'unvalidated'",
    "lifecycle_status": "TEXT NOT NULL DEFAULT 'published'",
    "lifecycle_revision": "INTEGER NOT NULL DEFAULT 0",
    "lifecycle_changed_at": "TIMESTAMPTZ",
    "lifecycle_changed_by": "TEXT NOT NULL DEFAULT ''",
    "lifecycle_reason": "TEXT NOT NULL DEFAULT ''",
}


def _table_exists(cursor, table: str, use_pg: bool) -> bool:
    cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = ?)",
        (table,),
    )
    return bool(cursor.fetchone()[0])



def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    )
    return {str(row[0]) for row in cursor.fetchall()}



def _ensure_document_columns(cursor, use_pg: bool) -> set[str]:
    if not _table_exists(cursor, "ai_document", use_pg):
        raise RuntimeError("knowledge_v1_provenance requires ai_document")
    existing = _columns(cursor, "ai_document", use_pg)
    for name, definition in _DOCUMENT_COLUMNS.items():
        if name in existing:
            continue
        pass
        cursor.execute(f"ALTER TABLE ai_document ADD COLUMN {name} {definition}")
        existing.add(name)
    return existing


def _json_type(use_pg: bool) -> tuple[str, str]:
    return "JSONB", "'{}'::jsonb"
    return "TEXT", "'{}'"


def _time_type(use_pg: bool) -> str:
    return "TIMESTAMPTZ"


def _create_revision_table(cursor, use_pg: bool) -> None:
    json_type, json_default = _json_type(use_pg)
    time_type = _time_type(use_pg)
    bool_type = "BOOLEAN"
    bool_default = "FALSE"
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS ai_document_revision (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            revision_no INTEGER NOT NULL CHECK (revision_no > 0),
            canonical_url TEXT NOT NULL DEFAULT '',
            source_kind TEXT NOT NULL DEFAULT '',
            fetch_url TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            normalized_content_hash TEXT NOT NULL DEFAULT '',
            original_content TEXT NOT NULL DEFAULT '',
            normalized_content TEXT NOT NULL DEFAULT '',
            metadata_json {json_type} NOT NULL DEFAULT {json_default},
            source_metadata_json {json_type} NOT NULL DEFAULT {json_default},
            fetch_metadata_json {json_type} NOT NULL DEFAULT {json_default},
            parser_name TEXT NOT NULL DEFAULT '',
            parser_version TEXT NOT NULL DEFAULT '',
            cleaner_name TEXT NOT NULL DEFAULT '',
            cleaner_version TEXT NOT NULL DEFAULT '',
            mime_type TEXT NOT NULL DEFAULT '',
            byte_size BIGINT NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
            source_etag TEXT NOT NULL DEFAULT '',
            source_last_modified TEXT NOT NULL DEFAULT '',
            http_status INTEGER,
            fetched_at {time_type},
            status TEXT NOT NULL DEFAULT 'published',
            lifecycle_status TEXT NOT NULL DEFAULT 'published',
            lifecycle_reason TEXT NOT NULL DEFAULT '',
            is_current {bool_type} NOT NULL DEFAULT {bool_default},
            legacy_source_id TEXT NOT NULL DEFAULT '',
            legacy_source_version_id TEXT NOT NULL DEFAULT '',
            legacy_document_id TEXT NOT NULL DEFAULT '',
            legacy_document_version_id TEXT NOT NULL DEFAULT '',
            created_at {time_type} NOT NULL,
            created_by TEXT NOT NULL DEFAULT 'migration',
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, document_id, revision_no),
            FOREIGN KEY (document_id) REFERENCES ai_document(id) ON DELETE CASCADE
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_ai_document_revision_document "
        "ON ai_document_revision(tenant_id, document_id, revision_no DESC)",
        "CREATE INDEX IF NOT EXISTS ix_ai_document_revision_source "
        "ON ai_document_revision(tenant_id, canonical_url, fetched_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_ai_document_revision_hash "
        "ON ai_document_revision(tenant_id, content_hash)",
    ):
        cursor.execute(statement)
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_document_revision_content "
        "ON ai_document_revision(tenant_id, document_id, content_hash) "
        "WHERE content_hash <> ''"
    )


def _row_dict(cursor, row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    columns = [str(item[0]) for item in (cursor.description or ())]
    return dict(zip(columns, row))


def _json_load(value: Any, default: Any = None) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return default if default is not None else {}
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default if default is not None else {}


def _json_value(value: Any, use_pg: bool) -> Any:
    value = value if isinstance(value, (dict, list)) else {}
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    pass
    try:
        from psycopg2.extras import Json

        return Json(value, dumps=lambda item: json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    except ImportError:
        return encoded


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _valid_hash(value: Any) -> str:
    candidate = _text(value).lower()
    return candidate if len(candidate) == 64 and all(char in "0123456789abcdef" for char in candidate) else ""


def _status(value: Any, default: str = "published") -> str:
    candidate = _text(value).lower()
    return candidate or default


def _metadata_with_precedence(primary: Any, fallback: Any) -> dict[str, Any]:
    result = _json_load(fallback, {})
    if not isinstance(result, dict):
        result = {}
    override = _json_load(primary, {})
    if isinstance(override, dict):
        # Existing V1 metadata contains the retrieval classification already;
        # source facts fill gaps without erasing those operator-curated tags.
        merged = dict(override)
        merged.update(result)
        return merged
    return result


def _encode_revision_id(legacy_version_id: str, document_id: str) -> str:
    seed = f"{legacy_version_id}:{document_id}".encode("utf-8")
    return "v1rev-" + hashlib.sha256(seed).hexdigest()[:32]


def _knowledge_base_id(cursor, tenant_id: str) -> str:
    row = cursor.execute(
        "SELECT id FROM ai_knowledge_base "
        "WHERE tenant_id = ? AND enabled = 1 ORDER BY created_at, id LIMIT 1",
        (tenant_id,),
    ).fetchone()
    if row:
        return _text(row[0])
    row = cursor.execute("SELECT id FROM ai_knowledge_base ORDER BY created_at, id LIMIT 1").fetchone()
    if row:
        return _text(row[0])
    raise RuntimeError(f"No ai_knowledge_base exists for tenant {tenant_id}")


def _target_documents(cursor, columns: set[str], tenant_id: str, v2_document_id: str, urls: list[str]) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = [tenant_id]
    if v2_document_id and "document_id" in columns:
        clauses.append("document_id = ?")
        params.append(v2_document_id)
    for url in urls:
        if not url:
            continue
        clauses.extend(["source = ?", "canonical_url = ?"])
        params.extend([url, url])
    if not clauses:
        return []
    rows = cursor.execute(
        "SELECT id, tenant_id, name, source, content_hash, metadata_json, status "
        "FROM ai_document WHERE tenant_id = ? AND (" + " OR ".join(clauses) + ") "
        "ORDER BY created_at, id",
        tuple(params),
    ).fetchall()
    return [_row_dict(cursor, row) for row in rows]


def _insert_ai_document(cursor, columns: set[str], item: dict[str, Any], source: dict[str, Any], version: dict[str, Any], use_pg: bool) -> str:
    tenant_id = _text(item.get("tenant_id")) or "tenant-default"
    v2_document_id = _text(item.get("v2_document_id"))
    document_id = "v1-migrated-" + hashlib.sha256(v2_document_id.encode("utf-8")).hexdigest()[:24]
    normalized = _text(version.get("normalized_content"))
    original = _text(version.get("original_content"))
    content_hash = _valid_hash(version.get("normalized_content_hash")) or _valid_hash(version.get("content_hash"))
    if not content_hash:
        content_hash = _hash_text(normalized or original)
    source_meta = _json_load(source.get("metadata_json"), {})
    version_meta = _json_load(version.get("metadata_json"), {})
    metadata = _metadata_with_precedence(version_meta, source_meta)
    canonical_url = _text(item.get("source_uri")) or _text(source.get("canonical_url"))
    now = _now_iso()
    values: dict[str, Any] = {
        "id": document_id,
        "knowledge_base_id": _knowledge_base_id(cursor, tenant_id),
        "name": _text(item.get("title")) or canonical_url or v2_document_id,
        "source": canonical_url,
        "vendor": _text(metadata.get("vendor")) or "all",
        "platform": _text(metadata.get("platform_code")) or "all",
        "version": _text((metadata.get("version_scope") or {}).get("primary")) if isinstance(metadata.get("version_scope"), dict) else "",
        "status": "active" if normalized else _status(item.get("status"), "active"),
        "created_at": _text(item.get("created_at")) or now,
        "updated_at": _text(item.get("updated_at")) or now,
        "tenant_id": tenant_id,
        "acl_json": _json_value(_json_load(item.get("acl_json"), {}), use_pg),
        "source_trust_level": _text(item.get("trust_level")) or "official",
        "knowledge_source_type": "official_url" if canonical_url else "user_document",
        "metadata_json": _json_value(metadata, use_pg),
        "normalized_content": normalized,
        "content_hash": content_hash,
        "document_id": v2_document_id,
        "document_category": _text(metadata.get("document_category")) or _text(item.get("document_kind")),
        "product_family": _text(metadata.get("product_family")),
        "product_series": _text(metadata.get("product_series")),
        "product_model": _text(metadata.get("product_model")),
        "os_family": _text(metadata.get("os_family")),
        "os_generation": _text(metadata.get("os_generation")),
        "software_train": _text(metadata.get("software_train")),
        "software_release": _text(metadata.get("software_release")),
        "cli_platform": _text(metadata.get("platform_code")),
        "verification_level": _text(item.get("trust_level")) or "official",
        "original_content": original,
        "ingestion_status": "ready" if normalized else "needs_reindex",
        "canonical_url": canonical_url,
        "source_kind": _text(item.get("source_kind")) or _text(source.get("source_kind")),
        "source_content_hash": _text(source.get("content_hash")) or _text(version.get("content_hash")),
        "source_fetched_at": version.get("fetched_at") or source.get("fetched_at"),
        "source_etag": _text(source.get("source_etag")),
        "source_last_modified": _text(source.get("source_last_modified")),
        "source_http_status": source.get("http_status"),
        "source_byte_size": max(0, int(source.get("byte_size") or version.get("byte_size") or 0)),
        "source_parser_name": _text(version.get("parser_name")) or _text(source.get("parser_name")),
        "source_parser_version": _text(version.get("parser_version")) or _text(source.get("parser_version")),
        "source_raw_content_ref": _text(source.get("raw_content_ref")),
        "source_validation_status": _text(source.get("validation_status")) or "unvalidated",
        "lifecycle_status": _status(item.get("lifecycle_status") or item.get("status")),
        "lifecycle_revision": max(0, int(item.get("lifecycle_revision") or 0)),
    }
    filtered = {key: value for key, value in values.items() if key in columns}
    names = list(filtered)
    placeholders = ", ".join("?" for _ in names)
    cursor.execute(
        f"INSERT INTO ai_document ({', '.join(names)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
        tuple(filtered[name] for name in names),
    )
    return document_id


def _update_document(cursor, columns: set[str], target: dict[str, Any], item: dict[str, Any], source: dict[str, Any], version: dict[str, Any], use_pg: bool) -> None:
    source_meta = _json_load(source.get("metadata_json"), {})
    version_meta = _json_load(version.get("metadata_json"), {})
    metadata = _metadata_with_precedence(target.get("metadata_json"), _metadata_with_precedence(version_meta, source_meta))
    canonical_url = _text(item.get("source_uri")) or _text(source.get("canonical_url")) or _text(target.get("source"))
    source_hash = _text(source.get("content_hash")) or _text(version.get("content_hash"))
    values: dict[str, Any] = {
        "canonical_url": canonical_url,
        "source_kind": _text(item.get("source_kind")) or _text(source.get("source_kind")),
        "source_content_hash": source_hash,
        "source_fetched_at": version.get("fetched_at") or source.get("fetched_at"),
        "source_etag": _text(source.get("source_etag")),
        "source_last_modified": _text(source.get("source_last_modified")),
        "source_http_status": source.get("http_status"),
        "source_byte_size": max(0, int(source.get("byte_size") or version.get("byte_size") or 0)),
        "source_parser_name": _text(version.get("parser_name")) or _text(source.get("parser_name")),
        "source_parser_version": _text(version.get("parser_version")) or _text(source.get("parser_version")),
        "source_raw_content_ref": _text(source.get("raw_content_ref")),
        "source_validation_status": _text(source.get("validation_status")) or "unvalidated",
        "lifecycle_status": _status(item.get("lifecycle_status") or item.get("status")),
        "lifecycle_revision": max(0, int(item.get("lifecycle_revision") or 0)),
        "metadata_json": _json_value(metadata, use_pg),
    }
    filtered = {key: value for key, value in values.items() if key in columns}
    if not filtered:
        return
    assignments = ", ".join(f"{key} = ?" for key in filtered)
    cursor.execute(
        f"UPDATE ai_document SET {assignments} WHERE id = ? AND tenant_id = ?",
        tuple(filtered.values()) + (_text(target.get("id")), _text(item.get("tenant_id")) or "tenant-default"),
    )


def _insert_revision(cursor, revision: dict[str, Any], use_pg: bool) -> None:
    exists = cursor.execute(
        "SELECT 1 FROM ai_document_revision WHERE tenant_id = ? AND id = ?",
        (revision["tenant_id"], revision["id"]),
    ).fetchone()
    if exists:
        return
    names = list(revision)
    placeholders = ", ".join("?" for _ in names)
    cursor.execute(
        f"INSERT INTO ai_document_revision ({', '.join(names)}) VALUES ({placeholders})",
        tuple(revision[name] for name in names),
    )


def _revision_from_v2(target_id: str, item: dict[str, Any], source: dict[str, Any], version: dict[str, Any], use_pg: bool, current: bool) -> dict[str, Any]:
    metadata = _metadata_with_precedence(version.get("metadata_json"), source.get("metadata_json"))
    now = _now_iso()
    return {
        "id": _encode_revision_id(_text(version.get("v2_version_id")), target_id),
        "tenant_id": _text(item.get("tenant_id")) or "tenant-default",
        "document_id": target_id,
        "revision_no": max(1, int(version.get("version_no") or 1)),
        "canonical_url": _text(item.get("source_uri")) or _text(source.get("canonical_url")),
        "source_kind": _text(item.get("source_kind")) or _text(source.get("source_kind")),
        "fetch_url": _text(source.get("fetch_url")) or _text(item.get("source_uri")),
        "content_hash": _text(source.get("content_hash")) or _text(version.get("content_hash")),
        "normalized_content_hash": _text(version.get("normalized_content_hash")),
        "original_content": _text(version.get("original_content")),
        "normalized_content": _text(version.get("normalized_content")),
        "metadata_json": _json_value(metadata, use_pg),
        "source_metadata_json": _json_value(_json_load(source.get("metadata_json"), {}), use_pg),
        "fetch_metadata_json": _json_value({
            "error_code": _text(source.get("error_code")),
            "error": _json_load(source.get("error_json"), {}),
            "verification_method": _text(source.get("verification_method")),
        }, use_pg),
        "parser_name": _text(version.get("parser_name")) or _text(source.get("parser_name")),
        "parser_version": _text(version.get("parser_version")) or _text(source.get("parser_version")),
        "cleaner_name": _text(version.get("cleaner_name")),
        "cleaner_version": _text(version.get("cleaner_version")),
        "mime_type": _text(version.get("mime_type")) or _text(source.get("response_content_type")),
        "byte_size": max(0, int(source.get("byte_size") or version.get("byte_size") or 0)),
        "source_etag": _text(source.get("source_etag")),
        "source_last_modified": _text(source.get("source_last_modified")),
        "http_status": source.get("http_status"),
        "fetched_at": version.get("fetched_at") or source.get("fetched_at") or now,
        "status": _status(version.get("status")),
        "lifecycle_status": _status(version.get("lifecycle_status") or version.get("status")),
        "lifecycle_reason": _text(version.get("lifecycle_reason")),
        "is_current": bool(current),
        "legacy_source_id": _text(source.get("v2_source_id")),
        "legacy_source_version_id": _text(source.get("v2_source_version_id")),
        "legacy_document_id": _text(item.get("v2_document_id")),
        "legacy_document_version_id": _text(version.get("v2_version_id")),
        "created_at": _text(version.get("created_at")) or _text(source.get("created_at")) or now,
        "created_by": _text(version.get("created_by")) or _text(source.get("created_by")) or "migration",
    }


def _revision_from_v1(cursor, row: dict[str, Any], use_pg: bool) -> dict[str, Any]:
    normalized = _text(row.get("normalized_content"))
    original = _text(row.get("original_content"))
    content_hash = _valid_hash(row.get("content_hash")) or _hash_text(normalized or original)
    status = _status(row.get("status"))
    return {
        "id": _encode_revision_id("v1-current", _text(row.get("id"))),
        "tenant_id": _text(row.get("tenant_id")) or "tenant-default",
        "document_id": _text(row.get("id")),
        "revision_no": 1,
        "canonical_url": _text(row.get("canonical_url")) or _text(row.get("source")),
        "source_kind": _text(row.get("source_kind")) or _text(row.get("knowledge_source_type")),
        "fetch_url": _text(row.get("source")),
        "content_hash": content_hash,
        "normalized_content_hash": content_hash,
        "original_content": original,
        "normalized_content": normalized,
        "metadata_json": _json_value(_json_load(row.get("metadata_json"), {}), use_pg),
        "source_metadata_json": _json_value({}, use_pg),
        "fetch_metadata_json": _json_value({}, use_pg),
        "parser_name": "",
        "parser_version": _text(row.get("parser_version")),
        "cleaner_name": "",
        "cleaner_version": "",
        "mime_type": "",
        "byte_size": 0,
        "source_etag": _text(row.get("source_etag")),
        "source_last_modified": _text(row.get("source_last_modified")),
        "http_status": row.get("source_http_status"),
        "fetched_at": row.get("source_fetched_at") or row.get("updated_at") or _now_iso(),
        "status": status,
        "lifecycle_status": _status(row.get("lifecycle_status"), status),
        "lifecycle_reason": _text(row.get("lifecycle_reason")),
        "is_current": True,
        "legacy_source_id": "",
        "legacy_source_version_id": "",
        "legacy_document_id": "",
        "legacy_document_version_id": "",
        "created_at": _text(row.get("created_at")) or _now_iso(),
        "created_by": "migration",
    }


def _backfill_v2(cursor, columns: set[str], use_pg: bool) -> set[str]:
    required = {
        "kb_document",
        "kb_document_version",
        "kb_source_registry",
        "kb_source_version",
    }
    if not all(_table_exists(cursor, table, use_pg) for table in required):
        return set()
    rows = cursor.execute(
        """
        SELECT
            d.id AS v2_document_id, d.tenant_id, d.collection_id,
            d.source_registry_id, d.canonical_key, d.title, d.description,
            d.source_uri, d.trust_level, d.acl_json AS document_acl_json,
            d.metadata_json AS document_metadata_json, d.current_version_id,
            d.source_kind, d.status AS document_status, d.lifecycle_status,
            d.lifecycle_revision, d.lifecycle_reason, d.created_at AS document_created_at,
            d.updated_at AS document_updated_at, d.created_by AS document_created_by,
            v.id AS v2_version_id, v.version_no, v.original_content,
            v.normalized_content, v.content_hash, v.normalized_content_hash,
            v.metadata_json AS version_metadata_json, v.parser_name,
            v.parser_version, v.trust_level AS version_trust_level,
            v.status AS version_status, v.mime_type, v.byte_size,
            v.fetched_at, v.lifecycle_status AS version_lifecycle_status,
            v.lifecycle_reason AS version_lifecycle_reason,
            v.created_at AS version_created_at, v.created_by AS version_created_by,
            sr.id AS v2_source_id, sr.source_kind AS registry_source_kind,
            sr.canonical_url, sr.trust_level AS source_trust_level,
            sr.validation_status, sr.metadata_json AS source_metadata_json,
            sr.created_at AS source_created_at, sr.created_by AS source_created_by,
            sv.id AS v2_source_version_id, sv.fetch_url, sv.content_hash AS source_content_hash,
            sv.fetched_at AS source_fetched_at, sv.byte_size AS source_byte_size,
            sv.parser_name AS source_parser_name, sv.parser_version AS source_parser_version,
            sv.source_etag, sv.source_last_modified, sv.http_status,
            sv.raw_content_ref, sv.response_content_type, sv.error_code,
            sv.error_json, sv.verification_method, sv.created_at AS source_version_created_at,
            sv.created_by AS source_version_created_by
        FROM kb_document AS d
        LEFT JOIN kb_document_version AS v
          ON v.tenant_id = d.tenant_id AND v.document_id = d.id
        LEFT JOIN kb_source_registry AS sr
          ON sr.tenant_id = d.tenant_id AND sr.id = d.source_registry_id
        LEFT JOIN kb_source_version AS sv
          ON sv.tenant_id = d.tenant_id AND sv.id = v.source_version_id
        ORDER BY d.id, v.version_no, v.id
        """
    ).fetchall()
    targets_by_v2_document: dict[str, list[dict[str, Any]]] = {}
    migrated_document_ids: set[str] = set()
    for raw_row in rows:
        row = _row_dict(cursor, raw_row)
        v2_document_id = _text(row.get("v2_document_id"))
        if not v2_document_id:
            continue
        if v2_document_id not in targets_by_v2_document:
            urls = [_text(row.get("source_uri")), _text(row.get("canonical_url"))]
            targets = _target_documents(
                cursor,
                columns,
                _text(row.get("tenant_id")) or "tenant-default",
                v2_document_id,
                list(dict.fromkeys(url for url in urls if url)),
            )
            item = {
                "v2_document_id": v2_document_id,
                "tenant_id": _text(row.get("tenant_id")) or "tenant-default",
                "source_uri": _text(row.get("source_uri")),
                "source_kind": _text(row.get("source_kind")) or _text(row.get("registry_source_kind")),
                "title": _text(row.get("title")),
                "trust_level": _text(row.get("trust_level")) or _text(row.get("source_trust_level")),
                "status": row.get("document_status"),
                "lifecycle_status": row.get("lifecycle_status"),
                "lifecycle_revision": row.get("lifecycle_revision"),
                "lifecycle_reason": row.get("lifecycle_reason"),
                "created_at": row.get("document_created_at"),
                "updated_at": row.get("document_updated_at"),
                "created_by": row.get("document_created_by"),
                "acl_json": row.get("document_acl_json"),
                "document_kind": row.get("document_kind"),
            }
            source = {
                "v2_source_id": row.get("v2_source_id") or row.get("source_registry_id"),
                "source_kind": row.get("registry_source_kind") or row.get("source_kind"),
                "canonical_url": row.get("canonical_url"),
                "trust_level": row.get("source_trust_level"),
                "validation_status": row.get("validation_status"),
                "metadata_json": row.get("source_metadata_json"),
                "created_at": row.get("source_created_at"),
                "created_by": row.get("source_created_by"),
            }
            version = {
                "normalized_content": row.get("normalized_content"),
                "original_content": row.get("original_content"),
                "content_hash": row.get("content_hash"),
                "normalized_content_hash": row.get("normalized_content_hash"),
                "metadata_json": row.get("version_metadata_json"),
                "parser_name": row.get("parser_name"),
                "parser_version": row.get("parser_version"),
            }
            if not targets:
                generated_id = _insert_ai_document(cursor, columns, item, source, version, use_pg)
                targets = _target_documents(cursor, columns, item["tenant_id"], v2_document_id, [item["source_uri"], source["canonical_url"]])
                if not targets:
                    targets = [{"id": generated_id, "tenant_id": item["tenant_id"], "metadata_json": "{}", "source": item["source_uri"]}]
            targets_by_v2_document[v2_document_id] = targets

        item = {
            "v2_document_id": v2_document_id,
            "tenant_id": _text(row.get("tenant_id")) or "tenant-default",
            "source_uri": _text(row.get("source_uri")),
            "source_kind": _text(row.get("source_kind")) or _text(row.get("registry_source_kind")),
            "title": _text(row.get("title")),
            "trust_level": _text(row.get("trust_level")) or _text(row.get("source_trust_level")),
            "status": row.get("document_status"),
            "lifecycle_status": row.get("lifecycle_status"),
            "lifecycle_revision": row.get("lifecycle_revision"),
            "lifecycle_reason": row.get("lifecycle_reason"),
        }
        source = {
            "v2_source_id": row.get("v2_source_id") or row.get("source_registry_id"),
            "v2_source_version_id": row.get("v2_source_version_id") or "",
            "source_kind": row.get("registry_source_kind") or row.get("source_kind"),
            "canonical_url": row.get("canonical_url"),
            "trust_level": row.get("source_trust_level"),
            "validation_status": row.get("validation_status"),
            "metadata_json": row.get("source_metadata_json"),
            "content_hash": row.get("source_content_hash"),
            "fetched_at": row.get("source_fetched_at"),
            "byte_size": row.get("source_byte_size"),
            "parser_name": row.get("source_parser_name"),
            "parser_version": row.get("source_parser_version"),
            "source_etag": row.get("source_etag"),
            "source_last_modified": row.get("source_last_modified"),
            "http_status": row.get("http_status"),
            "raw_content_ref": row.get("raw_content_ref"),
            "fetch_url": row.get("fetch_url"),
            "response_content_type": row.get("response_content_type"),
            "error_code": row.get("error_code"),
            "error_json": row.get("error_json"),
            "verification_method": row.get("verification_method"),
            "created_at": row.get("source_version_created_at"),
            "created_by": row.get("source_version_created_by"),
        }
        version = {
            "v2_version_id": row.get("v2_version_id"),
            "version_no": row.get("version_no"),
            "original_content": row.get("original_content"),
            "normalized_content": row.get("normalized_content"),
            "content_hash": row.get("content_hash"),
            "normalized_content_hash": row.get("normalized_content_hash"),
            "metadata_json": row.get("version_metadata_json"),
            "parser_name": row.get("parser_name"),
            "parser_version": row.get("parser_version"),
            "cleaner_name": "",
            "cleaner_version": "",
            "mime_type": row.get("mime_type"),
            "byte_size": row.get("byte_size"),
            "fetched_at": row.get("fetched_at"),
            "status": row.get("version_status"),
            "lifecycle_status": row.get("version_lifecycle_status"),
            "lifecycle_reason": row.get("version_lifecycle_reason"),
            "created_at": row.get("version_created_at"),
            "created_by": row.get("version_created_by"),
        }
        for target in targets_by_v2_document[v2_document_id]:
            target_id = _text(target.get("id"))
            if not target_id:
                continue
            _update_document(cursor, columns, target, item, source, version, use_pg)
            if _text(version.get("v2_version_id")):
                _insert_revision(
                    cursor,
                    _revision_from_v2(
                        target_id,
                        {**item, "source_uri": item["source_uri"]},
                        source,
                        version,
                        use_pg,
                        _text(row.get("current_version_id")) == _text(row.get("v2_version_id")),
                    ),
                    use_pg,
                )
            migrated_document_ids.add(target_id)
    return migrated_document_ids


def _backfill_existing_v1(cursor, columns: set[str], migrated_document_ids: set[str], use_pg: bool) -> None:
    rows = cursor.execute("SELECT * FROM ai_document ORDER BY created_at, id").fetchall()
    for raw_row in rows:
        row = _row_dict(cursor, raw_row)
        document_id = _text(row.get("id"))
        tenant_id = _text(row.get("tenant_id")) or "tenant-default"
        if not document_id or document_id in migrated_document_ids:
            continue
        exists = cursor.execute(
            "SELECT 1 FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? LIMIT 1",
            (tenant_id, document_id),
        ).fetchone()
        if exists:
            continue
        _insert_revision(cursor, _revision_from_v1(cursor, row, use_pg), use_pg)


def upgrade(cursor, use_pg: bool) -> None:
    columns = _ensure_document_columns(cursor, use_pg)
    _create_revision_table(cursor, use_pg)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_document_canonical_url "
        "ON ai_document(tenant_id, canonical_url)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_document_source_content_hash "
        "ON ai_document(tenant_id, source_content_hash)"
    )
    migrated_document_ids = _backfill_v2(cursor, columns, use_pg)
    _backfill_existing_v1(cursor, columns, migrated_document_ids, use_pg)


def downgrade(cursor, use_pg: bool) -> None:
    # This is a forward convergence migration.  Removing provenance would
    # discard source history; the cleanup release owns any explicit archival.
    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
