"""Finalize the Knowledge Engine V1 cutover and remove the retired catalog.

The application now reads and writes only the V1 document/revision projection.
This migration is intentionally the destructive boundary: it first preserves
the remaining V2-only source identities, relation facts, lifecycle events,
site alerts, and change-action facts as typed records in ``ai_document_revision``.
It then verifies that every old row has a V1 representation before dropping
the retired tables and PostgreSQL trigger functions.

Historical migration modules are kept for fresh-install replay and audit, but
no runtime schema object from the retired catalog remains after this upgrade.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any, Iterable

from . import m0189_knowledge_v1_provenance as _provenance


VERSION = 191
NAME = "knowledge_v1_finalize_cleanup"


_V2_TABLES = (
    "kb_document_lifecycle_event",
    "kb_document_source",
    "kb_source_change_action",
    "kb_source_refresh_observation",
    "kb_site_anomaly_alert",
    "kb_document_version",
    "kb_document",
    "kb_source_version",
    "kb_source_registry",
    "ai_retrieval_index_shadow_chunk",
    "ai_retrieval_index_generation",
    "ai_retrieval_rollout_flag",
)


def _table_exists(cursor, table: str, use_pg: bool) -> bool:
    return _provenance._table_exists(cursor, table, use_pg)


def _row_dict(cursor, row: Any) -> dict[str, Any]:
    return _provenance._row_dict(cursor, row)


def _text(value: Any) -> str:
    return _provenance._text(value)


def _json_load(value: Any, default: Any = None) -> Any:
    return _provenance._json_load(value, default)


def _json_value(value: Any, use_pg: bool) -> Any:
    return _provenance._json_value(value, use_pg)


def _json_safe(value: Any) -> Any:
    """Convert driver-native timestamps before storing row snapshots as JSON."""

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _now_iso() -> str:
    return _provenance._now_iso()


def _stable_id(prefix: str, *parts: Any) -> str:
    seed = ":".join(_text(item) for item in parts).encode("utf-8")
    return prefix + hashlib.sha256(seed).hexdigest()[:32]


def _next_revision_no(cursor, tenant_id: str, document_id: str) -> int:
    row = cursor.execute(
        "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM ai_document_revision "
        "WHERE tenant_id = ? AND document_id = ?",
        (tenant_id, document_id),
    ).fetchone()
    return max(1, int(row[0] or 1))


def _insert_record(cursor, record: dict[str, Any], use_pg: bool) -> bool:
    if cursor.execute(
        "SELECT 1 FROM ai_document_revision WHERE tenant_id = ? AND id = ?",
        (record["tenant_id"], record["id"]),
    ).fetchone():
        return False
    names = list(record)
    cursor.execute(
        f"INSERT INTO ai_document_revision ({', '.join(names)}) "
        f"VALUES ({', '.join('?' for _ in names)})",
        tuple(record[name] for name in names),
    )
    return True


def _base_record(
    *,
    tenant_id: str,
    document_id: str,
    revision_no: int,
    record_id: str,
    record_type: str,
    metadata: dict[str, Any],
    source_kind: str = "",
    canonical_url: str = "",
    fetch_url: str = "",
    content_hash: str = "",
    normalized_content_hash: str = "",
    original_content: str = "",
    normalized_content: str = "",
    source_metadata: dict[str, Any] | None = None,
    fetch_metadata: dict[str, Any] | None = None,
    parser_name: str = "",
    parser_version: str = "",
    mime_type: str = "",
    byte_size: int = 0,
    source_etag: str = "",
    source_last_modified: str = "",
    http_status: Any = None,
    fetched_at: Any = None,
    status: str = "observed",
    lifecycle_status: str = "observed",
    lifecycle_reason: str = "",
    legacy_source_id: str = "",
    legacy_source_version_id: str = "",
    legacy_document_id: str = "",
    legacy_document_version_id: str = "",
    created_at: Any = None,
    created_by: str = "migration",
    observation_outcome: str = "",
    detection_type: str = "none",
    error_code: str = "",
    replacement_url: str = "",
    request_method: str = "GET",
    checked_at: Any = None,
    source_observation_id: str = "",
    legacy_action_id: str = "",
    use_pg: bool,
) -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": record_id,
        "tenant_id": tenant_id,
        "document_id": document_id,
        "revision_no": revision_no,
        "canonical_url": canonical_url,
        "source_kind": source_kind,
        "fetch_url": fetch_url,
        "content_hash": content_hash,
        "normalized_content_hash": normalized_content_hash,
        "original_content": original_content,
        "normalized_content": normalized_content,
        "metadata_json": _json_value(metadata, use_pg),
        "source_metadata_json": _json_value(source_metadata or {}, use_pg),
        "fetch_metadata_json": _json_value(fetch_metadata or {}, use_pg),
        "parser_name": parser_name,
        "parser_version": parser_version,
        "cleaner_name": "",
        "cleaner_version": "",
        "mime_type": mime_type,
        "byte_size": max(0, int(byte_size or 0)),
        "source_etag": source_etag,
        "source_last_modified": source_last_modified,
        "http_status": http_status,
        "fetched_at": fetched_at or now,
        "status": status or "observed",
        "lifecycle_status": lifecycle_status or status or "observed",
        "lifecycle_reason": lifecycle_reason,
        "is_current": False,
        "legacy_source_id": legacy_source_id,
        "legacy_source_version_id": legacy_source_version_id,
        "legacy_document_id": legacy_document_id,
        "legacy_document_version_id": legacy_document_version_id,
        "created_at": created_at or now,
        "created_by": created_by or "migration",
        "record_type": record_type,
        "observation_outcome": observation_outcome,
        "detection_type": detection_type or "none",
        "error_code": error_code,
        "replacement_url": replacement_url,
        "request_method": request_method or "GET",
        "checked_at": checked_at,
        "source_observation_id": source_observation_id,
        "legacy_action_id": legacy_action_id,
    }


def _source_documents(cursor, use_pg: bool) -> dict[tuple[str, str], str]:
    """Ensure every old source identity has a V1 document identity."""

    result: dict[tuple[str, str], str] = {}
    rows = cursor.execute("SELECT * FROM kb_source_registry ORDER BY tenant_id, id").fetchall()
    for raw_row in rows:
        source = _row_dict(cursor, raw_row)
        tenant_id = _text(source.get("tenant_id")) or "tenant-default"
        source_id = _text(source.get("id"))
        mapped = cursor.execute(
            "SELECT document_id FROM ai_document_revision "
            "WHERE tenant_id = ? AND legacy_source_id = ? "
            "ORDER BY CASE WHEN record_type = 'document_revision' THEN 0 ELSE 1 END, revision_no "
            "LIMIT 1",
            (tenant_id, source_id),
        ).fetchone()
        if mapped:
            document_id = _text(mapped[0])
        else:
            document_id = _m0190_source_placeholder(cursor, source, use_pg)
        result[(tenant_id, source_id)] = document_id

        identity_id = _stable_id("v1src-", tenant_id, source_id)
        metadata = _json_load(source.get("metadata_json"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        metadata = {
            **metadata,
            "source_identity": {
                "source_type": _text(source.get("source_type")),
                "source_kind": _text(source.get("source_kind")),
                "name": _text(source.get("name")),
                "description": _text(source.get("description")),
                "allowed_host": _text(source.get("allowed_host")),
                "allowed_scheme": _text(source.get("allowed_scheme")),
                "allowed_port": source.get("allowed_port"),
                "host_match_mode": _text(source.get("host_match_mode")),
                "trust_level": _text(source.get("trust_level")),
                "collection_policy": _json_load(source.get("collection_policy_json"), {}),
                "status": _text(source.get("status")),
                "fetch_enabled": bool(source.get("fetch_enabled")),
                "policy_version": source.get("policy_version"),
                "policy_hash": _text(source.get("policy_hash")),
                "validation_status": _text(source.get("validation_status")),
                "validation": _json_load(source.get("validation_json"), {}),
                "legal_hold": bool(source.get("legal_hold")),
            },
        }
        record = _base_record(
            tenant_id=tenant_id,
            document_id=document_id,
            revision_no=_next_revision_no(cursor, tenant_id, document_id),
            record_id=identity_id,
            record_type="source_identity",
            metadata=metadata,
            source_kind=_text(source.get("source_kind")),
            canonical_url=_text(source.get("canonical_url")),
            fetch_url=_text(source.get("canonical_url")),
            source_metadata=metadata,
            status=_text(source.get("status")) or "draft",
            lifecycle_status=_text(source.get("status")) or "draft",
            lifecycle_reason=_text(source.get("deletion_reason")) or _text(source.get("disable_reason")),
            legacy_source_id=source_id,
            created_at=source.get("created_at"),
            created_by=_text(source.get("created_by")) or "migration",
            use_pg=use_pg,
        )
        _insert_record(cursor, record, use_pg)
    return result


def _m0190_source_placeholder(cursor, source: dict[str, Any], use_pg: bool) -> str:
    """Call the additive migration helper without importing application code."""

    from . import m0190_knowledge_v1_source_observations as _observations

    return _observations._source_placeholder(cursor, source, use_pg)


def _document_for_legacy(
    cursor,
    tenant_id: str,
    *,
    document_id: str = "",
    document_version_id: str = "",
    source_id: str = "",
    source_documents: dict[tuple[str, str], str],
) -> str | None:
    if document_version_id:
        row = cursor.execute(
            "SELECT document_id FROM ai_document_revision "
            "WHERE tenant_id = ? AND legacy_document_version_id = ? "
            "ORDER BY CASE WHEN record_type = 'document_revision' THEN 0 ELSE 1 END, revision_no LIMIT 1",
            (tenant_id, document_version_id),
        ).fetchone()
        if row:
            return _text(row[0])
    if document_id:
        row = cursor.execute(
            "SELECT document_id FROM ai_document_revision "
            "WHERE tenant_id = ? AND legacy_document_id = ? "
            "ORDER BY CASE WHEN record_type = 'document_revision' THEN 0 ELSE 1 END, revision_no LIMIT 1",
            (tenant_id, document_id),
        ).fetchone()
        if row:
            return _text(row[0])
        row = cursor.execute(
            "SELECT id FROM ai_document WHERE tenant_id = ? AND id = ? LIMIT 1",
            (tenant_id, document_id),
        ).fetchone()
        if row:
            return _text(row[0])
    if source_id:
        mapped = source_documents.get((tenant_id, source_id))
        if mapped:
            return mapped
    row = cursor.execute(
        "SELECT id FROM ai_document WHERE tenant_id = ? ORDER BY created_at, id LIMIT 1",
        (tenant_id,),
    ).fetchone()
    return _text(row[0]) if row else None


def _backfill_document_source_links(cursor, use_pg: bool, source_documents: dict[tuple[str, str], str]) -> set[str]:
    migrated: set[str] = set()
    for raw_row in cursor.execute("SELECT * FROM kb_document_source ORDER BY tenant_id, id").fetchall():
        row = _row_dict(cursor, raw_row)
        tenant_id = _text(row.get("tenant_id")) or "tenant-default"
        source_id = _text(row.get("source_registry_id"))
        document_id = _document_for_legacy(
            cursor,
            tenant_id,
            document_id=_text(row.get("document_id")),
            document_version_id=_text(row.get("document_version_id")),
            source_id=source_id,
            source_documents=source_documents,
        )
        if not document_id:
            raise RuntimeError(f"Cannot map document-source relation {row.get('id')} to V1")
        relation_id = _stable_id("v1link-", tenant_id, row.get("id"))
        metadata = {
            "legacy_relation": {
                key: _json_safe(value)
                for key, value in row.items()
                if key not in {"metadata_json"}
            },
            "metadata": _json_safe(_json_load(row.get("metadata_json"), {})),
        }
        record = _base_record(
            tenant_id=tenant_id,
            document_id=document_id,
            revision_no=_next_revision_no(cursor, tenant_id, document_id),
            record_id=relation_id,
            record_type="document_source_link",
            metadata=metadata,
            canonical_url=_text(row.get("canonical_url")),
            fetch_url=_text(row.get("canonical_url")),
            content_hash=_text(row.get("content_hash")),
            source_metadata={"source_registry_id": source_id},
            status=_text(row.get("status")) or "observed",
            lifecycle_status=_text(row.get("status")) or "observed",
            legacy_source_id=source_id,
            legacy_source_version_id=_text(row.get("source_version_id")),
            legacy_document_id=_text(row.get("document_id")),
            legacy_document_version_id=_text(row.get("document_version_id")),
            created_at=row.get("created_at"),
            created_by=_text(row.get("created_by")) or "migration",
            checked_at=row.get("observed_at"),
            use_pg=use_pg,
        )
        _insert_record(cursor, record, use_pg)
        migrated.add(_text(row.get("id")))
    return migrated


def _backfill_lifecycle_events(cursor, use_pg: bool, source_documents: dict[tuple[str, str], str]) -> set[str]:
    migrated: set[str] = set()
    for raw_row in cursor.execute("SELECT * FROM kb_document_lifecycle_event ORDER BY tenant_id, created_at, id").fetchall():
        row = _row_dict(cursor, raw_row)
        tenant_id = _text(row.get("tenant_id")) or "tenant-default"
        legacy_document_id = _text(row.get("document_id"))
        legacy_version_id = _text(row.get("document_version_id"))
        document_id = _document_for_legacy(
            cursor,
            tenant_id,
            document_id=legacy_document_id,
            document_version_id=legacy_version_id,
            source_documents=source_documents,
        )
        if not document_id:
            raise RuntimeError(f"Cannot map lifecycle event {row.get('id')} to V1")
        metadata = {"legacy_lifecycle_event": _json_safe(row)}
        record = _base_record(
            tenant_id=tenant_id,
            document_id=document_id,
            revision_no=_next_revision_no(cursor, tenant_id, document_id),
            record_id=_stable_id("v1life-", tenant_id, row.get("id")),
            record_type="lifecycle_event",
            metadata=metadata,
            source_kind="lifecycle_event",
            status=_text(row.get("to_status")) or "observed",
            lifecycle_status=_text(row.get("to_status")) or "observed",
            lifecycle_reason=_text(row.get("reason")),
            legacy_document_id=legacy_document_id,
            legacy_document_version_id=legacy_version_id,
            created_at=row.get("created_at"),
            created_by=_text(row.get("actor_id")) or "migration",
            request_method="INTERNAL",
            checked_at=row.get("created_at"),
            legacy_action_id=_text(row.get("id")),
            use_pg=use_pg,
        )
        _insert_record(cursor, record, use_pg)
        migrated.add(_text(row.get("id")))
    return migrated


def _alert_source_id(row: dict[str, Any]) -> str:
    source_ids = _json_load(row.get("source_ids_json"), [])
    if isinstance(source_ids, list):
        for source_id in source_ids:
            if _text(source_id):
                return _text(source_id)
    return ""


def _backfill_site_alerts(cursor, use_pg: bool, source_documents: dict[tuple[str, str], str]) -> set[str]:
    migrated: set[str] = set()
    for raw_row in cursor.execute("SELECT * FROM kb_site_anomaly_alert ORDER BY tenant_id, id").fetchall():
        row = _row_dict(cursor, raw_row)
        tenant_id = _text(row.get("tenant_id")) or "tenant-default"
        source_id = _alert_source_id(row)
        document_id = _document_for_legacy(
            cursor,
            tenant_id,
            source_id=source_id,
            source_documents=source_documents,
        )
        if not document_id:
            raise RuntimeError(f"Cannot map site alert {row.get('id')} to V1")
        metadata = {
            "legacy_site_alert": {
                "id": _text(row.get("id")),
                "host": _text(row.get("host")),
                "alert_code": _text(row.get("alert_code")),
                "severity": _text(row.get("severity")),
                "title": _text(row.get("title")),
                "status": _text(row.get("status")),
                "failure_count": row.get("failure_count"),
                "first_seen_at": row.get("first_seen_at"),
                "last_seen_at": row.get("last_seen_at"),
                "resolved_at": row.get("resolved_at"),
                "source_ids": _json_safe(_json_load(row.get("source_ids_json"), [])),
                "details": _json_safe(_json_load(row.get("details_json"), {})),
            }
        }
        status = _text(row.get("status")) or "open"
        record = _base_record(
            tenant_id=tenant_id,
            document_id=document_id,
            revision_no=_next_revision_no(cursor, tenant_id, document_id),
            record_id=_stable_id("v1alert-", tenant_id, row.get("id")),
            record_type="site_alert",
            metadata=metadata,
            source_kind="site_alert",
            status=status,
            lifecycle_status=status,
            lifecycle_reason=_text(row.get("title")),
            legacy_source_id=source_id,
            created_at=row.get("first_seen_at") or row.get("last_seen_at"),
            created_by="migration",
            error_code=_text(row.get("alert_code")),
            request_method="INTERNAL",
            checked_at=row.get("last_seen_at"),
            use_pg=use_pg,
        )
        _insert_record(cursor, record, use_pg)
        migrated.add(_text(row.get("id")))
    return migrated


def _backfill_change_actions(cursor, use_pg: bool, source_documents: dict[tuple[str, str], str]) -> set[str]:
    migrated: set[str] = set()
    for raw_row in cursor.execute("SELECT * FROM kb_source_change_action ORDER BY tenant_id, id").fetchall():
        row = _row_dict(cursor, raw_row)
        tenant_id = _text(row.get("tenant_id")) or "tenant-default"
        source_id = _text(row.get("source_registry_id"))
        observation = cursor.execute(
            "SELECT document_id FROM ai_document_revision "
            "WHERE tenant_id = ? AND source_observation_id = ? LIMIT 1",
            (tenant_id, _text(row.get("refresh_observation_id"))),
        ).fetchone()
        document_id = _text(observation[0]) if observation else _document_for_legacy(
            cursor,
            tenant_id,
            source_id=source_id,
            source_documents=source_documents,
        )
        if not document_id:
            raise RuntimeError(f"Cannot map source change action {row.get('id')} to V1")
        metadata = {"legacy_source_change_action": _json_safe(row)}
        record = _base_record(
            tenant_id=tenant_id,
            document_id=document_id,
            revision_no=_next_revision_no(cursor, tenant_id, document_id),
            record_id=_stable_id("v1action-", tenant_id, row.get("id")),
            record_type="source_change_action",
            metadata=metadata,
            source_kind="source_change_action",
            status=_text(row.get("status")) or "observed",
            lifecycle_status=_text(row.get("status")) or "observed",
            legacy_source_id=source_id,
            created_at=row.get("created_at"),
            created_by=_text(row.get("created_by")) or "migration",
            detection_type=_text(row.get("detection_type")) or "none",
            error_code=_text(row.get("last_error_code")),
            request_method="INTERNAL",
            checked_at=row.get("updated_at") or row.get("created_at"),
            legacy_action_id=_text(row.get("id")),
            use_pg=use_pg,
        )
        _insert_record(cursor, record, use_pg)
        migrated.add(_text(row.get("id")))
    return migrated


def _backfill_orphan_source_versions(cursor, use_pg: bool, source_documents: dict[tuple[str, str], str]) -> set[str]:
    migrated: set[str] = set()
    for raw_row in cursor.execute("SELECT * FROM kb_source_version ORDER BY tenant_id, id").fetchall():
        row = _row_dict(cursor, raw_row)
        tenant_id = _text(row.get("tenant_id")) or "tenant-default"
        source_version_id = _text(row.get("id"))
        if cursor.execute(
            "SELECT 1 FROM ai_document_revision WHERE tenant_id = ? AND legacy_source_version_id = ? LIMIT 1",
            (tenant_id, source_version_id),
        ).fetchone():
            migrated.add(source_version_id)
            continue
        source_id = _text(row.get("source_registry_id"))
        document_id = _document_for_legacy(
            cursor,
            tenant_id,
            source_id=source_id,
            source_documents=source_documents,
        )
        if not document_id:
            raise RuntimeError(f"Cannot map source version {source_version_id} to V1")
        metadata = {
            "legacy_source_version": {
                key: _json_safe(value)
                for key, value in row.items()
                if key not in {"metadata_json", "error_json"}
            },
            "metadata": _json_safe(_json_load(row.get("metadata_json"), {})),
            "error": _json_safe(_json_load(row.get("error_json"), {})),
        }
        status = _text(row.get("status")) or "observed"
        record = _base_record(
            tenant_id=tenant_id,
            document_id=document_id,
            revision_no=_next_revision_no(cursor, tenant_id, document_id),
            record_id=_stable_id("v1sv-", tenant_id, source_version_id),
            record_type="source_version",
            metadata=metadata,
            source_kind="source_version",
            canonical_url="",
            fetch_url=_text(row.get("fetch_url")),
            content_hash=_text(row.get("content_hash")),
            source_metadata={"source_registry_id": source_id},
            fetch_metadata={
                "error": _json_load(row.get("error_json"), {}),
                "verification_method": _text(row.get("verification_method")),
                "raw_content_storage": _text(row.get("raw_content_storage")),
            },
            parser_name=_text(row.get("parser_name")),
            parser_version=_text(row.get("parser_version")),
            mime_type=_text(row.get("response_content_type")),
            byte_size=row.get("byte_size") or 0,
            source_etag=_text(row.get("source_etag")),
            source_last_modified=_text(row.get("source_last_modified")),
            http_status=row.get("http_status"),
            fetched_at=row.get("fetched_at"),
            status=status,
            lifecycle_status=status,
            legacy_source_id=source_id,
            legacy_source_version_id=source_version_id,
            created_at=row.get("created_at"),
            created_by=_text(row.get("created_by")) or "migration",
            error_code=_text(row.get("error_code")),
            use_pg=use_pg,
        )
        _insert_record(cursor, record, use_pg)
        migrated.add(source_version_id)
    return migrated


def _count(cursor, sql: str, params: Iterable[Any] = ()) -> int:
    row = cursor.execute(sql, tuple(params)).fetchone()
    return int(row[0] or 0)


def _ensure_current_version_projection(cursor, use_pg: bool) -> None:
    """Keep the V1 document identity pointed at its current revision."""

    columns = _provenance._columns(cursor, "ai_document", use_pg)
    if "current_version_id" not in columns:
        definition = "TEXT"
        cursor.execute(f"ALTER TABLE ai_document ADD COLUMN current_version_id {definition}")
    cursor.execute(
        "UPDATE ai_document SET current_version_id = ("
        "SELECT r.id FROM ai_document_revision r "
        "WHERE r.tenant_id = ai_document.tenant_id AND r.document_id = ai_document.id "
        "AND r.record_type = 'document_revision' "
        "ORDER BY r.revision_no DESC, r.created_at DESC, r.id DESC LIMIT 1) "
        "WHERE EXISTS (SELECT 1 FROM ai_document_revision r2 "
        "WHERE r2.tenant_id = ai_document.tenant_id AND r2.document_id = ai_document.id "
        "AND r2.record_type = 'document_revision')"
    )


def _assert_data_gates(
    cursor,
    *,
    migrated_sources: dict[tuple[str, str], str],
    migrated_links: set[str],
    migrated_events: set[str],
    migrated_alerts: set[str],
    migrated_actions: set[str],
    migrated_versions: set[str],
) -> None:
    gates = {
        "source_registry": _count(cursor, "SELECT count(*) FROM kb_source_registry"),
        "source_identity": _count(cursor, "SELECT count(*) FROM ai_document_revision WHERE record_type = 'source_identity' AND legacy_source_id <> ''"),
        "source_version": _count(cursor, "SELECT count(*) FROM kb_source_version"),
        "document_version": _count(cursor, "SELECT count(*) FROM kb_document_version"),
        "document_source": _count(cursor, "SELECT count(*) FROM kb_document_source"),
        "lifecycle_event": _count(cursor, "SELECT count(*) FROM kb_document_lifecycle_event"),
        "site_alert": _count(cursor, "SELECT count(*) FROM kb_site_anomaly_alert"),
        "change_action": _count(cursor, "SELECT count(*) FROM kb_source_change_action"),
    }
    if len(migrated_sources) != gates["source_registry"]:
        raise RuntimeError(f"V1 source identity gate failed: {len(migrated_sources)} != {gates['source_registry']}")
    if gates["source_identity"] < gates["source_registry"]:
        raise RuntimeError("V1 source identity records are incomplete")
    if len(migrated_versions) != gates["source_version"]:
        raise RuntimeError(f"V1 source-version gate failed: {len(migrated_versions)} != {gates['source_version']}")
    if _count(cursor, "SELECT count(*) FROM kb_document_version v WHERE NOT EXISTS (SELECT 1 FROM ai_document_revision r WHERE r.tenant_id = v.tenant_id AND r.legacy_document_version_id = v.id)"):
        raise RuntimeError("V1 document-version gate failed")
    if len(migrated_links) != gates["document_source"]:
        raise RuntimeError(f"V1 document-source gate failed: {len(migrated_links)} != {gates['document_source']}")
    if len(migrated_events) != gates["lifecycle_event"]:
        raise RuntimeError(f"V1 lifecycle-event gate failed: {len(migrated_events)} != {gates['lifecycle_event']}")
    if len(migrated_alerts) != gates["site_alert"]:
        raise RuntimeError(f"V1 site-alert gate failed: {len(migrated_alerts)} != {gates['site_alert']}")
    if len(migrated_actions) != gates["change_action"]:
        raise RuntimeError(f"V1 change-action gate failed: {len(migrated_actions)} != {gates['change_action']}")


def _drop_retired_schema(cursor, use_pg: bool) -> None:
    for table in _V2_TABLES:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
    for function in (
        "kb_source_version_fact_immutable_guard",
        "kb_document_version_fact_immutable_guard",
        "kb_source_refresh_observation_append_only_guard",
        "kb_source_refresh_observation_insert_guard",
        "kb_source_change_action_scope_guard",
    ):
        cursor.execute(f"DROP FUNCTION IF EXISTS {function}()")


def upgrade(cursor, use_pg: bool) -> None:
    if not _table_exists(cursor, "ai_document_revision", use_pg):
        raise RuntimeError("knowledge_v1_finalize_cleanup requires ai_document_revision")
    _ensure_current_version_projection(cursor, use_pg)
    if not _table_exists(cursor, "kb_source_registry", use_pg):
        # A clean database with a partially selected migration history can
        # still complete the V1 migration without creating a retired schema.
        return

    source_documents = _source_documents(cursor, use_pg)
    links = _backfill_document_source_links(cursor, use_pg, source_documents)
    events = _backfill_lifecycle_events(cursor, use_pg, source_documents)
    alerts = _backfill_site_alerts(cursor, use_pg, source_documents)
    actions = _backfill_change_actions(cursor, use_pg, source_documents)
    versions = _backfill_orphan_source_versions(cursor, use_pg, source_documents)
    _assert_data_gates(
        cursor,
        migrated_sources=source_documents,
        migrated_links=links,
        migrated_events=events,
        migrated_alerts=alerts,
        migrated_actions=actions,
        migrated_versions=versions,
    )
    _drop_retired_schema(cursor, use_pg)


def downgrade(cursor, use_pg: bool) -> None:
    # The old catalog is intentionally not recreated on downgrade. Restore
    # from the pre-cutover PostgreSQL backup if rollback is required.
    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
