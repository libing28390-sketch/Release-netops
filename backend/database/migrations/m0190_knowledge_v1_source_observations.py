"""Move source-refresh evidence into the V1 provenance stream.

The V2 refresh table is append-only operational evidence.  V1 still needs
that evidence for freshness status, so this migration extends the already
created ``ai_document_revision`` table with an explicit observation record
kind and copies every existing observation into it.  The old table remains
untouched until the runtime reader has been switched and the final cleanup
migration is approved.
"""

from __future__ import annotations

import hashlib
from typing import Any

from . import m0189_knowledge_v1_provenance as _provenance


VERSION = 190
NAME = "knowledge_v1_source_observations"


_OBSERVATION_COLUMNS = {
    "record_type": "TEXT NOT NULL DEFAULT 'document_revision'",
    "observation_outcome": "TEXT NOT NULL DEFAULT ''",
    "detection_type": "TEXT NOT NULL DEFAULT 'none'",
    "error_code": "TEXT NOT NULL DEFAULT ''",
    "replacement_url": "TEXT NOT NULL DEFAULT ''",
    "request_method": "TEXT NOT NULL DEFAULT 'GET'",
    "checked_at": "TIMESTAMPTZ",
    "source_observation_id": "TEXT NOT NULL DEFAULT ''",
    "legacy_action_id": "TEXT NOT NULL DEFAULT ''",
}

_OFFICIAL_SOURCE_KINDS = {
    "official_url",
    "product_page",
    "configuration_guide",
    "command_reference",
    "release_note",
    "troubleshooting_guide",
    "product_support",
}


def _ensure_revision_columns(cursor, use_pg: bool) -> set[str]:
    if not _provenance._table_exists(cursor, "ai_document_revision", use_pg):
        raise RuntimeError("knowledge_v1_source_observations requires ai_document_revision")
    columns = _provenance._columns(cursor, "ai_document_revision", use_pg)
    for name, definition in _OBSERVATION_COLUMNS.items():
        if name in columns:
            continue
        pass
        cursor.execute(f"ALTER TABLE ai_document_revision ADD COLUMN {name} {definition}")
        columns.add(name)
    return columns


def _row_dict(cursor, row: Any) -> dict[str, Any]:
    return _provenance._row_dict(cursor, row)


def _source_placeholder(cursor, source: dict[str, Any], use_pg: bool) -> str:
    tenant_id = _provenance._text(source.get("tenant_id")) or "tenant-default"
    canonical_url = _provenance._text(source.get("canonical_url"))
    seed = f"{tenant_id}:{canonical_url or source.get('id') or 'unknown'}".encode("utf-8")
    document_id = "v1-source-" + hashlib.sha256(seed).hexdigest()[:24]
    existing = cursor.execute(
        "SELECT id FROM ai_document WHERE tenant_id = ? AND id = ?",
        (tenant_id, document_id),
    ).fetchone()
    if existing:
        return _provenance._text(existing[0])

    metadata = _provenance._json_load(source.get("metadata_json"), {})
    if not isinstance(metadata, dict):
        metadata = {}
    policy = _provenance._json_load(source.get("collection_policy_json"), {})
    if isinstance(policy, dict) and policy:
        metadata.setdefault("collection_policy", policy)
    ai_columns = _provenance._columns(cursor, "ai_document", use_pg)
    values: dict[str, Any] = {
        "id": document_id,
        "knowledge_base_id": _provenance._knowledge_base_id(cursor, tenant_id),
        "name": _provenance._text(source.get("name")) or canonical_url or document_id,
        "source": canonical_url,
        "vendor": _provenance._text(metadata.get("vendor")) or "all",
        "platform": _provenance._text(metadata.get("platform_code")) or "all",
        "version": "",
        "status": "active" if _provenance._text(source.get("status")) == "active" else "draft",
        "created_at": _provenance._text(source.get("created_at")) or _provenance._now_iso(),
        "updated_at": _provenance._text(source.get("updated_at")) or _provenance._now_iso(),
        "tenant_id": tenant_id,
        "acl_json": _provenance._json_value({}, use_pg),
        "source_trust_level": _provenance._text(source.get("trust_level")) or "official",
        "knowledge_source_type": "official_url" if _provenance._text(source.get("source_kind")) in _OFFICIAL_SOURCE_KINDS else "internal",
        "metadata_json": _provenance._json_value(metadata, use_pg),
        "document_id": document_id,
        "ingestion_status": "source_only",
        "canonical_url": canonical_url,
        "source_kind": _provenance._text(source.get("source_kind")),
        "source_validation_status": _provenance._text(source.get("validation_status")) or "unvalidated",
        "lifecycle_status": "published" if _provenance._text(source.get("status")) == "active" else "draft",
        "lifecycle_revision": 0,
    }
    filtered = {key: value for key, value in values.items() if key in ai_columns}
    names = list(filtered)
    placeholders = ", ".join("?" for _ in names)
    cursor.execute(
        f"INSERT INTO ai_document ({', '.join(names)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
        tuple(filtered[name] for name in names),
    )
    return document_id


def _resolve_source_document(cursor, source: dict[str, Any], use_pg: bool) -> str:
    tenant_id = _provenance._text(source.get("tenant_id")) or "tenant-default"
    source_id = _provenance._text(source.get("id"))
    if source_id:
        row = cursor.execute(
            "SELECT document_id FROM ai_document_revision "
            "WHERE tenant_id = ? AND legacy_source_id = ? "
            "ORDER BY CASE WHEN record_type = 'document_revision' THEN 0 ELSE 1 END, revision_no "
            "LIMIT 1",
            (tenant_id, source_id),
        ).fetchone()
        if row and _provenance._text(row[0]):
            return _provenance._text(row[0])
    canonical_url = _provenance._text(source.get("canonical_url"))
    if canonical_url:
        row = cursor.execute(
            "SELECT id FROM ai_document WHERE tenant_id = ? "
            "AND (canonical_url = ? OR source = ?) ORDER BY created_at, id LIMIT 1",
            (tenant_id, canonical_url, canonical_url),
        ).fetchone()
        if row:
            return _provenance._text(row[0])
    return _source_placeholder(cursor, source, use_pg)


def _next_revision_no(cursor, tenant_id: str, document_id: str) -> int:
    row = cursor.execute(
        "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM ai_document_revision "
        "WHERE tenant_id = ? AND document_id = ?",
        (tenant_id, document_id),
    ).fetchone()
    return max(1, int(row[0] or 1))


def _insert_observation(cursor, row: dict[str, Any], source: dict[str, Any], document_id: str, use_pg: bool) -> None:
    tenant_id = _provenance._text(row.get("tenant_id")) or "tenant-default"
    observation_id = _provenance._text(row.get("id"))
    if not observation_id:
        return
    if cursor.execute(
        "SELECT 1 FROM ai_document_revision WHERE tenant_id = ? AND source_observation_id = ?",
        (tenant_id, observation_id),
    ).fetchone():
        return

    metadata = _provenance._json_load(row.get("metadata_json"), {})
    error = _provenance._json_load(row.get("error_json"), {})
    version_signal = _provenance._json_load(row.get("version_signal_json"), {})
    fetch_metadata = {
        "error": error if isinstance(error, dict) else {},
        "version_signal": version_signal if isinstance(version_signal, dict) else {},
        "response_content_type": _provenance._text(row.get("response_content_type")),
    }
    now = _provenance._now_iso()
    revision = {
        "id": "v1obs-" + hashlib.sha256(f"{tenant_id}:{observation_id}".encode("utf-8")).hexdigest()[:32],
        "tenant_id": tenant_id,
        "document_id": document_id,
        "revision_no": _next_revision_no(cursor, tenant_id, document_id),
        "canonical_url": _provenance._text(source.get("canonical_url")),
        "source_kind": _provenance._text(source.get("source_kind")),
        "fetch_url": _provenance._text(row.get("fetch_url")),
        "content_hash": _provenance._text(row.get("content_hash")),
        "normalized_content_hash": "",
        "original_content": "",
        "normalized_content": "",
        "metadata_json": _provenance._json_value(metadata if isinstance(metadata, dict) else {}, use_pg),
        "source_metadata_json": _provenance._json_value(_provenance._json_load(source.get("metadata_json"), {}), use_pg),
        "fetch_metadata_json": _provenance._json_value(fetch_metadata, use_pg),
        "parser_name": "",
        "parser_version": "",
        "cleaner_name": "",
        "cleaner_version": "",
        "mime_type": _provenance._text(row.get("response_content_type")),
        "byte_size": max(0, int(row.get("byte_size") or 0)),
        "source_etag": _provenance._text(row.get("source_etag")),
        "source_last_modified": _provenance._text(row.get("source_last_modified")),
        "http_status": row.get("http_status"),
        "fetched_at": row.get("checked_at") or now,
        "status": "observed",
        "lifecycle_status": "observed",
        "lifecycle_reason": "",
        "is_current": False,
        "legacy_source_id": _provenance._text(source.get("id")),
        "legacy_source_version_id": _provenance._text(row.get("source_version_id")),
        "legacy_document_id": "",
        "legacy_document_version_id": "",
        "created_at": _provenance._text(row.get("created_at")) or now,
        "created_by": _provenance._text(row.get("created_by")) or "migration",
        "record_type": "source_observation",
        "observation_outcome": _provenance._text(row.get("outcome")),
        "detection_type": _provenance._text(row.get("detection_type")) or "none",
        "error_code": _provenance._text(row.get("error_code")),
        "replacement_url": _provenance._text(row.get("replacement_url")),
        "request_method": _provenance._text(row.get("request_method")) or "GET",
        "checked_at": row.get("checked_at") or now,
        "source_observation_id": observation_id,
        "legacy_action_id": "",
    }
    names = list(revision)
    placeholders = ", ".join("?" for _ in names)
    cursor.execute(
        f"INSERT INTO ai_document_revision ({', '.join(names)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
        tuple(revision[name] for name in names),
    )


def _backfill_observations(cursor, use_pg: bool) -> None:
    if not _provenance._table_exists(cursor, "kb_source_refresh_observation", use_pg):
        return
    sources = cursor.execute("SELECT * FROM kb_source_registry ORDER BY tenant_id, id").fetchall()
    source_map = {_provenance._text(_row_dict(cursor, row).get("id")): _row_dict(cursor, row) for row in sources}
    rows = cursor.execute(
        "SELECT * FROM kb_source_refresh_observation ORDER BY tenant_id, checked_at, id"
    ).fetchall()
    documents: dict[tuple[str, str], str] = {}
    for raw_row in rows:
        row = _row_dict(cursor, raw_row)
        source_id = _provenance._text(row.get("source_registry_id"))
        source = source_map.get(source_id)
        if not source:
            continue
        key = (_provenance._text(row.get("tenant_id")) or "tenant-default", source_id)
        if key not in documents:
            source["id"] = source_id
            documents[key] = _resolve_source_document(cursor, source, use_pg)
        _insert_observation(cursor, row, source, documents[key], use_pg)


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_revision_columns(cursor, use_pg)
    cursor.execute("DROP INDEX IF EXISTS ux_ai_document_revision_content")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_document_revision_content "
        "ON ai_document_revision(tenant_id, document_id, content_hash) "
        "WHERE content_hash <> '' AND record_type = 'document_revision'"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_document_revision_observation "
        "ON ai_document_revision(tenant_id, document_id, record_type, checked_at DESC)"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_document_revision_source_observation "
        "ON ai_document_revision(tenant_id, source_observation_id) "
        "WHERE source_observation_id <> ''"
    )
    _backfill_observations(cursor, use_pg)


def downgrade(cursor, use_pg: bool) -> None:
    # Observation records are audit evidence. Keep them on downgrade.
    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
